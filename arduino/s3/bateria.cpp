#include <Arduino.h>
#include "konfiguracja.h"
#include "bateria.h"
#include "silniki.h"
#include "siec.h"

static float napiecie = 0;               // napięcie pakietu po filtracji [V]
static bool  krytyczna = false;          // blokada jazdy
static unsigned long ponizejOd = 0;      // początek przebywania poniżej progu krytycznego (0 = nie dotyczy)
static int pokazanyProcent = -1;         // procent raportowany (z histerezą)

// Przybliżona charakterystyka rozładowania ogniwa Li-ion: napięcie -> procent
static const float TAB_V[] = {3.30, 3.40, 3.50, 3.60, 3.70, 3.80, 3.90, 4.00, 4.10, 4.20};
static const int   TAB_P[] = {   0,    5,   10,   20,   35,   50,   65,   80,   90,  100};

static float zmierz() {
  // Średnia z 16 odczytów ADC ogranicza szum pojedynczego pomiaru
  uint32_t suma = 0;
  for (int i = 0; i < 16; i++) suma += analogReadMilliVolts(PIN_BATERIA);
  float mv = suma / 16.0f;
  return mv / 1000.0f * (BAT_R1 + BAT_R2) / BAT_R2 * BAT_KALIBRACJA;
}

static bool podlaczona() {
  return napiecie >= BAT_MIN_POMIAR_V;   // niższe napięcie = brak baterii (np. zasilanie z USB)
}

void bateriaBegin() {
  pinMode(PIN_BATERIA, INPUT);
  napiecie = zmierz();
}

float bateriaNapiecie() { return napiecie; }
bool  bateriaKrytyczna() { return krytyczna; }

int bateriaProcent() {
  if (!podlaczona()) return 0;
  float ogniwo = napiecie / BAT_OGNIWA;
  if (ogniwo <= TAB_V[0]) return 0;
  const int n = sizeof(TAB_V) / sizeof(TAB_V[0]);
  if (ogniwo >= TAB_V[n - 1]) return 100;
  for (int i = 1; i < n; i++) {
    if (ogniwo <= TAB_V[i]) {
      float t = (ogniwo - TAB_V[i - 1]) / (TAB_V[i] - TAB_V[i - 1]);
      return (int)(TAB_P[i - 1] + t * (TAB_P[i] - TAB_P[i - 1]) + 0.5f);
    }
  }
  return 100;
}

static const char* stan() {
  if (!podlaczona())                    return "brak";
  if (krytyczna)                        return "krytyczny";
  if (napiecie < BAT_OSTRZEZENIE_V)     return "niski";
  return "ok";
}

void bateriaUpdate() {
  static unsigned long ostatniPomiar = 0, ostatniaWysylka = 0;
  unsigned long teraz = millis();

  // Pomiar co 100 ms z filtrem wykładniczym
  if (teraz - ostatniPomiar >= 100) {
    ostatniPomiar = teraz;
    float v = zmierz();
    if (v < BAT_MIN_POMIAR_V || napiecie < BAT_MIN_POMIAR_V) { napiecie = v; pokazanyProcent = -1; }   // podłączenie / odłączenie baterii
    else napiecie += BAT_WYGLADZANIE * (v - napiecie);

    // Stan krytyczny z opóźnieniem zadziałania i histerezą
    if (!podlaczona()) {
      ponizejOd = 0;
      if (krytyczna) { krytyczna = false; Serial.println("Bateria: brak pomiaru -> blokada zdjeta"); }
    } else if (!krytyczna) {
      if (napiecie < BAT_KRYTYCZNA_V) {
        if (ponizejOd == 0) ponizejOd = teraz;
        if (teraz - ponizejOd >= BAT_CZAS_KRYTYCZNY_MS) {
          krytyczna = true;
          silnikiStop();
          Serial.printf("BATERIA KRYTYCZNA (%.2f V) -> jazda zablokowana\n", napiecie);
        }
      } else {
        ponizejOd = 0;   // krótkotrwały spadek napięcia (np. przy ruszaniu) jest pomijany
      }
    } else if (napiecie > BAT_POWROT_V) {
      krytyczna = false;
      ponizejOd = 0;
      Serial.printf("Bateria: %.2f V -> blokada jazdy zdjeta\n", napiecie);
    }
  }

  // Raport co 1 s; procent zmieniany przy różnicy co najmniej 2 punktów (histereza)
  if (teraz - ostatniaWysylka >= 1000) {
    ostatniaWysylka = teraz;
    int p = bateriaProcent();
    if (pokazanyProcent < 0 || abs(p - pokazanyProcent) >= 2 || p == 0 || p == 100) pokazanyProcent = p;
    char linia[48];
    snprintf(linia, sizeof(linia), "bat:%.2f:%d:%s", napiecie, pokazanyProcent, stan());
    siecWyslij(linia);
  }
}
