"""Phase 5 tests — VoicePipeline.listen_and_chat() and start_listening()."""
import time
from unittest.mock import MagicMock, patch

import numpy as np

from pipeline import CoachingPipeline
from session import Session
from voice_pipeline import VoicePipeline


def _make_pipeline(speak_fn=None):
    session = Session(plan="Study calculus", persona="strict coach")
    client = MagicMock()
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(
            finish_reason="stop",
            message=MagicMock(content="Focus!", tool_calls=None),
        )]
    )
    cp = CoachingPipeline(session=session, client=client)
    return VoicePipeline(coaching_pipeline=cp, speak_fn=speak_fn or MagicMock())


def test_listen_and_chat_calls_speak_with_response():
    vp = _make_pipeline()
    fake_audio = np.zeros(16000, dtype=np.float32)
    with patch("voice_pipeline.transcribe_audio", return_value="I need help"):
        result = vp.listen_and_chat(fake_audio)
    vp._speak.assert_called_once()
    assert result == "Focus!"


def test_listen_and_chat_returns_empty_on_empty_transcription():
    vp = _make_pipeline()
    fake_audio = np.zeros(16000, dtype=np.float32)
    with patch("voice_pipeline.transcribe_audio", return_value=""):
        result = vp.listen_and_chat(fake_audio)
    vp._speak.assert_not_called()
    assert result == ""


def test_start_listening_spawns_daemon_thread():
    vp = _make_pipeline()
    with patch("voice_pipeline.listen_loop"):
        vp.start_listening()
        time.sleep(0.05)
    assert vp._listen_thread is not None
    assert vp._listen_thread.daemon is True
