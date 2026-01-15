from __future__ import annotations
import logging
import uuid
from typing import Any
from pydantic_ai import RunContext

logger = logging.getLogger(__name__)

def register_vscode_tools(agent):
    """
    Registers VS Code specific context tools to a pydantic-ai agent.
    """

    @agent.tool
    async def get_active_file_context(ctx: RunContext[Any]) -> dict[str, Any] | str:
        """
        Gets the context of the currently active file in VS Code.
        Returns path, language, content, and selection info.
        """
        call_id = str(uuid.uuid4())
        await ctx.deps.adapter.send_agent_action(
            action_type="tool_start",
            label="Fetching active editor context",
            call_id=call_id,
            interaction_id=ctx.deps.interaction_id,
            step_id=ctx.deps.step_id
        )
        try:
            result = await ctx.deps.adapter.call_vscode_tool("get_active_file_context", {})
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label="Context received",
                status="success",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return result
        except Exception as e:
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label="Failed to get context",
                status="failure",
                details=str(e),
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Error: {str(e)}"

    @agent.tool
    async def get_workspace_diagnostics(ctx: RunContext[Any]) -> list[dict[str, Any]] | str:
        """
        Gets all errors and warnings (diagnostics) from the current workspace.
        """
        call_id = str(uuid.uuid4())
        await ctx.deps.adapter.send_agent_action(
            action_type="tool_start",
            label="Analyzing workspace diagnostics",
            call_id=call_id,
            interaction_id=ctx.deps.interaction_id,
            step_id=ctx.deps.step_id
        )
        try:
            result = await ctx.deps.adapter.call_vscode_tool("get_workspace_diagnostics", {})
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Analysis complete: found issues in {len(result)} files",
                status="success",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return result
        except Exception as e:
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label="Failed to get diagnostics",
                status="failure",
                details=str(e),
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Error: {str(e)}"

    @agent.tool
    async def get_workspace_structure(ctx: RunContext[Any], max_depth: int = 3) -> str:
        """
        Gets a tree view of the workspace directory structure.
        Useful at the start of a task to understand the project layout.
        
        Args:
            max_depth: Maximum depth of directory traversal (default: 3).
        
        Returns:
            A tree-style representation of the workspace structure.
        """
        call_id = str(uuid.uuid4())
        await ctx.deps.adapter.send_agent_action(
            action_type="tool_start",
            label="Getting workspace structure",
            call_id=call_id,
            interaction_id=ctx.deps.interaction_id,
            step_id=ctx.deps.step_id
        )
        try:
            result = await ctx.deps.adapter.call_vscode_tool(
                "get_workspace_structure", 
                {"max_depth": max_depth}
            )
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label="Workspace structure retrieved",
                status="success",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return result
        except Exception as e:
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label="Failed to get workspace structure",
                status="failure",
                details=str(e),
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Error: {str(e)}"

    @agent.tool
    async def run_terminal_command(ctx: RunContext[Any], command: str, cwd: str | None = None) -> str:
        """
        Runs a terminal command in the workspace.
        Useful for running tests, builds, or other shell commands.
        
        Args:
            command: The command to execute.
            cwd: Working directory (optional, defaults to workspace root).
        
        Returns:
            Command output (stdout + stderr).
        """
        call_id = str(uuid.uuid4())
        await ctx.deps.adapter.send_agent_action(
            action_type="tool_start",
            label=f"Running: {command[:50]}...",
            details=f"Command: {command}",
            call_id=call_id,
            interaction_id=ctx.deps.interaction_id,
            step_id=ctx.deps.step_id
        )
        try:
            result = await ctx.deps.adapter.call_vscode_tool(
                "run_terminal_command",
                {"command": command, "cwd": cwd}
            )
            status = "success" if result.get("exitCode", 1) == 0 else "failure"
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Command finished (exit: {result.get('exitCode', '?')})",
                status=status,
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Exit code: {result.get('exitCode')}\n\nOutput:\n{result.get('output', '')}"
        except Exception as e:
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label="Command failed",
                status="failure",
                details=str(e),
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Error: {str(e)}"

    @agent.tool
    async def execute_vscode_command(ctx: RunContext[Any], command: str, args: list | None = None) -> Any:
        """
        Executes any VS Code command with arguments.
        Example: execute_vscode_command('vcca.stop').
        """
        call_id = str(uuid.uuid4())
        await ctx.deps.adapter.send_agent_action(
            action_type="tool_start",
            label=f"Executing VS Code command: {command}",
            call_id=call_id,
            interaction_id=ctx.deps.interaction_id,
            step_id=ctx.deps.step_id
        )
        try:
            result = await ctx.deps.adapter.call_vscode_tool("execute_vscode_command", {"command": command, "args": args or []})
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label="Command executed",
                status="success",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return result
        except Exception as e:
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label="Command execution failed",
                status="failure",
                details=str(e),
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Error: {str(e)}"

    @agent.tool
    async def get_workspace_config(ctx: RunContext[Any], section: str) -> Any:
        """Reads VS Code settings for a specific section (e.g., 'editor', 'vcca')."""
        try:
            return await ctx.deps.adapter.call_vscode_tool("get_workspace_config", {"section": section})
        except Exception as e:
            return f"Error: {str(e)}"

    @agent.tool
    async def update_workspace_config(ctx: RunContext[Any], section: str, key: str, value: Any, target: str = "workspace") -> str:
        """Updates VS Code settings. target can be 'user' or 'workspace'."""
        try:
            return await ctx.deps.adapter.call_vscode_tool("update_workspace_config", {
                "section": section, 
                "key": key, 
                "value": value, 
                "target": target
            })
        except Exception as e:
            return f"Error: {str(e)}"

    logger.info("VS Code context tools registered.")
