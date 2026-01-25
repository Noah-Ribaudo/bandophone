package com.bandophone

import android.app.*
import android.content.Intent
import android.media.*
import android.os.IBinder
import android.util.Log
import java.io.InputStream
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread

/**
 * Foreground service that accepts PCM audio over a socket and plays it
 * into the active phone call using AudioTrack with VOICE_COMMUNICATION usage.
 */
class AudioInjectionService : Service() {

    companion object {
        const val TAG = "AudioInjection"
        const val PORT = 9999
        const val SAMPLE_RATE = 48000
        const val CHANNEL_CONFIG = AudioFormat.CHANNEL_OUT_MONO
        const val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT
        const val NOTIFICATION_ID = 1
        const val CHANNEL_ID = "bandophone_audio"
    }

    private var serverSocket: ServerSocket? = null
    private var audioTrack: AudioTrack? = null
    private var isRunning = false

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        Log.i(TAG, "Service created")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(NOTIFICATION_ID, createNotification())
        
        if (!isRunning) {
            isRunning = true
            startServer()
        }
        
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        isRunning = false
        serverSocket?.close()
        audioTrack?.stop()
        audioTrack?.release()
        Log.i(TAG, "Service destroyed")
        super.onDestroy()
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Audio Injection",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "Bandophone audio injection service"
        }
        
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(channel)
    }

    private fun createNotification(): Notification {
        val intent = Intent(this, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            this, 0, intent, PendingIntent.FLAG_IMMUTABLE
        )

        return Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("Bandophone Active")
            .setContentText("Listening for audio on port $PORT")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentIntent(pendingIntent)
            .build()
    }

    private fun startServer() {
        thread {
            try {
                serverSocket = ServerSocket(PORT)
                Log.i(TAG, "Server listening on port $PORT")

                while (isRunning) {
                    try {
                        val client = serverSocket?.accept() ?: break
                        Log.i(TAG, "Client connected from ${client.inetAddress}")
                        handleClient(client)
                    } catch (e: Exception) {
                        if (isRunning) {
                            Log.e(TAG, "Error accepting client", e)
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Server error", e)
            }
        }
    }

    private fun handleClient(client: Socket) {
        thread {
            try {
                val inputStream = client.getInputStream()
                initAudioTrack()
                audioTrack?.play()
                
                Log.i(TAG, "Playing audio...")
                streamAudio(inputStream)
                
            } catch (e: Exception) {
                Log.e(TAG, "Error handling client", e)
            } finally {
                audioTrack?.stop()
                client.close()
                Log.i(TAG, "Client disconnected")
            }
        }
    }

    private fun initAudioTrack() {
        val bufferSize = AudioTrack.getMinBufferSize(
            SAMPLE_RATE, CHANNEL_CONFIG, AUDIO_FORMAT
        ) * 2

        audioTrack = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setSampleRate(SAMPLE_RATE)
                    .setChannelMask(CHANNEL_CONFIG)
                    .setEncoding(AUDIO_FORMAT)
                    .build()
            )
            .setBufferSizeInBytes(bufferSize)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()

        Log.i(TAG, "AudioTrack initialized: buffer=$bufferSize")
    }

    private fun streamAudio(input: InputStream) {
        val buffer = ByteArray(4096)
        var bytesRead: Int

        while (isRunning) {
            bytesRead = input.read(buffer)
            if (bytesRead == -1) break
            
            audioTrack?.write(buffer, 0, bytesRead)
        }
    }
}
