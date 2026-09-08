"""Calibration c-VEP : fixer chaque cible quelques secondes -> template + filtre spatial.

Plus courte que la calibration Motor Imagery (~3 min contre 5-7 min) parce qu'on n'apprend pas
une intention mentale, seulement la **forme de ta réponse visuelle** au code. ⚠️ La durée exacte
est CALCULÉE et imprimée au lancement (`≈ X.X min`, cf. `calibrate`) : aux réglages du dépôt
(6 cibles × `CVEP_CAL_CYCLES`=15 cycles, `CVEP_CAL_BLOCKS`=3 → 18 blocs entrelacés) elle vaut
**≈ 2,7 min**, hors briefing et hors contrôle de liaison. Le « ~1 min » qui traînait dans la doc
datait d'un réglage antérieur.

Déroulé : les 3 cibles clignotent en permanence avec le même code décalé ; on te demande
d'en fixer une, et on enregistre `CVEP_CAL_CYCLES` cycles complets. On recommence pour
chaque cible. Enregistrer les 3 (plutôt qu'une seule) coûte le même temps total et vérifie
en prime que l'alignement des lags est bon (l'accuracy leave-one-out le dit).

Chaque époque est prélevée EXACTEMENT à une frontière de cycle (frame % L == 0) : la
fenêtre couvre alors le cycle qui vient de s'écouler, donc démarre à la phase 0 du code.
"""

import os
import random
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (CH_NAMES, CVEP_BAND, CVEP_CAL_BLOCKS,  # noqa: E402
                    CVEP_CAL_CYCLES, CVEP_CHANNELS, CVEP_DECISION_CYCLES, CVEP_LAG_ROTATION,
                    CVEP_MODEL_PATH, CVEP_RCCA_MODEL_PATH, FS_UNICORN, cvep_lag_gap_ms,
                    use_utf8_console)
from core.cvep_code import blocs_entrelaces, build_targets, is_on  # noqa: E402
from core.cvep_decoder import CVEPModel, groupes_de_cycles  # noqa: E402
# ⚠️ `_mcnemar_p` et `SEUIL_MCNEMAR` sont NÉS ici (commit `bd3b588`) et ont DÉMÉNAGÉ dans `core/` :
# `core/cvep_rcca.py::_rejouer` (la commande `--seuils`) en a besoin lui aussi, et `core/`
# n'importe JAMAIS `research/`. La règle du dépôt dit exactement quoi faire dans ce cas — le module
# visé déménage. Importés ici pour que `_gagnant` et l'écran continuent d'appeler LE MÊME objet,
# pas une seconde copie qui divergerait un jour.
from core.cvep_rcca import SEUIL_MCNEMAR, RCCAModel, _mcnemar_p  # noqa: E402
from research.itr import itr  # noqa: E402
from research.ui import BG, DIM, FG, GO, WARN, Abort  # noqa: E402

SETTLE_CYCLES = 2   # cycles jetés après un changement de cible (déplacement du regard + VEP qui s'installe)
# Plancher d'utilité pour le contrôle de séance (bits/min). ~1/3 du meilleur c-VEP mesuré
# (27,1) : en dessous, la séance n'apprend rien qu'on ne sache déjà. Voir `_early_check`.
EARLY_ITR_MIN = 10.0

BRIEF = [
    "Calibration c-VEP",
    "",
    "• Les cibles clignotent selon un code pseudo-aléatoire (ça « grésille », c'est normal).",
    "• Une cible est CERCLÉE : fixe-la, sans bouger les yeux, jusqu'au changement.",
    "• Regard bien PLANTÉ sur le disque (contrairement au Motor Imagery : ici le regard compte).",
    "• Cligne le moins possible pendant l'enregistrement, reste immobile.",
    "• La durée totale est affichée dans la console au lancement.",
    "",
    "Appuie sur une touche pour commencer (ESC pour annuler).",
]


def _briefing(app):
    while True:
        pressed = []
        app.drain(on_key=lambda e: pressed.append(True))
        if pressed:
            return True
        app.win.fill(BG)
        h = app.win.get_height()
        y = int(h * 0.16)
        for i, line in enumerate(BRIEF):
            f = app.big if i == 0 else app.small
            col = FG if i == 0 else (GO if line.startswith("Appuie") else FG)
            app.center(f, line, col, y)
            y += int(h * 0.085) if i == 0 else int(h * 0.056)
        app.pygame.display.flip()
        app.clock.tick(60)
        if app.smoke:
            return True


def _make_blocks(plan, cycles, n_blocks):
    """Le plan des blocs entrelacés — DÉLÈGUE à `core.cvep_code.blocs_entrelaces`.

    ⚠️ La règle a DÉMÉNAGÉ dans `core/` (chantier « la console, seul point d'entrée », tâche 8) :
    la fenêtre `src/stimulus/cvep.py` la joue elle aussi maintenant, et `stimulus` n'a pas le
    droit d'importer `research`. Deux exemplaires de la même règle de protocole finiraient par
    diverger sans que personne le voie. Ce passe-plat reste pour ne pas toucher `calibrate()`.
    """
    return blocs_entrelaces(plan, cycles, n_blocks, random)


def _wilson_hi(acc, n, z=1.96):
    """Borne SUPÉRIEURE de l'intervalle de Wilson (petits effectifs)."""
    if n == 0:
        return 1.0
    d = 1 + z * z / n
    c = (acc + z * z / (2 * n)) / d
    h = z * ((acc * (1 - acc) / n + z * z / (4 * n * n)) ** 0.5) / d
    return min(1.0, c + h)


def _early_check(model, epochs, lags, n_targets):
    """Verdict à mi-parcours : « cette séance peut-elle encore donner quelque chose ? »

    Le 2026-07-20 on a dépensé 4,5 min de casque sur une séance à 3,0 bits/min, et AUCUN
    indicateur pré-séance ne l'avait vue venir (le ratio alpha valait 18,93, le meilleur
    jamais mesuré ; la dérive brute ne discrimine pas). La seule mesure qui marche est la
    performance elle-même — autant la lire pendant l'enregistrement plutôt qu'après.

    ⚠️ Critère volontairement ASYMÉTRIQUE : on convertit la borne HAUTE de Wilson en ITR et
    on n'alerte que si même l'hypothèse la PLUS FAVORABLE reste inutile. Un LOO à mi-parcours
    porte sur peu d'époques : le lire comme une estimation ponctuelle ferait abandonner des
    séances correctes. Pas d'alerte ne veut donc PAS dire « ça va bien », seulement « on ne
    peut pas encore l'exclure » — c'est exactement ce qu'on attend d'un garde-fou.

    ⚠️ Le critère est en BITS/MIN, pas en accuracy. Une première version comparait l'accuracy
    à 2x le hasard : elle attrapait les liaisons mortes mais RATAIT la séance à 8 cibles du
    2026-07-20 (LOO 21 %, borne haute 30 %, seuil 25 % -> « continue », résultat final
    3,0 bits/min). Normal : 21 % à 8 cibles est réellement au-dessus du hasard, la séance
    n'était pas morte, elle était médiocre — et « 2x le hasard » ne veut pas dire la même
    chose à 4, 6 ou 8 cibles. L'ITR est la seule échelle comparable entre configurations.

    Le seuil vient de l'UTILITÉ projet, pas d'un ajustement sur les données : une séance qui
    ne peut pas atteindre ~1/3 de notre meilleur c-VEP (27,1 bits/min) n'apprend rien.
    Distinction importante — sur les 6 séances archivées, n'importe quel seuil entre 9 et 15
    « fonctionne », donc les valider dessus ne prouverait rien (4 points informatifs, 2
    dégénérés à 0). À revoir quand on aura une dizaine de séances.

    LIMITE CONNUE : ne détecte pas une séance qui s'effondre APRÈS le contrôle (la séance
    14:09 était à 15,8 de borne haute à 40 % puis a fini à 0, avec une accuracy décroissante
    au fil des tiers). Un contrôle ponctuel ne peut pas prédire une dégradation ultérieure.

    Retourne (alerte, accuracy, itr_borne_haute) ou None si les données ne suffisent pas.
    """
    by_lag = {}
    for l in lags:
        by_lag[l] = by_lag.get(l, 0) + 1
    if len(by_lag) < n_targets or min(by_lag.values()) < 2:
        return None                      # toutes les cibles doivent avoir été vues
    probe = CVEPModel(fs=model.fs, refresh=model.refresh, code_len=model.code_len)
    probe.channels = model.channels          # suivre le modèle réel, pas le défaut de config
    probe.fit([e[:, probe.channels] for e in epochs], lags)
    acc = probe.cv_
    if acc is None:
        return None
    hi = _wilson_hi(acc, len(epochs))
    hi_itr = itr(n_targets, hi, model.n_cyc / model.fs)
    return (hi_itr < EARLY_ITR_MIN), acc, hi_itr


def _fit_et_compte(modele, epochs, labels, **kw):
    """Ajuste `modele` sur EXACTEMENT `epochs`/`labels`, et rend `len(epochs)` — capturé ICI, au
    point d'appel, pour qu'un futur tronquage de l'ARGUMENT (`epochs[:-6]`) se voie dans le
    compte rendu, et pas seulement dans le modèle ajusté. Un `len(labels)` recalculé ailleurs,
    lui, ne bougerait pas si un seul des deux appels était tronqué — c'est exactement le trou que
    la revue de tâche 6 a trouvé dans `n_epoques`."""
    modele.fit(epochs, labels, **kw)
    return len(epochs)


def entraine_les_deux(epochs, labels, fs=FS_UNICORN, refresh=60.0, band=CVEP_BAND,
                      channels=None, n_cycles=CVEP_DECISION_CYCLES):
    """Entraîne eCCA ET rCCA sur les MÊMES époques de calibration, PARMI LE MÊME JEU DE CIBLES,
    les note HORS-PLI sur les MÊMES groupes de validation croisée, et rend
    `{"eCCA": {...}, "rCCA": {...}}`.

    ⚠️ Ce n'est PAS une nouvelle analyse : `CVEPModel.hors_pli` et `RCCAModel.hors_pli` existent
    depuis la tâche 3 (jumeaux, même contrat `(epochs, labels, n_cycles) -> scores`) et sont déjà
    éprouvés — `python src/core/cvep_rcca.py --seuils <calib.npz>` les fait déjà tourner côte à
    côte sur une calibration réelle (43/90 chacun, à k=1). Cette fonction se contente de les
    appeler tous les deux sur les mêmes entrées et de porter le résultat jusqu'à l'écran.

    `n_cycles` vaut `CVEP_DECISION_CYCLES` par défaut : c'est la géométrie où le MOTEUR décide,
    pas celle d'une époque de calibration seule — `groupes_de_cycles` prescrit littéralement de
    « mesurer un décodeur à la géométrie où il servira » (tâche 3). Mesuré sur
    `data/cvep_calib_last.npz` (lecture seule) : à k=1 les deux décodeurs sont à ÉGALITÉ EXACTE
    (43/90 chacun) ; à k=2 (la géométrie réelle), ils ne le sont plus.

    ⚠️ **Une séance INTERROMPUE (ESC pendant l'enregistrement, cf. `Abort` dans `calibrate()`) peut
    n'avoir vu qu'un SOUS-ENSEMBLE des cibles du plan.** `CVEPModel.hors_pli` ne juge alors que
    parmi les lags RÉELLEMENT VUS (son `uniq = sorted(set(lags))` rétrécit avec eux, et son hasard
    aussi) — mais un `RCCAModel` construit avec TOUS les codes du plan resterait jugé sur 1/6,
    quel que soit ce qui a été enregistré. Comparer les deux tels quels offre alors des points
    gratuits à celui jugé sur le plus petit jeu : MESURÉ sur `cvep_calib_last.npz` tronqué à 3
    cibles, eCCA 71,1 % (hasard 33,3 %) contre rCCA 51,1 % (hasard 16,7 %) — un « gagnant »
    entièrement fabriqué par l'écart de hasard, pas par le signal. On réduit donc les codes du
    rCCA aux SEULES cibles présentes dans `labels`, exactement comme `hors_pli` réduit `uniq` :
    les deux décodeurs jugent alors sur le MÊME nombre d'alternatives, quoi qu'il arrive à la
    séance.

    `epochs` : cycles BRUTS (n_cyc x n_voies enregistrées, ex. 8 pour l'Unicorn) — la réduction
    aux voies AJUSTÉES (`channels`, `CVEP_CHANNELS` par défaut) se fait ICI, la MÊME pour les deux
    décodeurs : sans ça, un montage différent d'un décodeur à l'autre biaiserait la comparaison
    (vérifié par un garde qui REFUSE plutôt que de comparer si jamais ça divergeait).
    `labels` : le LAG (frames) fixé à chaque époque, comme les stocke `calibrate()`.

    Chaque valeur du dict rendu porte :
      `modele`      — l'objet entraîné (CVEPModel ou RCCAModel), prêt pour `.save(...)` ;
      `justesse`    — accuracy HORS-PLI (jamais celle, optimiste, d'un modèle qui a vu l'essai
                      qu'il note — le piège qui a gonflé le premier écran de calibration MI) ;
      `n_epoques`   — le nombre d'époques RÉELLEMENT données à `.fit()` pour CE décodeur (lu sur
                      l'appel lui-même, `_fit_et_compte`) ; DOIT être `len(labels)` pour les deux,
                      sinon ils n'ont pas vu le même protocole ;
      `n_cycles`    — la GÉOMÉTRIE à laquelle `justesse` a été mesurée : le nombre de cycles
                      moyennés par décision. C'est de CE champ que l'appelant doit tirer la DURÉE
                      d'une décision pour calculer un ITR — jamais d'une constante recopiée à
                      côté. La constante `CVEP_DECISION_CYCLES` a déjà été migrée ici sans l'être
                      dans `calibrate()`, et l'ITR affiché à l'étudiant s'est retrouvé DOUBLÉ
                      (48 bits/min « PROMETTEUR » là où la séance de référence en vaut 24,
                      « FAIBLE ») sans qu'aucune des 47 assertions du fichier ne s'en aperçoive.
                      Justesse et durée sortent maintenant du même dict, donc de la même mesure ;
      `groupes`     — les groupes de validation croisée (`core.cvep_decoder.groupes_de_cycles`,
                      à la géométrie `n_cycles`) — LES MÊMES pour les deux, par construction ;
      `n_decisions` — le nombre de groupes RÉELLEMENT notés par ce décodeur (la longueur de ce
                      que SON `hors_pli` a rendu). Comparé à `len(groupes)` par l'appelant : s'il
                      diffère, ce décodeur a été noté à une AUTRE géométrie que celle annoncée
                      dans `groupes` — la comparaison ne serait plus honnête, silencieusement ;
      `n_cibles`    — le nombre d'alternatives RÉELLEMENT notées par ce décodeur (la largeur de
                      SA matrice de scores hors-pli, `sc.shape[1]`) : c'est CE nombre qui fixe le
                      hasard contre lequel lire `justesse`. DOIT être égal pour les deux, sinon
                      l'un a été jugé sur un jeu de cibles plus facile que l'autre (le Critical 1
                      de la revue de tâche 6). `None` si `n_decisions == 0` (rien à mesurer à
                      cette géométrie) — jamais une valeur d'apparence normale sur du vide (tour 2
                      de la revue) ;
      `corrects`    — tableau booléen, une valeur par DÉCISION, dans le MÊME ordre que l'autre
                      décodeur (les deux `hors_pli` parcourent `groupes_de_cycles` sur des
                      étiquettes en bijection — même frontières, donc même ordre de groupes,
                      quelle que soit l'encodage). C'est ce qui rend les décisions eCCA et rCCA
                      APPARIÉES, condition nécessaire pour un test de McNemar (`_gagnant`) — les
                      comparer comme deux échantillons INDÉPENDANTS serait le mauvais test.
                      `None` si `n_decisions == 0`.
    """
    plan, code = build_targets()
    codes = np.stack([np.asarray(c["code"], dtype=int) for c in plan])
    lag_a_idx = {c["lag"]: i for i, c in enumerate(plan)}

    labels = [int(l) for l in labels]
    # Les cibles RÉELLEMENT présentes dans cette séance — un sous-ensemble du plan complet si la
    # calibration a été interrompue. `RCCAModel` DOIT être construit sur CES codes-là (voir le
    # ⚠️ ci-dessus), pas sur les `CVEP_N_TARGETS` du plan complet.
    #
    # ⚠️ **Trié par POSITION DANS LE PLAN (`lag_a_idx`), surtout pas par valeur de lag.** Le
    # contrat d'appariement du rCCA est POSITIONNEL et il est écrit deux fois dans `core/` :
    # `cvep_rcca.RCCADecoder` (« `plan[i]` doit décrire la cible dont `model.codes[i]` est le
    # code : c'est le SEUL appariement qui existe entre un score et un nom de cible ») et
    # `cvep_models._codes_affiches` (« lignes comprises dans le même ORDRE »). Or `build_targets`
    # fait TOURNER l'affectation lag↔position quand `CVEP_LAG_ROTATION != 0` : `sorted(set(labels))`
    # et l'ordre du plan ne coïncident qu'à rotation nulle. Un `sorted()` nu — c'est ce qu'il y
    # avait ici — produisait donc, hors rotation zéro, un modèle rCCA dont les lignes sont une
    # PERMUTATION de celles du stimulus : `cvep_models.charger` le refuse (à juste titre : permuté,
    # il nommerait systématiquement la cible voisine), APRÈS que la calibration a annoncé
    # « modèles sauvegardés » et l'a peut-être nommé gagnant. Recalibrer reproduisait le même
    # fichier refusé — une impasse permanente, invisible parce que le seul cas testé était
    # rotation = 0.
    presentes = sorted(set(labels), key=lambda l: lag_a_idx[l])
    codes_vus = np.stack([codes[lag_a_idx[l]] for l in presentes])
    idx_local = {l: i for i, l in enumerate(presentes)}
    idx = [idx_local[l] for l in labels]     # RCCAModel indexe ses cibles 0..n-1, pas par lag

    ecca = CVEPModel(fs=fs, refresh=refresh, code_len=len(code), band=band, channels=channels)
    rcca = RCCAModel(codes_vus, fs=fs, refresh=refresh, band=band, channels=list(ecca.channels))

    # Réduits UNE fois, puis donnés aux DEUX décodeurs — c'est cette identité qui garantit
    # « les mêmes époques », pas une conviction qu'elles seront construites pareil deux fois.
    epochs_ecca = [np.asarray(e, dtype=float)[:, ecca.channels] for e in epochs]
    epochs_rcca = epochs_ecca
    for nom, mdl, ep in (("eCCA", ecca, epochs_ecca), ("rCCA", rcca, epochs_rcca)):
        largeur = int(np.asarray(ep[0]).shape[1]) if len(ep) else None
        if largeur != len(mdl.channels):
            raise ValueError(
                f"{nom} : {len(ep)} époques à {largeur} voies pour {len(mdl.channels)} voies "
                f"déclarées ({mdl.channels}) — la comparaison ne serait pas honnête")

    n_epoques_ecca = _fit_et_compte(ecca, epochs_ecca, labels)
    n_epoques_rcca = _fit_et_compte(rcca, epochs_rcca, idx, compute_cv=False)   # cv_ ci-dessous

    groupes = groupes_de_cycles(labels, n_cycles)
    sc_e, y_e, _ = ecca.hors_pli(epochs_ecca, labels, n_cycles=n_cycles)
    sc_r, y_r = rcca.hors_pli(epochs_rcca, idx, n_cycles=n_cycles)
    ecca.cv_ = float((sc_e.argmax(axis=1) == y_e).mean()) if len(y_e) else None
    rcca.cv_ = float((sc_r.argmax(axis=1) == y_r).mean()) if len(y_r) else None
    # ⚠️ `groupes_de_cycles` peut rendre AUCUN groupe à la géométrie `n_cycles` (une séance trop
    # courte, ou — mesuré au tour 1 de la revue — le protocole `--smoke` d'origine, dont les blocs
    # interrompaient systématiquement toute paire de cycles consécutifs). Au tour 1, `n_cibles`
    # retombait sur `len(presentes)` pour éviter un `IndexError` sur `.shape[1]` — mais un chiffre
    # qui a l'air d'une vraie mesure sur du VIDE est exactement le genre de panne muette que ce
    # dépôt existe pour éliminer (tour 2 de la revue) : `calibrate()` plantait un cran plus loin,
    # sur `cv_e*100` avec `cv_e is None`, parce que rien ne disait explicitement « il n'y a rien
    # à afficher ». `n_cibles` et `corrects` sont donc `None` quand `n_decisions == 0`, au même
    # titre que `justesse` — l'appelant DOIT fermer ce chemin avant tout calcul, pas le deviner.
    #
    # ⚠️ **Le test qui décide « rien à mesurer » DOIT être `len(sc) == 0` (le nombre de LIGNES),
    # jamais `sc.ndim`** — trouvé en écrivant le test du cas vide (tour 2) : sur un tableau vide,
    # `CVEPModel.hors_pli` rend `(0,)` (1 dimension, `np.asarray([])`) mais `RCCAModel.hors_pli`
    # rend `(0, n_targets)` (2 dimensions : `_hors_pli` PRÉ-ALLOUE `np.zeros((len(groupes),
    # n_targets))` avant sa boucle, donc la largeur survit même à zéro ligne). Un test sur `.ndim`
    # aurait donc laissé passer un `n_cibles` rCCA d'apparence normale — 6, le compte du plan —
    # sur un tableau qui ne contient VRAIMENT rien. `len(sc)` vaut 0 dans les deux cas, sans cette
    # divergence d'implémentation entre les deux jumeaux.
    #
    # ⚠️ **Cette divergence est TOUJOURS VRAIE aujourd'hui, pas un accident corrigé ailleurs** :
    # `cvep_decoder.py::CVEPModel.hors_pli` rend `(0,)`, `cvep_rcca.py::RCCAModel._hors_pli` rend
    # `(0, n_targets)`. **TRANCHÉ à la revue finale de branche : on ne les aligne PAS.** Le
    # contournement `len(sc) == 0` est correct pour les DEUX formes, il est documenté avec sa
    # preuve, et il est testé — aligner les deux toucherait deux fichiers de la tâche 3 déjà
    # validés pour ne supprimer qu'un commentaire. La règle qui en découle, et qui vaut pour tout
    # futur appelant : **c'est l'APPELANT qui ferme le chemin vide, avant tout calcul.** Le second
    # appelant, `core/cvep_rcca.py::_rejouer`, le fait maintenant lui aussi (il mourait sur trois
    # tracebacks différents pour cette seule et même cause).
    n_cibles_e = int(sc_e.shape[1]) if len(sc_e) > 0 else None
    n_cibles_r = int(sc_r.shape[1]) if len(sc_r) > 0 else None
    corrects_e = (sc_e.argmax(axis=1) == y_e) if len(sc_e) > 0 else None
    corrects_r = (sc_r.argmax(axis=1) == y_r) if len(sc_r) > 0 else None

    return {
        "eCCA": {"modele": ecca, "justesse": ecca.cv_, "n_epoques": n_epoques_ecca,
                 "n_cycles": int(n_cycles), "groupes": groupes, "n_decisions": len(sc_e),
                 "n_cibles": n_cibles_e, "corrects": corrects_e},
        "rCCA": {"modele": rcca, "justesse": rcca.cv_, "n_epoques": n_epoques_rcca,
                 "n_cycles": int(n_cycles), "groupes": groupes, "n_decisions": len(sc_r),
                 "n_cibles": n_cibles_r, "corrects": corrects_r},
    }


def _gagnant(res, seuil=SEUIL_MCNEMAR):
    """Le décodeur qui gagne, ou `None` si l'écart n'est PAS DÉFENDABLE — test de McNemar exact
    bilatéral (`_mcnemar_p`) sur les décisions APPARIÉES, PAS une comparaison de deux justesses
    comme si elles venaient d'échantillons indépendants. Pure, sans effet de bord.

    ⚠️ **Ne JAMAIS nommer de gagnant sur un écart qui n'est pas défendable.** C'est précisément
    parce que ce chantier n'a mesuré AUCUNE différence détectable entre les deux décodeurs sur la
    seule séance réelle disponible (k=1 : eCCA 43/90 contre rCCA 43/90, tâche 3 ; k=2, la
    géométrie du moteur : **eCCA 22/37 = 59,5 % contre rCCA 24/37 = 64,9 %**, McNemar p=0,73)
    qu'il rouvre le rCCA au lieu de le jeter — un « gagnant » affiché sur un écart de deux
    décisions dirait le contraire de ce que la mesure montre, à un étudiant qui n'a aucun moyen de
    le savoir.

    ⚠️ Écrire **`<décodeur> <valeur>`, jamais une valeur nue** : ce fichier nomme systématiquement
    eCCA en premier, et « 24/37 contre 22/37 » — deux fractions nues dans l'ordre INVERSE de cette
    convention — attribuait silencieusement le meilleur chiffre au mauvais décodeur, à trois lignes
    d'une fixture qui disait l'inverse.

    Rend un dict, jamais un simple nom : l'écran a besoin de la p-value et du nombre de décisions
    discordantes pour être honnête, pas seulement des deux pourcentages qui ne portent pas
    l'incertitude à eux seuls.
        `gagnant`        — "eCCA" | "rCCA" | None (indiscernables, ou rien à mesurer) ;
        `p`               — la p-value de McNemar, ou None si rien n'a pu être mesuré ;
        `b`, `c`          — décisions où SEUL eCCA (b) / SEUL rCCA (c) est correct ;
        `n_discordantes`  — `b + c` : c'est CE nombre qui porte l'information, pas les deux
                             pourcentages de justesse pris isolément (tour 2 de la revue).
    """
    corrects_e, corrects_r = res["eCCA"]["corrects"], res["rCCA"]["corrects"]
    if corrects_e is None or corrects_r is None:
        return {"gagnant": None, "p": None, "b": None, "c": None, "n_discordantes": None}
    b = int(np.sum(corrects_e & ~corrects_r))      # eCCA SEUL correct
    c = int(np.sum(~corrects_e & corrects_r))      # rCCA SEUL correct
    p = _mcnemar_p(b, c)
    gagnant = None
    if p < seuil and b != c:
        gagnant = "eCCA" if b > c else "rCCA"
    return {"gagnant": gagnant, "p": p, "b": b, "c": c, "n_discordantes": b + c}


def _draw(app, plan, spots, frame, target, done, total, b_idx, n_blocks):
    """Rendu d'une frame : toutes les cibles clignotent, celle à fixer est cerclée."""
    app.win.fill(BG)
    app.draw_ring(plan, spots, lambda c, f: is_on(f, c["code"]), frame, cue=target["name"])
    app.center(app.big, f"FIXE la cible {target['name']}", FG, 52)
    app.center(app.mid, f"bloc {b_idx}/{n_blocks}  —  cycle {done}/{total}",
               GO if done else WARN, 100)
    app.hud("ESC = annuler")
    app.pygame.display.flip()


def chemin_modele_horodate(decodeur, dossier=None):
    """`cvep_model_AAAAMMJJ-HHMMSS.npz` (eCCA) ou `cvep_rcca_model_AAAAMMJJ-HHMMSS.npz` (rCCA) —
    un fichier NEUF, jamais un écrasement.

    ⚠️ **`calibrate()` écrivait par défaut dans `CVEP_MODEL_PATH` / `CVEP_RCCA_MODEL_PATH`, des
    noms FIXES : la calibration suivante EFFAÇAIT donc la précédente.** `data/cvep_rcca_model.npz`
    est la trace du 2026-07-21 (35,6 %, codes Gold) que ce chantier cite comme preuve du jeu égal
    eCCA/rCCA (`core/cvep_rcca.py`) — et une revue a mesuré qu'une exécution de smoke mal câblée
    suffisait à l'écraser (incident documenté dans le rapport de tâche 6). Le P300 et l'ErrP
    avaient déjà cette parade (`research.p300_calibrate.chemin_modele_horodate`,
    `research.errp_calibrate.chemin_modele_horodate`) ; le c-VEP ne l'avait pas reprise.

    `core.cvep_models.MOTIFS` liste déjà les fichiers `cvep_model*.npz` / `cvep_rcca_model*.npz`
    du plus récent au plus ancien : le moteur, la console et les applis pygame prennent donc
    automatiquement le dernier calibré, sans rien à changer côté lecture.
    """
    if decodeur not in ("eCCA", "rCCA"):
        raise ValueError(f"décodeur inconnu : {decodeur!r} (attendu 'eCCA' ou 'rCCA')")
    dossier = os.path.dirname(CVEP_MODEL_PATH) if dossier is None else dossier
    prefixe = "cvep_model" if decodeur == "eCCA" else "cvep_rcca_model"
    return os.path.join(dossier, f"{prefixe}_{time.strftime('%Y%m%d-%H%M%S')}.npz")


def calibrate(app, cycles=CVEP_CAL_CYCLES, save_path=None, rcca_save_path=None):
    """Enregistre, entraîne les DEUX décodeurs (eCCA et rCCA, `entraine_les_deux`), sauvegarde
    les deux modèles, affiche les deux justesses et NOMME le gagnant. Retourne (ok, res|None) où
    `res` est le dict rendu par `entraine_les_deux`.

    `save_path=None` / `rcca_save_path=None` -> des fichiers HORODATÉS, jamais `CVEP_MODEL_PATH` /
    `CVEP_RCCA_MODEL_PATH` : voir `chemin_modele_horodate`.
    """
    save_path = save_path or chemin_modele_horodate("eCCA")
    rcca_save_path = rcca_save_path or chemin_modele_horodate("rCCA")
    plan, code = build_targets()
    L = len(code)
    spots = app.ring_spots(plan)
    acq = app.acq
    model = CVEPModel(fs=acq.fs, refresh=app.refresh, code_len=L)
    # On ENREGISTRE les 8 voies (rien n'est perdu, on pourra chercher le meilleur sous-ensemble
    # hors ligne) mais on n'AJUSTE que sur `model.channels` — donner 8 voies à une CCA calibrée
    # sur peu de cycles surapprend.
    rows = acq.eeg_rows
    epoch_s = model.n_cyc / acq.fs
    if app.smoke:
        # ⚠️ PAS `cycles = 2` : avec `CVEP_CAL_BLOCKS = 3` blocs, `_make_blocks` aurait alors donné
        # à CHAQUE bloc UN SEUL cycle (`per = max(1, 2 // 3) = 1`), jamais deux CONSÉCUTIFS — donc
        # `groupes_de_cycles(labels, k=2)`, la géométrie de DÉCISION DU MOTEUR (tâche 6), ne
        # trouvait de paire que si le mélange des blocs en plaçait deux du MÊME bloc côte à côte
        # par CHANCE. Mesuré : 3 échecs sur 5 lancements (`IndexError`, un tableau de scores VIDE
        # n'a qu'UNE dimension). `cycles = 6` fait que CHAQUE bloc porte 2 cycles consécutifs
        # (`per = max(1, 6 // 3) = 2`), donc au moins une paire par bloc, quel que soit le mélange.
        cycles = 6

    blocks = _make_blocks(plan, cycles, CVEP_CAL_BLOCKS)
    gap = cvep_lag_gap_ms(len(plan), L, app.refresh)
    n_blk = len(blocks)
    est = (len(plan) * cycles + n_blk * SETTLE_CYCLES) * L / app.refresh / 60.0 + n_blk * 1.8 / 60.0
    print(f"[cvep-cal] code L={L} @ {app.refresh:.0f}Hz -> cycle {L/app.refresh:.2f}s "
          f"({model.n_cyc} éch.)  8 voies enregistrées, ajustement sur {model.channels}")
    print(f"[cvep-cal] {len(plan)} cibles, écart entre lags {gap:.0f} ms"
          + ("" if gap >= 150 else "  ⚠️ < durée VEP ~150 ms : cibles voisines confusables"))
    print(f"[cvep-cal] {cycles} cycles/cible, {n_blk} blocs entrelacés (ordre mélangé) "
          f" ≈ {est:.1f} min")
    if not _briefing(app):
        return False, None
    # liaison casque vérifiée AVANT d'investir les `est` minutes annoncées juste au-dessus (≈ 2,7
    # aux réglages du dépôt) ; voies clés (occipitales) encadrées
    if not app.signal_check(highlight=CVEP_CHANNELS, mode_label="c-VEP"):
        return False, None

    epochs, lags = [], []
    check_at = max(1, int(round(n_blk * 0.4)))   # bloc où se déclenche le contrôle de séance
    got_by_lag = {c["lag"]: 0 for c in plan}
    frame, prev_phase = 0, -1
    settle = 0 if app.smoke else SETTLE_CYCLES
    try:
        for b_idx, (target, n_cyc) in enumerate(blocks, start=1):
            # Surveillance en cours de séance : une liaison qui lâche au bloc 3 produirait
            # sinon 3 minutes de signal plat, puis un modèle à 0 % sans le moindre indice.
            if not app.smoke:
                _, qrows, _ = app.signal_ok(0.5)
                dead = [n for n, _, v in qrows if v == "morte"]
                if dead:
                    print(f"[cvep-cal] ⛔ LIAISON PERDUE (voies plates : {', '.join(dead)}) "
                          f"au bloc {b_idx}/{len(blocks)} — arrêt, rien n'est entraîné.")
                    print("[cvep-cal] vérifie le câble du casque, les électrodes et les mastoïdes.")
                    app.flash("Liaison casque perdue",
                              f"voies plates : {', '.join(dead)} — vérifie le câble", 4.0)
                    return False, None
            got, skip, start = 0, settle, frame
            while got < n_cyc:
                app.drain()
                phase = frame % L
                # frontière de cycle : la fenêtre qui précède couvre un cycle entier depuis la phase 0
                if phase == 0 and prev_phase != 0:
                    if skip > 0:
                        skip -= 1
                    else:
                        ep = acq.get_epoch(epoch_s, rows=rows, filtered=False)
                        if ep is not None and len(ep) >= model.n_cyc:
                            epochs.append(ep[:model.n_cyc])
                            lags.append(target["lag"])
                            got += 1
                            got_by_lag[target["lag"]] += 1
                prev_phase = phase
                _draw(app, plan, spots, frame, target, got, n_cyc, b_idx, len(blocks))
                app.clock.tick(int(app.refresh) + 5)
                frame += 1
                # garde-fou headless : borne le temps passé par bloc sans fausser le compte
                if app.smoke and (frame - start) > (n_cyc + settle + 2) * L:
                    break
            print(f"[cvep-cal] bloc {b_idx}/{len(blocks)} {target['name']:<10} "
                  f"lag={target['lag']:>3} : {got} cycles", flush=True)
            # Garde-fou de séance : une fois seulement, à ~40 % du parcours (assez d'époques
            # pour que le LOO ait un sens, assez tôt pour que l'abandon fasse gagner du temps).
            if b_idx == check_at and not app.smoke:
                verdict = _early_check(model, epochs, lags, len(plan))
                if verdict is not None:
                    bad, acc, hi_itr = verdict
                    # ⚠️ « à 1 cycle » n'est pas décoratif : ce contrôle mesure et convertit à la
                    # géométrie d'UNE époque, alors que le chiffre final de la calibration est à
                    # `CVEP_DECISION_CYCLES`. Les deux ITR ne sont donc PAS sur la même échelle,
                    # et le plancher `EARLY_ITR_MIN` s'applique à celle-ci. Le dire ici, parce que
                    # c'est là que les deux chiffres se croisent sous les yeux de l'étudiant.
                    print(f"[cvep-cal] contrôle à mi-parcours ({len(epochs)} cycles, à 1 cycle "
                          f"par décision — PAS la géométrie du chiffre final) : "
                          f"LOO {acc*100:.0f}% (hasard {100.0/len(plan):.0f}%)  ->  au MIEUX "
                          f"{hi_itr:.1f} bits/min"
                          + (f"  ⚠️ SOUS LE PLANCHER D'UTILITÉ ({EARLY_ITR_MIN:.0f})" if bad
                             else "  -> on continue"), flush=True)
                    if bad:
                        app.flash("Séance mal engagée",
                                  f"au mieux {hi_itr:.0f} bits/min — ESC pour arrêter "
                                  f"(le déjà-enregistré est conservé)", 6.0)
            if b_idx < len(blocks):
                # inter-bloc = point de PAUSE sûr (époques du bloc déjà ramassées, le settle du
                # bloc suivant absorbe le redémarrage) -> ESPACE met en pause pendant cet écran
                app.flash("Change de cible",
                          f"prépare-toi à fixer {blocks[b_idx][0]['name']}   ·   Espace = pause",
                          1.8, skippable=False, pausable=True)
    except Abort:
        print("[cvep-cal] interrompu — entraînement sur ce qui est déjà enregistré.")
    print("[cvep-cal] cycles par cible : "
          + "  ".join(f"{c['name']}={got_by_lag[c['lag']]}" for c in plan))

    if len(set(lags)) < 2 or len(epochs) < 4:
        print("[cvep-cal] pas assez de données pour entraîner.")
        return False, None

    # Les DEUX décodeurs, sur les MÊMES époques : « lequel est meilleur pour CETTE personne ? »
    # ne se répond que si la calibration entraîne les deux (cf. la docstring d'entraine_les_deux et
    # celle de core/cvep_rcca.py — mesuré une fois, aucune différence DÉTECTABLE entre les deux,
    # McNemar p=0,73 sur 37 décisions ; ce qui n'est pas « ils se valent »).
    res = entraine_les_deux(epochs, lags, fs=acq.fs, refresh=app.refresh)
    ecca, rcca = res["eCCA"]["modele"], res["rCCA"]["modele"]
    n_cibles_vues = len(set(lags))
    # ⚠️ **`n_targets` = ce que la séance a RÉELLEMENT présenté, jamais `len(plan)`.** Le template
    # eCCA est COMMUN à tous les lags : un modèle entraîné sur 3 cibles « marche » techniquement à
    # 6 et publie six corrélations d'apparence normale, dont trois sortent de lags qu'aucun cerveau
    # n'a jamais vus. C'est exactement la panne invisible que `CVEPRuntime._desaccord_code` refuse
    # (« ce modèle a été calibré sur N cible(s), le stimulus actuel en affiche M ») — mais ce refus
    # ne peut mordre que si le fichier dit la VÉRITÉ sur lui-même. Écrire `len(plan)` ici rendait le
    # contrôle du moteur inopérant sur le seul cas qu'il vise, et l'asymétrie s'était creusée : le
    # rCCA d'une séance tronquée n'est plus écrit du tout, l'eCCA l'était en se déclarant complet.
    ecca.save(save_path, n_targets=n_cibles_vues)
    # ⚠️ **Une séance INTERROMPUE ne produit PAS de fichier rCCA, et le dire.** Le modèle rCCA
    # d'une séance à 3 cibles sur 6 porte 3 codes ; `core.cvep_models.charger` exige les codes du
    # stimulus AFFICHÉ (les 6, dans l'ordre du plan) et le refuse — donc le fichier n'apparaîtrait
    # jamais dans la liste de la console ni dans `modeles_disponibles`. Le sauvegarder quand même
    # annonçait « modèles sauvegardés : … (rCCA) » à l'étudiant, et pouvait même le nommer
    # gagnant : un succès affiché pour un artefact que rien ne peut charger. La COMPARAISON,
    # elle, reste valable (les deux décodeurs jugent parmi les mêmes cibles) et s'affiche.
    if n_cibles_vues == len(plan):
        rcca.save(rcca_save_path)
        ligne_sauvegarde = (f"modèles sauvegardés : {save_path} (eCCA)  ·  "
                            f"{rcca_save_path} (rCCA)")
    else:
        ligne_sauvegarde = (
            f"séance interrompue ({n_cibles_vues} cibles sur {len(plan)}) : modèle eCCA "
            f"sauvegardé ({save_path}) mais DÉCLARÉ à {n_cibles_vues} cibles — le moteur le "
            f"REFUSERA tant que le stimulus en affiche {len(plan)}, et il dira pourquoi. Modèle "
            f"rCCA NON sauvegardé : il porterait {n_cibles_vues} codes quand le stimulus en "
            f"affiche {len(plan)}, et `core.cvep_models.charger` le refuserait. La comparaison "
            f"ci-dessous reste valable ; recalibre en entier pour obtenir des modèles utilisables.")
    if not app.smoke:
        # ⚠️ ARCHIVER, ne jamais écraser : dans un projet d'exploration les jeux de données SONT
        # le résultat. Une version antérieure n'écrivait que « cvep_calib_last.npz » et la
        # meilleure séance (27,1 bits/min) a été perdue à la calibration suivante — impossible
        # de comparer les amplitudes pour diagnostiquer l'effondrement.
        data = dict(epochs=np.asarray(epochs), lags=np.asarray(lags), fs=acq.fs,
                    refresh=app.refresh, n_targets=len(plan), rotation=CVEP_LAG_ROTATION,
                    channels=np.asarray(model.channels, dtype=int),   # voies AJUSTÉES
                    ch_names=np.asarray(CH_NAMES),                    # les 8 ENREGISTRÉES
                    sigma=float(np.asarray(epochs).std()))
        folder = os.path.dirname(save_path)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        archive = os.path.join(
            folder, f"cvep_calib_{stamp}_n{len(plan)}_rot{CVEP_LAG_ROTATION}.npz")
        np.savez(archive, **data)
        np.savez(os.path.join(folder, "cvep_calib_last.npz"), **data)   # raccourci d'analyse
        print(f"[cvep-cal] données archivées : {os.path.basename(archive)}")

    # ⚠️ À la géométrie de DÉCISION DU MOTEUR (CVEP_DECISION_CYCLES cycles), une séance trop
    # courte ou trop fragmentée peut ne fournir AUCUNE décision : `entraine_les_deux` le dit
    # explicitement (`justesse`/`n_cibles`/`corrects` à `None`), plutôt que de rendre un chiffre
    # d'apparence normale sur du vide. Fermer ce chemin ICI, avant tout calcul : c'est le
    # `TypeError` (`cv_e*100` sur un `None`) que le tour 2 de la revue a trouvé un cran plus loin.
    cv_e, cv_r = res["eCCA"]["justesse"], res["rCCA"]["justesse"]
    n_cibles = res["eCCA"]["n_cibles"]      # == res["rCCA"]["n_cibles"], garanti par construction
    if cv_e is None or cv_r is None or not n_cibles:
        print(f"[cvep-cal] {len(epochs)} cycles enregistrés, mais AUCUNE décision à la géométrie "
              f"du moteur ({CVEP_DECISION_CYCLES} cycles) — trop peu de cycles consécutifs de la "
              f"même cible pour en former une seule. Les modèles sont sauvegardés (le filtre "
              f"spatial et le classifieur existent), mais aucune justesse fiable ne les "
              f"accompagne : recalibre, avec davantage de cycles par cible si possible.")
        print(f"[cvep-cal] {ligne_sauvegarde}")
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < (0.1 if app.smoke else 5.0):
            try:
                app.drain(on_key=lambda e: None)
            except Abort:
                break
            app.win.fill(BG)
            h = app.win.get_height()
            app.center(app.big, "Pas assez de décisions", WARN, int(h * 0.40))
            app.center(app.mid, f"{len(epochs)} cycles enregistrés, aucune paire consécutive à "
                       f"la géométrie du moteur", DIM, int(h * 0.50))
            app.center(app.small, "modèles sauvegardés, mais sans justesse fiable — recalibre",
                       DIM, int(h * 0.58))
            app.pygame.display.flip()
            app.clock.tick(60)
        return False, res

    # Avec N cibles variable, l'accuracy brute n'est plus comparable d'une config à l'autre
    # (70% sur 6 cibles vaut bien plus que 70% sur 3). On rapporte donc l'ITR, l'échelle qui
    # combine nombre de choix, justesse et vitesse — cf. itr.py. Un ITR par décodeur : ils n'ont
    # aucune raison de dégrader à la même vitesse.
    # ⚠️ `n_cibles` (ce que les DEUX décodeurs ont RÉELLEMENT jugé), jamais `len(plan)` : sur une
    # séance INTERROMPUE (Critical 1), les deux ne jugent plus que parmi un sous-ensemble, et un
    # hasard/ITR calculés à `len(plan)` restaient gonflés dans exactement ce cas-là (réserve du
    # tour 2 de la revue) — un « DÉPASSE LE SSVEP » qui ne mesure pas ce qu'il prétend mesurer.
    # ⚠️ **La DURÉE d'une décision se lit sur le MÊME dict que la justesse, jamais sur une
    # constante recopiée à côté.** `cycle_s = L / app.refresh` (UN cycle) est resté ici quand
    # `entraine_les_deux` a migré sa mesure à `CVEP_DECISION_CYCLES` : les justesses venaient de
    # k=2 et la durée de k=1, donc l'ITR affiché était EXACTEMENT DOUBLÉ. Sur la séance de
    # référence (6 cibles, eCCA 59,5 %, rCCA 64,9 %), l'écran annonçait « 48 bits/min —
    # PROMETTEUR » là où la mesure vaut 24 et où le README annonce 22 — et le verdict basculait
    # d'un cran complet (seuil `ref/2` = 25,0). Aucune des 47 assertions du fichier ne s'en
    # apercevait : aucune ne lisait une valeur d'ITR. Faire dériver la durée de `res` supprime la
    # classe entière — changer `n_cycles` déplace maintenant les deux chiffres ensemble.
    from research.itr import itr as _itr
    chance = 100.0 / n_cibles
    k_decision = res["eCCA"]["n_cycles"]      # la géométrie où cv_e/cv_r ont ÉTÉ MESURÉES
    decision_s = k_decision * L / app.refresh
    bits_e = _itr(n_cibles, cv_e, decision_s)
    bits_r = _itr(n_cibles, cv_r, decision_s)
    meilleur = max(bits_e, bits_r)
    ref = _itr(3, 0.95, 1.5)   # SSVEP actuel = la barre à battre
    # ⚠️ McNemar, PAS une comparaison de deux pourcentages : voir `_gagnant`, tour 2 de la revue.
    # « indiscernables » est la réponse honnête ET la réponse attendue — c'est précisément parce
    # que les deux décodeurs se valent que ce chantier a rouvert le rCCA (cf. core/cvep_rcca.py).
    mn = _gagnant(res)
    verdict = ("DÉPASSE LE SSVEP" if meilleur >= ref else
               "PROMETTEUR" if meilleur >= ref / 2 else
               "FAIBLE (contact électrodes ? regard qui décroche ? refais un essai)")
    print(f"[cvep-cal] {len(epochs)} cycles sur {n_cibles} cibles jugées (hasard {chance:.0f}%), "
          f"décision = {k_decision} cycle(s) ({decision_s:.2f}s) :")
    print(f"[cvep-cal]   eCCA  leave-one-out {cv_e*100:5.1f}%  -> {bits_e:5.1f} bits/min")
    print(f"[cvep-cal]   rCCA  leave-one-out {cv_r*100:5.1f}%  -> {bits_r:5.1f} bits/min")
    ligne_gagnant = (f"indiscernables sur cette séance (McNemar p={mn['p']:.3f})" if mn["gagnant"]
                     is None else f"gagnant : {mn['gagnant']} (McNemar p={mn['p']:.3f})")
    print(f"[cvep-cal] {ligne_gagnant} — {mn['n_discordantes']} décisions discordantes sur "
          f"{res['eCCA']['n_decisions']} (eCCA seul {mn['b']}, rCCA seul {mn['c']})")
    print(f"[cvep-cal]   —   SSVEP de référence {ref:.1f} -> {verdict}")
    print(f"[cvep-cal] `python src/research/cvep_analyze.py` pour le gain en moyennant plusieurs cycles.")
    print(f"[cvep-cal] {ligne_sauvegarde}")

    t0 = time.perf_counter()
    while time.perf_counter() - t0 < (0.1 if app.smoke else 5.0):
        try:
            app.drain(on_key=lambda e: None)
        except Abort:
            break
        app.win.fill(BG)
        h = app.win.get_height()
        app.center(app.big, f"eCCA {cv_e*100:.0f}%   ·   rCCA {cv_r*100:.0f}%", FG, int(h * 0.28))
        app.center(app.mid, ligne_gagnant, DIM if mn["gagnant"] is None else GO, int(h * 0.38))
        app.center(app.small, f"{mn['n_discordantes']} décisions discordantes sur "
                   f"{res['eCCA']['n_decisions']}  ({mn['b']} eCCA seul, {mn['c']} rCCA seul)",
                   DIM, int(h * 0.46))
        app.center(app.mid, f"{meilleur:.0f} bits/min (meilleur des deux, décision "
                   f"{k_decision} cycles)   —   SSVEP réf. {ref:.0f}",
                   GO if meilleur >= ref / 2 else WARN, int(h * 0.56))
        app.center(app.small, verdict, DIM, int(h * 0.65))
        app.center(app.small,
                   "modèles sauvegardés (eCCA et rCCA) — ESC pour continuer"
                   if n_cibles_vues == len(plan) else
                   f"séance interrompue : eCCA sauvegardé, rCCA NON ({n_cibles_vues}/{len(plan)} "
                   f"cibles) — ESC pour continuer",
                   DIM, int(h * 0.73))
        app.pygame.display.flip()
        app.clock.tick(60)
    return meilleur >= ref / 2, res


# --- Autotest (aucun casque, c-VEP synthétique) ------------------------------

def _selftest():
    """La comparaison honnête eCCA/rCCA (tâche 6) : mêmes époques, mêmes groupes de validation
    croisée, un gagnant nommé — et les deux chiffres survivent à un aller-retour sur disque.
    Aucun casque, aucune donnée réelle."""
    import shutil
    import tempfile

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    from core.cvep_decoder import synth_cvep

    # 8 voies BRUTES (comme l'Unicorn), réduites à 4 AJUSTÉES (comme CVEP_CHANNELS) : la
    # distinction compte pour le garde de largeur de voies (Important 6 de la revue) — un
    # fixture qui générerait directement des époques à 4 voies ne pourrait jamais faire diverger
    # « brut » et « réduit », et le garde resterait invérifiable.
    fs, refresh, n_raw, voies = 250.0, 60.0, 8, [4, 5, 6, 7]
    rng = np.random.default_rng(0)
    plan, code = build_targets()
    epochs, labels = [], []
    for c in plan:
        for _ in range(8):
            epochs.append(synth_cvep(code, c["lag"], n_raw, fs, refresh, -6.0, rng))
            labels.append(c["lag"])

    # --- LE test de cette tâche : la comparaison est honnête. ---------------------------------
    # Les deux décodeurs s'ajustent sur les MÊMES époques, en validation croisée groupée. Comparer
    # deux protocoles différents ne dirait rien ; c'est tout l'intérêt d'avoir gardé le stimulus
    # identique (cf. `core/cvep_rcca.py`, docstring du module).
    res = entraine_les_deux(epochs, labels, fs=fs, refresh=refresh, channels=voies)
    chk(set(res) == {"eCCA", "rCCA"}, f"les deux décodeurs sont entraînés ({sorted(res)})")
    chk(res["eCCA"]["n_epoques"] == res["rCCA"]["n_epoques"] == len(labels),
        f"...sur le MÊME nombre d'époques — sinon la comparaison ne veut rien dire "
        f"({res['eCCA']['n_epoques']}, {res['rCCA']['n_epoques']}, {len(labels)})")
    chk(res["eCCA"]["groupes"] == res["rCCA"]["groupes"],
        f"...et les mêmes groupes de validation croisée ({len(res['eCCA']['groupes'])} vs "
        f"{len(res['rCCA']['groupes'])} groupes)")
    # ⚠️ Ce contrôle est ce qui empêche « groupes » d'être décoratif : il compare ce que CHAQUE
    # décodeur a RÉELLEMENT noté (la longueur de son propre `hors_pli`) au nombre de groupes
    # annoncé. Si un futur appel passait un `n_cycles` différent à un seul des deux `hors_pli`
    # (l'asymétrie déjà trouvée ailleurs dans ce chantier, cf. `RCCADecoder.n_cycles`), ce
    # décodeur noterait un nombre de groupes différent de celui annoncé — silencieusement, sans
    # ce contrôle. Preuve par mutation dans le rapport de tâche.
    chk(res["eCCA"]["n_decisions"] == res["rCCA"]["n_decisions"] == len(res["eCCA"]["groupes"]),
        f"...et chaque décodeur a RÉELLEMENT noté autant de groupes qu'annoncé — sinon deux "
        f"géométries différentes se compareraient sans qu'aucun message ne le dise "
        f"({res['eCCA']['n_decisions']}, {res['rCCA']['n_decisions']}, "
        f"{len(res['eCCA']['groupes'])})")
    chk(res["eCCA"]["n_cibles"] == res["rCCA"]["n_cibles"] == len(plan),
        f"...et les deux décodeurs jugent parmi le MÊME nombre d'alternatives — ici les "
        f"{len(plan)} du plan complet ({res['eCCA']['n_cibles']}, {res['rCCA']['n_cibles']})")
    chk(0.0 <= res["eCCA"]["justesse"] <= 1.0 and 0.0 <= res["rCCA"]["justesse"] <= 1.0,
        f"...et chacun rend une justesse HORS-PLI, dans [0, 1] ({res['eCCA']['justesse']}, "
        f"{res['rCCA']['justesse']})")
    chk(res["eCCA"]["modele"].decoder == "eCCA" and res["rCCA"]["modele"].decoder == "rCCA",
        "...et chaque modèle SAIT quel décodeur il est (le champ que `save` écrit)")

    # --- Important 4 (revue) : la géométrie de MESURE est celle où le moteur DÉCIDE. ----------
    import inspect
    defaut_k = inspect.signature(entraine_les_deux).parameters["n_cycles"].default
    chk(defaut_k == CVEP_DECISION_CYCLES,
        f"la comparaison mesure par défaut à la géométrie de DÉCISION DU MOTEUR "
        f"(CVEP_DECISION_CYCLES={CVEP_DECISION_CYCLES}), pas à celle d'une époque de calibration "
        f"seule où k=1 masquerait un écart réel entre les deux décodeurs ({defaut_k})")

    # --- Critical 2 (revue) : la calibration du menu n'écrit plus JAMAIS le nom FIXE par défaut.
    # Vérifié sur le TEXTE SOURCE et pas en l'exécutant : appeler `calibrate(app)` sans chemin
    # pour voir où il écrit, c'est exactement l'accident qu'on veut interdire (celui qui a détruit
    # le modèle Gold du 21 juillet lors d'un smoke mal câblé — cf. le rapport de tâche 6).
    src_cal = inspect.getsource(calibrate)
    chk('chemin_modele_horodate("eCCA")' in src_cal and 'chemin_modele_horodate("rCCA")' in src_cal
        and "save_path=CVEP_MODEL_PATH" not in src_cal
        and "rcca_save_path=CVEP_RCCA_MODEL_PATH" not in src_cal,
        "calibrate() retombe sur des chemins HORODATÉS quand on ne lui en donne pas — jamais sur "
        "CVEP_MODEL_PATH / CVEP_RCCA_MODEL_PATH en dur dans sa signature")
    chemin_e_h = chemin_modele_horodate("eCCA")
    chemin_r_h = chemin_modele_horodate("rCCA")
    chk(chemin_e_h != CVEP_MODEL_PATH and chemin_r_h != CVEP_RCCA_MODEL_PATH,
        f"...et ces chemins horodatés ne sont VRAIMENT jamais les noms fixes ({chemin_e_h}, "
        f"{chemin_r_h})")
    import fnmatch

    from core.cvep_models import MOTIFS
    chk(fnmatch.fnmatch(os.path.basename(chemin_e_h), MOTIFS[0])
        and fnmatch.fnmatch(os.path.basename(chemin_r_h), MOTIFS[1])
        and not fnmatch.fnmatch(os.path.basename(chemin_r_h), MOTIFS[0]),
        f"...et ils restent VUS par cvep_models (motifs {MOTIFS}), chacun sous SON motif "
        f"({os.path.basename(chemin_e_h)}, {os.path.basename(chemin_r_h)})")
    chk(os.path.dirname(chemin_modele_horodate("eCCA", dossier="/tmp/xyz_cvep_test")) ==
        "/tmp/xyz_cvep_test",
        "...et un `dossier` explicite est respecté, pas toujours celui de CVEP_MODEL_PATH — "
        "c'est ce détour qu'un test ou un smoke doit prendre pour ne jamais écrire dans data/")

    # --- Critical 1 (revue) : une séance INTERROMPUE ne doit PAS fausser le hasard. -----------
    # Tronquée à 3 cibles sur 6 (le cas d'un ESC en cours d'enregistrement, cf. `Abort` dans
    # `calibrate()`) : SANS restreindre les codes du rCCA aux cibles VUES, il resterait jugé sur
    # 1/6 (hasard 16,7 %) quand eCCA rétrécit correctement à 1/3 (33,3 %) — c'est EXACTEMENT ce
    # qui a produit « gagnant : eCCA » sur des points offerts par le hasard, pas par le signal
    # (mesuré par la revue sur une séance réelle tronquée : 71,1 % contre 51,1 %).
    trois = plan[:3]
    epochs3, labels3 = [], []
    for c in trois:
        for _ in range(8):
            epochs3.append(synth_cvep(code, c["lag"], n_raw, fs, refresh, -6.0, rng))
            labels3.append(c["lag"])
    res3 = entraine_les_deux(epochs3, labels3, fs=fs, refresh=refresh, channels=voies)
    chk(res3["eCCA"]["n_cibles"] == res3["rCCA"]["n_cibles"] == 3,
        f"une séance tronquée à 3 cibles sur 6 juge les DEUX décodeurs parmi 3 alternatives, "
        f"jamais 6 pour l'un et 3 pour l'autre ({res3['eCCA']['n_cibles']}, "
        f"{res3['rCCA']['n_cibles']})")
    chk(res3["rCCA"]["modele"].n_targets == 3,
        f"...et le modèle rCCA entraîné porte VRAIMENT 3 codes, pas les 6 du plan complet "
        f"({res3['rCCA']['modele'].n_targets})")
    # ⚠️ Cette propriété est juste POUR LA COMPARAISON et fatale POUR UN FICHIER : un modèle rCCA
    # à 3 codes est refusé par `core.cvep_models.charger`, qui exige les 6 codes du stimulus
    # affiché. `calibrate()` ne le sauvegarde donc PAS (vérifié plus bas, tour 3) — la phrase
    # « modèle rCCA sauvegardé » ici serait un contresens.
    from core.cvep_models import charger as _charger_c2
    _tmp_c2 = tempfile.mkdtemp(prefix="cvep_calibrate_c2_tronq_")
    try:
        _ch_c2 = res3["rCCA"]["modele"].save(os.path.join(_tmp_c2, "cvep_rcca_model.npz"))
        _m_c2, _pb_c2 = _charger_c2(_ch_c2)
        chk(_m_c2 is None and _pb_c2 is not None,
            f"...et un tel fichier serait REFUSÉ au chargement — d'où le refus de l'écrire "
            f"({_pb_c2})")
    finally:
        shutil.rmtree(_tmp_c2, ignore_errors=True)

    # --- Le gagnant nommé, PAR MCNEMAR — pas par une comparaison de deux pourcentages. ---------
    # ⚠️ Tour 2 de la revue : `_gagnant` comparait deux justesses comme si elles venaient de deux
    # échantillons INDÉPENDANTS, et nommait un gagnant sur un écart qui n'avait rien de défendable
    # (eCCA 59,5 % contre rCCA 64,9 % sur la vraie séance — McNemar p=0,73, DU BRUIT). Les
    # fixtures portent des décisions APPARIÉES (mêmes essais, corrects ou non pour chaque
    # décodeur), la seule forme que `_gagnant` accepte maintenant.
    def _corrects_fabrique(n_concordants, b, c, n_faux=0):
        """(corrects_e, corrects_r) : `n_concordants` décisions où les deux sont D'ACCORD ET
        CORRECTS, `b` où SEUL eCCA est correct, `c` où SEUL rCCA l'est, `n_faux` où les deux se
        trompent ENSEMBLE.

        ⚠️ `n_faux` n'est pas décoratif : sans lui, une fixture ne pouvait porter QUE des
        concordances correctes, donc ses justesses réelles (32/37 et 34/37) contredisaient les
        pourcentages qu'elle annonçait dans son propre commentaire (59,5 % et 64,9 %) et les
        `justesse` passées dans le même dict. `_gagnant` n'utilise que `corrects`, donc
        l'assertion restait juste — mais le test le plus lu du fichier mentait sur ses chiffres,
        et le prochain lecteur l'aurait cru."""
        e = np.array([True] * n_concordants + [True] * b + [False] * c + [False] * n_faux,
                     dtype=bool)
        r = np.array([True] * n_concordants + [False] * b + [True] * c + [False] * n_faux,
                     dtype=bool)
        return e, r

    e_fort, r_faible = _corrects_fabrique(0, 15, 0)      # eCCA correct partout, rCCA nulle part
    mn_fort = _gagnant({"eCCA": {"justesse": 1.0, "corrects": e_fort},
                        "rCCA": {"justesse": 0.0, "corrects": r_faible}})
    chk(mn_fort["gagnant"] == "eCCA" and mn_fort["p"] < 0.001,
        f"un écart DÉFENDABLE (15 décisions discordantes, toutes en faveur d'eCCA) nomme eCCA "
        f"gagnant ({mn_fort})")
    mn_inverse = _gagnant({"eCCA": {"justesse": 0.0, "corrects": r_faible},
                           "rCCA": {"justesse": 1.0, "corrects": e_fort}})
    chk(mn_inverse["gagnant"] == "rCCA", f"...dans les deux sens ({mn_inverse})")

    # Le cas RÉEL, celui qui a motivé ce tour de revue : 37 décisions, 3 discordances pour eCCA
    # seul, 5 pour rCCA seul (mesuré sur data/cvep_calib_last.npz à k=2, lecture seule), soit
    # eCCA 22/37 = 59,5 % contre rCCA 24/37 = 64,9 % — un écart qui A L'AIR réel — et pourtant
    # McNemar p=0,7265625 : DU BRUIT. La vraie séance demande 19 concordances CORRECTES et 10
    # concordances FAUSSES : c'est la seule combinaison qui reproduit les deux pourcentages.
    e_reel, r_reel = _corrects_fabrique(19, 3, 5, n_faux=10)
    chk(len(e_reel) == len(r_reel) == 37 and int(e_reel.sum()) == 22 and int(r_reel.sum()) == 24,
        f"la fixture « cas réel » reproduit VRAIMENT les chiffres qu'elle annonce : 37 décisions, "
        f"eCCA {int(e_reel.sum())}/37 = {e_reel.mean()*100:.1f} %, rCCA {int(r_reel.sum())}/37 = "
        f"{r_reel.mean()*100:.1f} % — une fixture qui ment sur ses propres chiffres est crue par "
        f"le lecteur suivant")
    mn_reel = _gagnant({"eCCA": {"justesse": float(e_reel.mean()), "corrects": e_reel},
                        "rCCA": {"justesse": float(r_reel.mean()), "corrects": r_reel}})
    chk(mn_reel["gagnant"] is None and abs(mn_reel["p"] - 0.7265625) < 1e-9,
        f"...et un écart de POURCENTAGE réel (eCCA 59,5 % contre rCCA 64,9 %) mais NON DÉFENDABLE "
        f"(McNemar p=0,73, le cas mesuré sur la vraie séance) ne nomme PERSONNE — c'est le défaut "
        f"central trouvé au tour 2 de la revue ({mn_reel})")
    chk(mn_reel["n_discordantes"] == 8 and mn_reel["b"] == 3 and mn_reel["c"] == 5,
        f"...et le nombre de décisions DISCORDANTES est juste — c'est LUI qui porte "
        f"l'information, pas les deux pourcentages pris isolément ({mn_reel})")

    # Rien à mesurer (séance sans aucune décision à cette géométrie) -> rien à nommer, sans lever.
    mn_vide = _gagnant({"eCCA": {"justesse": None, "corrects": None},
                        "rCCA": {"justesse": None, "corrects": None}})
    chk(mn_vide["gagnant"] is None and mn_vide["p"] is None,
        f"...et l'absence de mesure ne nomme personne non plus, sans lever ({mn_vide})")

    # --- Important 4bis (revue, tour 2) : _mcnemar_p reproduit EXACTEMENT le calcul indépendant
    # du relecteur (b=3, c=5 -> p=0,727), et ce n'est pas un hasard de fixture : c'est le test
    # binomial exact bilatéral standard (identique à scipy.stats.binomtest / R binom.test).
    chk(abs(_mcnemar_p(3, 5) - 0.7265625) < 1e-9 and abs(_mcnemar_p(5, 3) - 0.7265625) < 1e-9,
        f"_mcnemar_p(3, 5) = _mcnemar_p(5, 3) = 0,7265625 ({_mcnemar_p(3, 5)}, {_mcnemar_p(5, 3)})")
    chk(_mcnemar_p(0, 0) == 1.0, "aucune décision discordante -> p=1 (rien ne distingue les deux)")
    chk(_mcnemar_p(10, 10) == 1.0, "un partage parfait -> p=1 aussi (symétrie totale)")
    # ...et c'est LE MÊME objet que celui de `--seuils`, pas une seconde copie. `_mcnemar_p` est né
    # ici puis a DÉMÉNAGÉ dans `core/` (`core/cvep_rcca.py::_rejouer` en a besoin, et `core/`
    # n'importe jamais `research/`). Deux implémentations du même test, chacune avec ses propres
    # tests, finissent par diverger sans que rien ne le dise — c'est exactement ce que la règle du
    # déménagement existe pour empêcher. Vérifiable seulement de CE côté de la frontière.
    import core.cvep_rcca as _core_rcca
    chk(_mcnemar_p is _core_rcca._mcnemar_p and SEUIL_MCNEMAR == _core_rcca.SEUIL_MCNEMAR,
        "l'écran de calibration et `--seuils` appellent LE MÊME `_mcnemar_p`, au même seuil — une "
        "seule implémentation du test dans le dépôt")

    # --- La casse trouvée au tour 2 : ZÉRO décision à la géométrie de mesure. -------------------
    # Aucune paire de cycles consécutifs de la même cible : chaque cible n'apparaît qu'UNE fois,
    # dans un ordre qui alterne systématiquement (jamais deux d'affilée). `groupes_de_cycles`
    # rend alors [] à k=2, et `hors_pli` un tableau de scores VIDE. Le tour 1 évitait le crash en
    # laissant `n_cibles` retomber sur `len(presentes)` — un chiffre D'APPARENCE NORMALE sur du
    # VIDE — et `calibrate()` plantait un cran plus loin (`cv_e*100` avec `cv_e is None`, un
    # `TypeError`, DANS LE CHEMIN DE PRODUCTION). `n_cibles` et `corrects` doivent dire eux-mêmes
    # qu'il n'y a rien, pour que l'appelant ferme le chemin AVANT tout calcul.
    epochs_alt, labels_alt = [], []
    for _ in range(2):                          # 2 tours, chaque cible vue 1 fois par tour
        for c in plan:
            epochs_alt.append(synth_cvep(code, c["lag"], n_raw, fs, refresh, -6.0, rng))
            labels_alt.append(c["lag"])
    from core.cvep_decoder import groupes_de_cycles as _gdc
    chk(_gdc(labels_alt, CVEP_DECISION_CYCLES) == [],
        f"fixture : AUCUNE paire de cycles consécutifs de la même cible à k="
        f"{CVEP_DECISION_CYCLES} ({_gdc(labels_alt, CVEP_DECISION_CYCLES)})")
    res_vide = entraine_les_deux(epochs_alt, labels_alt, fs=fs, refresh=refresh, channels=voies)
    for nom in ("eCCA", "rCCA"):
        r = res_vide[nom]
        chk(r["n_decisions"] == 0, f"{nom} : zéro décision à cette géométrie ({r['n_decisions']})")
        chk(r["justesse"] is None, f"{nom} : ...donc AUCUNE justesse ({r['justesse']})")
        chk(r["n_cibles"] is None,
            f"{nom} : ...et `n_cibles` le dit AUSSI, plutôt qu'un chiffre d'apparence normale "
            f"sur du vide — c'est ce qui manquait au tour 1 ({r['n_cibles']})")
        chk(r["corrects"] is None, f"{nom} : ...et `corrects`, pour la même raison ({r['corrects']})")

    # --- Important 6 (revue) : « les mêmes époques » n'était vérifié que par un compte tautologique.
    # `_fit_et_compte` est le mécanisme qui rend `n_epoques` non-décoratif : il DOIT compter
    # l'ARGUMENT réellement passé à `.fit()`, jamais une longueur recalculée à côté (qui, elle,
    # ne verrait PAS un futur tronquage inline comme `epochs[:-6]`).
    class _ModeleFactice:
        def __init__(self):
            self.vu = None

        def fit(self, epochs, labels, **kw):
            self.vu = (list(epochs), list(labels), kw)

    mf = _ModeleFactice()
    n_a = _fit_et_compte(mf, [1, 2, 3], ["a", "b", "c"], compute_cv=False)
    chk(n_a == 3 and mf.vu == ([1, 2, 3], ["a", "b", "c"], {"compute_cv": False}),
        f"_fit_et_compte ajuste EXACTEMENT ce qu'on lui donne, mots-clés compris ({n_a}, {mf.vu})")
    n_b = _fit_et_compte(mf, [1, 2, 3], ["a", "b"])
    chk(n_b == 3,
        f"...et il compte les ÉPOQUES qu'il a reçues, pas les étiquettes — sinon un tronquage "
        f"appliqué à un seul des deux côtés (epochs OU labels) pourrait passer inaperçu ({n_b})")

    # --- Les deux chiffres ET le champ `decoder` partent dans le fichier de modèle. ------------
    from core.cvep_models import charger
    from core.cvep_rcca import RCCADecoder

    tmp = tempfile.mkdtemp(prefix="cvep_calibrate_selftest_")
    try:
        chemin_e = res["eCCA"]["modele"].save(os.path.join(tmp, "cvep_model.npz"),
                                              n_targets=len(plan))
        chemin_r = res["rCCA"]["modele"].save(os.path.join(tmp, "cvep_rcca_model.npz"))
        relu_e, pb_e = charger(chemin_e)
        relu_r, pb_r = charger(chemin_r)
        chk(relu_e is not None and pb_e is None and relu_e.decoder == "eCCA"
            and abs(relu_e.cv_ - res["eCCA"]["justesse"]) < 1e-12,
            f"le modèle eCCA sauvegardé se relit, décodeur et justesse compris ({pb_e})")
        chk(relu_r is not None and pb_r is None and relu_r.decoder == "rCCA"
            and abs(relu_r.cv_ - res["rCCA"]["justesse"]) < 1e-12,
            f"...et le modèle rCCA aussi ({pb_r})")

        # --- Critical 3 (revue) : l'appariement lag -> ligne de code n'était vérifié par RIEN. -
        # La JUSTESSE seule ne suffit pas : un décalage SYSTÉMATIQUE (chaque époque appariée à
        # la cible VOISINE) reste interne cohérent — le classifieur apprend « code[i+1] pour la
        # réponse à la cible i » et `hors_pli` le note avec le MÊME décalage, donc juste EN
        # AVEUGLE (mesuré par la revue : +1 % len(plan) -> justesse 1,0/1,0, VERDICT OK). Seul un
        # contrôle EXTERNE — quelle cible le modèle sauvegardé désigne-t-il RÉELLEMENT ? — le voit.
        cible_connue = 4
        # DÉJÀ réduite aux voies AJUSTÉES (comme le fait `_cvep_decode` en ligne, avant d'appeler
        # `classify` : `dec.model.channels` sélectionne, `RCCAModel.scores` ne réduit rien lui-même).
        fenetre_connue = synth_cvep(code, plan[cible_connue]["lag"], len(voies), fs, refresh,
                                    -6.0, rng)
        dec = RCCADecoder(relu_r, plan, corr_min=-1e9, margin=0.0, n_cycles=1)
        choisi, _ = dec.classify(fenetre_connue, 0)
        chk(choisi is not None and choisi["name"] == plan[cible_connue]["name"],
            f"le modèle rCCA sauvegardé-puis-relu désigne la cible RÉELLEMENT affichée, pas sa "
            f"voisine ({None if choisi is None else choisi['name']} au lieu de "
            f"{plan[cible_connue]['name']}) — un décalage systématique de l'appariement lag -> "
            f"ligne de code resterait invisible à la seule justesse hors-pli")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- Revue finale, Critical 2 : LE MÊME contrôle À ROTATION NON NULLE. ---------------------
    # Le contrôle ci-dessus tourne à `CVEP_LAG_ROTATION = 0` — le SEUL point où « trié par valeur
    # de lag » et « ordre du plan » coïncident. C'est cette coïncidence qui a rendu invisible le
    # défaut créé par le correctif Critical 1 : `codes_vus` empilé par lag croissant, quand le
    # rCCA et `cvep_models._codes_affiches` apparient PAR POSITION dans le plan. Hors rotation
    # zéro, les lignes du modèle sont donc une PERMUTATION de celles du stimulus, `charger` refuse
    # tout modèle fraîchement calibré, et recalibrer reproduit le même fichier refusé.
    # `config.py` dit explicitement que ce paramètre « reste disponible » : ce cas doit être testé.
    import core.cvep_code as _cc
    _rot_reelle = _cc.CVEP_LAG_ROTATION
    _cc.CVEP_LAG_ROTATION = 2
    try:
        plan_rot, code_rot = build_targets()
        lags_rot = [c["lag"] for c in plan_rot]
        chk(lags_rot != sorted(lags_rot),
            f"fixture : à CVEP_LAG_ROTATION = 2, l'ordre du plan n'est VRAIMENT plus l'ordre des "
            f"valeurs de lag — les deux tris divergent ({lags_rot})")
        epochs_rot, labels_rot = [], []
        for c in plan_rot:
            for _ in range(8):
                epochs_rot.append(synth_cvep(code_rot, c["lag"], n_raw, fs, refresh, -6.0, rng))
                labels_rot.append(c["lag"])
        res_rot = entraine_les_deux(epochs_rot, labels_rot, fs=fs, refresh=refresh, channels=voies)
        codes_plan_rot = np.stack([np.asarray(c["code"], dtype=int) for c in plan_rot])
        chk(np.array_equal(res_rot["rCCA"]["modele"].codes, codes_plan_rot),
            "le modèle rCCA calibré à rotation 2 porte les codes du plan DANS L'ORDRE DU PLAN, "
            "pas triés par valeur de lag — c'est l'ordre, et lui seul, qui apparie un score à un "
            "nom de cible")
        tmp_rot = tempfile.mkdtemp(prefix="cvep_calibrate_rot_")
        try:
            chemin_rot = res_rot["rCCA"]["modele"].save(
                os.path.join(tmp_rot, "cvep_rcca_model.npz"))
            relu_rot, pb_rot = charger(chemin_rot)
            chk(relu_rot is not None and pb_rot is None,
                f"...donc `cvep_models.charger` l'ACCEPTE — un modèle qu'on vient de calibrer "
                f"sans rien avoir changé ne doit pas être refusé ({pb_rot})")
            if relu_rot is not None:
                cible_rot = 4
                fenetre_rot = synth_cvep(code_rot, plan_rot[cible_rot]["lag"], len(voies),
                                         fs, refresh, -6.0, rng)
                choisi_rot, _ = RCCADecoder(relu_rot, plan_rot, corr_min=-1e9, margin=0.0,
                                            n_cycles=1).classify(fenetre_rot, 0)
                chk(choisi_rot is not None
                    and choisi_rot["name"] == plan_rot[cible_rot]["name"],
                    f"...et il désigne la cible RÉELLEMENT AFFICHÉE, pas sa voisine "
                    f"({None if choisi_rot is None else choisi_rot['name']} au lieu de "
                    f"{plan_rot[cible_rot]['name']})")
        finally:
            shutil.rmtree(tmp_rot, ignore_errors=True)
    finally:
        _cc.CVEP_LAG_ROTATION = _rot_reelle
    chk(_cc.CVEP_LAG_ROTATION == _rot_reelle,
        f"...et la rotation réelle est restaurée, même si le bloc ci-dessus avait levé "
        f"({_cc.CVEP_LAG_ROTATION})")

    # --- Tour 3 de la revue : PROTÉGER calibrate() lui-même, pas seulement ce qui l'alimente. ----
    # Mesuré par le re-relecteur : muter `n_cibles` en `len(plan)` (réserve C1) OU désactiver le
    # garde à zéro décision (la casse TypeError du tour 2) laissait CE FICHIER **et** `app.py
    # --smoke` VERTS TOUS LES DEUX — aucun test n'exerçait `calibrate()` lui-même sur une séance
    # TRONQUÉE ni sur une séance SANS AUCUNE paire de cycles consécutifs ; seule la donnée en amont
    # (`entraine_les_deux`) était protégée. On exerce donc le VRAI `calibrate()`, via une VRAIE
    # `App(smoke=True)`, en détournant `_make_blocks` (la fabrique de blocs d'enregistrement) pour
    # forcer les deux scénarios qu'un smoke normal n'atteint jamais.
    import contextlib
    import io
    import re as _re

    from research.itr import itr as _itr_ref
    from research.ui import App

    _ce_module = sys.modules[__name__]
    _make_blocks_original = _ce_module._make_blocks

    @contextlib.contextmanager
    def _blocs_detournes(fabrique):
        """Remplace `_make_blocks` par `fabrique` le temps du bloc, la restaure après — y compris
        si `calibrate()` lève, pour qu'un test qui rougit ne laisse rien de patché derrière lui."""
        _ce_module._make_blocks = fabrique
        try:
            yield
        finally:
            _ce_module._make_blocks = _make_blocks_original

    app_int = App(smoke=True)
    try:
        # --- Réserve C1 : le hasard et l'ITR affichés DOIVENT suivre n_cibles, pas len(plan). ---
        tmp1 = tempfile.mkdtemp(prefix="cvep_calibrate_c1_selftest_")
        try:
            with _blocs_detournes(lambda p, c, n: _make_blocks_original(p[:3], c, n)):
                capture = io.StringIO()
                with contextlib.redirect_stdout(capture):
                    ok1, res1 = calibrate(app_int, save_path=os.path.join(tmp1, "e.npz"),
                                          rcca_save_path=os.path.join(tmp1, "r.npz"))
            sortie1 = capture.getvalue()
            fichiers1 = set(os.listdir(tmp1))
            # Relu par le chemin RÉEL du moteur (`CVEPModel.load`), pas depuis l'objet en mémoire :
            # c'est le FICHIER qui voyage jusqu'au moteur, et c'est lui qui doit dire la vérité.
            ecca1 = CVEPModel.load(os.path.join(tmp1, "e.npz"))
        finally:
            shutil.rmtree(tmp1, ignore_errors=True)
        chk(res1["eCCA"]["n_cibles"] == 3,
            f"calibrate() sur une séance tronquée à 3 cibles sur 6 en juge bien 3 "
            f"({res1['eCCA']['n_cibles']})")
        m_hasard = _re.search(r"hasard (\d+)%", sortie1)
        chk(m_hasard is not None and m_hasard.group(1) == "33",
            f"...et le HASARD IMPRIMÉ par calibrate() suit n_cibles=3 (33 %), jamais len(plan)=6 "
            f"(17 %) — sinon l'ITR et le verdict affichés à l'étudiant resteraient gonflés sur "
            f"EXACTEMENT la séance que Critical 1 visait "
            f"({m_hasard.group(0) if m_hasard else sortie1!r})")
        # --- Revue finale, Critical 2 (b) : la séance tronquée n'écrit PAS de fichier rCCA. -----
        # Il porterait 3 codes pour un stimulus qui en affiche 6 : `cvep_models.charger` le
        # refuse (vérifié plus haut sur `res3`), donc il n'apparaîtrait jamais dans la liste de la
        # console. L'écrire quand même, en annonçant « modèles sauvegardés : … (rCCA) », donne un
        # succès pour un artefact que rien ne peut charger — et le gagnant nommé peut être lui.
        chk("e.npz" in fichiers1 and "r.npz" not in fichiers1,
            f"une séance tronquée sauvegarde l'eCCA et PAS le rCCA ({sorted(fichiers1)})")
        chk("rCCA NON sauvegardé" in sortie1 and "séance interrompue" in sortie1,
            f"...et calibrate() le DIT, au lieu d'annoncer « modèles sauvegardés » pour les deux "
            f"({[l for l in sortie1.splitlines() if 'sauvegard' in l]})")
        # --- Revue finale, E-I3 : le fichier eCCA DÉCLARE ce que la séance a présenté. ----------
        # ⚠️ Le template eCCA est commun à tous les lags : un modèle à 3 cibles « marche » à 6 et
        # publie six corrélations d'apparence normale, dont trois issues de lags jamais montrés.
        # `CVEPRuntime._desaccord_code` refuse précisément ce cas — mais seulement si le fichier
        # ne ment pas sur lui-même. Avec `n_targets=len(plan)`, la calibration rendait ce refus
        # INOPÉRANT sur la seule séance qu'il vise, et l'asymétrie s'était creusée : le rCCA d'une
        # séance tronquée n'est plus écrit du tout, l'eCCA l'était en se déclarant complet.
        chk(ecca1.n_targets == 3,
            f"le modèle eCCA d'une séance tronquée se déclare à 3 cibles — celles qu'il a "
            f"réellement vues —, jamais aux {len(build_targets()[0])} du plan : c'est ce champ, et "
            f"lui seul, qui permet au moteur de le refuser ({ecca1.n_targets})")
        chk("REFUSERA" in sortie1,
            f"...et calibrate() prévient que le moteur le refusera tant que le stimulus affichera "
            f"plus de cibles, au lieu d'annoncer une sauvegarde sans réserve "
            f"({[l for l in sortie1.splitlines() if 'sauvegard' in l]})")

        # --- Revue finale, Critical 1 : l'ITR IMPRIMÉ est calculé à la géométrie où la justesse
        # a été MESURÉE. `cycle_s = L / app.refresh` (un cycle) est resté ici quand la mesure est
        # passée à `CVEP_DECISION_CYCLES` : l'ITR affiché était EXACTEMENT DOUBLÉ, et le verdict
        # basculait d'un cran (« PROMETTEUR » au lieu de « FAIBLE » sur la séance de référence).
        # Aucune des 47 assertions du fichier ne lisait une valeur d'ITR — celle-ci le fait, sur
        # la sortie du VRAI `calibrate()`, et elle ne dépend pas de la justesse obtenue (qui, sur
        # un board de test, peut tomber sous le hasard et rendre tous les ITR nuls).
        L_test = len(build_targets()[1])
        m_geo = _re.search(r"décision = (\d+) cycle\(s\) \(([\d.]+)s\)", sortie1)
        chk(m_geo is not None and int(m_geo.group(1)) == res1["eCCA"]["n_cycles"]
            and abs(float(m_geo.group(2))
                    - res1["eCCA"]["n_cycles"] * L_test / app_int.refresh) < 0.01,
            f"la DURÉE de décision imprimée est celle où la justesse a été mesurée "
            f"({res1['eCCA']['n_cycles']} cycles = "
            f"{res1['eCCA']['n_cycles'] * L_test / app_int.refresh:.2f}s), pas un cycle "
            f"({L_test / app_int.refresh:.2f}s) — le facteur 2 exact "
            f"({m_geo.group(0) if m_geo else sortie1!r})")
        # ...et l'ITR imprimé se relit à partir de la DURÉE IMPRIMÉE, pas d'une autre : les deux
        # chiffres de la même ligne doivent décrire le même décodeur. (Cette assertion-ci ne
        # suffit pas à elle seule — sur un board de test, la justesse peut tomber sous le hasard
        # et les deux géométries rendent alors 0,0 bits/min : c'est l'assertion sur la DURÉE
        # ci-dessus qui porte la preuve.)
        m_bits = _re.search(r"eCCA\s+leave-one-out\s+([\d.]+)%\s+->\s+([\d.]+) bits/min", sortie1)
        chk(m_bits is not None and m_geo is not None and abs(
            float(m_bits.group(2))
            - _itr_ref(res1["eCCA"]["n_cibles"], res1["eCCA"]["justesse"],
                       float(m_geo.group(2)))) < 0.05,
            f"...et l'ITR imprimé est bien celui de la durée IMPRIMÉE à côté de lui "
            f"({m_bits.group(0) if m_bits else sortie1!r})")
        # ...et la géométrie annoncée n'est pas une constante recopiée : elle sort du dict que
        # `entraine_les_deux` rend, donc de la mesure elle-même.
        chk(res1["eCCA"]["n_cycles"] == res1["rCCA"]["n_cycles"] == CVEP_DECISION_CYCLES,
            f"la géométrie rendue par entraine_les_deux est celle du moteur "
            f"({res1['eCCA']['n_cycles']}, {res1['rCCA']['n_cycles']}, {CVEP_DECISION_CYCLES})")
        # Le chiffre CONCRET, sur la séance de référence que le dépôt documente partout (6 cibles,
        # eCCA 22/37 = 59,5 %, rCCA 24/37 = 64,9 %, code L=63 à 60 Hz) : c'est le chiffre-vedette
        # du chantier, et c'est lui qui était doublé. ⚠️ C'est CETTE assertion qui fait autorité
        # sur les 19,1 / 23,8 bits/min que README.md et docs/SPEC.md annoncent désormais — ils
        # citent la mesure d'ici, plus un « ~22 » sans provenance.
        ref_ssvep = _itr_ref(3, 0.95, 1.5)
        bits_ref_e = _itr_ref(6, 22 / 37, CVEP_DECISION_CYCLES * 63 / 60.0)
        bits_ref_r = _itr_ref(6, 24 / 37, CVEP_DECISION_CYCLES * 63 / 60.0)
        chk(abs(bits_ref_e - 19.1) < 0.1 and abs(bits_ref_r - 23.8) < 0.1
            and max(bits_ref_e, bits_ref_r) < ref_ssvep / 2,
            f"séance de RÉFÉRENCE : eCCA {bits_ref_e:.1f} et rCCA {bits_ref_r:.1f} bits/min à "
            f"{CVEP_DECISION_CYCLES} cycles — EXACTEMENT les 19,1 et 23,8 que la doc annonce, et "
            f"SOUS la moitié du SSVEP ({ref_ssvep/2:.1f}) donc verdict « FAIBLE »")
        chk(abs(_itr_ref(6, 24 / 37, 63 / 60.0) - 2 * bits_ref_r) < 1e-9
            and _itr_ref(6, 24 / 37, 63 / 60.0) >= ref_ssvep / 2,
            f"...et le calcul à UN cycle rendait exactement le DOUBLE "
            f"({_itr_ref(6, 24/37, 63/60.0):.1f}), donc « PROMETTEUR » : un cran de verdict "
            f"complet, sur un chiffre faux d'un facteur 2 exact")

        # --- La casse TypeError (tour 2) : calibrate() ne doit PAS planter à zéro décision. -----
        tmp2 = tempfile.mkdtemp(prefix="cvep_calibrate_td_selftest_")
        try:
            with _blocs_detournes(lambda p, c, n: [(cible, 1) for _ in range(2) for cible in p]):
                ok2, res2 = calibrate(app_int, save_path=os.path.join(tmp2, "e.npz"),
                                      rcca_save_path=os.path.join(tmp2, "r.npz"))
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)
        # Arriver ici EST une partie de la preuve : un `TypeError` (celui du tour 2, `chance =
        # 100.0 / n_cibles` avec `n_cibles=None`) aurait fait sortir `_selftest()` en exception
        # avant cette ligne, sans que `chk` n'ait la main pour le dire proprement.
        chk(ok2 is False,
            f"calibrate() sur une séance SANS AUCUNE paire de cycles consécutifs rend "
            f"(False, ...), jamais un TypeError ({ok2})")
        chk(res2["eCCA"]["justesse"] is None and res2["eCCA"]["n_cibles"] is None,
            f"...et le résultat dit bien qu'il n'y a rien à mesurer, ce qui est CE QUI PERMET à "
            f"calibrate() de fermer le chemin AVANT tout calcul ({res2['eCCA']['justesse']}, "
            f"{res2['eCCA']['n_cibles']})")
    finally:
        app_int.close()

    print(f"[cvep-calibrate] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    sys.exit(0 if _selftest() else 1)
