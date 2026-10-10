from __future__ import annotations

from iterm_agents.session_state import AWAITING_USER_STATE, SessionStateTracker


def _session(
    state: str,
    *,
    session_id: str = "session-1",
    agent_type: str = "codex",
) -> dict[str, object]:
    return {
        "id": session_id,
        "agent_type": agent_type,
        "agent_state": state,
    }


class TestSessionStateTracker:
    def test_initial_idle_does_not_wait_for_user(self) -> None:
        tracker = SessionStateTracker()

        [session] = tracker.apply([_session("idle")])

        assert session["agent_state"] == "idle"
        assert session["awaiting_user"] is False

    def test_running_to_idle_marks_session_as_awaiting_user(self) -> None:
        tracker = SessionStateTracker()

        tracker.apply([_session("running")])
        [session] = tracker.apply([_session("idle")])

        assert session["agent_state"] == AWAITING_USER_STATE
        assert session["awaiting_user"] is True

    def test_acknowledge_clears_awaiting_user_until_next_run(self) -> None:
        tracker = SessionStateTracker()

        tracker.apply([_session("running")])
        tracker.apply([_session("idle")])
        tracker.acknowledge("session-1")
        [session] = tracker.apply([_session("idle")])

        assert session["agent_state"] == "idle"
        assert session["awaiting_user"] is False

    def test_acknowledge_all_clears_every_done_session(self) -> None:
        tracker = SessionStateTracker()

        tracker.apply(
            [_session("running", session_id="a"), _session("running", session_id="b")]
        )
        tracker.apply(
            [_session("idle", session_id="a"), _session("idle", session_id="b")]
        )
        tracker.acknowledge_all()
        a, b = tracker.apply(
            [_session("idle", session_id="a"), _session("idle", session_id="b")]
        )

        assert a["agent_state"] == "idle"
        assert b["agent_state"] == "idle"
        assert a["awaiting_user"] is False
        assert b["awaiting_user"] is False

    def test_new_run_clears_awaiting_user_immediately(self) -> None:
        tracker = SessionStateTracker()

        tracker.apply([_session("running")])
        tracker.apply([_session("idle")])
        [session] = tracker.apply([_session("running")])

        assert session["agent_state"] == "running"
        assert session["awaiting_user"] is False

    def test_missing_agent_metadata_clears_stale_waiting_state(self) -> None:
        tracker = SessionStateTracker()

        tracker.apply([_session("running")])
        tracker.apply([_session("idle")])
        [session] = tracker.apply([_session("", agent_type="")])

        assert session["agent_state"] == ""
        assert session["awaiting_user"] is False
