"""
Logowanie i zarządzanie użytkownikami w aplikacji na komputer (klient API serwera).
"""

import json
import os
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from tkinter import messagebox, simpledialog, ttk

PLIK_USTAWIEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui_ustawienia.json")

KOLOR_TLA = "#121212"
STYL = {"bg": KOLOR_TLA, "fg": "#FFFFFF"}


class BladApi(Exception):
    def __init__(self, komunikat, kod=0):
        super().__init__(komunikat)
        self.kod = kod


def api(host, port, metoda, sciezka, dane=None, token=None):
    """Zapytanie do API serwera; zwraca odpowiedź JSON lub zgłasza BladApi."""
    req = urllib.request.Request(f"http://{host}:{port}{sciezka}", method=metoda,
                                 data=json.dumps(dane).encode() if dane is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            komunikat = json.loads(e.read()).get("blad", e.reason)
        except ValueError:
            komunikat = e.reason
        raise BladApi(komunikat, e.code)
    except OSError as e:
        raise BladApi(f"brak połączenia z serwerem ({e})")


def _wczytaj_ustawienia():
    try:
        with open(PLIK_USTAWIEN, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _zapisz_ustawienia(ust):
    try:
        with open(PLIK_USTAWIEN, "w", encoding="utf-8") as f:
            json.dump(ust, f)
    except OSError:
        pass


# ==================== LOGOWANIE ====================
def zaloguj(root, domyslny_host, domyslny_port):
    """Formularz logowania w oknie root.

    Zwraca {host, port, token, login, admin} po zalogowaniu lub None po zamknięciu okna.
    """
    ust = _wczytaj_ustawienia()
    wynik = {}

    root.title("Logowanie – sterowanie robotem")
    root.configure(bg=KOLOR_TLA)
    ramka = tk.Frame(root, bg=KOLOR_TLA, padx=30, pady=20)
    ramka.pack()

    tk.Label(ramka, text="Logowanie", **STYL, font=("Segoe UI", 16, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 15))
    pola = {}
    for i, (klucz, etykieta, wartosc, ukryte) in enumerate((
            ("host", "Adres serwera:", ust.get("host", domyslny_host), False),
            ("port", "Port:", str(ust.get("port", domyslny_port)), False),
            ("login", "Login:", ust.get("login", ""), False),
            ("haslo", "Hasło:", "", True)), start=1):
        tk.Label(ramka, text=etykieta, **STYL, font=("Segoe UI", 11)).grid(row=i, column=0, sticky="e", padx=5, pady=4)
        e = tk.Entry(ramka, width=24, font=("Segoe UI", 11), show="•" if ukryte else "")
        e.insert(0, wartosc)
        e.grid(row=i, column=1, pady=4)
        pola[klucz] = e

    blad = tk.Label(ramka, text="", bg=KOLOR_TLA, fg="#F44336", font=("Segoe UI", 10))
    blad.grid(row=5, column=0, columnspan=2, pady=(8, 0))

    def wyslij(_event=None):
        host = pola["host"].get().strip()
        try:
            port = int(pola["port"].get())
        except ValueError:
            blad.config(text="niepoprawny port")
            return
        login = pola["login"].get().strip()
        blad.config(text="Logowanie...", fg="#BBBBBB")
        root.update_idletasks()
        try:
            odp = api(host, port, "POST", "/api/login", {"login": login, "haslo": pola["haslo"].get(), "klient": "pc"})
        except BladApi as e:
            blad.config(text=str(e), fg="#F44336")
            return
        _zapisz_ustawienia({"host": host, "port": port, "login": login})
        wynik.update(host=host, port=port, token=odp["token"], login=odp["login"], admin=odp["admin"])
        ramka.destroy()
        root.quit()

    tk.Button(ramka, text="Zaloguj", width=14, command=wyslij).grid(row=6, column=0, columnspan=2, pady=(12, 0))
    root.bind("<Return>", wyslij)
    (pola["haslo"] if pola["login"].get() else pola["login"]).focus_set()

    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    try:
        root.unbind("<Return>")
    except tk.TclError:
        return None                     # okno zamknięte
    return wynik or None


# ==================== ZARZĄDZANIE UŻYTKOWNIKAMI ====================
class OknoUzytkownikow:
    """Okno administratora: lista kont, dodawanie, usuwanie, uprawnienia i zmiana hasła."""

    def __init__(self, root, sesja):
        self.sesja = sesja
        self.okno = tk.Toplevel(root)
        self.okno.title("Użytkownicy")
        self.okno.configure(bg=KOLOR_TLA, padx=12, pady=12)

        self.tabela = ttk.Treeview(self.okno, columns=("login", "rola"), show="headings", height=10,
                                   selectmode="browse")
        self.tabela.heading("login", text="Login")
        self.tabela.heading("rola", text="Rola")
        self.tabela.column("login", width=180)
        self.tabela.column("rola", width=140)
        self.tabela.grid(row=0, column=0, columnspan=4, sticky="nsew")

        przyciski = (("Nadaj / odbierz admina", self._przelacz_admina),
                     ("Zmień hasło", self._zmien_haslo),
                     ("Usuń", self._usun),
                     ("Odśwież", self.odswiez))
        for i, (tekst, akcja) in enumerate(przyciski):
            tk.Button(self.okno, text=tekst, command=akcja).grid(row=1, column=i, pady=8, padx=2, sticky="ew")

        nowy = tk.LabelFrame(self.okno, text="Nowy użytkownik", bg=KOLOR_TLA, fg="#FFFFFF", padx=8, pady=8)
        nowy.grid(row=2, column=0, columnspan=4, sticky="ew")
        tk.Label(nowy, text="Login:", **STYL).grid(row=0, column=0, sticky="e")
        self.nowy_login = tk.Entry(nowy, width=18)
        self.nowy_login.grid(row=0, column=1, padx=4)
        tk.Label(nowy, text="Hasło:", **STYL).grid(row=0, column=2, sticky="e")
        self.nowe_haslo = tk.Entry(nowy, width=14, show="•")
        self.nowe_haslo.grid(row=0, column=3, padx=4)
        self.nowy_admin = tk.BooleanVar()
        tk.Checkbutton(nowy, text="administrator", variable=self.nowy_admin, bg=KOLOR_TLA, fg="#FFFFFF",
                       selectcolor="#333333", activebackground=KOLOR_TLA).grid(row=0, column=4, padx=4)
        tk.Button(nowy, text="Dodaj", command=self._dodaj).grid(row=0, column=5, padx=4)

        self.odswiez()

    def _api(self, metoda, sciezka, dane=None):
        s = self.sesja
        try:
            return api(s["host"], s["port"], metoda, sciezka, dane, s["token"])
        except BladApi as e:
            messagebox.showerror("Błąd", str(e), parent=self.okno)
            return None

    def _zaznaczony(self):
        wybor = self.tabela.selection()
        if not wybor:
            messagebox.showinfo("Użytkownicy", "Należy zaznaczyć użytkownika na liście.", parent=self.okno)
            return None
        return self.tabela.item(wybor[0], "values")

    def odswiez(self):
        lista = self._api("GET", "/api/uzytkownicy")
        if lista is None:
            return
        self.tabela.delete(*self.tabela.get_children())
        for u in lista:
            rola = "administrator" if u["admin"] else "użytkownik"
            self.tabela.insert("", "end", values=(u["login"], rola))

    def _dodaj(self):
        dane = {"login": self.nowy_login.get().strip(), "haslo": self.nowe_haslo.get(),
                "admin": self.nowy_admin.get()}
        if self._api("POST", "/api/uzytkownicy", dane) is not None:
            self.nowy_login.delete(0, "end")
            self.nowe_haslo.delete(0, "end")
            self.nowy_admin.set(False)
            self.odswiez()

    def _przelacz_admina(self):
        z = self._zaznaczony()
        if z:
            login, rola = z
            self._api("PATCH", f"/api/uzytkownicy/{urllib.parse.quote(login)}", {"admin": rola != "administrator"})
            self.odswiez()

    def _zmien_haslo(self):
        z = self._zaznaczony()
        if not z:
            return
        haslo = simpledialog.askstring("Zmiana hasła", f"Nowe hasło dla {z[0]}:", show="•", parent=self.okno)
        if haslo and self._api("PATCH", f"/api/uzytkownicy/{urllib.parse.quote(z[0])}", {"haslo": haslo}) is not None:
            messagebox.showinfo("Zmiana hasła", "Hasło zostało zmienione.", parent=self.okno)

    def _usun(self):
        z = self._zaznaczony()
        if z and messagebox.askyesno("Usuwanie", f"Usunąć użytkownika {z[0]}?", parent=self.okno):
            self._api("DELETE", f"/api/uzytkownicy/{urllib.parse.quote(z[0])}")
            self.odswiez()