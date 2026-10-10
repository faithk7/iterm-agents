# iterm-agents

An iTerm2 toolbelt panel that lists coding agents running in terminal sessions.

This is a separate project derived from [it2ag](https://github.com/mkusaka/it2ag) by mkusaka (GPL-2.0). The panel, the session list, git grouping, click-to-focus, and the Claude Code and Codex activity signals come from that code. See [NOTICE](NOTICE).

## What it recognizes

| Agent | Process | Running |
| --- | --- | --- |
| Claude Code | executable name `claude` | a `caffeinate` child, the signal it2ag uses |
| Codex | executable name `codex` | a sandbox child, the IOKit assertion `Codex is running an active turn`, or the `(… esc to interrupt)` hint above its composer |
| Cursor Agent | `cursor-agent`, or `node` / `agent` whose command line contains both `/cursor-agent/` and `index.js` | a busy child, or a composer footer that says `ctrl+c to stop` and is still changing |
| Devin CLI | executable name `devin` | a busy child, or the `(esc … to interrupt)` hint above its input box |
| Kimi Code | executable name `kimi` or `kimi-code` | a busy child, or the `Working…` status label above its composer |

The Cursor editor (`Cursor.app`), the Kimi desktop app, and `kimi-cu` are not treated as these CLIs.

Cursor Agent launches as a private `node` binary, so a basename check of `node` would match every Node process. The command line has to point at that CLI's `index.js`. A bare `agent` process with no `cursor-agent` path is ignored, because other tools install a binary of that name.

Cursor Agent, Devin, and Kimi Code do not publish a turn signal the way Claude and Codex do. A live process with no sandbox or `caffeinate` child is shown as idle, including while the model is waiting on the network, unless the session's own footer says a turn is live. Cursor's composer counts as running while `ctrl+c to stop` is on screen and the visible screen is still changing. The braille spinner does not count. A footer that stays the same is idle, so a status line Cursor never clears does not keep the session marked running. Devin's status line counts as running while it shows the `esc twice to interrupt` hint above the input box; the hint is redrawn in place and disappears when the turn ends, so no staleness check is needed. Codex's status line works the same way: `esc to interrupt` above the `›` composer means a live turn. That covers Codex launches with sandboxing bypassed, where no sandbox child ever appears and recent Codex builds no longer raise the IOKit assertion. Kimi Code counts as running while its status line shows an in-progress label — `Working…`, `Prompting…`, `Orchestrating…`, `Queued…`, `Rate limited…` or `Thinking…` — above the composer box; the terminal labels (`Completed.`, `Failed.`, `Aborted.`, `Cancelled.`) do not count.

## Run

iTerm2 needs **Settings → General → Magic → Enable Python API**. Shell Integration supplies the working directory used for the repo and branch.

```bash
uv sync
uv run iterm-agents
```

The panel is named **Agents**. `Cmd+Shift+M` focuses its search box. Click a row to jump to that pane.

```bash
uv run iterm-agents --install-autolaunch
```

That writes `~/Library/Application Support/iTerm2/Scripts/AutoLaunch/iterm-agents.py`, which is separate from it2ag's autolaunch script.

## License

GPL-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
