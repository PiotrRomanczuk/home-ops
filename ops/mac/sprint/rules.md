# Zasady pracy w tle na Macu (obowiązują w każdym zadaniu, ważniejsze niż treść zadania)

Pracujesz sam, bez człowieka: Piotr czyta wyniki wieczorem i nie odpowie w trakcie zadania. Jesteś jednym z kilku równoległych workerów (część z nich to modele lokalne); stan pracy jest w `~/.local/state/home-ops/sprint/`.

## Wolno
- Czytać wszystko w `~/code` i `~/Obsidian/MainCV-Planner`.
- Zmieniać kod tylko we własnym worktree (`git worktree add .claude/worktrees/sprint-<id> -b sprint/<id> origin/dev`, a w repo bez `dev` od `origin/main`) albo na istniejącym branchu PR-a, który naprawiasz. Commit, `git push` brancha, `gh pr create` z etykietą `mac-worker` (utwórz etykietę, jeśli jej nie ma).
- Edytować notatki vaulta wskazane w zadaniu. Commit tylko swoich plików: `git add <plik> && git commit -m "…"`. Bez `git add -A`. Gdy git zgłosi blokadę indeksu, odczekaj kilka sekund i ponów.
- Używać lokalnej bazy `StrummyLocal` (docker na Macu) do testów.

## Branche
- Reguła trzech branchy (`dev` → `test` → `main`) obowiązuje, ale nie tworzysz gałęzi `dev` ani `test`. PR kieruj do `dev`, jeśli repo już ją ma; w przeciwnym razie do `main` i dopisz w wyniku pod „Czeka na Piotra”: „repo bez dev/test”.

## Nie wolno (bez wyjątków)
- `gh pr merge`, `gh pr review --approve`, merge do `main`, push do `main`, `git push --force` na cudzych branchach.
- `ssh` do jakiegokolwiek hosta (uwh, uwo, wfh, rpi, nas), wdrożenia, migracje na bazach innych niż lokalna.
- Wysyłanie czegokolwiek na zewnątrz: maile, wiadomości, posty, komentarze na GitHubie poza opisem własnego PR-a, płatności, formularze.
- Kasowanie danych, branchy i plików, których sam nie utworzyłeś w tym zadaniu. Sekrety: nie czytaj `.env*` z wartościami produkcyjnymi, nie wypisuj i nie zapisuj żadnych kluczy.
- Zmiany w `~/.claude/`, w hookach, w ustawieniach uprawnień, w `config.json`, w plikach runnera i nadzorcy GPU (`~/bin/home-ops/`, `/usr/local/*/mac-worker/`, `~/Library/LaunchAgents/`) i w plikach stanu innych niż Twój wynik oraz nowe zadania w `queue/` (tylko planista).
- Uruchamianie długich obliczeń (przebiegi wsadowe, modele lokalne po wielu plikach): to robi nadzorca GPU z listy Piotra. Opisz propozycję w wyniku.

## Jak pracować
- Zadanie ma się zmieścić w jednej sesji. Gdy jest za duże, zrób sensowną część i opisz resztę w wyniku jako propozycję kolejnych zadań.
- Gdy potrzebna jest decyzja Piotra, nie zgaduj i nie czekaj: wpisz ją do wyniku w sekcji „Czeka na Piotra” i zakończ albo zrób to, co od tej decyzji nie zależy.
- Przed commitem kodu uruchom lint, typecheck i testy projektu (komendy w `CLAUDE.md` repozytorium). Gdy nie przechodzą, nie otwieraj PR-a; opisz problem w wyniku.
- Nowy PR z nowym kodem: najwyżej 2 otwarte PR-y z etykietą `mac-worker` na projekt (sprawdź `gh pr list --label mac-worker --state open`). Raport z testów ręcznych w `docs/manual-tests/` jak zwykle.
- Po zakończeniu usuń swój worktree (`git worktree remove`), branch zostaje na GitHubie.
- Proste przeszukiwanie zlecaj agentom na tańszym modelu (`model: haiku`), nie na swoim.

## Wynik (obowiązkowo)
Na końcu zapisz plik `~/.local/state/home-ops/sprint/results/<id>.md`:

```markdown
# <id> — <jedno zdanie: co zrobiono>
- Stan: zrobione | częściowo | nie zrobione (dlaczego)
- Zmiany: pliki / commity / PR (linki)
- Sprawdzone: jakie testy przeszły
## Czeka na Piotra
- …
## Propozycje kolejnych zadań
- …
```

Ostatnia wiadomość sesji: jedno zdanie o wyniku.
