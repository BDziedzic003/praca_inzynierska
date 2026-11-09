"""
Konta użytkowników, uwierzytelnianie tokenami JWT i historia logowań (baza MongoDB).

Kolekcje:
    uzytkownicy  - {login, sol, haslo, iteracje, admin, wersja_tokenow, utworzono}
    uniewaznione - {jti, wygasa}   tokeny unieważnione przez wylogowanie
                                   (usuwane automatycznie po upływie ważności tokenu)
    logowania    - {login, czas, zdarzenie, adres, klient}   historia logowań
                                   (usuwana automatycznie po CZAS_HISTORII)
    konfiguracja - {_id: "jwt", klucz}   klucz podpisujący tokeny (tworzony przy pierwszym uruchomieniu)

Po zalogowaniu serwer wydaje token JWT (tokeny_jwt.py) z danymi:
    sub - login, admin - uprawnienia administratora, ver - wersja tokenów konta,
    iat / exp - czas wydania i wygaśnięcia, jti - unikalny identyfikator tokenu.
Weryfikacja tokenu: podpis i czas ważności, brak na liście unieważnionych oraz zgodność
wersji z kontem. Zmiana uprawnień lub hasła (przez administratora) zwiększa wersję,
co unieważnia wszystkie wcześniejsze tokeny tego konta; usunięcie konta również.

Hasła są przechowywane jako skrót PBKDF2-HMAC-SHA256 z losową solą; liczba iteracji
zapisywana jest przy każdym haśle, a skróty utworzone z mniejszą liczbą iteracji są
przeliczane przy najbliższym poprawnym logowaniu. Nowe hasła muszą spełniać politykę
haseł: co najmniej 8 znaków, inne niż login i spoza listy najpopularniejszych haseł.
Przy pierwszym uruchomieniu, gdy baza jest pusta, tworzone jest konto "admin"
z losowym hasłem wypisywanym w konsoli serwera.
Zależności: pymongo.
"""

import datetime
import hashlib
import hmac
import os
import re
import secrets
import time

import tokeny_jwt

ITERACJE = 600_000                    # liczba iteracji PBKDF2-HMAC-SHA256 (zalecenie OWASP)
ITERACJE_POPRZEDNIE = 200_000         # wartość dla skrótów zapisanych bez pola "iteracje"
CZAS_SESJI = datetime.timedelta(hours=12)
CZAS_HISTORII = datetime.timedelta(days=90)   # okres przechowywania historii logowań
WZOR_LOGINU = re.compile(r"^[a-z0-9_.-]{3,32}$")
MIN_DLUGOSC_HASLA = 8
MAX_DLUGOSC_HASLA = 128

DOMYSLNY_ADMIN = "admin"

# Najczęściej używane hasła (m.in. z publicznych zestawień haseł ujawnionych w wyciekach),
# porównywane bez rozróżniania wielkości liter.
POPULARNE_HASLA = frozenset("""
123456 123456789 12345678 1234567890 1234567 12345 123123 111111 000000 654321 666666 555555
888888 7777777 121212 112233 123321 147258369 987654321 11111111 00000000 12341234 123456a
password password1 password123 passw0rd p@ssw0rd qwerty qwerty123 qwerty1 qwertyuiop qwer1234
asdfghjkl asdfgh zxcvbnm 1q2w3e4r 1q2w3e4r5t 1qaz2wsx zaq12wsx zaq1@wsx qazwsx 12qwaszx q1w2e3r4
abc123 abcd1234 aa123456 iloveyou princess sunshine football baseball monkey dragon master
letmein welcome whatever trustno1 superman batman starwars shadow michael freedom
admin admin123 administrator root toor test test123 haslo haslo123 haslo1 polska polska1
kochanie misiek misiaczek mamusia tatusia marcin bartek mateusz lukasz kacper agnieszka
monika karolina zaq1xsw2 robot robot123 robocik ratownik
""".split())


class BladUzytkownika(Exception):
    """Błąd operacji na kontach; kod odpowiada statusowi HTTP zwracanemu przez API."""

    def __init__(self, komunikat, kod=400):
        super().__init__(komunikat)
        self.kod = kod


def _teraz():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso_utc(czas: datetime.datetime) -> str:
    """Czas w formacie ISO 8601 ze strefą UTC (MongoDB zwraca czas UTC bez strefy)."""
    if czas.tzinfo is None:
        czas = czas.replace(tzinfo=datetime.timezone.utc)
    return czas.isoformat()


def _skrot(haslo: str, sol: bytes, iteracje: int = ITERACJE) -> str:
    return hashlib.pbkdf2_hmac("sha256", haslo.encode(), sol, iteracje).hex()


def _normalizuj_login(login) -> str:
    return str(login or "").strip().lower()


class Uzytkownicy:
    def __init__(self, uri=None, baza="robot", kolekcje=None):
        """uri - adres serwera MongoDB;
        kolekcje - (uzytkownicy, uniewaznione, logowania, konfiguracja) podane bezpośrednio (testy)."""
        if kolekcje is None:
            from pymongo import MongoClient
            klient = MongoClient(uri, serverSelectionTimeoutMS=3000)
            klient.admin.command("ping")          # wyjątek, gdy baza jest niedostępna
            db = klient[baza]
            kolekcje = (db["uzytkownicy"], db["uniewaznione"], db["logowania"], db["konfiguracja"])
        self.konta, self.uniewaznione, self.logowania, self.konfiguracja = kolekcje

        self.konta.create_index("login", unique=True)
        self.uniewaznione.create_index("jti", unique=True)
        self.uniewaznione.create_index("wygasa", expireAfterSeconds=0)
        self._indeks_historii()
        self.klucz = self._klucz_jwt()

        if self.konta.count_documents({}) == 0:
            haslo = secrets.token_urlsafe(9)
            self.dodaj(DOMYSLNY_ADMIN, haslo, admin=True)
            print(f"Utworzono konto administratora: login {DOMYSLNY_ADMIN}, hasło {haslo} "
                  f"- hasło należy zapisać i zmienić po pierwszym zalogowaniu")

    # ---------- logowanie ----------
    def zaloguj(self, login, haslo):
        """Zwraca {token, login, admin} lub None przy błędnych danych."""
        login = _normalizuj_login(login)
        konto = self.konta.find_one({"login": login})
        if not konto:
            _skrot(str(haslo), os.urandom(16))   # wyrównanie czasu odpowiedzi
            return None
        iteracje = konto.get("iteracje", ITERACJE_POPRZEDNIE)
        if not hmac.compare_digest(_skrot(str(haslo), bytes.fromhex(konto["sol"]), iteracje), konto["haslo"]):
            return None
        if iteracje < ITERACJE:
            # skrót utworzony z mniejszą liczbą iteracji - przeliczenie przy poprawnym logowaniu
            self.konta.update_one({"login": login}, {"$set": self._nowy_skrot(str(haslo))})
        teraz = int(time.time())
        admin = bool(konto.get("admin"))
        token = tokeny_jwt.utworz({
            "sub": login,
            "admin": admin,
            "ver": konto.get("wersja_tokenow", 0),
            "iat": teraz,
            "exp": teraz + int(CZAS_SESJI.total_seconds()),
            "jti": secrets.token_hex(12),
        }, self.klucz)
        return {"token": token, "login": login, "admin": admin}

    def wyloguj(self, token):
        """Unieważnienie tokenu do końca jego ważności."""
        dane = tokeny_jwt.odczytaj(token or "", self.klucz)
        if dane and not self.uniewaznione.find_one({"jti": dane.get("jti")}):
            wygasa = datetime.datetime.fromtimestamp(dane["exp"], datetime.timezone.utc)
            self.uniewaznione.insert_one({"jti": dane.get("jti"), "wygasa": wygasa})

    # ---------- historia logowań ----------
    def zapisz_zdarzenie(self, login, zdarzenie, adres, klient):
        """zdarzenie: "logowanie", "nieudane logowanie" lub "wylogowanie"."""
        self.logowania.insert_one({"login": _normalizuj_login(login)[:64], "czas": _teraz(),
                                   "zdarzenie": zdarzenie, "adres": adres, "klient": str(klient or "?")[:16]})

    def historia(self, limit=200, login=None):
        """Najnowsze zdarzenia logowania (od najnowszego)."""
        filtr = {"login": _normalizuj_login(login)} if login else {}
        wpisy = self.logowania.find(filtr).sort("czas", -1).limit(limit)
        return [{"login": w["login"], "czas": _iso_utc(w["czas"]), "zdarzenie": w["zdarzenie"],
                 "adres": w.get("adres", ""), "klient": w.get("klient", "")} for w in wpisy]

    def sesja(self, token):
        """Zwraca {login, admin} dla ważnego tokenu JWT lub None."""
        dane = tokeny_jwt.odczytaj(token or "", self.klucz)
        if not dane:
            return None
        if self.uniewaznione.find_one({"jti": dane.get("jti")}):
            return None
        konto = self.konta.find_one({"login": dane.get("sub")})
        if not konto or konto.get("wersja_tokenow", 0) != dane.get("ver"):
            return None
        return {"login": konto["login"], "admin": bool(dane.get("admin"))}

    # ---------- zarządzanie kontami (administrator) ----------
    def lista(self):
        return [{"login": k["login"], "admin": bool(k.get("admin"))}
                for k in sorted(self.konta.find({}), key=lambda k: k["login"])]

    def dodaj(self, login, haslo, admin=False):
        login = _normalizuj_login(login)
        if not WZOR_LOGINU.match(login):
            raise BladUzytkownika("login: 3-32 znaki, litery a-z, cyfry, _ . -")
        self._sprawdz_haslo(haslo, login)
        if self.konta.find_one({"login": login}):
            raise BladUzytkownika("użytkownik o tym loginie już istnieje", 409)
        self.konta.insert_one({"login": login, **self._nowy_skrot(haslo),
                               "admin": bool(admin), "utworzono": _teraz()})

    def usun(self, login, wykonujacy):
        login = _normalizuj_login(login)
        konto = self._konto(login)
        if login == wykonujacy:
            raise BladUzytkownika("nie można usunąć własnego konta")
        if konto.get("admin"):
            self._sprawdz_ostatniego_admina()
        self.konta.delete_one({"login": login})       # tokeny konta przestają być ważne
        self.logowania.delete_many({"login": login})  # usunięcie historii logowań użytkownika

    def ustaw_admin(self, login, admin, wykonujacy):
        login = _normalizuj_login(login)
        konto = self._konto(login)
        if not admin and konto.get("admin"):
            if login == wykonujacy:
                raise BladUzytkownika("nie można odebrać uprawnień samemu sobie")
            self._sprawdz_ostatniego_admina()
        zmiany = {"admin": bool(admin)}
        if bool(admin) != bool(konto.get("admin")):
            # uprawnienia zapisane w tokenie są nieaktualne - użytkownik loguje się ponownie
            zmiany["wersja_tokenow"] = konto.get("wersja_tokenow", 0) + 1
        self.konta.update_one({"login": login}, {"$set": zmiany})

    def zmien_haslo(self, login, haslo, wykonujacy=None):
        login = _normalizuj_login(login)
        konto = self._konto(login)
        self._sprawdz_haslo(haslo, login)
        zmiany = self._nowy_skrot(haslo)
        if login != wykonujacy:
            # zmiana hasła innego użytkownika kończy jego dotychczasowe sesje
            zmiany["wersja_tokenow"] = konto.get("wersja_tokenow", 0) + 1
        self.konta.update_one({"login": login}, {"$set": zmiany})

    # ---------- pomocnicze ----------
    @staticmethod
    def _nowy_skrot(haslo):
        """Pola dokumentu konta z nowym skrótem hasła i nową solą."""
        sol = os.urandom(16)
        return {"sol": sol.hex(), "haslo": _skrot(haslo, sol), "iteracje": ITERACJE}

    def _indeks_historii(self):
        """Indeks TTL: wpisy historii logowań usuwane automatycznie po CZAS_HISTORII."""
        sekundy = int(CZAS_HISTORII.total_seconds())
        indeksy = self.logowania.index_information()
        if "czas_1" in indeksy and indeksy["czas_1"].get("expireAfterSeconds") != sekundy:
            self.logowania.drop_index("czas_1")       # indeks bez TTL lub z innym okresem
        self.logowania.create_index("czas", expireAfterSeconds=sekundy)

    def _klucz_jwt(self) -> bytes:
        """Klucz podpisujący tokeny; przechowywany w bazie, więc tokeny są ważne po restarcie serwera."""
        wpis = self.konfiguracja.find_one({"_id": "jwt"})
        if not wpis:
            wpis = {"_id": "jwt", "klucz": secrets.token_hex(32)}
            self.konfiguracja.insert_one(wpis)
        return bytes.fromhex(wpis["klucz"])

    def _konto(self, login):
        konto = self.konta.find_one({"login": login})
        if not konto:
            raise BladUzytkownika("nie ma takiego użytkownika", 404)
        return konto

    def _sprawdz_ostatniego_admina(self):
        if self.konta.count_documents({"admin": True}) <= 1:
            raise BladUzytkownika("musi pozostać co najmniej jeden administrator")

    @staticmethod
    def _sprawdz_haslo(haslo, login):
        """Polityka haseł: długość, różnica względem loginu, brak na liście popularnych haseł."""
        if not isinstance(haslo, str) or len(haslo) < MIN_DLUGOSC_HASLA:
            raise BladUzytkownika(f"hasło musi mieć co najmniej {MIN_DLUGOSC_HASLA} znaków")
        if len(haslo) > MAX_DLUGOSC_HASLA:
            raise BladUzytkownika(f"hasło może mieć najwyżej {MAX_DLUGOSC_HASLA} znaków")
        if haslo.lower() == login:
            raise BladUzytkownika("hasło nie może być takie samo jak login")
        if haslo.lower() in POPULARNE_HASLA:
            raise BladUzytkownika("hasło jest zbyt popularne - należy wybrać inne")
