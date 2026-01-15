"""Tool executor for structured agent protocol."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Callable, Awaitable

from backend.src.agent.structured_protocol import ToolCall, ToolResult
from backend.src.adapters.base import FilesystemAdapter

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    Executes tool calls requested by the structured agent.
    
    This separates tool execution from the LLM, giving us:
    - Full control over execution
    - Parallel execution capability
    - Timeout handling
    - Result formatting
    """
    
    def __init__(
        self, 
        adapter: FilesystemAdapter,
        tool_timeout: float = 30.0
    ):
        self.adapter = adapter
        self.tool_timeout = tool_timeout
        self._tools: dict[str, Callable] = {}
        self._register_builtin_tools()
    
    def _register_builtin_tools(self):
        """Register all available tools."""
        # File operations
        self._tools["read_file"] = self._read_file
        self._tools["write_file"] = self._write_file
        self._tools["create_file"] = self._create_file
        self._tools["edit_file"] = self._edit_file
        self._tools["apply_diff"] = self._apply_diff
        self._tools["list_directory"] = self._list_directory
        self._tools["search_in_files"] = self._search_in_files
        
        # VS Code context tools (delegated to frontend)
        self._tools["get_workspace_structure"] = self._get_workspace_structure
        self._tools["get_workspace_diagnostics"] = self._get_workspace_diagnostics
        self._tools["get_active_file_context"] = self._get_active_file_context
        self._tools["get_file_outline"] = self._get_file_outline
        self._tools["find_references"] = self._find_references
        
        # Extended VS Code Tools
        self._tools["execute_vscode_command"] = self._execute_vscode_command
        self._tools["get_workspace_config"] = self._get_workspace_config
        self._tools["update_workspace_config"] = self._update_workspace_config
        
        # Terminal
        self._tools["run_terminal_command"] = self._run_terminal_command
        
        # Utility
        self._tools["log_thought"] = self._log_thought
    
    def get_available_tools(self) -> list[dict]:
        """Return list of available tools with descriptions."""
        return [
            {
                "name": "read_file",
                "params": ["path", "start_line?", "end_line?"],
                "description": "Read file content. Use line ranges for large files."
            },
            {
                "name": "write_file",
                "params": ["path", "content"],
                "description": "Overwrite entire file content."
            },
            {
                "name": "create_file",
                "params": ["path", "content"],
                "description": "Create a new file (fails if exists)."
            },
            {
                "name": "edit_file",
                "params": ["path", "old_string", "new_string"],
                "description": "Replace exact text in file. Include 2-3 context lines."
            },
            {
                "name": "apply_diff",
                "params": ["path", "diff"],
                "description": "Apply unified diff to file."
            },
            {
                "name": "list_directory",
                "params": ["path"],
                "description": "List files and folders in directory."
            },
            {
                "name": "search_in_files",
                "params": ["pattern", "path?", "is_regex?"],
                "description": "Search for text or pattern in files. 'pattern' is the search text."
            },
            {
                "name": "get_workspace_structure",
                "params": ["max_depth?", "path?"],
                "description": "Get project directory tree. Start from 'path' if provided."
            },
            {
                "name": "get_workspace_diagnostics",
                "params": [],
                "description": "Get all errors/warnings in workspace."
            },
            {
                "name": "get_active_file_context",
                "params": [],
                "description": "Get currently open editor content."
            },
            {
                "name": "get_file_outline",
                "params": ["path"],
                "description": "Get functions/classes structure in file."
            },
            {
                "name": "find_references",
                "params": ["symbol", "path?"],
                "description": "Find all usages of a symbol."
            },
            {
                "name": "run_terminal_command",
                "params": ["command", "cwd?"],
                "description": "Run shell command in terminal (PowerShell on Windows)."
            },
            {
                "name": "execute_vscode_command",
                "params": ["command", "args?"],
                "description": "Execute any built-in or extension VS Code command."
            },
            {
                "name": "get_workspace_config",
                "params": ["section"],
                "description": "Read VS Code settings for a specific section (e.g., 'editor', 'vcca')."
            },
            {
                "name": "update_workspace_config",
                "params": ["section", "key", "value", "target?"],
                "description": "Update VS Code settings. target can be 'user' or 'workspace'."
            },
            {
                "name": "log_thought",
                "params": ["thought"],
                "description": "Log internal reasoning (for debugging)."
            }
        ]
    
    async def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """Execute a single tool (public wrapper)."""
        return await self._execute_single(tool_call)

    async def execute_tools_with_hooks(
        self,
        tools: list[ToolCall],
        on_start: Callable[[ToolCall], Awaitable[None]] | None = None,
        on_end: Callable[[ToolResult], Awaitable[None]] | None = None
    ) -> list[ToolResult]:
        """Execute tools in parallel with hooks."""
        async def wrapped(t):
            if on_start: 
                try: await on_start(t)
                except: pass
            res = await self._execute_single(t)
            if on_end:
                try: await on_end(res)
                except: pass
            return res
            
        return await asyncio.gather(*(wrapped(t) for t in tools))

    async def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """Execute a single tool (public wrapper)."""
        return await self._execute_single(tool_call)

    async def execute_tools_with_hooks(
        self,
        tools: list[ToolCall],
        on_start: Callable[[ToolCall], Awaitable[None]] | None = None,
        on_end: Callable[[ToolResult], Awaitable[None]] | None = None
    ) -> list[ToolResult]:
        """Execute tools in parallel with hooks."""
        async def wrapped(t):
            # Ensure call_id exists
            if not t.call_id:
                t.call_id = str(uuid.uuid4())
            
            if on_start: 
                try: 
                    logger.debug(f"Calling on_start hook for tool: {t.name}")
                    await on_start(t)
                except Exception as e:
                    logger.error(f"Error in on_start hook: {e}")
            
            res = await self._execute_single(t)
            
            if on_end:
                try: 
                    logger.debug(f"Calling on_end hook for tool: {t.name}")
                    await on_end(res)
                except Exception as e:
                    logger.error(f"Error in on_end hook: {e}")
            return res
            
        return await asyncio.gather(*(wrapped(t) for t in tools))

    async def execute_tools(
        self,
        tool_calls: list[ToolCall],
        parallel: bool = False
    ) -> list[ToolResult]:
        """
        Execute a list of tool calls.
        
        Args:
            tool_calls: List of tools to execute
            parallel: If True, execute tools in parallel where possible
        
        Returns:
            List of ToolResult with execution outcomes
        """
        if not tool_calls:
            return []
        
        # Assign call_ids if not present
        for tc in tool_calls:
            if not tc.call_id:
                tc.call_id = str(uuid.uuid4())[:8]
        
        if parallel:
            # Execute all tools in parallel
            tasks = [self._execute_single(tc) for tc in tool_calls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Convert exceptions to ToolResults
            final_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    final_results.append(ToolResult(
                        name=tool_calls[i].name,
                        call_id=tool_calls[i].call_id,
                        success=False,
                        result=f"Error: {result}"
                    ))
                else:
                    final_results.append(result)
            return final_results
        else:
            # Sequential execution
            results = []
            for tc in tool_calls:
                result = await self._execute_single(tc)
                results.append(result)
            return results
    
    async def _execute_single(self, tool_call: ToolCall) -> ToolResult:
        """Execute a single tool call with timeout."""
        start_time = time.time()
        
        tool_fn = self._tools.get(tool_call.name)
        if not tool_fn:
            return ToolResult(
                name=tool_call.name,
                call_id=tool_call.call_id,
                success=False,
                result=f"Unknown tool: {tool_call.name}"
            )
        
        # Prepare and normalize arguments
        args = tool_call.args.copy()
        
        # Normalize 'path' argument (common LLM hallucination)
        if 'path' not in args:
            for alias in ['file_path', 'filepath', 'file', 'target', 'directory', 'folder']:
                if alias in args:
                    args['path'] = args.pop(alias)
                    break
        
        # Normalize 'pattern' for search (common LLM hallucination to use 'query')
        if tool_call.name == "search_in_files" and 'pattern' not in args:
            if 'query' in args:
                args['pattern'] = args.pop('query')
                
        # Handle 'max_depth' alias
        if 'max_depth' not in args and 'depth' in args:
            args['max_depth'] = args.pop('depth')
        
        try:
            logger.info(f"Executing tool: {tool_call.name} with normalized args: {args}")
            
            # Execute with timeout
            # Use inspect to see if we should pass kwargs or only specific args
            import inspect
            sig = inspect.signature(tool_fn)
            
            # Filter args to match function signature if no **kwargs in tool_fn
            has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            
            if not has_varkw:
                filtered_args = {k: v for k, v in args.items() if k in sig.parameters}
                result = await asyncio.wait_for(
                    tool_fn(**filtered_args),
                    timeout=self.tool_timeout
                )
            else:
                result = await asyncio.wait_for(
                    tool_fn(**args),
                    timeout=self.tool_timeout
                )
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            return ToolResult(
                name=tool_call.name,
                call_id=tool_call.call_id,
                success=True,
                result=str(result) if result is not None else "Success",
                duration_ms=duration_ms
            )
            
        except asyncio.TimeoutError:
            return ToolResult(
                name=tool_call.name,
                call_id=tool_call.call_id,
                success=False,
                result=f"Tool timed out after {self.tool_timeout}s"
            )
        except Exception as e:
            logger.error(f"Tool {tool_call.name} failed: {e}", exc_info=True)
            return ToolResult(
                name=tool_call.name,
                call_id=tool_call.call_id,
                success=False,
                result=f"Error: {e}"
            )
    
    # ==================== Tool Implementations ====================
    
    async def _read_file(
        self, 
        path: str, 
        start_line: int | None = None, 
        end_line: int | None = None,
        **kwargs
    ) -> str:
        """Read file content."""
        content = await self.adapter.read_file(path)
        
        if start_line is not None or end_line is not None:
            lines = content.split('\n')
            start = (start_line or 1) - 1  # Convert to 0-indexed
            end = end_line or len(lines)
            content = '\n'.join(lines[start:end])
        
        return content
    
    async def _write_file(self, path: str, content: str, **kwargs) -> str:
        """Write file content."""
        await self.adapter.write_file(path, content)
        return f"File written: {path}"
    
    async def _create_file(self, path: str, content: str, **kwargs) -> str:
        """Create new file."""
        # Check if exists first
        try:
            await self.adapter.read_file(path)
            return f"Error: File already exists: {path}"
        except Exception:
            pass
        
        await self.adapter.write_file(path, content)
        return f"File created: {path}"
    
    async def _edit_file(self, path: str, old_string: str, new_string: str, **kwargs) -> str:
        """Edit file by replacing text."""
        content = await self.adapter.read_file(path)
        
        if old_string not in content:
            return f"Error: Text not found in file. Make sure to include exact whitespace and context."
        
        count = content.count(old_string)
        if count > 1:
            return f"Error: Text found {count} times. Include more context to make it unique."
        
        new_content = content.replace(old_string, new_string, 1)
        await self.adapter.write_file(path, new_content)
        return f"File edited: {path}"
    
    async def _apply_diff(self, path: str, diff: str, **kwargs) -> str:
        """Apply unified diff to file."""
        # Simple diff application - could be enhanced
        content = await self.adapter.read_file(path)
        
        # Parse and apply diff (simplified)
        # For now, delegate to a proper diff library or implement
        return "Diff application not yet implemented. Use edit_file instead."
    
    async def _list_directory(self, path: str, **kwargs) -> str:
        """List directory contents."""
        entries = await self.adapter.list_directory(path)
        return "\n".join(entries)
    
    async def _search_in_files(
        self, 
        pattern: str | None = None, 
        path: str | None = None, 
        is_regex: bool = False,
        **kwargs
    ) -> str:
        """Search for pattern in files."""
        # Handle 'query' as alias for 'pattern' (common LLM hallucination)
        search_pattern = pattern or kwargs.get("query")
        if not search_pattern:
            return "Error: Missing 'pattern' argument for search_in_files."
            
        results = await self.adapter.search_in_files(search_pattern, path, is_regex)
        return results
    
    async def _get_workspace_structure(self, max_depth: int = 3, path: str | None = None, **kwargs) -> str:
        """Get workspace structure from VS Code.
        
        Args:
            max_depth: How many levels to descend
            path: Optional relative path to start from (e.g. 'src')
        """
        args = {"max_depth": max_depth}
        if path:
            args["path"] = path
            
        return await self.adapter.call_vscode_tool(
            "get_workspace_structure", 
            args
        )
    
    async def _get_workspace_diagnostics(self, **kwargs) -> str:
        """Get workspace diagnostics from VS Code."""
        return await self.adapter.call_vscode_tool(
            "get_workspace_diagnostics", 
            {}
        )
    
    async def _get_active_file_context(self, **kwargs) -> str:
        """Get active file context from VS Code."""
        return await self.adapter.call_vscode_tool(
            "get_active_file_context", 
            {}
        )
    
    async def _get_file_outline(self, path: str, **kwargs) -> str:
        """Get file outline from VS Code."""
        return await self.adapter.call_vscode_tool(
            "get_file_outline", 
            {"path": path}
        )
    
    async def _find_references(self, symbol: str, path: str | None = None, **kwargs) -> str:
        """Find references from VS Code."""
        args = {"symbol": symbol}
        if path:
            args["path"] = path
        return await self.adapter.call_vscode_tool("find_references", args)
    
    async def _execute_vscode_command(self, command: str, args: list | None = None, **kwargs) -> Any:
        """Execute a VS Code command."""
        return await self.adapter.call_vscode_tool(
            "execute_vscode_command", 
            {"command": command, "args": args or []}
        )
    
    async def _get_workspace_config(self, section: str, **kwargs) -> Any:
        """Get workspace configuration."""
        return await self.adapter.call_vscode_tool(
            "get_workspace_config", 
            {"section": section}
        )
    
    async def _update_workspace_config(self, section: str, key: str, value: Any, target: str = "workspace", **kwargs) -> str:
        """Update workspace configuration."""
        return await self.adapter.call_vscode_tool(
            "update_workspace_config", 
            {"section": section, "key": key, "value": value, "target": target}
        )
    
    async def _run_terminal_command(self, command: str, cwd: str | None = None, **kwargs) -> str:
        """Run terminal command."""
        return await self.adapter.run_terminal_command(command, cwd)
    
    async def _log_thought(self, thought: str, **kwargs) -> str:
        """Log agent's thought process."""
        logger.info(f"Agent thought: {thought}")
        await self.adapter.log_debug("agent_thought", {"thought": thought})
        return "Thought logged"
