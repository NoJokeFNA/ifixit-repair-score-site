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
- iFixit API reads share one request budget across workers and retries, capped at 32 requests per second by default with up to 32 workers. Use `--api-rate 4` for the previous conservative ceiling, or select another ceiling such as 16 or 64. A 429 response applies `Retry-After` to all workers, halves the rate, and recovers gradually after successful responses. Every device and variant is still fetched on every import; no stale device cache is substituted.
- The quality report includes API request counts, configured/current rate and observed throttling, so production timings can be compared with the actual request budget.

Rubric maintenance:
- Rubric tables are fetched from the wiki JSON API (`contents_rendered`), avoiding the themed HTML page and its inline CSS/scripts.
- The daily build probes version numbers 1.0 through 10.9 (one minor digit), including gaps.
- New criteria are added automatically when the source scoring table uses the existing layout.
- Missing previously published versions or an unrecognized scoring table fail the build and preserve the previous rubric output.
- Python regression tests: `PYTHONPATH=src python -m unittest discover -s tests -v`.
- Before publishing, the daily workflow runs browser checks for every generated version, including its details dialog, sorting, and a simulated future criterion. Changes to iFixit's URL scheme, version numbering, or table layout may require a parser update.

French score matching:
- Production fetches use the public WooCommerce Store API, selecting only product identity, description fields and score data. The current 601-product catalogue takes seven product pages of up to 100 items plus one category lookup, instead of 38 themed HTML pages. Product IDs, source URLs, category count and pagination totals are verified before replacement. The HTML reader remains available for independent parity checks.
- The French index and iFixit's score use different methods; differences between them are expected and are never treated as conflicts.
- Each category imports `/wikis/CATEGORY/{title}/topic_variants`, its local `model_number` fields, and explicit model labels in the identification section. Every named regional variant and variant ID is retained; an unnamed variant is not treated as a model identifier.
- Exact model numbers take precedence when available. The French score records only the model numbers actually present in its source entries, not every region listed by iFixit. Network variants, hardware suffixes such as U/U1, and iPhone SE generations remain distinct. No fuzzy matching is used.
- `model_identification` stores codes, full variant names including regions/Dual-SIM, endpoint availability, and reference URLs. Manufacturer-verified fallbacks in `data/verified_model_numbers.json` cover categories with incomplete API metadata.
- Variant requests share the existing rate limiter. Unsupported code formats remain in the raw variant names; they are not guessed into model identifiers.
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

Import quality monitoring:
- Generation uses temporary candidate files and compares them against the current output files before replacement. Parser failures or a rejected comparison retain the previous source, device, and rubric outputs.
- Exact source titles retain repeated spaces and special characters when encoded as API URLs. Search-style normalization must not change a device's identity.
- A confirmed device HTTP 404 is recorded in `source_removals` and removes the unavailable device from publication with a warning. Device/variant authentication errors, server failures, rate limits and malformed data still block publication. A variant-endpoint 404 must not be mistaken for deletion of the device.
- Successful device reads store `wikiid`, `wiki_namespace`, and explicit redirect evidence. Renames are compared by a persisted wiki ID or a verified redirect from a previously published name. A unique, complete model-number set with matching brand and reference URLs can establish a rename when an old name disappears; overlapping or ambiguous model sets and name similarity alone are insufficient. The report records the matching method. Redirect loops and conflicting identities are rejected.
- A redirect to the `WIKI` namespace does not provide category variants. The report identifies this case, and previously published variants are never copied into the new snapshot to conceal missing source evidence. Verified changes from successful variant responses, and explicit moves into `WIKI`, are reported as warnings rather than permanently blocking the daily job. Unexplained variant losses remain guarded.
- An unexplained loss of at least 10% of previously published source URLs, devices, French scores, iFixit scores, model identifications, or named regional variants blocks the import. Confirmed device deletions and verified source variant changes are excluded from the blocking threshold but remain visible in losses and warnings. Added records cannot hide lost records. Smaller losses are recorded as warnings.
- A manufacturer with at least three French scores losing half or more of them also blocks the import, even if its global share is small. A device with at least three named regional variants losing half or more of them is protected in the same way.
- `--quality-report PATH` writes counts, exact lost identities, errors and warnings as JSON. The daily workflow adds a GitHub Actions summary and retains the report as an artifact for 30 days, including failed runs.
- Unexplained large losses require source review before deliberately changing a baseline; confirmed device deletions remain automatic, visible warnings.
