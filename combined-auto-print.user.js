// ==UserScript==
// @name         Auto Print Label (Shopee + TikTok + Odoo)
// @namespace    http://tampermonkey.net/
// @version      1.8
// @description  Ctrl+V เลข order → auto-print ใบปะหน้า (รองรับ Shopee + TikTok + Odoo)
// @match        https://seller.shopee.co.th/*
// @match        https://seller.tiktok.com/*
// @match        https://seller-th.tiktok.com/*
// @match        https://tdfb.odoo.com/*
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_addValueChangeListener
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  // human-feel jitter หลัง condition met (ms) — ปรับได้
  var J = {
    input:   [80, 150],   // หลังพิมพ์ search (รอ React state sync)
    click:   [80, 200],   // ก่อนคลิก element
    confirm: [100, 250],  // ก่อนกด confirm / ปิดท้าย
  };

  // ────────────────────────────────────────────
  // FORMAT DETECTION
  // ────────────────────────────────────────────
  function detectPlatform(text) {
    if (/^\d{15,20}$/.test(text)) return 'tiktok';
    if (/^S\d{4,6}$/.test(text)) return 'odoo';
    if (/^[A-Z0-9]{6,25}$/i.test(text) && /[A-Za-z]/.test(text)) return 'shopee';
    return null;
  }

  function currentPlatform() {
    var h = location.hostname;
    if (h.includes('tiktok')) return 'tiktok';
    if (h.includes('shopee')) return 'shopee';
    if (h === 'tdfb.odoo.com') return 'odoo';
    return null;
  }

  // ────────────────────────────────────────────
  // SHARED UTILITIES
  // ────────────────────────────────────────────
  function jitter(range) {
    return Math.floor(Math.random() * (range[1] - range[0] + 1)) + range[0];
  }

  function sleep(ms) {
    return new Promise(function (r) { setTimeout(r, ms); });
  }

  function showToast(msg, type) {
    var el = document.getElementById('__apl_toast__');
    if (!el) {
      el = document.createElement('div');
      el.id = '__apl_toast__';
      Object.assign(el.style, {
        position: 'fixed', top: '20px', right: '20px',
        zIndex: '2147483647', padding: '12px 18px',
        borderRadius: '8px', fontSize: '13px',
        fontFamily: 'system-ui, sans-serif', fontWeight: '600',
        color: '#fff', maxWidth: '340px',
        boxShadow: '0 4px 16px rgba(0,0,0,.35)',
        transition: 'opacity .3s', pointerEvents: 'none', lineHeight: '1.5',
      });
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.style.opacity = '1';
    el.style.background =
      type === 'error' ? '#c53030' : type === 'success' ? '#276749' :
      type === 'warn'  ? '#b7791f' : '#1a202c';
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.style.opacity = '0'; },
      type === 'error' ? 6000 : type === 'warn' ? 5000 : 3000);
  }

  function setReactValue(input, value) {
    var setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(input, value);
    input.dispatchEvent(new Event('input',  { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  // polling 50ms (เร็วกว่าเดิม 4x)
  function waitFor(selector, text, timeout) {
    timeout = timeout || 10000;
    return new Promise(function (resolve, reject) {
      var deadline = Date.now() + timeout;
      function check() {
        var candidates = Array.from(document.querySelectorAll(selector));
        var el = text
          ? candidates.find(function (c) { return c.textContent.includes(text); })
          : candidates[0];
        if (el) return resolve(el);
        if (Date.now() > deadline) return reject(new Error('Timeout: ' + selector + (text ? ' "' + text + '"' : '')));
        setTimeout(check, 50);
      }
      check();
    });
  }

  // รอจน element ไม่ disabled จริงๆ (รองรับ HTML disabled, aria-disabled, class disabled)
  function waitUntilEnabled(el, timeout) {
    timeout = timeout || 5000;
    return new Promise(function (resolve, reject) {
      var deadline = Date.now() + timeout;
      function check() {
        var isDisabled = el.disabled
          || el.getAttribute('aria-disabled') === 'true'
          || el.classList.contains('disabled')
          || el.classList.contains('ant-btn-loading');
        if (!isDisabled) return resolve(el);
        if (Date.now() > deadline) return reject(new Error('Timeout: element still disabled'));
        setTimeout(check, 50);
      }
      check();
    });
  }

  function pressEnter(el) {
    ['keydown', 'keypress', 'keyup'].forEach(function (t) {
      el.dispatchEvent(new KeyboardEvent(t, { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
    });
  }

  function waitForPath(pattern, timeout) {
    timeout = timeout || 10000;
    return new Promise(function (resolve, reject) {
      if (pattern.test(location.pathname)) return resolve();
      var deadline = Date.now() + timeout;
      var timer = setInterval(function () {
        if (pattern.test(location.pathname)) {
          clearInterval(timer);
          resolve();
        } else if (Date.now() > deadline) {
          clearInterval(timer);
          reject(new Error('Timeout รอ navigate: ' + pattern));
        }
      }, 50);
    });
  }

  function hookWindowOpen() {
    var _orig = window.open;
    window.open = function () {
      var newWin = _orig.apply(this, arguments);
      window.open = _orig;
      if (newWin) {
        try {
          newWin.addEventListener('load', function () {
            setTimeout(function () { newWin.print(); newWin.close(); }, 800);
          });
        } catch (_e) {}
      }
      return newWin;
    };
  }

  // ────────────────────────────────────────────
  // TIKTOK AUTOMATION
  // ────────────────────────────────────────────
  async function runTikTok(orderNumber) {
    try {
      showToast('[TikTok] ค้นหา ' + orderNumber + '…');
      var searchInput = await waitFor('input[placeholder*="หมายเลขคำสั่งซื้อ"]', null, 6000);
      searchInput.focus();
      setReactValue(searchInput, orderNumber);
      await sleep(jitter(J.input));
      pressEnter(searchInput);

      showToast('[TikTok] รอผลลัพธ์…');
      await waitFor('tbody tr', null, 10000);

      showToast('[TikTok] เลือก order…');
      var selectAll = await waitFor('thead input[type="checkbox"]', null, 5000);
      await waitUntilEnabled(selectAll);
      await sleep(jitter(J.click));
      if (!selectAll.checked) selectAll.click();

      showToast('[TikTok] เปิด dialog พิมพ์เอกสาร…');
      var printDocBtn = await waitFor('button', 'พิมพ์เอกสาร', 6000);
      await waitUntilEnabled(printDocBtn);
      await sleep(jitter(J.click));
      printDocBtn.click();

      var modal = await waitFor('[role="dialog"]', 'พิมพ์เอกสาร', 6000)
        .catch(function () { return waitFor('div', 'พิมพ์เอกสาร', 4000); });

      showToast('[TikTok] เลือก A6…');
      // รอ A6 ปรากฏใน modal ก่อนค่อย query
      await waitFor('[role="dialog"] label, [role="dialog"] span', 'A6', 5000)
        .catch(function () { return null; });
      await sleep(jitter(J.click));

      var allLabels = Array.from(modal.querySelectorAll('label, [class*="label"], span'));
      var a6Label = allLabels.find(function (l) { return l.textContent.includes('A6'); });
      if (a6Label) {
        var a6Input = a6Label.querySelector('input[type="checkbox"], input[type="radio"]')
          || modal.querySelector('input[type="checkbox"]');
        if (a6Input && !a6Input.checked) a6Input.click();
        else if (!a6Input) a6Label.click();
      } else {
        var firstCb = modal.querySelector('input[type="checkbox"]');
        if (firstCb && !firstCb.checked) firstCb.click();
      }

      showToast('[TikTok] กด พิมพ์…');
      var confirmBtn = Array.from(modal.querySelectorAll('button')).find(function (b) {
        var t = b.textContent.trim();
        return t === 'พิมพ์' || (t.startsWith('พิมพ์') && !t.includes('เอกสาร'));
      }) || Array.from(modal.querySelectorAll('button')).find(function (b) {
        return !b.textContent.includes('ยกเลิก');
      });
      if (!confirmBtn) throw new Error('ไม่พบปุ่ม "พิมพ์" ใน dialog');

      await waitUntilEnabled(confirmBtn);
      await sleep(jitter(J.confirm));
      hookWindowOpen();
      confirmBtn.click();

      showToast('[TikTok] เสร็จ! กำลังปริ้นอัตโนมัติ…', 'success');
    } catch (err) {
      showToast('[TikTok] Error: ' + err.message, 'error');
      console.error('[AutoPrint TikTok]', err);
    }
  }

  // ────────────────────────────────────────────
  // SHOPEE AUTOMATION
  // ────────────────────────────────────────────
  async function runShopee(orderNumber) {
    try {
      showToast('[Shopee] ค้นหา ' + orderNumber + '…');

      var searchInput = await Promise.any([
        waitFor('input[placeholder*="เลขที่คำสั่งซื้อ"]', null, 2000),
        waitFor('input[placeholder*="order"]',             null, 2000),
        waitFor('input[placeholder*="Order"]',             null, 2000),
        waitFor('input[type="text"][placeholder]',         null, 2000),
      ]).catch(function () {
        return waitFor('input[type="search"], input[type="text"]', null, 4000);
      });

      searchInput.focus();
      setReactValue(searchInput, orderNumber);
      await sleep(jitter(J.input));
      pressEnter(searchInput);

      showToast('[Shopee] รอผลลัพธ์…');
      await waitFor('tbody tr, [class*="order-item"], [class*="orderItem"]', null, 10000);

      showToast('[Shopee] เลือก order…');
      var orderCb = await waitFor(
        'tbody input[type="checkbox"], [class*="order"] input[type="checkbox"]',
        null, 5000
      ).catch(function () { return null; });
      if (orderCb) {
        await waitUntilEnabled(orderCb);
        await sleep(jitter(J.click));
        if (!orderCb.checked) orderCb.click();
      }

      showToast('[Shopee] เตรียมจัดส่ง…');
      var actionBtn = await Promise.any([
        waitFor('button', 'เตรียมจัดส่ง',    3000),
        waitFor('button', 'พิมพ์ใบปะหน้า',   3000),
        waitFor('button', 'จัดส่งพัสดุ',      3000),
      ]).catch(function () { return null; });

      if (actionBtn) {
        await waitUntilEnabled(actionBtn);
        await sleep(jitter(J.click));
        actionBtn.click();
        showToast('[Shopee] รอกด ตกลง อัตโนมัติ…');
      } else {
        showToast('[Shopee] ค้นหาเสร็จ — กด เตรียมจัดส่ง เองแล้ว script จะ print ให้', 'warn');
      }
    } catch (err) {
      showToast('[Shopee] Error: ' + err.message, 'error');
      console.error('[AutoPrint Shopee]', err);
    }
  }

  // ────────────────────────────────────────────
  // ODOO AUTOMATION (2-phase เพราะต้อง navigate)
  // ────────────────────────────────────────────

  async function odooPhase1(orderNumber) {
    showToast('[Odoo] ค้นหา ' + orderNumber + '…');

    var searchInput = await waitFor('input.o_searchview_input', null, 6000)
      .catch(function () {
        return waitFor('input[placeholder*="Search"], input[placeholder*="ค้นหา"]', null, 4000);
      });

    searchInput.focus();
    searchInput.value = orderNumber;
    searchInput.dispatchEvent(new Event('input',  { bubbles: true }));
    searchInput.dispatchEvent(new Event('change', { bubbles: true }));
    await sleep(jitter(J.input));
    pressEnter(searchInput);

    showToast('[Odoo] รอผลลัพธ์…');
    var firstRow = await waitFor('.o_data_row', null, 10000);
    await sleep(jitter(J.click));

    var clickTarget = firstRow.querySelector('td.o_data_cell') || firstRow;
    clickTarget.click();
    showToast('[Odoo] กำลังเปิด order…');

    await waitForPath(/^\/odoo\/sales\/\d+/, 10000);
    await sleep(jitter(J.click));
    await odooPhase2();
  }

  async function odooPhase2() {
    hookWindowOpen();
    var _origAClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () {
      if (this.hasAttribute('download') && this.href) {
        HTMLAnchorElement.prototype.click = _origAClick;
        var url = this.href;
        var html = '<!DOCTYPE html><html><head><title>Print</title><style>*{margin:0;padding:0}iframe{width:100vw;height:100vh;border:none}</style></head>'
          + '<body><iframe src="' + url + '"></iframe>'
          + '<script>setTimeout(function(){window.print();},2500);<\/script></body></html>';
        var blob = new Blob([html], { type: 'text/html' });
        var htmlUrl = URL.createObjectURL(blob);
        window.open(htmlUrl, '_blank');
        return;
      }
      return _origAClick.call(this);
    };

    showToast('[Odoo] เปิดเมนู gear…');
    var gearBtn = await waitFor('.o_cp_action_menus button', null, 8000)
      .catch(function () {
        var cogEl = document.querySelector('button .fa-cog, button .fa-gear');
        if (cogEl) return cogEl.closest('button');
        return waitFor('button[data-bs-toggle="dropdown"]', null, 4000);
      });

    if (!gearBtn) throw new Error('ไม่พบปุ่ม Action Menu (gear)');
    await waitUntilEnabled(gearBtn);
    await sleep(jitter(J.click));
    gearBtn.click();

    showToast('[Odoo] คลิก Print…');
    var printItem = await waitFor(
      '.dropdown-menu .dropdown-item, .o_dropdown_menu .o_menu_item, li',
      'Print', 4000
    );
    await sleep(jitter(J.click));
    printItem.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
    printItem.dispatchEvent(new MouseEvent('mouseover',  { bubbles: true }));
    if (printItem.tagName !== 'A') printItem.click();

    showToast('[Odoo] คลิก ใบปะหน้า…');
    var labelItem = await waitFor(
      '.dropdown-menu a, .dropdown-menu .dropdown-item, li a',
      'ใบปะหน้า', 4000
    );
    await sleep(jitter(J.confirm));
    labelItem.click();

    showToast('[Odoo] เสร็จ! กำลังปริ้นอัตโนมัติ…', 'success');
  }

  async function runOdoo(orderNumber) {
    try {
      var path = location.pathname;
      if (/^\/odoo\/sales\/\d+/.test(path)) {
        await odooPhase2();
      } else if (/^\/odoo\/sales(\?|$)/.test(path)) {
        await odooPhase1(orderNumber);
      } else {
        GM_setValue('odoo_pending_job', JSON.stringify({
          orderNumber: orderNumber,
          phase: 1,
          ts: Date.now(),
        }));
        showToast('[Odoo] กำลังไปหน้า Sales…');
        location.href = '/odoo/sales';
      }
    } catch (err) {
      showToast('[Odoo] Error: ' + err.message, 'error');
      console.error('[AutoPrint Odoo]', err);
    }
  }

  // ────────────────────────────────────────────
  // TIKTOK REACTIVE LOGIC — auto-print label page
  // ────────────────────────────────────────────
  if (currentPlatform() === 'tiktok') {
    var path = location.pathname.toLowerCase();
    if (/\/(print|label|awb|shipping)/.test(path)) {
      function doPrint() {
        setTimeout(function () { window.print(); window.close(); }, 1000);
      }
      if (document.readyState === 'complete') {
        doPrint();
      } else {
        window.addEventListener('load', doPrint);
      }
    }
    console.log('[Auto Print] TikTok reactive logic active');
  }

  // ────────────────────────────────────────────
  // SHOPEE REACTIVE LOGIC
  // ────────────────────────────────────────────
  if (currentPlatform() === 'shopee') {

    function findByText(text) {
      for (var el of document.querySelectorAll('button, a, span')) {
        if (el.textContent.trim() === text) return el;
      }
      return null;
    }

    if (location.pathname.startsWith('/awbprint')) {
      var awbObserver = new MutationObserver(function () {
        var btn = findByText('พิมพ์เอกสาร');
        if (!btn) return;
        awbObserver.disconnect();
        setTimeout(function () { btn.click(); }, jitter([600, 1000]));
      });
      awbObserver.observe(document.body, { childList: true, subtree: true });
    }

    function watchForPrintButton() {
      var start = Date.now();
      var obs = new MutationObserver(function () {
        var btn = findByText('พิมพ์ใบปะหน้าพัสดุ');
        if (btn) {
          obs.disconnect();
          setTimeout(function () { btn.click(); }, jitter([400, 800]));
        } else if (Date.now() - start > 8000) {
          obs.disconnect();
        }
      });
      obs.observe(document.body, { childList: true, subtree: true });
    }

    document.addEventListener('click', function (e) {
      var btn = e.target.closest('button, a, span');
      if (!btn || btn.textContent.trim() !== 'ตกลง') return;
      setTimeout(function () { watchForPrintButton(); }, jitter([200, 700]));
    }, true);

    console.log('[Auto Print] Shopee reactive logic active');
  }

  // ────────────────────────────────────────────
  // ODOO REACTIVE LOGIC — pickup pending job หลัง navigate
  // ────────────────────────────────────────────
  if (currentPlatform() === 'odoo') {
    (function () {
      var raw = GM_getValue('odoo_pending_job');
      if (!raw) return;

      var job;
      try { job = JSON.parse(raw); } catch (_) { return; }
      if (Date.now() - job.ts > 30000) { GM_setValue('odoo_pending_job', ''); return; }

      var p = location.pathname;
      var isListPage   = /^\/odoo\/sales(\?|$)/.test(p);
      var isDetailPage = /^\/odoo\/sales\/\d+/.test(p);

      if (job.phase === 1 && isListPage) {
        GM_setValue('odoo_pending_job', '');
        setTimeout(function () {
          odooPhase1(job.orderNumber).catch(function (err) {
            showToast('[Odoo] Error: ' + err.message, 'error');
          });
        }, 1200);
      } else if (job.phase === 2 && isDetailPage) {
        GM_setValue('odoo_pending_job', '');
        setTimeout(function () {
          odooPhase2().catch(function (err) {
            showToast('[Odoo] Error: ' + err.message, 'error');
          });
        }, 1200);
      }
    })();
    console.log('[Auto Print] Odoo reactive logic active');
  }

  // ────────────────────────────────────────────
  // BUSY LOCK — ป้องกัน order ซ้อนกัน
  // ────────────────────────────────────────────
  var _busy = false;

  async function withBusy(fn) {
    if (_busy) {
      showToast('กำลังทำงานอยู่ — รอให้เสร็จก่อนแล้วยิงใหม่', 'warn');
      return;
    }
    _busy = true;
    try { await fn(); } finally { _busy = false; }
  }

  // ────────────────────────────────────────────
  // SHARED ORDER DISPATCHER
  // ────────────────────────────────────────────
  var NAMES = { tiktok: 'TikTok', shopee: 'Shopee', odoo: 'Odoo' };

  function handleOrderInput(trimmed) {
    var orderPlatform = detectPlatform(trimmed);
    if (!orderPlatform) return false;

    var sitePlatform = currentPlatform();
    if (orderPlatform === sitePlatform) {
      withBusy(function () {
        if (orderPlatform === 'tiktok') return runTikTok(trimmed);
        if (orderPlatform === 'odoo')   return runOdoo(trimmed);
        return runShopee(trimmed);
      });
    } else {
      GM_setValue('auto_print_job', JSON.stringify({
        platform: orderPlatform,
        orderNumber: trimmed,
        ts: Date.now(),
      }));
      showToast('ส่งไปยัง ' + NAMES[orderPlatform] + ' tab แล้ว — สลับไปดูได้เลย', 'warn');
    }
    return true;
  }

  // ────────────────────────────────────────────
  // CROSS-TAB RELAY (GM_setValue — ทำงานข้าม domain ได้)
  // ────────────────────────────────────────────
  GM_addValueChangeListener('auto_print_job', function (name, oldVal, newVal) {
    if (!newVal) return;
    var job;
    try { job = JSON.parse(newVal); } catch (_) { return; }
    if (job.platform !== currentPlatform()) return;
    window.focus();
    showToast('[' + NAMES[job.platform] + '] รับ order จาก tab อื่น…');
    withBusy(function () {
      if (job.platform === 'tiktok') return runTikTok(job.orderNumber);
      if (job.platform === 'odoo')   return runOdoo(job.orderNumber);
      return runShopee(job.orderNumber);
    });
  });

  // ────────────────────────────────────────────
  // PASTE HANDLER — Ctrl+V
  // ────────────────────────────────────────────
  document.addEventListener('paste', function (e) {
    var trimmed = ((e.clipboardData || window.clipboardData).getData('text/plain') || '').trim();
    if (!detectPlatform(trimmed)) return;
    e.preventDefault();
    e.stopPropagation();
    handleOrderInput(trimmed);
  }, true);

  // ────────────────────────────────────────────
  // BARCODE SCANNER — USB HID keyboard wedge
  // scanner พิมพ์ตัวอักษรเร็ว (<80ms ต่อตัว) แล้วกด Enter
  // ────────────────────────────────────────────
  var _bcBuf = '';
  var _bcLastKey = 0;
  var _bcTimer = null;
  var SCANNER_GAP_MS = 80;

  function isFocusedOnInput() {
    var el = document.activeElement;
    if (!el) return false;
    var tag = el.tagName.toLowerCase();
    return tag === 'input' || tag === 'textarea' || el.isContentEditable;
  }

  function resetBcBuf() {
    _bcBuf = '';
    _bcLastKey = 0;
    clearTimeout(_bcTimer);
    _bcTimer = null;
  }

  document.addEventListener('keydown', function (e) {
    // ถ้า focus อยู่บน input ไม่ต้องทำอะไร
    if (isFocusedOnInput()) { resetBcBuf(); return; }

    if (e.key === 'Enter') {
      var buf = _bcBuf;
      resetBcBuf();
      if (buf.length >= 6) handleOrderInput(buf);
      return;
    }

    // รับแค่ตัวอักษรที่พิมพ์ได้ (ยาว 1 ตัว)
    if (e.key.length !== 1) { resetBcBuf(); return; }

    var now = Date.now();
    // ถ้าช้าเกิน SCANNER_GAP_MS = คนพิมพ์ ไม่ใช่ scanner → reset
    if (_bcBuf.length > 0 && now - _bcLastKey > SCANNER_GAP_MS) {
      resetBcBuf();
    }

    _bcBuf += e.key;
    _bcLastKey = now;

    // safety reset ถ้าไม่มี Enter ใน 500ms
    clearTimeout(_bcTimer);
    _bcTimer = setTimeout(resetBcBuf, 500);
  }, true);

  console.log('[Auto Print Label] v1.8 loaded — platform:', currentPlatform(),
    '— Ctrl+V หรือยิง barcode เพื่อ print ใบปะหน้า');

  // ────────────────────────────────────────────
  // WEBSOCKET BRIDGE — รับ barcode จาก desktop app
  // Desktop app ต้องเปิด WebSocket server ที่ ws://localhost:9999
  // ────────────────────────────────────────────
  (function initScannerBridge() {
    var WS_URL = 'ws://localhost:9999';
    var ws = null;
    var reconnectTimer = null;

    function connect() {
      try {
        ws = new WebSocket(WS_URL);

        ws.onopen = function () {
          showToast('Scanner bridge connected', 'success');
          console.log('[Auto Print Label] Scanner bridge connected');
        };

        ws.onmessage = function (evt) {
          var barcode = (evt.data || '').trim();
          if (!barcode) return;
          console.log('[Auto Print Label] Scanner received:', barcode);
          handleOrderInput(barcode);
        };

        ws.onclose = function () {
          ws = null;
          reconnectTimer = setTimeout(connect, 3000);
        };

        ws.onerror = function () {
          ws.close();
        };
      } catch (_) {
        reconnectTimer = setTimeout(connect, 3000);
      }
    }

    connect();
  })();
})();
