#!/usr/bin/env python3
"""
Bandophone Realtime Bridge

OpenAI Realtime API with ask_bando() function for Clawdbot integration.

Fast voice conversation with on-demand access to full Clawdbot capabilities.
"""

import asyncio
import base64
import json
import os
import struct
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable
import argparse
import logging

try:
    import websockets
except ImportError:
    print("pip install websockets httpx", file=sys.stderr)
    sys.exit(1)

from config import BandophoneConfig, VOICES, DEFAULT_INSTRUCTIONS
from audio_server import AudioServer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger("bandophone")

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"
OPENAI_MODEL = "gpt-4o-realtime-preview-2024-12-17"


# Function definition for ask_bando
ASK_BANDO_FUNCTION = {
    "type": "function",
    "name": "ask_bando",
    "description": "Ask Bando (the full AI assistant) for help with tasks requiring tools or memory. Use this for: looking up information, checking calendar/email/files, running commands, controlling smart home, web search, or anything needing tools or persistent context.",
    "parameters": {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": "What you need Bando to do or look up. Be specific."
            },
            "context": {
                "type": "string",
                "description": "Brief context about the current conversation."
            }
        },
        "required": ["request"]
    }
}


class ClawdbotBridge:
    """Bridge to Clawdbot for ask_bando function calls via CLI."""
    
    def __init__(self, config: BandophoneConfig):
        self.config = config
    
    async def ask_bando(self, request: str, context: str = "", urgent: bool = False) -> str:
        """Send a request to Clawdbot and get response via CLI."""
        
        # Format the message
        message = f"[Voice call request] {request}"
        if context:
            message = f"[Voice call context: {context}]\n\n{request}"
        
        log.info(f"Asking Bando: {request[:100]}...")
        
        try:
            # Use clawdbot agent CLI to send message and get response
            cmd = [
                "clawdbot", "agent",
                "--message", message,
                "--json",
                "--agent", "main"  # Use main agent
            ]
            
            # Override with specific session if configured
            if self.config.clawdbot_session:
                cmd.extend(["--session-id", self.config.clawdbot_session])
            
            # Run async subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30.0
            )
            
            if process.returncode == 0:
                try:
                    result = json.loads(stdout.decode())
                    reply = result.get("reply", result.get("response", ""))
                    if reply:
                        log.info(f"Bando replied: {reply[:100]}...")
                        return reply
                except json.JSONDecodeError:
                    # Maybe plain text response
                    reply = stdout.decode().strip()
                    if reply:
                        return reply
            
            log.error(f"Clawdbot error: {stderr.decode()[:200]}")
            return "Sorry, I couldn't reach Bando right now."
                
        except asyncio.TimeoutError:
            log.warning("Clawdbot request timed out")
            return "Bando is taking a while to respond. Try again?"
        except Exception as e:
            log.error(f"Clawdbot error: {e}")
            return f"Had trouble reaching Bando: {str(e)[:50]}"
    
    async def sync_transcript(self, transcript: str):
        """Sync call transcript to Clawdbot session via CLI."""
        if not self.config.sync_to_clawdbot:
            return
        
        try:
            cmd = [
                "clawdbot", "agent",
                "--message", f"[Voice call transcript]\n\n{transcript}",
                "--agent", "main"
            ]
            if self.config.clawdbot_session:
                cmd.extend(["--session-id", self.config.clawdbot_session])
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await asyncio.wait_for(process.communicate(), timeout=10.0)
            
        except Exception as e:
            log.warning(f"Failed to sync transcript: {e}")


class AudioResampler:
    """Audio resampling utilities."""
    
    @staticmethod
    def downsample(data: bytes, src_rate: int, dst_rate: int) -> bytes:
        if src_rate == dst_rate:
            return data
        ratio = src_rate // dst_rate
        samples = struct.unpack(f'<{len(data)//2}h', data)
        downsampled = samples[::ratio]
        return struct.pack(f'<{len(downsampled)}h', *downsampled)
    
    @staticmethod
    def upsample(data: bytes, src_rate: int, dst_rate: int) -> bytes:
        if src_rate == dst_rate:
            return data
        ratio = dst_rate // src_rate
        samples = struct.unpack(f'<{len(data)//2}h', data)
        upsampled = []
        for i in range(len(samples) - 1):
            upsampled.append(samples[i])
            for j in range(1, ratio):
                interp = samples[i] + (samples[i+1] - samples[i]) * j // ratio
                upsampled.append(interp)
        upsampled.append(samples[-1])
        return struct.pack(f'<{len(upsampled)}h', *upsampled)


class TranscriptLogger:
    """Saves conversation transcripts."""
    
    def __init__(self, output_dir: str = "transcripts"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.entries = []
        self.start_time = None
        self.current_file = None
    
    def start(self):
        self.start_time = datetime.now()
        self.entries = []
        filename = self.start_time.strftime("call_%Y%m%d_%H%M%S.txt")
        self.current_file = self.output_dir / filename
    
    def log(self, speaker: str, text: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {speaker}: {text}"
        self.entries.append(entry)
        
        # Write incrementally
        if self.current_file:
            with open(self.current_file, "a") as f:
                f.write(entry + "\n")
    
    def get_transcript(self) -> str:
        return "\n".join(self.entries)
    
    def stop(self):
        if self.current_file and self.entries:
            duration = (datetime.now() - self.start_time).total_seconds()
            with open(self.current_file, "a") as f:
                f.write(f"\n---\nCall duration: {duration:.1f}s\n")
            log.info(f"Transcript saved: {self.current_file}")


class RealtimeBridge:
    """Main bridge between phone and OpenAI Realtime API with Clawdbot integration."""
    
    def __init__(self, config: BandophoneConfig, audio_server: Optional[AudioServer] = None):
        self.config = config
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.is_running = False
        
        self.clawdbot = ClawdbotBridge(config)
        self.transcript = TranscriptLogger(config.transcripts_dir)
        self.resampler = AudioResampler()
        self.audio_server = audio_server
        
        # Playback callback
        self.on_audio_response: Optional[Callable[[bytes], None]] = None
        
        # State
        self.current_response_text = ""
        self.pending_function_call = None
        
    async def connect(self):
        """Connect to OpenAI Realtime API."""
        if not self.config.openai_api_key:
            raise ValueError("OpenAI API key required")
        
        headers = {
            "Authorization": f"Bearer {self.config.openai_api_key}",
            "OpenAI-Beta": "realtime=v1"
        }
        
        url = f"{OPENAI_REALTIME_URL}?model={OPENAI_MODEL}"
        
        log.info("Connecting to OpenAI Realtime...")
        self.ws = await websockets.connect(url, additional_headers=headers)
        self.is_connected = True
        log.info("✅ Connected!")
        
        await self._configure_session()
    
    async def _configure_session(self):
        """Configure Realtime session with ask_bando function."""
        config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": self.config.instructions,
                "voice": self.config.voice,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 700
                },
                "tools": [ASK_BANDO_FUNCTION],
                "tool_choice": "auto"
            }
        }
        
        await self.ws.send(json.dumps(config))
        log.info(f"Session configured: voice={self.config.voice}")
    
    async def send_audio(self, audio_data: bytes):
        """Send captured audio to OpenAI."""
        if not self.is_connected:
            return
        
        # Resample 48kHz → 24kHz
        resampled = self.resampler.downsample(
            audio_data,
            self.config.audio.capture_rate,
            self.config.audio.openai_rate
        )
        
        audio_b64 = base64.b64encode(resampled).decode('utf-8')
        await self.ws.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": audio_b64
        }))
    
    async def commit_audio(self):
        """Commit the audio buffer to trigger response generation."""
        if not self.is_connected:
            return
        
        log.debug("Committing audio buffer")
        await self.ws.send(json.dumps({
            "type": "input_audio_buffer.commit"
        }))
        
        # Also create a response
        await self.ws.send(json.dumps({
            "type": "response.create"
        }))
    
    async def handle_responses(self):
        """Handle responses from OpenAI Realtime."""
        try:
            async for message in self.ws:
                if not self.is_running:
                    break
                
                data = json.loads(message)
                event_type = data.get("type", "")
                
                await self._process_event(event_type, data)
                
        except websockets.exceptions.ConnectionClosed:
            log.warning("Connection closed")
            self.is_connected = False
    
    async def _process_event(self, event_type: str, data: dict):
        """Process events from Realtime API."""
        
        if self.config.verbose:
            log.debug(f"Event: {event_type}")
        
        if event_type == "session.created":
            log.debug("Session created")
        
        elif event_type == "response.audio.delta":
            # AI audio chunk
            audio_b64 = data.get("delta", "")
            if audio_b64:
                audio_data = base64.b64decode(audio_b64)
                # Resample 24kHz → 48kHz for playback
                resampled = self.resampler.upsample(
                    audio_data,
                    self.config.audio.openai_rate,
                    self.config.audio.playback_rate
                )
                
                # Send to Android app via WebSocket
                if self.audio_server and self.audio_server.has_clients:
                    asyncio.create_task(self.audio_server.send_audio(resampled))
                
                if self.on_audio_response:
                    self.on_audio_response(resampled)
        
        elif event_type == "response.audio_transcript.delta":
            text = data.get("delta", "")
            if text:
                self.current_response_text += text
                if self.config.verbose:
                    print(f"\r🤖 {self.current_response_text}", end="", flush=True)
        
        elif event_type == "response.audio_transcript.done":
            if self.current_response_text:
                if self.config.verbose:
                    print()
                self.transcript.log("AI", self.current_response_text)
                self.current_response_text = ""
        
        elif event_type == "conversation.item.input_audio_transcription.completed":
            text = data.get("transcript", "")
            if text:
                log.info(f"User: {text}")
                self.transcript.log("User", text)
        
        elif event_type == "response.function_call_arguments.delta":
            # Accumulate function call arguments
            if self.pending_function_call is None:
                self.pending_function_call = {"name": "", "arguments": ""}
            self.pending_function_call["arguments"] += data.get("delta", "")
        
        elif event_type == "response.function_call_arguments.done":
            # Function call complete - execute it
            if self.pending_function_call:
                await self._execute_function_call(data)
        
        elif event_type == "response.output_item.added":
            item = data.get("item", {})
            if item.get("type") == "function_call":
                self.pending_function_call = {
                    "name": item.get("name", ""),
                    "call_id": item.get("call_id", ""),
                    "arguments": ""
                }
        
        elif event_type == "error":
            error = data.get("error", {})
            log.error(f"API Error: {error.get('message', data)}")
    
    async def _execute_function_call(self, data: dict):
        """Execute ask_bando function and return result."""
        if not self.pending_function_call:
            return
        
        name = self.pending_function_call.get("name", "")
        call_id = self.pending_function_call.get("call_id") or data.get("call_id", "")
        args_str = self.pending_function_call.get("arguments", "{}")
        
        log.info(f"Function call: {name}")
        
        if name == "ask_bando":
            try:
                args = json.loads(args_str)
                request = args.get("request", "")
                context = args.get("context", "")
                urgent = args.get("urgent", False)
                
                # Call Clawdbot
                result = await self.clawdbot.ask_bando(request, context, urgent)
                
            except json.JSONDecodeError:
                result = "Sorry, I had trouble understanding that request."
            except Exception as e:
                log.error(f"Function call error: {e}")
                result = f"Error: {str(e)[:100]}"
        else:
            result = f"Unknown function: {name}"
        
        # Send result back to Realtime
        await self.ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": result
            }
        }))
        
        # Trigger response generation
        await self.ws.send(json.dumps({"type": "response.create"}))
        
        self.pending_function_call = None
    
    async def start(self):
        """Start the bridge - called after connect()."""
        self.is_running = True
        self.transcript.start()
    
    async def stop(self):
        """Stop the bridge."""
        self.is_running = False
        self.is_connected = False
        
        # Sync transcript to Clawdbot
        if self.transcript.entries:
            await self.clawdbot.sync_transcript(self.transcript.get_transcript())
        
        self.transcript.stop()
        
        if self.ws:
            await self.ws.close()
        
        log.info("Bridge stopped")


class PhoneCapture:
    """Audio capture from phone via ADB."""
    
    def __init__(self, config: BandophoneConfig):
        self.config = config
        self.process = None
        self.is_running = False
    
    def check_call_active(self) -> bool:
        cmd = ['adb', 'shell', 'su -c "export LD_LIBRARY_PATH=/data/local/tmp && /data/local/tmp/tinymix get \'Audio DSP State\'"']
        result = subprocess.run(cmd, capture_output=True, text=True)
        # The ">" marker indicates current state
        return "> Telephony" in result.stdout
    
    def setup_capture(self):
        cmd = ['adb', 'shell', 'su -c "export LD_LIBRARY_PATH=/data/local/tmp && /data/local/tmp/tinymix set \'Incall Capture Stream0\' \'UL_DL\'"']
        subprocess.run(cmd, capture_output=True)
    
    async def capture_loop(self, bridge: RealtimeBridge):
        """Capture and stream audio to bridge."""
        self.is_running = True
        
        log.info("Waiting for active call...")
        while self.is_running and not self.check_call_active():
            await asyncio.sleep(1)
        
        if not self.is_running:
            return
        
        log.info("📞 Call active! Starting capture...")
        self.setup_capture()
        
        rate = self.config.audio.capture_rate
        device = self.config.capture_device
        
        cmd = ['adb', 'shell', f'su -c "export LD_LIBRARY_PATH=/data/local/tmp && /data/local/tmp/tinycap /dev/stdout -D 0 -d {device} -c 1 -r {rate} -b 16"']
        
        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.process.stdout.read(44)  # Skip WAV header
        
        chunk_size = self.config.audio.capture_chunk_bytes
        
        while self.is_running:
            try:
                chunk = self.process.stdout.read(chunk_size)
                if not chunk:
                    if not self.check_call_active():
                        log.info("Call ended")
                        break
                    continue
                
                await bridge.send_audio(chunk)
                await asyncio.sleep(0.01)
                
            except Exception as e:
                log.error(f"Capture error: {e}")
                break
        
        self.stop()
    
    def stop(self):
        self.is_running = False
        if self.process:
            self.process.terminate()
            self.process = None


class FileCapture:
    """Capture from a pre-recorded audio file for testing."""
    
    def __init__(self, filepath: str, config: BandophoneConfig):
        self.filepath = filepath
        self.config = config
        self.is_running = False
    
    async def capture_loop(self, bridge: RealtimeBridge):
        """Stream audio from file to bridge."""
        import wave
        
        self.is_running = True
        log.info(f"📁 Playing test file: {self.filepath}")
        
        try:
            # Convert to proper format if needed
            temp_wav = "/tmp/bandophone_test_converted.wav"
            subprocess.run([
                "ffmpeg", "-y", "-i", self.filepath,
                "-ar", "24000", "-ac", "1", "-f", "wav", temp_wav
            ], capture_output=True)
            
            with wave.open(temp_wav, 'rb') as wf:
                chunk_frames = 2400  # 100ms at 24kHz
                
                while self.is_running:
                    chunk = wf.readframes(chunk_frames)
                    if not chunk:
                        log.info("File playback complete, committing audio...")
                        # Commit the audio buffer to trigger response
                        await bridge.commit_audio()
                        # Wait for response
                        await asyncio.sleep(10)
                        break
                    
                    await bridge.send_audio(chunk)
                    # Simulate real-time playback
                    await asyncio.sleep(0.1)
                    
        except Exception as e:
            log.error(f"File capture error: {e}")
        
        self.stop()
    
    def stop(self):
        self.is_running = False


async def main():
    parser = argparse.ArgumentParser(description="Bandophone Realtime Bridge")
    parser.add_argument("--config", "-c", help="Config file")
    parser.add_argument("--voice", "-v", choices=list(VOICES.keys()), help="Voice")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--api-key", help="OpenAI API key")
    parser.add_argument("--list-voices", action="store_true", help="List voices")
    parser.add_argument("--test-file", "-t", help="Test with audio file instead of live capture")
    parser.add_argument("--server-port", type=int, default=8765, help="WebSocket server port for Android app")
    
    args = parser.parse_args()
    
    if args.list_voices:
        for v, d in VOICES.items():
            print(f"  {v}: {d}")
        return
    
    config = BandophoneConfig.load(args.config or "bandophone.json")
    
    if args.voice:
        config.voice = args.voice
    if args.verbose:
        config.verbose = args.verbose
    if args.api_key:
        config.openai_api_key = args.api_key
    
    if not config.openai_api_key:
        config.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
    
    if not config.openai_api_key:
        print("Set OPENAI_API_KEY or use --api-key", file=sys.stderr)
        sys.exit(1)
    
    # Start audio server for Android app
    audio_server = AudioServer(port=args.server_port)
    await audio_server.start()
    
    bridge = RealtimeBridge(config, audio_server=audio_server)
    
    # Use file capture for testing, or live capture from phone
    if args.test_file:
        capture = FileCapture(args.test_file, config)
    else:
        capture = PhoneCapture(config)
    
    try:
        # Connect to OpenAI first
        await bridge.connect()
        bridge.is_running = True
        bridge.transcript.start()
        
        log.info("Bridge ready. Listening...")
        log.info(f"Android app can connect to ws://YOUR_MAC_IP:{args.server_port}")
        
        # Then run capture and response handling in parallel
        await asyncio.gather(
            bridge.handle_responses(),
            capture.capture_loop(bridge)
        )
    except KeyboardInterrupt:
        log.info("Interrupted")
    finally:
        capture.stop()
        await bridge.stop()
        await audio_server.stop()


if __name__ == "__main__":
    asyncio.run(main())
