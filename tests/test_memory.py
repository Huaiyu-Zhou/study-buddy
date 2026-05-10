import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from memory import StudyMemory


@pytest.fixture
def tmp_palace(tmp_path):
    """Use a temporary directory as the palace path."""
    return str(tmp_path / "test_palace")


class TestStudyMemoryInit:
    def test_creates_instance(self, tmp_palace):
        mem = StudyMemory(palace_path=tmp_palace)
        assert mem is not None

    def test_stores_palace_path(self, tmp_palace):
        mem = StudyMemory(palace_path=tmp_palace)
        assert mem.palace_path == tmp_palace


class TestWakeUp:
    def test_wake_up_returns_string(self, tmp_palace):
        mem = StudyMemory(palace_path=tmp_palace)
        context = mem.wake_up(wing="calculus")
        assert isinstance(context, str)

    def test_wake_up_empty_palace_returns_string(self, tmp_palace):
        mem = StudyMemory(palace_path=tmp_palace)
        context = mem.wake_up(wing="calculus")
        # Even an empty palace returns default text (identity + instructions)
        assert isinstance(context, str)

    @patch("memory.MemoryStack")
    def test_wake_up_delegates_to_memory_stack(self, mock_stack_cls, tmp_palace):
        mock_stack = MagicMock()
        mock_stack.wake_up.return_value = "User struggles with integration by parts."
        mock_stack_cls.return_value = mock_stack

        mem = StudyMemory(palace_path=tmp_palace)
        context = mem.wake_up(wing="calculus")

        mock_stack.wake_up.assert_called_once_with(wing="calculus")
        assert context == "User struggles with integration by parts."


class TestSearch:
    @patch("memory.search_memories")
    def test_search_returns_results(self, mock_search, tmp_palace):
        mock_search.return_value = {
            "query": "integration",
            "filters": {"wing": "calculus"},
            "results": [
                {"text": "User asked about u-substitution.", "wing": "calculus", "room": "integrals", "similarity": 0.92}
            ],
        }
        mem = StudyMemory(palace_path=tmp_palace)
        results = mem.search("integration", wing="calculus")
        assert len(results) == 1
        assert "u-substitution" in results[0]["text"]

    @patch("memory.search_memories")
    def test_search_failure_returns_empty(self, mock_search, tmp_palace):
        mock_search.side_effect = Exception("DB error")
        mem = StudyMemory(palace_path=tmp_palace)
        results = mem.search("anything", wing="calculus")
        assert results == []


class TestPersist:
    def test_persist_builds_session_text(self, tmp_palace):
        from session import Session
        session = Session(
            plan="review integrals",
            persona="drill sergeant",
            subject="calculus",
            distraction_count=3,
            conversation_history=[
                {"role": "user", "content": "I keep getting distracted"},
                {"role": "assistant", "content": "Let's refocus on your integral practice."},
            ],
        )
        mem = StudyMemory(palace_path=tmp_palace)
        text = mem._build_session_text(session)
        assert "review integrals" in text
        assert "drill sergeant" in text
        assert "3 distraction" in text
        assert "I keep getting distracted" in text
        assert "Let's refocus" in text

    @patch("memory.subprocess")
    def test_persist_calls_mempalace_mine(self, mock_subprocess, tmp_palace):
        from session import Session
        session = Session(subject="calculus", plan="review integrals")
        mem = StudyMemory(palace_path=tmp_palace)
        mem.persist(session)
        mock_subprocess.run.assert_called_once()
        call_args = mock_subprocess.run.call_args
        cmd = call_args[0][0]
        assert "mempalace" in cmd[0]
        assert "mine" in cmd
