"""Pure screen-text signals for live agent turns.

Hints must belong to the live composer, because transcripts can quote the
same text. These parsers provide evidence of activity; completion timing
and acknowledgements belong to SessionStateTracker.
"""

from __future__ import annotations

from iterm_agents.models import AgentType

# A frozen "Running N tokens" footer is a finished turn whose status line
# never cleared. Real generation changes this signature every few seconds.
CURSOR_FOOTER_STALE_SECONDS = 30.0


def screen_shows_active_turn(agent_type: AgentType, screen_text: str) -> bool:
    """True when the agent's composer footer shows a live turn."""
    if agent_type is AgentType.CURSOR:
        return cursor_activity_signature(screen_text) is not None
    if agent_type is AgentType.DEVIN:
        return devin_screen_shows_active_turn(screen_text)
    if agent_type is AgentType.CODEX:
        return codex_screen_shows_active_turn(screen_text)
    if agent_type is AgentType.KIMI:
        return kimi_screen_shows_active_turn(screen_text)
    return False


def codex_screen_shows_active_turn(screen_text: str) -> bool:
    """True while Codex's status line shows the interrupt hint.

    A running turn draws ``Working (<elapsed> • esc to interrupt)`` on the
    line above the composer. The hint is redrawn in place, so it only exists
    on screen while the turn is live. Anchoring it to the composer prompt
    or the shortcuts footer below keeps transcript echoes of the same
    string from matching; not every composer variant draws the same
    prompt character.
    """
    lines = screen_text.splitlines()
    for index in range(len(lines) - 1, max(len(lines) - 13, -1), -1):
        if "esc to interrupt)" not in lines[index]:
            continue
        for lookahead in range(index + 1, min(index + 9, len(lines))):
            stripped = lines[lookahead].lstrip()
            if stripped.startswith("\u203a") or "? for shortcuts" in stripped:
                return True
    return False


_KIMI_BUSY_LABELS = (
    "Working",
    "Prompting",
    "Orchestrating",
    "Queued",
    "Rate limited",
    "Thinking",
)

_KIMI_BUSY_NEEDLES = tuple(
    f"{label}{suffix}" for label in _KIMI_BUSY_LABELS for suffix in ("…", "...")
)


def kimi_screen_shows_active_turn(screen_text: str) -> bool:
    """True while Kimi's status line shows an in-progress label.

    A live turn draws ``Working…`` (or Prompting/Orchestrating/Queued/
    Rate limited/Thinking, all ending in an ellipsis) above the composer
    box;
    while a tool runs the label is empty and the status line shows only
    the spinner and its rotating `` · Tip:`` hint. Finished turns end
    with ``Completed.``, ``Failed.`` and friends. The status line is
    redrawn in place, so it only exists on screen while the turn is
    live. Anchoring it to the composer box underneath keeps transcript
    echoes of the same label from matching.
    """
    lines = screen_text.splitlines()
    for index in range(len(lines) - 1, max(len(lines) - 24, -1), -1):
        line = lines[index]
        if "· Tip:" not in line and not any(needle in line for needle in _KIMI_BUSY_NEEDLES):
            continue
        for lookahead in range(index + 1, min(index + 16, len(lines))):
            if lines[lookahead].lstrip().startswith(("╭", "│")):
                return True
    return False


def devin_screen_shows_active_turn(screen_text: str) -> bool:
    """True while Devin's status line shows the interrupt hint.

    A running turn draws ``<activity> · <elapsed> (esc twice to interrupt)``
    on the line directly above the input box. The hint is redrawn in place,
    so it only exists on screen while the turn is live. Anchoring it to the
    box border underneath keeps transcript echoes of the same string from
    matching.
    """
    lines = screen_text.splitlines()
    for index in range(len(lines) - 2, max(len(lines) - 12, -1), -1):
        line = lines[index]
        if "esc" in line and "to interrupt)" in line and lines[index + 1].lstrip().startswith("──"):
            return True
    return False


def cursor_activity_signature(screen_text: str) -> str | None:
    """Stable id of an in-progress Cursor turn, or None when the footer is idle.

    The live signal is ``ctrl+c to stop`` inside the composer box. A
    ``Running N tokens`` line left above that box after the turn ends does
    not count. The signature is the visible screen with insignificant
    spacing dropped. The animated spinner stays in it: during a quiet
    thinking or reconnect stall it is the only thing still moving, and a
    leftover footer frozen after the turn ends does not move at all.
    """
    footer = _cursor_footer_lines(screen_text)
    if not any("ctrl+c to stop" in line for line in footer):
        return None
    return _normalize_cursor_screen(screen_text)


def _normalize_cursor_screen(screen_text: str) -> str:
    """Drop insignificant spacing."""
    lines = (" ".join(line.split()) for line in screen_text.splitlines())
    return "\n".join(line for line in lines if line)


def cursor_turn_is_live(
    signature: str | None,
    previous: str | None,
    age_seconds: float,
    *,
    stale_after: float = CURSOR_FOOTER_STALE_SECONDS,
) -> bool:
    """A footer that still says stop, but has not changed, is a finished turn."""
    if signature is None:
        return False
    if previous != signature:
        return True
    return age_seconds < stale_after


def _cursor_footer_lines(screen_text: str) -> list[str]:
    """The composer box and the status line directly above it."""
    lines = [line.rstrip() for line in screen_text.splitlines()]
    box = next((index for index, line in enumerate(lines) if "▄▄▄" in line), None)
    if box is None:
        return [line.strip() for line in lines if line.strip()][-8:]
    start = box
    previous = box - 1
    while previous >= 0 and not lines[previous].strip():
        previous -= 1
    if previous >= 0:
        start = previous
    return [line.strip() for line in lines[start:] if line.strip()]
