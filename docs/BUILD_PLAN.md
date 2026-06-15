# Build Plan — AI Study Buddy

Ordered by dependency. Each phase produces something runnable before moving on.

---

## Phase 1 — Foundation
*Goal: project skeleton, config, dependencies installed and importable*

- [x] `requirements.txt` — pin all dependencies
- [x] `.env.example` — `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `DAILY_API_KEY`, `FISH_AUDIO_API_KEY`
- [x] `config.py` — intervals, thresholds, model names, voice ID, Whisper model size
- [x] `session.py` — session state: plan, persona, snapshot history, off-task timer, distraction count, conversation history, focus streak

**Done when:** `python -c "from session import Session; print(Session())"` works

---

## Phase 2 — Activity Watchdog
*Goal: the system can watch what the user is doing*

- [x] `watchdog.py` — capture active process + window title (`pywin32`)
- [x] `watchdog.py` — browser URL extraction for Chrome/Edge (UI Automation, with fallback)
- [x] `watchdog.py` — idle time detection (`GetLastInputInfo`)
- [x] `watchdog.py` — two-tier classifier: local heuristics first, flag ambiguous cases
- [x] `watchdog.py` — async tick loop, appends `WindowSnapshot` to session

**Done when:** running the watchdog for 60 seconds prints a readable log of windows + on/off-task classification

---

## Phase 3 — Pipecat Pipeline (no voice yet)
*Goal: Pipecat pipeline wired up with OpenAI / gpt-4o-mini, text in / text out*

- [x] `pipeline.py` — Pipecat pipeline setup
- [x] `pipeline.py` — OpenAI / gpt-4o-mini integration with system prompt (plan + persona + conversation history)
- [x] `pipeline.py` — tool call definitions (`set_break`, `change_persona`, `load_wing`, `update_plan`, `get_session_summary`)
- [x] `pipeline.py` — watchdog injection: system message → pipeline when off-task threshold crossed
- [x] `pipeline.py` — cooldown enforcement: minimum time between interventions (uses `last_intervention_timestamp` from session)
- [x] `pipeline.py` — escalation logic: distraction count tracked, tone escalates after repeated offences
- [x] `pipeline.py` — positive reinforcement: trigger unprompted encouragement after configurable focus streak (default 25 min)
- [x] Test: pipe a text message in, get a text response back with tool calls working

**Done when:** sending "I'm on YouTube" as a fake watchdog event produces a coach text response; sending it 3 times escalates the tone; 25-min focus timer triggers encouragement

---

## Phase 4 — Voice Output
*Goal: pipeline speaks*

- [x] Add Fish Audio Turbo TTS to Pipecat pipeline (streaming)
- [x] `voice_output.py` — mic mute/unmute hooks (prevent echo while coach is speaking)
## Phase 4 & 5 — Pipecat Migration
*Goal: full streaming pipeline with barge-in support*

- [x] Update `requirements.txt` to `pipecat-ai[whisper,fish,local,silero]>=0.0.54`
- [x] Refactor `tools.py` to use Pipecat `register_function` pattern
- [x] Implement `StudyBuddyVoicePipeline` using Pipecat `PipelineTask`
- [x] Migrate imports and schemas to Pipecat v1.1.0 standards
- [x] Verify pipeline construction with `smoke_pipecat.py`
- [x] Remove obsolete `pipeline.py`, `voice_input.py`, `voice_output.py`, `mic_control.py`

**Done when:** Pipecat orchestrates the full STT → LLM → TTS loop.

---

## Phase 6 — MemPalace Integration
*Goal: coach has long-term memory across sessions*

- [x] `memory.py` — MemPalace init, wing/room structure per subject
- [x] `memory.py` — wake-up on session start: load relevant history into system prompt
- [x] `memory.py` — write session events (interventions, responses, outcomes) at end of session
- [x] Wire `load_wing` tool call to MemPalace wake-up
- [x] Test: run two sessions on same subject, verify second session coach references first

**Done when:** coach mentions something from a previous session without being told

---

## Phase 7 — Session Setup Flow
*Goal: structured start-of-session experience via Web UI*

- [x] Web dashboard setup form: allow user to input subject, study plan, and select supervisor persona
- [x] Send plan and persona via `/connect` API when starting a session
- [x] Coach dynamically configures its system prompt and begins monitoring based on user selections

**Done when:** user can launch a customized coaching session from the web browser.

---

## Phase 8 — WebRTC Transport Integration
*Goal: low-latency UDP-based audio transport & client-server split*

- [x] Remove PyAudio and local PortAudio dependencies from bot execution environment
- [x] Implement FastAPI server (`server.py`) inside WSL/Linux to serve frontend and manage Daily.co rooms
- [x] Refactor `voice_pipeline.py` to use `DailyTransport` and cloud-based `DeepgramSTTService`
- [x] Build `win_watchdog.py` running on Windows to capture activity and send it to FastAPI server via `/activity`
- [x] Integrate `daily-js` SDK in `templates/index.html` with interactive voice visualizer ring and live stats dashboard

**Done when:** voice coaching works with sub-1.5s latency inside the browser, and the Windows watchdog client successfully triggers real-time voice interventions.

---

## Phase 9 — Polish & Resilience
*Goal: handles real-world failure gracefully*

- [ ] Graceful shutdown: write session summary to MemPalace when user stops coaching
- [ ] Error handling: API key missing warning, connection failure logs, Daily room limits
- [ ] CLI flags / `.env` for: default persona, off-task threshold, cooldown, Fish Audio voice ID
- [ ] `README.md` — setup instructions for client-server WSL setup

---

## Parking Lot (post-v1)
- Custom persona builder
- Multiple study blocks with break scheduling
- Browser extension for richer tab context
- Remote deployment of Bot Server (Linux VPS) with secure WebSocket watchdog tunneling

