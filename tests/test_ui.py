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
const scrolls = [];
const focusRequests = [];
const cardPositions = {one: 1650, two: 2650};
const viewport = {
  innerHeight: 900, scrollY: 600, addEventListener() {},
  scrollTo(options) {
    const session = cards.find(card => card.classList.contains('current')).dataset.session;
    scrolls.push({session, options});
    this.scrollY = options.top;
  },
};
const timeouts = [];
const listeners = {};
const documentListeners = {};
const elementListeners = {};
const elements = new Map();
let hitTestCard = null;
function addListener(registry, key, name, fn) {
  if (!registry[key]) registry[key] = {};
  if (!registry[key][name]) registry[key][name] = [];
  registry[key][name].push(fn);
}
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: '', textContent: '', disabled: false,
    focus() {},
    addEventListener(name, fn) { addListener(elementListeners, id, name, fn); },
    set innerHTML(html) {
      if (id === 'sessions') {
        writes++;
        cards = [...html.matchAll(/class="agent ([^"]*)"\s+data-session="([^"]*)"/g)]
          .map(([, cls, session]) => {
            const classes = new Set(cls.trim().split(/\s+/));
            return {
              dataset: {session},
              classList: {
                contains: c => classes.has(c),
                toggle(c, enabled) { if (enabled) classes.add(c); else classes.delete(c); },
                add: c => classes.add(c), remove: c => classes.delete(c),
              },
              getBoundingClientRect: () => ({
                top: cardPositions[session] - viewport.scrollY,
                bottom: cardPositions[session] - viewport.scrollY + 60,
              }),
            };
          });
      }
      this.html = html;
    },
    get innerHTML() { return this.html || ''; },
  });
  return elements.get(id);
}
const context = vm.createContext({
  document: {
    hasFocus: () => false,
    getElementById: element,
    addEventListener(name, fn) { addListener(documentListeners, 'document', name, fn); },
    elementFromPoint: () => hitTestCard,
    querySelectorAll: () => cards,
    querySelector: selector => selector === '.agent.current'
      ? cards.find(card => card.classList.contains('current')) : cards[0],
    createElement: () => {
      escapeElements++;
      return { set textContent(s) { this.innerHTML = s; } };
    },
  },
  window: viewport,
  fetch: url => {
    if (url.startsWith('/api/focus')) {
      focusRequests.push(url);
      return Promise.resolve({ ok: true });
    }
    return new Promise(() => {});
  },
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
    contains: c => classes.has(c),
    toggle(c, enabled) { if (enabled) classes.add(c); else classes.delete(c); },
    add: c => classes.add(c), remove: c => classes.delete(c),
  },
  querySelector: selector => selector === '.status'
    ? status : { remove() { hintRemoved = true; } },
  getBoundingClientRect: () => ({
    top: cardPositions.one - viewport.scrollY,
    bottom: cardPositions.one - viewport.scrollY + 60,
  }),
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
assert.equal(scrolls.length, 1, 'refocusing an already visible card must not scroll');
assert.equal(scrolls[0].options.top, 1470);
assert.equal(cardPositions.one - viewport.scrollY, 180, 'card top must land one-fifth down');
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
  const pressedCard = { dataset: {session: 'two'} };
  const currentClickCard = {
    dataset: {session: 'one'},
    closest: selector => selector === '.agent' ? currentClickCard : null,
  };
  hitTestCard = currentClickCard;
  const beforePress = focusRequests.length;
  documentListeners.document.pointerdown[0]({
    target: { closest: selector => selector === '.agent' ? pressedCard : null },
    button: 0,
    pointerType: 'mouse',
    clientX: 42,
    clientY: 84,
  });
  assert.equal(
    focusRequests.length, beforePress + 1,
    'a press must activate even when WebKit never dispatches pointerup or click',
  );
  assert.equal(new URL('http://panel' + focusRequests.at(-1)).searchParams.get('session'), 'two');
  elementListeners.sessions.click[0]({
    detail: 1,
    clientX: 42,
    clientY: 300,
    target: {
      closest: selector => selector === '.agent' ? currentClickCard : null,
    },
  });
  documentListeners.document.pointerup[0]();
  while (timeouts.length) timeouts.shift()();
  await Promise.resolve();
  const captured = new URL('http://panel' + focusRequests.at(-1));
  assert.equal(
    captured.searchParams.get('session'),
    'one',
    'a stale press from another window must not replace the current hit target',
  );

  const beforeCompleteClick = focusRequests.length;
  documentListeners.document.pointerdown[0]({
    target: { closest: selector => selector === '.agent' ? currentClickCard : null },
    button: 0, pointerType: 'mouse', clientX: 42, clientY: 300,
  });
  elementListeners.sessions.click[0]({
    detail: 1, clientX: 42, clientY: 300,
    target: { closest: selector => selector === '.agent' ? currentClickCard : null },
  });
  assert.equal(focusRequests.length, beforeCompleteClick + 1,
    'one press/click sends one activation');

  const beforeRightClick = focusRequests.length;
  documentListeners.document.pointerdown[0]({
    target: { closest: selector => selector === '.agent' ? currentClickCard : null },
    button: 2, pointerType: 'mouse', clientX: 42, clientY: 300,
  });
  assert.equal(focusRequests.length, beforeRightClick,
    'right-click must only open the action menu');
  elementListeners.sessions.click[0]({
    detail: 0, clientX: 0, clientY: 0,
    target: { closest: selector => selector === '.agent' ? pressedCard : null },
  });
  assert.equal(new URL('http://panel' + focusRequests.at(-1)).searchParams.get('session'), 'two',
    'keyboard activation uses its selected card rather than screen coordinates');
  documentListeners.document.pointerup[0]();
  while (timeouts.length) timeouts.shift()();
  await Promise.resolve();

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

  element('search').value = '';
  vm.runInContext(`
    allSessions[0].focused = false; allSessions[1].focused = true; filterSessions();
  `, context);
  assert.equal(scrolls.at(-1).session, 'two', 'polls must reveal focus without an SSE event');
  let scrollCount = scrolls.length;
  vm.runInContext('filterSessions(); filterSessions()', context);
  assert.equal(scrolls.length, scrollCount, 'unchanged polls must allow manual scrolling');

  vm.runInContext("toggleGroup('')", context);
  assert.ok(!element('sessions').innerHTML.includes('class="agent '));
  listeners['focus-changed']({data: JSON.stringify({focused: ['one']})});
  assert.equal(scrolls.at(-1).session, 'one');
  assert.ok(element('sessions').innerHTML.includes('class="agent '), 'focus opens its group');

  element('search').value = 'hidden';
  vm.runInContext('filterSessions()', context);
  listeners['focus-changed']({data: JSON.stringify({focused: ['two']})});
  scrollCount = scrolls.length;
  listeners['focus-changed']({data: JSON.stringify({focused: ['one']})});
  assert.equal(element('search').value, 'hidden', 'focus must preserve the search filter');
  assert.equal(scrolls.length, scrollCount, 'excluded cards cannot be scrolled into view');
  element('search').value = '';
  vm.runInContext('filterSessions()', context);
  assert.equal(scrolls.at(-1).session, 'one', 'clearing search must reveal pending focus');

  for (const guard of ['pointerDown', 'labelEditorOpen', 'ctxMenu']) {
    listeners['focus-changed']({data: JSON.stringify({focused: ['one']})});
    vm.runInContext(`${guard} = true`, context);
    scrollCount = scrolls.length;
    listeners['focus-changed']({data: JSON.stringify({focused: ['two']})});
    assert.equal(scrolls.length, scrollCount, 'focus must not jump during an interaction');
    vm.runInContext(`${guard} = false; filterSessions()`, context);
    assert.equal(scrolls.length, scrollCount + 1);
    assert.equal(scrolls.at(-1).session, 'two');
  }
  const visibilityCases = [[0, false], [180, false], [840, false], [-1, true], [841, true]];
  for (const [top, mustScroll] of visibilityCases) {
    listeners['focus-changed']({data: JSON.stringify({focused: []})});
    viewport.scrollY = 600;
    cardPositions.one = viewport.scrollY + top;
    scrollCount = scrolls.length;
    listeners['focus-changed']({data: JSON.stringify({focused: ['one']})});
    assert.equal(scrolls.length, scrollCount + Number(mustScroll), 'scroll only clipped cards');
    if (mustScroll) assert.equal(cardPositions.one - viewport.scrollY, 180);
    else assert.equal(viewport.scrollY, 600, 'keep the existing view for visible cards');
  }
  listeners['focus-changed']({data: JSON.stringify({focused: []})});
  cardPositions.one = 100;
  viewport.scrollY = 400;
  listeners['focus-changed']({data: JSON.stringify({focused: ['one']})});
  assert.equal(scrolls.at(-1).options.top, 0, 'scrolling must clamp at the start of the list');
})().catch(error => { console.error(error); process.exitCode = 1; });
""",
        ],
        input=json.dumps(script),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
