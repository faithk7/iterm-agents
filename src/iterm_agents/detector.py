"""Agent process detection.

Derived from it2ag by mkusaka (https://github.com/mkusaka/it2ag), GPL-2.0.
Claude Code and Codex keep that project's signals. Cursor Agent, Devin CLI,
and Kimi Code are matched from the executable path, because those programs
do not share Claude's or Codex's process names.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from git import InvalidGitRepositoryError, Repo


class AgentType(Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    CURSOR = "cursor"
    DEVIN = "devin"
    KIMI = "kimi"


class AgentState(Enum):
    RUNNING = "running"
    IDLE = "idle"


@dataclass
class ProcessInfo:
    pid: int
    ppid: int
    comm: str


@dataclass
class AgentInfo:
    agent_type: AgentType
    state: AgentState
    pid: int
    session_pid: int | None = None


_BUSY_CHILD_NAMES = frozenset({"caffeinate", "sandbox-exec", "bwrap", "codex-linux-sandbox"})


def _build_process_table() -> dict[int, ProcessInfo]:
    """Build a process table from ps output.

    `command` includes arguments. Cursor Agent's on-disk launcher is a shell
    wrapper that execs a private `node` binary, so the executable basename
    alone is not enough to tell it from any other Node process.
    """
    result = subprocess.run(
        ["ps", "-axww", "-o", "pid,ppid,command"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        return {}

    table: dict[int, ProcessInfo] = {}
    for line in result.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        table[pid] = ProcessInfo(pid=pid, ppid=ppid, comm=parts[2].strip())
    return table


def _get_children(table: dict[int, ProcessInfo], pid: int) -> list[ProcessInfo]:
    """Get all direct children of a process."""
    return [p for p in table.values() if p.ppid == pid]


def _get_descendants(table: dict[int, ProcessInfo], pid: int) -> list[ProcessInfo]:
    """Get all descendants of a process (BFS)."""
    descendants: list[ProcessInfo] = []
    queue = [pid]
    visited: set[int] = {pid}
    while queue:
        current = queue.pop(0)
        for child in _get_children(table, current):
            if child.pid not in visited:
                visited.add(child.pid)
                descendants.append(child)
                queue.append(child.pid)
    return descendants


def _find_ancestor_pid(
    table: dict[int, ProcessInfo], pid: int, target_pids: set[int]
) -> int | None:
    """Walk up the process tree to find if any target_pid is an ancestor."""
    visited: set[int] = set()
    current = pid
    while current > 1 and current not in visited:
        visited.add(current)
        if current in target_pids:
            return current
        proc = table.get(current)
        if proc is None:
            break
        current = proc.ppid
    return None


def _comm_basename(comm: str) -> str:
    """Extract the basename from a comm string (may be a full path)."""
    return os.path.basename(comm)


def _executable_token(command: str) -> str:
    command = command.strip()
    if not command:
        return ""
    return command.split(None, 1)[0]


def _executable_name(command: str) -> str:
    return _comm_basename(_executable_token(command))


def _is_claude_process(comm: str) -> bool:
    return _executable_name(comm) == "claude"


def _is_codex_process(comm: str) -> bool:
    return _executable_name(comm) == "codex"


def _is_cursor_agent(command: str) -> bool:
    """Match the Cursor Agent CLI, not the Cursor editor.

    The installed command is `cursor-agent` (and sometimes `agent`). It execs
    `.../cursor-agent/versions/<version>/node` with `index.js` from that same
    directory. The editor process lives in Cursor.app and is ignored.
    """
    if "Cursor.app" in command:
        return False
    name = _executable_name(command)
    if name == "cursor-agent":
        return True
    if "/cursor-agent/" not in command or "index.js" not in command:
        return False
    return name in {"node", "agent", "cursor-agent"}


def _classify(command: str) -> AgentType | None:
    name = _executable_name(command)
    if name == "claude":
        return AgentType.CLAUDE
    if name == "codex":
        return AgentType.CODEX
    if name == "devin":
        return AgentType.DEVIN
    if name == "kimi":
        return AgentType.KIMI
    if _is_cursor_agent(command):
        return AgentType.CURSOR
    return None


def _is_agent_process(comm: str) -> bool:
    return _classify(comm) is not None


def _has_busy_child(table: dict[int, ProcessInfo], pid: int) -> bool:
    for descendant in _get_descendants(table, pid):
        if _executable_name(descendant.comm) in _BUSY_CHILD_NAMES:
            return True
    return False


def _detect_claude_state(table: dict[int, ProcessInfo], pid: int) -> AgentState:
    """Claude Code spawns caffeinate when running a turn."""
    for descendant in _get_descendants(table, pid):
        if _executable_name(descendant.comm) == "caffeinate":
            return AgentState.RUNNING
    return AgentState.IDLE


def _get_codex_active_pids() -> set[int]:
    """Get PIDs of codex processes that are actively running a turn.

    Parses macOS `pmset -g assertions` output which includes per-process
    IOKit power assertions. Codex creates an assertion with the reason
    "Codex is running an active turn" when executing a turn.
    """
    try:
        result = subprocess.run(
            ["pmset", "-g", "assertions"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return set()
    except Exception:
        return set()

    active_pids: set[int] = set()
    lines = result.stdout.splitlines()
    for line in lines:
        # Lines look like: "   pid 90513(codex-aarch64-apple-darwin): [0x...] ... named: "...""
        if "Codex is running an active turn" in line:
            # Extract PID from "pid NNNN(" pattern
            for part in line.split():
                if part.startswith("pid"):
                    continue
                # The token after "pid" is "NNNN(name):"
                paren = part.find("(")
                if paren > 0:
                    with contextlib.suppress(ValueError):
                        active_pids.add(int(part[:paren]))
                    break
    return active_pids


def _detect_codex_state(table: dict[int, ProcessInfo], pid: int) -> AgentState:
    """Detect codex running state via sandbox child processes.

    Falls back to IOKit assertion check via detect_agents for batch detection.
    """
    descendants = _get_descendants(table, pid)
    for descendant in descendants:
        name = _executable_name(descendant.comm)
        if name in ("sandbox-exec", "bwrap", "codex-linux-sandbox"):
            return AgentState.RUNNING
    return AgentState.IDLE


def _detect_busy_child_state(table: dict[int, ProcessInfo], pid: int) -> AgentState:
    """Cursor Agent, Devin, and Kimi Code have no published turn signal.

    A sleep-prevention or sandbox child means a turn is doing work. With no
    such child the session is listed as idle even if the model is waiting on
    the network.
    """
    if _has_busy_child(table, pid):
        return AgentState.RUNNING
    return AgentState.IDLE


def _has_agent_ancestor(table: dict[int, ProcessInfo], pid: int) -> bool:
    """True when a parent process is itself a recognized agent.

    Cursor Agent's node process can spawn more node processes. Those children
    are the same session, not extra agents.
    """
    visited: set[int] = set()
    proc = table.get(pid)
    if proc is None:
        return False
    current = proc.ppid
    while current > 1 and current not in visited:
        visited.add(current)
        parent = table.get(current)
        if parent is None:
            break
        if _classify(parent.comm) is not None:
            return True
        current = parent.ppid
    return False


def detect_agents(session_pids: set[int] | None = None) -> list[AgentInfo]:
    """Detect coding-agent processes.

    Args:
        session_pids: If provided, only return agents that are descendants
                      of these PIDs (iTerm2 session shell PIDs).
    """
    table = _build_process_table()
    agents: list[AgentInfo] = []
    # Batch-fetch codex active PIDs from IOKit assertions (one pmset call)
    codex_active_pids = _get_codex_active_pids()

    for proc in table.values():
        agent_type = _classify(proc.comm)
        if agent_type is None or _has_agent_ancestor(table, proc.pid):
            continue

        if agent_type is AgentType.CLAUDE:
            state = _detect_claude_state(table, proc.pid)
        elif agent_type is AgentType.CODEX:
            state = _detect_codex_state(table, proc.pid)
            # IOKit assertion is per-PID and authoritative
            if proc.pid in codex_active_pids:
                state = AgentState.RUNNING
        else:
            state = _detect_busy_child_state(table, proc.pid)

        session_pid: int | None = None
        if session_pids:
            session_pid = _find_ancestor_pid(table, proc.pid, session_pids)
            if session_pid is None:
                continue  # not in any known session

        agents.append(
            AgentInfo(
                agent_type=agent_type,
                state=state,
                pid=proc.pid,
                session_pid=session_pid,
            )
        )

    return agents


@dataclass
class GitInfo:
    repo: str
    branch: str
    root_repo: str


def get_git_info(path: str) -> GitInfo:
    """Get git repo name, branch, and root repo path for a directory.

    For worktrees, root_repo points to the main repository's toplevel,
    so sessions in different worktrees of the same repo get grouped together.
    """
    empty = GitInfo(repo="", branch="", root_repo="")
    if not path or not os.path.isdir(path):
        return empty
    try:
        repo = Repo(path, search_parent_directories=True)
    except (InvalidGitRepositoryError, Exception):
        return empty

    try:
        toplevel = str(repo.working_tree_dir or "")
        repo_name = os.path.basename(toplevel) if toplevel else ""

        branch = ""
        if not repo.head.is_detached:
            branch = repo.active_branch.name

        # Resolve root repo for worktree grouping.
        # repo.common_dir points to the shared .git dir (same for all worktrees).
        # For normal repos: /path/to/repo/.git
        # For worktrees: /path/to/main-repo/.git (the main repo's git dir)
        root_repo = toplevel
        common_dir = Path(repo.common_dir).resolve()
        if common_dir != Path(repo.git_dir).resolve():
            # This is a worktree; common_dir is the main repo's .git
            root_repo = str(common_dir.parent)
            # Use the main repo's name, not the worktree directory name
            repo_name = os.path.basename(root_repo)

        return GitInfo(repo=repo_name, branch=branch, root_repo=root_repo)
    except Exception:
        return empty
