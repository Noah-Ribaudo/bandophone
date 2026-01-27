package com.bando.phone.audio

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.util.Base64
import android.util.Log
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import okhttp3.*
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * RealtimeAudioBridge - Transparent bridge between phone call audio and OpenAI Realtime API
 * 
 * Design goals:
 * - Minimum latency (small buffers, immediate streaming)
 * - Full Realtime API feature support (barging/interruption)
 * - Phone bridge should be invisible to the API
 * 
 * Audio flow:
 * - Capture: AudioRecord (24kHz mono) → base64 → WebSocket → OpenAI
 * - Playback: OpenAI → WebSocket → base64 decode → AudioTrack (24kHz mono)
 */
class RealtimeAudioBridge(
    private val apiKey: String,
    private val instructions: String = "You are a helpful assistant on a phone call.",
    private val voice: String = "alloy"
) {
    companion object {
        private const val TAG = "RealtimeAudioBridge"
        
        // OpenAI Realtime API format
        private const val SAMPLE_RATE = 24000
        private const val CHANNEL_CONFIG_IN = AudioFormat.CHANNEL_IN_MONO
        private const val CHANNEL_CONFIG_OUT = AudioFormat.CHANNEL_OUT_MONO
        private const val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT
        
        // Buffer sizes - tuned for low latency
        // 20ms chunks = good balance of latency vs efficiency
        private const val CHUNK_DURATION_MS = 20
        private const val SAMPLES_PER_CHUNK = SAMPLE_RATE * CHUNK_DURATION_MS / 1000  // 480 samples
        private const val BYTES_PER_CHUNK = SAMPLES_PER_CHUNK * 2  // 960 bytes (16-bit = 2 bytes)
        
        private const val REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-17"
    }
    
    private var webSocket: WebSocket? = null
    private var audioRecord: AudioRecord? = null
    private var audioTrack: AudioTrack? = null
    
    private var captureJob: Job? = null
    private var playbackJob: Job? = null
    
    private val playbackQueue = Channel<ByteArray>(Channel.UNLIMITED)
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    
    private var isRunning = false
    
    // Callbacks
    var onTranscript: ((String, Boolean) -> Unit)? = null  // text, isFinal
    var onError: ((String) -> Unit)? = null
    var onConnected: (() -> Unit)? = null
    var onDisconnected: (() -> Unit)? = null
    
    /**
     * Start the bridge - call this when phone call becomes active
     */
    fun start() {
        if (isRunning) return
        isRunning = true
        
        Log.i(TAG, "Starting RealtimeAudioBridge")
        
        // Initialize audio components
        initAudioRecord()
        initAudioTrack()
        
        // Connect to OpenAI
        connectWebSocket()
    }
    
    /**
     * Stop the bridge - call this when phone call ends
     */
    fun stop() {
        if (!isRunning) return
        isRunning = false
        
        Log.i(TAG, "Stopping RealtimeAudioBridge")
        
        captureJob?.cancel()
        playbackJob?.cancel()
        
        audioRecord?.stop()
        audioRecord?.release()
        audioRecord = null
        
        audioTrack?.stop()
        audioTrack?.release()
        audioTrack = null
        
        webSocket?.close(1000, "Call ended")
        webSocket = null
        
        onDisconnected?.invoke()
    }
    
    private fun initAudioRecord() {
        val minBufferSize = AudioRecord.getMinBufferSize(
            SAMPLE_RATE, CHANNEL_CONFIG_IN, AUDIO_FORMAT
        )
        
        // Use small buffer for low latency, but at least minBufferSize
        val bufferSize = maxOf(minBufferSize, BYTES_PER_CHUNK * 4)
        
        audioRecord = AudioRecord(
            MediaRecorder.AudioSource.VOICE_COMMUNICATION,  // Key: captures call audio
            SAMPLE_RATE,
            CHANNEL_CONFIG_IN,
            AUDIO_FORMAT,
            bufferSize
        ).also {
            if (it.state != AudioRecord.STATE_INITIALIZED) {
                Log.e(TAG, "AudioRecord failed to initialize")
                onError?.invoke("Failed to initialize audio capture")
            }
        }
    }
    
    private fun initAudioTrack() {
        val minBufferSize = AudioTrack.getMinBufferSize(
            SAMPLE_RATE, CHANNEL_CONFIG_OUT, AUDIO_FORMAT
        )
        
        // Small buffer for low latency
        val bufferSize = maxOf(minBufferSize, BYTES_PER_CHUNK * 4)
        
        audioTrack = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)  // Key: plays into call
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AUDIO_FORMAT)
                    .setSampleRate(SAMPLE_RATE)
                    .setChannelMask(CHANNEL_CONFIG_OUT)
                    .build()
            )
            .setBufferSizeInBytes(bufferSize)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .setPerformanceMode(AudioTrack.PERFORMANCE_MODE_LOW_LATENCY)
            .build()
    }
    
    private fun connectWebSocket() {
        val client = OkHttpClient.Builder()
            .readTimeout(0, TimeUnit.MILLISECONDS)  // No timeout for streaming
            .build()
        
        val request = Request.Builder()
            .url(REALTIME_URL)
            .header("Authorization", "Bearer $apiKey")
            .header("OpenAI-Beta", "realtime=v1")
            .build()
        
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.i(TAG, "WebSocket connected")
                configureSession()
                startAudioStreaming()
                onConnected?.invoke()
            }
            
            override fun onMessage(webSocket: WebSocket, text: String) {
                handleServerEvent(text)
            }
            
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WebSocket error: ${t.message}")
                onError?.invoke(t.message ?: "WebSocket error")
                if (isRunning) {
                    // Reconnect after delay
                    scope.launch {
                        delay(1000)
                        if (isRunning) connectWebSocket()
                    }
                }
            }
            
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(TAG, "WebSocket closed: $reason")
                onDisconnected?.invoke()
            }
        })
    }
    
    private fun configureSession() {
        val config = JSONObject().apply {
            put("type", "session.update")
            put("session", JSONObject().apply {
                put("modalities", JSONArray().apply { put("text"); put("audio") })
                put("instructions", instructions)
                put("voice", voice)
                put("input_audio_format", "pcm16")
                put("output_audio_format", "pcm16")
                put("input_audio_transcription", JSONObject().apply {
                    put("model", "whisper-1")
                })
                put("turn_detection", JSONObject().apply {
                    put("type", "server_vad")
                    put("threshold", 0.5)
                    put("prefix_padding_ms", 300)
                    put("silence_duration_ms", 500)  // Fast turn detection for barging
                })
            })
        }
        
        webSocket?.send(config.toString())
        Log.d(TAG, "Session configured")
    }
    
    private fun startAudioStreaming() {
        // Start capture (mic → OpenAI)
        captureJob = scope.launch {
            audioRecord?.startRecording()
            val buffer = ByteArray(BYTES_PER_CHUNK)
            
            Log.i(TAG, "Starting audio capture loop")
            
            while (isActive && isRunning) {
                val bytesRead = audioRecord?.read(buffer, 0, BYTES_PER_CHUNK) ?: -1
                
                if (bytesRead > 0) {
                    // Send immediately - no buffering for lowest latency
                    sendAudioChunk(buffer.copyOf(bytesRead))
                }
            }
        }
        
        // Start playback (OpenAI → speaker)
        playbackJob = scope.launch {
            audioTrack?.play()
            
            Log.i(TAG, "Starting audio playback loop")
            
            while (isActive && isRunning) {
                val chunk = playbackQueue.receive()
                audioTrack?.write(chunk, 0, chunk.size)
            }
        }
    }
    
    private fun sendAudioChunk(pcmData: ByteArray) {
        val base64Audio = Base64.encodeToString(pcmData, Base64.NO_WRAP)
        
        val event = JSONObject().apply {
            put("type", "input_audio_buffer.append")
            put("audio", base64Audio)
        }
        
        webSocket?.send(event.toString())
    }
    
    private fun handleServerEvent(json: String) {
        try {
            val event = JSONObject(json)
            val type = event.optString("type")
            
            when (type) {
                "response.audio.delta" -> {
                    // AI audio chunk - queue for playback immediately
                    val base64Audio = event.optString("delta")
                    if (base64Audio.isNotEmpty()) {
                        val pcmData = Base64.decode(base64Audio, Base64.DEFAULT)
                        scope.launch {
                            playbackQueue.send(pcmData)
                        }
                    }
                }
                
                "response.audio_transcript.delta" -> {
                    // Partial transcript of AI response
                    val text = event.optString("delta")
                    onTranscript?.invoke(text, false)
                }
                
                "conversation.item.input_audio_transcription.completed" -> {
                    // User's speech transcribed
                    val text = event.optString("transcript")
                    Log.d(TAG, "User said: $text")
                }
                
                "response.audio.done" -> {
                    Log.d(TAG, "AI finished speaking")
                }
                
                "input_audio_buffer.speech_started" -> {
                    // User started speaking - this enables barging!
                    Log.d(TAG, "User speech detected (barge-in)")
                }
                
                "input_audio_buffer.speech_stopped" -> {
                    Log.d(TAG, "User speech ended")
                }
                
                "error" -> {
                    val error = event.optJSONObject("error")
                    val message = error?.optString("message") ?: "Unknown error"
                    Log.e(TAG, "API error: $message")
                    onError?.invoke(message)
                }
                
                else -> {
                    Log.v(TAG, "Event: $type")
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error parsing event: ${e.message}")
        }
    }
    
    /**
     * Send a text message (for hybrid text+audio conversations)
     */
    fun sendText(text: String) {
        val event = JSONObject().apply {
            put("type", "conversation.item.create")
            put("item", JSONObject().apply {
                put("type", "message")
                put("role", "user")
                put("content", listOf(
                    JSONObject().apply {
                        put("type", "input_text")
                        put("text", text)
                    }
                ))
            })
        }
        webSocket?.send(event.toString())
        
        // Trigger response
        webSocket?.send(JSONObject().apply {
            put("type", "response.create")
        }.toString())
    }
    
    /**
     * Interrupt the AI (manual barge)
     */
    fun interrupt() {
        webSocket?.send(JSONObject().apply {
            put("type", "response.cancel")
        }.toString())
    }
}
