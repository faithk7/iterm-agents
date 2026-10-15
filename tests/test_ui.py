"""Exercise the embedded panel script without adding a browser dependency."""

import json
import shutil
import subprocess

import pytest

from iterm_agents.ui import AGENT_MONITOR_HTML


def test_panels_bind_independently_before_cross_window_activation() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to exercise the panel JavaScript")
    script = AGENT_MONITOR_HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    result = subprocess.run(
        [node, "-e", r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const script = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
let keyWindow = 'w1';
const focus = {w1: 'one', w2: 'two'};
const activations = [];
function makePanel(savedName = '', probeRule = true) {
  const elements = new Map();
  const documentEvents = {};
  const requests = [];
  const sources = [];
  const timeouts = [];
  let resolveBinding;
  let resolveInitialPoll;
  let ownerKey = false;
  let clock = 1000;
  let probeReads = 0;
  // iTerm2's WebView may report false even during an actual panel click.
  const hasFocus = false;
  const windowEvents = {};
  const rows = [
    {id: 'one', name: 'one', agent_state: 'idle', window_id: 'w1'},
    {id: 'two', name: 'two', agent_state: 'idle', window_id: 'w2'},
  ];
  const document = {
    styleSheets: [{cssRules: [{selectorText: '#owner-probe::-webkit-scrollbar'},
      ...(probeRule ? [{selectorText: '#owner-probe::-webkit-scrollbar:window-inactive'}] : [])]}],
    hasFocus: () => hasFocus,
    addEventListener(name, fn) {(documentEvents[name] ||= []).push(fn);},
    querySelectorAll: () => [], querySelector: () => null,
    createElement: () => ({set textContent(s) {this.innerHTML = s;}}),
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, {
        value: '', innerHTML: '', focus() {}, select() {}, addEventListener() {},
        style: {}, offsetWidth: 50,
        get clientWidth() { probeReads++; return ownerKey ? 49 : 48; },
      });
      return elements.get(id);
    },
  };
  const context = vm.createContext({
    Date: class extends Date { static now() { return clock; } },
    document, window: {
      name: savedName,
      location: {protocol: 'http:', host: 'panel'},
      addEventListener(name, fn) {(windowEvents[name] ||= []).push(fn);}, innerHeight: 900,
    },
    setInterval() {}, setTimeout(fn, ms) {timeouts.push({fn, ms});},
    WebSocket: class {
      constructor(url) { this.url = url; sources.push(this); }
      close() {this.closed = true;}
      emit(event, data = {}) {this.onmessage({data: JSON.stringify({event, data})});}
    },
    fetch(url) {
      requests.push(url);
      if (url === '/api/panel-window') {
        const sourceWindow = keyWindow;
        return new Promise(resolve => { resolveBinding = () => resolve({
          ok: true, json: async () => ({window_id: sourceWindow}),
        }); });
      }
      if (url.startsWith('/api/focus')) {
        const session = new URL('http://panel' + url).searchParams.get('session');
        activations.push(session);
        keyWindow = rows.find(row => row.id === session).window_id;
        return Promise.resolve({ok: true});
      }
      if (url.startsWith('/api/sessions') &&
          !new URL('http://panel' + url).searchParams.has('window')) {
        return new Promise(resolve => { resolveInitialPoll = () => resolve({
          json: async () => rows.map(row => ({...row, focused: false})),
        }); });
      }
      const windowId = new URL('http://panel' + url).searchParams.get('window');
      return Promise.resolve({headers: {
        get: () => rows.some(row => row.window_id === windowId) ? 'present' : 'missing',
      }, json: async () => rows.map(row => ({
        ...row, focused: row.id === focus[windowId],
      }))});
    },
  });
  vm.runInContext(script, context);
  return {context, requests, sources, timeouts, documentEvents,
    bind: () => resolveBinding(), initialPoll: () => resolveInitialPoll(),
    setOwnerKey: key => { ownerKey = key; },
    probe: () => { clock += 1000; vm.runInContext('checkOwnerWindow()', context); },
    tick: () => { clock += 250; vm.runInContext('checkOwnerWindow()', context); },
    probeReads: () => probeReads,
    advance: ms => { clock += ms; },
    loseFocus: () => windowEvents.blur.forEach(fn => fn())};
}
async function settle() {for (let i = 0; i < 12; i++) await Promise.resolve();}
(async () => {
  const a = makePanel();
  assert.ok(!a.requests.includes('/api/panel-window'), 'loading cannot guess the owner');
  assert.equal(vm.runInContext("document.getElementById('focus-hint').hidden", a.context),
    false, 'an unbound panel must show its first-click instruction');
  a.documentEvents.pointerdown.forEach(fn => fn({target: {closest: () => null}, button: 0}));
  assert.equal(vm.runInContext("document.getElementById('focus-hint').textContent", a.context),
    'Connecting focus marker…');
  const firstClick = vm.runInContext("focusSession('two')", a.context);
  assert.equal(activations.length, 0, 'binding must finish before activating another window');
  a.bind();
  await firstClick;
  a.loseFocus();
  assert.equal(keyWindow, 'w2');
  assert.equal(vm.runInContext('panelWindowId', a.context), 'w1');
  assert.equal(vm.runInContext("document.getElementById('focus-hint').hidden", a.context), true,
    'successful binding removes the instruction');
  const b = makePanel();
  const binding = vm.runInContext('bindPanelWindow()', b.context);
  b.bind();
  await binding;
  assert.equal(vm.runInContext('panelWindowId', b.context), 'w2');
  for (const [panel, owner] of [[a, 'w1'], [b, 'w2']]) {
    assert.equal(panel.sources.at(-1).url, 'ws://panel/api/ws?window=' + owner);
    assert.ok(panel.sources[0].closed, 'binding replaces the unscoped event stream');
    panel.initialPoll();
    await settle();
    assert.equal(vm.runInContext('allSessions.length', panel.context), 2,
      'a binding completed during startup must refetch without waiting for the poll timer');
    await vm.runInContext('loadSessions()', panel.context);
    assert.deepEqual(Array.from(vm.runInContext('allSessions.map(s => s.focused)', panel.context)),
      owner === 'w1' ? [true, false] : [false, true]);
    assert.ok(vm.runInContext("document.getElementById('sessions').innerHTML", panel.context)
      .includes('idle current'), 'the bound panel must render the blue current-pane indicator');
    const requestsBefore = panel.requests.length;
    panel.sources.at(-1).emit('sessions-changed');
    await settle();
    assert.equal(panel.requests.length, requestsBefore + 1,
      'a completed scan updates the panel immediately without its polling timer');
    assert.ok(panel.requests.at(-1).includes('cached=1'));
  }
  keyWindow = 'w2';
  await vm.runInContext('bindPanelWindow()', a.context);
  assert.equal(vm.runInContext('panelWindowId', a.context), 'w1',
    'ownership cannot follow the key window');
  assert.equal(a.requests.filter(url => url === '/api/panel-window').length, 1);
  for (const [panel, owner] of [[a, 'w1'], [b, 'w2']]) {
    const savedName = vm.runInContext('window.name', panel.context);
    const reloaded = makePanel(savedName);
    await settle();
    assert.equal(vm.runInContext('panelWindowId', reloaded.context), owner,
      'a reload restores its own owner even when another window is key');
    assert.equal(reloaded.sources[0].url, 'ws://panel/api/ws?window=' + owner);
    assert.ok(!reloaded.requests.includes('/api/panel-window'),
      'restoring a known owner requires no simulated click or focus handshake');
    assert.ok(vm.runInContext("document.getElementById('sessions').innerHTML", reloaded.context)
      .includes('idle current'), 'restored binding renders the marker without interaction');
  }
  const stale = makePanel('iterm-agents:window:closed-window');
  await settle();
  assert.equal(vm.runInContext('panelWindowId', stale.context), '',
    'a closed owner is discarded instead of binding to the current window');
  assert.equal(vm.runInContext('window.name', stale.context), '');
  assert.equal(vm.runInContext("document.getElementById('focus-hint').hidden", stale.context),
    false);
  const newWindow = makePanel('iterm-agents:window:w2');
  await settle();
  newWindow.context.fetch = () => Promise.resolve({
    headers: {get: () => 'present'},
    json: async () => [{id: 'one', window_id: 'w1', agent_state: 'idle'}],
  });
  await vm.runInContext('loadSessions()', newWindow.context);
  assert.equal(vm.runInContext('panelWindowId', newWindow.context), 'w2',
    'an older cached list must not invalidate a newly confirmed window binding');
  const c = makePanel();
  const abortedBinding = vm.runInContext('bindPanelWindow()', c.context);
  c.loseFocus(); c.bind();
  assert.equal(await abortedBinding, false,
    'a window switch during binding must not assign the wrong owner');
  assert.equal(vm.runInContext('panelWindowId', c.context), '');
  assert.equal(vm.runInContext("document.getElementById('focus-hint').textContent", c.context),
    'Focus connection failed. Click here to retry.');
  c.documentEvents.keydown.forEach(fn => fn({key: 'x'}));
  c.bind();
  await settle();
  assert.equal(vm.runInContext('panelWindowId', c.context), keyWindow,
    'actual keyboard interaction can also bind the panel');
  keyWindow = 'w1';
  const d = makePanel(), e = makePanel();
  d.setOwnerKey(true);
  d.probe(); e.probe();
  assert.ok(!e.requests.includes('/api/panel-window'),
    'a panel whose own window is not key never asks for the current window');
  d.bind();
  await settle();
  assert.equal(vm.runInContext('panelWindowId', d.context), 'w1');
  keyWindow = 'w2';
  d.setOwnerKey(false); e.setOwnerKey(true);
  d.probe(); e.probe();
  e.bind();
  await settle();
  assert.equal(vm.runInContext('panelWindowId', d.context), 'w1',
    'another window becoming key leaves a bound panel alone');
  assert.equal(vm.runInContext('panelWindowId', e.context), 'w2',
    'each panel binds without a click once its own window is key');
  const f = makePanel();
  f.setOwnerKey(true);
  f.probe();
  f.setOwnerKey(false);
  f.bind();
  await settle();
  assert.equal(vm.runInContext('panelWindowId', f.context), '',
    'losing key status during the handshake must not assign an owner');
  assert.ok(!['Connecting focus marker…', 'Focus connection failed. Click here to retry.']
    .includes(vm.runInContext("document.getElementById('focus-hint').textContent", f.context)),
    'background attempts leave the hint alone');
  keyWindow = 'w1';
  d.setOwnerKey(true);
  d.probe(); d.probe();
  assert.equal(d.requests.filter(url => url === '/api/panel-window').length, 2,
    'a bound panel rechecks once per activation, not on every tick');
  d.bind();
  await settle();
  assert.equal(vm.runInContext('panelWindowId', d.context), 'w1');
  vm.runInContext("panelWindowId = 'w2'", d.context);
  d.setOwnerKey(false); d.probe();
  d.setOwnerKey(true); d.probe();
  d.bind();
  await settle();
  assert.equal(vm.runInContext('panelWindowId', d.context), 'w1',
    'a wrong binding corrects itself the next time its window is key');
  assert.equal(vm.runInContext('window.name', d.context), 'iterm-agents:window:w1');
  const beforeIdleReads = d.probeReads();
  const beforeIdleRequests = d.requests.length;
  for (let i = 0; i < 100; i++) d.tick();
  assert.ok(d.probeReads() - beforeIdleReads <= 25,
    'bound panels rebuild the scrollbar at most once a second');
  assert.equal(d.requests.length, beforeIdleRequests,
    'staying in a bound window requires no further handshakes');
  const noRule = makePanel('', false);
  noRule.setOwnerKey(true);
  noRule.probe();
  assert.ok(!noRule.requests.includes('/api/panel-window'),
    'without the :window-inactive rule every panel reads as key, so never auto-bind');
  const restored = makePanel('iterm-agents:window:w1');
  await settle();
  const oldSocket = restored.sources.at(-1);
  oldSocket.onerror(); oldSocket.onclose();
  assert.equal(restored.timeouts.filter(timer => timer.ms === 3000).length, 1,
    'a failed socket schedules only one reconnect');
  restored.timeouts.find(timer => timer.ms === 3000).fn();
  oldSocket.emit('focus-changed', {window_id: 'w1', focused: []});
  assert.deepEqual(Array.from(vm.runInContext('allSessions.map(s => s.focused)', restored.context)),
    [true, false], 'a closed socket cannot overwrite the restored marker');
  restored.sources.at(-1).emit('focus-changed', {window_id: 'w1', focused: []});
  assert.deepEqual(Array.from(vm.runInContext('allSessions.map(s => s.focused)', restored.context)),
    [false, false], 'the reconnected socket delivers focus updates');
  const hidden = makePanel('iterm-agents:window:w1');
  await settle();
  const polls = () => hidden.requests.filter(url => url.startsWith('/api/sessions')).length;
  const before = polls();
  vm.runInContext('document.hidden = true', hidden.context);
  hidden.advance(1000);
  vm.runInContext('pollSessions()', hidden.context);
  await settle();
  assert.equal(polls(), before, 'a hidden panel skips one-second polls');
  hidden.advance(4000);
  vm.runInContext('pollSessions()', hidden.context);
  await settle();
  assert.equal(polls(), before + 1, 'a hidden panel still polls every five seconds');
  vm.runInContext('document.hidden = false', hidden.context);
  hidden.advance(1000);
  vm.runInContext('pollSessions()', hidden.context);
  await settle();
  assert.equal(polls(), before + 2, 'a visible panel polls every second');
})().catch(error => {console.error(error); process.exitCode = 1;});
"""],
        input=json.dumps(script), text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


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
  location: {protocol: 'http:', host: 'panel'},
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
    styleSheets: [],
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
  WebSocket: class {
    constructor() {
      listeners['focus-changed'] = e => this.onmessage({data: JSON.stringify({
        event: 'focus-changed', data: {window_id: 'w1', ...JSON.parse(e.data)},
      })});
    }
    close() {}
  },
});
vm.runInContext(script, context);
for (const [name, displayed] of [
  ['✳ Bd-knowledge — ~/Project', '✳ bd-knowledge'],
  ['Full System Update — ~', 'full System Update'],
  ['Recent Git Commits — /Users/qukai/My Project', 'recent Git Commits'],
  ['Review — pending', 'review — pending'],
  ['Merge latest main | iTerm', 'merge latest main'],
  ['Remove file path from content | iterm-agents', 'remove file path from content'],
  ['Summary | repo — ~/Project', 'summary'],
  ['Summary — ~/Project | repo', 'summary'],
  ['already lowercase', 'already lowercase'],
  ['Équipe API', 'équipe API'],
]) {
  context.sessionName = name;
  const html = vm.runInContext(
    "renderGroup('', '', [{id: 'case', name: sessionName, agent_state: 'idle'}])", context);
  assert.ok(html.includes(`<div class="session-name">${displayed}</div>`));
}
vm.runInContext(`allSessions = [
  {id: 'one', name: 'visible', agent_state: 'awaiting_user', awaiting_user: true, window_id: 'w1'},
  {id: 'two', name: 'hidden', agent_state: 'idle', window_id: 'w1'}
];`, context);
vm.runInContext("panelWindowId = 'w1'", context);
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
const beforeForeignFocus = scrolls.length;
listeners['focus-changed']({data: JSON.stringify({window_id: 'w2', focused: ['two']})});
assert.ok(classes.has('current'), 'another window cannot move this panel marker');
assert.equal(scrolls.length, beforeForeignFocus, 'another window cannot scroll this panel');
escapeElements = 0;
for (let i = 0; i < 100; i++) {
  listeners['focus-changed']({data: JSON.stringify({focused: ['one']})});
}
assert.equal(escapeElements, 0, 'duplicate focus events must skip HTML generation');
assert.equal(scrolls.length, beforeForeignFocus, 'duplicate events must not measure or scroll');
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
