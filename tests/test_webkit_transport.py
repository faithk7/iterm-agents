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
from unittest.mock import AsyncMock

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
        probe.view = [[WKWebView alloc] initWithFrame:NSMakeRect(0, 0, 400, 300) configuration:config];
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
        "}, 8000);", "}, window.testRequestDeadline || 8000);"
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
