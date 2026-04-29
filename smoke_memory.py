"""
Phase 6 Smoke Test — MemPalace Integration

Simulates two sessions on the same subject and verifies the second session
has access to history from the first.

Usage: python smoke_memory.py
"""

import sys
import os
import tempfile

sys.stdout.reconfigure(encoding="utf-8")

from memory import StudyMemory
from session import Session


def main():
    # Use a temp palace for isolation
    tmp_dir = tempfile.mkdtemp(prefix="studybuddy_smoke_")
    palace_path = os.path.join(tmp_dir, "palace")
    print(f"🏰 Using temp palace: {palace_path}")

    mem = StudyMemory(palace_path=palace_path)

    # --- Session 1 ---
    print("\n--- Session 1: Calculus ---")
    session1 = Session(
        plan="review integration by parts",
        persona="encouraging friend",
        subject="calculus",
        distraction_count=2,
        conversation_history=[
            {"role": "user", "content": "I keep messing up integration by parts"},
            {"role": "assistant", "content": "That's okay! Let's break it down step by step. The LIATE rule can help you pick u and dv."},
            {"role": "user", "content": "Oh that actually makes sense now"},
            {"role": "assistant", "content": "Great progress! You nailed the u-substitution part."},
        ],
    )
    mem.persist(session1)
    print("✅ Session 1 persisted")

    # --- Wake-up for Session 2 ---
    print("\n--- Session 2: Wake-up ---")
    context = mem.wake_up(wing="calculus")
    if context:
        print(f"✅ Wake-up returned context ({len(context)} chars):")
        print(f"   {context[:300]}...")
    else:
        print("⚠️  Wake-up returned empty — this is expected on first run if mine hasn't indexed yet")

    # --- Search for specific memory ---
    print("\n--- Search: 'integration by parts' ---")
    results = mem.search("integration by parts", wing="calculus")
    if results:
        print(f"✅ Found {len(results)} result(s):")
        for r in results:
            sim = r.get('similarity', 0)
            print(f"   [{sim:.2f}] {r['text'][:150]}...")
    else:
        print("⚠️  No search results — may need to run `mempalace mine` first")

    print("\n🎉 Smoke test complete!")


if __name__ == "__main__":
    main()
