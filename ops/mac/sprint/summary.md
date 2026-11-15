---
project: sprint
cwd: ~/Obsidian/MainCV-Planner
model: sonnet
effort: low
kind: summary
priority: 2
max_minutes: 20
lock: vault
---
Napisz dzienne podsumowanie pracy w tle na Macu za ostatnie 24 h. Przeczytaj `~/.local/state/home-ops/sprint/results/*.md` zmienione od poprzedniego podsumowania, `logs/runs.jsonl` (ostatnie 24 h), `usage.json` (zużycie limitu) oraz `gpu/status.json` i `gpu/log.jsonl` (nadzorca GPU, ostatnie 24 h).

W najnowszym raporcie tygodniowym (`ls -t 3-Zasoby/analysis/*-mac-worker-tydzien.md | head -1` w vaulcie), POD nagłówkiem „## Podsumowania” (tabeli przebiegów niżej nie ruszaj), dopisz sekcję `### <data>` z listami:
- Zrobione (per projekt, z linkami do PR-ów i notatek),
- Utknęło (zadania w `failed/` i dlaczego),
- Lokalne LLM vs Claude: dla każdego modelu i rodzaju zadania (`kind`) liczba prób, udane, średni czas, przekazane dalej (eskalacje z `local:*` do sonnet); jedno zdanie wniosku,
- GPU: które zadanie, ile godzin pracy, pauzy i ich powody, zdarzenia temperatury/pamięci,
- Limit: tydzień % i sesja % z `usage.json`,
- Czeka na Piotra (zebrane ze wszystkich wyników, bez powtórzeń, najważniejsze na górze).

Zacommituj tylko ten plik i wypchnij vault (`git add <plik> && git commit -m "mac-worker: podsumowanie dnia" && git push`).
