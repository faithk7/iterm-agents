from __future__ import annotations

from iterm_agents.session_state import AWAITING_USER_STATE, SessionStateTracker


def _session(
    state: str,
    *,
    session_id: str = "session-1",
    agent_type: str = "claude",
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

    def test_set_label_surfaces_in_apply(self) -> None:
        tracker = SessionStateTracker()

        tracker.set_label("session-1", "blocked on review")
        [session] = tracker.apply([_session("idle")])

        assert session["label"] == "blocked on review"

    def test_empty_label_clears(self) -> None:
        tracker = SessionStateTracker()

        tracker.set_label("session-1", "wip")
        tracker.set_label("session-1", "")
        [session] = tracker.apply([_session("idle")])

        assert session["label"] == ""

    def test_label_is_dropped_when_session_disappears(self) -> None:
        tracker = SessionStateTracker()

        tracker.set_label("session-1", "wip")
        tracker.apply([_session("idle")])

        # session-1 vanishes for a scan; its label is pruned with it.
        tracker.apply([_session("idle", session_id="session-2")])

        [same] = tracker.apply([_session("idle", session_id="session-1")])
        assert same["label"] == ""


class TestCodexCompletion:
    def apply(
        self, tracker: SessionStateTracker, state: str, now: float, *, fresh: bool = True
    ) -> dict[str, object]:
        [row] = tracker.apply([_session(state, agent_type="codex")], observed_at=now, fresh=fresh)
        return row

    def test_brief_idle_gap_never_shows_done(self) -> None:
        tracker = SessionStateTracker()
        self.apply(tracker, "running", 0.0)
        assert self.apply(tracker, "idle", 1.0)["agent_state"] == "running"
        assert self.apply(tracker, "running", 2.0)["agent_state"] == "running"
        assert self.apply(tracker, "idle", 3.0)["agent_state"] == "running"
        assert self.apply(tracker, "idle", 5.9)["agent_state"] == "running"
        done = self.apply(tracker, "idle", 6.0)
        assert done["agent_state"] == AWAITING_USER_STATE
        assert done["awaiting_user"] is True

    def test_cached_idle_cannot_confirm_completion(self) -> None:
        tracker = SessionStateTracker()
        self.apply(tracker, "running", 0.0)
        self.apply(tracker, "idle", 1.0)
        for now in (1.1, 2.0, 4.0, 10.0):
            assert self.apply(tracker, "idle", now, fresh=False)["agent_state"] == "running"
        assert self.apply(tracker, "idle", 10.1)["agent_state"] == AWAITING_USER_STATE

    def test_unknown_resets_idle_confirmation_and_keeps_previous_state(self) -> None:
        tracker = SessionStateTracker()
        self.apply(tracker, "running", 0.0)
        self.apply(tracker, "idle", 1.0)
        assert self.apply(tracker, "unknown", 4.0)["agent_state"] == "running"
        assert self.apply(tracker, "idle", 5.0)["agent_state"] == "running"
        assert self.apply(tracker, "idle", 8.0)["agent_state"] == AWAITING_USER_STATE
        assert self.apply(tracker, "unknown", 9.0)["agent_state"] == AWAITING_USER_STATE

    def test_initial_idle_and_acknowledged_completion_stay_idle(self) -> None:
        tracker = SessionStateTracker()
        assert self.apply(tracker, "idle", 0.0)["agent_state"] == "idle"
        self.apply(tracker, "running", 1.0)
        self.apply(tracker, "idle", 2.0)
        self.apply(tracker, "idle", 5.0)
        tracker.acknowledge("session-1")
        assert self.apply(tracker, "idle", 5.1, fresh=False)["agent_state"] == "idle"
        assert self.apply(tracker, "running", 6.0)["agent_state"] == "running"

    def test_closed_session_drops_pending_completion(self) -> None:
        tracker = SessionStateTracker()
        self.apply(tracker, "running", 0.0)
        self.apply(tracker, "idle", 1.0)
        tracker.apply([], observed_at=2.0)
        assert self.apply(tracker, "idle", 5.0)["agent_state"] == "idle"

    def test_replaced_codex_process_does_not_inherit_pending_completion(self) -> None:
        tracker = SessionStateTracker()
        running = {**_session("running", agent_type="codex"), "agent_pid": 100}
        idle = {**running, "agent_state": "idle"}
        tracker.apply([dict(running)], observed_at=0.0)
        tracker.apply([dict(idle)], observed_at=1.0)
        [row] = tracker.apply([{**idle, "agent_pid": 200}], observed_at=4.0)
        assert row["agent_state"] == "idle"
        assert row["awaiting_user"] is False

    def test_sessions_have_independent_confirmation_timers(self) -> None:
        tracker = SessionStateTracker()
        a = _session("running", session_id="a", agent_type="codex")
        b = {**a, "id": "b"}
        tracker.apply([a, b], observed_at=0.0)
        tracker.apply([{**a, "agent_state": "idle"}, b], observed_at=1.0)
        idle = [{**row, "agent_state": "idle"} for row in (a, b)]
        tracker.apply([dict(row) for row in idle], observed_at=2.0)
        rows = tracker.apply([dict(row) for row in idle], observed_at=4.0)
        assert [row["agent_state"] for row in rows] == [AWAITING_USER_STATE, "running"]
