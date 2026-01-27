package com.bandophone

import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.*
import java.util.concurrent.TimeUnit

class SettingsActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        setContent {
            MaterialTheme {
                SettingsScreen(
                    onSave = { apiKey, instructions, voice ->
                        ApiKeyManager.saveApiKey(this, apiKey)
                        ApiKeyManager.saveInstructions(this, instructions)
                        ApiKeyManager.saveVoice(this, voice)
                        Toast.makeText(this, "Settings saved!", Toast.LENGTH_SHORT).show()
                        finish()
                    },
                    onBack = { finish() }
                )
            }
        }
    }
}

sealed class ApiTestResult {
    object Idle : ApiTestResult()
    object Testing : ApiTestResult()
    data class Success(val message: String) : ApiTestResult()
    data class Error(val message: String) : ApiTestResult()
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onSave: (String, String, String) -> Unit,
    onBack: () -> Unit
) {
    var apiKey by remember {
        mutableStateOf(
            ApiKeyManager.getApiKey(BandophoneApp.instance) ?: ""
        )
    }
    var instructions by remember {
        mutableStateOf(
            ApiKeyManager.getInstructions(BandophoneApp.instance)
        )
    }
    var selectedVoice by remember {
        mutableStateOf(
            ApiKeyManager.getVoice(BandophoneApp.instance)
        )
    }
    var showApiKey by remember { mutableStateOf(false) }
    var testResult by remember { mutableStateOf<ApiTestResult>(ApiTestResult.Idle) }
    
    val scope = rememberCoroutineScope()
    
    val voices = listOf(
        "alloy" to "Alloy (Neutral)",
        "ash" to "Ash (Soft)",
        "ballad" to "Ballad (Warm)",
        "coral" to "Coral (Clear)",
        "echo" to "Echo (Male)",
        "sage" to "Sage (Wise)",
        "shimmer" to "Shimmer (Soft Female)",
        "verse" to "Verse (Dynamic)"
    )
    
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Settings") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Text("←", style = MaterialTheme.typography.headlineMedium)
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Text(
                "OpenAI Configuration",
                style = MaterialTheme.typography.headlineSmall
            )
            
            // API Key Input
            OutlinedTextField(
                value = apiKey,
                onValueChange = { 
                    apiKey = it
                    testResult = ApiTestResult.Idle  // Reset test when key changes
                },
                label = { Text("OpenAI API Key") },
                placeholder = { Text("Paste your API key here") },
                modifier = Modifier.fillMaxWidth(),
                visualTransformation = if (showApiKey) {
                    VisualTransformation.None
                } else {
                    PasswordVisualTransformation()
                },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                trailingIcon = {
                    TextButton(onClick = { showApiKey = !showApiKey }) {
                        Text(if (showApiKey) "Hide" else "Show")
                    }
                },
                singleLine = false,
                maxLines = 3
            )
            
            // Show key info to help verify
            if (apiKey.isNotBlank()) {
                Text(
                    "${apiKey.trim().length} characters" + 
                        if (apiKey.trim().startsWith("sk-")) " • starts with sk-" else " • ⚠️ should start with sk-",
                    style = MaterialTheme.typography.bodySmall,
                    color = if (apiKey.trim().startsWith("sk-")) 
                        MaterialTheme.colorScheme.onSurfaceVariant 
                    else 
                        Color(0xFFF44336)
                )
            }
            
            // Test API Key Button
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                OutlinedButton(
                    onClick = {
                        scope.launch {
                            testResult = ApiTestResult.Testing
                            testResult = testRealtimeApi(apiKey.trim())
                        }
                    },
                    enabled = apiKey.isNotBlank() && testResult !is ApiTestResult.Testing
                ) {
                    Text(if (testResult is ApiTestResult.Testing) "Testing..." else "Test API Key")
                }
                
                // Test result indicator
                when (val result = testResult) {
                    is ApiTestResult.Success -> {
                        Text(
                            "✅ ${result.message}",
                            color = Color(0xFF4CAF50),
                            modifier = Modifier.padding(top = 8.dp)
                        )
                    }
                    is ApiTestResult.Error -> {
                        Text(
                            "❌ ${result.message}",
                            color = Color(0xFFF44336),
                            modifier = Modifier.padding(top = 8.dp),
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                    else -> {}
                }
            }
            
            Text(
                "Get your API key from: https://platform.openai.com/api-keys",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            
            Spacer(modifier = Modifier.height(8.dp))
            
            // Voice Selection
            Text(
                "AI Voice",
                style = MaterialTheme.typography.titleMedium
            )
            
            voices.forEach { (voiceId, voiceName) ->
                Row(
                    modifier = Modifier.fillMaxWidth()
                ) {
                    RadioButton(
                        selected = selectedVoice == voiceId,
                        onClick = { selectedVoice = voiceId }
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        voiceName,
                        modifier = Modifier.padding(top = 12.dp)
                    )
                }
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            // Instructions Input
            Text(
                "AI Instructions",
                style = MaterialTheme.typography.titleMedium
            )
            
            OutlinedTextField(
                value = instructions,
                onValueChange = { instructions = it },
                label = { Text("System Instructions") },
                placeholder = { Text("How should the AI behave?") },
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 120.dp),
                maxLines = 6
            )
            
            Text(
                "These instructions tell the AI how to behave during calls.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            
            Spacer(modifier = Modifier.height(16.dp))
            
            // Save Button
            Button(
                onClick = {
                    if (apiKey.isBlank()) {
                        return@Button
                    }
                    onSave(apiKey.trim(), instructions, selectedVoice)
                },
                modifier = Modifier.fillMaxWidth(),
                enabled = apiKey.isNotBlank()
            ) {
                Text("Save Settings")
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.secondaryContainer
                )
            ) {
                Column(
                    modifier = Modifier.padding(16.dp)
                ) {
                    Text(
                        "ℹ️ Important",
                        style = MaterialTheme.typography.titleSmall
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        "After saving, you need to set BandoPhone as your default phone app " +
                                "in Android settings for the AI to work during calls.",
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            }
        }
    }
}

/**
 * Test the API key by connecting to the Realtime API WebSocket
 */
private suspend fun testRealtimeApi(apiKey: String): ApiTestResult = withContext(Dispatchers.IO) {
    if (!apiKey.startsWith("sk-")) {
        return@withContext ApiTestResult.Error("Key should start with 'sk-'")
    }
    
    val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .build()
    
    val request = Request.Builder()
        .url("wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-17")
        .header("Authorization", "Bearer $apiKey")
        .header("OpenAI-Beta", "realtime=v1")
        .build()
    
    var result: ApiTestResult = ApiTestResult.Error("Connection timeout")
    val latch = java.util.concurrent.CountDownLatch(1)
    
    val listener = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            // Connection successful - we'll get session.created message
        }
        
        override fun onMessage(webSocket: WebSocket, text: String) {
            try {
                val json = org.json.JSONObject(text)
                val type = json.optString("type")
                if (type == "session.created") {
                    result = ApiTestResult.Success("Connected!")
                    webSocket.close(1000, "Test complete")
                    latch.countDown()
                }
            } catch (e: Exception) {
                // Ignore parse errors
            }
        }
        
        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            val errorMsg = when {
                response?.code == 401 -> "Invalid API key"
                response?.code == 403 -> "No Realtime API access"
                response?.code == 429 -> "Rate limited"
                t.message?.contains("401") == true -> "Invalid API key"
                else -> t.message ?: "Connection failed"
            }
            result = ApiTestResult.Error(errorMsg)
            latch.countDown()
        }
        
        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            latch.countDown()
        }
    }
    
    val webSocket = client.newWebSocket(request, listener)
    
    // Wait for result with timeout
    val completed = latch.await(10, TimeUnit.SECONDS)
    if (!completed) {
        webSocket.cancel()
        result = ApiTestResult.Error("Timeout")
    }
    
    client.dispatcher.executorService.shutdown()
    
    result
}
