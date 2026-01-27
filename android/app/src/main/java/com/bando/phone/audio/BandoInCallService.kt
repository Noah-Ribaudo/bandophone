package com.bando.phone.audio

import android.telecom.Call
import android.telecom.InCallService
import android.util.Log
import com.bando.phone.bridge.ClawdbotBridge
import com.bandophone.ApiKeyManager
import kotlinx.coroutines.*

/**
 * BandoInCallService - Android InCallService that bridges calls to AI
 *
 * When registered as the default phone app, this service receives call events
 * and can handle calls using HybridRealtimeBridge (TinyALSA + OpenAI Realtime API).
 *
 * Flow:
 * 1. Call comes in or user places call
 * 2. onCallAdded() is triggered
 * 3. When call becomes ACTIVE, start HybridRealtimeBridge
 * 4. Bridge handles audio capture → OpenAI → audio playback
 * 5. When call ends, stop bridge and save transcript
 */
class BandoInCallService : InCallService() {
    
    companion object {
        private const val TAG = "BandoInCallService"
        
        // Configuration - could be moved to settings
        private const val GATEWAY_URL = "http://192.168.4.82:3000"  // Mac mini Tailscale IP
        private const val DEFAULT_VOICE = "onyx"  // Deep, authoritative male
    }
    
    private var bridge: HybridRealtimeBridge? = null
    private var clawdbotBridge: ClawdbotBridge? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    
    private var currentCall: Call? = null
    
    private val callCallback = object : Call.Callback() {
        override fun onStateChanged(call: Call, state: Int) {
            Log.i(TAG, "Call state changed: ${stateToString(state)}")
            
            when (state) {
                Call.STATE_ACTIVE -> {
                    // Call is active - start the bridge
                    startBridge(call)
                }
                Call.STATE_DISCONNECTED -> {
                    // Call ended - stop the bridge
                    stopBridge()
                    call.unregisterCallback(this)
                }
            }
        }
    }
    
    override fun onCallAdded(call: Call) {
        super.onCallAdded(call)
        Log.i(TAG, "Call added: ${call.details?.handle}")
        
        currentCall = call
        call.registerCallback(callCallback)
        
        // If it's an incoming call, we might want to answer it automatically
        // For now, let the user answer manually
        // call.answer(android.telecom.VideoProfile.STATE_AUDIO_ONLY)
    }
    
    override fun onCallRemoved(call: Call) {
        super.onCallRemoved(call)
        Log.i(TAG, "Call removed")
        
        if (call == currentCall) {
            stopBridge()
            currentCall = null
        }
    }
    
    private fun startBridge(call: Call) {
        val apiKey = ApiKeyManager.getApiKey(applicationContext)
        if (apiKey == null) {
            Log.e(TAG, "No OpenAI API key configured - cannot start bridge")
            return
        }
        
        // Get caller info
        val handle = call.details?.handle?.schemeSpecificPart ?: "unknown"
        val callerName = call.details?.callerDisplayName
        val direction = if (call.details?.callDirection == Call.Details.DIRECTION_INCOMING) {
            "inbound"
        } else {
            "outbound"
        }
        
        Log.i(TAG, "Starting bridge for $direction call with $handle")
        
        // Initialize Clawdbot bridge
        clawdbotBridge = ClawdbotBridge(GATEWAY_URL)
        
        // Create and start the hybrid bridge
        bridge = HybridRealtimeBridge(
            apiKey = apiKey,
            clawdbotBridge = clawdbotBridge,
            callerNumber = handle,
            callerName = callerName,
            direction = direction,
            voice = DEFAULT_VOICE
        ).apply {
            // Set up callbacks
            onConnected = {
                Log.i(TAG, "Bridge connected to OpenAI")
            }
            
            onDisconnected = {
                Log.i(TAG, "Bridge disconnected")
            }
            
            onTranscript = { text, isFinal ->
                if (isFinal) {
                    Log.d(TAG, "AI: $text")
                }
            }
            
            onUserTranscript = { text, isFinal ->
                if (isFinal) {
                    Log.d(TAG, "Caller: $text")
                }
            }
            
            onError = { error ->
                Log.e(TAG, "Bridge error: $error")
            }
            
            onContextLoaded = { context ->
                Log.i(TAG, "Loaded context for ${context.userName}")
            }
        }
        
        bridge?.start()
    }
    
    private fun stopBridge() {
        Log.i(TAG, "Stopping bridge")
        
        bridge?.stop()
        bridge = null
        
        clawdbotBridge?.close()
        clawdbotBridge = null
    }
    
    override fun onDestroy() {
        super.onDestroy()
        stopBridge()
        scope.cancel()
    }
    
    private fun stateToString(state: Int): String {
        return when (state) {
            Call.STATE_NEW -> "NEW"
            Call.STATE_DIALING -> "DIALING"
            Call.STATE_RINGING -> "RINGING"
            Call.STATE_HOLDING -> "HOLDING"
            Call.STATE_ACTIVE -> "ACTIVE"
            Call.STATE_DISCONNECTED -> "DISCONNECTED"
            Call.STATE_CONNECTING -> "CONNECTING"
            Call.STATE_DISCONNECTING -> "DISCONNECTING"
            Call.STATE_SELECT_PHONE_ACCOUNT -> "SELECT_PHONE_ACCOUNT"
            Call.STATE_SIMULATED_RINGING -> "SIMULATED_RINGING"
            Call.STATE_AUDIO_PROCESSING -> "AUDIO_PROCESSING"
            else -> "UNKNOWN($state)"
        }
    }
}
