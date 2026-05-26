"""FastAPI server for Study Buddy WebRTC mode.

Handles:
1. Serving the frontend HTML page
2. Creating Daily.co rooms and tokens on-demand
3. Spawning the Pipecat bot to join the room
4. Receiving activity snapshots from Windows host watchdog client
"""

import asyncio
import logging
import os
from datetime import datetime
from urllib.parse import urlparse
from typing import Optional

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from pipecat.transports.daily.utils import (
    DailyRESTHelper,
    DailyRoomParams,
    DailyRoomProperties,
)

import config
from session import Session, WindowSnapshot
from voice_pipeline import StudyBuddyVoicePipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("study_buddy_server")

app = FastAPI(title="Study Buddy Coach")

# Enable CORS for local testing stability
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state for the active session
active_pipeline: Optional[StudyBuddyVoicePipeline] = None
active_session: Optional[Session] = None

# Ensure templates directory exists
os.makedirs("templates", exist_ok=True)

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the coaching interface page."""
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.post("/connect")
async def connect(request: Request):
    """Create a Daily room, spawn the bot, and return connection info.
    Accepts optional plan, persona, and subject from the request.
    """
    global active_pipeline, active_session

    try:
        data = await request.json()
    except Exception:
        data = {}

    plan = data.get("plan", "review integrals")
    persona = data.get("persona", "lady_s")
    subject = data.get("subject", "calculus")

    # Clean up any existing active pipeline/session to avoid leaks
    if active_pipeline and active_pipeline.task:
        try:
            logger.info("Cleaning up existing session...")
            # We can let the runner stop or we just spawn the new one.
        except Exception:
            pass

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
                    exp=int(datetime.now().timestamp()) + 60 * 60 * 4,  # Room expires in 4 hours
                    enable_chat=False,
                )
            )
        )

        # 2. Create tokens for the bot and the client
        bot_token = await daily_helper.get_token(room.url, expiry_time=60 * 60 * 4)
        client_token = await daily_helper.get_token(room.url, expiry_time=60 * 60 * 4)

    # 3. Spawn the bot as an async background task
    asyncio.create_task(_run_bot(room.url, bot_token, plan, persona, subject))

    # 4. Return the room URL and client token to the frontend
    return JSONResponse(
        content={
            "room_url": room.url,
            "token": client_token,
        }
    )

@app.post("/activity")
async def update_activity(request: Request):
    """Receive activity updates from the win_watchdog client."""
    global active_pipeline, active_session
    if not active_pipeline or not active_session:
        return {"status": "no_active_session"}

    data = await request.json()
    process = data.get("process", "unknown")
    title = data.get("window_title", "")
    url = data.get("url")
    idle = data.get("idle_seconds", 0)

    # Reconstruct classification logic locally on the server (doesn't need win32gui)
    snapshot = WindowSnapshot(
        timestamp=datetime.now(),
        process=process,
        window_title=title,
        url=url,
        idle_seconds=idle,
        is_on_task=None,
    )
    
    # Classify
    is_on_task = None
    if snapshot.url:
        domain = urlparse(snapshot.url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        if any(domain == d or domain.endswith("." + d) for d in config.KNOWN_DISTRACTION_DOMAINS):
            is_on_task = False
        elif any(domain == d or domain.endswith("." + d) for d in config.KNOWN_STUDY_DOMAINS):
            is_on_task = True
    
    if is_on_task is None:
        if snapshot.process in config.KNOWN_DISTRACTION_PROCESSES:
            is_on_task = False
        elif snapshot.process in config.KNOWN_STUDY_PROCESSES:
            is_on_task = True
            
    snapshot.is_on_task = is_on_task

    active_session.snapshot_history.append(snapshot)
    if len(active_session.snapshot_history) > config.MAX_SNAPSHOT_HISTORY:
        active_session.snapshot_history.pop(0)

    logger.info(
        "watchdog update: process=%s title=%r url=%s idle=%ds on_task=%s",
        process, title, url, idle, snapshot.is_on_task,
    )

    # Process task state machine
    if idle < config.IDLE_THRESHOLD_SECONDS:
        if snapshot.is_on_task is False:
            if active_session.off_task_start is None:
                active_session.off_task_start = datetime.now()
            # Trigger intervention check
            asyncio.create_task(active_pipeline.maybe_intervene())
        elif snapshot.is_on_task is True:
            active_session.off_task_start = None
            if active_session.focus_streak_start is None:
                active_session.focus_streak_start = datetime.now()
            # Trigger positive reinforcement check
            asyncio.create_task(active_pipeline.maybe_reinforce())

    return {
        "status": "success",
        "distraction_count": active_session.distraction_count,
        "is_on_break": active_session.is_on_break(),
    }

@app.get("/session")
async def get_session_stats():
    """Get active session stats for dashboard display."""
    global active_session
    if not active_session:
        return {"active": False}
    
    duration = int((datetime.now() - active_session.session_start).total_seconds())
    return {
        "active": True,
        "plan": active_session.plan,
        "persona": active_session.persona,
        "subject": active_session.subject,
        "distraction_count": active_session.distraction_count,
        "duration_seconds": duration,
        "is_on_break": active_session.is_on_break(),
        "focus_streak_seconds": active_session.focus_streak_seconds(),
        "off_task_seconds": active_session.off_task_duration_seconds(),
    }

async def _run_bot(room_url: str, token: str, plan: str, persona: str, subject: str):
    """Run the Study Buddy pipeline as a bot inside a Daily room."""
    global active_pipeline, active_session
    active_session = Session(plan=plan, persona=persona, subject=subject)
    active_pipeline = StudyBuddyVoicePipeline(active_session, room_url=room_url, token=token)

    try:
        logger.info(f"Bot joining room: {room_url}")
        await active_pipeline.start()
    except Exception as e:
        logger.exception(f"Bot error: {e}")
    finally:
        logger.info("Bot session ended.")
        active_pipeline = None
        active_session = None

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
