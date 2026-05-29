import os
import json
from datetime import datetime

HISTORY_FILE = "study_history.json"

def load_history() -> dict:
    """Load study history from JSON file."""
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading history: {e}")
        return {}

def save_history(history: dict) -> None:
    """Save study history to JSON file."""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving history: {e}")

def record_activity(target: str, is_focus: bool, seconds: int) -> None:
    """
    Record study focus seconds and app/domain time consumption for today.
    """
    if not target:
        return
        
    today_str = datetime.now().strftime("%Y-%m-%d")
    history = load_history()
    
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
        
    # Clean target name (e.g. discard subdomains like www. or keep standard name)
    target_clean = target.lower().strip()
    if target_clean.startswith("www."):
        target_clean = target_clean[4:]
        
    if target_clean not in day_data["apps"]:
        day_data["apps"][target_clean] = 0
    day_data["apps"][target_clean] += seconds
    
    save_history(history)
