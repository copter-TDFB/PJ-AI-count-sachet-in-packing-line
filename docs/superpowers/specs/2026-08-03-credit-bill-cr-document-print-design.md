# Print the Cr. document alongside the receipt for credit-bill orders

## Problem

`InvoicePrintWorker` in `odoo_counter_app.py` gates on `sale.order.x_studio_need_bill`
against a single configured value (`invoice_need_bill_value`, default `"ปริ้นใบเสร็จ"`),
then downloads and silent-prints exactly one PDF via a hardcoded report id
(`invoice_report_id`, default `1204`). Any other `need_bill` value — including the
credit-bill case — just logs "need-bill flag not set, skip" and does nothing.

Production actually has a second `need_bill` selection value, `"ปริ้นใบกำกับ (เครดิต)"`,
for credit customers. Confirmed live in Odoo (`ir.actions.report`, both bound to
`account.move`):

| id | name | today's role |
|---|---|---|
| `1204` | 💵ใบกำกับภาษี/ใบเสร็จรับเงิน/ใบส่งสินค้า🟢 (ต้นฉบับ) | already `invoice_report_id` — cash receipt |
| `1200` | 💳ใบกำกับภาษี/ใบแจ้งหนี้/ใบส่งสินค้า (Cr.)🔵 (ต้นฉบับ) | not wired up yet — credit document |

For a credit-bill order, both documents need to print: the existing receipt (1204,
unchanged) plus the Cr. document (1200), in that order.

## Goal

When `need_bill` matches the credit value, `InvoicePrintWorker` downloads and prints
**both** `1204` and `1200` (in that order) against the same resolved posted invoice,
using the same download/print helpers already in place. The existing cash-bill path
(`need_bill == "ปริ้นใบเสร็จ"`) is untouched — same single document, same status
messages.

## Non-goals

- **No `(สำเนา)` / copy variants.** Odoo also has copy-variant reports (`1287`, `1288`,
  `1286`) — out of scope; only the `(ต้นฉบับ)` / original reports are printed.
- **No PDF merging.** The two documents print as two separate silent
  `_print_pdf_via_sumatra` calls to the same configured printer, not combined into one
  PDF file.
- **No retry/backoff on partial failure.** If the first document prints but the second
  fails, the worker stops and warns with a count — it does not retry.
- **No settings-dialog UI for the new report id or credit value.** Matches the existing
  precedent: `invoice_report_id`, `invoice_need_bill_field`, and `invoice_need_bill_value`
  are already JSON-only (no UI), only `invoice_printer_name` and the two auto-print/
  auto-create toggles have dialog checkboxes.
- **No change to the auto-create-if-missing step.** `_create_and_post_invoice` still
  fires the same way regardless of which `need_bill` value matched — only which
  report(s) get downloaded/printed afterward differs.
- **No generalization to an arbitrary-length "bill profile" list.** Only two values
  exist today (cash, credit); a config-driven N-value mapping is more generality than
  the current requirement calls for.

## Approaches considered

**A. Extend `InvoicePrintWorker` with a per-branch document list (chosen).** Add a pure
helper, `_resolve_documents_to_print(need_bill, cfg) -> list[tuple[int, str]]`, that maps
the matched `need_bill` value to an ordered list of `(report_id, label)` pairs. The
existing gate/create/resolve steps in `run()` stay as they are; only the final
download+print step becomes a loop over this list. Smallest diff, reuses
`_download_invoice_pdf`/`_print_pdf_via_sumatra` unchanged, and the resolution logic is
a pure function — testable the same way `_create_and_post_invoice` is tested today
(plain pytest, no Qt/Odoo needed).

**B. Fully config-driven "bill profiles" (a `need_bill` value → list-of-report-ids
mapping stored as JSON).** Same mechanism as A, but generalized so a third/fourth bill
type could be added via config alone. Rejected for now — YAGNI, only two values exist
today; nothing currently needs the extra generality.

**C. Separate `CreditInvoicePrintWorker` class for the credit path.** Rejected — would
duplicate the gate/resolve logic (~60 lines) across two classes that would need to stay
in sync, and the shared `_invoice_queue`/pump mechanism would need to pick which class
to construct.

## Design

### Where

`odoo_counter_app.py`: one new pure helper function near `_download_invoice_pdf`, two
new config keys read by `_load_invoice_config()`, one changed block in
`InvoicePrintWorker.run()`.

### New helper function

```python
def _resolve_documents_to_print(need_bill: str, cfg: dict) -> list[tuple[int, str]]:
    """Maps a matched need_bill value to the ordered list of (report_id, label) to
    download and print. Empty list means need_bill matched neither known value —
    caller logs and skips, unchanged from today's behavior."""
    need_bill = (need_bill or '').strip()
    if need_bill == cfg['need_bill_value']:
        return [(cfg['report_id'], str(cfg['report_id']))]
    if need_bill == cfg['need_bill_credit_value']:
        return [
            (cfg['report_id'], str(cfg['report_id'])),
            (cfg['cr_report_id'], f"Cr.({cfg['cr_report_id']})"),
        ]
    return []
```

### `InvoicePrintWorker.run()` change

The existing single-value comparison and the final download/print block become:

```python
need_bill_field = orders[0].get(cfg['need_bill_field'])
need_bill = need_bill_field[1] if isinstance(need_bill_field, (list, tuple)) else (need_bill_field or '')
documents = _resolve_documents_to_print(need_bill, cfg)
if not documents:
    print(f"[Invoice] {self.picking_name}: need-bill flag not set, skip", flush=True)
    return
```

*(existing `invoice_ids` / auto-create / resolve-posted-invoice steps unchanged)*

```python
printed = []
for report_id, label in documents:
    self.print_status.emit('checking', f'กำลังดึง {label} ({invoice_name})...')
    path = _download_invoice_pdf(models, uid, invoices[0]['id'], invoice_name, report_id)
    if not path:
        self.print_status.emit(
            'warn',
            f'{self.picking_name}: พิมพ์ไปแล้ว {len(printed)}/{len(documents)} ฉบับ — ดึง {label} ไม่สำเร็จ'
        )
        return
    _print_pdf_via_sumatra(cfg['sumatra_path'], printer, path)
    printed.append(label)

suffix = f' ({" + ".join(printed)})' if len(printed) > 1 else ''
self.print_status.emit('ok', f'พิมพ์ใบเสร็จ {invoice_name} แล้ว{suffix}')
print(f"[Invoice] {self.picking_name}: printed {invoice_name} ({', '.join(printed)})", flush=True)
```

For the cash branch (`documents == [(1204, '1204')]`), the loop runs once and `suffix`
is empty, so the `'ok'` toast stays byte-identical to today's
`"พิมพ์ใบเสร็จ {invoice_name} แล้ว"` — no observable change for existing cash orders.
The credit branch's toast becomes `"พิมพ์ใบเสร็จ {invoice_name} แล้ว (1204 + Cr.(1200))"`.
The stdout log line always lists every document printed, cash or credit alike, since
that line has no existing consumer to stay compatible with.

### Config keys

Added to `_load_invoice_config()`'s returned dict, alongside the existing
`need_bill_value`/`report_id`:

| Key | Default | Note |
|---|---|---|
| `invoice_need_bill_credit_value` | `"ปริ้นใบกำกับ (เครดิต)"` | second selection value of the same `x_studio_need_bill` field |
| `invoice_cr_report_id` | `1200` | `ir.actions.report` id for the Cr. document, same pattern as existing `invoice_report_id` |

No new save function is needed — these are read-only defaults like `invoice_report_id`
already is (no settings-dialog control writes them).

### Error handling

| Condition | Behavior |
|---|---|
| `need_bill` matches neither value | unchanged: log-only skip, no toast |
| `need_bill` matches cash value | unchanged: single document (1204), same messages |
| `need_bill` matches credit value, both documents download+print | `'ok'` with both labels |
| Credit: 1204 succeeds, 1200 download or print fails | `'warn'`: `"พิมพ์ไปแล้ว 1/2 ฉบับ — ดึง Cr.(1200) ไม่สำเร็จ"`, stops (no retry) — the 1204 page has already physically printed and cannot be recalled |
| Credit: 1204 itself fails | `'warn'`: `"พิมพ์ไปแล้ว 0/2 ฉบับ — ดึง 1204 ไม่สำเร็จ"`, stops before attempting 1200 |

### Testing

New pytest cases for `_resolve_documents_to_print` (no Qt/Odoo needed, same convention
as `test_invoice_posting.py`):

1. `need_bill == "ปริ้นใบเสร็จ"` → `[(1204, '1204')]`.
2. `need_bill == "ปริ้นใบกำกับ (เครดิต)"` → `[(1204, '1204'), (1200, 'Cr.(1200)')]`, in that
   order.
3. `need_bill == ""` / unrelated string → `[]`.
4. Config overrides (`report_id`/`cr_report_id`/`need_bill_credit_value` set to
   non-default values) are honored rather than the hardcoded defaults leaking through.

Manual verification (no automated coverage for the download/print I/O, consistent with
this project's existing testing boundary):

1. Scan a Pack barcode whose sale order has `need_bill == "ปริ้นใบเสร็จ"` → confirm
   unchanged behavior, exactly one page prints.
2. Scan a Pack barcode whose sale order has `need_bill == "ปริ้นใบกำกับ (เครดิต)"` →
   confirm both 1204 and 1200 download to `invoices/` and both print, in that order.
3. Temporarily point `invoice_cr_report_id` at an invalid id → confirm the credit case
   warns with a "1/2" count after 1204 has already printed, and does not attempt a
   second print of 1204.

### Docs

- Update `PROJECT_CONTEXT.md`'s `InvoicePrintWorker` (KAN-47) section: document the
  second `need_bill` value, the two new config keys, and the multi-document print loop
  replacing the single download/print step.
