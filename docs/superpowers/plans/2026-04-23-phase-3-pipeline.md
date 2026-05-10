# Phase 3: Claude Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up a text-in/text-out coaching pipeline using DeepSeek as the LLM — with tool calling, cooldown enforcement, escalation tiers, and positive reinforcement.

**Architecture:** `CoachingPipeline` in `pipeline.py` wraps the `openai` SDK pointed at DeepSeek's API endpoint. It builds a system prompt from session state, runs a synchronous tool-call loop after each API call, and exposes three public methods: `chat()` for user-initiated turns, `maybe_intervene()` for watchdog-triggered interruptions, and `maybe_reinforce()` for focus-streak encouragement. Tool schemas and handlers live in `tools.py`. No Pipecat yet — Pipecat wraps the pipeline in Phase 4 when voice is added.

**Tech Stack:** `openai` Python SDK (OpenAI-compatible API, pointed at DeepSeek), `pytest` + `pytest-mock`, existing `session.py` / `config.py`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `config.py` | Modify | Add `DEEPSEEK_MODEL` and `DEEPSEEK_API_KEY` constants |
| `requirements.txt` | Modify | Add `openai` package |
| `session.py` | Modify | Add `break_end`, `end_requested`, `is_on_break()` |
| `tools.py` | Create | Tool schemas (OpenAI format) + `handle_tool_call` dispatcher |
| `pipeline.py` | Create | `CoachingPipeline` class |
| `tests/test_tools.py` | Create | Unit tests for all tool handlers |
| `tests/test_pipeline.py` | Create | Unit tests for pipeline logic |
| `smoke_pipeline.py` | Create | Manual smoke test against real DeepSeek API |

---

### Task 1: Extend config and requirements

**Files:**
- Modify: `config.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Write the failing import test**

Create `tests/test_config_phase3.py`:

```python
def test_deepseek_model_is_defined():
    from config import DEEPSEEK_MODEL
    assert isinstance(DEEPSEEK_MODEL, str)
    assert len(DEEPSEEK_MODEL) > 0


def test_deepseek_api_key_is_defined():
    from config import DEEPSEEK_API_KEY
    assert isinstance(DEEPSEEK_API_KEY, str)
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_config_phase3.py -v
```

Expected: `ImportError: cannot import name 'DEEPSEEK_MODEL'`

- [ ] **Step 3: Add DeepSeek constants to config.py**

Open `config.py` and add after the existing API key block (after line 9):

```python
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
```

- [ ] **Step 4: Add openai to requirements.txt**

Append to `requirements.txt`:

```
openai==1.75.0
```

Then install:

```
pip install openai==1.75.0
```

- [ ] **Step 5: Run test to verify it passes**

```
pytest tests/test_config_phase3.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add config.py requirements.txt tests/test_config_phase3.py
git commit -m "feat: add DEEPSEEK_MODEL/DEEPSEEK_API_KEY config constants and openai dependency"
```

---

### Task 2: Extend Session with break state

**Files:**
- Modify: `session.py`
- Create: `tests/test_session_phase3.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_session_phase3.py`:

```python
from datetime import datetime, timedelta
from session import Session


def test_is_on_break_returns_false_when_no_break():
    session = Session()
    assert session.is_on_break() is False


def test_is_on_break_returns_true_when_break_in_future():
    session = Session()
    session.break_end = datetime.now() + timedelta(minutes=5)
    assert session.is_on_break() is True


def test_is_on_break_returns_false_when_break_expired():
    session = Session()
    session.break_end = datetime.now() - timedelta(seconds=1)
    assert session.is_on_break() is False


def test_end_requested_defaults_to_false():
    session = Session()
    assert session.end_requested is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_session_phase3.py -v
```

Expected: `AttributeError: 'Session' object has no attribute 'is_on_break'`

- [ ] **Step 3: Update session.py**

Replace the entire contents of `session.py` with:

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class WindowSnapshot:
    timestamp: datetime
    process: str
    window_title: str
    url: Optional[str]
    idle_seconds: int
    is_on_task: Optional[bool]  # True=on-task, False=off-task, None=ambiguous (send to LLM)


@dataclass
class Session:
    plan: str = ""
    persona: str = "encouraging friend"
    snapshot_history: list[WindowSnapshot] = field(default_factory=list)
    off_task_start: Optional[datetime] = None
    last_intervention: Optional[datetime] = None
    distraction_count: int = 0
    focus_streak_start: Optional[datetime] = None
    conversation_history: list[dict] = field(default_factory=list)
    break_end: Optional[datetime] = None
    end_requested: bool = False

    def off_task_duration_seconds(self) -> int:
        """Seconds the user has been continuously off-task. 0 if currently on-task."""
        if self.off_task_start is None:
            return 0
        return int((datetime.now() - self.off_task_start).total_seconds())

    def focus_streak_seconds(self) -> int:
        """Seconds of uninterrupted on-task focus. 0 if no active streak."""
        if self.focus_streak_start is None:
            return 0
        return int((datetime.now() - self.focus_streak_start).total_seconds())

    def seconds_since_last_intervention(self) -> Optional[int]:
        """Seconds since the coach last intervened. None if no intervention yet."""
        if self.last_intervention is None:
            return None
        return int((datetime.now() - self.last_intervention).total_seconds())

    def is_on_break(self) -> bool:
        """True if the user is currently in a timed break period."""
        if self.break_end is None:
            return False
        return datetime.now() < self.break_end
```

- [ ] **Step 4: Run all tests to verify they pass**

```
pytest tests/test_session_phase3.py tests/test_watchdog.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add session.py tests/test_session_phase3.py
git commit -m "feat: extend Session with break_end, end_requested, and is_on_break()"
```

---

### Task 3: Create tools.py — schemas and handlers

**Files:**
- Create: `tools.py`
- Create: `tests/test_tools.py`

The tool schemas use OpenAI's function-calling format (the same format DeepSeek accepts):

```json
{
  "type": "function",
  "function": {
    "name": "...",
    "description": "...",
    "parameters": { "type": "object", "properties": {...}, "required": [...] }
  }
}
```

- [ ] **Step 1: Write failing tests**

Create `tests/test_tools.py`:

```python
from datetime import datetime, timedelta
from session import Session
import tools


def _session(**kwargs) -> Session:
    s = Session(plan="calculus revision")
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


# --- Schema tests ---

def test_tool_schemas_is_a_list_of_six():
    assert isinstance(tools.TOOL_SCHEMAS, list)
    assert len(tools.TOOL_SCHEMAS) == 6


def test_all_schemas_have_openai_format():
    for schema in tools.TOOL_SCHEMAS:
        assert schema["type"] == "function"
        assert "function" in schema
        assert "name" in schema["function"]
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]


def test_schema_names_are_correct():
    names = {s["function"]["name"] for s in tools.TOOL_SCHEMAS}
    assert names == {
        "set_break", "change_persona", "load_wing",
        "update_plan", "get_session_summary", "end_session",
    }


# --- Handler tests ---

def test_set_break_sets_break_end_on_session():
    session = _session()
    result = tools.handle_tool_call("set_break", {"minutes": 5}, session)
    assert session.is_on_break() is True
    assert "5" in result


def test_change_persona_updates_session():
    session = _session()
    result = tools.handle_tool_call("change_persona", {"persona": "drill sergeant"}, session)
    assert session.persona == "drill sergeant"
    assert "drill sergeant" in result.lower()


def test_load_wing_returns_confirmation_string():
    session = _session()
    result = tools.handle_tool_call("load_wing", {"subject": "biology"}, session)
    assert "biology" in result.lower()


def test_update_plan_updates_session():
    session = _session()
    session.off_task_start = datetime.now() - timedelta(seconds=200)
    result = tools.handle_tool_call("update_plan", {"new_plan": "essay writing"}, session)
    assert session.plan == "essay writing"
    assert session.off_task_start is None  # reset after plan change
    assert "essay writing" in result.lower()


def test_get_session_summary_returns_string_with_distraction_count():
    session = _session()
    session.distraction_count = 3
    result = tools.handle_tool_call("get_session_summary", {}, session)
    assert "3" in result


def test_end_session_sets_end_requested():
    session = _session()
    result = tools.handle_tool_call("end_session", {}, session)
    assert session.end_requested is True
    assert isinstance(result, str)
    assert len(result) > 0


def test_handle_tool_call_raises_for_unknown_tool():
    session = _session()
    try:
        tools.handle_tool_call("nonexistent_tool", {}, session)
        assert False, "Expected ValueError"
    except ValueError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_tools.py -v
```

Expected: `ModuleNotFoundError: No module named 'tools'`

- [ ] **Step 3: Implement tools.py**

Create `tools.py`:

```python
from datetime import datetime, timedelta
from typing import Any
from session import Session


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "set_break",
            "description": "Pause the activity watchdog for a specified number of minutes. Use when the user says they are taking a break.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer", "description": "Length of the break in minutes."}
                },
                "required": ["minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "change_persona",
            "description": "Change your coaching persona for the rest of the session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "persona": {"type": "string", "description": "New persona description (e.g. 'strict coach', 'encouraging friend', 'drill sergeant')."}
                },
                "required": ["persona"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_wing",
            "description": "Load long-term memory for a specific subject or study domain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Subject or domain to load (e.g. 'calculus', 'biology')."}
                },
                "required": ["subject"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_plan",
            "description": "Update the user's study plan for the current session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "new_plan": {"type": "string", "description": "The new study plan description."}
                },
                "required": ["new_plan"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_session_summary",
            "description": "Return a summary of the current session — distractions, focus streak, study plan.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_session",
            "description": "End the study session. Produces a session summary, saves memory, and exits.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


def handle_tool_call(name: str, tool_input: dict[str, Any], session: Session) -> str:
    if name == "set_break":
        return _set_break(tool_input["minutes"], session)
    if name == "change_persona":
        return _change_persona(tool_input["persona"], session)
    if name == "load_wing":
        return _load_wing(tool_input["subject"], session)
    if name == "update_plan":
        return _update_plan(tool_input["new_plan"], session)
    if name == "get_session_summary":
        return _get_session_summary(session)
    if name == "end_session":
        return _end_session(session)
    raise ValueError(f"Unknown tool: {name}")


def _set_break(minutes: int, session: Session) -> str:
    session.break_end = datetime.now() + timedelta(minutes=minutes)
    return f"Break started. I'll check back in {minutes} minute(s)."


def _change_persona(persona: str, session: Session) -> str:
    session.persona = persona
    return f"Persona updated to: {persona}."


def _load_wing(subject: str, session: Session) -> str:
    # MemPalace integration comes in Phase 6 — stub for now
    return f"Memory wing loaded for: {subject}."


def _update_plan(new_plan: str, session: Session) -> str:
    session.plan = new_plan
    session.off_task_start = None  # reset off-task timer — new plan context
    return f"Study plan updated to: {new_plan}."


def _get_session_summary(session: Session) -> str:
    focus_min = session.focus_streak_seconds() // 60
    return (
        f"Session summary: {session.distraction_count} distraction(s) so far. "
        f"Current focus streak: {focus_min} minute(s). "
        f"Study plan: {session.plan}."
    )


def _end_session(session: Session) -> str:
    session.end_requested = True
    return _get_session_summary(session)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_tools.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tools.py tests/test_tools.py
git commit -m "feat: tool schemas (OpenAI format) and handlers for all 6 coaching tools"
```

---

### Task 4: Create pipeline.py — CoachingPipeline with chat()

**Files:**
- Create: `pipeline.py`
- Create: `tests/test_pipeline.py`

The OpenAI-compatible API response structure differs from Anthropic:
- `response.choices[0].finish_reason` — `"stop"` (text) or `"tool_calls"` (tool use)
- `response.choices[0].message.content` — the text string
- `response.choices[0].message.tool_calls` — list of tool calls (or `None`)
- Each tool call: `.id`, `.function.name`, `.function.arguments` (JSON string)

The system prompt is sent as a `{"role": "system", ...}` message prepended to the conversation.

- [ ] **Step 1: Write failing tests**

Create `tests/test_pipeline.py`:

```python
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from session import Session
import config


# ── mock helpers ──────────────────────────────────────────────────────────────

def _mock_text_response(text: str) -> MagicMock:
    message = MagicMock()
    message.content = text
    message.tool_calls = None
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _mock_tool_response(tool_name: str, tool_input: dict, tool_call_id: str = "tc_abc") -> MagicMock:
    tc = MagicMock()
    tc.id = tool_call_id
    tc.function.name = tool_name
    tc.function.arguments = json.dumps(tool_input)

    message = MagicMock()
    message.content = None
    message.tool_calls = [tc]

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "tool_calls"

    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _pipeline(session=None):
    from pipeline import CoachingPipeline
    if session is None:
        session = Session(plan="calculus revision")
    client = MagicMock()
    return CoachingPipeline(session, client), client


# ── build_system_prompt ───────────────────────────────────────────────────────

def test_build_system_prompt_includes_plan():
    pipeline, _ = _pipeline()
    prompt = pipeline.build_system_prompt()
    assert "calculus revision" in prompt


def test_build_system_prompt_includes_persona():
    session = Session(plan="calculus", persona="drill sergeant")
    pipeline, _ = _pipeline(session)
    prompt = pipeline.build_system_prompt()
    assert "drill sergeant" in prompt


def test_build_system_prompt_no_escalation_note_at_zero_distractions():
    pipeline, _ = _pipeline()
    prompt = pipeline.build_system_prompt()
    assert "drifted" not in prompt.lower()


def test_build_system_prompt_escalates_after_five_distractions():
    session = Session(plan="calculus")
    session.distraction_count = 5
    pipeline, _ = _pipeline(session)
    prompt = pipeline.build_system_prompt()
    assert "something seems off" in prompt.lower() or "reflective" in prompt.lower()


# ── chat() ────────────────────────────────────────────────────────────────────

def test_chat_returns_text_from_api():
    pipeline, client = _pipeline()
    client.chat.completions.create.return_value = _mock_text_response("Great, let's get started!")
    result = pipeline.chat("Hi")
    assert result == "Great, let's get started!"


def test_chat_appends_to_conversation_history():
    pipeline, client = _pipeline()
    client.chat.completions.create.return_value = _mock_text_response("Hello!")
    pipeline.chat("Hi there")
    assert pipeline.session.conversation_history[-2] == {"role": "user", "content": "Hi there"}
    assert pipeline.session.conversation_history[-1] == {"role": "assistant", "content": "Hello!"}


def test_chat_handles_tool_call_then_continues():
    session = Session(plan="calculus")
    pipeline, client = _pipeline(session)
    client.chat.completions.create.side_effect = [
        _mock_tool_response("change_persona", {"persona": "strict coach"}, "tc_001"),
        _mock_text_response("I'll be more direct from now on."),
    ]
    result = pipeline.chat("Be stricter with me")
    assert result == "I'll be more direct from now on."
    assert client.chat.completions.create.call_count == 2
    assert session.persona == "strict coach"


def test_chat_sends_system_prompt_as_first_message():
    pipeline, client = _pipeline()
    client.chat.completions.create.return_value = _mock_text_response("Got it.")
    pipeline.chat("new message")
    call_kwargs = client.chat.completions.create.call_args.kwargs
    messages_sent = call_kwargs["messages"]
    assert messages_sent[0]["role"] == "system"
    assert "calculus revision" in messages_sent[0]["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_pipeline.py::test_build_system_prompt_includes_plan tests/test_pipeline.py::test_chat_returns_text_from_api -v
```

Expected: `ModuleNotFoundError: No module named 'pipeline'`

- [ ] **Step 3: Implement pipeline.py**

Create `pipeline.py`:

```python
import json
from datetime import datetime
from typing import Optional

import openai

import config
from session import Session
from tools import TOOL_SCHEMAS, handle_tool_call


def _escalation_note(distraction_count: int) -> str:
    if distraction_count == 0:
        return ""
    if distraction_count <= 2:
        return f"The user has drifted off-task {distraction_count} time(s) this session. Be a bit firmer in your next response."
    if distraction_count <= 4:
        return f"The user has drifted off-task {distraction_count} times. Use a noticeably firmer, more direct tone."
    return (
        f"The user has drifted {distraction_count} times — something seems off. "
        "Shift to a reflective, empathetic mode: ask what's going on rather than just redirecting."
    )


class CoachingPipeline:
    def __init__(self, session: Session, client: openai.OpenAI) -> None:
        self.session = session
        self.client = client

    def build_system_prompt(self) -> str:
        parts = [
            f"You are a study coach with the persona: {self.session.persona}.",
            f"The user's current study plan: {self.session.plan}.",
            "Monitor focus, give brief interventions when the user goes off-task, and celebrate focus streaks.",
            "Keep responses concise — 1-3 sentences unless the user asks for more.",
        ]
        note = _escalation_note(self.session.distraction_count)
        if note:
            parts.append(note)
        return "\n".join(parts)

    def chat(self, user_message: str) -> str:
        """Send a message through the pipeline and return the coach's text reply."""
        self.session.conversation_history.append({"role": "user", "content": user_message})

        messages = [{"role": "system", "content": self.build_system_prompt()}]
        messages.extend(self.session.conversation_history)

        response = self.client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
        )

        while response.choices[0].finish_reason == "tool_calls":
            message = response.choices[0].message
            # Append the assistant's tool-call turn to the running message list
            messages.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in message.tool_calls
                ],
            })
            # Execute each tool and append results
            for tc in message.tool_calls:
                args = json.loads(tc.function.arguments)
                result = handle_tool_call(tc.function.name, args, self.session)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

            response = self.client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=messages,
                tools=TOOL_SCHEMAS,
            )

        text = response.choices[0].message.content or ""
        self.session.conversation_history.append({"role": "assistant", "content": text})
        return text
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_pipeline.py::test_build_system_prompt_includes_plan tests/test_pipeline.py::test_build_system_prompt_includes_persona tests/test_pipeline.py::test_build_system_prompt_no_escalation_note_at_zero_distractions tests/test_pipeline.py::test_build_system_prompt_escalates_after_five_distractions tests/test_pipeline.py::test_chat_returns_text_from_api tests/test_pipeline.py::test_chat_appends_to_conversation_history tests/test_pipeline.py::test_chat_handles_tool_call_then_continues tests/test_pipeline.py::test_chat_sends_system_prompt_as_first_message -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "feat: CoachingPipeline with build_system_prompt and chat() tool loop (DeepSeek/OpenAI SDK)"
```

---

### Task 5: Add maybe_intervene() to pipeline.py

**Files:**
- Modify: `pipeline.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pipeline.py`:

```python
# ── maybe_intervene() ─────────────────────────────────────────────────────────

def test_maybe_intervene_returns_none_when_below_threshold():
    session = Session(plan="calculus")
    session.off_task_start = datetime.now() - timedelta(seconds=config.OFF_TASK_THRESHOLD_SECONDS - 10)
    pipeline, client = _pipeline(session)
    assert pipeline.maybe_intervene() is None
    client.chat.completions.create.assert_not_called()


def test_maybe_intervene_returns_none_when_on_break():
    session = Session(plan="calculus")
    session.off_task_start = datetime.now() - timedelta(seconds=config.OFF_TASK_THRESHOLD_SECONDS + 10)
    session.break_end = datetime.now() + timedelta(minutes=5)
    pipeline, client = _pipeline(session)
    assert pipeline.maybe_intervene() is None
    client.chat.completions.create.assert_not_called()


def test_maybe_intervene_returns_none_during_cooldown():
    session = Session(plan="calculus")
    session.off_task_start = datetime.now() - timedelta(seconds=config.OFF_TASK_THRESHOLD_SECONDS + 10)
    session.last_intervention = datetime.now() - timedelta(seconds=config.INTERVENTION_COOLDOWN_SECONDS - 30)
    pipeline, client = _pipeline(session)
    assert pipeline.maybe_intervene() is None
    client.chat.completions.create.assert_not_called()


def test_maybe_intervene_calls_api_when_threshold_crossed():
    session = Session(plan="calculus")
    session.off_task_start = datetime.now() - timedelta(seconds=config.OFF_TASK_THRESHOLD_SECONDS + 10)
    pipeline, client = _pipeline(session)
    client.chat.completions.create.return_value = _mock_text_response("Stop scrolling and get back to calculus!")
    result = pipeline.maybe_intervene()
    assert result == "Stop scrolling and get back to calculus!"
    assert client.chat.completions.create.called


def test_maybe_intervene_increments_distraction_count():
    session = Session(plan="calculus")
    session.off_task_start = datetime.now() - timedelta(seconds=config.OFF_TASK_THRESHOLD_SECONDS + 10)
    pipeline, client = _pipeline(session)
    client.chat.completions.create.return_value = _mock_text_response("Hey, focus!")
    pipeline.maybe_intervene()
    assert session.distraction_count == 1


def test_maybe_intervene_sets_last_intervention():
    session = Session(plan="calculus")
    session.off_task_start = datetime.now() - timedelta(seconds=config.OFF_TASK_THRESHOLD_SECONDS + 10)
    pipeline, client = _pipeline(session)
    client.chat.completions.create.return_value = _mock_text_response("Hey!")
    pipeline.maybe_intervene()
    assert session.last_intervention is not None
    assert (datetime.now() - session.last_intervention).total_seconds() < 5
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_pipeline.py -k "intervene" -v
```

Expected: `AttributeError: 'CoachingPipeline' object has no attribute 'maybe_intervene'`

- [ ] **Step 3: Add maybe_intervene to pipeline.py**

Add the following method inside `CoachingPipeline` (after the `chat` method):

```python
    def maybe_intervene(self) -> Optional[str]:
        """Trigger a watchdog intervention if conditions are met. Returns coach text or None."""
        if self.session.is_on_break():
            return None
        if self.session.off_task_duration_seconds() < config.OFF_TASK_THRESHOLD_SECONDS:
            return None
        since_last = self.session.seconds_since_last_intervention()
        if since_last is not None and since_last < config.INTERVENTION_COOLDOWN_SECONDS:
            return None

        last_snap = self.session.snapshot_history[-1] if self.session.snapshot_history else None
        context = ""
        if last_snap:
            context = f" ({last_snap.process}"
            if last_snap.url:
                context += f", {last_snap.url}"
            context += ")"

        prompt = (
            f"[WATCHDOG] User has been off-task for {self.session.off_task_duration_seconds()}s"
            f"{context}. Study plan: {self.session.plan}. Intervene now."
        )

        self.session.last_intervention = datetime.now()
        self.session.distraction_count += 1
        return self.chat(prompt)
```

- [ ] **Step 4: Run all intervene tests**

```
pytest tests/test_pipeline.py -k "intervene" -v
```

Expected: all PASS

- [ ] **Step 5: Run full test suite to check for regressions**

```
pytest tests/ -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "feat: CoachingPipeline.maybe_intervene() with cooldown and escalation"
```

---

### Task 6: Add maybe_reinforce() to pipeline.py

**Files:**
- Modify: `pipeline.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pipeline.py`:

```python
# ── maybe_reinforce() ─────────────────────────────────────────────────────────

def test_maybe_reinforce_returns_none_when_streak_short():
    session = Session(plan="calculus")
    session.focus_streak_start = datetime.now() - timedelta(seconds=config.FOCUS_STREAK_THRESHOLD_SECONDS - 60)
    pipeline, client = _pipeline(session)
    assert pipeline.maybe_reinforce() is None
    client.chat.completions.create.assert_not_called()


def test_maybe_reinforce_returns_none_when_no_streak():
    session = Session(plan="calculus")
    # focus_streak_start is None by default
    pipeline, client = _pipeline(session)
    assert pipeline.maybe_reinforce() is None


def test_maybe_reinforce_returns_none_during_cooldown():
    session = Session(plan="calculus")
    session.focus_streak_start = datetime.now() - timedelta(seconds=config.FOCUS_STREAK_THRESHOLD_SECONDS + 60)
    session.last_intervention = datetime.now() - timedelta(seconds=config.INTERVENTION_COOLDOWN_SECONDS - 30)
    pipeline, client = _pipeline(session)
    assert pipeline.maybe_reinforce() is None
    client.chat.completions.create.assert_not_called()


def test_maybe_reinforce_returns_encouragement_when_streak_reached():
    session = Session(plan="calculus")
    session.focus_streak_start = datetime.now() - timedelta(seconds=config.FOCUS_STREAK_THRESHOLD_SECONDS + 60)
    pipeline, client = _pipeline(session)
    client.chat.completions.create.return_value = _mock_text_response("Amazing — 25 minutes of solid focus!")
    result = pipeline.maybe_reinforce()
    assert result == "Amazing — 25 minutes of solid focus!"
    assert client.chat.completions.create.called


def test_maybe_reinforce_resets_focus_streak_after_firing():
    session = Session(plan="calculus")
    session.focus_streak_start = datetime.now() - timedelta(seconds=config.FOCUS_STREAK_THRESHOLD_SECONDS + 60)
    pipeline, client = _pipeline(session)
    client.chat.completions.create.return_value = _mock_text_response("Great job!")
    pipeline.maybe_reinforce()
    # Streak reset so it doesn't fire every tick
    assert session.focus_streak_seconds() < 5
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_pipeline.py -k "reinforce" -v
```

Expected: `AttributeError: 'CoachingPipeline' object has no attribute 'maybe_reinforce'`

- [ ] **Step 3: Add maybe_reinforce to pipeline.py**

Add the following method inside `CoachingPipeline` (after `maybe_intervene`):

```python
    def maybe_reinforce(self) -> Optional[str]:
        """Send unprompted encouragement if the user has sustained a focus streak. Returns coach text or None."""
        if self.session.focus_streak_seconds() < config.FOCUS_STREAK_THRESHOLD_SECONDS:
            return None
        since_last = self.session.seconds_since_last_intervention()
        if since_last is not None and since_last < config.INTERVENTION_COOLDOWN_SECONDS:
            return None

        streak_min = self.session.focus_streak_seconds() // 60
        prompt = (
            f"[WATCHDOG] The user has been focused for {streak_min} minutes without drifting. "
            "Give brief, warm encouragement. One sentence only."
        )

        self.session.last_intervention = datetime.now()
        self.session.focus_streak_start = datetime.now()  # reset so it doesn't fire every tick
        return self.chat(prompt)
```

- [ ] **Step 4: Run all tests**

```
pytest tests/ -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "feat: CoachingPipeline.maybe_reinforce() for focus streak encouragement"
```

---

### Task 7: Smoke test script

**Files:**
- Create: `smoke_pipeline.py`

This script hits the real DeepSeek API. It requires `DEEPSEEK_API_KEY` in `.env`.

- [ ] **Step 1: Add DEEPSEEK_API_KEY to .env**

Open `.env` and add:

```
DEEPSEEK_API_KEY=your_key_here
```

- [ ] **Step 2: Create smoke_pipeline.py**

```python
"""
Smoke test for Phase 3 pipeline — hits the real DeepSeek API.
Requires DEEPSEEK_API_KEY in .env.

Usage: python smoke_pipeline.py
"""
from datetime import datetime, timedelta
import openai
import config
from session import Session, WindowSnapshot
from pipeline import CoachingPipeline


def main():
    print("=== Study Buddy — Phase 3 Smoke Test ===\n")

    session = Session(plan="calculus revision — integration by parts")
    client = openai.OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )
    pipeline = CoachingPipeline(session, client)

    # 1. Normal chat turn
    reply = pipeline.chat("Hi, I'm about to start studying.")
    print(f"[User]  Hi, I'm about to start studying.")
    print(f"[Coach] {reply}\n")

    # 2. Simulate 3 off-task interventions to trigger escalation
    for i in range(3):
        session.off_task_start = datetime.now() - timedelta(seconds=config.OFF_TASK_THRESHOLD_SECONDS + 10)
        session.last_intervention = None  # bypass cooldown for smoke test
        snap = WindowSnapshot(
            timestamp=datetime.now(),
            process="chrome.exe",
            window_title="YouTube - lofi beats",
            url="https://www.youtube.com/watch?v=xyz",
            idle_seconds=0,
            is_on_task=False,
        )
        session.snapshot_history.append(snap)
        reply = pipeline.maybe_intervene()
        print(f"[Intervention {i + 1}] {reply}\n")

    print(f"Distraction count: {session.distraction_count}  (expected 3)")

    # 3. Simulate focus streak
    session.off_task_start = None
    session.focus_streak_start = datetime.now() - timedelta(seconds=config.FOCUS_STREAK_THRESHOLD_SECONDS + 60)
    session.last_intervention = None
    reply = pipeline.maybe_reinforce()
    print(f"\n[Reinforcement] {reply}")

    # 4. Tool call — change persona via chat
    reply = pipeline.chat("Can you be stricter with me?")
    print(f"\n[User]  Can you be stricter with me?")
    print(f"[Coach] {reply}")
    print(f"Persona: {session.persona}")

    print("\n=== Smoke test complete ===")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the smoke test**

```
python smoke_pipeline.py
```

Verify:
- All three interventions fire with progressively firmer tone
- Reinforcement fires and returns encouragement text
- After "Can you be stricter?" the persona field on the session changes (tool call executed)

- [ ] **Step 4: Commit**

```bash
git add smoke_pipeline.py
git commit -m "feat: smoke_pipeline.py — manual end-to-end test for Phase 3 with DeepSeek"
```

---

## Self-Review

**Spec coverage:**

| BUILD_PLAN requirement | Covered by |
|---|---|
| Claude/LLM integration with system prompt (plan + persona + history) | Task 4 — `build_system_prompt`, `chat()` |
| Tool call definitions (set_break, change_persona, load_wing, update_plan, get_session_summary, end_session) | Task 3 — `tools.py` |
| Watchdog injection → pipeline when off-task threshold crossed | Task 5 — `maybe_intervene()` |
| Cooldown enforcement | Task 5 — `maybe_intervene()` cooldown guard |
| Escalation logic — distraction count → firmer tone | Task 4 — `_escalation_note()` in system prompt |
| Positive reinforcement — 25-min focus streak | Task 6 — `maybe_reinforce()` |
| Done-when: fake event → coach text | Task 7 — smoke test |
| Done-when: 3 distractions → escalated tone | Task 7 — smoke test (3 interventions) |
| Done-when: 25-min focus → encouragement | Task 7 — smoke test (reinforcement) |

**Placeholder scan:** None — all steps contain complete code.

**Type consistency:**
- `handle_tool_call(name: str, tool_input: dict, session: Session) -> str` — consistent in tools.py and pipeline.py
- `CoachingPipeline(session: Session, client: openai.OpenAI)` — consistent across pipeline.py and all tests
- `chat(user_message: str) -> str` — consistent usage in `maybe_intervene` and `maybe_reinforce`
- `maybe_intervene() -> Optional[str]` — consistent
- `maybe_reinforce() -> Optional[str]` — consistent
- `Session.is_on_break() -> bool` — defined Task 2, used Task 5
- `Session.break_end: Optional[datetime]` — defined Task 2, set in `_set_break` Task 3
- `Session.end_requested: bool` — defined Task 2, set in `_end_session` Task 3
