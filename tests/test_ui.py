"""Exercise the embedded panel script without adding a browser dependency."""

import json
import shutil
import subprocess

import pytest

from iterm_agents.ui import AGENT_MONITOR_HTML


def test_focus_updates_refresh_cursor_without_replacing_cards() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to exercise the panel JavaScript")
    script = AGENT_MONITOR_HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    subprocess.run(
        [
            node,
            "-e",
            r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const script = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
let writes = 0;
let cards = [];
let hovering = true;
const frames = [];
const timeouts = [];
const listeners = {};
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: '', textContent: '', disabled: false,
    focus() {}, addEventListener() {},
    set innerHTML(html) { if (id === 'sessions') writes++; this.html = html; },
    get innerHTML() { return this.html || ''; },
  });
  return elements.get(id);
}
const context = vm.createContext({
  document: {
    hasFocus: () => false,
    getElementById: element,
    addEventListener() {},
    querySelectorAll: () => cards,
    querySelector: selector => selector === '.agent:hover'
      ? (hovering ? cards[0] : null) : cards[0],
    createElement: () => ({ set textContent(s) { this.innerHTML = s; } }),
  },
  window: { addEventListener() {} },
  fetch: url => url.startsWith('/api/focus')
    ? Promise.resolve({ ok: true }) : new Promise(() => {}),
  setInterval() {},
  setTimeout: fn => timeouts.push(fn),
  requestAnimationFrame: fn => frames.push(fn),
  EventSource: class {
    addEventListener(name, fn) { listeners[name] = fn; }
  },
});
vm.runInContext(script, context);
vm.runInContext(`allSessions = [
  {id: 'one', name: 'visible', agent_state: 'awaiting_user', awaiting_user: true},
  {id: 'two', name: 'hidden', agent_state: 'idle'}
];`, context);
element('search').value = 'visible';
vm.runInContext('filterSessions()', context);
const classes = new Set(['awaiting-user']);
const status = {};
let hintRemoved = false;
cards = [{
  dataset: { session: 'one' },
  classList: {
    toggle(c, enabled) { if (enabled) classes.add(c); else classes.delete(c); },
    add: c => classes.add(c), remove: c => classes.delete(c),
  },
  querySelector: selector => selector === '.status'
    ? status : { remove() { hintRemoved = true; } },
}];
const originalCard = cards[0];
const initialWrites = writes;
for (const focused of [['one'], ['two'], ['one']]) {
  listeners['focus-changed']({ data: JSON.stringify({ focused }) });
  while (timeouts.length) timeouts.shift()();
  vm.runInContext('filterSessions()', context);
  assert.equal(writes, initialWrites, 'focus must not replace the hovered card');
  assert.equal(classes.has('current'), focused.includes('one'));
}
vm.runInContext("acknowledgeCard('one'); filterSessions()", context);
assert.equal(writes, initialWrites, 'clearing done must preserve the card');
assert.equal(cards[0], originalCard);
assert.ok(classes.has('idle'));
assert.ok(!classes.has('awaiting-user'));
assert.ok(hintRemoved);
assert.equal(status.innerHTML, '&#9675; idle');
assert.ok(!element('sessions').innerHTML.includes('hidden'));
(async () => {
  for (let i = 0; i < 3; i++) {
    await vm.runInContext("focusSession('one')", context);
    assert.ok(classes.has('cursor-refresh'), 'every click must refresh the cursor');
    assert.equal(frames.length, 1);
    frames.shift()();
    assert.ok(classes.has('cursor-refresh'), 'keep the new style for one frame');
    frames.shift()();
    assert.ok(!classes.has('cursor-refresh'), 'restore the pointing hand');
    assert.equal(writes, initialWrites);
  }
  hovering = false;
  await vm.runInContext("focusSession('one')", context);
  assert.equal(frames.length, 0, 'do not change cursors outside cards');
  hovering = true;
  for (const guard of ['labelEditorOpen', 'ctxMenu']) {
    vm.runInContext(`${guard} = true`, context);
    await vm.runInContext("focusSession('one')", context);
    assert.equal(frames.length, 0, 'leave editors and menus alone');
    vm.runInContext(`${guard} = false`, context);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
""",
        ],
        input=json.dumps(script),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
