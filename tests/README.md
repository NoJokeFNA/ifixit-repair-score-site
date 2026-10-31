# Browser regression checks

Run with Node.js, Playwright, Chromium, and a local Chart.js UMD distribution:

```sh
# If Playwright is not already installed, keep test dependencies outside the checkout:
npm install --prefix /tmp/ifixit-browser-tools playwright
curl -fLsS https://cdn.jsdelivr.net/npm/chart.js -o /tmp/ifixit-chart.js
NODE_PATH=/tmp/ifixit-browser-tools/node_modules CHART_JS_PATH=/tmp/ifixit-chart.js node tests/browser.cjs
```

`CHROMIUM_PATH` defaults to `/usr/bin/chromium`; `WEB_TEST_OUTPUT` defaults to
`/tmp/ifixit-web-check`. Screenshots are saved there. Tests serve repository files
through Playwright routes, with a fresh browser context per scenario. No web
server or production writes are needed. Chart.js is served locally; Google Fonts
are blocked so the checks do not rely on external font availability.

Checks cover cold and slow loads, 1920×1080, 3440×1440, 390×844, 320×740,
768×1024, corrupt cache, blocked storage, quota failures, cached offline data,
brand deep links, retry after an HTTP failure, and unavailable chart CDN. They
assert populated data/filters, real chart creation (when available), no uncaught
browser errors, no page overflow or clipped controls, sorting, search, and reload.
