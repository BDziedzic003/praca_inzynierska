#pragma once
// Konfiguracja sterownika ESP32-S3: sieć, przypisanie pinów i parametry modułów.

// --- Sieć Wi-Fi (wspólna z ESP32-CAM) ---
#define WIFI_SSID   "robot_projekt"
#define WIFI_HASLO  "xdxdxdxd"

// --- mDNS i serwer komend ---
#define MDNS_NAZWA   "s3"          // nazwa w sieci: s3.local
#define PORT_KOMEND  8080

// --- Watchdog ---
// Maksymalny czas bez komend (serwer wysyła "ping" co 200 ms), po którym robot jest zatrzymywany.
#define WATCHDOG_MS  600

// --- Serwo (obrót kamery) ---
#define PIN_SERWA            9
#define SERWO_MIN_US         500
#define SERWO_MAX_US         2400
#define SERWO_KROK           1     // krok ruchu [°]
#define SERWO_OPOZNIENIE_MS  15    // odstęp między krokami [ms]

// --- UART do ESP32-CAM ---
#define LINK_RX   18    // S3 GPIO18 <- CAM TX (GPIO13)
#define LINK_TX   17    // S3 GPIO17 -> CAM RX (GPIO14)
#define LINK_BAUD 115200

// --- Silniki (TB6612) ---
#define STBY   7     // wejście czuwania sterownika
#define AIN1   4     // silnik A - kierunek
#define AIN2   2
#define PWMA   1     // silnik A - prędkość (PWM)
#define BIN1   15    // silnik B - kierunek
#define BIN2   16
#define PWMB   14    // silnik B - prędkość (PWM)

#define PREDKOSC_DOMYSLNA  150   // 0-255, gdy komenda nie zawiera prędkości

// --- Bateria (pakiet 3S Li-ion) ---
// Dzielnik napięcia: plus baterii (za wyłącznikiem) -> R1 -> PIN_BATERIA -> R2 -> GND
#define PIN_BATERIA            5       // wejście ADC1 (ADC2 jest niedostępne przy aktywnym Wi-Fi)
#define BAT_R1                 47000.0f
#define BAT_R2                 10000.0f
#define BAT_KALIBRACJA         1.107f  // napięcie zmierzone multimetrem / napięcie wskazywane
#define BAT_OGNIWA             3
// Progi z zapasem na nierównomierne naładowanie ogniw (brak układu wyrównującego napięcia ogniw).
// Z układem BMS: OSTRZEZENIE 10.8, KRYTYCZNA 10.2, POWROT 10.6.
#define BAT_OSTRZEZENIE_V      11.1f   // próg ostrzeżenia
#define BAT_KRYTYCZNA_V        10.8f   // próg blokady jazdy
#define BAT_POWROT_V           11.1f   // próg zdjęcia blokady (histereza)
#define BAT_CZAS_KRYTYCZNY_MS  5000    // czas utrzymania napięcia poniżej progu krytycznego
#define BAT_MIN_POMIAR_V       5.0f    // poniżej: brak baterii, blokada nieaktywna
#define BAT_WYGLADZANIE        0.02f   // współczynnik filtru (0.02 ≈ 5 s stałej czasowej)

// --- Audio ---
// Wzmacniacz MAX98357A (zasilanie 5 V)
#define PIN_GLOSNIK_BCLK    12
#define PIN_GLOSNIK_LRCLK   11
#define PIN_GLOSNIK_DIN     10
// Mikrofon INMP441 (zasilanie 3,3 V, L/R -> GND)
#define PIN_MIC_SCK         13
#define PIN_MIC_WS          8
#define PIN_MIC_SD          6

#define AUDIO_CZESTOTLIWOSC 16000   // [Hz], zgodne z serwerem i aplikacjami
#define AUDIO_PROBKI_PAKIET 512     // próbek w pakiecie (32 ms)
#define AUDIO_PORT_GLOSNIK  8081    // odbiór dźwięku z serwera
#define AUDIO_PORT_MIKROFON 8082    // wysyłanie dźwięku do serwera
#define MIC_WZMOCNIENIE     4.0f    // wzmocnienie programowe mikrofonu
#define GLOSNIK_GLOSNOSC    1.0f    // współczynnik głośności 0.0-1.0
