from typing import Literal, Union, Any, Optional
from pydantic import BaseModel, Field

class BaseMessage(BaseModel):
    type: str
    id: str | None = None

# --- Incoming Messages (Client -> Server) ---

class ConfigMessage(BaseMessage):
    type: Literal["config"]
    sample_rate: int = 16000
    chunk_size: int = 4096
    language: str | None = None

class AudioChunkMessage(BaseMessage):
    type: Literal["audio_chunk"]
    data: str  # Base64 encoded PCM data

class TextMessage(BaseMessage):
    type: Literal["text_input"]
    text: str

class ClearContextMessage(BaseMessage):
    type: Literal["clear_context"]

class StopGenerationMessage(BaseMessage):
    type: Literal["stop_generation"]

class ToggleTTSMessage(BaseMessage):
    type: Literal["toggle_tts"]
    enabled: bool

IncomingMessage = Union[ConfigMessage, AudioChunkMessage, TextMessage, ClearContextMessage, StopGenerationMessage, ToggleTTSMessage]

# --- Outgoing Messages (Server -> Client) ---

class StatusMessage(BaseMessage):
    type: Literal["status"]
    # Allow any string for status to be flexible with UI
    status: str 
    message: str | None = None

class TTSStatusMessage(BaseMessage):
    type: Literal["tts_status"]
    status: Literal["started", "stopped", "error"]
    message_id: str | None = None
    error: str | None = None

class TranscriptMessage(BaseMessage):
    type: Literal["transcript"]
    text: str
    is_final: bool = False

class AgentResponseMessage(BaseMessage):
    type: Literal["response"]
    text: str
    is_delta: bool = True  # Streaming tokens
    is_final: bool = False

class ToolUsageMessage(BaseMessage):
    type: Literal["tool_usage"]
    tool_name: str
    input_data: dict[str, Any]
    call_id: str | None = None

class ToolResultMessage(BaseMessage):
    type: Literal["tool_result"]
    output: Any
    call_id: str | None = None

class TTSAudioMessage(BaseMessage):
    type: Literal["tts_audio"]
    data: str  # base64 encoded audio
    is_final: bool = False

class AgentActionMessage(BaseMessage):
    type: Literal["agent_action"]
    action_type: Literal["thinking", "tool_start", "tool_end", "info"]
    action_label: str | None = None
    action_details: str | None = None
    action_status: Literal["running", "success", "failure"] = "running"
    tool_name: str | None = None
    input_data: dict[str, Any] | None = None
    call_id: str | None = None
    interaction_id: str | None = None
    step_id: str | None = None

class StepStartMessage(BaseMessage):
    type: Literal["step_start"]
    payload: dict[str, Any]

class StepCompleteMessage(BaseMessage):
    type: Literal["step_complete"]
    payload: dict[str, Any]

class PlanCreatedMessage(BaseMessage):
    type: Literal["plan_created"]
    payload: dict[str, Any]

class ErrorMessage(BaseMessage):
    type: Literal["error"]
    error: str
    message: str | None = None

class CommandMessage(BaseMessage):
    type: Literal["command"]
    command: str
    args: dict[str, Any] | None = None

class DebugMessage(BaseMessage):
    type: Literal["debug"]
    category: str # "llm", "tool", "system"
    data: Any
    interaction_id: str | None = None
    step_id: str | None = None

OutgoingMessage = Union[StatusMessage, TranscriptMessage, AgentResponseMessage, ToolUsageMessage, TTSAudioMessage, TTSStatusMessage, ErrorMessage, AgentActionMessage, CommandMessage, DebugMessage, StepStartMessage, StepCompleteMessage, PlanCreatedMessage]
IncomingMessage = Union[ConfigMessage, AudioChunkMessage, TextMessage, ClearContextMessage, StopGenerationMessage, ToolResultMessage, ToggleTTSMessage]
