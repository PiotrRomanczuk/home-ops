---
created: 2026-11-11
updated: 2026-11-11
status: accepted
---

# ADR: the Mapa tab is a React SPA next to the plain-JS console, the vault stays the model

**Date**: 2026-11-11 · **Author**: Piotr (with Claude) · **Scope**: `ingest/web/`, `routes/mapa.ts`, `/api/{map,pressure,processes}`

## Context

Piotr's private tools started calling each other: job-radar feeds
vectordigital and natalia-cv, several projects need Ollama on wfh, d4 and
job-radar live in home-ops' Postgres. That knowledge existed only as prose
and two Mermaid diagrams in the vault's `SYSTEM-MAP.md`. The ask was UML /
BPMN "in a nicer UI than plain UML", **keeping the project-map mechanics**
(project notes with frontmatter, `Projekty.base` as a view), plus a way to
see which projects have the most bugs, issues and missing features.

The console (`ingest/public/`) has no build step: hyperscript `h()`, one CSS
file per view. Piotr asked for a proper UI framework for this view; graph
layout, a canvas with pan/zoom, side sheets and a BPMN editor are a poor fit
for hand-rolled DOM.

## Decision

1. **The vault is the model.** Relations are frontmatter on project notes:
   `depends_on` (it breaks without X), `feeds` (it sends data / logs / leads
   to X), `hosts`. Processes are notes with `type: process` plus a BPMN 2.0
   file next to them. home-ops only mirrors them (planner-sync → `projects`,
   `processes`, migration 029). A target without a note becomes an "external"
   node; no extra notes are created for services.
2. **Views, not drawings.** `/api/map` builds the graph, transitive
   dependents ("if it goes down") and per-node pressure; nothing about the
   picture is stored. Ecosystem ≈ UML component, Infrastruktura ≈ UML
   deployment, Procesy = real BPMN (bpmn-js), Presja = a ranked queue.
3. **A separate SPA under `/mapa/`**, not a rewrite of the console: Vite +
   React + TypeScript, Tailwind v4 + shadcn/ui, React Flow + elkjs. Its own
   page avoids Tailwind's preflight fighting `styles.css`; the console gets a
   tab that links there. Built in the first stage of the ingest Dockerfile,
   served by Hono behind the same viewer login.
4. **Pressure is a suggestion.** score = base × blast × status weight, with
   every part returned and shown. `QUEUE.md` and `/task-review` decide.

## Consequences

- The ingest image now needs a Node build stage; `ingest/web` has its own
  package, lockfile and CI job.
- Two UI stacks live side by side. Other tabs can move into the SPA one at a
  time if that ever pays off — not planned.
- Relations are only as good as the frontmatter. Planner notes get
  `depends_on` / `feeds` columns in `Projekty.base` and in the template, so
  gaps are visible where they are edited.

## Rejected

- **Hand-drawn UML/BPMN files** (PlantUML, draw.io): a second copy of the
  truth that drifts, like the Strummy blueprint `dashboard.html` without a
  generator.
- **Obsidian Canvas generated from frontmatter**: stays in the vault but has
  no live data (errors, CI, issues) and needs a regeneration step.
- **Extending the plain-JS console**: no layout engine, no component library;
  the BPMN editor alone would be a large hand-written integration.
