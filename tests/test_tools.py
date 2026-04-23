from datetime import datetime, timedelta
from session import Session
import tools


def _session(**kwargs) -> Session:
    s = Session(plan="calculus revision")
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


# --- Schema tests ---

def test_tool_schemas_is_a_list_of_six():
    assert isinstance(tools.TOOL_SCHEMAS, list)
    assert len(tools.TOOL_SCHEMAS) == 6


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
    }


# --- Handler tests ---

def test_set_break_sets_break_end_on_session():
    session = _session()
    result = tools.handle_tool_call("set_break", {"minutes": 5}, session)
    assert session.is_on_break() is True
    assert "5" in result


def test_change_persona_updates_session():
    session = _session()
    result = tools.handle_tool_call("change_persona", {"persona": "drill sergeant"}, session)
    assert session.persona == "drill sergeant"
    assert "drill sergeant" in result.lower()


def test_load_wing_returns_confirmation_string():
    session = _session()
    result = tools.handle_tool_call("load_wing", {"subject": "biology"}, session)
    assert "biology" in result.lower()


def test_update_plan_updates_session():
    session = _session()
    session.off_task_start = datetime.now() - timedelta(seconds=200)
    result = tools.handle_tool_call("update_plan", {"new_plan": "essay writing"}, session)
    assert session.plan == "essay writing"
    assert session.off_task_start is None  # reset after plan change
    assert "essay writing" in result.lower()


def test_get_session_summary_returns_string_with_distraction_count():
    session = _session()
    session.distraction_count = 3
    result = tools.handle_tool_call("get_session_summary", {}, session)
    assert "3" in result


def test_end_session_sets_end_requested():
    session = _session()
    result = tools.handle_tool_call("end_session", {}, session)
    assert session.end_requested is True
    assert isinstance(result, str)
    assert len(result) > 0


def test_handle_tool_call_raises_for_unknown_tool():
    session = _session()
    try:
        tools.handle_tool_call("nonexistent_tool", {}, session)
        assert False, "Expected ValueError"
    except ValueError:
        pass
