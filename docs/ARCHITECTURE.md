# Architecture — AI Study Buddy

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          main.py (orchestrator)                     │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                     Pipecat Pipeline                        │   │
│  │                                                             │   │
│  │  ┌───────────┐    ┌───────────┐    ┌────────────────────┐  │   │
│  │  │  Whisper  │───▶│  OpenAI  │───▶│  Fish Audio Turbo  │  │   │
│  │  │  STT      │    │  (Brain) │    │  TTS (streaming)   │  │   │
│  │  │  + VAD    │    │          │    │                    │  │   │
│  │  └───────────┘    └────┬─────┘    └────────────────────┘  │   │
│  │                        │ tool calls                        │   │
│  └────────────────────────┼──────────────────────────────────┘   │
│                           │                                        │
│         ┌─────────────────┼──────────────────┐                    │
│         ▼                 ▼                  ▼                    │
│   ┌───────────┐    ┌────────────┐    ┌────────────┐               │
│   │ Watchdog  │    │  Session   │    │ MemPalace  │               │
│   │ (pywin32) │───▶│  (state)   │    │ (memory)   │               │
│   └───────────┘    └────────────┘    └────────────┘               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## The Streaming Pipeline

The core voice loop uses **Pipecat** as the orchestrator over a WebRTC connection. Every stage overlaps — TTS begins speaking before the LLM has finished generating, which brings Time-to-First-Audio to roughly 1.0–1.5 seconds (VAD finalization + Deepgram STT cloud inference + OpenAI LLM first token + Fish Audio first audio chunk).

```
User speaks (Browser mic)
    │
    ▼
[Daily.co WebRTC] — streams audio frame-by-frame via UDP to DailyTransport
    │
    ▼
[Silero VAD] — detects end of speech (~300ms silence)
    │
    ▼
[Deepgram STT] — cloud-based transcription with low latency
    │
    ▼
[Pipecat] — routes text into OpenAI LLM, manages barge-in
    │
    ▼
[OpenAI LLM] — streams tokens word-by-word (gpt-4o-mini)
    │
    ▼
[Fish Audio Turbo] — converts streaming tokens to audio chunks as they arrive
    │
    ▼
[Daily.co WebRTC] — streams audio back to user's browser for playback
```

**Barge-in:** If the user speaks while the coach is talking, the WebRTC audio channel detects the interruption, Pipecat kills the TTS stream, and immediately routes the new speech through the pipeline. The coach stops mid-sentence.

---

## Activity Detection (The Watchdog)

The watchdog runs locally on the Windows host as `win_watchdog.py`. It polls the active window using `pywin32` every 5 seconds, and sends a snapshot to the server running in WSL/Linux via an HTTP POST request to `/activity`.

### What it captures

```python
{
  "process": "chrome.exe",
  "window_title": "YouTube - lofi hip hop",
  "url": "https://www.youtube.com/watch?v=...",  # if browser, via UI Automation
  "idle_seconds": 3
}
```

### Three combined signals

**Option A — Active window title + process name**
Always captured. Works for all apps. Sometimes vague (e.g. "New Tab").

**Option B — Browser active tab URL**
Attempted when active process is a Chromium browser. Dramatically more precise.
Fragile: may break across browser updates. Always has a fallback to window title.

**Option C — Idle detection**
`GetLastInputInfo` tracks keyboard/mouse activity. If idle > 3 minutes, pause the
off-task timer — user has stepped away, not distracted.

### Intervention flow

When the `/activity` endpoint on the server receives an update and detects off-task behaviour beyond the threshold, it **injects a system message directly into the Pipecat pipeline**:

```
[SYSTEM]: User has been on YouTube for 2 minutes. Study plan: revising calculus.
Persona: Drill Sergeant. Intervene now.
```

The LLM receives this as a pipeline input and triggers TTS immediately — the coach speaks to the user via the browser's WebRTC audio connection without the user having to say anything.

---

## Memory System (Three-Tier Memory)

The system uses a **Three-Tier Memory System** to manage short-term and long-term context:

1. **Active Session Memory (Working Memory):** The live conversation turns in the current session.
2. **Intra-Day Cache (Short-Term Memory):** Saved in `today_history.json`. It carries over the clean raw conversation turns and list of closed distractions across multiple sessions on the same calendar day.
3. **Long-Term Memory (MemPalace & CoreMemory):**
   * **MemPalace** (`pip install mempalace`) is a local-first memory repository. At the start of a new calendar day (lazy-checked on startup), the system consolidates yesterday's raw cache, runs a reflection summary using the LLM, and writes a single cohesive daily summary (including focus stats, distraction counts, and key conversational arcs) into `MemPalace`'s `general` wing.
   * **CoreMemory** (`core_memory.json`) stores high-level relationship details and facts about the user (e.g. name, preferences) injected into the prompt and updated via tool calls.

### Spatial hierarchy (MemPalace)

```
Wing: Calculus          ← one per subject / study domain
  Room: Integrals       ← one per specific topic
  Room: Derivatives
Wing: Biology
  Room: Cell division
```

### Session wake-up & Daily stats

At the start of each session, the app:
1. Performs date comparison on `today_history.json`. If it's a new day, yesterday's history is consolidated into the `general` wing in MemPalace and the cache is cleared.
2. Restores today's previous chat history from the cache if on the same day.
3. Wakes up context from the relevant subject wing in MemPalace.
4. Queries `study_history.json` for today's app focus stats and closed distractions list, injecting a productivity log directly into the companion's system prompt context.

### What gets stored on teardown

- The active session's conversation turns and closed distraction events are appended to the `today_history.json` cache.
- The `core_memory.json` changes and neural drives are persisted immediately.

---

## Tool Calling

The coach uses **function calling** to perform actions during conversation. This is cleaner
than parsing intent from free text and directly handles many session management needs.

| User says | The LLM calls | Python does |
|---|---|---|
| "I'm taking 5 minutes" | `set_break(minutes=5)` | Pauses watchdog, starts countdown, alerts when done |
| "Be less harsh" | `change_persona("friend")` | Updates system prompt for next turn |
| "Start biology session" | `load_wing("biology")` | Runs MemPalace wake-up for Biology wing |
| "What have I been doing?" | `get_session_summary()` | Returns session stats from state |
| "Update my plan — doing essays now" | `update_plan("essay writing")` | Updates session plan, resets on-task classification |
| "I'm done" / "end session" | `end_session()` | Speaks summary, writes to MemPalace, exits cleanly |

---

## Session End Flow

Two paths to session end — both produce identical outcomes:

- **Voice:** user says "I'm done" / "end session" → the coach calls `end_session()` tool → summary spoken via TTS → session data cached to `today_history.json` → process exits cleanly
- **Ctrl+C:** signal handler catches SIGINT → same summary + cache save path → process exits cleanly

Neither path requires the user to confirm. The coach speaks the summary regardless of how the session ends.

---

## Session State

Tracked in `session.py`, passed to the Pipecat pipeline and watchdog:

- Study plan (mutable mid-session via tool call)
- Chosen persona (mutable via tool call)
- Rolling window snapshot history (last 20 entries)
- Off-task streak duration + timestamp
- Last intervention timestamp (cooldown enforcement)
- Continuous on-task duration (for positive reinforcement)
- Conversation history (passed to the LLM as context each turn)
- Distraction count (for escalation logic — coach gets firmer after repeated offences)

---

## Coach Intelligence

**Classification strategy (two-tier to control API cost):**

1. **Fast local heuristics** — obvious cases classified without calling the LLM:
   - Known distractions: `youtube.com`, `netflix.com`, `instagram.com`, `reddit.com`, games
   - Known study tools: `khanacademy.org`, `notion.so`, PDF viewers, IDEs
2. **The LLM for ambiguous cases** — anything not in the heuristic lists:
   - `discord.com` (study group or chat?)
   - `youtube.com/watch?v=...` with an educational title
   - `google.com` (researching or procrastinating?)

**Escalation:** Distraction count tracked per session. Each repeated offence unlocks a
firmer intervention tier. After 5 distractions, the coach shifts to a reflective mode:
"You've drifted five times — something seems off. What's going on?"

**Positive reinforcement:** After a configurable focus streak (default: 25 minutes
uninterrupted), the coach gives brief encouragement unprompted.

---

## Key Design Decisions

**Why Pipecat?**
It handles the hardest parts of voice pipelines — streaming, barge-in, pipeline orchestration — without custom plumbing. Using it means we don't reinvent a voice framework.

**Why WebRTC (Daily.co)?**
Browser-based WebRTC provides high audio quality, native Echo Cancellation, and leverages UDP instead of TCP, reducing audio latency and jitter. It also completely removes local audio device (PyAudio/PortAudio) installation headaches.

**Why Deepgram for STT?**
Moving STT to the cloud (Deepgram) allows for fast and highly accurate transcriptions (Nova-2 model) at a fraction of the response latency of local Whisper on CPU.

**Why Fish Audio for TTS?**
Voice quality matters for a coaching persona people will hear for hours. Fish Audio Turbo supports streaming, so audio begins playing before the full response is generated. Requires internet + `FISH_AUDIO_API_KEY`. Free tier: 10,000 chars/month.

**Why MemPalace over a simple conversation log?**
A flat log grows unbounded and doesn't support semantic retrieval. MemPalace lets the coach pull *relevant* history efficiently — what happened last Tuesday in calculus, not the entire session archive. Verbatim storage means nothing is lost to summarisation.

**Why GPT-4o-mini for coaching, not rule-based logic?**
Rules are brittle. An LLM can understand that a YouTube video titled "3Blue1Brown — Calculus Explained" might be on-task. Context matters, and rules can't encode it.

---

## Tech Stack

| Concern | Library / Tool | Notes |
|---|---|---|
| Voice transport | `pipecat-ai[daily]` | Connects to Daily.co room for WebRTC audio transport |
| WebRTC Client | `daily-js` (Browser) | Establishes low-latency audio connection in browser |
| Web Server | `fastapi` + `uvicorn` | Serves frontend & connects client to bot session |
| Active window | `pywin32` | Windows host client only |
| Browser URL | `pywin32` UI Automation | Chromium browsers, fragile — fallback to title |
| Idle detection | `pywin32` `GetLastInputInfo` | Windows host client only |
| STT | `deepgram` (Nova-2) | Cloud-based, low latency, smart formatting |
| AI coaching | `openai` (gpt-4o-mini) | Model configured for streaming turn-taking and tools |
| TTS | `fish_audio` (s2-pro) | Streaming, API key required |
| Long-term memory | `mempalace` | Local, ChromaDB + SQLite, verbatim storage |
| Async runtime | `asyncio` | Runs on bot backend for pipeline orchestration |
| Config | `python-dotenv` | API keys from .env |

---

## Requirements

- **Python:** 3.10+
- **OS:** Windows 10 or Windows 11 (for watchdog client); WSL or Linux/macOS (for FastAPI server and Daily transport bot)
- **API keys:** `DAILY_API_KEY`, `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `FISH_AUDIO_API_KEY`
- **Internet:** required for WebRTC streaming, STT, LLM, and TTS services
