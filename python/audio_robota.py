"""
Łączność głosowa z robotem przez serwer (tryb półdupleksowy):

    mikrofon robota     --serwer-->  głośniki komputera  (nasłuch)
    mikrofon komputera  --serwer-->  głośnik robota      (nadawanie)

Próbki przesyłane są jako ramki binarne WebSocket w formacie zgodnym z audio.cpp
na ESP32-S3: 16 kHz, 16 bit, mono, PCM little-endian.
Zależności: sounddevice, numpy.
"""

import threading
import time

import numpy as np

try:
    import sounddevice as sd
except Exception as e:
    sd = None
    _SD_ERROR = str(e)

RATE = 16000                 # zgodne z AUDIO_CZESTOTLIWOSC w konfiguracja.h
BLOCK = 512                  # próbek w pakiecie (32 ms)

JITTER_START_S = 0.10        # bufor wstępny przed rozpoczęciem odtwarzania
MAX_BUFFER_S = 0.40          # górna granica opóźnienia odtwarzania


class AudioRobota:
    def __init__(self, send_mic):
        """send_mic: funkcja wysyłająca pakiet próbek z mikrofonu komputera do serwera."""
        self.send_mic = send_mic
        self.listening = True         # nasłuch mikrofonu robota
        self.talking = False          # nadawanie do robota
        self.level = 0.0              # poziom sygnału z robota (0..1)
        self.level_out = 0.0          # poziom sygnału wysyłanego (0..1)
        self.clipping = False         # przesterowanie sygnału wysyłanego
        self.listen_gain = 0.5        # wzmocnienie odtwarzanego dźwięku z robota
        self.talk_gain = 2.0          # wzmocnienie dźwięku wysyłanego do robota
        self._clip_until = 0.0
        self.error = None

        self._buf = bytearray()
        self._lock = threading.Lock()
        self._prebuffer = True
        self._last_packet = 0.0

        if sd is None:
            self.error = f"brak biblioteki sounddevice ({_SD_ERROR})"
            return
        try:
            self._out = sd.RawOutputStream(samplerate=RATE, channels=1, dtype="int16",
                                           blocksize=BLOCK, callback=self._out_cb)
            self._inp = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16",
                                          blocksize=BLOCK, callback=self._in_cb)
            self._out.start()
            self._inp.start()
        except Exception as e:
            self.error = str(e)

    def set_talking(self, on: bool):
        self.talking = on
        if on:
            self._clear()             # podczas nadawania dźwięk z robota nie jest odtwarzany
        else:
            self.level_out = 0.0

    def set_listening(self, on: bool):
        self.listening = on
        if not on:
            self._clear()

    def clear(self):
        self._clear()

    def _clear(self):
        with self._lock:
            self._buf.clear()
            self._prebuffer = True

    def close(self):
        for name in ("_out", "_inp"):
            stream = getattr(self, name, None)
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

    def update_level(self):
        """Wygaszanie wskaźnika poziomu, gdy dźwięk nie dociera."""
        if time.time() - self._last_packet > 0.5:
            self.level *= 0.5

    def feed(self, data: bytes):
        """Pakiet próbek z robota."""
        if not data or len(data) % 2:
            return
        self._last_packet = time.time()
        samples = np.frombuffer(data, dtype=np.int16)
        self.level = min(1.0, float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) / 8000.0)

        if self.talking or not self.listening or self.error:
            return
        if abs(self.listen_gain - 1.0) > 0.01:
            data = np.clip(samples.astype(np.float32) * self.listen_gain, -32768, 32767).astype(np.int16).tobytes()
        max_bytes = int(MAX_BUFFER_S * RATE) * 2
        with self._lock:
            self._buf += data
            if len(self._buf) > max_bytes:            # ograniczenie opóźnienia: odrzucenie najstarszych próbek
                del self._buf[:len(self._buf) - max_bytes // 2]

    def _out_cb(self, outdata, frames, time_info, status):
        need = frames * 2
        with self._lock:
            if self._prebuffer:
                if len(self._buf) < int(JITTER_START_S * RATE) * 2:
                    outdata[:] = bytes(need)
                    return
                self._prebuffer = False
            if len(self._buf) >= need:
                outdata[:] = bytes(self._buf[:need])
                del self._buf[:need]
            else:                                      # brak danych: cisza i ponowne buforowanie
                outdata[:] = bytes(self._buf) + bytes(need - len(self._buf))
                self._buf.clear()
                self._prebuffer = True

    # ---------- komputer -> robot ----------
    def _in_cb(self, indata, frames, time_info, status):
        if not self.talking:
            return
        samples = np.frombuffer(bytes(indata), dtype=np.int16).astype(np.float32) * self.talk_gain
        if not samples.size:
            return
        if float(np.max(np.abs(samples))) > 32000:   # sygnalizacja przesterowania przez 1 s
            self._clip_until = time.time() + 1.0
        self.clipping = time.time() < self._clip_until
        self.level_out = min(1.0, float(np.sqrt(np.mean(samples ** 2))) / 8000.0)
        self.send_mic(np.clip(samples, -32768, 32767).astype(np.int16).tobytes())