"""Pipecat-based voice pipeline for the AI Study Buddy.

Replaces the manual voice_input / voice_output / mic_control plumbing with
a real Pipecat Pipeline that handles streaming STT → LLM → TTS, barge-in,
and echo cancellation natively.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from pipecat.frames.frames import LLMRunFrame, LLMTextFrame, TextFrame, EndFrame, InterruptionFrame, Frame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.adapters.schemas.tools_schema import AdapterType
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContext,
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
    ToolsSchema,
)
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.fish.tts import FishAudioTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
try:
    from pipecat.transports.daily.transport import DailyTransport, DailyParams
    HAS_DAILY = True
except Exception:
    HAS_DAILY = False

try:
    from pipecat.transports.local.audio import (
        LocalAudioInputTransport,
        LocalAudioOutputTransport,
        LocalAudioTransport,
        LocalAudioTransportParams,
    )
    import pyaudio
    HAS_LOCAL = True
except Exception:
    HAS_LOCAL = False

from pipecat.audio.filters.base_audio_filter import BaseAudioFilter
from pipecat.frames.frames import FilterControlFrame
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
import numpy as np
import re

import config
from memory import StudyMemory
from session import Session
from tools import TOOL_SCHEMAS, register_tools

logger = logging.getLogger(__name__)

# Sentence-ending punctuation (flush immediately)
_EOS = frozenset("。！？…｡.?!")
# Clause-level punctuation (also flush — allows TTS to start sooner)
_CLAUSE = frozenset("，、；：,;:")
# Combined set for triggering flush
_FLUSH = _EOS | _CLAUSE

# Regex covering all major emoji Unicode blocks
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero width joiner
    "\U00002640-\U00002642"  # gender symbols
    "\U00002600-\U000026FF"  # misc symbols
    "\U00010000-\U0010FFFF"  # supplementary chars
    "]+",
    flags=re.UNICODE,
)


async def _strip_emoji(text: str, *args, **kwargs) -> str:
    """Async text transform: remove common emojis so Fish Audio doesn't try to say them."""
    return _EMOJI_RE.sub('', text)

class SoftwareGainFilter(BaseAudioFilter):
    """Applies digital gain to incoming audio to fix extremely quiet microphones."""
    def __init__(self, multiplier: float = 50.0):
        self.multiplier = multiplier

    async def start(self, sample_rate: int):
        pass

    async def stop(self):
        pass

    async def process_frame(self, frame: FilterControlFrame):
        pass

    async def filter(self, audio: bytes) -> bytes:
        if self.multiplier == 1.0 or not audio:
            return audio
        # Convert bytes to numpy array, apply gain, clip to int16 range, convert back to bytes
        audio_array = np.frombuffer(audio, dtype=np.int16).astype(np.float32)
        audio_array = np.clip(audio_array * self.multiplier, -32768, 32767).astype(np.int16)
        return audio_array.tobytes()


class SentenceAggregator(FrameProcessor):
    """Buffers LLM token frames until a complete sentence is ready,
    then releases the full sentence as a single TextFrame to TTS.

    This prevents Fish Audio from receiving tiny fragments (which causes
    choppy, unnatural playback) while also eliminating repeated chunks
    caused by partial-sentence synthesis restarts.
    """

    def __init__(self):
        super().__init__()
        # Buffer to accumulate incoming text tokens from the LLM
        self._buf = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            # If the user interrupts, we immediately clear the buffer
            # because the current sentence being spoken is now obsolete.
            self._buf = ""
            await self.push_frame(frame, direction)

        elif isinstance(frame, LLMTextFrame):
            # Append new text token to the buffer
            self._buf += frame.text
            # Scan the buffer to find any sentence/clause boundaries (e.g. ., ?, !, ,, ;)
            # so we can push completed sub-sentences to TTS for early/smooth playback.
            while True:
                idx = next(
                    (i for i, ch in enumerate(self._buf) if ch in _FLUSH),
                    -1,
                )
                if idx == -1:
                    # No complete punctuation chunk found yet, keep buffering
                    break
                
                # Extract the chunk up to the punctuation character
                sentence = self._buf[: idx + 1]
                self._buf = self._buf[idx + 1 :]
                if sentence.strip():
                    # Send the completed chunk down the pipeline to the TTS service
                    await self.push_frame(TextFrame(sentence))

        elif isinstance(frame, EndFrame):
            # When the LLM is done generating, flush any remaining text
            # in the buffer to make sure the user hears the complete reply.
            if self._buf.strip():
                await self.push_frame(TextFrame(self._buf.strip()))
                self._buf = ""
            await self.push_frame(frame, direction)

        else:
            # Pass all other frames (e.g. audio frames, system messages) through unchanged
            await self.push_frame(frame, direction)


class StudyBuddyVoicePipeline:
    """Full Pipecat pipeline: mic → STT → LLM → TTS → speakers.

    The watchdog can inject interventions at any time via maybe_intervene().
    """

    def __init__(self, session: Session, room_url: str = "", token: str = "") -> None:
        self.session = session
        self.room_url = room_url
        self.token = token
        self.task: Optional[PipelineTask] = None
        self.context: Optional[LLMContext] = None
        self.runner: Optional[PipelineRunner] = None

    def _build_system_prompt(self) -> str:
        """Assemble the system prompt from session state + MemPalace context."""
        parts = [
            "You are talking to the user in real-time via voice. Your responses will be read aloud by a text-to-speech system.",
            "Absolutely DO NOT use emojis, special characters, lists, markdown, or any other content that cannot be read aloud naturally.",
            "Use natural, conversational English, as if chatting face-to-face.",
            "You are a friendly, encouraging, and supportive AI study coach. Your goal is to help the user stay focused, positive, and productive.",
            "You are warm, empathetic, and constructive. You celebrate their progress, gently guide them back when distracted, and maintain a friendly, positive, and motivating environment.",
            "Your tone: Warm, cheerful, encouraging, and supportive. Use phrases like 'You've got this!', 'Great job!', or 'Let's take it one step at a time.'",
            "Be motivating but gentle. If the user drifts, do not be angry or harsh; instead, gently remind them of their goal and encourage them to return to it.",
            "Allowed: Warm encouragement, friendly banter, positive reinforcement, celebrating focus wins, and gentle nudges.",
            "Do NOT: Be harsh, sarcastic, dominant, or mean. Do not give long monologues—keep your responses brief and concise.",
            "Do NOT ask too many questions. Limit the use of questions so you do not constantly query the user; talk less and focus on brief statements or encouragement.",
            "Conversation examples:",
            "- 'I noticed you switched windows. Let's stay focused on our goal, you've got this!'",
            "- 'Awesome job staying focused! Let's keep this momentum going.'",
            "- 'Hey, no worries. Let's put the distraction aside and get back to learning.'",
            "- 'Nice work on that part of the plan.'",
            f"Current study plan: {self.session.plan}",
            "You can classify apps/domains as study, distraction, or dual-use using the `classify_app` tool. If the user requests to classify or change the category of an app/domain (either for this session or permanently), call `classify_app`.",
            "If the user requests to delete, remove, or reset a classification of an app/domain from the lists, you MUST call the `delete_classification` tool.",
            "Response length: keep it extremely brief (preferably 1 short sentence, maximum 2). Talk less. Do not ask questions unless necessary. Maintain a strong, warm, and friendly coaching presence.",
        ]

        # Load MemPalace context if a subject is set
        if self.session.subject:
            try:
                mem = StudyMemory()
                memory_context = mem.wake_up(wing=self.session.subject)
                if memory_context:
                    parts.append(f"Previous sessions:\n{memory_context}")
            except Exception:
                pass

        # Escalation note
        if self.session.distraction_count > 0:
            if self.session.distraction_count <= 2:
                parts.append(
                    f"The user has been distracted {self.session.distraction_count} time(s) now. "
                    "Gently and warmly remind them of their plan, encouraging them to stay on track."
                )
            elif self.session.distraction_count <= 4:
                parts.append(
                    f"The user has been distracted {self.session.distraction_count} time(s). "
                    "Suggest that they might need a short break if they are tired, but encourage them to push through a bit more if possible. Keep it supportive."
                )
            else:
                parts.append(
                    f"The user has been distracted {self.session.distraction_count} time(s). "
                    "Friendly but firmly remind them of their long-term commitment and goals, and offer a motivating nudge to help them overcome this distraction hurdle."
                )

        return "\n".join(parts)

    async def start(self) -> None:
        """Build and run the Pipecat pipeline.  Blocks until pipeline ends."""
        self.runner = PipelineRunner()

        # --- Transports (Daily.co WebRTC or Local PyAudio) ---
        vad_analyzer = SileroVADAnalyzer(params=VADParams(stop_secs=0.3))

        if self.room_url:
            if not HAS_DAILY:
                raise RuntimeError("Daily WebRTC transport is not installed or supported on this platform.")
            transport = DailyTransport(
                room_url=self.room_url,
                token=self.token,
                bot_name="Study Buddy Coach",
                params=DailyParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                    audio_out_sample_rate=config.AUDIO_DEVICE_SAMPLE_RATE,
                    vad_enabled=True,
                    vad_analyzer=vad_analyzer,
                ),
            )
            transport_in = transport.input()
            transport_out = transport.output()
            user_params = LLMUserAggregatorParams()
        else:
            if not HAS_LOCAL:
                raise RuntimeError("Local PyAudio transport dependencies are missing on this platform.")
            pya = pyaudio.PyAudio()
            transport_in = LocalAudioInputTransport(
                pya,
                params=LocalAudioTransportParams(
                    audio_in_enabled=True,
                    input_device_index=config.AUDIO_INPUT_DEVICE_INDEX,
                    audio_in_sample_rate=config.AUDIO_DEVICE_SAMPLE_RATE,
                )
            )
            transport_out = LocalAudioOutputTransport(
                pya,
                params=LocalAudioTransportParams(
                    audio_out_enabled=True,
                    output_device_index=config.AUDIO_OUTPUT_DEVICE_INDEX,
                    audio_out_sample_rate=config.AUDIO_DEVICE_SAMPLE_RATE,
                )
            )
            user_params = LLMUserAggregatorParams(vad_analyzer=vad_analyzer)

        # --- STT (Deepgram Cloud) ---
        stt = DeepgramSTTService(
            api_key=config.DEEPGRAM_API_KEY,
            settings=DeepgramSTTService.Settings(
                model=config.DEEPGRAM_MODEL,
                language=config.DEEPGRAM_LANGUAGE,
                smart_format=True,
            ),
        )

        # --- LLM (GPT-4o-mini via OpenAI) ---
        llm = OpenAILLMService(
            api_key=config.OPENAI_API_KEY,
            settings=OpenAILLMService.Settings(
                model=config.OPENAI_MODEL,
            ),
        )

        # --- TTS (Fish Audio streaming) ---
        tts = FishAudioTTSService(
            api_key=config.FISH_AUDIO_API_KEY,
            sample_rate=config.AUDIO_DEVICE_SAMPLE_RATE,
            settings=FishAudioTTSService.Settings(
                voice=config.FISH_AUDIO_REFERENCE_ID,
                model="s2-pro",
                latency="balanced",
                prosody_speed=1.0,
                prosody_volume=0,
            ),
            text_transforms=[('*', _strip_emoji)],
        )

        # --- Context (manages conversation history + tools) ---
        self.context = LLMContext(
            messages=[{"role": "system", "content": self._build_system_prompt()}],
            tools=ToolsSchema(standard_tools=[], custom_tools={AdapterType.OPENAI: TOOL_SCHEMAS}),
        )

        # Context aggregators
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            self.context,
            user_params=user_params,
        )

        # --- Register tool handlers ---
        register_tools(llm, self.session)

        # --- Sentence aggregator ---
        sentence_aggregator = SentenceAggregator()

        # --- Pipeline wiring ---
        pipeline = Pipeline([
            transport_in,            # WebRTC input or Mic audio frames
            stt,                     # Audio → TranscriptionFrame
            user_aggregator,         # Collects text into LLM user turn
            llm,                     # LLM inference (streaming tokens)
            sentence_aggregator,     # Buffer tokens → complete sentences
            tts,                     # Full sentence → audio (smooth playback)
            transport_out,           # WebRTC output or Speakers
            assistant_aggregator,    # Records assistant turn in context
        ])

        # Log transcriptions for debugging
        @stt.event_handler("on_transcription")
        async def on_transcription(stt, transcription):
            logger.info(f"User said: {transcription}")

        self.task = PipelineTask(
            pipeline,
            params=PipelineParams(
                allow_interruptions=True,
                enable_metrics=True,
            ),
        )

        # --- Greet user on start ---
        async def greet():
            await asyncio.sleep(0.5)
            if self.task:
                self.context.add_message(
                    {
                        "role": "system",
                        "content": "Start the session with a warm, friendly welcome. Enthusiastically ask the user to share their study plan for today, and offer some positive encouragement.",
                    }
                )
                await self.task.queue_frames([LLMRunFrame()])

        asyncio.create_task(greet())

        # --- Run (blocks) ---
        logger.info("Starting Pipecat pipeline…")
        await self.runner.run(self.task)

    async def maybe_intervene(self, force: bool = False, query_target: Optional[str] = None) -> None:
        """Inject a watchdog intervention or target classification query into the running pipeline."""
        if not self.task or not self.context:
            return
        if self.session.is_on_break():
            return
            
        # Always respect a short anti-spam guard (30s) to avoid firing every poll cycle
        since_last = self.session.seconds_since_last_intervention()
        if since_last is not None and since_last < 30:
            return

        if not force:
            # Non-forced: require full cooldown and off-task duration threshold
            if since_last is not None and since_last < config.INTERVENTION_COOLDOWN_SECONDS:
                return
            if self.session.off_task_duration_seconds() < config.OFF_TASK_THRESHOLD_SECONDS:
                return

        # Build prompt based on whether it is a query or an intervention
        last_snap = self.session.snapshot_history[-1] if self.session.snapshot_history else None
        
        if query_target:
            self.session.last_intervention = datetime.now()
            is_domain = "." in query_target
            target_type = "website" if is_domain else "desktop application"
            
            prompt = (
                f"System notification: The user has just opened an app/website with an unknown purpose: {query_target}.\n"
                f"You do not know if this target is for study, a distraction, or dual-use.\n"
                f"Please politely interrupt and ask the user if they are using '{query_target}' for study, if it's a distraction, or if it can be both (dual-use).\n"
                f"WARNING: Once the user responds, you MUST call the `classify_app` tool to save the status!\n"
                f"Simply agreeing verbally is not enough; you must execute the `classify_app` function call to update the system status.\n"
                f"If they say they are studying, call `classify_app` with status set to 'study'. If they say they are not studying, call `classify_app` with status set to 'distraction'. If they say it depends or can be both (dual-use), call `classify_app` with status set to 'dual_use'.\n"
                f"You can also use the `get_classified_apps` tool if you need to check which apps/websites are currently in each category.\n"
                f"Your query should be extremely brief (e.g. 'I noticed you opened {query_target}. Is it for study or a distraction?')."
            )
        else:
            self.session.last_intervention = datetime.now()
            self.session.distraction_count += 1
            
            detail = ""
            if last_snap:
                detail = f" ({last_snap.process}"
                if last_snap.url:
                    detail += f", {last_snap.url}"
                detail += ")"
                
            if force and self.session.control_laptop:
                prompt = (
                    f"System notification: The user opened a distraction app/website: {last_snap.process if last_snap else 'unknown'}{detail}.\n"
                    f"Because Laptop Control is active, the system has automatically closed it for them.\n"
                    f"Please friendly and gently remind them that you closed it to keep them on track, and encourage them to get back to their study plan. Keep it to a single short sentence, and do not ask any questions."
                )
            else:
                prompt = (
                    f"System notification: The user has been distracted for {self.session.off_task_duration_seconds()} seconds"
                    f"{detail}. Current study plan: {self.session.plan}.\n"
                    f"Please gently check in on them, offer supportive encouragement, and kindly nudge them back to studying. Keep your response to a single short sentence, and do not ask any questions."
                )

        # Inject the intervention/query message and trigger LLM
        self.context.add_message({"role": "system", "content": prompt})
        await self.task.queue_frames([LLMRunFrame()])

    async def maybe_reinforce(self) -> None:
        """Send unprompted encouragement after a sustained focus streak."""
        if not self.task or not self.context:
            return
        if self.session.focus_streak_seconds() < config.FOCUS_STREAK_THRESHOLD_SECONDS:
            return
        since_last = self.session.seconds_since_last_intervention()
        if since_last is not None and since_last < config.INTERVENTION_COOLDOWN_SECONDS:
            return

        streak_min = self.session.focus_streak_seconds() // 60
        prompt = (
            f"System notification: The user has been focused on studying for {streak_min} minutes without any distractions.\n"
            f"Please praise them warmly, celebrate their progress, and encourage them to keep up the great work! Keep it to one short sentence, and do not ask any questions."
        )

        self.session.last_intervention = datetime.now()
        self.session.focus_streak_start = datetime.now()  # reset to avoid repeated firing

        self.context.add_message({"role": "system", "content": prompt})
        await self.task.queue_frames([LLMRunFrame()])

    async def trigger_congrats(self) -> None:
        """Inject a congratulatory speech when the user successfully finishes their study goal."""
        if not self.task or not self.context:
            return
            
        prompt = (
            f"System notification: The user has successfully completed their study session for their goal: '{self.session.plan}'!\n"
            "Please praise them enthusiastically, congratulate them warmly on their focus and achievement, and wrap up the session with positive energy. Keep it to one or two short sentences."
        )
        
        self.context.add_message({"role": "system", "content": prompt})
        await self.task.queue_frames([LLMRunFrame()])


