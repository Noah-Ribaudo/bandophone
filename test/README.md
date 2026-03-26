# Bandophone Test Harness

End-to-end self-test for the Bandophone audio bridge using Twilio Media Streams.

## Architecture

```
┌─────────────┐     Twilio      ┌──────────────┐     TinyALSA     ┌─────────────┐
│ Test Harness │◄──Media Stream──►│  Twilio SIP  │◄──Phone Call──►│  Pixel 7 Pro │
│  (this code) │    (WebSocket)  │   Gateway    │   (cellular)    │ (Bandophone) │
└─────────────┘                  └──────────────┘                 └──────┬──────┘
      │                                                                  │
      │  inject test audio                                    capture + inject
      │  record AI responses                                  via TinyALSA
      │  measure latency                                             │
      │                                                       ┌─────┴──────┐
      └───────────────────────────────────────────────────────│  OpenAI RT  │
                                                              └────────────┘
```

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Twilio Credentials

Already stored in macOS Keychain:
```bash
security find-generic-password -a "bando" -s "twilio-account-sid" -w
security find-generic-password -a "bando" -s "twilio-auth-token" -w
```

### 3. ngrok (for Twilio webhook access)

```bash
brew install ngrok
# Or use an alternative: npx localtunnel --port 5000
```

### 4. Generate Test Audio

```bash
python generate_test_audio.py           # All default phrases
python generate_test_audio.py --list    # See what was generated
```

## Usage

### Dry Run (test credentials)

```bash
python test_call.py --dry-run
```

### Full Test Call

```bash
# Basic — call Pixel, record everything Twilio hears
python test_call.py

# With audio injection — speak a test phrase into the call
python test_call.py --inject audio/weather.wav

# With custom duration
python test_call.py --duration 30

# With existing ngrok tunnel
python test_call.py --tunnel-url https://abc123.ngrok.io
```

### Manual Server Mode

Run the webhook server standalone for debugging:

```bash
# Terminal 1: Start server
python twilio_test_server.py --port 5000 --ws-port 8766

# Terminal 2: Start ngrok
ngrok http 5000

# Terminal 3: Trigger call manually or via test_call.py --no-tunnel
```

## Files

| File | Purpose |
|------|---------|
| `twilio_test_server.py` | Flask webhook + WebSocket server for Twilio Media Streams |
| `test_call.py` | Test orchestrator — starts server, tunnel, initiates call |
| `generate_test_audio.py` | Generate 8kHz mulaw test audio from TTS |
| `audio/` | Generated test audio files |
| `results/` | Test results — recordings, latency reports, logs |

## Audio Formats

- **Twilio Media Streams**: 8kHz mu-law mono (telephony standard)
- **Bandophone capture**: 48kHz stereo PCM16 → downsampled to 24kHz mono for OpenAI
- **Bandophone inject**: 24kHz mono PCM16 from OpenAI → stereo → 16kHz device playback

The test harness operates at the Twilio/telephony layer (8kHz mulaw), testing the full audio path including codec conversion.

## Latency Measurement

When using `--inject`, the harness measures:
- **Inject time**: When test audio is sent to Twilio
- **Response time**: When first non-silent audio is received back from Twilio
- **Latency**: The difference — includes Twilio processing + cellular latency + Bandophone capture + OpenAI Realtime inference + Bandophone injection + return path

## Trial Account Notes

- Twilio trial account can only call **verified numbers**
- The Pixel (+17736984245) is verified ✅
- Outbound caller ID must be +14842960680 (our Twilio number)
- Trial calls play a brief Twilio announcement before connecting
