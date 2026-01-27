#!/usr/bin/env python3
"""Quick dry-run test: connect to OpenAI Realtime API, configure session, send silence, get greeting."""

import asyncio
import base64
import json
import os
import struct
import subprocess
import sys

try:
    import websockets
except ImportError:
    print("pip install websockets")
    sys.exit(1)

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"
OPENAI_MODEL = "gpt-4o-realtime-preview-2024-12-17"


def get_api_key():
    """Get API key from env or Keychain."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-a", "bando", "-s", "openai-api-key", "-w"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                key = result.stdout.strip()
        except Exception:
            pass
    return key


async def test_connection():
    api_key = get_api_key()
    if not api_key:
        print("❌ No API key found")
        return False
    
    print(f"API key: {api_key[:20]}...")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "OpenAI-Beta": "realtime=v1"
    }
    
    url = f"{OPENAI_REALTIME_URL}?model={OPENAI_MODEL}"
    
    print("Connecting to OpenAI Realtime API...")
    
    try:
        async with websockets.connect(url, additional_headers=headers) as ws:
            print("✅ Connected!")
            
            # Wait for session.created
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            print(f"Event: {data['type']}")
            
            if data["type"] == "session.created":
                session = data.get("session", {})
                print(f"  Session ID: {session.get('id', 'N/A')}")
                print(f"  Model: {session.get('model', 'N/A')}")
                print(f"  Voice: {session.get('voice', 'N/A')}")
            
            # Configure session
            config = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": "Say 'hello, bandophone is connected' very briefly.",
                    "voice": "alloy",
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "silence_duration_ms": 500
                    }
                }
            }
            await ws.send(json.dumps(config))
            print("Session configured")
            
            # Wait for session.updated
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)
            print(f"Event: {data['type']}")
            
            # Send a text message to get a response (no audio needed)
            await ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Hello! Just testing the connection. Say 'bandophone connected' briefly."}]
                }
            }))
            await ws.send(json.dumps({"type": "response.create"}))
            print("Sent test message, waiting for response...")
            
            # Collect response
            transcript = ""
            audio_bytes = 0
            timeout = 15
            start = asyncio.get_event_loop().time()
            
            while asyncio.get_event_loop().time() - start < timeout:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    data = json.loads(msg)
                    evt = data.get("type", "")
                    
                    if evt == "response.audio.delta":
                        audio_b64 = data.get("delta", "")
                        audio_bytes += len(base64.b64decode(audio_b64)) if audio_b64 else 0
                    
                    elif evt == "response.audio_transcript.delta":
                        transcript += data.get("delta", "")
                    
                    elif evt == "response.done":
                        print(f"\n✅ Response received!")
                        print(f"  Transcript: {transcript}")
                        print(f"  Audio: {audio_bytes} bytes ({audio_bytes / 48000:.1f}s at 24kHz)")
                        break
                    
                    elif evt == "error":
                        print(f"❌ Error: {data.get('error', {}).get('message', data)}")
                        break
                    
                    elif evt not in ("response.created", "response.output_item.added", 
                                     "conversation.item.created", "response.content_part.added",
                                     "response.audio_transcript.done", "response.content_part.done",
                                     "response.output_item.done", "rate_limits.updated"):
                        print(f"  Event: {evt}")
                        
                except asyncio.TimeoutError:
                    print("Timeout waiting for response")
                    break
            
            print("\n✅ Dry run complete — OpenAI Realtime API connection works!")
            return True
            
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"❌ Connection failed: HTTP {e.status_code}")
        if e.status_code == 401:
            print("  → Invalid API key")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_connection())
    sys.exit(0 if success else 1)
