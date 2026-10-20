"""Enregistre le flux BRUT du moteur, avec des notes horodatées, pour une analyse hors ligne.

Sert à caler les seuils de « Contact des électrodes » : pendant qu'on décolle ou sèche une
électrode exprès, on tape une note (« C3 décollée », « C3 remise »), et l'analyse retrouve ensuite
quel morceau du signal correspond à quel état du montage.

Il écoute le flux `EEG_API_Unicorn_raw` comme une application : il n'ouvre PAS le casque, et se
lance donc dans un second terminal, console ouverte (elle publie ce flux dès qu'elle tourne).
Seulement le flux de CETTE machine : en salle, chaque poste publie sous le même nom.

Le fichier va dans `seances/` (jamais dans `data/`, réservé aux modèles) :
`brut_AAAAMMJJ-HHMMSS.npz`, avec `signal` (échantillons × voies, µV, non filtré), `horodatages`
(horloge LSL de ce poste), `voies`, `fs`, et les notes : `notes` et `notes_t` (même horloge).

    python src/research/enregistre_brut.py              # tape une note + Entrée ; « fin » arrête
    python src/research/enregistre_brut.py --duree 300  # s'arrête seul après 300 s
    python src/research/enregistre_brut.py --smoke      # autotest, sur un faux flux
"""

import argparse
import os
import queue
import socket
import sys
import threading
import time

import numpy as np
from pylsl import StreamInlet, local_clock, proc_clocksync, resolve_byprop

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import SEANCES_DIR, use_utf8_console  # noqa: E402
from core.lsl_io import stream_name  # noqa: E402

FIN = "fin"


def flux_de_cette_machine(flux, hote=None):
    """Les flux publiés par cette machine (nom d'hôte comparé sans casse)."""
    hote = (hote or socket.gethostname()).casefold()
    return [f for f in flux if (f.hostname() or "").casefold() == hote]


def noms_des_voies(info):
    """Les noms des voies annoncés par le flux, ou « voie_0 »… s'il n'en annonce pas."""
    noms, voie = [], info.desc().child("channels").child("channel")
    while not voie.empty():
        noms.append(voie.child_value("label"))
        voie = voie.next_sibling()
    return noms if len(noms) == info.channel_count() else [
        f"voie_{i}" for i in range(info.channel_count())]


class Enregistreur:
    """Tire le flux en tâche de fond ; `noter()` ajoute une note à l'instant présent."""

    def __init__(self, info):
        self.inlet = StreamInlet(info, processing_flags=proc_clocksync)
        # La description COMPLÈTE (les noms des voies) ne vient qu'avec `inlet.info()` : un flux
        # trouvé par `resolve_byprop` n'en porte que l'en-tête. Gardée vivante : les noms se
        # lisent dedans.
        self.info = self.inlet.info(timeout=5.0)
        self.voies = noms_des_voies(self.info)
        self.fs = self.info.nominal_srate()
        self.blocs, self.temps = [], []
        self.notes, self.notes_t = [], []
        self._fini = threading.Event()
        self._fil = threading.Thread(target=self._tirer, daemon=True)

    def demarrer(self):
        self.inlet.open_stream(timeout=5.0)
        self._fil.start()

    def _tirer(self):
        while not self._fini.is_set():
            bloc, temps = self.inlet.pull_chunk(timeout=0.2)
            if temps:
                self.blocs.append(np.asarray(bloc, dtype=np.float32))
                self.temps.extend(temps)

    def noter(self, texte, instant):
        self.notes.append(texte)
        self.notes_t.append(instant)

    def arreter(self):
        self._fini.set()
        self._fil.join(timeout=2.0)

    def sauver(self, dossier):
        os.makedirs(dossier, exist_ok=True)
        chemin = os.path.join(dossier, time.strftime("brut_%Y%m%d-%H%M%S.npz"))
        signal = (np.concatenate(self.blocs) if self.blocs
                  else np.zeros((0, len(self.voies)), dtype=np.float32))
        np.savez_compressed(chemin, signal=signal, horodatages=np.asarray(self.temps),
                            voies=np.asarray(self.voies), fs=float(self.fs),
                            notes=np.asarray(self.notes, dtype=str),
                            notes_t=np.asarray(self.notes_t, dtype=float))
        return chemin, len(signal)


def trouver(nom, attente_s=10.0, hote=None):
    """Le flux `nom` de cette machine, ou None. Dit pourquoi quand il manque."""
    tous = resolve_byprop("name", nom, timeout=attente_s)
    locaux = flux_de_cette_machine(tous, hote)
    if not locaux:
        if tous:
            print(f"Le flux {nom} existe, mais sur une autre machine : il est ignoré.")
        else:
            print(f"Aucun flux {nom} : la console tourne-t-elle, casque ouvert ?")
        return None
    return locaux[0]


def enregistrer(info, lire_note, dossier, duree_s=None):
    """Enregistre jusqu'à « fin », Ctrl+C ou `duree_s`. Rend (chemin, nombre d'échantillons).

    `lire_note()` rend la note suivante (None : plus de note). Elle est lue dans un fil à part, et
    horodatée dès qu'elle arrive : attendre le clavier ne doit ni retarder l'instant d'une note,
    ni empêcher l'arrêt après `duree_s`."""
    enr = Enregistreur(info)
    enr.demarrer()
    arrivees = queue.Queue()

    def lire():
        while True:
            try:
                note = lire_note()
            except (EOFError, KeyboardInterrupt):
                note = None
            arrivees.put((local_clock(), note))
            if note is None or note.strip().casefold() == FIN:
                return

    threading.Thread(target=lire, daemon=True).start()
    debut = time.time()
    try:
        while duree_s is None or time.time() - debut < duree_s:
            try:
                instant, note = arrivees.get(timeout=0.2)
            except queue.Empty:
                continue
            if note is None or note.strip().casefold() == FIN:
                break
            if note.strip():
                enr.noter(note.strip(), instant)
                print(f"  noté à {time.time() - debut:6.1f} s : {note.strip()}")
    except KeyboardInterrupt:
        pass
    finally:
        enr.arreter()
    return enr.sauver(dossier)


def _smoke():
    """Sur un faux flux publié ici : signal, voies, notes horodatées, et le fichier hors de data/."""
    import tempfile

    from pylsl import StreamInfo, StreamOutlet

    from core.config import DATA_DIR

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    voies = ["Fz", "C3", "Cz", "C4", "Pz", "PO7", "Oz", "PO8"]
    nom = f"{stream_name('raw')}_smoke_{os.getpid()}"
    info = StreamInfo(nom, "EEG", len(voies), 250.0, "float32", f"smoke-{os.getpid()}")
    canaux = info.desc().append_child("channels")
    for v in voies:
        canaux.append_child("channel").append_child_value("label", v)
    sortie = StreamOutlet(info)
    publie = threading.Event()

    def publier():
        n = 0
        while not publie.is_set():
            sortie.push_chunk([[float(n + i)] * len(voies) for i in range(25)])
            n += 25
            time.sleep(0.1)

    fil = threading.Thread(target=publier, daemon=True)
    fil.start()
    try:
        trouve = trouver(nom, attente_s=5.0)
        chk(trouve is not None, "le flux de cette machine est trouvé par son nom")
        notes = iter(["C3 décollée", "", "C3 remise", "fin", "jamais lue"])

        def lire_note():
            time.sleep(0.7)
            return next(notes, None)

        with tempfile.TemporaryDirectory() as dossier:
            avant = local_clock()
            chemin, n = enregistrer(trouve, lire_note, dossier)
            apres = local_clock()
            with np.load(chemin) as z:
                signal, temps = z["signal"], z["horodatages"]
                lues = list(z["voies"]), list(z["notes"]), z["notes_t"]
            chk(os.path.dirname(chemin) == dossier
                and not os.path.abspath(chemin).startswith(os.path.abspath(DATA_DIR)),
                "le fichier va dans le dossier demandé, jamais dans data/")
            chk(signal.shape[1] == 8 and n > 200 and len(temps) == len(signal),
                f"le signal est là, un horodatage par échantillon ({signal.shape})")
            chk(lues[0] == voies, f"les noms des voies viennent du flux ({lues[0]})")
            chk(lues[1] == ["C3 décollée", "C3 remise"],
                f"les notes sont gardées, sans la ligne vide ni ce qui suit « fin » ({lues[1]})")
            chk(len(lues[2]) == 2 and avant <= lues[2][0] < lues[2][1] <= apres
                and temps[0] <= lues[2][1] <= temps[-1] + 1.0,
                "chaque note a son instant, sur la même horloge que le signal")

            def clavier_muet():
                time.sleep(60.0)
                return None

            t0 = time.time()
            _chemin, n_duree = enregistrer(trouve, clavier_muet, dossier, duree_s=1.0)
            chk(time.time() - t0 < 3.0 and n_duree > 0,
                f"avec une durée, l'enregistrement s'arrête seul, même si personne ne tape rien "
                f"({time.time() - t0:.1f} s)")
    finally:
        publie.set()
        fil.join(timeout=2.0)

    class _Faux:
        def __init__(self, hote):
            self.hote = hote

        def hostname(self):
            return self.hote

    garde = flux_de_cette_machine([_Faux("POSTE-1"), _Faux("autre"), _Faux("poste-1")], "poste-1")
    chk([f.hote for f in garde] == ["POSTE-1", "poste-1"],
        "seuls les flux de CETTE machine sont gardés, sans tenir compte de la casse")
    print(f"[enregistre-brut] VERDICT : {'OK' if ok else 'ÉCHEC'}")
    return ok


def main():
    use_utf8_console()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--duree", type=float, default=None, help="arrêt automatique après N secondes")
    p.add_argument("--dossier", default=SEANCES_DIR, help="où écrire (défaut : seances/)")
    p.add_argument("--smoke", action="store_true", help="autotest sur un faux flux")
    args = p.parse_args()
    if args.smoke:
        sys.exit(0 if _smoke() else 1)

    info = trouver(stream_name("raw"))
    if info is None:
        sys.exit(1)
    print(f"Enregistrement du flux brut ({info.channel_count()} voies, "
          f"{info.nominal_srate():g} Hz).")
    print(f"Tape une note puis Entrée (ex. « C3 décollée », « C3 remise ») ; « {FIN} » arrête.")
    chemin, n = enregistrer(info, input, args.dossier, args.duree)
    print(f"Écrit : {chemin} ({n} échantillons, {n / max(info.nominal_srate(), 1.0):.0f} s).")


if __name__ == "__main__":
    main()
