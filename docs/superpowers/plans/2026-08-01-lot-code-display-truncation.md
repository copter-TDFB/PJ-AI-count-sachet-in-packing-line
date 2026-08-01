# Lot Code Display Truncation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show only a fixed 4-character batch snippet (characters 10-13) of each lot code in the
counting popup's `Lot:` line, instead of the full raw code from Odoo.

**Architecture:** One-line change inside `CounterPanel._create_product_card`'s existing lot-line
loop in `odoo_counter_app.py` — slice `lot['name']` to `[9:13]` before building the display
string, falling back to the full string if it's shorter than 13 characters. No new functions, no
new signals, no change to data sent back to Odoo.

**Tech Stack:** Python, PyQt6 (existing app — no new dependencies).

## Global Constraints

- This project has **no automated test suite** (per `CLAUDE.md`) — verification is manual, via
  running `test/demo_multi_lot_popup.py` and reading the rendered popup.
- The truncation is **display-only**. `lot['name']` must never be truncated before anything that
  talks to Odoo — confirmed the only consumer of `lot['name']` in the whole file is this one
  display line.
- Truncation rule is a **fixed position**, `name[9:13]` (0-indexed Python slice = characters
  10-13, 1-indexed), applying identically regardless of product/lot prefix (HR, ME, GM, etc.) —
  not derived from a delimiter or supplier code.
- Fallback: if `len(name) < 13`, show the full name unchanged.

---

### Task 1: Truncate lot code in `_create_product_card`, verify via demo, update docs

**Files:**
- Modify: `odoo_counter_app.py:1749-1763` (`CounterPanel._create_product_card`, the lot-line loop)
- Modify: `test/demo_multi_lot_popup.py` (mock lot names + docstring)
- Modify: `PROJECT_CONTEXT.md:870`

**Interfaces:**
- Consumes: `lot['name']` (str), already present on every dict inside a `lots_by_product[pid]`
  list — no new fields, no signature changes anywhere.
- Produces: nothing new is exposed — `lot_lines` (the list already returned inside the dict from
  `_create_product_card`) now contains truncated names instead of full ones. No other task or
  caller depends on the *content* of `lot_lines` beyond displaying it, so this is self-contained.

- [ ] **Step 1: Update the demo script's mock data to realistic long lot codes, plus one short one**

  Open `test/demo_multi_lot_popup.py`. Replace the `'lots_by_product'` block (currently uses short
  8-character names like `'LOT-A123'`, which are all shorter than 13 chars and wouldn't exercise
  truncation at all) with codes long enough to actually show truncation, and add one short one to
  exercise the fallback path:

  ```python
      'lots_by_product': {
          101: [
              {'name': 'HR0008HKW026621326R', 'expiration_date': '2026-09-01 00:00:00', 'qty': 30.0},
              {'name': 'HR0008HKW099921326R', 'expiration_date': '2026-11-15 00:00:00', 'qty': 20.0},
          ],
          102: [
              {'name': 'GM0002XYZ011122333R', 'expiration_date': '2026-10-01 00:00:00', 'qty': 30.0},
              {'name': 'LOT9', 'expiration_date': '', 'qty': 5.0},
          ],
          # 103: ไม่มี key -> การ์ดจะโชว์ "Lot: -"
      },
  ```

  `HR0008HKW026621326R` and `HR0008HKW099921326R` are 19 characters (realistic length, ≥13).
  `GM0002XYZ011122333R` is 19 characters too. `LOT9` is only 4 characters — this is the fallback
  case (shorter than 13 chars, so it should display unchanged, unlike the other three).

  Also update the module docstring's example line (currently
  `- สินค้า A: 2 lot คนละจำนวน คนละวันหมดอายุ -> "Lot: LOT-A123 x30 (EXP ...), LOT-A456 x20 (EXP ...)"`)
  to:

  ```python
    - สินค้า A: 2 lot รหัสยาว ต้องตัดเหลือ 4 ตัว (ตำแหน่ง 10-13)  -> "Lot: 0266: 30 ซอง (EXP ...)"
    - สินค้า B: 1 lot รหัสยาว + 1 lot สั้นกว่า 13 ตัว (fallback)  -> โชว์เต็มไม่ตัด
    - สินค้า C: ไม่มี lot เลย                                    -> "Lot: -"
  ```

- [ ] **Step 2: Run the demo BEFORE the code change to confirm today's (untruncated) baseline**

  Run: `python test/demo_multi_lot_popup.py`

  Expected: popup opens, no exceptions in the terminal. The Houjicha card's `Lot:` line shows the
  **full** long codes (e.g. `Lot: HR0008HKW026621326R: 30 ซอง (EXP 01/09/2026)`), because the
  truncation code hasn't been added yet — this confirms the new mock data loads correctly before
  changing behavior. Close the popup (it exits automatically).

- [ ] **Step 3: Implement the truncation rule**

  Open `odoo_counter_app.py`, find `_create_product_card` (around line 1749). Change:

  ```python
        if lots:
            lot_lines = []
            for lot in lots:
                piece = lot['name']
                qty = lot.get('qty')
  ```

  to:

  ```python
        if lots:
            lot_lines = []
            for lot in lots:
                raw_name = lot['name']
                piece = raw_name[9:13] if len(raw_name) >= 13 else raw_name
                qty = lot.get('qty')
  ```

  Nothing else in the loop body changes — the qty/EXP formatting that follows still appends onto
  `piece` exactly as before.

- [ ] **Step 4: Run the demo AFTER the code change to verify truncation + fallback**

  Run: `python test/demo_multi_lot_popup.py`

  Expected, reading the popup on screen:
  - Houjicha Rich card, line 1: `Lot: 0266: 30 ซอง (EXP 01/09/2026)`
  - Houjicha Rich card, line 2: `0999: 20 ซอง (EXP 15/11/2026)` (indented continuation line)
  - Genmaicha card, line 1: `Lot: 0111: 30 ซอง (EXP 01/10/2026)`
  - Genmaicha card, line 2: `LOT9: 5 ซอง` (full 4-char name shown unchanged — this is the
    fallback path, since `'LOT9'` is only 4 characters, shorter than 13)
  - Classic Blend card: `Lot: -` (unchanged — no lots at all is a separate case from "short lot
    name")

  If the font-auto-shrink logic truncates any line further into a `+N lot` summary because the
  card is too short for your screen, that's the pre-existing `_fit_lot_label` behavior working as
  designed (see `docs/superpowers/specs/2026-08-01-lot-code-display-truncation-design.md`'s
  Non-goals) — not a bug in this task. Close the popup when done (it exits automatically).

- [ ] **Step 5: Update `PROJECT_CONTEXT.md`'s Lot/EXP row description**

  Open `PROJECT_CONTEXT.md`, find line 870:

  ```
    - Lot + EXP row (สีเขียวมิ้นต์) — แสดง lot names dedupe + วันหมดอายุในรูปแบบ `dd/MM/yyyy`; ถ้าไม่มี lot แสดง `Lot: -`
  ```

  Replace with a version that reflects current actual behavior (qty, per-lot line stacking,
  dynamic font, and the new truncation rule all shipped this session but were never documented
  here):

  ```
    - Lot + EXP row (สีเขียวมิ้นต์) — 1 บรรทัดต่อ lot: รหัส lot ตัดเหลือ 4 ตัว (ตำแหน่ง 10-13,
      `name[9:13]`; ถ้าสั้นกว่า 13 ตัวโชว์เต็ม) + จำนวนซอง (`: N ซอง`) + วันหมดอายุ
      (`(EXP dd/MM/yyyy)`); ถ้าไม่มี lot แสดง `Lot: -`. ขนาดฟอนต์ปรับอัตโนมัติ (13px ลงไปจนถึง
      8px floor) ตามจำนวน lot ของการ์ดนั้น ๆ ผ่าน `_fit_lot_label()`/`_fit_cards_to_viewport()` —
      ถ้าล้นแม้ที่ 8px จะตัดเหลือ `+N lot` แทนการล้นการ์ด
  ```

- [ ] **Step 6: Commit**

  ```bash
  git add odoo_counter_app.py test/demo_multi_lot_popup.py PROJECT_CONTEXT.md
  git commit -m "feat: truncate lot code display to 4-char batch snippet"
  ```
