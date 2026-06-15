from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import config


@dataclass
class WindowSnapshot:
    """Represents a single point-in-time capture of the user's active window and focus state.

    Attributes:
        timestamp: The datetime when this snapshot was taken.
        process: Name of the foreground process (e.g. 'chrome.exe', 'spotify.exe').
        window_title: Title of the foreground window.
        url: Active browser tab URL (if process is a supported browser and retrieval succeeds).
        idle_seconds: Seconds of user inactivity (no mouse/keyboard input) detected on the host.
        is_on_task: Classification: True=on-task, False=off-task, None=ambiguous (sent to LLM).
        pid: Process Identifier (PID) of the foreground window process.
    """
    timestamp: datetime
    process: str
    window_title: str
    url: Optional[str]
    idle_seconds: int
    is_on_task: Optional[bool]  # True=on-task, False=off-task, None=ambiguous (send to LLM)
    pid: Optional[int] = None


@dataclass
class Session:
    """Manages state, goals, thresholds, and history for a single Study Buddy session.

    Attributes:
        plan: The user's study plan or goal for this session.
        persona: The active companion persona/attitude.
        subject: The academic/work subject being studied (e.g., 'calculus').
        session_start: The datetime when the session began.
        snapshot_history: Deque of recent WindowSnapshots to track focus trends.
        off_task_start: Timestamp when the user began their current off-task streak.
        last_intervention: Timestamp of the last companion warning/check-in.
        distraction_count: Cumulative count of distractions detected in the session.
        focus_streak_start: Timestamp when the user began their current focus streak.
        conversation_history: List of role/content chat turns in the active session.
        break_end: Timestamp when the user's current scheduled break period ends.
        end_requested: Flag indicating that the user/bot requested to end the session.
        control_laptop: Flag indicating whether distracting processes should be terminated.
        ai_coaching: Flag indicating if the Pipecat WebRTC audio loop is enabled.
        session_allowed_targets: Temp overrides of allowed process/domain names for this session.
        session_denied_targets: Temp overrides of blocked process/domain names for this session.
        queried_targets: Set of unclassified target names already queried to avoid repeating.
        persisted: Flag indicating if the session has been saved/consolidated to memory.
        closed_distractions: List of dicts recording auto-terminated distraction processes.
    """
    plan: str = ""
    persona: str = "Warm emotional companion"
    subject: str = ""
    session_start: datetime = field(default_factory=datetime.now)
    snapshot_history: deque = field(default_factory=lambda: deque(maxlen=config.MAX_SNAPSHOT_HISTORY))
    off_task_start: Optional[datetime] = None
    last_intervention: Optional[datetime] = None
    distraction_count: int = 0
    focus_streak_start: Optional[datetime] = None
    conversation_history: list[dict] = field(default_factory=list)
    break_end: Optional[datetime] = None
    end_requested: bool = False
    control_laptop: bool = False
    ai_coaching: bool = True
    session_allowed_targets: set[str] = field(default_factory=set)
    session_denied_targets: set[str] = field(default_factory=set)
    queried_targets: set[str] = field(default_factory=set)
    persisted: bool = False
    closed_distractions: list[dict] = field(default_factory=list)

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
