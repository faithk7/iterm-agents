# Applying changes to the running panel

After editing `src/iterm_agents/`, the Agents panel keeps running the old code until the monitor is reinstalled and restarted. Do both yourself; the user does not need to quit iTerm2.

1. Run the tests: `uv run pytest -q`
2. Reinstall from this checkout: `bash install.sh --source .` (installs to `~/.local/share/iterm-agents`; keeps the existing AutoLaunch wrapper)
3. Restart the monitor:
   ```
   pkill -f 'bin/iterm-agents$'
   nohup ~/.local/share/iterm-agents/venv/bin/iterm-agents >/tmp/iterm-agents.log 2>&1 &
   ```
   Check with `ps -axo pid,command | grep '[i]term-agents'`. The old process may run from the repo's `.venv` instead of the installed copy; the `pkill` pattern covers both.
