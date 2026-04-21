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
