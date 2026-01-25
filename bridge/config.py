"""
Bandophone Configuration

Simplified config: voices and settings only, no presets.
"""

from dataclasses import dataclass, field
from typing import Optional
import json
import os

# OpenAI Realtime voice options
VOICES = {
    "alloy": "Neutral, balanced",
    "ash": "Soft, thoughtful", 
    "ballad": "Warm, storytelling",
    "coral": "Bright, friendly",
    "echo": "Warm male",
    "sage": "Calm, wise",
    "shimmer": "Clear female",
    "verse": "Dynamic, engaging"
}

# Default system prompt - positions Realtime as voice interface to Bando
DEFAULT_INSTRUCTIONS = """You are the voice interface for Bando, an AI assistant.

Keep responses conversational and brief - this is a phone call.
When you need to:
- Look something up
- Check calendar, email, or files  
- Run commands or use tools
- Access memory or past context

Call the ask_bando function. It connects to the full Bando system with all capabilities.

For simple chat, respond directly. For anything requiring tools or memory, use ask_bando.

Be natural and friendly. If audio is unclear, ask for clarification."""


@dataclass
class AudioConfig:
    """Audio format configuration."""
    capture_rate: int = 48000      # From Pixel 7 Pro
    openai_rate: int = 24000       # OpenAI Realtime expects 24kHz
    playback_rate: int = 48000     # For injection back to call
    channels: int = 1
    bit_depth: int = 16
    chunk_ms: int = 100
    
    @property
    def capture_chunk_bytes(self) -> int:
        return int(self.capture_rate * self.channels * (self.bit_depth // 8) * self.chunk_ms / 1000)


@dataclass  
class BandophoneConfig:
    """Main configuration."""
    # API Keys
    openai_api_key: str = ""
    clawdbot_url: str = "http://localhost:4440"  # For ask_bando
    clawdbot_session: str = ""  # Session key for Clawdbot
    
    # Voice
    voice: str = "alloy"
    instructions: str = DEFAULT_INSTRUCTIONS
    
    # Audio
    audio: AudioConfig = field(default_factory=AudioConfig)
    
    # Device
    adb_device: Optional[str] = None
    capture_device: int = 20
    playback_device: int = 18
    
    # Features
    save_transcripts: bool = True
    transcripts_dir: str = "transcripts"
    sync_to_clawdbot: bool = True  # Send transcripts to Clawdbot session
    
    # Debug
    verbose: bool = False
    
    @classmethod
    def load(cls, path: str = "bandophone.json") -> "BandophoneConfig":
        """Load config from JSON file."""
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            if "audio" in data:
                data["audio"] = AudioConfig(**data["audio"])
            return cls(**data)
        return cls()
    
    def save(self, path: str = "bandophone.json"):
        """Save config to JSON file."""
        data = {
            "openai_api_key": self.openai_api_key,
            "clawdbot_url": self.clawdbot_url,
            "clawdbot_session": self.clawdbot_session,
            "voice": self.voice,
            "instructions": self.instructions,
            "audio": {
                "capture_rate": self.audio.capture_rate,
                "openai_rate": self.audio.openai_rate,
                "playback_rate": self.audio.playback_rate,
            },
            "adb_device": self.adb_device,
            "capture_device": self.capture_device,
            "playback_device": self.playback_device,
            "save_transcripts": self.save_transcripts,
            "transcripts_dir": self.transcripts_dir,
            "sync_to_clawdbot": self.sync_to_clawdbot,
            "verbose": self.verbose,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


def list_voices():
    """Print available voices."""
    print("Available voices:")
    for voice, desc in VOICES.items():
        print(f"  {voice}: {desc}")
