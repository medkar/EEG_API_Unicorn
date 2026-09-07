"""La calibration ErrP : la fenêtre mène la piste, le MOTEUR entraîne.

Deuxième sous-classe concrète de `MarkerCalibrationRuntime` (`core/modes/marker_calib.py`, à lire
avant celui-ci), après `p300_calib.py`. Elle ne fournit que les trois choses que le socle réclame :

  1. `runtime_cls_du_mode = ErrPRuntime` — la géométrie d'époque est LUE là, jamais redéclarée ici ;
  2. `_etiquette(ts, marqueur)` — chaque `feedback` délimite une époque ET porte son étiquette ;
  3. `_entrainer(enregistre, fs)` — xDAWN + Riemann, l'AUC hors-pli groupée par bloc, le test de
     permutation, et une sauvegarde HORODATÉE.

⚠️⚠️ **CE MODE N'A PAS DE `cue`, ET C'EST LA CHOSE À COMPRENDRE EN PREMIER.** Chez le P300 et le
c-VEP, un marqueur ANNONCE la cible puis d'autres délimitent les époques : la vérité-terrain est
donnée d'avance et vaut pour toute la manche. Ici l'étiquette voyage sur l'événement `feedback`
lui-même, qui gagne un champ `error: true|false` **pendant la calibration seulement**.

Et c'est bien « seulement ». **L'ErrP est une BCI PASSIVE : tout son objet est de deviner, depuis
l'EEG seul, que la machine s'est trompée.** Un émetteur qui publierait `error` en décodage donnerait
la réponse au moteur — sans que rien ne le signale : le flux `decoded_errp` garderait la même forme,
les scores resteraient plausibles, et tout ce que ce produit affirme sur ce mode deviendrait faux.
La garde est écrite des deux côtés et dans les deux sens : côté fenêtre par
`stimulus/errp.py::marqueur_feedback` (l'unique endroit qui décide si l'étiquette part), côté moteur
par le refus ci-dessous d'un `feedback` sans étiquette — un tel marqueur vient d'une fenêtre qui
DÉCODE, ses époques n'ont aucune vérité-terrain, et les étiqueter « correct » par défaut glisserait
de vraies erreurs dans la classe majoritaire, en silence.

⚠️ **Ce qui change par rapport à l'ancien chemin** : les époques d'entraînement étaient découpées
par `research/errp_calibrate.py` (l'horloge de l'appli pygame, `app.acq.get_raw`) et celles du
décodage par le moteur (marqueurs LSL, `time_correction`). Deux chemins, aucun test pour les
accorder. Ici il n'y en a plus qu'UN : le socle prélève par `epoch_from_stream`, avec les
`pre_s`/`post_s` lus sur `ErrPRuntime` — littéralement l'appel que `core/modes/errp.py` fait en
décodant.

⚠️ **CE FICHIER NE TESTE PAS L'ALIGNEMENT, et il ne le peut pas.** Son autotest juge un décodage,
donc il tolère ce qu'un décodage tolère. L'alignement est gardé UN CRAN PLUS BAS, par
`python src/core/modes/marker_calib.py`, qui compare échantillon par échantillon les deux chemins
d'épochage sur deux géométries. Ne pas déplacer ce garde-là ici en croyant le rapprocher de son
sujet — il n'y survivrait pas (mesuré côté P300 : une translation de 150 ms laisse l'autotest de la
sous-classe entièrement vert).

⚠️ **`ErrPRuntime` est importé TARDIVEMENT, dans la propriété**, exactement comme chez le P300 et
pour la même raison mesurée : `core/modes/errp.py` importe ce module-ci (son `Calib` porte
`runtime_cls=ErrPCalibration`), donc un import en tête d'ici refermerait un CYCLE. Un cycle
module-à-module survit tant que chacun est importé par son nom de paquet — mais pas quand l'un des
deux fichiers est lancé DIRECTEMENT (`python src/core/modes/errp.py`, l'un des autotests de la
recette) : Python le charge alors sous le nom `__main__`, la garde de `sys.modules` ne joue plus, et
le second exemplaire demande un nom pas encore défini. Différer l'import supprime l'arête au lieu de
l'ordonner.

Autotest :
    python src/core/modes/errp_calib.py
"""

import os as _os
import sys as _sys
import time as _time

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
import numpy as np  # noqa: E402

from core.config import (CALIB_CANDIDAT_PREFIXE, ERRP_CAL_BLOCKS,  # noqa: E402
                         ERRP_CAL_TRIALS, ERRP_EPOCH_S, ERRP_ERROR_RATE, ERRP_FEEDBACK_S,
                         ERRP_MAX_RUN_STEPS, ERRP_PERM_N, ERRP_TRACK_CELLS, use_utf8_console)
from core.errp_decoder import CORRECT, ERROR, ErrPModel  # noqa: E402
from core.errp_track import (PAUSE_FIN_COURSE_S, PAUSE_INTER_PAS_S,  # noqa: E402
                             PAUSE_NOUVELLE_COURSE_S)
from core.modes.marker_calib import MarkerCalibrationRuntime  # noqa: E402
# ⚠️ `core.modes.errp` n'est PAS importé ici : cf. le ⚠️ de la docstring du module. Il l'est dans
# `ErrPCalibration.runtime_cls_du_mode`, une fois le programme lancé.

# Ce que l'étudiant lit AVANT de commencer, sur la page de la console. Le protocole lui-même
# s'affiche dans la fenêtre de stimulus : ce qui est ici est ce qu'il faut avoir compris avant.
BRIEFING = (
    "Un POINT lumineux doit rejoindre la pastille verte : c'est le BUT.",
    "À chaque pas il avance d'une case — le plus souvent VERS la pastille.",
    "Parfois il part DANS LE MAUVAIS SENS : c'est une erreur, et c'est ce qu'on enregistre.",
    "Tu n'as RIEN à faire d'autre que suivre le point et VOULOIR qu'il arrive.",
    "N'ANTICIPE pas les erreurs : l'ErrP est une réaction à une SURPRISE. Si tu passes la séance",
    "à guetter la prochaine bévue, il n'y a plus rien à détecter.",
    "Reste immobile et cligne le moins possible à l'instant PRÉCIS où le point bouge.",
)

# La phrase d'honnêteté de l'ErrP — PROPRE à ce mode, et elle dit TROIS choses (docs/recette.md
# §2.8, README) : ce que le détecteur attrape vraiment, que ces deux taux-là sont eux-mêmes
# optimistes, et ce qu'il est normal d'observer en séance. Celle du MI parle de 40 % à trois
# classes, celle du P300 de sélection parmi six cibles : les recopier ici serait faux deux fois.
HONNETETE = (
    "Au réglage par défaut, ce détecteur attrape UNE ERREUR SUR DEUX et annule une bonne commande "
    "sur sept (TPR 0,50 / TNR 0,855 sur la séance de référence). Ce n'est pas un défaut de "
    "réglage : c'est ce que vaut un ERP mono-essai en électrodes sèches. ⚠️ Et ces deux taux sont "
    "eux-mêmes OPTIMISTES. L'AUC, elle, est honnête — elle vient de scores hors-pli (0,776, "
    "p = 0,0099 sur 100 permutations, 200 essais, une personne) ; mais le SEUIL qui produit « une "
    "sur deux / une sur sept » a été choisi en REGARDANT ces mêmes scores, donc le taux de bonnes "
    "commandes gardées dépasse sa cible PAR CONSTRUCTION. En séance, attends-toi à en annuler "
    "plus, pas moins. Donc : ne conclus rien d'un essai, ni de dix — sur dix erreurs délibérées, "
    "EN ATTRAPER CINQ EST LE RÉSULTAT ATTENDU. Huit ou deux tiennent dans le bruit."
)

# Le verdict porte sur l'AUC hors-pli, jamais sur le TPR/TNR : ces deux-là sont mesurés au seuil
# qui les a choisis (cf. HONNETETE), donc un verdict calé dessus se féliciterait tout seul. Les
# paliers reprennent celui de l'écran de résultat historique (`research/errp_calibrate._results` :
# vert à partir de 0,70 ET significatif), avec un mot de plus pour ne pas laisser croire qu'un
# détecteur mono-essai à 0,78 est un décodeur fiable — c'est le repère du projet, et il reste
# modeste.
VERDICTS = ((0.75, "BON pour un ErrP mono-essai — au niveau du repère du projet (0,776)"),
            (0.65, "UTILISABLE"),
            (0.00, "FAIBLE — ré-essaie : saline Fz/Cz/Pz, et surtout n'ANTICIPE pas les erreurs "
                   "(l'ErrP est une réaction à une surprise ; à guetter la prochaine bévue, il "
                   "n'y a plus rien à détecter)"))

# Au-delà, l'AUC observée n'est pas distinguable de ce que le hasard produit sur ce nombre
# d'essais. C'est le seuil usuel, et c'est la règle de rigueur de ce projet : ne jamais conclure
# sur du bruit. Un verdict qui vanterait une AUC de 0,80 non significative sur 20 essais est
# exactement la panne que le test de permutation existe pour empêcher.
PERM_ALPHA = 0.05

# Les planchers en dessous desquels on REFUSE d'entraîner. Ce ne sont PAS des « il en faut au
# moins tant pour que ce soit bien » : ce sont les gardes de `ErrPModel.fit` lui-même
# (`core/errp_decoder.py`), sous lesquelles il ne pose AUCUN score hors-pli — donc aucun seuil
# réglable, donc un modèle que `errp_models.charger` REFUSERA au chargement. Produire un tel
# fichier serait écrire un candidat que personne ne pourra jamais retenir.
MIN_EPOQUES = 10
MIN_PAR_CLASSE = 2

# Paliers auxquels un marqueur refusé se DIT. Même motif que `p300_calib._PALIERS_REFUS` : une
# ligne par ordre de grandeur. Le dire à chaque pas noierait le terminal (200 par séance), le dire
# une seule fois laisserait une fenêtre lancée en mode DÉCODAGE — l'erreur la plus banale — ne
# produire qu'une ligne pour une séance entière perdue.
_PALIERS_REFUS = (1, 10, 100, 1000)

# La dérive moyenne du point vers sa cible, en cases par pas : un pas correct rapproche d'une
# case, une erreur en éloigne d'une. `max(...)` parce qu'à un taux d'erreur >= 50 % la piste est
# une marche aléatoire qui n'arrive jamais — la formule diviserait par zéro ou changerait de signe.
_DERIVE_PAR_PAS = max(0.05, 1.0 - 2.0 * ERRP_ERROR_RATE)
# Combien de pas dure une course, en moyenne : la distance du centre à une extrémité, divisée par
# la dérive, et plafonnée comme la piste le plafonne.
_PAS_PAR_COURSE = min(float(ERRP_MAX_RUN_STEPS), (ERRP_TRACK_CELLS // 2) / _DERIVE_PAR_PAS)


def verdict(auc, perm_p=None):
    """Le verdict, depuis l'AUC hors-pli ET sa significativité. None quand rien n'a été mesuré.

    L'ordre compte : une AUC NON significative n'est pas « faible », elle est **indistinguable du
    hasard**, et les deux ne se corrigent pas de la même façon (l'une demande un meilleur signal,
    l'autre plus d'essais). Les annoncer d'un même mot enverrait resaliner des électrodes qui vont
    très bien.
    """
    if auc is None:
        return ("AUC non mesurée : la séance n'avait pas de quoi faire une validation croisée "
                "honnête (deux classes, assez d'essais de chacune)")
    if perm_p is not None and perm_p >= PERM_ALPHA:
        return (f"NON SIGNIFICATIF (permutation p = {perm_p:.3f}) : cette AUC est indistinguable "
                f"de ce que le hasard produit sur ce nombre d'essais. Refais une séance plus "
                f"longue avant de t'en servir — ce n'est pas un problème de contact")
    for seuil, texte in VERDICTS:
        if auc >= seuil:
            return texte
    return VERDICTS[-1][1]


def horodatage(maintenant=None):
    """`AAAAMMJJ_HHMMSS`, le format que portent déjà les modèles ErrP du dépôt.

    ⚠️ `maintenant or _time.time()` serait faux : `0.0` (l'epoch Unix) est un instant VALIDE et
    pourtant falsy — même piège que dans `core/modes/mi_calib.py`, où il est documenté au long.
    """
    return _time.strftime("%Y%m%d_%H%M%S",
                          _time.localtime(_time.time() if maintenant is None else maintenant))


def chemins_libres(dossier, n_epoques, prefixe=""):
    """(chemin du modèle, chemin de l'enregistrement), les DEUX garantis libres au retour.

    Jumeau exact de `core/modes/p300_calib.py::chemins_libres`, et pour la même raison : le format
    du nom a une résolution d'une SECONDE, `save`/`savez` écrasent sans rien demander, et deux
    séances qui finissent la même seconde produiraient sinon les mêmes deux fichiers.

    ⚠️ Le motif `errp_model*.joblib` est celui que `core/errp_models.MOTIF` cherche : s'en écarter
    produirait un modèle que la console ne proposerait jamais. Et le nom est HORODATÉ, jamais fixe
    — `data/errp_model.joblib` est la trace casque du 24 juillet, le SEUL modèle ErrP enregistré
    sur un vrai cerveau (AUC 0,7763, p = 0,0099, 200 essais / 5 blocs), et aucun code de ce dépôt
    ne sait ré-entraîner depuis ses époques : l'écraser coûterait une séance entière.

    `prefixe` : `CALIB_CANDIDAT_PREFIXE` quand ce qu'on écrit est un CANDIDAT — un fichier qui ne
    doit correspondre à aucun motif de découverte tant que personne ne l'a retenu (cf. le
    commentaire de cette constante dans `core/config.py`). Défaut `""` : l'autre appelant,
    `research/errp_calibrate.py`, écrit directement dans `data/` un modèle définitif.
    """
    maintenant = _time.time()
    while True:
        stamp = horodatage(maintenant)
        chemin_modele = _os.path.join(dossier, f"{prefixe}errp_model_{stamp}.joblib")
        chemin_npz = _os.path.join(dossier,
                                   f"{prefixe}errp_calib_{stamp}_n{int(n_epoques):03d}.npz")
        if not _os.path.exists(chemin_modele) and not _os.path.exists(chemin_npz):
            return chemin_modele, chemin_npz
        maintenant += 1.0


def groupes_contigus(n, blocs=ERRP_CAL_BLOCKS):
    """Le numéro de BLOC de chacune des `n` époques, dans leur ordre d'arrivée.

    ⚠️ **Ce sont les GROUPES de la validation croisée, et ils ne sont pas décoratifs.** Sans eux,
    `_cv_splitter` retombe sur un `StratifiedKFold` qui mélange les époques : deux pas voisins de
    la même course — même piste, même fatigue, même dérive d'électrode — se retrouvent l'un dans
    l'entraînement et l'autre dans le test, et l'AUC monte pour une raison qui n'a rien à voir avec
    l'ErrP. C'est la fuite que `GroupKFold` existe pour fermer.

    Le bloc est une TRANCHE CONTIGUË de la séance, exactement comme dans
    `research/errp_calibrate.py` (`groups.append(r)`, un bloc = `trials // blocks` pas d'affilée).
    La différence est qu'il est reconstruit ICI, depuis l'ordre d'arrivée des marqueurs, au lieu
    d'être annoncé par la fenêtre. C'est délibéré : un marqueur de bloc de plus, c'est un contrat
    public de plus à tenir, à documenter et à ne jamais perdre — pour une information que le moteur
    possède déjà, puisqu'il reçoit les feedbacks dans l'ordre.
    """
    n = int(n)
    blocs = max(1, min(int(blocs), n)) if n else 1
    par_bloc = n / blocs
    return [min(blocs - 1, int(i // par_bloc)) for i in range(n)]


def entrainer(epochs, labels, fs, chemin_modele, chemin_npz=None, pre_s=None, post_s=None,
              n_perm=None, blocs=ERRP_CAL_BLOCKS):
    """Entraîne, évalue, écrit — et rend le dict que la console affiche. LÈVE si la séance est
    trop pauvre pour valoir un modèle.

    `chemin_modele` est EXPLICITE, jamais deviné ici : c'est l'appelant qui décide où écrire (la
    calibration du moteur passe son dossier candidat, `research/errp_calibrate.py` son `save_path`).
    Un défaut fixe est précisément ce qui a fait perdre les modèles du MI.

    `chemin_npz` (facultatif) archive les époques BRUTES à côté du modèle, écrit AVANT le `.joblib`
    — si le disque est plein, l'exception remonte avant que le modèle n'existe, et aucun modèle
    orphelin ne se retrouve ÉLU comme le plus récent chargeable.

    ⚠️ **`pre_s`/`post_s` sont ceux avec lesquels les époques ont RÉELLEMENT été découpées**, pas
    une valeur par défaut reprise de la configuration. Le modèle les porte en attributs, et
    `core/modes/errp.py::_desaccord_geometrie` les COMPARE à ce que le runtime prélève avant
    d'accepter de décoder avec. Les laisser par défaut marcherait tant que personne ne touche à
    `ErrPRuntime.pre_s` — et le jour où quelqu'un y touche, le mode refuserait le modèle qu'on
    vient tout juste de calibrer, EN ACCUSANT LE MODÈLE. C'est le défaut mesuré côté P300 à la
    tâche 4, et il ne se voit dans aucun test tant que les deux nombres coïncident.

    `n_perm` : None -> `ERRP_PERM_N` (100), la valeur du protocole. 0 saute la permutation, donc
    rend `perm_p = None` — un autotest de câblage peut le vouloir ; une séance réelle, jamais : sans
    p-value, rien ne distingue une AUC de 0,80 sur 20 essais d'un tirage chanceux.
    """
    epochs = np.asarray(epochs, dtype=float)
    labels = np.asarray(labels, dtype=int)
    compte = np.bincount(labels, minlength=2)
    if (len(epochs) < MIN_EPOQUES or len(set(labels.tolist())) < 2
            or int(compte.min()) < MIN_PAR_CLASSE):
        raise ValueError(
            f"séance trop pauvre pour entraîner : {len(epochs)} époque(s), "
            f"{int(compte[CORRECT])} correcte(s) et {int(compte[ERROR])} erreur(s) — il en faut "
            f"au moins {MIN_EPOQUES} au total, des DEUX classes, et au moins {MIN_PAR_CLASSE} de "
            f"chaque. En dessous, l'entraînement ne produit AUCUN score hors-pli, donc aucun seuil "
            f"réglable, donc un modèle que le mode refusera au démarrage. Refais une séance plus "
            f"longue, et vérifie la liaison du casque : des époques perdues en cours de route (le "
            f"journal du moteur les compte) donnent exactement cette allure")

    groupes = np.asarray(groupes_contigus(len(labels), blocs), dtype=int)
    n_perm = ERRP_PERM_N if n_perm is None else int(n_perm)
    modele = ErrPModel(fs=fs, pre_s=pre_s, post_s=post_s).fit(epochs, labels, groups=groupes,
                                                              n_perm=n_perm)

    _os.makedirs(_os.path.dirname(chemin_modele) or ".", exist_ok=True)
    if chemin_npz:
        # `pre_s`/`post_s` sont ARCHIVÉS avec les époques : sans eux, un ré-entraînement futur ne
        # saurait pas où tombe l'onset du feedback dans les échantillons qu'il relit.
        np.savez(chemin_npz, epochs=epochs, labels=labels, groups=groupes, fs=fs,
                 pre_s=modele.pre_s, post_s=modele.post_s)
    modele.save(chemin_modele)

    mesures = modele.metrics_ or {"tpr": 0.0, "tnr": 0.0, "bal_acc": 0.0}
    auc, perm_p = modele.cv_auc_, modele.perm_p_
    verdict_txt = verdict(auc, perm_p)
    auc_txt = "non mesurée" if auc is None else f"{auc * 100:.1f}%"
    perm_txt = "non testée" if perm_p is None else f"p={perm_p:.3f}"
    print(f"[errp-calib] {len(epochs)} époques ({int(compte[ERROR])} erreurs) sur "
          f"{len(set(groupes.tolist()))} blocs — AUC erreur/correct (hors-pli, par bloc) "
          f"{auc_txt}, permutation {perm_txt}, nfilter retenu {modele.nfilter_}")
    print(f"[errp-calib] au seuil {modele.threshold_:+.3f} : attrape {mesures['tpr']:.0%} des "
          f"erreurs, garde {mesures['tnr']:.0%} des bonnes commandes — {verdict_txt}")
    print(f"[errp-calib] modèle : {chemin_modele}")
    if chemin_npz:
        print(f"[errp-calib] enregistrement : {chemin_npz}")
    return {
        "modele": chemin_modele,
        "nom": _os.path.basename(chemin_modele),
        "enregistrement": chemin_npz,
        "n_essais": int(len(epochs)),
        "n_erreurs": int(compte[ERROR]),
        "auc": None if auc is None else float(auc),
        "perm_p": None if perm_p is None else float(perm_p),
        "tpr": float(mesures["tpr"]),
        "tnr": float(mesures["tnr"]),
        # Le niveau du hasard d'une AUC, affiché à côté d'elle par la console : 0,5, et pas 1/6
        # comme la sélection du P300. « 0,68 » ne veut rien dire sans lui.
        "hasard": 0.5,
        "verdict": verdict_txt,
        "honnetete": HONNETETE,
    }


def entrainer_dans(dossier, epochs, labels, fs, pre_s=None, post_s=None, n_perm=None,
                   blocs=ERRP_CAL_BLOCKS, prefixe=""):
    """`entrainer`, mais c'est le DOSSIER qu'on donne : les deux noms de fichiers sont horodatés et
    garantis libres (`chemins_libres`). C'est la porte de la calibration du moteur."""
    chemin_modele, chemin_npz = chemins_libres(dossier, len(labels), prefixe=prefixe)
    return entrainer(epochs, labels, fs, chemin_modele=chemin_modele, chemin_npz=chemin_npz,
                     pre_s=pre_s, post_s=post_s, n_perm=n_perm, blocs=blocs)


class ErrPCalibration(MarkerCalibrationRuntime):
    """La calibration ErrP vue du moteur : il écoute, il découpe, il entraîne. Rien d'autre.

    La ligne du temps (chauffe, essais, entraînement, les trois abandons) vient entièrement de
    `MarkerCalibrationRuntime`. Ce qui est ici est ce que le socle ne peut pas savoir : quels
    marqueurs délimitent une époque, ce qu'ils valent comme étiquette, et ce qu'on entraîne avec.
    """

    classes = ("correct", "erreur")

    # Ce que la console affiche comme durée, hors chauffe. Calculée depuis `core/config.py` et
    # `core/errp_track.py` — le moteur ne peut PAS la deviner, puisqu'il ne mène pas le protocole,
    # mais il peut lire les constantes sous lesquelles ce protocole a été réglé. C'est une
    # ESTIMATION : la longueur d'une course est aléatoire (elle dépend du tirage des erreurs et du
    # plafond de pas), et elle vaut pour les réglages PAR DÉFAUT de la fenêtre.
    duree_protocole_s = (ERRP_CAL_TRIALS * (ERRP_FEEDBACK_S + PAUSE_INTER_PAS_S)
                         + (ERRP_CAL_TRIALS / _PAS_PAR_COURSE)
                         * (PAUSE_FIN_COURSE_S + PAUSE_NOUVELLE_COURSE_S - PAUSE_INTER_PAS_S)
                         + PAUSE_NOUVELLE_COURSE_S + ERRP_EPOCH_S)

    # Combien de permutations pour la p-value. `None` = `ERRP_PERM_N` (100), la valeur du
    # protocole. C'est un ATTRIBUT DE CLASSE et pas un littéral pour que l'autotest puisse abaisser
    # ce nombre sans dévier du chemin d'entraînement : 100 permutations, ce sont 100 validations
    # croisées complètes (~30 s sur une vraie séance), et un autotest qui les subirait finirait par
    # ne plus être lancé. Le mettre à 0 en production supprimerait la seule chose qui distingue une
    # AUC réelle d'un tirage chanceux — c'est vérifié par `_selftest`.
    n_perm = None

    def __init__(self, spec, params, engine, rng=None, dossier=None):
        """`dossier` : où écrire — porté par `CalibrationRuntime` et SANS repli sur `DATA_DIR`.

        C'est le moteur qui le donne, et c'est son dossier CANDIDAT temporaire : une calibration
        qui choisissait elle-même écrivait dans `data/` AVANT d'annoncer sa précision, donc une
        séance ratée y devenait le modèle le plus récent — celui qui est proposé par défaut — sans
        que personne ait pu la refuser.
        """
        super().__init__(spec, params, engine, rng=rng, dossier=dossier)
        self._refus = 0        # feedbacks refusés : aucune étiquette, ou étiquette illisible

    # --- ce que le socle demande ---------------------------------------------

    @property
    def runtime_cls_du_mode(self):
        """La classe qui DÉCODE l'ErrP — c'est d'elle que le socle lit `pre_s`/`post_s`.

        ⚠️ Le socle attend un attribut de classe ; c'est ici une PROPRIÉTÉ, pour l'unique raison
        expliquée en tête de module (le cycle d'import). Elle rend le même objet à chaque appel, et
        l'import d'un module déjà chargé n'est qu'une recherche dans un dictionnaire.

        ⚠️ Conséquence à connaître avant d'écrire un test : `ErrPCalibration.runtime_cls_du_mode`
        (sur la CLASSE) rend l'objet propriété, pas `ErrPRuntime`. Ce qui compte se lit sur une
        INSTANCE, comme le socle le fait.
        """
        from core.modes.errp import ErrPRuntime
        return ErrPRuntime

    def _etiquette(self, ts, marqueur):
        """Chaque `feedback` délimite une époque ET porte son étiquette. Il n'y a pas de `cue`.

        ⚠️ **Un `feedback` SANS `error` est REFUSÉ, jamais étiqueté par défaut.** C'est le marqueur
        d'une fenêtre lancée en mode DÉCODAGE : ses époques n'ont aucune vérité-terrain. Les
        compter « correct » — le choix qui vient naturellement, puisque c'est la classe majoritaire
        — glisserait ~28 % de vraies erreurs dans la classe des bonnes commandes, et le modèle
        apprendrait à ne jamais rien détecter. Rien ne le signalerait : le bon NOMBRE d'époques
        arriverait à l'entraînement, dans des proportions plausibles.

        ⚠️ **`False` est une étiquette VALIDE**, et c'est le piège de ce hook : le socle décide
        « pas d'époque » sur `etiquette is None`, pas sur sa fausseté. Un `if not etiquette` écrit
        un jour là-haut ferait disparaître EN SILENCE toutes les époques correctes — soit ~72 % de
        la séance — et laisserait un jeu d'entraînement à une seule classe. `_selftest` le vérifie.

        ⚠️ **Seul `bool` est accepté**, pas `1`/`0` ni `"true"`. Une étiquette est la vérité-terrain
        du jeu d'entraînement : la deviner à partir d'un type inattendu, c'est prendre le risque de
        l'inverser sur toute une séance. Un émetteur tiers qui enverrait autre chose doit
        l'apprendre au premier pas, par un message, pas au moment où son modèle décode du bruit.
        """
        if marqueur.get("event") != "feedback":
            return None      # un événement inconnu s'ignore : le protocole grandira
        if "error" not in marqueur:
            self._refuse("un « feedback » est arrivé SANS champ `error` : cette époque n'a aucune "
                         "vérité-terrain. La fenêtre tourne-t-elle bien avec « --calibrer » ?")
            return None
        etiquette = marqueur.get("error")
        if not isinstance(etiquette, bool):
            self._refuse(f"« error: {etiquette!r} » n'est pas un booléen "
                         f"({type(etiquette).__name__}) : on ne DEVINE pas une vérité-terrain")
            return None
        self.classe = "erreur" if etiquette else "correct"
        return etiquette

    def _refuse(self, detail):
        self._refus += 1
        if self._refus in _PALIERS_REFUS:
            print(f"[errp-calib] marqueur refusé ({self._refus} dans cette séance) : {detail} "
                  f"— vérifie la fenêtre de stimulus")

    def _entrainer(self, enregistre, fs):
        """Traduit les étiquettes en classes du décodeur, puis entraîne dans `self.dossier`.

        `self.pre_s`/`self.post_s` : la géométrie avec laquelle le socle vient RÉELLEMENT de
        découper ces époques, lue sur le runtime de décodage. Le modèle la porte, et le mode la
        compare à la sienne avant d'accepter de décoder avec (`errp.py::_desaccord_geometrie`).
        `CALIB_CANDIDAT_PREFIXE` : ce qui sort d'ici est un CANDIDAT, invisible au motif
        `errp_model*.joblib` tant que personne ne l'a retenu.
        """
        epochs = [e for e, _lab in enregistre]
        labels = [ERROR if lab else CORRECT for _e, lab in enregistre]
        return entrainer_dans(self.dossier_ou_lever(), epochs, labels, fs,
                              pre_s=self.pre_s, post_s=self.post_s, n_perm=self.n_perm,
                              prefixe=CALIB_CANDIDAT_PREFIXE)

    # --- l'état, pour l'afficheur -------------------------------------------

    def state(self, now=None):
        """Celui du socle, plus le compteur de feedbacks REFUSÉS.

        Sans lui, une fenêtre lancée en mode décodage pendant une calibration ne se voit que dans
        le terminal — et elle produit une séance entière d'époques sans étiquette, donc une
        calibration qui échoue au bout de six minutes sans qu'on sache pourquoi.
        """
        base = super().state(now)
        base["refus_etiquette"] = self._refus
        return base


def _selftest():
    """Une séance de calibration entière, jouée par des marqueurs sur un tampon EEG FABRIQUÉ.

    Aucun casque, aucune fenêtre, aucune attente réelle : l'horloge est donnée à `tick`, et le
    signal porte de vrais ErrP synthétiques plantés AUX INSTANTS des feedbacks d'erreur — donc
    l'entraînement porte sur quelque chose, et le test peut juger le CONTENU, pas seulement la
    plomberie.
    """
    import glob as _glob
    import shutil
    import tempfile
    from fnmatch import fnmatch

    from core.config import empreinte_dossier, nom_retenu
    from core.errp_decoder import synth_errp_epoch
    from core.modes import errp as _errp

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    FS = 250.0
    SOA = 1.45              # la cadence intra-course du protocole (ERRP_FEEDBACK_S + pause)
    N_PAS = 60

    class _FausseAcq:
        fs = FS

    class _MoteurFactice:
        """Le strict nécessaire : un tampon EEG horodaté et la file de marqueurs du moteur."""

        def __init__(self, eeg, ts):
            self.acq = _FausseAcq()
            self.recent, self.recent_ts = eeg, ts
            self.t0 = float(ts[0])
            self._lots = []

        def file(self, lot):
            self._lots.append(list(lot))

        def markers_murs(self, mode_id, post_s):
            return self._lots.pop(0) if self._lots else []

    def seance(n_pas=N_PAS, graine=0, taux=0.3, amp=1.6):
        """(marqueurs, tampon EEG, horodatages, étiquettes) — un ErrP synthétique planté à chaque
        feedback d'ERREUR, et rien à ceux qui sont corrects.

        Les époques sont ensuite prélevées par le vrai chemin (`epoch_from_stream`, via le socle) :
        c'est ce qui rend ce test capable de dire quelque chose du décodage et pas seulement du
        câblage.
        """
        rng = np.random.default_rng(graine)
        t0 = 1000.0
        plan, verites, t = [], [], t0 + 2.0
        for i in range(n_pas):
            # Alternance forcée sur les premiers pas : sans elle, un tirage malheureux peut donner
            # une classe minoritaire à un seul membre, et c'est alors le REFUS qu'on testerait
            # sans le savoir, pas la séance nominale.
            erreur = (i % 3 == 0) if i < 9 else bool(rng.random() < taux)
            plan.append((t, {"mode": "errp", "event": "feedback", "error": erreur}))
            verites.append(erreur)
            t += SOA
        duree = t - t0 + 3.0

        ts = np.arange(t0, t0 + duree, 1.0 / FS)
        eeg = rng.normal(0.0, 1.8, (len(ts), 8))
        eeg += 0.7 * np.sin(2 * np.pi * 10 * (ts - t0))[:, None]        # un alpha de fond
        # ⚠️ La géométrie est LUE sur le runtime de décodage ici AUSSI, et passée à
        # `synth_errp_epoch` : ses défauts sont ceux de `core/config.py`, donc une fixture qui les
        # laisserait fabriquerait une onde d'une autre longueur que la tranche où on la plante dès
        # que quelqu'un déplace `ErrPRuntime.pre_s`. Le test tomberait alors sur un `ValueError` de
        # broadcast au lieu de dire ce qu'il a à dire — et c'est précisément le remaniement sous
        # lequel il doit rester lisible, puisque c'est celui qui met à nu la géométrie SAUVEGARDÉE.
        pre_s, post_s = _errp.ErrPRuntime.pre_s, _errp.ErrPRuntime.post_s
        n_pre, n_post = int(round(pre_s * FS)), int(round(post_s * FS))
        for (instant, m), erreur in zip(plan, verites):
            if not erreur:
                continue
            i = int(np.searchsorted(ts, instant))
            onde = synth_errp_epoch(True, fs=FS, pre_s=pre_s, post_s=post_s, amp=amp,
                                    noise=0.0, rng=rng)
            # `noise=0` ne suffit pas : `synth_errp_epoch` ajoute aussi un alpha. On ne garde que
            # la réponse évoquée, en la centrant.
            tranche = onde[:n_pre + n_post]
            eeg[i - n_pre:i + n_post] += tranche - tranche.mean(axis=0)
        return plan, eeg, ts, verites

    def joue(rt, moteur, plan, pas=0.25):
        """Fait vivre la séance : `calib_start`, la chauffe, les marqueurs, `calib_end`."""
        t0 = moteur.t0
        rt.tick(moteur, t0)
        rt.encaisser(moteur, t0, {"mode": "errp", "event": "calib_start", "trials": len(plan)})
        rt.tick(moteur, t0 + rt.warmup_s + 0.1)          # la chauffe s'écoule -> « essais »
        for instant, m in plan:
            rt.encaisser(moteur, instant, m)
        rt.encaisser(moteur, plan[-1][0] + 1.0, {"mode": "errp", "event": "calib_end"})
        t = t0 + rt.warmup_s + 0.2
        for _ in range(10):
            rt.tick(moteur, t)
            if rt.terminee:
                break
            t += pas
        return rt

    class _CalibRapide(ErrPCalibration):
        """La VRAIE classe, avec moins de permutations. Cf. le commentaire de `n_perm` : 100
        validations croisées feraient de cet autotest une minute d'attente, et un autotest qu'on
        n'ose plus lancer ne garde rien.

        ⚠️ **24 et pas 12**, et ce n'est pas un arrondi. `_permutation_p` rend `(k + 1)/(n + 1)`,
        donc la p-value la plus PETITE atteignable vaut `1/(n_perm + 1)` : à 12 permutations, le
        plancher est 0,077 — au-dessus de `PERM_ALPHA`. Une séance parfaitement décodée n'aurait
        alors JAMAIS pu ressortir significative, et cet autotest n'aurait exercé qu'une moitié du
        verdict, sans que rien ne le dise. À 24, le plancher tombe à 0,040 et les deux branches
        sont atteignables. Vérifié explicitement plus bas."""

        n_perm = 24

    dossier = tempfile.mkdtemp(prefix="errp_calib_")
    empreinte_avant = empreinte_dossier()
    try:
        # --- 1. Le contrat : le mode déclare CETTE calibration, avec une époque dimensionnée ---
        # PAS `is ErrPCalibration` : lancé directement, ce fichier tourne en `__main__` avec SA
        # classe, et l'import de `core.modes.errp` juste au-dessus en a chargé une SECONDE sous le
        # nom de paquet. Mêmes valeurs, objet différent — l'artefact mécanique que
        # `core/modes/mi_calib.py` documente au long. On compare donc ce qui identifie.
        calib = _errp.SPEC.calibration
        chk(calib is not None and calib.kind == "fenetre" and calib.stimulus_id == "errp",
            f"l'ErrP déclare une calibration menée par une FENÊTRE ({calib!r})")
        chk(calib.runtime_cls is not None
            and calib.runtime_cls.__name__ == ErrPCalibration.__name__,
            f"...et le moteur sait la JOUER : son runtime_cls est renseigné "
            f"({getattr(calib.runtime_cls, '__name__', None)})")
        chk(abs(calib.epoch_s - (_errp.ErrPRuntime.pre_s + _errp.ErrPRuntime.post_s)) < 1e-9,
            f"...et son epoch_s vaut la géométrie que le runtime PRÉLÈVE ({calib.epoch_s} s)")
        chk(ErrPCalibration.duree_protocole_s > 120.0,
            f"la durée du protocole est RENSEIGNÉE — laissée à 0, la console annoncerait « ≈ 0 min "
            f"» pour une séance de plusieurs minutes ({ErrPCalibration.duree_protocole_s:.0f} s)")
        chk(ErrPCalibration.n_perm is None,
            f"la classe de PRODUCTION ne saute pas le test de permutation : sans p-value, rien ne "
            f"distingue une AUC de 0,80 sur 20 essais d'un tirage chanceux "
            f"({ErrPCalibration.n_perm})")

        # --- 2. La géométrie est LUE sur le runtime de décodage, jamais redéclarée -------------
        plan, eeg, ts, verites = seance()
        moteur = _MoteurFactice(eeg, ts)
        rt = _CalibRapide(_errp.SPEC, {}, moteur, dossier=dossier)
        chk(rt.runtime_cls_du_mode is _errp.ErrPRuntime,
            f"la calibration DÉSIGNE le runtime de DÉCODAGE — c'est de lui, et de nulle part "
            f"ailleurs, que vient sa géométrie d'époque ({rt.runtime_cls_du_mode})")
        chk(rt.pre_s == _errp.ErrPRuntime.pre_s and rt.post_s == _errp.ErrPRuntime.post_s,
            f"...et elle en LIT pre_s/post_s ({rt.pre_s}, {rt.post_s})")

        # --- 3. L'étiquette voyage sur le feedback LUI-MÊME, et `False` en est une -------------
        joue(rt, moteur, plan)
        chk(rt.phase == "fini", f"la séance aboutit ({rt.phase}, problème={rt.probleme!r})")
        etiquettes = [lab for _e, lab in rt._enregistre] if rt._enregistre else []
        chk(len(etiquettes) == len(plan) and etiquettes == verites,
            f"une époque par feedback, étiquetée par le champ `error` de CE feedback — il n'y a "
            f"pas de `cue` dans ce mode ({len(etiquettes)} pour {len(plan)})")
        chk(etiquettes.count(False) > 0 and etiquettes.count(True) > 0,
            f"...et les DEUX classes sont enregistrées : `False` est une étiquette VALIDE, pas un "
            f"« pas d'époque ». Un `if not etiquette` dans le socle ferait disparaître EN SILENCE "
            f"les {etiquettes.count(False)} époques correctes, soit la majorité de la séance")

        res = rt.resultat or {}
        chk(res.get("n_essais") == len(plan),
            f"toutes les époques annoncées partent à l'entraînement ({res.get('n_essais')})")
        chk(res.get("n_erreurs") == sum(verites),
            f"...dont le bon nombre d'erreurs ({res.get('n_erreurs')} pour {sum(verites)})")

        # --- 4. L'AUC est hors-pli, la permutation est CALCULÉE --------------------------------
        chk(res.get("auc") is not None and 0.0 <= res["auc"] <= 1.0,
            f"l'AUC est une probabilité ({res.get('auc')})")
        chk(res.get("perm_p") is not None and 0.0 <= res["perm_p"] <= 1.0,
            f"le test de permutation est CALCULÉ et rendu — c'est lui qui distingue une AUC d'un "
            f"tirage chanceux, et le projet en fait une règle ({res.get('perm_p')})")
        # ⚠️ Le plancher de la p-value vaut `1/(n_perm + 1)` : à trop peu de permutations, AUCUNE
        # séance ne peut ressortir significative, et cet autotest n'exercerait qu'une moitié du
        # verdict en restant vert. On l'exige explicitement plutôt que de le supposer.
        chk(1.0 / (_CalibRapide.n_perm + 1) < PERM_ALPHA,
            f"...avec assez de permutations pour que « significatif » soit ATTEIGNABLE : le "
            f"plancher est 1/(n+1) = {1.0 / (_CalibRapide.n_perm + 1):.3f}, sous "
            f"{PERM_ALPHA}")
        chk(res.get("perm_p") < PERM_ALPHA,
            f"...et sur une séance où l'onde est VRAIMENT là, la permutation la déclare "
            f"significative ({res.get('perm_p')})")
        chk(res.get("tpr") is not None and res.get("tnr") is not None,
            f"le point de fonctionnement est rendu à côté ({res.get('tpr')}, {res.get('tnr')})")
        chk(abs(res.get("hasard", 0.0) - 0.5) < 1e-9,
            f"le niveau du hasard d'une AUC est 0,5 — pas 1/6 comme la sélection du P300 "
            f"({res.get('hasard')})")
        chk(res.get("verdict") == verdict(res.get("auc"), res.get("perm_p")),
            f"le verdict est recalculé depuis l'AUC ET sa significativité, jamais depuis le "
            f"TPR/TNR — qui sont mesurés au seuil qui les a choisis ({res.get('verdict')!r})")

        # Le contenu, pas seulement la plomberie : sur ce signal, l'AUC doit battre le hasard.
        # Sans cette ligne, un épochage décalé de 200 ms passerait tout le reste.
        chk(res.get("auc", 0.0) > 0.5,
            f"...et sur de l'ErrP synthétique, l'AUC BAT le hasard — un épochage décalé ne le "
            f"pourrait pas ({res.get('auc')})")

        # --- 5. La phrase d'honnêteté est celle de l'ErrP, et elle dit les TROIS choses --------
        phrase = res.get("honnetete", "")
        chk(bool(phrase), "le résultat porte SA phrase d'honnêteté")
        chk("une erreur sur deux" in phrase.lower() and "sur sept" in phrase.lower(),
            "...et elle dit ce que ce détecteur attrape VRAIMENT au réglage par défaut (une erreur "
            "sur deux, une bonne commande annulée sur sept)")
        chk("optimiste" in phrase.lower() and "0,776" in phrase,
            "...que ces deux taux sont eux-mêmes OPTIMISTES — le seuil a été choisi en regardant "
            "les scores qui le mesurent, donc le TNR dépasse sa cible PAR CONSTRUCTION")
        chk("cinq" in phrase.lower() and "dix" in phrase.lower(),
            "...et ce qu'il est NORMAL d'observer : sur dix erreurs délibérées, en attraper cinq "
            "est le résultat attendu")
        chk("trois classes" not in phrase and "40 %" not in phrase
            and "leave-one-round-out" not in phrase,
            "...et ce n'est celle NI du Motor Imagery NI du P300 : ni trois classes, ni une "
            "sélection parmi six cibles")

        # --- 6. Le modèle est écrit dans le dossier DONNÉ, et jamais dans le vrai data/ --------
        chk(res.get("modele", "").startswith(dossier),
            f"le modèle est écrit dans le dossier reçu ({res.get('modele')})")
        chk(nom_retenu(res.get("modele", "")).startswith("errp_model_")
            and res.get("modele", "").endswith(".joblib"),
            f"...sous un nom HORODATÉ, jamais fixe : `data/errp_model.joblib` est la trace casque "
            f"du 24 juillet ({_os.path.basename(res.get('modele', ''))})")
        chk(bool(res.get("enregistrement")) and _os.path.exists(res["enregistrement"]),
            f"...et les époques BRUTES sont archivées à côté ({res.get('enregistrement')})")

        from core import errp_models

        # ⚠️ Ce qui sort d'une calibration est un CANDIDAT, et il ne doit être proposé à PERSONNE
        # tant que quelqu'un ne l'a pas retenu. Le préfixe le rend invisible au motif de
        # découverte — sans lui, un candidat oublié dans son dossier temporaire redeviendrait « le
        # modèle chargeable le plus récent » le jour où ce dossier serait scanné.
        chk(_os.path.basename(res.get("modele", "")).startswith(CALIB_CANDIDAT_PREFIXE),
            f"le modèle produit est un CANDIDAT, marqué comme tel "
            f"({_os.path.basename(res.get('modele', ''))})")
        chk(errp_models.modeles_disponibles(dossier) == [],
            f"...donc INVISIBLE au motif `{errp_models.MOTIF}` : rien à découvrir dans son dossier "
            f"({errp_models.modeles_disponibles(dossier)})")
        chk(fnmatch(nom_retenu(res.get("modele", "")), errp_models.MOTIF),
            f"...mais le nom sous lequel il sera RETENU, lui, correspond au motif — sinon le "
            f"modèle enregistré ne serait jamais proposé ({nom_retenu(res.get('modele', ''))})")

        # --- 6bis. Le modèle produit est ACCEPTÉ par le mode qui décodera avec -----------------
        # `ErrPRuntime.__init__` refuse un modèle dont la géométrie d'époque n'est pas celle qu'il
        # prélève (`_desaccord_geometrie`), et un modèle sans scores hors-pli (`_sans_scores_oof`).
        # C'est le contrôle SYMÉTRIQUE de tout ce fichier : on a vérifié que la calibration découpe
        # comme le décodage, on vérifie ici que ce qu'elle en SAUVEGARDE le dit aussi. Sans cette
        # ligne, `ErrPModel(fs=fs)` construit avec ses défauts passait tous les tests, et le premier
        # changement de `ErrPRuntime.pre_s` aurait fait refuser, au démarrage du mode, le modèle
        # qu'on venait tout juste de calibrer — en accusant le modèle.
        class _MoteurDuMode:
            acq = _FausseAcq()
            instance = "selftest"

        try:
            decodeur = _errp.ErrPRuntime(_errp.SPEC,
                                         {"model": res["modele"], "stream_in": "x",
                                          "tnr_target": 0.85},
                                         _MoteurDuMode())
            refus = None
        except ValueError as e:
            decodeur, refus = None, str(e)
        chk(decodeur is not None,
            f"le modèle sorti de cette calibration est ACCEPTÉ par le mode qui décodera avec "
            f"({refus or 'aucun refus'})")
        chk(refus is not None or (decodeur.model.pre_s == _errp.ErrPRuntime.pre_s
                                  and decodeur.model.post_s == _errp.ErrPRuntime.post_s
                                  and decodeur.model.fs == _FausseAcq.fs),
            f"...parce qu'il PORTE la géométrie avec laquelle ses époques ont été découpées, pas "
            f"un défaut de configuration ({getattr(decodeur, 'model', None)})")

        # --- 7. Une séance trop pauvre est REFUSÉE, en disant quoi faire -----------------------
        plan_court, eeg_c, ts_c, _v = seance(n_pas=6, graine=1)
        moteur_c = _MoteurFactice(eeg_c, ts_c)
        rt_court = _CalibRapide(_errp.SPEC, {}, moteur_c, dossier=dossier)
        joue(rt_court, moteur_c, plan_court)
        chk(rt_court.phase == "annule" and "trop pauvre" in rt_court.probleme,
            f"une séance trop pauvre refuse d'entraîner ({rt_court.phase}, {rt_court.probleme})")
        chk("Refais une séance plus longue" in rt_court.probleme,
            f"...en disant quoi faire ({rt_court.probleme})")
        chk(len(_glob.glob(_os.path.join(dossier, "*errp_model*.joblib"))) == 1,
            f"...et n'écrit AUCUN second fichier de modèle "
            f"({_glob.glob(_os.path.join(dossier, '*errp_model*.joblib'))})")

        # Une calibration sans dossier ne retombe PAS sur `data/` : elle refuse, en disant qui
        # aurait dû lui en donner un.
        rt_sans = _CalibRapide(_errp.SPEC, {}, _MoteurFactice(eeg, ts))
        try:
            rt_sans.dossier_ou_lever()
            refus_dossier = None
        except ValueError as e:
            refus_dossier = str(e)
        chk(refus_dossier is not None and "data/" in refus_dossier,
            f"sans dossier, la calibration REFUSE au lieu de retomber sur data/ "
            f"({(refus_dossier or 'aucun refus')[:70]}…)")

        # --- 8. LA GARDE DE CETTE TÂCHE : un feedback SANS étiquette est refusé ----------------
        # C'est le marqueur d'une fenêtre lancée en mode DÉCODAGE. L'étiqueter « correct » par
        # défaut — la classe majoritaire, le choix qui vient naturellement — glisserait ~28 % de
        # vraies erreurs dans les bonnes commandes, et le modèle apprendrait à ne jamais rien
        # détecter. Rien ne le signalerait : le bon NOMBRE d'époques arriverait à l'entraînement.
        moteur_r = _MoteurFactice(eeg, ts)
        rt_r = _CalibRapide(_errp.SPEC, {}, moteur_r, dossier=dossier)
        rt_r.tick(moteur_r, moteur_r.t0)
        rt_r.encaisser(moteur_r, moteur_r.t0,
                       {"mode": "errp", "event": "calib_start", "trials": 6})
        rt_r.tick(moteur_r, moteur_r.t0 + rt_r.warmup_s + 0.1)
        t_r = moteur_r.t0 + 20.0
        rt_r.encaisser(moteur_r, t_r, {"mode": "errp", "event": "feedback"})
        chk(rt_r.essai == 0 and rt_r._refus == 1,
            f"un `feedback` NU (celui d'une fenêtre qui DÉCODE) est refusé, jamais étiqueté "
            f"« correct » par défaut ({rt_r.essai} enregistrée(s), {rt_r._refus} refus)")
        rt_r.encaisser(moteur_r, t_r + 0.1, {"mode": "errp", "event": "feedback", "error": 1})
        chk(rt_r.essai == 0 and rt_r._refus == 2,
            f"`error: 1` non plus : une étiquette se lit, elle ne se DEVINE pas — l'inverser sur "
            f"toute une séance ne lèverait aucune erreur ({rt_r._refus} refus)")
        rt_r.encaisser(moteur_r, t_r + 0.2, {"mode": "errp", "event": "feedback", "error": "true"})
        chk(rt_r.essai == 0 and rt_r._refus == 3,
            f"ni la chaîne « true » ({rt_r._refus} refus)")
        rt_r.encaisser(moteur_r, t_r + 0.3, {"mode": "errp", "event": "run_start"})
        chk(rt_r.essai == 0 and rt_r._refus == 3,
            f"un événement INCONNU, lui, est ignoré sans être compté comme un refus : le protocole "
            f"grandira ({rt_r._refus} refus)")
        rt_r.encaisser(moteur_r, t_r + 0.4, {"mode": "errp", "event": "feedback", "error": False})
        rt_r.encaisser(moteur_r, t_r + 1.9, {"mode": "errp", "event": "feedback", "error": True})
        chk([lab for _e, lab in rt_r._enregistre] == [False, True],
            f"...et un feedback bien formé passe, dans les deux valeurs "
            f"({[lab for _e, lab in rt_r._enregistre]})")
        chk(rt_r.state(now=t_r)["refus_etiquette"] == 3,
            f"les refus sont VISIBLES dans l'instantané : sinon une fenêtre lancée en mode "
            f"décodage ne se voit que dans un terminal que personne ne lit "
            f"({rt_r.state(now=t_r)['refus_etiquette']})")

        # --- 9. Les blocs de la validation croisée sont des tranches CONTIGUËS -----------------
        # Sans groupes, `_cv_splitter` mélange les époques et deux pas voisins de la même course
        # se retrouvent l'un en entraînement, l'autre en test : l'AUC monte pour une raison qui
        # n'a rien à voir avec l'ErrP.
        g = groupes_contigus(20, blocs=5)
        chk(g == sorted(g) and len(set(g)) == 5 and g.count(0) == 4,
            f"20 époques en 5 blocs contigus de 4 ({g})")
        chk(groupes_contigus(3, blocs=5) == [0, 1, 2],
            f"...et une séance plus courte que le nombre de blocs n'en fabrique pas de vides "
            f"({groupes_contigus(3, blocs=5)})")
        chk(groupes_contigus(0, blocs=5) == [],
            "...ni ne lève sur une séance vide (le refus d'entraîner s'en charge, plus haut)")

        # --- 10. Le verdict : une AUC NON significative n'est pas une AUC faible ---------------
        chk("NON SIGNIFICATIF" in verdict(0.85, perm_p=0.4),
            f"une belle AUC dont la permutation dit p=0,4 est déclarée INDISTINGUABLE DU HASARD — "
            f"pas « bonne » ({verdict(0.85, perm_p=0.4)[:50]}…)")
        chk("contact" in verdict(0.85, perm_p=0.4),
            "...et le refus dit que ce n'est PAS un problème de contact : rallonger la séance et "
            "resaliner ne réparent pas la même panne")
        chk("FAIBLE" in verdict(0.55, perm_p=0.01) and "saline" in verdict(0.55, perm_p=0.01),
            f"une AUC basse mais significative, elle, s'attaque par le SIGNAL "
            f"({verdict(0.55, perm_p=0.01)[:40]}…)")
        chk(verdict(None) and "non mesurée" in verdict(None),
            f"et une AUC absente le dit ({verdict(None)})")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    chk(empreinte_dossier() == empreinte_avant,
        "AUCUN fichier n'a bougé dans le vrai `data/` — il porte des enregistrements EEG d'une "
        "personne identifiable, et son modèle le plus récent est celui que le moteur ÉLIT")

    print(f"[errp-calib] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
