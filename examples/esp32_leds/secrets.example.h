// Copy this file to secrets.h (ignored by git) and put in it the Wi-Fi network the console's
// computer is on too: that computer's mobile hotspot, or the Wi-Fi of a router. At 2.4 GHz: the
// ESP32 does not see 5 GHz.
#define WIFI_SSID "network-name"
#define WIFI_PASS "password"

// Optional, a second network: the ESP32 takes the one it sees, the strongest if it sees both.
// #define WIFI_SSID_2 "network-name-2"
// #define WIFI_PASS_2 "password-2"

// Optional: the IP address of the console's computer. Without it, the hello is broadcast on the
// network, which is usually enough; with it, the hello goes straight to that computer (useful if
// the console never lists the ESP32: a computer on several networks, a VPN). On the Windows
// mobile hotspot, the computer is at 192.168.137.1.
// #define CONSOLE_IP "192.168.137.1"
