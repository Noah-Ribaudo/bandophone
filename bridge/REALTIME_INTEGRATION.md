# Realtime API + Phone Integration

## Architecture

```
Phone Call ←→ TinyALSA ←→ PhoneAudioStream ←→ RealtimeBridge ←→ OpenAI Realtime API
```

**Audio Flow:**
1. **User speaks** → tinycap (48kHz stereo) → convert to 24kHz mono → Realtime API
2. **AI responds** → Realtime API (24kHz mono) → convert to stereo → tinyplay (16kHz magic) → phone call

## Integration Code

```python
# In realtime_bridge.py, add:

from phone_audio_stream import PhoneAudioStream

class RealtimeBridge:
    def __init__(self, config, phone_stream: PhoneAudioStream = None):
        self.phone_stream = phone_stream or PhoneAudioStream()
        # ... existing init ...
    
    async def handle_event(self, data: dict):
        event_type = data.get("type", "")
        
        # When AI sends audio, inject to phone
        if event_type == "response.audio.delta":
            audio_b64 = data.get("delta", "")
            if audio_b64:
                audio_data = base64.b64decode(audio_b64)
                # Inject to phone (24kHz mono)
                await self.phone_stream.inject_audio(audio_data)
        
        # ... rest of existing handlers ...
    
    async def run_with_phone(self):
        """Run with phone audio streaming."""
        await self.phone_stream.start()
        
        # Start capture → Realtime API streaming
        async def capture_task():
            async for chunk in self.phone_stream.capture_stream():
                await self.send_audio(chunk)
        
        capture = asyncio.create_task(capture_task())
        
        try:
            await self.run()  # Existing WebSocket loop
        finally:
            capture.cancel()
            await self.phone_stream.stop()
```

## Key Insight: The 16kHz Magic

The Pixel 7 Pro's audio routing is weird:
- OpenAI outputs 24kHz mono PCM
- We convert to stereo (duplicate channels)
- We tell tinyplay the rate is **16kHz** but feed it **24kHz content**
- Result: Plays at correct speed!

This was discovered empirically on 2026-01-26.

## Quick Test

```bash
# Make sure call is active, then:
cd ~/projects/bandophone/bridge
python3 phone_audio_stream.py
```

## Latency Considerations

1. **Capture chunk size**: 100ms chunks = good balance of latency vs efficiency
2. **Injection buffering**: Accumulate ~100ms before injecting to avoid constant ADB overhead
3. **ADB overhead**: Each push/play is ~50-100ms; could optimize with continuous streaming
4. **Realtime API**: ~200-500ms response latency

**Total expected latency**: ~500-800ms (compared to batch pipeline ~3-5s)

## Future Optimizations

1. **Continuous tinyplay**: Keep tinyplay running, pipe audio via ADB shell
2. **Shared memory**: Use Android's AudioTrack from an app instead of CLI tools
3. **USB audio**: Direct audio routing over USB (complex but lowest latency)
