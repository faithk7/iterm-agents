# iterm-agents

An iTerm2 toolbelt panel that lists coding agents running in terminal sessions.

This is a separate project derived from [it2ag](https://github.com/mkusaka/it2ag) by mkusaka (GPL-2.0). The panel, the session list, git grouping, click-to-focus, and the Claude Code and Codex activity signals come from that code. See [NOTICE](NOTICE).

## What it recognizes

| Agent | Process | Running |
| --- | --- | --- |
| Claude Code | executable name `claude` | a `caffeinate` child, the signal it2ag uses |
| Codex | executable name `codex` | a sandbox child, or the IOKit assertion `Codex is running an active turn` |
| Cursor Agent | `cursor-agent`, or `node` / `agent` whose command line contains both `/cursor-agent/` and `index.js` | a busy child, or a visible footer that says `Running … tokens` or `ctrl+c to stop` |
| Devin CLI | executable name `devin` | the same busy-child rule |
| Kimi Code | executable name `kimi` or `kimi-code` | the same busy-child rule |

The Cursor editor (`Cursor.app`), the Kimi desktop app, and `kimi-cu` are not treated as these CLIs.

Cursor Agent launches as a private `node` binary, so a basename check of `node` would match every Node process. The command line has to point at that CLI's `index.js`. A bare `agent` process with no `cursor-agent` path is ignored, because other tools install a binary of that name.

Cursor Agent, Devin, and Kimi Code do not publish a turn signal the way Claude and Codex do. A live process with no sandbox or `caffeinate` child is shown as idle, including while the model is waiting on the network.

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
