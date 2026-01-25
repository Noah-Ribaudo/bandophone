package com.bandophone

import android.util.Log
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import okhttp3.*
import okio.ByteString
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * WebSocket client for connecting to the Bandophone bridge on Mac.
 * Receives AI audio and sends it to AudioInjectionService.
 */
class BridgeClient(
    private val onAudioReceived: (ByteArray) -> Unit,
    private val onStatusChanged: (ConnectionStatus) -> Unit
) {
    companion object {
        private const val TAG = "BridgeClient"
        private const val RECONNECT_DELAY_MS = 3000L
    }

    enum class ConnectionStatus {
        DISCONNECTED,
        CONNECTING,
        CONNECTED,
        ERROR
    }

    private var webSocket: WebSocket? = null
    private val client = OkHttpClient.Builder()
        .pingInterval(30, TimeUnit.SECONDS)
        .build()
    
    private var serverUrl: String = ""
    private var shouldReconnect = false
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private val _status = MutableStateFlow(ConnectionStatus.DISCONNECTED)
    val status: StateFlow<ConnectionStatus> = _status

    fun connect(url: String) {
        serverUrl = url
        shouldReconnect = true
        doConnect()
    }

    private fun doConnect() {
        if (serverUrl.isEmpty()) return
        
        _status.value = ConnectionStatus.CONNECTING
        onStatusChanged(ConnectionStatus.CONNECTING)
        
        val request = Request.Builder()
            .url(serverUrl)
            .build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.d(TAG, "Connected to bridge")
                _status.value = ConnectionStatus.CONNECTED
                onStatusChanged(ConnectionStatus.CONNECTED)
                
                // Send hello
                webSocket.send(JSONObject().apply {
                    put("type", "hello")
                    put("client", "bandophone-android")
                }.toString())
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    val json = JSONObject(text)
                    when (json.optString("type")) {
                        "audio" -> {
                            // Base64 audio data
                            val audioB64 = json.getString("data")
                            val audioBytes = android.util.Base64.decode(audioB64, android.util.Base64.DEFAULT)
                            onAudioReceived(audioBytes)
                        }
                        "ping" -> {
                            webSocket.send(JSONObject().put("type", "pong").toString())
                        }
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Error parsing message: ${e.message}")
                }
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                // Binary audio data directly
                onAudioReceived(bytes.toByteArray())
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "Connection closing: $reason")
                webSocket.close(1000, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "Connection closed: $reason")
                _status.value = ConnectionStatus.DISCONNECTED
                onStatusChanged(ConnectionStatus.DISCONNECTED)
                scheduleReconnect()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "Connection failed: ${t.message}")
                _status.value = ConnectionStatus.ERROR
                onStatusChanged(ConnectionStatus.ERROR)
                scheduleReconnect()
            }
        })
    }

    private fun scheduleReconnect() {
        if (!shouldReconnect) return
        
        scope.launch {
            delay(RECONNECT_DELAY_MS)
            if (shouldReconnect) {
                Log.d(TAG, "Reconnecting...")
                doConnect()
            }
        }
    }

    fun disconnect() {
        shouldReconnect = false
        webSocket?.close(1000, "Client disconnect")
        webSocket = null
        _status.value = ConnectionStatus.DISCONNECTED
    }

    fun sendStatus(inCall: Boolean) {
        webSocket?.send(JSONObject().apply {
            put("type", "status")
            put("inCall", inCall)
        }.toString())
    }
}
