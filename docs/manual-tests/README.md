---
created: 2026-11-17
updated: 2026-11-17
---

# Manual test reports

This repo is **public**. A report with real data does not go into it.

- Screenshots only from **demo data**, and the report carries the marker `data-demo="true"` (for example `<body data-demo="true">`).
- No real names of students or clients, e-mail addresses, phone numbers, MAC addresses or LAN/tailnet addresses in text or images.
- `scripts/check-public-data.sh` runs in CI on every PR to `dev`, `test` and `main` and checks the lines the PR adds. Locally: `BASE=origin/dev scripts/check-public-data.sh`.
- Image files (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.svg`, `.heic`, `.avif`, `.bmp`, `.tif`, `.tiff`, any letter case) added or changed under `docs/` are blocked as `image file` unless a `file:` rule in the allowlist permits them.
- Justified exceptions go to `scripts/public-data-allowlist.txt`, one rule per line with a comment.
- No screenshot of demo data possible? Describe the result in text and in command output.
