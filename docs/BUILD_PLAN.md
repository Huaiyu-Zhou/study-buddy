# Build Plan — AI Study Buddy

Ordered by dependency. Each phase produces something runnable before moving on.

---

## Phase 1 — Foundation
*Goal: project skeleton, config, dependencies installed and importable*

- [x] `requirements.txt` — pin all dependencies
- [x] `.env.example` — `ANTHROPIC_API_KEY`, `FISH_AUDIO_API_KEY`
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
*Goal: Pipecat pipeline wired up with Claude, text in / text out*

- [x] `pipeline.py` — Pipecat pipeline setup
- [x] `pipeline.py` — Claude integration with system prompt (plan + persona + conversation history)
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
*Goal: structured start-of-session experience*

- [ ] `main.py` — first-run check: Whisper model download, API key validation, mic/speaker test
- [ ] `main.py` — ask for study plan (voice or typed)
- [ ] `main.py` — ask for persona choice (voice or typed)
- [ ] Coach confirms plan and begins monitoring
- [ ] Handle: vague plan (coach asks for clarification), no plan given

**Done when:** cold launch to active monitoring session works end-to-end

---

## Phase 8 — Ambiguous Activity Classification & User-Initiated Conversation
*Goal: handle edge cases the heuristics can't — and let the user start conversations*

- [ ] Ambiguous activity: send window snapshot to Claude for classification (anything not in heuristic lists)
- [ ] "What should I do?" — user-initiated conversation supported at any time, not just in response to interventions

**Done when:** opening `discord.com` triggers a Claude classification call (not a heuristic hit); speaking unprompted mid-session gets a natural coach response

---

## Phase 9 — Polish & Resilience
*Goal: handles real-world failure gracefully*

- [ ] Graceful shutdown on Ctrl+C: session summary spoken + written ("62 min studied, 3 distractions")
- [ ] Error handling: mic not found, API key missing, pywin32 permission errors, Fish Audio rate limit
- [ ] CLI flags / `.env` for: persona, off-task threshold, cooldown, Whisper model, Fish Audio voice ID
- [ ] `README.md` — setup instructions

---

## Parking Lot (post-v1)
- Session history log + stats dashboard
- Custom persona builder
- Support for macOS/Linux
- Multiple study blocks with break scheduling
- Browser extension for richer tab context
