#!/usr/bin/env python3
"""
Simple Bandophone telephony test — just verifies Twilio can call the Pixel.
Uses <Say> TwiML (no Media Streams needed) to speak a test phrase.
"""

import subprocess
import sys
import time
import threading
import json
import logging

from flask import Flask, Response, request

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger("simple-test")

TWILIO_FROM = "+14842960680"
TWILIO_TO = "+17736984245"  # Pixel 7 Pro

app = Flask(__name__)

call_events = []

@app.route("/voice", methods=["POST"])
def voice():
    log.info(f"📞 Voice webhook! CallSid={request.form.get('CallSid')}")
    call_events.append(("voice_webhook", time.time()))
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Hello. This is a Bandophone test call. The telephony path is working. Goodbye.</Say>
    <Pause length="2"/>
</Response>"""
    return Response(twiml, mimetype="text/xml")

@app.route("/status", methods=["POST"])
def status():
    status = request.form.get("CallStatus", "unknown")
    call_sid = request.form.get("CallSid", "unknown")
    duration = request.form.get("CallDuration", "?")
    log.info(f"📊 Status: {status} (SID: {call_sid}, duration: {duration}s)")
    call_events.append((status, time.time()))
    return "", 200

@app.route("/health", methods=["GET"])
def health():
    return json.dumps({"status": "ok", "events": call_events}), 200


def get_twilio_creds():
    def kc(s):
        r = subprocess.run(
            ["security", "find-generic-password", "-a", "bando", "-s", s, "-w"],
            capture_output=True, text=True
        )
        if r.returncode != 0:
            raise RuntimeError(f"Missing {s} in Keychain")
        return r.stdout.strip()
    return kc("twilio-account-sid"), kc("twilio-auth-token")


def auto_answer_adb(delay=5):
    """Wait then auto-answer the call via ADB."""
    time.sleep(delay)
    log.info("📱 Auto-answering via ADB...")
    # Try multiple methods
    r = subprocess.run(
        ["adb", "shell", "input", "keyevent", "CALL"],
        capture_output=True, text=True, timeout=5
    )
    log.info(f"ADB answer result: {r.returncode} {r.stdout} {r.stderr}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--tunnel-url", required=True, help="Public HTTPS URL")
    parser.add_argument("--auto-answer", action="store_true", default=True)
    parser.add_argument("--no-auto-answer", dest="auto_answer", action="store_false")
    args = parser.parse_args()

    tunnel_url = args.tunnel_url.rstrip("/")

    # Start Flask
    flask_thread = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5050, debug=False, use_reloader=False), daemon=True)
    flask_thread.start()
    log.info("Flask started on :5050")
    time.sleep(1)

    # Verify tunnel is reachable
    log.info(f"Verifying tunnel: {tunnel_url}/health")
    r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", f"{tunnel_url}/health"], capture_output=True, text=True, timeout=10)
    if r.stdout.strip() != "200":
        log.error(f"❌ Tunnel not reachable (HTTP {r.stdout.strip()})")
        sys.exit(1)
    log.info("✅ Tunnel reachable")

    # Get creds
    sid, token = get_twilio_creds()

    # Start auto-answer thread
    if args.auto_answer:
        threading.Thread(target=auto_answer_adb, args=(6,), daemon=True).start()

    # Make the call
    from twilio.rest import Client
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
        )
        log.info(f"✅ Call created: {call.sid} (status: {call.status})")
    except Exception as e:
        log.error(f"❌ Call failed: {e}")
        sys.exit(1)

    # Monitor call for up to 45 seconds
    log.info("Monitoring call (up to 45s)...")
    start = time.time()
    final_status = None
    while time.time() - start < 45:
        time.sleep(3)
        try:
            call = client.calls(call.sid).fetch()
            log.info(f"  Call status: {call.status}")
            if call.status in ("completed", "failed", "busy", "no-answer", "canceled"):
                final_status = call.status
                break
        except Exception as e:
            log.warning(f"Status check error: {e}")

    if not final_status:
        final_status = "timeout"
        try:
            client.calls(call.sid).update(status="completed")
        except:
            pass

    # Report
    log.info("\n" + "=" * 50)
    log.info("📊 TEST RESULTS")
    log.info("=" * 50)
    log.info(f"Call SID:    {call.sid}")
    log.info(f"Final:       {final_status}")
    log.info(f"Events:      {call_events}")

    if final_status == "completed":
        log.info("✅ PASS — Twilio → Pixel telephony path works!")
    else:
        log.info(f"⚠️  Call ended with: {final_status}")

    log.info("=" * 50)


if __name__ == "__main__":
    main()
