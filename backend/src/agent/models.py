from __future__ import annotations
from enum import Enum
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

class TaskComplexity(str, Enum):
    SIMPLE = "simple"   # Chat, simple query, single file read
    MEDIUM = "medium"   # Single file edit, basic explanation
    COMPLEX = "complex" # Multi-file edit, debugging, architecture, reasoning

class Agentmode(str, Enum):
    CHAT = "chat"           # Just talk, no tools needed (or basic retrieval)
    FAST_TOOL = "fast_tool" # Needs tools but task is simple
    DEEP_THINKING = "deep"  # Needs complex reasoning and potentially multiple tool steps
    PLANNING = "planning"   # Creating or updating a plan

class IntentAnalysis(BaseModel):
    """Structured output from the Intent Router."""
    original_prompt: str = Field(description="The original user input")
    refined_prompt: str = Field(description="A clear, technical reformulation of the user's intent. Fix ambiguities.")
    complexity: TaskComplexity = Field(description="Estimated complexity of the task")
    suggested_mode: Agentmode = Field(description="Which agent mode is best suited")
    relevant_files: List[str] = Field(default_factory=list, description="List of filenames mentioned or implied by context")
    reasoning: str = Field(description="Brief explanation of why this mode/complexity was chosen")

# --- Planner / Orchestrator Models ---

class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    WAITING_FOR_USER = "waiting_for_user" # For clarifications or approval
    SKIPPED = "skipped"

class TaskStep(BaseModel):
    id: str = Field(description="Unique ID of the step (e.g., '1', '2')")
    title: str = Field(description="Short title of the step")
    description: str = Field(description="Detailed description for the agent")
    status: StepStatus = Field(default=StepStatus.PENDING)
    result: Optional[str] = Field(default=None, description="Output/Result of the step")
    mode: Agentmode = Field(default=Agentmode.FAST_TOOL, description="Agent mode for this step")

class ExecutionPlan(BaseModel):
    original_request: str
    refined_goal: str
    steps: List[TaskStep]
    requires_approval: bool = False
    
class SessionState(BaseModel):
    interaction_id: Optional[str] = None
    plan: Optional[ExecutionPlan] = None
    chat_history: List[Any] = Field(default_factory=list) 
    is_paused: bool = False
    waiting_for_input: bool = False

