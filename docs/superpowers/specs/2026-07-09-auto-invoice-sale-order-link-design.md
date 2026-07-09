# Auto-created test invoices don't carry Sale Order ID / Sale Channel / Sale Type

## Problem

`test_odoo_counter_app.py` (test tenant only, `tdfb-02072026-test`) auto-creates and posts an
invoice when a Print-Bill Sale Order has zero invoices (see `CONTEXT.md` → "Auto-invoice
creation", [[docs/adr/0003-auto-created-invoices-posted-immediately.md]]). It does this via
Odoo's standard "Create Invoice" wizard (`sale.advance.payment.inv`), called over XML-RPC in
`BarcodeWorker._create_and_post_invoice()`.

Invoices created this way are missing three fields that invoices created through the normal
flow (a human clicking "Create Invoice" in the UI, or the marketplace sync) have filled in:

- **Sale Order ID** (`x_studio_sale_order_id`) — stays empty
- **Sale Channel** (`x_studio_related_field_1gq_1i7nmr48s`) — stays empty as a result
- **Sale Type** (`x_studio_sale_type`) — stays empty as a result

Confirmed via `fields_get` on `account.move` in the test tenant:

| Field | store | related |
|---|---|---|
| `x_studio_sale_order_id` | `True` | — (plain many2one to `sale.order`) |
| `x_studio_related_field_1gq_1i7nmr48s` (Sale Channel) | `False` | `x_studio_sale_order_id.source_id` |
| `x_studio_sale_type` (Sale Type) | `False` | `x_studio_sale_order_id.x_studio_sale_type` |

Sale Channel and Sale Type are non-stored related fields computed live from
`x_studio_sale_order_id`. Only `x_studio_sale_order_id` needs to be written — the other two
follow automatically. `_create_and_post_invoice()` already has `sale_order_id` in scope; it's
just never written back to the invoice.

Reproduced concretely: test-tenant invoice `INV/2026/07/00090` (id 1670186, `create_uid`
"Operation Engineer" — the account `test_odoo_counter_app.py` runs as, created 2026-07-08) has
`x_studio_sale_order_id: False`. Test-tenant invoice `INV/2026/07/00071` (id 1668761, created by
a different, human user on 2026-07-02) has it linked to sale order `MZS-240639`, and shows Sale
Channel/Sale Type correctly.

## Goal

Auto-created invoices should show Sale Order ID / Sale Channel / Sale Type in the Odoo UI,
matching normally-created invoices, so the data reads as complete. No known downstream
report/accounting process currently depends on these fields for auto-created invoices — this is
about data completeness/consistency, not fixing a break.

## Non-goals

- No backfill of already-created invoices that fell into this gap (e.g. the existing
  `INV/2026/07/00090` test invoice). Fix applies to invoices created from this point forward only.
- No change to `odoo_counter_app.py` (production) — it has no auto-invoice-creation code path at
  all; this entire feature is test-tenant-only per ADR-0003.
- No change to how/when the invoice is posted, no change to the PDF-fetch flow.

## Approaches considered

**A. Write `x_studio_sale_order_id` back onto the invoice right after posting (chosen).**
We already know `sale_order_id` at that point. One extra `write` call, best-effort, non-fatal.
Sale Channel/Sale Type follow for free since they're non-stored related fields.

**B. Set something on the sale order beforehand and hope Odoo's invoice-creation copies it.**
Rejected — we don't actually know what mechanism sets `x_studio_sale_order_id` on normally
created invoices (could be an automation unrelated to invoice creation itself, e.g. a
marketplace-sync job that stamps it after the fact by matching `invoice_origin`). Relying on an
unverified, uncontrolled mechanism is riskier than writing the field directly ourselves.

**C. Resolve Sale Type/Channel in the app without writing back to Odoo.**
Rejected — doesn't satisfy the actual goal (the Odoo record itself should read as complete);
anyone opening the invoice directly in Odoo would still see it as incomplete.

## Design

### Where

`test_odoo_counter_app.py`, class `BarcodeWorker`. One new method, one new call site inside
`_create_and_post_invoice()`.

### Implementation

```python
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
```

Call site in `_create_and_post_invoice()`, after posting succeeds:

```python
self._post_invoices_with_recovery(models, uid, new_invoice_ids)
self._link_sale_order(models, uid, new_invoice_ids, sale_order_id)
return new_invoice_ids
```

### Data flow

1. Wizard creates + `_run_create_invoices_with_recovery` returns `new_invoice_ids`.
2. `_post_invoices_with_recovery` posts them (unchanged).
3. `_link_sale_order` writes `x_studio_sale_order_id` on each of `new_invoice_ids`.
4. Odoo recomputes Sale Channel/Sale Type on next read since they're related, non-stored.
5. `_create_and_post_invoice` returns `new_invoice_ids` as before; callers are unaffected.

### Error handling

`_link_sale_order` has its own try/except, separate from `_create_and_post_invoice`'s outer
try/except. A failure here (e.g. the same "cannot marshal None" XML-RPC quirk already documented
elsewhere in this file) only logs to stdout — it does not raise, does not emit
`invoice_create_failed`, and does not affect the return value. The invoice was already validly
created and posted by this point; this field is enrichment, not a correctness requirement for
the invoice itself.

### Testing / verification

This project has no automated test suite (manual verification only, per `CLAUDE.md`). Verify by
running `test_odoo_counter_app.py` against the test tenant, scanning a barcode whose picking's
sale order has `x_studio_need_bill == 'ปริ้นใบเสร็จ'` and zero existing invoices, then opening the
newly created invoice in the Odoo UI and confirming Sale Order ID, Sale Channel, and Sale Type
are all populated. Also re-run the existing happy path once (a picking that already has an
invoice) to confirm no regression in PDF fetching.

### Docs

Add one sentence to `CONTEXT.md` → "Auto-invoice creation" noting that the invoice created by
this flow is now also linked back to its Sale Order via `x_studio_sale_order_id`.
