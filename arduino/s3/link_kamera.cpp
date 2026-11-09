#include <Arduino.h>
#include "konfiguracja.h"
#include "link_kamera.h"

static bool wifiKamery = false;

void linkKameraBegin() {
  Serial1.begin(LINK_BAUD, SERIAL_8N1, LINK_RX, LINK_TX);
}

bool kameraWifiOk() {
  return wifiKamery;
}

void linkKameraUpdate() {
  if (Serial1.available()) {
    String msg = Serial1.readStringUntil('\n');
    msg.trim();
    if (!msg.length()) return;

    Serial.print("[KAMERA] ");
    Serial.println(msg);

    if (msg.startsWith("WIFI_CONNECTED"))     wifiKamery = true;
    else if (msg == "WIFI_DISCONNECTED")      wifiKamery = false;
  }
}
