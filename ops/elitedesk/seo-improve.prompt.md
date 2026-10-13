Pracujesz w repozytorium strony gitarawarszawa.pl (Next.js 16, Tailwind v4, TypeScript; treść po polsku). Piotr uczy gry na gitarze dorosłych stacjonarnie na ul. Szwedzkiej (Praga-Północ, Warszawa), tuż przy stacji metra M2 Szwedzka. Strategia: ekspansja fraz lokalnych na prawy brzeg Wisły i linię M2 (Targówek, Bródno, Zacisze, Praga-Południe, Gocław, Wola, Śródmieście) oraz centralne stacje M1 przez przesiadkę na Świętokrzyskiej (Politechnika–Dworzec Gdański). Cel: zebrać dane o popycie z każdej dzielnicy (GSC pokazuje tylko to, co jest w top 100, więc dzielnica bez własnej treści nie daje żadnych danych) i zdobyć uczniów bez płatnych ogłoszeń.

Zadanie: wykonaj hipotezy z sekcji „DO WYKONANIA” briefu (status ready, maks. 3) — każdą jako osobną, małą, mierzalną zmianę. Jeśli sekcja jest pusta, wybierz 1–2 zmiany z analiz i okazji w briefie i powiedz, którą hipotezę realizujesz. Zmiany mają zwiększyć widoczność lub CTR dla konkretnej frazy/strony. Przykłady dozwolonych zmian: title/description strony (app/layout.tsx, lib/site.ts), nowy akapit FAQ, sekcja „Dojazd” z konkretnymi stacjami i czasami, nowy artykuł w /poradnik pod jedną frazę (trasa app/poradnik/[slug], treść w components/article), `areaServed` w lib/schema.ts, linki wewnętrzne. Trzymaj się istniejących wzorców (sprawdź jak zbudowany jest podobny plik, zanim coś dodasz).

Fakty o dojeździe (jedyne źródło liczb — nie dopisuj innych):
- M2 na wschód od Szwedzkiej, po kolei: Targówek Mieszkaniowy, Trocka, Zacisze, Kondratowicza, Bródno (koniec).
- M2 na zachód od Szwedzkiej, po kolei: Dworzec Wileński, Stadion Narodowy, Centrum Nauki Kopernik, Nowy Świat-Uniwersytet, Świętokrzyska (przesiadka na M1), Rondo ONZ, Rondo Daszyńskiego, Płocka, Młynów, Księcia Janusza, Ulrychów, Bemowo.
- Orientacyjny czas: ok. 2 minuty na stację; pisz „ok. X min”, nigdy „dokładnie”, i nie podawaj liczby przystanków.
- Sąsiedzi Szwedzkiej: Dworzec Wileński (jedna stacja na zachód) i Targówek Mieszkaniowy (jedna stacja na wschód). Stadion Narodowy to dwie stacje.
- Praga-Południe/Gocław: tramwajem lub autobusem do Dworca Wileńskiego, potem jedna stacja M2 do Szwedzkiej; nie podawaj minut.

Zasady twarde:
- Zero inline style, wszystko w className z tokenami projektu.
- Pliki < 150 linii, komponenty < 200; bez `any`.
- Nie zmieniaj cen, godzin, adresu, numeru telefonu ani polityki prywatności.
- Nie twórz 5 kopii strony z podmienioną dzielnicą (thin content). Jedna dobra sekcja lub jedna strona-hub dojazdu > wiele płytkich stron.
- Nie dodawaj dzielnic spoza zakresu (Marki/Ząbki dopiero po weryfikacji wizytówki).
- Bramka dla stron lokalnych (dzielnica/stacja): ≥ 300 słów unikalnej treści, konkretne dane lokalne (stacja, czas dojazdu, trasa), własne FAQ, link do cennika i rezerwacji, JSON-LD. Jeśli nie da się tego spełnić, strona dostaje `noindex` albo nie powstaje.
- Każda zmiana ma linię w raporcie HTML: „hipoteza #id → pliki → fraza → sygnał w GSC → kiedy sprawdzić”.
- Przed końcem uruchom `npm run lint`, `npm run typecheck`, `npm test` i popraw błędy.
- Utwórz `docs/manual-tests/<dzisiejsza data>-seo-auto.html` (samowystarczalny HTML): co zmieniono, pod jaką frazę, jak sprawdzić ręcznie, jaki sygnał w GSC potwierdzi skuteczność i kiedy go szukać.
- Nie commituj i nie pushuj — skrypt zrobi to po bramkach. Nie dotykaj .git.

Jeśli nie masz pewności co do faktu (liczby, nazwy, czasu), pomiń go zamiast zgadywać — sędzia odrzuci diff z niezweryfikowanymi liczbami.

Jeśli brief nie uzasadnia żadnej zmiany (szum, brak danych), nie zmieniaj niczego i napisz dlaczego.

Brief:
{{BRIEF}}
