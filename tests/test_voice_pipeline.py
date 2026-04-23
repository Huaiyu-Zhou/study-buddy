from unittest.mock import MagicMock
from session import Session


def _voice_pipeline(session=None):
    from voice_pipeline import VoicePipeline
    if session is None:
        session = Session(plan="calculus revision")
    mock_coaching = MagicMock()
    mock_speak = MagicMock()
    vp = VoicePipeline(mock_coaching, speak_fn=mock_speak)
    return vp, mock_coaching, mock_speak


def test_chat_calls_pipeline_chat_and_speaks(mocker):
    vp, mock_coaching, mock_speak = _voice_pipeline()
    mock_coaching.chat.return_value = "Let's get started!"
    result = vp.chat("Hi")
    mock_coaching.chat.assert_called_once_with("Hi")
    mock_speak.assert_called_once_with("Let's get started!")
    assert result == "Let's get started!"


def test_maybe_intervene_speaks_when_text_returned(mocker):
    vp, mock_coaching, mock_speak = _voice_pipeline()
    mock_coaching.maybe_intervene.return_value = "Stop scrolling!"
    result = vp.maybe_intervene()
    mock_coaching.maybe_intervene.assert_called_once()
    mock_speak.assert_called_once_with("Stop scrolling!")
    assert result == "Stop scrolling!"


def test_maybe_intervene_does_not_speak_when_none(mocker):
    vp, mock_coaching, mock_speak = _voice_pipeline()
    mock_coaching.maybe_intervene.return_value = None
    result = vp.maybe_intervene()
    mock_speak.assert_not_called()
    assert result is None


def test_maybe_reinforce_speaks_when_text_returned(mocker):
    vp, mock_coaching, mock_speak = _voice_pipeline()
    mock_coaching.maybe_reinforce.return_value = "Great focus!"
    result = vp.maybe_reinforce()
    mock_coaching.maybe_reinforce.assert_called_once()
    mock_speak.assert_called_once_with("Great focus!")
    assert result == "Great focus!"


def test_maybe_reinforce_does_not_speak_when_none(mocker):
    vp, mock_coaching, mock_speak = _voice_pipeline()
    mock_coaching.maybe_reinforce.return_value = None
    result = vp.maybe_reinforce()
    mock_speak.assert_not_called()
    assert result is None


def test_session_property_delegates_to_coaching_pipeline():
    vp, mock_coaching, _ = _voice_pipeline()
    mock_coaching.session = Session(plan="biology")
    assert vp.session.plan == "biology"
