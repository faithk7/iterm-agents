"""Exercise the embedded panel script without adding a browser dependency."""

import json
import shutil
import subprocess

import pytest

from iterm_agents.ui import AGENT_MONITOR_HTML


def test_panel_skips_unchanged_html_and_preserves_focus_updates() -> None:
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
let escapeElements = 0;
let cards = [];
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
    querySelector: () => cards[0],
    createElement: () => {
      escapeElements++;
      return { set textContent(s) { this.innerHTML = s; } };
    },
  },
  window: { addEventListener() {} },
  fetch: url => url.startsWith('/api/focus')
    ? Promise.resolve({ ok: true }) : new Promise(() => {}),
  setInterval() {},
  setTimeout: fn => timeouts.push(fn),
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
escapeElements = 0;
vm.runInContext('allSessions = JSON.parse(JSON.stringify(allSessions)); filterSessions()', context);
assert.equal(escapeElements, 0, 'unchanged polls must skip HTML generation');
assert.equal(writes, initialWrites);
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
assert.ok(element('count').textContent.includes('0 done'));
(async () => {
  for (let i = 0; i < 3; i++) {
    await vm.runInContext("focusSession('one')", context);
    assert.equal(writes, initialWrites);
    assert.equal(cards[0], originalCard);
  }
  vm.runInContext("toggleGroup('')", context);
  assert.ok(!element('sessions').innerHTML.includes('class="agent '));
  escapeElements = 0;
  vm.runInContext("allSessions[0].label = 'new label'; filterSessions()", context);
  assert.equal(escapeElements, 2, 'collapsed groups only escape the header');
  vm.runInContext("toggleGroup('')", context);
  assert.ok(element('sessions').innerHTML.includes('new label'));

  for (const guard of ['pointerDown', 'labelEditorOpen', 'ctxMenu']) {
    const before = writes;
    escapeElements = 0;
    vm.runInContext(`${guard} = true; allSessions[0].name += 'x'; filterSessions()`, context);
    assert.equal(writes, before, 'interaction guards must defer replacement');
    assert.equal(escapeElements, 0);
    vm.runInContext(`${guard} = false; filterSessions()`, context);
    assert.equal(writes, before + 1, 'deferred changes must render after the guard clears');
  }

  vm.runInContext('loadingSessions = false', context);
  const snapshot = vm.runInContext('JSON.parse(JSON.stringify(allSessions))', context);
  context.fetch = () => Promise.reject(new Error('offline'));
  await vm.runInContext('loadSessions()', context);
  assert.ok(element('sessions').innerHTML.includes('Failed to load sessions'));
  context.fetch = () => Promise.resolve({json: async () => snapshot});
  await vm.runInContext('loadSessions()', context);
  assert.ok(!element('sessions').innerHTML.includes('Failed to load sessions'));
  assert.ok(element('sessions').innerHTML.includes('new label'));

  element('search').value = 'no match';
  vm.runInContext('filterSessions()', context);
  const emptyWrites = writes;
  vm.runInContext('filterSessions()', context);
  assert.equal(writes, emptyWrites, 'unchanged empty results must preserve the DOM');
  assert.equal(element('count').textContent, '');
  assert.ok(element('clear-all').disabled);
})().catch(error => { console.error(error); process.exitCode = 1; });
""",
        ],
        input=json.dumps(script),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
