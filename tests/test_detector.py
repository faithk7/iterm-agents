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
    _comm_basename,
    _detect_claude_state,
    _detect_codex_state,
    _find_ancestor_pid,
    _get_children,
    _get_codex_active_pids,
    _get_descendants,
    _is_agent_process,
    _is_claude_process,
    _is_codex_process,
    detect_agents,
    get_git_info,
)


def _make_table(procs: list[tuple[int, int, str]]) -> dict[int, ProcessInfo]:
    return {pid: ProcessInfo(pid=pid, ppid=ppid, comm=comm) for pid, ppid, comm in procs}


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


class TestGetChildren:
    def test_direct_children(self) -> None:
        table = _make_table(
            [
                (1, 0, "init"),
                (10, 1, "bash"),
                (20, 1, "zsh"),
                (30, 10, "claude"),
            ]
        )
        children = _get_children(table, 1)
        pids = {c.pid for c in children}
        assert pids == {10, 20}

    def test_no_children(self) -> None:
        table = _make_table([(10, 1, "bash")])
        children = _get_children(table, 10)
        assert children == []


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
        desc = _get_descendants(table, 20)
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
        desc = _get_descendants(table, 20)
        pids = {d.pid for d in desc}
        assert pids == {30, 40, 50}

    def test_no_descendants(self) -> None:
        table = _make_table([(20, 10, "claude")])
        desc = _get_descendants(table, 20)
        assert desc == []

    def test_nonexistent_pid(self) -> None:
        table = _make_table([(20, 10, "claude")])
        desc = _get_descendants(table, 999)
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
        assert _detect_claude_state(table, 20) == AgentState.RUNNING

    def test_idle_without_caffeinate(self) -> None:
        table = _make_table(
            [
                (20, 10, "claude"),
            ]
        )
        assert _detect_claude_state(table, 20) == AgentState.IDLE

    def test_running_with_deep_caffeinate(self) -> None:
        table = _make_table(
            [
                (20, 10, "claude"),
                (30, 20, "node"),
                (40, 30, "caffeinate"),
            ]
        )
        assert _detect_claude_state(table, 20) == AgentState.RUNNING

    def test_idle_with_unrelated_children(self) -> None:
        table = _make_table(
            [
                (20, 10, "claude"),
                (30, 20, "node"),
                (40, 20, "python"),
            ]
        )
        assert _detect_claude_state(table, 20) == AgentState.IDLE


class TestDetectCodexState:
    def test_running_with_sandbox(self) -> None:
        table = _make_table(
            [
                (20, 10, "codex"),
                (30, 20, "sandbox-exec"),
            ]
        )
        assert _detect_codex_state(table, 20) == AgentState.RUNNING

    def test_running_with_bwrap(self) -> None:
        table = _make_table(
            [
                (20, 10, "codex"),
                (30, 20, "bwrap"),
            ]
        )
        assert _detect_codex_state(table, 20) == AgentState.RUNNING

    def test_running_with_linux_sandbox(self) -> None:
        table = _make_table(
            [
                (20, 10, "codex"),
                (30, 20, "codex-linux-sandbox"),
            ]
        )
        assert _detect_codex_state(table, 20) == AgentState.RUNNING

    def test_idle_without_sandbox(self) -> None:
        table = _make_table(
            [
                (20, 10, "codex"),
            ]
        )
        assert _detect_codex_state(table, 20) == AgentState.IDLE

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
        assert _detect_codex_state(table, 20) == AgentState.IDLE


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
        assert _detect_claude_state(table, 20) == AgentState.RUNNING


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
