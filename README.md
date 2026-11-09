# iFixit Repair Scores Site

Python 3.13 project that builds a JSON with device repairability information from the iFixit API. A separate gh-pages branch hosts the static website and the generated JSON.

- Data source: iFixit API v2.0
- Backend (master branch): Python only
- Frontend (gh-pages branch): vanilla HTML/JS/CSS
- Deployment: GitHub Pages via Actions

Workflows:
- build-json-to-pages.yml: builds devices_with_scores.json and commits it directly to the gh-pages branch (manual dispatch or daily at 03:00 UTC).
- pages.yml: deploys the gh-pages branch to GitHub Pages when files there change.
- ci.yml: runs Ruff (lint/format) on main.

Local run example:
- python src/fetch_device_data.py --categories "iPhone" "Android Phone" --scores-output devices_with_scores.json

Rubric maintenance:
- The daily build probes version numbers 1.0 through 10.9 (one minor digit), including gaps.
- New criteria are added automatically when the source scoring table uses the existing layout.
- Missing previously published versions or an unrecognized scoring table fail the build and preserve the previous rubric output.
- Python regression tests: `PYTHONPATH=src python -m unittest discover -s tests -v`.
- Before publishing, the daily workflow runs browser checks for every generated version, including its details dialog, sorting, and a simulated future criterion. Changes to iFixit's URL scheme, version numbering, or table layout may require a parser update.

French score matching:
- The French index and iFixit's score use different methods; differences between them are expected and are never treated as conflicts.
- Network variants and iPhone SE generations remain distinct. Only exact normalized identities match; no fuzzy or prefix matching is used.
- Cosmetic/storage variants can share a score only if the matching source entries agree. Conflicts within the French source produce a null score with source evidence, never a majority vote.
- `france_repairability` contains `status` (`matched`, `conflicting`, `not_found`), `score`, and the original source product names, URLs, scores and calculation dates. The scalar `france_repairability_score` remains available for existing consumers.
- Fetches verify the advertised product count and unique product URLs across every page. Timeouts are retried; missing pages, changed markup and invalid scores stop the build before the French output is replaced.
- Intentionally conservative: a source listing without 5G cannot establish a score for a 5G device. Missing matches do not mean the device is unrepairable. Additional aliases require model-specific evidence and regression tests.
- Coordinate rollout with the `gh-pages` frontend containing `tests/france.cjs`; the daily publication workflow requires that check. Keep the Beta label until outstanding source conflicts and model aliases have been reviewed.

## API authentication

The current [official API documentation](https://www.ifixit.com/api-docs)
announces the end of anonymous API access on **January 1, 2027**, with test
brownouts during December 2026. Anonymous reads still work during the transition.

Sign in to iFixit and create a personal API key at
[User → API keys](https://www.ifixit.com/User/api_keys). Copy it once and store it
as the repository Actions secret **IFIXIT_TOKEN** (Settings → Secrets and variables
→ Actions). The daily workflow passes this secret only to the Python collector;
it is never placed in the public JSON or browser assets. Use a read-only key for
this collector and monitor its expiry (keys last at most one year).

Locally, supply `IFIXIT_TOKEN` through your environment. Proxy settings are ignored
by default; set `IFIXIT_USE_PROXY=true` to opt in. A custom CA bundle can be supplied
via `IFIXIT_CA_BUNDLE`; TLS verification stays enabled, including with a proxy.
An authorization preflight runs before any output is written, and API 401/403
responses always fail rather than being parsed as device data.

API compatibility checked against the official OpenAPI download on 2026-11-09:
the collector's `/guides` pagination/filter and category wiki endpoints remain
covered. Rubric and repairability HTML pages are separate from the JSON API and
remain protected by the existing parser regression checks. The site embeds its
own Python client; updating the separate SDK alone does not update this collector.
