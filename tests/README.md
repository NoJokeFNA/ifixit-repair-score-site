# Browser regression checks

Run with Node.js, Playwright, and Chromium. All application assets are served locally:

```sh
# If Playwright is not already installed, keep test dependencies outside the checkout:
npm install --prefix /tmp/ifixit-browser-tools playwright
NODE_PATH=/tmp/ifixit-browser-tools/node_modules node tests/browser.cjs
NODE_PATH=/tmp/ifixit-browser-tools/node_modules node tests/rubric.cjs
NODE_PATH=/tmp/ifixit-browser-tools/node_modules node tests/responsive.cjs
NODE_PATH=/tmp/ifixit-browser-tools/node_modules node tests/data.cjs
```

`CHROMIUM_PATH` defaults to `/usr/bin/chromium`; `WEB_TEST_OUTPUT` defaults to
`/tmp/ifixit-web-check`. Screenshots are saved there. Tests serve repository files
through Playwright routes, with a fresh browser context per scenario. No web
server or production writes are needed. Chart.js and the font files are served from the committed local assets.

Checks cover cold and slow loads, 1920×1080, 3440×1440, 390×844, 320×740,
768×1024, corrupt cache, blocked storage, quota failures, cached offline data,
brand deep links, retry after an HTTP failure, and unavailable chart CDN. They
assert populated data/filters, real chart creation (when available), no uncaught
browser errors, no page overflow or clipped controls, sorting, search, and reload.

`rubric.cjs` checks the pinned Chart.js version, every rubric version's dialog,
keyboard access, ascending/descending rubric sorting, and the compact layout in
both themes at desktop, tablet, and phone widths. It also injects a future version
with a new criterion to verify that no frontend code change is needed to display
new rubric data. Both scripts run in the browser regression workflow on gh-pages.

`responsive.cjs` covers 3440×1440, 1920×1080, 1280×720, 768×1024,
1024×768, 390×844, and 320×740 in both themes. It checks that both original header
information cards are visible without expanding anything, search remains reachable,
the original column order is preserved, the More options
trigger stays in place, and expandable controls remain accessible. Actual chart
clicks test selection, same-bar cancellation, both clear buttons, URL/reload
persistence, and Reset. Search/manufacturer filters must survive a chart click;
other bars must remain available. No external asset request is allowed.

`data.cjs` validates device field types, score ranges, links, rubric versions and
unique names. It tests Fairphone manufacturer filtering and separate model names,
CSV column/value alignment with one row per device, JSON export, and consistent
scrollbar colors in both themes.
The daily data workflow also runs this check before publishing generated data.

`france.cjs` checks every device's French score against the source snapshot and
its original product URL, score and calculation date. It also tests matched,
conflicting and missing scores, the compact source dialog with the keyboard,
unchanged table row heights, long source lists, Escape/backdrop dismissal, decimal
sorting, comparison, desktop/mobile themes, and unsafe legacy caches while
offline. Its browser fixtures are fixed independently of the real snapshot so
new source listings and corrected scores are allowed. Run it with the same
`NODE_PATH` as the other checks. French and iFixit scores are independent and
are not expected to be equal.

Missing French scores now show a compact `-` button with a descriptive tooltip
and a keyboard/touch-accessible explanation. The France suite distinguishes no
verified source, an unverified variant, conflicting source scores and legacy
cached values. It also checks manufacturer/API model references and that a
French source's Global model is not labelled as the US variant.

Run `node tests/chart.cjs` with the same Playwright environment to check the
compact distribution on mobile and desktop in both themes. Fixed fixtures cover
visible count labels, scored-only tooltip percentages, score zero, filtering,
and empty selections without stale bars.

French score statuses distinguish missing evidence, uncertain variants and conflicting
values. A scalar score is shown only when every matching source agrees; its source
count and agreement are shown in the source dialog. Fixtures cover agreeing iPhone
variants and inconsistent cached match metadata, with no aggregate score for conflicts.
