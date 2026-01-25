"""
Bandophone Configuration

Centralized config for voices, personalities, and audio settings.
"""

from dataclasses import dataclass, field
from typing import Optional
import json
import os

# OpenAI Realtime voice options
VOICES = {
    "alloy": "Neutral, balanced voice",
    "echo": "Warm, conversational male voice", 
    "shimmer": "Clear, expressive female voice",
    "ash": "Soft, thoughtful voice",
    "ballad": "Warm, storytelling voice",
    "coral": "Bright, friendly voice",
    "sage": "Calm, wise voice",
    "verse": "Dynamic, engaging voice"
}

# Preset personalities
PERSONALITIES = {
    "assistant": {
        "name": "Bando",
        "voice": "alloy",
        "instructions": """You are Bando, a helpful AI assistant on a phone call.
Keep responses brief and natural - this is a voice conversation, not text.
Be warm, friendly, and conversational. Ask clarifying questions if needed.
If the audio is unclear, politely ask them to repeat."""
    },
    "receptionist": {
        "name": "Alex",
        "voice": "coral",
        "instructions": """You are Alex, a professional receptionist.
Answer calls politely, take messages, and help callers reach the right person.
Be efficient but friendly. Collect name, callback number, and reason for call.
If the person they're looking for isn't available, offer to take a message."""
    },
    "concierge": {
        "name": "Morgan",
        "voice": "sage",
        "instructions": """You are Morgan, a personal concierge assistant.
Help with reservations, appointments, and information lookup.
Be proactive in offering suggestions. Confirm all details before ending the call.
Speak with confidence and warmth."""
    },
    "screener": {
        "name": "Sam", 
        "voice": "echo",
        "instructions": """You are Sam, a call screener.
Your job is to determine if the call is important or spam.
Ask who is calling, what company they're from, and the purpose of the call.
Be polite but efficient. Report your assessment at the end."""
    }
}


@dataclass
class AudioConfig:
    """Audio format configuration."""
    capture_rate: int = 48000      # From Pixel 7 Pro
    openai_rate: int = 24000       # OpenAI Realtime expects 24kHz
    playback_rate: int = 48000     # For injection back to call
    channels: int = 1
    bit_depth: int = 16
    chunk_ms: int = 100            # Chunk size in milliseconds
    
    @property
    def capture_chunk_bytes(self) -> int:
        return int(self.capture_rate * self.channels * (self.bit_depth // 8) * self.chunk_ms / 1000)
    
    @property
    def openai_chunk_bytes(self) -> int:
        return int(self.openai_rate * self.channels * (self.bit_depth // 8) * self.chunk_ms / 1000)


@dataclass  
class BandophoneConfig:
    """Main configuration."""
    # API
    openai_api_key: str = ""
    
    # Personality
    personality: str = "assistant"
    custom_instructions: Optional[str] = None
    voice: str = "alloy"
    
    # Audio
    audio: AudioConfig = field(default_factory=AudioConfig)
    
    # Device
    adb_device: Optional[str] = None  # None = auto-detect
    capture_device: int = 20           # PCM device for capture
    playback_device: int = 18          # PCM device for playback
    
    # Behavior
    auto_answer: bool = False          # Auto-answer incoming calls
    transcribe_only: bool = False      # Just transcribe, no AI response
    save_recordings: bool = True       # Save call recordings
    recordings_dir: str = "recordings"
    
    # Logging
    verbose: bool = False
    log_file: Optional[str] = None
    
    @classmethod
    def load(cls, path: str = "bandophone.json") -> "BandophoneConfig":
        """Load config from JSON file."""
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            
            # Handle nested audio config
            if "audio" in data:
                data["audio"] = AudioConfig(**data["audio"])
            
            return cls(**data)
        return cls()
    
    def save(self, path: str = "bandophone.json"):
        """Save config to JSON file."""
        data = {
            "openai_api_key": self.openai_api_key,
            "personality": self.personality,
            "custom_instructions": self.custom_instructions,
            "voice": self.voice,
            "audio": {
                "capture_rate": self.audio.capture_rate,
                "openai_rate": self.audio.openai_rate,
                "playback_rate": self.audio.playback_rate,
                "channels": self.audio.channels,
                "bit_depth": self.audio.bit_depth,
                "chunk_ms": self.audio.chunk_ms,
            },
            "adb_device": self.adb_device,
            "capture_device": self.capture_device,
            "playback_device": self.playback_device,
            "auto_answer": self.auto_answer,
            "transcribe_only": self.transcribe_only,
            "save_recordings": self.save_recordings,
            "recordings_dir": self.recordings_dir,
            "verbose": self.verbose,
            "log_file": self.log_file,
        }
        
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    
    def get_instructions(self) -> str:
        """Get the system instructions for the AI."""
        if self.custom_instructions:
            return self.custom_instructions
        
        personality = PERSONALITIES.get(self.personality, PERSONALITIES["assistant"])
        return personality["instructions"]
    
    def get_voice(self) -> str:
        """Get the voice to use."""
        if self.voice:
            return self.voice
        
        personality = PERSONALITIES.get(self.personality, PERSONALITIES["assistant"])
        return personality["voice"]


def list_voices():
    """Print available voices."""
    print("Available voices:")
    for voice, desc in VOICES.items():
        print(f"  {voice}: {desc}")


def list_personalities():
    """Print available personalities."""
    print("Available personalities:")
    for name, config in PERSONALITIES.items():
        print(f"  {name}: {config['name']} ({config['voice']})")
        print(f"    {config['instructions'][:80]}...")
        print()
