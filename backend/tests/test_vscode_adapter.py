import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from backend.src.adapters.vscode import VSCodeAdapter
from backend.src.api.messages import ToolUsageMessage


@pytest.mark.asyncio
async def test_vscode_adapter_read_file():
    # Setup
    send_mock = AsyncMock()
    adapter = VSCodeAdapter(send_mock)

    # Task to simulate calling read_file
    read_task = asyncio.create_task(adapter.read_file("test.txt"))

    # Wait a bit for the message to reach the send_mock
    await asyncio.sleep(0.01)

    # Verify tool_usage message was sent
    send_mock.assert_called_once()
    msg = send_mock.call_args[0][0]
    assert isinstance(msg, ToolUsageMessage)
    assert msg.tool_name == "read_file"
    assert msg.input_data == {"path": "test.txt"}
    call_id = msg.call_id

    # Simulate receiving a result
    adapter.handle_tool_result(call_id, "file content")

    # Verifying the result
    result = await read_task
    assert result == "file content"


@pytest.mark.asyncio
async def test_vscode_adapter_timeout():
    send_mock = AsyncMock()
    adapter = VSCodeAdapter(send_mock)

    # We'll lower the timeout temporarily if possible, or just let it timeout.
    # The adapter has a hardcoded 30.0s.
    # Let's mock asyncio.wait_for to raise timeout quickly for this test
    with MagicMock() as mock_wait_for:
        import asyncio

        original_wait_for = asyncio.wait_for
        asyncio.wait_for = AsyncMock(side_effect=asyncio.TimeoutError())

        try:
            with pytest.raises(Exception) as excinfo:
                await adapter.read_file("fail.txt")
            assert "timed out" in str(excinfo.value)
        finally:
            asyncio.wait_for = original_wait_for


@pytest.mark.asyncio
async def test_vscode_adapter_write_file():
    send_mock = AsyncMock()
    adapter = VSCodeAdapter(send_mock)

    write_task = asyncio.create_task(adapter.write_file("test.txt", "new content"))
    await asyncio.sleep(0.01)

    msg = send_mock.call_args[0][0]
    adapter.handle_tool_result(msg.call_id, "success")

    result = await write_task
    assert result is True
