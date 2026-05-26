# Product Requirements Document — AI Study Buddy

## Overview

AI Study Buddy is a proactive AI coaching system that runs in the background while you study. It monitors what you're actually doing on your computer, compares it against what you planned to study, and speaks up — unprompted — when it notices you've gone off track. It behaves like a human study partner who calls you out, encourages you, and keeps you accountable without you having to ask it anything.

---

## Problem

Studying alone is hard. The usual failure mode isn't that people don't know what to study — it's that they drift without noticing. You open one tab, then another, and 20 minutes later you're watching YouTube with no clear moment where you decided to stop studying. No one calls you out. No one notices.

Existing tools (Pomodoro timers, site blockers, focus apps) are passive or blocking. They don't understand context, can't talk to you, and don't adapt.

---

## Target User

Someone studying alone — student, self-learner, professional — who wants an intelligent accountability partner that watches their back without being asked.

---

## Core Features

### 1. Session Setup
- At session start, the user declares their study plan (e.g. "revising calculus for 90 minutes")
- Input can be **typed or spoken** — user's choice
- The coach confirms the plan back and begins monitoring

### 2. Activity Monitoring
- The system continuously observes what the user is doing on their computer
- See [ARCHITECTURE.md](ARCHITECTURE.md) for detection method options and recommendation
- Monitoring runs silently in the background — no visible UI required

### 3. Proactive Coaching
- The coach decides autonomously when to intervene — the user does not trigger it
- Interventions are triggered when the system detects the user has been off-task beyond a configurable threshold
- The coach does not nag constantly — there is a cooldown between interventions
- The coach escalates in firmness after repeated distractions within a session
- The coach can also give positive reinforcement when the user is doing well (e.g. "You've been focused for 40 minutes, solid work")
- Users can speak to the coach proactively at any time — not just in response to interventions

### 4. Voice In / Voice Out
- The coach speaks aloud using text-to-speech (Fish Audio Turbo, streaming)
- The user can speak back naturally — the system listens ambiently via Silero VAD
- No push-to-talk required; the system detects when the user is speaking
- Barge-in supported: speaking while the coach is talking immediately interrupts it
- STT (Deepgram Nova-2) runs in the cloud to optimize latency and integrate with the WebRTC pipeline

### 5. Configurable Persona & Tone
- Users choose the coach's personality at session start (or in settings)
- Examples: strict drill sergeant, encouraging friend, calm Zen mentor, competitive peer
- Persona affects both the language used and how aggressively it intervenes
- Persona can be changed mid-session by voice ("be less harsh")

### 6. Long-Term Memory
- The coach remembers across sessions using MemPalace (local, no cloud)
- Memory is organised by subject (Wing) and topic (Room)
- At session start, relevant history is loaded into the coach's context
- The coach can reference past struggles, patterns, and wins without being told
- Verbatim storage — nothing is lost to summarisation

### 7. Session Summary
- The user ends the session by saying "I'm done" / "end session" (voice command) or pressing Ctrl+C
- Both paths deliver the same outcome: the coach speaks a summary (time studied, distractions, longest focus streak) then exits
- Summary is also written to local storage for MemPalace to reference in future sessions

---

## Out of Scope (v1)

- No screen recording or video capture
- No screenshot analysis or computer vision
- No mobile support
- No cloud sync or multi-device
- No integration with calendars, task managers, or external apps
- No blocking of websites or applications — the coach speaks, it doesn't lock anything

---

## Success Criteria

- The coach correctly identifies off-task behaviour within 2 minutes of it starting
- The coach speaks up without the user doing anything
- The user can have a natural back-and-forth voice conversation with the coach
- The system runs continuously in the background without requiring attention

---

## Non-Functional Requirements

- Runs on Windows (watchdog client and browser UI) and WSL or Linux (FastAPI bot server)
- Low-latency response (Time-to-First-Audio < 1.5 seconds)
- Internet connection required for WebRTC streaming, STT, LLM, and TTS services
- Minimal CPU/memory footprint on Windows host during idle monitoring
