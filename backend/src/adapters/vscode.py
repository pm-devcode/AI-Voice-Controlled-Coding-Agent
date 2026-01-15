from __future__ import annotations
import asyncio
import uuid
import json
from typing import Any
from backend.src.adapters.base import FilesystemAdapter
from backend.src.api.messages import ToolUsageMessage, AgentActionMessage, DebugMessage
from backend.src.logging_setup import get_debug_logger

debug_logger = get_debug_logger()  # Separate logger for debug panel

class VSCodeAdapter(FilesystemAdapter):
    """
    Adapter that delegates filesystem operations to the VS Code Extension via WebSocket.
    """

    def __init__(self, send_callback):
        self.send = send_callback
        self._pending_calls: dict[str, asyncio.Future] = {}

    async def _call_remote_tool(self, tool_name: str, **kwargs) -> Any:
        call_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self._pending_calls[call_id] = future

        # Send tool request to frontend
        await self.send(ToolUsageMessage(
            type="tool_usage",
            tool_name=tool_name,
            input_data=kwargs,
            call_id=call_id
        ))

        try:
            # Wait for ToolResultMessage to be processed via handle_tool_result
            # Reduce timeout to 15s to fail faster and avoid prolonged hangs
            return await asyncio.wait_for(future, timeout=15.0)
        except asyncio.TimeoutError:
            del self._pending_calls[call_id]
            # Provide a generic error that encourages the agent to ask the user, not just retry blindly.
            raise Exception(f"Tool call '{tool_name}' timed out after 15s. The frontend might be disconnected.")

    def handle_tool_result(self, call_id: str, output: Any):
        """Called by the WebSocket router when a tool_result arrives."""
        if call_id in self._pending_calls:
            self._pending_calls[call_id].set_result(output)
            del self._pending_calls[call_id]

    async def call_vscode_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Implements the tool calling via WebSocket."""
        return await self._call_remote_tool(tool_name, **args)

    async def read_file(self, file_path: str) -> str:
        return await self._call_remote_tool("read_file", path=file_path)

    async def write_file(self, file_path: str, content: str) -> bool:
        # For VS Code, "write_file" often means a WorkspaceEdit
        result = await self._call_remote_tool("write_file", path=file_path, content=content)
        return result is True or result == "success"

    async def list_dir(self, directory_path: str) -> list[str]:
        return await self._call_remote_tool("list_dir", path=directory_path)

    async def exists(self, path: str) -> bool:
        return await self._call_remote_tool("exists", path=path)

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
        await self.send(AgentActionMessage(
            type="agent_action",
            action_type=action_type,
            action_label=label,
            action_details=details,
            action_status=status,
            call_id=call_id,
            interaction_id=interaction_id,
            step_id=step_id
        ))

    async def log_debug(self, category: str, data: Any, interaction_id: str | None = None, step_id: str | None = None) -> None:
        """Log a debug message to the UI and debug log file."""
        # Send to UI debug panel
        await self.send(DebugMessage(
            type="debug",
            category=category,
            data=data,
            interaction_id=interaction_id,
            step_id=step_id
        ))
        
        # Also log to debug file
        try:
            log_entry = {
                "category": category,
                "data": data,
                "interaction_id": interaction_id,
                "step_id": step_id
            }
            debug_logger.info(json.dumps(log_entry, ensure_ascii=False, default=str))
        except Exception as e:
            # Don't let logging errors break the flow
            pass

    # ==================== Extended tool support ====================
    
    async def search_in_files(self, pattern: str, path: str | None = None, is_regex: bool = False) -> str:
        """Search for pattern in workspace files."""
        return await self._call_remote_tool(
            "search_in_files", 
            pattern=pattern, 
            path=path, 
            is_regex=is_regex
        )
    
    async def call_vscode_tool(self, tool_name: str, args: dict) -> str:
        """
        Call a VS Code-specific tool by name.
        Routes to the frontend for execution.
        """
        return await self._call_remote_tool(tool_name, **args)
    
    async def run_terminal_command(self, command: str, cwd: str | None = None) -> str:
        """Run a terminal command via VS Code."""
        return await self._call_remote_tool(
            "run_terminal_command",
            command=command,
            cwd=cwd
        )
