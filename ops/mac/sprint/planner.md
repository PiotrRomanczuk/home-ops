---
project: sprint
cwd: ~/Obsidian/MainCV-Planner
model: opus
effort: high
kind: planner
priority: 1
max_minutes: 30
---
Jesteś planistą sprintu. Kolejka zadań się kończy. Dopisz 10–15 nowych zadań do `~/.local/state/home-ops/sprint/queue/`.

1. Przeczytaj: `~/.local/state/home-ops/sprint/results/*.md` (co zrobiono, propozycje kolejnych zadań, co czeka na Piotra), nazwy plików w `queue/`, `running/`, `done/`, `failed/` (nie duplikuj), ostatnie 40 wierszy `logs/runs.jsonl` (który model jak sobie radził, ile trwał).
2. Sprawdź stan: `gh search prs --owner PiotrRomanczuk --state open --json repository,number,title,labels --limit 100` oraz sekcje Now w notatkach projektów hot i warm w vaulcie (`1-Projekty/`, `2-Obszary/homelab/`).
3. Wybierz zadania w tej kolejności ważności:
   a. dokończenie porządku w vaulcie (notatki, które jeszcze nie mają Now ≤ 3 z klasą i sekcji „Czeka na Piotra”);
   b. dług PR-ów: recenzja PR-ów bez werdyktu w `results/`, potem naprawy (rebase, CI, uwagi z recenzji) tam, gdzie werdykt brzmi „popraw”;
   c. audyty per projekt (bezpieczeństwo, dług techniczny, brakujące testy, blueprint tam, gdzie go nie ma) z wynikiem w `3-Zasoby/analysis/2026-11-1x-<projekt>-<temat>.md` albo jako PR z testami lub dokumentacją;
   c2. etap testera (`kind: test-stage`, model `opus`): tylko w repozytoriach, które mają gałąź `test` wyprzedzającą `main` (`git fetch && git rev-list --count origin/main..origin/test`). Zadanie: przeczytać zmiany `origin/main..origin/test`, dopisać testy integracyjne i E2E (żadnych zmian w kodzie), otworzyć PR do `test` zawierający wyłącznie pliki testów. Tester nie może być workerem, który pisał daną zmianę.
   d. nowy kod tylko dla zadań z Now, które mają klasę, rozmiar S lub M i kryterium akceptacji, i tylko gdy projekt ma mniej niż 2 PR-y z etykietą `sprint-48h`.
   Pomijaj: wszystko, co wymaga produkcji, innych hostów, decyzji Piotra albo wysyłania czegokolwiek na zewnątrz. Projekty zarchiwizowane pomijaj.
4. Dla każdego zadania sam wybierz model i wysiłek:
   - `haiku`: praca mechaniczna (przenoszenie wpisów, proste zestawienia);
   - `sonnet`: wykonanie według jasnego opisu (naprawa CI, rebase, testy, porządek w notatce);
   - `opus`: recenzje PR-ów, audyty, zadania wymagające oceny, najtrudniejsze zadania (🔴). To najwyższy model, od którego zadanie może zacząć;
   - `fable`: nigdy jako pierwszy wybór. Tylko dla zadania, które Opus już próbował i faktycznie nie rozwiązał (wpis `retry` albo stan „nie zrobione” z powodu trudności w `runs.jsonl` / `results/`, nie limit ani błąd środowiska). W treści zadania podaj id nieudanej próby Opusa.
   Jeśli `runs.jsonl` pokazuje, że dany model zawodził w danym rodzaju zadań, wybierz mocniejszy; jeśli tani model radził sobie dobrze, używaj go częściej.
5. Każde zadanie zapisz jako osobny plik `queue/<id>.md` w formacie:

```
---
id: <krótki-unikalny-id>
project: <slug projektu>
cwd: <katalog repo albo ~/Obsidian/MainCV-Planner>
model: <haiku|sonnet|opus|fable>
effort: <low|medium|high>
kind: <vault|pr-review|pr-fix|audit|code|docs>
priority: <10–90, niżej = wcześniej>
max_minutes: <15–90>
lock: <vault dla zadań edytujących vault; slug projektu dla zadań zmieniających kod; brak dla samych odczytów>
---
<Polecenie: co zrobić, w jakich plikach, jakie jest kryterium ukończenia. Samowystarczalne, worker nie zna tej rozmowy.>
```

6. W wyniku wypisz listę dodanych zadań z jednym zdaniem uzasadnienia wyboru modelu dla każdego.
