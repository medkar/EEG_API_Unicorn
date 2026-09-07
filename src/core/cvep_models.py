"""Les modèles c-VEP sur le disque : lesquels existent, lequel se charge vraiment, et AVEC QUEL
DÉCODEUR.

Jumeau de `mi_models.py` / `p300_models.py` / `errp_models.py`, et pour la même raison : un modèle
est propre à UNE personne, et le mode doit pouvoir dire « aucun choix disponible » plutôt que
démarrer muet. Une chose de plus ici : le c-VEP a **deux décodeurs** sur le même stimulus (eCCA et
rCCA), et **c'est le fichier qui déclare le sien**. L'étudiant choisit un modèle, pas un algorithme.

⚠️ **Comment le décodeur se lit, et pourquoi pas autrement.** Chaque `save` écrit un champ
`decoder` (`"eCCA"` | `"rCCA"`). Un fichier **sans ce champ** est un modèle d'avant le chantier
c-VEP-moteur, donc un **eCCA** — c'était le seul décodeur qui existait sous ce nom de fichier
(`data/cvep_model.npz` est exactement dans ce cas). Inférer le décodeur de la présence de telle ou
telle clé (« il y a `codes`, donc c'est du rCCA ») marcherait aujourd'hui et casserait au premier
champ ajouté ; un champ explicite se lit et se teste.

⚠️ **Trois divergences ASSUMÉES avec les trois jumeaux, à ne pas prendre pour des oublis.**

1. **Pas de refus de « modèle hérité » par nom de module.** C'est LE refus central des trois autres
   (un pickle `joblib` grave le chemin de module de sa classe, et le déménagement dans `core/` a
   coûté leurs modèles au P300, à l'ErrP et au MI). Le c-VEP écrit du `np.savez` de **tableaux
   purs** : aucun nom de classe dans le fichier, donc rien à ressusciter — c'est mesuré, pas
   espéré (cf. `cvep_decoder._selftest`). Le refus qui le remplace est le n° 2.
2. **Un refus que les autres n'ont pas : le STIMULUS.** Un modèle rCCA porte ses **codes**. Le seul
   modèle rCCA qui existe sur ce poste (`data/cvep_rcca_model.npz`) a été calibré sur des **codes
   Gold distincts** — une hypothèse mesurée, réfutée, et retirée du produit : plus aucun émetteur
   ne les affiche. Sans ce refus, ce fichier réapparaîtrait dans la liste de la console et le
   moteur décoderait un stimulus que personne n'affiche, avec des scores d'apparence normale.
   Le contrôle vit **ici** et pas dans le mode, précisément pour que le fichier ne soit jamais
   *proposé* — un refus au démarrage du mode l'aurait laissé dans la liste.
   ⚠️ Le contrôle jumeau côté eCCA reste, lui, dans `core/modes/cvep.py` (`_desaccord_code`) : un
   modèle eCCA ne porte pas de codes, seulement un `code_len` et un `n_targets`, et ces
   désaccords-là se réparent en restaurant `CVEP_BITS`/`CVEP_N_TARGETS` — le mode le dit en
   nommant les deux nombres, ce qu'une disparition de la liste ne dirait pas.
   ⚠️ **Et il ne couvre PAS `CVEP_TAPS`, contrairement au refus rCCA ci-dessus.** Le dire, parce
   que la symétrie apparente laisse croire l'inverse : `CVEPModel.save` n'enregistre pas les taps,
   donc `_desaccord_code` ne compare que la LONGUEUR du code. Passer `CVEP_TAPS` de `(6, 5)` à
   `(6, 1)` — l'autre polynôme primitif de degré 6, celui-là même dont ce fichier se sert pour
   fabriquer ses « codes étrangers » — laisse `code_len = 63` inchangé : le modèle eCCA est
   accepté, et son template est corrélé à une m-séquence que plus aucun écran n'affiche. Un
   modèle rCCA de la même séance serait refusé, lui, parce qu'il porte ses codes. C'est un champ
   qui manque à `CVEPModel.save`, pas une couverture assumée.
3. **`decrire` rend `cv_loo`, pas `cv_auc`.** Le chiffre honnête du c-VEP est une **justesse
   leave-one-out à 6 cibles** (hasard 16,7 %), pas une AUC à deux classes. Les nommer pareil serait
   un mensonge d'étiquette — `mi_models.decrire` diverge déjà de la même façon (`cv_groupee`). Les
   quatre clés que les quatre modules partagent restent `chemin`, `nom`, `date`, `probleme`.

⚠️ **Charger un modèle rCCA coûte plus cher qu'un eCCA** : `RCCAModel.load` ne sérialise pas
l'objet pyntbci, il **ré-ajuste** depuis les époques stockées. Mesuré sur ce poste : ~0,3 s et
~750 ko par modèle rCCA, contre ~1 ms et 4 ko pour un eCCA. La liste se construit à l'ouverture du
catalogue, pas en boucle — mais si un jour `data/` contient dix modèles rCCA, c'est ici qu'il
faudra regarder.

⚠️ **Corollaire : `pyntbci` est une dépendance du MOTEUR, pas d'un outil d'analyse.** Ré-ajuster au
chargement veut dire que sans elle, aucun modèle rCCA ne se charge — et comme `modeles_disponibles`
ne garde que ce qui se charge, ils **disparaissaient tous de la liste de la console sans un mot**.
Les deux moitiés du remède vivent ici : `charger` NOMME le cas (`PyntbciManquant`, message
actionnable) au lieu d'annoncer « modèle illisible », et `modeles_disponibles` compte les retirés et
le dit. Les modèles eCCA, eux, ne dépendent de rien de tout ça et restent utilisables.

Autotest :
    python src/core/cvep_models.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from core.config import CVEP_LAG_ROTATION, DATA_DIR, use_utf8_console  # noqa: E402


import glob as _glob  # noqa: E402
import time as _time  # noqa: E402

import numpy as _np  # noqa: E402

from core.cvep_code import build_targets  # noqa: E402
from core.cvep_decoder import CVEPModel  # noqa: E402
from core.cvep_rcca import MSG_PYNTBCI, PyntbciManquant, RCCAModel  # noqa: E402

# Deux familles de noms, une par décodeur — d'où un TUPLE là où les trois jumeaux ont une seule
# chaîne. Un motif unique élargi (`cvep*model*.npz`) attraperait la même chose aujourd'hui, mais
# aussi tout fichier futur portant « model » dans son nom ; deux motifs explicites disent quels
# fichiers sont des modèles.
MOTIFS = ("cvep_model*.npz", "cvep_rcca_model*.npz")

# Le décodeur par défaut d'un fichier qui ne déclare rien : voir le ⚠️ de la docstring.
DECODEUR_HERITE = "eCCA"

# Quelle classe pour quel `decoder`, et ce que son `load` exige de trouver dans le fichier. Les
# clés sont listées pour pouvoir refuser AVANT d'appeler `load` : un `KeyError` remonté tel quel
# dirait « modèle illisible (KeyError) », alors que le vrai diagnostic est « ce n'est pas un
# modèle c-VEP » (typiquement un `cvep_calib_*.npz` recopié sous un nom de modèle).
_CLASSES = {
    "eCCA": (CVEPModel, ("w", "template", "fs", "refresh", "code_len", "band", "cv")),
    "rCCA": (RCCAModel, ("codes", "epochs", "labels", "fs", "refresh", "band", "channels",
                         "event", "enc", "cv")),
}


def _codes_affiches():
    """Les codes que le stimulus affiche AUJOURD'HUI, un par cible, dans l'ordre des cibles.

    C'est `build_targets()` qui fait autorité — donc `CVEP_BITS`, `CVEP_TAPS`, `CVEP_N_TARGETS` et
    `CVEP_LAG_ROTATION` de `core/config.py`. Un modèle rCCA doit porter EXACTEMENT ces codes,
    lignes comprises dans le même ORDRE : `RCCADecoder` apparie `plan[i]` à `codes[i]`, et une
    simple permutation des lignes (ce que produit un changement de `CVEP_LAG_ROTATION`) ferait
    nommer la cible voisine sans que rien ne lève.
    """
    plan, _code = build_targets()
    return _np.stack([_np.asarray(c["code"], dtype=int) for c in plan])


def charger(chemin):
    """(modèle, None) si le modèle se charge, (None, raison) sinon. Ne lève jamais.

    La `raison` est destinée à un étudiant : elle dit quoi FAIRE, pas seulement ce qui a raté.
    Le modèle rendu porte `.decoder` (`"eCCA"` | `"rCCA"`), attribut de sa CLASSE : c'est de lui
    que le moteur déduit comment décoder.
    """
    # Un chemin vide n'est pas un incident : c'est l'état d'un formulaire dont la liste de
    # modèles est vide (dépôt fraîchement cloné, aucune calibration faite). La docstring promet
    # de ne jamais lever ; `os.path.isfile(None)` levait. Le refus doit dire quoi faire.
    if not chemin:
        # ⚠️ Le stimulus de calibration c-VEP est verrouillé à la frame : il est rendu par une
        # FENÊTRE de `src/stimulus/`, que la console lance (cf. `Calib(kind="fenetre")` du mode).
        # Ce texte est celui du `help` du réglage « Modèle entraîné » : le même geste dit du même
        # mot aux deux endroits où un étudiant peut le lire.
        return None, ("aucun modèle désigné — ouvre la console, page c-VEP, et clique "
                      "« Calibrer le c-VEP » pour en produire un")
    if not _os.path.isfile(chemin):
        return None, f"modèle introuvable : {chemin}"
    nom = _os.path.basename(chemin)
    try:
        # ⚠️ PAS d'`allow_pickle=True`, et c'est mesuré, pas une précaution en l'air : les trois
        # fichiers réels du dépôt (`cvep_model.npz`, `cvep_rcca_model.npz`, `cvep_calib_last.npz`)
        # se relisent tous sans lui — le format c-VEP n'a que des tableaux de types simples. Le
        # drapeau n'apportait donc rien, et il coûtait : `np.load(..., allow_pickle=True)` DÉPICKLE
        # au premier accès, c'est-à-dire exécute du code contenu dans le fichier. Or cette fonction
        # est exactement celle qui ouvre des fichiers dont on ne sait rien (`modeles_disponibles`
        # charge tout ce qui traîne dans `data/`), dans le module dont la docstring vante l'absence
        # de nom de classe à ressusciter. Sans le drapeau, un `.npz` piégé lève, et le refus dit
        # « modèle illisible » au lieu de l'exécuter.
        with _np.load(chemin) as d:
            presentes = set(d.files)
            # Le champ d'aiguillage. Absent = modèle d'avant ce chantier, donc eCCA.
            decodeur = str(d["decoder"]) if "decoder" in presentes else DECODEUR_HERITE
            codes = _np.asarray(d["codes"]) if "codes" in presentes else None
    except Exception as e:      # noqa: BLE001 - un .npz casse de mille façons, toutes équivalentes
        # `np.load` refuse un fichier qui n'est pas une archive ; un `.npy` nu n'a pas de `.files`
        # (AttributeError). Les deux se disent de la même façon à l'étudiant.
        return None, f"modèle illisible ({type(e).__name__}) : {nom}"

    if decodeur not in _CLASSES:
        return None, (f"ce fichier déclare un décodeur inconnu ({decodeur!r}, attendus "
                      f"{' ou '.join(sorted(_CLASSES))}) — il vient d'une version plus récente du "
                      f"produit, ou il a été bricolé : {nom}")
    classe, requises = _CLASSES[decodeur]
    manquantes = [c for c in requises if c not in presentes]
    if manquantes:
        # Le cas concret : un `cvep_calib_*.npz` (des époques de calibration) recopié sous un nom
        # de modèle. Sans ce contrôle, `load` lève un KeyError et on annonce « illisible », ce qui
        # envoie chercher une corruption de fichier là où il n'y a qu'un fichier mal rangé.
        return None, (f"ce n'est pas un modèle c-VEP {decodeur} (il manque "
                      f"{', '.join(manquantes)}) : {nom}")

    # ⚠️ Le refus de STIMULUS, et il se pose AVANT `load` — pour un modèle rCCA, `load` ré-ajuste
    # pyntbci sur les époques stockées (~0,3 s), et il n'y a aucune raison de payer ça pour un
    # fichier qu'on va refuser. Voir le ⚠️ n° 2 de la docstring du module pour le pourquoi.
    if decodeur == "rCCA":
        attendus = _codes_affiches()
        if codes is None or codes.shape != attendus.shape or not _np.array_equal(codes, attendus):
            # Dire LEQUEL des deux désaccords, parce qu'ils se réparent différemment : une
            # dimension qui change vient de la config (CVEP_BITS/CVEP_N_TARGETS), un contenu qui
            # change à dimensions égales vient d'une autre FAMILLE de codes (Gold) ou d'un autre
            # ordre de lignes (CVEP_LAG_ROTATION). Un message qui affichait « 6x63 contre 6x63 »
            # ne disait rien à personne.
            if codes is None or codes.shape != attendus.shape:
                forme = "aucun" if codes is None else "x".join(str(n) for n in codes.shape)
                quoi = (f"il porte {forme} codes, le stimulus actuel en affiche "
                        f"{'x'.join(str(n) for n in attendus.shape)} — la config a changé depuis "
                        f"la calibration (CVEP_BITS, CVEP_TAPS, CVEP_N_TARGETS)")
            else:
                # ⚠️ **Ce refus signale un VRAI défaut, à TOUTE rotation — et ce message a dit
                # l'inverse.** Il expliquait qu'à `CVEP_LAG_ROTATION` non nul le désaccord était
                # « le cas ATTENDU même sans rien avoir changé », parce que la calibration
                # empilait ses codes par lag CROISSANT quand le plan, lui, les fait TOURNER.
                # C'était vrai, et ça ne l'est plus : depuis le 2026-08-21,
                # `research/cvep_calibrate.py` écrit ses codes DANS L'ORDRE DU PLAN, et son
                # autotest le vérifie à rotation = 2 (un modèle qu'on vient de calibrer est
                # ACCEPTÉ, quelle que soit la rotation). Laisser la phrase revenait à apprendre à
                # l'étudiant qu'un vrai défaut est normal — la pire des deux erreurs possibles
                # ici. On NOMME donc les trois causes réelles, sans en excuser aucune.
                quoi = ("mêmes dimensions, mais pas les mêmes codes ni le même ordre. Trois "
                        "causes, toutes réelles : des codes Gold distincts (hypothèse mesurée, "
                        "réfutée et retirée du produit — plus aucun émetteur ne les affiche) ; "
                        f"un CVEP_LAG_ROTATION changé depuis la calibration (il vaut "
                        f"{CVEP_LAG_ROTATION} aujourd'hui), qui PERMUTE les lignes ; ou un modèle "
                        "calibré AVANT le 2026-08-21, quand la calibration empilait encore ses "
                        "codes par lag croissant au lieu de l'ordre du plan. Un ordre permuté "
                        "ferait nommer la cible voisine, d'où le refus")
            return None, (f"ce modèle rCCA a été calibré sur d'AUTRES codes que ceux affichés "
                          f"aujourd'hui : {quoi}. Recalibre (`python src/research/app.py`, mode "
                          f"c-VEP) : {nom}")

    try:
        modele = classe.load(chemin)
    except PyntbciManquant as e:
        # ⚠️ NOMMÉ avant le `except Exception` d'à côté, et c'est tout l'intérêt : celui-ci ne
        # garde que `type(e).__name__`, donc ce cas se lisait « modèle illisible
        # (PyntbciManquant) » — un fichier parfaitement sain annoncé comme corrompu, et un
        # étudiant qui part chercher une corruption là où il manque un `pip install`. Le message
        # complet dit quoi FAIRE (`pip install -r requirements.txt`) et que l'eCCA, lui, n'en
        # dépend pas : les modèles eCCA restent utilisables sans cette dépendance.
        return None, f"{e} (fichier : {nom})"
    except Exception as e:      # noqa: BLE001 - un modèle sur disque casse de mille façons
        return None, f"modèle illisible ({type(e).__name__}) : {nom}"
    return modele, None


def modeles_disponibles(dossier=DATA_DIR):
    """Les chemins des modèles c-VEP RÉELLEMENT chargeables, du PLUS RÉCENT au plus ancien.

    Rend une **liste**, comme ses trois jumeaux (`mi_models`, `p300_models`, `errp_models`) : les
    quatre alimentent le même `Param(kind="choice", choices_fn=…)`, et deux types différents pour
    la même fonction finissent par produire un `+` ou un `==` qui marche d'un côté et pas de
    l'autre. (`Param.choices_status` applique `tuple(...)` de toute façon.)

    Le plus récent d'abord, parce que c'est le défaut proposé : après une calibration, c'est
    celui qu'on vient de faire qu'on veut essayer. Les DEUX décodeurs sont dans la même liste,
    triés ensemble : la question posée à l'étudiant est « quel modèle », pas « quel algorithme ».

    On charge pour lister, au lieu de se fier au nom : un fichier au bon nom mais au mauvais
    format apparaîtrait dans le formulaire de la console et échouerait au démarrage du mode —
    exactement le genre de « ça a l'air bon » que ce produit cherche à supprimer.
    """
    # ⚠️ `key=_os.path.getmtime` s'évalue sur TOUS les candidats : un fichier qui disparaît (ou
    # qu'un antivirus verrouille) entre le `glob` et la clé ferait sortir un `FileNotFoundError`
    # de cette fonction, que `Param.choices_status` classerait en « `choices_fn` qui lève = DÉFAUT
    # de déclaration » — un bug du produit annoncé là où il n'y a qu'une course bénigne (catalogue
    # ouvert pendant qu'une calibration écrit). Correctif repris de `errp_models`, à l'identique.
    candidats = set()
    for motif in MOTIFS:
        candidats.update(_glob.glob(_os.path.join(dossier, motif)))
    chemins = sorted(candidats,
                     key=lambda c: _os.path.getmtime(c) if _os.path.isfile(c) else 0.0,
                     reverse=True)
    # ⚠️ **Une dépendance manquante ne doit pas faire DISPARAÎTRE des modèles en silence.** Ce
    # filtre écarte tout ce qui ne se charge pas, ce qui est juste — sauf pour `pyntbci` : sans
    # lui, `RCCAModel.load` échoue et TOUS les modèles rCCA s'évaporent de la liste de la console,
    # sans un mot. Un fichier parfaitement bon qui disparaît est exactement la panne muette que ce
    # module existe pour supprimer, retournée. On les compte donc, et on le DIT une fois — la
    # liste, elle, reste honnête : ces fichiers ne sont réellement pas chargeables ici.
    utilisables, sans_pyntbci = [], []
    for c in chemins:
        modele, raison = charger(c)
        if modele is not None:
            utilisables.append(c)
        elif raison and MSG_PYNTBCI in raison:
            sans_pyntbci.append(_os.path.basename(c))
    if sans_pyntbci:
        print(f"[cvep-models] ⚠️ {len(sans_pyntbci)} modèle(s) rCCA RETIRÉ(S) de la liste "
              f"({', '.join(sans_pyntbci)}) — {MSG_PYNTBCI}")
    return utilisables


def decrire(chemin):
    """Une ligne lisible pour la liste de la console : date, décodeur, justesse honnête, cibles.
    Ne lève jamais, exactement comme `charger`, sa fonction sœur.

    `cv_loo` est la justesse **leave-one-out** mesurée à la calibration : chaque cycle est classé
    par un modèle qui ne l'a pas vu. C'est la seule mesure honnête ici, et elle se lit contre le
    hasard à `n_targets` cibles (16,7 % à 6), pas contre 50 %.

    ⚠️ AUCUN appelant en production aujourd'hui — la console n'importe pas encore ce module (même
    situation que `errp_models.decrire`). Cette forme existe pour la PARITÉ avec les trois jumeaux,
    que la console lira quand elle affichera les listes de modèles.
    """
    modele, raison = charger(chemin)
    # `chemin and` court-circuite None, "" et l'entier 0, que `os.path.isfile` prendrait pour un
    # descripteur de fichier (stdin) — même durcissement que chez les jumeaux, sur la fonction
    # PUBLIQUE qui remplit la liste de modèles, à un fil Qt de distance.
    horodatage = _os.path.getmtime(chemin) if chemin and _os.path.isfile(chemin) else 0.0
    infos = {
        "chemin": chemin,
        "nom": _os.path.basename(chemin) if chemin else "",
        "date": _time.strftime("%Y-%m-%d %H:%M", _time.localtime(horodatage)) if horodatage else "",
        "decodeur": None,
        "cv_loo": None,
        "n_targets": None,
        "n_epoques": None,
        "probleme": raison,
    }
    if modele is None:
        return infos
    infos["decodeur"] = modele.decoder
    cv = getattr(modele, "cv_", None)
    infos["cv_loo"] = float(cv) if cv is not None else None
    # eCCA : `n_targets` est ce que la calibration a ENREGISTRÉ (0 = modèle antérieur au champ) ;
    # rCCA : c'est le nombre de codes, donc toujours connu.
    cibles = getattr(modele, "n_targets", 0)
    infos["n_targets"] = int(cibles) or None
    epoques = getattr(modele, "_labels", None)
    infos["n_epoques"] = int(len(epoques)) if epoques is not None else None
    return infos


def _selftest():
    """Sur un dossier temporaire : les deux décodeurs, un modèle hérité, un stimulus réfuté.

    ⚠️ Aucun fichier du vrai `data/` n'est lu ni écrit : `data/` contient des enregistrements EEG
    d'une personne identifiable, sur un dépôt public, et `data/cvep_model.npz` est le seul modèle
    c-VEP existant. Toutes les fixtures sont fabriquées dans un dossier temporaire, nettoyé dans
    un `finally`.
    """
    import contextlib as _contextlib
    import io as _io
    import shutil
    import tempfile

    from core.cvep_code import m_sequence
    from core.config import CVEP_CHANNELS

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    def _ecca(cv=0.48, code_len=63):
        m = CVEPModel(fs=250.0, refresh=60.0, code_len=code_len, channels=CVEP_CHANNELS)
        m.w = _np.ones(len(CVEP_CHANNELS))
        m.template = _np.zeros(int(round(code_len * 250.0 / 60.0)))
        m.cv_ = cv
        return m

    def _rcca(codes, cv=0.51, n_par_cible=2):
        """Un vrai `RCCAModel` ajusté (donc sauvegardable et rechargeable), sur peu d'époques :
        ce fichier teste le CATALOGUE, pas le décodage — `cvep_rcca.py` s'en charge."""
        rng = _np.random.default_rng(1)
        n_ch = len(CVEP_CHANNELS)
        m = RCCAModel(codes, fs=250.0, refresh=60.0, channels=list(range(n_ch)))
        epochs = [rng.normal(0.0, 1.0, (m.n_cyc, n_ch))
                  for _ in range(len(codes) * n_par_cible)]
        labels = [i for i in range(len(codes)) for _ in range(n_par_cible)]
        m.fit(epochs, labels, compute_cv=False)
        m.cv_ = cv
        return m

    dossier = tempfile.mkdtemp(prefix="cvep_models_")
    try:
        codes_du_jour = _codes_affiches()

        # --- 1. LE test de cette tâche : le fichier DÉCLARE son décodeur. ---------------------
        # Le moteur choisit sa classe de décodage d'après ce champ. Deviner d'après les clés
        # présentes marcherait aujourd'hui et casserait au premier champ ajouté.
        chemin_ecca = _ecca().save(_os.path.join(dossier, "cvep_model.npz"), n_targets=6)
        chemin_rcca = _rcca(codes_du_jour).save(
            _os.path.join(dossier, "cvep_rcca_model.npz"))

        # Le modèle HÉRITÉ : écrit exactement comme `CVEPModel.save` l'écrivait AVANT ce chantier,
        # c'est-à-dire sans le champ. ⚠️ Fabriqué à la main et pas par `save()` amputé : c'est la
        # forme de `data/cvep_model.npz`, le seul modèle c-VEP réellement existant, et c'est lui
        # que ce test protège.
        chemin_herite = _os.path.join(dossier, "cvep_model_herite.npz")
        vieux = _ecca(cv=0.42)
        _np.savez(chemin_herite, w=vieux.w, template=vieux.template, fs=vieux.fs,
                  refresh=vieux.refresh, code_len=vieux.code_len,
                  band=_np.asarray(vieux.band), n_targets=6,
                  channels=_np.asarray(vieux.channels, dtype=int), cv=vieux.cv_)
        with _np.load(chemin_herite) as d:
            chk("decoder" not in d.files,
                f"fixture : le modèle hérité n'a VRAIMENT pas le champ ({sorted(d.files)})")

        # `getattr(..., None)` et pas `.decoder` : une `charger` cassée rend (None, raison), et on
        # veut lire un ÉCHEC nommé, pas un `AttributeError: 'NoneType'` qui n'apprend rien.
        def _declare(chemin):
            return getattr(charger(chemin)[0], "decoder", None)

        chk(_declare(chemin_ecca) == "eCCA",
            f"un modèle eCCA se déclare comme tel ({_declare(chemin_ecca)})")
        chk(_declare(chemin_rcca) == "rCCA",
            f"un modèle rCCA aussi, et le moteur choisit le décodeur d'après CE champ "
            f"({_declare(chemin_rcca)})")
        chk(_declare(chemin_herite) == "eCCA",
            f"un modèle SANS le champ est un eCCA hérité, pas une erreur "
            f"({_declare(chemin_herite)})")
        # ...et la classe rendue est celle du décodeur, pas seulement l'étiquette : c'est ce que
        # le moteur va appeler. Une `charger` qui rendrait toujours un CVEPModel en recopiant le
        # champ `decoder` passerait les trois assertions ci-dessus.
        chk(isinstance(charger(chemin_rcca)[0], RCCAModel)
            and isinstance(charger(chemin_ecca)[0], CVEPModel)
            and isinstance(charger(chemin_herite)[0], CVEPModel),
            "...et c'est bien la CLASSE correspondante qui est rendue, pas juste l'étiquette")

        # --- 2. Le refus de STIMULUS : les codes Gold restent dehors. -------------------------
        # `data/cvep_rcca_model.npz` est calibré sur des codes Gold distincts — hypothèse mesurée,
        # réfutée, retirée du produit. Aucun émetteur ne les affiche plus. Sans ce refus, il
        # réapparaît dans la liste de la console et le moteur décode un stimulus fantôme.
        # (Les codes de la fixture viennent d'un AUTRE polynôme primitif : `core/` n'importe pas
        # `research/`, donc pas de `make_distinct_codes` ici — et n'importe quel jeu de codes
        # différent fait le même travail.)
        autre = m_sequence(6, (6, 1))
        codes_etrangers = _np.stack([_np.roll(autre, -l) for l in (0, 10, 21, 32, 42, 52)])
        chk(not _np.array_equal(codes_etrangers, codes_du_jour),
            "fixture : ces codes ne sont VRAIMENT pas ceux du stimulus d'aujourd'hui")
        chemin_gold = _rcca(codes_etrangers).save(
            _os.path.join(dossier, "cvep_rcca_model_gold.npz"))
        _m, raison = charger(chemin_gold)
        chk(_m is None and "réfut" in (raison or "") and "recalibre" in (raison or "").lower()
            and "cvep_rcca_model_gold.npz" in (raison or ""),
            f"un modèle rCCA calibré sur d'AUTRES codes est refusé, en le nommant et en disant "
            f"quoi faire ({raison})")
        chk(chemin_gold not in modeles_disponibles(dossier),
            "...et il n'apparaît donc pas dans la liste proposée à l'étudiant")

        # 2 bis. Le cas sournois : les BONS codes, dans le MAUVAIS ORDRE. C'est ce que produit un
        # changement de `CVEP_LAG_ROTATION` entre la calibration et aujourd'hui. `RCCADecoder`
        # apparie `plan[i]` à `codes[i]` : permutés, tous les scores sont bons et tous les NOMS
        # sont faux. Une comparaison écrite en `set(...)` ou `sorted(...)` — la simplification
        # qu'on écrit sans y penser — laisse passer exactement ce fichier-là.
        permutes = _np.roll(codes_du_jour, 1, axis=0)
        chemin_permute = _rcca(permutes).save(
            _os.path.join(dossier, "cvep_rcca_model_permute.npz"))
        _m, raison = charger(chemin_permute)
        chk(_m is None and "codes" in (raison or ""),
            f"...et les MÊMES codes dans un autre ORDRE sont refusés aussi : l'appariement "
            f"score↔cible en dépend ({raison})")
        # 2 ter. Le message ne doit pas EXCUSER ce refus — et il l'a fait, mais SEULEMENT à
        # `CVEP_LAG_ROTATION` non nul : il annonçait alors « le cas ATTENDU même sans rien avoir
        # changé ». C'était vrai tant que la calibration empilait ses codes par lag croissant, et
        # faux depuis qu'elle écrit dans l'ordre du plan (2026-08-21 ; `cvep_calibrate` le vérifie
        # à rotation 2). ⚠️ **La rotation du dépôt vaut 0, donc ce test DOIT la détourner** :
        # relu à 0, le message n'a jamais contenu la phrase et l'assertion serait creuse.
        # Assertion sur le TEXTE parce que c'est le texte qui était le défaut : il apprenait à
        # l'étudiant qu'un vrai désaccord de codes est normal, donc à passer outre.
        global CVEP_LAG_ROTATION
        _rot_avant = CVEP_LAG_ROTATION
        CVEP_LAG_ROTATION = 2
        try:
            _m, raison_rot = charger(chemin_permute)
        finally:
            CVEP_LAG_ROTATION = _rot_avant
        chk("ATTENDU" not in (raison_rot or "") and "recalibre" in (raison_rot or "").lower()
            and "CVEP_LAG_ROTATION" in (raison_rot or ""),
            f"...et à CVEP_LAG_ROTATION NON NUL ce refus reste présenté comme un VRAI défaut à "
            f"réparer, jamais comme un cas attendu : la calibration écrit ses codes dans l'ordre "
            f"du plan depuis le 2026-08-21, donc un modèle frais est ACCEPTÉ à toute rotation "
            f"({raison_rot})")

        # 2 quater. `pyntbci` ABSENT : le cas est NOMMÉ, et les modèles rCCA ne s'évaporent pas
        # de la liste en silence. On simule la dépendance manquante à l'endroit exact où elle
        # manquerait — `_fit_clf`, le seul `import pyntbci` du produit, appelé par `load`.
        vrai_fit_clf = RCCAModel._fit_clf

        def _sans_pyntbci(self, X, y):
            raise PyntbciManquant(MSG_PYNTBCI)

        RCCAModel._fit_clf = _sans_pyntbci
        try:
            _m, raison = charger(chemin_rcca)
            capture = _io.StringIO()
            with _contextlib.redirect_stdout(capture):
                liste_sans = modeles_disponibles(dossier)
            dit = capture.getvalue()
        finally:
            RCCAModel._fit_clf = vrai_fit_clf
        chk(_m is None and "pyntbci" in (raison or "") and "pip install" in (raison or "")
            and "illisible" not in (raison or ""),
            f"sans `pyntbci`, un modèle rCCA est refusé en disant QUOI FAIRE, pas annoncé "
            f"« illisible » — le fichier est sain, c'est la dépendance qui manque ({raison})")
        chk(chemin_rcca not in liste_sans and "cvep_rcca_model.npz" in dit
            and "pip install" in dit,
            f"...et son retrait de la liste est DIT, au lieu de le faire disparaître en silence "
            f"du catalogue de la console ({dit.strip()!r})")
        chk(chemin_ecca in liste_sans,
            f"...tandis que les modèles eCCA restent listés : eux ne dépendent pas de `pyntbci` "
            f"({[_os.path.basename(c) for c in liste_sans]})")

        # --- 3. Les refus qui ne dépendent pas du décodeur. -----------------------------------
        casse = _os.path.join(dossier, "cvep_model_casse.npz")
        with open(casse, "wb") as f:
            f.write(b"ceci n'est pas une archive numpy")
        _m, raison = charger(casse)
        chk(_m is None and "illisible" in (raison or "") and "cvep_model_casse.npz" in (raison or ""),
            f"un fichier illisible rend une raison au lieu de lever ({raison})")

        _m, raison = charger(_os.path.join(dossier, "absent.npz"))
        chk(_m is None and "introuvable" in (raison or ""),
            f"un chemin inexistant est signalé comme tel ({raison})")

        # `charger` promet de ne JAMAIS lever. Elle lèverait pourtant sur None (os.path.isfile(None)
        # lève) — et un formulaire de console rend très bien None ou "" quand aucun modèle n'existe.
        for entree in (None, "", 0):
            _m, raison = charger(entree)
            chk(_m is None and raison and "aucun modèle" in raison,
                f"charger({entree!r}) rend une raison au lieu de lever ({raison})")

        # Un `.npz` au bon nom mais qui n'est pas un modèle : le cas concret est un
        # `cvep_calib_*.npz` (des ÉPOQUES) recopié sous un nom de modèle en rangeant `data/`.
        # Sans le contrôle de clés, `load` lève un KeyError et on annonce « illisible » — on
        # envoie chercher une corruption là où il n'y a qu'un fichier mal rangé.
        faux_modele = _os.path.join(dossier, "cvep_model_calib.npz")
        _np.savez(faux_modele, epochs=_np.zeros((4, 262, 8)), lags=_np.zeros(4), fs=250.0)
        _m, raison = charger(faux_modele)
        chk(_m is None and "pas un modèle c-VEP" in (raison or "")
            and "cvep_model_calib.npz" in (raison or ""),
            f"un fichier d'époques rangé sous un nom de modèle est refusé POUR CE QU'IL EST "
            f"({raison})")

        # Un `.npz` dont les tableaux sont de dtype OBJET, c'est-à-dire du pickle. `np.load(...,
        # allow_pickle=True)` DÉPICKLE au premier accès — donc exécute du code contenu dans le
        # fichier — et `charger` est précisément la fonction qui ouvre tout ce qui traîne dans
        # `data/`. Sans le drapeau, numpy refuse et l'étudiant lit « modèle illisible ».
        #
        # ⚠️ Ce que cette assertion protège EXACTEMENT, mesuré par analyse de mutation : « aucun
        # pickle n'est dépickle NULLE PART dans le chemin de chargement ». **Et la profondeur des
        # deux couches n'existe QUE sur le chemin rCCA** — c'est le piège que ce commentaire
        # affirmait à tort pour les deux décodeurs. Sur un fichier rCCA il y a bien deux `np.load`
        # (celui de `charger`, qui lit `codes`, et celui de `RCCAModel.load`), donc remettre
        # `allow_pickle=True` sur UN SEUL laisse cette assertion-ci verte. Sur un fichier eCCA,
        # `charger` ne lit qu'UN champ du fichier — `decoder`, une chaîne, qu'un `.npz` piégé
        # garde évidemment en chaîne pour franchir l'aiguillage : sa propre `np.load` ne peut donc
        # PAS voir le piège, et `CVEPModel.load` est la seule et unique couche. D'où la fixture
        # eCCA juste en dessous, sans laquelle y remettre le drapeau ne rougissait RIEN du dépôt.
        # La fixture rCCA vise la clé `codes` parce que c'est la seule que `charger` lit
        # elle-même, et son contenu est celui des VRAIS codes, pour que le contrôle de stimulus ne
        # masque pas le résultat.
        pickle_piege = _os.path.join(dossier, "cvep_rcca_model_pickle.npz")
        rcca_ok = _rcca(codes_du_jour)
        _np.savez(pickle_piege, codes=_np.asarray(codes_du_jour, dtype=object),
                  epochs=_np.asarray(rcca_ok._epochs), labels=rcca_ok._labels,
                  fs=250.0, refresh=60.0, band=_np.asarray([2.0, 45.0]),
                  channels=_np.asarray(rcca_ok.channels, dtype=int), event="refe", enc=0.30,
                  cv=0.5, decoder="rCCA")
        with _np.load(pickle_piege, allow_pickle=True) as d:
            chk(d["codes"].dtype == object,
                f"fixture : le fichier contient VRAIMENT un tableau d'objets ({d['codes'].dtype})")
        _m, raison = charger(pickle_piege)
        chk(_m is None and "illisible" in (raison or "")
            and "cvep_rcca_model_pickle.npz" in (raison or ""),
            f"un .npz qui contient du PICKLE est refusé, pas dépickle — `charger` ouvre tout ce "
            f"qui traîne dans data/ ({raison})")
        chk(pickle_piege not in modeles_disponibles(dossier),
            "...et il n'apparaît donc pas dans la liste proposée à l'étudiant")

        # Le JUMEAU eCCA du piège ci-dessus, et il n'est PAS redondant (cf. le ⚠️) : sur ce
        # chemin-là, `CVEPModel.load` est la SEULE couche. Scénario concret : un
        # `cvep_model_dupote.npz` reçu d'un camarade ou produit par un script tiers, sans champ
        # `decoder` (donc « eCCA hérité », le chemin le plus permissif) et avec `w` en dtype
        # objet. `modeles_disponibles` ouvre tout ce qui traîne dans `data/` : si le drapeau
        # revenait, le pickle s'exécuterait à l'OUVERTURE DU CATALOGUE de la console, avant tout
        # choix de l'étudiant.
        piege_ecca = _os.path.join(dossier, "cvep_model_pickle.npz")
        me = _ecca()
        _np.savez(piege_ecca, w=_np.asarray([me.w], dtype=object), template=me.template,
                  fs=me.fs, refresh=me.refresh, code_len=me.code_len,
                  band=_np.asarray(me.band), n_targets=6,
                  channels=_np.asarray(me.channels, dtype=int), cv=me.cv_)
        with _np.load(piege_ecca, allow_pickle=True) as d:
            chk(d["w"].dtype == object and "decoder" not in d.files,
                f"fixture : ce fichier eCCA contient VRAIMENT un tableau d'objets, et pas de "
                f"champ `decoder` — le chemin le plus permissif ({d['w'].dtype})")
        _m, raison = charger(piege_ecca)
        chk(_m is None and "illisible" in (raison or "")
            and "cvep_model_pickle.npz" in (raison or ""),
            f"un .npz eCCA qui contient du PICKLE est refusé, pas dépickle ({raison})")
        chk(piege_ecca not in modeles_disponibles(dossier),
            "...et il n'apparaît donc pas dans la liste proposée à l'étudiant")
        _os.remove(piege_ecca)   # la section 5 compte la liste EXACTE du dossier

        # Un décodeur déclaré que ce produit ne connaît pas : fichier venu d'une version plus
        # récente, ou bricolé. On le NOMME plutôt que de retomber en silence sur l'eCCA.
        exotique = _os.path.join(dossier, "cvep_model_exotique.npz")
        m = _ecca()
        _np.savez(exotique, w=m.w, template=m.template, fs=m.fs, refresh=m.refresh,
                  code_len=m.code_len, band=_np.asarray(m.band), n_targets=6,
                  channels=_np.asarray(m.channels, dtype=int), cv=m.cv_, decoder="xCCA")
        _m, raison = charger(exotique)
        chk(_m is None and "xCCA" in (raison or ""),
            f"un décodeur déclaré inconnu est refusé EN LE NOMMANT, pas ramené à l'eCCA "
            f"({raison})")

        # --- 4. La description affichée à côté de chaque modèle. ------------------------------
        d = decrire(chemin_rcca)
        chk(d["nom"] == "cvep_rcca_model.npz" and d["decodeur"] == "rCCA",
            f"la description porte le nom du fichier ET son décodeur ({d['nom']}, {d['decodeur']})")
        chk(isinstance(d["cv_loo"], float) and 0.0 <= d["cv_loo"] <= 1.0
            and d["n_targets"] == 6 and d["n_epoques"] == 12,
            f"...la justesse leave-one-out, le nombre de cibles et d'époques "
            f"({d['cv_loo']}, {d['n_targets']}, {d['n_epoques']})")
        chk(d["date"] and d["probleme"] is None, f"...et une date lisible ({d['date']})")
        chk(decrire(chemin_ecca)["decodeur"] == "eCCA"
            and decrire(chemin_ecca)["n_targets"] == 6,
            f"un eCCA se décrit avec SON décodeur ({decrire(chemin_ecca)})")
        d_refuse = decrire(chemin_gold)
        chk(d_refuse["probleme"] and d_refuse["cv_loo"] is None and d_refuse["decodeur"] is None,
            f"un modèle refusé se décrit par SON PROBLÈME, sans chiffres ({d_refuse['probleme']})")
        for entree in (None, "", 0):
            d_vide = decrire(entree)
            chk(d_vide["probleme"] and d_vide["cv_loo"] is None and d_vide["nom"] == "",
                f"decrire({entree!r}) décrit un problème au lieu de lever ({d_vide['probleme']})")

        # --- 5. La liste : les deux décodeurs ensemble, du plus récent au plus ancien. ---------
        # On renomme pour que le tri alphabétique et le tri chronologique DIVERGENT : sans
        # `key=getmtime`, l'ordre alphabétique inversé rendrait ["…_z", "…_a"], l'OPPOSÉ de
        # l'ordre attendu. Et les deux familles de noms doivent apparaître dans la même liste :
        # la question posée à l'étudiant est « quel modèle », pas « quel algorithme ».
        vieil_ecca = _os.path.join(dossier, "cvep_model_z.npz")
        _os.rename(chemin_ecca, vieil_ecca)
        _os.utime(vieil_ecca, (1_600_000_000, 1_600_000_000))
        _os.utime(chemin_herite, (1_600_000_100, 1_600_000_100))
        dispo = modeles_disponibles(dossier)
        chk(dispo == [chemin_rcca, chemin_herite, vieil_ecca],
            f"les deux décodeurs sont dans la MÊME liste, du plus récent au plus ancien ({dispo})")
        chk(all(charger(c)[0] is not None for c in dispo),
            "...et tout ce qui est listé se charge réellement")

        # --- 6. Ce que la liste laisse DEHORS. ------------------------------------------------
        # Le dossier contient exactement les deux pièges, et le résultat attendu reste [] :
        #   (a) un modèle PARFAITEMENT valide sous un nom hors motif — il rougit l'élargissement
        #       `MOTIFS = ("*.npz",)` qu'on écrit sans y penser ;
        #   (b) un fichier illisible sous un nom qui, lui, correspond — il rougit la suppression
        #       du filtre `charger(...)` et son inversion.
        vide = tempfile.mkdtemp(prefix="cvep_models_vide_")
        try:
            hors_motif = _ecca().save(_os.path.join(vide, "modele_cvep.npz"), n_targets=6)
            chk(_os.path.isfile(hors_motif), "fixture : le modèle hors-motif existe bien")
            illisible = _os.path.join(vide, "cvep_model_illisible.npz")
            with open(illisible, "wb") as f:
                f.write(b"ceci n'est pas une archive numpy")
            chk(modeles_disponibles(vide) == [],
                f"un dossier sans AUCUN modèle utilisable rend [], sans lever — ni le fichier "
                f"hors-motif, ni l'illisible ({modeles_disponibles(vide)})")

            # ...et un candidat qui s'ÉVAPORE entre le `glob` et le tri par date ne fait pas
            # lever : la console ouvre son catalogue pendant qu'une calibration écrit, et
            # `Param.choices_status` classerait cette course en « DÉFAUT de déclaration ».
            disparu = _os.path.join(vide, "cvep_model_disparu.npz")
            vrai_glob = _glob.glob
            _glob.glob = lambda motif: [disparu, illisible]
            try:
                liste_course, leve = modeles_disponibles(vide), None
            except Exception as e:      # noqa: BLE001 - c'est l'exception elle-même qu'on teste
                liste_course, leve = None, f"{type(e).__name__}: {e}"
            finally:
                _glob.glob = vrai_glob
            chk(leve is None and liste_course == [],
                f"un fichier disparu entre le glob et le tri par date ne fait pas lever la liste "
                f"({leve or liste_course})")
        finally:
            shutil.rmtree(vide, ignore_errors=True)
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    print(f"[cvep-models] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
