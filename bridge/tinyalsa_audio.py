#!/usr/bin/env python3
"""
TinyALSA Audio Module for Bandophone

Handles audio injection and capture for phone calls on Android using TinyALSA.

VERIFIED WORKING CONFIG (Pixel 7 Pro):
- Injection: device 19, 24kHz stereo content, tell device 16000Hz rate
- Capture: device 20, 48kHz stereo, tinymix 152=DL
- Mic mute: tinymix 167=1

Audio Conversion:
- OpenAI API (24kHz mono PCM16) → stereo → device 19
- Device 20 (48kHz stereo) → 16kHz mono → Whisper
"""

import asyncio
import logging
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Callable
import time

log = logging.getLogger("tinyalsa")


class TinyALSAConfig:
    """Configuration for TinyALSA devices and parameters."""
    
    # Device IDs
    INJECTION_DEVICE = 19  # audio_incall_pb_0
    CAPTURE_DEVICE = 20    # audio_incall_cap_0
    
    # Sample rates
    INJECTION_RATE_ACTUAL = 24000  # Content is 24kHz stereo
    INJECTION_RATE_TOLD = 16000    # But we tell device 16kHz (magic!)
    CAPTURE_RATE = 48000           # Device captures at 48kHz
    WHISPER_RATE = 16000           # Whisper expects 16kHz mono
    
    # Audio format
    CHANNELS_STEREO = 2
    CHANNELS_MONO = 1
    BITS_PER_SAMPLE = 16
    
    # Mixer controls
    MIXER_CAPTURE_ENABLE = 152     # "Incall Capture Stream0" - set to "DL"
    MIXER_MIC_MUTE = 167           # Mic mute control
    MIXER_DEVICE = 0               # Device ID for tinymix
    
    # TinyALSA binary paths on device
    TINYALSA_DIR = "/data/local/tmp"
    TINYPLAY = f"{TINYALSA_DIR}/tinyplay"
    TINYCAP = f"{TINYALSA_DIR}/tinycap"
    TINYMIX = f"{TINYALSA_DIR}/tinymix"
    
    # Temp files on device
    TEMP_DIR = "/sdcard"
    INJECTION_FILE = f"{TEMP_DIR}/bandophone_inject.pcm"
    CAPTURE_FILE = f"{TEMP_DIR}/bandophone_capture.pcm"


class AudioConverter:
    """Audio format conversion utilities."""
    
    @staticmethod
    def mono_to_stereo(data: bytes) -> bytes:
        """Convert mono PCM16 to stereo by duplicating samples."""
        samples = struct.unpack(f'<{len(data)//2}h', data)
        stereo = []
        for sample in samples:
            stereo.extend([sample, sample])  # L and R channels identical
        return struct.pack(f'<{len(stereo)}h', *stereo)
    
    @staticmethod
    def stereo_to_mono(data: bytes) -> bytes:
        """Convert stereo PCM16 to mono by averaging channels."""
        samples = struct.unpack(f'<{len(data)//2}h', data)
        mono = []
        for i in range(0, len(samples), 2):
            if i + 1 < len(samples):
                avg = (samples[i] + samples[i+1]) // 2
                mono.append(avg)
        return struct.pack(f'<{len(mono)}h', *mono)
    
    @staticmethod
    def resample_simple(data: bytes, src_rate: int, dst_rate: int) -> bytes:
        """Simple resampling by dropping/duplicating samples."""
        if src_rate == dst_rate:
            return data
        
        samples = struct.unpack(f'<{len(data)//2}h', data)
        ratio = dst_rate / src_rate
        
        resampled = []
        for i in range(int(len(samples) * ratio)):
            src_idx = int(i / ratio)
            if src_idx < len(samples):
                resampled.append(samples[src_idx])
        
        return struct.pack(f'<{len(resampled)}h', *resampled)


class TinyALSAMixer:
    """Control TinyALSA mixer settings via ADB."""
    
    def __init__(self, device_id: str = None):
        """
        Initialize mixer controller.
        
        Args:
            device_id: ADB device ID (optional, uses first device if None)
        """
        self.device_id = device_id
        self.config = TinyALSAConfig()
    
    def _run_adb(self, command: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run ADB shell command with root."""
        adb_cmd = ['adb']
        if self.device_id:
            adb_cmd.extend(['-s', self.device_id])
        
        full_cmd = f'su -c "export LD_LIBRARY_PATH={self.config.TINYALSA_DIR} && {command}"'
        adb_cmd.extend(['shell', full_cmd])
        
        result = subprocess.run(adb_cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            log.error(f"ADB command failed: {result.stderr}")
            raise RuntimeError(f"ADB command failed: {result.stderr}")
        return result
    
    def enable_capture(self) -> bool:
        """Enable in-call audio capture stream (must be done for each call)."""
        try:
            log.info("Enabling in-call capture stream...")
            self._run_adb(f"{self.config.TINYMIX} -D {self.config.MIXER_DEVICE} set {self.config.MIXER_CAPTURE_ENABLE} DL")
            return True
        except Exception as e:
            log.error(f"Failed to enable capture: {e}")
            return False
    
    def mute_mic(self, muted: bool = True) -> bool:
        """Mute/unmute the phone's microphone."""
        try:
            value = 1 if muted else 0
            log.info(f"{'Muting' if muted else 'Unmuting'} microphone...")
            self._run_adb(f"{self.config.TINYMIX} -D {self.config.MIXER_DEVICE} set {self.config.MIXER_MIC_MUTE} {value}")
            return True
        except Exception as e:
            log.error(f"Failed to mute/unmute mic: {e}")
            return False
    
    def check_call_active(self) -> bool:
        """Check if a phone call is currently active."""
        try:
            result = self._run_adb(f"{self.config.TINYMIX} -D {self.config.MIXER_DEVICE} get 'Audio DSP State'", check=False)
            # The ">" marker indicates current state
            return "> Telephony" in result.stdout
        except Exception as e:
            log.error(f"Failed to check call state: {e}")
            return False


class TinyALSAInjector:
    """
    Audio injection into phone calls using TinyALSA.
    
    Converts OpenAI Realtime API audio (24kHz mono PCM16) to the format needed
    for phone call injection.
    """
    
    def __init__(self, device_id: str = None):
        """
        Initialize injector.
        
        Args:
            device_id: ADB device ID (optional, uses first device if None)
        """
        self.device_id = device_id
        self.config = TinyALSAConfig()
        self.converter = AudioConverter()
        self.mixer = TinyALSAMixer(device_id)
        self.injection_process: Optional[asyncio.subprocess.Process] = None
        self._injection_buffer = bytearray()
        self._is_injecting = False
    
    def prepare_audio_chunk(self, audio_data: bytes) -> bytes:
        """
        Convert OpenAI Realtime API audio (24kHz mono) to injection format.
        
        Args:
            audio_data: 24kHz mono PCM16 audio from OpenAI
        
        Returns:
            Stereo PCM16 audio ready for injection
        """
        # Already 24kHz mono - just convert to stereo
        return self.converter.mono_to_stereo(audio_data)
    
    async def inject_audio(self, audio_data: bytes) -> bool:
        """
        Inject audio into an active phone call.
        
        Args:
            audio_data: 24kHz mono PCM16 audio from OpenAI Realtime API
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Convert to stereo
            stereo_data = self.prepare_audio_chunk(audio_data)
            
            # Write to temporary file on device
            with tempfile.NamedTemporaryFile(suffix='.pcm', delete=False) as tmp:
                tmp.write(stereo_data)
                tmp_path = tmp.name
            
            # Push to device
            adb_push = ['adb']
            if self.device_id:
                adb_push.extend(['-s', self.device_id])
            adb_push.extend(['push', tmp_path, self.config.INJECTION_FILE])
            
            result = await asyncio.create_subprocess_exec(
                *adb_push,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await result.communicate()
            
            # Clean up local temp file
            Path(tmp_path).unlink()
            
            if result.returncode != 0:
                log.error("Failed to push audio to device")
                return False
            
            # Play on device 19 with magic rate trick
            adb_play = ['adb']
            if self.device_id:
                adb_play.extend(['-s', self.device_id])
            
            play_cmd = (
                f'su -c "export LD_LIBRARY_PATH={self.config.TINYALSA_DIR} && '
                f'{self.config.TINYPLAY} {self.config.INJECTION_FILE} '
                f'-D {self.config.MIXER_DEVICE} '
                f'-d {self.config.INJECTION_DEVICE} '
                f'-c {self.config.CHANNELS_STEREO} '
                f'-r {self.config.INJECTION_RATE_TOLD} '  # Tell device 16kHz (but it's 24kHz!)
                f'-b {self.config.BITS_PER_SAMPLE}"'
            )
            adb_play.extend(['shell', play_cmd])
            
            result = await asyncio.create_subprocess_exec(
                *adb_play,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await result.communicate()
            
            if result.returncode != 0:
                log.error(f"Injection playback failed: {stderr.decode()}")
                return False
            
            log.debug(f"Injected {len(audio_data)} bytes of audio")
            return True
            
        except Exception as e:
            log.error(f"Audio injection error: {e}")
            return False
    
    async def inject_audio_stream(self, audio_data: bytes):
        """
        Stream audio injection (accumulate and send in chunks).
        
        Args:
            audio_data: Audio chunk to inject
        """
        self._injection_buffer.extend(audio_data)
        
        # Send when we have enough data (e.g., 100ms worth)
        chunk_size = int(self.config.INJECTION_RATE_ACTUAL * 0.1 * 2)  # 100ms, 16-bit
        
        if len(self._injection_buffer) >= chunk_size:
            chunk = bytes(self._injection_buffer[:chunk_size])
            self._injection_buffer = self._injection_buffer[chunk_size:]
            await self.inject_audio(chunk)


class TinyALSACapture:
    """
    Audio capture from phone calls using TinyALSA.
    
    Captures call audio and converts to format suitable for Whisper transcription.
    """
    
    def __init__(self, device_id: str = None):
        """
        Initialize capture.
        
        Args:
            device_id: ADB device ID (optional, uses first device if None)
        """
        self.device_id = device_id
        self.config = TinyALSAConfig()
        self.converter = AudioConverter()
        self.mixer = TinyALSAMixer(device_id)
        self.capture_process: Optional[asyncio.subprocess.Process] = None
        self.is_capturing = False
        self._capture_offset = 0
    
    async def start_capture(self) -> bool:
        """
        Start capturing audio from active phone call.
        
        Returns:
            True if capture started successfully
        """
        try:
            # Enable capture stream
            if not self.mixer.enable_capture():
                return False
            
            # Clean up any existing capture file
            cleanup_cmd = ['adb']
            if self.device_id:
                cleanup_cmd.extend(['-s', self.device_id])
            cleanup_cmd.extend(['shell', f'su -c "rm -f {self.config.CAPTURE_FILE}"'])
            await asyncio.create_subprocess_exec(*cleanup_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            
            # Start tinycap in background
            adb_cap = ['adb']
            if self.device_id:
                adb_cap.extend(['-s', self.device_id])
            
            cap_cmd = (
                f'su -c "export LD_LIBRARY_PATH={self.config.TINYALSA_DIR} && '
                f'{self.config.TINYCAP} {self.config.CAPTURE_FILE} '
                f'-D {self.config.MIXER_DEVICE} '
                f'-d {self.config.CAPTURE_DEVICE} '
                f'-c {self.config.CHANNELS_STEREO} '
                f'-r {self.config.CAPTURE_RATE} '
                f'-b {self.config.BITS_PER_SAMPLE} &"'
            )
            adb_cap.extend(['shell', cap_cmd])
            
            result = await asyncio.create_subprocess_exec(
                *adb_cap,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Give it a moment to start
            await asyncio.sleep(0.1)
            
            self.is_capturing = True
            self._capture_offset = 44  # Skip WAV header
            log.info("Audio capture started")
            return True
            
        except Exception as e:
            log.error(f"Failed to start capture: {e}")
            return False
    
    async def read_capture_chunk(self, chunk_size: int = 4800) -> Optional[bytes]:
        """
        Read a chunk of captured audio and convert to Whisper format.
        
        Args:
            chunk_size: Size of chunk to read (bytes)
        
        Returns:
            16kHz mono PCM16 audio for Whisper, or None if no data available
        """
        if not self.is_capturing:
            return None
        
        try:
            # Check file size
            adb_stat = ['adb']
            if self.device_id:
                adb_stat.extend(['-s', self.device_id])
            adb_stat.extend(['shell', f'su -c "stat -c%s {self.config.CAPTURE_FILE}"'])
            
            result = await asyncio.create_subprocess_exec(
                *adb_stat,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await result.communicate()
            
            try:
                file_size = int(stdout.decode().strip())
            except ValueError:
                return None
            
            # Check if we have new data
            available = file_size - self._capture_offset
            if available < chunk_size:
                return None
            
            # Read chunk from device
            adb_read = ['adb']
            if self.device_id:
                adb_read.extend(['-s', self.device_id])
            adb_read.extend([
                'shell',
                f'su -c "dd if={self.config.CAPTURE_FILE} bs=1 skip={self._capture_offset} count={chunk_size} 2>/dev/null"'
            ])
            
            result = await asyncio.create_subprocess_exec(
                *adb_read,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await result.communicate()
            
            if not stdout:
                return None
            
            # Update offset
            self._capture_offset += len(stdout)
            
            # Convert: 48kHz stereo → 16kHz mono for Whisper
            mono_48k = self.converter.stereo_to_mono(stdout)
            mono_16k = self.converter.resample_simple(
                mono_48k,
                self.config.CAPTURE_RATE,
                self.config.WHISPER_RATE
            )
            
            return mono_16k
            
        except Exception as e:
            log.error(f"Failed to read capture chunk: {e}")
            return None
    
    async def stop_capture(self):
        """Stop audio capture."""
        if not self.is_capturing:
            return
        
        try:
            # Kill tinycap
            adb_kill = ['adb']
            if self.device_id:
                adb_kill.extend(['-s', self.device_id])
            adb_kill.extend(['shell', 'su -c "killall tinycap"'])
            
            await asyncio.create_subprocess_exec(
                *adb_kill,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            self.is_capturing = False
            log.info("Audio capture stopped")
            
        except Exception as e:
            log.error(f"Failed to stop capture: {e}")
    
    async def capture_loop(self, callback: Callable[[bytes], None], chunk_interval: float = 0.1):
        """
        Continuous capture loop that calls callback with audio chunks.
        
        Args:
            callback: Function to call with each captured audio chunk (16kHz mono)
            chunk_interval: How often to poll for new data (seconds)
        """
        # Start capture
        if not await self.start_capture():
            log.error("Failed to start capture loop")
            return
        
        try:
            while self.is_capturing:
                chunk = await self.read_capture_chunk()
                if chunk:
                    callback(chunk)
                await asyncio.sleep(chunk_interval)
        finally:
            await self.stop_capture()


class TinyALSAAudioBridge:
    """
    Complete audio bridge for Bandophone phone calls.
    
    Combines injection and capture with proper mixer control.
    """
    
    def __init__(self, device_id: str = None):
        """
        Initialize audio bridge.
        
        Args:
            device_id: ADB device ID (optional, uses first device if None)
        """
        self.device_id = device_id
        self.mixer = TinyALSAMixer(device_id)
        self.injector = TinyALSAInjector(device_id)
        self.capture = TinyALSACapture(device_id)
        self.is_active = False
    
    async def wait_for_call(self, poll_interval: float = 0.5) -> bool:
        """
        Wait for an active phone call to begin.
        
        Args:
            poll_interval: How often to check for active call (seconds)
        
        Returns:
            True when call is active, False if interrupted
        """
        log.info("Waiting for active phone call...")
        while True:
            if self.mixer.check_call_active():
                log.info("📞 Call detected!")
                return True
            await asyncio.sleep(poll_interval)
    
    async def setup_call(self, mute_mic: bool = True) -> bool:
        """
        Setup audio routing for an active call.
        
        Args:
            mute_mic: Whether to mute the phone's microphone
        
        Returns:
            True if setup successful
        """
        log.info("Setting up call audio routing...")
        
        # Enable capture stream
        if not self.mixer.enable_capture():
            return False
        
        # Optionally mute mic
        if mute_mic:
            if not self.mixer.mute_mic(True):
                log.warning("Failed to mute mic, continuing anyway...")
        
        self.is_active = True
        log.info("✅ Call audio routing ready")
        return True
    
    async def teardown_call(self):
        """Clean up after call ends."""
        if not self.is_active:
            return
        
        log.info("Tearing down call audio...")
        
        # Stop capture if running
        await self.capture.stop_capture()
        
        # Unmute mic
        self.mixer.mute_mic(False)
        
        self.is_active = False
        log.info("Call audio teardown complete")
    
    async def inject(self, audio_data: bytes) -> bool:
        """
        Inject audio into call (convenience method).
        
        Args:
            audio_data: 24kHz mono PCM16 from OpenAI Realtime API
        
        Returns:
            True if successful
        """
        return await self.injector.inject_audio(audio_data)
    
    async def start_capture_loop(self, callback: Callable[[bytes], None]):
        """
        Start continuous audio capture (convenience method).
        
        Args:
            callback: Function to call with captured audio (16kHz mono PCM16)
        """
        await self.capture.capture_loop(callback)


# Example usage
if __name__ == "__main__":
    async def main():
        logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
        
        # Create bridge
        bridge = TinyALSAAudioBridge()
        
        # Wait for call
        await bridge.wait_for_call()
        
        # Setup call audio
        if await bridge.setup_call(mute_mic=True):
            log.info("Bridge ready - call audio active")
        
        # Would now start injection/capture loops
        # ...
        
        # Cleanup
        await bridge.teardown_call()
    
    asyncio.run(main())
