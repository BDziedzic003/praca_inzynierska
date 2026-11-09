#pragma once
// Komunikacja sieciowa ESP32-S3.
// Połączenie z Wi-Fi (tryb STA), rozgłaszanie nazwy w mDNS (s3.local) oraz serwer TCP
// przyjmujący komendy tekstowe od serwera. Zawiera zabezpieczenia:
// zatrzymanie robota po rozłączeniu klienta oraz watchdog braku komend.

void siecBegin();
void siecUpdate();                    // obsługa klienta i komend, wywoływane w loop()
bool siecKlientPolaczony();
void siecWyslij(const char* linia);   // wysłanie linii tekstu do serwera
