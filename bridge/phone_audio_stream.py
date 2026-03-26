"""
Phone Audio Streaming for Bandophone
Bidirectional audio streaming via TinyALSA

Capture: Stream tinycap stdout via `adb exec-out` (zero file-polling latency)
Inject:  FIFO pipe → persistent tinyplay (no per-chunk push+play overhead)

Audio formats:
  Capture: device 20 @ 48kHz stereo → 24kHz mono for OpenAI Realtime API
  Inject:  24kHz mono from OpenAI → stereo → device 19 @ 16kHz (magic ratio!)
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

# FIFO for inject
INJECT_FIFO = "/data/local/tmp/bandophone_inject.fifo"


class PhoneAudioStream:
    """Bidirectional audio streaming to/from phone calls."""
    
    def __init__(self, device_serial: Optional[str] = None):
        self.device_serial = device_serial
        self.tinyalsa_path = "/data/local/tmp"
        self._running = False
        self._inject_queue: asyncio.Queue = None
        self._inject_task = None
        self._inject_proc = None  # Persistent tinyplay process
        self._inject_writer = None  # FIFO writer process
        
    def _adb_base(self) -> list:
        """Return base ADB command with device serial."""
        cmd = ["adb"]
        if self.device_serial:
            cmd.extend(["-s", self.device_serial])
        return cmd
    
    def _build_shell_cmd(self, cmd: str, as_root: bool = True) -> list:
        """Build full ADB shell command list."""
        adb = self._adb_base()
        if as_root:
            escaped = cmd.replace("'", "'\\''")
            return adb + ["shell", f"su -c '{escaped}'"]
        else:
            return adb + ["shell", cmd]

    def _adb_cmd(self, cmd: str, as_root: bool = True, timeout: int = 10) -> str:
        """Run ADB shell command (BLOCKING — only use for setup, not hot paths)."""
        full = self._build_shell_cmd(cmd, as_root)
        
        for attempt in range(3):
            try:
                result = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
                return result.stdout.strip()
            except subprocess.TimeoutExpired:
                log.warning(f"ADB timeout (attempt {attempt+1}/3): {cmd[:60]}...")
                if attempt < 2:
                    try:
                        subprocess.run(
                            self._adb_base() + ["connect", self.device_serial] if self.device_serial else ["adb", "devices"],
                            capture_output=True, timeout=5
                        )
                    except:
                        pass
                    import time
                    time.sleep(1)
            except Exception as e:
                log.warning(f"ADB error (attempt {attempt+1}/3): {e}")
                if attempt < 2:
                    import time
                    time.sleep(1)
        
        log.error(f"ADB command failed after 3 attempts: {cmd[:60]}...")
        return ""
    
    async def _adb_cmd_async(self, cmd: str, as_root: bool = True, timeout: int = 10, binary: bool = False):
        """Non-blocking ADB shell command. Returns str (or bytes if binary)."""
        full = self._build_shell_cmd(cmd, as_root)
        try:
            proc = await asyncio.create_subprocess_exec(
                *full,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return stdout if binary else stdout.decode('utf-8', errors='replace').strip()
        except asyncio.TimeoutError:
            log.warning(f"Async ADB timeout: {cmd[:60]}...")
            try:
                proc.kill()
            except:
                pass
            return b'' if binary else ''
        except Exception as e:
            log.warning(f"Async ADB error: {e}")
            return b'' if binary else ''
    
    def is_call_active(self) -> bool:
        """Check for active phone call using mCallState.
        mCallState: 0=IDLE, 1=RINGING, 2=OFFHOOK(active/dialing)
        """
        output = self._adb_cmd("dumpsys telephony.registry | grep mCallState", as_root=False)
        return "mCallState=2" in output
    
    def setup_mixer(self):
        """Configure mixer for bidirectional audio."""
        self._adb_cmd(f"{self.tinyalsa_path}/tinymix -D 0 set {MIXER_CAPTURE_STREAM} DL")
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
            if i + 1 < len(samples):
                avg = (samples[i] + samples[i+1]) // 2
                mono.append(avg)
        return struct.pack(f'<{len(mono)}h', *mono)
    
    @staticmethod
    def resample_48k_to_24k(pcm_48k: bytes) -> bytes:
        """Simple 2:1 downsampling from 48kHz to 24kHz."""
        samples = struct.unpack(f'<{len(pcm_48k)//2}h', pcm_48k)
        resampled = samples[::2]
        return struct.pack(f'<{len(resampled)}h', *resampled)
    
    @staticmethod
    def audio_level_db(pcm_data: bytes) -> float:
        """Calculate RMS level in dB for PCM16 audio. Returns -inf for silence."""
        if not pcm_data or len(pcm_data) < 2:
            return float('-inf')
        samples = struct.unpack(f'<{len(pcm_data)//2}h', pcm_data)
        if not samples:
            return float('-inf')
        rms = (sum(s*s for s in samples) / len(samples)) ** 0.5
        if rms < 1:
            return float('-inf')
        import math
        return 20 * math.log10(rms / 32768.0)
    
    @staticmethod
    def apply_gain(pcm_data: bytes, gain_db: float) -> bytes:
        """Apply gain (in dB) to PCM16 audio. Clips at ±32767."""
        if gain_db == 0:
            return pcm_data
        import math
        factor = 10 ** (gain_db / 20.0)
        samples = struct.unpack(f'<{len(pcm_data)//2}h', pcm_data)
        gained = []
        for s in samples:
            v = int(s * factor)
            gained.append(max(-32767, min(32767, v)))
        return struct.pack(f'<{len(gained)}h', *gained)
    
    @staticmethod
    def normalize_audio(pcm_data: bytes, target_db: float = -16.0) -> bytes:
        """Normalize audio to target RMS level. Good for phone speech: -16 to -12 dB.
        Returns original if silence or close to target."""
        level = PhoneAudioStream.audio_level_db(pcm_data)
        if level == float('-inf') or level > -3:  # Silence or already very loud
            return pcm_data
        
        diff = target_db - level
        # Only adjust if more than 3dB off target
        if abs(diff) < 3:
            return pcm_data
        
        # Cap gain adjustment to avoid amplifying noise
        gain = max(-12, min(18, diff))  # -12 to +18 dB range
        return PhoneAudioStream.apply_gain(pcm_data, gain)
    
    # ─── INJECT (AI → Phone Call) ────────────────────────────────────────
    
    async def inject_audio(self, pcm_24k_mono: bytes):
        """Queue audio for injection into the phone call."""
        if self._inject_queue:
            await self._inject_queue.put(pcm_24k_mono)
    
    async def _start_inject_pipe(self):
        """Start persistent FIFO-based inject pipeline.
        
        Architecture:
        1. FIFO created on device
        2. tinyplay reads from FIFO in background (blocks until writer opens)
        3. Persistent `adb shell cat > FIFO` writer with stdin pipe
        4. We write PCM data to writer's stdin → tinyplay plays it continuously
        
        Result: zero per-chunk overhead, no gaps between chunks.
        """
        # Create FIFO
        self._adb_cmd(f"rm -f {INJECT_FIFO}")
        self._adb_cmd(f"mkfifo {INJECT_FIFO}")
        
        # Start tinyplay reading from FIFO in background on device
        # It blocks on FIFO open until writer connects
        play_cmd = (
            f"export LD_LIBRARY_PATH={self.tinyalsa_path} && "
            f"nohup {self.tinyalsa_path}/tinyplay {INJECT_FIFO} "
            f"-D 0 -d {INJECT_DEVICE} -c 2 -r {INJECT_RATE} -b 16 -i raw "
            f"</dev/null >/dev/null 2>&1 &"
        )
        self._adb_cmd(play_cmd)
        
        # Give tinyplay a moment to start and block on FIFO open
        await asyncio.sleep(0.3)
        
        # Open persistent writer to FIFO (this unblocks tinyplay)
        adb = self._adb_base()
        self._inject_writer = await asyncio.create_subprocess_exec(
            *adb, "shell", f"su -c 'cat > {INJECT_FIFO}'",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        log.info("✅ FIFO inject pipeline started (continuous streaming)")
    
    async def _inject_loop(self):
        """Background task: inject audio via FIFO (primary) or per-chunk (fallback)."""
        self._inject_queue = asyncio.Queue()
        buffer = b''
        min_chunk = 24000 * 2 // 10  # 100ms at 24kHz = 4800 bytes
        fifo_mode = False
        
        # Try FIFO mode
        try:
            await self._start_inject_pipe()
            fifo_mode = True
        except Exception as e:
            log.warning(f"FIFO inject setup failed ({e}), using per-chunk fallback")
        
        while self._running:
            try:
                try:
                    chunk = await asyncio.wait_for(self._inject_queue.get(), timeout=0.05)
                    buffer += chunk
                except asyncio.TimeoutError:
                    pass
                
                if len(buffer) >= min_chunk:
                    if fifo_mode and self._inject_writer and self._inject_writer.returncode is None:
                        try:
                            pcm_stereo = self.mono_to_stereo(buffer)
                            self._inject_writer.stdin.write(pcm_stereo)
                            await self._inject_writer.stdin.drain()
                            buffer = b''
                        except (BrokenPipeError, ConnectionResetError, OSError) as e:
                            log.warning(f"FIFO write failed ({e}), switching to per-chunk")
                            fifo_mode = False
                    
                    if not fifo_mode:
                        await self._do_inject_file(buffer)
                        buffer = b''
                    
            except Exception as e:
                log.error(f"Inject error: {e}")
                await asyncio.sleep(0.1)
    
    async def _do_inject_file(self, pcm_24k_mono: bytes):
        """Fallback: push audio file and play via tinyplay (async, non-blocking)."""
        pcm_stereo = self.mono_to_stereo(pcm_24k_mono)
        
        with tempfile.NamedTemporaryFile(suffix='.pcm', delete=False) as f:
            f.write(pcm_stereo)
            temp_path = f.name
        
        try:
            adb = self._adb_base()
            remote_path = "/sdcard/inject.pcm"
            
            proc = await asyncio.create_subprocess_exec(
                *adb, "push", temp_path, remote_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await asyncio.wait_for(proc.communicate(), timeout=5)
            
            cmd = (f"{self.tinyalsa_path}/tinyplay {remote_path} "
                   f"-D 0 -d {INJECT_DEVICE} -c 2 -r {INJECT_RATE} -b 16")
            await self._adb_cmd_async(cmd)
            
        finally:
            os.unlink(temp_path)
    
    # ─── CAPTURE (Phone Call → AI) ───────────────────────────────────────
    
    async def capture_stream(self, 
                            chunk_duration_ms: int = 100,
                            on_audio: Optional[Callable[[bytes], None]] = None
                            ) -> AsyncGenerator[bytes, None]:
        """
        Stream captured audio from phone call via exec-out + tinycap stdout.
        
        Primary: Direct streaming via `adb exec-out` + `tinycap --` (raw PCM to stdout)
        Fallback: File-based capture if streaming fails
        
        Yields 24kHz mono PCM chunks (Realtime API format).
        """
        # Ensure mixer is set
        self._adb_cmd(f"{self.tinyalsa_path}/tinymix -D 0 set {MIXER_CAPTURE_STREAM} DL")
        
        # Kill any existing tinycap
        self._adb_cmd("pkill -9 tinycap")
        await asyncio.sleep(0.2)
        
        # Try streaming mode first, fall back to file mode
        try:
            log.info("Attempting streaming capture (exec-out + tinycap --)...")
            async for chunk in self._capture_streaming(chunk_duration_ms, on_audio):
                yield chunk
        except Exception as e:
            log.warning(f"Streaming capture failed: {e}, falling back to file-based")
            async for chunk in self._capture_file_based(chunk_duration_ms, on_audio):
                yield chunk
    
    async def _capture_streaming(self, chunk_duration_ms: int, on_audio=None):
        """
        Direct streaming: tinycap -- writes raw PCM to stdout, we read via exec-out.
        No file polling, no dd, minimal latency.
        """
        # Chunk size: 48kHz stereo 16-bit for chunk_duration_ms
        bytes_per_frame = 2 * CAPTURE_CHANNELS  # 16-bit * 2 channels = 4 bytes/frame
        frames_per_chunk = int(CAPTURE_RATE * chunk_duration_ms / 1000)
        capture_chunk = frames_per_chunk * bytes_per_frame  # e.g., 19200 bytes for 100ms
        
        adb = self._adb_base()
        
        # Launch tinycap with -- for stdout output (raw PCM, no WAV header!)
        cmd = (
            f"su -c 'export LD_LIBRARY_PATH={self.tinyalsa_path} && "
            f"{self.tinyalsa_path}/tinycap -- "
            f"-D 0 -d {CAPTURE_DEVICE} -c {CAPTURE_CHANNELS} -r {CAPTURE_RATE} -b 16'"
        )
        
        proc = await asyncio.create_subprocess_exec(
            *adb, "exec-out", cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        log.info(f"Streaming capture started (tinycap -- via exec-out, chunk={capture_chunk}b)")
        
        chunks_sent = 0
        
        try:
            while self._running:
                # Read exactly one chunk of raw PCM data
                try:
                    data = await asyncio.wait_for(
                        proc.stdout.readexactly(capture_chunk),
                        timeout=2.0
                    )
                except asyncio.IncompleteReadError as e:
                    if e.partial:
                        data = e.partial
                        log.warning(f"Incomplete read: got {len(data)}/{capture_chunk}")
                        if len(data) < capture_chunk // 2:
                            break
                    else:
                        break
                except asyncio.TimeoutError:
                    log.warning("Capture stream timeout — tinycap may have died")
                    break
                
                if not data:
                    log.warning("Capture stream ended (empty read)")
                    break
                
                chunks_sent += 1
                
                # Convert: 48kHz stereo → 24kHz mono  
                pcm_48k_mono = self.stereo_to_mono(data)
                pcm_24k_mono = self.resample_48k_to_24k(pcm_48k_mono)
                
                # Normalize audio levels for consistent Whisper transcription
                raw_level = self.audio_level_db(pcm_24k_mono)
                pcm_24k_mono = self.normalize_audio(pcm_24k_mono, target_db=-16.0)
                
                if chunks_sent <= 5 or chunks_sent % 50 == 0:
                    norm_level = self.audio_level_db(pcm_24k_mono)
                    log.info(f"📤 Stream chunk #{chunks_sent} ({len(pcm_24k_mono)}b) raw={raw_level:.1f}dB norm={norm_level:.1f}dB")
                
                if on_audio:
                    on_audio(pcm_24k_mono)
                
                yield pcm_24k_mono
                
        finally:
            try:
                proc.kill()
            except:
                pass
            self._adb_cmd("pkill -9 tinycap")
            log.info(f"Streaming capture stopped after {chunks_sent} chunks")
    
    async def _capture_file_based(self, chunk_duration_ms: int, on_audio=None):
        """
        Fallback: File-based capture with async reads.
        Uses tail+head via exec-out for binary-safe fast reads.
        """
        capture_chunk = int(CAPTURE_RATE * 2 * CAPTURE_CHANNELS * chunk_duration_ms / 1000)
        remote_path = "/sdcard/capture_stream.pcm"
        
        # Clean up and start tinycap to file
        self._adb_cmd(f"rm -f {remote_path}")
        
        adb = self._adb_base()
        start_cmd = (
            f"su -c 'export LD_LIBRARY_PATH={self.tinyalsa_path} && "
            f"nohup {self.tinyalsa_path}/tinycap {remote_path} "
            f"-D 0 -d {CAPTURE_DEVICE} -c {CAPTURE_CHANNELS} -r {CAPTURE_RATE} -b 16 "
            f"</dev/null >/dev/null 2>&1 &'"
        )
        subprocess.Popen(
            adb + ["shell", start_cmd],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        log.info(f"File-based capture started: tinycap → {remote_path}")
        
        await asyncio.sleep(0.5)
        
        WAV_HEADER = 44
        read_offset = WAV_HEADER
        chunks_sent = 0
        stall_count = 0
        
        try:
            while self._running:
                # Async file size check
                result = await self._adb_cmd_async(
                    f"stat -c%s {remote_path} 2>/dev/null || echo 0"
                )
                try:
                    file_size = int(result)
                except:
                    await asyncio.sleep(0.05)
                    stall_count += 1
                    if stall_count > 100:
                        log.warning("Capture file not growing")
                        break
                    continue
                
                available = file_size - read_offset
                
                if available >= capture_chunk:
                    stall_count = 0
                    
                    # Use exec-out + tail+head for binary-safe fast reads
                    offset_1indexed = read_offset + 1
                    read_cmd = (
                        f"tail -c +{offset_1indexed} {remote_path} | "
                        f"head -c {capture_chunk}"
                    )
                    
                    chunk_data = await self._adb_cmd_async(read_cmd, binary=True)
                    
                    if chunk_data and len(chunk_data) == capture_chunk:
                        read_offset += capture_chunk
                        chunks_sent += 1
                        
                        pcm_48k_mono = self.stereo_to_mono(chunk_data)
                        pcm_24k_mono = self.resample_48k_to_24k(pcm_48k_mono)
                        
                        # Normalize for consistent Whisper transcription
                        raw_level = self.audio_level_db(pcm_24k_mono)
                        pcm_24k_mono = self.normalize_audio(pcm_24k_mono, target_db=-16.0)
                        
                        if chunks_sent <= 5 or chunks_sent % 20 == 0:
                            norm_level = self.audio_level_db(pcm_24k_mono)
                            log.info(f"📤 File chunk #{chunks_sent} ({len(pcm_24k_mono)}b) offset={read_offset} raw={raw_level:.1f}dB norm={norm_level:.1f}dB")
                        
                        if on_audio:
                            on_audio(pcm_24k_mono)
                        
                        yield pcm_24k_mono
                    else:
                        log.debug(f"Short read: {len(chunk_data) if chunk_data else 0}/{capture_chunk}")
                        await asyncio.sleep(0.02)
                else:
                    stall_count += 1
                    await asyncio.sleep(0.02)
                    
        finally:
            self._adb_cmd("pkill -9 tinycap")
            self._adb_cmd(f"rm -f {remote_path}")
            log.info(f"File-based capture stopped after {chunks_sent} chunks")
    
    # ─── LIFECYCLE ───────────────────────────────────────────────────────
    
    async def start(self):
        """Start bidirectional streaming."""
        self._running = True
        self.setup_mixer()
        self._inject_task = asyncio.create_task(self._inject_loop())
        log.info("Phone audio stream started")
    
    async def stop(self):
        """Stop streaming and clean up all resources."""
        self._running = False
        
        # Close FIFO writer first (signals EOF to tinyplay)
        if self._inject_writer and self._inject_writer.returncode is None:
            try:
                self._inject_writer.stdin.close()
                await asyncio.wait_for(self._inject_writer.wait(), timeout=2)
            except:
                try:
                    self._inject_writer.kill()
                except:
                    pass
        
        # Kill device-side processes
        self._adb_cmd("pkill -9 tinycap")
        self._adb_cmd("pkill -9 tinyplay")
        
        # Clean up FIFO
        self._adb_cmd(f"rm -f {INJECT_FIFO}")
        
        # Cancel inject task
        if self._inject_task:
            self._inject_task.cancel()
        
        # Unmute mic (restore phone to normal)
        self._adb_cmd(f"{self.tinyalsa_path}/tinymix -D 0 set {MIXER_MIC_MUTE} 0")
        
        log.info("Phone audio stream stopped")
    
    async def hangup(self):
        """End the phone call via ADB."""
        log.info("Hanging up call...")
        self._adb_cmd("input keyevent KEYCODE_ENDCALL", as_root=False)


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
            if count >= 100:
                break
        
        await stream.stop()
    
    asyncio.run(test())
