import logging
import sys
import os
import site
from pathlib import Path
from datetime import datetime
from backend.src.config import get_settings

def setup_dll_paths():
    """Add NVIDIA library paths to DLL search path on Windows."""
    if sys.platform != "win32":
        return

    # Helper to find where packages are installed (site-packages)
    paths_to_check = site.getsitepackages()
    paths_to_check.append(site.getusersitepackages())
    
    # Also add current venv site-packages if active
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
         paths_to_check.append(os.path.join(sys.prefix, "Lib", "site-packages"))

    nvidia_libs = ["nvidia/cublas", "nvidia/cudnn"]
    
    for site_pkg in paths_to_check:
        for lib in nvidia_libs:
            # Check for 'bin' or 'lib' folders inside the package
            lib_path = Path(site_pkg) / lib
            if lib_path.exists():
                # Add bin/ to path (usually where DLLs are on Windows)
                bin_path = lib_path / "bin"
                if bin_path.exists():
                    os.add_dll_directory(str(bin_path))
                    os.environ["PATH"] = str(bin_path) + os.pathsep + os.environ["PATH"]
                    # print(f"Added DLL path: {bin_path}")
                
                # Sometimes they might be in root or lib? (Usually bin for nvidia pypi packages)

def setup_logging():
    """
    Setup logging with three separate log files:
    1. backend.log - Standard backend logs (all modules)
    2. chat.log - Conversation history (user messages, agent responses)
    3. debug.log - Debug panel messages (sent to UI debug panel)
    """
    # Fix encoding for Windows Console to avoid UnicodeEncodeErrors
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')

    # Setup DLLs for CUDA
    setup_dll_paths()

    settings = get_settings()
    log_level = settings.LOG_LEVEL.upper()
    
    # Create logs directory
    logs_dir = Path(".vcca") / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    # Timestamp for session
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 1. Standard backend log (console + file)
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        # Avoid double setup
        return

    backend_handler = logging.FileHandler(
        logs_dir / f"backend_{timestamp}.log",
        encoding='utf-8'
    )
    backend_handler.setLevel(getattr(logging, log_level, logging.INFO))
    backend_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            backend_handler
        ]
    )
    
    # 2. Chat conversation log
    chat_logger = logging.getLogger("vcca.chat")
    chat_logger.setLevel(logging.INFO)
    chat_logger.propagate = False  # Don't propagate to root
    
    chat_handler = logging.FileHandler(
        logs_dir / f"chat_{timestamp}.log",
        encoding='utf-8'
    )
    chat_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
    chat_logger.addHandler(chat_handler)
    
    # 3. Debug panel log
    debug_logger = logging.getLogger("vcca.debug")
    debug_logger.setLevel(logging.DEBUG)
    debug_logger.propagate = False  # Don't propagate to root
    
    debug_handler = logging.FileHandler(
        logs_dir / f"debug_{timestamp}.log",
        encoding='utf-8'
    )
    debug_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
    debug_logger.addHandler(debug_handler)
    
    # Set levels for specific third-party libraries if needed to reduce noise
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    
    logging.info(f"Logs initialized: {logs_dir}")
    logging.info(f"  - Backend: backend_{timestamp}.log")
    logging.info(f"  - Chat: chat_{timestamp}.log")
    logging.info(f"  - Debug: debug_{timestamp}.log")


def get_chat_logger():
    """Get the chat conversation logger."""
    return logging.getLogger("vcca.chat")


def get_debug_logger():
    """Get the debug panel logger."""
    return logging.getLogger("vcca.debug")
