import os
from dotenv import load_dotenv

load_dotenv()

# API keys (unused in Phase 1-2, loaded for later phases)
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
FISH_AUDIO_API_KEY: str = os.getenv("FISH_AUDIO_API_KEY", "")
FISH_AUDIO_REFERENCE_ID: str = os.getenv("FISH_AUDIO_REFERENCE_ID", "")
TTS_OUTPUT_FORMAT: str = "pcm"
TTS_SAMPLE_RATE: int = 44100
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# Watchdog polling
WATCHDOG_INTERVAL_SECONDS: int = 30
IDLE_THRESHOLD_SECONDS: int = 180       # 3 min idle = stepped away, pause off-task timer

# Coaching thresholds
OFF_TASK_THRESHOLD_SECONDS: int = 120       # 2 min off-task before intervention
INTERVENTION_COOLDOWN_SECONDS: int = 300    # 5 min minimum between interventions
FOCUS_STREAK_THRESHOLD_SECONDS: int = 1500  # 25 min focus for positive reinforcement
MAX_DISTRACTION_ESCALATIONS: int = 5        # after this many, coach shifts to reflective mode

# Session history
MAX_SNAPSHOT_HISTORY: int = 20

# Whisper (used in Phase 5)
WHISPER_MODEL_SIZE: str = "base"

# Voice input (Phase 5)
MIC_SAMPLE_RATE: int = 16000          # Whisper expects 16 kHz
MIC_CHUNK_FRAMES: int = 512           # ~32 ms per chunk at 16 kHz
VAD_THRESHOLD: float = 0.5            # Silero VAD confidence threshold
VAD_SILENCE_MS: int = 700             # ms of silence before speech is considered done

# Heuristic classifier — domains classified without calling Claude
KNOWN_DISTRACTION_DOMAINS: set[str] = {
    "youtube.com",
    "netflix.com",
    "instagram.com",
    "reddit.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "facebook.com",
    "twitch.tv",
    "9gag.com",
}

KNOWN_STUDY_DOMAINS: set[str] = {
    "khanacademy.org",
    "notion.so",
    "coursera.org",
    "edx.org",
    "brilliant.org",
    "wolframalpha.com",
    "desmos.com",
    "scholar.google.com",
    "wikipedia.org",
}

# Heuristic classifier — process names (lowercased .exe) classified without Claude
KNOWN_DISTRACTION_PROCESSES: set[str] = {
    "steam.exe",
    "epicgameslauncher.exe",
    "spotify.exe",
}

KNOWN_STUDY_PROCESSES: set[str] = {
    "code.exe",        # VS Code
    "pycharm64.exe",
    "idea64.exe",
    "acrobat.exe",
    "sumatrapdf.exe",
    "obsidian.exe",
    "anki.exe",
}
