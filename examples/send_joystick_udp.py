"""Envoi du joystick au Waffle en UDP — brique réutilisable pour l'appli EEG.

Le robot (nœud `joystick_teleop` sur le Pi) écoute des datagrammes UDP JSON
`{"jx": <-1..1>, "jy": <-1..1>}` sur le port 5005.
  - jy > 0 -> le robot avance ; jy < 0 -> recule
  - jx > 0 -> tourne à droite ; jx < 0 -> à gauche
  - aucun paquet pendant 0.5 s -> le robot s'arrête (watchdog)

=> Le décodeur EEG n'a qu'à appeler `sender.send(jx, jy)` en boucle (~10-20 Hz).
Aucune dépendance (stdlib uniquement), pas de ROS2 nécessaire côté PC.

Démo : python send_joystick_udp.py 10.191.69.104
(⚠️ roues en l'air) avance ~2 s, virage ~2 s, diagonale ~2 s, puis stop.
"""

import json
import socket
import sys
import time


class JoystickSender:
    def __init__(self, host, port=5005):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, jx, jy):
        """Envoie un point joystick. jx, jy seront bornés à [-1, 1]."""
        jx = max(-1.0, min(1.0, float(jx)))
        jy = max(-1.0, min(1.0, float(jy)))
        payload = json.dumps({"jx": round(jx, 3), "jy": round(jy, 3)}).encode("utf-8")
        self.sock.sendto(payload, self.addr)

    def hold(self, jx, jy, duration_s, rate_hz=15.0):
        """Maintient une consigne pendant duration_s en ré-émettant à rate_hz
        (indispensable : sans réémission, le watchdog du robot coupe à 0.5 s)."""
        period = 1.0 / rate_hz
        t_end = time.time() + duration_s
        while time.time() < t_end:
            self.send(jx, jy)
            time.sleep(period)

    def stop(self):
        """Consigne neutre. (Le watchdog arrête aussi tout seul si on cesse d'émettre.)"""
        self.send(0.0, 0.0)

    def close(self):
        self.sock.close()


def _demo(host):
    js = JoystickSender(host)
    print(f"[demo] envoi vers {host}:5005  (roues en l'air !)")
    try:
        print("[demo] avance (jy=0.6)")
        js.hold(0.0, 0.6, 2.0)
        print("[demo] virage droite (jx=0.6)")
        js.hold(0.6, 0.0, 2.0)
        print("[demo] diagonale avant-droite (jx=0.5, jy=0.5)")
        js.hold(0.5, 0.5, 2.0)
    finally:
        js.stop()
        js.close()
        print("[demo] stop.")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "10.191.69.104"
    _demo(target)
