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

# Le vocabulaire de phase du moteur, rendu en français. UNE seule fois : la tuile de la grille et
# la page du mode affichent la même phase du même mode, et deux tables séparées finiraient par se
# contredire — un mode annoncé « repos » ici et « rest » là.
PHASES_FR = {"warmup": "chauffe", "rest": "repos", "running": "décode"}

# Le SSVEP : jusqu'où va la barre. Une barre pleine à ras le seuil laisserait croire qu'on est au
# maximum alors qu'on vient à peine de déclencher — d'où 2× le seuil. Ici et pas dans chaque
# écran : la tuile et la page ont divergé sur ce facteur (tuile 1×, page 2×), au point qu'un même
# score de 3,1 pour un seuil de 2,5 s'affichait « barre PLEINE » sur la grille et « 62 % » sur la
# page. Deux écrans, mêmes données, deux lectures.
SSVEP_SPAN_SEUILS = 2.0


def classement_relatif(scores):
    """Des scores SANS échelle absolue -> une part de 0 à 1 par cible. UNE seule écriture.

    Le P300 publie des log-odds moyens : non bornés, négatifs le plus souvent (une cible flashe
    une fois sur six), non comparables d'une manche à l'autre. Une barre « remplie à 40 % d'un
    maximum » n'aurait donc aucun sens ; ce qu'on montre est le CLASSEMENT — la plus faible vide,
    la plus forte pleine — parce que c'est l'écart 1er-2e qui décide.

    ⚠️ **Cette fonction existe parce que la règle a déjà divergé une fois.** Elle était écrite
    deux fois, mot pour mot : dans `live_views.ActiveView._update_selection` (la page) et dans
    `grid.ModeTile._apercu_scores` (la tuile). La page a été corrigée lors d'un chantier, la tuile
    oubliée — et pendant ce temps la grille montrait six moignons de 2 px là où la page montrait
    un classement lisible. Les deux ont été remises d'accord ; les garder d'accord demande
    qu'elles appellent le MÊME code, pas qu'elles se ressemblent.

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
