#!/usr/bin/env python3
"""
Bandophone Web UI

Simple web interface for configuration and monitoring.

Usage:
    python web_ui.py [--port 8080]
    
Then open http://localhost:8080
"""

import json
import os
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import argparse

from config import BandophoneConfig, VOICES, PERSONALITIES

# Inline HTML template (no external dependencies)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bandophone 🦝📞</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
            color: #333;
        }
        h1 { 
            text-align: center;
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        .subtitle {
            text-align: center;
            color: #666;
            margin-bottom: 30px;
        }
        .card {
            background: white;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .card h2 {
            margin-top: 0;
            border-bottom: 2px solid #6200EE;
            padding-bottom: 10px;
        }
        .status {
            display: flex;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 15px;
        }
        .status-item {
            flex: 1;
            min-width: 150px;
            text-align: center;
            padding: 15px;
            background: #f9f9f9;
            border-radius: 8px;
        }
        .status-item .icon { font-size: 2em; }
        .status-item .label { color: #666; font-size: 0.9em; }
        .status-item .value { font-weight: bold; margin-top: 5px; }
        .status-item.ok { background: #e8f5e9; }
        .status-item.error { background: #ffebee; }
        .status-item.warning { background: #fff8e1; }
        
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: 500;
        }
        select, input, textarea {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 6px;
            margin-bottom: 15px;
            font-size: 16px;
        }
        textarea { min-height: 100px; resize: vertical; }
        button {
            background: #6200EE;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 16px;
            margin-right: 10px;
        }
        button:hover { background: #5000d0; }
        button.secondary {
            background: #f5f5f5;
            color: #333;
            border: 1px solid #ddd;
        }
        button.secondary:hover { background: #eee; }
        
        .voice-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 10px;
            margin-bottom: 15px;
        }
        .voice-option {
            padding: 15px;
            border: 2px solid #ddd;
            border-radius: 8px;
            cursor: pointer;
            text-align: center;
        }
        .voice-option:hover { border-color: #6200EE; }
        .voice-option.selected {
            border-color: #6200EE;
            background: #f3e5f5;
        }
        .voice-option .name { font-weight: bold; }
        .voice-option .desc { font-size: 0.85em; color: #666; }
        
        .personality-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .personality-option {
            padding: 15px;
            border: 2px solid #ddd;
            border-radius: 8px;
            cursor: pointer;
        }
        .personality-option:hover { border-color: #6200EE; }
        .personality-option.selected {
            border-color: #6200EE;
            background: #f3e5f5;
        }
        .personality-option .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .personality-option .name { font-weight: bold; }
        .personality-option .voice { 
            font-size: 0.85em;
            background: #e0e0e0;
            padding: 2px 8px;
            border-radius: 4px;
        }
        .personality-option .desc {
            font-size: 0.9em;
            color: #666;
            margin-top: 8px;
        }
        
        .toast {
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: #333;
            color: white;
            padding: 12px 24px;
            border-radius: 8px;
            display: none;
        }
        .toast.show { display: block; }
    </style>
</head>
<body>
    <h1>🦝 Bandophone</h1>
    <p class="subtitle">Give your AI assistant a real phone</p>
    
    <div class="card">
        <h2>📊 Status</h2>
        <div class="status" id="status">
            <div class="status-item" id="status-device">
                <div class="icon">📱</div>
                <div class="label">Device</div>
                <div class="value">Checking...</div>
            </div>
            <div class="status-item" id="status-call">
                <div class="icon">📞</div>
                <div class="label">Call</div>
                <div class="value">Checking...</div>
            </div>
            <div class="status-item" id="status-api">
                <div class="icon">🔑</div>
                <div class="label">API Key</div>
                <div class="value">Checking...</div>
            </div>
        </div>
    </div>
    
    <div class="card">
        <h2>🎭 Personality</h2>
        <div class="personality-list" id="personalities">
            <!-- Filled by JS -->
        </div>
    </div>
    
    <div class="card">
        <h2>🎤 Voice</h2>
        <div class="voice-grid" id="voices">
            <!-- Filled by JS -->
        </div>
    </div>
    
    <div class="card">
        <h2>⚙️ Custom Instructions</h2>
        <textarea id="instructions" placeholder="Override the personality's default instructions..."></textarea>
        <button onclick="saveConfig()">💾 Save Configuration</button>
        <button class="secondary" onclick="resetInstructions()">Reset to Default</button>
    </div>
    
    <div class="card">
        <h2>🔑 API Key</h2>
        <input type="password" id="apiKey" placeholder="sk-...">
        <button onclick="saveApiKey()">Save API Key</button>
    </div>
    
    <div class="toast" id="toast">Saved!</div>
    
    <script>
        const VOICES = %%VOICES%%;
        const PERSONALITIES = %%PERSONALITIES%%;
        
        let currentConfig = {
            voice: 'alloy',
            personality: 'assistant',
            custom_instructions: '',
            api_key_set: false
        };
        
        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            renderVoices();
            renderPersonalities();
            loadConfig();
            checkStatus();
            
            // Poll status every 5s
            setInterval(checkStatus, 5000);
        });
        
        function renderVoices() {
            const container = document.getElementById('voices');
            container.innerHTML = Object.entries(VOICES).map(([id, desc]) => `
                <div class="voice-option" data-voice="${id}" onclick="selectVoice('${id}')">
                    <div class="name">${id}</div>
                    <div class="desc">${desc}</div>
                </div>
            `).join('');
        }
        
        function renderPersonalities() {
            const container = document.getElementById('personalities');
            container.innerHTML = Object.entries(PERSONALITIES).map(([id, config]) => `
                <div class="personality-option" data-personality="${id}" onclick="selectPersonality('${id}')">
                    <div class="header">
                        <span class="name">${config.name}</span>
                        <span class="voice">${config.voice}</span>
                    </div>
                    <div class="desc">${config.instructions.substring(0, 100)}...</div>
                </div>
            `).join('');
        }
        
        function selectVoice(voice) {
            currentConfig.voice = voice;
            document.querySelectorAll('.voice-option').forEach(el => {
                el.classList.toggle('selected', el.dataset.voice === voice);
            });
        }
        
        function selectPersonality(personality) {
            currentConfig.personality = personality;
            currentConfig.voice = PERSONALITIES[personality].voice;
            
            document.querySelectorAll('.personality-option').forEach(el => {
                el.classList.toggle('selected', el.dataset.personality === personality);
            });
            document.querySelectorAll('.voice-option').forEach(el => {
                el.classList.toggle('selected', el.dataset.voice === currentConfig.voice);
            });
        }
        
        async function loadConfig() {
            try {
                const resp = await fetch('/api/config');
                const data = await resp.json();
                currentConfig = { ...currentConfig, ...data };
                
                selectVoice(data.voice || 'alloy');
                selectPersonality(data.personality || 'assistant');
                document.getElementById('instructions').value = data.custom_instructions || '';
                
            } catch (e) {
                console.error('Failed to load config:', e);
            }
        }
        
        async function saveConfig() {
            try {
                await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        voice: currentConfig.voice,
                        personality: currentConfig.personality,
                        custom_instructions: document.getElementById('instructions').value
                    })
                });
                showToast('Configuration saved!');
            } catch (e) {
                showToast('Error saving config');
            }
        }
        
        async function saveApiKey() {
            const key = document.getElementById('apiKey').value;
            if (!key) return;
            
            try {
                await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ api_key: key })
                });
                document.getElementById('apiKey').value = '';
                showToast('API key saved!');
                checkStatus();
            } catch (e) {
                showToast('Error saving API key');
            }
        }
        
        function resetInstructions() {
            document.getElementById('instructions').value = '';
            showToast('Instructions reset to default');
        }
        
        async function checkStatus() {
            try {
                const resp = await fetch('/api/status');
                const data = await resp.json();
                
                updateStatusItem('status-device', data.device_connected, 
                    data.device_connected ? 'Connected' : 'Not connected');
                updateStatusItem('status-call', data.call_active, 
                    data.call_active ? 'Active' : 'Idle',
                    data.call_active ? 'ok' : null);
                updateStatusItem('status-api', data.api_key_set,
                    data.api_key_set ? 'Set' : 'Not set');
                    
            } catch (e) {
                console.error('Status check failed:', e);
            }
        }
        
        function updateStatusItem(id, ok, text, forceClass) {
            const el = document.getElementById(id);
            el.querySelector('.value').textContent = text;
            el.classList.remove('ok', 'error', 'warning');
            if (forceClass) {
                el.classList.add(forceClass);
            } else {
                el.classList.add(ok ? 'ok' : 'error');
            }
        }
        
        function showToast(msg) {
            const toast = document.getElementById('toast');
            toast.textContent = msg;
            toast.classList.add('show');
            setTimeout(() => toast.classList.remove('show'), 2000);
        }
    </script>
</body>
</html>
"""


class BandophoneHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Bandophone Web UI."""
    
    config_path = "bandophone.json"
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass
    
    def _send_json(self, data, status=200):
        """Send JSON response."""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def _send_html(self, html):
        """Send HTML response."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode())
    
    def do_GET(self):
        """Handle GET requests."""
        path = urlparse(self.path).path
        
        if path == '/' or path == '/index.html':
            # Serve main page with config injected
            html = HTML_TEMPLATE
            html = html.replace('%%VOICES%%', json.dumps(VOICES))
            html = html.replace('%%PERSONALITIES%%', json.dumps(PERSONALITIES))
            self._send_html(html)
        
        elif path == '/api/config':
            config = BandophoneConfig.load(self.config_path)
            self._send_json({
                'voice': config.voice,
                'personality': config.personality,
                'custom_instructions': config.custom_instructions or '',
                'api_key_set': bool(config.openai_api_key)
            })
        
        elif path == '/api/status':
            self._send_json(self._get_status())
        
        else:
            self.send_error(404)
    
    def do_POST(self):
        """Handle POST requests."""
        path = urlparse(self.path).path
        
        if path == '/api/config':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            
            config = BandophoneConfig.load(self.config_path)
            
            if 'voice' in data:
                config.voice = data['voice']
            if 'personality' in data:
                config.personality = data['personality']
            if 'custom_instructions' in data:
                config.custom_instructions = data['custom_instructions'] or None
            if 'api_key' in data:
                config.openai_api_key = data['api_key']
            
            config.save(self.config_path)
            self._send_json({'status': 'ok'})
        
        else:
            self.send_error(404)
    
    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def _get_status(self):
        """Get system status."""
        status = {
            'device_connected': False,
            'call_active': False,
            'api_key_set': False
        }
        
        # Check device
        result = subprocess.run("adb devices", shell=True, capture_output=True, text=True)
        status['device_connected'] = 'device' in result.stdout and result.stdout.count('\n') > 2
        
        # Check call
        if status['device_connected']:
            result = subprocess.run(
                'adb shell "su -c \'export LD_LIBRARY_PATH=/data/local/tmp && /data/local/tmp/tinymix get \"Audio DSP State\"\'"',
                shell=True, capture_output=True, text=True
            )
            status['call_active'] = 'Telephony' in result.stdout
        
        # Check API key
        config = BandophoneConfig.load(self.config_path)
        status['api_key_set'] = bool(config.openai_api_key)
        
        return status


def main():
    parser = argparse.ArgumentParser(description="Bandophone Web UI")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Port to listen on")
    parser.add_argument("--config", "-c", default="bandophone.json", help="Config file path")
    args = parser.parse_args()
    
    BandophoneHandler.config_path = args.config
    
    server = HTTPServer(('0.0.0.0', args.port), BandophoneHandler)
    print(f"🦝 Bandophone Web UI running at http://localhost:{args.port}")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
