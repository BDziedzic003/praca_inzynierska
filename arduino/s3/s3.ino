/*
  Sterownik robota ratowniczego - ESP32-S3.

  Moduły:
    serwo.*        obrót kamery (SG90)
    silniki.*      napęd (2 silniki DC, TB6612)
    siec.*         Wi-Fi, mDNS (s3.local), serwer komend TCP
    link_kamera.*  odbiór komunikatów z ESP32-CAM przez UART
    bateria.*      pomiar napięcia baterii i blokada jazdy
    audio.*        transmisja dźwięku (INMP441, MAX98357A, UDP)
    konfiguracja.h parametry i przypisanie pinów

  Klientem sterownika jest aplikacja serwerowa (serwer.py), która przekazuje komendy
  operatorów i odbiera raporty stanu baterii oraz dźwięk z mikrofonu.

  Komendy TCP (port 8080, zakończone '\n'):
    kamera:  left / right / camstop
    jazda:   forward[:v] / backward[:v] / spinleft[:v] / spinright[:v] / drivestop   (v = 0-255)
    ogólne:  stop (kamera + jazda), ping (heartbeat)
    audio:   mic:1 / mic:0

  Połączenia:
    UART do kamery:   GPIO18 (RX) <- CAM GPIO13 (TX), GPIO17 (TX) -> CAM GPIO14 (RX)
    Bateria:          dzielnik 47k/10k -> GPIO5
    Głośnik:          MAX98357A  BCLK=12, LRCLK=11, DIN=10
    Mikrofon:         INMP441    SCK=13, WS=8, SD=6
    Serwo:            GPIO9
    Silniki (TB6612): STBY=7, AIN1=4, AIN2=2, PWMA=1, BIN1=15, BIN2=16, PWMB=14
                      VM z pakietu akumulatorów, VCC z wyjścia 3,3 V płytki
    Zasilanie 5 V:    przetwornica LM2596 (ESP32-S3-Pico, ESP32-CAM, serwo, MAX98357A)
    Masa wspólna dla wszystkich modułów.
*/

#include "konfiguracja.h"
#include "serwo.h"
#include "silniki.h"
#include "siec.h"
#include "link_kamera.h"
#include "bateria.h"
#include "audio.h"

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\nSterownik S3 - start");

  serwoBegin();          // ustawienie serwa w pozycji środkowej
  silnikiBegin();
  linkKameraBegin();
  bateriaBegin();
  siecBegin();           // blokuje do czasu połączenia z Wi-Fi
  audioBegin();          // zadania audio działają niezależnie od loop()

  Serial.println("Gotowy. Czekam na komendy i debug z kamery.");
}

void loop() {
  siecUpdate();
  linkKameraUpdate();
  serwoUpdate();
  silnikiUpdate();
  bateriaUpdate();
}
