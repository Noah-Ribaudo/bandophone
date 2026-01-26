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
