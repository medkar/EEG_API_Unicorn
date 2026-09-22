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

Autotest :
    python src/core/modes/p300_test.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (P300_CAL_ROUNDS, P300_EPOCH_S, P300_N_TARGETS,  # noqa: E402
                         P300_PAUSE_MANCHE_S, P300_REPS, use_utf8_console)
from core.modes.affichage import NIVEAUX, lignes, mot_de, non_mesure, pct, verifier  # noqa: E402
from core.modes.contract import Param  # noqa: E402
from core.modes.mesure import MesureSpec  # noqa: E402
from core.modes.mesure_marqueurs import MesureMarqueurs  # noqa: E402
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

    def __init__(self, spec, params, engine, rng=None):
        super().__init__(spec, params, engine, rng=rng)
        # Le modèle chargé et vérifié par le MODE : un fichier effacé depuis la validation, ou une
        # géométrie d'époque étrangère, lèvent ici avec la raison du mode.
        self._decideur = _DecideurP300(SPEC_P300, {p.key: self.params.get(p.key)
                                                   for p in SPEC_P300.params},
                                       _Vue(getattr(engine, "acq", None)))
        self._manche_en_cours = False    # un `cue` a ouvert une manche que rien n'a encore fermée
        self._manches_sans_cue = 0       # `round_end` sans manche ouverte : jamais notées
        self._manches_sans_fin = 0       # `cue` arrivé avant le `round_end` d'avant : jamais notées

    def _manches(self):
        try:
            return max(0, int(self.params.get("essais", MANCHES_DEFAUT)))
        except (TypeError, ValueError):
            return MANCHES_DEFAUT

    def duree_estimee_s(self):
        return float(self.warmup_s) + duree_protocole_s(self._manches())

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
      • `faible` — rien de sélectionné (NON MESURÉ) ; ou l'intervalle de Wilson CONTIENT le hasard ;
        ou la justesse est sous la ligne « UTILISABLE » de l'entraînement (60 %) ;
      • `bon` — au-dessus du hasard ET au repère (la ligne « EXCELLENT », 80 %) ;
      • `moyen` — entre les deux.
    """
    hasard = _hasard_de(n_cibles)
    n = len(decisions)
    if n < MANCHES_MIN:
        raise ValueError(f"{n} manche(s) retenue(s) : il n'y a pas de quoi conclure — "
                         f"l'intervalle serait plus large que l'échelle. Refais le test.")
    n_sans = sum(1 for _c, d in decisions if d is None)
    n_justes = sum(1 for c, d in decisions if d is not None and d == c)
    justesse = n_justes / n
    ic_bas, ic_haut = (float(v) for v in wilson(n_justes, n))
    plus_long = max(MANCHES)
    court = (manches_demandees or 0) < plus_long

    if n_sans == n:
        niveau, mot = "faible", "NON MESURÉ"
    elif ic_bas <= hasard or justesse < SEUIL_UTILISABLE:
        niveau, mot = "faible", "FAIBLE"
    elif justesse >= SEUIL_REPERE:
        niveau, mot = "bon", "AU NIVEAU DU REPÈRE"
    else:
        niveau, mot = "moyen", "UTILISABLE"

    chiffres = (f"{pct(justesse)} de cibles justes, entre {ic_bas * 100:.0f} et {pct(ic_haut)} "
                f"(hasard {pct(hasard)}) sur {n} manches"
                + (f", dont {n_sans} sans décision" if n_sans else ""))
    reprendre = "reprends le contact de Fz/Cz/Pz et fixe franchement la cible cerclée"
    if n_sans:
        reserve = (f"{n_sans} manche(s) sur {n} sans décision : le moteur a perdu des époques "
                   f"(liaison, tampon) — ce n'est pas ton modèle ; vérifie le contact et re-teste.")
    elif niveau == "faible" and ic_bas <= hasard:
        reserve = (f"L'intervalle contient le hasard : à {n} manches on ne peut pas conclure — "
                   f"refais le test à {plus_long} manches avant de juger." if court else
                   f"L'intervalle contient le hasard même sur {n} manches : {reprendre}, puis "
                   f"réentraîne.")
    elif niveau == "faible":
        reserve = (f"Sous le seuil d'utilisation ({pct(SEUIL_UTILISABLE)}) : {reprendre}, puis "
                   f"réentraîne.")
    elif niveau == "moyen":
        reserve = (f"Au-dessus du hasard, sous le repère ({pct(SEUIL_REPERE)}) : {reprendre}, "
                   f"ou réentraîne.")
    elif court:
        reserve = (f"Sur {n} manches l'intervalle reste large : confirme à {plus_long} manches "
                   f"avant de transcrire ces réglages dans ton application.")
    else:
        reserve = ("Mesuré sur CETTE séance : le P300 suit l'attention — re-teste après une pause "
                   "avant de transcrire ces réglages dans ton application.")
    affichage = (non_mesure(f"aucune des {n} manches n'a été sélectionnée (hasard "
                            f"{pct(hasard)})", reserve) if mot == "NON MESURÉ"
                 else lignes(niveau, mot, chiffres, reserve))

    par_cible = {c: {"manches": sum(1 for k, _d in decisions if k == c),
                     "justes": sum(1 for k, d in decisions if k == c and d == c)}
                 for c in range(n_cibles)}
    verdict = (
        f"{mot} — sur {n} MANCHES (une décision par manche : la cible que `decoded_p300` publiait "
        f"au `round_end`, jamais une par flash"
        + (f" — {n_epoques} époques au total" if n_epoques else "") +
        f"), la cible sélectionnée était la cible cerclée {n_justes} fois, soit {pct(justesse)} [IC95 "
        f"{ic_bas * 100:.0f} ; {ic_haut * 100:.0f}] pour un hasard à {pct(hasard)} ({n_cibles} "
        f"cibles). ")
    if n_sans:
        verdict += (f"{n_sans} manche(s) sans décision (`target_index = -1`) comptent comme NON "
                    f"sélectionnées : ton application n'aurait rien reçu. ")
    if hors_calcul:
        verdict += (f"⚠️ {hors_calcul} manche(s) de plus ont été JOUÉES mais ne sont pas dans ce "
                    f"calcul : leur `cue` ou leur `round_end` s'est perdu. ")
    verdict += ("Par cible (justes / manches) : "
                + ", ".join(f"{c} {v['justes']}/{v['manches']}" for c, v in par_cible.items())
                + f". Seuils de l'entraînement : {pct(SEUIL_REPERE)} (repère), "
                  f"{pct(SEUIL_UTILISABLE)} (utilisable).")

    return {
        "n_essais": n, "n_justes": n_justes, "n_sans_decision": n_sans,
        "n_epoques": int(n_epoques), "n_hors_calcul": int(hors_calcul),
        "justesse": round(justesse, 3), "ic_bas": round(ic_bas, 3), "ic_haut": round(ic_haut, 3),
        "hasard": hasard, "n_cibles": int(n_cibles), "repere": SEUIL_REPERE,
        "par_cible": par_cible, "decisions": [(c, d) for c, d in decisions],
        "reglages": dict(reglages or {}),
        **affichage,
        "verdict": verdict,
        "honnetete": HONNETETE,
    }


HONNETETE = (
    "Ce test mesure la règle du PRODUIT — ton modèle, et la sélection du mode P300 (moyenne des "
    "scores sur les répétitions de chaque cible, puis la meilleure) — sur le protocole "
    "d'entraînement : une décision par MANCHE, celle que `decoded_p300` publiait au `round_end`. "
    f"Les {P300_REPS * P300_N_TARGETS} flashs d'une manche ne sont pas autant d'observations : la "
    f"sélection les MOYENNE, et les compter rétrécirait l'intervalle d'un facteur "
    f"~{(P300_REPS * P300_N_TARGETS) ** 0.5:.0f} sans rien apprendre.\n"
    "Une manche sans décision (`target_index = -1` : trop peu d'époques, ou une cible jamais "
    "flashée) compte comme une sélection RATÉE — ton application n'aurait rien reçu. À marge de "
    "sélection nulle, le mode tranche toujours une manche complète : un -1 est une PERTE, pas une "
    "abstention.\n"
    f"Repères : les seuils sont ceux de l'entraînement ({pct(SEUIL_REPERE)} excellent, "
    f"{pct(SEUIL_UTILISABLE)} utilisable). Une ou deux "
    "erreurs sur six sont ATTENDUES : l'AUC du projet, 0,71, mesure une époque isolée ; la "
    "sélection se lit après moyennage. Aucun repère EN DIRECT : le P300 n'a jamais été décodé au "
    "casque à travers le moteur. Un modèle est propre à UNE personne, et le P300 suit l'attention : "
    "ce score décrit CETTE séance."
)

BRIEFING = (
    "Ce test rejoue le protocole d'ENTRAÎNEMENT, mais le moteur SÉLECTIONNE au lieu d'apprendre : à "
    "la fin de chaque manche, il choisit une cible avec ton modèle, et on compare à la cible "
    "cerclée.",
) + BRIEFING_CALIB + (
    f"Déroulé : stabilisation du casque ({MesureMarqueurs.warmup_s:.0f} s), puis les manches, "
    f"~{PAR_MANCHE_S:.0f} s chacune.",
    "Il faut un modèle entraîné : c'est lui qui décide. Rien n'est écrit sur le disque — ce test "
    "rend un score, pas un modèle.",
)


SPEC = MesureSpec(
    id="p300_test",
    label="Test P300",
    summary="Le protocole d'entraînement, rejoué : la fenêtre cercle une cible par manche, le "
            "moteur sélectionne avec ton modèle, et on compare.",
    briefing=BRIEFING,
    # Les `Param` du MODE, les MÊMES objets : sans modèle, `contract.validate` refuse le test avec
    # la raison du mode — pas l'interface.
    params=tuple(SPEC_P300.params) + (
        Param(
            key="essais",
            label="Manches",
            kind="choice",
            default=MANCHES_DEFAUT,
            choices=MANCHES,
            help=(f"Une manche = une sélection : la fenêtre cercle une cible, fait flasher les "
                  f"{P300_N_TARGETS}, et le moteur choisit. Court par défaut (une manche par "
                  f"cible), parce qu'on refait ce test à chaque réglage — mais un test court a un "
                  f"intervalle LARGE : s'il contient le hasard, prends {max(MANCHES)}. À 60 Hz : "
                  + ", ".join(f"{n} ≈ {(MesureMarqueurs.warmup_s + duree_protocole_s(n)) / 60:.1f}"
                              f" min".replace(".", ",") for n in MANCHES) + "."),
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
        chk(raison is not None and "aucun choix disponible" in raison,
            f"sans modèle, `contract.validate` REFUSE le test, avec la raison du mode ({raison})")
        p300_models.modeles_disponibles = lambda d=dossier: vrai_dispo(d)
        valeurs, raison = validate(SPEC, {})
        chk(valeurs is not None and valeurs["model"] == chemin
            and valeurs["essais"] == MANCHES_DEFAUT == min(MANCHES),
            f"avec un modèle il passe, et le défaut est le test COURT ({raison or valeurs['essais']})")
        chk(all(any(p is q for q in SPEC.params) for p in SPEC_P300.params),
            "le test déclare les `Param` du MODE eux-mêmes (identité)")
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
    chk("contient le hasard" in deux["reserve"] and "seuil" not in deux["reserve"],
        f"…et la réserve dit POURQUOI : l'intervalle, pas un seuil qu'il dépasse ({deux['reserve']})")
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
