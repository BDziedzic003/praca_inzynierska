#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <ESP_I2S.h>
#include "konfiguracja.h"
#include "audio.h"

static I2SClass glosnik;
static I2SClass mikrofon;

static volatile uint32_t odbiorcaIp = 0;    // adres IPv4 serwera, 0 = brak
static volatile bool mikWlaczony = false;

void audioUstawOdbiorce(IPAddress ip) {
  odbiorcaIp = (uint32_t)ip;
}

void audioMikrofon(bool wlaczony) {
  mikWlaczony = wlaczony;
}

// Zadanie: mikrofon -> UDP
static void zadanieMikrofon(void *) {
  WiFiUDP udp;
  static int32_t surowe[AUDIO_PROBKI_PAKIET * 2];   // ramki stereo L, R, ...; mikrofon w kanale L
  static int16_t pakiet[AUDIO_PROBKI_PAKIET];
  float poprzX = 0, poprzY = 0;                      // stan filtru górnoprzepustowego

  for (;;) {
    size_t bajty = mikrofon.readBytes((char *)surowe, sizeof(surowe));
    int n = bajty / 8;                               // 8 bajtów = para próbek L+R
    uint32_t ip = odbiorcaIp;
    if (!mikWlaczony || ip == 0 || n == 0) continue; // odczyt trwa nadal, aby nie przepełnić bufora I2S

    for (int i = 0; i < n; i++) {
      float x = (float)(surowe[2 * i] >> 16);        // kanał L, 24 bit -> 16 bit
      float y = x - poprzX + 0.995f * poprzY;        // usunięcie składowej stałej
      poprzX = x; poprzY = y;
      int32_t s = (int32_t)(y * MIC_WZMOCNIENIE);
      pakiet[i] = (int16_t)constrain(s, -32768, 32767);
    }
    udp.beginPacket(IPAddress(ip), AUDIO_PORT_MIKROFON);
    udp.write((uint8_t *)pakiet, n * 2);
    udp.endPacket();
  }
}

// Zadanie: UDP -> głośnik
static void zadanieGlosnik(void *) {
  WiFiUDP udp;
  udp.begin(AUDIO_PORT_GLOSNIK);
  static int16_t bufor[AUDIO_PROBKI_PAKIET * 2];
  static int16_t cisza[64] = {0};                    // 4 ms ciszy

  for (;;) {
    int dlugosc = udp.parsePacket();
    if (dlugosc > 0) {
      int odczyt = udp.read((uint8_t *)bufor, min(dlugosc, (int)sizeof(bufor)));
      int n = odczyt / 2;
      for (int i = 0; i < n; i++) {
        int32_t s = (int32_t)(bufor[i] * GLOSNIK_GLOSNOSC);
        bufor[i] = (int16_t)constrain(s, -32768, 32767);
      }
      glosnik.write((uint8_t *)bufor, n * 2);        // zapis blokujący w tempie odtwarzania
    } else {
      // Brak danych: krótkie porcje ciszy, dzięki czemu kolejny pakiet
      // jest odtwarzany niemal bez opóźnienia.
      glosnik.write((uint8_t *)cisza, sizeof(cisza));
    }
  }
}

void audioBegin() {
  // Głośnik: 16 bit, mono
  glosnik.setPins(PIN_GLOSNIK_BCLK, PIN_GLOSNIK_LRCLK, PIN_GLOSNIK_DIN);
  if (!glosnik.begin(I2S_MODE_STD, AUDIO_CZESTOTLIWOSC, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO)) {
    Serial.println("AUDIO: blad uruchamiania glosnika (I2S)");
    return;
  }
  // Mikrofon: 32 bit, stereo (INMP441 przesyła 24 bity w 32-bitowej ramce, kanał L)
  mikrofon.setPins(PIN_MIC_SCK, PIN_MIC_WS, -1, PIN_MIC_SD);
  if (!mikrofon.begin(I2S_MODE_STD, AUDIO_CZESTOTLIWOSC, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO)) {
    Serial.println("AUDIO: blad uruchamiania mikrofonu (I2S)");
    return;
  }

  xTaskCreatePinnedToCore(zadanieMikrofon, "mikrofon", 6144, NULL, 3, NULL, 1);
  xTaskCreatePinnedToCore(zadanieGlosnik,  "glosnik",  6144, NULL, 3, NULL, 1);
  Serial.printf("AUDIO: gotowe (glosnik UDP %d, mikrofon -> serwer UDP %d)\n",
                AUDIO_PORT_GLOSNIK, AUDIO_PORT_MIKROFON);
}
