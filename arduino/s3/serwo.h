#pragma once
// Sterowanie serwem SG90 obracającym kamerę.
// Ruch jest nieblokujący: serwoUpdate() przesuwa serwo o SERWO_KROK stopni
// co SERWO_OPOZNIENIE_MS, dopóki ustawiony jest kierunek lub nie zostanie osiągnięta skrajna pozycja.

void serwoBegin();
void serwoUstawKierunek(int k);    // -1 = lewo, 0 = stop, 1 = prawo
void serwoUpdate();                // wywoływane w loop()
int  serwoKat();                   // aktualny kąt 0-179
