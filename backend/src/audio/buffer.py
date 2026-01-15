import numpy as np
import base64

class AudioBuffer:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.buffer = np.array([], dtype=np.float32)

    def add_chunk(self, b64_chunk: str) -> np.ndarray:
        """
        Decodes base64 PCM data and appends to buffer.
        Returns the decoded numpy array of the chunk.
        """
        # Decode base64
        audio_bytes = base64.b64decode(b64_chunk)
        
        # Convert to numpy array (assuming 16-bit PCM mono)
        # We need to normalize to float32 [-1.0, 1.0] for VAD and Whisper
        audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
        audio_float32 = audio_int16.astype(np.float32) / 32768.0
        
        self.buffer = np.concatenate((self.buffer, audio_float32))
        return audio_float32

    def get_audio(self) -> np.ndarray:
        return self.buffer

    def clear(self):
        self.buffer = np.array([], dtype=np.float32)

    @property
    def duration_seconds(self) -> float:
        return len(self.buffer) / self.sample_rate
