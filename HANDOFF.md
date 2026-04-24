# Project Handoff & State (AI Study Buddy)

## Current Status (As of Phase 4 Completion)
The project has successfully completed **Phase 4: Voice Output**. 

We have shifted the text-to-speech architecture from **ElevenLabs** to **Fish Audio**. The core components currently implemented and passing tests are:
- **Phase 1 (Foundation):** Core data models (`session.py`) and config management.
- **Phase 2 (Watchdog):** Activity monitoring (capturing window titles, URLs, idle time).
- **Phase 3 (Pipeline Logic):** LLM integration using DeepSeek for the coaching logic, intervention rules, and tool calls.
- **Phase 4 (Voice Output):** Fish Audio streaming TTS integrated with `pyaudio` for real-time PCM playback. Microphone muting is implemented during speech to prevent feedback.

## Next Steps
- **Phase 5 (Voice Input):** Implement STT using `faster-whisper`, integrate Silero VAD for voice activity detection, and fully wire Pipecat to allow bidirectional voice (barge-in support).

## Important Environment Variables (`.env`)
To run the system, you **MUST** configure the following variables in your `.env` file:
```env
ANTHROPIC_API_KEY=your_anthropic_key # Or DeepSeek key if using DeepSeek (currently set up for DeepSeek in config)
DEEPSEEK_API_KEY=your_deepseek_key
FISH_AUDIO_API_KEY=your_fish_audio_api_key
FISH_AUDIO_REFERENCE_ID=your_chosen_voice_model_id
```
*Note: We experienced a `402 Insufficient Balance` error when testing Fish Audio with the current API key. Ensure the Fish Audio account has sufficient credits.*

## Key Files & Entry Points
- `config.py`: Centralized configuration (thresholds, API keys).
- `watchdog.py`: Monitors user activity.
- `pipeline.py`: Core logic for the LLM coach to evaluate activity and intervene.
- `voice_output.py`: Fish Audio + PyAudio integration.
- `smoke_voice.py` / `test_pipeline_audio.py`: Standalone scripts to test the voice output pipeline.

## Known Issues / Gotchas
- **Encoding Issues:** When running in Windows terminals, print statements with emojis may cause `UnicodeEncodeError`. Use `sys.stdout.reconfigure(encoding='utf-8')` if necessary, which is currently applied in `test_pipeline_audio.py`.
- **Microphone Control:** The `pycaw` library is used to mute the microphone during TTS playback. This requires Windows.

*If picking this up on a new machine, remember to run `pip install -r requirements.txt` and populate your `.env` file first!*
