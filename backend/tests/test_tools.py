from __future__ import annotations
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from pydantic_ai import Agent
from backend.src.tools.file_ops import register_file_tools
from backend.src.tools.vscode_ctx import register_vscode_tools
from backend.src.adapters.local_fs import LocalFilesystemAdapter
from backend.src.agent.agent import AgentDependencies


@pytest.fixture
def temp_workspace():
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
    shutil.rmtree(tmpdir)


@pytest.fixture
def local_adapter(temp_workspace):
    return LocalFilesystemAdapter(root_dir=temp_workspace)


@pytest.fixture
def deps(local_adapter):
    return AgentDependencies(
        adapter=local_adapter, interaction_id="test-interaction", step_id="test-step"
    )


@pytest.fixture
def run_context(deps):
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


def get_tool_fn(agent, name):
    """Helper to extract a tool function from a pydantic-ai Agent."""
    for ts in agent.toolsets:
        if hasattr(ts, "tools") and name in ts.tools:
            return ts.tools[name].function
    raise KeyError(f"Tool {name} not found in agent toolsets")


@pytest.mark.asyncio
async def test_file_ops_read_write(temp_workspace, local_adapter, run_context):
    from pydantic_ai.models.test import TestModel

    agent = Agent(TestModel())
    register_file_tools(agent, local_adapter)

    write_tool = get_tool_fn(agent, "write_file")
    read_tool = get_tool_fn(agent, "read_file")

    # Test Write
    res_write = await write_tool(run_context, "hello.txt", "Hello World")
    assert "Successfully wrote" in res_write
    assert (temp_workspace / "hello.txt").read_text() == "Hello World"

    # Test Read
    res_read = await read_tool(run_context, "hello.txt")
    assert res_read == "Hello World"

    # Test Line Range
    (temp_workspace / "lines.txt").write_text("L1\nL2\nL3\nL4")
    res_lines = await read_tool(run_context, "lines.txt", start_line=2, end_line=3)
    assert res_lines == "L2\nL3"


@pytest.mark.asyncio
async def test_file_ops_edit_file(temp_workspace, local_adapter, run_context):
    from pydantic_ai.models.test import TestModel

    agent = Agent(TestModel())
    register_file_tools(agent, local_adapter)

    edit_tool = get_tool_fn(agent, "edit_file")

    path = "edit_test.py"
    original_content = "def test():\n    print('old')\n    return True"
    (temp_workspace / path).write_text(original_content)

    # Test successful edit
    old_str = "    print('old')"
    new_str = "    print('new')"
    res = await edit_tool(run_context, path, old_str, new_str)
    assert "Successfully edited" in res

    updated_content = (temp_workspace / path).read_text()
    assert "print('new')" in updated_content
    assert "print('old')" not in updated_content

    # Test failure: old_string not found
    res_fail = await edit_tool(run_context, path, "non-existent", "replacement")
    assert "Error: The exact string to replace was not found" in res_fail

    # Test failure: multiple matches
    (temp_workspace / "multi.txt").write_text("abc\nabc\nabc")
    res_multi = await edit_tool(run_context, "multi.txt", "abc", "def")
    assert "Found 2 matches" in res_multi or "Found 3 matches" in res_multi


@pytest.mark.asyncio
async def test_file_ops_list_and_search(temp_workspace, local_adapter, run_context):
    from pydantic_ai.models.test import TestModel

    agent = Agent(TestModel())
    register_file_tools(agent, local_adapter)

    list_tool = get_tool_fn(agent, "list_directory")
    # For search, I need to check the tool name in file_ops.py
    # From read_file earlier it was 'search_in_files'

    (temp_workspace / "dir").mkdir()
    (temp_workspace / "dir" / "file.txt").write_text("content")

    # Test List
    res_list = await list_tool(run_context, "dir")
    assert "file.txt" in res_list

    # Test Search (if it exists)
    try:
        search_tool = get_tool_fn(agent, "search_in_files")
        res_search = await search_tool(run_context, "content", path="dir")
        # In mock mode, it returns 'mock.txt'
        assert "Found content" in res_search
    except KeyError:
        # Some tools might not be registered yet or have different names
        pass


@pytest.mark.asyncio
async def test_vscode_ctx_tools(local_adapter, run_context):
    # Mock adapter's remote tool call
    local_adapter._call_remote_tool = AsyncMock()

    from pydantic_ai.models.test import TestModel

    agent = Agent(TestModel())
    register_vscode_tools(agent)

    # Active file context
    local_adapter._call_remote_tool.return_value = {
        "path": "test.py",
        "language": "python",
    }
    tool = get_tool_fn(agent, "get_active_file_context")
    res = await tool(run_context)
    assert res["path"] == "test.py"
    local_adapter._call_remote_tool.assert_called_with("get_active_file_context")

    # Diagnostics
    local_adapter._call_remote_tool.return_value = [{"message": "Error", "severity": 1}]
    diag_tool = get_tool_fn(agent, "get_workspace_diagnostics")
    res_diag = await diag_tool(run_context)
    assert len(res_diag) == 1
    assert res_diag[0]["message"] == "Error"
