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

`@run-at` is a single global directive and cannot be scoped per `@match`, so the
blast radius is contained in code instead: at `document-start` only the Lazada
print-page override runs; everything else (all platforms' reactive logic,
listeners, WebSocket bridge) is deferred to `DOMContentLoaded` via a
`whenDomReady()` gate, reproducing the previous `document-idle` timing exactly.

## Consequences

- **Do not revert to `document-idle`.** It silently reintroduces the double-print
  (one incomplete at ~50% load, one correct at 100%) — hard to diagnose later.
- **Keep the `whenDomReady()` gate.** Removing it would run every platform's logic
  at `document-start` (before `document.body` exists) — unintended scope creep that
  this design deliberately avoids. Only the Lazada print override belongs early.
- Shopee/TikTok/Odoo are unaffected: their code runs at the same point as before.
