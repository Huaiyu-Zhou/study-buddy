"""
Smoke test for Phase 4 voice output — hits real Fish Audio + DeepSeek APIs.
Requires FISH_AUDIO_API_KEY, FISH_AUDIO_REFERENCE_ID, and DEEPSEEK_API_KEY in .env.

Usage: python smoke_voice.py
"""
from datetime import datetime, timedelta

import openai

import config
from session import Session, WindowSnapshot
from pipeline import CoachingPipeline
from voice_pipeline import VoicePipeline
from voice_output import speak


def main():
    print("=== Study Buddy — Phase 4 Voice Smoke Test ===\n")

    # Verify keys are set
    if not config.FISH_AUDIO_API_KEY:
        print("ERROR: FISH_AUDIO_API_KEY not set in .env")
        return
    if not config.FISH_AUDIO_REFERENCE_ID:
        print("ERROR: FISH_AUDIO_REFERENCE_ID not set in .env")
        return
    if not config.DEEPSEEK_API_KEY:
        print("ERROR: DEEPSEEK_API_KEY not set in .env")
        return

    # 1. Test raw TTS — speak a fixed string
    print("[Test 1] Raw TTS — speaking fixed text...")
    speak("Your study session is starting. Good luck.")
    print("[Test 1] DONE — did you hear it?\n")

    # 2. Test full voice pipeline — chat produces spoken audio
    print("[Test 2] Voice pipeline — chat turn...")
    session = Session(plan="calculus revision — integration by parts")
    client = openai.OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )
    coaching = CoachingPipeline(session, client)
    voice = VoicePipeline(coaching)

    reply = voice.chat("Hi, I just sat down to study.")
    print(f"[Coach] {reply}\n")

    # 3. Test intervention — watchdog trigger produces spoken audio
    print("[Test 3] Voice intervention — simulating off-task...")
    session.off_task_start = datetime.now() - timedelta(
        seconds=config.OFF_TASK_THRESHOLD_SECONDS + 10
    )
    session.last_intervention = None
    snap = WindowSnapshot(
        timestamp=datetime.now(),
        process="chrome.exe",
        window_title="YouTube - lofi beats",
        url="https://www.youtube.com/watch?v=xyz",
        idle_seconds=0,
        is_on_task=False,
    )
    session.snapshot_history.append(snap)
    reply = voice.maybe_intervene()
    print(f"[Intervention] {reply}\n")

    print("=== Smoke test complete ===")


if __name__ == "__main__":
    main()
