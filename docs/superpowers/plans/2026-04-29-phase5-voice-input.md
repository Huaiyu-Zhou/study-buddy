# Phase 5 — Voice Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add speech-to-text so the user can speak naturally and be heard by the coach, completing the full voice loop (speak → transcribe → Claude → TTS).

**Architecture:** A `voice_input.py` module runs Silero VAD on a PyAudio mic stream; when speech ends, the audio buffer is transcribed via `faster-whisper` on a thread-pool executor (keeping the event loop free). A `is_tts_playing` flag — set by `voice_output.speak()` — gates transcription so the mic is silent while the coach is talking. `VoicePipeline` gains a `listen_and_chat()` method that wires the full loop.

**Tech Stack:** `faster-whisper` (CTranslate2 backend), `silero-vad` (PyTorch), `PyAudio`, `asyncio.get_event_loop().run_in_executor`, existing `VoicePipeline` / `voice_output.speak`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `voice_input.py` | **Create** | VAD loop, Whisper transcription, `is_tts_playing` flag |
| `voice_output.py` | **Modify** | Set/clear `voice_input.is_tts_playing` around playback |
| `voice_pipeline.py` | **Modify** | Add `listen_and_chat()` that drives the full voice loop |
| `config.py` | **Modify** | Add `VAD_SILENCE_MS`, `VAD_THRESHOLD`, `MIC_SAMPLE_RATE` |
| `tests/test_voice_input.py` | **Create** | Unit tests for VAD gating, transcription, threading |
| `tests/test_voice_pipeline_phase5.py` | **Create** | Integration test for `listen_and_chat()` |
| `smoke_voice_input.py` | **Create** | End-to-end smoke: speak → transcribe → coach speaks back |

---

## Task 1: Config constants for voice input

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add constants**

  Open `config.py`. After the `WHISPER_MODEL_SIZE` line (line 29), add:

  ```python
  # Voice input (Phase 5)
  MIC_SAMPLE_RATE: int = 16000          # Whisper expects 16 kHz
  MIC_CHUNK_FRAMES: int = 512           # ~32 ms per chunk at 16 kHz
  VAD_THRESHOLD: float = 0.5            # Silero VAD confidence threshold
  VAD_SILENCE_MS: int = 700             # ms of silence before speech is considered done
  ```

- [ ] **Step 2: Verify import**

  ```bash
  python -c "import config; print(config.VAD_SILENCE_MS)"
  ```
  Expected output: `700`

- [ ] **Step 3: Commit**

  ```bash
  git add config.py
  git commit -m "config: add voice-input constants (Phase 5)"
  ```

---

## Task 2: `voice_input.py` — VAD + Whisper transcription

**Files:**
- Create: `voice_input.py`
- Create: `tests/test_voice_input.py`

### Step group A — failing tests first

- [ ] **Step 1: Write failing tests**

  Create `tests/test_voice_input.py`:

  ```python
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
  ```

- [ ] **Step 2: Run tests — expect failures**

  ```bash
  pytest tests/test_voice_input.py -v
  ```
  Expected: `ModuleNotFoundError: No module named 'voice_input'` (all fail).

### Step group B — implementation

- [ ] **Step 3: Install dependencies**

  ```bash
  pip install faster-whisper silero-vad
  ```

  Add to `requirements.txt`:
  ```
  faster-whisper
  silero-vad
  ```

- [ ] **Step 4: Create `voice_input.py`**

  ```python
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
  ```

- [ ] **Step 5: Run tests — expect pass**

  ```bash
  pytest tests/test_voice_input.py -v
  ```
  Expected: all 6 tests **PASS**.

- [ ] **Step 6: Commit**

  ```bash
  git add voice_input.py tests/test_voice_input.py requirements.txt
  git commit -m "feat(phase5): voice_input — VAD + faster-whisper transcription"
  ```

---

## Task 3: Wire `is_tts_playing` into `voice_output.speak()`

**Files:**
- Modify: `voice_output.py`
- Modify: `tests/test_voice_output.py` (append one test)

- [ ] **Step 1: Write failing test**

  Append to `tests/test_voice_output.py`:

  ```python
  def test_speak_clears_tts_flag_after_playback():
      """is_tts_playing must be False after speak() completes."""
      import voice_input
      import voice_output

      with (
          patch("voice_output.mute_mic"),
          patch("voice_output.unmute_mic"),
          patch("voice_output._create_client") as mock_client,
          patch("voice_output.pyaudio.PyAudio") as mock_pa,
      ):
          mock_client.return_value.tts.convert.return_value = iter([b"audio"])
          mock_stream = MagicMock()
          mock_pa.return_value.open.return_value = mock_stream
          voice_output.speak("hello")

      assert voice_input.is_tts_playing is False
  ```

- [ ] **Step 2: Run test — expect fail**

  ```bash
  pytest tests/test_voice_output.py::test_speak_clears_tts_flag_after_playback -v
  ```
  Expected: FAIL (ImportError or AttributeError — `voice_input` not set in `voice_output`).

- [ ] **Step 3: Update `voice_output.py`**

  Replace full file content:

  ```python
  import logging
  from typing import Optional

  import pyaudio
  from fishaudio import FishAudio

  import config
  import voice_input as _voice_input
  from mic_control import mute_mic, unmute_mic

  logger = logging.getLogger(__name__)


  def _create_client() -> FishAudio:
      """Create a Fish Audio client using the configured API key."""
      return FishAudio(api_key=config.FISH_AUDIO_API_KEY)


  def speak(text: Optional[str]) -> None:
      """Stream text through Fish Audio TTS and play through speakers.

      Sets voice_input.is_tts_playing=True during playback so the VAD loop
      skips transcription and prevents echo feedback.
      Mutes the microphone for the same reason.
      Handles errors gracefully — logs and continues, never raises.
      """
      if not text:
          return

      _voice_input.is_tts_playing = True
      mute_mic()
      try:
          client = _create_client()
          audio_stream = client.tts.convert(
              text=text,
              reference_id=config.FISH_AUDIO_REFERENCE_ID,
              format=config.TTS_OUTPUT_FORMAT,
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
          logger.error("TTS playback failed: %s", e)
      finally:
          _voice_input.is_tts_playing = False
          unmute_mic()
  ```

- [ ] **Step 4: Run all voice tests**

  ```bash
  pytest tests/test_voice_output.py tests/test_voice_input.py -v
  ```
  Expected: all **PASS**.

- [ ] **Step 5: Commit**

  ```bash
  git add voice_output.py tests/test_voice_output.py
  git commit -m "feat(phase5): set is_tts_playing flag in voice_output.speak()"
  ```

---

## Task 4: `VoicePipeline.listen_and_chat()` + smoke test

**Files:**
- Modify: `voice_pipeline.py`
- Create: `tests/test_voice_pipeline_phase5.py`
- Create: `smoke_voice_input.py`

### Step group A — failing tests

- [ ] **Step 1: Write failing tests**

  Create `tests/test_voice_pipeline_phase5.py`:

  ```python
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
  ```

- [ ] **Step 2: Run tests — expect failures**

  ```bash
  pytest tests/test_voice_pipeline_phase5.py -v
  ```
  Expected: FAIL (`VoicePipeline has no attribute 'listen_and_chat'`).

### Step group B — implementation

- [ ] **Step 3: Replace `voice_pipeline.py`**

  ```python
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
  ```

- [ ] **Step 4: Run all phase 5 tests**

  ```bash
  pytest tests/test_voice_pipeline_phase5.py tests/test_voice_input.py tests/test_voice_output.py -v
  ```
  Expected: all **PASS**.

- [ ] **Step 5: Full suite — no regressions**

  ```bash
  pytest -v
  ```
  Expected: all previously passing tests still **PASS**.

- [ ] **Step 6: Commit**

  ```bash
  git add voice_pipeline.py tests/test_voice_pipeline_phase5.py
  git commit -m "feat(phase5): VoicePipeline.listen_and_chat + start_listening"
  ```

### Step group C — smoke test

- [ ] **Step 7: Create `smoke_voice_input.py`**

  ```python
  """Smoke test — Phase 5 full voice loop.

  Run: python smoke_voice_input.py

  What happens:
    1. Coach speaks an intro prompt.
    2. A listen thread starts — speak into the mic.
    3. Your speech is transcribed and sent to the coach.
    4. The coach responds via TTS.
    5. Press Ctrl+C to end.

  Warning: downloads the faster-whisper 'base' model on first run (~150 MB).
  """
  import logging
  import time

  import openai

  import config
  from pipeline import CoachingPipeline
  from session import Session
  from voice_pipeline import VoicePipeline

  logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

  session = Session(plan="Review Python async/await", persona="encouraging tutor")
  client = openai.OpenAI(
      api_key=config.DEEPSEEK_API_KEY,
      base_url="https://api.deepseek.com",
  )
  cp = CoachingPipeline(session=session, client=client)
  vp = VoicePipeline(coaching_pipeline=cp)

  print("Starting voice loop. Speak into your mic. Ctrl+C to stop.")
  vp.chat("Your study session is starting. Greet the user in one sentence.")
  vp.start_listening()

  try:
      while True:
          time.sleep(1)
  except KeyboardInterrupt:
      print("\nSession ended.")
  ```

- [ ] **Step 8: Run smoke test manually**

  ```bash
  python smoke_voice_input.py
  ```

  Expected:
  - Coach speaks greeting via Fish Audio TTS.
  - Speak a sentence → it transcribes → coach replies via TTS.
  - No echo (mic muted + `is_tts_playing` blocks VAD during TTS).
  - Ctrl+C exits cleanly.

- [ ] **Step 9: Final commit**

  ```bash
  git add smoke_voice_input.py
  git commit -m "smoke: phase5 full voice loop (speak->transcribe->coach->TTS)"
  ```

---

## Self-Review

### 1. Spec coverage

| BUILD_PLAN.md item | Covered by |
|---|---|
| `voice_input.py` — load `faster-whisper` (`base` model, warn user) | Task 2, Step 4 (`_get_model` logs a warning before downloading) |
| Run Whisper in thread pool executor | Task 2 — `_executor`, `transcribe_in_executor` |
| Silero VAD loop, skip while TTS playing | Task 2 — `collect_speech_once` checks `is_tts_playing` at entry and mid-loop |
| Add STT to Pipecat pipeline | Task 4 — `listen_and_chat`, `start_listening` wires VAD→transcribe→`chat()` |
| Test barge-in | Task 3 — `is_tts_playing=True` causes `collect_speech_once` to return `None`, pausing collection; smoke validates end-to-end |

**Done when:** full voice loop works — speak → transcribe → Claude responds → TTS plays ✓

### 2. Placeholder scan — none found.

### 3. Type consistency

- `transcribe_audio(audio: np.ndarray) -> str` — imported and called identically in `voice_pipeline.py` ✓
- `listen_loop(callback: Callable[[str], None])` — wired to `_callback(text: str)` in `start_listening()` ✓
- `is_tts_playing: bool` — referenced as `_voice_input.is_tts_playing` in `voice_output.py` and as the module-level `voice_input.is_tts_playing` in `voice_input.py` ✓
