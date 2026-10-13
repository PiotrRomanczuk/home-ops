Pracujesz w repozytorium strony gitarawarszawa.pl (Next.js 16, Tailwind v4, TypeScript; treść po polsku). Piotr uczy gry na gitarze dorosłych stacjonarnie na ul. Szwedzkiej (Praga-Północ, Warszawa), 100 m od metra M2 Szwedzka. Strategia: ekspansja fraz lokalnych na prawy brzeg Wisły i linię M2 (Targówek, Bródno, Zacisze, Praga-Południe, Gocław, Wola, Śródmieście) oraz centralne stacje M1 przez przesiadkę na Świętokrzyskiej (Politechnika–Dworzec Gdański). Cel: zebrać dane o popycie z każdej dzielnicy (GSC pokazuje tylko to, co jest w top 100, więc dzielnica bez własnej treści nie daje żadnych danych) i zdobyć uczniów bez płatnych ogłoszeń.

Zadanie: na podstawie poniższego briefu z ostatniego tygodnia wprowadź w repo 1–3 konkretne, małe zmiany, które najbardziej zwiększą widoczność lub CTR. Przykłady dozwolonych zmian: title/description strony (app/layout.tsx, lib/site.ts), nowy akapit FAQ, sekcja „Dojazd” z konkretnymi stacjami i czasami, nowy artykuł w /poradnik pod jedną frazę (trasa app/poradnik/[slug], treść w components/article), `areaServed` w lib/schema.ts, linki wewnętrzne. Trzymaj się istniejących wzorców (sprawdź jak zbudowany jest podobny plik, zanim coś dodasz).

Zasady twarde:
- Zero inline style, wszystko w className z tokenami projektu.
- Pliki < 150 linii, komponenty < 200; bez `any`.
- Nie zmieniaj cen, godzin, adresu, numeru telefonu ani polityki prywatności.
- Nie twórz 5 kopii strony z podmienioną dzielnicą (thin content). Jedna dobra sekcja lub jedna strona-hub dojazdu > wiele płytkich stron.
- Nie dodawaj dzielnic spoza zakresu (Marki/Ząbki dopiero po weryfikacji wizytówki).
- Przed końcem uruchom `npm run lint`, `npm run typecheck`, `npm test` i popraw błędy.
- Utwórz `docs/manual-tests/<dzisiejsza data>-seo-auto.html` (samowystarczalny HTML): co zmieniono, pod jaką frazę, jak sprawdzić ręcznie, jaki sygnał w GSC potwierdzi skuteczność i kiedy go szukać.
- Nie commituj i nie pushuj — skrypt zrobi to po bramkach. Nie dotykaj .git.

Jeśli brief nie uzasadnia żadnej zmiany (szum, brak danych), nie zmieniaj niczego i napisz dlaczego.

Brief:
{{BRIEF}}
