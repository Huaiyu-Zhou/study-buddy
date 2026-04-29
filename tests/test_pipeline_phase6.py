from unittest.mock import patch, MagicMock
from session import Session
from pipeline import CoachingPipeline


class TestSystemPromptWithMemory:
    def test_system_prompt_includes_memory_context(self):
        session = Session(plan="review integrals", subject="calculus")
        client = MagicMock()
        pipeline = CoachingPipeline(session=session, client=client)
        pipeline.memory_context = "User prefers encouragement over pressure for calculus."

        prompt = pipeline.build_system_prompt()
        assert "User prefers encouragement" in prompt

    def test_system_prompt_without_memory_context(self):
        session = Session(plan="review integrals")
        client = MagicMock()
        pipeline = CoachingPipeline(session=session, client=client)

        prompt = pipeline.build_system_prompt()
        assert "study coach" in prompt.lower()
        assert "Previous sessions:" not in prompt


class TestPipelineWakeUp:
    @patch("pipeline.StudyMemory")
    def test_load_memory_sets_context(self, mock_mem_cls):
        mock_mem = MagicMock()
        mock_mem.wake_up.return_value = "User drifts at the 40-minute mark."
        mock_mem_cls.return_value = mock_mem

        session = Session(subject="calculus")
        client = MagicMock()
        pipeline = CoachingPipeline(session=session, client=client)
        pipeline.load_memory()

        assert pipeline.memory_context == "User drifts at the 40-minute mark."

    @patch("pipeline.StudyMemory")
    def test_load_memory_empty_returns_empty(self, mock_mem_cls):
        mock_mem = MagicMock()
        mock_mem.wake_up.return_value = ""
        mock_mem_cls.return_value = mock_mem

        session = Session(subject="calculus")
        client = MagicMock()
        pipeline = CoachingPipeline(session=session, client=client)
        pipeline.load_memory()

        assert pipeline.memory_context == ""

    def test_load_memory_skips_when_no_subject(self):
        session = Session()  # no subject set
        client = MagicMock()
        pipeline = CoachingPipeline(session=session, client=client)
        pipeline.load_memory()

        assert pipeline.memory_context == ""
