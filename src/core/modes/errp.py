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

Quatre pannes bruyantes propres à ce mode (les trois premières — flux introuvable, marqueur trop
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

Autotest :
    python src/core/modes/errp.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (ERRP_ARTIFACT_RATIO, ERRP_EPOCH_S, ERRP_PRE_S,  # noqa: E402
                         SSVEP_WARMUP_S, use_utf8_console)
import numpy as np  # noqa: E402

from core import errp_models  # noqa: E402
from core.errp_decoder import epoch_from_stream  # noqa: E402
from core.modes.contract import Calib, ModeSpec, Param, Rest, validate  # noqa: E402
from core.modes.runtime import ModeRuntime  # noqa: E402


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
    """

    pre_s = ERRP_PRE_S      # attributs de CLASSE : `registry.check()` les compare à
    post_s = ERRP_EPOCH_S   # `marker_epoch_s` pour qu'aucune époque ne soit tronquée en silence

    def __init__(self, spec, params, engine):
        super().__init__(spec, params, engine)
        self._out = None
        self._decoded = None
        self.model, raison = errp_models.charger(params["model"])
        if self.model is None:
            # On lève ICI plutôt que de démarrer un mode muet. `validate` a déjà écarté le cas
            # « aucun modèle » ; il reste celui du fichier effacé entre la validation et le
            # démarrage, que seul le moteur peut voir — même garde que le P300 et le MI.
            raise ValueError(raison)
        desaccord = self._desaccord_geometrie(engine)
        if desaccord is not None:
            raise ValueError(desaccord)
        # Tâche 3 remplace cette ligne par un recalcul (`pick_threshold` sur un réglage
        # `tnr_target` exposé à l'étudiant) ; pour l'instant, le seuil APPRIS pendant la
        # calibration — celui que `ErrPModel.fit` a réglé pour une TNR par défaut.
        self.seuil = float(self.model.threshold_)
        self._sigmas_repos = None    # σ par voie mesuré au repos — la référence du rejet d'artefact
        self._echantillons = []      # les σ successifs mesurés PENDANT le repos, avant médiane
        self._epoques_perdues = 0    # marqueurs mûrs dont l'époque a quand même débordé du tampon
        self._artefacts = 0          # époques écartées : σ trop grand par rapport au repos
        self._marqueurs_chauffe = 0  # feedbacks jetés, reçus pendant la chauffe OU le repos
        self._chauffe_dite = False   # l'avertissement de chauffe/repos, une fois par repos

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

    def _open(self):
        # Le vrai `DecodedErrPPublisher` arrive à la tâche 4 : `core/lsl_io.py` ne le porte pas
        # encore, et ce mode n'est pas non plus dans `registry.MODES`. Ce runtime décode déjà de
        # bout en bout ; il ne publie nulle part tant qu'il n'est pas branché. `_selftest`
        # bouchonne `_out` directement, comme `p300.py` le fait déjà pour ses propres tests.
        self._out = None

    def _close(self):
        self._out = None

    def _reset_rest(self):
        self._sigmas_repos = None
        self._echantillons = []
        self._decoded = None
        self._chauffe_dite = False

    def output(self):
        return self._decoded

    def state(self):
        """Comme `ModeRuntime.state()`, plus les compteurs de ce que ce mode JETTE — le même
        filet que `P300Runtime.state()` : sans cette sortie, un client qui n'a pas la console
        ouverte au bon instant ne voit jamais combien d'époques ont été perdues ou écartées."""
        base = super().state()
        base["epoques_perdues"] = self._epoques_perdues
        base["artefacts"] = self._artefacts
        base["marqueurs_chauffe"] = self._marqueurs_chauffe
        return base

    def _rest_step(self, engine, now):
        bloc = engine.recent
        sig = engine.acq.sigma_from_block(bloc)
        if sig is None:
            return False
        self._echantillons.append(sig)
        if now < self._rest_until:
            return False
        self._sigmas_repos = np.median(np.asarray(self._echantillons), axis=0)
        print(f"[errp] repos mesuré ({len(self._echantillons)} fenêtres) — σ par voie : "
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
        self._marqueurs_chauffe += len(jetes)
        if not self._chauffe_dite:
            self._chauffe_dite = True
            print(f"[errp] {len(jetes)} marqueur(s) reçus pendant la CHAUFFE/le REPOS : jetés — "
                  f"l'offset DC du casque dérive encore et le repos n'a pas fini de mesurer son "
                  f"bruit de fond. Le premier feedback décodé sera le premier reçu APRÈS le repos.")

    def _run_step(self, engine, lsl_ts):
        for ts, marqueur in engine.markers_murs(self.spec.id, post_s=self.post_s):
            if marqueur.get("event") != "feedback":
                continue        # un événement inconnu s'ignore : le protocole grandira
            self._traiter_feedback(engine, ts, lsl_ts)

    def _traiter_feedback(self, engine, ts, lsl_ts):
        """Un feedback, un verdict — jamais de silence (cf. ⚠️ de la docstring du module)."""
        epoque = epoch_from_stream(engine.recent, engine.recent_ts, ts, engine.acq.fs,
                                   pre_s=self.pre_s, post_s=self.post_s)
        if epoque is None:
            self._epoques_perdues += 1
            self._publish(-1, 0.0, artefact=0, lsl_ts=lsl_ts)
            return
        if self._est_artefact(epoque):
            self._artefacts += 1
            self._publish(-1, 0.0, artefact=1, lsl_ts=lsl_ts)
            return
        score = float(np.ravel(self.model.score(epoque[None, ...]))[0])
        self._publish(1 if score >= self.seuil else 0, score, artefact=0, lsl_ts=lsl_ts)

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

    def _publish(self, error, score, artefact, lsl_ts):
        if self._out is not None:
            self._out.push(error, score, artefact, lsl_ts)
        self._decoded = {
            "error": int(error),
            "score": round(float(score), 3),
            "artefact": int(artefact),
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
    ),
    rest=Rest(
        warmup_s=SSVEP_WARMUP_S,   # 15 s : l'offset DC de l'Unicorn dérive après ouverture
        duration_s=8.0,            # même durée que le SSVEP : deux modes lancés ensemble PARTAGENT
        instruction="Repos : regarde l'écran, immobile — on mesure le bruit de fond de tes voies.",
    ),
    calibration=Calib(kind="natif",
                      reason="l'onset du feedback écran doit être horodaté à la frame"),
    # `stream`/`channels` restent VIDES à dessein : `DecodedErrPPublisher` (tâche 4) n'existe pas
    # encore dans `core/lsl_io.py`, et ce mode n'est pas non plus dans `registry.MODES` — brancher
    # les deux est le travail de la tâche 4 (qui modifie CE fichier à nouveau, cf. le plan du
    # chantier). `status="moteur"` reflète déjà ce que ce mode EST : un runtime qui décode de bout
    # en bout, pas encore un flux qu'un étudiant peut lire sur le réseau.
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

        def push(self, error, score, artefact, lsl_ts=None):
            self.lignes.append((error, score, artefact, lsl_ts))

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
        chk({p.key for p in SPEC.params} == {"model"},
            "seul le modèle se règle pour l'instant — tnr_target arrive à la tâche 3")

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
        chk(SPEC.status == "moteur" and SPEC.stream is None,
            "le mode est déjà « moteur » ; son flux et ses voies restent à brancher à la tâche 4 "
            "(DecodedErrPPublisher, core/lsl_io.py, registry.py)")

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
        ErrPModel(fs=125.0).save(autre_geo)
        essai = dict(values, model=autre_geo)
        try:
            ErrPRuntime(SPEC, essai, moteur)
            refus_geo = None
        except ValueError as e:
            refus_geo = str(e)
        chk(refus_geo is not None and "fs" in refus_geo and "125" in refus_geo,
            f"un modèle entraîné sur une AUTRE géométrie d'époque est refusé au démarrage, en "
            f"nommant l'écart ({refus_geo})")

        rt = ErrPRuntime(SPEC, values, moteur)
        rt._out = _FauxPublieur()
        rt._opened = True
        chk(rt.phase == "warmup", "l'ErrP commence par une chauffe")
        seuil_reel = rt.seuil
        chk(seuil_reel == float(modele.threshold_),
            f"le seuil de départ est celui APPRIS par la calibration ({seuil_reel})")

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
            f"...et le REPOS jette et compte lui aussi les feedbacks reçus pendant qu'il mesure "
            f"({rt._marqueurs_chauffe})")
        texte_chauffe = capture.getvalue()
        print(texte_chauffe, end="")   # rejoué : la capture ne doit pas rendre ce test muet
        chk(texte_chauffe.count("CHAUFFE") == 1,
            f"l'avertissement n'est dit qu'UNE fois pour toute la chauffe ET le repos "
            f"({texte_chauffe.count('CHAUFFE')} occurrence(s))")
        chk(rt._out.lignes == [],
            f"...et aucun des 3 feedbacks jetés n'a produit la moindre publication "
            f"({len(rt._out.lignes)})")

        # Le repos mesure son σ sur PLUSIEURS fenêtres avant de conclure (`_rest_until`) : on
        # avance jusqu'à ce qu'il tienne, sans qu'aucun marqueur ne traîne plus dans la file.
        moteur._lots = []
        for t in (2.0, 2.7, 3.5):
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
        t_reel = 105.0
        moteur._lots = [[marqueur(t_reel)]]
        rt.tick(moteur, lsl_ts=t_reel, now=4.0)
        chk(len(rt._out.lignes) == 1, f"le vrai modèle produit une ligne ({len(rt._out.lignes)})")
        err_reel, score_reel, art_reel, ts_reel = rt._out.lignes[-1]
        chk(err_reel in (-1, 0, 1), f"un index dans le contrat ({err_reel})")
        chk(art_reel == 0 and np.isfinite(score_reel),
            f"un feedback banal (bruit à l'échelle du repos) n'est PAS un artefact, et le score "
            f"est un nombre fini ({art_reel}, {score_reel})")
        chk(ts_reel == t_reel, f"l'horodatage publié est celui du FEEDBACK ({ts_reel})")
        chk(rt.output() == {"error": err_reel, "score": round(score_reel, 3), "artefact": 0},
            f"la sortie exposée à l'affichage reprend la même décision ({rt.output()})")

        # --- La logique score/seuil, sur un modèle à score CONNU -----------------------------
        espion = _ModeleScore(seuil_reel + 5.0)     # nettement AU-DESSUS du seuil
        rt.model = espion
        t = 106.0
        moteur._lots = [[marqueur(t)]]
        rt.tick(moteur, lsl_ts=t, now=4.5)
        chk(rt._out.lignes[-1] == (1, seuil_reel + 5.0, 0, t),
            f"score >= seuil -> error=1, avec le VRAI score et l'horodatage du feedback "
            f"({rt._out.lignes[-1]})")
        chk(espion.appels == 1, f"le modèle a bien été consulté une fois ({espion.appels})")

        espion2 = _ModeleScore(seuil_reel - 5.0)    # nettement SOUS le seuil
        rt.model = espion2
        t = 107.0
        moteur._lots = [[marqueur(t)]]
        rt.tick(moteur, lsl_ts=t, now=5.0)
        chk(rt._out.lignes[-1] == (0, seuil_reel - 5.0, 0, t),
            f"score < seuil -> error=0, jamais -1 : « correct » est une réponse à part entière, "
            f"pas une absence de verdict ({rt._out.lignes[-1]})")

        # --- Une époque PERDUE (mûre mais hors du tampon) publie -1, artefact=0, SANS consulter
        # le modèle -------------------------------------------------------------------------
        avant_perdues = rt._epoques_perdues
        rt.model = espion   # si jamais consulté, on le saurait (nouvel appel compté)
        appels_avant = espion.appels
        t_perdu = 5.0        # loin AVANT recent_ts[0] = 100.0 : hors du tampon
        moteur._lots = [[marqueur(t_perdu)]]
        rt.tick(moteur, lsl_ts=t_perdu, now=5.5)
        ligne = rt._out.lignes[-1]
        chk(ligne == (-1, 0.0, 0, t_perdu),
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
        rt.tick(moteur, lsl_ts=t_art, now=6.0)
        ligne = rt._out.lignes[-1]
        chk(ligne == (-1, 0.0, 1, t_art),
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
        rt.tick(moteur, lsl_ts=110.1, now=7.0)
        chk(len(rt._out.lignes) == avant_lignes + 2,
            f"deux feedbacks rapprochés publient DEUX verdicts, sans période réfractaire — elle "
            f"reste au démonstrateur pygame ({len(rt._out.lignes) - avant_lignes})")

        # --- Le flux ne se tait JAMAIS : autant de lignes publiées que de feedbacks ENVOYÉS ----
        # (1 réel + 1 score>=seuil + 1 score<seuil + 1 perdu + 1 artefact + 2 rapprochés = 7 ;
        # l'événement inconnu n'en fait PAS partie, il n'a jamais atteint `_traiter_feedback`.)
        chk(len(rt._out.lignes) == 7,
            f"un échantillon par feedback envoyé, quoi qu'il arrive ({len(rt._out.lignes)}/7)")

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
    finally:
        errp_models.modeles_disponibles = vrai_dispo
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[errp] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
