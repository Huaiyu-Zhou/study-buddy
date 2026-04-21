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
    is_on_task: Optional[bool]  # True=on-task, False=off-task, None=ambiguous (send to Claude)


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
