# TinyALSA Integration Guide

## Overview

The `tinyalsa_audio.py` module provides production-ready audio routing for Bandophone phone calls. This guide shows how to integrate it with `realtime_bridge.py`.

## Quick Start

```python
from tinyalsa_audio import TinyALSAAudioBridge

async def main():
    # Create bridge
    bridge = TinyALSAAudioBridge()
    
    # Wait for active call
    await bridge.wait_for_call()
    
    # Setup call audio (mutes mic, enables capture)
    await bridge.setup_call(mute_mic=True)
    
    # Now ready for injection and capture
    # ...
    
    # Cleanup when call ends
    await bridge.teardown_call()
```

## Integration with RealtimeBridge

### Current Architecture

`realtime_bridge.py` currently has:
- `PhoneCapture` class - handles tinycap via ADB
- Manual resampling in `RealtimeBridge`
- File-based capture polling

### Recommended Changes

#### 1. Replace PhoneCapture with TinyALSAAudioBridge

```python
# OLD
from realtime_bridge import PhoneCapture
capture = PhoneCapture(config)

# NEW
from tinyalsa_audio import TinyALSAAudioBridge
audio_bridge = TinyALSAAudioBridge()
```

#### 2. Update Audio Injection

```python
class RealtimeBridge:
    def __init__(self, config, audio_bridge: TinyALSAAudioBridge = None):
        self.config = config
        self.audio_bridge = audio_bridge
        # ...
    
    async def _process_event(self, event_type: str, data: dict):
        # ...
        if event_type == "response.audio.delta":
            audio_b64 = data.get("delta", "")
            if audio_b64:
                audio_data = base64.b64decode(audio_b64)
                
                # NEW: Direct injection via TinyALSA
                if self.audio_bridge:
                    await self.audio_bridge.inject(audio_data)
                
                # Keep WebSocket server for Android app too
                if self.audio_server and self.audio_server.has_clients:
                    # Resample for app display
                    resampled = self.resampler.upsample(
                        audio_data, 24000, 48000
                    )
                    asyncio.create_task(self.audio_server.send_audio(resampled))
```

#### 3. Update Audio Capture

```python
async def capture_and_send_to_realtime():
    """Capture audio and send to OpenAI Realtime API."""
    
    def on_capture_chunk(audio_16k_mono: bytes):
        """Called with each captured chunk (already in Whisper format)."""
        # Resample 16kHz → 24kHz for Realtime API
        audio_24k = resampler.upsample(audio_16k_mono, 16000, 24000)
        
        # Send to OpenAI
        asyncio.create_task(realtime_bridge.send_audio(audio_24k))
    
    # Start capture loop
    await audio_bridge.start_capture_loop(on_capture_chunk)
```

#### 4. Main Loop Integration

```python
async def main():
    config = BandophoneConfig.load("bandophone.json")
    
    # Create TinyALSA bridge
    audio_bridge = TinyALSAAudioBridge()
    
    # Wait for call
    log.info("Waiting for phone call...")
    await audio_bridge.wait_for_call()
    
    # Setup call audio
    await audio_bridge.setup_call(mute_mic=True)
    
    # Create Realtime API bridge
    realtime_bridge = RealtimeBridge(config, audio_bridge=audio_bridge)
    await realtime_bridge.connect()
    await realtime_bridge.start()
    
    # Run capture and response handling in parallel
    await asyncio.gather(
        realtime_bridge.handle_responses(),
        audio_bridge.start_capture_loop(
            lambda chunk: asyncio.create_task(
                process_capture(chunk, realtime_bridge)
            )
        )
    )
    
    # Cleanup
    await audio_bridge.teardown_call()
    await realtime_bridge.stop()

async def process_capture(chunk_16k_mono: bytes, bridge: RealtimeBridge):
    """Process captured audio chunk."""
    # Resample 16kHz → 24kHz for OpenAI
    chunk_24k = AudioConverter.resample_simple(chunk_16k_mono, 16000, 24000)
    await bridge.send_audio(chunk_24k)
```

## Audio Flow

### Injection (AI → Phone)
```
OpenAI Realtime API (24kHz mono PCM16)
    ↓
TinyALSAInjector.inject_audio()
    ↓
AudioConverter.mono_to_stereo() (24kHz stereo)
    ↓
ADB push to device
    ↓
tinyplay -d 19 -r 16000 (rate trick!)
    ↓
Phone call audio output
```

### Capture (Phone → AI)
```
Phone call audio input
    ↓
tinycap -d 20 -r 48000 -c 2
    ↓
TinyALSACapture.read_capture_chunk()
    ↓
AudioConverter.stereo_to_mono() (48kHz mono)
    ↓
AudioConverter.resample_simple() (16kHz mono)
    ↓
Whisper transcription OR
    ↓
Resample to 24kHz → OpenAI Realtime API
```

## Testing

Run the test suite to verify everything works:

```bash
cd ~/projects/bandophone/bridge
python3 test_tinyalsa.py
```

Tests will:
1. Check mixer control functions
2. Verify audio conversion
3. Test injection (requires active call)
4. Test capture (requires active call)
5. Test full bridge setup/teardown

## Best Practices

### Error Handling

Always wrap audio operations in try/except:

```python
try:
    success = await audio_bridge.inject(audio_data)
    if not success:
        log.warning("Injection failed, buffering for retry")
except Exception as e:
    log.error(f"Injection error: {e}")
```

### Call State Management

Check if call is still active periodically:

```python
if not audio_bridge.mixer.check_call_active():
    log.info("Call ended")
    await cleanup()
    break
```

### Cleanup

Always teardown properly:

```python
try:
    # ... main loop ...
finally:
    await audio_bridge.teardown_call()
```

## Configuration

All TinyALSA parameters are in `TinyALSAConfig`:

```python
class TinyALSAConfig:
    INJECTION_DEVICE = 19
    CAPTURE_DEVICE = 20
    INJECTION_RATE_TOLD = 16000  # Rate trick
    CAPTURE_RATE = 48000
    MIXER_CAPTURE_ENABLE = 152
    MIXER_MIC_MUTE = 167
    # ...
```

These are verified for **Pixel 7 Pro**. Other devices may need different values.

## Troubleshooting

### No audio injected
- Check call is active: `mixer.check_call_active()`
- Verify stereo conversion is applied
- Check ADB connection
- Verify TinyALSA binaries on device

### Poor capture quality
- Ensure capture stream is enabled (tinymix 152=DL)
- Verify 48kHz → 16kHz resampling
- Check for mono conversion
- Test with different mixer settings

### Call detection fails
- Verify TinyALSA binaries in `/data/local/tmp/`
- Check root access via ADB
- Test manually: `adb shell su -c "tinymix get 'Audio DSP State'"`

## Advanced Usage

### Streaming Injection

For real-time streaming, accumulate small chunks:

```python
injector = TinyALSAInjector()

# Stream small chunks as they arrive
async for audio_chunk in realtime_audio_stream:
    await injector.inject_audio_stream(audio_chunk)
```

### Custom Capture Callback

Process captured audio in real-time:

```python
def on_capture(audio_16k_mono: bytes):
    # Send to Whisper for transcription
    transcript = whisper.transcribe(audio_16k_mono)
    log.info(f"User said: {transcript}")
    
    # Or send to Realtime API
    audio_24k = resample(audio_16k_mono, 16000, 24000)
    asyncio.create_task(realtime_bridge.send_audio(audio_24k))

await audio_bridge.start_capture_loop(on_capture)
```

## Next Steps

1. Integrate into main `realtime_bridge.py`
2. Test full duplex (simultaneous injection + capture)
3. Add Whisper transcription with context prompts
4. Implement streaming injection for lower latency
5. Add automatic call detection and setup
6. Test on other Android devices (may need config changes)
