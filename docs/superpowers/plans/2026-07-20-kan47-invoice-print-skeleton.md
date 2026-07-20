# KAN-47 (T1): Invoice Auto-Print Walking Skeleton — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scanning a Pack barcode whose sale order has `x_studio_need_bill == "ปริ้นใบเสร็จ"` silently prints the already-posted customer invoice PDF on a configured printer, running from source against production Odoo, without interrupting the counting popup.

**Architecture:** One new `pyqtSignal` on `BarcodeWorker` (`invoice_job_ready`) announces a found sale order id, independent of the existing `origin`/3g-move checks. `MainWindow` pushes each announcement onto a `deque` and runs `InvoicePrintWorker` instances strictly one at a time — a fresh worker is started only after the previous one's `finished` signal fires, mirroring the existing `OdooSaveWorker`/`BarcodeWorker` one-shot-per-job shape already used throughout this file. Each `InvoicePrintWorker` checks the need-bill gate, resolves the already-posted invoice, downloads its PDF over an authenticated Odoo web session (ported from `test_odoo_counter_app.py`), and prints it silently via SumatraPDF. Printer name, report id, and Studio field names are config-driven with safe defaults, so no settings UI is required yet.

**Tech Stack:** Python, PyQt6 (`QThread`/`pyqtSignal`), `xmlrpc.client` (Odoo RPC), `requests` (web-session PDF download — new dependency), `subprocess` (SumatraPDF), `collections.deque`.

## Global Constraints

- Touches `odoo_counter_app.py` (production) only. Do not modify `test_odoo_counter_app.py`.
- No auto-invoice-creation and no wait-for-pack-done polling — both are test-tenant-only per [[docs/adr/0003-auto-created-invoices-posted-immediately.md]] and out of scope here. If no posted invoice exists yet at scan time, that's a warning + skip.
- Out of scope (separate tickets): SumatraPDF packaging/bundling (T2/KAN-48), config relocation to `%LOCALAPPDATA%` (T3/KAN-49), printer-picker settings UI (T4/KAN-50), idempotency/dedupe/retry (T5/KAN-51).
- This project has no automated test suite, linter, or CI (per `CLAUDE.md`) — verification is manual. Do not introduce a pytest/unit-test scaffold.
- `invoice_report_id` default (`1204`, carried over from the test-tenant prototype) must be reconfirmed against **production** before being treated as correct — this is a verification step (Task 2), not an assumption.
- No default-printer fallback: an empty/unset `invoice_printer_name` must skip with a warning, never silently print to whatever Windows considers the default printer.
- Full design detail and rationale: [[docs/superpowers/specs/2026-07-20-kan47-invoice-print-skeleton-design.md]].

---

### Task 1: Invoice config loader

**Files:**
- Modify: `odoo_counter_app.py` (module level, between `_save_settings` and the `OdooConn` class, current lines 72–80)
- Test: none (no test suite in this project) — manual functional check in Step 2

**Interfaces:**
- Consumes: `_load_config_dict() -> dict` (existing, reads `crop_config.json`).
- Produces: `_load_invoice_config() -> dict` with keys `printer_name` (str), `report_id` (int), `sumatra_path` (str), `need_bill_field` (str), `need_bill_value` (str). Tasks 4 and 5 call this directly.

- [ ] **Step 1: Add `_load_invoice_config()`**

Find this exact block:

```python
def _save_settings(rect: tuple, conf: float):
    x, y, w, h = rect
    _crop_config_path().write_text(
        json.dumps({'x': x, 'y': y, 'w': w, 'h': h, 'conf': conf}, indent=2),
        encoding='utf-8'
    )


# ── Connection cache ──────────────────────────────────────────
class OdooConn:
```

Replace it with:

```python
def _save_settings(rect: tuple, conf: float):
    x, y, w, h = rect
    _crop_config_path().write_text(
        json.dumps({'x': x, 'y': y, 'w': w, 'h': h, 'conf': conf}, indent=2),
        encoding='utf-8'
    )


def _load_invoice_config() -> dict:
    """Invoice auto-print settings (KAN-47), read from the same crop_config.json.
    No printer-picker UI exists yet (T4) — printer_name is set by hand-editing the file."""
    d = _load_config_dict()
    printer_name    = d.get('invoice_printer_name')
    report_id       = d.get('invoice_report_id')
    sumatra_path    = d.get('invoice_sumatra_path')
    need_bill_field = d.get('invoice_need_bill_field')
    need_bill_value = d.get('invoice_need_bill_value')
    return {
        'printer_name':    printer_name if isinstance(printer_name, str) else '',
        'report_id':       report_id if isinstance(report_id, int) else 1204,
        'sumatra_path':    sumatra_path if isinstance(sumatra_path, str) and sumatra_path
                           else r'C:\Program Files\SumatraPDF\SumatraPDF.exe',
        'need_bill_field': need_bill_field if isinstance(need_bill_field, str) and need_bill_field
                           else 'x_studio_need_bill',
        'need_bill_value': need_bill_value if isinstance(need_bill_value, str) and need_bill_value
                           else 'ปริ้นใบเสร็จ',
    }


# ── Connection cache ──────────────────────────────────────────
class OdooConn:
```

- [ ] **Step 2: Syntax + functional check**

Run:
```bash
python -m py_compile "odoo_counter_app.py"
```
Expected: no output, exit code 0.

Then run:
```bash
python -c "from odoo_counter_app import _load_invoice_config; print(_load_invoice_config())"
```
Expected (no `crop_config.json` overrides yet, so all defaults):
```
{'printer_name': '', 'report_id': 1204, 'sumatra_path': 'C:\\Program Files\\SumatraPDF\\SumatraPDF.exe', 'need_bill_field': 'x_studio_need_bill', 'need_bill_value': 'ปริ้นใบเสร็จ'}
```
(This import loads the app's full dependency stack — PyQt6, ultralytics, opencv — so it can take several seconds; that's expected, not a hang.)

- [ ] **Step 3: Commit**

```bash
git add odoo_counter_app.py
git commit -m "feat(invoice): add invoice auto-print config loader

Reads printer name, report id, and Studio field names from the existing
crop_config.json, with safe defaults (empty printer — no default-printer
fallback per KAN-47 AC3)."
```

---

### Task 2: `_download_invoice_pdf` helper + new imports

**Files:**
- Modify: `odoo_counter_app.py` (imports block, current lines 1–23; and between `OdooConn` and `BarcodeWorker`, current lines 95–102)
- Test: none — manual read-only verification in Step 3

**Interfaces:**
- Consumes: `OdooConn` (existing), module constants `ODOO_URL`/`ODOO_DB`/`ODOO_USER`/`ODOO_PASSWORD` (existing), `_get_base_dir()` (existing).
- Produces: `_download_invoice_pdf(models, uid, invoice_id: int, invoice_name: str, report_id: int) -> Path | None`. Task 4's `InvoicePrintWorker` calls this directly with that exact signature.

- [ ] **Step 1: Add imports**

Find this exact block:

```python
import sys
import ctypes
import json
import time
import asyncio
import threading
import queue
import itertools
_snd_counter = itertools.count()
import xmlrpc.client
import cv2
import numpy as np
import websockets
from pathlib import Path
```

Replace it with:

```python
import sys
import ctypes
import json
import time
import asyncio
import threading
import queue
import subprocess
import itertools
from collections import deque
_snd_counter = itertools.count()
import xmlrpc.client
import requests
import cv2
import numpy as np
import websockets
from pathlib import Path
```

- [ ] **Step 2: Add `_download_invoice_pdf`**

Find this exact block:

```python
    @classmethod
    def reset(cls):
        cls._uid    = None
        cls._models = None


# ── Worker: ค้นหา picking จาก barcode ───────────────────────
class BarcodeWorker(QThread):
```

Replace it with:

```python
    @classmethod
    def reset(cls):
        cls._uid    = None
        cls._models = None


def _download_invoice_pdf(models, uid, invoice_id: int, invoice_name: str, report_id: int) -> Path | None:
    """Web-session login + /report/pdf download. None on any failure. Ported from
    test_odoo_counter_app.py (KAN-70/71 prototype); report_id is config-driven here
    instead of a hardcoded module constant (KAN-47)."""
    try:
        with requests.Session() as session:
            resp = session.post(
                f"{ODOO_URL}/web/session/authenticate",
                json={
                    'jsonrpc': '2.0', 'method': 'call',
                    'params': {'db': ODOO_DB, 'login': ODOO_USER, 'password': ODOO_PASSWORD},
                },
                timeout=30,
            )
            result = resp.json().get('result')
            if not result or not result.get('uid'):
                return None

            reports = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'ir.actions.report', 'read',
                [[report_id]],
                {'fields': ['report_name']}
            )
            if not reports:
                return None
            report_name = reports[0]['report_name']

            r = session.get(f"{ODOO_URL}/report/pdf/{report_name}/{invoice_id}", timeout=60)
            if r.status_code != 200 or 'pdf' not in r.headers.get('Content-Type', '').lower():
                return None

            out_dir = _get_base_dir() / 'invoices'
            out_dir.mkdir(exist_ok=True)
            safe_name = "".join(c if c.isalnum() or c in '-_' else '_' for c in invoice_name)
            path = out_dir / f"{safe_name}.pdf"
            path.write_bytes(r.content)
            return path
    except Exception as e:
        print(f"[Invoice] ดาวน์โหลดไม่สำเร็จ: {e}", flush=True)
        return None


# ── Worker: ค้นหา picking จาก barcode ───────────────────────
class BarcodeWorker(QThread):
```

- [ ] **Step 3: Syntax check + confirm `invoice_report_id` default resolves in PRODUCTION**

Run:
```bash
python -m py_compile "odoo_counter_app.py"
```
Expected: no output, exit code 0.

This is a read-only check against production Odoo — it only calls `read`, no writes:
```python
import xmlrpc.client

ODOO_URL = 'https://tdfb.odoo.com'
ODOO_DB = 'tdfb'
ODOO_USER = 'operation.engineer@tdfb.co'
ODOO_PASSWORD = 'KBT123'

common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")

reports = models.execute_kw(
    ODOO_DB, uid, ODOO_PASSWORD,
    'ir.actions.report', 'read',
    [[1204]],
    {'fields': ['report_name', 'name', 'model']}
)
print("Report 1204 in production:", reports)
```
Expected: a list with one dict whose `model` is `account.move` and `name` reads like an invoice/tax-invoice report. **If it's empty or `model` isn't `account.move`, the `1204` default from the test tenant does NOT carry over to production** — stop here, find the correct report id in the production Odoo UI (Settings → Technical → Reports, filtered to `account.move`), and use that id when setting `invoice_report_id` in Task 6's config setup instead of relying on the default.

- [ ] **Step 4: Commit**

```bash
git add odoo_counter_app.py
git commit -m "feat(invoice): add invoice PDF download helper

Ports the web-session-login + /report/pdf fetch from
test_odoo_counter_app.py, parameterized by report_id instead of a
hardcoded constant. New requests dependency."
```

---

### Task 3: `BarcodeWorker` invoice-job signal

**Files:**
- Modify: `odoo_counter_app.py`, class `BarcodeWorker` (signal declarations, current line ~106; `run()` body, current lines ~129–151)
- Test: none — behavior verified end-to-end in Task 6

**Interfaces:**
- Consumes: `picking['sale_id']` (already read by the existing `search_read`).
- Produces: `BarcodeWorker.invoice_job_ready` signal, `pyqtSignal(int, str)` — `(sale_order_id, picking_name)`. Task 5 connects to this.

- [ ] **Step 1: Add the signal declaration**

Find this exact block:

```python
class BarcodeWorker(QThread):
    data_ready     = pyqtSignal(dict)
    not_found      = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    origin_ready   = pyqtSignal(str, object)  # fire ทันทีที่เจอ picking ใน Odoo (มี/ไม่มีสินค้า 3g ก็ส่ง)
```

Replace it with:

```python
class BarcodeWorker(QThread):
    data_ready         = pyqtSignal(dict)
    not_found          = pyqtSignal(str)
    error_occurred     = pyqtSignal(str)
    origin_ready       = pyqtSignal(str, object)  # fire ทันทีที่เจอ picking ใน Odoo (มี/ไม่มีสินค้า 3g ก็ส่ง)
    invoice_job_ready  = pyqtSignal(int, str)     # sale_order_id, picking_name — independent of origin/3g-move outcome
```

- [ ] **Step 2: Emit it independent of the `origin` check**

Find this exact block:

```python
            picking = pickings[0]
            origin = (picking.get('origin') or '').strip() if isinstance(picking.get('origin'), str) else ''
            shop = None
            try:
                sale_id = picking.get('sale_id')
                if isinstance(sale_id, (list, tuple)) and sale_id and isinstance(sale_id[0], int):
                    sale = models.execute_kw(
                        ODOO_DB, uid, ODOO_PASSWORD,
                        'sale.order', 'read', [[sale_id[0]]],
                        {'fields': [SHOP_IDENTITY_FIELD]}
                    )
                    if sale:
                        value = sale[0].get(SHOP_IDENTITY_FIELD)
                        if isinstance(value, (list, tuple)) and len(value) >= 2 and isinstance(value[0], int):
                            name = str(value[1] or '').strip()
                            if name:
                                shop = {'id': value[0], 'name': name}
                        elif isinstance(value, str) and value.strip():
                            shop = {'id': 0, 'name': value.strip()}
            except Exception:
                pass
            if origin:
                self.origin_ready.emit(origin, shop)
```

Replace it with:

```python
            picking = pickings[0]
            origin = (picking.get('origin') or '').strip() if isinstance(picking.get('origin'), str) else ''
            shop = None
            sale_id = picking.get('sale_id')
            try:
                if isinstance(sale_id, (list, tuple)) and sale_id and isinstance(sale_id[0], int):
                    sale = models.execute_kw(
                        ODOO_DB, uid, ODOO_PASSWORD,
                        'sale.order', 'read', [[sale_id[0]]],
                        {'fields': [SHOP_IDENTITY_FIELD]}
                    )
                    if sale:
                        value = sale[0].get(SHOP_IDENTITY_FIELD)
                        if isinstance(value, (list, tuple)) and len(value) >= 2 and isinstance(value[0], int):
                            name = str(value[1] or '').strip()
                            if name:
                                shop = {'id': value[0], 'name': name}
                        elif isinstance(value, str) and value.strip():
                            shop = {'id': 0, 'name': value.strip()}
            except Exception:
                pass
            if origin:
                self.origin_ready.emit(origin, shop)
            # Invoice trigger (KAN-47): independent of origin being blank and of the
            # 3g-move check below — fires whenever the picking has a sale order at all.
            if isinstance(sale_id, (list, tuple)) and sale_id and isinstance(sale_id[0], int):
                self.invoice_job_ready.emit(sale_id[0], picking['name'])
```

Note: `sale_id = picking.get('sale_id')` moved above the `try:` — it's a plain dict `.get()` call that cannot raise, so this is safe, and it makes `sale_id` available for the new unconditional check below regardless of whether the shop-lookup RPC inside the `try` succeeded.

- [ ] **Step 3: Syntax check**

Run:
```bash
python -m py_compile "odoo_counter_app.py"
```
Expected: no output, exit code 0.

- [ ] **Step 4: Commit**

```bash
git add odoo_counter_app.py
git commit -m "feat(invoice): emit invoice_job_ready from BarcodeWorker

Fires whenever a scanned picking has a sale order, independent of
origin being blank and independent of the 3g-move validation outcome,
per KAN-47's trigger requirement."
```

---

### Task 4: `InvoicePrintWorker`

**Files:**
- Modify: `odoo_counter_app.py` (between the end of `BarcodeWorker` and the start of `OdooSaveWorker`, current lines ~242–248)
- Test: none — behavior verified end-to-end in Task 6

**Interfaces:**
- Consumes: `_load_invoice_config()` (Task 1), `_download_invoice_pdf(models, uid, invoice_id, invoice_name, report_id)` (Task 2), `OdooConn` (existing).
- Produces: `InvoicePrintWorker(sale_order_id: int, picking_name: str)` — a `QThread` with signal `print_status = pyqtSignal(str, str)` emitting `(level, message)` where `level` is `'ok'`, `'checking'`, or `'warn'`. Task 5 instantiates this and connects to `print_status` and `finished`.

- [ ] **Step 1: Add the class**

Find this exact block:

```python
            self.data_ready.emit({'picking': picking, 'moves': moves, 'lots_by_product': lots_by_product})

        except Exception as e:
            OdooConn.reset()
            self.error_occurred.emit(str(e))


# ── Worker: บันทึก log note กลับ Odoo ───────────────────────
class OdooSaveWorker(QThread):
```

Replace it with:

```python
            self.data_ready.emit({'picking': picking, 'moves': moves, 'lots_by_product': lots_by_product})

        except Exception as e:
            OdooConn.reset()
            self.error_occurred.emit(str(e))


# ── Worker: พิมพ์ใบกำกับภาษีอัตโนมัติ (invoice auto-print, KAN-47) ──
class InvoicePrintWorker(QThread):
    print_status = pyqtSignal(str, str)  # ('ok'|'checking'|'warn'), message

    def __init__(self, sale_order_id: int, picking_name: str):
        super().__init__()
        self.sale_order_id = sale_order_id
        self.picking_name  = picking_name

    def run(self):
        try:
            cfg = _load_invoice_config()
            printer = cfg['printer_name']
            if not printer:
                self.print_status.emit('warn', 'ยังไม่ได้ตั้งค่าเครื่องพิมพ์ใบเสร็จ')
                print(f"[Invoice] {self.picking_name}: printer not configured, skip", flush=True)
                return

            OdooConn.ensure()
            uid, models = OdooConn._uid, OdooConn._models

            orders = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'sale.order', 'read',
                [[self.sale_order_id]],
                {'fields': [cfg['need_bill_field'], 'invoice_ids']}
            )
            if not orders:
                print(f"[Invoice] {self.picking_name}: sale order not found, skip", flush=True)
                return

            need_bill_field = orders[0].get(cfg['need_bill_field'])
            need_bill = need_bill_field[1] if isinstance(need_bill_field, (list, tuple)) else (need_bill_field or '')
            if (need_bill or '').strip() != cfg['need_bill_value']:
                print(f"[Invoice] {self.picking_name}: need-bill flag not set, skip", flush=True)
                return

            invoice_ids = orders[0].get('invoice_ids') or []
            if not invoice_ids:
                self.print_status.emit('warn', f'{self.picking_name}: ยังไม่มีใบกำกับภาษี')
                return

            invoices = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'account.move', 'search_read',
                [[['id', 'in', invoice_ids], ['move_type', '=', 'out_invoice'], ['state', '=', 'posted']]],
                {'fields': ['name'], 'limit': 1, 'order': 'id desc'}
            )
            if not invoices:
                self.print_status.emit('warn', f'{self.picking_name}: ไม่มีใบกำกับภาษีที่ post แล้ว')
                return
            invoice_name = invoices[0]['name']

            self.print_status.emit('checking', f'กำลังดึงใบเสร็จ {invoice_name}...')
            path = _download_invoice_pdf(models, uid, invoices[0]['id'], invoice_name, cfg['report_id'])
            if not path:
                self.print_status.emit('warn', f'ดึงใบเสร็จ {invoice_name} ไม่สำเร็จ')
                return

            subprocess.run(
                [cfg['sumatra_path'], '-print-to', printer, '-silent', str(path)],
                check=True, timeout=30
            )
            self.print_status.emit('ok', f'พิมพ์ใบเสร็จ {invoice_name} แล้ว')
            print(f"[Invoice] {self.picking_name}: printed {invoice_name}", flush=True)

        except Exception as e:
            OdooConn.reset()
            self.print_status.emit('warn', f'{self.picking_name}: {e}')
            print(f"[Invoice] {self.picking_name}: error — {e}", flush=True)


# ── Worker: บันทึก log note กลับ Odoo ───────────────────────
class OdooSaveWorker(QThread):
```

- [ ] **Step 2: Syntax + importability check**

Run:
```bash
python -m py_compile "odoo_counter_app.py"
```
Expected: no output, exit code 0.

```bash
python -c "from odoo_counter_app import InvoicePrintWorker; print(InvoicePrintWorker)"
```
Expected: `<class 'odoo_counter_app.InvoicePrintWorker'>`

- [ ] **Step 3: Commit**

```bash
git add odoo_counter_app.py
git commit -m "feat(invoice): add InvoicePrintWorker

Gates on x_studio_need_bill, resolves the already-posted invoice via
sale_id -> invoice_ids -> account.move (no text search, no
auto-creation), downloads the PDF, and prints it silently via
SumatraPDF. No default-printer fallback."
```

---

### Task 5: `MainWindow` queue wiring

**Files:**
- Modify: `odoo_counter_app.py`, class `MainWindow` (`__init__`, current lines ~1578–1581; `_on_barcode_scanned`, current lines ~1738–1749)
- Test: none — behavior verified end-to-end in Task 6

**Interfaces:**
- Consumes: `BarcodeWorker.invoice_job_ready` (Task 3), `InvoicePrintWorker` (Task 4).
- Produces: nothing consumed by later tasks — this is the last code-writing task.

- [ ] **Step 1: Add queue state in `__init__`**

Find this exact block:

```python
        self._counter_panel = CounterPanel()
        self._counter_panel.closed.connect(self._on_counter_closed)
        self._camera_worker = None
        self._workers: set  = set()
```

Replace it with:

```python
        self._counter_panel = CounterPanel()
        self._counter_panel.closed.connect(self._on_counter_closed)
        self._camera_worker = None
        self._workers: set  = set()
        self._invoice_queue: deque = deque()
        self._invoice_worker: InvoicePrintWorker | None = None
```

- [ ] **Step 2: Connect the signal and add the queue-pump methods**

Find this exact block:

```python
    def _on_barcode_scanned(self, barcode: str):
        self.lbl_bc_icon.setText("⏳")
        self.lbl_status.setStyleSheet("color:#888; font-size:12px;")
        self.lbl_status.setText(f"กำลังค้นหา {barcode} ...")
        w = BarcodeWorker(barcode)
        w.data_ready.connect(self._on_barcode_data)
        w.not_found.connect(self._on_not_found)
        w.error_occurred.connect(self._on_error)
        w.origin_ready.connect(self._bridge.broadcast)
        w.finished.connect(lambda: self._workers.discard(w))
        self._workers.add(w)
        w.start()

    def _on_counter_closed(self):
```

Replace it with:

```python
    def _on_barcode_scanned(self, barcode: str):
        self.lbl_bc_icon.setText("⏳")
        self.lbl_status.setStyleSheet("color:#888; font-size:12px;")
        self.lbl_status.setText(f"กำลังค้นหา {barcode} ...")
        w = BarcodeWorker(barcode)
        w.data_ready.connect(self._on_barcode_data)
        w.not_found.connect(self._on_not_found)
        w.error_occurred.connect(self._on_error)
        w.origin_ready.connect(self._bridge.broadcast)
        w.invoice_job_ready.connect(self._on_invoice_job_ready)
        w.finished.connect(lambda: self._workers.discard(w))
        self._workers.add(w)
        w.start()

    def _on_invoice_job_ready(self, sale_order_id: int, picking_name: str):
        self._invoice_queue.append((sale_order_id, picking_name))
        self._pump_invoice_queue()

    def _pump_invoice_queue(self):
        if self._invoice_worker is not None or not self._invoice_queue:
            return
        sale_order_id, picking_name = self._invoice_queue.popleft()
        w = InvoicePrintWorker(sale_order_id, picking_name)
        w.print_status.connect(self._on_invoice_print_status)
        w.finished.connect(self._on_invoice_worker_finished)
        self._invoice_worker = w
        w.start()

    def _on_invoice_worker_finished(self):
        self._invoice_worker = None
        self._pump_invoice_queue()

    def _on_invoice_print_status(self, level: str, message: str):
        color = {'ok': '#4CAF50', 'checking': '#888', 'warn': '#EF9A9A'}.get(level, '#888')
        self.lbl_status.setStyleSheet(f"color:{color}; font-size:12px;")
        self.lbl_status.setText(message)

    def _on_counter_closed(self):
```

- [ ] **Step 3: Syntax check**

Run:
```bash
python -m py_compile "odoo_counter_app.py"
```
Expected: no output, exit code 0.

- [ ] **Step 4: Commit**

```bash
git add odoo_counter_app.py
git commit -m "feat(invoice): wire InvoicePrintWorker queue into MainWindow

Jobs run strictly one at a time via a deque + chained finished signal
(no persistent background thread) — a fresh worker starts only once
the previous one completes. Status surfaces on the existing lbl_status
bar, same widget used for barcode/camera/Odoo-connection messages."
```

---

### Task 6: Document the flow in `PROJECT_CONTEXT.md`

**Files:**
- Modify: `PROJECT_CONTEXT.md` (new `### InvoicePrintWorker` subsection, current lines 362–383; Quick Reference list, current lines 1231–1243)
- Test: none — documentation only

**Interfaces:**
- Consumes: nothing (describes the already-committed Tasks 1–5).
- Produces: nothing — no later task depends on this.

- [ ] **Step 1: Add the `InvoicePrintWorker` subsection**

Find this exact block:

```markdown
### `OdooSaveWorker`

ทำงานหลัง popup hide เท่านั้น (ดู Auto-save flow ด้านล่าง)

Input:

- `picking_id`
- `product_counts` list ที่มี `product_name`, `counted`, `demand`

Logic:

- สร้าง body เช่น `AI นับ <product>: นับได้ <counted> / <demand> pcs`
- call `stock.picking.message_post`
- `message_type = comment`
- `subtype_xmlid = mail.mt_note`

Signal:

- success emit `save_done` (ปัจจุบัน `CounterPanel` ไม่ subscribe เพราะ toast แสดงไปแล้วก่อน save)
- error emit `save_error` — `CounterPanel` log ลง stdout เฉย ๆ ไม่ขึ้น toast (เพราะ UI ถูก hide ไปแล้ว)

### `OdooStatusWorker`
```

Replace it with:

```markdown
### `OdooSaveWorker`

ทำงานหลัง popup hide เท่านั้น (ดู Auto-save flow ด้านล่าง)

Input:

- `picking_id`
- `product_counts` list ที่มี `product_name`, `counted`, `demand`

Logic:

- สร้าง body เช่น `AI นับ <product>: นับได้ <counted> / <demand> pcs`
- call `stock.picking.message_post`
- `message_type = comment`
- `subtype_xmlid = mail.mt_note`

Signal:

- success emit `save_done` (ปัจจุบัน `CounterPanel` ไม่ subscribe เพราะ toast แสดงไปแล้วก่อน save)
- error emit `save_error` — `CounterPanel` log ลง stdout เฉย ๆ ไม่ขึ้น toast (เพราะ UI ถูก hide ไปแล้ว)

### `InvoicePrintWorker` (KAN-47, invoice auto-print)

Trigger มาจาก `BarcodeWorker.invoice_job_ready(sale_order_id, picking_name)` — emit ทันทีที่ picking มี `sale_id`, ไม่ขึ้นกับว่า `origin` ว่างหรือไม่พบสินค้า 3g ก็ตาม (คนละจุดกับ `origin_ready`). `MainWindow` เก็บ job ไว้ใน `deque` (`_invoice_queue`) แล้ว spawn `InvoicePrintWorker` ทีละตัวเท่านั้น — worker ตัวใหม่จะเริ่มก็ต่อเมื่อตัวก่อนหน้า `finished` แล้ว (ไม่มี background thread ค้างตลอดอายุโปรแกรม; ดู `_pump_invoice_queue`).

Logic ใน `run()`:

1. เช็ก `invoice_printer_name` จาก `_load_invoice_config()` — ถ้าไม่ตั้งค่าไว้ emit warning แล้ว skip ทันที (ไม่มี default-printer fallback)
2. อ่าน `sale.order` เอาฟิลด์ `x_studio_need_bill` (unwrap many2one shape) + `invoice_ids` — ถ้าค่าไม่ตรงกับ `invoice_need_bill_value` (default `"ปริ้นใบเสร็จ"`) log เฉย ๆ ไม่มี toast แล้ว return
3. resolve invoice ที่ post แล้วผ่าน `invoice_ids → account.move (move_type=out_invoice, state=posted)` เท่านั้น — **ไม่มี text-search ข้าม field, ไม่ auto-create invoice** (auto-create เป็นของ `test_odoo_counter_app.py`/KAN-71 เฉพาะ test tenant เท่านั้น ดู [[docs/adr/0003-auto-created-invoices-posted-immediately.md]])
4. ดาวน์โหลด PDF ผ่าน `_download_invoice_pdf()` (web-session login + `/report/pdf/<report_name>/<invoice_id>`, พอร์ตมาจาก `test_odoo_counter_app.py`)
5. พิมพ์เงียบผ่าน `subprocess.run([sumatra_path, '-print-to', printer, '-silent', pdf_path])`

Signal: `print_status(level, message)` โดย `level` เป็น `'ok'|'checking'|'warn'` — `MainWindow._on_invoice_print_status` เอาไปแสดงใน `lbl_status` เดียวกับ barcode/camera/Odoo status (สีเขียว/เทา/แดงอ่อน)

Config keys ใหม่ใน `crop_config.json` (อ่านผ่าน `_load_invoice_config()`): `invoice_printer_name` (default `""` — ตั้งใจไม่มี fallback), `invoice_report_id` (default `1204`, ต้องยืนยันกับ production ก่อนใช้จริง), `invoice_sumatra_path`, `invoice_need_bill_field`, `invoice_need_bill_value`. ยังไม่มี settings UI (T4/KAN-50) — ตั้งค่า printer ด้วยการแก้ไฟล์ JSON เองไปก่อน.

Scope: นี่คือ walking skeleton (T1/KAN-47) เท่านั้น — SumatraPDF ยังรันจาก local install (bundling เป็น T2/KAN-48), config ยังอยู่ใน `crop_config.json` เดิม (ย้ายไป `%LOCALAPPDATA%` เป็น T3/KAN-49), ยังไม่มี idempotency/dedupe กันสแกนซ้ำ (T5/KAN-51).

### `OdooStatusWorker`
```

- [ ] **Step 2: Update the Quick Reference list**

Find this exact block:

```markdown
`odoo_counter_app.py`

- `OdooConn` - XML-RPC connection cache
- `BarcodeWorker` - search picking/moves + lot/exp lookup
- `OdooSaveWorker` - post Odoo note (fire-and-forget จาก hideEvent)
- `_PingTransport` - XML-RPC timeout transport
```

Replace it with:

```markdown
`odoo_counter_app.py`

- `OdooConn` - XML-RPC connection cache
- `BarcodeWorker` - search picking/moves + lot/exp lookup + emits `invoice_job_ready`
- `OdooSaveWorker` - post Odoo note (fire-and-forget จาก hideEvent)
- `InvoicePrintWorker` - gate + resolve posted invoice + download PDF + silent SumatraPDF print (KAN-47)
- `_PingTransport` - XML-RPC timeout transport
```

- [ ] **Step 3: Commit**

```bash
git add PROJECT_CONTEXT.md
git commit -m "docs: document InvoicePrintWorker flow (KAN-47)

Adds the class to the Odoo Logic section and Quick Reference list,
matching the existing documentation style for BarcodeWorker/OdooSaveWorker."
```

---

### Task 7: Manual end-to-end verification against production

**Files:**
- Create (scratch, not committed): discovery script — save outside the repo (e.g. the scratchpad directory), do not add to git.
- Modify: `crop_config.json` (per-machine, gitignored — not committed either).
- Verify: `odoo_counter_app.py` (running instance), production Odoo (`https://tdfb.odoo.com`).

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: nothing — terminal verification step.

> **Requires the physical packing-station machine** (camera hardware + `ai_3g_v12.pt` model, and a real configured printer for Step 3's physical output). If running from a plain dev shell without that hardware, say so explicitly and stop rather than claiming verification succeeded, per this project's `CLAUDE.md`.

- [ ] **Step 1: Configure the printer for this machine**

Add (or edit) `crop_config.json` next to `odoo_counter_app.py`:

```json
{
  "invoice_printer_name": "<exact Windows printer name for this machine>"
}
```

If Task 2 Step 3 found that report id `1204` does **not** resolve to an `account.move` report in production, also add `"invoice_report_id": <confirmed id>` here. Leave any existing crop/conf keys in this file untouched — `_load_config_dict()` merges all keys from the same file.

- [ ] **Step 2: Find a qualifying sale order (need-bill flag set, has a posted invoice)**

Run this read-only script (adjust nothing):

```python
import xmlrpc.client

ODOO_URL = 'https://tdfb.odoo.com'
ODOO_DB = 'tdfb'
ODOO_USER = 'operation.engineer@tdfb.co'
ODOO_PASSWORD = 'KBT123'

common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")

orders = models.execute_kw(
    ODOO_DB, uid, ODOO_PASSWORD,
    'sale.order', 'search_read',
    [[['x_studio_need_bill', '=', 1], ['invoice_ids', '!=', False]]],
    {'fields': ['id', 'name'], 'limit': 5}
)
print("Candidate sale orders (need_bill set, has invoice):", orders)

for o in orders:
    pickings = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.picking', 'search_read',
        [[['sale_id', '=', o['id']], ['picking_type_id.name', 'ilike', 'Pack']]],
        {'fields': ['name', 'x_studio_tracking_no', 'state']}
    )
    print(f"  {o['name']} pickings:", pickings)
```

Expected: at least one order with a picking whose `state` is `assigned` and `x_studio_tracking_no` is a non-empty barcode. Note that barcode — it's the input for Step 3. Also note one order from the *original* JQL-style search with `invoice_ids = False` if any appear (or construct one) — needed for Step 5.

- [ ] **Step 3: Happy path — scan and confirm silent print**

```bash
python odoo_counter_app.py
```

Type the barcode from Step 2 followed by Enter. Watch the status label and stdout for `[Invoice]`-prefixed lines.

Expected: status line shows "กำลังดึงใบเสร็จ..." then "พิมพ์ใบเสร็จ ... แล้ว" in green; a `.pdf` appears under `invoices/` next to `odoo_counter_app.py`; the counting popup opens and behaves normally, unaffected by the invoice job; **the invoice physically prints on the configured printer** — confirm this on the hardware, not just the status message.

- [ ] **Step 4: Skip path — order without the need-bill flag**

Scan a barcode for a picking whose sale order does **not** have `x_studio_need_bill = "ปริ้นใบเสร็จ"`.

Expected: exactly one `[Invoice] ...: need-bill flag not set, skip` line in stdout, no status message change from this job, no print, counting proceeds normally.

- [ ] **Step 5: Warning path — flagged order with no posted invoice**

Scan a barcode for a picking whose sale order has the need-bill flag set but `invoice_ids` empty (from Step 2's note, or set one up in Odoo by removing/leaving an order un-invoiced).

Expected: status line shows `ยังไม่มีใบกำกับภาษี` in the warning color, one `[Invoice]` stdout line, no print, counting proceeds normally.

- [ ] **Step 6: Warning path — printer not configured**

Temporarily remove `invoice_printer_name` from `crop_config.json` (or blank it), restart the app, scan a flagged+invoiced order again.

Expected: status line shows `ยังไม่ได้ตั้งค่าเครื่องพิมพ์ใบเสร็จ`, stdout shows `printer not configured, skip`, no Odoo calls happen for this job (fails fast, before any RPC). Restore `invoice_printer_name` afterward.

- [ ] **Step 7: Queue serialization — two flagged scans back-to-back**

With the printer configured again, scan two different flagged+invoiced orders' barcodes in quick succession (before the first's status reaches "พิมพ์...แล้ว").

Expected: stdout shows the first job's `[Invoice] ... printed ...` line completing before the second job's `กำลังดึงใบเสร็จ...` status ever appears — confirms `_pump_invoice_queue` serializes correctly and no two `SumatraPDF` processes run concurrently.

No commit for this task — it's verification only, with no code changes (aside from the gitignored `crop_config.json`, which is per-machine and not committed).

---

## Self-Review Notes

- **Spec coverage:** Signal flow & queue wiring (spec Part 1) → Tasks 3 & 5. `InvoicePrintWorker` internals (spec Part 2) → Task 4, using the config loader from Task 1 and the download helper from Task 2. Config keys table → Task 1. Error/toast matrix → all covered by Task 4's branches and exercised individually in Task 7 Steps 4–6. Testing/verification section, including the report-id confirmation and hardware caveat → Task 2 Step 3 (report id) and Task 7 (everything else). Spec's "Docs" section (update `PROJECT_CONTEXT.md`) → Task 6, added once the code it describes (Tasks 1–5) already exists.
- **Placeholder scan:** no TBD/TODO; every step has literal code, literal commands, or literal read-only scripts with stated expected output.
- **Type consistency:** `_load_invoice_config() -> dict` (Task 1) keys (`printer_name`, `report_id`, `sumatra_path`, `need_bill_field`, `need_bill_value`) are the exact keys read by `InvoicePrintWorker.run()` in Task 4. `_download_invoice_pdf(models, uid, invoice_id, invoice_name, report_id)` (Task 2) signature matches its one call site in Task 4 exactly (`_download_invoice_pdf(models, uid, invoices[0]['id'], invoice_name, cfg['report_id'])`). `invoice_job_ready = pyqtSignal(int, str)` (Task 3) matches both its emit call (`sale_id[0], picking['name']`) and its connection/handler signature in Task 5 (`_on_invoice_job_ready(self, sale_order_id: int, picking_name: str)`). `InvoicePrintWorker(sale_order_id: int, picking_name: str)` (Task 4) matches its instantiation in Task 5's `_pump_invoice_queue`. `print_status = pyqtSignal(str, str)` (Task 4) matches `_on_invoice_print_status(self, level: str, message: str)` (Task 5).
