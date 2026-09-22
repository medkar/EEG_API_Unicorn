"""Le TEST du c-VEP : le protocole d'entraînement, avec le moteur qui DÉCIDE au lieu d'apprendre.

La fenêtre `src/stimulus/cvep.py --calibrer` joue l'entraînement : elle cercle une cible par bloc,
publie `cue`, `block_end`, et son HORLOGE `cycle` sans interruption. Le moteur, au lieu
d'apprendre, décode comme le mode en direct ; on compare bloc par bloc à la cible cerclée. Un score
avec son hasard, **rien sur le disque**. La ligne du temps vient de `mesure_marqueurs.py`.

1. **LA DÉCISION EST CELLE DU MODE** : un `CVEPRuntime` (ton modèle, `corr_min`, `margin`, le
   vote), deux `print` coupés. 🔴 **La PHASE est APPELÉE, jamais recopiée** : ce fichier donne les
   `cycle` au décideur et c'est `CVEPRuntime._phase_et_cause` qui répond. Tenu, comme dans
   `cvep_calib.py`, par un test `ast` (aucun modulo ici) et par l'identité des méthodes héritées.

2. **UN ESSAI = UN BLOC = UNE DÉCISION : la DERNIÈRE sortie, ce que `decoded_cvep` publiait quand
   le bloc se ferme.** Le mode décide 5 fois par seconde sur des fenêtres qui se chevauchent : les
   compter gonflerait l'effectif (~5 par cycle de bloc, ~26 à la longueur de l'entraînement ; sur
   le SSVEP, n = 24 devenait 168). La dernière, parce que :
   • c'est UNE fenêtre votée, l'unité même du repère EN DIRECT (~46 % / ~71 %, compté en
     FENÊTRES) : on estime la même grandeur, sur des unités indépendantes ;
   • « au moins une émission dans le bloc » monterait avec la longueur du bloc, donc avec `essais` ;
   • sa mémoire (fenêtre + vote) ne voit que ce bloc : la cible est cerclée dès le settle.
   Pas la première : vote sans historique, toujours -1 dès que `min_votes` ≥ 2.

3. **`-1` = SILENCE, jamais une erreur** : il compte dans l'émission, pas dans la justesse. Score =
   COUPLE ; hasard = 1 / cibles du PLAN, jamais 1/2 ; Wilson sur les blocs JOUÉS pour l'émission,
   sur les blocs DÉCIDÉS pour la justesse.

4. **LE REJEU EST EXACT** : la dernière sortie ne dépend que des `vote_len` dernières fenêtres ; on
   prélève ce qu'elles couvrent (longueur MESURÉE sur `_fenetre`) et le décideur les rejoue à SA
   cadence. L'autotest compare chaque bloc à un `CVEPRuntime` qui décode EN CONTINU.

⚠️ **`--cycles` = cycles ENREGISTRÉS PAR CIBLE**, en `CVEP_CAL_BLOCKS` blocs entrelacés : 6 ×
min(cycles, 3) blocs, donc 18 au plus dès 3 cycles. Au-delà, les blocs s'allongent sans qu'il y en
ait davantage. D'où les choix (2, 3).

⚠️ **Le compteur de chauffe du socle ment pour le c-VEP** (la fenêtre clignote pendant la chauffe,
exprès) : le verdict ne cite JAMAIS ces tics d'horloge, seulement les BLOCS (`cue`) qui y tombent.

Autotest :
    python src/core/modes/cvep_test.py
"""

import os as _os
import random as _random
import sys as _sys
from collections import Counter, deque

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
import numpy as np  # noqa: E402

from core.config import (CH_NAMES, CVEP_CAL_BLOCKS, CVEP_CAL_SETTLE_CYCLES,  # noqa: E402
                         CVEP_CORR_MIN, CVEP_DECISION_CYCLES, CVEP_MARGIN, CVEP_MIN_VOTES,
                         CVEP_VOTE_LEN, FILTER_MARGIN_S, use_utf8_console)
from core.cvep_code import blocs_entrelaces, build_targets  # noqa: E402
from core.modes.affichage import lignes, non_mesure, pct, verifier  # noqa: E402
from core.modes.contract import Param  # noqa: E402
from core.modes.cvep import SPEC as SPEC_CVEP  # noqa: E402
from core.modes.cvep import CVEPRuntime  # noqa: E402
from core.modes.cvep_calib import BRIEFING as BRIEFING_CALIB  # noqa: E402
from core.modes.cvep_calib import REFRESH_REFERENCE_HZ  # noqa: E402
from core.modes.mesure import MesureSpec  # noqa: E402
from core.modes.mesure_marqueurs import MesureMarqueurs  # noqa: E402
# Wilson, importé : deux écritures finiraient par se contredire sur le même effectif.
from core.modes.ssvep_mesure import wilson  # noqa: E402
from core.p300_decoder import epoch_from_stream  # noqa: E402

# Le repère EN DIRECT, le seul qui se compare à un test : hors ligne, par FENÊTRE VOTÉE, aux défauts
# du mode, une séance (`cvep_rcca.py --seuils`, cf. `CVEP_RCCA_*` dans core/config.py). PAS le
# 59,5 / 64,9 % de l'entraînement : un argmax sans seuils ni vote, qui émet toujours.
REPERE_EMISSION = 0.46
REPERE_JUSTESSE = 0.71
_REGLAGES_DU_REPERE = {"corr_min": CVEP_CORR_MIN, "margin": CVEP_MARGIN,
                       "min_votes": CVEP_MIN_VOTES, "vote_len": CVEP_VOTE_LEN}

# Cycles ENREGISTRÉS par cible (l'unité de `--cycles`). 3 = le plus court qui joue les 18 blocs ;
# 2 = 12 blocs, la vérification rapide.
ESSAIS = (2, 3)
ESSAIS_DEFAUT = 3
ESSAIS_MIN = 6      # le plancher de `ssvep_mesure` et `mi_test`

# Les compteurs qui PARTITIONNENT les fenêtres du mode : chaque pas en incrémente UN, ce qui nomme
# la cause d'un -1 sans relire le texte du motif.
_CAUSES =("decodages", "sans_reference", "reference_perimee", "sous_les_seuils", "vote_non_conclu")
_CAUSES_HORLOGE = ("sans_reference", "reference_perimee")
_CAUSES_FR = {"sans_reference": "horloge absente", "reference_perimee": "horloge périmée",
              "sous_les_seuils": "sous les seuils", "vote_non_conclu": "vote non conclu"}

_PLAN, _CODE = build_targets()
_PERIODE_S = CVEPRuntime.period_s(None)     # 0,2 s : la cadence du mode, LUE (méthode non liée)
_VOTE_LEN_MAX = next(p.max for p in SPEC_CVEP.params if p.key == "vote_len")


def _hasard_de(n_cibles):
    """Le hasard d'une désignation parmi `n_cibles`. DÉDUIT du plan, jamais écrit en dur."""
    return 1.0 / n_cibles


def _label(cle):
    """Le libellé d'un réglage du mode : la réserve nomme le champ que l'étudiant a sous les yeux."""
    return next(p.label for p in SPEC_CVEP.params if p.key == cle)


def _blocs(cycles):
    """Les blocs que joue la fenêtre pour `cycles` par cible — la RÈGLE PARTAGÉE, pas recopiée."""
    return blocs_entrelaces(_PLAN, int(cycles), CVEP_CAL_BLOCKS, _random.Random(0))


def _duree_protocole_s(cycles):
    """La séance de la fenêtre hors chauffe, à 60 Hz : par bloc le settle puis les cycles enregistrés,
    plus le cycle de garde dont le marqueur ferme le dernier bloc."""
    blocs = _blocs(cycles)
    joues = len(blocs) * CVEP_CAL_SETTLE_CYCLES + sum(n for _c, n in blocs) + 1
    return joues * len(_CODE) / REFRESH_REFERENCE_HZ


def _minutes(cycles):
    return f"{(MesureMarqueurs.warmup_s + _duree_protocole_s(cycles)) / 60.0:.1f}".replace(".", ",")


def _compteurs(decideur):
    etat = decideur.state()
    return tuple(etat[k] for k in _CAUSES)


class _DecideurCVEP(CVEPRuntime):
    """Le runtime du MODE, rejoué, deux `print` coupés (« [cvep] CIBLE… » ferait croire que le mode
    tourne ; un refus d'horloge se dirait à chaque bloc). Le reste est hérité (vérifié)."""

    dernier_refus = ""

    def _log(self, target_index, scores, motif=None):
        pass

    def _refuse_marqueur(self, detail):
        self._marqueurs_refuses += 1
        self.dernier_refus = detail


class _Rejeu:
    """Ce que `_run_step` lit d'un moteur. `markers_murs` suit la règle du moteur : mûr dès que le
    tampon atteint `ts + post_s`, rendu une seule fois."""

    def __init__(self, acq, horloge=()):
        self.acq, self.instance = acq, "cvep_test"
        self.recent = self.recent_ts = None
        self._horloge, self._curseur = list(horloge), 0

    def markers_murs(self, mode_id, post_s):
        fin, rendus = float(self.recent_ts[-1]), []
        while (self._curseur < len(self._horloge)
               and self._horloge[self._curseur][0] + post_s <= fin):
            rendus.append(self._horloge[self._curseur])
            self._curseur += 1
        return rendus


class MesureCVEP(MesureMarqueurs):
    """Le protocole d'entraînement c-VEP, rejoué ; le moteur décide à la fin de chaque bloc."""

    marker_mode_id = "cvep"
    runtime_cls_du_mode = CVEPRuntime
    unite = "cycle"          # `essai` compte les cycles ENREGISTRÉS — l'unité de `--cycles`
    # `trials` compte les cycles ENREGISTRÉS : l'unité est le `cycle` reçu dans un bloc ouvert.
    evenement_verite, champ_verite, evenement_unite = "cue", "target", "cycle"
    # Le tampon du moteur, pour le PIRE réglage : plus long vote, fenêtre à 60 Hz, marge de filtre.
    # Un modèle sous 60 Hz au vote maximal est REFUSÉ à la construction plutôt que tronqué.
    epoque_marqueur_s = ((_VOTE_LEN_MAX - 1) * _PERIODE_S
                         + CVEP_DECISION_CYCLES * len(_CODE) / REFRESH_REFERENCE_HZ
                         + FILTER_MARGIN_S + 0.05)

    def __init__(self, spec, params, engine, rng=None):
        # Tout ceci AVANT le socle, qui lit `pre_s` pour vérifier le tampon.
        self._acq = getattr(engine, "acq", None)
        if self._acq is None:
            raise ValueError("aucune acquisition : le test ne découperait pas les fenêtres comme "
                             "le mode, donc il ne mesurerait pas la règle du produit")
        # Un modèle effacé depuis la validation lève ICI, avec la raison de `cvep_models.charger`.
        self._decideur = _DecideurCVEP(SPEC_CVEP, {p.key: params[p.key] for p in SPEC_CVEP.params},
                                       _Rejeu(self._acq))
        # La fenêtre du mode, MESURÉE sur `_fenetre` (cycles repliés + marge), pas recalculée.
        sonde = _Rejeu(self._acq)
        sonde.recent = np.zeros((int(30 * float(self._acq.fs)), len(CH_NAMES)))
        self._n_fenetre = len(self._decideur._fenetre(sonde))
        self._pas = int(round(float(self._acq.fs) * self._decideur.period_s()))
        self._n_pre = self._n_fenetre + (int(params["vote_len"]) - 1) * self._pas
        self._horloge = deque(maxlen=64)     # les derniers `cycle` reçus : ~1 min d'horloge
        self._fin_de_bloc = None             # (époque, instants) au dernier cycle du bloc ouvert
        self._bloc_ouvert = False
        self._blocs_sans_fin = 0             # un `cue` arrivé alors qu'un bloc était ouvert
        self._blocs_en_chauffe = 0           # des BLOCS, jamais des tics d'horloge
        self._dernier_refus = ""
        super().__init__(spec, params, engine, rng=rng)

    # --- la géométrie : REDÉCLARÉE, comme `cvep_calib` et `ssvep_mesure` ------------------------

    @property
    def pre_s(self):
        """Ce que couvrent les `vote_len` dernières fenêtres, marge comprise. `CVEPRuntime` n'a pas
        de `pre_s` à LIRE ; ce qui est lu, c'est sa fenêtre (`_fenetre`) et sa cadence."""
        return self._n_pre / float(self._acq.fs)

    @property
    def post_s(self):
        """Zéro : on décide sur ce qui PRÉCÈDE la fin du bloc, comme le flux à cet instant."""
        return 0.0

    def duree_estimee_s(self):
        return float(self.warmup_s) + _duree_protocole_s(self.params.get("essais", ESSAIS_DEFAUT))

    def rappel(self):
        if self.phase == "essais":
            return "fixe le disque CERCLÉ sans bouger les yeux — le moteur décide à la fin de chaque bloc"
        return ""

    def _verite_lisible(self, valeur):
        valeur = super()._verite_lisible(valeur)
        return valeur if valeur is not None and 0 <= valeur < len(self._decideur.plan) else None

    # --- les marqueurs --------------------------------------------------------------------------

    def encaisser(self, engine, ts, marqueur):
        """Le socle, plus deux gestes PENDANT LA CHAUFFE : un `cue` y est un BLOC perdu, compté ; un
        `cycle` y est le régime normal — ni perdu ni dit, mais GARDÉ, comme `CVEPRuntime.tick` le
        garde en direct : les premières fenêtres du 1er bloc peuvent en avoir besoin."""
        if self._demarre and self.phase == "chauffe":
            event = marqueur.get("event")
            if event == self.evenement_verite:
                self._blocs_en_chauffe += 1
            elif event == "cycle":
                self._horloge.append((float(ts), dict(marqueur)))
        super().encaisser(engine, ts, marqueur)

    def _encaisser_protocole(self, engine, ts, marqueur):
        """`cycle` : l'horloge, et — dans un bloc — l'époque de son dernier cycle. `cue` ouvre le
        bloc (SANS sa cible : le socle la garde au correcteur). `block_end` : on décide, on note."""
        event = marqueur.get("event")
        if event == "cycle":
            self._horloge.append((float(ts), dict(marqueur)))
            if self._bloc_ouvert:
                self._fin_de_bloc = self._prelever_avec_instants(engine, ts)
        elif event == "cue":
            if self._bloc_ouvert:
                self._blocs_sans_fin += 1
            self._bloc_ouvert, self._fin_de_bloc = True, None
        elif event == "block_end":
            ouvert, self._bloc_ouvert = self._bloc_ouvert, False
            fin, self._fin_de_bloc = self._fin_de_bloc, None
            # Toujours consigner : sans vérité en attente (`cue` perdu), le socle le COMPTE.
            self._consigner(self._rejouer(*fin) if ouvert and fin is not None else None)

    def _prelever_avec_instants(self, engine, ts):
        """L'époque (par le socle) et les HORODATAGES des mêmes échantillons — MÊME appel, sur la
        colonne des temps : la phase se lit au dernier échantillon, comme `_run_step` en direct."""
        epoque = self._prelever(engine, ts)
        if epoque is None:
            return None
        instants = epoch_from_stream(engine.recent_ts, engine.recent_ts,
                                     float(ts) + float(self.decalage_s), engine.acq.fs,
                                     pre_s=self.pre_s, post_s=self.post_s)
        return epoque, instants

    def _rejouer(self, epoque, instants):
        """Les sorties que `decoded_cvep` aurait publiées aux derniers pas du bloc, la dernière au
        dernier échantillon. `[{target_index, …, "cause": None | clé du compteur}, …]`."""
        d = self._decideur
        # Le bloc est jugé SEUL. Redondant aujourd'hui (les `vote_len` fenêtres chassent tout vote
        # antérieur : mutation invisible, mesuré) — gardé pour ne pas tenir à cette arithmétique.
        d._reset_rest()
        rejeu = _Rejeu(self._acq, self._horloge)
        sorties, n = [], len(epoque)
        for fin in range(n - ((n - self._n_fenetre) // self._pas) * self._pas, n + 1, self._pas):
            rejeu.recent, rejeu.recent_ts = epoque[:fin], instants[:fin]
            avant = _compteurs(d)
            d._run_step(rejeu, float(instants[fin - 1]))
            cause = next((c for c, a, b in zip(_CAUSES, avant, _compteurs(d)) if b > a), None)
            if cause is not None:
                sorties.append(dict(d.output(), cause=None if cause == "decodages" else cause))
        self._dernier_refus = d.dernier_refus or self._dernier_refus
        return sorties

    @staticmethod
    def _decision_du_bloc(sorties):
        """**LA décision d'un bloc : la DERNIÈRE sortie. Une seule.** `(cible, None)` ou
        `(None, cause)`. ⚠️ `-1` testé AVANT tout indiçage : c'est un silence, pas une cible."""
        derniere = sorties[-1]
        index = int(derniere["target_index"])
        if index < 0:
            return None, derniere.get("cause") or "inconnue"
        return index, None

    def _mesurer(self, enregistre, fs):
        """Une décision par bloc, puis le score. Aucun fichier."""
        decisions, perdus = [], 0
        for sorties, cible in enregistre:
            if not sorties:
                perdus += 1      # l'époque du dernier cycle avait quitté le tampon
                continue
            decide, cause = self._decision_du_bloc(sorties)
            decisions.append((int(cible), decide, cause))
        pertes = {"perdus": perdus, "sans_fin": self._blocs_sans_fin + int(self._bloc_ouvert),
                  "sans_verite": self._essais_sans_verite, "en_chauffe": self._blocs_en_chauffe}
        reglages = dict(self.params, model=_os.path.basename(str(self.params.get("model", ""))))
        return noter(decisions, len(self._decideur.plan), pertes=pertes,
                     refus_horloge=self._dernier_refus, essais=self.params.get("essais"),
                     reglages=reglages)


def noter(decisions, n_cibles, *, pertes=None, refus_horloge="", essais=None, reglages=None):
    """Le score. `decisions` : `[(cible cerclée, cible émise | None, cause | None), ...]`, **UNE
    par bloc**.

    Niveaux (la console les peint, ne les recalcule pas) : `faible` = horloge inutilisable (NON
    MESURÉ), aucune émission (MUET), ou Wilson de la justesse contenant le hasard (FAIBLE) ; `bon` =
    au-dessus du hasard ET justesse ≥ 71 % ET émission ≥ 46 %, le repère EN DIRECT (points estimés,
    comme `mi_test`) ; `moyen` = au-dessus du hasard, sous le repère sur l'un des deux.
    """
    pertes = {k: int(v) for k, v in (pertes or {}).items() if v}
    reglages = dict(reglages or {})
    hasard = _hasard_de(n_cibles)
    n_essais = len(decisions)
    if n_essais < ESSAIS_MIN:
        raise ValueError(f"{n_essais} bloc(s) retenu(s) : il n'y a pas de quoi conclure — "
                         f"l'intervalle serait plus large que l'échelle.")
    emis = [(c, d) for c, d, _k in decisions if d is not None]
    n_emis = len(emis)
    n_justes = sum(1 for c, d in emis if d == c)
    taux = n_emis / n_essais
    justesse = n_justes / n_emis if n_emis else 0.0
    # Deux effectifs, deux intervalles : les blocs JOUÉS portent l'émission, les blocs DÉCIDÉS la
    # justesse (invariant n°3).
    em_bas, em_haut = (float(v) for v in wilson(n_emis, n_essais))
    ic_bas, ic_haut = (float(v) for v in wilson(n_justes, n_emis))
    silences = Counter(k for _c, d, k in decisions if d is None)
    n_horloge = sum(silences[k] for k in _CAUSES_HORLOGE)
    horloge_seule = n_emis == 0 and n_horloge == n_essais
    court = (essais or 0) < max(ESSAIS)

    if horloge_seule:
        niveau, mot = "faible", "NON MESURÉ"
    elif n_emis == 0:
        niveau, mot = "faible", "MUET"
    elif ic_bas <= hasard:
        niveau, mot = "faible", "FAIBLE"
    elif justesse >= REPERE_JUSTESSE and taux >= REPERE_EMISSION:
        niveau, mot = "bon", "AU NIVEAU DU REPÈRE"
    else:
        niveau, mot = "moyen", "UTILISABLE"

    seuil, vote, marge = _label("corr_min"), _label("min_votes"), _label("margin")
    if horloge_seule:
        chiffres = f"aucune décision possible : l'horloge du code n'a servi sur aucun des {n_essais} blocs"
        # Le DIAGNOSTIC du mode, pas sa fin (« lance l'émetteur avec --refresh… ») : ici, personne
        # ne tape de commande — c'est la console qui lance la fenêtre.
        reserve = (f"L'horloge de la fenêtre a été refusée par le mode ("
                   f"{refus_horloge.split(' — ')[0]}) : réentraîne sur CET écran."
                   if refus_horloge else
                   "Aucun marqueur « cycle » utilisable : vérifie « Flux de marqueurs » et que la "
                   "fenêtre de stimulus tourne jusqu'au bout.")
    elif n_emis == 0:
        chiffres = f"aucune cible émise sur {n_essais} blocs (hasard {pct(hasard)})"
        dominante = silences.most_common(1)[0][0]
        if dominante == "vote_non_conclu":
            reserve = (f"Les fenêtres ne s'accordent jamais : plante le regard sur le disque "
                       f"cerclé, ou baisse « {vote} », puis re-teste.")
        elif dominante in _CAUSES_HORLOGE:
            reserve = ("L'horloge du code s'est perdue sur la plupart des blocs : la fenêtre de "
                       "stimulus doit tourner sans interruption jusqu'à la fin.")
        else:
            reserve = (f"Aucun bloc ne passe les seuils : saline Pz/PO7/Oz/PO8, puis baisse "
                       f"« {seuil} » d'un cran et re-teste.")
    else:
        chiffres = (f"{pct(justesse)} de cibles justes quand il émet (hasard {pct(hasard)}), "
                    f"{pct(taux)} d'émission — {n_emis} blocs décidés sur {n_essais}")
        if niveau == "faible" and court:
            reserve = (f"L'intervalle contient le hasard : à {n_emis} blocs décidés on ne peut pas "
                       f"conclure — refais le test à {max(ESSAIS)} cycles par cible "
                       f"({len(_blocs(max(ESSAIS)))} blocs) avant de juger.")
        elif niveau == "faible":
            reserve = ("L'intervalle contient le hasard : réentraîne — saline Pz/PO7/Oz/PO8, et "
                       "PLANTE le regard sur le disque cerclé sans le promener.")
        elif taux < REPERE_EMISSION and justesse >= REPERE_JUSTESSE:
            reserve = (f"Juste quand il parle, mais il ne parle que sur {pct(taux)} des blocs "
                       f"(repère ~{pct(REPERE_EMISSION)}) : baisse « {seuil} » ou « {vote} » d'un "
                       f"cran, puis re-teste.")
        elif taux >= REPERE_EMISSION and justesse < REPERE_JUSTESSE:
            reserve = (f"Il parle souvent mais se trompe sur {pct(1 - justesse)} de ce qu'il émet "
                       f"(repère ~{pct(1 - REPERE_JUSTESSE)}) : remonte « {seuil} » ou « {marge} » "
                       f"d'un cran, puis re-teste.")
        elif niveau == "moyen":
            reserve = ("Sous le repère sur les DEUX chiffres : resaline Pz/PO7/Oz/PO8 et réentraîne "
                       "avant de toucher aux seuils.")
        else:
            reserve = (f"Mesuré sur {n_essais} blocs de CETTE séance : l'intervalle reste large — "
                       f"re-teste après une pause avant de transcrire ces réglages dans ton "
                       f"application.")

    verdict = (f"{mot} — sur {n_essais} BLOCS (une décision par bloc : ce que `decoded_cvep` "
               f"publiait quand le bloc se fermait, jamais une par fenêtre), ")
    if n_emis:
        verdict += (f"le moteur a émis une cible {n_emis} fois — soit {pct(taux)} d'émission "
                    f"[IC95 {em_bas * 100:.0f} ; {em_haut * 100:.0f}] — et il avait raison "
                    f"{n_justes} fois sur {n_emis}, soit {pct(justesse)} de justesse à l'émission "
                    f"[IC95 {ic_bas * 100:.0f} ; {ic_haut * 100:.0f}] pour un hasard à "
                    f"{pct(hasard)} ({n_cibles} cibles). ")
    else:
        verdict += (f"le moteur n'a émis AUCUNE cible, soit {pct(0.0)} d'émission, pour un hasard "
                    f"à {pct(hasard)} ({n_cibles} cibles). ")
    if silences:
        verdict += (f"Les {sum(silences.values())} bloc(s) muets (-1) ne comptent pas comme des "
                    f"erreurs : " + ", ".join(f"{n} {_CAUSES_FR.get(k, k)}"
                                             for k, n in silences.most_common()) + ". ")
    if refus_horloge:
        verdict += f"Horloge refusée par le mode : {refus_horloge}. "
    textes = {"perdus": "joué(s) sans époque (l'EEG avait quitté le tampon)",
              "sans_fin": "sans « block_end »", "sans_verite": "sans cible lisible",
              "en_chauffe": "joué(s) pendant la CHAUFFE du moteur"}
    if pertes:
        verdict += ("⚠️ Hors du calcul : " + " ; ".join(f"{n} bloc(s) {textes.get(k, k)}"
                                                       for k, n in pertes.items())
                    + f". L'effectif ci-dessus décrit {n_essais} blocs, pas davantage. ")
    verdict += (f"Repère EN DIRECT du projet, aux défauts du mode : ~{pct(REPERE_EMISSION)} "
                f"d'émission et ~{pct(REPERE_JUSTESSE)} de justesse à l'émission (hors ligne, par "
                f"fenêtre votée, une séance) — pas le 59,5 / 64,9 % de l'entraînement, qui ignore "
                f"seuils et vote.")
    ecarts = [k for k, v in _REGLAGES_DU_REPERE.items()
              if k in reglages and abs(float(reglages[k]) - float(v)) > 1e-9]
    if ecarts:
        verdict += (" Tes réglages diffèrent de ceux du repère (" + ", ".join(_label(k) for k in ecarts)
                    + ") : la comparaison n'est qu'indicative.")

    affichage = (non_mesure(chiffres, reserve) if horloge_seule
                 else lignes(niveau, mot, chiffres, reserve))
    return {
        "n_essais": n_essais, "n_emis": n_emis, "n_justes": n_justes,
        "n_silences": n_essais - n_emis, "silences": dict(silences), "pertes": pertes,
        "taux_emission": round(taux, 3), "justesse": round(justesse, 3),
        "ic_emission_bas": round(em_bas, 3), "ic_emission_haut": round(em_haut, 3),
        "ic_bas": round(ic_bas, 3), "ic_haut": round(ic_haut, 3),
        "hasard": hasard, "n_cibles": int(n_cibles),
        "repere_emission": REPERE_EMISSION, "repere_justesse": REPERE_JUSTESSE,
        "decisions": [(int(c), None if d is None else int(d), k) for c, d, k in decisions],
        "reglages": reglages,
        **affichage,
        "verdict": verdict,
        "honnetete": HONNETETE,
    }


HONNETETE = (
    "Ce test mesure la règle du PRODUIT — ton modèle, ses seuils, son vote — sur les réglages du "
    "lancement : UNE décision par bloc, celle que `decoded_cvep` publiait quand il se fermait. Le "
    f"flux sort {1 / _PERIODE_S:.0f} décisions par seconde sur des fenêtres qui se chevauchent : "
    "les compter rétrécirait l'intervalle sans rien apprendre.\n"
    "Un bloc MUET (-1) compte dans le taux d'émission, jamais comme une erreur. Les deux chiffres "
    "se lisent ENSEMBLE : « 71 % de justesse » sans « 46 % d'émission » décrit une BCI qu'on n'a "
    "pas. Ce repère-là (hors ligne, par fenêtre votée, aux défauts du mode, UNE séance) est celui "
    "qui se compare à ce test ; le 59,5 / 64,9 % de l'entraînement est un argmax sans seuils ni "
    "vote, et l'y comparer fabrique un verdict faux dans les deux sens.\n"
    f"Au plus {len(_blocs(max(ESSAIS)))} blocs par test : l'intervalle reste large. Et le c-VEP "
    "n'a JAMAIS été décodé au casque à travers le moteur — attends-toi à moins, pas à plus. Ce "
    "score décrit CETTE séance, sur CE montage."
)

BRIEFING = (
    "Ce test rejoue le protocole d'ENTRAÎNEMENT, mais le moteur DÉCIDE au lieu d'apprendre : à la "
    "fin de chaque bloc, il dit quelle cible il voit avec ton modèle et tes réglages, et on "
    "compare à la cible cerclée.",
) + tuple(BRIEFING_CALIB) + (
    "Le moteur se TAIT souvent, et c'est normal : un bloc muet n'est pas une erreur, il fait "
    "baisser le taux d'émission — les deux chiffres se lisent ensemble.",
    "Il faut un modèle entraîné : c'est lui qui décide. Rien n'est écrit sur le disque.",
)

SPEC = MesureSpec(
    id="cvep_test",
    label="Tester le c-VEP",
    summary="Le protocole d'entraînement, rejoué : le moteur décide avec ton modèle et tes "
            "réglages, bloc par bloc, et on compare à la cible cerclée.",
    briefing=BRIEFING,
    # Les `Param` du MODE, les MÊMES objets : sans modèle, `contract.validate` refuse le test avec
    # la raison du mode, et la console passe les réglages courants tels quels.
    params=tuple(SPEC_CVEP.params) + (
        Param(
            key="essais",
            label="Longueur : cycles enregistrés par cible",
            kind="choice",
            default=ESSAIS_DEFAUT,
            choices=ESSAIS,
            help=(f"L'argument « --cycles » de la fenêtre, dans SON unité : des cycles ENREGISTRÉS "
                  f"par cible, répartis en {CVEP_CAL_BLOCKS} blocs entrelacés. Le test rend UNE "
                  f"décision par bloc : "
                  + ", ".join(f"{n} → {len(_blocs(n))} blocs ≈ {_minutes(n)} min" for n in ESSAIS)
                  + f". Au-delà de {max(ESSAIS)}, les blocs s'allongent sans qu'il y en ait "
                  f"davantage : le test durerait plus sans gagner une seule décision."),
        ),
    ),
    runtime_cls=MesureCVEP,
    stimulus_id="cvep",
)


def _selftest():  # noqa: C901 - un autotest se lit de haut en bas
    """Sur un modèle eCCA entraîné à la volée (c-VEP synthétique), dans un dossier TEMPORAIRE."""
    import ast
    import inspect
    import json
    import shutil
    import tempfile
    import textwrap

    from core.config import CVEP_CHANNELS, DATA_DIR, empreinte_dossier
    from core.cvep_decoder import CVEPModel, synth_cvep
    from core.modes import cvep as _cvep
    from core.modes.contract import validate

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    empreinte_avant = empreinte_dossier(DATA_DIR)
    # 63 × 240 / 60 = 252 échantillons pile : des cycles concaténés ne dérivent pas contre leurs
    # marqueurs (même choix que `cvep_calib._selftest`).
    FS, REFRESH = 240.0, 60.0
    L = len(_CODE)
    N_CYC = int(round(L * FS / REFRESH))

    class _FausseAcq:
        fs = FS
        margin_n = int(round(FILTER_MARGIN_S * FS))

    class _Moteur:
        """Toute la séance déjà dans le tampon : `_prelever` découpe ce qui PRÉCÈDE un marqueur."""

        def __init__(self, eeg, ts):
            self.acq, self.recent, self.recent_ts = _FausseAcq(), eeg, ts
            self.t0, self.instance = float(ts[0]), "selftest"

        def markers_murs(self, mode_id, post_s):
            return []

    class _MoteurContinu:
        """`EngineServer.markers_murs`, réécrite ICI : partagée avec `_Rejeu`, une faute commune
        aux deux passerait inaperçue."""

        def __init__(self, horloge):
            self.acq, self.instance, self.horloge, self.i = _FausseAcq(), "selftest", horloge, 0

        def markers_murs(self, mode_id, post_s):
            rendus = []
            while self.i < len(self.horloge) and self.horloge[self.i][0] + post_s <= self.recent_ts[-1]:
                rendus.append(self.horloge[self.i])
                self.i += 1
            return rendus

    def seance(cycles=6, snr=-3.0, graine=0, muets=(), refresh=REFRESH):
        """La séance `--calibrer`, cycle par cycle (cible cerclée dès le settle ; bloc muet = bruit)."""
        rng = np.random.default_rng(graine)
        blocs = blocs_entrelaces(_PLAN, cycles, CVEP_CAL_BLOCKS, _random.Random(graine))
        suite = [(None, None, None)] * 2
        for k, (cible, n) in enumerate(blocs):
            i = _PLAN.index(cible)
            suite += [("settle", i, k)] * CVEP_CAL_SETTLE_CYCLES + [("bloc", i, k)] * n
        suite += [(None, None, None)]
        sigma = float(np.std(synth_cvep(_CODE, 0, len(CH_NAMES), FS, REFRESH, snr, rng)))
        eeg = np.concatenate([
            rng.normal(0.0, sigma, (N_CYC, len(CH_NAMES))) if role is None or k in muets
            else synth_cvep(_CODE, _PLAN[i]["lag"], len(CH_NAMES), FS, REFRESH, snr, rng)
            for role, i, k in suite])
        ts = 1000.0 + np.arange(len(eeg)) / FS
        marqueurs, fins = [], []
        for j, (role, i, k) in enumerate(suite):
            t = 1000.0 + j * N_CYC / FS
            marqueurs.append((t, {"mode": "cvep", "event": "cycle", "refresh": refresh}))
            prole, _pi, pk = suite[j - 1] if j else (None, None, None)
            if prole == "bloc" and (role != "bloc" or k != pk):
                marqueurs.append((t, {"mode": "cvep", "event": "block_end"}))
                fins.append(t)
            if role == "bloc" and (prole != "bloc" or k != pk):
                marqueurs.append((t, {"mode": "cvep", "event": "cue", "target": i}))
        return marqueurs, eeg, ts, blocs, fins

    def joue(rt, moteur, marqueurs, trials=36, chauffe_avant=None):
        """Marqueurs d'avant `chauffe_avant` (défaut : les 2 cycles de garde) PENDANT la chauffe."""
        rt.tick(moteur, 0.0)
        rt.encaisser(moteur, moteur.t0, {"mode": "cvep", "event": "calib_start", "trials": trials})
        limite = moteur.t0 + 1.5 * N_CYC / FS if chauffe_avant is None else chauffe_avant
        garde = [(t, m) for t, m in marqueurs if t < limite]
        for t, m in garde:
            rt.encaisser(moteur, t, m)
        rt.tick(moteur, rt.warmup_s + 0.1)
        for t, m in marqueurs[len(garde):]:
            rt.encaisser(moteur, t, m)
        rt.encaisser(moteur, marqueurs[-1][0] + 0.5, {"mode": "cvep", "event": "calib_end"})
        for k in range(6):
            rt.tick(moteur, rt.warmup_s + 0.2 + 0.25 * k)
        return rt.resultat or {}

    def continu(v, eeg, ts, marqueurs, t_fin):
        """Ce qu'un VRAI `CVEPRuntime`, décodant en continu depuis 8 s, publiait à `t_fin`."""
        ref = _cvep.CVEPRuntime(_cvep.SPEC, {p.key: v[p.key] for p in SPEC_CVEP.params}, None)
        ref._log = lambda *a, **k: None
        moteur = _MoteurContinu([(t, m) for t, m in marqueurs if m["event"] == "cycle"])
        i_fin, pas = int(np.searchsorted(ts, t_fin)), int(round(FS * ref.period_s()))
        debut = max(1, i_fin - 40 * pas)
        for fin in range(i_fin - ((i_fin - debut) // pas) * pas, i_fin + 1, pas):
            moteur.recent, moteur.recent_ts = eeg[:fin], ts[:fin]
            ref._run_step(moteur, float(ts[fin - 1]))
        sortie = ref.output()
        return None if sortie is None or sortie["target_index"] < 0 else sortie["target_index"]

    # === 1. LE HASARD, LA LONGUEUR ============================================================
    chk(abs(_hasard_de(len(_PLAN)) - 1.0 / 6) < 1e-9 and len(_PLAN) == 6,
        f"hasard parmi les {len(_PLAN)} cibles du PLAN = 1/6, jamais 1/2 ({_hasard_de(len(_PLAN))})")
    chk([len(_blocs(n)) for n in (2, 3, 15)] == [12, 18, 18],
        f"`--cycles` = cycles enregistrés PAR CIBLE, en {CVEP_CAL_BLOCKS} blocs : 12, 18, et 18 "
        f"encore à 15 (l'entraînement) — le nombre de décisions PLAFONNE")
    essais = next(p for p in SPEC.params if p.key == "essais")
    chk(essais.kind == "choice" and essais.default in essais.choices == ESSAIS
        and "cycles" in essais.label and "par cible" in essais.label,
        f"la longueur est un « choice » dans l'unité de `--cycles`, NOMMÉE ({essais.label!r})")
    chk(all(any(p is q for q in SPEC.params) for p in SPEC_CVEP.params)
        and SPEC.stimulus_id == "cvep",
        "le test déclare les `Param` du MODE eux-mêmes (identité), et la fenêtre « cvep »")

    rng = np.random.default_rng(5)
    lags = [c["lag"] for c in _PLAN]
    modele = CVEPModel(fs=FS, refresh=REFRESH, code_len=L, channels=CVEP_CHANNELS)
    modele.fit([synth_cvep(_CODE, g, len(modele.channels), FS, REFRESH, -6.0, rng)
                for g in lags for _ in range(6)], [g for g in lags for _ in range(6)])
    dossier = tempfile.mkdtemp(prefix="cvep_test_")
    avant = _cvep.CVEP_MODEL_PATH
    try:
        # === 2. UN TEST EXIGE UN MODÈLE — refusé par le CONTRAT ================================
        _os.makedirs(_os.path.join(dossier, "vide"))
        _cvep.CVEP_MODEL_PATH = _os.path.join(dossier, "vide", "cvep_model.npz")
        _v, raison = validate(SPEC, {})
        chk(raison is not None and "aucun choix disponible" in raison,
            f"sans modèle, `validate` REFUSE le test avec la raison du mode ({raison[:60]}…)")
        _cvep.CVEP_MODEL_PATH = modele.save(_os.path.join(dossier, "cvep_model.npz"),
                                            n_targets=len(_PLAN))
        valeurs, raison = validate(SPEC, {"essais": 2})
        chk(valeurs is not None, f"avec un modèle, il passe ({raison})")

        marqueurs, eeg, ts, blocs, fins = seance(muets=(3, 11))
        moteur = _Moteur(eeg, ts)
        rt2 = MesureCVEP(SPEC, valeurs, moteur)
        rt3 = MesureCVEP(SPEC, dict(valeurs, essais=3), moteur)
        chk(abs(rt3.duree_estimee_s() - rt3.warmup_s - 91 * L / REFRESH_REFERENCE_HZ) < 1e-6
            and rt2.duree_estimee_s() < rt3.duree_estimee_s(),
            f"la durée annoncée suit `essais` : 3 -> 18 × (4 jetés + 1) + 1 cycles, "
            f"{rt3.duree_estimee_s() / 60:.1f} min ; 2 -> {rt2.duree_estimee_s() / 60:.1f} min")
        rt15 = MesureCVEP(SPEC, dict(valeurs, vote_len=_VOTE_LEN_MAX), moteur)
        chk(rt3.pre_s < rt15.pre_s <= MesureCVEP.epoque_marqueur_s,
            f"l'époque suit `vote_len`, et le tampon couvre le plus long vote ({rt15.pre_s:.2f} s)")

        # === 3. UNE SÉANCE ENTIÈRE, par la vraie porte ========================================
        rt = MesureCVEP(SPEC, valeurs, moteur)
        res = joue(rt, moteur, marqueurs)
        chk(rt.phase == "fini" and res.get("verdict"), f"verdict rendu ({rt.phase}, {rt.probleme!r})")
        chk(res.get("n_essais") == len(blocs) == 18 and rt.total() == rt.essai == 36,
            f"🔴 UN ESSAI = UN BLOC : effectif {res.get('n_essais')} — ni les {rt.total()} cycles "
            f"annoncés (la barre d'avancement), ni les {18 * valeurs['vote_len']} sorties rejouées")
        chk(abs(res.get("hasard", 0) - 1.0 / 6) < 1e-9, f"hasard rapporté 1/6 ({res.get('hasard')})")
        chk(rt.state(now=0.0).get("unite") == "cycle",
            f"l'avancement affiché compte des CYCLES — l'unité de `--cycles`, que l'étudiant a "
            f"choisie ({rt.state(now=0.0).get('unite')!r})")
        muets = [res["decisions"][k] for k in (3, 11)]
        chk(all(d is None for _c, d, _k in muets) and res["n_emis"] < res["n_essais"],
            f"les blocs où le sujet ne regarde rien sont MUETS ({muets})")
        chk(res["justesse"] == 1.0 and res["n_emis"] >= 14 and res["niveau"] == "bon",
            f"…et ne comptent pas comme des erreurs ({res['chiffres']}, {res['niveau']})")
        chk(not verifier(res), f"affichage cohérent avec le verdict ({verifier(res)})")
        chk(rt._marqueurs_chauffe == 2 and "chauffe" not in res["verdict"].lower()
            and not res["pertes"],
            f"⚠️ les {rt._marqueurs_chauffe} tics d'horloge de la chauffe ne sont PAS dits perdus")
        chk(all(m.get("event") == "cycle" and "target" not in m for _t, m in rt._horloge),
            "le décideur ne reçoit QUE l'horloge : jamais un `cue`, jamais une cible")
        try:
            chk(bool(json.dumps(rt.state(now=0.0))), "l'instantané, résultat compris, est sérialisable")
        except (TypeError, ValueError) as e:
            chk(False, f"l'instantané doit être sérialisable ({e})")

        # === 4. LE REJEU EST EXACT : chaque bloc contre un CVEPRuntime qui décode en continu ====
        for reglage in ({}, {"vote_len": 5, "min_votes": 3}):
            v = dict(valeurs, **reglage)
            r = res if not reglage else joue(MesureCVEP(SPEC, v, moteur), moteur, marqueurs)
            attendu = [continu(v, eeg, ts, marqueurs, t) for t in fins]
            obtenu = [d for _c, d, _k in r.get("decisions", [])]
            chk(obtenu == attendu and any(d is not None for d in attendu),
                f"[vote {v['min_votes']}/{v['vote_len']}] chaque bloc décide ce que `decoded_cvep`, "
                f"décodé EN CONTINU, publiait à sa fin "
                f"({sum(a == b for a, b in zip(obtenu, attendu))}/{len(attendu)})")
        # Le settle du 1er bloc tombe dans la CHAUFFE ; un vote de 13 sur 15 a besoin de ces tics.
        v = dict(valeurs, vote_len=_VOTE_LEN_MAX, min_votes=_VOTE_LEN_MAX - 2)
        t_cue = next(t for t, m in marqueurs if m["event"] == "cue")
        r = joue(MesureCVEP(SPEC, v, moteur), moteur, marqueurs, chauffe_avant=t_cue)
        premier = continu(v, eeg, ts, marqueurs, fins[0])
        chk(premier is not None and r.get("decisions", [(0, None, 0)])[0][1] == premier,
            f"les tics de la CHAUFFE servent au 1er bloc, comme en direct "
            f"({r.get('decisions', [None])[0]} contre {premier})")

        # === 5. LA RÈGLE : la DERNIÈRE sortie ================================================
        s = [{"target_index": -1, "cause": "vote_non_conclu"}, {"target_index": 2, "cause": None},
             {"target_index": 4, "cause": None}]
        chk(MesureCVEP._decision_du_bloc(s) == (4, None),
            "la décision est la DERNIÈRE sortie (4) — pas la première (-1), pas la majorité (2)")
        s[-1] = {"target_index": -1, "cause": "sous_les_seuils"}
        chk(MesureCVEP._decision_du_bloc(s) == (None, "sous_les_seuils"),
            "…et un bloc qui FINIT muet est muet, même si une sortie antérieure a émis")

        # === 6. HORLOGE REFUSÉE ; un BLOC dans la chauffe ====================================
        faux = [(t, dict(m, refresh=120.0) if m["event"] == "cycle" else m) for t, m in marqueurs]
        r = joue(MesureCVEP(SPEC, valeurs, moteur), moteur, faux)
        chk(r.get("mot") == "NON MESURÉ" and "120" in r.get("reserve", "") and not verifier(r),
            f"fenêtre à 120 Hz, modèle à 60 : NON MESURÉ, avec le diagnostic du mode "
            f"({r.get('reserve', '')[:70]}…)")
        rc = MesureCVEP(SPEC, valeurs, moteur)
        rc.tick(moteur, 0.0)
        rc.encaisser(moteur, moteur.t0, {"mode": "cvep", "event": "calib_start", "trials": 36})
        for t, m in marqueurs[:12]:
            rc.encaisser(moteur, t, m)
        chk(rc._blocs_en_chauffe == 1 and rc._marqueurs_chauffe == 12,
            f"dans la chauffe, un `cue` est un BLOC perdu, un `cycle` n'est qu'un tic "
            f"({rc._blocs_en_chauffe} bloc sur {rc._marqueurs_chauffe} marqueurs)")
    finally:
        _cvep.CVEP_MODEL_PATH = avant
        shutil.rmtree(dossier, ignore_errors=True)

    # === 7. LE VERDICT, sur des décisions fabriquées ===========================================
    def fab(emis, justes, blocs=18, cause="sous_les_seuils", **kw):
        d = [(i % 6, i % 6 if i < justes else (i + 1) % 6, None) for i in range(emis)]
        return noter(d + [(i % 6, None, cause) for i in range(blocs - emis)], 6, **kw)

    r = fab(9, 7)
    chk(r["niveau"] == "bon" and f"{pct(r['taux_emission'])} d'émission" in r["verdict"]
        and f"{pct(r['justesse'])} de justesse" in r["verdict"],
        f"les DEUX chiffres sont dans le verdict, ensemble ({r['chiffres']})")
    chk(pct(r["taux_emission"]) in r["chiffres"] and pct(r["justesse"]) in r["chiffres"],
        "…et dans la ligne visible par défaut")
    chk((r["ic_emission_bas"], r["ic_emission_haut"]) == tuple(round(x, 3) for x in wilson(9, 18))
        and (r["ic_bas"], r["ic_haut"]) == tuple(round(x, 3) for x in wilson(7, 9)),
        "Wilson sur les blocs JOUÉS (18) pour l'émission, DÉCIDÉS (9) pour la justesse")
    r = fab(6, 6)
    chk(r["justesse"] == 1.0 and abs(r["taux_emission"] - 1 / 3) < 1e-3,
        f"un bloc muet n'est PAS une erreur : 6/6 émis justes sur 18 = 100 % de justesse, 33 % "
        f"d'émission ({r['justesse']}, {r['taux_emission']})")
    r = fab(12, 5)
    chk(r["niveau"] == "moyen",
        f"5 justes sur 12 : Wilson [{r['ic_bas']} ; {r['ic_haut']}] passe 1/6, PAS 1/2 ({r['niveau']})")
    r = fab(4, 4)
    chk(r["niveau"] == "moyen" and _label("corr_min") in r["reserve"],
        f"juste mais trop muet : orange, la réserve nomme le réglage ({r['reserve'][:60]}…)")
    r = fab(16, 8)
    chk(r["niveau"] == "moyen" and "remonte" in r["reserve"],
        f"bavard mais faux : REMONTER les seuils ({r['reserve'][:60]}…)")
    r = fab(6, 2, essais=2)
    chk(r["mot"] == "FAIBLE" and "3 cycles" in r["reserve"],
        "l'intervalle contient le hasard : FAIBLE, et un test court renvoie au plus long")
    r = fab(0, 0, cause="vote_non_conclu")
    chk(r["mot"] == "MUET" and _label("min_votes") in r["reserve"],
        f"aucune émission : MUET, et la cause dominante choisit le geste ({r['reserve'][:60]}…)")
    chk(fab(0, 0, cause="sans_reference")["mot"] == "NON MESURÉ",
        "aucune horloge : NON MESURÉ, pas FAIBLE")
    r = fab(9, 7, pertes={"en_chauffe": 1, "perdus": 2})
    chk("CHAUFFE" in r["verdict"] and "2 bloc(s) joué(s) sans époque" in r["verdict"],
        "les BLOCS perdus (chauffe, tampon) sont dits dans le verdict")
    chk("indicative" in fab(9, 7, reglages={"corr_min": 0.20})["verdict"],
        "un réglage différent du repère le dit")
    chk(all(not verifier(fab(e, j, **kw)) for e, j, kw in
            ((9, 7, {}), (4, 4, {}), (16, 8, {}), (6, 2, {}), (0, 0, {}),
             (0, 0, {"cause": "sans_reference"}))),
        "`affichage.verifier` ne trouve rien à redire, à chaque niveau")
    try:
        fab(3, 3, blocs=5)
        chk(False, "5 blocs : il faut REFUSER de conclure")
    except ValueError:
        chk(True, "sous 6 blocs retenus, le calcul REFUSE de conclure")

    # === 8. LA DÉCISION EST CELLE DU MODE, et la PHASE est APPELÉE ============================
    herites = ("_run_step", "decide", "_phase_et_cause", "phase_a", "_fenetre",
               "_encaisser_marqueurs", "maj_reference", "_publish")
    chk(all(getattr(_DecideurCVEP, n) is getattr(CVEPRuntime, n) for n in herites),
        f"le décideur HÉRITE sans les redéfinir : {', '.join(herites)}")
    modulos = [(obj.__name__, n.lineno) for obj in (MesureCVEP, _DecideurCVEP, _Rejeu, noter)
               for n in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(obj))))
               if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod)]
    chk(not modulos,
        f"🔴 la phase n'est PAS recopiée : aucun modulo dans ce module ({modulos}) — une copie de "
        f"la formule en contiendrait un, et dériverait en silence")

    chk(empreinte_dossier(DATA_DIR) == empreinte_avant, "et tout ce test n'a rien écrit dans data/")
    print(f"[cvep-test] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
