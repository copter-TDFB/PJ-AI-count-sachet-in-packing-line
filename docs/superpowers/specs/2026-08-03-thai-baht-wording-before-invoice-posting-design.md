# Thai-baht wording before invoice posting

## Purpose

When the application auto-creates a customer invoice, run Odoo's server action
`ใส่คำอ่าน ไทยบาท by feng` while the invoice is still a draft.  Only then post
the invoice.

## Flow

1. The existing sale-order invoice wizard creates one or more draft
   `account.move` records.
2. The application resolves the Odoo server action by its displayed name,
   `ใส่คำอ่าน ไทยบาท by feng`.
3. It runs that action with the newly-created invoice IDs as the active
   `account.move` records.
4. On success, the existing `account.move.action_post` call posts the
   invoices.
5. The existing sale-order linking remains after posting.

## Error handling

If the server action cannot be found or fails, the auto-invoice flow reports
the error and returns failure.  It must not call `action_post`; the invoice
remains Draft so it can be inspected or corrected in Odoo.

## Compatibility

The action is looked up by name rather than a database-specific numeric ID.
This permits the same source to work against Odoo databases where the server
action has a different ID.  The action must be available to the configured
Odoo user.

## Testing

Add a unit regression test using the existing XML-RPC test double.  It will
assert that the server-action lookup and invocation occur before
`account.move.action_post`, and that a server-action failure prevents posting.
