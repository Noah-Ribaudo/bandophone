#!/bin/bash
cd "$(dirname "$0")"

# Start bridge
python3 realtime_bridge.py --verbose &
BRIDGE_PID=$!
echo "Bridge started: $BRIDGE_PID"

# Auto-answer loop
while kill -0 $BRIDGE_PID 2>/dev/null; do
    STATE=$(adb shell dumpsys telephony.registry 2>/dev/null | grep "mCallState=" | head -1)
    if [[ "$STATE" == *"mCallState=1"* ]]; then
        echo "$(date): RINGING! Answering..."
        adb shell input keyevent KEYCODE_CALL
        adb shell input keyevent KEYCODE_HEADSETHOOK
        sleep 2
    fi
    sleep 0.3
done
