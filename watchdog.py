import asyncio
import ctypes
import logging
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

from config import (
    IDLE_THRESHOLD_SECONDS,
    KNOWN_DISTRACTION_DOMAINS,
    KNOWN_DISTRACTION_PROCESSES,
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


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def get_active_window_info() -> tuple[str, str, int]:
    """Return (process_name_lowercased, window_title, pid) for the foreground window."""
    if not HAS_WIN32:
        raise RuntimeError("Windows win32 API is not available on this platform.")
    hwnd = win32gui.GetForegroundWindow()
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
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


def classify_snapshot(snapshot: WindowSnapshot, session: Session) -> Optional[bool]:
    """
    Classify a window snapshot using local heuristics.
    Returns True (on-task), False (off-task), or None (ambiguous — needs query).
    """
    import config
    
    # Resolve domain or process target name
    target = None
    is_domain = False
    if snapshot.url:
        domain = urlparse(snapshot.url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        target = domain
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
        if any(target == d or target.endswith("." + d) for d in KNOWN_DISTRACTION_DOMAINS):
            return False
        if any(target == d or target.endswith("." + d) for d in KNOWN_STUDY_DOMAINS):
            return True
        if any(target == d or target.endswith("." + d) for d in config.KNOWN_DUAL_USE_DOMAINS):
            return None  # Dual-use
    else:
        if target in KNOWN_DISTRACTION_PROCESSES:
            return False
        if target in KNOWN_STUDY_PROCESSES:
            return True
        if target in config.KNOWN_DUAL_USE_PROCESSES:
            return None  # Dual-use

    return None  # Ambiguous / Unclassified


async def watchdog_loop(
    session: Session,
    on_off_task: Callable[..., Awaitable[None]],
    on_on_task: Optional[Callable[[WindowSnapshot, Session], Awaitable[None]]] = None,
) -> None:
    """
    Poll active window every WATCHDOG_INTERVAL_SECONDS.
    - Appends WindowSnapshot to session.snapshot_history (capped at MAX_SNAPSHOT_HISTORY).
    - Calls on_off_task(snapshot, session) when snapshot is off-task and user is not idle.
    - Resets session.off_task_start to None when user returns to an on-task window.
    - Skips the callback when idle >= IDLE_THRESHOLD_SECONDS (user stepped away).
    Runs until cancelled.
    """
    while True:
        process, title, pid = get_active_window_info()
        idle = get_idle_seconds()
        url = get_browser_url(process)

        snapshot = WindowSnapshot(
            timestamp=datetime.now(),
            process=process,
            window_title=title,
            url=url,
            idle_seconds=idle,
            is_on_task=None,
            pid=pid,
        )
        snapshot.is_on_task = classify_snapshot(snapshot, session)

        session.snapshot_history.append(snapshot)
        if len(session.snapshot_history) > MAX_SNAPSHOT_HISTORY:
            session.snapshot_history.pop(0)

        logger.info(
            "watchdog: process=%s title=%r url=%s idle=%ds on_task=%s",
            process, title, url, idle, snapshot.is_on_task,
        )

        if idle < IDLE_THRESHOLD_SECONDS:
            if snapshot.is_on_task is None:
                # Trigger verbal query intervention for unclassified or dual-use target
                target = urlparse(snapshot.url).netloc.lower() if snapshot.url else snapshot.process
                if target.startswith("www."):
                    target = target[4:]
                
                if target and target not in session.queried_targets:
                    session.queried_targets.add(target)
                    logger.info("watchdog: target '%s' requires classification. Triggering query.", target)
                    try:
                        await on_off_task(snapshot, session, force=True, query_target=target)
                    except TypeError:
                        await on_off_task(snapshot, session)
            
            elif snapshot.is_on_task is False:
                if session.off_task_start is None:
                    session.off_task_start = datetime.now()
                
                if session.control_laptop:
                    logger.warning("watchdog: distracting process detected! Closing: %s", process)
                    terminate_process(snapshot.pid, snapshot.process)
                    try:
                        await on_off_task(snapshot, session, force=True)
                    except TypeError:
                        await on_off_task(snapshot, session)
                else:
                    try:
                        await on_off_task(snapshot, session, force=False)
                    except TypeError:
                        await on_off_task(snapshot, session)
                        
            elif snapshot.is_on_task is True:
                session.off_task_start = None
                if session.focus_streak_start is None:
                    session.focus_streak_start = datetime.now()
                if on_on_task:
                    await on_on_task(snapshot, session)

        await _sleep(WATCHDOG_INTERVAL_SECONDS)
