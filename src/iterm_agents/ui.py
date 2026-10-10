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
    -webkit-user-select: none;
    user-select: none;
  }
  input { -webkit-user-select: text; user-select: text; }
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
  .refresh-btn:disabled { opacity: 0.4; cursor: default; }
  .refresh-btn:disabled:hover { color: #888; border-color: #555; }
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
    position: sticky;
    top: 0;
    z-index: 1;
    background: #1e1e1e;
    font-size: 11px;
    font-weight: 600;
    color: #dcdcaa;
    padding: 4px 0 6px 0;
    border-bottom: 1px solid #333;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 5px;
  }
  .repo-header .chevron {
    color: #808080;
    font-size: 13px;
    line-height: 1;
  }
  .repo-header:hover .chevron { color: #d4d4d4; }
  .agent {
    position: relative;
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
  .agent.running { border-left-color: #d7ba7d; }
  .agent.awaiting-user { border-left-color: #4ec9b0; background: #1c332a; }
  .agent.awaiting-user:hover, .agent.awaiting-user.focused { background: #22402f; }
  .agent.idle { border-left-color: #555; }
  .agent-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .status { font-weight: bold; font-size: 11px; }
  .running .status { color: #d7ba7d; }
  .awaiting-user .status { color: #4ec9b0; }
  .idle .status { color: #808080; }
  .agent-type {
    font-size: 10px;
    padding: 1px 5px;
    border-radius: 3px;
    background: #3c3c3c;
    color: #aaa;
  }
  .agent-type.claude { background: #452c22; color: #e08a63; }
  .agent-type.codex { background: #1a3a5c; color: #61afef; }
  .agent-type.cursor { background: #2a2a4a; color: #b4b4f0; }
  .agent-type.devin { background: #3a2a4a; color: #d4a4e8; }
  .agent-type.kimi { background: #12233d; color: #5b87c9; }
  .label {
    font-size: 10px;
    padding: 1px 5px;
    border-radius: 3px;
    background: #3a3a28;
    color: #dcdcaa;
    max-width: 90px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .label-editor {
    position: absolute;
    top: 3px;
    left: 6px;
    right: 6px;
    z-index: 10;
  }
  .label-editor input {
    width: 100%;
    background: #252526;
    border: 1px solid #569cd6;
    border-radius: 4px;
    color: #d4d4d4;
    font-size: 11px;
    padding: 4px 6px;
    outline: none;
    box-shadow: 0 2px 8px rgba(0,0,0,0.5);
  }
  .ctx-menu {
    position: fixed;
    z-index: 20;
    min-width: 110px;
    padding: 3px 0;
    background: #252526;
    border: 1px solid #454545;
    border-radius: 4px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    outline: none;
  }
  .ctx-item {
    padding: 4px 12px;
    font-size: 11px;
    color: #d4d4d4;
    cursor: pointer;
    white-space: nowrap;
  }
  .ctx-item:hover { background: #094771; }
  .session-name { color: #d4d4d4; font-size: 11px; margin-top: 2px; }
  .branch-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 2px;
  }
  .branch {
    color: #ce9178;
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .action-hint { color: #4ec9b0; font-size: 10px; margin-top: 3px; }
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
    <span>
      <button class="refresh-btn" id="clear-all" title="Mark all done as read"
              onclick="clearAllDone()">&#10003;</button>
      <button class="refresh-btn" title="Collapse all"
              onclick="toggleCollapseAll()">&#8847;</button>
      <button class="refresh-btn" onclick="loadSessions()">&#8635;</button>
    </span>
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
    // Never steal focus from an open context menu or label editor.
    function focusSearch() {
      if (ctxMenu || labelEditorOpen) return;
      document.getElementById('search').focus({ preventScroll: true });
    }
    let hadFocus = document.hasFocus();
    window.addEventListener('focus', focusSearch);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) focusSearch();
    });
    setInterval(() => {
      const hasFocus = document.hasFocus();
      if (hasFocus && !hadFocus) focusSearch();
      hadFocus = hasFocus;
    }, 200);

    document.addEventListener('keydown', (e) => {
      // The context menu and label editor handle their own keys.
      if (ctxMenu || labelEditorOpen) return;
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

    // A refresh rewriting the row eats the click, so defer DOM writes until
    // the button is released. Click fires just after pointerup, so keep
    // suppressing briefly or a refresh in that gap still swallows the click.
    let pointerDown = false;
    let pointerSeq = 0;
    document.addEventListener('pointerdown', () => { pointerDown = true; pointerSeq++; }, true);
    document.addEventListener('pointerup', () => {
      const seq = pointerSeq;
      setTimeout(() => { if (pointerSeq === seq) pointerDown = false; }, 300);
    }, true);
    document.addEventListener('pointercancel', () => { pointerDown = false; }, true);

    // Collapsed repo keys; persists across the per-second re-render.
    const collapsedRepos = new Set();

    document.getElementById('sessions').addEventListener('click', (e) => {
      const header = e.target.closest('.repo-header');
      if (header) toggleGroup(header.parentElement.dataset.key);
    });

    // Right-click a card for its action menu. The menu and the label editor
    // both live outside the polling render's reach until dismissed.
    let ctxMenu = null;
    let labelEditorOpen = false;

    document.getElementById('sessions').addEventListener('contextmenu', (e) => {
      const card = e.target.closest('.agent');
      if (!card) return;
      e.preventDefault();
      openCtxMenu(card.dataset.session, e.clientX, e.clientY);
    });

    function openCtxMenu(sessionId, x, y) {
      closeCtxMenu();
      closeLabelEditor();
      const session = allSessions.find(s => s.id === sessionId);
      const items = [
        ['label', 'Label\u2026'],
        ['focus', 'Focus session'],
      ];
      if (session && session.agent_state === 'awaiting_user')
        items.push(['read', 'Mark as read']);
      const menu = document.createElement('div');
      menu.className = 'ctx-menu';
      for (const [action, text] of items) {
        const item = document.createElement('div');
        item.className = 'ctx-item';
        item.textContent = text;
        item.addEventListener('click', (e) => {
          e.stopPropagation();
          closeCtxMenu();
          if (action === 'label') openLabelEditor(sessionId);
          else if (action === 'focus') focusSession(sessionId);
          else markSessionRead(sessionId);
        });
        menu.appendChild(item);
      }
      document.body.appendChild(menu);
      menu.style.left = Math.min(x, window.innerWidth - menu.offsetWidth - 4) + 'px';
      menu.style.top = Math.min(y, window.innerHeight - menu.offsetHeight - 4) + 'px';
      // Focus the menu so the webview actually receives the Esc key — a
      // right-click alone does not move keyboard focus off the terminal.
      menu.tabIndex = -1;
      menu.focus({ preventScroll: true });
      ctxMenu = menu;
    }

    function closeCtxMenu() {
      if (ctxMenu) { ctxMenu.remove(); ctxMenu = null; }
    }

    // While a menu or the label editor is open, the first outside click is
    // spent dismissing it — captured here so it can't also jump to a session,
    // toggle a group, or hit a header button underneath.
    document.addEventListener('click', (e) => {
      if (ctxMenu) {
        if (ctxMenu.contains(e.target)) return;
        e.preventDefault();
        e.stopPropagation();
        closeCtxMenu();
      } else if (labelEditorOpen && !e.target.closest('.label-editor')) {
        e.preventDefault();
        e.stopPropagation();
        closeLabelEditor();
      }
    }, true);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeCtxMenu();
    });
    // Clicks outside the webview never reach the page; the window blur does.
    window.addEventListener('blur', closeCtxMenu);

    async function markSessionRead(sessionId) {
      try {
        await fetch('/api/clear?session=' + encodeURIComponent(sessionId));
      } catch(e) {}
      await loadSessions(true);
    }

    function openLabelEditor(sessionId) {
      const card = document.querySelector(`.agent[data-session="${sessionId}"]`);
      if (!card) return;
      closeLabelEditor();
      const session = allSessions.find(s => s.id === sessionId);
      const wrap = document.createElement('div');
      wrap.className = 'label-editor';
      const input = document.createElement('input');
      input.value = (session && session.label) || '';
      input.placeholder = 'Label\u2026';
      input.maxLength = 40;
      wrap.appendChild(input);
      wrap.addEventListener('click', e => e.stopPropagation());
      card.appendChild(wrap);
      labelEditorOpen = true;
      input.focus();
      input.select();
      input.addEventListener('keydown', (e) => {
        e.stopPropagation();
        if (e.key === 'Enter') saveLabel(sessionId, input.value.trim());
        else if (e.key === 'Escape') closeLabelEditor();
      });
      input.addEventListener('blur', () => setTimeout(closeLabelEditor, 100));
    }

    function closeLabelEditor() {
      const ed = document.querySelector('.label-editor');
      if (ed) ed.remove();
      labelEditorOpen = false;
    }

    async function saveLabel(sessionId, label) {
      try {
        await fetch('/api/label?session=' + encodeURIComponent(sessionId) +
                    '&label=' + encodeURIComponent(label));
      } catch(e) {}
      closeLabelEditor();
      await loadSessions(true);
    }

    function toggleGroup(key) {
      if (collapsedRepos.has(key)) collapsedRepos.delete(key);
      else collapsedRepos.add(key);
      filterSessions(true);
    }

    function toggleCollapseAll() {
      const keys = [...document.querySelectorAll('.repo-group')]
        .map(g => g.dataset.key);
      const expand = keys.every(k => collapsedRepos.has(k));
      for (const key of keys) {
        if (expand) collapsedRepos.delete(key);
        else collapsedRepos.add(key);
      }
      filterSessions(true);
    }

    let loadingSessions = false;

    async function loadSessions(force) {
      if (loadingSessions) return;
      loadingSessions = true;
      try {
        const res = await fetch('/api/sessions');
        allSessions = await res.json();
        filterSessions(force);
      } catch(e) {
        document.getElementById('sessions').innerHTML =
          '<div class="no-results">Failed to load sessions<br>' + esc(String(e)) + '</div>';
      } finally {
        loadingSessions = false;
      }
    }

    function filterSessions(force) {
      const q = document.getElementById('search').value.toLowerCase();
      const filtered = q
        ? allSessions.filter(s =>
            [s.name, s.repo, s.branch, s.path, s.agent_type, s.root_repo].some(
              v => v && v.toLowerCase().includes(q)
            ))
        : allSessions;
      focusedIndex = -1;
      renderSessions(filtered, force);
    }

    function renderSessions(sessions, force) {
      const container = document.getElementById('sessions');
      if (sessions.length === 0) {
        container.innerHTML = '<div class="no-results">No sessions found</div>';
        document.getElementById('count').textContent = '';
        document.getElementById('clear-all').disabled = true;
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

      // pointerDown suppresses stray interval writes mid-click; renders a
      // click handler asked for are safe — the click already dispatched.
      // An open context menu or label editor is also left untouched.
      if (force || (!pointerDown && !labelEditorOpen && !ctxMenu)) {
        container.innerHTML = html;
      }

      const running = sessions.filter(s => s.agent_state === 'running').length;
      const awaiting = sessions.filter(s => s.agent_state === 'awaiting_user').length;
      document.getElementById('clear-all').disabled = awaiting === 0;
      const withAgent = sessions.filter(s => s.agent_type).length;
      document.getElementById('count').textContent =
        `${running} running / ${awaiting} done / ` +
        `${withAgent} agents / ${sessions.length} sessions`;
    }

    function renderGroup(repoName, repoPath, items) {
      const sessionsHtml = items.map(s => {
        const meta = stateMeta(s.agent_state);
        const typeBadge = s.agent_type
          ? `<span class="agent-type ${s.agent_type}">${s.agent_type}</span>`
          : '';
        const labelTitle = s.label ? esc(s.label).replace(/"/g, '&quot;') : '';
        const labelChip = s.label
          ? `<span class="label" title="${labelTitle}">${esc(s.label)}</span>`
          : '';
        const nameLine = s.name && s.name !== s.path
          ? `<div class="session-name">${esc(s.name)}</div>`
          : '';
        const branchLine = s.branch || labelChip
          ? `<div class="branch-row">
               <span class="branch">${s.branch ? esc(s.branch) : ''}</span>
               ${labelChip}
             </div>`
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
          ${nameLine}
          ${branchLine}
          ${actionHint}
        </div>`;
      }).join('');

      const titleAttr = repoPath ? ` title="${esc(repoPath)}"` : '';
      const isCollapsed = collapsedRepos.has(repoPath);
      const chevron = isCollapsed ? '&#9656;' : '&#9662;';

      return `<div class="repo-group" data-key="${esc(repoPath).replace(/"/g, '&quot;')}">
        <div class="repo-header"${titleAttr}>
          <span>${esc(repoName)}</span>
          <span class="chevron">${chevron}</span>
        </div>
        ${isCollapsed ? '' : sessionsHtml}
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
          return { cls: 'awaiting-user', icon: '&#9670;', label: 'done' };
        case 'idle':
          return { cls: 'idle', icon: '&#9675;', label: 'idle' };
        default:
          return { cls: 'idle', icon: '&#9675;', label: state || 'no agent' };
      }
    }

    async function clearAllDone() {
      try {
        await fetch('/api/clear');
        await loadSessions(true);
      } catch(e) {}
    }

    async function focusSession(sessionId) {
      try {
        await fetch('/api/focus?session=' + encodeURIComponent(sessionId));
        await loadSessions(true);
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
