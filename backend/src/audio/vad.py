import logging
import torch
import numpy as np

logger = logging.getLogger(__name__)

class VADDetector:
    def __init__(self, sample_rate: int = 16000, threshold: float = 0.5):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.model = None
        self.utils = None
        self._load_model()

    def _load_model(self):
        try:
            # Load Silero VAD model
            # We use use_onnx=True if possible for speed, but standard torch is fine for now
            self.model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=False  
            )
            (self.get_speech_timestamps, _, self.read_audio, _, _) = utils
            logger.info("Silero VAD model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Silero VAD model: {e}")
            raise

    def is_speech(self, audio_chunk: np.ndarray) -> bool:
        """
        Check if the given audio chunk contains speech.
        Args:
            audio_chunk: float32 numpy array
        """
        if self.model is None:
            return False

        # Prepare tensor
        tensor = torch.from_numpy(audio_chunk)
        
        # Add batch dimension if needed
        if tensor.ndim == 1:
            tensor = tensor.unsqueeze(0)

        # Get probability
        # Silero expects (batch, samples)
        speech_prob = self.model(tensor, self.sample_rate).item()
        return speech_prob > self.threshold

    def reset(self):
        if self.model:
            self.model.reset_states()
