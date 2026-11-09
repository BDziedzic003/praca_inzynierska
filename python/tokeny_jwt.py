"""
Tokeny JWT (JSON Web Token, RFC 7519) podpisywane algorytmem HS256 (HMAC-SHA256).

Token ma postać  naglowek.dane.podpis  (każda część zakodowana base64url):
    naglowek - {"alg": "HS256", "typ": "JWT"}
    dane     - np. {"sub": "jan", "admin": false, "iat": ..., "exp": ..., "jti": ...}
    podpis   - HMAC-SHA256(naglowek.dane, klucz serwera)

Podpis gwarantuje, że treści tokenu nie można zmienić bez znajomości klucza.
Implementacja oparta wyłącznie na bibliotece standardowej.
"""

import base64
import hashlib
import hmac
import json
import time

NAGLOWEK = {"alg": "HS256", "typ": "JWT"}


def _b64(dane: bytes) -> str:
    return base64.urlsafe_b64encode(dane).rstrip(b"=").decode()


def _b64_dekoduj(tekst: str) -> bytes:
    return base64.urlsafe_b64decode(tekst + "=" * (-len(tekst) % 4))


def _json(obiekt) -> bytes:
    return json.dumps(obiekt, separators=(",", ":"), ensure_ascii=False).encode()


def utworz(dane: dict, klucz: bytes) -> str:
    """Podpisany token JWT z podanymi danymi (claims)."""
    poczatek = f"{_b64(_json(NAGLOWEK))}.{_b64(_json(dane))}"
    podpis = hmac.new(klucz, poczatek.encode(), hashlib.sha256).digest()
    return f"{poczatek}.{_b64(podpis)}"


def odczytaj(token: str, klucz: bytes):
    """Dane z tokenu po sprawdzeniu podpisu i czasu ważności; None dla tokenu nieprawidłowego."""
    try:
        naglowek, dane, podpis = token.split(".")
        if json.loads(_b64_dekoduj(naglowek)).get("alg") != "HS256":   # odrzucenie m.in. "alg": "none"
            return None
        oczekiwany = hmac.new(klucz, f"{naglowek}.{dane}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(oczekiwany, _b64_dekoduj(podpis)):
            return None
        wynik = json.loads(_b64_dekoduj(dane))
    except (ValueError, AttributeError, TypeError):
        return None
    if not isinstance(wynik, dict) or wynik.get("exp", 0) <= time.time():
        return None
    return wynik