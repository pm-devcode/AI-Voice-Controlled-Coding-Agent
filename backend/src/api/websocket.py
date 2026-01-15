import asyncio
import logging
import json
import base64
from typing import Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from backend.src.api.messages import (
    IncomingMessage, 
    OutgoingMessage,
    StatusMessage,
    ErrorMessage,
    ConfigMessage,
    AudioChunkMessage,
    TextMessage,
    TranscriptMessage,
    AgentResponseMessage,
    CommandMessage,
    AgentActionMessage,
    DebugMessage
)
from backend.src.config import get_settings
from backend.src.audio.processor import AudioProcessor
from backend.src.audio.tts import TTSProcessor
from backend.src.audio.recorder import get_audio_recorder
from backend.src.agent.agent import VCCAAgent
from backend.src.agent.intent_router import IntentRouter
from backend.src.agent.models import Agentmode
from backend.src.adapters.vscode import VSCodeAdapter
from backend.src.logging_setup import get_chat_logger

router = APIRouter()
logger = logging.getLogger(__name__)
chat_logger = get_chat_logger()  # Separate logger for conversations

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connection accepted.")
    
    recorder = get_audio_recorder()
    
    try:
        settings = get_settings()
        
        async def send_callback(msg: OutgoingMessage):
            try:
                await websocket.send_json(msg.model_dump(exclude_none=True))
            except:
                pass
            
        # --- Components Initialization ---
        # Audio parts first so callback can use it
        from backend.src.api.messages import TTSStatusMessage, ToggleTTSMessage
        
        async def tts_send_callback(data: dict):
            # Map dict back to TTSStatusMessage if it matches
            if data.get("type") == "tts_status":
                 await send_callback(TTSStatusMessage(**data))
            else:
                 # Original fallback for any other message tts might send
                 from backend.src.api.messages import BaseMessage
                 await send_callback(BaseMessage(**data))

        tts_processor = TTSProcessor(tts_send_callback)
        adapter = VSCodeAdapter(send_callback)
        executor_agent = VCCAAgent(adapter) # Executor
        
        from backend.src.agent.state_manager import StateManager
        from backend.src.agent.planner import PlannerAgent
        from backend.src.agent.orchestrator import Orchestrator
        
        state_manager = StateManager()
        planner = PlannerAgent(adapter=adapter)
        
        # Bridge Orchestrator events to WebSocket messages
        async def orchestrator_ui_callback(msg_type: str, payload: Any):
            if msg_type == "plan_update":
                # Send plan structure to UI
                await send_callback(CommandMessage(type="command", command="update_plan", payload=payload))
                
            elif msg_type == "step_update":
                await send_callback(CommandMessage(type="command", command="update_step", payload=payload))
                
                status = payload.get("status")
                # When step is done, flush TTS buffer
                if status == "done" or status == "failed" or status == "paused":
                     await tts_processor.flush()

            elif msg_type == "step_output_stream":
                # Stream content
                chunk = payload["chunk"]
                i_id = orchestrator.state.interaction_id
                await send_callback(AgentResponseMessage(type="response", text=chunk, is_delta=True, id=i_id))
                # Stream to TTS
                await tts_processor.speak_stream(chunk, message_id=i_id)
                # Log to chat (accumulate for complete messages, or log chunks)
                chat_logger.info(f"AGENT_CHUNK: {chunk}")
            
            elif msg_type == "clarification_stream":
                # Question/answer streaming (no plan modification)
                chunk = payload["chunk"]
                i_id = orchestrator.state.interaction_id
                await send_callback(AgentResponseMessage(type="response", text=chunk, is_delta=True, id=i_id))
                await tts_processor.speak_stream(chunk, message_id=i_id)
                chat_logger.info(f"AGENT_CLARIFICATION: {chunk}")
            
            elif msg_type == "clarification_complete":
                # Question answered
                await tts_processor.flush()
                i_id = orchestrator.state.interaction_id
                await send_callback(AgentResponseMessage(type="response", text="", is_delta=False, is_final=True, id=i_id))
                await send_callback(StatusMessage(type="status", status="ready"))
                chat_logger.info("CLARIFICATION_COMPLETE")
            
            elif msg_type == "chat_stream":
                # General chat streaming
                chunk = payload["chunk"]
                i_id = orchestrator.state.interaction_id
                await send_callback(AgentResponseMessage(type="response", text=chunk, is_delta=True, id=i_id))
                await tts_processor.speak_stream(chunk, message_id=i_id)
                chat_logger.info(f"AGENT_CHAT: {chunk}")
            
            elif msg_type == "chat_complete":
                # Chat complete
                await tts_processor.flush()
                i_id = orchestrator.state.interaction_id
                await send_callback(AgentResponseMessage(type="response", text="", is_delta=False, is_final=True, id=i_id))
                await send_callback(StatusMessage(type="status", status="ready"))
                chat_logger.info("CHAT_COMPLETE")
                
            elif msg_type == "plan_approval_needed":
                # Plan was already sent via chat_stream, just send approval command
                await send_callback(CommandMessage(type="command", command="request_approval", payload=payload))
                
            elif msg_type == "error":
                err_msg = str(payload)
                # Correctly construct ErrorMessage with required 'error' field
                await send_callback(ErrorMessage(type="error", error="Agent Error", message=err_msg))
                await tts_processor.speak(f"An error occurred: {err_msg[:50]}")
                
            elif msg_type == "plan_cancelled":
                await send_callback(StatusMessage(type="status", status="ready", message="Plan Cancelled"))
                await tts_processor.speak("Plan cancelled.")
            
            elif msg_type == "agent_action":
                # Forward tool execution events to UI (tool_start, tool_end)
                from backend.src.api.messages import AgentActionMessage
                await send_callback(AgentActionMessage(type="agent_action", **payload))
            
            elif msg_type == "step_start":
                # Notify UI about step starting
                from backend.src.api.messages import StepStartMessage
                await send_callback(StepStartMessage(type="step_start", payload=payload))
            
            elif msg_type == "step_complete":
                # Notify UI about step completion
                from backend.src.api.messages import StepCompleteMessage
                await send_callback(StepCompleteMessage(type="step_complete", payload=payload))
            
            elif msg_type == "plan_created":
                # Send full plan to UI
                from backend.src.api.messages import PlanCreatedMessage
                await send_callback(PlanCreatedMessage(type="plan_created", payload=payload))

        orchestrator = Orchestrator(state_manager, planner, executor_agent, orchestrator_ui_callback)
        
        # Audio parts
        audio_processor = AudioProcessor(send_callback, executor_agent) # Agent dependency might be unused now

        logger.info("Initializing components complete.")
        
        current_task_handler = None

        # --- Audio Queue Setup ---
        audio_queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        
        def recorder_callback(data: bytes):
            try:
                b64 = base64.b64encode(data).decode('utf-8')
                loop.call_soon_threadsafe(audio_queue.put_nowait, b64)
            except Exception as e:
                logger.error(f"Recorder queue error: {e}")
        
        recorder.set_callback(recorder_callback)

        async def process_audio_queue():
            while True:
                b64_data = await audio_queue.get()
                
                if b64_data is None: # FLUSH command
                    text = await audio_processor.flush()
                    if text:
                        await handle_input(text)
                    audio_queue.task_done()
                    continue

                text = await audio_processor.process_chunk(b64_data)
                if text:
                    recorder.stop()
                    await send_message(websocket, CommandMessage(type="command", command="stop_recording"))
                    
                    # Handle Voice Input via Orchestrator
                    await handle_input(text)
                    
                audio_queue.task_done()

        audio_processing_task = asyncio.create_task(process_audio_queue())

        # --- Input Handler ---
        async def handle_input(text: str):
            nonlocal current_task_handler
            try:
                # Log user input to chat log
                chat_logger.info(f"USER: {text}")
                
                # 1. Send Transcript to UI so user sees what they said/typed
                await send_message(websocket, TranscriptMessage(type="transcript", text=text, is_final=True))
                
                # 2. Update status to indicate work in progress
                await send_message(websocket, StatusMessage(type="status", status="working", message="Processing..."))

                # 3. Process with Orchestrator - new routing handles intent classification
                if orchestrator.state.waiting_for_input:
                    await orchestrator.handle_user_feedback(text)
                else:
                    # Use new intent-based routing
                    await orchestrator.handle_user_input(text)
                
                # After task is done (or paused):
                if orchestrator.state.is_paused:
                    await send_message(websocket, StatusMessage(type="status", status="error", message="Paused (Error)"))
                elif orchestrator.state.waiting_for_input:
                    await send_message(websocket, StatusMessage(type="status", status="ready", message="Waiting for input"))
                else:
                    await send_message(websocket, StatusMessage(type="status", status="ready"))
                
            except Exception as e:
                logger.error(f"Input handler error: {e}", exc_info=True)
                chat_logger.error(f"ERROR: {e}")
                await send_message(websocket, ErrorMessage(type="error", error="Internal Error", message=str(e)))

        # Send initial status
        await send_message(websocket, StatusMessage(type="status", status="ready", message="Connected"))
        
        # Test Debug Log
        try:
             await adapter.log_debug("system", "Debug Logs Initialized. If you see this, the pipeline works.")
        except Exception as e:
             logger.error(f"Failed to send test debug log: {e}")

        # Send System Status (Devices)
        system_status = {
            "recorder": recorder.get_info(),
            "tts": tts_processor.get_info(),
            "llm": {
                "provider": "Gemini", 
                "model": settings.GEMINI_MODEL_FAST
            } 
        }
        await send_message(websocket, CommandMessage(type="command", command="system_status", payload=system_status))
        
        # Check for Recovery
        if orchestrator.state.plan:
            # We have a suspended session
            await send_message(websocket, AgentResponseMessage(
                type="response", text="⚠️ **Restored previous session.**\nUse 'resume' to continue or just ask for something new.",
                is_final=True
            ))
            # Send the plan to UI
            await orchestrator._broadcast_plan()
        
        # Check for API Key
        if not settings.GEMINI_API_KEY:
             await send_message(websocket, AgentResponseMessage(
                type="response", 
                text="⚠️ **GEMINI_API_KEY is missing!**", 
                is_final=True
            ))

        while True:
            # We expect JSON messages
            data = await websocket.receive_text()
            
            try:
                payload = json.loads(data)
                msg_type = payload.get("type")

                if msg_type == "start_recording":
                    logger.debug("Received start_recording command.")
                    try:
                        recorder.start()
                        await send_message(websocket, StatusMessage(type="status", status="listening"))
                        logger.debug("Recording started successfully.")
                    except Exception as e:
                        logger.exception("Failed to start recording")
                        await send_message(websocket, ErrorMessage(type="error", error="Audio Error", message=f"Failed to start microphone: {e}"))
                
                elif msg_type == "audio_chunk":
                    msg = AudioChunkMessage(**payload)
                    await audio_queue.put(msg.data)

                elif msg_type == "stop_recording":
                    logger.debug("Received stop_recording command.")
                    recorder.stop()
                    # Queue FLUSH command to process remaining audio
                    await audio_queue.put(None)
                    await send_message(websocket, StatusMessage(type="status", status="ready"))

                elif msg_type == "text_input":
                    msg = TextMessage(**payload)
                    
                    # Check for special commands
                    text_lower = msg.text.strip().lower()
                    
                    # Check if plan is waiting for approval
                    if orchestrator.state.is_paused and orchestrator.state.waiting_for_input and orchestrator.state.plan:
                        if text_lower in ["wykonaj", "wykonaj plan", "approve", "ok", "yes", "start", "run"]:
                            logger.info(f"User approved plan via text: {msg.text}")
                            # Resume execution
                            orchestrator.state.is_paused = False
                            orchestrator.state.waiting_for_input = False
                            await send_message(websocket, StatusMessage(type="status", status="processing", message="Executing plan..."))
                            asyncio.create_task(orchestrator._execution_loop())
                            continue
                        elif text_lower in ["anuluj", "cancel", "reject", "no", "stop"]:
                            logger.info(f"User rejected plan via text: {msg.text}")
                            await orchestrator.cancel_task()
                            await send_message(websocket, AgentResponseMessage(type="response", text="Plan rejected. What would you like to do instead?", is_delta=False))
                            await send_message(websocket, StatusMessage(type="status", status="ready"))
                            continue
                    
                    # Check for "resume" command
                    if text_lower == "resume":
                        asyncio.create_task(orchestrator.resume_task())
                    else:
                        asyncio.create_task(handle_input(msg.text))
                        
                elif msg_type == "stop_generation":
                    # Orchestrator cancel/pause
                    orchestrator.state.is_paused = True 
                    recorder.stop()
                    tts_processor.stop() # Stop playing audio immediately
                
                elif msg_type == "backend_action":
                    action = payload.get("action")
                    if action == "retry":
                         # Retry logic ?
                         await orchestrator.resume_task() # Simple resume for now
                    elif action == "stop":
                         await orchestrator.cancel_task()
                
                elif msg_type == "approve_plan":
                    logger.info("User approved plan")
                    # Resume execution
                    orchestrator.state.is_paused = False
                    orchestrator.state.waiting_for_input = False
                    await send_message(websocket, StatusMessage(type="status", status="processing", message="Executing plan..."))
                    asyncio.create_task(orchestrator._execution_loop())
                
                elif msg_type == "reject_plan":
                    logger.info("User rejected plan")
                    await orchestrator.cancel_task()
                    await send_message(websocket, AgentResponseMessage(type="response", text="Plan rejected. What would you like to do instead?", is_delta=False))
                    await send_message(websocket, StatusMessage(type="status", status="ready"))
                
                elif msg_type == "tool_result":
                    # Tool result from Extension via WebSocket
                    call_id = payload.get("call_id")
                    output = payload.get("output")
                    if call_id:
                        logger.info(f"Received tool_result for call_id: {call_id}")
                        # Pass to VSCode adapter to resolve the pending future
                        adapter.handle_tool_result(call_id, output)
                    else:
                        logger.warning(f"tool_result message missing call_id: {payload}")

                elif msg_type == "config":
                    pass
                
                elif msg_type == "toggle_tts":
                    tts_processor.enabled = payload.get("enabled", True)
                    if not tts_processor.enabled:
                        tts_processor.stop()
                    logger.info(f"TTS toggled to: {tts_processor.enabled}")

                elif msg_type == "stop_generation":
                    # Also stop TTS
                    tts_processor.stop()
                    # And LLM (if implemented)
                    if hasattr(orchestrator, 'cancel_task'):
                        # But stop_generation usually means "stop talking/thinking right now"
                        # Orchestrator might need a more granular stop.
                        pass
                
                else:
                    logger.warning(f"Unknown message type: {msg_type}")

            except ValidationError as e:
                logger.error(f"Validation error: {e}")
            except Exception as e:
                logger.exception("Error processing message")


    except WebSocketDisconnect:
        logger.info("Client disconnected normally.")
        if recorder:
            recorder.stop()
        if 'audio_processing_task' in locals():
            audio_processing_task.cancel()
        if 'tts_processor' in locals():
            await tts_processor.shutdown()
            
    except Exception as e:
        logger.exception("Unexpected error in WebSocket endpoint")
    finally:
        if recorder:
            recorder.stop()
        # Ensure TTS is shut down if we exit via Exception or other means
        if 'tts_processor' in locals() and tts_processor._is_running:
             # _is_running is internal, but safe enough here or just call shutdown again (idempotent-ish)
             try:
                await tts_processor.shutdown()
             except:
                pass

        try:
            await websocket.close()
        except:
            pass

async def send_message(websocket: WebSocket, message: OutgoingMessage):
    await websocket.send_json(message.model_dump(exclude_none=True))

