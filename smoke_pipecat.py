"""Smoke test — verify the Pipecat pipeline can be constructed without errors.

This does NOT start the audio loop (requires mic/speakers).
It validates that all imports, service constructors, and tool registration work.

Run:  python smoke_pipecat.py
"""

import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import config
from session import Session


def main():
    print("=== Pipecat Pipeline Smoke Test ===\n")

    # 1. Check API keys
    print("1. Checking API keys...")
    assert config.DEEPSEEK_API_KEY, "DEEPSEEK_API_KEY is empty"
    assert config.FISH_AUDIO_API_KEY, "FISH_AUDIO_API_KEY is empty"
    assert config.FISH_AUDIO_REFERENCE_ID, "FISH_AUDIO_REFERENCE_ID is empty"
    print("   [OK] All API keys present\n")

    # 2. Verify pipecat imports
    print("2. Verifying Pipecat imports...")
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContext,
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.services.fish.tts import FishAudioTTSService
    from pipecat.services.whisper.stt import WhisperSTTService
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.frames.frames import LLMRunFrame
    print("   [OK] All Pipecat modules importable\n")

    # 3. Construct services (does NOT call any API)
    print("3. Constructing services...")
    llm = OpenAILLMService(
        api_key=config.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
        settings=OpenAILLMService.Settings(
            model=config.DEEPSEEK_MODEL,
        ),
    )
    tts = FishAudioTTSService(
        api_key=config.FISH_AUDIO_API_KEY,
        settings=FishAudioTTSService.Settings(
            voice=config.FISH_AUDIO_REFERENCE_ID,
        ),
    )
    print("   [OK] LLM and TTS services created\n")

    # 4. Register tools
    print("4. Registering tools...")
    session = Session(plan="smoke test", persona="encouraging friend")
    from tools import TOOL_SCHEMAS, register_tools
    register_tools(llm, session)
    print(f"   [OK] {len(TOOL_SCHEMAS)} tools registered\n")

    # 5. Create context
    from pipecat.adapters.schemas.tools_schema import AdapterType
    from pipecat.processors.aggregators.llm_response_universal import ToolsSchema
    context = LLMContext(
        messages=[{"role": "system", "content": "You are a study coach."}],
        tools=ToolsSchema(standard_tools=[], custom_tools={AdapterType.OPENAI: TOOL_SCHEMAS}),
    )
    print(f"   [OK] Context created with {len(context.messages)} message(s)\n")

    # 6. Verify StudyBuddyVoicePipeline can be instantiated
    print("6. Constructing StudyBuddyVoicePipeline...")
    from voice_pipeline import StudyBuddyVoicePipeline
    vp = StudyBuddyVoicePipeline(session)
    print("   [OK] Pipeline object created\n")

    print("=== All smoke checks passed! ===")
    print("(Audio loop not started — run with a mic/speakers to test live.)")


if __name__ == "__main__":
    main()
