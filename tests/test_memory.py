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
