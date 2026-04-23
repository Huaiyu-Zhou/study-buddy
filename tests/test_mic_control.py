from unittest.mock import MagicMock, patch


def test_mute_mic_calls_set_mute_true(mocker):
    mock_volume = MagicMock()
    mocker.patch("mic_control._get_mic_volume", return_value=mock_volume)
    from mic_control import mute_mic
    mute_mic()
    mock_volume.SetMute.assert_called_once_with(True, None)


def test_unmute_mic_calls_set_mute_false(mocker):
    mock_volume = MagicMock()
    mocker.patch("mic_control._get_mic_volume", return_value=mock_volume)
    from mic_control import unmute_mic
    unmute_mic()
    mock_volume.SetMute.assert_called_once_with(False, None)


def test_mute_mic_handles_no_microphone(mocker):
    mocker.patch("mic_control._get_mic_volume", return_value=None)
    from mic_control import mute_mic
    # Should not raise — just log a warning
    mute_mic()


def test_unmute_mic_handles_no_microphone(mocker):
    mocker.patch("mic_control._get_mic_volume", return_value=None)
    from mic_control import unmute_mic
    # Should not raise — just log a warning
    unmute_mic()
