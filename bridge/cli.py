#!/usr/bin/env python3
"""
Bandophone CLI

Usage:
    bandophone status
    bandophone config --voice shimmer
    bandophone config --api-key sk-...
    bandophone test-capture
    bandophone run
"""

import argparse
import subprocess
import sys
import os
import json

from config import BandophoneConfig, VOICES


def cmd_status(args):
    """Check system status."""
    print("🦝 Bandophone Status\n")
    
    # Check ADB
    result = subprocess.run("adb devices", shell=True, capture_output=True, text=True)
    devices = [l for l in result.stdout.strip().split('\n')[1:] if l.strip() and 'device' in l]
    
    if devices:
        print(f"📱 Device: Connected")
    else:
        print("❌ Device: Not connected")
    
    # Check call state
    result = subprocess.run(
        'adb shell "su -c \'export LD_LIBRARY_PATH=/data/local/tmp && /data/local/tmp/tinymix get \"Audio DSP State\"\'"',
        shell=True, capture_output=True, text=True
    )
    
    if "Telephony" in result.stdout:
        print("📞 Call: Active")
    else:
        print("📞 Call: Idle")
    
    # Check config
    config = BandophoneConfig.load(args.config)
    print(f"\n⚙️  Voice: {config.voice}")
    print(f"🔑 API Key: {'Set' if config.openai_api_key else 'Not set'}")
    print(f"📝 Transcripts: {config.transcripts_dir}/")
    
    return 0


def cmd_config(args):
    """Configure settings."""
    config = BandophoneConfig.load(args.config)
    
    if args.voice:
        if args.voice not in VOICES:
            print(f"Unknown voice. Options: {', '.join(VOICES.keys())}")
            return 1
        config.voice = args.voice
        print(f"Voice: {args.voice}")
    
    if args.api_key:
        config.openai_api_key = args.api_key
        print("API key set")
    
    if args.instructions:
        config.instructions = args.instructions
        print("Instructions updated")
    
    if args.show:
        print(json.dumps({
            "voice": config.voice,
            "api_key": "***" if config.openai_api_key else "(not set)",
            "instructions": config.instructions[:80] + "..." if len(config.instructions) > 80 else config.instructions,
            "sync_to_clawdbot": config.sync_to_clawdbot,
        }, indent=2))
        return 0
    
    config.save(args.config)
    print(f"Saved to {args.config}")
    return 0


def cmd_test_capture(args):
    """Test audio capture."""
    duration = args.duration
    output = args.output or "/tmp/bandophone_test.wav"
    
    # Check call
    result = subprocess.run(
        'adb shell "su -c \'export LD_LIBRARY_PATH=/data/local/tmp && /data/local/tmp/tinymix get \"Audio DSP State\"\'"',
        shell=True, capture_output=True, text=True
    )
    
    if "Telephony" not in result.stdout and not args.force:
        print("⚠️  No active call. Use --force to capture anyway.")
        return 1
    
    print(f"Capturing {duration}s...")
    
    # Capture
    subprocess.run(
        'adb shell "su -c \'export LD_LIBRARY_PATH=/data/local/tmp && /data/local/tmp/tinymix set \"Incall Capture Stream0\" \"UL_DL\"\'"',
        shell=True, capture_output=True
    )
    
    subprocess.run(
        f'adb shell "su -c \'export LD_LIBRARY_PATH=/data/local/tmp && timeout {duration+1} /data/local/tmp/tinycap /data/local/tmp/test.raw -D 0 -d 20 -c 1 -r 48000 -b 16\'"',
        shell=True
    )
    
    subprocess.run("adb pull /data/local/tmp/test.raw /tmp/test.raw", shell=True, capture_output=True)
    subprocess.run(f"tail -c +45 /tmp/test.raw | ffmpeg -y -f s16le -ar 48000 -ac 1 -i - {output}", shell=True, capture_output=True)
    
    if os.path.exists(output):
        size = os.path.getsize(output)
        print(f"✅ Captured to {output} ({size} bytes)")
        
        if args.transcribe:
            print("Transcribing...")
            subprocess.run(f"whisper {output} --model tiny --output_format txt --output_dir /tmp --language en", shell=True)
    else:
        print("❌ Capture failed")
        return 1
    
    return 0


def cmd_voices(args):
    """List voices."""
    print("Available voices:\n")
    for voice, desc in VOICES.items():
        print(f"  {voice}: {desc}")
    return 0


def cmd_run(args):
    """Run the realtime bridge."""
    print("Starting Bandophone bridge...")
    print("(Use Ctrl+C to stop)\n")
    
    cmd = ["python3", "realtime_bridge.py"]
    if args.verbose:
        cmd.append("--verbose")
    if args.config:
        cmd.extend(["--config", args.config])
    
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    os.execvp("python3", cmd)


def main():
    parser = argparse.ArgumentParser(description="Bandophone - Voice channel for Clawdbot")
    parser.add_argument("--config", "-c", default="bandophone.json", help="Config file")
    
    subs = parser.add_subparsers(dest="command")
    
    # status
    subs.add_parser("status", help="Check status")
    
    # config
    p = subs.add_parser("config", help="Configure")
    p.add_argument("--voice", "-v", help="Set voice")
    p.add_argument("--api-key", help="Set OpenAI API key")
    p.add_argument("--instructions", "-i", help="Set custom instructions")
    p.add_argument("--show", "-s", action="store_true", help="Show config")
    
    # test-capture
    p = subs.add_parser("test-capture", help="Test capture")
    p.add_argument("--duration", "-d", type=int, default=5)
    p.add_argument("--output", "-o")
    p.add_argument("--transcribe", "-t", action="store_true")
    p.add_argument("--force", "-f", action="store_true")
    
    # voices
    subs.add_parser("voices", help="List voices")
    
    # run
    p = subs.add_parser("run", help="Run the bridge")
    p.add_argument("--verbose", action="store_true")
    
    args = parser.parse_args()
    
    if args.command == "status":
        return cmd_status(args)
    elif args.command == "config":
        return cmd_config(args)
    elif args.command == "test-capture":
        return cmd_test_capture(args)
    elif args.command == "voices":
        return cmd_voices(args)
    elif args.command == "run":
        return cmd_run(args)
    else:
        parser.print_help()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
