# iterm-agents

[简体中文](README.md) | [English](README.en.md)

![iterm-agents: Five agents. One view. Know what's running. Jump to what's finished.](docs/promo-iterm-agents.png)

An iTerm2 toolbelt panel that watches your terminal sessions and shows which
coding agents are running — Claude Code, Codex, Cursor Agent, Devin, and Kimi
Code — so you can see at a glance which turn is still working and which just
finished, then click through to that pane.

![The full iTerm2 window with terminal panes and the Agents toolbelt on the right](docs/iterm-window.png)

## Supported agents

| Agent        | Detected process                                     |
| ------------ | ---------------------------------------------------- |
| Claude Code  | `claude`                                             |
| Codex        | `codex`                                              |
| Cursor Agent | `cursor-agent` (or `node`/`agent` on its `index.js`) |
| Devin CLI    | `devin`                                              |
| Kimi Code    | `kimi` / `kimi-code`                                 |

## What you get

- **An Agents panel in every window** — opened in each existing window at
  launch and in each new window when you first activate it; background scans
  never switch window focus, and a toolbelt you hide by hand stays hidden.
- **Live state per session** — `running` while a turn is live, `done` when one
  just finished, `idle` otherwise.
- **Repo grouping** — sessions group under their git repo, with worktrees
  folding into the main repo; groups collapse individually or all at once.
- **Jump to a session** — click a row to focus that pane.
- **Search** — filter sessions by name, repo, branch, or agent type.

Everything stays on your Mac. The monitor reads local processes, git
repositories, and the visible text of your iTerm2 sessions; it serves the panel
only on `127.0.0.1` and sends nothing over the network.

## Requirements

- **macOS with [iTerm2](https://iterm2.com/)**, open while the monitor runs.
- iTerm2's **Python API** and **Shell Integration** enabled
  ([steps below](#set-up-iterm2)).
- **Git** for repo information and manual cloning. If `git --version` fails,
  run `xcode-select --install`, finish Apple's Command Line Tools installation,
  then retry.
- Python ≥ 3.10. The quick installer sets up Python and
  **[uv](https://docs.astral.sh/uv/getting-started/installation/)** for you.
- At least one supported agent CLI, installed and signed in separately.
  iterm-agents monitors your existing CLIs; it does not install or launch them.

## Quick start

### Set up iTerm2

Both install methods need these settings. Open iTerm2: press `Cmd+Space`, type
`iTerm`, and press `Enter`. If you have not installed it yet, download it from
[iterm2.com](https://iterm2.com/) and move it into **Applications**. Then:

1. **Enable the Python API** — press `Cmd+,`, open **General → Magic**, and
   tick **Enable Python API**. Restart iTerm2 if it asks.
2. **Enable Shell Integration** — choose **iTerm2 → Install Shell
   Integration**, follow the prompts, and open a new tab with `Cmd+T`. It
   reports each session's working directory for repo/branch labels and
   grouping. On iTerm2 3.5+, you can instead enable **Settings → Profiles →
   General → Command → Load shell integration automatically** for a supported
   login shell. See
   [iTerm2's Shell Integration guide](https://iterm2.com/documentation-shell-integration.html).

### macOS installer (recommended)

Paste this command into an iTerm2 tab:

```bash
curl -fsSL https://raw.githubusercontent.com/faithk7/iterm-agents/main/install.sh | bash
```

The [installer](install.sh) downloads the project, reuses uv or installs it
without changing your shell profiles, sets up Python 3.12 and the monitor's
dependencies, and installs the AutoLaunch wrapper. It installs under
`~/.local/share/iterm-agents` and requires no Homebrew or `sudo`.

When it finishes, quit and reopen iTerm2. The **Agents** panel should appear in
the toolbelt. If it is hidden, choose **View → Show Toolbelt**.

To start the installed monitor manually:

```bash
"$HOME/.local/share/iterm-agents/venv/bin/iterm-agents"
```

Rerun the installer command to update, then restart the monitor to load the
new version. Keep its installation folder in place for AutoLaunch to work.

If you already have a checkout, you can install your local version with:

```bash
bash install.sh --source .
```

Use `--no-autolaunch` for manual startup only. If an existing wrapper differs,
the installer will stop rather than overwrite it; use `--force-autolaunch`
when you intend to replace it. For example:

```bash
bash install.sh --source . --no-autolaunch
bash install.sh --source . --force-autolaunch
```

Run `bash install.sh --help` for all options, including a custom install folder.

### Manual setup with uv

Finish [Set up iTerm2](#set-up-iterm2) first. Keep the checkout in a location
you plan to keep if you want automatic startup later. Run the terminal commands
below inside iTerm2.

1. **Install uv** if you do not already have it. With Homebrew:

   ```bash
   brew install uv
   ```

   Without Homebrew, follow the
   [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).

2. **Clone, install, and start the monitor:**

   ```bash
   git clone https://github.com/faithk7/iterm-agents.git
   cd iterm-agents
   uv sync
   uv run iterm-agents
   ```

   Keep this command running in its tab or pane. Press `Ctrl+C` there to stop
   the monitor. To start it again, run `uv run iterm-agents` from the checkout.

The **Agents** panel opens in each window's toolbelt. If it is hidden, use
**View → Show Toolbelt**.

### Alternative: venv and pip

If you prefer pip, use a `python3` interpreter at version 3.10 or newer.
This is a complete alternative to the uv commands above:

```bash
git clone https://github.com/faithk7/iterm-agents.git
cd iterm-agents
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/iterm-agents
```

You do not need to activate the virtual environment. For later commands,
replace `uv run iterm-agents` with `.venv/bin/iterm-agents`.

## Check that it works

1. If you started the monitor in a terminal, it should print something like:

   ```text
   iterm-agents: running (http://127.0.0.1:50123/)
   iterm-agents: Ctrl+C to stop
   ```

   The port is chosen automatically and may differ from this example. With
   automatic startup there is no terminal to watch: the **Agents** panel
   appearing is the check, and `pgrep -fl iterm-agents` lists the running
   monitor.

2. Press `Cmd+T` to open another tab, change into a git repository, and launch
   a supported CLI you already use, such as `claude` or `codex`.

3. Find that session in **Agents**. You should see its agent badge and, with
   Shell Integration active, its repo/branch information.

4. Submit a prompt and watch the status change to **running**, then **done**
   when the monitor observes the turn ending. Click its row to focus that pane
   and clear the done mark. Detection depends on the signals described below.

## Automatic startup

The macOS installer sets up AutoLaunch by default. The commands below are for
manual installations; installer users can replace `uv run iterm-agents` with
`"$HOME/.local/share/iterm-agents/venv/bin/iterm-agents"`.

After checking that manual startup works, press `Ctrl+C` in the monitor's
terminal, then install the AutoLaunch wrapper from the checkout:

```bash
uv run iterm-agents --install-autolaunch
```

For the pip setup, use `.venv/bin/iterm-agents --install-autolaunch`.
Then quit and reopen iTerm2. You can now use the panel without keeping a
dedicated monitor tab open.

The wrapper is written to
`~/Library/Application Support/iTerm2/Scripts/AutoLaunch/iterm-agents.py`,
separate from it2ag's autolaunch script. Only one monitor instance runs at a
time; starting another prints `iterm-agents: already running` and exits.

The uv setup records the checkout's absolute path; the pip setup records the
installed executable's absolute path. Keep the checkout and `.venv` in place.
If you move them, recreate the virtual environment at its new location and
reinstall the wrapper with:

```bash
uv run iterm-agents --install-autolaunch --force
```

Use `--force` only when you intend to replace the existing wrapper. The same
command updates an older wrapper to use the current installation.

### Disable automatic startup

Remove this project's wrapper:

```bash
rm "$HOME/Library/Application Support/iTerm2/Scripts/AutoLaunch/iterm-agents.py"
```

Removing it prevents future automatic launches; it does not stop an already
running monitor. Quit and reopen iTerm2 after removing it. You can still start
the monitor manually with the command from the quick start.

## Uninstall

Remove the AutoLaunch wrapper as shown above, stop the monitor, then delete the
installation:

```bash
pkill -f 'bin/iterm-agents'
rm -rf "$HOME/.local/share/iterm-agents"
```

Use your own folder if you installed with `--install-dir`; for a manual setup,
delete the checkout instead. uv may also keep a downloaded Python and a cache
under `~/.local/share/uv` and `~/.cache/uv`; remove those only if nothing else
uses uv.

## Usage

- Each row shows a color-coded agent badge and a status: **running**, **done**,
  or **idle**. A row with no detected agent shows its session name only.
- **Done** means the monitor observed a transition from running to idle. It
  does not confirm success; check the agent's output for failures or questions.
  A turn that ended before the monitor started will not have a done mark.
- Click a row to jump to that terminal pane; a done row's mark clears on click.
- Each window's panel marks that window's active pane with a blue bar.
  Switching windows doesn't move other panels' markers or scroll positions.
- Right-click a card for its menu: label it, focus it, or mark it read.
  Labels show as a chip in the card's top row and last until the session or
  the monitor exits.
- Header buttons: `✓` marks every done session as read, `⊏` collapses or
  expands all repo groups, `↻` refreshes.
- `Cmd+Shift+M` opens the toolbelt in the current window and focuses search.

With the panel focused, you can navigate without the mouse:

| Key       | Action                                                                           |
| --------- | -------------------------------------------------------------------------------- |
| `↑` / `↓` | Move between visible session rows; `↑` from the first row returns to search      |
| `Enter`   | Focus the selected terminal pane                                                 |
| `Escape`  | Return to search and select its text; close an open context menu or label editor |

Search matches session names, repo names, branches, paths, and agent types.

## Troubleshooting

| Symptom                                                       | What to check                                                                                                                                                                        |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `uv: command not found`                                       | Install uv using the quick start, then open a new terminal tab if the installer changed your `PATH`.                                                                                 |
| Installer says Git is not ready                               | Run `xcode-select --install`, complete Apple's Command Line Tools installation, and rerun the installer.                                                                             |
| Installer refuses an unmanaged directory                      | Choose another dedicated folder with `--install-dir`; the installer protects existing folders it did not create.                                                                     |
| Cannot connect to iTerm2                                      | Keep iTerm2 open and enable **Settings → General → Magic → Enable Python API**. Restart iTerm2 if requested.                                                                         |
| Agents panel is missing                                       | Bring iTerm2 to the foreground and use **View → Show Toolbelt** or `Cmd+Shift+M`. Check that the monitor printed `running`.                                                          |
| Repo or branch is missing                                     | Enable Shell Integration for that session's profile/shell, open a new tab, and change into a git repository. A session outside a repo has no repo/branch label.                      |
| Session appears without an agent badge                        | Run a supported CLI in that iTerm2 pane. Detection scans local processes; an agent running on a remote host over SSH is not detected. Desktop apps are excluded.                     |
| Agent stays idle while working, or done appears early         | Activity detection uses process and screen hints, which can vary by CLI version. Screen hints currently match English UI text. See **How detection works** below.                    |
| `iterm-agents: already running`                               | A monitor is already active, possibly through AutoLaunch. Use its panel; stop the manual instance with `Ctrl+C` in its terminal before launching another.                            |
| `Failed to load sessions`                                     | `TypeError: Load failed` means the monitor is not running; check with `pgrep -fl iterm-agents`. Otherwise check its terminal for errors. Restart it, then use the panel's `↻` button. |
| Blue marker missing in a panel                                | Make that window the active iTerm2 window once, or click inside its panel. The panel then follows that window's active pane.                                                         |
| AutoLaunch does not start                                     | Try manual startup first. Check that the saved checkout/executable and `.venv` still exist. Reinstall the wrapper with `--install-autolaunch --force` from the working installation. |
| Wrapper installation says the file already exists and differs | Inspect the wrapper at the path printed in the error. Use `--force` if you intend to replace it.                                                                                     |

To inspect the available commands or report your version:

```bash
uv run iterm-agents --help
uv run iterm-agents --version
```

The local server selects an available port by default. If you need a fixed
port, use `uv run iterm-agents --port 50123`; choose an unused port.

## How detection works

Sessions are matched by the processes in [Supported agents](#supported-agents).
A session counts as **running** when:

| Agent        | Running signal                                                                           |
| ------------ | ---------------------------------------------------------------------------------------- |
| Claude Code  | a `caffeinate` child, the signal it2ag uses                                              |
| Codex        | a sandbox child, the IOKit assertion `Codex is running an active turn`, or a screen hint |
| Cursor Agent | a busy child, or a screen hint                                                           |
| Devin CLI    | a busy child, or a screen hint                                                           |
| Kimi Code    | a busy child, or a screen hint                                                           |

Not treated as CLIs: the Cursor editor (`Cursor.app`), the Kimi desktop app,
and `kimi-cu`. Cursor Agent runs as a private `node` binary, so its command
line must contain both `/cursor-agent/` and `index.js`; a bare `agent` process
with no such path is ignored.

Cursor Agent, Devin, and Kimi Code publish no turn signal like Claude's or
Codex's, so with no busy child they fall back to the session's screen. Each
hint must appear above the live composer, so transcript echoes don't match.
All hints are English UI text; a localized build may not be detected. The
screen hints are:

- **Cursor** — `ctrl+c to stop` in the composer while the screen keeps
  changing; the spinner alone keeps a quiet stall alive. A footer frozen for
  30 seconds counts as finished.
- **Devin** — `esc twice/again to interrupt` above the input box.
- **Codex** — `esc to interrupt` above the `›` composer or `? for shortcuts`
  footer; covers sandbox-disabled launches where no child or assertion appears.
  The panel waits for about three seconds of idle before showing **done**, so
  brief pauses keep showing **running**.
- **Kimi** — a `Working…`/`Prompting…`/`Orchestrating…`/`Queued…`/
  `Rate limited…`/`Thinking…` status label, or a bare spinner + `· Tip:` line
  while a tool runs. `Completed.`/`Failed.`/`Aborted.`/`Cancelled.` don't
  count.

## Development

```bash
uv run pytest            # tests
uv run ruff check src/   # lint
uv run mypy src/         # typecheck (src/ only; tests use fakes)
```

`uv sync` installs the project editable, so code in `src/` is picked up after
restarting the monitor.

See [Python architecture](docs/architecture.md) for module responsibilities,
the observation-to-display flow, and cache/focus state rules.

## Acknowledgements

[it2ag](https://github.com/mkusaka/it2ag) by
[@mkusaka](https://github.com/mkusaka) — the project this is derived from.
Its process scan, toolbelt panel, session list, git and worktree grouping,
click-to-focus, and the Claude Code and Codex activity signals are reused
here; the Cursor Agent, Devin, and Kimi Code detection is new. See
[NOTICE](NOTICE).

## License

GPL-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
