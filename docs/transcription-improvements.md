# Transcription Improvement Strategies

## Problem
"tacos" → "pumpkins" - significant transcription error

## Potential Causes
1. **Sample rate mismatch** - capturing at 48kHz, Whisper optimized for 16kHz
2. **Stereo vs mono** - Whisper expects mono
3. **Phone call audio artifacts** - compression, narrow bandwidth
4. **No context/prompt** - Whisper has no guidance

## Strategies to Test

### 1. Pre-process Audio (HIGH PRIORITY)
```bash
# Convert 48kHz stereo → 16kHz mono before transcription
ffmpeg -f s16le -ar 48000 -ac 2 -i capture.pcm \
  -ar 16000 -ac 1 capture_16k_mono.wav
```
Whisper's native format is 16kHz mono - this alone might fix most issues.

### 2. Use Whisper Prompt Parameter
```python
# Add context to guide transcription
response = client.audio.transcriptions.create(
    model="whisper-1",
    file=audio_file,
    prompt="This is a phone conversation about food preferences. Common foods mentioned: tacos, pizza, burgers, salads."
)
```

### 3. Capture at 16kHz Instead of 48kHz
```bash
# Try capturing at native Whisper rate
tinycap /sdcard/capture.pcm -D 0 -d 20 -c 1 -r 16000 -b 16
```
May reduce quality but better match for transcription.

### 4. Use Realtime API's Built-in Transcription
The Realtime API can transcribe incoming audio natively - no separate Whisper call needed. This is likely more optimized for streaming audio.

### 5. Audio Enhancement
```bash
# Noise reduction + normalization
ffmpeg -i capture.wav -af "highpass=f=200,lowpass=f=3000,loudnorm" enhanced.wav
```
Phone calls are 300-3400Hz bandwidth - filter to that range.

### 6. Post-Processing with GPT
```python
# Fix obvious transcription errors
corrected = gpt_fix(f"Fix any obvious transcription errors in this phone call transcript. Context: discussing favorite foods. Transcript: {raw_transcript}")
```

### 7. Try Different Capture Settings
- Device 21 or 22 instead of 20
- UL_DL instead of DL (might have different quality)
- Different mixer settings

## Test Priority
1. **16kHz mono conversion** - easiest, likely biggest impact
2. **Whisper prompt** - easy to add
3. **Realtime API native transcription** - best for production
4. **Audio enhancement** - if still having issues

## Metrics to Track
- Word Error Rate (WER)
- Common substitution patterns
- Audio levels (are we clipping?)

---

## Implementation Complete (2026-01-26)

### New TinyALSA Audio Module

Created `bridge/tinyalsa_audio.py` - production-ready module for phone call audio routing.

**Features:**
- **Audio Injection:** Converts OpenAI Realtime API audio (24kHz mono PCM16) → stereo → device 19 with rate trick
- **Audio Capture:** Captures from device 20 (48kHz stereo) → converts to 16kHz mono for Whisper
- **Mixer Control:** Manages tinymix settings (capture enable, mic mute)
- **Error Handling:** Comprehensive error handling and logging throughout
- **Async Architecture:** Fully async/await compatible with realtime_bridge.py

**Classes:**
- `TinyALSAConfig` - Configuration constants for verified working setup
- `AudioConverter` - Audio format conversion (mono↔stereo, resampling)
- `TinyALSAMixer` - Mixer control via ADB (capture enable, mic mute, call detection)
- `TinyALSAInjector` - Audio injection into calls
- `TinyALSACapture` - Audio capture from calls with format conversion
- `TinyALSAAudioBridge` - High-level API combining all functionality

**Audio Pipeline:**
```
OpenAI Realtime (24kHz mono) 
  → TinyALSAInjector.inject_audio()
  → mono_to_stereo() 
  → push to device
  → tinyplay device 19 (told 16kHz, actually 24kHz stereo)
  → Phone call output ✅

Phone call input
  → tinycap device 20 (48kHz stereo)
  → TinyALSACapture.read_capture_chunk()
  → stereo_to_mono()
  → resample 48kHz → 16kHz
  → Whisper-ready audio ✅
```

**Testing:**
- Created `bridge/test_tinyalsa.py` - comprehensive test suite
- Tests: mixer control, audio conversion, injection, capture, full bridge
- Run with: `python3 bridge/test_tinyalsa.py`

**Next Steps for Integration:**
1. Update `realtime_bridge.py` to use `TinyALSAAudioBridge` instead of current PhoneCapture
2. Replace resampling logic with AudioConverter methods
3. Add streaming injection support for real-time audio
4. Test full duplex: simultaneous capture + injection during live call
5. Add Whisper prompt with conversation context for better transcription

**Key Insights:**
- 16kHz mono is Whisper's native format - conversion is critical for accuracy
- Stereo requirement for injection is hardware-specific (Pixel 7 Pro)
- Rate "trick" (tell device 16kHz, feed 24kHz) is reproducible magic
- Mixer settings reset between calls - must re-enable capture each time
