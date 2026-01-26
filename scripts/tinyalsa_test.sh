#!/bin/bash
# Bandophone TinyALSA Test Script
# Quick test of audio injection and capture on Pixel 7 Pro

set -e

DEVICE_IP="${DEVICE_IP:-192.168.4.167:5555}"
OPENAI_KEY=$(cat ~/projects/bandophone/bridge/bandophone.json | grep openai_api_key | cut -d'"' -f4)

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== Bandophone TinyALSA Test ===${NC}"

# Check ADB connection
echo "Checking ADB connection..."
adb devices | grep -q "$DEVICE_IP" || { echo "Device not connected. Run: adb connect $DEVICE_IP"; exit 1; }
echo "✓ Device connected"

# Check if call is active
CALL_STATE=$(adb shell dumpsys telecom | grep "state=ACTIVE" | head -1)
if [ -z "$CALL_STATE" ]; then
    echo -e "${YELLOW}No active call. Start a call first.${NC}"
    exit 1
fi
echo "✓ Call active"

# Setup mixer for capture
echo "Setting up mixer..."
adb shell su -c "/data/local/tmp/tinymix -D 0 set 152 DL"  # Enable capture (downlink)
adb shell su -c "/data/local/tmp/tinymix -D 0 set 167 1"   # Mute mic
echo "✓ Mixer configured"

# Generate test prompt
echo "Generating test prompt..."
PROMPT_TEXT="${1:-Hello! This is a test of the Bandophone system. Please say something.}"
curl -s https://api.openai.com/v1/audio/speech \
    -H "Authorization: Bearer $OPENAI_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"tts-1\", \"input\": \"$PROMPT_TEXT\", \"voice\": \"onyx\", \"response_format\": \"pcm\"}" \
    -o /tmp/prompt.pcm

# Convert to stereo
ffmpeg -y -f s16le -ar 24000 -ac 1 -i /tmp/prompt.pcm -ac 2 -f s16le /tmp/prompt_stereo.pcm 2>/dev/null
adb push /tmp/prompt_stereo.pcm /sdcard/prompt.pcm
echo "✓ Prompt ready"

# Play prompt
echo -e "${GREEN}Playing prompt...${NC}"
adb shell su -c "/data/local/tmp/tinyplay /sdcard/prompt.pcm -D 0 -d 19 -c 2 -r 16000 -b 16"

# Capture response
echo -e "${GREEN}Capturing response for 5 seconds...${NC}"
(adb shell su -c "/data/local/tmp/tinycap /sdcard/response.pcm -D 0 -d 20 -c 2 -r 48000 -b 16" &)
sleep 5
adb shell su -c "pkill -9 tinycap"

# Pull and convert
adb pull /sdcard/response.pcm /tmp/response.pcm
ffmpeg -y -f s16le -ar 48000 -ac 2 -i /tmp/response.pcm -ar 16000 -ac 1 /tmp/response.wav 2>/dev/null
echo "✓ Captured"

# Transcribe
echo "Transcribing..."
TRANSCRIPT=$(curl -s https://api.openai.com/v1/audio/transcriptions \
    -H "Authorization: Bearer $OPENAI_KEY" \
    -F "file=@/tmp/response.wav" \
    -F "model=whisper-1" \
    -F "prompt=Phone conversation" | jq -r '.text')

echo -e "${GREEN}Transcript: ${NC}$TRANSCRIPT"

# Get AI response
echo "Getting AI response..."
AI_RESPONSE=$(curl -s https://api.openai.com/v1/chat/completions \
    -H "Authorization: Bearer $OPENAI_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"gpt-4o-mini\", \"messages\": [{\"role\": \"system\", \"content\": \"Brief friendly phone assistant.\"}, {\"role\": \"user\", \"content\": \"$TRANSCRIPT\"}]}" | jq -r '.choices[0].message.content')

echo -e "${GREEN}AI Response: ${NC}$AI_RESPONSE"

# TTS and play response
curl -s https://api.openai.com/v1/audio/speech \
    -H "Authorization: Bearer $OPENAI_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"tts-1\", \"input\": \"$AI_RESPONSE\", \"voice\": \"onyx\", \"response_format\": \"pcm\"}" \
    -o /tmp/ai_response.pcm

ffmpeg -y -f s16le -ar 24000 -ac 1 -i /tmp/ai_response.pcm -ac 2 -f s16le /tmp/ai_response_stereo.pcm 2>/dev/null
adb push /tmp/ai_response_stereo.pcm /sdcard/response_out.pcm

echo -e "${GREEN}Playing AI response...${NC}"
adb shell su -c "/data/local/tmp/tinyplay /sdcard/response_out.pcm -D 0 -d 19 -c 2 -r 16000 -b 16"

echo -e "${GREEN}=== Test Complete ===${NC}"
