#include <Arduino.h>
#include <ESP32Servo.h>
#include "konfiguracja.h"
#include "serwo.h"

static Servo serwo;
static int kat = 90;             // pozycja początkowa: środek
static int kierunek = 0;         // -1 / 0 / 1
static unsigned long ostatniRuch = 0;

void serwoBegin() {
  serwo.setPeriodHertz(50);
  serwo.attach(PIN_SERWA, SERWO_MIN_US, SERWO_MAX_US);
  serwo.write(kat);
}

void serwoUstawKierunek(int k) {
  kierunek = k;
}

int serwoKat() {
  return kat;
}

void serwoUpdate() {
  if (kierunek != 0 && millis() - ostatniRuch >= SERWO_OPOZNIENIE_MS) {
    ostatniRuch = millis();
    kat += kierunek * SERWO_KROK;

    if (kat >= 179) { kat = 179; kierunek = 0; }   // zatrzymanie w skrajnych położeniach
    if (kat <= 0)   { kat = 0;   kierunek = 0; }

    serwo.write(kat);
  }
}
