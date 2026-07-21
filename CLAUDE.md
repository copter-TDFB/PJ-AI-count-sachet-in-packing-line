# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read This First

`PROJECT_CONTEXT.md` is the authoritative onboarding document (written in Thai, ~1200 lines). It covers the full app flow, every worker class, Odoo logic, camera/model logic, build/release steps, and known caveats in far more detail than this file. **Read the relevant section of `PROJECT_CONTEXT.md` before editing any code.** Keep it updated when behavior changes — it is the project's source of truth, and `AGENTS.md` directs all agents to it.

Architecture decisions are recorded in `docs/adr/` (e.g. ADR-0001 explains why the Lazada print page is left to native printing).

## What This Is

A Windows desktop app for a packing line: a camera + YOLO OBB (oriented bounding box) model counts 3g product sachets and verifies the count against the demand on an Odoo `stock.picking` (Pack order), looked up by scanned barcode. Built with PyQt6, packaged with PyInstaller, and self-updates from GitHub Releases.

## Commands

```powershell
# Run the main app from source (needs deps + model .pt in project root)
python odoo_counter_app.py

# Run the batch model evaluator (scores a model against a labeled dataset, exports CSV)
python batch_eval_app.py

# Build exe + assemble dist_release/ (launcher.exe + app/)
.\build.ps1 <version>          # e.g. .\build.ps1 1.2 — defaults to 0.0.0 if omitted
.\dist_release\launcher.exe    # test the built artifact (run launcher, NOT app/odoo_counter.exe)

# Build, zip, and publish a GitHub Release (requires `gh auth login` first)
.\release.ps1 1.2.0 "release notes"

# Ship a userscript fix: bump @version + commit + rebase + push (file-scoped)
.\push-userscript.ps1          # auto-bumps last digit (2.9 -> 2.10)
.\push-userscript.ps1 3.0      # or set the version explicitly
```

There is no test suite, linter, or CI. Verification is manual: run from source, run a batch eval on a small dataset, then test the built `launcher.exe`. If you cannot run the app (needs camera/Odoo/internet/credentials), say so explicitly rather than claiming it works.

Key dependencies (no requirements.txt — installed ad hoc): `PyQt6`, `opencv-python` (`cv2`), `numpy`, `ultralytics`, `openvino`, `pynput`, `websockets`, `truststore`, `certifi`, `requests`, `PyInstaller`.

## Architecture (the parts that span files)

The system has **four cooperating pieces**, not just one app:

1. **`launcher.py`** — a tkinter shell that checks GitHub Releases, downloads the newest `.zip`, replaces the `app/` folder, and launches `app/odoo_counter.exe`. Users run the launcher, never the inner exe. The launcher owns auto-update; SSL uses truststore → certifi → default fallback (matters because exes built on a dev machine often lack the user's CA store).

2. **`odoo_counter_app.py`** — the main PyQt6 app. UI thread + several `QThread`/daemon workers communicating via Qt signals:
   - `MainWindow` (barcode scan home) → `CounterPanel` (counting popup)
   - `CameraWorker` (loads model, opens camera, runs YOLO inference in an inner daemon thread)
   - `BarcodeWorker` (Odoo lookup: picking → moves → lot/expiration)
   - `OdooSaveWorker` (posts a note back to Odoo, fire-and-forget after the popup hides)
   - `OdooStatusWorker` (pings Odoo every 30s), `OdooConn` (cached XML-RPC connection)
   - `GlobalBarcodeListener` (global keyboard capture via VK codes to bypass IME / Thai layout)
   - `BarcodeBridgeWorker` (WebSocket server on port 9999 broadcasting the picking `origin` to a browser userscript)

3. **`batch_eval_app.py`** — a standalone PyQt6 tool to evaluate a model against a YOLO-format dataset and export per-class accuracy/MAE to CSV. Shares the OpenVINO/.pt loading pattern with the main app.

4. **`combined-auto-print.user.js`** — a Tampermonkey userscript (Shopee/TikTok/Odoo/Lazada) that connects to the bridge's `ws://localhost:9999`, receives the order `origin` string, and auto-prints shipping labels. Self-updates via `@updateURL`/`@downloadURL` pointing at `main` on GitHub; bump `@version` when changing it.

### Cross-cutting behaviors worth knowing before editing

- **Inference is gated to save CPU.** `CameraWorker` runs YOLO only while a counting popup is open (`_inference_enabled`); frames aren't even queued otherwise. Scanning a valid barcode enables it; closing the popup disables it.
- **Counting is crop-filtered.** The model runs on the full preprocessed frame, but only detections whose OBB center falls inside the normalized crop rect are counted. Uploaded images skip the crop (whole image counted).
- **Save is optimistic/async.** On an exact count: play sound → snapshot → show success toast → auto-hide popup, and only then (in `hideEvent`) post the note to Odoo. A success toast does **not** mean the Odoo post succeeded — errors only print to stdout. Do not move `_save_to_odoo()` back into the synchronous pre-hide flow.
- **Config precedence:** `crop_config.json` (gitignored, per-machine) overrides `DEFAULT_CONF`/crop defaults in source. A machine that saved settings won't pick up a new source default until the file is edited or re-saved via the gear dialog.
- **Model loading prefers OpenVINO.** Loads `<model>_openvino_model/` if present (faster startup), falls back to the `.pt`. Current model is `ai_3g_v12.pt` / `ai_3g_v12_openvino_model/`.

## Editing Guardrails

- **Odoo orders now use two formats:** `S\d{4,6}` (legacy, e.g. `S00123`) and `MZS-\d+` (new, e.g. `MZS-240278`) — both route to `runOdoo`. If adding a third format, update `detectPlatform` in `combined-auto-print.user.js` and bump `@version`.
- **Adding a product or changing the model version touches multiple files in lockstep.** PROJECT_CONTEXT.md has explicit checklists ("Changing Model Version Checklist", "Adding New Product Checklist") — follow them. Product matching is keyword-based across `BarcodeWorker`'s Odoo search domain, `_KEYWORD_ODOO_NAME`, `_OBB_COLORS`, and `_extract_keyword()`; the YOLO class names must contain the matching keyword too.
- **Don't change the release zip structure.** The launcher expects a root `app/` folder; `release.ps1` zips with `tar -caf <zip> -C dist_release app`. The launcher grabs the *first* `.zip` asset in the latest release.
- **`version.txt` must be UTF-8 without BOM.** `build.ps1` writes it via .NET `WriteAllText` for this reason (PowerShell 5.1 `Out-File -Encoding utf8` adds a BOM that broke launcher version parsing).
- **The browser runs the userscript published on `main`, not your working tree.** When debugging userscript behavior, check `git show HEAD:combined-auto-print.user.js` (and `git log`) for the version users actually run — the working copy can diverge (e.g. a local revert). To ship a fix, bump `@version` *above* the published number (Tampermonkey only auto-updates to a higher version), then push to `main`.
  - `push-userscript.ps1` does this in one step (bump `@version` → commit → fetch → rebase → push, scoped to just the userscript file). Note: this helper is currently untracked in git.
- **Large binaries are everywhere.** `.pt` models (~20–40MB each) and release `.zip`s (~500MB+) sit in the repo root; most are gitignored (`*.pt`, `*.zip`, `*_openvino_model/`). Never `git add -A` blindly or commit these. `snapshots/` is **not** ignored — guard against it.
- Odoo credentials are hardcoded in `odoo_counter_app.py` (`ODOO_URL`/`ODOO_DB`/`ODOO_USER`/`ODOO_PASSWORD`). Never copy the secret into docs or commits. Target is production `https://tdfb.odoo.com` (db `tdfb`).
- Don't `git reset --hard` or revert in-progress user edits without being asked — much working-tree change predates the last commits.
