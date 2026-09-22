"""Le TEST du Motor Imagery : le protocole d'entraînement, avec le moteur qui DÉCIDE au lieu d'apprendre.

Même ligne du temps que la calibration MI — mêmes durées, mêmes consignes, classes tirées au
hasard — mais à la fin de chaque essai le moteur DÉCIDE avec ton modèle et tes réglages, et on
compare à la consigne. Un score avec son niveau de hasard, **rien sur le disque**. Le MI est
endogène : pas de fenêtre de stimulus, pas de marqueurs — d'où `MesureRuntime` DIRECTEMENT, comme
le contrôle alpha, avec de vraies `Etape`.

--- LES QUATRE INVARIANTS ---------------------------------------------------------------------

1. **LA DÉCISION EST CELLE DU MODE.** Le décideur est un `MIRuntime`, rejoué à SA cadence ;
   `_run_step` (fenêtre brute, probabilité minimale, vote) n'est pas redéfinie (vérifié).

2. **UN ESSAI = UNE DÉCISION.** Le mode décide toutes les 0,2 s sur des fenêtres de 2 s qui se
   chevauchent : ~26 par essai. Les compter gonflerait l'effectif d'autant et rétrécirait
   l'intervalle d'un facteur ~5 (sur le SSVEP : n = 24 devenait 168). La décision d'un essai est
   **la DERNIÈRE sortie : ce que `decoded_mi` publiait quand l'imagerie se termine** — la consigne
   tenue le plus longtemps, ce qu'un client lit alors, un vote fait de CET essai seul (cf. 4). Ni
   la première (vote sans historique), ni une majorité (le produit publie un flux, pas un résumé).

3. **`-1` = « VOTE NON CONCLU », JAMAIS « REPOS ».** Un essai sans décision compte dans le taux
   d'émission, jamais comme une erreur, jamais comme REPOS — une classe du modèle, avec son indice.
   Le piège tient en une ligne : `classes[-1]` vaut `"REPOS"`. Le score est donc un COUPLE, comme
   le SSVEP : taux d'émission + justesse à l'émission, Wilson sur les essais DÉCIDÉS.

4. **L'ÉTAPE ENREGISTRÉE EST L'ESSAI ENTIER (mise en route + imagerie, 7 s).** Le plus long vote
   permis (15 fenêtres) remonte à 4,8 s ; l'imagerie seule n'en porterait que 11. Avec 26, le vote
   final est celui du flux en direct quel que soit le réglage (comparé dans l'autotest à un
   `MIRuntime` qui décode EN CONTINU depuis l'essai précédent).

⚠️ **Le hasard se DÉDUIT du modèle chargé** : 1/3 à trois classes, 1/2 en gauche/droite. Écrit en
dur, 62 % en G/D passerait pour un succès contre 33 %.

⚠️ **Les réglages sont ceux du MODE** : la `SPEC` déclare les `Param` du mode MI eux-mêmes (mêmes
objets : bornes, source de modèles, `votes_atteignables`). La console passe donc les réglages
courants tels quels (`snapshot()["reglages"]["mi"]` + `trials_per_class`), et le résultat les
recopie dans `reglages`.

Autotest :
    python src/core/modes/mi_test.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
import numpy as np  # noqa: E402

from core.config import (MI_CUE_S, MI_IMAGERY_S, MI_REST_S, MI_WINDOW_S,  # noqa: E402
                         use_utf8_console)
from core.mi_decoder import MI_CONTROL  # noqa: E402
from core.modes.affichage import (NIVEAUX, au_dessus_du_hasard, lignes, p_hasard,  # noqa: E402
                                  pct, texte_p, verifier)
from core.modes.contract import Param  # noqa: E402
from core.modes.mesure import Etape, MesureRuntime, MesureSpec  # noqa: E402
from core.modes.mi import MI_DECODE_HZ, MIRuntime  # noqa: E402
from core.modes.mi import SPEC as SPEC_MI  # noqa: E402
# Les consignes de l'ENTRAÎNEMENT, importées : une autre formulation peut faire passer d'une
# imagerie kinesthésique (qui produit une ERD) à une imagerie visuelle (qui n'en produit pas).
from core.modes.mi_calib import INSTRUCTIONS, RAPPEL  # noqa: E402
# Wilson et le seul repère d'ÉMISSION du projet, importés : deux écritures de Wilson finiraient par
# se contredire sur le même effectif.
from core.modes.ssvep_mesure import REFERENCE_EMISSION, wilson  # noqa: E402

# La seule séance de référence du projet, ré-mesurée honnêtement (CV PAR ESSAI) : 40,0 % à 3 classes
# (p = 0,082, PAS significatif), 63,3 % à 2 classes (p = 0,038). Chiffres de CALIBRATION, hors
# ligne : aucun repère EN DIRECT n'existe. Rangés par nombre de classes, qui fixe le hasard.
REPERES_JUSTESSE = {3: 0.400, 2: 0.633}

# Le seul repère d'émission du projet : le SSVEP, le mode FIABLE, émet sur 44 % des essais dans son
# régime normal. Un MI plus souvent muet ne « tient » pas dans une application.
EMISSION_MIN_BON = REFERENCE_EMISSION

# Le plancher du taux SSVEP (`ssvep_mesure.rejouer`). Le protocole joue au moins 8 essais : on n'y
# tombe que si le tampon du moteur en a perdu.
ESSAIS_MIN = 6

# L'étape NON enregistrée. En minuscules : « REPOS » est une CLASSE, pas une pause, et `_mesurer`
# ne compte que les étapes dont le nom est une classe du modèle.
PAUSE = "pause"

# Essais PAR CLASSE. Défaut COURT, parce qu'on refait ce test à chaque réglage ; 10 = l'effectif de
# la séance de référence (30 essais à 3 classes), pour TRANCHER quand l'intervalle est trop large.
ESSAIS_PAR_CLASSE = (4, 6, 10)
ESSAIS_PAR_CLASSE_DEFAUT = 6


def _hasard_de(classes):
    """Le niveau du hasard d'une décision parmi `classes`. DÉDUIT, jamais écrit en dur."""
    return 1.0 / len(classes)


def _label(cle):
    """Le libellé d'un réglage du mode MI : la réserve nomme le champ que l'étudiant a sous les yeux."""
    return next(p.label for p in SPEC_MI.params if p.key == cle)


class _DecideurMI(MIRuntime):
    """Le runtime du MODE, rejoué. Seul `_log` est coupé (« [mi] INTENTION… » ferait croire que le
    mode tourne) ; `_run_step` et `_publish`, qui portent la décision, sont hérités tels quels."""

    def _log(self, index, probas):
        pass


class _Rejeu:
    """Ce que `MIRuntime._run_step` lit d'un moteur : `acq` (pour `motor_window`) et `recent`."""

    def __init__(self, acq):
        self.acq = acq
        self.recent = None
        self.instance = "mi_test"


class MesureMI(MesureRuntime):
    """Le protocole d'entraînement MI, rejoué ; le moteur décide à la fin de chaque essai."""

    unite = "essai"          # une étape enregistrée = un essai entier (cf. `_essai`)

    def __init__(self, spec, params, engine, rng=None):
        # Retenue MAINTENANT : `cancel()` remet `self.engine` à None, et le calcul a besoin de
        # `motor_window`, le découpage exact du mode en direct.
        self._acq = getattr(engine, "acq", None)
        self._rejeu = _Rejeu(self._acq)
        # AVANT le socle, qui appelle `protocole()` : les essais sont tirés parmi les classes DU
        # MODÈLE. Un modèle effacé depuis la validation lève ici, avec la raison de `charger`.
        self._decideur = _DecideurMI(SPEC_MI, {p.key: params[p.key] for p in SPEC_MI.params},
                                     self._rejeu)
        self.classes = tuple(self._decideur.classes)
        super().__init__(spec, params, engine, rng=rng)

    @classmethod
    def _essai(cls, classe):
        """UN essai : la pause qui le précède (non enregistrée), puis l'essai entier (enregistré).

        La pause AVANT : la première prépare, et le calcul suit le dernier essai sans attente.
        """
        return (Etape(PAUSE, MI_REST_S, enregistre=False,
                      instruction="Pause — relâche, l'essai suivant arrive",
                      rappel="au TOP, la consigne change : imagine dès qu'elle s'affiche"),
                Etape(classe, MI_CUE_S + MI_IMAGERY_S,
                      instruction=INSTRUCTIONS.get(classe, f"Imagine : {classe}"),
                      rappel=RAPPEL if classe in MI_CONTROL else ""))

    def protocole(self):
        """Les essais, TIRÉS AU HASARD parmi les classes du modèle — un ordre fixe s'anticipe.

        Pas d'échauffement, à la différence de la calibration : un test exige un modèle, donc suit
        un entraînement, et six essais de plus (51 s) alourdiraient d'un tiers le test par défaut.
        """
        par_classe = int(self.params.get("trials_per_class", ESSAIS_PAR_CLASSE_DEFAUT))
        suite = [c for c in self.classes for _ in range(par_classe)]
        self.rng.shuffle(suite)
        return tuple(e for classe in suite for e in self._essai(classe))

    @classmethod
    def epoque_etape_s(cls):
        """La plus longue étape ENREGISTRÉE, sur laquelle le moteur dimensionne son tampon.

        ⚠️ Redéfinie : le socle joue `protocole()` sur la CLASSE, or celui-ci dépend d'une instance
        (modèle, tirage) — il rendrait 0, et nos essais de 7 s ne seraient couverts que par accident
        (la panne du contrôle alpha, étapes « IGNORÉES »). Mesurée par le même `_essai`.
        """
        return max(float(e.duree_s) for e in cls._essai("GAUCHE") if e.enregistre)

    def _sorties_de_l_essai(self, epoque, fs):
        """TOUTES les sorties que le mode aurait publiées pendant cet essai, dans l'ordre.

        À la cadence du mode, la DERNIÈRE fenêtre finissant avec l'imagerie. Le vote est vidé
        d'abord : sans effet sur la décision tant qu'un essai porte plus de fenêtres que le plus
        long vote (vérifié), mais c'est l'indépendance des essais qu'on tient, pas une arithmétique.
        """
        decideur = self._decideur
        decideur._reset_rest()
        epoque = np.asarray(epoque, dtype=float)
        pas = int(round(fs * decideur.period_s()))
        besoin = int(round(MI_WINDOW_S * fs))
        sorties = []
        for fin in range(len(epoque) - ((len(epoque) - besoin) // pas) * pas, len(epoque) + 1, pas):
            self._rejeu.recent = epoque[:fin]
            decideur._run_step(self._rejeu, 0.0)
            if decideur.output() is not None:
                sorties.append(decideur.output())
        return sorties

    def _decision_de_l_essai(self, sorties):
        """**LA décision d'un essai : la DERNIÈRE sortie. Une seule.** La classe, ou None.

        ⚠️ Les invariants n°2 et n°3 vivent ici : rendre toutes les sorties multiplierait l'effectif
        par ~26 ; lire `classes[intent_index]` sans tester `-1` ferait de chaque silence un REPOS.
        """
        index = int(sorties[-1]["intent_index"])
        if index < 0:
            return None
        return self.classes[index]

    def _mesurer(self, enregistre, fs):
        """Une décision par essai, puis le score. Aucun fichier."""
        if self._acq is None:
            raise ValueError("aucune acquisition : le test ne découperait pas les fenêtres comme "
                             "le mode, donc il ne mesurerait pas la règle du produit")
        decisions, fenetres = [], []
        for epoque, cible in enregistre:
            if cible not in self.classes:
                continue
            sorties = self._sorties_de_l_essai(epoque, fs)
            if not sorties:
                raise ValueError(f"un essai de {len(epoque) / fs:.1f} s ne porte aucune fenêtre de "
                                 f"{MI_WINDOW_S:g} s : protocole et décodeur ne s'accordent plus")
            fenetres.append(len(sorties))
            decisions.append((cible, self._decision_de_l_essai(sorties)))
        reglages = dict(self.params, model=_os.path.basename(str(self.params.get("model", ""))))
        resultat = noter(decisions, self.classes, perdus=self.total() - len(decisions),
                         essais_par_classe=int(self.params.get("trials_per_class", 0)) or None,
                         reglages=reglages)
        resultat["fenetres_par_essai"] = int(min(fenetres)) if fenetres else 0
        return resultat


def noter(decisions, classes, perdus=0, essais_par_classe=None, reglages=None):
    """Le score. `decisions` : `[(consigne, classe décidée | None), ...]`, **UNE par essai**.

    Les niveaux, jugés ICI (la console les peint, elle ne les recalcule pas) :
      • `faible` — aucune décision, ou le test binomial EXACT ne distingue pas la justesse du
        hasard (`affichage.au_dessus_du_hasard`, la porte partagée — Wilson reste l'intervalle
        affiché). La séance de référence (40 % à 3 classes, PAS significatif) y serait, et c'est
        juste.
      • `bon` — intervalle au-dessus du hasard, justesse au repère du projet pour ce nombre de
        classes, ET émission au moins celle du SSVEP dans son régime normal (44 %).
      • `moyen` — au-dessus du hasard, mais sous le repère ou trop souvent muet.
    """
    classes = tuple(classes)
    hasard = _hasard_de(classes)
    n_essais = len(decisions)
    if n_essais < ESSAIS_MIN:
        raise ValueError(f"{n_essais} essai(s) retenu(s) : il n'y a pas de quoi conclure — "
                         f"l'intervalle serait plus large que l'échelle.")
    emis = [(c, d) for c, d in decisions if d is not None]
    n_emis = len(emis)
    n_justes = sum(1 for c, d in emis if d == c)
    taux = n_emis / n_essais
    justesse = n_justes / n_emis if n_emis else 0.0
    # Sur les essais DÉCIDÉS : c'est la justesse À L'ÉMISSION qu'on encadre (invariant n°2).
    ic_bas, ic_haut = (float(v) for v in wilson(n_justes, n_emis))
    p = p_hasard(n_justes, n_emis, hasard)
    au_dessus = au_dessus_du_hasard(n_justes, n_emis, hasard)
    repere = REPERES_JUSTESSE.get(len(classes))

    if n_emis == 0 or not au_dessus:
        niveau, mot = "faible", ("MUET" if n_emis == 0 else "FAIBLE")
    elif repere is not None and justesse >= repere and taux >= EMISSION_MIN_BON:
        niveau, mot = "bon", "AU NIVEAU DU REPÈRE"
    else:
        niveau, mot = "moyen", "UTILISABLE"

    if n_emis == 0:
        chiffres = f"aucune décision sur {n_essais} essais (hasard {pct(hasard)}) : le vote n'a jamais conclu"
    else:
        chiffres = (f"{pct(justesse)} de classes justes, entre {ic_bas * 100:.0f} et "
                    f"{pct(ic_haut)} (hasard {pct(hasard)}) sur {n_emis} essais décidés sur "
                    f"{n_essais}")

    plus_long = max(ESSAIS_PAR_CLASSE)
    reglage = f"baisse « {_label('prob_min')} » ou « {_label('min_votes')} », puis re-teste."
    if n_emis == 0:
        reserve = f"Le vote n'a jamais conclu : {reglage}"
    elif niveau == "faible" and (essais_par_classe or 0) < plus_long:
        reserve = (f"Pas distinguable du hasard ({texte_p(p)}) : à {n_emis} essais décidés on ne "
                   f"peut pas conclure — refais le test à {plus_long} essais par classe avant de "
                   f"juger.")
    elif niveau == "faible":
        reserve = (f"Pas distinguable du hasard même sur un test long ({texte_p(p)}) : réentraîne "
                   f"— contact de C3/Cz/C4, immobilité, imagerie kinesthésique (SENTIR, pas voir).")
    elif taux < EMISSION_MIN_BON:
        reserve = f"Le moteur ne décide que sur {pct(taux)} des essais : {reglage}"
    elif niveau == "moyen":
        reserve = ("Au-dessus du hasard, mais sous le repère du projet : réentraîne, contact de "
                   "C3/Cz/C4 et imagerie kinesthésique (SENTIR, pas voir).")
    else:
        reserve = ("Mesuré sur CETTE séance : le MI baisse avec la fatigue — re-teste après une "
                   "pause avant de transcrire ces réglages dans ton application.")

    par_classe = {c: {"essais": sum(1 for k, _d in decisions if k == c),
                      "decides": sum(1 for k, d in decisions if k == c and d is not None),
                      "justes": sum(1 for k, d in decisions if k == c and d == c)}
                  for c in classes}
    verdict = (
        f"{mot} — sur {n_essais} ESSAIS (une décision par essai : ce que `decoded_mi` publiait à "
        f"la fin de l'imagerie, jamais une par fenêtre), le moteur a conclu {n_emis} fois — soit "
        f"{pct(taux)} d'émission — et il avait raison {n_justes} fois sur {n_emis}, soit "
        f"{pct(justesse)} [IC95 {ic_bas * 100:.0f} ; {ic_haut * 100:.0f}] pour un hasard à "
        f"{pct(hasard)} ({len(classes)} classes) — test binomial exact sur les essais décidés, "
        f"{texte_p(p)} : {'au-dessus du hasard' if au_dessus else 'indistinguable du hasard'}. "
        f"Les {n_essais - n_emis} essai(s) sans décision "
        f"(vote non conclu) ne comptent ni comme une erreur ni comme REPOS. ")
    if perdus:
        verdict += (f"⚠️ {perdus} essai(s) de plus ont été JOUÉS mais ne sont pas dans ce calcul : "
                    f"le tampon du moteur ne les couvrait pas. ")
    verdict += ("Par classe (justes / décidés / essais) : "
                + ", ".join(f"{c} {v['justes']}/{v['decides']}/{v['essais']}"
                            for c, v in par_classe.items()) + ". ")
    verdict += (f"Aucun repère du projet à {len(classes)} classes." if repere is None else
                f"Repère du projet à {len(classes)} classes : {pct(repere)} (calibration hors "
                f"ligne, une personne).")

    return {
        "n_essais": n_essais, "n_emis": n_emis, "n_justes": n_justes,
        "n_silences": n_essais - n_emis, "n_perdus": int(perdus),
        "taux_emission": round(taux, 3), "justesse": round(justesse, 3),
        "ic_bas": round(ic_bas, 3), "ic_haut": round(ic_haut, 3),
        "hasard": hasard, "p_hasard": round(p, 4), "classes": list(classes), "repere": repere,
        "par_classe": par_classe, "decisions": [(c, d) for c, d in decisions],
        "reglages": dict(reglages or {}),
        **lignes(niveau, mot, chiffres, reserve),
        "verdict": verdict,
        "honnetete": HONNETETE,
    }


# Le facteur dont l'effectif serait gonflé si on comptait les fenêtres, depuis les constantes.
FENETRES_PAR_ESSAI = int(round((MI_CUE_S + MI_IMAGERY_S - MI_WINDOW_S) * MI_DECODE_HZ)) + 1

HONNETETE = (
    "Ce test mesure la règle du PRODUIT — ton modèle, sa probabilité minimale, son vote — sur les "
    "réglages avec lesquels il a été lancé : une décision par essai, celle que `decoded_mi` "
    f"publiait quand l'imagerie se terminait. Les {FENETRES_PAR_ESSAI} fenêtres glissantes d'un "
    "essai ne sont pas autant d'observations : les compter rétrécirait l'intervalle d'un facteur "
    f"~{FENETRES_PAR_ESSAI ** 0.5:.0f} sans rien apprendre.\n"
    "Un essai SANS décision (vote non conclu, `intent_index = -1`) compte dans le taux d'émission, "
    "jamais comme une erreur, et JAMAIS comme REPOS : REPOS est une classe que le modèle doit "
    "reconnaître, « je ne sais pas » n'en est pas une.\n"
    "Repères : la seule séance de référence du projet, mesurée honnêtement en CALIBRATION (hors "
    "ligne), donnait 40 % à 3 classes (p = 0,082, PAS significatif) et 63 % à 2 classes "
    "(p = 0,038). Aucun repère EN DIRECT : le Motor Imagery n'a jamais été décodé au casque à "
    "travers le moteur. Un modèle est propre à UNE personne, et la justesse chute avec la fatigue "
    "(57 % puis 33 % entre les deux moitiés de la séance de référence) : ce score décrit CETTE "
    "séance."
)


def _duree_min(par_classe, n_classes):
    """La durée d'un test, en minutes — depuis la forme d'UN essai (`_essai`), jamais recopiée."""
    par_essai = sum(float(e.duree_s) for e in MesureMI._essai("GAUCHE"))
    return (MesureRuntime.warmup_s + par_classe * n_classes * par_essai) / 60.0


BRIEFING = (
    "Ce test rejoue le protocole d'ENTRAÎNEMENT, mais le moteur DÉCIDE au lieu d'apprendre : à la "
    "fin de chaque essai, il dit quelle classe il a reconnue avec ton modèle, et on compare à la "
    "consigne.",
    f"Déroulé : stabilisation du casque ({MesureRuntime.warmup_s:.0f} s), puis les essais, tirés au "
    f"hasard : {MI_REST_S:g} s de pause, puis {MI_CUE_S + MI_IMAGERY_S:.0f} s d'imagerie sur la "
    f"consigne affichée.",
    "Un TOP sonore marque le début et la fin de chaque essai ; la consigne est écrite à l'écran.",
    "Imagine EXACTEMENT comme à l'entraînement : dès la consigne, en SENTANT le serrement, sans "
    "bouger la main, et tiens jusqu'à la pause. REPOS = ne rien imaginer.",
    "Il faut un modèle entraîné : c'est lui qui décide. Rien n'est écrit sur le disque — ce test "
    "rend un score, pas un modèle.",
)


SPEC = MesureSpec(
    id="mi_test",
    label="Tester le Motor Imagery",
    summary="Le protocole d'entraînement, rejoué : le moteur décide avec ton modèle et tes "
            "réglages, et on compare à la consigne.",
    briefing=BRIEFING,
    # Les `Param` du MODE, les MÊMES objets : sans modèle, `contract.validate` refuse le test avec
    # la raison du mode — pas l'interface.
    params=tuple(SPEC_MI.params) + (
        Param(
            key="trials_per_class",
            label="Essais par classe",
            kind="choice",
            default=ESSAIS_PAR_CLASSE_DEFAUT,
            choices=ESSAIS_PAR_CLASSE,
            help=(f"Court par défaut, parce qu'on refait ce test à chaque réglage. Mais un test "
                  f"court a un intervalle de confiance LARGE : si le verdict dit « pas distinguable "
                  f"du hasard », prends {max(ESSAIS_PAR_CLASSE)} — l'effectif de la séance "
                  f"de référence du projet. À 3 classes : "
                  + ", ".join(f"{n} ≈ {_duree_min(n, 3):.1f} min".replace(".", ",")
                              for n in ESSAIS_PAR_CLASSE) + "."),
        ),
    ),
    runtime_cls=MesureMI,
)


def _selftest():
    """Sur des modèles entraînés à la volée, dans un dossier TEMPORAIRE — jamais `data/`."""
    import json
    import random as _random
    import shutil
    import tempfile

    from core import mi_models
    from core.acquisition import UnicornAcquisition
    from core.config import DATA_DIR, empreinte_dossier
    from core.mi_decoder import MI_LABELS, MIModel, synth_mi_trial
    from core.modes import registry
    from core.modes.contract import validate

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    empreinte_avant = empreinte_dossier(DATA_DIR)
    FS = 250.0
    N_ESSAI = int(round((MI_CUE_S + MI_IMAGERY_S) * FS))

    class _FausseAcq:
        """`motor_window` est CELLE de l'acquisition, empruntée : le découpage est celui du mode."""
        fs = FS
        motor_window = UnicornAcquisition.motor_window

    class _FauxMoteur:
        """Rend une époque de LA classe de l'étape en cours (ERD synthétique, ou `fabrique`)."""

        def __init__(self, rng, fabrique=None):
            self.acq, self.rng, self.rt, self.demandes, self.fabrique = _FausseAcq(), rng, None, [], fabrique

        def recent_window(self, seconds):
            self.demandes.append(seconds)
            n, classe = int(round(seconds * FS)), self.rt.classe
            if self.fabrique is not None:
                return self.fabrique(classe, n)
            return synth_mi_trial(classe, n_samp=n, fs=FS, rng=self.rng).T

    def _jouer(rt, moteur):
        moteur.rt, t = rt, 0.0
        for _ in range(40000):
            rt.tick(moteur, t)
            if rt.terminee:
                break
            t += 0.25
        return rt.resultat

    def _rejouer_en_continu(runtime, flux):
        """Fait décoder `runtime` sur `flux` à sa cadence, la dernière fenêtre au dernier échantillon."""
        pas, besoin, rejeu = int(round(FS * runtime.period_s())), int(round(MI_WINDOW_S * FS)), \
            _Rejeu(_FausseAcq())
        for fin in range(len(flux) - ((len(flux) - besoin) // pas) * pas, len(flux) + 1, pas):
            rejeu.recent = flux[:fin]
            runtime._run_step(rejeu, 0.0)
        i = runtime.output()["intent_index"]
        return None if i < 0 else runtime.classes[i]

    # === 1. LE HASARD SE DÉDUIT DES CLASSES ==================================================
    chk(abs(_hasard_de(["GAUCHE", "DROITE", "REPOS"]) - 1 / 3) < 1e-9,
        "trois classes -> hasard 1/3")
    chk(abs(_hasard_de(["GAUCHE", "DROITE"]) - 1 / 2) < 1e-9,
        "deux classes -> hasard 1/2 : il se DÉDUIT du modèle, il n'est pas écrit en dur")

    vrai_dispo = mi_models.modeles_disponibles
    dossier = tempfile.mkdtemp(prefix="mi_test_")
    try:
        rng = np.random.default_rng(0)
        for nom, labels in (("mi_model_3c.joblib", MI_LABELS), ("mi_model_2c.joblib", MI_CONTROL)):
            X = [synth_mi_trial(lab, rng=rng) for lab in labels for _ in range(10)]
            y = [lab for lab in labels for _ in range(10)]
            MIModel(labels=labels, fs=FS, reref_mode="none").fit(
                np.asarray(X), np.asarray(y)).save(_os.path.join(dossier, nom))
        m3 = _os.path.join(dossier, "mi_model_3c.joblib")
        m2 = _os.path.join(dossier, "mi_model_2c.joblib")

        # === 2. UN TEST EXIGE UN MODÈLE — refusé par le CONTRAT, pas par l'interface ===========
        vide = _os.path.join(dossier, "vide")
        _os.makedirs(vide)
        mi_models.modeles_disponibles = lambda d=vide: vrai_dispo(d)
        _v, raison = validate(SPEC, {})
        chk(raison is not None and "aucun choix disponible" in raison,
            f"sans modèle, `contract.validate` REFUSE le test, avec une raison lisible ({raison})")
        mi_models.modeles_disponibles = lambda d=dossier: vrai_dispo(d)
        valeurs, raison = validate(SPEC, {"model": m3})
        chk(valeurs is not None, f"avec un modèle, il passe ({raison})")
        chk(all(any(p is q for q in SPEC.params) for p in SPEC_MI.params),
            "le test déclare les `Param` du MODE eux-mêmes (identité) : la console lui passe les "
            "réglages courants tels quels")
        _v, raison = validate(SPEC, {"model": m3, "vote_len": 3, "min_votes": 10})
        chk(raison is not None and "10" in raison,
            f"…donc la contrainte du mode le protège : vote inatteignable refusé ({raison})")

        # === 3. LE PROTOCOLE ==================================================================
        rt = MesureMI(SPEC, valeurs, _FauxMoteur(rng), rng=_random.Random(1))
        enreg = [e for e in rt._etapes if e.enregistre]
        chk(rt.total() == len(enreg) == 18
            and all(sum(1 for e in enreg if e.nom == c) == 6 for c in MI_LABELS),
            f"6 essais par classe DU MODÈLE × 3 = 18 essais enregistrés ({rt.total()})")
        chk([e.nom for e in enreg] != sorted(e.nom for e in enreg),
            "…ENTRELACÉS au hasard, pas en blocs : un ordre fixe s'anticipe")
        chk(all(e.duree_s == MI_CUE_S + MI_IMAGERY_S for e in enreg)
            and all(e.duree_s == MI_REST_S for e in rt._etapes if not e.enregistre),
            "durées LUES dans `core/config.py` : essai = mise en route + imagerie, pause non "
            "enregistrée")
        chk(all(e.instruction == INSTRUCTIONS[e.nom] for e in enreg),
            "…et les consignes sont celles de l'ENTRAÎNEMENT, importées")
        chk(abs(rt.duree_estimee_s() - (MesureRuntime.warmup_s
                                        + 18 * (MI_REST_S + MI_CUE_S + MI_IMAGERY_S))) < 1e-9,
            f"la durée annoncée compte la chauffe et les pauses ({rt.duree_estimee_s():.0f} s)")
        chk(MesureMI.epoque_etape_s() == max(e.duree_s for e in enreg) > 0,
            f"le tampon du moteur est dimensionné sur l'essai ENTIER ({MesureMI.epoque_etape_s():g} "
            f"s) — le calcul du socle, joué sur la classe, rendrait 0")
        rt2 = MesureMI(SPEC, dict(valeurs, model=m2), _FauxMoteur(rng), rng=_random.Random(2))
        chk(rt2.classes == MI_CONTROL and "REPOS" not in {e.nom for e in rt2._etapes},
            f"un modèle GAUCHE/DROITE ne fait jouer AUCUN essai REPOS ({rt2.classes})")

        # === 4. DE BOUT EN BOUT, sur de l'ERD synthétique ======================================
        fichiers_avant = sorted(_os.listdir(dossier))
        moteur = _FauxMoteur(rng)
        rt = MesureMI(SPEC, valeurs, moteur, rng=_random.Random(3))
        res = _jouer(rt, moteur)
        chk(rt.phase == "fini" and res is not None,
            f"la séance se termine sur un verdict ({rt.phase}, {rt.probleme!r})")
        chk(rt.state(now=0.0).get("unite") == "essai",
            f"l'avancement affiché compte des ESSAIS ({rt.state(now=0.0).get('unite')!r})")
        chk(moteur.demandes == [MI_CUE_S + MI_IMAGERY_S] * 18,
            f"une fenêtre prélevée par essai, de la durée de l'essai ({len(moteur.demandes)})")
        chk(abs(res["hasard"] - 1 / 3) < 1e-9 and res["reglages"]["model"] == "mi_model_3c.joblib"
            and res["reglages"]["prob_min"] == valeurs["prob_min"],
            f"hasard du modèle chargé, et les réglages qui ont produit le score ({res['reglages']})")
        try:
            json.dumps(rt.state(now=0.0))
            serialisable = True
        except (TypeError, ValueError):
            serialisable = False
        chk(serialisable, "l'instantané, résultat compris, est sérialisable (il part dans `snapshot()`)")

        # === 5. UN ESSAI = UNE DÉCISION ========================================================
        # ⚠️ LE test de ce module : compter les ~26 sorties d'un essai est l'« amélioration »
        # plausible (plus de données, intervalle plus serré), et elle est fausse.
        chk(res["fenetres_par_essai"] == FENETRES_PAR_ESSAI > 1,
            f"chaque essai porte {res['fenetres_par_essai']} fenêtres de décision — sans ça "
            f"l'assertion suivante serait vraie à vide")
        chk(res["n_essais"] == len(res["decisions"]) == 18 and res["n_emis"] <= 18,
            f"…et l'effectif est le nombre d'ESSAIS ({res['n_essais']} essais, {res['n_emis']} "
            f"décidés — les fenêtres en auraient fait {18 * res['fenetres_par_essai']})")
        attendu = [round(float(v), 3) for v in wilson(res["n_justes"], res["n_emis"])]
        chk([res["ic_bas"], res["ic_haut"]] == attendu,
            f"l'intervalle porte sur les essais DÉCIDÉS ({attendu})")
        chk(res["fenetres_par_essai"] >= next(p.max for p in SPEC_MI.params if p.key == "vote_len"),
            "un essai porte plus de fenêtres que le plus long vote permis : le vote final n'en "
            "manque jamais, et l'essai précédent n'y vote jamais")
        chk(empreinte_dossier(DATA_DIR) == empreinte_avant
            and sorted(_os.listdir(dossier)) == fichiers_avant,
            "une séance complète n'a RIEN écrit — ni dans `data/`, ni à côté des modèles")

        # === 6. LA DÉCISION EST CELLE DU MODE, comparée à un MIRuntime qui décode EN CONTINU ====
        chk(issubclass(_DecideurMI, MIRuntime) and _DecideurMI._run_step is MIRuntime._run_step
            and _DecideurMI._publish is MIRuntime._publish,
            "le décideur EST le runtime du mode : `_run_step` et `_publish` ne sont pas redéfinis")

        # Scores FABRIQUÉS, lus dans le signal (voie 0 = un code), servis aux DEUX décodeurs.
        SCORES = {1: {"GAUCHE": 0.90, "DROITE": 0.05, "REPOS": 0.05},
                  2: {"GAUCHE": 0.05, "DROITE": 0.88, "REPOS": 0.07},
                  3: {"GAUCHE": 0.45, "DROITE": 0.30, "REPOS": 0.25},    # sous le seuil
                  4: {"GAUCHE": 0.04, "DROITE": 0.13, "REPOS": 0.83}}

        def _scores(window):
            return dict(SCORES[int(round(float(np.asarray(window)[-1, 0])))])

        def _signal(codes_et_durees):
            morceaux = []
            for code, duree in codes_et_durees:
                bloc = rng.normal(0.0, 1e-3, (int(round(duree * FS)), 8))
                bloc[:, 0] = code
                morceaux.append(bloc)
            return np.vstack(morceaux)

        # GAUCHE sûr 5,8 s, DROITE sûr 1 s, tiède 0,2 s : le vote final (5 fenêtres) voit 4 DROITE
        # + 1 tiède -> DROITE ; la première sortie n'a pas de vote ; la majorité des 26 est GAUCHE ;
        # la dernière fenêtre SEULE est sous le seuil. Trois lectures fausses, trois réponses fausses.
        essai = _signal([(1, 5.8), (2, 1.0), (3, 0.2)])
        avant = _signal([(4, MI_CUE_S + MI_IMAGERY_S), (3, MI_REST_S)])   # un essai REPOS + pause
        rt._decideur.decoder.scores = _scores
        sorties = rt._sorties_de_l_essai(essai, FS)
        decision = rt._decision_de_l_essai(sorties)
        direct = MIRuntime(SPEC_MI, {p.key: valeurs[p.key] for p in SPEC_MI.params},
                           _Rejeu(_FausseAcq()))
        direct._last_log = float("inf")          # pas de journal : ce n'est pas un vrai mode
        direct.decoder.scores = _scores
        en_direct = _rejouer_en_continu(direct, np.vstack([avant, essai]))
        chk(decision == en_direct == "DROITE",
            f"la décision du test est CELLE que `decoded_mi` publiait à la fin de l'imagerie, le "
            f"mode ayant décodé en continu depuis l'essai précédent ({decision} / {en_direct})")
        labels = [s["label"] for s in sorties]
        chk(rt._decision_de_l_essai(sorties[:1]) != decision
            and max(set(labels), key=labels.count) != decision,
            "…et la situation discrimine : la PREMIÈRE sortie et la MAJORITÉ répondraient autre chose")

        del rt._decideur.decoder.scores          # retour au VRAI décodeur (méthode de la classe)
        del direct.decoder.scores
        accord = 0
        for label in MI_LABELS * 3:
            ep = synth_mi_trial(label, n_samp=N_ESSAI, fs=FS, rng=rng).T
            prec = synth_mi_trial("DROITE" if label == "GAUCHE" else "GAUCHE",
                                  n_samp=N_ESSAI + int(round(MI_REST_S * FS)), fs=FS, rng=rng).T
            direct._reset_rest()
            accord += (rt._decision_de_l_essai(rt._sorties_de_l_essai(ep, FS))
                       == _rejouer_en_continu(direct, np.vstack([prec, ep])))
        chk(accord == 9, f"…et sur 9 essais d'ERD synthétique, sans bouchon, le test et le flux en "
                         f"direct décident pareil ({accord}/9)")

        # === 7. -1 VEUT DIRE « VOTE NON CONCLU », JAMAIS REPOS ===================================
        # Consignes REPOS -> scores tièdes (le vote ne conclut pas) ; GAUCHE/DROITE -> sûrs et justes.
        code_de = {"GAUCHE": 1, "DROITE": 2, "REPOS": 3}
        moteur7 = _FauxMoteur(rng, fabrique=lambda classe, n: _signal([(code_de[classe], n / FS)]))
        rt7 = MesureMI(SPEC, valeurs, moteur7, rng=_random.Random(7))
        rt7._decideur.decoder.scores = _scores
        res7 = _jouer(rt7, moteur7)
        repos7 = [d for c, d in res7["decisions"] if c == "REPOS"]
        chk(len(repos7) == 6 and all(d is None for d in repos7),
            f"un vote non conclu sur un essai REPOS reste SANS décision ({repos7})")
        chk(res7["n_emis"] == res7["n_justes"] == 12 and res7["n_silences"] == 6
            and abs(res7["taux_emission"] - 12 / 18) < 1e-3,
            f"…compté dans le taux d'émission ({res7['taux_emission']:.2f}), ni comme une erreur ni "
            f"comme un REPOS juste ({res7['n_justes']}/{res7['n_emis']})")
        code_de["REPOS"] = 4                      # la réciproque : REPOS reconnu avec certitude
        rt7b = MesureMI(SPEC, valeurs, moteur7, rng=_random.Random(8))
        rt7b._decideur.decoder.scores = _scores
        res7b = _jouer(rt7b, moteur7)
        chk(res7b["n_emis"] == 18 and res7b["par_classe"]["REPOS"]["justes"] == 6,
            f"…tandis qu'un REPOS reconnu est une décision ordinaire ({res7b['par_classe']['REPOS']})")

        # === 8. LES NIVEAUX, jugés par le moteur =================================================
        def _dec(classes, n, emis, justes):
            """`n` essais : les `justes` premiers justes, puis faux jusqu'à `emis`, puis muets."""
            return [(classes[i % len(classes)],
                     classes[i % len(classes)] if i < justes
                     else classes[(i + 1) % len(classes)] if i < emis else None)
                    for i in range(n)]

        bon = noter(_dec(MI_LABELS, 18, 18, 14), MI_LABELS, essais_par_classe=6)
        chk(bon["niveau"] == "bon" and bon["mot"] == "AU NIVEAU DU REPÈRE",
            f"14/18 à 3 classes, intervalle au-dessus du hasard -> bon ({bon['chiffres']})")
        muet_souvent = noter(_dec(MI_LABELS, 24, 5, 5), MI_LABELS, essais_par_classe=8)
        chk(muet_souvent["niveau"] == "moyen" and "Probabilité minimale" in muet_souvent["reserve"],
            f"5/5 justes sur 5 décisions en 24 essais -> moyen, et la réserve dit quel réglage "
            f"toucher ({muet_souvent['reserve']})")
        sous_repere = noter(_dec(MI_LABELS, 400, 400, 156), MI_LABELS)
        chk(sous_repere["niveau"] == "moyen" and sous_repere["ic_bas"] > 1 / 3,
            f"39 % sur 400 : au-dessus du hasard, sous le repère de 40 % -> moyen "
            f"({sous_repere['chiffres']})")
        flou = noter(_dec(MI_LABELS, 18, 13, 6), MI_LABELS, essais_par_classe=6)
        chk(flou["niveau"] == "faible" and "10 essais par classe" in flou["reserve"],
            f"6/13 : pas distinguable du hasard -> faible, et la réserve dit d'allonger "
            f"({flou['reserve']})")
        # I-2 : deux décisions justes sur 18 essais (3 classes), quatre sur 12 en gauche/droite.
        # Wilson les peignait ORANGE ; le test binomial exact dit p = 0,111 et p = 0,062.
        deux = noter(_dec(MI_LABELS, 18, 2, 2), MI_LABELS, essais_par_classe=6)
        gd = noter(_dec(MI_CONTROL, 12, 4, 4), MI_CONTROL, essais_par_classe=6)
        chk(deux["niveau"] == "faible" and gd["niveau"] == "faible"
            and "p = 0,111" in deux["verdict"] and "p = 0,06" in gd["verdict"],
            f"2/2 décidés à 3 classes et 4/4 en G/D ne sont PAS au-dessus du hasard : FAIBLE "
            f"({deux['mot']} / {gd['mot']})")
        muet = noter(_dec(MI_LABELS, 18, 0, 0), MI_LABELS)
        chk(muet["niveau"] == "faible" and muet["mot"] == "MUET",
            f"aucune décision -> MUET, pas un score ({muet['chiffres']})")
        # Le MÊME résultat brut, jugé contre deux hasards : c'est le hasard écrit en dur qui se voit.
        g3 = noter(_dec(MI_LABELS, 16, 16, 10), MI_LABELS)
        g2 = noter(_dec(MI_CONTROL, 16, 16, 10), MI_CONTROL)
        chk(g3["niveau"] != "faible" and g2["niveau"] == "faible" and "hasard 50 %" in g2["chiffres"],
            f"10/16 bat le hasard à 3 classes, PAS en gauche/droite ({g3['niveau']} / "
            f"{g2['niveau']} : {g2['chiffres']})")
        for r in (bon, muet_souvent, sous_repere, flou, muet, g2, res, res7):
            chk(not verifier(r) and r["niveau"] in NIVEAUX and "hasard" in r["chiffres"]
                and r["reserve"] and r["honnetete"],
                f"affichage cohérent (`affichage.verifier`) : {r['mot']} | {r['chiffres']} "
                f"{verifier(r)}")
        try:
            noter(_dec(MI_LABELS, 5, 5, 5), MI_LABELS)
            chk(False, "moins de 6 essais doit être refusé")
        except ValueError as e:
            chk("pas de quoi conclure" in str(e), f"moins de 6 essais : refusé ({str(e)[:40]}…)")

        # === 9. BRANCHÉ ===========================================================================
        vu = registry.get_mesure("mi_test")
        chk(vu is not None and vu.runtime_cls.__name__ == "MesureMI"
            and registry.get("mi").test_id == "mi_test",
            "le mode MI déclare `test_id='mi_test'`, et le registre la connaît")
        sain, defauts = registry.check()
        chk(sain, f"le registre reste sain ({defauts})")
    finally:
        mi_models.modeles_disponibles = vrai_dispo
        shutil.rmtree(dossier, ignore_errors=True)

    chk(empreinte_dossier(DATA_DIR) == empreinte_avant,
        f"`data/` est intact ({len(empreinte_avant)} fichiers avant, "
        f"{len(empreinte_dossier(DATA_DIR))} après)")
    print(f"[mi-test] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
