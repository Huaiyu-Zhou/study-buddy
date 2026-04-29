"""Smoke test — Phase 5 full voice loop.

Run: python smoke_voice_input.py

What happens:
  1. Coach speaks an intro prompt.
  2. A listen thread starts — speak into the mic.
  3. Your speech is transcribed and sent to the coach.
  4. The coach responds via TTS.
  5. Press Ctrl+C to end.

Warning: downloads the faster-whisper 'base' model on first run (~150 MB).
"""
import logging
import time

import openai

import config
from pipeline import CoachingPipeline
from session import Session
from voice_pipeline import VoicePipeline

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

session = Session(plan="Review Python async/await", persona="encouraging tutor")
client = openai.OpenAI(
    api_key=config.DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
)
cp = CoachingPipeline(session=session, client=client)
vp = VoicePipeline(coaching_pipeline=cp)

print("Starting voice loop. Speak into your mic. Ctrl+C to stop.")
vp.chat("Your study session is starting. Greet the user in one sentence.")
vp.start_listening()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nSession ended.")
