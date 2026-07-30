"""Mode Motor Imagery : quelle imagerie motrice l'utilisateur produit. BCI **active**.

Le décodage est dans `core/mi_decoder.py` (CSP + LDA). Ici on décrit le MODE : ce qui se règle,
ce qui se publie, et ce qu'il faut avoir avant de pouvoir décoder — à savoir un modèle ENTRAÎNÉ.

C'est la différence de nature avec le SSVEP : la CCA n'apprend rien, le MI si. Sans modèle, ce
mode ne démarre pas, et il le DIT. Un mode qui démarrerait sans modèle ne lèverait aucune erreur,
publierait des probabilités et ne déciderait jamais rien.

⚠️ Un modèle est propre à UNE personne. Les probabilités d'un modèle entraîné sur quelqu'un
d'autre sont plausibles et fausses — le pire des deux mondes.

⚠️ Le moteur ne rend AUCUN stimulus, et le MI n'en a pas besoin : il est endogène. L'application
cliente n'a rien à afficher pour que le décodage fonctionne.

Autotest :
    python src/core/modes/mi.py
"""

import os as _os
import sys as _sys
import time as _time
from collections import Counter, deque

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (MI_MIN_VOTES, MI_PROB_MIN, MI_VOTE_LEN,  # noqa: E402
                         SSVEP_WARMUP_S, use_utf8_console)
import numpy as np  # noqa: E402

from core import mi_models  # noqa: E402
from core.lsl_io import DecodedMIPublisher, mi_channel_labels, stream_name  # noqa: E402
from core.mi_decoder import MIDecoder  # noqa: E402
from core.modes.contract import ModeSpec, Param, Rest, validate  # noqa: E402
from core.modes.runtime import ModeRuntime  # noqa: E402

MI_DECODE_HZ = 5.0     # cadence de décodage — la même que le SSVEP, pour que les deux se lisent pareil


class MIRuntime(ModeRuntime):
    """Charge un modèle, glisse une fenêtre de 2 s, vote, publie. Aucun plancher à mesurer.

    Pourquoi pas de plancher, alors que le SSVEP en mesure un : ici la référence est APPRISE
    pendant la calibration, elle n'est pas un niveau de bruit du jour. Le mode garde en revanche
    la CHAUFFE : l'offset DC de l'Unicorn dérive après ouverture de session, et le MI lit C3/C4,
    précisément les voies qui saturent.

    Pourquoi un vote glissant : une décision par fenêtre serait beaucoup trop instable pour
    piloter quoi que ce soit. On exige `min_votes` fenêtres d'accord sur les `vote_len`
    dernières — c'est le lissage qui existait déjà dans le pilote pygame, aux mêmes valeurs.
    """

    def __init__(self, spec, params, engine):
        super().__init__(spec, params, engine)
        self._out = None
        self._decoded = None
        self._last_log = 0.0
        self.model, raison = mi_models.charger(params["model"])
        if self.model is None:
            # On lève ICI plutôt que de démarrer un mode muet. `validate` a déjà écarté le cas
            # « aucun modèle » ; il reste celui du fichier effacé entre la validation et le
            # démarrage, que seul le moteur peut voir.
            raise ValueError(raison)
        self.decoder = MIDecoder(self.model, prob_min=float(params["prob_min"]))
        self._votes = deque(maxlen=int(params["vote_len"]))

    @property
    def classes(self):
        return list(self.model.labels)

    def _open(self):
        # Le flux est créé tout de suite, comme pour le SSVEP : un client qui cherche le flux au
        # lancement et ne le trouve pas abandonne (`resolve_byprop` a un délai fini).
        self._out = DecodedMIPublisher(
            self.classes, prob_min=float(self.params["prob_min"]),
            votes=(int(self.params["min_votes"]), int(self.params["vote_len"])),
            instance=self.engine.instance)

    def _close(self):
        self._out = None

    def _reset_rest(self):
        self._votes.clear()
        self._decoded = None

    def period_s(self):
        return 1.0 / MI_DECODE_HZ

    def output(self):
        return self._decoded

    def _rest_step(self, engine, now):
        """Rien à mesurer : le repos de ce mode dure 0 s, seule la chauffe compte.

        On rend True dès que l'échéance est passée. `begin_rest` a posé `_rest_until = now` au
        premier pas de la phase, donc c'est vrai immédiatement — le mode passe à « running » au
        tick suivant, sans avoir rien collecté.
        """
        if now < self._rest_until:
            return False
        print(f"[mi] modèle « {_os.path.basename(self.params['model'])} » — décodage en cours "
              f"sur {stream_name('decoded_mi')} ({', '.join(self.classes)})")
        self.rest_report = {"kind": "mi", "model": _os.path.basename(self.params["model"]),
                            "classes": self.classes}
        return True

    def _run_step(self, engine, lsl_ts):
        window = engine.acq.motor_window(engine.recent)
        if window is None:
            return
        # `self.decoder.scores(window)` seul, PAS `.classify()` : ce dernier renvoie None dans
        # DEUX cas différents — probabilité sous le seuil, OU classe gagnante = REPOS — et les
        # confond. Ici REPOS est une classe ORDINAIRE du vote, exactement comme GAUCHE et
        # DROITE : elle peut gagner et se publier avec SON indice. Seul un écart sous le seuil
        # produit None. Sans cette distinction, l'indice de REPOS est INATTEIGNABLE : le flux
        # répondrait « je ne sais pas » quand le modèle est certain à 99 % que la personne se
        # repose — exactement ce que `DecodedMIPublisher` interdit (cf. sa docstring : « -1 et
        # la classe REPOS sont deux choses différentes »).
        scores = self.decoder.scores(window)
        meilleure = max(scores, key=scores.get)
        label = meilleure if scores[meilleure] >= self.decoder.prob_min else None
        self._votes.append(label)

        # Le vote peut désigner None : « aucune fenêtre récente n'était assez sûre » est une
        # réponse, et c'est celle qu'il faut publier plutôt qu'un second choix inventé.
        gagnant, compte = Counter(self._votes).most_common(1)[0]
        if gagnant is None or compte < int(self.params["min_votes"]):
            retenu = None
        else:
            retenu = gagnant

        probas = [float(scores.get(c, 0.0)) for c in self.classes]
        if retenu is None:
            self._publish(-1, 0.0, probas, lsl_ts)
        else:
            self._publish(self.classes.index(retenu), float(scores[retenu]), probas, lsl_ts)

    def _publish(self, index, confidence, probas, lsl_ts):
        if self._out is not None:
            self._out.push(index, confidence, probas, lsl_ts)
        self._decoded = {
            "intent_index": int(index),
            "label": self.classes[index] if index >= 0 else "",
            "confidence": round(float(confidence), 3),
            "probas": {c: round(p, 3) for c, p in zip(self.classes, probas)},
            "threshold": float(self.params["prob_min"]),
        }
        self._log(index, probas)

    def _log(self, index, probas):
        """Trace la décision ~1×/s : pendant une séance on veut voir ce qui est décodé sans
        dépendre d'un troisième terminal branché au bon moment."""
        now = _time.perf_counter()
        if now - self._last_log < 1.0:
            return
        self._last_log = now
        detail = "  ".join(f"{c} p={p:.2f}" for c, p in zip(self.classes, probas))
        verdict = (f"— (vote non conclu, seuil {self.params['prob_min']:g})" if index < 0
                   else f"INTENTION {self.classes[index]}")
        print(f"[mi] {verdict:<34} {detail}")


def _channels(params):
    """Les voies dépendent des classes DU MODÈLE choisi, pas d'une liste figée.

    Un modèle entraîné à deux classes publierait quatre voies au lieu de cinq. Lire le modèle
    est le seul moyen de ne pas mentir dans les métadonnées ; si le modèle est illisible, on rend
    les classes par défaut plutôt que de lever — cette fonction est appelée par l'affichage.
    """
    chemin = params.get("model")
    modele = mi_models.charger(chemin)[0] if chemin else None
    classes = list(modele.labels) if modele is not None else ["GAUCHE", "DROITE", "REPOS"]
    return mi_channel_labels(classes)


SPEC = ModeSpec(
    id="mi",
    label="Motor Imagery",
    family="actif",
    summary="Imagination d'un mouvement main gauche / main droite (CSP+LDA).",
    status="moteur",
    params=(
        Param(
            key="model",
            label="Modèle entraîné",
            kind="choice",
            # Le lambda est délibéré : il résout `modeles_disponibles` À L'APPEL. Lier la
            # fonction directement figerait la référence à l'import, et l'autotest ne pourrait
            # plus rediriger la recherche vers un dossier temporaire sans toucher à `data/`.
            choices_fn=lambda: mi_models.modeles_disponibles(),
            help="Le modèle produit par une calibration MI, propre à TA personne — celui de "
                 "quelqu'un d'autre donne des probabilités plausibles et fausses. Aucun modèle "
                 "dans la liste ? Lance une calibration : "
                 "`python src/research/mi_calibrate.py`.",
        ),
        Param(
            key="prob_min",
            label="Probabilité minimale",
            kind="float",
            default=MI_PROB_MIN,
            min=0.34, max=0.99,
            help="En dessous, la fenêtre ne vote pour personne. Monter ce seuil rend le mode "
                 "plus prudent : moins d'intentions émises, mais moins de fausses.",
        ),
        Param(
            key="vote_len",
            label="Fenêtres du vote",
            kind="int",
            default=MI_VOTE_LEN,
            min=1, max=15,
            help="Sur combien de fenêtres récentes on vote. Le MI est plus bruité que le SSVEP, "
                 "d'où un lissage un peu plus long. À 5 Hz, 5 fenêtres = 1 seconde.",
        ),
        Param(
            key="min_votes",
            label="Votes concordants",
            kind="int",
            default=MI_MIN_VOTES,
            min=1, max=15,
            constraints=("votes_atteignables",),
            help="Combien de ces fenêtres doivent être d'accord pour émettre une intention. "
                 "En demander plus retarde la décision et la rend plus sûre. Ne peut pas "
                 "dépasser « Fenêtres du vote » : au-delà, aucun vote ne peut plus jamais "
                 "aboutir, et le mode ne décide plus rien — en silence.",
        ),
    ),
    rest=Rest(
        warmup_s=SSVEP_WARMUP_S,
        duration_s=0.0,
        instruction="Le casque se stabilise — reste immobile.",
    ),
    calibration=None,   # la calibration est la moitié B ; le mode consomme un modèle déjà entraîné
    stream="decoded_mi",
    channels_fn=_channels,
    runtime_cls=MIRuntime,
)


def _selftest():
    """Le mode de bout en bout, sur un modèle entraîné à la volée et du signal FABRIQUÉ.

    On ne juge PAS la justesse du décodage : de l'ERD synthétique n'a pas de sens
    physiologique ici. On vérifie le CONTRAT — que le mode refuse de démarrer sans modèle, que
    la chauffe précède le décodage, que le vote retarde bien la première intention, et qu'une
    décision publiée porte un index dans les bornes.
    """
    import shutil
    import tempfile

    from core.acquisition import UnicornAcquisition
    from core.mi_decoder import MI_LABELS, MIModel, synth_mi_trial

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _FauxPublieur:
        def __init__(self):
            self.lignes = []

        def push(self, index, confidence, probas, lsl_ts=None):
            self.lignes.append((index, confidence, list(probas)))

    class _FauxMoteur:
        def __init__(self, recent):
            self.acq = UnicornAcquisition(synthetic=True)
            self.instance = "selftest"
            self.recent = recent

    # Capturée AVANT le `try` : si `MIModel.fit` levait à l'intérieur, un `finally` qui la
    # restaure aurait lu une variable jamais assignée (`UnboundLocalError`), masquant l'erreur
    # réelle ET sautant le nettoyage du dossier temporaire.
    vrai_dispo = mi_models.modeles_disponibles
    dossier = tempfile.mkdtemp(prefix="mi_mode_")
    try:
        # Un modèle jetable, entraîné sur de l'ERD synthétique.
        rng = np.random.default_rng(0)
        epochs, y = [], []
        for label in MI_LABELS:
            for _ in range(8):
                epochs.append(synth_mi_trial(label, rng=rng))
                y.append(label)
        chemin = _os.path.join(dossier, "mi_model.joblib")
        MIModel(fs=250.0).fit(np.asarray(epochs), np.asarray(y)).save(chemin)

        # On redirige la RECHERCHE de modèles vers un dossier temporaire, en remplaçant la
        # fonction dans son module. C'est possible — et propre — parce que le contrat appelle
        # `mi_models.modeles_disponibles()` à travers un lambda : la résolution a lieu à
        # l'appel, pas à l'import. Aucun `data/` n'est touché, aucun objet gelé n'est mutilé.

        # 1. Sans modèle du tout, le mode REFUSE et dit comment en obtenir un.
        vide = _os.path.join(dossier, "aucun")
        _os.makedirs(vide, exist_ok=True)
        mi_models.modeles_disponibles = lambda dossier=vide: vrai_dispo(dossier)
        _v, raison = validate(SPEC, {})
        chk(raison is not None and "aucun choix disponible" in raison
            and "calibration" in raison,
            f"sans modèle, le mode refuse en disant quoi faire ({raison})")

        # 2. Avec un modèle, les défauts sont valides et le plus récent est pris.
        mi_models.modeles_disponibles = lambda d=dossier: vrai_dispo(d)
        values, raison = validate(SPEC, {})
        chk(values is not None, f"avec un modèle, les défauts passent ({raison})")
        chk(values["model"] == chemin, f"et c'est le modèle trouvé qui est pris ({values['model']})")
        chk(_channels(values) == ["intent_index", "confidence",
                                  "p_GAUCHE", "p_DROITE", "p_REPOS"],
            f"les voies viennent des classes DU MODÈLE ({_channels(values)})")

        bruit = rng.normal(0.0, 8.0, (int(5.0 * 250), 8))
        moteur = _FauxMoteur(bruit)
        rt = MIRuntime(SPEC, values, moteur)
        rt._out = _FauxPublieur()
        rt._opened = True
        chk(rt.phase == "warmup", "le MI commence par une chauffe")

        # 3. Chauffe puis décodage, sans plancher à mesurer.
        rt.begin_rest(now=0.0, warmup_s=0.0, duration_s=0.0)
        rt.tick(moteur, lsl_ts=0.0, now=0.1)
        rt.tick(moteur, lsl_ts=0.2, now=0.2)
        chk(rt.phase == "running", f"un repos de durée nulle passe tout de suite ({rt.phase})")
        chk(rt.rest_report and rt.rest_report["kind"] == "mi",
            f"et laisse un compte-rendu nommant le modèle ({rt.rest_report})")

        # 4. Le vote retarde la première intention : c'est le but.
        rt._votes.clear()
        rt._out.lignes.clear()
        for i in range(int(values["vote_len"])):
            moteur.recent = rng.normal(0.0, 8.0, (int(5.0 * 250), 8))
            rt.tick(moteur, lsl_ts=1.0 + i, now=1.0 + i)
        chk(len(rt._out.lignes) == int(values["vote_len"]),
            f"une décision publiée par fenêtre ({len(rt._out.lignes)})")
        index, _conf, probas = rt._out.lignes[-1]
        chk(-1 <= index < len(MI_LABELS), f"index d'intention dans les bornes ({index})")
        chk(len(probas) == len(MI_LABELS), f"une probabilité par classe ({probas})")
        chk(abs(sum(probas) - 1.0) < 1e-3, f"et elles somment à 1 ({sum(probas):.3f})")

        premiere = rt._out.lignes[0][0]
        chk(premiere == -1,
            f"la toute première fenêtre ne peut pas conclure — le vote exige "
            f"{values['min_votes']} accords (index={premiere})")

        # 5. REPOS est une classe ORDINAIRE du vote, pas un synonyme de « je ne sais pas ».
        # `MIDecoder.classify()` la traite comme un cas d'arrêt (comme une proba sous le
        # seuil) ; `_run_step` ne doit PLUS s'en servir pour cette raison précise. On fixe ICI
        # les scores rendus par le décodeur, plutôt que d'espérer qu'un signal synthétique y
        # mène : sur seulement 8 essais/classe, un modèle jetable ne classe pas forcément une
        # fenêtre de repos fraîche comme REPOS (question de justesse du décodage, que ce
        # fichier ne juge PAS — cf. docstring de `_selftest`). Ce qu'on vérifie ici est le
        # CONTRAT du runtime : quand le décodeur est certain de REPOS, le mode publie SON
        # indice, jamais -1. Le `chk(-1 <= index < len(MI_LABELS))` du bloc précédent passe
        # dans les DEUX mondes (REPOS atteignable ou non) ; celui-ci fabrique la situation au
        # lieu d'espérer qu'elle survienne.
        vrais_scores = rt.decoder.scores
        rt.decoder.scores = lambda window: {"GAUCHE": 0.05, "DROITE": 0.05, "REPOS": 0.90}
        try:
            rt._votes.clear()
            rt._out.lignes.clear()
            for i in range(int(values["vote_len"])):
                moteur.recent = rng.normal(0.0, 8.0, (int(5.0 * 250), 8))
                rt.tick(moteur, lsl_ts=20.0 + i, now=20.0 + i)
        finally:
            rt.decoder.scores = vrais_scores
        index_repos, conf_repos, probas_repos = rt._out.lignes[-1]
        chk(index_repos == MI_LABELS.index("REPOS"),
            f"un décodeur certain de REPOS publie SON indice, jamais -1 (index={index_repos}, "
            f"probas={probas_repos})")
        chk(conf_repos == 0.90,
            f"avec la confiance réellement rapportée par le décodeur, pas une confiance nulle "
            f"({conf_repos:.2f})")

        # 6. Le contrat du mode.
        chk(SPEC.rest.duration_s == 0.0 and SPEC.rest.warmup_s == SSVEP_WARMUP_S,
            f"chauffe obligatoire, aucun plancher ({SPEC.rest})")
        chk(SPEC.stream == "decoded_mi" and SPEC.status == "moteur",
            "le mode publie decoded_mi et tourne dans le moteur")
        chk(all(p.affecte_decodage for p in SPEC.params),
            "tous les réglages du MI affectent le décodage : en changer un refait le mode")

        # 7. min_votes ne peut pas dépasser vote_len : au-delà, aucun vote ne peut plus jamais
        # aboutir, et le mode ne décide plus rien — en silence, la panne type de ce produit.
        _v, raison = validate(SPEC, {"vote_len": 3, "min_votes": 10})
        chk(raison is not None and "3" in raison and "10" in raison,
            f"exiger plus de votes que de fenêtres est refusé, en nommant les deux valeurs "
            f"({raison})")
    finally:
        mi_models.modeles_disponibles = vrai_dispo
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[mi] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
