#pragma once
// Dwukierunkowa transmisja dźwięku (tryb półdupleksowy).
//
//   mikrofon INMP441 (I2S) -> UDP -> serwer      (port AUDIO_PORT_MIKROFON)
//   serwer -> UDP -> wzmacniacz MAX98357A (I2S)   (port AUDIO_PORT_GLOSNIK)
//
// Format: 16 kHz, 16 bit, mono, surowe próbki PCM (little-endian).
// Mikrofon i głośnik obsługiwane są w osobnych zadaniach FreeRTOS, niezależnie od loop().
// Nadawanie z mikrofonu włączane jest komendą TCP "mic:1", wyłączane "mic:0".
#include <IPAddress.h>

void audioBegin();
void audioUstawOdbiorce(IPAddress ip);  // adres serwera; 0.0.0.0 = brak odbiorcy
void audioMikrofon(bool wlaczony);
