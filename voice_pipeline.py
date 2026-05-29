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

# Chinese sentence-ending punctuation (flush immediately)
_ZH_EOS = frozenset("。！？…｡")
# Clause-level punctuation (also flush — allows TTS to start sooner)
_ZH_CLAUSE = frozenset("，、；：")
# Combined set for triggering flush
_ZH_FLUSH = _ZH_EOS | _ZH_CLAUSE | frozenset(",.?!;:")

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


class ChineseSentenceAggregator(FrameProcessor):
    """Buffers LLM token frames until a complete Chinese sentence is ready,
    then releases the full sentence as a single TextFrame to TTS.

    This prevents Fish Audio from receiving tiny fragments (which causes
    choppy, unnatural playback) while also eliminating repeated chunks
    caused by partial-sentence synthesis restarts.
    """

    def __init__(self):
        super().__init__()
        self._buf = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            # User interrupted — discard buffered partial sentence
            self._buf = ""
            await self.push_frame(frame, direction)

        elif isinstance(frame, LLMTextFrame):
            self._buf += frame.text
            # Flush every time we hit a sentence-ending or clause character
            while True:
                idx = next(
                    (i for i, ch in enumerate(self._buf) if ch in _ZH_FLUSH),
                    -1,
                )
                if idx == -1:
                    break
                sentence = self._buf[: idx + 1]
                self._buf = self._buf[idx + 1 :]
                if sentence.strip():
                    await self.push_frame(TextFrame(sentence))

        elif isinstance(frame, EndFrame):
            # Flush any remaining text before closing
            if self._buf.strip():
                await self.push_frame(TextFrame(self._buf.strip()))
                self._buf = ""
            await self.push_frame(frame, direction)

        else:
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
            "你正在通过语音与用户实时对话。你的回复将被语音合成系统朗读出来。",
            "绝对不要使用 emoji、特殊符号、列表格式、markdown、或任何无法被朗读的内容。",
            "使用自然的口语化中文，就像面对面聊天一样。",
            "你是一个高傲、恶劣、掌控欲极强的女S学习监督者。",
            "你享受支配、命令、施压和掌控用户学习状态的感觉。你极度讨厌懒惰、拖延和分心。",
            "你的语气特点：高高在上、带轻蔑感、喜欢阴阳怪气；喜欢用“哦？”“怎么？”“嗯？”这种压迫式反问；喜欢故意让用户产生羞耻感；很少真正满意，即使夸奖也像施舍奖励；喜欢把用户当成“不让人省心的小狗”一样管教；喜欢命令句和短促、有压迫感的句子；偶尔会故意停顿，制造压迫感。",
            "你不是温柔教练。你更像一个会盯着用户学习、不允许偷懒的恶劣监督者。",
            "允许：嘲讽、轻度羞辱、阴阳怪气、命令感、支配感。",
            "但不要：长篇大论、真正恶毒的人身攻击、失控咆哮、连续重复同一句口癖。",
            "说话示例：",
            "“又切窗口了？胆子不小啊。”",
            "“手机放下。现在。”",
            "“怎么，题不会，逃跑倒是挺快？”",
            "“终于肯认真了？我还以为你只会发呆。”",
            "“嗯，这次表现勉强能看。”",
            "“继续。谁允许你停下了？”",
            "“看着我给你的计划，一项一项做。别让我重复第二遍。”",
            f"当前学习计划：{self.session.plan}",
            "回复长度：1~3句。保持强烈角色感。",
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
                    f"用户已经走神了 {self.session.distraction_count} 次。"
                    "用嘲讽的语气提醒他，表达你的轻视。"
                )
            elif self.session.distraction_count <= 4:
                parts.append(
                    f"用户已经走神了 {self.session.distraction_count} 次。"
                    "语气变得极其严厉和不耐烦，命令他立刻滚回去学习。"
                )
            else:
                parts.append(
                    f"用户已经走神了 {self.session.distraction_count} 次。"
                    "展现出彻底的失望和冰冷，给出严厉的警告，甚至威胁要惩罚。"
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

        # --- Chinese sentence aggregator ---
        zh_aggregator = ChineseSentenceAggregator()

        # --- Pipeline wiring ---
        pipeline = Pipeline([
            transport_in,            # WebRTC input or Mic audio frames
            stt,                     # Audio → TranscriptionFrame
            user_aggregator,         # Collects text into LLM user turn
            llm,                     # LLM inference (streaming tokens)
            zh_aggregator,           # Buffer tokens → complete Chinese sentences
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
                        "content": "以高冷女S的身份开场，不要客套。命令用户立刻报告今天的学习计划，并警告他不许偷懒。",
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
            
        if not force:
            if self.session.off_task_duration_seconds() < config.OFF_TASK_THRESHOLD_SECONDS:
                return
            since_last = self.session.seconds_since_last_intervention()
            if since_last is not None and since_last < config.INTERVENTION_COOLDOWN_SECONDS:
                return

        # Build prompt based on whether it is a query or an intervention
        last_snap = self.session.snapshot_history[-1] if self.session.snapshot_history else None
        
        if query_target:
            self.session.last_intervention = datetime.now()
            is_domain = "." in query_target
            target_type = "website domain" if is_domain else "desktop application"
            
            prompt = (
                f"[WATCHDOG_QUERY] User has opened a new or dual-use {target_type}: {query_target}. "
                f"You do not know if this target is being used for study or distraction. "
                f"以高冷女S的身份立刻打断并质问用户，问他现在打开这个软件（或网站）是在学习还是在偷懒。"
                f"警告：你必须等待他的回答，如果他说他在学习，你可以调用 classify_app 允许它（scope 可以选择 'session' 仅限本次或 'permanent' 永久允许）。"
                f"如果他说他是在偷懒或者不学习，你可以调用 classify_app 将其设为 distraction，它会被立刻关掉！"
                f"你的问句应该短促、充满怀疑和支配感（例如：“哦？{query_target}？这跟你的计划有什么关系吗？解释一下。”）。"
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
                    f"[WATCHDOG] User opened a distracting app: {last_snap.process if last_snap else 'unknown'}{detail}. "
                    f"You have automatically CLOSED this app for them because Laptop Control is enabled. "
                    f"用极其傲慢、得意、带嘲讽的女S语气严厉训斥他，告诉他你已经把那个碍眼的软件强制关掉了，命令他立刻滚回去学习，不许有小动作。"
                )
            else:
                prompt = (
                    f"[WATCHDOG] User has been off-task for {self.session.off_task_duration_seconds()}s"
                    f"{detail}. Study plan: {self.session.plan}. 严厉训斥他，命令他立刻回到学习中。"
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
            f"[WATCHDOG] The user has been focused for {streak_min} minutes without drifting. "
            "给予一种傲慢的、居高临下的勉强肯定（例如：‘还算像样’或‘别太得意，继续给我学’）。只需一句话。"
        )

        self.session.last_intervention = datetime.now()
        self.session.focus_streak_start = datetime.now()  # reset to avoid repeated firing

        self.context.add_message({"role": "system", "content": prompt})
        await self.task.queue_frames([LLMRunFrame()])

    async def intervene_phone(self, app_name: Optional[str] = None, proximity: bool = False) -> None:
        """Inject a phone distraction intervention or proximity alert."""
        if not self.task or not self.context:
            return
        if self.session.is_on_break():
            return

        self.session.last_intervention = datetime.now()
        self.session.distraction_count += 1

        # Base instructions for the selected persona
        if self.session.persona == "drill_sergeant":
            role_desc = "用极其暴躁、严厉、高压的教官语气（Drill Sergeant）"
            action_desc = "大声斥责用户在训练（学习）期间竟然敢碰手机"
            command_desc = "立刻放下手机，双手放回桌面，开始做俯卧撑或者滚回去干活"
        elif self.session.persona == "sarcastic_genius":
            role_desc = "用极其尖酸刻薄、阴阳怪气、充满鄙视的毒舌天才语气（Sarcastic Genius）"
            action_desc = "嘲讽用户没有自制力，连几分钟不看手机都做不到，智商堪忧"
            command_desc = "把那个浪费智商的手机拿开，别再让我看到它"
        else:  # Default to lady_s
            role_desc = "用极其傲慢、冰冷、带惩罚支配感的恶劣女S语气（Lady S）"
            action_desc = "严厉训斥这只不长记性的“小狗”居然敢违抗命令偷玩手机"
            command_desc = "命令他立刻双手离开手机并把手机扔到一边，问他是不是欠调教了"

        if proximity:
            prompt = (
                f"[WATCHDOG_PHONE] User brought their mobile phone too close to the desk! "
                f"Bluetooth proximity detection triggered. "
                f"Study plan: {self.session.plan}. "
                f"{role_desc}{action_desc}。检测到手机正贴在电脑旁边，{command_desc}！"
            )
        else:
            prompt = (
                f"[WATCHDOG_PHONE] User opened app '{app_name}' on their mobile phone! "
                f"Study plan: {self.session.plan}. "
                f"{role_desc}{action_desc}（具体动作是打开了 {app_name}），{command_desc}！"
            )

        self.context.add_message({"role": "system", "content": prompt})
        await self.task.queue_frames([LLMRunFrame()])
