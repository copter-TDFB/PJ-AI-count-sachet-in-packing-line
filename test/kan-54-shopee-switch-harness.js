const assert = require('assert');
const fs = require('fs');
const nodeConsole = console;

const source = fs.readFileSync('combined-auto-print.user.js', 'utf8').replace(
  /\}\)\(\);\s*$/,
  'global.__kan54 = { shopTextMatches, getShopeeSwitchJob, runShopeeSwitchJob, SHOPEE_SWITCH_JOB_KEY, J };\n})();\n'
);

function makeElement(text, onClick, parent) {
  return {
    textContent: text,
    innerText: text,
    parentElement: parent || null,
    disabled: false,
    classList: { contains: () => false },
    getAttribute: () => null,
    getBoundingClientRect: () => ({ left: 1100, top: 30, width: 120, height: 32 }),
    click: onClick || (() => {}),
    focus: () => {},
    dispatchEvent: () => {},
  };
}

function makeEnvironment(initialPhase) {
  const storage = {};
  const events = [];
  const clicks = [];
  let phase = initialPhase;
  const orderNumber = 'ABCD1234';
  const profile = makeElement('Shop B\nlogin-account', () => {
    clicks.push('profile'); phase = 'dropdown';
  });
  const switchShop = makeElement('สลับร้านค้า', () => {
    clicks.push('switch'); phase = 'list';
  });
  const row = makeElement('Shop B account-name');
  const details = makeElement('รายละเอียด', () => {
    clicks.push('details'); phase = 'dashboard';
  }, row);
  const orders = makeElement('คำสั่งซื้อ', () => {
    clicks.push('orders'); phase = 'submenu';
  });
  const myOrders = makeElement('คำสั่งซื้อของฉัน', () => {
    clicks.push('my-orders'); phase = 'orders-page';
  });
  const allFilters = [0, 1, 2].map((n) => makeElement('ทั้งหมด', () => clicks.push(`all-${n}`)));
  const printButton = makeElement('พิมพ์ใบปะหน้า', () => clicks.push('print'));
  const input = makeElement('', () => {});
  input.focus = () => events.push('run-search');
  const card = makeElement(orderNumber);
  const toast = { style: {} };
  const body = {
    appendChild: () => {},
    contains: () => true,
    get textContent() {
      return phase === 'list' ? 'เลือกร้านที่จะจัดการ' : '';
    },
    get innerText() { return this.textContent; },
  };

  function controls() {
    if (phase === 'dropdown') return [switchShop];
    if (phase === 'list') return [details];
    if (phase === 'dashboard') return [orders];
    if (phase === 'submenu') return [myOrders];
    if (phase === 'orders-page') return [...allFilters, profile, printButton];
    return [profile];
  }

  global.window = { innerWidth: 1280, focus: () => {}, addEventListener: () => {} };
  global.location = { hostname: 'seller.shopee.co.th', pathname: '/orders' };
  global.document = {
    body,
    readyState: 'complete',
    getElementById: (id) => id === '__apl_toast__' ? toast : null,
    createElement: () => toast,
    addEventListener: () => {},
    querySelector: () => null,
    querySelectorAll: (selector) => {
      if (selector === 'body') return [body];
      if (selector.includes('input')) return [input];
      if (selector.includes('order-card') || selector.includes('order-item-infos') || selector.includes('data-testid')) return [card];
      if (selector === 'button') return controls().filter((el) => el === printButton);
      return controls();
    },
  };
  global.HTMLInputElement = function HTMLInputElement() {};
  Object.defineProperty(global.HTMLInputElement.prototype, 'value', { get() { return this._value || ''; }, set(v) { this._value = v; } });
  global.Event = function Event() {};
  global.KeyboardEvent = function KeyboardEvent() {};
  global.WebSocket = function WebSocket() {};
  global.MutationObserver = function MutationObserver() { this.observe = () => {}; this.disconnect = () => {}; };
  global.GM_setValue = (key, value) => { storage[key] = value; events.push(`set:${key}`); };
  global.GM_getValue = (key) => storage[key];
  global.GM_deleteValue = (key) => { delete storage[key]; events.push(`delete:${key}`); };
  global.GM_addValueChangeListener = () => {};
  global.console = { log: () => {}, error: () => {} };

  eval(source);
  global.__kan54.J.click = [0, 0];
  global.__kan54.J.input = [0, 0];
  global.__kan54.J.confirm = [0, 0];
  return { api: global.__kan54, storage, events, clicks, input };
}

async function runStep(step, phase, expectedClick) {
  const env = makeEnvironment(phase);
  const job = {
    jobId: `job-${step}`,
    orderNumber: 'ABCD1234',
    targetShopHint: 'shop b',
    step,
    expiresAt: Date.now() + 5 * 60 * 1000,
  };
  env.storage[env.api.SHOPEE_SWITCH_JOB_KEY] = JSON.stringify(job);
  await env.api.runShopeeSwitchJob(env.api.getShopeeSwitchJob());
  assert.strictEqual(env.clicks[0], expectedClick, `${step} should attempt ${expectedClick}`);
  assert.ok(!env.storage[env.api.SHOPEE_SWITCH_JOB_KEY], `${step} should clear the switch job before search`);
  const cleared = env.events.lastIndexOf(`delete:${env.api.SHOPEE_SWITCH_JOB_KEY}`);
  assert.ok(cleared >= 0, `${step} should delete the switch job`);
  return { env, cleared };
}

(async () => {
  const matcher = makeEnvironment('profile').api.shopTextMatches;
  assert.strictEqual(matcher('Shop B account-name', 'shop b'), true);
  assert.strictEqual(matcher('Shop B account-name', 'unknown-co'), false);
  nodeConsole.log('PASS matcher: case-insensitive substring and unknown shop');

  const cases = [
    ['open_profile', 'profile', 'profile'],
    ['profile_clicked', 'dropdown', 'switch'],
    ['shop_list', 'list', 'details'],
    ['shop_selected', 'dashboard', 'orders'],
    ['orders_opened', 'submenu', 'my-orders'],
    ['orders_page', 'orders-page', 'all-0'],
  ];
  for (const [step, phase, expected] of cases) await runStep(step, phase, expected);
  nodeConsole.log('PASS state machine: all persisted steps attempt their expected next action');

  const ttl = makeEnvironment('profile');
  ttl.storage[ttl.api.SHOPEE_SWITCH_JOB_KEY] = JSON.stringify({
    jobId: 'expired', orderNumber: 'ABCD1234', targetShopHint: 'shop b',
    step: 'open_profile', expiresAt: Date.now() - 1,
  });
  assert.strictEqual(ttl.api.getShopeeSwitchJob(), null);
  assert.deepStrictEqual(ttl.clicks, []);
  nodeConsole.log('PASS TTL: expired job is cleared and never clicks');

  const final = await runStep('orders_page', 'orders-page', 'all-0');
  const firstSearch = final.env.events.indexOf('run-search');
  assert.ok(final.cleared >= 0 && firstSearch >= 0, 'final flow should clear then invoke normal Shopee search/print');
  assert.ok(final.cleared < firstSearch, 'switch job must be deleted before normal Shopee search begins');
  nodeConsole.log('PASS clearing: switch job is deleted before normal Shopee search/print runs');
})().catch((err) => {
  process.stderr.write(`FAIL ${err.stack}\n`);
  process.exitCode = 1;
});
