"""Tests for agent detection logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from git import Repo

from iterm_agents.detector import (
    AgentState,
    AgentType,
    GitInfo,
    ProcessInfo,
    _build_children,
    _comm_basename,
    _detect_claude_state,
    _detect_codex_state,
    _find_ancestor_pid,
    _get_codex_active_pids,
    _get_descendants,
    _is_agent_process,
    _is_claude_process,
    _is_codex_process,
    cursor_activity_signature,
    cursor_turn_is_live,
    detect_agents,
    get_git_info,
    screen_shows_active_turn,
)


def _make_table(procs: list[tuple[int, int, str]]) -> dict[int, ProcessInfo]:
    return {pid: ProcessInfo(pid=pid, ppid=ppid, command=command) for pid, ppid, command in procs}


class TestCommBasename:
    def test_simple(self) -> None:
        assert _comm_basename("claude") == "claude"

    def test_full_path(self) -> None:
        assert _comm_basename("/usr/local/bin/claude") == "claude"

    def test_nested_path(self) -> None:
        assert _comm_basename("/a/b/c/codex") == "codex"

    def test_just_slash(self) -> None:
        assert _comm_basename("/") == ""


class TestIsAgentProcess:
    def test_claude(self) -> None:
        assert _is_claude_process("claude")
        assert _is_claude_process("/usr/local/bin/claude")

    def test_codex(self) -> None:
        assert _is_codex_process("codex")
        assert _is_codex_process("/home/user/.local/bin/codex")

    def test_not_agent(self) -> None:
        assert not _is_agent_process("bash")
        assert not _is_agent_process("node")

    def test_partial_name_not_matched(self) -> None:
        assert not _is_claude_process("claude-helper")
        assert not _is_codex_process("codex-sandbox")

    def test_is_agent_matches_either(self) -> None:
        assert _is_agent_process("claude")
        assert _is_agent_process("codex")
        assert not _is_agent_process("vim")


class TestDescendants:
    def test_finds_children(self) -> None:
        table = _make_table(
            [
                (1, 0, "init"),
                (10, 1, "bash"),
                (20, 10, "claude"),
                (30, 20, "caffeinate"),
                (40, 20, "node"),
            ]
        )
        desc = _get_descendants(_build_children(table), 20)
        pids = {d.pid for d in desc}
        assert pids == {30, 40}

    def test_deep_tree(self) -> None:
        table = _make_table(
            [
                (1, 0, "init"),
                (10, 1, "bash"),
                (20, 10, "codex"),
                (30, 20, "sandbox-exec"),
                (40, 30, "bash"),
                (50, 40, "python"),
            ]
        )
        desc = _get_descendants(_build_children(table), 20)
        pids = {d.pid for d in desc}
        assert pids == {30, 40, 50}

    def test_no_descendants(self) -> None:
        table = _make_table([(20, 10, "claude")])
        desc = _get_descendants(_build_children(table), 20)
        assert desc == []

    def test_nonexistent_pid(self) -> None:
        table = _make_table([(20, 10, "claude")])
        desc = _get_descendants(_build_children(table), 999)
        assert desc == []


class TestFindAncestor:
    def test_finds_ancestor(self) -> None:
        table = _make_table(
            [
                (1, 0, "init"),
                (10, 1, "bash"),
                (20, 10, "claude"),
            ]
        )
        assert _find_ancestor_pid(table, 20, {10}) == 10

    def test_no_match(self) -> None:
        table = _make_table(
            [
                (1, 0, "init"),
                (10, 1, "bash"),
                (20, 10, "claude"),
            ]
        )
        assert _find_ancestor_pid(table, 20, {99}) is None

    def test_self_is_target(self) -> None:
        table = _make_table(
            [
                (10, 1, "bash"),
                (20, 10, "claude"),
            ]
        )
        assert _find_ancestor_pid(table, 10, {10}) == 10

    def test_deep_ancestor(self) -> None:
        table = _make_table(
            [
                (1, 0, "init"),
                (10, 1, "bash"),
                (20, 10, "zsh"),
                (30, 20, "node"),
                (40, 30, "claude"),
            ]
        )
        assert _find_ancestor_pid(table, 40, {10}) == 10


class TestDetectClaudeState:
    def test_running_with_caffeinate(self) -> None:
        table = _make_table(
            [
                (20, 10, "claude"),
                (30, 20, "caffeinate"),
            ]
        )
        assert _detect_claude_state(_build_children(table), 20) == AgentState.RUNNING

    def test_idle_without_caffeinate(self) -> None:
        table = _make_table(
            [
                (20, 10, "claude"),
            ]
        )
        assert _detect_claude_state(_build_children(table), 20) == AgentState.IDLE

    def test_running_with_deep_caffeinate(self) -> None:
        table = _make_table(
            [
                (20, 10, "claude"),
                (30, 20, "node"),
                (40, 30, "caffeinate"),
            ]
        )
        assert _detect_claude_state(_build_children(table), 20) == AgentState.RUNNING

    def test_idle_with_unrelated_children(self) -> None:
        table = _make_table(
            [
                (20, 10, "claude"),
                (30, 20, "node"),
                (40, 20, "python"),
            ]
        )
        assert _detect_claude_state(_build_children(table), 20) == AgentState.IDLE


class TestDetectCodexState:
    def test_running_with_sandbox(self) -> None:
        table = _make_table(
            [
                (20, 10, "codex"),
                (30, 20, "sandbox-exec"),
            ]
        )
        assert _detect_codex_state(_build_children(table), 20) == AgentState.RUNNING

    def test_running_with_bwrap(self) -> None:
        table = _make_table(
            [
                (20, 10, "codex"),
                (30, 20, "bwrap"),
            ]
        )
        assert _detect_codex_state(_build_children(table), 20) == AgentState.RUNNING

    def test_running_with_linux_sandbox(self) -> None:
        table = _make_table(
            [
                (20, 10, "codex"),
                (30, 20, "codex-linux-sandbox"),
            ]
        )
        assert _detect_codex_state(_build_children(table), 20) == AgentState.RUNNING

    def test_idle_without_sandbox(self) -> None:
        table = _make_table(
            [
                (20, 10, "codex"),
            ]
        )
        assert _detect_codex_state(_build_children(table), 20) == AgentState.IDLE

    def test_idle_with_non_sandbox_children(self) -> None:
        """Non-sandbox children don't affect _detect_codex_state directly.
        IOKit assertion check in detect_agents handles the running detection."""
        table = _make_table(
            [
                (20, 10, "codex"),
                (30, 20, "npm exec freee-mcp"),
                (40, 20, "sleep"),
            ]
        )
        # _detect_codex_state only checks for sandbox-exec descendants
        assert _detect_codex_state(_build_children(table), 20) == AgentState.IDLE


class TestGetCodexActivePids:
    def test_parses_active_pid(self) -> None:
        pmset_output = (
            "Listed by owning process:\n"
            "   pid 90513(codex-aarch64-apple-darwin): [0x0004055400018f9a]"
            " 00:00:10 PreventUserIdleSystemSleep"
            ' named: "Codex is running an active turn"\n'
            "   pid 384(powerd): [0x0003db9300018771]"
            " 02:55:59 PreventUserIdleSystemSleep"
            ' named: "Powerd - Prevent sleep while display is on"\n'
        )
        with patch("iterm_agents.detector.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = pmset_output
            pids = _get_codex_active_pids()
        assert pids == {90513}

    def test_multiple_active_codex(self) -> None:
        pmset_output = (
            "   pid 100(codex-aarch64-apple-darwin): [0x01]"
            " 00:00:05 PreventUserIdleSystemSleep"
            ' named: "Codex is running an active turn"\n'
            "   pid 200(codex-aarch64-apple-darwin): [0x02]"
            " 00:00:03 PreventUserIdleSystemSleep"
            ' named: "Codex is running an active turn"\n'
        )
        with patch("iterm_agents.detector.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = pmset_output
            pids = _get_codex_active_pids()
        assert pids == {100, 200}

    def test_no_active_codex(self) -> None:
        pmset_output = (
            "   pid 384(powerd): [0x01]"
            " 02:55:59 PreventUserIdleSystemSleep"
            ' named: "Powerd - Prevent sleep while display is on"\n'
        )
        with patch("iterm_agents.detector.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = pmset_output
            pids = _get_codex_active_pids()
        assert pids == set()

    def test_pmset_failure(self) -> None:
        with patch("iterm_agents.detector.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            pids = _get_codex_active_pids()
        assert pids == set()


class TestDetectAgents:
    def test_child_index_is_shared_and_rebuilt_for_each_snapshot(self) -> None:
        table = _make_table(
            [
                (10, 1, "zsh"),
                (20, 10, "claude"),
                (30, 20, "caffeinate"),
                (40, 1, "zsh"),
                (50, 40, "codex"),
                (60, 50, "sandbox-exec"),
                (70, 1, "zsh"),
                (80, 70, "kimi"),
                (90, 80, "caffeinate"),
            ]
        )
        with (
            patch("iterm_agents.detector._build_process_table", return_value=table),
            patch("iterm_agents.detector._get_codex_active_pids", return_value=set()),
            patch("iterm_agents.detector._build_children", wraps=_build_children) as build,
        ):
            assert [a.state for a in detect_agents()] == [AgentState.RUNNING] * 3
            assert build.call_count == 1
            for pid in (30, 60, 90):
                del table[pid]
            assert [a.state for a in detect_agents()] == [AgentState.IDLE] * 3
            assert build.call_count == 2

    @patch("iterm_agents.detector._get_codex_active_pids", return_value=set())
    @patch("iterm_agents.detector._build_process_table")
    def test_finds_claude_and_codex(self, mock_table: object, mock_pids: object) -> None:
        mock_table.return_value = _make_table(  # type: ignore[union-attr]
            [
                (1, 0, "init"),
                (10, 1, "bash"),
                (20, 10, "claude"),
                (30, 20, "caffeinate"),
                (40, 1, "zsh"),
                (50, 40, "codex"),
                (60, 50, "sandbox-exec"),
            ]
        )
        agents = detect_agents()
        assert len(agents) == 2
        claude_agents = [a for a in agents if a.agent_type == AgentType.CLAUDE]
        codex_agents = [a for a in agents if a.agent_type == AgentType.CODEX]
        assert len(claude_agents) == 1
        assert claude_agents[0].state == AgentState.RUNNING
        assert len(codex_agents) == 1
        assert codex_agents[0].state == AgentState.RUNNING

    @patch("iterm_agents.detector._get_codex_active_pids", return_value=set())
    @patch("iterm_agents.detector._build_process_table")
    def test_filters_by_session_pids(self, mock_table: object, mock_pids: object) -> None:
        mock_table.return_value = _make_table(  # type: ignore[union-attr]
            [
                (1, 0, "init"),
                (10, 1, "bash"),
                (20, 10, "claude"),
                (40, 1, "zsh"),
                (50, 40, "codex"),
            ]
        )
        # Only session with pid=10, so codex (under pid=40) should be excluded
        agents = detect_agents(session_pids={10})
        assert len(agents) == 1
        assert agents[0].agent_type == AgentType.CLAUDE
        assert agents[0].session_pid == 10

    @patch("iterm_agents.detector._get_codex_active_pids", return_value=set())
    @patch("iterm_agents.detector._build_process_table")
    def test_no_agents(self, mock_table: object, mock_pids: object) -> None:
        mock_table.return_value = _make_table(  # type: ignore[union-attr]
            [
                (1, 0, "init"),
                (10, 1, "bash"),
                (20, 10, "vim"),
            ]
        )
        agents = detect_agents()
        assert agents == []

    @patch("iterm_agents.detector._get_codex_active_pids", return_value={50})
    @patch("iterm_agents.detector._build_process_table")
    def test_codex_running_via_iokit_assertion(self, mock_table: object, mock_pids: object) -> None:
        """Codex with IOKit assertion should be running even without sandbox children."""
        mock_table.return_value = _make_table(  # type: ignore[union-attr]
            [
                (1, 0, "init"),
                (10, 1, "bash"),
                (50, 10, "codex"),
                (60, 50, "npm exec freee-mcp"),
            ]
        )
        agents = detect_agents()
        assert len(agents) == 1
        assert agents[0].agent_type == AgentType.CODEX
        assert agents[0].state == AgentState.RUNNING

    @patch("iterm_agents.detector._get_codex_active_pids", return_value={50})
    @patch("iterm_agents.detector._build_process_table")
    def test_only_active_codex_is_running(self, mock_table: object, mock_pids: object) -> None:
        """Only the codex PID in the assertion set should be running."""
        mock_table.return_value = _make_table(  # type: ignore[union-attr]
            [
                (1, 0, "init"),
                (10, 1, "bash"),
                (50, 10, "codex"),  # active (in assertion set)
                (70, 1, "zsh"),
                (80, 70, "codex"),  # idle (not in assertion set)
            ]
        )
        agents = detect_agents()
        assert len(agents) == 2
        active = next(a for a in agents if a.pid == 50)
        idle = next(a for a in agents if a.pid == 80)
        assert active.state == AgentState.RUNNING
        assert idle.state == AgentState.IDLE

    @patch("iterm_agents.detector._get_codex_active_pids", return_value=set())
    @patch("iterm_agents.detector._build_process_table")
    def test_recognizes_cursor_devin_and_kimi(self, mock_table: object, mock_pids: object) -> None:
        cursor = (
            "/Users/kaiqu/.local/share/cursor-agent/versions/2026.10.01/node "
            "--use-system-ca "
            "/Users/kaiqu/.local/share/cursor-agent/versions/2026.10.01/index.js"
        )
        mock_table.return_value = _make_table(  # type: ignore[union-attr]
            [
                (1, 0, "init"),
                (10, 1, "zsh"),
                (20, 10, cursor),
                (21, 20, "/usr/bin/sandbox-exec"),
                (30, 1, "zsh"),
                (40, 30, "/opt/homebrew/bin/devin"),
                (50, 1, "zsh"),
                (60, 50, "/Users/kaiqu/.kimi-code/bin/kimi"),
                (70, 1, "/Applications/Cursor.app/Contents/MacOS/Cursor"),
                (80, 1, "/Applications/Kimi.app/Contents/MacOS/Kimi"),
                (90, 1, "/Applications/KimiCU.app/Contents/MacOS/kimi-cu"),
            ]
        )
        agents = detect_agents()
        found = {agent.agent_type: agent for agent in agents}
        assert set(found) == {AgentType.CURSOR, AgentType.DEVIN, AgentType.KIMI}
        assert found[AgentType.CURSOR].state == AgentState.RUNNING
        assert found[AgentType.CURSOR].pid == 20
        assert found[AgentType.DEVIN].state == AgentState.IDLE
        assert found[AgentType.KIMI].state == AgentState.IDLE

    @patch("iterm_agents.detector._get_codex_active_pids", return_value=set())
    @patch("iterm_agents.detector._build_process_table")
    def test_kimi_code_process_name(self, mock_table: object, mock_pids: object) -> None:
        mock_table.return_value = _make_table(  # type: ignore[union-attr]
            [
                (1, 0, "init"),
                (10, 1, "-zsh"),
                (20, 10, "kimi-code"),
                (30, 20, "/Applications/KimiCU.app/Contents/MacOS/kimi-cu mcp -s user"),
            ]
        )
        agents = detect_agents()
        assert len(agents) == 1
        assert agents[0].pid == 20
        assert agents[0].agent_type == AgentType.KIMI
        assert agents[0].session_pid is None

    @patch("iterm_agents.detector._get_codex_active_pids", return_value=set())
    @patch("iterm_agents.detector._build_process_table")
    def test_cursor_wrapper_argv_counts_once(self, mock_table: object, mock_pids: object) -> None:
        parent = (
            "/Users/kaiqu/.local/bin/agent --use-system-ca "
            "/Users/kaiqu/.local/share/cursor-agent/versions/2026.10.01/index.js"
        )
        child = (
            "/Users/kaiqu/.local/share/cursor-agent/versions/2026.10.01/node "
            "/Users/kaiqu/.local/share/cursor-agent/versions/2026.10.01/index.js"
        )
        mock_table.return_value = _make_table(  # type: ignore[union-attr]
            [
                (10, 1, "zsh"),
                (20, 10, parent),
                (21, 20, child),
            ]
        )
        agents = detect_agents()
        assert len(agents) == 1
        assert agents[0].pid == 20
        assert agents[0].agent_type == AgentType.CURSOR

    def test_caffeinate_with_arguments_is_running(self) -> None:
        table = _make_table(
            [
                (20, 10, "/usr/local/bin/claude"),
                (30, 20, "/usr/bin/caffeinate -dims"),
            ]
        )
        assert _detect_claude_state(_build_children(table), 20) == AgentState.RUNNING


class TestScreenShowsActiveTurn:
    def test_cursor_running_footer(self) -> None:
        screen = "\n".join(
            [
                "  some command output",
                "  ⠠⠜ Running  8.98k tokens",
                "  → Add a follow-up                                       ctrl+c to stop",
                "  Grok 4.7 256K High                                      Run Everything",
            ]
        )
        assert screen_shows_active_turn(AgentType.CURSOR, screen)

    def test_cursor_idle_follow_up_is_not_running(self) -> None:
        screen = "\n".join(
            [
                "  → Add a follow-up",
                "  Grok 4.7 256K High · 35.1%                              Run Everything",
            ]
        )
        assert not screen_shows_active_turn(AgentType.CURSOR, screen)

    def test_running_mention_above_the_footer_is_ignored(self) -> None:
        older = [f"  Running {index} tokens in the transcript" for index in range(20)]
        screen = "\n".join(
            [
                *older,
                "  → Add a follow-up",
                "  Grok 4.7 256K High                                      Run Everything",
            ]
        )
        assert not screen_shows_active_turn(AgentType.CURSOR, screen)

    def test_other_agents_ignore_the_cursor_footer(self) -> None:
        screen = "  ⠠⠜ Running  8.98k tokens\n  ctrl+c to stop"
        assert not screen_shows_active_turn(AgentType.KIMI, screen)

    def test_leftover_running_line_above_an_idle_composer_is_ignored(self) -> None:
        screen = "\n".join(
            [
                "  ⠰⠳ Running  2.79k tokens",
                "  ▄▄▄▄▄▄▄▄",
                "  → Add a follow-up",
                "  ▀▀▀▀▀▀▀▀",
                "  Grok 4.7 256K High · 88.5% · 14 files edited            Run Everything",
                "  ~",
            ]
        )
        assert cursor_activity_signature(screen) is None
        assert not screen_shows_active_turn(AgentType.CURSOR, screen)

    def test_signature_tracks_the_spinner_and_a_tool_timer(self) -> None:
        first = "\n".join(
            [
                "    import asyncio 2.6s in code/iterm-agents",
                "  ⠰⠳ Running  2.79k tokens",
                "  ▄▄▄▄▄▄▄▄",
                "  → Add a follow-up                                       ctrl+c to stop",
                "  ▀▀▀▀▀▀▀▀",
                "  3 tasks",
                "  ~",
            ]
        )
        spun = first.replace("⠰⠳", "⠠⠜")
        later = first.replace("2.6s", "7.6s")
        signature = cursor_activity_signature(first)
        assert signature is not None
        # The spinner ticks while the turn lives, so it counts as motion.
        assert cursor_activity_signature(spun) != signature
        assert cursor_activity_signature(later) != signature
        # A frame redrawn with the same spinner glyph is not motion.
        assert cursor_activity_signature(first) == signature

    def test_frozen_footer_is_not_a_live_turn(self) -> None:
        signature = "Running 2.79k tokens"
        assert cursor_turn_is_live(signature, None, 0)
        assert cursor_turn_is_live(signature, signature, 29)
        assert not cursor_turn_is_live(signature, signature, 30)
        assert cursor_turn_is_live("Running 2.80k tokens", signature, 40)


class TestDevinScreenShowsActiveTurn:
    def test_running_status_line_above_the_input_box(self) -> None:
        screen = "\n".join(
            [
                "  │ some tool output",
                "  ⠀⠸ Running tools · 2m 28s (esc twice to interrupt)",
                "  ─────────────────────────── (bypass permissions on) ─",
                "  ❭ Guide Devin while it works",
                "  ───────────────────────────────────────────────",
                "  SWE-2 Max                       Context: 89k / 262k tokens (34%)",
            ]
        )
        assert screen_shows_active_turn(AgentType.DEVIN, screen)

    def test_esc_again_variant_is_running(self) -> None:
        screen = "\n".join(
            [
                "  ⠀⠸ Thinking · 12s (esc again to interrupt)",
                "  ─────────────────────────── (bypass permissions on) ─",
                "  ❭ Guide Devin while it works",
                "  ───────────────────────────────────────────────",
                "  SWE-2 Max                       Context: 89k / 262k tokens (34%)",
            ]
        )
        assert screen_shows_active_turn(AgentType.DEVIN, screen)

    def test_idle_composer_is_not_running(self) -> None:
        screen = "\n".join(
            [
                "  Report updated.",
                "  ─────────────────────────── (bypass permissions on) ─",
                "  ❭ Ask Devin to build features, fix bugs, or work on your code",
                "  ───────────────────────────────────────────────",
                "  SWE-2 High                      Context: 98k / 262k tokens (37%)",
            ]
        )
        assert not screen_shows_active_turn(AgentType.DEVIN, screen)

    def test_transcript_echo_without_box_border_is_ignored(self) -> None:
        screen = "\n".join(
            [
                '  │ print("(esc twice to interrupt)")',
                "  │ Exited with code 0",
                "  ─────────────────────────── (bypass permissions on) ─",
                "  ❭ Ask Devin to build features, fix bugs, or work on your code",
                "  ───────────────────────────────────────────────",
                "  SWE-2 Max                       Context: 89k / 262k tokens (34%)",
            ]
        )
        assert not screen_shows_active_turn(AgentType.DEVIN, screen)

    def test_hint_above_the_footer_window_is_ignored(self) -> None:
        older = [f"  transcript line {index}" for index in range(15)]
        screen = "\n".join(
            [
                "  ⠀⠸ Running tools · 2m 28s (esc twice to interrupt)",
                "  ─────────────────────────── (bypass permissions on) ─",
                *older,
                "  ❭ Ask Devin to build features, fix bugs, or work on your code",
                "  ───────────────────────────────────────────────",
                "  SWE-2 Max                       Context: 89k / 262k tokens (34%)",
            ]
        )
        assert not screen_shows_active_turn(AgentType.DEVIN, screen)

    def test_other_agents_ignore_the_devin_hint(self) -> None:
        screen = "\n".join(
            [
                "  ⠀⠸ Running tools · 2m 28s (esc twice to interrupt)",
                "  ─────────────────────────── (bypass permissions on) ─",
            ]
        )
        assert not screen_shows_active_turn(AgentType.KIMI, screen)


class TestCodexScreenShowsActiveTurn:
    def test_working_status_line_above_the_composer(self) -> None:
        screen = "\n".join(
            [
                "  • Explored",
                "  └ Read index.tsx",
                "  • Working (4m 34s • esc to interrupt)",
                "    └ Tip: Press ⌃r to search previously entered prompts.",
                "  \u203a Ask Codex to do anything",
                "  GPT-6.1-Sol high · ~/repo · Thread title",
                "  ? for shortcuts     ⚠ 1 warning · f2 to view",
            ]
        )
        assert screen_shows_active_turn(AgentType.CODEX, screen)

    def test_shortcuts_footer_anchors_composerless_variant(self) -> None:
        screen = "\n".join(
            [
                "  • Working (8s • esc to interrupt)",
                "  Ask Codex to do anything",
                "  GPT-6.1-Sol high · ~/repo · Thread title",
                "  ← for agents · ? for shortcuts",
            ]
        )
        assert screen_shows_active_turn(AgentType.CODEX, screen)

    def test_draft_in_the_composer_still_counts(self) -> None:
        screen = "\n".join(
            [
                "  • Working (12s • esc to interrupt)",
                "  \u203a follow up on this later",
                "  GPT-6.1-Sol high · ~/repo · Thread title",
            ]
        )
        assert screen_shows_active_turn(AgentType.CODEX, screen)

    def test_idle_composer_is_not_running(self) -> None:
        screen = "\n".join(
            [
                "  • Explored",
                "  └ Read index.tsx",
                "  \u203a Ask Codex to do anything",
                "  GPT-6.1-Sol high · ~/repo · Thread title",
                "  ? for shortcuts",
            ]
        )
        assert not screen_shows_active_turn(AgentType.CODEX, screen)

    def test_transcript_echo_without_composer_is_ignored(self) -> None:
        screen = "\n".join(
            [
                '  • print("esc to interrupt)")',
                "  • Explored",
                "  └ Read index.tsx",
                "  GPT-6.1-Sol high · ~/repo · Thread title",
            ]
        )
        assert not screen_shows_active_turn(AgentType.CODEX, screen)

    def test_hint_above_the_footer_window_is_ignored(self) -> None:
        older = [f"  transcript line {index}" for index in range(15)]
        screen = "\n".join(
            [
                "  • Working (4m 34s • esc to interrupt)",
                "    └ Tip: Press ⌃r to search previously entered prompts.",
                *older,
                "  \u203a Ask Codex to do anything",
                "  GPT-6.1-Sol high · ~/repo · Thread title",
            ]
        )
        assert not screen_shows_active_turn(AgentType.CODEX, screen)

    def test_other_agents_ignore_the_codex_hint(self) -> None:
        screen = "\n".join(
            [
                "  • Working (4m 34s • esc to interrupt)",
                "  \u203a Ask Codex to do anything",
            ]
        )
        assert not screen_shows_active_turn(AgentType.DEVIN, screen)


class TestKimiScreenShowsActiveTurn:
    def test_working_status_line_above_the_composer(self) -> None:
        screen = "\n".join(
            [
                "  001 [⣿⣦⣀⣀⣀⣀⣀⣀] Let me write the first reque…",
                "  🌗 Working…  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "   ──────────────────────────────────────────────",
                "    Todo",
                "    ● 写 43 条回复 —— 6 …",
                "    … +1 more (1 done) · ctrl+t to expand",
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
                "  Ask When Needed swarm  K2.8 Preview thinking:…",
            ]
        )
        assert screen_shows_active_turn(AgentType.KIMI, screen)

    def test_orchestrating_and_rate_limited_variants(self) -> None:
        for label in (
            "Orchestrating",
            "Prompting",
            "Queued",
            "Rate limited",
            "Thinking",
        ):
            screen = "\n".join(
                [
                    f"  🌖 {label}…  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    "  ╭────────────────────────────────────────────╮",
                    "  │ >                                          │",
                    "  ╰────────────────────────────────────────────╯",
                ]
            )
            assert screen_shows_active_turn(AgentType.KIMI, screen), label

    def test_plan_mode_thinking_status_above_the_composer(self) -> None:
        screen = "\n".join(
            [
                "  ✨ list the files in this directory",
                "  ⠋ thinking…",
                "    The user asked a simple question…",
                "   ⠋ Thinking… · Tip: ask Kimi to schedule tasks",
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
                "  plan  K2.8 Preview thinking: max",
            ]
        )
        assert screen_shows_active_turn(AgentType.KIMI, screen)

    def test_lowercase_thinking_transcript_is_not_running(self) -> None:
        screen = "\n".join(
            [
                "  ⠋ thinking…",
                "    The user asked a simple question…",
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
                "  plan  K2.8 Preview thinking: max",
            ]
        )
        assert not screen_shows_active_turn(AgentType.KIMI, screen)

    def test_label_free_spinner_tip_above_the_composer(self) -> None:
        screen = "\n".join(
            [
                "  ● Running a command · $ curl -s -X POST …",
                '  ·· {"ok":true,"data":{}}',
                "  🌑 · Tip: @: mention files",
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
                "  Ask When Needed K2.8 Preview thinking: max",
            ]
        )
        assert screen_shows_active_turn(AgentType.KIMI, screen)

    def test_ascii_ellipsis_variant(self) -> None:
        screen = "\n".join(
            [
                "  🌗 Working...  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
            ]
        )
        assert screen_shows_active_turn(AgentType.KIMI, screen)

    def test_idle_composer_is_not_running(self) -> None:
        screen = "\n".join(
            [
                "  Report done.",
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
                "  Ask When Needed K3 thinking: max",
            ]
        )
        assert not screen_shows_active_turn(AgentType.KIMI, screen)

    def test_terminal_labels_are_not_running(self) -> None:
        for label in ("Completed.", "Failed.", "Aborted.", "Cancelled."):
            screen = "\n".join(
                [
                    f"  🌕 {label}",
                    "  ╭────────────────────────────────────────────╮",
                    "  │ >                                          │",
                    "  ╰────────────────────────────────────────────╯",
                ]
            )
            assert not screen_shows_active_turn(AgentType.KIMI, screen), label

    def test_transcript_echo_without_composer_is_ignored(self) -> None:
        screen = "\n".join(
            [
                '  • print("Working…")',
                "  transcript line",
                "  Ask When Needed K3 thinking: max",
            ]
        )
        assert not screen_shows_active_turn(AgentType.KIMI, screen)

    def test_label_above_the_footer_window_is_ignored(self) -> None:
        older = [f"  transcript line {index}" for index in range(30)]
        screen = "\n".join(
            [
                "  🌗 Working…  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                *older,
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
            ]
        )
        assert not screen_shows_active_turn(AgentType.KIMI, screen)

    def test_other_agents_ignore_the_kimi_label(self) -> None:
        screen = "\n".join(
            [
                "  🌗 Working…  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "  ╭────────────────────────────────────────────╮",
                "  │ >                                          │",
                "  ╰────────────────────────────────────────────╯",
            ]
        )
        assert not screen_shows_active_turn(AgentType.CODEX, screen)


class TestGetGitInfo:
    def test_non_git_dir(self) -> None:
        info = get_git_info("/tmp")
        assert info.repo == ""
        assert info.branch == ""
        assert info.root_repo == ""

    def test_empty_path(self) -> None:
        info = get_git_info("")
        assert info == GitInfo(repo="", branch="", root_repo="")

    def test_nonexistent_path(self) -> None:
        info = get_git_info("/nonexistent/path/that/does/not/exist")
        assert info.repo == ""

    def test_normal_repo(self, tmp_path: Path) -> None:
        """A normal git repo should return repo name, branch, and root_repo == toplevel."""
        repo_dir = tmp_path / "my-project"
        repo_dir.mkdir()
        repo = Repo.init(repo_dir)
        (repo_dir / "README.md").write_text("hello")
        repo.index.add(["README.md"])
        repo.index.commit("init")

        info = get_git_info(str(repo_dir))
        assert info.repo == "my-project"
        assert info.branch in ("master", "main")
        assert info.root_repo == str(repo_dir)

    def test_worktree_uses_main_repo_name(self, tmp_path: Path) -> None:
        """A worktree should report the main repo's name, not the worktree dir name."""
        main_dir = tmp_path / "my-project"
        main_dir.mkdir()
        repo = Repo.init(main_dir)
        (main_dir / "README.md").write_text("hello")
        repo.index.add(["README.md"])
        repo.index.commit("init")

        repo.git.branch("feature-branch")
        wt_dir = tmp_path / "20260401_worktree_feature"
        repo.git.worktree("add", str(wt_dir), "feature-branch")

        info = get_git_info(str(wt_dir))
        assert info.repo == "my-project"
        assert info.branch == "feature-branch"
        assert info.root_repo == str(main_dir)

    def test_subdirectory_of_repo(self, tmp_path: Path) -> None:
        """get_git_info from a subdirectory should still find the repo."""
        repo_dir = tmp_path / "my-project"
        sub_dir = repo_dir / "src" / "app"
        sub_dir.mkdir(parents=True)
        repo = Repo.init(repo_dir)
        (repo_dir / "README.md").write_text("hello")
        repo.index.add(["README.md"])
        repo.index.commit("init")

        info = get_git_info(str(sub_dir))
        assert info.repo == "my-project"

    def test_detached_head(self, tmp_path: Path) -> None:
        """Detached HEAD should return empty branch."""
        repo_dir = tmp_path / "my-project"
        repo_dir.mkdir()
        repo = Repo.init(repo_dir)
        (repo_dir / "README.md").write_text("hello")
        repo.index.add(["README.md"])
        commit = repo.index.commit("init")

        repo.head.reference = commit  # type: ignore[assignment]
        repo.head.reset(index=True, working_tree=True)

        info = get_git_info(str(repo_dir))
        assert info.repo == "my-project"
        assert info.branch == ""
