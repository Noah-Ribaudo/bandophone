#!/usr/bin/env python3
"""
Generate Test Audio Files for Bandophone Testing

Creates mulaw/PCM audio files compatible with Twilio Media Streams (8kHz mulaw).
Uses macOS `say` command + ffmpeg for TTS, or ElevenLabs API if available.

Usage:
    python generate_test_audio.py                    # Generate all default phrases
    python generate_test_audio.py --phrase "Hello"   # Custom phrase
    python generate_test_audio.py --elevenlabs       # Use ElevenLabs TTS
    python generate_test_audio.py --list             # List generated files
"""

import argparse
import audioop
import os
import subprocess
import struct
import sys
import wave
from pathlib import Path

AUDIO_DIR = Path(__file__).parent / "audio"

DEFAULT_PHRASES = [
    ("greeting", "Hello, how are you doing today?"),
    ("weather", "What's the weather like today?"),
    ("time", "What time is it right now?"),
    ("joke", "Tell me a joke."),
    ("goodbye", "Okay, goodbye!"),
    ("complex", "Can you check my calendar for tomorrow and tell me what I have scheduled?"),
    ("silence", None),  # Generate silence for baseline testing
]


def generate_with_say(text: str, output_path: Path, voice: str = "Samantha"):
    """Generate audio using macOS `say` command + ffmpeg conversion."""
    # say outputs AIFF, convert to 8kHz mono WAV via ffmpeg
    temp_aiff = "/tmp/bandophone_tts_temp.aiff"
    temp_wav = str(output_path.with_suffix('.wav'))
    
    # Generate with say
    subprocess.run(
        ["say", "-v", voice, "-o", temp_aiff, text],
        check=True, capture_output=True
    )
    
    # Convert to 8kHz mono 16-bit PCM WAV
    subprocess.run(
        ["ffmpeg", "-y", "-i", temp_aiff, "-ar", "8000", "-ac", "1",
         "-acodec", "pcm_s16le", temp_wav],
        check=True, capture_output=True
    )
    
    # Also create mulaw version
    mulaw_path = output_path.with_suffix('.ulaw')
    with wave.open(temp_wav, 'rb') as wf:
        pcm_data = wf.readframes(wf.getnframes())
    
    mulaw_data = audioop.lin2ulaw(pcm_data, 2)
    mulaw_path.write_bytes(mulaw_data)
    
    # Clean up temp
    os.unlink(temp_aiff)
    
    duration = len(pcm_data) / (8000 * 2)
    print(f"  ✅ {output_path.name} ({duration:.1f}s) — WAV + mulaw")
    return temp_wav, str(mulaw_path)


def generate_with_elevenlabs(text: str, output_path: Path, voice_id: str = "21m00Tcm4TlvDq8ikWAM"):
    """Generate audio using ElevenLabs API."""
    try:
        api_key = subprocess.run(
            ["security", "find-generic-password", "-a", "bando", "-s", "elevenlabs-api-key", "-w"],
            capture_output=True, text=True, check=True
        ).stdout.strip()
    except subprocess.CalledProcessError:
        print("  ❌ ElevenLabs API key not found in Keychain", file=sys.stderr)
        return None, None
    
    import json
    import urllib.request
    
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "Content-Type": "application/json",
        "xi-api-key": api_key,
    }
    payload = json.dumps({
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
        }
    }).encode()
    
    req = urllib.request.Request(url, data=payload, headers=headers)
    
    temp_mp3 = "/tmp/bandophone_elevenlabs.mp3"
    with urllib.request.urlopen(req) as response:
        with open(temp_mp3, 'wb') as f:
            f.write(response.read())
    
    # Convert to 8kHz mono WAV
    wav_path = str(output_path.with_suffix('.wav'))
    subprocess.run(
        ["ffmpeg", "-y", "-i", temp_mp3, "-ar", "8000", "-ac", "1",
         "-acodec", "pcm_s16le", wav_path],
        check=True, capture_output=True
    )
    
    # Create mulaw version
    mulaw_path = output_path.with_suffix('.ulaw')
    with wave.open(wav_path, 'rb') as wf:
        pcm_data = wf.readframes(wf.getnframes())
    mulaw_data = audioop.lin2ulaw(pcm_data, 2)
    mulaw_path.write_bytes(mulaw_data)
    
    os.unlink(temp_mp3)
    
    duration = len(pcm_data) / (8000 * 2)
    print(f"  ✅ {output_path.name} ({duration:.1f}s) — WAV + mulaw [ElevenLabs]")
    return wav_path, str(mulaw_path)


def generate_silence(output_path: Path, duration_s: float = 3.0):
    """Generate silence file for baseline testing."""
    num_samples = int(8000 * duration_s)
    pcm_data = struct.pack(f'<{num_samples}h', *([0] * num_samples))
    
    wav_path = str(output_path.with_suffix('.wav'))
    with wave.open(wav_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(pcm_data)
    
    mulaw_path = output_path.with_suffix('.ulaw')
    mulaw_data = audioop.lin2ulaw(pcm_data, 2)
    mulaw_path.write_bytes(mulaw_data)
    
    print(f"  ✅ {output_path.name} ({duration_s}s silence) — WAV + mulaw")
    return wav_path, str(mulaw_path)


def generate_tone(output_path: Path, freq: float = 440.0, duration_s: float = 1.0):
    """Generate a sine tone for testing audio path."""
    import math
    num_samples = int(8000 * duration_s)
    samples = []
    for i in range(num_samples):
        t = i / 8000.0
        sample = int(16000 * math.sin(2 * math.pi * freq * t))
        samples.append(sample)
    
    pcm_data = struct.pack(f'<{num_samples}h', *samples)
    
    wav_path = str(output_path.with_suffix('.wav'))
    with wave.open(wav_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(pcm_data)
    
    mulaw_path = output_path.with_suffix('.ulaw')
    mulaw_data = audioop.lin2ulaw(pcm_data, 2)
    mulaw_path.write_bytes(mulaw_data)
    
    print(f"  ✅ {output_path.name} ({duration_s}s, {freq}Hz tone) — WAV + mulaw")
    return wav_path, str(mulaw_path)


def list_audio_files():
    """List all generated audio files."""
    if not AUDIO_DIR.exists():
        print("No audio files generated yet. Run without --list first.")
        return
    
    print(f"\nAudio files in {AUDIO_DIR}/:")
    for f in sorted(AUDIO_DIR.iterdir()):
        size = f.stat().st_size
        if f.suffix == '.wav':
            with wave.open(str(f), 'rb') as wf:
                duration = wf.getnframes() / wf.getframerate()
            print(f"  {f.name:40s} {size:>8d} bytes  {duration:.1f}s")
        else:
            print(f"  {f.name:40s} {size:>8d} bytes")


def main():
    parser = argparse.ArgumentParser(description="Generate test audio for Bandophone")
    parser.add_argument("--phrase", help="Custom phrase to generate")
    parser.add_argument("--name", default="custom", help="Name for custom phrase file")
    parser.add_argument("--elevenlabs", action="store_true", help="Use ElevenLabs TTS")
    parser.add_argument("--voice", default="Samantha", help="macOS say voice (default: Samantha)")
    parser.add_argument("--list", action="store_true", help="List generated files")
    parser.add_argument("--tone", action="store_true", help="Also generate test tone")
    args = parser.parse_args()
    
    if args.list:
        list_audio_files()
        return
    
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    
    generate_fn = generate_with_elevenlabs if args.elevenlabs else generate_with_say
    
    if args.phrase:
        # Single custom phrase
        name = args.name.replace(" ", "_").lower()
        output = AUDIO_DIR / f"{name}"
        print(f"\nGenerating: \"{args.phrase}\"")
        if args.elevenlabs:
            generate_with_elevenlabs(args.phrase, output)
        else:
            generate_with_say(args.phrase, output, voice=args.voice)
    else:
        # Generate all default phrases
        print(f"\nGenerating default test phrases to {AUDIO_DIR}/:")
        for name, text in DEFAULT_PHRASES:
            output = AUDIO_DIR / name
            if text is None:
                generate_silence(output)
            else:
                generate_fn(text, output) if not args.elevenlabs else generate_with_elevenlabs(text, output)
        
        # Always generate a test tone
        generate_tone(AUDIO_DIR / "tone_440hz", freq=440.0, duration_s=1.0)
    
    if args.tone:
        generate_tone(AUDIO_DIR / "tone_440hz", freq=440.0, duration_s=1.0)
        generate_tone(AUDIO_DIR / "tone_1khz", freq=1000.0, duration_s=1.0)
    
    print(f"\n✅ Audio files ready in {AUDIO_DIR}/")
    print("Use with test_call.py --inject audio/<name>.wav")


if __name__ == "__main__":
    main()
