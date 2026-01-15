from __future__ import annotations
import logging
from typing import Any
from pydantic_ai import Agent, RunContext
from backend.src.config import get_settings
from backend.src.adapters.base import FilesystemAdapter
from backend.src.adapters.local import LocalFileSystemAdapter

logger = logging.getLogger(__name__)
settings = get_settings()

class CoderAgent:
    def __init__(self, adapter: FilesystemAdapter | None = None):
        self.adapter = adapter or LocalFileSystemAdapter()
        
        # Initialize the Pydantic AI Agent
        self.agent = Agent(
            model=f"google-gla:{settings.GEMINI_MODEL_FAST}",
            deps_type=FilesystemAdapter,
            system_prompt=(
                "You are an expert AI software engineer. "
                "You have access to tools to read and write files in the workspace. "
                "Be concise and professional. Always use tools when required."
            ),
        )
        
        # Register Tools
        self._setup_tools()

    def _setup_tools(self):
        @self.agent.tool
        async def read_file(ctx: RunContext[FilesystemAdapter], path: str, **kwargs) -> str:
            """Reads the content of a file.
            
            Args:
                path: Relative or absolute path to the file.
            """
            logger.info(f"Tool call: read_file({path})")
            return await ctx.deps.read_file(path)

        @self.agent.tool
        async def write_file(ctx: RunContext[FilesystemAdapter], path: str, content: str, **kwargs) -> str:
            """Writes or overwrites a file with the given content.
            
            Args:
                path: Relative or absolute path to the file.
                content: The content to write.
            """
            logger.info(f"Tool call: write_file({path})")
            success = await ctx.deps.write_file(path, content)
            return "File written successfully." if success else "Failed to write file."

        @self.agent.tool
        async def list_directory(ctx: RunContext[FilesystemAdapter], path: str = ".", **kwargs) -> list[str]:
            """Lists files in a directory.
            
            Args:
                path: Path to the directory. Defaults to root.
            """
            logger.info(f"Tool call: list_directory({path})")
            return await ctx.deps.list_dir(path)

    async def run(self, prompt: str) -> str:
        """Run the agent on a specific prompt."""
        try:
            result = await self.agent.run(prompt, deps=self.adapter)
            return result.data
        except Exception as e:
            logger.error(f"Agent error: {e}")
            return f"Error: {e}"

    async def chat_stream(self, prompt: str):
        """Run the agent and stream results (for WebSocket)."""
        async with self.agent.run_stream(prompt, deps=self.adapter) as result:
            async for message in result.stream_text():
                yield message
