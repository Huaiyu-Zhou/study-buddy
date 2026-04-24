# AI Study Buddy — Phase 1 & 2: Foundation + Watchdog

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the session state model and activity watchdog — the foundation layer that detects what the user is doing on their computer, with zero API dependencies.

**Architecture:** `session.py` holds the Session dataclass (mutable state shared across the app) and WindowSnapshot (one poll result). `config.py` centralises all constants and loads `.env`. `watchdog.py` polls the active window every 30 seconds, classifies it using local heuristics, appends to session history, and calls a callback when the user goes off-task. All Win32 calls are isolated in small, mockable functions so tests run without a real Windows GUI context.

**Tech Stack:** Python 3.10+, pywin32, psutil, comtypes, python-dotenv, pytest, pytest-asyncio

---

## File Map

| File | Created/Modified | Responsibility |
|---|---|---|
| `requirements.txt` | Create | Pin all Phase 1-2 deps |
| `pytest.ini` | Create | Configure pytest (asyncio mode) |
| `.env.example` | Create | Template for API keys |
| `config.py` | Create | All constants, loads .env |
| `session.py` | Create | Session + WindowSnapshot dataclasses |
| `watchdog.py` | Create | Win32 polling, heuristic classifier, async loop |
| `tests/__init__.py` | Create | Make tests a package |
| `tests/test_session.py` | Create | Session dataclass tests |
| `tests/test_watchdog.py` | Create | Watchdog unit + integration tests |

---

## Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `.env.example`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `requirements.txt`**

```
# Core (Phase 1-2)
pywin32==306
psutil==5.9.8
python-dotenv==1.0.1
comtypes==1.4.8

# Dev
pytest==8.1.1
pytest-asyncio==0.23.6
pytest-mock==3.14.0
```

- [ ] **Step 2: Create `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 3: Create `.env.example`**

```
ANTHROPIC_API_KEY=your_key_here
FISH_AUDIO_API_KEY=your_key_here
FISH_AUDIO_VOICE_ID=your_voice_id_here
```

- [ ] **Step 4: Create `tests/__init__.py`** (empty file)

- [ ] **Step 5: Install dependencies**

Run: `pip install -r requirements.txt`
Expected: all packages install without error

- [ ] **Step 6: Verify pytest works**

Run: `pytest --collect-only`
Expected: "no tests ran" or "collected 0 items" — no errors

- [ ] **Step 7: Commit**

```bash
git add requirements.txt pytest.ini .env.example tests/__init__.py
git commit -m "chore: project scaffold — deps, pytest config, test package"
```

---

## Task 2: `config.py`

**Files:**
- Create: `config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
import config

def test_config_has_watchdog_settings():
    assert isinstance(config.WATCHDOG_INTERVAL_SECONDS, int)
    assert isinstance(config.IDLE_THRESHOLD_SECONDS, int)
    assert isinstance(config.OFF_TASK_THRESHOLD_SECONDS, int)
    assert isinstance(config.INTERVENTION_COOLDOWN_SECONDS, int)
    assert isinstance(config.FOCUS_STREAK_THRESHOLD_SECONDS, int)
    assert isinstance(config.MAX_SNAPSHOT_HISTORY, int)

def test_config_heuristic_lists_are_sets():
    assert isinstance(config.KNOWN_DISTRACTION_DOMAINS, set)
    assert isinstance(config.KNOWN_STUDY_DOMAINS, set)
    assert isinstance(config.KNOWN_DISTRACTION_PROCESSES, set)
    assert isinstance(config.KNOWN_STUDY_PROCESSES, set)

def test_known_distractions_includes_youtube():
    assert "youtube.com" in config.KNOWN_DISTRACTION_DOMAINS

def test_known_study_includes_khanacademy():
    assert "khanacademy.org" in config.KNOWN_STUDY_DOMAINS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Create `config.py`**

```python
import os
from dotenv import load_dotenv

load_dotenv()

# API keys (unused in Phase 1-2, loaded for later phases)
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
FISH_AUDIO_API_KEY: str = os.getenv("FISH_AUDIO_API_KEY", "")
FISH_AUDIO_VOICE_ID: str = os.getenv("FISH_AUDIO_VOICE_ID", "")

# Watchdog polling
WATCHDOG_INTERVAL_SECONDS: int = 30
IDLE_THRESHOLD_SECONDS: int = 180       # 3 min idle = stepped away, pause off-task timer

# Coaching thresholds
OFF_TASK_THRESHOLD_SECONDS: int = 120       # 2 min off-task before intervention
INTERVENTION_COOLDOWN_SECONDS: int = 300    # 5 min minimum between interventions
FOCUS_STREAK_THRESHOLD_SECONDS: int = 1500  # 25 min focus for positive reinforcement
MAX_DISTRACTION_ESCALATIONS: int = 5        # after this many, coach shifts to reflective mode

# Session history
MAX_SNAPSHOT_HISTORY: int = 20

# Whisper (used in Phase 5)
WHISPER_MODEL_SIZE: str = "base"

# Heuristic classifier — domains classified without calling Claude
KNOWN_DISTRACTION_DOMAINS: set[str] = {
    "youtube.com",
    "netflix.com",
    "instagram.com",
    "reddit.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "facebook.com",
    "twitch.tv",
    "9gag.com",
}

KNOWN_STUDY_DOMAINS: set[str] = {
    "khanacademy.org",
    "notion.so",
    "coursera.org",
    "edx.org",
    "brilliant.org",
    "wolframalpha.com",
    "desmos.com",
    "scholar.google.com",
    "wikipedia.org",
}

# Heuristic classifier — process names (lowercased .exe) classified without Claude
KNOWN_DISTRACTION_PROCESSES: set[str] = {
    "steam.exe",
    "epicgameslauncher.exe",
    "spotify.exe",
}

KNOWN_STUDY_PROCESSES: set[str] = {
    "code.exe",        # VS Code
    "pycharm64.exe",
    "idea64.exe",
    "acrobat.exe",
    "sumatrapdf.exe",
    "obsidian.exe",
    "anki.exe",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: config.py — all constants and heuristic classifier lists"
```

---

## Task 3: `session.py` — Session State

**Files:**
- Create: `session.py`
- Create: `tests/test_session.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_session.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_session.py -v`
Expected: `ModuleNotFoundError: No module named 'session'`

- [ ] **Step 3: Create `session.py`**

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_session.py -v`
Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add session.py tests/test_session.py
git commit -m "feat: session.py — Session and WindowSnapshot dataclasses"
```

---

## Task 4: `watchdog.py` — Active Window + Idle Detection

**Files:**
- Create: `watchdog.py` (initial — just `get_active_window_info` and `get_idle_seconds`)
- Create: `tests/test_watchdog.py` (initial)

- [ ] **Step 1: Write failing tests**

Create `tests/test_watchdog.py`:

```python
from unittest.mock import patch, MagicMock
from watchdog import get_active_window_info, get_idle_seconds

def test_get_active_window_info_returns_process_and_title(mocker):
    mocker.patch("watchdog.win32gui.GetForegroundWindow", return_value=12345)
    mocker.patch("watchdog.win32process.GetWindowThreadProcessId", return_value=(0, 999))
    mocker.patch("watchdog.win32gui.GetWindowText", return_value="YouTube - lofi hip hop")

    mock_proc = MagicMock()
    mock_proc.name.return_value = "Chrome.exe"
    mocker.patch("watchdog.psutil.Process", return_value=mock_proc)

    process, title = get_active_window_info()

    assert process == "chrome.exe"  # lowercased
    assert title == "YouTube - lofi hip hop"

def test_get_active_window_info_handles_process_access_denied(mocker):
    import psutil
    mocker.patch("watchdog.win32gui.GetForegroundWindow", return_value=12345)
    mocker.patch("watchdog.win32process.GetWindowThreadProcessId", return_value=(0, 999))
    mocker.patch("watchdog.win32gui.GetWindowText", return_value="Some Window")
    mocker.patch("watchdog.psutil.Process", side_effect=psutil.AccessDenied(999))

    process, title = get_active_window_info()
    assert process == "unknown"

def test_get_idle_seconds_returns_integer(mocker):
    mocker.patch("watchdog.ctypes.windll.user32.GetLastInputInfo", return_value=True)
    mocker.patch("watchdog.ctypes.windll.kernel32.GetTickCount", return_value=5000)

    # Patch LASTINPUTINFO so dwTime reads as 2000
    mock_lii = MagicMock()
    mock_lii.dwTime = 2000
    mocker.patch("watchdog._LASTINPUTINFO", return_value=mock_lii)

    result = get_idle_seconds()
    assert isinstance(result, int)
    assert result >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_watchdog.py -v`
Expected: `ModuleNotFoundError: No module named 'watchdog'`

- [ ] **Step 3: Create `watchdog.py` with the two functions**

```python
import ctypes
import logging
from typing import Optional

import psutil
import win32gui
import win32process

logger = logging.getLogger(__name__)


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def get_active_window_info() -> tuple[str, str]:
    """Return (process_name_lowercased, window_title) for the foreground window."""
    hwnd = win32gui.GetForegroundWindow()
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        proc = psutil.Process(pid)
        process_name = proc.name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        process_name = "unknown"
    window_title = win32gui.GetWindowText(hwnd)
    return process_name, window_title


def get_idle_seconds() -> int:
    """Return seconds since the last keyboard or mouse input."""
    lii = _LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
    elapsed_ms = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
    return elapsed_ms // 1000
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_watchdog.py -v`
Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add watchdog.py tests/test_watchdog.py
git commit -m "feat: watchdog — get_active_window_info and get_idle_seconds"
```

---

## Task 5: `watchdog.py` — Browser URL Extraction

**Files:**
- Modify: `watchdog.py` (add `get_browser_url` and `CHROMIUM_PROCESSES`)
- Modify: `tests/test_watchdog.py` (add URL extraction tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_watchdog.py`:

```python
from watchdog import get_browser_url, CHROMIUM_PROCESSES

def test_get_browser_url_returns_none_for_non_browser():
    result = get_browser_url("notepad.exe")
    assert result is None

def test_get_browser_url_returns_none_for_non_browser_edge_case():
    result = get_browser_url("chrome_helper.exe")
    # not in CHROMIUM_PROCESSES, so should return None
    assert result is None

def test_chromium_processes_contains_chrome_and_edge():
    assert "chrome.exe" in CHROMIUM_PROCESSES
    assert "msedge.exe" in CHROMIUM_PROCESSES

def test_get_browser_url_returns_none_on_automation_failure(mocker):
    # Simulate comtypes raising on import — should return None gracefully
    mocker.patch.dict("sys.modules", {"comtypes": None})
    result = get_browser_url("chrome.exe")
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_watchdog.py::test_get_browser_url_returns_none_for_non_browser -v`
Expected: `ImportError` or `AttributeError` — `get_browser_url` does not exist yet

- [ ] **Step 3: Add `get_browser_url` to `watchdog.py`**

Add these lines after the imports and before `get_active_window_info`:

```python
CHROMIUM_PROCESSES: set[str] = {"chrome.exe", "msedge.exe", "brave.exe", "opera.exe"}
```

Add this function after `get_idle_seconds`:

```python
def get_browser_url(process_name: str) -> Optional[str]:
    """
    Try to read the active tab URL from a Chromium browser via UI Automation.
    Returns None on any failure — callers always have window_title as fallback.
    """
    if process_name not in CHROMIUM_PROCESSES:
        return None
    try:
        import comtypes
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation

        automation = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
        hwnd = win32gui.GetForegroundWindow()
        element = automation.ElementFromHandle(hwnd)

        # Find address bar: ControlType=Edit (50004), scoped to descendants
        condition = automation.CreatePropertyCondition(30003, 50004)
        address_bar = element.FindFirst(2, condition)
        if address_bar is None:
            return None
        url: str = address_bar.CurrentValue
        if url and (url.startswith("http://") or url.startswith("https://")):
            return url
        return None
    except Exception:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_watchdog.py -v`
Expected: all tests PASS (including the 3 from Task 4)

- [ ] **Step 5: Commit**

```bash
git add watchdog.py tests/test_watchdog.py
git commit -m "feat: watchdog — get_browser_url via UI Automation (graceful fallback)"
```

---

## Task 6: `watchdog.py` — Heuristic Classifier

**Files:**
- Modify: `watchdog.py` (add `classify_snapshot`)
- Modify: `tests/test_watchdog.py` (add classifier tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_watchdog.py`:

```python
from datetime import datetime
from session import WindowSnapshot
from watchdog import classify_snapshot

def _snap(process="notepad.exe", title="Untitled", url=None, idle=0):
    return WindowSnapshot(
        timestamp=datetime.now(),
        process=process,
        window_title=title,
        url=url,
        idle_seconds=idle,
        is_on_task=None,
    )

def test_classify_known_distraction_url_returns_false():
    snap = _snap(url="https://www.youtube.com/watch?v=abc")
    assert classify_snapshot(snap) is False

def test_classify_known_study_url_returns_true():
    snap = _snap(url="https://khanacademy.org/math/calculus")
    assert classify_snapshot(snap) is True

def test_classify_subdomain_of_distraction_returns_false():
    snap = _snap(url="https://old.reddit.com/r/learnpython")
    assert classify_snapshot(snap) is False

def test_classify_ambiguous_url_returns_none():
    snap = _snap(url="https://discord.com/channels/123/456")
    assert classify_snapshot(snap) is None

def test_classify_known_distraction_process_no_url_returns_false():
    snap = _snap(process="steam.exe")
    assert classify_snapshot(snap) is False

def test_classify_known_study_process_no_url_returns_true():
    snap = _snap(process="code.exe")
    assert classify_snapshot(snap) is True

def test_classify_unknown_process_no_url_returns_none():
    snap = _snap(process="unknownapp.exe")
    assert classify_snapshot(snap) is None

def test_classify_url_takes_precedence_over_process():
    # Process is a known study tool, but URL is a distraction — URL wins
    snap = _snap(process="code.exe", url="https://youtube.com/watch?v=xyz")
    assert classify_snapshot(snap) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_watchdog.py -k "classify" -v`
Expected: `ImportError` — `classify_snapshot` does not exist yet

- [ ] **Step 3: Add `classify_snapshot` to `watchdog.py`**

Add this import at the top of `watchdog.py`:

```python
from urllib.parse import urlparse
```

Add this import alongside the existing config imports (add after the existing imports block):

```python
from config import (
    KNOWN_DISTRACTION_DOMAINS,
    KNOWN_STUDY_DOMAINS,
    KNOWN_DISTRACTION_PROCESSES,
    KNOWN_STUDY_PROCESSES,
)
from session import WindowSnapshot
```

Add this function after `get_browser_url`:

```python
def classify_snapshot(snapshot: WindowSnapshot) -> Optional[bool]:
    """
    Classify a window snapshot using local heuristics.
    Returns True (on-task), False (off-task), or None (ambiguous — caller sends to Claude).
    URL is checked first — more precise than process name.
    """
    if snapshot.url:
        domain = urlparse(snapshot.url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        if any(domain == d or domain.endswith("." + d) for d in KNOWN_DISTRACTION_DOMAINS):
            return False
        if any(domain == d or domain.endswith("." + d) for d in KNOWN_STUDY_DOMAINS):
            return True
        return None  # URL present but domain unknown — ambiguous

    if snapshot.process in KNOWN_DISTRACTION_PROCESSES:
        return False
    if snapshot.process in KNOWN_STUDY_PROCESSES:
        return True

    return None  # no URL, process unknown — ambiguous
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `pytest tests/ -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add watchdog.py tests/test_watchdog.py
git commit -m "feat: watchdog — classify_snapshot heuristic classifier"
```

---

## Task 7: `watchdog.py` — Async Poll Loop

**Files:**
- Modify: `watchdog.py` (add `watchdog_loop`)
- Modify: `tests/test_watchdog.py` (add loop integration test)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_watchdog.py`:

```python
import asyncio
from unittest.mock import AsyncMock, call
from watchdog import watchdog_loop
from session import Session

async def test_watchdog_loop_calls_on_off_task_when_off_task(mocker):
    """When snapshot is off-task and user is not idle, on_off_task must be called."""
    session = Session(plan="calculus revision")
    on_off_task = AsyncMock()

    # Simulate: chrome on YouTube, not idle
    mocker.patch("watchdog.get_active_window_info", return_value=("chrome.exe", "YouTube"))
    mocker.patch("watchdog.get_idle_seconds", return_value=0)
    mocker.patch("watchdog.get_browser_url", return_value="https://youtube.com/watch?v=abc")

    # Run one iteration then cancel
    async def run_one_tick():
        task = asyncio.create_task(watchdog_loop(session, on_off_task))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    mocker.patch("watchdog.asyncio.sleep", new=AsyncMock())
    await run_one_tick()

    assert on_off_task.called
    snapshot_arg = on_off_task.call_args[0][0]
    assert snapshot_arg.is_on_task is False

async def test_watchdog_loop_does_not_call_on_off_task_when_on_task(mocker):
    """When snapshot is on-task, on_off_task must NOT be called."""
    session = Session(plan="calculus revision")
    on_off_task = AsyncMock()

    mocker.patch("watchdog.get_active_window_info", return_value=("code.exe", "main.py - VS Code"))
    mocker.patch("watchdog.get_idle_seconds", return_value=0)
    mocker.patch("watchdog.get_browser_url", return_value=None)

    async def run_one_tick():
        task = asyncio.create_task(watchdog_loop(session, on_off_task))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    mocker.patch("watchdog.asyncio.sleep", new=AsyncMock())
    await run_one_tick()

    on_off_task.assert_not_called()
    assert session.off_task_start is None

async def test_watchdog_loop_skips_callback_when_idle(mocker):
    """Idle user (stepped away) should not trigger the off-task callback."""
    session = Session(plan="calculus revision")
    on_off_task = AsyncMock()

    # YouTube open but user is idle — stepped away, not distracted
    mocker.patch("watchdog.get_active_window_info", return_value=("chrome.exe", "YouTube"))
    mocker.patch("watchdog.get_idle_seconds", return_value=999)  # well over threshold
    mocker.patch("watchdog.get_browser_url", return_value="https://youtube.com/watch?v=abc")

    async def run_one_tick():
        task = asyncio.create_task(watchdog_loop(session, on_off_task))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    mocker.patch("watchdog.asyncio.sleep", new=AsyncMock())
    await run_one_tick()

    on_off_task.assert_not_called()

async def test_watchdog_loop_appends_snapshot_to_history(mocker):
    """Each poll should append one WindowSnapshot to session.snapshot_history."""
    session = Session(plan="calculus revision")
    on_off_task = AsyncMock()

    mocker.patch("watchdog.get_active_window_info", return_value=("code.exe", "notes.py"))
    mocker.patch("watchdog.get_idle_seconds", return_value=0)
    mocker.patch("watchdog.get_browser_url", return_value=None)

    async def run_one_tick():
        task = asyncio.create_task(watchdog_loop(session, on_off_task))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    mocker.patch("watchdog.asyncio.sleep", new=AsyncMock())
    await run_one_tick()

    assert len(session.snapshot_history) == 1
    assert session.snapshot_history[0].process == "code.exe"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_watchdog.py -k "loop" -v`
Expected: `ImportError` — `watchdog_loop` does not exist yet

- [ ] **Step 3: Add `watchdog_loop` to `watchdog.py`**

Add this import at the top of `watchdog.py`:

```python
import asyncio
from typing import Callable, Awaitable
from datetime import datetime
```

Add this import to the config imports block (already partially there from Task 6):

```python
from config import (
    KNOWN_DISTRACTION_DOMAINS,
    KNOWN_STUDY_DOMAINS,
    KNOWN_DISTRACTION_PROCESSES,
    KNOWN_STUDY_PROCESSES,
    WATCHDOG_INTERVAL_SECONDS,
    IDLE_THRESHOLD_SECONDS,
    MAX_SNAPSHOT_HISTORY,
)
```

Add this function at the bottom of `watchdog.py`:

```python
async def watchdog_loop(
    session: "Session",
    on_off_task: Callable[["WindowSnapshot", "Session"], Awaitable[None]],
) -> None:
    """
    Poll active window every WATCHDOG_INTERVAL_SECONDS.
    - Appends WindowSnapshot to session.snapshot_history (capped at MAX_SNAPSHOT_HISTORY).
    - Calls on_off_task(snapshot, session) when snapshot is off-task and user is not idle.
    - Resets session.off_task_start to None when user returns to an on-task window.
    - Skips the callback entirely when idle >= IDLE_THRESHOLD_SECONDS (user stepped away).
    Runs until cancelled.
    """
    while True:
        process, title = get_active_window_info()
        idle = get_idle_seconds()
        url = get_browser_url(process)

        snapshot = WindowSnapshot(
            timestamp=datetime.now(),
            process=process,
            window_title=title,
            url=url,
            idle_seconds=idle,
            is_on_task=None,
        )
        snapshot.is_on_task = classify_snapshot(snapshot)

        session.snapshot_history.append(snapshot)
        if len(session.snapshot_history) > MAX_SNAPSHOT_HISTORY:
            session.snapshot_history.pop(0)

        logger.info(
            "watchdog: process=%s title=%r url=%s idle=%ds on_task=%s",
            process, title, url, idle, snapshot.is_on_task,
        )

        if idle < IDLE_THRESHOLD_SECONDS:
            if snapshot.is_on_task is False:
                if session.off_task_start is None:
                    session.off_task_start = datetime.now()
                await on_off_task(snapshot, session)
            elif snapshot.is_on_task is True:
                session.off_task_start = None

        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `pytest tests/ -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add watchdog.py tests/test_watchdog.py
git commit -m "feat: watchdog — async poll loop with off-task callback and history"
```

---

## Task 8: Smoke Test — End-to-End Watchdog Log

**Files:**
- Create: `smoke_watchdog.py` (temporary dev script, not committed)

- [ ] **Step 1: Create `smoke_watchdog.py`**

```python
"""
Temporary smoke test — run this manually to verify the watchdog works.
Polls for 60 seconds and prints a log of every window snapshot.
Delete this file after you're satisfied.
"""
import asyncio
import logging
from session import Session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


async def print_off_task(snapshot, session):
    print(f"[OFF-TASK] {snapshot.process} | {snapshot.window_title} | url={snapshot.url}")


async def main():
    from watchdog import watchdog_loop
    import config
    config.WATCHDOG_INTERVAL_SECONDS = 5  # speed up for smoke test

    session = Session(plan="calculus revision")
    print("Watching for 60 seconds. Switch windows to test.")
    try:
        await asyncio.wait_for(watchdog_loop(session, print_off_task), timeout=60)
    except asyncio.TimeoutError:
        print(f"\nDone. {len(session.snapshot_history)} snapshots captured.")
        for s in session.snapshot_history:
            print(f"  {s.timestamp:%H:%M:%S} | {s.process:20s} | on_task={s.is_on_task} | {s.window_title[:50]}")


asyncio.run(main())
```

- [ ] **Step 2: Run the smoke test**

Run: `python smoke_watchdog.py`

Expected output (example):
```
2026-04-17 12:00:00 watchdog: process=chrome.exe title='YouTube - lofi hip hop' url=https://youtube.com... idle=2s on_task=False
[OFF-TASK] chrome.exe | YouTube - lofi hip hop | url=https://youtube.com/watch?v=...
2026-04-17 12:00:05 watchdog: process=code.exe title='session.py - study buddy' url=None idle=1s on_task=True
...
Done. 12 snapshots captured.
```

- [ ] **Step 3: Run full test suite one final time**

Run: `pytest tests/ -v`
Expected: all tests PASS

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "chore: phase 1+2 complete — foundation and watchdog implemented and tested"
```

---

## Self-Review

**Spec coverage:**
- [x] `requirements.txt` — Task 1
- [x] `.env.example` — Task 1
- [x] `config.py` — Task 2
- [x] `session.py` — Task 3 (plan, persona, snapshot_history, off_task_start, last_intervention, distraction_count, focus_streak_start, conversation_history)
- [x] `watchdog.py` — active window (Task 4), browser URL (Task 5), idle detection (Task 4), two-tier classifier (Task 6), async tick loop (Task 7)
- [x] Done-when: 60-second run prints readable window log — Task 8 smoke test

**Type consistency:** `WindowSnapshot` defined in `session.py`, imported in `watchdog.py` consistently throughout. `classify_snapshot` receives `WindowSnapshot`, returns `Optional[bool]`. `watchdog_loop` callback signature `(WindowSnapshot, Session) -> Awaitable[None]` used identically in tests and implementation.

**No placeholders:** all tasks contain complete code, exact commands, and expected output.
