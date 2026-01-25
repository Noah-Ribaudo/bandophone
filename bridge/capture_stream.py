#!/usr/bin/env python3
"""
Bandophone: Real-time call audio capture and streaming.

Captures audio from an active call and streams it for processing.
Can output to:
- WebSocket (for OpenAI Realtime API)
- File (for testing)
- stdout (for piping)

Usage:
    python capture_stream.py --output ws://localhost:8080
    python capture_stream.py --output file:call_capture.raw
    python capture_stream.py --output stdout | whisper -
"""

import subprocess
import argparse
import sys
import time
import signal
import os

# Constants for Pixel 7 Pro
SAMPLE_RATE = 48000
CHANNELS = 1
BIT_DEPTH = 16
DEVICE_CARD = 0
DEVICE_NUM = 20  # audio_incall_cap_0

TINYCAP = "/data/local/tmp/tinycap"
TINYMIX = "/data/local/tmp/tinymix"
LD_LIB = "/data/local/tmp"


def run_adb(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run an ADB shell command."""
    full_cmd = f'adb shell "su -c \'{cmd}\'"'
    return subprocess.run(full_cmd, shell=True, capture_output=True, text=True, check=check)


def check_call_active() -> bool:
    """Check if a call is active (Audio DSP State = Telephony)."""
    result = run_adb(f'export LD_LIBRARY_PATH={LD_LIB} && {TINYMIX} get "Audio DSP State"', check=False)
    return "Telephony" in result.stdout


def setup_capture():
    """Configure mixer for UL_DL capture."""
    run_adb(f'export LD_LIBRARY_PATH={LD_LIB} && {TINYMIX} set "Incall Capture Stream0" "UL_DL"')
    print("Configured capture for UL_DL mode", file=sys.stderr)


def stream_capture(output_type: str, output_target: str):
    """Stream captured audio to the specified output."""
    
    if not check_call_active():
        print("⚠️  No active call detected. Waiting...", file=sys.stderr)
        while not check_call_active():
            time.sleep(1)
        print("📞 Call detected!", file=sys.stderr)
    
    setup_capture()
    
    # Create a FIFO on the device for streaming
    fifo_path = "/data/local/tmp/capture_fifo"
    run_adb(f"rm -f {fifo_path} && mkfifo {fifo_path}", check=False)
    
    # Start tinycap writing to FIFO in background
    capture_cmd = f"""
        export LD_LIBRARY_PATH={LD_LIB}
        {TINYCAP} {fifo_path} -D {DEVICE_CARD} -d {DEVICE_NUM} -c {CHANNELS} -r {SAMPLE_RATE} -b {BIT_DEPTH} &
        CAPTURE_PID=$!
        echo $CAPTURE_PID
    """
    
    # Start capture process
    print(f"Starting capture at {SAMPLE_RATE}Hz...", file=sys.stderr)
    
    if output_type == "file":
        # Direct capture to file
        result = run_adb(
            f'export LD_LIBRARY_PATH={LD_LIB} && timeout 30 {TINYCAP} /data/local/tmp/stream_test.raw '
            f'-D {DEVICE_CARD} -d {DEVICE_NUM} -c {CHANNELS} -r {SAMPLE_RATE} -b {BIT_DEPTH}',
            check=False
        )
        print(f"Capture complete. Pulling file...", file=sys.stderr)
        subprocess.run(f"adb pull /data/local/tmp/stream_test.raw {output_target}", shell=True)
        
    elif output_type == "stdout":
        # Stream to stdout via adb exec-out
        # Note: This requires the capture to be running and readable
        print("Streaming to stdout (Ctrl+C to stop)...", file=sys.stderr)
        
        # Start tinycap and cat the output
        process = subprocess.Popen(
            f'adb shell "su -c \'export LD_LIBRARY_PATH={LD_LIB} && '
            f'{TINYCAP} /dev/stdout -D {DEVICE_CARD} -d {DEVICE_NUM} '
            f'-c {CHANNELS} -r {SAMPLE_RATE} -b {BIT_DEPTH}\'"',
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        
        try:
            # Skip the WAV header (44 bytes)
            process.stdout.read(44)
            
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
        except KeyboardInterrupt:
            process.terminate()
            print("\nStopped.", file=sys.stderr)
    
    elif output_type == "ws":
        print(f"WebSocket streaming to {output_target} not yet implemented", file=sys.stderr)
        print("TODO: Implement OpenAI Realtime API connection", file=sys.stderr)
    
    else:
        print(f"Unknown output type: {output_type}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Stream call audio capture")
    parser.add_argument(
        "--output", "-o",
        default="stdout",
        help="Output target: stdout, file:path.raw, or ws://url"
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for call to become active"
    )
    
    args = parser.parse_args()
    
    # Parse output type
    if args.output == "stdout":
        output_type, output_target = "stdout", None
    elif args.output.startswith("file:"):
        output_type, output_target = "file", args.output[5:]
    elif args.output.startswith("ws://") or args.output.startswith("wss://"):
        output_type, output_target = "ws", args.output
    else:
        print(f"Invalid output format: {args.output}", file=sys.stderr)
        sys.exit(1)
    
    # Check ADB connection
    result = subprocess.run("adb devices", shell=True, capture_output=True, text=True)
    if "device" not in result.stdout or result.stdout.count("device") < 2:
        print("❌ No Android device connected via ADB", file=sys.stderr)
        sys.exit(1)
    
    try:
        stream_capture(output_type, output_target)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)


if __name__ == "__main__":
    main()
