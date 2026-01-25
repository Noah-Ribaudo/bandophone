#!/usr/bin/env python3
"""
Bandophone CLI

Command-line interface for configuration and control.

Usage:
    bandophone config --voice shimmer --personality receptionist
    bandophone status
    bandophone call --wait
    bandophone test-capture
"""

import argparse
import subprocess
import sys
import os
import json
from pathlib import Path

from config import BandophoneConfig, VOICES, PERSONALITIES


def cmd_config(args):
    """Configure Bandophone settings."""
    config_path = args.config or "bandophone.json"
    
    # Load existing or create new
    config = BandophoneConfig.load(config_path)
    
    # Update values
    if args.voice:
        if args.voice not in VOICES:
            print(f"Unknown voice: {args.voice}")
            print(f"Available: {', '.join(VOICES.keys())}")
            return 1
        config.voice = args.voice
        print(f"Voice set to: {args.voice}")
    
    if args.personality:
        if args.personality not in PERSONALITIES:
            print(f"Unknown personality: {args.personality}")
            print(f"Available: {', '.join(PERSONALITIES.keys())}")
            return 1
        config.personality = args.personality
        config.voice = PERSONALITIES[args.personality]["voice"]
        print(f"Personality set to: {args.personality} (voice: {config.voice})")
    
    if args.instructions:
        config.custom_instructions = args.instructions
        print(f"Custom instructions set")
    
    if args.api_key:
        config.openai_api_key = args.api_key
        print("API key set")
    
    if args.show:
        print(json.dumps({
            "personality": config.personality,
            "voice": config.voice,
            "custom_instructions": config.custom_instructions[:50] + "..." if config.custom_instructions and len(config.custom_instructions) > 50 else config.custom_instructions,
            "api_key": "***" if config.openai_api_key else "(not set)",
            "capture_device": config.capture_device,
            "playback_device": config.playback_device,
        }, indent=2))
        return 0
    
    # Save
    config.save(config_path)
    print(f"Config saved to {config_path}")
    return 0


def cmd_status(args):
    """Check system status."""
    print("🦝 Bandophone Status\n")
    
    # Check ADB
    result = subprocess.run("adb devices", shell=True, capture_output=True, text=True)
    devices = [l for l in result.stdout.strip().split('\n')[1:] if l.strip()]
    
    if devices:
        print(f"📱 Android devices: {len(devices)}")
        for d in devices:
            print(f"   {d}")
    else:
        print("❌ No Android devices connected")
    
    # Check call state
    result = subprocess.run(
        'adb shell "su -c \'export LD_LIBRARY_PATH=/data/local/tmp && /data/local/tmp/tinymix get \"Audio DSP State\"\'"',
        shell=True, capture_output=True, text=True
    )
    
    if "Telephony" in result.stdout:
        print("📞 Call state: ACTIVE")
    elif "error" in result.stdout.lower() or result.returncode != 0:
        print("⚠️  Call state: Cannot determine (is device rooted?)")
    else:
        print("📞 Call state: Idle")
    
    # Check tinycap
    result = subprocess.run(
        'adb shell "su -c \'test -f /data/local/tmp/tinycap && echo ok\'"',
        shell=True, capture_output=True, text=True
    )
    
    if "ok" in result.stdout:
        print("✅ tinycap: Installed")
    else:
        print("❌ tinycap: Not found (run setup first)")
    
    # Check config
    config_path = args.config or "bandophone.json"
    if os.path.exists(config_path):
        config = BandophoneConfig.load(config_path)
        print(f"\n⚙️  Config: {config_path}")
        print(f"   Voice: {config.voice}")
        print(f"   Personality: {config.personality}")
        print(f"   API Key: {'✅ Set' if config.openai_api_key else '❌ Not set'}")
    else:
        print(f"\n⚠️  No config file (run 'bandophone config' to create)")
    
    return 0


def cmd_test_capture(args):
    """Test audio capture."""
    duration = args.duration or 5
    output = args.output or "/tmp/bandophone_test.wav"
    
    print(f"Testing capture for {duration}s...")
    
    # Check for active call
    result = subprocess.run(
        'adb shell "su -c \'export LD_LIBRARY_PATH=/data/local/tmp && /data/local/tmp/tinymix get \"Audio DSP State\"\'"',
        shell=True, capture_output=True, text=True
    )
    
    if "Telephony" not in result.stdout:
        print("⚠️  No active call - capture may fail")
        if not args.force:
            print("   Use --force to capture anyway, or make a call first")
            return 1
    
    # Set capture mode
    subprocess.run(
        'adb shell "su -c \'export LD_LIBRARY_PATH=/data/local/tmp && /data/local/tmp/tinymix set \"Incall Capture Stream0\" \"UL_DL\"\'"',
        shell=True, capture_output=True
    )
    
    # Capture
    raw_file = "/data/local/tmp/test_capture.raw"
    subprocess.run(
        f'adb shell "su -c \'export LD_LIBRARY_PATH=/data/local/tmp && timeout {duration+1} /data/local/tmp/tinycap {raw_file} -D 0 -d 20 -c 1 -r 48000 -b 16\'"',
        shell=True
    )
    
    # Pull and convert
    subprocess.run(f"adb pull {raw_file} /tmp/capture.raw", shell=True, capture_output=True)
    
    # Convert to WAV (skip broken header)
    subprocess.run(
        f"tail -c +45 /tmp/capture.raw | ffmpeg -y -f s16le -ar 48000 -ac 1 -i - {output}",
        shell=True, capture_output=True
    )
    
    if os.path.exists(output):
        size = os.path.getsize(output)
        duration_actual = size / (48000 * 2)  # 16-bit mono
        print(f"✅ Captured {duration_actual:.1f}s to {output}")
        
        if args.transcribe:
            print("Transcribing...")
            result = subprocess.run(
                f"whisper {output} --model tiny --output_format txt --output_dir /tmp --language en",
                shell=True, capture_output=True, text=True
            )
            
            txt_file = output.replace('.wav', '.txt')
            if os.path.exists(f"/tmp/{Path(output).stem}.txt"):
                with open(f"/tmp/{Path(output).stem}.txt") as f:
                    print(f"\n📝 Transcript:\n{f.read()}")
    else:
        print("❌ Capture failed")
        return 1
    
    return 0


def cmd_voices(args):
    """List available voices."""
    print("Available voices:\n")
    for voice, desc in VOICES.items():
        marker = "  " if not args.all else ("▶ " if voice == "alloy" else "  ")
        print(f"{marker}{voice}: {desc}")
    
    print("\nUse with: bandophone config --voice <name>")
    return 0


def cmd_personalities(args):
    """List available personalities."""
    print("Available personalities:\n")
    for name, config in PERSONALITIES.items():
        print(f"  {name}: {config['name']}")
        print(f"    Voice: {config['voice']}")
        print(f"    {config['instructions'][:60]}...")
        print()
    
    print("Use with: bandophone config --personality <name>")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Bandophone - Give your AI a real phone",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  bandophone status                    Check system status
  bandophone config --voice shimmer    Set voice
  bandophone config --personality receptionist
  bandophone voices                    List available voices
  bandophone test-capture              Test audio capture
        """
    )
    
    parser.add_argument("--config", "-c", help="Config file path", default="bandophone.json")
    
    subparsers = parser.add_subparsers(dest="command", help="Command")
    
    # config
    p_config = subparsers.add_parser("config", help="Configure settings")
    p_config.add_argument("--voice", "-v", help="Set voice")
    p_config.add_argument("--personality", "-p", help="Set personality preset")
    p_config.add_argument("--instructions", "-i", help="Set custom instructions")
    p_config.add_argument("--api-key", help="Set OpenAI API key")
    p_config.add_argument("--show", "-s", action="store_true", help="Show current config")
    
    # status
    p_status = subparsers.add_parser("status", help="Check system status")
    
    # test-capture
    p_capture = subparsers.add_parser("test-capture", help="Test audio capture")
    p_capture.add_argument("--duration", "-d", type=int, default=5, help="Capture duration in seconds")
    p_capture.add_argument("--output", "-o", help="Output file path")
    p_capture.add_argument("--transcribe", "-t", action="store_true", help="Transcribe after capture")
    p_capture.add_argument("--force", "-f", action="store_true", help="Capture even without active call")
    
    # voices
    p_voices = subparsers.add_parser("voices", help="List available voices")
    p_voices.add_argument("--all", "-a", action="store_true", help="Show all details")
    
    # personalities
    p_pers = subparsers.add_parser("personalities", help="List available personalities")
    
    args = parser.parse_args()
    
    if args.command == "config":
        return cmd_config(args)
    elif args.command == "status":
        return cmd_status(args)
    elif args.command == "test-capture":
        return cmd_test_capture(args)
    elif args.command == "voices":
        return cmd_voices(args)
    elif args.command == "personalities":
        return cmd_personalities(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
