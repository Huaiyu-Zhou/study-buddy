from unittest.mock import patch, MagicMock
from watchdog import get_active_window_info, get_idle_seconds, get_browser_url, CHROMIUM_PROCESSES

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
    mocker.patch("watchdog.ctypes.sizeof", return_value=8)
    mocker.patch("watchdog.ctypes.byref", return_value=MagicMock())

    mock_lii = MagicMock()
    mock_lii.dwTime = 2000
    mocker.patch("watchdog._LASTINPUTINFO", return_value=mock_lii)

    result = get_idle_seconds()
    assert isinstance(result, int)
    assert result >= 0

def test_get_browser_url_returns_none_for_non_browser():
    result = get_browser_url("notepad.exe")
    assert result is None

def test_get_browser_url_returns_none_for_non_browser_edge_case():
    result = get_browser_url("chrome_helper.exe")
    assert result is None

def test_chromium_processes_contains_chrome_and_edge():
    assert "chrome.exe" in CHROMIUM_PROCESSES
    assert "msedge.exe" in CHROMIUM_PROCESSES

def test_get_browser_url_returns_none_on_automation_failure(mocker):
    mocker.patch.dict("sys.modules", {"comtypes": None})
    result = get_browser_url("chrome.exe")
    assert result is None

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
    snap = _snap(process="code.exe", url="https://youtube.com/watch?v=xyz")
    assert classify_snapshot(snap) is False
