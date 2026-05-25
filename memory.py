"""MemPalace wrapper for the Study Buddy — long-term memory across sessions."""

import logging
import os
import subprocess
import tempfile
from datetime import datetime
from typing import Optional

from mempalace.layers import MemoryStack
from mempalace.searcher import search_memories

logger = logging.getLogger(__name__)


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
        """Build a verbatim text blob from a session for storage."""
        duration = int((datetime.now() - session.session_start).total_seconds()) // 60
        lines = [
            f"=== Study Session: {session.subject or 'general'} ===",
            f"Date: {session.session_start.strftime('%Y-%m-%d %H:%M')}",
            f"Duration: {duration} minutes",
            f"Plan: {session.plan}",
            f"Persona: {session.persona}",
            f"Distractions: {session.distraction_count} distraction(s)",
            "",
            "--- Conversation ---",
        ]
        for msg in session.conversation_history:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            lines.append(f"[{role}]: {content}")

        lines.append("")
        lines.append("=== End of Session ===")
        return "\n".join(lines)

    def persist(self, session) -> None:
        """Write the full session to MemPalace as a verbatim drawer under the subject wing."""
        text = self._build_session_text(session)
        wing = session.subject or "general"
        tmp_dir = None

        try:
            # Create a dedicated temp directory so mempalace mine only scans the session file
            tmp_dir = tempfile.mkdtemp(prefix="studybuddy_session_")
            tmp_path = os.path.join(tmp_dir, f"session_{wing}.md")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(text)

            import sys
            cmd = [sys.executable, "-m", "mempalace", "mine", tmp_dir, "--wing", wing]
            subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            logger.info("Session persisted to MemPalace wing '%s'", wing)
        except Exception as e:
            logger.warning("Failed to persist session to MemPalace: %s", e)
        finally:
            if tmp_dir:
                try:
                    import shutil
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except OSError:
                    pass

