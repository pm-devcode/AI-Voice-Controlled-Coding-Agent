"""Structured JSON protocol models for agent communication."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """A single tool call request from LLM."""

    name: str = Field(description="Tool function name")
    args: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    call_id: str | None = Field(default=None, description="Unique ID for tracking")


class ToolResult(BaseModel):
    """Result of a single tool execution."""

    name: str = Field(description="Tool function name")
    call_id: str | None = Field(default=None, description="Matching call_id")
    success: bool = Field(description="Whether tool executed successfully")
    result: str = Field(description="Tool output or error message")
    duration_ms: int | None = Field(default=None, description="Execution time in ms")


class AgentResponseType(str, Enum):
    """Type of agent response."""

    TOOL_REQUEST = "tool_request"  # Agent wants to use tools
    FINAL_RESPONSE = "final_response"  # Agent is done, has response
    CLARIFICATION = "clarification"  # Agent needs more info from user


class StructuredAgentResponse(BaseModel):
    """
    Structured response from LLM agent.
    
    The agent must respond in this format, allowing us to:
    1. Know exactly which tools it wants to use
    2. Execute tools ourselves with full control
    3. Track reasoning separately from output
    """

    response_type: AgentResponseType = Field(
        description="Type of response: tool_request, final_response, or clarification"
    )
    reasoning: str | None = Field(
        default=None,
        description="Agent's internal reasoning (shown in debug, not to user)"
    )
    tools: list[ToolCall] = Field(
        default_factory=list,
        description="List of tools to execute. Empty if final_response."
    )
    response: str | None = Field(
        default=None,
        description="Final response text to show user. Only set for final_response/clarification."
    )
    confidence: float = Field(
        default=1.0,
        description="Confidence level 0-1 in the response"
    )


class ToolResultsMessage(BaseModel):
    """Message sent back to LLM with tool execution results."""

    tool_results: list[ToolResult] = Field(
        description="Results of executed tools"
    )
    context: str | None = Field(
        default=None,
        description="Additional context if needed"
    )


# JSON Schema for prompting LLM
STRUCTURED_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "response_type": {
            "type": "string",
            "enum": ["tool_request", "final_response", "clarification"],
            "description": "Type of response"
        },
        "reasoning": {
            "type": "string",
            "description": "Your internal reasoning process (optional)"
        },
        "tools": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Tool function name"},
                    "args": {"type": "object", "description": "Tool arguments"}
                },
                "required": ["name"]
            },
            "description": "Tools to execute. Required if response_type is tool_request."
        },
        "response": {
            "type": "string",
            "description": "Final response to user. Required if response_type is final_response or clarification."
        }
    },
    "required": ["response_type"]
}


def get_structured_system_prompt(available_tools: list[dict]) -> str:
    """Generate system prompt that enforces structured JSON output."""
    
    tools_description = "\n".join([
        f"- `{t['name']}({', '.join(t.get('params', []))})` - {t.get('description', 'No description')}"
        for t in available_tools
    ])
    
    return f"""You are VCCA (Voice-Controlled Coding Agent), an expert AI coding assistant operating in a Windows environment.

## 💻 ENVIRONMENT & CAPABILITIES
You have FULL ACCESS to the local file system and VS Code workspace.
You can execute shell commands in the terminal (PowerShell) and invoke any VS Code API command.
You communicate with the system by generating a **Tool Execution Manifest** in JSON format.
Your commands are executed by a secure backend and the results are returned to you in the next turn.

## 🛠️ AVAILABLE TOOLS
You MUST use these tools to interact with the project:
{tools_description}

## 📝 RESPONSE PROTOCOL (JSON ONLY)
You MUST respond with a valid JSON object. NEVER say "I cannot access" or "I am an AI" - you are a privileged system agent.

Format:
```json
{{
  "response_type": "tool_request" | "final_response" | "clarification",
  "reasoning": "Brief technical logic for selecting these tools",
  "tools": [
    {{"name": "tool_name", "args": {{"arg1": "value1"}}}}
  ],
  "response": "Summary for the user (ONLY for final_response or clarification)"
}}
```

## 🚀 STRATEGY
1. **Explore**: Use `get_workspace_structure` or `list_directory` to find relevant files.
2. **Analyze**: Use `read_file` to understand content.
3. **Control**: Use `run_terminal_command` for builds, tests, or git operations. Use `execute_vscode_command` for IDE-specific actions.
4. **Execute**: Perform requested edits or searches.
5. **Iterate**: Use tool results to refine your next steps.
6. **Autonomy**: Never ask the user for information (file paths, code snippets, configs) that can be found in the workspace. Discover it yourself!

## 📊 PRESENTATION & SUMMARIES
- **Structure**: Use high-density information formats like **Bullet Points**, **Numbered Lists**, or **Tables**.
- **Analysis Results**: Present investigation findings in structured lists or tables.
- **Clarity**: When summarizing actions, group them by logical category (e.g., "Files Modified", "Terminal Tests", "Configuration Changes").
- **Tables**: Use Markdown tables to compare values, list diagnostics, or show step-by-step progress when appropriate.
- **Boldness**: Use **bold text** for important file paths, symbols, and status.
- **Silence**: Do NOT provide a `response` field (keep it null or empty) when requesting tools (`tool_request`) if you are just performing intermediate analysis steps. Only provide a `response` when you have a `final_response` or need `clarification`.

## LANGUAGE RULES
- **Conversational Response**: Reply in the SAME LANGUAGE the user used.
- **Code & Artifacts**: ALL source code and file names MUST be in ENGLISH.

Respond ONLY with the JSON object. No markdown blocks outside the JSON, no extra text."""
