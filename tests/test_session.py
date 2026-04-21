from datetime import datetime, timedelta
from session import Session, WindowSnapshot

def test_session_default_values():
    s = Session()
    assert s.plan == ""
    assert s.persona == "encouraging friend"
    assert s.snapshot_history == []
    assert s.distraction_count == 0
    assert s.conversation_history == []

def test_off_task_duration_returns_zero_when_not_set():
    s = Session()
    assert s.off_task_duration_seconds() == 0

def test_off_task_duration_returns_elapsed_seconds():
    s = Session()
    s.off_task_start = datetime.now() - timedelta(seconds=65)
    assert 60 <= s.off_task_duration_seconds() <= 70

def test_focus_streak_returns_zero_when_not_set():
    s = Session()
    assert s.focus_streak_seconds() == 0

def test_focus_streak_returns_elapsed_seconds():
    s = Session()
    s.focus_streak_start = datetime.now() - timedelta(seconds=300)
    assert 295 <= s.focus_streak_seconds() <= 310

def test_seconds_since_last_intervention_returns_none_when_not_set():
    s = Session()
    assert s.seconds_since_last_intervention() is None

def test_seconds_since_last_intervention_returns_elapsed():
    s = Session()
    s.last_intervention = datetime.now() - timedelta(seconds=120)
    assert 115 <= s.seconds_since_last_intervention() <= 125

def test_window_snapshot_fields():
    now = datetime.now()
    snap = WindowSnapshot(
        timestamp=now,
        process="chrome.exe",
        window_title="YouTube",
        url="https://youtube.com/watch?v=abc",
        idle_seconds=5,
        is_on_task=False,
    )
    assert snap.process == "chrome.exe"
    assert snap.is_on_task is False

def test_session_repr_works():
    s = Session(plan="calculus revision")
    assert "calculus revision" in repr(s)
