# Bandophone 🦝📞

**Give your AI assistant a real phone.**

Got a spare rootable Android and a spare phone line? Bandophone lets your AI assistant make and receive actual phone calls — dial real numbers, talk to real people, handle real conversations.

No SIP infrastructure. No number porting. No dedicated hardware. Just a phone that your AI can use like a person would.

> ⚠️ **Early Development** — This project is exploring uncharted territory. Contributions and findings welcome.

> 🛠️ **Built by a UX designer and an AI** — This is a best-effort project by [Noah](https://github.com/noahribaudo) (UX designer, not a systems programmer) and [Bando](https://github.com/clawdbot/clawdbot) (an AI assistant). We're learning as we go. **Do not assume this is secure.** Don't use it for anything sensitive. We're sharing it because the concept is cool and maybe real developers can help make it better.

## The Vision

Your AI assistant shouldn't be trapped in a chat window. It should be able to:
- 📞 **Call businesses** — Schedule appointments, check hours, make reservations
- 📲 **Receive calls** — Answer your phone when you're busy, take messages
- 🗣️ **Have real conversations** — Using OpenAI Realtime or similar voice AI APIs

All over the regular phone network, with a real phone number that anyone can call.

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
bandophone/
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
git clone https://github.com/yourusername/bandophone.git
cd bandophone

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
- Designed to integrate with [OpenAI Realtime API](https://platform.openai.com/docs/guides/realtime)
- Inspired by the dream of AI assistants that can actually call people

## See Also

- [Clawdbot](https://github.com/clawdbot/clawdbot) — The AI assistant framework this was built for
- [Clawdbot Android Node](https://github.com/clawdbot/clawdbot-android) — Companion app (Bandophone may integrate here later)

---

*"The best interface is no interface." — Golden Krishna*

*Sometimes the best interface is just a phone call.*
