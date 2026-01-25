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

### Phase 1: Discovery ✅ COMPLETE
- [x] Map PCM devices for call audio on Pixel 7 Pro
- [x] Identify required mixer controls (`Incall Capture Stream0` = UL_DL)
- [x] Verify audio capture during active call
- [x] Document sample rates (48kHz, not 16kHz!)

### Phase 2: Proof of Concept (In Progress)
- [x] Capture call audio to file
- [x] Transcribe with Whisper — working!
- [ ] **Play audio into active call** — blocked, needs Android app
- [ ] Basic streaming to external endpoint

### Phase 3: AI Integration
- [ ] OpenAI Realtime API integration
- [ ] Real-time bidirectional streaming
- [ ] Latency optimization

### Phase 4: Productization
- [ ] Android app with background service
- [ ] WebSocket control API
- [ ] Documentation for other devices

### Current Blockers

**Audio Injection**: Direct ALSA writes (`tinyplay`) bypass Android's AudioFlinger routing. We need an Android app using `AudioTrack` with `USAGE_VOICE_COMMUNICATION` to properly route audio to the telephony transmit path. See [docs/PLAYBACK_RESEARCH.md](docs/PLAYBACK_RESEARCH.md).

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

### Prerequisites
- Rooted Android phone (tested: Pixel 7 Pro)
- ADB connected
- Python 3.10+
- OpenAI API key with Realtime API access

### Installation

```bash
# Clone the repo
git clone https://github.com/Noah-Ribaudo/bandophone.git
cd bandophone

# Install Python dependencies
pip install -r bridge/requirements.txt

# Run diagnostics on your connected Android device
./scripts/diagnose.sh

# Set up tinyalsa on phone (if not done)
# See docs/AUDIO_ROUTING.md for device-specific setup
```

### Configuration

```bash
# CLI method
./bandophone config --personality assistant --voice alloy
./bandophone config --api-key sk-your-key-here

# Or use the Web UI
python bridge/web_ui.py
# Open http://localhost:8080
```

### Available Voices
- **alloy** - Neutral, balanced
- **echo** - Warm, conversational male
- **shimmer** - Clear, expressive female
- **ash** - Soft, thoughtful
- **ballad** - Warm, storytelling
- **coral** - Bright, friendly
- **sage** - Calm, wise
- **verse** - Dynamic, engaging

### Personality Presets
- **assistant** (Bando) - General helpful assistant
- **receptionist** (Alex) - Professional call answering
- **concierge** (Morgan) - Personal concierge services
- **screener** (Sam) - Call screening and filtering

### Usage

```bash
# Check status
./bandophone status

# Test audio capture (during active call)
./bandophone test-capture --transcribe

# Run the full AI bridge (requires OpenAI API key)
python bridge/realtime_bridge.py --verbose
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
