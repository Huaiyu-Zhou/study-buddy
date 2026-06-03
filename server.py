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
from watchdog import classify_snapshot

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

import socket

def get_local_ip() -> str:
    """Detect the server's local network IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# Ensure templates directory exists
os.makedirs("templates", exist_ok=True)

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the coaching interface page."""
    with open("templates/index.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    
    local_ip = get_local_ip()
    html_content = html_content.replace("{{LOCAL_IP}}", local_ip)
    return HTMLResponse(content=html_content)

@app.post("/connect")
async def connect(request: Request):
    """Create a Daily room, spawn the bot, and return connection info.
    Accepts optional plan, persona, subject, and control_laptop from the request.
    """
    global active_pipeline, active_session

    try:
        data = await request.json()
    except Exception:
        data = {}

    plan = data.get("plan", "review integrals")
    persona = data.get("persona", "lady_s")
    subject = data.get("subject", "calculus")
    control_laptop = data.get("control_laptop", False)

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
    asyncio.create_task(_run_bot(room.url, bot_token, plan, persona, subject, control_laptop))

    # 4. Return the room URL and client token to the frontend
    return JSONResponse(
        content={
            "room_url": room.url,
            "token": client_token,
        }
    )

@app.api_route("/phone_activity", methods=["GET", "POST"])
async def phone_activity(request: Request):
    """Receive notifications when the user interacts with their mobile phone."""
    global active_pipeline, active_session
    if not active_pipeline or not active_session:
        return {"status": "no_active_session"}

    # Extract parameters from query string or JSON payload
    app_name = request.query_params.get("app", "Phone")
    event = request.query_params.get("event", "unlock")

    if request.method == "POST":
        try:
            data = await request.json()
            app_name = data.get("app", app_name)
            event = data.get("event", event)
        except Exception:
            pass

    logger.warning("Phone activity webhook received: app=%s, event=%s", app_name, event)

    # Enforce phone intervention cooldown
    since_last = active_session.seconds_since_last_intervention()
    if since_last is not None and since_last < config.PHONE_COOLDOWN_SECONDS:
        logger.info("Phone activity warning suppressed due to cooldown (%ds since last)", since_last)
        return {"status": "cooldown_active"}

    # Trigger verbal phone scolding
    asyncio.create_task(active_pipeline.intervene_phone(app_name=app_name))

    return {
        "status": "success",
        "distraction_count": active_session.distraction_count,
    }

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
    pid = data.get("pid")

    snapshot = WindowSnapshot(
        timestamp=datetime.now(),
        process=process,
        window_title=title,
        url=url,
        idle_seconds=idle,
        is_on_task=None,
        pid=pid,
    )
    
    # Classify using dynamic & session state
    snapshot.is_on_task = classify_snapshot(snapshot, active_session)

    active_session.snapshot_history.append(snapshot)
    if len(active_session.snapshot_history) > config.MAX_SNAPSHOT_HISTORY:
        active_session.snapshot_history.pop(0)

    logger.info(
        "watchdog update: process=%s title=%r url=%s idle=%ds on_task=%s",
        process, title, url, idle, snapshot.is_on_task,
    )

    action_payload = {}

    # Process task state machine and save stats to history manager
    if idle < config.IDLE_THRESHOLD_SECONDS:
        # Determine target name
        target = urlparse(snapshot.url).netloc.lower() if snapshot.url else snapshot.process
        if target.startswith("www."):
            target = target[4:]
        is_focus = (snapshot.is_on_task is True)
        
        try:
            import history_manager
            history_manager.record_activity(target, is_focus, config.WATCHDOG_INTERVAL_SECONDS)
        except Exception as e:
            logger.error(f"Failed to record activity in history_manager: {e}")

        if snapshot.is_on_task is None:
            # Query trigger logic for new/dual-use app
            target = urlparse(snapshot.url).netloc.lower() if snapshot.url else snapshot.process
            if target.startswith("www."):
                target = target[4:]
                
            if target and target not in active_session.queried_targets:
                active_session.queried_targets.add(target)
                logger.info("watchdog update: target '%s' requires classification. Triggering query.", target)
                asyncio.create_task(active_pipeline.maybe_intervene(force=True, query_target=target))
                
        elif snapshot.is_on_task is False:
            if active_session.off_task_start is None:
                active_session.off_task_start = datetime.now()
            
            if active_session.control_laptop:
                logger.warning("watchdog update: distracting process detected! Requiring client to close: %s", process)
                asyncio.create_task(active_pipeline.maybe_intervene(force=True))
                action_payload = {
                    "action": "close_process",
                    "target_pid": snapshot.pid,
                    "target_process": snapshot.process,
                }
            else:
                asyncio.create_task(active_pipeline.maybe_intervene(force=False))
                
        elif snapshot.is_on_task is True:
            active_session.off_task_start = None
            if active_session.focus_streak_start is None:
                active_session.focus_streak_start = datetime.now()
            asyncio.create_task(active_pipeline.maybe_reinforce())

    resp_content = {
        "status": "success",
        "distraction_count": active_session.distraction_count,
        "is_on_break": active_session.is_on_break(),
    }
    resp_content.update(action_payload)
    return resp_content

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

@app.get("/history")
async def get_history():
    """Retrieve persistent study history for the frontend calendar."""
    import history_manager
    return history_manager.load_history()

@app.get("/classifications")
async def get_classifications():
    """Retrieve all current classifications (study, distraction, and dual_use)."""
    return {
        "study": {
            "processes": sorted(list(config.KNOWN_STUDY_PROCESSES)),
            "domains": sorted(list(config.KNOWN_STUDY_DOMAINS))
        },
        "distraction": {
            "processes": sorted(list(config.KNOWN_DISTRACTION_PROCESSES)),
            "domains": sorted(list(config.KNOWN_DISTRACTION_DOMAINS))
        },
        "dual_use": {
            "processes": sorted(list(config.KNOWN_DUAL_USE_PROCESSES)),
            "domains": sorted(list(config.KNOWN_DUAL_USE_DOMAINS))
        }
    }

@app.post("/classify")
async def classify(request: Request):
    """Add or modify a dynamic classification."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid JSON body"})
        
    name = data.get("name")
    is_domain = data.get("is_domain")
    status = data.get("status")  # "study", "distraction", "dual_use"
    
    if not name or is_domain is None or not status:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Missing required fields (name, is_domain, status)"})
        
    config.add_dynamic_classification(name, is_domain, status)
    return {"status": "success"}

@app.post("/classify/delete")
async def delete_classification(request: Request):
    """Delete a classification rule."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid JSON body"})
        
    name = data.get("name")
    is_domain = data.get("is_domain")
    
    if not name or is_domain is None:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Missing required fields (name, is_domain)"})
        
    config.delete_dynamic_classification(name, is_domain)
    return {"status": "success"}

@app.post("/stop")
async def stop_session():
    """Stop the active study session and clean up state."""
    global active_pipeline, active_session
    logger.info("Stopping active session manually.")
    active_pipeline = None
    active_session = None
    return {"status": "success"}


async def _run_bot(room_url: str, token: str, plan: str, persona: str, subject: str, control_laptop: bool):
    """Run the Study Buddy pipeline as a bot inside a Daily room."""
    global active_pipeline, active_session
    active_session = Session(plan=plan, persona=persona, subject=subject, control_laptop=control_laptop)
    active_pipeline = StudyBuddyVoicePipeline(active_session, room_url=room_url, token=token)

    try:
        logger.info(f"Bot joining room: {room_url}")
        await active_pipeline.start()
    except Exception as e:
        logger.error(f"Bot error (Voice coach disabled, running local watchdog mode): {e}")
        # Keep active_session alive to allow local watchdog and stats tracking
        return
    finally:
        # Only clean up if the pipeline successfully completed its run loop
        if active_pipeline:
            logger.info("Bot session ended normally.")
            active_pipeline = None
            active_session = None

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)

