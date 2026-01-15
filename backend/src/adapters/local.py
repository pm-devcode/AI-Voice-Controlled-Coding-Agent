from __future__ import annotations
import os
import aiofiles
from pathlib import Path
from backend.src.adapters.base import FilesystemAdapter
from backend.src.config import get_settings

class LocalFilesystemAdapter(FilesystemAdapter):
    """Implementation of FileSystemAdapter for local OS filesystem."""

    def __init__(self, root_path: str | None = None):
        # Default to workspace root if not provided, else cwd
        # But we need to use get_settings() potentially
        self.root = Path(root_path or os.getcwd()).resolve()

    async def _resolve_path(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = (self.root / p).resolve()
        
        # Security check: ensure path is within root
        # if not str(p).startswith(str(self.root)): pass
        return p

    async def read_file(self, path: str) -> str:
        abs_path = await self._resolve_path(path)
        async with aiofiles.open(abs_path, mode='r', encoding='utf-8') as f:
            return await f.read()

    async def write_file(self, path: str, content: str) -> bool:
        abs_path = await self._resolve_path(path)
        # Ensure dir exists
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(abs_path, mode='w', encoding='utf-8') as f:
            await f.write(content)
        return True

    async def list_dir(self, path: str) -> list[str]:
        abs_path = await self._resolve_path(path)
        entries = []
        # Not truly async listing but compatible
        if abs_path.is_dir():
            for name in os.listdir(abs_path):
                entries.append(name)
        return entries
        
    async def exists(self, path: str) -> bool:
        abs_path = await self._resolve_path(path)
        return abs_path.exists()

    async def send_agent_action(self, action_type: str, label: str, details: str | None = None, status: str = "running", call_id: str | None = None) -> None:
        # Local adapter doesn't support UI feedback usually, or just logs it
        pass

    async def log_debug(self, category: str, data: Any, interaction_id: str | None = None, step_id: str | None = None) -> None:
         # Just log to console
         print(f"[DEBUG][{category}] {data} (ID: {interaction_id}, Step: {step_id})")

    async def write_file(self, path: str, content: str) -> bool:
        abs_path = await self._resolve_path(path)
        # Ensure directory exists
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(abs_path, mode='w', encoding='utf-8') as f:
            await f.write(content)
        return True

    async def list_dir(self, path: str) -> list[str]:
        abs_path = await self._resolve_path(path)
        return os.listdir(abs_path)

    async def get_workspace_root(self) -> str:
        return str(self.root)
