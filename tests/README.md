# Browser regression checks

Run Node.js, Playwright and Chromium:

```sh
npm ci
npm run build
npm install --prefix /tmp/ifixit-browser-tools playwright@1.65.0
export NODE_PATH=/tmp/ifixit-browser-tools/node_modules
export CHROMIUM_PATH=/usr/bin/chromium
node tests/browser.cjs
node tests/rubric.cjs
node tests/chart.cjs
node tests/data.cjs
node tests/france.cjs
node tests/responsive.cjs
node tests/images.cjs
```

Tests route repository assets beneath a subdirectory URL, as GitHub Pages does.
No test writes to production. Synthetic scenarios are independent of changing
live device counts; data checks also validate the actual committed snapshot.

- `browser.cjs`: English UI, search/filter data, saved page size, device details,
  comparisons, original-project credits and repository link.
- `rubric.cjs`: every published iFixit version, actual revision-note differences,
  a simulated future criterion, and dynamically loaded French workbook criteria.
- `chart.cjs`: score zero, count labels, score-filter cancellation and independent
  search/manufacturer state.
- `data.cjs`: unique device identities, valid values/URLs, image assets, CSV field
  alignment, and custom scrollbar colours with a stable content width.
- `france.cjs`: source snapshot consistency, matched/missing/conflicting values,
  RAM/storage evidence and the catalogue-versus-calculation-sheet discrepancy.
- `responsive.cjs`: 320-3440px layouts in light and dark appearances, accessible
  navigation, compact actions and no width jump between comparison modes.
- `images.cjs`: correct image identity when a previous request finishes late,
  frameless viewing, zoom controls, reset and Escape.

The daily data workflow runs rubric/data/French checks against the newly generated
candidate files before committing them. The complete suite also runs on frontend
pushes and pull requests.

`navigation.cjs` checks shared filter/comparison/rubric URLs, stable device identity
across source reordering, back/forward and reload with an open dialog, malformed
route parameters, missing/different rubric editions, and current/stale/unknown
import timestamps.
