---
project: sprint
cwd: ~/Obsidian/MainCV-Planner
model: sonnet
effort: medium
kind: summary
priority: 2
max_minutes: 20
lock: vault
---
Napisz podsumowanie okresowe sprintu. Przeczytaj `~/.local/state/home-ops/sprint/results/*.md` zmienione od poprzedniego podsumowania oraz `logs/runs.jsonl`.

W pliku `3-Zasoby/analysis/2026-11-14-sprint-48h.md` w vaulcie, POD nagłówkiem „## Podsumowania” (nad tabelą przebiegów jej nie ruszaj), dopisz sekcję `### <data i godzina>` z trzema listami:
- Zrobione (per projekt, z linkami do PR-ów i notatek),
- Utknęło (zadania w `failed/` i dlaczego),
- Czeka na Piotra (zebrane ze wszystkich wyników, bez powtórzeń, najważniejsze na górze).

Zacommituj tylko ten plik i wypchnij vault (`git add 3-Zasoby/analysis/2026-11-14-sprint-48h.md && git commit -m "sprint: podsumowanie" && git push`).
