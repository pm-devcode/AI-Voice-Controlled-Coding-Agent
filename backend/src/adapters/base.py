from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

class FilesystemAdapter(ABC):
    """Abstract adapter for filesystem operations."""
    
    @abstractmethod
    async def read_file(self, file_path: str) -> str:
        """Read content of a file."""
        pass

    @abstractmethod
    async def write_file(self, file_path: str, content: str) -> bool:
        """Write content to a file."""
        pass

    @abstractmethod
    async def list_dir(self, directory_path: str) -> list[str]:
        """List files and directories in a path."""
        pass

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Check if path exists."""
        pass

    @abstractmethod
    async def send_agent_action(
        self, 
        action_type: str, 
        label: str, 
        details: str | None = None,
        status: str = "running",
        call_id: str | None = None,
        interaction_id: str | None = None,
        step_id: str | None = None
    ) -> None:
        """Send a progress/thought message to the UI."""
        pass

    @abstractmethod
    async def log_debug(self, category: str, data: Any, interaction_id: str | None = None, step_id: str | None = None) -> None:
        """Log a debug message to the UI."""
        pass

    @abstractmethod
    async def call_vscode_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Call a specific tool on the VS Code side."""
        pass

    # Additional methods for tool executor
    
    async def list_directory(self, path: str) -> list[str]:
        """Alias for list_dir."""
        return await self.list_dir(path)
    
    async def search_in_files(self, pattern: str, path: str | None = None, is_regex: bool = False) -> str:
        """Search for pattern in files. Override in subclass for VS Code support."""
        return "Search not implemented in this adapter."
    
    async def call_vscode_tool(self, tool_name: str, args: dict) -> str:
        """
        Call a VS Code-specific tool.
        Override in VSCodeAdapter to route to frontend.
        """
        return f"Tool {tool_name} not available in this adapter."
    
    async def run_terminal_command(self, command: str, cwd: str | None = None) -> str:
        """Run a terminal command. Override in subclass for implementation."""
        return "Terminal commands not implemented in this adapter."
