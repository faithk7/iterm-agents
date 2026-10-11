# Python architecture

The monitor observes existing iTerm2 sessions, infers agent activity, and
serves a local panel. Modules follow those responsibilities:

| Module | Responsibility |
| --- | --- |
| `__main__.py` | CLI arguments, single-instance lock, iTerm2 event-loop entry |
| `autolaunch.py` | Render and install the independent startup wrapper |
| `models.py` | Shared agent/process/Git types and the `SessionRow` JSON contract |
| `processes.py` | Blocking process snapshots via macOS libproc or `ps` |
| `detector.py` | Process classification, ancestry, and process/assertion activity signals |
| `screen_signals.py` | Pure parsers for activity hints anchored to live composers |
| `git_info.py` | Best-effort repository metadata and main-repo worktree grouping |
| `session_state.py` | Completion confirmation, acknowledgements, and session labels |
| `server.py` | HTTP/event transport, scan/cache orchestration, and iTerm2 focus/toolbelt integration |
| `ui.py` | Embedded HTML, CSS, and JavaScript for the panel |

New code imports types and helpers from their owning modules. `detector.py`
continues to re-export its existing public types and signal helpers for
compatibility. The shared models have no iTerm2 or GitPython imports, and screen
parsers do no I/O.

## From observation to display

1. The server snapshots iTerm2's window/tab/pane layout and reads session shell
   PIDs and directories. Scan RPCs share a semaphore so they do not flood the
   connection used by focus requests.
2. Process detection and Git reads run through `asyncio.to_thread`. They return
   values; mutable server state stays on the iTerm2 event loop.
3. The detector associates agent processes with session shells by ancestry.
   Idle or unknown agents can gain running evidence from their visible screen.
   Cursor also tracks whether its screen signature has changed recently.
4. The server caches the completed scan. Each response copies those rows before
   the state tracker adds labels and completion marks. Focus flags are scoped
   to the requesting panel's window.

The session API uses string values for agent types and states. `running`,
`idle`, and `unknown` are observation states; `awaiting_user` is a display state
for an observed completion that has not been acknowledged. It does not imply
that the turn succeeded. Labels and acknowledgements live only in memory.

## State rules to preserve

- A fresh successful scan can advance completion state; a cached poll cannot.
  `observed_at` is the scan's monotonic timestamp, not the response time.
- Codex must remain idle for the confirmation interval across fresh scans.
  Unknown observations and failed scans reset that interval while retaining
  the previous display state. A replaced agent PID starts new tracking.
- A failed scan is different from a successful empty scan. An initial failure
  returns HTTP 503; a later failure serves the previous snapshot. A successful
  scan prunes tracking for sessions that have disappeared.
- Focus notifications can arrive while scans await RPCs. The focus epoch and
  preserved layout maps keep a newer pane or tab event from being overwritten
  by an older snapshot. Each window remembers its own selected pane.
- Toolbelts are opened once per window. Background scans do not activate other
  windows, and manually hidden toolbelts stay hidden.
- Screen hints are tied to live composers because transcript text can quote
  the same hints. A Cursor footer that stops changing eventually expires.

## Validation and future boundaries

Run `uv run pytest`, `uv run ruff check src/`,
`uv run ruff format --check src/`, and `uv run mypy src/`.
Tests for process snapshots, screen signals, and Git metadata sit in matching
test modules. Server tests exercise cached/fresh observations, failed scans,
focus races, and panel event routing. The native WebKit transport test requires
macOS and clang; the native process test requires macOS.

The next larger refactor would separate layout/focus tracking and panel event
clients from `AgentMonitorServer`. Keep the ordering rules above explicit at
those boundaries. HTTP runner and background-task shutdown also deserve a
single lifecycle owner before adding restart support. Moving the embedded UI
into resource files would require checking both wheel and executable packaging.
