#!/usr/bin/env python3
"""
Bandophone Realtime Bridge

Full-featured integration with OpenAI Realtime API.
Handles capture, streaming, AI responses, and playback coordination.

Usage:
    python realtime_bridge.py --personality assistant --voice alloy
    python realtime_bridge.py --config bandophone.json
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
    print("pip install websockets", file=sys.stderr)
    sys.exit(1)

from config import BandophoneConfig, VOICES, PERSONALITIES, list_voices, list_personalities

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger("bandophone")

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"
OPENAI_MODEL = "gpt-4o-realtime-preview-2024-12-17"


class AudioResampler:
    """Simple audio resampling utilities."""
    
    @staticmethod
    def downsample(data: bytes, src_rate: int, dst_rate: int) -> bytes:
        """Downsample audio by integer factor."""
        if src_rate == dst_rate:
            return data
        
        ratio = src_rate // dst_rate
        if ratio <= 0:
            raise ValueError(f"Cannot downsample from {src_rate} to {dst_rate}")
        
        samples = struct.unpack(f'<{len(data)//2}h', data)
        downsampled = samples[::ratio]
        return struct.pack(f'<{len(downsampled)}h', *downsampled)
    
    @staticmethod
    def upsample(data: bytes, src_rate: int, dst_rate: int) -> bytes:
        """Upsample audio by integer factor (simple linear interpolation)."""
        if src_rate == dst_rate:
            return data
        
        ratio = dst_rate // src_rate
        if ratio <= 0:
            raise ValueError(f"Cannot upsample from {src_rate} to {dst_rate}")
        
        samples = struct.unpack(f'<{len(data)//2}h', data)
        upsampled = []
        
        for i in range(len(samples) - 1):
            upsampled.append(samples[i])
            # Linear interpolation
            for j in range(1, ratio):
                interp = samples[i] + (samples[i+1] - samples[i]) * j // ratio
                upsampled.append(interp)
        
        upsampled.append(samples[-1])
        return struct.pack(f'<{len(upsampled)}h', *upsampled)


class CallRecorder:
    """Records call audio for later review."""
    
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.current_file: Optional[Path] = None
        self.file_handle = None
        self.start_time: Optional[datetime] = None
    
    def start(self):
        """Start a new recording."""
        self.start_time = datetime.now()
        filename = self.start_time.strftime("call_%Y%m%d_%H%M%S.raw")
        self.current_file = self.output_dir / filename
        self.file_handle = open(self.current_file, "wb")
        log.info(f"Recording to {self.current_file}")
    
    def write(self, data: bytes):
        """Write audio data to recording."""
        if self.file_handle:
            self.file_handle.write(data)
    
    def stop(self) -> Optional[Path]:
        """Stop recording and return the file path."""
        if self.file_handle:
            self.file_handle.close()
            self.file_handle = None
            
            duration = (datetime.now() - self.start_time).total_seconds()
            log.info(f"Recording stopped: {duration:.1f}s")
            
            return self.current_file
        return None


class TranscriptLogger:
    """Logs conversation transcripts."""
    
    def __init__(self, output_dir: str = "transcripts"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.current_file: Optional[Path] = None
        self.file_handle = None
    
    def start(self):
        """Start a new transcript."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_file = self.output_dir / f"transcript_{timestamp}.txt"
        self.file_handle = open(self.current_file, "w")
        self.file_handle.write(f"Call started: {datetime.now().isoformat()}\n")
        self.file_handle.write("-" * 50 + "\n\n")
    
    def log_user(self, text: str):
        """Log user speech."""
        if self.file_handle:
            self.file_handle.write(f"USER: {text}\n\n")
            self.file_handle.flush()
    
    def log_ai(self, text: str):
        """Log AI speech."""
        if self.file_handle:
            self.file_handle.write(f"AI: {text}\n\n")
            self.file_handle.flush()
    
    def stop(self):
        """Stop logging."""
        if self.file_handle:
            self.file_handle.write("-" * 50 + "\n")
            self.file_handle.write(f"Call ended: {datetime.now().isoformat()}\n")
            self.file_handle.close()
            self.file_handle = None


class RealtimeBridge:
    """Main bridge between phone call and OpenAI Realtime API."""
    
    def __init__(self, config: BandophoneConfig):
        self.config = config
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.is_running = False
        
        # Components
        self.recorder = CallRecorder(config.recordings_dir) if config.save_recordings else None
        self.transcript = TranscriptLogger()
        self.resampler = AudioResampler()
        
        # Callbacks for playback
        self.on_audio_response: Optional[Callable[[bytes], None]] = None
        
        # State
        self.current_ai_text = ""
        
    async def connect(self):
        """Connect to OpenAI Realtime API."""
        if not self.config.openai_api_key:
            raise ValueError("OpenAI API key not set")
        
        headers = {
            "Authorization": f"Bearer {self.config.openai_api_key}",
            "OpenAI-Beta": "realtime=v1"
        }
        
        url = f"{OPENAI_REALTIME_URL}?model={OPENAI_MODEL}"
        
        log.info("Connecting to OpenAI Realtime API...")
        self.ws = await websockets.connect(url, extra_headers=headers)
        self.is_connected = True
        log.info("✅ Connected to OpenAI")
        
        await self._configure_session()
    
    async def _configure_session(self):
        """Configure the Realtime session."""
        config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": self.config.get_instructions(),
                "voice": self.config.get_voice(),
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
                }
            }
        }
        
        await self.ws.send(json.dumps(config))
        log.info(f"Session configured: voice={self.config.get_voice()}, personality={self.config.personality}")
    
    async def send_audio(self, audio_data: bytes):
        """Send captured audio to OpenAI."""
        if not self.is_connected:
            return
        
        # Resample from capture rate to OpenAI rate
        resampled = self.resampler.downsample(
            audio_data,
            self.config.audio.capture_rate,
            self.config.audio.openai_rate
        )
        
        # Save to recording
        if self.recorder:
            self.recorder.write(audio_data)
        
        # Send to OpenAI
        audio_b64 = base64.b64encode(resampled).decode('utf-8')
        message = {
            "type": "input_audio_buffer.append",
            "audio": audio_b64
        }
        
        await self.ws.send(json.dumps(message))
    
    async def handle_responses(self):
        """Handle responses from OpenAI."""
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
        """Process a single event from OpenAI."""
        
        if event_type == "session.created":
            log.info("Session created")
        
        elif event_type == "session.updated":
            log.debug("Session updated")
        
        elif event_type == "response.audio.delta":
            # Received audio chunk from AI
            audio_b64 = data.get("delta", "")
            if audio_b64:
                audio_data = base64.b64decode(audio_b64)
                
                # Resample from OpenAI rate to playback rate
                resampled = self.resampler.upsample(
                    audio_data,
                    self.config.audio.openai_rate,
                    self.config.audio.playback_rate
                )
                
                # Send to playback handler
                if self.on_audio_response:
                    self.on_audio_response(resampled)
        
        elif event_type == "response.audio.done":
            log.debug("AI audio response complete")
        
        elif event_type == "response.audio_transcript.delta":
            # AI's speech being transcribed
            text = data.get("delta", "")
            if text:
                self.current_ai_text += text
                if self.config.verbose:
                    print(f"\r🤖 {self.current_ai_text}", end="", flush=True)
        
        elif event_type == "response.audio_transcript.done":
            # AI finished speaking
            if self.current_ai_text:
                if self.config.verbose:
                    print()  # Newline after progressive output
                log.info(f"AI: {self.current_ai_text}")
                self.transcript.log_ai(self.current_ai_text)
                self.current_ai_text = ""
        
        elif event_type == "conversation.item.input_audio_transcription.completed":
            # User's speech transcribed
            text = data.get("transcript", "")
            if text:
                log.info(f"User: {text}")
                self.transcript.log_user(text)
        
        elif event_type == "input_audio_buffer.speech_started":
            log.debug("User started speaking")
        
        elif event_type == "input_audio_buffer.speech_stopped":
            log.debug("User stopped speaking")
        
        elif event_type == "error":
            error = data.get("error", {})
            log.error(f"API Error: {error.get('message', data)}")
    
    async def start(self):
        """Start the bridge."""
        self.is_running = True
        
        # Start recording/transcription
        if self.recorder:
            self.recorder.start()
        self.transcript.start()
        
        await self.connect()
        
        # Run response handler
        await self.handle_responses()
    
    async def stop(self):
        """Stop the bridge."""
        self.is_running = False
        self.is_connected = False
        
        # Stop recording/transcription
        if self.recorder:
            self.recorder.stop()
        self.transcript.stop()
        
        if self.ws:
            await self.ws.close()
        
        log.info("Bridge stopped")


class PhoneCapture:
    """Handles audio capture from phone via ADB."""
    
    def __init__(self, config: BandophoneConfig):
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self.is_running = False
    
    def _get_adb_prefix(self) -> str:
        """Get ADB command prefix."""
        if self.config.adb_device:
            return f"adb -s {self.config.adb_device}"
        return "adb"
    
    def check_call_active(self) -> bool:
        """Check if a call is currently active."""
        cmd = f'{self._get_adb_prefix()} shell "su -c \'export LD_LIBRARY_PATH=/data/local/tmp && /data/local/tmp/tinymix get \"Audio DSP State\"\'"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return "Telephony" in result.stdout
    
    def setup_capture(self):
        """Configure mixer for capture."""
        adb = self._get_adb_prefix()
        cmd = f'{adb} shell "su -c \'export LD_LIBRARY_PATH=/data/local/tmp && /data/local/tmp/tinymix set \"Incall Capture Stream0\" \"UL_DL\"\'"'
        subprocess.run(cmd, shell=True, capture_output=True)
        log.info("Capture configured for UL_DL mode")
    
    async def capture_loop(self, bridge: RealtimeBridge):
        """Capture audio and send to bridge."""
        self.is_running = True
        
        # Wait for call to be active
        log.info("Waiting for active call...")
        while self.is_running and not self.check_call_active():
            await asyncio.sleep(1)
        
        if not self.is_running:
            return
        
        log.info("📞 Call detected! Starting capture...")
        self.setup_capture()
        
        # Start tinycap process
        adb = self._get_adb_prefix()
        rate = self.config.audio.capture_rate
        device = self.config.capture_device
        
        cmd = f'{adb} shell "su -c \'export LD_LIBRARY_PATH=/data/local/tmp && /data/local/tmp/tinycap /dev/stdout -D 0 -d {device} -c 1 -r {rate} -b 16\'"'
        
        self.process = subprocess.Popen(
            cmd, shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        
        # Skip WAV header
        self.process.stdout.read(44)
        
        chunk_size = self.config.audio.capture_chunk_bytes
        
        while self.is_running:
            try:
                chunk = self.process.stdout.read(chunk_size)
                if not chunk:
                    # Check if call ended
                    if not self.check_call_active():
                        log.info("Call ended")
                        break
                    continue
                
                await bridge.send_audio(chunk)
                await asyncio.sleep(0.01)  # Small delay to prevent overwhelming
                
            except Exception as e:
                log.error(f"Capture error: {e}")
                break
        
        self.stop()
    
    def stop(self):
        """Stop capture."""
        self.is_running = False
        if self.process:
            self.process.terminate()
            self.process = None


async def main():
    parser = argparse.ArgumentParser(description="Bandophone Realtime Bridge")
    parser.add_argument("--config", "-c", help="Config file path")
    parser.add_argument("--personality", "-p", choices=list(PERSONALITIES.keys()), help="Personality preset")
    parser.add_argument("--voice", "-v", choices=list(VOICES.keys()), help="Voice to use")
    parser.add_argument("--list-voices", action="store_true", help="List available voices")
    parser.add_argument("--list-personalities", action="store_true", help="List available personalities")
    parser.add_argument("--transcribe-only", action="store_true", help="Only transcribe, no AI response")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--api-key", help="OpenAI API key (or set OPENAI_API_KEY env)")
    
    args = parser.parse_args()
    
    if args.list_voices:
        list_voices()
        return
    
    if args.list_personalities:
        list_personalities()
        return
    
    # Load config
    if args.config:
        config = BandophoneConfig.load(args.config)
    else:
        config = BandophoneConfig()
    
    # Override with CLI args
    if args.personality:
        config.personality = args.personality
    if args.voice:
        config.voice = args.voice
    if args.transcribe_only:
        config.transcribe_only = args.transcribe_only
    if args.verbose:
        config.verbose = args.verbose
    if args.api_key:
        config.openai_api_key = args.api_key
    
    # Get API key from env if not set
    if not config.openai_api_key:
        config.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
    
    if not config.openai_api_key:
        print("Error: OpenAI API key required. Set OPENAI_API_KEY or use --api-key", file=sys.stderr)
        sys.exit(1)
    
    # Create bridge and capture
    bridge = RealtimeBridge(config)
    capture = PhoneCapture(config)
    
    # TODO: Set up playback handler when Android app is ready
    # bridge.on_audio_response = playback_handler
    
    try:
        # Run bridge and capture in parallel
        await asyncio.gather(
            bridge.start(),
            capture.capture_loop(bridge)
        )
    except KeyboardInterrupt:
        log.info("Interrupted")
    finally:
        capture.stop()
        await bridge.stop()


if __name__ == "__main__":
    asyncio.run(main())
