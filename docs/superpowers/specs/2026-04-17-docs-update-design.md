---
name: Docs Update — Session End, Requirements, Build Plan Reorder
description: Targeted patches to PRD, ARCHITECTURE, and BUILD_PLAN to fill gaps in session end flow, system requirements, and phase ordering
type: project
---

# Docs Update Design — AI Study Buddy

**Date:** 2026-04-17
**Approach:** Option A — targeted patches to each doc where gaps exist. No restructuring.

---

## PRD.md

**Change:** Feature 7 (Session Summary) — add session end trigger.

The user can end the session via:
- Voice command: "I'm done" / "end session" / similar
- Ctrl+C keyboard interrupt

Both paths deliver the same outcome: spoken summary + MemPalace write.

---

## ARCHITECTURE.md

**Change 1:** Add `end_session()` to the Tool Calling table.

| User says | Claude calls | Python does |
|---|---|---|
| "I'm done" / "end session" | `end_session()` | Speaks summary, writes to MemPalace, exits cleanly |

**Change 2:** Add a "Session End Flow" section after Session State.

Two paths to session end:
- Voice: user says "I'm done" → Claude calls `end_session()` tool → summary spoken → MemPalace write → process exits
- Ctrl+C: signal handler catches SIGINT → same summary + MemPalace write path → process exits

**Change 3:** Add a "Requirements" section to the bottom.

- Python 3.10+
- Windows 10/11 (pywin32 is Windows-only)
- pywin32 UI Automation (browser URL extraction) may require running as administrator
- Fish Audio API key required for TTS
- Anthropic API key required for coaching

---

## BUILD_PLAN.md

**Change 1:** Phase 3 (Pipeline) — add three tasks moved from Phase 8:
- Escalation logic: track distraction count, escalate tone after repeated offences
- Cooldown enforcement: minimum time between interventions
- Positive reinforcement: trigger after configurable focus streak

Rationale: these are part of the core watchdog-to-pipeline flow, not polish. They belong in Phase 3 where the watchdog injection is wired up.

**Change 2:** Phase 8 — rename and narrow scope to:
- "Ambiguous Activity Classification & User-Initiated Conversation"
- Send ambiguous windows to Claude for classification (not covered by local heuristics)
- User-initiated conversation: "What should I do?" supported at any time
