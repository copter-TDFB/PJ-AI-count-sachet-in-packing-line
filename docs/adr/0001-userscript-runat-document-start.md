# Userscript runs at `document-start` to win the Lazada print race

The Lazada label print page (`/apps/order/print?jobId=…`) calls `window.print()`
on its own before the header image (logo/barcode) finishes loading. When the tab
is opened programmatically (script-triggered, so background/throttled), this fires
during load and prints an incomplete page — manual clicks work only because the
foreground tab loads images in time. To fix it we override `window.print` on that
page, swallow the early call, and re-fire via `printWhenReady()` once images+fonts
are loaded. That override only wins the race if it runs **before** Lazada's own
scripts, so `combined-auto-print.user.js` uses `@run-at document-start` (not
`document-idle`).

## Consequences

- **Do not revert to `document-idle`.** It silently reintroduces the double-print
  (one incomplete at ~50% load, one correct at 100%) — hard to diagnose later.
- Safe because no top-level code touches `document.body` synchronously; every DOM
  access is deferred (events, `setTimeout`, `waitFor` polling, promise callbacks),
  so `body` always exists by the time it runs.
- Applies to all four platforms (Shopee/TikTok/Odoo/Lazada); audited — no regression.
