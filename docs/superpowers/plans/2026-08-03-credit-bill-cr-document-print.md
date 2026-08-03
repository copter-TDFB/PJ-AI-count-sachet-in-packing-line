# Print the Cr. Document Alongside the Receipt for Credit-Bill Orders — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a sale order's `x_studio_need_bill` is set to the credit value, `InvoicePrintWorker` (production app, `odoo_counter_app.py`) downloads and silent-prints **both** the existing receipt report (`1204`) and a second "Cr." report (`1200`), in that order, instead of only the receipt. The existing cash-bill path (`need_bill == "ปริ้นใบเสร็จ"`) is unchanged — still exactly one document, byte-identical status messages.

**Architecture:** A new pure helper, `_resolve_documents_to_print(need_bill, cfg) -> list[tuple[int, str]]`, maps the matched `need_bill` value to an ordered list of `(report_id, label)` pairs to download+print — `[(1204, '1204')]` for cash, `[(1204, '1204'), (1200, 'Cr.(1200)')]` for credit, `[]` for neither (unchanged skip). `InvoicePrintWorker.run()`'s single download/print call becomes a loop over this list, stopping and warning with a "printed N/M" count on the first failure. Two new config keys (`invoice_need_bill_credit_value` default `"ปริ้นใบกำกับ (เครดิต)"`, `invoice_cr_report_id` default `1200`) are read the same JSON-only way as the existing `invoice_report_id`.

**Tech Stack:** Python, PyQt6, `xmlrpc.client`/`requests` against Odoo. Tests: plain `pytest` against the new pure helper only (no Qt/Odoo needed), matching `test_invoice_posting.py`'s existing convention. No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-03-credit-bill-cr-document-print-design.md`. Read it if anything below is ambiguous.
- Files touched: `odoo_counter_app.py` (code), `test_invoice_posting.py` (tests), `PROJECT_CONTEXT.md` (docs). No other file changes.
- Confirmed live against production Odoo (`tdfb.odoo.com`, via the read-only `odoo-read` skill): `ir.actions.report` id `1200` = `💳ใบกำกับภาษี/ใบแจ้งหนี้/ใบส่งสินค้า (Cr.)🔵 (ต้นฉบับ)`, bound to `account.move` — same model as the existing `1204` report. Do not substitute the `(สำเนา)`/copy variants (`1287`, `1288`, `1286`) — out of scope.
- New config keys are JSON-only (no settings-dialog UI), matching the existing precedent for `invoice_report_id`/`invoice_need_bill_field`/`invoice_need_bill_value` — do not add a `CropSettingsDialog` checkbox or field for this.
- No PDF merging — the two documents print as two separate `_print_pdf_via_sumatra` calls to the same configured printer, not combined into one PDF.
- No retry/backoff on partial failure. If the first document prints but the second fails to download/print, stop and emit a `'warn'` status with an explicit "printed N/M" count — do not retry, and do not re-print the document(s) that already succeeded.
- No change to the auto-create-if-missing step (`_create_and_post_invoice`) — it fires the same way regardless of which `need_bill` value matched; only which report(s) get downloaded/printed afterward differs.
- Cash-branch behavior must stay byte-identical to today: when `_resolve_documents_to_print` returns exactly one document, the `'ok'` toast text is unchanged (`"พิมพ์ใบเสร็จ {invoice_name} แล้ว"`, no suffix).
- This project has no CI/linter (per `CLAUDE.md`). The new pure helper gets real pytest coverage (this codebase already has `pytest` installed and `test_invoice_posting.py` uses it — confirmed by running it). The download/print loop wired into `InvoicePrintWorker.run()` has no automated test (Qt + live Odoo I/O) — verify manually, consistent with this project's existing testing boundary.

---

### Task 1: Add `_resolve_documents_to_print` helper + two new config keys (TDD)

**Files:**
- Modify: `odoo_counter_app.py:156-179` (`_load_invoice_config`) — add `cr_report_id` and `need_bill_credit_value` keys.
- Modify: `odoo_counter_app.py` — insert new function `_resolve_documents_to_print` immediately after `_load_invoice_config` (currently ends at line 179, right before the `# ── Connection cache ─` comment at line 182).
- Test: `test_invoice_posting.py` — add import + 4 new test functions.

**Interfaces:**
- Produces: `_resolve_documents_to_print(need_bill: str, cfg: dict) -> list[tuple[int, str]]`; `_load_invoice_config()`'s returned dict gains keys `'cr_report_id': int` and `'need_bill_credit_value': str`. Task 2 depends on both.

- [ ] **Step 1: Write the failing tests**

Open `test_invoice_posting.py`. Change the top import line:

```python
from odoo_counter_app import _create_and_post_invoice
```

to:

```python
from odoo_counter_app import _create_and_post_invoice, _resolve_documents_to_print
```

Then append these four test functions at the end of the file:

```python
def test_resolve_documents_to_print_cash_value_returns_single_report():
    cfg = {
        'need_bill_value': 'ปริ้นใบเสร็จ',
        'need_bill_credit_value': 'ปริ้นใบกำกับ (เครดิต)',
        'report_id': 1204,
        'cr_report_id': 1200,
    }

    assert _resolve_documents_to_print('ปริ้นใบเสร็จ', cfg) == [(1204, '1204')]


def test_resolve_documents_to_print_credit_value_returns_both_reports_in_order():
    cfg = {
        'need_bill_value': 'ปริ้นใบเสร็จ',
        'need_bill_credit_value': 'ปริ้นใบกำกับ (เครดิต)',
        'report_id': 1204,
        'cr_report_id': 1200,
    }

    assert _resolve_documents_to_print('ปริ้นใบกำกับ (เครดิต)', cfg) == [
        (1204, '1204'),
        (1200, 'Cr.(1200)'),
    ]


def test_resolve_documents_to_print_unrelated_value_returns_empty_list():
    cfg = {
        'need_bill_value': 'ปริ้นใบเสร็จ',
        'need_bill_credit_value': 'ปริ้นใบกำกับ (เครดิต)',
        'report_id': 1204,
        'cr_report_id': 1200,
    }

    assert _resolve_documents_to_print('', cfg) == []
    assert _resolve_documents_to_print('บางค่าอื่นที่ไม่เกี่ยว', cfg) == []


def test_resolve_documents_to_print_honors_config_overrides_not_hardcoded_defaults():
    cfg = {
        'need_bill_value': 'CASH',
        'need_bill_credit_value': 'CREDIT',
        'report_id': 111,
        'cr_report_id': 222,
    }

    assert _resolve_documents_to_print('CASH', cfg) == [(111, '111')]
    assert _resolve_documents_to_print('CREDIT', cfg) == [(111, '111'), (222, 'Cr.(222)')]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
python -m pytest test_invoice_posting.py -v
```
Expected: the 4 new tests fail with `ImportError: cannot import name '_resolve_documents_to_print'` (the function doesn't exist yet). The 2 pre-existing tests still pass.

- [ ] **Step 3: Add the config keys and the helper function**

In `odoo_counter_app.py`, find this exact block:

```python
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

Replace it with:

```python
def _load_invoice_config() -> dict:
    """Invoice auto-print settings (KAN-47), read from the same crop_config.json.
    Printer-picker UI lives in CropSettingsDialog (KAN-50) — printer_name is set there and
    persisted via _save_invoice_printer(), no more hand-editing the JSON file."""
    d = _load_config_dict()
    printer_name           = d.get('invoice_printer_name')
    auto_print_enabled     = d.get('invoice_auto_print_enabled')
    auto_create_enabled    = d.get('invoice_auto_create_enabled')
    report_id              = d.get('invoice_report_id')
    cr_report_id           = d.get('invoice_cr_report_id')
    sumatra_path           = d.get('invoice_sumatra_path')
    need_bill_field        = d.get('invoice_need_bill_field')
    need_bill_value        = d.get('invoice_need_bill_value')
    need_bill_credit_value = d.get('invoice_need_bill_credit_value')
    return {
        'printer_name':        printer_name if isinstance(printer_name, str) else '',
        'auto_print_enabled':  auto_print_enabled if isinstance(auto_print_enabled, bool) else True,
        'auto_create_enabled': auto_create_enabled if isinstance(auto_create_enabled, bool) else True,
        'report_id':           report_id if isinstance(report_id, int) else 1204,
        'cr_report_id':        cr_report_id if isinstance(cr_report_id, int) else 1200,
        'sumatra_path':        sumatra_path if isinstance(sumatra_path, str) and sumatra_path
                                else _default_sumatra_path(),
        'need_bill_field':     need_bill_field if isinstance(need_bill_field, str) and need_bill_field
                                else 'x_studio_need_bill',
        'need_bill_value':     need_bill_value if isinstance(need_bill_value, str) and need_bill_value
                                else 'ปริ้นใบเสร็จ',
        'need_bill_credit_value': need_bill_credit_value
                                if isinstance(need_bill_credit_value, str) and need_bill_credit_value
                                else 'ปริ้นใบกำกับ (เครดิต)',
    }


def _resolve_documents_to_print(need_bill: str, cfg: dict) -> list[tuple[int, str]]:
    """Maps a matched need_bill value to the ordered list of (report_id, label) to
    download and print. Empty list means need_bill matched neither known value —
    caller logs and skips, unchanged from before this function existed."""
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

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
python -m pytest test_invoice_posting.py -v
```
Expected: all 6 tests pass (2 pre-existing + 4 new).

- [ ] **Step 5: Syntax-check the whole file**

Run:
```bash
python -m py_compile "odoo_counter_app.py"
```
Expected: no output, exit code 0.

- [ ] **Step 6: Commit**

```bash
git add odoo_counter_app.py test_invoice_posting.py
git commit -m "feat: add _resolve_documents_to_print + credit-bill config keys

New invoice_cr_report_id (default 1200) and invoice_need_bill_credit_value
(default \"ปริ้นใบกำกับ (เครดิต)\") config keys, plus a pure helper mapping a
matched need_bill value to the ordered list of (report_id, label) to
print. Not yet called from InvoicePrintWorker — that's the next commit."
```

---

### Task 2: Wire the multi-document print loop into `InvoicePrintWorker.run()`

**Files:**
- Modify: `odoo_counter_app.py:584-620` (`InvoicePrintWorker.run` — the `need_bill` gate and the download/print block).
- Test: none automated (Qt + live Odoo I/O) — Step 3 is manual verification against the currently-configured Odoo tenant.

**Interfaces:**
- Consumes: `_resolve_documents_to_print(need_bill, cfg)` and `cfg['cr_report_id']`/`cfg['need_bill_credit_value']` from Task 1.
- Produces: the actual feature. No later task depends on anything new here.

- [ ] **Step 1: Replace the gate check and the download/print block**

Find this exact block:

```python
            need_bill_field = orders[0].get(cfg['need_bill_field'])
            need_bill = need_bill_field[1] if isinstance(need_bill_field, (list, tuple)) else (need_bill_field or '')
            if (need_bill or '').strip() != cfg['need_bill_value']:
                print(f"[Invoice] {self.picking_name}: need-bill flag not set, skip", flush=True)
                return

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

            invoices = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'account.move', 'search_read',
                [[['id', 'in', invoice_ids], ['move_type', '=', 'out_invoice'], ['state', '=', 'posted']]],
                {'fields': ['name'], 'limit': 1, 'order': 'id desc'}
            )
            if not invoices:
                self.print_status.emit('warn', f'{self.picking_name}: ไม่มีใบกำกับภาษีที่ post แล้ว')
                return
            invoice_name = invoices[0]['name']

            self.print_status.emit('checking', f'กำลังดึงใบเสร็จ {invoice_name}...')
            path = _download_invoice_pdf(models, uid, invoices[0]['id'], invoice_name, cfg['report_id'])
            if not path:
                self.print_status.emit('warn', f'ดึงใบเสร็จ {invoice_name} ไม่สำเร็จ')
                return

            _print_pdf_via_sumatra(cfg['sumatra_path'], printer, path)
            self.print_status.emit('ok', f'พิมพ์ใบเสร็จ {invoice_name} แล้ว')
            print(f"[Invoice] {self.picking_name}: printed {invoice_name}", flush=True)
```

Replace it with:

```python
            need_bill_field = orders[0].get(cfg['need_bill_field'])
            need_bill = need_bill_field[1] if isinstance(need_bill_field, (list, tuple)) else (need_bill_field or '')
            documents = _resolve_documents_to_print(need_bill, cfg)
            if not documents:
                print(f"[Invoice] {self.picking_name}: need-bill flag not set, skip", flush=True)
                return

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

            invoices = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                'account.move', 'search_read',
                [[['id', 'in', invoice_ids], ['move_type', '=', 'out_invoice'], ['state', '=', 'posted']]],
                {'fields': ['name'], 'limit': 1, 'order': 'id desc'}
            )
            if not invoices:
                self.print_status.emit('warn', f'{self.picking_name}: ไม่มีใบกำกับภาษีที่ post แล้ว')
                return
            invoice_name = invoices[0]['name']

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

- [ ] **Step 2: Syntax-check the file**

```bash
python -m py_compile "odoo_counter_app.py"
```
Expected: no output, exit code 0.

- [ ] **Step 3: Verify live, without needing the camera**

`InvoicePrintWorker` only needs `(sale_order_id, picking_name)` — it doesn't touch the camera or barcode listener, so it can be exercised directly, the same way Task 4 of `2026-08-03-production-auto-invoice-creation.md` verified the auto-create step.

Prerequisites on the machine running this:
- `invoice_printer_name` in config must be set to a printer present in `QPrinterInfo.availablePrinterNames()` (e.g. `_save_invoice_printer('Microsoft Print to PDF')` if nothing is configured yet — it "prints" to a PDF file, not paper, so it's safe to use for this check).
- Two real sale orders in the currently-configured Odoo tenant: one with `need_bill == "ปริ้นใบเสร็จ"` and a posted invoice (or `invoice_auto_create_enabled` on and zero invoices), one with `need_bill == "ปริ้นใบกำกับ (เครดิต)"` likewise. First confirm the field's actual type/values so the right filter is used:
  ```bash
  python "C:/Users/copter/.claude/skills/odoo-read/scripts/odoo_read.py" fields sale.order --match need_bill
  ```
  Then locate qualifying orders (adjust the filter based on the field type reported above — `=` for a Selection field, `~` ilike-on-the-related-record's name if it turns out to be a many2one):
  ```bash
  python "C:/Users/copter/.claude/skills/odoo-read/scripts/odoo_read.py" search sale.order \
      --fields id,name,x_studio_need_bill,invoice_ids --where "x_studio_need_bill~เครดิต" --limit 5
  python "C:/Users/copter/.claude/skills/odoo-read/scripts/odoo_read.py" search sale.order \
      --fields id,name,x_studio_need_bill,invoice_ids --where "x_studio_need_bill~ใบเสร็จ" --limit 5
  ```

Cash case:
```bash
python - <<'PYEOF'
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from odoo_counter_app import InvoicePrintWorker

SALE_ORDER_ID = 0  # <-- replace with a real id, need_bill == "ปริ้นใบเสร็จ"

w = InvoicePrintWorker(SALE_ORDER_ID, 'VERIFY-TASK2-CASH')
messages = []
w.print_status.connect(lambda level, msg: messages.append((level, msg)))
w.run()
for m in messages:
    print(m)
PYEOF
```
Expected: ends in `('ok', 'พิมพ์ใบเสร็จ {name} แล้ว')` — **no** `(1204)` suffix, byte-identical to today's message. Confirm exactly one PDF was downloaded to `invoices/` and one page printed.

Credit case:
```bash
python - <<'PYEOF'
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from odoo_counter_app import InvoicePrintWorker

SALE_ORDER_ID = 0  # <-- replace with a real id, need_bill == "ปริ้นใบกำกับ (เครดิต)"

w = InvoicePrintWorker(SALE_ORDER_ID, 'VERIFY-TASK2-CREDIT')
messages = []
w.print_status.connect(lambda level, msg: messages.append((level, msg)))
w.run()
for m in messages:
    print(m)
PYEOF
```
Expected: two `'checking'` messages (one for `1204`, one for `Cr.(1200)`), ending in `('ok', 'พิมพ์ใบเสร็จ {name} แล้ว (1204 + Cr.(1200))')`. Confirm in `invoices/` that both PDFs were downloaded and both pages printed, receipt first.

- [ ] **Step 4: Commit**

```bash
git add odoo_counter_app.py
git commit -m "feat: print the Cr. document alongside the receipt for credit bills

InvoicePrintWorker now resolves need_bill against both the cash and
credit values via _resolve_documents_to_print, looping over the
resulting document list instead of downloading/printing a single
hardcoded report. Cash orders are unaffected; credit orders now print
1204 (receipt) then 1200 (Cr.) in one pass, warning with a printed-N/M
count if either download/print step fails."
```

---

### Task 3: Update `PROJECT_CONTEXT.md`

**Files:**
- Modify: `PROJECT_CONTEXT.md` (`InvoicePrintWorker` (KAN-47) section, current lines 447-459).
- Test: none — documentation only.

**Interfaces:** none — this task produces docs, not code.

- [ ] **Step 1: Update the logic list and config-keys line**

Find this exact block:

```markdown
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

Replace it with:

```markdown
1. เช็ก `invoice_printer_name` จาก `_load_invoice_config()` — ถ้าไม่ตั้งค่าไว้ emit warning แล้ว skip ทันที (ไม่มี default-printer fallback)
2. เช็กว่า printer นั้นยังอยู่ใน `QPrinterInfo.availablePrinterNames()` หรือไม่ (KAN-50) — ถ้าตั้งค่าไว้แต่เครื่องพิมพ์ถูกลบ/เปลี่ยนชื่อไปแล้ว emit warning คนละข้อความจาก "ยังไม่ได้ตั้งค่า" แล้ว skip ทันที เช่นกัน (**ไม่มี fallback ไปเครื่องพิมพ์อื่น**)
3. อ่าน `sale.order` เอาฟิลด์ `x_studio_need_bill` (unwrap many2one shape) + `invoice_ids` แล้วส่งเข้า `_resolve_documents_to_print(need_bill, cfg)` เพื่อ resolve เป็นลิสต์ `(report_id, label)` ที่ต้องพิมพ์: ตรงกับ `invoice_need_bill_value` (default `"ปริ้นใบเสร็จ"`) ได้ลิสต์ 1 รายการ (`1204`); ตรงกับ `invoice_need_bill_credit_value` (default `"ปริ้นใบกำกับ (เครดิต)"`) ได้ลิสต์ 2 รายการตามลำดับ (`1204` แล้วต่อด้วย `1200`/Cr.); ไม่ตรงทั้งคู่ได้ลิสต์ว่าง → log เฉย ๆ ไม่มี toast แล้ว return
4. ถ้า `invoice_ids` ว่างและ `invoice_auto_create_enabled` (default `True`) เปิดอยู่ — สร้าง+post invoice ให้อัตโนมัติผ่าน `_create_and_post_invoice()` (wizard `sale.advance.payment.inv`, พอร์ตมาจาก `test_odoo_counter_app.py`/KAN-71) ก่อนไปต่อข้อ 5 ด้านล่าง (ทำงานเหมือนกันไม่ว่า need_bill จะเป็นค่าเงินสดหรือเครดิต) สร้างตอนสแกน barcode ทันที ไม่รอ picking เป็น `done` — ถ้าปิด kill switch นี้ไว้ หรือสร้าง/post ไม่สำเร็จ ก็ emit warning แล้ว skip เหมือนพฤติกรรมเดิม (posted invoice legally final ใน Odoo แล้ว แก้ทีหลังได้แค่ credit note — ดู [[docs/adr/0003-auto-created-invoices-posted-immediately.md]] และ [[docs/adr/0004-auto-created-invoices-extended-to-production.md]])
5. resolve invoice ที่ post แล้วผ่าน `invoice_ids → account.move (move_type=out_invoice, state=posted)` — ไม่มี text-search ข้าม field
6. วนพิมพ์ทีละฉบับตามลิสต์จากข้อ 3: ดาวน์โหลด PDF ผ่าน `_download_invoice_pdf()` (web-session login + `/report/pdf/<report_name>/<invoice_id>`, พอร์ตมาจาก `test_odoo_counter_app.py`) แล้วพิมพ์เงียบผ่าน `_print_pdf_via_sumatra(sumatra_path, printer, pdf_path)` — helper กลาง (KAN-50) ที่ห่อ `subprocess.run([sumatra_path, '-print-to', printer, '-silent', pdf_path], check=True, timeout=30)` ตัวเดียวกันกับที่ปุ่ม "พิมพ์ทดสอบ" ใน settings dialog เรียกใช้; ถ้าฉบับใดฉบับหนึ่งดาวน์โหลด/พิมพ์ไม่สำเร็จ หยุดทันทีและแจ้ง warn ระบุจำนวนที่พิมพ์ไปแล้ว (เช่น `"พิมพ์ไปแล้ว 1/2 ฉบับ — ดึง Cr.(1200) ไม่สำเร็จ"`) — ไม่ retry เพราะฉบับที่พิมพ์ไปแล้วออกจากเครื่องพิมพ์จริงแล้ว เรียกคืนไม่ได้

Signal: `print_status(level, message)` โดย `level` เป็น `'ok'|'checking'|'warn'` — `MainWindow._on_invoice_print_status` เอาไปแสดงใน `lbl_status` เดียวกับ barcode/camera/Odoo status (สีเขียว/เทา/แดงอ่อน)

Config keys (อ่านผ่าน `_load_invoice_config()` จาก `%LOCALAPPDATA%\odoo-counter\config.json`): `invoice_printer_name` (default `""` — ตั้งใจไม่มี fallback), `invoice_auto_print_enabled` (default `True`, KAN-125), `invoice_auto_create_enabled` (default `True`, kill switch แยกต่างหากสำหรับการสร้าง invoice อัตโนมัติ — ปิดได้โดยไม่กระทบการพิมพ์ invoice ที่มีอยู่แล้ว), `invoice_report_id` (default `1204`, ต้องยืนยันกับ production ก่อนใช้จริง), `invoice_cr_report_id` (default `1200`, รายงาน Cr. สำหรับลูกค้าเครดิต — ยืนยันแล้วว่าตรงกับ `ir.actions.report` id `1200` บน production ผูกกับ `account.move` เหมือน `invoice_report_id`), `invoice_sumatra_path`, `invoice_need_bill_field`, `invoice_need_bill_value`, `invoice_need_bill_credit_value` (default `"ปริ้นใบกำกับ (เครดิต)"`, ค่า selection ที่สองของฟิลด์เดียวกับ `invoice_need_bill_value`). Settings UI มีแล้ว (T4/KAN-50) — ตั้งค่า printer และ toggle ทั้งสองผ่านหน้าตั้งค่าเฟือง (`CropSettingsDialog`) แทนการแก้ไฟล์ JSON เอง; บันทึกผ่าน `_save_invoice_printer()` / `_save_invoice_auto_print()` / `_save_invoice_auto_create()` (merge-based เหมือน `_save_settings()`) — `invoice_cr_report_id`/`invoice_need_bill_credit_value` เป็น JSON-only เหมือน `invoice_report_id`, ไม่มีช่องตั้งค่าใน UI.
```

- [ ] **Step 2: Commit**

```bash
git add PROJECT_CONTEXT.md
git commit -m "docs: document the credit-bill Cr. document print loop

Updates PROJECT_CONTEXT.md's InvoicePrintWorker section: the need_bill
gate now resolves a list of documents to print (via
_resolve_documents_to_print), the two new config keys
(invoice_cr_report_id, invoice_need_bill_credit_value), and the
partial-failure warning behavior."
```

---

## Self-Review Notes

- **Spec coverage:** Goal (print both 1204 and 1200 for credit orders, in order, cash path unchanged) → Task 2. New pure helper + its 4 test cases from the spec's Testing section → Task 1. Config keys (`invoice_cr_report_id` default `1200`, `invoice_need_bill_credit_value` default `"ปริ้นใบกำกับ (เครดิต)"`) → Task 1. Error-handling table (both succeed / 1204 succeeds+1200 fails / 1204 itself fails) → Task 2's code + Step 3's two verification scripts. Non-goals (no copy variants, no PDF merging, no retry, no settings UI, no auto-create change, no generalized N-value config) → captured in Global Constraints and untouched by every task's file list. Docs section → Task 3.
- **Placeholder scan:** no TBD/TODO. `SALE_ORDER_ID = 0` placeholders in Task 2 Step 3 are explicitly flagged as "replace with a real id" for values that can only be known by querying the live tenant at verification time, with the exact `odoo-read` commands to find them — not a specification gap.
- **Type consistency:** `_resolve_documents_to_print(need_bill: str, cfg: dict) -> list[tuple[int, str]]` — same signature and same dict key names (`need_bill_value`, `need_bill_credit_value`, `report_id`, `cr_report_id`) at its definition (Task 1) and its call site (Task 2's edit to `InvoicePrintWorker.run()`). `_load_invoice_config()`'s new keys (`cr_report_id`, `need_bill_credit_value`) match what `_resolve_documents_to_print` reads from `cfg` in both Task 1 (definition) and Task 3 (docs). The `'ok'` message format (`"พิมพ์ใบเสร็จ {invoice_name} แล้ว{suffix}"`) and the `'warn'` partial-failure format are identical between Task 2's code and Task 3's docs update.
