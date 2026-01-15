from __future__ import annotations
import os
import logging
from pathlib import Path
from backend.src.adapters.base import FilesystemAdapter

logger = logging.getLogger(__name__)

import aiofiles

class LocalFilesystemAdapter(FilesystemAdapter):
    """Direct disk access for standalone mode."""

    def __init__(self, root_dir: str | Path | None = None):
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()
        logger.info(f"Local FS initialized at: {self.root_dir}")

    def _get_abs_path(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return (self.root_dir / p).resolve()

    async def read_file(self, file_path: str) -> str:
        abs_path = self._get_abs_path(file_path)
        logger.debug(f"Reading file: {abs_path}")
        async with aiofiles.open(abs_path, "r", encoding="utf-8") as f:
            return await f.read()

    async def write_file(self, file_path: str, content: str) -> bool:
        abs_path = self._get_abs_path(file_path)
        logger.info(f"Writing file: {abs_path}")
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(abs_path, "w", encoding="utf-8") as f:
            await f.write(content)
        return True

    async def list_dir(self, directory_path: str) -> list[str]:
        abs_path = self._get_abs_path(directory_path)
        logger.debug(f"Listing dir: {abs_path}")
        return os.listdir(abs_path)

    async def exists(self, path: str) -> bool:
        return self._get_abs_path(path).exists()

    async def send_agent_action(
        self, 
        action_type: str, 
        label: str, 
        details: str | None = None,
        status: str = 'running',
        call_id: str | None = None,
        interaction_id: str | None = None,
        step_id: str | None = None
    ) -> None:
        logger.info(f"AGENT ACTION: {label} ({action_type}) - {status}")

    async def log_debug(
        self, 
        category: str, 
        data: Any, 
        interaction_id: str | None = None, 
        step_id: str | None = None
    ) -> None:
        logger.debug(f"DEBUG [{category}]: {data}")

    async def call_vscode_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        return await self._call_remote_tool(tool_name, **args)

    async def _call_remote_tool(self, tool_name: str, **kwargs) -> Any:
        """Fallback for tools that usually run in VS Code."""
        logger.warning(f"Standalone mode: simulating remote tool '{tool_name}' with {kwargs}")
        
        if tool_name == "search_in_files":
            # Very basic mock implementation
            pattern = kwargs.get("pattern", "")
            return [{"file": "mock.txt", "line": 1, "text": f"Found {pattern}"}]
            
        return f"Mock result for {tool_name}"

