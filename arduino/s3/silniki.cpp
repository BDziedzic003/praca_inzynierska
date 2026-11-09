#include <Arduino.h>
#include "konfiguracja.h"
#include "silniki.h"

// Parametry rampy
#define CZAS_ROZPEDZANIA_MS 600   // czas narastania PWM od 0 do 255
#define CZAS_HAMOWANIA_MS   300   // czas opadania PWM od 255 do 0
#define PWM_START           50    // minimalne wypełnienie, przy którym silniki ruszają
#define KROK_MS             10    // okres aktualizacji PWM

// Kierunek i prędkość: zadane (cel) i bieżące (akt), osobno dla silników A i B
static int celKierA = 0, celPredA = 0, aktKierA = 0, aktPredA = 0;
static int celKierB = 0, celPredB = 0, aktKierB = 0, aktPredB = 0;

static void ustawSilnikA(int kierunek, int predkosc) {
  predkosc = constrain(predkosc, 0, 255);

  if (kierunek == 1) {
    digitalWrite(AIN1, HIGH);
    digitalWrite(AIN2, LOW);
  } else if (kierunek == -1) {
    digitalWrite(AIN1, LOW);
    digitalWrite(AIN2, HIGH);
  } else {
    digitalWrite(AIN1, LOW);
    digitalWrite(AIN2, LOW);
    predkosc = 0;
  }
  analogWrite(PWMA, predkosc);
}

static void ustawSilnikB(int kierunek, int predkosc) {
  predkosc = constrain(predkosc, 0, 255);

  if (kierunek == 1) {
    digitalWrite(BIN1, HIGH);
    digitalWrite(BIN2, LOW);
  } else if (kierunek == -1) {
    digitalWrite(BIN1, LOW);
    digitalWrite(BIN2, HIGH);
  } else {
    digitalWrite(BIN1, LOW);
    digitalWrite(BIN2, LOW);
    predkosc = 0;
  }
  analogWrite(PWMB, predkosc);
}

// Jeden krok rampy dla jednego silnika.
// Przy zmianie kierunku silnik jest najpierw hamowany do zera.
static void krokRozpedu(int &aktKier, int &aktPred, int celKier, int celPred) {
  const int krokGora = max(1, (int)(255UL * KROK_MS / CZAS_ROZPEDZANIA_MS));
  const int krokDol  = max(1, (int)(255UL * KROK_MS / CZAS_HAMOWANIA_MS));

  if (aktKier != celKier) {
    if (aktPred > 0) aktPred = max(0, aktPred - krokDol);
    if (aktPred == 0) aktKier = celKier;
  } else if (aktKier != 0) {
    if (aktPred < celPred) {
      int nowa = (aktPred < PWM_START) ? PWM_START : aktPred + krokGora;
      aktPred = min(nowa, celPred);
    } else if (aktPred > celPred) {
      aktPred = max(celPred, aktPred - krokDol);
    }
  }
}

void silnikiUpdate() {
  static unsigned long ostatni = 0;
  unsigned long teraz = millis();
  if (teraz - ostatni < KROK_MS) return;
  ostatni = teraz;

  krokRozpedu(aktKierA, aktPredA, celKierA, celPredA);
  krokRozpedu(aktKierB, aktPredB, celKierB, celPredB);

  ustawSilnikA(aktKierA, aktPredA);
  ustawSilnikB(aktKierB, aktPredB);
}

void silnikiBegin() {
  pinMode(STBY, OUTPUT);
  pinMode(AIN1, OUTPUT);
  pinMode(AIN2, OUTPUT);
  pinMode(PWMA, OUTPUT);
  pinMode(BIN1, OUTPUT);
  pinMode(BIN2, OUTPUT);
  pinMode(PWMB, OUTPUT);

  digitalWrite(STBY, HIGH);  // wyprowadzenie TB6612 ze stanu czuwania
  silnikiStop();
}

static void ustawCel(int kierA, int kierB, int predkosc) {
  predkosc = constrain(predkosc, 0, 255);
  celKierA = kierA; celPredA = predkosc;
  celKierB = kierB; celPredB = predkosc;
}

void silnikiJedzDoPrzodu(int predkosc) {
  ustawCel(1, 1, predkosc);
}

void silnikiJedzDoTylu(int predkosc) {
  ustawCel(-1, -1, predkosc);
}

void silnikiSkretWLewo(int predkosc) {
  ustawCel(-1, 1, predkosc);
}

void silnikiSkretWPrawo(int predkosc) {
  ustawCel(1, -1, predkosc);
}

void silnikiStop() {
  celKierA = celKierB = 0;
  celPredA = celPredB = 0;
  aktKierA = aktKierB = 0;
  aktPredA = aktPredB = 0;
  ustawSilnikA(0, 0);
  ustawSilnikB(0, 0);
}
