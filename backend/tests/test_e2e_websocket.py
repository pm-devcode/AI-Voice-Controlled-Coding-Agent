import pytest
import asyncio
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
from backend.src.main import app

@pytest.fixture
def mock_e2e_components():
    with patch("backend.src.api.websocket.VCCAAgent") as MockAgentClass, \
         patch("backend.src.agent.intent_router.IntentRouter") as MockIntentRouter, \
         patch("backend.src.agent.intent_router.Agent") as MockPydanticAgent, \
         patch("backend.src.agent.orchestrator.PlannerAgent") as MockPlannerAgent, \
         patch("backend.src.api.websocket.TTSProcessor") as MockTTS, \
         patch("backend.src.api.websocket.AudioProcessor") as MockAudio, \
         patch("backend.src.api.websocket.get_audio_recorder") as MockRecorder, \
         patch("backend.src.audio.vad.VADDetector") as MockVAD:
        
        # Setup Agent Mock
        mock_agent = MockAgentClass.return_value
        mock_agent.adapter = MagicMock()
        mock_agent.adapter.log_debug = AsyncMock()
        mock_agent.load_dynamic_context = AsyncMock()
        mock_agent.chat = AsyncMock(return_value="Mock response")

        # Setup Intent Mock
        from backend.src.agent.intent_router import IntentAnalysis, IntentType
        analysis = IntentAnalysis(
            original_prompt="test",
            refined_prompt="test",
            intent=IntentType.CHAT,
            confidence=1.0,
            reasoning="test",
            show_plan_only=False
        )
        instance_router = MockIntentRouter.return_value
        instance_router.analyze = AsyncMock(return_value=analysis)
        
        # Setup Planner Mock
        instance_planner = MockPlannerAgent.return_value
        instance_planner.create_plan = AsyncMock()
        instance_planner.update_plan = AsyncMock()

        # Setup TTS Mock
        mock_tts = MockTTS.return_value
        mock_tts.speak_stream = AsyncMock()
        mock_tts.speak = AsyncMock()
        mock_tts.flush = AsyncMock()
        mock_tts.shutdown = AsyncMock()
        mock_tts.get_info.return_value = {"status": "mock"}

        yield {
            "agent_class": MockAgentClass,
            "agent": mock_agent,
            "intent_router": instance_router,
            "planner": instance_planner,
            "tts": mock_tts
        }

def test_e2e_websocket_basic_flow(mock_e2e_components):
    """
    Simplified E2E test to verify WebSocket connectivity and basic message exchange.
    """
    mock_agent = mock_e2e_components["agent"]
    
    async def mock_stream(*args, **kwargs):
        yield "Success"
    mock_agent.chat_stream.side_effect = mock_stream

    client = TestClient(app)
    with client.websocket_connect("/ws") as websocket:
        # Drain ready
        for _ in range(20):
            msg = websocket.receive_json()
            if msg.get("status") == "ready":
                break
        
        # Request
        websocket.send_json({"type": "text_input", "text": "Hello"})

        # Check for response
        found_success = False
        for _ in range(50):
            msg = websocket.receive_json()
            if msg.get("type") == "response" and "Success" in msg.get("text", ""):
                found_success = True
            if msg.get("type") == "status" and msg.get("status") == "ready":
                break
        
        assert found_success
