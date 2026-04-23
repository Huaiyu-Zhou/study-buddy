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


# ── maybe_reinforce() ─────────────────────────────────────────────────────────

def test_maybe_reinforce_returns_none_when_streak_short():
    session = Session(plan="calculus")
    session.focus_streak_start = datetime.now() - timedelta(seconds=config.FOCUS_STREAK_THRESHOLD_SECONDS - 60)
    pipeline, client = _pipeline(session)
    assert pipeline.maybe_reinforce() is None
    client.chat.completions.create.assert_not_called()


def test_maybe_reinforce_returns_none_when_no_streak():
    session = Session(plan="calculus")
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
    assert session.focus_streak_seconds() < 5
