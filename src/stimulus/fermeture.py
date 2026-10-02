"""Fermer une fenêtre SANS perdre ses derniers marqueurs. Une écriture, les quatre fenêtres.

⚠️ **Mesuré le 2026-10-02** (vrai moteur synthétique, vraie fenêtre c-VEP `--tester`, flux isolés)
: le `calib_end` s'est perdu dans 2 séances sur 5. Le test restait alors en « essais » sans verdict
(« la séance ATTEND »), et un entraînement serait resté sans modèle. Le moteur l'a même dit : « inlet
de marqueurs en erreur : the stream has been lost ».

**La cause.** Le moteur lit les marqueurs par un inlet `recover=False` (`core/markers.py`, pour une
raison mesurée là-bas). Avec `recover=False`, liblsl JETTE un échantillon DÉJÀ REÇU si l'émetteur
disparaît avant qu'on ne l'ait tiré : `pull_sample` lève `LostError` au lieu de le rendre (vérifié en
isolé : un marqueur poussé 200 ms avant la mort de l'outlet, tiré 500 ms après, est perdu). Or une
fenêtre publiait `calib_end` puis rendait la main quelques millisecondes plus tard, ce qui détruisait
son outlet. Le moteur, qui tire ses marqueurs une fois par tour de boucle (`POLL_S` = 50 ms), perdait
la course une fois sur deux.

**Le remède, ici et une seule fois.** Après le DERNIER marqueur, l'outlet reste vivant `DELAI_S`
avant que la fenêtre ne rende la main — si quelqu'un l'écoute. On l'appelle APRÈS `pygame.quit()` :
la fenêtre a déjà disparu de l'écran, seul le processus attend. Ce n'est pas un critère observable,
c'est un délai BORNÉ : le contrat des marqueurs n'a aucun accusé de réception, et la fenêtre ne peut
pas savoir ce que le moteur a lu. 2 s, c'est 40 tours de boucle du moteur. Le tirage n'attend pas la
maturité de l'époque (`markers_murs`) : un marqueur tiré est en sécurité dans la file du moteur,
même si son époque n'est pas encore complète.

Autotest (aucun casque, aucun moteur, un flux de test au nom unique) :
    python src/stimulus/fermeture.py
"""

import os as _os
import sys as _sys
import time as _time

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

DELAI_S = 2.0


def laisser_tirer(outlet, delai_s=None, dormir=_time.sleep):
    """Garde `outlet` vivant `delai_s` (défaut `DELAI_S`) si quelqu'un l'écoute, pour que le moteur
    tire les derniers marqueurs avant que l'outlet ne meure. Rend la durée attendue (0.0 si personne
    n'écoute : il n'y a rien à perdre, et un `--smoke` sans consommateur n'attend pas).

    À appeler juste avant que la fenêtre ne rende la main, APRÈS son dernier marqueur. Les fenêtres
    l'appellent par le MODULE (`fermeture.laisser_tirer(outlet)`) : c'est ce texte-là que
    l'autotest cherche dans leur `run`.
    """
    try:
        ecoute = outlet is not None and bool(outlet.have_consumers())
    except Exception:  # noqa: BLE001 - dans le doute, attendre : 2 s ne coûtent rien
        ecoute = True
    if not ecoute:
        return 0.0
    attente = DELAI_S if delai_s is None else float(delai_s)
    dormir(attente)
    return attente


FENETRES = ("cvep.py", "p300.py", "errp.py", "ssvep.py")


def _texte_de_run(fichier):
    """Le texte de `def run(` jusqu'à la définition suivante de premier niveau."""
    with open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), fichier),
              encoding="utf-8") as f:
        texte = f.read()
    debut = texte.index("\ndef run(")
    fin = texte.find("\ndef ", debut + 1)
    return texte[debut:fin if fin >= 0 else len(texte)]


def _appelle_apres_quit(texte):
    """Vrai si `fermeture.laisser_tirer(outlet)` suit le DERNIER `pygame.quit()` de `run`."""
    return 0 <= texte.rfind("pygame.quit()") < texte.rfind("fermeture.laisser_tirer(outlet)")


def _seance_isolee(nom, delai_s, poll_s):
    """Un émetteur qui publie `calib_start`, quelques `cue`, puis `calib_end` et rend la main ;
    en face, l'inlet du MOTEUR (`core.markers.MarkerInlet`, `recover=False`) tiré toutes les
    `poll_s`, comme le fait la boucle du moteur. Rend la liste des événements reçus."""
    import json
    import threading

    from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet

    from core.markers import MarkerInlet

    outlet = StreamOutlet(StreamInfo(nom, "Markers", 1, IRREGULAR_RATE, "string", nom))
    inlet = MarkerInlet(nom)
    recus, arret = [], threading.Event()

    def moteur():
        while not arret.is_set():
            try:
                if not inlet.connecte:
                    inlet.resolve()
                recus.extend(m.get("event") for _ts, m in inlet.pull())
            except Exception:  # noqa: BLE001 - LostError : le marqueur en attente est PERDU
                pass
            arret.wait(poll_s)

    fil = threading.Thread(target=moteur, daemon=True)
    fil.start()
    fin = _time.perf_counter() + 5.0
    while not outlet.have_consumers() and _time.perf_counter() < fin:
        _time.sleep(0.01)
    for m in ({"event": "calib_start"}, {"event": "cue"}, {"event": "calib_end"}):
        outlet.push_sample([json.dumps(dict(m, mode="test"))])
    laisser_tirer(outlet, delai_s=delai_s)
    del outlet                       # la fenêtre rend la main : son outlet meurt ICI
    _time.sleep(max(0.5, 3 * poll_s))
    arret.set()
    fil.join(timeout=2.0)
    inlet.lache("fin de l'autotest")
    return recus


def _selftest():
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _Muet:
        def have_consumers(self):
            return False

    attendu = []
    chk(laisser_tirer(_Muet(), dormir=attendu.append) == 0.0 and not attendu
        and laisser_tirer(None, dormir=attendu.append) == 0.0,
        "personne n'écoute (ou pas d'outlet) : on n'attend PAS — un `--smoke` reste rapide")

    class _Ecoute:
        def have_consumers(self):
            return True

    chk(laisser_tirer(_Ecoute(), dormir=attendu.append) == DELAI_S and attendu == [DELAI_S],
        f"quelqu'un écoute : l'outlet reste vivant {DELAI_S:g} s")

    # Le CÂBLAGE : chaque fenêtre l'appelle dans `run`, après son dernier `pygame.quit()`. Lu
    # dans la SOURCE (les importer coûterait pygame) — une fenêtre qui l'oublie rougit ici.
    oublis = [f for f in FENETRES if not _appelle_apres_quit(_texte_de_run(f))]
    chk(not oublis,
        f"les {len(FENETRES)} fenêtres gardent leur outlet après `pygame.quit()` "
        f"({oublis or 'aucun oubli'})")
    sans_appel = _texte_de_run(FENETRES[0]).replace("fermeture.laisser_tirer(outlet)", "pass")
    chk(not _appelle_apres_quit(sans_appel),
        "…et la même lecture rougit sur une fenêtre qui ne l'appelle pas (mutation)")

    # 🔴 La perte, sur un VRAI flux et l'inlet RÉEL du moteur, tiré à la cadence du moteur. Cinq
    # séances : aucun `calib_end` perdu. Puis le délai RETIRÉ (la fenêtre d'avant) : la perte
    # revient — sinon cette garde ne prouverait rien.
    from core.server import POLL_S

    base = f"EEG_API_Unicorn_fermeture_smoke_{_os.getpid()}"
    avec = [_seance_isolee(f"{base}_{i}", None, POLL_S) for i in range(5)]
    chk(all(r[-1:] == ["calib_end"] for r in avec),
        f"5 séances, outlet gardé {DELAI_S:g} s : le moteur (inlet `recover=False`, tiré toutes les "
        f"{POLL_S:g} s) reçoit CHAQUE `calib_end` ({[r[-1:] for r in avec]})")
    sans = [_seance_isolee(f"{base}_m{i}", 0.0, POLL_S) for i in range(5)]
    perdus = sum(1 for r in sans if "calib_end" not in r)
    chk(perdus >= 1,
        f"…et SANS le délai, la perte est bien là : {perdus} `calib_end` perdu(s) sur 5 (la garde "
        f"mord sur la panne qu'elle prétend empêcher)")

    print(f"[fermeture] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    from core.config import use_utf8_console

    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
