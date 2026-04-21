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
    mocker.patch("watchdog.ctypes.sizeof", return_value=8)
    mocker.patch("watchdog.ctypes.byref", return_value=MagicMock())

    mock_lii = MagicMock()
    mock_lii.dwTime = 2000
    mocker.patch("watchdog._LASTINPUTINFO", return_value=mock_lii)

    result = get_idle_seconds()
    assert isinstance(result, int)
    assert result >= 0
