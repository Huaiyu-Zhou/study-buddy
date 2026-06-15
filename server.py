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
import socket
from datetime import datetime
from typing import Optional

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pipecat.frames.frames import EndFrame

from pipecat.transports.daily.utils import (
    DailyRESTHelper,
    DailyRoomParams,
    DailyRoomProperties,
)

import config
import history_manager
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

def get_local_ip() -> str:
    """Detect the server's local network IP address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
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
    Accepts optional plan, persona, subject, control_laptop, and ai_coaching from the request.
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
    ai_coaching = data.get("ai_coaching", True)

    # Clean up any existing active pipeline/session to avoid leaks
    if active_pipeline and active_pipeline.task:
        try:
            logger.info("Cleaning up existing session...")
            await active_pipeline.task.queue_frames([EndFrame()])
        except Exception:
            logger.warning("Failed to clean up previous session.")

    if ai_coaching:
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
        asyncio.create_task(_run_bot(room.url, bot_token, plan, persona, subject, control_laptop, ai_coaching))

        # 4. Return the room URL and client token to the frontend
        return JSONResponse(
            content={
                "room_url": room.url,
                "token": client_token,
                "ai_coaching": True,
            }
        )
    else:
        # AI Coaching is disabled (closed)
        active_session = Session(plan=plan, persona=persona, subject=subject, control_laptop=control_laptop, ai_coaching=False)
        active_pipeline = None
        logger.info("AI Coaching is disabled. Spawning watchdog-only session.")
        return JSONResponse(
            content={
                "room_url": "",
                "token": "",
                "ai_coaching": False,
            }
        )



@app.post("/activity")
async def update_activity(request: Request):
    """Receive activity updates from the win_watchdog client."""
    global active_pipeline, active_session
    if not active_session:
        return {"status": "no_active_session"}

    # Parse JSON payload from the watchdog client
    data = await request.json()
    
    # Construct a local WindowSnapshot object from the request parameters.
    # is_on_task starts as None, and will be resolved by local classifiers.
    snapshot = WindowSnapshot(
        timestamp=datetime.now(),
        process=data.get("process", "unknown"),
        window_title=data.get("window_title", ""),
        url=data.get("url"),
        idle_seconds=data.get("idle_seconds", 0),
        is_on_task=None,
        pid=data.get("pid"),
    )

    # Shared logic: classify target, update session state, and determine action flags.
    # Runs the same classification machine as the local direct watchdog client.
    from watchdog import process_snapshot, WatchdogResult
    result = process_snapshot(snapshot, active_session)

    logger.info(
        "watchdog update: process=%s title=%r url=%s idle=%ds on_task=%s",
        snapshot.process, snapshot.window_title, snapshot.url,
        snapshot.idle_seconds, snapshot.is_on_task,
    )

    # Record to history (server-only concern)
    if snapshot.idle_seconds < config.IDLE_THRESHOLD_SECONDS:
        try:
            history_manager.record_activity(
                result.target_name, result.is_focus, config.WATCHDOG_INTERVAL_SECONDS,
            )
        except Exception as e:
            logger.error("Failed to record activity: %s", e)

    # Build response action payload
    action_payload = {}

    if result.should_query:
        logger.info("watchdog update: target '%s' requires classification.", result.query_target)
        if active_pipeline:
            asyncio.create_task(active_pipeline.maybe_intervene(force=True, query_target=result.query_target))
    elif result.should_intervene:
        if result.should_close_process:
            logger.warning("watchdog update: distracting process! Requiring client to close: %s", snapshot.process)
            action_payload = {
                "action": "close_process",
                "target_pid": snapshot.pid,
                "target_process": snapshot.process,
            }
            active_session.closed_distractions.append({
                "timestamp": datetime.now().isoformat(),
                "target": snapshot.process
            })
        elif result.should_close_tab:
            logger.warning("watchdog update: distracting website on '%s'. Requiring client to close tab.", snapshot.process)
            action_payload = {
                "action": "close_tab",
                "target_process": snapshot.process,
            }
            active_session.closed_distractions.append({
                "timestamp": datetime.now().isoformat(),
                "target": snapshot.url or snapshot.window_title or "distracting website"
            })
        if active_pipeline:
            asyncio.create_task(active_pipeline.maybe_intervene(force=True))

    elif result.should_reinforce:
        if active_pipeline:
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
    return history_manager.load_history()

@app.get("/classifications")
async def get_classifications():
    """Retrieve all current classifications (study, distraction, and dual_use)."""
    study_processes = set(config.KNOWN_STUDY_PROCESSES)
    study_domains = set(config.KNOWN_STUDY_DOMAINS)
    distraction_processes = set(config.KNOWN_DISTRACTION_PROCESSES)
    distraction_domains = set(config.KNOWN_DISTRACTION_DOMAINS)
    dual_use_processes = set(config.KNOWN_DUAL_USE_PROCESSES)
    dual_use_domains = set(config.KNOWN_DUAL_USE_DOMAINS)

    if active_session:
        for target in active_session.session_allowed_targets:
            display_target = f"{target} (session only)"
            if "." in target and not target.endswith(".exe"):
                study_domains.add(display_target)
            else:
                study_processes.add(display_target)
        for target in active_session.session_denied_targets:
            display_target = f"{target} (session only)"
            if "." in target and not target.endswith(".exe"):
                distraction_domains.add(display_target)
            else:
                distraction_processes.add(display_target)

    return {
        "study": {
            "processes": sorted(study_processes),
            "domains": sorted(study_domains)
        },
        "distraction": {
            "processes": sorted(distraction_processes),
            "domains": sorted(distraction_domains)
        },
        "dual_use": {
            "processes": sorted(dual_use_processes),
            "domains": sorted(dual_use_domains)
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
        
    if name.endswith(" (session only)"):
        name = name[:-15]

    name_lower = name.lower()
    if is_domain:
        name_lower = config.strip_www(name_lower)

    config.add_dynamic_classification(name_lower, is_domain, status)
    
    if active_session:
        active_session.session_allowed_targets.discard(name_lower)
        active_session.session_denied_targets.discard(name_lower)
        
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
        
    if name.endswith(" (session only)"):
        name = name[:-15]

    name_lower = name.lower()
    if is_domain:
        name_lower = config.strip_www(name_lower)

    config.delete_dynamic_classification(name_lower, is_domain)
    
    if active_session:
        active_session.session_allowed_targets.discard(name_lower)
        active_session.session_denied_targets.discard(name_lower)
        
    return {"status": "success"}

@app.post("/stop")
async def stop_session():
    """Stop the active study session and clean up state."""
    global active_pipeline, active_session
    logger.info("Stopping active session manually.")
    if active_pipeline:
        # Save companion emotional state before cleanup
        try:
            await active_pipeline.save_companion_state()
        except Exception:
            logger.warning("Failed to save companion state on stop.")
        if active_pipeline.task:
            try:
                await active_pipeline.task.queue_frames([EndFrame()])
            except Exception:
                logger.warning("Failed to gracefully stop pipeline.")
    active_pipeline = None
    active_session = None
    return {"status": "success"}

@app.post("/congratulate")
async def congratulate():
    """Trigger a congratulatory coach interruption when study goals are complete."""
    global active_pipeline
    if active_pipeline:
        logger.info("Session complete: triggering congrats speech.")
        asyncio.create_task(active_pipeline.trigger_congrats())
        return {"status": "success"}
    return {"status": "no_active_session"}



async def _run_bot(room_url: str, token: str, plan: str, persona: str, subject: str, control_laptop: bool, ai_coaching: bool):
    """Run the Study Buddy pipeline as a bot inside a Daily room."""
    global active_pipeline, active_session
    active_session = Session(plan=plan, persona=persona, subject=subject, control_laptop=control_laptop, ai_coaching=ai_coaching)
    active_pipeline = StudyBuddyVoicePipeline(active_session, room_url=room_url, token=token)

    try:
        logger.info(f"Bot joining room: {room_url}")
        await active_pipeline.start()
        logger.info("Bot session ended normally.")
        # Save companion state before cleanup
        try:
            await active_pipeline.save_companion_state()
        except Exception:
            logger.warning("Failed to save companion state on session end.")
        active_pipeline = None
        active_session = None
    except Exception as e:
        logger.error(f"Bot error (Voice coach disabled, running local watchdog mode): {e}")
        # Save companion state even on error
        if active_pipeline:
            try:
                await active_pipeline.save_companion_state()
            except Exception:
                pass
        # Keep active_session alive to allow local watchdog and stats tracking
        active_pipeline = None

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)

