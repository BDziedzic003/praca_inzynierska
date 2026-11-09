"""
Serwer pośredniczący między robotem a aplikacjami operatora (telefon, przeglądarka, komputer).

Serwer jest jedynym klientem ESP32-S3 i ESP32-CAM. Aplikacje operatora łączą się
wyłącznie z serwerem:

    ESP32-S3   <--TCP 8080 (komendy, bateria)-->      serwer  <--WebSocket /ws-->   klienci
    ESP32-S3   --UDP 8082 (mikrofon robota)-->         serwer  --WebSocket-->        klienci słuchający
    ESP32-S3   <--UDP 8081 (głośnik robota)--          serwer  <--WebSocket--        klient mówiący
    ESP32-CAM  --HTTP :81/stream (MJPEG)-->            serwer  --HTTP /stream-->     klienci

Dostęp wymaga zalogowania. Konta użytkowników są przechowywane w bazie MongoDB
(uzytkownicy.py); token JWT otrzymany z /api/login (tokeny_jwt.py) jest dołączany do adresów
/ws?token=... i /stream?token=... oraz do zapytań API (nagłówek Authorization: Bearer ...).

API (JSON):
    POST   /api/login                {login, haslo, klient}  -> {token, login, admin}
    POST   /api/logout
    GET    /api/ja                                    -> {login, admin}
    GET    /api/logowania            (administrator)  -> [{login, czas, zdarzenie, adres, klient}]
    GET    /api/uzytkownicy          (administrator)  -> [{login, admin}]
    POST   /api/uzytkownicy          (administrator)  {login, haslo, admin}
    PATCH  /api/uzytkownicy/<login>  (administrator)  {admin} i/lub {haslo}
    DELETE /api/uzytkownicy/<login>  (administrator)

Zasady:
    - sterować mogą wszyscy klienci, telefon może zablokować sterowanie z pozostałych stanowisk,
    - komenda "stop" jest przyjmowana zawsze, także przy aktywnej blokadzie,
    - dźwięk z robota trafia do wszystkich słuchających klientów,
    - mówić do robota może jednocześnie tylko jeden klient; telefon ma pierwszeństwo
      (przerywa mówienie z pozostałych stanowisk), a przy blokadzie pozostałe
      stanowiska nie mogą mówić,
    - ruch zlecony przez klienta jest zatrzymywany, gdy klient przestaje odpowiadać.

Pod adresem http://<serwer>:8000/ udostępniana jest aplikacja webowa (React.js) z folderu
web/dist, a stan serwera pod /status.

Uruchomienie:  python serwer.py   (wymaga działającej bazy MongoDB)
Zależności:    pymongo.
"""

import json
import mimetypes
import os
import queue
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from uzytkownicy import BladUzytkownika, Uzytkownicy
from ws_proste import WebSocket, accept_key

# ==================== USTAWIENIA ====================
S3_HOST = "192.168.1.3"                       # adres IP lub nazwa mDNS ESP32-S3
S3_PORT = 8080

KAMERA_HOST = "192.168.1.4"
KAMERA_STREAM_URL = f"http://{KAMERA_HOST}:81/stream"

# Parametry kamery ustawiane przy każdym połączeniu (/control?var=NAZWA&val=WARTOSC).
CAMERA_SETTINGS = {
    "awb_gain": 0,
    # "quality": 16,    # jakość JPEG 10-63 (większa wartość = mniejsze klatki)
    # "framesize": 5,   # 5 = QVGA 320x240, 8 = VGA 640x480
}
CAMERA_XCLK_MHZ = None               # częstotliwość zegara kamery; None = bez zmian

MONGO_URI = "mongodb://localhost:27017"
MONGO_BAZA = "robot"

PORT_SERWERA = 8000                  # HTTP (obraz) i WebSocket (sterowanie, dźwięk)
AUDIO_PORT_Z_ROBOTA = 8082           # PORT_MIKROFON w konfiguracja.h
AUDIO_PORT_DO_ROBOTA = 8081          # PORT_GLOSNIK w konfiguracja.h

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "dist")   # zbudowana aplikacja React.js

HEARTBEAT_S = 0.2                    # musi być krótszy niż WATCHDOG_MS w konfiguracja.h
RECONNECT_S = 2.0
WATCHDOG_KLIENTA_S = 0.6             # brak wiadomości od sterującego klienta -> zatrzymanie ruchu
TIMEOUT_KLIENTA_S = 5.0              # brak wiadomości -> rozłączenie klienta
STREAM_BUFOR = 32768                 # bufor wysyłania obrazu [B]; mały bufor ogranicza opóźnienie obrazu
STAN_CO_S = 0.5                      # okres rozsyłania stanu do klientów

KOMENDY_JAZDY = {"forward", "backward", "spinleft", "spinright"}
KOMENDY_KAMERY = {"left", "right"}


def log(tekst):
    print(time.strftime("%H:%M:%S"), tekst, flush=True)


# ==================== POŁĄCZENIE Z ESP32-S3 ====================
class PolaczenieS3:
    """Połączenie TCP z ESP32-S3: wysyłanie komend, heartbeat i odbiór raportów."""

    def __init__(self, host, port, on_line, on_connect, on_disconnect):
        self.host = host
        self.port = port
        self.on_line = on_line
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.sock = None
        self.lock = threading.Lock()
        self.connected = False
        self.peer_ip = None
        threading.Thread(target=self._connect_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def _connect_loop(self):
        while True:
            if self.connected:
                time.sleep(0.5)
                continue
            try:
                s = socket.create_connection((self.host, self.port), timeout=3)
                s.settimeout(None)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                with self.lock:
                    self.sock = s
                    self.peer_ip = s.getpeername()[0]
                    self.connected = True
                log(f"Połączono z robotem {self.host}:{self.port} ({self.peer_ip})")
                threading.Thread(target=self._read_loop, args=(s,), daemon=True).start()
                self.on_connect()
            except OSError as e:
                log(f"Brak połączenia z robotem {self.host}:{self.port} ({e}), ponawiam...")
                time.sleep(RECONNECT_S)

    def _heartbeat_loop(self):
        while True:
            if self.connected:
                self.send("ping")
            time.sleep(HEARTBEAT_S)

    def _drop(self, sock, powod):
        with self.lock:
            if self.sock is not sock:
                return
            self.connected = False
            self.sock = None
        try:
            sock.close()
        except OSError:
            pass
        log(f"Utracono połączenie z robotem ({powod})")
        self.on_disconnect()

    def send(self, komenda: str):
        with self.lock:
            sock = self.sock
            if not sock:
                return
            try:
                sock.sendall((komenda + "\n").encode())
                return
            except OSError:
                pass
        self._drop(sock, "błąd wysyłania")

    def _read_loop(self, sock):
        buf = b""
        while True:
            try:
                data = sock.recv(256)
            except OSError:
                break
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.decode(errors="ignore").strip()
                if line:
                    self.on_line(line)
        self._drop(sock, "robot zamknął połączenie")


# ==================== OBRAZ Z KAMERY ====================
class Kamera:
    """Odbiór strumienia MJPEG z ESP32-CAM i udostępnianie najnowszej klatki wielu odbiorcom."""

    def __init__(self, url):
        self.url = url
        self.host = urllib.parse.urlparse(url).hostname
        self.cond = threading.Condition()
        self.klatka = None           # najnowsza klatka JPEG
        self.numer = 0               # licznik klatek (do wykrywania nowej klatki)
        self.fps = 0.0
        self.kb = 0.0
        threading.Thread(target=self._run, daemon=True).start()

    def czekaj_na_klatke(self, ostatni_numer, timeout=2.0):
        """Zwraca (numer, jpeg) nowszej klatki lub (ostatni_numer, None) po upływie czasu."""
        with self.cond:
            self.cond.wait_for(lambda: self.numer != ostatni_numer, timeout)
            if self.numer == ostatni_numer:
                return ostatni_numer, None
            return self.numer, self.klatka

    def _apply_settings(self):
        try:
            if CAMERA_XCLK_MHZ:
                urllib.request.urlopen(f"http://{self.host}/xclk?xclk={CAMERA_XCLK_MHZ}", timeout=2).read()
            for var, val in CAMERA_SETTINGS.items():
                urllib.request.urlopen(f"http://{self.host}/control?var={var}&val={val}", timeout=2).read()
            log(f"Ustawienia kamery wysłane: {CAMERA_SETTINGS}")
        except OSError as e:
            log(f"Nie udało się wysłać ustawień kamery ({e})")

    def _run(self):
        while True:
            try:
                resp = urllib.request.urlopen(self.url, timeout=5)
            except OSError:
                time.sleep(1.0)
                continue

            log("Połączono z kamerą")
            self._apply_settings()
            read = resp.read1 if hasattr(resp, "read1") else (lambda n: resp.read(4096))
            buf = b""
            frames, t0, nbytes = 0, time.time(), 0
            try:
                while True:
                    chunk = read(65536)
                    if not chunk:
                        break
                    buf += chunk

                    # ostatnia kompletna klatka JPEG (znaczniki SOI 0xFFD8 ... EOI 0xFFD9)
                    end = buf.rfind(b"\xff\xd9")
                    if end == -1:
                        if len(buf) > 2_000_000:
                            buf = b""
                        continue
                    start = buf.rfind(b"\xff\xd8", 0, end)
                    jpg = buf[start:end + 2] if start != -1 else None
                    buf = buf[end + 2:]
                    if jpg is None:
                        continue

                    with self.cond:
                        self.klatka = jpg
                        self.numer += 1
                        self.cond.notify_all()

                    frames += 1
                    nbytes += len(jpg)
                    if time.time() - t0 >= 1.0:
                        self.fps = frames / (time.time() - t0)
                        self.kb = nbytes / frames / 1024
                        frames, t0, nbytes = 0, time.time(), 0
            except OSError:
                pass
            finally:
                try:
                    resp.close()
                except OSError:
                    pass
            self.fps = 0.0
            log("Utracono obraz z kamery, ponawiam...")
            time.sleep(0.5)


# ==================== KLIENT (telefon, przeglądarka lub komputer) ====================
class Klient:
    def __init__(self, ws: WebSocket, adres: str, uzytkownik: str):
        self.ws = ws
        self.adres = adres
        self.uzytkownik = uzytkownik  # login zalogowanego użytkownika
        self.rola = "pc"             # "pc", "web" lub "telefon" (ustawiane wiadomością hello)
        self.sluchanie = False       # klient odbiera dźwięk z robota
        self.mowi = False            # klient nadaje dźwięk do robota
        self.ostatnio = time.time()  # czas ostatniej wiadomości od klienta
        # Wysyłanie w osobnym wątku: wolny klient nie blokuje pozostałych.
        self.kolejka = queue.Queue(maxsize=100)
        threading.Thread(target=self._nadawanie, daemon=True).start()

    def __str__(self):
        return f"{self.rola} {self.adres} ({self.uzytkownik})"

    def wyslij(self, msg):
        """msg: str (ramka tekstowa) lub bytes (dźwięk). Przy przepełnionej kolejce wiadomość jest pomijana."""
        try:
            self.kolejka.put_nowait(msg)
        except queue.Full:
            pass

    def _nadawanie(self):
        while not self.ws.zamkniete:
            try:
                msg = self.kolejka.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                if isinstance(msg, bytes):
                    self.ws.send_bytes(msg)
                else:
                    self.ws.send_text(msg)
            except OSError:
                self.ws.close()


# ==================== SERWER ====================
class Serwer:
    def __init__(self, uzytkownicy: Uzytkownicy):
        self.uzytkownicy = uzytkownicy
        self.lock = threading.RLock()
        self.klienci = []
        self.blokada = False                 # sterowanie z pozostałych stanowisk zablokowane przez telefon
        self.wlasciciel_jazdy = None         # klient, który zlecił trwającą jazdę
        self.wlasciciel_kamery = None        # klient, który zlecił trwający obrót kamery
        self.mikrofon = None                 # ostatni stan wysłany komendą mic (None = nieznany)
        self.bateria = None                  # ostatni raport baterii (linia "bat:...")

        self.s3 = PolaczenieS3(S3_HOST, S3_PORT, self._z_robota, self._robot_polaczony, self._robot_rozlaczony)
        self.kamera = Kamera(KAMERA_STREAM_URL)

        self.udp_rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_rx.bind(("", AUDIO_PORT_Z_ROBOTA))
        self.udp_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        threading.Thread(target=self._audio_loop, daemon=True).start()
        threading.Thread(target=self._watchdog_loop, daemon=True).start()
        threading.Thread(target=self._stan_loop, daemon=True).start()

    # ---------- robot ----------
    def _z_robota(self, line):
        if line.startswith("bat:"):
            self.bateria = line
            self._rozeslij(line)
        else:
            log(f"[S3] {line}")

    def _robot_polaczony(self):
        with self.lock:
            self.mikrofon = None
            self._aktualizuj_mikrofon()
        self._rozeslij_stan()

    def _robot_rozlaczony(self):
        with self.lock:
            self.mikrofon = None
            self.wlasciciel_jazdy = None
            self.wlasciciel_kamery = None
        self.bateria = None
        self._rozeslij_stan()

    def _aktualizuj_mikrofon(self):
        """Mikrofon robota nadaje, gdy ktoś słucha i nikt nie mówi do robota (eliminacja echa)."""
        with self.lock:
            on = any(k.sluchanie for k in self.klienci) and not any(k.mowi for k in self.klienci)
            if on != self.mikrofon and self.s3.connected:
                self.s3.send(f"mic:{1 if on else 0}")
                self.mikrofon = on

    def _audio_loop(self):
        """Dźwięk z mikrofonu robota przekazywany do słuchających klientów."""
        while True:
            try:
                data, _ = self.udp_rx.recvfrom(4096)
            except OSError:
                time.sleep(0.1)
                continue
            with self.lock:
                odbiorcy = [k for k in self.klienci if k.sluchanie]
            for k in odbiorcy:
                k.wyslij(data)

    # ---------- klienci ----------
    def obsluz_klienta(self, ws: WebSocket, adres: str, uzytkownik: str):
        k = Klient(ws, adres, uzytkownik)
        with self.lock:
            self.klienci.append(k)
        log(f"Nowy klient: {adres}, użytkownik {uzytkownik}")
        self._wyslij_stan(k)
        if self.bateria:
            k.wyslij(self.bateria)
        try:
            while True:
                msg = ws.recv()
                if msg is None:
                    break
                k.ostatnio = time.time()
                if isinstance(msg, bytes):
                    self._glos_od(k, msg)
                else:
                    for line in msg.split("\n"):
                        if line.strip():
                            self._komenda(k, line.strip())
                    # Natychmiastowa odpowiedź przyspiesza potwierdzenie TCP; system telefonu
                    # (algorytm Nagle'a) nie wstrzymuje wtedy kolejnej komendy w oczekiwaniu na nie.
                    self._wyslij_stan(k)
        finally:
            ws.close()
            self._usun_klienta(k)

    def _usun_klienta(self, k: Klient):
        with self.lock:
            if k in self.klienci:
                self.klienci.remove(k)
            self._zatrzymaj_ruch_klienta(k)
            if k.rola == "telefon" and self.blokada and not any(x.rola == "telefon" for x in self.klienci):
                self.blokada = False
                log("Blokada sterowania zdjęta (brak połączonego telefonu)")
            self._aktualizuj_mikrofon()
        log(f"Klient rozłączony: {k}")
        self._rozeslij_stan()

    def rozlacz_uzytkownika(self, login: str):
        """Rozłączenie wszystkich połączeń danego użytkownika (po usunięciu konta)."""
        with self.lock:
            klienci = [k for k in self.klienci if k.uzytkownik == login]
        for k in klienci:
            k.ws.close()

    def _moze_sterowac(self, k: Klient) -> bool:
        return k.rola == "telefon" or not self.blokada

    def _zatrzymaj_ruch_klienta(self, k: Klient):
        """Zatrzymanie ruchu zleconego przez danego klienta."""
        with self.lock:
            if self.wlasciciel_jazdy is k:
                self.s3.send("drivestop")
                self.wlasciciel_jazdy = None
            if self.wlasciciel_kamery is k:
                self.s3.send("camstop")
                self.wlasciciel_kamery = None

    def _komenda(self, k: Klient, line: str):
        cmd, _, arg = line.partition(":")

        if cmd == "ping":
            return

        if cmd == "hello":
            k.rola = arg if arg in ("telefon", "web") else "pc"
            log(f"Klient {k.adres} ({k.uzytkownik}) przedstawił się jako: {k.rola}")
            self._wyslij_stan(k)
            return

        if cmd == "sluchaj":
            k.sluchanie = arg == "1"
            self._aktualizuj_mikrofon()
            return

        if cmd == "blokada":
            if k.rola != "telefon":
                return
            with self.lock:
                self.blokada = arg == "1"
                if self.blokada:
                    for wl in (self.wlasciciel_jazdy, self.wlasciciel_kamery):
                        if wl is not None and wl.rola != "telefon":
                            self._zatrzymaj_ruch_klienta(wl)
                    for x in self.klienci:
                        if x.rola != "telefon":
                            x.mowi = False
                self._aktualizuj_mikrofon()
            log(f"Blokada sterowania z komputera: {'WŁĄCZONA' if self.blokada else 'wyłączona'}")
            self._rozeslij_stan()
            return

        if cmd == "mow":
            with self.lock:
                if arg != "1":
                    k.mowi = False
                elif k.rola == "telefon":
                    # telefon ma pierwszeństwo: przerywa mówienie pozostałych klientów
                    for x in self.klienci:
                        x.mowi = x is k
                elif self._moze_sterowac(k) and not any(x.mowi for x in self.klienci if x is not k):
                    k.mowi = True
                else:
                    k.mowi = False            # odmowa: mówi inny klient lub aktywna blokada
                self._aktualizuj_mikrofon()
            self._rozeslij_stan()
            return

        if cmd == "stop":                     # zatrzymanie awaryjne jest zawsze dozwolone
            with self.lock:
                self.s3.send("stop")
                self.wlasciciel_jazdy = None
                self.wlasciciel_kamery = None
            return

        if cmd in KOMENDY_JAZDY or cmd in KOMENDY_KAMERY or cmd in ("drivestop", "camstop"):
            if not self._moze_sterowac(k):
                return
            with self.lock:
                self.s3.send(line)
                if cmd in KOMENDY_JAZDY:
                    self.wlasciciel_jazdy = k
                elif cmd == "drivestop":
                    self.wlasciciel_jazdy = None
                elif cmd in KOMENDY_KAMERY:
                    self.wlasciciel_kamery = k
                else:
                    self.wlasciciel_kamery = None
            return

        log(f"Nieznana komenda od {k}: {line}")

    def _glos_od(self, k: Klient, data: bytes):
        """Dźwięk od klienta przekazywany do głośnika robota (tylko od klienta, który ma prawo mówić)."""
        if not k.mowi:
            return
        ip = self.s3.peer_ip if self.s3.connected else None
        if not ip:
            return
        try:
            self.udp_tx.sendto(data, (ip, AUDIO_PORT_DO_ROBOTA))
        except OSError:
            pass

    # ---------- stan ----------
    def _wyslij_stan(self, k: Klient):
        """stan:<robot>:<blokada>:<sterowanie>:<mowi>:<fps>:<kb>
        robot      - 1 gdy serwer jest połączony z ESP32-S3
        blokada    - 1 gdy telefon zablokował sterowanie z komputera
        sterowanie - 1 gdy ten klient może sterować robotem
        mowi       - 1 gdy inny klient nadaje dźwięk do robota
        fps, kb    - liczba klatek na sekundę i średni rozmiar klatki z kamery"""
        mowi = any(x.mowi for x in self.klienci if x is not k)
        k.wyslij(f"stan:{int(self.s3.connected)}:{int(self.blokada)}:{int(self._moze_sterowac(k))}:"
                 f"{int(mowi)}:{self.kamera.fps:.0f}:{self.kamera.kb:.0f}")

    def _rozeslij_stan(self):
        with self.lock:
            klienci = list(self.klienci)
        for k in klienci:
            self._wyslij_stan(k)

    def _rozeslij(self, msg):
        with self.lock:
            klienci = list(self.klienci)
        for k in klienci:
            k.wyslij(msg)

    def _stan_loop(self):
        while True:
            time.sleep(STAN_CO_S)
            self._rozeslij_stan()

    def _watchdog_loop(self):
        while True:
            time.sleep(0.1)
            teraz = time.time()
            with self.lock:
                for wl in {self.wlasciciel_jazdy, self.wlasciciel_kamery} - {None}:
                    if teraz - wl.ostatnio > WATCHDOG_KLIENTA_S:
                        log(f"Brak sygnału od {wl} -> zatrzymanie ruchu")
                        self._zatrzymaj_ruch_klienta(wl)
                martwi = [k for k in self.klienci if teraz - k.ostatnio > TIMEOUT_KLIENTA_S]
            for k in martwi:
                log(f"Klient {k} nie odpowiada - rozłączanie")
                k.ws.close()


# ==================== HTTP / WebSocket ====================
serwer: Serwer = None


class Obsluga(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    # ---------- pomocnicze ----------
    def _sciezka(self):
        url = urllib.parse.urlparse(self.path)
        return url.path.rstrip("/") or "/", urllib.parse.parse_qs(url.query)

    def _token(self):
        """Token z nagłówka Authorization: Bearer ... lub z parametru ?token=..."""
        naglowek = self.headers.get("Authorization", "")
        if naglowek.startswith("Bearer "):
            return naglowek[7:].strip()
        return (self._sciezka()[1].get("token") or [""])[0]

    def _sesja(self):
        try:
            return serwer.uzytkownicy.sesja(self._token())
        except Exception as e:
            log(f"Błąd bazy danych: {e}")
            return None

    def _json(self, kod, dane):
        tresc = json.dumps(dane, ensure_ascii=False).encode()
        self.send_response(kod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(tresc)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(tresc)

    def _blad(self, kod, komunikat):
        self._json(kod, {"blad": komunikat})

    def _cialo(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            dane = json.loads(self.rfile.read(n).decode())
            return dane if isinstance(dane, dict) else {}
        except (ValueError, UnicodeDecodeError):
            return {}

    # ---------- metody HTTP ----------
    def do_GET(self):
        sciezka, _ = self._sciezka()
        if sciezka.startswith("/api/"):
            self._api("GET", sciezka)
            return
        if sciezka in ("/ws", "/stream", "/snapshot"):
            sesja = self._sesja()
            if not sesja:
                self.send_error(401, "Wymagane zalogowanie")
                return
            if sciezka == "/ws":
                self._websocket(sesja)
            elif sciezka == "/stream":
                self._stream()
            else:
                self._snapshot()
            return
        if sciezka == "/status":
            self._status()
        else:
            self._plik(sciezka)

    def do_POST(self):
        self._api("POST", self._sciezka()[0])

    def do_PATCH(self):
        self._api("PATCH", self._sciezka()[0])

    def do_DELETE(self):
        self._api("DELETE", self._sciezka()[0])

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---------- API ----------
    def _api(self, metoda, sciezka):
        dane = self._cialo() if metoda in ("POST", "PATCH") else {}
        u = serwer.uzytkownicy
        try:
            if metoda == "POST" and sciezka == "/api/login":
                adres, klient = self.client_address[0], dane.get("klient")
                wynik = u.zaloguj(dane.get("login"), dane.get("haslo", ""))
                if not wynik:
                    u.zapisz_zdarzenie(dane.get("login"), "nieudane logowanie", adres, klient)
                    time.sleep(0.5)               # spowolnienie prób odgadnięcia hasła
                    self._blad(401, "nieprawidłowy login lub hasło")
                    return
                u.zapisz_zdarzenie(wynik["login"], "logowanie", adres, klient)
                log(f"Zalogowano: {wynik['login']} ({adres}, {klient or '?'})")
                self._json(200, wynik)
                return

            sesja = self._sesja()
            if not sesja:
                self._blad(401, "wymagane zalogowanie")
                return

            if metoda == "POST" and sciezka == "/api/logout":
                u.wyloguj(self._token())
                u.zapisz_zdarzenie(sesja["login"], "wylogowanie", self.client_address[0], dane.get("klient"))
                self._json(200, {"ok": True})
                return
            if metoda == "GET" and sciezka == "/api/ja":
                self._json(200, sesja)
                return

            if not (sciezka.startswith("/api/uzytkownicy") or sciezka == "/api/logowania"):
                self._blad(404, "nieznany adres")
                return
            if not sesja["admin"]:
                self._blad(403, "wymagane uprawnienia administratora")
                return

            if metoda == "GET" and sciezka == "/api/logowania":
                parametry = self._sciezka()[1]
                try:
                    limit = max(1, min(1000, int((parametry.get("limit") or ["200"])[0])))
                except ValueError:
                    limit = 200
                self._json(200, u.historia(limit, (parametry.get("login") or [None])[0]))
                return

            login = urllib.parse.unquote(sciezka[len("/api/uzytkownicy/"):]) if sciezka.startswith("/api/uzytkownicy/") else None
            kto = sesja["login"]
            if metoda == "GET" and login is None:
                self._json(200, u.lista())
            elif metoda == "POST" and login is None:
                u.dodaj(dane.get("login"), dane.get("haslo"), bool(dane.get("admin")))
                log(f"{kto}: dodano użytkownika {dane.get('login')}")
                self._json(201, {"ok": True})
            elif metoda == "PATCH" and login:
                if "admin" in dane:
                    u.ustaw_admin(login, bool(dane["admin"]), kto)
                    log(f"{kto}: {login} - administrator: {bool(dane['admin'])}")
                if "haslo" in dane:
                    u.zmien_haslo(login, dane["haslo"], kto)
                    log(f"{kto}: zmieniono hasło użytkownika {login}")
                self._json(200, {"ok": True})
            elif metoda == "DELETE" and login:
                u.usun(login, kto)
                serwer.rozlacz_uzytkownika(login)
                log(f"{kto}: usunięto użytkownika {login}")
                self._json(200, {"ok": True})
            else:
                self._blad(404, "nieznany adres")
        except BladUzytkownika as e:
            self._blad(e.kod, str(e))
        except Exception as e:
            log(f"Błąd API: {e}")
            self._blad(500, "błąd serwera lub bazy danych")

    def _websocket(self, sesja):
        key = self.headers.get("Sec-WebSocket-Key")
        if not key or "websocket" not in self.headers.get("Upgrade", "").lower():
            self.send_error(400, "Expected WebSocket upgrade")
            return
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept_key(key))
        self.end_headers()
        self.wfile.flush()
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.close_connection = True
        serwer.obsluz_klienta(WebSocket(self.connection, self.rfile, klient=False), self.client_address[0],
                              sesja["login"])

    def _stream(self):
        self.close_connection = True
        # Przy wolniejszym odbiorcy klatki nie gromadzą się w buforze systemu, tylko są pomijane
        self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, STREAM_BUFOR)
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        numer = -1
        try:
            while True:
                numer, jpg = serwer.kamera.czekaj_na_klatke(numer)
                if jpg is None:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpg)
                                 + jpg + b"\r\n")
                self.wfile.flush()
        except OSError:
            pass

    def _snapshot(self):
        jpg = serwer.kamera.klatka
        if jpg is None:
            self.send_error(503, "Brak obrazu z kamery")
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpg)))
        self.end_headers()
        self.wfile.write(jpg)

    def _plik(self, sciezka):
        """Pliki aplikacji webowej (web/dist); bez zbudowanej aplikacji - strona stanu."""
        if sciezka == "/":
            sciezka = "/index.html"
        root = os.path.realpath(WEB_DIR)
        plik = os.path.realpath(os.path.join(root, sciezka.lstrip("/")))
        if not os.path.isfile(os.path.join(root, "index.html")):
            self._status()
            return
        if not plik.startswith(root + os.sep) or not os.path.isfile(plik):
            self.send_error(404, "Not found")
            return
        with open(plik, "rb") as f:
            tresc = f.read()
        typ = mimetypes.guess_type(plik)[0] or "application/octet-stream"
        if plik.endswith(".js"):
            typ = "text/javascript"                # Windows potrafi zwracać błędny typ dla .js
        self.send_response(200)
        self.send_header("Content-Type", typ + ("; charset=utf-8" if typ.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(tresc)))
        self.send_header("Cache-Control", "no-cache" if plik.endswith(".html") else "max-age=86400")
        self.end_headers()
        self.wfile.write(tresc)

    def _status(self):
        with serwer.lock:
            klienci = ", ".join(str(k) for k in serwer.klienci) or "brak"
        tekst = (
            f"Serwer robota\n"
            f"robot (ESP32-S3): {'połączony' if serwer.s3.connected else 'brak połączenia'}\n"
            f"kamera: {serwer.kamera.fps:.0f} fps\n"
            f"bateria: {serwer.bateria or '--'}\n"
            f"blokada sterowania z komputera: {'tak' if serwer.blokada else 'nie'}\n"
            f"klienci: {klienci}\n"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(tekst)))
        self.end_headers()
        self.wfile.write(tekst)


def adres_lokalny():
    """Adres IP komputera w sieci lokalnej (do wpisania w aplikacji na telefonie)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.1.1", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def main(uzytkownicy=None):
    global serwer
    if uzytkownicy is None:
        try:
            uzytkownicy = Uzytkownicy(MONGO_URI, MONGO_BAZA)
        except ImportError:
            sys.exit("Brak biblioteki pymongo: pip install pymongo")
        except Exception as e:
            sys.exit(f"Brak połączenia z bazą MongoDB ({MONGO_URI}): {e}")
    serwer = Serwer(uzytkownicy)
    http = ThreadingHTTPServer(("", PORT_SERWERA), Obsluga)
    http.daemon_threads = True
    log(f"Serwer działa: http://{adres_lokalny()}:{PORT_SERWERA}  (adres do wpisania w aplikacji na telefonie)")
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        serwer.s3.send("mic:0")
        serwer.s3.send("stop")
        log("Serwer zatrzymany")


if __name__ == "__main__":
    main()
