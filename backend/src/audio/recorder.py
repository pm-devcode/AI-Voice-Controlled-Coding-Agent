import sounddevice as sd
import numpy as np
import logging
import asyncio
import threading
from typing import Optional, Callable

logger = logging.getLogger(__name__)

class LocalAudioRecorder:
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.is_recording = False
        self._stream: Optional[sd.InputStream] = None
        self._on_audio_data: Optional[Callable[[np.ndarray], None]] = None
        self._loop = None

    def set_callback(self, callback: Callable[[bytes], None]):
        """Callback that receives raw PCM bytes."""
        self._on_audio_data = callback

    def start(self):
        """Start recording from the default input device."""
        if self.is_recording:
            return

        try:
            # We need to run the callback in the asyncio loop if it's async, 
            # but for now we assume it pushes data to a queue or websocket directly.
            self.is_recording = True
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype='int16',
                callback=self._audio_callback,
                blocksize=4096 
            )
            self._stream.start()
            logger.info("Local audio recording started.")
        except Exception as e:
            logger.error(f"Failed to start local recording: {e}")
            self.is_recording = False
            if self._stream:
                try:
                    self._stream.close()
                except: 
                    pass
                self._stream = None
            raise e

    def stop(self):
        """Stop recording."""
        if not self.is_recording:
            return

        self.is_recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.info("Local audio recording stopped.")

    def get_info(self) -> dict:
        try:
            device_info = sd.query_devices(kind='input')
            return {
                "is_recording": self.is_recording,
                "device_name": device_info.get("name", "Default"),
                "sample_rate": self.sample_rate,
                "channels": self.channels
            }
        except Exception as e:
             return {
                "is_recording": self.is_recording,
                "error": str(e)
            }

    def _audio_callback(self, indata, frames, time, status):
        """Called by sounddevice in a separate thread."""
        if status:
            logger.warning(f"Audio input status: {status}")
        
        if self.is_recording and self._on_audio_data:
            # indata is a numpy array (frames, channels)
            # We need bytes
            audio_bytes = indata.tobytes()
            self._on_audio_data(audio_bytes)

# Singleton instance
_recorder = LocalAudioRecorder()

def get_audio_recorder() -> LocalAudioRecorder:
    return _recorder
