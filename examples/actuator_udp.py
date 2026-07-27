"""Exemple : traduire une intention décodée en ACTION, ici des datagrammes UDP-JSON.

C'est le patron « l'action appartient au client » (SPEC §9). L'API publie une intention
neutre — quelle cible, quelle classe, quel état mental — et ne sait pas ce qu'on en fait.
Décider qu'une cible signifie « avance » est le travail de l'application avale, et ce
fichier montre à quoi ressemble ce travail réduit au minimum.

Le transport est volontairement trivial : un datagramme UDP JSON, aucune dépendance hors
stdlib. Un actionneur qui écoute ça s'écrit en dix lignes dans n'importe quel langage, sans
installer LSL — c'est l'issue de secours pour un microcontrôleur ou une carte embarquée à
qui on ne veut rien imposer.

⚠️ **Fire-and-forget** : UDP ne garantit rien et ne rend aucun accusé. D'où `hold()`, qui
ré-émet en continu : un actionneur bien conçu s'arrête de lui-même quand le flux se tait
(chien de garde), ce qui est la bonne façon de s'arrêter quand le décodage ne dit plus rien.

⚠️ **Les clés `jx`/`jy` du JSON sont conservées telles quelles.** Elles datent du banc
d'essai robot, dont le récepteur les attend encore : les renommer casserait un montage qui
marche, pour un gain purement cosmétique. Un nouveau projet est libre de choisir ses propres
noms — c'est son contrat, pas celui de l'API.

*(Hérité du banc d'essai qui a servi à valider le décodage, voir docs/robot_testbed.md. Le
robot n'est plus un objectif du produit ; ce fichier reste comme exemple de sortie
applicative.)*

Démo :
    python examples/actuator_udp.py 192.168.1.42
"""

import json
import socket
import sys
import time

DEFAULT_PORT = 5005


class ActuatorSender:
    """Émetteur UDP-JSON d'une consigne à deux axes normalisés, bornés à [-1, 1]."""

    def __init__(self, host, port=DEFAULT_PORT):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, jx, jy):
        """Envoie une consigne à deux axes. `jx` et `jy` sont bornés à [-1, 1]."""
        jx = max(-1.0, min(1.0, float(jx)))
        jy = max(-1.0, min(1.0, float(jy)))
        payload = json.dumps({"jx": round(jx, 3), "jy": round(jy, 3)}).encode("utf-8")
        self.sock.sendto(payload, self.addr)

    def hold(self, jx, jy, duration_s, rate_hz=15.0):
        """Maintient une consigne en la ré-émettant à `rate_hz` : sans flux continu, un
        actionneur muni d'un chien de garde s'arrête (typiquement au bout de 0,5 s)."""
        period = 1.0 / rate_hz
        t_end = time.time() + duration_s
        while time.time() < t_end:
            self.send(jx, jy)
            time.sleep(period)

    def stop(self):
        """Consigne neutre. Cesser d'émettre arrête aussi, via le chien de garde."""
        self.send(0.0, 0.0)

    def close(self):
        self.sock.close()


# Ancien nom, du temps où ce fichier était spécifique au joystick d'un robot. Conservé pour
# ne pas casser un script d'étudiant ni une vieille branche qui l'importerait encore.
JoystickSender = ActuatorSender


def _demo(host):
    out = ActuatorSender(host)
    print(f"[demo] envoi vers {host}:{DEFAULT_PORT}")
    try:
        for label, (jx, jy) in (("avant", (0.0, 0.6)), ("droite", (0.6, 0.0)),
                                ("diagonale", (0.5, 0.5))):
            print(f"[demo] {label} -> jx={jx} jy={jy}")
            out.hold(jx, jy, 2.0)
    finally:
        out.stop()
        out.close()
        print("[demo] stop.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("usage : python examples/actuator_udp.py <hôte> [port]")
        sys.exit(1)
    _demo(sys.argv[1])
