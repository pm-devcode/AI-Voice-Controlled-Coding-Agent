from __future__ import annotations
import logging
import uuid
import re
from typing import TYPE_CHECKING, Any
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from backend.src.adapters.base import FilesystemAdapter

logger = logging.getLogger(__name__)

# We will pass the adapter via the Agent's dependencies (pydantic-ai logic)

class ReadFileResult(BaseModel):
    content: str
    success: bool
    error: str | None = None

from pydantic_ai import RunContext

def register_file_tools(agent, adapter: FilesystemAdapter):
    """
    Registers file manipulation tools to a pydantic-ai agent.
    """
    
    logger.info(f"Registering file tools on agent: {type(agent)}")

    @agent.tool
    async def read_file(ctx: RunContext[Any], path: str, start_line: int | None = None, end_line: int | None = None) -> str:
        """
        Reads the content of a file at the given path, optionally a specific line range.
        
        Args:
            path: The relative or absolute path to the file.
            start_line: Optional 1-based starting line number. If provided with end_line, only that range is returned.
            end_line: Optional 1-based ending line number (inclusive).
        """
        call_id = str(uuid.uuid4())
        line_info = f" (lines {start_line}-{end_line})" if start_line and end_line else ""
        await ctx.deps.adapter.send_agent_action(
            action_type="tool_start",
            label=f"Reading file: {path}{line_info}",
            details=f"Target path: {path}",
            call_id=call_id,
            interaction_id=ctx.deps.interaction_id,
            step_id=ctx.deps.step_id
        )
        try:
            result = await ctx.deps.adapter.read_file(path)
            
            # Track verification
            if hasattr(ctx.deps, 'written_files') and path in ctx.deps.written_files:
                if hasattr(ctx.deps, 'verified_files'):
                    ctx.deps.verified_files.add(path)

            # Apply line range if specified
            if start_line is not None and end_line is not None:
                lines = result.split('\n')
                # Convert to 0-based index
                start_idx = max(0, start_line - 1)
                end_idx = min(len(lines), end_line)
                result = '\n'.join(lines[start_idx:end_idx])
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Finished reading: {path}",
                status="success",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return result
        except Exception as e:
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Failed reading: {path}",
                details=str(e),
                status="failure",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Error reading file: {str(e)}"

    @agent.tool
    async def write_file(ctx: RunContext[Any], path: str, content: str) -> str:
        """
        Writes content to a file. Overwrites if exists.
        
        Args:
            path: Target file path.
            content: The text content to write.
        """
        call_id = str(uuid.uuid4())
        await ctx.deps.adapter.send_agent_action(
            action_type="tool_start",
            label=f"Writing to file: {path}",
            details=f"Adding {len(content)} characters",
            call_id=call_id,
            interaction_id=ctx.deps.interaction_id,
            step_id=ctx.deps.step_id
        )
        try:
            await ctx.deps.adapter.write_file(path, content)
            
            # Track written files
            if hasattr(ctx.deps, 'written_files'):
                ctx.deps.written_files.add(path)

            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Successfully wrote to: {path}",
                status="success",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Successfully wrote to {path}"
        except Exception as e:
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Failed writing to: {path}",
                details=str(e),
                status="failure",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Error writing file: {str(e)}"

    @agent.tool
    async def list_directory(ctx: RunContext[Any], path: str = ".") -> str:
        """
        Lists files and directories in the given path.
        """
        call_id = str(uuid.uuid4())
        await ctx.deps.adapter.send_agent_action(
            action_type="tool_start",
            label=f"Listing directory: {path}",
            details=f"Path: {path}",
            call_id=call_id,
            interaction_id=ctx.deps.interaction_id,
            step_id=ctx.deps.step_id
        )
        try:
            items = await ctx.deps.adapter.list_dir(path)
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Directory listing completed for: {path}",
                status="success",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return "\n".join(items) if items else "(Empty directory)"
        except Exception as e:
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Failed to list directory: {path}",
                details=str(e),
                status="failure",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Error: {str(e)}"
            
    @agent.tool
    async def log_thought(ctx: RunContext[Any], thought: str) -> str:
        """
        Logs a specific thought or plan step to the user's progress panel.
        Use this when you are about to start a multi-step task or want to explain your reasoning.
        
        Args:
            thought: A concise sentence describing what you are thinking or planning to do.
        """
        await ctx.deps.adapter.send_agent_action(
            action_type="thinking",
            label=thought,
            status="success",
            interaction_id=ctx.deps.interaction_id,
            step_id=ctx.deps.step_id
        )
        return "Thought logged."

    @agent.tool
    async def edit_file(
        ctx: RunContext[Any], 
        path: str, 
        old_string: str, 
        new_string: str
    ) -> str:
        """
        Edits a file by replacing an exact string match with new content.
        This is the PREFERRED way to edit files - safer than overwriting the whole file.
        
        IMPORTANT GUIDELINES:
        1. First use read_file to see the current content
        2. old_string must be an EXACT match (including whitespace and indentation)
        3. Include 2-3 lines of context before and after for uniqueness
        4. Use this for small, targeted edits
        
        Args:
            path: The file path to edit.
            old_string: The exact text to find and replace (include context lines).
            new_string: The replacement text (same formatting/indentation).
        
        Returns:
            Success or error message.
        """
        call_id = str(uuid.uuid4())
        await ctx.deps.adapter.send_agent_action(
            action_type="tool_start",
            label=f"Editing file: {path}",
            details=f"Replacing {len(old_string)} chars",
            call_id=call_id,
            interaction_id=ctx.deps.interaction_id,
            step_id=ctx.deps.step_id
        )
        try:
            # Read current content
            content = await ctx.deps.adapter.read_file(path)
            
            # Check if old_string exists
            if old_string not in content:
                await ctx.deps.adapter.send_agent_action(
                    action_type="tool_end",
                    label=f"Edit failed: old_string not found in {path}",
                    status="failure",
                    call_id=call_id,
                    interaction_id=ctx.deps.interaction_id,
                    step_id=ctx.deps.step_id
                )
                return f"Error: The exact string to replace was not found in {path}. Please read the file first to get the exact content."
            
            # Check for multiple matches
            count = content.count(old_string)
            if count > 1:
                await ctx.deps.adapter.send_agent_action(
                    action_type="tool_end",
                    label=f"Edit failed: multiple matches ({count}) in {path}",
                    status="failure",
                    call_id=call_id,
                    interaction_id=ctx.deps.interaction_id,
                    step_id=ctx.deps.step_id
                )
                return f"Error: Found {count} matches of old_string. Please include more context lines to make it unique."
            
            # Perform replacement
            new_content = content.replace(old_string, new_string, 1)
            await ctx.deps.adapter.write_file(path, new_content)
            
            # Track written files
            if hasattr(ctx.deps, 'written_files'):
                ctx.deps.written_files.add(path)
            
            # Record successful edit in session memory
            if hasattr(ctx.deps, 'session_memory') and ctx.deps.session_memory:
                ctx.deps.session_memory.record_successful_edit(
                    file_path=path,
                    action="edit_file",
                    context=old_string[:100]
                )

            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Successfully edited: {path}",
                status="success",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Successfully edited {path}. Replaced {len(old_string)} chars with {len(new_string)} chars."
        except Exception as e:
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Failed editing: {path}",
                details=str(e),
                status="failure",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Error editing file: {str(e)}"

    @agent.tool
    async def search_in_files(
        ctx: RunContext[Any], 
        pattern: str, 
        path: str = ".",
        is_regex: bool = False
    ) -> str:
        """
        Searches for a pattern in files within a directory.
        Useful for finding code definitions, usages, or specific text.
        
        Args:
            pattern: The text or regex pattern to search for.
            path: Directory to search in (default: workspace root).
            is_regex: Whether pattern is a regular expression.
        
        Returns:
            Matching file paths and line numbers with snippets.
        """
        call_id = str(uuid.uuid4())
        await ctx.deps.adapter.send_agent_action(
            action_type="tool_start",
            label=f"Searching for: {pattern}",
            details=f"In: {path}",
            call_id=call_id,
            interaction_id=ctx.deps.interaction_id,
            step_id=ctx.deps.step_id
        )
        try:
            # Call remote search tool on VS Code side
            result = await ctx.deps.adapter._call_remote_tool(
                "search_in_files", 
                pattern=pattern, 
                path=path, 
                is_regex=is_regex
            )
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Search completed: found matches",
                status="success",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            if isinstance(result, list):
                return "\n".join([f"{r['file']}:{r['line']}: {r['text']}" for r in result])
            return str(result)
        except Exception as e:
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Search failed",
                details=str(e),
                status="failure",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Error searching: {str(e)}"

    @agent.tool
    async def get_file_outline(ctx: RunContext[Any], path: str) -> str:
        """
        Gets the structure/outline of a code file (functions, classes, methods).
        Useful for understanding file structure before editing.
        
        Args:
            path: Path to the source code file.
        
        Returns:
            List of symbols (functions, classes) with line numbers.
        """
        call_id = str(uuid.uuid4())
        await ctx.deps.adapter.send_agent_action(
            action_type="tool_start",
            label=f"Getting outline: {path}",
            call_id=call_id,
            interaction_id=ctx.deps.interaction_id,
            step_id=ctx.deps.step_id
        )
        try:
            result = await ctx.deps.adapter._call_remote_tool("get_file_outline", path=path)
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Outline retrieved for: {path}",
                status="success",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            if isinstance(result, list):
                return "\n".join([f"L{s['line']}: {s['kind']} {s['name']}" for s in result])
            return str(result)
        except Exception as e:
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Failed to get outline",
                details=str(e),
                status="failure",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Error getting outline: {str(e)}"

    @agent.tool
    async def create_file(ctx: RunContext[Any], path: str, content: str) -> str:
        """
        Creates a new file with the given content.
        Use this for NEW files only. For editing existing files, use edit_file.
        
        Args:
            path: Path for the new file.
            content: The content to write.
        
        Returns:
            Success or error message.
        """
        call_id = str(uuid.uuid4())
        await ctx.deps.adapter.send_agent_action(
            action_type="tool_start",
            label=f"Creating file: {path}",
            details=f"With {len(content)} characters",
            call_id=call_id,
            interaction_id=ctx.deps.interaction_id,
            step_id=ctx.deps.step_id
        )
        try:
            # Check if file already exists
            exists = await ctx.deps.adapter.exists(path)
            if exists:
                await ctx.deps.adapter.send_agent_action(
                    action_type="tool_end",
                    label=f"File already exists: {path}",
                    status="failure",
                    call_id=call_id,
                    interaction_id=ctx.deps.interaction_id,
                    step_id=ctx.deps.step_id
                )
                return f"Error: File {path} already exists. Use edit_file to modify it."
            
            await ctx.deps.adapter.write_file(path, content)
            
            # Track written files
            if hasattr(ctx.deps, 'written_files'):
                ctx.deps.written_files.add(path)

            # Record successful edit in session memory
            if hasattr(ctx.deps, 'session_memory') and ctx.deps.session_memory:
                ctx.deps.session_memory.record_successful_edit(
                    file_path=path,
                    action="create_file"
                )

            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Created: {path}",
                status="success",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Successfully created {path}"
        except Exception as e:
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Failed to create: {path}",
                details=str(e),
                status="failure",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Error creating file: {str(e)}"

    @agent.tool
    async def apply_diff(ctx: RunContext[Any], path: str, diff: str) -> str:
        """
        Applies a unified diff to a file. Best for complex multi-line changes.
        
        Use this when:
        - Changing multiple separate sections of a file
        - The changes are complex and edit_file would be cumbersome
        - You want to show the user exactly what will change
        
        The diff format should be:
        ```
        @@ -start,count +start,count @@
         context line
        -removed line
        +added line
         context line
        ```
        
        Args:
            path: The file path to patch.
            diff: The unified diff content (without file headers, just hunks).
        
        Returns:
            Success message with summary of changes, or error details.
        """
        call_id = str(uuid.uuid4())
        await ctx.deps.adapter.send_agent_action(
            action_type="tool_start",
            label=f"Applying diff to: {path}",
            details=f"Diff size: {len(diff)} chars",
            call_id=call_id,
            interaction_id=ctx.deps.interaction_id,
            step_id=ctx.deps.step_id
        )
        try:
            content = await ctx.deps.adapter.read_file(path)
            lines = content.split('\n')
            
            # Parse and apply diff hunks
            result_lines = lines.copy()
            offset = 0  # Track line number shifts from previous hunks
            hunks_applied = 0
            
            # Split diff into hunks
            hunk_pattern = re.compile(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')
            current_hunk = []
            hunks = []
            
            for line in diff.split('\n'):
                match = hunk_pattern.match(line)
                if match:
                    if current_hunk:
                        hunks.append(current_hunk)
                    current_hunk = [line]
                elif current_hunk:
                    current_hunk.append(line)
            if current_hunk:
                hunks.append(current_hunk)
            
            for hunk in hunks:
                if not hunk:
                    continue
                    
                header = hunk[0]
                match = hunk_pattern.match(header)
                if not match:
                    continue
                
                old_start = int(match.group(1)) - 1  # Convert to 0-based
                old_count = int(match.group(2)) if match.group(2) else 1
                
                # Apply changes
                new_lines = []
                old_idx = old_start + offset
                
                for diff_line in hunk[1:]:
                    if not diff_line:
                        continue
                    if diff_line.startswith(' '):
                        # Context line - keep it
                        new_lines.append(diff_line[1:])
                    elif diff_line.startswith('-'):
                        # Remove line - skip it (don't add to new_lines)
                        pass
                    elif diff_line.startswith('+'):
                        # Add line
                        new_lines.append(diff_line[1:])
                    else:
                        # Treat as context if no prefix
                        new_lines.append(diff_line)
                
                # Replace the old section with new
                result_lines = result_lines[:old_idx] + new_lines + result_lines[old_idx + old_count:]
                offset += len(new_lines) - old_count
                hunks_applied += 1
            
            if hunks_applied == 0:
                await ctx.deps.adapter.send_agent_action(
                    action_type="tool_end",
                    label=f"No valid hunks found in diff",
                    status="failure",
                    call_id=call_id,
                    interaction_id=ctx.deps.interaction_id,
                    step_id=ctx.deps.step_id
                )
                return "Error: No valid diff hunks found. Check the diff format."
            
            new_content = '\n'.join(result_lines)
            await ctx.deps.adapter.write_file(path, new_content)
            
            # Track written files
            if hasattr(ctx.deps, 'written_files'):
                ctx.deps.written_files.add(path)
            
            # Record successful edit in session memory
            if hasattr(ctx.deps, 'session_memory') and ctx.deps.session_memory:
                ctx.deps.session_memory.record_successful_edit(
                    file_path=path,
                    action="apply_diff"
                )

            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Applied {hunks_applied} hunks to: {path}",
                status="success",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Successfully applied {hunks_applied} diff hunk(s) to {path}"
        except Exception as e:
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Failed to apply diff: {path}",
                details=str(e),
                status="failure",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Error applying diff: {str(e)}"

    @agent.tool
    async def find_references(ctx: RunContext[Any], symbol: str, path: str | None = None) -> str:
        """
        Finds all references/usages of a symbol in the workspace using VS Code's LSP.
        
        Use this to:
        - Find where a function/class/variable is used
        - Understand impact before refactoring
        - Navigate the codebase
        
        Args:
            symbol: The symbol name to find references for.
            path: Optional file path where the symbol is defined (improves accuracy).
        
        Returns:
            List of file:line locations where the symbol is referenced.
        """
        call_id = str(uuid.uuid4())
        await ctx.deps.adapter.send_agent_action(
            action_type="tool_start",
            label=f"Finding references: {symbol}",
            details=f"In: {path or 'workspace'}",
            call_id=call_id,
            interaction_id=ctx.deps.interaction_id,
            step_id=ctx.deps.step_id
        )
        try:
            result = await ctx.deps.adapter._call_remote_tool(
                "find_references",
                symbol=symbol,
                path=path
            )
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Found {len(result) if isinstance(result, list) else 0} references",
                status="success",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            if isinstance(result, list):
                return "\n".join([f"{r['file']}:{r['line']}: {r.get('text', '')}" for r in result])
            return str(result)
        except Exception as e:
            await ctx.deps.adapter.send_agent_action(
                action_type="tool_end",
                label=f"Failed to find references",
                details=str(e),
                status="failure",
                call_id=call_id,
                interaction_id=ctx.deps.interaction_id,
                step_id=ctx.deps.step_id
            )
            return f"Error finding references: {str(e)}"

    logger.info("File tools registered to agent.")
