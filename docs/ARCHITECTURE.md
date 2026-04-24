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
│  │  │  Whisper  │───▶│  Claude  │───▶│  Fish Audio Turbo  │  │   │
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

The core voice loop uses **Pipecat** as the orchestrator. Every stage overlaps — TTS begins
speaking before Claude has finished generating, which brings Time-to-First-Audio to
roughly 1.5–3 seconds on CPU (VAD finalization + Whisper inference + Claude first token +
Fish Audio first audio chunk).

```
User speaks
    │
    ▼
[Silero VAD] — detects end of speech (~500ms silence)
    │
    ▼
[faster-whisper] — local transcription (runs in thread pool, not event loop)
    │
    ▼
[Pipecat] — routes text into Claude, manages barge-in
    │
    ▼
[Claude] — streams tokens word-by-word
    │
    ▼
[Fish Audio Turbo] — converts streaming tokens to audio chunks as they arrive
    │
    ▼
Speaker output (user hears coach almost immediately)
```

**Barge-in:** If the user speaks while the coach is talking, Pipecat kills the TTS stream
and immediately routes the new speech through the pipeline. The coach stops mid-sentence.

---

## Activity Detection (The Watchdog)

A lightweight background thread — separate from the Pipecat pipeline — polls the active
window every 30 seconds using `pywin32`.

### What it captures

```python
{
  process: "chrome.exe",
  window_title: "YouTube - lofi hip hop",
  url: "https://www.youtube.com/watch?v=...",  # if browser, via UI Automation
  idle_seconds: 3
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

When the watchdog detects off-task behaviour beyond the threshold, it **injects a system
message directly into the Pipecat pipeline**:

```
[SYSTEM]: User has been on YouTube for 2 minutes. Study plan: revising calculus.
Persona: Drill Sergeant. Intervene now.
```

Claude receives this as a pipeline input and triggers TTS immediately — the coach speaks
without the user saying anything.

---

## Memory System (MemPalace)

**MemPalace** (`pip install mempalace`) is a local-first long-term memory system for AI
agents. It stores verbatim conversation history and retrieves relevant context via semantic
search. No cloud storage — everything stays on the machine.

### Spatial hierarchy

```
Wing: Calculus          ← one per subject / study domain
  Room: Integrals       ← one per specific topic
  Room: Derivatives
Wing: Biology
  Room: Cell division
```

### Session wake-up

At the start of each session, the app runs a wake-up query against the relevant wing to
pull historical context into Claude's system prompt:

```
mempalace wake-up --wing calculus
```

This gives Claude facts like: "User struggles with integration by parts at the 40-minute
mark. Responds better to encouragement than pressure on this topic."

### What gets stored

- The user's exact words (verbatim, not summarised)
- Coach interventions and the user's responses to them
- Session outcomes ("studied 62 minutes, drifted 3 times")
- Persona preferences per subject

---

## Tool Calling

Claude uses **function calling** to perform actions during conversation. This is cleaner
than parsing intent from free text and directly handles many session management needs.

| User says | Claude calls | Python does |
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

- **Voice:** user says "I'm done" / "end session" → Claude calls `end_session()` tool → summary spoken via TTS → session data written to MemPalace → process exits cleanly
- **Ctrl+C:** signal handler catches SIGINT → same summary + MemPalace write path → process exits cleanly

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
- Conversation history (passed to Claude as context each turn)
- Distraction count (for escalation logic — coach gets firmer after repeated offences)

---

## Coach Intelligence

**Classification strategy (two-tier to control API cost):**

1. **Fast local heuristics** — obvious cases classified without calling Claude:
   - Known distractions: `youtube.com`, `netflix.com`, `instagram.com`, `reddit.com`, games
   - Known study tools: `khanacademy.org`, `notion.so`, PDF viewers, IDEs
2. **Claude for ambiguous cases** — anything not in the heuristic lists:
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
It handles the hardest parts of voice pipelines — streaming, barge-in, pipeline
orchestration — without custom plumbing. Using it means we don't reinvent a voice framework.

**Why faster-whisper locally?**
STT runs offline for privacy. Local Whisper means ambient listening doesn't send audio to
any cloud service. Use `base` model (74MB, ~200MB RAM) as default — transcribes short
phrases in 0.5–2s on CPU. Must run in a thread pool executor, not the asyncio event loop.

**Why Fish Audio for TTS?**
Voice quality matters for a coaching persona people will hear for hours. Fish Audio Turbo
supports streaming, so audio begins playing before the full response is generated. Requires
internet + `FISH_AUDIO_API_KEY`. Free tier: 10,000 chars/month.

**Why MemPalace over a simple conversation log?**
A flat log grows unbounded and doesn't support semantic retrieval. MemPalace lets the coach
pull *relevant* history efficiently — what happened last Tuesday in calculus, not the entire
session archive. Verbatim storage means nothing is lost to summarisation.

**Why Claude for coaching, not rule-based logic?**
Rules are brittle. Claude can understand that a YouTube video titled "3Blue1Brown — Calculus
Explained" might be on-task. Context matters, and rules can't encode it.

---

## Tech Stack

| Concern | Library | Notes |
|---|---|---|
| Voice pipeline | `pipecat` | Orchestrates STT → LLM → TTS, handles barge-in |
| Active window | `pywin32` | Windows only |
| Browser URL | `pywin32` UI Automation | Chromium browsers, fragile — fallback to title |
| Idle detection | `pywin32` `GetLastInputInfo` | |
| STT | `faster-whisper` + Silero VAD | Local, CPU-capable, thread pool executor |
| AI coaching | `anthropic` SDK | Claude Sonnet (latest) |
| TTS | `fish_audio` (Turbo) | Streaming, API key required |
| Long-term memory | `mempalace` | Local, ChromaDB + SQLite, verbatim storage |
| Audio playback | `pygame` | Cross-platform |
| Async runtime | `asyncio` | Concurrent watchdog + pipeline |
| Config | `python-dotenv` | API keys from .env |

---

## Requirements

- **Python:** 3.10+
- **OS:** Windows 10 or Windows 11 (pywin32 is Windows-only)
- **Permissions:** pywin32 UI Automation (browser URL extraction) may require running as administrator
- **API keys:** `ANTHROPIC_API_KEY` (required), `FISH_AUDIO_API_KEY` (required for TTS)
- **Internet:** required for Claude API calls and Fish Audio TTS; STT runs fully offline
