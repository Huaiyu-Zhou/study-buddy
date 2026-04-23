import json
from datetime import datetime
from typing import Optional

import openai

import config
from session import Session
from tools import TOOL_SCHEMAS, handle_tool_call


def _escalation_note(distraction_count: int) -> str:
    if distraction_count == 0:
        return ""
    if distraction_count <= 2:
        return f"The user has drifted off-task {distraction_count} time(s) this session. Be a bit firmer in your next response."
    if distraction_count <= 4:
        return f"The user has drifted off-task {distraction_count} times. Use a noticeably firmer, more direct tone."
    return (
        f"The user has drifted {distraction_count} times — something seems off. "
        "Shift to a reflective, empathetic mode: ask what's going on rather than just redirecting."
    )


class CoachingPipeline:
    def __init__(self, session: Session, client: openai.OpenAI) -> None:
        self.session = session
        self.client = client

    def build_system_prompt(self) -> str:
        parts = [
            f"You are a study coach with the persona: {self.session.persona}.",
            f"The user's current study plan: {self.session.plan}.",
            "Monitor focus, give brief interventions when the user goes off-task, and celebrate focus streaks.",
            "Keep responses concise — 1-3 sentences unless the user asks for more.",
        ]
        note = _escalation_note(self.session.distraction_count)
        if note:
            parts.append(note)
        return "\n".join(parts)

    def chat(self, user_message: str) -> str:
        """Send a message through the pipeline and return the coach's text reply."""
        self.session.conversation_history.append({"role": "user", "content": user_message})

        messages = [{"role": "system", "content": self.build_system_prompt()}]
        messages.extend(self.session.conversation_history)

        response = self.client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
        )

        while response.choices[0].finish_reason == "tool_calls":
            message = response.choices[0].message
            # Append the assistant's tool-call turn to the running message list
            messages.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in message.tool_calls
                ],
            })
            # Execute each tool and append results
            for tc in message.tool_calls:
                args = json.loads(tc.function.arguments)
                result = handle_tool_call(tc.function.name, args, self.session)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

            response = self.client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=messages,
                tools=TOOL_SCHEMAS,
            )

        text = response.choices[0].message.content or ""
        self.session.conversation_history.append({"role": "assistant", "content": text})
        return text

    def maybe_intervene(self) -> Optional[str]:
        """Trigger a watchdog intervention if conditions are met. Returns coach text or None."""
        if self.session.is_on_break():
            return None
        if self.session.off_task_duration_seconds() < config.OFF_TASK_THRESHOLD_SECONDS:
            return None
        since_last = self.session.seconds_since_last_intervention()
        if since_last is not None and since_last < config.INTERVENTION_COOLDOWN_SECONDS:
            return None

        last_snap = self.session.snapshot_history[-1] if self.session.snapshot_history else None
        context = ""
        if last_snap:
            context = f" ({last_snap.process}"
            if last_snap.url:
                context += f", {last_snap.url}"
            context += ")"

        prompt = (
            f"[WATCHDOG] User has been off-task for {self.session.off_task_duration_seconds()}s"
            f"{context}. Study plan: {self.session.plan}. Intervene now."
        )

        self.session.last_intervention = datetime.now()
        self.session.distraction_count += 1
        return self.chat(prompt)

    def maybe_reinforce(self) -> Optional[str]:
        """Send unprompted encouragement if the user has sustained a focus streak. Returns coach text or None."""
        if self.session.focus_streak_seconds() < config.FOCUS_STREAK_THRESHOLD_SECONDS:
            return None
        since_last = self.session.seconds_since_last_intervention()
        if since_last is not None and since_last < config.INTERVENTION_COOLDOWN_SECONDS:
            return None

        streak_min = self.session.focus_streak_seconds() // 60
        prompt = (
            f"[WATCHDOG] The user has been focused for {streak_min} minutes without drifting. "
            "Give brief, warm encouragement. One sentence only."
        )

        self.session.last_intervention = datetime.now()
        self.session.focus_streak_start = datetime.now()  # reset so it doesn't fire every tick
        return self.chat(prompt)
