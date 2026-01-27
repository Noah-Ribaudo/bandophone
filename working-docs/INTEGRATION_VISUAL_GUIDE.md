# Visual Integration Guide

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BandoPhone App                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌────────────────┐         ┌────────────────┐                    │
│  │   MainActivity │◄────────┤ SettingsActivity│                    │
│  │                │         │                │                    │
│  │  - Start/Stop  │         │  - API Key     │                    │
│  │  - Status UI   │         │  - Voice       │                    │
│  │  - Legacy Mode │         │  - Instructions│                    │
│  └────────┬───────┘         └───────┬────────┘                    │
│           │                         │                              │
│           │                         ▼                              │
│           │                  ┌─────────────┐                       │
│           │                  │ApiKeyManager│                       │
│           │                  │             │                       │
│           │                  │ Encrypted   │                       │
│           │                  │ Storage     │                       │
│           │                  └──────┬──────┘                       │
│           │                         │                              │
│           │     Phone Call Starts   │                              │
│           │            │            │                              │
│           │            ▼            │                              │
│           │   ┌─────────────────────▼────────┐                    │
│           │   │  BandoInCallService          │                    │
│           │   │                              │                    │
│           │   │  1. onCreate()               │                    │
│           │   │  2. Load API key             │                    │
│           │   │  3. Create CallAudioManager  │                    │
│           │   └──────────┬───────────────────┘                    │
│           │              │                                         │
│           │              ▼                                         │
│           │   ┌─────────────────────────┐                         │
│           │   │  CallAudioManager       │                         │
│           │   │                         │                         │
│           │   │  1. Setup audio routing │                         │
│           │   │  2. Detect call active  │                         │
│           │   │  3. Start bridge        │                         │
│           │   └──────────┬──────────────┘                         │
│           │              │                                         │
│           │              ▼                                         │
│           │   ┌─────────────────────────────────┐                 │
│           │   │   RealtimeAudioBridge           │                 │
│           │   │                                 │                 │
│           │   │  ┌──────────┐  ┌─────────────┐ │                 │
│           │   │  │AudioRecord│  │  AudioTrack │ │                 │
│           │   │  │(24kHz)    │  │  (24kHz)    │ │                 │
│           │   │  │VOICE_COMM │  │ VOICE_COMM  │ │                 │
│           │   │  └─────┬─────┘  └──────▲──────┘ │                 │
│           │   │        │               │         │                 │
│           │   │        ▼               │         │                 │
│           │   │   ┌─────────────────────────┐   │                 │
│           │   │   │   WebSocket (OkHttp)    │   │                 │
│           │   │   │   wss://api.openai.com  │   │                 │
│           │   │   └─────────────────────────┘   │                 │
│           │   └─────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │   OpenAI Realtime API  │
                    │   gpt-4o-realtime      │
                    └────────────────────────┘
```

## Data Flow Diagram

```
User Speech ──────────────────────────────────────────► AI Response
    │                                                        │
    ▼                                                        ▼
Phone Mic                                          Phone Speaker
    │                                                        ▲
    ▼                                                        │
AudioRecord                                           AudioTrack
(VOICE_COMMUNICATION)                         (VOICE_COMMUNICATION)
    │                                                        ▲
    │ 24kHz PCM16                                 24kHz PCM16│
    ▼                                                        │
Base64 Encode                                      Base64 Decode
    │                                                        ▲
    │ JSON event                                   JSON event│
    ▼                                                        │
WebSocket Send                                   WebSocket Receive
    │                                                        ▲
    └────────────────────► OpenAI ◄────────────────────────┘
                      (Server VAD + GPT-4o)
```

## File Organization

```
bandophone/
├── android/
│   └── app/
│       ├── build.gradle                    [MODIFIED] Dependencies
│       └── src/main/
│           ├── AndroidManifest.xml         [MODIFIED] Permissions + Services
│           └── java/
│               ├── com/bandophone/
│               │   ├── MainActivity.kt     [MODIFIED] Added Settings nav
│               │   ├── SettingsActivity.kt [NEW] Settings UI
│               │   ├── ApiKeyManager.kt    [NEW] Secure storage
│               │   ├── BandophoneApp.kt    [EXISTING] App class
│               │   ├── AudioInjectionService.kt [EXISTING] Legacy
│               │   └── BridgeClient.kt     [EXISTING] Legacy
│               └── com/bando/phone/audio/
│                   ├── RealtimeAudioBridge.kt [EXISTING] WebSocket bridge
│                   └── CallAudioManager.kt    [MODIFIED] API key integration
│
├── docs/
│   └── NATIVE_AUDIO_ARCHITECTURE.md       [EXISTING] Architecture doc
│
├── INTEGRATION_SUMMARY.md                 [NEW] Full integration details
├── VERIFICATION_CHECKLIST.md              [NEW] Testing procedures
├── QUICK_START_NATIVE_AUDIO.md            [NEW] User guide
├── SUBAGENT_INTEGRATION_REPORT.md         [NEW] Executive summary
└── INTEGRATION_VISUAL_GUIDE.md            [NEW] This file
```

## Call Lifecycle States

```
┌─────────────┐
│   Idle      │
│   (No call) │
└──────┬──────┘
       │
       │ Incoming/Outgoing Call
       ▼
┌─────────────────┐
│   Ringing       │
└──────┬──────────┘
       │
       │ Call Answered
       ▼
┌──────────────────────────┐
│   Active (Connected)     │◄─── BandoInCallService launches here
│                          │
│   ┌──────────────────┐   │
│   │ Audio Routing    │   │
│   │ MODE_IN_COMM     │   │
│   └────────┬─────────┘   │
│            │             │
│            ▼             │
│   ┌──────────────────┐   │
│   │ Bridge Started   │   │
│   │ OpenAI Connected │   │
│   └────────┬─────────┘   │
│            │             │
│            ▼             │
│   ┌──────────────────┐   │
│   │ Conversation     │   │◄─── User can speak/listen here
│   │ Active           │   │
│   └────────┬─────────┘   │
└────────────┼─────────────┘
             │
             │ Call Ends
             ▼
┌──────────────────────┐
│   Disconnecting      │
│                      │
│   - Stop bridge      │
│   - Release audio    │
│   - Reset routing    │
└──────┬───────────────┘
       │
       ▼
┌─────────────┐
│   Idle      │
└─────────────┘
```

## Settings Flow

```
User Opens App
      │
      ▼
┌─────────────┐
│ MainActivity│
│             │
│ Has API Key?├─── Yes ──► Show "✅ Configured" status
│             │
└──────┬──────┘
       │
       │ No
       ▼
Show "⚠️ Not Configured"
       │
       │ User taps "⚙️ Settings"
       ▼
┌──────────────────┐
│ SettingsActivity │
│                  │
│ ┌──────────────┐ │
│ │ API Key      │ │◄─── User enters: sk-xxxxx
│ └──────────────┘ │
│ ┌──────────────┐ │
│ │ Voice        │ │◄─── User selects: Alloy, Echo, etc.
│ └──────────────┘ │
│ ┌──────────────┐ │
│ │ Instructions │ │◄─── User edits system prompt
│ └──────────────┘ │
│                  │
│ [Save Settings]  │◄─── User taps Save
└────────┬─────────┘
         │
         ▼
ApiKeyManager.saveApiKey()
         │
         ▼
EncryptedSharedPreferences
         │
         │ AES256-GCM Encryption
         ▼
┌─────────────────────┐
│ Android Keystore    │
│ (Secure Hardware)   │
└─────────────────────┘
```

## Audio Pipeline Detail

```
                    CAPTURE PATH (User → OpenAI)
                    ═════════════════════════════

Phone Mic ──► Phone Call Audio ──► AudioRecord
                                         │
                                         │ MediaRecorder.AudioSource
                                         │ .VOICE_COMMUNICATION
                                         │
                                         ▼
                                  ┌─────────────┐
                                  │ 24kHz Mono  │
                                  │ PCM16       │
                                  │ 20ms chunks │
                                  │ (960 bytes) │
                                  └──────┬──────┘
                                         │
                                         │ Base64 encode
                                         ▼
                                  ┌─────────────┐
                                  │ JSON Event  │
                                  │ {           │
                                  │   type: "..." │
                                  │   audio: "..." │
                                  │ }           │
                                  └──────┬──────┘
                                         │
                                         │ WebSocket.send()
                                         ▼
                                      OpenAI




                    PLAYBACK PATH (OpenAI → User)
                    ══════════════════════════════

                                      OpenAI
                                         │
                                         │ WebSocket event
                                         ▼
                                  ┌─────────────┐
                                  │ JSON Event  │
                                  │ {           │
                                  │   type: "..." │
                                  │   delta: "..." │
                                  │ }           │
                                  └──────┬──────┘
                                         │
                                         │ Base64 decode
                                         ▼
                                  ┌─────────────┐
                                  │ 24kHz Mono  │
                                  │ PCM16       │
                                  │ Raw bytes   │
                                  └──────┬──────┘
                                         │
                                         │ AudioTrack.write()
                                         ▼
                                    AudioTrack
                                         │
                                         │ AudioAttributes.USAGE
                                         │ _VOICE_COMMUNICATION
                                         │
Phone Speaker ◄── Phone Call Audio ◄────┘
```

## Permission & Setup Checklist

```
┌─────────────────────────────────────────────┐
│ 1. Install App                              │
│    ✓ APK built and installed                │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│ 2. Grant Permissions                        │
│    □ RECORD_AUDIO                           │
│    □ READ_PHONE_STATE                       │
│    □ POST_NOTIFICATIONS                     │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│ 3. Configure Settings                       │
│    □ Enter OpenAI API key                   │
│    □ Choose voice                           │
│    □ Edit instructions (optional)           │
│    □ Save                                   │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│ 4. Set as Default Phone App                │
│    Android Settings → Apps → Default Apps  │
│    → Phone App → BandoPhone                 │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│ 5. Make Test Call                           │
│    Call connects → AI automatically answers │
└─────────────────────────────────────────────┘
```

## Debug Output Example

```bash
# Successful call with AI integration

01-26 12:15:23.456  1234  1234 I BandoInCallService: BandoInCallService created
01-26 12:15:23.457  1234  1234 I BandoInCallService: Call added
01-26 12:15:25.123  1234  1234 I CallAudioManager: Call became active, starting AI bridge
01-26 12:15:25.124  1234  1234 D CallAudioManager: Audio routing configured for voice communication
01-26 12:15:25.125  1234  1234 I RealtimeAudioBridge: Starting RealtimeAudioBridge
01-26 12:15:25.789  1234  5678 I RealtimeAudioBridge: WebSocket connected
01-26 12:15:25.790  1234  5678 D RealtimeAudioBridge: Session configured
01-26 12:15:25.791  1234  5678 I RealtimeAudioBridge: Starting audio capture loop
01-26 12:15:25.792  1234  5679 I RealtimeAudioBridge: Starting audio playback loop
01-26 12:15:27.123  1234  5678 D RealtimeAudioBridge: User speech detected (barge-in)
01-26 12:15:27.456  1234  5678 D RealtimeAudioBridge: User said: Hello
01-26 12:15:28.123  1234  5678 D RealtimeAudioBridge: AI finished speaking
01-26 12:16:45.678  1234  1234 I CallAudioManager: Call ended, stopping AI bridge
01-26 12:16:45.679  1234  1234 I RealtimeAudioBridge: Stopping RealtimeAudioBridge
01-26 12:16:45.680  1234  1234 D CallAudioManager: Audio routing reset to normal
```

## Troubleshooting Decision Tree

```
AI not responding during call?
        │
        ├─ Check: BandoInCallService launched?
        │       │
        │       ├─ No ──► Is app set as default phone app? ──► Fix: Set in Android Settings
        │       │
        │       └─ Yes ──► Check: API key configured?
        │                       │
        │                       ├─ No ──► Fix: Enter API key in Settings
        │                       │
        │                       └─ Yes ──► Check: WebSocket connected?
        │                                       │
        │                                       ├─ No ──► Check internet, API key validity
        │                                       │
        │                                       └─ Yes ──► Check: Audio permissions?
        │                                                       │
        │                                                       ├─ No ──► Grant RECORD_AUDIO
        │                                                       │
        │                                                       └─ Yes ──► Check logs for errors
```

---

**All visual guides complete!** 🎨

For detailed information, see:
- **Architecture:** `docs/NATIVE_AUDIO_ARCHITECTURE.md`
- **Implementation:** `INTEGRATION_SUMMARY.md`
- **Testing:** `VERIFICATION_CHECKLIST.md`
- **Quick Start:** `QUICK_START_NATIVE_AUDIO.md`
- **Status:** `SUBAGENT_INTEGRATION_REPORT.md`
