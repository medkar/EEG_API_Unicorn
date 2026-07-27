"""Acquisition Unicorn via BrainFlow -> fenêtre glissante des voies occipitales.

Fournit un `get_window()` prêt pour `controller.run_live` : à chaque appel, la dernière
fenêtre de `window_s` s des voies occipitales (PO7, Oz, PO8), filtrée (detrend + bandpass
+ notch 50 Hz).

⚠️ IMPORTANT — le chemin UNICORN n'est PAS testé (pas de casque le 2026-07-16). Il est en
revanche VALIDÉ sur le board SYNTHÉTIQUE de BrainFlow (`--synthetic`), qui exerce toute la
plomberie : session, indexation des voies, fenêtrage, filtres, forme (500, 3). Demain, il
suffit de lancer SANS `--synthetic` et de déboguer sur le vrai flux.

Prérequis Unicorn (demain) : casque chargé + appairé en Bluetooth. BrainFlow parle au
casque via l'API Unicorn de g.tec (aucun ROS2). fs = 250 Hz, 8 voies EEG sur les rows 0..7
(ordre g.tec : Fz, C3, Cz, C4, Pz, PO7, Oz, PO8).

Lancer :
    python src/acquisition.py --synthetic          # smoke test plomberie (sans casque)
    python src/acquisition.py --synthetic --run     # + boucle run_live -> UDP 127.0.0.1
    python src/acquisition.py                        # DEMAIN : vrai Unicorn
    python src/acquisition.py --serial UN-2019.05.51 # si plusieurs Unicorn appairés
"""

import argparse
import os
import sys
import time

import numpy as np
from brainflow.board_shim import BoardShim, BoardIds, BrainFlowInputParams
from brainflow.data_filter import DataFilter, DetrendOperations, FilterTypes, NoiseTypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (BANDPASS, CH_NAMES, FILTER_MARGIN_S, OCCIPITAL, UDP_PORT,  # noqa: E402
                    UNICORN_SERIAL, WINDOW_S, use_utf8_console)


class UnicornAcquisition:
    """Session BrainFlow + extraction de la fenêtre occipitale la plus récente.

    `synthetic=True` utilise le board de test de BrainFlow (aucun casque) pour valider le
    code. `get_window()` renvoie (window_n x len(OCCIPITAL)) ou None tant que le buffer
    n'est pas rempli.
    """

    def __init__(self, serial=None, window_s=WINDOW_S, synthetic=False,
                 bandpass=BANDPASS, notch=NoiseTypes.FIFTY, order=4, verbose=False):
        self.board_id = BoardIds.SYNTHETIC_BOARD if synthetic else BoardIds.UNICORN_BOARD
        if serial is None and not synthetic:
            serial = UNICORN_SERIAL  # par défaut : le casque déclaré dans config.py
        self.fs = BoardShim.get_sampling_rate(self.board_id)
        self.window_n = int(round(window_s * self.fs))
        self.margin_n = int(round(FILTER_MARGIN_S * self.fs))   # jetée après filtrage
        self.bandpass = bandpass
        self.notch = notch
        self.order = order

        # OCCIPITAL indexe la LISTE des voies EEG (ordre device). Sur Unicorn : rows 5,6,7.
        eeg = BoardShim.get_eeg_channels(self.board_id)
        # On tronque à len(CH_NAMES)=8 : le board SYNTHÉTIQUE en expose 16, et un modèle
        # entraîné sur l'Unicorn (8 voies) planterait au décodage en mode --synthetic.
        self.eeg_rows = list(eeg)[:len(CH_NAMES)]       # les 8 voies EEG (pour MI / c-VEP)
        self.occ_rows = [eeg[i] for i in OCCIPITAL]
        self.occ_names = [CH_NAMES[i] for i in OCCIPITAL]
        # Canal timestamp BrainFlow (temps Unix par échantillon) : sert au P300 à découper les
        # époques calées sur chaque flash SANS dérive d'horloge (cf. get_raw).
        self.ts_row = BoardShim.get_timestamp_channel(self.board_id)

        params = BrainFlowInputParams()
        if serial:
            params.serial_number = serial
        (BoardShim.enable_dev_board_logger if verbose else BoardShim.disable_board_logger)()
        self.board = BoardShim(self.board_id, params)

    def start(self):
        self.board.prepare_session()
        self.board.start_stream()
        return self

    def stop(self):
        try:
            if self.board.is_prepared():
                self.board.stop_stream()
                self.board.release_session()
        except Exception:  # noqa: BLE001 - l'arrêt ne doit jamais masquer l'erreur d'origine
            pass

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def _filter(self, sig):
        """Detrend + bandpass + notch 50 Hz. Rend un NOUVEAU tableau, sans toucher à `sig`.

        ⚠️ Ne jamais remplacer ce `np.array(..., copy=True)` par `np.ascontiguousarray` :
        celui-ci rend l'objet TEL QUEL quand il est déjà float64 C-contigu, et le filtrage
        écrase alors les données de l'appelant. Le bug a existé (2026-07-27) et il est
        sournois : tous les appelants historiques passent `data[rows, :].T`, une vue
        TRANSPOSÉE donc non contiguë, qui était copiée par chance. Le premier appelant à
        passer un tampon persistant et contigu (le serveur LSL) a vu son tampon se faire
        filtrer sur place, puis re-filtrer à chaque tour, avec une marche géante à la
        frontière entre la partie déjà filtrée et les échantillons bruts fraîchement
        ajoutés — σ mesuré 40 000 µV pour un EEG à 5 µV.
        """
        out = np.array(sig, dtype=np.float64, order="C")
        lo, hi = self.bandpass
        for c in range(out.shape[1]):
            col = np.ascontiguousarray(out[:, c])
            DataFilter.detrend(col, DetrendOperations.CONSTANT.value)
            DataFilter.perform_bandpass(col, self.fs, lo, hi, self.order,
                                        FilterTypes.BUTTERWORTH.value, 0.0)
            DataFilter.remove_environmental_noise(col, self.fs, self.notch.value)
            out[:, c] = col
        return out

    def get_window(self, filtered=True):
        """Dernière fenêtre occipitale (window_n x C), ou None si buffer pas encore rempli.

        On récupère `window_n + margin_n` échantillons, on filtre, puis on ne garde que les
        `window_n` derniers : le transitoire d'établissement du filtre tombe dans la marge
        jetée au lieu de polluer le début de la fenêtre analysée (cf. FILTER_MARGIN_S).
        """
        data = self.board.get_current_board_data(self.window_n + self.margin_n)
        if data.shape[1] < self.window_n:
            return None
        sig = data[self.occ_rows, :].T  # (n, C)
        out = self._filter(sig) if filtered else sig
        return out[-self.window_n:]

    def sigma_from_block(self, block):
        """σ par voie d'un bloc (n x C) DÉJÀ collecté, transitoire du filtre écarté.

        ⚠️ Écarter le transitoire n'est pas un raffinement, c'est ce qui sépare une mesure
        utilisable d'une mesure fausse d'un facteur 100. L'Unicorn sort un offset DC énorme et
        DÉRIVANT (mesuré le 2026-07-27 : 10⁵ µV, en rampe sur des dizaines de secondes après
        l'ouverture de session). `_filter` ne retire que la MOYENNE (`detrend(CONSTANT)`), pas
        la rampe ; le Butterworth étant à PASSE UNIQUE, ce résidu se présente comme une marche
        géante en début de tampon et son transitoire d'établissement domine tout le σ.
        Mesuré sur casque, même tampon : **σ = 2060 µV transitoire compris, 22 µV sans**.
        Le second chiffre est de l'EEG, le premier est du filtre.

        `block` doit donc contenir `margin_n` échantillons de PLUS que la fenêtre à mesurer.
        Retourne None si le bloc est trop court.
        """
        if block is None or len(block) <= self.margin_n:
            return None
        return self._filter(block)[self.margin_n:].std(axis=0)

    def quality(self, seconds=2.0, rows=None):
        """σ par voie après filtrage — détecte une voie morte ou saturée.

        Une voie « morte » (câble débranché, électrode décollée, casque éteint) donne un signal
        plat ou quasi plat : σ s'effondre. Une voie flottante ou saturée donne au contraire un
        σ énorme. Entre les deux se trouve l'EEG réel (typiquement 5-20 en bande 5-40 Hz).
        Retourne un tableau de σ, ou None tant que le buffer n'est pas rempli.

        On récupère `margin_n` échantillons de plus que demandé, et on les jette après
        filtrage (cf. `sigma_from_block`) : sans ça, le σ mesure le filtre, pas l'électrode.
        """
        rows = self.eeg_rows if rows is None else rows
        n = int(round(seconds * self.fs)) + self.margin_n
        data = self.board.get_current_board_data(n)
        if data.shape[1] < n:
            return None
        return self.sigma_from_block(data[rows, :].T)

    def get_epoch(self, seconds, rows=None, filtered=False, margin_s=0.0):
        """Époque des `rows` (défaut : TOUTES les voies EEG) sur les dernières `seconds`,
        forme (n_samp x n_ch). Pour le Motor Imagery : voies complètes, le décodeur MI filtre
        lui-même (bande mu/beta). Retourne None tant que le buffer n'est pas rempli.

        `margin_s` : échantillons SUPPLÉMENTAIRES récupérés AVANT la fenêtre. On rend l'époque
        allongée telle quelle — au décodeur de filtrer puis de ne garder que la fin. Le début
        de la fenêtre utile échappe ainsi au transitoire du filtre. La fenêtre reste calée sur
        « maintenant » à la fin, ce qui préserve l'alignement de phase du c-VEP.
        """
        rows = self.eeg_rows if rows is None else rows
        n = int(round(seconds * self.fs))
        extra = int(round(margin_s * self.fs))
        data = self.board.get_current_board_data(n + extra)
        if data.shape[1] < n:
            return None
        sig = data[rows, :].T
        out = self._filter(sig) if filtered else sig
        return out if extra else out[-n:]

    def get_new_data(self):
        """Échantillons ARRIVÉS DEPUIS LE DERNIER APPEL : (eeg (n x 8), ts (n,)), non filtrés.

        Pour la diffusion en continu (serveur LSL) : on veut publier chaque échantillon une
        fois et une seule, sans trou ni doublon, ce que `get_current_board_data` ne permet pas
        (elle rend toujours la même fenêtre glissante).

        ⚠️ CETTE MÉTHODE VIDE LE TAMPON de BrainFlow. Les autres accesseurs (`get_window`,
        `get_epoch`, `get_raw`, `quality`) lisent, eux, un tampon glissant qu'ils supposent
        REMPLI : les mélanger avec celle-ci dans la même session leur ferait rendre des
        fenêtres tronquées ou None. Un seul lecteur incrémental par session, donc — le jour
        où le moteur devra à la fois diffuser et décoder, ce sera à lui de tenir son propre
        tampon à partir de ce que rend cette méthode.

        Retourne (None, None) si rien de neuf.
        """
        data = self.board.get_board_data()
        if data.shape[1] < 1:
            return None, None
        return data[self.eeg_rows, :].T, data[self.ts_row, :]

    def get_raw(self, seconds):
        """Flux BRUT (non filtré) des `seconds` dernières secondes : (eeg (n x 8), ts (n,)).

        Pour le P300 : on récupère un bloc entier (toute une manche de flashs), on garde le canal
        TIMESTAMP, puis on découpe chaque époque à l'onset de son flash via le timestamp (robuste
        à la dérive d'horloge, contrairement à un comptage d'échantillons depuis un t0 pygame).
        Le filtrage ERP (bande 1-12 Hz) est fait ensuite par le décodeur, PAS ici — la bande
        d'acquisition SSVEP (5-40 Hz) couperait justement le P300. Retourne (None, None) tant
        que le buffer ne contient rien.
        """
        n = int(round(seconds * self.fs))
        data = self.board.get_current_board_data(n)
        if data.shape[1] < 1:
            return None, None
        return data[self.eeg_rows, :].T, data[self.ts_row, :]


def _demo(args):
    with UnicornAcquisition(serial=args.serial, synthetic=args.synthetic,
                            verbose=args.verbose) as acq:
        print(f"[acq] board={acq.board_id.name} fs={acq.fs}Hz  voies occ={acq.occ_names} "
              f"(rows {acq.occ_rows})  window={acq.window_n} ech.")

        # Attend le remplissage de la première fenêtre (~window_s).
        t0, w = time.perf_counter(), None
        while w is None and time.perf_counter() - t0 < 6.0:
            time.sleep(0.2)
            w = acq.get_window()
        if w is None:
            print("[acq] ÉCHEC : aucune donnée (fenêtre jamais remplie).")
            return False
        print(f"[acq] 1re fenêtre OK : shape={w.shape} dtype={w.dtype}")
        for i in range(3):
            time.sleep(0.5)
            w = acq.get_window()
            print(f"[acq]   maj {i}: shape={w.shape}  σ/voie={np.round(w.std(axis=0), 3)}")

        q = acq.quality()
        if q is not None:
            from config import CH_NAMES as _CH, signal_verdict as _verdict
            print("[acq] liaison : " + "  ".join(
                f"{_CH[i]}={s:.1f}({_verdict(s)})" for i, s in enumerate(q)))

        if args.run:
            _demo_run_live(acq)
    return True


def _demo_run_live(acq):
    """Câble get_window -> run_live -> UDP local, ~3 s, pour prouver la chaîne complète.

    (Board synthétique => pas de vrai SSVEP : les commandes seront surtout STOP/aléatoires.
    On ne valide ICI que le CÂBLAGE, pas la justesse du décodage.)"""
    import json
    import socket
    import threading

    from controller import run_live

    recv, stop_l = [], threading.Event()

    def listen():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", UDP_PORT))
        s.settimeout(0.2)
        while not stop_l.is_set():
            try:
                data, _ = s.recvfrom(1024)
                recv.append(json.loads(data.decode("utf-8")))
            except (socket.timeout, ValueError, OSError):
                pass
        s.close()

    threading.Thread(target=listen, daemon=True).start()
    time.sleep(0.2)
    stop, sender = run_live(acq.get_window, host="127.0.0.1", port=UDP_PORT)
    time.sleep(3.0)
    stop.set()
    stop_l.set()
    time.sleep(0.3)
    sender.close()
    print(f"[acq] run_live OK : {len(recv)} datagrammes reçus en ~3 s (cadence ~15 Hz).")


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Acquisition Unicorn (BrainFlow) - EEG Waffle.")
    p.add_argument("--synthetic", action="store_true", help="board de test BrainFlow (sans casque)")
    p.add_argument("--serial", default=None, help="numéro de série Unicorn (si plusieurs appairés)")
    p.add_argument("--run", action="store_true", help="enchaîner sur run_live -> UDP 127.0.0.1")
    p.add_argument("--verbose", action="store_true", help="logs BrainFlow détaillés")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    ok = _demo(_parse_args(sys.argv[1:]))
    sys.exit(0 if ok else 1)
