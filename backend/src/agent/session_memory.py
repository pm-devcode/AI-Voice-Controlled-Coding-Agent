"""Session memory for tracking successful patterns and learnings."""
from __future__ import annotations
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Memory file location (relative to workspace)
MEMORY_FILE = ".vcca/session_memory.json"
MAX_PATTERNS = 50  # Max patterns to keep per category
MAX_HISTORY = 100  # Max interaction history entries


class EditPattern(BaseModel):
    """A successful edit pattern that worked."""
    file_pattern: str = Field(description="File type or path pattern (e.g., '*.py', 'src/components/*')")
    action: str = Field(description="What was done (e.g., 'add import', 'fix function')")
    context: str = Field(description="Surrounding context that helped")
    success_count: int = Field(default=1)
    last_used: str = Field(default_factory=lambda: datetime.now().isoformat())


class InteractionSummary(BaseModel):
    """Summary of a past interaction."""
    timestamp: str
    user_request: str
    files_modified: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    success: bool = True
    notes: str = ""


class SessionMemory(BaseModel):
    """Persistent memory for a project session."""
    project_path: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    
    # Successful edit patterns
    edit_patterns: list[EditPattern] = Field(default_factory=list)
    
    # Common file locations learned
    file_locations: dict[str, str] = Field(default_factory=dict)  # concept -> path
    
    # Past interactions summary
    interaction_history: list[InteractionSummary] = Field(default_factory=list)
    
    # User preferences learned
    preferences: dict[str, Any] = Field(default_factory=dict)
    
    # Project-specific notes
    notes: list[str] = Field(default_factory=list)


class SessionMemoryManager:
    """Manages loading, saving, and querying session memory."""
    
    def __init__(self, workspace_path: str | None = None):
        self.workspace_path = Path(workspace_path) if workspace_path else Path(".")
        self.memory_file = self.workspace_path / MEMORY_FILE
        self._memory: SessionMemory | None = None
    
    def load(self) -> SessionMemory:
        """Load memory from disk or create new."""
        if self._memory:
            return self._memory
        
        try:
            if self.memory_file.exists():
                data = json.loads(self.memory_file.read_text(encoding="utf-8"))
                self._memory = SessionMemory(**data)
                logger.info(f"Loaded session memory with {len(self._memory.edit_patterns)} patterns")
            else:
                self._memory = SessionMemory(project_path=str(self.workspace_path))
                logger.info("Created new session memory")
        except Exception as e:
            logger.warning(f"Could not load session memory: {e}")
            self._memory = SessionMemory(project_path=str(self.workspace_path))
        
        return self._memory
    
    def save(self) -> bool:
        """Save memory to disk."""
        if not self._memory:
            return False
        
        try:
            self._memory.updated_at = datetime.now().isoformat()
            
            # Ensure directory exists
            self.memory_file.parent.mkdir(parents=True, exist_ok=True)
            
            self.memory_file.write_text(
                self._memory.model_dump_json(indent=2),
                encoding="utf-8"
            )
            logger.debug("Session memory saved")
            return True
        except Exception as e:
            logger.error(f"Could not save session memory: {e}")
            return False
    
    def record_successful_edit(
        self, 
        file_path: str, 
        action: str, 
        context: str = ""
    ) -> None:
        """Record a successful edit pattern."""
        memory = self.load()
        
        # Determine file pattern
        file_ext = Path(file_path).suffix
        file_pattern = f"*{file_ext}" if file_ext else file_path
        
        # Check if pattern already exists
        for pattern in memory.edit_patterns:
            if pattern.file_pattern == file_pattern and pattern.action == action:
                pattern.success_count += 1
                pattern.last_used = datetime.now().isoformat()
                self.save()
                return
        
        # Add new pattern
        memory.edit_patterns.append(EditPattern(
            file_pattern=file_pattern,
            action=action,
            context=context[:200]  # Truncate context
        ))
        
        # Trim old patterns if too many
        if len(memory.edit_patterns) > MAX_PATTERNS:
            # Sort by success count and recency
            memory.edit_patterns.sort(
                key=lambda p: (p.success_count, p.last_used),
                reverse=True
            )
            memory.edit_patterns = memory.edit_patterns[:MAX_PATTERNS]
        
        self.save()
    
    def record_file_location(self, concept: str, path: str) -> None:
        """Record a file location for a concept (e.g., 'tests' -> 'tests/')."""
        memory = self.load()
        memory.file_locations[concept.lower()] = path
        self.save()
    
    def record_interaction(
        self,
        user_request: str,
        files_modified: list[str] | None = None,
        tools_used: list[str] | None = None,
        success: bool = True,
        notes: str = ""
    ) -> None:
        """Record a summarized interaction."""
        memory = self.load()
        
        memory.interaction_history.append(InteractionSummary(
            timestamp=datetime.now().isoformat(),
            user_request=user_request[:200],  # Truncate
            files_modified=files_modified or [],
            tools_used=tools_used or [],
            success=success,
            notes=notes[:100]
        ))
        
        # Trim old history
        if len(memory.interaction_history) > MAX_HISTORY:
            memory.interaction_history = memory.interaction_history[-MAX_HISTORY:]
        
        self.save()
    
    def add_note(self, note: str) -> None:
        """Add a project-specific note."""
        memory = self.load()
        memory.notes.append(f"[{datetime.now().strftime('%Y-%m-%d')}] {note}")
        if len(memory.notes) > 50:
            memory.notes = memory.notes[-50:]
        self.save()
    
    def get_relevant_patterns(self, file_path: str) -> list[EditPattern]:
        """Get patterns relevant to a file type."""
        memory = self.load()
        file_ext = Path(file_path).suffix
        
        relevant = []
        for pattern in memory.edit_patterns:
            if file_ext and f"*{file_ext}" == pattern.file_pattern:
                relevant.append(pattern)
            elif file_path in pattern.file_pattern:
                relevant.append(pattern)
        
        return sorted(relevant, key=lambda p: p.success_count, reverse=True)[:5]
    
    def get_file_location(self, concept: str) -> str | None:
        """Get known location for a concept."""
        memory = self.load()
        return memory.file_locations.get(concept.lower())
    
    def get_recent_interactions(self, count: int = 5) -> list[InteractionSummary]:
        """Get recent interaction summaries."""
        memory = self.load()
        return memory.interaction_history[-count:]
    
    def get_prompt_context(self) -> str:
        """Get memory context for inclusion in prompts."""
        memory = self.load()
        
        lines = []
        
        # Recent successful patterns
        if memory.edit_patterns:
            top_patterns = sorted(
                memory.edit_patterns, 
                key=lambda p: p.success_count, 
                reverse=True
            )[:5]
            if top_patterns:
                lines.append("\n## LEARNED PATTERNS (from past successful edits)")
                for p in top_patterns:
                    lines.append(f"- {p.file_pattern}: {p.action} (used {p.success_count}x)")
        
        # Known file locations
        if memory.file_locations:
            lines.append("\n## KNOWN FILE LOCATIONS")
            for concept, path in list(memory.file_locations.items())[:10]:
                lines.append(f"- {concept}: {path}")
        
        # Recent context
        recent = self.get_recent_interactions(3)
        if recent:
            lines.append("\n## RECENT SESSION HISTORY")
            for interaction in recent:
                status = "✓" if interaction.success else "✗"
                lines.append(f"- {status} {interaction.user_request[:50]}...")
                if interaction.files_modified:
                    lines.append(f"  Modified: {', '.join(interaction.files_modified[:3])}")
        
        return "\n".join(lines) if lines else ""
