# Architecture — AI Study Buddy

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        main.py (orchestrator)               │
│                                                             │
│   ┌──────────────┐    ┌──────────────┐    ┌─────────────┐  │
│   │    Monitor   │───▶│    Session   │◀───│    Coach    │  │
│   │  (activity)  │    │    (state)   │    │  (Claude)   │  │
│   └──────────────┘    └──────────────┘    └──────┬──────┘  │
│                                                   │         │
│   ┌──────────────┐                       ┌────────▼──────┐  │
│   │ Voice Input  │──────────────────────▶│ Voice Output  │  │
│   │  (Whisper)   │                       │  (edge-tts)   │  │
│   └──────────────┘                       └───────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Activity Detection

This is the core sensing problem: how do we know what the user is doing without using a camera or screenshot analysis?

### Option A — Active Window Title + Process Name
Read the currently focused window's title and executable name using the Windows accessibility API (`pywin32`).

- **Examples:** `chrome.exe / "YouTube - lofi beats"`, `notion.exe / "Calculus Notes"`, `discord.exe / "general"`
- **Pros:** Zero privacy concern, very fast, no API cost, works for all apps
- **Cons:** Title alone is sometimes vague (e.g. a Chrome tab titled "New Tab")

### Option B — Browser Active Tab URL
For Chrome and Edge, the current URL can be read via the Windows UI Automation API or by querying the browser's accessibility tree.

- **Examples:** `https://youtube.com/watch?v=...`, `https://khanacademy.org/...`
- **Pros:** Dramatically more precise for browser-based distractions and study tools
- **Cons:** Only works for Chromium browsers; requires extra plumbing; some sites obfuscate titles

### Option C — Idle Detection
Track keyboard and mouse activity to detect if the user is active at all (using `pywin32` `GetLastInputInfo`).

- **Pros:** Simple signal — if no input for 5 mins, user probably left the desk
- **Cons:** Tells you nothing about *what* they're doing, only *whether* they're there

### Recommendation: A + B + C together

Use all three as a combined signal:
1. **Always** capture process + window title (Option A) — the baseline
2. **If the active process is a browser**, also attempt to read the URL (Option B)
3. **Track idle time** (Option C) — if idle, pause off-task timer (user is away, not distracted)

This gives the coach a rich, structured snapshot each tick:
```
{
  process: "chrome.exe",
  window_title: "YouTube - lofi hip hop",
  url: "https://www.youtube.com/watch?v=jfKfPfyJRdk",  // if available
  idle_seconds: 3
}
```

---

## Components

### monitor.py — Activity Monitor
- Runs on a timer (default: every 20 seconds)
- Captures: active process, window title, browser URL (if applicable), idle time
- Appends a `WindowSnapshot` to the session history
- Emits an event when a new snapshot is ready

### session.py — Session State
- Holds the user's study plan, session start time
- Tracks rolling snapshot history (last N entries)
- Tracks how long the user has been continuously off-task
- Tracks when the coach last spoke (for cooldown enforcement)

### coach.py — AI Coach (Claude)
- Receives the study plan + recent activity history
- Sends a structured prompt to Claude asking two things:
  1. Is the user currently on-task or off-task? Why?
  2. If the coach should speak — what should it say, given the chosen persona?
- Claude's response drives the intervention decision
- API calls only happen when the off-task threshold is crossed (not on every tick)

### voice_input.py — Speech-to-Text
- Runs `faster-whisper` locally in a background thread
- Ambient listening — detects speech automatically using VAD (voice activity detection)
- Transcribes the user's response and passes it to the coach for a reply

### voice_output.py — Text-to-Speech
- Uses `elevenlabs` Python SDK (high-quality neural voices)
- Streams audio for low latency (~200–400ms to first audio)
- Queues speech so multiple messages don't overlap
- Mutes the microphone while speaking to prevent echo (coach's voice being transcribed as user input)
- Requires internet + `ELEVENLABS_API_KEY`
- Free tier: 10,000 characters/month — sufficient for light use, may need paid plan for heavy daily use

### main.py — Orchestrator
- Handles session setup (ask for plan, choose persona)
- Starts the monitor loop and voice listener as async tasks
- Connects events: new snapshot → coach evaluation → optional intervention

---

## Data Flow

```
1. User sets plan ("revise calculus, 90 mins") via voice or text
2. Monitor ticks every 20s → captures WindowSnapshot → appends to session
3. Session checks: has user been off-task for > threshold?
   - YES + cooldown elapsed → trigger coach
   - NO → do nothing
4. Coach sends to Claude: plan + last 5 snapshots + persona
5. Claude returns: { on_task, reasoning, message }
6. If intervention: voice_output speaks the message
7. Voice input detects user reply → coach sends follow-up to Claude → voice_output responds
```

---

## Key Design Decisions

**Why no screenshots?**
Simpler, faster, cheaper (no vision API cost per tick), and better for privacy. Window titles + URLs are sufficient to distinguish "reading a textbook PDF" from "watching YouTube".

**Why Claude for the coaching decision, not just rule-based logic?**
Rule-based logic ("if youtube.com → off task") is brittle. Claude can understand nuance: a YouTube video about the topic you're studying might be on-task. A Discord message to a study group might be fine. Context matters.

**Why faster-whisper locally?**
Voice input needs to work without internet and without latency. A local Whisper model on CPU is good enough for conversational speech. Use `base` model as default — 74MB, ~200MB RAM, transcribes short phrases in 0.5–2 seconds on CPU. Must run in a thread pool executor, not the asyncio event loop, to avoid blocking the monitor tick.

**Why ElevenLabs for TTS?**
Voice quality matters significantly for a coaching persona — a natural-sounding voice is more engaging and less annoying over long sessions. ElevenLabs produces noticeably more human speech than alternatives. Streams audio for low latency. Requires internet and an API key (free tier: 10,000 chars/month).

---

## Tech Stack

| Concern | Library | Notes |
|---|---|---|
| Active window | `pywin32` | Windows only |
| Browser URL | `pywin32` UI Automation | Chromium browsers |
| Idle detection | `pywin32` `GetLastInputInfo` | |
| AI coaching | `anthropic` SDK | Claude Sonnet |
| STT | `faster-whisper` | Local, CPU-capable |
| TTS | `elevenlabs` | Streaming, API key required, 10k chars/month free |
| Audio playback | `pygame` | Cross-platform |
| Async runtime | `asyncio` | Concurrent monitor + voice |
| Config | `python-dotenv` | API key from .env |
