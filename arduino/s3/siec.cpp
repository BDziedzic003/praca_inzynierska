#include <WiFi.h>
#include <ESPmDNS.h>
#include "konfiguracja.h"
#include "siec.h"
#include "serwo.h"
#include "silniki.h"
#include "bateria.h"
#include "audio.h"

static WiFiServer serwer(PORT_KOMEND);
static WiFiClient klient;

static String bufor;                          // bufor odbieranej linii
static unsigned long ostatniaKomenda = 0;     // czas odebrania ostatniej linii (również "ping")
static bool watchdogZatrzymal = true;         // robot zatrzymany przez watchdog lub po rozłączeniu

void siecBegin() {
  Serial.print("Lacze z WiFi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_HASLO);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Polaczono! IP: ");
  Serial.println(WiFi.localIP());

  if (MDNS.begin(MDNS_NAZWA)) {
    MDNS.addService("robot", "tcp", PORT_KOMEND);
    Serial.printf("mDNS: %s.local  (komendy na porcie %d)\n", MDNS_NAZWA, PORT_KOMEND);
  } else {
    Serial.println("Blad uruchamiania mDNS");
  }

  serwer.begin();
  serwer.setNoDelay(true);
}

bool siecKlientPolaczony() {
  return klient && klient.connected();
}

// Interpretacja jednej komendy w formacie "nazwa" lub "nazwa:wartość", np. "forward:150".
// Brak wartości oznacza PREDKOSC_DOMYSLNA.
static void obsluzKomende(String linia) {
  linia.trim();
  linia.toLowerCase();
  if (linia.length() == 0) return;

  ostatniaKomenda = millis();
  watchdogZatrzymal = false;

  if (linia == "ping") return;               // heartbeat - tylko odświeżenie watchdoga

  int separator = linia.indexOf(':');
  String komenda = (separator == -1) ? linia : linia.substring(0, separator);
  int predkosc = PREDKOSC_DOMYSLNA;
  if (separator != -1) {
    predkosc = linia.substring(separator + 1).toInt();
    predkosc = constrain(predkosc, 0, 255);
  }

  // Blokada jazdy przy krytycznym stanie baterii (kamera i "stop" pozostają aktywne)
  bool komendaJazdy = (komenda == "forward" || komenda == "backward" ||
                       komenda == "spinleft" || komenda == "spinright");
  if (komendaJazdy && bateriaKrytyczna()) {
    silnikiStop();
    Serial.println("Jazda zablokowana - bateria krytyczna");
    return;
  }

  // Kamera (serwo)
  if (komenda == "right") {
    serwoUstawKierunek(1);
    Serial.println("kamera -> w prawo");
  } else if (komenda == "left") {
    serwoUstawKierunek(-1);
    Serial.println("kamera -> w lewo");
  } else if (komenda == "camstop") {
    serwoUstawKierunek(0);
    Serial.println("kamera -> stop");
  } else if (komenda == "stop") {
    serwoUstawKierunek(0);
    silnikiStop();
    Serial.println("-> stop (kamera + jazda)");

  // Jazda
  } else if (komenda == "forward") {
    silnikiJedzDoPrzodu(predkosc);
    Serial.printf("jazda -> przod @ %d\n", predkosc);
  } else if (komenda == "backward") {
    silnikiJedzDoTylu(predkosc);
    Serial.printf("jazda -> tyl @ %d\n", predkosc);
  } else if (komenda == "spinleft") {
    silnikiSkretWLewo(predkosc);
    Serial.printf("jazda -> skret w lewo @ %d\n", predkosc);
  } else if (komenda == "spinright") {
    silnikiSkretWPrawo(predkosc);
    Serial.printf("jazda -> skret w prawo @ %d\n", predkosc);
  // Audio
  } else if (komenda == "mic") {
    audioMikrofon(predkosc == 1);              // "mic:1" / "mic:0"
    Serial.println(predkosc == 1 ? "mikrofon -> wlaczony" : "mikrofon -> wyciszony");

  } else if (komenda == "drivestop") {
    silnikiStop();
    Serial.println("jazda -> stop");

  } else {
    Serial.println("Nieznana komenda: " + linia);
  }
}

void siecUpdate() {
  static bool bylPolaczony = false;
  bool jest = siecKlientPolaczony();

  // Rozłączenie klienta: zatrzymanie ruchu i wyłączenie transmisji audio
  if (bylPolaczony && !jest) {
    serwoUstawKierunek(0);
    silnikiStop();
    audioMikrofon(false);
    audioUstawOdbiorce(IPAddress((uint32_t)0));
    watchdogZatrzymal = true;
    Serial.println("Klient rozlaczony -> STOP (failsafe)");
  }
  bylPolaczony = jest;

  if (!jest) {
    WiFiClient nowy = serwer.available();
    if (nowy) {
      klient = nowy;
      klient.setNoDelay(true);
      bufor = "";
      ostatniaKomenda = millis();
      audioUstawOdbiorce(klient.remoteIP());   // adres docelowy dźwięku z mikrofonu
      Serial.print("Klient polaczony: ");
      Serial.println(klient.remoteIP());
    }
    return;
  }

  // Nieblokujący odbiór komend, znak po znaku
  while (klient.available()) {
    char c = (char)klient.read();
    if (c == '\n') {
      obsluzKomende(bufor);
      bufor = "";
    } else if (c != '\r') {
      if (bufor.length() < 64) bufor += c;   // ograniczenie długości linii
    }
  }

  // Watchdog: brak komend przez WATCHDOG_MS przy aktywnym połączeniu
  // (np. zawieszony serwer lub zerwane Wi-Fi bez zamknięcia połączenia)
  if (!watchdogZatrzymal && millis() - ostatniaKomenda > WATCHDOG_MS) {
    serwoUstawKierunek(0);
    silnikiStop();
    watchdogZatrzymal = true;
    Serial.println("Brak komend od serwera -> STOP (watchdog)");
  }
}

void siecWyslij(const char* linia) {
  if (siecKlientPolaczony()) klient.println(linia);
}
