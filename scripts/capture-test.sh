#!/bin/bash
#
# Bandophone Call Capture Test
# Run this DURING an active phone call
#

set -e

DURATION=${1:-5}
OUTPUT_DIR="/data/local/tmp"
TINYCAP="/data/local/tmp/tinycap"
TINYMIX="/data/local/tmp/tinymix"

echo "═══════════════════════════════════════════════════════"
echo "  Bandophone Call Capture Test"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "⚠️  Make sure you have an ACTIVE CALL before running!"
echo ""

# Check device
DEVICE=$(adb devices | grep -v "List" | grep "device$" | head -1 | cut -f1)
if [ -z "$DEVICE" ]; then
    echo "❌ No device connected"
    exit 1
fi
echo "📱 Device: $DEVICE"

# Verify tools exist
adb shell "su -c 'test -f $TINYCAP'" || {
    echo "❌ tinycap not found at $TINYCAP"
    echo "   Run the build first!"
    exit 1
}

echo ""
echo "📊 Current incall capture state:"
adb shell "su -c 'export LD_LIBRARY_PATH=/data/local/tmp && $TINYMIX get \"Incall Capture Stream0\"'"

echo ""
echo "🔧 Setting up capture..."

# Try each capture mode
for MODE in "UL_DL" "DL" "UL"; do
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Testing mode: $MODE (${DURATION}s)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Set the mixer control
    adb shell "su -c 'export LD_LIBRARY_PATH=/data/local/tmp && $TINYMIX set \"Incall Capture Stream0\" \"$MODE\"'" 2>&1
    
    # Verify it was set
    CURRENT=$(adb shell "su -c 'export LD_LIBRARY_PATH=/data/local/tmp && $TINYMIX get \"Incall Capture Stream0\"'" 2>&1)
    echo "Current setting: $CURRENT"
    
    FILENAME="call_${MODE}_16k.wav"
    
    echo "Recording to $OUTPUT_DIR/$FILENAME..."
    
    # Try 16000 Hz first (VoLTE standard)
    adb shell "su -c 'export LD_LIBRARY_PATH=/data/local/tmp && $TINYCAP $OUTPUT_DIR/$FILENAME -D 0 -d 20 -c 1 -r 16000 -b 16 -T $DURATION'" 2>&1 || {
        echo "⚠️  16kHz failed, trying 48kHz..."
        FILENAME="call_${MODE}_48k.wav"
        adb shell "su -c 'export LD_LIBRARY_PATH=/data/local/tmp && $TINYCAP $OUTPUT_DIR/$FILENAME -D 0 -d 20 -c 1 -r 48000 -b 16 -T $DURATION'" 2>&1 || {
            echo "❌ Capture failed for $MODE"
            continue
        }
    }
    
    # Check file size
    SIZE=$(adb shell "su -c 'stat -c%s $OUTPUT_DIR/$FILENAME 2>/dev/null || echo 0'" | tr -d '\r')
    echo "File size: $SIZE bytes"
    
    if [ "$SIZE" -gt 1000 ]; then
        echo "✅ Got data! Pulling to local machine..."
        adb pull "$OUTPUT_DIR/$FILENAME" "./$FILENAME"
    else
        echo "⚠️  File too small - may be silence or device not active during call"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎧 Test complete! Check the .wav files for audio."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "If files are silent, try:"
echo "  - Make sure you're on an active voice call (not WhatsApp/etc)"
echo "  - Check Audio DSP State: tinymix get 'Audio DSP State'"
echo "  - Check if device 20 shows activity during call"
