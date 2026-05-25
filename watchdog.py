import asyncio
import ctypes
import logging
from datetime import datetime
from typing import Awaitable, Callable, Optional
from urllib.parse import urlparse

import psutil
import win32gui
import win32process

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


async def watchdog_loop(
    session: Session,
    on_off_task: Callable[[WindowSnapshot, Session], Awaitable[None]],
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
                if session.focus_streak_start is None:
                    session.focus_streak_start = datetime.now()
                if on_on_task:
                    await on_on_task(snapshot, session)

        await _sleep(WATCHDOG_INTERVAL_SECONDS)
