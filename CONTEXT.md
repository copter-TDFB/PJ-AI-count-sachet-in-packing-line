# PJ AI Count Sachet PK — Domain Context

A packing-line app: an AI camera counts sachets against the demand on an Odoo Pack Order, and — for orders flagged to need one — auto-prints a tax Invoice at the same time.

## Language

**Pack Order (Picking)**:
An Odoo `stock.picking` of type "Pack", looked up by scanned tracking barcode. Tied to exactly one **Sale Order** via `sale_id`.
_Avoid_: "picking" alone when the type matters — this app only ever acts on Pack-type pickings.

**Sale Order**:
The Odoo `sale.order` behind a Pack Order. Carries the **Print Bill flag** and, once invoiced, the resulting **Invoice**(s).

**Print Bill flag**:
The Odoo Studio field `x_studio_need_bill` on a Sale Order. When its value is exactly `"ปริ้นใบเสร็จ"`, the order is expected to have a printable Invoice attached by the time its Pack Order is scanned. The negative value is `"ไม่ปริ้นใบเสร็จ"`.
_Avoid_: "need bill", "invoice flag" — say "Print Bill flag" and quote the exact Thai value when precision matters.

**Invoice**:
An Odoo `account.move` with `move_type = out_invoice` **and** `state = posted`. Only a posted Invoice has a real tax invoice number and can be downloaded/printed — a `draft` Invoice has no number yet (`name` is `False` in Odoo until posting), and a `cancel` Invoice is not usable at all.
_Avoid_: "bill", "ใบเสร็จ" when the state (draft vs. posted vs. cancelled) actually matters — those words get used loosely in the UI copy, but this glossary entry is the precise one.

**Auto-invoice creation**:
The policy — test tenant only, implemented in `test_odoo_counter_app.py` — that when a Print-Bill Sale Order has literally zero Invoices (`invoice_ids` empty), the app creates one and posts it immediately, then continues on to fetch its PDF in the same pass, instead of silently giving up.
- Scoped narrowly on purpose: a Sale Order whose only existing Invoice(s) are `draft` or `cancel` does **not** trigger this — those are left exactly as today (silent skip) pending a separate follow-up decision. See [[docs/adr/0003-auto-created-invoices-posted-immediately.md]] for why posting happens immediately rather than leaving the invoice as Draft.
- The invoice created by this flow is also linked back to its Sale Order (`x_studio_sale_order_id`) right after posting, so Sale Channel and Sale Type — related fields computed from that link — show up the same as on a normally-created invoice. Best-effort; a failure here only logs to stdout and does not affect the invoice itself.

## Example dialogue

> **Dev**: An order has `need_bill = "ปริ้นใบเสร็จ"` but the PDF never shows up. Is that a bug?
> **Domain expert**: Check the Invoice state first. If `invoice_ids` is truly empty, auto-invoice creation should kick in and fix it. But if there's already an Invoice sitting there in `draft` or `cancel`, that's a known gap — we deliberately didn't touch those yet.
> **Dev**: Why not just post the existing draft instead of leaving it stuck?
> **Domain expert**: Different decision, different risk — we scoped this round to "no Invoice at all" only. Expanding to repair draft/cancelled Invoices is its own ticket.
