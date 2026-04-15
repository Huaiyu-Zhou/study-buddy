# Build Plan — AI Study Buddy

Ordered by dependency. Each phase produces something runnable so we can test before moving on.

---

## Phase 1 — Foundation
*Goal: project skeleton, config, dependencies installed and importable*

- [ ] `requirements.txt` — pin all dependencies
- [ ] `.env.example` — document required environment variables (`ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`)
- [ ] `config.py` — central settings (intervals, thresholds, model, voice)
- [ ] `session.py` — session state dataclass (plan, snapshot history, off-task timer, last intervention)

**Done when:** `python -c "from session import Session; print(Session())"` works

---

## Phase 2 — Activity Monitor
*Goal: the system can watch what the user is doing*

- [ ] `monitor.py` — capture active process + window title (`pywin32`)
- [ ] `monitor.py` — browser URL extraction for Chrome/Edge (UI Automation)
- [ ] `monitor.py` — idle time detection (`GetLastInputInfo`)
- [ ] `monitor.py` — async tick loop that appends `WindowSnapshot` to session

**Done when:** running the monitor for 60 seconds prints a readable log of what windows were active

---

## Phase 3 — Voice Output
*Goal: the system can speak before it can listen — easier to test coaching*

- [ ] `voice_output.py` — ElevenLabs SDK wrapper, streaming, queued
- [ ] `voice_output.py` — audio playback via `pygame`
- [ ] `voice_output.py` — mic mute/unmute hooks (prevent echo when coach is speaking)
- [ ] Smoke test: make it say "Your study session is starting. Good luck."

**Done when:** calling `speak("hello")` plays audio through speakers

---

## Phase 4 — AI Coach
*Goal: Claude evaluates activity and decides whether to intervene*

- [ ] `coach.py` — build the system prompt (plan + persona + recent snapshots)
- [ ] `coach.py` — call Claude API, parse structured response (`on_task`, `message`)
- [ ] `coach.py` — intervention logic (off-task threshold + cooldown check)
- [ ] `coach.py` — persona definitions (drill sergeant, encouraging friend, Zen mentor, competitive peer)
- [ ] Integration test: feed fake snapshots and verify Claude generates an appropriate message

**Done when:** feeding 5 "YouTube" snapshots to the coach produces a spoken intervention

---

## Phase 5 — Voice Input
*Goal: user can speak back and the coach responds*

- [ ] `voice_input.py` — load `faster-whisper` (`base` model, ~74MB download on first run)
- [ ] `voice_input.py` — run Whisper in thread pool executor (not event loop — it's CPU-bound)
- [ ] `voice_input.py` — VAD loop using silero-vad (built into faster-whisper)
- [ ] `voice_input.py` — skip transcription while TTS is playing (echo prevention)
- [ ] `voice_input.py` — transcribe speech, emit text event
- [ ] `coach.py` — handle user reply: send conversation turn to Claude, speak response

**Done when:** saying "I got distracted, sorry" out loud triggers a spoken coach response

---

## Phase 6 — Session Setup Flow
*Goal: structured start-of-session experience*

- [ ] `main.py` — ask for study plan (voice or typed)
- [ ] `main.py` — ask for persona choice (voice or typed)
- [ ] `main.py` — coach confirms plan back to user and starts monitoring
- [ ] Handle edge cases: no plan given, unclear input

**Done when:** full startup flow works end-to-end from cold launch

---

## Phase 7 — Positive Reinforcement
*Goal: coach also celebrates focus streaks, not just punishes distraction*

- [ ] `session.py` — track continuous on-task duration
- [ ] `coach.py` — trigger encouragement message after N minutes of focus
- [ ] Tune message frequency so it doesn't become annoying

---

## Phase 8 — Polish & Config
*Goal: user-tunable settings, graceful shutdown*

- [ ] CLI flags or `.env` for: persona, off-task threshold, intervention cooldown, whisper model size
- [ ] Graceful shutdown on Ctrl+C with session summary ("You studied for 47 minutes, great work")
- [ ] Error handling: mic not found, API key missing, pywin32 permission errors
- [ ] `README.md` — setup instructions

---

## Parking Lot (post-v1 ideas)
- Session history log (what were you doing, for how long)
- Multiple study blocks / break scheduling
- Web UI for config and session review
- Support for macOS/Linux
- Custom persona builder
