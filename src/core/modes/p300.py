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

Sept pannes bruyantes de ce sous-système (un décodeur qui tourne, publie des scores honnêtes et
ne déclenche simplement jamais est la panne la plus coûteuse de ce projet) :
    1. aucun flux de marqueurs trouvé       -> dit par `EngineServer._ouvre_marker_inlet`
    2. un marqueur plus vieux que le tampon -> compté, `engine.marqueurs_perdus`
    3. un marqueur dans le futur            -> compté, `engine.marqueurs_futurs`
    4. une cible hors de la plage déclarée  -> dite PAR PALIERS dans la manche (`_refus_cible`)
    5. `round_end` avec trop peu de flashs  -> dite, publiée comme -1 (`_decider`)
    6. `round_end` qui n'arrive JAMAIS      -> dite, manche ABANDONNÉE (`_verifie_abandon`)
    7. des flashs pendant la CHAUFFE        -> jetés, comptés (`_marqueurs_chauffe`), dits
Les trois premières vivent une couche plus bas (`core/markers.py`, `core/server.py`) et sont
prouvées là-bas ; ce fichier ajoute et prouve les quatre dernières, propres au protocole P300.

⚠️ **La 6e (trouvée à la relecture, pas au premier jet) est la plus sournoise des sept** : sans
`_verifie_abandon`, une application externe qui plante EN PLEINE manche (le cas normal d'un
plantage) laisse `_epoques`/`_cibles` avec des flashs ORPHELINS, pour toujours. Si l'application
redémarre et flashe une manche NEUVE sans avoir renvoyé le `round_end` de l'ancienne, les nouveaux
flashs s'EMPILENT sur les orphelins. Le garde de couverture (`len(par_cible) < n_targets`) ne
vérifie que « chaque cible a flashé au moins une fois » — pas « ces flashs viennent de la MÊME
manche » : une contamination peut le satisfaire, atteindre `select()`, et publier une cible
choisie avec une confiance normale — silencieusement fausse. Aucune des six autres pannes ne
s'en aperçoit.

⚠️ **La 7e a la même forme, un cran plus tôt.** Personne ne consomme les marqueurs pendant la
chauffe : sans le `tick` redéfini ci-dessous, le curseur du moteur ne bouge pas de toute la
chauffe, puis le premier `_run_step` avale l'arriéré — dont tout ce qui a déjà quitté le tampon
EEG, `round_end` compris. C'est le comportement PAR DÉFAUT de la première manche de chaque
séance (l'émetteur flashe dès son lancement, et `docs/markers.md` dit de le lancer à côté du
moteur), et de chaque « Refaire le repos ». On les JETTE donc explicitement, en le comptant et en
le disant : une époque prélevée pendant que l'offset DC de l'Unicorn dérive encore n'a de toute
façon aucune valeur — c'est exactement ce que la chauffe existe pour écarter.

Autotest :
    python src/core/modes/p300.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (MARKER_STREAM_DEFAULT, P300_EPOCH_S, P300_MIN_REPS,  # noqa: E402
                         P300_N_TARGETS, P300_PRE_S, P300_REPS, P300_ROUND_TIMEOUT_S,
                         P300_SELECT_MARGIN, SSVEP_WARMUP_S, use_utf8_console)
import numpy as np  # noqa: E402

from core import p300_models  # noqa: E402
from core.lsl_io import DecodedP300Publisher, p300_channel_labels, stream_name  # noqa: E402
from core.p300_decoder import epoch_from_stream  # noqa: E402
from core.modes.contract import Calib, ModeSpec, Param, Rest, validate  # noqa: E402
from core.modes.runtime import ModeRuntime  # noqa: E402

# Plafond DUR d'une manche, compté **PAR CIBLE** : au-delà, ce ne sont plus les répétitions d'une
# même manche, c'est une manche NEUVE soudée à la précédente par un `round_end` perdu.
#
# ⚠️ Ce plafond était GLOBAL (`P300_N_TARGETS * P300_REPS * 2` = 96 époques), et il ratait le seul
# cas crédible : une manche normale fait 48 époques, deux manches soudées en font exactement 96,
# et `96 > 96` est FAUX. Les deux garde-fous se taisaient, `select()` recevait 96 époques dont la
# moitié portaient l'intention de la manche PRÉCÉDENTE, et le moteur publiait une cible plausible
# avec une confiance normale — silencieusement fausse. Trois manches soudées (144) déclenchaient
# bien : le garde attrapait l'invraisemblable et ratait le vraisemblable.
#
# Pourquoi PAR CIBLE et pas un `>=` sur le plafond global : un compteur global ne peut pas à la
# fois tolérer un protocole qui répéterait plus que la référence ET distinguer 2×8 répétitions de
# 1×16. Le discriminant « par cible » n'a pas cette ambiguïté : dans UNE manche, une cible flashe
# `reps` fois, jamais plus. Le prix est assumé et il est BRUYANT : une application qui répète plus
# de `P300_REPS` fois par cible fait abandonner ses manches, avec un message qui nomme la
# constante à changer — au lieu de publier une sélection fausse sans un mot. C'est aussi ce que
# `DecodedP300Publisher` annonce désormais dans ses métadonnées (`max_reps_per_target`) : un
# PLAFOND que le moteur applique, et non plus le nombre de répétitions de l'application externe,
# que le moteur ne contrôle pas.
#
# Pourquoi pas l'ÉCART entre deux flashs consécutifs (une frontière de manche dure plus qu'un SOA
# de 150 ms) : mesuré sur l'émetteur de ce dépôt, la frontière entre deux manches est aujourd'hui
# un intervalle inter-flash ordinaire — il n'y a AUCUNE pause à détecter (c'est un défaut connu de
# l'émetteur, pas du mode). Un seuil sur l'écart ne détecterait donc rien ici, et punirait au
# passage un protocole légitimement lent (un speller à SOA 1 s). Le compte par cible, lui, ne
# dépend d'aucune horloge.
_MAX_PAR_CIBLE = P300_REPS

# Paliers auxquels une cible refusée se DIT (panne n°4), dans la manche en cours. Le même motif
# que les compteurs de marqueurs du moteur (`EngineServer._dit_compteurs_marqueurs`) : une ligne
# par ordre de grandeur, jamais une par flash.
_PALIERS_REFUS = (1, 10, 100, 1000)


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
        desaccord = self._desaccord_geometrie(engine)
        if desaccord is not None:
            # Même refus, pour la même raison : un modèle entraîné sur une AUTRE géométrie
            # d'époque (autre fréquence d'échantillonnage, autres bornes pré/post) rend des scores
            # parfaitement plausibles et faux. `registry.check()` compare déjà `marker_epoch_s` au
            # runtime — le contrat au moteur ; ce contrôle-ci compare le runtime au MODÈLE, la
            # moitié que personne ne regardait.
            raise ValueError(desaccord)
        self._epoques = []          # les époques valides de la manche EN COURS
        self._cibles = []           # la cible flashée pour chaque époque, même index que ci-dessus
        # L'horodatage (temps MARQUEUR, jamais `time.time()` — cf. `_verifie_abandon`) du dernier
        # flash REÇU dans la manche en cours, accepté OU refusé. None : aucune manche en cours.
        # ⚠️ « Reçu » et pas « accepté » : une application bien vivante qui numérote mal ses cibles
        # serait sinon indiscernable d'une application morte, et sa manche — 100 % refusée, donc
        # sans une seule époque — ne pourrait JAMAIS être abandonnée (donc jamais réarmer le
        # message de la panne n°4).
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
        self._marqueurs_chauffe = 0    # flashs jetés parce que reçus pendant la chauffe (n°7)
        self._chauffe_dite = False     # l'avertissement de chauffe, une fois par chauffe

    def _desaccord_geometrie(self, engine):
        """La phrase à dire si le MODÈLE n'a pas été entraîné sur la géométrie que ce runtime
        prélève — None si tout concorde.

        `P300Model` porte `fs`, `pre_s` et `post_s` en attributs : ce sont les trois nombres qui
        décident de la FORME d'une époque (`(pre_s+post_s)*fs` échantillons) et de l'endroit où
        l'onset tombe dedans. Un modèle entraîné à 500 Hz, ou avec 300 ms de pré-stimulus, reçoit
        ici des matrices d'une autre taille (xDAWN lèverait) ou, pire, de la MÊME taille avec
        l'onset ailleurs — et sort alors des log-odds plausibles et faux.
        """
        fs_moteur = float(getattr(getattr(engine, "acq", None), "fs", 0.0) or 0.0)
        attendus = (("fs", fs_moteur), ("pre_s", float(self.pre_s)), ("post_s", float(self.post_s)))
        ecarts = []
        for nom, attendu in attendus:
            valeur = getattr(self.model, nom, None)
            if valeur is None or abs(float(valeur) - attendu) > 1e-9:
                ecarts.append(f"{nom} : modèle {valeur}, moteur {attendu:g}")
        if not ecarts:
            return None
        return (f"ce modèle n'a pas été entraîné sur la géométrie d'époque que ce mode prélève "
                f"({' ; '.join(ecarts)}) — ses scores seraient plausibles et faux. Recalibre "
                f"(`python src/research/app.py`, mode P300) plutôt que de le forcer.")

    def _open(self):
        # Comme le SSVEP et le MI : le flux existe TOUT DE SUITE, avant même la fin de la
        # chauffe. Un client qui le cherche au lancement ne doit pas dépendre de l'instant où
        # arrive le premier flash — `resolve_byprop` a un délai fini.
        self._out = DecodedP300Publisher(self.n_targets, max_reps=_MAX_PAR_CIBLE,
                                         margin=P300_SELECT_MARGIN,
                                         instance=self.engine.instance)

    def _close(self):
        self._out = None

    def _reset_rest(self):
        self._vider_manche()
        self._decoded = None
        self._chauffe_dite = False

    def output(self):
        return self._decoded

    def state(self):
        """Comme `ModeRuntime.state()`, plus les compteurs de tout ce que ce mode JETTE.

        Chacun compte une perte d'un genre différent : une cible hors plage (panne n°4), une
        époque qui a débordé du tampon malgré un marqueur mûr (la variante « locale » de la panne
        n°2), une manche jetée faute de `round_end` (n°6), et les flashs reçus pendant la chauffe
        (n°7).

        Sans cette sortie, les quatre n'ont AUCUN filet en dehors du terminal : un client qui n'a
        pas la console ouverte au bon instant ne les voit jamais, et `print` n'est lu par personne
        en dehors d'une séance surveillée.
        """
        base = super().state()
        base["refus_cible"] = self._refus_cible
        base["epoques_perdues"] = self._epoques_perdues
        base["manches_abandonnees"] = self._manches_abandonnees
        base["marqueurs_chauffe"] = self._marqueurs_chauffe
        return base

    def _rest_step(self, engine, now):
        """Rien à mesurer : comme le MI, seule la chauffe compte (cf. docstring de la classe)."""
        if now < self._rest_until:
            return False
        print(f"[p300] modèle « {_os.path.basename(self.params['model'])} » — écoute des "
              f"marqueurs sur « {self.params['stream_in']} », publication sur "
              f"{stream_name(self.spec.stream)} ({self.n_targets} cibles)")
        self.rest_report = {"kind": "p300", "model": _os.path.basename(self.params["model"]),
                            "n_targets": self.n_targets}
        return True

    def tick(self, engine, lsl_ts, now):
        """Comme `ModeRuntime.tick`, mais la chauffe CONSOMME les marqueurs au lieu de les laisser
        s'empiler derrière un curseur immobile (panne n°7, cf. docstring du module).

        Redéfinir `tick` plutôt qu'écrire ça dans `_rest_step` : `_rest_step` n'est appelé QUE
        pendant la phase « rest », et c'est la phase « warmup » (15 s, la plus longue des deux
        ici, `Rest.duration_s` valant 0) qui laisse l'arriéré se former.
        """
        if self.phase != "running":
            self._jeter_marqueurs_de_chauffe(engine)
        super().tick(engine, lsl_ts, now)

    def _jeter_marqueurs_de_chauffe(self, engine):
        """Vide la file de CE mode pendant la chauffe, en comptant et en le disant une fois.

        Appeler `markers_murs` est ce qui fait avancer le curseur du moteur : sans cet appel, le
        moteur garde tout, puis le premier `_run_step` reçoit d'un coup 15 s de flashs dont la
        plupart n'ont plus leur EEG dans le tampon — ils partiraient alors en
        `engine.marqueurs_perdus`, comptés par le moteur mais sans que personne puisse dire
        pourquoi. Les jeter ICI est le même geste que la chauffe elle-même (`ModeRuntime.tick` :
        « on JETTE ces secondes »), mais dit à voix haute.
        """
        jetes = engine.markers_murs(self.spec.id, post_s=self.post_s)
        if not jetes:
            return
        self._marqueurs_chauffe += len(jetes)
        if not self._chauffe_dite:
            self._chauffe_dite = True
            print(f"[p300] {len(jetes)} marqueur(s) reçus pendant la CHAUFFE : jetés — l'offset DC "
                  f"du casque dérive encore, ces époques ne valent rien. La première manche "
                  f"décodée sera la première COMPLÈTE après la chauffe.")

    def _run_step(self, engine, lsl_ts):
        """Ramasser les flashs mûrs, décider à `round_end`, et abandonner une manche qui ne se
        fermera visiblement jamais (panne n°6)."""
        for ts, marqueur in engine.markers_murs(self.spec.id, post_s=self.post_s):
            event = marqueur.get("event")
            if event == "flash":
                self._encaisser_flash(engine, ts, marqueur)
                # APRÈS `_encaisser_flash` (qui peut abandonner la manche et donc remettre cet
                # horodatage à None), et pour un flash REFUSÉ aussi bien qu'accepté : cf. le
                # commentaire de `_dernier_flash_ts` dans `__init__`.
                self._dernier_flash_ts = ts
            elif event == "round_end":
                # L'instant du `round_end`, PAS `lsl_ts` : la boucle du moteur tourne à ~5 Hz et
                # l'émetteur enchaîne les manches sans pause, donc « maintenant » tombe 0,9 à
                # 1,1 s plus tard — souvent DANS la manche suivante. Un client qui aligne cette
                # décision sur autre chose (une vidéo, un log de jeu) lirait un décalage constant.
                self._decider(ts)
            # Tout autre événement est ignoré : le protocole s'enrichira, et un mode qui
            # refuserait ce qu'il ne connaît pas casserait au premier ajout.
        # APRÈS le lot de ce tour, pas seulement quand un marqueur arrive : c'est précisément le
        # cas d'une application plantée (plus AUCUN marqueur, jamais) qu'il faut attraper, et lui
        # seul garantit que `_run_step` continue d'être appelé (`lsl_ts` avance à chaque tour de
        # la boucle du moteur, marqueurs ou pas).
        self._verifie_abandon(lsl_ts)

    def _encaisser_flash(self, engine, ts, marqueur):
        cible = marqueur.get("target")
        # `isinstance(cible, bool)` d'abord : en Python `bool` HÉRITE de `int`, donc `True` passe
        # `isinstance(cible, int)` ET `0 <= True < 6`. Un émetteur qui enverrait `true` en JSON
        # (le mot-clé existe, et il est à une faute de frappe de `1`) serait alors décodé comme la
        # cible 1, en silence.
        if isinstance(cible, bool) or not isinstance(cible, int):
            self._refuse_cible(f"« {cible!r} » n'est pas un entier "
                               f"({type(cible).__name__}) — `target` doit être un indice de cible")
            return
        if not 0 <= cible < self.n_targets:
            self._refuse_cible(f"« {cible} » est hors de la plage attendue [0, {self.n_targets}[")
            return
        if self._cibles.count(cible) >= _MAX_PAR_CIBLE:
            # Panne bruyante n°6, variante PAR CIBLE : dans UNE manche, une cible flashe `reps`
            # fois, jamais plus. Au-delà, c'est une manche NEUVE soudée à celle-ci par un
            # `round_end` perdu (cf. le commentaire de `_MAX_PAR_CIBLE`). On abandonne les
            # orphelins ICI, avant `_decider` — un `round_end` arrivé plus tard dans le même lot
            # de marqueurs publierait sinon une cible plausible et fausse — et ce flash-ci ouvre
            # la manche suivante, qui a toutes ses chances d'être décodée juste.
            self._abandonne_manche(f"la cible {cible} a déjà flashé {_MAX_PAR_CIBLE} fois dans "
                                   f"cette manche (plafond par cible = P300_REPS)")
        epoque = epoch_from_stream(engine.recent, engine.recent_ts, ts, engine.acq.fs,
                                   pre_s=self.pre_s, post_s=self.post_s)
        if epoque is None:
            # Le marqueur était mûr mais l'époque déborde quand même : le tampon a été vidé
            # entre-temps. Compté, jamais tu — comme `engine.marqueurs_perdus` juste en dessous.
            self._epoques_perdues += 1
            return
        # ⚠️ Les deux listes s'allongent ENSEMBLE, après la garde ci-dessus : `_decider` les
        # apparie par `zip`, donc un `append` qui passerait devant la garde décalerait les deux
        # pour tout le reste de la manche — chaque flash suivant classé sous la cible du
        # précédent, cible fausse et confiance normale (prouvé par mutation dans `_selftest`).
        self._epoques.append(epoque)
        self._cibles.append(cible)

    def _refuse_cible(self, detail):
        """Panne bruyante n°4 : une cible inutilisable est un bug de l'application cliente.

        Comptée toujours, dite par PALIERS (1, 10, 100…) DANS LA MANCHE : le dire à chaque flash
        noierait le terminal (jusqu'à 48 par manche), et le dire une seule fois par manche laissait
        un émetteur qui numérote mal TOUTES ses cibles — l'erreur la plus banale — n'imprimer
        qu'une ligne pour des minutes de séance. `_refus_cible` est réarmé à chaque manche
        (`_vider_manche`), donc ces paliers repartent de zéro à chaque manche.
        """
        self._refus_cible += 1
        if self._refus_cible in _PALIERS_REFUS:
            print(f"[p300] cible refusée ({self._refus_cible} dans cette manche) : {detail} "
                  f"— vérifie l'émetteur de marqueurs")

    def _verifie_abandon(self, lsl_ts):
        """Abandonne la manche en cours si elle ne se fermera visiblement JAMAIS — panne n°6.

        Deux façons de le détecter, et je veux les deux :
          1. **Délai d'abandon** (ici) : aucun flash REÇU depuis plus de `P300_ROUND_TIMEOUT_S`.
             Ce qui attrape une application externe plantée EN PLEINE manche — le cas normal d'un
             plantage, et le seul des deux qui ne dépend pas du DÉBIT de flashs.
          2. **Plafond par cible** (`_MAX_PAR_CIBLE`, dans `_encaisser_flash`) : une cible qui
             flashe plus que `P300_REPS` fois dans la même manche — l'application tourne toujours
             mais n'envoie plus jamais `round_end`, et sa manche suivante se soude à celle-ci. Ce
             contrôle-là ne peut PAS vivre ici : `_verifie_abandon` tourne après le lot de
             marqueurs du tour, donc après un `round_end` arrivé dans le même lot — trop tard.

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

        ⚠️ La condition d'entrée est « une manche est EN COURS », pas « il y a des époques » : une
        manche dont TOUS les flashs ont été refusés (panne n°4 sur chaque cible) n'a aucune époque
        et serait sinon inabandonnable — donc `_refus_cible` ne serait jamais réarmé, et la garde
        anti-bruit redeviendrait « une fois par SESSION », le défaut exact que `_vider_manche`
        existe pour empêcher.
        """
        if not self._epoques and not self._refus_cible:
            return
        if (self._dernier_flash_ts is None
                or lsl_ts - self._dernier_flash_ts <= P300_ROUND_TIMEOUT_S):
            return
        self._abandonne_manche(f"aucun flash reçu depuis {lsl_ts - self._dernier_flash_ts:.1f} s "
                               f"(> {P300_ROUND_TIMEOUT_S:g} s)")

    def _abandonne_manche(self, raison):
        """Jette la manche en cours en le DISANT et en le comptant. Le seul chemin par lequel des
        époques disparaissent sans avoir été décidées."""
        self._manches_abandonnees += 1
        refuses = f", {self._refus_cible} refusé(s)" if self._refus_cible else ""
        print(f"[p300] manche ABANDONNÉE : {raison} — round_end jamais reçu (application externe "
              f"plantée ?). {len(self._epoques)} flash(s) orphelin(s) jeté(s){refuses}.")
        self._vider_manche()

    def _decider(self, ts):
        """Fin de manche : agréger les scores par cible et publier — ou dire pourquoi non.

        `ts` est l'horodatage du marqueur `round_end` lui-même, pas l'instant où le moteur le
        traite : c'est la date de la DÉCISION de l'utilisateur, et c'est elle qui doit voyager
        avec l'échantillon publié.
        """
        minimum = self.n_targets * P300_MIN_REPS
        if len(self._epoques) < minimum:
            # Panne bruyante n°5 : une manche trop courte ne peut pas départager les cibles.
            # Le plancher est `P300_MIN_REPS` répétitions (la constante que l'arrêt dynamique
            # utilise déjà pour la même raison), pas UNE : à une seule répétition, chaque cible
            # n'a qu'une époque, donc un score de bruit non moyenné — et la décision sortirait
            # avec exactement la même tête qu'une décision sur 48 flashs.
            # On publie quand même, avec -1 ET la raison : un client qui attend un échantillon
            # par manche ne doit pas rester suspendu.
            motif = (f"manche trop courte : {len(self._epoques)} flash(s) valides pour "
                     f"{self.n_targets} cibles × {P300_MIN_REPS} répétition(s) minimum")
            print(f"[p300] manche ignorée : {motif}")
            self._publish(-1, 0.0, len(self._epoques), [0.0] * self.n_targets, ts, motif=motif)
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
            motif = (f"{len(par_cible)} cible(s) ont flashé sur {self.n_targets} — l'émetteur "
                     f"n'a pas fini sa séquence")
            print(f"[p300] manche ignorée : {motif}")
            self._publish(-1, 0.0, len(self._epoques), [0.0] * self.n_targets, ts, motif=motif)
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
            # `select` a refusé : l'écart entre les deux meilleures cibles est sous
            # `P300_SELECT_MARGIN`. C'est le SEUL -1 accompagné de vrais scores (les deux autres
            # publient des zéros faute d'avoir consulté le modèle), et il était jusqu'ici le seul
            # sans motif imprimé — `_log` lui en inventait même un faux (« manche non conclue,
            # 48 flashs valides », alors que 48 flashs, c'est conclusif).
            # ⚠️ NE PAS supprimer cette branche parce que `P300_SELECT_MARGIN` vaut 0 aujourd'hui
            # et la rend inatteignable : remonter la constante ferait alors tomber le `else` sur
            # `moyennes[None]` -> `KeyError` -> moteur à terre.
            motif = (f"scores trop serrés : écart 1er-2e sous la marge "
                     f"{P300_SELECT_MARGIN:g} exigée")
            print(f"[p300] manche non tranchée : {motif}")
            self._publish(-1, 0.0, len(self._epoques), scores, ts, motif=motif)
        else:
            self._publish(int(choisi), float(moyennes[choisi]), len(self._epoques),
                          scores, ts)
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

    def _publish(self, target_index, confidence, n_flashes, scores, lsl_ts, motif=None):
        if self._out is not None:
            self._out.push(target_index, confidence, n_flashes, scores, lsl_ts)
        self._decoded = {
            "target_index": int(target_index),
            "confidence": round(float(confidence), 3),
            "n_flashes": int(n_flashes),
            "scores": [round(float(s), 3) for s in scores],
        }
        self._log(target_index, n_flashes, scores, motif)

    def _log(self, target_index, n_flashes, scores, motif=None):
        """Trace CHAQUE décision, sans limite de fréquence : contrairement au SSVEP/MI (~5 Hz en
        continu), ce flux est RARE — une manche complète prend plusieurs secondes, aucun risque
        de noyer le terminal (cf. docstring de `DecodedP300Publisher`).

        `n_flashes` est sur CHAQUE ligne, décision comprise : c'est le seul chiffre qui distingue
        une sélection sur une manche complète d'une sélection sur le minimum syndical, et il ne
        s'affichait que sur les -1. `motif` est la raison du refus, donnée par l'appelant — jamais
        reconstruite ici, où l'on ne sait pas laquelle des trois s'applique.
        """
        detail = "  ".join(f"cible {i}: {s:+.2f}" for i, s in enumerate(scores))
        verdict = (f"— ({motif or 'manche non conclue'})" if target_index < 0
                   else f"CIBLE {target_index}")
        print(f"[p300] {verdict:<62} {n_flashes:>3} flash(s)  {detail}")


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
                   "flash. Le moteur l'écoute par son NOM, résolu quand un mode qui consomme des "
                   "marqueurs démarre — un seul inlet existe pour tout le moteur, partagé par "
                   "tous ces modes. Le changer pendant que le mode tourne n'a AUCUN effet : "
                   "l'inlet ouvert reste sur l'ancien nom. ARRÊTER puis redémarrer ce mode suffit "
                   "en revanche à reprendre le nouveau — l'inlet est lâché dès que plus aucun "
                   "mode actif ne l'écoute, il n'y a plus besoin de relancer le moteur. Deux "
                   "modes actifs qui en réclameraient des noms différents ne sont pas mélangés en "
                   "silence : un désaccord est signalé bruyamment, un seul nom gagne."),
    ),
    rest=Rest(warmup_s=SSVEP_WARMUP_S, duration_s=0.0,
              instruction="Le casque se stabilise — reste immobile."),
    calibration=Calib(kind="natif",
                      reason="époques calées sur l'onset exact de chaque flash, rendu par "
                             "l'application externe"),
    # Le nom du flux vient du PUBLIEUR, il n'est pas réécrit ici : le contrat public s'écrivait à
    # deux endroits (`SPEC.stream` et le littéral de `DecodedP300Publisher`) sans que rien ne les
    # relie — deux façons de nommer la même chose finissent toujours par diverger.
    stream=DecodedP300Publisher.SUFFIXE,
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
    fait de marqueurs déjà mûrs : épocher, agréger par cible, décider, publier — et sur les quatre
    pannes bruyantes propres au protocole P300 (cible hors plage, manche trop courte, manche qui
    ne se ferme jamais, flashs reçus pendant la chauffe).

    Deux façons de tricher que ce test refuse maintenant : juger une époque sur sa FORME (une
    époque juste au bon endroit peut avoir été filtrée deux fois — on compare donc à la tranche
    brute, valeur pour valeur) et juger un appariement sur des COMPTES (une permutation des
    cibles donne le même dictionnaire de tailles — on plante donc une amplitude unique par flash
    et on la relit par cible).
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

    # L'échantillon où tombe l'onset dans une époque, à la fréquence du board synthétique. Sert
    # aux faux modèles pour relire l'amplitude PLANTÉE au moment du flash, donc pour prouver
    # QUELLE époque est arrivée sous QUELLE cible — pas seulement combien.
    N_PRE = int(round(P300_PRE_S * 250.0))

    # Marge sentinelle : le défaut de `select` dans le VRAI décodeur vaut 0.0, et
    # `P300_SELECT_MARGIN` vaut 0.0 aussi — un faux modèle qui prendrait `margin=0.0` par défaut
    # ne pourrait donc PAS distinguer « le runtime a passé la marge » de « le runtime a oublié
    # l'argument ». Cette valeur-là, elle, ne peut venir que d'un oubli.
    _MARGE_ABSENTE = "marge jamais transmise"

    class _FauxPublieur:
        def __init__(self):
            self.lignes = []

        def push(self, target_index, confidence, n_flashes, scores, lsl_ts=None):
            self.lignes.append((target_index, confidence, n_flashes, list(scores), lsl_ts))

    class _FauxMoteur:
        """Juste ce dont le runtime a besoin. `markers_murs` rend les marqueurs un LOT à la
        fois, dans l'ordre fourni pour CE test : la maturité elle-même (horodatage, curseur,
        purge) est déjà prouvée côté `server.py` (cf. docstring de `_selftest`).

        `appels_murs` compte les appels : c'est l'APPEL qui fait avancer le curseur du moteur,
        donc le seul moyen de prouver que la chauffe consomme les marqueurs au lieu de les
        laisser s'empiler (panne n°7)."""

        def __init__(self, recent, recent_ts):
            self.acq = UnicornAcquisition(synthetic=True)
            self.instance = "selftest"
            self.recent = recent
            self.recent_ts = recent_ts
            self._lots = []
            self.appels_murs = 0

        def markers_murs(self, mode_id, post_s):
            self.appels_murs += 1
            return self._lots.pop(0) if self._lots else []

    class _ModeleControle:
        """Un faux modèle P300 dont `select` renvoie des scores FIXES et CONNUS par cible, pour
        prouver l'appariement score_<i> <-> cible i sans dépendre d'un vrai décodage (déjà
        validé dans `p300_decoder.py`)."""

        def __init__(self, scores_par_cible, gagnant):
            self._scores = dict(scores_par_cible)
            self._gagnant = gagnant
            self.appels = 0
            self.marge_recue = _MARGE_ABSENTE

        def select(self, epochs_by_target, margin=_MARGE_ABSENTE):
            self.appels += 1
            self.marge_recue = margin
            return self._gagnant, dict(self._scores)

    class _ModeleEspion:
        """Compte ses appels — sert à prouver qu'une manche incomplète ne consulte JAMAIS le
        modèle plutôt que de lui demander un argmax sur un sous-ensemble de cibles."""

        def __init__(self):
            self.appels = 0

        def select(self, epochs_by_target, margin=0.0):
            self.appels += 1
            return 0, {k: 99.0 for k in epochs_by_target}   # une réponse CERTAINE si jamais appelée

    class _ModeleIndecis:
        """Rend `(None, scores)` : c'est ce que le VRAI `select` fait quand l'écart 1er-2e passe
        sous la marge. `P300_SELECT_MARGIN` valant 0, cette branche est inatteignable avec le vrai
        décodeur — elle n'en est pas moins la seule à publier -1 AVEC de vrais scores, et la seule
        que remonter la constante rendrait vivante. Sans ce modèle, la mutation
        `if choisi is None: self._publish(0, ...)` — littéralement la confusion « -1 = la cible
        0 » — passait tous les tests."""

        def __init__(self, scores_par_cible):
            self._scores = dict(scores_par_cible)

        def select(self, epochs_by_target, margin=0.0):
            return None, dict(self._scores)

    class _ModeleCapture:
        """Capture, cible par cible, l'AMPLITUDE plantée à l'onset de chaque époque reçue — pas
        seulement leur nombre.

        ⚠️ Compter ne suffisait pas : une PERMUTATION pure des cibles
        (`_cibles.append((cible + 1) % n)`) donne `{1:1, 2:1, …, 0:1}`, dict ÉGAL à
        `{i: 1 for i in range(6)}` — l'égalité de dictionnaires ignore l'ordre. L'appariement
        époque <-> cible n'était donc prouvé qu'en SORTIE (`_ModeleControle`), jamais en ENTRÉE.
        En relisant `v[0][N_PRE, 0]`, une permutation change la valeur lue et se voit.
        """

        def __init__(self):
            self.recu = None
            self.marge_recue = _MARGE_ABSENTE

        def select(self, epochs_by_target, margin=_MARGE_ABSENTE):
            self.marge_recue = margin
            self.recu = {k: [float(np.asarray(e)[N_PRE, 0]) for e in v]
                         for k, v in epochs_by_target.items()}
            return 0, {k: 0.0 for k in epochs_by_target}

    def marqueur(t, cible):
        return (t, {"mode": "p300", "event": "flash", "target": cible})

    def fin_manche(t):
        return (t, {"mode": "p300", "event": "round_end"})

    def manche(t, reps=P300_MIN_REPS, cibles=None, soa=0.15):
        """Le lot de marqueurs d'une manche : `reps` répétitions de chaque cible, à `soa`
        d'intervalle. Rend `(lot, instant du prochain marqueur)` — SANS `round_end`, que chaque
        scénario ajoute (ou pas : son absence est la panne n°6)."""
        lot = []
        for _ in range(reps):
            for tgt in (range(P300_N_TARGETS) if cibles is None else cibles):
                lot.append(marqueur(t, tgt))
                t += soa
        return lot, t

    rng = np.random.default_rng(0)
    fs = 250.0
    # 20 s de tampon continu, largement assez de marge pour des flashs entre t=101 et t=118 avec
    # pre_s=0,15 / post_s=0,80. Du BRUIT, pas des zéros : une covariance nulle sur toutes les
    # époques rendrait la moyenne riemannienne de xDAWN dégénérée.
    recent_ts = np.arange(100.0, 120.0, 1.0 / fs)
    recent = rng.normal(0.0, 5.0, (len(recent_ts), 8))

    def moteur_marque(lot):
        """Un faux moteur dont le tampon porte, à l'onset de CHAQUE flash du lot, une amplitude
        unique et croissante. Rend `(moteur, {instant: amplitude})`.

        C'est ce qui permet de reconnaître une époque à son contenu : sans marque, deux époques de
        bruit sont interchangeables et rien ne distingue « la bonne époque sous la bonne cible »
        de « une époque quelconque sous la bonne cible ».
        """
        eeg = recent.copy()
        amplitudes = {}
        for k, (t, d) in enumerate(m for m in lot if m[1].get("event") == "flash"):
            amplitudes[t] = 500.0 + k
            eeg[int(np.searchsorted(recent_ts, t)), :] = amplitudes[t]
        return _FauxMoteur(eeg, recent_ts), amplitudes

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

        # 3bis. Le contrôle SYMÉTRIQUE du précédent, et celui qui manquait : `registry.check()`
        # compare le CONTRAT au runtime ; personne ne comparait le runtime au MODÈLE. Un modèle
        # entraîné à une autre fréquence (ou avec d'autres bornes pré/post) découpe une autre
        # géométrie d'époque et rend des log-odds plausibles et faux.
        # Nom volontairement HORS du motif `p300_model*.joblib` : ce modèle est bon à jeter, il
        # n'a rien à faire dans une liste de modèles proposés.
        autre_geo = _os.path.join(dossier, "geometrie_etrangere.joblib")
        P300Model(fs=125.0).save(autre_geo)
        essai = dict(values)
        essai["model"] = autre_geo
        try:
            P300Runtime(SPEC, essai, moteur)
            refus_geo = None
        except ValueError as e:
            refus_geo = str(e)
        chk(refus_geo is not None and "fs" in refus_geo and "125" in refus_geo,
            f"un modèle entraîné sur une AUTRE géométrie d'époque est refusé au démarrage, en "
            f"nommant l'écart ({refus_geo})")

        rt = P300Runtime(SPEC, values, moteur)
        rt._out = _FauxPublieur()
        rt._opened = True
        chk(rt.phase == "warmup", "le P300 commence par une chauffe")

        # 4. La CHAUFFE consomme les marqueurs au lieu de les laisser s'empiler (panne n°7).
        # C'est l'appel à `markers_murs` qui fait avancer le curseur du moteur : sans lui, les
        # 15 s de chauffe s'accumulent et le premier `_run_step` les avale d'un coup — la moitié
        # ayant déjà quitté le tampon EEG, `round_end` compris. C'est le comportement PAR DÉFAUT
        # de la première manche de chaque séance, pas un cas tordu.
        rt.begin_rest(now=0.0, warmup_s=15.0, duration_s=0.0)
        lot_chauffe, t_fin_chauffe = manche(101.0, reps=1)
        lot_chauffe.append(fin_manche(t_fin_chauffe))
        moteur._lots = [lot_chauffe]
        appels_avant = moteur.appels_murs
        capture_chauffe = io.StringIO()
        with redirect_stdout(capture_chauffe):
            rt.tick(moteur, lsl_ts=t_fin_chauffe, now=1.0)     # encore en pleine chauffe
        texte_chauffe = capture_chauffe.getvalue()
        print(texte_chauffe, end="")
        chk(rt.phase == "warmup", f"à 1 s sur 15, on est toujours en chauffe ({rt.phase})")
        chk(moteur.appels_murs == appels_avant + 1,
            f"la chauffe CONSOMME quand même la file de marqueurs : le curseur du moteur avance "
            f"({moteur.appels_murs - appels_avant} appel(s) à markers_murs)")
        chk(rt._marqueurs_chauffe == len(lot_chauffe),
            f"...les marqueurs jetés sont COMPTÉS, pas perdus en silence "
            f"({rt._marqueurs_chauffe} sur {len(lot_chauffe)})")
        chk("CHAUFFE" in texte_chauffe,
            f"...et l'étudiant l'apprend, une fois ({texte_chauffe.strip()!r})")
        chk(rt._epoques == [] and rt._out.lignes == [],
            f"...sans qu'une seule époque de chauffe rejoigne une manche, ni qu'une décision soit "
            f"publiée ({len(rt._epoques)} époque(s), {len(rt._out.lignes)} décision(s))")

        # Chauffe puis écoute, sans plancher à mesurer.
        rt.begin_rest(now=0.0, warmup_s=0.0, duration_s=0.0)
        rt.tick(moteur, lsl_ts=0.0, now=0.1)
        rt.tick(moteur, lsl_ts=0.2, now=0.2)
        chk(rt.phase == "running", f"un repos de durée nulle passe tout de suite ({rt.phase})")
        chk(rt.rest_report and rt.rest_report["kind"] == "p300",
            f"et laisse un compte-rendu nommant le modèle ({rt.rest_report})")
        chk(rt._marqueurs_chauffe == len(lot_chauffe),
            f"le compteur de chauffe est un compteur de SESSION : il ne s'efface pas au passage "
            f"en décodage ({rt._marqueurs_chauffe})")

        # 5. Une manche COMPLÈTE, sur le VRAI décodeur : on ne juge PAS la justesse du décodage
        # (déjà validée dans `p300_decoder.py` sur du vrai P300 synthétique) — ici le signal est
        # du BRUIT — seulement le CONTRAT : un index dans les bornes, un score par cible,
        # `n_flashes` qui compte les flashs incorporés, et l'horodatage du `round_end`.
        lot, t = manche(101.0)
        t_round_end = t
        lot.append(fin_manche(t_round_end))
        moteur._lots = [lot]
        rt.tick(moteur, lsl_ts=t + 5.0, now=1.0)    # `lsl_ts` VOLONTAIREMENT loin du round_end
        chk(len(rt._out.lignes) == 1,
            f"une décision publiée pour cette manche complète ({len(rt._out.lignes)})")
        index, _confiance, n_flashes, scores, ts_publie = rt._out.lignes[-1]
        # La manche est complète et `P300_SELECT_MARGIN` vaut 0 : `select` rend TOUJOURS un
        # argmax ici. `-1 <= index` était donc vrai quoi qu'il arrive — le seul test qui fait
        # tourner le vrai décodeur ne pouvait pas échouer.
        chk(0 <= index < P300_N_TARGETS, f"index de cible dans les bornes ({index})")
        chk(len(scores) == P300_N_TARGETS, f"un score par cible ({scores})")
        chk(n_flashes == P300_N_TARGETS * P300_MIN_REPS,
            f"n_flashes compte les flashs valides incorporés à la décision ({n_flashes})")
        chk(rt.output() is not None and rt.output()["target_index"] == index,
            f"la sortie exposée à l'affichage reprend la même décision ({rt.output()})")
        chk(ts_publie == t_round_end,
            f"la décision est horodatée à l'instant du round_end, PAS au tour de boucle qui l'a "
            f"traité ({ts_publie} attendu {t_round_end}, lsl_ts valait {t + 5.0})")
        chk(len(rt._epoques) == len(rt._cibles) == 0,
            f"et la manche décidée est vidée des DEUX côtés ({len(rt._epoques)} époques, "
            f"{len(rt._cibles)} cibles)")

        # --- PREUVE 1/2 : l'appariement score_<i> <-> cible i --------------------------------
        # Un modèle-CONTRÔLE dont `select` renvoie des scores FIXES, ASYMÉTRIQUES et tous
        # DISTINCTS : une inversion, un tri, ou un décalage d'index produirait une liste
        # DIFFÉRENTE de celle attendue — rien ici ne pourrait passer par coïncidence.
        # ⚠️ Le gagnant annoncé est la cible 3, dont le score (0,5) n'est NI le maximum NI le
        # minimum : avec `gagnant=1` (qui était aussi l'argmax des scores), deux mutations
        # passaient — un runtime qui recalculerait son propre argmax au lieu de croire `select`,
        # et `confidence = max(moyennes.values())` au lieu du score DU gagnant.
        scores_connus = {0: -3.0, 1: 7.0, 2: -1.5, 3: 0.5, 4: -2.5, 5: 4.0}
        controle = _ModeleControle(scores_connus, gagnant=3)
        rt.model = controle
        lot, t = manche(101.0)
        lot.append(fin_manche(t))
        moteur._lots = [lot]
        rt.tick(moteur, lsl_ts=t, now=2.0)
        index, confiance, _n, scores, _ts = rt._out.lignes[-1]
        attendu = [scores_connus[i] for i in range(P300_N_TARGETS)]
        chk(scores == attendu,
            f"score_<i> correspond EXACTEMENT à la cible i, dans l'ordre des indices "
            f"({scores} attendu {attendu})")
        chk(index == 3 and abs(confiance - 0.5) < 1e-9,
            f"et la cible publiée est celle que le MODÈLE a choisie, avec SON score comme "
            f"confiance — pas l'argmax ni le max des scores ({index}, {confiance})")
        chk(controle.marge_recue == P300_SELECT_MARGIN,
            f"la marge de protocole est bien TRANSMISE à `select` — un appel qui l'omettrait "
            f"prendrait le défaut de la signature ({controle.marge_recue!r})")

        # --- PREUVE 2/2 : une manche INCOMPLÈTE publie -1, sans même consulter le modèle -------
        # Cas A : moins de flashs valides que le plancher (`n_targets × P300_MIN_REPS`).
        espion = _ModeleEspion()
        rt.model = espion
        t = 101.0
        lot = [marqueur(t, 0), marqueur(t + 0.15, 1), marqueur(t + 0.30, 2)]
        lot.append(fin_manche(t + 0.45))
        moteur._lots = [lot]
        rt.tick(moteur, lsl_ts=t + 0.45, now=3.0)
        index, _c, n_flashes, scores, _ts = rt._out.lignes[-1]
        chk(index == -1 and n_flashes == 3,
            f"3 flashs pour {P300_N_TARGETS} cibles : la manche est refusée, PAS un argmax sur "
            f"les 3 cibles vues (index={index}, n_flashes={n_flashes})")
        chk(scores == [0.0] * P300_N_TARGETS,
            f"et les scores publiés sont neutres, pas ceux d'un calcul partiel ({scores})")
        chk(espion.appels == 0,
            f"le modèle n'est même pas CONSULTÉ — {espion.appels} appel(s) au lieu de 0")

        # Cas A' : le plancher vaut `P300_MIN_REPS` répétitions, pas UNE. Une manche d'une seule
        # répétition (6 flashs, toutes les cibles couvertes) donne un score de bruit NON MOYENNÉ
        # par cible — et sortait jusqu'ici avec exactement la même tête qu'une décision sur 48
        # flashs, `_log` n'imprimant `n_flashes` que sur les -1.
        lot, t = manche(101.0, reps=1)
        lot.append(fin_manche(t))
        moteur._lots = [lot]
        capture_court = io.StringIO()
        with redirect_stdout(capture_court):
            rt.tick(moteur, lsl_ts=t, now=3.5)
        texte_court = capture_court.getvalue()
        print(texte_court, end="")
        index, _c, n_flashes, _s, _ts = rt._out.lignes[-1]
        chk(index == -1 and n_flashes == P300_N_TARGETS,
            f"une manche d'UNE répétition (toutes les cibles vues) est refusée : le plancher est "
            f"{P300_MIN_REPS} répétitions (index={index}, n_flashes={n_flashes})")
        chk(espion.appels == 0,
            f"et le modèle n'est toujours pas consulté ({espion.appels} appel(s))")
        chk(f"{P300_N_TARGETS} flash(s)" in texte_court and "trop courte" in texte_court,
            f"le journal dit le MOTIF et le nombre de flashs, sur la même ligne "
            f"({texte_court.strip()!r})")

        # Cas B : autant (ou plus) de flashs que le plancher, mais pas TOUTES les cibles vues —
        # celui que la preuve rouge-puis-vert cible : la brèche ne se voit ni sur le nombre de
        # flashs ni sur les bornes de l'index, seulement sur la COUVERTURE des cibles.
        lot, t = manche(101.0, reps=P300_N_TARGETS, cibles=(0, 1))   # 12 flashs, 2 cibles
        lot.append(fin_manche(t))
        moteur._lots = [lot]
        rt.tick(moteur, lsl_ts=t, now=4.0)
        index, _c, n_flashes, scores, _ts = rt._out.lignes[-1]
        chk(index == -1 and n_flashes == 2 * P300_N_TARGETS,
            f"{2 * P300_N_TARGETS} flashs mais 2 cibles seulement sur {P300_N_TARGETS} : "
            f"refusée quand même, pas un argmax sur les 2 cibles vues (index={index}, "
            f"n_flashes={n_flashes})")
        chk(scores == [0.0] * P300_N_TARGETS, f"scores neutres, pas partiels ({scores})")
        chk(espion.appels == 0,
            f"le modèle n'est TOUJOURS pas consulté — {espion.appels} appel(s) au lieu de 0")

        # --- La branche `choisi is None` : le SEUL -1 accompagné de VRAIS scores ---------------
        # `P300_SELECT_MARGIN` vaut 0, donc le vrai `select` ne rend jamais None aujourd'hui et
        # aucun test ne passait par là. La mutation `if choisi is None: self._publish(0, …)` est
        # littéralement la confusion « -1 = la cible 0 » autour de laquelle toute la docstring de
        # ce module est construite ; remonter la constante suffirait à la rendre vivante.
        rt.model = _ModeleIndecis(scores_connus)
        lot, t = manche(101.0)
        lot.append(fin_manche(t))
        moteur._lots = [lot]
        capture_indecis = io.StringIO()
        with redirect_stdout(capture_indecis):
            rt.tick(moteur, lsl_ts=t, now=4.5)
        texte_indecis = capture_indecis.getvalue()
        print(texte_indecis, end="")
        index, confiance, n_flashes, scores, _ts = rt._out.lignes[-1]
        chk(index == -1,
            f"un modèle qui refuse de trancher publie -1 — « pas de décision », JAMAIS la cible 0 "
            f"(index={index})")
        chk(scores == attendu and confiance == 0.0,
            f"...avec les VRAIS scores calculés (c'est le seul -1 qui en a), et une confiance "
            f"neutre ({scores}, {confiance})")
        chk("marge" in texte_indecis and f"{P300_N_TARGETS * P300_MIN_REPS} flash(s)" in
            texte_indecis,
            f"...et le journal dit POURQUOI, au lieu d'inventer « manche non conclue » sur une "
            f"manche complète ({texte_indecis.strip()!r})")

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
        # exactement ce qu'un plantage produit. Le tampon porte une amplitude UNIQUE à l'onset de
        # chaque flash : on saura donc dire QUELLE époque est arrivée sous QUELLE cible, et pas
        # seulement combien il y en avait.
        t0 = 101.0
        lot_avortee = [marqueur(t0, 0), marqueur(t0 + 0.15, 1), marqueur(t0 + 0.30, 2)]
        lot_neuve, t1 = manche(115.0)
        moteur_c, amplitudes = moteur_marque(lot_avortee + lot_neuve)
        moteur_c._lots = [lot_avortee]
        rt.tick(moteur_c, lsl_ts=t0 + 0.30, now=10.0)
        chk(len(rt._epoques) == 3,
            f"les 3 flashs de la manche avortée sont bien en attente, round_end jamais arrivé "
            f"({len(rt._epoques)})")

        # Le temps passe, largement au-delà du délai d'abandon — SANS AUCUN NOUVEAU MARQUEUR :
        # c'est le simple passage du temps qui doit déclencher l'abandon (`lsl_ts` avance à
        # chaque tour de la boucle du moteur, marqueurs ou pas), pas un événement particulier.
        avant_abandons = rt._manches_abandonnees
        moteur_c._lots = []
        lsl_apres_delai = t0 + 0.30 + P300_ROUND_TIMEOUT_S + 1.0
        rt.tick(moteur_c, lsl_ts=lsl_apres_delai, now=25.0)
        chk(len(rt._epoques) == 0,
            f"la manche avortée est jetée après le délai, sans aucun nouveau marqueur "
            f"({len(rt._epoques)} époque(s) restante(s))")
        chk(rt._manches_abandonnees == avant_abandons + 1,
            f"l'abandon est COMPTÉ ({rt._manches_abandonnees - avant_abandons})")

        # Manche NEUVE et complète. Si les 3 orphelins avaient survécu, les cibles 0/1/2
        # porteraient CHACUNE une époque de plus — et surtout une époque dont l'amplitude
        # trahirait son origine.
        moteur_c._lots = [lot_neuve + [fin_manche(t1)]]
        rt.tick(moteur_c, lsl_ts=t1, now=26.0)
        attendu_recu = {}
        for t_flash, d in lot_neuve:
            attendu_recu.setdefault(d["target"], []).append(amplitudes[t_flash])
        chk(capture_modele.recu == attendu_recu,
            f"la manche neuve n'hérite d'AUCUN flash orphelin de l'avortée, et chaque époque est "
            f"rangée sous LA cible qui l'a produite — vérifié sur le contenu, pas sur le compte "
            f"({capture_modele.recu} attendu {attendu_recu})")
        chk(capture_modele.marge_recue == P300_SELECT_MARGIN,
            f"la marge de protocole est transmise ici aussi ({capture_modele.marge_recue!r})")

        # --- Panne bruyante n°6, LE cas crédible : DEUX MANCHES SOUDÉES ----------------------
        # Un seul `round_end` manquant colle deux manches complètes. Avec un plafond GLOBAL de
        # 96 époques (= exactement deux manches) et une comparaison stricte, les deux garde-fous
        # se taisaient : `select` recevait 96 époques dont la moitié portaient l'intention de la
        # manche PRÉCÉDENTE, et le moteur publiait une cible plausible avec une confiance normale.
        # Le plafond PAR CIBLE, lui, tombe sur le premier flash de trop — donc AVANT le
        # `round_end` du même lot, qui publierait sinon la décision fausse.
        lot_a, t_mid = manche(101.0, reps=P300_REPS)      # manche A, complète, SANS round_end
        lot_b, t_fin = manche(t_mid, reps=P300_REPS)      # manche B, soudée à la précédente
        moteur_s, amp_s = moteur_marque(lot_a + lot_b)
        moteur_s._lots = [lot_a + lot_b + [fin_manche(t_fin)]]
        capture_soude = _ModeleCapture()
        rt.model = capture_soude
        avant_abandons = rt._manches_abandonnees
        avant_lignes = len(rt._out.lignes)
        rt.tick(moteur_s, lsl_ts=t_fin, now=27.0)
        chk(rt._manches_abandonnees == avant_abandons + 1,
            f"le plafond par cible ({_MAX_PAR_CIBLE}) abandonne la manche A, sans attendre le "
            f"délai ({rt._manches_abandonnees - avant_abandons} abandon(s))")
        chk(len(rt._out.lignes) == avant_lignes + 1,
            f"une SEULE décision sort de ces deux manches soudées ({len(rt._out.lignes) - avant_lignes})")
        _i, _c, n_flashes, _s, _ts = rt._out.lignes[-1]
        chk(n_flashes == P300_N_TARGETS * P300_REPS,
            f"et elle porte sur UNE manche ({P300_N_TARGETS * P300_REPS} flashs), pas sur les "
            f"deux soudées ({n_flashes})")
        chk(sorted(capture_soude.recu) == list(range(P300_N_TARGETS))
            and all(len(v) == P300_REPS for v in capture_soude.recu.values()),
            f"le modèle reçoit {P300_REPS} époques par cible, pas {2 * P300_REPS} "
            f"({ {k: len(v) for k, v in capture_soude.recu.items()} })")
        frontiere = max(amp_s[t] for t, d in lot_a)
        chk(min(min(v) for v in capture_soude.recu.values()) > frontiere,
            f"...et ce sont TOUTES des époques de la manche B : aucune amplitude de la manche A "
            f"(<= {frontiere:g}) n'a survécu ({capture_soude.recu[0]})")
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
        # `state()` est lu ICI, pendant que le compteur vaut 1 : plus bas, deux remises à zéro
        # l'ont précédé et l'assertion `state()["refus_cible"] == rt._refus_cible` valait `0 == 0`
        # — un `state()` qui écrirait `0` en dur passait.
        etat_b = rt.state()
        chk(etat_b["refus_cible"] == 1,
            f"...et `state()` le montre PENDANT qu'il vaut 1, pas seulement une fois retombé à 0 "
            f"({etat_b['refus_cible']})")

        moteur._lots = [[fin_manche(t + 0.15)]]
        rt.tick(moteur, lsl_ts=t + 0.15, now=6.5)   # referme B proprement avant la suite du test

        # Manche B' : un booléen est un `int` en Python, donc `True` passait
        # `isinstance(cible, int)` ET `0 <= True < 6` — un `target: true` en JSON (le mot-clé
        # existe, et il est à une faute de frappe de `1`) était décodé comme la cible 1, en
        # silence. Manche à part : le message ne se réimprime qu'au premier refus de CHAQUE
        # manche (paliers), et la manche B en a déjà eu un.
        capture_bool = io.StringIO()
        with redirect_stdout(capture_bool):
            moteur._lots = [[marqueur(t + 0.30, True)]]
            rt.tick(moteur, lsl_ts=t + 0.30, now=6.6)
        texte_bool = capture_bool.getvalue()
        print(texte_bool, end="")
        chk(rt._refus_cible == 1 and not rt._epoques,
            f"un booléen n'est PAS une cible, même si `bool` hérite de `int` "
            f"({rt._refus_cible} refus, {len(rt._epoques)} époque(s))")
        chk("entier" in texte_bool,
            f"...et le message nomme le vrai problème (le TYPE), pas « hors de la plage » "
            f"({texte_bool.strip()!r})")
        moteur._lots = [[fin_manche(t + 0.45)]]
        rt.tick(moteur, lsl_ts=t + 0.45, now=6.7)   # referme B' à son tour

        # Manche C : TOUS ses flashs refusés, donc AUCUNE époque. `_verifie_abandon` rendait la
        # main sur `if not self._epoques` : une telle manche ne se fermait JAMAIS (seul un
        # `round_end` la ferme, et l'émetteur fautif n'en envoie pas forcément), donc
        # `_refus_cible` gardait sa valeur pour le reste de la SESSION et la garde anti-bruit
        # redevenait « une fois par session ». ⚠️ Et `_dernier_flash_ts` n'avançant que sur les
        # flashs ACCEPTÉS, un émetteur bien vivant mais fautif était indiscernable d'un mort.
        t = 111.0
        moteur._lots = [[marqueur(t, 42), marqueur(t + 0.15, 43)]]
        with redirect_stdout(io.StringIO()):
            rt.tick(moteur, lsl_ts=t + 0.15, now=7.0)
        chk(rt._refus_cible == 2 and not rt._epoques,
            f"manche C : deux cibles refusées, aucune époque ({rt._refus_cible} refus, "
            f"{len(rt._epoques)} époque(s))")
        chk(rt._dernier_flash_ts == t + 0.15,
            f"l'horodatage de vie de la manche avance sur un flash REFUSÉ aussi ({rt._dernier_flash_ts})")
        avant_abandons = rt._manches_abandonnees
        moteur._lots = []
        capture_c = io.StringIO()
        with redirect_stdout(capture_c):
            rt.tick(moteur, lsl_ts=t + 0.15 + P300_ROUND_TIMEOUT_S + 1.0, now=8.0)
        texte_c = capture_c.getvalue()
        print(texte_c, end="")
        chk(rt._manches_abandonnees == avant_abandons + 1 and rt._refus_cible == 0,
            f"une manche 100 % refusée est ABANDONNÉE au délai, ce qui RÉARME le compteur "
            f"({rt._manches_abandonnees - avant_abandons} abandon, refus={rt._refus_cible})")
        chk("refusé" in texte_c,
            f"...et l'abandon dit combien de flashs avaient été refusés ({texte_c.strip()!r})")

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
        # ⚠️ L'assertion que 478 lignes de test n'avaient pas : `_cibles` n'était lu NULLE PART.
        # Remonter `self._cibles.append(cible)` au-dessus de la garde `if epoque is None` — une
        # édition d'UNE ligne — décale les deux listes pour tout le reste de la manche, et
        # `_decider` (qui les apparie par `zip`) classe alors chaque flash suivant sous la cible du
        # PRÉCÉDENT : cible fausse, confiance normale, déclenché par un événement qui a son propre
        # compteur donc connu pour arriver.
        chk(len(rt._cibles) == 0,
            f"...et sa CIBLE non plus : les deux listes ne s'allongent QUE ensemble "
            f"({len(rt._cibles)} cible(s) pour {len(rt._epoques)} époque(s))")
        rt._vider_manche()

        # Les compteurs de pannes ont une sortie AUTRE que le terminal : `state()`, lu par la
        # console (ou n'importe quel autre client du moteur qui n'a pas les yeux sur les logs).
        etat = rt.state()
        chk({"refus_cible", "epoques_perdues", "manches_abandonnees", "marqueurs_chauffe"}
            <= set(etat),
            f"les quatre compteurs de pertes sont exposés dans state() ({sorted(etat)})")
        chk(etat["refus_cible"] == rt._refus_cible
            and etat["epoques_perdues"] == rt._epoques_perdues
            and etat["manches_abandonnees"] == rt._manches_abandonnees,
            f"...et reflètent les compteurs RÉELS du runtime, pas une copie figée "
            f"(state={etat['refus_cible'], etat['epoques_perdues'], etat['manches_abandonnees']}, "
            f"réel={rt._refus_cible, rt._epoques_perdues, rt._manches_abandonnees})")
        chk(etat["marqueurs_chauffe"] == rt._marqueurs_chauffe > 0,
            f"...y compris ce qui a été jeté pendant la chauffe, qui n'a AUCUN autre filet que "
            f"le terminal ({etat['marqueurs_chauffe']})")

        # 6. Le contrat du mode.
        chk(SPEC.rest.duration_s == 0.0 and SPEC.rest.warmup_s == SSVEP_WARMUP_S,
            f"chauffe obligatoire, aucun plancher ({SPEC.rest})")
        chk(SPEC.stream == "decoded_p300" and SPEC.status == "moteur",
            "le mode publie decoded_p300 et tourne dans le moteur")
        chk(SPEC.stream == DecodedP300Publisher.SUFFIXE,
            f"...et ce nom vient du PUBLIEUR, pas d'un second littéral qui pourrait en diverger "
            f"({SPEC.stream} / {DecodedP300Publisher.SUFFIXE})")
        chk(SPEC.calibration is not None and SPEC.calibration.kind == "natif"
            and SPEC.calibration.runtime_cls is None,
            "sa calibration reste NATIVE : le moteur ne la joue pas, l'appli pygame la joue")
        chk(all(p.affecte_decodage for p in SPEC.params if p.key != "stream_in"),
            "le modèle affecte le décodage ; le flux de marqueurs (juste le NOM écouté), non")
        chk(P300_ROUND_TIMEOUT_S > 0.0,
            f"un délai d'abandon strictement positif est déclaré ({P300_ROUND_TIMEOUT_S:g} s)")
        chk(_MAX_PAR_CIBLE >= P300_REPS,
            f"le plafond par cible ne peut PAS se déclencher sur une manche normale : une cible "
            f"y flashe {P300_REPS} fois, le plafond en tolère {_MAX_PAR_CIBLE}")

        # --- LE test d'alignement ------------------------------------------------
        # On fabrique un tampon plat, on y plante un pic d'amplitude unique à un instant CONNU, et
        # on envoie un marqueur à cet instant. L'époque extraite doit contenir ce pic exactement à
        # l'échantillon `n_pre` — c'est-à-dire à l'onset. Un décalage de 3 échantillons (12 ms) ne
        # change RIEN d'autre : l'époque a la bonne taille, le décodeur tourne, les scores sortent.
        fs = 250.0
        n_pre = int(round(P300_PRE_S * fs))       # 38 (0,15 s × 250 Hz, arrondi)
        n_post = int(round(P300_EPOCH_S * fs))    # 200
        t0 = 1000.0
        ts = np.arange(t0, t0 + 4.0, 1.0 / fs)
        eeg = np.zeros((len(ts), 8))
        instant_du_pic = t0 + 2.0
        i_pic = int(np.searchsorted(ts, instant_du_pic))
        eeg[i_pic, :] = np.arange(1, 9) * 10.0    # une valeur DISTINCTE par voie (10, 20, ..., 80) —
        # PAS un scalaire répété : une valeur unique sur les 8 voies laisserait passer un échange de
        # deux voies (`np.array_equal` resterait vrai), cf. le commentaire plus bas (correction de
        # revue, tâche 5 ErrP, tour 1 — même fixture trop généreuse trouvée ici et dans errp.py)

        epoque = epoch_from_stream(eeg, ts, instant_du_pic, fs,
                                  pre_s=P300_PRE_S, post_s=P300_EPOCH_S)
        chk(epoque is not None, "l'époque est extraite")
        chk(epoque.shape == (n_pre + n_post, 8),
            f"elle a exactement pré+post échantillons ({epoque.shape})")
        position = int(np.argmax(epoque[:, 0]))
        chk(position == n_pre,
            f"⚠️ ALIGNEMENT : le pic planté à l'onset se retrouve à l'échantillon {position}, "
            f"il devait être à {n_pre} (décalage de {position - n_pre} échantillons = "
            f"{(position - n_pre) / fs * 1000:+.0f} ms)")
        chk(abs(epoque[n_pre, 0] - 10.0) < 1e-9,   # voie 0 = 1 * 10.0, cf. la fixture par voie ci-dessus
            f"et c'est bien LA valeur plantée qu'on retrouve ({epoque[n_pre, 0]})")

        # Le même test, décalé d'une demi-période d'échantillonnage : un marqueur ne tombe jamais
        # pile sur un échantillon dans la vraie vie. On accepte 1 échantillon d'écart, pas plus.
        epoque = epoch_from_stream(eeg, ts, instant_du_pic + 0.002, fs,
                                  pre_s=P300_PRE_S, post_s=P300_EPOCH_S)
        chk(epoque is not None,
            "l'époque décalée d'une demi-période est extraite elle aussi")
        position = int(np.argmax(epoque[:, 0])) if epoque is not None else -1
        chk(abs(position - n_pre) <= 1,
            f"un marqueur entre deux échantillons reste aligné à ±1 ({position} vs {n_pre})")

        # --- LE MÊME test, mais par le VRAI chemin d'appel (_encaisser_flash, pas un appel direct
        # à epoch_from_stream) --------------------------------------------------------------------
        # Le test ci-dessus prouve que `epoch_from_stream` positionne juste QUAND on lui donne les
        # bons pre_s/post_s — il ne prouve PAS que `_encaisser_flash` les lui TRANSMET dans le bon
        # ordre. Piège concret, pas théorique : P300_PRE_S (0,15 s -> 38 éch.) et P300_EPOCH_S
        # (0,80 s -> 200 éch.) ont des tailles différentes, mais 38+200 == 200+38 == 238 — une
        # INVERSION `pre_s=self.post_s, post_s=self.pre_s` à l'appel réel produirait une époque de
        # la MÊME FORME (238, 8), invisible à tout contrôle de taille ou de bornes. Seule la
        # POSITION du signal DANS l'époque que le runtime a RÉELLEMENT construite peut l'attraper —
        # d'où ce second test, qui repasse par `rt.tick()` (donc par `_encaisser_flash`) au lieu
        # d'appeler le décodeur en direct comme ci-dessus.
        rt._vider_manche()
        moteur_aligne = _FauxMoteur(eeg, ts)
        moteur_aligne._lots = [[marqueur(instant_du_pic, 0)]]
        rt.tick(moteur_aligne, lsl_ts=instant_du_pic, now=999.0)
        chk(len(rt._epoques) == 1,
            f"le flash a produit UNE époque en passant par _encaisser_flash, le vrai chemin "
            f"d'appel du runtime ({len(rt._epoques)})")
        position_reelle = int(np.argmax(rt._epoques[-1][:, 0])) if rt._epoques else -1
        chk(position_reelle == n_pre,
            f"⚠️ ALIGNEMENT (chemin réel _encaisser_flash) : le pic se retrouve à l'échantillon "
            f"{position_reelle}, il devait être à {n_pre} (décalage de "
            f"{position_reelle - n_pre} échantillons = "
            f"{(position_reelle - n_pre) / fs * 1000:+.0f} ms) — pre_s/post_s mal transmis par "
            f"le runtime")
        # ⚠️ LA seule assertion qui ferme le trou du DOUBLE FILTRAGE — et elle en remplace trois.
        # La position du pic ne suffit PAS : `filtfilt` est à phase nulle, donc ajouter un
        # `bandpass()` dans `_encaisser_flash` laisse le maximum exactement au même échantillon
        # (vérifié par mutation). Or `P300Model._prep` filtre DÉJÀ — le double filtrage passait
        # donc cet autotest sans un mot, la panne exacte contre laquelle ce projet a écrit un
        # garde dédié pour le Motor Imagery (« bruit à p=0,99 »). Une correction de ligne de base
        # ou une conversion d'unité passaient de même. Comparer à la TRANCHE BRUTE attendue
        # épingle d'un coup la position, la forme, ET l'absence de tout traitement — et, la fixture
        # plantant une valeur DISTINCTE par voie (pas un scalaire répété, cf. plus haut, trouvé en
        # revue tâche 5 ErrP tour 1), l'ORDRE des voies aussi : ce que le runtime empile doit être
        # l'EEG, tel quel.
        attendue = eeg[i_pic - n_pre:i_pic + n_post]
        chk(rt._epoques and rt._epoques[-1].shape == (n_pre + n_post, 8),
            f"l'époque construite par le runtime a exactement la FORME attendue "
            f"({rt._epoques[-1].shape if rt._epoques else None} attendu {(n_pre + n_post, 8)})")
        chk(bool(rt._epoques) and np.array_equal(rt._epoques[-1], attendue),
            "⚠️ l'époque du runtime est la tranche BRUTE du tampon, valeur pour valeur : aucun "
            "filtrage, aucune correction de ligne de base, aucune conversion d'unité ne s'est "
            "glissée dans `_encaisser_flash` (le décodeur filtre déjà — le faire deux fois est "
            "silencieux et détruit le signal)")
        chk(len(rt._epoques) == len(rt._cibles) == 1,
            f"et les deux listes sont toujours appariées ({len(rt._epoques)} époque(s), "
            f"{len(rt._cibles)} cible(s))")
        rt._vider_manche()
    finally:
        p300_models.modeles_disponibles = vrai_dispo
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[p300] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
