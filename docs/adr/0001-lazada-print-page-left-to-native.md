# Lazada print page is left to Lazada's native print

The userscript is **excluded** from the Lazada label print page (`https://sellercenter.lazada.co.th/apps/order/print*`) via `@exclude`. That page calls `window.print()` by itself once it has rendered, and that native print produces a complete label. The userscript only needs to run on the seller order-list page to search an order and click "พิมพ์ฉลากจัดส่ง"; it has no job on the print page.

## Considered Options

- **Intercept and re-fire (v2.4–v2.7, rejected).** Run at `document-start`, swallow Lazada's early `window.print()`, then re-fire via `printWhenReady()` after `document.images`/`document.fonts` settle. This was meant to fix a "blank/cut header". In practice it made labels print **cut off**: `printWhenReady()` only waits on top-document `<img>`/fonts, which don't represent the label's actual rendered content, so it fired the print at the wrong moment — earlier/different than Lazada's own well-timed call.
- **Let native print run, script still injected (v2.3, rejected).** Even with the interception removed, merely injecting the script on the print page perturbed the page's "ready" timing and still clipped the label.
- **Exclude the print page entirely (chosen).** No script on `/apps/order/print` → Lazada's native print is untouched → complete label, every time.

## Consequences

- Tampermonkey only auto-updates when `@version` increases. The previously-published version was 2.7, so this change ships as **2.8** to actually reach installed clients.
- If a real "blank header" recurs on native print, the fix belongs in *when we trigger navigation to the print page*, **not** in intercepting `window.print()` on that page. Do not reintroduce a `document-start` print hook for Lazada — it has been tried and it regressed.
