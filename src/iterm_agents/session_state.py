"""Session-level UI state tracking for agent activity."""

from __future__ import annotations

from typing import Any

AWAITING_USER_STATE = "awaiting_user"


class SessionStateTracker:
    """Tracks recent agent activity to surface completion acknowledgements."""

    def __init__(self) -> None:
        self._last_agent_states: dict[str, str] = {}
        self._awaiting_user_sessions: set[str] = set()

    def apply(self, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Decorate sessions with transient UI state derived from state transitions."""
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

            if not agent_type or raw_state not in {"running", "idle"}:
                self._awaiting_user_sessions.discard(session_id)
                continue

            previous_state = self._last_agent_states.get(session_id)
            if previous_state == "running" and raw_state == "idle":
                self._awaiting_user_sessions.add(session_id)
            if raw_state == "running":
                self._awaiting_user_sessions.discard(session_id)

            next_last_agent_states[session_id] = raw_state

            if raw_state == "idle" and session_id in self._awaiting_user_sessions:
                session["agent_state"] = AWAITING_USER_STATE
                session["awaiting_user"] = True

        self._awaiting_user_sessions.intersection_update(active_session_ids)
        self._last_agent_states = next_last_agent_states
        return sessions

    def acknowledge(self, session_id: str) -> None:
        """Clear the transient completion state for a session."""
        self._awaiting_user_sessions.discard(session_id)
        if (
            session_id in self._last_agent_states
            and self._last_agent_states[session_id] != "running"
        ):
            self._last_agent_states[session_id] = "idle"
