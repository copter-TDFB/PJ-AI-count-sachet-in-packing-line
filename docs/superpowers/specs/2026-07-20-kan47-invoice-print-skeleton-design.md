# KAN-47 (T1): Invoice auto-print walking skeleton

## Problem

Operators currently print customer invoices manually from Odoo. The packing-line app
(`odoo_counter_app.py`) already knows the sale order the moment a scanned barcode resolves to a
`stock.picking` (it reads `picking.sale_id → sale.order` today for shop routing, KAN-52/54). This
is the thinnest end-to-end slice that adds silent invoice printing to that existing flow: gate on
a Studio field, resolve the already-posted invoice, download the PDF, print it — without touching
the counting flow.

A working reference already exists: `test_odoo_counter_app.py` (test tenant only) implements the
Odoo-side fetch logic end-to-end as part of the KAN-70 demo + KAN-71 gate work. It is **not**
directly deployable to production as-is — see Non-goals.

## Goal

Scanning a Pack barcode whose sale order has `x_studio_need_bill == "ปริ้นใบเสร็จ"` silently prints
the already-posted customer invoice PDF on a configured printer, without interrupting the counting
popup, running from source against **production** Odoo (`tdfb.odoo.com`).

## Non-goals

- **No auto-invoice-creation.** `test_odoo_counter_app.py`'s `_create_and_post_invoice()` is
  test-tenant-only per [[docs/adr/0003-auto-created-invoices-posted-immediately.md]] — production
  invoices are already created by the normal business/accounting process. If none exists yet at
  scan time, that's a warning + skip, not something this app creates.
- **No wait-for-pack-done gating.** `InvoiceAfterValidateWorker`'s poll-until-`state == 'done'`
  loop exists only because the test harness creates the invoice itself and needs the picking
  finalized first. Production checks for an existing posted invoice at picking-found time; no
  polling.
- **No packaging/bundling of SumatraPDF** (T2, KAN-48).
- **No config relocation to `%LOCALAPPDATA%`** (T3, KAN-49) — new keys go into the existing
  `crop_config.json` loader for now.
- **No printer-picker settings UI** (T4, KAN-50) — printer name is set by hand-editing
  `crop_config.json` until T4 ships.
- **No idempotency/dedupe/retry** (T5, KAN-51) — re-scanning the same barcode twice can enqueue a
  duplicate print job in this ticket's scope; T5 owns preventing that.

## Approaches considered

**A. Serial one-shot `InvoicePrintWorker` instances, chained via `finished` (chosen).**
`MainWindow` holds a `deque` of pending `(sale_order_id, picking_name)` jobs and starts a new
`InvoicePrintWorker` (a `QThread`) only when no worker is currently running; each worker's
`finished` signal pumps the next job. Matches the existing `OdooSaveWorker`/`BarcodeWorker` shape
already used throughout this file — no new lifecycle pattern, no thread to start at boot or stop
in `closeEvent`.

**B. One persistent `QThread` with an internal `queue.Queue`, started once at app boot.**
Matches the ticket text's literal wording ("single background FIFO queue thread") and mirrors
`CameraWorker`'s inner `_infer` loop. Rejected for this ticket: it requires extra lifecycle
management (explicit start/stop/sentinel, and a crash mid-loop silently stops all future invoice
printing for the rest of the session with no obvious symptom) that buys nothing given invoice
jobs are low-frequency and bursts are rare — both approaches guarantee strictly-serial execution,
which is the actual requirement.

**C. `queue.Queue` + `ThreadPoolExecutor(max_workers=1)`.** Rejected — introduces a concurrency
primitive not used anywhere else in this codebase for equivalent behavior to A/B (YAGNI).

## Design

### Where

`odoo_counter_app.py`. Changes to `BarcodeWorker` (one field, one signal), one new
`InvoicePrintWorker` class, and wiring in `MainWindow`.

### `BarcodeWorker` change

Extend the existing `sale.order` read (already fetched for `SHOP_IDENTITY_FIELD`, KAN-52/54 — no
extra RPC round trip) to also request `x_studio_need_bill`, and add:

```python
invoice_job_ready = pyqtSignal(int, str)  # sale_order_id, picking_name
```

Fired at the same point `origin_ready` fires — independent of whether 3g-move validation finds
anything, and independent of `origin` being blank. The need-bill gate check itself stays inside
`InvoicePrintWorker`, not here; `BarcodeWorker`'s only new responsibility is "read one more field,
emit one more signal when `sale_id` is present."

### `MainWindow` queue wiring (Approach A)

```python
from collections import deque
...
self._invoice_queue: deque = deque()
self._invoice_worker: InvoicePrintWorker | None = None

def _on_invoice_job_ready(self, sale_order_id: int, picking_name: str):
    self._invoice_queue.append((sale_order_id, picking_name))
    self._pump_invoice_queue()

def _pump_invoice_queue(self):
    if self._invoice_worker is not None or not self._invoice_queue:
        return
    sale_order_id, picking_name = self._invoice_queue.popleft()
    w = InvoicePrintWorker(sale_order_id, picking_name)
    w.print_status.connect(self._on_invoice_print_status)   # (level, message)
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
```

`self.lbl_status` is the same status-bar label already used for barcode/camera/Odoo-connection
messages (and the same one `test_odoo_counter_app.py` uses for its invoice status text) — no new
UI element. This queue is independent of `_workers`/`_save_workers` and never blocks counting.

### `InvoicePrintWorker`

Ported from `test_odoo_counter_app.py`'s `_fetch_invoice_pdf` / `_download_invoice_pdf`, with
auto-creation and wait-for-done removed, and `os.startfile()` replaced by a silent SumatraPDF
print:

```python
class InvoicePrintWorker(QThread):
    print_status = pyqtSignal(str, str)  # ('ok'|'checking'|'warn'), message

    def __init__(self, sale_order_id: int, picking_name: str):
        super().__init__()
        self.sale_order_id = sale_order_id
        self.picking_name = picking_name

    def run(self):
        try:
            cfg = _load_invoice_config()
            printer = cfg.get('printer_name')
            if not printer:                                    # AC3 — no default-printer fallback
                self.print_status.emit('warn', 'ยังไม่ได้ตั้งค่าเครื่องพิมพ์ใบเสร็จ')
                print(f"[Invoice] {self.picking_name}: printer not configured, skip", flush=True)
                return

            OdooConn.ensure()
            uid, models = OdooConn._uid, OdooConn._models

            orders = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, 'sale.order', 'read',
                [[self.sale_order_id]], {'fields': [cfg['need_bill_field'], 'invoice_ids']})
            if not orders:
                print(f"[Invoice] {self.picking_name}: sale order not found, skip", flush=True)
                return

            need_bill_field = orders[0].get(cfg['need_bill_field'])
            need_bill = need_bill_field[1] if isinstance(need_bill_field, (list, tuple)) else (need_bill_field or '')
            if (need_bill or '').strip() != cfg['need_bill_value']:
                print(f"[Invoice] {self.picking_name}: need-bill flag not set, skip", flush=True)   # AC2 — log only, no toast
                return

            invoice_ids = orders[0].get('invoice_ids') or []
            if not invoice_ids:
                self.print_status.emit('warn', f'{self.picking_name}: ยังไม่มีใบกำกับภาษี')
                return

            invoices = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, 'account.move', 'search_read',
                [[['id', 'in', invoice_ids], ['move_type', '=', 'out_invoice'], ['state', '=', 'posted']]],
                {'fields': ['name'], 'limit': 1, 'order': 'id desc'})
            if not invoices:
                self.print_status.emit('warn', f'{self.picking_name}: ไม่มีใบกำกับภาษีที่ post แล้ว')
                return
            invoice_name = invoices[0]['name']

            self.print_status.emit('checking', f'กำลังดึงใบเสร็จ {invoice_name}...')
            path = _download_invoice_pdf(models, uid, invoices[0]['id'], invoice_name, cfg['report_id'])
            if not path:
                self.print_status.emit('warn', f'ดึงใบเสร็จ {invoice_name} ไม่สำเร็จ')
                return

            subprocess.run([cfg['sumatra_path'], '-print-to', printer, '-silent', str(path)],
                           check=True, timeout=30)
            self.print_status.emit('ok', f'พิมพ์ใบเสร็จ {invoice_name} แล้ว')
            print(f"[Invoice] {self.picking_name}: printed {invoice_name}", flush=True)

        except Exception as e:
            OdooConn.reset()
            self.print_status.emit('warn', f'{self.picking_name}: {e}')
            print(f"[Invoice] {self.picking_name}: error — {e}", flush=True)
```

`_download_invoice_pdf` is the same web-session-login + `/report/pdf/<report_name>/<invoice_id>`
function already in `test_odoo_counter_app.py`, with the report id parameterized from config
instead of hardcoded, and pointed at production's `ODOO_URL`/`ODOO_DB`/credentials (already
defined at module level in `odoo_counter_app.py`).

### Config keys

Added to the existing `crop_config.json` loader (`_load_config_dict()` / same pattern as
`_load_crop()`, `_load_conf()`):

| Key | Default | Note |
|---|---|---|
| `invoice_printer_name` | `""` | Empty on purpose — AC3 forbids a default-printer fallback |
| `invoice_report_id` | `1204` | Carried over from the test harness; **must be reconfirmed against production** during implementation (AC5) — not assumed correct |
| `invoice_sumatra_path` | `C:\Program Files\SumatraPDF\SumatraPDF.exe` | T1 runs from source with a locally-installed SumatraPDF; bundling it is T2 |
| `invoice_need_bill_field` | `x_studio_need_bill` | |
| `invoice_need_bill_value` | `ปริ้นใบเสร็จ` | |

No settings-dialog UI exists for these yet (T4). For T1, the operator sets
`invoice_printer_name` by hand-editing `crop_config.json` once — accepted stopgap.

### Error handling

| Condition | Behavior |
|---|---|
| Need-bill flag not set | stdout log line only, no status message (AC2) |
| Printer not configured | warning status + stdout log, skip entirely — checked first, before any Odoo call |
| `sale_id` missing / sale order not found | stdout log, no status message (nothing to report to the operator) |
| No `invoice_ids` on sale order | warning status + stdout log |
| No posted `out_invoice` found | warning status + stdout log |
| PDF download failure (session auth, report fetch, non-PDF response) | warning status + stdout log |
| SumatraPDF print failure (missing binary, non-zero exit, timeout) | warning status + stdout log |
| Success | green status message + stdout log |

Every failure path returns from `InvoicePrintWorker.run()` normally (or via the outer
`except`) — none of them raise into the queue-pump wiring, and none of them touch the counting
popup or `CounterPanel`. `OdooConn.reset()` on the outer exception matches the existing pattern in
`BarcodeWorker`/`OdooStatusWorker`.

### Testing / verification

This project has no automated test suite (manual verification only, per `CLAUDE.md`). Verify by
running `python odoo_counter_app.py` from source against **production** Odoo:

1. Scan a Pack barcode whose sale order has `x_studio_need_bill = "ปริ้นใบเสร็จ"` and an existing
   posted invoice → confirm the PDF prints on the configured printer, counting popup is
   unaffected, status line shows the printed invoice name.
2. Scan an order without the flag → confirm one stdout log line, no status message, no print.
3. Scan an order with the flag but no posted invoice yet → confirm a warning status message,
   counting continues normally.
4. Unset `invoice_printer_name` → confirm warning + skip, no crash.
5. Scan two flagged orders back-to-back before the first print finishes → confirm the second job
   waits in `_invoice_queue` and prints only after the first completes (no overlapping
   `SumatraPDF` processes).
6. Confirm `invoice_report_id: 1204` actually resolves the correct report in **production** (not
   just the test tenant) before treating it as the shipped default — record whatever id is
   confirmed.

**Requires packing-station hardware** (an actual configured printer) to verify step 1's physical
output — flag this explicitly to whoever runs verification; it cannot be confirmed from a dev
machine alone.

### Docs

Update `PROJECT_CONTEXT.md` with a new section describing the invoice auto-print flow once T1
lands, per `CLAUDE.md`'s "keep it updated when behavior changes" instruction.
