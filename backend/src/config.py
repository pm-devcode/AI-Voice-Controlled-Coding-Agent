import os
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Core
    BACKEND_HOST: str = "127.0.0.1"
    BACKEND_PORT: int = 8775
    LOG_LEVEL: str = "DEBUG"

    # API Keys
    GEMINI_API_KEY: str | None = None
    ELEVENLABS_API_KEY: str | None = None

    # Model Config
    WHISPER_MODEL: str = "large"
    WHISPER_DEVICE: str = "cuda"
    WHISPER_COMPUTE_TYPE: str = "int8"
    
    # Agent Config
    GEMINI_MODEL_FAST: str = "gemini-2.0-flash" 
    GEMINI_MODEL_THINKING: str = "gemini-2.0-flash" # Use 2.0 flash as thinking/pro substitute as 1.5-pro-002 is not listed
    MAX_CONTEXT_TOKENS: int = 128000

    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    WORKSPACE_ROOT: Path | None = None  # Will be set by client

    # MCP
    MCP_ENABLED: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

@lru_cache()
def get_settings():
    # Try to find .env in current directory, then in backend root
    env_path = Path(".env")
    if not env_path.exists():
        # Fallback to backend root (where src/ is)
        project_root = Path(__file__).resolve().parent.parent.parent
        env_path = project_root / ".env"
    
    settings = Settings(_env_file=env_path if env_path.exists() else None)
    
    # Debug logging (masking private key)
    key = settings.GEMINI_API_KEY
    if key:
        masked_key = key[:4] + "..." + key[-4:] if len(key) > 8 else "****"
        # Since this is a library-like call, we use a temporary print or local logger
        # For now, just ensuring it's loaded.
        pass
    
    return settings
