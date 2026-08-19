# Link Auto-Created Test Invoices to Their Sale Order — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make invoices auto-created by `test_odoo_counter_app.py`'s KAN-70 flow carry `x_studio_sale_order_id`, so Sale Order ID / Sale Channel / Sale Type show up on them the same way they do on normally-created invoices.

**Architecture:** One new best-effort helper method (`BarcodeWorker._link_sale_order`) called once, right after the existing invoice-posting call in `_create_and_post_invoice`. It writes a single stored field (`x_studio_sale_order_id`) on the invoice via the same `models.execute_kw` XML-RPC pattern already used throughout the file. Sale Channel and Sale Type are Odoo-side related fields computed from that link — no other write is needed.

**Tech Stack:** Python, `xmlrpc.client` against Odoo (test tenant `tdfb-02072026-test`). No new dependencies.

## Global Constraints

- Fix applies going forward only — no backfill of already-created invoices (e.g. the existing test-tenant `INV/2026/07/00090`, id 1670186).
- Touches `test_odoo_counter_app.py` only. `odoo_counter_app.py` (production) has no auto-invoice-creation code path and must not be touched.
- Do not change when/how the invoice is posted, and do not change the PDF-fetch flow.
- Write only `x_studio_sale_order_id`. Do not attempt to write `x_studio_related_field_1gq_1i7nmr48s` or `x_studio_sale_type` directly — both are non-stored `related` fields (readonly on `account.move`); writing to them would error.
- This project has no automated test suite, linter, or CI (per `CLAUDE.md`) — verification is manual. Do not introduce a pytest/unit-test scaffold as part of this fix.

---

### Task 1: Add `_link_sale_order` and wire it into `_create_and_post_invoice`, update docs

**Files:**
- Modify: `test_odoo_counter_app.py` (class `BarcodeWorker`, inside the block spanning current lines 320–329)
- Modify: `CONTEXT.md` (glossary entry "Auto-invoice creation", current lines 22–24)
- Test: none — no test suite in this project; see Task 2 for manual verification

**Interfaces:**
- Consumes: `models` (xmlrpc.client.ServerProxy for `/xmlrpc/2/object`), `uid` (int), `ODOO_DB`/`ODOO_PASSWORD` module constants — all already in scope inside `BarcodeWorker` methods.
- Produces: `BarcodeWorker._link_sale_order(self, models, uid, invoice_ids: list, sale_order_id: int) -> None`. No other task depends on this — it's a leaf call.

- [ ] **Step 1: Edit `test_odoo_counter_app.py` — add the call site and the new method**

Find this exact block (current lines ~320–329):

```python
            self._post_invoices_with_recovery(models, uid, new_invoice_ids)
            return new_invoice_ids
        except Exception as e:
            print(f"[Invoice] สร้าง/post ใบกำกับภาษีไม่สำเร็จ (sale order {sale_order_id}): {e}", flush=True)
            self.invoice_create_failed.emit(str(e))
            return None
        finally:
            self.invoice_create_unblock.emit()

    def _run_create_invoices_with_recovery(self, models, uid, sale_order_id: int, wizard_id: int, ctx: dict) -> list:
```

Replace it with:

```python
            self._post_invoices_with_recovery(models, uid, new_invoice_ids)
            self._link_sale_order(models, uid, new_invoice_ids, sale_order_id)
            return new_invoice_ids
        except Exception as e:
            print(f"[Invoice] สร้าง/post ใบกำกับภาษีไม่สำเร็จ (sale order {sale_order_id}): {e}", flush=True)
            self.invoice_create_failed.emit(str(e))
            return None
        finally:
            self.invoice_create_unblock.emit()

    def _link_sale_order(self, models, uid, invoice_ids: list, sale_order_id: int):
        """Best-effort: stamp x_studio_sale_order_id so Sale Type/Channel (related fields) show up.
        Non-fatal — invoice is already posted and legally final by this point."""
        try:
            models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'account.move', 'write',
                [invoice_ids, {'x_studio_sale_order_id': sale_order_id}]
            )
        except Exception as e:
            print(f"[Invoice] เชื่อม Sale Order ID ไม่สำเร็จ (invoice {invoice_ids}): {e}", flush=True)

    def _run_create_invoices_with_recovery(self, models, uid, sale_order_id: int, wizard_id: int, ctx: dict) -> list:
```

- [ ] **Step 2: Syntax-check the file (no heavy imports needed)**

Run:
```bash
python -m py_compile "test_odoo_counter_app.py"
```
Expected: no output, exit code 0. If it fails, the error message will point at a line number — re-check indentation of the new method (must be indented one level inside `class BarcodeWorker`, matching `_run_create_invoices_with_recovery` above it).

- [ ] **Step 3: Update `CONTEXT.md` glossary entry**

Find this exact line in the "Auto-invoice creation" entry:

```markdown
- Scoped narrowly on purpose: a Sale Order whose only existing Invoice(s) are `draft` or `cancel` does **not** trigger this — those are left exactly as today (silent skip) pending a separate follow-up decision. See [[docs/adr/0003-auto-created-invoices-posted-immediately.md]] for why posting happens immediately rather than leaving the invoice as Draft.
```

Add a new bullet directly after it:

```markdown
- Scoped narrowly on purpose: a Sale Order whose only existing Invoice(s) are `draft` or `cancel` does **not** trigger this — those are left exactly as today (silent skip) pending a separate follow-up decision. See [[docs/adr/0003-auto-created-invoices-posted-immediately.md]] for why posting happens immediately rather than leaving the invoice as Draft.
- The invoice created by this flow is also linked back to its Sale Order (`x_studio_sale_order_id`) right after posting, so Sale Channel and Sale Type — related fields computed from that link — show up the same as on a normally-created invoice. Best-effort; a failure here only logs to stdout and does not affect the invoice itself.
```

- [ ] **Step 4: Commit**

```bash
git add test_odoo_counter_app.py CONTEXT.md
git commit -m "feat(test-app): link auto-created invoices back to their sale order

Sale Order ID / Sale Channel / Sale Type were blank on invoices auto-created
by the KAN-70 flow because x_studio_sale_order_id was never written back.
Sale Channel and Sale Type are non-stored related fields computed from that
link, so writing x_studio_sale_order_id alone is sufficient."
```

---

### Task 2: Manual end-to-end verification against the test tenant

**Files:**
- Create (scratch, not committed): a throwaway script to locate a qualifying sale order — save it anywhere outside the repo (e.g. the scratchpad directory), do not add it to git.
- Verify: `test_odoo_counter_app.py` (running instance), Odoo UI (`https://tdfb-02072026-test.odoo.com`)

**Interfaces:**
- Consumes: `BarcodeWorker._link_sale_order` from Task 1 (verified indirectly — by observing its effect in Odoo, not by calling it directly).
- Produces: nothing consumed by later tasks — this is the terminal verification step.

> This task requires the physical packing-station machine (camera hardware + the `ai_3g_v12.pt` model file) because `test_odoo_counter_app.py` opens a camera at startup. If you're running this from a plain dev shell without that hardware, say so explicitly and stop here rather than claiming verification succeeded — per this project's own `CLAUDE.md` guidance.

- [ ] **Step 1: Find a qualifying sale order (Print-Bill flag set, zero invoices)**

Run this script (adjust nothing — it only reads):

```python
import xmlrpc.client

ODOO_URL = 'https://tdfb-02072026-test.odoo.com'
ODOO_DB = 'tdfb-02072026-test'
ODOO_USER = 'operation.engineer@tdfb.co'
ODOO_PASSWORD = '***REDACTED***'

common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")

orders = models.execute_kw(
    ODOO_DB, uid, ODOO_PASSWORD,
    'sale.order', 'search_read',
    [[['x_studio_need_bill', '=', 1], ['invoice_ids', '=', False]]],
    {'fields': ['id', 'name'], 'limit': 5}
)
print("Candidate sale orders (need_bill set, zero invoices):", orders)

for o in orders:
    pickings = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'stock.picking', 'search_read',
        [[['sale_id', '=', o['id']], ['picking_type_id.name', 'ilike', 'Pack']]],
        {'fields': ['name', 'x_studio_tracking_no', 'state']}
    )
    print(f"  {o['name']} pickings:", pickings)
```

Expected: at least one order with a picking whose `state` is `assigned` and `x_studio_tracking_no` is a non-empty barcode string. Note that barcode string — it's the input for Step 2. If none exist, create one manually in Odoo first (out of scope for this plan to automate).

- [ ] **Step 2: Run the test app and trigger the flow**

```bash
python test_odoo_counter_app.py
```

Type the barcode from Step 1 followed by Enter (the app's global keyboard listener picks it up the same as a real scanner). Watch stdout for `[Invoice]`-prefixed lines.

Expected: no `[Invoice] เชื่อม Sale Order ID ไม่สำเร็จ` line. (If it does appear, the invoice was still created and posted correctly — this fix is best-effort by design — but note the error message for follow-up.)

- [ ] **Step 3: Confirm in Odoo UI**

Re-run the Step 1 script's `sale.order` `read` for that same order's `invoice_ids` to get the new invoice id, or open the sale order directly in the Odoo web UI (`https://tdfb-02072026-test.odoo.com`) and follow its Invoices smart button.

Expected: the invoice now shows Sale Order ID, Sale Channel, and Sale Type populated — matching the layout already seen on `INV/2026/07/00071`.

- [ ] **Step 4: Confirm no regression in PDF fetch**

Check that a new PDF appeared under the `invoices/` folder next to `test_odoo_counter_app.py`, named after the invoice (see `_download_invoice_pdf`'s `out_dir = _get_base_dir() / 'invoices'`).

Expected: PDF file present and openable. This confirms Task 1's change didn't interfere with the existing `_maybe_fetch_invoice` → `_fetch_invoice_pdf` → `_download_invoice_pdf` chain that runs after `_create_and_post_invoice` returns.

No commit for this task — it's verification only, with no code changes.

---

## Self-Review Notes

- **Spec coverage:** Design section (write `x_studio_sale_order_id`, non-fatal error handling) → Task 1 Step 1. Docs section → Task 1 Step 3. Testing/verification section → Task 2. Scope/non-goals (no backfill, no production changes, no posting/PDF changes) → captured in Global Constraints and reaffirmed in Task 2's header note.
- **Placeholder scan:** no TBD/TODO; every step has literal code, literal commands, and literal expected output.
- **Type consistency:** `_link_sale_order(self, models, uid, invoice_ids: list, sale_order_id: int)` — same signature used in both the call site (Task 1 Step 1) and the method definition (same step). `sale_order_id` is the same parameter name already used by the enclosing `_create_and_post_invoice(self, models, uid, sale_order_id: int)`, so no renaming/confusion at the call site.
