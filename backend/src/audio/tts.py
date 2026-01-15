import logging
import base64
import edge_tts
import asyncio
import re
import sounddevice as sd
import numpy as np
import io
import soundfile as sf
# from backend.src.api.messages import TTSAudioMessage # No longer sending audio bytes

logger = logging.getLogger(__name__)

class TTSProcessor:
    def __init__(self, send_callback=None):
        # send_callback used to be for WS, now is optional or unused for audio
        self.send = send_callback
        self.voices = {
            "en": "en-US-AndrewNeural",
            "pl": "pl-PL-MarekNeural"
        }
        self.enabled = True
        self._queue = asyncio.Queue()
        self._buffer = ""
        self._is_running = True
        self._current_message_id = None
        self._worker_task = asyncio.create_task(self._process_queue())

    def stop(self):
        """Stop current playback and clear queue."""
        # Clear queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break
        
        self._buffer = ""
        self._current_message_id = None
        sd.stop() # Stop sounddevice immediately
        
        # Notify UI that speaking stopped
        if self.send:
            asyncio.create_task(self.send({"type": "tts_status", "status": "stopped"}))
            
        logger.info("TTS Stopped.")

    async def shutdown(self):
        """Stop worker task and cleanup resources."""
        self._is_running = False
        self.stop()
        
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        logger.info("TTS Processor shut down.")

    async def speak_stream(self, chunk: str, message_id: str = None):
        """Append chunk to buffer and queue complete sentences."""
        if not self.enabled or not chunk: return
        self._buffer += chunk
        
        if message_id:
            self._current_message_id = message_id
        
        # Simple heuristic split: split on [.?!] followed by whitespace or end
        # We want to capture the punctuation too.
        # This regex looks for punctuation followed by space
        while True:
            # Match punctuation that ends a sentence
            match = re.search(r'([.?!]+)(\s+)', self._buffer)
            if match:
                end_idx = match.end()
                sentence = self._buffer[:end_idx].strip()
                if sentence:
                    await self.speak(sentence, message_id=self._current_message_id)
                self._buffer = self._buffer[end_idx:]
            else:
                break
    
    async def flush(self):
        """Flush remaining buffer."""
        if not self.enabled: return
        if self._buffer.strip():
            await self.speak(self._buffer.strip(), message_id=self._current_message_id)
        self._buffer = ""

    async def _process_queue(self):
        logger.info("TTS Worker loop started.")
        while self._is_running:
            try:
                item = await self._queue.get()
                text = item["text"]
                msg_id = item.get("message_id")
                
                if not self.enabled:
                    self._queue.task_done()
                    continue

                lang = self._detect_language(text)
                voice = self.voices.get(lang, self.voices["en"])
                
                # Notify UI started speaking
                if self.send:
                    await self.send({
                        "type": "tts_status", 
                        "status": "started", 
                        "message_id": msg_id
                    })

                try:
                    communicate = edge_tts.Communicate(text, voice)
                    mp3_data = b""
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            mp3_data += chunk["data"]
                    
                    if mp3_data:
                        # Run blocking play in a thread to not block loop
                        await asyncio.to_thread(self._play_local_blocking, mp3_data)
                    
                    # Notify UI finished speaking this part
                    # If queue is empty, we can say it's stopped/idle
                    if self.send and self._queue.empty():
                         await self.send({
                            "type": "tts_status", 
                            "status": "stopped", 
                            "message_id": msg_id
                        })
                except Exception as e:
                    logger.error(f"TTS Synthesis/Playback Error: {e}")
                    if self.send:
                        await self.send({
                            "type": "tts_status", 
                            "status": "error", 
                            "message_id": msg_id,
                            "error": str(e)
                        })

                self._queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"TTS Worker Loop Error: {e}")
                try:
                    self._queue.task_done()
                except:
                    pass

    def _play_local_blocking(self, audio_bytes: bytes):
        """Runs in a separate thread."""
        try:
             data, fs = sf.read(io.BytesIO(audio_bytes))
             sd.play(data, fs)
             sd.wait() # Blocking wait
        except Exception as e:
             logger.error(f"Playback error: {e}")

    def _detect_language(self, text: str) -> str:
        """Simple heuristic to detect if text is Polish or English."""
        # Polish characteristic characters
        pl_chars = re.compile(r'[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]')
        if pl_chars.search(text):
            return "pl"
        
        # Common Polish words
        pl_words = {"jest", "nie", "tak", "cześć", "agent", "kod", "plik", "projekt"}
        words = set(text.lower().split())
        if words.intersection(pl_words):
            return "pl"
            
        return "en"

    def get_info(self) -> dict:
        try:
            device_info = sd.query_devices(kind='output')
            return {
                "engine": "Edge TTS",
                "voices": self.voices,
                "output_device": device_info.get("name", "Default"),
                "status": "ready",
                "enabled": self.enabled
            }
        except Exception as e:
            return {
                "engine": "Edge TTS",
                "error": str(e),
                "enabled": self.enabled
            }

    async def speak(self, text: str, message_id: str = None):
        """
        Queue text for speaking.
        """
        await self._queue.put({"text": text, "message_id": message_id})
        
    # Legacy method removal or update. The old speak implementation is now replaced by queue put.
    # But I need to remove the old implementation from the file if it exists below.
    # The read_file showed the old speak method. I need to make sure I don't implement it twice or leave it.
    
    # Actually, the user asked to REPLACE the old speak logic.
    # My previous tool call replaced __init__ and inserted _process_queue etc BEFORE _detect_language.
    # But the OLD speak method is still DOWN THERE in the file.
    
    # I should use replace_string_in_file or read file to find where to cut.
    # Let's read the file again to see current state.
