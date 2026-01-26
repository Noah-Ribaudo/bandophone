# Native Audio Architecture for Bandophone

## Goal
Make the phone call audio bridge completely transparent to OpenAI's Realtime API.
From the API's perspective, it should be indistinguishable from a web app.

## Architecture

```
┌─────────────┐     Cell      ┌──────────────────────────────────────┐
│   You       │◄────Call────►│         Pixel 7 Pro                  │
│ (iPhone)    │               │                                      │
└─────────────┘               │  ┌──────────────────────────────┐   │
                              │  │     BandoInCallService        │   │
                              │  │                                │   │
                              │  │  ┌────────────────────────┐   │   │
                              │  │  │  RealtimeAudioBridge   │   │   │
                              │  │  │                        │   │   │
                              │  │  │  AudioRecord ──────────┼───┼───┼──► OpenAI
                              │  │  │  (24kHz mono)          │   │   │    Realtime
                              │  │  │                        │   │   │    API
                              │  │  │  AudioTrack ◄──────────┼───┼───┼─── (WebSocket)
                              │  │  │  (24kHz mono)          │   │   │
                              │  │  └────────────────────────┘   │   │
                              │  └──────────────────────────────┘   │
                              └──────────────────────────────────────┘
```

## Key Components

### 1. RealtimeAudioBridge.kt
Direct WebSocket connection to OpenAI Realtime API with:
- **AudioRecord** using `VOICE_COMMUNICATION` source → captures call audio
- **AudioTrack** using `VOICE_COMMUNICATION` usage → plays into call
- **24kHz mono PCM16** - native Realtime API format, no conversion needed
- **20ms chunks** - low latency, ~960 bytes per chunk
- **Server VAD** - OpenAI handles voice activity detection + barging

### 2. CallAudioManager.kt
Orchestrates the bridge lifecycle:
- Detects call state changes
- Configures `MODE_IN_COMMUNICATION` audio routing
- Starts/stops bridge when calls connect/disconnect

### 3. BandoInCallService
Android's `InCallService` integration:
- System grants access to call audio
- Automatically triggered for all calls
- No user interaction needed once set as default

## Latency Breakdown

| Component | Latency |
|-----------|---------|
| AudioRecord buffer | ~20ms |
| WebSocket send | ~10ms |
| Network RTT | ~50-100ms |
| OpenAI processing | ~200-500ms |
| WebSocket receive | ~10ms |
| AudioTrack buffer | ~20ms |
| **Total** | **~300-650ms** |

This is comparable to a native web app experience!

## Barging / Interruption

Works natively because:
1. We use `server_vad` turn detection
2. OpenAI's VAD detects user speech immediately
3. Sends `input_audio_buffer.speech_started` event
4. Current response is automatically interrupted
5. No special handling needed on our side

## Setup Requirements

### Android Manifest
```xml
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />
<uses-permission android:name="android.permission.BIND_INCALL_SERVICE" />

<service
    android:name=".audio.BandoInCallService"
    android:permission="android.permission.BIND_INCALL_SERVICE"
    android:exported="true">
    <meta-data
        android:name="android.telecom.IN_CALL_SERVICE_UI"
        android:value="true" />
    <intent-filter>
        <action android:name="android.telecom.InCallService" />
    </intent-filter>
</service>
```

### Build Dependencies
```kotlin
// build.gradle.kts
dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
}
```

### User Setup
1. Install BandoPhone app
2. Set as default phone app (for InCallService access)
3. Grant microphone permission
4. Configure OpenAI API key in app

## Comparison to TinyALSA Approach

| Aspect | TinyALSA (CLI) | Native Android |
|--------|----------------|----------------|
| Latency | ~500-800ms+ | ~300-650ms |
| Barging | Manual, delayed | Native, instant |
| Reliability | File I/O overhead | Direct streaming |
| Complexity | ADB, root, CLI tools | Standard Android APIs |
| Battery | High (constant ADB) | Efficient |

## Future Optimizations

1. **WebRTC instead of WebSocket**
   - Even lower latency
   - Better for real-time audio
   - OpenAI supports this natively

2. **Opus codec**
   - If OpenAI adds support
   - Better compression, lower bandwidth

3. **Echo cancellation tuning**
   - Android's AEC may need adjustment
   - Test with `AcousticEchoCanceler`

## Testing

1. Build and install app
2. Set as default phone app
3. Make a test call
4. AI should answer automatically
5. Test barging by interrupting mid-sentence
