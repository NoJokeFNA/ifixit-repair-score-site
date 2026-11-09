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
