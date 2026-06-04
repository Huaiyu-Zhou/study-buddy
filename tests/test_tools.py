"""Tests for tools.py — Pipecat-based function call handlers.

Since handlers are now async and use FunctionCallParams, we test them
by calling register_tools() on a mock LLM service, then invoking the
registered handlers directly.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

from session import Session
import tools


def _session(**kwargs) -> Session:
    s = Session(plan="calculus revision")
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


def _make_params(arguments: dict) -> MagicMock:
    """Create a mock FunctionCallParams with an async result_callback."""
    params = MagicMock()
    params.arguments = arguments
    params.result_callback = AsyncMock()
    return params


def _get_registered_handlers(session: Session) -> dict:
    """Register tools on a mock LLM and capture the handler map."""
    mock_llm = MagicMock()
    handlers = {}

    def capture_register(name, handler):
        handlers[name] = handler

    mock_llm.register_function = capture_register
    tools.register_tools(mock_llm, session)
    return handlers


# --- Schema tests ---

def test_tool_schemas_is_a_list_of_nine():
    assert isinstance(tools.TOOL_SCHEMAS, list)
    assert len(tools.TOOL_SCHEMAS) == 9


def test_all_schemas_have_openai_format():
    for schema in tools.TOOL_SCHEMAS:
        assert schema["type"] == "function"
        assert "function" in schema
        assert "name" in schema["function"]
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]


def test_schema_names_are_correct():
    names = {s["function"]["name"] for s in tools.TOOL_SCHEMAS}
    assert names == {
        "set_break", "change_persona", "load_wing",
        "update_plan", "get_session_summary", "end_session",
        "classify_app", "delete_classification", "get_classified_apps",
    }


# --- Handler tests ---

def test_set_break_sets_break_end_on_session():
    session = _session()
    handlers = _get_registered_handlers(session)
    params = _make_params({"minutes": 5})
    asyncio.get_event_loop().run_until_complete(handlers["set_break"](params))
    assert session.is_on_break() is True
    result_text = params.result_callback.call_args[0][0]
    assert "5" in result_text


def test_change_persona_updates_session():
    session = _session()
    handlers = _get_registered_handlers(session)
    params = _make_params({"persona": "drill sergeant"})
    asyncio.get_event_loop().run_until_complete(handlers["change_persona"](params))
    assert session.persona == "drill sergeant"
    result_text = params.result_callback.call_args[0][0]
    assert "drill sergeant" in result_text.lower()


def test_update_plan_updates_session():
    session = _session()
    session.off_task_start = datetime.now() - timedelta(seconds=200)
    handlers = _get_registered_handlers(session)
    params = _make_params({"new_plan": "essay writing"})
    asyncio.get_event_loop().run_until_complete(handlers["update_plan"](params))
    assert session.plan == "essay writing"
    assert session.off_task_start is None  # reset after plan change
    result_text = params.result_callback.call_args[0][0]
    assert "essay writing" in result_text.lower()


def test_get_session_summary_returns_string_with_distraction_count():
    session = _session()
    session.distraction_count = 3
    handlers = _get_registered_handlers(session)
    params = _make_params({})
    asyncio.get_event_loop().run_until_complete(handlers["get_session_summary"](params))
    result_text = params.result_callback.call_args[0][0]
    assert "3" in result_text


def test_end_session_sets_end_requested():
    session = _session()
    handlers = _get_registered_handlers(session)
    params = _make_params({})
    asyncio.get_event_loop().run_until_complete(handlers["end_session"](params))
    assert session.end_requested is True
    result_text = params.result_callback.call_args[0][0]
    assert len(result_text) > 0


def test_register_tools_registers_all_nine():
    session = _session()
    mock_llm = MagicMock()
    registered = []
    mock_llm.register_function = lambda name, handler: registered.append(name)
    tools.register_tools(mock_llm, session)
    assert set(registered) == {
        "set_break", "change_persona", "load_wing",
        "update_plan", "get_session_summary", "end_session",
        "classify_app", "delete_classification", "get_classified_apps",
    }

def test_delete_classification_session_removes_from_session():
    session = _session()
    session.session_allowed_targets.add("classroom.google.com")
    handlers = _get_registered_handlers(session)
    params = _make_params({"name": "classroom.google.com", "is_domain": True, "scope": "session"})
    asyncio.get_event_loop().run_until_complete(handlers["delete_classification"](params))
    assert "classroom.google.com" not in session.session_allowed_targets
    result_text = params.result_callback.call_args[0][0]
    assert "removed" in result_text

@patch("config.delete_dynamic_classification")
def test_delete_classification_permanent_removes_permanently(mock_delete):
    session = _session()
    session.session_allowed_targets.add("classroom.google.com")
    handlers = _get_registered_handlers(session)
    params = _make_params({"name": "classroom.google.com", "is_domain": True, "scope": "permanent"})
    asyncio.get_event_loop().run_until_complete(handlers["delete_classification"](params))
    assert "classroom.google.com" not in session.session_allowed_targets
    mock_delete.assert_called_once_with("classroom.google.com", True)
    result_text = params.result_callback.call_args[0][0]
    assert "deleted permanently" in result_text

def test_get_classified_apps_returns_list_summary():
    session = _session()
    handlers = _get_registered_handlers(session)
    params = _make_params({})
    asyncio.get_event_loop().run_until_complete(handlers["get_classified_apps"](params))
    result_text = params.result_callback.call_args[0][0]
    assert isinstance(result_text, str)
    assert "Classified Apps and Websites" in result_text
    assert "Study/Allowed" in result_text


# --- Phase 6 additions ---

from unittest.mock import patch

class TestLoadWingIntegration:
    @patch("tools._get_memory")
    def test_load_wing_calls_mempalace_search(self, mock_get_mem):
        mock_mem = MagicMock()
        mock_mem.search.return_value = [
            {"text": "User struggles with derivatives.", "wing": "calculus", "similarity": 0.9}
        ]
        mock_get_mem.return_value = mock_mem

        session = Session(subject="calculus")
        handlers = _get_registered_handlers(session)
        params = _make_params({"subject": "calculus"})
        asyncio.get_event_loop().run_until_complete(handlers["load_wing"](params))
        mock_mem.search.assert_called_once()
        result_text = params.result_callback.call_args[0][0]
        assert "derivatives" in result_text

    @patch("tools._get_memory")
    def test_load_wing_no_results(self, mock_get_mem):
        mock_mem = MagicMock()
        mock_mem.search.return_value = []
        mock_get_mem.return_value = mock_mem

        session = Session(subject="biology")
        handlers = _get_registered_handlers(session)
        params = _make_params({"subject": "biology"})
        asyncio.get_event_loop().run_until_complete(handlers["load_wing"](params))
        result_text = params.result_callback.call_args[0][0]
        assert "No memories found" in result_text or "first recorded" in result_text

    @patch("tools._get_memory")
    def test_load_wing_graceful_when_no_memory(self, mock_get_mem):
        mock_get_mem.return_value = None
        session = Session()
        handlers = _get_registered_handlers(session)
        params = _make_params({"subject": "calculus"})
        asyncio.get_event_loop().run_until_complete(handlers["load_wing"](params))
        result_text = params.result_callback.call_args[0][0]
        assert isinstance(result_text, str)
        assert "unavailable" in result_text.lower() or "loaded" in result_text.lower()

    @patch("tools._get_memory")
    def test_load_wing_sets_session_subject(self, mock_get_mem):
        mock_mem = MagicMock()
        mock_mem.search.return_value = []
        mock_get_mem.return_value = mock_mem

        session = Session()
        assert session.subject == ""
        handlers = _get_registered_handlers(session)
        params = _make_params({"subject": "physics"})
        asyncio.get_event_loop().run_until_complete(handlers["load_wing"](params))
        assert session.subject == "physics"
