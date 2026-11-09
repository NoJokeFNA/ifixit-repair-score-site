# Browser regression checks

Run with Node.js, Playwright, and Chromium. All application assets are served locally:

```sh
# If Playwright is not already installed, keep test dependencies outside the checkout:
npm install --prefix /tmp/ifixit-browser-tools playwright
NODE_PATH=/tmp/ifixit-browser-tools/node_modules node tests/browser.cjs
NODE_PATH=/tmp/ifixit-browser-tools/node_modules node tests/rubric.cjs
NODE_PATH=/tmp/ifixit-browser-tools/node_modules node tests/responsive.cjs
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
1024×768, 390×844, and 320×740 in both themes. It checks that search is on
the first screen, Score and Rubric are initially visible, device names stay fixed
while the table scrolls, and expandable controls remain accessible. Actual chart
clicks test selection, same-bar cancellation, both clear buttons, URL/reload
persistence, and Reset. Search/manufacturer filters must survive a chart click;
other bars must remain available. No external asset request is allowed.
