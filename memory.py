"""MemPalace wrapper for the Study Buddy — long-term memory across sessions."""

import logging
from typing import Optional

from mempalace.layers import MemoryStack

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
