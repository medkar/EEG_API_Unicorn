"""La calibration Motor Imagery : le protocole, l'entraînement, la sauvegarde.

Le protocole est celui qui a été validé au casque, dans l'écran pygame désormais archivé
(`archive/mi_calibrate.py`) — mêmes durées, mêmes consignes, même découpage. Il est repris ici
mot pour mot, à trois différences près, toutes voulues :

1. **L'accuracy affichée est HONNÊTE** (validation croisée par essai, cf. `MIModel.fit`). L'écran
   pygame archivé affiche un chiffre gonflé de 10 à 16 points.
2. **Rien n'est jamais écrasé** : le modèle et l'enregistrement sont horodatés. `mi_calib_last.npz`
   avait un nom FIXE, et c'est ce qui a fait perdre les époques d'une séance à 42 essais.
3. **Une séance abandonnée n'entraîne rien** (cf. `CalibrationRuntime.cancel`).

Autotest :
    python src/core/modes/mi_calib.py
"""

import os as _os
import random as _random
import sys as _sys
import time as _time

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
import numpy as np  # noqa: E402

from core.config import (CALIB_CANDIDAT_PREFIXE, MI_CUE_S, MI_IMAGERY_S,  # noqa: E402
                         MI_METHOD, MI_MISES_EN_ROUTE, MI_REST_S, MI_SESSIONS,
                         MI_TRAIN_STEP_S,
                         MI_WARMUP_PER_CLASS, MI_WINDOW_S, SECTEUR_HZ, SSVEP_WARMUP_S,
                         use_utf8_console)
from core.i18n import nombre, tr  # noqa: E402
from core.mi_decoder import MI_BAND, MI_CONTROL, MI_LABELS, MIModel  # noqa: E402
from core.modes.affichage import verifier as _verifier_affichage  # noqa: E402
from core.modes.affichage import (au_dessus_du_hasard, depuis_table, lignes,  # noqa: E402
                                  niveau_par_seuils, non_mesure, p_hasard, pct,
                                  seuil_du_hasard, texte_filtre,
                                  texte_p, verifier)
from core.modes.calibration import CalibrationRuntime  # noqa: E402
from core.modes.contract import Calib, Param, bande_de, params_bande  # noqa: E402

# Les consignes, telles qu'elles ont été validées. La formulation compte : « SENTIR le serrement »
# et non « se le représenter » est la différence entre de l'imagerie kinesthésique, qui produit
# une ERD exploitable, et de l'imagerie visuelle, qui n'en produit pas.
# Les clés du dictionnaire sont les ÉTIQUETTES des classes (celles du modèle et du `.npz`) : elles
# ne se traduisent pas. Seul le texte affiché passe par `tr`.
INSTRUCTIONS = {
    "LEFT": tr("calib.mi.instruction.gauche"),
    "RIGHT": tr("calib.mi.instruction.droite"),
    "REST": tr("calib.mi.instruction.repos"),
}
RAPPEL = tr("calib.mi.rappel")

# Les tâches par défaut : les deux poings, le contraste le mieux mesuré sur ce casque (63 % à deux
# tâches). Sans REST, le modèle désigne toujours l'une des tâches : c'est le seuil de probabilité du
# mode qui le fait taire quand il n'est pas sûr.
TACHES_DEFAUT = MI_CONTROL
TACHES_MAX = 5

# Le minimum d'essais par tâche pour entraîner. La validation croisée par essai en demande 2 (deux
# plis) ; avec 3, chaque pli d'apprentissage garde au moins deux essais de chaque tâche. Le plus
# court réglage (10 essais par tâche) est loin au-dessus : ce minimum ne joue que si des essais ont
# été perdus pendant la séance (coupure Bluetooth).
ESSAIS_MIN_PAR_TACHE = 3


# Les classes d'origine portent des noms ANGLAIS : ce sont ceux que reçoit l'application
# (`p_LEFT`…), quelle que soit la langue de la console. Leurs noms français, tapés, y mènent aussi :
# « gauche » devient la classe LEFT, comme « left ».
ALIAS_FRANCAIS = {"GAUCHE": "LEFT", "DROITE": "RIGHT", "REPOS": "REST"}


def canonique(tache):
    """Une tâche tapée qui nomme une classe d'origine (« rest », « Gauche », « left ») DEVIENT
    cette classe.

    Elle retrouve ainsi sa consigne validée, son top latéralisé (`console/beeps.py` les connaît
    par leur nom exact) et, pour REST, son sens dans le flux publié (`rest_index`). Toute autre
    tâche garde le texte tapé.
    """
    connues = {c.casefold(): c for c in MI_LABELS}
    connues.update({nom.casefold(): c for nom, c in ALIAS_FRANCAIS.items()})
    return connues.get(tache.casefold(), tache)


def consigne(tache):
    """Ce que l'écran affiche pendant l'essai : la consigne validée, ou la tâche telle que tapée.

    Rien hors d'un essai (`tache` vide : chauffe, entraînement) — sinon « Imagine : » à vide.
    """
    if not tache:
        return ""
    return INSTRUCTIONS.get(tache) or tr("calib.mi.instruction.tache", tache=tache)


def rappel_de(tache):
    """Le rappel sous la consigne. Rien pour REST, ni hors d'un essai."""
    if not tache:
        return ""
    if tache in MI_CONTROL:
        return RAPPEL
    return "" if tache == "REST" else tr("calib.mi.rappel.tache")

BRIEFING = (
    tr("calib.mi.briefing.1"),
    tr("calib.mi.briefing.2"),
    tr("calib.mi.briefing.3"),
    tr("calib.mi.briefing.4"),
    tr("calib.mi.briefing.5"),
    tr("calib.mi.briefing.6"),
    tr("calib.mi.briefing.7"),
)

# Les seuils des verdicts. Le score est mesuré sur des essais que le modèle n'a pas vus : c'est un
# chiffre honnête, nettement plus bas qu'un score calculé sur des fenêtres mélangées. Pour situer :
# sur ce casque, chez une personne, 40 % à 3 tâches et 63 % à 2 — un score modeste est normal.
#
# Les seuils dépendent du hasard, donc du nombre de tâches : 45 % est un bon score à 3 tâches
# (hasard 33 %), mais il est sous le hasard à 2 (50 %). On mesure donc l'écart au hasard en part de
# ce qui reste à gagner au-dessus de lui (le kappa de Cohen) : 0,40 et 0,175 donnent 60 % et 45 % à
# 3 tâches, 70 % et 59 % à 2, 52 % et 34 % à 5.
KAPPA_EXCELLENT = 0.40
KAPPA_UTILISABLE = 0.175


def table_pour(hasard):
    """La table des verdicts pour ce niveau de hasard (1 / nombre de tâches)."""
    def seuil(kappa):
        return round(hasard + kappa * (1.0 - hasard), 4)
    return ((seuil(KAPPA_EXCELLENT), tr("calib.mi.verdict.excellent")),
            (seuil(KAPPA_UTILISABLE), tr("calib.mi.verdict.utilisable")),
            (0.00, tr("calib.mi.verdict.faible")))


VERDICTS = table_pour(1.0 / len(MI_LABELS))     # la table à 3 classes

# La phrase d'honnêteté du MI : OBLIGATOIRE avec le résultat, quelle que soit l'accuracy. Un
# « 40 % » sans elle ne veut rien dire.
#
# Elle vit ICI, avec le chiffre qu'elle explique, et PAS dans `console/calib_page.py` : la page
# est générique et ne connaît aucun mode, donc une phrase de page s'afficherait sous tous les
# résultats — « 40 % à trois classes », « niveau du hasard 33 % » sous une sélection parmi six
# cibles, où elle n'a aucun sens. Chaque calibration porte la sienne dans son résultat, comme
# le P300 (`p300_calib.HONNETETE`).
HONNETETE = tr("calib.mi.honnetete")

# Le nom de chaque méthode, tel que le résultat l'affiche. Les CLÉS sont les identifiants de
# `mi_decoder.build_pipe` (ceux que le modèle enregistre) : elles ne se traduisent pas.
METHODES = {
    "csp": tr("calib.mi.methode.csp"),
    "fbcsp": tr("calib.mi.methode.fbcsp"),
    "riemann": tr("calib.mi.methode.riemann"),
}


def filtre_de(methode, bande, secteur_hz, shrinkage=False):
    """La phrase qui dit AVEC QUOI ce chiffre a été obtenu : méthode, bande, coupe-bande.

    Son champ `filtre` dans le résultat, lu par le repli « Détails » comme celui des trois autres
    entraînements : deux séances à 40 % ne se comparent pas si l'une a appris sur 8-30 Hz en CSP
    et l'autre sur 4-40 Hz en FBCSP.
    """
    nom = METHODES.get(methode, methode)
    if shrinkage and methode in ("csp", "fbcsp"):
        nom += tr("calib.mi.methode.shrinkage")
    return texte_filtre(bande, secteur_hz, nom)


def horodatage(maintenant=None):
    """`AAAAMMJJ-HHMMSS`. Le paramètre existe pour que le test soit reproductible.

    ⚠️ `maintenant or _time.time()` serait faux : `0.0` (l'epoch Unix, un instant valide) est
    FALSY en Python, donc `or` le remplacerait par l'heure réelle — c'est le
    même piège que `now=0.0` dans `calibration.py`. Inatteignable en séance réelle, mais un
    piège posé pour le prochain test.
    """
    return _time.strftime("%Y%m%d-%H%M%S",
                          _time.localtime(_time.time() if maintenant is None else maintenant))


def _chemins_libres(dossier, n_essais, prefixe=""):
    """Le couple (chemin du modèle, chemin de l'enregistrement) pour CETTE séance — les DEUX
    chemins sont GARANTIS libres au moment du retour, sans changer le FORMAT du nom.

    `horodatage()` n'a qu'une résolution d'une seconde : deux séances qui finissent la même
    seconde produiraient sinon le MÊME couple de noms, et `save`/`savez` écrasent sans vérifier —
    exactement la panne que l'horodatage existe pour fermer (cf. docstring du module, point 2).
    On avance donc d'une seconde tant que l'un des deux fichiers existe déjà : un décalage de
    quelques secondes sur l'estampille est un prix dérisoire devant la perte d'une séance.

    `prefixe` : ce que la calibration du moteur passe (`CALIB_CANDIDAT_PREFIXE`) pour que le
    fichier écrit ne corresponde à AUCUN motif de découverte tant qu'il n'est pas retenu — cf. le
    long commentaire de cette constante dans `core/config.py`. Défaut `""` : un appelant qui écrit
    un modèle DÉFINITIF (il n'y en a plus dans le dépôt pour le MI, mais le P300 en a un) garde
    le nom que sa liste cherche. Le préfixe est posé ICI, dans la fonction qui vérifie la liberté
    du nom, et pas après coup : vérifier un nom puis en écrire un autre ne vérifie rien.
    """
    maintenant = _time.time()
    while True:
        stamp = horodatage(maintenant)
        chemin_modele = _os.path.join(dossier, f"{prefixe}mi_model_{stamp}.joblib")
        chemin_npz = _os.path.join(dossier, f"{prefixe}mi_calib_{stamp}_n{n_essais:02d}.npz")
        if not _os.path.exists(chemin_modele) and not _os.path.exists(chemin_npz):
            return chemin_modele, chemin_npz
        maintenant += 1.0


def decouper(epoque, n, pas):
    """Découpe une époque (n_samp, n_ch) en fenêtres (n_ch, n) glissantes.

    L'orientation compte : `MIModel` attend (n_essais, n_ch, n_samp), et le CSP est un filtre
    SPATIAL — une transposition oubliée décoderait du bruit avec des probabilités à 0,99.
    """
    return [epoque[i:i + n].T for i in range(0, len(epoque) - n + 1, pas)]


def _non_significatif(cv, n_essais, hasard):
    """Vrai pour un score que la table jugerait utilisable ou mieux, mais que le hasard produit
    aussi : 14 essais justes sur 30 à 3 tâches (47 %) passe la ligne des 45 %, alors qu'un tirage au
    hasard fait aussi bien une fois sur dix.

    C'est le test binomial exact qui tranche (`affichage.au_dessus_du_hasard`, la même porte que
    les tests), compté en ESSAIS — l'unité de la validation croisée, jamais en fenêtres. Sous la
    ligne FAIBLE, la table garde la main : son conseil (soigner le signal) est le bon.
    """
    if cv is None or not n_essais or not hasard:
        return False
    if niveau_par_seuils(cv, table_pour(hasard)) == "faible":
        return False
    return not au_dessus_du_hasard(int(round(cv * n_essais)), int(n_essais), hasard)


def verdict(cv, n_essais=None, hasard=None):
    """La phrase. Avec `n_essais` et `hasard`, un chiffre indistinguable du hasard est déclaré
    NON SIGNIFICATIF au lieu d'« utilisable » — cf. `_non_significatif`."""
    if _non_significatif(cv, n_essais, hasard):
        p = p_hasard(int(round(cv * n_essais)), int(n_essais), hasard)
        # Le mot est passé en valeur, pas réécrit dans la phrase : `lignes_de` affiche le MÊME mot
        # en face, et `affichage.verifier` exige que le verdict commence par lui — dans toutes les
        # langues.
        return tr("calib.mi.verdict.non_significatif", mot=tr("calib.mot.non_significatif"),
                  n=n_essais, p=texte_p(p))
    table = table_pour(hasard) if hasard else VERDICTS
    for seuil, texte in table:
        if cv >= seuil:
            return texte
    return table[-1][1]


def lignes_de(cv, n_essais, hasard):
    """Les quatre clés d'affichage — du MÊME calcul que `verdict` (même porte, même table)."""
    if cv is None:
        return non_mesure(tr("calib.mi.non_mesure.raison"), tr("calib.mi.non_mesure.conseil"))
    chiffres = tr("calib.mi.chiffres", justesse=pct(cv), hasard=pct(hasard), n=n_essais)
    # Le score à atteindre pour faire mieux que le hasard, calculé par la même porte que le
    # verdict : « 55 % » ne dit rien seul — il faut 75 % à 20 essais et deux tâches.
    seuil = seuil_du_hasard(n_essais, hasard) if n_essais and hasard else None
    if n_essais and hasard:
        chiffres += " " + (tr("calib.mi.chiffres.seuil", seuil=pct(seuil)) if seuil is not None
                           else tr("calib.mi.chiffres.sans_seuil", n=n_essais))
    if _non_significatif(cv, n_essais, hasard):
        return lignes("faible", tr("calib.mot.non_significatif"), chiffres,
                      tr("calib.mi.reserve.non_significatif"))
    return depuis_table(cv, table_pour(hasard), chiffres)


class MICalibration(CalibrationRuntime):
    """Le protocole MI. Sa seule particularité est ce qu'elle fait des époques à la fin."""

    imagery_s = MI_IMAGERY_S
    rest_s = MI_REST_S
    warmup_s = SSVEP_WARMUP_S          # la même chauffe que les modes : c'est la même dérive DC
    warmup_per_class = MI_WARMUP_PER_CLASS
    # Le découpage en fenêtres d'entraînement. Attributs de CLASSE, comme les durées, et pour la
    # même raison : un test doit pouvoir jouer une séance entière en quelques secondes, et il ne
    # peut le faire qu'en raccourcissant la fenêtre EN MÊME TEMPS que l'imagerie. Les raccourcir
    # séparément donne `imagery_s < window_s`, donc ZÉRO fenêtre découpée et un entraînement qui
    # refuse.
    window_s = MI_WINDOW_S
    step_s = MI_TRAIN_STEP_S

    # Pas de `__init__` ici : `dossier` est porté par `CalibrationRuntime`, qui n'a AUCUN repli
    # sur `DATA_DIR`. Une calibration n'écrit jamais dans `data/` : sinon une séance ratée
    # deviendrait aussitôt le modèle le plus récent — celui que le moteur, la console et les
    # applis proposent par défaut — sans que personne ait pu la refuser.

    @property
    def cue_s(self):
        """La mise en route de cette séance, réglée dans « Entraîner » ; le modèle la retient.
        ⚠️ Une propriété : le smoke du moteur l'écrase au niveau de la CLASSE pour jouer une séance
        en accéléré, puis la restaure."""
        return float(getattr(self, "params", {}).get("mise_en_route_s", MI_CUE_S))

    @property
    def classes(self):
        """Les tâches de cette séance, réglées dans « Entraîner ». Elles deviennent les classes du
        modèle, donc les voies `p_<tâche>` du flux publié au décodage."""
        return tuple(canonique(t) for t in self.params.get("taches") or TACHES_DEFAUT)

    def instruction(self):
        return consigne(self.classe)

    def rappel(self):
        return rappel_de(self.classe)

    def croix(self):
        """Une croix pendant tout l'essai (mise en route et imagerie), pour TOUTES les tâches.

        Le regard reste au même endroit quelle que soit la tâche. Sans elle, des yeux qui se
        relâchent pendant REST font monter l'alpha occipital (PO7, Oz, PO8) ; le CAR l'étale sur
        C3 et C4, dans la bande du mu, et le modèle apprendrait un contraste qui n'a rien de moteur.
        Rien pendant la pause, qui n'est jamais enregistrée."""
        return self.phase in ("echauffement", "essais") and self.etape in ("cue", "imagerie")

    def _entrainer(self, enregistre, fs):
        """CSP + LDA (ou FBCSP) sur les fenêtres, CV honnête par essai, puis sauvegarde horodatée.

        La bande, la méthode et le secteur sont ceux de CETTE séance (réglages « Entraîner », et
        secteur du poste que porte le moteur). Ils partent DANS le modèle : le décodage les relit
        et filtre exactement comme l'entraînement — c'est pour ça que la bande se règle ici et
        jamais dans « Régler » (un modèle décodé sur un autre filtre ne lève rien, il se trompe).
        """
        n = int(round(self.window_s * fs))
        pas = int(round(self.step_s * fs))
        X, y, groupes = [], [], []
        for indice, (epoque, label) in enumerate(enregistre):
            for fenetre in decouper(np.asarray(epoque, dtype=float), n, pas):
                X.append(fenetre)
                y.append(label)
                groupes.append(indice)     # le GROUPE est l'essai : c'est ce qui rend la CV honnête

        # La garde compte des ESSAIS par tâche, pas des fenêtres : c'est le nombre d'essais qui
        # permet la validation croisée (`MIModel.fit` en demande 2 pour former deux plis). Compter
        # des fenêtres ne le garantit pas : des essais perdus en séance (« essai IGNORÉ » dans
        # `CalibrationRuntime._pas_essai`) laisseraient sortir un modèle sans score honnête.
        # Commentaire jumeau dans `core/mi_decoder.py::MIModel.fit`.
        groupes_np, y_np = np.asarray(groupes), np.asarray(y)
        comptes = {c: len(np.unique(groupes_np[y_np == c])) if len(y_np) else 0
                   for c in self.classes}
        if not X or min(comptes.values()) < ESSAIS_MIN_PAR_TACHE:
            raise ValueError(tr("calib.mi.trop_court", comptes=comptes,
                                minimum=ESSAIS_MIN_PAR_TACHE))

        bande = bande_de(self.params, MI_BAND)
        methode = "fbcsp" if self.params.get("fbcsp") else MI_METHOD
        secteur = getattr(self.engine, "secteur_hz", SECTEUR_HZ)
        modele = MIModel(labels=self.classes, fs=fs, band=bande, method=methode,
                         secteur_hz=secteur,
                         shrinkage=bool(self.params.get("lda_shrinkage"))).fit(
            np.asarray(X), np.asarray(y), groups=np.asarray(groupes))
        # Relus du MODÈLE, pas des réglages : la phrase dit ce que le modèle a VRAIMENT appris.
        filtre = filtre_de(modele.method, modele.band, modele.secteur_hz,
                           modele.shrinkage) + " · " + tr(
            "calib.mi.mise_en_route", s=nombre(self.cue_s))

        dossier = self.dossier_ou_lever()
        _os.makedirs(dossier, exist_ok=True)
        # Le motif `mi_model*.joblib` est celui que `mi_models.modeles_disponibles` cherche :
        # ne pas s'en écarter, sinon le modèle RETENU n'apparaîtra jamais dans la liste.
        # `_chemins_libres` (pas `horodatage` appelée seule) : deux séances qui finissent la
        # même seconde ne doivent PAS produire le même couple de fichiers — cf. sa docstring.
        # ⚠️ `CALIB_CANDIDAT_PREFIXE` : ce qu'on écrit ici est un CANDIDAT, dans le dossier
        # temporaire du moteur. Le préfixe le rend invisible à `mi_model*.joblib` tant qu'il n'a
        # pas été retenu ; c'est `save_calibration` qui l'ôte en le déplaçant vers `data/`.
        chemin_modele, chemin_npz = _chemins_libres(dossier, len(enregistre),
                                                    prefixe=CALIB_CANDIDAT_PREFIXE)
        # Le `.npz` D'ABORD, le `.joblib` ENSUITE : si `savez` échoue (disque plein, verrou
        # antivirus), l'exception remonte AVANT que le modèle n'existe — aucun fichier orphelin.
        # Dans l'ordre inverse, un `.npz` qui échoue après un `.joblib` déjà écrit laisserait un
        # MODÈLE sur le disque, visible dans la liste de la console, sans enregistrement ni
        # provenance : exactement ce que « l'échec ne produit AUCUN fichier » interdit. Un `.npz`
        # orphelin, lui, est inoffensif — rien ne le liste, rien ne le propose.
        # Avec la géométrie, le FILTRE du modèle : `research/mi_compare.py` rejoue une séance
        # avec le secteur où elle a été enregistrée. `secteur_hz = 0` veut dire « pas de
        # coupe-bande » (la convention de `core/filtrage.py`, comme le `.npz` du P300) ; un `.npz`
        # sans ces champs n'a ni bande ni secteur, et l'outil le dit.
        # La mise en route part dans le modèle (« Tester » la rejoue) ET dans l'enregistrement :
        # c'est elle qu'on compare d'une séance à l'autre.
        modele.mise_en_route_s = float(self.cue_s)
        np.savez(chemin_npz,
                 epochs=np.asarray([e for e, _l in enregistre]),
                 labels=np.asarray([l for _e, l in enregistre]),
                 fs=fs, window_s=self.window_s, step_s=self.step_s,
                 imagery_s=self.imagery_s, mise_en_route_s=float(self.cue_s),
                 lda_shrinkage=bool(modele.shrinkage),
                 bande=np.asarray(modele.band, dtype=float),
                 secteur_hz=float(modele.secteur_hz or 0.0), methode=modele.method)
        modele.save(chemin_modele)

        # `None` PROPAGÉ, jamais recopié en 0.0 : un 0 % afficherait « FAIBLE — contact des
        # électrodes, immobilité… », un diagnostic précis et SANS RAPPORT avec la vraie cause (pas
        # assez d'essais distincts pour former deux plis). `mi_models.decrire()` et
        # `MIModel.fit` préservent ce None, et il doit l'être ICI aussi.
        cv = modele.cv_groupee_
        hasard = 1.0 / len(self.classes)
        if cv is None:
            verdict_txt = tr("calib.mi.verdict.non_mesurable")
            print(f"[mi-calib] {verdict_txt}")
        else:
            verdict_txt = verdict(cv, len(enregistre), hasard)
            print(f"[mi-calib] accuracy HONNÊTE (validation croisée par essai) : {cv*100:.1f}% "
                  f"— hasard {hasard*100:.0f}% — {verdict_txt}")
        print(f"[mi-calib] (pour mémoire, la CV naïve, fenêtres mélangées : "
              f"{modele.cv_*100:.1f}% — gonflée, ne pas s'y fier)")
        print(f"[mi-calib] {filtre}")
        print(f"[mi-calib] modèle : {chemin_modele}")
        print(f"[mi-calib] enregistrement : {chemin_npz}")
        return {
            "modele": chemin_modele,
            "nom": _os.path.basename(chemin_modele),
            "enregistrement": chemin_npz,
            "n_essais": len(enregistre),
            "n_fenetres": len(X),
            "cv_groupee": cv,
            "cv_naive": float(modele.cv_),
            "hasard": hasard,
            "classes": list(self.classes),
            "mise_en_route_s": float(self.cue_s),
            "shrinkage": bool(modele.shrinkage),
            # Avec quoi ce chiffre a été obtenu — les valeurs que le modèle PORTE, relues de lui.
            "methode": modele.method,
            "bande": [float(modele.band[0]), float(modele.band[1])],
            "secteur_hz": modele.secteur_hz,
            "verdict": verdict_txt,
            # Ce qui s'affiche EN FACE (cf. `core/modes/affichage.py`) — même calcul que le verdict.
            **lignes_de(cv, len(enregistre), hasard),
            # AVEC QUOI ce modèle a appris (méthode, bande, coupe-bande) : une ligne du repli
            # « Détails », la même pour les quatre entraînements.
            "filtre": filtre,
            # La phrase qui dit ce que ce chiffre vaut. Elle voyage AVEC le résultat, parce que
            # l'écran qui l'affiche est générique et ne connaît aucun mode : celle du P300 parle
            # d'AUC et de sélection parmi six cibles, celle-ci de 40 % à trois classes.
            "honnetete": HONNETETE,
        }


CALIB = Calib(
    kind="moteur",
    label=tr("calib.mi.label"),
    briefing=BRIEFING,
    epoch_s=MI_IMAGERY_S,
    params=(
        # Les TÂCHES à imaginer, de 2 à 5 (un champ par tâche dans la console). Réglées à
        # l'entraînement, comme la bande : le modèle les porte, et le test comme le décodage les
        # relisent de lui.
        Param(
            key="taches",
            label=tr("calib.mi.param.taches.label"),
            kind="text_list",
            default=TACHES_DEFAUT,
            count=(2, TACHES_MAX),
            help=tr("calib.mi.param.taches.aide"),
        ),
        # La MISE EN ROUTE : le temps entre le bip et le début de l'enregistrement. 3 s par défaut
        # (il faut souvent ~2 s pour bien lancer l'imagination) ; la littérature découpe dès 1 s.
        # Un réglage, pour que chacun mesure ce qui lui convient. Cf. `core/config.py`.
        Param(
            key="mise_en_route_s",
            label=tr("calib.mi.param.mise_en_route.label"),
            kind="choice",
            unit="s",
            default=MI_CUE_S,
            choices=MI_MISES_EN_ROUTE,
            help=tr("calib.mi.param.mise_en_route.aide"),
        ),
        Param(
            key="trials_per_class",
            label=tr("calib.mi.param.trials_per_class.label"),
            kind="choice",
            default=MI_SESSIONS[1],
            choices=MI_SESSIONS,
            help=tr("calib.mi.param.trials_per_class.aide"),
        ),
        # La bande, réglée à l'entraînement et enregistrée dans le modèle. Les bornes gardent
        # toujours 10-20 Hz dedans (le haut du mu, le bas du bêta) : une bande qui retirerait le
        # rythme moteur est refusée, elle ne décoderait que du bruit sans rien dire. Elles
        # s'arrêtent à 4 et 40 Hz : sous 4 Hz, la dérive et les mouvements des yeux ; au-dessus de
        # 40 Hz, la crispation des muscles de la mâchoire. Le FBCSP en ferait des sous-bandes, et
        # les CHOISIRAIT si elles suivent la consigne : un modèle qui décode la crispation, pas
        # l'imagination du mouvement.
        *params_bande(MI_BAND, (4.0, 10.0), (20.0, 40.0), tr("calib.mi.param.bande.aide")),
        # FBCSP : une OPTION, décochée — jamais mesurée utile sur ce casque. Un test de 18 à 30
        # essais ne suffit pas à dire s'il fait mieux que le CSP, et deux entraînements mêlent la
        # méthode et la séance. La comparaison honnête se fait sur UNE séance, par validation
        # croisée : `src/research/mi_compare.py`.
        Param(
            key="fbcsp",
            label=tr("calib.mi.param.fbcsp.label"),
            kind="bool",
            default=False,
            help=tr("calib.mi.param.fbcsp.aide"),
        ),
        # La LDA À SHRINKAGE : une OPTION, décochée, comme le FBCSP. Aucune différence mesurée sur
        # ce casque, mais elle aide quand il y a beaucoup de caractéristiques pour peu d'essais, et
        # ce qui ne change rien chez une personne peut aider une autre. Même comparaison :
        # `src/research/mi_compare.py`.
        Param(
            key="lda_shrinkage",
            label=tr("calib.mi.param.shrinkage.label"),
            kind="bool",
            default=False,
            help=tr("calib.mi.param.shrinkage.aide"),
        ),
    ),
    runtime_cls=MICalibration,
)


def _selftest():
    """Une séance complète, jouée en accéléré sur du signal FABRIQUÉ, dans un dossier temporaire."""
    import glob as _glob
    import hashlib
    import shutil
    import tempfile
    from fnmatch import fnmatch

    from core.config import empreinte_dossier, nom_retenu
    from core.mi_decoder import synth_mi_trial
    from core.modes import mi as _mi

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    def _hash_fichier(chemin):
        """L'empreinte OCTET POUR OCTET d'un fichier — la preuve la plus directe qu'un contenu
        n'a pas bougé, plus fiable qu'une comparaison de valeurs qui pourraient coïncider."""
        with open(chemin, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    class _FausseAcq:
        fs = 250.0

    class _FauxMoteur:
        """Rend une époque d'ERD synthétique CORRESPONDANT à la classe cuée.

        Sans ça, l'entraînement porterait sur du bruit et le test ne dirait rien du contenu — il
        ne prouverait que la plomberie. Ici, un modèle doit sortir ET les classes doivent être
        celles qu'on a cuées.
        """

        def __init__(self, runtime, rng, alias=None):
            self.acq = _FausseAcq()
            self.runtime = runtime
            self.rng = rng
            self.rendus = []      # les époques RENDUES, dans l'ordre des appels — cf. plus bas
            self.alias = alias or {}    # tâche libre -> classe d'origine dont elle reçoit l'ERD

        def recent_window(self, seconds):
            n = int(round(seconds * self.acq.fs))
            label = self.runtime.classe or "REST"
            label = self.alias.get(label, label)
            epoque = synth_mi_trial(label, n_samp=n, fs=self.acq.fs, rng=self.rng).T
            self.rendus.append(np.array(epoque, copy=True))
            return epoque

    dossier = tempfile.mkdtemp(prefix="mi_calib_")
    empreinte_avant = empreinte_dossier()
    try:
        # PAS `is CALIB` : lancé directement (`python src/core/modes/mi_calib.py`), CE fichier
        # tourne en `__main__` avec SON `CALIB`. L'import de `core.modes.mi` juste en dessous
        # (nécessaire pour lire le contrat qu'il déclare) déclenche `from core.modes import
        # mi_calib`, qui recharge CE MÊME fichier une SECONDE fois, sous son nom de paquet
        # `core.modes.mi_calib` cette fois — avec sa PROPRE instance de `CALIB` : mêmes valeurs,
        # objet différent. Artefact mécanique du couple « script exécutable directement » +
        # « importé ailleurs par son nom de paquet », pas un défaut de câblage : comparer les
        # champs qui identifient CETTE calibration est le test qui tient, pas l'identité.
        calib_mi = _mi.SPEC.calibration
        chk(calib_mi is not None and calib_mi.label == CALIB.label
            and calib_mi.runtime_cls is not None
            and calib_mi.runtime_cls.__name__ == MICalibration.__name__,
            f"le mode MI déclare CETTE calibration dans son contrat ({calib_mi!r})")
        chk(_mi.SPEC.calibration.epoch_s == MI_IMAGERY_S,
            f"et annonce la longueur d'époque dont le moteur devra dimensionner son tampon "
            f"({_mi.SPEC.calibration.epoch_s} s)")

        rng = np.random.default_rng(0)
        rt = MICalibration(_mi.SPEC, {"taches": MI_LABELS, "trials_per_class": 6}, None,
                           rng=_random.Random(0), dossier=dossier)
        rt.engine = _FauxMoteur(rt, rng)

        t = 0.0
        for _ in range(20000):
            rt.tick(rt.engine, t)
            if rt.terminee:
                break
            t += 0.25

        chk(rt.phase == "fini", f"la séance aboutit ({rt.phase} ; problème={rt.probleme!r})")
        res = rt.resultat or {}
        chk(res.get("n_essais") == 18,
            f"6 essais × 3 classes = 18 enregistrés ({res.get('n_essais')})")
        chk(res.get("n_fenetres") == 18 * 3,
            f"et 3 fenêtres par essai de 4 s ({res.get('n_fenetres')})")

        # L'invariant du chantier : le chiffre AFFICHÉ est l'honnête, et il est plus BAS.
        chk(res.get("cv_groupee") is not None and res.get("cv_naive") is not None,
            f"les deux CV sont rapportées ({res.get('cv_groupee')}, {res.get('cv_naive')})")
        chk(res["cv_groupee"] < res["cv_naive"],
            f"et c'est l'HONNÊTE qui est affichée, plus basse que la naïve "
            f"({res['cv_groupee']*100:.1f}% contre {res['cv_naive']*100:.1f}%)")
        chk(abs(res.get("hasard", 0) - 1 / 3) < 1e-9,
            f"le niveau du hasard est rapporté à côté ({res.get('hasard')})")
        # Le verdict doit être RECALCULÉ depuis la CV honnête, jamais recopié depuis la naïve —
        # sinon l'étudiant lit un verdict optimiste pendant que le chiffre honnête, affiché juste
        # à côté, est plus bas. Une implémentation qui calculerait verdict(cv_naive) tout en
        # gardant cv_groupee honnête passerait toutes les assertions précédentes : celle-ci
        # recoupe explicitement les deux au lieu de les vérifier séparément.
        # Les trois lignes affichées EN FACE viennent de la MÊME table que ce verdict : le mot
        # ouvre la phrase, les chiffres portent leur point de comparaison (`affichage.verifier`).
        chk(not _verifier_affichage(res),
            f"l'affichage du résultat est cohérent avec son verdict ({_verifier_affichage(res)})")
        chk(res["verdict"] == verdict(res["cv_groupee"], res["n_essais"], res["hasard"]),
            f"le verdict est recalculé depuis la CV HONNÊTE, pas depuis la naïve "
            f"({res['verdict']!r} == verdict({res['cv_groupee']!r}))")

        # La phrase d'honnêteté voyage AVEC le résultat, et c'est bien CELLE DU MI. L'écran qui
        # l'affiche (`console/calib_page.py`) est générique : il ne connaît aucun mode, donc il ne
        # peut pas la choisir : une phrase d'interface s'afficherait aussi sous le résultat du
        # P300 — « 40 % à trois classes » sous une sélection parmi six cibles.
        chk(res.get("honnetete") == HONNETETE and "40 %" in HONNETETE,
            "le résultat porte la phrase d'honnêteté du MI (repère : 40 % à trois tâches)")
        chk("AUC" not in res.get("honnetete", "") and "six cibles" not in res.get("honnetete", ""),
            "...et pas celle du P300, qui parle d'AUC et de sélection parmi six cibles")

        # Le modèle et l'enregistrement de CETTE séance sont horodatés. (« Rien n'est jamais
        # écrasé » — même à la même seconde — est prouvé plus bas, par DEUX séances RÉUSSIES :
        # une seule séance ici ne pourrait rien en dire.)
        from core import mi_models

        chk(nom_retenu(res["modele"]).startswith("mi_model_")
            and res["modele"].endswith(".joblib"),
            f"le modèle est horodaté ({_os.path.basename(res['modele'])})")
        chk("_n18.npz" in res["enregistrement"],
            f"l'enregistrement porte le nombre d'essais ({_os.path.basename(res['enregistrement'])})")

        # ⚠️ Ce qui sort d'une calibration est un CANDIDAT, et il ne doit être proposé à PERSONNE
        # tant que quelqu'un ne l'a pas retenu. Sinon une calibration ratée deviendrait, en
        # silence, le modèle le plus récent — donc celui que le moteur ÉLIT par défaut — avant
        # même que son chiffre ne s'affiche.
        chk(_os.path.basename(res["modele"]).startswith(CALIB_CANDIDAT_PREFIXE),
            f"le modèle produit est un CANDIDAT, marqué comme tel "
            f"({_os.path.basename(res['modele'])})")
        chk(mi_models.modeles_disponibles(dossier) == [],
            f"...donc INVISIBLE au motif `{mi_models.MOTIF}` : rien à découvrir dans son dossier "
            f"({mi_models.modeles_disponibles(dossier)})")
        chk(fnmatch(nom_retenu(res["modele"]), mi_models.MOTIF),
            f"...mais le nom sous lequel il sera RETENU, lui, correspond au motif — sinon le "
            f"modèle enregistré ne serait jamais proposé ({nom_retenu(res['modele'])})")

        d = mi_models.decrire(res["modele"])
        chk(d["cv_groupee"] is not None and abs(d["cv_groupee"] - res["cv_groupee"]) < 1e-9,
            f"la description du modèle porte la CV HONNÊTE, pas None ({d['cv_groupee']})")
        chk(d["n_essais"] == 18, f"et le nombre d'essais ({d['n_essais']})")

        # --- l'invariant « époques BRUTES », pinné d'un bout à l'autre ----------------------
        # La garde du projet (`acquisition.py --synthetic`) protège `motor_window`, que la
        # calibration n'appelle JAMAIS : elle passe par `recent_window`, une SECONDE porte vers
        # `MIModel.fit`, sans serrure dédiée. Sans cette comparaison, un `bandpass(reref(...))`
        # inséré avant `decouper` passerait toutes les assertions ci-dessus ET le smoke du
        # moteur. Comparaison OCTET POUR OCTET entre ce que le
        # faux moteur a RENDU et ce que le `.npz` a PERSISTÉ : ça pinne d'un coup le non-filtrage
        # (les valeurs) ET l'orientation (n_essais, n_samp, n_ch) — une transposition oubliée
        # romprait aussi cette égalité (les deux tableaux n'auraient plus la même forme). `rendus`
        # ne contient QUE les essais ENREGISTRÉS — l'échauffement ne prélève rien (phase
        # "echauffement" != "essais" dans `CalibrationRuntime._pas_essai`) — donc la comparaison
        # est exacte, sans avoir à exclure quoi que ce soit après coup.
        attendu_n = int(round(rt.imagery_s * rt.engine.acq.fs))
        chk(len(rt.engine.rendus) == res["n_essais"],
            f"le faux moteur a rendu exactement une époque par essai ENREGISTRÉ "
            f"({len(rt.engine.rendus)} pour {res['n_essais']} essais)")
        with np.load(res["enregistrement"]) as npz:
            epochs_disque = np.array(npz["epochs"])
        chk(epochs_disque.shape == (res["n_essais"], attendu_n, 8),
            f"le .npz persiste la forme (essais, échantillons, voies), jamais transposée "
            f"({epochs_disque.shape})")
        chk(np.array_equal(epochs_disque, np.asarray(rt.engine.rendus)),
            "et son contenu est OCTET POUR OCTET celui rendu par recent_window — rien ne "
            "l'a filtré entre la capture et la sauvegarde")

        # Une séance trop courte doit REFUSER d'entraîner, avec une raison, plutôt que de
        # produire un modèle que rien ne distingue d'un bon.
        court = MICalibration(_mi.SPEC, {"taches": MI_LABELS, "trials_per_class": 1}, None,
                              rng=_random.Random(1), dossier=dossier)
        court.engine = _FauxMoteur(court, rng)
        t = 0.0
        for _ in range(20000):
            court.tick(court.engine, t)
            if court.terminee:
                break
            t += 0.25
        chk(court.phase == "annule" and "pas assez de données" in court.probleme,
            f"une séance trop courte refuse d'entraîner, en disant pourquoi "
            f"({court.phase}, {court.probleme})")
        chk(len(_glob.glob(_os.path.join(dossier, "*mi_model*.joblib"))) == 1,
            f"et n'écrit AUCUN second fichier de modèle "
            f"({[_os.path.basename(p) for p in _glob.glob(_os.path.join(dossier, '*mi_model*.joblib'))]})")

        # La garde compte des ESSAIS distincts, pas des fenêtres. Une tâche réduite à DEUX essais
        # (les autres ont sauté) a 6 fenêtres : une garde en fenêtres (5) laisserait entraîner,
        # celle en essais (3) refuse, en le disant.
        rng_g = np.random.default_rng(11)
        sautes = [(synth_mi_trial(lab, n_samp=int(MI_IMAGERY_S * 250), fs=250.0, rng=rng_g).T, lab)
                  for lab, n in (("LEFT", 4), ("RIGHT", 2)) for _ in range(n)]
        garde = MICalibration(_mi.SPEC, {"taches": ("LEFT", "RIGHT"), "trials_per_class": 10},
                              None, dossier=_os.path.join(dossier, "garde"))
        try:
            garde._entrainer(sautes, 250.0)
            refus_garde = None
        except ValueError as e:
            refus_garde = str(e)
        chk(refus_garde is not None and "pas assez de données" in refus_garde
            and str(ESSAIS_MIN_PAR_TACHE) in refus_garde,
            f"une tâche réduite à 2 essais distincts (6 fenêtres) REFUSE d'entraîner : la garde "
            f"compte des essais, plus des fenêtres ({refus_garde})")

        # Une calibration sans dossier ne retombe PAS sur `data/` : elle refuse, en nommant qui
        # aurait dû lui en donner un. C'est ce repli silencieux qui faisait proposer une séance
        # ratée comme modèle par défaut.
        sans = MICalibration(_mi.SPEC, {"taches": MI_LABELS, "trials_per_class": 1}, None,
                             rng=_random.Random(9))
        try:
            sans.dossier_ou_lever()
            refus_dossier = None
        except ValueError as e:
            refus_dossier = str(e)
        chk(refus_dossier is not None and "data/" in refus_dossier,
            f"sans dossier, la calibration REFUSE au lieu de retomber sur data/ "
            f"({(refus_dossier or 'aucun refus')[:70]}…)")

        # --- la bande, la méthode et le secteur de l'entraînement ----------------------------
        # Ils partent DANS le modèle, et c'est le modèle qu'on relit ici — pas le résultat, qui
        # pourrait les annoncer sans que `_entrainer` les ait passés à `MIModel`. Un modèle appris
        # sur 8-30 Hz qui se dirait appris sur 4-40 Hz ne lèverait rien : il décoderait moins bien.
        import joblib

        from core.mi_decoder import sous_bandes
        from core.modes.contract import validate

        defaut = joblib.load(res["modele"])
        chk(tuple(defaut.band) == MI_BAND and defaut.method == MI_METHOD
            and defaut.secteur_hz == SECTEUR_HZ,
            f"sans réglage, et sans secteur annoncé par le moteur, le modèle porte la bande de "
            f"toujours, la méthode du dépôt et le secteur par défaut ({defaut.band}, "
            f"{defaut.method}, {defaut.secteur_hz})")

        valeurs, raison = validate(CALIB, {})
        chk(raison is None and bande_de(valeurs, (0.0, 0.0)) == MI_BAND
            and valeurs.get("fbcsp") is False,
            f"les réglages d'« Entraîner » : la bande de toujours et FBCSP décoché par défaut "
            f"({raison or valeurs})")
        chk(valeurs and tuple(valeurs.get("taches", ())) == ("LEFT", "RIGHT"),
            f"…et DEUX tâches par défaut, les poings "
            f"({valeurs and valeurs['taches']})")

        # --- LES TÂCHES SE RÈGLENT ---------------------------------------------------------
        # Pieds/mains au lieu de poing droit/poing gauche : l'écran nomme la tâche tapée, le
        # modèle apprend CES classes, et le flux les publie sous ces noms. « repos » tapé en minuscules redevient REST, la classe d'origine.
        dossier_libre = _os.path.join(dossier, "libre")
        chk([canonique(t) for t in ("left", "Right", "REST", "gauche", "DROITE", "repos", "Pieds")]
            == ["LEFT", "RIGHT", "REST", "LEFT", "RIGHT", "REST", "Pieds"],
            "les classes d'origine se tapent en anglais ou en français, en majuscules ou non, et "
            "deviennent toujours LEFT, RIGHT, REST (les noms que reçoit l'application) ; une autre "
            "tâche garde son nom")
        libre = MICalibration(_mi.SPEC, {"taches": ("Pieds", "Mains", "repos"),
                                         "trials_per_class": 6, "mise_en_route_s": 1.0}, None,
                              rng=_random.Random(5), dossier=dossier_libre)
        libre.engine = _FauxMoteur(libre, rng, alias={"Pieds": "LEFT", "Mains": "RIGHT"})
        vues = {}
        croix = set()         # (étape, tâche, croix publiée)
        debuts_cue, durees_cue = {}, []
        t = 0.0
        for _ in range(20000):
            libre.tick(libre.engine, t)
            if libre.etape == "cue" and "cue" not in debuts_cue:
                debuts_cue["cue"] = t
            elif libre.etape != "cue" and "cue" in debuts_cue:
                durees_cue.append(t - debuts_cue.pop("cue"))
            if libre.phase in ("echauffement", "essais"):
                croix.add((libre.etape, libre.classe if libre.etape != "repos" else "",
                           libre.state(now=t)["croix"]))
            if libre.classe:
                vues.setdefault(libre.classe, (libre.instruction(), libre.rappel()))
            if libre.terminee:
                break
            t += 0.25
        res_l = libre.resultat or {}
        chk(libre.phase == "fini" and libre.classes == ("Pieds", "Mains", "REST")
            and res_l.get("classes") == ["Pieds", "Mains", "REST"] and res_l.get("n_essais") == 18,
            f"des tâches libres : la séance cue CES tâches, « repos » redevient REST "
            f"({libre.phase}, {res_l.get('classes')}, {res_l.get('n_essais')} essais)")
        chk(vues.get("Pieds") == (tr("calib.mi.instruction.tache", tache="Pieds"),
                                  tr("calib.mi.rappel.tache"))
            and vues.get("REST") == (INSTRUCTIONS["REST"], ""),
            f"l'écran NOMME la tâche tapée ; REST garde sa consigne validée, sans rappel ({vues})")
        appris = MIModel.load(res_l["modele"]) if res_l.get("modele") else None
        from core.lsl_io import mi_channel_labels
        chk(appris is not None and list(appris.labels) == ["Pieds", "Mains", "REST"]
            and mi_channel_labels(appris.labels)[2:] == ["p_Pieds", "p_Mains", "p_REST"],
            f"le MODÈLE porte ces tâches, donc le flux publiera p_Pieds, p_Mains, p_REST "
            f"({appris and appris.labels})")
        attendu = {(e, c, True) for e in ("cue", "imagerie") for c in ("Pieds", "Mains", "REST")}
        attendu.add(("repos", "", False))
        chk(croix == attendu,
            f"la croix de fixation : pendant la mise en route ET l'imagerie de CHAQUE tâche, REST "
            f"compris, jamais pendant la pause ({sorted(croix)})")
        # La MISE EN ROUTE : jouée telle que réglée, et retenue par le modèle, par
        # l'enregistrement et par la ligne « Détails ».
        with np.load(res_l["enregistrement"]) as npz:
            archivee = float(npz["mise_en_route_s"]) if "mise_en_route_s" in npz.files else None
        chk(durees_cue and max(durees_cue) <= 1.0 + 0.25
            and getattr(appris, "mise_en_route_s", None) == 1.0 and archivee == 1.0
            and res_l.get("mise_en_route_s") == 1.0
            and tr("calib.mi.mise_en_route", s="1") in res_l.get("filtre", ""),
            f"la mise en route réglée (1 s) est jouée ({max(durees_cue or [0]):g} s au pas de "
            f"0,25 s), et retenue par le modèle, l'enregistrement et « Détails » "
            f"({getattr(appris, 'mise_en_route_s', None)}, {archivee}, {res_l.get('filtre')})")
        chk(validate(CALIB, {})[0]["mise_en_route_s"] == MI_CUE_S == 3.0
            and validate(CALIB, {"mise_en_route_s": 0.5})[0] is None,
            "…3 s par défaut (il faut ~2 s pour lancer l'imagination), et rien sous 1 s : refusé "
            "par le contrat")
        chk(res_l.get("hasard") == 1 / 3,
            f"le hasard suit le nombre de tâches ({res_l.get('hasard')})")

        # Les seuils du verdict sont RELATIFS AU HASARD : 60/45 % à 3 classes ; à 2, « 45 % » n'est plus « utilisable » — il est SOUS le hasard.
        chk([s for s, _t in VERDICTS] == [0.60, 0.45, 0.0]
            and [s for s, _t in table_pour(0.5)] == [0.70, 0.5875, 0.0],
            f"seuils : 60/45 % à 3 classes (inchangés), 70/59 % à 2 "
            f"({[s for s, _t in table_pour(0.5)]})")
        chk(verdict(0.45, hasard=0.5) == tr("calib.mi.verdict.faible")
            and verdict(0.45, hasard=1 / 3) == tr("calib.mi.verdict.utilisable"),
            "45 % est UTILISABLE à 3 classes, FAIBLE à 2 (le hasard y est à 50 %)")
        _v, raison = validate(CALIB, {"bande_bas": 12.0})
        chk(raison is not None,
            f"une coupure basse au-dessus de 10 Hz est REFUSÉE : elle couperait le mu ({raison})")
        # Les deux bords EXTÉRIEURS : sous 4 Hz la dérive et le regard,
        # au-dessus de 40 Hz l'EMG — ce que le FBCSP isolerait en sous-bandes et sélectionnerait.
        _v, refus_bas = validate(CALIB, {"bande_bas": 3.5})
        _v, refus_haut = validate(CALIB, {"bande_haut": 41.0})
        chk(refus_bas is not None and refus_haut is not None,
            f"une coupure basse sous 4 Hz et une haute au-dessus de 40 Hz sont REFUSÉES : dérive "
            f"et EMG ({refus_bas} | {refus_haut})")
        chk(validate(CALIB, {})[0]["lda_shrinkage"] is False,
            "la LDA à shrinkage est DÉCOCHÉE par défaut (jamais mesurée utile sur ce casque)")
        valeurs, raison = validate(CALIB, {"trials_per_class": 10, "bande_bas": 4.0,
                                           "bande_haut": 40.0, "fbcsp": True,
                                           "lda_shrinkage": True})
        chk(raison is None, f"une bande large avec FBCSP est acceptée ({raison})")

        # Une séance jouée avec ces réglages, par un moteur réglé sur le secteur des Amériques.
        # Dossier À PART : le décompte des fichiers de modèle, plus bas, porte sur `dossier`.
        dossier_regle = _os.path.join(dossier, "reglee")
        reglee = MICalibration(_mi.SPEC, {**valeurs, "trials_per_class": 6}, None,
                               rng=_random.Random(4), dossier=dossier_regle)
        reglee.engine = _FauxMoteur(reglee, rng)
        reglee.engine.secteur_hz = 60.0
        t = 0.0
        for _ in range(20000):
            reglee.tick(reglee.engine, t)
            if reglee.terminee:
                break
            t += 0.25
        res_r = reglee.resultat or {}
        chk(reglee.phase == "fini" and res_r.get("modele"),
            f"une séance réglée (4-40 Hz, FBCSP, secteur 60 Hz) aboutit "
            f"({reglee.phase} ; problème={reglee.probleme!r})")
        appris = joblib.load(res_r["modele"]) if res_r.get("modele") else None
        chk(appris is not None and tuple(appris.band) == (4.0, 40.0),
            f"le modèle ÉCRIT porte la bande réglée ({getattr(appris, 'band', None)})")
        banc = appris.pipe.named_steps.get("banc") if appris is not None else None
        chk(appris is not None and appris.method == "fbcsp" and banc is not None
            and banc.sous_bandes == sous_bandes((4.0, 40.0)),
            f"...la méthode réglée, dont le banc découpe CETTE bande "
            f"({getattr(appris, 'method', None)}, "
            f"{len(banc.sous_bandes) if banc is not None else 0} sous-bandes)")
        chk(appris is not None and appris.secteur_hz == 60.0 and banc is not None
            and banc.secteur_hz == 60.0,
            f"...et le secteur du MOTEUR, jusque dans le banc qui filtre "
            f"({getattr(appris, 'secteur_hz', None)})")
        chk(res_r.get("methode") == "fbcsp" and res_r.get("bande") == [4.0, 40.0]
            and res_r.get("secteur_hz") == 60.0,
            f"le résultat les rapporte, relus du modèle ({res_r.get('methode')}, "
            f"{res_r.get('bande')}, {res_r.get('secteur_hz')})")
        archive = {}
        if res_r.get("enregistrement"):
            with np.load(res_r["enregistrement"]) as npz:
                archive = {k: npz[k].tolist() for k in ("bande", "secteur_hz", "methode")
                           if k in npz.files}
        chk(archive == {"bande": [4.0, 40.0], "secteur_hz": 60.0, "methode": "fbcsp"},
            f"et l'ENREGISTREMENT les archive avec les époques : `research/mi_compare.py` rejoue "
            f"la séance avec son secteur ({archive})")
        chk(METHODES["fbcsp"] in res_r.get("filtre", "")
            and "4–40 Hz" in res_r.get("filtre", "") and "60 Hz" in res_r.get("filtre", "")
            and res_r.get("honnetete") == HONNETETE,
            f"et le repli « Détails » NOMME la méthode et la bande, sur sa propre ligne "
            f"({res_r.get('filtre', '')!r})")
        # La LDA à shrinkage cochée : apprise par le modèle, archivée avec les époques,
        # et dite dans « Détails ».
        with np.load(res_r["enregistrement"]) as npz:
            archive_s = bool(npz["lda_shrinkage"]) if "lda_shrinkage" in npz.files else None
        chk(appris is not None and appris.shrinkage is True
            and appris.pipe.named_steps["lda"].shrinkage == "auto" and archive_s is True
            and res_r.get("shrinkage") is True
            and tr("calib.mi.methode.shrinkage").strip() in res_r.get("filtre", ""),
            f"cochée, la LDA à shrinkage est APPRISE par le modèle, archivée, et dite dans "
            f"« Détails » ({res_r.get('filtre', '')!r}, archive {archive_s})")

        # --- `_chemins_libres` seule, avant l'intégration complète --------------------------
        # Une collision sur le premier essai force une avance d'exactement 1 s, sur les DEUX
        # chemins à la fois — c'est ce qui la rend testable indépendamment de toute séance.
        sonde_dossier = _os.path.join(dossier, "sonde")
        _os.makedirs(sonde_dossier, exist_ok=True)
        vrai_time = _time.time
        _time.time = lambda: 1_800_000_000.0
        try:
            m1, n1 = _chemins_libres(sonde_dossier, 7)
            open(m1, "wb").close()
            open(n1, "wb").close()
            m2, n2 = _chemins_libres(sonde_dossier, 7)
            # Le préfixe fait un nom DIFFÉRENT, donc un fichier différent : un candidat n'entre
            # jamais en collision avec un modèle définitif du même dossier, et réciproquement.
            m3, _n3 = _chemins_libres(sonde_dossier, 7, prefixe=CALIB_CANDIDAT_PREFIXE)
        finally:
            _time.time = vrai_time
        chk(_os.path.basename(m3) == CALIB_CANDIDAT_PREFIXE + _os.path.basename(m1)
            and not _os.path.exists(m3),
            f"le préfixe candidat s'applique au NOM, et le rend libre indépendamment "
            f"({_os.path.basename(m3)})")
        chk(m1 != m2 and n1 != n2,
            f"une collision force une avance sur les DEUX chemins "
            f"({_os.path.basename(m1)} -> {_os.path.basename(m2)})")
        chk(horodatage(1_800_000_001.0) in m2,
            f"et l'avance est de exactement 1 s, pas plus ({_os.path.basename(m2)})")

        # --- « rien n'est jamais écrasé » : preuve par DEUX séances, pas affirmation --------
        # Le format du nom (AAAAMMJJ-HHMMSS) a une résolution d'une SECONDE : deux séances
        # RÉUSSIES qui finissent la même seconde sont le cas où un nom fixe écraserait les
        # époques de la première. Horloge ÉPINGLÉE pour reproduire cette
        # collision à coup sûr plutôt que de compter sur la chance, restaurée dans un `finally`.
        vrai_time = _time.time
        _time.time = lambda: 1_700_000_000.0
        try:
            premiere = MICalibration(_mi.SPEC, {"taches": MI_LABELS, "trials_per_class": 6}, None,
                                     rng=_random.Random(2), dossier=dossier)
            premiere.engine = _FauxMoteur(premiere, rng)
            t = 0.0
            for _ in range(20000):
                premiere.tick(premiere.engine, t)
                if premiere.terminee:
                    break
                t += 0.25
            chk(premiere.phase == "fini",
                f"la première des deux séances à la même seconde aboutit ({premiere.phase})")

            # L'empreinte est prise ICI, entre les deux séances — c'est elle qui distingue
            # « le fichier a survécu » de « un fichier du même nom existe, peu importe lequel ».
            hash_modele_avant = (_hash_fichier(premiere.resultat["modele"])
                                 if premiere.resultat else None)
            hash_npz_avant = (_hash_fichier(premiere.resultat["enregistrement"])
                              if premiere.resultat else None)

            seconde = MICalibration(_mi.SPEC, {"taches": MI_LABELS, "trials_per_class": 6}, None,
                                    rng=_random.Random(3), dossier=dossier)
            seconde.engine = _FauxMoteur(seconde, rng)
            t = 0.0
            for _ in range(20000):
                seconde.tick(seconde.engine, t)
                if seconde.terminee:
                    break
                t += 0.25
            chk(seconde.phase == "fini",
                f"la seconde des deux séances à la même seconde aboutit ({seconde.phase})")
        finally:
            _time.time = vrai_time

        res1, res2 = premiere.resultat or {}, seconde.resultat or {}
        chk(bool(res1.get("modele")) and bool(res2.get("modele"))
            and res1["modele"] != res2["modele"],
            f"deux séances à la MÊME seconde produisent deux modèles DISTINCTS "
            f"({_os.path.basename(res1.get('modele', '?'))} vs "
            f"{_os.path.basename(res2.get('modele', '?'))})")
        chk(bool(res1.get("enregistrement")) and bool(res2.get("enregistrement"))
            and res1["enregistrement"] != res2["enregistrement"],
            f"et deux enregistrements DISTINCTS "
            f"({_os.path.basename(res1.get('enregistrement', '?'))} vs "
            f"{_os.path.basename(res2.get('enregistrement', '?'))})")
        # Les deux fichiers EXISTENT côte à côte, aucun n'a chassé l'autre. On regarde le disque
        # (`glob`) et non `modeles_disponibles` : un candidat est justement invisible à ce
        # catalogue-là, et exiger l'inverse ici testerait le contraire de la ligne du dessus.
        sur_disque = _glob.glob(_os.path.join(dossier, "*mi_model*.joblib"))
        chk(res1.get("modele") in sur_disque and res2.get("modele") in sur_disque,
            f"et les DEUX modèles sont sur le disque, aucun n'a chassé l'autre "
            f"({[_os.path.basename(p) for p in sur_disque]})")
        chk(hash_modele_avant is not None and bool(res1.get("modele"))
            and _hash_fichier(res1["modele"]) == hash_modele_avant,
            "le modèle de la PREMIÈRE séance est resté OCTET POUR OCTET intact après la seconde")
        chk(hash_npz_avant is not None and bool(res1.get("enregistrement"))
            and _hash_fichier(res1["enregistrement"]) == hash_npz_avant,
            "et son enregistrement aussi")

        # Même recoupement qu'au-dessus (verdict vs CV honnête), sur DEUX séances de plus : la
        # séance principale (`res`) ne suffit pas à elle seule à débusquer un `verdict(cv_naive)`
        # ici, ses deux CV tombent dans le MÊME palier — ces deux-ci, si : `cv_groupee`/`cv_naive`
        # encadrent une frontière de `VERDICTS` sur chacune (vérifié sur cette graine).
        chk(res1.get("verdict") == verdict(res1.get("cv_groupee"), res1.get("n_essais"),
                                           res1.get("hasard"))
            and res2.get("verdict") == verdict(res2.get("cv_groupee"), res2.get("n_essais"),
                                               res2.get("hasard")),
            f"et sur ces deux séances aussi, le verdict recoupe la CV honnête, pas la naïve "
            f"(séance 1 : {res1.get('verdict')!r} pour honnête {res1.get('cv_groupee')!r}, "
            f"naïve {res1.get('cv_naive')!r} ; séance 2 : {res2.get('verdict')!r} pour honnête "
            f"{res2.get('cv_groupee')!r}, naïve {res2.get('cv_naive')!r})")

        chk(verdict(0.70) == "EXCELLENT" and verdict(0.50) == "UTILISABLE"
            and verdict(0.40).startswith("FAIBLE"),
            "les verdicts sont calés sur l'échelle HONNÊTE : 40 % n'est pas « utilisable »")

        # --- un chiffre que le hasard produit n'est pas « UTILISABLE » ---------------------
        # 14/30 à 3 classes = 47 %, au-dessus de la ligne orange (45 %), mais un tirage au hasard
        # fait aussi bien près d'une fois sur dix (p = 0,090). La couleur promet « nettement au-dessus du hasard » :
        # c'est le test binomial EXACT qui le dit, par la MÊME fonction que les tests.
        try:
            v_ns = verdict(14 / 30, n_essais=30, hasard=1 / 3)
        except TypeError:
            v_ns = ""
        lignes_de = globals().get("lignes_de")
        aff_ns = lignes_de(14 / 30, 30, 1 / 3) if callable(lignes_de) else {}
        chk(v_ns.startswith("NON SIGNIFICATIF") and "p = 0,090" in v_ns
            and aff_ns.get("niveau") == "faible" and aff_ns.get("mot") == "NON SIGNIFICATIF",
            f"14/30 à 3 classes n'est PAS distinguable du hasard : rouge, « NON SIGNIFICATIF », "
            f"et la p-value dans le verdict ({aff_ns.get('niveau')}, {v_ns[:60]!r})")
        aff_ok = lignes_de(21 / 30, 30, 1 / 3) if callable(lignes_de) else {}
        chk(aff_ok.get("niveau") == "bon"
            and verdict(21 / 30, n_essais=30, hasard=1 / 3) == "EXCELLENT",
            f"…tandis que 21/30 l'est, et garde la table ({aff_ok.get('niveau')})")
        chk(callable(lignes_de) and not verifier({**aff_ns, "verdict": v_ns})
            and not verifier({**aff_ok, "verdict": "EXCELLENT"}),
            "…et le MOT ouvre le verdict dans les deux cas : un seul calcul")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    chk(empreinte_dossier() == empreinte_avant,
        "AUCUN fichier n'a bougé dans le vrai `data/` — il porte des enregistrements EEG d'une "
        "personne identifiable, et son modèle le plus récent est celui que le moteur ÉLIT")

    print(f"[mi-calib] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
