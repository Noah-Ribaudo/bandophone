#!/usr/bin/env python3
"""
Bandophone Test Runner

Orchestrates end-to-end testing of the Bandophone audio bridge:
1. Starts webhook server (Flask + WebSocket)
2. Starts ngrok tunnel for public URL
3. Initiates outbound Twilio call to Pixel 7 Pro
4. Optionally injects test audio via Media Stream
5. Records everything Twilio receives (AI responses)
6. Measures latency and saves results

Usage:
    python test_call.py                          # Full test call
    python test_call.py --dry-run                # Test credentials only
    python test_call.py --inject audio/weather.wav  # Inject specific audio
    python test_call.py --record --duration 30   # Record for 30 seconds
    python test_call.py --no-tunnel              # Skip ngrok (use existing tunnel)
    python test_call.py --tunnel-url https://abc.ngrok.io  # Use existing tunnel
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent))

from twilio_test_server import (
    app, create_session, get_session,
    start_servers, run_websocket_server, MediaStreamSession
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger("test-call")

# ─── Config ──────────────────────────────────────────────────────────────

TWILIO_FROM = "+14842960680"
TWILIO_TO = "+17736984245"  # Pixel 7 Pro

FLASK_PORT = 5000
WS_PORT = 8766

RESULTS_DIR = Path(__file__).parent / "results"


def get_twilio_creds() -> tuple:
    """Get Twilio credentials from macOS Keychain."""
    def keychain_get(service: str) -> str:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", "bando", "-s", service, "-w"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to get {service} from Keychain")
        return result.stdout.strip()
    
    return (
        keychain_get("twilio-account-sid"),
        keychain_get("twilio-auth-token"),
    )


def test_twilio_connection(sid: str, token: str) -> bool:
    """Test Twilio API connection."""
    from twilio.rest import Client
    
    try:
        client = Client(sid, token)
        account = client.api.accounts(sid).fetch()
        log.info(f"✅ Twilio connected: {account.friendly_name} ({account.status})")
        
        # Check verified numbers
        verified = [n.phone_number for n in client.outgoing_caller_ids.list()]
        log.info(f"Verified numbers: {verified}")
        
        if TWILIO_TO not in verified:
            log.warning(f"⚠️  Target {TWILIO_TO} is NOT verified — call will fail on trial account!")
            return False
        
        return True
    except Exception as e:
        log.error(f"❌ Twilio connection failed: {e}")
        return False


# ─── Tunnel Management ──────────────────────────────────────────────────

def start_ngrok(port: int) -> str:
    """Start ngrok tunnel and return public URL."""
    # Check if ngrok is available
    ngrok_path = subprocess.run(["which", "ngrok"], capture_output=True, text=True).stdout.strip()
    
    if not ngrok_path:
        # Try brew install
        log.info("ngrok not found — attempting install via brew...")
        result = subprocess.run(["brew", "install", "ngrok"], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                "ngrok not available. Install with: brew install ngrok\n"
                "Or use --tunnel-url with an existing tunnel.\n"
                "Alternatives: localtunnel (npx localtunnel), bore (cargo install bore-cli)"
            )
        ngrok_path = "ngrok"
    
    # Start ngrok in background
    proc = subprocess.Popen(
        [ngrok_path, "http", str(port), "--log", "stdout", "--log-format", "json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    # Wait for tunnel URL from ngrok API
    time.sleep(3)
    
    try:
        result = subprocess.run(
            ["curl", "-s", "http://localhost:4040/api/tunnels"],
            capture_output=True, text=True, timeout=5
        )
        tunnels = json.loads(result.stdout)
        for tunnel in tunnels.get("tunnels", []):
            if tunnel.get("proto") == "https":
                url = tunnel["public_url"]
                log.info(f"🌐 ngrok tunnel: {url}")
                return url
    except Exception as e:
        log.warning(f"Failed to get ngrok URL from API: {e}")
    
    # Fallback: try reading from stdout
    proc.terminate()
    raise RuntimeError("Failed to get ngrok tunnel URL. Try: ngrok http 5000 manually, then use --tunnel-url")


def start_localtunnel(port: int) -> str:
    """Start localtunnel as ngrok alternative."""
    proc = subprocess.Popen(
        ["npx", "localtunnel", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    
    # Read URL from stdout
    for line in proc.stdout:
        if "your url is:" in line.lower():
            url = line.strip().split()[-1]
            log.info(f"🌐 localtunnel: {url}")
            return url
    
    raise RuntimeError("Failed to start localtunnel")


# ─── Test Execution ─────────────────────────────────────────────────────

async def run_test(
    sid: str,
    token: str,
    tunnel_url: str,
    inject_file: str = None,
    record: bool = True,
    duration: int = 60,
    inject_delay: float = 5.0,
):
    """Execute the full test call."""
    from twilio.rest import Client
    
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RESULTS_DIR / f"run_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Create media stream session
    session = create_session(record=record, output_dir=str(run_dir))
    
    # Event to wait for stream to start
    stream_started = asyncio.Event()
    stream_stopped = asyncio.Event()
    
    def on_start():
        log.info("🎙️  Media Stream active — audio flowing!")
        stream_started.set()
    
    def on_stop():
        log.info("🛑 Media Stream stopped")
        stream_stopped.set()
    
    session.on_stream_start = on_start
    session.on_stream_stop = on_stop
    
    # Start WebSocket server (for Twilio Media Stream)
    ws_server = await asyncio.start_server(lambda r, w: None, "0.0.0.0", WS_PORT)
    
    # Actually use websockets library
    import websockets.server
    ws_task = asyncio.create_task(run_websocket_server(port=WS_PORT))
    
    # Give servers a moment
    await asyncio.sleep(1)
    
    # Initiate call
    client = Client(sid, token)
    
    voice_url = f"{tunnel_url}/voice"
    status_url = f"{tunnel_url}/status"
    
    log.info(f"📞 Calling {TWILIO_TO} from {TWILIO_FROM}...")
    log.info(f"   Voice URL: {voice_url}")
    
    try:
        call = client.calls.create(
            url=voice_url,
            to=TWILIO_TO,
            from_=TWILIO_FROM,
            status_callback=status_url,
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            status_callback_method="POST",
            # Record the call on Twilio's side too
            record=record,
        )
        log.info(f"📞 Call initiated: {call.sid}")
        log.info(f"   Status: {call.status}")
    except Exception as e:
        log.error(f"❌ Failed to initiate call: {e}")
        ws_task.cancel()
        return
    
    # Wait for Media Stream to connect
    log.info("Waiting for Media Stream to connect...")
    try:
        # The media stream connects via a separate websocket, wait up to 30s
        await asyncio.wait_for(stream_started.wait(), timeout=30)
    except asyncio.TimeoutError:
        log.error("❌ Media Stream did not connect within 30s")
        log.info("Check that:")
        log.info("  1. The webhook URL is accessible from Twilio")
        log.info("  2. The call was answered by Bandophone")
        log.info("  3. ngrok/tunnel is running")
        
        # Check call status
        call = client.calls(call.sid).fetch()
        log.info(f"Call status: {call.status}")
        ws_task.cancel()
        return
    
    log.info("✅ Media Stream connected and audio flowing!")
    
    # Inject test audio if requested
    if inject_file:
        log.info(f"Waiting {inject_delay}s before injecting audio...")
        await asyncio.sleep(inject_delay)
        
        log.info(f"📤 Injecting: {inject_file}")
        await session.send_audio_file(inject_file, mark_latency=True)
        log.info("Injection complete, listening for AI response...")
    
    # Wait for duration or until stream ends
    log.info(f"Recording for up to {duration}s...")
    try:
        await asyncio.wait_for(stream_stopped.wait(), timeout=duration)
        log.info("Call ended naturally")
    except asyncio.TimeoutError:
        log.info(f"Duration limit reached ({duration}s)")
    
    # End call
    try:
        client.calls(call.sid).update(status="completed")
        log.info("Call terminated")
    except Exception as e:
        log.warning(f"Failed to terminate call: {e}")
    
    # Wait a moment for final audio
    await asyncio.sleep(2)
    
    # Save results
    stats = session.get_stats()
    results = {
        "timestamp": timestamp,
        "call_sid": call.sid,
        "from": TWILIO_FROM,
        "to": TWILIO_TO,
        "tunnel_url": tunnel_url,
        "inject_file": inject_file,
        "duration_s": stats.get("elapsed_s", 0),
        "received_audio_duration_s": stats.get("received_duration_s", 0),
        "received_chunks": stats.get("received_chunks", 0),
        "sent_chunks": stats.get("sent_chunks", 0),
        "latency_ms": stats.get("latency_ms"),
        "record": record,
    }
    
    results_path = run_dir / "results.json"
    results_path.write_text(json.dumps(results, indent=2))
    
    log.info("\n" + "=" * 60)
    log.info("📊 TEST RESULTS")
    log.info("=" * 60)
    log.info(f"Call SID:          {call.sid}")
    log.info(f"Duration:          {stats.get('elapsed_s', 0):.1f}s")
    log.info(f"Received audio:    {stats.get('received_duration_s', 0):.1f}s")
    log.info(f"Received chunks:   {stats.get('received_chunks', 0)}")
    log.info(f"Sent chunks:       {stats.get('sent_chunks', 0)}")
    if stats.get('latency_ms') is not None:
        log.info(f"Response latency:  {stats['latency_ms']:.0f}ms")
    log.info(f"Results saved to:  {run_dir}/")
    log.info("=" * 60)
    
    ws_task.cancel()


# ─── Main ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Bandophone Test Runner")
    parser.add_argument("--dry-run", action="store_true",
                        help="Test Twilio API connection without making a call")
    parser.add_argument("--inject", type=str,
                        help="Audio file to inject during call (WAV/mulaw)")
    parser.add_argument("--inject-delay", type=float, default=5.0,
                        help="Seconds to wait before injecting audio (default: 5)")
    parser.add_argument("--record", action="store_true", default=True,
                        help="Save received audio to WAV (default: True)")
    parser.add_argument("--no-record", action="store_true",
                        help="Don't save audio recordings")
    parser.add_argument("--duration", type=int, default=60,
                        help="Max call duration in seconds (default: 60)")
    parser.add_argument("--tunnel-url", type=str,
                        help="Use existing tunnel URL instead of starting ngrok")
    parser.add_argument("--no-tunnel", action="store_true",
                        help="Skip tunnel setup (for local testing)")
    parser.add_argument("--flask-port", type=int, default=FLASK_PORT,
                        help=f"Flask HTTP port (default: {FLASK_PORT})")
    parser.add_argument("--ws-port", type=int, default=WS_PORT,
                        help=f"WebSocket port (default: {WS_PORT})")
    parser.add_argument("--to", type=str, default=TWILIO_TO,
                        help=f"Phone number to call (default: {TWILIO_TO})")
    parser.add_argument("--from", dest="from_number", type=str, default=TWILIO_FROM,
                        help=f"Twilio phone number (default: {TWILIO_FROM})")
    args = parser.parse_args()
    
    call_to = args.to
    call_from = args.from_number
    flask_port = args.flask_port
    ws_port = args.ws_port
    
    record = not args.no_record
    
    # Get credentials
    log.info("🔑 Loading Twilio credentials from Keychain...")
    try:
        sid, token = get_twilio_creds()
    except RuntimeError as e:
        log.error(f"❌ {e}")
        log.info("Store credentials: security add-generic-password -a bando -s twilio-account-sid -w '<SID>' -U")
        sys.exit(1)
    
    # Test connection
    if not test_twilio_connection(sid, token):
        if args.dry_run:
            sys.exit(1)
        log.warning("Continuing despite verification warning...")
    
    if args.dry_run:
        log.info("✅ Dry run complete — credentials verified")
        sys.exit(0)
    
    # Start Flask server
    log.info(f"Starting webhook server on port {flask_port}...")
    start_servers(flask_port=flask_port, ws_port=ws_port)
    
    # Setup tunnel
    tunnel_url = None
    ngrok_proc = None
    
    if args.tunnel_url:
        tunnel_url = args.tunnel_url.rstrip("/")
        log.info(f"Using provided tunnel: {tunnel_url}")
    elif not args.no_tunnel:
        try:
            tunnel_url = start_ngrok(flask_port)
        except RuntimeError as e:
            log.error(str(e))
            log.info("\nAlternatives:")
            log.info("  1. Install ngrok: brew install ngrok")
            log.info("  2. Start ngrok manually: ngrok http 5000")
            log.info("  3. Use localtunnel: npx localtunnel --port 5000")
            log.info("  4. Use --tunnel-url with an existing tunnel")
            sys.exit(1)
    else:
        tunnel_url = f"http://localhost:{flask_port}"
        log.warning("No tunnel — Twilio won't be able to reach this server!")
    
    # Resolve inject file path
    inject_file = None
    if args.inject:
        inject_path = Path(args.inject)
        if not inject_path.is_absolute():
            inject_path = Path(__file__).parent / inject_path
        if not inject_path.exists():
            log.error(f"❌ Inject file not found: {inject_path}")
            log.info("Run generate_test_audio.py first to create test audio files")
            sys.exit(1)
        inject_file = str(inject_path)
    
    # Run test
    try:
        asyncio.run(run_test(
            sid=sid,
            token=token,
            tunnel_url=tunnel_url,
            inject_file=inject_file,
            record=record,
            duration=args.duration,
            inject_delay=args.inject_delay,
        ))
    except KeyboardInterrupt:
        log.info("\n🛑 Test interrupted by user")
    finally:
        # Cleanup ngrok if we started it
        if ngrok_proc:
            ngrok_proc.terminate()


if __name__ == "__main__":
    main()
