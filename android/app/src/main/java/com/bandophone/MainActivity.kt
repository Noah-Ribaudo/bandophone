package com.bandophone

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import android.app.Activity
import android.util.Log
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

/**
 * Simple UI to start/stop the audio injection service and show status.
 */
class MainActivity : Activity() {

    companion object {
        const val TAG = "Bandophone"
        const val PERMISSION_REQUEST_CODE = 100
    }

    private var isServiceRunning = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // Simple programmatic layout (no XML needed for basic testing)
        val layout = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            setPadding(48, 48, 48, 48)
        }

        val title = TextView(this).apply {
            text = "🦝 Bandophone"
            textSize = 32f
            setPadding(0, 0, 0, 32)
        }

        val status = TextView(this).apply {
            text = "Status: Stopped"
            textSize = 18f
            setPadding(0, 0, 0, 32)
        }

        val toggleButton = Button(this).apply {
            text = "Start Service"
            setOnClickListener {
                if (checkPermissions()) {
                    toggleService(status, this)
                }
            }
        }

        val infoText = TextView(this).apply {
            text = """
                Audio Injection Service
                
                When running, listens on port 9999 for PCM audio data
                and plays it using AudioTrack with VOICE_COMMUNICATION.
                
                Format: 48kHz, 16-bit, mono
                
                Test with:
                nc localhost 9999 < audio.raw
            """.trimIndent()
            textSize = 14f
            setPadding(0, 32, 0, 0)
        }

        layout.addView(title)
        layout.addView(status)
        layout.addView(toggleButton)
        layout.addView(infoText)

        setContentView(layout)
    }

    private fun checkPermissions(): Boolean {
        val permissions = arrayOf(
            Manifest.permission.READ_PHONE_STATE,
            Manifest.permission.RECORD_AUDIO,
            Manifest.permission.MODIFY_AUDIO_SETTINGS
        )

        val needed = permissions.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (needed.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, needed.toTypedArray(), PERMISSION_REQUEST_CODE)
            return false
        }

        return true
    }

    private fun toggleService(status: TextView, button: Button) {
        val serviceIntent = Intent(this, AudioInjectionService::class.java)

        if (isServiceRunning) {
            stopService(serviceIntent)
            status.text = "Status: Stopped"
            button.text = "Start Service"
            isServiceRunning = false
            Log.i(TAG, "Service stopped")
        } else {
            startForegroundService(serviceIntent)
            status.text = "Status: Running (port 9999)"
            button.text = "Stop Service"
            isServiceRunning = true
            Log.i(TAG, "Service started")
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        
        if (requestCode == PERMISSION_REQUEST_CODE) {
            if (grantResults.all { it == PackageManager.PERMISSION_GRANTED }) {
                Log.i(TAG, "All permissions granted")
            } else {
                Log.w(TAG, "Some permissions denied")
            }
        }
    }
}
