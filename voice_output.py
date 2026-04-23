import logging
from typing import Optional

import pyaudio
from elevenlabs.client import ElevenLabs

import config
from mic_control import mute_mic, unmute_mic

logger = logging.getLogger(__name__)


def _create_client() -> ElevenLabs:
    """Create an ElevenLabs client using the configured API key."""
    return ElevenLabs(api_key=config.ELEVENLABS_API_KEY)


def speak(text: Optional[str]) -> None:
    """Stream text through ElevenLabs TTS and play through speakers.

    Mutes the microphone during playback to prevent echo feedback.
    Handles errors gracefully — logs and continues, never raises.
    """
    if not text:
        return

    mute_mic()
    try:
        client = _create_client()

        audio_stream = client.text_to_speech.stream(
            text=text,
            voice_id=config.ELEVENLABS_VOICE_ID,
            model_id=config.ELEVENLABS_MODEL,
            output_format=config.TTS_OUTPUT_FORMAT,
        )

        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=config.TTS_SAMPLE_RATE,
            output=True,
        )
        try:
            for chunk in audio_stream:
                if isinstance(chunk, bytes):
                    stream.write(chunk)
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
    except Exception as e:
        logger.error(f"TTS playback failed: {e}")
    finally:
        unmute_mic()
