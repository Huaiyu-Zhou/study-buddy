"""Phase 6 tests — MemPalace integration via load_wing tool (Pipecat handlers)."""

import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from session import Session
import tools


def _make_params(arguments: dict) -> MagicMock:
    params = MagicMock()
    params.arguments = arguments
    params.result_callback = AsyncMock()
    return params


def _get_handlers(session):
    mock_llm = MagicMock()
    handlers = {}
    mock_llm.register_function = lambda name, handler: handlers.__setitem__(name, handler)
    tools.register_tools(mock_llm, session)
    return handlers


class TestLoadWingIntegration:
    @patch("tools._get_memory")
    def test_load_wing_calls_mempalace_search(self, mock_get_mem):
        mock_mem = MagicMock()
        mock_mem.search.return_value = [
            {"text": "User struggles with derivatives.", "wing": "calculus", "similarity": 0.9}
        ]
        mock_get_mem.return_value = mock_mem

        session = Session(subject="calculus")
        handlers = _get_handlers(session)
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
        handlers = _get_handlers(session)
        params = _make_params({"subject": "biology"})
        asyncio.get_event_loop().run_until_complete(handlers["load_wing"](params))
        result_text = params.result_callback.call_args[0][0]
        assert "No memories found" in result_text or "first recorded" in result_text

    @patch("tools._get_memory")
    def test_load_wing_graceful_when_no_memory(self, mock_get_mem):
        mock_get_mem.return_value = None
        session = Session()
        handlers = _get_handlers(session)
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
        handlers = _get_handlers(session)
        params = _make_params({"subject": "physics"})
        asyncio.get_event_loop().run_until_complete(handlers["load_wing"](params))
        assert session.subject == "physics"
