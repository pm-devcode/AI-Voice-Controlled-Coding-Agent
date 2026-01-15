from __future__ import annotations
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from backend.src.agent.structured_protocol import (
    StructuredAgentResponse, ToolCall, AgentResponseType
)
from backend.src.agent.tool_executor import ToolExecutor
from backend.src.agent.structured_agent import StructuredAgent

@pytest.fixture
def mock_adapter():
    adapter = MagicMock()
    adapter.read_file = AsyncMock(return_value="test content")
    adapter.write_file = AsyncMock(return_value=True)
    adapter.list_dir = AsyncMock(return_value=["file1.py", "file2.py"])
    adapter.log_debug = AsyncMock()
    adapter.call_vscode_tool = AsyncMock(return_value="vsc result")
    return adapter

@pytest.mark.asyncio
async def test_tool_executor_read_file(mock_adapter):
    executor = ToolExecutor(mock_adapter)
    tool_call = ToolCall(name="read_file", args={"path": "test.txt"})
    
    results = await executor.execute_tools([tool_call])
    
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].result == "test content"
    mock_adapter.read_file.assert_called_with("test.txt")

@pytest.mark.asyncio
async def test_tool_executor_edit_file(mock_adapter):
    mock_adapter.read_file.return_value = "Hello World"
    executor = ToolExecutor(mock_adapter)
    tool_call = ToolCall(name="edit_file", args={
        "path": "test.txt",
        "old_string": "World",
        "new_string": "VCCA"
    })
    
    results = await executor.execute_tools([tool_call])
    
    assert results[0].success is True
    mock_adapter.write_file.assert_called_once()
    write_args = mock_adapter.write_file.call_args[0]
    assert write_args[1] == "Hello VCCA"

@pytest.mark.asyncio
async def test_tool_executor_unknown_tool(mock_adapter):
    executor = ToolExecutor(mock_adapter)
    tool_call = ToolCall(name="non_existent_tool", args={})
    
    results = await executor.execute_tools([tool_call])
    
    assert results[0].success is False
    assert "Unknown tool" in results[0].result

def test_structured_agent_parse_valid_json():
    agent = StructuredAgent(MagicMock())
    raw_json = json.dumps({
        "response_type": "tool_request",
        "reasoning": "thought",
        "tools": [{"name": "read_file", "args": {"path": "a.txt"}}],
        "response": None
    })
    
    parsed = agent._parse_response(raw_json)
    assert parsed.response_type == AgentResponseType.TOOL_REQUEST
    assert len(parsed.tools) == 1
    assert parsed.tools[0].name == "read_file"

def test_structured_agent_parse_markdown_json():
    agent = StructuredAgent(MagicMock())
    raw_text = "Here is my response:\n```json\n{\"response_type\": \"final_response\", \"response\": \"Hello\"}\n```"
    
    parsed = agent._parse_response(raw_text)
    assert parsed.response_type == AgentResponseType.FINAL_RESPONSE
    assert parsed.response == "Hello"

@pytest.mark.asyncio
async def test_structured_agent_loop(mock_adapter):
    # Setup agent with mock adapter
    # Note: We need to mock settings to avoid API key checks if possible, 
    # but StructuredAgent uses get_settings() inside.
    agent = StructuredAgent(mock_adapter)
    
    # 1st response: ask for tool
    # 2nd response: final answer
    responses = [
        json.dumps({
            "response_type": "tool_request",
            "tools": [{"name": "read_file", "args": {"path": "test.txt"}}]
        }),
        json.dumps({
            "response_type": "final_response",
            "response": "Done!"
        })
    ]
    
    with patch.object(agent, "_call_llm", AsyncMock(side_effect=responses)):
        chunks = []
        async for chunk in agent.run("Analyze this"):
            chunks.append(chunk)
            
        # Verify tool was requested and "Done!" final message arrived
        assert any("Using tools: read_file" in c for c in chunks)
        assert chunks[-1] == "Done!"
        assert mock_adapter.read_file.called
