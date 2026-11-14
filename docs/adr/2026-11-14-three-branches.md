---
created: 2026-11-14
updated: 2026-11-15
status: accepted
---

# ADR: Three long-lived branches — dev → test → main, with an independent test stage

**Date**: 2026-11-14 · **Author**: Piotr (with Claude) · **Scope**: this repo as the pilot of the global rule (`branch-hygiene.md`, 2026-11-14); `.github/workflows/{check,flow}.yml`, `ops/ci/flow_{paths,ops,cli}.py`, `ops/elitedesk/pr_gate.py`

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
| 5a | `check` green on `test` and `test` ahead of `main` with a different tree → a PR `test` → `main` is opened (one per batch). | automation; Piotr merges |
| 5b | `check` red on `test` → an issue labelled `back-to-dev`. Nothing is reverted: the fix is a PR into `dev` and flows again. | automation |
| 6 | `main` moved → `main` is merged into `dev`. | automation |

- Piotr clicks twice per change: into `dev` and, per batch, into `main`.
- Promotion PRs (`test` → `main`) are merged with a merge commit and the branch is kept; `pr_gate.merge_reviewed`
  does this for any PR whose head is `dev`, `test` or `main`. Squashing would make `test` and `main` diverge.
- `main` is protected: changes only through a PR. A production hotfix is a PR into `main` on Piotr's instruction;
  step 6 brings it to `dev`.
- Unit tests stay with the change on `dev`. End-to-end tests keep the global cap (10 per feature).

## Consequences

- **Token.** `flow.yml` uses the repo secret `FLOW_TOKEN` when it exists: a fine-grained PAT or GitHub App for
  this repository only, with *Contents*, *Pull requests*, *Issues* and *Workflows* write. Its pushes start `check`
  by themselves and may carry changes to `.github/workflows/`. Without it the flow falls back to `GITHUB_TOKEN`,
  which (a) starts no workflows, so `flow.yml` dispatches `check` on every branch it pushes to (`check` has
  `workflow_dispatch` for that), and (b) cannot push a change to `.github/workflows/` at all — such a promotion
  files one issue with the manual push (`git push origin origin/dev:test`) and stops. The first promotion of
  this very change is such a case. Creating the secret is Piotr's call (`RUNBOOK.md`, Branches).
- If the repository does not allow Actions to open pull requests (Settings → Actions → General), step 5a files
  one issue with the compare link instead, refreshed on every green `test`. Turning that setting on, or
  `FLOW_TOKEN`, is Piotr's call.
- Every issue the flow files is deduplicated by its fixed title; counts and run links live in the body.
- Step 5a needs `test` ahead of `main` **and** a different tree: after a release, step 6 and the next
  promotion add only merge commits, which must not open a new release PR.
- Writers (`promote`, `tester-pr`, `sync`) share one concurrency group and retry a push once after merging the
  moved branch. GitHub keeps one pending job per group, so a burst can drop a queued job; all of them work
  from the branch state, and the next green run repeats the work.
- `pr_gate` keeps history only for the repo's own long-lived branches (head owner = repo owner): a fork's
  branch named `main` is squashed like any feature branch.
- **The first release `test` → `main` is merged by hand** with a merge commit (`RUNBOOK.md`, "First release"):
  until `main` carries the new `pr_gate`, "Dziś" on uwh would squash it and delete `test`.
- uwh still deploys `main` (`RUNBOOK.md`); there is no separate test environment. End-to-end here means the
  Postgres-backed route tests in `check` until the console gets browser tests.
- `github-repo-sync` reads the default branch from GitHub, so Postęp now counts commits on `dev`.
- The tester is a task type for now (sprint queue, later a routine on uwh next to `pr-review`).

## Rejected

- **Manual promotion `dev` → `test`.** A third click per change for no decision.
- **Reverting on a red `test`.** Rewrites history and loses the failing test as the specification of the fix.
- **Tests written on `test` staying there.** `dev` would never see them; the next author could not run them.
