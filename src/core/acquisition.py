"""Acquisition Unicorn via BrainFlow — la seule porte d'entrée du signal dans le projet.

Tout ce qui décode part d'ici. Deux façons de lire le casque, à ne PAS mélanger dans une
même session :

- `get_window()` / `get_epoch()` / `get_raw()` / `quality()` lisent une fenêtre GLISSANTE :
  chaque appel rend les dernières secondes, quitte à renvoyer deux fois le même échantillon.
  C'est ce que veulent les décodeurs, qui redécident en continu.
- `get_new_data()` VIDE le tampon : chaque échantillon sort une fois et une seule. C'est ce
  que veut le moteur, qui doit diffuser un flux sans trou ni doublon — et c'est pourquoi
  `server.py` tient son propre tampon glissant à partir de ce qu'il en tire.

Filtrage : detrend + passe-bande + notch 50 Hz, appliqué sur une fenêtre ÉLARGIE de
`FILTER_MARGIN_S` de chaque côté puis rognée. Sans cette marge, le transitoire d'établissement
du filtre reste dans la fenêtre et se fait passer pour du signal (il avait fait mesurer un σ de
40 000 µV sur de l'EEG à 5 µV).

BrainFlow parle au casque via l'API g.tec : 250 Hz, 8 voies sur les rows 0..7, dans l'ordre
Fz, C3, Cz, C4, Pz, PO7, Oz, PO8. Le casque doit être chargé et appairé en Bluetooth.

Lancer (test de l'acquisition seule) :
    python src/core/acquisition.py --synthetic           # sans casque (board de test)
    python src/core/acquisition.py                        # vrai Unicorn
    python src/core/acquisition.py --serial UN-2019.05.51 # si plusieurs Unicorn appairés
"""

import argparse
import os
import sys
import time

import numpy as np
from brainflow.board_shim import BoardShim, BoardIds, BrainFlowInputParams
from brainflow.data_filter import DataFilter, DetrendOperations, FilterTypes, NoiseTypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))      # -> src/
from core.config import (BANDPASS, CH_NAMES, FILTER_MARGIN_S, MI_WINDOW_S,  # noqa: E402
                    OCCIPITAL, UNICORN_SERIAL, WINDOW_S, use_utf8_console)


def _median_offdiag(filtered):
    """Corrélation médiane entre paires de voies distinctes d'un bloc (n x C) filtré.

    Retourne **None** quand la corrélation n'est pas définie. Ce n'est pas de la prudence
    décorative : une voie strictement constante (câble débranché, saturation à fond, board de
    test entre deux blocs) donne une variance nulle, `np.corrcoef` répond NaN, et ce NaN se
    propage jusqu'à l'état publié. Or NaN n'existe pas en JSON : il ne dégrade pas l'affichage,
    il fait échouer la sérialisation de TOUT l'état et le tableau de bord se vide d'un coup.
    Mieux vaut « corrélation indisponible » qu'une page blanche.
    """
    with np.errstate(invalid="ignore", divide="ignore"):
        c = np.corrcoef(filtered.T)
    if not np.all(np.isfinite(c)):
        return None
    return float(np.median(c[~np.eye(c.shape[0], dtype=bool)]))


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
        source = self.sigma_source(block)
        return None if source is None else source.std(axis=0)

    def common_mode(self, block):
        """Corrélation médiane entre voies (signal filtré) — détecte une RÉFÉRENCE DÉCROCHÉE.

        Le σ par voie ne voit PAS ce défaut : quand une mastoïde se décolle, les 8 voies
        mesurent toutes la même chose (la référence qui flotte) avec des amplitudes qui
        restent plausibles. L'écran de contrôle affiche alors 8 barres rassurantes sur un
        signal sans aucune information — une séance entière perdue, deux fois le 2026-07-27.

        Mesuré sur casque le même jour : mastoïdes absentes -> médiane **+1,000** (mode
        commun pur, min +1,000 sur toutes les paires) ; mastoïdes en place -> **+0,31 à
        +0,50**. La séparation est énorme et le mécanisme est physique, pas statistique :
        deux voies qui mesurent la même référence flottante corrèlent exactement à 1.

        On prend la MÉDIANE et non le max : avec un bon montage, certaines paires voisines
        (occipitales adjacentes) montent légitimement à +0,87.

        Retourne None si le bloc est trop court.
        """
        source = self.sigma_source(block)
        return None if source is None else _median_offdiag(source)

    def sigma_source(self, block):
        """Bloc filtré, transitoire écarté — la base commune de `sigma_from_block`/`common_mode`."""
        if block is None or len(block) <= self.margin_n:
            return None
        return self._filter(block)[self.margin_n:]

    def link_check(self, seconds=2.0, rows=None):
        """(σ par voie, corrélation inter-voies) — l'état de la liaison en UNE lecture.

        Les deux indicateurs sont complémentaires et aucun ne remplace l'autre : le σ voit
        une voie morte ou saturée, la corrélation voit une référence décrochée. Ils sont
        calculés ici sur le MÊME tampon filtré, pour ne pas payer deux fois le filtrage ni
        risquer de décrire deux instants différents.
        """
        rows = self.eeg_rows if rows is None else rows
        n = int(round(seconds * self.fs)) + self.margin_n
        data = self.board.get_current_board_data(n)
        if data.shape[1] < n:
            return None, None
        source = self.sigma_source(data[rows, :].T)
        return source.std(axis=0), _median_offdiag(source)

    def occipital_window(self, block):
        """Fenêtre SSVEP (window_n x len(OCCIPITAL)) depuis un bloc DÉJÀ collecté (n x 8).

        Même résultat que `get_window()`, mais sur un tampon que l'appelant possède au lieu
        du tampon glissant de BrainFlow. C'est ce qui permet à un moteur qui DIFFUSE (donc
        qui vide le tampon avec `get_new_data`) de DÉCODER en même temps : il tient son
        propre historique et le passe ici.

        `block` indexe les 8 voies dans l'ordre de `CH_NAMES` — pas les rows du board.
        Retourne None tant que le bloc est trop court.
        """
        need = self.window_n + self.margin_n
        if block is None or len(block) < need:
            return None
        return self._filter(block[-need:][:, OCCIPITAL])[-self.window_n:]

    def motor_window(self, block, seconds=MI_WINDOW_S):
        """Fenêtre MI (n x 8) depuis un bloc possédé par l'appelant. **Non filtrée**, exprès.

        Le Motor Imagery utilise les 8 voies — le CSP fait lui-même le tri spatial — et le
        modèle applique son propre re-référencement CAR puis son passe-bande 8-30 Hz dans
        `MIModel._prep`. Filtrer ici filtrerait deux fois : phase décalée et variances
        modifiées, or ce sont exactement les variances que le CSP exploite. Le modèle
        décoderait alors sur autre chose que ce sur quoi il a été entraîné — sans erreur, avec
        des probabilités parfaitement plausibles.

        `block` indexe les 8 voies dans l'ordre de `CH_NAMES` — pas les rows du board, comme
        pour `occipital_window`. Ce n'est pas un détail de forme ici : le CSP est un filtre
        SPATIAL, il apprend une combinaison des voies dans CET ordre. Un appelant qui passerait
        des rows du board décoderait du bruit, et le dirait avec des probabilités à 0,99.

        Retourne None tant que le bloc est trop court.
        """
        need = int(round(seconds * self.fs))
        if block is None or len(block) < need:
            return None
        return np.asarray(block[-need:], dtype=float)

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
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # Fenêtre MI : toutes les voies, 2 s, et surtout NON filtrée — le modèle filtre lui-même.
    acq_mi = UnicornAcquisition(synthetic=True)
    bloc = np.random.default_rng(0).normal(0.0, 8.0, (int(5.0 * acq_mi.fs), 8))
    fen = acq_mi.motor_window(bloc)
    chk(fen is not None and fen.shape == (int(MI_WINDOW_S * acq_mi.fs), 8),
        f"la fenêtre MI fait 2 s sur les 8 voies ({None if fen is None else fen.shape})")
    chk(np.allclose(fen, bloc[-len(fen):]),
        "et elle rend le signal TEL QUEL : le modèle applique son propre CAR et son passe-bande")
    chk(acq_mi.motor_window(bloc[:10]) is None,
        "un bloc trop court rend None plutôt qu'une fenêtre incomplète")

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
            from core.config import CH_NAMES as _CH, signal_verdict as _verdict
            print("[acq] liaison : " + "  ".join(
                f"{_CH[i]}={s:.1f}({_verdict(s)})" for i, s in enumerate(q)))

    return ok


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Acquisition Unicorn (BrainFlow) — EEG_API_Unicorn.",
        epilog="Ce test ne valide que l'ACQUISITION. La chaîne complète jusqu'aux flux LSL, "
               "c'est `python src/core/server.py --smoke`.")
    p.add_argument("--synthetic", action="store_true", help="board de test BrainFlow (sans casque)")
    p.add_argument("--serial", default=None, help="numéro de série Unicorn (si plusieurs appairés)")
    p.add_argument("--verbose", action="store_true", help="logs BrainFlow détaillés")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    ok = _demo(_parse_args(sys.argv[1:]))
    sys.exit(0 if ok else 1)
