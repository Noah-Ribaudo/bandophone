#!/usr/bin/env python3
"""
Twilio Test Server for Bandophone

Flask webhook server + WebSocket handler for Twilio Media Streams.
Serves TwiML to establish bidirectional Media Stream, then handles
the WebSocket connection for audio capture and injection.

Usage:
    python twilio_test_server.py [--port 5000] [--ws-port 8766]
    
    The server needs a public URL — use ngrok or similar:
    ngrok http 5000
"""

import asyncio
import base64
import json
import logging
import struct
import threading
import time
import wave
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from flask import Flask, Response, request

try:
    import websockets
    import websockets.server
except ImportError:
    print("pip install websockets", file=__import__('sys').stderr)
    raise

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger("twilio-server")

# ─── Audio Utilities ─────────────────────────────────────────────────────

def pcm16_to_mulaw(pcm_data: bytes) -> bytes:
    """Convert 16-bit PCM to 8-bit mu-law."""
    import audioop
    return audioop.lin2ulaw(pcm_data, 2)


def mulaw_to_pcm16(mulaw_data: bytes) -> bytes:
    """Convert 8-bit mu-law to 16-bit PCM."""
    import audioop
    return audioop.ulaw2lin(mulaw_data, 2)


def resample_pcm(data: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Simple resampling for PCM16 mono data."""
    if src_rate == dst_rate:
        return data
    import audioop
    return audioop.ratecv(data, 2, 1, src_rate, dst_rate, None)[0]


# ─── Media Stream Handler ───────────────────────────────────────────────

class MediaStreamSession:
    """Handles a single Twilio Media Stream WebSocket session."""
    
    def __init__(self, record: bool = False, output_dir: str = "results"):
        self.stream_sid: Optional[str] = None
        self.call_sid: Optional[str] = None
        self.account_sid: Optional[str] = None
        self.started_at: Optional[float] = None
        
        # Audio buffers
        self.received_audio: bytearray = bytearray()  # mulaw from Twilio (what Bandophone says)
        self.received_pcm: bytearray = bytearray()     # PCM16 version
        self.sent_chunks: int = 0
        self.received_chunks: int = 0
        
        # Recording
        self.record = record
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Callbacks
        self.on_audio_received: Optional[Callable[[bytes, float], None]] = None
        self.on_stream_start: Optional[Callable[[], None]] = None
        self.on_stream_stop: Optional[Callable[[], None]] = None
        
        # Latency tracking
        self.inject_time: Optional[float] = None
        self.first_response_time: Optional[float] = None
        self.latency_ms: Optional[float] = None
        
        # State
        self.is_active = False
        self.ws = None
        
    async def handle_websocket(self, websocket):
        """Handle incoming WebSocket connection from Twilio."""
        self.ws = websocket
        self.is_active = True
        self.started_at = time.time()
        log.info("📡 Media Stream WebSocket connected")
        
        try:
            async for message in websocket:
                data = json.loads(message)
                event = data.get("event", "")
                
                if event == "connected":
                    log.info("Twilio Media Stream connected")
                    
                elif event == "start":
                    self.stream_sid = data["start"]["streamSid"]
                    self.call_sid = data["start"]["callSid"]
                    self.account_sid = data["start"]["accountSid"]
                    log.info(f"Stream started: {self.stream_sid}")
                    log.info(f"Call SID: {self.call_sid}")
                    if self.on_stream_start:
                        self.on_stream_start()
                    
                elif event == "media":
                    payload_b64 = data["media"]["payload"]
                    mulaw_chunk = base64.b64decode(payload_b64)
                    timestamp = data["media"].get("timestamp", "")
                    
                    self.received_audio.extend(mulaw_chunk)
                    self.received_chunks += 1
                    
                    # Convert to PCM for analysis
                    pcm_chunk = mulaw_to_pcm16(mulaw_chunk)
                    self.received_pcm.extend(pcm_chunk)
                    
                    # Latency measurement: detect first non-silent response
                    if self.inject_time and not self.first_response_time:
                        # Check if audio is non-silent (RMS > threshold)
                        samples = struct.unpack(f'<{len(pcm_chunk)//2}h', pcm_chunk)
                        rms = (sum(s*s for s in samples) / max(len(samples), 1)) ** 0.5
                        if rms > 500:  # Non-trivial audio
                            self.first_response_time = time.time()
                            self.latency_ms = (self.first_response_time - self.inject_time) * 1000
                            log.info(f"⏱️  Response latency: {self.latency_ms:.0f}ms")
                    
                    if self.on_audio_received:
                        self.on_audio_received(pcm_chunk, float(timestamp) if timestamp else 0)
                    
                    if self.received_chunks % 100 == 0:
                        elapsed = time.time() - self.started_at
                        log.info(f"📥 Received {self.received_chunks} chunks ({len(self.received_audio)} bytes, {elapsed:.1f}s)")
                    
                elif event == "stop":
                    log.info("Stream stopped by Twilio")
                    if self.on_stream_stop:
                        self.on_stream_stop()
                    break
                    
                elif event == "mark":
                    log.debug(f"Mark event: {data.get('mark', {}).get('name', '')}")
                    
        except websockets.exceptions.ConnectionClosed:
            log.info("WebSocket connection closed")
        finally:
            self.is_active = False
            if self.record:
                self._save_recordings()
    
    async def send_audio(self, pcm_data: bytes, sample_rate: int = 8000):
        """Send audio to Twilio (which goes to Bandophone's capture).
        
        Args:
            pcm_data: PCM16 mono audio data
            sample_rate: Sample rate of pcm_data (will be resampled to 8kHz if needed)
        """
        if not self.is_active or not self.ws or not self.stream_sid:
            log.warning("Cannot send audio: stream not active")
            return
        
        # Resample to 8kHz if needed
        if sample_rate != 8000:
            pcm_data = resample_pcm(pcm_data, sample_rate, 8000)
        
        # Convert PCM16 to mulaw
        mulaw_data = pcm16_to_mulaw(pcm_data)
        
        # Send in chunks (Twilio expects ~20ms chunks = 160 bytes of mulaw)
        chunk_size = 160  # 20ms at 8kHz mulaw
        for i in range(0, len(mulaw_data), chunk_size):
            chunk = mulaw_data[i:i + chunk_size]
            payload = base64.b64encode(chunk).decode('utf-8')
            
            msg = {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {
                    "payload": payload
                }
            }
            
            try:
                await self.ws.send(json.dumps(msg))
                self.sent_chunks += 1
            except Exception as e:
                log.error(f"Send error: {e}")
                break
        
        log.info(f"📤 Sent {len(mulaw_data)} bytes ({self.sent_chunks} total chunks)")
    
    async def send_audio_file(self, filepath: str, mark_latency: bool = True):
        """Send a pre-encoded mulaw file to Twilio.
        
        Args:
            filepath: Path to 8kHz mulaw raw file or WAV file
            mark_latency: If True, mark injection time for latency measurement
        """
        if not self.is_active or not self.ws or not self.stream_sid:
            log.warning("Cannot send audio: stream not active")
            return
        
        filepath = Path(filepath)
        
        if filepath.suffix == '.wav':
            # Read WAV and convert
            with wave.open(str(filepath), 'rb') as wf:
                pcm_data = wf.readframes(wf.getnframes())
                rate = wf.getframerate()
                channels = wf.getnchannels()
                
                # Convert to mono if stereo
                if channels == 2:
                    import audioop
                    pcm_data = audioop.tomono(pcm_data, 2, 0.5, 0.5)
                
                # Resample to 8kHz
                if rate != 8000:
                    pcm_data = resample_pcm(pcm_data, rate, 8000)
                
                mulaw_data = pcm16_to_mulaw(pcm_data)
        elif filepath.suffix == '.ulaw' or filepath.suffix == '.mulaw':
            mulaw_data = filepath.read_bytes()
        elif filepath.suffix == '.raw':
            # Assume PCM16 8kHz mono
            pcm_data = filepath.read_bytes()
            mulaw_data = pcm16_to_mulaw(pcm_data)
        else:
            log.error(f"Unsupported audio format: {filepath.suffix}")
            return
        
        if mark_latency:
            self.inject_time = time.time()
            self.first_response_time = None
            self.latency_ms = None
            log.info(f"⏱️  Latency timer started at inject")
        
        # Send in real-time chunks (20ms each)
        chunk_size = 160  # 20ms at 8kHz mulaw
        for i in range(0, len(mulaw_data), chunk_size):
            if not self.is_active:
                break
            chunk = mulaw_data[i:i + chunk_size]
            payload = base64.b64encode(chunk).decode('utf-8')
            
            msg = {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {
                    "payload": payload
                }
            }
            
            try:
                await self.ws.send(json.dumps(msg))
                self.sent_chunks += 1
            except Exception as e:
                log.error(f"Send error: {e}")
                break
            
            # Pace to real-time (20ms per chunk)
            await asyncio.sleep(0.02)
        
        # Send a mark to know when audio is done
        await self.ws.send(json.dumps({
            "event": "mark",
            "streamSid": self.stream_sid,
            "mark": {"name": "inject_complete"}
        }))
        
        log.info(f"📤 Injected audio file: {filepath.name} ({len(mulaw_data)} bytes mulaw)")
    
    def _save_recordings(self):
        """Save received audio to WAV file."""
        if not self.received_pcm:
            log.info("No audio to save")
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        wav_path = self.output_dir / f"twilio_received_{timestamp}.wav"
        
        with wave.open(str(wav_path), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(8000)
            wf.writeframes(bytes(self.received_pcm))
        
        duration = len(self.received_pcm) / (8000 * 2)
        log.info(f"💾 Saved recording: {wav_path} ({duration:.1f}s)")
        
        # Save latency report
        if self.latency_ms is not None:
            report_path = self.output_dir / f"latency_{timestamp}.json"
            report = {
                "call_sid": self.call_sid,
                "stream_sid": self.stream_sid,
                "inject_time": self.inject_time,
                "first_response_time": self.first_response_time,
                "latency_ms": self.latency_ms,
                "total_received_chunks": self.received_chunks,
                "total_sent_chunks": self.sent_chunks,
                "duration_s": time.time() - self.started_at if self.started_at else 0,
            }
            report_path.write_text(json.dumps(report, indent=2))
            log.info(f"💾 Saved latency report: {report_path}")
    
    def get_stats(self) -> dict:
        """Get session statistics."""
        return {
            "stream_sid": self.stream_sid,
            "call_sid": self.call_sid,
            "is_active": self.is_active,
            "received_chunks": self.received_chunks,
            "sent_chunks": self.sent_chunks,
            "received_bytes": len(self.received_audio),
            "received_duration_s": len(self.received_pcm) / (8000 * 2) if self.received_pcm else 0,
            "latency_ms": self.latency_ms,
            "elapsed_s": time.time() - self.started_at if self.started_at else 0,
        }


# ─── Flask App (TwiML Webhooks) ─────────────────────────────────────────

app = Flask(__name__)

# Global state shared between Flask and WebSocket
_current_session: Optional[MediaStreamSession] = None
_ws_host: str = "localhost"
_ws_port: int = 8766


@app.route("/voice", methods=["POST"])
def voice_webhook():
    """TwiML webhook for outbound calls. Establishes Media Stream."""
    log.info(f"📞 Voice webhook hit! CallSid={request.form.get('CallSid', 'unknown')}")
    
    # Construct WebSocket URL — Twilio needs wss:// for production,
    # but for ngrok tunneling we use the same host
    ws_url = f"wss://{request.host}/media-stream"
    
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}">
            <Parameter name="test" value="bandophone" />
        </Stream>
    </Connect>
</Response>"""
    
    log.info(f"TwiML response with stream URL: {ws_url}")
    return Response(twiml, mimetype="text/xml")


@app.route("/status", methods=["POST"])
def status_callback():
    """Status callback for call events."""
    status = request.form.get("CallStatus", "unknown")
    call_sid = request.form.get("CallSid", "unknown")
    log.info(f"📊 Call status: {status} (SID: {call_sid})")
    return "", 200


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    stats = _current_session.get_stats() if _current_session else {}
    return json.dumps({"status": "ok", "session": stats}), 200


# ─── WebSocket Server ───────────────────────────────────────────────────

async def websocket_handler(websocket, path=None):
    """Handle incoming Twilio Media Stream WebSocket."""
    global _current_session
    
    log.info(f"🔌 WebSocket connection from {websocket.remote_address}")
    
    if _current_session is None:
        _current_session = MediaStreamSession(record=True)
    
    await _current_session.handle_websocket(websocket)


def get_session() -> Optional[MediaStreamSession]:
    """Get the current media stream session."""
    return _current_session


def create_session(record: bool = True, output_dir: str = "results") -> MediaStreamSession:
    """Create a new media stream session."""
    global _current_session
    _current_session = MediaStreamSession(record=record, output_dir=output_dir)
    return _current_session


# ─── Server Launcher ────────────────────────────────────────────────────

def run_flask(port: int = 5000):
    """Run Flask in a thread."""
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


async def run_websocket_server(host: str = "0.0.0.0", port: int = 8766):
    """Run WebSocket server."""
    server = await websockets.server.serve(websocket_handler, host, port)
    log.info(f"🌐 WebSocket server listening on ws://{host}:{port}")
    await server.wait_closed()


def start_servers(flask_port: int = 5000, ws_port: int = 8766):
    """Start both Flask and WebSocket servers.
    
    Returns (flask_thread, ws_loop) — call this from the test runner.
    """
    global _ws_port
    _ws_port = ws_port
    
    # Flask in a thread
    flask_thread = threading.Thread(
        target=run_flask,
        args=(flask_port,),
        daemon=True
    )
    flask_thread.start()
    log.info(f"🌐 Flask server started on port {flask_port}")
    
    return flask_thread


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Twilio Test Server")
    parser.add_argument("--port", type=int, default=5000, help="Flask HTTP port")
    parser.add_argument("--ws-port", type=int, default=8766, help="WebSocket port")
    args = parser.parse_args()
    
    # Start Flask in a thread
    start_servers(flask_port=args.port, ws_port=args.ws_port)
    
    # Run WebSocket server in main event loop
    asyncio.run(run_websocket_server(port=args.ws_port))
