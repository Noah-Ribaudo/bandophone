#!/usr/bin/env python3
"""
Bandophone Phase 2: Bidirectional Media Streams Test

Tests Twilio Media Streams by:
1. Starting Flask+WebSocket server on port 5050
2. Starting cloudflared tunnel
3. Initiating call to Pixel via Twilio
4. Auto-answering on Pixel via ADB
5. Receiving audio, injecting test audio back
6. Saving results and measurements
"""

import os
import sys
import json
import time
import base64
import struct
import wave
import subprocess
import threading
import signal
import logging
import re
from datetime import datetime
from pathlib import Path

# Add venv packages
sys.path.insert(0, str(Path(__file__).parent / '.venv' / 'lib' / 'python3.13' / 'site-packages'))

from flask import Flask, request, Response
from flask_sock import Sock
from twilio.rest import Client as TwilioClient

# ─── Config ───────────────────────────────────────────────────────────────────
PORT = 5050
PIXEL_NUMBER = "+17736984245"
ADB_DEVICE = "192.168.4.167:5555"
CALL_DURATION = 30  # seconds
INJECT_DELAY = 3    # seconds after stream starts before injecting audio
AUDIO_DIR = Path(__file__).parent / "audio"
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ─── Logging ──────────────────────────────────────────────────────────────────
run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = RESULTS_DIR / f"media_stream_{run_id}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("media_streams")

# ─── Globals ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
sock = Sock(app)

tunnel_url = None
tunnel_process = None
call_sid = None
stream_sid = None
ws_connected = threading.Event()
stream_started = threading.Event()
first_audio_received = threading.Event()
test_complete = threading.Event()

# Timestamps for latency
timestamps = {
    "server_started": None,
    "tunnel_ready": None,
    "call_initiated": None,
    "call_answered": None,
    "ws_connected": None,
    "stream_started": None,
    "first_audio_received": None,
    "audio_injection_started": None,
    "audio_injection_complete": None,
    "call_ended": None,
}

# Audio collection
received_chunks = []  # list of (timestamp, sequence, chunk_data_bytes)
received_before_inject = []
received_after_inject = []
injection_time = None

# ─── Twilio Credentials ──────────────────────────────────────────────────────
def get_keychain(name):
    result = subprocess.run(
        ["security", "find-generic-password", "-a", "bando", "-s", name, "-w"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get {name} from Keychain")
    return result.stdout.strip()

TWILIO_SID = get_keychain("twilio-account-sid")
TWILIO_TOKEN = get_keychain("twilio-auth-token")
TWILIO_NUMBER = get_keychain("twilio-phone-number")

# ─── Audio Helpers ────────────────────────────────────────────────────────────
def load_test_audio():
    """Load pre-generated ulaw audio for injection."""
    ulaw_file = AUDIO_DIR / "greeting.ulaw"
    if ulaw_file.exists():
        data = ulaw_file.read_bytes()
        log.info(f"Loaded test audio: {ulaw_file.name} ({len(data)} bytes, {len(data)/8000:.2f}s)")
        return data

    # Fallback: generate with say + ffmpeg
    log.info("Generating test audio with macOS say...")
    subprocess.run(["say", "-o", "/tmp/test_bandophone.aiff", "Hello, can you hear me?"], check=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", "/tmp/test_bandophone.aiff",
        "-ar", "8000", "-ac", "1", "-f", "mulaw", "/tmp/test_bandophone.ulaw"
    ], check=True, capture_output=True)
    data = Path("/tmp/test_bandophone.ulaw").read_bytes()
    log.info(f"Generated test audio: {len(data)} bytes, {len(data)/8000:.2f}s")
    return data

def ulaw_to_pcm16(ulaw_bytes):
    """Convert mu-law bytes to 16-bit PCM using the standard decoding table."""
    import audioop
    return audioop.ulaw2lin(ulaw_bytes, 2)

def save_audio_to_wav(pcm_data, filename):
    """Save raw 16-bit PCM data as WAV file."""
    filepath = RESULTS_DIR / filename
    with wave.open(str(filepath), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(pcm_data)
    log.info(f"Saved WAV: {filepath} ({len(pcm_data)} bytes)")
    return filepath

# ─── Flask Routes ─────────────────────────────────────────────────────────────
@app.route("/voice", methods=["POST"])
def voice_webhook():
    """Twilio voice webhook — returns TwiML to start a Media Stream."""
    log.info(f"Voice webhook hit! CallSid={request.form.get('CallSid')}")
    log.info(f"  CallStatus={request.form.get('CallStatus')}")

    ws_url = tunnel_url.replace("https://", "wss://") + "/stream"
    log.info(f"  Stream URL: {ws_url}")

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Starting media stream test.</Say>
    <Connect>
        <Stream url="{ws_url}" />
    </Connect>
</Response>"""

    log.info(f"  Returning TwiML with Stream")
    return Response(twiml, mimetype="text/xml")

@app.route("/status", methods=["POST"])
def status_callback():
    """Twilio status callback."""
    status = request.form.get("CallStatus", "unknown")
    log.info(f"Call status callback: {status}")
    if status == "in-progress":
        timestamps["call_answered"] = time.time()
    elif status in ("completed", "failed", "busy", "no-answer"):
        timestamps["call_ended"] = time.time()
    return "", 200

@app.route("/connect-action", methods=["POST"])
def connect_action():
    """Called when <Connect> ends — reveals Stream errors."""
    log.info("=" * 40)
    log.info("CONNECT ACTION CALLBACK!")
    log.info(f"  Form data: {dict(request.form)}")
    log.info("=" * 40)
    # Return TwiML to keep the call alive a bit
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?><Response><Say>Connect action received.</Say></Response>',
        mimetype="text/xml",
    )

@app.route("/health")
def health():
    return "ok"

@app.before_request
def log_request():
    log.info(f"Incoming request: {request.method} {request.path} from {request.remote_addr}")
    if request.content_type and "form" in request.content_type:
        log.info(f"  Form data: {dict(request.form)}")

# ─── WebSocket Handler ────────────────────────────────────────────────────────
@sock.route("/stream")
def stream_handler(ws):
    """Handle Twilio Media Stream WebSocket."""
    global stream_sid, injection_time

    log.info("WebSocket connection opened!")
    timestamps["ws_connected"] = time.time()
    ws_connected.set()

    test_audio = load_test_audio()
    audio_injected = False
    stream_start_time = None
    chunk_count = 0

    try:
        while not test_complete.is_set():
            try:
                raw = ws.receive(timeout=1)
            except Exception:
                if test_complete.is_set():
                    break
                continue

            if raw is None:
                break

            msg = json.loads(raw)
            event = msg.get("event")

            if event == "connected":
                log.info(f"Stream connected: protocol={msg.get('protocol')}")

            elif event == "start":
                stream_sid = msg["start"]["streamSid"]
                media_format = msg["start"].get("mediaFormat", {})
                log.info(f"Stream started! SID={stream_sid}")
                log.info(f"  Media format: {json.dumps(media_format)}")
                log.info(f"  Tracks: {msg['start'].get('tracks', [])}")
                timestamps["stream_started"] = time.time()
                stream_start_time = time.time()
                stream_started.set()

            elif event == "media":
                chunk_count += 1
                media = msg["media"]
                payload = base64.b64decode(media["payload"])
                ts = float(media.get("timestamp", 0))
                seq = int(msg.get("sequenceNumber", 0))

                if not first_audio_received.is_set():
                    timestamps["first_audio_received"] = time.time()
                    first_audio_received.set()
                    log.info(f"First audio chunk received! ({len(payload)} bytes, seq={seq})")

                received_chunks.append((time.time(), seq, payload))

                if injection_time is None:
                    received_before_inject.append(payload)
                else:
                    received_after_inject.append(payload)

                # Log periodically
                if chunk_count % 50 == 0:
                    elapsed = time.time() - stream_start_time if stream_start_time else 0
                    log.info(f"  Received {chunk_count} chunks ({elapsed:.1f}s elapsed)")

                # Inject audio after delay
                if (not audio_injected and stream_start_time and
                        time.time() - stream_start_time >= INJECT_DELAY):
                    audio_injected = True
                    injection_time = time.time()
                    timestamps["audio_injection_started"] = injection_time
                    log.info(f"Injecting test audio ({len(test_audio)} bytes = {len(test_audio)/8000:.2f}s)...")

                    # Send in 160-byte chunks (20ms each)
                    chunk_size = 160
                    chunks_sent = 0
                    for i in range(0, len(test_audio), chunk_size):
                        chunk = test_audio[i:i+chunk_size]
                        # Pad last chunk if needed
                        if len(chunk) < chunk_size:
                            chunk = chunk + b'\xff' * (chunk_size - len(chunk))  # 0xff = silence in mulaw

                        send_msg = json.dumps({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {
                                "payload": base64.b64encode(chunk).decode("ascii")
                            }
                        })
                        ws.send(send_msg)
                        chunks_sent += 1

                    timestamps["audio_injection_complete"] = time.time()
                    inject_duration = timestamps["audio_injection_complete"] - injection_time
                    log.info(f"Audio injection complete: {chunks_sent} chunks sent in {inject_duration*1000:.1f}ms")

            elif event == "stop":
                log.info(f"Stream stopped. AccountSid={msg.get('stop', {}).get('accountSid', 'N/A')}")
                break

            elif event == "mark":
                log.info(f"Mark event: {msg.get('mark', {}).get('name', 'unknown')}")

            else:
                log.info(f"Unknown event: {event}")

    except Exception as e:
        log.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        log.info(f"WebSocket closed. Total chunks received: {chunk_count}")

# ─── Cloudflared Tunnel ──────────────────────────────────────────────────────
def start_tunnel():
    """Start cloudflared tunnel and extract the URL."""
    global tunnel_url, tunnel_process

    log.info("Starting cloudflared tunnel...")
    tunnel_process = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{PORT}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Read output to find the tunnel URL and wait for connection registration
    url_pattern = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
    registered_pattern = re.compile(r"Registered tunnel connection")
    deadline = time.time() + 30
    got_url = False
    got_registered = False

    for line in iter(tunnel_process.stdout.readline, ""):
        log.info(f"  cloudflared: {line.strip()}")
        
        if not got_url:
            match = url_pattern.search(line)
            if match:
                tunnel_url = match.group(0)
                log.info(f"Tunnel URL: {tunnel_url}")
                got_url = True
        
        if registered_pattern.search(line):
            got_registered = True
            timestamps["tunnel_ready"] = time.time()
            log.info("Tunnel connection registered!")
        
        if got_url and got_registered:
            break
            
        if time.time() > deadline:
            if got_url:
                log.warning("Tunnel URL found but connection not yet registered — proceeding anyway")
                timestamps["tunnel_ready"] = time.time()
                break
            raise TimeoutError("cloudflared didn't produce URL in 30s")

    # Continue reading in background
    def drain():
        for line in iter(tunnel_process.stdout.readline, ""):
            if line:
                log.debug(f"  cloudflared: {line.strip()}")
    threading.Thread(target=drain, daemon=True).start()

    return tunnel_url

# ─── ADB Auto-Answer ─────────────────────────────────────────────────────────
def auto_answer_pixel():
    """Wait for phone to ring, then answer via ADB. Only send ONE keyevent!
    
    IMPORTANT: Sending CALL keyevent toggles the call state.
    First press = answer. Second press = HANG UP. So we send exactly once
    and then wait for the stream to connect.
    """
    log.info("Waiting to auto-answer on Pixel...")
    time.sleep(5)  # Give the call time to reach the phone

    # Send exactly ONE answer keyevent
    log.info("Sending answer keyevent...")
    result = subprocess.run(
        ["adb", "-s", ADB_DEVICE, "shell", "input", "keyevent", "CALL"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        log.info("✅ Sent CALL keyevent to Pixel (answering call)")
    else:
        log.warning(f"ADB error: {result.stderr}")
        return False

    # Now just wait for the WebSocket stream to connect
    log.info("Call answered — waiting for Media Stream WebSocket...")
    if ws_connected.wait(timeout=20):
        log.info("WebSocket connected — stream is live!")
        return True

    log.warning("Call answered but WebSocket never connected (Stream may have failed)")
    return False

# ─── Main Test ────────────────────────────────────────────────────────────────
def run_test():
    global call_sid

    log.info("=" * 60)
    log.info("BANDOPHONE PHASE 2: Media Streams Test")
    log.info("=" * 60)

    timestamps["server_started"] = time.time()

    # 1. Start cloudflared
    start_tunnel()
    if not tunnel_url:
        log.error("No tunnel URL — aborting")
        return

    # 2. Start Flask in background
    log.info(f"Starting Flask server on port {PORT}...")
    flask_thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False),
        daemon=True,
    )
    flask_thread.start()
    time.sleep(2)  # Let Flask start

    # 3. Verify server is up locally
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"http://localhost:{PORT}/health")
        log.info(f"Flask local health check: {resp.read().decode()}")
    except Exception as e:
        log.error(f"Flask not responding locally: {e}")
        return

    # 4. Verify tunnel is accessible (use public DNS since Tailscale MagicDNS can't resolve cloudflare)
    log.info("Verifying tunnel via curl with explicit DNS...")
    tunnel_ok = False
    for attempt in range(15):
        try:
            # Use --resolve to bypass Tailscale DNS
            host = tunnel_url.replace("https://", "")
            result = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 "--max-time", "5",
                 "--resolve", f"{host}:443:104.16.230.132",
                 f"{tunnel_url}/health"],
                capture_output=True, text=True, timeout=10,
            )
            code = result.stdout.strip()
            log.info(f"Tunnel health check attempt {attempt+1}: HTTP {code}")
            if code == "200":
                tunnel_ok = True
                break
            elif code == "502":
                log.info(f"  Got 502 — tunnel routing not ready yet")
        except Exception as e:
            log.info(f"Tunnel check attempt {attempt+1} failed: {e}")
        time.sleep(2)

    if not tunnel_ok:
        # Twilio uses its own DNS, so even if we can't verify locally, proceed
        log.warning("Couldn't verify tunnel locally (Tailscale DNS issue) — proceeding anyway since Twilio has its own DNS")
    else:
        log.info("Tunnel verified and accessible!")

    log.info(f"Initiating call: {TWILIO_NUMBER} → {PIXEL_NUMBER}")
    twilio = TwilioClient(TWILIO_SID, TWILIO_TOKEN)

    # Use inline TwiML instead of webhook URL (avoids any webhook fetch issues)
    ws_url = tunnel_url.replace("https://", "wss://") + "/stream"
    status_url = f"{tunnel_url}/status"
    connect_action_url = f"{tunnel_url}/connect-action"
    twiml_str = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Starting media stream test.</Say>
    <Connect action="{connect_action_url}">
        <Stream url="{ws_url}" />
    </Connect>
    <Say>Stream connection ended or failed. Goodbye.</Say>
</Response>"""

    log.info(f"  Stream WebSocket URL: {ws_url}")
    log.info(f"  Status URL: {status_url}")
    log.info(f"  Connect action URL: {connect_action_url}")
    log.info(f"  TwiML (inline): {twiml_str.strip()}")

    call = twilio.calls.create(
        to=PIXEL_NUMBER,
        from_=TWILIO_NUMBER,
        twiml=twiml_str,
        status_callback=status_url,
        status_callback_event=["initiated", "ringing", "answered", "completed"],
        timeout=30,
    )
    call_sid = call.sid
    timestamps["call_initiated"] = time.time()
    log.info(f"Call initiated! SID={call_sid}")

    # 6. Auto-answer on Pixel
    answer_thread = threading.Thread(target=auto_answer_pixel, daemon=True)
    answer_thread.start()

    # 7. Wait for stream or timeout
    log.info(f"Waiting up to {CALL_DURATION}s for test to complete...")
    stream_started.wait(timeout=20)

    if stream_started.is_set():
        log.info("Stream is active — letting it run...")
        # Wait for the remaining duration
        elapsed = time.time() - timestamps["stream_started"]
        remaining = CALL_DURATION - elapsed
        if remaining > 0:
            test_complete.wait(timeout=remaining)
    else:
        log.warning("Stream never started!")
        # Check if voice webhook was at least hit
        if not ws_connected.is_set():
            log.warning("WebSocket never connected — voice webhook may not have been reached")
            log.warning("This could be a DNS/tunnel issue — Twilio couldn't reach the webhook URL")
        time.sleep(5)

    # 8. Hang up
    test_complete.set()
    log.info("Ending call...")
    try:
        twilio.calls(call_sid).update(status="completed")
        timestamps["call_ended"] = time.time()
        log.info("Call terminated via API")
    except Exception as e:
        log.warning(f"Error ending call: {e}")

    time.sleep(2)  # Let WebSocket close cleanly

    # 9. Save results
    save_results()

def save_results():
    """Save audio and analysis."""
    log.info("\n" + "=" * 60)
    log.info("RESULTS")
    log.info("=" * 60)

    # Audio stats
    total_chunks = len(received_chunks)
    total_bytes = sum(len(c[2]) for c in received_chunks)
    log.info(f"Total audio chunks received: {total_chunks}")
    log.info(f"Total audio bytes: {total_bytes}")
    log.info(f"Audio duration: {total_bytes/8000:.2f}s")

    # Save all received audio as WAV
    if received_chunks:
        all_ulaw = b"".join(c[2] for c in received_chunks)
        pcm_data = ulaw_to_pcm16(all_ulaw)
        wav_path = save_audio_to_wav(pcm_data, f"received_audio_{run_id}.wav")
        log.info(f"All received audio saved to: {wav_path}")

        # Save pre-injection audio
        if received_before_inject:
            pre_ulaw = b"".join(received_before_inject)
            pre_pcm = ulaw_to_pcm16(pre_ulaw)
            save_audio_to_wav(pre_pcm, f"pre_inject_{run_id}.wav")

        # Save post-injection audio
        if received_after_inject:
            post_ulaw = b"".join(received_after_inject)
            post_pcm = ulaw_to_pcm16(post_ulaw)
            save_audio_to_wav(post_pcm, f"post_inject_{run_id}.wav")

    # Timestamps & latency
    log.info("\nTimestamps:")
    for key, ts in timestamps.items():
        if ts:
            log.info(f"  {key}: {datetime.fromtimestamp(ts).strftime('%H:%M:%S.%f')[:-3]}")
        else:
            log.info(f"  {key}: NOT RECORDED")

    log.info("\nLatency measurements:")
    if timestamps["call_initiated"] and timestamps["ws_connected"]:
        log.info(f"  Call → WS connected: {(timestamps['ws_connected'] - timestamps['call_initiated']):.2f}s")
    if timestamps["ws_connected"] and timestamps["first_audio_received"]:
        log.info(f"  WS connected → first audio: {(timestamps['first_audio_received'] - timestamps['ws_connected'])*1000:.0f}ms")
    if timestamps["audio_injection_started"] and timestamps["audio_injection_complete"]:
        log.info(f"  Audio injection time: {(timestamps['audio_injection_complete'] - timestamps['audio_injection_started'])*1000:.0f}ms")
    if timestamps["stream_started"] and timestamps["call_ended"]:
        log.info(f"  Stream duration: {(timestamps['call_ended'] - timestamps['stream_started']):.2f}s")

    # Success criteria
    log.info("\n" + "=" * 60)
    log.info("SUCCESS CRITERIA:")
    ws_ok = timestamps["ws_connected"] is not None
    audio_ok = len(received_chunks) > 0
    inject_ok = timestamps["audio_injection_complete"] is not None
    saved_ok = total_chunks > 0

    log.info(f"  WebSocket connection established: {'✅' if ws_ok else '❌'}")
    log.info(f"  Receiving audio data:             {'✅' if audio_ok else '❌'} ({total_chunks} chunks)")
    log.info(f"  Audio injected back:              {'✅' if inject_ok else '❌'}")
    log.info(f"  Audio saved to file:              {'✅' if saved_ok else '❌'}")
    log.info("=" * 60)

    # Save summary JSON
    summary = {
        "run_id": run_id,
        "timestamps": {k: v for k, v in timestamps.items()},
        "audio": {
            "total_chunks": total_chunks,
            "total_bytes": total_bytes,
            "duration_s": total_bytes / 8000 if total_bytes else 0,
            "chunks_before_inject": len(received_before_inject),
            "chunks_after_inject": len(received_after_inject),
        },
        "success": {
            "ws_connected": ws_ok,
            "audio_received": audio_ok,
            "audio_injected": inject_ok,
            "audio_saved": saved_ok,
        },
    }
    summary_path = RESULTS_DIR / f"summary_{run_id}.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    log.info(f"\nSummary saved to: {summary_path}")
    log.info(f"Full log: {log_file}")

# ─── Cleanup ──────────────────────────────────────────────────────────────────
def cleanup(signum=None, frame=None):
    log.info("Cleaning up...")
    test_complete.set()
    if tunnel_process:
        tunnel_process.terminate()
        log.info("Tunnel terminated")
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

if __name__ == "__main__":
    try:
        run_test()
    except Exception as e:
        log.error(f"Test failed: {e}", exc_info=True)
    finally:
        cleanup()
