#pragma once
// Napęd robota: dwa silniki DC sterowane przez mostek TB6612.
// Funkcje jazdy ustawiają wartości zadane, a silnikiUpdate() realizuje
// płynne przyspieszanie i hamowanie (rampa PWM).

void silnikiBegin();

void silnikiJedzDoPrzodu(int predkosc);   // prędkość 0-255
void silnikiJedzDoTylu(int predkosc);
void silnikiSkretWLewo(int predkosc);     // obrót w miejscu
void silnikiSkretWPrawo(int predkosc);
void silnikiStop();                       // zatrzymanie natychmiastowe, bez rampy
void silnikiUpdate();                     // wywoływane w loop()
