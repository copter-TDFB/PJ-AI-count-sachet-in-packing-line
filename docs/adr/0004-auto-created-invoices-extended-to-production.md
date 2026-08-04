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
