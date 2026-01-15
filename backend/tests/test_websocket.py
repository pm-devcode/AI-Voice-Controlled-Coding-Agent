import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from backend.src.main import app

@pytest.fixture(autouse=True)
def mock_heavy_components():
    with patch("backend.src.api.websocket.VCCAAgent") as MockAgentClass, \
         patch("backend.src.agent.intent_router.IntentRouter") as MockIntentRouter, \
         patch("backend.src.agent.orchestrator.PlannerAgent") as MockPlannerAgent, \
         patch("backend.src.api.websocket.TTSProcessor") as MockTTS, \
         patch("backend.src.api.websocket.AudioProcessor") as MockAudio, \
         patch("backend.src.api.websocket.get_audio_recorder") as MockRecorder, \
         patch("backend.src.audio.vad.VADDetector") as MockVAD:
        
        # Configure mocks
        mock_agent = MockAgentClass.return_value
        mock_agent.adapter = MagicMock()
        mock_agent.adapter.log_debug = AsyncMock()
        mock_agent.load_dynamic_context = AsyncMock()
        mock_agent.chat = AsyncMock(return_value="Mock response")

        # Default Intent Router behavior
        from backend.src.agent.intent_router import IntentAnalysis, IntentType
        instance_router = MockIntentRouter.return_value
        instance_router.analyze = AsyncMock(return_value=IntentAnalysis(
            original_prompt="test",
            refined_prompt="test",
            intent=IntentType.CHAT,
            confidence=1.0,
            reasoning="Testing",
            show_plan_only=False
        ))

        # Default Agent behavior
        async def mock_stream(*args, **kwargs):
            print("DEBUG: mock_stream called")
            yield "Hello"
            yield " world"
        mock_agent.chat_stream.side_effect = mock_stream
        
        # Default TTS behavior
        mock_tts = MockTTS.return_value
        mock_tts.get_info.return_value = {"status": "mock"}
        mock_tts.speak_stream = AsyncMock()
        mock_tts.speak = AsyncMock()
        mock_tts.flush = AsyncMock()
        mock_tts.shutdown = AsyncMock()

        yield {
            "agent": mock_agent,
            "router": instance_router,
            "tts": mock_tts
        }

def test_websocket_connection(mock_heavy_components):
    client = TestClient(app)
    with client.websocket_connect("/ws") as websocket:
        # 1. Drain messages until ready
        while True:
            data = websocket.receive_json()
            if data["type"] == "status" and data["status"] == "ready":
                break
        assert data["status"] == "ready"

def test_websocket_text_input_flow(mock_heavy_components):
    """
    Test the basic flow of text input with a mocked agent.
    """
    mock_agent = mock_heavy_components["agent"]
    
    # Mock Agent chat_stream specifically for this test
    async def mock_stream(*args, **kwargs):
        print("DEBUG: mock_stream called")
        yield "Hello"
        yield " world"
    mock_agent.chat_stream.side_effect = mock_stream

    client = TestClient(app)
    with client.websocket_connect("/ws") as websocket:
        # Skip initial ready
        while True:
            msg = websocket.receive_json()
            if msg["type"] == "status" and msg["status"] == "ready":
                break

        # Send text input
        websocket.send_json(
            {"type": "text_input", "id": "test_cmd", "text": "Hello agent"}
        )

        # 1. Drain until we get chunks OR status working
        chunks = []
        is_working = False
        is_ready = False
        
        for _ in range(50):
            msg = websocket.receive_json()
            print(f"DEBUG RECV: {msg}")
            
            if msg["type"] == "status":
                if msg["status"] == "working":
                    is_working = True
                if msg["status"] == "ready" and is_working:
                    is_ready = True
                    break
            
            if msg["type"] == "response":
                chunks.append(msg["text"])
        
        full_text = "".join(chunks)
        assert is_working
        assert "Hello" in full_text
        assert " world" in full_text
        assert is_ready
