# Study Buddy → WebRTC (Daily.co) 架构迁移方案

> **文档版本**: v1.0  
> **创建日期**: 2026-05-19  
> **目标**: 将语音流水线从本地 PyAudio 硬件驱动迁移至 Daily.co WebRTC 云端架构，
> 实现端到端响应延迟从 ~1.5s 降低至 ~0.8s。

---

## 一、当前架构 vs 目标架构

### 1.1 当前架构（本地 PyAudio 驱动）

```
┌─────────────────────────────────────────────────────────────┐
│                   你的 Windows 电脑                          │
│                                                             │
│  ┌──────────┐    ┌──────────────────────────────────────┐   │
│  │ 麦克风    │───▶│ PyAudio (LocalAudioInputTransport)   │   │
│  └──────────┘    └──────────────┬───────────────────────┘   │
│                                 │ PCM 音频                   │
│                                 ▼                            │
│                    ┌──── WebSocket (TCP) ────┐               │
│                    │  Deepgram 云端 STT      │               │
│                    └──────────┬──────────────┘               │
│                               │ 文本                         │
│                               ▼                              │
│                    ┌──── HTTPS (TCP) ────────┐               │
│                    │  OpenAI / DeepSeek LLM  │               │
│                    └──────────┬──────────────┘               │
│                               │ 流式文本                     │
│                               ▼                              │
│               ┌── ChineseSentenceAggregator ──┐              │
│               └──────────────┬────────────────┘              │
│                              │ 完整句子                      │
│                              ▼                               │
│                    ┌──── WebSocket (TCP) ────┐               │
│                    │  Fish Audio 云端 TTS    │               │
│                    └──────────┬──────────────┘               │
│                               │ PCM 音频                     │
│                               ▼                              │
│  ┌──────────┐    ┌──────────────────────────────────────┐   │
│  │ 扬声器    │◀──│ PyAudio (LocalAudioOutputTransport)  │   │
│  └──────────┘    └──────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Watchdog (win32gui + psutil，监控窗口切换)             │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**延迟瓶颈**: 音频数据在你的电脑与 3 个云端服务之间经历 6 次 TCP 网络往返 (~600ms)。

### 1.2 目标架构（Daily.co WebRTC）

```
┌─────────────────────────┐         ┌─────────────────────────────────┐
│    用户浏览器 (Client)    │         │   Python 后端服务 (你的电脑)      │
│                         │ WebRTC  │                                 │
│  ┌──────────┐           │◀═══════▶│  ┌─────────────────────────┐    │
│  │ 麦克风    │──▶ daily-js│  UDP   │  │ DailyTransport (Bot)    │    │
│  │ 扬声器    │◀── daily-js│        │  └──────────┬──────────────┘    │
│  └──────────┘           │         │             │ Pipecat Pipeline  │
│                         │         │             ▼                   │
│  ┌──────────────────┐   │         │  STT ──▶ LLM ──▶ TTS           │
│  │ "Start Coaching" │   │         │  (Deepgram) (OpenAI) (Fish)    │
│  │  按钮             │   │         │                                 │
│  └──────────────────┘   │         │  ┌─────────────────────────┐    │
│                         │         │  │ Watchdog (win32gui)     │    │
│                         │         │  └─────────────────────────┘    │
└─────────────────────────┘         └─────────────────────────────────┘
                   │
              Daily.co SFU
           (选择性转发单元,
            全球 PoP 节点)
```

**提速原理**:
- 音频传输使用 UDP 而非 TCP，丢包不阻塞。
- Daily.co 全球 PoP 节点确保最优路由。
- 浏览器原生 WebRTC 引擎（C++ 实现），硬件缓冲极低。

---

## 二、前提条件

### 2.1 注册 Daily.co 账号
1. 访问 https://dashboard.daily.co/
2. 免费注册（无需信用卡）
3. 在 Developers > API Keys 中获取你的 `DAILY_API_KEY`

### 2.2 安装新依赖
```bash
pip install "pipecat-ai[daily]" fastapi uvicorn aiohttp
```

解释:
| 依赖 | 用途 |
|------|------|
| `pipecat-ai[daily]` | 安装 Pipecat 的 Daily WebRTC 传输器 |
| `fastapi` | 轻量级 Web 框架，用于托管 `/connect` API 和前端页面 |
| `uvicorn` | ASGI 服务器，用于运行 FastAPI |
| `aiohttp` | 异步 HTTP 客户端，用于调用 Daily.co REST API 创建房间和 Token |

---

## 三、需要修改和新增的文件

### 3.1 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `.env` | 修改 | 添加 `DAILY_API_KEY` |
| `config.py` | 修改 | 读取 `DAILY_API_KEY`，添加 `DAILY_API_URL` |
| `voice_pipeline.py` | 修改 | 替换 Transport 层，接收 `room_url` + `token` 参数 |
| `main.py` | 保留 | 保留为本地 PyAudio 模式的入口（向后兼容） |
| `server.py` | **新增** | FastAPI 后端：创建房间、签发 Token、启动 Bot |
| `templates/index.html` | **新增** | 用户对话页面（浏览器 WebRTC 客户端） |
| `requirements.txt` | 修改 | 添加新依赖 |
| `session.py` | 不变 | 无需改动 |
| `tools.py` | 不变 | 无需改动 |
| `watchdog.py` | 不变 | 继续在本地运行，监控窗口切换 |
| `memory.py` | 不变 | 无需改动 |

---

## 四、各文件详细改动说明

### 4.1 `.env` — 添加 Daily.co 凭证

```diff
+ DAILY_API_KEY=your_daily_api_key_here
```

### 4.2 `config.py` — 读取 Daily.co 配置

```python
# Daily.co WebRTC (Phase 8 - WebRTC Transport)
DAILY_API_KEY: str = os.getenv("DAILY_API_KEY", "")
DAILY_API_URL: str = "https://api.daily.co/v1"
```

### 4.3 `voice_pipeline.py` — 重构 Transport 层

这是改动量最大的文件，但改动范围非常集中，只涉及 Transport 的初始化部分。

#### 需要修改的 import 区域（约 L28-L33）

```diff
- from pipecat.transports.local.audio import (
-     LocalAudioInputTransport,
-     LocalAudioOutputTransport,
-     LocalAudioTransport,
-     LocalAudioTransportParams,
- )
+ from pipecat.transports.daily.transport import DailyTransport, DailyParams
```

#### 需要修改的 `__init__` 方法签名

```diff
- def __init__(self, session: Session) -> None:
+ def __init__(self, session: Session, room_url: str = "", token: str = "") -> None:
      self.session = session
+     self.room_url = room_url
+     self.token = token
      self.task: Optional[PipelineTask] = None
      self.context: Optional[LLMContext] = None
      self.runner: Optional[PipelineRunner] = None
```

#### 需要修改的 `start()` 方法中 Transport 创建部分（约 L217-L242）

将整个 PyAudio 初始化和 `LocalAudioInputTransport` / `LocalAudioOutputTransport` 替换为：

```python
        # --- Transport (Daily.co WebRTC) ---
        transport = DailyTransport(
            room_url=self.room_url,
            token=self.token,
            bot_name="Study Buddy Coach",
            params=DailyParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_out_sample_rate=config.AUDIO_DEVICE_SAMPLE_RATE,
                vad_enabled=True,
                vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.3)),
            ),
        )
```

> **注意**: `DailyParams` 内置了 VAD 支持，所以 `vad_analyzer` 从
> `LLMUserAggregatorParams` 移入到 `DailyParams` 中。

#### 需要修改的 Pipeline wiring（约 L297-L306）

```diff
      pipeline = Pipeline([
-         transport_in,            # Mic audio frames
+         transport.input(),       # WebRTC audio in
          stt,                     # Audio → TranscriptionFrame
          user_aggregator,         # Collects text into LLM user turn
          llm,                     # LLM inference (streaming tokens)
          zh_aggregator,           # Buffer tokens → complete Chinese sentences
          tts,                     # Full sentence → audio (smooth playback)
-         transport_out,           # Audio → speakers
+         transport.output(),      # WebRTC audio out
          assistant_aggregator,    # Records assistant turn in context
      ])
```

#### 其余部分完全不变
以下逻辑 **100% 保留**，无需任何修改：
- `_build_system_prompt()` — 系统提示词构建
- `ChineseSentenceAggregator` — 中文断句聚合器
- `_strip_emoji()` — Emoji 过滤
- `maybe_intervene()` — Watchdog 介入逻辑
- `maybe_reinforce()` — 正面强化逻辑
- 所有 STT / LLM / TTS 服务配置
- 所有 Tool schemas 和 handlers

### 4.4 `server.py` — 全新的 FastAPI 后端入口

```python
"""FastAPI server for Study Buddy WebRTC mode.

Handles:
1. Serving the frontend HTML page
2. Creating Daily.co rooms and tokens on-demand
3. Spawning the Pipecat bot to join the room
"""

import asyncio
import logging
import os

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pipecat.transports.services.helpers.daily_rest import (
    DailyRESTHelper,
    DailyRoomParams,
    DailyRoomProperties,
)

import config
from session import Session
from voice_pipeline import StudyBuddyVoicePipeline
from watchdog import watchdog_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("study_buddy_server")

app = FastAPI(title="Study Buddy Coach")


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the coaching interface page."""
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.post("/connect")
async def connect():
    """Create a Daily room, spawn the bot, and return connection info."""

    # 1. Create a Daily room via REST API
    async with aiohttp.ClientSession() as http_session:
        daily_helper = DailyRESTHelper(
            daily_api_key=config.DAILY_API_KEY,
            daily_api_url=config.DAILY_API_URL,
            aiohttp_session=http_session,
        )

        room = await daily_helper.create_room(
            params=DailyRoomParams(
                properties=DailyRoomProperties(
                    exp=60 * 60 * 4,  # Room expires in 4 hours
                    enable_chat=False,
                )
            )
        )

        # 2. Create tokens for the bot and the client
        bot_token = await daily_helper.get_token(room.url, expiry_time=60 * 60 * 4)
        client_token = await daily_helper.get_token(room.url, expiry_time=60 * 60 * 4)

    # 3. Spawn the bot as an async background task
    asyncio.create_task(_run_bot(room.url, bot_token))

    # 4. Return the room URL and client token to the frontend
    return JSONResponse(
        content={
            "room_url": room.url,
            "token": client_token,
        }
    )


async def _run_bot(room_url: str, token: str):
    """Run the Study Buddy pipeline as a bot inside a Daily room."""
    session = Session()
    pipeline = StudyBuddyVoicePipeline(session, room_url=room_url, token=token)

    # Start the watchdog (monitors active windows)
    watchdog_task = asyncio.create_task(
        watchdog_loop(
            session,
            on_off_task=lambda snap, sess: pipeline.maybe_intervene(),
        )
    )

    try:
        logger.info(f"Bot joining room: {room_url}")
        await pipeline.start()
    except Exception as e:
        logger.exception(f"Bot error: {e}")
    finally:
        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass
        logger.info("Bot session ended.")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7860)
```

### 4.5 `templates/index.html` — 用户前端界面

这是一个精心设计的对话页面，用户在浏览器中打开它后：
1. 点击 **"开始监督 (Start Coaching)"** 按钮。
2. 浏览器请求麦克风权限。
3. 通过 WebRTC 直接与 Bot 建立超低延迟语音连接。

核心 JS 逻辑（使用 Daily.co 官方 SDK `daily-js`）：

```javascript
// 1. 请求后端创建房间
const resp = await fetch("/connect", { method: "POST" });
const { room_url, token } = await resp.json();

// 2. 创建 Daily call 对象并加入房间
const callFrame = window.DailyIframe.createCallObject();
await callFrame.join({ url: room_url, token: token });

// 3. 完成！音频通过 WebRTC UDP 自动双向流动
```

### 4.6 `requirements.txt` — 添加新依赖

```diff
  # Phase 4 & 5 — Pipecat pipeline (replaces manual audio plumbing)
- pipecat-ai[deepgram,fish,local,silero]>=0.0.54
+ pipecat-ai[daily,deepgram,fish,silero]>=0.0.54

+ # Phase 8 — WebRTC server
+ fastapi>=0.115.0
+ uvicorn>=0.34.0
+ aiohttp>=3.11.0
```

> 注意：移除了 `local`（PyAudio）extra，添加了 `daily` extra。

---

## 五、启动方式变化

### 之前（本地 PyAudio 模式）
```bash
python main.py
# 直接通过物理麦克风和扬声器对话
```

### 之后（WebRTC 模式）
```bash
python server.py
# 打开浏览器访问 http://localhost:7860
# 点击 "Start Coaching" 按钮开始对话
```

> `main.py` 保留不动，作为"本地离线模式"的后备入口。

---

## 六、不需要改动的部分（影响范围评估）

| 模块 | 是否需要改动 | 原因 |
|------|:---:|------|
| `session.py` | ❌ | 纯数据类，与传输层无关 |
| `tools.py` | ❌ | 工具定义和 handler，与传输层无关 |
| `watchdog.py` | ❌ | 继续使用 win32gui 监控窗口（与 WebRTC 无关） |
| `memory.py` | ❌ | MemPalace 记忆系统，与传输层无关 |
| `config.py` | ⚠️ 微改 | 仅增加 2 行读取 Daily.co Key |
| `tests/` | ⚠️ 可能 | 如果测试中 mock 了 Transport 相关类，需要更新 |

---

## 七、预期性能提升

### 延迟对比（从"用户说完话"到"听到第一个字"）

| 步骤 | PyAudio 本地模式 | WebRTC 模式 | 节省 |
|------|:---:|:---:|:---:|
| VAD 静音检测 | 300ms | 300ms | 0ms |
| 音频传输到 STT | ~100ms (TCP) | ~50ms (UDP) | **50ms** |
| STT 识别 | ~300ms | ~300ms | 0ms |
| STT 结果返回 | ~100ms (TCP) | ~50ms (UDP) | **50ms** |
| LLM 首字生成 | ~150ms | ~150ms | 0ms |
| LLM 结果传回 | ~100ms (TCP) | ~50ms (UDP) | **50ms** |
| 文本缓冲至首个标点 | ~200ms | ~200ms | 0ms |
| TTS 合成首包 | ~400ms | ~400ms | 0ms |
| TTS 音频传回 | ~100ms (TCP) | ~50ms (UDP) | **50ms** |
| 音频缓冲播放 | ~80ms (PyAudio) | ~30ms (WebRTC) | **50ms** |
| **总计** | **~1830ms** | **~1580ms** | **~250ms** |

> 注意：上表假设所有服务（STT/LLM/TTS）仍然通过本地 Python 进程的 WebSocket 调用。
> 如果未来将 Pipeline Agent 部署到与 STT/LLM/TTS 同机房的云端服务器，
> 还能再额外减少 ~400ms 的网络往返，做到 **~1.0s 以内**。

### 其他隐性收益
- **消除 TCP 队头阻塞**: UDP 丢包不阻塞后续帧，音频播放更流畅。
- **浏览器原生 AEC**: 自动回声消除，无需手动处理。
- **跨设备访问**: 手机、平板也能通过浏览器使用。
- **无需安装 PyAudio**: 移除了对 PortAudio C 库的依赖（安装经常出错的头号难题）。

---

## 八、风险与注意事项

1. **Watchdog 局限性**: `watchdog.py` 依赖 `win32gui`，只能在运行 `server.py` 的
   那台 Windows 电脑上监控窗口。如果将 server 部署到远程服务器，Watchdog 将无法工作。
   目前阶段建议继续在本地运行 `server.py`。

2. **Daily.co 免费额度**: 免费版每月提供 10,000 分钟的参与者分钟数，
   对于个人学习监督使用绰绰有余。

3. **PyAudio 后备模式**: `main.py` 保持不变，在没有网络或不想使用浏览器时，
   仍可以通过 `python main.py` 使用本地模式。

4. **虚拟环境中的 Fish Audio patch**: 之前我们修改了
   `venv/Lib/site-packages/pipecat/services/fish/tts.py` 中的 1024 字节限制。
   如果重新安装 pipecat（`pip install pipecat-ai[daily,...]`），这个 patch 会被覆盖，
   需要重新应用。

---

## 九、执行步骤清单

- [ ] 步骤 1: 注册 Daily.co 并获取 API Key
- [ ] 步骤 2: 将 `DAILY_API_KEY` 添加到 `.env`
- [ ] 步骤 3: 安装新依赖 `pip install "pipecat-ai[daily]" fastapi uvicorn aiohttp`
- [ ] 步骤 4: 更新 `config.py` (添加 2 行)
- [ ] 步骤 5: 重构 `voice_pipeline.py` (替换 Transport 层)
- [ ] 步骤 6: 创建 `server.py` (FastAPI 后端)
- [ ] 步骤 7: 创建 `templates/index.html` (前端页面)
- [ ] 步骤 8: 更新 `requirements.txt`
- [ ] 步骤 9: 运行 `python server.py` 并在浏览器中测试
- [ ] 步骤 10: 验证语音延迟和打断功能
