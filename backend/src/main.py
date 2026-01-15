from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from backend.src.config import get_settings
from backend.src.api.websocket import router as websocket_router
from backend.src.audio.transcriber import Transcriber
from backend.src.logging_setup import setup_logging
import asyncio
import logging

# Setup logging before anything else
setup_logging()

logger = logging.getLogger(__name__)
settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schedule model loading in background thread so server accepts connections immediately
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, run_preload)
    yield

app = FastAPI(
    title="VCCA Backend",
    version="0.1.0",
    description="Voice-Controlled Coding Agent Backend",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(websocket_router)

def run_preload():
    """Blocking function to preload model."""
    try:
        logger.info("Starting background model preload...")
        transcriber = Transcriber()
        transcriber.preload()
        logger.info("Background model preload finished.")
    except Exception as e:
        logger.error(f"Background model preload failed: {e}")

@app.get("/health")
async def health_check():
    key = settings.GEMINI_API_KEY
    has_key = key is not None and len(key) > 5
    masked_key = (key[:4] + "..." + key[-4:]) if has_key else None
    
    return {
        "status": "ok", 
        "version": app.version,
        "gemini_api_key_set": has_key,
        "gemini_api_key_val": masked_key,
        "whisper_model": settings.WHISPER_MODEL
    }

if __name__ == "__main__":
    import uvicorn
    import os
    
    reload_mode = os.getenv("BACKEND_RELOAD", "false").lower() == "true"
    
    uvicorn.run(
        "backend.src.main:app", 
        host=settings.BACKEND_HOST, 
        port=settings.BACKEND_PORT, 
        reload=reload_mode
    )
