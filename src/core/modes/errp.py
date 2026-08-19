"""Mode ErrP : la machine vient-elle de se tromper, à CHAQUE feedback qu'une application externe
affiche. BCI **passive** — pas un choix, une réaction : le décodeur lit le potentiel d'erreur
(ERP fronto-central) que le cerveau émet malgré lui quand il perçoit une bévue de la machine.

Le décodage est dans `core/errp_decoder.py` (xDAWN + covariances riemanniennes + régression
logistique, réutilisant la pile P300 par composition). Ici on décrit le MODE : ce qui se règle, ce
qui se publie, et ce qu'il faut avoir avant de pouvoir décoder — un modèle ENTRAÎNÉ, comme le P300
et le Motor Imagery (`core/modes/p300.py`, le jumeau le plus proche de ce fichier, à lire avant
celui-ci). Sans modèle, ce mode ne démarre pas, et il le DIT.

⚠️ Un modèle est propre à UNE personne. Les scores d'un modèle entraîné sur quelqu'un d'autre sont
plausibles et faux — le pire des deux mondes.

⚠️ Le moteur ne rend AUCUN stimulus : c'est une application EXTERNE qui affiche le feedback (une
piste, une cible, une erreur DÉLIBÉRÉE de temps en temps) et publie l'instant où il apparaît à
l'écran sur le flux de marqueurs LSL (`core/markers.py`, événement `{"mode": "errp",
"event": "feedback"}`). Ce mode se contente d'ÉCOUTER ce flux (`engine.markers_murs`), d'épocher
l'EEG autour de chaque feedback (`core.errp_decoder.epoch_from_stream`), et de publier un verdict.

**Ton modèle de forme est `core/modes/p300.py` — mais trois de ses pires défauts n'ont PAS
d'équivalent ici, et c'est structurel : il n'y a pas de manche.** Le P300 agrège plusieurs flashs
avant de décider ; l'ErrP décide sur CHAQUE feedback, seul. Donc, par rapport à son jumeau :
    - pas de plafond de répétitions par cible (`_MAX_PAR_CIBLE`) : rien ne se répète ;
    - pas de contamination entre manches (`_verifie_abandon`) : rien ne s'accumule d'un feedback
      à l'autre, chaque `_traiter_feedback` se referme lui-même, du premier au dernier octet ;
    - pas d'abandon de manche : il n'y a rien à abandonner — un feedback qui n'arrive jamais ne
      laisse aucun état orphelin (contrairement à des flashs en attente d'un `round_end`).

⚠️ **Le moteur PUBLIE, il n'annule rien.** `ERRP_REFRACTORY_S` (la période après un veto pendant
laquelle le démonstrateur pygame ignore une 2e détection) reste dans `src/research/` — ce runtime
ne l'applique PAS, et ce n'est pas un oubli : « ne pas annuler la commande suivante » EST une
décision de commande, et ce projet publie des intentions neutres, jamais des commandes. Deux
feedbacks à 100 ms d'écart publient donc chacun leur propre verdict, sans qu'aucun des deux
n'efface l'autre (prouvé par `_selftest`).

⚠️ **Le flux ne se tait JAMAIS.** Un feedback reçu produit TOUJOURS un échantillon, même quand
l'époque est perdue (hors du tampon) ou rejetée pour artefact — jamais un silence. Et ces deux cas
publient `error = -1` (« pas de verdict »), **jamais `0`** : publier 0 affirmerait « pas d'erreur »
alors qu'on n'a rien vu. Un clignement au moment précis où la machine se trompe est le cas
FRÉQUENT, pas l'exception — c'est justement l'instant où l'utilisateur sursaute.

Cinq pannes bruyantes propres à ce mode (les trois premières — flux introuvable, marqueur trop
vieux, marqueur dans le futur — vivent une couche plus bas, `core/markers.py` et `core/server.py`,
déjà prouvées là-bas) :
    4. un modèle entraîné sur une AUTRE géométrie d'époque (fs, pré/post) -> refusé au démarrage,
       en nommant l'écart (`_desaccord_geometrie`) — le même contrôle que le P300, pour la même
       raison : une matrice de la même taille avec l'onset ailleurs rend des scores plausibles et
       faux, sans qu'aucune exception ne le signale.
    5. une époque mûre qui déborde quand même du tampon      -> comptée, `_epoques_perdues`,
       publiée `-1`
    6. une époque contaminée par un artefact (σ trop grand par rapport au repos, ex. un
       clignement) -> comptée, `_artefacts`, publiée `-1`
    7. des feedbacks reçus pendant la chauffe OU le repos    -> jetés, comptés
       (`_marqueurs_chauffe`), dits UNE fois (`_jeter_marqueurs_de_chauffe`) — le même défaut que
       le P300 a payé (sa revue l'a trouvé en critique n°2), et PLUS probable ici : ce mode attend
       15 s de chauffe PUIS 8 s de repos (23 s, contre 15 s pour le P300), et **c'est pendant le
       repos que ce mode mesure sa référence d'artefact** — sans consommer les marqueurs sur toute
       cette fenêtre, `markers_murs` ne serait jamais appelé, et le premier pas de décodage
       avalerait l'arriéré d'un coup, dont tout ce qui a déjà quitté le tampon EEG part en
       `engine.marqueurs_perdus`, sans que personne puisse dire pourquoi.
    8. un taux de rejet d'artefact ANORMALEMENT élevé (seuil mal calé, mauvais contact, casque
       qui dérive encore) -> rien ne le distinguait d'un clignement occasionnel : compté
       (`_epoques_vues`, `_artefacts`), exposé dans `state()`, et dit UNE fois en franchissant un
       palier déraisonnable (`_verifie_taux_rejet`) — sans quoi un mode qui écarte 9 époques sur
       10 tourne en silence : le flux ne se tait jamais (chaque feedback publie -1), mais rien ne
       dit si CE -1 est un clignement isolé ou le signe d'un réglage structurellement mauvais.
       ⚠️ Ces deux compteurs se rapportent au REPOS EN COURS, pas à la séance : « Refaire le
       repos » les remet à zéro ET réarme l'alarme (`_reset_rest`), sans quoi l'action que
       l'alarme RECOMMANDE serait précisément celle qui l'éteint pour le reste de la séance.
    9. une voie à σ NUL au repos (électrode arrachée, amplificateur en butée) -> son seuil de
       rejet vaudrait `4,0 × 0 = 0` et écarterait TOUTE époque de la séance : le repos REFUSE de
       conclure et nomme la voie (`_rest_step`), au lieu de rendre une référence inutilisable.

⚠️ **L'horodatage publié est celui du FEEDBACK, jamais « maintenant ».** Le moteur ne ramasse un
marqueur qu'une fois son époque complète (0,7 s après l'affichage), et sa boucle tourne à ~5 Hz :
publier l'instant du tour de boucle décalerait chaque verdict de 0,7 à 1,0 s — soit la fenêtre du
feedback SUIVANT (`ERRP_FEEDBACK_S` = 1,0 s) — et donnerait le MÊME horodatage à deux feedbacks
ramassés dans le même lot. Le seul contenu utile de ce flux est « la machine s'est trompée À CET
INSTANT-LÀ » : un verdict détaché de son événement ne vaut rien. Cf. `_traiter_feedback`, et
`p300.py` qui a tranché pareil pour son `round_end`.

⚠️ **σ du repos et σ de l'époque doivent être mesurés sur la MÊME représentation ET sur la MÊME
LONGUEUR DE FENÊTRE — les deux trouvés en revue, pas au premier jet.** Le second point est dans
`_rest_step` (le tampon du moteur fait 5,0 s, l'époque 0,9 s ; sur une dérive lente, mesuré ×2,01
de référence en trop, donc un sous-rejet invisible). Le premier :
`engine.acq.sigma_from_block` FILTRE (passe-bande ACQUISITION
5-40 Hz, cf. `core/acquisition.py`) ; l'époque que `_est_artefact` juge est BRUTE, sans aucun
traitement (cf. panne n°6). Un filtre ne peut que RETIRER de la puissance : à état électrique
identique, σ_brut ≥ σ_filtré, TOUJOURS — comparer les deux gonfle tout ratio d'un biais
SYSTÉMATIQUE, dans un seul sens (le SUR-rejet), pas d'un hasard de tirage. Mesuré (script jetable,
avec le vrai filtre d'acquisition) : sur du bruit blanc seul déjà ×1,9 (= la perte de bande,
√(125/35)) ; avec ne serait-ce que 10 µV de dérive ORDINAIRE sous 5 Hz — rien d'anormal sur ce
casque, cf. `core/acquisition.py` sur la dérive DC — le rapport grimpe à ~×9 et REJETTE 30 ÉPOQUES
SAINES SUR 30 en répétition. `_rest_step` mesure donc son σ sur le BRUT, comme l'époque (0 rejet à
tort sur les mêmes 30 tirages) — au prix assumé de ne plus filtrer le 50 Hz ni la dérive du repos
lui-même, sans conséquence ici : ce σ ne sert qu'à un RATIO contre une autre mesure BRUTE, jamais
affiché en valeur absolue comme une mesure de qualité (ça, c'est le rôle du flux `quality`, qui
compare bien du filtré à du filtré).

⚠️ **Ce que ce rejet attrape VRAIMENT, mesuré, et pas ce qu'on espérait.** Une version antérieure
de cette docstring promettait « un vrai clignement de 60 µV toujours détecté, ratio ~×10 » : ce
chiffre venait de la fixture de l'autotest (un repos à σ ≈ 2 µV), pas d'une séance. Re-mesuré sur
20 séances synthétiques réalistes (EEG propre 10 µV + dérive ordinaire, clignement gaussien de
~300 ms), support borné : `ERRP_ARTIFACT_RATIO` = 4,0 rejette **100 % des clignements à partir de
~150 µV crête, et rien en dessous de ~100 µV**. C'est un filet contre les GROS artefacts (le
sursaut, l'électrode qu'on touche), pas un détecteur de clignement fin — un clignement discret
part au modèle, et c'est assumé : un seuil assez bas pour l'attraper rejetterait aussi de l'EEG
sain, ce qui est le défaut que le tour de revue précédent venait de corriger.

Autotest :
    python src/core/modes/errp.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (ERRP_ARTIFACT_RATIO, ERRP_EPOCH_S, ERRP_PRE_S,  # noqa: E402
                         ERRP_TNR_TARGET, MARKER_STREAM_DEFAULT, SSVEP_WARMUP_S,
                         use_utf8_console)
import numpy as np  # noqa: E402

from core import errp_models  # noqa: E402
from core.errp_decoder import epoch_from_stream, pick_threshold  # noqa: E402
from core.lsl_io import DecodedErrPPublisher, errp_channel_labels  # noqa: E402
from core.modes.contract import Calib, ModeSpec, Param, Rest, validate  # noqa: E402
from core.modes.runtime import ModeRuntime  # noqa: E402

# Palier d'alarme du taux de rejet (panne n°8) : au-delà, ce n'est plus « un clignement
# occasionnel », c'est le signe d'un seuil mal calé, d'un mauvais contact, ou d'un casque qui
# dérive encore. 0,5 (pas 0,9) : le but est d'alerter TÔT, pas d'attendre l'extrême — un
# détecteur qui fonctionne correctement rejette une minorité des feedbacks, pas la moitié.
_TAUX_REJET_ALARME = 0.5
# Sous ce nombre d'époques VUES (perdues exclues), un taux est du bruit d'échantillonnage, pas un
# diagnostic : 1 artefact sur 2 essais ne dit rien sur le réglage, seulement sur le hasard.
_TAUX_REJET_MIN_ECHANTILLONS = 10
# En dessous, une voie est MORTE, pas calme : électrode arrachée, câble débranché, amplificateur
# en butée (le projet documente C3/Cz qui saturent à la réouverture de l'appli). Le seuil de rejet
# d'une telle voie vaudrait `4,0 × 0 = 0` et écarterait TOUTE époque de la séance — cf. `_rest_step`.
_SIGMA_VOIE_MORTE = 1e-6


class ErrPRuntime(ModeRuntime):
    """Un verdict par feedback : la machine vient-elle de se tromper. Aucune manche, aucun état
    qui survit d'un feedback à l'autre — `_traiter_feedback` se referme entièrement à chaque appel
    (cf. la docstring du module pour ce que ça retire par rapport au P300, son modèle de forme).

    ⚠️ Le moteur PUBLIE, il n'annule rien. La période réfractaire et la décision d'annuler une
    commande appartiennent à l'application : « n'annule pas cette commande » EST une commande, et
    ce projet publie des intentions neutres, jamais des commandes. `ERRP_REFRACTORY_S` reste au
    démonstrateur pygame — voir `src/research/`.

    `pre_s`/`post_s` sont des ATTRIBUTS DE CLASSE, pas seulement des variables d'instance : c'est
    ce qui permet à `registry.check()` de comparer `spec.marker_epoch_s` (ce que le moteur
    DIMENSIONNE) à ce que ce runtime PRÉLÈVE vraiment — le même contrôle que pour `P300Runtime`.

    Le SEUL réglage de ce mode est `tnr_target` : « quelle part des BONNES commandes garder »,
    jamais un seuil en log-odds — un nombre qui ne veut rien dire pour un étudiant. `__init__`
    traduit ce taux en seuil via `pick_threshold` (`core/errp_decoder.py`), sur les scores hors-pli
    de SA PROPRE calibration (`self.model.oof_y_`/`oof_scores_`). Le résultat est gardé dans
    `self.point_de_fonctionnement` (`tnr_target`, `seuil`, `tpr`, `tnr`) — c'est CE dict que
    `DecodedErrPPublisher` publie dans les métadonnées du flux (branché à la tâche 4).
    """

    pre_s = ERRP_PRE_S      # attributs de CLASSE : `registry.check()` les compare à
    post_s = ERRP_EPOCH_S   # `marker_epoch_s` pour qu'aucune époque ne soit tronquée en silence

    def __init__(self, spec, params, engine):
        super().__init__(spec, params, engine)
        self._out = None
        self._decoded = None
        # La dernière époque SCORÉE — uniquement le chemin de succès, cf. `_traiter_feedback` : une
        # époque perdue ou rejetée pour artefact la laisse INTACTE, elle ne se vide jamais toute
        # seule. Le nom le dit exprès (correction de revue, tâche 5 tour 1) : « dernière reçue »
        # aurait suggéré à tort qu'elle bouge à CHAQUE feedback. Pas pour l'affichage, pour
        # `_selftest` : LE TEST D'ALIGNEMENT compare son CONTENU, échantillon par échantillon, à la
        # tranche brute du tampon (cf. la docstring du module).
        self._derniere_epoque_scoree = None
        self.model, raison = errp_models.charger(params["model"])
        if self.model is None:
            # On lève ICI plutôt que de démarrer un mode muet. `validate` a déjà écarté le cas
            # « aucun modèle » ; il reste celui du fichier effacé entre la validation et le
            # démarrage, que seul le moteur peut voir — même garde que le P300 et le MI.
            raise ValueError(raison)
        desaccord = self._desaccord_geometrie(engine)
        if desaccord is not None:
            raise ValueError(desaccord)
        sans_scores = self._sans_scores_oof()
        if sans_scores is not None:
            raise ValueError(sans_scores)
        # Le SEUL réglage de ce mode : l'étudiant choisit un TAUX (« quelle part des bonnes
        # commandes je garde »), jamais un seuil en log-odds. `pick_threshold` est la MÊME fonction
        # que `ErrPModel.fit` utilise déjà pour poser `threshold_` (cf. `core/errp_decoder.py`) —
        # on ne réinvente rien, on la rappelle avec la cible de CET étudiant sur les scores hors-
        # pli de SA PROPRE calibration (`oof_y_`/`oof_scores_`, gardés par `ErrPModel` pour
        # exactement cet usage, cf. son commentaire « pour régler le seuil a posteriori »).
        cible = float(params["tnr_target"])
        self.seuil, mesures = pick_threshold(self.model.oof_y_, self.model.oof_scores_,
                                             tnr_target=cible)
        self.point_de_fonctionnement = {"tnr_target": cible, "seuil": self.seuil,
                                        "tpr": mesures["tpr"], "tnr": mesures["tnr"]}
        # ⚠️ Le TNR obtenu n'est pas toujours celui visé : `pick_threshold` retombe sur le seuil qui
        # MAXIMISE le TNR quand la cible est inatteignable. Sans ce message, l'étudiant croirait
        # avoir obtenu ce qu'il a demandé.
        print(f"[errp] point de fonctionnement : garde {mesures['tnr']:.1%} des bonnes commandes "
              f"(visé {cible:.0%}), attrape {mesures['tpr']:.1%} des erreurs — seuil {self.seuil:.3f}")
        self._sigmas_repos = None    # σ par voie mesuré au repos — la référence du rejet d'artefact
        self._echantillons = []      # les σ successifs mesurés PENDANT le repos, avant médiane
        self._epoques_perdues = 0    # marqueurs mûrs dont l'époque a quand même débordé du tampon
        self._marqueurs_chauffe = 0  # feedbacks jetés, reçus pendant la chauffe OU le repos
        self._chauffe_dite = False   # l'avertissement de chauffe/repos, une fois par repos
        self._repos_mort_dit = False  # l'avertissement « voie à σ nul », une fois par repos
        # ⚠️ Correction de revue (tour 2) : ces trois-là se rapportent au REPOS EN COURS, pas à
        # la session — c'est `_reset_rest` qui les remet à zéro. Le taux de rejet se juge CONTRE
        # LE σ QUI L'A PRODUIT : le mesurer par-dessus l'ancien mêle deux références et rend
        # impossible de voir si « Refaire le repos » a servi — précisément le geste que l'alarme
        # de la panne n°8 RECOMMANDE. Pire, garder `_rejet_eleve_dit` à True en travers d'un
        # nouveau repos éteignait l'alarme pour le RESTE de la séance, même si le nouveau σ
        # empirait la situation. Le P300 a tranché dans le même sens pour le cas analogue
        # (`_refus_cible`, réarmé à chaque manche).
        self._epoques_vues = 0       # feedbacks dont l'époque a pu être EXTRAITE (perdues
                                      # exclues) — le DÉNOMINATEUR du taux de rejet (panne n°8)
        self._artefacts = 0          # époques écartées : σ trop grand par rapport au repos
        self._rejet_eleve_dit = False   # l'alarme de sur-rejet (panne n°8), au plus UNE fois
        # …et les CUMULS de session, qui eux ne se remettent jamais à zéro : sans eux, refaire le
        # repos effacerait l'historique de ce que ce mode a déjà écarté dans la séance. Exposés à
        # part dans `state()`, jamais mélangés au taux courant.
        self._epoques_vues_session = 0
        self._artefacts_session = 0

    def _desaccord_geometrie(self, engine):
        """La phrase à dire si le MODÈLE n'a pas été entraîné sur la géométrie que ce runtime
        prélève — None si tout concorde. Jumeau exact de `P300Runtime._desaccord_geometrie` :
        `ErrPModel` porte `fs`, `pre_s` et `post_s`, les trois nombres qui décident de la FORME
        d'une époque et de l'endroit où le feedback tombe dedans. Un modèle entraîné à une autre
        fréquence, ou avec d'autres bornes pré/post que `ERRP_PRE_S`/`ERRP_EPOCH_S` du moment (un
        script de ré-entraînement direct, ou une constante qui a changé depuis), reçoit ici des
        matrices d'une autre taille — ou pire, de la MÊME taille avec l'onset ailleurs — et rend
        des scores plausibles et faux, sans qu'aucune exception ne le signale.
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
                f"(`python src/research/app.py`, mode ErrP) plutôt que de le forcer.")

    def _sans_scores_oof(self):
        """La phrase à dire si le modèle n'a pas de scores hors-pli — None si tout va bien.

        ⚠️ Correction de revue (tâche 3) : SECOND filet, indépendant du premier
        (`errp_models.charger`, qui refuse déjà ce cas À LA SOURCE — cf. `errp_models.py`). Même
        raisonnement que `self.model is None` plus haut : `validate` a déjà écarté ce cas via la
        liste que `charger` filtre, il reste la course entre la validation et le démarrage (un
        fichier remplacé entre-temps), que seul le moteur peut voir.

        `ErrPModel.fit` ne pose `oof_scores_`/`oof_y_` que si la calibration a au moins 10 essais,
        2 classes, et une classe minoritaire d'au moins 2 membres (sa garde, `errp_decoder.py`) —
        en dessous, ces deux attributs restent `None`. Sans ce filet, `pick_threshold(None, None,
        ...)` plus bas lève une exception numpy BRUTE — mesuré, pas supposé :
        `ValueError: zero-dimensional arrays cannot be concatenated`, sans aucun rapport avec ce
        qu'il faut faire.
        """
        if self.model.oof_scores_ is None or self.model.oof_y_ is None:
            # ⚠️ La cause se LIT sur le modèle (`echec_oof_`, posé par `ErrPModel.fit` au moment où
            # sa garde a mordu), elle ne se récite pas. Réciter la liste des trois causes possibles
            # obligeait l'étudiant à deviner laquelle est la sienne, et cette liste devenait fausse
            # en silence à la première garde ajoutée. `getattr` parce qu'un modèle entraîné avant
            # que cet attribut existe n'en a pas : on retombe alors sur la formulation générale.
            cause = getattr(self.model, "echec_oof_", None)
            return (f"ce modèle n'a pas de scores hors-pli "
                    f"({cause or 'calibration trop courte ou dégénérée'}) — impossible d'y régler "
                    f"un seuil. Recalibre (`python src/research/app.py`, mode ErrP) plutôt que de "
                    f"le forcer.")
        return None

    def _open(self):
        # Comme le SSVEP, le MI et le P300 : le flux existe TOUT DE SUITE, avant même la fin de la
        # chauffe/du repos — un client qui le cherche au lancement ne doit pas dépendre de
        # l'instant où arrive le premier feedback (`resolve_byprop` a un délai fini).
        # `n_calib` = l'effectif de `self.model.oof_y_`, PAS `self.model.n_epoques_` — bien que ce
        # dernier existe désormais (ajouté par la revue finale, parité avec `P300Model`). Les deux
        # nombres sont égaux aujourd'hui mais ne répondent pas à la même question : `n_epoques_`
        # dit combien d'époques ont entraîné le modèle, `len(oof_y_)` dit sur combien d'essais le
        # POINT DE FONCTIONNEMENT publié ici a été mesuré. C'est le second que le client a besoin
        # de lire à côté de `tpr_measured`, et il se mettrait à diverger le jour où un essai serait
        # écarté du calcul hors-pli sans l'être de l'entraînement.
        self._out = DecodedErrPPublisher(self.point_de_fonctionnement,
                                         n_calib=len(self.model.oof_y_),
                                         instance=self.engine.instance)

    def _close(self):
        self._out = None

    def _reset_rest(self):
        """Tout ce qui dépend du σ de repos meurt avec lui — y compris le taux de rejet.

        ⚠️ Correction de revue (tour 2). `_artefacts`/`_epoques_vues`/`_rejet_eleve_dit`
        SURVIVAIENT à « Refaire le repos », au nom de l'historique de session. Or c'est
        exactement l'action que l'alarme de la panne n°8 recommande, et la garder armée avait
        deux effets, tous deux muets : `state()["taux_rejet"]` mélangeait les époques jugées
        contre l'ANCIEN σ et celles jugées contre le NOUVEAU (« 30/80 = 37 % » alors que le
        taux courant est 0 %, d'où la conclusion fausse « le nouveau repos n'a rien changé »),
        et `_rejet_eleve_dit` déjà à True empêchait toute nouvelle alarme pour le reste de la
        séance — même si le nouveau repos avait EMPIRÉ le rejet. L'historique n'est pas perdu
        pour autant : il part dans `_epoques_vues_session`/`_artefacts_session`, exposés à part.
        """
        self._sigmas_repos = None
        self._echantillons = []
        self._decoded = None
        self._chauffe_dite = False
        self._repos_mort_dit = False
        self._epoques_vues = 0
        self._artefacts = 0
        self._rejet_eleve_dit = False

    def output(self):
        return self._decoded

    def state(self):
        """Comme `ModeRuntime.state()`, plus les compteurs de ce que ce mode JETTE, ET le taux de
        rejet qui en découle (panne n°8) — le même filet que `P300Runtime.state()` : sans cette
        sortie, un client qui n'a pas la console ouverte au bon instant ne voit jamais combien
        d'époques ont été perdues ou écartées, ni si ce chiffre est en train de dériver.

        ⚠️ Correction de revue (tour 1, tâche 4) : `point_de_fonctionnement` (tnr_target/seuil/
        tpr/tnr) voyage ICI, pas dans `output()` — c'est une mesure de SESSION, posée une fois en
        `__init__`, pas un champ publié à chaque échantillon (contrairement à `threshold`, qui
        EST sur le flux). Sans lui, aucun client de la console ne peut savoir que ce détecteur
        n'attrape qu'une partie des erreurs : la console est un CLIENT du moteur, elle ne peut
        montrer que ce que `state()` lui donne.
        """
        base = super().state()
        base["epoques_perdues"] = self._epoques_perdues
        # ⚠️ `epoques_vues`/`artefacts`/`taux_rejet` décrivent le REPOS EN COURS, pas la séance
        # entière (cf. `_reset_rest`) : les trois se lisent ensemble, et `artefacts / epoques_vues`
        # vaut TOUJOURS `taux_rejet`. Les cumuls de séance sont juste en dessous, nommés autrement
        # — mélanger les deux est ce qui rendait « Refaire le repos » impossible à évaluer.
        base["epoques_vues"] = self._epoques_vues
        base["artefacts"] = self._artefacts
        # None tant qu'aucune époque n'a pu être jugée : un taux de 0/0 mentirait en affichant 0.
        base["taux_rejet"] = (round(self._artefacts / self._epoques_vues, 3)
                              if self._epoques_vues else None)
        base["epoques_vues_session"] = self._epoques_vues_session
        base["artefacts_session"] = self._artefacts_session
        base["marqueurs_chauffe"] = self._marqueurs_chauffe
        base["point_de_fonctionnement"] = self.point_de_fonctionnement
        return base

    def _rest_step(self, engine, now):
        """σ du repos, mesuré sur le BRUT **et sur la longueur d'UNE ÉPOQUE** — ni
        `engine.acq.sigma_from_block()`, ni `engine.recent` en entier.

        ⚠️ Deux corrections de revue, indépendantes, qui poussaient dans des sens OPPOSÉS. Une
        seule règle les résume : **ce σ n'existe que pour être comparé à celui d'une époque
        (`_est_artefact`), donc il doit être mesuré COMME elle — même représentation, même
        longueur de fenêtre.** Tout écart sur l'un des deux est un biais SYSTÉMATIQUE du ratio,
        pas un hasard de tirage.

        1. La REPRÉSENTATION (tour 1). `sigma_from_block` FILTRE (passe-bande ACQUISITION
           5-40 Hz), alors que l'époque jugée est BRUTE (`_traiter_feedback`, aucun traitement).
           Un filtre ne peut que RETIRER de la puissance : σ_brut ≥ σ_filtré, TOUJOURS — donc
           biais dans le seul sens du SUR-rejet. Mesuré (avec le vrai filtre d'acquisition) :
           rien que la perte de bande donne ×1,9 (=√(125/35)) sur du bruit blanc ; avec 10 µV de
           dérive ORDINAIRE sous 5 Hz, ~×9, et 30 époques SAINES rejetées sur 30 en répétition.

        2. Le SUPPORT (tour 2). `engine.recent` fait `EngineServer.keep` échantillons — **5,0 s**
           aujourd'hui, dont le terme dominant est `MI_IMAGERY_S`, c'est-à-dire l'époque
           d'entraînement d'un AUTRE mode : le rejet d'artefact de l'ErrP était réglé par une
           constante du Motor Imagery. L'époque jugée, elle, fait `pre_s + post_s` = 0,9 s. Or
           pour toute composante LENTE (dérive DC résiduelle, 1/f — la signature documentée de
           ce casque), σ CROÎT avec la longueur de la fenêtre : σ ∝ √T pour une marche
           aléatoire, σ ∝ T pour une rampe. La référence était donc GONFLÉE, le ratio jugé
           déflaté, et le mode SOUS-rejetait — l'inverse du défaut n°1, et bien pire : un
           sur-rejet se VOIT (`taux_rejet`, panne n°8), un sous-rejet ne se voit JAMAIS. L'époque
           contaminée part au modèle, qui rend un score plausible, publié avec `artifact = 0`.
           Mesuré (script jetable, 20 séances synthétiques, dérive ordinaire de 20 µV sur 5 s,
           EEG propre à 10 µV) : σ_repos(5,0 s)/σ_repos(0,9 s) = **×2,01** (min ×1,22, max
           ×2,57). Le mode se comportait donc comme si `ERRP_ARTIFACT_RATIO` valait 8 au lieu
           de 4. Conséquence mesurée sur les mêmes séances : un clignement de 150 µV crête
           n'était rejeté que 9 % du temps, contre **100 %** une fois le support borné ; il
           fallait 250 µV pour atteindre 50 % de rejet.
           ⚠️ Sur du bruit BLANC ce ratio vaut 1,00 — et sur le board synthétique de BrainFlow
           aussi (mesuré, 8 voies sur 8, ratio 0,98-1,00 : il est stationnaire). C'est
           exactement pourquoi aucun smoke, aucun `--synthetic`, ne pouvait le voir : il faut
           une fixture qui PORTE une dérive, sur UN SEUL tampon continu.

        `server.py._publish_quality` interdit déjà ce même geste, en toutes lettres, pour la
        mesure de qualité (« On ne passe PAS `self.recent` en entier… un couplage NON borné »).
        Borner à `n_epoque` a en prime un effet sur la MÉDIANE de la ligne d'après : deux
        fenêtres successives sont espacées de `period_s()` = 0,2 s, donc le recouvrement tombe
        de 96 % (5,0 s) à 78 % (0,9 s). Un clignement pendant le repos polluait 26 des ~40
        fenêtres — soit la MAJORITÉ, donc la médiane elle-même, donc le seuil de TOUTE la
        séance ; il n'en pollue plus que ~5, et la médiane fait enfin ce que son nom promet.

        Le plancher est `n_epoque` lui-même, plus `engine.acq.margin_n` : ce dernier était
        emprunté « comme ordre de grandeur commode », alors que le bon plancher est précisément
        la longueur qu'on s'apprête à mesurer.

        La chauffe de 15 s existe déjà pour laisser la rampe DC se tasser AVANT toute mesure :
        c'est elle qui rend un repos brut exploitable, pas un filtrage a posteriori — qui
        rendrait en prime le détecteur aveugle à un clignement (déflexion LENTE, sous 5 Hz :
        filtrer l'ÉPOQUE aussi effacerait le signal même que ce rejet vise — mesuré sur la
        fixture du tour 1, le ratio du MÊME clignement tombait de ~×10 à ~×2,2, repassant sous
        le seuil ×4). Pour ce que ce rejet attrape vraiment en séance, en µV et pas en ratio,
        voir le ⚠️ de la docstring du MODULE : ~150 µV crête, pas 60.
        """
        n_epoque = int(round((self.pre_s + self.post_s) * engine.acq.fs))
        bloc = engine.recent
        if bloc is None or len(bloc) < n_epoque:
            return False
        sig = np.asarray(bloc[-n_epoque:], dtype=float).std(axis=0)
        self._echantillons.append(sig)
        if now < self._rest_until:
            return False
        sigmas = np.median(np.asarray(self._echantillons), axis=0)
        # ⚠️ Panne n°9 (trouvée en revue) : une voie à σ NUL donne un seuil de rejet de
        # `4,0 × 0 = 0`, que la moindre valeur non constante franchit — donc TOUTE époque de la
        # séance écartée, un flux de `-1` en boucle. C'est le symptôme d'une électrode arrachée
        # ou d'un amplificateur en butée, pas d'un repos réussi : on REFUSE de conclure, on le
        # DIT en nommant la ou les voies, et on remesure une fenêtre entière plutôt que de
        # répéter le message 5 fois par seconde.
        mortes = [int(i) for i, s in enumerate(sigmas) if float(s) <= _SIGMA_VOIE_MORTE]
        if mortes:
            if not self._repos_mort_dit:
                self._repos_mort_dit = True
                print(f"[errp] repos INEXPLOITABLE : voie(s) {mortes} à σ nul (électrode "
                      f"décollée, câble débranché ou amplificateur en butée) — avec cette "
                      f"référence, le rejet d'artefact écarterait TOUTE époque de la séance. "
                      f"Vérifie le contact, puis « Refaire le repos ».")
            self._echantillons = []
            self._rest_until = now + self._rest_s
            return False
        self._sigmas_repos = sigmas
        print(f"[errp] repos mesuré ({len(self._echantillons)} fenêtres de {n_epoque} "
              f"échantillons, la longueur d'une époque) — σ par voie (brut) : "
              f"{np.array2string(self._sigmas_repos, precision=1)}")
        self.rest_report = {"kind": "errp", "fenetres": len(self._echantillons),
                            "sigma": [round(float(s), 2) for s in self._sigmas_repos]}
        return True

    def tick(self, engine, lsl_ts, now):
        """Comme `ModeRuntime.tick`, mais la chauffe ET le repos CONSOMMENT les marqueurs au lieu
        de les laisser s'empiler derrière un curseur immobile (panne n°7, cf. docstring du
        module). Redéfinir `tick` plutôt qu'écrire ça dans `_rest_step` : `_rest_step` n'est
        appelé QUE pendant la phase « rest », et c'est aussi pendant « warmup » (15 s) que
        l'arriéré se forme — le même choix que `P300Runtime.tick`, élargi à « rest » puisqu'ici
        cette phase dure 8 s au lieu de 0.

        ⚠️ `in ("warmup", "rest")`, pas `== "warmup"` : le second se lit comme une simplification
        (`ModeRuntime.tick` teste bien `warmup` en premier) et coûterait les 8 s de repos —
        ~8 marqueurs empilés derrière un curseur immobile, avalés d'un coup au premier
        `_run_step`. C'est la SEULE différence entre ce `tick` et celui du P300, donc sa raison
        d'être ; `_selftest` la prouve par un `tick` dont la phase est « rest » À L'ENTRÉE.
        """
        if self.phase in ("warmup", "rest"):
            self._jeter_marqueurs_de_chauffe(engine)
        super().tick(engine, lsl_ts, now)

    def _jeter_marqueurs_de_chauffe(self, engine):
        """Vide la file de CE mode pendant la chauffe ET le repos, en comptant et en le disant
        une fois. Appeler `markers_murs` est ce qui fait avancer le curseur du moteur : sans cet
        appel pendant les 23 s d'attente (15 s de chauffe + 8 s de repos, PLUS LONGUES que celles
        du P300), le premier `_run_step` recevrait d'un coup tous les feedbacks de la séance dont
        la plupart n'ont plus leur EEG dans le tampon — ils partiraient alors en
        `engine.marqueurs_perdus`, comptés par le moteur mais sans que personne puisse dire
        pourquoi. C'était le critique n°2 de la revue du P300 ; le geste est identique
        (`p300.py._jeter_marqueurs_de_chauffe`), le message est adapté.
        """
        jetes = engine.markers_murs(self.spec.id, post_s=self.post_s)
        if not jetes:
            return
        # ⚠️ Compté APRÈS le même filtrage que `_run_step` (`event == "feedback"`), pas sur le
        # retour brut : `markers_murs` ne trie que par `mode_id` (cf. `server.py`), et ce
        # protocole GRANDIRA — le commentaire de `_run_step` le dit. Le jour où l'émetteur
        # publiera un `{"mode": "errp", "event": "run_start"}` par piste, chacun serait compté
        # comme un feedback perdu, dans le chiffre même qui sert à décider si l'émetteur a été
        # lancé trop tôt. L'appel à `markers_murs` reste inconditionnel : c'est LUI qui fait
        # avancer le curseur, feedback ou pas.
        feedbacks = sum(1 for _ts, m in jetes if m.get("event") == "feedback")
        if not feedbacks:
            return
        self._marqueurs_chauffe += feedbacks
        if not self._chauffe_dite:
            self._chauffe_dite = True
            # ⚠️ « le premier dont l'ÉPOQUE COMPLÈTE tombe après le repos », pas « le premier
            # reçu après le repos » (correction de revue) : `markers_murs` ne rend un marqueur
            # que quand `ts + post_s` est dans le tampon, donc un feedback affiché moins de
            # `post_s` = 0,7 s avant la fin du repos n'est PAS encore mûr — il échappe à ce
            # rejet, reste en file, et se fait décoder au premier pas de décodage sur de l'EEG
            # prélevé AVANT la fin du repos. Bénin en usage nominal (8 s de repos, donc du
            # débordement sur de l'EEG de repos), pas avec un repos raccourci.
            print(f"[errp] {feedbacks} feedback(s) reçus pendant la CHAUFFE/le REPOS : jetés — "
                  f"l'offset DC du casque dérive encore et le repos n'a pas fini de mesurer son "
                  f"bruit de fond. Le premier feedback décodé sera le premier dont l'ÉPOQUE "
                  f"COMPLÈTE tombe après le repos.")

    def _run_step(self, engine, lsl_ts):
        """⚠️ `lsl_ts` (« maintenant » dans l'horloge LSL) est reçu parce que `ModeRuntime.tick`
        le passe à tous les modes — mais ce mode ne le PUBLIE PAS, et c'est une décision, pas un
        oubli : ce qui part sur le réseau est l'horodatage du FEEDBACK (`ts`), cf.
        `_traiter_feedback`. Il n'est pas non plus transmis plus bas, pour qu'aucune ligne ne
        puisse le publier par accident.
        """
        for ts, marqueur in engine.markers_murs(self.spec.id, post_s=self.post_s):
            if marqueur.get("event") != "feedback":
                continue        # un événement inconnu s'ignore : le protocole grandira
            self._traiter_feedback(engine, ts)

    def _traiter_feedback(self, engine, ts):
        """Un feedback, un verdict — jamais de silence (cf. ⚠️ de la docstring du module).

        ⚠️ `ts` (l'instant du feedback à l'écran) sert à DEUX choses, et c'est volontaire : il
        découpe l'époque, ET il horodate l'échantillon publié. Publier « maintenant » à la place
        — ce que faisait ce runtime avant la revue de branche — décale CHAQUE verdict de 0,7 à
        1,0 s : `markers_murs` ne rend un marqueur qu'une fois `ts + post_s` dans le tampon
        (0,7 s), la boucle du moteur ajoute la granularité de `period_s()` (0,2 s) et le délai de
        lecture du bloc. Comme un feedback reste affiché `ERRP_FEEDBACK_S` = 1,0 s, le verdict
        tombait donc sur la fenêtre du feedback SUIVANT. Pire, deux feedbacks ramassés dans le
        même lot recevaient le MÊME horodatage : un client n'avait plus aucun moyen de savoir
        auquel des deux se rapporte un verdict. Or le seul contenu utile de ce flux est « la
        machine s'est trompée À CET INSTANT-LÀ ». `p300.py` a tranché de la même façon, pour la
        même raison (« L'instant du `round_end`, PAS `lsl_ts` »).
        """
        epoque = epoch_from_stream(engine.recent, engine.recent_ts, ts, engine.acq.fs,
                                   pre_s=self.pre_s, post_s=self.post_s)
        if epoque is None:
            self._epoques_perdues += 1
            self._publish(-1, 0.0, artefact=0, lsl_ts=ts)
            return
        self._epoques_vues += 1
        self._epoques_vues_session += 1
        if self._est_artefact(epoque):
            self._artefacts += 1
            self._artefacts_session += 1
            self._verifie_taux_rejet()
            self._publish(-1, 0.0, artefact=1, lsl_ts=ts)
            return
        # ⚠️ Capturée ICI — au tout dernier moment avant l'appel au modèle, rien après — c'est ce
        # qui permet à la preuve rouge-puis-vert (tâche 5) de fonctionner : un traitement inséré
        # par erreur entre l'extraction et le scorage (un `bandpass()` de trop, par exemple) se
        # refléterait DANS cette valeur, alors qu'une assertion de simple POSITION resterait
        # aveugle (`filtfilt` est à phase nulle : le pic reste au même échantillon). Seul CE
        # chemin l'écrit — l'époque perdue et l'artefact sont déjà sortis par un `return`, plus
        # haut, sans y toucher.
        self._derniere_epoque_scoree = epoque
        score = float(np.ravel(self.model.score(epoque[None, ...]))[0])
        self._publish(1 if score >= self.seuil else 0, score, artefact=0, lsl_ts=ts)

    def _est_artefact(self, epoque):
        """σ de l'époque contre σ du repos, voie par voie. Un clignement sur l'erreur est le cas
        FRÉQUENT : c'est justement au moment où la machine se trompe que l'utilisateur sursaute.

        Avant que le repos ait rendu sa mesure (`_sigmas_repos is None`), on ne rejette rien :
        aucune référence, aucun jugement possible. Ne devrait pas arriver en usage normal —
        `_run_step` ne démarre qu'une fois la phase « rest » terminée — mais une garde manquante
        ici ferait lever un `TypeError` sur `None > ...` au lieu de publier -1 proprement.
        """
        if self._sigmas_repos is None:
            return False
        sig = np.asarray(epoque, dtype=float).std(axis=0)
        return bool(np.any(sig > ERRP_ARTIFACT_RATIO * self._sigmas_repos))

    def _verifie_taux_rejet(self):
        """Panne bruyante n°8 : dit UNE fois, quand le taux de rejet franchit un palier
        déraisonnable, ce que rien d'autre ne distinguait — « un clignement occasionnel » d'« un
        seuil structurellement mal calé pour ce casque ou cette séance ».

        Sans ce compteur, un mode qui écarte 9 époques sur 10 tourne en silence : chaque
        feedback publie -1 (le flux ne se tait jamais, cf. docstring du module), mais AUCUN de
        ces -1 ne dit s'il est isolé ou systématique. C'est la panne canonique de ce projet — un
        décodeur qui publie des scores honnêtes et ne déclenche jamais — sous un autre visage :
        ici, un rejet honnête qui ne laisse plus jamais rien passer.

        `_TAUX_REJET_MIN_ECHANTILLONS` avant de juger : un taux sur un tout petit effectif est
        du bruit d'échantillonnage, pas un diagnostic (1 artefact sur 2 essais ne prouve rien).
        """
        if self._rejet_eleve_dit or self._epoques_vues < _TAUX_REJET_MIN_ECHANTILLONS:
            return
        taux = self._artefacts / self._epoques_vues
        if taux < _TAUX_REJET_ALARME:
            return
        self._rejet_eleve_dit = True
        print(f"[errp] ⚠️ taux de rejet artefact élevé : {self._artefacts}/{self._epoques_vues} "
              f"({taux:.0%}) des époques écartées — au-delà d'un clignement occasionnel. "
              f"Vérifie le contact des électrodes, ou « Refaire le repos ».")

    def _publish(self, error, score, artefact, lsl_ts):
        if self._out is not None:
            # `self.seuil` est CONSTANT pour toute la durée de vie de ce runtime (posé une fois en
            # __init__) : le publier à CHAQUE échantillon, plutôt que dans les seules métadonnées,
            # permet à un client qui n'a capturé que le flux de données (un enregistrement XDF, par
            # exemple, sans sa description LSL) de savoir quand même contre quoi `score` a été
            # comparé — cf. la docstring de `DecodedErrPPublisher`.
            self._out.push(error, score, self.seuil, artefact, lsl_ts)
        # ⚠️ Correction de revue (tour 1, tâche 4) : la clé était `"artefact"` (français), alors
        # que `ssvep.py`/`neuro.py` écrivent `"artifact"` (anglais), aligné sur le libellé de voie
        # LSL (`errp_channel_labels()` -> "artifact"). Masqué tant que rien ne lisait `output()`
        # côté console — un piège prêt à mordre le premier rendu écrit sur le motif des modes
        # voisins (`sortie.get("artifact")`), qui aurait lu `None` en silence.
        self._decoded = {
            "error": int(error),
            "score": round(float(score), 3),
            "artifact": int(artefact),
            "threshold": float(self.seuil),
        }
        self._log(error, score, artefact)

    def _log(self, error, score, artefact):
        """Trace CHAQUE verdict, sans limite de fréquence : un feedback reste affiché
        `ERRP_FEEDBACK_S` = 1 s, ce flux est donc bien plus lent que le SSVEP ou le MI (~5 Hz en
        continu) — aucun risque de noyer le terminal, le même raisonnement que `P300Runtime._log`.
        """
        if artefact:
            verdict = "— (écarté : artefact, σ au-dessus du repos)"
        elif error < 0:
            verdict = "— (perdu : époque hors du tampon)"
        elif error == 1:
            verdict = "ERREUR détectée"
        else:
            verdict = "correct"
        print(f"[errp] {verdict:<40} score={score:+.3f}  seuil={self.seuil:+.3f}")


SPEC = ModeSpec(
    id="errp", label="ErrP", family="passif",   # passif : une RÉACTION observée, pas un choix fait
    summary="Un verdict par feedback affiché : la machine vient-elle de se tromper (potentiel d'erreur).",
    status="moteur",
    params=(
        Param(key="model", label="Modèle entraîné", kind="choice",
              choices_fn=lambda: errp_models.modeles_disponibles(),
              help="Le modèle produit par une calibration ErrP, propre à TA personne — celui "
                   "de quelqu'un d'autre donne des verdicts plausibles et faux. Aucun modèle "
                   "dans la liste ? Lance `python src/research/app.py`, mode ErrP, et calibre."),
        Param(
            key="tnr_target",
            label="Bonnes commandes gardées",
            kind="float",
            default=ERRP_TNR_TARGET,
            min=0.50, max=0.99,
            help="La part des BONNES commandes que tu veux garder. Le moteur en déduit son seuil "
                 "sur les données de TA calibration. Monter cette valeur annule moins de bonnes "
                 "commandes mais attrape moins d'erreurs — mesuré sur la séance de référence : "
                 "garder 95 % n'attrape que 24 % des erreurs, garder 85 % en attrape 50 %, "
                 "garder 70 % en attrape 71 %. Il n'y a pas de repas gratuit.",
        ),
        # ⚠️ Le MÊME `Param` que `p300.py`, et il ne peut pas manquer ici (correction de revue) :
        # ce mode déclare `marker_epoch_s > 0`, donc le moteur le compte parmi ceux qui écoutent
        # des marqueurs (`server._nom_flux_marqueurs`). Sans ce réglage, `contract.validate`
        # REFUSE la clé (« réglage inconnu pour « ErrP » ») et le flux entrant reste gelé sur
        # `MARKER_STREAM_DEFAULT` — deux binômes dans la même salle ne peuvent plus se séparer,
        # et le moteur du binôme B épocherait l'EEG de B autour des feedbacks affichés chez A,
        # en publiant des verdicts parfaitement plausibles. Pire, l'omission cassait la voie de
        # secours que l'aide du P300 PROMET : `_libere_marker_inlet` ne lâche l'inlet que si
        # AUCUN mode actif n'écoute des marqueurs, donc en `--mode errp,p300` l'ErrP le
        # maintenait ouvert sur l'ancien nom et redémarrer le P300 ne reprenait rien.
        Param(key="stream_in", label="Flux de marqueurs", kind="choice",
              choices=(MARKER_STREAM_DEFAULT,), default=MARKER_STREAM_DEFAULT,
              affecte_decodage=False,
              help="Le nom du flux LSL sur lequel ton application publie l'onset de chaque "
                   "feedback affiché. Le moteur l'écoute par son NOM, résolu quand un mode qui "
                   "consomme des marqueurs démarre — un seul inlet existe pour tout le moteur, "
                   "partagé par tous ces modes. Le changer pendant que le mode tourne n'a AUCUN "
                   "effet : l'inlet ouvert reste sur l'ancien nom. ARRÊTER puis redémarrer ce "
                   "mode suffit en revanche à reprendre le nouveau — l'inlet est lâché dès que "
                   "plus aucun mode actif ne l'écoute. Deux modes actifs qui en réclameraient "
                   "des noms différents ne sont pas mélangés en silence : un désaccord est "
                   "signalé bruyamment, un seul nom gagne."),
    ),
    rest=Rest(
        warmup_s=SSVEP_WARMUP_S,   # 15 s : l'offset DC de l'Unicorn dérive après ouverture
        duration_s=8.0,            # même durée que le SSVEP : deux modes lancés ensemble PARTAGENT
        instruction="Repos : regarde l'écran, immobile — on mesure le bruit de fond de tes voies.",
    ),
    calibration=Calib(kind="natif",
                      reason="l'onset du feedback écran doit être horodaté à la frame"),
    # Le suffixe est le même littéral que celui que `DecodedErrPPublisher` construit lui-même via
    # `stream_name("decoded_errp")` (core/lsl_io.py) — la même convention que le MI (`decoded_mi`).
    # Les VOIES, elles, viennent de `errp_channel_labels()` : LA seule fonction qui les nomme, pour
    # le publieur ET pour ce contrat — deux façons de les construire finiraient par diverger d'un
    # espace ou d'une décimale (cf. sa docstring dans lsl_io.py).
    stream="decoded_errp",
    channels=tuple(errp_channel_labels()),
    runtime_cls=ErrPRuntime,
    marker_epoch_s=ERRP_PRE_S + ERRP_EPOCH_S,   # 0,9 s — dimensionne le tampon du moteur
)


def _selftest():
    """Le mode de bout en bout : un vrai modèle ErrP entraîné sur du signal synthétique, un faux
    moteur qui rend des marqueurs et un tampon SUR COMMANDE.

    La MATURITÉ d'un marqueur (horodatage, curseur par mode, purge) est déjà prouvée dans
    `server.py` (`_smoke_marqueurs_murs`, `_smoke_marqueurs_file_coincee`) : ce mode ne la
    réimplémente pas, ce test ne la rejoue donc pas. Il se concentre sur ce que CE mode fait de
    marqueurs déjà mûrs : épocher, rejeter un artefact, comparer à un seuil, publier — et sur les
    pannes bruyantes propres au protocole ErrP (géométrie du modèle, époque perdue, artefact,
    feedbacks pendant la chauffe/le repos).

    Le verdict du VRAI modèle sur une époque tirée au hasard n'est PAS ce que ce test juge (l'ErrP
    mono-essai est un détecteur imparfait par construction, AUC ~0,78 mesurée — un tirage précis
    peut se tromper, et un test qui en dépendrait serait FRAGILE). La logique score/seuil est donc
    prouvée avec un faux modèle à score CONNU (comme `_ModeleControle` dans `p300.py`) ; le vrai
    modèle sert uniquement à prouver que le chemin réel (charger, comparer la géométrie, appeler
    `.score()`) fonctionne de bout en bout, sans juger LEQUEL des deux verdicts il rend.
    """
    import io
    import shutil
    import tempfile
    from contextlib import redirect_stdout

    from core.acquisition import UnicornAcquisition
    from core.errp_decoder import ErrPModel, synth_errp_epoch

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _FauxPublieur:
        def __init__(self):
            self.lignes = []

        def push(self, error, score, seuil, artefact, lsl_ts=None):
            self.lignes.append((error, score, seuil, artefact, lsl_ts))

    class _FauxMoteur:
        """Juste ce dont le runtime a besoin. `markers_murs` rend les marqueurs un LOT à la fois,
        dans l'ordre fourni pour CE test — la maturité elle-même est déjà prouvée côté
        `server.py` (cf. docstring de `_selftest`)."""

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

    class _ModeleScore:
        """Un faux modèle ErrP dont `.score()` renvoie une valeur FIXE et connue à l'avance —
        prouve la logique score/seuil/artefact sans dépendre de la justesse d'un vrai décodage
        mono-essai (déjà validée, avec son AUC honnête, dans `errp_decoder.py`)."""

        def __init__(self, valeur):
            self.valeur = valeur
            self.appels = 0

        def score(self, epochs):
            self.appels += 1
            return [self.valeur] * len(epochs)

    def marqueur(t, event="feedback"):
        return (t, {"mode": "errp", "event": event})

    rng = np.random.default_rng(0)
    fs = 250.0

    dossier = tempfile.mkdtemp(prefix="errp_mode_")
    vrai_dispo = errp_models.modeles_disponibles
    try:
        # 1. Sans modèle du tout, le mode REFUSE et dit comment en obtenir un.
        vide = _os.path.join(dossier, "aucun")
        _os.makedirs(vide, exist_ok=True)
        errp_models.modeles_disponibles = lambda dossier=vide: vrai_dispo(dossier)
        _v, raison = validate(SPEC, {})
        chk(raison is not None and "aucun choix disponible" in raison
            and "research/app.py" in raison,
            f"sans modèle, le mode refuse en disant quoi faire ({raison})")

        # Un modèle jetable, entraîné sur de l'ErrP synthétique (même recette que
        # `errp_models._selftest` : 40 essais, 30 % d'erreurs, 4 blocs — assez pour une AUC
        # groupée non triviale ; n_perm=0 parce que ce fichier ne teste pas la significativité).
        n_trials, error_rate, blocks = 40, 0.3, 4
        epochs, y, groups = [], [], []
        per = max(1, n_trials // blocks)
        for i in range(n_trials):
            is_err = rng.random() < error_rate
            epochs.append(synth_errp_epoch(is_err, fs=fs, rng=rng))
            y.append(1 if is_err else 0)
            groups.append(min(blocks - 1, i // per))
        modele = ErrPModel(fs=fs).fit(np.asarray(epochs), np.asarray(y),
                                      groups=np.asarray(groups), n_perm=0)
        chemin = _os.path.join(dossier, "errp_model.joblib")
        modele.save(chemin)

        # 2. Avec un modèle, les défauts sont valides et c'est lui qui est pris.
        errp_models.modeles_disponibles = lambda d=dossier: vrai_dispo(d)
        values, raison = validate(SPEC, {})
        chk(values is not None, f"avec un modèle, les défauts passent ({raison})")
        chk(values["model"] == chemin, f"et c'est le modèle trouvé qui est pris ({values['model']})")
        chk(values["tnr_target"] == ERRP_TNR_TARGET,
            f"...et le taux de bonnes commandes à garder prend le défaut du protocole "
            f"({values['tnr_target']})")
        chk({p.key for p in SPEC.params} == {"model", "tnr_target", "stream_in"},
            "le modèle, le taux de bonnes commandes à garder ET le flux de marqueurs se règlent")
        # ⚠️ `stream_in` n'est pas décoratif : ce mode déclare `marker_epoch_s > 0`, donc le
        # moteur le lit (`server._nom_flux_marqueurs`) pour choisir le flux entrant. Sans lui,
        # `contract.validate` REFUSAIT la clé — le flux de marqueurs de l'ErrP était gelé sur le
        # défaut, et deux binômes dans la même salle ne pouvaient plus se séparer.
        chk(values.get("stream_in") == MARKER_STREAM_DEFAULT,
            f"...et le flux de marqueurs prend le défaut du protocole, comme le P300 "
            f"({values.get('stream_in')})")
        chk(SPEC.marker_epoch_s > 0.0,
            f"ce mode CONSOMME des marqueurs, donc le moteur lit son stream_in — c'est ce qui "
            f"rend ce réglage obligatoire et non décoratif ({SPEC.marker_epoch_s})")

        # 3. Le contrat du mode.
        chk(SPEC.id == "errp" and SPEC.family == "passif",
            f"identifiant et famille du mode ({SPEC.id}, {SPEC.family})")
        chk(ErrPRuntime.pre_s == ERRP_PRE_S and ErrPRuntime.post_s == ERRP_EPOCH_S,
            f"pre_s/post_s sont exposés en attributs de CLASSE, lisibles par registry.check() "
            f"({ErrPRuntime.pre_s}, {ErrPRuntime.post_s})")
        chk(SPEC.marker_epoch_s == ERRP_PRE_S + ERRP_EPOCH_S,
            f"l'époque déclarée vaut pré+post ({SPEC.marker_epoch_s:g})")
        chk(SPEC.rest.warmup_s == SSVEP_WARMUP_S and SPEC.rest.duration_s == 8.0,
            f"chauffe 15 s puis repos 8 s, comme le SSVEP ({SPEC.rest})")
        chk(SPEC.calibration is not None and SPEC.calibration.kind == "natif"
            and SPEC.calibration.runtime_cls is None,
            "sa calibration reste NATIVE : l'appli pygame la joue, pas le moteur")
        chk(SPEC.status == "moteur" and SPEC.stream == "decoded_errp",
            f"le mode est publié sur decoded_errp (status={SPEC.status!r}, stream={SPEC.stream!r})")
        chk(list(SPEC.channels_for(values)) == errp_channel_labels(),
            f"...avec les voies construites par LA seule fonction qui les nomme, pour le "
            f"publieur ET pour ce contrat ({SPEC.channels_for(values)})")

        # 20 s de tampon continu, largement assez de marge pour des feedbacks entre t=105 et
        # t=110 avec pre_s=0,2 / post_s=0,7. Du BRUIT à l'échelle de l'EEG (pas des zéros) : le
        # rejet d'artefact compare un σ à un autre σ, un tampon plat ne prouverait rien.
        recent_ts = np.arange(100.0, 120.0, 1.0 / fs)
        recent = rng.normal(0.0, 2.0, (len(recent_ts), 8))
        moteur = _FauxMoteur(recent, recent_ts)

        # 3bis. Un modèle entraîné sur une AUTRE géométrie d'époque est refusé au DÉMARRAGE, en
        # nommant l'écart — le même contrôle que `P300Runtime`, pour la même raison : une matrice
        # de la même taille avec l'onset ailleurs rend des scores plausibles et faux.
        autre_geo = _os.path.join(dossier, "geometrie_etrangere.joblib")
        # ⚠️ Doit être ENTRAÎNÉ, pas seulement construit — depuis la correction de revue de la
        # tâche 3 (fix 1 ci-dessous) : `errp_models.charger` refuse désormais tout modèle SANS
        # scores hors-pli, et un `ErrPModel` jamais `.fit()` en est un. Sans cet entraînement, ce
        # fixture serait arrêté par le PREMIER filet (pas de scores hors-pli) avant d'atteindre le
        # SECOND (la géométrie) que ce test précis vise — trouvé en relançant, pas supposé.
        ErrPModel(fs=125.0).fit(np.asarray(epochs), np.asarray(y), groups=np.asarray(groups),
                                n_perm=0).save(autre_geo)
        essai = dict(values, model=autre_geo)
        try:
            ErrPRuntime(SPEC, essai, moteur)
            refus_geo = None
        except ValueError as e:
            refus_geo = str(e)
        chk(refus_geo is not None and "fs" in refus_geo and "125" in refus_geo,
            f"un modèle entraîné sur une AUTRE géométrie d'époque est refusé au démarrage, en "
            f"nommant l'écart ({refus_geo})")

        # 3ter. ⚠️ Correction de revue (tâche 3) : un modèle sans scores hors-pli (calibration
        # trop courte : moins de 10 essais, une seule classe, ou une classe à moins de 2 membres)
        # est refusé au DÉMARRAGE, EN LE NOMMANT — le SECOND filet, indépendant du premier
        # (`errp_models.charger`, déjà testé dans `errp_models.py`) pour la même course que
        # « aucun modèle » ci-dessus : un fichier remplacé entre la validation et le démarrage
        # reste possible, et seul le moteur peut le voir. `errp_models.charger` est monkeypatché
        # ICI pour isoler ce SECOND filet : sans le court-circuiter, son propre refus (le premier
        # filet) masquerait qu'`__init__` a — ou n'a pas — le sien.
        #
        # AVANT ce correctif, ce même scénario faisait tomber `pick_threshold` sur une exception
        # numpy BRUTE — mesuré, pas supposé : `ValueError: zero-dimensional arrays cannot be
        # concatenated`, à des lignes de tout message nommé, l'inverse du standard de ce fichier
        # (cf. `_desaccord_geometrie` juste au-dessus).
        degenere = _os.path.join(dossier, "geometrie_degeneree.joblib")
        modele_degenere = ErrPModel(fs=fs).fit(np.asarray(epochs[:5]), np.asarray(y[:5]), n_perm=0)
        chk(modele_degenere.oof_scores_ is None and modele_degenere.oof_y_ is None,
            f"fixture : 5 essais (< 10) ne posent PAS de scores hors-pli, la dégénérescence est "
            f"réelle, pas simulée ({modele_degenere.oof_scores_})")
        modele_degenere.save(degenere)
        vrai_charger = errp_models.charger
        errp_models.charger = lambda chemin: (modele_degenere, None)  # court-circuite le 1er filet
        try:
            essai_degenere = dict(values, model=degenere)
            try:
                ErrPRuntime(SPEC, essai_degenere, moteur)
                refus_scores = None
            except ValueError as e:
                refus_scores = str(e)
        finally:
            errp_models.charger = vrai_charger
        chk(refus_scores is not None and "hors-pli" in refus_scores
            and "recalibre" in refus_scores.lower(),
            f"un modèle sans scores hors-pli est refusé au démarrage, EN LE NOMMANT, plutôt que "
            f"de laisser pick_threshold lever une exception numpy brute ({refus_scores})")

        # ⚠️ Capturé : c'est ICI que se dit le point de fonctionnement (tâche 3). Sans ce message,
        # l'étudiant croirait avoir obtenu exactement le TNR qu'il a demandé — cf. plus bas, le
        # cas où `pick_threshold` retombe sur le seuil qui MAXIMISE le TNR.
        capture_recalcul = io.StringIO()
        with redirect_stdout(capture_recalcul):
            rt = ErrPRuntime(SPEC, values, moteur)
        texte_recalcul = capture_recalcul.getvalue()
        print(texte_recalcul, end="")   # rejoué : la capture ne doit pas rendre ce test muet
        rt._out = _FauxPublieur()
        rt._opened = True
        chk(rt.phase == "warmup", "l'ErrP commence par une chauffe")
        seuil_reel = rt.seuil
        chk(seuil_reel == float(modele.threshold_),
            f"avec le réglage par défaut (tnr_target={ERRP_TNR_TARGET:g}, identique à celui de "
            f"la calibration), le seuil RECALCULÉ retombe exactement sur celui qu'avait appris "
            f"ErrPModel.fit ({seuil_reel})")
        chk("point de fonctionnement" in texte_recalcul and "visé" in texte_recalcul,
            f"...et ce recalcul se DIT au démarrage, avec le TNR visé ET celui obtenu — sans quoi "
            f"l'étudiant croirait avoir eu exactement ce qu'il a demandé ({texte_recalcul.strip()!r})")
        chk(rt.point_de_fonctionnement is not None
            and set(rt.point_de_fonctionnement) == {"tnr_target", "seuil", "tpr", "tnr"},
            f"point_de_fonctionnement expose EXACTEMENT les 4 clés que `DecodedErrPPublisher` "
            f"publie dans les métadonnées (tâche 4) ({rt.point_de_fonctionnement})")
        chk(rt.point_de_fonctionnement["tnr_target"] == values["tnr_target"]
            and rt.point_de_fonctionnement["seuil"] == seuil_reel,
            f"...avec la cible demandée et le seuil qu'elle a produit ({rt.point_de_fonctionnement})")
        # Le CÂBLAGE de `stream_in` : `server._nom_flux_marqueurs` lit `rt.params["stream_in"]`
        # sur chaque mode actif dont `marker_epoch_s > 0`. Un runtime qui ne porterait pas la clé
        # retomberait en silence sur `MARKER_STREAM_DEFAULT` via son `.get(..., défaut)`.
        chk(rt.params.get("stream_in") == MARKER_STREAM_DEFAULT,
            f"le RUNTIME porte le nom du flux entrant, là où le moteur va le chercher "
            f"({rt.params.get('stream_in')})")

        # --- ⚠️ TEST DE MONOTONIE (tâche 3) : LE test qui protège le SEUL réglage de ce mode -----
        # Demander à garder PLUS de bonnes commandes doit donner un seuil PLUS HAUT et attraper
        # MOINS d'erreurs. C'est une MONOTONIE : une implémentation cassée (seuil constant, cible
        # ignorée, sens inversé) ne peut pas la simuler.
        #
        # ⚠️ Passe par un VRAI `ErrPRuntime`, reconstruit à CHAQUE cible — pas seulement par un
        # appel direct à `pick_threshold` : ce que ce test protège, c'est que LE MODE lise
        # `params["tnr_target"]`, pas que `pick_threshold` soit monotone (déjà de la responsabilité
        # de `errp_decoder.py`). C'est exactement le défaut trouvé en revue du P300 : `stream_in`
        # déclaré dans le contrat, jamais lu par le runtime. Un test qui n'appellerait que
        # `pick_threshold` en direct resterait VERT même si `ErrPRuntime.__init__` ignorait `cible`
        # (la preuve rouge-puis-vert de cette tâche, dans le rapport, mute précisément CE recalcul).
        points = []
        for cible in (0.70, 0.85, 0.95):
            essai_cible = dict(values, tnr_target=cible)
            rt_cible = ErrPRuntime(SPEC, essai_cible, moteur)
            seuil_direct, m_direct = pick_threshold(modele.oof_y_, modele.oof_scores_,
                                                    tnr_target=cible)
            pdf = rt_cible.point_de_fonctionnement
            chk(rt_cible.seuil == seuil_direct and pdf["tpr"] == m_direct["tpr"]
                and pdf["tnr"] == m_direct["tnr"],
                f"à tnr_target={cible:g}, le runtime recalcule EXACTEMENT ce que rend "
                f"pick_threshold sur les scores de SA calibration (seuil={rt_cible.seuil} vs "
                f"{seuil_direct})")
            points.append((cible, pdf["seuil"], pdf["tpr"], pdf["tnr"]))
        seuils = [p[1] for p in points]
        tprs = [p[2] for p in points]
        chk(seuils[0] < seuils[1] < seuils[2],
            f"viser plus de bonnes commandes MONTE le seuil ({[round(s, 3) for s in seuils]})")
        chk(tprs[0] > tprs[1] > tprs[2],
            f"...et fait attraper MOINS d'erreurs ({[round(t, 3) for t in tprs]})")
        chk(all(p[3] >= p[0] - 1e-9 for p in points),
            f"et chaque point atteint la cible demandée ({[(p[0], round(p[3], 3)) for p in points]})")

        # 4. La CHAUFFE *et* le REPOS consomment les marqueurs au lieu de les laisser s'empiler
        # (panne n°7). C'est l'appel à `markers_murs` qui fait avancer le curseur du moteur.
        rt.begin_rest(now=0.0, warmup_s=1.0, duration_s=2.0)
        moteur._lots = [[marqueur(101.0), marqueur(101.1)]]     # 2 feedbacks pendant la chauffe
        capture = io.StringIO()
        with redirect_stdout(capture):
            rt.tick(moteur, lsl_ts=101.1, now=0.5)      # encore en chauffe (< 1,0 s)
        chk(rt.phase == "warmup", f"à 0,5 s sur 1, on est toujours en chauffe ({rt.phase})")
        chk(rt._marqueurs_chauffe == 2,
            f"les 2 feedbacks de la chauffe sont jetés et COMPTÉS ({rt._marqueurs_chauffe})")

        moteur._lots = [[marqueur(101.2)]]      # 1 feedback de plus, pile à la bascule vers "rest"
        with redirect_stdout(capture):
            rt.tick(moteur, lsl_ts=101.2, now=1.5)      # chauffe finie -> repos
        chk(rt.phase == "rest", f"la chauffe finie, le repos commence ({rt.phase})")
        chk(rt._marqueurs_chauffe == 3,
            f"...celui reçu PILE à la bascule est jeté lui aussi ({rt._marqueurs_chauffe})")

        # ⚠️ LA seule assertion qui distingue `in ("warmup", "rest")` de `== "warmup"` — la
        # raison d'être DÉCLARÉE de ce `tick` redéfini. Les deux appels ci-dessus avaient la
        # phase « warmup » À L'ENTRÉE (la bascule a lieu DANS `super().tick`, après la garde) :
        # ils ne prouvaient donc rien sur le repos, malgré ce que leur message affirmait. Ici la
        # phase EST « rest » à l'entrée, et la file n'est PAS vide. Sans cette garde élargie, les
        # 8 s de repos empileraient ~8 marqueurs derrière un curseur immobile, avalés d'un coup
        # au premier `_run_step` — dont tout ce qui a quitté le tampon part en
        # `engine.marqueurs_perdus`, sans que personne puisse dire pourquoi (panne n°7).
        appels_avant_repos = moteur.appels_murs
        moteur._lots = [[marqueur(101.3)]]
        rt.tick(moteur, lsl_ts=102.1, now=2.0)          # phase == "rest" À L'ENTRÉE
        chk(rt.phase == "rest" and rt._marqueurs_chauffe == 4
            and moteur.appels_murs == appels_avant_repos + 1,
            f"le REPOS jette et compte lui aussi les feedbacks reçus pendant qu'il mesure, et "
            f"c'est son appel à markers_murs qui fait avancer le curseur du moteur "
            f"({rt.phase}, {rt._marqueurs_chauffe}, "
            f"{moteur.appels_murs - appels_avant_repos} appel(s))")

        # ⚠️ Un événement qui n'est PAS un feedback ne gonfle pas le compteur de feedbacks jetés :
        # `markers_murs` ne trie que par `mode_id`, et le protocole grandira. Ce chiffre sert à
        # décider si l'émetteur a été lancé trop tôt — le fausser, c'est fausser ce diagnostic.
        moteur._lots = [[marqueur(101.35, event="run_start"), marqueur(101.4)]]
        rt.tick(moteur, lsl_ts=102.2, now=2.1)
        chk(rt._marqueurs_chauffe == 5,
            f"...mais seuls les FEEDBACKS sont comptés : un « run_start » jeté en même temps "
            f"n'ajoute rien au compte ({rt._marqueurs_chauffe}, 5 attendu)")

        texte_chauffe = capture.getvalue()
        print(texte_chauffe, end="")   # rejoué : la capture ne doit pas rendre ce test muet
        chk(texte_chauffe.count("CHAUFFE") == 1,
            f"l'avertissement n'est dit qu'UNE fois pour toute la chauffe ET le repos "
            f"({texte_chauffe.count('CHAUFFE')} occurrence(s))")
        # ⚠️ Le message PROMET ce que le moteur tient. « le premier reçu APRÈS le repos » était
        # faux : un feedback affiché moins de `post_s` = 0,7 s avant la fin du repos n'est pas
        # encore mûr, échappe donc à ce rejet, et se fait décoder sur de l'EEG prélevé AVANT.
        chk("ÉPOQUE COMPLÈTE" in texte_chauffe and "premier reçu APRÈS" not in texte_chauffe,
            f"...et il promet ce qui est VRAI : « le premier dont l'ÉPOQUE COMPLÈTE tombe après "
            f"le repos », pas « le premier reçu après » ({texte_chauffe.strip()!r})")
        chk(rt._out.lignes == [],
            f"...et aucun des feedbacks jetés n'a produit la moindre publication "
            f"({len(rt._out.lignes)})")

        # Le repos mesure son σ sur PLUSIEURS fenêtres avant de conclure (`_rest_until`) : on
        # avance jusqu'à ce qu'il tienne, sans qu'aucun marqueur ne traîne plus dans la file.
        moteur._lots = []
        for t in (2.7, 3.5):
            rt.tick(moteur, lsl_ts=101.2, now=t)
        chk(rt.phase == "running", f"le repos mesuré, le mode se met à décoder ({rt.phase})")
        chk(rt.rest_report is not None and rt.rest_report["kind"] == "errp"
            and rt.rest_report["fenetres"] > 0,
            f"...et laisse un compte-rendu avec le nombre de fenêtres mesurées ({rt.rest_report})")
        chk(rt._sigmas_repos is not None and len(rt._sigmas_repos) == 8,
            f"...un σ par voie, sur les 8 voies ({rt._sigmas_repos})")
        chk(rt._out.lignes == [], "toujours aucune publication avant le premier pas décodé")

        # --- Le CONTRAT du chemin réel : un feedback bien formé, sur le VRAI modèle -----------
        # On ne juge PAS lequel des deux verdicts sort (cf. docstring de `_selftest`) : seulement
        # que le chemin complet (`epoch_from_stream` -> `_est_artefact` -> `model.score` -> seuil
        # -> publication) tourne sans lever et respecte le CONTRAT.
        #
        # ⚠️ TOUS les `tick` à partir d'ici passent un `lsl_ts` VOLONTAIREMENT loin de
        # l'horodatage du marqueur (+0,8 s, l'ordre de grandeur réel : `markers_murs` ne rend un
        # marqueur qu'une fois `ts + post_s` = 0,7 s dans le tampon, plus la granularité de la
        # boucle). C'est ce qui rend les assertions d'horodatage DISCRIMINANTES : tant que les
        # deux valeurs étaient égales dans la fixture, `chk(ts_reel == t_reel)` restait vert quoi
        # que publie le runtime — le seul appel où elles différaient (le lot à deux marqueurs
        # plus bas) n'assertait que le NOMBRE de lignes.
        t_reel = 105.0
        moteur._lots = [[marqueur(t_reel)]]
        rt.tick(moteur, lsl_ts=t_reel + 0.8, now=4.0)
        chk(len(rt._out.lignes) == 1, f"le vrai modèle produit une ligne ({len(rt._out.lignes)})")
        err_reel, score_reel, seuil_pub, art_reel, ts_reel = rt._out.lignes[-1]
        chk(err_reel in (-1, 0, 1), f"un index dans le contrat ({err_reel})")
        chk(art_reel == 0 and np.isfinite(score_reel),
            f"un feedback banal (bruit à l'échelle du repos) n'est PAS un artefact, et le score "
            f"est un nombre fini ({art_reel}, {score_reel})")
        chk(ts_reel == t_reel,
            f"l'horodatage publié est celui du FEEDBACK, PAS le tour de boucle qui l'a traité "
            f"({ts_reel} attendu {t_reel}, lsl_ts valait {t_reel + 0.8}) — sans quoi chaque "
            f"verdict tomberait 0,7 à 1,0 s trop tard, soit sur le feedback SUIVANT")
        # ⚠️ Le POINT DE FONCTIONNEMENT (tâche 4) : le seuil publié à CHAQUE échantillon, pas
        # seulement dans les métadonnées — cf. le commentaire de `_publish`.
        chk(seuil_pub == rt.seuil,
            f"le seuil publié EST celui contre lequel `score` a été comparé, pas une constante "
            f"({seuil_pub} vs rt.seuil={rt.seuil})")
        chk(rt.output() == {"error": err_reel, "score": round(score_reel, 3), "artifact": 0,
                            "threshold": rt.seuil},
            f"la sortie exposée à l'affichage reprend la même décision, avec la clé "
            f"« artifact » (anglais, alignée sur ssvep.py/neuro.py et le libellé de voie LSL) "
            f"({rt.output()})")

        # --- La logique score/seuil, sur un modèle à score CONNU -----------------------------
        espion = _ModeleScore(seuil_reel + 5.0)     # nettement AU-DESSUS du seuil
        rt.model = espion
        t = 106.0
        moteur._lots = [[marqueur(t)]]
        rt.tick(moteur, lsl_ts=t + 0.8, now=4.5)
        chk(rt._out.lignes[-1] == (1, seuil_reel + 5.0, seuil_reel, 0, t),
            f"score >= seuil -> error=1, avec le VRAI score, le seuil publié et l'horodatage du "
            f"feedback ({rt._out.lignes[-1]})")
        chk(espion.appels == 1, f"le modèle a bien été consulté une fois ({espion.appels})")

        espion2 = _ModeleScore(seuil_reel - 5.0)    # nettement SOUS le seuil
        rt.model = espion2
        t = 107.0
        moteur._lots = [[marqueur(t)]]
        rt.tick(moteur, lsl_ts=t + 0.8, now=5.0)
        chk(rt._out.lignes[-1] == (0, seuil_reel - 5.0, seuil_reel, 0, t),
            f"score < seuil -> error=0, jamais -1 : « correct » est une réponse à part entière, "
            f"pas une absence de verdict ({rt._out.lignes[-1]})")

        # --- Une époque PERDUE (mûre mais hors du tampon) publie -1, artefact=0, SANS consulter
        # le modèle -------------------------------------------------------------------------
        avant_perdues = rt._epoques_perdues
        rt.model = espion   # si jamais consulté, on le saurait (nouvel appel compté)
        appels_avant = espion.appels
        t_perdu = 5.0        # loin AVANT recent_ts[0] = 100.0 : hors du tampon
        moteur._lots = [[marqueur(t_perdu)]]
        rt.tick(moteur, lsl_ts=t_perdu + 0.8, now=5.5)
        ligne = rt._out.lignes[-1]
        chk(ligne == (-1, 0.0, seuil_reel, 0, t_perdu),
            f"une époque perdue publie -1, score neutre, artefact=0 — JAMAIS 0 ({ligne})")
        chk(rt._epoques_perdues == avant_perdues + 1,
            f"...et c'est COMPTÉ, pas ignoré en silence ({rt._epoques_perdues})")
        chk(espion.appels == appels_avant,
            f"...sans que le modèle soit consulté ({espion.appels - appels_avant} appel(s) de plus)")

        # --- Une époque ARTEFACT (σ très supérieur au repos) publie -1, artefact=1, SANS
        # consulter le modèle -----------------------------------------------------------------
        avant_artefacts = rt._artefacts
        appels_avant = espion.appels
        t_art = 108.0
        i_art = int(np.searchsorted(recent_ts, t_art))
        n_pre, n_post = int(round(ERRP_PRE_S * fs)), int(round(ERRP_EPOCH_S * fs))
        recent[i_art - n_pre:i_art + n_post] = rng.normal(0.0, 200.0, (n_pre + n_post, 8))
        moteur._lots = [[marqueur(t_art)]]
        rt.tick(moteur, lsl_ts=t_art + 0.8, now=6.0)
        ligne = rt._out.lignes[-1]
        chk(ligne == (-1, 0.0, seuil_reel, 1, t_art),
            f"une époque artefact publie -1, score neutre, artefact=1 — JAMAIS 0 ({ligne})")
        chk(rt._artefacts == avant_artefacts + 1,
            f"...et c'est COMPTÉ séparément des époques perdues ({rt._artefacts})")
        chk(espion.appels == appels_avant,
            f"...sans que le modèle soit consulté — un clignement au moment de l'erreur est le "
            f"cas FRÉQUENT, pas l'exception ({espion.appels - appels_avant} appel(s) de plus)")

        # --- Un événement inconnu s'ignore : le protocole grandira, sans publication -----------
        avant_lignes = len(rt._out.lignes)
        moteur._lots = [[marqueur(109.0, event="round_end")]]   # existe côté P300, pas ici
        rt.tick(moteur, lsl_ts=109.0, now=6.5)
        chk(len(rt._out.lignes) == avant_lignes,
            f"un événement qui n'est pas « feedback » ne publie RIEN ({len(rt._out.lignes)} "
            f"ligne(s), {avant_lignes} attendues)")

        # --- ⚠️ Le moteur PUBLIE, il n'annule rien : deux feedbacks à 100 ms d'écart (bien SOUS
        # ERRP_REFRACTORY_S=1,5 s) publient CHACUN leur verdict, aucun n'efface l'autre ----------
        avant_lignes = len(rt._out.lignes)
        moteur._lots = [[marqueur(110.0), marqueur(110.1)]]
        rt.tick(moteur, lsl_ts=110.9, now=7.0)      # UN seul tour de boucle pour les DEUX
        chk(len(rt._out.lignes) == avant_lignes + 2,
            f"deux feedbacks rapprochés publient DEUX verdicts, sans période réfractaire — elle "
            f"reste au démonstrateur pygame ({len(rt._out.lignes) - avant_lignes})")
        # ⚠️ L'assertion qui ferme définitivement le trou de l'horodatage : DEUX feedbacks
        # ramassés dans le MÊME lot, donc au même tour de boucle. Publier « maintenant » leur
        # donnerait le MÊME horodatage (110,9 tous les deux) — un client ne pourrait ni les
        # distinguer l'un de l'autre, ni les rattacher à son propre journal, et le seul contenu
        # utile de ce flux (« la machine s'est trompée À CET INSTANT-LÀ ») disparaîtrait. C'est
        # le cas ORDINAIRE, pas un cas tordu : la boucle du moteur tourne à ~5 Hz et l'émetteur
        # affiche un feedback par seconde.
        chk([l[-1] for l in rt._out.lignes[-2:]] == [110.0, 110.1],
            f"...CHACUN horodaté à SON feedback, pas les deux au même tour de boucle "
            f"({[l[-1] for l in rt._out.lignes[-2:]]}, lsl_ts valait 110.9 pour les deux)")

        # --- Le flux ne se tait JAMAIS : autant de lignes publiées que de feedbacks ENVOYÉS ----
        # (1 réel + 1 score>=seuil + 1 score<seuil + 1 perdu + 1 artefact + 2 rapprochés = 7 ;
        # l'événement inconnu n'en fait PAS partie, il n'a jamais atteint `_traiter_feedback`.)
        chk(len(rt._out.lignes) == 7,
            f"un échantillon par feedback envoyé, quoi qu'il arrive ({len(rt._out.lignes)}/7)")

        # ⚠️ Le CÂBLAGE du taux de rejet (panne n°8), après un trafic RÉEL — pas des compteurs
        # posés à la main. Deux mutations d'une ligne, toutes deux plausibles à la relecture, ne
        # se distinguent que d'ici : déplacer `_epoques_vues += 1` APRÈS la garde d'artefact (ce
        # qui se lit comme « ne compter que les époques réellement jugées ») donne un
        # dénominateur qui EXCLUT les artefacts, donc un `taux_rejet` qui peut dépasser 1,0 —
        # « 300 % » affiché dans la console, et l'alarme qui part beaucoup trop tôt.
        # 6 = 1 réel + 2 espions + 1 artefact + 2 rapprochés ; l'époque PERDUE est exclue (elle
        # n'a jamais pu être extraite) et l'événement inconnu n'a jamais atteint le décodage.
        chk(rt._epoques_vues == 6 and rt._epoques_perdues == 1 and rt._artefacts == 1,
            f"le dénominateur du taux compte les époques EXTRAITES, artefacts COMPRIS, perdues "
            f"EXCLUES ({rt._epoques_vues} vues, {rt._epoques_perdues} perdues, "
            f"{rt._artefacts} artefacts)")

        # ⚠️ …et l'alarme elle-même, franchie PAR `tick`. Les quatre cas de règle plus bas posent
        # les compteurs à la main et appellent `_verifie_taux_rejet` en direct : ils prouvent la
        # RÈGLE (plancher d'effectif, palier, dite une seule fois) mais jamais le FIL qui la
        # relie au runtime. Supprimer l'appel depuis la branche artefact de `_traiter_feedback`
        # (il a tout l'air d'un détail d'affichage) laissait les 64 assertions vertes — et, en
        # séance, un casque mal salé rejetant 9 époques sur 10 publiait `-1` en boucle sans que
        # RIEN ne soit jamais dit. On sature donc une plage entière du tampon et on y envoie
        # 10 feedbacks, par le chemin réel.
        i_sat = int(np.searchsorted(recent_ts, 111.0))
        recent[i_sat:] = rng.normal(0.0, 200.0, (len(recent) - i_sat, 8))
        moteur._lots = [[marqueur(111.5 + 0.5 * k) for k in range(10)]]
        capture_alarme = io.StringIO()
        with redirect_stdout(capture_alarme):
            rt.tick(moteur, lsl_ts=117.0, now=7.5)
        texte_alarme = capture_alarme.getvalue()
        print(texte_alarme, end="")
        chk(rt._artefacts == 11 and rt._epoques_vues == 16,
            f"les 10 feedbacks saturés sont tous comptés comme artefacts par le chemin réel "
            f"({rt._artefacts}/{rt._epoques_vues})")
        # « 5/10 », pas « 11/16 » : l'alarme part au PREMIER franchissement du palier (10 époques
        # vues, 50 % de rejet), au 4ᵉ des 10 feedbacks — c'est le but, alerter TÔT — et ne se
        # répète pas pour les 6 suivants, tous artefacts eux aussi.
        chk(texte_alarme.count("taux de rejet") == 1 and "5/10" in texte_alarme,
            f"...et l'alarme de sur-rejet part DEPUIS `tick`, au premier franchissement du "
            f"palier, une seule fois pour les 10 ({texte_alarme.count('taux de rejet')} "
            f"occurrence(s) : {texte_alarme.strip()!r})")

        # 5. Les compteurs de pertes ont une sortie AUTRE que le terminal : `state()`.
        etat = rt.state()
        chk({"epoques_perdues", "artefacts", "marqueurs_chauffe"} <= set(etat),
            f"les trois compteurs de pertes sont exposés dans state() ({sorted(etat)})")
        chk(etat["epoques_perdues"] == rt._epoques_perdues
            and etat["artefacts"] == rt._artefacts
            and etat["marqueurs_chauffe"] == rt._marqueurs_chauffe,
            f"...et reflètent les compteurs RÉELS du runtime, pas une copie figée "
            f"(state={etat['epoques_perdues'], etat['artefacts'], etat['marqueurs_chauffe']}, "
            f"réel={rt._epoques_perdues, rt._artefacts, rt._marqueurs_chauffe})")

        # --- ⚠️ « Refaire le repos » RÉARME l'alarme et remet son dénominateur à zéro ----------
        # C'est l'action que l'alarme ci-dessus RECOMMANDE en toutes lettres. La garder armée
        # avait deux effets, tous deux muets : `taux_rejet` mélangeait les époques jugées contre
        # l'ANCIEN σ et le NOUVEAU (« 11/16 » encore affiché alors que le taux courant est 0 %,
        # d'où la conclusion fausse « le nouveau repos n'a rien changé, le casque est mauvais »),
        # et `_rejet_eleve_dit` déjà à True empêchait TOUTE nouvelle alarme pour le reste de la
        # séance — même si le nouveau repos avait empiré le rejet. Le P300 a tranché pareil pour
        # son `_refus_cible`.
        vues_session_avant = rt._epoques_vues_session
        arts_session_avant = rt._artefacts_session
        rt.begin_rest(now=10.0, warmup_s=0.0, duration_s=0.0)
        etat_refait = rt.state()
        chk(etat_refait["taux_rejet"] is None and etat_refait["artefacts"] == 0
            and etat_refait["epoques_vues"] == 0 and not rt._rejet_eleve_dit,
            f"« Refaire le repos » remet le taux à « rien mesuré » et RÉARME l'alarme, sans quoi "
            f"le geste que l'alarme recommande serait celui qui l'éteint pour la séance "
            f"({etat_refait['taux_rejet']}, {etat_refait['artefacts']}/"
            f"{etat_refait['epoques_vues']}, dite={rt._rejet_eleve_dit})")
        chk(etat_refait["epoques_vues_session"] == vues_session_avant == 16
            and etat_refait["artefacts_session"] == arts_session_avant == 11,
            f"...sans perdre l'historique de la séance, qui vit dans deux compteurs NOMMÉS à "
            f"part ({etat_refait['epoques_vues_session']}, {etat_refait['artefacts_session']})")
        chk(etat_refait["marqueurs_chauffe"] == rt._marqueurs_chauffe == 5,
            f"...et les feedbacks jetés pendant la chauffe restent, eux, un compteur de SÉANCE "
            f"({etat_refait['marqueurs_chauffe']})")
        rt.tick(moteur, lsl_ts=118.0, now=11.0)      # repos de durée nulle : on redécode
        chk(rt.phase == "running", f"...et le mode repart en décodage ({rt.phase})")

        # --- ⚠️ 6. LE TEST D'ALIGNEMENT (tâche 5), par le CONTENU — pas par la position ---------
        # La revue du P300 a établi qu'une assertion de POSITION laisse passer un double
        # filtrage : `filtfilt` est à phase nulle, sa réponse impulsionnelle équivalente est une
        # autocorrélation maximale au lag 0 — un `bandpass()` ajouté par erreur entre l'extraction
        # et le scorage laisse donc le PIC exactement au même échantillon. Or `ErrPModel` filtre
        # déjà en interne (composition sur `core.p300_decoder.build_pipe`). La SEULE assertion qui
        # ferme ce trou compare `rt._derniere_epoque_scoree` — ce que le runtime a RÉELLEMENT
        # envoyé au modèle — au CONTENU de la tranche brute du tampon, échantillon par échantillon.
        #
        # ⚠️ Correction de revue (tâche 5, tour 1) : la fixture d'origine plantait 42.0 IDENTIQUE
        # sur les 8 voies. Une valeur RÉPÉTÉE rend `np.array_equal` aveugle à un échange de deux
        # colonnes (deux voies interverties restent, valeur pour valeur, la tranche attendue) —
        # le test tenait sa promesse sur la position, la forme et l'absence de traitement, PAS sur
        # l'ordre des voies, malgré ce que son propre message affirmait déjà. Une valeur DISTINCTE
        # par voie referme ce trou (preuve rouge-puis-vert : rapport de tâche 5, tour de
        # correction 1).
        #
        # Un pic planté à un instant CONNU, une valeur DISTINCTE par voie (pas un scalaire répété,
        # cf. ⚠️ ci-dessus) dans un tampon par ailleurs nul.
        fs = 250.0
        n_pre, n_post = int(round(ERRP_PRE_S * fs)), int(round(ERRP_EPOCH_S * fs))
        t0 = 1000.0
        ts = np.arange(t0, t0 + 4.0, 1.0 / fs)
        eeg = np.zeros((len(ts), 8))
        instant = t0 + 2.0
        i_pic = int(np.searchsorted(ts, instant))
        eeg[i_pic, :] = np.arange(1, 9) * 10.0   # 10, 20, ..., 80 : une valeur PAR VOIE, qu'aucun
        #                                           calcul ne produit ni par hasard ni par permutation

        # ⚠️ Correction de revue (tour 2) : par `tick`, pas par un appel direct à
        # `_traiter_feedback`. Cette assertion est présentée comme LE test du sous-système ; en
        # court-circuitant `tick` -> `_run_step` -> `markers_murs` -> filtrage de l'événement,
        # elle ne pouvait rien dire de la couche qui FOURNIT `ts`. Une mutation dans `_run_step`
        # qui passerait `lsl_ts` en 2ᵉ argument décalerait CHAQUE époque de 0,7 à 1,0 s — le
        # défaut exact que cette assertion existe pour attraper — et restait verte.
        moteur.recent, moteur.recent_ts = eeg, ts
        moteur._lots = [[marqueur(instant)]]
        rt.tick(moteur, lsl_ts=instant + 0.8, now=12.0)   # lsl_ts VOLONTAIREMENT différent

        # UNE assertion qui épingle position, forme, ordre des voies ET absence de traitement — les
        # QUATRE, désormais que la fixture est distincte par voie (cf. ⚠️ ci-dessus) : un échange de
        # deux colonnes changerait le contenu comparé, `np.array_equal` deviendrait faux.
        chk(np.array_equal(rt._derniere_epoque_scoree, eeg[i_pic - n_pre:i_pic + n_post]),
            "⚠️ ALIGNEMENT : l'époque constituée par le runtime est EXACTEMENT la tranche brute du "
            "tampon — même position, même forme, même ordre de voies, et AUCUN traitement appliqué "
            "en chemin (un filtrage ajouté ici laisserait le pic au même échantillon, un échange de "
            "deux voies laisserait passer une fixture à valeur unique répétée — ni l'un ni l'autre "
            "ne passe celle-ci, à valeur distincte par voie)")
        chk(rt._out.lignes[-1][-1] == instant,
            f"...et l'époque prélevée AUTOUR de `ts` est publiée AVEC `ts` : le chemin complet, "
            f"du marqueur mûr à l'échantillon LSL, tient sur le MÊME instant "
            f"({rt._out.lignes[-1][-1]} attendu {instant}, lsl_ts valait {instant + 0.8})")

        # --- ⚠️ PREUVE ROUGE-PUIS-VERT : le repos se mesure comme l'ÉPOQUE — même
        # représentation (tour 1) ET même longueur de fenêtre (tour 2) --------------------------
        # UN SEUL tampon continu de 20 s, portant une dérive lente ORDINAIRE. C'est la seule
        # configuration qui existe en séance, et c'est ce qui rend cette preuve capable de voir
        # les DEUX défauts à la fois :
        #   · si `_rest_step` FILTRE (`engine.acq.sigma_from_block`) alors que l'époque est
        #     brute, sa référence s'effondre (le filtre retire la dérive) et l'époque SAINE
        #     ci-dessous est rejetée à tort — c'était le défaut du tour 1 ;
        #   · si `_rest_step` mesure sur `engine.recent` ENTIER (5,0 s) alors que l'époque fait
        #     0,9 s, sa référence est GONFLÉE par la dérive (σ croît avec la fenêtre) et le
        #     CLIGNEMENT ci-dessous n'est plus rejeté — c'était le défaut du tour 2.
        # ⚠️ L'ancienne fixture donnait au repos et à l'époque deux tampons DISTINCTS, taillés
        # chacun à sa propre échelle, avec la dérive RENORMALISÉE sur chacun : les deux supports
        # portaient donc, par construction, la MÊME amplitude de dérive — le seul cas où le biais
        # de support disparaît. L'effet à démontrer était neutralisé dans la fixture au lieu
        # d'être testé. Ici, il n'y a qu'un tampon : le repos y glisse comme le moteur le ferait,
        # et les époques en sont des tranches.
        from scipy.signal import butter, filtfilt

        def sous_5hz(n, fs, rng, amp_uv, ref_n):
            """Dérive lente ORDINAIRE (PAS un clignement) : marche aléatoire lissée sous
            ~0,5 Hz — exactement ce qu'un passe-bande 5-40 Hz retire, artefact ou pas.

            ⚠️ `ref_n` : l'amplitude est calibrée sur une fenêtre de CETTE longueur, jamais sur
            le tampon entier. C'est ce qui donne au chiffre un sens lisible (« 20 µV de σ sur
            5 s ») et, surtout, ce qui interdit de renormaliser la dérive tampon par tampon — le
            geste exact par lequel l'ancienne fixture effaçait le biais qu'elle prétendait
            mesurer.
            """
            marche = np.cumsum(rng.normal(0.0, 1.0, n))
            b, a = butter(2, 0.5 / (fs / 2.0), btype="low")
            lisse = filtfilt(b, a, marche)
            lisse -= lisse.mean()
            pas = max(1, ref_n // 4)
            sigmas = [lisse[i:i + ref_n].std() for i in range(0, max(1, n - ref_n), pas)]
            return lisse * (amp_uv / (float(np.median(sigmas)) + 1e-9))

        def bruit_avec_derive(n, fs, rng, drift_uv, ref_n):
            """EEG plausible : bruit large bande faible, un peu d'alpha, et une dérive lente
            COMMUNE aux 8 voies (le cas d'une référence qui dérive — et le cas déterministe :
            un tirage par voie ferait dépendre le verdict de la voie la moins bruitée)."""
            t = np.arange(n) / fs
            X = rng.normal(0.0, 2.0, (n, 8))
            X += (0.7 * np.sin(2 * np.pi * 10 * t + rng.uniform(0, 2 * np.pi)))[:, None]
            return X + sous_5hz(n, fs, rng, drift_uv, ref_n)[:, None]

        n_keep = 1250        # `EngineServer.keep` aujourd'hui : 5,0 s à 250 Hz (cf. server.py)
        n_epoque = int(round(ERRP_PRE_S * fs)) + int(round(ERRP_EPOCH_S * fs))   # 225 = 0,9 s
        rng_derive = np.random.default_rng(7)
        n_continu = int(20.0 * fs)
        continu = bruit_avec_derive(n_continu, fs, rng_derive, drift_uv=20.0, ref_n=n_keep)
        ts_continu = 200.0 + np.arange(n_continu) / fs

        moteur_derive = _FauxMoteur(continu[:n_keep], ts_continu[:n_keep])
        rt2 = ErrPRuntime(SPEC, values, moteur_derive)
        rt2._out = _FauxPublieur()
        rt2._opened = True
        rt2.begin_rest(now=0.0, warmup_s=0.0, duration_s=2.0)
        # Le repos GLISSE dans le même tampon, 0,2 s par pas — exactement ce que fait la boucle
        # du moteur (`period_s()`), et ce qui donne son sens au mot « médiane ».
        for k in range(11):
            fin = n_keep + int(k * 0.2 * fs)
            moteur_derive.recent = continu[fin - n_keep:fin]
            moteur_derive.recent_ts = ts_continu[fin - n_keep:fin]
            rt2.tick(moteur_derive, lsl_ts=float(ts_continu[fin - 1]) + 0.8, now=0.2 * k)
        chk(rt2.phase == "running",
            f"repos conclu (dérive ordinaire comprise) pour la preuve rouge-puis-vert ({rt2.phase})")

        # La suite du MÊME tampon, à 4 s plus loin : « juste un autre instant de la même séance ».
        fin = n_keep + int(4.0 * fs)
        fenetre = slice(fin - n_keep, fin)
        moteur_derive.recent_ts = ts_continu[fenetre]
        t_saine = float(ts_continu[fin - n_epoque - 10])
        moteur_derive.recent = continu[fenetre]
        moteur_derive._lots = [[marqueur(t_saine)]]
        rt2.tick(moteur_derive, lsl_ts=t_saine + 0.8, now=5.0)
        e_derive, _s_derive, _seuil_derive, art_derive, _t_derive = rt2._out.lignes[-1]
        chk(art_derive == 0,
            f"⚠️ une époque SAINE (dérive ORDINAIRE, rien d'anormal) n'est PAS rejetée à tort — "
            f"avec un repos FILTRÉ contre une époque brute (défaut du tour 1), sa référence "
            f"s'effondre et le même scénario rejetait 30 fois sur 30 (artefact publié={art_derive})")
        chk(e_derive in (0, 1),
            f"...et un VRAI verdict sort (score comparé au seuil), pas un -1 déguisé ({e_derive})")

        # …et le MÊME tampon, avec un clignement franc injecté DANS l'époque : lui doit être
        # rejeté. C'est l'assertion que le support gonflé faisait tomber — mesuré hors dépôt sur
        # 20 séances synthétiques : à 150 µV crête, 9 % de rejet avec `engine.recent` entier
        # contre 100 % une fois borné à la longueur d'une époque.
        t_clign = float(ts_continu[fin - n_epoque - 300])
        i_clign = int(np.searchsorted(ts_continu, t_clign))
        tc = np.arange(n_epoque) / fs
        bosse = 150.0 * np.exp(-0.5 * ((tc - tc[n_epoque // 2]) / 0.12) ** 2)
        contamine = continu.copy()
        n_pre_e = int(round(ERRP_PRE_S * fs))
        contamine[i_clign - n_pre_e:i_clign - n_pre_e + n_epoque] += bosse[:, None]
        moteur_derive.recent = contamine[fenetre]
        moteur_derive._lots = [[marqueur(t_clign)]]
        rt2.tick(moteur_derive, lsl_ts=t_clign + 0.8, now=5.5)
        e_clign, _s_clign, _seuil_clign, art_clign, _t_clign = rt2._out.lignes[-1]
        chk(art_clign == 1 and e_clign == -1,
            f"⚠️ SUPPORT : un clignement franc (150 µV crête) DANS le même tampon continu EST "
            f"rejeté — mesurer le repos sur `engine.recent` entier (5,0 s) au lieu d'une époque "
            f"(0,9 s) gonfle sa référence de ×2,0 sur une dérive lente, et le laissait passer "
            f"avec un verdict plausible et `artifact = 0` (publié : error={e_clign}, "
            f"artifact={art_clign})")

        # --- ⚠️ Panne n°9 : une voie MORTE au repos ne produit pas une référence, mais un refus -
        # σ_repos = 0 sur une voie donne un seuil de `4,0 × 0 = 0` : TOUTE époque de la séance
        # serait écartée, et le flux publierait `-1` en boucle. Sans ce refus, l'alarme de la
        # panne n°8 le dirait UNE fois, puis plus rien.
        morte = continu[:n_keep].copy()
        morte[:, 3] = 42.0          # voie 3 bloquée sur une constante : électrode arrachée
        moteur_mort = _FauxMoteur(morte, ts_continu[:n_keep])
        rt_mort = ErrPRuntime(SPEC, values, moteur_mort)
        rt_mort._out = _FauxPublieur()
        rt_mort._opened = True
        rt_mort.begin_rest(now=0.0, warmup_s=0.0, duration_s=0.0)
        capture_morte = io.StringIO()
        with redirect_stdout(capture_morte):
            rt_mort.tick(moteur_mort, lsl_ts=300.0, now=0.0)
            rt_mort.tick(moteur_mort, lsl_ts=300.2, now=0.2)   # la 2e fois ne se répète pas
        texte_mort = capture_morte.getvalue()
        print(texte_mort, end="")
        chk(rt_mort.phase == "rest" and rt_mort._sigmas_repos is None,
            f"une voie à σ NUL empêche le repos de conclure : pas de référence, pas de décodage "
            f"({rt_mort.phase}, sigmas={rt_mort._sigmas_repos})")
        chk(texte_mort.count("INEXPLOITABLE") == 1 and "[3]" in texte_mort,
            f"...et l'étudiant l'apprend UNE fois, avec la VOIE nommée — pas 5 fois par seconde "
            f"({texte_mort.strip()!r})")

        # --- Le sur-rejet doit être DÉTECTABLE (panne n°8) : compteur exposé, avertissement dit
        # UNE fois, jamais avant le plancher d'échantillons -------------------------------------
        rt3 = ErrPRuntime(SPEC, values, moteur)

        rt3._epoques_vues = rt3._artefacts = _TAUX_REJET_MIN_ECHANTILLONS - 1   # 100 % de rejet…
        capture_bas = io.StringIO()
        with redirect_stdout(capture_bas):
            rt3._verifie_taux_rejet()
        chk(not rt3._rejet_eleve_dit and capture_bas.getvalue() == "",
            f"...mais SOUS le plancher de {_TAUX_REJET_MIN_ECHANTILLONS} échantillons, même à "
            f"100 % de rejet : PAS d'alarme, un si petit effectif est du bruit, pas un diagnostic")

        rt3._epoques_vues, rt3._artefacts = 20, 3   # 15 % : un clignement occasionnel, plausible
        rt3._verifie_taux_rejet()
        chk(not rt3._rejet_eleve_dit,
            f"un taux de 15 % ne déclenche RIEN ({rt3._artefacts}/{rt3._epoques_vues})")

        rt3._epoques_vues, rt3._artefacts = 20, 12   # 60 % : au-delà du palier (0,5)
        capture_haut = io.StringIO()
        with redirect_stdout(capture_haut):
            rt3._verifie_taux_rejet()
        texte_haut = capture_haut.getvalue()
        print(texte_haut, end="")
        chk(rt3._rejet_eleve_dit and "taux de rejet" in texte_haut and "12/20" in texte_haut,
            f"un taux de 60 % déclenche l'alarme, avec le compte EXACT dans le message "
            f"({texte_haut.strip()!r})")

        rt3._epoques_vues, rt3._artefacts = 40, 30   # encore pire : l'alarme ne doit PAS se répéter
        capture_repete = io.StringIO()
        with redirect_stdout(capture_repete):
            rt3._verifie_taux_rejet()
        chk(capture_repete.getvalue() == "",
            "...mais elle ne se répète pas : dite UNE fois par session, pas à chaque nouvel "
            "artefact, sans quoi elle noierait le terminal exactement comme le mode qu'elle "
            "dénonce noie le flux de -1")

        etat3 = rt3.state()
        chk(etat3["epoques_vues"] == 40 and etat3["artefacts"] == 30
            and etat3["taux_rejet"] == 0.75,
            f"state() expose le taux de rejet CALCULÉ, pas seulement les deux compteurs bruts "
            f"({etat3['epoques_vues']}, {etat3['artefacts']}, {etat3['taux_rejet']})")

        etat_vide = ErrPRuntime(SPEC, values, moteur).state()
        chk(etat_vide["taux_rejet"] is None,
            f"...et un mode qui n'a encore rien vu affiche None, pas 0 (qui affirmerait « aucun "
            f"rejet » au lieu de « rien mesuré ») ({etat_vide['taux_rejet']})")
    finally:
        errp_models.modeles_disponibles = vrai_dispo
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[errp] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
