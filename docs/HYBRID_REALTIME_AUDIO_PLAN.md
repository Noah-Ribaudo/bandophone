# Hybrid TinyALSA + Realtime API Architecture

**Goal:** Enable full OpenAI Realtime API features (streaming, server VAD, barging, low latency) on Android phone calls while capturing far-end audio (what the other party says) without routing local mic audio.

**Device:** Rooted Pixel 7 Pro running Android 16

---

## The Problem

### Current Native Approach (What We Built Today)
- Uses `AudioRecord` with `VOICE_COMMUNICATION` source
- Streams mic audio → OpenAI Realtime API
- OpenAI responds with audio → `AudioTrack` plays into call

**Issue:** `AudioRecord` captures the LOCAL microphone. When mic is muted (so user's voice doesn't go through), OpenAI receives silence and can't hear the remote party.

### Previous TinyALSA Batch Approach
- `tinycap` device 20 captures far-end audio (what remote party says)
- Audio sent to Whisper → GPT → TTS → `tinyplay` device 19

**Issue:** Batch processing breaks Realtime API benefits - no streaming, no server VAD, no natural barging, high latency.

---

## Proposed Solution: Hybrid Streaming Architecture

### Core Insight
TinyALSA gives us access to the RIGHT audio (far-end call audio), and the Realtime API gives us the RIGHT processing (streaming, VAD, barging). We need to bridge them.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Phone Call                                │
│   Remote Party ←──────────────────────────────→ Pixel 7 Pro     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   TinyALSA Layer (Root)                          │
│                                                                  │
│   tinycap device 20 ──→ Far-end audio (what remote says)        │
│   tinyplay device 19 ←── AI audio injection (what AI says)      │
│   tinymix 167=1 ──────── Mic muted (user voice blocked)         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              Streaming Bridge (New Component)                    │
│                                                                  │
│   ┌─────────────────┐         ┌──────────────────────┐         │
│   │ TinyALSA Reader │ ──────→ │ RealtimeAudioBridge  │         │
│   │ (JNI/Native)    │ PCM     │ (Kotlin + OkHttp)    │         │
│   └─────────────────┘         └──────────────────────┘         │
│           ▲                            │ ▲                      │
│           │                            │ │                      │
│           │ read                       │ │ WebSocket            │
│           │                            ▼ │                      │
│   ┌─────────────────┐         ┌──────────────────────┐         │
│   │ ALSA Device 20  │         │   OpenAI Realtime    │         │
│   │ (48kHz stereo)  │         │   API Server         │         │
│   └─────────────────┘         └──────────────────────┘         │
│                                        │                        │
│                                        ▼                        │
│   ┌─────────────────┐         ┌──────────────────────┐         │
│   │ TinyALSA Writer │ ←────── │ Audio Playback       │         │
│   │ (JNI/Native)    │ PCM     │ Queue                │         │
│   └─────────────────┘         └──────────────────────┘         │
│           │                                                     │
│           ▼                                                     │
│   ┌─────────────────┐                                          │
│   │ ALSA Device 19  │                                          │
│   │ (inject to call)│                                          │
│   └─────────────────┘                                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementation Options

### Option A: JNI TinyALSA Library (Recommended)

**Approach:** Compile tinyalsa as a native library, access directly from Android app via JNI.

**Pros:**
- Lowest possible latency (direct memory access)
- No process spawning overhead
- Clean integration with existing Kotlin code
- Full control over buffer sizes and timing

**Cons:**
- Requires NDK setup and JNI boilerplate
- More complex build process
- Need to handle native crashes gracefully

**Implementation:**
1. Add tinyalsa source to `app/src/main/cpp/`
2. Create JNI wrapper (`TinyALSABridge.kt` + `tinyalsa_jni.cpp`)
3. Expose functions:
   - `startCapture(device: Int, channels: Int, rate: Int, callback: (ByteArray) -> Unit)`
   - `startPlayback(device: Int, channels: Int, rate: Int): PlaybackHandle`
   - `writePlayback(handle: PlaybackHandle, data: ByteArray)`
   - `setMixerControl(control: Int, value: Int)`

**Latency estimate:** ~10-20ms (buffer to buffer)

### Option B: Process Streaming via stdin/stdout

**Approach:** Spawn tinycap/tinyplay as child processes, stream via pipes.

**Pros:**
- Uses existing binaries (no compilation needed)
- Simpler initial implementation
- Easier to debug (can test commands manually)

**Cons:**
- Process spawn overhead (~50-100ms initial)
- IPC overhead for data transfer
- Less control over buffering
- Potential for pipe buffer issues

**Implementation:**
1. Spawn: `su -c "tinycap - -D 0 -d 20 -c 2 -r 48000 -b 16"` (stdout mode)
2. Read stdout in real-time from Kotlin
3. Resample 48kHz stereo → 24kHz mono (Realtime API format)
4. Stream to WebSocket

**Latency estimate:** ~50-100ms

### Option C: FIFO Named Pipes

**Approach:** Create FIFO, have tinycap write to it, app reads from it.

**Pros:**
- Decouples capture process from app
- Can survive app restarts
- Shell script friendly

**Cons:**
- Extra filesystem operations
- Buffer management complexity
- Permissions issues possible

**Latency estimate:** ~30-50ms

---

## Recommended Implementation: Option A (JNI)

### Phase 1: Native Library Setup (2-3 hours)

1. **Add NDK support to build.gradle:**
```kotlin
android {
    ndkVersion "25.2.9519653"
    externalNativeBuild {
        cmake {
            path "src/main/cpp/CMakeLists.txt"
        }
    }
}
```

2. **Create CMakeLists.txt:**
```cmake
cmake_minimum_required(VERSION 3.18.1)
project(tinyalsa_bridge)

add_library(tinyalsa STATIC
    tinyalsa/mixer.c
    tinyalsa/pcm.c
)

add_library(tinyalsa_bridge SHARED
    tinyalsa_jni.cpp
)

target_link_libraries(tinyalsa_bridge
    tinyalsa
    log
)
```

3. **JNI Interface (tinyalsa_jni.cpp):**
```cpp
extern "C" {

JNIEXPORT jlong JNICALL
Java_com_bando_phone_audio_TinyALSABridge_nativeOpenCapture(
    JNIEnv *env, jobject thiz,
    jint card, jint device, jint channels, jint rate) {
    
    struct pcm_config config = {
        .channels = channels,
        .rate = rate,
        .period_size = 480,  // 20ms at 24kHz, 10ms at 48kHz
        .period_count = 4,
        .format = PCM_FORMAT_S16_LE,
    };
    
    struct pcm *pcm = pcm_open(card, device, PCM_IN, &config);
    return (jlong)pcm;
}

JNIEXPORT jint JNICALL
Java_com_bando_phone_audio_TinyALSABridge_nativeRead(
    JNIEnv *env, jobject thiz,
    jlong handle, jbyteArray buffer) {
    
    struct pcm *pcm = (struct pcm *)handle;
    jbyte *buf = env->GetByteArrayElements(buffer, NULL);
    int size = env->GetArrayLength(buffer);
    
    int ret = pcm_read(pcm, buf, size);
    
    env->ReleaseByteArrayElements(buffer, buf, 0);
    return ret;
}

// Similar for playback, mixer control...

}
```

4. **Kotlin Wrapper (TinyALSABridge.kt):**
```kotlin
object TinyALSABridge {
    init {
        System.loadLibrary("tinyalsa_bridge")
    }
    
    external fun nativeOpenCapture(card: Int, device: Int, channels: Int, rate: Int): Long
    external fun nativeRead(handle: Long, buffer: ByteArray): Int
    external fun nativeClose(handle: Long)
    
    external fun nativeOpenPlayback(card: Int, device: Int, channels: Int, rate: Int): Long
    external fun nativeWrite(handle: Long, buffer: ByteArray): Int
    
    external fun nativeSetMixer(card: Int, control: Int, value: Int): Int
}
```

### Phase 2: Audio Pipeline Integration (2-3 hours)

1. **Modify RealtimeAudioBridge to use TinyALSA for capture:**

```kotlin
// Instead of AudioRecord:
private fun startCapture() {
    captureJob = scope.launch(Dispatchers.IO) {
        // Open TinyALSA capture (device 20 = far-end audio)
        val handle = TinyALSABridge.nativeOpenCapture(
            card = 0, device = 20, channels = 2, rate = 48000
        )
        
        val buffer = ByteArray(CAPTURE_BUFFER_SIZE)  // ~10ms of audio
        
        while (isActive && isRunning) {
            val bytesRead = TinyALSABridge.nativeRead(handle, buffer)
            if (bytesRead > 0) {
                // Convert 48kHz stereo → 24kHz mono (Realtime API format)
                val converted = convertAudio(buffer, bytesRead)
                sendAudioChunk(converted)
            }
        }
        
        TinyALSABridge.nativeClose(handle)
    }
}
```

2. **Audio format conversion:**
```kotlin
private fun convertAudio(input: ByteArray, length: Int): ByteArray {
    // 48kHz stereo S16LE → 24kHz mono S16LE
    // Downsample by 2, mix stereo to mono
    
    val samples = length / 4  // 4 bytes per stereo sample
    val output = ByteArray(samples)  // 2 bytes per mono sample, half the samples
    
    val inputBuffer = ByteBuffer.wrap(input).order(ByteOrder.LITTLE_ENDIAN)
    val outputBuffer = ByteBuffer.wrap(output).order(ByteOrder.LITTLE_ENDIAN)
    
    for (i in 0 until samples step 2) {  // Skip every other sample (downsample)
        val left = inputBuffer.getShort(i * 4)
        val right = inputBuffer.getShort(i * 4 + 2)
        val mono = ((left + right) / 2).toShort()
        outputBuffer.putShort(mono)
    }
    
    return output
}
```

3. **Playback options:**

**Option A: TinyALSA playback (device 19)**
```kotlin
private fun startPlayback() {
    playbackJob = scope.launch(Dispatchers.IO) {
        val handle = TinyALSABridge.nativeOpenPlayback(
            card = 0, device = 19, channels = 2, rate = 48000
        )
        
        while (isActive && isRunning) {
            val chunk = playbackQueue.receive()
            // Convert 24kHz mono → 48kHz stereo
            val converted = convertForPlayback(chunk)
            TinyALSABridge.nativeWrite(handle, converted)
        }
        
        TinyALSABridge.nativeClose(handle)
    }
}
```

**Option B: Keep native AudioTrack** (might work without TinyALSA if USAGE_VOICE_COMMUNICATION routes correctly)

### Phase 3: Mixer and Call Integration (1 hour)

```kotlin
object CallAudioSetup {
    fun setupForAICall() {
        // Mute local mic
        TinyALSABridge.nativeSetMixer(0, 167, 1)
        
        // Enable capture routing
        TinyALSABridge.nativeSetMixer(0, 152, /* DL value */)
    }
    
    fun teardown() {
        // Restore normal audio routing
        TinyALSABridge.nativeSetMixer(0, 167, 0)
    }
}
```

---

## Audio Format Summary

| Stage | Format | Notes |
|-------|--------|-------|
| TinyALSA Capture (dev 20) | 48kHz stereo S16LE | Far-end call audio |
| After conversion | 24kHz mono S16LE | Realtime API input format |
| Realtime API output | 24kHz mono S16LE | AI response audio |
| After conversion | 48kHz stereo S16LE | For TinyALSA playback |
| TinyALSA Playback (dev 19) | 48kHz stereo S16LE | Injected into call |

---

## Latency Budget

| Component | Time |
|-----------|------|
| TinyALSA capture buffer | 10ms |
| Format conversion | 1ms |
| WebSocket send | 5ms |
| Network RTT | 50-100ms |
| OpenAI processing | 100-300ms |
| WebSocket receive | 5ms |
| Format conversion | 1ms |
| TinyALSA playback buffer | 10ms |
| **Total** | **~180-430ms** |

This is comparable to or better than the current web-based Realtime API demo.

---

## Risks and Mitigations

### Risk 1: ALSA device access permissions
**Mitigation:** App runs commands via `su`, or we set device permissions at boot.

### Risk 2: Audio routing changes between Android versions
**Mitigation:** Device-specific config, tested on Pixel 7 Pro Android 16. May need adjustment for other devices.

### Risk 3: Buffer underruns/overruns
**Mitigation:** Use ring buffers, monitor for glitches, tune period sizes.

### Risk 4: JNI crashes
**Mitigation:** Defensive error handling, signal handlers, fallback to process-based approach.

---

## Testing Plan

1. **Unit test TinyALSA JNI wrapper** — Capture/playback to files
2. **Integration test audio pipeline** — Loopback test (capture → convert → playback)
3. **Realtime API test** — WebSocket connection + audio streaming
4. **Full call test** — Make actual call, verify AI conversation works
5. **Latency measurement** — Timestamp audio packets, measure round-trip
6. **Barging test** — Interrupt AI mid-sentence, verify quick response

---

## Success Criteria

- [ ] Far-end audio captured without local mic
- [ ] Audio streams to Realtime API (not batched)
- [ ] Server VAD detects speech correctly
- [ ] Barging/interruption works naturally
- [ ] Round-trip latency < 500ms
- [ ] No audio glitches during normal conversation
- [ ] Works reliably across multiple calls

---

## Timeline Estimate

| Phase | Time | Deliverable |
|-------|------|-------------|
| Phase 1: NDK/JNI setup | 2-3 hours | TinyALSA native library + JNI wrapper |
| Phase 2: Audio pipeline | 2-3 hours | Integrated capture/playback with RealtimeAudioBridge |
| Phase 3: Call integration | 1 hour | Mixer setup, call lifecycle hooks |
| Testing & debugging | 2-3 hours | Working end-to-end system |
| **Total** | **7-10 hours** | Production-ready hybrid system |

---

## Alternatives Considered

1. **Android's AudioRecord with REMOTE_SUBMIX** — Requires system app signature, not available for user apps even with root.

2. **Xposed/LSPosed hooks** — Could hook audio system calls, but adds complexity and potential instability.

3. **Custom kernel module** — Maximum control but requires maintaining kernel patches across updates.

4. **External audio interface** — USB audio device could capture call audio, but adds hardware dependency.

**Conclusion:** JNI TinyALSA wrapper is the best balance of capability, reliability, and maintainability.

---

## Questions for Review

1. Is the JNI approach the right call, or should we prototype with process streaming first?
2. Should playback use TinyALSA or try native AudioTrack first?
3. Any concerns about the audio format conversion approach?
4. Are there better ways to handle the 48kHz→24kHz resampling?
5. What's the fallback plan if JNI approach hits unexpected roadblocks?
