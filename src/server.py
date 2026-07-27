"""Moteur headless : casque Unicorn -> flux LSL. C'est le MVP de docs/SPEC.md §10.

Ce fichier est le **cœur du produit** : il tourne SANS interface graphique. L'application
pygame (`src/app.py`), le futur tableau de bord web et le code d'un étudiant sont tous, du
point de vue du moteur, des clients qui écoutent les mêmes flux.

Ce qu'il publie aujourd'hui (SPEC §4) :
    EEG_API_Unicorn_raw       les 8 voies, µV, 250 Hz
    EEG_API_Unicorn_quality   σ par voie, ~1 Hz (électrode décollée ?)
    EEG_API_Unicorn_status    état du moteur, JSON, à chaque changement + périodique

Pas encore : les flux `decoded_*`, le control plane entrant, les marqueurs. Ils viendront
poser leurs publications sur le même squelette de boucle.

Lancer :
    python src/server.py --synthetic       # sans casque (board de test BrainFlow)
    python src/server.py                    # vrai Unicorn
    python src/server.py --duration 60      # s'arrête tout seul au bout de 60 s
    python src/server.py --smoke            # test headless de bout en bout (CI)
"""

import argparse
import os
import signal
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from acquisition import UnicornAcquisition  # noqa: E402
from config import CH_NAMES, use_utf8_console  # noqa: E402
from lsl_io import (ClockBridge, QualityPublisher, RawPublisher,  # noqa: E402
                    StatusPublisher, stream_name, verdict_from_sigma)

# Cadence de la boucle. On ne publie PAS échantillon par échantillon : on ramasse ~50 ms de
# signal d'un coup. Assez court pour rester très en dessous des fenêtres de décision d'un
# mode BCI (1-2 s), assez long pour ne pas réveiller le processus 250 fois par seconde.
POLL_S = 0.05
QUALITY_PERIOD_S = 1.0    # cadence du flux `quality`
STATUS_PERIOD_S = 2.0     # rappel périodique de l'état (pour un client qui arrive en retard)
QUALITY_WINDOW_S = 2.0    # longueur de signal sur laquelle on mesure le σ par voie


class EngineServer:
    """Boucle acquisition -> publication. Un objet, une session casque, trois flux."""

    def __init__(self, serial=None, synthetic=False, verbose=False):
        self.synthetic = synthetic
        self.acq = UnicornAcquisition(serial=serial, synthetic=synthetic, verbose=verbose)
        self.clock = ClockBridge()
        self.raw_out = RawPublisher(ch_names=CH_NAMES, fs=self.acq.fs)
        self.quality_out = QualityPublisher(ch_names=CH_NAMES)
        self.status_out = StatusPublisher()
        self.samples = 0
        self._stop = False
        # Tampon de qualité : le σ se mesure sur QUALITY_WINDOW_S de signal, mais la boucle
        # vide le tampon BrainFlow à chaque tour (cf. get_new_data). On garde donc nous-mêmes
        # les dernières secondes publiées — c'est le « tampon du moteur » annoncé dans
        # acquisition.get_new_data, en tout petit.
        self._recent = np.zeros((0, len(CH_NAMES)))

    def stop(self):
        self._stop = True

    def _status_key(self, running):
        """Ce qui constitue un vrai CHANGEMENT d'état — hors compteurs (cf. StatusPublisher.push)."""
        return (running, self.synthetic, None)  # (marche, board, mode actif)

    def _state(self, running):
        return {
            "running": running,
            "board": "synthetic" if self.synthetic else "unicorn",
            "fs_hz": float(self.acq.fs),
            "channels": list(CH_NAMES),
            "mode": None,            # aucun décodeur au MVP
            "samples_published": self.samples,
            "streams": [stream_name(s) for s in ("raw", "quality", "status")],
        }

    def _publish_quality(self, lsl_ts):
        """σ par voie sur les dernières secondes, calculé sur du signal FILTRÉ.

        Le filtrage est indispensable ICI (contrairement au flux brut) : sur du signal
        quasi-brut, le σ est dominé par le ronflement secteur 50 Hz et la dérive lente des
        électrodes sèches, pas par l'EEG — un σ mesuré ainsi ne dit rien de l'état du contact.

        Le calcul est délégué à `sigma_from_block` pour partager UNE seule définition du σ
        avec l'écran `signal_check` de l'appli : deux mesures de qualité qui divergeraient
        seraient pires que pas de mesure du tout.
        """
        sigmas = self.acq.sigma_from_block(self._recent)
        if sigmas is not None:
            self.quality_out.push(sigmas, lsl_ts)

    def run(self, duration_s=None):
        """Boucle principale. `duration_s=None` = jusqu'à Ctrl+C."""
        started = time.perf_counter()
        last_quality = last_status = 0.0
        # + margin_n : le σ se calcule sur QUALITY_WINDOW_S de signal APRÈS avoir jeté le
        # transitoire du filtre, il faut donc garder les deux (cf. sigma_from_block).
        keep = int(QUALITY_WINDOW_S * self.acq.fs) + self.acq.margin_n

        with self.acq:
            print(f"[server] board={self.acq.board_id.name} fs={self.acq.fs} Hz")
            for suffix in ("raw", "quality", "status"):
                print(f"[server] flux LSL publie : {stream_name(suffix)}")
            self.status_out.push(self._state(True), key=self._status_key(True), force=True)

            while not self._stop:
                now = time.perf_counter()
                if duration_s is not None and now - started >= duration_s:
                    break

                eeg, ts_unix = self.acq.get_new_data()
                if eeg is not None and len(eeg):
                    self.samples += self.raw_out.push(eeg, self.clock.to_lsl(ts_unix))
                    self._recent = np.vstack([self._recent, eeg])[-keep:]

                if now - last_quality >= QUALITY_PERIOD_S:
                    self._publish_quality(self.clock.to_lsl(time.time()))
                    last_quality = now

                # Publié quand l'état change, plus un rappel périodique pour les clients qui
                # se connectent après le démarrage (LSL ne rejoue pas le passé).
                due = now - last_status >= STATUS_PERIOD_S
                if self.status_out.push(self._state(True), key=self._status_key(True),
                                        force=due) and due:
                    last_status = now

                time.sleep(POLL_S)

            self.status_out.push(self._state(False), key=self._status_key(False), force=True)

        elapsed = time.perf_counter() - started
        print(f"[server] arrêt : {self.samples} échantillons publiés en {elapsed:.1f} s "
              f"({self.samples / max(elapsed, 1e-9):.1f} Hz effectif)")
        return self.samples


def _smoke():
    """Test de bout en bout sans casque : le serveur publie, un client local reçoit.

    Vérifie ce qui casserait silencieusement : la continuité du flux (pas de trou), la
    cadence réelle vs les 250 Hz annoncés, et la présence du flux qualité.
    """
    import threading

    from pylsl import StreamInlet, resolve_byprop

    server = EngineServer(synthetic=True)

    # Garde-fou : `_filter` ne doit JAMAIS modifier son entrée. Le serveur lui passe un
    # tampon persistant ; s'il était filtré sur place, les échantillons bruts suivants
    # seraient collés sur une queue déjà filtrée et le σ deviendrait absurde (vécu le
    # 2026-07-27 : 40 000 µV mesurés sur un EEG à 5 µV). Un tableau contigu float64 est
    # exactement le cas qui déclenchait le bug.
    probe = np.full((300, len(CH_NAMES)), 150000.0, dtype=np.float64)
    untouched = probe.copy()
    server.acq._filter(probe)
    if not np.array_equal(probe, untouched):
        print("[smoke] ÉCHEC : _filter modifie son entrée (voir acquisition._filter)")
        return False
    thread = threading.Thread(target=server.run, kwargs={"duration_s": 6.0}, daemon=True)
    thread.start()

    raw = resolve_byprop("name", stream_name("raw"), timeout=10.0)
    qual = resolve_byprop("name", stream_name("quality"), timeout=5.0)
    stat = resolve_byprop("name", stream_name("status"), timeout=5.0)
    if not raw or not qual or not stat:
        print("[smoke] ÉCHEC : flux introuvables")
        server.stop()
        return False

    raw_in, qual_in = StreamInlet(raw[0], max_buflen=30), StreamInlet(qual[0], max_buflen=30)
    stat_in = StreamInlet(stat[0], max_buflen=30)
    raw_in.open_stream(timeout=5.0)   # sinon on rate tout ce qui précède le 1er pull
    qual_in.open_stream(timeout=5.0)
    stat_in.open_stream(timeout=5.0)

    got, stamps, quality_rows, status_rows = 0, [], 0, 0
    watch_started = time.perf_counter()
    deadline = watch_started + 7.0
    while time.perf_counter() < deadline and thread.is_alive():
        chunk, ts = raw_in.pull_chunk(timeout=0.2, max_samples=512)
        got += len(chunk)
        stamps.extend(ts)
        qchunk, _ = qual_in.pull_chunk(timeout=0.0, max_samples=16)
        quality_rows += len(qchunk)
        schunk, _ = stat_in.pull_chunk(timeout=0.0, max_samples=256)
        status_rows += len(schunk)
    watched_s = time.perf_counter() - watch_started
    thread.join(timeout=5.0)

    ok = True
    print(f"[smoke] reçu {got} échantillons, {quality_rows} mesures de qualité, "
          f"{status_rows} messages d'état")
    # L'état est *événementiel* : il doit se taire tant que rien ne change. Un compteur
    # glissé dans la charge utile avait suffi à le faire émettre à 19,6 Hz au lieu de 0,5 Hz
    # (dédup défaite) — assez discret pour passer inaperçu, assez bruyant pour noyer un
    # client. On garde donc une borne dure ici.
    status_hz = status_rows / max(watched_s, 1e-9)
    if status_hz > 3.0:
        print(f"[smoke] ÉCHEC : le flux d'état émet à {status_hz:.1f} Hz (déduplication cassée ?)")
        ok = False
    if got < 500:
        print("[smoke] ÉCHEC : trop peu d'échantillons reçus")
        ok = False
    if quality_rows < 2:
        print("[smoke] ÉCHEC : le flux qualité ne publie pas")
        ok = False
    if len(stamps) > 2:
        gaps = np.diff(np.asarray(stamps))
        rate = 1.0 / np.median(gaps)
        print(f"[smoke] cadence mesurée {rate:.1f} Hz, plus grand trou {gaps.max() * 1000:.1f} ms")
        # Le board synthétique tourne à 250 Hz nominal comme l'Unicorn ; un écart franc
        # signalerait un timestamp mal converti, pas un problème de débit.
        if not 200.0 < rate < 300.0:
            print("[smoke] ÉCHEC : cadence incohérente avec les 250 Hz annoncés")
            ok = False

    print(f"[smoke] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _parse_args(argv):
    p = argparse.ArgumentParser(description="EEG_API_Unicorn — moteur headless, sorties LSL.")
    p.add_argument("--synthetic", action="store_true", help="board de test BrainFlow (sans casque)")
    p.add_argument("--serial", default=None, help="numéro de série Unicorn (si plusieurs appairés)")
    p.add_argument("--duration", type=float, default=None, help="durée en s (défaut : jusqu'à Ctrl+C)")
    p.add_argument("--smoke", action="store_true", help="test headless de bout en bout, puis quitte")
    p.add_argument("--verbose", action="store_true", help="logs BrainFlow détaillés")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    args = _parse_args(sys.argv[1:])
    if args.smoke:
        sys.exit(0 if _smoke() else 1)

    engine = EngineServer(serial=args.serial, synthetic=args.synthetic, verbose=args.verbose)
    # Ctrl+C doit fermer PROPREMENT la session BrainFlow : une session laissée ouverte
    # empêche la suivante de s'ouvrir (BOARD_NOT_READY au relancement).
    signal.signal(signal.SIGINT, lambda *_: engine.stop())
    print("[server] Ctrl+C pour arrêter.")
    engine.run(duration_s=args.duration)
