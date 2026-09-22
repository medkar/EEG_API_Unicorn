"""Le TEST de l'ErrP : le protocole d'entraînement, avec le moteur qui DÉCIDE au lieu d'apprendre.

La fenêtre joue sa séance d'entraînement (`src/stimulus/errp.py --calibrer`) : le point avance vers
la pastille, commet des erreurs DÉLIBÉRÉES, et chaque `feedback` part avec `error: true|false`. Le
moteur décide à chaque feedback avec ton modèle et ton réglage ; on compare. Rien sur le disque.

1. 🔴 **LA CLOISON : la vérité atteint le CORRECTEUR, JAMAIS le DÉCODEUR.** BCI PASSIVE : en
   décodage le marqueur est nu, parce que donner la réponse au décodeur rendrait faux tout ce qu'on
   mesure. Ici elle voyage sur le marqueur même qui délimite l'époque — une fuite donnerait un score
   parfait et faux, EN SILENCE. Deux murs : le socle RETIRE `error` avant que ce fichier ne voie le
   marqueur et ne la rend qu'à `_consigner`, APRÈS la décision ; et le décodeur ne reçoit jamais le
   moteur, seulement une `_VueEEG` — le vrai moteur garde dans `_marqueurs` la file où les feedbacks
   attendent AVEC leur étiquette. Tenus par un test d'ABSENCE sur un décodeur ESPION (`_selftest`).
2. **LA DÉCISION EST CELLE DU MODE** : un `ErrPRuntime` — ton modèle, le seuil qu'il déduit de
   « Bonnes commandes gardées », son rejet d'artefact —, comparé dans l'autotest à ce que
   `decoded_errp` publie.
3. **UN ESSAI = UN FEEDBACK = UNE DÉCISION** : erreur, bonne commande, ou PAS DE VERDICT (-1 :
   artefact, époque perdue). Un -1 n'est NI une erreur attrapée NI une bonne commande gardée : il
   compte À PART.
4. **LE SCORE EST UN COUPLE** — bonnes commandes gardées, erreurs attrapées, chacune avec SON Wilson.
   Pas de hasard unique, c'est un détecteur : au hasard il attraperait autant d'erreurs qu'il annule
   de bonnes commandes, et le test exact de Fisher dit si l'écart dépasse le bruit.

⚠️ **La référence d'artefact** : le mode prend 8 s de repos sur une piste immobile. La fenêtre
`--calibrer` n'en joue pas, mais tient sa piste IMMOBILE 15 s après son lancement, ce qui déborde la
chauffe du moteur : le repos est pris là, par le `_rest_step` du mode, clos au premier pas s'il n'a
pas eu ses 8 s. Sa durée réelle est dans le résultat.

Autotest :
    python src/core/modes/errp_test.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
import numpy as np  # noqa: E402
from scipy.stats import fisher_exact  # noqa: E402

from core.config import (ERRP_EPOCH_S, ERRP_ERROR_RATE, ERRP_FEEDBACK_S,  # noqa: E402
                         ERRP_TNR_TARGET, use_utf8_console)
from core.errp_track import (PAUSE_FIN_COURSE_S, PAUSE_INTER_PAS_S,  # noqa: E402
                             PAUSE_NOUVELLE_COURSE_S)
from core.modes.affichage import lignes, non_mesure, pct  # noqa: E402
from core.modes.contract import Param  # noqa: E402
from core.modes.errp import SPEC as SPEC_ERRP  # noqa: E402
# Le seuil d'ALARME de rejet du mode (« plus un clignement occasionnel ») : repris, pas redéfini.
from core.modes.errp import _TAUX_REJET_ALARME, ErrPRuntime  # noqa: E402
# Les consignes de l'entraînement, son seuil de significativité, la longueur moyenne d'une course.
from core.modes.errp_calib import BRIEFING as BRIEFING_ENTRAINEMENT  # noqa: E402
from core.modes.errp_calib import PERM_ALPHA, _PAS_PAR_COURSE  # noqa: E402
from core.modes.mesure import MesureSpec  # noqa: E402
from core.modes.mesure_marqueurs import (MesureMarqueurs,  # noqa: E402
                                         params_du_mode_pour_un_test, reglages_du_decideur)
from core.modes.ssvep_mesure import wilson  # noqa: E402

# Le repère : la séance de référence (200 essais, une personne), réglage par défaut. ⚠️ Taux
# OPTIMISTES (seuil choisi sur les scores qui les mesurent), mais cohérents avec l'AUC hors-pli 0,776
# sous un modèle binormal : c'est la courbe du projet, prise à 85 %. Le vert exige son ÉCART
# (attrapées − annulées) : sur ~20 erreurs, un détecteur au repère le franchit une fois sur deux.
REPERE_TPR, REPERE_TNR = 0.500, 0.855
REPERE_ECART = REPERE_TPR - (1.0 - REPERE_TNR)
REJET_MAX_BON = _TAUX_REJET_ALARME

# Des PAS de la piste, l'unité de `--essais`. Simulé au repère (27 % d'erreurs, Fisher unilatéral à
# 5 %) : 40 pas le distinguent du hasard une fois sur deux, 80 dans 87 % des cas, 200 (la longueur
# de l'entraînement) presque toujours. Défaut COURT : on re-teste à chaque réglage.
ESSAIS = (40, 80, 200)
ESSAIS_DEFAUT = 80


def _duree_protocole_s(essais):
    """La formule de `ErrPCalibration.duree_protocole_s`, pour `essais` pas (comparée à 200)."""
    return (essais * (ERRP_FEEDBACK_S + PAUSE_INTER_PAS_S)
            + (essais / _PAS_PAR_COURSE)
            * (PAUSE_FIN_COURSE_S + PAUSE_NOUVELLE_COURSE_S - PAUSE_INTER_PAS_S)
            + PAUSE_NOUVELLE_COURSE_S + ERRP_EPOCH_S)


def _label(cle):
    """Le libellé d'un réglage du mode : la réserve nomme le champ que l'étudiant a sous les yeux."""
    return next(p.label for p in SPEC_ERRP.params if p.key == cle)


class _Frequence:
    __slots__ = ("fs",)

    def __init__(self, fs):
        self.fs = float(fs)


class _VueEEG:
    """🔴 CE QUE LE DÉCODEUR VOIT DU MOTEUR : le tampon EEG horodaté et sa fréquence. RIEN d'autre —
    ni `markers_murs`, ni `_marqueurs`, où la réponse attend. Reconstruite à chaque appel."""
    __slots__ = ("acq", "recent", "recent_ts", "instance")

    def __init__(self, engine):
        self.acq = _Frequence(engine.acq.fs)
        self.recent = getattr(engine, "recent", None)
        self.recent_ts = getattr(engine, "recent_ts", None)
        self.instance = "errp_test"


class _DecideurErrP(ErrPRuntime):
    """Le runtime du MODE. Seul `_log` est coupé (« [errp] ERREUR détectée » ferait croire que le mode
    tourne) ; jamais ouvert, donc `_publish` ne pousse rien sur le réseau."""

    def _log(self, error, score, artefact):
        pass


class MesureErrP(MesureMarqueurs):
    """Le protocole d'entraînement ErrP, rejoué ; le moteur décide à chaque feedback."""

    marker_mode_id = "errp"
    runtime_cls_du_mode = ErrPRuntime
    evenement_verite = evenement_unite = "feedback"     # la vérité voyage SUR l'unité
    champ_verite = "error"
    epoque_marqueur_s = SPEC_ERRP.marker_epoch_s
    _classe_decideur = _DecideurErrP                     # pour que l'autotest y glisse son ESPION

    def __init__(self, spec, params, engine, rng=None):
        # AVANT le socle : un modèle effacé depuis la validation lève ici, avec la raison du mode.
        # 🔴 Sur une VUE lui aussi : un runtime GARDE le moteur qu'on lui donne à la construction.
        self._decideur = self._classe_decideur(
            SPEC_ERRP, reglages_du_decideur(SPEC_ERRP, params), _VueEEG(engine))
        super().__init__(spec, params, engine, rng=rng)
        self._maintenant = self._repos_debut = self._dernier_repos = None
        self._repos_s = None           # durée RÉELLE de la référence d'artefact
        self._derniere_epoque = None   # la dernière prélevée par le socle (autotest : alignement)

    def tick(self, engine, now):
        self._maintenant = now
        super().tick(engine, now)

    def duree_estimee_s(self):
        n = self._essais_annonces or int(self.params.get("essais") or ESSAIS_DEFAUT)
        return float(self.warmup_s) + _duree_protocole_s(n)

    def instruction(self):
        if self.phase == "essais" and self._decideur._sigmas_repos is None:
            return "Regarde la piste immobile, sans bouger : le moteur mesure ton bruit de fond."
        return super().instruction()

    def rappel(self):
        if self.phase == "essais" and self._decideur._sigmas_repos is None:
            return "ne cligne pas maintenant : c'est la référence du rejet d'artefact"
        return super().rappel()

    # --- la référence d'artefact : le repos du MODE --------------------------------------

    def _ouvrir_les_essais(self, now):
        super()._ouvrir_les_essais(now)
        self._maintenant = self._repos_debut = now
        self._decideur._rest_until = now + self._decideur._rest_s

    def _pendant_les_essais(self, engine, now):
        """`_rest_step` du mode, à SA cadence, tant que la fenêtre tient sa piste immobile."""
        dec = self._decideur
        if dec._sigmas_repos is not None or (
                self._dernier_repos is not None and now - self._dernier_repos < dec.period_s()):
            return
        self._dernier_repos = now
        if dec._rest_step(_VueEEG(engine), now):
            self._repos_s = now - self._repos_debut

    def _reference_prete(self, engine):
        """Si la fenêtre joue son premier pas avant les 8 s du mode, le repos est clos sur ce qu'il a
        mesuré, par le MÊME `_rest_step`, échéance ramenée à maintenant. False si une voie est
        MORTE : le mode refuserait de conclure, et décider sans référence mesurerait un décodeur
        que personne n'utilise."""
        dec = self._decideur
        if dec._sigmas_repos is None:
            dec._rest_until = self._maintenant
            dec._rest_step(_VueEEG(engine), self._maintenant)
            if dec._sigmas_repos is None:
                return False
            self._repos_s = self._maintenant - self._repos_debut
        return True

    # --- les marqueurs -------------------------------------------------------------------

    def _verite_lisible(self, valeur):
        """Un BOOLÉEN strict : `1`, `"true"` ou un feedback sans champ (fenêtre lancée sans
        `--calibrer`) ne se devinent pas — deviner une vérité, c'est risquer de l'inverser."""
        return valeur if isinstance(valeur, bool) else None

    def _encaisser_protocole(self, engine, ts, marqueur):
        """Un feedback, UNE décision — prise ICI, le marqueur NU (le socle a retiré `error`) :
        l'époque par le socle (avancement, pertes), la DÉCISION par le runtime du mode sur une
        `_VueEEG`, puis `_consigner`, où SEULEMENT la vérité rejoint la décision déjà prise."""
        if marqueur.get("event") != "feedback":
            return      # un événement inconnu s'ignore : le protocole grandira
        if not self._reference_prete(engine):
            self._abandonne(
                "la référence d'artefact n'a pas pu être mesurée sur la piste immobile : une voie "
                "a un σ NUL (électrode décollée, câble, amplificateur en butée — le journal du "
                "moteur la nomme). Le mode refuserait de décoder ainsi ; le test aussi. Vérifie "
                "le contact, puis relance le test.")
            return
        self._derniere_epoque = self._prelever(engine, ts)
        dec = self._decideur
        dec._decoded = None
        dec._traiter_feedback(_VueEEG(engine), ts)          # 🔴 la VUE, jamais `engine`
        sortie = dec.output()
        self._consigner({"error": int(sortie["error"]), "artifact": int(sortie["artifact"]),
                         "score": float(sortie["score"])})

    def _mesurer(self, enregistre, fs):
        if not enregistre:
            if self._verites_illisibles:
                raise ValueError(
                    f"aucun essai noté : {self._verites_illisibles} feedback(s) sans étiquette "
                    f"« error » lisible — la fenêtre tourne-t-elle avec « --calibrer » ?")
            raise ValueError("aucun feedback reçu pendant les essais : rien à noter")
        dec = self._decideur
        vise = float(self.params["tnr_target"])
        resultat = noter([(verite, obs["error"]) for obs, verite in enregistre], vise,
                         essais_demandes=int(self.params.get("essais") or 0) or None,
                         artefacts=sum(1 for obs, _v in enregistre if obs["artifact"]),
                         perdus=self._epoques_perdues, chauffe=self._marqueurs_chauffe,
                         promesse=dec.point_de_fonctionnement,
                         reglages={"model": _os.path.basename(str(self.params.get("model", ""))),
                                   "tnr_target": vise, "seuil": round(float(dec.seuil), 3),
                                   "essais": self.params.get("essais")})
        resultat["repos"] = {"secondes": round(float(self._repos_s or 0.0), 1),
                             "fenetres": (dec.rest_report or {}).get("fenetres")}
        return resultat


def noter(essais, tnr_vise, essais_demandes=None, artefacts=0, perdus=0, chauffe=0,
          promesse=None, reglages=None):
    """Le score. `essais` : `[(vérité, décision), ...]`, UN par feedback — vérité True = erreur
    délibérée ; décision 1 = erreur vue, 0 = bonne commande, -1 = PAS DE VERDICT.

    Niveaux (la console les peint, elle ne les recalcule pas) : `faible` si Fisher unilatéral ne
    distingue pas le couple du hasard (p ≥ `PERM_ALPHA`, le seuil de l'entraînement) ; `bon` si
    l'écart attrapées − annulées atteint celui du repère ET que moins de feedbacks restent sans
    verdict que le seuil d'alarme du mode ; `moyen` sinon. Sans erreur OU sans bonne commande
    jugée : NON MESURÉ — un taux sans effectif n'existe pas.
    """
    essais = [(bool(v), int(d)) for v, d in essais]
    n = len(essais)
    if n == 0:
        raise ValueError("aucun feedback noté : il n'y a rien à mesurer")
    jugees = [(v, d) for v, d in essais if d >= 0]       # 🔴 -1 : ni l'un, ni l'autre
    n_err = sum(1 for v, _d in jugees if v)
    n_ok = len(jugees) - n_err
    tp = sum(1 for v, d in jugees if v and d == 1)
    tn = sum(1 for v, d in jugees if not v and d == 0)
    n_sans = n - len(jugees)
    taux_sans = n_sans / n
    plus_long = max(ESSAIS)
    base = {
        "n_essais": n, "n_erreurs_jouees": sum(1 for v, _d in essais if v),
        "n_verdicts": len(jugees), "n_sans_verdict": n_sans, "taux_sans_verdict": round(taux_sans, 3),
        "n_artefacts": int(artefacts), "n_perdus": int(perdus), "n_chauffe": int(chauffe),
        "n_erreurs": n_err, "n_bonnes": n_ok, "n_attrapees": tp, "n_gardees": tn,
        "tnr_vise": float(tnr_vise), "decisions": essais, "reglages": dict(reglages or {}),
        "promesse": {k: float(v) for k, v in (promesse or {}).items()},
        "repere": {"tpr": REPERE_TPR, "tnr": REPERE_TNR, "ecart": round(REPERE_ECART, 3)},
        "honnetete": HONNETETE,
    }
    sans_txt = (f"{n_sans} SANS VERDICT (-1 : {artefacts} artefact(s), {perdus} époque(s) perdue(s)) "
                f"comptent à part — ni erreur attrapée, ni bonne commande gardée" if n_sans
                else "aucun n'est resté sans verdict")
    if n_err == 0 or n_ok == 0:
        raison = (f"aucun verdict sur {n} feedbacks" if not jugees else
                  f"aucune {'ERREUR' if n_err == 0 else 'BONNE commande'} jugée sur {n} feedbacks")
        conseil = ("Presque tout est resté sans verdict : vérifie le contact de Fz/Cz/Pz et cligne "
                   "moins quand le point bouge, puis re-teste." if taux_sans >= REJET_MAX_BON
                   else f"Refais le test à {plus_long} essais.")
        return {**base, **non_mesure(raison, conseil),
                "verdict": f"NON MESURÉ — {raison} : un taux sans effectif n'existe pas ; {sans_txt}."}

    tpr, tnr = tp / n_err, tn / n_ok
    fpr = 1.0 - tnr
    tpr_bas, tpr_haut = (float(x) for x in wilson(tp, n_err))
    tnr_bas, tnr_haut = (float(x) for x in wilson(tn, n_ok))
    p = float(fisher_exact([[tp, n_err - tp], [n_ok - tn, tn]], alternative="greater")[1])
    ecart = tpr - fpr

    if p >= PERM_ALPHA:
        niveau, mot = "faible", "FAIBLE"
    elif ecart >= REPERE_ECART and taux_sans < REJET_MAX_BON:
        niveau, mot = "bon", "AU NIVEAU DU REPÈRE"
    else:
        niveau, mot = "moyen", "UTILISABLE"

    # Les DEUX taux, chacun à SA place, et le hasard d'un détecteur : la diagonale.
    chiffres = (f"garde {pct(tnr)} des bonnes commandes, attrape {pct(tpr)} des erreurs (hasard : "
                f"{pct(fpr)}, autant qu'il en annule) · {n_err} erreurs sur {len(jugees)} verdicts")

    label = _label("tnr_target")
    if niveau == "faible" and (essais_demandes or 0) < plus_long:
        reserve = (f"À {n_err} erreurs jugées, on ne distingue pas ce détecteur du hasard : refais "
                   f"le test à {plus_long} essais avant de juger.")
    elif niveau == "faible":
        reserve = ("Indistinguable du hasard même sur un test long : réentraîne — saline Fz/Cz/Pz, "
                   "et n'ANTICIPE pas les erreurs.")
    elif taux_sans >= REJET_MAX_BON:
        reserve = (f"{pct(taux_sans)} des feedbacks sans verdict (artefact, époque perdue) : cligne "
                   f"moins quand le point bouge, vérifie le contact, puis re-teste.")
    elif tnr_haut < tnr_vise:
        reserve = (f"Il garde moins de bonnes commandes que demandé ({pct(tnr)} pour "
                   f"{pct(tnr_vise)}) : le seuil de l'entraînement est optimiste — monte « {label} "
                   f"», puis re-teste.")
    elif ecart < REPERE_ECART and abs(tnr_vise - ERRP_TNR_TARGET) > 0.05:
        reserve = (f"Le repère est pris à « {label} » = {pct(ERRP_TNR_TARGET)} ; à {pct(tnr_vise)}, "
                   f"même un bon détecteur sépare moins — re-teste à {pct(ERRP_TNR_TARGET)} avant "
                   f"de réentraîner.")
    elif ecart < REPERE_ECART:
        reserve = (f"Mieux que le hasard, moins bien que le repère : réentraîne (saline Fz/Cz/Pz, "
                   f"n'anticipe pas) — bouger « {label} » échange un taux contre l'autre, sans rien "
                   f"gagner.")
    else:
        reserve = ("Mesuré sur des essais NEUFS de CETTE séance : re-teste après une pause avant de "
                   "transcrire ce réglage dans ton application.")

    verdict = (
        f"{mot} — sur {n} FEEDBACKS (un essai = un feedback = une décision), le moteur en a jugé "
        f"{len(jugees)} ; {sans_txt}. Parmi les {n_ok} BONNES commandes jugées, il en a gardé "
        f"{tn}, soit {pct(tnr)} [IC95 {tnr_bas * 100:.0f} ; {tnr_haut * 100:.0f}] pour "
        f"{pct(tnr_vise)} visées ; parmi les {n_err} ERREURS délibérées jugées, il en a attrapé "
        f"{tp}, soit {pct(tpr)} [IC95 {tpr_bas * 100:.0f} ; {tpr_haut * 100:.0f}]. Au hasard, il "
        f"attraperait autant d'erreurs qu'il annule de bonnes commandes ({pct(fpr)}) : test exact "
        f"de Fisher, p = {p:.3f} — "
        f"{'au-dessus du hasard' if p < PERM_ALPHA else 'indistinguable du hasard'}. ")
    if promesse:
        verdict += (f"Sur sa propre calibration, ce modèle promettait {pct(promesse['tnr'])} gardées "
                    f"et {pct(promesse['tpr'])} attrapées à ce réglage — des taux OPTIMISTES, "
                    f"mesurés sur les scores qui ont choisi le seuil. ")
    if chauffe:
        verdict += f"{chauffe} feedback(s) reçus pendant la stabilisation du casque ont été jetés. "
    verdict += (f"Repère du projet (réglage {pct(ERRP_TNR_TARGET)}, une personne) : "
                f"{pct(REPERE_TPR)} attrapées pour {pct(REPERE_TNR, 1)} gardées, un écart de "
                f"{REPERE_ECART * 100:.0f} points ; ici {ecart * 100:.0f}.")

    return {**base,
            "tpr": round(tpr, 3), "tnr": round(tnr, 3), "fpr": round(fpr, 3),
            "tpr_bas": round(tpr_bas, 3), "tpr_haut": round(tpr_haut, 3),
            "tnr_bas": round(tnr_bas, 3), "tnr_haut": round(tnr_haut, 3),
            "ecart": round(ecart, 3), "p_hasard": round(p, 4),
            **lignes(niveau, mot, chiffres, reserve), "verdict": verdict}


HONNETETE = (
    "Ce test mesure la règle du PRODUIT — ton modèle, le seuil que le moteur déduit de « Bonnes "
    "commandes gardées » sur les scores de TA calibration, le rejet d'artefact contre ton repos — "
    "sur des essais NEUFS : une décision par feedback, celle que `decoded_errp` publierait. La "
    "fenêtre publie la réponse de chaque pas ; elle va au correcteur, jamais au décodeur.\n"
    "Un feedback SANS VERDICT (-1 : artefact, ou époque perdue) compte à part : ni erreur "
    "attrapée, ni bonne commande gardée.\n"
    "Pas de hasard unique : c'est un DÉTECTEUR, pas un sélecteur. Au hasard, il attraperait autant "
    "d'erreurs qu'il annule de bonnes commandes ; le test exact de Fisher dit si l'écart entre les "
    "deux dépasse le bruit.\n"
    f"Repère : {pct(REPERE_TPR)} d'erreurs attrapées pour {pct(REPERE_TNR, 1)} de bonnes commandes "
    "gardées (réglage 85 %, 200 essais, une personne) — des taux OPTIMISTES, le seuil ayant été "
    "choisi sur les scores qui les mesurent. C'est ce que ce test corrige : attends-toi à garder "
    "MOINS de bonnes commandes que visé. Sur une dizaine d'erreurs, en attraper cinq est le "
    "résultat attendu ; huit ou deux tiennent dans le bruit.\n"
    "La référence d'artefact est mesurée sur la piste IMMOBILE, entre la stabilisation du casque et "
    "le premier pas : 8 s au plus, souvent moins — le mode, lui, en prend 8 pleines."
)

BRIEFING = (
    ("Ce test rejoue l'ENTRAÎNEMENT, mais le moteur DÉCIDE au lieu d'apprendre : à chaque pas il "
     "dit s'il a vu une erreur, et on compare aux erreurs que la fenêtre commet exprès."),
) + tuple(BRIEFING_ENTRAINEMENT) + (
    "Au début, la piste reste IMMOBILE quelques secondes : ne bouge pas, le moteur mesure ton bruit "
    "de fond.",
    "Il faut un modèle entraîné : c'est lui qui décide, avec ton réglage « Bonnes commandes "
    "gardées ». Rien n'est écrit sur le disque — ce test rend un score, pas un modèle.",
)

SPEC = MesureSpec(
    id="errp_test",
    label="Tester l'ErrP",
    summary="Le protocole d'entraînement, rejoué : le moteur décide avec ton modèle et ton réglage, "
            "et on compare aux erreurs que la fenêtre commet exprès.",
    briefing=BRIEFING,
    # Les `Param` du MODE, les MÊMES objets : sans modèle, `contract.validate` refuse le test avec
    # la raison du mode — pas l'interface. La console passe les réglages courants tels quels. SAUF
    # le flux de marqueurs : un test écoute celui de sa fenêtre (`mesure_marqueurs.CLE_FLUX`).
    params=params_du_mode_pour_un_test(SPEC_ERRP) + (
        Param(
            key="essais",
            label="Essais",
            kind="choice",
            default=ESSAIS_DEFAUT,
            choices=ESSAIS,
            help=("Des pas de la piste, un verdict par pas. Court par défaut, parce qu'on refait ce "
                  "test à chaque réglage — mais la part d'erreurs attrapées se mesure sur les seules "
                  f"erreurs délibérées (~{pct(ERRP_ERROR_RATE)} des pas) : "
                  + ", ".join(f"{n} ≈ {(MesureErrP.warmup_s + _duree_protocole_s(n)) / 60:.1f} "
                              f"min (~{n * ERRP_ERROR_RATE:.0f} erreurs)".replace(".", ",")
                              for n in ESSAIS)
                  + f". {max(ESSAIS)} est la longueur de l'entraînement : prends-le pour TRANCHER "
                    f"quand le verdict dit que l'intervalle est trop large."),
        ),
    ),
    runtime_cls=MesureErrP,
    stimulus_id="errp",
)


def _porte_la_verite(obj, profondeur=0, vus=None):
    """La vérité-terrain est-elle ATTEIGNABLE depuis `obj` ? Un booléen nu passé en argument, ou un
    marqueur portant encore `error: true|false`, n'importe où à quatre niveaux (attributs,
    conteneurs, objet d'une méthode liée). ⚠️ `type(...) is bool` : la SORTIE du décodeur a aussi
    une clé `error`, mais entière (-1, 0, 1) — sa réponse, pas la vérité."""
    import inspect

    vus = set() if vus is None else vus
    if type(obj) is bool:
        return profondeur == 0
    if (profondeur > 4 or id(obj) in vus
            or isinstance(obj, (str, bytes, int, float, np.ndarray, type(None)))):
        return False
    vus.add(id(obj))
    if isinstance(obj, dict):
        if type(obj.get("error")) is bool:
            return True
        enfants = list(obj.values())
    elif isinstance(obj, (list, tuple, set)):
        enfants = list(obj)
    elif inspect.ismethod(obj):
        enfants = [obj.__self__]
    elif hasattr(obj, "__dict__"):
        enfants = list(vars(obj).values())
    elif hasattr(obj, "__slots__"):
        enfants = [getattr(obj, s, None) for s in obj.__slots__]
    else:
        return False
    return any(_porte_la_verite(e, profondeur + 1, vus) for e in enfants)


def _selftest():
    """Sur un modèle ErrP entraîné à la volée, dans un dossier TEMPORAIRE — jamais `data/`."""
    import json
    import shutil
    import tempfile

    from core import errp_models
    from core.config import DATA_DIR, ERRP_CAL_TRIALS, empreinte_dossier
    from core.errp_decoder import ErrPModel, synth_errp_epoch
    from core.modes.affichage import NIVEAUX, verifier
    from core.modes.contract import validate
    from core.modes.errp_calib import ErrPCalibration

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    empreinte_avant = empreinte_dossier(DATA_DIR)
    FS, SOA, T0 = 250.0, 1.45, 1000.0     # T0 : premier tick (horloge LSL = horloge du test)
    pre_s, post_s = ErrPRuntime.pre_s, ErrPRuntime.post_s
    n_pre, n_post = int(round(pre_s * FS)), int(round(post_s * FS))

    class _FausseAcq:
        fs = FS

    class _FauxMoteur:
        """Un tampon GLISSANT de 5 s, et la file `_marqueurs` du vrai `EngineServer` : les marqueurs
        tels qu'ARRIVÉS, étiquette comprise — un décodeur qui recevrait ce moteur y lirait la
        réponse. `markers_murs` : la règle du vrai, en court (rendu une fois MÛR, un curseur/mode)."""

        def __init__(self, eeg, ts, marqueurs, garde_s=5.0):
            self.acq, self._eeg, self._ts = _FausseAcq(), eeg, ts
            self._a_venir = sorted(marqueurs, key=lambda m: m[0])
            self._marqueurs, self._curseurs, self._garde = [], {}, int(garde_s * FS)
            self.avancer(float(ts[0]) + garde_s)

        def avancer(self, t):
            fin = int(np.searchsorted(self._ts, t, side="right"))
            self.recent = self._eeg[max(0, fin - self._garde):fin]
            self.recent_ts = self._ts[max(0, fin - self._garde):fin]
            while self._a_venir and self._a_venir[0][0] <= t:
                self._marqueurs.append(self._a_venir.pop(0))

        def markers_murs(self, mode_id, post_s):
            dernier, plus_vieux = float(self.recent_ts[-1]), float(self.recent_ts[0])
            i, murs = self._curseurs.get(mode_id, 0), []
            while i < len(self._marqueurs) and self._marqueurs[i][0] + post_s <= dernier:
                ts, m = self._marqueurs[i]
                i += 1
                if m.get("mode") == mode_id and ts >= plus_vieux:
                    murs.append((ts, m))
            self._curseurs[mode_id] = i
            return murs

    def seance(n_pas, graine=0, amp=1.2, decalage_s=3.0, artefact_a=None):
        """La fenêtre `--calibrer` : `calib_start`, piste immobile jusqu'à `decalage_s` après la
        chauffe, un feedback ÉTIQUETÉ par pas, un ErrP synthétique planté sur chaque ERREUR."""
        rng = np.random.default_rng(graine)
        verites = [(i % 3 == 0) if i < 9 else bool(rng.random() < 0.3) for i in range(n_pas)]
        instants = [T0 + 15.0 + decalage_s + SOA * i for i in range(n_pas)]
        fin = instants[-1] + post_s + 0.15
        ts = np.arange(T0 - 6.0, fin + 4.0, 1.0 / FS)
        eeg = rng.normal(0.0, 2.0, (len(ts), 8)) + 0.7 * np.sin(2 * np.pi * 10 * ts)[:, None]
        for i, (instant, erreur) in enumerate(zip(instants, verites)):
            j = int(np.searchsorted(ts, instant))
            if erreur:
                onde = synth_errp_epoch(True, fs=FS, pre_s=pre_s, post_s=post_s, amp=amp,
                                        noise=0.0, rng=rng)[:n_pre + n_post]
                eeg[j - n_pre:j + n_post] += onde - onde.mean(axis=0)
            if i == artefact_a:                        # un sursaut : σ ~100 fois le repos
                eeg[j - n_pre:j + n_post] += rng.normal(0.0, 200.0, (n_pre + n_post, 8))
        marqueurs = ([(T0 + 1.0, {"mode": "errp", "event": "calib_start", "trials": n_pas})]
                     + [(t, {"mode": "errp", "event": "feedback", "error": v})
                        for t, v in zip(instants, verites)]
                     + [(fin, {"mode": "errp", "event": "calib_end"})])
        return marqueurs, eeg, ts, verites

    def jouer(rt, moteur, pas=0.1):
        t = T0
        while t <= float(moteur._ts[-1]) and not rt.terminee:
            moteur.avancer(t)
            rt.tick(moteur, t)
            t += pas
        return rt.resultat

    vrai_dispo = errp_models.modeles_disponibles
    dossier = tempfile.mkdtemp(prefix="errp_test_")
    try:
        # Un modèle jetable, entraîné sur de l'ErrP synthétique (la recette de `modes/errp.py`).
        rng = np.random.default_rng(1)
        y = [(i % 3 == 0) for i in range(60)]
        X = [synth_errp_epoch(e, fs=FS, amp=1.2, rng=rng) for e in y]
        chemin = _os.path.join(dossier, "errp_model_test.joblib")
        modele = ErrPModel(fs=FS).fit(np.asarray(X), np.asarray(y, dtype=int),
                                      groups=np.asarray([i * 4 // 60 for i in range(60)]),
                                      n_perm=0)
        modele.save(chemin)
        fichiers_avant = sorted(_os.listdir(dossier))
        errp_models.modeles_disponibles = lambda d=dossier: vrai_dispo(d)
        valeurs = {"model": chemin, "tnr_target": 0.70, "essais": ESSAIS_DEFAUT}

        # === 1. 🔴 LA CLOISON : la vérité atteint le CORRECTEUR, JAMAIS le DÉCODEUR =============
        # Un test d'ABSENCE, donc par un décodeur ESPION qui note tout ce qu'on lui passe — à la
        # construction comme à chaque appel. La fenêtre joue `--calibrer` : la file porte la réponse.
        class _DecideurEspion(_DecideurErrP):
            def __init__(self, spec, params, engine):
                self.vu = [("__init__", (spec, params, engine))]
                super().__init__(spec, params, engine)

            def _traiter_feedback(self, engine, ts):
                self.vu.append(("_traiter_feedback", (engine, ts)))
                return super()._traiter_feedback(engine, ts)

            def _rest_step(self, engine, now):
                self.vu.append(("_rest_step", (engine, now)))
                return super()._rest_step(engine, now)

        class _MesureEspionnee(MesureErrP):
            _classe_decideur = _DecideurEspion

            def __init__(self, *args, **kwargs):
                self.recus = []
                super().__init__(*args, **kwargs)

            def _encaisser_protocole(self, engine, ts, marqueur):
                self.recus.append(dict(marqueur))
                super()._encaisser_protocole(engine, ts, marqueur)

        marqueurs, eeg, ts, verites = seance(24, artefact_a=10)
        moteur = _FauxMoteur(eeg, ts, marqueurs)
        rt = _MesureEspionnee(SPEC, valeurs, moteur)
        res = jouer(rt, moteur)
        espion = rt._decideur
        chk(rt.state(now=T0).get("unite") == "essai",
            f"l'avancement affiché compte des ESSAIS — l'unité du réglage « Essais » "
            f"({rt.state(now=T0).get('unite')!r})")
        appels = [a for nom, a in espion.vu if nom == "_traiter_feedback"]
        chk(len(appels) == len(verites) == 24,
            f"le décodeur a bien été appelé, une fois par feedback ({len(appels)} sur "
            f"{len(verites)}) — sans ça l'assertion suivante serait vraie à vide")
        fuites = [nom for nom, args in espion.vu if any(_porte_la_verite(a) for a in args)]
        chk(not fuites and rt.recus and not any("error" in m for m in rt.recus),
            f"…et la vérité ne lui a JAMAIS été passée, ni atteignable depuis ce qu'on lui passe, "
            f"ni au crochet de décodage — un décodeur qui la verrait rendrait un score parfait et "
            f"faux, en silence (fuites : {fuites[:3]})")
        chk([lab for _o, lab in rt._enregistre] == verites
            and (res or {}).get("n_erreurs_jouees") == sum(verites),
            f"…tandis que le CORRECTEUR l'a reçue, appariée à chaque décision, et l'a comptée "
            f"({[lab for _o, lab in rt._enregistre][:6]}…, {(res or {}).get('n_erreurs_jouees')} "
            f"erreurs pour {sum(verites)} jouées)")
        chk(_porte_la_verite(moteur) and _porte_la_verite(True)
            and not _porte_la_verite({"error": 1}),
            "…et le détecteur de fuite n'est pas aveugle : il trouve la réponse dans le MOTEUR et "
            "dans un booléen nu, pas dans la SORTIE du décodeur (entière)")

        # === 2. LA DÉCISION EST CELLE DU MODE ==================================================
        chk(issubclass(_DecideurErrP, ErrPRuntime)
            and all(getattr(_DecideurErrP, m) is getattr(ErrPRuntime, m)
                    for m in ("_traiter_feedback", "_est_artefact", "_rest_step", "_publish")),
            "le décideur EST le runtime du mode : époque, rejet d'artefact, repos et seuil hérités")
        chk(espion.point_de_fonctionnement["tnr_target"] == 0.70
            and espion.seuil != float(modele.threshold_),
            f"le seuil est celui que le MODE déduit de TON réglage (0,70 -> {espion.seuil:+.3f}), "
            f"pas celui de la calibration ({float(modele.threshold_):+.3f})")

        class _FauxPublieur:
            def __init__(self):
                self.lignes = []

            def push(self, error, score, seuil, artefact, lsl_ts=None):
                self.lignes.append((error, score, artefact))

        # En face, le chemin de DÉCODAGE : le vrai `ErrPRuntime`, la fenêtre SANS `--calibrer`
        # (marqueurs nus), le même repos. Chaque décision du test doit être CELLE qu'il publie.
        nus = [(t, {k: v for k, v in m.items() if k != "error"}) for t, m in marqueurs
               if m["event"] == "feedback"]
        moteur_nu = _FauxMoteur(eeg, ts, nus)
        direct = ErrPRuntime(SPEC_ERRP, reglages_du_decideur(SPEC_ERRP, valeurs), moteur_nu)
        direct._log = lambda *a: None
        direct._out, direct._opened, direct.phase = _FauxPublieur(), True, "running"
        direct._sigmas_repos = espion._sigmas_repos
        t = T0
        while t <= float(ts[-1]):
            moteur_nu.avancer(t)
            direct.tick(moteur_nu, t, t)
            t += 0.1
        # Le score au 1/1000, la précision de `output()` (le flux LSL, lui, le porte entier).
        publie = [(e, round(float(s), 3), a) for e, s, a in direct._out.lignes]
        consigne = [(o["error"], o["score"], o["artifact"]) for o, _v in rt._enregistre]
        chk(publie == consigne and len({e for e, _s, _a in consigne}) >= 2,
            f"chaque décision du test est EXACTEMENT celle que `decoded_errp` publie en décodage — "
            f"verdict, score, artefact ({[e for e, _s, _a in consigne]})")
        chk(consigne[10][0] == -1 and consigne[10][2] == 1 and res["n_artefacts"] == 1
            and res["n_sans_verdict"] == 1,
            f"…l'artefact planté est rejeté par la règle du mode (-1), et compté À PART "
            f"({consigne[10]}, {res['n_sans_verdict']} sans verdict)")
        chk(rt._derniere_epoque is not None
            and np.array_equal(rt._derniere_epoque, espion._derniere_epoque_scoree),
            "l'époque jugée par le décodeur est, à l'échantillon près, celle que le socle a prélevée")

        # === 3. LA RÉFÉRENCE D'ARTEFACT ========================================================
        noms = [nom for nom, _a in espion.vu]
        premier = noms.index("_traiter_feedback") if "_traiter_feedback" in noms else len(noms)
        chk("_rest_step" in noms[:premier] and "_rest_step" not in noms[premier:]
            and espion.rest_report["fenetres"] >= 10 and 3.0 <= res["repos"]["secondes"] < 8.0,
            f"le repos du MODE est mesuré sur la piste immobile, et clos AVANT la première décision "
            f"quand la fenêtre démarre avant 8 s ({res['repos']})")
        m_lent, e_lent, t_lent, _v = seance(6, graine=2, decalage_s=12.0)
        moteur = _FauxMoteur(e_lent, t_lent, m_lent)
        rt_lent = MesureErrP(SPEC, valeurs, moteur)
        res_lent = jouer(rt_lent, moteur)
        chk(rt_lent.phase == "fini" and abs(res_lent["repos"]["secondes"] - 8.0) < 0.3,
            f"…et une fenêtre lente lui laisse ses 8 s pleines, comme au mode ({res_lent['repos']})")
        m_mort, e_mort, t_mort, _v = seance(6, graine=3)
        e_mort[:, 3] = 0.0                             # C4 débranchée
        moteur = _FauxMoteur(e_mort, t_mort, m_mort)
        rt_mort = MesureErrP(SPEC, valeurs, moteur)
        jouer(rt_mort, moteur)
        chk(rt_mort.phase == "annule" and "σ NUL" in rt_mort.probleme and not rt_mort._enregistre,
            f"une voie MORTE : le mode refuserait de conclure son repos, le test s'annule en le "
            f"disant, sans une seule décision ({rt_mort.phase}, {rt_mort.probleme[:50]}…)")

        # === 4. LE SCORE ========================================================================
        def E(err_1, err_0, err_m1, ok_0, ok_1, ok_m1):
            """Erreurs jugées ERREUR / jugées bonnes / sans verdict, puis de même les bonnes."""
            return ([(True, 1)] * err_1 + [(True, 0)] * err_0 + [(True, -1)] * err_m1
                    + [(False, 0)] * ok_0 + [(False, 1)] * ok_1 + [(False, -1)] * ok_m1)

        r = noter(E(4, 4, 8, 30, 5, 5), 0.85, essais_demandes=80)
        chk(r["tpr"] == 0.5 and r["fpr"] == round(5 / 35, 3) and r["n_sans_verdict"] == 13
            and r["n_verdicts"] == 43,
            f"-1 n'est NI une erreur attrapée NI une bonne commande gardée : 4/8 attrapées (pas "
            f"12/16), 5/35 annulées (pas 10/40), 13 sans verdict à part ({r['tpr']}, {r['fpr']})")
        r = noter(E(5, 15, 0, 57, 3, 0), 0.85)
        chk(r["tpr"] == 0.25 and r["tnr"] == 0.95
            and "garde 95 % des bonnes commandes, attrape 25 % des erreurs" in r["chiffres"]
            and "gardé 57, soit 95 %" in r["verdict"] and "attrapé 5, soit 25 %" in r["verdict"],
            f"chaque taux à SA place, dans les chiffres ET dans le verdict ({r['chiffres']})")

        cas = {  # nom : (essais, visé, essais demandés, niveau attendu, mot-clé de la réserve)
            "bon": (E(12, 10, 2, 50, 8, 2), 0.85, 80, "bon", "après une pause"),
            "sous le repère": (E(25, 31, 0, 115, 29, 0), 0.85, 200, "moyen", "réentraîne"),
            "réglage extrême": (E(12, 44, 0, 138, 6, 0), 0.95, 200, "moyen", "re-teste à 85 %"),
            "trop de -1": (E(12, 10, 40, 50, 8, 50), 0.85, 200, "moyen", "sans verdict"),
            "garde trop peu": (E(20, 2, 0, 42, 18, 0), 0.85, 80, "bon", "monte « "),
            "hasard, court": (E(2, 9, 0, 25, 4, 0), 0.85, 40, "faible", "à 200 essais"),
            "hasard, long": (E(2, 9, 0, 25, 4, 0), 0.85, 200, "faible", "réentraîne"),
            "sans erreur": (E(0, 0, 11, 25, 4, 0), 0.85, 40, "faible", "200 essais"),
            "tout rejeté": (E(0, 0, 11, 0, 0, 29), 0.85, 40, "faible", "contact"),
        }
        notes = {}
        for nom, (ess, vise, demandes, niveau, mot_cle) in cas.items():
            r = notes[nom] = noter(ess, vise, essais_demandes=demandes)
            chk(r["niveau"] == niveau and mot_cle in r["reserve"],
                f"{nom} -> {r['niveau']} {r['mot']} | {r['chiffres']} | {r['reserve']}")
        chk(notes["sans erreur"]["mot"] == notes["tout rejeté"]["mot"] == "NON MESURÉ"
            and "aucun verdict" in notes["tout rejeté"]["chiffres"],
            "sans erreur jugée, ou sans aucun verdict : NON MESURÉ, pas un taux sur zéro essai")
        chk(notes["hasard, court"]["p_hasard"] >= PERM_ALPHA > notes["bon"]["p_hasard"],
            f"« faible » = Fisher ne distingue pas le couple du hasard "
            f"(p = {notes['hasard, court']['p_hasard']} contre {notes['bon']['p_hasard']})")
        for r in list(notes.values()) + [res, res_lent]:
            chk(not verifier(r) and r["niveau"] in NIVEAUX and r["honnetete"]
                and (r["mot"] == "NON MESURÉ" or "hasard" in r["chiffres"]),
                f"affichage cohérent : {r['mot']} {verifier(r)}")

        # === 5. LE CONTRAT ======================================================================
        chk(all(any(p is q for q in SPEC.params) for p in SPEC_ERRP.params if p.key != "stream_in")
            and SPEC.stimulus_id == "errp"
            and MesureErrP.epoque_marqueur_s == SPEC_ERRP.marker_epoch_s,
            "le test déclare les `Param` du MODE eux-mêmes, la fenêtre ErrP, et l'époque du mode")
        chk(abs(_duree_protocole_s(ERRP_CAL_TRIALS) - ErrPCalibration.duree_protocole_s) < 1e-9,
            f"la durée annoncée suit la formule de l'entraînement ({_duree_protocole_s(80):.0f} s "
            f"pour 80 pas)")
        vide = _os.path.join(dossier, "vide")
        _os.makedirs(vide)
        errp_models.modeles_disponibles = lambda d=vide: vrai_dispo(d)
        _v, raison = validate(SPEC, {})
        chk(raison is not None and "aucun choix disponible" in raison,
            f"sans modèle, le CONTRAT refuse le test, avec la raison du mode ({raison[:60]}…)")
        errp_models.modeles_disponibles = lambda d=dossier: vrai_dispo(d)
        v, raison = validate(SPEC, {"model": chemin})
        chk(v is not None and v["essais"] == ESSAIS_DEFAUT and v["tnr_target"] == ERRP_TNR_TARGET,
            f"avec un modèle il passe, test COURT par défaut ({raison or v['essais']})")
        try:
            json.dumps(rt.state(now=T0))
            serialisable = True
        except (TypeError, ValueError):
            serialisable = False
        chk(serialisable, "l'instantané, résultat compris, est sérialisable (il part dans `snapshot()`)")

        # === C2 : un TEST écoute le flux PAR DÉFAUT, et n'offre pas d'en choisir un autre ============
        # « Tester » lance TOUJOURS notre fenêtre, qui publie sur `MARKER_STREAM_DEFAULT`. Un test qui
        # héritait le « Flux de marqueurs » du mode (réglé sur l'appli de l'étudiant) écoutait un flux
        # où personne ne publiait : abandon à 30 s, fenêtre plein écran jouant dans le vide.
        from core.config import MARKER_STREAM_DEFAULT as _DEFAUT
        from core.modes.contract import validate as _valider
        from core.server import EngineServer as _Moteur_
        chk("stream_in" not in {p.key for p in SPEC.params},
            f"le test ne déclare PAS « Flux de marqueurs » ({[p.key for p in SPEC.params]})")
        _v, _raison = _valider(SPEC, {"stream_in": "MonAppli_ERRP"})
        chk(_v is None and "stream_in" in (_raison or ""),
            f"…et le contrat REFUSE qu'on le lui passe : brancher une appli, c'est « Connecter » "
            f"({_raison})")
        chk(_Moteur_._flux_attendu(rt) == _DEFAUT,
            f"le moteur écoute, pour ce test, le flux PAR DÉFAUT — celui de la fenêtre qu'il lance "
            f"({_Moteur_._flux_attendu(rt)})")
        chk(sorted(_os.listdir(dossier)) == sorted(fichiers_avant + ["vide"]),
            "aucune séance n'a rien écrit à côté du modèle")
    finally:
        errp_models.modeles_disponibles = vrai_dispo
        shutil.rmtree(dossier, ignore_errors=True)

    chk(empreinte_dossier(DATA_DIR) == empreinte_avant,
        f"`data/` est intact ({len(empreinte_avant)} fichiers avant, "
        f"{len(empreinte_dossier(DATA_DIR))} après)")
    print(f"[errp-test] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
