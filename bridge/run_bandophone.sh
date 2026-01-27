#!/bin/bash
# Bandophone - Launch Script
# Connects to Pixel 7 Pro and runs the realtime bridge

cd "$(dirname "$0")"

# Ensure ADB is connected
ADB_DEVICE="${BANDOPHONE_ADB:-192.168.4.167:5555}"
echo "Connecting to ADB device: $ADB_DEVICE"
adb connect "$ADB_DEVICE" 2>/dev/null

# Load API key from Keychain
export OPENAI_API_KEY=$(security find-generic-password -a "bando" -s "openai-api-key" -w 2>/dev/null)
if [ -z "$OPENAI_API_KEY" ]; then
    echo "ERROR: No OpenAI API key in Keychain"
    exit 1
fi
echo "API key loaded from Keychain"

# Start bridge
python3 realtime_bridge.py --verbose "$@" &
BRIDGE_PID=$!
echo "Bridge started: $BRIDGE_PID"

# Auto-answer loop
while kill -0 $BRIDGE_PID 2>/dev/null; do
    STATE=$(adb -s "$ADB_DEVICE" shell dumpsys telephony.registry 2>/dev/null | grep "mCallState=" | head -1)
    if [[ "$STATE" == *"mCallState=1"* ]]; then
        echo "$(date): RINGING! Answering..."
        adb -s "$ADB_DEVICE" shell input keyevent KEYCODE_CALL
        adb -s "$ADB_DEVICE" shell input keyevent KEYCODE_HEADSETHOOK
        sleep 2
    fi
    sleep 0.3
done
