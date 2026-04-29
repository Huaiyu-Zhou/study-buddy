import threading
from typing import Callable, Optional

import numpy as np

from pipeline import CoachingPipeline
from session import Session
from voice_input import listen_loop, transcribe_audio
from voice_output import speak as default_speak


class VoicePipeline:
    """Wraps CoachingPipeline to speak every response through TTS.

    Phase 5 additions
    -----------------
    listen_and_chat(audio)  — transcribe audio array, send to coach, speak reply
    start_listening()       — spawn daemon thread running voice_input.listen_loop
    """

    def __init__(
        self,
        coaching_pipeline: CoachingPipeline,
        speak_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._pipeline = coaching_pipeline
        self._speak = speak_fn or default_speak
        self._listen_thread: Optional[threading.Thread] = None

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

    def listen_and_chat(self, audio: np.ndarray) -> str:
        """Transcribe audio, send to coach, speak reply.

        Returns the coach's text response, or '' if transcription is empty.
        """
        user_text = transcribe_audio(audio)
        if not user_text:
            return ""
        return self.chat(user_text)

    def start_listening(self) -> None:
        """Spawn a daemon thread running the VAD->transcribe->chat loop."""
        def _callback(text: str) -> None:
            self.chat(text)

        self._listen_thread = threading.Thread(
            target=listen_loop,
            args=(_callback,),
            daemon=True,
            name="voice-listen-loop",
        )
        self._listen_thread.start()
