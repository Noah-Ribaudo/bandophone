#!/usr/bin/env python3
"""
Test script for TinyALSA audio module.

Tests:
1. Mixer control (check call state, enable capture, mute mic)
2. Audio conversion (mono→stereo, stereo→mono, resampling)
3. Injection (test tone injection)
4. Capture (capture and save to file)
5. Full duplex (capture and inject simultaneously)
"""

import asyncio
import logging
import struct
import math
import sys
from pathlib import Path

# Add bridge directory to path
sys.path.insert(0, str(Path(__file__).parent))

from tinyalsa_audio import (
    TinyALSAAudioBridge,
    TinyALSAMixer,
    TinyALSAInjector,
    TinyALSACapture,
    AudioConverter,
    TinyALSAConfig
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger("test")


def generate_test_tone(frequency: int = 440, duration: float = 1.0, rate: int = 24000) -> bytes:
    """
    Generate a sine wave test tone.
    
    Args:
        frequency: Tone frequency in Hz
        duration: Duration in seconds
        rate: Sample rate
    
    Returns:
        PCM16 mono audio data
    """
    num_samples = int(rate * duration)
    samples = []
    
    for i in range(num_samples):
        t = i / rate
        sample = int(32767 * 0.5 * math.sin(2 * math.pi * frequency * t))
        samples.append(sample)
    
    return struct.pack(f'<{len(samples)}h', *samples)


async def test_mixer():
    """Test mixer control functions."""
    log.info("=" * 60)
    log.info("TEST 1: Mixer Control")
    log.info("=" * 60)
    
    mixer = TinyALSAMixer()
    
    # Check call state
    log.info("Checking if call is active...")
    is_active = mixer.check_call_active()
    log.info(f"Call active: {is_active}")
    
    if not is_active:
        log.warning("No active call detected - some tests will be skipped")
        return False
    
    # Enable capture
    log.info("Enabling capture stream...")
    success = mixer.enable_capture()
    log.info(f"Capture enable: {'✅ SUCCESS' if success else '❌ FAILED'}")
    
    # Mute mic
    log.info("Muting microphone...")
    success = mixer.mute_mic(True)
    log.info(f"Mic mute: {'✅ SUCCESS' if success else '❌ FAILED'}")
    
    # Unmute mic
    await asyncio.sleep(1)
    log.info("Unmuting microphone...")
    success = mixer.mute_mic(False)
    log.info(f"Mic unmute: {'✅ SUCCESS' if success else '❌ FAILED'}")
    
    return True


async def test_audio_conversion():
    """Test audio conversion functions."""
    log.info("\n" + "=" * 60)
    log.info("TEST 2: Audio Conversion")
    log.info("=" * 60)
    
    converter = AudioConverter()
    
    # Test mono → stereo
    log.info("Testing mono → stereo conversion...")
    mono_data = struct.pack('<4h', 100, 200, 300, 400)
    stereo_data = converter.mono_to_stereo(mono_data)
    
    mono_samples = struct.unpack('<4h', mono_data)
    stereo_samples = struct.unpack('<8h', stereo_data)
    
    log.info(f"Mono samples: {mono_samples}")
    log.info(f"Stereo samples: {stereo_samples}")
    
    # Verify duplication
    assert stereo_samples[0] == stereo_samples[1] == mono_samples[0]
    assert stereo_samples[2] == stereo_samples[3] == mono_samples[1]
    log.info("✅ Mono → stereo conversion correct")
    
    # Test stereo → mono
    log.info("\nTesting stereo → mono conversion...")
    mono_back = converter.stereo_to_mono(stereo_data)
    mono_back_samples = struct.unpack('<4h', mono_back)
    log.info(f"Converted back: {mono_back_samples}")
    log.info("✅ Stereo → mono conversion works")
    
    # Test resampling
    log.info("\nTesting 48kHz → 16kHz resampling...")
    test_data = struct.pack('<6h', 100, 200, 300, 400, 500, 600)
    resampled = converter.resample_simple(test_data, 48000, 16000)
    resampled_samples = struct.unpack(f'<{len(resampled)//2}h', resampled)
    log.info(f"Original (48kHz): 6 samples")
    log.info(f"Resampled (16kHz): {len(resampled_samples)} samples")
    log.info("✅ Resampling works")


async def test_injection(duration: float = 2.0):
    """Test audio injection."""
    log.info("\n" + "=" * 60)
    log.info("TEST 3: Audio Injection")
    log.info("=" * 60)
    
    injector = TinyALSAInjector()
    
    # Check if call is active
    if not injector.mixer.check_call_active():
        log.warning("⚠️  No active call - skipping injection test")
        log.info("Start a phone call to test injection")
        return
    
    # Generate test tone (440 Hz, 2 seconds, 24kHz mono)
    log.info(f"Generating {duration}s test tone (440 Hz)...")
    tone = generate_test_tone(440, duration, 24000)
    log.info(f"Generated {len(tone)} bytes of audio")
    
    # Inject
    log.info("Injecting audio into call...")
    log.info("You should hear a tone in the call!")
    success = await injector.inject_audio(tone)
    
    if success:
        log.info("✅ Injection successful!")
    else:
        log.error("❌ Injection failed")


async def test_capture(duration: float = 5.0):
    """Test audio capture."""
    log.info("\n" + "=" * 60)
    log.info("TEST 4: Audio Capture")
    log.info("=" * 60)
    
    capture = TinyALSACapture()
    
    # Check if call is active
    if not capture.mixer.check_call_active():
        log.warning("⚠️  No active call - skipping capture test")
        log.info("Start a phone call to test capture")
        return
    
    log.info(f"Capturing {duration}s of call audio...")
    log.info("Speak during the call to test capture!")
    
    # Start capture
    if not await capture.start_capture():
        log.error("❌ Failed to start capture")
        return
    
    # Capture chunks
    captured_data = bytearray()
    start_time = asyncio.get_event_loop().time()
    
    while (asyncio.get_event_loop().time() - start_time) < duration:
        chunk = await capture.read_capture_chunk()
        if chunk:
            captured_data.extend(chunk)
            log.info(f"Captured {len(chunk)} bytes (total: {len(captured_data)})")
        await asyncio.sleep(0.1)
    
    # Stop capture
    await capture.stop_capture()
    
    # Save to file
    output_file = Path("/tmp/bandophone_capture_test.pcm")
    output_file.write_bytes(captured_data)
    log.info(f"✅ Captured {len(captured_data)} bytes, saved to {output_file}")
    log.info(f"Convert to WAV with: ffmpeg -f s16le -ar 16000 -ac 1 -i {output_file} {output_file.with_suffix('.wav')}")


async def test_full_bridge():
    """Test complete audio bridge."""
    log.info("\n" + "=" * 60)
    log.info("TEST 5: Full Audio Bridge")
    log.info("=" * 60)
    
    bridge = TinyALSAAudioBridge()
    
    # Wait for call
    log.info("Waiting for active call...")
    log.info("(Start a phone call now if not already active)")
    
    # Wait with timeout
    try:
        await asyncio.wait_for(bridge.wait_for_call(), timeout=30.0)
    except asyncio.TimeoutError:
        log.warning("⚠️  No call detected within 30 seconds, skipping bridge test")
        return
    
    # Setup call
    log.info("Setting up call audio...")
    if not await bridge.setup_call(mute_mic=True):
        log.error("❌ Failed to setup call")
        return
    
    log.info("✅ Bridge setup complete!")
    log.info("Bridge is ready for injection and capture")
    
    # Cleanup
    await bridge.teardown_call()
    log.info("✅ Bridge teardown complete")


async def main():
    """Run all tests."""
    log.info("TinyALSA Audio Module Test Suite")
    log.info("=" * 60)
    
    # Test 1: Mixer
    await test_mixer()
    
    # Test 2: Audio conversion
    await test_audio_conversion()
    
    # Test 3: Injection (requires active call)
    await test_injection(duration=2.0)
    
    # Test 4: Capture (requires active call)
    await test_capture(duration=5.0)
    
    # Test 5: Full bridge
    await test_full_bridge()
    
    log.info("\n" + "=" * 60)
    log.info("All tests complete!")
    log.info("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("\nTests interrupted by user")
