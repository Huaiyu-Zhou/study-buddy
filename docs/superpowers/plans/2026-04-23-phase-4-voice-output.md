# Phase 4: Voice Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the coaching pipeline speak aloud using Fish Audio streaming TTS with real-time PCM playback via PyAudio, including mic mute/unmute to prevent echo.

**Architecture:** `voice_output.py` wraps the Fish Audio SDK and PyAudio into two public functions: `speak(text)` for blocking playback and `speak_streamed(text)` for low-latency streaming. Mic mute/unmute uses `pycaw` to control the Windows default capture device. The existing `CoachingPipeline` stays unchanged — a new `VoicePipeline` wrapper in `voice_pipeline.py` calls pipeline methods and routes text responses through TTS. No Pipecat yet — Pipecat is introduced in Phase 5 when bidirectional voice (STT + TTS + barge-in) is needed.

**Tech Stack:** `Fish Audio` Python SDK, `pyaudio`, `pycaw`, existing `pipeline.py` / `session.py` / `config.py`, `pytest` + `pytest-mock`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `config.py` | Modify | Add `FISH_AUDIO_MODEL`, `TTS_OUTPUT_FORMAT`, `TTS_SAMPLE_RATE` |
| `requirements.txt` | Modify | Add `Fish Audio`, `pyaudio`, `pycaw` |
| `.env.example` | Modify | Add `DEEPSEEK_API_KEY` (missing from Phase 3) |
| `voice_output.py` | Create | Fish Audio TTS streaming + PyAudio playback |
| `mic_control.py` | Create | Mic mute/unmute via pycaw |
| `voice_pipeline.py` | Create | Wraps `CoachingPipeline`, routes responses through TTS |
| `tests/test_voice_output.py` | Create | Unit tests for voice_output module |
| `tests/test_mic_control.py` | Create | Unit tests for mic_control module |
| `tests/test_voice_pipeline.py` | Create | Unit tests for voice_pipeline module |
| `smoke_voice.py` | Create | Manual smoke test — coach speaks through speakers |

---

### Task 1: Extend config and requirements

**Files:**
- Modify: `config.py`
- Modify: `requirements.txt`
- Modify: `.env.example`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_phase4.py`:

```python
def test_FISH_AUDIO_model_is_defined():
    from config import FISH_AUDIO_MODEL
    assert isinstance(FISH_AUDIO_MODEL, str)
    assert len(FISH_AUDIO_MODEL) > 0


def test_tts_output_format_is_defined():
    from config import TTS_OUTPUT_FORMAT
    assert isinstance(TTS_OUTPUT_FORMAT, str)
    assert "pcm" in TTS_OUTPUT_FORMAT


def test_tts_sample_rate_is_defined():
    from config import TTS_SAMPLE_RATE
    assert isinstance(TTS_SAMPLE_RATE, int)
    assert TTS_SAMPLE_RATE > 0
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_config_phase4.py -v
```

Expected: `ImportError: cannot import name 'FISH_AUDIO_MODEL'`

- [ ] **Step 3: Add TTS constants to config.py**

Open `config.py` and add after the existing `FISH_AUDIO_VOICE_ID` line (after line 9):

```python
FISH_AUDIO_MODEL: str = os.getenv("FISH_AUDIO_MODEL", "eleven_flash_v2_5")
TTS_OUTPUT_FORMAT: str = "pcm_24000"   # raw 16-bit LE PCM at 24kHz — no decoding needed
TTS_SAMPLE_RATE: int = 24000
```

- [ ] **Step 4: Add dependencies to requirements.txt**

Append to `requirements.txt` after the `# Phase 3` section:

```
# Phase 4
Fish Audio>=1.0.0
pyaudio>=0.2.14
pycaw>=20240210
```

- [ ] **Step 5: Update .env.example**

Add to `.env.example`:

```
DEEPSEEK_API_KEY=your_key_here
```

- [ ] **Step 6: Install dependencies**

```
pip install Fish Audio pyaudio pycaw
```

- [ ] **Step 7: Run test to verify it passes**

```
pytest tests/test_config_phase4.py -v
```

Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add config.py requirements.txt .env.example tests/test_config_phase4.py
git commit -m "feat: add Fish Audio TTS config constants and Phase 4 dependencies"
```

---

### Task 2: Create mic_control.py — mic mute/unmute

**Files:**
- Create: `mic_control.py`
- Create: `tests/test_mic_control.py`

Mic control uses `pycaw` to access the Windows default capture device via COM. All COM calls are isolated in small functions so tests can mock them.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mic_control.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_mic_control.py -v
```

Expected: `ModuleNotFoundError: No module named 'mic_control'`

- [ ] **Step 3: Implement mic_control.py**

Create `mic_control.py`:

```python
import logging
from ctypes import cast, POINTER
from typing import Optional

logger = logging.getLogger(__name__)


def _get_mic_volume() -> Optional[object]:
    """Get the IAudioEndpointVolume interface for the default microphone.
    Returns None if no microphone is found or pycaw is unavailable.
    """
    try:
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        mic = AudioUtilities.GetMicrophone()
        if mic is None:
            logger.warning("No microphone found.")
            return None
        interface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    except Exception as e:
        logger.warning(f"Failed to access microphone: {e}")
        return None


def mute_mic() -> None:
    """Mute the default system microphone. No-op if unavailable."""
    volume = _get_mic_volume()
    if volume is None:
        return
    volume.SetMute(True, None)
    logger.debug("Microphone muted.")


def unmute_mic() -> None:
    """Unmute the default system microphone. No-op if unavailable."""
    volume = _get_mic_volume()
    if volume is None:
        return
    volume.SetMute(False, None)
    logger.debug("Microphone unmuted.")
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_mic_control.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add mic_control.py tests/test_mic_control.py
git commit -m "feat: mic_control — mute/unmute default microphone via pycaw"
```

---

### Task 3: Create voice_output.py — Fish Audio TTS + PyAudio playback

**Files:**
- Create: `voice_output.py`
- Create: `tests/test_voice_output.py`

The Fish Audio SDK streams raw PCM bytes via `client.text_to_speech.stream()` with `output_format="pcm_24000"`. PyAudio writes these bytes directly to the audio output — no MP3 decoding needed. Mic is muted while speaking to prevent echo feedback.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_voice_output.py`:

```python
from unittest.mock import MagicMock, patch, call
import voice_output


def test_create_FISH_AUDIO_client_uses_config_api_key(mocker):
    mocker.patch("config.FISH_AUDIO_API_KEY", "test-key-123")
    mock_client_cls = mocker.patch("voice_output.Fish Audio")
    voice_output._create_client()
    mock_client_cls.assert_called_once_with(api_key="test-key-123")


def test_speak_streams_text_to_audio(mocker):
    # Mock Fish Audio client
    mock_client = MagicMock()
    mock_stream = [b"\x00\x01" * 100, b"\x00\x02" * 100]
    mock_client.text_to_speech.stream.return_value = iter(mock_stream)
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
    mock_client.text_to_speech.stream.assert_called_once()
    call_kwargs = mock_client.text_to_speech.stream.call_args.kwargs
    assert call_kwargs["text"] == "Hello world"
    assert call_kwargs["output_format"] == "pcm_24000"

    # Verify audio chunks were written to PyAudio stream
    assert mock_audio_stream.write.call_count == 2

    # Verify mic was muted then unmuted
    mock_mute.assert_called_once()
    mock_unmute.assert_called_once()


def test_speak_unmutes_mic_on_error(mocker):
    mock_client = MagicMock()
    mock_client.text_to_speech.stream.side_effect = RuntimeError("API error")
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
    mock_client.text_to_speech.stream.assert_not_called()


def test_speak_skips_none_text(mocker):
    mock_client = MagicMock()
    mocker.patch("voice_output._create_client", return_value=mock_client)
    mocker.patch("voice_output.mute_mic")
    mocker.patch("voice_output.unmute_mic")

    voice_output.speak(None)
    mock_client.text_to_speech.stream.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_voice_output.py -v
```

Expected: `ModuleNotFoundError: No module named 'voice_output'`

- [ ] **Step 3: Implement voice_output.py**

Create `voice_output.py`:

```python
import logging
from typing import Optional

import pyaudio
from Fish Audio.client import Fish Audio

import config
from mic_control import mute_mic, unmute_mic

logger = logging.getLogger(__name__)


def _create_client() -> Fish Audio:
    """Create an Fish Audio client using the configured API key."""
    return Fish Audio(api_key=config.FISH_AUDIO_API_KEY)


def speak(text: Optional[str]) -> None:
    """Stream text through Fish Audio TTS and play through speakers.

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
            voice_id=config.FISH_AUDIO_VOICE_ID,
            model_id=config.FISH_AUDIO_MODEL,
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_voice_output.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add voice_output.py tests/test_voice_output.py
git commit -m "feat: voice_output — Fish Audio streaming TTS with PyAudio playback and mic mute"
```

---

### Task 4: Create voice_pipeline.py — voice-enabled pipeline wrapper

**Files:**
- Create: `voice_pipeline.py`
- Create: `tests/test_voice_pipeline.py`

`VoicePipeline` wraps `CoachingPipeline` and speaks every response. It exposes the same three public methods (`chat`, `maybe_intervene`, `maybe_reinforce`) but routes the text through `speak()` before returning.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_voice_pipeline.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_voice_pipeline.py -v
```

Expected: `ModuleNotFoundError: No module named 'voice_pipeline'`

- [ ] **Step 3: Implement voice_pipeline.py**

Create `voice_pipeline.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_voice_pipeline.py -v
```

Expected: all PASS

- [ ] **Step 5: Run full test suite to check for regressions**

```
pytest tests/ -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add voice_pipeline.py tests/test_voice_pipeline.py
git commit -m "feat: VoicePipeline — wraps CoachingPipeline with TTS voice output"
```

---

### Task 5: Smoke test — coach speaks through speakers

**Files:**
- Create: `smoke_voice.py`

This script hits the real Fish Audio and DeepSeek APIs. Requires `FISH_AUDIO_API_KEY`, `FISH_AUDIO_VOICE_ID`, and `DEEPSEEK_API_KEY` in `.env`.

- [ ] **Step 1: Create smoke_voice.py**

```python
"""
Smoke test for Phase 4 voice output — hits real Fish Audio + DeepSeek APIs.
Requires FISH_AUDIO_API_KEY, FISH_AUDIO_VOICE_ID, and DEEPSEEK_API_KEY in .env.

Usage: python smoke_voice.py
"""
from datetime import datetime, timedelta

import openai

import config
from session import Session, WindowSnapshot
from pipeline import CoachingPipeline
from voice_pipeline import VoicePipeline
from voice_output import speak


def main():
    print("=== Study Buddy — Phase 4 Voice Smoke Test ===\n")

    # Verify keys are set
    if not config.FISH_AUDIO_API_KEY:
        print("ERROR: FISH_AUDIO_API_KEY not set in .env")
        return
    if not config.FISH_AUDIO_VOICE_ID:
        print("ERROR: FISH_AUDIO_VOICE_ID not set in .env")
        return
    if not config.DEEPSEEK_API_KEY:
        print("ERROR: DEEPSEEK_API_KEY not set in .env")
        return

    # 1. Test raw TTS — speak a fixed string
    print("[Test 1] Raw TTS — speaking fixed text...")
    speak("Your study session is starting. Good luck.")
    print("[Test 1] DONE — did you hear it?\n")

    # 2. Test full voice pipeline — chat produces spoken audio
    print("[Test 2] Voice pipeline — chat turn...")
    session = Session(plan="calculus revision — integration by parts")
    client = openai.OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )
    coaching = CoachingPipeline(session, client)
    voice = VoicePipeline(coaching)

    reply = voice.chat("Hi, I just sat down to study.")
    print(f"[Coach] {reply}\n")

    # 3. Test intervention — watchdog trigger produces spoken audio
    print("[Test 3] Voice intervention — simulating off-task...")
    session.off_task_start = datetime.now() - timedelta(
        seconds=config.OFF_TASK_THRESHOLD_SECONDS + 10
    )
    session.last_intervention = None
    snap = WindowSnapshot(
        timestamp=datetime.now(),
        process="chrome.exe",
        window_title="YouTube - lofi beats",
        url="https://www.youtube.com/watch?v=xyz",
        idle_seconds=0,
        is_on_task=False,
    )
    session.snapshot_history.append(snap)
    reply = voice.maybe_intervene()
    print(f"[Intervention] {reply}\n")

    print("=== Smoke test complete ===")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the smoke test**

```
python smoke_voice.py
```

Verify:
- Test 1: "Your study session is starting. Good luck." plays through speakers
- Test 2: Coach response to "Hi, I just sat down to study." plays through speakers
- Test 3: Watchdog intervention response plays through speakers
- Microphone mutes while audio plays, unmutes after

- [ ] **Step 3: Commit**

```bash
git add smoke_voice.py
git commit -m "feat: smoke_voice.py — manual end-to-end test for Phase 4 voice output"
```

---

## Self-Review

**Spec coverage:**

| BUILD_PLAN requirement | Covered by |
|---|---|
| Add Fish Audio Turbo TTS to pipeline (streaming) | Task 3 — `voice_output.py` with `client.text_to_speech.stream()` |
| `voice_output.py` — mic mute/unmute hooks | Task 2 — `mic_control.py` + Task 3 — `speak()` calls mute/unmute |
| Smoke test: coach says "Your study session is starting. Good luck." | Task 5 — `smoke_voice.py` Test 1 |
| Done-when: watchdog trigger produces spoken audio through speakers | Task 5 — `smoke_voice.py` Test 3 |

**Placeholder scan:** None — all steps contain complete code.

**Type consistency:**
- `speak(text: Optional[str]) -> None` — defined Task 3, used in Task 4 and Task 5
- `mute_mic() -> None` / `unmute_mic() -> None` — defined Task 2, used in Task 3
- `_get_mic_volume() -> Optional[object]` — defined and mocked consistently in Task 2
- `VoicePipeline(coaching_pipeline, speak_fn)` — defined Task 4, used in Task 5
- `VoicePipeline.chat(str) -> str` — consistent with `CoachingPipeline.chat`
- `VoicePipeline.maybe_intervene() -> Optional[str]` — consistent with `CoachingPipeline.maybe_intervene`
- `VoicePipeline.maybe_reinforce() -> Optional[str]` — consistent with `CoachingPipeline.maybe_reinforce`
- `config.FISH_AUDIO_MODEL`, `config.TTS_OUTPUT_FORMAT`, `config.TTS_SAMPLE_RATE` — defined Task 1, used in Task 3
