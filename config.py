"""Configuration settings and classification rule loaders for the AI Study Buddy.

Defines API credentials, thresholds for session tracking (e.g. idle thresholds, focus streaks),
audio sampling settings, and persistent heuristics for process/website domain classification
(study-related, distractions, or dual-use). Reads environment variables from the `.env` file.
"""

import json
import logging
import os
import tempfile
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

# API keys (unused in Phase 1-2, loaded for later phases)
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
FISH_AUDIO_API_KEY: str = os.getenv("FISH_AUDIO_API_KEY", "")
FISH_AUDIO_REFERENCE_ID: str = os.getenv("FISH_AUDIO_REFERENCE_ID", "")
TTS_OUTPUT_FORMAT: str = "pcm"
TTS_SAMPLE_RATE: int = 44100
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL: str = "gpt-4o-mini"

# Daily.co WebRTC (Phase 8 - WebRTC Transport)
DAILY_API_KEY: str = os.getenv("DAILY_API_KEY", "")
DAILY_API_URL: str = "https://api.daily.co/v1"

# Deepgram (Phase 7 - Cloud STT)
DEEPGRAM_API_KEY: str = os.getenv("DEEPGRAM_API_KEY", "")
DEEPGRAM_MODEL: str = "nova-2"
DEEPGRAM_LANGUAGE: str = "en-US"  # Set to English (US) to transcribe user speech during English coaching sessions

# MemPalace (Phase 6)
MEMPALACE_PALACE_PATH: str = os.getenv("MEMPALACE_PALACE_PATH", os.path.expanduser("~/.mempalace/palace"))

# Watchdog polling
WATCHDOG_INTERVAL_SECONDS: int = 5
IDLE_THRESHOLD_SECONDS: int = 180       # 3 min idle = stepped away, pause off-task timer

# Coaching thresholds
OFF_TASK_THRESHOLD_SECONDS: int = 120       # 2 min off-task before intervention
INTERVENTION_COOLDOWN_SECONDS: int = 300    # 5 min minimum between interventions
FOCUS_STREAK_THRESHOLD_SECONDS: int = 1500  # 25 min focus for positive reinforcement
MAX_DISTRACTION_ESCALATIONS: int = 5        # after this many, coach shifts to reflective mode

# Companion persona
COMPANION_NAME: str = os.getenv("COMPANION_NAME", "Luna")

# Session history
MAX_SNAPSHOT_HISTORY: int = 20

# Voice input (Phase 5)
MIC_SAMPLE_RATE: int = 16000          # Whisper expects 16 kHz
MIC_CHUNK_FRAMES: int = 512           # ~32 ms per chunk at 16 kHz
VAD_THRESHOLD: float = 0.5            # Silero VAD confidence threshold
VAD_SILENCE_MS: int = 700             # ms of silence before speech is considered done

# Audio device selection
# Run: python -c "import pyaudio; p=pyaudio.PyAudio(); [print(i, p.get_device_info_by_index(i)['name']) for i in range(p.get_device_count())]"
# to list available devices and update the indices below.
# Use None to fall back to the system default device.
AUDIO_INPUT_DEVICE_INDEX: int | None = None
AUDIO_OUTPUT_DEVICE_INDEX: int | None = None
AUDIO_DEVICE_SAMPLE_RATE: int = int(os.getenv("AUDIO_DEVICE_SAMPLE_RATE", "16000"))  # SileroVAD requirement

# Heuristic classifier — populated by load_dynamic_rules() on import
KNOWN_DISTRACTION_DOMAINS: set[str] = set()
KNOWN_STUDY_DOMAINS: set[str] = set()
KNOWN_DISTRACTION_PROCESSES: set[str] = set()
KNOWN_STUDY_PROCESSES: set[str] = set()
KNOWN_DUAL_USE_DOMAINS: set[str] = set()
KNOWN_DUAL_USE_PROCESSES: set[str] = set()

# Canonical set of browser process names (used across modules)
BROWSER_PROCESSES: frozenset[str] = frozenset({
    "chrome.exe", "msedge.exe", "brave.exe", "opera.exe",
    "firefox.exe", "safari.exe", "iexplore.exe",
    "librewolf.exe", "floorp.exe", "arc.exe",
})

def strip_www(domain: str) -> str:
    """Remove leading 'www.' from a domain name."""
    return domain[4:] if domain.startswith("www.") else domain


# --- Dynamic Persistence Logic ---

DYNAMIC_RULES_PATH = "watchdog_rules.json"

DEFAULT_RULES = {
    "study_processes": ["code.exe", "pycharm64.exe", "idea64.exe", "acrobat.exe", "sumatrapdf.exe", "obsidian.exe", "anki.exe"],
    "distraction_processes": ["steam.exe", "epicgameslauncher.exe", "spotify.exe"],
    "dual_use_processes": [],
    "study_domains": ["khanacademy.org", "notion.so", "coursera.org", "edx.org", "brilliant.org", "wolframalpha.com", "desmos.com", "scholar.google.com", "wikipedia.org"],
    "distraction_domains": ["netflix.com", "instagram.com", "reddit.com", "twitter.com", "x.com", "tiktok.com", "facebook.com", "twitch.tv", "9gag.com", "spotify.com"],
    "dual_use_domains": ["youtube.com"]
}

def load_dynamic_rules():
    global KNOWN_STUDY_PROCESSES, KNOWN_DISTRACTION_PROCESSES, KNOWN_STUDY_DOMAINS, KNOWN_DISTRACTION_DOMAINS, KNOWN_DUAL_USE_DOMAINS, KNOWN_DUAL_USE_PROCESSES
    
    # Write defaults if watchdog_rules.json doesn't exist or is legacy template
    needs_init = not os.path.exists(DYNAMIC_RULES_PATH)
    if not needs_init:
        try:
            with open(DYNAMIC_RULES_PATH, "r", encoding="utf-8") as f:
                rules = json.load(f)
            if "dual_use_domains" not in rules:
                needs_init = True
        except Exception:
            needs_init = True

    if needs_init:
        try:
            with open(DYNAMIC_RULES_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_RULES, f, indent=2)
        except Exception as e:
            logger.error("Failed to write default rules: %s", e)

    try:
        with open(DYNAMIC_RULES_PATH, "r", encoding="utf-8") as f:
            rules = json.load(f)
        
        # Clear and update existing sets in-place to preserve references across modules
        KNOWN_STUDY_PROCESSES.clear()
        KNOWN_STUDY_PROCESSES.update(rules.get("study_processes", DEFAULT_RULES["study_processes"]))
        
        KNOWN_DISTRACTION_PROCESSES.clear()
        KNOWN_DISTRACTION_PROCESSES.update(rules.get("distraction_processes", DEFAULT_RULES["distraction_processes"]))
        
        KNOWN_DUAL_USE_PROCESSES.clear()
        KNOWN_DUAL_USE_PROCESSES.update(rules.get("dual_use_processes", DEFAULT_RULES["dual_use_processes"]))
        
        KNOWN_STUDY_DOMAINS.clear()
        KNOWN_STUDY_DOMAINS.update(rules.get("study_domains", DEFAULT_RULES["study_domains"]))
        
        KNOWN_DISTRACTION_DOMAINS.clear()
        KNOWN_DISTRACTION_DOMAINS.update(rules.get("distraction_domains", DEFAULT_RULES["distraction_domains"]))
        
        KNOWN_DUAL_USE_DOMAINS.clear()
        KNOWN_DUAL_USE_DOMAINS.update(rules.get("dual_use_domains", DEFAULT_RULES["dual_use_domains"]))
    except Exception as e:
        logger.error("Failed to load dynamic rules: %s", e)

def _save_rules() -> None:
    """Persist current classification sets to disk atomically."""
    rules = {
        "study_processes": sorted(KNOWN_STUDY_PROCESSES),
        "distraction_processes": sorted(KNOWN_DISTRACTION_PROCESSES),
        "dual_use_processes": sorted(KNOWN_DUAL_USE_PROCESSES),
        "study_domains": sorted(KNOWN_STUDY_DOMAINS),
        "distraction_domains": sorted(KNOWN_DISTRACTION_DOMAINS),
        "dual_use_domains": sorted(KNOWN_DUAL_USE_DOMAINS),
    }
    import time
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".json", dir=".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(rules, f, indent=2)
            
            for attempt in range(5):
                try:
                    os.replace(tmp_path, DYNAMIC_RULES_PATH)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        except BaseException:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            raise
    except Exception as e:
        logger.error("Failed to save dynamic rules: %s", e)


def add_dynamic_classification(name: str, is_domain: bool, status: str):
    """Add a target to the dynamic classification lists and persist it."""
    name_lower = name.lower()
    if is_domain:
        name_lower = strip_www(name_lower)

    # Pick the three sets to update (domain vs process)
    if is_domain:
        sets = {"study": KNOWN_STUDY_DOMAINS, "distraction": KNOWN_DISTRACTION_DOMAINS, "dual_use": KNOWN_DUAL_USE_DOMAINS}
    else:
        sets = {"study": KNOWN_STUDY_PROCESSES, "distraction": KNOWN_DISTRACTION_PROCESSES, "dual_use": KNOWN_DUAL_USE_PROCESSES}

    for key, s in sets.items():
        if key == status:
            s.add(name_lower)
        else:
            s.discard(name_lower)

    _save_rules()


def delete_dynamic_classification(name: str, is_domain: bool):
    """Delete a target from all dynamic classification lists and persist it."""
    name_lower = name.lower()
    if is_domain:
        name_lower = strip_www(name_lower)

    for s in (KNOWN_STUDY_DOMAINS, KNOWN_DISTRACTION_DOMAINS, KNOWN_DUAL_USE_DOMAINS) if is_domain else (KNOWN_STUDY_PROCESSES, KNOWN_DISTRACTION_PROCESSES, KNOWN_DUAL_USE_PROCESSES):
        s.discard(name_lower)

    _save_rules()

# Load dynamic rules on module import
load_dynamic_rules()


