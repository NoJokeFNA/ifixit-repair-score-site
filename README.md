# iFixit Repair Scores Site

Python 3.13 project that builds a JSON with device repairability information from the iFixit API. A separate gh-pages branch hosts the static website and the generated JSON.

- Data source: iFixit API v2.0
- Backend (main branch): Python only
- Frontend (gh-pages branch): vanilla HTML/JS/CSS
- Deployment: GitHub Pages via Actions

Workflows:
- build-json-to-pages.yml: builds devices_with_scores.json and commits it directly to the gh-pages branch (manual dispatch or daily at 03:00 UTC).
- pages.yml: deploys the gh-pages branch to GitHub Pages when files there change.
- ci.yml: runs Ruff (lint/format) on main.

Local run example:
- python src/fetch_device_data.py --categories "iPhone" "Android Phone" --scores-output devices_with_scores.json
