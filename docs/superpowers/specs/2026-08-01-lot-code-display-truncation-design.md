# Lot code display: truncate to a 4-character batch snippet

## Problem

Lot codes pulled from Odoo are long (e.g. `HR0008HKW026621326R`). Combined with the qty/EXP
info already added to the `Lot:` line this session, the full code makes each line read as a
dense, hard-to-parse blob on the packing-line touchscreen. The floor worker only actually cares
about a short internal batch snippet buried in the middle of the code — everything else on either
side is noise to them.

## Goal

Show only that 4-character snippet in the `Lot:` line instead of the full code, e.g.
`HR0008HKW026621326R` → `0266`.

## Non-goals

- No change to what's stored or sent to Odoo — `lot['name']` is already display-only (verified:
  grepped the file, its only use is building the `Lot:` line; `_save_to_odoo`/`OdooSaveWorker`
  post only counts + picking id, never lot names).
- No settings/config UI for the character range — position 10–13 is hardcoded, confirmed to be a
  fixed company-wide convention that applies the same way regardless of product/prefix (HR, ME,
  etc.), not derived from a delimiter or supplier code.
- No change to qty formatting (`N ซอง`), EXP formatting, per-lot line stacking, or the dynamic
  auto-shrink font sizing already shipped this session — only the lot-name portion of each line
  changes.

## Design

### Where

`_create_product_card` in `odoo_counter_app.py`, in the lot-line-building loop (~line 1752),
where `piece = lot['name']` currently starts each line.

### Rule

```python
raw_name = lot['name']
piece = raw_name[9:13] if len(raw_name) >= 13 else raw_name
```

Characters 10–13 (1-indexed), i.e. Python slice `[9:13]` — a fixed position, confirmed against a
second real lot code from a different product prefix, so it is not prefix-specific.

### Fallback

If `len(raw_name) < 13`, show the full code unchanged rather than a truncated/blank fragment.
Confirmed this shouldn't occur in practice (real lot codes are always ≥13 characters), but kept
as a zero-cost defensive guard for a manually-entered `lot_name` (unregistered-lot case) that
happens to be short.

## Testing / verification

No automated test suite (manual only, per `CLAUDE.md`). Verify via
`test/demo_multi_lot_popup.py` — update its mock lot names to realistic ≥13-character codes and
confirm the `Lot:` line shows only the 4-character snippet. Also add one mock lot name shorter
than 13 characters to exercise the fallback path.

## Docs

`PROJECT_CONTEXT.md` line 870 currently describes the Lot/EXP row as "แสดง lot names dedupe +
วันหมดอายุ" without mentioning any truncation — update it to note the 4-character display rule
once this lands.
