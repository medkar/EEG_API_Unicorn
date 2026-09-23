"""Le TEST du P300 : le protocole d'entraînement, avec le moteur qui SÉLECTIONNE au lieu d'apprendre.

La fenêtre lancée avec `--calibrer` joue exactement la séance d'entraînement : elle CERCLE une cible
par manche (`cue`), fait flasher les six (`flash`), ferme la manche (`round_end`). Ici, à chaque
`round_end`, le moteur sélectionne une cible avec TON modèle, et on compare à la cible cerclée. Un
score avec son niveau de hasard, **rien sur le disque**. La ligne du temps, la cloison de vérité et
l'épochage viennent du socle (`modes/mesure_marqueurs.py`, à lire avant).

--- LES QUATRE INVARIANTS ---------------------------------------------------------------------

1. **LA DÉCISION EST CELLE DU MODE.** Le décideur est un `P300Runtime` dont seul `_log` est coupé.
   Chaque `flash` et chaque `round_end` passent par SON `_run_step` : sa garde de cible, son
   plafond par cible, son épochage, ses deux refus (manche trop courte, cible jamais flashée), et
   `select` avec la marge de protocole. Une sélection réécrite ici passerait tous les tests par
   construction, et divergerait au premier changement du mode.

2. **UN ESSAI = UNE MANCHE = UNE DÉCISION**, celle que `decoded_p300` publiait au `round_end`. Les
   48 flashs d'une manche ne sont pas autant d'observations : la sélection les MOYENNE. L'effectif
   de Wilson est un nombre de manches. ⚠️ `self.essai` compte des FLASHS : c'est l'unité du
   `trials` que la fenêtre annonce, donc de la barre d'avancement — pas l'effectif.

3. **`-1` = « PAS DE DÉCISION », et c'est une sélection RATÉE.** À marge nulle
   (`P300_SELECT_MARGIN = 0`), le mode tranche TOUJOURS une manche complète : un -1 veut dire que
   des époques se sont perdues (liaison, tampon), pas que le modèle s'abstient. Ton application
   n'aurait rien reçu : la manche compte comme non sélectionnée, et la réserve en nomme la cause.
   (Si la marge monte un jour, le -1 devient une abstention, et le score un COUPLE comme le MI.)

4. **LE HASARD EST 1 / NOMBRE DE CIBLES DU MODE** — 1/6, 17 %. Jamais 1/2 : se tromper de hasard
   rend un verdict faux sans rien casser (8 manches sur 12 battent 1/6, pas 1/2).

⚠️ **Les réglages sont ceux du MODE** : la `SPEC` déclare les `Param` du mode P300 eux-mêmes (sans
modèle, `contract.validate` refuse le test avec la raison du mode), plus `essais` = le nombre de
MANCHES — l'unité de `--rounds`, que la console transmet par `stimulus/registry.option_compte`.
Tous, sauf le « Flux de marqueurs » : un test écoute le flux de SA fenêtre, le défaut.

Autotest :
    python src/core/modes/p300_test.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (P300_CAL_ROUNDS, P300_EPOCH_S, P300_N_TARGETS,  # noqa: E402
                         P300_PAUSE_MANCHE_S, P300_REPS, use_utf8_console)
from core.i18n import tr  # noqa: E402
from core.modes.affichage import (MOT_NON_MESURE, NIVEAUX, au_dessus_du_hasard,  # noqa: E402
                                  lignes, mot_de, non_mesure, p_hasard, pct, texte_p, verifier)
from core.modes.contract import Param  # noqa: E402
from core.modes.mesure import MesureSpec  # noqa: E402
from core.modes.mesure_marqueurs import (MesureMarqueurs,  # noqa: E402
                                         params_du_mode_pour_un_test, reglages_du_decideur)
from core.modes.p300 import SPEC as SPEC_P300  # noqa: E402
from core.modes.p300 import P300Runtime  # noqa: E402
# Les consignes, la durée d'une manche et les seuils de l'ENTRAÎNEMENT, importés : le test rejoue
# ce protocole-là, et une seconde table de seuils finirait par peindre en vert ce que la
# calibration juge faible.
from core.modes.p300_calib import BRIEFING as BRIEFING_CALIB  # noqa: E402
from core.modes.p300_calib import SOA_REFERENCE_S, VERDICTS, P300Calibration  # noqa: E402
# Wilson, importé : deux écritures finiraient par se contredire sur le même effectif.
from core.modes.ssvep_mesure import wilson  # noqa: E402

# Les seuils de la table de l'ENTRAÎNEMENT (`p300_calib.VERDICTS`) : « EXCELLENT » dès 80 % de
# sélection, « UTILISABLE » dès 60 %. Le 80 % est le repère : une ou deux erreurs sur six sont
# ATTENDUES (recette 2.7), et la ligne verte tombe entre les deux — 5/6 vert, 4/6 orange, 3/6 rouge.
SEUIL_REPERE = VERDICTS[0][0]
SEUIL_UTILISABLE = VERDICTS[1][0]

# MANCHES (l'unité de `--rounds`). La fenêtre cercle les cibles À TOUR DE RÔLE : 6 = chaque cible
# une fois, le plus court test équilibré — le défaut, parce qu'on refait ce test à chaque réglage ;
# 12 = la séance d'entraînement ; 24 = pour TRANCHER quand l'intervalle est trop large.
MANCHES = (P300_N_TARGETS, 2 * P300_N_TARGETS, 4 * P300_N_TARGETS)
MANCHES_DEFAUT = MANCHES[0]

# Sous 3 manches retenues, une seule pèse 50 points : le verdict serait pile ou face. Le plus court
# test en joue 6 ; on ne tombe ici que si la moitié de la séance s'est perdue.
MANCHES_MIN = 3

# Une manche à 60 Hz, depuis les constantes de la FENÊTRE : la pause qui la précède (le `cue` y est
# affiché), puis `P300_REPS` flashs de chaque cible au SOA de référence. L'autotest vérifie qu'à 12
# manches on retombe EXACTEMENT sur la durée que la calibration annonce.
PAR_MANCHE_S = P300_PAUSE_MANCHE_S + P300_REPS * P300_N_TARGETS * SOA_REFERENCE_S


def duree_protocole_s(manches):
    """La durée hors chauffe de `manches` manches — plus la dernière époque qui finit de s'écrire."""
    return float(manches) * PAR_MANCHE_S + P300_EPOCH_S


def _minutes(manches):
    """La durée d'un test de `manches` manches, chauffe comprise, en minutes (« 3,1 »)."""
    return f"{(MesureMarqueurs.warmup_s + duree_protocole_s(manches)) / 60:.1f}".replace(".", ",")


def _hasard_de(n_cibles):
    """Le niveau du hasard d'une sélection parmi `n_cibles`. DÉDUIT du mode, jamais écrit en dur."""
    return 1.0 / n_cibles


class _DecideurP300(P300Runtime):
    """Le runtime du MODE. Seul `_log` est coupé (« [p300] CIBLE… » ferait croire que le mode tourne) ;
    `_run_step`, `_encaisser_flash`, `_decider` et `_publish` sont hérités tels quels (vérifié)."""

    def _log(self, target_index, n_flashes, scores, motif=None):
        pass


class _Vue:
    """Ce que `P300Runtime.__init__` lit d'un moteur : `acq` (le modèle doit porter SA fréquence).
    Pas le moteur entier : `cancel()` doit pouvoir le libérer, et le décideur vit aussi longtemps que
    la mesure."""

    instance = "p300_test"

    def __init__(self, acq):
        self.acq = acq


class _Rejeu:
    """Ce que `P300Runtime._run_step` lit d'un moteur, le temps d'UN marqueur : le tampon horodaté du
    VRAI moteur, son `acq`, et ce marqueur-là comme seul marqueur mûr."""

    def __init__(self, engine, ts, marqueur):
        self.acq, self.recent, self.recent_ts = engine.acq, engine.recent, engine.recent_ts
        self._lot = [(ts, marqueur)]

    def markers_murs(self, mode_id, post_s):
        lot, self._lot = self._lot, []
        return lot


class MesureP300(MesureMarqueurs):
    """Le protocole d'entraînement P300, rejoué ; le mode sélectionne à chaque `round_end`."""

    marker_mode_id = "p300"
    runtime_cls_du_mode = P300Runtime          # pre_s/post_s y sont LUS par le socle
    evenement_verite, champ_verite = "cue", "target"
    evenement_unite = "flash"                  # la fenêtre annonce des FLASHS dans `trials`
    epoque_marqueur_s = SPEC_P300.marker_epoch_s
    # ⚠️ L'avancement AFFICHÉ est en MANCHES (cf. `state`), pas dans l'unité de `trials` : la garde
    # de silence du socle compte les flashs annoncés, l'écran compte ce que l'étudiant a choisi.
    unite = tr("mesure.unite.manche")

    def __init__(self, spec, params, engine, rng=None):
        super().__init__(spec, params, engine, rng=rng)
        # Le modèle chargé et vérifié par le MODE : un fichier effacé depuis la validation, ou une
        # géométrie d'époque étrangère, lèvent ici avec la raison du mode.
        self._decideur = _DecideurP300(SPEC_P300, reglages_du_decideur(SPEC_P300, self.params),
                                       _Vue(getattr(engine, "acq", None)))
        self._manche_en_cours = False    # un `cue` a ouvert une manche que rien n'a encore fermée
        self._manches_sans_cue = 0       # `round_end` sans manche ouverte : jamais notées
        self._manches_sans_fin = 0       # `cue` arrivé avant le `round_end` d'avant : jamais notées
        self._manches_jouees = 0         # `round_end` reçus pendant les essais : l'avancement affiché

    def _manches(self):
        try:
            return max(0, int(self.params.get("essais", MANCHES_DEFAUT)))
        except (TypeError, ValueError):
            return MANCHES_DEFAUT

    def duree_estimee_s(self):
        return float(self.warmup_s) + duree_protocole_s(self._manches())

    def state(self, now=None):
        """L'instantané du socle, l'avancement en MANCHES : l'étudiant a choisi « Manches : 6 », il
        lit « 2 sur 6 », pas « 36 sur 108 » flashs. Seuls `essai` et `total` changent — la garde de
        silence (`_verifie_silence`) lit `_essais_vus` et `_essais_annonces`, en flashs, et
        `total()` reste celui du socle."""
        etat = super().state(now)
        etat["essai"], etat["total"] = self._manches_jouees, self._manches()
        return etat

    def _verite_lisible(self, valeur):
        """Un indice de cible entier, DANS la géométrie du mode : un `cue` hors plage n'ouvre rien."""
        valeur = super()._verite_lisible(valeur)
        if valeur is None or not 0 <= valeur < self._decideur.n_targets:
            return None
        return valeur

    def _rejouer(self, engine, ts, marqueur):
        """UN marqueur, dans le `_run_step` du MODE — rien n'est décidé ailleurs."""
        self._decideur._run_step(_Rejeu(engine, ts, marqueur), float(ts))

    def _encaisser_protocole(self, engine, ts, marqueur):
        event = marqueur.get("event")
        if event == "cue":
            # La vérité est déjà chez le correcteur. Un `cue` OUVRE une manche : si la précédente
            # n'a jamais reçu son `round_end`, ses flashs traînent chez le mode. Jetés par le geste
            # du MODE (compté, dit) — sinon ils se souderaient à cette manche-ci, dont la vérité
            # noterait une sélection faite à moitié sur la précédente.
            if self._manche_en_cours:
                self._manches_sans_fin += 1
                if self._decideur._epoques:
                    self._decideur._abandonne_manche("« cue » d'une nouvelle manche avant le "
                                                     "« round_end » de la précédente")
            self._manche_en_cours = True
            return
        if event == "flash":
            if not self._essai_ouvert:
                return      # sa manche n'a pas de `cue` : compté au `round_end`
            # ⚠️ L'époque est découpée DEUX FOIS, par le MÊME appel sur le MÊME tampon : par le
            # socle (avancement, pertes comptées et dites), puis par le mode (sa garde de cible,
            # son plafond par cible). Donner au mode l'époque du socle obligerait à réécrire
            # `_encaisser_flash` — le second chemin que ce fichier existe pour ne pas ouvrir.
            if self._prelever(engine, ts) is not None:
                self._rejouer(engine, ts, marqueur)
            return
        if event == "round_end":
            self._manche_en_cours = False
            self._manches_jouees += 1
            if not self._essai_ouvert:
                self._manches_sans_cue += 1
                self._decideur._vider_manche()
                return
            self._consigner(self._decision(engine, ts, marqueur))

    def _decision(self, engine, ts, marqueur):
        """**LA décision de la manche : ce que `decoded_p300` publiait à ce `round_end`.** La cible,
        ou None — `-1` n'est jamais une cible (invariant n°3)."""
        avant = self._decideur.output()
        self._rejouer(engine, ts, marqueur)
        sortie = self._decideur.output()
        if sortie is None or sortie is avant:
            return None
        index = int(sortie["target_index"])
        return None if index < 0 else index

    def cancel(self):
        super().cancel()
        self._decideur._vider_manche()

    def _mesurer(self, enregistre, fs):
        """Une décision par manche, déjà prise ; ici on compte. Aucun fichier."""
        reglages = dict(self.params, model=_os.path.basename(str(self.params.get("model", ""))))
        return noter([(cible, decision) for decision, cible in enregistre],
                     self._decideur.n_targets, n_epoques=self.essai,
                     manches_demandees=self._manches(),
                     hors_calcul=self._manches_sans_cue + self._manches_sans_fin,
                     reglages=reglages)


def noter(decisions, n_cibles, n_epoques=0, manches_demandees=None, hors_calcul=0, reglages=None):
    """Le score. `decisions` : `[(cible cerclée, cible sélectionnée | None), ...]`, **UNE par manche**.

    Les niveaux, jugés ICI (la console les peint, elle ne les recalcule pas) :
      • `faible` — rien de sélectionné (NON MESURÉ) ; ou le test binomial EXACT ne distingue pas
        la sélection du hasard (`affichage.au_dessus_du_hasard`, p ≥ 0,05 — la porte PARTAGÉE par
        tous les tests ; Wilson reste l'intervalle affiché) ; ou la justesse est sous la ligne
        « UTILISABLE » de l'entraînement (60 %) ;
      • `bon` — au-dessus du hasard ET au repère (la ligne « EXCELLENT », 80 %) ;
      • `moyen` — entre les deux.
    """
    hasard = _hasard_de(n_cibles)
    n = len(decisions)
    if n < MANCHES_MIN:
        raise ValueError(tr("mesure.p300_test.erreur.trop_peu", n=n))
    n_sans = sum(1 for _c, d in decisions if d is None)
    n_justes = sum(1 for c, d in decisions if d is not None and d == c)
    justesse = n_justes / n
    ic_bas, ic_haut = (float(v) for v in wilson(n_justes, n))
    p = p_hasard(n_justes, n, hasard)
    au_dessus = au_dessus_du_hasard(n_justes, n, hasard)
    plus_long = max(MANCHES)
    court = (manches_demandees or 0) < plus_long

    non_mesure_ = n_sans == n
    if non_mesure_:
        niveau, mot = "faible", MOT_NON_MESURE
    elif not au_dessus or justesse < SEUIL_UTILISABLE:
        niveau, mot = "faible", tr("mesure.mot.faible")
    elif justesse >= SEUIL_REPERE:
        niveau, mot = "bon", tr("mesure.mot.repere")
    else:
        niveau, mot = "moyen", tr("mesure.mot.utilisable")

    chiffres = (tr("mesure.p300_test.chiffres_sans", justesse=pct(justesse),
                   bas=f"{ic_bas * 100:.0f}", haut=pct(ic_haut), hasard=pct(hasard), n=n,
                   sans=n_sans) if n_sans else
                tr("mesure.p300_test.chiffres", justesse=pct(justesse), bas=f"{ic_bas * 100:.0f}",
                   haut=pct(ic_haut), hasard=pct(hasard), n=n))
    if n_sans:
        reserve = tr("mesure.p300_test.reserve.sans_decision", sans=n_sans, n=n)
    elif niveau == "faible" and not au_dessus:
        reserve = (tr("mesure.p300_test.reserve.faible_court", p=texte_p(p), n=n, long=plus_long)
                   if court else tr("mesure.p300_test.reserve.faible_long", n=n, p=texte_p(p)))
    elif niveau == "faible":
        reserve = tr("mesure.p300_test.reserve.sous_seuil", seuil=pct(SEUIL_UTILISABLE))
    elif niveau == "moyen":
        reserve = tr("mesure.p300_test.reserve.moyen", repere=pct(SEUIL_REPERE))
    elif court:
        reserve = tr("mesure.p300_test.reserve.bon_court", n=n, long=plus_long)
    else:
        reserve = tr("mesure.p300_test.reserve.bon")
    affichage = (non_mesure(tr("mesure.p300_test.chiffres.non_mesure", n=n, hasard=pct(hasard)),
                            reserve) if non_mesure_
                 else lignes(niveau, mot, chiffres, reserve))

    par_cible = {c: {"manches": sum(1 for k, _d in decisions if k == c),
                     "justes": sum(1 for k, d in decisions if k == c and d == c)}
                 for c in range(n_cibles)}
    verdict = tr("mesure.p300_test.verdict.base", mot=mot, n=n,
                 epoques=tr("mesure.p300_test.verdict.epoques", n=n_epoques) if n_epoques else "",
                 justes=n_justes, justesse=pct(justesse), bas=f"{ic_bas * 100:.0f}",
                 haut=f"{ic_haut * 100:.0f}", hasard=pct(hasard), k=n_cibles, p=texte_p(p),
                 conclusion=(tr("mesure.commun.au_dessus") if au_dessus
                             else tr("mesure.commun.indistinguable")))
    if n_sans:
        verdict += tr("mesure.p300_test.verdict.sans_decision", n=n_sans)
    if hors_calcul:
        verdict += tr("mesure.p300_test.verdict.hors_calcul", n=hors_calcul)
    verdict += tr("mesure.p300_test.verdict.par_cible",
                  liste=", ".join(f"{c} {v['justes']}/{v['manches']}"
                                  for c, v in par_cible.items()),
                  repere=pct(SEUIL_REPERE), utilisable=pct(SEUIL_UTILISABLE))

    return {
        "n_essais": n, "n_justes": n_justes, "n_sans_decision": n_sans,
        "n_epoques": int(n_epoques), "n_hors_calcul": int(hors_calcul),
        "justesse": round(justesse, 3), "ic_bas": round(ic_bas, 3), "ic_haut": round(ic_haut, 3),
        "hasard": hasard, "p_hasard": round(p, 4), "n_cibles": int(n_cibles),
        "repere": SEUIL_REPERE,
        "par_cible": par_cible, "decisions": [(c, d) for c, d in decisions],
        "reglages": dict(reglages or {}),
        **affichage,
        "verdict": verdict,
        "honnetete": HONNETETE,
    }


HONNETETE = tr("mesure.p300_test.honnetete", flashs=P300_REPS * P300_N_TARGETS,
               facteur=f"{(P300_REPS * P300_N_TARGETS) ** 0.5:.0f}",
               excellent=pct(SEUIL_REPERE), utilisable=pct(SEUIL_UTILISABLE))

BRIEFING = (
    tr("mesure.p300_test.briefing.1"),
) + tuple(BRIEFING_CALIB) + (
    tr("mesure.p300_test.briefing.deroule", chauffe=f"{MesureMarqueurs.warmup_s:.0f}",
       manche=f"{PAR_MANCHE_S:.0f}"),
    tr("mesure.commun.modele_requis"),
)


SPEC = MesureSpec(
    id="p300_test",
    label=tr("mesure.p300_test.label"),
    summary=tr("mesure.p300_test.summary"),
    briefing=BRIEFING,
    # Les `Param` du MODE, les MÊMES objets : sans modèle, `contract.validate` refuse le test avec
    # la raison du mode — pas l'interface. SAUF le flux de marqueurs : un test écoute toujours
    # celui de la fenêtre qu'il lance (cf. `mesure_marqueurs.CLE_FLUX`).
    params=params_du_mode_pour_un_test(SPEC_P300) + (
        Param(
            key="essais",
            label=tr("mesure.p300_test.param.essais.label"),
            kind="choice",
            default=MANCHES_DEFAUT,
            choices=MANCHES,
            # L'aide de la bulle ⓘ : ce qu'est une manche, quand allonger, la durée de chaque choix.
            help=tr("mesure.p300_test.param.essais.aide", k=P300_N_TARGETS, long=max(MANCHES),
                    durees=", ".join(tr("mesure.commun.duree", n=n, minutes=_minutes(n))
                                     for n in MANCHES)),
        ),
    ),
    runtime_cls=MesureP300,
    stimulus_id="p300",
)


def _selftest():
    """Sur un modèle entraîné à la volée, dans un dossier TEMPORAIRE — jamais `data/`."""
    import io
    import json
    import shutil
    import tempfile
    from contextlib import redirect_stdout

    import numpy as np

    from core import p300_models
    from core.config import DATA_DIR, empreinte_dossier
    from core.modes.contract import validate
    from core.p300_decoder import NONTARGET, TARGET, P300Model, epoch_from_stream, synth_p300_epoch

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    empreinte_avant = empreinte_dossier(DATA_DIR)
    FS, REPS, SOA, PAUSE = 250.0, 3, 0.15, 1.0
    PRE, POST = P300Runtime.pre_s, P300Runtime.post_s

    class _FausseAcq:
        fs = FS

    class _Moteur:
        def __init__(self, eeg, ts):
            self.acq, self.instance = _FausseAcq(), "selftest"
            self.recent, self.recent_ts, self.t0 = eeg, ts, float(ts[0])
            self._lots, self.appels = [], []

        def markers_murs(self, mode_id, post_s):
            self.appels.append((mode_id, post_s))
            return self._lots.pop(0) if self._lots else []

    def m(event, **champs):
        return {"mode": "p300", "event": event, **champs}

    def seance(cues, graine, reps_de=None, absente=None, sans_fin=()):
        """(plan, eeg, ts) : une manche par cue, un P300 PLANTÉ à chaque flash de la cible cerclée.
        `reps_de` {manche: reps}, `absente` {manche: cible jamais flashée}, `sans_fin` : manches
        dont le `round_end` s'est perdu."""
        rng = np.random.default_rng(graine)
        t0 = 1000.0
        t, plan, planter = t0 + 2.0, [], []
        for r, cue in enumerate(cues):
            plan.append((t, m("cue", target=cue)))
            t += PAUSE
            for _ in range((reps_de or {}).get(r, REPS)):
                for tgt in rng.permutation(P300_N_TARGETS):
                    if (absente or {}).get(r) == tgt:
                        continue
                    plan.append((t, m("flash", target=int(tgt))))
                    if tgt == cue:
                        planter.append(t)
                    t += SOA
            if r not in sans_fin:
                plan.append((t, m("round_end")))
            t += 0.5
        ts = np.arange(t0, t + 3.0, 1.0 / FS)
        eeg = rng.normal(0.0, 1.6, (len(ts), 8)) + 0.8 * np.sin(2 * np.pi * 10 * (ts - t0))[:, None]
        n_pre, n_post = int(round(PRE * FS)), int(round(POST * FS))
        for instant in planter:
            i = int(np.searchsorted(ts, instant))
            onde = synth_p300_epoch(True, fs=FS, amp=1.4, noise=0.0, rng=rng)[:n_pre + n_post]
            eeg[i - n_pre:i + n_post] += onde - onde.mean(axis=0)
        return plan, eeg, ts

    def demarree(moteur, valeurs, plan):
        rt = MesureP300(SPEC, valeurs, moteur)
        rt.tick(moteur, moteur.t0)
        rt.encaisser(moteur, moteur.t0, m("calib_start",
                                          trials=sum(1 for _t, k in plan if k["event"] == "flash")))
        rt.tick(moteur, moteur.t0 + rt.warmup_s + 0.1)
        for t, k in plan:
            rt.encaisser(moteur, t, k)
        return rt

    def jouer(valeurs, plan, eeg, ts):
        moteur = _Moteur(eeg, ts)
        rt = demarree(moteur, valeurs, plan)
        rt.encaisser(moteur, plan[-1][0] + 1.0, m("calib_end"))
        t = moteur.t0 + rt.warmup_s + 0.2
        for _ in range(5):
            rt.tick(moteur, t)
            if rt.terminee:
                break
            t += 0.25
        return rt

    def en_direct(chemin, plan, eeg, ts):
        """Ce que `decoded_p300` publiait, manche par manche : un VRAI `P300Runtime`, ses lots."""
        moteur = _Moteur(eeg, ts)
        rt = P300Runtime(SPEC_P300, {"model": chemin, "stream_in": "x"}, moteur)
        sorties, lot = [], []
        for t, k in plan:
            lot.append((t, k))
            if k["event"] == "round_end":
                moteur._lots, lot = [lot], []
                with redirect_stdout(io.StringIO()):
                    rt._run_step(moteur, t)
                i = rt.output()["target_index"]
                sorties.append(None if i < 0 else i)
        return sorties

    def dec(n, justes, sans=0):
        """`n` manches cerclées à tour de rôle : `justes` justes, puis `sans` sans décision, puis
        fausses."""
        return [(i % 6, i % 6 if i < justes else None if i < justes + sans else (i + 1) % 6)
                for i in range(n)]

    vrai_dispo = p300_models.modeles_disponibles
    dossier = tempfile.mkdtemp(prefix="p300_test_")
    try:
        # Un modèle entraîné sur une AUTRE séance synthétique, découpée par le chemin du décodage.
        plan_e, eeg_e, ts_e = seance([r % 6 for r in range(12)], graine=1)
        X, y, g, manche, cue = [], [], [], -1, None
        for t, k in plan_e:
            if k["event"] == "cue":
                manche, cue = manche + 1, k["target"]
            elif k["event"] == "flash":
                X.append(epoch_from_stream(eeg_e, ts_e, t, FS, pre_s=PRE, post_s=POST))
                y.append(TARGET if k["target"] == cue else NONTARGET)
                g.append(manche)
        chemin = _os.path.join(dossier, "p300_model_20260101_000000.joblib")
        P300Model(fs=FS, pre_s=PRE, post_s=POST).fit(
            np.asarray(X), np.asarray(y), groups=np.asarray(g), compute_cv=False).save(chemin)

        # === 1. UN TEST EXIGE UN MODÈLE — refusé par le CONTRAT, pas par l'interface ============
        vide = _os.path.join(dossier, "vide")
        _os.makedirs(vide)
        p300_models.modeles_disponibles = lambda d=vide: vrai_dispo(d)
        _v, raison = validate(SPEC, {})
        chk(raison is not None and "Aucun modèle entraîné" in raison,
            f"sans modèle, `contract.validate` REFUSE le test, avec la raison du mode ({raison})")
        p300_models.modeles_disponibles = lambda d=dossier: vrai_dispo(d)
        valeurs, raison = validate(SPEC, {})
        chk(valeurs is not None and valeurs["model"] == chemin
            and valeurs["essais"] == MANCHES_DEFAUT == min(MANCHES),
            f"avec un modèle il passe, et le défaut est le test COURT ({raison or valeurs['essais']})")
        chk(all(any(p is q for q in SPEC.params) for p in SPEC_P300.params if p.key != "stream_in"),
            "le test déclare les `Param` du MODE eux-mêmes (identité), sauf le flux de marqueurs")
        autre = _os.path.join(dossier, "geometrie_etrangere.joblib")
        P300Model(fs=125.0).save(autre)
        try:
            MesureP300(SPEC, dict(valeurs, model=autre), _Moteur(eeg_e, ts_e))
            refus = None
        except ValueError as e:
            refus = str(e)
        chk(refus is not None and "125" in refus,
            f"…et il refuse ce que le MODE refuse : un modèle d'une autre géométrie ({refus})")

        # === 2. LA DURÉE, en manches ============================================================
        chk(abs(duree_protocole_s(P300_CAL_ROUNDS) - P300Calibration.duree_protocole_s) < 1e-9,
            f"à {P300_CAL_ROUNDS} manches, la durée est EXACTEMENT celle que l'entraînement annonce")
        moteur = _Moteur(eeg_e, ts_e)
        courte = MesureP300(SPEC, valeurs, moteur).duree_estimee_s()
        longue = MesureP300(SPEC, dict(valeurs, essais=max(MANCHES)), moteur).duree_estimee_s()
        chk(courte == MesureMarqueurs.warmup_s + duree_protocole_s(MANCHES_DEFAUT)
            and longue == MesureMarqueurs.warmup_s + duree_protocole_s(max(MANCHES)) > courte,
            f"la durée annoncée suit le nombre de manches ({courte:.0f} s / {longue:.0f} s)")
        rt = MesureP300(SPEC, valeurs, moteur)
        chk([rt._verite_lisible(v) for v in (5, 6, -1, True, "2")] == [5, None, None, None, None],
            "un `cue` hors de la géométrie du mode (6, -1), booléen ou texte n'ouvre AUCUNE manche")
        rt.tick(moteur, moteur.t0)
        rt.tick(moteur, moteur.t0 + 1.0)
        chk(moteur.appels == [("p300", POST)],
            f"le moteur est interrogé sous le `mode` de la fenêtre, à la maturité du MODE "
            f"({moteur.appels})")

        # === C2 : un TEST écoute le flux PAR DÉFAUT, et n'offre pas d'en choisir un autre ============
        # « Tester » lance TOUJOURS notre fenêtre, qui publie sur `MARKER_STREAM_DEFAULT`. Un test qui
        # héritait le « Flux de marqueurs » du mode (réglé sur l'appli de l'étudiant) écoutait un flux
        # où personne ne publiait : abandon à 30 s, fenêtre plein écran jouant dans le vide.
        from core.config import MARKER_STREAM_DEFAULT as _DEFAUT
        from core.modes.contract import validate as _valider
        from core.server import EngineServer as _Moteur_
        chk("stream_in" not in {p.key for p in SPEC.params},
            f"le test ne déclare PAS « Flux de marqueurs » ({[p.key for p in SPEC.params]})")
        _v, _raison = _valider(SPEC, {"stream_in": "MonAppli_P300"})
        chk(_v is None and "stream_in" in (_raison or ""),
            f"…et le contrat REFUSE qu'on le lui passe : brancher une appli, c'est « Connecter » "
            f"({_raison})")
        chk(_Moteur_._flux_attendu(rt) == _DEFAUT,
            f"le moteur écoute, pour ce test, le flux PAR DÉFAUT — celui de la fenêtre qu'il lance "
            f"({_Moteur_._flux_attendu(rt)})")

        # === 3. DE BOUT EN BOUT, et UN ESSAI = UNE MANCHE =======================================
        plan, eeg, ts = seance(list(range(6)), graine=2)
        fichiers_avant = sorted(_os.listdir(dossier))
        journal = io.StringIO()
        with redirect_stdout(journal):
            rt = jouer(valeurs, plan, eeg, ts)
        res = rt.resultat or {}
        chk(rt.phase == "fini", f"la séance se termine sur un verdict ({rt.phase}, {rt.probleme!r})")
        chk("[p300] CIBLE" not in journal.getvalue(),
            "le décideur ne journalise pas comme le mode : rien ne fait croire que le mode tourne")
        # ⚠️ LE test de ce module : `self.essai` compte des FLASHS (l'unité de `trials`), et le
        # prendre pour l'effectif est l'erreur à une ligne — 108 « essais » au lieu de 6.
        chk(res.get("n_epoques") == 6 * REPS * P300_N_TARGETS == rt.essai > 6,
            f"la séance a bien retenu {rt.essai} époques de flash — sans ça la suite serait vraie à "
            f"vide")
        chk(res.get("n_essais") == 6 and len(res.get("decisions", [])) == 6,
            f"…et l'effectif est un nombre de MANCHES, pas de flashs ({res.get('n_essais')})")
        attendu = [round(float(v), 3) for v in wilson(res.get("n_justes", 0), 6)]
        chk([res.get("ic_bas"), res.get("ic_haut")] == attendu,
            f"l'intervalle de Wilson porte sur les 6 manches ({attendu})")
        chk(abs(res.get("hasard", 0) - 1.0 / 6) < 1e-9 and res.get("n_cibles") == P300_N_TARGETS,
            f"le hasard est celui des {P300_N_TARGETS} cibles du mode, 1/6 ({res.get('hasard')})")
        chk([c for c, _d in res.get("decisions", [])] == list(range(6)),
            "chaque décision est notée contre la cible cerclée de SA manche")
        chk(res.get("n_justes", 0) >= 4,
            f"sur du P300 synthétique la sélection BAT le hasard — un appariement décalé d'une "
            f"manche ne le pourrait pas ({res.get('n_justes')}/6)")
        chk(res.get("reglages", {}).get("model") == _os.path.basename(chemin)
            and res["reglages"].get("essais") == MANCHES_DEFAUT,
            f"le résultat dit sur quels réglages il a été mesuré ({res.get('reglages')})")

        # === 3 bis. L'AVANCEMENT affiché est en MANCHES — la garde de silence, elle, en FLASHS ====
        # L'étudiant choisit « Manches : 6 » ; il lisait « 12 phase(s) enregistrée(s) sur 288 »
        # (des flashs, sous l'unité du contrôle alpha). L'instantané publie maintenant des manches
        # ET leur nom ; la garde du socle continue de compter les flashs annoncés par `trials`.
        etat = rt.state(now=0.0)
        chk(etat.get("unite") == "manche" and (etat.get("essai"), etat.get("total")) == (6, 6),
            f"en fin de test l'écran lit « 6 manches sur 6 », pas des flashs "
            f"({etat.get('essai')} {etat.get('unite')!r} sur {etat.get('total')})")
        fin_2e = [i for i, (_t, k) in enumerate(plan) if k["event"] == "round_end"][1]
        moteur_mi = _Moteur(eeg, ts)
        rt_mi = MesureP300(SPEC, valeurs, moteur_mi)
        rt_mi.tick(moteur_mi, moteur_mi.t0)
        rt_mi.encaisser(moteur_mi, moteur_mi.t0, m("calib_start", trials=rt.total()))
        rt_mi.tick(moteur_mi, moteur_mi.t0 + rt_mi.warmup_s + 0.1)
        with redirect_stdout(io.StringIO()):
            for t, k in plan[:fin_2e + 1]:
                rt_mi.encaisser(moteur_mi, t, k)
        etat = rt_mi.state(now=0.0)
        chk((etat.get("essai"), etat.get("total")) == (2, MANCHES_DEFAUT),
            f"…et à mi-séance, « 2 manches sur {MANCHES_DEFAUT} » ({etat.get('essai')} sur "
            f"{etat.get('total')})")
        chk(rt_mi._essais_vus == 2 * REPS * P300_N_TARGETS
            and rt_mi.total() == 6 * REPS * P300_N_TARGETS,
            f"…pendant que la garde de silence du socle compte toujours les FLASHS annoncés "
            f"({rt_mi._essais_vus} vus sur {rt_mi.total()}) — l'affichage ne la touche pas")
        try:
            json.dumps(rt.state(now=0.0))
            serialisable = True
        except (TypeError, ValueError):
            serialisable = False
        chk(serialisable, "l'instantané, résultat compris, est sérialisable (il part dans `snapshot()`)")

        # === 4. LA DÉCISION EST CELLE DU MODE ====================================================
        chk(issubclass(_DecideurP300, P300Runtime)
            and all(getattr(_DecideurP300, f) is getattr(P300Runtime, f)
                    for f in ("_run_step", "_encaisser_flash", "_decider", "_publish")),
            "le décideur EST le runtime du mode : ni l'épochage, ni la sélection, ni la publication "
            "ne sont redéfinis")
        chk([d for _c, d in res["decisions"]] == en_direct(chemin, plan, eeg, ts),
            "…et il sélectionne, manche par manche, ce que le mode publiait EN DIRECT")
        # Les trois refus du mode : une manche d'UNE répétition, une cible jamais flashée, une
        # cible flashée au-delà du plafond. Une sélection réécrite (`model.select` sur les époques
        # reçues) trancherait les trois ; des époques données au mode à la main, le troisième.
        plan_g, eeg_g, ts_g = seance([0, 1, 2, 3, 4], graine=3, absente={2: 5},
                                     reps_de={1: 1, 3: P300_REPS + 1})
        with redirect_stdout(io.StringIO()):
            rt_g = jouer(valeurs, plan_g, eeg_g, ts_g)
        res_g = rt_g.resultat or {}
        decisions_g = [d for _c, d in res_g.get("decisions", [])]
        chk(len(decisions_g) == 5 and decisions_g[1:4] == [None, None, None],
            f"manche trop courte, cible jamais flashée, plafond par cible dépassé : AUCUNE "
            f"sélection — les gardes du MODE, pas une réécriture ({decisions_g})")
        chk(decisions_g == en_direct(chemin, plan_g, eeg_g, ts_g),
            "…exactement comme le mode en direct, manche par manche")

        # === 5. -1 = PAS DE DÉCISION, une sélection RATÉE =======================================
        chk(res_g.get("n_hors_calcul") == 0,
            f"une manche abandonnée par le plafond est quand même DÉCIDÉE (-1) : elle est dans le "
            f"calcul, pas « jouée hors calcul » ({res_g.get('n_hors_calcul')})")
        chk(res_g.get("n_sans_decision") == 3 and res_g.get("n_essais") == 5
            and res_g.get("n_justes", 0) <= 2 and "sans décision" in res_g.get("reserve", ""),
            f"les trois manches sans décision restent dans l'effectif, NON sélectionnées, et la "
            f"réserve en nomme la cause ({res_g.get('chiffres')} | {res_g.get('reserve')})")

        # === 6. UN `round_end` PERDU NE SOUDE PAS DEUX MANCHES ===================================
        plan_p, eeg_p, ts_p = seance([2, 3, 4], graine=4, sans_fin=(1,))
        with redirect_stdout(io.StringIO()):
            rt_p = demarree(_Moteur(eeg_p, ts_p), valeurs, plan_p)
        chk([lab for _o, lab in rt_p._enregistre] == [2, 4] and rt_p._manches_sans_fin == 1
            and rt_p._decideur._manches_abandonnees == 1
            and rt_p._decideur.output()["n_flashes"] == REPS * P300_N_TARGETS,
            f"la manche sans `round_end` est jetée par le MODE au `cue` suivant : la dernière "
            f"sélection ne porte que SES {REPS * P300_N_TARGETS} flashs "
            f"({rt_p._decideur.output()['n_flashes']}), notée contre SA cible")

        chk(empreinte_dossier(DATA_DIR) == empreinte_avant
            and sorted(_os.listdir(dossier)) == fichiers_avant,
            "des séances complètes n'ont RIEN écrit — ni dans `data/`, ni à côté du modèle")
    finally:
        p300_models.modeles_disponibles = vrai_dispo
        shutil.rmtree(dossier, ignore_errors=True)

    # === 7. LE HASARD, ET LES NIVEAUX jugés par le moteur ========================================
    chk(mot_de(VERDICTS[0][1]) == "EXCELLENT" and mot_de(VERDICTS[1][1]) == "UTILISABLE",
        f"les seuils lus par position dans la table de l'entraînement sont bien ses lignes "
        f"« EXCELLENT » et « UTILISABLE » ({SEUIL_REPERE}, {SEUIL_UTILISABLE})")
    res = noter(dec(12, 9), 6, manches_demandees=12)
    chk(abs(res["hasard"] - 1.0 / 6) < 1e-9,
        f"le hasard d'une sélection parmi 6 est 1/6, jamais 1/2 ({res['hasard']})")
    chk(pct(res["justesse"]) in res["verdict"] and pct(res["hasard"]) in res["verdict"]
        and "hasard" in res["chiffres"],
        f"le verdict porte la mesure ET son hasard ({res['chiffres']})")
    # Le MÊME résultat brut contre deux hasards : c'est un hasard écrit en dur qui se verrait ici.
    six, deux = noter(dec(12, 8), 6), noter(dec(12, 8), 2, manches_demandees=24)
    chk(six["niveau"] == "moyen" and deux["niveau"] == "faible" and "hasard 50 %" in deux["chiffres"],
        f"8/12 bat le hasard à 6 cibles, PAS à 2 ({six['niveau']} / {deux['niveau']})")
    chk("distinguable du hasard" in deux["reserve"] and "p = " in deux["reserve"]
        and "seuil" not in deux["reserve"],
        f"…et la réserve dit POURQUOI : le hasard, p-value à l'appui, pas un seuil qu'il dépasse "
        f"({deux['reserve']})")
    cas = {
        "5/6": (noter(dec(6, 5), 6, manches_demandees=6), "bon", "confirme à 24"),
        "8/10": (noter(dec(10, 8), 6, manches_demandees=24), "bon", "après une pause"),
        "6/10": (noter(dec(10, 6), 6), "moyen", "sous le repère"),
        "6/12": (noter(dec(12, 6), 6, manches_demandees=24), "faible", "réentraîne"),
        "2/6": (noter(dec(6, 2), 6, manches_demandees=6), "faible", "à 24 manches"),
        "4/6+1": (noter(dec(6, 4, sans=1), 6), "moyen", "sans décision"),
        "0/6": (noter(dec(6, 0, sans=6), 6), "faible", "sans décision"),
    }
    for nom, (r, niveau, reserve) in cas.items():
        chk(r["niveau"] == niveau and reserve in r["reserve"],
            f"{nom} -> {niveau} ({r['mot']} | {r['reserve'][:60]}…)")
    # I-2 : 2 manches justes sur 3 retenues. 67 % passe la ligne « utilisable » (60 %) et Wilson
    # [21 ; 94] passe 1/6 ; le test binomial exact dit p = 0,074. Rouge.
    r = noter(dec(3, 2), 6, manches_demandees=6)
    chk(r["niveau"] == "faible" and "p = 0,074" in r["verdict"],
        f"2/3 : p = 0,074, FAIBLE — pas UTILISABLE ({r['mot']}, Wilson [{r['ic_bas']} ; "
        f"{r['ic_haut']}])")
    chk(cas["0/6"][0]["mot"] == "NON MESURÉ",
        "rien de sélectionné : NON MESURÉ, pas FAIBLE — on vérifie la liaison, pas les électrodes")
    for r in [res, six, deux] + [c[0] for c in cas.values()]:
        chk(not verifier(r) and r["niveau"] in NIVEAUX and "hasard" in r["chiffres"],
            f"affichage cohérent : {r['mot']} | {r['chiffres']} {verifier(r)}")
    try:
        noter(dec(2, 2), 6)
        chk(False, f"moins de {MANCHES_MIN} manches doit être refusé")
    except ValueError as e:
        chk("pas de quoi conclure" in str(e), f"moins de {MANCHES_MIN} manches : refusé")

    chk(empreinte_dossier(DATA_DIR) == empreinte_avant,
        f"`data/` est intact ({len(empreinte_avant)} fichiers avant, "
        f"{len(empreinte_dossier(DATA_DIR))} après)")
    print(f"[p300-test] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
