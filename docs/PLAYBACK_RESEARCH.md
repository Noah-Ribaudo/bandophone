# Playback (Audio Injection) Research

**Status**: ❌ Not Working Yet — Needs Android App

## What We Tried

### 1. Direct PCM via tinyplay
```bash
tinyplay test.pcm -D 0 -d 18 -c 1 -r 48000 -b 16
# Result: "Played 509602 bytes" but audio NOT heard in call
```
The device accepts writes but audio doesn't route to telephony TX.

### 2. Voice Call Mic Source = IN_CALL_MUSIC
```bash
tinymix set "Voice Call Mic Source" "IN_CALL_MUSIC"
# Result: No change - audio still not routed
```

### 3. termux-media-player
```bash
termux-media-player play /storage/emulated/0/test.wav
# Result: Plays through speaker, not routed to call
```

### 4. Incall Playback Stream0
```bash
tinymix set "Incall Playback Stream0" 1
# Result: Enabled but no effect
```

## Why It's Not Working

The audio policy configuration shows:
```xml
<mixPort name="incall playback" role="source"
         flags="AUDIO_OUTPUT_FLAG_INCALL_MUSIC">
    <profile format="AUDIO_FORMAT_PCM_16_BIT"
             samplingRates="48000"
             channelMasks="AUDIO_CHANNEL_OUT_STEREO" />
</mixPort>
<route type="mix" sink="Telephony Tx" sources="incall playback,voice call tx" />
```

The route exists, but Android's Audio HAL (AudioFlinger) needs to be involved. Direct ALSA access bypasses the routing logic.

## Solution: Android App

We need a minimal Android app that:
1. Uses `AudioTrack` with `STREAM_VOICE_CALL` or `USAGE_VOICE_COMMUNICATION`
2. Or uses `AudioTrack.Builder().setUsage(AudioAttributes.USAGE_INCALL_MUSIC)`
3. Accepts audio input via socket/pipe from our capture script
4. Plays it into the call through the proper AudioFlinger route

### Required Permissions
- `android.permission.MODIFY_AUDIO_SETTINGS`
- `android.permission.MODIFY_PHONE_STATE` (system app only?)
- Possibly needs to be a system app or granted via root

### Reference Apps
- ACR (Another Call Recorder) - does call audio injection
- Google Phone app - plays prompts during calls
- Check how "call hold music" apps work

## Alternative Approaches

### A. Bluetooth HFP
Route call audio through Bluetooth, intercept at the HFP layer.
- Pro: Standard protocol, well-documented
- Con: Added latency, complexity

### B. Virtual Audio Device  
Create a virtual audio device that appears as a headset.
- Pro: Clean abstraction
- Con: Kernel module required

### C. Magisk Module
Modify AudioFlinger or Audio HAL to expose direct injection.
- Pro: System-level solution
- Con: Device-specific, fragile

## Next Steps

1. Create minimal Android app with AudioTrack incall playback
2. Test with hardcoded audio file first
3. Add socket interface for real-time streaming
4. Integrate with capture script for full duplex

## Workaround: One-Way AI

Until playback works, we can still do:
- **AI Transcription**: Capture call → Whisper → text summary
- **AI Listening**: Real-time transcription for note-taking
- **Call Recording**: Archive calls with transcripts

Full bidirectional AI conversation requires solving playback.
