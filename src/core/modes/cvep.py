"""Mode c-VEP : quelle cible est fixée, lue dans le DÉCALAGE d'un même code, jamais dans une
fréquence. BCI **active** : l'utilisateur choisit une cible en la fixant, comme le SSVEP — mais
là où le SSVEP cherche une fréquence, le c-VEP cherche une PHASE dans une m-séquence.

Le décodage (corrélation par lag) est dans `core/cvep_decoder.py` ; la m-séquence et le plan des
cibles dans `core/cvep_code.py` (tous deux déménagés dans `core/` à la tâche 1 de ce chantier, le
modèle `data/cvep_model.npz` survivant intact). Ici on décrit le MODE : ce qui se règle, ce qui se
publie, et — le cœur de CE fichier — **où en est le code affiché en ce moment**, sans quoi aucune
corrélation ne veut rien dire.

⚠️ **Ce fichier est différent de son patron, `core/modes/p300.py`/`core/modes/errp.py`, et c'est le
point à comprendre avant de lire plus loin.** Le P300 et l'ErrP DÉCOUPENT une époque **autour** de
chaque marqueur — le marqueur délimite un événement discret (un flash, un feedback). Le c-VEP, lui,
décode **en continu sur une fenêtre glissante**, comme le SSVEP : ses marqueurs ne délimitent RIEN,
ils **tiennent une horloge**. Un programme séparé (`research/cvep_stimulus.py`, tâche 5 de ce
chantier) affiche le clignotement et publie un marqueur `{"mode":"cvep","event":"cycle",
"refresh":…}` à CHAQUE redémarrage de la m-séquence (toutes les 63 frames). Ce runtime reconstruit,
à tout instant `t_fin`, la position dans le code que ce marqueur implique : c'est la **phase**.
`SPEC.marker_epoch_s` (voir plus bas) en découle : il **dimensionne le tampon du moteur**, il ne
décrit **aucune époque** — si ce champ te fait chercher un `pre_s`/`post_s` comme chez le P300 ou
l'ErrP, tu ne le trouveras pas ici, et c'est voulu : `CVEPRuntime` n'expose délibérément PAS ces
deux attributs de classe, pour que `registry.check()` n'applique pas la logique de troncature
d'époque (`pre_s+post_s` contre `marker_epoch_s`) à un mode qui n'en a pas.

⚠️ **Le cœur de ce fichier est la distinction entre `None` et `0`.** `phase_a` rend `None` quand il
n'y a pas de phase connue, et `0` est une position VALIDE du code (la toute première frame de la
m-séquence). Les confondre ferait décoder sur une horloge fausse tout en publiant des corrélations
d'apparence parfaitement normale — la panne muette que ce projet existe pour éliminer. TROIS
chemins rendent `None`, chacun une panne muette s'il n'est pas traité (cf. `phase_a`) :
    1. aucun marqueur de cycle n'a JAMAIS été reçu (`maj_reference` jamais appelée) ;
    2. `t_fin` est ANTÉRIEUR au dernier marqueur connu (horloges en désaccord, ou un appel avant
       la toute première référence utile) — sans cette garde, `int(age * refresh) % code_len` sur
       un `age` négatif rend un entier PLAUSIBLE (le modulo Python est toujours positif), sans la
       moindre exception ;
    3. la référence est PÉRIMÉE : plus de `CVEP_PEREMPTION_CYCLES` cycles se sont écoulés sans
       nouveau marqueur. Continuer en « roue libre » au-delà a été écarté par la spec (cf. le
       commentaire de la constante, `core/config.py`) : une petite dérive d'horloge entre l'écran
       et le moteur s'accumule vite au regard d'un code qui ne fait que 63 frames.

⚠️ Comme le P300 et l'ErrP : un modèle est propre à UNE personne, et ce mode ne démarre pas sans
un modèle ENTRAÎNÉ pour la même raison qu'eux — les scores d'un modèle entraîné sur quelqu'un
d'autre sont plausibles et faux, le pire des deux mondes. `_charger`/`_modeles_disponibles`
ci-dessous sont **provisoires** : le catalogue multi-modèles (plusieurs fichiers horodatés, triés
du plus récent au plus ancien, comme `mi_models.py`/`p300_models.py`/`errp_models.py`) arrive avec
`core/cvep_models.py` à la tâche 3 de ce chantier. En attendant, un SEUL modèle existe par
construction (`CVEP_MODEL_PATH`, cf. tâche 1) : ces deux fonctions se contentent de dire s'il est
là ou pas, sans rien inventer sur d'éventuels autres fichiers.

⚠️ **Second refus, propre à ce mode, à ne pas confondre avec le premier** : même avec un modèle
présent et lisible, `maj_reference` refuse tout marqueur dont le rafraîchissement déclaré
s'écarte de plus de 1 Hz de celui auquel le modèle a été calibré. Le modèle est calibré à UN
rafraîchissement, et c'est l'ÉMETTEUR qui tient l'écran — le moteur ne peut pas le voir avant de
recevoir un marqueur. Sans cette garde : le décodage tourne, les scores restent honnêtes, et RIEN
ne se déclenche jamais — c'est la panne qui a coûté une séance au SSVEP (cf. `SSVEP_WARMUP_S`).

⚠️ **Ce que ce fichier NE fait PAS encore, délibérément.** Il tient l'horloge du code et refuse de
décoder quand il ne la connaît pas — mais il n'appelle jamais `CVEPDecoder.classify` : la fenêtre
glissante, la publication sur `decoded_cvep` et l'enregistrement dans `registry.MODES` sont le
travail de la tâche 4 de ce chantier. `__init__` construit quand même `self.plan`/`self.code` (via
`build_targets()`) et vérifie qu'ils s'accordent avec le modèle chargé — c'est la seule décision
qui devait être prise MAINTENANT : `phase_a` a besoin de `self.code_len`, et le prendre du modèle
sans jamais le confronter à ce que la config ACTUELLE construit aurait laissé un désaccord de
`CVEP_BITS` (config changée après une calibration) tout aussi silencieux que celui du
rafraîchissement.

Autotest :
    python src/core/modes/cvep.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (CVEP_BITS, CVEP_CHANNELS, CVEP_DECISION_CYCLES,  # noqa: E402
                         CVEP_MODEL_PATH, CVEP_N_TARGETS, CVEP_PEREMPTION_CYCLES,
                         SSVEP_WARMUP_S, use_utf8_console)

from core.cvep_code import build_targets  # noqa: E402
from core.cvep_decoder import CVEPModel  # noqa: E402
from core.modes.contract import Calib, ModeSpec, Param, Rest, validate  # noqa: E402
from core.modes.runtime import ModeRuntime  # noqa: E402

# Tolérance flottante sur `age * refresh`, juste avant de tronquer en frame entière dans
# `phase_a`. ⚠️ MESURÉ, pas de précaution en l'air : à `ref_ts=100.0` et `t_fin=100.0+63/60.0`
# (exactement un cycle plus tard, le cas même que le test de ce fichier vérifie), `age` vaut
# `1.0499999999999972` au lieu de `1.05` — l'ARRONDI binaire de `100.0 + 63/60.0 - 100.0`, jamais
# `1.05` exactement. `age * 60.0` rend alors `62.99999999999983`, et `int(...)` TRONQUE vers 62 au
# lieu de 63 : la phase calculée retombe sur 62 au lieu de 0, un décalage d'UNE frame entière au
# pire moment (juste au wrap du code). Même classe de bug, même ordre de grandeur, que
# `registry._EPS_S` (« 0.15 + 0.80 vaut 0.9500000000000001 en flottant ») — 1e-9 s n'a aucune
# commune mesure avec un échantillon EEG (4 ms à 250 Hz) ni avec une frame d'écran (16,7 ms à
# 60 Hz), donc aucune vraie fraction de frame ne peut se glisser dessous.
_EPS_FRAME = 1e-9


def _charger(chemin):
    """(modèle, None) si le modèle se charge, (None, raison) sinon. Ne lève jamais.

    La `raison` est destinée à un étudiant : elle dit quoi FAIRE, pas seulement ce qui a raté —
    même contrat que `errp_models.charger`/`p300_models.charger`/`mi_models.charger`, dont cette
    fonction est une version PROVISOIRE et réduite (un seul chemin possible, cf. docstring du
    module) : la tâche 3 la remplacera par `core.cvep_models.charger`, avec le même contrat.
    """
    if not chemin:
        return None, ("aucun modèle désigné — lance `python src/research/app.py`, mode c-VEP, "
                      "et calibre pour en produire un")
    if not _os.path.isfile(chemin):
        return None, f"modèle introuvable : {chemin}"
    try:
        return CVEPModel.load(chemin), None
    except Exception as e:      # noqa: BLE001 - un modèle sur disque casse de mille façons
        return None, f"modèle illisible ({type(e).__name__}) : {_os.path.basename(chemin)}"


def _modeles_disponibles():
    """Les chemins des modèles c-VEP RÉELLEMENT chargeables. PROVISOIRE (cf. docstring du
    module) : cette liste ne connaît qu'UN chemin fixe, `CVEP_MODEL_PATH` — pas de tri par date,
    pas plusieurs candidats. Alimente le même `Param(kind="choice", choices_fn=…)` que ses futurs
    jumeaux, pour que la tâche 3 n'ait qu'à substituer cette fonction sans toucher au contrat.
    """
    return (CVEP_MODEL_PATH,) if _charger(CVEP_MODEL_PATH)[0] is not None else ()


class CVEPRuntime(ModeRuntime):
    """Tient la phase du code affiché, et refuse de décoder quand elle ne se connaît pas.

    ⚠️ N'expose PAS `pre_s`/`post_s` (contrairement à `P300Runtime`/`ErrPRuntime`) : ce mode ne
    découpe aucune époque autour d'un marqueur, cf. la docstring du module. En ajouter ferait
    croire à `registry.check()` que `marker_epoch_s` doit couvrir `pre_s+post_s`, alors qu'il
    dimensionne ici un tampon glissant, pas une tranche prélevée à un instant précis.
    """

    def __init__(self, spec, params, engine):
        super().__init__(spec, params, engine)
        self.model, raison = _charger(params["model"])
        if self.model is None:
            # On lève ICI plutôt que de démarrer un mode muet. `validate` a déjà écarté le cas
            # « aucun modèle » ; il reste celui du fichier effacé entre la validation et le
            # démarrage, que seul le moteur peut voir — même garde que P300Runtime/ErrPRuntime.
            raise ValueError(raison)
        self.plan, self.code = build_targets()
        desaccord = self._desaccord_code()
        if desaccord is not None:
            raise ValueError(desaccord)
        # == len(self.code), vérifié juste au-dessus : `phase_a` s'appuie sur CETTE valeur (celle
        # que le modèle a APPRISE), pas sur `len(self.code)` — les deux sont égales par
        # construction ici, mais c'est le modèle qui fait autorité sur ce qu'il a décodé.
        self.code_len = self.model.code_len
        # Aucune phase connue tant qu'aucun marqueur de cycle n'est arrivé : c'est CE `None`,
        # distinct de `0`, qui fait refuser `phase_a` plutôt que de rendre une position plausible
        # et fausse. Cf. le ⚠️ de la docstring du module.
        self._ref_ts = None
        self._ref_refresh = None

    def _desaccord_code(self):
        """La phrase à dire si le modèle n'a pas été calibré pour le code que la config ACTUELLE
        construit — None si tout concorde.

        `build_targets()` (donc `self.code`) dépend de `CVEP_BITS`/`CVEP_TAPS` dans
        `core/config.py`, jamais du modèle chargé. Un modèle calibré avant un changement de ces
        constantes porterait un `code_len` différent : sans ce contrôle, `phase_a` continuerait de
        rendre un entier plausible (juste modulo un AUTRE nombre que celui du code réellement
        affiché), et les lags de `self.plan` ne correspondraient à rien dans le template appris —
        un désaccord aussi silencieux que celui du rafraîchissement (`maj_reference`), découvert
        ici pour la même raison : un décodeur qui tourne, publie des scores honnêtes en apparence,
        et ne veut plus rien dire.
        """
        if self.model.code_len != len(self.code):
            return (f"ce modèle a été calibré pour un code de {self.model.code_len} frames, la "
                    f"config actuelle (CVEP_BITS={CVEP_BITS}) en construit un de "
                    f"{len(self.code)} — recalibre (`python src/research/app.py`, mode c-VEP), "
                    f"ou restaure CVEP_BITS à sa valeur de calibration.")
        return None

    def maj_reference(self, ts, refresh):
        """Un marqueur de cycle vient d'arriver : le code était à la frame 0 à l'instant `ts`.

        ⚠️ Le modèle est calibré à UN rafraîchissement, et c'est l'ÉMETTEUR qui tient l'écran — le
        moteur ne peut pas le voir avant de recevoir un marqueur. Sans cette garde : le décodage
        tourne, les scores restent honnêtes, et RIEN ne se déclenche jamais. C'est la panne qui a
        coûté une séance au SSVEP.
        """
        refresh = float(refresh)
        if abs(refresh - self.model.refresh) > 1.0:
            raise ValueError(
                f"l'émetteur affiche à {refresh:.1f} Hz, le modèle a été calibré à "
                f"{self.model.refresh:.1f} Hz — recalibre, ou lance l'émetteur avec "
                f"--refresh {self.model.refresh:.0f}")
        self._ref_ts = float(ts)
        self._ref_refresh = refresh

    def phase_a(self, t_fin):
        """Position dans le code à l'instant LSL `t_fin`, ou None s'il n'y a pas de phase.

        ⚠️ `None` et `0` sont deux choses DIFFÉRENTES : 0 est une position valide du code,
        None veut dire « je ne sais pas où j'en suis ». Les confondre ferait décoder sur une
        horloge fausse en publiant des corrélations d'apparence normale.

        ⚠️ Écart signalé au brief, MESURÉ : sa formule littérale (`int(age * refresh) %
        code_len`, sans `_EPS_FRAME`) échoue sur son PROPRE test de bord de cycle — cf. le
        commentaire de `_EPS_FRAME` ci-dessus pour les nombres exacts. Sans cette tolérance,
        `phase_a` rendrait 62 au lieu de 0 pile au wrap du code, une frame entière de moins que
        la position réelle, silencieusement (aucune exception, un entier plausible).
        """
        if self._ref_ts is None:
            return None
        age = float(t_fin) - self._ref_ts
        if age < 0.0 or age > CVEP_PEREMPTION_CYCLES * self.code_len / self._ref_refresh:
            return None
        return int(age * self._ref_refresh + _EPS_FRAME) % self.code_len


SPEC = ModeSpec(
    id="cvep", label="c-VEP", family="actif",
    summary="Cible fixée parmi N, par codes pseudo-aléatoires décalés (le plus rapide).",
    status="moteur",
    params=(
        Param(key="model", label="Modèle entraîné", kind="choice",
              choices_fn=_modeles_disponibles,
              help="Le modèle produit par une calibration c-VEP, propre à TA personne — celui "
                   "de quelqu'un d'autre donne des corrélations plausibles et fausses. Aucun "
                   "modèle dans la liste ? Lance `python src/research/app.py`, mode c-VEP, et "
                   "calibre. ⚠️ Provisoire : cette liste ne connaît qu'UN chemin fixe "
                   "(`CVEP_MODEL_PATH`) — le catalogue multi-modèles, trié du plus récent au "
                   "plus ancien comme le MI/P300/ErrP, arrive à la tâche 3 de ce chantier."),
    ),
    rest=Rest(
        warmup_s=SSVEP_WARMUP_S,   # 15 s : l'offset DC de l'Unicorn dérive après ouverture
        duration_s=0.0,            # pas de plancher à mesurer : la décision se joue sur une
        #                            corrélation contre un template appris, pas sur un z-score
        #                            contre un repos du jour (contrairement au SSVEP/neuro/ErrP)
        instruction="Le casque se stabilise — reste immobile.",
    ),
    calibration=Calib(kind="natif", reason="stimulus verrouillé à la frame", label="Calibrer"),
    stream="decoded_cvep",
    runtime_cls=CVEPRuntime,
    # La fenêtre de décision : CVEP_DECISION_CYCLES cycles du code, 2 x 63 / 60 = 2,1 s. ⚠️ Ce
    # champ DIMENSIONNE LE TAMPON DU MOTEUR, il NE DÉCRIT AUCUNE ÉPOQUE — contrairement au P300 et
    # à l'ErrP, dont les marqueurs délimitent un événement discret. Les marqueurs c-VEP ne
    # délimitent rien : ils tiennent une horloge (cf. la docstring du module). Si tu cherches un
    # `pre_s`/`post_s` correspondant sur `CVEPRuntime`, il n'y en a pas, volontairement.
    marker_epoch_s=CVEP_DECISION_CYCLES * (2 ** CVEP_BITS - 1) / 60.0,
)


def _selftest():
    """Le runtime c-VEP : la phase et ses TROIS états muets (LE test de cette tâche, brief
    étape 1), plus les refus qui protègent `__init__` — sans modèle, modèle/rafraîchissement en
    désaccord avec l'émetteur, et modèle/config en désaccord sur la longueur du code.

    Aucun casque, aucune fenêtre EEG : ce fichier ne décode rien encore (cf. le ⚠️ de la docstring
    du module) — il tient l'horloge du code et refuse de la tenir à tort, rien de plus.
    """
    import contextlib
    import shutil
    import tempfile

    import numpy as np

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    @contextlib.contextmanager
    def _modele_temporaire(modele=None, n_targets=CVEP_N_TARGETS):
        """Pointe `CVEP_MODEL_PATH` vers CE modèle (sauvegardé dans un dossier temporaire) le
        temps du bloc `with` — ou vers un chemin qui n'existe pas si `modele` est None (« aucun
        modèle »). Restauré et le dossier nettoyé ENSUITE, quoi qu'il arrive.

        ⚠️ C'est le SEUL levier qui permette à `_modeles_disponibles`/`validate` de voir CE
        modèle plutôt que le vrai `data/cvep_model.npz` du dépôt — jamais touché, jamais même lu
        par ce fichier de test. Même geste que `errp.py` monkey-patchant
        `errp_models.modeles_disponibles` pour ses propres tests ; ici il n'existe pas encore de
        module `cvep_models` à monkey-patcher (tâche 3), donc c'est la constante elle-même,
        importée dans CE module, qui est repointée.
        """
        global CVEP_MODEL_PATH
        dossier = tempfile.mkdtemp(prefix="cvep_mode_test_")
        avant = CVEP_MODEL_PATH
        try:
            if modele is None:
                CVEP_MODEL_PATH = _os.path.join(dossier, "aucun_modele.npz")
            else:
                CVEP_MODEL_PATH = modele.save(_os.path.join(dossier, "cvep_model.npz"),
                                              n_targets=n_targets)
            yield
        finally:
            CVEP_MODEL_PATH = avant
            shutil.rmtree(dossier, ignore_errors=True)

    def _runtime_de_test(code_len=63, refresh=60.0, n_targets=CVEP_N_TARGETS):
        """Fabrique minimale, sans moteur ni casque : un `CVEPModel` synthétique de la forme
        voulue (voies = CVEP_CHANNELS, `code_len`/`refresh` donnés — les VALEURS de `w`/`template`
        n'ont aucune importance, aucun test de ce fichier ne décode dessus), sauvegardé puis
        rechargé par le chemin RÉEL de `CVEPRuntime.__init__` (`validate` puis construction) —
        pas de raccourci qui court-circuiterait les refus que ce fichier doit protéger.
        """
        modele = CVEPModel(fs=250.0, refresh=refresh, code_len=code_len, channels=CVEP_CHANNELS)
        modele.w = np.ones(len(CVEP_CHANNELS))
        modele.template = np.zeros(code_len)
        modele.cv_ = 0.5
        with _modele_temporaire(modele, n_targets=n_targets):
            valeurs, raison = validate(SPEC, {})
            if raison is not None:
                raise RuntimeError(f"fabrique de test cassée : {raison}")
            rt = CVEPRuntime(SPEC, valeurs, engine=None)
        return rt

    # --- 1. Sans modèle du tout : le mode REFUSE et dit comment en obtenir un. ----------------
    with _modele_temporaire(None):
        valeurs, raison = validate(SPEC, {})
    chk(raison is not None and "aucun choix disponible" in raison
        and "research/app.py" in raison,
        f"sans modèle, le mode refuse en disant quoi faire ({raison})")

    # --- 2. La phase, et ses TROIS états muets (LE test de cette tâche, brief étape 1) --------
    # Chacun est une panne muette s'il n'est pas traité : le mode continuerait de publier des
    # scores d'apparence honnête calculés sur une horloge fausse.
    rt = _runtime_de_test(code_len=63, refresh=60.0)

    chk(rt.phase_a(100.0) is None,
        "sans aucun marqueur reçu, il n'y a PAS de phase — et surtout pas 0, qui serait une "
        "position valide du code")

    rt.maj_reference(ts=100.0, refresh=60.0)
    chk(rt.phase_a(100.0) == 0, f"à l'instant du marqueur, la phase vaut 0 ({rt.phase_a(100.0)})")
    chk(rt.phase_a(100.0 + 10 / 60.0) == 10,
        f"dix frames plus tard, phase = 10 ({rt.phase_a(100.0 + 10 / 60.0)})")
    chk(rt.phase_a(100.0 + 63 / 60.0) == 0,
        "un cycle entier plus tard, la phase est REVENUE à 0 (modulo la longueur du code)")

    # Péremption : au-delà de CVEP_PEREMPTION_CYCLES, la référence ne vaut plus rien. Continuer
    # en roue libre est l'approche écartée par la spec : à 59,94 Hz réels contre 60 supposés,
    # l'erreur atteint 3,6 frames en une minute sur un code qui en fait 63.
    juste_avant = 100.0 + (CVEP_PEREMPTION_CYCLES * 63 / 60.0) - 0.01
    juste_apres = 100.0 + (CVEP_PEREMPTION_CYCLES * 63 / 60.0) + 0.01
    chk(rt.phase_a(juste_avant) is not None,
        "juste avant la péremption, la référence sert encore")
    chk(rt.phase_a(juste_apres) is None,
        "juste après, elle est PÉRIMÉE : on cesse de décoder au lieu de dériver en silence")

    # ⚠️ Le TROISIÈME état muet, documenté en commentaire dans `phase_a` mais pas exercé par le
    # test ci-dessus : `t_fin` ANTÉRIEUR au dernier marqueur connu (age < 0). Pas un cas d'école :
    # deux horloges en léger désaccord, ou un appel fait avant la toute première référence utile.
    # Sans la garde `age < 0.0`, `int(age * refresh) % code_len` sur un age NÉGATIF rend un entier
    # PLAUSIBLE (le modulo Python est toujours positif) — AUCUNE exception, juste une phase qui a
    # l'air normale et qui ne veut rien dire.
    chk(rt.phase_a(100.0 - 1.0) is None,
        f"un instant ANTÉRIEUR au dernier marqueur connu n'a pas de phase valide non plus "
        f"({rt.phase_a(100.0 - 1.0)})")

    # --- 3. Le refus de rafraîchissement : l'émetteur et le modèle doivent s'accorder --------
    rt2 = _runtime_de_test(code_len=63, refresh=60.0)
    try:
        rt2.maj_reference(ts=200.0, refresh=75.0)   # modèle calibré à 60 Hz, émetteur à 75 Hz
        refus_refresh = None
    except ValueError as e:
        refus_refresh = str(e)
    chk(refus_refresh is not None and "75.0" in refus_refresh and "60" in refus_refresh
        and "recalibre" in refus_refresh,
        f"un émetteur qui affiche à un AUTRE rafraîchissement que le modèle est refusé, en "
        f"nommant les deux fréquences ({refus_refresh})")
    chk(rt2.phase_a(200.0) is None,
        "...et le refus n'a laissé AUCUNE référence utilisable derrière lui")

    # 3bis. À l'inverse, un petit écart (bruit de mesure du refresh réel de l'écran) est toléré.
    rt2.maj_reference(ts=200.0, refresh=60.4)
    chk(rt2.phase_a(200.0) == 0,
        f"un écart de 0,4 Hz (sous la tolérance de 1 Hz) est accepté ({rt2.phase_a(200.0)})")

    # --- 4. Le refus de désaccord de code : un modèle calibré pour un AUTRE code_len ---------
    modele_faux = CVEPModel(fs=250.0, refresh=60.0, code_len=31, channels=CVEP_CHANNELS)
    modele_faux.w = np.ones(len(CVEP_CHANNELS))
    modele_faux.template = np.zeros(31)
    modele_faux.cv_ = 0.5
    with _modele_temporaire(modele_faux):
        valeurs, raison = validate(SPEC, {})
        chk(valeurs is not None, f"un modèle à 31 frames passe la validation du CHOIX ({raison})")
        try:
            CVEPRuntime(SPEC, valeurs, engine=None)
            refus_code = None
        except ValueError as e:
            refus_code = str(e)
    chk(refus_code is not None and "31" in refus_code and "63" in refus_code,
        f"...mais la CONSTRUCTION refuse un modèle calibré pour un AUTRE code que celui que la "
        f"config actuelle construit, en nommant les deux longueurs ({refus_code})")

    # --- 5. Le contrat du mode -----------------------------------------------------------------
    chk(SPEC.id == "cvep" and SPEC.family == "actif" and SPEC.status == "moteur",
        f"identifiant, famille et statut du mode ({SPEC.id}, {SPEC.family}, {SPEC.status})")
    chk(SPEC.stream == "decoded_cvep", f"publié sur decoded_cvep ({SPEC.stream})")
    chk(abs(SPEC.marker_epoch_s - 2.1) < 1e-9,
        f"la fenêtre de décision dimensionne le tampon, 2 x 63/60 = 2,1 s ({SPEC.marker_epoch_s:g})")
    chk(SPEC.calibration is not None and SPEC.calibration.kind == "natif"
        and SPEC.calibration.label == "Calibrer" and SPEC.calibration.runtime_cls is None,
        "sa calibration reste NATIVE : l'appli pygame la joue, pas le moteur")
    chk(SPEC.rest is not None and SPEC.rest.warmup_s == SSVEP_WARMUP_S
        and SPEC.rest.duration_s == 0.0,
        f"chauffe seule, pas de repos à mesurer — le c-VEP ne normalise pas contre un plancher "
        f"({SPEC.rest})")
    chk(not hasattr(CVEPRuntime, "pre_s") and not hasattr(CVEPRuntime, "post_s"),
        "CVEPRuntime n'expose PAS pre_s/post_s : marker_epoch_s dimensionne un tampon, pas une "
        "époque (cf. docstring du module) — registry.check() ne doit pas y voir un troisième "
        "mode à marqueurs délimitant une tranche")

    print(f"[cvep] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
