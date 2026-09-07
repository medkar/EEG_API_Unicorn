"""La piste de l'ErrP : où va le point, quand la machine se trompe, combien de temps on attend.

Ce module n'existait pas avant le 2026-09-07, et son absence était un défaut connu, écrit noir sur
blanc dans le code qu'il remplace : *« ⚠️ Cette fonction est un DOUBLE de `_decide_step`, pas
encore une source unique »*. Il y avait DEUX implémentations de la même règle — celle de
`research/errp_calibrate.py`, sous laquelle les modèles ont été entraînés, et celle de l'émetteur,
sous laquelle ils sont appliqués — et un test qui rejouait 500 pas à graine égale pour vérifier
qu'elles ne divergeaient pas. Un test pareil est un aveu : il protège une duplication au lieu de la
supprimer, et il ne peut rien dire du 501e pas.

Le déménagement dans `core` est ce que la règle du projet prescrit : quand `stimulus` a besoin de
ce que `research` détient, ce n'est pas la frontière qu'on assouplit, c'est le module qui déménage.
La calibration ErrP jouée par le moteur en aura besoin à son tour.

⚠️ **Les trois pauses ne sont pas des réglages de confort.** Ce sont les durées sous lesquelles les
époques du modèle du 2026-07-24 (AUC 0,776) ont été enregistrées. Les changer sans réentraîner
décale la position du feedback dans l'époque, ce qui ne lève aucune erreur et dégrade le décodage
en silence.

Autotest :
    python src/core/errp_track.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from core.config import use_utf8_console  # noqa: E402

# Les trois temps d'attente de la piste, en secondes. Ils étaient jusqu'ici des LITTÉRAUX dans
# `research/errp_calibrate.py:_run_block` et des constantes RECOPIÉES dans l'émetteur, arrimées
# l'une à l'autre par un test qui lisait le code source de `_run_block` avec `inspect.getsource`.
# Le test disparaît avec la duplication : les deux lisent désormais le même nom.
PAUSE_INTER_PAS_S = 0.45        # entre deux pas d'une même course — SOA intra-course 1,45 s
PAUSE_FIN_COURSE_S = 0.7        # état FINAL : le point est sur la cible (ou on renonce)
PAUSE_NOUVELLE_COURSE_S = 0.9   # état NEUF : point au centre, cible redéplacée
# ⚠️ DEUX écrans statiques par fin de course, pas un, et le second est celui qui compte. Sans lui,
# la remise à zéro — le point saute de plusieurs cases ET la cible change d'extrémité une fois sur
# deux — tombait dans la frame horodatée du pas SUIVANT : l'époque commençait sur un transitoire
# visuel plein écran qui n'est pas le feedback qu'elle prétend mesurer. Mesuré sur 200 séances
# simulées : 14,9 % des époques partaient ainsi.


def nouvelle_cible(n_cells, rng):
    """La cible, à L'UNE des deux extrémités de la piste (tirage 50/50).

    Choix voulu : sur l'ensemble d'une séance, les erreurs (des pas qui ÉLOIGNENT) sont autant à
    gauche qu'à droite, donc le SENS du mouvement est décorrélé de l'étiquette erreur/correct. Un
    décodeur ne peut pas apprendre la direction à la place de l'ErrP (Chavarriaga 2010 équilibre
    ainsi).
    """
    return rng.choice([0, n_cells - 1])


def decide_pas(rng, pos, cible, n_cells, taux_erreur, force=None):
    """Un pas du point : il avance d'une case vers `cible`, ou s'en éloigne si erreur DÉLIBÉRÉE.

    `force` (utilisé par les smokes) impose une erreur (`True`) ou un pas correct (`False`) ;
    sinon le tirage se fait à `taux_erreur`. Rebond au bord de la piste — sans lui, un point qui
    atteint une extrémité en sortirait.

    Retourne `(nouvelle_pos, erreur)`. ⚠️ **`erreur` suit l'EFFET RÉEL du pas**, après rebond
    éventuel, pas l'intention du tirage : un rebond transforme un tirage « erreur » en pas qui
    rapproche, et c'est le pas VU par la personne qui produit — ou non — un potentiel d'erreur.
    Étiqueter l'intention plutôt que l'effet apprendrait au modèle le contraire de ce qu'il doit
    détecter, sur environ un pas de bord sur deux.
    """
    vers = 1 if cible > pos else -1
    erreur_tiree = (rng.random() < taux_erreur) if force is None else bool(force)
    pas = -vers if erreur_tiree else vers
    nouvelle_pos = pos + pas
    if nouvelle_pos < 0 or nouvelle_pos >= n_cells:            # bord -> rebond dans l'autre sens
        nouvelle_pos = pos - pas
    return nouvelle_pos, abs(nouvelle_pos - cible) > abs(pos - cible)


def _selftest():
    """Les quatre propriétés dont dépend la validité des modèles ErrP déjà entraînés."""
    import random

    use_utf8_console()
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    n = 9
    rng = random.Random(1234)

    # 1. La cible est à une extrémité, et les deux sortent.
    tirages = [nouvelle_cible(n, rng) for _ in range(400)]
    chk(set(tirages) == {0, n - 1}, f"la cible est TOUJOURS à une extrémité ({sorted(set(tirages))})")
    part_gauche = tirages.count(0) / len(tirages)
    chk(0.40 < part_gauche < 0.60,
        f"…et les deux extrémités sortent autant (gauche {part_gauche:.2f}) — c'est ce qui "
        f"décorrèle le SENS du mouvement de l'étiquette, sans quoi un décodeur apprendrait la "
        f"direction à la place de l'ErrP")

    # 2. Le point ne sort jamais de la piste.
    rng = random.Random(7)
    pos, cible, dehors = n // 2, nouvelle_cible(n, rng), 0
    for _ in range(3000):
        pos, _err = decide_pas(rng, pos, cible, n, 0.3)
        dehors += int(not 0 <= pos < n)
        if pos == cible:
            pos, cible = n // 2, nouvelle_cible(n, rng)
    chk(dehors == 0, f"le point reste sur la piste, rebond de bord compris ({dehors} sorties)")

    # 3. L'étiquette suit l'EFFET, pas l'intention — et le rebond en fabrique la preuve.
    #    Au bord, un tirage « erreur » ne PEUT PAS éloigner : le pas est renvoyé vers l'intérieur,
    #    donc vers la cible opposée. Si l'étiquette suivait l'intention, elle dirait « erreur ».
    rng = random.Random(0)
    pos_bord, cible_loin = 0, n - 1
    nouvelle, erreur = decide_pas(rng, pos_bord, cible_loin, n, 0.0, force=True)
    chk(nouvelle == 1 and erreur is False,
        f"au bord, un tirage « erreur » rebondit VERS la cible et l'étiquette dit correct "
        f"(pos {pos_bord}->{nouvelle}, erreur={erreur})")

    # 4. Le taux d'erreur joué est celui qu'on demande — hors effets de bord.
    rng = random.Random(99)
    pos, cible, erreurs, total = n // 2, nouvelle_cible(n, rng), 0, 4000
    for _ in range(total):
        pos, err = decide_pas(rng, pos, cible, n, 0.28)
        erreurs += int(err)
        if pos == cible:
            pos, cible = n // 2, nouvelle_cible(n, rng)
    taux = erreurs / total
    chk(0.20 < taux < 0.32,
        f"le taux d'erreurs RÉELLES reste proche du taux demandé ({taux:.3f} pour 0,28). Les deux "
        f"ne sont pas identiques et n'ont pas à l'être : un rebond de bord annule l'erreur tirée, "
        f"et la course redémarre au centre, d'où un écart de quelques millièmes dans un sens ou "
        f"dans l'autre selon la graine")

    # 5. Les trois pauses sont celles sous lesquelles le modèle a été enregistré.
    chk((PAUSE_INTER_PAS_S, PAUSE_FIN_COURSE_S, PAUSE_NOUVELLE_COURSE_S) == (0.45, 0.7, 0.9),
        "les trois pauses valent 0,45 / 0,7 / 0,9 s — les durées du modèle du 2026-07-24 "
        "(AUC 0,776). Les changer sans réentraîner décale le feedback dans l'époque, en silence")

    print(f"[errp-track] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
