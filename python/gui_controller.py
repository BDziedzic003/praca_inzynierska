"""
Aplikacja operatora na komputer: podgląd z kamery, sterowanie z klawiatury,
dwukierunkowa łączność głosowa i wskaźnik stanu baterii.

Aplikacja łączy się z serwerem (serwer.py), który musi być uruchomiony wcześniej.
Korzystanie wymaga zalogowania; administrator ma dodatkowo dostęp do zarządzania
użytkownikami (przycisk „Użytkownicy”). Telefon ma pierwszeństwo: może zablokować
sterowanie z komputera i przerwać mówienie z komputera. Do robota może jednocześnie
mówić tylko jeden operator.

Sterowanie:
    W/A/S/D      - jazda (przód / tył / obrót w lewo / obrót w prawo)
    Strzałki L/P - obrót kamery (serwo)
    T            - nadawanie głosu do robota (przytrzymanie)
    M            - włączenie / wyłączenie nasłuchu
    +/-          - zmiana prędkości jazdy
    Esc          - zatrzymanie awaryjne (działa także przy blokadzie)

Zabezpieczenia:
    - heartbeat "ping" co 200 ms; serwer zatrzymuje ruch po 600 ms bez wiadomości
    - utrata fokusu okna powoduje zatrzymanie robota

Zależności: opencv-python, pillow, sounddevice, numpy.
"""

import queue
import threading
import time
import tkinter as tk
import urllib.request

import cv2
import numpy as np
from PIL import Image, ImageTk

import ws_proste
from audio_robota import AudioRobota
from gui_logowanie import BladApi, OknoUzytkownikow, api, zaloguj

# ==================== USTAWIENIA ====================
SERWER_HOST = "127.0.0.1"     # domyślny adres serwera w oknie logowania
SERWER_PORT = 8000

# Obrót obrazu wynikający z orientacji kamery w obudowie.
CAMERA_ROTATION = cv2.ROTATE_90_COUNTERCLOCKWISE

DISPLAY_MAX_W = 640
DISPLAY_MAX_H = 640

MIN_SPEED = 40
MAX_SPEED = 255
SPEED_STEP = 20
DEFAULT_SPEED = 150

RECONNECT_INTERVAL_S = 2.0
HEARTBEAT_INTERVAL_S = 0.2


# ==================== POŁĄCZENIE Z SERWEREM ====================
class KlientSerwera:
    """Połączenie WebSocket z serwerem: komendy, heartbeat, stan robota i dźwięk."""

    def __init__(self, host, port, token, on_audio):
        self.host = host
        self.port = port
        self.token = token
        self.sesja_wygasla = False   # serwer odrzucił token (np. usunięte konto)
        self.on_audio = on_audio
        self.ws = None
        self.connected = False
        self._stop = False
        self.sluchanie = True
        # stan otrzymywany od serwera
        self.robot = False
        self.blokada = False
        self.sterowanie = True
        self.inny_mowi = False       # inny klient mówi do robota
        self.fps = 0
        self.kb = 0
        self.battery = None          # (napięcie, procent, stan, czas odbioru)
        threading.Thread(target=self._connect_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def _connect_loop(self):
        while not self._stop:
            try:
                ws = ws_proste.connect(self.host, self.port, f"/ws?token={self.token}")
            except OSError as e:
                if " 401 " in str(e):
                    self.sesja_wygasla = True
                print(f"Brak połączenia z serwerem {self.host}:{self.port} ({e}), ponawiam...")
                time.sleep(RECONNECT_INTERVAL_S)
                continue
            self.ws = ws
            self.sesja_wygasla = False
            self.connected = True
            print(f"Połączono z serwerem {self.host}:{self.port}")
            self.send("hello:pc")
            self.send(f"sluchaj:{1 if self.sluchanie else 0}")
            self._read_loop(ws)
            self.connected = False
            self.ws = None
            self.robot = False
            if not self._stop:
                print("Utracono połączenie z serwerem, ponawiam...")
                time.sleep(RECONNECT_INTERVAL_S)

    def _heartbeat_loop(self):
        while not self._stop:
            if self.connected:
                self.send("ping")
            time.sleep(HEARTBEAT_INTERVAL_S)

    def send(self, komenda: str):
        ws = self.ws
        if ws is None:
            return
        try:
            ws.send_text(komenda)
        except OSError:
            ws.close()

    def send_bytes(self, data: bytes):
        ws = self.ws
        if ws is None or not self.connected:
            return
        try:
            ws.send_bytes(data)
        except OSError:
            ws.close()

    def set_sluchanie(self, on: bool):
        self.sluchanie = on
        self.send(f"sluchaj:{1 if on else 0}")

    def close(self):
        self._stop = True
        if self.ws:
            self.ws.close()

    def _read_loop(self, ws):
        while not self._stop:
            msg = ws.recv()
            if msg is None:
                break
            if isinstance(msg, bytes):
                self.on_audio(msg)
                continue
            for line in msg.split("\n"):
                self._line(line.strip())

    def _line(self, line):
        pola = line.split(":")
        try:
            if pola[0] == "bat" and len(pola) == 4:
                self.battery = (float(pola[1]), int(pola[2]), pola[3], time.time())
            elif pola[0] == "stan" and len(pola) == 7:
                self.robot = pola[1] == "1"
                self.blokada = pola[2] == "1"
                self.sterowanie = pola[3] == "1"
                self.inny_mowi = pola[4] == "1"
                self.fps = int(pola[5])
                self.kb = int(pola[6])
                if not self.robot:
                    self.battery = None
            elif line:
                print(f"[serwer] {line}")
        except ValueError:
            pass


# ==================== ODBIÓR OBRAZU (MJPEG przez HTTP) ====================
class CameraStream:
    """Odbiór strumienia MJPEG udostępnianego przez serwer.

    Z bufora wybierana jest zawsze najnowsza kompletna klatka JPEG,
    co minimalizuje opóźnienie obrazu.
    """

    def __init__(self, url, frame_queue: queue.Queue):
        self.url = url
        self.frame_queue = frame_queue
        self._stop = False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self._stop:
            try:
                resp = urllib.request.urlopen(self.url, timeout=5)
            except OSError:
                time.sleep(1.0)
                continue

            read = resp.read1 if hasattr(resp, "read1") else (lambda n: resp.read(4096))
            buf = b""
            try:
                while not self._stop:
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

                    frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is None:
                        continue

                    if CAMERA_ROTATION is not None:
                        frame = cv2.rotate(frame, CAMERA_ROTATION)

                    h, w = frame.shape[:2]
                    scale = min(DISPLAY_MAX_W / w, DISPLAY_MAX_H / h)
                    if abs(scale - 1.0) > 0.01:
                        frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)

                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    if self.frame_queue.full():
                        try:
                            self.frame_queue.get_nowait()
                        except queue.Empty:
                            pass
                    self.frame_queue.put(rgb_frame)
            except OSError:
                pass
            finally:
                try:
                    resp.close()
                except OSError:
                    pass
            time.sleep(0.5)

    def stop(self):
        self._stop = True


# ==================== GUI ====================
class RobotControllerGUI:
    def __init__(self, root, sesja):
        self.root = root
        self.sesja = sesja               # {host, port, token, login, admin}
        self.host = sesja["host"]
        self.port = sesja["port"]
        self.wylogowano = False
        self.talk_denied_until = 0.0
        self.okno_uzytkownikow = None
        root.title("Sterowanie robotem")
        root.configure(bg="#121212")

        self.speed = DEFAULT_SPEED
        self.pressed_keys = set()

        self.audio = AudioRobota(lambda data: self.client.send_bytes(data))
        if self.audio.error:
            print(f"Audio niedostępne: {self.audio.error}")
        self.client = KlientSerwera(self.host, self.port, sesja["token"], self.audio.feed)
        self.frame_queue = queue.Queue(maxsize=1)
        self.camera_stream = CameraStream(f"http://{self.host}:{self.port}/stream?token={sesja['token']}",
                                          self.frame_queue)

        self._build_ui()
        self._bind_keys()

        self.root.focus_force()

        self.root.after(30, self._poll_camera_frame)
        self.root.after(500, self._update_status)

        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- interfejs ----------
    def _build_ui(self):
        style = {"bg": "#121212", "fg": "#FFFFFF"}

        user_frame = tk.Frame(self.root, bg="#121212")
        user_frame.pack(fill="x", padx=10, pady=(8, 0))
        rola = "administrator" if self.sesja["admin"] else "użytkownik"
        tk.Label(user_frame, text=f"👤 {self.sesja['login']} ({rola})", **style,
                 font=("Segoe UI", 10)).pack(side="left")
        tk.Button(user_frame, text="Wyloguj", takefocus=0, command=self._logout).pack(side="right")
        if self.sesja["admin"]:
            tk.Button(user_frame, text="Użytkownicy", takefocus=0,
                      command=self._show_users).pack(side="right", padx=5)

        self.status_label = tk.Label(self.root, text="Łączenie...", **style, font=("Segoe UI", 11))
        self.status_label.pack(pady=(10, 5))

        self.lock_label = tk.Label(self.root, text="", **style, font=("Segoe UI", 11, "bold"))
        self.lock_label.pack(pady=(0, 5))

        self.battery_label = tk.Label(self.root, text="Bateria: --", **style, font=("Segoe UI", 12, "bold"))
        self.battery_label.pack(pady=(0, 5))

        self.audio_label = tk.Label(self.root, text="Audio: --", **style, font=("Segoe UI", 11))
        self.audio_label.pack(pady=(0, 5))

        vol_frame = tk.Frame(self.root, bg="#121212")
        vol_frame.pack(pady=(0, 5))
        tk.Label(vol_frame, text="Głośność u mnie [%]:", **style, font=("Segoe UI", 10)).grid(row=0, column=0, padx=5)
        self.listen_scale = tk.Scale(vol_frame, from_=0, to=300, resolution=10, orient="horizontal", length=180,
                                     bg="#121212", fg="#FFFFFF", highlightthickness=0, troughcolor="#333333",
                                     takefocus=0,
                                     command=lambda v: setattr(self.audio, "listen_gain", int(v) / 100))
        self.listen_scale.set(int(self.audio.listen_gain * 100))
        self.listen_scale.grid(row=0, column=1)
        tk.Label(vol_frame, text="Głośność robota [%]:", **style, font=("Segoe UI", 10)).grid(row=0, column=2, padx=(20, 5))
        self.talk_scale = tk.Scale(vol_frame, from_=50, to=800, resolution=25, orient="horizontal", length=180,
                                   bg="#121212", fg="#FFFFFF", highlightthickness=0, troughcolor="#333333",
                                   takefocus=0,
                                   command=lambda v: setattr(self.audio, "talk_gain", int(v) / 100))
        self.talk_scale.set(int(self.audio.talk_gain * 100))
        self.talk_scale.grid(row=0, column=3)

        # zwolnienie fokusu suwaka, aby klawisze strzałek sterowały kamerą
        for sc in (self.listen_scale, self.talk_scale):
            sc.bind("<ButtonRelease-1>", lambda e: self.root.focus_set())

        self.video_label = tk.Label(self.root, bg="#000000", text="Brak obrazu z kamery",
                                    fg="#888888", font=("Segoe UI", 11))
        self.video_label.pack(padx=10, pady=10)

        speed_frame = tk.Frame(self.root, bg="#121212")
        speed_frame.pack(pady=(0, 10))

        tk.Label(speed_frame, text="Prędkość:", **style, font=("Segoe UI", 12)).pack(side="left", padx=5)
        tk.Button(speed_frame, text="−", width=3, command=lambda: self._adjust_speed(-SPEED_STEP),
                  takefocus=0).pack(side="left")
        self.speed_value_label = tk.Label(speed_frame, text=str(self.speed), **style,
                                          font=("Segoe UI", 14, "bold"), width=4)
        self.speed_value_label.pack(side="left", padx=5)
        tk.Button(speed_frame, text="+", width=3, command=lambda: self._adjust_speed(SPEED_STEP),
                  takefocus=0).pack(side="left")

        help_text = ("W/A/S/D = jazda   |   ← / → = kamera   |   T = mów (trzymaj)   |   M = słuchanie wł./wył.   |   "
                     "+/- = prędkość   |   Esc = STOP")
        tk.Label(self.root, text=help_text, **style, font=("Segoe UI", 9)).pack(pady=(0, 10))

    # ---------- klawiatura ----------
    def _bind_keys(self):
        self.root.bind("<KeyPress>", self._on_key_press)
        self.root.bind("<KeyRelease>", self._on_key_release)
        self.root.bind("<FocusOut>", self._on_focus_out)

    def _on_key_press(self, event):
        key = event.keysym.lower()

        if key in self.pressed_keys:
            return  # pominięcie autopowtarzania klawisza

        self.pressed_keys.add(key)

        if key == "w":
            self.client.send(f"forward:{self.speed}")
        elif key == "s":
            self.client.send(f"backward:{self.speed}")
        elif key == "a":
            self.client.send(f"spinleft:{self.speed}")
        elif key == "d":
            self.client.send(f"spinright:{self.speed}")
        elif key == "left":
            self.client.send("right")  # kierunek odwrócony zgodnie z montażem serwa
        elif key == "right":
            self.client.send("left")
        elif key in ("plus", "equal", "kp_add"):
            self._adjust_speed(SPEED_STEP)
        elif key in ("minus", "kp_subtract"):
            self._adjust_speed(-SPEED_STEP)
        elif key == "t":
            self._set_talking(True)
        elif key == "m":
            self.audio.set_listening(not self.audio.listening)
            self.client.set_sluchanie(self.audio.listening)
        elif key == "escape":
            self.client.send("stop")

    def _on_key_release(self, event):
        key = event.keysym.lower()
        self.pressed_keys.discard(key)

        if key in ("w", "s", "a", "d"):
            # powrót do ruchu odpowiadającego innemu wciśniętemu klawiszowi lub zatrzymanie
            for k, cmd in (("w", "forward"), ("s", "backward"), ("a", "spinleft"), ("d", "spinright")):
                if k in self.pressed_keys:
                    self.client.send(f"{cmd}:{self.speed}")
                    break
            else:
                self.client.send("drivestop")
        elif key == "t":
            self._set_talking(False)
        elif key in ("left", "right"):
            if "left" in self.pressed_keys:
                self.client.send("right")  # kierunek odwrócony zgodnie z montażem serwa
            elif "right" in self.pressed_keys:
                self.client.send("left")
            else:
                self.client.send("camstop")

    def _on_focus_out(self, event):
        # FocusOut występuje także przy zmianie fokusu wewnątrz okna,
        # dlatego stan fokusu aplikacji sprawdzany jest z opóźnieniem.
        self.root.after(50, self._check_focus)

    def _check_focus(self):
        # Po utracie fokusu zdarzenia zwolnienia klawiszy nie docierają do aplikacji,
        # więc robot jest zatrzymywany.
        try:
            has_focus = self.root.focus_get() is not None
        except (KeyError, tk.TclError):
            has_focus = False
        if has_focus:
            return
        if self.audio.talking:
            self._set_talking(False)
        if self.pressed_keys:
            self.pressed_keys.clear()
            self.client.send("stop")
            print("Okno straciło fokus -> STOP")

    # ---------- mówienie ----------
    def _set_talking(self, on):
        if on and (self.audio.error or not self.client.connected):
            return
        if on and (self.client.inny_mowi or not self.client.sterowanie):
            self.talk_denied_until = time.time() + 2.0      # komunikat o odmowie przez 2 s
            return
        if on == self.audio.talking:
            return
        self.audio.set_talking(on)
        self.client.send(f"mow:{1 if on else 0}")

    def _adjust_speed(self, delta):
        self.speed = max(MIN_SPEED, min(MAX_SPEED, self.speed + delta))
        self.speed_value_label.config(text=str(self.speed))

        # aktualizacja prędkości trwającego ruchu
        for k, cmd in (("w", "forward"), ("s", "backward"), ("a", "spinleft"), ("d", "spinright")):
            if k in self.pressed_keys:
                self.client.send(f"{cmd}:{self.speed}")
                break

    # ---------- kamera ----------
    def _poll_camera_frame(self):
        try:
            rgb_frame = self.frame_queue.get_nowait()
            photo = ImageTk.PhotoImage(Image.fromarray(rgb_frame))
            self.video_label.configure(image=photo, text="")
            self.video_label.image = photo  # referencja chroniąca obraz przed usunięciem
        except queue.Empty:
            pass
        except Exception as e:
            print(f"Błąd wyświetlania klatki: {e}")

        self.root.after(30, self._poll_camera_frame)

    # ---------- status ----------
    def _update_status(self):
        c = self.client
        adres = f"{self.host}:{self.port}"
        if c.sesja_wygasla:
            self.status_label.config(text="Sesja wygasła lub konto usunięto – wyloguj się i zaloguj ponownie",
                                     fg="#F44336")
        elif not c.connected:
            self.status_label.config(text=f"Łączenie z serwerem {adres}...", fg="#F44336")
        elif not c.robot:
            self.status_label.config(text=f"Serwer {adres}: brak połączenia z robotem", fg="#FFC107")
        else:
            cam = f"kamera: {c.fps} fps, {c.kb} KB/klatkę" if c.fps else "kamera: brak obrazu"
            self.status_label.config(text=f"Połączono z robotem przez serwer {adres}   |   {cam}", fg="#4CAF50")

        if c.connected and not c.sterowanie:
            self.lock_label.config(text="🔒 Sterowanie przejął telefon – komputer może tylko zatrzymać robota (Esc)",
                                   fg="#121212", bg="#FFC107")
        else:
            self.lock_label.config(text="", bg="#121212")

        self._update_battery()
        self._update_audio()
        self.root.after(200, self._update_status)

    def _update_audio(self):
        self.audio.update_level()
        # serwer przerywa mówienie, gdy telefon zaczyna mówić lub włącza blokadę
        if self.audio.talking and (self.client.inny_mowi or not self.client.sterowanie or not self.client.connected):
            self.audio.set_talking(False)
            self.talk_denied_until = time.time() + 2.0

        if self.audio.error:
            self.audio_label.config(text=f"Audio niedostępne: {self.audio.error}", fg="#888888")
        elif self.audio.talking:
            bars = int(self.audio.level_out * 20)
            meter = "▮" * bars + "▯" * (20 - bars)
            if self.audio.clipping:
                self.audio_label.config(text=f"🎤 MÓWISZ  {meter}  PRZESTEROWANIE – zmniejsz głośność robota", fg="#F44336")
            else:
                self.audio_label.config(text=f"🎤 MÓWISZ do robota  {meter}", fg="#FFC107")
        elif self.client.inny_mowi:
            self.audio_label.config(text="🗣 Inny operator mówi do robota", fg="#FFC107")
        elif time.time() < self.talk_denied_until:
            self.audio_label.config(text="Mówienie niedostępne – telefon ma pierwszeństwo", fg="#F44336")
        elif not self.audio.listening:
            self.audio_label.config(text="🔇 Słuchanie wyciszone (M = włącz)", fg="#888888")
        else:
            bars = int(self.audio.level * 20)
            self.audio_label.config(text="🔊 Słuchasz robota  " + "▮" * bars + "▯" * (20 - bars), fg="#4CAF50")

    def _update_battery(self):
        bat = self.client.battery
        if not self.client.connected or bat is None or time.time() - bat[3] > 3.0:
            self.battery_label.config(text="Bateria: --", fg="#888888", bg="#121212")
            return
        volts, pct, state, _ = bat
        if state == "brak":
            self.battery_label.config(text="Bateria: brak pomiaru (zasilanie z USB?)", fg="#888888", bg="#121212")
        elif state == "krytyczny":
            self.battery_label.config(text=f"⚠ BATERIA KRYTYCZNA {volts:.1f} V ({pct}%) – jazda zablokowana, naładuj!",
                                      fg="#FFFFFF", bg="#B71C1C")
        elif state == "niski":
            self.battery_label.config(text=f"Bateria: {volts:.1f} V ({pct}%) – niski poziom, wracaj",
                                      fg="#121212", bg="#FFC107")
        else:
            self.battery_label.config(text=f"Bateria: {volts:.1f} V ({pct}%)", fg="#4CAF50", bg="#121212")

    def _show_users(self):
        if self.okno_uzytkownikow and self.okno_uzytkownikow.okno.winfo_exists():
            self.okno_uzytkownikow.okno.lift()
            return
        self.okno_uzytkownikow = OknoUzytkownikow(self.root, self.sesja)

    def _logout(self):
        try:
            api(self.host, self.port, "POST", "/api/logout", {"klient": "pc"}, self.sesja["token"])
        except BladApi:
            pass
        self.wylogowano = True
        self._on_close()

    def _on_close(self):
        if self.pressed_keys:
            self.client.send("stop")
        if self.audio.talking:
            self.client.send("mow:0")
        self.client.send("sluchaj:0")
        self.client.close()
        self.camera_stream.stop()
        self.audio.close()
        self.root.destroy()


def main():
    # Po wylogowaniu ponownie wyświetlane jest okno logowania.
    while True:
        root = tk.Tk()
        sesja = zaloguj(root, SERWER_HOST, SERWER_PORT)
        if sesja is None:
            return
        app = RobotControllerGUI(root, sesja)
        root.mainloop()
        if not app.wylogowano:
            return


if __name__ == "__main__":
    main()