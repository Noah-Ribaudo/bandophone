package com.bando.phone.audio

import android.util.Log
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * TinyALSAStreamer - Process-based streaming capture/playback via TinyALSA
 *
 * Uses su + tinycap/tinyplay binaries for direct ALSA access on rooted device.
 * This is Option B from the architecture review - faster to implement than JNI,
 * with acceptable latency overhead (~30-80ms).
 */
class TinyALSAStreamer {
    companion object {
        private const val TAG = "TinyALSAStreamer"

        // TinyALSA binary paths
        private const val TINYCAP = "/data/local/tmp/tinycap"
        private const val TINYPLAY = "/data/local/tmp/tinyplay"
        private const val TINYMIX = "/data/local/tmp/tinymix"

        // Audio parameters
        private const val CARD = 0
        private const val CAPTURE_DEVICE = 20  // Far-end audio (what remote party says)
        private const val PLAYBACK_DEVICE = 19 // Injection into call (what AI says)

        private const val NATIVE_RATE = 48000
        private const val NATIVE_CHANNELS = 2
        private const val TARGET_RATE = 24000  // Realtime API format
        private const val TARGET_CHANNELS = 1

        // Buffer size: 20ms of audio at 48kHz stereo = 3840 bytes
        private const val CAPTURE_BUFFER_SIZE = 3840

        // Mixer controls (Pixel 7 Pro specific)
        private const val MIC_MUTE_CONTROL = 167
        private const val CAPTURE_ROUTE_CONTROL = 152
    }

    private var captureProcess: Process? = null
    private var playbackProcess: Process? = null
    private var playbackWriter: java.io.OutputStream? = null
    private var captureJob: Job? = null
    private var playbackJob: Job? = null

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val playbackQueue = Channel<ByteArray>(Channel.UNLIMITED)

    private var isRunning = false
    private var playbackReady = false

    // FIFO for continuous playback
    private val PLAYBACK_FIFO = "/data/local/tmp/playback_fifo"

    // Callbacks
    var onAudioCaptured: ((ByteArray) -> Unit)? = null
    var onError: ((String) -> Unit)? = null

    // Simple low-pass filter state for proper decimation
    private val filterState = FloatArray(8) // FIR filter delay line

    /**
     * Set up mixer for AI call mode
     */
    fun setupMixer(): Boolean {
        return try {
            // Mute local mic so user's voice doesn't go through
            executeCommand("$TINYMIX -D $CARD set $MIC_MUTE_CONTROL 1")

            // Enable capture routing for far-end audio
            executeCommand("$TINYMIX -D $CARD set $CAPTURE_ROUTE_CONTROL DL")

            Log.i(TAG, "Mixer configured for AI call mode")
            true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to configure mixer: ${e.message}")
            onError?.invoke("Mixer setup failed: ${e.message}")
            false
        }
    }

    /**
     * Reset mixer to normal mode
     */
    fun resetMixer() {
        try {
            executeCommand("$TINYMIX -D $CARD set $MIC_MUTE_CONTROL 0")
            Log.i(TAG, "Mixer reset to normal mode")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to reset mixer: ${e.message}")
        }
    }

    /**
     * Start capturing far-end audio and streaming via callback
     */
    fun startCapture() {
        if (isRunning) return
        isRunning = true

        captureJob = scope.launch {
            try {
                Log.i(TAG, "Starting TinyALSA capture process")

                // Start tinycap with stdout output (--)
                // -p 480 = 10ms period at 48kHz
                // -n 4 = 4 periods buffer
                val cmd = arrayOf(
                    "su", "-c",
                    "$TINYCAP -- -D $CARD -d $CAPTURE_DEVICE -c $NATIVE_CHANNELS -r $NATIVE_RATE -b 16 -p 480 -n 4"
                )

                captureProcess = Runtime.getRuntime().exec(cmd)
                val inputStream = captureProcess!!.inputStream

                Log.i(TAG, "Capture process started, reading audio stream")

                val buffer = ByteArray(CAPTURE_BUFFER_SIZE)

                while (isActive && isRunning) {
                    val bytesRead = inputStream.read(buffer)
                    if (bytesRead > 0) {
                        // Convert 48kHz stereo → 24kHz mono with proper filtering
                        val converted = convertAudio(buffer, bytesRead)
                        onAudioCaptured?.invoke(converted)
                    } else if (bytesRead < 0) {
                        Log.w(TAG, "Capture stream ended")
                        break
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Capture error: ${e.message}")
                onError?.invoke("Capture error: ${e.message}")
            } finally {
                captureProcess?.destroy()
                captureProcess = null
            }
        }
    }

    /**
     * Start playback process for injecting AI audio into call
     * Uses a persistent tinyplay process with FIFO for low latency
     */
    fun startPlayback() {
        playbackJob = scope.launch {
            try {
                Log.i(TAG, "Starting persistent TinyALSA playback")

                // Create FIFO
                executeCommand("rm -f $PLAYBACK_FIFO && mkfifo $PLAYBACK_FIFO")
                Log.d(TAG, "Created playback FIFO")

                // Start persistent tinyplay reading from FIFO
                // Run in background so we can write to FIFO
                val playCmd = arrayOf(
                    "su", "-c",
                    "$TINYPLAY $PLAYBACK_FIFO -D $CARD -d $PLAYBACK_DEVICE -c 2 -r 48000 -b 16"
                )
                playbackProcess = Runtime.getRuntime().exec(playCmd)
                Log.d(TAG, "Started persistent tinyplay process")

                // Small delay to let tinyplay open the FIFO for reading
                delay(100)

                // Open FIFO for writing
                val fifoWriteProcess = Runtime.getRuntime().exec(arrayOf(
                    "su", "-c", "cat > $PLAYBACK_FIFO"
                ))
                playbackWriter = fifoWriteProcess.outputStream
                playbackReady = true
                Log.i(TAG, "Playback FIFO ready for streaming")

                // Process queue
                while (isActive && isRunning) {
                    val audioData = playbackQueue.receive()
                    val converted = convertForPlayback(audioData)

                    playbackWriter?.write(converted)
                    playbackWriter?.flush()
                    Log.v(TAG, "Wrote ${converted.size} bytes to FIFO")
                }
            } catch (e: Exception) {
                if (isRunning) {
                    Log.e(TAG, "Playback error: ${e.message}")
                    onError?.invoke("Playback error: ${e.message}")
                }
            }
        }
    }

    /**
     * Queue audio for playback
     */
    suspend fun queuePlayback(audioData: ByteArray) {
        playbackQueue.send(audioData)
    }

    /**
     * Stop all streaming
     */
    fun stop() {
        isRunning = false
        playbackReady = false

        captureJob?.cancel()
        playbackJob?.cancel()

        // Close FIFO writer
        try {
            playbackWriter?.close()
        } catch (e: Exception) {
            Log.w(TAG, "Error closing playback writer: ${e.message}")
        }
        playbackWriter = null

        captureProcess?.destroy()
        playbackProcess?.destroy()

        captureProcess = null
        playbackProcess = null

        // Clean up FIFO
        try {
            Runtime.getRuntime().exec(arrayOf("su", "-c", "rm -f $PLAYBACK_FIFO"))
        } catch (e: Exception) {
            Log.w(TAG, "Error removing FIFO: ${e.message}")
        }

        Log.i(TAG, "TinyALSA streamer stopped")
    }

    /**
     * Convert 48kHz stereo S16LE → 24kHz mono S16LE
     * Uses simple averaging + decimation by 2
     * (A proper implementation would use a low-pass filter before decimation)
     */
    private fun convertAudio(input: ByteArray, length: Int): ByteArray {
        val inputBuffer = ByteBuffer.wrap(input, 0, length).order(ByteOrder.LITTLE_ENDIAN)

        // Input: 48kHz stereo = 4 bytes per sample frame
        // Output: 24kHz mono = 2 bytes per sample frame
        // Decimation factor = 2, so output is 1/4 the size
        val numInputFrames = length / 4
        val numOutputFrames = numInputFrames / 2
        val output = ByteArray(numOutputFrames * 2)
        val outputBuffer = ByteBuffer.wrap(output).order(ByteOrder.LITTLE_ENDIAN)

        // Simple approach: average pairs of stereo frames, then average L+R
        // This provides basic anti-aliasing by averaging before decimation
        var outputIdx = 0
        var inputIdx = 0

        while (inputIdx < numInputFrames - 1 && outputIdx < numOutputFrames) {
            // Read two consecutive stereo frames
            val left1 = inputBuffer.getShort(inputIdx * 4).toInt()
            val right1 = inputBuffer.getShort(inputIdx * 4 + 2).toInt()
            val left2 = inputBuffer.getShort((inputIdx + 1) * 4).toInt()
            val right2 = inputBuffer.getShort((inputIdx + 1) * 4 + 2).toInt()

            // Average all 4 samples (basic 2-tap anti-aliasing + stereo mix)
            val mono = ((left1 + right1 + left2 + right2) / 4).toShort()

            outputBuffer.putShort(outputIdx * 2, mono)

            inputIdx += 2  // Skip 2 input frames per output frame
            outputIdx++
        }

        return output
    }

    /**
     * Convert 24kHz mono S16LE → 24kHz stereo S16LE for playback
     * Simple mono→stereo duplication (no sample rate change)
     */
    private fun convertForPlayback(input: ByteArray): ByteArray {
        val inputBuffer = ByteBuffer.wrap(input).order(ByteOrder.LITTLE_ENDIAN)

        // Input: 24kHz mono = 2 bytes per sample
        // Output: 24kHz stereo = 4 bytes per sample frame (same sample count)
        val numInputSamples = input.size / 2
        val output = ByteArray(numInputSamples * 4)  // Same samples, 4 bytes each (stereo)
        val outputBuffer = ByteBuffer.wrap(output).order(ByteOrder.LITTLE_ENDIAN)

        for (i in 0 until numInputSamples) {
            val sample = inputBuffer.getShort(i * 2)

            // Output one stereo frame per input sample (duplicate L/R)
            outputBuffer.putShort(i * 4, sample)      // Left
            outputBuffer.putShort(i * 4 + 2, sample)  // Right
        }

        return output
    }

    /**
     * Execute a shell command via su
     */
    private fun executeCommand(command: String): String {
        val process = Runtime.getRuntime().exec(arrayOf("su", "-c", command))
        val output = process.inputStream.bufferedReader().readText()
        val error = process.errorStream.bufferedReader().readText()
        process.waitFor()

        if (error.isNotEmpty()) {
            Log.w(TAG, "Command stderr: $error")
        }

        return output
    }
}
