const fs = require('fs');

global.window = {
  focus: () => { console.log('[window.focus() called]') }
};
const toastDiv = { style: {} };
global.document = {
  getElementById: (id) => id === '__apl_toast__' ? toastDiv : null,
  createElement: (tag) => toastDiv,
  body: {
    appendChild: (el) => {},
    contains: () => false,
  },
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener: () => {}
};
global.location = {
  hostname: 'seller.tiktok.com',
  pathname: '/order'
};
global.setTimeout = setTimeout;
global.clearTimeout = clearTimeout;
global.console.log = (...args) => process.stdout.write(args.join(' ') + '\n');
global.console.error = (...args) => process.stderr.write(args.join(' ') + '\n');

const gmStorage = {};
const gmListeners = [];

global.GM_setValue = (k, v) => {
  gmStorage[k] = v;
  console.log(`[GM_setValue] ${k} = ${v}`);
  gmListeners.forEach(l => {
    if (l.key === k) l.fn(k, undefined, v);
  });
};

global.GM_getValue = (k) => {
  return gmStorage[k];
};

global.GM_deleteValue = (k) => {
  delete gmStorage[k];
  console.log(`[GM_deleteValue] ${k}`);
};

global.GM_addValueChangeListener = (k, fn) => {
  gmListeners.push({key: k, fn: fn});
};

let wsInstance = null;
class MockWebSocket {
  constructor(url) {
    this.url = url;
    console.log(`[WS] Connecting to ${url}`);
    wsInstance = this;
    setTimeout(() => { if (this.onopen) this.onopen(); }, 10);
  }
}
global.WebSocket = MockWebSocket;

Object.defineProperty(toastDiv, 'textContent', {
  set(val) { console.log(`[Toast] "${val}"`); }
});

const scriptContent = fs.readFileSync('combined-auto-print.user.js', 'utf8');

// Expose TAB_ID out of IIFE for testing
const modifiedScript = scriptContent.replace(
  "var TAB_ID =", "global.TAB_ID ="
);

try {
  eval(modifiedScript);
} catch(e) {
  console.error("Script eval error:", e);
}

setTimeout(() => {
  console.log("\n--- TEST 1: Baseline v1 string ---");
  wsInstance.onmessage({ data: "MZS-240278" });
  
  setTimeout(() => {
    console.log("\n--- TEST 2: v2 JSON frame (TikTok with shop) ---");
    wsInstance.onmessage({ data: JSON.stringify({order:"123456789012345678", platform:"tiktok", shop:{name:"ร้าน B"}}) });
    
    setTimeout(() => {
      console.log("\n--- TEST 3: Cross-tab relay claim (2 tabs same platform) ---");
      global.location.hostname = 'seller.tiktok.com';
      const jobPayload = {
        jobId: "job999",
        platform: "tiktok",
        orderNumber: "123456789012345678",
        ts: Date.now()
      };
      
      console.log("> Tab 1 (Current Tab) receives cross-tab event...");
      gmListeners[0].fn('auto_print_job', undefined, JSON.stringify(jobPayload));
      
      console.log("> Tab 2 receives cross-tab event at the exact same time...");
      const realTabId = global.TAB_ID;
      global.TAB_ID = "mockTab2"; // Fake tab 2 ID
      gmListeners[0].fn('auto_print_job', undefined, JSON.stringify(jobPayload));
      global.TAB_ID = realTabId; // Restore tab 1 ID
      
    }, 500);
  }, 500);
}, 100);
