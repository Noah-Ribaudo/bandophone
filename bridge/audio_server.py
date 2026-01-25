#!/usr/bin/env python3
"""
WebSocket server for sending AI audio to Android app.
"""

import asyncio
import base64
import json
import logging
import websockets
from typing import Set, Optional

log = logging.getLogger("bandophone.server")


class AudioServer:
    """
    WebSocket server that sends AI audio to connected Android clients.
    """
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.clients: Set[websockets.WebSocketServerProtocol] = set()
        self.server: Optional[websockets.WebSocketServer] = None
    
    async def start(self):
        """Start the WebSocket server."""
        self.server = await websockets.serve(
            self._handle_client,
            self.host,
            self.port
        )
        log.info(f"Audio server listening on ws://{self.host}:{self.port}")
    
    async def stop(self):
        """Stop the server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
    
    async def _handle_client(self, websocket: websockets.WebSocketServerProtocol, path: str):
        """Handle a new client connection."""
        client_addr = websocket.remote_address
        log.info(f"Android client connected: {client_addr}")
        self.clients.add(websocket)
        
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type", "")
                    
                    if msg_type == "hello":
                        log.info(f"Client hello: {data.get('client', 'unknown')}")
                        await websocket.send(json.dumps({
                            "type": "welcome",
                            "server": "bandophone-bridge"
                        }))
                    
                    elif msg_type == "status":
                        in_call = data.get("inCall", False)
                        log.info(f"Client call status: {'in call' if in_call else 'idle'}")
                    
                    elif msg_type == "pong":
                        pass  # Heartbeat response
                    
                except json.JSONDecodeError:
                    log.warning(f"Invalid JSON from client")
                    
        except websockets.exceptions.ConnectionClosed:
            log.info(f"Client disconnected: {client_addr}")
        finally:
            self.clients.discard(websocket)
    
    async def send_audio(self, audio_data: bytes):
        """Send audio to all connected clients."""
        if not self.clients:
            return
        
        # Send as binary for efficiency
        disconnected = set()
        for client in self.clients:
            try:
                await client.send(audio_data)
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(client)
        
        self.clients -= disconnected
    
    async def send_audio_json(self, audio_data: bytes):
        """Send audio as JSON (base64 encoded) to all clients."""
        if not self.clients:
            return
        
        message = json.dumps({
            "type": "audio",
            "data": base64.b64encode(audio_data).decode('utf-8')
        })
        
        disconnected = set()
        for client in self.clients:
            try:
                await client.send(message)
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(client)
        
        self.clients -= disconnected
    
    @property
    def has_clients(self) -> bool:
        return len(self.clients) > 0


# Test server standalone
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    async def main():
        server = AudioServer()
        await server.start()
        
        print("Audio server running. Press Ctrl+C to stop.")
        try:
            await asyncio.Future()  # Run forever
        except KeyboardInterrupt:
            pass
        finally:
            await server.stop()
    
    asyncio.run(main())
