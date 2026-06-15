"""Memory systems for the Study Buddy companion.

Contains:
- CoreMemory: Persistent relationship state (core_memory.json)
- StudyMemory: MemPalace wrapper for long-term session memory
"""

import json
import logging
import os
import subprocess
import tempfile
from datetime import datetime
from typing import Optional

from mempalace.layers import MemoryStack
from mempalace.searcher import search_memories
import config

logger = logging.getLogger(__name__)

CORE_MEMORY_PATH = "core_memory.json"
TODAY_HISTORY_PATH = "today_history.json"


class IntradayCache:
    """Manages the cache for today's raw conversation history and closed distractions.
    Designed to carry over context across multiple sessions on the same calendar day.
    """
    def __init__(self, path: str = TODAY_HISTORY_PATH) -> None:
        self.path = path

    def load(self) -> dict:
        """Load today's cached history. Returns a dict with 'date', 'messages', and 'closed_distractions'."""
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Failed to load intraday cache: %s", e)
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "messages": [],
            "closed_distractions": []
        }

    def save(self, messages: list[dict], closed_distractions: list[dict]) -> None:
        """Save the conversation history and closed distractions to the cache."""
        try:
            data = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "messages": messages,
                "closed_distractions": closed_distractions
            }
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Failed to save intraday cache: %s", e)

    def clear(self) -> None:
        """Clear/delete the intraday cache file."""
        if os.path.exists(self.path):
            try:
                os.remove(self.path)
            except Exception as e:
                logger.error("Failed to clear intraday cache: %s", e)


def filter_conversational_messages(messages: list[dict]) -> list[dict]:
    """Filters a list of messages to keep only clean conversational user/assistant turns.
    Removes system prompts, tool calls, and tool response messages to prevent formatting errors.
    """
    clean_msgs = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if role == "user" and content:
            clean_msgs.append({"role": "user", "content": content})
        elif role == "assistant" and content and not msg.get("tool_calls"):
            clean_msgs.append({"role": "assistant", "content": content})
    return clean_msgs


def persist_consolidated_summary(text: str, date_str: str) -> None:
    """Write the consolidated daily summary text to MemPalace."""
    import sys
    import shutil
    tmp_dir = None
    try:
        # Create a unique temporary directory to avoid conflicts during concurrent runs
        tmp_dir = tempfile.mkdtemp(prefix="studybuddy_consolidated_")
        tmp_path = os.path.join(tmp_dir, f"daily_consolidated_{date_str}.md")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(text)

        # Run the MemPalace CLI tool as a subprocess to index the generated markdown file
        cmd = [sys.executable, "-m", "mempalace", "mine", tmp_dir, "--wing", "general"]
        subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        logger.info("Consolidated daily summary for %s persisted to MemPalace wing 'general'", date_str)
    except Exception as e:
        logger.warning("Failed to persist consolidated summary to MemPalace: %s", e)
    finally:
        if tmp_dir:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except OSError:
                pass


def consolidate_day_history() -> None:
    """Summarize today's cached sessions and write a single daily summary to MemPalace."""
    cache = IntradayCache()
    cached_data = cache.load()
    messages = cached_data.get("messages", [])
    closed_distractions = cached_data.get("closed_distractions", [])
    cached_date = cached_data.get("date")

    if not messages and not closed_distractions:
        logger.info("No intraday cache to consolidate.")
        return

    logger.info("Consolidating yesterday's intraday cache (%s) into MemPalace...", cached_date)

    # 1. Fetch study statistics for that date from study_history.json
    try:
        from history_manager import load_history
        history = load_history()
        day_stats = history.get(cached_date, {})
    except Exception as e:
        logger.warning("Could not load study stats during consolidation: %s", e)
        day_stats = {}

    # 2. Build the text input for the summarizer
    focus_seconds = day_stats.get("total_focus_seconds", 0)
    session_seconds = day_stats.get("total_session_seconds", 0)
    apps = day_stats.get("apps", {})

    focus_min = focus_seconds // 60
    session_min = session_seconds // 60

    stats_str = f"Date: {cached_date}\n"
    stats_str += f"Total session duration: {session_min} minutes\n"
    stats_str += f"Total focus duration: {focus_min} minutes\n"
    stats_str += "App/website usage:\n"
    for app, secs in apps.items():
        stats_str += f"  - {app}: {secs // 60} minutes\n"

    stats_str += "\nClosed Distractions:\n"
    if closed_distractions:
        for dist in closed_distractions:
            ts = dist.get("timestamp", "")
            target = dist.get("target", "")
            stats_str += f"  - [{ts}] {target}\n"
    else:
        stats_str += "  - None\n"

    conversation_str = "\nConversation:\n"
    clean_messages = filter_conversational_messages(messages)
    for msg in clean_messages:
        role = msg.get("role", "").capitalize()
        content = msg.get("content", "")
        conversation_str += f"{role}: {content}\n"

    prompt = (
        "You are the summarization engine for Study Buddy companion AI. "
        "Your task is to write a warm, emotional, and relational summary of the day's interactions to be stored in the long-term Memory Palace. "
        "The summary should capture the user's progress, what subjects they studied, how focused they were, what apps/websites they spent time on, "
        "what distractions were automatically closed by the companion, and the conversational/emotional arc of the day.\n\n"
        "Do NOT write verbatim transcripts. Write a concise, 2-3 paragraph journal-style entry from the perspective of the companion. "
        "Keep it personal and warm.\n\n"
        f"--- Day Statistics ---\n{stats_str}\n"
        f"--- Conversations ---\n{conversation_str}\n"
    )

    summary_text = ""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=config.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a warm, helpful summary writer for the companion's Memory Palace."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=800
        )
        summary_text = response.choices[0].message.content
    except Exception as e:
        logger.error("Failed to generate daily summary from LLM: %s", e)
        # Fallback to simple text assembly
        summary_text = f"=== Daily Consolidated Summary ({cached_date}) ===\n"
        summary_text += f"Focus time: {focus_min}m out of {session_min}m total.\n"
        if closed_distractions:
            summary_text += f"Closed distractions: {', '.join(set(d.get('target', '') for d in closed_distractions))}\n"
        summary_text += f"Conversation carried {len(clean_messages)} turns."

    # 3. Persist the summary to MemPalace
    persist_consolidated_summary(summary_text, cached_date)

DEFAULT_CORE_MEMORY = {
    "student": {
        "name": "",
        "personal_details": "",
        "emotional_patterns": "",
        "likes_and_dislikes": "",
        "life_context": "",
        "current_mood_guess": "",
    },
    "relationship": {
        "our_story": "",
        "shared_memories": "",
        "inside_jokes": "",
        "how_i_feel_about_them": "Just getting to know each other. Curious and warm.",
    },
    "companion_notes": "",
}


class CoreMemory:
    """Persistent relationship memory — the companion's understanding of the user
    and the relationship. Loaded at session start, updated mid-conversation via
    LLM tool calls.

    Stored as a flat JSON file (core_memory.json). Designed to stay small
    (~500 tokens) so it can be injected into the system prompt every turn.
    """

    def __init__(self, path: str = CORE_MEMORY_PATH) -> None:
        self.path = path
        self._data: dict = self._load()

    def _load(self) -> dict:
        """Load core memory from disk, or create defaults if missing."""
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Failed to load core memory, using defaults: %s", e)
        return json.loads(json.dumps(DEFAULT_CORE_MEMORY))  # deep copy

    def save(self) -> None:
        """Persist core memory to disk."""
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("Failed to save core memory: %s", e)

    def update(self, section: str, field: str, value: str) -> str:
        """Update a specific field in core memory.

        Args:
            section: 'student', 'relationship', or 'companion_notes'
            field: The field name within the section (e.g., 'name', 'personal_details')
            value: The new value to set

        Returns:
            Confirmation message string.
        """
        if section == "companion_notes":
            self._data["companion_notes"] = value
            self.save()
            return f"Companion notes updated."

        if section not in self._data:
            return f"Unknown section: {section}. Use 'student', 'relationship', or 'companion_notes'."

        if not isinstance(self._data[section], dict):
            return f"Section '{section}' is not a structured section."

        if field not in self._data[section]:
            return f"Unknown field '{field}' in section '{section}'. Available: {list(self._data[section].keys())}"

        old_value = self._data[section][field]
        # Append to existing value rather than overwrite (relationship grows)
        if old_value and value not in old_value:
            self._data[section][field] = f"{old_value} {value}"
        else:
            self._data[section][field] = value

        self.save()
        return f"Remembered: {section}.{field} updated."

    def get_context_block(self) -> str:
        """Generate a text block for injection into the system prompt.

        Returns the core memory formatted as natural text the companion
        can reference during conversation.
        """
        lines = ["[YOUR MEMORY OF THIS PERSON AND YOUR RELATIONSHIP]"]

        student = self._data.get("student", {})
        if student.get("name"):
            lines.append(f"Their name: {student['name']}")
        if student.get("personal_details"):
            lines.append(f"What you know about them: {student['personal_details']}")
        if student.get("emotional_patterns"):
            lines.append(f"Their emotional patterns: {student['emotional_patterns']}")
        if student.get("likes_and_dislikes"):
            lines.append(f"Likes/dislikes: {student['likes_and_dislikes']}")
        if student.get("life_context"):
            lines.append(f"What's going on in their life: {student['life_context']}")
        if student.get("current_mood_guess"):
            lines.append(f"How they seemed last time: {student['current_mood_guess']}")

        relationship = self._data.get("relationship", {})
        if relationship.get("our_story"):
            lines.append(f"Your story together: {relationship['our_story']}")
        if relationship.get("shared_memories"):
            lines.append(f"Shared memories: {relationship['shared_memories']}")
        if relationship.get("inside_jokes"):
            lines.append(f"Inside jokes: {relationship['inside_jokes']}")
        if relationship.get("how_i_feel_about_them"):
            lines.append(f"How you feel about them: {relationship['how_i_feel_about_them']}")

        notes = self._data.get("companion_notes", "")
        if notes:
            lines.append(f"Your private notes: {notes}")

        if len(lines) == 1:
            lines.append("You don't know much about them yet. Be curious and get to know them!")

        return "\n".join(lines)

    def search(self, query: str) -> str:
        """Simple keyword search across all core memory fields.

        Returns matching content or a 'nothing found' message.
        """
        query_lower = query.lower()
        matches = []

        for section_name, section in self._data.items():
            if isinstance(section, dict):
                for field_name, value in section.items():
                    if value and query_lower in value.lower():
                        matches.append(f"{section_name}.{field_name}: {value}")
            elif isinstance(section, str) and section and query_lower in section.lower():
                matches.append(f"{section_name}: {section}")

        if matches:
            return "Found in memory:\n" + "\n".join(matches)
        return f"Nothing found in memory about '{query}'."


class StudyMemory:
    """Manages the MemPalace integration: wake-up, search, and persist."""

    def __init__(self, palace_path: Optional[str] = None) -> None:
        self.palace_path = palace_path or ""
        self._stack: Optional[MemoryStack] = None

    def _get_stack(self) -> MemoryStack:
        """Lazily initialise the MemoryStack."""
        if self._stack is None:
            self._stack = MemoryStack()
        return self._stack

    def wake_up(self, wing: str) -> str:
        """Load L0 + L1 context for a wing. Returns empty string if nothing found."""
        try:
            stack = self._get_stack()
            context = stack.wake_up(wing=wing)
            if context:
                logger.info("MemPalace wake-up loaded %d chars for wing '%s'", len(context), wing)
                return context
            return ""
        except Exception as e:
            logger.warning("MemPalace wake-up failed for wing '%s': %s", wing, e)
            return ""

    def search(self, query: str, wing: str, room: Optional[str] = None, n_results: int = 5) -> list[dict]:
        """Semantic search across stored sessions. Returns list of result dicts."""
        try:
            kwargs = {"query": query, "wing": wing, "room": room, "n_results": n_results}
            if self.palace_path:
                kwargs["palace_path"] = self.palace_path
            response = search_memories(**kwargs)
            return response.get("results", [])
        except Exception as e:
            logger.warning("MemPalace search failed: %s", e)
            return []

    def _build_session_text(self, session) -> str:
        """Build an emotional summary from a session for storage.

        Instead of storing verbatim transcripts (which feel surveillance-like),
        stores an emotional/relational summary of what happened.
        """
        duration = int((datetime.now() - session.session_start).total_seconds()) // 60
        lines = [
            f"=== Session with companion: {session.subject or 'general'} ===",
            f"Date: {session.session_start.strftime('%Y-%m-%d %H:%M')}",
            f"Duration: {duration} minutes",
            f"Study plan: {session.plan}",
            f"Distractions: {session.distraction_count}",
            "",
            "--- Session Notes ---",
        ]
        # Extract only user and assistant messages (skip system interventions)
        user_msgs = []
        assistant_msgs = []
        for msg in session.conversation_history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user" and content:
                user_msgs.append(content)
            elif role == "assistant" and content:
                assistant_msgs.append(content)

        # Store a summary rather than verbatim (keeps memory warm, not creepy)
        if user_msgs:
            # Take first and last few user messages to capture session arc
            sample = user_msgs[:3] + (user_msgs[-2:] if len(user_msgs) > 3 else [])
            lines.append("Things they said: " + " | ".join(sample[:5]))
        if assistant_msgs:
            sample = assistant_msgs[:2] + (assistant_msgs[-1:] if len(assistant_msgs) > 2 else [])
            lines.append("Things I said: " + " | ".join(sample[:3]))

        lines.append("")
        lines.append("=== End of Session ===")
        return "\n".join(lines)

    def persist(self, session) -> None:
        """Write the full session to MemPalace as a verbatim drawer under the general wing."""
        text = self._build_session_text(session)
        wing = "general"
        tmp_dir = None

        try:
            # Create a dedicated temp directory so mempalace mine only scans the session file
            tmp_dir = tempfile.mkdtemp(prefix="studybuddy_session_")
            tmp_path = os.path.join(tmp_dir, f"session_{session.subject or 'general'}.md")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(text)

            import sys
            cmd = [sys.executable, "-m", "mempalace", "mine", tmp_dir, "--wing", wing]
            subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            logger.info("Session persisted to MemPalace wing 'general'")
        except Exception as e:
            logger.warning("Failed to persist session to MemPalace: %s", e)
        finally:
            if tmp_dir:
                try:
                    import shutil
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except OSError:
                    pass

