"""Shared agent, process, Git, and session payload types.

This module has no OS or iTerm2 dependencies so signal parsers and display
state can use the same vocabulary without importing the detector.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypedDict


class AgentType(Enum):
    """The coding agents this monitor recognizes."""

    CLAUDE = "claude"
    CODEX = "codex"
    CURSOR = "cursor"
    DEVIN = "devin"
    KIMI = "kimi"


class AgentState(Enum):
    """Whether an agent is mid-turn, waiting, or could not be observed."""

    RUNNING = "running"
    IDLE = "idle"
    UNKNOWN = "unknown"


@dataclass
class ProcessInfo:
    """A process row: pid, parent pid, and command line or fallback name."""

    pid: int
    ppid: int
    command: str


@dataclass
class AgentInfo:
    """A detected agent process and the iTerm2 session shell it belongs to."""

    agent_type: AgentType
    state: AgentState
    pid: int
    session_pid: int | None = None


@dataclass
class GitInfo:
    """Repo display info: name, checked-out branch, and main repo path."""

    repo: str
    branch: str
    root_repo: str


class _SessionMetadata(TypedDict):
    id: str
    window_id: str
    name: str
    path: str
    repo: str
    branch: str
    root_repo: str
    agent_type: str
    agent_pid: int
    agent_state: str
    pid: int
    focused: bool


class SessionRow(_SessionMetadata, total=False):
    """JSON row shared by scans, display-state tracking, and the panel.

    Scans fill the metadata fields. SessionStateTracker adds the optional
    display fields to a copy; it may replace agent_state with awaiting_user.
    Path fields are abbreviated for display rather than filesystem access.
    """

    label: str
    awaiting_user: bool
