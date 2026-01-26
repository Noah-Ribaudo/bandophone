"""
Phone Audio Streaming for Bandophone
Bidirectional audio streaming via TinyALSA

Injection: 24kHz mono → stereo → device 19 @ 16kHz (magic ratio!)
Capture: device 20 @ 48kHz stereo → 24kHz mono for Realtime API
"""

import asyncio
import subprocess
import struct
import logging
import tempfile
import os
from typing import Optional, Callable, AsyncGenerator
from pathlib import Path

log = logging.getLogger(__name__)

# Device config discovered 2026-01-26
INJECT_DEVICE = 19
INJECT_RATE = 16000  # Tell device this rate - magic ratio for 24kHz content!
CAPTURE_DEVICE = 20
CAPTURE_RATE = 48000
CAPTURE_CHANNELS = 2

# Mixer controls
MIXER_CAPTURE_STREAM = 152  # Set to "DL" for downlink (remote party audio)
MIXER_MIC_MUTE = 167


class PhoneAudioStream:
    """Bidirectional audio streaming to/from phone calls."""
    
    def __init__(self, device_serial: Optional[str] = None):
        self.device_serial = device_serial
        self.tinyalsa_path = "/data/local/tmp"
        self._capture_task = None
        self._inject_queue: asyncio.Queue = None
        self._inject_task = None
        self._running = False
        
    def _adb_cmd(self, cmd: str, as_root: bool = True) -> str:
        """Run ADB shell command."""
        adb = ["adb"]
        if self.device_serial:
            adb.extend(["-s", self.device_serial])
        
        if as_root:
            full = adb + ["shell", "su", "-c", cmd]
        else:
            full = adb + ["shell", cmd]
        
        result = subprocess.run(full, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    
    def is_call_active(self) -> bool:
        """Check for active phone call."""
        output = self._adb_cmd("dumpsys telecom | grep 'state=ACTIVE'", as_root=False)
        return "ACTIVE" in output
    
    def setup_mixer(self):
        """Configure mixer for bidirectional audio."""
        # Enable capture (downlink = remote party's audio)
        self._adb_cmd(f"{self.tinyalsa_path}/tinymix -D 0 set {MIXER_CAPTURE_STREAM} DL")
        # Mute phone's mic (we inject AI audio instead)
        self._adb_cmd(f"{self.tinyalsa_path}/tinymix -D 0 set {MIXER_MIC_MUTE} 1")
        log.info("Mixer configured: capture=DL, mic=muted")
    
    @staticmethod
    def mono_to_stereo(pcm_mono: bytes) -> bytes:
        """Convert mono PCM to stereo by duplicating channels."""
        samples = struct.unpack(f'<{len(pcm_mono)//2}h', pcm_mono)
        stereo = []
        for s in samples:
            stereo.extend([s, s])
        return struct.pack(f'<{len(stereo)}h', *stereo)
    
    @staticmethod
    def stereo_to_mono(pcm_stereo: bytes) -> bytes:
        """Convert stereo PCM to mono by averaging channels."""
        samples = struct.unpack(f'<{len(pcm_stereo)//2}h', pcm_stereo)
        mono = []
        for i in range(0, len(samples), 2):
            avg = (samples[i] + samples[i+1]) // 2
            mono.append(avg)
        return struct.pack(f'<{len(mono)}h', *mono)
    
    @staticmethod
    def resample_48k_to_24k(pcm_48k: bytes) -> bytes:
        """Simple 2:1 downsampling from 48kHz to 24kHz."""
        samples = struct.unpack(f'<{len(pcm_48k)//2}h', pcm_48k)
        # Take every other sample (simple decimation)
        resampled = samples[::2]
        return struct.pack(f'<{len(resampled)}h', *resampled)
    
    async def inject_audio(self, pcm_24k_mono: bytes):
        """
        Inject audio into the phone call.
        
        Args:
            pcm_24k_mono: 24kHz mono PCM16 (OpenAI Realtime API format)
        """
        if self._inject_queue:
            await self._inject_queue.put(pcm_24k_mono)
    
    async def _inject_loop(self):
        """Background task to inject queued audio."""
        self._inject_queue = asyncio.Queue()
        buffer = b''
        
        # Minimum chunk size for efficient injection (100ms of audio)
        min_chunk = 24000 * 2 // 10  # 24kHz * 2 bytes * 0.1s = 4800 bytes
        
        while self._running:
            try:
                # Wait for audio with timeout
                try:
                    chunk = await asyncio.wait_for(self._inject_queue.get(), timeout=0.1)
                    buffer += chunk
                except asyncio.TimeoutError:
                    pass
                
                # Inject when we have enough
                if len(buffer) >= min_chunk:
                    await self._do_inject(buffer)
                    buffer = b''
                    
            except Exception as e:
                log.error(f"Inject error: {e}")
                await asyncio.sleep(0.1)
    
    async def _do_inject(self, pcm_24k_mono: bytes):
        """Actually inject audio to device."""
        # Convert mono to stereo
        pcm_stereo = self.mono_to_stereo(pcm_24k_mono)
        
        # Write to temp file and push
        with tempfile.NamedTemporaryFile(suffix='.pcm', delete=False) as f:
            f.write(pcm_stereo)
            temp_path = f.name
        
        try:
            # Push to device
            adb = ["adb"]
            if self.device_serial:
                adb.extend(["-s", self.device_serial])
            
            remote_path = "/sdcard/inject.pcm"
            subprocess.run(adb + ["push", temp_path, remote_path], 
                          capture_output=True, timeout=5)
            
            # Play with tinyplay - use 16kHz rate for correct 24kHz playback!
            cmd = f"{self.tinyalsa_path}/tinyplay {remote_path} -D 0 -d {INJECT_DEVICE} -c 2 -r {INJECT_RATE} -b 16"
            self._adb_cmd(cmd)
            
        finally:
            os.unlink(temp_path)
    
    async def capture_stream(self, 
                            chunk_duration_ms: int = 100,
                            on_audio: Optional[Callable[[bytes], None]] = None
                            ) -> AsyncGenerator[bytes, None]:
        """
        Stream captured audio from phone call.
        
        Yields 24kHz mono PCM chunks (Realtime API format).
        
        Args:
            chunk_duration_ms: Chunk size in milliseconds
            on_audio: Optional callback for each chunk
        """
        # Re-enable capture (mixer resets sometimes)
        self._adb_cmd(f"{self.tinyalsa_path}/tinymix -D 0 set {MIXER_CAPTURE_STREAM} DL")
        
        # Calculate chunk sizes
        # Capture at 48kHz stereo, output 24kHz mono
        capture_chunk = int(CAPTURE_RATE * 2 * CAPTURE_CHANNELS * chunk_duration_ms / 1000)
        
        remote_path = "/sdcard/capture_stream.pcm"
        
        # Start continuous capture
        start_cmd = f"{self.tinyalsa_path}/tinycap {remote_path} -D 0 -d {CAPTURE_DEVICE} -c {CAPTURE_CHANNELS} -r {CAPTURE_RATE} -b 16 &"
        self._adb_cmd(start_cmd)
        
        read_offset = 0
        
        try:
            while self._running:
                # Check file size
                result = self._adb_cmd(f"stat -c%s {remote_path} 2>/dev/null || echo 0")
                try:
                    file_size = int(result)
                except:
                    await asyncio.sleep(0.05)
                    continue
                
                available = file_size - read_offset
                
                if available >= capture_chunk:
                    # Read chunk via dd
                    adb = ["adb"]
                    if self.device_serial:
                        adb.extend(["-s", self.device_serial])
                    
                    result = subprocess.run(
                        adb + ["shell", f"su -c 'dd if={remote_path} bs=1 skip={read_offset} count={capture_chunk} 2>/dev/null'"],
                        capture_output=True, timeout=5
                    )
                    
                    if result.returncode == 0 and len(result.stdout) == capture_chunk:
                        pcm_48k_stereo = result.stdout
                        read_offset += capture_chunk
                        
                        # Convert: 48kHz stereo → 24kHz mono
                        pcm_48k_mono = self.stereo_to_mono(pcm_48k_stereo)
                        pcm_24k_mono = self.resample_48k_to_24k(pcm_48k_mono)
                        
                        if on_audio:
                            on_audio(pcm_24k_mono)
                        
                        yield pcm_24k_mono
                else:
                    await asyncio.sleep(0.02)  # 20ms polling
                    
        finally:
            # Stop capture
            self._adb_cmd("pkill -9 tinycap")
            self._adb_cmd(f"rm {remote_path}")
    
    async def start(self):
        """Start bidirectional streaming."""
        self._running = True
        self.setup_mixer()
        self._inject_task = asyncio.create_task(self._inject_loop())
        log.info("Phone audio stream started")
    
    async def stop(self):
        """Stop streaming."""
        self._running = False
        self._adb_cmd("pkill -9 tinycap")
        self._adb_cmd("pkill -9 tinyplay")
        if self._inject_task:
            self._inject_task.cancel()
        log.info("Phone audio stream stopped")


# Quick test
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    
    async def test():
        stream = PhoneAudioStream()
        
        if not stream.is_call_active():
            print("No active call!")
            return
        
        await stream.start()
        
        print("Streaming for 10 seconds...")
        count = 0
        async for chunk in stream.capture_stream(chunk_duration_ms=100):
            count += 1
            print(f"Captured chunk {count}: {len(chunk)} bytes")
            if count >= 100:  # 10 seconds
                break
        
        await stream.stop()
    
    asyncio.run(test())
