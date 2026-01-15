"""Intent Router - classifies user input and refines prompts with context."""
from __future__ import annotations
import logging
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from backend.src.config import get_settings
from backend.src.agent.models import ExecutionPlan, StepStatus

logger = logging.getLogger(__name__)


class IntentType(Enum):
    """Types of user intents"""
    NEW_TASK = "new_task"           # Start completely new task
    CONTINUE_TASK = "continue"       # Add to current plan
    MODIFY_CURRENT = "modify"        # Change current plan
    CLARIFICATION = "clarify"        # Ask question about current context
    CANCEL = "cancel"                # Stop current plan
    CHAT = "chat"                    # General conversation


class IntentAnalysis(BaseModel):
    """Router output with refined prompt and classification"""
    intent: IntentType
    refined_prompt: str = Field(description="Clear technical description with resolved references")
    original_prompt: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="Why this intent + what was resolved")
    resolved_references: dict[str, str] = Field(default_factory=dict, description="Mapping of ambiguous refs to concrete ones")
    relevant_context: str = Field(default="", description="Context summary used for refinement")
    show_plan_only: bool = Field(default=False, description="If true, show plan for approval without executing")


class IntentRouter:
    """
    Analyzes user input to:
    1. Resolve ambiguous references (this, that, it)
    2. Add context from conversation history
    3. Classify intent type
    4. Generate refined technical prompt
    """
    
    def __init__(self, adapter=None):
        self.settings = get_settings()
        self.adapter = adapter
        
        # Setup Google provider
        provider = None
        if self.settings.GEMINI_API_KEY:
            provider = GoogleProvider(api_key=self.settings.GEMINI_API_KEY)
        
        # Use fast model for quick classification
        model = GoogleModel(
            self.settings.GEMINI_MODEL_FAST,
            provider=provider
        )
        
        sys_prompt = self._build_system_prompt()
        
        self.agent = Agent(
            model=model,
            system_prompt=sys_prompt
        )
        
        logger.info("Intent Router initialized")
    
    def _build_system_prompt(self) -> str:
        return """You are an Intent Analysis Agent for VCCA (Voice-Controlled Coding Agent).

## YOUR JOB
1. **Resolve ambiguities** - replace "to", "this", "that", "it" with specific references from context
2. **Add context** - incorporate relevant details from conversation history
3. **Classify intent** - determine what user wants to do
4. **Refine prompt** - create clear, technical prompt for executor

## INTENT TYPES
- **NEW_TASK**: User wants to start completely new task (ignore current plan)
- **CONTINUE_TASK**: User wants to add steps to current plan
- **MODIFY_CURRENT**: User wants to change/update current plan
- **CLARIFICATION**: User asks question about current context (no plan change)
- **CANCEL**: User wants to stop/cancel current plan
- **CHAT**: General conversation, greeting, or off-topic

## DECISION RULES
### NEW_TASK when:
- User explicitly says "new task", "start over", "create new"
- Request is unrelated to current plan's domain
- User changes topic completely

**SPECIAL CASE - Planning & Status Requests:**
- If user asks to "create a plan", "plan X", "zaplanuj X": Set intent: "new_task", show_plan_only: true.
- If user asks about project status, implementation plan, or "what is done":
    * Set intent: "new_task"
    * Refine to: "Analyze project documentation (README, PLAN.md, issues) and code structure to determine implementation status and current plan. Look for .md files."
    * This ensures the agent uses tools to find the answer instead of just chatting.

**Planning keywords (any language):**
- English: "create a plan", "make a plan", "plan for", "planning"
- Polish: "zaplanuj", "utwórz plan", "stwórz plan", "planowanie"
- Indicators: User wants to SEE the plan, not execute immediately

**Execution keywords (show_plan_only=false):**
- "implement", "create", "build", "add", "fix", "refactor"
- "zaimplementuj", "stwórz", "dodaj", "napraw"
- Indicators: User wants ACTION, not just planning

### CONTINUE_TASK when:
- User says "add", "also", "and then", "next"
- Request extends current plan's scope
- Uses "to this", "to that" referring to current work

### MODIFY_CURRENT when:
- User says "change", "update", "fix", "replace"
- Request alters existing plan or completed work
- Uses "instead of", "rather than"

### CLARIFICATION when:
- User asks "how", "why", "what", "explain"
- No action implied, just information request

### CANCEL when:
- User says "stop", "cancel", "abort", "nevermind"

### CHAT when:
- Greetings: "hi", "hello", "cześć"
- Unrelated: "what's the weather", "tell me a joke"

## REFERENCE RESOLUTION
Replace ambiguous words with concrete references:
- "to" / "tego" → specific file/function name
- "this" / "to" → specific component from last step
- "it" → specific object from context
- "there" → specific location/file

## OUTPUT FORMAT
Always return valid IntentAnalysis JSON:
{
  "intent": "continue",
  "refined_prompt": "Add unit tests for user_login function in auth.py using pytest",
  "original_prompt": "add tests to that",
  "confidence": 0.95,
  "reasoning": "User wants to add tests (CONTINUE). Resolved 'that' to user_login function from last step.",
  "resolved_references": {
    "that": "user_login function in auth.py"
  },
  "relevant_context": "Last step: Created user_login function in auth.py",
  "show_plan_only": false
}

CRITICAL: 
- intent field must be lowercase: "new_task", "continue", "modify", "clarify", "cancel", or "chat"
- show_plan_only: true ONLY for meta-planning requests ("create plan", "zaplanuj")

## EXAMPLES

### Example 1: Ambiguous continuation
Context: "Just created user_login function in auth.py"
Input: "Dodaj testy do tego"
Output:
{
  "intent": "continue",
  "refined_prompt": "Add unit tests for the user_login function in auth.py using pytest framework",
  "original_prompt": "Dodaj testy do tego",
  "confidence": 0.95,
  "reasoning": "User wants to add tests to recently created function. Resolved 'tego' to user_login function.",
  "resolved_references": {"tego": "user_login function in auth.py"}
}

### Example 2: Modification
Context: "Implemented fetch_users() with MongoDB in api.py"
Input: "Change it to use Redis instead"
Output:
{
  "intent": "modify",
  "refined_prompt": "Modify fetch_users() function in api.py to use Redis instead of MongoDB for data storage",
  "original_prompt": "Change it to use Redis instead",
  "confidence": 0.9,
  "reasoning": "User wants to modify existing implementation. Resolved 'it' to fetch_users function.",
  "resolved_references": {"it": "fetch_users() function"}
}

### Example 3: New unrelated task
Context: "Working on authentication system"
Input: "Create a new data visualization dashboard"
Output:
{
  "intent": "new_task",
  "refined_prompt": "Create a new data visualization dashboard with charts and graphs",
  "original_prompt": "Creat,
  "show_plan_only": false
}

### Example 3b: Meta-planning request (SHOW PLAN ONLY)
Context: Any
Input: "Zaplanuj weryfikację technologii w tym projekcie"
Output:
{
  "intent": "new_task",
  "refined_prompt": "Create and present an execution plan for technology verification in this project",
  "original_prompt": "Zaplanuj weryfikację technologii w tym projekcie",
  "confidence": 0.95,
  "reasoning": "User asks to CREATE A PLAN (meta-planning), not execute immediately. Set show_plan_only=true to present plan for approval first.",
  "resolved_references": {},
  "show_plan_only": truee a new data visualization dashboard",
  "confidence": 0.95,
  "reasoning": "User wants to start completely new task unrelated to current authentication work.",
  "resolved_references": {}
}

### Example 4: Question
Context: "Just added JWT authentication"
Input: "How does JWT token validation work?"
Output:
{
  "intent": "clarify",
  "refined_prompt": "Explain how JWT token validation works in the context of the recently implemented authentication",
  "original_prompt": "How does JWT token validation work?",
  "confidence": 0.9,
  "reasoning": "User asks for explanation, no action implied.",
  "resolved_references": {}
}

### Example 5: Greeting
Context: Any
Input: "Cześć, co tam?"
Output:
{
  "intent": "chat",
  "refined_prompt": "Respond to casual greeting",
  "original_prompt": "Cześć, co tam?",
  "confidence": 1.0,
  "reasoning": "Casual greeting, not a coding task.",
  "resolved_references": {},
  "show_plan_only": false
}

### Example 6: Execute immediately (NO show_plan_only)
Context: Any
Input: "Implement user authentication with JWT"
Output:
{
  "intent": "new_task",
  "refined_prompt": "Implement user authentication system using JWT tokens",
  "original_prompt": "Implement user authentication with JWT",
  "confidence": 0.95,
  "reasoning": "User wants to IMPLEMENT (execute action), not just plan. Execute immediately.",
  "resolved_references": {},
  "show_plan_only": false
}

### Example 7: Polish "plan" keyword
Context: Any
Input: "Utwórz plan refaktoryzacji bazy danych"
Output:
{
  "intent": "new_task",
  "refined_prompt": "Create and present an execution plan for database refactoring",
  "original_prompt": "Utwórz plan refaktoryzacji bazy danych",
  "confidence": 0.95,
  "reasoning": "User asks to CREATE A PLAN (meta-planning). Keywords: 'utwórz plan'. Set show_plan_only=true.",
  "resolved_references": {},
  "show_plan_only": true
}

## CRITICAL
- Always return valid JSON matching IntentAnalysis schema
- confidence should reflect how certain you are (0.7-1.0 typically)
- refined_prompt must be in ENGLISH (technical terms)
- reasoning should explain your decision
"""
    
    async def analyze(
        self,
        user_input: str,
        current_plan: ExecutionPlan | None = None,
        chat_history: list[Any] | None = None
    ) -> IntentAnalysis:
        """
        Analyze user input and return intent classification with refined prompt.
        
        Args:
            user_input: Raw user message
            current_plan: Currently executing plan (if any)
            chat_history: Recent conversation history
            
        Returns:
            IntentAnalysis with classification and refined prompt
        """
        # Build context string
        context_parts = []
        
        if current_plan:
            context_parts.append(f"Current Plan Goal: {current_plan.refined_goal}")
            
            # Recent completed steps
            done_steps = [s for s in current_plan.steps if s.status == StepStatus.DONE]
            if done_steps:
                last_step = done_steps[-1]
                context_parts.append(f"Last Completed Step: {last_step.title}")
                if last_step.result:
                    # Truncate result for context
                    result_preview = last_step.result[:200] + "..." if len(last_step.result) > 200 else last_step.result
                    context_parts.append(f"Result: {result_preview}")
            
            # Current/pending steps
            pending = [s for s in current_plan.steps if s.status == StepStatus.PENDING]
            if pending:
                context_parts.append(f"Pending Steps: {', '.join([s.title for s in pending[:3]])}")
        else:
            context_parts.append("No active plan")
        
        context_str = "\n".join(context_parts)
        
        # Build prompt for intent router
        analysis_prompt = f"""Context:
{context_str}

User Input: "{user_input}"

Analyze the intent and refine the prompt with resolved references."""
        
        try:
            # Run with structured output
            result = await self.agent.run(analysis_prompt)
            
            # Extract text from result (handle different pydantic-ai versions)
            if hasattr(result, 'data'):
                text = result.data
            elif hasattr(result, 'content'):
                text = result.content
            elif hasattr(result, 'output'):
                text = result.output
            else:
                logger.warning(f"Intent Router result attributes: {dir(result)}")
                text = str(result)
            
            # Parse JSON response
            import json
            
            # Clean up markdown code blocks if present
            if isinstance(text, str):
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].strip()
            
            # Parse and validate
            data = json.loads(text)
            analysis = IntentAnalysis(**data)
            analysis.relevant_context = context_str
            
            logger.info(f"Intent classified: {analysis.intent.value} (confidence: {analysis.confidence})")
            return analysis
            
        except Exception as e:
            logger.error(f"Intent analysis failed: {e}")
            # Fallback to safe defaults
            return IntentAnalysis(
                intent=IntentType.CLARIFICATION,
                refined_prompt=user_input,
                original_prompt=user_input,
                confidence=0.5,
                reasoning=f"Fallback due to error: {str(e)}",
                relevant_context=context_str
            )
