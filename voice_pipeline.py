"""Pipecat-based voice pipeline for the AI Study Buddy.

Replaces the manual voice_input / voice_output / mic_control plumbing with
a real Pipecat Pipeline that handles streaming STT → LLM → TTS, barge-in,
and echo cancellation natively.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from pipecat.frames.frames import LLMRunFrame
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
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.audio.vad.silero import SileroVADAnalyzer

import config
from memory import StudyMemory
from session import Session
from tools import TOOL_SCHEMAS, register_tools

logger = logging.getLogger(__name__)


class StudyBuddyVoicePipeline:
    """Full Pipecat pipeline: mic → STT → LLM → TTS → speakers.

    The watchdog can inject interventions at any time via maybe_intervene().
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.task: Optional[PipelineTask] = None
        self.context: Optional[LLMContext] = None
        self.runner: Optional[PipelineRunner] = None

    def _build_system_prompt(self) -> str:
        """Assemble the system prompt from session state + MemPalace context."""
        parts = [
            f"You are a study coach with the persona: {self.session.persona}.",
            f"The user's current study plan: {self.session.plan}.",
            "Monitor focus, give brief interventions when off-task, and celebrate streaks.",
            "Keep responses concise — 1-3 sentences unless the user asks for more.",
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
                    f"The user has drifted off-task {self.session.distraction_count} time(s). "
                    "Be a bit firmer."
                )
            elif self.session.distraction_count <= 4:
                parts.append(
                    f"The user has drifted off-task {self.session.distraction_count} times. "
                    "Use a noticeably firmer, more direct tone."
                )
            else:
                parts.append(
                    f"The user has drifted {self.session.distraction_count} times — something seems off. "
                    "Shift to a reflective, empathetic mode: ask what's going on."
                )

        return "\n".join(parts)

    async def start(self) -> None:
        """Build and run the Pipecat pipeline.  Blocks until pipeline ends."""
        self.runner = PipelineRunner()

        # --- Transport (mic + speakers via PyAudio) ---
        transport = LocalAudioTransport(
            params=LocalAudioTransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
            )
        )

        # --- STT (local faster-whisper) ---
        stt = WhisperSTTService(
            settings=WhisperSTTService.Settings(
                model=config.WHISPER_MODEL_SIZE,
            ),
        )

        # --- LLM (DeepSeek via OpenAI-compatible endpoint) ---
        llm = OpenAILLMService(
            api_key=config.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
            settings=OpenAILLMService.Settings(
                model=config.DEEPSEEK_MODEL,
            ),
        )

        # --- TTS (Fish Audio streaming) ---
        tts = FishAudioTTSService(
            api_key=config.FISH_AUDIO_API_KEY,
            settings=FishAudioTTSService.Settings(
                voice=config.FISH_AUDIO_REFERENCE_ID,
            ),
        )

        # --- Context (manages conversation history + tools) ---
        self.context = LLMContext(
            messages=[{"role": "system", "content": self._build_system_prompt()}],
            tools=ToolsSchema(standard_tools=[], custom_tools={AdapterType.OPENAI: TOOL_SCHEMAS}),
        )

        # Context aggregators: user_aggregator collects STT text into user turns,
        # assistant_aggregator collects LLM output into assistant turns.
        # VAD is attached to the user aggregator so speech boundaries are detected.
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            self.context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(),
            ),
        )

        # --- Register tool handlers ---
        register_tools(llm, self.session)

        # --- Pipeline wiring ---
        pipeline = Pipeline([
            transport.input(),       # Mic audio frames
            stt,                     # Audio → TranscriptionFrame
            user_aggregator,         # Collects text into LLM user turn
            llm,                     # LLM inference (streaming)
            tts,                     # Text → audio (streaming)
            transport.output(),      # Audio → speakers
            assistant_aggregator,    # Records assistant turn in context
        ])

        self.task = PipelineTask(
            pipeline,
            params=PipelineParams(
                allow_interruptions=True,
                enable_metrics=True,
            ),
        )

        # --- Event: greet user on connect ---
        @transport.event_handler("on_client_connected")
        async def on_connected(transport, client):
            self.context.add_message(
                "developer",
                "Introduce yourself briefly as the user's study coach and ask what they are studying today.",
            )
            await self.task.queue_frames([LLMRunFrame()])

        # --- Run (blocks) ---
        logger.info("Starting Pipecat pipeline…")
        await self.runner.run(self.task)

    async def maybe_intervene(self) -> None:
        """Inject a watchdog intervention into the running pipeline.

        Called from the async watchdog loop when the user has been off-task
        long enough and cooldown has expired.
        """
        if not self.task or not self.context:
            return
        if self.session.is_on_break():
            return
        if self.session.off_task_duration_seconds() < config.OFF_TASK_THRESHOLD_SECONDS:
            return
        since_last = self.session.seconds_since_last_intervention()
        if since_last is not None and since_last < config.INTERVENTION_COOLDOWN_SECONDS:
            return

        # Build context about the current distraction
        last_snap = self.session.snapshot_history[-1] if self.session.snapshot_history else None
        detail = ""
        if last_snap:
            detail = f" ({last_snap.process}"
            if last_snap.url:
                detail += f", {last_snap.url}"
            detail += ")"

        self.session.last_intervention = datetime.now()
        self.session.distraction_count += 1

        prompt = (
            f"[WATCHDOG] User has been off-task for {self.session.off_task_duration_seconds()}s"
            f"{detail}. Study plan: {self.session.plan}. Intervene now."
        )

        # Inject the intervention message and trigger LLM
        self.context.add_message("developer", prompt)
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
            f"[WATCHDOG] The user has been focused for {streak_min} minutes without drifting. "
            "Give brief, warm encouragement. One sentence only."
        )

        self.session.last_intervention = datetime.now()
        self.session.focus_streak_start = datetime.now()  # reset to avoid repeated firing

        self.context.add_message("developer", prompt)
        await self.task.queue_frames([LLMRunFrame()])
