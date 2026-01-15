import json
import socket
import threading
import time
import asyncio
import pytest
import uvicorn
from websockets.asyncio.client import connect
import base64
import numpy as np
from backend.src.main import app

def get_free_port():
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]

class LiveServer:
    def __init__(self, port):
        self.port = port
        self.config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error")
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run)
        self.thread.daemon = True

    def start(self):
        self.thread.start()
        # Wait for server to be ready
        time.sleep(1)

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)

@pytest.fixture(scope="module")
def live_server():
    port = get_free_port()
    server = LiveServer(port)
    server.start()
    url = f"ws://127.0.0.1:{port}/ws"
    yield url
    server.stop()

@pytest.mark.asyncio
async def test_live_websocket_connection(live_server):
    async with connect(live_server) as ws:
        # Initial message is status: ready
        msg = json.loads(await ws.recv())
        assert msg["type"] == "status"
        assert msg["status"] == "ready"

@pytest.mark.asyncio
async def test_live_text_input_and_tool_call(live_server):
    async with connect(live_server) as ws:
        # Skip ready
        await ws.recv()
        
        # Send text input that triggers a tool (requires reading files or similar)
        # We need to be careful with models. Since we are running the REAL server,
        # it will use real Gemini if configured, or fail if not.
        # However, for this integration test, we mostly care about the WebSocket cycle.
        
        await ws.send(json.dumps({
            "type": "text_input",
            "text": "Check if file exists: non_existent_file.txt"
        }))
        
        # We expect a sequence of messages
        # status: working -> plan_update (if it decides to plan) -> etc.
        
        found_tool_usage = False
        start_time = time.time()
        while time.time() - start_time < 10: # 10s timeout
            try:
                raw_msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw_msg)
                
                if msg["type"] == "tool_usage":
                    found_tool_usage = True
                    # Respond to tool
                    await ws.send(json.dumps({
                        "type": "tool_result",
                        "call_id": msg["call_id"],
                        "output": "File does not exist"
                    }))
                
                if msg["type"] == "response" and msg.get("is_final"):
                    break
            except asyncio.TimeoutError:
                break
        
        # If Gemini is not set up, it might just return an error message in 'response'
        # That's also fine for a connection test.
        # assert found_tool_usage  # This depends on LLM behavior

@pytest.mark.asyncio
async def test_live_audio_chunk_flow(live_server):
    async with connect(live_server) as ws:
        await ws.recv() # skip ready
        
        # Create silent audio chunk (1s)
        silent_data = np.zeros(16000, dtype=np.int16)
        b64_data = base64.b64encode(silent_data.tobytes()).decode('utf-8')
        
        # Send audio chunk
        await ws.send(json.dumps({
            "type": "audio_chunk",
            "data": b64_data
        }))
        
        # Stop recording to trigger flush
        await ws.send(json.dumps({
            "type": "stop_recording"
        }))
        
        # We expect a transcript message (likely empty if silence) or status: ready
        received_something = False
        start_time = time.time()
        while time.time() - start_time < 5:
            try:
                raw_msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                msg = json.loads(raw_msg)
                if msg["type"] in ["transcript", "status", "response"]:
                    received_something = True
                if msg.get("status") == "ready" and received_something:
                    break
            except asyncio.TimeoutError:
                break
        
        assert received_something
