"""HTML UI template for the Toolbelt WebView."""

from __future__ import annotations

AGENT_MONITOR_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 12px;
    padding: 8px;
    background: #1e1e1e;
    color: #d4d4d4;
  }
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
  }
  .title { font-size: 13px; font-weight: 600; color: #569cd6; }
  .refresh-btn {
    background: none; border: 1px solid #555; color: #888;
    border-radius: 3px; padding: 2px 6px; cursor: pointer; font-size: 11px;
  }
  .refresh-btn:hover { color: #d4d4d4; border-color: #888; }
  .search-box {
    width: 100%;
    padding: 5px 8px;
    margin-bottom: 8px;
    background: #2d2d2d;
    border: 1px solid #444;
    border-radius: 4px;
    color: #d4d4d4;
    font-size: 12px;
    outline: none;
  }
  .search-box:focus { border-color: #569cd6; }
  .search-box::placeholder { color: #666; }

  .repo-group { margin-bottom: 10px; }
  .repo-header {
    font-size: 11px;
    font-weight: 600;
    color: #dcdcaa;
    padding: 4px 0 2px 0;
    border-bottom: 1px solid #333;
    margin-bottom: 4px;
    cursor: default;
  }
  .agent {
    padding: 5px 8px;
    margin: 3px 0;
    border-radius: 4px;
    background: #2d2d2d;
    border-left: 3px solid #808080;
    cursor: pointer;
    transition: background 0.15s;
    outline: none;
  }
  .agent:hover, .agent.focused { background: #383838; }
  .agent.focused { outline: 1px solid #569cd6; }
  .agent.running { border-left-color: #4ec9b0; }
  .agent.awaiting-user { border-left-color: #d7ba7d; background: #332a1c; }
  .agent.awaiting-user:hover, .agent.awaiting-user.focused { background: #423520; }
  .agent.idle { border-left-color: #555; }
  .agent-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .status { font-weight: bold; font-size: 11px; }
  .running .status { color: #4ec9b0; }
  .awaiting-user .status { color: #d7ba7d; }
  .idle .status { color: #808080; }
  .agent-type {
    font-size: 10px;
    padding: 1px 5px;
    border-radius: 3px;
    background: #3c3c3c;
    color: #aaa;
  }
  .agent-type.claude { background: #2a3a4a; color: #7cb3d4; }
  .agent-type.codex { background: #2a4a2a; color: #7cd47c; }
  .agent-type.cursor { background: #2a2a4a; color: #b4b4f0; }
  .agent-type.devin { background: #3a2a4a; color: #d4a4e8; }
  .agent-type.kimi { background: #4a3a2a; color: #e8c49a; }
  .session-name { color: #d4d4d4; font-size: 11px; margin-top: 2px; }
  .branch { color: #ce9178; font-size: 11px; margin-top: 2px; }
  .path { color: #6a9955; font-size: 10px; margin-top: 1px; }
  .action-hint { color: #d7ba7d; font-size: 10px; margin-top: 3px; }
  .count {
    font-size: 11px;
    color: #808080;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid #333;
  }
  .no-results {
    color: #666;
    font-style: italic;
    padding: 16px 0;
    text-align: center;
  }
</style>
</head>
<body>
  <div class="header">
    <span class="title">Agents</span>
    <button class="refresh-btn" onclick="loadSessions()">&#8635;</button>
  </div>
  <input type="text" class="search-box" id="search"
         placeholder="Search by name, repo, branch..."
         oninput="filterSessions()">
  <div id="sessions"></div>
  <div class="count" id="count"></div>

  <script>
    let allSessions = [];
    let focusedIndex = -1;

    // Auto-focus search input when the Toolbelt panel gets focus.
    // Use multiple strategies since embedded WebViews may not fire focus events.
    let hadFocus = document.hasFocus();
    window.addEventListener('focus', () => {
      document.getElementById('search').focus();
    });
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) document.getElementById('search').focus();
    });
    setInterval(() => {
      const hasFocus = document.hasFocus();
      if (hasFocus && !hadFocus) {
        document.getElementById('search').focus();
      }
      hadFocus = hasFocus;
    }, 200);

    document.addEventListener('keydown', (e) => {
      const items = getAgentElements();
      const search = document.getElementById('search');

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (items.length === 0) return;
        focusedIndex = Math.min(focusedIndex + 1, items.length - 1);
        updateFocus(items);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (focusedIndex <= 0) {
          // Go back to search box
          focusedIndex = -1;
          clearFocus(items);
          search.focus();
        } else {
          focusedIndex--;
          updateFocus(items);
        }
      } else if (e.key === 'Enter' && focusedIndex >= 0 && focusedIndex < items.length) {
        e.preventDefault();
        items[focusedIndex].click();
      } else if (e.key === 'Escape') {
        focusedIndex = -1;
        clearFocus(items);
        search.focus();
        search.select();
      }
    });

    function getAgentElements() {
      return [...document.querySelectorAll('.agent')];
    }

    function updateFocus(items) {
      clearFocus(items);
      if (focusedIndex >= 0 && focusedIndex < items.length) {
        items[focusedIndex].classList.add('focused');
        items[focusedIndex].scrollIntoView({ block: 'nearest' });
        // Remove focus from search so arrow keys don't move cursor
        document.getElementById('search').blur();
      }
    }

    function clearFocus(items) {
      for (const el of items) el.classList.remove('focused');
    }

    let loadingSessions = false;

    async function loadSessions() {
      if (loadingSessions) return;
      loadingSessions = true;
      try {
        const res = await fetch('/api/sessions');
        allSessions = await res.json();
        filterSessions();
      } catch(e) {
        document.getElementById('sessions').innerHTML =
          '<div class="no-results">Failed to load sessions</div>';
      } finally {
        loadingSessions = false;
      }
    }

    function filterSessions() {
      const q = document.getElementById('search').value.toLowerCase();
      const filtered = q
        ? allSessions.filter(s =>
            [s.name, s.repo, s.branch, s.path, s.agent_type, s.root_repo].some(
              v => v && v.toLowerCase().includes(q)
            ))
        : allSessions;
      focusedIndex = -1;
      renderSessions(filtered);
    }

    function renderSessions(sessions) {
      const container = document.getElementById('sessions');
      if (sessions.length === 0) {
        container.innerHTML = '<div class="no-results">No sessions found</div>';
        document.getElementById('count').textContent = '';
        return;
      }

      // Group by root_repo
      const groups = new Map();
      const noRepo = [];
      for (const s of sessions) {
        const key = s.root_repo || '';
        if (!key) { noRepo.push(s); continue; }
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(s);
      }

      // Sort groups: groups with running agents first
      const sortedKeys = [...groups.keys()].sort((a, b) => {
        const aRun = groups.get(a).some(s => statePriority(s.agent_state) <= 1) ? 0 : 1;
        const bRun = groups.get(b).some(s => statePriority(s.agent_state) <= 1) ? 0 : 1;
        if (aRun !== bRun) return aRun - bRun;
        return a.localeCompare(b);
      });

      let html = '';
      for (const key of sortedKeys) {
        const items = groups.get(key);
        const repoName = items[0].repo || key.split('/').pop() || key;
        html += renderGroup(repoName, key, items);
      }
      if (noRepo.length > 0) {
        html += renderGroup('(no repo)', '', noRepo);
      }

      container.innerHTML = html;

      const running = sessions.filter(s => s.agent_state === 'running').length;
      const awaiting = sessions.filter(s => s.agent_state === 'awaiting_user').length;
      const withAgent = sessions.filter(s => s.agent_type).length;
      document.getElementById('count').textContent =
        `${running} running / ${awaiting} awaiting / ` +
        `${withAgent} agents / ${sessions.length} sessions`;
    }

    function renderGroup(repoName, repoPath, items) {
      const sessionsHtml = items.map(s => {
        const meta = stateMeta(s.agent_state);
        const typeBadge = s.agent_type
          ? `<span class="agent-type ${s.agent_type}">${s.agent_type}</span>`
          : '';
        const branchLine = s.branch
          ? `<div class="branch">${esc(s.branch)}</div>`
          : '';
        const pathLine = s.path
          ? `<div class="path">${esc(s.path)}</div>`
          : '';
        const actionHint = s.awaiting_user
          ? '<div class="action-hint">Click to clear</div>'
          : '';
        return `<div class="agent ${meta.cls}" data-session="${s.id}"
                     onclick="focusSession('${s.id}')">
          <div class="agent-top">
            <span class="status">${meta.icon} ${meta.label}</span>
            ${typeBadge}
          </div>
          <div class="session-name">${esc(s.name || '(unnamed)')}</div>
          ${branchLine}
          ${pathLine}
          ${actionHint}
        </div>`;
      }).join('');

      const titleAttr = repoPath ? ` title="${esc(repoPath)}"` : '';

      return `<div class="repo-group">
        <div class="repo-header"${titleAttr}>
          <span>${esc(repoName)}</span>
        </div>
        ${sessionsHtml}
      </div>`;
    }

    function esc(str) {
      const d = document.createElement('div');
      d.textContent = str;
      return d.innerHTML;
    }

    function statePriority(state) {
      switch (state) {
        case 'running': return 0;
        case 'awaiting_user': return 1;
        case 'idle': return 2;
        default: return 3;
      }
    }

    function stateMeta(state) {
      switch (state) {
        case 'running':
          return { cls: 'running', icon: '&#9679;', label: 'running' };
        case 'awaiting_user':
          return { cls: 'awaiting-user', icon: '&#9670;', label: 'awaiting user' };
        case 'idle':
          return { cls: 'idle', icon: '&#9675;', label: 'idle' };
        default:
          return { cls: 'idle', icon: '&#9675;', label: state || 'no agent' };
      }
    }

    async function focusSession(sessionId) {
      try {
        await fetch('/api/focus?session=' + encodeURIComponent(sessionId));
        await loadSessions();
      } catch(e) {}
    }

    loadSessions();
    setInterval(loadSessions, 1000);

    // SSE: listen for focus events from the Python side (Cmd+Shift+M)
    function connectSSE() {
      const es = new EventSource('/api/events');
      es.addEventListener('focus-search', () => {
        const search = document.getElementById('search');
        search.focus();
        search.select();
        focusedIndex = -1;
        clearFocus(getAgentElements());
      });
      es.onerror = () => {
        es.close();
        setTimeout(connectSSE, 3000);
      };
    }
    connectSSE();

    // Focus search on initial load
    document.getElementById('search').focus();
  </script>
</body>
</html>"""
