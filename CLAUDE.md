# CLAUDE.md — home-ops

_2026-11-14 · updated 2026-11-15 (gates in a subshell, stacked PRs → dev)_

Read `docs/CONTEXT.md` first (what the system is), `docs/RUNBOOK.md` for deploys, `docs/adr/` for decisions.

## Branches: dev → test → main

- New work: branch from `origin/dev`, PR into `dev` (the default branch). Unit tests go with the change.
- `dev` green → merged into `test` automatically. `test` is where an independent tester adds integration and
  end-to-end tests (PRs into `test` that touch only test files merge by themselves and flow back to `dev`).
- `test` green → a PR `test` → `main` is opened. `main` is what uwh runs; it only changes through that PR.
- A red `test` files an issue labelled `back-to-dev`; fix it with a PR into `dev`.
- A PR stacked on another feature branch is retargeted to `dev` (never `main`) once the lower one merges.
- Never merge or approve a PR from the session that wrote it. Details: `docs/adr/2026-11-14-three-branches.md`.

## Gates before a commit

```bash
(cd ingest && npm ci && npm run check && npx vitest run src/__tests__ public)
python3 -m unittest discover -s agents/tests -p 'test_*.py'
python3 -m unittest discover -s ops/elitedesk/tests -p 'test_*.py'
python3 -m unittest discover -s ops/ci/tests -p 'test_*.py'
```

Route tests against Postgres run in CI (`check.yml`, job with the `postgres` service); locally they need
`DATABASE_URL`. New Python files and migrations must be added to the explicit lists in `check.yml`.
