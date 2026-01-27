# Bandophone 🦝📞

**Give your AI assistant a real phone.**

Got a spare rootable Android and a spare phone line? Bandophone lets your AI assistant make and receive actual phone calls — dial real numbers, talk to real people, handle real conversations.

No SIP infrastructure. No number porting. No dedicated hardware. Just a phone that your AI can use like a person would.

> ⚠️ **Active Development** — Core audio pipeline working. Clawdbot integration in progress.

> 🛠️ **Built by a UX designer and an AI** — This is a best-effort project by [Noah](https://github.com/noahribaudo) (UX designer, not a systems programmer) and [Bando](https://github.com/clawdbot/clawdbot) (an AI assistant). We're learning as we go. **Do not assume this is secure.** Don't use it for anything sensitive. We're sharing it because the concept is cool and maybe real developers can help make it better.

## The Vision

Your AI assistant shouldn't be trapped in a chat window. It should be able to:
- 📞 **Call businesses** — Schedule appointments, check hours, make reservations
- 📲 **Receive calls** — Answer your phone when you're busy, take messages
- 🗣️ **Have real conversations** — Using OpenAI Realtime API with sub-second latency

All over the regular phone network, with a real phone number that anyone can call.

## How It Works

```
┌─────────────┐     ┌─────────────────────────────────────────┐     ┌─────────────┐
│   Cellular  │────▶│            Bandophone App               │────▶│  Clawdbot   │
│    Call     │◀────│  TinyALSA → OpenAI Realtime → TinyALSA  │◀────│  Gateway    │
└─────────────┘     └─────────────────────────────────────────┘     └─────────────┘
                                       │
                                       ▼
                              • Context (memories, calendar)
                              • Transcript logging
                              • Tool execution (lights, reminders)
```

### Audio Pipeline
1. **Capture**: TinyALSA captures far-end audio from device 20 (48kHz stereo)
2. **Convert**: Downsample to 24kHz mono for Realtime API
3. **AI Processing**: Stream to OpenAI with server-side VAD and barging
4. **Playback**: TinyALSA injects AI audio via device 19 into the call

### Clawdbot Integration
1. **Context Injection**: On call start, fetch memories, calendar, user info
2. **Transcript Logging**: Stream conversation to daily memory files
3. **Tool Bridging**: AI can check calendar, create reminders, control lights

## Requirements

- **Rooted Android phone** (Magisk recommended)
- **Pixel 7 Pro** (other devices need adaptation)
- **SELinux permissive** or appropriate policies
- **TinyALSA binaries** on device (`/data/local/tmp/`)
- **OpenAI API key** with Realtime API access
- **Clawdbot Gateway** (optional, for full integration)

## Project Status

### ✅ Phase 1: Audio Discovery — COMPLETE
- [x] Map PCM devices for call audio on Pixel 7 Pro
- [x] Identify mixer controls for far-end capture
- [x] Document audio routing (48kHz stereo native)
- [x] Verify TinyALSA capture/playback during calls

### ✅ Phase 2: Audio Pipeline — COMPLETE
- [x] TinyALSAStreamer: Process-based capture/playback
- [x] Sample rate conversion: 48kHz ↔ 24kHz
- [x] Stereo ↔ mono conversion
- [x] FIFO-based continuous playback

### 🔄 Phase 3: OpenAI Realtime — COMPLETE
- [x] HybridRealtimeBridge: Full Realtime API integration
- [x] Server-side VAD (voice activity detection)
- [x] Barging (interrupt AI while speaking)
- [x] Whisper transcription of both parties
- [x] Function calling support

### 🔄 Phase 4: Clawdbot Integration — IN PROGRESS
- [x] ClawdbotBridge: RPC client for Gateway
- [x] Context fetching (memories, user info, calendar)
- [x] Transcript streaming
- [x] phone-bridge plugin for Gateway
- [ ] Tool execution (calendar, reminders, lights)
- [ ] Full testing with live calls

### Phase 5: Android App
- [ ] Call detection and auto-answer
- [ ] Background service
- [ ] API key secure storage
- [ ] Settings UI

## Architecture

```
bandophone/
├── android/
│   └── app/src/main/java/com/bando/phone/
│       ├── audio/
│       │   ├── HybridRealtimeBridge.kt  # Main orchestrator
│       │   └── TinyALSAStreamer.kt      # TinyALSA wrapper
│       └── bridge/
│           └── ClawdbotBridge.kt        # Gateway RPC client
├── docs/
│   ├── CLAWDBOT_PHONE_CHANNEL_PLAN.md   # Integration design
│   ├── HYBRID_REALTIME_AUDIO_PLAN.md    # Audio architecture
│   ├── AUDIO_ROUTING.md                 # Device findings
│   └── NATIVE_AUDIO_ARCHITECTURE.md     # TinyALSA details
└── working-docs/                        # Development notes
```

## Quick Start

### 1. Set up TinyALSA on Phone

```bash
# Push TinyALSA binaries
adb push tinycap tinyplay tinymix /data/local/tmp/
adb shell chmod +x /data/local/tmp/tiny*

# Test capture (during active call)
adb shell su -c "/data/local/tmp/tinycap /data/local/tmp/test.wav -D 0 -d 20 -c 2 -r 48000 -b 16 -p 480 -n 4"
```

### 2. Configure phone-bridge Plugin

Add to your Clawdbot config:

```yaml
extensions:
  phone-bridge:
    enabled: true
    authToken: "your-secret-token"
    trustedNumbers:
      - "+16305382264"  # Your number
    logTranscripts: true
```

### 3. Build and Run Android App

```bash
cd android
./gradlew assembleDebug
adb install app/build/outputs/apk/debug/app-debug.apk
```

## Key Files

| File | Purpose |
|------|---------|
| `HybridRealtimeBridge.kt` | Orchestrates TinyALSA + Realtime API + Clawdbot |
| `TinyALSAStreamer.kt` | Process-based TinyALSA wrapper |
| `ClawdbotBridge.kt` | JSON-RPC client for Gateway |
| `phone-bridge/index.ts` | Gateway plugin for phone calls |

## Pixel 7 Pro Audio Routing

```
Device 20 (Capture):  Far-end audio (what caller says)
Device 19 (Playback): Inject audio (what AI says)
Mixer 167: Mic mute control
Mixer 152: Capture routing (set to DL for far-end)
```

## Voices

Supported OpenAI Realtime voices:
- **alloy** - Neutral, balanced (default)
- **echo** - Warm, conversational male
- **shimmer** - Clear, expressive female
- **ash** - Soft, thoughtful
- **ballad** - Warm, storytelling
- **coral** - Bright, friendly
- **sage** - Calm, wise
- **verse** - Dynamic, engaging

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
- [Clawdbot Android Node](https://github.com/clawdbot/clawdbot-android) — Companion app

---

*"The best interface is no interface." — Golden Krishna*

*Sometimes the best interface is just a phone call.*
