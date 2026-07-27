"""Moteur headless : casque Unicorn -> flux LSL. C'est le MVP de docs/SPEC.md §10.

Ce fichier est le **cœur du produit** : il tourne SANS interface graphique. L'application
pygame (`src/app.py`), le futur tableau de bord web et le code d'un étudiant sont tous, du
point de vue du moteur, des clients qui écoutent les mêmes flux.

Ce qu'il publie aujourd'hui (SPEC §4) :
    EEG_API_Unicorn_raw            les 8 voies, µV, 250 Hz
    EEG_API_Unicorn_quality        σ par voie, ~1 Hz (électrode décollée ?)
    EEG_API_Unicorn_status         état du moteur, JSON, à chaque changement + périodique
    EEG_API_Unicorn_decoded_ssvep  cible regardée, ~5 Hz (avec --mode ssvep)

Pas encore : les autres flux `decoded_*`, le control plane entrant, les marqueurs. Ils
viendront poser leurs publications sur le même squelette de boucle.

⚠️ Le moteur ne rend AUCUN stimulus. Pour le SSVEP, c'est l'application cliente qui fait
clignoter les cibles ; elle déclare simplement leurs fréquences au moteur (`--freqs`). Le
couplage est lâche — aucune synchronisation à la frame n'est nécessaire, contrairement au
c-VEP (SPEC §7).

Lancer :
    python src/server.py --synthetic              # sans casque (board de test BrainFlow)
    python src/server.py                           # vrai Unicorn, brut + qualité seulement
    python src/server.py --mode ssvep              # + décodage SSVEP (cibles par défaut)
    python src/server.py --mode ssvep --freqs 15,20,8.57
    python src/server.py --duration 60             # s'arrête tout seul au bout de 60 s
    python src/server.py --smoke                   # test headless de bout en bout (CI)
"""

import argparse
import os
import signal
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from acquisition import UnicornAcquisition  # noqa: E402
from cca_decoder import CCADecoder  # noqa: E402
from config import (ARTIFACT_SIGMA_RATIO, CH_NAMES, SSVEP_BASELINE_S,  # noqa: E402
                    choose_frequencies, use_utf8_console)
from lsl_io import (ClockBridge, DecodedSSVEPPublisher, QualityPublisher,  # noqa: E402
                    RawPublisher, StatusPublisher, stream_name, verdict_from_sigma)

# Cadence de la boucle. On ne publie PAS échantillon par échantillon : on ramasse ~50 ms de
# signal d'un coup. Assez court pour rester très en dessous des fenêtres de décision d'un
# mode BCI (1-2 s), assez long pour ne pas réveiller le processus 250 fois par seconde.
POLL_S = 0.05
QUALITY_PERIOD_S = 1.0    # cadence du flux `quality`
STATUS_PERIOD_S = 2.0     # rappel périodique de l'état (pour un client qui arrive en retard)
QUALITY_WINDOW_S = 2.0    # longueur de signal sur laquelle on mesure le σ par voie
SSVEP_DECODE_HZ = 5.0     # cadence de décodage SSVEP (fenêtres glissantes de WINDOW_S)
SSVEP_BASELINE_SAMPLE_HZ = 5.0   # cadence d'échantillonnage du plancher de repos


class EngineServer:
    """Boucle acquisition -> publication. Un objet, une session casque, N flux.

    Le moteur tient **son propre tampon glissant** (`_recent`). C'est le point d'architecture
    central : `get_new_data()` VIDE le tampon de BrainFlow, donc les accesseurs à fenêtre
    glissante (`get_window`, `get_epoch`) ne peuvent plus servir. Diffuser et décoder en même
    temps n'est possible qu'en gardant l'historique ici, et en alimentant depuis lui à la fois
    la publication brute et les décodeurs.
    """

    def __init__(self, serial=None, synthetic=False, verbose=False, mode=None, freqs=None):
        self.synthetic = synthetic
        self.mode = mode
        self.acq = UnicornAcquisition(serial=serial, synthetic=synthetic, verbose=verbose)
        self.clock = ClockBridge()
        self.raw_out = RawPublisher(ch_names=CH_NAMES, fs=self.acq.fs)
        self.quality_out = QualityPublisher(ch_names=CH_NAMES)
        self.status_out = StatusPublisher()
        self.samples = 0
        self._stop = False
        self._recent = np.zeros((0, len(CH_NAMES)))

        # Le tampon doit satisfaire le plus gourmand des consommateurs : la qualité veut
        # QUALITY_WINDOW_S, le SSVEP veut WINDOW_S — chacun plus la marge de filtre.
        self.keep = max(int(QUALITY_WINDOW_S * self.acq.fs),
                        self.acq.window_n) + self.acq.margin_n

        self.decoder = None
        self.ssvep_out = None
        self.freqs = []
        self._baseline_samples = []
        self._baseline_sigmas = []
        self._sigma_ref = None
        self._baseline_until = None
        self._baseline_s = SSVEP_BASELINE_S
        self._baseline_done = False
        if mode == "ssvep":
            self._setup_ssvep(freqs)

    def _setup_ssvep(self, freqs):
        """Prépare le décodage SSVEP. `freqs` = les fréquences que l'appli cliente affiche.

        Elles sont une ENTRÉE, pas une constante du moteur : c'est l'application externe qui
        rend le stimulus (SPEC §7) et qui déclare donc son jeu de fréquences. Le défaut
        correspond aux cibles historiques ramenées aux diviseurs entiers d'un écran 60 Hz.

        Le flux `decoded_ssvep` n'est PAS créé ici : il naît à la fin de la mesure du repos
        (`_finish_baseline`), quand on sait sur quelle échelle on décidera. Publier un flux
        dont les métadonnées annonceraient la mauvaise échelle, ou le recréer en cours de
        route, obligerait les clients déjà connectés à le redécouvrir — le contrat doit être
        stable une fois le flux visible.
        """
        if not freqs:
            freqs = [c["actual_hz"] for c in choose_frequencies(60)]
        self.freqs = [float(f) for f in freqs]
        self.decoder = CCADecoder(self.freqs, fs=self.acq.fs)

    def stop(self):
        self._stop = True

    @property
    def phase(self):
        """« baseline » pendant la mesure du repos, « decoding » ensuite, sinon « streaming »."""
        if self.decoder is None:
            return "streaming"
        return "decoding" if self._baseline_done else "baseline"

    def _status_key(self, running):
        """Ce qui constitue un vrai CHANGEMENT d'état — hors compteurs (cf. StatusPublisher.push)."""
        return (running, self.synthetic, self.mode, self.phase)

    def _state(self, running):
        streams = ["raw", "quality", "status"] + (["decoded_ssvep"] if self.ssvep_out else [])
        state = {
            "running": running,
            "board": "synthetic" if self.synthetic else "unicorn",
            "fs_hz": float(self.acq.fs),
            "channels": list(CH_NAMES),
            "mode": self.mode,
            "phase": self.phase,
            "samples_published": self.samples,
            "streams": [stream_name(s) for s in streams],
        }
        if self.decoder is not None:
            state["frequencies_hz"] = self.freqs
            # Ce que le client doit AFFICHER à l'utilisateur pendant le repos : sans cette
            # consigne, le plancher est mesuré pendant que l'étudiant fixe une cible, et
            # les seuils sortent faux pour toute la séance.
            state["instruction"] = ("Ne fixe AUCUNE cible : mesure du bruit de fond."
                                    if self.phase == "baseline" else "Fixe une cible.")
        return state

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

    def _tick_ssvep(self, lsl_ts):
        """Un pas de décodage SSVEP : d'abord mesurer le repos, ensuite décider."""
        window = self.acq.occipital_window(self._recent)
        if window is None:
            return

        if not self._baseline_done:
            self._collect_baseline(window)
            return

        # Rejet d'artefact : une fenêtre dont l'amplitude explose par rapport au repos ne
        # contient pas d'EEG (mouvement, clignement). En décoder des ρ produirait des
        # détections aléatoires ; on publie « aucune cible » plutôt que du bruit habillé.
        sd = float(window.std(axis=0).mean())
        if self._sigma_ref and sd > ARTIFACT_SIGMA_RATIO * self._sigma_ref:
            self.ssvep_out.push(-1, 0.0, 0.0, [0.0] * len(self.freqs), lsl_ts)
            return

        freq, scores = self.decoder.classify(window)
        ordered = [scores[f] for f in self.freqs]
        if freq is None:
            self.ssvep_out.push(-1, 0.0, max(ordered), ordered, lsl_ts)
        else:
            index = self.freqs.index(freq)
            self.ssvep_out.push(index, freq, scores[freq], ordered, lsl_ts)

    def _collect_baseline(self, window):
        """Accumule le plancher de ρ au repos, puis ajuste le décodeur.

        Pourquoi c'est nécessaire alors que le SSVEP est réputé « sans calibration » : chaque
        fréquence a un fond de corrélation DIFFÉRENT au repos, selon sa proximité au pic alpha
        du jour. Un seuil commun est donc structurellement injuste — mesuré sur ce casque, une
        cible proche de l'alpha n'émettait jamais alors que son ρ moyen dépassait le seuil.
        Ce n'est pas un modèle appris, juste un étalonnage de quelques secondes, à refaire à
        chaque séance. Le client DOIT afficher la consigne « ne fixe rien » (voir `_state`).
        """
        # Le décompte part de la PREMIÈRE fenêtre exploitable, pas du démarrage : il faut
        # d'abord WINDOW_S + la marge de filtre (2,5 s) pour que le tampon en produise une.
        # Compter depuis le lancement rognerait le repos d'autant — mesuré : 3 fenêtres
        # récoltées au lieu de 15, donc plancher rejeté faute d'effectif.
        if self._baseline_until is None:
            self._baseline_until = time.perf_counter() + self._baseline_s

        self._baseline_samples.append(self.decoder.scores(window))
        self._baseline_sigmas.append(float(window.std(axis=0).mean()))
        if time.perf_counter() < self._baseline_until:
            return

        if self.decoder.fit_baseline(self._baseline_samples):
            self._sigma_ref = float(np.median(self._baseline_sigmas))
            line = "  ".join(f"{f:g}Hz: μ={m:.2f} σ={s:.2f}"
                             for f, (m, s) in self.decoder.baseline.items())
            print(f"[server] plancher de repos ({len(self._baseline_samples)} fenêtres) — {line}")
            print(f"[server] σ de référence {self._sigma_ref:.1f} -> rejet d'artefact au-delà "
                  f"de {ARTIFACT_SIGMA_RATIO * self._sigma_ref:.0f}")
        else:
            # Trop peu de fenêtres pour un plancher fiable. On décode quand même, mais sur ρ
            # BRUT — et surtout on laisse `decoder.baseline` à None : y mettre un plancher
            # neutre ferait basculer `decoder.thresholds` sur l'échelle z (seuil 2,5) tout en
            # comparant des ρ compris entre 0 et 1, donc plus aucune détection, en silence.
            print(f"[server] plancher NON mesuré ({len(self._baseline_samples)} fenêtres) "
                  f"-> décodage sur ρ brut, seuils moins justes")

        self._baseline_done = True
        scale = "z" if self.decoder.baseline else "rho"
        self.ssvep_out = DecodedSSVEPPublisher(self.freqs, decision_scale=scale,
                                               thresholds=self.decoder.thresholds)
        print(f"[server] flux LSL publie : {stream_name('decoded_ssvep')} "
              f"(échelle {scale}, seuil {self.decoder.thresholds[0]})")

    def run(self, duration_s=None, baseline_s=SSVEP_BASELINE_S):
        """Boucle principale. `duration_s=None` = jusqu'à Ctrl+C."""
        started = time.perf_counter()
        last_quality = last_status = last_ssvep = 0.0

        with self.acq:
            print(f"[server] board={self.acq.board_id.name} fs={self.acq.fs} Hz")
            for suffix in ("raw", "quality", "status"):
                print(f"[server] flux LSL publie : {stream_name(suffix)}")
            if self.decoder is not None:
                print(f"[server] mode {self.mode} — cibles "
                      + ", ".join(f"{f:g} Hz" for f in self.freqs))
                print(f"[server] REPOS {baseline_s:.0f} s : ne fixe AUCUNE cible "
                      f"(mesure du bruit de fond)")
                self._baseline_s = baseline_s
            self.status_out.push(self._state(True), key=self._status_key(True), force=True)

            while not self._stop:
                now = time.perf_counter()
                if duration_s is not None and now - started >= duration_s:
                    break

                eeg, ts_unix = self.acq.get_new_data()
                if eeg is not None and len(eeg):
                    self.samples += self.raw_out.push(eeg, self.clock.to_lsl(ts_unix))
                    self._recent = np.vstack([self._recent, eeg])[-self.keep:]

                if now - last_quality >= QUALITY_PERIOD_S:
                    self._publish_quality(self.clock.to_lsl(time.time()))
                    last_quality = now

                if self.decoder is not None:
                    period = 1.0 / (SSVEP_BASELINE_SAMPLE_HZ if not self._baseline_done
                                    else SSVEP_DECODE_HZ)
                    if now - last_ssvep >= period:
                        self._tick_ssvep(self.clock.to_lsl(time.time()))
                        last_ssvep = now

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
    return ok and _smoke_ssvep()


def _smoke_ssvep():
    """Le mode SSVEP câblé de bout en bout, sur board synthétique.

    On ne vérifie PAS la justesse du décodage : le board synthétique n'émet aucun vrai SSVEP,
    donc la cible « détectée » n'a aucun sens. On vérifie le CÂBLAGE — que la baseline se
    termine, que le flux décodé apparaît, qu'il publie au bon rythme et que ses valeurs
    respectent le contrat annoncé (index dans les bornes, scores en nombre attendu).
    """
    import threading

    from pylsl import StreamInlet, resolve_byprop

    freqs = [15.0, 20.0, 8.57]
    server = EngineServer(synthetic=True, mode="ssvep", freqs=freqs)
    thread = threading.Thread(target=server.run,
                              kwargs={"duration_s": 12.0, "baseline_s": 3.0}, daemon=True)
    thread.start()

    found = resolve_byprop("name", stream_name("decoded_ssvep"), timeout=12.0)
    if not found:
        print("[smoke-ssvep] ÉCHEC : le flux décodé n'apparaît pas après la baseline")
        server.stop()
        return False
    inlet = StreamInlet(found[0])
    inlet.open_stream(timeout=5.0)
    n_ch = inlet.info().channel_count()
    scale = inlet.info().desc().child("decoding").child_value("decision_scale")
    print(f"[smoke-ssvep] flux décodé : {n_ch} voies, échelle « {scale} »")

    rows, t0 = [], time.perf_counter()
    while time.perf_counter() - t0 < 4.0 and thread.is_alive():
        chunk, _ts = inlet.pull_chunk(timeout=0.2, max_samples=64)
        rows.extend(chunk)
    server.stop()
    thread.join(timeout=5.0)

    ok = True
    if n_ch != 3 + len(freqs):
        print(f"[smoke-ssvep] ÉCHEC : {n_ch} voies au lieu de {3 + len(freqs)}")
        ok = False
    if len(rows) < 5:
        print(f"[smoke-ssvep] ÉCHEC : {len(rows)} décisions reçues, trop peu")
        ok = False
    for r in rows:
        if not (-1 <= int(r[0]) < len(freqs)):
            print(f"[smoke-ssvep] ÉCHEC : target_index hors bornes ({r[0]})")
            ok = False
            break
    if rows:
        detected = sum(1 for r in rows if int(r[0]) >= 0)
        print(f"[smoke-ssvep] {len(rows)} décisions, dont {detected} avec une cible "
              f"(sans valeur sur bruit synthétique — on teste le câblage)")
    print(f"[smoke-ssvep] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _parse_args(argv):
    p = argparse.ArgumentParser(description="EEG_API_Unicorn — moteur headless, sorties LSL.")
    p.add_argument("--synthetic", action="store_true", help="board de test BrainFlow (sans casque)")
    p.add_argument("--serial", default=None, help="numéro de série Unicorn (si plusieurs appairés)")
    p.add_argument("--duration", type=float, default=None, help="durée en s (défaut : jusqu'à Ctrl+C)")
    p.add_argument("--mode", choices=["ssvep"], default=None,
                   help="décodeur à publier en plus du brut (défaut : aucun)")
    p.add_argument("--freqs", default=None,
                   help="fréquences des cibles affichées par l'appli cliente, ex. 15,20,8.57")
    p.add_argument("--baseline", type=float, default=SSVEP_BASELINE_S,
                   help="durée du repos initial en s (mesure du bruit de fond)")
    p.add_argument("--smoke", action="store_true", help="test headless de bout en bout, puis quitte")
    p.add_argument("--verbose", action="store_true", help="logs BrainFlow détaillés")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    args = _parse_args(sys.argv[1:])
    if args.smoke:
        sys.exit(0 if _smoke() else 1)

    freqs = [float(f) for f in args.freqs.split(",")] if args.freqs else None
    engine = EngineServer(serial=args.serial, synthetic=args.synthetic,
                          verbose=args.verbose, mode=args.mode, freqs=freqs)
    # Ctrl+C doit fermer PROPREMENT la session BrainFlow : une session laissée ouverte
    # empêche la suivante de s'ouvrir (BOARD_NOT_READY au relancement).
    signal.signal(signal.SIGINT, lambda *_: engine.stop())
    print("[server] Ctrl+C pour arrêter.")
    engine.run(duration_s=args.duration, baseline_s=args.baseline)
