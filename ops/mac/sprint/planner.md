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

**Główny fokus (decyzja Piotra 2026-11-15): `home-ops`, `lesson-notes`, `social-hub`, `vectordigital`, `gitara-lekcje`.** Nowe zadania twórz tylko dla tych pięciu projektów. Wyjątki: pomysł Piotra, który wprost wskazuje inny projekt, oraz zadania samego mac-workera (podsumowania, porównywanie modeli lokalnych). W pozostałych projektach nie zlecaj nowych recenzji, poprawek ani audytów; z `failed/limit-*/` przywracaj tylko zadania z tych pięciu projektów.

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
   b. dług PR-ów: recenzja PR-ów bez werdyktu w `results/` albo z werdyktem dla starszego SHA (każda recenzja zapisuje przy PR-ze linię `SHA: <headRefOid>`; porównaj z `gh pr view <nr> --json headRefOid`; gdy SHA się nie zmienił, nie zlecaj ponownej recenzji), potem naprawy (rebase, CI, uwagi z recenzji) tam, gdzie werdykt brzmi „popraw”;
   c. dokończenie porządku w vaulcie (notatki bez Now ≤ 3 z klasą i bez sekcji „Czeka na Piotra”);
   d. audyty per projekt (bezpieczeństwo, dług techniczny, brakujące testy, blueprint tam, gdzie go nie ma) z wynikiem w `3-Zasoby/analysis/<data>-<projekt>-<temat>.md` albo jako PR z testami lub dokumentacją;
   e. etap testera (`kind: test-stage`, model `opus`): tylko w repozytoriach, które mają gałąź `test` wyprzedzającą `main` (`git fetch && git rev-list --count origin/main..origin/test`). Zadanie: przeczytać zmiany `origin/main..origin/test`, dopisać testy integracyjne i E2E (żadnych zmian w kodzie), otworzyć PR do `test` zawierający wyłącznie pliki testów. Tester nie może być workerem, który pisał daną zmianę;
   f. nowy kod tylko dla zadań z Now, które mają klasę, rozmiar S lub M i kryterium akceptacji, i tylko gdy projekt ma mniej niż 2 otwarte PR-y z etykietą `mac-worker`.
   Pomijaj: wszystko, co wymaga produkcji, innych hostów, decyzji Piotra albo wysyłania czegokolwiek na zewnątrz. Projekty zarchiwizowane pomijaj.
6. Dla każdego zadania wybierz model i wysiłek:
   - `local:<model>` (modele lokalne przez Ollamę, bez kosztu limitu, wolniejsze): **pierwszy wybór dla zadań wykonawczych rozmiaru XS i S** (dopisanie testów, podział pliku ponad limit, poprawki lintera, prosta poprawka według listy z recenzji, dokumentacja, porządek w notatce, zestawienia). Podział ról: Ty analizujesz i piszesz specyfikację, model lokalny implementuje, Opus recenzuje. Nigdy recenzje PR-ów, audyty, zadania 🔴 ani wymagające oceny.
     - **Na razie wstrzymane:** dopóki `results/local-models.md` nie ma wiersza z udanym przebiegiem w runnerze (tryb uprawnień dla `local:*` czeka na decyzję Piotra), nie dodawaj zadań `local:*` ani `bench-*`. Bez tego każde takie zadanie zajmuje GPU do limitu czasu bez wyniku. Runner i tak przerywa każde zadanie `local:*` po `local.max_minutes` (domyślnie 20 min), niezależnie od `max_minutes` zadania.
     - Dostępne modele: `ollama list`. Wybieraj według tabeli `results/local-models.md` (rodzaj zadania → najlepszy model), jeśli istnieje; bez danych zmieniaj modele między zadaniami, żeby zebrać porównanie.
     - Treść zadania lokalnego to pełna specyfikacja: pliki do zmiany, co dokładnie zrobić, kryterium akceptacji, komendy sprawdzające (lint, typecheck, testy) i rozmiar (XS/S). Model lokalny nie zgaduje.
     - `max_minutes`: XS 30, S 60 (runner puszcza jedno zadanie lokalne naraz). Po porażce runner sam przekaże zadanie sonnetowi.
     - Do każdego zadania lokalnego, które zmienia kod, dodaj od razu zadanie recenzji: `kind: local-review`, `model: opus`, `after: <id zadania lokalnego>`. Recenzent czyta diff i wynik komend sprawdzających i kończy wynik linią `Ocena lokalna: model=<model, który faktycznie wykonał> rodzaj=<rodzaj> rozmiar=<XS|S> ocena=<przyjęte|po poprawkach|odrzucone> linie_do_poprawy=<liczba>` oraz dokładną listą poprawek. Przy kolejnym planowaniu: „po poprawkach” → zadanie `sonnet` z tą listą; „odrzucone” → to samo zadanie od nowa na `sonnet`.
     - Drabina trudności: zaczynaj od XS; po 3 kolejnych ocenach „przyjęte” dla danego modelu dawaj mu S, po 2 „odrzucone” wróć do XS;
   - `haiku`: praca mechaniczna (przenoszenie wpisów, proste zestawienia);
   - `sonnet`: wykonanie według jasnego opisu (naprawa CI, rebase, testy, porządek w notatce);
   - `opus`: recenzje PR-ów, audyty, zadania wymagające oceny, najtrudniejsze zadania (🔴). To najwyższy model, od którego zadanie może zacząć;
   - `fable`: nigdy jako pierwszy wybór. Tylko dla zadania, które Opus już próbował i faktycznie nie rozwiązał (wpis `retry` albo stan „nie zrobione” z powodu trudności w `runs.jsonl` / `results/`, nie limit ani błąd środowiska). W treści zadania podaj id nieudanej próby Opusa.
   Jeśli `runs.jsonl` pokazuje, że dany model zawodził w danym rodzaju zadań, wybierz mocniejszy; jeśli tani lub lokalny model radził sobie dobrze, używaj go częściej. `max_minutes` dobieraj realnie: zadanie Claude zaczyna się tylko wtedy, gdy zmieści się przed końcem okna pracy.
7. Porównywanie modeli lokalnych (najwyżej 1/3 zadań lokalnych w jednym planowaniu):
   a. Zestaw kontrolny: jeśli nie ma pliku `results/bench-suite.md`, dodaj zadanie `bench-suite` (`opus`): ułożyć 8 stałych zadań z wzorcem odpowiedzi, po jednym na rodzaj (nowa funkcja z testem, podział pliku ponad limit, poprawki lintera, dopisanie testów, poprawka błędu według opisu, podsumowanie wyników, klasyfikacja pozycji do JSON, recenzja diffu z celowo wstawionym błędem), na podstawie zadań z `done/`; zadania mają działać na kopii plików w katalogu wyniku, nie w repozytoriach. Zapis w `results/bench-suite.md`.
   b. Przebieg: dla modelu z `ollama list` (rozmiar do 30 GB), który nie ma jeszcze wiersza w `results/local-models.md`, dodaj 8 zadań `bench-<model>-<n>` (`model: local:<model>`, `kind: bench`, `max_minutes: 15`, treść z zestawu) i zadanie `bench-eval-<model>` (`opus`, `after:` ostatnie z nich): porównać wyniki z wzorcem, ocenić każde 0–3, dopisać do `results/local-models.md` wiersze: model, rodzaj zadania, ocena, czas, błędne wywołania narzędzi; na górze pliku tabela „rodzaj zadania → najlepszy model”.
   c. Nowe modele: najwyżej raz na dobę zadanie `model-scout` (`opus`, `kind: model-scout`): na podstawie `results/local-models.md` i biblioteki https://ollama.com/library wybrać najwyżej 2 kandydatów i zainstalować ich według zasad z `rules.md` („Modele lokalne”). Wynik: co zainstalowano, rozmiar, dlaczego.
8. Pliki zadań zapisuj narzędziem Write (nie przez Bash: heredoc, `cat >`, `echo >`). Hook `guard-bash.py` blokuje polecenia Basha z nazwami stosów produkcyjnych. Każde zadanie zapisz jako osobny plik `queue/<id>.md` w formacie:

```
---
id: <krótki-unikalny-id>
project: <slug projektu>
cwd: <katalog repo albo ~/Obsidian/MainCV-Planner>
model: <local:<model z ollama list>|haiku|sonnet|opus|fable>
effort: <low|medium|high>
kind: <vault|pr-review|pr-fix|audit|code|docs|idea|local-review|bench|model-scout>
priority: <10–90, niżej = wcześniej>
max_minutes: <15–90>
lock: <vault dla zadań edytujących vault; slug projektu dla zadań zmieniających kod; brak dla samych odczytów>
---
<Polecenie: co zrobić, w jakich plikach, jakie jest kryterium ukończenia. Samowystarczalne, worker nie zna tej rozmowy.>
```

9. W wyniku wypisz listę dodanych zadań z jednym zdaniem uzasadnienia wyboru modelu dla każdego oraz listę obsłużonych pomysłów.
