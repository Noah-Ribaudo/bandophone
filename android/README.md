# Bandophone Android App

Minimal Android app for audio injection into phone calls.

## Why This Is Needed

Direct ALSA access via `tinyplay` bypasses Android's AudioFlinger routing, so audio isn't sent to the telephony transmit path. We need to use the Android AudioTrack API with proper stream types.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Bandophone Android App                                  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────────┐    ┌──────────────────────────┐   │
│  │  Socket Server  │───▶│  AudioTrack Player       │   │
│  │  (port 9999)    │    │  USAGE_VOICE_COMMUNICATION│   │
│  └─────────────────┘    └──────────────────────────┘   │
│                                                         │
│  ┌─────────────────┐    ┌──────────────────────────┐   │
│  │  Call Listener  │───▶│  Auto-enable on call     │   │
│  │                 │    │                          │   │
│  └─────────────────┘    └──────────────────────────┘   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Key Components

### 1. AudioTrack with Voice Usage

```kotlin
val audioTrack = AudioTrack.Builder()
    .setAudioAttributes(
        AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build()
    )
    .setAudioFormat(
        AudioFormat.Builder()
            .setSampleRate(48000)
            .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
            .build()
    )
    .setBufferSizeInBytes(bufferSize)
    .setTransferMode(AudioTrack.MODE_STREAM)
    .build()
```

### 2. Socket Server

Listens on localhost:9999 for PCM audio data from the bridge script.

### 3. Call State Listener

Automatically starts the audio injection service when a call becomes active.

## Permissions Required

```xml
<uses-permission android:name="android.permission.READ_PHONE_STATE" />
<uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
```

## Building

```bash
cd android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## TODO

- [ ] Create Android Studio project
- [ ] Implement AudioTrack player service
- [ ] Implement socket server
- [ ] Test audio injection during call
- [ ] Add UI for status/control
