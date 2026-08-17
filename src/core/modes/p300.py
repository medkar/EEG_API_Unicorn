"""Mode P300 : quelle cible l'utilisateur a sélectionnée, par onde P300 (oddball attentionnel).
BCI **active**, pilotée par les MARQUEURS d'une application EXTERNE — ni casque supplémentaire,
ni stimulus rendu par le moteur.

Le décodage est dans `core/p300_decoder.py` (xDAWN + covariances riemanniennes + régression
logistique). Ici on décrit le MODE : ce qui se règle, ce qui se publie, et ce qu'il faut avoir
avant de pouvoir décoder — à savoir un modèle ENTRAÎNÉ. C'est la même contrainte que le Motor
Imagery (`core/modes/mi.py`, le jumeau le plus proche de ce fichier, à lire avant celui-ci) : sans
modèle, ce mode ne démarre pas, et il le DIT.

⚠️ Un modèle est propre à UNE personne. Les scores d'un modèle entraîné sur quelqu'un d'autre sont
plausibles et faux — le pire des deux mondes.

⚠️ Le moteur ne rend AUCUN stimulus : c'est une application EXTERNE qui fait clignoter les cibles
et publie l'onset de chaque flash sur un flux de marqueurs LSL (`core/markers.py`). Ce mode se
contente d'ÉCOUTER ce flux (`engine.markers_murs`), d'épocher l'EEG autour de chaque flash
(`core.p300_decoder.epoch_from_stream`), et de décider à `round_end`.

⚠️ **`target_index = -1` signifie « pas de décision » — jamais « la cible 0 ».** Une manche qui ne
peut pas conclure (trop peu de flashs valides, ou des cibles qui n'ont pas toutes eu la chance de
flasher) publie -1 ET dit pourquoi dans le journal, plutôt que de choisir un argmax sur un
sous-ensemble de cibles. C'est mot pour mot la garde qu'il a fallu inscrire pour le Motor Imagery
(`DecodedMIPublisher`) — elle se reproduira chez le premier client qui lit ce flux sans lire la doc.

Six pannes bruyantes de ce sous-système (un décodeur qui tourne, publie des scores honnêtes et
ne déclenche simplement jamais est la panne la plus coûteuse de ce projet) :
    1. aucun flux de marqueurs trouvé       -> dit par `EngineServer._ouvre_marker_inlet`
    2. un marqueur plus vieux que le tampon -> compté, `engine.marqueurs_perdus`
    3. un marqueur dans le futur            -> compté, `engine.marqueurs_futurs`
    4. une cible hors de la plage déclarée  -> dite une fois PAR MANCHE, comptée (`_refus_cible`)
    5. `round_end` avec trop peu de flashs  -> dite, publiée comme -1 (`_decider`)
    6. `round_end` qui n'arrive JAMAIS      -> dite, manche ABANDONNÉE (`_verifie_abandon`)
Les trois premières vivent une couche plus bas (`core/markers.py`, `core/server.py`) et sont
prouvées là-bas ; ce fichier ajoute et prouve les trois dernières, propres au protocole P300.

⚠️ **La 6e (trouvée à la relecture, pas au premier jet) est la plus sournoise des six** : sans
`_verifie_abandon`, une application externe qui plante EN PLEINE manche (le cas normal d'un
plantage) laisse `_epoques`/`_cibles` avec des flashs ORPHELINS, pour toujours. Si l'application
redémarre et flashe une manche NEUVE sans avoir renvoyé le `round_end` de l'ancienne, les nouveaux
flashs s'EMPILENT sur les orphelins. Le garde de couverture (`len(par_cible) < n_targets`) ne
vérifie que « chaque cible a flashé au moins une fois » — pas « ces flashs viennent de la MÊME
manche » : une contamination peut le satisfaire, atteindre `select()`, et publier une cible
choisie avec une confiance normale — silencieusement fausse. Aucune des cinq autres pannes ne
s'en aperçoit.

Autotest :
    python src/core/modes/p300.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (MARKER_STREAM_DEFAULT, P300_EPOCH_S, P300_N_TARGETS,  # noqa: E402
                         P300_PRE_S, P300_REPS, P300_ROUND_TIMEOUT_S, P300_SELECT_MARGIN,
                         SSVEP_WARMUP_S, use_utf8_console)
import numpy as np  # noqa: E402

from core import p300_models  # noqa: E402
from core.lsl_io import DecodedP300Publisher, p300_channel_labels, stream_name  # noqa: E402
from core.p300_decoder import epoch_from_stream  # noqa: E402
from core.modes.contract import Calib, ModeSpec, Param, Rest, validate  # noqa: E402
from core.modes.runtime import ModeRuntime  # noqa: E402

# Plafond DUR sur une manche : au-delà, elle ne se fermera visiblement JAMAIS (`round_end` perdu
# ou jamais envoyé) — on l'abandonne en le disant plutôt que de laisser les listes grossir sans
# borne. ×2 la taille d'une manche normale (P300_N_TARGETS cibles × P300_REPS répétitions) :
# large marge pour un protocole qui répéterait plus que la référence, sans laisser fuiter une
# manche qui n'en finit jamais. Dérivé du protocole, pas une constante séparée dans config.py :
# rien d'autre n'en a besoin.
_MAX_EPOQUES = P300_N_TARGETS * P300_REPS * 2


class P300Runtime(ModeRuntime):
    """Écoute les marqueurs d'une application externe, époque l'EEG autour de chaque flash, et
    décide à `round_end`. Aucune fenêtre glissante à faire tourner : ce mode ne fait RIEN tant
    qu'aucun marqueur n'arrive, il est entièrement piloté par ce que l'application externe envoie.

    Pourquoi aucun plancher à mesurer, comme le MI : la référence cible/non-cible est APPRISE
    pendant la calibration, ce n'est pas un niveau de bruit du jour. Seule la CHAUFFE reste :
    l'offset DC de l'Unicorn dérive après ouverture de session, et Fz/Cz/Pz — la ligne médiane où
    le P300 est maximal — y est exposée comme n'importe quelle voie.

    `pre_s`/`post_s` sont des ATTRIBUTS DE CLASSE, pas seulement des variables locales : c'est ce
    qui permet au contrôle structurel de `registry.check()` de comparer `spec.marker_epoch_s` (ce
    que le moteur DIMENSIONNE) à ce que ce runtime PRÉLÈVE vraiment. Jumeau exact de
    `Calib.epoch_s` comparé à `MICalibration.imagery_s`.

    ⚠️ Une manche qui n'a jamais reçu son `round_end` (application externe plantée en plein
    milieu) est ABANDONNÉE — voir `_verifie_abandon`, appelée à chaque `_run_step`. Sans ça, ses
    flashs restent ORPHELINS indéfiniment, et une manche NEUVE lancée plus tard s'empilerait
    dessus en silence.
    """

    pre_s = P300_PRE_S
    post_s = P300_EPOCH_S

    def __init__(self, spec, params, engine):
        super().__init__(spec, params, engine)
        self._out = None
        self._decoded = None
        # La géométrie (6 cibles) est FIXE — alignée sur le c-VEP pour comparer les deux
        # paradigmes à cibles identiques (cf. `core/config.py`, P300_N_TARGETS) — pas un réglage
        # du mode : contrairement au MI, dont les classes dépendent du modèle choisi.
        self.n_targets = P300_N_TARGETS
        self.model, raison = p300_models.charger(params["model"])
        if self.model is None:
            # On lève ICI plutôt que de démarrer un mode muet. `validate` a déjà écarté le cas
            # « aucun modèle » ; il reste celui du fichier effacé entre la validation et le
            # démarrage, que seul le moteur peut voir.
            raise ValueError(raison)
        self._epoques = []          # les époques valides de la manche EN COURS
        self._cibles = []           # la cible flashée pour chaque époque, même index que ci-dessus
        # L'horodatage (temps MARQUEUR, jamais `time.time()` — cf. `_verifie_abandon`) du dernier
        # flash valide accepté dans la manche en cours. None : aucune manche en cours.
        self._dernier_flash_ts = None
        # `_refus_cible` est réarmé À CHAQUE manche (`_vider_manche`) : une cible hors plage est
        # un défaut de CETTE manche-là, pas seulement de la toute première de la session — sans
        # le réarmement, une récidive plus tard dans la séance serait comptée mais ne s'imprime
        # plus jamais. `_epoques_perdues` et `_manches_abandonnees` restent au contraire des
        # compteurs de SESSION, jamais réinitialisés — le même choix que `engine.marqueurs_perdus`
        # et consorts : rien ne délimite « une manche » pour un marqueur déjà rejeté avant d'avoir
        # rejoint une manche, ou pour une manche qui n'a justement jamais pu s'en fermer une.
        self._refus_cible = 0          # cibles hors plage reçues DANS LA MANCHE EN COURS
        self._epoques_perdues = 0      # marqueurs mûrs dont l'époque a quand même débordé
        self._manches_abandonnees = 0  # manches jetées faute de round_end (panne n°6)

    def _open(self):
        # Comme le SSVEP et le MI : le flux existe TOUT DE SUITE, avant même la fin de la
        # chauffe. Un client qui le cherche au lancement ne doit pas dépendre de l'instant où
        # arrive le premier flash — `resolve_byprop` a un délai fini.
        self._out = DecodedP300Publisher(self.n_targets, reps=P300_REPS,
                                         instance=self.engine.instance)

    def _close(self):
        self._out = None

    def _reset_rest(self):
        self._vider_manche()
        self._decoded = None

    def output(self):
        return self._decoded

    def state(self):
        """Comme `ModeRuntime.state()`, plus les compteurs des pannes bruyantes n°4/5/6.

        Sans cette sortie, `_refus_cible`/`_epoques_perdues`/`_manches_abandonnees` n'ont AUCUN
        filet en dehors du terminal : un client qui n'a pas la console ouverte au bon instant ne
        les voit jamais, et `print` n'est lu par personne en dehors d'une séance surveillée.
        """
        base = super().state()
        base["refus_cible"] = self._refus_cible
        base["epoques_perdues"] = self._epoques_perdues
        base["manches_abandonnees"] = self._manches_abandonnees
        return base

    def _rest_step(self, engine, now):
        """Rien à mesurer : comme le MI, seule la chauffe compte (cf. docstring de la classe)."""
        if now < self._rest_until:
            return False
        print(f"[p300] modèle « {_os.path.basename(self.params['model'])} » — écoute des "
              f"marqueurs sur « {self.params['stream_in']} », publication sur "
              f"{stream_name('decoded_p300')} ({self.n_targets} cibles)")
        self.rest_report = {"kind": "p300", "model": _os.path.basename(self.params["model"]),
                            "n_targets": self.n_targets}
        return True

    def _run_step(self, engine, lsl_ts):
        """Ramasser les flashs mûrs, décider à `round_end`, et abandonner une manche qui ne se
        fermera visiblement jamais (panne n°6)."""
        for ts, marqueur in engine.markers_murs(self.spec.id, post_s=self.post_s):
            event = marqueur.get("event")
            if event == "flash":
                self._encaisser_flash(engine, ts, marqueur)
            elif event == "round_end":
                self._decider(lsl_ts)
            # Tout autre événement est ignoré : le protocole s'enrichira, et un mode qui
            # refuserait ce qu'il ne connaît pas casserait au premier ajout.
        # APRÈS le lot de ce tour, pas seulement quand un marqueur arrive : c'est précisément le
        # cas d'une application plantée (plus AUCUN marqueur, jamais) qu'il faut attraper, et lui
        # seul garantit que `_run_step` continue d'être appelé (`lsl_ts` avance à chaque tour de
        # la boucle du moteur, marqueurs ou pas).
        self._verifie_abandon(lsl_ts)

    def _encaisser_flash(self, engine, ts, marqueur):
        cible = marqueur.get("target")
        if not isinstance(cible, int) or not 0 <= cible < self.n_targets:
            # Panne bruyante n°4 : une cible hors plage est un bug de l'application cliente.
            # Le dire une fois PAR MANCHE suffit (`_refus_cible` est réarmé dans `_vider_manche`) ;
            # le répéter à chaque flash noierait le terminal — jusqu'à 48 par manche (8 répétitions
            # × 6 cibles).
            self._refus_cible += 1
            if self._refus_cible == 1:
                print(f"[p300] cible « {cible} » hors de la plage attendue "
                      f"[0, {self.n_targets}[ — vérifie l'émetteur de marqueurs")
            return
        epoque = epoch_from_stream(engine.recent, engine.recent_ts, ts, engine.acq.fs,
                                   pre_s=self.pre_s, post_s=self.post_s)
        if epoque is None:
            # Le marqueur était mûr mais l'époque déborde quand même : le tampon a été vidé
            # entre-temps. Compté, jamais tu — comme `engine.marqueurs_perdus` juste en dessous.
            self._epoques_perdues += 1
            return
        self._epoques.append(epoque)
        self._cibles.append(cible)
        # Horodatage MARQUEUR, jamais `time.time()` (cf. `_verifie_abandon`) : c'est ce qui permet
        # de dire « cette manche n'a plus donné signe de vie depuis X secondes » sans que le
        # runtime touche à une horloge lui-même.
        self._dernier_flash_ts = ts

    def _verifie_abandon(self, lsl_ts):
        """Abandonne la manche en cours si elle ne se fermera visiblement JAMAIS — panne n°6.

        Deux façons de le détecter, et je veux les deux :
          1. **Délai d'abandon** : aucun flash accepté depuis plus de `P300_ROUND_TIMEOUT_S`. Ce
             qui attrape une application externe plantée EN PLEINE manche — le cas normal d'un
             plantage, et le seul des deux qui ne dépend pas du DÉBIT de flashs.
          2. **Plafond dur** (`_MAX_EPOQUES`) : bien plus d'époques qu'un protocole normal n'en
             produit — l'application tourne toujours mais n'envoie plus jamais `round_end`.

        ⚠️ Comparaison entre horodatages de MARQUEURS et `lsl_ts` (celui que `tick()` reçoit du
        moteur) — jamais `time.time()` : un runtime ne lit jamais l'horloge lui-même dans ce
        projet (cf. `ModeRuntime`). `lsl_ts` avance à CHAQUE tour de la boucle du moteur, y
        compris quand `engine.markers_murs` ne rend rien — c'est précisément ce qui rend le
        délai d'abandon détectable même quand plus AUCUN marqueur n'arrive jamais.

        Sans ce garde-fou : les flashs d'une manche avortée restent ORPHELINS dans `_epoques`/
        `_cibles`. Si l'application redémarre et flashe une manche NEUVE sans avoir renvoyé le
        `round_end` de l'ancienne, les nouveaux flashs s'EMPILENT sur les orphelins. Le garde de
        couverture de `_decider` (`len(par_cible) < n_targets`) ne vérifie que « chaque cible a
        flashé au moins une fois » — pas « ces flashs viennent de la MÊME manche » : une
        contamination peut le satisfaire, atteindre `select()`, et publier une cible choisie avec
        une confiance normale — SILENCIEUSEMENT fausse. Aucune des cinq autres pannes ne s'en
        aperçoit (prouvé par `_selftest`, scénario dédié).
        """
        if not self._epoques:
            return
        trop_vieille = (self._dernier_flash_ts is not None
                        and lsl_ts - self._dernier_flash_ts > P300_ROUND_TIMEOUT_S)
        trop_pleine = len(self._epoques) > _MAX_EPOQUES
        if not (trop_vieille or trop_pleine):
            return
        if trop_vieille:
            raison = (f"aucun flash accepté depuis {lsl_ts - self._dernier_flash_ts:.1f} s "
                      f"(> {P300_ROUND_TIMEOUT_S:g} s)")
        else:
            raison = f"{len(self._epoques)} flashs accumulés (plafond {_MAX_EPOQUES})"
        self._manches_abandonnees += 1
        print(f"[p300] manche ABANDONNÉE : {raison} — round_end jamais reçu (application externe "
              f"plantée ?). {len(self._epoques)} flash(s) orphelin(s) jeté(s).")
        self._vider_manche()

    def _decider(self, lsl_ts):
        """Fin de manche : agréger les scores par cible et publier — ou dire pourquoi non."""
        if len(self._epoques) < self.n_targets:
            # Panne bruyante n°5 : une manche trop courte ne peut pas départager les cibles.
            # On publie quand même, avec -1 ET la raison : un client qui attend un échantillon
            # par manche ne doit pas rester suspendu.
            print(f"[p300] manche ignorée : {len(self._epoques)} flashs pour {self.n_targets} "
                  f"cibles — il en faut au moins un par cible")
            self._publish(-1, 0.0, len(self._epoques), [0.0] * self.n_targets, lsl_ts)
            self._vider_manche()
            return

        par_cible = {}
        for epoque, cible in zip(self._epoques, self._cibles):
            par_cible.setdefault(cible, []).append(epoque)
        if len(par_cible) < self.n_targets:
            # Une cible qui n'a jamais flashé n'a aucun score : l'argmax porterait sur un
            # sous-ensemble, et désignerait une cible « gagnante » parmi celles qui ont eu la
            # chance d'être montrées. Refuser est la seule réponse honnête — sans même consulter
            # le modèle (prouvé par `_selftest`, avec un modèle-espion qui compte ses appels).
            print(f"[p300] manche ignorée : {len(par_cible)} cibles ont flashé sur "
                  f"{self.n_targets} — l'émetteur n'a pas fini sa séquence")
            self._publish(-1, 0.0, len(self._epoques), [0.0] * self.n_targets, lsl_ts)
            self._vider_manche()
            return

        # `select` agrège lui-même les répétitions (moyenne des log-odds) et applique la marge.
        # On ne ré-agrège rien ici : ce calcul a été validé au casque, le refaire à côté en
        # créerait une seconde version qui finirait par diverger. `P300_SELECT_MARGIN` vient
        # directement de `core.config` : c'est une constante de PROTOCOLE, pas un réglage exposé.
        choisi, moyennes = self.model.select(par_cible, margin=P300_SELECT_MARGIN)
        # L'appariement score_<i> <-> cible i est le CONTRAT PUBLIC du flux : une inversion ne se
        # voit ni sur les bornes de l'index, ni sur le nombre de voies — seulement ici. On
        # construit donc `scores` en parcourant les indices DANS L'ORDRE, jamais `list(moyennes.
        # values())` (dont l'ordre suit l'insertion dans `par_cible`, pas l'indice de la cible).
        scores = [float(moyennes.get(i, 0.0)) for i in range(self.n_targets)]
        if choisi is None:
            self._publish(-1, 0.0, len(self._epoques), scores, lsl_ts)
        else:
            self._publish(int(choisi), float(moyennes[choisi]), len(self._epoques),
                          scores, lsl_ts)
        self._vider_manche()

    def _vider_manche(self):
        """Repart pour la manche suivante : les flashs déjà décidés (ou orphelins abandonnés) ne
        doivent pas fuiter dans la décision d'après.

        `_refus_cible` est réarmé ICI, PAS gardé pour toute la session : une cible hors plage est
        un défaut DE CETTE manche, et une récidive dans une manche sans rapport doit se réimprimer
        — sinon la garde `== 1` ne se déclenche plus jamais après la toute première de la vie du
        runtime, silencieusement, pour le reste de la séance.
        """
        self._epoques = []
        self._cibles = []
        self._dernier_flash_ts = None
        self._refus_cible = 0

    def _publish(self, target_index, confidence, n_flashes, scores, lsl_ts):
        if self._out is not None:
            self._out.push(target_index, confidence, n_flashes, scores, lsl_ts)
        self._decoded = {
            "target_index": int(target_index),
            "confidence": round(float(confidence), 3),
            "n_flashes": int(n_flashes),
            "scores": [round(float(s), 3) for s in scores],
        }
        self._log(target_index, n_flashes, scores)

    def _log(self, target_index, n_flashes, scores):
        """Trace CHAQUE décision, sans limite de fréquence : contrairement au SSVEP/MI (~5 Hz en
        continu), ce flux est RARE — une manche complète prend plusieurs secondes, aucun risque
        de noyer le terminal (cf. docstring de `DecodedP300Publisher`)."""
        detail = "  ".join(f"cible {i}: {s:+.2f}" for i, s in enumerate(scores))
        verdict = (f"— (manche non conclue, {n_flashes} flash(s) valides)" if target_index < 0
                  else f"CIBLE {target_index}")
        print(f"[p300] {verdict:<34} {detail}")


def _channels(params):
    """Les voies du P300 : `n_targets` est une géométrie FIXE (couronne à 6 cibles, alignée sur
    le c-VEP), pas un réglage du mode — contrairement au MI, dont les voies dépendent du modèle
    choisi. `params` n'est donc pas lu ; l'argument existe pour respecter le contrat `channels_fn`.
    """
    return p300_channel_labels(P300_N_TARGETS)


SPEC = ModeSpec(
    id="p300",
    label="P300",
    family="actif",
    summary="Sélection parmi 6 cibles par onde P300 (oddball attentionnel).",
    status="moteur",
    params=(
        Param(key="model", label="Modèle entraîné", kind="choice",
              choices_fn=lambda: p300_models.modeles_disponibles(),
              help="Le modèle produit par une calibration P300, propre à TA personne — celui "
                   "de quelqu'un d'autre donne des scores plausibles et faux. Aucun modèle "
                   "dans la liste ? Lance `python src/research/app.py`, mode P300, et calibre."),
        Param(key="stream_in", label="Flux de marqueurs", kind="choice",
              choices=(MARKER_STREAM_DEFAULT,), default=MARKER_STREAM_DEFAULT,
              affecte_decodage=False,
              help="Le nom du flux LSL sur lequel ton application publie l'onset de chaque "
                   "flash. Le moteur l'écoute par son NOM, résolu la PREMIÈRE fois qu'un mode "
                   "qui consomme des marqueurs démarre dans cette session — un seul inlet existe "
                   "pour tout le moteur. Le changer plus tard n'a AUCUN effet tant que le moteur "
                   "lui-même tourne encore, pas même en redémarrant ce mode : il faut relancer le "
                   "moteur pour qu'un nouveau nom soit repris. Deux modes actifs qui en "
                   "réclameraient des noms différents ne sont pas mélangés en silence : un "
                   "désaccord est signalé bruyamment, un seul nom gagne."),
    ),
    rest=Rest(warmup_s=SSVEP_WARMUP_S, duration_s=0.0,
              instruction="Le casque se stabilise — reste immobile."),
    calibration=Calib(kind="natif",
                      reason="époques calées sur l'onset exact de chaque flash, rendu par "
                             "l'application externe"),
    stream="decoded_p300",
    channels_fn=_channels,
    runtime_cls=P300Runtime,
    marker_epoch_s=P300_PRE_S + P300_EPOCH_S,   # 0,95 s — dimensionne le tampon du moteur
)


def _selftest():
    """Le mode de bout en bout : un vrai modèle entraîné sur du P300 synthétique, un faux moteur
    qui rend des marqueurs SUR COMMANDE.

    La MATURITÉ d'un marqueur (horodatage, curseur par mode, purge) est déjà prouvée dans
    `server.py` (`_smoke_marqueurs_murs`, `_smoke_marqueurs_file_coincee`) : ce mode ne la
    réimplémente pas, ce test ne la rejoue donc pas non plus. Il se concentre sur ce que CE mode
    fait de marqueurs déjà mûrs : épocher, agréger par cible, décider, publier — et sur les trois
    pannes bruyantes propres au protocole P300 (cible hors plage, manche trop courte, manche qui
    ne se ferme jamais).
    """
    import io
    import shutil
    import tempfile
    from contextlib import redirect_stdout

    from core.acquisition import UnicornAcquisition
    from core.p300_decoder import P300Model, synth_p300_epoch

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _FauxPublieur:
        def __init__(self):
            self.lignes = []

        def push(self, target_index, confidence, n_flashes, scores, lsl_ts=None):
            self.lignes.append((target_index, confidence, n_flashes, list(scores)))

    class _FauxMoteur:
        """Juste ce dont le runtime a besoin. `markers_murs` rend les marqueurs un LOT à la
        fois, dans l'ordre fourni pour CE test : la maturité elle-même (horodatage, curseur,
        purge) est déjà prouvée côté `server.py` (cf. docstring de `_selftest`)."""

        def __init__(self, recent, recent_ts):
            self.acq = UnicornAcquisition(synthetic=True)
            self.instance = "selftest"
            self.recent = recent
            self.recent_ts = recent_ts
            self._lots = []

        def markers_murs(self, mode_id, post_s):
            return self._lots.pop(0) if self._lots else []

    class _ModeleControle:
        """Un faux modèle P300 dont `select` renvoie des scores FIXES et CONNUS par cible, pour
        prouver l'appariement score_<i> <-> cible i sans dépendre d'un vrai décodage (déjà
        validé dans `p300_decoder.py`)."""

        def __init__(self, scores_par_cible, gagnant):
            self._scores = dict(scores_par_cible)
            self._gagnant = gagnant
            self.appels = 0

        def select(self, epochs_by_target, margin=0.0):
            self.appels += 1
            return self._gagnant, dict(self._scores)

    class _ModeleEspion:
        """Compte ses appels — sert à prouver qu'une manche incomplète ne consulte JAMAIS le
        modèle plutôt que de lui demander un argmax sur un sous-ensemble de cibles."""

        def __init__(self):
            self.appels = 0

        def select(self, epochs_by_target, margin=0.0):
            self.appels += 1
            return 0, {k: 99.0 for k in epochs_by_target}   # une réponse CERTAINE si jamais appelée

    class _ModeleCapture:
        """Capture la FORME de `epochs_by_target` (nombre d'époques par cible) sans juger leur
        contenu — sert à prouver qu'une manche neuve n'hérite d'AUCUN flash orphelin d'une manche
        avortée. Si une contamination avait lieu, une cible retrouvée dans les deux manches
        porterait DEUX époques au lieu d'une, et cette capture le montrerait directement."""

        def __init__(self):
            self.recu = None

        def select(self, epochs_by_target, margin=0.0):
            self.recu = {k: len(v) for k, v in epochs_by_target.items()}
            return 0, {k: 0.0 for k in epochs_by_target}

    def marqueur(t, cible):
        return (t, {"mode": "p300", "event": "flash", "target": cible})

    def fin_manche(t):
        return (t, {"mode": "p300", "event": "round_end"})

    rng = np.random.default_rng(0)
    fs = 250.0
    # 20 s de tampon continu, largement assez de marge pour des flashs entre t=101 et t=118 avec
    # pre_s=0,15 / post_s=0,80. Du BRUIT, pas des zéros : une covariance nulle sur toutes les
    # époques rendrait la moyenne riemannienne de xDAWN dégénérée.
    recent_ts = np.arange(100.0, 120.0, 1.0 / fs)
    recent = rng.normal(0.0, 5.0, (len(recent_ts), 8))

    vrai_dispo = p300_models.modeles_disponibles
    dossier = tempfile.mkdtemp(prefix="p300_mode_")
    try:
        # Un modèle jetable, entraîné sur du P300 synthétique (même recette que
        # `p300_decoder._synth_dataset`, en plus court : ce test ne juge pas la justesse du
        # décodage, seulement le CONTRAT du mode).
        epochs, y, groups = [], [], []
        n_rounds, reps = 6, 4
        for r in range(n_rounds):
            cue = r % P300_N_TARGETS
            for _ in range(reps):
                for tgt in range(P300_N_TARGETS):
                    epochs.append(synth_p300_epoch(tgt == cue, fs=fs, rng=rng))
                    y.append(1 if tgt == cue else 0)
                    groups.append(r)
        modele = P300Model(fs=fs).fit(np.asarray(epochs), np.asarray(y), groups=np.asarray(groups))
        chemin = _os.path.join(dossier, "p300_model.joblib")
        modele.save(chemin)

        # 1. Sans modèle du tout, le mode REFUSE et dit comment en obtenir un.
        vide = _os.path.join(dossier, "aucun")
        _os.makedirs(vide, exist_ok=True)
        p300_models.modeles_disponibles = lambda dossier=vide: vrai_dispo(dossier)
        _v, raison = validate(SPEC, {})
        chk(raison is not None and "aucun choix disponible" in raison
            and "research/app.py" in raison,
            f"sans modèle, le mode refuse en disant quoi faire ({raison})")

        # 2. Avec un modèle, les défauts sont valides et c'est lui qui est pris.
        p300_models.modeles_disponibles = lambda d=dossier: vrai_dispo(d)
        values, raison = validate(SPEC, {})
        chk(values is not None, f"avec un modèle, les défauts passent ({raison})")
        chk(values["model"] == chemin, f"et c'est le modèle trouvé qui est pris ({values['model']})")
        chk(values["stream_in"] == MARKER_STREAM_DEFAULT,
            f"le flux de marqueurs par défaut est celui du protocole ({values['stream_in']})")
        chk(_channels(values) == list(p300_channel_labels(P300_N_TARGETS)),
            f"les voies sont celles de la géométrie à {P300_N_TARGETS} cibles ({_channels(values)})")
        chk({p.key for p in SPEC.params} == {"model", "stream_in"},
            "P300_SELECT_MARGIN n'est PAS un réglage exposé : une constante de protocole ne "
            "bouge pas dans ce chantier")

        # 3. `pre_s`/`post_s` sont des ATTRIBUTS DE CLASSE — c'est ce que `registry.check()` lit
        # pour comparer `marker_epoch_s` (le tampon que le moteur DIMENSIONNE) à ce que ce
        # runtime PRÉLÈVE vraiment. Jumeau exact : `Calib.epoch_s` contre `MICalibration.imagery_s`.
        chk(P300Runtime.pre_s == P300_PRE_S and P300Runtime.post_s == P300_EPOCH_S,
            f"pre_s/post_s sont exposés en attributs de CLASSE ({P300Runtime.pre_s}, "
            f"{P300Runtime.post_s})")
        chk(SPEC.marker_epoch_s == P300Runtime.pre_s + P300Runtime.post_s,
            f"marker_epoch_s du contrat vaut EXACTEMENT pre_s+post_s du runtime "
            f"({SPEC.marker_epoch_s:g} == {P300Runtime.pre_s + P300Runtime.post_s:g})")

        moteur = _FauxMoteur(recent, recent_ts)
        rt = P300Runtime(SPEC, values, moteur)
        rt._out = _FauxPublieur()
        rt._opened = True
        chk(rt.phase == "warmup", "le P300 commence par une chauffe")

        # 4. Chauffe puis écoute, sans plancher à mesurer.
        rt.begin_rest(now=0.0, warmup_s=0.0, duration_s=0.0)
        rt.tick(moteur, lsl_ts=0.0, now=0.1)
        rt.tick(moteur, lsl_ts=0.2, now=0.2)
        chk(rt.phase == "running", f"un repos de durée nulle passe tout de suite ({rt.phase})")
        chk(rt.rest_report and rt.rest_report["kind"] == "p300",
            f"et laisse un compte-rendu nommant le modèle ({rt.rest_report})")

        # 5. Une manche COMPLÈTE, sur le VRAI décodeur (chaque cible flashe au moins une fois) :
        # on ne juge PAS la justesse du décodage (déjà validée dans `p300_decoder.py` sur du vrai
        # P300 synthétique) — ici le signal est du BRUIT — seulement le CONTRAT : un index dans
        # les bornes, un score par cible, `n_flashes` qui compte les flashs incorporés.
        t = 101.0
        lot = []
        for tgt in range(P300_N_TARGETS):
            lot.append(marqueur(t, tgt))
            t += 0.15
        lot.append(fin_manche(t))
        moteur._lots = [lot]
        rt.tick(moteur, lsl_ts=t, now=1.0)
        chk(len(rt._out.lignes) == 1,
            f"une décision publiée pour cette manche complète ({len(rt._out.lignes)})")
        index, _confiance, n_flashes, scores = rt._out.lignes[-1]
        chk(-1 <= index < P300_N_TARGETS, f"index de cible dans les bornes ({index})")
        chk(len(scores) == P300_N_TARGETS, f"un score par cible ({scores})")
        chk(n_flashes == P300_N_TARGETS,
            f"n_flashes compte les flashs valides incorporés à la décision ({n_flashes})")
        chk(rt.output() is not None and rt.output()["target_index"] == index,
            f"la sortie exposée à l'affichage reprend la même décision ({rt.output()})")

        # --- PREUVE 1/2 : l'appariement score_<i> <-> cible i --------------------------------
        # Un modèle-CONTRÔLE dont `select` renvoie des scores FIXES, ASYMÉTRIQUES et tous
        # DISTINCTS : une inversion, un tri, ou un décalage d'index produirait une liste
        # DIFFÉRENTE de celle attendue — rien ici ne pourrait passer par coïncidence.
        scores_connus = {0: -3.0, 1: 7.0, 2: -1.5, 3: 0.5, 4: -2.5, 5: 4.0}
        rt.model = _ModeleControle(scores_connus, gagnant=1)
        t = 101.0
        lot = []
        for tgt in range(P300_N_TARGETS):
            lot.append(marqueur(t, tgt))
            t += 0.15
        lot.append(fin_manche(t))
        moteur._lots = [lot]
        rt.tick(moteur, lsl_ts=t, now=2.0)
        index, confiance, _n, scores = rt._out.lignes[-1]
        attendu = [scores_connus[i] for i in range(P300_N_TARGETS)]
        chk(scores == attendu,
            f"score_<i> correspond EXACTEMENT à la cible i, dans l'ordre des indices "
            f"({scores} attendu {attendu})")
        chk(index == 1 and abs(confiance - 7.0) < 1e-9,
            f"et la cible choisie est celle du meilleur score, avec CE score comme confiance "
            f"({index}, {confiance})")

        # --- PREUVE 2/2 : une manche INCOMPLÈTE publie -1, sans même consulter le modèle -------
        # Cas A : moins de flashs valides que de cibles (`len(self._epoques) < n_targets`).
        espion = _ModeleEspion()
        rt.model = espion
        t = 101.0
        lot = [marqueur(t, 0), marqueur(t + 0.15, 1), marqueur(t + 0.30, 2)]
        lot.append(fin_manche(t + 0.45))
        moteur._lots = [lot]
        rt.tick(moteur, lsl_ts=t + 0.45, now=3.0)
        index, _c, n_flashes, scores = rt._out.lignes[-1]
        chk(index == -1 and n_flashes == 3,
            f"3 flashs pour {P300_N_TARGETS} cibles : la manche est refusée, PAS un argmax sur "
            f"les 3 cibles vues (index={index}, n_flashes={n_flashes})")
        chk(scores == [0.0] * P300_N_TARGETS,
            f"et les scores publiés sont neutres, pas ceux d'un calcul partiel ({scores})")
        chk(espion.appels == 0,
            f"le modèle n'est même pas CONSULTÉ — {espion.appels} appel(s) au lieu de 0")

        # Cas B : autant (ou plus) de flashs que de cibles, mais pas TOUTES les cibles vues —
        # celui que la preuve rouge-puis-vert cible : la brèche ne se voit ni sur le nombre de
        # flashs ni sur les bornes de l'index, seulement sur la COUVERTURE des cibles.
        t = 101.0
        lot = []
        for _ in range(P300_N_TARGETS):        # 6 flashs, mais seulement 2 cibles distinctes
            for tgt in (0, 1):
                lot.append(marqueur(t, tgt))
                t += 0.15
        lot.append(fin_manche(t))
        moteur._lots = [lot]
        rt.tick(moteur, lsl_ts=t, now=4.0)
        index, _c, n_flashes, scores = rt._out.lignes[-1]
        chk(index == -1 and n_flashes == 2 * P300_N_TARGETS,
            f"{2 * P300_N_TARGETS} flashs mais 2 cibles seulement sur {P300_N_TARGETS} : "
            f"refusée quand même, pas un argmax sur les 2 cibles vues (index={index}, "
            f"n_flashes={n_flashes})")
        chk(scores == [0.0] * P300_N_TARGETS, f"scores neutres, pas partiels ({scores})")
        chk(espion.appels == 0,
            f"le modèle n'est TOUJOURS pas consulté — {espion.appels} appel(s) au lieu de 0")

        # --- PREUVE CRITIQUE : une manche AVORTÉE (jamais de round_end) n'en contamine pas une
        # NEUVE ------------------------------------------------------------------------------
        # Le garde de couverture de `_decider` (`len(par_cible) < n_targets`) vérifie seulement
        # « chaque cible a flashé au moins une fois » — pas « ces flashs viennent de la MÊME
        # manche ». Sans `_verifie_abandon`, une application plantée en pleine manche (le cas
        # normal d'un plantage) laisse des flashs ORPHELINS ; si elle redémarre et flashe une
        # manche neuve sans jamais avoir envoyé le round_end de l'ancienne, les nouveaux flashs
        # s'EMPILENT dessus, silencieusement.
        capture_modele = _ModeleCapture()
        rt.model = capture_modele

        # Manche AVORTÉE : seulement 3 des 6 cibles flashent, puis PLUS RIEN — pas de round_end,
        # exactement ce qu'un plantage produit.
        t0 = 101.0
        lot = [marqueur(t0, 0), marqueur(t0 + 0.15, 1), marqueur(t0 + 0.30, 2)]
        moteur._lots = [lot]
        rt.tick(moteur, lsl_ts=t0 + 0.30, now=10.0)
        chk(len(rt._epoques) == 3,
            f"les 3 flashs de la manche avortée sont bien en attente, round_end jamais arrivé "
            f"({len(rt._epoques)})")

        # Le temps passe, largement au-delà du délai d'abandon — SANS AUCUN NOUVEAU MARQUEUR :
        # c'est le simple passage du temps qui doit déclencher l'abandon (`lsl_ts` avance à
        # chaque tour de la boucle du moteur, marqueurs ou pas), pas un événement particulier.
        avant_abandons = rt._manches_abandonnees
        moteur._lots = []
        lsl_apres_delai = t0 + 0.30 + P300_ROUND_TIMEOUT_S + 1.0
        rt.tick(moteur, lsl_ts=lsl_apres_delai, now=25.0)
        chk(len(rt._epoques) == 0,
            f"la manche avortée est jetée après le délai, sans aucun nouveau marqueur "
            f"({len(rt._epoques)} époque(s) restante(s))")
        chk(rt._manches_abandonnees == avant_abandons + 1,
            f"l'abandon est COMPTÉ ({rt._manches_abandonnees - avant_abandons})")

        # Manche NEUVE et complète : une époque PAR cible. Si les 3 orphelins avaient survécu,
        # les cibles 0/1/2 porteraient CHACUNE deux époques au lieu d'une — c'est ce que
        # `_ModeleCapture` révèle, en lisant directement ce que `_decider` lui a transmis.
        t1 = 115.0
        lot = []
        for tgt in range(P300_N_TARGETS):
            lot.append(marqueur(t1, tgt))
            t1 += 0.15
        lot.append(fin_manche(t1))
        moteur._lots = [lot]
        rt.tick(moteur, lsl_ts=t1, now=26.0)
        chk(capture_modele.recu == {i: 1 for i in range(P300_N_TARGETS)},
            f"la manche neuve n'hérite d'AUCUN flash orphelin de l'avortée : une époque par "
            f"cible, jamais deux ({capture_modele.recu})")

        # --- Panne bruyante n°6 (variante) : le PLAFOND abandonne aussi, sans attendre le délai.
        # Débit rapide, `round_end` qui n'arrive jamais : au-delà de `_MAX_EPOQUES`, la manche est
        # jetée tout de suite — pas besoin d'attendre `P300_ROUND_TIMEOUT_S` d'inactivité.
        t2 = 101.0
        lot = []
        for i in range(_MAX_EPOQUES + 1):
            lot.append(marqueur(t2, i % P300_N_TARGETS))
            t2 += 0.02
        moteur._lots = [lot]
        avant_abandons = rt._manches_abandonnees
        rt.tick(moteur, lsl_ts=t2, now=27.0)
        chk(rt._manches_abandonnees == avant_abandons + 1,
            f"le plafond ({_MAX_EPOQUES} époques) abandonne aussi, sans attendre le délai "
            f"({rt._manches_abandonnees - avant_abandons})")
        chk(len(rt._epoques) == 0, "et la manche est bien vidée après coup")

        # --- Panne bruyante n°4 : une cible hors plage, réarmée à CHAQUE manche --------------
        # Manche A : trois cibles invalides dans la MÊME manche. COMPTÉES chacune, mais dites
        # UNE SEULE fois — répéter l'avertissement à chaque flash noierait le terminal.
        #
        # ⚠️ Le round_end est envoyé dans un tick SÉPARÉ, PAS dans le même lot que les trois
        # flashs invalides : `_decider` (déclenché par round_end) appelle `_vider_manche()`, qui
        # réarme `_refus_cible` à 0 dans la FOULÉE — si les deux partageaient un tick, le compte
        # serait déjà retombé à 0 avant que ce test ait pu le lire, pour la mauvaise raison (la
        # remise à zéro fonctionnerait, mais on croirait à tort que rien n'a été compté).
        avant = rt._refus_cible
        t = 101.0
        lot = [marqueur(t, 99), marqueur(t + 0.15, -1), marqueur(t + 0.30, "deux")]
        moteur._lots = [lot]
        capture = io.StringIO()
        with redirect_stdout(capture):
            rt.tick(moteur, lsl_ts=t + 0.30, now=5.0)
        texte = capture.getvalue()
        print(texte, end="")     # rejoué : la capture ne doit pas rendre ce test muet
        chk(rt._refus_cible == avant + 3,
            f"les trois cibles hors plage de la manche A sont COMPTÉES ({rt._refus_cible - avant})")
        chk(texte.count("hors de la plage") == 1,
            f"...mais l'avertissement n'est imprimé qu'UNE fois pour les trois "
            f"({texte.count('hors de la plage')} occurrence(s))")

        # Referme la manche A PROPREMENT (aucune époque valide dedans -> publie -1), DANS UN TICK
        # À PART : c'est CE round_end qui doit réarmer `_refus_cible`, prouvé juste après.
        moteur._lots = [[fin_manche(t + 0.45)]]
        rt.tick(moteur, lsl_ts=t + 0.45, now=5.5)
        chk(rt._refus_cible == 0,
            f"la fermeture de la manche A réarme le compteur à 0 ({rt._refus_cible})")

        # Manche B, séparée de A par ce round_end : une SEULE cible invalide doit de nouveau
        # s'imprimer — la garde s'est RÉARMÉE à la fermeture de la manche A, ce n'est PAS « la
        # première de la session » (sans quoi toute récidive plus tard serait comptée mais ne
        # s'imprimerait plus jamais, sans le moindre filet en dehors du terminal).
        t = 110.0
        lot = [marqueur(t, 99)]
        moteur._lots = [lot]
        capture2 = io.StringIO()
        with redirect_stdout(capture2):
            rt.tick(moteur, lsl_ts=t, now=6.0)
        texte2 = capture2.getvalue()
        print(texte2, end="")
        chk(texte2.count("hors de la plage") == 1,
            f"une manche B, neuve, réimprime l'avertissement : la garde n'est pas « une fois "
            f"par session » ({texte2.count('hors de la plage')} occurrence(s))")
        chk(rt._refus_cible == 1, f"et son propre compteur repart bien de 1, pas de 4 ({rt._refus_cible})")
        moteur._lots = [[fin_manche(t + 0.15)]]
        rt.tick(moteur, lsl_ts=t + 0.15, now=6.5)   # referme B proprement avant la suite du test

        # --- Panne bruyante n°5 (variante) : l'époque déborde malgré un marqueur mûr ---------
        # Simule un tampon vidé entre la maturité du marqueur et son traitement : un horodatage
        # hors du tampon fait rendre None à `epoch_from_stream`, sans lever.
        avant_perdues = rt._epoques_perdues
        lot = [marqueur(5.0, 0)]           # 5.0 est loin AVANT recent_ts[0]=100.0
        moteur._lots = [lot]
        rt.tick(moteur, lsl_ts=5.0, now=6.0)
        chk(rt._epoques_perdues == avant_perdues + 1,
            f"une époque qui déborde du tampon est COMPTÉE, pas ignorée en silence "
            f"({rt._epoques_perdues - avant_perdues})")
        chk(len(rt._epoques) == 0,
            "...et ne rejoint PAS la manche en cours (elle n'a rien à décoder)")
        rt._vider_manche()

        # Les compteurs de pannes ont une sortie AUTRE que le terminal : `state()`, lu par la
        # console (ou n'importe quel autre client du moteur qui n'a pas les yeux sur les logs).
        etat = rt.state()
        chk({"refus_cible", "epoques_perdues", "manches_abandonnees"} <= set(etat),
            f"les trois compteurs de pannes bruyantes sont exposés dans state() ({sorted(etat)})")
        chk(etat["refus_cible"] == rt._refus_cible
            and etat["epoques_perdues"] == rt._epoques_perdues
            and etat["manches_abandonnees"] == rt._manches_abandonnees,
            f"...et reflètent les compteurs RÉELS du runtime, pas une copie figée "
            f"(state={etat['refus_cible'], etat['epoques_perdues'], etat['manches_abandonnees']}, "
            f"réel={rt._refus_cible, rt._epoques_perdues, rt._manches_abandonnees})")

        # 6. Le contrat du mode.
        chk(SPEC.rest.duration_s == 0.0 and SPEC.rest.warmup_s == SSVEP_WARMUP_S,
            f"chauffe obligatoire, aucun plancher ({SPEC.rest})")
        chk(SPEC.stream == "decoded_p300" and SPEC.status == "moteur",
            "le mode publie decoded_p300 et tourne dans le moteur")
        chk(SPEC.calibration is not None and SPEC.calibration.kind == "natif"
            and SPEC.calibration.runtime_cls is None,
            "sa calibration reste NATIVE : le moteur ne la joue pas, l'appli pygame la joue")
        chk(all(p.affecte_decodage for p in SPEC.params if p.key != "stream_in"),
            "le modèle affecte le décodage ; le flux de marqueurs (juste le NOM écouté), non")
        chk(P300_ROUND_TIMEOUT_S > 0.0,
            f"un délai d'abandon strictement positif est déclaré ({P300_ROUND_TIMEOUT_S:g} s)")
        chk(_MAX_EPOQUES > P300_N_TARGETS,
            f"le plafond dur dépasse largement une manche normale ({_MAX_EPOQUES} > "
            f"{P300_N_TARGETS})")
    finally:
        p300_models.modeles_disponibles = vrai_dispo
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[p300] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
