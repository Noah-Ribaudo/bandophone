package com.bandophone

import android.app.*
import android.content.Context
import android.content.Intent
import android.media.*
import android.os.Build
import android.os.IBinder
import android.telecom.TelecomManager
import android.util.Log
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.*
import java.util.concurrent.LinkedBlockingQueue

/**
 * Foreground service that injects AI audio into active phone calls.
 * 
 * Uses AudioRecord (VOICE_COMMUNICATION) replacement strategy:
 * When a call is active, we can inject audio that appears to come from the mic.
 */
class AudioInjectionService : Service() {
    companion object {
        private const val TAG = "AudioInjection"
        private const val NOTIFICATION_ID = 1001
        private const val CHANNEL_ID = "bandophone_service"
        
        const val ACTION_START = "com.bandophone.START"
        const val ACTION_STOP = "com.bandophone.STOP"
        const val EXTRA_BRIDGE_URL = "bridge_url"
        
        private const val SAMPLE_RATE = 48000
        private const val CHANNEL_CONFIG = AudioFormat.CHANNEL_OUT_MONO
        private const val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT
    }

    private var audioTrack: AudioTrack? = null
    private var bridgeClient: BridgeClient? = null
    private val audioQueue = LinkedBlockingQueue<ByteArray>()
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var playbackJob: Job? = null
    private var isRunning = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                val bridgeUrl = intent.getStringExtra(EXTRA_BRIDGE_URL) ?: "ws://192.168.1.100:8765"
                start(bridgeUrl)
            }
            ACTION_STOP -> stop()
        }
        return START_STICKY
    }

    private fun start(bridgeUrl: String) {
        if (isRunning) return
        isRunning = true
        
        Log.d(TAG, "Starting audio injection service, bridge: $bridgeUrl")
        
        // Start foreground
        startForeground(NOTIFICATION_ID, createNotification("Connecting..."))
        
        // Initialize AudioTrack for call audio injection
        initAudioTrack()
        
        // Connect to bridge
        bridgeClient = BridgeClient(
            onAudioReceived = { audioData ->
                // Queue audio for playback
                audioQueue.offer(audioData)
            },
            onStatusChanged = { status ->
                updateNotification(status.name)
            }
        )
        bridgeClient?.connect(bridgeUrl)
        
        // Start playback loop
        startPlaybackLoop()
    }

    private fun initAudioTrack() {
        val bufferSize = AudioTrack.getMinBufferSize(SAMPLE_RATE, CHANNEL_CONFIG, AUDIO_FORMAT)
        
        audioTrack = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setEncoding(AUDIO_FORMAT)
                        .setSampleRate(SAMPLE_RATE)
                        .setChannelMask(CHANNEL_CONFIG)
                        .build()
                )
                .setBufferSizeInBytes(bufferSize * 2)
                .setTransferMode(AudioTrack.MODE_STREAM)
                .build()
        } else {
            @Suppress("DEPRECATION")
            AudioTrack(
                AudioManager.STREAM_VOICE_CALL,
                SAMPLE_RATE,
                CHANNEL_CONFIG,
                AUDIO_FORMAT,
                bufferSize * 2,
                AudioTrack.MODE_STREAM
            )
        }
        
        audioTrack?.play()
        Log.d(TAG, "AudioTrack initialized")
    }

    private fun startPlaybackLoop() {
        playbackJob = scope.launch {
            while (isActive && isRunning) {
                try {
                    val audioData = audioQueue.poll()
                    if (audioData != null) {
                        audioTrack?.write(audioData, 0, audioData.size)
                    } else {
                        delay(10)
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Playback error: ${e.message}")
                }
            }
        }
    }

    private fun stop() {
        Log.d(TAG, "Stopping audio injection service")
        isRunning = false
        
        playbackJob?.cancel()
        bridgeClient?.disconnect()
        
        audioTrack?.stop()
        audioTrack?.release()
        audioTrack = null
        
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        stop()
        scope.cancel()
        super.onDestroy()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Bandophone Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Voice bridge active"
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    private fun createNotification(status: String): Notification {
        val stopIntent = Intent(this, AudioInjectionService::class.java).apply {
            action = ACTION_STOP
        }
        val stopPendingIntent = PendingIntent.getService(
            this, 0, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Bandophone")
            .setContentText(status)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .addAction(android.R.drawable.ic_media_pause, "Stop", stopPendingIntent)
            .setOngoing(true)
            .build()
    }

    private fun updateNotification(status: String) {
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, createNotification(status))
    }
}
