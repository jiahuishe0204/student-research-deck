const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const web = process.env.RESEARCH_HOME_WEB_DIR || path.join(__dirname, '../web');
const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
const script = fs.readFileSync(path.join(web, 'app.js'), 'utf8');
const remote = 'https://research.example';
const taskId = 'TASK-abcdef123456';
const taskKey = 'research-delivery.production-task.v1';
const localTaskKey = 'research-delivery.active-task.v1';
const topicKey = 'research-delivery.pending-topic.v1';
const tierKey = 'research-delivery.pending-tier.v1';
const saved = {[taskKey]: taskId, [localTaskKey]: '{"taskId":"demo","token":"mock"}', [topicKey]: '已有主题', [tierKey]: 'deep'};
const gateway = {ok: true, runtime: 'edgeone-gateway'};
const local = {ok: true, runtime_version: 'mock'};
const intent = {normalized_topic: '测试主题'};
const reply = (body, status = 200) => new Response(JSON.stringify(body), {status});
const settled = () => new Promise(resolve => setImmediate(resolve));

function element() {
  const listeners = new Map();
  return {
    listeners, value: '', disabled: false, hidden: true, dataset: {}, style: {},
    classList: {add() {}, toggle() {}},
    addEventListener(type, listener) { listeners.set(type, listener); },
    setAttribute() {}, focus() {}, scrollIntoView() {}, replaceChildren() {},
    checkValidity() { return true; },
  };
}

function home({url = remote, health, storage = {}} = {}) {
  const elements = new Map();
  const get = selector => {
    if (!elements.has(selector)) elements.set(selector, element());
    return elements.get(selector);
  };
  const form = get('#intent-form');
  const submit = get('.primary');
  form.querySelector = get;
  submit.disabled = /<button\b[^>]*class="primary"[^>]*\bdisabled\b/.test(html);
  get('#task').value = '新调研主题';
  get('input[name="tier"]:checked').value = 'fast';
  const state = new Map(Object.entries(storage));
  const sessionStorage = {
    getItem: key => state.get(key) ?? null,
    setItem: (key, value) => state.set(key, value),
    removeItem: key => state.delete(key),
  };
  const requests = [];
  const timers = new Map();
  const context = vm.createContext({
    document: {querySelector: get, querySelectorAll: () => [], addEventListener() {}},
    location: new URL(url), sessionStorage, AbortController, console,
    setTimeout(fn, delay) { timers.set(delay, fn); return delay; },
    clearTimeout: delay => timers.delete(delay),
    fetch: async (route, options = {}) => {
      const method = options.method || 'GET';
      requests.push({method, route, options});
      if (route === '/api/health') return health(options);
      if (route === '/auth/otp/request') return reply({challenge_id: 'challenge'});
      if (route === '/auth/otp/verify') return reply({csrf_token: 'mock-csrf'});
      if (route === '/api/intent') return reply({data: intent, intent_ticket: 'ticket'});
      if (route === '/tasks') return reply({data: {task_id: taskId}});
      if (route === '/api/tasks') return reply({data: {task_id: 'demo', owner_token: 'mock'}});
      if (route.endsWith('/progress')) return reply({data: {status: 'completed'}});
      if (route.includes('/tasks/')) return reply({data: null});
      throw new Error('Unexpected request ' + method + ' ' + route);
    },
  });
  vm.runInContext(script, context);
  async function fire(selector, type = 'click') {
    const target = get(selector);
    let prevented = false;
    await target.listeners.get(type)({currentTarget: target, preventDefault() { prevented = true; }});
    if (type === 'submit') assert.equal(prevented, true);
  }
  return {
    get, submit, context, state, requests, timers, fire,
    postRoutes: () => requests.filter(item => item.method === 'POST').map(item => item.route),
    // Model native activation: a disabled submit button blocks both click and implicit Enter.
    activate: () => !submit.disabled && fire('#intent-form', 'submit'),
    submitEvent: () => fire('#intent-form', 'submit'),
  };
}

test('initial HTML disables native activation while the deferred bundle loads', () => {
  assert.match(html, /<button class="primary" type="submit" disabled>/);
  assert.match(html, /id="service-status" role="status">正在连接服务…/);
});

test('pending health blocks click, Enter and a programmatic submit, then unlocks', async () => {
  const initial = {...saved};
  let finishHealth;
  const app = home({storage: initial, health: () => new Promise(resolve => { finishHealth = resolve; })});
  await app.activate(); // Click.
  await app.activate(); // Implicit Enter.
  await app.submitEvent(); // Synthetic submit bypasses the HTML control.
  assert.deepEqual(app.postRoutes(), []);
  assert.deepEqual(Object.fromEntries(app.state), initial);
  assert.equal(app.submit.disabled, true);
  assert.equal(app.get('#task').value, '新调研主题');
  finishHealth(reply(gateway));
  await settled();
  assert.equal(app.submit.disabled, false);
});

const unavailable = [
  ['503', () => reply({...gateway, ok: false}, 503)],
  ['404', () => reply({}, 404)],
  ['HTML', () => new Response('<!doctype html><title>Fallback</title>')],
  ['unhealthy gateway with HTTP 200', () => reply({...gateway, ok: false})],
  ['wrong gateway', () => reply({ok: true, runtime: 'another-gateway'})],
  ['healthy demo endpoint on a remote host', () => reply(local)],
  ['network error', () => { throw new TypeError('Mock fetch failed'); }],
];
for (const [name, health] of unavailable) {
  test('remote home fails closed after ' + name, async () => {
    const app = home({url: 'https://preview.example', storage: saved, health});
    await settled();
    await app.submitEvent();
    assert.deepEqual(app.postRoutes(), []);
    assert.deepEqual(Object.fromEntries(app.state), saved);
    assert.equal(app.submit.disabled, true);
    assert.equal(app.get('#task').value, '新调研主题');
    assert.match(app.get('#error').textContent, /刷新/);
  });
}

test('a stalled health response body has a finite wait and preserves session', async () => {
  const app = home({storage: saved, health: ({signal} = {}) => ({
    ok: true,
    json: () => new Promise((_resolve, reject) => {
      signal?.addEventListener('abort', () => reject(signal.reason), {once: true});
    }),
  })});
  await settled();
  assert.equal(app.timers.size, 1);
  const [delay, timeout] = [...app.timers][0];
  assert.equal(delay, 12000);
  timeout();
  await settled();
  await app.submitEvent();
  assert.deepEqual(app.postRoutes(), []);
  assert.deepEqual(Object.fromEntries(app.state), saved);
  assert.equal(app.submit.disabled, true);
  assert.match(app.get('#error').textContent, /刷新/);
  assert.equal(app.timers.size, 0);
});

test('pending and blocked modes refuse stale recovery controls', async () => {
  let finishHealth;
  const app = home({storage: saved, health: () => new Promise(resolve => { finishHealth = resolve; })});
  vm.runInContext("currentTaskId = 'TASK-abcdef123456'", app.context);
  await app.fire('#cancel-task');
  await app.fire('#resume-task');
  finishHealth(reply({}, 503));
  await settled();
  await app.fire('#cancel-task');
  await app.fire('#resume-task');
  assert.deepEqual(app.requests.map(item => item.route), ['/api/health']);
  assert.deepEqual(Object.fromEntries(app.state), saved);
});

test('healthy production submits through email, intent and confirmed creation', async () => {
  const app = home({health: () => reply(gateway)});
  await settled();
  assert.equal(app.submit.disabled, false);
  await app.submitEvent();
  assert.equal(app.state.get(topicKey), '新调研主题');
  assert.equal(app.get('#production-auth').hidden, false);
  assert.deepEqual(app.postRoutes(), []);
  app.get('#auth-email').value = 'reader@example.test';
  app.get('#auth-code').value = '123456';
  await app.fire('#request-code');
  await app.fire('#verify-code');
  assert.deepEqual(app.postRoutes(), ['/auth/otp/request', '/auth/otp/verify', '/api/intent']);
  await app.fire('#confirm');
  await settled();
  assert.deepEqual(app.postRoutes(), [
    '/auth/otp/request', '/auth/otp/verify', '/api/intent', '/tasks', '/tasks/' + taskId + '/continue',
  ]);
  assert.equal(app.state.get(taskKey), taskId);
  assert.equal(app.state.has(topicKey), false);
  assert.equal(app.requests.find(item => item.route === '/tasks').options.headers['X-CSRF-Token'], 'mock-csrf');
  assert.ok(app.requests.some(item => item.method === 'GET' && item.route === '/tasks/' + taskId + '/progress'));
});

test('healthy production restores a saved task and retries on the production route only', async () => {
  const app = home({storage: {[taskKey]: taskId, research_csrf_token: 'mock-csrf'}, health: () => reply(gateway)});
  await settled();
  await app.fire('#cancel-task');
  await app.fire('#resume-task');
  assert.deepEqual(app.postRoutes(), ['/tasks/' + taskId + '/retry']);
  assert.ok(app.requests.some(item => item.method === 'GET' && item.route === '/tasks/' + taskId + '/progress'));
});

for (const host of ['localhost', '127.0.0.1', '[::1]']) {
  test('healthy loopback demo on ' + host + ' retains its local request routes', async () => {
    const app = home({url: 'http://' + host + ':4180', health: () => reply(local)});
    await settled();
    assert.equal(app.submit.disabled, false);
    await app.submitEvent();
    assert.deepEqual(app.postRoutes(), ['/api/tasks', '/api/intent', '/api/tasks/demo/events']);
    await app.fire('#cancel-task');
    await app.fire('#resume-task');
    assert.deepEqual(app.postRoutes().slice(-2), ['/api/tasks/demo/cancel', '/api/tasks/demo/resume']);
  });
}

test('file preview rejects programmatic submission before any network call', async () => {
  const app = home({url: 'file:///preview/index.html', storage: saved});
  await app.submitEvent();
  assert.deepEqual(app.requests, []);
  assert.deepEqual(Object.fromEntries(app.state), saved);
  assert.equal(app.submit.disabled, true);
  assert.match(app.get('#error').textContent, /文件预览/);
});
