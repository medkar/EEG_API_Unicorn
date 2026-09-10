"""La garde de `data/` pour les autotests des fenêtres. Une seule écriture, quatre appelants.

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
