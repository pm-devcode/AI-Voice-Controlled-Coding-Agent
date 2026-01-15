"""Structured Agent with JSON protocol for tool execution."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, AsyncIterator, Callable, Awaitable

from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from backend.src.config import get_settings
from backend.src.adapters.base import FilesystemAdapter
from backend.src.agent.structured_protocol import (
    StructuredAgentResponse,
    AgentResponseType,
    ToolCall,
    ToolResult,
    ToolResultsMessage,
    get_structured_system_prompt,
)
from backend.src.agent.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

# Maximum iterations to prevent infinite loops
MAX_TOOL_ITERATIONS = 10


class StructuredAgent:
    """
    Agent that uses structured JSON protocol for tool execution.
    
    Instead of letting pydantic-ai automatically execute tools,
    this agent:
    1. Asks LLM for a structured JSON response
    2. Parses the response to extract tool calls
    3. Executes tools ourselves with full control
    4. Sends results back to LLM
    5. Repeats until final response
    """
    
    def __init__(self, adapter: FilesystemAdapter, ui_callback: Callable[[str, Any], Awaitable[None]] | None = None):
        self.adapter = adapter
        self.settings = get_settings()
        self.tool_executor = ToolExecutor(adapter)
        self.ui_callback = ui_callback
        
        # Initialize provider
        api_key = self.settings.GEMINI_API_KEY
        self._provider = GoogleProvider(api_key=api_key) if api_key else None
        
        # Create the LLM model
        self._model = GoogleModel(
            self.settings.GEMINI_MODEL_FAST,
            provider=self._provider
        )
        
        # Build system prompt with tool descriptions
        self._system_prompt = get_structured_system_prompt(
            self.tool_executor.get_available_tools()
        )
        
        # Create agent with structured output
        self._agent = Agent(
            model=self._model,
            output_type=StructuredAgentResponse,
            system_prompt=self._system_prompt
        )
    
    async def _on_tool_start(self, tool_call: ToolCall):
        if self.ui_callback:
            if not tool_call.call_id:
                tool_call.call_id = str(uuid.uuid4())
                
            # Generate a nice label for the UI
            label = f"{tool_call.name}"
            await self.ui_callback("agent_action", {
                "action_type": "tool_start",
                "action_label": label,
                "tool_name": tool_call.name,
                "input_data": tool_call.args,
                "call_id": tool_call.call_id
            })

    async def _on_tool_end(self, result: ToolResult):
        if self.ui_callback:
            status = "success" if result.success else "failure"
            await self.ui_callback("agent_action", {
                "action_type": "tool_end",
                "action_status": status,
                "call_id": result.call_id,
                "output": result.result
            })

    async def run(
        self,
        user_prompt: str,
        history: list[dict] | None = None,
        context: str | None = None,
        interaction_id: str | None = None,
        step_id: str | None = None
    ) -> AsyncIterator[str]:
        """
        Run the structured agent loop.
        
        Yields text chunks as the agent responds.
        Handles tool execution internally.
        """
        # Conversation history starting with existing history if provided
        messages = list(history) if history else []
        
        # Build initial prompt
        # Prepend a confirmation that tools are ready to use
        tool_list = ", ".join([t["name"] for t in self.tool_executor.get_available_tools()])
        tool_header = f"[SYSTEM: ENVIRONMENT READY. Tools available: {tool_list}]\n\n"
        
        full_prompt = tool_header + user_prompt
        if context:
            full_prompt = f"{full_prompt}\n\n---\n## CONTEXT\n{context}"
        
        # Add current user request to history
        messages.append({"role": "user", "content": full_prompt})
        
        iteration = 0
        while iteration < MAX_TOOL_ITERATIONS:
            iteration += 1
            logger.info(f"Structured agent iteration {iteration}")
            
            # Get LLM response
            try:
                response_text = await self._call_llm(messages)
                logger.debug(f"LLM raw response: {response_text[:500]}...")
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                yield f"Error calling LLM: {e}"
                return
            
            # Parse structured response
            try:
                parsed = self._parse_response(response_text)
            except Exception as e:
                logger.error(f"Failed to parse LLM response: {e}")
                logger.debug(f"Raw response was: {response_text}")
                # Try to extract any useful text
                yield f"Error parsing response: {e}\n\nRaw: {response_text[:500]}"
                return
            
            # Log reasoning if present
            if parsed.reasoning:
                await self.adapter.log_debug(
                    "agent_reasoning",
                    {"reasoning": parsed.reasoning},
                    interaction_id=interaction_id,
                    step_id=step_id
                )
            
            # Handle response based on type
            if parsed.response_type == AgentResponseType.FINAL_RESPONSE:
                # Agent is done
                logger.info("Agent provided final response")
                if parsed.response:
                    yield parsed.response
                return
            
            elif parsed.response_type == AgentResponseType.CLARIFICATION:
                # Agent needs more info - yield the question
                logger.info("Agent requesting clarification")
                if parsed.response:
                    yield parsed.response
                return
            
            elif parsed.response_type == AgentResponseType.TOOL_REQUEST:
                # Agent wants to use tools
                if not parsed.tools:
                    logger.warning("Tool request but no tools specified")
                    yield "Agent requested tools but didn't specify which ones."
                    return
                
                # Check if this response is substantially different from thoughts already shared
                # Avoid yielding full summaries during tool requests to prevent repetition
                if parsed.response and len(parsed.response) < 200:
                    yield f"{parsed.response}\n"

                # Log tool requests
                await self.adapter.log_debug(
                    "tool_requests",
                    {"tools": [t.model_dump() for t in parsed.tools]},
                    interaction_id=interaction_id,
                    step_id=step_id
                )
                

                # Execute tools with granular event tracking
                results = await self.tool_executor.execute_tools_with_hooks(
                    parsed.tools,
                    on_start=self._on_tool_start,
                    on_end=self._on_tool_end
                )
                  
                # Log results
                await self.adapter.log_debug(
                    "tool_results",
                   {"results": [r.model_dump() for r in results]},
                    interaction_id=interaction_id,
                    step_id=step_id
                )
                
                # Yield short success indicator for each tool (unless it failed)
                for result in results:
                    if result.success:
                        # Truncate result for status message
                        res_preview = result.result[:100].replace('\n', ' ')
                        if len(result.result) > 100:
                            res_preview += "..."
                        # DO NOT yield results to chat stream anymore (UI handles tool_trace events)
                        # yield f"✅ *{result.name}*: {res_preview}\n"
                    else:
                        pass
                        # yield f"❌ *{result.name} failed*: {result.result}\n"
                
                # Add LLM response to history
                messages.append({
                    "role": "assistant",
                    "content": response_text
                })
                
                # Add tool results as user message
                results_message = self._format_tool_results(results)
                messages.append({
                    "role": "user",
                    "content": results_message
                })
                
                # Continue loop for next iteration
                continue
        
        # Max iterations reached
        logger.warning(f"Max iterations ({MAX_TOOL_ITERATIONS}) reached")
        yield "\n\n⚠️ Maximum tool iterations reached. Task may be incomplete."
    
    async def _call_llm(self, messages: list[dict]) -> str:
        """Call the LLM with the conversation history using pydantic-ai."""
        # Convert our simple history to pydantic-ai format
        from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart
        
        history = []
        last_prompt = ""
        
        for i, msg in enumerate(messages):
            role = msg["role"]
            content = msg["content"]
            
            # Last user message is the current prompt, not history
            if i == len(messages) - 1 and role == "user":
                last_prompt = content
                continue
            
            if role == "user":
                history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
            elif role == "assistant":
                # If assistant content is JSON (from structured agent), 
                # we should ideally pass it back as a message.
                history.append(ModelResponse(parts=[TextPart(content=content)]))
        
        # Use pydantic-ai agent with output_type to enforce structured output
        try:
            result = await self._agent.run(last_prompt, message_history=history)
            
            # In pydantic-ai, structured output is ideally available via .data
            if hasattr(result, "data") and result.data is not None:
                # If it's the expected model, dump to JSON
                if hasattr(result.data, "model_dump_json"):
                    return result.data.model_dump_json()
                # If it's a dict or other serializable
                try:
                    return json.dumps(result.data)
                except:
                    pass
                
            # Fallback 1: Check result.response (ModelResponse)
            response = getattr(result, "response", result)
            if hasattr(response, "parts"):
                for part in response.parts:
                    # Look for tool call to 'final_result' (pydantic-ai's way of returning result_type)
                    if hasattr(part, "tool_name") and part.tool_name == "final_result":
                        if hasattr(part, "args") and isinstance(part.args, dict):
                            return json.dumps(part.args)
                    
                    # Look for plain text if everything else fails
                    if hasattr(part, "content") and part.content:
                        return part.content
                    if hasattr(part, "text") and part.text:
                        return part.text

            # Fallback 2: Check all_messages for the last ModelResponse
            if hasattr(result, "all_messages"):
                msgs = result.all_messages()
                if msgs:
                    last_msg = msgs[-1]
                    if hasattr(last_msg, "parts"):
                        for part in last_msg.parts:
                            if hasattr(part, "tool_name") and part.tool_name == "final_result":
                                if hasattr(part, "args") and isinstance(part.args, dict):
                                    return json.dumps(part.args)

            # Last resort: string representation
            return str(response)
        except Exception as e:
            logger.error(f"Pydantic-AI agent call failed: {e}")
            raise
    
    def _parse_response(self, response_text: str) -> StructuredAgentResponse:
        """Parse LLM response into structured format."""
        # Clean up response - remove markdown code blocks if present
        text = response_text.strip()
        
        # Try to extract JSON from code blocks
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if json_match:
            text = json_match.group(1).strip()
        
        # Also try to find JSON object directly
        json_obj_match = re.search(r'\{[\s\S]*\}', text)
        if json_obj_match:
            text = json_obj_match.group(0)
        
        # Parse JSON
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            # Try to fix common issues
            # Sometimes LLM adds trailing commas
            text = re.sub(r',\s*}', '}', text)
            text = re.sub(r',\s*]', ']', text)
            data = json.loads(text)
        
        # Convert to structured response
        response_type = data.get("response_type", "final_response")
        if isinstance(response_type, str):
            response_type = AgentResponseType(response_type)
        
        tools = []
        for t in data.get("tools", []):
            tools.append(ToolCall(
                name=t.get("name", ""),
                args=t.get("args", {})
            ))
        
        return StructuredAgentResponse(
            response_type=response_type,
            reasoning=data.get("reasoning"),
            tools=tools,
            response=data.get("response"),
            confidence=data.get("confidence", 1.0)
        )
    
    def _format_tool_results(self, results: list[ToolResult]) -> str:
        """Format tool results as a message for the LLM."""
        parts = ["Here are the tool execution results:\n"]
        
        for r in results:
            status = "✓ SUCCESS" if r.success else "✗ FAILED"
            parts.append(f"### {r.name} [{status}]")
            
            # Truncate very long results
            result_text = r.result
            if len(result_text) > 5000:
                result_text = result_text[:2500] + "\n\n[... truncated ...]\n\n" + result_text[-2500:]
            
            parts.append(f"```\n{result_text}\n```\n")
        
        parts.append("\nNow analyze these results and either:")
        parts.append("1. Request more tools if needed (response_type: 'tool_request')")
        parts.append("2. Provide your final response (response_type: 'final_response')")
        parts.append("\nRespond with JSON only.")
        
        return "\n".join(parts)


class HybridAgent:
    """
    Hybrid agent that uses structured protocol for complex tasks
    and simple chat for conversations.
    """
    
    def __init__(self, adapter: FilesystemAdapter):
        self.adapter = adapter
        self.structured_agent = StructuredAgent(adapter)
        self.settings = get_settings()
        
        # Simple chat agent for non-tool interactions
        api_key = self.settings.GEMINI_API_KEY
        provider = GoogleProvider(api_key=api_key) if api_key else None
        model = GoogleModel(self.settings.GEMINI_MODEL_FAST, provider=provider)
        
        self._chat_agent = Agent(
            model=model,
            system_prompt=(
                "You are VCCA, a friendly AI coding assistant. "
                "Respond naturally in the same language the user uses. "
                "For coding tasks, be concise and helpful."
            )
        )
    
    async def run(
        self,
        user_prompt: str,
        use_tools: bool = True,
        context: str | None = None,
        interaction_id: str | None = None,
        step_id: str | None = None
    ) -> AsyncIterator[str]:
        """
        Run the appropriate agent based on task type.
        
        Args:
            user_prompt: User's request
            use_tools: If True, use structured agent with tools
            context: Additional context
            interaction_id: For logging
            step_id: For logging
        """
        if use_tools:
            # Use structured agent for tool-requiring tasks
            async for chunk in self.structured_agent.run(
                user_prompt,
                context=context,
                interaction_id=interaction_id,
                step_id=step_id
            ):
                yield chunk
        else:
            # Use simple chat for conversations
            result = await self._chat_agent.run(user_prompt)
            yield result.data
