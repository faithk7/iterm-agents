"""Classify agent processes and infer activity from their descendants.

Derived from it2ag by mkusaka (https://github.com/mkusaka/it2ag), GPL-2.0.
Process snapshots, screen signals, and Git metadata live in separate modules.
Claude Code and Codex retain it2ag's process and power-assertion signals.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
from collections import deque

from iterm_agents.git_info import get_git_info
from iterm_agents.models import AgentInfo, AgentState, AgentType, GitInfo, ProcessInfo
from iterm_agents.processes import build_process_table as _build_process_table
from iterm_agents.screen_signals import (
    CURSOR_FOOTER_STALE_SECONDS,
    codex_screen_shows_active_turn,
    cursor_activity_signature,
    cursor_turn_is_live,
    devin_screen_shows_active_turn,
    kimi_screen_shows_active_turn,
    screen_shows_active_turn,
)

# Keep existing public detector imports working while implementation lives
# in modules that own each responsibility. New code imports those directly.
__all__ = [
    "CURSOR_FOOTER_STALE_SECONDS",
    "AgentInfo",
    "AgentState",
    "AgentType",
    "GitInfo",
    "ProcessInfo",
    "codex_screen_shows_active_turn",
    "cursor_activity_signature",
    "cursor_turn_is_live",
    "detect_agents",
    "devin_screen_shows_active_turn",
    "get_git_info",
    "kimi_screen_shows_active_turn",
    "screen_shows_active_turn",
]

_BUSY_CHILD_NAMES = frozenset({"caffeinate", "sandbox-exec", "bwrap", "codex-linux-sandbox"})


def _build_children(table: dict[int, ProcessInfo]) -> dict[int, list[ProcessInfo]]:
    """Index child processes once per process-table snapshot."""
    children: dict[int, list[ProcessInfo]] = {}
    for proc in table.values():
        children.setdefault(proc.ppid, []).append(proc)
    return children


def _get_descendants(children: dict[int, list[ProcessInfo]], pid: int) -> list[ProcessInfo]:
    """Get all descendants of a process (BFS)."""
    descendants: list[ProcessInfo] = []
    queue: deque[int] = deque([pid])
    visited: set[int] = {pid}
    while queue:
        current = queue.popleft()
        for child in children.get(current, []):
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
    """The first token of a command line — the invoked program, minus args."""
    command = command.strip()
    if not command:
        return ""
    return command.split(None, 1)[0]


def _executable_name(command: str) -> str:
    """The executable's basename, e.g. ``claude`` from ``/opt/x/claude -v``."""
    return _comm_basename(_executable_token(command))


def _is_claude_process(command: str) -> bool:
    """True for the Claude Code CLI."""
    return _executable_name(command) == "claude"


def _is_codex_process(command: str) -> bool:
    """True for the Codex CLI."""
    return _executable_name(command) == "codex"


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


# The Kimi Code CLI sets its process name to `kimi-code`. The desktop app is
# `Kimi` and the computer-use helper is `kimi-cu`; neither is this CLI.
_EXECUTABLE_AGENT_TYPES = {
    "claude": AgentType.CLAUDE,
    "codex": AgentType.CODEX,
    "devin": AgentType.DEVIN,
    "kimi": AgentType.KIMI,
    "kimi-code": AgentType.KIMI,
}


def _classify(command: str) -> AgentType | None:
    """Map a command line to an agent type, or None for everything else."""
    agent_type = _EXECUTABLE_AGENT_TYPES.get(_executable_name(command))
    if agent_type is not None:
        return agent_type
    if _is_cursor_agent(command):
        return AgentType.CURSOR
    return None


def _is_agent_process(command: str) -> bool:
    """True when the command belongs to a recognized agent."""
    return _classify(command) is not None


def _has_busy_child(children: dict[int, list[ProcessInfo]], pid: int) -> bool:
    """True when a sandbox or sleep-prevention descendant marks a live turn."""
    for descendant in _get_descendants(children, pid):
        if _executable_name(descendant.command) in _BUSY_CHILD_NAMES:
            return True
    return False


def _detect_claude_state(children: dict[int, list[ProcessInfo]], pid: int) -> AgentState:
    """Claude Code spawns caffeinate when running a turn."""
    for descendant in _get_descendants(children, pid):
        if _executable_name(descendant.command) == "caffeinate":
            return AgentState.RUNNING
    return AgentState.IDLE


def _get_codex_active_pids() -> set[int] | None:
    """Get PIDs of codex processes that are actively running a turn.

    Parses macOS `pmset -g assertions` output which includes per-process
    IOKit power assertions. Codex creates an assertion with the reason
    "Codex is running an active turn" when executing a turn.
    None means the assertion read failed; an empty set is a valid idle result.
    """
    try:
        result = subprocess.run(
            ["pmset", "-g", "assertions"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return None
    except Exception:
        return None

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


def _detect_codex_state(children: dict[int, list[ProcessInfo]], pid: int) -> AgentState:
    """Detect codex running state via sandbox child processes.

    Falls back to IOKit assertion check via detect_agents for batch detection.
    """
    descendants = _get_descendants(children, pid)
    for descendant in descendants:
        name = _executable_name(descendant.command)
        if name in ("sandbox-exec", "bwrap", "codex-linux-sandbox"):
            return AgentState.RUNNING
    return AgentState.IDLE


def _detect_busy_child_state(children: dict[int, list[ProcessInfo]], pid: int) -> AgentState:
    """Cursor Agent, Devin, and Kimi Code have no published turn signal.

    A sleep-prevention or sandbox child means a turn is doing work. With no
    such child the session is listed as idle even if the model is waiting on
    the network.
    """
    if _has_busy_child(children, pid):
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
        if _classify(parent.command) is not None:
            return True
        current = parent.ppid
    return False


def detect_agents(session_pids: set[int] | None = None) -> list[AgentInfo]:
    """Detect coding-agent processes.

    Args:
        session_pids: If provided, only return agents that are descendants
                      of these PIDs (iTerm2 session shell PIDs).
    """
    table = _build_process_table(session_pids)
    children = _build_children(table)
    agents: list[AgentInfo] = []
    # Lazily fetched: `pmset` spawns a subprocess, so skip it entirely on
    # scans where no codex process exists.
    codex_active_pids: set[int] | None = None
    codex_assertions_read = False

    for proc in table.values():
        agent_type = _classify(proc.command)
        if agent_type is None or _has_agent_ancestor(table, proc.pid):
            continue

        if agent_type is AgentType.CLAUDE:
            state = _detect_claude_state(children, proc.pid)
        elif agent_type is AgentType.CODEX:
            state = _detect_codex_state(children, proc.pid)
            # IOKit assertion is per-PID and authoritative
            if not codex_assertions_read:
                codex_active_pids = _get_codex_active_pids()
                codex_assertions_read = True
            if codex_active_pids is not None and proc.pid in codex_active_pids:
                state = AgentState.RUNNING
            elif codex_active_pids is None and state is AgentState.IDLE:
                state = AgentState.UNKNOWN
        else:
            state = _detect_busy_child_state(children, proc.pid)

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
