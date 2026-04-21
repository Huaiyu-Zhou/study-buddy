import ctypes
import logging
from typing import Optional

import psutil
import win32gui
import win32process

logger = logging.getLogger(__name__)

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
