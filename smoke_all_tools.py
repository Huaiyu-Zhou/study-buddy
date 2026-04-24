import openai
import config
from session import Session
from pipeline import CoachingPipeline
import os

def check(condition, message):
    if condition:
        print(f"[PASS] {message}")
    else:
        print(f"[FAIL] {message}")

def main():
    print("=== DeepSeek All-Tools Stress Test ===\n")

    session = Session(plan="original plan", persona="original persona")
    client = openai.OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )
    pipeline = CoachingPipeline(session, client)

    # 1. Test update_plan
    print("Testing 'update_plan'...")
    pipeline.chat("I want to change my study plan to 'Mastering Python Decorators'.")
    check(session.plan == "Mastering Python Decorators", "Plan updated to 'Mastering Python Decorators'")

    # 2. Test change_persona
    print("\nTesting 'change_persona'...")
    reply = pipeline.chat("I want you to change your persona to 'encouraging mentor' for the rest of this session.")
    print(f"Coach reply: {reply}")
    check(session.persona == "encouraging mentor", f"Persona is now: {session.persona}")

    # 3. Test set_break
    print("\nTesting 'set_break'...")
    pipeline.chat("I'm feeling tired, can I take a 15 minute break?")
    check(session.is_on_break(), "Session is now on break")

    # 4. Test load_wing (Stub)
    print("\nTesting 'load_wing'...")
    reply = pipeline.chat("Load the memory wing for 'Advanced Algorithms'.")
    check("Advanced Algorithms" in reply, "Coach acknowledged loading memory wing")

    # 5. Test get_session_summary
    print("\nTesting 'get_session_summary'...")
    reply = pipeline.chat("Give me a summary of how I'm doing so far.")
    check("distraction" in reply.lower() or "plan" in reply.lower(), "Coach provided a session summary")

    # 6. Test end_session
    print("\nTesting 'end_session'...")
    pipeline.chat("I'm done for today. Let's wrap up the session.")
    check(session.end_requested == True, "Session end requested")

    print("\n=== All Tools Test Complete ===")

if __name__ == "__main__":
    # Ensure UTF-8 output for Windows console math/symbols
    main()
