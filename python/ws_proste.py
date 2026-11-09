"""
Minimalna implementacja protokołu WebSocket (RFC 6455) oparta wyłącznie na bibliotece standardowej.

Obsługiwane są ramki tekstowe i binarne, ping/pong oraz zamknięcie połączenia.
Moduł wykorzystują serwer (serwer.py) i aplikacja na komputer (gui_controller.py).
"""

import base64
import hashlib
import os
import socket
import struct
import threading

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT, OP_TEXT, OP_BIN, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
MAX_PAYLOAD = 1_000_000


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


class WebSocket:
    """Połączenie WebSocket na otwartym gnieździe (po wymianie nagłówków HTTP)."""

    def __init__(self, sock, rfile, klient: bool):
        self.sock = sock
        self.rfile = rfile          # bufor odczytu (może zawierać dane odebrane razem z nagłówkami)
        self.klient = klient        # ramki wysyłane przez klienta muszą być maskowane
        self._lock = threading.Lock()
        self.zamkniete = False

    # ---------- wysyłanie ----------
    def _send_frame(self, opcode, payload: bytes):
        n = len(payload)
        head = bytearray([0x80 | opcode])
        mask_bit = 0x80 if self.klient else 0
        if n < 126:
            head.append(mask_bit | n)
        elif n < 65536:
            head.append(mask_bit | 126)
            head += struct.pack(">H", n)
        else:
            head.append(mask_bit | 127)
            head += struct.pack(">Q", n)
        if self.klient:
            mask = os.urandom(4)
            head += mask
            payload = _xor(payload, mask)
        with self._lock:
            self.sock.sendall(bytes(head) + payload)

    def send_text(self, text: str):
        self._send_frame(OP_TEXT, text.encode())

    def send_bytes(self, data: bytes):
        self._send_frame(OP_BIN, data)

    def close(self):
        """Zamknięcie połączenia; odblokowuje również wątek oczekujący w recv()."""
        if self.zamkniete:
            return
        self.zamkniete = True
        try:
            self._send_frame(OP_CLOSE, b"")
        except OSError:
            pass
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    # ---------- odbiór ----------
    def _read_exact(self, n):
        data = self.rfile.read(n)
        if data is None or len(data) < n:
            raise ConnectionError("połączenie zamknięte")
        return data

    def recv(self):
        """Zwraca str (ramka tekstowa), bytes (ramka binarna) lub None po zamknięciu połączenia."""
        fragmenty, typ = [], None
        try:
            while True:
                b1, b2 = self._read_exact(2)
                fin, opcode = b1 & 0x80, b1 & 0x0F
                n = b2 & 0x7F
                if n == 126:
                    n = struct.unpack(">H", self._read_exact(2))[0]
                elif n == 127:
                    n = struct.unpack(">Q", self._read_exact(8))[0]
                if n > MAX_PAYLOAD:
                    raise ConnectionError("zbyt duża ramka")
                mask = self._read_exact(4) if b2 & 0x80 else None
                payload = self._read_exact(n) if n else b""
                if mask:
                    payload = _xor(payload, mask)

                if opcode == OP_CLOSE:
                    self.close()
                    return None
                if opcode == OP_PING:
                    self._send_frame(OP_PONG, payload)
                    continue
                if opcode == OP_PONG:
                    continue
                if opcode in (OP_TEXT, OP_BIN):
                    typ, fragmenty = opcode, [payload]
                elif opcode == OP_CONT and typ is not None:
                    fragmenty.append(payload)
                else:
                    continue
                if fin:
                    data = b"".join(fragmenty)
                    return data.decode(errors="ignore") if typ == OP_TEXT else data
        except (OSError, ConnectionError, ValueError):
            self.close()
            return None


def _xor(data: bytes, mask: bytes) -> bytes:
    """Maskowanie/odmaskowanie danych (XOR z 4-bajtowym kluczem)."""
    n = len(data)
    if not n:
        return b""
    klucz = (mask * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "little") ^ int.from_bytes(klucz, "little")).to_bytes(n, "little")


def connect(host: str, port: int, path: str = "/ws", timeout: float = 3.0) -> WebSocket:
    """Nawiązanie połączenia WebSocket jako klient."""
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ).encode())
    rfile = sock.makefile("rb")
    status = rfile.readline().decode(errors="ignore")
    if " 101 " not in status:
        sock.close()
        raise ConnectionError(f"serwer odrzucił połączenie: {status.strip()}")
    naglowki = {}
    while True:
        line = rfile.readline().decode(errors="ignore").strip()
        if not line:
            break
        k, _, v = line.partition(":")
        naglowki[k.strip().lower()] = v.strip()
    if naglowki.get("sec-websocket-accept") != accept_key(key):
        sock.close()
        raise ConnectionError("niepoprawna odpowiedź serwera WebSocket")
    sock.settimeout(None)
    return WebSocket(sock, rfile, klient=True)
