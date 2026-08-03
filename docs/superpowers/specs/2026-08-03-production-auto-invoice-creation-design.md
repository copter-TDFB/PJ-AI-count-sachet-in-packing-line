# Auto-create invoice in production when a Print-Bill order has none

## Problem

`InvoicePrintWorker` in `odoo_counter_app.py` (the production app) already gates on `need_bill`
and resolves/downloads/prints an existing posted invoice. But when a sale order needs a bill and
has **zero** invoices, it just warns and gives up:

```python
invoice_ids = orders[0].get('invoice_ids') or []
if not invoice_ids:
    self.print_status.emit('warn', f'{self.picking_name}: ยังไม่มีใบกำกับภาษี')
    return
```

`test_odoo_counter_app.py` already has a working reference for the missing half: when
`invoice_ids` is empty it calls Odoo's standard "Create Invoice" wizard
(`sale.advance.payment.inv`), posts the result immediately, then continues into the same
download/print flow. Per
[[docs/adr/0003-auto-created-invoices-posted-immediately.md]] and the
`2026-07-20-kan47-invoice-print-skeleton-design.md` / `2026-07-09-auto-invoice-sale-order-link-design.md`
specs, this was deliberately kept test-tenant-only — a posted invoice is legally final in
production and can only be corrected with a credit note. This spec **reverses that scoping
decision**: production should now auto-create too.

## Goal

When `InvoicePrintWorker` finds `need_bill` set and `invoice_ids` empty, it creates and posts an
invoice (same wizard, same immediate-post behavior as the test harness), then falls through into
the existing resolve/download/print steps unchanged — gated by a new, separate, per-machine
kill switch that defaults on.

## Non-goals

- **No wait-for-picking-done gating.** Confirmed with the user: creation happens at scan time
  (picking still `assigned`), not after the picking is validated to `done`. The
  `odoo_validate_clicked` webhook / `InvoiceAfterValidateWorker` poll-until-done pattern in
  `test_odoo_counter_app.py` is not being ported. (`BarcodeBridgeWorker` in production also has no
  code path to receive/parse inbound websocket messages today — out of scope here.)
- **No change to draft/cancelled-invoice handling.** Auto-create only fires when `invoice_ids` is
  literally empty, exactly like today and like the reference implementation. A sale order with an
  existing draft/cancelled invoice and no posted one still just warns ("ไม่มีใบกำกับภาษีที่ post
  แล้ว") — unchanged.
- **No changes to `test_odoo_counter_app.py`** — it already has this behavior; it's the reference.
- **No idempotency/dedupe work (T5/KAN-51).** Re-scanning the same barcode twice is an existing
  gap, not introduced or worsened materially by this change (a second attempt finds the
  first attempt's `invoice_ids` already populated and skips straight to resolve/print).
- **No backfill or repointing of `ODOO_URL`/`ODOO_DB`.** The working tree currently points
  `odoo_counter_app.py` at the test tenant (`tdfb-10072026-test-v2`) — that edit is left as-is by
  this change; repointing to `tdfb.odoo.com` is a separate, later decision by the user.

## Approaches considered

**A. Port the wizard-call logic as module-level functions next to `_download_invoice_pdf` (chosen).**
`odoo_counter_app.py` already keeps its Odoo RPC helpers (`_download_invoice_pdf`,
`_print_pdf_via_sumatra`, `_render_test_print_pdf`) as free functions, not methods on a worker
class. `test_odoo_counter_app.py` put the equivalent logic as instance methods on `BarcodeWorker`
because it also needed the `invoice_creating`/`invoice_create_failed` signals for UI blocking
during the wait-for-done poll. Since that poll isn't being ported (see Non-goals), there's no
reason to carry the method-on-worker shape over — a free function matches this file's existing
convention and is simpler to call from `InvoicePrintWorker.run()`.

**B. Port as methods on `InvoicePrintWorker`, mirroring the test file structure exactly.**
Rejected — no signals are needed beyond the `print_status` one `InvoicePrintWorker` already has,
so this would just be extra indirection (`self._create_and_post_invoice(...)` vs a plain function
call) for no benefit, and would diverge from how every other Odoo helper in this file is written.

## Design

### Where

`odoo_counter_app.py`: new module-level functions near `_download_invoice_pdf`, one changed branch
in `InvoicePrintWorker.run()`, one new config key + save function, one new checkbox in
`CropSettingsDialog`.

### New helper functions

Ported from `test_odoo_counter_app.py`'s `BarcodeWorker._create_and_post_invoice` /
`_run_create_invoices_with_recovery` / `_post_invoices_with_recovery` / `_link_sale_order`,
converted from instance methods to free functions taking `(models, uid, ...)` explicitly:

```python
def _create_and_post_invoice(models, uid, sale_order_id: int) -> list | None:
    """Auto-invoice creation: sale order has zero invoices — create one via Odoo's standard
    "Create Invoice" wizard (sale.advance.payment.inv, same path the UI button uses) and post it
    immediately so it has a real tax invoice number and can be printed. Returns new invoice_ids,
    or None on failure. Posted invoices are legally final in Odoo — see docs/adr/0003."""
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
```

The "cannot marshal None" RPC-response recovery and the `x_studio_sale_order_id` link-back are
carried over unchanged even though they were characterized against a since-renamed test tenant
(`tdfb-10072026-test` → `tdfb-10072026-test-v2`) — both are non-fatal/best-effort already, so
carrying them costs nothing if the quirk or the Studio field don't reproduce exactly the same way.

### `InvoicePrintWorker.run()` change

The existing empty-`invoice_ids` branch (today: warn + return) becomes:

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

Everything after this (resolve posted `out_invoice` from `invoice_ids`, download PDF, print via
Sumatra) is unchanged — it now also runs on the just-created invoice.

### Config keys

Added to `_load_invoice_config()` (same `crop_config.json`-derived dict), alongside the existing
`invoice_auto_print_enabled`:

| Key | Default | Note |
|---|---|---|
| `invoice_auto_create_enabled` | `True` | New kill switch, separate from `invoice_auto_print_enabled` — confirmed with user: defaults on, matching the existing auto-print switch's default |

New sibling save function, matching `_save_invoice_auto_print`'s merge-based pattern:

```python
def _save_invoice_auto_create(enabled: bool):
    config_path = _config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    d = _load_config_dict()
    d.update({'invoice_auto_create_enabled': enabled})
    config_path.write_text(json.dumps(d, indent=2), encoding='utf-8')
```

### Settings UI

`CropSettingsDialog`:
- New constructor param `current_auto_create: bool = True`.
- New checkbox `self.chk_auto_create = QCheckBox("อนุญาตให้สร้างใบกำกับภาษีอัตโนมัติ")` added to the
  existing "เครื่องพิมพ์ใบเสร็จ (Invoice Printer)" group box, directly below
  `self.chk_auto_print`.
- New `get_auto_create_enabled() -> bool` accessor, matching `get_auto_print_enabled()`.

`MainWindow._open_crop_settings()`:
```python
cur_auto_create = inv_cfg['auto_create_enabled']
dlg = CropSettingsDialog(cur_rect, cur_conf, cur_printer, cur_auto_print, cur_auto_create, parent=self)
...
new_auto_create = dlg.get_auto_create_enabled()
...
_save_invoice_auto_create(new_auto_create)
```

### Error handling

| Condition | Behavior |
|---|---|
| `invoice_ids` empty, auto-create switch off | unchanged: warning status "ยังไม่มีใบกำกับภาษี", stop |
| `invoice_ids` empty, auto-create switch on, wizard/post fails | warning status "สร้างใบกำกับภาษีไม่สำเร็จ", stdout has the underlying exception, stop — no partial state is left dangling for the app to worry about (worst case: Odoo has a posted invoice that just failed to resolve/print on this pass — a later manual reprint or next scan's `invoice_ids` check will find it) |
| `invoice_ids` empty, auto-create succeeds | falls through into existing resolve/download/print error handling unchanged |
| `_link_sale_order_on_invoice` fails | non-fatal, logged only — invoice is already posted, continues to resolve/download/print |

### Testing / verification

No automated test suite (per `CLAUDE.md`). Verify by running `python odoo_counter_app.py` from
source — currently configured against the test tenant (`tdfb-10072026-test-v2`), so this can be
exercised safely before ever repointing at production:

1. Scan a Pack barcode whose sale order has `need_bill` set and zero invoices → confirm an invoice
   is created, posted, and its PDF prints; check in Odoo that the invoice is posted with a real
   invoice number and (best-effort) `x_studio_sale_order_id` set.
2. Toggle the new "อนุญาตให้สร้างใบกำกับภาษีอัตโนมัติ" checkbox off in settings, re-scan the same
   scenario → confirm it warns "ยังไม่มีใบกำกับภาษี" and does not create anything (today's behavior).
3. Scan a sale order that already has a posted invoice → confirm unchanged behavior (resolve
   existing invoice, no second one created).
4. Scan the same barcode twice in a row (before/after the first invoice is created) → confirm the
   second pass finds `invoice_ids` populated and does not attempt to create a second invoice.
5. Confirm the settings dialog persists the new checkbox's state across restarts
   (`%LOCALAPPDATA%\odoo-counter\config.json`).

### Docs

- Update `PROJECT_CONTEXT.md`'s `InvoicePrintWorker` (KAN-47) section: replace the line stating
  "ไม่มี text-search ข้าม field, ไม่ auto-create invoice" with the new auto-create behavior and the
  new config key / kill switch.
- Add a new ADR noting this supersedes/extends ADR-0003's test-tenant-only scoping for production,
  recording the accepted risk (posted invoices are legally final; a bad count found later needs a
  credit note) and the mitigation (separate default-on kill switch, scan-time creation without
  wait-for-done gating).
