"""
Smoke test for Phase 3 pipeline — hits the real DeepSeek API.
Requires DEEPSEEK_API_KEY in .env.

Usage: python smoke_pipeline.py
"""
from datetime import datetime, timedelta
import openai
import config
from session import Session, WindowSnapshot
from pipeline import CoachingPipeline


def main():
    print("=== Study Buddy — Phase 3 Smoke Test ===\n")

    session = Session(plan="calculus revision — integration by parts")
    client = openai.OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )
    pipeline = CoachingPipeline(session, client)

    # 1. Normal chat turn
    reply = pipeline.chat("Hi, I'm about to start studying.")
    print(f"[User]  Hi, I'm about to start studying.")
    print(f"[Coach] {reply}\n")

    # 2. Simulate 3 off-task interventions to trigger escalation
    for i in range(3):
        session.off_task_start = datetime.now() - timedelta(seconds=config.OFF_TASK_THRESHOLD_SECONDS + 10)
        session.last_intervention = None  # bypass cooldown for smoke test
        snap = WindowSnapshot(
            timestamp=datetime.now(),
            process="chrome.exe",
            window_title="YouTube - lofi beats",
            url="https://www.youtube.com/watch?v=xyz",
            idle_seconds=0,
            is_on_task=False,
        )
        session.snapshot_history.append(snap)
        reply = pipeline.maybe_intervene()
        print(f"[Intervention {i + 1}] {reply}\n")

    print(f"Distraction count: {session.distraction_count}  (expected 3)")

    # 3. Simulate focus streak
    session.off_task_start = None
    session.focus_streak_start = datetime.now() - timedelta(seconds=config.FOCUS_STREAK_THRESHOLD_SECONDS + 60)
    session.last_intervention = None
    reply = pipeline.maybe_reinforce()
    print(f"\n[Reinforcement] {reply}")

    # 4. Tool call — change persona via chat
    reply = pipeline.chat("Can you be stricter with me?")
    print(f"\n[User]  Can you be stricter with me?")
    print(f"[Coach] {reply}")
    print(f"Persona: {session.persona}")

    print("\n=== Smoke test complete ===")


if __name__ == "__main__":
    main()
