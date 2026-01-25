#!/bin/bash
#
# Bandophone: Capture call audio and transcribe with Whisper
# Usage: ./capture-and-transcribe.sh [duration_seconds] [mode]
# Modes: UL_DL (both), DL (caller only), UL (mic only)
#

set -e

DURATION=${1:-5}
MODE=${2:-UL_DL}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="/Users/noahribaudo/projects/bandophone/test_captures"
REMOTE_DIR="/data/local/tmp"
TINYCAP="$REMOTE_DIR/tinycap"
TINYMIX="$REMOTE_DIR/tinymix"

# Correct sample rate for Pixel 7 Pro VoLTE
SAMPLE_RATE=48000

mkdir -p "$OUTPUT_DIR"

echo "═══════════════════════════════════════════════════════"
echo "  Bandophone Capture & Transcribe"
echo "═══════════════════════════════════════════════════════"
echo "Duration: ${DURATION}s | Mode: $MODE | Rate: ${SAMPLE_RATE}Hz"
echo ""

# Check device
DEVICE=$(adb devices | grep -v "List" | grep "device$" | head -1 | cut -f1)
if [ -z "$DEVICE" ]; then
    echo "❌ No device connected"
    exit 1
fi

# Check if call is active
DSP_STATE=$(adb shell "su -c 'export LD_LIBRARY_PATH=$REMOTE_DIR && $TINYMIX get \"Audio DSP State\"'" 2>/dev/null | tr -d '\r')
if [[ ! "$DSP_STATE" =~ "Telephony" ]]; then
    echo "⚠️  No active call detected (Audio DSP State: $DSP_STATE)"
    echo "   Make a call first, or this will fail!"
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
fi

echo "📞 Call active. Setting capture mode to $MODE..."

# Set mixer control
adb shell "su -c 'export LD_LIBRARY_PATH=$REMOTE_DIR && $TINYMIX set \"Incall Capture Stream0\" \"$MODE\"'" 2>/dev/null

# Capture
REMOTE_FILE="$REMOTE_DIR/capture_${TIMESTAMP}.raw"
echo "🎙️  Capturing ${DURATION}s of audio..."

adb shell "su -c 'export LD_LIBRARY_PATH=$REMOTE_DIR && timeout $((DURATION + 1)) $TINYCAP $REMOTE_FILE -D 0 -d 20 -c 1 -r $SAMPLE_RATE -b 16'" 2>&1 || true

# Check file size
SIZE=$(adb shell "su -c 'stat -c%s $REMOTE_FILE 2>/dev/null || echo 0'" | tr -d '\r')
echo "📊 Captured $SIZE bytes"

if [ "$SIZE" -lt 1000 ]; then
    echo "❌ Capture too small. Was a call active?"
    exit 1
fi

# Pull and convert
LOCAL_RAW="$OUTPUT_DIR/capture_${TIMESTAMP}.raw"
LOCAL_WAV="$OUTPUT_DIR/capture_${TIMESTAMP}.wav"

echo "📥 Pulling audio..."
adb pull "$REMOTE_FILE" "$LOCAL_RAW" 2>/dev/null

# Skip tinycap's broken header (44 bytes) and convert to proper WAV
tail -c +45 "$LOCAL_RAW" > "${LOCAL_RAW}.pcm"
ffmpeg -y -f s16le -ar $SAMPLE_RATE -ac 1 -i "${LOCAL_RAW}.pcm" "$LOCAL_WAV" 2>/dev/null
rm "${LOCAL_RAW}.pcm" "$LOCAL_RAW"

# Get duration
ACTUAL_DURATION=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$LOCAL_WAV" 2>/dev/null)
echo "✅ Saved: $LOCAL_WAV (${ACTUAL_DURATION}s)"

# Transcribe
echo ""
echo "🧠 Transcribing with Whisper..."
TRANSCRIPT_DIR="$OUTPUT_DIR/transcripts"
mkdir -p "$TRANSCRIPT_DIR"

whisper "$LOCAL_WAV" --model tiny --output_format txt --output_dir "$TRANSCRIPT_DIR" --language en 2>/dev/null

TRANSCRIPT=$(cat "$TRANSCRIPT_DIR/capture_${TIMESTAMP}.txt" 2>/dev/null || echo "(no speech detected)")

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📝 Transcript:"
echo "$TRANSCRIPT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Files:"
echo "  Audio: $LOCAL_WAV"
echo "  Text:  $TRANSCRIPT_DIR/capture_${TIMESTAMP}.txt"

# Cleanup remote
adb shell "su -c 'rm -f $REMOTE_FILE'" 2>/dev/null
