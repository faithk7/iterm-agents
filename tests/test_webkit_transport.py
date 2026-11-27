"""Run the panel in native WebKit to catch browser connection-pool stalls."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import iterm2.api_pb2
import iterm2.rpc
import pytest
from aiohttp import web

from iterm_agents.server import AgentMonitorServer
from iterm_agents.ui import AGENT_MONITOR_HTML


@pytest.fixture(scope="module")
def webkit_probe(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if sys.platform != "darwin" or shutil.which("clang") is None:
        pytest.skip("Native WebKit transport test requires macOS and clang")
    directory = tmp_path_factory.mktemp("webkit-transport")
    source = directory / "probe.m"
    source.write_text(r'''
#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
@interface Probe : NSObject <WKScriptMessageHandler>
@property(strong) WKWebView *view;
@end
@implementation Probe
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
    printf("%s\n", [[message.body description] UTF8String]); fflush(stdout);
    if ([[message.body description] hasPrefix:@"DONE"]) exit(0);
}
@end
int main(int argc, char **argv) {
    @autoreleasepool {
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
        Probe *probe = [Probe new];
        WKWebViewConfiguration *config = [WKWebViewConfiguration new];
        [config.userContentController addScriptMessageHandler:probe name:@"result"];
    double width = argc > 2 ? [[NSString stringWithUTF8String:argv[2]] doubleValue] : 400;
    probe.view = [[WKWebView alloc] initWithFrame:NSMakeRect(0, 0, width, 300) configuration:config];
        [probe.view loadRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:[NSString stringWithUTF8String:argv[1]]]]];
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{ puts("TIMEOUT"); exit(2); });
        [NSApp run];
    }
    return 0;
}
''')
    binary = directory / "probe"
    subprocess.run(
        ["clang", "-fobjc-arc", "-framework", "Cocoa", "-framework", "WebKit",
         str(source), "-o", str(binary)],
        check=True, capture_output=True, timeout=30,
    )
    return binary


async def test_repo_groups_in_narrow_webkit_panel(
    webkit_probe: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]
    rows = [
        {
            "id": f"s-{number}",
            "name": f"agent {number}",
            "window_id": "w1",
            "repo": repo,
            "root_repo": f"~/projects/{repo}",
            "branch": branch,
            "agent_state": "running",
            "agent_type": "codex",
        }
        for number, repo, branch in (
            (1, "repo", "main"), (2, "repo", "worktree"), (3, "repo", "fix"), (4, "other", "main")
        )
    ]
    server._scan_cache = (time.monotonic(), rows.copy())
    server._scan_sessions = AsyncMock(side_effect=rows.copy)
    server._activate_session = AsyncMock()

    def close(_connection, *, sessions, force):
        assert sessions == ["s-2", "s-3"]
        assert force is False
        rows[:] = [row for row in rows if row["id"] != "s-2"]
        response = iterm2.api_pb2.CloseResponse()
        response.statuses.extend([response.OK, response.USER_DECLINED])
        return SimpleNamespace(close_response=response)

    native_close = AsyncMock(side_effect=close)
    monkeypatch.setattr(iterm2.rpc, "async_close", native_close)
    html = AGENT_MONITOR_HTML.replace(
        "<script>", """<script>window.name = 'iterm-agents:window:w1';
window.addEventListener('error', e => window.webkit.messageHandlers.result
  .postMessage('DONE ' + e.message));
""", 1
    ).replace("</body>", r'''
<script>
const check = (pass, message) => { if (!pass) throw new Error(message); };
const card = id => document.querySelector(`.agent[data-session="s-${id}"]`);
const groupOf = id => card(id)?.closest('.custom-group');
const nameOf = group => group?.querySelector('.group-name').textContent;
const choose = label => [...document.querySelectorAll('.ctx-item')]
  .find(item => item.textContent === label).click();
const rightClick = target => target.dispatchEvent(new MouseEvent('contextmenu',
  {bubbles: true, cancelable: true, button: 2}));
const groupMenu = group => rightClick(group.querySelector('.custom-group-header'));
const key = (target, key, shiftKey = false) => target.dispatchEvent(new KeyboardEvent('keydown',
  {bubbles: true, cancelable: true, key, shiftKey}));
function enterName(name) {
  const input = document.querySelector('.label-editor input');
  input.value = name;
  input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
}
function createGroup(id, name) {
  rightClick(card(id));
  choose('Add to group…');
  choose('New group…');
  enterName(name);
}
async function waitFor(condition, message) {
  const deadline = performance.now() + 2000;
  while (performance.now() < deadline) {
    if (condition()) return;
    await new Promise(resolve => setTimeout(resolve, 15));
  }
  throw new Error(message + ' ' + document.getElementById('group-status').textContent);
}
(async () => {
  await waitFor(() => card(4), 'initial cards');
  key(document.getElementById('search'), 'ArrowDown');
  key(document.activeElement, 'F10', true);
  check(document.querySelector('.ctx-item')?.textContent === 'Add to group…',
    'Shift+F10 opens the selected session menu');
  key(document.activeElement, 'Escape');
  let dataTransfer;
  function startDrag(target) {
    target.dispatchEvent(new PointerEvent('pointerdown',
      {bubbles: true, button: 0, pointerType: 'mouse'}));
    const source = target.closest('[draggable="true"]');
    check(source, 'drag starts from a draggable element');
    dataTransfer = new DataTransfer();
    source.dispatchEvent(new DragEvent('dragstart', {bubbles: true, dataTransfer}));
  }
  function drag(target, type, clientY = 0) {
    return !target.dispatchEvent(new DragEvent(type,
      {bubbles: true, cancelable: true, dataTransfer, clientY}));
  }
  startDrag(card(3).querySelector('.session-name'));
  check(!drag(card(4), 'dragover'), 'cannot reorder across repos');
  const firstTop = card(1).getBoundingClientRect().top + 1;
  check(drag(card(1), 'dragover', firstTop) && card(1).classList.contains('drop-before'),
    'show an insertion marker for a loose session');
  check(drag(card(1), 'drop', firstTop), 'drop from the session title');
  await waitFor(() => card(3).nextElementSibling === card(1), 'reorder loose session cards');
  startDrag(card(3));
  check(drag(card(2), 'drop', card(2).getBoundingClientRect().bottom - 1),
    'restore loose order by dragging the bar');
  await waitFor(() => card(2).nextElementSibling === card(3), 'restore loose order');

  createGroup(2, 'Placement');
  await waitFor(() => groupOf(2), 'create group in middle');
  check(!document.querySelector('.drag-handle, .menu-trigger'), 'no grip or menu buttons');
  check(card(1).nextElementSibling === groupOf(2) && groupOf(2).nextElementSibling === card(3),
    'a new group takes its card’s position');
  startDrag(card(3));
  const placementHeader = groupOf(2).querySelector('.custom-group-header');
  check(drag(placementHeader, 'drop', placementHeader.getBoundingClientRect().top + 1),
    'drop a loose session before a group');
  await waitFor(() => card(3).nextElementSibling === groupOf(2), 'reorder beside a group');
  rightClick(card(3));
  choose('Move down');
  await waitFor(() => groupOf(2).nextElementSibling === card(3), 'restore position below the group');
  key(groupOf(2).querySelector('.group-toggle'), 'F10', true);
  choose('Move down');
  await waitFor(() => card(3).nextElementSibling === groupOf(2), 'move down past a loose card');
  groupMenu(groupOf(2));
  choose('Move up');
  await waitFor(() => groupOf(2).nextElementSibling === card(3), 'move up past a loose card');
  startDrag(groupOf(2).querySelector('.custom-group-header'));
  const looseTop = card(1).getBoundingClientRect().top + 1;
  check(drag(card(1), 'dragover', looseTop) && drag(card(1), 'drop', looseTop),
    'drop group before a loose card');
  await waitFor(() => groupOf(2).nextElementSibling === card(1), 'drag reorders against loose card');
  groupMenu(groupOf(2));
  choose('Ungroup sessions');
  await waitFor(() => card(2) && !groupOf(2), 'ungroup placement test session');

  createGroup(1, 'Release <review>');
  await waitFor(() => groupOf(1), 'create group');
  check(nameOf(groupOf(1)) === 'Release <review>', 'escape group name');
  check(groupOf(1).closest('.repo-group').dataset.key === '~/projects/repo', 'repo nesting');
  check(document.documentElement.scrollWidth === 240, 'narrow panel does not overflow');
  const first = groupOf(1).dataset.group;
  const rejected = await fetch('/api/groups', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'move', session: 's-4', group: first})});
  check(rejected.status === 409, 'reject moves across repos');
  rightClick(card(2));
  choose('Add to group…');
  choose('Release <review>');
  await waitFor(() => groupOf(2)?.dataset.group === first, 'join via worktree');
  startDrag(card(2).querySelector('.session-name'));
  check(drag(card(1), 'drop', card(1).getBoundingClientRect().top + 1),
    'drop session before a sibling in its group');
  await waitFor(() => card(2).nextElementSibling === card(1), 'reorder sessions within a group');
  rightClick(card(2));
  choose('Move down');
  await waitFor(() => card(1).nextElementSibling === card(2), 'reorder sessions using the menu');

  groupOf(1).querySelector('.group-toggle').click();
  check(!card(1) && document.querySelector('.group-summary').textContent === '2 running',
    'collapsed group status');
  const search = document.getElementById('search');
  search.value = 'release <review>';
  search.dispatchEvent(new Event('input'));
  check(card(1) && card(2) && !card(3), 'search expands matching group');
  search.value = '';
  search.dispatchEvent(new Event('input'));

  groupMenu(groupOf(1));
  choose('Rename group…');
  enterName('Review');
  await waitFor(() => nameOf(groupOf(1)) === 'Review', 'rename group');
  groupMenu(groupOf(1));
  choose('Change color…');
  choose('Purple');
  await waitFor(() => groupOf(1)?.style.getPropertyValue('--group-color') === '#c1a0ec',
    'recolor group');
  createGroup(3, 'Fixes');
  await waitFor(() => groupOf(3), 'second group');

  const order = () => [...groupOf(1).closest('.repo-group').querySelectorAll('.group-name')]
    .map(name => name.textContent).join(', ');
  check(order() === 'Review, Fixes', 'new groups are appended');
  const fixesId = groupOf(3).dataset.group;
  const fixes = () => document.querySelector(`.custom-group[data-group="${fixesId}"]`);
  fixes().querySelector('.group-toggle').click();
  check(!card(3), 'collapse group before moving');

  startDrag(fixes().querySelector('.group-name'));
  const review = groupOf(1);
  const header = review.querySelector('.custom-group-header');
  const rect = header.getBoundingClientRect();
  check(drag(header, 'dragover', rect.bottom - 1) && review.classList.contains('drop-after'),
    'show insertion marker after target');
  check(drag(header, 'dragover', rect.top + 1) && review.classList.contains('drop-before'),
    'show insertion marker before target');
  check(drag(header, 'drop', rect.top + 1), 'drop group before existing group');
  await waitFor(() => order() === 'Fixes, Review', 'drag reorders group');
  check(!card(3), 'moving a group preserves collapse');
  fixes().querySelector('.group-toggle').click();

  groupMenu(fixes());
  choose('Move down');
  await waitFor(() => order() === 'Review, Fixes', 'move group down from menu');
  groupMenu(fixes());
  choose('Move up');
  await waitFor(() => order() === 'Fixes, Review', 'move group up from menu');
  groupMenu(fixes());
  choose('Move down');
  await waitFor(() => order() === 'Review, Fixes', 'restore group order');

  createGroup(4, 'Other repo group');
  await waitFor(() => groupOf(4), 'group in another repo');
  const crossRepo = await fetch('/api/groups', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'reorder', group: fixesId,
      target: 'group:' + groupOf(4).dataset.group, before: true})});
  check(crossRepo.status === 409, 'reject group reordering across repos');

  startDrag(card(1));
  check(!drag(card(4).closest('.repo-group').querySelector('.repo-header'), 'dragover'),
    'foreign repo is not a drop target');
  check(drag(groupOf(3), 'dragover') && drag(groupOf(3), 'drop'), 'drop in same repo');
  await waitFor(() => nameOf(groupOf(1)) === 'Fixes', 'drag membership');
  check(nameOf(groupOf(2)) === 'Review', 'part of old group remains');
  check(order() === 'Review, Fixes', 'changing membership preserves group order');
  check((await (await fetch('/api/sessions?cached=1')).json())[0].group.name === 'Fixes',
    'group membership is shared by fresh panels');

  rightClick(card(1));
  choose('Remove from group');
  await waitFor(() => card(1) && !groupOf(1), 'remove member');
  groupMenu(groupOf(3));
  choose('Ungroup sessions');
  await waitFor(() => card(3) && !groupOf(3), 'ungroup all members');

  groupMenu(groupOf(2));
  choose('Close group…');
  check(document.activeElement.textContent === 'Cancel', 'close confirmation focuses Cancel');
  choose('Cancel');
  check(card(2), 'cancel keeps the session');

  groupMenu(groupOf(2));
  choose('Close group…');
  await fetch('/api/groups', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'move', session: 's-3', group: first})});
  choose('Close 1 session');
  const groupStatus = document.getElementById('group-status');
  await waitFor(() => groupStatus.textContent.includes('Group changed'), 'reject stale confirmation');
  await waitFor(() => groupOf(3)?.dataset.group === first, 'show updated membership');
  groupMenu(groupOf(2));
  choose('Close group…');
  choose('Close 2 sessions');
  await waitFor(() => groupStatus.textContent === 'Closed 1 of 2 sessions.', 'show partial close');
  await waitFor(() => !card(2), 'closed session disappears');
  check(groupOf(3) && card(4), 'declined and unrelated sessions stay open');

  const cmdClick = id => card(id).dispatchEvent(new MouseEvent('click',
    {bubbles: true, cancelable: true, metaKey: true}));
  cmdClick(1);
  cmdClick(3);
  check(card(1).classList.contains('selected') && card(3).classList.contains('selected'),
    'cmd-click selects cards');
  rightClick(card(3));
  choose('Add 2 sessions to group…');
  choose('New group…');
  enterName('Bulk');
  await waitFor(() => groupOf(1) && groupOf(1) === groupOf(3) && nameOf(groupOf(1)) === 'Bulk',
    'bulk add to a new group');
  check(card(1).classList.contains('selected'), 'selection survives regrouping');
  rightClick(card(1));
  check(document.querySelector('.ctx-item').textContent.startsWith('Add 2 sessions'),
    'selected card opens the bulk menu');
  choose('Clear selection');
  check(!document.querySelector('.agent.selected'), 'clear selection');

  card(1).click();
  await new Promise(resolve => setTimeout(resolve, 50));
  window.webkit.messageHandlers.result.postMessage('DONE groups worked');
})().catch(error => window.webkit.messageHandlers.result
  .postMessage('DONE ' + error.message + '\n' + error.stack));
</script></body>''')
    app = web.Application()

    async def page(_request: web.Request) -> web.Response:
        return web.Response(text=html, content_type="text/html")

    app.router.add_get("/", page)
    app.router.add_get("/api/ws", server._handle_ws)
    app.router.add_get("/api/sessions", server._handle_sessions)
    app.router.add_get("/api/focus", server._handle_focus)
    app.router.add_post("/api/groups", server._handle_group)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    server.port = port
    process = await asyncio.create_subprocess_exec(
        str(webkit_probe), f"http://127.0.0.1:{port}/", "240",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        output, errors = await asyncio.wait_for(process.communicate(), timeout=15)
        assert process.returncode == 0 and output.strip() == b"DONE groups worked", (
            output.decode() + errors.decode()
        )
        server._activate_session.assert_awaited_once_with("s-1")
        native_close.assert_awaited_once_with(None, sessions=["s-2", "s-3"], force=False)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        await runner.cleanup()
        await asyncio.gather(*server._detached_tasks, return_exceptions=True)


async def test_six_panel_streams_do_not_queue_a_card_click(webkit_probe: Path) -> None:
    server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]
    rows = [{"id": "s-1", "name": "agent", "window_id": "w1", "agent_state": "idle"}]
    server._scan_cache = (time.monotonic(), rows)
    server._window_ids = {"w1"}
    server._focused_by_window = {"w1": "s-1"}
    server._scan_sessions = AsyncMock(return_value=rows)
    server._activate_session = AsyncMock()
    html = AGENT_MONITOR_HTML.replace(
        "<script>", "<script>window.name = 'iterm-agents:window:w1';", 1
    ).replace("</body>", r'''
<script>
const streams = [eventsSource];
let opened = 0, completed = false;
function report(s) { window.webkit.messageHandlers.result.postMessage(s); }
function ready() {
  if (++opened !== 6) return;
  const start = performance.now();
  focusSession('s-1').then(() => {
    completed = true;
    report('DONE request_ms=' + Math.round(performance.now() - start));
    streams.forEach(stream => stream.close());
  });
  setTimeout(() => {
    if (!completed) {
      report('click queued behind panel streams');
      streams[0].close();
    }
  }, 1000);
}
streams[0].addEventListener('open', ready);
for (let i = 1; i < 6; i++) {
  const stream = new streams[0].constructor(streams[0].url);
  stream.addEventListener('open', ready);
  streams.push(stream);
}
</script></body>''')
    app = web.Application()

    async def page(_request: web.Request) -> web.Response:
        return web.Response(text=html, content_type="text/html")

    app.router.add_get("/", page)
    app.router.add_get("/api/events", server._handle_sse)
    if hasattr(server, "_handle_ws"):
        app.router.add_get("/api/ws", server._handle_ws)
    app.router.add_get("/api/sessions", server._handle_sessions)
    app.router.add_get("/api/focus", server._handle_focus)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    process = await asyncio.create_subprocess_exec(
        str(webkit_probe), f"http://127.0.0.1:{port}/",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        output, errors = await asyncio.wait_for(process.communicate(), timeout=15)
        assert process.returncode == 0, output.decode() + errors.decode()
        elapsed = re.search(rb"DONE request_ms=(\d+)", output)
        assert elapsed is not None, output.decode()
        assert int(elapsed[1]) < 1000, output.decode()
        print(f"Native WebKit, six panel connections: card request {int(elapsed[1])} ms")
        server._activate_session.assert_awaited_once_with("s-1")
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        await runner.cleanup()
        await asyncio.gather(*server._detached_tasks, return_exceptions=True)


@pytest.mark.parametrize("stall", ["fetch", "body"])
async def test_webkit_deadline_preserves_cards_and_recovers(webkit_probe: Path, stall: str) -> None:
    """Exercise real browser timers, including a response body that never arrives."""
    server = AgentMonitorServer(connection=None)  # type: ignore[arg-type]
    rows = [{"id": "s-1", "name": "agent", "window_id": "w1", "agent_state": "idle"}]
    server._scan_cache = (time.monotonic(), rows)
    html = AGENT_MONITOR_HTML.replace(
        "}, deadline);", "}, window.testRequestDeadline || deadline);"
    ).replace(
        "</body>", r'''
<script>
window.addEventListener('error', e => window.webkit.messageHandlers.result.postMessage('ERROR ' + e.message));
window.addEventListener('unhandledrejection', e => window.webkit.messageHandlers.result.postMessage('ERROR ' + e.reason));
const ready = setInterval(async () => {
  if (!document.querySelector('.agent')) return;
  clearInterval(ready);
  const originalFetch = window.fetch;
  const card = document.querySelector('.agent');
  window.testRequestDeadline = 50;
  window.fetch = () => STALL === 'fetch'
    ? new Promise(() => {})
    : Promise.resolve({ok: true, json: () => new Promise(() => {})});
  await loadSessions(true);
  if (loadingSessions || document.querySelector('.agent') !== card ||
      document.getElementById('connection-status').hidden) {
    window.webkit.messageHandlers.result.postMessage('DONE failed deadline');
    return;
  }
  window.fetch = originalFetch;
  window.testRequestDeadline = 8000;
  await loadSessions(true);
  const recovered = !document.getElementById('connection-status').hidden
    ? 'failed recovery' : 'recovered';
  window.webkit.messageHandlers.result.postMessage('DONE ' + recovered);
}, 10);
</script></body>'''.replace("STALL", json.dumps(stall)),
    )
    app = web.Application()

    async def page(_request: web.Request) -> web.Response:
        return web.Response(text=html, content_type="text/html")

    app.router.add_get("/", page)
    app.router.add_get("/api/sessions", server._handle_sessions)
    app.router.add_get("/api/ws", server._handle_ws)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    process = await asyncio.create_subprocess_exec(
        str(webkit_probe), f"http://127.0.0.1:{runner.addresses[0][1]}/",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        output, errors = await asyncio.wait_for(process.communicate(), 15)
        assert process.returncode == 0, output.decode() + errors.decode()
        assert b"DONE recovered" in output, output.decode() + errors.decode()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        await runner.cleanup()
        await asyncio.gather(*server._detached_tasks, return_exceptions=True)
