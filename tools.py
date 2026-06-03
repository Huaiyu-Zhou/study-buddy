"""Tool schemas and Pipecat function-call handlers for the Study Buddy coach.

Pipecat registers each tool as an async handler via llm.register_function().
Handlers receive a FunctionCallParams object and return results via
params.result_callback().
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from pipecat.services.llm_service import FunctionCallParams

import config
from memory import StudyMemory
from session import Session

logger = logging.getLogger(__name__)

# Lazily initialised — None until first use
_memory_instance: StudyMemory | None = None


def _get_memory() -> StudyMemory | None:
    global _memory_instance
    if _memory_instance is None:
        try:
            _memory_instance = StudyMemory(palace_path=config.MEMPALACE_PALACE_PATH)
        except Exception as e:
            logger.warning("Failed to initialise MemPalace: %s", e)
            return None
    return _memory_instance


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "set_break",
            "description": "Pause the activity watchdog for a specified number of minutes. Use when the user says they are taking a break.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer", "description": "Length of the break in minutes."}
                },
                "required": ["minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "change_persona",
            "description": "Change your coaching persona for the rest of the session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "persona": {"type": "string", "description": "New persona description (e.g. 'strict coach', 'encouraging friend', 'drill sergeant')."}
                },
                "required": ["persona"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_wing",
            "description": "Load long-term memory for a specific subject or study domain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Subject or domain to load (e.g. 'calculus', 'biology')."}
                },
                "required": ["subject"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_plan",
            "description": "Update the user's study plan for the current session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "new_plan": {"type": "string", "description": "The new study plan description."}
                },
                "required": ["new_plan"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_session_summary",
            "description": "Return a summary of the current session — distractions, focus streak, study plan.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_session",
            "description": "End the study session. Produces a session summary, saves memory, and exits.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_app",
            "description": "Classify a process or web domain as 'study', 'distraction', or 'dual_use' based on user response.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The process name (e.g. 'draw.io') or domain name (e.g. 'youtube.com')."},
                    "is_domain": {"type": "boolean", "description": "True if target is a website domain, False if it is a desktop process."},
                    "status": {"type": "string", "enum": ["study", "distraction", "dual_use"], "description": "Whether this is allowed for study, blocked as a distraction, or dual-use (can be both)."},
                    "scope": {"type": "string", "enum": ["session", "permanent"], "description": "Whether this classification applies only to this session, or is permanently saved."}
                },
                "required": ["name", "is_domain", "status", "scope"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_classified_apps",
            "description": "Get lists of all current app and website classifications (study, distraction, and dual-use/can be both).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


def register_tools(llm, session: Session) -> None:
    """Register all tool handlers onto a Pipecat LLM service.

    Each handler is an async function that receives FunctionCallParams
    and sends results back via params.result_callback().
    """

    async def _on_set_break(params: FunctionCallParams):
        minutes = params.arguments["minutes"]
        session.break_end = datetime.now() + timedelta(minutes=minutes)
        await params.result_callback(f"Break started. I'll check back in {minutes} minute(s).")

    async def _on_change_persona(params: FunctionCallParams):
        session.persona = params.arguments["persona"]
        await params.result_callback(f"Persona updated to: {params.arguments['persona']}.")

    async def _on_load_wing(params: FunctionCallParams):
        subject = params.arguments["subject"]
        session.subject = subject
        mem = _get_memory()
        if mem is None:
            await params.result_callback(
                f"Memory wing loaded for: {subject}. (MemPalace unavailable — running without long-term memory.)"
            )
            return

        results = mem.search(f"study session {subject}", wing=subject, n_results=3)
        if not results:
            await params.result_callback(
                f"Memory wing loaded for: {subject}. No memories found yet — this will be your first recorded session."
            )
            return

        snippets = [r["text"][:200] for r in results]
        ctx = "\n".join(snippets)
        await params.result_callback(f"Memory wing loaded for: {subject}. Here's what I remember:\n{ctx}")

    async def _on_update_plan(params: FunctionCallParams):
        session.plan = params.arguments["new_plan"]
        session.off_task_start = None  # reset off-task timer — new plan context
        await params.result_callback(f"Study plan updated to: {params.arguments['new_plan']}.")

    async def _on_get_session_summary(params: FunctionCallParams):
        focus_min = session.focus_streak_seconds() // 60
        summary = (
            f"Session summary: {session.distraction_count} distraction(s) so far. "
            f"Current focus streak: {focus_min} minute(s). "
            f"Study plan: {session.plan}."
        )
        await params.result_callback(summary)

    async def _on_end_session(params: FunctionCallParams):
        session.end_requested = True

        # Persist conversation to MemPalace
        mem = _get_memory()
        if mem:
            try:
                mem.persist(session)
            except Exception as e:
                logger.warning("Failed to persist session to MemPalace: %s", e)

        focus_min = session.focus_streak_seconds() // 60
        summary = (
            f"Session ending. {session.distraction_count} distraction(s). "
            f"Focus streak: {focus_min} minute(s)."
        )
        await params.result_callback(summary)

    async def _on_classify_app(params: FunctionCallParams):
        name = params.arguments["name"]
        is_domain = params.arguments["is_domain"]
        status = params.arguments["status"]
        scope = params.arguments["scope"]
        
        name_lower = name.lower()
        
        if scope == "session":
            if status == "study":
                session.session_allowed_targets.add(name_lower)
                session.session_denied_targets.discard(name_lower)
            elif status == "distraction":
                session.session_denied_targets.add(name_lower)
                session.session_allowed_targets.discard(name_lower)
            elif status == "dual_use":
                session.session_allowed_targets.discard(name_lower)
                session.session_denied_targets.discard(name_lower)
            msg = f"Target {name} classified as {status} for the current session."
        else:
            import config
            config.add_dynamic_classification(name, is_domain, status)
            msg = f"Target {name} classified permanently as {status}."
            
        logger.info(msg)
        
        # If Laptop Control is active and it is classified as distraction, close it
        is_browser = name.lower() in {"chrome.exe", "msedge.exe", "brave.exe", "opera.exe", "firefox.exe", "safari.exe", "iexplore.exe"}
        if status == "distraction" and session.control_laptop and not is_browser:
            from watchdog import terminate_process
            terminated = terminate_process(pid=None, name=name)
            if terminated:
                msg += " I have terminated the distraction."
            else:
                msg += " (Pending termination request sent to client)."
        elif status == "distraction" and session.control_laptop and is_browser:
            msg += " (Browser target, skipped termination request to avoid closing all tabs)."
                
        await params.result_callback(msg)

    async def _on_get_classified_apps(params: FunctionCallParams):
        import config
        summary = (
            f"Classified Apps and Websites:\n"
            f"- Study/Allowed: processes: {list(config.KNOWN_STUDY_PROCESSES)}, websites: {list(config.KNOWN_STUDY_DOMAINS)}\n"
            f"- Distractions/Blocked: processes: {list(config.KNOWN_DISTRACTION_PROCESSES)}, websites: {list(config.KNOWN_DISTRACTION_DOMAINS)}\n"
            f"- Dual-Use/Can be both: processes: {list(config.KNOWN_DUAL_USE_PROCESSES)}, websites: {list(config.KNOWN_DUAL_USE_DOMAINS)}"
        )
        await params.result_callback(summary)

    # Register each handler with the LLM service
    llm.register_function("set_break", _on_set_break)
    llm.register_function("change_persona", _on_change_persona)
    llm.register_function("load_wing", _on_load_wing)
    llm.register_function("update_plan", _on_update_plan)
    llm.register_function("get_session_summary", _on_get_session_summary)
    llm.register_function("end_session", _on_end_session)
    llm.register_function("classify_app", _on_classify_app)
    llm.register_function("get_classified_apps", _on_get_classified_apps)
