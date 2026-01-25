#!/bin/bash
#
# Test audio injection via the Bandophone Android app
# Requires: app running on phone, ADB connected
#

set -e

PHONE_PORT=9999
TEST_AUDIO="${1:-/tmp/test_tts.pcm}"

if [ ! -f "$TEST_AUDIO" ]; then
    echo "Creating test audio with macOS TTS..."
    say -o /tmp/test_tts.aiff "Hello, this is a test of Bandophone audio injection. Can you hear me?"
    ffmpeg -y -i /tmp/test_tts.aiff -ar 48000 -ac 1 -f s16le "$TEST_AUDIO" 2>/dev/null
fi

echo "Setting up ADB port forward..."
adb forward tcp:$PHONE_PORT tcp:$PHONE_PORT

echo "Checking if service is responding..."
if ! nc -z localhost $PHONE_PORT 2>/dev/null; then
    echo "❌ Cannot connect to port $PHONE_PORT"
    echo "   Make sure the Bandophone app is running with service started"
    exit 1
fi

echo "Sending test audio ($(du -h "$TEST_AUDIO" | cut -f1))..."
cat "$TEST_AUDIO" | nc localhost $PHONE_PORT

echo "✅ Audio sent! Check if you heard it in the call."
