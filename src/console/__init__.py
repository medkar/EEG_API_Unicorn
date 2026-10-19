"""`console` — la console d'expérimentation (PySide6). Un CLIENT du moteur, pas le moteur.

Elle crée un `EngineServer`, lance sa boucle dans un fil, et sonde `snapshot()` par un `QTimer`.
Aucun HTTP, aucun navigateur.

**Deux règles, et elles ne sont pas négociables :**

1. *Le fil Qt ne touche jamais la session BrainFlow.* Toute action passe par `engine.submit()`,
   qui met la commande en file pour que la boucle du moteur l'applique elle-même. C'est ce qui
   protège l'acquisition.
2. *Aucune logique ici que le moteur ne possède pas déjà.* Pas de validation seulement côté
   console, pas de catalogue de modes en dur, pas de règle métier dans le code d'affichage. La
   console rend et envoie des commandes. C'est ce qui garde la majorité du travail testable sans
   écran, et ce qui rendrait un futur changement d'interface peu coûteux.

`console` importe `core`. `core` ne sait pas que `console` existe.
"""

import os as _os
import sys as _sys

# Qt choisit son backend d'affichage à l'IMPORT, pas à la création de la QApplication : ce
# réglage doit donc être posé avant le premier `import PySide6`, où qu'il ait lieu. Ici plutôt
# que dans `app.py` parce que Python exécute TOUJOURS ce fichier avant n'importe quel
# sous-module du paquet — un futur `import console.grid` isolé reste donc couvert.
if "--smoke" in _sys.argv:
    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.i18n import tr  # noqa: E402


def nom_phase(phase):
    """Le vocabulaire de phase du moteur (`warmup`, `rest`, `running`), dans la langue de l'écran.

    UNE seule fois : la tuile de la grille et la page du mode affichent la même phase du même
    mode, et deux tables séparées finiraient par se contredire — un mode annoncé « repos » ici et
    « rest » là. Une phase inconnue s'affiche telle quelle plutôt que de disparaître.
    """
    noms = {"warmup": tr("console.phase.chauffe"), "rest": tr("console.phase.repos"),
            "running": tr("console.phase.decode")}
    return noms.get(phase, phase)


def decompte(mode_state):
    """« décodage dans ≈ 32 s », « encore un instant… », ou "" quand le mode décode déjà.

    Le temps vient du MOTEUR (`avant_decodage_s`), qui connaît ses échéances ; la console ne
    fait que l'écrire. À zéro, le repos se prolonge peut-être (le SSVEP attend d'avoir assez de
    fenêtres) : on ne l'affiche pas en négatif, on dit qu'il faut encore un instant.
    """
    avant = (mode_state or {}).get("avant_decodage_s")
    if avant is None:
        return ""
    if avant < 0.5:
        return tr("console.decompte.instant")
    return tr("console.decompte.secondes", s=int(round(avant)))


def compter(n, unite):
    """« 0 manche », « 1 manche », « 6 manches » — `unite` est celle que le MOTEUR publie.

    ⚠️ L'unité n'est pas un détail d'affichage : un test réglé en « manches » doit compter en
    manches, pas dans le vocabulaire du contrôle alpha (« phases enregistrées », « fenêtres
    prélevées »), sinon l'élève lit « 12 phases sur 288 » sous un verdict « … sur 6 manches ».
    Le moteur publie l'unité de chaque protocole (`state()["unite"]`) ; la console n'en connaît
    aucune.

    La règle du pluriel appartient à la LANGUE, pas au code : son suffixe et les terminaisons qui
    ne varient pas sont lus dans le catalogue (« s », et « s,x,z » en français).
    """
    invariables = tuple(f for f in tr("console.pluriel.invariables").split(",") if f)
    mot = unite if n <= 1 or unite.endswith(invariables) else unite + tr("console.pluriel.suffixe")
    return tr("console.compte", n=n, unite=mot)

# Jusqu'où va la barre d'un mode qui PUBLIE UN SEUIL. Une barre pleine à ras le seuil laisserait
# croire qu'on est au maximum alors qu'on vient à peine de déclencher — d'où 2× le seuil, ce qui
# place le déclenchement à mi-hauteur, un repère visuel immédiat. Défini ici et pas dans chaque
# écran : si la tuile et la page n'avaient pas le même facteur, un même score s'afficherait
# « barre pleine » sur la grille et « 62 % » sur la page (mêmes données, deux lectures).
# Le facteur n'appartient à aucun mode : le SSVEP (z) et le c-VEP (`corr_min`) s'en servent
# pareillement.
SPAN_SEUILS = 2.0


def span_correlation(corr_min):
    """L'échelle absolue d'un score BORNÉ (le c-VEP), contre le seuil que le mode PUBLIE.

    PLAFOND à 1 et non plancher, contrairement au z du SSVEP : une corrélation de Pearson vit
    dans [-1, 1], et `2 x 0,26 = 0,52` est justement l'échelle qui sépare 0,21 (décision fausse)
    de 0,33 (décision juste) — les deux seuls chiffres que ce projet ait mesurés. La formule du
    SSVEP (`max(..., 1.0)`) écraserait les deux dans le tiers bas de la barre, visuellement
    identiques.

    ⚠️ **La tuile (`grid.ModeTile._apercu_scores`) et la page
    (`live_views.ActiveView._update_correlations`) appellent cette même fonction** : écrite
    deux fois, la règle dérive. Le cas qui les séparait est `corr_min = 0`, valeur LÉGALE
    (`min=0.0` sur le réglage) et courante en séance (cf. docs/recette.md, test 2.9) : l'une
    affichait 33 %, l'autre toutes les barres pleines, deux diagnostics opposés.

    `corr_min = 0` veut dire « aucun seuil ne borne l'échelle » : on retombe alors sur l'échelle
    absolue complète d'une corrélation, 1,0. Jamais 0 — une échelle nulle rend toute barre pleine.
    """
    span = min(SPAN_SEUILS * float(corr_min), 1.0)
    return span if span > 0.0 else 1.0


def classement_relatif(scores):
    """Des scores SANS échelle absolue -> une part de 0 à 1 par cible. UNE seule écriture.

    Le P300 publie des log-odds moyens : non bornés, négatifs le plus souvent (une cible flashe
    une fois sur six), non comparables d'une manche à l'autre. Une barre « remplie à 40 % d'un
    maximum » n'aurait donc aucun sens ; ce qu'on montre est le CLASSEMENT — la plus faible vide,
    la plus forte pleine — parce que c'est l'écart 1er-2e qui décide.

    ⚠️ **La page (`live_views.ActiveView._update_selection`) et la tuile
    (`grid.ModeTile._apercu_scores`) appellent cette même fonction.** Deux copies de la règle
    dérivent : la grille montrerait six moignons de 2 px là où la page montre un classement
    lisible. Rester d'accord demande d'appeler le MÊME code, pas de se ressembler.

    `etendue <= 0` (scores tous égaux, ou une seule cible) laisse tout à mi-hauteur : ni division
    par zéro, ni gagnant désigné qui n'en est pas un.
    """
    valeurs = [float(s) for s in (scores or [])]
    if not valeurs:
        return []
    bas, haut = min(valeurs), max(valeurs)
    etendue = haut - bas
    if etendue <= 0:
        return [0.5] * len(valeurs)
    return [max(0.0, min((v - bas) / etendue, 1.0)) for v in valeurs]
