import asyncio
import ctypes
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, Optional
from urllib.parse import urlparse

import psutil
try:
    import win32gui
    import win32process
    HAS_WIN32 = True
except ImportError:
    win32gui = None
    win32process = None
    HAS_WIN32 = False

import config
from config import (
    IDLE_THRESHOLD_SECONDS,
    KNOWN_DISTRACTION_DOMAINS,
    KNOWN_DISTRACTION_PROCESSES,
    KNOWN_DUAL_USE_DOMAINS,
    KNOWN_DUAL_USE_PROCESSES,
    KNOWN_STUDY_DOMAINS,
    KNOWN_STUDY_PROCESSES,
    MAX_SNAPSHOT_HISTORY,
    WATCHDOG_INTERVAL_SECONDS,
)
from session import Session, WindowSnapshot

logger = logging.getLogger(__name__)

# Alias so tests can patch watchdog._sleep without affecting asyncio.sleep globally
_sleep = asyncio.sleep

CHROMIUM_PROCESSES: set[str] = {"chrome.exe", "msedge.exe", "brave.exe", "opera.exe"}
# Full browser set for general browser detection
_BROWSER_PROCESSES = config.BROWSER_PROCESSES


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def get_active_window_info() -> tuple[str, str, int]:
    """Return (process_name_lowercased, window_title, pid) for the foreground window."""
    if not HAS_WIN32:
        raise RuntimeError("Windows win32 API is not available on this platform.")
    hwnd = win32gui.GetForegroundWindow()
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    if pid < 0:
        pid = pid & 0xffffffff
    try:
        proc = psutil.Process(pid)
        process_name = proc.name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        process_name = "unknown"
    window_title = win32gui.GetWindowText(hwnd)
    return process_name, window_title, pid


def get_idle_seconds() -> int:
    """Return seconds since the last keyboard or mouse input."""
    if not HAS_WIN32 or not hasattr(ctypes, "windll"):
        return 0
    lii = _LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
    elapsed_ms = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
    return elapsed_ms // 1000



def terminate_process(pid: Optional[int], name: Optional[str]) -> bool:
    """Attempt to terminate a process by PID, with a name-based fallback."""
    if not pid and not name:
        return False
    
    # 1. Try terminating by PID
    if pid:
        try:
            proc = psutil.Process(pid)
            if not name or proc.name().lower() == name.lower():
                proc.terminate()
                logger.info("Terminated process by PID: %d (%s)", pid, proc.name())
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.warning("Failed to terminate process by PID %d: %s", pid, e)
    
    # 2. Try terminating by name as fallback
    if name:
        logger.info("Attempting fallback termination by process name: %s", name)
        name_lower = name.lower()
        terminated_any = False
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'].lower() == name_lower:
                    psutil.Process(proc.info['pid']).terminate()
                    logger.info("Terminated process by name search: PID %d (%s)", proc.info['pid'], name)
                    terminated_any = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return terminated_any

    return False


def is_likely_url(s: str) -> bool:
    """Heuristic check to determine if a string looks like a web URL/domain.

    Accepts strings starting with http/https, or string representations
    containing a dot in the domain section and minimal lengths.
    """
    s = s.strip()
    if not s or " " in s:  # Spaces generally invalidate domain URLs
        return False
    if s.startswith(("http://", "https://")):
        return True
    parts = s.split('/')
    domain_part = parts[0]
    # Check that domain has a dot (e.g. google.com) and is longer than 3 characters
    return "." in domain_part and len(domain_part) > 3


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

        # Search all Edit controls (50004) under the window
        condition = automation.CreatePropertyCondition(30003, 50004)
        edit_controls = element.FindAll(2, condition)
        if edit_controls:
            # First pass: try matching by specific automation IDs (more direct)
            for i in range(edit_controls.Length):
                ctrl = edit_controls.GetElement(i)
                try:
                    auto_id = ctrl.CurrentAutomationId
                    if auto_id in ("address-bar", "AddressAndSearchEditBox"):
                        val = ctrl.CurrentValue
                        if val and is_likely_url(val):
                            url = val.strip()
                            if not (url.startswith("http://") or url.startswith("https://")):
                                url = "https://" + url
                            return url
                except Exception:
                    pass

            # Second pass: check values of all edit controls to see if any looks like a URL/domain
            for i in range(edit_controls.Length):
                ctrl = edit_controls.GetElement(i)
                try:
                    val = ctrl.CurrentValue
                    if val and is_likely_url(val):
                        url = val.strip()
                        if not (url.startswith("http://") or url.startswith("https://")):
                            url = "https://" + url
                        return url
                except Exception:
                    pass

        return None
    except Exception:
        return None


def _match_domain(target: str, domain_set: set[str]) -> bool:
    """Check if target matches any domain in the set (exact or subdomain)."""
    if target in domain_set:
        return True
    return any(target.endswith("." + d) for d in domain_set)


def classify_snapshot(snapshot: WindowSnapshot, session: Session) -> Optional[bool]:
    """
    Classify a window snapshot using local heuristics.
    Returns True (on-task), False (off-task), or None (ambiguous — needs query).
    """
    # Resolve domain or process target name
    if snapshot.url:
        target = config.strip_www(urlparse(snapshot.url).netloc.lower())
        is_domain = True
    else:
        target = snapshot.process
        is_domain = False

    if not target:
        return None

    # Check session overrides first
    if target in session.session_allowed_targets:
        return True
    if target in session.session_denied_targets:
        return False

    # Check permanent sets
    if is_domain:
        if _match_domain(target, KNOWN_DISTRACTION_DOMAINS):
            return False
        if _match_domain(target, KNOWN_STUDY_DOMAINS):
            return True
        if _match_domain(target, KNOWN_DUAL_USE_DOMAINS):
            return None  # Dual-use
    else:
        if target in KNOWN_DISTRACTION_PROCESSES:
            return False
        if target in KNOWN_STUDY_PROCESSES:
            return True
        if target in KNOWN_DUAL_USE_PROCESSES:
            return None  # Dual-use

    return None  # Ambiguous / Unclassified


# ---------------------------------------------------------------------------
# Shared snapshot processing — used by both watchdog_loop() and server.py
# ---------------------------------------------------------------------------

@dataclass
class WatchdogResult:
    """Describes what happened when a snapshot was processed."""
    is_on_task: Optional[bool] = None
    target_name: str = ""
    is_focus: bool = False

    # Actions the caller should execute
    should_query: bool = False
    query_target: Optional[str] = None
    should_intervene: bool = False
    should_reinforce: bool = False
    should_close_process: bool = False
    should_close_tab: bool = False


def _resolve_target(snapshot: WindowSnapshot) -> str:
    """Determine the best human-readable target name for a snapshot."""
    if snapshot.url:
        return config.strip_www(urlparse(snapshot.url).netloc.lower())
    if snapshot.process.lower() in _BROWSER_PROCESSES and snapshot.window_title:
        domain_match = re.search(r'([a-zA-Z0-9-]+\.[a-zA-Z]{2,})', snapshot.window_title)
        if domain_match:
            return domain_match.group(1).lower()
    return snapshot.process


def process_snapshot(snapshot: WindowSnapshot, session: Session) -> WatchdogResult:
    """Shared state machine: classify, update session state, determine actions.

    Call this from *both* the local watchdog_loop and the server /activity
    endpoint so the logic stays in one place.
    """
    # 1. Classify
    snapshot.is_on_task = classify_snapshot(snapshot, session)

    # 2. Append to history (deque auto-evicts)
    session.snapshot_history.append(snapshot)

    # 3. Resolve target name
    target = _resolve_target(snapshot)

    result = WatchdogResult(
        is_on_task=snapshot.is_on_task,
        target_name=target,
        is_focus=(snapshot.is_on_task is True),
    )

    # 4. Skip state transitions when user is idle (stepped away)
    if snapshot.idle_seconds >= IDLE_THRESHOLD_SECONDS:
        return result

    # 5. State machine
    if snapshot.is_on_task is None:
        # Unclassified / dual-use — may need to ask the user
        query_target = config.strip_www(
            urlparse(snapshot.url).netloc.lower() if snapshot.url else snapshot.process
        )
        is_browser_target = query_target.lower() in _BROWSER_PROCESSES
        if query_target and not is_browser_target and query_target not in session.queried_targets:
            session.queried_targets.add(query_target)
            result.should_query = True
            result.query_target = query_target

    elif snapshot.is_on_task is False:
        # Off-task — track state and flag for intervention
        session.focus_streak_start = None
        if session.off_task_start is None:
            session.off_task_start = datetime.now()

        is_browser = snapshot.process.lower() in _BROWSER_PROCESSES
        if session.control_laptop and not is_browser:
            result.should_close_process = True
        elif session.control_laptop and is_browser:
            result.should_close_tab = True

        result.should_intervene = True

    elif snapshot.is_on_task is True:
        # On-task — track streak and flag for reinforcement
        session.off_task_start = None
        if session.focus_streak_start is None:
            session.focus_streak_start = datetime.now()
        result.should_reinforce = True

    return result


async def watchdog_loop(
    session: Session,
    on_off_task: Callable[..., Awaitable[None]],
    on_on_task: Optional[Callable[[WindowSnapshot, Session], Awaitable[None]]] = None,
) -> None:
    """
    Poll active window every WATCHDOG_INTERVAL_SECONDS.
    Delegates classification and state tracking to process_snapshot().
    Runs until cancelled.
    """
    while True:
        process, title, pid = get_active_window_info()
        idle = get_idle_seconds()
        url = get_browser_url(process)

        # Fallback to parsing window title if URL was not retrieved via UI Automation
        if not url and process in CHROMIUM_PROCESSES and title:
            title_lower = title.lower()
            all_domains = KNOWN_DISTRACTION_DOMAINS | KNOWN_STUDY_DOMAINS | KNOWN_DUAL_USE_DOMAINS
            for domain in all_domains:
                keyword = domain.split('.')[0]
                # Match keyword as a whole word to prevent false positives (e.g. 'x' matching any title for x.com)
                if re.search(r'\b' + re.escape(keyword) + r'\b', title_lower):
                    url = f"https://{domain}"
                    logger.info("watchdog fallback: extracted URL from browser title: %r -> %s", title, url)
                    break

        snapshot = WindowSnapshot(
            timestamp=datetime.now(),
            process=process,
            window_title=title,
            url=url,
            idle_seconds=idle,
            is_on_task=None,
            pid=pid,
        )

        result = process_snapshot(snapshot, session)

        logger.info(
            "watchdog: process=%s title=%r url=%s idle=%ds on_task=%s",
            process, title, url, idle, snapshot.is_on_task,
        )

        # --- Execute actions ---
        if result.should_query:
            logger.info("watchdog: target '%s' requires classification. Triggering query.", result.query_target)
            try:
                await on_off_task(snapshot, session, force=True, query_target=result.query_target)
            except TypeError:
                await on_off_task(snapshot, session)

        elif result.should_intervene:
            if result.should_close_process:
                logger.warning("watchdog: distracting process detected! Closing: %s", process)
                terminate_process(snapshot.pid, snapshot.process)
            elif result.should_close_tab:
                logger.warning("watchdog: distracting website on browser '%s'. Simulating Ctrl+W.", process)
                try:
                    hwnd = win32gui.GetForegroundWindow()
                    _, cur_pid = win32process.GetWindowThreadProcessId(hwnd)
                    if cur_pid == snapshot.pid:
                        ctypes.windll.user32.keybd_event(0x11, 0, 0, 0)   # Ctrl down
                        await asyncio.sleep(0.05)
                        ctypes.windll.user32.keybd_event(0x57, 0, 0, 0)   # W down
                        await asyncio.sleep(0.05)
                        ctypes.windll.user32.keybd_event(0x57, 0, 2, 0)   # W up
                        await asyncio.sleep(0.05)
                        ctypes.windll.user32.keybd_event(0x11, 0, 2, 0)   # Ctrl up
                except Exception as e:
                    logger.error("Failed to simulate Ctrl+W: %s", e)

            force = result.should_close_process or result.should_close_tab
            try:
                await on_off_task(snapshot, session, force=force)
            except TypeError:
                await on_off_task(snapshot, session)

        elif result.should_reinforce and on_on_task:
            await on_on_task(snapshot, session)

        await _sleep(WATCHDOG_INTERVAL_SECONDS)
