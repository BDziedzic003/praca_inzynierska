#pragma once
// Monitorowanie baterii 3S Li-ion.
// Napięcie mierzone jest przez dzielnik rezystorowy (R1 = 47k, R2 = 10k) na wejściu PIN_BATERIA.
// - pomiar co 100 ms z uśrednianiem i filtrem wygładzającym,
// - raport do serwera co 1 s:  bat:<napięcie>:<procent>:<stan>
//   (stan: ok / niski / krytyczny / brak),
// - blokada jazdy, gdy napięcie pozostaje poniżej progu krytycznego dłużej niż BAT_CZAS_KRYTYCZNY_MS
//   (działa niezależnie od serwera).

void  bateriaBegin();
void  bateriaUpdate();        // wywoływane w loop()
float bateriaNapiecie();      // napięcie pakietu po filtracji [V]
int   bateriaProcent();       // szacowany stan naładowania 0-100 %
bool  bateriaKrytyczna();     // true = jazda zablokowana
