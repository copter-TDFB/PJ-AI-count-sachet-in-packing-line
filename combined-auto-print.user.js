// ==UserScript==
// @name         Auto Print Label (Shopee + TikTok + Odoo + Lazada)
// @namespace    http://tampermonkey.net/
// @version      2.9
// @description  Ctrl+V เลข order → auto-print ใบปะหน้า (รองรับ Shopee + TikTok + Odoo + Lazada)
// @author       copter-TDFB
// @match        https://seller.shopee.co.th/*
// @match        https://seller.tiktok.com/*
// @match        https://seller-th.tiktok.com/*
// @match        https://tdfb.odoo.com/odoo/sales*
// @match        https://sellercenter.lazada.co.th/*
// @exclude      https://sellercenter.lazada.co.th/apps/order/print*
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_addValueChangeListener
// @run-at       document-idle
// @updateURL    https://raw.githubusercontent.com/copter-TDFB/PJ-AI-count-sachet-in-packing-line/main/combined-auto-print.user.js
// @downloadURL  https://raw.githubusercontent.com/copter-TDFB/PJ-AI-count-sachet-in-packing-line/main/combined-auto-print.user.js
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
    if (/^\d{18}$/.test(text)) return 'tiktok';
    if (/^\d{16}$/.test(text)) return 'lazada';
    if (/^S\d{4,6}$/.test(text) || /^MZS-\d+$/.test(text)) return 'odoo';
    if (/^[A-Z0-9]{6,25}$/i.test(text) && /[A-Za-z]/.test(text)) return 'shopee';
    return null;
  }

  function currentPlatform() {
    var h = location.hostname;
    if (h.includes('tiktok')) return 'tiktok';
    if (h.includes('shopee')) return 'shopee';
    if (h === 'tdfb.odoo.com') return 'odoo';
    if (h.includes('lazada')) return 'lazada';
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

  // นับจำนวนแท็ก/ชิปที่ค้างอยู่ในกล่องค้นหา (ดูจากปุ่ม × รอบๆ input)
  function countChips(wrap, input) {
    if (!wrap) return 0;
    return Array.from(wrap.querySelectorAll(
      '[class*="remove"], [class*="close"], [class*="tag"], [class*="chip"], [class*="token"]'
    )).filter(function (el) {
      return el !== input && !el.contains(input) && isVisibleInput(el);
    }).length;
  }

  // เคลีย order เก่าในช่องค้นหาออกก่อน
  // Lazada ช่องนี้เป็นแบบ "แท็ก/ชิป" — กด Enter แล้วเลขจะสะสมเป็นแท็ก
  // วิธีที่ทนทานสุด (ไม่ขึ้นกับชื่อ class): กด Backspace ในช่องที่ว่าง
  // → tag input เกือบทั้งหมด (รวม Ant Design) จะลบแท็กตัวท้ายออกทีละตัว
  async function clearReactInput(input) {
    if (!input) return;
    input.focus();
    // ล้างตัวอักษรที่ยังพิมพ์ค้าง (ยังไม่ได้กด Enter) ให้ช่องว่างก่อน
    if (input.value) { setReactValue(input, ''); await sleep(50); }

    var wrap = input.closest('[class*="select"], [class*="input"], [class*="search"]')
      || input.parentElement;

    // กด Backspace ลบแท็กเก่าทีละตัว สูงสุด 30 ครั้ง — หยุดเมื่อไม่มีแท็กเหลือ
    for (var i = 0; i < 30; i++) {
      input.focus();
      pressBackspace(input);
      await sleep(70);
      // ถ้านับแท็กได้และเหลือ 0 → หยุด
      if (wrap && countChips(wrap, input) === 0 && i >= 1) break;
    }

    // สำรอง: ถ้ายังมีปุ่ม × ที่คลิกได้ ก็ลองกดให้หมด
    if (wrap) {
      for (var n = 0; n < 30; n++) {
        var removers = Array.from(wrap.querySelectorAll(
          '[class*="remove"], [class*="close"], [class*="clear"],' +
          '[aria-label*="close"], [aria-label*="remove"], [aria-label*="ล้าง"]'
        )).filter(function (el) {
          return el !== input && !el.contains(input) && isVisibleInput(el);
        });
        if (!removers.length) {
          removers = Array.from(wrap.querySelectorAll('span, i, svg, button')).filter(function (el) {
            var t = (el.textContent || '').trim();
            return (t === '×' || t === '✕' || t === '✖') && isVisibleInput(el);
          });
        }
        if (!removers.length) break;
        removers[0].click();
        await sleep(80);
      }
    }

    if (input.value) setReactValue(input, '');
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

  function pressKey(el, key, code, keyCode) {
    ['keydown', 'keypress', 'keyup'].forEach(function (t) {
      el.dispatchEvent(new KeyboardEvent(t, {
        key: key, code: code, keyCode: keyCode, which: keyCode, bubbles: true,
      }));
    });
  }

  function pressEnter(el) {
    pressKey(el, 'Enter', 'Enter', 13);
  }

  function pressBackspace(el) {
    pressKey(el, 'Backspace', 'Backspace', 8);
  }

  // ── หาช่องค้นหาแบบทนทาน ───────────────────────────────────────────
  // selector 'input[type="text"]' จะ "ไม่" match <input> ที่ไม่มี type
  // attribute (ดีฟอลต์เป็น text) ซึ่ง React apps อย่าง Lazada มักเรนเดอร์แบบนี้
  // → สแกน input ทั้งหมดแล้วเลือกช่องที่มองเห็นได้ + ดูเหมือนช่องค้นหา
  function isVisibleInput(el) {
    if (!el) return false;
    var rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    var style = getComputedStyle(el);
    return style.visibility !== 'hidden' && style.display !== 'none';
  }

  function findSearchInput(keywords) {
    var TEXTLIKE = ['', 'text', 'search'];
    var candidates = Array.from(document.querySelectorAll('input')).filter(function (el) {
      var t = (el.getAttribute('type') || '').toLowerCase();
      return TEXTLIKE.indexOf(t) !== -1 && !el.disabled && isVisibleInput(el);
    });
    if (!candidates.length) return null;
    var kw = (keywords || ['คำสั่งซื้อ', 'หมายเลข', 'order', 'tracking', 'ค้นหา', 'search'])
      .map(function (k) { return k.toLowerCase(); });
    var matchesKw = function (s) {
      s = (s || '').toLowerCase();
      return kw.some(function (k) { return s.indexOf(k) !== -1; });
    };
    var preferred = candidates.find(function (el) {
      return matchesKw(el.getAttribute('placeholder'))
        || matchesKw(el.getAttribute('aria-label'))
        || matchesKw(el.getAttribute('name'));
    });
    return preferred || candidates[0];
  }

  // ── หา input ที่อยู่ "ข้างๆ" ป้ายข้อความที่กำหนด ────────────────────
  // Lazada: "หมายเลขคำสั่งซื้อ" เป็น dropdown/ป้าย ส่วนช่องที่ต้องพิมพ์เลขจริง
  // อยู่ติดกัน (ช่องที่มีไอคอนแว่นขยาย) → หาป้ายข้อความก่อน แล้วไต่ขึ้นไปหา
  // container ที่มี <input> ข้างใน แล้วเลือกช่องกรอกค่า (ไม่ใช่ตัว dropdown)
  function findInputNearLabel(labelText) {
    var leaves = Array.from(document.querySelectorAll('body *')).filter(function (el) {
      return el.children.length === 0
        && (el.textContent || '').trim().indexOf(labelText) !== -1;
    });
    for (var L = 0; L < leaves.length; L++) {
      var container = leaves[L];
      for (var i = 0; i < 6 && container; i++) {
        var inputs = Array.from(container.querySelectorAll('input')).filter(function (inp) {
          return isVisibleInput(inp) && !inp.disabled;
        });
        if (inputs.length) {
          // ข้ามช่องที่ placeholder คือป้ายเอง (น่าจะเป็น dropdown) ถ้ามีตัวเลือกอื่น
          var valueInput = inputs.find(function (inp) {
            return (inp.getAttribute('placeholder') || '').indexOf(labelText) === -1;
          });
          return valueInput || inputs[inputs.length - 1];
        }
        container = container.parentElement;
      }
    }
    return null;
  }

  // หาช่องค้นหา Lazada: ลองหาช่องข้างป้าย "หมายเลขคำสั่งซื้อ" ก่อน
  // ถ้าไม่เจอ ค่อย fallback ไปสแกน input ทั้งหน้า
  function waitForSearchInput(timeout, keywords) {
    timeout = timeout || 10000;
    return new Promise(function (resolve, reject) {
      var deadline = Date.now() + timeout;
      function check() {
        var el = findInputNearLabel('หมายเลขคำสั่งซื้อ') || findSearchInput(keywords);
        if (el) return resolve(el);
        if (Date.now() > deadline) return reject(new Error('Timeout: ไม่พบช่องค้นหา (input)'));
        setTimeout(check, 50);
      }
      check();
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

  // รอให้หน้าพร้อมจริง (โหลดเสร็จ + รูป/บาร์โค้ด + ฟอนต์) แล้วค่อยสั่งพิมพ์
  // กันเคสพิมพ์เร็วเกินจน layout เพี้ยน / ฉลากล้น / หน้าว่าง
  function printWhenReady(opts) {
    opts = opts || {};
    var closeAfter = opts.closeAfter !== false;   // default: ปิดหน้าต่างหลังพิมพ์
    var maxWaitMs  = opts.maxWaitMs  || 8000;      // เพดานเวลา กันรอค้างถ้าหน้าโหลดไม่จบ
    var bufferMs   = opts.bufferMs   || 350;       // กันชนสั้น ๆ หลังพร้อม
    var done = false;

    function fire() {
      if (done) return;
      done = true;
      setTimeout(function () {
        try { window.print(); } catch (_e) {}
        if (closeAfter) { try { window.close(); } catch (_e) {} }
      }, bufferMs);
    }

    function whenLoaded(cb) {
      if (document.readyState === 'complete') cb();
      else window.addEventListener('load', cb, { once: true });
    }

    // กันค้าง: ถ้ารอเกิน maxWaitMs ก็พิมพ์เลย
    var hardTimer = setTimeout(fire, maxWaitMs);

    whenLoaded(function () {
      var waits = [];

      // รอรูป/บาร์โค้ดทุกตัวในหน้าให้โหลดเสร็จก่อน
      Array.prototype.slice.call(document.images || []).forEach(function (img) {
        if (img.complete) return;
        waits.push(new Promise(function (resolve) {
          img.addEventListener('load',  resolve, { once: true });
          img.addEventListener('error', resolve, { once: true });
        }));
      });

      // รอฟอนต์ (ถ้าเบราว์เซอร์รองรับ)
      if (document.fonts && document.fonts.ready) {
        waits.push(Promise.resolve(document.fonts.ready).catch(function () {}));
      }

      Promise.all(waits).then(function () {
        clearTimeout(hardTimer);
        fire();
      }, function () {
        clearTimeout(hardTimer);
        fire();
      });
    });
  }

  // ────────────────────────────────────────────
  // TIKTOK AUTOMATION
  // ────────────────────────────────────────────
  async function runTikTok(orderNumber) {
    try {
      showToast('[TikTok] ค้นหา ' + orderNumber + '…');
      var searchInput = await waitFor('input[placeholder*="หมายเลขคำสั่งซื้อ"]', null, 6000);

      // จับ row เก่าก่อน search — ใช้ detect ว่า React flush results ใหม่แล้ว
      var staleRow = document.querySelector('tbody tr');

      searchInput.focus();
      setReactValue(searchInput, orderNumber);
      await sleep(jitter(J.input));
      pressEnter(searchInput);

      showToast('[TikTok] รอผลลัพธ์…');

      // รอ row เก่า detach ออกจาก DOM ก่อน (ป้องกันเจอผลลัพธ์เก่า)
      if (staleRow) {
        await new Promise(function (resolve) {
          if (!document.body.contains(staleRow)) return resolve();
          var fallback = setTimeout(resolve, 5000);
          var obs = new MutationObserver(function () {
            if (!document.body.contains(staleRow)) {
              clearTimeout(fallback);
              obs.disconnect();
              resolve();
            }
          });
          obs.observe(document.body, { childList: true, subtree: true });
        });
      }

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

      // หลังกด "พิมพ์" จะมี popup ยืนยันโผล่ในหน้าเดิม — กด "พิมพ์ต่อ" เพื่อเข้าหน้าปริ้น
      showToast('[TikTok] กด พิมพ์ต่อ…');
      var continueBtn = await waitFor('button', 'พิมพ์ต่อ', 8000)
        .catch(function () { return waitFor('button, a, [role="button"]', 'พิมพ์ต่อ', 4000); });
      await waitUntilEnabled(continueBtn);
      await sleep(jitter(J.confirm));
      continueBtn.click();

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

      var staleRow = document.querySelector('tbody tr, [class*="order-item"], [class*="orderItem"]');

      searchInput.focus();
      setReactValue(searchInput, orderNumber);
      await sleep(jitter(J.input));
      pressEnter(searchInput);

      showToast('[Shopee] รอผลลัพธ์…');
      if (staleRow) {
        await new Promise(function (resolve) {
          if (!document.body.contains(staleRow)) return resolve();
          var fallback = setTimeout(resolve, 5000);
          var obs = new MutationObserver(function () {
            if (!document.body.contains(staleRow)) {
              clearTimeout(fallback); obs.disconnect(); resolve();
            }
          });
          obs.observe(document.body, { childList: true, subtree: true });
        });
      }
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
  // LAZADA AUTOMATION
  // ────────────────────────────────────────────
  async function runLazada(orderNumber) {
    try {
      showToast('[Lazada] ค้นหา ' + orderNumber + '…');

      var searchInput = await waitForSearchInput(10000);

      var staleRow = document.querySelector('tbody tr, [class*="order-item"], [class*="orderItem"]');

      // เคลีย order เก่าออกจากช่องก่อน แล้วค่อยพิมพ์เลขใหม่
      searchInput.focus();
      await clearReactInput(searchInput);
      await sleep(jitter(J.input));
      setReactValue(searchInput, orderNumber);
      await sleep(jitter(J.input));
      pressEnter(searchInput);

      showToast('[Lazada] รอผลลัพธ์…');
      if (staleRow) {
        await new Promise(function (resolve) {
          if (!document.body.contains(staleRow)) return resolve();
          var fallback = setTimeout(resolve, 5000);
          var obs = new MutationObserver(function () {
            if (!document.body.contains(staleRow)) {
              clearTimeout(fallback); obs.disconnect(); resolve();
            }
          });
          obs.observe(document.body, { childList: true, subtree: true });
        });
      }
      await waitFor('tbody tr, [class*="order-item"], [class*="orderItem"]', null, 10000);

      showToast('[Lazada] กด การดำเนินการเพิ่มเติม…');
      var moreBtn = await waitFor('button, a, span', 'การดำเนินการเพิ่มเติม', 8000);
      await waitUntilEnabled(moreBtn);
      await sleep(jitter(J.click));
      moreBtn.click();

      showToast('[Lazada] กด พิมพ์ฉลากจัดส่ง…');
      var printLabelBtn = await waitFor('button, a, li, span', 'พิมพ์ฉลากจัดส่ง', 5000);
      await waitUntilEnabled(printLabelBtn);
      await sleep(jitter(J.click));
      printLabelBtn.click();

      showToast('[Lazada] เสร็จ! เปิดหน้าใบปะหน้าแล้ว', 'success');
    } catch (err) {
      showToast('[Lazada] Error: ' + err.message, 'error');
      console.error('[AutoPrint Lazada]', err);
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

    var staleRow = document.querySelector('.o_data_row');

    searchInput.focus();
    searchInput.value = orderNumber;
    searchInput.dispatchEvent(new Event('input',  { bubbles: true }));
    searchInput.dispatchEvent(new Event('change', { bubbles: true }));
    await sleep(jitter(J.input));
    pressEnter(searchInput);

    showToast('[Odoo] รอผลลัพธ์…');
    if (staleRow) {
      await new Promise(function (resolve) {
        if (!document.body.contains(staleRow)) return resolve();
        var fallback = setTimeout(resolve, 5000);
        var obs = new MutationObserver(function () {
          if (!document.body.contains(staleRow)) {
            clearTimeout(fallback); obs.disconnect(); resolve();
          }
        });
        obs.observe(document.body, { childList: true, subtree: true });
      });
    }
    var firstRow = await waitFor('.o_data_row', null, 10000);
    await sleep(jitter(J.click));

    var clickTarget = firstRow.querySelector('td.o_data_cell') || firstRow;
    clickTarget.click();
    showToast('[Odoo] กำลังเปิด order…');

    await waitForPath(/^\/odoo\/sales\/\d+/, 10000);
    await sleep(jitter(J.click));
    await odooPhase2();
  }

  // เปิด PDF ใน overlay ที่มองเห็น แล้วสั่งพิมพ์ "ตัว PDF" โดยตรง (vector = คมเท่ากดเอง)
  // แทนวิธีเดิมที่พิมพ์หน้า HTML หุ้ม iframe (raster = เบลอ)
  function openPdfOverlayAndPrint(url) {
    var overlay = null, objectUrl = null, printed = false;

    function cleanup() {
      if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
      if (objectUrl) { try { URL.revokeObjectURL(objectUrl); } catch (_e) {} }
      overlay = null; objectUrl = null;
    }

    function buildOverlay(src, isBlob) {
      if (isBlob) objectUrl = src;

      overlay = document.createElement('div');
      overlay.style.cssText = [
        'position:fixed', 'inset:0', 'z-index:2147483647',
        'background:rgba(0,0,0,.78)', 'display:flex',
        'flex-direction:column', 'padding:24px', 'box-sizing:border-box'
      ].join(';');

      var bar = document.createElement('div');
      bar.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;margin-bottom:8px';

      var reprintBtn = document.createElement('button');
      reprintBtn.textContent = '🖨️ พิมพ์อีกครั้ง';
      reprintBtn.style.cssText = 'padding:6px 14px;border:none;border-radius:6px;background:#2563eb;color:#fff;cursor:pointer;font-size:14px';

      var closeBtn = document.createElement('button');
      closeBtn.textContent = '✕ ปิด';
      closeBtn.style.cssText = 'padding:6px 14px;border:none;border-radius:6px;background:#e11d48;color:#fff;cursor:pointer;font-size:14px';
      closeBtn.onclick = cleanup;

      bar.appendChild(reprintBtn);
      bar.appendChild(closeBtn);

      var iframe = document.createElement('iframe');
      iframe.style.cssText = 'flex:1;width:100%;border:none;background:#fff;border-radius:6px';

      function doPrint() {
        try {
          iframe.contentWindow.focus();
          iframe.contentWindow.print();
        } catch (e) {
          // พิมพ์ผ่าน iframe ไม่ได้ (cross-origin ฯลฯ) → fallback เปิดแท็บใหม่
          console.warn('[AutoPrint Odoo] iframe print ไม่ได้:', e);
          showToast('[Odoo] พิมพ์ผ่านหน้านี้ไม่ได้ กำลังเปิดแท็บใหม่…', 'warn');
          window.open(url, '_blank');
          cleanup();
        }
      }
      reprintBtn.onclick = doPrint;

      iframe.addEventListener('load', function () {
        // ปิด overlay อัตโนมัติเมื่อพิมพ์เสร็จ (ผูกกับหน้าต่าง PDF เอง)
        try {
          iframe.contentWindow.addEventListener('afterprint', function () {
            setTimeout(cleanup, 300);
          }, { once: true });
        } catch (_e) {}

        if (printed) return;   // กันยิง print ซ้ำ
        printed = true;
        setTimeout(doPrint, 400);
      });

      iframe.src = src;
      overlay.appendChild(bar);
      overlay.appendChild(iframe);
      document.body.appendChild(overlay);
    }

    // backup: บางเบราว์เซอร์ยิง afterprint ที่ window หลัก
    window.addEventListener('afterprint', function () {
      setTimeout(cleanup, 300);
    }, { once: true });

    // กรณี Odoo: href เป็น blob: URL ของ PDF อยู่แล้ว (same-origin)
    // → โหลดเข้า iframe ทันทีแบบ synchronous กันโดน Odoo revoke ทิ้ง (ไม่ต้อง fetch ซ้ำ)
    if (/^blob:/i.test(url)) {
      buildOverlay(url, false);  // false = ไม่ revoke (เป็น blob ของ Odoo ไม่ใช่ของเรา)
      return;
    }

    // กรณี http(s) + download → fetch เป็น blob เพื่อ render inline แม้ต้นทางเป็น attachment
    fetch(url, { credentials: 'include' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.blob();
      })
      .then(function (blob) {
        buildOverlay(URL.createObjectURL(blob), true);
      })
      .catch(function (err) {
        console.warn('[AutoPrint Odoo] fetch blob ล้มเหลว, โหลด url ตรง:', err);
        showToast('[Odoo] โหลดแบบ blob ไม่ได้ ใช้วิธีสำรอง…', 'warn');
        buildOverlay(url, false);  // fallback: โหลด url ตรงเข้า iframe
      });
  }

  async function odooPhase2() {
    hookWindowOpen();
    var _origAClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () {
      if (this.hasAttribute('download') && this.href) {
        HTMLAnchorElement.prototype.click = _origAClick;
        openPdfOverlayAndPrint(this.href);
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
    if (/\/(print|label|awb|shipping|easesafe)/.test(path)) {
      // closeAfter:false — อย่าปิดหน้าหลังปริ้น เพราะ window.print() บนหน้านี้
      // (PDF/cross-origin) ไม่ค้างรอ dialog → ถ้าปิดเลยจะปิดแท็บทิ้งก่อนได้ปริ้นจริง
      printWhenReady({ closeAfter: false });   // รอหน้าพร้อม (โหลด+รูป+ฟอนต์) แล้วค่อยพิมพ์
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
      waitFor('button, a, span', 'พิมพ์เอกสาร', 20000)
        .then(function (el) {
          var btn = el.closest('button') || el;
          return waitUntilEnabled(btn, 20000);
        })
        .then(function (btn) {
          setTimeout(function () {
            window.addEventListener('afterprint', function () { window.close(); }, { once: true });
            btn.click();
          }, jitter([600, 1000]));
        })
        .catch(function (err) {
          showToast('[Shopee] ' + (err.message || 'ไม่พบปุ่ม พิมพ์เอกสาร'), 'warn');
        });
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
  var NAMES = { tiktok: 'TikTok', shopee: 'Shopee', odoo: 'Odoo', lazada: 'Lazada' };

  function handleOrderInput(trimmed) {
    var orderPlatform = detectPlatform(trimmed);
    if (!orderPlatform) return false;

    var sitePlatform = currentPlatform();
    if (orderPlatform === sitePlatform) {
      withBusy(function () {
        if (orderPlatform === 'tiktok') return runTikTok(trimmed);
        if (orderPlatform === 'odoo')   return runOdoo(trimmed);
        if (orderPlatform === 'lazada') return runLazada(trimmed);
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
      if (job.platform === 'lazada') return runLazada(job.orderNumber);
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

  // ────────────────────────────────────────────
  // LAZADA REACTIVE LOGIC
  // ────────────────────────────────────────────
  if (currentPlatform() === 'lazada') {
    // ตามที่ตั้งใจ: Lazada จบที่ "พิมพ์ฉลากจัดส่ง" — ไม่ auto-print หน้า label
    console.log('[Auto Print] Lazada reactive logic active (no auto-print)');
  }

  console.log('[Auto Print Label] v2.0 loaded — platform:', currentPlatform(),
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
