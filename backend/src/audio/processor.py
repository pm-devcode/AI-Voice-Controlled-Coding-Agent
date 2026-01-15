import logging
import asyncio
import numpy as np

from backend.src.audio.buffer import AudioBuffer
from backend.src.audio.vad import VADDetector
from backend.src.audio.transcriber import Transcriber
from backend.src.audio.tts import TTSProcessor
from backend.src.api.messages import StatusMessage, TranscriptMessage, AgentResponseMessage

logger = logging.getLogger(__name__)

class AudioProcessor:
    def __init__(self, send_callback, agent):
        self.send = send_callback
        self.agent = agent
        self.buffer = AudioBuffer()
        self.vad = VADDetector()
        self.transcriber = Transcriber() 
        self.tts = TTSProcessor(send_callback)
        
        # VAD State
        self.is_speaking = False
        self.silence_frames = 0
        self.SILENCE_THRESHOLD_FRAMES = 3 # ~800ms if chunk is 256ms

    async def flush(self) -> str | None:
        """Forces processing of current buffer content."""
        if self.buffer.duration_seconds > 0.2: # Reduced threshold for short commands
            logger.info(f"Flushing audio buffer ({self.buffer.duration_seconds:.2f}s)...")
            return await self._process_full_audio()
        
        logger.debug(f"Flush ignored. Buffer too short ({self.buffer.duration_seconds:.2f}s)")
        self.buffer.clear()
        self.is_speaking = False
        self.silence_frames = 0
        return None

    async def process_chunk(self, b64_chunk: str) -> str | None:
        """
        Processes a chunk of audio. Returns transcribed text if speech ended, else None.
        """
        # 1. Add to buffer
        try:
            chunk_data = self.buffer.add_chunk(b64_chunk)
        except Exception as e:
            logger.error(f"Failed to add chunk to buffer: {e}")
            return None
        
        # 2. VAD Check
        try:
            is_speech = self.vad.is_speech(chunk_data)
        except Exception as e:
            # Fallback if VAD fails
            # logger.error(f"VAD Error: {e}")
            is_speech = True # Assume speech to be safe?
        
        if is_speech:
            if not self.is_speaking:
                self.is_speaking = True
                logger.debug("VAD: Voice activity started.")
                # We do NOT send listening status here if we are using Push-to-Talk logic from UI, 
                # because UI already shows listening.
            self.silence_frames = 0
            return None
        else:
            if self.is_speaking:
                self.silence_frames += 1
                if self.silence_frames > self.SILENCE_THRESHOLD_FRAMES:
                    # End of speech detected (auto-silence detection)
                    self.is_speaking = False
                    logger.info("VAD: Silence detected (Auto-Flush).")
                    return await self._process_full_audio()
            return None

    async def _process_full_audio(self) -> str | None:
        audio_data = self.buffer.get_audio()
        duration = self.buffer.duration_seconds
        
        if duration < 0.5:
             # Too short, ignore
             self.buffer.clear()
             return None

        await self.send(StatusMessage(type="status", status="processing", message="Transcribing..."))
        
        try:
            loop = asyncio.get_running_loop()
            text = await loop.run_in_executor(None, self.transcriber.transcribe, audio_data)
        except Exception as e:
            logger.error(f"Transcription execution failed: {e}")
            await self.send(ErrorMessage(type="error", error="STT Error", message=f"Transcription failed: {str(e)[:100]}"))
            await self.send(StatusMessage(type="status", status="error", message="STT Failed"))
            self.buffer.clear()
            return None
        
        self.buffer.clear()
        
        if text:
            await self.send(TranscriptMessage(type="transcript", text=text, is_final=True))
            return text
        
        return None
