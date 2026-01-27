package com.bando.phone.audio

import android.util.Base64
import android.util.Log
import com.bando.phone.bridge.ClawdbotBridge
import com.bando.phone.bridge.PhoneContext
import com.bando.phone.bridge.ToolResult
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import okhttp3.*
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * HybridRealtimeBridge - TinyALSA capture + OpenAI Realtime API + Clawdbot Integration
 * 
 * Uses process-based TinyALSA for capturing far-end call audio (what the other party says)
 * while streaming to OpenAI Realtime API for full VAD, barging, and low-latency features.
 * 
 * Clawdbot integration:
 * - Fetches context (memories, calendar, user info) at call start
 * - Streams transcripts to Gateway for logging
 * - Bridges function calls to Clawdbot tools
 * 
 * Audio flow:
 * - Capture: TinyALSA device 20 (48kHz stereo) → convert → 24kHz mono → WebSocket → OpenAI
 * - Playback: OpenAI → WebSocket → 24kHz mono → convert → TinyALSA device 19 (48kHz stereo)
 */
class HybridRealtimeBridge(
    private val apiKey: String,
    private val clawdbotBridge: ClawdbotBridge? = null,
    private val callerNumber: String = "unknown",
    private val callerName: String? = null,
    private val direction: String = "outbound",
    private var instructions: String = "You are a helpful assistant on a phone call.",
    private val voice: String = "alloy"
) {
    companion object {
        private const val TAG = "HybridRealtimeBridge"
        private const val REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-17"
    }
    
    private var webSocket: WebSocket? = null
    private val tinyALSA = TinyALSAStreamer()
    
    private val playbackQueue = Channel<ByteArray>(Channel.UNLIMITED)
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    
    private var isRunning = false
    
    // Clawdbot integration state
    private var callId: String? = null
    private var phoneContext: PhoneContext? = null
    
    // Callbacks
    var onTranscript: ((String, Boolean) -> Unit)? = null
    var onUserTranscript: ((String, Boolean) -> Unit)? = null
    var onError: ((String) -> Unit)? = null
    var onConnected: (() -> Unit)? = null
    var onDisconnected: (() -> Unit)? = null
    var onSpeechStarted: (() -> Unit)? = null
    var onSpeechEnded: (() -> Unit)? = null
    var onContextLoaded: ((PhoneContext) -> Unit)? = null
    
    /**
     * Start the hybrid bridge
     */
    fun start() {
        if (isRunning) return
        isRunning = true
        
        Log.i(TAG, "Starting HybridRealtimeBridge")
        
        // Set up TinyALSA mixer for AI call mode
        if (!tinyALSA.setupMixer()) {
            onError?.invoke("Failed to configure audio mixer")
            return
        }
        
        // Set up capture callback - audio from far-end goes to OpenAI
        tinyALSA.onAudioCaptured = { audioData ->
            sendAudioChunk(audioData)
        }
        
        tinyALSA.onError = { error ->
            Log.e(TAG, "TinyALSA error: $error")
            onError?.invoke(error)
        }
        
        // Initialize Clawdbot integration (async, non-blocking)
        scope.launch {
            initClawdbotIntegration()
        }
        
        // Connect to OpenAI first, then start audio streaming
        connectWebSocket()
    }
    
    /**
     * Initialize Clawdbot integration - fetch context and register call
     */
    private suspend fun initClawdbotIntegration() {
        val bridge = clawdbotBridge ?: return
        
        try {
            // Fetch context for session instructions
            Log.i(TAG, "Fetching Clawdbot context...")
            val context = bridge.fetchContext(callerNumber, direction)
            phoneContext = context
            
            // Update instructions if we got context
            if (context.systemInstructions.isNotEmpty()) {
                instructions = context.systemInstructions
                Log.i(TAG, "Loaded context for ${context.userName}")
                onContextLoaded?.invoke(context)
                
                // Update session if already connected
                webSocket?.let { updateSessionInstructions() }
            }
            
            // Register the call
            val id = bridge.startCall(callerNumber, callerName, direction)
            if (id.isNotEmpty()) {
                callId = id
                Log.i(TAG, "Call registered with Gateway: $id")
            }
        } catch (e: Exception) {
            // Non-fatal - continue without Clawdbot integration
            Log.w(TAG, "Clawdbot integration failed (continuing anyway): ${e.message}")
        }
    }
    
    /**
     * Update session instructions after context is loaded
     */
    private fun updateSessionInstructions() {
        val config = JSONObject().apply {
            put("type", "session.update")
            put("session", JSONObject().apply {
                put("instructions", instructions)
            })
        }
        webSocket?.send(config.toString())
        Log.d(TAG, "Updated session instructions with Clawdbot context")
    }
    
    /**
     * Stop the bridge
     */
    fun stop() {
        if (!isRunning) return
        isRunning = false
        
        Log.i(TAG, "Stopping HybridRealtimeBridge")
        
        tinyALSA.stop()
        tinyALSA.resetMixer()
        
        webSocket?.close(1000, "Call ended")
        webSocket = null
        
        // End call with Clawdbot (save transcript)
        val bridge = clawdbotBridge
        val id = callId
        if (bridge != null && id != null) {
            // Use a new scope since we're canceling the main one
            CoroutineScope(Dispatchers.IO).launch {
                try {
                    val duration = bridge.endCall(id)
                    Log.i(TAG, "Call ended with Gateway, duration: ${duration}ms")
                } catch (e: Exception) {
                    Log.w(TAG, "Failed to end call with Gateway: ${e.message}")
                }
            }
        }
        callId = null
        
        scope.cancel()
        
        onDisconnected?.invoke()
    }
    
    /**
     * Stream transcript to Clawdbot (async, non-blocking)
     */
    private fun streamTranscriptToClawdbot(speaker: String, text: String, isFinal: Boolean) {
        val bridge = clawdbotBridge ?: return
        val id = callId ?: return
        
        scope.launch {
            try {
                bridge.sendTranscript(speaker, text, isFinal, id)
            } catch (e: Exception) {
                // Silently ignore - transcript logging is best-effort
                Log.v(TAG, "Transcript send failed: ${e.message}")
            }
        }
    }
    
    private fun connectWebSocket() {
        val client = OkHttpClient.Builder()
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .build()
        
        val request = Request.Builder()
            .url(REALTIME_URL)
            .header("Authorization", "Bearer $apiKey")
            .header("OpenAI-Beta", "realtime=v1")
            .build()
        
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.i(TAG, "WebSocket connected to OpenAI")
                configureSession()
                
                // Start TinyALSA streaming now that WebSocket is ready
                tinyALSA.startCapture()
                tinyALSA.startPlayback()
                
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
                        delay(2000)
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
                    put("silence_duration_ms", 500)
                })
                // Add tools if Clawdbot is connected
                if (clawdbotBridge != null) {
                    put("tools", buildPhoneTools())
                }
            })
        }
        
        webSocket?.send(config.toString())
        Log.d(TAG, "Session configured with voice=$voice, tools=${clawdbotBridge != null}")
    }
    
    /**
     * Build tool definitions for Realtime API
     * These are bridged to Clawdbot for execution
     */
    private fun buildPhoneTools(): JSONArray {
        return JSONArray().apply {
            // Calendar
            put(JSONObject().apply {
                put("type", "function")
                put("name", "get_calendar")
                put("description", "Get calendar events for today or a specific date range")
                put("parameters", JSONObject().apply {
                    put("type", "object")
                    put("properties", JSONObject().apply {
                        put("start_date", JSONObject().apply {
                            put("type", "string")
                            put("description", "Start date (YYYY-MM-DD), defaults to today")
                        })
                        put("end_date", JSONObject().apply {
                            put("type", "string")
                            put("description", "End date (YYYY-MM-DD), defaults to start_date")
                        })
                    })
                    put("required", JSONArray())
                })
            })
            
            // Reminders
            put(JSONObject().apply {
                put("type", "function")
                put("name", "create_reminder")
                put("description", "Create a reminder for later")
                put("parameters", JSONObject().apply {
                    put("type", "object")
                    put("properties", JSONObject().apply {
                        put("text", JSONObject().apply {
                            put("type", "string")
                            put("description", "What to remind about")
                        })
                        put("time", JSONObject().apply {
                            put("type", "string")
                            put("description", "When to remind (e.g., 'in 30 minutes', 'at 3pm', 'tomorrow morning')")
                        })
                    })
                    put("required", JSONArray().apply { put("text"); put("time") })
                })
            })
            
            // Weather
            put(JSONObject().apply {
                put("type", "function")
                put("name", "get_weather")
                put("description", "Get current weather or forecast")
                put("parameters", JSONObject().apply {
                    put("type", "object")
                    put("properties", JSONObject().apply {
                        put("location", JSONObject().apply {
                            put("type", "string")
                            put("description", "Location (defaults to user's location)")
                        })
                    })
                    put("required", JSONArray())
                })
            })
            
            // Lights
            put(JSONObject().apply {
                put("type", "function")
                put("name", "control_lights")
                put("description", "Control smart home lights")
                put("parameters", JSONObject().apply {
                    put("type", "object")
                    put("properties", JSONObject().apply {
                        put("action", JSONObject().apply {
                            put("type", "string")
                            put("enum", JSONArray().apply { put("on"); put("off"); put("dim") })
                            put("description", "What to do with the lights")
                        })
                        put("room", JSONObject().apply {
                            put("type", "string")
                            put("description", "Which room or 'all' for all lights")
                        })
                        put("brightness", JSONObject().apply {
                            put("type", "number")
                            put("description", "Brightness level 0-100 (for dim action)")
                        })
                    })
                    put("required", JSONArray().apply { put("action") })
                })
            })
            
            // Send message
            put(JSONObject().apply {
                put("type", "function")
                put("name", "send_message")
                put("description", "Send a text message to someone")
                put("parameters", JSONObject().apply {
                    put("type", "object")
                    put("properties", JSONObject().apply {
                        put("to", JSONObject().apply {
                            put("type", "string")
                            put("description", "Recipient name or phone number")
                        })
                        put("message", JSONObject().apply {
                            put("type", "string")
                            put("description", "Message to send")
                        })
                    })
                    put("required", JSONArray().apply { put("to"); put("message") })
                })
            })
            
            // Get current time
            put(JSONObject().apply {
                put("type", "function")
                put("name", "get_time")
                put("description", "Get the current time and date")
                put("parameters", JSONObject().apply {
                    put("type", "object")
                    put("properties", JSONObject())
                    put("required", JSONArray())
                })
            })
            
            // Web search
            put(JSONObject().apply {
                put("type", "function")
                put("name", "search_web")
                put("description", "Search the web for information")
                put("parameters", JSONObject().apply {
                    put("type", "object")
                    put("properties", JSONObject().apply {
                        put("query", JSONObject().apply {
                            put("type", "string")
                            put("description", "What to search for")
                        })
                    })
                    put("required", JSONArray().apply { put("query") })
                })
            })
        }
    }
    
    /**
     * Send captured audio to OpenAI
     */
    private fun sendAudioChunk(pcmData: ByteArray) {
        if (!isRunning || webSocket == null) return
        
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
                    // AI audio chunk - queue for playback
                    val base64Audio = event.optString("delta")
                    if (base64Audio.isNotEmpty()) {
                        val pcmData = Base64.decode(base64Audio, Base64.DEFAULT)
                        Log.d(TAG, "Received AI audio chunk: ${pcmData.size} bytes")
                        scope.launch {
                            tinyALSA.queuePlayback(pcmData)
                        }
                    }
                }
                
                "response.audio_transcript.delta" -> {
                    val text = event.optString("delta")
                    onTranscript?.invoke(text, false)
                }
                
                "response.audio_transcript.done" -> {
                    val text = event.optString("transcript")
                    Log.d(TAG, "AI said: $text")
                    onTranscript?.invoke(text, true)
                    // Stream to Clawdbot
                    if (text.isNotEmpty()) {
                        streamTranscriptToClawdbot("assistant", text, true)
                    }
                }
                
                "conversation.item.input_audio_transcription.completed" -> {
                    val text = event.optString("transcript")
                    Log.d(TAG, "User (far-end) said: $text")
                    onUserTranscript?.invoke(text, true)
                    // Stream to Clawdbot
                    if (text.isNotEmpty()) {
                        streamTranscriptToClawdbot("user", text, true)
                    }
                }
                
                "input_audio_buffer.speech_started" -> {
                    Log.d(TAG, "Far-end speech detected - barging enabled")
                    onSpeechStarted?.invoke()
                }
                
                "input_audio_buffer.speech_stopped" -> {
                    Log.d(TAG, "Far-end speech ended")
                    onSpeechEnded?.invoke()
                }
                
                "response.audio.done" -> {
                    Log.d(TAG, "AI finished speaking")
                }
                
                "response.function_call_arguments.done" -> {
                    // Function call from AI - bridge to Clawdbot
                    val callId = event.optString("call_id")
                    val name = event.optString("name")
                    val arguments = event.optString("arguments")
                    
                    Log.i(TAG, "Function call: $name($arguments)")
                    handleFunctionCall(callId, name, arguments)
                }
                
                "error" -> {
                    val error = event.optJSONObject("error")
                    val message = error?.optString("message") ?: "Unknown error"
                    Log.e(TAG, "API error: $message")
                    onError?.invoke(message)
                }
                
                "session.created", "session.updated" -> {
                    Log.v(TAG, "Session event: $type")
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
     * Handle function call from Realtime API - bridge to Clawdbot
     */
    private fun handleFunctionCall(callId: String, name: String, argumentsJson: String) {
        val bridge = clawdbotBridge
        if (bridge == null) {
            // No Clawdbot - return error
            sendFunctionResult(callId, "Tool execution unavailable - Clawdbot not connected")
            return
        }
        
        scope.launch {
            try {
                // Parse arguments
                val args = try {
                    val json = JSONObject(argumentsJson)
                    val map = mutableMapOf<String, Any>()
                    json.keys().forEach { key ->
                        map[key] = json.get(key)
                    }
                    map
                } catch (e: Exception) {
                    emptyMap<String, Any>()
                }
                
                // Execute via Clawdbot
                val result = bridge.executeTool(name, args)
                
                if (result.success && result.result != null) {
                    sendFunctionResult(callId, result.result)
                } else {
                    sendFunctionResult(callId, result.error ?: "Tool execution failed")
                }
            } catch (e: Exception) {
                Log.e(TAG, "Function call error: ${e.message}")
                sendFunctionResult(callId, "Error: ${e.message}")
            }
        }
    }
    
    /**
     * Send function result back to Realtime API
     */
    private fun sendFunctionResult(callId: String, result: String) {
        // Create function output item
        val outputEvent = JSONObject().apply {
            put("type", "conversation.item.create")
            put("item", JSONObject().apply {
                put("type", "function_call_output")
                put("call_id", callId)
                put("output", result)
            })
        }
        webSocket?.send(outputEvent.toString())
        
        // Trigger response generation
        val responseEvent = JSONObject().apply {
            put("type", "response.create")
        }
        webSocket?.send(responseEvent.toString())
        
        Log.d(TAG, "Sent function result for $callId")
    }
    
    /**
     * Send a text message to the AI
     */
    fun sendText(text: String) {
        val event = JSONObject().apply {
            put("type", "conversation.item.create")
            put("item", JSONObject().apply {
                put("type", "message")
                put("role", "user")
                put("content", JSONArray().apply {
                    put(JSONObject().apply {
                        put("type", "input_text")
                        put("text", text)
                    })
                })
            })
        }
        webSocket?.send(event.toString())
        
        // Trigger response
        webSocket?.send(JSONObject().apply {
            put("type", "response.create")
        }.toString())
    }
    
    /**
     * Manually interrupt the AI
     */
    fun interrupt() {
        webSocket?.send(JSONObject().apply {
            put("type", "response.cancel")
        }.toString())
    }
}
