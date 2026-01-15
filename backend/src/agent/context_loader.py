"""Project context loader for enriching LLM prompts with project metadata."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Files to look for and their importance
PROJECT_FILES = [
    # Python
    ("pyproject.toml", "Python project config"),
    ("setup.py", "Python setup"),
    ("requirements.txt", "Python dependencies"),
    # JavaScript/TypeScript
    ("package.json", "Node.js project config"),
    ("tsconfig.json", "TypeScript config"),
    # Rust
    ("Cargo.toml", "Rust project config"),
    # Go
    ("go.mod", "Go module config"),
    # General
    ("README.md", "Project documentation"),
    (".editorconfig", "Editor config"),
]

# Max chars to include per file
MAX_FILE_SIZE = 2000


class ProjectContextLoader:
    """
    Loads and caches project context for LLM prompts.
    Uses direct filesystem access (not WebSocket) for speed.
    """
    
    def __init__(self, workspace_path: str | Path | None = None):
        self.workspace_path = Path(workspace_path) if workspace_path else Path.cwd()
        self._cache: dict[str, Any] = {}
        self._project_type: str | None = None
        self._loaded = False
    
    async def load_context(self) -> dict[str, Any]:
        """
        Loads project context from config files using direct filesystem reads.
        Returns a dict with project info.
        """
        if self._loaded:
            return self._cache
        
        context = {
            "project_type": "unknown",
            "files_found": [],
            "summary": "",
            "details": {}
        }
        
        for filename, description in PROJECT_FILES:
            try:
                file_path = self.workspace_path / filename
                if not file_path.exists():
                    continue
                
                content = file_path.read_text(encoding="utf-8")
                if content:
                    # Truncate if too large
                    if len(content) > MAX_FILE_SIZE:
                        content = content[:MAX_FILE_SIZE] + "\n... (truncated)"
                    
                    context["files_found"].append(filename)
                    context["details"][filename] = {
                        "description": description,
                        "content": content
                    }
                    
                    # Detect project type
                    if filename == "package.json":
                        context["project_type"] = "nodejs"
                        self._parse_package_json(content, context)
                    elif filename == "pyproject.toml":
                        context["project_type"] = "python"
                        self._parse_pyproject(content, context)
                    elif filename == "Cargo.toml":
                        context["project_type"] = "rust"
                    elif filename == "go.mod":
                        context["project_type"] = "go"
            except Exception as e:
                logger.debug(f"Could not read {filename}: {e}")
                continue
        
        # Build summary
        context["summary"] = self._build_summary(context)
        
        self._cache = context
        self._loaded = True
        self._project_type = context["project_type"]
        
        return context
    
    def _parse_package_json(self, content: str, context: dict) -> None:
        """Extract key info from package.json."""
        try:
            data = json.loads(content)
            context["name"] = data.get("name", "unknown")
            context["version"] = data.get("version", "0.0.0")
            context["dependencies"] = list(data.get("dependencies", {}).keys())[:20]
            context["dev_dependencies"] = list(data.get("devDependencies", {}).keys())[:10]
            context["scripts"] = list(data.get("scripts", {}).keys())
        except json.JSONDecodeError:
            pass
    
    def _parse_pyproject(self, content: str, context: dict) -> None:
        """Extract key info from pyproject.toml."""
        # Simple TOML parsing for key fields
        lines = content.split("\n")
        for line in lines:
            if line.startswith("name = "):
                context["name"] = line.split("=")[1].strip().strip('"\'')
            elif line.startswith("version = "):
                context["version"] = line.split("=")[1].strip().strip('"\'')
    
    def _build_summary(self, context: dict) -> str:
        """Build a concise summary string for the LLM."""
        parts = [f"Project Type: {context['project_type']}"]
        
        if "name" in context:
            parts.append(f"Name: {context['name']}")
        if "version" in context:
            parts.append(f"Version: {context['version']}")
        if context.get("dependencies"):
            deps = ", ".join(context["dependencies"][:10])
            parts.append(f"Key Dependencies: {deps}")
        if context.get("scripts"):
            scripts = ", ".join(context["scripts"][:5])
            parts.append(f"Available Scripts: {scripts}")
        
        return " | ".join(parts)
    
    def get_prompt_context(self) -> str:
        """
        Returns a formatted string suitable for including in the system prompt.
        Call load_context() first.
        """
        if not self._loaded:
            return ""
        
        lines = ["\n## PROJECT CONTEXT"]
        lines.append(f"Type: {self._cache.get('project_type', 'unknown')}")
        
        if self._cache.get("summary"):
            lines.append(f"Summary: {self._cache['summary']}")
        
        # Include key config file contents
        for filename in ["package.json", "pyproject.toml"]:
            if filename in self._cache.get("details", {}):
                content = self._cache["details"][filename]["content"]
                # Only include first 1000 chars
                if len(content) > 1000:
                    content = content[:1000] + "\n..."
                lines.append(f"\n### {filename}:\n```\n{content}\n```")
        
        return "\n".join(lines)
    
    def invalidate_cache(self) -> None:
        """Clear the cache to force reload on next access."""
        self._cache = {}
        self._loaded = False
        self._project_type = None
