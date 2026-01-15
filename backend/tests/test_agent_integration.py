import pytest
import asyncio
from pydantic_ai.models.test import TestModel
from pydantic_ai import Agent
from unittest.mock import AsyncMock
from backend.src.agent.agent import VCCAAgent, AgentDependencies
from backend.src.adapters.vscode import VSCodeAdapter


@pytest.mark.asyncio
async def test_agent_tool_usage_integration():
    """
    Test that the agent correctly identifies when to use a tool
    and interacts with the adapter.
    """
    # 1. Setup Adapter with a mock send callback
    send_mock = AsyncMock()
    adapter = VSCodeAdapter(send_mock)

    # 2. Setup Agent with TestModel
    # TestModel allows us to pre-define what the LLM should return/call
    from pydantic_ai.models.test import TestModel

    # We want to simulate the agent wanting to call 'read_file'
    test_model = TestModel()

    agent_wrapper = VCCAAgent(adapter)
    # Inject TestModel into the real agent (fast_agent for simple tasks)
    agent_wrapper.fast_agent.model = test_model

    # Define what the model should do: call read_file
    # In pydantic-ai TestModel, you can set the call_tools
    # However, it's easier to just use agent.run with a specific model override if needed.

    # Let's try to see if it registers tools correctly
    # Checking if read_file is in any of the toolsets
    tool_names = []
    for toolset in agent_wrapper.fast_agent.toolsets:
        for name in toolset.tools.keys():
            tool_names.append(name)
    assert "read_file" in tool_names


@pytest.mark.asyncio
async def test_agent_full_tool_call_flow():
    """
    Integration test: Agent -> Tool Call -> Adapter -> Outgoing Message ->
    (Simulated Response) -> Adapter Result -> Agent Final Answer.
    """
    send_mock = AsyncMock()
    adapter = VSCodeAdapter(send_mock)
    agent_wrapper = VCCAAgent(adapter)

    # Mocking the model to return a tool call
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.test import TestModel

    # Define tool call sequence
    # 1. Model says "I need to read test.txt" + calls tool
    # 2. After tool result, model says "The content is Hello"
    test_model = TestModel(
        custom_output_text="The file content is: Hello World", call_tools=["read_file"]
    )
    agent_wrapper.fast_agent.model = test_model

    # We need to handle the tool execution because the TestModel
    # will actually try to execute the registered function.
    # The registered function in Agent calls adapter.read_file()
    # adapter.read_file() sends a message and WAITS for a future.

    # So we run the agent in a task
    chat_task = asyncio.create_task(agent_wrapper.chat("What is in test.txt?"))

    # Wait for the adapter to send the tool_usage message
    await asyncio.sleep(0.1)

    # Verify message sent to "VS Code"
    send_mock.assert_called()
    msg = send_mock.call_args[0][0]
    assert msg.type == "tool_usage"
    assert msg.tool_name == "read_file"
    call_id = msg.call_id

    # Simulate Extension providing result
    adapter.handle_tool_result(call_id, "Hello World")

    # Final answer
    answer = await chat_task
    assert "Hello World" in answer


@pytest.mark.asyncio
async def test_agent_write_file_flow():
    """
    Test agent calling write_file.
    """
    send_mock = AsyncMock()
    adapter = VSCodeAdapter(send_mock)
    agent_wrapper = VCCAAgent(adapter)

    test_model = TestModel(
        custom_output_text="Successfully updated test.txt", call_tools=["write_file"]
    )
    agent_wrapper.fast_agent.model = test_model

    chat_task = asyncio.create_task(agent_wrapper.chat("Change test.txt to 'Goodbye'"))

    await asyncio.sleep(0.1)

    # Verify the tool usage message was sent via the adapter's send callback
    assert send_mock.called
    msg = send_mock.call_args[0][0]
    assert msg.tool_name == "write_file"

    adapter.handle_tool_result(msg.call_id, "success")

    answer = await chat_task
    assert "updated" in answer


@pytest.mark.asyncio
async def test_agent_error_handling_in_tool():
    """
    Test agent's response when a tool call fails.
    """
    send_mock = AsyncMock()
    adapter = VSCodeAdapter(send_mock)
    agent_wrapper = VCCAAgent(adapter)

    test_model = TestModel(
        custom_output_text="Error: Permission denied", call_tools=["read_file"]
    )
    agent_wrapper.fast_agent.model = test_model

    chat_task = asyncio.create_task(agent_wrapper.chat("Read secret.txt"))

    await asyncio.sleep(0.1)

    msg = send_mock.call_args[0][0]
    # We provide a failing tool result
    adapter.handle_tool_result(msg.call_id, "Error: Permission denied")

    answer = await chat_task
    assert "Permission" in answer or "denied" in answer


import asyncio
