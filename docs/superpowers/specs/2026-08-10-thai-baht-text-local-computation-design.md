# Thai baht text: compute locally instead of calling the Odoo server action

## Context

`_apply_thai_baht_wording()` in `odoo_counter_app.py` runs between creating a
draft invoice and posting it (`_create_and_post_invoice()`), filling in the
`x_studio_thai_bahttext` field on `account.move` so the printed tax invoice
shows the total in Thai words. It currently does this by calling Odoo's
`ir.actions.server.run()` on action id `956`.

### Why this needs to change

The Odoo account the app authenticates as (`operation.engineer@tdfb.co`) has
no access to the `ir.actions.server` model at all — confirmed live against
production:

```
ir.actions.server.read([956]) -> Fault: "You are not allowed to access
'Server Action' (ir.actions.server) records. This operation is allowed
for the following groups: Administration/Settings"
check_access_rights('read') on ir.actions.server -> False
```

The account's group list (checked live) does not include Administration/
Settings, and Odoo restricts `ir.actions.server` execution to that group by
design, since a server action can run arbitrary code. There is no narrower
group that grants execute-only access to one action via RPC.

Per the existing code order:

```
1. create invoice (wizard)
2. link x_studio_sale_order_id
3. _apply_thai_baht_wording()   <- raises here
4. action_post
```

If step 3 raises, `_create_and_post_invoice()` catches the exception and
returns `None` — but the invoice created in step 1 is already sitting in
Odoo as an un-posted draft. It never reaches step 4. In practice, someone
has been opening these drafts in the Odoo UI and manually running the
wording action (with their own, properly-privileged account) before posting.
The goal of this change is for the auto-invoice flow to finish unattended:
create → link → word → post, with no human step in between.

### Background: how the account lost access

The original design
(`2026-08-03-thai-baht-wording-before-invoice-posting-design.md`) specified
looking the action up **by name** (`'ใส่คำอ่าน ไทยบาท by feng'`) rather than
by numeric ID, explicitly so the code would keep working across databases
with different IDs for the same action, and stated as a precondition: "The
action must be available to the configured Odoo user."

Commit `77061e2` pointed `ODOO_URL`/`ODOO_DB` at a temporary test database
(`tdfb-10072026-test-v2`) and, in the same commit, replaced the by-name
lookup with a hardcoded `THAI_BAHT_WORDING_ACTION_ID = 956` — presumably
whatever id the action happened to have on that test copy. Commit `522327e`
reverted the URL/DB back to production but did not revert the action
lookup, so production has been calling action id `956` — a value only ever
verified against the test database — via an account that, per the finding
above, cannot run any server action regardless of how it's located. Both
problems (possibly-wrong id, and no execute permission at all) disappear
once the app stops calling `ir.actions.server` entirely, which is what this
design does. This document supersedes the 2026-08-03 spec for this feature.

## Decision

Replace the body of `_apply_thai_baht_wording()`: compute the Thai
baht-text string locally from each invoice's `amount_total` and `write()`
it directly to `x_studio_thai_bahttext`, instead of invoking the Odoo
server action. No other function changes — same name, same signature, same
call site and call order in `_create_and_post_invoice()`.

Rejected alternatives:
- **Keep calling the action, add a local fallback on failure.** Rejected —
  there is no scenario where the action call succeeds for this account, so
  the primary path is dead code that only adds noise (a guaranteed RPC
  round-trip and Fault on every invoice).
- **Ask an Odoo admin to grant this account access.** Rejected — requires
  an external dependency with no timeline, contradicts the "finish
  unattended" goal, and would mean broadening a service account's
  permissions to run arbitrary server actions (Odoo gates this at
  Administration/Settings specifically because of that risk) just to
  unblock one action.

## Algorithm

Standard Thai BAHTTEXT-style conversion (same rules used by Thai
accounting software / Excel's `BAHTTEXT`):

- Digits: ศูนย์ หนึ่ง สอง สาม สี่ ห้า หก เจ็ด แปด เก้า
- Place names within a 6-digit group: (units) สิบ ร้อย พัน หมื่น แสน
- Special cases within a group:
  - units digit `1` **and** the group has more than one significant digit
    → "เอ็ด" instead of "หนึ่ง" (e.g. 21 → ยี่สิบ**เอ็ด**, but 1 alone → หนึ่ง)
  - tens digit `2` → "ยี่สิบ" instead of "สองสิบ"
  - tens digit `1` → "สิบ" instead of "หนึ่งสิบ"
  - digit `0` in any place → omitted (no "ศูนย์ร้อย" etc.)
- Amounts ≥ 1,000,000: split into 6-digit groups, convert each group with
  the same rules (the "เอ็ด" rule is evaluated per-group, so e.g.
  11,000,000 → สิบเอ็ดล้าน), joined by "ล้าน" between groups (no trailing
  "ล้าน" after the final, least-significant group).
- Convert the amount to integer satang first (`round(amount * 100)`) to
  avoid float rounding artifacts, then `divmod(100)` to get baht and
  satang separately.
- Suffix: `...บาทถ้วน` when satang is 0, otherwise
  `...บาท<satang in words>สตางค์`.

Verified by hand against real production values already stored in
`x_studio_thai_bahttext` (entered via the working action, by an account
that does have permission):

| amount_total | x_studio_thai_bahttext |
|---|---|
| 625 | หกร้อยยี่สิบห้าบาทถ้วน |
| 21465 | สองหมื่นหนึ่งพันสี่ร้อยหกสิบห้าบาทถ้วน |
| 10518 | หนึ่งหมื่นห้าร้อยสิบแปดบาทถ้วน |
| 608 | หกร้อยแปดบาทถ้วน |
| 500 | ห้าร้อยบาทถ้วน |

All sampled amounts were whole baht (no satang case seen in real data);
satang handling is implemented per the standard algorithm but has no real
sample to check against.

## Code changes (all in `odoo_counter_app.py`)

- Add three module-level private helpers near `_apply_thai_baht_wording()`:
  - `_thai_six_digit_text(n: int) -> str` — converts 0–999999 to Thai words
  - `_thai_number_to_text(n: int) -> str` — handles million-grouping for
    larger integers
  - `_amount_to_thai_baht_text(amount: float) -> str` — satang split +
    "บาทถ้วน"/"...สตางค์" suffix, calls the above
- Rewrite `_apply_thai_baht_wording()`:
  ```python
  def _apply_thai_baht_wording(models, uid, invoice_ids: list):
      """Compute Thai baht-text locally and write it to x_studio_thai_bahttext —
      the account has no access to run ir.actions.server (Settings-only in Odoo)."""
      invoices = models.execute_kw(
          ODOO_DB, uid, ODOO_PASSWORD, 'account.move', 'read',
          [invoice_ids], {'fields': ['amount_total']}
      )
      for inv in invoices:
          text = _amount_to_thai_baht_text(inv['amount_total'])
          models.execute_kw(
              ODOO_DB, uid, ODOO_PASSWORD, 'account.move', 'write',
              [[inv['id']], {'x_studio_thai_bahttext': text}]
          )
  ```
- Delete the now-unused `THAI_BAHT_WORDING_ACTION_ID = 956` constant.

## Validation

One-time only (not a permanent test file, per explicit decision — this is a
dev-time confidence check, not an ongoing regression test):

1. Implement the helpers and the rewritten `_apply_thai_baht_wording()`.
2. In a scratch script (not committed), import the new
   `_amount_to_thai_baht_text` function from `odoo_counter_app.py`.
3. Read invoices from production that already have `x_studio_thai_bahttext`
   populated (the set gathered during this design session, ~30-45 records,
   entered via the working action under a properly-privileged account).
4. For each, compute `_amount_to_thai_baht_text(amount_total)` and diff
   against the stored string.
5. Any mismatch must be root-caused and fixed in the algorithm before the
   change is considered done.

## Non-goals

- No change to `_create_and_post_invoice()`'s call order or error handling.
- No admin permission request to Odoo.
- No dual-path (action + local fallback).
- No permanent regression test under `test/` for the comparison step.
- No attempt to separately fix or audit the stale test-database action id —
  moot once the action call is removed.

## Risks / edge cases

- **Float precision** on `amount_total` — handled by converting to integer
  satang via rounding before any text conversion.
- **Zero baht / zero satang** — both branches produce sensible (if unusual)
  output; not expected in practice for a real invoice total.
- **Amounts ≥ 1,000,000** — implemented per the standard grouping algorithm;
  no real sample this large was available to verify against.
- **Negative amounts** — out of scope. `amount_total` on an `out_invoice` is
  expected non-negative in this flow; not handled defensively.
