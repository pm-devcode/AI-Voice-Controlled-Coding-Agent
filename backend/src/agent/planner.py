from __future__ import annotations
import logging
import os
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from backend.src.config import get_settings
from backend.src.agent.models import ExecutionPlan, TaskStep, StepStatus, Agentmode
from backend.src.agent.models import IntentAnalysis # Input might be this or raw text
from backend.src.adapters.base import FilesystemAdapter

logger = logging.getLogger(__name__)

class PlannerAgent:
    """
    Generates execution plans (Step-by-Step) from user requests.
    """
    def __init__(self, adapter: FilesystemAdapter | None = None):
        self.settings = get_settings()
        self.adapter = adapter
        
        api_key = self.settings.GEMINI_API_KEY
        provider = GoogleProvider(api_key=api_key) if api_key else None
        
        # We use a model capable of structure generation (e.g. Pro or Flash depending on complexity)
        # Using Thinking model might be overkill for simple lists, but good for "Refinement".
        # Let's use Flash for speed/cost unless "Thinking" is requested.
        model_name = self.settings.GEMINI_MODEL_FAST
        
        model = GoogleModel(
            model_name,
            provider=provider
        )

        sys_prompt = (
            "You are an expert Technical Planner for VCCA (Voice-Controlled Coding Agent)."
            "\nYour goal: Break down the user's coding request into a set of sequential, logical steps."
            "\n\n## LANGUAGE RULES (CRITICAL)"
            "\n- **MUST use the SAME LANGUAGE as the user's request for ALL step titles and descriptions**"
            "\n- If user writes in Polish → steps MUST be in Polish"
            "\n- If user writes in English → steps MUST be in English"
            "\n- **Code/Tech Specs**: Keep technical terms and code references in ENGLISH."
            "\n- Example: User says 'Zaplanuj weryfikację' → Step 1: 'Uzyskaj strukturę projektu' (Polish)"
            "\n\n## AVAILABLE TOOLS (for each step)"
            "\nThe executor agent has these tools:"
            "\n- `read_file(path, start_line, end_line)` - Read file content"
            "\n- `edit_file(path, old_string, new_string)` - Edit file by replacing exact text"
            "\n- `apply_diff(path, diff)` - Apply unified diff for complex changes"
            "\n- `create_file(path, content)` - Create new files"
            "\n- `search_in_files(pattern, path, is_regex)` - Find code/text"
            "\n- `find_references(symbol, path)` - Find symbol usages (LSP)"
            "\n- `get_file_outline(path)` - Get functions/classes structure"
            "\n- `get_workspace_structure(max_depth)` - Get directory tree"
            "\n- `get_workspace_diagnostics()` - Get errors/warnings"
            "\n- `run_terminal_command(command, cwd)` - Run shell commands (PowerShell on Windows)"
            "\n- `execute_vscode_command(command, args)` - Execute any VS Code command"
            "\n- `get_workspace_config(section)` - Read VS Code settings"
            "\n- `update_workspace_config(section, key, value)` - Update VS Code settings"
            "\n\n## ENVIRONMENT"
            "\n- **Operating System**: Windows (use `dir`, `del`, `copy` instead of `ls`, `rm`, `cp`)"
            "\n- **Terminal**: PowerShell 5.1"
            "\n- **Privileges**: FULL ACCESS to terminal and VS Code API."
            "\n\n## PLANNING GUIDELINES"
            "\n1. **Refine Goal**: Rephrase the user request into a clear technical objective."
            "\n2. **Breakdown**: Create 1 to N steps. Each step must be self-contained."
            "\n3. **Modes**: Assign the correct mode for each step:"
            "\n   - `fast_tool`: Simple file edits, reading, checks, search."
            "\n   - `deep`: Complex logic generation, debugging, multi-file refactoring."
            "\n   - `chat`: Asking user for info or explaining results."
            "\n4. **Approval**: Set `requires_approval = True` if modifying >3 files or deleting data."
            "\n5. **Step Dependencies**: Ensure each step builds on previous results."
            "\n6. **First Step**: Often should be reading/understanding existing code first. If paths are unknown, use `get_workspace_structure` or `run_terminal_command` (dir) FIRST."
            "\n7. **Autonomy**: Do NOT ask the user for information you can find yourself. Use tools to discover paths, symbols, and configs."
            "\n8. **Silent Execution & Final Report**: The execution of intermediate analysis steps should NOT produce chat summaries, only the logic/tools run. ALWAYS add a final step titled 'Final Summary/Report' (mode: `chat`) to present the collected findings to the user."
            "\n\n## OUTPUT FORMAT"
            "\nReturn ONLY a valid JSON object matching this structure:"
            "\n```json"
            "\n{"
            "\n  \"original_request\": \"...\","
            "\n  \"refined_goal\": \"...\","
            "\n  \"requires_approval\": false,"
            "\n  \"steps\": ["
            "\n    {"
            "\n      \"id\": \"1\","
            "\n      \"title\": \"Step Title\","
            "\n      \"description\": \"Detailed instructions for the executor...\","
            "\n      \"mode\": \"fast_tool\","
            "\n      \"status\": \"pending\""
            "\n    }"
            "\n  ]"
            "\n}"
            "\n```"
        )

        self.agent = Agent(
            model=model,
            system_prompt=sys_prompt
        )
        self.agent._raw_sys_prompt = sys_prompt
        
    async def create_plan(self, user_input: str, context_files: list[str] = None, interaction_id: str | None = None, history: list[Any] | None = None) -> ExecutionPlan:
        """
        Creates a new plan from scratch.
        For new tasks, history should be None or empty.
        """
        # Determine current environment info
        import platform
        os_info = f"{platform.system()} {platform.release()}"
        env_context = f"Operating System: {os_info} (Windows prefers 'dir'/'del', Unix prefers 'ls'/'rm')"
        
        prompt = f"User Request: {user_input}\n{env_context}\nContext Files: {context_files or []}\n\nReturn valid JSON."
        
        if self.adapter:
             debug_payload = {
                 "component": "Planner", 
                 "prompt": prompt,
             }
             
             # Extract safely
             if hasattr(self.agent, '_raw_sys_prompt'):
                 debug_payload["system_prompt"] = self.agent._raw_sys_prompt
             else:
                 # Fallback (old check)
                 sp = self.agent.system_prompt
                 debug_payload["system_prompt"] = str(sp)

             if history is not None and len(history) > 0:
                try:
                    debug_history = []
                    for i, msg in enumerate(history):
                        if hasattr(msg, "model_dump"):
                            dump = msg.model_dump(exclude_none=True)
                            dump['_index'] = i
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
                 debug_payload["history"] = "None (Fresh planning - no history)"
                 debug_payload["history_length"] = 0

             await self.adapter.log_debug("llm_req", debug_payload, interaction_id=interaction_id)

        try:
            result = await self.agent.run(prompt, message_history=history)
            
            # Inspect result to find data/content
            if hasattr(result, 'data'):
                text = result.data
            elif hasattr(result, 'content'): # Fallback for some versions
                text = result.content
            elif hasattr(result, 'output'):
                 text = result.output
            else:
                 logger.warning(f"Planner result attributes: {dir(result)}")
                 text = str(result)
            
            if self.adapter:
                 await self.adapter.log_debug("llm_res", {"component": "Planner", "output": text}, interaction_id=interaction_id)

            # Ensure json is imported before usage
            import json

            # Simple cleanup for Markdown blocks
            if isinstance(text, str):
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].strip()
            
            # If text is an object (unexpectedly), try to dump it
            if not isinstance(text, str):
                text = json.dumps(text)

            data = json.loads(text)
            return ExecutionPlan(**data)
        except Exception as e:
            logger.error(f"Planning failed: {e}")
            if 'result' in locals():
                logger.debug(f"Result type: {type(result)}")
                logger.debug(f"Result dir: {dir(result)}")
            
            # Fallback plan for errors
            return ExecutionPlan(
                original_request=user_input,
                refined_goal="Execute user request (Fallback)",
                steps=[
                    TaskStep(
                        id="1",
                        title="Execute Request",
                        description=f"Direct execution: {user_input}",
                        mode=Agentmode.DEEP_THINKING # Safer to default to deep
                    )
                ]
            )

    async def update_plan(self, current_plan: ExecutionPlan, user_feedback: str, history: list[Any] | None = None) -> ExecutionPlan:
        """
        Updates future steps based on feedback.
        """
        # We only want to replan PENDING steps.
        done_steps = [s for s in current_plan.steps if s.status in [StepStatus.DONE, StepStatus.FAILED]]
        # The agent returns a NEW plan, we merge it? 
        # Actually easier to just asking agent to output a FRESH ExecutionPlan based on "Remaining work".
        
        prompt = (
            f"Original Goal: {current_plan.refined_goal}\n"
            f"Completed Steps: {[s.title for s in done_steps]}\n"
            f"Current Situation: User provided feedback/change: '{user_feedback}'\n"
            f"Task: Update the REMAINING steps to accommodate this feedback. Do not list completed steps."
            "\nOutput JSON matching the ExecutionPlan structure."
        )

        if self.adapter:
             debug_payload = {
                 "component": "Planner", 
                 "prompt": prompt,
             }
             if hasattr(self.agent, '_raw_sys_prompt'):
                 debug_payload["system_prompt"] = self.agent._raw_sys_prompt
             
             if history is not None:
                try:
                    debug_history = []
                    for msg in history:
                        if hasattr(msg, "model_dump"):
                            debug_history.append(msg.model_dump(exclude_none=True))
                        elif hasattr(msg, "kind") and hasattr(msg, "parts"):
                             debug_history.append({"kind": msg.kind, "parts": str(msg.parts)})
                        else:
                            debug_history.append(str(msg))
                    debug_payload["history"] = debug_history
                except Exception as e:
                    debug_payload["history"] = f"Error serializing history: {e}"
             else:
                 debug_payload["history"] = "None"
            
             await self.adapter.log_debug("llm_req", debug_payload)
        
        try:
            result = await self.agent.run(prompt, message_history=history)
             # Parse output manually
            import json
            text = result.data
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].strip()
            
            new_plan_data = ExecutionPlan(**json.loads(text))
            
            # Merge: Keep old done steps, append new steps
            # Renumber IDs? Yes.
            
            merged_steps = [s for s in done_steps] # Immutable history
            
            start_id = len(merged_steps) + 1
            for i, step in enumerate(new_plan_data.steps):
                step.id = str(start_id + i)
                merged_steps.append(step)
                
            current_plan.steps = merged_steps
            current_plan.refined_goal = new_plan_data.refined_goal # Update goal if changed
            
            return current_plan
        except Exception as e:
             logger.error(f"Re-planning failed: {e}")
             return current_plan # Return original if fail
    
    async def extend_plan(
        self,
        current_plan: ExecutionPlan,
        additional_request: str,
        interaction_id: str | None = None,
        history: list[Any] | None = None
    ) -> ExecutionPlan:
        """
        Extends current plan with new steps based on additional user request.
        Updates refined_goal to reflect expanded scope.
        Keeps all existing steps (completed and pending).
        
        Args:
            current_plan: The existing execution plan
            additional_request: User's additional request (already refined by Intent Router)
            interaction_id: For logging
            history: Chat history for context
            
        Returns:
            Updated ExecutionPlan with expanded goal and new steps
        """
        # Summarize current plan state
        done_steps = [s for s in current_plan.steps if s.status == StepStatus.DONE]
        pending_steps = [s for s in current_plan.steps if s.status == StepStatus.PENDING]
        
        done_summary = "\n".join([f"  ✓ {s.title}" for s in done_steps]) or "  (none)"
        pending_summary = "\n".join([f"  ○ {s.title}" for s in pending_steps]) or "  (none)"
        
        prompt = f"""You are extending an existing execution plan.

CURRENT PLAN:
Goal: {current_plan.refined_goal}

Completed Steps:
{done_summary}

Pending Steps:
{pending_summary}

USER'S ADDITIONAL REQUEST:
{additional_request}

TASK:
1. Update refined_goal to reflect the EXPANDED scope (include both original and new work)
2. Keep ALL existing steps (both completed and pending) - DO NOT remove or modify them
3. Add NEW steps at the end to fulfill the additional request
4. Ensure new steps build on the completed work

Return a complete ExecutionPlan JSON with:
- refined_goal: (expanded to include new scope)
- steps: [all existing steps + new steps]
- requires_approval: (true if new steps modify >3 files or delete data)

IMPORTANT:
- Existing step IDs must stay the same
- New step IDs continue from {len(current_plan.steps) + 1}
- All existing step statuses must be preserved
- Only add steps, don't remove or reorder existing ones

Return valid JSON matching ExecutionPlan schema."""
        
        if self.adapter:
            await self.adapter.log_debug("llm_req", {
                "component": "Planner (extend)",
                "prompt": prompt,
                "current_goal": current_plan.refined_goal,
                "additional_request": additional_request
            }, interaction_id=interaction_id)
        
        try:
            result = await self.agent.run(prompt, message_history=history)
            
            import json
            text = result.data
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].strip()
            
            extended_plan_data = json.loads(text)
            extended_plan = ExecutionPlan(**extended_plan_data)
            
            # Validation: Ensure existing steps are preserved
            if len(extended_plan.steps) < len(current_plan.steps):
                logger.warning("Extended plan has fewer steps than original - using original")
                return current_plan
            
            logger.info(f"Plan extended: {len(current_plan.steps)} → {len(extended_plan.steps)} steps")
            return extended_plan
            
        except Exception as e:
            logger.error(f"Plan extension failed: {e}")
            return current_plan  # Return original on failure
    
    async def modify_plan(
        self,
        current_plan: ExecutionPlan,
        modification_request: str,
        interaction_id: str | None = None,
        history: list[Any] | None = None
    ) -> ExecutionPlan:
        """
        Modifies current plan based on user's change request.
        Can update pending steps, refined_goal, or add/remove steps.
        NEVER modifies completed steps.
        
        Args:
            current_plan: The existing execution plan
            modification_request: User's modification request (already refined by Intent Router)
            interaction_id: For logging
            history: Chat history for context
            
        Returns:
            Modified ExecutionPlan
        """
        done_steps = [s for s in current_plan.steps if s.status == StepStatus.DONE]
        pending_steps = [s for s in current_plan.steps if s.status == StepStatus.PENDING]
        in_progress = [s for s in current_plan.steps if s.status == StepStatus.IN_PROGRESS]
        
        done_summary = "\n".join([f"  ✓ {s.title}" for s in done_steps]) or "  (none)"
        pending_summary = "\n".join([f"  ○ {s.id}. {s.title} - {s.description}" for s in pending_steps]) or "  (none)"
        
        prompt = f"""You are modifying an existing execution plan based on user's change request.

CURRENT PLAN:
Goal: {current_plan.refined_goal}

Completed Steps (IMMUTABLE - cannot change):
{done_summary}

Pending Steps (can be modified):
{pending_summary}

USER'S MODIFICATION REQUEST:
{modification_request}

TASK:
1. Update refined_goal if the overall objective changed
2. KEEP all completed steps EXACTLY as-is (immutable)
3. Modify, add, or remove PENDING steps as needed
4. Ensure modified plan is still coherent and achievable

RULES:
- Completed step IDs, titles, and statuses MUST remain unchanged
- You can change pending step descriptions, modes, or order
- You can add new pending steps
- You can mark pending steps as SKIPPED if no longer needed
- Step IDs should be sequential

Return complete ExecutionPlan JSON with all steps (completed + modified pending)."""
        
        if self.adapter:
            await self.adapter.log_debug("llm_req", {
                "component": "Planner (modify)",
                "prompt": prompt,
                "current_goal": current_plan.refined_goal,
                "modification_request": modification_request
            }, interaction_id=interaction_id)
        
        try:
            result = await self.agent.run(prompt, message_history=history)
            
            import json
            text = result.data
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].strip()
            
            modified_plan_data = json.loads(text)
            modified_plan = ExecutionPlan(**modified_plan_data)
            
            # Validation: Ensure completed steps weren't changed
            modified_done = [s for s in modified_plan.steps if s.status == StepStatus.DONE]
            if len(modified_done) != len(done_steps):
                logger.warning("Modified plan changed completed steps - preserving original completed steps")
                # Merge: keep original done, use new pending
                modified_plan.steps = done_steps + [s for s in modified_plan.steps if s.status != StepStatus.DONE]
            
            logger.info(f"Plan modified: goal updated, {len(modified_plan.steps)} total steps")
            return modified_plan
            
        except Exception as e:
            logger.error(f"Plan modification failed: {e}")
            return current_plan  # Return original on failure
