import logging
import os
import numpy as np
from faster_whisper import WhisperModel
from backend.src.config import get_settings

logger = logging.getLogger(__name__)

_model_cache = None

class Transcriber:
    def __init__(self):
        self.settings = get_settings()
        self._model = None

    def preload(self):
        """Forces model loading (and download if needed) to cache."""
        if self._model is None:
            self._model = self._load_model()
            
    def _load_model(self):
        global _model_cache
        if _model_cache is not None:
            return _model_cache

        try:
            logger.info(f"Loading Whisper model: {self.settings.WHISPER_MODEL} on {self.settings.WHISPER_DEVICE}...")
            model = WhisperModel(
                self.settings.WHISPER_MODEL, 
                device=self.settings.WHISPER_DEVICE, 
                compute_type=self.settings.WHISPER_COMPUTE_TYPE
            )
            logger.info("Whisper model loaded.")
            _model_cache = model
            return model
        except Exception as e:
            logger.error(f"Failed to load Whisper model with {self.settings.WHISPER_COMPUTE_TYPE}: {e}")
            
            # 1. Try CUDA with int8 (low VRAM optimized)
            if self.settings.WHISPER_DEVICE == "cuda":
                try:
                    logger.warning("Attempting CUDA fallback with int8 (VRAM efficient)...")
                    model = WhisperModel(
                        self.settings.WHISPER_MODEL, 
                        device="cuda", 
                        compute_type="int8"
                    )
                    logger.info("Whisper model loaded on CUDA (int8).")
                    _model_cache = model
                    return model
                except Exception as e2:
                    logger.error(f"CUDA int8 fallback failed: {e2}")

                # 2. Try CUDA with float32 (last resort for CUDA)
                try:
                    logger.warning("Attempting CUDA fallback with float32...")
                    model = WhisperModel(
                        self.settings.WHISPER_MODEL, 
                        device="cuda", 
                        compute_type="float32"
                    )
                    logger.info("Whisper model loaded on CUDA (float32).")
                    _model_cache = model
                    return model
                except Exception as e3:
                    logger.error(f"CUDA float32 fallback failed: {e3}")

            # 3. Fallback to CPU
            logger.warning("Attempting fallback to CPU int8...")
            try:
                model = WhisperModel(
                    self.settings.WHISPER_MODEL, 
                    device="cpu", 
                    compute_type="int8"
                )
                logger.info("Whisper model loaded on CPU.")
                _model_cache = model
                return model
            except Exception as e3:
                 logger.error(f"CPU fallback failed: {e3}")
                 return None

    def transcribe(self, audio: np.ndarray) -> str:
        """
        Transcribe the given audio array.
        """
        if self._model is None:
            self._model = self._load_model()
            
        if self._model is None:
            raise RuntimeError("Transcriber model failed to load.")

        segments, info = self._model.transcribe(audio, beam_size=5) # Auto-detect language
        
        text = " ".join([segment.text for segment in segments]).strip()
        logger.info(f"Transcibed: '{text}' (prob: {info.language_probability})")
        return text
