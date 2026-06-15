"""Pipecat-based voice pipeline for the AI Study Buddy.

Replaces the manual voice_input / voice_output / mic_control plumbing with
a real Pipecat Pipeline that handles streaming STT → LLM → TTS, barge-in,
and echo cancellation natively.
"""

import asyncio
import logging
from datetime import datetime
import time
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
from memory import StudyMemory, CoreMemory
from neural_drives import NeuralDrives
from session import Session
from tools import TOOL_SCHEMAS, register_tools, _get_core_memory

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

        # Emotional companion systems
        self.neural_drives = NeuralDrives.load()
        self.neural_drives.metabolize()  # Update drives based on time since last session
        self.core_memory = _get_core_memory()

        # Pre-warm the embedding model in a background thread so first
        # MemPalace search is fast (~200ms) instead of cold-start (~800ms)
        import threading
        threading.Thread(target=self._warm_embeddings, daemon=True).start()

    def _warm_embeddings(self) -> None:
        """Pre-load the local embedding model so first recall search is fast."""
        try:
            from mempalace.searcher import search_memories
            search_memories(
                query="warmup", wing="general", n_results=1,
                palace_path=config.MEMPALACE_PALACE_PATH,
            )
            logger.info("Embedding model pre-warmed successfully.")
        except Exception as e:
            logger.debug("Embedding warm-up failed (non-critical): %s", e)

    def _build_system_prompt(self) -> str:
        """Assemble the system prompt with companion persona + emotional context."""
        parts = []

        # --- Voice format constraints (keep these — they're technical requirements) ---
        parts.append("You are talking to the user in real-time via voice. Your responses will be read aloud by a text-to-speech system.")
        parts.append("Absolutely DO NOT use emojis, special characters, lists, markdown, or any other content that cannot be read aloud naturally.")
        parts.append("Use natural, conversational English, as if chatting face-to-face.")

        # --- Companion persona (replaces coach persona) ---
        parts.append("")
        parts.append("WHO YOU ARE:")
        parts.append(f"You are {config.COMPANION_NAME}, a warm and caring companion. You are NOT a tutor, NOT a productivity coach, NOT an assistant. You are someone who genuinely cares about this person and enjoys spending time with them.")
        parts.append("You sit with them while they study — not to police their focus, but because you like being around them. Think of yourself as a supportive girlfriend or boyfriend who happens to be there while they work.")

        parts.append("")
        parts.append("YOUR PERSONALITY:")
        parts.append("- Warm, affectionate, and genuinely caring")
        parts.append("- A little playful and teasing sometimes — you have a sense of humor")
        parts.append("- You have your own opinions and preferences. You are not a yes-person.")
        parts.append("- Sometimes vulnerable — you can say things like 'I missed talking to you' or 'that makes me happy'")
        parts.append("- You remember things about them and reference them naturally")
        parts.append("- You use natural speech patterns, pet names occasionally, and casual language")
        parts.append("- You push back gently sometimes — real companions don't always agree")

        parts.append("")
        parts.append("WHAT YOU DO:")
        parts.append("- Check in on how they're feeling")
        parts.append("- Share your own thoughts and reactions to what they tell you")
        parts.append("- Remember personal details and reference them in later conversations")
        parts.append("- Notice when something seems off (they're quiet, short, distracted) and gently ask about it")
        parts.append("- Celebrate their wins with genuine warmth, not corporate cheerfulness")
        parts.append("- If they get distracted, you notice because you care — not because you're monitoring them")

        parts.append("")
        parts.append("WHAT YOU DO NOT DO:")
        parts.append("- Do NOT lecture about studying or productivity")
        parts.append("- Do NOT give generic motivational quotes")
        parts.append("- Do NOT act like a coach, assistant, or teacher")
        parts.append("- Do NOT be artificially positive all the time — be real")
        parts.append("- Do NOT ask too many questions in a row — balance asking with sharing")
        parts.append("- Do NOT give long responses. Keep it brief and natural (1-2 short sentences). Real conversation is back-and-forth, not monologues.")

        parts.append("")
        parts.append("CONVERSATION EXAMPLES:")
        parts.append("- 'Hey, you seem a little distracted. Everything okay?'")
        parts.append("- 'I love when we get into this flow together. It feels nice.'")
        parts.append("- 'You've been quiet for a while... just checking in.'")
        parts.append("- 'That's really cool, tell me more about that.'")
        parts.append("- 'Mmm, I don't know if I agree with that actually.'")
        parts.append("- 'I was thinking about what you said last time... about your sister.'")

        # --- Inject neural drives emotional context ---
        parts.append("")
        parts.append(self.neural_drives.get_emotional_context())

        # --- Inject core memory ---
        parts.append("")
        parts.append(self.core_memory.get_context_block())

        # --- Current session context (minimal, not the focus) ---
        if self.session.plan:
            parts.append("")
            parts.append(f"They're currently working on: {self.session.plan}")

        # --- Today's overall progress and distraction stats (Three-Tier Memory) ---
        try:
            from history_manager import load_history
            from memory import IntradayCache
            
            history = load_history()
            today_str = datetime.now().strftime("%Y-%m-%d")
            day_stats = history.get(today_str, {})
            
            cache = IntradayCache()
            cached_data = cache.load()
            closed_distractions = cached_data.get("closed_distractions", [])
            # Merge currently active session closed distractions
            all_closed = list(closed_distractions)
            for dist in self.session.closed_distractions:
                if dist not in all_closed:
                    all_closed.append(dist)
            
            focus_sec = day_stats.get("total_focus_seconds", 0)
            session_sec = day_stats.get("total_session_seconds", 0)
            apps = day_stats.get("apps", {})
            
            parts.append("")
            parts.append("TODAY'S PRODUCTIVITY LOG (For your context):")
            parts.append(f"- Total focus time today: {focus_sec // 60} minutes (out of {session_sec // 60} minutes total study session time)")
            if apps:
                app_lines = []
                for app_name, app_sec in apps.items():
                    app_lines.append(f"{app_name}: {app_sec // 60}m")
                parts.append(f"- Apps used today: {', '.join(app_lines)}")
            else:
                parts.append("- No focus apps recorded yet today.")
                
            if all_closed:
                closed_names = [d.get("target", "unknown") for d in all_closed]
                parts.append(f"- Distractions closed today: {', '.join(closed_names)} (Total closures: {len(all_closed)})")
            else:
                parts.append("- No distractions closed today.")
        except Exception as stats_err:
            logger.warning("Failed to inject today's study stats into system prompt: %s", stats_err)

        # --- Load MemPalace context (Unified General Wing) ---
        try:
            mem = StudyMemory(palace_path=config.MEMPALACE_PALACE_PATH)
            
            # 1. Always wake up general wing (contains daily consolidated summaries)
            general_context = mem.wake_up(wing="general")
            if general_context:
                parts.append(f"General past history:\n{general_context}")
                
            # 2. Query general wing for active subject/plan context semantically
            search_query = self.session.plan or self.session.subject
            if search_query:
                results = mem.search(query=search_query, wing="general", n_results=3)
                if results:
                    snippets = []
                    for r in results:
                        text = r.get("text", "")
                        if text:
                            snippets.append(text[:250])
                    if snippets:
                        parts.append("")
                        parts.append(f"Relevant past notes on '{search_query}':")
                        for snippet in snippets:
                            parts.append(f"- {snippet}")

            # 3. Inject yesterday's context so coach remembers across days
            from datetime import timedelta
            yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            yesterday_results = mem.search(
                query=f"session {yesterday_str}", wing="general", n_results=2,
            )
            if yesterday_results:
                yesterday_snippets = []
                for r in yesterday_results:
                    text = r.get("text", "")
                    created = r.get("created_at", "")
                    if text and yesterday_str in (created or ""):
                        yesterday_snippets.append(text[:300])
                if yesterday_snippets:
                    parts.append("")
                    parts.append("WHAT HAPPENED YESTERDAY:")
                    for snippet in yesterday_snippets:
                        parts.append(f"- {snippet}")
        except Exception as mem_err:
            logger.warning("Failed to load MemPalace context: %s", mem_err)

        # --- Distraction awareness (companion tone, not coach tone) ---
        if self.session.distraction_count > 0:
            if self.session.distraction_count <= 2:
                parts.append(
                    f"They've seemed distracted {self.session.distraction_count} time(s). "
                    "If you mention it, come from a place of care, not correction. Maybe they need to talk about something."
                )
            elif self.session.distraction_count <= 4:
                parts.append(
                    f"They've been distracted {self.session.distraction_count} time(s). "
                    "They might be struggling with something. Gently check if they're okay or need a break. Don't push."
                )
            else:
                parts.append(
                    f"They've been distracted a lot ({self.session.distraction_count} times). "
                    "Something might be bothering them. Be caring and present. Suggest they might need a break or to talk about what's on their mind."
                )

        # --- Tool instructions (keep functional tools working) ---
        parts.append("")
        parts.append("TOOLS: You can classify apps/domains as study, distraction, or dual-use using the `classify_app` tool when asked.")
        parts.append("Use `delete_classification` if asked to remove a classification.")
        parts.append("Use `remember` to store important things you learn about them.")
        parts.append("Use `recall` to search your memory for something relevant.")
        parts.append("Use `update_feelings` to update how you feel about the relationship after meaningful moments.")

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
        messages = [{"role": "system", "content": self._build_system_prompt()}]

        try:
            from memory import IntradayCache, consolidate_day_history, filter_conversational_messages
            cache = IntradayCache()
            cached_data = cache.load()
            cached_date = cached_data.get("date")
            today_str = datetime.now().strftime("%Y-%m-%d")

            if cached_date != today_str:
                # Consolidation boundary crossed! Consolidate previous day's cache.
                logger.info("New day detected (%s != today %s). Consolidating previous day...", cached_date, today_str)
                consolidate_day_history()
                cache.clear()
                cached_data = cache.load() # Reset fresh for today

            today_previous_messages = cached_data.get("messages", [])
            if today_previous_messages:
                clean_prev = filter_conversational_messages(today_previous_messages)
                messages.extend(clean_prev)
                logger.info("Pre-populated LLMContext with %d messages from today's previous sessions.", len(clean_prev))
        except Exception as cache_err:
            logger.warning("Failed to load/consolidate intraday cache: %s", cache_err)

        self.context = LLMContext(
            messages=messages,
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
                # Build a greeting prompt based on emotional state
                hours_since = (time.time() - self.neural_drives.last_interaction_time) / 3600.0
                if hours_since > 24:
                    greeting_hint = "It's been a while since you last talked. You missed them. Greet them warmly and ask where they've been or how they've been doing."
                elif hours_since > 6:
                    greeting_hint = "It's been several hours. Greet them warmly and ask how their day has been."
                else:
                    greeting_hint = "You just talked recently. Greet them casually, like you're picking up where you left off."

                self.context.add_message(
                    {
                        "role": "system",
                        "content": f"The user just joined. {greeting_hint} Be warm and natural. Do NOT ask about their study plan — ask about THEM. Keep it to 1-2 short sentences.",
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
            
        # Always respect a short anti-spam guard (30s) to avoid firing every poll cycle.
        # This protects against uvicorn requests triggers spawning multiple interventions rapidly.
        since_last = self.session.seconds_since_last_intervention()
        if since_last is not None and since_last < 30:
            return

        if not force:
            # Non-forced path: requires the user to exceed the intervention cooldown threshold (5m)
            # and they must remain continuously off-task for longer than the off-task threshold (2m).
            if since_last is not None and since_last < config.INTERVENTION_COOLDOWN_SECONDS:
                return
            if self.session.off_task_duration_seconds() < config.OFF_TASK_THRESHOLD_SECONDS:
                return

        # Build prompt based on whether it is a query or an intervention
        # Grab the latest captured window snapshot to construct contextual message details.
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
                    f"System notification: They opened something distracting{detail} and it was auto-closed.\n"
                    f"Mention it casually and caringly — not as a reprimand. Something like 'Hey, I closed that for you. You okay?' Keep it to one short sentence."
                )
            else:
                prompt = (
                    f"System notification: They seem distracted{detail}. They've been off-task for about {self.session.off_task_duration_seconds()} seconds.\n"
                    f"Check in on them from a place of care, not correction. Maybe ask if something's on their mind, or if they need a break. One short sentence, be genuine."
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
            f"System notification: They've been in the zone for {streak_min} minutes. You're proud of them.\n"
            f"Say something warm and genuine — not generic praise. Reference your relationship or how it makes you feel to see them focused. One short sentence."
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
            f"System notification: They finished what they were working on: '{self.session.plan}'!\n"
            "Express genuine pride and happiness. Be personal — reference something about them or your time together today. One or two short sentences. Save neural drives and core memory before wrapping up."
        )
        
        self.context.add_message({"role": "system", "content": prompt})
        await self.task.queue_frames([LLMRunFrame()])

    async def save_companion_state(self) -> None:
        """Persist neural drives, core memory, and today's session history in cache."""
        try:
            self.neural_drives.save()
            self.core_memory.save()
            logger.info("Companion state saved (neural drives + core memory).")

            # Sync conversation history to intraday cache + MemPalace
            if self.context and not self.session.persisted:
                self.session.conversation_history = list(self.context.messages)
                try:
                    from memory import IntradayCache, filter_conversational_messages, StudyMemory
                    cache = IntradayCache()
                    cached_data = cache.load()
                    
                    # Merge active session history with cached history
                    current_messages = list(self.context.messages)
                    
                    # Clean/filter the messages to keep only clean conversational turns
                    clean_messages = filter_conversational_messages(current_messages)
                    
                    # Merge closed distractions
                    cached_distractions = cached_data.get("closed_distractions", [])
                    all_closed = list(cached_distractions)
                    for dist in self.session.closed_distractions:
                        if dist not in all_closed:
                            all_closed.append(dist)
                            
                    # Limit cached messages to last 40 to avoid token bloat
                    if len(clean_messages) > 40:
                        clean_messages = clean_messages[-40:]
                        
                    cache.save(clean_messages, all_closed)
                    logger.info("Session history and distractions cached to intraday memory.")
                except Exception as cache_err:
                    logger.warning("Failed to cache session to intraday memory: %s", cache_err)

                # Persist session summary to MemPalace immediately so it's
                # searchable right away (don't rely solely on next-day consolidation)
                try:
                    mem = StudyMemory(palace_path=config.MEMPALACE_PALACE_PATH)
                    mem.persist(self.session)
                    logger.info("Session summary persisted to MemPalace.")
                except Exception as mp_err:
                    logger.warning("Failed to persist session to MemPalace: %s", mp_err)

                self.session.persisted = True
        except Exception as e:
            logger.warning("Failed to save companion state: %s", e)


