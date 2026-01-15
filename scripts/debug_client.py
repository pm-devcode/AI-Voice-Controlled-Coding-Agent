import asyncio
import json
import websockets
import base64
import sys

async def debug_client():
    uri = "ws://127.0.0.1:8775/ws"
    print(f"Connecting to {uri}...")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected!")
            
            # 1. Listen for initial status
            msg = await websocket.recv()
            print(f"Server: {msg}")

            # 2. Send text command
            command = "list the current directory"
            print(f"\nSending text command: '{command}'")
            payload = {
                "type": "text_input",
                "id": "test_1",
                "text": command
            }
            await websocket.send(json.dumps(payload))

            # 3. Listen for responses
            while True:
                try:
                    raw_msg = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    msg = json.loads(raw_msg)
                    
                    if msg["type"] == "status":
                        print(f"[STATUS] {msg.get('status')}: {msg.get('message')}")
                    elif msg["type"] == "response":
                        print(f"[AGENT] {msg.get('text')}", end="", flush=True)
                        if msg.get("is_final"):
                            print("\n--- End of response ---")
                            break
                    elif msg["type"] == "error":
                        print(f"[ERROR] {msg.get('error')}")
                        break
                except asyncio.TimeoutError:
                    print("\nTimed out waiting for response.")
                    break

            # 4. Try a file creation command
            command = "create a file named 'test_vcca.txt' with content 'Hello from VCCA Agent!'"
            print(f"\nSending text command: '{command}'")
            payload = {
                "type": "text_input",
                "id": "test_2",
                "text": command
            }
            await websocket.send(json.dumps(payload))
            
            while True:
                try:
                    raw_msg = await asyncio.wait_for(websocket.recv(), timeout=20.0)
                    msg = json.loads(raw_msg)
                    
                    if msg["type"] == "status":
                        print(f"[STATUS] {msg.get('status')}: {msg.get('message')}")
                    elif msg["type"] == "response":
                        print(f"[AGENT] {msg.get('text')}", end="", flush=True)
                        if msg.get("is_final"):
                            print("\n--- End of response ---")
                            break
                except asyncio.TimeoutError:
                    print("\nTimed out waiting for response.")
                    break

    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(debug_client())
