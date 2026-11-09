# System zdalnego sterowania robotem ratowniczym

Praca inżynierska: *System zdalnego sterowania robotem ratowniczym do eksploracji trudno dostępnych przestrzeni*.

Gąsienicowy robot z kamerą, mikrofonem i głośnikiem jest sterowany przez sieć Wi-Fi z trzech aplikacji:
mobilnej (Android), webowej (przeglądarka) i okienkowej (komputer). Wszystkie aplikacje łączą się
z serwerem w Pythonie, który jako jedyny komunikuje się z robotem.

```
                 sieć Wi-Fi (router)
 ┌─────── robot ───────┐        ┌──── komputer ────┐        ┌──── operatorzy ────┐
 │ ESP32-S3  (napęd,   │◄─TCP──►│                  │◄──────►│ telefon (Android)  │
 │  serwo, audio,      │◄─UDP──►│  serwer.py :8000 │◄──────►│ przeglądarka       │
 │  bateria)           │        │                  │◄──────►│ aplikacja na PC    │
 │ ESP32-CAM (obraz)   │─HTTP──►│     MongoDB      │        └────────────────────┘
 └─────────────────────┘        └──────────────────┘
```

## Struktura repozytorium

| Folder | Zawartość |
|---|---|
| `arduino/` | oprogramowanie mikrokontrolerów: szkic ESP32-S3 (`s3.ino`) i szkic ESP32-CAM (`CameraWebServer.ino`) |
| `python/` | serwer (`serwer.py`), aplikacja okienkowa na komputer (`gui_controller.py`), obsługa użytkowników i tokenów JWT – szczegóły w [`python/README.md`](python/README.md) |
| `python/web/` | aplikacja webowa (React.js + Vite) udostępniana przez serwer |
| `react/robot-app/` | aplikacja mobilna (React Native + Expo, Android) – szczegóły w [`react/robot-app/README.md`](react/robot-app/README.md) |

## Wymagania

| Element | Wymagane oprogramowanie |
|---|---|
| Mikrokontrolery | Arduino IDE 2, pakiet płytek **esp32 by Espressif Systems** (wersja 3.x), biblioteka **ESP32Servo** |
| Serwer i aplikacja na PC | Python 3 (3.9 lub nowszy), **MongoDB Community Server** |
| Aplikacja webowa | Node.js (wersja LTS) |
| Aplikacja mobilna | Node.js (LTS) oraz Android Studio z Android SDK (budowanie lokalne) lub konto expo.dev (budowanie w chmurze) |

Wszystkie urządzenia (robot, komputer z serwerem, telefon) muszą być w tej samej sieci Wi-Fi.

## Konfiguracja

| Co | Gdzie |
|---|---|
| Nazwa i hasło sieci Wi-Fi robota | `arduino/.../konfiguracja.h` (`WIFI_SSID`, `WIFI_HASLO`) oraz `CameraWebServer.ino` (`ssid`, `password`) |
| Kalibracja pomiaru baterii | `konfiguracja.h` (`BAT_KALIBRACJA`) |
| Adresy robota i kamery | `python/serwer.py` (`S3_HOST`, `KAMERA_HOST`) – dla kamery najlepiej ustawić stały adres (rezerwację DHCP) w routerze |
| Adres bazy danych | `python/serwer.py` (`MONGO_URI`, domyślnie `mongodb://localhost:27017`) |

> Repozytorium zawiera hasło do sieci Wi-Fi robota, dlatego powinno pozostać **prywatne**.

## Uruchomienie – kolejność

1. Włączyć router i zasilanie robota.
2. Sprawdzić, czy działa usługa MongoDB (instaluje się jako usługa Windows i startuje automatycznie).
3. Uruchomić serwer.
4. Uruchomić dowolne aplikacje operatora i zalogować się.

### 1. Mikrokontrolery (jednorazowo, po zmianach w kodzie)

**ESP32-S3-Pico** – otworzyć `s3.ino` w Arduino IDE, wybrać płytkę **ESP32S3 Dev Module**
(Flash Size 16MB, PSRAM: QSPI PSRAM), port COM płytki i wgrać szkic.

**ESP32-CAM** – otworzyć `CameraWebServer.ino`, wybrać płytkę **AI Thinker ESP32-CAM**.
Moduł programuje się przez konwerter USB–UART: przed wgraniem zewrzeć GPIO0 z GND
i zresetować moduł, po wgraniu rozewrzeć i zresetować ponownie.

Po starcie oba moduły wypisują w Monitorze portu szeregowego (115200) swój adres IP.

### 2. Serwer

```powershell
cd python
pip install pymongo
python serwer.py
```

- Serwer wypisuje adres, np. `Serwer działa: http://192.168.1.10:8000` – ten adres wpisuje się w aplikacjach.
- Przy **pierwszym uruchomieniu** (pusta baza) tworzone jest konto `admin` z losowym hasłem
  wypisanym w konsoli. Hasło należy zapisać i zmienić po zalogowaniu.
- Przy pierwszym uruchomieniu Windows pyta o dostęp do sieci – należy zezwolić dla sieci prywatnych.
- Stan serwera: `http://<adres serwera>:8000/status`.

### 3. Aplikacja webowa

Jednorazowo (i po każdej zmianie w kodzie aplikacji) trzeba ją zbudować:

```powershell
cd python\web
npm install
npm run build
```

Serwer sam udostępnia zbudowaną aplikację – wystarczy otworzyć w przeglądarce
`http://<adres serwera>:8000/`.

- Mówienie do robota z przeglądarki działa tylko pod adresem `http://localhost:8000`
  (na komputerze z serwerem) – przeglądarki udostępniają mikrofon tylko w bezpiecznym kontekście.
  Pod adresem IP działa sterowanie, obraz i nasłuch.
- Tryb deweloperski (zmiany widoczne od razu): `npm run dev`, adres `http://localhost:5173`.

### 4. Aplikacja na komputer

```powershell
cd python
pip install sounddevice numpy opencv-python pillow
python gui_controller.py
```

W oknie logowania podać adres serwera (`localhost`, jeśli serwer działa na tym samym komputerze),
port `8000`, login i hasło.

### 5. Aplikacja mobilna (Android)

Aplikacja ma własny moduł natywny, dlatego **nie działa w Expo Go** – trzeba zbudować plik APK.

```powershell
cd react\robot-app
npm install
```

**Wariant A – lokalnie** (telefon podłączony przez USB z włączonym debugowaniem USB, Android Studio z SDK):

```powershell
npx expo run:android --variant release
```

Polecenie buduje aplikację i instaluje ją na telefonie; działa ona bez połączenia z komputerem.
Do pracy nad kodem służy `npx expo run:android` (wersja deweloperska, wymaga uruchomionego
na komputerze serwera Metro, który polecenie włącza samo).

**Wariant B – w chmurze Expo** (bez Android Studio):

```powershell
npm install -g eas-cli
eas login
eas build -p android --profile preview
```

Po zakończeniu EAS podaje link do pliku APK do pobrania i zainstalowania na telefonie.

W aplikacji na ekranie logowania podać adres IP serwera, port `8000`, login i hasło.
Przy pierwszym uruchomieniu aplikacja prosi o dostęp do mikrofonu.

## Obsługa

| Działanie | Telefon | Przeglądarka / komputer |
|---|---|---|
| Jazda | przyciski ▲ ▼ ◀ ▶ (przytrzymanie) | `W` `S` `A` `D` lub przyciski |
| Obrót kamery | przyciski ⟲ ⟳ | `←` `→` |
| Prędkość jazdy | przyciski − / + | `-` / `+` |
| Mówienie do robota | 🎤 Mów (przytrzymanie) | `T` (przytrzymanie) |
| Nasłuch włącz / wyłącz | 🔊 / 🔇 | `M` |
| Zatrzymanie awaryjne | STOP | `Esc` |
| Blokada sterowania z innych stanowisk | Zablokuj PC | – |
| Zarządzanie użytkownikami (administrator) | 👥 Użytkownicy | zakładka „Użytkownicy” / okno użytkowników |
| Historia logowań (administrator) | – | zakładka „Historia logowań” (przeglądarka) |

Zasady współpracy stanowisk:

- telefon ma pierwszeństwo – może zablokować sterowanie z komputera i przeglądarki,
- zatrzymanie awaryjne działa zawsze, także przy blokadzie,
- robota mogą słuchać wszyscy, mówić – jeden operator naraz (telefon przerywa innych),
- robot zatrzymuje się, gdy przez 600 ms nie dostaje komend (utrata łączności, awaria aplikacji lub serwera),
- przy krytycznie niskim napięciu baterii (poniżej 10,8 V przez 5 s) jazda jest blokowana.

## Porty

| Port | Protokół | Zastosowanie |
|---|---|---|
| 8000 | HTTP / WebSocket | serwer – API, obraz, sterowanie, dźwięk, aplikacja webowa |
| 8080 | TCP | ESP32-S3 – komendy i raporty baterii |
| 8081 / 8082 | UDP | dźwięk do robota / z robota |
| 80 / 81 | HTTP | ESP32-CAM – ustawienia kamery / strumień MJPEG |
| 27017 | MongoDB | baza danych (tylko lokalnie) |

## Najczęstsze problemy

| Objaw | Rozwiązanie |
|---|---|
| Serwer kończy działanie z komunikatem „Brak połączenia z bazą MongoDB” | uruchomić usługę MongoDB (Usługi Windows → MongoDB Server) |
| Aplikacje nie łączą się z serwerem | sprawdzić, czy urządzenia są w tej samej sieci i czy Zapora Windows przepuszcza Pythona w sieci prywatnej |
| Brak obrazu z kamery | sprawdzić `KAMERA_HOST` w `serwer.py` i zasilanie ESP32-CAM (przy spadkach napięcia moduł się restartuje) |
| W przeglądarce nie da się mówić | otworzyć aplikację przez `http://localhost:8000` na komputerze z serwerem |
| Telefon: „main has not been registered” lub brak biblioteki | `npm install`, `npx expo install --fix`, ponownie zbudować aplikację |
| Pod adresem `:8000/` brak aplikacji webowej | zbudować ją: `npm run build` w `python\web` |

## Testy

```powershell
cd react\robot-app
npm test          # testy logiki protokołu i przetwarzania dźwięku
```
