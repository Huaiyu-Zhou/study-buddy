"""Phase 5 — Voice Input: VAD loop + faster-whisper transcription.

Public API
----------
is_tts_playing : bool
    Set to True by voice_output.speak() during playback.
    collect_speech_once() returns None while this flag is True.

transcribe_audio(audio: np.ndarray) -> str
    Synchronous. Runs faster-whisper on float32 16 kHz audio.

transcribe_in_executor(audio: np.ndarray) -> Coroutine[str]
    Async wrapper — runs transcribe_audio on the default thread-pool executor.

collect_speech_once(mic_stream) -> np.ndarray | None
    Reads from an open PyAudio stream until VAD detects end-of-speech.
    Returns float32 audio array, or None if TTS is playing.

listen_loop(callback) -> None
    Blocking loop: collect_speech_once -> transcribe -> callback(text).
    Call on a daemon thread.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

import numpy as np
import pyaudio
import torch

import config

logger = logging.getLogger(__name__)

# Global flag — set by voice_output.speak() to gate transcription
is_tts_playing: bool = False

# Thread-pool for running Whisper off the event loop
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper")

# Lazy-loaded Whisper model (downloaded on first call)
_model = None


def _get_model():
    """Return the faster-whisper model, downloading on first call."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        logger.warning(
            "Downloading faster-whisper '%s' model — this may take a minute on first run.",
            config.WHISPER_MODEL_SIZE,
        )
        _model = WhisperModel(config.WHISPER_MODEL_SIZE, compute_type="int8")
        logger.info("faster-whisper model loaded.")
    return _model


def transcribe_audio(audio: np.ndarray) -> str:
    """Transcribe float32 16 kHz audio. Returns stripped text string."""
    model = _get_model()
    segments, _ = model.transcribe(audio, language="en", beam_size=1)
    return "".join(seg.text for seg in segments).strip()


async def transcribe_in_executor(audio: np.ndarray) -> str:
    """Run transcribe_audio on the thread-pool executor (non-blocking)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, transcribe_audio, audio)


def _load_vad_model():
    """Load Silero VAD model from torch hub."""
    model, utils = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        force_reload=False,
        onnx=False,
    )
    return model, utils


def collect_speech_once(mic_stream) -> Optional[np.ndarray]:
    """Read mic until end-of-speech. Returns float32 audio or None if TTS active.

    Parameters
    ----------
    mic_stream : pyaudio.Stream
        Already-open PyAudio input stream at MIC_SAMPLE_RATE, paInt16, mono.
    """
    if is_tts_playing:
        return None

    vad_model, _ = _load_vad_model()
    silence_limit = int(
        config.VAD_SILENCE_MS / 1000 * config.MIC_SAMPLE_RATE / config.MIC_CHUNK_FRAMES
    )

    speech_frames = []
    silent_chunks = 0
    speaking = False

    while True:
        if is_tts_playing:
            return None

        raw = mic_stream.read(config.MIC_CHUNK_FRAMES, exception_on_overflow=False)
        pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        chunk_tensor = torch.from_numpy(pcm)

        confidence = vad_model(chunk_tensor, config.MIC_SAMPLE_RATE).item()
        is_speech = confidence >= config.VAD_THRESHOLD

        if is_speech:
            speaking = True
            silent_chunks = 0
            speech_frames.append(pcm)
        elif speaking:
            speech_frames.append(pcm)
            silent_chunks += 1
            if silent_chunks >= silence_limit:
                break

    return np.concatenate(speech_frames) if speech_frames else None


def listen_loop(callback: Callable[[str], None]) -> None:
    """Blocking listen loop. Run on a daemon thread.

    Continuously collects speech, transcribes it, and calls callback(text).
    Skips silently when TTS is playing.
    """
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=config.MIC_SAMPLE_RATE,
        input=True,
        frames_per_buffer=config.MIC_CHUNK_FRAMES,
    )
    logger.info("Microphone listen loop started.")
    try:
        while True:
            audio = collect_speech_once(stream)
            if audio is None:
                continue
            text = transcribe_audio(audio)
            if text:
                logger.info("Transcribed: %s", text)
                callback(text)
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
