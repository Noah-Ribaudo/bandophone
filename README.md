# Bandophone 🦝📞

**Route Android phone call audio to AI in real-time.**

Bandophone captures cellular call audio from a rooted Android device and streams it bidirectionally to an AI backend (OpenAI Realtime, etc.), enabling AI-powered phone conversations over real phone numbers.

> ⚠️ **Early Development** — This project is exploring uncharted territory. Contributions and findings welcome.

## Why?

Existing AI voice solutions require:
- SIP/VoIP infrastructure
- Porting your phone number
- Dedicated hardware

Bandophone takes a different approach: use the phone you already have. Your AI assistant makes and receives calls using your actual cellular connection.

## How It Works

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Cellular  │────▶│  Bandophone  │────▶│  AI Backend │
│    Call     │◀────│   (Phone)   │◀────│  (OpenAI)   │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                           ▼
                    WebSocket API
                    (control/monitor)
```

1. **Audio Capture**: Hooks into Android's audio subsystem to capture call audio (uplink + downlink)
2. **Format Conversion**: Resamples telephony audio (8-16kHz) to AI-expected format (24kHz)
3. **Bidirectional Streaming**: Sends caller audio to AI, plays AI responses back into the call
4. **Control API**: WebSocket interface for initiating calls, monitoring state, injecting audio

## Requirements

- **Rooted Android phone** (Magisk recommended)
- **SELinux permissive** or appropriate policies
- **USB debugging** or Termux SSH access
- Tested on: Pixel 7 Pro (Tensor G2) — other devices may need adaptation

## Project Status

### Phase 1: Discovery (Current)
- [ ] Map PCM devices for call audio on Pixel 7 Pro
- [ ] Identify required mixer controls
- [ ] Verify audio capture during active call
- [ ] Document sample rates and formats

### Phase 2: Proof of Concept
- [ ] Capture call audio to file
- [ ] Play audio file into active call
- [ ] Basic streaming to external endpoint

### Phase 3: AI Integration
- [ ] OpenAI Realtime API integration
- [ ] Real-time bidirectional streaming
- [ ] Latency optimization

### Phase 4: Productization
- [ ] Android app with background service
- [ ] WebSocket control API
- [ ] Documentation for other devices

## Architecture

```
voxbridge/
├── docs/
│   ├── AUDIO_ROUTING.md      # Device-specific audio findings
│   ├── MIXER_CONTROLS.md     # ALSA mixer documentation
│   └── SUPPORTED_DEVICES.md  # Tested devices and quirks
├── scripts/
│   ├── diagnose.sh           # Audio subsystem diagnostics
│   ├── capture-test.sh       # Test audio capture
│   └── playback-test.sh      # Test audio injection
├── android/                  # Android app (later)
├── bridge/                   # Core streaming logic
└── examples/
    └── openai-realtime/      # Example AI integration
```

## Quick Start

*Coming soon — we're still in the discovery phase.*

```bash
# Clone the repo
git clone https://github.com/yourusername/voxbridge.git
cd voxbridge

# Run diagnostics on your connected Android device
./scripts/diagnose.sh
```

## Research Notes

### Known Challenges

1. **Mixer Controls**: Android audio routing requires specific ALSA mixer settings that vary by device
2. **Audio Format**: Telephony uses 8-16kHz; AI APIs expect 24kHz — resampling needed
3. **Separate Streams**: Uplink (your mic) and downlink (caller) may be on different PCM devices
4. **HAL Contention**: Android's Audio HAL may lock devices during calls

### Alternative Approaches Considered

| Approach | Pros | Cons |
|----------|------|------|
| Raw PCM capture | Direct, low latency | Device-specific, needs root |
| AudioRecord API | Standard Android API | May not expose call audio |
| Bluetooth HFP | Standard protocol | Added latency, complexity |
| SIP/VoIP | Battle-tested | Requires number porting |

We chose raw PCM capture for lowest latency and maximum control, accepting the device-specific complexity.

## Contributing

This is uncharted territory. If you have:
- A rooted Android device and want to help test
- Knowledge of Android audio internals
- Experience with real-time audio streaming

Please open an issue or PR! Device-specific findings are especially valuable.

## License

MIT

## Acknowledgments

- Built for the [Clawdbot](https://github.com/clawdbot/clawdbot) community
- Inspired by the dream of AI assistants that can actually call people

---

*"The best interface is no interface." — Golden Krishna*

*Sometimes the best interface is just a phone call.*
