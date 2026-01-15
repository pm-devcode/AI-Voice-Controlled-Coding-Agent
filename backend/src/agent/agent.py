from __future__ import annotations
import logging
import os
from dataclasses import dataclass, field
from typing import Any
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from backend.src.config import get_settings
from backend.src.adapters.base import FilesystemAdapter
from backend.src.tools.file_ops import register_file_tools
from backend.src.tools.vscode_ctx import register_vscode_tools
from backend.src.agent.models import Agentmode
from backend.src.agent.context_loader import ProjectContextLoader
from backend.src.agent.session_memory import SessionMemoryManager

logger = logging.getLogger(__name__)

@dataclass
class AgentDependencies:
    adapter: FilesystemAdapter
    interaction_id: str | None = None
    step_id: str | None = None
    session_memory: SessionMemoryManager | None = None
    written_files: set[str] = field(default_factory=set)
    verified_files: set[str] = field(default_factory=set)

class VCCAAgent:
    """The core reasoning engine of VCCA."""

    def __init__(self, adapter: FilesystemAdapter, workspace_path: str | None = None):
        self.settings = get_settings()
        self.adapter = adapter
        self._provider = None
        self.workspace_path = workspace_path
        
        # Initialize context and memory (use direct filesystem, not WebSocket adapter)
        self.context_loader = ProjectContextLoader(workspace_path)
        self.session_memory = SessionMemoryManager(workspace_path)
        self._project_context: str = ""
        
        self._setup_auth()
        
        # Initialize sub-agents
        self.fast_agent = self._create_agent(model_name=self.settings.GEMINI_MODEL_FAST)
        self.thinking_agent = self._create_agent(model_name=self.settings.GEMINI_MODEL_THINKING or self.settings.GEMINI_MODEL_FAST)

    def _setup_auth(self):
        if self.settings.GEMINI_API_KEY:
            logger.info("Using GEMINI_API_KEY from settings.")
            self._provider = GoogleProvider(api_key=self.settings.GEMINI_API_KEY)
            os.environ["GOOGLE_API_KEY"] = self.settings.GEMINI_API_KEY
        else:
            logger.warning("GEMINI_API_KEY is not set in settings.")
            if "GOOGLE_API_KEY" in os.environ:
                 logger.info("Using existing GOOGLE_API_KEY from environment.")
            else:
                 logger.error("No Gemini API key found in settings or environment!")

    def _get_base_system_prompt(self) -> str:
        """Returns the base system prompt without dynamic context."""
        return (
            "You are VCCA (Voice-Controlled Coding Agent), an expert AI coding assistant."
            "\n\n## LANGUAGE RULES"
            "\n- **Conversational Response**: Reply in the SAME LANGUAGE the user used (e.g., Polish for Polish input)."
            "\n- **Code & Artifacts**: ALL source code, comments, file names, variable names MUST be in ENGLISH."
            "\n\n## CRITICAL: TOOL USAGE"
            "\n**ALWAYS use tools when asked to perform actions or answer questions about the project.** "
            "\n- **AUTONOMY FIRST**: Do NOT ask the user for file paths, variable names, or code snippets if you can find them yourself. Use `search_in_files`, `list_directory`, or `find_references` to discover the context."
            "\n- Never say 'I cannot' or 'I am unable to' without first ATTEMPTING to use the appropriate tool."
            "\n- If the user asks about project status, implementation plan, or structure: **SEARCH FOR IT**. "
            "Examine `README.md`, any `.md` files, `package.json`, or directory structures using `get_workspace_structure`."
            "\n- If a tool fails, report the actual error."
            "\n\n## YOUR CAPABILITIES"
            "\nYou have access to these tools:"
            "\n- `read_file(path, start_line, end_line)` - Read file content (use line ranges for large files)"
            "\n- `edit_file(path, old_string, new_string)` - **PREFERRED** for editing. Replace exact text."
            "\n- `apply_diff(path, diff)` - Apply unified diff for complex multi-section changes"
            "\n- `create_file(path, content)` - Create NEW files only"
            "\n- `write_file(path, content)` - Overwrite entire file (use sparingly)"
            "\n- `list_directory(path)` - List files and folders"
            "\n- `search_in_files(pattern, path, is_regex)` - Find code/text across files"
            "\n- `find_references(symbol, path)` - Find all usages of a symbol (LSP)"
            "\n- `get_file_outline(path)` - Get functions/classes in a file"
            "\n- `get_workspace_structure(max_depth)` - Get project directory tree"
            "\n- `get_active_file_context()` - Get currently open editor content"
            "\n- `get_workspace_diagnostics()` - Get all errors/warnings in workspace"
            "\n- `run_terminal_command(command, cwd)` - Run shell commands (PowerShell on Windows)"
            "\n- `execute_vscode_command(command, args)` - Execute any VS Code command"
            "\n- `get_workspace_config(section)` - Read VS Code settings"
            "\n- `update_workspace_config(section, key, value)` - Update VS Code settings"
            "\n- `log_thought(thought)` - Log your reasoning process"
            "\n\n## ENVIRONMENT"
            "\n- **Operating System**: Windows"
            "\n- **Terminal**: PowerShell (use `dir`, `del`, `copy` instead of `ls`, `rm`, `cp`)"
            "\n- **Privileges**: FULL ACCESS to terminal and VS Code API."
            "\n\n## 📊 PRESENTATION & SUMMARIES (CRITICAL)"
            "\n- **Visual Structure**: Use **Bullet Points**, **Numbered Lists**, and **Markdown Tables** to make summaries readable."
            "\n- **Spacing**: Use adequate whitespace (newlines) between sections for clarity."
            "\n- **Code Blocks**: Always use triple backticks with language identifiers for code snippets (e.g., ```python)."
            "\n- **Analysis & Findings**: When presenting analysis or search results, ALWAYS use structured formats (lists/tables). Avoid unstructured text walls."
            "\n- **Categorization**: Group findings into logical sections (e.g., Analysis, Changes Made, Next Steps)."
            "\n- **Conciseness**: Avoid long paragraphs; prefer concise, actionable points."
            "\n- **Readability**: Avoid dense blocks of text. Break complex information into multiple bullet points."
            "\n- **No-Repeat Rule**: If a result (like file content or command output) was already shown in a previous step, summarize it in ONE sentence (e.g., 'File updated as requested'). Do NOT re-print full content."
            "\n- **Boldness**: Use **bold** for file paths and key technical terms."

            "\n\n## CODING WORKFLOW (CRITICAL)"
            "\n1. **UNDERSTAND FIRST**: Before any edit, read the relevant file sections"
            "\n2. **PLAN**: Use `log_thought` to explain your approach"
            "\n3. **EDIT SAFELY**: Use `edit_file` with enough context (2-3 lines before/after) to ensure unique match"
            "\n4. **VERIFY**: After edits, read the file again to confirm changes"
            "\n\n## EDIT_FILE BEST PRACTICES"
            "\n- Include 2-3 lines of unchanged code BEFORE and AFTER the target text"
            "\n- Match whitespace and indentation EXACTLY"
            "\n- If edit fails with 'not found', re-read the file - content may have changed"
            "\n- If edit fails with 'multiple matches', include more context lines"
            "\n- For large changes, use `apply_diff` or break into multiple `edit_file` calls"
            "\n\n## ERROR HANDLING"
            "\n- If a tool times out, report the error - DO NOT retry in a loop"
            "\n- If you see repeated errors, STOP and explain the issue"
            "\n- Always report what you tried and what failed"
            "\n\n## RESPONSE STYLE"
            "\n- Be concise but thorough"
            "\n- Use `log_thought` for internal reasoning (don't put it in your response)"
            "\n- Show code changes you made with clear file paths"
            "\n- Explain what you changed and why"
        )

    def _create_agent(self, model_name: str) -> Agent:
        """Factory method to create a localized agent instance."""
        model = GoogleModel(
            model_name,
            provider=self._provider
        )
        
        sys_prompt = self._get_base_system_prompt()

        agent = Agent(
            model=model,
            deps_type=AgentDependencies,
            system_prompt=sys_prompt
        )
        # Store raw prompt for debugging
        agent._raw_sys_prompt = sys_prompt
        
        # Register tools for every agent instance
        register_file_tools(agent, self.adapter)
        register_vscode_tools(agent)
        
        return agent
    
    async def load_dynamic_context(self) -> str:
        """Load project context and session memory for prompt enrichment."""
        context_parts = []
        
        try:
            # Load project context (package.json, pyproject.toml, etc.)
            await self.context_loader.load_context()
            project_ctx = self.context_loader.get_prompt_context()
            if project_ctx:
                context_parts.append(project_ctx)
        except Exception as e:
            logger.warning(f"Could not load project context: {e}")
        
        try:
            # Load session memory (learned patterns, history)
            memory_ctx = self.session_memory.get_prompt_context()
            if memory_ctx:
                context_parts.append(memory_ctx)
        except Exception as e:
            logger.warning(f"Could not load session memory: {e}")
        
        self._project_context = "\n".join(context_parts)
        return self._project_context
        
    async def chat(self, user_input: str, history: list[Any] | None = None) -> str:
        # Legacy method fallback
        full_text = ""
        async for chunk in self.chat_stream(user_input, history):
            full_text += chunk
        return full_text

    async def chat_stream(self, user_input: str, history: list[Any] | None = None, mode: Agentmode = Agentmode.FAST_TOOL, interaction_id: str | None = None, step_id: str | None = None):
        """
        Streams the agent's response (delta-style), selecting the appropriate model based on mode.
        """
        # Load dynamic context on first call or periodically
        if not self._project_context:
            await self.load_dynamic_context()
        
        deps = AgentDependencies(
            adapter=self.adapter,
            interaction_id=interaction_id,
            step_id=step_id,
            session_memory=self.session_memory
        )
        
        # Select sub-agent
        target_agent = self.thinking_agent if mode == Agentmode.DEEP_THINKING else self.fast_agent
        logger.info(f"Agent routing to: {'Thinking Agent' if mode == Agentmode.DEEP_THINKING else 'Fast Agent'}")
        
        # Build enhanced prompt with context
        enhanced_prompt = user_input
        if self._project_context:
            enhanced_prompt = f"{user_input}\n\n---\n{self._project_context}"
        
        # Prepare full debug payload
        debug_payload = {
            "component": "VCCAAgent", 
            "mode": str(mode),
            "prompt": user_input,
            "has_project_context": bool(self._project_context),
        }
        
        # Safely extra system prompt
        try:
            if hasattr(target_agent, '_raw_sys_prompt'):
                debug_payload["system_prompt"] = target_agent._raw_sys_prompt
            # Check if it's a simple string attribute
            elif hasattr(target_agent, 'system_prompt'):
                sp = target_agent.system_prompt
                debug_payload["system_prompt"] = str(sp)
            else:
                 debug_payload["system_prompt"] = "[Unknown - Attribute missing]"
        except Exception as e:
            debug_payload["system_prompt"] = f"[Error retrieving prompt: {e}]"

        if history is not None:
            # We explicitly check for None, as empty list [] is valid history (length 0)
            try:
                # Attempt to serialize history items (likely ModelMessage objects)
                debug_history = []
                for i, msg in enumerate(history):
                    if hasattr(msg, "model_dump"):
                        dump = msg.model_dump(exclude_none=True)
                        # Add index for clarity
                        dump['_index'] = i
                        # Simplify parts for readability
                        if 'parts' in dump and isinstance(dump['parts'], list):
                            simplified_parts = []
                            for part in dump['parts']:
                                if isinstance(part, dict):
                                    # Keep only essential fields
                                    if 'content' in part:
                                        simplified_parts.append({
                                            'type': part.get('part_kind', 'unknown'),
                                            'content': str(part['content'])[:200] + '...' if len(str(part.get('content', ''))) > 200 else part.get('content', '')
                                        })
                                    elif 'tool_name' in part:
                                        simplified_parts.append({
                                            'type': 'tool_call' if 'args' in part else 'tool_return',
                                            'tool': part.get('tool_name'),
                                            'args': part.get('args', {}),
                                            'result': str(part.get('content', ''))[:200] + '...' if 'content' in part and len(str(part.get('content', ''))) > 200 else part.get('content')
                                        })
                            dump['parts'] = simplified_parts
                        debug_history.append(dump)
                    elif hasattr(msg, "kind") and hasattr(msg, "parts"):
                        debug_history.append({"_index": i, "kind": msg.kind, "parts": str(msg.parts)[:500]})
                    else:
                        debug_history.append({"_index": i, "raw": str(msg)[:500]})
                
                debug_payload["history"] = debug_history
                debug_payload["history_length"] = len(history)
            except Exception as e:
                debug_payload["history"] = f"Error serializing history: {e}"
        else:
             debug_payload["history"] = "None (No history provided)"

        await self.adapter.log_debug("llm_req", debug_payload, interaction_id=interaction_id, step_id=step_id)

        # DEBUG: Log tool registration status
        try:
            # Check different possible attributes for tools
            tools_count = 0
            tool_names = []
            
            if hasattr(target_agent, '_function_toolset'):
                toolset = target_agent._function_toolset
                # _function_toolset is internal, count registered functions differently
                # Try accessing internal _function_tools dict
                if hasattr(toolset, '_function_tools'):
                    tools_dict = toolset._function_tools
                    tools_count = len(tools_dict)
                    tool_names = list(tools_dict.keys())[:15]
                else:
                    # Fallback: count public methods (not ideal)
                    public_attrs = [k for k in dir(toolset) if not k.startswith('_')]
                    tools_count = len(public_attrs)
                    tool_names = public_attrs[:10]
            
            tools_info = {
                "tools_registered": tools_count,
                "tool_names": tool_names,
                "agent_type": str(type(target_agent)),
                "has_function_toolset": hasattr(target_agent, '_function_toolset'),
                "toolset_type": str(type(target_agent._function_toolset)) if hasattr(target_agent, '_function_toolset') else None
            }
            logger.info(f"Agent tools status: {tools_info}")
            await self.adapter.log_debug("tools_status", tools_info, interaction_id=interaction_id, step_id=step_id)
        except Exception as e:
            logger.error(f"Could not log tools status: {e}", exc_info=True)

        try:
            # We must await the run_stream carefully. 
            # Use enhanced_prompt which includes project context
            async with target_agent.run_stream(enhanced_prompt, deps=deps, message_history=history) as result:
                last_len = 0
                full_text = ""
                async for text in result.stream_text():
                    delta = text[last_len:]
                    last_len = len(text)
                    full_text = text # Accumulate for logging
                    if delta:
                        yield delta
                
                # Check for new messages to update history
                if history is not None:
                    # pydantic_ai does not modify history in-place always.
                    # We capture new messages (User + ToolCalls + ToolReturns + ModelResponse)
                    new_messages = result.new_messages()
                    if new_messages:
                        # Log what's being added to history
                        await self.adapter.log_debug("history_update", {
                            "new_messages_count": len(new_messages),
                            "new_messages_kinds": [msg.kind if hasattr(msg, 'kind') else type(msg).__name__ for msg in new_messages],
                            "total_history_after": len(history) + len(new_messages)
                        }, interaction_id=interaction_id, step_id=step_id)
                        
                        history.extend(new_messages)
                        
                        # Log tools usage to Debug panel
                        for msg in new_messages:
                            # if msg is a ModelResponse with tool calls
                            if hasattr(msg, 'parts'):
                                for part in msg.parts:
                                    if hasattr(part, 'tool_name'): # ToolCallPart
                                        await self.adapter.log_debug("tool_call", {
                                            "tool": part.tool_name,
                                            "args": getattr(part, 'args', {})
                                        }, interaction_id=interaction_id, step_id=step_id)
                                    elif hasattr(part, 'content') and hasattr(part, 'tool_name'): # ToolReturnPart in some versions?
                                        # In pydantic-ai, ToolReturn is usually in a ModelRequest from the agent to itself
                                        pass
                            
                            # if msg is a ModelRequest with tool returns
                            if hasattr(msg, 'parts'):
                                for part in msg.parts:
                                    if hasattr(part, 'tool_name') and hasattr(part, 'content'): # ToolReturnPart
                                        res_str = str(part.content)
                                        await self.adapter.log_debug("tool_res", {
                                            "tool": part.tool_name,
                                            "result": res_str[:1000] + "..." if len(res_str) > 1000 else res_str
                                        }, interaction_id=interaction_id, step_id=step_id)
                
                # Log verified files and written files summary
                if deps.verified_files or deps.written_files:
                    summary = {}
                    if deps.written_files:
                        summary["files_written"] = list(deps.written_files)
                    if deps.verified_files:
                        summary["files_verified"] = list(deps.verified_files)
                    
                    await self.adapter.log_debug("files_summary", summary, 
                                                interaction_id=interaction_id, 
                                                step_id=step_id)

                await self.adapter.log_debug("llm_res", {
                    "component": "VCCAAgent",
                    "output_preview": full_text[:500] + "..." if len(full_text) > 500 else full_text
                }, interaction_id=interaction_id, step_id=step_id)

        except RuntimeError as e:
            if "Event loop is closed" in str(e):
                 # This is a pytest-asyncio specific issue with how pydantic-ai manages loops vs pytest
                 # Fallback to non-stream for test safety?
                 # Or just log it.
                 logger.error(f"Event loop error: {e}")
                 # Try synchronous run? No, everything is async.
                 # Just try to yield error.
                 yield f"Error executing request: {e}"
            else:
                 logger.error(f"Runtime error in chat_stream: {e}")
                 yield f"Error executing request: {e}"
        except Exception as e:
            logger.error(f"Error in chat_stream: {e}")
            yield f"Error executing request: {e}"
