# Thai-baht wording before invoice posting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-created invoices receive their Sale Order ID and Thai-baht wording before Odoo posts them.

**Architecture:** Keep the existing sale-invoice wizard and post-recovery helper. Move the Sale Order ID write into the draft phase, add one focused helper that resolves and runs the Odoo server action in an `account.move` context, then call the existing post helper. A lightweight recording XML-RPC double drives the real invoice-flow function in regression tests.

**Tech Stack:** Python 3.11, XML-RPC (`execute_kw`), Odoo server actions, pytest.

## Global Constraints

- Use the Odoo action name exactly: `ใส่คำอ่าน ไทยบาท by feng`.
- The required order is: create draft invoice, write `x_studio_sale_order_id`, run the server action, then call `account.move.action_post`.
- Do not post an invoice if writing the Sale Order ID, resolving the action, or running the action fails.
- Preserve the current action-post recovery behavior.
- Do not alter the user’s staged Odoo test-tenant URL/database change.

---

### Task 1: Prove and implement the successful draft-to-post sequence

**Files:**
- Create: `test_invoice_posting.py`
- Modify: `odoo_counter_app.py:277-344`
- Test: `test_invoice_posting.py`

**Interfaces:**
- Consumes: `_create_and_post_invoice(models, uid, sale_order_id)` and `models.execute_kw(...)`.
- Produces: `_apply_thai_baht_wording(models, uid, invoice_ids)`; it resolves the named `ir.actions.server` record and calls its `run` method with active `account.move` IDs.

- [ ] **Step 1: Write the failing regression test**

Create `test_invoice_posting.py` with a recording XML-RPC double and this test. It invokes the real production function and asserts the observable RPC order.

```python
from odoo_counter_app import _create_and_post_invoice


class RecordingModels:
    def __init__(self, action_ids=(501,)):
        self.calls = []
        self.action_ids = list(action_ids)

    def execute_kw(self, _db, _uid, _password, model, method, args, kwargs=None):
        self.calls.append((model, method, args, kwargs or {}))
        if (model, method) == ('sale.advance.payment.inv', 'create'):
            return 900
        if (model, method) == ('sale.advance.payment.inv', 'create_invoices'):
            return None
        if (model, method) == ('sale.order', 'read'):
            return [{'invoice_ids': [101]}]
        if (model, method) == ('ir.actions.server', 'search'):
            return self.action_ids
        if (model, method) in {
            ('account.move', 'write'),
            ('ir.actions.server', 'run'),
            ('account.move', 'action_post'),
        }:
            return True
        raise AssertionError((model, method, args, kwargs))


def _call_index(calls, model, method):
    return next(i for i, call in enumerate(calls) if call[:2] == (model, method))


def test_auto_created_invoice_sets_sale_order_and_thai_baht_wording_before_posting():
    models = RecordingModels()

    assert _create_and_post_invoice(models, 7, 42) == [101]

    write_index = _call_index(models.calls, 'account.move', 'write')
    action_search_index = _call_index(models.calls, 'ir.actions.server', 'search')
    action_run_index = _call_index(models.calls, 'ir.actions.server', 'run')
    post_index = _call_index(models.calls, 'account.move', 'action_post')
    assert write_index < action_search_index < action_run_index < post_index
    assert models.calls[write_index][2] == [[101], {'x_studio_sale_order_id': 42}]
    assert models.calls[action_run_index][3]['context'] == {
        'active_model': 'account.move', 'active_ids': [101], 'active_id': 101,
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; $env:UV_CACHE_DIR='C:\tmp\uv-cache'; uv run --python 3.11 --with pytest --with PyQt6 --with opencv-python --with numpy --with ultralytics --with openvino --with pynput --with websockets --with requests python -m pytest test_invoice_posting.py::test_auto_created_invoice_sets_sale_order_and_thai_baht_wording_before_posting -q
```

Expected: FAIL because the current production flow calls `action_post` before it writes the Sale Order ID and has no server-action invocation.

- [ ] **Step 3: Implement the minimal production flow**

In `odoo_counter_app.py`, declare the exact action name near the invoice helpers and add this helper before `_create_and_post_invoice`:

```python
THAI_BAHT_WORDING_ACTION_NAME = 'ใส่คำอ่าน ไทยบาท by feng'


def _apply_thai_baht_wording(models, uid, invoice_ids: list):
    action_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, 'ir.actions.server', 'search',
        [[
            ['name', '=', THAI_BAHT_WORDING_ACTION_NAME],
            ['model_id.model', '=', 'account.move'],
        ]],
        {'limit': 1},
    )
    models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, 'ir.actions.server', 'run',
        [action_ids],
        {'context': {
            'active_model': 'account.move',
            'active_ids': invoice_ids,
            'active_id': invoice_ids[0],
        }},
    )
```

Update `_create_and_post_invoice` so the calls following `new_invoice_ids` are exactly:

```python
_link_sale_order_on_invoice(models, uid, new_invoice_ids, sale_order_id)
_apply_thai_baht_wording(models, uid, new_invoice_ids)
_post_invoices_with_recovery(models, uid, new_invoice_ids)
```

Make `_link_sale_order_on_invoice` propagate failures instead of swallowing them, because the invoice must remain Draft if the Sale Order ID cannot be written. Update its docstring to state it is a required pre-posting write.

- [ ] **Step 4: Run the regression test to verify it passes**

Run the exact command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit the implementation and successful regression test**

```powershell
git add odoo_counter_app.py test_invoice_posting.py
git commit -m "feat: apply Thai-baht wording before invoice post"
```

### Task 2: Prevent posting if the server action is absent

**Files:**
- Modify: `test_invoice_posting.py`
- Test: `test_invoice_posting.py`

**Interfaces:**
- Consumes: `RecordingModels(action_ids=())` and `_create_and_post_invoice(models, uid, sale_order_id)` from Task 1.
- Produces: Regression evidence that an unavailable Odoo action leaves the invoice unposted.

- [ ] **Step 1: Write the failing regression test**

Append this test to `test_invoice_posting.py`:

```python
def test_missing_thai_baht_action_leaves_auto_created_invoice_unposted(capsys):
    models = RecordingModels(action_ids=())

    assert _create_and_post_invoice(models, 7, 42) is None

    assert not any(
        call[:2] == ('account.move', 'action_post') for call in models.calls
    )
    assert 'ไม่พบ Odoo action' in capsys.readouterr().out
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; $env:UV_CACHE_DIR='C:\tmp\uv-cache'; uv run --python 3.11 --with pytest --with PyQt6 --with opencv-python --with numpy --with ultralytics --with openvino --with pynput --with websockets --with requests python -m pytest test_invoice_posting.py::test_missing_thai_baht_action_leaves_auto_created_invoice_unposted -q
```

Expected: FAIL until `_apply_thai_baht_wording` explicitly raises a clear missing-action error before `action_post`.

- [ ] **Step 3: Implement the minimal error path**

Ensure the empty search result branch in `_apply_thai_baht_wording` is exactly:

```python
if not action_ids:
    raise RuntimeError(f'ไม่พบ Odoo action: {THAI_BAHT_WORDING_ACTION_NAME}')
```

Do not catch this error inside the helper. The existing `try`/`except` in `_create_and_post_invoice` must catch it, print it, and return `None`; because `_post_invoices_with_recovery` comes later, no post RPC is made.

- [ ] **Step 4: Run both invoice-posting tests to verify they pass**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; $env:UV_CACHE_DIR='C:\tmp\uv-cache'; uv run --python 3.11 --with pytest --with PyQt6 --with opencv-python --with numpy --with ultralytics --with openvino --with pynput --with websockets --with requests python -m pytest test_invoice_posting.py -q
```

Expected: 2 passed.

- [ ] **Step 5: Commit the missing-action regression test**

```powershell
git add test_invoice_posting.py
git commit -m "test: prevent invoice post without Thai-baht action"
```

### Task 3: Verify the source remains syntactically valid

**Files:**
- Verify: `odoo_counter_app.py`

**Interfaces:**
- Consumes: The completed invoice helper changes from Tasks 1 and 2.
- Produces: Python compiler evidence that the modified application source parses.

- [ ] **Step 1: Compile the application source**

Run:

```powershell
$env:UV_CACHE_DIR='C:\tmp\uv-cache'; uv run --python 3.11 python -m py_compile odoo_counter_app.py
```

Expected: exit code 0 with no compiler output.

- [ ] **Step 2: Inspect the final targeted diff**

Run:

```powershell
git diff --check HEAD -- odoo_counter_app.py test_invoice_posting.py
git diff HEAD -- odoo_counter_app.py test_invoice_posting.py
```

Expected: no whitespace errors; the only production behavior change is the required pre-post sequence.
