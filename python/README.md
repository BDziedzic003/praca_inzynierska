# Serwer i aplikacja operatora na komputer

```
                      ┌──────────── komputer ────────────┐
ESP32-S3  ◄─TCP 8080─►│                                  │◄─WebSocket /ws──► telefon (aplikacja)
ESP32-S3  ─UDP 8082──►│  serwer.py  (port 8000)          │◄─HTTP /stream───  telefon
ESP32-S3  ◄─UDP 8081──│                                  │◄─WebSocket /ws──► gui_controller.py
ESP32-CAM ─HTTP :81──►│                                  │◄─HTTP /stream───  gui_controller.py
                      └──────────────────────────────────┘
```

| Plik | Rola |
|---|---|
| `serwer.py` | jedyny klient robota i kamery; udostępnia sterowanie, obraz i dźwięk aplikacjom |
| `gui_controller.py` | aplikacja na komputer (klient serwera) |
| `audio_robota.py` | odtwarzanie dźwięku z robota w aplikacji na komputer |
| `uzytkownicy.py` | konta użytkowników, uwierzytelnianie i historia logowań w bazie MongoDB |
| `tokeny_jwt.py` | tworzenie i weryfikacja tokenów JWT (HS256) |
| `gui_logowanie.py` | okno logowania i okno zarządzania użytkownikami w aplikacji na komputer |
| `ws_proste.py` | obsługa protokołu WebSocket (biblioteka standardowa) |
| `web/` | aplikacja webowa w React.js (Vite), udostępniana przez serwer pod `http://<serwer>:8000/` |

## Uruchomienie

Wymagana jest baza MongoDB – najprościej MongoDB Community Server zainstalowany jako usługa
Windows (domyślny adres `mongodb://localhost:27017`, ustawiany w `serwer.py` jako `MONGO_URI`;
można też podać adres bazy MongoDB Atlas). Baza `robot` i kolekcje tworzą się same.

```bash
pip install pymongo                                    # serwer
pip install sounddevice numpy opencv-python pillow    # gui_controller.py
python serwer.py                                       # najpierw serwer
python gui_controller.py                               # w drugim oknie terminala
```

Przy pierwszym uruchomieniu, gdy baza jest pusta, serwer tworzy konto **admin** z losowym
hasłem wypisanym w konsoli – hasło należy zapisać i zmienić po pierwszym zalogowaniu
(Użytkownicy → Zmień hasło). Po uruchomieniu wypisuje adres do wpisania
w aplikacji na telefonie. Przy pierwszym uruchomieniu system Windows pyta o dostęp
do sieci – należy zezwolić na sieci prywatne.

Adresy robota i kamery ustawia się na początku `serwer.py` (`S3_HOST`, `KAMERA_HOST`),
adres serwera w aplikacji na komputer – w oknie logowania (zapamiętywany w
`gui_ustawienia.json`). Strona `http://<serwer>:8000/status` pokazuje bieżący stan serwera.

## Aplikacja webowa (React.js)

Wymagany Node.js (LTS). Jednorazowe zbudowanie aplikacji:

```bash
cd web
npm install
npm run build          # wynik w web/dist, serwer udostępnia go automatycznie
```

Po zbudowaniu aplikacja jest dostępna w przeglądarce pod `http://<serwer>:8000/`
(stan serwera: `/status`). Funkcje: logowanie, podgląd kamery, sterowanie klawiaturą
(W/A/S/D, ←/→, T, M, +/-, Esc) lub przyciskami, nasłuch i mówienie do robota, a dla
administratora zakładki „Użytkownicy” i „Historia logowań”. Przeglądarka jest klientem
o takich samych uprawnieniach jak aplikacja na komputer (telefon ma pierwszeństwo).

Mówienie z przeglądarki wymaga dostępu do mikrofonu, który przeglądarki udostępniają
tylko w bezpiecznym kontekście: przez `http://localhost:8000` (na komputerze z serwerem)
lub przez https. Pod adresem `http://192.168...` działa sterowanie, obraz i nasłuch.

Podczas zmian w kodzie: `npm run dev` (adres `http://localhost:5173`, zapytania są
przekazywane do serwer.py na porcie 8000).

## Użytkownicy

| | Użytkownik | Administrator |
|---|---|---|
| Sterowanie, obraz, dźwięk | tak | tak |
| Lista użytkowników, dodawanie, usuwanie | – | tak |
| Nadawanie i odbieranie uprawnień administratora | – | tak |
| Zmiana hasła dowolnego użytkownika | – | tak |

- Hasła są zapisywane jako skrót PBKDF2-HMAC-SHA256 (600 000 iteracji) z losową solą, nigdy
  jawnym tekstem. Skróty utworzone wcześniej z mniejszą liczbą iteracji są przeliczane
  automatycznie przy najbliższym poprawnym logowaniu.
- Polityka haseł: co najmniej 8 znaków (najwyżej 128), hasło różne od loginu i spoza listy
  najpopularniejszych haseł.
- Uwierzytelnianie odbywa się tokenami **JWT** (RFC 7519, podpis HS256). Token zawiera login,
  uprawnienia (`admin`), czas wydania i wygaśnięcia (12 h) oraz unikalny identyfikator `jti`.
  Klucz podpisujący jest losowany przy pierwszym uruchomieniu i przechowywany w kolekcji
  `konfiguracja`, dlatego restart serwera nie wylogowuje użytkowników.
- Serwer sprawdza podpis i ważność tokenu, a dodatkowo listę unieważnionych tokenów
  (kolekcja `uniewaznione`, wpisy dodawane przy wylogowaniu i usuwane automatycznie po
  wygaśnięciu tokenu) oraz wersję tokenów konta.
- Usunięcie konta, zmiana jego uprawnień albo zmiana jego hasła przez administratora
  unieważnia wszystkie wcześniejsze tokeny tego konta – użytkownik musi zalogować się
  ponownie (nowe uprawnienia trafiają do nowego tokenu). Usunięty użytkownik jest od razu rozłączany.
- Nie można usunąć własnego konta, odebrać uprawnień samemu sobie ani usunąć ostatniego administratora.
- Każde logowanie, nieudana próba logowania i wylogowanie jest zapisywane w kolekcji
  `logowania` (login, czas, adres IP, aplikacja: komputer / telefon / przeglądarka).
  Administrator widzi tę historię w aplikacji webowej. Wpisy są usuwane automatycznie
  po 90 dniach (indeks TTL), a usunięcie konta usuwa również jego historię logowań.
- Login: 3–32 znaki (a–z, cyfry, `_ . -`), wielkość liter bez znaczenia.

## API (JSON, `http://<serwer>:8000/api/...`)

Token z `/api/login` przekazuje się w nagłówku `Authorization: Bearer <token>`,
a w adresach obrazu i WebSocket jako parametr `?token=<token>`.

| Metoda i adres | Dostęp | Treść / odpowiedź |
|---|---|---|
| `POST /api/login` | wszyscy | `{login, haslo, klient}` → `{token, login, admin}` |
| `POST /api/logout` | zalogowani | unieważnia token |
| `GET /api/ja` | zalogowani | `{login, admin}` |
| `GET /api/uzytkownicy` | administrator | `[{login, admin}]` |
| `POST /api/uzytkownicy` | administrator | `{login, haslo, admin}` |
| `PATCH /api/uzytkownicy/<login>` | administrator | `{admin}` i/lub `{haslo}` |
| `DELETE /api/uzytkownicy/<login>` | administrator | – |
| `GET /api/logowania?limit=&login=` | administrator | `[{login, czas, zdarzenie, adres, klient}]` |

Błędy zwracane są jako `{"blad": "opis"}` z kodem 400, 401 (brak lub nieważny token),
403 (brak uprawnień administratora), 404 lub 409 (login zajęty).

## Zasady współpracy klientów

| | Telefon | Komputer |
|---|---|---|
| Sterowanie jazdą i kamerą | tak | tak, chyba że telefon włączył blokadę |
| Zatrzymanie awaryjne (STOP / Esc) | tak | zawsze |
| Słuchanie robota | tak | tak |
| Mówienie do robota | tak, przerywa mówienie z komputera | tak, gdy nie mówi telefon i nie ma blokady |
| Blokada sterowania z komputera | włącza i wyłącza | – |

- Blokada jest zdejmowana automatycznie, gdy rozłączy się ostatni telefon.
- Włączenie blokady zatrzymuje ruch zlecony wcześniej z komputera.
- Mikrofon robota jest włączony, gdy co najmniej jeden klient słucha i nikt nie mówi.
- Ruch zlecony przez klienta jest zatrzymywany, gdy klient przez 600 ms nie wysyła
  wiadomości (heartbeat co 200 ms); po 5 s ciszy klient jest rozłączany.
- Serwer wysyła do ESP32-S3 własny heartbeat, więc watchdog robota (600 ms) zatrzymuje
  go również w razie awarii serwera.

## Protokół WebSocket (`ws://<serwer>:8000/ws?token=<token>`)

Klient → serwer (wiadomości tekstowe):

| Wiadomość | Znaczenie |
|---|---|
| `hello:telefon` / `hello:pc` / `hello:web` | przedstawienie się klienta (pierwsza wiadomość) |
| `ping` | heartbeat co 200 ms |
| `forward:<v>`, `backward:<v>`, `spinleft:<v>`, `spinright:<v>`, `drivestop` | jazda |
| `left`, `right`, `camstop` | obrót kamery |
| `stop` | zatrzymanie awaryjne |
| `sluchaj:1` / `sluchaj:0` | odbiór dźwięku z robota |
| `mow:1` / `mow:0` | nadawanie do robota (jeden klient naraz, telefon ma pierwszeństwo) |
| `blokada:1` / `blokada:0` | blokada sterowania z komputera (tylko telefon) |

Wiadomości binarne od klienta, który ma prawo mówić, to próbki PCM przekazywane do głośnika robota.

Serwer → klient:

| Wiadomość | Znaczenie |
|---|---|
| `bat:<V>:<%>:<stan>` | raport baterii z ESP32-S3 (co 1 s) |
| `stan:<robot>:<blokada>:<sterowanie>:<mowi>:<fps>:<kb>` | stan serwera (co 0,5 s i po każdej zmianie) |
| wiadomość binarna | próbki PCM z mikrofonu robota (16 kHz, 16 bit, mono, 512 próbek) |
