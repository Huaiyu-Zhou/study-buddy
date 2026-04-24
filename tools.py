from datetime import datetime, timedelta
from typing import Any
from session import Session


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
]


def handle_tool_call(name: str, tool_input: dict[str, Any], session: Session) -> str:
    if name == "set_break":
        return _set_break(tool_input["minutes"], session)
    if name == "change_persona":
        return _change_persona(tool_input["persona"], session)
    if name == "load_wing":
        return _load_wing(tool_input["subject"], session)
    if name == "update_plan":
        return _update_plan(tool_input["new_plan"], session)
    if name == "get_session_summary":
        return _get_session_summary(session)
    if name == "end_session":
        return _end_session(session)
    raise ValueError(f"Unknown tool: {name}")


def _set_break(minutes: int, session: Session) -> str:
    session.break_end = datetime.now() + timedelta(minutes=minutes)
    return f"Break started. I'll check back in {minutes} minute(s)."


def _change_persona(persona: str, session: Session) -> str:
    session.persona = persona
    return f"Persona updated to: {persona}."


def _load_wing(subject: str, session: Session) -> str:
    # MemPalace integration comes in Phase 6 — stub for now
    return f"Memory wing loaded for: {subject}."


def _update_plan(new_plan: str, session: Session) -> str:
    session.plan = new_plan
    session.off_task_start = None  # reset off-task timer — new plan context
    return f"Study plan updated to: {new_plan}."


def _get_session_summary(session: Session) -> str:
    focus_min = session.focus_streak_seconds() // 60
    return (
        f"Session summary: {session.distraction_count} distraction(s) so far. "
        f"Current focus streak: {focus_min} minute(s). "
        f"Study plan: {session.plan}."
    )


def _end_session(session: Session) -> str:
    session.end_requested = True
    return _get_session_summary(session)
