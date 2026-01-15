from __future__ import annotations
import logging
import asyncio
import uuid
from typing import Callable, Awaitable, Any
from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart

from backend.src.agent.models import SessionState, ExecutionPlan, StepStatus, Agentmode, TaskStep
from backend.src.agent.state_manager import StateManager
from backend.src.agent.planner import PlannerAgent
from backend.src.agent.agent import VCCAAgent
from backend.src.agent.intent_router import IntentRouter, IntentType
from backend.src.agent.structured_agent import StructuredAgent

logger = logging.getLogger(__name__)

# Feature flag for structured agent
USE_STRUCTURED_AGENT = True


class Orchestrator:
    """
    Manages the execution lifecycle: Planning -> Execution -> State Management -> UI Feedback.
    """
    def __init__(
        self, 
        state_manager: StateManager, 
        planner: PlannerAgent,
        executor_agent: VCCAAgent,
        ui_callback: Callable[[str, Any], Awaitable[None]] # type, payload
    ):
        self.state_manager = state_manager
        self.planner = planner
        self.agent = executor_agent
        self.ui_callback = ui_callback
        self.intent_router = IntentRouter(adapter=executor_agent.adapter)
        
        # Structured agent for step execution (uses JSON protocol)
        if USE_STRUCTURED_AGENT:
            self.structured_agent = StructuredAgent(executor_agent.adapter, ui_callback=ui_callback)
            logger.info("Using structured agent with JSON protocol for step execution.")
        else:
            self.structured_agent = None
        
        self.state = SessionState()
        
        # Disable state restoration as requested
        # loaded = self.state_manager.load_state()
        # if loaded:
        #    self.state = loaded
        #    logger.info("Restored suspended session state.")
        logger.info("Starting fresh session (persistence disabled).")
    
    async def handle_user_input(self, user_input: str):
        """
        Main entry point for user messages (Phase 1 - blocking).
        Routes based on intent analysis with refined prompt.
        
        Args:
            user_input: Raw user message
        """
        # 1. Analyze intent and refine prompt
        analysis = await self.intent_router.analyze(
            user_input,
            current_plan=self.state.plan,
            chat_history=self.state.chat_history
        )
        
        # 2. Log analysis for debugging
        if hasattr(self.agent, 'adapter'):
            await self.agent.adapter.log_debug("intent_analysis", {
                "original": analysis.original_prompt,
                "refined": analysis.refined_prompt,
                "intent": analysis.intent.value,
                "confidence": analysis.confidence,
                "resolved": analysis.resolved_references,
                "reasoning": analysis.reasoning
            }, interaction_id=self.state.interaction_id)
        
        logger.info(f"Intent: {analysis.intent.value} (confidence: {analysis.confidence})")
        logger.info(f"Refined: {analysis.refined_prompt}")
        logger.info(f"Show plan only: {analysis.show_plan_only}")
        
        # 3. Route based on intent
        match analysis.intent:
            case IntentType.NEW_TASK:
                await self._start_new_task(analysis.refined_prompt, analysis.original_prompt, show_plan_only=analysis.show_plan_only)
            
            case IntentType.CONTINUE_TASK:
                await self._extend_current_plan(analysis.refined_prompt, analysis.original_prompt)
            
            case IntentType.MODIFY_CURRENT:
                await self._modify_plan(analysis.refined_prompt, analysis.original_prompt)
            
            case IntentType.CLARIFICATION:
                await self._answer_question(analysis.refined_prompt, analysis.original_prompt)
            
            case IntentType.CANCEL:
                await self.cancel_task()
            
            case IntentType.CHAT:
                await self._handle_chat(analysis.refined_prompt, analysis.original_prompt)

    async def start_new_task(self, user_input: str):
        """Legacy method - delegates to handle_user_input for backward compatibility."""
        await self.handle_user_input(user_input)

    async def _start_new_task(self, refined_prompt: str, original_prompt: str, show_plan_only: bool = False):
        """Internal: Creates a new plan and starts execution."""
        interaction_id = str(uuid.uuid4())
        
        # 1. Create Plan using refined prompt
        plan = await self.planner.create_plan(
            refined_prompt, 
            interaction_id=interaction_id,
            history=None  # Fresh start for new task planning
        )
        
        self.state.plan = plan
        self.state.interaction_id = interaction_id
        self.state.is_paused = False
        self.state.waiting_for_input = False
        
        # Initialize history with original user message (for natural conversation flow)
        # Format plan as nice Markdown
        steps_md = "\n".join([
            f"**{i+1}. {s.title}**\n   *{s.description}*\n"
            for i, s in enumerate(plan.steps)
        ])
        
        plan_message = f"""I have analyzed your request and created this execution plan:

---

### 🎯 Goal
{plan.refined_goal}

### 📋 Steps
{steps_md}
---

{'✋ **Waiting for your approval to proceed...**' if (show_plan_only or plan.requires_approval) else '▶️ **Executing plan...**'}"""
        
        self.state.chat_history = [
            ModelRequest(parts=[UserPromptPart(content=original_prompt)]),
            # We don't need to put the full plan in chat text history anymore since we have a specialized UI event
            ModelResponse(parts=[TextPart(content="Plan generated.")])
        ]
        
        # Save & Notify
        self._persist()
        # Broadcast PLAN EVENT explicitly for the new UI
        await self.ui_callback("plan_created", plan.model_dump())
        await self._broadcast_plan()
        
        # NOTE: plan_created event is now responsible for showing the UI.
        # We NO LONGER emit a generic chat stream for the plan text.
        # await self.ui_callback("chat_stream", {"chunk": plan_message})
        # await self.ui_callback("chat_complete", {})
        
        # If show_plan_only, stop here and wait for approval
        if show_plan_only:
            self.state.is_paused = True
            self.state.waiting_for_input = True
            self._persist()
            await self.ui_callback("plan_approval_needed", plan.model_dump())
            logger.info("Plan created and presented for approval (show_plan_only=True)")
            return
        
        # Check approval requirement from planner
        if plan.requires_approval:
             self.state.is_paused = True
             self.state.waiting_for_input = True
             self._persist()
             await self.ui_callback("plan_approval_needed", plan.model_dump())
             return

        # Start Loop
        await self._execution_loop()

    async def resume_task(self):
        """Resumes an existing paused/crashed task."""
        if not self.state.plan:
             logger.warning("No plan to resume.")
             return
             
        self.state.is_paused = False
        self._persist()
        await self._broadcast_plan()
        await self._execution_loop()

    async def handle_user_feedback(self, feedback: str):
        """User modified plan or answered a question."""
        if self.state.waiting_for_input:
            # It was a question or approval
            self.state.waiting_for_input = False
            self.state.is_paused = False
            
            # If it was approval check:
            if self.state.plan and self.state.plan.requires_approval:
                 if "no" in feedback.lower() or "stop" in feedback.lower():
                     # Cancel
                     await self.cancel_task()
                     return
                 else:
                     self.state.plan.requires_approval = False # Approved
            
            # TODO: If it was a clarification question, pass feedback to next step context?
            # Ideally we log it in history or modify the next step.
            
            await self._execution_loop()
        else:
            # Interrupting/Changing plan
            logger.info("User interrupted with feedback, replanning...")
            self.state.is_paused = True # Pause current exec if possible? 
            # Actually if loop is running, we can't easily "pause" the running step unless we cancel task.
            # For now, let's assume we update plan for *future* steps.
            
            if self.state.plan:
                new_plan = await self.planner.update_plan(
                    self.state.plan, 
                    feedback, 
                    history=self.state.chat_history
                )
                self.state.plan = new_plan
                self._persist()
                await self._broadcast_plan()
                # If we were paused, resume? Or wait? 
                # Let's wait for explicit "resume" command or assume feedback implies proceed?
                # User asked to change plan, so usually we proceed.
                self.state.is_paused = False
                await self._execution_loop()

    async def _execution_loop(self):
        """Main execution engine."""
        if not self.state.plan:
            return

        steps = self.state.plan.steps
        
        # Find first pending step
        # Note: steps are ordered.
        for step in steps:
            if self.state.is_paused:
                break
                
            if step.status == StepStatus.DONE or step.status == StepStatus.SKIPPED:
                continue
            
            # Ready to run
            logger.info(f"Orchestrator starting step: {step.id} - {step.title}")
            
            step.status = StepStatus.IN_PROGRESS
            self._persist()
            await self._broadcast_update(step.id, step.status)
            
            # [NEW] Notify UI about step start
            await self.ui_callback("step_start", step.model_dump())
            
            # prepare context from previous steps
            context_str = self._build_context()
            
            # Format step execution prompt
            prompt = f"Executing Step {step.id}: {step.title}\n\nTask: {step.description}"
            
            try:
                full_response = ""
                
                # Use structured agent if enabled, otherwise fall back to legacy
                if self.structured_agent:
                    # Convert history for structured agent
                    simple_history = self._get_simple_history()
                    
                    # Structured agent with JSON protocol
                    async for chunk in self.structured_agent.run(
                        prompt,
                        history=simple_history,
                        context=context_str, # Pass context separately
                        interaction_id=self.state.interaction_id,
                        step_id=step.id
                    ):
                        if self.state.is_paused:
                            break
                        
                        full_response += chunk
                        if chunk.strip(): # Avoid sending empty updates
                             pass # Do NOT stream step execution text to UI for structured agent
                             # Chat UI will only show tool usage and final summary
                else:
                    # Legacy: pydantic-ai auto tool execution
                    async for chunk in self.agent.chat_stream(
                        prompt, 
                        history=self.state.chat_history,
                        mode=step.mode, 
                        interaction_id=self.state.interaction_id, 
                        step_id=step.id
                    ):
                        if self.state.is_paused:
                            break
                        
                        full_response += chunk
                        await self.ui_callback("step_output_stream", {"id": step.id, "chunk": chunk})
                
                if self.state.is_paused:
                     step.status = StepStatus.PENDING
                     step.result = full_response + " [PAUSED]"
                     self._persist()
                     await self._broadcast_update(step.id, "paused")
                     break

                # Step Success
                step.result = full_response
                step.status = StepStatus.DONE
                
                # [NEW] Notify UI about step complete
                await self.ui_callback("step_complete", {"id": step.id, "result": step.result})
                
                # Update global chat history with step result
                self.state.chat_history.append(
                    ModelResponse(parts=[TextPart(content=full_response)])
                )
                
                # Record in session memory if available
                if hasattr(self.agent, 'session_memory'):
                    self.agent.session_memory.record_interaction(
                        user_request=step.title,
                        success=True,
                        notes=f"Completed step {step.id}"
                    )

                self._persist()
                await self._broadcast_update(step.id, step.status, result=full_response)
                
            except Exception as e:
                logger.error(f"Step failed: {e}")
                step.status = StepStatus.FAILED
                step.result = str(e)
                self.state.is_paused = True # Stop on error
                self._persist()
                await self._broadcast_update(step.id, step.status)
                
                # Ask user what to do?
                await self.ui_callback("error", f"Step {step.title} failed: {e}. Resume to retry.")
                break

        # 🎯 FINAL SUMMARY after all steps are done
        if not self.state.is_paused and self.state.plan:
            all_done = all(s.status == StepStatus.DONE for s in self.state.plan.steps)
            if all_done:
                logger.info("Plan execution complete. Generating final summary.")
                
                # Build comprehensive context from all step results
                all_results = []
                for s in self.state.plan.steps:
                    if s.result:
                        all_results.append(f"**{s.title}**: {s.result}")
                results_context = "\n\n".join(all_results)
                
                summary_prompt = f"""Wszystkie kroki analizy/zadania zostały wykonane. 

Zebrane wyniki z kroków:
{results_context}

Na podstawie powyższych wyników przygotuj SZCZEGÓŁOWY RAPORT w języku użytkownika (polskim jeśli użytkownik pisał po polsku). 

Raport powinien zawierać:
1. **Cel analizy/zadania** - co było do zrobienia
2. **Kluczowe ustalenia** - najważniejsze odkrycia, fakty, dane (użyj list punktowanych)
3. **Szczegóły techniczne** - jeśli dotyczy: architektura, technologie, struktura projektu (użyj tabel gdzie pasuje)
4. **Wnioski i rekomendacje** - podsumowanie z konkretnymi zaleceniami

Użyj formatowania Markdown: nagłówki ##, listy -, pogrubienia **, tabele gdzie pasuje. Raport powinien być wyczerpujący ale czytelny."""
                
                await self.ui_callback("chat_stream", {"chunk": "\n\n---\n### 🏁 Podsumowanie wykonania\n\n"})
                
                async for chunk in self.agent.chat_stream(
                    summary_prompt,
                    history=self.state.chat_history,
                    mode=Agentmode.FAST_TOOL,
                    interaction_id=self.state.interaction_id
                ):
                    await self.ui_callback("chat_stream", {"chunk": chunk})
                
                await self.ui_callback("chat_complete", {})

    def _build_context(self) -> str:
        """
        Collects results from previous steps with intelligent truncation.
        Prioritizes recent steps and important information.
        """
        if not self.state.plan:
            return ""
        
        ctx_parts = []
        done_steps = [s for s in self.state.plan.steps if s.status == StepStatus.DONE and s.result]
        
        # Give more space to recent steps
        for i, step in enumerate(done_steps):
            is_recent = i >= len(done_steps) - 2  # Last 2 steps get more space
            max_len = 2000 if is_recent else 500
            
            result = step.result or ""
            if len(result) > max_len:
                # Smart truncation: keep beginning and end
                half = max_len // 2
                result = result[:half] + "\n...[truncated]...\n" + result[-half:]
            
            ctx_parts.append(f"### Step '{step.title}' (completed)\n{result}\n")
        
        return "\n".join(ctx_parts)

    def _persist(self):
        self.state_manager.save_state(self.state)
        
    async def _broadcast_plan(self):
        """Sends the full plan to UI."""
        if self.state.plan:
            await self.ui_callback("plan_update", self.state.plan.model_dump())

    async def _broadcast_update(self, step_id: str, status: str, result: str | None = None):
         payload = {"id": step_id, "status": status}
         if result:
             payload["result"] = result
         await self.ui_callback("step_update", payload)

    async def cancel_task(self):
        self.state.plan = None
        self.state.is_paused = False
        self.state_manager.clear_state()
        await self.ui_callback("plan_cancelled", {})
    
    async def _extend_current_plan(self, refined_prompt: str, original_prompt: str):
        """
        Extends current plan with new steps based on additional request.
        """
        if not self.state.plan:
            # No active plan, treat as new task
            logger.info("No active plan to extend, creating new task")
            await self._start_new_task(refined_prompt, original_prompt)
            return
        
        logger.info(f"Extending current plan: {self.state.plan.refined_goal}")
        
        # Add user message to history
        self.state.chat_history.append(
            ModelRequest(parts=[UserPromptPart(content=original_prompt)])
        )
        
        # Extend plan
        extended_plan = await self.planner.extend_plan(
            current_plan=self.state.plan,
            additional_request=refined_prompt,
            interaction_id=self.state.interaction_id,
            history=self.state.chat_history
        )
        
        # Add plan update to history with nice formatting
        new_steps_md = "\n".join([
            f"**{s.id}. {s.title}**\n   *{s.description}*"
            for s in extended_plan.steps[len(self.state.plan.steps):]
        ])
        
        extend_message = f"""✅ I've extended the plan to include your request.

### 🎯 Updated Goal
{extended_plan.refined_goal}

### ➕ New Steps Added
{new_steps_md}"""
        
        self.state.chat_history.append(
            ModelResponse(parts=[TextPart(content=extend_message)])
        )
        
        self.state.plan = extended_plan
        self._persist()
        await self._broadcast_plan()
        
        # Continue execution if not paused
        if not self.state.is_paused:
            await self._execution_loop()
    
    async def _modify_plan(self, refined_prompt: str, original_prompt: str):
        """
        Modifies current plan based on user's change request.
        """
        if not self.state.plan:
            logger.info("No active plan to modify, creating new task")
            await self._start_new_task(refined_prompt, original_prompt)
            return
        
        logger.info(f"Modifying current plan: {self.state.plan.refined_goal}")
        
        # Add user message to history
        self.state.chat_history.append(
            ModelRequest(parts=[UserPromptPart(content=original_prompt)])
        )
        
        # Modify plan
        modified_plan = await self.planner.modify_plan(
            current_plan=self.state.plan,
            modification_request=refined_prompt,
            interaction_id=self.state.interaction_id,
            history=self.state.chat_history
        )
        
        # Add plan update to history with nice formatting
        modified_steps_md = "\n".join([
            f"{'✓' if s.status.value == 'done' else '○'} **{s.id}. {s.title}** *({s.status.value})*"
            for s in modified_plan.steps
        ])
        
        modify_message = f"""✏️ I've updated the plan based on your request.

### 🎯 Updated Goal
{modified_plan.refined_goal}

### 📝 Modified Steps
{modified_steps_md}"""
        
        self.state.chat_history.append(
            ModelResponse(parts=[TextPart(content=modify_message)])
        )
        
        self.state.plan = modified_plan
        self._persist()
        await self._broadcast_plan()
        
        # Continue/restart execution
        if not self.state.is_paused:
            await self._execution_loop()
    
    async def _answer_question(self, refined_prompt: str, original_prompt: str):
        """
        Answers user's question without modifying plan.
        Uses chat mode for direct response.
        """
        logger.info(f"Answering question: {refined_prompt}")
        
        if not self.state.interaction_id:
            self.state.interaction_id = str(uuid.uuid4())

        # Add user question to history
        self.state.chat_history.append(
            ModelRequest(parts=[UserPromptPart(content=original_prompt)])
        )
        
        # Stream response
        full_response = ""
        async for chunk in self.agent.chat_stream(
            refined_prompt,
            history=self.state.chat_history,
            mode=Agentmode.FAST_TOOL,  # Fast mode for questions
            interaction_id=self.state.interaction_id
        ):
            full_response += chunk
            await self.ui_callback("clarification_stream", {"chunk": chunk})
        
        # Notify completion
        await self.ui_callback("clarification_complete", {"response": full_response})
    
    async def _handle_chat(self, refined_prompt: str, original_prompt: str):
        """
        Handles general chat/greeting without creating plan.
        """
        logger.info(f"Handling chat: {refined_prompt}")
        
        if not self.state.interaction_id:
            self.state.interaction_id = str(uuid.uuid4())

        # Add to history
        self.state.chat_history.append(
            ModelRequest(parts=[UserPromptPart(content=original_prompt)])
        )
        
        # Simple greeting response
        full_response = ""
        async for chunk in self.agent.chat_stream(
            refined_prompt,
            history=self.state.chat_history,
            mode=Agentmode.FAST_TOOL,
            interaction_id=self.state.interaction_id
        ):
            full_response += chunk
            await self.ui_callback("chat_stream", {"chunk": chunk})
        
        await self.ui_callback("chat_complete", {"response": full_response})

    def _get_simple_history(self) -> list[dict]:
        """Convert pydantic-ai history to simple dict list for StructuredAgent."""
        simple_history = []
        for msg in self.state.chat_history:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, UserPromptPart):
                        simple_history.append({"role": "user", "content": part.content})
            elif isinstance(msg, ModelResponse):
                for part in msg.parts:
                    if isinstance(part, TextPart):
                        simple_history.append({"role": "assistant", "content": part.content})
        return simple_history
