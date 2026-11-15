---
project: sprint
cwd: ~/Obsidian/MainCV-Planner
model: opus
effort: high
kind: planner
priority: 1
max_minutes: 30
lock: vault
---
Jesteś planistą pracy w tle na Macu (mac-worker). Kolejka zadań się kończy. Dopisz 6–10 nowych zadań do `~/.local/state/home-ops/sprint/queue/`. Budżet Claude jest ograniczony (tło zużywa najwyżej 80% tygodniowego limitu, równo rozłożone na tydzień), więc wybieraj zadania o największej wartości.

1. Przeczytaj: `~/.local/state/home-ops/sprint/results/*.md` (co zrobiono, propozycje kolejnych zadań, co czeka na Piotra), nazwy plików w `queue/`, `running/`, `done/`, `failed/` (nie duplikuj), ostatnie 60 wierszy `logs/runs.jsonl` (który model jak sobie radził, ile trwał, także modele lokalne `local:*`).
2. Pomysły Piotra: w notatce `2-Obszary/homelab/mac-praca-w-tle.md`, sekcja „## Pomysły”. Każdą linię `- [ ]`:
   - zamień w jedno lub kilka zadań i oznacz w notatce: `- [x] … → <id zadania>`;
   - jeśli brakuje decyzji Piotra, nie twórz zadania; oznacz `- [x] … → czeka na Piotra` i dopisz pytanie do swojego wyniku w sekcji „Czeka na Piotra”;
   - jeśli pomysł to długie obliczenia lokalne (GPU, model lokalny po wielu plikach, przebieg wsadowy), nie twórz zadania. Dopisz propozycję do sekcji „## Propozycje GPU” w tej notatce: nazwa, dokładne polecenie (`argv` jako lista JSON), `cwd`, liczba shardów, szacowany czas. Oznacz pomysł `→ propozycja GPU`. Zadania GPU dodaje tylko Piotr.
   Zmieniaj w notatce tylko te linie i sekcję propozycji. Zacommituj notatkę: `git add 2-Obszary/homelab/mac-praca-w-tle.md && git commit -m "mac-worker: pomysły → zadania"`.
3. Jeśli istnieje katalog `failed/limit-*/` (zadania, które padły tylko na limicie), przejrzyj go: zadania nadal aktualne (np. recenzja PR-a, który jest wciąż otwarty) przenieś do `queue/` z `attempts: 0`; potem zmień nazwę katalogu na `failed/przejrzane-<data>/`.
4. Sprawdź stan: `gh search prs --owner PiotrRomanczuk --state open --json repository,number,title,labels --limit 100` oraz sekcje Now w notatkach projektów hot i warm w vaulcie (`1-Projekty/`, `2-Obszary/homelab/`).
5. Wybierz zadania w tej kolejności ważności:
   a. pomysły Piotra z punktu 2;
   b. dług PR-ów: recenzja PR-ów bez werdyktu w `results/`, potem naprawy (rebase, CI, uwagi z recenzji) tam, gdzie werdykt brzmi „popraw”;
   c. dokończenie porządku w vaulcie (notatki bez Now ≤ 3 z klasą i bez sekcji „Czeka na Piotra”);
   d. audyty per projekt (bezpieczeństwo, dług techniczny, brakujące testy, blueprint tam, gdzie go nie ma) z wynikiem w `3-Zasoby/analysis/<data>-<projekt>-<temat>.md` albo jako PR z testami lub dokumentacją;
   e. etap testera (`kind: test-stage`, model `opus`): tylko w repozytoriach, które mają gałąź `test` wyprzedzającą `main` (`git fetch && git rev-list --count origin/main..origin/test`). Zadanie: przeczytać zmiany `origin/main..origin/test`, dopisać testy integracyjne i E2E (żadnych zmian w kodzie), otworzyć PR do `test` zawierający wyłącznie pliki testów. Tester nie może być workerem, który pisał daną zmianę;
   f. nowy kod tylko dla zadań z Now, które mają klasę, rozmiar S lub M i kryterium akceptacji, i tylko gdy projekt ma mniej niż 2 otwarte PR-y z etykietą `mac-worker`.
   Pomijaj: wszystko, co wymaga produkcji, innych hostów, decyzji Piotra albo wysyłania czegokolwiek na zewnątrz. Projekty zarchiwizowane pomijaj.
6. Dla każdego zadania wybierz model i wysiłek:
   - `local:qwen3.8:27b` albo `local:gemma4:26b` (modele lokalne, bez kosztu limitu, wolniejsze): do około 1/3 zadań, które dałbyś haiku lub sonnetowi — porządki w notatkach, zestawienia, proste poprawki z testami. Nigdy recenzje PR-ów, audyty, zadania 🔴 ani wymagające oceny. Zmieniaj modele między zadaniami, żeby zebrać porównanie. Zadanie lokalne: `max_minutes` co najmniej 60 (runner i tak puszcza tylko jedno lokalne naraz). Po porażce runner sam przekaże je sonnetowi;
   - `haiku`: praca mechaniczna (przenoszenie wpisów, proste zestawienia);
   - `sonnet`: wykonanie według jasnego opisu (naprawa CI, rebase, testy, porządek w notatce);
   - `opus`: recenzje PR-ów, audyty, zadania wymagające oceny, najtrudniejsze zadania (🔴). To najwyższy model, od którego zadanie może zacząć;
   - `fable`: nigdy jako pierwszy wybór. Tylko dla zadania, które Opus już próbował i faktycznie nie rozwiązał (wpis `retry` albo stan „nie zrobione” z powodu trudności w `runs.jsonl` / `results/`, nie limit ani błąd środowiska). W treści zadania podaj id nieudanej próby Opusa.
   Jeśli `runs.jsonl` pokazuje, że dany model zawodził w danym rodzaju zadań, wybierz mocniejszy; jeśli tani lub lokalny model radził sobie dobrze, używaj go częściej. `max_minutes` dobieraj realnie: zadanie Claude zaczyna się tylko wtedy, gdy zmieści się przed końcem okna pracy.
7. Każde zadanie zapisz jako osobny plik `queue/<id>.md` w formacie:

```
---
id: <krótki-unikalny-id>
project: <slug projektu>
cwd: <katalog repo albo ~/Obsidian/MainCV-Planner>
model: <local:qwen3.8:27b|local:gemma4:26b|haiku|sonnet|opus|fable>
effort: <low|medium|high>
kind: <vault|pr-review|pr-fix|audit|code|docs|idea>
priority: <10–90, niżej = wcześniej>
max_minutes: <15–90>
lock: <vault dla zadań edytujących vault; slug projektu dla zadań zmieniających kod; brak dla samych odczytów>
---
<Polecenie: co zrobić, w jakich plikach, jakie jest kryterium ukończenia. Samowystarczalne, worker nie zna tej rozmowy.>
```

8. W wyniku wypisz listę dodanych zadań z jednym zdaniem uzasadnienia wyboru modelu dla każdego oraz listę obsłużonych pomysłów.
