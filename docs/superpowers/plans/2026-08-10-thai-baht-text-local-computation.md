# Thai Baht Text Local Computation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Odoo server-action call in `_apply_thai_baht_wording()` with a local, pure-Python Thai baht-text computation, so the auto-invoice flow (create → link → word → post) completes unattended instead of failing at the wording step for an account that has no `ir.actions.server` access.

**Architecture:** Three new pure functions in `odoo_counter_app.py` (`_thai_six_digit_text`, `_thai_number_to_text`, `_amount_to_thai_baht_text`) implement the standard Thai BAHTTEXT algorithm. `_apply_thai_baht_wording()` is rewired to call `_amount_to_thai_baht_text()` on each invoice's `amount_total` and `write()` the result to `x_studio_thai_bahttext` directly, instead of calling `ir.actions.server.run()`.

**Tech Stack:** Python 3, standard library only (no new dependencies). New test coverage follows this repo's existing standalone-script convention (see `test/test_launcher_install.py`), not pytest. However, `test_invoice_posting.py` — a pre-existing, tracked pytest suite at the repo root that `CLAUDE.md` doesn't mention but that does exist and does import directly from `odoo_counter_app.py` — already covers `_apply_thai_baht_wording()` against the *old* action-based implementation and must be updated (pytest 9.0.3 is installed) so it doesn't break.

## Global Constraints

- No change to `_create_and_post_invoice()`'s call order or error handling — `_apply_thai_baht_wording()` keeps its exact name, signature, and call site (odoo_counter_app.py:316).
- No admin permission request to Odoo, and no dual-path (action call + local fallback) — the account cannot run `ir.actions.server` under any lookup method, so the action call is removed entirely, not guarded.
- No permanent regression test comparing against live Odoo data — the live-data comparison (Task 4) is a one-time, uncommitted verification step.
- New standalone test files go under `test/`, following the existing standalone-script pattern: `importlib.util.spec_from_file_location` to load the module under test, a `check(label, ok, detail)` helper printing `[PASS]`/`[FAIL]`, and a `main()` that returns an exit code via `sys.exit(main())`. Do not introduce pytest for *new* test files (Task 1's test file). This does not apply to Task 3, which updates the pre-existing pytest file in place — leave it as pytest, matching its own existing convention, not the standalone-script one.
- All new Thai-language strings/comments in the added code should read naturally alongside the existing Thai comments already in `odoo_counter_app.py`.
- Do not relocate `test_invoice_posting.py` into `test/` as part of this work — that's a pre-existing convention violation unrelated to this change; out of scope.

---

### Task 1: Implement Thai baht-text pure functions with tests

**Files:**
- Modify: `odoo_counter_app.py:295` (replace the now-unused `THAI_BAHT_WORDING_ACTION_ID = 956` constant with three new functions)
- Test: `test/test_thai_baht_text.py` (new)

**Interfaces:**
- Produces: `_amount_to_thai_baht_text(amount: float) -> str`, defined at module level in `odoo_counter_app.py`. Task 2 calls this function from within `_apply_thai_baht_wording()` in the same module (no import needed — same file). Internal helpers `_thai_number_to_text(n: int) -> str` and `_thai_six_digit_text(n: int) -> str` are implementation details of `_amount_to_thai_baht_text` and are not called directly by Task 2, but the test in this task exercises `_amount_to_thai_baht_text` end-to-end (it does not need to call the internal helpers separately).

- [ ] **Step 1: Write the failing test**

Create `test/test_thai_baht_text.py`:

```python
"""ทดสอบฟังก์ชันแปลงจำนวนเงิน -> คำอ่านภาษาไทย (Thai baht-text) แบบ offline

ไม่แตะ Odoo/เน็ตเลย เคสจำนวนเต็มบาทเป็นค่าจริงที่ดึงมาจาก production
(account.move.x_studio_thai_bahttext ที่มีอยู่แล้ว เข้าโดย action เดิมด้วย account ที่มีสิทธิ์)
ตอนออกแบบฟีเจอร์นี้ — ดู
docs/superpowers/specs/2026-08-10-thai-baht-text-local-computation-design.md
เคสสตางค์/หลักล้านเป็นกฎมาตรฐานของ BAHTTEXT ที่ไม่มีตัวอย่างจริงให้เทียบ แต่ต้องถูกต้องตามหลักเกณฑ์

รัน: python test\\test_thai_baht_text.py
"""
import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_app():
    spec = importlib.util.spec_from_file_location('odoo_counter_app_under_test',
                                                    PROJECT_ROOT / 'odoo_counter_app.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check(label: str, ok: bool, detail: str = '') -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ''))
    return ok


# (amount, expected_text)
CASES = [
    # ค่าจริงจาก production (มาจาก action เดิม ผ่าน account ที่มีสิทธิ์)
    (625, 'หกร้อยยี่สิบห้าบาทถ้วน'),
    (21465, 'สองหมื่นหนึ่งพันสี่ร้อยหกสิบห้าบาทถ้วน'),
    (10518, 'หนึ่งหมื่นห้าร้อยสิบแปดบาทถ้วน'),
    (7380, 'เจ็ดพันสามร้อยแปดสิบบาทถ้วน'),
    (608, 'หกร้อยแปดบาทถ้วน'),
    (505, 'ห้าร้อยห้าบาทถ้วน'),
    (500, 'ห้าร้อยบาทถ้วน'),
    # เคสกฎพิเศษของ BAHTTEXT ที่ไม่มีตัวอย่างจริงในข้อมูล production
    (0, 'ศูนย์บาทถ้วน'),
    (1, 'หนึ่งบาทถ้วน'),
    (11, 'สิบเอ็ดบาทถ้วน'),
    (21, 'ยี่สิบเอ็ดบาทถ้วน'),
    (3690.50, 'สามพันหกร้อยเก้าสิบบาทห้าสิบสตางค์'),
    (0.01, 'ศูนย์บาทหนึ่งสตางค์'),
    (1_000_000, 'หนึ่งล้านบาทถ้วน'),
    (11_000_000, 'สิบเอ็ดล้านบาทถ้วน'),
]


def test_amount_to_thai_baht_text(mod) -> bool:
    print('แปลงจำนวนเงิน -> คำอ่านภาษาไทย')
    ok = True
    for amount, expected in CASES:
        actual = mod._amount_to_thai_baht_text(amount)
        ok &= check(f'{amount} -> {expected!r}', actual == expected, f'ได้ {actual!r}')
    return bool(ok)


def main() -> int:
    mod = load_app()
    results = [test_amount_to_thai_baht_text(mod)]
    print()
    if all(results):
        print('ผ่านทั้งหมด')
        return 0
    print('มีเคสที่ไม่ผ่าน')
    return 1


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test\test_thai_baht_text.py`
Expected: `AttributeError: module 'odoo_counter_app_under_test' has no attribute '_amount_to_thai_baht_text'` (the function doesn't exist yet).

- [ ] **Step 3: Implement the functions**

In `odoo_counter_app.py`, replace line 295 (`THAI_BAHT_WORDING_ACTION_ID = 956`) with:

```python
_THAI_DIGITS = ('ศูนย์', 'หนึ่ง', 'สอง', 'สาม', 'สี่', 'ห้า', 'หก', 'เจ็ด', 'แปด', 'เก้า')
_THAI_PLACES = ('', 'สิบ', 'ร้อย', 'พัน', 'หมื่น', 'แสน')


def _thai_six_digit_text(n: int) -> str:
    """Converts 0-999999 to Thai words. Caller handles grouping above 999999 with 'ล้าน'."""
    if n == 0:
        return ''
    digits = str(n)
    length = len(digits)
    parts = []
    for i, ch in enumerate(digits):
        d = int(ch)
        if d == 0:
            continue
        place = length - i - 1
        if place == 0:
            parts.append('เอ็ด' if (d == 1 and length > 1) else _THAI_DIGITS[d])
        elif place == 1:
            if d == 1:
                parts.append('สิบ')
            elif d == 2:
                parts.append('ยี่สิบ')
            else:
                parts.append(_THAI_DIGITS[d] + 'สิบ')
        else:
            parts.append(_THAI_DIGITS[d] + _THAI_PLACES[place])
    return ''.join(parts)


def _thai_number_to_text(n: int) -> str:
    """Converts a non-negative integer to Thai words, grouping every 6 digits with 'ล้าน'."""
    if n == 0:
        return _THAI_DIGITS[0]
    groups = []
    while n > 0:
        groups.append(n % 1_000_000)
        n //= 1_000_000
    groups.reverse()
    last_index = len(groups) - 1
    parts = []
    for i, group in enumerate(groups):
        if group == 0:
            continue
        parts.append(_thai_six_digit_text(group))
        if i != last_index:
            parts.append('ล้าน')
    return ''.join(parts)


def _amount_to_thai_baht_text(amount: float) -> str:
    """Converts a money amount to Thai baht-text, e.g. 3690.0 -> 'สามพันหกร้อยเก้าสิบบาทถ้วน'."""
    total_satang = round(amount * 100)
    baht, satang = divmod(total_satang, 100)
    baht_text = _thai_number_to_text(baht) + 'บาท'
    if satang == 0:
        return baht_text + 'ถ้วน'
    return baht_text + _thai_number_to_text(satang) + 'สตางค์'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python test\test_thai_baht_text.py`
Expected: every case prints `[PASS]`, final line `ผ่านทั้งหมด`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add odoo_counter_app.py test/test_thai_baht_text.py
git commit -m "feat: add local Thai baht-text conversion

Pure-function implementation of the standard BAHTTEXT algorithm, to
replace the ir.actions.server call in the next task. Verified against
real production x_studio_thai_bahttext values plus standard BAHTTEXT
edge cases (zero, เอ็ด, ยี่สิบ, satang, million-grouping)."
```

---

### Task 2: Rewire `_apply_thai_baht_wording()` to compute locally

**Files:**
- Modify: `odoo_counter_app.py:357-367` (the function body — this line range is for the pre-Task-1 file; after Task 1 inserts new functions before it, locate the function by name, not by line number)

**Interfaces:**
- Consumes: `_amount_to_thai_baht_text(amount: float) -> str` from Task 1 (same module, no import).
- Produces: `_apply_thai_baht_wording(models, uid, invoice_ids: list) -> None` — unchanged name/signature/call site, so `_create_and_post_invoice()` (odoo_counter_app.py:316) requires no edit.

- [ ] **Step 1: Replace the function body**

Find the current implementation:

```python
def _apply_thai_baht_wording(models, uid, invoice_ids: list):
    """Run the Thai-baht wording server action against draft customer invoices."""
    context = {
        'active_model': 'account.move',
        'active_ids': invoice_ids,
        'active_id': invoice_ids[0],
    }
    models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, 'ir.actions.server', 'run',
        [[THAI_BAHT_WORDING_ACTION_ID]], {'context': context}
    )
```

Replace it with:

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

- [ ] **Step 2: Confirm no dangling references to the removed constant**

Run: `grep -n "THAI_BAHT_WORDING_ACTION_ID" odoo_counter_app.py`
Expected: no output (the constant was replaced in Task 1, and nothing else references it).

- [ ] **Step 3: Confirm the file still parses**

Run: `python -c "import ast; ast.parse(open('odoo_counter_app.py', encoding='utf-8').read())"`
Expected: no output, exit code 0 (this checks syntax only — it does not require PyQt6/cv2/ultralytics/etc. to be importable).

- [ ] **Step 4: Re-run Task 1's test as a sanity check**

Run: `python test\test_thai_baht_text.py`
Expected: still `ผ่านทั้งหมด` — this task didn't touch the conversion functions, so this just confirms Task 2's edit didn't break the module load.

- [ ] **Step 5: Commit**

```bash
git add odoo_counter_app.py
git commit -m "fix: stop calling the blocked ir.actions.server action for Thai baht text

operation.engineer@tdfb.co has no execute access to ir.actions.server
in production (Settings-only by Odoo design, confirmed live). The call
was raising inside _create_and_post_invoice(), which left auto-created
invoices stuck in draft, never posted. _apply_thai_baht_wording() now
computes and writes x_studio_thai_bahttext locally instead."
```

---

### Task 3: Update `test_invoice_posting.py` for the new local computation

`test_invoice_posting.py` is a pre-existing, tracked pytest file at the repo root (not under `test/` — leave it there, relocating it is out of scope) that imports directly from `odoo_counter_app.py` and already exercises `_apply_thai_baht_wording()` against the old action-based implementation. Two of its tests assert calls to `ir.actions.server`/`run` with `[[956]]`, which no longer happen after Task 2 — they must be updated or every `pytest test_invoice_posting.py` run will fail starting from this point.

**Files:**
- Modify: `test_invoice_posting.py` (repo root — the whole file, lines 1-60, covering `RecordingModels` and the two Thai-baht tests; the four `test_resolve_documents_to_print_*` tests below them are unrelated and untouched)

**Interfaces:**
- Consumes: `_amount_to_thai_baht_text(amount: float) -> str` from Task 1, `_apply_thai_baht_wording`/`_create_and_post_invoice` from Task 2 (all same module, imported at the top of this test file).

- [ ] **Step 1: Replace `RecordingModels` and the two Thai-baht tests**

Find the current top of the file:

```python
from odoo_counter_app import _create_and_post_invoice, _resolve_documents_to_print


class RecordingModels:
    """Record XML-RPC calls while supplying the standard invoice-wizard responses."""

    def __init__(self, server_action_run_error=None):
        self.calls = []
        self.server_action_run_error = server_action_run_error

    def execute_kw(self, database, uid, password, model, method, args, kwargs=None):
        self.calls.append((model, method, args, kwargs or {}))
        if (model, method) == ('sale.advance.payment.inv', 'create'):
            return 9
        if (model, method) == ('sale.order', 'read'):
            return [{'invoice_ids': [101]}]
        if (model, method) == ('ir.actions.server', 'run') and self.server_action_run_error:
            raise self.server_action_run_error
        return True


def test_auto_created_invoice_sets_sale_order_and_thai_baht_wording_before_posting():
    models = RecordingModels()

    invoice_ids = _create_and_post_invoice(models, uid=7, sale_order_id=42)

    assert invoice_ids == [101]
    calls = models.calls
    write_index = next(
        index for index, call in enumerate(calls)
        if call[:2] == ('account.move', 'write')
    )
    run_index = next(
        index for index, call in enumerate(calls)
        if call[:2] == ('ir.actions.server', 'run')
    )
    post_index = next(
        index for index, call in enumerate(calls)
        if call[:2] == ('account.move', 'action_post')
    )

    assert calls[write_index][2] == [[101], {'x_studio_sale_order_id': 42}]
    assert calls[run_index][3]['context'] == {
        'active_model': 'account.move',
        'active_ids': [101],
        'active_id': 101,
    }
    assert calls[run_index][2] == [[956]]
    assert ('ir.actions.server', 'search') not in [call[:2] for call in calls]
    assert write_index < run_index < post_index


def test_thai_baht_action_failure_leaves_auto_created_invoice_unposted(capsys):
    models = RecordingModels(server_action_run_error=RuntimeError('server action failed'))

    invoice_ids = _create_and_post_invoice(models, 7, 42)

    assert invoice_ids is None
    assert ('account.move', 'action_post') not in [call[:2] for call in models.calls]
    assert 'server action failed' in capsys.readouterr().out
```

Replace it with:

```python
from odoo_counter_app import _amount_to_thai_baht_text, _create_and_post_invoice, _resolve_documents_to_print


class RecordingModels:
    """Record XML-RPC calls while supplying the standard invoice-wizard responses."""

    def __init__(self, thai_baht_write_error=None):
        self.calls = []
        self.thai_baht_write_error = thai_baht_write_error

    def execute_kw(self, database, uid, password, model, method, args, kwargs=None):
        self.calls.append((model, method, args, kwargs or {}))
        if (model, method) == ('sale.advance.payment.inv', 'create'):
            return 9
        if (model, method) == ('sale.order', 'read'):
            return [{'invoice_ids': [101]}]
        if (model, method) == ('account.move', 'read'):
            return [{'id': 101, 'amount_total': 3690.0}]
        if (model, method) == ('account.move', 'write') and 'x_studio_thai_bahttext' in args[1] \
                and self.thai_baht_write_error:
            raise self.thai_baht_write_error
        return True


def test_auto_created_invoice_sets_sale_order_and_thai_baht_wording_before_posting():
    models = RecordingModels()

    invoice_ids = _create_and_post_invoice(models, uid=7, sale_order_id=42)

    assert invoice_ids == [101]
    calls = models.calls
    link_index = next(
        index for index, call in enumerate(calls)
        if call[:2] == ('account.move', 'write') and call[2][1] == {'x_studio_sale_order_id': 42}
    )
    wording_index = next(
        index for index, call in enumerate(calls)
        if call[:2] == ('account.move', 'write') and 'x_studio_thai_bahttext' in call[2][1]
    )
    post_index = next(
        index for index, call in enumerate(calls)
        if call[:2] == ('account.move', 'action_post')
    )

    assert calls[wording_index][2] == [[101], {'x_studio_thai_bahttext': _amount_to_thai_baht_text(3690.0)}]
    assert ('ir.actions.server', 'run') not in [call[:2] for call in calls]
    assert link_index < wording_index < post_index


def test_thai_baht_write_failure_leaves_auto_created_invoice_unposted(capsys):
    models = RecordingModels(thai_baht_write_error=RuntimeError('write failed'))

    invoice_ids = _create_and_post_invoice(models, 7, 42)

    assert invoice_ids is None
    assert ('account.move', 'action_post') not in [call[:2] for call in models.calls]
    assert 'write failed' in capsys.readouterr().out
```

- [ ] **Step 2: Run the updated tests**

Run: `python -m pytest test_invoice_posting.py -q`
Expected: all tests pass (6 total — the 2 updated Thai-baht tests plus the 4 unrelated `test_resolve_documents_to_print_*` tests, untouched).

- [ ] **Step 3: Commit**

```bash
git add test_invoice_posting.py
git commit -m "test: update invoice-posting tests for local Thai baht-text write

The mock previously asserted a call to ir.actions.server/run with the
hardcoded action id 956. Updated to assert the new account.move/write
call with x_studio_thai_bahttext instead, matching odoo_counter_app.py's
new _apply_thai_baht_wording() from the prior commit."
```

---

### Task 4: One-time live validation against production Odoo data

This task has no code deliverable and produces no commit unless it finds a bug. Its deliverable is confidence: proof that `_amount_to_thai_baht_text()` reproduces what Odoo's own (properly-privileged) action has already written for real invoices.

**Files:**
- None committed. Scratch script lives outside the repo (e.g. the session scratchpad directory), or anywhere convenient — do not add it to `test/`, per the explicit one-time-only decision in the spec.

- [ ] **Step 1: Write the comparison script**

Save this as a standalone script (e.g. `verify_against_odoo.py` in your scratch directory, not in the repo):

```python
import importlib.util
import io
import ssl
import sys
import xmlrpc.client
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJECT_ROOT = Path(r"C:\Users\copter\Desktop\PJ\PJ AI count sachet PK")

spec = importlib.util.spec_from_file_location('odoo_counter_app_under_test',
                                                PROJECT_ROOT / 'odoo_counter_app.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ctx = ssl.create_default_context()
common = xmlrpc.client.ServerProxy(f'{mod.ODOO_URL}/xmlrpc/2/common', context=ctx)
uid = common.authenticate(mod.ODOO_DB, mod.ODOO_USER, mod.ODOO_PASSWORD, {})
models = xmlrpc.client.ServerProxy(f'{mod.ODOO_URL}/xmlrpc/2/object', context=ctx)

recs = models.execute_kw(
    mod.ODOO_DB, uid, mod.ODOO_PASSWORD,
    'account.move', 'search_read',
    [[['x_studio_thai_bahttext', '!=', False], ['move_type', '=', 'out_invoice']]],
    {'fields': ['name', 'amount_total', 'x_studio_thai_bahttext'], 'order': 'id desc', 'limit': 50}
)

mismatches = 0
for r in recs:
    computed = mod._amount_to_thai_baht_text(r['amount_total'])
    actual = r['x_studio_thai_bahttext']
    status = 'OK' if computed == actual else 'MISMATCH'
    if status == 'MISMATCH':
        mismatches += 1
    print(f"{status}  {r['name']}  total={r['amount_total']}")
    if status == 'MISMATCH':
        print(f"    computed: {computed}")
        print(f"    actual:   {actual}")

print(f"\n{len(recs)} checked, {mismatches} mismatch(es)")
```

- [ ] **Step 2: Run it**

Run: `python verify_against_odoo.py` (redirect to a file first if your terminal can't render Thai — e.g. `python verify_against_odoo.py > out.txt 2>&1` then read `out.txt`).

Expected: `50 checked, 0 mismatch(es)`.

- [ ] **Step 3a: If 0 mismatches — done**

No further action. Delete the scratch script (it was never part of the repo).

- [ ] **Step 3b: If any mismatches — fix and re-verify**

For each mismatched `(amount_total, actual)` pair:
1. Add it as a new entry to `CASES` in `test/test_thai_baht_text.py` (using the real `actual` string as the expected value).
2. Run `python test\test_thai_baht_text.py` — it will now fail on the new case.
3. Fix `_thai_six_digit_text`, `_thai_number_to_text`, or `_amount_to_thai_baht_text` in `odoo_counter_app.py` so the new case passes without breaking any existing case.
4. Re-run `python test\test_thai_baht_text.py` until `ผ่านทั้งหมด`.
5. Re-run the Step 1 script until `0 mismatch(es)`.
6. Commit the fix:

```bash
git add odoo_counter_app.py test/test_thai_baht_text.py
git commit -m "fix: correct Thai baht-text conversion for <describe the case>

Found via one-time comparison against production x_studio_thai_bahttext
values (docs/superpowers/specs/2026-08-10-thai-baht-text-local-computation-design.md)."
```

---

## Post-plan note

`docs/superpowers/specs/2026-08-03-thai-baht-wording-before-invoice-posting-design.md` (the original spec for the action-based approach) is superseded by `docs/superpowers/specs/2026-08-10-thai-baht-text-local-computation-design.md`, which this plan implements. No action needed on the old file — it stays as historical record.
