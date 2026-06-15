"""History Manager for the AI Study Buddy.

Manages persistent logging of daily study focus durations and application-specific
time metrics to a local JSON file (`study_history.json`). Operates using a lazy-loaded
in-memory cache that flushes updates to disk atomically to prevent file corruption.
"""

import json
import logging
import os
import tempfile
from datetime import datetime

logger = logging.getLogger(__name__)

HISTORY_FILE = "study_history.json"

# In-memory cache — loaded once, flushed periodically
_cache: dict | None = None
_dirty: bool = False


def _load_from_disk() -> dict:
    """Read history JSON from disk (internal)."""
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Error loading history: %s", e)
        return {}


def _ensure_cache() -> dict:
    """Lazy-load the in-memory cache."""
    global _cache
    if _cache is None:
        _cache = _load_from_disk()
    return _cache


def load_history() -> dict:
    """Load study history (cached in memory after first read)."""
    return _ensure_cache()


def save_history(history: dict) -> None:
    """Save study history to JSON file atomically."""
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".json", dir=".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, HISTORY_FILE)
        except BaseException:
            os.unlink(tmp_path)
            raise
    except Exception as e:
        logger.error("Error saving history: %s", e)


def flush() -> None:
    """Write cached history to disk if dirty."""
    global _dirty
    if _dirty and _cache is not None:
        save_history(_cache)
        _dirty = False


def record_activity(target: str, is_focus: bool, seconds: int) -> None:
    """
    Record study focus seconds and app/domain time consumption for today.
    Updates the in-memory cache and marks it dirty for the next flush.
    """
    global _dirty
    if not target:
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    history = _ensure_cache()

    if today_str not in history:
        history[today_str] = {
            "total_focus_seconds": 0,
            "total_session_seconds": 0,
            "apps": {}
        }

    day_data = history[today_str]
    day_data["total_session_seconds"] += seconds
    if is_focus:
        day_data["total_focus_seconds"] += seconds

    # Clean target name
    target_clean = target.lower().strip()
    if target_clean.startswith("www."):
        target_clean = target_clean[4:]

    if target_clean not in day_data["apps"]:
        day_data["apps"][target_clean] = 0
    day_data["apps"][target_clean] += seconds

    _dirty = True
    # Flush every 12 calls (~60s at 5s polling interval)
    if not hasattr(record_activity, "_call_count"):
        record_activity._call_count = 0
    record_activity._call_count += 1
    if record_activity._call_count >= 12:
        record_activity._call_count = 0
        flush()
