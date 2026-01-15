from __future__ import annotations
import pytest
import numpy as np
import base64
from unittest.mock import MagicMock, AsyncMock, patch
from backend.src.audio.buffer import AudioBuffer
from backend.src.audio.vad import VADDetector
from backend.src.audio.processor import AudioProcessor


def test_audio_buffer():
    buffer = AudioBuffer(sample_rate=16000)

    # Create 1 second of "silence" in int16 (16000 samples)
    silent_data = np.zeros(16000, dtype=np.int16)
    b64_data = base64.b64encode(silent_data.tobytes()).decode("utf-8")

    chunk = buffer.add_chunk(b64_data)
    assert len(chunk) == 16000
    assert len(buffer.get_audio()) == 16000
    assert buffer.duration_seconds == 1.0

    buffer.clear()
    assert len(buffer.get_audio()) == 0
    assert buffer.duration_seconds == 0.0


@patch("torch.hub.load")
def test_vad_detector(mock_torch_load):
    # Mock Silero VAD
    mock_model = MagicMock()
    mock_utils = (MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
    mock_torch_load.return_value = (mock_model, mock_utils)

    vad = VADDetector()

    # Mock model output (probability 0.9)
    mock_model.return_value = MagicMock(item=lambda: 0.9)

    audio_chunk = np.random.rand(512).astype(np.float32)
    assert vad.is_speech(audio_chunk) is True

    # Mock low probability (0.1)
    mock_model.return_value = MagicMock(item=lambda: 0.1)
    assert vad.is_speech(audio_chunk) is False


@pytest.mark.asyncio
async def test_audio_processor_flow():
    mock_send = AsyncMock()
    mock_agent = MagicMock()

    with (
        patch("backend.src.audio.processor.VADDetector") as MockVAD,
        patch("backend.src.audio.processor.Transcriber") as MockTranscriber,
    ):
        # Setup mocks
        vad_instance = MockVAD.return_value
        vad_instance.is_speech.return_value = True  # Always speech

        transcriber_instance = MockTranscriber.return_value
        transcriber_instance.transcribe.return_value = "Hello agent"

        processor = AudioProcessor(mock_send, mock_agent)

        # Send a larger chunk (1s of audio)
        mock_data = np.zeros(16000, dtype=np.int16)
        mock_chunk = base64.b64encode(mock_data.tobytes()).decode("utf-8")

        # Test process_chunk
        await processor.process_chunk(mock_chunk)
        assert processor.is_speaking is True

        # Test silence detection
        vad_instance.is_speech.return_value = False
        # Push 4 silent chunks to trigger auto-flush (threshold is 3)
        for _ in range(4):
            await processor.process_chunk(mock_chunk)

        # Verify it flushed (transcribe should be called)
        # Note: _process_full_audio ends with transcriber call
        # We need to wait a bit or ensure the executor is handled.
        # Since we mocked Transcriber.transcribe, it should be called via loop.run_in_executor

        # Check if transcript message was sent
        # We might need to wait for the executor if it's async
        assert any(
            call.args[0].type == "transcript" for call in mock_send.call_args_list
        )
