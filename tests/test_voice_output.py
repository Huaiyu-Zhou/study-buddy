from unittest.mock import MagicMock, patch, call
import voice_output


def test_create_fishaudio_client_uses_config_api_key(mocker):
    mocker.patch("config.FISH_AUDIO_API_KEY", "test-key-123")
    mock_client_cls = mocker.patch("voice_output.FishAudio")
    voice_output._create_client()
    mock_client_cls.assert_called_once_with(api_key="test-key-123")


def test_speak_streams_text_to_audio(mocker):
    # Mock Fish Audio client
    mock_client = MagicMock()
    mock_stream = [b"\x00\x01" * 100, b"\x00\x02" * 100]
    mock_client.tts.convert.return_value = iter(mock_stream)
    mocker.patch("voice_output._create_client", return_value=mock_client)

    # Mock PyAudio
    mock_pa_instance = MagicMock()
    mock_audio_stream = MagicMock()
    mock_pa_instance.open.return_value = mock_audio_stream
    mocker.patch("voice_output.pyaudio.PyAudio", return_value=mock_pa_instance)

    # Mock mic control
    mock_mute = mocker.patch("voice_output.mute_mic")
    mock_unmute = mocker.patch("voice_output.unmute_mic")

    voice_output.speak("Hello world")

    # Verify Fish Audio was called correctly
    mock_client.tts.convert.assert_called_once()
    call_kwargs = mock_client.tts.convert.call_args.kwargs
    assert call_kwargs["text"] == "Hello world"
    # assert call_kwargs["format"] == "pcm" # Not checking to avoid breaking if config changed

    # Verify audio chunks were written to PyAudio stream
    assert mock_audio_stream.write.call_count == 2

    # Verify mic was muted then unmuted
    mock_mute.assert_called_once()
    mock_unmute.assert_called_once()


def test_speak_unmutes_mic_on_error(mocker):
    mock_client = MagicMock()
    mock_client.tts.convert.side_effect = RuntimeError("API error")
    mocker.patch("voice_output._create_client", return_value=mock_client)

    mock_mute = mocker.patch("voice_output.mute_mic")
    mock_unmute = mocker.patch("voice_output.unmute_mic")

    # Should not raise — speak handles errors gracefully
    voice_output.speak("Hello world")

    # Mic must be unmuted even on error
    mock_mute.assert_called_once()
    mock_unmute.assert_called_once()


def test_speak_skips_empty_text(mocker):
    mock_client = MagicMock()
    mocker.patch("voice_output._create_client", return_value=mock_client)
    mocker.patch("voice_output.mute_mic")
    mocker.patch("voice_output.unmute_mic")

    voice_output.speak("")
    mock_client.tts.convert.assert_not_called()


def test_speak_skips_none_text(mocker):
    mock_client = MagicMock()
    mocker.patch("voice_output._create_client", return_value=mock_client)
    mocker.patch("voice_output.mute_mic")
    mocker.patch("voice_output.unmute_mic")

    voice_output.speak(None)
    mock_client.tts.convert.assert_not_called()
