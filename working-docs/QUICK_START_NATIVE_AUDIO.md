# Quick Start: Native Audio Integration

## Prerequisites

1. **Java 17** installed
2. **Android device** (Pixel 7 Pro recommended) or emulator
3. **OpenAI API key** from https://platform.openai.com/api-keys

## Build & Install

```bash
# Navigate to project
cd ~/projects/bandophone/android

# Set Java home (macOS)
export JAVA_HOME=$(/usr/libexec/java_home -v 17)

# Build
./gradlew assembleDebug

# Install on device
adb install app/build/outputs/apk/debug/app-debug.apk
```

## Configuration

1. **Open BandoPhone app**
2. **Tap ⚙️ Settings** in top-right
3. **Enter OpenAI API key**
   - Get from: https://platform.openai.com/api-keys
   - Format: `sk-...`
4. **Choose voice** (default: Alloy)
5. **Edit instructions** (optional)
6. **Tap "Save Settings"**

## Set as Default Phone App

**Required for native audio to work!**

1. Open **Android Settings**
2. Go to **Apps**
3. Tap **Default apps**
4. Tap **Phone app**
5. Select **Bandophone**

## Test

1. **Make a test call** to another phone
2. **Wait for connection** (~2 seconds)
3. **Speak to the AI**: "Hello, can you hear me?"
4. **Listen for response**
5. **Try interrupting** the AI mid-sentence

## Troubleshooting

### No response during call

**Check logcat:**
```bash
adb logcat | grep -E "BandoInCall|RealtimeAudio|CallAudio"
```

**Look for:**
- ✅ "BandoInCallService created"
- ✅ "Call became active"
- ✅ "WebSocket connected"
- ❌ "No API key configured"
- ❌ "WebSocket error"

### API key error

**Verify:**
1. API key is valid and starts with `sk-`
2. OpenAI account has credits
3. API key has Realtime API access

**Fix:**
1. Go to Settings
2. Re-enter API key
3. Save

### Audio not working

**Check permissions:**
```bash
adb shell dumpsys package com.bandophone | grep permission
```

**Should see:**
- ✅ android.permission.RECORD_AUDIO: granted=true
- ✅ android.permission.MODIFY_AUDIO_SETTINGS: granted=true

**If not granted:**
1. Open app
2. Grant permissions when prompted
3. Or: Settings → Apps → Bandophone → Permissions

### Not set as default phone app

**Symptoms:**
- BandoInCallService doesn't launch
- No logs during calls

**Fix:**
- Follow "Set as Default Phone App" steps above

## Logs & Debugging

### View all relevant logs
```bash
adb logcat -c  # Clear logs
# Make a call
adb logcat | grep -E "Bando|Realtime|CallAudio"
```

### Check WebSocket traffic
```bash
adb logcat | grep -i "websocket\|okhttp"
```

### Monitor audio system
```bash
adb logcat | grep -E "AudioTrack|AudioRecord"
```

### Export logs
```bash
adb logcat -d > ~/Desktop/bandophone-logs.txt
```

## Expected Behavior

### Successful Call Flow

```
1. Call starts
   [BandoInCallService] BandoInCallService created
   [BandoInCallService] Call added

2. Call becomes active
   [CallAudioManager] Call became active, starting AI bridge
   [CallAudioManager] Audio routing configured for voice communication

3. Bridge starts
   [RealtimeAudioBridge] Starting RealtimeAudioBridge
   [RealtimeAudioBridge] WebSocket connected
   [RealtimeAudioBridge] Session configured
   [RealtimeAudioBridge] Starting audio capture loop
   [RealtimeAudioBridge] Starting audio playback loop

4. Conversation
   [RealtimeAudioBridge] User speech detected (barge-in)
   [RealtimeAudioBridge] User said: Hello, can you hear me?
   [RealtimeAudioBridge] AI response started
   [RealtimeAudioBridge] AI finished speaking

5. Call ends
   [CallAudioManager] Call ended, stopping AI bridge
   [RealtimeAudioBridge] Stopping RealtimeAudioBridge
   [CallAudioManager] Audio routing reset to normal
```

## Performance Expectations

- **Connection time:** 1-2 seconds after call connects
- **Response latency:** 300-650ms (comparable to web app)
- **Audio quality:** Clear, telephone-grade
- **Interruption delay:** ~200-300ms (server VAD detection)

## Common Issues

### "No API key configured"
**Cause:** API key not saved or corrupted  
**Fix:** Re-enter in Settings

### "WebSocket error: 401"
**Cause:** Invalid API key  
**Fix:** Verify key is correct, has credits

### "WebSocket error: Connection timeout"
**Cause:** Network issue  
**Fix:** Check internet connection, try wifi vs cellular

### "AudioRecord failed to initialize"
**Cause:** Permission denied or audio busy  
**Fix:** 
- Grant RECORD_AUDIO permission
- Close other apps using microphone
- Restart device

### AI doesn't stop when interrupted
**Cause:** Server VAD not detecting speech  
**Fix:**
- Speak louder/clearer
- Check microphone not muted
- Verify VOICE_COMMUNICATION audio routing

## Feature Testing

### ✅ Basic Conversation
"Hello" → AI responds with greeting

### ✅ Multi-turn Dialog
Ask a question → AI answers → Ask follow-up → AI continues conversation

### ✅ Interruption/Barging
Let AI start speaking → Interrupt mid-sentence → AI should stop

### ✅ Natural Turn-taking
Speak → Wait for response → AI speaks → Silence → You can speak again

### ✅ Different Voices
Try each voice in Settings, verify they sound different

### ✅ Custom Instructions
Set "Always respond in pirate speak" → Test call → Verify AI follows instructions

## Advanced Testing

### Network Reliability
1. Start call on WiFi
2. During conversation, toggle airplane mode briefly
3. Verify reconnection

### Call Interruptions
1. During AI speech, put call on hold
2. Resume
3. Verify bridge recovers

### Battery Impact
1. Make 5-minute call with AI
2. Check battery stats
3. Should be comparable to normal voice call

## Success Indicators

You know it's working when:

1. ✅ Settings save and reload
2. ✅ Logs show service launching during calls
3. ✅ You hear AI voice through phone speaker/earpiece
4. ✅ AI responds to your speech
5. ✅ You can interrupt AI naturally
6. ✅ Call quality is good
7. ✅ No crashes or errors

## Getting Help

If issues persist:

1. **Collect logs:**
   ```bash
   adb logcat -d > bandophone-debug.log
   ```

2. **Check files:**
   - Integration summary: `INTEGRATION_SUMMARY.md`
   - Verification checklist: `VERIFICATION_CHECKLIST.md`
   - Architecture: `docs/NATIVE_AUDIO_ARCHITECTURE.md`

3. **Review code:**
   - InCall service: `app/src/main/java/com/bando/phone/audio/CallAudioManager.kt`
   - Bridge: `app/src/main/java/com/bando/phone/audio/RealtimeAudioBridge.kt`

## What's Next?

After successful testing:

1. **Optimize** - Tune audio buffers, reduce latency
2. **Enhance** - Add status notifications, better error handling
3. **Polish** - Improve UI, add usage stats
4. **Deploy** - Build release APK, distribute

---

**Ready to test?** Start with the "Build & Install" section above! 🚀
