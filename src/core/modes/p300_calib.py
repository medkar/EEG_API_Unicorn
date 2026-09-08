"""La calibration P300 : la fenêtre mène le protocole, le MOTEUR entraîne.

Première sous-classe concrète de `MarkerCalibrationRuntime` (`core/modes/marker_calib.py`, à lire
avant celui-ci). Elle ne fournit que les trois choses que le socle réclame :

  1. `runtime_cls_du_mode = P300Runtime` — la géométrie d'époque est LUE là, jamais redéclarée ici ;
  2. `_etiquette(ts, marqueur)` — le `cue` porte la cible attendue, chaque `flash` délimite une
     époque, étiquetée cible/non-cible selon qu'il porte cette cible-là ;
  3. `_entrainer(enregistre, fs)` — xDAWN + Riemann, la sélection en leave-one-round-out, et une
     sauvegarde HORODATÉE.

⚠️ **Ce qui change par rapport à l'ancien chemin**, et c'est le point du chantier : les époques
d'entraînement étaient découpées par `research/p300_calibrate.py` (l'horloge de l'appli pygame) et
celles du décodage par le moteur (marqueurs LSL, `time_correction`). Deux chemins, aucun test pour
les accorder. Ici il n'y en a plus qu'UN : le socle prélève par `epoch_from_stream`, avec les
`pre_s`/`post_s` lus sur `P300Runtime` — littéralement l'appel que `core/modes/p300.py` fait en
décodant.

⚠️ **CE FICHIER NE TESTE PAS L'ALIGNEMENT, et il ne le peut pas.** Son autotest juge un décodage,
donc il tolère ce qu'un décodage tolère : MESURÉ, translater l'époque de 150 ms (37 échantillons)
laisse ici la sélection à 6/6 et l'AUC à 94 % — tout reste VERT. C'est exactement la panne
« indiscernable d'un succès » du projet. L'alignement est gardé UN CRAN PLUS BAS, par
`python src/core/modes/marker_calib.py`, qui compare échantillon par échantillon les deux chemins
d'épochage sur deux géométries : la même mutation y rougit sur cinq assertions. Ne pas déplacer ce
garde-là ici en croyant le rapprocher de son sujet — il n'y survivrait pas.

⚠️ **L'ÉTIQUETTE VOYAGE AVEC L'ÉPOQUE, dans le même tuple**, et ce n'est pas un détail de style.
La tentation est d'empiler `flashed`/`groups` dans des listes parallèles au moment où le marqueur
arrive — c'est ce que faisait l'ancienne calibration. Mais le socle n'enregistre PAS toujours :
quand l'époque déborde du tampon (`epoch_from_stream` rend None), il compte une perte et passe. Des
listes parallèles se décaleraient alors d'un cran pour tout le reste de la séance, chaque époque
apprenant l'étiquette de la suivante — un modèle entraîné sur du bruit, avec des scores plausibles.
Même famille que la garde de `core/modes/p300.py::_encaisser_flash` (« les deux listes s'allongent
ENSEMBLE »), fermée ici par la STRUCTURE plutôt que par une garde.

⚠️ **`P300Runtime` est importé TARDIVEMENT, dans la propriété, et ce n'est pas de la coquetterie.**
`core/modes/p300.py` importe ce module-ci (son `Calib` porte `runtime_cls=P300Calibration`) : un
import en tête d'ici refermerait un CYCLE. Un cycle module-à-module survit tant que chacun est
importé par son nom de paquet — mais pas quand l'un des deux fichiers est lancé DIRECTEMENT :
Python le charge alors sous le nom `__main__`, la garde de `sys.modules` ne joue plus, et le second
exemplaire se retrouve à demander un nom pas encore défini. MESURÉ, avant d'écrire cette ligne :
`python src/core/modes/p300.py` sortait sur `ImportError: cannot import name 'BRIEFING' from
partially initialized module` — c'est-à-dire l'autotest du mode P300, l'un des six que la recette
demande. Différer l'import supprime l'arête au lieu de l'ordonner : plus aucun ordre de chargement
ne peut échouer.

Autotest :
    python src/core/modes/p300_calib.py
"""

import os as _os
import sys as _sys
import time as _time
from collections import namedtuple

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
import numpy as np  # noqa: E402

from core.config import (CALIB_CANDIDAT_PREFIXE, P300_CAL_ROUNDS,  # noqa: E402
                         P300_EPOCH_S, P300_FLASH_OFF_FR, P300_FLASH_ON_FR, P300_MIN_REPS,
                         P300_N_TARGETS, P300_PAUSE_MANCHE_S, P300_PRE_S, P300_REPS,
                         use_utf8_console)
from core.modes.marker_calib import MarkerCalibrationRuntime  # noqa: E402
from core.p300_decoder import NONTARGET, TARGET, P300Model  # noqa: E402
# ⚠️ `core.modes.p300` n'est PAS importé ici : cf. le ⚠️ de la docstring du module. Il l'est dans
# `P300Calibration.runtime_cls_du_mode`, une fois le programme lancé.

# Le rafraîchissement de RÉFÉRENCE, et il ne sert QU'À ESTIMER une durée. `core` ne voit aucun
# écran : c'est la fenêtre qui mesure le vrai rafraîchissement, et le SOA réel en dépend
# (P300_FLASH_ON_FR + P300_FLASH_OFF_FR frames). 60 Hz est la valeur sous laquelle le protocole a
# été réglé (cf. `core/config.py`). Se tromper ici ne fausse RIEN d'autre que le « ≈ N min »
# affiché par la console — jamais un décodage — mais un étudiant à qui l'on annonce 2 min pour une
# séance de 5 ne s'assied pas de la même façon.
REFRESH_REFERENCE_HZ = 60.0
SOA_REFERENCE_S = (P300_FLASH_ON_FR + P300_FLASH_OFF_FR) / REFRESH_REFERENCE_HZ

# Ce que l'étudiant lit AVANT de commencer, sur la page de la console. Le protocole lui-même
# s'affiche dans la fenêtre de stimulus : ce qui est ici est ce qu'il faut avoir compris avant.
BRIEFING = (
    "Une cible est CERCLÉE en bleu : c'est celle qu'il faut fixer pendant toute la manche.",
    "Les six cibles s'allument une à une, en bref éclair, dans le désordre.",
    "COMPTE mentalement les éclairs de TA cible. Le comptage n'est pas un gadget : c'est la",
    "tâche mentale qui rend le flash attendu saillant. Sans elle, l'onde s'effondre.",
    "Reste immobile et cligne le moins possible PENDANT les éclairs — cligne entre les manches.",
    "La cible à fixer change à chaque manche, et c'est la FENÊTRE de stimulus qui l'annonce.",
)

# La phrase d'honnêteté du P300 — PROPRE à ce mode. Celle du Motor Imagery parle de 40 % à trois
# classes et de validation croisée par essai : la recopier ici serait faux deux fois (ni le même
# nombre de classes, ni la même unité de regroupement).
HONNETETE = (
    "Deux chiffres, et ils ne disent pas la même chose. L'AUC cible/non-cible est mesurée par "
    "validation croisée PAR MANCHE (GroupKFold) : aucune époque d'une manche ne sert à la fois à "
    "entraîner et à tester. Repère du projet, mesuré sur une personne : 0,71 sur 576 époques — "
    "c'est ce que VAUT un P300 mono-essai en électrodes sèches, pas un échec. Le chiffre qui "
    "décide, lui, est la SÉLECTION en leave-one-round-out (« la cible désignée est-elle "
    "retrouvée ? »), parce que c'est la question que l'utilisateur pose vraiment. Une ou deux "
    "erreurs sur six sélections sont ATTENDUES : le P300 se lit par MOYENNAGE sur les "
    "répétitions, pas par époque."
)

# Les verdicts portent sur la SÉLECTION (hasard : 1/6 ≈ 17 %), jamais sur l'AUC. Un seuil sur
# l'AUC dirait « faible » d'une séance dont toutes les sélections tombent juste — l'AUC mesure une
# époque isolée, la sélection mesure ce qu'on en fait après moyennage.
VERDICTS = ((0.80, "EXCELLENT"), (0.60, "UTILISABLE"),
            (0.00, "FAIBLE — ré-essaie : saline les électrodes, FIXE la cible cerclée et COMPTE "
                   "ses éclairs (sans le comptage, l'onde s'effondre)"))

# Les deux planchers en dessous desquels on REFUSE d'entraîner, plutôt que de produire un modèle
# que rien ne distingue d'un bon dans la liste de la console.
# ⚠️ `MIN_MANCHES = 2` n'est pas « deux manches suffisent » : c'est le point sous lequel les deux
# mesures deviennent littéralement incalculables — `GroupKFold` ne peut pas former deux plis avec
# un seul groupe, et le leave-one-round-out n'a aucune manche à tenir à l'écart. Une séance à deux
# manches passera donc, avec des chiffres très bruités : c'est le rôle du verdict de le dire, pas
# celui du refus.
MIN_MANCHES = 2
MIN_EPOQUES = P300_N_TARGETS * P300_MIN_REPS

# Paliers auxquels un marqueur refusé se DIT. Même motif que `core/modes/p300.py::_PALIERS_REFUS`
# et que les compteurs du moteur : une ligne par ordre de grandeur. Le dire à chaque flash
# noierait le terminal (des centaines par séance), le dire une fois laisserait une fenêtre qui
# numérote MAL TOUTES ses cibles — l'erreur la plus banale — n'imprimer qu'une ligne.
_PALIERS_REFUS = (1, 10, 100, 1000)


class Etiquette(namedtuple("Etiquette", "flashee manche attendue")):
    """Ce qu'on sait d'une époque au moment où on la prélève, en UN objet.

    `flashee` : l'indice de la cible qui vient de s'allumer. `manche` : le numéro de la manche en
    cours (le GROUPE de la validation croisée). `attendue` : la cible que le `cue` de cette
    manche-là a désignée. `cible` s'en déduit — et c'est tout l'intérêt de les transporter
    ensemble : rien ne peut se décaler entre elles.
    """

    @property
    def est_cible(self):
        return self.flashee == self.attendue


def verdict(selection):
    """Le verdict, depuis le TAUX DE SÉLECTION. None quand il n'a pas été mesuré."""
    if selection is None:
        return ("justesse de sélection non mesurée : pas assez de manches pour en tenir une à "
                "l'écart")
    for seuil, texte in VERDICTS:
        if selection >= seuil:
            return texte
    return VERDICTS[-1][1]


def horodatage(maintenant=None):
    """`AAAAMMJJ_HHMMSS`, le format que portent déjà les modèles P300 du dépôt.

    ⚠️ `maintenant or _time.time()` serait faux : `0.0` (l'epoch Unix) est un instant VALIDE et
    pourtant falsy — même piège que dans `core/modes/mi_calib.py`, où il est documenté au long.
    """
    return _time.strftime("%Y%m%d_%H%M%S",
                          _time.localtime(_time.time() if maintenant is None else maintenant))


def chemins_libres(dossier, n_manches, prefixe=""):
    """(chemin du modèle, chemin de l'enregistrement), les DEUX garantis libres au retour.

    Jumeau exact de `core/modes/mi_calib.py::_chemins_libres`, et pour la même raison : le format
    du nom a une résolution d'une SECONDE, `save`/`savez` écrasent sans rien demander, et deux
    séances qui finissent la même seconde produiraient sinon les mêmes deux fichiers. On avance
    d'une seconde tant que l'un des deux existe — quelques secondes d'écart sur l'estampille
    coûtent infiniment moins qu'une séance perdue.

    Le motif `p300_model*.joblib` est celui que `core/p300_models.MOTIF` cherche : s'en écarter
    produirait un modèle que la console ne proposerait jamais.

    `prefixe` : `CALIB_CANDIDAT_PREFIXE` quand ce qu'on écrit est un CANDIDAT — un fichier qui
    ne doit correspondre à aucun motif de découverte tant que personne ne l'a retenu (cf. le
    commentaire de cette constante dans `core/config.py`). Défaut `""` : l'autre appelant,
    `archive/p300_calibrate.py`, écrit directement dans `data/` un modèle définitif, et doit
    garder le nom que `p300_models` cherche.
    """
    maintenant = _time.time()
    while True:
        stamp = horodatage(maintenant)
        chemin_modele = _os.path.join(dossier, f"{prefixe}p300_model_{stamp}.joblib")
        chemin_npz = _os.path.join(dossier,
                                   f"{prefixe}p300_calib_{stamp}_n{int(n_manches):02d}.npz")
        if not _os.path.exists(chemin_modele) and not _os.path.exists(chemin_npz):
            return chemin_modele, chemin_npz
        maintenant += 1.0


def selection_loro(epochs, flashed, groups, cues, fs, pre_s=P300_PRE_S, post_s=P300_EPOCH_S):
    """Justesse de SÉLECTION en leave-one-round-out : pour chaque manche tenue à l'écart, le
    modèle appris sur les autres retrouve-t-il la cible désignée ? Rend `(ok, total)`.

    C'est LA métrique du P300 : l'AUC dit ce que vaut une époque isolée, celle-ci dit ce que vaut
    la réponse rendue à l'utilisateur, après moyennage sur les répétitions.

    Montée telle quelle depuis `research/p300_calibrate.py` (elle y était déjà écrite et validée
    au casque) : `core` en a besoin maintenant que c'est le moteur qui entraîne.
    """
    epochs, flashed, groups = np.asarray(epochs), np.asarray(flashed), np.asarray(groups)
    y = np.array([TARGET if flashed[i] == cues[groups[i]] else NONTARGET
                  for i in range(len(groups))])
    ok = tot = 0
    for r in sorted(set(groups.tolist())):
        tr = groups != r
        if len(set(y[tr].tolist())) < 2:
            continue
        m = P300Model(fs=fs, pre_s=pre_s, post_s=post_s).fit(epochs[tr], y[tr], compute_cv=False)
        te = np.where(groups == r)[0]
        by = {}
        for i in te:
            by.setdefault(int(flashed[i]), []).append(epochs[i])
        pick, _ = m.select(by)
        ok += int(pick == cues[r])
        tot += 1
    return ok, tot


def entrainer(epochs, labels, flashed, groups, cues, fs, chemin_modele, chemin_npz=None,
              evaluer=True, pre_s=P300_PRE_S, post_s=P300_EPOCH_S):
    """Entraîne, évalue, écrit — et rend le dict que la console affiche. LÈVE si la séance est
    trop pauvre pour valoir un modèle.

    `chemin_modele` est EXPLICITE, jamais deviné ici : c'est l'appelant qui décide où écrire (la
    calibration du moteur passe son `self.dossier`, `research/p300_calibrate.py` passe son
    `save_path`). Un défaut fixe est précisément ce qui a fait perdre les modèles du MI.

    `chemin_npz` (facultatif) archive les époques BRUTES à côté du modèle. C'est ce qui a sauvé le
    P300 quand ses modèles sont devenus illisibles : on ré-entraîne depuis le disque au lieu de
    refaire une séance (cf. `core/p300_models.py`). Le `.npz` est écrit AVANT le `.joblib` — si le
    disque est plein, l'exception remonte avant que le modèle n'existe, et aucun modèle orphelin
    ne se retrouve ÉLU comme le plus récent chargeable.

    `evaluer=False` saute la validation croisée ET le leave-one-round-out : ~2 N entraînements de
    moins, pour un smoke qui vérifie le câblage et non la justesse.

    ⚠️ **`pre_s`/`post_s` sont ceux avec lesquels les époques ont RÉELLEMENT été découpées**, pas
    une valeur par défaut reprise de la configuration. Le modèle les porte en attributs, et
    `core/modes/p300.py::_desaccord_geometrie` les COMPARE à ce que le runtime prélève avant
    d'accepter de décoder avec. Les laisser par défaut marcherait tant que personne ne touche à
    `P300Runtime.pre_s` — et le jour où quelqu'un y touche, le mode refuserait le modèle qu'on
    vient tout juste de calibrer, en accusant le modèle. L'appelant qui a découpé les époques est
    le seul à savoir avec quoi.
    """
    epochs = np.asarray(epochs, dtype=float)
    labels = np.asarray(labels, dtype=int)
    flashed = np.asarray(flashed, dtype=int)
    groups = np.asarray(groups, dtype=int)
    manches = sorted(set(groups.tolist()))

    if len(epochs) < MIN_EPOQUES or len(manches) < MIN_MANCHES or len(set(labels.tolist())) < 2:
        raise ValueError(
            f"séance trop pauvre pour entraîner : {len(epochs)} époque(s) sur "
            f"{len(manches)} manche(s), {len(set(labels.tolist()))} classe(s) représentée(s) — "
            f"il en faut au moins {MIN_EPOQUES} sur {MIN_MANCHES} manches, cible ET non-cible. "
            f"Refais une séance plus longue, et vérifie la liaison du casque : des époques "
            f"perdues en cours de route (le journal du moteur les compte) donnent exactement "
            f"cette allure")

    modele = P300Model(fs=fs, pre_s=pre_s, post_s=post_s).fit(epochs, labels, groups=groups,
                                                              compute_cv=evaluer)
    sel_ok, sel_tot = (selection_loro(epochs, flashed, groups, cues, fs, pre_s, post_s)
                       if evaluer else (0, 0))
    selection = (sel_ok / sel_tot) if sel_tot else None

    _os.makedirs(_os.path.dirname(chemin_modele) or ".", exist_ok=True)
    if chemin_npz:
        # `pre_s`/`post_s` sont ARCHIVÉS avec les époques : sans eux, un ré-entraînement futur ne
        # saurait pas où tombe l'onset dans les échantillons qu'il relit.
        np.savez(chemin_npz, epochs=epochs, labels=labels, flashed=flashed, groups=groups,
                 cues=np.asarray(cues), fs=fs, pre_s=pre_s, post_s=post_s)
    modele.save(chemin_modele)

    auc = modele.cv_auc_
    verdict_txt = verdict(selection)
    hasard = 1.0 / P300_N_TARGETS
    auc_txt = "non mesurée" if auc is None else f"{auc * 100:.1f}%"
    sel_txt = ("non mesurée" if selection is None
               else f"{sel_ok}/{sel_tot} = {selection * 100:.0f}% (hasard {hasard * 100:.0f}%)")
    print(f"[p300-calib] {len(epochs)} époques sur {len(manches)} manches — "
          f"AUC cible/non-cible (par manche) {auc_txt}")
    print(f"[p300-calib] SÉLECTION (leave-one-round-out) : {sel_txt} — {verdict_txt}")
    print(f"[p300-calib] modèle : {chemin_modele}")
    if chemin_npz:
        print(f"[p300-calib] enregistrement : {chemin_npz}")
    return {
        "modele": chemin_modele,
        "nom": _os.path.basename(chemin_modele),
        "enregistrement": chemin_npz,
        "n_essais": int(len(epochs)),
        "n_manches": len(manches),
        "auc": None if auc is None else float(auc),
        "selection": selection,
        "selection_ok": int(sel_ok),
        "selection_total": int(sel_tot),
        "hasard": hasard,
        "verdict": verdict_txt,
        "honnetete": HONNETETE,
    }


def entrainer_dans(dossier, epochs, labels, flashed, groups, cues, fs, evaluer=True,
                   pre_s=P300_PRE_S, post_s=P300_EPOCH_S, prefixe=""):
    """`entrainer`, mais c'est le DOSSIER qu'on donne : les deux noms de fichiers sont horodatés
    et garantis libres (`chemins_libres`). C'est la porte de la calibration du moteur.

    `prefixe` passe tel quel à `chemins_libres` — voir sa docstring.
    """
    chemin_modele, chemin_npz = chemins_libres(dossier, len(cues), prefixe=prefixe)
    return entrainer(epochs, labels, flashed, groups, cues, fs,
                     chemin_modele=chemin_modele, chemin_npz=chemin_npz, evaluer=evaluer,
                     pre_s=pre_s, post_s=post_s)


class P300Calibration(MarkerCalibrationRuntime):
    """La calibration P300 vue du moteur : il écoute, il découpe, il entraîne. Rien d'autre.

    La ligne du temps (chauffe, essais, entraînement, les trois abandons) vient entièrement de
    `MarkerCalibrationRuntime`. Ce qui est ici est ce que le socle ne peut pas savoir : quels
    marqueurs délimitent une époque, ce qu'ils valent comme étiquette, et ce qu'on entraîne avec.
    """

    classes = ("non-cible", "cible")

    # Ce que la console affiche comme durée, hors chauffe. Calculée depuis `core/config.py` — le
    # moteur ne peut PAS la deviner, puisqu'il ne mène pas le protocole, mais il peut lire les
    # constantes sous lesquelles ce protocole a été réglé. Elle vaut pour les réglages PAR DÉFAUT
    # de la fenêtre : lancée avec d'autres, la fenêtre sera plus longue ou plus courte que ce
    # chiffre, et personne ne peut le savoir d'ici.
    duree_protocole_s = (P300_CAL_ROUNDS
                         * (P300_PAUSE_MANCHE_S + P300_REPS * P300_N_TARGETS * SOA_REFERENCE_S)
                         + P300_EPOCH_S)

    def __init__(self, spec, params, engine, rng=None, dossier=None):
        """`dossier` : où écrire — porté par `CalibrationRuntime` et SANS repli sur `DATA_DIR`.

        C'est le moteur qui le donne, et c'est son dossier CANDIDAT temporaire : une calibration
        qui choisissait elle-même écrivait dans `data/` AVANT d'annoncer sa précision, donc une
        séance ratée y devenait le modèle le plus récent — celui qui est proposé par défaut —
        sans que personne ait pu la refuser.
        """
        super().__init__(spec, params, engine, rng=rng, dossier=dossier)
        self._attendue = None    # la cible désignée par le dernier `cue` ; None avant le premier
        self._manche = -1        # le numéro de la manche en cours (le GROUPE de la CV)
        self._cues = []          # la cible désignée, manche par manche
        self._refus = 0          # marqueurs refusés : cible illisible, ou flash avant tout `cue`

    # --- ce que le socle demande ---------------------------------------------

    @property
    def runtime_cls_du_mode(self):
        """La classe qui DÉCODE le P300 — c'est d'elle que le socle lit `pre_s`/`post_s`.

        ⚠️ Le socle attend un attribut de classe ; c'est ici une PROPRIÉTÉ, pour l'unique raison
        expliquée en tête de module (le cycle d'import). Elle rend le même objet à chaque appel,
        et l'import d'un module déjà chargé n'est qu'une recherche dans un dictionnaire — c'est le
        même geste que l'import tardif de pyriemann dans `core/p300_decoder.py::build_pipe`.

        ⚠️ Conséquence à connaître avant d'écrire un test : `P300Calibration.runtime_cls_du_mode`
        (sur la CLASSE) rend l'objet propriété, pas `P300Runtime`. Ce qui compte se lit sur une
        INSTANCE, comme le socle le fait.
        """
        from core.modes.p300 import P300Runtime
        return P300Runtime

    def _etiquette(self, ts, marqueur):
        """`cue` MÉMORISE la cible de la manche ; `flash` délimite l'époque et l'étiquette.

        Deux marqueurs DIFFÉRENTS, et c'est pour ça que le socle a fait de ce point d'entrée une
        méthode à état plutôt qu'une table : la vérité-terrain n'arrive pas sur le marqueur qui
        délimite l'époque.

        ⚠️ `round_end` ne délimite aucune époque, mais il n'est pas ignoré pour autant : il FERME
        la manche, donc il oublie la cible désignée. C'est le seul garde contre un `cue` PERDU. Si
        on gardait la cible de la manche précédente, les flashs de la manche suivante seraient
        étiquetés sur elle : une manche entière apprise à l'envers, la vraie cible glissée dans la
        classe majoritaire, et rien pour le dire — ni exception, ni compteur, l'entraînement
        recevant exactement le bon nombre d'époques.
        """
        event = marqueur.get("event")

        if event == "cue":
            cible = self._cible_lisible(marqueur.get("target"), "cue")
            if cible is None:
                return None
            self._manche += 1
            self._attendue = cible
            self._cues.append(cible)
            self.classe = f"cible {cible}"
            return None

        if event == "round_end":
            self._attendue = None
            return None

        if event != "flash":
            return None

        if self._attendue is None:
            # Aucune cible désignée pour ce flash : soit la manche n'a pas encore été ouverte par
            # un `cue`, soit celui-ci s'est perdu (cf. le ⚠️ ci-dessus), soit la fenêtre décode au
            # lieu de calibrer. Ces époques n'ont AUCUNE vérité-terrain — les étiqueter
            # « non-cible » par défaut y glisserait de vraies cibles, en silence.
            self._refuse("un flash est arrivé sans qu'aucun « cue » n'ait désigné de cible pour "
                         "sa manche : cette époque n'a AUCUNE vérité-terrain")
            return None
        cible = self._cible_lisible(marqueur.get("target"), "flash")
        if cible is None:
            return None
        return Etiquette(cible, self._manche, self._attendue)

    def _cible_lisible(self, cible, quoi):
        """L'indice de cible, ou None en le disant. Même garde que `core/modes/p300.py`.

        `isinstance(cible, bool)` d'abord : en Python `bool` HÉRITE de `int`, donc `True` passe
        `isinstance(cible, int)` ET `0 <= True < 6`. Une fenêtre qui enverrait `true` en JSON — le
        mot-clé existe, et il est à une faute de frappe de `1` — verrait toutes ses époques
        étiquetées sur la cible 1.
        """
        if isinstance(cible, bool) or not isinstance(cible, int):
            self._refuse(f"« {cible!r} » n'est pas un indice de cible ({type(cible).__name__}) "
                         f"sur un marqueur « {quoi} »")
            return None
        if not 0 <= cible < P300_N_TARGETS:
            self._refuse(f"« {cible} » est hors de la plage attendue [0, {P300_N_TARGETS}[ "
                         f"sur un marqueur « {quoi} »")
            return None
        return cible

    def _refuse(self, detail):
        self._refus += 1
        if self._refus in _PALIERS_REFUS:
            print(f"[p300-calib] marqueur refusé ({self._refus} dans cette séance) : {detail} "
                  f"— vérifie la fenêtre de stimulus")

    def _entrainer(self, enregistre, fs):
        """Reconstitue les quatre tableaux depuis les étiquettes, puis entraîne dans `self.dossier`.

        Aucune liste parallèle n'a été tenue pendant la séance : tout est relu ici depuis les
        `Etiquette` transportées avec les époques (cf. le ⚠️ de la docstring du module).
        """
        epochs = [e for e, _lab in enregistre]
        labels = [TARGET if lab.est_cible else NONTARGET for _e, lab in enregistre]
        flashed = [lab.flashee for _e, lab in enregistre]
        groups = [lab.manche for _e, lab in enregistre]
        groups, cues = _renumerote(groups, self._cues)
        # `self.pre_s`/`self.post_s` : la géométrie avec laquelle le socle vient RÉELLEMENT de
        # découper ces époques, lue sur le runtime de décodage. Le modèle la porte, et le mode la
        # compare à la sienne avant d'accepter de décoder (`p300.py::_desaccord_geometrie`).
        # `CALIB_CANDIDAT_PREFIXE` : ce qui sort d'ici est un CANDIDAT, invisible à
        # `p300_model*.joblib` tant que personne ne l'a retenu (cf. `core/config.py`).
        return entrainer_dans(self.dossier_ou_lever(), epochs, labels, flashed, groups, cues, fs,
                              pre_s=self.pre_s, post_s=self.post_s,
                              prefixe=CALIB_CANDIDAT_PREFIXE)

    # --- l'état, pour l'afficheur -------------------------------------------

    def state(self, now=None):
        """Celui du socle, plus le compteur de marqueurs REFUSÉS.

        Sans lui, une fenêtre qui numérote mal ses cibles ne se voit que dans le terminal — et
        elle produit une séance entière d'époques mal étiquetées, donc un modèle qui décodera du
        bruit avec de belles probabilités.
        """
        base = super().state(now)
        base["refus_cible"] = self._refus
        return base


def _renumerote(groups, cues):
    """Renumérote les manches de 0 à n-1, en gardant `cues` aligné. Rend `(groups, cues)`.

    ⚠️ Nécessaire parce que `selection_loro` indexe `cues[groups[i]]` : une manche dont TOUTES les
    époques ont été perdues (tampon vidé, cibles refusées) laisserait un TROU dans la numérotation,
    et chaque manche suivante lirait la cible d'une AUTRE — vérité-terrain décalée, sans erreur.
    """
    ordre = sorted(set(groups))
    table = {ancien: nouveau for nouveau, ancien in enumerate(ordre)}
    return [table[g] for g in groups], [cues[a] for a in ordre]


def _selftest():
    """Une séance de calibration entière, jouée par des marqueurs sur un tampon EEG FABRIQUÉ.

    Aucun casque, aucune fenêtre, aucune attente réelle : l'horloge est donnée à `tick`, et le
    signal porte de vrais P300 synthétiques plantés AUX INSTANTS des flashs de cible — donc
    l'entraînement porte sur quelque chose, et le test peut juger le CONTENU, pas seulement la
    plomberie.
    """
    import glob as _glob
    import shutil
    import tempfile
    from fnmatch import fnmatch

    from core.config import empreinte_dossier, nom_retenu
    from core.modes import p300 as _p300
    from core.p300_decoder import synth_p300_epoch

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    FS = 250.0
    ROUNDS, REPS = 6, 3
    SOA = 0.15
    PAUSE = 1.0            # la pause entre manches, RACCOURCIE : le test n'en juge pas la durée

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

    def seance(rounds=ROUNDS, reps=REPS, graine=0, cible_de=None):
        """Le plan d'une séance : (marqueurs, tampon EEG, horodatages, cibles cuées).

        Le tampon est du bruit + un alpha partagé, DANS lequel on plante une réponse évoquée à
        l'instant de chaque flash de CIBLE. Les époques sont ensuite prélevées par le vrai chemin
        (`epoch_from_stream`, via le socle) : c'est ce qui rend ce test capable de dire quelque
        chose du décodage et pas seulement du câblage.
        """
        rng = np.random.default_rng(graine)
        cible_de = cible_de or (lambda r: r % P300_N_TARGETS)
        t0 = 1000.0
        plan, t, cues = [], t0 + 2.0, []
        for r in range(rounds):
            cue = cible_de(r)
            cues.append(cue)
            plan.append((t, {"mode": "p300", "event": "cue", "target": cue}))
            t += PAUSE
            for _ in range(reps):
                ordre = list(range(P300_N_TARGETS))
                rng.shuffle(ordre)
                for tgt in ordre:
                    plan.append((t, {"mode": "p300", "event": "flash", "target": tgt}))
                    t += SOA
            plan.append((t, {"mode": "p300", "event": "round_end"}))
            t += 0.5
        duree = t - t0 + 3.0

        ts = np.arange(t0, t0 + duree, 1.0 / FS)
        eeg = rng.normal(0.0, 1.6, (len(ts), 8))
        eeg += 0.8 * np.sin(2 * np.pi * 10 * (ts - t0))[:, None]        # un alpha de fond
        n_pre = int(round(P300_PRE_S * FS))
        n_post = int(round(P300_EPOCH_S * FS))
        for instant, m in plan:
            if m["event"] != "flash":
                continue
            manche = sum(1 for tt, mm in plan if mm["event"] == "cue" and tt <= instant) - 1
            if m["target"] != cues[manche]:
                continue
            i = int(np.searchsorted(ts, instant))
            onde = synth_p300_epoch(True, fs=FS, amp=1.4, noise=0.0, rng=rng)
            # `noise=0` ne suffit pas : `synth_p300_epoch` ajoute aussi un alpha. On ne garde que
            # la réponse évoquée, en soustrayant l'époque non-cible de la MÊME graine.
            eeg[i - n_pre:i + n_post] += onde[:n_pre + n_post] - onde[:n_pre + n_post].mean(axis=0)
        return plan, eeg, ts, cues

    def joue(rt, moteur, plan, pas=0.25):
        """Fait vivre la séance : `calib_start`, la chauffe, les marqueurs, `calib_end`."""
        t0 = moteur.t0
        rt.tick(moteur, t0)
        rt.encaisser(moteur, t0, {"mode": "p300", "event": "calib_start",
                                  "trials": sum(1 for _t, m in plan if m["event"] == "flash")})
        rt.tick(moteur, t0 + rt.warmup_s + 0.1)          # la chauffe s'écoule -> « essais »
        for instant, m in plan:
            rt.encaisser(moteur, instant, m)
        rt.encaisser(moteur, plan[-1][0] + 0.5, {"mode": "p300", "event": "calib_end"})
        t = t0 + rt.warmup_s + 0.2
        for _ in range(10):
            rt.tick(moteur, t)
            if rt.terminee:
                break
            t += pas
        return rt

    dossier = tempfile.mkdtemp(prefix="p300_calib_")
    empreinte_avant = empreinte_dossier()
    try:
        # --- 1. Le contrat : le mode déclare CETTE calibration, avec une époque dimensionnée ---
        # PAS `is P300Calibration` : lancé directement, ce fichier tourne en `__main__` avec SA
        # classe, et l'import de `core.modes.p300` juste au-dessus en a chargé une SECONDE sous le
        # nom de paquet. Mêmes valeurs, objet différent — l'artefact mécanique que
        # `core/modes/mi_calib.py` documente au long. On compare donc ce qui identifie.
        calib = _p300.SPEC.calibration
        chk(calib is not None and calib.kind == "fenetre" and calib.stimulus_id == "p300",
            f"le P300 déclare une calibration menée par une FENÊTRE ({calib!r})")
        chk(calib.runtime_cls is not None
            and calib.runtime_cls.__name__ == P300Calibration.__name__,
            f"...et le moteur sait la JOUER : son runtime_cls est renseigné "
            f"({getattr(calib.runtime_cls, '__name__', None)})")
        chk(abs(calib.epoch_s - (_p300.P300Runtime.pre_s + _p300.P300Runtime.post_s)) < 1e-9,
            f"...et son epoch_s vaut la géométrie que le runtime PRÉLÈVE ({calib.epoch_s} s)")
        chk(P300Calibration.duree_protocole_s > 60.0,
            f"la durée du protocole est RENSEIGNÉE — laissée à 0, la console annoncerait « ≈ 0 min "
            f"» pour une séance de plusieurs minutes ({P300Calibration.duree_protocole_s:.0f} s)")

        # --- 2. La géométrie est LUE sur le runtime de décodage, jamais redéclarée -------------
        plan, eeg, ts, cues = seance()
        moteur = _MoteurFactice(eeg, ts)
        rt = P300Calibration(_p300.SPEC, {}, moteur, dossier=dossier)
        chk(rt.runtime_cls_du_mode is _p300.P300Runtime,
            f"la calibration DÉSIGNE le runtime de DÉCODAGE — c'est de lui, et de nulle part "
            f"ailleurs, que vient sa géométrie d'époque ({rt.runtime_cls_du_mode})")
        chk(rt.pre_s == _p300.P300Runtime.pre_s and rt.post_s == _p300.P300Runtime.post_s,
            f"...et elle en LIT pre_s/post_s ({rt.pre_s}, {rt.post_s})")

        # --- 3. L'appariement cue -> étiquette, avant tout entraînement ------------------------
        joue(rt, moteur, plan)
        etiquettes = [lab for _e, lab in rt._enregistre] if rt._enregistre else []
        chk(rt.phase == "fini", f"la séance aboutit ({rt.phase}, problème={rt.probleme!r})")

        res = rt.resultat or {}
        chk(res.get("n_essais") == ROUNDS * REPS * P300_N_TARGETS,
            f"toutes les époques annoncées sont enregistrées "
            f"({res.get('n_essais')} pour {ROUNDS * REPS * P300_N_TARGETS})")
        chk(res.get("n_manches") == ROUNDS, f"et {ROUNDS} manches ({res.get('n_manches')})")

        # --- 4. L'AUC est une probabilité, la sélection en est une autre -----------------------
        chk(res.get("auc") is not None and 0.0 <= res["auc"] <= 1.0,
            f"l'AUC est une probabilité ({res.get('auc')})")
        chk(res.get("selection") is not None and 0.0 <= res["selection"] <= 1.0
            and res.get("selection_total") == ROUNDS,
            f"la SÉLECTION est mesurée sur CHAQUE manche tenue à l'écart "
            f"({res.get('selection_ok')}/{res.get('selection_total')})")
        chk(res.get("verdict") == verdict(res.get("selection")),
            f"le verdict est recalculé depuis la SÉLECTION, pas depuis l'AUC "
            f"({res.get('verdict')!r})")
        chk(abs(res.get("hasard", 0.0) - 1.0 / P300_N_TARGETS) < 1e-9,
            f"le niveau du hasard est rapporté à côté ({res.get('hasard')})")

        # Le contenu, pas seulement la plomberie : sur ce signal, la sélection doit battre le
        # hasard. Sans cette ligne, un épochage décalé de 200 ms passerait tout le reste.
        chk(res.get("selection", 0.0) > 1.0 / P300_N_TARGETS,
            f"...et sur du P300 synthétique, elle BAT le hasard — un épochage décalé ne le "
            f"pourrait pas ({res.get('selection')} contre {1.0 / P300_N_TARGETS:.2f})")

        # --- 5. La phrase d'honnêteté est celle du P300, pas celle du MI -----------------------
        chk(bool(res.get("honnetete")),
            "le résultat porte SA phrase d'honnêteté")
        chk("0,71" in res.get("honnetete", "") and "576" in res.get("honnetete", ""),
            "...et elle donne le repère MESURÉ du projet (0,71 sur 576 époques), pas une promesse")
        chk("trois classes" not in res.get("honnetete", "")
            and "40 %" not in res.get("honnetete", ""),
            "...et ce n'est PAS celle du Motor Imagery : 40 % à trois classes n'a aucun sens pour "
            "une sélection parmi six cibles")

        # --- 6. Le modèle est écrit dans le dossier DONNÉ, et jamais dans le vrai data/ --------
        chk(res.get("modele", "").startswith(dossier),
            f"le modèle est écrit dans le dossier reçu ({res.get('modele')})")
        chk(nom_retenu(res.get("modele", "")).startswith("p300_model_")
            and res.get("modele", "").endswith(".joblib"),
            f"...sous un nom HORODATÉ, jamais fixe ({_os.path.basename(res.get('modele', ''))})")
        chk(bool(res.get("enregistrement")) and _os.path.exists(res["enregistrement"]),
            f"...et les époques BRUTES sont archivées à côté ({res.get('enregistrement')})")

        from core import p300_models

        # ⚠️ L'INVERSE de ce que ce test exigeait avant le chantier « seul point d'entrée » : ce
        # qui sort d'une calibration est un CANDIDAT, et il ne doit être proposé à PERSONNE tant
        # que quelqu'un ne l'a pas retenu. Le préfixe le rend invisible au motif de découverte —
        # sans lui, un candidat oublié dans son dossier temporaire redeviendrait « le modèle
        # chargeable le plus récent » le jour où ce dossier serait scanné, c'est-à-dire le défaut
        # que ce chantier ferme, rouvert par sa propre correction.
        chk(_os.path.basename(res.get("modele", "")).startswith(CALIB_CANDIDAT_PREFIXE),
            f"le modèle produit est un CANDIDAT, marqué comme tel "
            f"({_os.path.basename(res.get('modele', ''))})")
        chk(p300_models.modeles_disponibles(dossier) == [],
            f"...donc INVISIBLE au motif `{p300_models.MOTIF}` : rien à découvrir dans son "
            f"dossier ({p300_models.modeles_disponibles(dossier)})")
        chk(fnmatch(nom_retenu(res.get("modele", "")), p300_models.MOTIF),
            f"...mais le nom sous lequel il sera RETENU, lui, correspond au motif — sinon le "
            f"modèle enregistré ne serait jamais proposé ({nom_retenu(res.get('modele', ''))})")

        # --- 6bis. Le modèle produit est ACCEPTÉ par le mode qui décodera avec -----------------
        # `P300Runtime.__init__` refuse un modèle dont la géométrie d'époque n'est pas celle qu'il
        # prélève (`_desaccord_geometrie`) — et il a raison : les scores seraient plausibles et
        # faux. C'est le contrôle SYMÉTRIQUE de tout ce fichier : on a vérifié que la calibration
        # découpe comme le décodage, on vérifie ici que ce qu'elle en SAUVEGARDE le dit aussi.
        # Sans cette ligne, `P300Model(fs=fs)` construit avec ses défauts passait tous les tests,
        # et le premier changement de `P300Runtime.pre_s` aurait fait refuser, au démarrage du
        # mode, le modèle qu'on venait tout juste de calibrer — en accusant le modèle.
        class _MoteurDuMode:
            acq = _FausseAcq()
            instance = "selftest"

        try:
            decodeur = _p300.P300Runtime(_p300.SPEC,
                                         {"model": res["modele"], "stream_in": "x"},
                                         _MoteurDuMode())
            refus = None
        except ValueError as e:
            decodeur, refus = None, str(e)
        chk(decodeur is not None,
            f"le modèle sorti de cette calibration est ACCEPTÉ par le mode qui décodera avec "
            f"({refus or 'aucun refus'})")
        chk(refus is not None or (decodeur.model.pre_s == _p300.P300Runtime.pre_s
                                  and decodeur.model.post_s == _p300.P300Runtime.post_s
                                  and decodeur.model.fs == _FausseAcq.fs),
            f"...parce qu'il PORTE la géométrie avec laquelle ses époques ont été découpées, pas "
            f"un défaut de configuration ({getattr(decodeur, 'model', None)})")

        # --- 7. Une séance trop pauvre est REFUSÉE, en disant quoi faire -----------------------
        plan_court, eeg_c, ts_c, _cues_c = seance(rounds=1, reps=1, graine=1)
        moteur_c = _MoteurFactice(eeg_c, ts_c)
        rt_court = P300Calibration(_p300.SPEC, {}, moteur_c, dossier=dossier)
        joue(rt_court, moteur_c, plan_court)
        chk(rt_court.phase == "annule" and "trop pauvre" in rt_court.probleme,
            f"une séance trop pauvre refuse d'entraîner ({rt_court.phase}, {rt_court.probleme})")
        chk("Refais une séance plus longue" in rt_court.probleme,
            f"...en disant quoi faire ({rt_court.probleme})")
        chk(len(_glob.glob(_os.path.join(dossier, "*p300_model*.joblib"))) == 1,
            f"...et n'écrit AUCUN second fichier de modèle "
            f"({_glob.glob(_os.path.join(dossier, '*p300_model*.joblib'))})")

        # Une calibration sans dossier ne retombe PAS sur `data/` : elle refuse, en disant qui
        # aurait dû lui en donner un. C'est le repli silencieux qui faisait proposer une séance
        # ratée comme modèle par défaut.
        rt_sans = P300Calibration(_p300.SPEC, {}, _MoteurFactice(eeg, ts))
        try:
            rt_sans.dossier_ou_lever()
            refus_dossier = None
        except ValueError as e:
            refus_dossier = str(e)
        chk(refus_dossier is not None and "data/" in refus_dossier,
            f"sans dossier, la calibration REFUSE au lieu de retomber sur data/ "
            f"({(refus_dossier or 'aucun refus')[:70]}…)")

        # --- 8. Les marqueurs mal formés sont refusés, pas étiquetés au hasard -----------------
        moteur_r = _MoteurFactice(eeg, ts)
        rt_r = P300Calibration(_p300.SPEC, {}, moteur_r, dossier=dossier)
        rt_r.tick(moteur_r, moteur_r.t0)
        rt_r.encaisser(moteur_r, moteur_r.t0, {"mode": "p300", "event": "calib_start", "trials": 6})
        rt_r.tick(moteur_r, moteur_r.t0 + rt_r.warmup_s + 0.1)
        t_r = moteur_r.t0 + 20.0
        rt_r.encaisser(moteur_r, t_r, {"mode": "p300", "event": "flash", "target": 0})
        chk(rt_r.essai == 0 and rt_r._refus == 1,
            f"un flash AVANT le premier cue est refusé : sans vérité-terrain, l'étiqueter "
            f"« non-cible » glisserait de vraies cibles dans la classe majoritaire "
            f"({rt_r.essai} enregistrée(s), {rt_r._refus} refus)")
        rt_r.encaisser(moteur_r, t_r + 0.1, {"mode": "p300", "event": "cue", "target": True})
        chk(rt_r._attendue is None and rt_r._refus == 2,
            f"`target: true` n'est PAS la cible 1 : en Python `bool` hérite de `int` "
            f"({rt_r._attendue!r}, {rt_r._refus} refus)")
        rt_r.encaisser(moteur_r, t_r + 0.2, {"mode": "p300", "event": "cue", "target": 99})
        chk(rt_r._attendue is None and rt_r._refus == 3,
            f"une cible hors plage non plus ({rt_r._attendue!r})")
        rt_r.encaisser(moteur_r, t_r + 0.3, {"mode": "p300", "event": "cue", "target": 2})
        rt_r.encaisser(moteur_r, t_r + 0.4, {"mode": "p300", "event": "flash", "target": 2})
        rt_r.encaisser(moteur_r, t_r + 0.6, {"mode": "p300", "event": "flash", "target": 5})
        rt_r.encaisser(moteur_r, t_r + 0.8, {"mode": "p300", "event": "round_end"})
        etiq = [lab for _e, lab in rt_r._enregistre]
        chk([e.est_cible for e in etiq] == [True, False],
            f"le flash de la cible CUÉE est « cible », les autres non ({etiq})")
        chk(all(e.manche == 0 for e in etiq),
            f"et les deux appartiennent à la manche du cue ({[e.manche for e in etiq]})")
        chk(rt_r.state(now=t_r)["refus_cible"] == 3,
            f"les refus sont VISIBLES dans l'instantané : sinon une fenêtre qui numérote mal ses "
            f"cibles ne se voit que dans un terminal que personne ne lit "
            f"({rt_r.state(now=t_r)['refus_cible']})")

        # Un `cue` PERDU ne doit pas faire hériter la cible de la manche précédente : `round_end`
        # a fermé la manche, donc les flashs suivants n'ont plus de vérité-terrain et sont
        # REFUSÉS. Sans ce garde, une manche entière serait apprise sur la cible d'AVANT — même
        # nombre d'époques, mêmes proportions, rien à voir dans aucun compteur.
        avant = len(rt_r._enregistre)
        rt_r.encaisser(moteur_r, t_r + 1.0, {"mode": "p300", "event": "flash", "target": 4})
        chk(len(rt_r._enregistre) == avant and rt_r._refus == 4,
            f"après un `round_end`, un flash sans nouveau `cue` est REFUSÉ — pas étiqueté sur la "
            f"cible de la manche précédente ({len(rt_r._enregistre) - avant} enregistrée(s), "
            f"{rt_r._refus} refus)")

        # --- 9. Une manche entièrement perdue ne DÉCALE pas la vérité-terrain ------------------
        # Le trou dans la numérotation est le seul défaut que `_renumerote` existe pour fermer, et
        # il ne lève rien : chaque manche suivante lirait la cible d'une AUTRE.
        groupes, cues_r = _renumerote([0, 0, 2, 2], [7, 8, 9])
        chk(groupes == [0, 0, 1, 1] and cues_r == [7, 9],
            f"une manche sans époque est retirée AVEC sa cible, pas seulement du groupe "
            f"({groupes}, {cues_r})")

        chk(len(etiquettes) == ROUNDS * REPS * P300_N_TARGETS,
            f"(rappel) la séance nominale avait bien enregistré ses "
            f"{ROUNDS * REPS * P300_N_TARGETS} époques ({len(etiquettes)})")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    chk(empreinte_dossier() == empreinte_avant,
        "AUCUN fichier n'a bougé dans le vrai `data/` — il porte des enregistrements EEG d'une "
        "personne identifiable, et son modèle le plus récent est celui que le moteur ÉLIT")

    print(f"[p300-calib] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
