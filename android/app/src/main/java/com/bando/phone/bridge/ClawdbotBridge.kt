package com.bando.phone.bridge

import android.util.Log
import kotlinx.coroutines.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * ClawdbotBridge - RPC client for Clawdbot Gateway phone-bridge plugin
 *
 * Provides methods for:
 * - Fetching context for Realtime API session instructions
 * - Registering/ending calls
 * - Streaming transcripts
 * - Executing tools via Clawdbot
 *
 * Uses JSON-RPC 2.0 over HTTP/WebSocket to communicate with the Gateway.
 */
class ClawdbotBridge(
    private val gatewayUrl: String,
    private val authToken: String? = null
) {
    companion object {
        private const val TAG = "ClawdbotBridge"
        private const val JSON_RPC_VERSION = "2.0"
        private val JSON_MEDIA_TYPE = "application/json".toMediaType()
    }
    
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()
    
    private val requestId = AtomicInteger(1)
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    
    // WebSocket for real-time transcript streaming (optional)
    private var transcriptSocket: WebSocket? = null
    
    // Current call state
    private var currentCallId: String? = null
    
    /**
     * Test connection to the Gateway
     */
    suspend fun testConnection(): Boolean {
        return try {
            val result = callRpc("phone.status", emptyMap())
            result.optBoolean("enabled", false)
        } catch (e: Exception) {
            Log.e(TAG, "Connection test failed: ${e.message}")
            false
        }
    }
    
    /**
     * Fetch context for Realtime API session instructions
     */
    suspend fun fetchContext(
        callerNumber: String,
        direction: String = "outbound"
    ): PhoneContext {
        val params = mapOf(
            "callerNumber" to callerNumber,
            "direction" to direction
        )
        
        val result = callRpc("phone.context", params)
        
        return PhoneContext(
            systemInstructions = result.optString("systemInstructions", ""),
            userName = result.optString("userName", ""),
            userInfo = result.optString("userInfo", ""),
            dateTime = result.optString("dateTime", ""),
            isTrusted = result.optBoolean("isTrusted", false)
        )
    }
    
    /**
     * Register a new call with the Gateway
     */
    suspend fun startCall(
        callerNumber: String,
        callerName: String? = null,
        direction: String = "outbound"
    ): String {
        val params = mutableMapOf(
            "callerNumber" to callerNumber,
            "direction" to direction
        )
        if (callerName != null) {
            params["callerName"] = callerName
        }
        
        val result = callRpc("phone.call.start", params)
        val callId = result.optString("callId", "")
        
        if (callId.isNotEmpty()) {
            currentCallId = callId
            Log.i(TAG, "Call registered: $callId")
        }
        
        return callId
    }
    
    /**
     * Send a transcript entry
     */
    suspend fun sendTranscript(
        speaker: String,
        text: String,
        final: Boolean = true,
        callId: String? = null
    ) {
        val id = callId ?: currentCallId ?: return
        
        val params = mapOf(
            "callId" to id,
            "speaker" to speaker,
            "text" to text,
            "final" to final
        )
        
        try {
            callRpc("phone.transcript", params)
        } catch (e: Exception) {
            // Log but don't fail - transcript logging is best-effort
            Log.w(TAG, "Failed to send transcript: ${e.message}")
        }
    }
    
    /**
     * End the current call
     */
    suspend fun endCall(callId: String? = null): Long {
        val id = callId ?: currentCallId ?: return 0L
        
        val params = mapOf("callId" to id)
        
        return try {
            val result = callRpc("phone.call.end", params)
            currentCallId = null
            result.optLong("durationMs", 0)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to end call: ${e.message}")
            currentCallId = null
            0L
        }
    }
    
    /**
     * Execute a tool via Clawdbot
     * Returns the result as a string suitable for Realtime API function response
     */
    suspend fun executeTool(
        name: String,
        arguments: Map<String, Any>
    ): ToolResult {
        val params = mapOf(
            "name" to name,
            "arguments" to arguments
        )
        
        return try {
            val result = callRpc("phone.tool", params)
            ToolResult(
                success = true,
                result = result.optString("result", ""),
                error = null
            )
        } catch (e: Exception) {
            Log.e(TAG, "Tool execution failed: ${e.message}")
            ToolResult(
                success = false,
                result = null,
                error = e.message ?: "Tool execution failed"
            )
        }
    }
    
    /**
     * Get plugin status
     */
    suspend fun getStatus(): PluginStatus {
        val result = callRpc("phone.status", emptyMap())
        
        val calls = mutableListOf<ActiveCall>()
        val callsArray = result.optJSONArray("calls") ?: JSONArray()
        for (i in 0 until callsArray.length()) {
            val call = callsArray.getJSONObject(i)
            calls.add(ActiveCall(
                callId = call.optString("callId"),
                callerNumber = call.optString("callerNumber"),
                direction = call.optString("direction"),
                duration = call.optLong("duration"),
                transcriptCount = call.optInt("transcriptCount")
            ))
        }
        
        return PluginStatus(
            enabled = result.optBoolean("enabled"),
            activeCalls = result.optInt("activeCalls"),
            calls = calls
        )
    }
    
    /**
     * Clean up resources
     */
    fun close() {
        transcriptSocket?.close(1000, "Bridge closed")
        transcriptSocket = null
        scope.cancel()
    }
    
    /**
     * Make a JSON-RPC call to the Gateway
     */
    private suspend fun callRpc(method: String, params: Map<String, Any>): JSONObject {
        return withContext(Dispatchers.IO) {
            val request = JSONObject().apply {
                put("jsonrpc", JSON_RPC_VERSION)
                put("id", requestId.getAndIncrement())
                put("method", method)
                put("params", JSONObject(params))
            }
            
            val httpRequest = Request.Builder()
                .url("$gatewayUrl/rpc")
                .post(request.toString().toRequestBody(JSON_MEDIA_TYPE))
                .apply {
                    if (authToken != null) {
                        header("Authorization", "Bearer $authToken")
                    }
                }
                .build()
            
            val response = client.newCall(httpRequest).execute()
            
            if (!response.isSuccessful) {
                throw IOException("RPC failed: ${response.code} ${response.message}")
            }
            
            val body = response.body?.string() ?: throw IOException("Empty response")
            val json = JSONObject(body)
            
            if (json.has("error")) {
                val error = json.getJSONObject("error")
                throw IOException("RPC error: ${error.optString("message")}")
            }
            
            json.optJSONObject("result") ?: JSONObject()
        }
    }
}

/**
 * Context for phone session
 */
data class PhoneContext(
    val systemInstructions: String,
    val userName: String,
    val userInfo: String,
    val dateTime: String,
    val isTrusted: Boolean
)

/**
 * Result from tool execution
 */
data class ToolResult(
    val success: Boolean,
    val result: String?,
    val error: String?
)

/**
 * Plugin status
 */
data class PluginStatus(
    val enabled: Boolean,
    val activeCalls: Int,
    val calls: List<ActiveCall>
)

/**
 * Active call info
 */
data class ActiveCall(
    val callId: String,
    val callerNumber: String,
    val direction: String,
    val duration: Long,
    val transcriptCount: Int
)
