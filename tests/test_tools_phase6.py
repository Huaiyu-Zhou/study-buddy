from unittest.mock import patch, MagicMock
from session import Session
from tools import handle_tool_call


class TestLoadWingIntegration:
    @patch("tools._get_memory")
    def test_load_wing_calls_mempalace_search(self, mock_get_mem):
        mock_mem = MagicMock()
        mock_mem.search.return_value = [
            {"text": "User struggles with derivatives.", "wing": "calculus", "similarity": 0.9}
        ]
        mock_get_mem.return_value = mock_mem

        session = Session(subject="calculus")
        result = handle_tool_call("load_wing", {"subject": "calculus"}, session)
        mock_mem.search.assert_called_once()
        assert "derivatives" in result

    @patch("tools._get_memory")
    def test_load_wing_no_results(self, mock_get_mem):
        mock_mem = MagicMock()
        mock_mem.search.return_value = []
        mock_get_mem.return_value = mock_mem

        session = Session(subject="biology")
        result = handle_tool_call("load_wing", {"subject": "biology"}, session)
        assert "No memories found" in result or "first recorded" in result

    @patch("tools._get_memory")
    def test_load_wing_graceful_when_no_memory(self, mock_get_mem):
        mock_get_mem.return_value = None
        session = Session()
        result = handle_tool_call("load_wing", {"subject": "calculus"}, session)
        assert isinstance(result, str)
        assert "unavailable" in result.lower() or "loaded" in result.lower()

    @patch("tools._get_memory")
    def test_load_wing_sets_session_subject(self, mock_get_mem):
        mock_mem = MagicMock()
        mock_mem.search.return_value = []
        mock_get_mem.return_value = mock_mem

        session = Session()
        assert session.subject == ""
        handle_tool_call("load_wing", {"subject": "physics"}, session)
        assert session.subject == "physics"
