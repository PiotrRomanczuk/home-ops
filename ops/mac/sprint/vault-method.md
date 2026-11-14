# Porządek w notatce projektu (metoda sprintu 2026-11-14)

Cel: sekcja Now ma być krótką listą zadań do wykonania, a nie dziennikiem stanu. Nic nie kasujesz, tylko przenosisz i skracasz. Rubryka klas: `3-Zasoby/analysis/2026-10-19-agent-queue-design.md` §8 (przeczytaj ją najpierw).

## Docelowe sekcje notatki (w tej kolejności, pozostałe sekcje zostają bez zmian)

1. `## Now` — najwyżej 3 otwarte zadania. Każde w jednej linii, do 200 znaków:
   `- [ ] <klasa> <rozmiar> [⛓] [🖥] <data wpisu> <co zrobić> · Akceptacja: <po czym poznać, że zrobione>`
   Klasa: 🔴 💰 🎯 🧹 💡. Rozmiar: S, M, L (XL podziel). Tylko zadania, które da się wykonać bez czekania na Piotra.
2. `## Czeka na Piotra` — merge, wdrożenie, decyzja, ręczny krok, hasło, test na żywo. Jedna linia na pozycję, z linkiem do PR-a albo pliku: `- [ ] <data> <co ma zrobić Piotr> · <link>`.
3. `## Next` — najwyżej 7 zadań, każde z klasą i rozmiarem.
4. `## Later` — reszta zadań, każde z klasą.
5. `## Dziennik` — najnowsze na górze. Tu trafiają: wszystkie odhaczone `[x]` z Now/Next oraz opisy „co zrobiono” wycięte z długich pozycji (pełna treść, bez skracania).

## Zasady

- Długą pozycję „zrobiono A, B, C; zostało D” rozbij: opis A–C idzie do Dziennika z datą, a D staje się zadaniem (Now, Next albo „Czeka na Piotra”).
- Stan PR-a sprawdź: `gh pr view <nr> --repo PiotrRomanczuk/<repo> --json state,mergedAt`. Scalony → pozycja odhaczona, do Dziennika z dopiskiem „scalone <data>”. Otwarty → jedna linia w „Czeka na Piotra”.
- Odhaczaj tylko to, co da się udowodnić (scalony PR, istniejący plik, commit na main). W razie wątpliwości zostaw otwarte.
- Nie wymyślaj zadań. Klasę i rozmiar nadaj na podstawie treści; gdy nie umiesz ocenić klasy, daj 🧹 i dopisz `(klasa do potwierdzenia)`.
- Gdy w Now jest więcej niż 3 zadania wykonalne, zostaw 3 według rubryki (klasa → ⛓ → mniejszy rozmiar), reszta do Next, nadmiar Next do Later.
- Frontmatter: ustaw `updated: 2026-11-14`. Nie zmieniaj `status`, `verdict`, `stream`, `dlaczego_teraz`; propozycje zmian tych pól wpisz do wyniku w „Czeka na Piotra”.
- Wikilinki i linki zostają nietknięte. Treść w języku notatki.

## Kontrola przed commitem

- Policz: liczba otwartych `- [ ]` przed i po w całej notatce. Każda różnica musi być wyjaśniona w wyniku (odhaczone z dowodem albo rozbite).
- `git diff --stat` pokazuje tylko tę notatkę. Żadna linia treści nie zniknęła: `git diff` nie ma usuniętych zdań, których nie ma w nowym miejscu.
- Commit: `git commit <ścieżka notatki> -m "sprint: porządek Now — <projekt>"`. Bez push (robi go podsumowanie).
