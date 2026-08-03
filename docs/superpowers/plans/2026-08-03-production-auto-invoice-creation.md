# Auto-Create Invoice in Production (InvoicePrintWorker) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `InvoicePrintWorker` (production app, `odoo_counter_app.py`) finds a sale order that needs a bill but has zero invoices, it creates and posts one automatically — via the same `sale.advance.payment.inv` wizard `test_odoo_counter_app.py` already uses — then continues into the existing resolve/download/print flow, instead of warning and giving up.

**Architecture:** Four free functions ported from `test_odoo_counter_app.py`'s `BarcodeWorker` methods (`_create_and_post_invoice` + two recovery helpers + a sale-order link-back), added next to `odoo_counter_app.py`'s other Odoo helpers (`_download_invoice_pdf`, `_print_pdf_via_sumatra`). One branch inside `InvoicePrintWorker.run()` changes from "warn and return" to "auto-create (if enabled), then continue." A new `invoice_auto_create_enabled` config key (default `True`) and a matching checkbox in `CropSettingsDialog` gate the new behavior independently of the existing `invoice_auto_print_enabled` switch.

**Tech Stack:** Python, PyQt6, `xmlrpc.client` against Odoo (currently the test tenant `tdfb-10072026-test-v2`, per the working tree's uncommitted `ODOO_URL`/`ODOO_DB`). No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-03-production-auto-invoice-creation-design.md`. Read it if anything below is ambiguous.
- Single file touched for code: `odoo_counter_app.py`. Docs touched: `PROJECT_CONTEXT.md`, new `docs/adr/0004-auto-created-invoices-extended-to-production.md`.
- This project has no automated test suite, linter, or CI (per `CLAUDE.md`) — verification below is `python -m py_compile` (syntax) plus small standalone scripts run directly against the already-configured Odoo tenant, not pytest. Do not introduce a pytest/unit-test scaffold.
- `ODOO_URL`/`ODOO_DB`/`ODOO_USER`/`ODOO_PASSWORD` are already defined at module level in `odoo_counter_app.py` — reuse them; never redefine or hardcode a second copy in a verification script (`from odoo_counter_app import ODOO_DB, ODOO_USER, ODOO_PASSWORD, OdooConn`, etc.).
- The working tree currently has `ODOO_URL`/`ODOO_DB` pointed at the test tenant (`tdfb-10072026-test-v2`) — do not touch, revert, or commit that diff; it's the user's in-progress edit and unrelated to this feature.
- Config lives at `%LOCALAPPDATA%\odoo-counter\config.json`, loaded via `_load_config_dict()` / `_config_path()`. New settings must go through the existing merge-based save pattern (load full dict, update only the new key, write back) — never overwrite the whole file.
- New kill switch `invoice_auto_create_enabled` defaults to `True` when absent from config (confirmed with user — matches `invoice_auto_print_enabled`'s default).
- No wait-for-picking-done gating — invoice creation happens at barcode-scan time, while the picking is still `assigned`. Do not add polling or a websocket "Validate" listener (`BarcodeBridgeWorker` is not touched by this plan).
- Auto-create only fires when `invoice_ids` is literally empty — a sale order whose only invoices are draft/cancelled is unchanged (still just warns "ไม่มีใบกำกับภาษีที่ post แล้ว").
- Posted invoices are legally final in Odoo (no draft-then-review step) — this is an intentional, user-confirmed trade-off, not something to soften with an extra confirmation step.

---

### Task 1: Add `invoice_auto_create_enabled` config key + save function

**Files:**
- Modify: `odoo_counter_app.py` (functions `_save_invoice_auto_print` at current lines 135–142 and `_load_invoice_config` at current lines 145–166)
- Test: none — no test suite in this project; this task's own check is a syntax compile plus a direct read/write round-trip script (Step 3). Full end-to-end coverage is Task 6.

**Interfaces:**
- Produces: `_save_invoice_auto_create(enabled: bool) -> None`; `_load_invoice_config()`'s returned dict gains key `'auto_create_enabled': bool`. Task 2 and Task 4 both depend on this key/function.

- [ ] **Step 1: Add the save function and the config key**

Find this exact block:

```python
def _save_invoice_auto_print(enabled: bool):
    """Sibling of _save_invoice_printer() for the invoice auto-print toggle (KAN-125) —
    loads full dict, updates invoice_auto_print_enabled, writes back."""
    config_path = _config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    d = _load_config_dict()
    d.update({'invoice_auto_print_enabled': enabled})
    config_path.write_text(json.dumps(d, indent=2), encoding='utf-8')


def _load_invoice_config() -> dict:
    """Invoice auto-print settings (KAN-47), read from the same crop_config.json.
    Printer-picker UI lives in CropSettingsDialog (KAN-50) — printer_name is set there and
    persisted via _save_invoice_printer(), no more hand-editing the JSON file."""
    d = _load_config_dict()
    printer_name       = d.get('invoice_printer_name')
    auto_print_enabled = d.get('invoice_auto_print_enabled')
    report_id          = d.get('invoice_report_id')
    sumatra_path       = d.get('invoice_sumatra_path')
    need_bill_field    = d.get('invoice_need_bill_field')
    need_bill_value    = d.get('invoice_need_bill_value')
    return {
        'printer_name':       printer_name if isinstance(printer_name, str) else '',
        'auto_print_enabled': auto_print_enabled if isinstance(auto_print_enabled, bool) else True,
        'report_id':          report_id if isinstance(report_id, int) else 1204,
        'sumatra_path':       sumatra_path if isinstance(sumatra_path, str) and sumatra_path
                               else _default_sumatra_path(),
        'need_bill_field':    need_bill_field if isinstance(need_bill_field, str) and need_bill_field
                               else 'x_studio_need_bill',
        'need_bill_value':    need_bill_value if isinstance(need_bill_value, str) and need_bill_value
                               else 'ปริ้นใบเสร็จ',
    }
```

Replace it with:

```python
def _save_invoice_auto_print(enabled: bool):
    """Sibling of _save_invoice_printer() for the invoice auto-print toggle (KAN-125) —
    loads full dict, updates invoice_auto_print_enabled, writes back."""
    config_path = _config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    d = _load_config_dict()
    d.update({'invoice_auto_print_enabled': enabled})
    config_path.write_text(json.dumps(d, indent=2), encoding='utf-8')


def _save_invoice_auto_create(enabled: bool):
    """Sibling of _save_invoice_auto_print() for the invoice auto-create-if-missing kill
    switch — same merge-based save, kept as its own key so it can be toggled independently
    of auto-print."""
    config_path = _config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    d = _load_config_dict()
    d.update({'invoice_auto_create_enabled': enabled})
    config_path.write_text(json.dumps(d, indent=2), encoding='utf-8')


def _load_invoice_config() -> dict:
    """Invoice auto-print settings (KAN-47), read from the same crop_config.json.
    Printer-picker UI lives in CropSettingsDialog (KAN-50) — printer_name is set there and
    persisted via _save_invoice_printer(), no more hand-editing the JSON file."""
    d = _load_config_dict()
    printer_name        = d.get('invoice_printer_name')
    auto_print_enabled  = d.get('invoice_auto_print_enabled')
    auto_create_enabled = d.get('invoice_auto_create_enabled')
    report_id           = d.get('invoice_report_id')
    sumatra_path        = d.get('invoice_sumatra_path')
    need_bill_field     = d.get('invoice_need_bill_field')
    need_bill_value     = d.get('invoice_need_bill_value')
    return {
        'printer_name':        printer_name if isinstance(printer_name, str) else '',
        'auto_print_enabled':  auto_print_enabled if isinstance(auto_print_enabled, bool) else True,
        'auto_create_enabled': auto_create_enabled if isinstance(auto_create_enabled, bool) else True,
        'report_id':           report_id if isinstance(report_id, int) else 1204,
        'sumatra_path':        sumatra_path if isinstance(sumatra_path, str) and sumatra_path
                                else _default_sumatra_path(),
        'need_bill_field':     need_bill_field if isinstance(need_bill_field, str) and need_bill_field
                                else 'x_studio_need_bill',
        'need_bill_value':     need_bill_value if isinstance(need_bill_value, str) and need_bill_value
                                else 'ปริ้นใบเสร็จ',
    }
```

- [ ] **Step 2: Syntax-check the file**

Run:
```bash
python -m py_compile "odoo_counter_app.py"
```
Expected: no output, exit code 0.

- [ ] **Step 3: Verify the round trip directly**

Run:
```bash
python - <<'PYEOF'
from odoo_counter_app import _load_invoice_config, _save_invoice_auto_create
print('default:', _load_invoice_config()['auto_create_enabled'])
_save_invoice_auto_create(False)
print('after False:', _load_invoice_config()['auto_create_enabled'])
_save_invoice_auto_create(True)
print('restored:', _load_invoice_config()['auto_create_enabled'])
PYEOF
```
Expected output (exactly, in order):
```
default: True
after False: False
restored: True
```
This writes to the real `%LOCALAPPDATA%\odoo-counter\config.json` on whatever machine runs it (merge-based — every other key is left untouched), and ends by restoring the default (`True`), so it's safe to run on a shared dev machine.

- [ ] **Step 4: Commit**

```bash
git add odoo_counter_app.py
git commit -m "feat: add invoice_auto_create_enabled config key + save function

New kill switch, separate from invoice_auto_print_enabled (KAN-125),
for the upcoming auto-create-invoice-if-missing behavior. Defaults to
True. UI wiring and the behavior itself land in later commits."
```

---

### Task 2: Add the "อนุญาตให้สร้างใบกำกับภาษีอัตโนมัติ" checkbox to the settings dialog

**Files:**
- Modify: `odoo_counter_app.py` (`CropSettingsDialog.__init__` at current lines 1062–1157, `get_auto_print_enabled` at current lines 1235–1236, `MainWindow._open_crop_settings` at current lines 2074–2107)
- Test: none — see Step 3 for a quick offscreen accessor check; full click-through-and-persist verification is folded into Task 6 (it needs a running app anyway).

**Interfaces:**
- Consumes: `_load_invoice_config()` / `_save_invoice_auto_create()` from Task 1.
- Produces: `CropSettingsDialog.get_auto_create_enabled() -> bool`. No other task depends on this directly — `MainWindow._open_crop_settings` is both producer and sole consumer of the wiring.

- [ ] **Step 1: Add the constructor param and checkbox**

Find this exact block (constructor signature + the printer-box section that adds `chk_auto_print`):

```python
class CropSettingsDialog(QDialog):
    def __init__(self, current_rect: tuple, current_conf: float, current_printer: str = '', current_auto_print: bool = True, parent=None):
```

Replace with:

```python
class CropSettingsDialog(QDialog):
    def __init__(self, current_rect: tuple, current_conf: float, current_printer: str = '', current_auto_print: bool = True, current_auto_create: bool = True, parent=None):
```

Then find this exact block:

```python
        self.chk_auto_print = QCheckBox("เปิดใช้งานพิมพ์ใบเสร็จอัตโนมัติ")
        self.chk_auto_print.setChecked(current_auto_print)
        self.chk_auto_print.setStyleSheet("color:#eee; font-size:13px;")
        pv.addWidget(self.chk_auto_print)

        pl = QHBoxLayout()
```

Replace with:

```python
        self.chk_auto_print = QCheckBox("เปิดใช้งานพิมพ์ใบเสร็จอัตโนมัติ")
        self.chk_auto_print.setChecked(current_auto_print)
        self.chk_auto_print.setStyleSheet("color:#eee; font-size:13px;")
        pv.addWidget(self.chk_auto_print)

        self.chk_auto_create = QCheckBox("อนุญาตให้สร้างใบกำกับภาษีอัตโนมัติ")
        self.chk_auto_create.setChecked(current_auto_create)
        self.chk_auto_create.setStyleSheet("color:#eee; font-size:13px;")
        pv.addWidget(self.chk_auto_create)

        pl = QHBoxLayout()
```

- [ ] **Step 2: Add the accessor**

Find this exact block:

```python
    def get_auto_print_enabled(self) -> bool:
        return self.chk_auto_print.isChecked()
```

Replace with:

```python
    def get_auto_print_enabled(self) -> bool:
        return self.chk_auto_print.isChecked()

    def get_auto_create_enabled(self) -> bool:
        return self.chk_auto_create.isChecked()
```

- [ ] **Step 3: Wire it in `_open_crop_settings`**

Find this exact block:

```python
        inv_cfg = _load_invoice_config()
        cur_printer = inv_cfg['printer_name']
        cur_auto_print = inv_cfg['auto_print_enabled']
        dlg = CropSettingsDialog(cur_rect, cur_conf, cur_printer, cur_auto_print, parent=self)
```

Replace with:

```python
        inv_cfg = _load_invoice_config()
        cur_printer = inv_cfg['printer_name']
        cur_auto_print = inv_cfg['auto_print_enabled']
        cur_auto_create = inv_cfg['auto_create_enabled']
        dlg = CropSettingsDialog(cur_rect, cur_conf, cur_printer, cur_auto_print, cur_auto_create, parent=self)
```

Then find this exact block:

```python
                new_printer = dlg.get_printer()
                new_auto_print = dlg.get_auto_print_enabled()
                self._camera_worker.set_crop_rect(new_rect)
                self._camera_worker.set_conf(new_conf)
                try:
                    _save_settings(new_rect, new_conf)
                    _save_invoice_printer(new_printer)
                    _save_invoice_auto_print(new_auto_print)
```

Replace with:

```python
                new_printer = dlg.get_printer()
                new_auto_print = dlg.get_auto_print_enabled()
                new_auto_create = dlg.get_auto_create_enabled()
                self._camera_worker.set_crop_rect(new_rect)
                self._camera_worker.set_conf(new_conf)
                try:
                    _save_settings(new_rect, new_conf)
                    _save_invoice_printer(new_printer)
                    _save_invoice_auto_print(new_auto_print)
                    _save_invoice_auto_create(new_auto_create)
```

- [ ] **Step 4: Syntax-check the file**

```bash
python -m py_compile "odoo_counter_app.py"
```
Expected: no output, exit code 0.

- [ ] **Step 5: Quick offscreen accessor check**

```bash
QT_QPA_PLATFORM=offscreen python - <<'PYEOF'
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from odoo_counter_app import CropSettingsDialog
dlg = CropSettingsDialog((0.0, 0.0, 1.0, 1.0), 0.7, current_printer='', current_auto_print=True, current_auto_create=True)
print('initial:', dlg.get_auto_create_enabled())
dlg.chk_auto_create.setChecked(False)
print('after uncheck:', dlg.get_auto_create_enabled())
PYEOF
```
Expected output:
```
initial: True
after uncheck: False
```
This constructs the real dialog (no display needed, `QT_QPA_PLATFORM=offscreen`) and confirms the checkbox is wired correctly, without needing to click through the running app yet.

- [ ] **Step 6: Commit**

```bash
git add odoo_counter_app.py
git commit -m "feat: add settings-dialog checkbox for the auto-create-invoice kill switch

Wires CropSettingsDialog.chk_auto_create through _open_crop_settings,
same load/save pattern as the existing auto-print checkbox (KAN-125)."
```

---

### Task 3: Port the invoice-creation helper functions

**Files:**
- Modify: `odoo_counter_app.py` (insert after `_download_invoice_pdf`, which currently ends at line 261, right before the `# ── Worker: ค้นหา picking จาก barcode` comment at line 264)
- Test: none — Step 3 below is a direct live script against the currently-configured test tenant.

**Interfaces:**
- Consumes: `ODOO_DB`, `ODOO_USER`, `ODOO_PASSWORD` module constants (already defined); a live `models`/`uid` pair from `OdooConn`.
- Produces: `_create_and_post_invoice(models, uid, sale_order_id: int) -> list | None`. Task 4 depends on this function's name and signature exactly.

- [ ] **Step 1: Insert the four helper functions**

Find this exact block:

```python
    except Exception as e:
        print(f"[Invoice] ดาวน์โหลดไม่สำเร็จ: {e}", flush=True)
        return None


# ── Worker: ค้นหา picking จาก barcode ───────────────────────
class BarcodeWorker(QThread):
```

Replace with:

```python
    except Exception as e:
        print(f"[Invoice] ดาวน์โหลดไม่สำเร็จ: {e}", flush=True)
        return None


def _create_and_post_invoice(models, uid, sale_order_id: int) -> list | None:
    """Auto-invoice creation: sale order has zero invoices — create one via Odoo's standard
    "Create Invoice" wizard (sale.advance.payment.inv, same path the UI button uses) and post it
    immediately so it has a real tax invoice number and can be printed. Returns new invoice_ids,
    or None on failure. Posted invoices are legally final in Odoo — see docs/adr/0003 and
    docs/adr/0004."""
    try:
        ctx = {'active_model': 'sale.order', 'active_ids': [sale_order_id], 'active_id': sale_order_id}
        wizard_id = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'sale.advance.payment.inv', 'create',
            [{'advance_payment_method': 'delivered'}],  # 'delivered' = "Regular invoice", not down payment
            {'context': ctx}
        )
        new_invoice_ids = _run_create_invoices_with_recovery(models, uid, sale_order_id, wizard_id, ctx)
        if not new_invoice_ids:
            raise RuntimeError("Odoo ไม่สร้างใบกำกับภาษีให้ (ไม่มีรายการที่ invoice ได้)")
        _post_invoices_with_recovery(models, uid, new_invoice_ids)
        _link_sale_order_on_invoice(models, uid, new_invoice_ids, sale_order_id)
        return new_invoice_ids
    except Exception as e:
        print(f"[Invoice] สร้าง/post ใบกำกับภาษีไม่สำเร็จ (sale order {sale_order_id}): {e}", flush=True)
        return None


def _run_create_invoices_with_recovery(models, uid, sale_order_id: int, wizard_id: int, ctx: dict) -> list:
    """Call the wizard's create_invoices; if the RPC response itself fails to marshal, re-read
    invoice_ids to check whether the invoice was actually created before giving up."""
    try:
        models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'sale.advance.payment.inv', 'create_invoices',
            [[wizard_id]], {'context': ctx}
        )
    except Exception as e:
        print(f"[Invoice] create_invoices RPC error — เช็คซ้ำว่าสร้างสำเร็จจริงไหม: {e}", flush=True)
    orders = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, 'sale.order', 'read',
        [[sale_order_id]], {'fields': ['invoice_ids']}
    )
    return orders[0].get('invoice_ids') or []


def _post_invoices_with_recovery(models, uid, invoice_ids: list):
    """Call action_post; if the RPC response fails to marshal, re-read the invoice state before
    re-raising — the post may have actually succeeded server-side."""
    try:
        models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, 'account.move', 'action_post', [invoice_ids])
    except Exception:
        print(f"[Invoice] action_post RPC error — เช็คซ้ำสถานะจริงก่อนยอมแพ้", flush=True)
        invoices = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD, 'account.move', 'read',
            [invoice_ids], {'fields': ['state']}
        )
        if any(inv['state'] != 'posted' for inv in invoices):
            raise


def _link_sale_order_on_invoice(models, uid, invoice_ids: list, sale_order_id: int):
    """Best-effort: stamp x_studio_sale_order_id so Sale Type/Channel (related fields) show up.
    Non-fatal — invoice is already posted and legally final by this point."""
    try:
        models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD, 'account.move', 'write',
            [invoice_ids, {'x_studio_sale_order_id': sale_order_id}]
        )
    except Exception as e:
        print(f"[Invoice] เชื่อม Sale Order ID ไม่สำเร็จ (invoice {invoice_ids}): {e}", flush=True)


# ── Worker: ค้นหา picking จาก barcode ───────────────────────
class BarcodeWorker(QThread):
```

- [ ] **Step 2: Syntax-check the file**

```bash
python -m py_compile "odoo_counter_app.py"
```
Expected: no output, exit code 0.

- [ ] **Step 3: Find a qualifying sale order in the test tenant, then call the new function live**

First, find a sale order with `need_bill` set and zero invoices — either via Odoo's web UI (Sales, filtered on the Print-Bill field being set and the Invoices smart button showing 0), or via the `/odoo-read` skill (`~/.claude/skills/odoo-read/scripts/odoo_read.py search sale.order ...`) if available. Note its numeric `id`.

Then run (replace `SALE_ORDER_ID` with that real id — this makes a real, irreversible write against whatever tenant `odoo_counter_app.py`'s `ODOO_URL`/`ODOO_DB` currently point at, which as of this plan is the test tenant):

```bash
python - <<'PYEOF'
from odoo_counter_app import OdooConn, _create_and_post_invoice

SALE_ORDER_ID = 0  # <-- replace with a real id from a sale order with zero invoices

OdooConn.ensure()
uid, models = OdooConn._uid, OdooConn._models
result = _create_and_post_invoice(models, uid, SALE_ORDER_ID)
print('new invoice_ids:', result)
PYEOF
```
Expected: prints a non-empty list, e.g. `new invoice_ids: [123456]`. Confirm in the Odoo UI that this sale order now has one posted invoice with a real invoice number (and, best-effort, `x_studio_sale_order_id` set on it).

- [ ] **Step 4: Commit**

```bash
git add odoo_counter_app.py
git commit -m "feat: add auto-invoice-creation helper functions

Ported from test_odoo_counter_app.py's BarcodeWorker methods
(_create_and_post_invoice, _run_create_invoices_with_recovery,
_post_invoices_with_recovery, _link_sale_order) as module-level
functions, matching this file's existing convention for Odoo helpers
(_download_invoice_pdf, _print_pdf_via_sumatra). Not yet called from
InvoicePrintWorker — that's the next commit."
```

---

### Task 4: Wire auto-create into `InvoicePrintWorker.run()`

**Files:**
- Modify: `odoo_counter_app.py` (`InvoicePrintWorker.run`, the empty-`invoice_ids` branch at current lines 491–494)
- Test: none — Step 3 below is a direct live script; full barcode-scan-triggered coverage is Task 6.

**Interfaces:**
- Consumes: `cfg['auto_create_enabled']` (Task 1), `_create_and_post_invoice` (Task 3).
- Produces: the actual feature. No later task depends on anything new here.

- [ ] **Step 1: Change the empty-`invoice_ids` branch**

Find this exact block:

```python
            invoice_ids = orders[0].get('invoice_ids') or []
            if not invoice_ids:
                self.print_status.emit('warn', f'{self.picking_name}: ยังไม่มีใบกำกับภาษี')
                return
```

Replace with:

```python
            invoice_ids = orders[0].get('invoice_ids') or []
            if not invoice_ids:
                if not cfg['auto_create_enabled']:
                    self.print_status.emit('warn', f'{self.picking_name}: ยังไม่มีใบกำกับภาษี')
                    return
                self.print_status.emit('checking', f'{self.picking_name}: กำลังสร้างใบกำกับภาษี...')
                invoice_ids = _create_and_post_invoice(models, uid, self.sale_order_id)
                if not invoice_ids:
                    self.print_status.emit('warn', f'{self.picking_name}: สร้างใบกำกับภาษีไม่สำเร็จ')
                    return
```

- [ ] **Step 2: Syntax-check the file**

```bash
python -m py_compile "odoo_counter_app.py"
```
Expected: no output, exit code 0.

- [ ] **Step 3: Verify live, without needing the camera**

`InvoicePrintWorker` only needs `(sale_order_id, picking_name)` — it doesn't touch the camera or barcode listener, so it can be exercised directly. Prerequisites on the machine running this:
- `invoice_printer_name` in config must be set to a printer name present in `QPrinterInfo.availablePrinterNames()`. On Windows, "Microsoft Print to PDF" is normally always available and safe to use for this check (it "prints" to a PDF file, not paper) — set it via `_save_invoice_printer('Microsoft Print to PDF')` first if not already configured.
- `invoice_auto_create_enabled` must be `True` (Task 1's default, unless something changed it since).
- A real sale order in the currently-configured tenant with `need_bill` set and zero invoices (find a fresh one the same way as Task 3 Step 3 — reusing the same order Task 3 already invoiced will just resolve/print the existing invoice, which also confirms the fall-through path works, but doesn't exercise auto-create again).

```bash
python - <<'PYEOF'
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from odoo_counter_app import InvoicePrintWorker

SALE_ORDER_ID = 0                # <-- replace with a real id, zero invoices, need_bill set
PICKING_NAME = 'VERIFY-TASK4'    # only used in log/status messages

w = InvoicePrintWorker(SALE_ORDER_ID, PICKING_NAME)
messages = []
w.print_status.connect(lambda level, msg: messages.append((level, msg)))
w.run()  # direct synchronous call — no QThread event loop needed for a one-shot check
for m in messages:
    print(m)
PYEOF
```
Expected: a `('checking', 'VERIFY-TASK4: กำลังสร้างใบกำกับภาษี...')` message, followed by a `('checking', 'กำลังดึงใบเสร็จ ...')` message, ending in `('ok', 'พิมพ์ใบเสร็จ ... แล้ว')`. Confirm in Odoo that the sale order now has a posted invoice. (If SumatraPDF isn't installed on this machine, the last step may instead be a `warn` about the print sub-process — that's a pre-existing local-environment gap, not a regression; the important confirmation is that the invoice was created, posted, and its PDF downloaded.)

Then re-run with the new `invoice_auto_create_enabled` switch off, against another zero-invoice order, to confirm the unchanged fallback:
```bash
python - <<'PYEOF'
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from odoo_counter_app import InvoicePrintWorker, _save_invoice_auto_create

_save_invoice_auto_create(False)
try:
    SALE_ORDER_ID = 0  # <-- another real id, zero invoices, need_bill set
    w = InvoicePrintWorker(SALE_ORDER_ID, 'VERIFY-TASK4-OFF')
    messages = []
    w.print_status.connect(lambda level, msg: messages.append((level, msg)))
    w.run()
    for m in messages:
        print(m)
finally:
    _save_invoice_auto_create(True)  # restore default
PYEOF
```
Expected: exactly one message, `('warn', 'VERIFY-TASK4-OFF: ยังไม่มีใบกำกับภาษี')`, and no invoice created for that order.

- [ ] **Step 4: Commit**

```bash
git add odoo_counter_app.py
git commit -m "feat: auto-create invoice when a Print-Bill order has none

InvoicePrintWorker now calls _create_and_post_invoice() before giving
up when invoice_ids is empty, gated by the invoice_auto_create_enabled
kill switch (default on). Mirrors test_odoo_counter_app.py's reference
behavior; see docs/adr/0003 and docs/adr/0004 for the accepted risk."
```

---

### Task 5: Update docs (`PROJECT_CONTEXT.md`, new ADR)

**Files:**
- Modify: `PROJECT_CONTEXT.md` (`InvoicePrintWorker` (KAN-47) section, current lines 443–464)
- Create: `docs/adr/0004-auto-created-invoices-extended-to-production.md`
- Test: none — documentation only.

**Interfaces:** none — this task produces docs, not code.

- [ ] **Step 1: Update the `InvoicePrintWorker` logic list and config-keys line in `PROJECT_CONTEXT.md`**

Find this exact block:

```markdown
Logic ใน `run()`:

1. เช็ก `invoice_printer_name` จาก `_load_invoice_config()` — ถ้าไม่ตั้งค่าไว้ emit warning แล้ว skip ทันที (ไม่มี default-printer fallback)
2. เช็กว่า printer นั้นยังอยู่ใน `QPrinterInfo.availablePrinterNames()` หรือไม่ (KAN-50) — ถ้าตั้งค่าไว้แต่เครื่องพิมพ์ถูกลบ/เปลี่ยนชื่อไปแล้ว emit warning คนละข้อความจาก "ยังไม่ได้ตั้งค่า" แล้ว skip ทันที เช่นกัน (**ไม่มี fallback ไปเครื่องพิมพ์อื่น**)
3. อ่าน `sale.order` เอาฟิลด์ `x_studio_need_bill` (unwrap many2one shape) + `invoice_ids` — ถ้าค่าไม่ตรงกับ `invoice_need_bill_value` (default `"ปริ้นใบเสร็จ"`) log เฉย ๆ ไม่มี toast แล้ว return
4. resolve invoice ที่ post แล้วผ่าน `invoice_ids → account.move (move_type=out_invoice, state=posted)` เท่านั้น — **ไม่มี text-search ข้าม field, ไม่ auto-create invoice** (auto-create เป็นของ `test_odoo_counter_app.py`/KAN-71 เฉพาะ test tenant เท่านั้น ดู [[docs/adr/0003-auto-created-invoices-posted-immediately.md]])
5. ดาวน์โหลด PDF ผ่าน `_download_invoice_pdf()` (web-session login + `/report/pdf/<report_name>/<invoice_id>`, พอร์ตมาจาก `test_odoo_counter_app.py`)
6. พิมพ์เงียบผ่าน `_print_pdf_via_sumatra(sumatra_path, printer, pdf_path)` — helper กลาง (KAN-50) ที่ห่อ `subprocess.run([sumatra_path, '-print-to', printer, '-silent', pdf_path], check=True, timeout=30)` ตัวเดียวกันกับที่ปุ่ม "พิมพ์ทดสอบ" ใน settings dialog เรียกใช้ ทำให้สอง path พิมพ์ผ่าน pipeline เดียวกันจริง ๆ ไม่ใช่ reimplementation คนละที่

Signal: `print_status(level, message)` โดย `level` เป็น `'ok'|'checking'|'warn'` — `MainWindow._on_invoice_print_status` เอาไปแสดงใน `lbl_status` เดียวกับ barcode/camera/Odoo status (สีเขียว/เทา/แดงอ่อน)

Config keys (อ่านผ่าน `_load_invoice_config()` จาก `%LOCALAPPDATA%\odoo-counter\config.json`): `invoice_printer_name` (default `""` — ตั้งใจไม่มี fallback), `invoice_auto_print_enabled` (default `True`, KAN-125), `invoice_report_id` (default `1204`, ต้องยืนยันกับ production ก่อนใช้จริง), `invoice_sumatra_path`, `invoice_need_bill_field`, `invoice_need_bill_value`. Settings UI มีแล้ว (T4/KAN-50) — ตั้งค่า printer ผ่าน dropdown ในหน้าตั้งค่าเฟือง (`CropSettingsDialog`) แทนการแก้ไฟล์ JSON เอง; บันทึกผ่าน `_save_invoice_printer()` / `_save_invoice_auto_print()` (merge-based เหมือน `_save_settings()`).
```

Replace with:

```markdown
Logic ใน `run()`:

1. เช็ก `invoice_printer_name` จาก `_load_invoice_config()` — ถ้าไม่ตั้งค่าไว้ emit warning แล้ว skip ทันที (ไม่มี default-printer fallback)
2. เช็กว่า printer นั้นยังอยู่ใน `QPrinterInfo.availablePrinterNames()` หรือไม่ (KAN-50) — ถ้าตั้งค่าไว้แต่เครื่องพิมพ์ถูกลบ/เปลี่ยนชื่อไปแล้ว emit warning คนละข้อความจาก "ยังไม่ได้ตั้งค่า" แล้ว skip ทันที เช่นกัน (**ไม่มี fallback ไปเครื่องพิมพ์อื่น**)
3. อ่าน `sale.order` เอาฟิลด์ `x_studio_need_bill` (unwrap many2one shape) + `invoice_ids` — ถ้าค่าไม่ตรงกับ `invoice_need_bill_value` (default `"ปริ้นใบเสร็จ"`) log เฉย ๆ ไม่มี toast แล้ว return
4. ถ้า `invoice_ids` ว่างและ `invoice_auto_create_enabled` (default `True`) เปิดอยู่ — สร้าง+post invoice ให้อัตโนมัติผ่าน `_create_and_post_invoice()` (wizard `sale.advance.payment.inv`, พอร์ตมาจาก `test_odoo_counter_app.py`/KAN-71) ก่อนไปต่อข้อ 5 ด้านล่าง สร้างตอนสแกน barcode ทันที ไม่รอ picking เป็น `done` — ถ้าปิด kill switch นี้ไว้ หรือสร้าง/post ไม่สำเร็จ ก็ emit warning แล้ว skip เหมือนพฤติกรรมเดิม (posted invoice legally final ใน Odoo แล้ว แก้ทีหลังได้แค่ credit note — ดู [[docs/adr/0003-auto-created-invoices-posted-immediately.md]] และ [[docs/adr/0004-auto-created-invoices-extended-to-production.md]])
5. resolve invoice ที่ post แล้วผ่าน `invoice_ids → account.move (move_type=out_invoice, state=posted)` — ไม่มี text-search ข้าม field
6. ดาวน์โหลด PDF ผ่าน `_download_invoice_pdf()` (web-session login + `/report/pdf/<report_name>/<invoice_id>`, พอร์ตมาจาก `test_odoo_counter_app.py`)
7. พิมพ์เงียบผ่าน `_print_pdf_via_sumatra(sumatra_path, printer, pdf_path)` — helper กลาง (KAN-50) ที่ห่อ `subprocess.run([sumatra_path, '-print-to', printer, '-silent', pdf_path], check=True, timeout=30)` ตัวเดียวกันกับที่ปุ่ม "พิมพ์ทดสอบ" ใน settings dialog เรียกใช้ ทำให้สอง path พิมพ์ผ่าน pipeline เดียวกันจริง ๆ ไม่ใช่ reimplementation คนละที่

Signal: `print_status(level, message)` โดย `level` เป็น `'ok'|'checking'|'warn'` — `MainWindow._on_invoice_print_status` เอาไปแสดงใน `lbl_status` เดียวกับ barcode/camera/Odoo status (สีเขียว/เทา/แดงอ่อน)

Config keys (อ่านผ่าน `_load_invoice_config()` จาก `%LOCALAPPDATA%\odoo-counter\config.json`): `invoice_printer_name` (default `""` — ตั้งใจไม่มี fallback), `invoice_auto_print_enabled` (default `True`, KAN-125), `invoice_auto_create_enabled` (default `True`, kill switch แยกต่างหากสำหรับการสร้าง invoice อัตโนมัติ — ปิดได้โดยไม่กระทบการพิมพ์ invoice ที่มีอยู่แล้ว), `invoice_report_id` (default `1204`, ต้องยืนยันกับ production ก่อนใช้จริง), `invoice_sumatra_path`, `invoice_need_bill_field`, `invoice_need_bill_value`. Settings UI มีแล้ว (T4/KAN-50) — ตั้งค่า printer และ toggle ทั้งสองผ่านหน้าตั้งค่าเฟือง (`CropSettingsDialog`) แทนการแก้ไฟล์ JSON เอง; บันทึกผ่าน `_save_invoice_printer()` / `_save_invoice_auto_print()` / `_save_invoice_auto_create()` (merge-based เหมือน `_save_settings()`).
```

- [ ] **Step 2: Create the new ADR**

Create `docs/adr/0004-auto-created-invoices-extended-to-production.md`:

```markdown
# Auto-created invoices are no longer test-tenant-only

ADR-0003 scoped auto-invoice-creation (create-and-post-immediately via the `sale.advance.payment.inv`
wizard) to `test_odoo_counter_app.py` running against a test tenant, specifically because a posted
invoice is legally final in production Odoo and a bad count discovered later can only be corrected
with a credit note. This ADR extends the same behavior to `odoo_counter_app.py` running against
production (`tdfb.odoo.com`): when a Print-Bill sale order has zero invoices, the app now creates
and posts one automatically, at barcode-scan time (before the picking is validated to `done`), the
same way the test harness always has. The trade-off ADR-0003 already accepted — a mis-count found
after the fact needs a credit note, not a simple edit — is now accepted for production traffic too.
The one added mitigation: a separate `invoice_auto_create_enabled` kill switch (default on,
independent of the existing `invoice_auto_print_enabled` switch from KAN-125) lets an operator
disable auto-creation on a single machine without affecting printing of invoices that already
exist.
```

- [ ] **Step 3: Commit**

```bash
git add PROJECT_CONTEXT.md docs/adr/0004-auto-created-invoices-extended-to-production.md
git commit -m "docs: document production auto-invoice creation

Updates PROJECT_CONTEXT.md's InvoicePrintWorker section with the new
auto-create step and invoice_auto_create_enabled config key, and adds
ADR-0004 recording that this extends ADR-0003's test-tenant-only
scoping to production."
```

---

### Task 6: Full end-to-end manual verification (real app, real barcode)

**Files:**
- Verify only: `odoo_counter_app.py` (running instance), Odoo UI (whatever tenant `ODOO_URL`/`ODOO_DB` currently point at)
- No code changes, no commit for this task.

**Interfaces:**
- Consumes: everything from Tasks 1–4, observed end-to-end rather than called directly.

> This task requires a working camera and the `ai_3g_v12.pt` model file, because `odoo_counter_app.py` opens a camera at startup — same requirement as this project's existing plans (e.g. `2026-07-09-auto-invoice-sale-order-link.md` Task 2). If running from a dev machine without that hardware, say so explicitly and stop here rather than claiming this task passed.

- [ ] **Step 1: Confirm settings persist across restarts**

Run the app, open settings (gear icon), confirm "อนุญาตให้สร้างใบกำกับภาษีอัตโนมัติ" is checked by default (or matches whatever Task 1 Step 3 last left in config), uncheck it, save, close the app, reopen, open settings again.
Expected: checkbox is still unchecked. Re-check it and save to restore the default before continuing.

- [ ] **Step 2: Scan a Print-Bill barcode with zero invoices**

Find (or set up) a Pack picking whose sale order has `need_bill` set and zero invoices — same lookup approach as Task 3 Step 3. Scan its barcode (or type it + Enter, matching the global-listener input path).

Expected: status line shows "กำลังสร้างใบกำกับภาษี..." then the usual "กำลังดึงใบเสร็จ ..." then "พิมพ์ใบเสร็จ ... แล้ว" (or a warn about the print sub-process if SumatraPDF isn't installed locally — see Task 4 Step 3's caveat). The counting popup behaves exactly as before (unaffected). Confirm in Odoo that a posted invoice now exists for that sale order.

- [ ] **Step 3: Scan the same barcode again**

Expected: this time `invoice_ids` is already populated, so it goes straight to resolve/download/print — no second invoice is created (confirm invoice count in Odoo is still 1 for that sale order).

- [ ] **Step 4: Toggle the kill switch off, scan a different zero-invoice order**

In settings, uncheck "อนุญาตให้สร้างใบกำกับภาษีอัตโนมัติ" and save. Scan a barcode for a different Print-Bill order with zero invoices.

Expected: status line shows "ยังไม่มีใบกำกับภาษี" (today's pre-existing behavior) and no invoice is created. Re-check the box and save afterward to leave the machine in its default state.

---

## Self-Review Notes

- **Spec coverage:** Goal (auto-create + fall through to existing print flow) → Task 4. New helper functions → Task 3. Config key + kill switch, default on → Task 1. Settings UI → Task 2. Non-goals (no wait-for-done, no draft/cancelled handling change, no `test_odoo_counter_app.py` changes, no `ODOO_URL`/`ODOO_DB` repointing) → captured in Global Constraints and untouched by every task's file list. Error-handling table → Task 4 Step 1's code + Step 3's verification of both branches (auto-create success and kill-switch-off). Docs section → Task 5. Testing/verification section's five scenarios → Tasks 3–4's direct scripts plus Task 6's full run (scenario 5, settings persistence, is Task 6 Step 1).
- **Placeholder scan:** no TBD/TODO. `SALE_ORDER_ID = 0` placeholders in Tasks 3/4 are explicitly flagged as "replace with a real id" for a value that can only be known by querying the live tenant at verification time — not a specification gap, and each occurrence says exactly how to obtain the real value.
- **Type consistency:** `_create_and_post_invoice(models, uid, sale_order_id: int) -> list | None` — same signature at its definition (Task 3) and its two call sites (Task 3's own verification script, Task 4's edit to `InvoicePrintWorker.run()`). `_save_invoice_auto_create(enabled: bool)` and `_load_invoice_config()['auto_create_enabled']` — same key name (`invoice_auto_create_enabled` in the JSON file, `auto_create_enabled` in the returned dict) used consistently across Task 1 (definition), Task 2 (UI wiring reads/writes it), Task 4 (`cfg['auto_create_enabled']` check), and Task 5 (docs). `CropSettingsDialog.get_auto_create_enabled()` matches the name used in Task 2 Step 3's `_open_crop_settings` wiring.
