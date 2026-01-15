from __future__ import annotations
import logging
import os
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from backend.src.config import get_settings
from backend.src.agent.models import IntentAnalysis, TaskComplexity, Agentmode

logger = logging.getLogger(__name__)

class IntentRouter:
    """
    Analyzes user input to determine intent, complexity, and routing.
    Uses a fast model (Gemini Flash) for low latency.
    """

    def __init__(self):
        self.settings = get_settings()
        
        # Ensure API key is set
        api_key = self.settings.GEMINI_API_KEY or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("No API Key found for IntentRouter via settings or env.")
        
        # Configure the model - strictly Flash for speed
        provider = GoogleProvider(api_key=api_key) if api_key else None
        model = GoogleModel(
            self.settings.GEMINI_MODEL_FAST, # e.g. gemini-2.0-flash
            provider=provider
        )

        self.agent = Agent(
            model=model,
            # result_type=IntentAnalysis, # Removed due to compatibility issues
            system_prompt=(
                "You are the 'Cerebral Cortex' of an AI Coding Assistant. "
                "Your job is to LISTEN to the user (who puts input via voice, often unstructured) "
                "and CLARIFY their intent into a structured technical plan.\n"
                "\n"
                "1. **Refine Prompt**: Rewrite the user's messy request into a clear, imperative instruction for an expert developer. "
                "Fix typos, expand context if obvious (e.g., 'fix it' -> 'fix the error in the current file'). "
                "If the input is in a non-English language (e.g. Polish), fix typos but keep the intent clear. You MAY translate to English if it helps technical precision, or keep in original language if it's a conversational query.\n"
                "2. **Assess Complexity**:\n"
                "   - SIMPLE: 'Hello', 'What is this file?', 'List files'.\n"
                "   - MEDIUM: 'Add a print statement', 'Rename this variable', 'Explain this function'.\n"
                "   - COMPLEX: 'Refactor this class', 'Create a new feature', 'Debug why this fails', 'Plan architecture'.\n"
                "3. **Route Mode**:\n"
                "   - CHAT: Conversational, no changes needed.\n"
                "   - FAST_TOOL: Simple actions (read/write single file).\n"
                "   - DEEP_THINKING: Requires planning, multi-step actions, or deep analysis.\n"
            )
        )

    async def analyze(self, user_input: str, context_summary: str = "") -> IntentAnalysis:
        """
        Analyzes the user input and returns a structured intent object.
        """
        logger.info(f"Router analyzing: {user_input[:50]}...")
        
        prompt = f"User Input: {user_input}\nContext: {context_summary}"
        
        try:
            # Pass result_type here instead
            result = await self.agent.run(prompt, result_type=IntentAnalysis)
            analysis = result.data
            logger.info(f"Router Analysis: Mode={analysis.suggested_mode}, Complexity={analysis.complexity}")
            logger.info(f"Refined Prompt: {analysis.refined_prompt}")
            return analysis
        except Exception as e:
            logger.error(f"Router failed: {e}")
            # Fallback to a safe default
            return IntentAnalysis(
                original_prompt=user_input,
                refined_prompt=user_input,
                complexity=TaskComplexity.SIMPLE,
                suggested_mode=Agentmode.CHAT,
                reasoning="Router failed, falling back to simple chat."
            )
