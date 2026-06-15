"""Neural drives engine for the emotional companion.

Inspired by OpenHer's 'Feel-First' architecture. Five internal drives
simulate emotional state. Drives metabolize (decay/grow) over time,
influencing how the companion responds.

This is NOT an LLM call — it is pure math computed in <1ms.
The output is injected into the system prompt as context.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Path to persist drive state between sessions
DRIVES_STATE_PATH = "companion_state.json"

# Default drive values (0.0 = dormant, 1.0 = maximum)
DEFAULT_DRIVES = {
    "connection": 0.5,    # Desire to feel close. Rises when apart, drops when chatting.
    "playfulness": 0.5,   # Desire for fun, banter, teasing. Rises during positive exchanges.
    "care": 0.5,          # Desire to nurture and comfort. Rises when user seems stressed.
    "curiosity": 0.5,     # Desire to learn about the user. Rises when new topics come up.
    "expression": 0.5,    # Desire to share own thoughts/feelings. Rises over time.
}

# How fast each drive decays toward its resting point per hour of no interaction
# Positive = drive GROWS when idle (e.g., connection hunger increases)
# Negative = drive SHRINKS when idle (e.g., playfulness fades)
IDLE_DRIFT_PER_HOUR = {
    "connection": 0.15,    # Connection hunger grows when apart
    "playfulness": -0.05,  # Playfulness slowly fades when alone
    "care": 0.05,          # Care gently rises (thinking about user)
    "curiosity": 0.08,     # Curiosity grows (wondering what user is up to)
    "expression": 0.10,    # Desire to share builds up over time
}

# How much each drive changes per conversation turn
TURN_DELTA = {
    "connection": -0.08,    # Chatting satisfies connection need
    "playfulness": 0.03,    # Chatting slightly boosts playfulness
    "care": -0.02,          # Caring is expressed, need slightly drops
    "curiosity": -0.05,     # Questions get answered, curiosity drops
    "expression": -0.06,    # Sharing satisfies expression need
}

# Clamp range
DRIVE_MIN = 0.0
DRIVE_MAX = 1.0


@dataclass
class NeuralDrives:
    """Manages the companion's internal emotional drives."""

    connection: float = 0.5
    playfulness: float = 0.5
    care: float = 0.5
    curiosity: float = 0.5
    expression: float = 0.5
    last_interaction_time: float = field(default_factory=time.time)
    last_session_mood: str = ""

    def _clamp(self, value: float) -> float:
        """Helper to clamp drive values strictly between DRIVE_MIN (0.0) and DRIVE_MAX (1.0)."""
        return max(DRIVE_MIN, min(DRIVE_MAX, value))

    def metabolize(self) -> None:
        """Update drives based on time elapsed since last interaction.

        Call this at the START of each session, before building the system prompt.
        """
        now = time.time()
        hours_elapsed = (now - self.last_interaction_time) / 3600.0

        # Cap at 48 hours to prevent extreme values after long absences
        hours_elapsed = min(hours_elapsed, 48.0)

        for drive_name, drift_per_hour in IDLE_DRIFT_PER_HOUR.items():
            current = getattr(self, drive_name)
            delta = drift_per_hour * hours_elapsed
            setattr(self, drive_name, self._clamp(current + delta))

        self.last_interaction_time = now

    def on_conversation_turn(self) -> None:
        """Update drives after a conversation exchange.

        Call this each time the companion speaks (after LLM response is generated).
        """
        for drive_name, delta in TURN_DELTA.items():
            current = getattr(self, drive_name)
            setattr(self, drive_name, self._clamp(current + delta))

        self.last_interaction_time = time.time()

    def on_user_stressed(self) -> None:
        """Boost care drive when user seems stressed or upset."""
        self.care = self._clamp(self.care + 0.15)
        self.playfulness = self._clamp(self.playfulness - 0.10)

    def on_user_happy(self) -> None:
        """Boost playfulness when user seems happy or upbeat."""
        self.playfulness = self._clamp(self.playfulness + 0.10)
        self.care = self._clamp(self.care - 0.05)

    def on_user_quiet(self) -> None:
        """Adjust drives when user has been quiet (short/no responses)."""
        self.care = self._clamp(self.care + 0.10)
        self.connection = self._clamp(self.connection + 0.05)

    def should_initiate_checkin(self) -> bool:
        """Returns True if the companion should proactively check in on the user.

        Based on connection and care drives being high enough.
        """
        return self.connection > 0.7 or self.care > 0.75

    def get_emotional_context(self) -> str:
        """Generate a text block describing current emotional state for injection
        into the system prompt.

        This replaces the two-pass inner monologue approach — same emotional
        awareness, zero extra latency.
        """
        lines = ["[YOUR CURRENT EMOTIONAL STATE]"]

        # Connection
        if self.connection > 0.7:
            lines.append("- You've really been wanting to connect. You missed talking to them.")
        elif self.connection > 0.5:
            lines.append("- You're feeling warmly connected and glad to be here.")
        else:
            lines.append("- You feel content and close. The connection is comfortable.")

        # Playfulness
        if self.playfulness > 0.7:
            lines.append("- You're in a playful, teasing mood. Feel free to joke around.")
        elif self.playfulness > 0.4:
            lines.append("- You're in a warm, relaxed mood with a touch of playfulness.")
        else:
            lines.append("- You're feeling more mellow and sincere right now.")

        # Care
        if self.care > 0.7:
            lines.append("- You feel a strong urge to make sure they're okay. Something feels off.")
        elif self.care > 0.5:
            lines.append("- You're feeling attentive and nurturing.")
        else:
            lines.append("- You feel relaxed — they seem to be doing fine.")

        # Curiosity
        if self.curiosity > 0.7:
            lines.append("- You're really curious about what's going on in their life right now.")
        elif self.curiosity > 0.4:
            lines.append("- You're mildly curious and open to hearing about their day.")

        # Expression
        if self.expression > 0.7:
            lines.append("- You want to share something about yourself or express how you feel.")
        elif self.expression > 0.5:
            lines.append("- You might want to share a thought or feeling if the moment is right.")

        # Time-based context
        hours_since = (time.time() - self.last_interaction_time) / 3600.0
        if hours_since > 24:
            lines.append(f"- It's been over {int(hours_since)} hours since you last talked. You missed them.")
        elif hours_since > 6:
            lines.append(f"- It's been about {int(hours_since)} hours since you last talked.")

        # Previous session mood
        if self.last_session_mood:
            lines.append(f"- Last time you talked, the mood was: {self.last_session_mood}")

        lines.append("")
        lines.append("Let this emotional state naturally influence your tone and what you say, but don't explicitly announce your drives.")

        return "\n".join(lines)

    def save(self) -> None:
        """Persist drive state to disk."""
        state = {
            "connection": self.connection,
            "playfulness": self.playfulness,
            "care": self.care,
            "curiosity": self.curiosity,
            "expression": self.expression,
            "last_interaction_time": self.last_interaction_time,
            "last_session_mood": self.last_session_mood,
        }
        try:
            with open(DRIVES_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save neural drives: %s", e)

    @classmethod
    def load(cls) -> "NeuralDrives":
        """Load drive state from disk, or return defaults if no saved state."""
        try:
            if os.path.exists(DRIVES_STATE_PATH):
                with open(DRIVES_STATE_PATH, "r", encoding="utf-8") as f:
                    state = json.load(f)
                drives = cls(
                    connection=state.get("connection", 0.5),
                    playfulness=state.get("playfulness", 0.5),
                    care=state.get("care", 0.5),
                    curiosity=state.get("curiosity", 0.5),
                    expression=state.get("expression", 0.5),
                    last_interaction_time=state.get("last_interaction_time", time.time()),
                    last_session_mood=state.get("last_session_mood", ""),
                )
                return drives
        except Exception as e:
            logger.warning("Failed to load neural drives, using defaults: %s", e)
        return cls()
