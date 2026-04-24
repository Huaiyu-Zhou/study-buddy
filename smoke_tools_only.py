import openai
import config
from session import Session
from pipeline import CoachingPipeline

def main():
    print("=== DeepSeek Tool Call Test ===\n")

    session = Session(plan="testing tools", persona="friendly coach")
    client = openai.OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )
    pipeline = CoachingPipeline(session, client)

    print(f"Current Persona: {session.persona}")
    
    print("\n[User] Please change your persona to 'drill sergeant'.")
    reply = pipeline.chat("Please change your persona to 'drill sergeant'.")
    
    print(f"[Coach] {reply}")
    print(f"\nFinal Persona: {session.persona}")
    
    if session.persona == "drill sergeant":
        print("\n[SUCCESS] DeepSeek successfully called the 'change_persona' tool!")
    else:
        print("\n[FAILURE] DeepSeek did not call the tool correctly.")

if __name__ == "__main__":
    main()
