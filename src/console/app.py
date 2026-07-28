"""La console d'expérimentation : régler, observer, publier — mode par mode.

Lancer :
    python src/console/app.py --synthetic          # sans casque (board de test BrainFlow)
    python src/console/app.py                      # vrai Unicorn, brut seul
    python src/console/app.py --mode ssvep         # + décodage SSVEP
    python src/console/app.py --mode ssvep,neuro   # les deux en même temps
    python src/console/app.py --smoke              # test headless (CI), puis quitte

⚠️ Ne jamais la lancer en même temps que `src/core/server.py` ni que `src/research/app.py` : le
casque n'accepte qu'une connexion, et les noms de flux sont un contrat public — deux moteurs
publient sous le même nom.
"""

import argparse
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse_args(argv):
    p = argparse.ArgumentParser(description="EEG_API_Unicorn — console d'expérimentation.")
    p.add_argument("--synthetic", action="store_true", help="board de test BrainFlow (sans casque)")
    p.add_argument("--serial", default=None, help="numéro de série Unicorn")
    p.add_argument("--mode", default=None, help="modes à démarrer, séparés par des virgules")
    p.add_argument("--no-raw", action="store_true", help="ne pas diffuser le signal brut")
    p.add_argument("--id", dest="instance", default=None, help="identité de cette instance")
    p.add_argument("--baseline", type=float, default=None,
                   help="raccourcir le repos — pour REGARDER l'interface sans attendre. Jamais "
                        "pour une vraie séance : le plancher serait mesuré sur trop peu de "
                        "fenêtres et fausserait toute la suite")
    p.add_argument("--warmup", type=float, default=None,
                   help="raccourcir la stabilisation (même réserve que --baseline)")
    p.add_argument("--smoke", action="store_true", help="test headless, puis quitte")
    p.add_argument("--verbose", action="store_true", help="logs BrainFlow détaillés")
    return p.parse_args(argv)


# QT_QPA_PLATFORM doit être posé AVANT le premier import de PySide6 : Qt choisit son backend
# d'affichage à l'import, pas à la création de la QApplication. Posé après, il n'a aucun effet
# et le test headless échoue sur une machine sans écran (la CI, plus tard).
_ARGS = _parse_args(sys.argv[1:])
if _ARGS.smoke:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import (QApplication, QMainWindow, QStackedWidget,  # noqa: E402
                               QVBoxLayout, QWidget)

from console.banner import Banner  # noqa: E402
from core.config import use_utf8_console  # noqa: E402
from core.modes import registry  # noqa: E402
from core.server import EngineServer  # noqa: E402

REFRESH_MS = 100    # ~10 Hz : le moteur décide à 5 Hz, sonder plus vite ne montrerait rien de plus


class Console(QMainWindow):
    """La fenêtre. Elle ne fait que deux choses : lire un état, envoyer des commandes."""

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("EEG_API_Unicorn — console d'expérimentation")
        self.resize(1100, 720)

        self.banner = Banner()
        self.stack = QStackedWidget()

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.banner)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_MS)

    def refresh(self):
        """Sonde le moteur et redistribue l'état. Le SEUL endroit qui appelle `snapshot()`."""
        self.apply_state(self.engine.snapshot())

    def apply_state(self, state):
        self.banner.update_from(state)


def fake_state():
    """Un `snapshot()` fabriqué, pour monter l'interface sans casque ni moteur.

    Construit depuis le VRAI registre : si un `ModeSpec` change, ce qu'on teste change avec lui.
    Un état factice écrit à la main deviendrait faux en silence — exactement le défaut qu'on
    reproche à un catalogue de modes recopié dans l'interface.
    """
    return {
        "running": True, "board": "synthetic", "instance": "faux", "fs_hz": 250.0,
        "channels": ["Fz", "C3", "Cz", "C4", "Pz", "PO7", "Oz", "PO8"],
        "mode": "ssvep", "modes": ["raw", "ssvep"], "phase": "decoding",
        "samples_published": 12345,
        "streams": ["EEG_API_Unicorn_raw", "EEG_API_Unicorn_quality",
                    "EEG_API_Unicorn_status", "EEG_API_Unicorn_decoded_ssvep"],
        "quality": {"sigmas": [7.2, 8.1, 6.9, 9.4, 5.5, 11.2, 6.1, 7.8],
                    "verdicts": ["ok"] * 8, "common_mode": 0.38, "reference_lost": False},
        "rest_instruction": "",
        "modes_state": {
            "raw": {"id": "raw", "label": "Brut", "family": "brut", "phase": "running",
                    "published": True, "params": {}, "instruction": "", "stream": "raw",
                    "channels": ["Fz", "C3", "Cz", "C4", "Pz", "PO7", "Oz", "PO8"],
                    "rest_report": None, "output": None},
            "ssvep": {"id": "ssvep", "label": "SSVEP", "family": "actif", "phase": "running",
                      "published": True, "params": {"freqs": [15.0, 20.0, 8.57]},
                      "instruction": "", "stream": "decoded_ssvep",
                      "channels": ["target_index", "freq_hz", "confidence",
                                   "score_15Hz", "score_20Hz", "score_8.57Hz"],
                      "rest_report": {"kind": "ssvep", "windows": 40, "targets": []},
                      "output": {"target_index": 0, "freq_hz": 15.0,
                                 "scores": [3.1, 0.4, 0.9], "artifact": False,
                                 "threshold": 2.5}},
        },
        "catalog": registry.catalog(),
    }


def _smoke():
    """Monte l'interface sans écran, depuis un état factice. Même philosophie que app.py --smoke.

    Ce qu'on vérifie ici est ce qui casse le plus souvent dans une interface : qu'elle se monte,
    qu'elle encaisse un état où tout est absent (moteur pas encore démarré), et qu'elle survit à
    une alarme. Le contenu métier, lui, est testé côté moteur — il n'y en a pas ici.
    """
    class _FauxMoteur:
        """Juste ce que la console lit : un état. Assez pour couvrir `refresh()`, qui est la
        SEULE ligne du fichier à toucher le moteur — sans ça, une faute de nom y passerait
        tous les tests et n'échouerait que devant un étudiant."""

        def __init__(self):
            self.appels = 0

        def snapshot(self):
            self.appels += 1
            return fake_state()

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    app = QApplication.instance() or QApplication([])
    moteur_faux = _FauxMoteur()
    console = Console(moteur_faux)
    console.timer.stop()          # pas de moteur : on pilote l'état à la main
    console.show()

    state = fake_state()
    console.apply_state(state)
    chk("Unicorn" not in console.banner.liaison.text(),
        f"le bandeau dit que c'est un board de test — « {console.banner.liaison.text()} »")
    chk("σ" in console.banner.sigmas.text(), f"et les σ — « {console.banner.sigmas.text()} »")
    chk(console.banner.alarme.text() == "", "aucune alarme sur un montage sain")

    # Référence décrochée : le défaut qui rend une séance inexploitable sans autre symptôme.
    state["quality"] = {**state["quality"], "reference_lost": True, "common_mode": 1.0}
    console.apply_state(state)
    chk("RÉFÉRENCE DÉCROCHÉE" in console.banner.alarme.text(),
        "l'alarme de référence s'affiche, en clair")

    # Moteur pas encore démarré : rien ne doit lever.
    console.apply_state({"running": False, "board": "unicorn", "fs_hz": 250.0,
                         "modes": [], "quality": None, "catalog": []})
    chk("attente" in console.banner.sigmas.text(),
        f"un état vide est encaissé — « {console.banner.sigmas.text()} »")

    # `refresh()` est la SEULE ligne qui touche le moteur : assurer qu'elle fonctionne.
    console.refresh()
    chk(moteur_faux.appels == 1,
        f"refresh() a consulté le moteur (appels={moteur_faux.appels})")

    app.processEvents()
    print(f"[console-smoke] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def run(args):
    modes = [m.strip() for m in (args.mode or "").split(",") if m.strip()]
    if not args.no_raw:
        modes.insert(0, "raw")
    engine = EngineServer(serial=args.serial, synthetic=args.synthetic, verbose=args.verbose,
                          modes=modes, instance=args.instance)

    # Le moteur tourne dans SON fil et possède seul la session BrainFlow. Le fil Qt ne fait que
    # lire `snapshot()` et poser des commandes en file.
    thread = threading.Thread(
        target=engine.run,
        kwargs={"baseline_s": args.baseline, "warmup_s": args.warmup}, daemon=True)
    thread.start()

    try:
        app = QApplication([])
        console = Console(engine)
        console.show()
        app.exec()
    finally:
        # Ctrl+C ou fermeture de la fenêtre doivent fermer PROPREMENT la session BrainFlow :
        # une session laissée ouverte empêche la suivante de s'ouvrir (BOARD_NOT_READY).
        engine.stop()
        thread.join(timeout=5.0)


if __name__ == "__main__":
    use_utf8_console()
    sys.exit(0 if _smoke() else 1) if _ARGS.smoke else run(_ARGS)
