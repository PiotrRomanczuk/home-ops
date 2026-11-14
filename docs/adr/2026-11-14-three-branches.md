---
created: 2026-11-14
updated: 2026-11-14
status: accepted
---

# ADR: Three long-lived branches — dev → test → main, with an independent test stage

**Date**: 2026-11-14 · **Author**: Piotr (with Claude) · **Scope**: this repo as the pilot of the global rule (`branch-hygiene.md`, 2026-11-14); `.github/workflows/{check,flow}.yml`, `ops/ci/flow_paths.py`, `ops/elitedesk/pr_gate.py`

## Context

Until now every PR went straight to `main`, and `main` is what uwh deploys. The author of a change (usually a
Claude session) also wrote its tests, so integration and end-to-end gaps were found in production. Piotr's rule since
2026-11-14: every project has `dev`, `test` and `main`. His choices for the pilot: promotion `dev` → `test` is
automatic; `test` exists only to add and run integration and end-to-end tests; anything found there goes back to `dev`.

## Decision

| Step | What happens | Who |
| --- | --- | --- |
| 1 | A feature branch with its unit tests is a PR into `dev` (default branch). `check` runs. | author; Piotr merges via "Dziś" |
| 2 | `check` green on `dev` → `flow.yml` merges `dev` into `test`. | automation |
| 3 | On `test`, a tester that did not write the change adds integration and end-to-end tests as a PR into `test`. | independent agent |
| 4 | A green PR into `test` that touches only test files (`ops/ci/flow_paths.py`) merges by itself, and `test` is merged back into `dev` so the author has the tests. | automation |
| 5a | `check` green on `test` and `test` ahead of `main` → a PR `test` → `main` is opened (one per batch). | automation; Piotr merges |
| 5b | `check` red on `test` → an issue labelled `back-to-dev`. Nothing is reverted: the fix is a PR into `dev` and flows again. | automation |
| 6 | `main` moved → `main` is merged into `dev`. | automation |

- Piotr clicks twice per change: into `dev` and, per batch, into `main`.
- Promotion PRs (`test` → `main`) are merged with a merge commit and the branch is kept; `pr_gate.merge_reviewed`
  does this for any PR whose head is `dev`, `test` or `main`. Squashing would make `test` and `main` diverge.
- `main` is protected: changes only through a PR. A production hotfix is a PR into `main` on Piotr's instruction;
  step 6 brings it to `dev`.
- Unit tests stay with the change on `dev`. End-to-end tests keep the global cap (10 per feature).

## Consequences

- Pushes made with `GITHUB_TOKEN` start no workflows, so `flow.yml` dispatches `check` on every branch it pushes
  to; `check` has `workflow_dispatch` for that.
- If the repository does not allow Actions to open pull requests (Settings → Actions → General), step 5a files an
  issue with the compare link instead. Turning that setting on is Piotr's call.
- uwh still deploys `main` (`RUNBOOK.md`); there is no separate test environment. End-to-end here means the
  Postgres-backed route tests in `check` until the console gets browser tests.
- `github-repo-sync` reads the default branch from GitHub, so Postęp now counts commits on `dev`.
- The tester is a task type for now (sprint queue, later a routine on uwh next to `pr-review`).

## Rejected

- **Manual promotion `dev` → `test`.** A third click per change for no decision.
- **Reverting on a red `test`.** Rewrites history and loses the failing test as the specification of the fix.
- **Tests written on `test` staying there.** `dev` would never see them; the next author could not run them.
