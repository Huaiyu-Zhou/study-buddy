from typing import Callable, Optional

from pipeline import CoachingPipeline
from session import Session
from voice_output import speak as default_speak


class VoicePipeline:
    """Wraps CoachingPipeline to speak every response through TTS.

    Accepts an optional speak_fn for dependency injection (testing).
    """

    def __init__(
        self,
        coaching_pipeline: CoachingPipeline,
        speak_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._pipeline = coaching_pipeline
        self._speak = speak_fn or default_speak

    @property
    def session(self) -> Session:
        return self._pipeline.session

    def chat(self, user_message: str) -> str:
        """Send a message through the pipeline, speak the response, return text."""
        text = self._pipeline.chat(user_message)
        self._speak(text)
        return text

    def maybe_intervene(self) -> Optional[str]:
        """Trigger intervention if conditions met. Speaks response if fired."""
        text = self._pipeline.maybe_intervene()
        if text is not None:
            self._speak(text)
        return text

    def maybe_reinforce(self) -> Optional[str]:
        """Trigger encouragement if focus streak reached. Speaks response if fired."""
        text = self._pipeline.maybe_reinforce()
        if text is not None:
            self._speak(text)
        return text
