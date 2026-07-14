# Task Selection & Priority Management — Feature Analysis

**Date**: 2026-07-14
**Author**: Claude
**Scope**: The "choose the next task / manage what matters" pipeline — Obsidian vault ↔ planner-sync ↔ Postgres ↔ console (Projects + Board tabs) ↔ morning digest. Analyzed at `feature/digest-terminal-look` (e538e49).

## 1. How it works today

The feature is a five-layer pipeline centered on the **Now / Next / Later** model, with a
single **"Today's focus"** pin as the priority mechanism:

1. **Obsidian vault** (`~/Obsidian/MainCV-Planner/projects/<slug>.md`) — human-edited
   source. Now/Next/Later checkbox sections per project, `status: hot|warm|dormant|stalled`
   in frontmatter.
2. **`agents/elitedesk/planner-sync.py`** — pulls the planner git repo every 60s, parses
   frontmatter + sections, POSTs the full project set to `/api/projects/sync`
   (transactional upsert + delete-missing, so vault deletes propagate). A separate 2s
   thread drains queued checkbox toggles back into the markdown and pushes to git.
3. **Postgres** — three tables: `projects` (denormalized section markdown), `task_toggles`
   (write-back queue with a `queued → applied|conflict|failed` state machine), and
   `board_tasks` (real task rows, but only for `BOARD_SLUG` = home-ops).
4. **Console UI** — a read-mostly Projects tab (checkbox toggles go through the queue),
   and a Board tab (`board.js` + `routes/board.ts`): drag-and-drop kanban over
   Now/Next/Later, mark done, and pin one card as ★ Today's focus. The single-focus
   invariant is enforced server-side in a transaction.
5. **Morning digest** (`ops/elitedesk/daily-digest.sh`) — "Today's focus" = the pinned
   board card, falling back to the top Next item; plus the full Now/Next lists.

The load-bearing design decision is the **authority split**: `board_tasks` is
authoritative for the home-ops slug (board edits render back into the vault markdown and
get committed as `planner-sync`), while the vault stays authoritative for every other
project. Reconciliation is watermark + managed-section-hash based (`board_sync_once`), so
the agent's own commits don't echo back as external edits.

## 2. What's genuinely good

- **The priority model is honest about how a single technical user works**: ordering
  within a column *is* the priority, and one pinned focus resolves "what do I do first"
  without inventing priority numbers, story points, or due dates nobody would maintain.
- **The digest closes the loop** — the system doesn't just store priorities, it pushes
  the top one at 07:00, and the steering contract is documented ("reorder Next to change
  tomorrow's focus").
- **Write-back is queue-based, not synchronous** — UI toggles survive the agent being
  down, conflicts surface as chips on the drill page rather than being silently lost,
  and the 2s drain thread keeps feedback sub-5s.
- Full-set sync with transactional delete-missing means the DB can't drift into ghost
  projects.

## 3. Problems, ranked

### 3.1 Digest fallback can pick a *completed* task as Today's focus — BUG

The comment in `daily-digest.sh` says "top **unchecked** Next item," but the SQL took
`split_part(next_md, E'\n', 1)` — the literal first line, checked or not. The vault style
keeps dated `[x]` items in place, so the moment the top Next item is marked done without
being removed, the morning email presents a completed task as Today's focus.

**Fixed 2026-07-14** (this branch): the fallback now selects the first line matching an
*unchecked* checkbox (`- [ ]`).

### 3.2 Tasks have no identity — everything matches by position or exact text

The structural weakness behind three separate fragilities:

- Checkbox toggles referenced `(section, idx)` only. If the vault file changes between
  the UI render and the toggle applying (item added/removed above it), the flip lands on
  the **wrong task**. The pre-edit `git pull` narrows the window but can't close it.
- The vault→board import (`POST /api/board/import`) is a destructive
  `DELETE all + reinsert`: ids churn, `created_at` is lost, and the focus pin is
  re-attached by **exact text match** — editing the focused task's wording in Obsidian
  silently drops the pin.
- Text *is* the join key everywhere, so renames are indistinguishable from
  delete+create.

**Partially fixed 2026-07-14** (this branch): toggles now carry the task's text
(migration `015_task_toggle_text`); planner-sync flips the matching-text line first and
falls back to the positional index only when the text isn't found. The import-path text
matching (focus re-pin) is unchanged — a proper fix needs stable task ids, which is a
design decision (see §4).

### 3.3 Agent restarts can clobber vault edits

`_board_last` (watermark + managed-section hash) lived only in memory. On restart, the
first tick takes the "DB is authoritative" branch — any Obsidian edits to home-ops
Now/Next/Later made while the agent was down get overwritten by the DB render.
Recoverable via git history, but silent.

**Fixed 2026-07-14** (this branch): the watermark/hash pair persists to a JSON state file
next to the clone (`<PLANNER_DIR>.state.json`), loaded at startup.

### 3.4 The board — the actual "choose next task" tool — exists for exactly one project

`BOARD_SLUG` is a single env var; every other project gets read-only lists plus checkbox
toggles. "Today's focus" is therefore a *home-ops* focus, not a global one. With ~13
projects in the vault and hot/warm tiering already in the DB, the natural question the
system can't yet answer is the cross-project one: "of everything across all hot
projects, what's first today?" The pieces exist (per-slug `board_tasks`, `is_focus`,
hot-first ordering in `/api/projects`) — missing are boards per slug and a global focus
concept for the digest. **Open — scope decision.**

### 3.5 No done-item hygiene

Done cards stay in columns forever unless hand-deleted; `projects/home-ops.md` shows the
pattern — Now contains long dated `[x]` entries acting as a changelog, and a `[x]` item
sits in *Later*. Fine as a log, but it means "Now" doesn't mean *now*, and it fed bug
§3.1. An auto-archive (move `[x]` older than N days to a `## Log` section during board
render) would keep the managed sections meaning what their names say. **Open.**

### 3.6 Prioritization is entirely manual, while the ingredients for assistance exist

Commits per project, error rates, pain points, staleness, and an overnight GPU LLM job
that already writes the morning narrative. The narrative could end with a *suggested*
focus — suggestion only, the pin stays the human override. **Open — future direction.**

## 4. Recommended order of work

1. ~~Fix the digest fallback to skip checked items~~ — **done** (this branch).
2. ~~Persist the board-sync watermark~~ — **done** (this branch).
3. ~~Match toggles by text with idx fallback~~ — **done** (this branch).
4. Decide the direction question: does the Board become the cross-project "what do I
   work on today" surface (boards per hot project + one global focus in the digest), or
   stay a home-ops-only tool with the vault as the cross-project view? That choice
   drives whether task identity (§3.2) is worth solving properly with stable ids.
5. Done-item auto-archive (§3.5) — small, independent, improves both the board and the
   digest regardless of the §4 decision.
