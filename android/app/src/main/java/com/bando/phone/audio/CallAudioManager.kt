package com.bando.phone.audio

import android.content.Context
import android.media.AudioManager
import android.telecom.Call
import android.telecom.InCallService
import android.util.Log

/**
 * CallAudioManager - Manages audio routing for phone calls with AI bridge
 * 
 * This integrates with Android's InCallService to:
 * 1. Detect when calls become active
 * 2. Configure audio routing for VOICE_COMMUNICATION mode
 * 3. Start/stop the RealtimeAudioBridge
 */
class CallAudioManager(
    private val context: Context,
    private val apiKey: String,
    private val instructions: String = "You are a helpful AI assistant on a phone call. Be conversational and natural.",
    private val voice: String = "alloy"
) {
    companion object {
        private const val TAG = "CallAudioManager"
    }
    
    private var audioManager: AudioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private var bridge: HybridRealtimeBridge? = null
    private var currentCall: Call? = null
    
    // Use TinyALSA hybrid approach for far-end audio capture
    private val useHybridBridge = true
    
    // Callbacks
    var onBridgeStarted: (() -> Unit)? = null
    var onBridgeStopped: (() -> Unit)? = null
    var onTranscript: ((String) -> Unit)? = null
    var onError: ((String) -> Unit)? = null
    
    /**
     * Call this when a phone call becomes active
     */
    fun onCallActive(call: Call) {
        Log.i(TAG, "Call became active, starting AI bridge")
        currentCall = call
        
        // Configure audio for voice communication
        setupAudioRouting()
        
        // Start the bridge
        startBridge()
    }
    
    /**
     * Call this when the phone call ends
     */
    fun onCallEnded() {
        Log.i(TAG, "Call ended, stopping AI bridge")
        
        stopBridge()
        resetAudioRouting()
        
        currentCall = null
    }
    
    private fun setupAudioRouting() {
        // Request audio focus for voice communication
        audioManager.mode = AudioManager.MODE_IN_COMMUNICATION
        
        // Use speaker or earpiece based on preference
        // For now, use earpiece (normal phone call experience)
        audioManager.isSpeakerphoneOn = false
        
        Log.d(TAG, "Audio routing configured for voice communication")
    }
    
    private fun resetAudioRouting() {
        audioManager.mode = AudioManager.MODE_NORMAL
        Log.d(TAG, "Audio routing reset to normal")
    }
    
    private fun startBridge() {
        Log.i(TAG, "Starting HybridRealtimeBridge (TinyALSA + Realtime API)")
        
        bridge = HybridRealtimeBridge(
            apiKey = apiKey,
            instructions = instructions,
            voice = voice
        ).apply {
            onConnected = {
                Log.i(TAG, "Bridge connected to OpenAI")
                onBridgeStarted?.invoke()
            }
            
            onDisconnected = {
                Log.i(TAG, "Bridge disconnected")
                onBridgeStopped?.invoke()
            }
            
            onTranscript = { text, isFinal ->
                if (isFinal) {
                    this@CallAudioManager.onTranscript?.invoke(text)
                }
            }
            
            onSpeechStarted = {
                Log.i(TAG, "Far-end speech detected (barging active)")
            }
            
            onSpeechEnded = {
                Log.i(TAG, "Far-end speech ended")
            }
            
            onError = { error ->
                Log.e(TAG, "Bridge error: $error")
                this@CallAudioManager.onError?.invoke(error)
            }
            
            start()
        }
    }
    
    private fun stopBridge() {
        bridge?.stop()
        bridge = null
    }
    
    /**
     * Send a text prompt to the AI (useful for initial greeting)
     */
    fun sendPrompt(text: String) {
        bridge?.sendText(text)
    }
    
    /**
     * Manually interrupt the AI
     */
    fun interruptAI() {
        bridge?.interrupt()
    }
}


/**
 * BandoInCallService - Android InCallService that integrates AI audio
 * 
 * Register this in AndroidManifest.xml:
 * 
 * <service
 *     android:name=".audio.BandoInCallService"
 *     android:permission="android.permission.BIND_INCALL_SERVICE"
 *     android:exported="true">
 *     <meta-data
 *         android:name="android.telecom.IN_CALL_SERVICE_UI"
 *         android:value="true" />
 *     <intent-filter>
 *         <action android:name="android.telecom.InCallService" />
 *     </intent-filter>
 * </service>
 */
class BandoInCallService : InCallService() {
    companion object {
        private const val TAG = "BandoInCallService"
    }
    
    private var callAudioManager: CallAudioManager? = null
    
    private val callCallback = object : Call.Callback() {
        override fun onStateChanged(call: Call, state: Int) {
            Log.d(TAG, "Call state changed: $state")
            
            when (state) {
                Call.STATE_ACTIVE -> {
                    // Call is connected and active
                    callAudioManager?.onCallActive(call)
                }
                
                Call.STATE_DISCONNECTED -> {
                    // Call ended
                    callAudioManager?.onCallEnded()
                    call.unregisterCallback(this)
                }
            }
        }
    }
    
    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "BandoInCallService created")
        
        // Get API key from secure storage
        val apiKey = com.bandophone.ApiKeyManager.getApiKey(this)
        if (apiKey.isNullOrBlank()) {
            Log.e(TAG, "No API key configured!")
            return
        }
        
        val instructions = com.bandophone.ApiKeyManager.getInstructions(this)
        val voice = com.bandophone.ApiKeyManager.getVoice(this)
        
        callAudioManager = CallAudioManager(
            context = this,
            apiKey = apiKey,
            instructions = instructions,
            voice = voice
        )
    }
    
    override fun onCallAdded(call: Call) {
        super.onCallAdded(call)
        Log.i(TAG, "Call added")
        call.registerCallback(callCallback)
        
        // If call is already active when added
        if (call.state == Call.STATE_ACTIVE) {
            callAudioManager?.onCallActive(call)
        }
    }
    
    override fun onCallRemoved(call: Call) {
        super.onCallRemoved(call)
        Log.i(TAG, "Call removed")
        callAudioManager?.onCallEnded()
    }
    
    override fun onDestroy() {
        callAudioManager?.onCallEnded()
        super.onDestroy()
    }
}
