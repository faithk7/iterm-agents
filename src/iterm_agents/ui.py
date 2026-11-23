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
  .focus-hint {
    display: block;
    width: 100%;
    margin-bottom: 8px;
    padding: 5px 8px;
    border: 1px solid #444;
    border-radius: 4px;
    background: transparent;
    color: #569cd6;
    font: inherit;
    font-size: 11px;
    text-align: left;
    cursor: pointer;
  }
  .focus-hint[hidden] { display: none; }
  .connection-status { color: #d7ba7d; margin-bottom: 8px; font-size: 11px; }
  .connection-status[hidden], #group-status:empty { display: none; }
  /* WebKit resolves :window-inactive from this WebView's own NSWindow, so the
     probe's scrollbar width reveals whether the panel's window is key. */
  #owner-probe {
    position: fixed; left: -100px; top: 0;
    width: 50px; height: 50px; overflow: scroll;
    contain: strict;
  }
  #owner-probe::-webkit-scrollbar { width: 1px; }
  #owner-probe::-webkit-scrollbar:window-inactive { width: 2px; }

  /* Hand is scoped to card groups: a stale hit-test after click resolves to
     the group, keeping the pointer a hand over cards only, not page margins. */
  .repo-group { margin-bottom: 10px; cursor: pointer; }
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
  .custom-group {
    margin: 5px 0 5px 5px;
    padding-left: 6px;
    border-left: 2px solid var(--group-color);
  }
  .custom-group-header {
    position: relative;
    display: flex;
    align-items: center;
    gap: 3px;
    color: var(--group-color);
  }
  .group-toggle, .menu-trigger {
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }
  .group-toggle {
    display: flex;
    flex: 1;
    align-items: center;
    gap: 4px;
    min-width: 0;
    padding: 5px 2px;
    text-align: left;
    font-size: 11px;
    font-weight: 600;
  }
  .group-name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .group-summary {
    margin-left: auto;
    color: #aaa;
    font-size: 10px;
    font-weight: 400;
    white-space: nowrap;
  }
  .menu-trigger, .drag-handle {
    color: #aaa;
    padding: 0 3px;
    line-height: 1.35;
  }
  .menu-trigger:hover, .drag-handle:hover { color: #fff; }
  .drag-handle { cursor: grab; -webkit-user-drag: element; }
  .card-actions { display: flex; align-items: center; gap: 3px; }
  .drop-target { outline: 1px solid #569cd6; outline-offset: 1px; }
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
  /* The session shown in a window's current tab gets a bar just left of the
     card, so it stays visible under the state's border color. */
  .agent.current::before {
    content: '';
    position: absolute;
    left: -6px;
    top: 4px;
    bottom: 4px;
    width: 3px;
    border-radius: 2px;
    background: #569cd6;
  }
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
  .agent-type.qodercn { background: #14351e; color: #4ade80; }
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
    max-width: calc(100vw - 8px);
    max-height: calc(100vh - 8px);
    overflow: auto;
  }
  .ctx-item {
    display: block;
    width: 100%;
    border: none;
    background: transparent;
    text-align: left;
    padding: 4px 12px;
    font-size: 11px;
    color: #d4d4d4;
    cursor: pointer;
    overflow-wrap: anywhere;
  }
  .ctx-item:hover, .ctx-item:focus-visible { background: #094771; }
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
         placeholder="Search sessions and groups…"
         oninput="searchSessions()">
  <button class="focus-hint" id="focus-hint" onclick="bindPanelWindow()"
          aria-live="polite">Click here to enable the blue focus marker</button>
  <div id="owner-probe" aria-hidden="true"><div style="height: 100px"></div></div>
  <div class="connection-status" id="connection-status" role="status" hidden></div>
  <div class="connection-status" id="group-status" role="status"></div>
  <div id="sessions"><div class="no-results">Loading sessions…</div></div>
  <div class="count" id="count"></div>

  <script>
    let allSessions = [];
    let focusedIndex = -1;
    // The browsing-context name survives reloads and belongs to this WebView.
    // localStorage/cookies would share ownership between different panels.
    const panelWindowPrefix = 'iterm-agents:window:';
    let panelWindowId = typeof window.name === 'string' &&
      window.name.startsWith(panelWindowPrefix)
      ? window.name.slice(panelWindowPrefix.length) : '';
    document.getElementById('focus-hint').hidden = !!panelWindowId;
    let bindingWindow = null;
    let panelFocusEpoch = 0;
    let eventsSource = null;

    // Bound the entire request, including JSON decoding. The deadline also
    // releases callers if a stalled transport fails to honour cancellation.
    async function panelRequest(url, json = false, options = {}) {
      const controller = new AbortController();
      let timer;
      try {
        return await Promise.race([
          (async () => {
            const response = await fetch(url, {...options, signal: controller.signal});
            if (response.ok === false) throw new Error('HTTP ' + response.status);
            return json ? {response, data: await response.json()} : response;
          })(),
          new Promise((resolve, reject) => {
            timer = setTimeout(() => {
              controller.abort();
              reject(new Error('Request timed out'));
            }, 8000);
          }),
        ]);
      } finally {
        clearTimeout(timer);
      }
    }

    function connectionStatus(message) {
      const status = document.getElementById('connection-status');
      if (status.textContent !== message) status.textContent = message;
      if (status.hidden !== !message) status.hidden = !message;
    }

    function panelUrl(path) {
      return panelWindowId ? path + '?window=' + encodeURIComponent(panelWindowId) : path;
    }

    // Passing stillOwner marks a background attempt: it may recheck a bound
    // panel and stays silent, since the next activation retries anyway.
    async function bindPanelWindow(stillOwner) {
      if (panelWindowId && !stillOwner) return true;
      if (bindingWindow) return bindingWindow;
      const hint = document.getElementById('focus-hint');
      if (!stillOwner) hint.textContent = 'Connecting focus marker…';
      const epoch = panelFocusEpoch;
      bindingWindow = (async () => {
        try {
          const {data} = await panelRequest('/api/panel-window', true);
          // WKWebView's hasFocus() can stay false after a real click. A blur
          // during the handshake, rather than that flag, invalidates ownership.
          if (!data.window_id || epoch !== panelFocusEpoch ||
              (stillOwner && !stillOwner())) return false;
          if (data.window_id === panelWindowId) return true;
          panelWindowId = data.window_id;
          window.name = panelWindowPrefix + panelWindowId;
          hint.hidden = true;
          connectEvents();
          loadSessions();
          return true;
        } catch(e) {
          return false;
        }
      })();
      try {
        return await bindingWindow;
      } finally {
        bindingWindow = null;
        if (!panelWindowId && !stillOwner) {
          hint.textContent = 'Focus connection failed. Click here to retry.';
        }
      }
    }

    // Unlike hasFocus(), this needs no click: it reads only whether the
    // panel's own window is key, so other panels' windows cannot claim it.
    function ownerWindowIsKey() {
      const probe = document.getElementById('owner-probe');
      // WebKit re-resolves the scrollbar style only when it is rebuilt.
      probe.style.overflow = 'hidden';
      void probe.offsetWidth;
      probe.style.overflow = '';
      return probe.offsetWidth - probe.clientWidth === 1;
    }
    // WebKit drops a rule it cannot parse. Without :window-inactive every
    // panel would read as key and claim the current window, so leave binding
    // to clicks instead.
    const ownerProbeSupported = [...document.styleSheets].some(sheet =>
      [...sheet.cssRules].some(rule => (rule.selectorText || '').includes(':window-inactive')));
    let ownerWasKey = false;
    let lastOwnerProbeAt = -Infinity;
    function checkOwnerWindow() {
      if (document.hidden || !ownerProbeSupported || bindingWindow) return;
      // First binding stays fast; afterwards this only repairs ownership.
      // Pane markers arrive over the event connection and never wait on the scrollbar probe.
      const now = Date.now();
      if (now - lastOwnerProbeAt < (panelWindowId ? 1000 : 250)) return;
      lastOwnerProbeAt = now;
      const isKey = ownerProbeSupported && ownerWindowIsKey();
      // Unbound panels retry while key; bound ones recheck once per
      // activation so a wrong binding corrects itself.
      if (isKey && (!panelWindowId || !ownerWasKey)) bindPanelWindow(ownerWindowIsKey);
      ownerWasKey = isKey;
    }
    setInterval(checkOwnerWindow, 250);

    // Auto-focus search input when the Toolbelt panel gets focus.
    // Use multiple strategies since embedded WebViews may not fire focus events.
    // Never steal focus from an open context menu or label editor.
    function focusSearch() {
      if (pointerDown || ctxMenu || labelEditorOpen || dragSession) return;
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
      bindPanelWindow();
      // The context menu and label editor handle their own keys.
      if (ctxMenu || labelEditorOpen) return;
      if (e.key === 'Enter' && e.target?.closest?.('button')) return;
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
    let pressedX = '';
    let pressedY = '';
    let pressedAt = 0;
    let activatedOnPress = false;
    document.addEventListener('pointerdown', (e) => {
      bindPanelWindow();
      pointerDown = true;
      const seq = ++pointerSeq;
      // Window changes can interrupt pointerup/click in the Toolbelt WebView.
      // Bound the render guard even when the release event never arrives.
      setTimeout(() => { if (pointerSeq === seq) pointerDown = false; }, 1000);
      const card = e.target.closest && e.target.closest('.agent');
      pressedX = Number.isFinite(e.clientX) ? String(e.clientX) : '';
      pressedY = Number.isFinite(e.clientY) ? String(e.clientY) : '';
      pressedAt = Date.now();
      activatedOnPress = !!card && !ctxMenu && !labelEditorOpen && e.button === 0 &&
        !e.target.closest('.drag-handle, .menu-trigger, .label-editor') &&
        (!e.pointerType || e.pointerType === 'mouse');
      if (activatedOnPress) {
        focusSession(card.dataset.session);
      }
    }, true);
    document.addEventListener('pointerup', () => {
      const seq = pointerSeq;
      setTimeout(() => { if (pointerSeq === seq) pointerDown = false; }, 300);
    }, true);
    document.addEventListener('pointercancel', () => {
      pointerDown = false;
      pressedX = '';
      pressedY = '';
      activatedOnPress = false;
    }, true);
    window.addEventListener('blur', () => {
      pointerDown = false;
      panelFocusEpoch++;
    });

    // Collapsed repo keys; persists across the per-second re-render.
    const collapsedRepos = new Set();
    const collapsedGroups = new Set();
    let dragSession = null;
    let dropTarget = null;
    const groupColors = [
      ['Blue', '#79b8f3'], ['Green', '#71c9a2'], ['Purple', '#c1a0ec'],
      ['Orange', '#f1ad79'], ['Pink', '#eaa1c5'], ['Yellow', '#e2c477'],
    ];
    const sessionsPanel = document.getElementById('sessions');

    sessionsPanel.addEventListener('click', (e) => {
      const menuButton = e.target.closest('.menu-trigger');
      if (menuButton) {
        const {left, bottom} = menuButton.getBoundingClientRect();
        const group = menuButton.closest('.custom-group-header');
        if (group) openGroupMenu(group, left, bottom);
        else openCtxMenu(menuButton.closest('.agent').dataset.session, left, bottom);
        return;
      }
      const groupToggle = e.target.closest('.group-toggle');
      if (groupToggle) {
        const id = groupToggle.closest('.custom-group').dataset.group;
        if (!collapsedGroups.delete(id)) collapsedGroups.add(id);
        filterSessions(true);
        if (e.detail === 0) {
          document.querySelector(`.custom-group[data-group="${id}"] .group-toggle`)
            ?.focus({preventScroll: true});
        }
        return;
      }
      if (e.target.closest('.drag-handle')) return;
      const header = e.target.closest('.repo-header');
      if (header) {
        toggleGroup(header.parentElement.dataset.key);
        return;
      }
      const card = e.target.closest('.agent');
      if (card) {
        const clickedSessionId = card.dataset.session;
        const keyboardClick = e.detail === 0;
        const samePress = !keyboardClick && activatedOnPress &&
          Date.now() - pressedAt < 1000 &&
          Math.abs(e.clientX - Number(pressedX)) < 5 &&
          Math.abs(e.clientY - Number(pressedY)) < 5;
        activatedOnPress = false;
        if (samePress) {
          pressedX = '';
          pressedY = '';
          return;
        }
        const hit = !keyboardClick && document.elementFromPoint && Number.isFinite(e.clientX)
          ? document.elementFromPoint(e.clientX, e.clientY) : null;
        const hitCard = hit && hit.closest ? hit.closest('.agent') : null;
        // elementFromPoint reflects the card currently visible beneath the
        // pointer. This avoids both stale WebKit click targets and stale press
        // state carried across an iTerm window switch.
        const sessionId = hitCard ? hitCard.dataset.session : clickedSessionId;
        pressedX = '';
        pressedY = '';
        focusSession(sessionId);
      }
    });

    // Right-click a card for its action menu. The menu and the label editor
    // both live outside the polling render's reach until dismissed.
    let ctxMenu = null;
    let labelEditorOpen = false;

    sessionsPanel.addEventListener('contextmenu', (e) => {
      const group = e.target.closest('.custom-group-header');
      if (group) {
        e.preventDefault();
        openGroupMenu(group, e.clientX, e.clientY);
        return;
      }
      const card = e.target.closest('.agent');
      if (!card) return;
      e.preventDefault();
      openCtxMenu(card.dataset.session, e.clientX, e.clientY);
    });

    sessionsPanel.addEventListener('dragstart', (e) => {
      const handle = e.target.closest('.drag-handle');
      if (!handle) return;
      const id = handle.closest('.agent').dataset.session;
      dragSession = allSessions.find(s => s.id === id) || null;
      if (!dragSession) {
        e.preventDefault();
        return;
      }
      pointerDown = false;
      e.dataTransfer.effectAllowed = 'move';
      // WebKit needs a payload to start a drag. Keep the session ID in the panel.
      e.dataTransfer.setData('text/plain', 'Move session');
    });

    function dragDestination(target) {
      if (!dragSession) return null;
      const area = target.closest('.custom-group, .repo-header');
      if (!area || area.closest('.repo-group').dataset.key !== (dragSession.root_repo || ''))
        return null;
      const group = area.dataset.group || '';
      return group === (dragSession.group?.id || '') ? null : area;
    }

    function highlightDropTarget(target) {
      if (dropTarget === target) return;
      dropTarget?.classList.remove('drop-target');
      dropTarget = target;
      dropTarget?.classList.add('drop-target');
    }

    sessionsPanel.addEventListener('dragover', (e) => {
      const area = dragDestination(e.target);
      highlightDropTarget(area);
      if (!area) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
    });
    sessionsPanel.addEventListener('dragleave', (e) => {
      if (dropTarget && !dropTarget.contains(e.relatedTarget)) highlightDropTarget(null);
    });
    sessionsPanel.addEventListener('drop', (e) => {
      const area = dragDestination(e.target);
      if (!area) return;
      e.preventDefault();
      const session = dragSession.id;
      dragSession = null;
      highlightDropTarget(null);
      editGroup({action: 'move', session, group: area.dataset.group || ''});
    });
    document.addEventListener('dragend', () => {
      dragSession = null;
      highlightDropTarget(null);
    });

    function openCtxMenu(sessionId, x, y) {
      const session = allSessions.find(s => s.id === sessionId);
      const items = [
        ['Add to group…', () => openGroupPicker(session, x, y)],
        ['Label…', () => openLabelEditor(sessionId)],
        ['Focus session', () => focusSession(sessionId)],
      ];
      if (session?.group) {
        items.splice(1, 0, ['Remove from group', () => editGroup({
          action: 'move', session: sessionId,
        })]);
      }
      if (session?.agent_state === 'awaiting_user')
        items.push(['Mark as read', () => markSessionRead(sessionId)]);
      openMenu(items, x, y);
    }

    function openGroupPicker(session, x, y) {
      if (!session) return;
      const repo = session.root_repo || '';
      const groups = new Map(allSessions
        .filter(s => s.group && (s.root_repo || '') === repo)
        .map(s => [s.group.id, s.group]));
      const items = [['New group…', () => openTextEditor(
        sessionCard(session.id), '', 'Group name', name => {
          if (name) editGroup({action: 'create', session: session.id, name,
            color: groupColors[groups.size % groupColors.length][1]});
        })]];
      for (const group of groups.values()) {
        if (group.id !== session.group?.id)
          items.push([group.name, () => editGroup({
            action: 'move', session: session.id, group: group.id,
          })]);
      }
      openMenu(items, x, y);
    }

    function openGroupMenu(header, x, y) {
      const id = header.closest('.custom-group').dataset.group;
      const group = allSessions.find(s => s.group?.id === id)?.group;
      if (!group) return;
      openMenu([
        ['Rename group…', () => openTextEditor(header, group.name, 'Group name', name => {
          if (name) editGroup({action: 'rename', group: id, name});
        })],
        ['Change color…', () => openMenu(groupColors.map(([name, color]) =>
          [name, () => editGroup({action: 'recolor', group: id, color})]), x, y)],
        ['Ungroup sessions', () => editGroup({action: 'ungroup', group: id})],
      ], x, y);
    }

    function openMenu(items, x, y) {
      closeCtxMenu();
      closeLabelEditor();
      const menu = document.createElement('div');
      menu.className = 'ctx-menu';
      for (const [label, action] of items) {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'ctx-item';
        item.textContent = label;
        item.addEventListener('click', (e) => {
          e.stopPropagation();
          closeCtxMenu();
          action();
        });
        menu.appendChild(item);
      }
      document.body.appendChild(menu);
      menu.style.left = Math.max(4, Math.min(x, window.innerWidth - menu.offsetWidth - 4)) + 'px';
      menu.style.top = Math.max(4, Math.min(y, window.innerHeight - menu.offsetHeight - 4)) + 'px';
      // Focus the menu so the webview actually receives the Esc key — a
      // right-click alone does not move keyboard focus off the terminal.
      menu.tabIndex = -1;
      menu.focus({ preventScroll: true });
      ctxMenu = menu;
    }

    async function editGroup(change) {
      const status = document.getElementById('group-status');
      status.textContent = '';
      try {
        await panelRequest('/api/groups', false, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(change),
        });
      } catch (error) {
        status.textContent = 'Could not update group. Try again.';
      }
      await loadSessions();
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
        await panelRequest('/api/clear?session=' + encodeURIComponent(sessionId));
      } catch(e) {}
      acknowledgeCard(sessionId);
    }

    // Mirror renderCard's done→idle output exactly — keeps markRendered()
    // truthful without a DOM swap.
    function markCardIdle(card) {
      card.classList.remove('awaiting-user');
      card.classList.add('idle');
      const status = card.querySelector('.status');
      if (status) status.innerHTML = '&#9675; idle';
      const hint = card.querySelector('.action-hint');
      if (hint) hint.remove();
    }

    function acknowledgeCard(sessionId) {
      const s = allSessions.find(x => x.id === sessionId);
      if (!s || s.agent_state !== 'awaiting_user') return;
      const currentLayout = renderKey(filteredSessions()) === lastRenderedInput;
      s.agent_state = 'idle';
      s.awaiting_user = false;
      const card = document.querySelector(`.agent[data-session="${sessionId}"]`);
      if (card) markCardIdle(card);
      if (s.group) {
        const summary = document.querySelector(
          `.custom-group[data-group="${s.group.id}"] .group-summary`);
        if (summary) summary.textContent = groupSummary(
          filteredSessions().filter(row => row.group?.id === s.group.id));
      }
      if (currentLayout) markRendered();
    }

    function sessionCard(sessionId) {
      return document.querySelector(`.agent[data-session="${CSS.escape(sessionId)}"]`);
    }

    function openLabelEditor(sessionId) {
      const session = allSessions.find(s => s.id === sessionId);
      openTextEditor(sessionCard(sessionId), session?.label || '', 'Label…',
        label => saveLabel(sessionId, label));
    }

    function openTextEditor(anchor, value, title, save) {
      if (!anchor || !anchor.isConnected) return;
      closeLabelEditor();
      const wrap = document.createElement('div');
      wrap.className = 'label-editor';
      const input = document.createElement('input');
      input.value = value;
      input.placeholder = title;
      input.setAttribute('aria-label', title);
      input.maxLength = 40;
      wrap.appendChild(input);
      wrap.addEventListener('click', e => e.stopPropagation());
      anchor.appendChild(wrap);
      labelEditorOpen = true;
      input.focus();
      input.select();
      input.addEventListener('keydown', (e) => {
        e.stopPropagation();
        if (e.isComposing) return;
        if (e.key === 'Enter') {
          closeLabelEditor();
          save(input.value.trim());
        }
        else if (e.key === 'Escape') closeLabelEditor();
      });
      input.addEventListener('blur', () => setTimeout(() => {
        if (wrap.isConnected) closeLabelEditor();
      }, 100));
    }

    function closeLabelEditor() {
      const ed = document.querySelector('.label-editor');
      if (ed) ed.remove();
      labelEditorOpen = false;
    }

    async function saveLabel(sessionId, label) {
      try {
        await panelRequest('/api/label?session=' + encodeURIComponent(sessionId) +
                    '&label=' + encodeURIComponent(label));
      } catch(e) {}
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
      if (expand) collapsedGroups.clear();
      filterSessions(true);
    }

    let loadingSessions = false;
    let reloadSessionsPending = false;
    let hasSessionSnapshot = false;
    let sessionFailures = 0;
    let nextSessionRetryAt = 0;
    let lastSuccessfulPollAt = 0;

    async function loadSessions(force) {
      if (!force && Date.now() < nextSessionRetryAt) return;
      if (loadingSessions) {
        reloadSessionsPending = true;
        return;
      }
      loadingSessions = true;
      const requestedWindowId = panelWindowId;
      try {
        const url = panelUrl('/api/sessions');
        const {response: res, data: sessions} = await panelRequest(
          url + (url.includes('?') ? '&' : '?') + 'cached=1', true);
        if (!Array.isArray(sessions)) throw new Error('Invalid session snapshot');
        // An unbound request may finish after the first-click handshake.
        if (requestedWindowId !== panelWindowId) return;
        // Old rows can predate this window. Only the native window snapshot
        // can invalidate its binding; never guess from a missing cached row.
        if (panelWindowId && res.headers?.get('X-Agents-Window') === 'missing') {
          panelWindowId = '';
          window.name = '';
          const hint = document.getElementById('focus-hint');
          hint.hidden = false;
          hint.textContent = 'Click here to enable the blue focus marker';
          connectEvents();
        }
        allSessions = sessions;
        filterSessions(force);
        hasSessionSnapshot = true;
        sessionFailures = 0;
        nextSessionRetryAt = 0;
        lastSuccessfulPollAt = Date.now();
        connectionStatus(res.headers?.get('X-Agents-Stale') === '1'
          ? 'Updates paused. Showing the last available statuses.' : '');
      } catch(e) {
        sessionFailures++;
        nextSessionRetryAt = Date.now() + Math.min(15000, 1000 * 2 ** (sessionFailures - 1));
        connectionStatus('Updates paused. Reconnecting…');
        if (!hasSessionSnapshot) {
          document.getElementById('sessions').innerHTML =
            '<div class="no-results">Waiting for sessions…</div>';
        }
      } finally {
        loadingSessions = false;
        // Binding or a scan update can arrive during the first fetch. Retry
        // immediately instead of leaving a new panel blank until the next poll.
        if (reloadSessionsPending || requestedWindowId !== panelWindowId) {
          reloadSessionsPending = false;
          loadSessions();
        }
      }
    }

    function filteredSessions() {
      const q = document.getElementById('search').value.toLowerCase();
      return q
        ? allSessions.filter(s =>
            [s.name, s.repo, s.branch, s.path, s.agent_type, s.root_repo, s.group?.name].some(
              v => v && v.toLowerCase().includes(q)
            ))
        : allSessions;
    }

    function searchSessions() {
      if (document.getElementById('search').value) {
        for (const session of filteredSessions()) {
          collapsedRepos.delete(session.root_repo || '');
          if (session.group) collapsedGroups.delete(session.group.id);
        }
      }
      filterSessions(true);
    }

    function filterSessions(force) {
      focusedIndex = -1;
      renderSessions(filteredSessions(), force);
    }

    // The last HTML written. Identical renders skip the innerHTML swap —
    // replacing the node under the cursor leaves WebKit showing a stale
    // arrow until the next mouse event.
    let lastRenderedHtml = '';
    let lastRenderedInput = '';
    let lastFocusedSessionId = '';
    let pendingFocusReveal = '';

    function renderKey(sessions) {
      return JSON.stringify([sessions, [...collapsedRepos].sort(), [...collapsedGroups].sort()]);
    }

    function buildHtml(sessions) {
      // Group by root_repo
      const groups = new Map();
      const noRepo = [];
      for (const s of sessions) {
        const key = s.root_repo || '';
        if (!key) { noRepo.push(s); continue; }
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(s);
      }

      // Alphabetical group order: stable across status changes, so a cleared
      // or finished agent never shifts a card out from under the cursor.
      const sortedKeys = [...groups.keys()].sort((a, b) => a.localeCompare(b));

      let html = '';
      for (const key of sortedKeys) {
        const items = groups.get(key);
        const repoName = items[0].repo || key.split('/').pop() || key;
        html += renderGroup(repoName, key, items);
      }
      if (noRepo.length > 0) {
        html += renderGroup('(no repo)', '', noRepo);
      }
      return html;
    }

    // After an optimistic DOM patch the DOM already matches a fresh render;
    // claim it so the next identical render skips the swap (see above).
    function markRendered() {
      const sessions = filteredSessions();
      lastRenderedHtml = buildHtml(sessions);
      lastRenderedInput = renderKey(sessions);
    }

    function renderSessions(sessions, force) {
      const focusedId = allSessions.find(s => s.focused)?.id || '';
      if (focusedId !== lastFocusedSessionId) {
        lastFocusedSessionId = focusedId;
        pendingFocusReveal = focusedId;
      }
      // pointerDown suppresses stray interval writes mid-click; renders a
      // click handler asked for are safe — the click already dispatched.
      // An open context menu or label editor is also left untouched.
      if (force || (!pointerDown && !labelEditorOpen && !ctxMenu && !dragSession)) {
        const reveal = sessions.find(s => s.id === pendingFocusReveal);
        if (reveal) {
          collapsedRepos.delete(reveal.root_repo || '');
          if (reveal.group) collapsedGroups.delete(reveal.group.id);
        }
        const key = renderKey(sessions);
        if (key !== lastRenderedInput) {
          const html = sessions.length ? buildHtml(sessions)
            : '<div class="no-results">No sessions found</div>';
          if (html !== lastRenderedHtml) {
            sessionsPanel.innerHTML = html;
            lastRenderedHtml = html;
          }
          lastRenderedInput = key;
        }
        if (reveal) {
          const card = document.querySelector('.agent.current');
          if (card) {
            const rect = card.getBoundingClientRect();
            if (rect.top < 0 || rect.bottom > window.innerHeight) {
              window.scrollTo({
                top: Math.max(0, window.scrollY + rect.top - window.innerHeight / 5),
              });
            }
            pendingFocusReveal = '';
          }
        }
      }

      const running = sessions.filter(s => s.agent_state === 'running').length;
      const awaiting = sessions.filter(s => s.agent_state === 'awaiting_user').length;
      document.getElementById('clear-all').disabled = awaiting === 0;
      const withAgent = sessions.filter(s => s.agent_type).length;
      document.getElementById('count').textContent =
        sessions.length ? `${running} running / ${awaiting} done / ` +
        `${withAgent} agents / ${sessions.length} sessions` : '';
    }

    function renderGroup(repoName, repoPath, items) {
      const isCollapsed = collapsedRepos.has(repoPath);
      let sessionsHtml = '';
      if (!isCollapsed) {
        const groups = new Map();
        const looseCards = [];
        for (const session of items) {
          if (!session.group) {
            looseCards.push(renderCard(session));
            continue;
          }
          const id = session.group.id;
          if (!groups.has(id)) groups.set(id, []);
          groups.get(id).push(session);
        }
        sessionsHtml = [...groups.values()].map(renderCustomGroup).join('') + looseCards.join('');
      }
      const escapedPath = esc(repoPath).replace(/"/g, '&quot;');
      const titleAttr = repoPath ? ` title="${escapedPath}"` : '';
      const chevron = isCollapsed ? '&#9656;' : '&#9662;';

      return `<div class="repo-group" data-key="${escapedPath}">
        <div class="repo-header"${titleAttr}>
          <span>${esc(repoName)}</span>
          <span class="chevron">${chevron}</span>
        </div>
        ${sessionsHtml}
      </div>`;
    }

    function groupSummary(items) {
      const running = items.filter(s => s.agent_state === 'running').length;
      const done = items.filter(s => s.agent_state === 'awaiting_user').length;
      const statuses = [running && `${running} running`, done && `${done} done`];
      return statuses.filter(Boolean).join(' · ') ||
        `${items.length} ${items.length === 1 ? 'session' : 'sessions'}`;
    }

    function renderCustomGroup(items) {
      const group = items[0].group;
      const collapsed = collapsedGroups.has(group.id);
      const chevron = collapsed ? '&#9656;' : '&#9662;';
      const name = esc(group.name).replace(/"/g, '&quot;');
      return `<div class="custom-group" data-group="${group.id}"
                   style="--group-color:${group.color}">
        <div class="custom-group-header">
          <button type="button" class="group-toggle" aria-expanded="${!collapsed}" title="${name}">
            <span aria-hidden="true">${chevron}</span>
            <span class="group-name">${name}</span>
            <span class="group-summary">${groupSummary(items)}</span>
          </button>
          <button type="button" class="menu-trigger" aria-label="Group actions">⋯</button>
        </div>
        ${collapsed ? '' : items.map(renderCard).join('')}
      </div>`;
    }

    function renderCard(s) {
      const meta = stateMeta(s.agent_state);
      const typeBadge = s.agent_type
        ? `<span class="agent-type ${s.agent_type}">${s.agent_type}</span>`
        : '';
      const labelTitle = s.label ? esc(s.label).replace(/"/g, '&quot;') : '';
      const labelChip = s.label
        ? `<span class="label" title="${labelTitle}">${esc(s.label)}</span>`
        : '';
      const displayName = (s.name || '')
        .replace(/\\s+\\|.*$/, '')
        .replace(/\\s+—\\s+[~/].*$/, '')
        .replace(/\\p{L}/u, c => c.toLowerCase());
      const nameLine = s.name && s.name !== s.path
        ? `<div class="session-name">${esc(displayName)}</div>`
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
      return `<div class="agent ${meta.cls}${s.focused ? ' current' : ''}"
                   data-session="${s.id}">
        <div class="agent-top">
          <span class="status">${meta.icon} ${meta.label}</span>
          <span class="card-actions">
            ${typeBadge}
            <span class="drag-handle" draggable="true" title="Drag to move session"
                  aria-hidden="true">⠿</span>
            <button type="button" class="menu-trigger" aria-label="Session actions">⋯</button>
          </span>
        </div>
        ${nameLine}
        ${branchLine}
        ${actionHint}
      </div>`;
    }

    function esc(str) {
      const d = document.createElement('div');
      d.textContent = str;
      return d.innerHTML;
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
        await panelRequest('/api/clear');
        await loadSessions(true);
      } catch(e) {}
    }

    async function focusSession(sessionId) {
      // Bind the source panel before a card click can activate another window.
      if (!panelWindowId) await bindPanelWindow();
      try {
        await panelRequest('/api/focus?session=' + encodeURIComponent(sessionId));
      } catch(e) {}
      // Patch the card in place — the marker arrives via the event connection and the poll
      // confirms the rest; a forced rewrite churns the node under the cursor.
      acknowledgeCard(sessionId);
    }

    loadSessions();
    // Polls drive the server's scans. A hidden panel (minimized, covered, on
    // another Space) keeps slow polls so turns still get their done marks.
    let lastPollAt = Date.now();
    function pollSessions() {
      if (document.hidden && Date.now() - lastPollAt < 5000) return;
      lastPollAt = Date.now();
      loadSessions();
    }
    setInterval(pollSessions, 1000);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) pollSessions();
    });

    // SSE streams share WebKit's small HTTP connection pool with fetch.
    // Several sidebars can exhaust it and queue a click for seconds. WebSocket
    // events keep that pool available for session reads and pane activation.
    class PanelEvents {
      constructor(url) {
        this.url = url;
        this.listeners = new Map();
        this.closed = false;
        this.socket = new WebSocket(url);
        this.socket.onopen = () => this.dispatch('open', {});
        this.socket.onmessage = (e) => {
          const frame = JSON.parse(e.data);
          this.dispatch(frame.event, {data: JSON.stringify(frame.data)});
        };
        const failed = () => { if (!this.closed && this.onerror) this.onerror(); };
        this.socket.onerror = failed;
        this.socket.onclose = failed;
      }
      addEventListener(name, fn) {
        if (!this.listeners.has(name)) this.listeners.set(name, []);
        this.listeners.get(name).push(fn);
      }
      dispatch(name, event) {
        if (!this.closed) (this.listeners.get(name) || []).forEach(fn => fn(event));
      }
      close() {
        this.closed = true;
        this.socket.close();
      }
    }

    function connectEvents() {
      if (eventsSource) eventsSource.close();
      const scheme = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
      const es = new PanelEvents(scheme + window.location.host + panelUrl('/api/ws'));
      eventsSource = es;
      // The event carries the focused session ids — toggle the marker in
      // place; a refetch would add a needless round trip to a fast path.
      es.addEventListener('focus-changed', (e) => {
        const data = JSON.parse(e.data);
        if (eventsSource !== es || !panelWindowId || data.window_id !== panelWindowId) return;
        const ids = new Set(data.focused || []);
        if (allSessions.every(s => !!s.focused === ids.has(s.id))) return;
        const currentLayout = renderKey(filteredSessions()) === lastRenderedInput;
        allSessions.forEach(s => { s.focused = ids.has(s.id); });
        document.querySelectorAll('.agent').forEach(el =>
          el.classList.toggle('current', ids.has(el.dataset.session)));
        if (currentLayout) markRendered();
        renderSessions(filteredSessions());
      });
      es.addEventListener('focus-search', () => {
        if (eventsSource !== es || !panelWindowId) return;
        const search = document.getElementById('search');
        search.focus();
        search.select();
        focusedIndex = -1;
        clearFocus(getAgentElements());
      });
      es.addEventListener('sessions-changed', () => {
        if (eventsSource === es) loadSessions();
      });
      // Application acknowledgements establish JS responsiveness, not GPU
      // health. Hidden/suspended pages are never assumed to be broken.
      es.addEventListener('health-check', () => {
        if (eventsSource !== es) return;
        es.socket.send(JSON.stringify({
          event: 'panel-health', visible: !document.hidden,
          busy: !!(pointerDown || labelEditorOpen || ctxMenu || dragSession ||
            document.getElementById('search').value),
          data_age_ms: lastSuccessfulPollAt ? Date.now() - lastSuccessfulPollAt : null,
        }));
      });
      es.onerror = () => {
        if (eventsSource !== es) return;
        es.close();
        eventsSource = null;
        setTimeout(() => { if (!eventsSource) connectEvents(); }, 3000);
      };
    }
    connectEvents();

    // Focus search on initial load
    document.getElementById('search').focus();
  </script>
</body>
</html>"""
