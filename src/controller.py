"""Boucle d'intégration SSVEP : fenêtre EEG -> CCA -> lissage -> consigne -> UDP.

AUJOURD'HUI (sans casque) : `simulate()` fabrique des fenêtres SYNTHÉTIQUES selon un
scénario d'intentions, envoie l'UDP en local (127.0.0.1) vers un mini-récepteur intégré,
et VÉRIFIE que la sortie {jx,jy} suit bien l'intention. Ça valide toute la plomberie.

DEMAIN (avec casque) : `run_live(window_provider)` — on remplace la source de fenêtres par
BrainFlow (voies OCCIPITAL) ; le décodage, le lissage, le mapping et l'envoi ne changent pas.

Lancer la simulation :
    python src/controller.py
"""

import json
import os
import socket
import sys
import threading
import time
from collections import Counter, deque

import numpy as np

# Imports internes : marche en script (`python src/controller.py`) ou en import.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))                       # src/
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "examples"))                                  # ActuatorSender
from config import (FS_UNICORN, MARGIN, MIN_VOTES, RHO_MIN, UDP_HOST, UDP_PORT, VOTE_LEN,  # noqa: E402
                    WINDOW_S, apply_invert, choose_frequencies, use_utf8_console)
from cca_decoder import CCADecoder, synth_ssvep  # noqa: E402
from actuator_udp import ActuatorSender  # noqa: E402

STOP_CMD = {"name": "STOP", "jx": 0.0, "jy": 0.0}


class SSVEPController:
    """Décode + lisse. `decide(window)` -> commande (dict) lissée, ou None (=> stop).

    Lissage : vote majoritaire glissant sur les `vote_len` dernières décisions. Il faut
    au moins `min_votes` décisions concordantes pour changer/tenir une commande. Ça évite
    que le robot tremble sur une détection isolée. Le « None » (rien fixé) vote aussi :
    un consensus de non-détection => stop.
    """

    def __init__(self, plan, vote_len=VOTE_LEN, min_votes=MIN_VOTES, rho_min=RHO_MIN,
                 margin=MARGIN, fs=FS_UNICORN):
        self.plan = plan
        self.freq_to_cmd = {round(c["actual_hz"], 4): c for c in plan}
        self.decoder = CCADecoder([c["actual_hz"] for c in plan], fs=fs,
                                  rho_min=rho_min, margin=margin)
        self.buffer = deque(maxlen=vote_len)
        self.min_votes = min_votes

    def decide_scored(self, window):
        """Comme `decide()`, mais renvoie aussi les ρ — évite de relancer une CCA juste
        pour l'affichage (l'appli montre les scores ET la décision à chaque fenêtre)."""
        freq, scores = self.decoder.classify(window)
        label = None if freq is None else round(freq, 4)
        self.buffer.append(label)
        winner, count = Counter(self.buffer).most_common(1)[0]
        cmd = self.freq_to_cmd[winner] if (winner is not None and count >= self.min_votes) else None
        return cmd, scores

    def decide(self, window):
        return self.decide_scored(window)[0]

    def skip(self):
        """Fenêtre écartée (artefact) : on vote None sans la décoder.

        Voter plutôt qu'ignorer est délibéré — un artefact doit pousser vers l'ARRÊT, pas
        laisser la dernière commande se maintenir pendant qu'on ne voit plus rien.
        """
        self.buffer.append(None)
        winner, count = Counter(self.buffer).most_common(1)[0]
        return self.freq_to_cmd[winner] if (winner is not None and count >= self.min_votes) else None


def run_live(window_provider, plan=None, host=UDP_HOST, port=UDP_PORT,
             decode_hz=4.0, send_hz=15.0, **ctrl_kw):
    """Câblage temps réel pour DEMAIN (non exercé aujourd'hui : pas de casque).

    Deux threads : décodage à `decode_hz` (met à jour la consigne) et émission UDP à
    `send_hz` (ré-émet la consigne courante — indispensable au chien de garde de l'actionneur).
    `window_provider()` doit renvoyer la fenêtre EEG (T x C) la plus récente, ou None.
    Retourne (stop_event, sender) ; l'appelant fait `stop_event.set()` pour arrêter.
    """
    plan = plan or choose_frequencies(60)
    ctrl = SSVEPController(plan, **ctrl_kw)
    sender = ActuatorSender(host, port)
    state = dict(STOP_CMD)
    stop = threading.Event()

    def decode_loop():
        dt = 1.0 / decode_hz
        while not stop.is_set():
            w = window_provider()
            if w is not None:
                cmd = ctrl.decide(w)
                state.update(cmd if cmd is not None else STOP_CMD)
            time.sleep(dt)

    def send_loop():
        dt = 1.0 / send_hz
        while not stop.is_set():
            jx, jy = apply_invert(state["jx"], state["jy"])  # correction de sens (config)
            sender.send(jx, jy)
            time.sleep(dt)

    threading.Thread(target=decode_loop, daemon=True).start()
    threading.Thread(target=send_loop, daemon=True).start()
    return stop, sender


# --- Simulation end-to-end (aucun casque requis) ---------------------------

def _udp_listener(port, received, stop):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", port))
    sock.settimeout(0.2)
    while not stop.is_set():
        try:
            data, _ = sock.recvfrom(1024)
            received.append((time.perf_counter(), json.loads(data.decode("utf-8"))))
        except socket.timeout:
            pass
        except (ValueError, OSError):
            pass
    sock.close()


def simulate(port=UDP_PORT, snr_db=-6.0, seed=0):
    """Rejoue un scénario d'intentions -> UDP local -> vérifie la sortie {jx,jy}."""
    rng = np.random.default_rng(seed)
    plan = choose_frequencies(60)
    by_name = {c["name"]: c for c in plan}
    ctrl = SSVEPController(plan)
    sender = ActuatorSender("127.0.0.1", port)

    received, stop = [], threading.Event()
    listener = threading.Thread(target=_udp_listener, args=(port, received, stop), daemon=True)
    listener.start()
    time.sleep(0.2)  # laisse le socket se binder

    # Scénario : (intention | None, durée s). None = « regarde ailleurs » (=> STOP attendu).
    scenario = [("AVANT", 2.5), ("GAUCHE", 2.5), (None, 2.0), ("DROITE", 2.5)]
    window_n = int(round(WINDOW_S * FS_UNICORN))  # fenêtre glissante (config.WINDOW_S)
    decode_dt, send_hz = 0.25, 15.0
    sends_per_decode = max(1, round(decode_dt * send_hz))

    print(f"[sim] envoi UDP 127.0.0.1:{port}  |  fenêtre 2.0s  |  décode 4 Hz  |  émission {send_hz:.0f} Hz")
    print(f"[sim] scénario : {' -> '.join(n or 'RIEN' for n, _ in scenario)}\n")
    segments = []  # (name, t0, t1, exp_jx, exp_jy)
    for intent, dur in scenario:
        exp = by_name[intent] if intent else STOP_CMD
        freq = by_name[intent]["actual_hz"] if intent else None
        t0 = time.perf_counter()
        t_end = t0 + dur
        last = "?"
        while time.perf_counter() < t_end:
            if freq is None:
                w = rng.normal(0.0, 1.0, (window_n, 3))          # bruit = rien fixé
            else:
                w = synth_ssvep(freq, window_n, snr_db=snr_db, rng=rng)
            cmd = ctrl.decide(w)
            jx, jy = (cmd["jx"], cmd["jy"]) if cmd else (0.0, 0.0)
            last = cmd["name"] if cmd else "STOP"
            for _ in range(sends_per_decode):
                sender.send(jx, jy)
                time.sleep(1.0 / send_hz)
        segments.append((intent or "RIEN", t0, t_end, exp["jx"], exp["jy"]))
        print(f"[sim] intention {str(intent or 'RIEN'):<8} -> sortie décodée « {last} »")

    time.sleep(0.3)
    stop.set()
    listener.join(timeout=1.0)
    sender.close()

    # Vérification : sur chaque segment (après 1 s de latence de lissage), la consigne
    # {jx,jy} dominante reçue doit égaler l'attendu.
    print(f"\n[sim] {len(received)} datagrammes reçus. Vérification par segment :")
    print("segment  | attendu (jx,jy)  | reçu dominant    | %match | verdict")
    settle, all_ok = 1.0, True
    for name, t0, t1, ejx, ejy in segments:
        pts = [d for (ts, d) in received if t0 + settle <= ts <= t1]
        if not pts:
            print(f"{name:<8} | ({ejx:+.1f},{ejy:+.1f})       | (aucun)          |    -   | ?")
            all_ok = False
            continue
        modal, cnt = Counter((round(d["jx"], 3), round(d["jy"], 3)) for d in pts).most_common(1)[0]
        ok = (modal == (round(ejx, 3), round(ejy, 3)))
        all_ok &= ok
        print(f"{name:<8} | ({ejx:+.1f},{ejy:+.1f})       | ({modal[0]:+.1f},{modal[1]:+.1f})       "
              f"| {cnt/len(pts)*100:5.1f}% | {'OK' if ok else 'ECHEC'}")
    print(f"\n[sim] {'TOUT OK — la sortie suit l’intention.' if all_ok else 'ÉCHEC sur au moins un segment.'}")
    return all_ok


if __name__ == "__main__":
    use_utf8_console()
    ok = simulate()
    sys.exit(0 if ok else 1)
