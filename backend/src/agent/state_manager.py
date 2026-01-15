import json
import logging
import os
from pathlib import Path
from typing import Optional

from backend.src.agent.models import SessionState

logger = logging.getLogger(__name__)

class StateManager:
    """
    Manages persistence of the agent's session state (plan, history, etc.)
    to a JSON file, allowing recovery after restarts.
    """
    def __init__(self, workspace_root: str = "."):
        self.workspace_root = Path(workspace_root)
        self.cache_dir = self.workspace_root / ".vcca" / ".cache"
        self.state_file = self.cache_dir / "session_state.json"
        
        self._ensure_cache_dir()

    def _ensure_cache_dir(self):
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create cache directory: {e}")

    def save_state(self, state: SessionState):
        """Saves the current SessionState to disk."""
        try:
            # Pydantic v2 dump
            data = state.model_dump(mode='json')
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Session state saved to {self.state_file}")
        except Exception as e:
            logger.error(f"Failed to save session state: {e}")

    def load_state(self) -> Optional[SessionState]:
        """Loads SessionState from disk if it exists."""
        if not self.state_file.exists():
            return None
        
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Basic validation: check if plan exists and is not empty or done
            state = SessionState.model_validate(data)
            
            # Optional: Check if the plan is actually resumable (not fully done)
            if state.plan:
                pending_steps = [s for s in state.plan.steps if s.status in ['pending', 'in_progress', 'waiting_for_user']]
                if not pending_steps and not state.waiting_for_input:
                    # Plan is effectively done, maybe don't load it or load as history?
                    # For now, load it as is, Orchestrator will decide what to do.
                    pass
            
            return state
        except Exception as e:
            logger.error(f"Failed to load session state: {e}")
            return None

    def clear_state(self):
        """Removes the stored session state."""
        try:
            if self.state_file.exists():
                os.remove(self.state_file)
                logger.info("Session state cleared.")
        except Exception as e:
            logger.error(f"Failed to clear session state: {e}")
