"""Les gardes PARTAGÉES par les autotests des fenêtres. Une seule écriture, quatre appelants.

Deux gardes vivent ici. La première protège `data/` (voir ci-dessous). La seconde protège le
VOCABULAIRE d'un test (`mot_du_geste`) : les trois fenêtres à marqueurs jouent le même protocole
pour entraîner et pour tester, et le seul repère de l'étudiant est le MOT. Elles l'ont eu faux
jusqu'au 2026-09-23 — plein écran « Calibration P300 » pendant la chauffe de chaque test, et un
ESC qui répondait « aucun modèle ne sera entraîné » alors qu'un test n'entraîne rien.



⚠️ **Pourquoi ce fichier existe.** `data/` porte des enregistrements EEG d'une personne
identifiable, sur un dépôt PUBLIC, et les modèles que le moteur propose par défaut. Un test qui y
écrit ne le dit pas : `git status --short data/` rend une sortie **vide** même après une écriture,
parce que le dossier est gitignoré. La seule preuve est une EMPREINTE prise avant et après.

Les douze `--smoke` de `archive/` l'ont, la console l'a. **Les quatre fenêtres de `stimulus/` ne
l'avaient pas** — constat de la revue du 2026-09-08 — alors que ce sont elles qu'on relance après
chaque modification, et qu'elles construisent désormais les runtimes de calibration du moteur.

Ce n'est pas une précaution théorique. Le 2026-09-08, un smoke d'archive dont le détournement de
dossier était devenu un no-op a écrit un modèle entraîné sur du bruit SYNTHÉTIQUE dans le vrai
`data/`, sous un nom que le catalogue liste — donc proposable par défaut à la séance casque
suivante. Sa propre garde d'empreinte existait, mais elle était placée APRÈS l'écriture.

⚠️ **Ce que la garde ne voit pas**, et il faut le savoir avant de s'y fier : une écriture SUIVIE
d'une suppression à l'intérieur du même smoke laisse l'empreinte inchangée. Elle attrape le fichier
oublié, pas le passage furtif. Cf. la docstring de `core.config.empreinte_dossier`.
"""

import contextlib as _contextlib
import io as _io
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from core.config import DATA_DIR, empreinte_dossier  # noqa: E402


def sous_garde_data(smoke):
    """Lance `smoke()` et refuse qu'il ait touché `data/`. Rend ce que rend `smoke`.

    L'empreinte est prise **avant tout travail** et relue dans un `finally` — dans cet ordre, et
    pas l'inverse : une garde posée après l'écriture ne prouve rien, et le `finally` fait que même
    un smoke qui lève emporte son verdict avec lui.
    """
    avant = empreinte_dossier(DATA_DIR)
    try:
        return smoke()
    finally:
        apres = empreinte_dossier(DATA_DIR)
        if apres != avant:
            ajoutes = sorted(set(apres) - set(avant))
            disparus = sorted(set(avant) - set(apres))
            raise AssertionError(
                f"ce smoke a TOUCHÉ le vrai data/ — {len(avant)} fichiers avant, "
                f"{len(apres)} après. Ajoutés : {ajoutes or 'aucun'} · disparus : "
                f"{disparus or 'aucun'} · sinon un contenu a changé. `data/` porte des "
                f"enregistrements EEG d'une personne identifiable et les modèles que le moteur "
                f"propose par défaut : un test n'y écrit jamais.")


def paroles_de_seance(run, **kwargs):
    """Joue `run(**kwargs)` en CAPTURANT ce qu'elle imprime. Rend `(fini, texte)`.

    Ce que la fenêtre imprime n'est pas un détail de confort : c'est le seul récit qui reste
    quand la séance est finie et l'écran éteint. Un autotest qui ne le lit pas laisse passer
    n'importe quel mot.
    """
    tampon = _io.StringIO()
    with _contextlib.redirect_stdout(tampon):
        fini = run(**kwargs)
    return fini, tampon.getvalue()


def mot_du_geste(chk, texte, marqueur, etiquette):
    """La ligne qui porte `marqueur` dit « test », et AUCUN autre mot de geste.

    On vise une LIGNE, pas le texte entier : une fenêtre a le droit de citer
    `core/modes/marker_calib.py` ou de comparer ses durées à celles de l'entraînement. Ce qu'elle
    n'a pas le droit de faire, c'est d'appeler CETTE séance-ci d'un autre nom que le sien.

    ⚠️ La ligne doit EXISTER : sans ce premier `chk`, supprimer le message ferait taire la
    fenêtre et passer le test — une assertion verte parce qu'elle ne lit rien (leçon du chantier
    « Configurer · Entraîner · Tester »).
    """
    lignes = [l for l in texte.splitlines() if marqueur in l]
    chk(len(lignes) == 1,
        f"{etiquette} : une séance de TEST imprime sa ligne « {marqueur} » "
        f"(trouvé {len(lignes)} fois)")
    bas = (lignes[0] if lignes else "").lower()
    chk(bool(lignes) and "test" in bas
        and "calibration" not in bas and "calibrer" not in bas and "entraîn" not in bas,
        f"{etiquette} : ...et elle l'appelle « test », jamais calibration ni entraînement "
        f"({(lignes[0] if lignes else '—')[:100]})")
