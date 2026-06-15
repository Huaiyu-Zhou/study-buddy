import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from memory import (
    IntradayCache,
    filter_conversational_messages,
    consolidate_day_history,
    persist_consolidated_summary
)


@pytest.fixture
def temp_cache_file(tmp_path):
    """Fixture to provide a path to a temporary cache file."""
    return str(tmp_path / "test_today_history.json")


class TestIntradayCache:
    def test_default_load(self, temp_cache_file):
        cache = IntradayCache(temp_cache_file)
        data = cache.load()
        assert data["date"] == datetime.now().strftime("%Y-%m-%d")
        assert data["messages"] == []
        assert data["closed_distractions"] == []

    def test_save_and_load(self, temp_cache_file):
        cache = IntradayCache(temp_cache_file)
        test_messages = [{"role": "user", "content": "Hello world"}]
        test_distractions = [{"timestamp": "2026-06-12T15:00:00", "target": "steam.exe"}]

        cache.save(test_messages, test_distractions)

        loaded = cache.load()
        assert loaded["date"] == datetime.now().strftime("%Y-%m-%d")
        assert len(loaded["messages"]) == 1
        assert loaded["messages"][0]["content"] == "Hello world"
        assert len(loaded["closed_distractions"]) == 1
        assert loaded["closed_distractions"][0]["target"] == "steam.exe"

    def test_clear(self, temp_cache_file):
        cache = IntradayCache(temp_cache_file)
        cache.save([{"role": "user", "content": "hi"}], [])
        assert os.path.exists(temp_cache_file)

        cache.clear()
        assert not os.path.exists(temp_cache_file)


class TestFilterConversationalMessages:
    def test_filters_system_and_tool_messages(self):
        raw_msgs = [
            {"role": "system", "content": "System prompt info"},
            {"role": "user", "content": "Hi companion!"},
            {"role": "assistant", "content": "Hi user!", "tool_calls": [{"id": "1", "type": "function"}]},
            {"role": "tool", "content": "Tool output response"},
            {"role": "assistant", "content": "I looked that up for you."},
        ]

        clean_msgs = filter_conversational_messages(raw_msgs)

        assert len(clean_msgs) == 2
        # Only keeping simple user and assistant messages
        assert clean_msgs[0] == {"role": "user", "content": "Hi companion!"}
        assert clean_msgs[1] == {"role": "assistant", "content": "I looked that up for you."}


class TestConsolidateDayHistory:
    @patch("memory.persist_consolidated_summary")
    @patch("openai.OpenAI")
    @patch("history_manager.load_history")
    @patch("memory.IntradayCache")
    def test_consolidate_logic(self, mock_cache_cls, mock_load_history, mock_openai_cls, mock_persist_summary):
        # 1. Setup mock intraday cache
        mock_cache = MagicMock()
        mock_cache.load.return_value = {
            "date": "2026-06-11",
            "messages": [
                {"role": "user", "content": "I want to study math"},
                {"role": "assistant", "content": "Sure, let's study math!"}
            ],
            "closed_distractions": [
                {"timestamp": "2026-06-11T12:00:00", "target": "game.exe"}
            ]
        }
        mock_cache_cls.return_value = mock_cache

        # 2. Setup mock study_history stats
        mock_load_history.return_value = {
            "2026-06-11": {
                "total_focus_seconds": 3600,
                "total_session_seconds": 4000,
                "apps": {"vs code": 3000, "chrome.exe": 600}
            }
        }

        # 3. Setup mock OpenAI API response
        mock_openai_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Yesterday was a great day of focusing on algebra. Hugs!"
        mock_openai_client.chat.completions.create.return_value.choices = [mock_choice]
        mock_openai_cls.return_value = mock_openai_client

        # 4. Trigger consolidation
        consolidate_day_history()

        # 5. Verify the daily stats lookups and LLM calls
        mock_load_history.assert_called_once()
        mock_openai_cls.assert_called_once()
        mock_persist_summary.assert_called_once_with(
            "Yesterday was a great day of focusing on algebra. Hugs!", "2026-06-11"
        )
