#pragma once
// Łącze UART z modułem ESP32-CAM.
// Odbiera komunikaty diagnostyczne kamery (np. WIFI_CONNECTED / WIFI_DISCONNECTED),
// przekazuje je na port szeregowy ESP32-S3 i udostępnia stan połączenia Wi-Fi kamery.

void linkKameraBegin();      // inicjalizacja UART (Serial1)
void linkKameraUpdate();     // odczyt przychodzących linii, wywoływany w loop()
bool kameraWifiOk();         // true, jeśli kamera zgłosiła WIFI_CONNECTED
