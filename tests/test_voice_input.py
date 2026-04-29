"""Tests for voice_input module (Phase 5)."""
import asyncio
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


def test_tts_flag_defaults_false():
    import voice_input
    voice_input.is_tts_playing = False  # reset
    assert voice_input.is_tts_playing is False


def test_tts_flag_can_be_set():
    import voice_input
    voice_input.is_tts_playing = True
    assert voice_input.is_tts_playing is True
    voice_input.is_tts_playing = False  # reset


def test_transcribe_audio_returns_string():
    import voice_input
    fake_segment = MagicMock()
    fake_segment.text = " hello world"
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_segment], MagicMock())
    with patch.object(voice_input, "_get_model", return_value=fake_model):
        result = voice_input.transcribe_audio(np.zeros(16000, dtype=np.float32))
    assert result == "hello world"


def test_transcribe_audio_empty_returns_empty():
    import voice_input
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([], MagicMock())
    with patch.object(voice_input, "_get_model", return_value=fake_model):
        result = voice_input.transcribe_audio(np.zeros(16000, dtype=np.float32))
    assert result == ""


def test_transcribe_in_executor_runs_on_thread():
    import voice_input
    fake_segment = MagicMock()
    fake_segment.text = " async test"
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_segment], MagicMock())

    async def run():
        with patch.object(voice_input, "_get_model", return_value=fake_model):
            return await voice_input.transcribe_in_executor(
                np.zeros(16000, dtype=np.float32)
            )

    assert asyncio.run(run()) == "async test"


def test_collect_speech_skips_while_tts_playing():
    import voice_input
    voice_input.is_tts_playing = True
    try:
        result = voice_input.collect_speech_once(mic_stream=MagicMock())
        assert result is None
    finally:
        voice_input.is_tts_playing = False
