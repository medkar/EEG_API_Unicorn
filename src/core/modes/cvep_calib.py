"""La calibration c-VEP : la fenêtre tient l'HORLOGE, le MOTEUR entraîne.

Troisième et DERNIÈRE sous-classe concrète de `MarkerCalibrationRuntime`
(`core/modes/marker_calib.py`, à lire avant celui-ci), après `p300_calib.py` et `errp_calib.py`.

⚠️⚠️ **CE MODE EST L'EXCEPTION DU CHANTIER, et c'est la chose à comprendre avant tout le reste.**
Chez le P300 et l'ErrP, l'invariant tenu par le socle est « la calibration prélève son époque par le
MÊME appel que le décodage » : `epoch_from_stream`, avec les `pre_s`/`post_s` LUS sur le runtime de
décodage. Ici il n'y a **aucun événement à découper** — les marqueurs `cycle` ne délimitent rien,
ils tiennent une horloge (cf. la docstring de `core/modes/cvep.py`) — et `CVEPRuntime` n'expose
délibérément NI `pre_s` NI `post_s`.

Le code commun entre l'entraînement et le décodage est donc ailleurs, et c'est **`phase_a`** : la
reconstruction de la position du code à un instant donné, depuis le dernier marqueur reçu. Ce
fichier l'**APPELLE**, il ne la réimplémente pas — littéralement :

    def phase_a(self, t_fin):
        return self.runtime_cls_du_mode.phase_a(self, t_fin)

C'est la méthode du DÉCODAGE, appelée sur cet objet-ci. Elle n'a besoin, sur son `self`, que de
trois choses que cette classe porte comme `CVEPRuntime` les porte : `code_len`, `_ref_ts` et
`_ref_refresh`. Une recopie de sa formule (`int(age * refresh + eps) % code_len`) donnerait les
mêmes nombres aujourd'hui et dériverait au premier changement — la tolérance `_EPS_FRAME` a déjà
coûté une frame entière à ce projet, et une frame entière suffit à faire échouer un décodage sans
lever la moindre exception. `python src/core/modes/cvep_calib.py` compare les DEUX reconstructions
par les VALEURS, sur une course qui inclut une frame sautée.

⚠️ **La géométrie de l'époque est donc REDÉCLARÉE ici, et c'est le seul endroit du chantier où
c'est le cas.** Une époque de calibration c-VEP est **un cycle entier du code**, pris JUSTE AVANT
le marqueur qui annonce le redémarrage — `pre_s = code_len / refresh`, `post_s = 0`. Ce n'est pas
une constante : `refresh` est celui que l'ÉMETTEUR déclare dans ses marqueurs, et le moteur ne le
connaît qu'après en avoir reçu un. C'est la même longueur que `CVEPModel.n_cyc`, celle que
`CVEPModel.fit` attend, et celle que `CVEPRuntime._fenetre` replie en ligne.

⚠️ **Ce que ce fichier NE teste PAS : l'alignement à l'échantillon près.** Comme chez ses deux
aînés, son autotest juge un décodage, donc il tolère ce qu'un décodage tolère. Ce qu'il teste, lui,
c'est l'accord des deux reconstructions de PHASE — le seul chemin partagé qui existe ici.

⚠️ **`CVEPRuntime` est importé TARDIVEMENT, dans la propriété**, exactement comme chez le P300 et
l'ErrP et pour la même raison mesurée : `core/modes/cvep.py` importe ce module-ci (son `Calib`
porte `runtime_cls=CVEPCalibration`), donc un import en tête refermerait un CYCLE. Un cycle
module-à-module survit tant que chacun est importé par son nom de paquet — mais pas quand l'un des
deux fichiers est lancé DIRECTEMENT (`python src/core/modes/cvep.py`, l'un des autotests de la
recette) : Python le charge alors sous le nom `__main__`, la garde de `sys.modules` ne joue plus, et
le second exemplaire demande un nom pas encore défini.

⚠️ **DEUX décodeurs, DEUX fichiers, et AUCUN gagnant nommé à la légère.** Le c-VEP est le seul mode
du produit à avoir deux décodeurs sur le même stimulus (eCCA et rCCA). La calibration les entraîne
sur les MÊMES époques et les compare par un **McNemar exact** sur des décisions APPARIÉES —
« indiscernables » est la réponse attendue, et c'est celle que la seule séance réelle donne
(p = 0,727 sur 8 décisions discordantes / 37). Ce dépôt a déjà relayé « rCCA gagne, 64,9 contre
59,5 » comme un résultat avant de mesurer ; le verdict rend donc le TEST, jamais l'écart seul.

Autotest :
    python src/core/modes/cvep_calib.py
"""

import os as _os
import sys as _sys
import time as _time

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
import numpy as np  # noqa: E402

from core.config import (CALIB_CANDIDAT_PREFIXE, CH_NAMES, CVEP_BAND,  # noqa: E402
                         CVEP_BITS, CVEP_CAL_BLOCKS, CVEP_CAL_CYCLES,
                         CVEP_CAL_SETTLE_CYCLES, CVEP_CHANNELS, CVEP_DECISION_CYCLES,
                         CVEP_LAG_ROTATION, CVEP_MODEL_PATH, CVEP_N_TARGETS, FS_UNICORN,
                         use_utf8_console)
from core.cvep_code import build_targets  # noqa: E402
from core.cvep_decoder import CVEPModel, groupes_de_cycles  # noqa: E402
from core.cvep_rcca import SEUIL_MCNEMAR, RCCAModel, _mcnemar_p  # noqa: E402
from core.modes.marker_calib import MarkerCalibrationRuntime  # noqa: E402
# ⚠️ `core.modes.cvep` n'est PAS importé ici : cf. le ⚠️ de la docstring du module. Il l'est dans
# `CVEPCalibration.runtime_cls_du_mode`, une fois le programme lancé.

# Le rafraîchissement de RÉFÉRENCE, et il ne sert qu'à DEUX choses : estimer la durée annoncée du
# protocole, et donner une longueur d'époque plausible AVANT le premier marqueur. Le vrai
# rafraîchissement vient de l'émetteur, marqueur par marqueur — `core` ne voit aucun écran.
REFRESH_REFERENCE_HZ = 60.0

# La longueur du code, en frames. Lue une fois ici pour les constantes de classe ; les instances,
# elles, la relisent sur `build_targets()` (cf. `CVEPCalibration.__init__`).
_CODE_LEN = 2 ** CVEP_BITS - 1

# Ce que l'étudiant lit AVANT de commencer, sur la page de la console. Le protocole lui-même
# s'affiche dans la fenêtre de stimulus : ce qui est ici est ce qu'il faut avoir compris avant.
BRIEFING = (
    "Les cibles clignotent toutes selon le MÊME code pseudo-aléatoire, décalé pour chacune.",
    "Ça « grésille » : c'est normal, c'est le stimulus.",
    "Une cible est CERCLÉE en vert : fixe-la, sans bouger les yeux, jusqu'au changement.",
    "PLANTE le regard sur le disque — ici le regard compte (contrairement au Motor Imagery).",
    "Cligne le moins possible et reste immobile pendant l'enregistrement.",
    "Le cercle change de cible régulièrement ; les premières secondes après chaque changement",
    "sont jetées, le temps que ton regard trouve la nouvelle cible.",
)

# La phrase d'honnêteté du c-VEP — PROPRE à ce mode, et elle dit QUATRE choses (docs/recette.md
# §2.9). Celle du P300 parle de sélection parmi six cibles et d'AUC, celle de l'ErrP d'un détecteur
# binaire, celle du MI de trois classes : les recopier ici serait faux à chaque fois.
HONNETETE = (
    "À SIX cibles, le hasard est à 16,7 % — jamais 50 %. Le repère du projet est de 59,5 % (eCCA) "
    "et 64,9 % (rCCA) sur la séance de référence, et ces deux chiffres sont HORS LIGNE : ils "
    "viennent d'une validation croisée sur les époques d'une calibration, pas d'un décodage en "
    "direct, encore moins à travers le réseau. ⚠️ Et ce n'est PAS le chiffre que tu relèveras en "
    "séance : le moteur ajoute deux seuils et un vote glissant, donc il se tait souvent. Ce qu'il "
    "produit, mesuré à k = 2 et aux seuils 0,26 / 0,09, est un COUPLE — environ 46 % d'émission "
    "et 71 % de justesse PARMI les verdicts émis. Comparer ton relevé au 59,5 / 64,9 % fabrique "
    "un verdict faux dans les deux sens. Enfin : le c-VEP n'a JAMAIS été décodé au casque par le "
    "moteur, donc attends-toi à moins, pas à plus."
)

# Les verdicts portent sur la justesse HORS-PLI du meilleur des deux décodeurs, à la géométrie où
# le moteur décide (`CVEP_DECISION_CYCLES` cycles). Le hasard est à 1/N cibles, pas à 50 %.
VERDICTS = ((0.55, "AU NIVEAU DU REPÈRE DU PROJET (59,5 / 64,9 % sur la séance de référence)"),
            (0.33, "UTILISABLE"),
            (0.00, "FAIBLE — ré-essaie : saline Pz/PO7/Oz/PO8, et PLANTE le regard sur le disque "
                   "cerclé sans le promener (ici le regard compte, contrairement au Motor "
                   "Imagery)"))

# Les planchers en dessous desquels on REFUSE d'entraîner, plutôt que de produire un modèle que
# rien ne distingue d'un bon dans la liste de la console.
# ⚠️ `MIN_CIBLES = 2` n'est pas « deux cibles suffisent » : c'est le point sous lequel il n'y a
# plus de choix à faire, donc plus rien à mesurer (`CVEPModel._loo` rend None sous deux lags, et
# `hors_pli` noterait un classement à une seule alternative). Une séance à deux cibles passera,
# avec des chiffres très bruités : c'est le rôle du verdict de le dire, pas celui du refus.
MIN_EPOQUES = 8
MIN_CIBLES = 2

# Paliers auxquels un marqueur refusé se DIT. Même motif que `p300_calib._PALIERS_REFUS` : une
# ligne par ordre de grandeur. À ~1 marqueur/s, le dire à chaque fois noierait le terminal ; une
# seule fois par séance laisserait un émetteur mal réglé passer inaperçu.
_PALIERS_REFUS = (1, 10, 100, 1000)


# --- L'entraînement : les DEUX décodeurs, sur les MÊMES époques ---------------
# ⚠️ Ce bloc est monté ici depuis `research/cvep_calibrate.py` (chantier « la console, seul point
# d'entrée », tâche 8). C'est le moteur qui entraîne maintenant, et `core` n'importe jamais
# `research` ; l'appli pygame, elle, ré-importe d'ici — le sens autorisé. Une seconde copie de
# cette comparaison, avec ses propres tests, finirait par diverger sans que rien ne le dise.

def _fit_et_compte(modele, epochs, labels, **kw):
    """Ajuste `modele` sur EXACTEMENT `epochs`/`labels`, et rend `len(epochs)` — capturé ICI, au
    point d'appel, pour qu'un futur tronquage de l'ARGUMENT (`epochs[:-6]`) se voie dans le
    compte rendu, et pas seulement dans le modèle ajusté. Un `len(labels)` recalculé ailleurs,
    lui, ne bougerait pas si un seul des deux appels était tronqué."""
    modele.fit(epochs, labels, **kw)
    return len(epochs)


def entraine_les_deux(epochs, labels, fs=FS_UNICORN, refresh=REFRESH_REFERENCE_HZ, band=CVEP_BAND,
                      channels=None, n_cycles=CVEP_DECISION_CYCLES):
    """Entraîne eCCA ET rCCA sur les MÊMES époques de calibration, PARMI LE MÊME JEU DE CIBLES,
    les note HORS-PLI sur les MÊMES groupes de validation croisée, et rend
    `{"eCCA": {...}, "rCCA": {...}}`.

    ⚠️ Ce n'est PAS une nouvelle analyse : `CVEPModel.hors_pli` et `RCCAModel.hors_pli` sont des
    jumeaux au même contrat (`(epochs, labels, n_cycles) -> scores`), déjà éprouvés —
    `python src/core/cvep_rcca.py --seuils <calib.npz>` les fait tourner côte à côte sur une
    calibration réelle. Cette fonction les appelle tous les deux sur les mêmes entrées.

    `n_cycles` vaut `CVEP_DECISION_CYCLES` par défaut : c'est la géométrie où le MOTEUR décide,
    pas celle d'une époque de calibration seule — `groupes_de_cycles` prescrit littéralement de
    « mesurer un décodeur à la géométrie où il servira ». Mesuré sur `data/cvep_calib_last.npz`
    (lecture seule) : à k=1 les deux décodeurs sont à ÉGALITÉ EXACTE (43/90 chacun) ; à k=2 (la
    géométrie réelle), ils ne le sont plus — sans que l'écart soit défendable pour autant (cf.
    `gagnant`).

    ⚠️ **Une séance INTERROMPUE peut n'avoir vu qu'un SOUS-ENSEMBLE des cibles du plan.**
    `CVEPModel.hors_pli` ne juge alors que parmi les lags RÉELLEMENT VUS (son
    `uniq = sorted(set(lags))` rétrécit avec eux, et son hasard aussi) — mais un `RCCAModel`
    construit avec TOUS les codes du plan resterait jugé sur 1/6, quel que soit ce qui a été
    enregistré. Comparer les deux tels quels offre alors des points gratuits à celui jugé sur le
    plus petit jeu : MESURÉ sur `cvep_calib_last.npz` tronqué à 3 cibles, eCCA 71,1 % (hasard
    33,3 %) contre rCCA 51,1 % (hasard 16,7 %) — un « gagnant » entièrement fabriqué par l'écart
    de hasard, pas par le signal. On réduit donc les codes du rCCA aux SEULES cibles présentes
    dans `labels`, exactement comme `hors_pli` réduit `uniq`.

    `epochs` : cycles BRUTS (n_cyc x n_voies enregistrées, ex. 8 pour l'Unicorn) — la réduction
    aux voies AJUSTÉES (`channels`, `CVEP_CHANNELS` par défaut) se fait ICI, la MÊME pour les deux
    décodeurs : sans ça, un montage différent d'un décodeur à l'autre biaiserait la comparaison
    (vérifié par un garde qui REFUSE plutôt que de comparer si jamais ça divergeait).
    `labels` : le LAG (frames) fixé à chaque époque.

    Chaque valeur du dict rendu porte :
      `modele`      — l'objet entraîné (CVEPModel ou RCCAModel), prêt pour `.save(...)` ;
      `justesse`    — accuracy HORS-PLI (jamais celle, optimiste, d'un modèle qui a vu l'essai
                      qu'il note — le piège qui a gonflé le premier écran de calibration MI) ;
      `n_epoques`   — le nombre d'époques RÉELLEMENT données à `.fit()` pour CE décodeur (lu sur
                      l'appel lui-même, `_fit_et_compte`) ; DOIT être `len(labels)` pour les deux ;
      `n_cycles`    — la GÉOMÉTRIE à laquelle `justesse` a été mesurée. C'est de CE champ que
                      l'appelant doit tirer la DURÉE d'une décision pour calculer un ITR — jamais
                      d'une constante recopiée à côté (l'ITR affiché s'est déjà retrouvé DOUBLÉ
                      pour cette raison exacte, sans qu'aucune assertion ne s'en aperçoive) ;
      `groupes`     — les groupes de validation croisée (`core.cvep_decoder.groupes_de_cycles`, à
                      la géométrie `n_cycles`) — LES MÊMES pour les deux, par construction ;
      `n_decisions` — le nombre de groupes RÉELLEMENT notés par ce décodeur. Comparé à
                      `len(groupes)` par l'appelant : s'il diffère, ce décodeur a été noté à une
                      AUTRE géométrie que celle annoncée, silencieusement ;
      `n_cibles`    — le nombre d'alternatives RÉELLEMENT notées (la largeur de SA matrice de
                      scores hors-pli) : c'est CE nombre qui fixe le hasard contre lequel lire
                      `justesse`. DOIT être égal pour les deux. `None` si `n_decisions == 0` —
                      jamais une valeur d'apparence normale sur du vide ;
      `corrects`    — tableau booléen, une valeur par DÉCISION, dans le MÊME ordre que l'autre
                      décodeur. C'est ce qui rend les décisions eCCA et rCCA APPARIÉES, condition
                      nécessaire pour un test de McNemar (`gagnant`) — les comparer comme deux
                      échantillons INDÉPENDANTS serait le mauvais test. `None` si rien à mesurer.
    """
    plan, code = build_targets()
    codes = np.stack([np.asarray(c["code"], dtype=int) for c in plan])
    lag_a_idx = {c["lag"]: i for i, c in enumerate(plan)}

    labels = [int(l) for l in labels]
    # Les cibles RÉELLEMENT présentes dans cette séance — un sous-ensemble du plan complet si la
    # calibration a été interrompue. `RCCAModel` DOIT être construit sur CES codes-là.
    #
    # ⚠️ **Trié par POSITION DANS LE PLAN (`lag_a_idx`), surtout pas par valeur de lag.** Le
    # contrat d'appariement du rCCA est POSITIONNEL et il est écrit deux fois dans `core/` :
    # `cvep_rcca.RCCADecoder` et `cvep_models._codes_affiches`. Or `build_targets` fait TOURNER
    # l'affectation lag↔position quand `CVEP_LAG_ROTATION != 0` : `sorted(set(labels))` et l'ordre
    # du plan ne coïncident qu'à rotation nulle. Un `sorted()` nu produisait donc, hors rotation
    # zéro, un modèle rCCA dont les lignes sont une PERMUTATION de celles du stimulus :
    # `cvep_models.charger` le refuse (à juste titre : permuté, il nommerait systématiquement la
    # cible voisine), APRÈS que la calibration a annoncé « modèles sauvegardés ». Recalibrer
    # reproduisait le même fichier refusé — une impasse permanente.
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
    # courte, ou dont les blocs interrompent systématiquement toute paire de cycles consécutifs).
    # Un chiffre qui a l'air d'une vraie mesure sur du VIDE est exactement la panne muette que ce
    # dépôt existe pour éliminer : `n_cibles` et `corrects` sont donc `None` quand
    # `n_decisions == 0`, au même titre que `justesse`. **L'appelant DOIT fermer ce chemin avant
    # tout calcul**, pas le deviner.
    #
    # ⚠️ **Le test qui décide « rien à mesurer » DOIT être `len(sc) == 0` (le nombre de LIGNES),
    # jamais `sc.ndim`** : sur un tableau vide, `CVEPModel.hors_pli` rend `(0,)` mais
    # `RCCAModel.hors_pli` rend `(0, n_targets)` (il PRÉ-ALLOUE, donc la largeur survit à zéro
    # ligne). Un test sur `.ndim` aurait laissé passer un `n_cibles` rCCA d'apparence normale — 6,
    # le compte du plan — sur un tableau qui ne contient VRAIMENT rien.
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


def gagnant(res, seuil=SEUIL_MCNEMAR):
    """Le décodeur qui gagne, ou `None` si l'écart n'est PAS DÉFENDABLE — test de McNemar exact
    bilatéral (`_mcnemar_p`) sur les décisions APPARIÉES, PAS une comparaison de deux justesses
    comme si elles venaient d'échantillons indépendants. Pure, sans effet de bord.

    ⚠️ **Ne JAMAIS nommer de gagnant sur un écart qui n'est pas défendable.** C'est précisément
    parce que ce projet n'a mesuré AUCUNE différence détectable entre les deux décodeurs sur la
    seule séance réelle disponible (k=1 : eCCA 43/90 contre rCCA 43/90 ; k=2, la géométrie du
    moteur : **eCCA 22/37 = 59,5 % contre rCCA 24/37 = 64,9 %**, McNemar p = 0,727) qu'il garde
    les deux au lieu d'en jeter un — un « gagnant » affiché sur un écart de deux décisions dirait
    le contraire de ce que la mesure montre, à un étudiant qui n'a aucun moyen de le savoir.

    ⚠️ Écrire **`<décodeur> <valeur>`, jamais une valeur nue** : ce fichier nomme systématiquement
    eCCA en premier, et « 24/37 contre 22/37 » — deux fractions nues dans l'ordre INVERSE de cette
    convention — attribuait silencieusement le meilleur chiffre au mauvais décodeur.

    Rend un dict, jamais un simple nom : l'écran a besoin de la p-value et du nombre de décisions
    discordantes pour être honnête, pas seulement des deux pourcentages qui ne portent pas
    l'incertitude à eux seuls.
        `gagnant`        — "eCCA" | "rCCA" | None (indiscernables, ou rien à mesurer) ;
        `p`              — la p-value de McNemar, ou None si rien n'a pu être mesuré ;
        `b`, `c`         — décisions où SEUL eCCA (b) / SEUL rCCA (c) est correct ;
        `n_discordantes` — `b + c` : c'est CE nombre qui porte l'information.
    """
    corrects_e, corrects_r = res["eCCA"]["corrects"], res["rCCA"]["corrects"]
    if corrects_e is None or corrects_r is None:
        return {"gagnant": None, "p": None, "b": None, "c": None, "n_discordantes": None}
    b = int(np.sum(corrects_e & ~corrects_r))      # eCCA SEUL correct
    c = int(np.sum(~corrects_e & corrects_r))      # rCCA SEUL correct
    p = _mcnemar_p(b, c)
    nom = None
    if p < seuil and b != c:
        nom = "eCCA" if b > c else "rCCA"
    return {"gagnant": nom, "p": p, "b": b, "c": c, "n_discordantes": b + c}


def phrase_comparaison(mn):
    """Ce que le TEST dit des deux décodeurs, en une phrase — jamais l'écart des pourcentages seul.

    ⚠️ C'est le point d'honnêteté de tout ce fichier. « rCCA 64,9 % contre eCCA 59,5 % » se lit
    comme un résultat et n'en est pas un : sur 37 décisions, cinq points d'écart tiennent
    entièrement dans le bruit (McNemar p = 0,727). Ce dépôt a relayé cet écart comme un verdict
    avant de mesurer, et a dû se corriger. La phrase rend donc le test, son p et le nombre de
    décisions DISCORDANTES — les seuls chiffres qui portent l'incertitude.
    """
    if mn["p"] is None:
        return ("les deux décodeurs n'ont PAS pu être comparés : aucune décision à noter à la "
                "géométrie du moteur")
    detail = (f"McNemar p = {mn['p']:.3f} sur {mn['n_discordantes']} décision(s) discordante(s) "
              f"({mn['b']} eCCA seul, {mn['c']} rCCA seul)")
    if mn["gagnant"] is None:
        return (f"les deux décodeurs sont INDISCERNABLES sur cette séance ({detail}) : ne choisis "
                f"pas sur l'écart des deux pourcentages, il est dans le bruit")
    return f"{mn['gagnant']} l'emporte, et l'écart est DÉFENDABLE ({detail})"


def verdict(acc, mn):
    """Le verdict affiché : la qualité de la séance, PUIS ce que le test dit des deux décodeurs.

    `acc` est la justesse hors-pli du MEILLEUR des deux, à la géométrie où le moteur décide.
    None quand rien n'a pu être mesuré — et le dire est alors tout ce qu'il y a à dire.
    """
    if acc is None:
        return (f"justesse NON MESURÉE : aucune décision à la géométrie du moteur "
                f"({CVEP_DECISION_CYCLES} cycles) — trop peu de cycles consécutifs de la même "
                f"cible. Les modèles existent, mais rien ne dit ce qu'ils valent : recalibre sans "
                f"interrompre la séance.")
    for seuil, texte in VERDICTS:
        if acc >= seuil:
            return f"{texte} — {phrase_comparaison(mn)}"
    return f"{VERDICTS[-1][1]} — {phrase_comparaison(mn)}"


def horodatage(maintenant=None):
    """`AAAAMMJJ-HHMMSS`, le format que portent déjà les modèles c-VEP du dépôt.

    ⚠️ `maintenant or _time.time()` serait faux : `0.0` (l'epoch Unix) est un instant VALIDE et
    pourtant falsy — même piège que dans `core/modes/mi_calib.py`, où il est documenté au long.
    """
    return _time.strftime("%Y%m%d-%H%M%S",
                          _time.localtime(_time.time() if maintenant is None else maintenant))


def chemins_libres(dossier, n_epoques, prefixe=""):
    """(modèle eCCA, modèle rCCA, enregistrement), les TROIS garantis libres au retour.

    Jumeau de `p300_calib.chemins_libres` / `errp_calib.chemins_libres`, avec un fichier de plus :
    le c-VEP est le seul mode à produire DEUX modèles par séance. On avance d'une seconde tant que
    l'un des trois existe — le format d'horodatage a une résolution d'une SECONDE, et `savez`
    écrase sans rien demander.

    ⚠️ Les motifs `cvep_model*.npz` / `cvep_rcca_model*.npz` sont ceux que `core.cvep_models.MOTIFS`
    cherche : s'en écarter produirait des modèles que la console ne proposerait jamais. Et les noms
    sont HORODATÉS, jamais fixes — `data/cvep_model.npz` et `data/cvep_rcca_model.npz` sont des
    traces de séances réelles qu'aucun code de ce dépôt ne sait refaire.

    `prefixe` : `CALIB_CANDIDAT_PREFIXE` quand ce qu'on écrit est un CANDIDAT — un fichier qui ne
    doit correspondre à aucun motif de découverte tant que personne ne l'a retenu.
    """
    maintenant = _time.time()
    while True:
        stamp = horodatage(maintenant)
        ecca = _os.path.join(dossier, f"{prefixe}cvep_model_{stamp}.npz")
        rcca = _os.path.join(dossier, f"{prefixe}cvep_rcca_model_{stamp}.npz")
        npz = _os.path.join(dossier,
                            f"{prefixe}cvep_calib_{stamp}_n{int(n_epoques):03d}.npz")
        if not any(_os.path.exists(p) for p in (ecca, rcca, npz)):
            return ecca, rcca, npz
        maintenant += 1.0


def chemin_modele_horodate(decodeur, dossier=None):
    """`cvep_model_AAAAMMJJ-HHMMSS.npz` (eCCA) ou `cvep_rcca_model_…` (rCCA) — un fichier NEUF.

    Le chemin d'entrée de l'appli pygame (`research/cvep_calibrate.calibrate`), qui écrit encore
    directement dans `data/`. La calibration du MOTEUR, elle, passe par `chemins_libres` et son
    dossier candidat : elle n'a pas le droit de choisir où elle écrit.
    """
    if decodeur not in ("eCCA", "rCCA"):
        raise ValueError(f"décodeur inconnu : {decodeur!r} (attendu 'eCCA' ou 'rCCA')")
    dossier = _os.path.dirname(CVEP_MODEL_PATH) if dossier is None else dossier
    prefixe = "cvep_model" if decodeur == "eCCA" else "cvep_rcca_model"
    return _os.path.join(dossier, f"{prefixe}_{horodatage()}.npz")


def entrainer(epochs, labels, fs, refresh, chemin_ecca, chemin_rcca, chemin_npz=None,
              band=CVEP_BAND, channels=None, n_cycles=CVEP_DECISION_CYCLES, hors_bloc=0):
    """Entraîne les DEUX décodeurs, écrit ce qui est écrivable, et rend le dict que la console
    affiche. LÈVE si la séance est trop pauvre pour valoir un modèle.

    ⚠️ **`fs` et `refresh` sont EXIGÉS, sans valeur par défaut, et c'est la leçon de la tâche 4.**
    Ce sont les deux nombres qui décident, avec `code_len`, `band` et `channels`, si le modèle
    produit sera ACCEPTÉ par le mode qui décodera avec : `CVEPRuntime._desaccord_code` compare le
    `code_len`, et `maj_reference` refuse tout marqueur dont le rafraîchissement s'écarte de plus
    de 1 Hz de celui du modèle. Côté P300, le modèle était construit avec ses valeurs PAR DÉFAUT
    alors que les époques étaient découpées avec celles du runtime : mêmes nombres, tous les tests
    verts, et un refus certain du modèle fraîchement calibré au premier déplacement de constante.
    Ici, `refresh` ne peut MÊME PAS avoir de défaut honnête : il vient de l'écran de l'émetteur, et
    `core` ne voit aucun écran.

    `chemin_ecca` / `chemin_rcca` sont EXPLICITES, jamais devinés ici : c'est l'appelant qui décide
    où écrire. Un défaut fixe est précisément ce qui a fait perdre ses modèles au MI.

    `chemin_npz` (facultatif) archive les époques BRUTES à côté des modèles, écrit AVANT eux — si
    le disque est plein, l'exception remonte avant qu'un modèle n'existe, et aucun modèle orphelin
    ne se retrouve ÉLU comme le plus récent chargeable. Dans un projet d'exploration, les jeux de
    données SONT le résultat : la meilleure séance c-VEP jamais enregistrée (27,1 bits/min) a été
    perdue faute d'archive.

    `hors_bloc` : le nombre de marqueurs d'horloge reçus HORS d'un bloc consigné. Purement
    informatif, mais il nomme la panne la plus banale — une fenêtre lancée SANS `--calibrer`, qui
    publie son horloge et aucune consigne.
    """
    plan, _code = build_targets()
    epochs = [np.asarray(e, dtype=float) for e in epochs]
    labels = [int(l) for l in labels]
    cibles_vues = sorted(set(labels))

    if len(epochs) < MIN_EPOQUES or len(cibles_vues) < MIN_CIBLES:
        raise ValueError(
            f"séance trop pauvre pour entraîner : {len(epochs)} époque(s) sur "
            f"{len(cibles_vues)} cible(s) — il en faut au moins {MIN_EPOQUES} sur "
            f"{MIN_CIBLES} cibles, sinon il n'y a rien à distinguer. "
            + (f"{hors_bloc} marqueur(s) d'horloge sont arrivés HORS d'un bloc consigné : la "
               f"fenêtre tourne-t-elle bien avec « --calibrer » ? " if hors_bloc else "")
            + "Refais une séance, et vérifie la liaison du casque : des époques perdues en cours "
              "de route (le journal du moteur les compte) donnent exactement cette allure")

    res = entraine_les_deux(epochs, labels, fs=fs, refresh=refresh, band=band,
                            channels=channels, n_cycles=n_cycles)
    mn = gagnant(res)
    cv_e, cv_r = res["eCCA"]["justesse"], res["rCCA"]["justesse"]
    n_cibles = res["eCCA"]["n_cibles"] or len(cibles_vues)
    meilleur = None if (cv_e is None or cv_r is None) else max(cv_e, cv_r)

    _os.makedirs(_os.path.dirname(chemin_ecca) or ".", exist_ok=True)
    if chemin_npz:
        np.savez(chemin_npz, epochs=np.asarray(epochs), lags=np.asarray(labels), fs=float(fs),
                 refresh=float(refresh), n_targets=len(plan), rotation=CVEP_LAG_ROTATION,
                 channels=np.asarray(res["eCCA"]["modele"].channels, dtype=int),
                 ch_names=np.asarray(CH_NAMES),
                 sigma=float(np.asarray(epochs).std()))

    # ⚠️ **`n_targets` = ce que la séance a RÉELLEMENT présenté, jamais `len(plan)`.** Le template
    # eCCA est COMMUN à tous les lags : un modèle entraîné sur 3 cibles « marche » techniquement à
    # 6 et publie six corrélations d'apparence normale, dont trois sortent de lags qu'aucun cerveau
    # n'a jamais vus. C'est exactement la panne invisible que `CVEPRuntime._desaccord_code` refuse
    # — mais ce refus ne peut mordre que si le fichier dit la VÉRITÉ sur lui-même.
    res["eCCA"]["modele"].save(chemin_ecca, n_targets=len(cibles_vues))
    # ⚠️ **Une séance INTERROMPUE ne produit PAS de fichier rCCA, et le dire.** Le modèle rCCA
    # d'une séance à 3 cibles sur 6 porte 3 codes ; `core.cvep_models.charger` exige les codes du
    # stimulus AFFICHÉ (les 6, dans l'ordre du plan) et le refuse — donc le fichier n'apparaîtrait
    # jamais dans la liste de la console. Le sauvegarder quand même annoncerait un succès pour un
    # artefact que rien ne peut charger, et pourrait même le nommer gagnant.
    complete = len(cibles_vues) == len(plan)
    if complete:
        res["rCCA"]["modele"].save(chemin_rcca)
    else:
        chemin_rcca = None

    verdict_txt = verdict(meilleur, mn)
    acc_txt = ("non mesurée" if meilleur is None
               else f"eCCA {cv_e * 100:.1f}%  ·  rCCA {cv_r * 100:.1f}%")
    print(f"[cvep-calib] {len(epochs)} cycles sur {len(cibles_vues)} cible(s) "
          f"(hasard {100.0 / n_cibles:.0f}%), décision = {res['eCCA']['n_cycles']} cycle(s) : "
          f"{acc_txt}")
    print(f"[cvep-calib] {phrase_comparaison(mn)}")
    print(f"[cvep-calib] modèle eCCA : {chemin_ecca}")
    print(f"[cvep-calib] modèle rCCA : "
          + (chemin_rcca if chemin_rcca else
             f"NON sauvegardé — séance à {len(cibles_vues)} cible(s) sur {len(plan)}, il porterait "
             f"trop peu de codes et `cvep_models.charger` le refuserait"))
    if chemin_npz:
        print(f"[cvep-calib] enregistrement : {chemin_npz}")

    return {
        "modele": chemin_ecca,
        "modele_rcca": chemin_rcca,
        "nom": _os.path.basename(chemin_ecca),
        "enregistrement": chemin_npz,
        "n_essais": int(len(epochs)),
        "n_cibles": int(n_cibles),
        "acc_ecca": None if cv_e is None else float(cv_e),
        "acc_rcca": None if cv_r is None else float(cv_r),
        "mcnemar_p": mn["p"],
        "n_discordantes": mn["n_discordantes"],
        "n_decisions": int(res["eCCA"]["n_decisions"]),
        # Le niveau du hasard, affiché par la console À CÔTÉ de la justesse : 1/N cibles, jamais
        # 0,5. « 60 % » ne veut pas dire la même chose à 3 cibles (33 %) qu'à 6 (16,7 %).
        "hasard": 1.0 / n_cibles,
        "verdict": verdict_txt,
        "honnetete": HONNETETE,
    }


def entrainer_dans(dossier, epochs, labels, fs, refresh, *, prefixe="", **kw):
    """`entrainer`, mais c'est le DOSSIER qu'on donne : les trois noms de fichiers sont horodatés
    et garantis libres (`chemins_libres`). C'est la porte de la calibration du moteur.

    `fs`/`refresh` restent positionnels et sans défaut ici aussi : un défaut posé sur ce passe-plat
    suffirait à rouvrir le trou qu'on ferme un cran plus bas (cf. `entrainer`).
    """
    chemin_ecca, chemin_rcca, chemin_npz = chemins_libres(dossier, len(labels), prefixe=prefixe)
    return entrainer(epochs, labels, fs, refresh, chemin_ecca=chemin_ecca,
                     chemin_rcca=chemin_rcca, chemin_npz=chemin_npz, **kw)


class CVEPCalibration(MarkerCalibrationRuntime):
    """La calibration c-VEP vue du moteur : il écoute l'horloge, il découpe des cycles, il entraîne.

    La ligne du temps (chauffe, essais, entraînement, les trois abandons) vient entièrement de
    `MarkerCalibrationRuntime`. Ce qui est ici est ce que le socle ne peut pas savoir : quels
    marqueurs délimitent une époque, ce qu'ils valent comme étiquette, et ce qu'on entraîne avec.

    Le protocole publié par `src/stimulus/cvep.py --calibrer` :

        {"mode":"cvep","event":"calib_start","trials":90}
        {"mode":"cvep","event":"cycle","refresh":60.0}     <- l'HORLOGE, ~1/s, SANS INTERRUPTION
        {"mode":"cvep","event":"cue","target":2}           <- la cible réellement CERCLÉE
        {"mode":"cvep","event":"block_end"}                <- le bloc se ferme, la cible s'oublie
        {"mode":"cvep","event":"calib_end"}

    ⚠️ **`cycle` continue de battre pendant TOUTE la séance**, y compris entre deux blocs et
    pendant la chauffe du moteur. Sans horloge il n'y a pas de phase, donc pas d'époque alignée :
    le mode ne décoderait pas mal, il ne décoderait **rien**. `cue` s'ajoute, il ne remplace rien.

    ⚠️ **`block_end` ferme le bloc, et ce n'est pas décoratif** — c'est le `round_end` du P300,
    transposé. Entre deux blocs, la fenêtre laisse passer `CVEP_CAL_SETTLE_CYCLES` cycles pendant
    lesquels le regard cherche la nouvelle cible : ces cycles-là n'ont AUCUNE vérité-terrain. Sans
    `block_end`, ils hériteraient de la cible du bloc PRÉCÉDENT — même nombre d'époques, mêmes
    proportions, aucun compteur, et une fraction de la séance apprise à l'envers.
    """

    # Ce que la console affiche comme durée, hors chauffe. Calculée depuis `core/config.py` — le
    # moteur ne peut PAS la deviner, puisqu'il ne mène pas le protocole, mais il peut lire les
    # constantes sous lesquelles ce protocole a été réglé. Elle vaut pour les réglages PAR DÉFAUT
    # de la fenêtre, à REFRESH_REFERENCE_HZ : (18 blocs x 4 cycles jetés) + 90 cycles enregistrés,
    # à 1,05 s le cycle, soit ~2,8 min.
    duree_protocole_s = ((CVEP_N_TARGETS * CVEP_CAL_BLOCKS * CVEP_CAL_SETTLE_CYCLES
                          + CVEP_N_TARGETS * CVEP_CAL_CYCLES)
                         * _CODE_LEN / REFRESH_REFERENCE_HZ)

    def __init__(self, spec, params, engine, rng=None, dossier=None):
        """`dossier` : où écrire — porté par `CalibrationRuntime` et SANS repli sur `DATA_DIR`.

        C'est le moteur qui le donne, et c'est son dossier CANDIDAT temporaire : une calibration
        qui choisissait elle-même écrivait dans `data/` AVANT d'annoncer sa précision, donc une
        séance ratée y devenait le modèle le plus récent — celui qui est proposé par défaut —
        sans que personne ait pu la refuser.
        """
        super().__init__(spec, params, engine, rng=rng, dossier=dossier)
        self.plan, code = build_targets()
        self.classes = tuple(c["name"] for c in self.plan)
        # `code_len` est le nom que `CVEPRuntime._phase_et_cause` lit sur son `self` : le porter
        # sous CE nom-là est ce qui permet d'appeler sa méthode telle quelle (cf. `phase_a`).
        self.code_len = len(code)
        self._ref_ts = None            # idem : les deux champs de l'horloge, aux mêmes noms
        self._ref_refresh = None
        self._refresh_seance = None    # le rafraîchissement du PREMIER marqueur — cf. `refresh`
        self._cible = None             # la cible du bloc en cours ; None hors bloc
        self._refus = 0                # marqueurs refusés : cible/refresh illisible, phase perdue
        self._hors_bloc = 0            # cycles reçus hors bloc (settle, pauses) — ATTENDUS
        self._blocs = 0                # blocs ouverts par un `cue`

    # --- ce que le socle demande ---------------------------------------------

    @property
    def runtime_cls_du_mode(self):
        """La classe qui DÉCODE le c-VEP — c'est d'elle que vient `phase_a`.

        ⚠️ Chez le P300 et l'ErrP, le socle lit `pre_s`/`post_s` sur cette classe. Ici il n'y a
        rien à y lire : `CVEPRuntime` n'expose ni l'un ni l'autre, délibérément (ce mode ne
        découpe aucune époque autour d'un marqueur). Ce que cette classe apporte est sa
        RECONSTRUCTION DE PHASE, et c'est le seul chemin partagé qui existe pour ce mode.

        ⚠️ Le socle attend un attribut de classe ; c'est ici une PROPRIÉTÉ, pour l'unique raison
        expliquée en tête de module (le cycle d'import). Elle rend le même objet à chaque appel, et
        l'import d'un module déjà chargé n'est qu'une recherche dans un dictionnaire.

        ⚠️ Conséquence à connaître avant d'écrire un test : `CVEPCalibration.runtime_cls_du_mode`
        (sur la CLASSE) rend l'objet propriété, pas `CVEPRuntime`. Ce qui compte se lit sur une
        INSTANCE.
        """
        from core.modes.cvep import CVEPRuntime
        return CVEPRuntime

    # --- LA PHASE : la fonction du DÉCODAGE, appelée sur cet objet -------------

    def phase_a(self, t_fin):
        """Position dans le code à l'instant LSL `t_fin`, ou None — **LA méthode du décodage**.

        ⚠️ **C'est l'invariant central de ce fichier, et il ne passe pas par `epoch_from_stream`.**
        On ne recopie pas la formule `int(age * refresh + _EPS_FRAME) % code_len` : on appelle la
        fonction du mode, non liée, avec cet objet-ci pour `self`. Elle n'a besoin que de
        `code_len`, `_ref_ts` et `_ref_refresh`, que cette classe porte sous les MÊMES noms.

        Une recopie donnerait les mêmes nombres aujourd'hui et dériverait demain — et la dérive ne
        casse rien : quelques frames d'écart ne lèvent aucune exception, les corrélations baissent
        juste assez pour que rien ne se déclenche, et c'est indiscernable de quelqu'un qui fixe
        mal. `_selftest` compare les deux reconstructions PAR LES VALEURS, sur une course qui
        inclut une frame sautée.
        """
        return self.runtime_cls_du_mode.phase_a(self, t_fin)

    def _phase_et_cause(self, t_fin):
        """(phase, cause) — celle du décodage aussi : `phase_a` s'y ramène, sur `self`."""
        return self.runtime_cls_du_mode._phase_et_cause(self, t_fin)

    # --- la géométrie de l'époque, REDÉCLARÉE (le seul cas du chantier) --------

    @property
    def refresh(self):
        """Le rafraîchissement de la séance : celui du PREMIER marqueur de cycle reçu.

        ⚠️ Le PREMIER, et pas le dernier, parce que c'est lui qui fixe la LONGUEUR de l'époque.
        Deux longueurs différentes dans le même jeu d'entraînement le rendraient impossible à
        empiler (`np.asarray` sur des tableaux de tailles différentes), et un `refresh` toléré à
        ±1 Hz suffit à déplacer `n_pre` de quatre échantillons. Les marqueurs qui s'en écartent
        sont refusés et comptés — un écran ne change pas de mode d'affichage en cours de séance.

        Avant le premier marqueur : `REFRESH_REFERENCE_HZ`, pour que `pre_s` ait une valeur
        (le socle la lit à chaque tour, y compris pendant la chauffe). Aucune époque n'est
        enregistrée dans cet état — `phase_a` rend None tant qu'aucune référence n'existe.
        """
        return REFRESH_REFERENCE_HZ if self._refresh_seance is None else self._refresh_seance

    @property
    def pre_s(self):
        """UN CYCLE ENTIER du code, pris JUSTE AVANT le marqueur qui annonce le redémarrage.

        ⚠️ C'est la seule redéclaration de géométrie du chantier, et voici pourquoi elle est
        inévitable : `CVEPRuntime` n'expose ni `pre_s` ni `post_s` (il ne découpe aucune époque),
        donc il n'y a rien à LIRE. Ce qui remplace la lecture est `phase_a` : l'époque n'est
        enregistrée que si la phase reconstruite à sa FIN vaut 0 — c'est-à-dire si elle couvre
        exactement le cycle qui vient de s'écouler, à la phase où `CVEPModel.fit` attend ses
        époques.

        La longueur est la MÊME que `CVEPModel.n_cyc` (`code_len * fs / refresh` échantillons) :
        `epoch_from_stream` prend `round(pre_s * fs)` et le modèle `round(code_len * fs /
        refresh)` — le même nombre, écrit deux fois parce que les deux le calculent depuis
        `code_len / refresh`.
        """
        return self.code_len / self.refresh

    @property
    def post_s(self):
        """Zéro : l'époque est DERRIÈRE le marqueur, jamais devant.

        Deux conséquences, toutes deux voulues. (1) `markers_murs(post_s=0)` libère chaque marqueur
        dès qu'il est dans le tampon, sans attendre de post-stimulus — comme
        `CVEPRuntime._encaisser_marqueurs`, et pour la même raison : une horloge n'a rien à attendre
        derrière elle. (2) L'époque couvre le cycle ÉCOULÉ, celui que le sujet vient de fixer, pas
        celui qui commence.
        """
        return 0.0

    # --- les marqueurs -------------------------------------------------------

    def _etiquette(self, ts, marqueur):
        """`cue` MÉMORISE la cible du bloc ; chaque `cycle` délimite une époque et l'étiquette.

        L'étiquette est le **lag** de la cible cerclée : c'est ce que `entraine_les_deux` attend
        comme `labels`, et c'est ce que le décodeur cherche en ligne.

        ⚠️ **L'ORDRE des marqueurs à un bord de cycle est un contrat**, et l'émetteur le tient :
        le `cycle` part d'abord, `cue` (ou `block_end`) juste après. Le `cycle` qui précède un
        `cue` clôt donc le dernier cycle JETÉ du settle, et le premier cycle enregistré est le
        suivant. Inverser les deux ferait enregistrer, à chaque bloc, une époque prise pendant que
        le regard se déplaçait encore.
        """
        event = marqueur.get("event")

        if event == "cue":
            cible = self._cible_lisible(marqueur.get("target"))
            if cible is None:
                return None
            self._cible = cible
            self._blocs += 1
            self.classe = self.plan[cible]["name"]
            return None

        if event == "block_end":
            # Le bloc se ferme : la cible est OUBLIÉE. Cf. le ⚠️ de la docstring de la classe —
            # sans ça, les cycles du settle suivant hériteraient de cette cible-ci.
            self._cible = None
            self.classe = ""
            return None

        if event != "cycle":
            return None      # un événement inconnu s'ignore : le protocole grandira

        refresh, souci = self._refresh_lisible(marqueur.get("refresh"))
        if souci is not None:
            # Le marqueur ne peut pas recaler l'horloge : il ne délimite donc rien. UN seul
            # message, celui de la cause RACINE — dire ensuite « la phase ne tient pas » ajouterait
            # une seconde ligne pour la même panne, et deux compteurs pour un incident.
            self._refuse(souci)
            return None
        self._ref_ts = float(ts)
        self._ref_refresh = float(refresh)

        # ⚠️ LE point du module. La phase de cette époque vient du DÉCODAGE (`phase_a`), elle
        # n'est pas SUPPOSÉE. L'époque couvre le cycle qui vient de s'écouler, et `CVEPModel.fit`
        # exige des époques à la phase 0 : on le DEMANDE à la fonction qui, en ligne, répondra à
        # la même question sur la même horloge.
        #
        # ⚠️ Le refus ci-dessous est une DÉFENSE EN PROFONDEUR, et il faut le lire comme tel : le
        # marqueur vient de poser la référence à `ts`, donc la réponse est 0 par construction
        # aujourd'hui. Elle cesserait de l'être si `phase_a` changeait de sémantique — nouvelle
        # règle de péremption, `_EPS_FRAME` déplacé, référence posée ailleurs. C'est exactement le
        # statut de la garde `age < 0` de `CVEPRuntime._phase_et_cause`, que ce mode documente
        # déjà comme « INATTEIGNABLE par le chemin du moteur, gardée quand même ». La panne
        # qu'elles ferment toutes les deux ne lève rien : un entier plausible, une époque décalée,
        # et un modèle qui décode du bruit avec des corrélations d'apparence normale.
        phase = self.phase_a(ts)
        if phase != 0:
            self._refuse(f"l'horloge du code ne tient pas à cet instant (phase reconstruite : "
                         f"{phase!r}, attendu 0) — l'époque serait décalée d'un nombre inconnu de "
                         f"frames, et rien en aval ne le verrait")
            return None

        if self._cible is None:
            # Le cas NORMAL entre deux blocs : le regard cherche la nouvelle cible pendant
            # `CVEP_CAL_SETTLE_CYCLES` cycles, qui n'ont aucune vérité-terrain. Compté, jamais
            # imprimé : ~4 par bloc est le protocole, pas un incident. Le compte ne sert que
            # lorsque la séance est trop pauvre — il nomme alors la fenêtre lancée SANS
            # « --calibrer », qui publie une horloge et pas une seule consigne.
            self._hors_bloc += 1
            return None
        return int(self.plan[self._cible]["lag"])

    def _cible_lisible(self, cible):
        """L'indice de cible, ou None en le disant. Même garde que `core/modes/p300.py`.

        `isinstance(cible, bool)` d'abord : en Python `bool` HÉRITE de `int`, donc `True` passe
        `isinstance(cible, int)` ET `0 <= True < 6`. Une fenêtre qui enverrait `true` en JSON — le
        mot-clé existe, et il est à une faute de frappe de `1` — verrait tout un bloc étiqueté sur
        la cible 1.
        """
        if isinstance(cible, bool) or not isinstance(cible, int):
            self._refuse(f"« {cible!r} » n'est pas un indice de cible "
                         f"({type(cible).__name__}) sur un marqueur « cue »")
            return None
        if not 0 <= cible < len(self.plan):
            self._refuse(f"« {cible} » est hors de la plage attendue [0, {len(self.plan)}[ "
                         f"sur un marqueur « cue »")
            return None
        return cible

    def _refresh_lisible(self, refresh):
        """`(rafraîchissement, None)` s'il est utilisable, `(None, raison)` sinon.

        Rend la RAISON au lieu de la dire elle-même : c'est `_etiquette` qui refuse le marqueur,
        et il ne doit y avoir qu'UN message — et qu'un compteur — par marqueur refusé.

        Deux gardes, la seconde propre à la calibration. La première est celle du mode
        (`CVEPRuntime._encaisser_marqueurs`) : `bool` hérite de `int`, donc `true` passerait pour
        1 Hz. La seconde compare au rafraîchissement de la SÉANCE au lieu de celui d'un modèle —
        il n'y a pas encore de modèle, c'est cette séance qui va en produire un. Un écran ne change
        pas de mode d'affichage en cours de route : un marqueur qui l'affirme vient d'un second
        émetteur, ou d'un émetteur relancé autrement, et ses époques n'auraient pas la même
        longueur que les autres — un jeu d'entraînement qui ne s'empile même pas.
        """
        if isinstance(refresh, bool) or not isinstance(refresh, (int, float)):
            return None, (f"« {refresh!r} » n'est pas un rafraîchissement "
                          f"({type(refresh).__name__}) — le marqueur de cycle doit porter un champ "
                          f"`refresh` en Hz")
        refresh = float(refresh)
        if refresh <= 0.0:
            return None, f"rafraîchissement non positif ({refresh:g} Hz)"
        if self._refresh_seance is None:
            self._refresh_seance = refresh
            return refresh, None
        if abs(refresh - self._refresh_seance) > 1.0:
            return None, (f"cet émetteur annonce {refresh:.1f} Hz, la séance a commencé à "
                          f"{self._refresh_seance:.1f} Hz — deux émetteurs publient-ils sur le "
                          f"même flux ? Les époques n'auraient pas la même longueur")
        return refresh, None

    def _refuse(self, detail):
        self._refus += 1
        if self._refus in _PALIERS_REFUS:
            print(f"[cvep-calib] marqueur refusé ({self._refus} dans cette séance) : {detail} "
                  f"— vérifie la fenêtre de stimulus")

    # --- l'entraînement ------------------------------------------------------

    def _entrainer(self, enregistre, fs):
        """Les deux décodeurs, sur les époques que le socle vient d'enregistrer.

        ⚠️ `fs` vient du MOTEUR et `self.refresh` de l'ÉMETTEUR : ce sont les deux nombres avec
        lesquels ces époques ont RÉELLEMENT été prélevées, et le modèle doit les porter. Les
        laisser aux défauts de `entraine_les_deux` marcherait tant que l'écran tourne à 60 Hz et
        le casque à 250 — et le jour où ce n'est plus vrai, `CVEPRuntime.maj_reference` refuserait
        le modèle qu'on vient tout juste de calibrer, en accusant le modèle.

        `CALIB_CANDIDAT_PREFIXE` : ce qui sort d'ici est un CANDIDAT, invisible aux motifs
        `cvep_model*.npz` / `cvep_rcca_model*.npz` tant que personne ne l'a retenu.
        """
        epochs = [e for e, _lag in enregistre]
        labels = [lag for _e, lag in enregistre]
        return entrainer_dans(self.dossier_ou_lever(), epochs, labels, float(fs), self.refresh,
                              prefixe=CALIB_CANDIDAT_PREFIXE, hors_bloc=self._hors_bloc)

    # --- l'état, pour l'afficheur -------------------------------------------

    def state(self, now=None):
        """Celui du socle, plus ce que cette séance REFUSE et ce qu'elle laisse passer.

        `cycles_hors_bloc` n'est pas une alarme : entre deux blocs, l'horloge bat pendant que le
        regard cherche la nouvelle cible. C'est quand il est le SEUL compteur à monter — zéro
        époque, zéro bloc — que la fenêtre tourne sans « --calibrer ».
        """
        base = super().state(now)
        base["refus_marqueur"] = self._refus
        base["cycles_hors_bloc"] = self._hors_bloc
        base["blocs"] = self._blocs
        return base


def _selftest():  # noqa: C901 - un autotest se lit de haut en bas, pas en morceaux
    """Trois parties, et c'est la première qui porte la tâche.

    **A. LA PHASE.** Une course de rendu rejouée frame par frame, incluant une frame SAUTÉE, avec
    les MÊMES marqueurs donnés à un vrai `CVEPRuntime` et à cette calibration : les deux
    reconstructions sont comparées PAR LES VALEURS. C'est le seul chemin de code partagé entre
    l'entraînement et le décodage pour ce mode — les deux autres calibrations du chantier
    partagent `epoch_from_stream`, celle-ci partage `phase_a`.

    **B. Une séance ENTIÈRE**, jouée par des marqueurs sur un tampon EEG fabriqué qui porte un
    vrai c-VEP synthétique : le test juge alors le CONTENU (la justesse bat le hasard) et pas
    seulement la plomberie. Plus l'aller-retour : le modèle produit est-il ACCEPTÉ par le
    `CVEPRuntime` qui décodera avec ?

    **C. Les refus et la comparaison** : marqueurs mal formés, séance trop pauvre, et le McNemar
    sur les chiffres RÉELS de la séance de référence.

    Aucun casque, aucune fenêtre, aucune attente réelle : l'horloge est FABRIQUÉE (`tick` reçoit
    `now`) et le tampon EEG est synthétique mais HORODATÉ, comme celui du vrai moteur.
    """
    import contextlib
    import glob as _glob
    import inspect
    import shutil
    import tempfile
    from fnmatch import fnmatch

    from core.config import empreinte_dossier, nom_retenu
    from core.cvep_code import blocs_entrelaces
    from core.cvep_decoder import synth_cvep
    from core.modes import cvep as _cvep

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    plan, code = build_targets()
    L = len(code)

    # ⚠️ fs et refresh sont choisis pour que `code_len * fs / refresh` soit ENTIER : sans ça, un
    # tampon fabriqué en concaténant des cycles dérive d'un demi-échantillon par cycle contre les
    # horodatages des marqueurs (0,5 éch./cycle x 90 cycles = 180 ms), et le test mesurerait sa
    # propre fixture. 63 x 240 / 60 = 252 pile.
    FS, REFRESH = 240.0, 60.0
    N_CYC = int(round(L * FS / REFRESH))

    @contextlib.contextmanager
    def _modele_temporaire(refresh=REFRESH):
        """Pointe `core.modes.cvep.CVEP_MODEL_PATH` vers un modèle JETABLE, le temps du bloc.

        ⚠️ C'est le SEUL levier qui permette de construire un vrai `CVEPRuntime` sans lire le
        `data/` du dépôt — qui porte des enregistrements EEG d'une personne identifiable. Même
        geste que `core/modes/cvep.py::_selftest` et que `src/stimulus/cvep.py::_runtime_de_test`.
        """
        dossier = tempfile.mkdtemp(prefix="cvep_calib_modele_")
        avant = _cvep.CVEP_MODEL_PATH
        try:
            m = CVEPModel(fs=FS, refresh=refresh, code_len=L, channels=CVEP_CHANNELS)
            m.w = np.ones(len(CVEP_CHANNELS))
            m.template = np.zeros(L)
            m.cv_ = 0.5
            _cvep.CVEP_MODEL_PATH = m.save(_os.path.join(dossier, "cvep_model.npz"),
                                           n_targets=len(plan))
            yield
        finally:
            _cvep.CVEP_MODEL_PATH = avant
            shutil.rmtree(dossier, ignore_errors=True)

    def _runtime_reel(refresh=REFRESH):
        """Un `CVEPRuntime` construit par son chemin RÉEL (`validate` puis `__init__`)."""
        with _modele_temporaire(refresh):
            valeurs, raison = _cvep.validate(_cvep.SPEC, {})
            if raison is not None:
                raise RuntimeError(f"fabrique de test cassée : {raison}")
            return _cvep.CVEPRuntime(_cvep.SPEC, valeurs, engine=None)

    class _FausseAcq:
        fs = FS

    class _MoteurFactice:
        """Le strict nécessaire : un tampon EEG horodaté et la file de marqueurs du moteur."""

        def __init__(self, eeg, ts):
            self.acq = _FausseAcq()
            self.recent, self.recent_ts = eeg, ts
            self.t0 = float(ts[0])
            self._lots = []

        def markers_murs(self, mode_id, post_s):
            return self._lots.pop(0) if self._lots else []

    # =====================================================================================
    # A. LA PHASE — LE test de cette tâche.
    # =====================================================================================
    # Deux compteurs, et c'est tout le sujet : `pos` est la position du code que l'ÉMETTEUR
    # affiche (+1 par image dessinée), `frame` est la frame d'écran écoulée (+1 par balayage).
    # Ils avancent ensemble SAUF à `saut_a`, où l'écran a basculé deux fois pendant que l'émetteur
    # ne comptait qu'une image — le cas qui arrive vraiment (vsync manqué, tour de boucle long),
    # et le seul où l'émetteur et le moteur ont le droit d'être en désaccord d'UNE frame.
    rt_phase = _runtime_reel()
    calib_phase = CVEPCalibration(_cvep.SPEC, {}, None)
    t0 = 1000.0
    saut_a = L * 3 + 17
    releve, saute = [], False
    pos = frame = 0
    while pos < L * 6:
        t = t0 + frame / REFRESH
        if pos % L == 0:
            # Le marqueur part APRÈS le flip de la frame 0 — à l'instant où l'écran la montre.
            rt_phase.maj_reference(ts=t, refresh=REFRESH)
            calib_phase._etiquette(t, {"mode": "cvep", "event": "cycle", "refresh": REFRESH})
        releve.append((t, pos % L, rt_phase.phase_a(t), calib_phase.phase_a(t)))
        if frame == saut_a and not saute:
            saute = True
            frame += 1          # l'écran a sauté une image ; le compteur de l'émetteur, non
        pos += 1
        frame += 1

    vues_rt = [v for _t, _p, v, _c in releve]
    vues_calib = [v for _t, _p, _v, v in releve]
    chk(vues_rt == vues_calib,
        f"[LE TEST] la calibration et le décodage reconstruisent EXACTEMENT la même phase, sur "
        f"les {len(releve)} frames d'une course qui inclut une frame sautée — c'est le seul "
        f"chemin de code partagé entre l'entraînement et le décodage pour ce mode "
        f"({sum(1 for a, b in zip(vues_rt, vues_calib) if a != b)} désaccord(s))")
    # ⚠️ Le témoin qui rend la comparaison ci-dessus NON VACANTE : elle doit savoir DISTINGUER.
    # Une phase translatée d'UNE seule frame — la panne caractéristique de ce mode, celle qui ne
    # lève rien — ne passerait pas.
    translatee = [None if v is None else (v + 1) % L for v in vues_rt]
    chk(translatee != vues_calib,
        "…et cette comparaison SAIT distinguer : une phase translatée d'UNE frame ne la passerait "
        "pas (c'est exactement la panne qui ne lève aucune exception)")
    chk(len({v for v in vues_calib if v is not None}) == L,
        f"…et la course balaie TOUTES les positions du code, pas seulement les bords de cycle où "
        f"la réponse est 0 par construction ({len(set(vues_calib))} positions distinctes pour "
        f"{L} frames de code)")
    ecarts = [abs((v - p + L // 2) % L - L // 2)
              for _t, p, v, _c in releve if v is not None]
    chk(max(ecarts[:saut_a]) == 0 and max(ecarts) <= 1,
        f"…et cette phase-là est bien celle que l'écran AFFICHE : accord EXACT tant qu'aucune "
        f"image n'est sautée, une frame d'écart au plus ensuite (pire écart {max(ecarts)})")

    # La preuve STRUCTURELLE derrière : la formule n'est pas recopiée. Un test de valeurs seul
    # resterait vert sur une réimplémentation à l'identique — c'est la DÉRIVE qu'on interdit, pas
    # l'écart du jour.
    import ast
    import textwrap

    arbre = ast.parse(textwrap.dedent(inspect.getsource(CVEPCalibration)))
    modulos = [n for n in ast.walk(arbre)
               if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod)]
    chk(not modulos,
        f"…et elle n'est pas RECOPIÉE : pas une seule arithmétique modulaire dans cette classe "
        f"({len(modulos)} trouvée(s)) — la phase se replie sur `code_len`, donc toute copie de la "
        f"formule en contiendrait une. Ce qu'il y a à la place est l'appel à "
        f"`runtime_cls_du_mode.phase_a` : une copie donnerait les mêmes nombres aujourd'hui et "
        f"dériverait au premier déplacement de `_EPS_FRAME`")

    # =====================================================================================
    # B. Une séance ENTIÈRE, du `calib_start` au modèle relu par le mode
    # =====================================================================================
    def seance(cycles=4, blocs_par_cible=2, settle=2, fs=FS, refresh=REFRESH, snr=-6.0, graine=0,
               cibles=None):
        """(marqueurs, eeg, ts, n_epoques_attendues) — un c-VEP synthétique CONTINU.

        Le tampon est fabriqué cycle par cycle : le cycle k porte la réponse au code décalé du lag
        de la cible affichée à ce moment-là. Les époques sont ensuite prélevées par le VRAI chemin
        (le socle, `epoch_from_stream` aux `pre_s`/`post_s` de cette classe), ce qui rend ce test
        capable de dire quelque chose du décodage et pas seulement du câblage.
        """
        import random as _random

        rng = np.random.default_rng(graine)
        n_cyc = int(round(L * fs / refresh))
        cibles = plan if cibles is None else cibles
        blocs = blocs_entrelaces(cibles, cycles, blocs_par_cible, _random.Random(graine))

        # La suite des cycles AFFICHÉS : deux cycles de garde (le tampon doit précéder le premier
        # marqueur), puis, par bloc, `settle` cycles jetés et `n` cycles enregistrés ; un dernier
        # cycle de garde pour que le marqueur qui CLÔT le dernier bloc existe.
        suite = [(None, plan[0])] * 2
        for cible, n in blocs:
            suite += [("settle", cible)] * settle + [("bloc", cible)] * n
        suite += [(None, plan[0])]
        eeg = np.concatenate([synth_cvep(code, c["lag"], len(CH_NAMES), fs, refresh, snr, rng)
                              for _r, c in suite], axis=0)
        ts = np.arange(len(eeg), dtype=float) / fs + 1000.0

        # ⚠️ **Le marqueur de cycle `i` clôt le cycle `i-1`** : c'est CE décalage qui fait tout le
        # protocole. `cue` part JUSTE APRÈS le marqueur qui ouvre le bloc (donc ce marqueur-là
        # clôt le dernier cycle de settle, et n'est pas enregistré), et `block_end` JUSTE APRÈS
        # celui qui clôt le dernier cycle enregistré. Inverser l'un des deux enregistrerait, à
        # chaque bloc, une époque prise pendant que le regard se déplaçait encore.
        marqueurs = []
        for i, (role, _cible) in enumerate(suite):
            instant = float(ts[0]) + i * n_cyc / fs
            marqueurs.append((instant, {"mode": "cvep", "event": "cycle", "refresh": refresh}))
            precedent = suite[i - 1][0] if i > 0 else None
            if precedent == "bloc" and role != "bloc":
                marqueurs.append((instant, {"mode": "cvep", "event": "block_end"}))
            if role == "bloc" and precedent != "bloc":
                marqueurs.append((instant, {"mode": "cvep", "event": "cue",
                                            "target": plan.index(suite[i][1])}))
        attendues = sum(n for _c, n in blocs)
        return marqueurs, eeg, ts, attendues

    def joue(rt, moteur, marqueurs, attendues):
        """Fait vivre la séance : `calib_start`, la chauffe, les marqueurs, `calib_end`."""
        t = moteur.t0
        rt.tick(moteur, t)
        rt.encaisser(moteur, t, {"mode": "cvep", "event": "calib_start", "trials": attendues})
        rt.tick(moteur, t + rt.warmup_s + 0.1)          # la chauffe s'écoule -> « essais »
        for instant, m in marqueurs:
            rt.encaisser(moteur, instant, m)
        rt.encaisser(moteur, marqueurs[-1][0] + 0.5, {"mode": "cvep", "event": "calib_end"})
        t = moteur.t0 + rt.warmup_s + 0.2
        for _ in range(10):
            rt.tick(moteur, t)
            if rt.terminee:
                break
            t += 0.25
        return rt

    dossier = tempfile.mkdtemp(prefix="cvep_calib_")
    empreinte_avant = empreinte_dossier()
    try:
        # --- 1. Le contrat : le mode déclare CETTE calibration, avec une époque dimensionnée ---
        # PAS `is CVEPCalibration` : lancé directement, ce fichier tourne en `__main__` avec SA
        # classe, et l'import de `core.modes.cvep` en a chargé une SECONDE sous le nom de paquet.
        calib_spec = _cvep.SPEC.calibration
        chk(calib_spec is not None and calib_spec.kind == "fenetre"
            and calib_spec.stimulus_id == "cvep",
            f"le c-VEP déclare une calibration menée par une FENÊTRE ({calib_spec!r})")
        chk(calib_spec.runtime_cls is not None
            and calib_spec.runtime_cls.__name__ == CVEPCalibration.__name__,
            f"…et le moteur sait la JOUER : son runtime_cls est renseigné "
            f"({getattr(calib_spec.runtime_cls, '__name__', None)})")
        chk(calib_spec.epoch_s >= _CODE_LEN / REFRESH_REFERENCE_HZ - 1e-9,
            f"…et son epoch_s couvre UN CYCLE ENTIER du code, la tranche que cette calibration "
            f"prélève ({calib_spec.epoch_s:.3f} s pour {_CODE_LEN / REFRESH_REFERENCE_HZ:.3f} s)")
        chk(CVEPCalibration.duree_protocole_s > 120.0,
            f"la durée du protocole est RENSEIGNÉE — laissée à 0, la console annoncerait "
            f"« ≈ 0 min » pour une séance de presque trois minutes "
            f"({CVEPCalibration.duree_protocole_s:.0f} s)")

        # --- 2. La géométrie de l'époque suit l'ÉMETTEUR, pas une constante -------------------
        marqueurs, eeg, ts, attendues = seance()
        moteur = _MoteurFactice(eeg, ts)
        rt = CVEPCalibration(_cvep.SPEC, {}, moteur, dossier=dossier)
        chk(rt.runtime_cls_du_mode is _cvep.CVEPRuntime,
            f"la calibration DÉSIGNE le runtime de DÉCODAGE — c'est de lui que vient sa "
            f"reconstruction de phase ({rt.runtime_cls_du_mode})")
        chk(abs(rt.pre_s - L / REFRESH_REFERENCE_HZ) < 1e-9 and rt.post_s == 0.0,
            f"avant tout marqueur, l'époque vaut un cycle au rafraîchissement de RÉFÉRENCE "
            f"({rt.pre_s:.4f} s)")

        joue(rt, moteur, marqueurs, attendues)
        chk(rt.phase == "fini", f"la séance aboutit ({rt.phase}, problème={rt.probleme!r})")
        res = rt.resultat or {}
        chk(res.get("n_essais") == attendues,
            f"toutes les époques annoncées sont enregistrées ({res.get('n_essais')} pour "
            f"{attendues})")
        chk(rt._hors_bloc > 0 and rt._refus == 0,
            f"…les cycles du settle sont laissés de côté sans être comptés comme des refus "
            f"({rt._hors_bloc} hors bloc, {rt._refus} refus)")

        # --- 3. Le CONTENU : la justesse bat le hasard -----------------------------------------
        chk(res.get("acc_ecca") is not None and res.get("acc_rcca") is not None,
            f"les DEUX décodeurs sont notés ({res.get('acc_ecca')}, {res.get('acc_rcca')})")
        chk(res.get("acc_ecca", 0.0) > res.get("hasard", 1.0),
            f"…et sur du c-VEP synthétique, l'eCCA BAT le hasard — un épochage décalé ne le "
            f"pourrait pas ({res.get('acc_ecca')} contre {res.get('hasard')})")
        chk(abs(res.get("hasard", 0.0) - 1.0 / len(plan)) < 1e-9,
            f"…et le hasard rapporté est 1/{len(plan)} = 16,7 %, jamais 50 % ({res.get('hasard')})")
        chk(res.get("mcnemar_p") is not None and res.get("n_discordantes") is not None,
            f"le McNemar est CALCULÉ et rendu ({res.get('mcnemar_p')}, "
            f"{res.get('n_discordantes')} discordantes)")
        chk("McNemar" in res.get("verdict", ""),
            f"…et le verdict rend le TEST, pas seulement l'écart entre deux pourcentages "
            f"({res.get('verdict')})")

        # --- 4. DEUX fichiers candidats, invisibles tant que personne ne les retient ------------
        chk(res.get("modele", "").startswith(dossier)
            and (res.get("modele_rcca") or "").startswith(dossier),
            f"les DEUX modèles sont écrits dans le dossier reçu ({res.get('modele')}, "
            f"{res.get('modele_rcca')})")
        chk(_os.path.isfile(res.get("modele", "")) and _os.path.isfile(res.get("modele_rcca", "")),
            "…et ils existent vraiment sur le disque")
        chk(bool(res.get("enregistrement")) and _os.path.exists(res["enregistrement"]),
            f"…et les époques BRUTES sont archivées à côté ({res.get('enregistrement')})")

        from core import cvep_models

        chk(all(_os.path.basename(res.get(cle) or "").startswith(CALIB_CANDIDAT_PREFIXE)
                for cle in ("modele", "modele_rcca")),
            f"ce qui sort d'ici est un CANDIDAT, marqué comme tel "
            f"({_os.path.basename(res.get('modele', ''))})")
        chk(cvep_models.modeles_disponibles(dossier) == [],
            f"…donc INVISIBLE aux motifs {cvep_models.MOTIFS} : rien à découvrir dans son dossier "
            f"({cvep_models.modeles_disponibles(dossier)})")
        chk(fnmatch(nom_retenu(res.get("modele", "")), cvep_models.MOTIFS[0])
            and fnmatch(nom_retenu(res.get("modele_rcca", "")), cvep_models.MOTIFS[1]),
            f"…mais les noms sous lesquels ils seront RETENUS, eux, correspondent aux motifs — "
            f"sinon les modèles enregistrés ne seraient jamais proposés "
            f"({nom_retenu(res.get('modele', ''))}, {nom_retenu(res.get('modele_rcca', ''))})")

        # --- 5. L'ALLER-RETOUR : le modèle produit est ACCEPTÉ par le mode qui décodera avec ----
        # ⚠️ C'est le contrôle SYMÉTRIQUE de tout ce fichier, et c'est le défaut mesuré à la
        # tâche 4 côté P300 : le modèle y était construit avec les valeurs PAR DÉFAUT de la
        # configuration alors que les époques venaient du runtime — mêmes nombres, tous les tests
        # verts, et un refus certain du modèle fraîchement calibré au premier déplacement de
        # constante. Pour le c-VEP, les nombres qui décident sont `refresh`, `code_len`, `fs`,
        # `band` et `channels`.
        class _MoteurDuMode:
            acq = _FausseAcq()
            instance = "selftest"

        def _accepte(chemin, refresh_emetteur):
            """(runtime, refus) — le mode accepte-t-il CE modèle, à CE rafraîchissement ?

            Construit le runtime DIRECTEMENT, sans passer par `validate` : celui-ci n'accepte
            qu'un modèle figurant dans `_modeles_disponibles()`, c'est-à-dire dans le vrai `data/`
            — et un candidat porte justement le préfixe qui l'en rend invisible. Même détour que
            `p300_calib._selftest`.
            """
            params = {"model": chemin, "stream_in": "x", "corr_min": 0.26, "margin": 0.09,
                      "vote_len": 3, "min_votes": 2}
            try:
                decodeur = _cvep.CVEPRuntime(_cvep.SPEC, params, _MoteurDuMode())
                decodeur.maj_reference(1000.0, refresh_emetteur)   # la garde du rafraîchissement
                return decodeur, None
            except ValueError as e:
                return None, str(e)

        decodeur, refus = _accepte(res["modele"], REFRESH)
        chk(decodeur is not None,
            f"le modèle eCCA sorti de cette calibration est ACCEPTÉ par le mode qui décodera avec, "
            f"et il accepte AUSSI l'horloge de l'émetteur ({refus or 'aucun refus'})")
        chk(refus is not None or (decodeur.model.fs == FS
                                  and abs(decodeur.model.refresh - REFRESH) < 1e-9
                                  and decodeur.model.code_len == L
                                  and list(decodeur.model.channels) == list(CVEP_CHANNELS)),
            f"…parce qu'il PORTE la géométrie avec laquelle ses époques ont été prélevées : fs du "
            f"MOTEUR, refresh de l'ÉMETTEUR, longueur du code et voies "
            f"({getattr(decodeur, 'model', None) and (decodeur.model.fs, decodeur.model.refresh)})")

        # …et le même contrôle à un AUTRE rafraîchissement, celui qui rend le test falsifiable :
        # à 80 Hz, un modèle construit sur le défaut 60 Hz serait refusé par `maj_reference`.
        # 63 x 240 / 80 = 189 pile — même exigence d'entier que la fixture principale.
        marq80, eeg80, ts80, att80 = seance(refresh=80.0, graine=1)
        moteur80 = _MoteurFactice(eeg80, ts80)
        rt80 = CVEPCalibration(_cvep.SPEC, {}, moteur80, dossier=dossier)
        joue(rt80, moteur80, marq80, att80)
        res80 = rt80.resultat or {}
        chk(rt80.phase == "fini" and abs(rt80.refresh - 80.0) < 1e-9
            and abs(rt80.pre_s - L / 80.0) < 1e-9,
            f"une séance jouée à 80 Hz LIT ce rafraîchissement sur les marqueurs et raccourcit son "
            f"époque en conséquence ({rt80.refresh} Hz, {rt80.pre_s:.4f} s)")
        _d80, refus80 = _accepte(res80.get("modele", ""), 80.0)
        chk(_d80 is not None,
            f"…et le modèle qu'elle produit est accepté par un mode dont l'émetteur affiche 80 Hz "
            f"({refus80 or 'aucun refus'})")
        _d60, refus60 = _accepte(res80.get("modele", ""), 60.0)
        chk(_d60 is None and "80" in (refus60 or ""),
            f"…tandis qu'un émetteur à 60 Hz est REFUSÉ, en nommant les deux chiffres : c'est ce "
            f"refus qui rend le test précédent falsifiable ({refus60})")

        # --- 6. Les marqueurs mal formés sont refusés, pas étiquetés au hasard ------------------
        moteur_r = _MoteurFactice(eeg, ts)
        rt_r = CVEPCalibration(_cvep.SPEC, {}, moteur_r, dossier=dossier)
        rt_r.tick(moteur_r, moteur_r.t0)
        rt_r.encaisser(moteur_r, moteur_r.t0,
                       {"mode": "cvep", "event": "calib_start", "trials": 6})
        rt_r.tick(moteur_r, moteur_r.t0 + rt_r.warmup_s + 0.1)
        t_r = moteur_r.t0 + 20.0
        rt_r.encaisser(moteur_r, t_r, {"mode": "cvep", "event": "cue", "target": True})
        chk(rt_r._cible is None and rt_r._refus == 1,
            f"`target: true` n'est PAS la cible 1 : en Python `bool` hérite de `int` "
            f"({rt_r._cible!r}, {rt_r._refus} refus)")
        rt_r.encaisser(moteur_r, t_r + 0.1, {"mode": "cvep", "event": "cue", "target": 99})
        chk(rt_r._cible is None and rt_r._refus == 2,
            f"une cible hors plage non plus ({rt_r._cible!r})")
        rt_r.encaisser(moteur_r, t_r + 0.2, {"mode": "cvep", "event": "cycle", "refresh": True})
        chk(rt_r._refresh_seance is None and rt_r._refus == 3,
            f"`refresh: true` n'est PAS 1 Hz, même piège — et UN seul refus pour UN marqueur "
            f"({rt_r._refresh_seance!r}, {rt_r._refus} refus)")
        avant_refus = rt_r._refus
        rt_r.encaisser(moteur_r, t_r + 0.3, {"mode": "cvep", "event": "cycle", "refresh": 60.0})
        rt_r.encaisser(moteur_r, t_r + 1.4, {"mode": "cvep", "event": "cycle", "refresh": 144.0})
        chk(rt_r._refresh_seance == 60.0 and rt_r._refus == avant_refus + 1,
            f"…et un émetteur qui change de rafraîchissement en cours de séance est refusé : ses "
            f"époques n'auraient pas la même longueur ({rt_r._refresh_seance}, "
            f"{rt_r._refus - avant_refus} refus de plus)")

        # Un `cycle` dont le marqueur a été refusé ne doit RIEN enregistrer : la phase n'est plus
        # celle du code affiché, et l'époque serait décalée d'un nombre inconnu de frames.
        rt_r.encaisser(moteur_r, t_r + 1.5, {"mode": "cvep", "event": "cue", "target": 2})
        avant_enr = len(rt_r._enregistre)
        rt_r.encaisser(moteur_r, t_r + 2.6, {"mode": "cvep", "event": "cycle", "refresh": 144.0})
        chk(len(rt_r._enregistre) == avant_enr,
            f"un marqueur d'horloge REFUSÉ n'enregistre aucune époque — sans cette garde, elle "
            f"serait prélevée sur une phase que plus rien ne garantit "
            f"({len(rt_r._enregistre) - avant_enr} enregistrée(s))")
        chk(rt_r.state(now=t_r)["refus_marqueur"] == rt_r._refus
            and "cycles_hors_bloc" in rt_r.state(now=t_r),
            f"les refus sont VISIBLES dans l'instantané : sinon un émetteur mal réglé ne se voit "
            f"que dans un terminal que personne ne lit ({rt_r.state(now=t_r)['refus_marqueur']})")

        # `block_end` OUBLIE la cible — sans lui, les cycles du settle suivant en hériteraient.
        rt_b = CVEPCalibration(_cvep.SPEC, {}, _MoteurFactice(eeg, ts), dossier=dossier)
        rt_b.tick(rt_b.engine, rt_b.engine.t0)
        rt_b.encaisser(rt_b.engine, rt_b.engine.t0,
                       {"mode": "cvep", "event": "calib_start", "trials": 4})
        rt_b.tick(rt_b.engine, rt_b.engine.t0 + rt_b.warmup_s + 0.1)
        t_b = rt_b.engine.t0 + 20.0
        rt_b.encaisser(rt_b.engine, t_b, {"mode": "cvep", "event": "cue", "target": 3})
        rt_b.encaisser(rt_b.engine, t_b + 0.1, {"mode": "cvep", "event": "block_end"})
        avant_b = len(rt_b._enregistre)
        rt_b.encaisser(rt_b.engine, t_b + 0.2, {"mode": "cvep", "event": "cycle", "refresh": 60.0})
        chk(rt_b._cible is None and len(rt_b._enregistre) == avant_b and rt_b._hors_bloc == 1,
            f"après un `block_end`, un cycle n'est PAS étiqueté sur la cible du bloc précédent — "
            f"c'est le settle du bloc suivant, il n'a aucune vérité-terrain "
            f"({rt_b._cible!r}, {rt_b._hors_bloc} hors bloc)")

        # --- 7. Une séance trop pauvre est REFUSÉE, en disant quoi faire ------------------------
        marq_court, eeg_c, ts_c, att_c = seance(cycles=1, blocs_par_cible=1, graine=2,
                                                cibles=plan[:1])
        moteur_c = _MoteurFactice(eeg_c, ts_c)
        rt_court = CVEPCalibration(_cvep.SPEC, {}, moteur_c, dossier=dossier)
        joue(rt_court, moteur_c, marq_court, att_c)
        chk(rt_court.phase == "annule" and "trop pauvre" in rt_court.probleme,
            f"une séance trop pauvre refuse d'entraîner ({rt_court.phase}, {rt_court.probleme})")
        chk("Refais une séance" in rt_court.probleme,
            f"…en disant quoi faire ({rt_court.probleme})")

        # …et le cas de la fenêtre lancée SANS `--calibrer` : une horloge, aucune consigne.
        moteur_h = _MoteurFactice(eeg, ts)
        rt_h = CVEPCalibration(_cvep.SPEC, {}, moteur_h, dossier=dossier)
        rt_h.tick(moteur_h, moteur_h.t0)
        rt_h.encaisser(moteur_h, moteur_h.t0,
                       {"mode": "cvep", "event": "calib_start", "trials": 90})
        rt_h.tick(moteur_h, moteur_h.t0 + rt_h.warmup_s + 0.1)
        for i in range(20):
            rt_h.encaisser(moteur_h, moteur_h.t0 + 20.0 + i * (L / 60.0),
                           {"mode": "cvep", "event": "cycle", "refresh": 60.0})
        rt_h.encaisser(moteur_h, moteur_h.t0 + 60.0, {"mode": "cvep", "event": "calib_end"})
        rt_h.tick(moteur_h, moteur_h.t0 + rt_h.warmup_s + 0.2)
        rt_h.tick(moteur_h, moteur_h.t0 + rt_h.warmup_s + 0.4)
        chk(rt_h.phase == "annule" and "--calibrer" in rt_h.probleme,
            f"une fenêtre lancée SANS « --calibrer » publie une horloge et aucune consigne : le "
            f"refus NOMME cette cause, la plus banale ({rt_h.probleme[:120]})")

        # Une calibration sans dossier ne retombe PAS sur `data/`.
        rt_sans = CVEPCalibration(_cvep.SPEC, {}, _MoteurFactice(eeg, ts))
        try:
            rt_sans.dossier_ou_lever()
            refus_dossier = None
        except ValueError as e:
            refus_dossier = str(e)
        chk(refus_dossier is not None and "data/" in refus_dossier,
            f"sans dossier, la calibration REFUSE au lieu de retomber sur data/ "
            f"({(refus_dossier or 'aucun refus')[:70]}…)")
        chk(len(_glob.glob(_os.path.join(dossier, "*cvep_model*.npz"))) == 2,
            f"…et aucune des séances refusées n'a écrit de modèle "
            f"({_glob.glob(_os.path.join(dossier, '*cvep_model*.npz'))})")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    # =====================================================================================
    # C. La comparaison des deux décodeurs — le TEST, jamais l'écart seul
    # =====================================================================================
    def _corrects(n_concordants, b, c, n_faux=0):
        """(corrects_e, corrects_r) : `n_concordants` décisions où les deux sont D'ACCORD ET
        CORRECTS, `b` où SEUL eCCA est correct, `c` où SEUL rCCA l'est, `n_faux` où les deux se
        trompent ENSEMBLE."""
        e = np.array([True] * n_concordants + [True] * b + [False] * c + [False] * n_faux,
                     dtype=bool)
        r = np.array([True] * n_concordants + [False] * b + [True] * c + [False] * n_faux,
                     dtype=bool)
        return e, r

    # Le cas RÉEL : 37 décisions, 3 discordances pour eCCA seul, 5 pour rCCA seul (mesuré sur
    # data/cvep_calib_last.npz à k=2, lecture seule), soit eCCA 22/37 = 59,5 % contre rCCA
    # 24/37 = 64,9 % — un écart qui A L'AIR réel — et pourtant McNemar p = 0,7265625 : DU BRUIT.
    e_reel, r_reel = _corrects(19, 3, 5, n_faux=10)
    chk(len(e_reel) == 37 and int(e_reel.sum()) == 22 and int(r_reel.sum()) == 24,
        f"la fixture « cas réel » reproduit VRAIMENT les chiffres qu'elle annonce : 37 décisions, "
        f"eCCA {int(e_reel.sum())}/37 = {e_reel.mean()*100:.1f} %, rCCA {int(r_reel.sum())}/37 = "
        f"{r_reel.mean()*100:.1f} % — une fixture qui ment sur ses chiffres est crue par le "
        f"lecteur suivant")
    mn_reel = gagnant({"eCCA": {"corrects": e_reel}, "rCCA": {"corrects": r_reel}})
    chk(mn_reel["gagnant"] is None and abs(mn_reel["p"] - 0.7265625) < 1e-9
        and mn_reel["n_discordantes"] == 8,
        f"…et cet écart de POURCENTAGE réel mais NON DÉFENDABLE ne nomme PERSONNE ({mn_reel})")
    v_reel = verdict(float(r_reel.mean()), mn_reel)
    chk("INDISCERNABLES" in v_reel and "0.727" in v_reel.replace(",", ".")
        and "bruit" in v_reel,
        f"…et le verdict le DIT, avec son p : il rend le TEST, pas l'écart des deux pourcentages "
        f"({v_reel})")

    e_fort, r_faible = _corrects(0, 15, 0)
    mn_fort = gagnant({"eCCA": {"corrects": e_fort}, "rCCA": {"corrects": r_faible}})
    chk(mn_fort["gagnant"] == "eCCA" and mn_fort["p"] < 0.001,
        f"un écart DÉFENDABLE (15 décisions discordantes, toutes du même côté) nomme bien un "
        f"gagnant ({mn_fort})")
    mn_inverse = gagnant({"eCCA": {"corrects": r_faible}, "rCCA": {"corrects": e_fort}})
    chk(mn_inverse["gagnant"] == "rCCA", f"…dans les deux sens ({mn_inverse})")
    mn_vide = gagnant({"eCCA": {"corrects": None}, "rCCA": {"corrects": None}})
    chk(mn_vide["gagnant"] is None and mn_vide["p"] is None
        and "n'ont PAS pu être comparés" in phrase_comparaison(mn_vide),
        f"…et l'absence de mesure ne nomme personne non plus, sans lever ({mn_vide})")
    chk("NON MESURÉE" in verdict(None, mn_vide),
        f"…le verdict d'une séance sans aucune décision dit qu'il n'y a rien à mesurer, plutôt "
        f"que d'afficher un 0 % qui se lirait comme un diagnostic ({verdict(None, mn_vide)})")

    # ...et c'est LE MÊME test que celui de `--seuils`, pas une seconde copie.
    import core.cvep_rcca as _core_rcca
    chk(_mcnemar_p is _core_rcca._mcnemar_p and SEUIL_MCNEMAR == _core_rcca.SEUIL_MCNEMAR,
        "la calibration et `cvep_rcca.py --seuils` appellent LE MÊME `_mcnemar_p`, au même seuil")

    # =====================================================================================
    # D. `entraine_les_deux` : la comparaison est-elle HONNÊTE ?
    # =====================================================================================
    # ⚠️ Ces assertions ont DÉMÉNAGÉ ici avec leur fonction (chantier « seul point d'entrée »,
    # tâche 8) : elles vivaient dans `research/cvep_calibrate.py`, qui n'entraîne plus. Elles
    # gardent la seule chose qui rend un « gagnant » lisible — que les deux décodeurs aient vu les
    # MÊMES époques, les MÊMES groupes de validation croisée et le MÊME nombre d'alternatives.
    # 8 voies BRUTES (comme l'Unicorn), réduites à 4 AJUSTÉES : un jeu généré directement à 4
    # voies ne pourrait jamais faire diverger « brut » et « réduit », et le garde de largeur de
    # voies resterait invérifiable.
    fs_d, ref_d, voies_d = 250.0, 60.0, list(CVEP_CHANNELS)
    rng_d = np.random.default_rng(0)
    epochs_d = [synth_cvep(code, c["lag"], len(CH_NAMES), fs_d, ref_d, -6.0, rng_d)
                for c in plan for _ in range(8)]
    labels_d = [c["lag"] for c in plan for _ in range(8)]
    res_d = entraine_les_deux(epochs_d, labels_d, fs=fs_d, refresh=ref_d, channels=voies_d)
    chk(res_d["eCCA"]["n_epoques"] == res_d["rCCA"]["n_epoques"] == len(labels_d),
        f"les deux décodeurs s'ajustent sur le MÊME nombre d'époques — sinon la comparaison ne "
        f"veut rien dire ({res_d['eCCA']['n_epoques']}, {res_d['rCCA']['n_epoques']})")
    chk(res_d["eCCA"]["groupes"] == res_d["rCCA"]["groupes"],
        f"…et sur les mêmes groupes de validation croisée "
        f"({len(res_d['eCCA']['groupes'])} groupes)")
    # ⚠️ Ce contrôle est ce qui empêche « groupes » d'être décoratif : il compare ce que CHAQUE
    # décodeur a RÉELLEMENT noté (la longueur de son propre `hors_pli`) au nombre annoncé. Un
    # `n_cycles` différent passé à un seul des deux `hors_pli` noterait un autre nombre de
    # groupes, silencieusement.
    chk(res_d["eCCA"]["n_decisions"] == res_d["rCCA"]["n_decisions"]
        == len(res_d["eCCA"]["groupes"]),
        f"…et chacun a RÉELLEMENT noté autant de groupes qu'annoncé — sinon deux géométries "
        f"différentes se compareraient sans qu'aucun message ne le dise "
        f"({res_d['eCCA']['n_decisions']}, {res_d['rCCA']['n_decisions']})")
    chk(res_d["eCCA"]["n_cibles"] == res_d["rCCA"]["n_cibles"] == len(plan),
        f"…et parmi le MÊME nombre d'alternatives ({res_d['eCCA']['n_cibles']}, "
        f"{res_d['rCCA']['n_cibles']})")
    chk(res_d["eCCA"]["modele"].decoder == "eCCA" and res_d["rCCA"]["modele"].decoder == "rCCA",
        "…et chaque modèle SAIT quel décodeur il est (le champ que `save` écrit)")
    defaut_k = inspect.signature(entraine_les_deux).parameters["n_cycles"].default
    chk(defaut_k == CVEP_DECISION_CYCLES,
        f"la comparaison mesure par défaut à la géométrie de DÉCISION DU MOTEUR "
        f"(CVEP_DECISION_CYCLES={CVEP_DECISION_CYCLES}), pas à celle d'une époque de calibration "
        f"seule où k=1 masquerait un écart réel ({defaut_k})")

    # ⚠️ Une séance INTERROMPUE ne doit pas fausser le hasard. Tronquée à 3 cibles sur 6 : SANS
    # restreindre les codes du rCCA aux cibles VUES, il resterait jugé sur 1/6 (16,7 %) quand
    # l'eCCA rétrécit correctement à 1/3 (33,3 %) — c'est EXACTEMENT ce qui a produit
    # « gagnant : eCCA » sur des points offerts par le hasard, pas par le signal (mesuré sur une
    # séance réelle tronquée : 71,1 % contre 51,1 %).
    epochs_t = [synth_cvep(code, c["lag"], len(CH_NAMES), fs_d, ref_d, -6.0, rng_d)
                for c in plan[:3] for _ in range(8)]
    labels_t = [c["lag"] for c in plan[:3] for _ in range(8)]
    res_t = entraine_les_deux(epochs_t, labels_t, fs=fs_d, refresh=ref_d, channels=voies_d)
    chk(res_t["eCCA"]["n_cibles"] == res_t["rCCA"]["n_cibles"] == 3,
        f"une séance tronquée à 3 cibles juge les DEUX décodeurs parmi 3 alternatives, jamais 6 "
        f"pour l'un et 3 pour l'autre ({res_t['eCCA']['n_cibles']}, {res_t['rCCA']['n_cibles']})")
    chk(res_t["rCCA"]["modele"].n_targets == 3,
        f"…et le modèle rCCA entraîné porte VRAIMENT 3 codes ({res_t['rCCA']['modele'].n_targets})")

    # ⚠️ ZÉRO décision à la géométrie de mesure : chaque cible n'apparaît qu'une fois, dans un
    # ordre qui alterne. `groupes_de_cycles` rend alors [] à k=2 et `hors_pli` un tableau VIDE. Un
    # chiffre d'apparence normale sur du vide est la panne muette que ce dépôt existe pour
    # éliminer : `justesse`, `n_cibles` et `corrects` doivent dire eux-mêmes qu'il n'y a rien.
    epochs_v = [synth_cvep(code, c["lag"], len(CH_NAMES), fs_d, ref_d, -6.0, rng_d)
                for _ in range(2) for c in plan]
    labels_v = [c["lag"] for _ in range(2) for c in plan]
    chk(groupes_de_cycles(labels_v, CVEP_DECISION_CYCLES) == [],
        f"fixture : AUCUNE paire de cycles consécutifs de la même cible à k={CVEP_DECISION_CYCLES}")
    res_v = entraine_les_deux(epochs_v, labels_v, fs=fs_d, refresh=ref_d, channels=voies_d)
    chk(all(res_v[n]["n_decisions"] == 0 and res_v[n]["justesse"] is None
            and res_v[n]["n_cibles"] is None and res_v[n]["corrects"] is None
            for n in ("eCCA", "rCCA")),
        f"…et les deux décodeurs le DISENT — justesse, n_cibles et corrects à None, jamais un "
        f"chiffre d'apparence normale sur du vide ({res_v['eCCA']['n_cibles']}, "
        f"{res_v['rCCA']['n_cibles']})")

    # ⚠️ `_fit_et_compte` est le mécanisme qui rend `n_epoques` non-décoratif : il DOIT compter
    # l'ARGUMENT réellement passé à `.fit()`, jamais une longueur recalculée à côté (qui, elle, ne
    # verrait PAS un futur tronquage écrit à même l'appel, `epochs[:-6]`).
    class _ModeleFactice:
        vu = None

        def fit(self, epochs, labels, **kw):
            self.vu = (list(epochs), list(labels), kw)

    mf = _ModeleFactice()
    n_a = _fit_et_compte(mf, [1, 2, 3], ["a", "b", "c"], compute_cv=False)
    chk(n_a == 3 and mf.vu == ([1, 2, 3], ["a", "b", "c"], {"compute_cv": False}),
        f"_fit_et_compte ajuste EXACTEMENT ce qu'on lui donne, mots-clés compris ({n_a}, {mf.vu})")
    chk(_fit_et_compte(mf, [1, 2, 3], ["a", "b"]) == 3,
        "…et il compte les ÉPOQUES reçues, pas les étiquettes — sinon un tronquage appliqué à un "
        "seul des deux côtés passerait inaperçu")

    # Les chemins de l'appli pygame : horodatés, jamais les noms FIXES (qui s'écrasent), et
    # reconnus par les motifs de découverte — chacun sous LE SIEN.
    from core.cvep_models import MOTIFS as _MOTIFS

    ch_e, ch_r = chemin_modele_horodate("eCCA"), chemin_modele_horodate("rCCA")
    chk(ch_e != CVEP_MODEL_PATH and fnmatch(_os.path.basename(ch_e), _MOTIFS[0])
        and fnmatch(_os.path.basename(ch_r), _MOTIFS[1])
        and not fnmatch(_os.path.basename(ch_r), _MOTIFS[0]),
        f"`chemin_modele_horodate` rend des noms HORODATÉS, vus par `cvep_models` et chacun sous "
        f"SON motif ({_os.path.basename(ch_e)}, {_os.path.basename(ch_r)})")
    chk(_os.path.dirname(chemin_modele_horodate("eCCA", dossier="/tmp/xyz_cvep")) == "/tmp/xyz_cvep",
        "…et un `dossier` explicite est respecté, jamais celui de CVEP_MODEL_PATH — c'est le "
        "détour qu'un test doit prendre pour ne jamais écrire dans data/")

    # --- La phrase d'honnêteté est celle du c-VEP, pas celle d'un autre mode ------------------
    chk("16,7" in HONNETETE and "hasard" in HONNETETE,
        "la phrase d'honnêteté donne le hasard à SIX cibles (16,7 %)")
    chk("HORS LIGNE" in HONNETETE and "59,5" in HONNETETE and "64,9" in HONNETETE,
        "…dit que le 59,5 / 64,9 % est un chiffre HORS LIGNE, pas une justesse en direct")
    chk("46 %" in HONNETETE and "71 %" in HONNETETE,
        "…donne le COUPLE que le moteur produira vraiment (~46 % d'émission, ~71 % de justesse à "
        "l'émission), parce que comparer le mauvais dénominateur fabrique un verdict faux")
    chk("JAMAIS été décodé au casque" in HONNETETE,
        "…et dit que le c-VEP n'a jamais été décodé au casque par le moteur")
    chk("trois classes" not in HONNETETE and "sélection" not in HONNETETE
        and "0,776" not in HONNETETE,
        "…et ce n'est celle d'AUCUN autre mode : ni les trois classes du MI, ni la sélection du "
        "P300, ni l'AUC de l'ErrP")

    chk(empreinte_dossier() == empreinte_avant,
        "AUCUN fichier n'a bougé dans le vrai `data/` — il porte des enregistrements EEG d'une "
        "personne identifiable, et son modèle le plus récent est celui que le moteur ÉLIT")

    print(f"[cvep-calib] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
