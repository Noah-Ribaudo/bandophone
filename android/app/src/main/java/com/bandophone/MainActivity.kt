package com.bandophone

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    
    private val requiredPermissions = arrayOf(
        Manifest.permission.RECORD_AUDIO,
        Manifest.permission.READ_PHONE_STATE,
        Manifest.permission.FOREGROUND_SERVICE
    )
    
    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val allGranted = permissions.values.all { it }
        if (!allGranted) {
            Toast.makeText(this, "Permissions required for voice bridge", Toast.LENGTH_LONG).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        checkPermissions()
        
        setContent {
            MaterialTheme {
                BandophoneScreen(
                    onStartService = { url -> startBridge(url) },
                    onStopService = { stopBridge() },
                    onOpenSettings = { openSettings() }
                )
            }
        }
    }
    
    private fun openSettings() {
        startActivity(Intent(this, SettingsActivity::class.java))
    }
    
    private fun checkPermissions() {
        val needed = requiredPermissions.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (needed.isNotEmpty()) {
            permissionLauncher.launch(needed.toTypedArray())
        }
    }
    
    private fun startBridge(url: String) {
        val intent = Intent(this, AudioInjectionService::class.java).apply {
            action = AudioInjectionService.ACTION_START
            putExtra(AudioInjectionService.EXTRA_BRIDGE_URL, url)
        }
        startForegroundService(intent)
        Toast.makeText(this, "Bridge starting...", Toast.LENGTH_SHORT).show()
    }
    
    private fun stopBridge() {
        val intent = Intent(this, AudioInjectionService::class.java).apply {
            action = AudioInjectionService.ACTION_STOP
        }
        startService(intent)
        Toast.makeText(this, "Bridge stopped", Toast.LENGTH_SHORT).show()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BandophoneScreen(
    onStartService: (String) -> Unit,
    onStopService: () -> Unit,
    onOpenSettings: () -> Unit
) {
    var bridgeUrl by remember { mutableStateOf("ws://192.168.4.82:8765") }
    var isRunning by remember { mutableStateOf(false) }
    val hasApiKey = remember { ApiKeyManager.hasApiKey(BandophoneApp.instance) }
    
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("🦝 Bandophone") },
                actions = {
                    TextButton(onClick = onOpenSettings) {
                        Text("⚙️ Settings")
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Text(
                "Voice Bridge for Bando",
                style = MaterialTheme.typography.headlineSmall
            )
            
            Text(
                "Choose between external bridge (Mac) or native OpenAI integration.",
                style = MaterialTheme.typography.bodyMedium
            )
            
            Spacer(modifier = Modifier.height(16.dp))
            
            // Native AI Status Card
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = if (hasApiKey) {
                        MaterialTheme.colorScheme.primaryContainer
                    } else {
                        MaterialTheme.colorScheme.errorContainer
                    }
                )
            ) {
                Column(
                    modifier = Modifier.padding(16.dp)
                ) {
                    Text(
                        "🤖 Native AI Integration",
                        style = MaterialTheme.typography.titleMedium
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    if (hasApiKey) {
                        Text(
                            "✅ OpenAI API key configured",
                            style = MaterialTheme.typography.bodySmall
                        )
                        Text(
                            "Native AI will answer calls automatically when set as default phone app.",
                            style = MaterialTheme.typography.bodySmall
                        )
                    } else {
                        Text(
                            "⚠️ No API key configured",
                            style = MaterialTheme.typography.bodySmall
                        )
                        Text(
                            "Go to Settings to configure OpenAI API key for native integration.",
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            }
            
            Spacer(modifier = Modifier.height(16.dp))
            
            Divider()
            
            Spacer(modifier = Modifier.height(16.dp))
            
            Text(
                "External Bridge (Legacy)",
                style = MaterialTheme.typography.titleMedium
            )
            
            OutlinedTextField(
                value = bridgeUrl,
                onValueChange = { bridgeUrl = it },
                label = { Text("Bridge URL") },
                placeholder = { Text("ws://mac-ip:8765") },
                modifier = Modifier.fillMaxWidth(),
                enabled = !isRunning
            )
            
            Spacer(modifier = Modifier.height(16.dp))
            
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                Button(
                    onClick = {
                        onStartService(bridgeUrl)
                        isRunning = true
                    },
                    enabled = !isRunning && bridgeUrl.isNotBlank(),
                    modifier = Modifier.weight(1f)
                ) {
                    Text("Start")
                }
                
                Button(
                    onClick = {
                        onStopService()
                        isRunning = false
                    },
                    enabled = isRunning,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.error
                    ),
                    modifier = Modifier.weight(1f)
                ) {
                    Text("Stop")
                }
            }
            
            Spacer(modifier = Modifier.weight(1f))
            
            Card(
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(
                    modifier = Modifier.padding(16.dp)
                ) {
                    Text(
                        "Status",
                        style = MaterialTheme.typography.titleMedium
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        if (isRunning) "🟢 Bridge active" else "⚪ Not connected",
                        style = MaterialTheme.typography.bodyLarge
                    )
                }
            }
            
            Text(
                "Note: Make sure the bridge is running on your Mac first.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}
