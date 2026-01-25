#!/usr/bin/env python3
"""
Bandophone: OpenAI Realtime API Integration

Connects call audio capture to OpenAI's Realtime API for AI-powered conversations.

Requirements:
    pip install websockets python-dotenv

Usage:
    export OPENAI_API_KEY=sk-...
    python openai_realtime.py

Architecture:
    Call Audio (capture) → [resample to 24kHz] → OpenAI Realtime → AI Response
                                                                        ↓
                                                          [resample to 48kHz] → Playback

Note: Playback requires the Android app to be working.
"""

import asyncio
import base64
import json
import os
import subprocess
import sys
from typing import Optional

try:
    import websockets
except ImportError:
    print("pip install websockets", file=sys.stderr)
    sys.exit(1)

# Constants
OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"
OPENAI_MODEL = "gpt-4o-realtime-preview"

# Audio formats
CAPTURE_RATE = 48000  # From Pixel 7 Pro
OPENAI_RATE = 24000   # OpenAI Realtime expects 24kHz
PLAYBACK_RATE = 48000 # For injection back into call


class BandophoneBridge:
    """Bridge between phone call audio and OpenAI Realtime API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.capture_process: Optional[subprocess.Popen] = None

    async def connect(self):
        """Connect to OpenAI Realtime API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "realtime=v1"
        }

        url = f"{OPENAI_REALTIME_URL}?model={OPENAI_MODEL}"
        
        print(f"Connecting to OpenAI Realtime API...", file=sys.stderr)
        self.ws = await websockets.connect(url, extra_headers=headers)
        self.is_connected = True
        print(f"✅ Connected!", file=sys.stderr)

        # Configure the session
        await self.configure_session()

    async def configure_session(self):
        """Configure the Realtime session for voice conversation."""
        config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": """You are Bando, an AI assistant having a phone conversation.
                Keep responses brief and conversational - this is a phone call, not a text chat.
                Speak naturally, as if talking to a friend.
                If you hear background noise or unclear audio, politely ask for clarification.""",
                "voice": "alloy",  # Options: alloy, echo, shimmer
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 500
                }
            }
        }

        await self.ws.send(json.dumps(config))
        print("Session configured", file=sys.stderr)

    async def send_audio(self, audio_data: bytes):
        """Send audio data to OpenAI (must be 24kHz PCM16)."""
        if not self.is_connected:
            return

        # Base64 encode the audio
        audio_b64 = base64.b64encode(audio_data).decode('utf-8')

        message = {
            "type": "input_audio_buffer.append",
            "audio": audio_b64
        }

        await self.ws.send(json.dumps(message))

    async def receive_responses(self):
        """Handle responses from OpenAI."""
        try:
            async for message in self.ws:
                data = json.loads(message)
                event_type = data.get("type", "")

                if event_type == "response.audio.delta":
                    # Received audio response
                    audio_b64 = data.get("delta", "")
                    if audio_b64:
                        audio_data = base64.b64decode(audio_b64)
                        # TODO: Send to playback service
                        print(f"Received {len(audio_data)} bytes of audio response", file=sys.stderr)

                elif event_type == "response.audio_transcript.delta":
                    # AI's speech transcribed
                    text = data.get("delta", "")
                    if text:
                        print(f"AI: {text}", end="", file=sys.stderr)

                elif event_type == "conversation.item.input_audio_transcription.completed":
                    # User's speech transcribed
                    text = data.get("transcript", "")
                    if text:
                        print(f"\nUser: {text}", file=sys.stderr)

                elif event_type == "error":
                    print(f"Error: {data}", file=sys.stderr)

        except websockets.exceptions.ConnectionClosed:
            print("Connection closed", file=sys.stderr)
            self.is_connected = False

    async def capture_and_stream(self):
        """Capture audio from phone call and stream to OpenAI."""
        
        # Start capture process (outputs raw PCM to stdout)
        cmd = [
            "adb", "shell",
            f"su -c 'export LD_LIBRARY_PATH=/data/local/tmp && "
            f"/data/local/tmp/tinycap /dev/stdout -D 0 -d 20 -c 1 -r {CAPTURE_RATE} -b 16'"
        ]

        print("Starting audio capture...", file=sys.stderr)
        self.capture_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )

        # Skip WAV header (44 bytes)
        self.capture_process.stdout.read(44)

        # Read and resample audio in chunks
        chunk_size = CAPTURE_RATE * 2 // 10  # 100ms of audio
        
        while self.is_connected:
            # Read chunk from capture
            chunk = self.capture_process.stdout.read(chunk_size)
            if not chunk:
                break

            # Resample from 48kHz to 24kHz (simple decimation - not great quality)
            # TODO: Use proper resampling (scipy, librosa, etc.)
            resampled = self._simple_downsample(chunk, CAPTURE_RATE, OPENAI_RATE)

            # Send to OpenAI
            await self.send_audio(resampled)

            # Small delay to prevent overwhelming the API
            await asyncio.sleep(0.05)

    def _simple_downsample(self, data: bytes, src_rate: int, dst_rate: int) -> bytes:
        """Simple downsampling by taking every Nth sample. Not high quality."""
        import struct
        
        ratio = src_rate // dst_rate
        samples = struct.unpack(f'<{len(data)//2}h', data)
        downsampled = samples[::ratio]
        return struct.pack(f'<{len(downsampled)}h', *downsampled)

    async def run(self):
        """Main loop."""
        await self.connect()

        # Run capture and receive in parallel
        await asyncio.gather(
            self.capture_and_stream(),
            self.receive_responses()
        )

    async def close(self):
        """Clean up."""
        self.is_connected = False
        if self.capture_process:
            self.capture_process.terminate()
        if self.ws:
            await self.ws.close()


async def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Set OPENAI_API_KEY environment variable", file=sys.stderr)
        sys.exit(1)

    bridge = BandophoneBridge(api_key)

    try:
        await bridge.run()
    except KeyboardInterrupt:
        print("\nStopping...", file=sys.stderr)
    finally:
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(main())
