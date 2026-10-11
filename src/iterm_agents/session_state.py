"""Session-level UI state tracking for agent activity."""

from __future__ import annotations

import time
from typing import Any

AWAITING_USER_STATE = "awaiting_user"
CODEX_IDLE_CONFIRM_SECONDS = 3.0


class SessionStateTracker:
    """Tracks recent agent activity to surface completion acknowledgements."""

    def __init__(self) -> None:
        self._last_agent_states: dict[str, str] = {}
        self._awaiting_user_sessions: set[str] = set()
        self._labels: dict[str, str] = {}
        self._idle_since: dict[str, float] = {}
        self._agent_keys: dict[str, tuple[str, object]] = {}

    def apply(
        self,
        sessions: list[dict[str, Any]],
        *,
        fresh: bool = True,
        observed_at: float | None = None,
    ) -> list[dict[str, Any]]:
        """Decorate rows; only fresh observations can advance completion state."""
        now = time.monotonic() if observed_at is None else observed_at
        active_session_ids = {
            str(session.get("id", "")) for session in sessions if session.get("id") is not None
        }
        next_last_agent_states: dict[str, str] = {}

        for session in sessions:
            session["awaiting_user"] = False

            session_id = str(session.get("id", ""))
            agent_type = str(session.get("agent_type", "") or "")
            raw_state = str(session.get("agent_state", "") or "")
            if not session_id:
                continue

            session["label"] = self._labels.get(session_id, "")

            if not agent_type or raw_state not in {"running", "idle", "unknown"}:
                self._awaiting_user_sessions.discard(session_id)
                self._idle_since.pop(session_id, None)
                self._agent_keys.pop(session_id, None)
                continue

            previous_state = self._last_agent_states.get(session_id)
            agent_key = (agent_type, session.get("agent_pid"))
            if fresh and self._agent_keys.get(session_id) != agent_key:
                previous_state = None
                self._idle_since.pop(session_id, None)
                self._awaiting_user_sessions.discard(session_id)
            self._agent_keys[session_id] = agent_key

            state = raw_state
            if not fresh:
                state = previous_state or raw_state
            elif raw_state == "unknown":
                # Missing evidence cannot complete a turn or extend idle time.
                self._idle_since.pop(session_id, None)
                state = previous_state or raw_state
            elif agent_type == "codex" and raw_state == "idle" and previous_state == "running":
                since = self._idle_since.setdefault(session_id, now)
                if now - since < CODEX_IDLE_CONFIRM_SECONDS:
                    state = "running"
            else:
                self._idle_since.pop(session_id, None)

            if previous_state == "running" and state == "idle":
                self._awaiting_user_sessions.add(session_id)
                self._idle_since.pop(session_id, None)
            if state == "running":
                self._awaiting_user_sessions.discard(session_id)

            next_last_agent_states[session_id] = state
            session["agent_state"] = state

            if state == "idle" and session_id in self._awaiting_user_sessions:
                session["agent_state"] = AWAITING_USER_STATE
                session["awaiting_user"] = True

        self._awaiting_user_sessions.intersection_update(active_session_ids)
        self._labels = {
            session_id: label
            for session_id, label in self._labels.items()
            if session_id in active_session_ids
        }
        self._last_agent_states = next_last_agent_states
        self._idle_since = {
            session_id: since
            for session_id, since in self._idle_since.items()
            if session_id in active_session_ids
        }
        self._agent_keys = {
            session_id: key
            for session_id, key in self._agent_keys.items()
            if session_id in active_session_ids
        }
        return sessions

    def invalidate_observations(self) -> None:
        """Interrupt idle confirmation after a failed scan, retaining display state."""
        self._idle_since.clear()

    def set_label(self, session_id: str, label: str) -> None:
        """Attach a custom label to a session row; an empty label clears it."""
        if label:
            self._labels[session_id] = label
        else:
            self._labels.pop(session_id, None)

    def acknowledge(self, session_id: str) -> None:
        """Clear the transient completion state for a session."""
        self._awaiting_user_sessions.discard(session_id)
        if (
            session_id in self._last_agent_states
            and self._last_agent_states[session_id] != "running"
        ):
            self._last_agent_states[session_id] = "idle"

    def acknowledge_all(self) -> None:
        """Clear every transient completion state at once."""
        self._awaiting_user_sessions.clear()
