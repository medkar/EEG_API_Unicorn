"""Les modèles c-VEP sur le disque : lesquels existent, lequel se charge vraiment, et AVEC QUEL
DÉCODEUR.

Jumeau de `mi_models.py` / `p300_models.py` / `errp_models.py`, et pour la même raison : un modèle
est propre à UNE personne, et le mode doit pouvoir dire « aucun choix disponible » plutôt que
démarrer muet. Une chose de plus ici : le c-VEP a **deux décodeurs** sur le même stimulus (eCCA et
rCCA), et **c'est le fichier qui déclare le sien**. L'étudiant choisit un modèle, pas un algorithme.

⚠️ **Comment le décodeur se lit, et pourquoi pas autrement.** Chaque `save` écrit un champ
`decoder` (`"eCCA"` | `"rCCA"`). Un fichier **sans ce champ** est un **eCCA**
(`data/cvep_model.npz` est dans ce cas). Inférer le décodeur de la présence de telle ou telle clé (« il y a `codes`, donc
c'est du rCCA ») casserait au premier champ ajouté ; un champ explicite se lit et se teste.

Trois différences avec les trois jumeaux, voulues :

1. **Pas de refus de « modèle hérité » par nom de module.** C'est le refus central des trois autres
   (un pickle `joblib` grave le chemin de module de sa classe). Le c-VEP écrit du `np.savez` de
   **tableaux purs** : aucun nom de classe dans le fichier, donc rien à ressusciter (cf.
   `cvep_decoder._selftest`). Le refus qui le remplace est le n° 2.
2. **Un refus que les autres n'ont pas : le STIMULUS.** Un modèle rCCA porte ses **codes**. Un
   modèle rCCA calibré sur des codes que plus aucun émetteur n'affiche (par exemple des codes Gold,
   une hypothèse réfutée et retirée du produit) ferait décoder un stimulus fantôme, avec des
   scores d'apparence normale. Le contrôle vit **ici** et pas dans le mode, pour que le fichier ne
   soit jamais *proposé* : un refus au démarrage du mode l'aurait laissé dans la liste.
   Le contrôle jumeau côté eCCA est dans `core/modes/cvep.py` (`_desaccord_code`) : un modèle
   eCCA ne porte pas de codes, seulement un `code_len` et un `n_targets`, et ces désaccords se
   réparent en restaurant `CVEP_BITS`/`CVEP_N_TARGETS` ; le mode le dit en nommant les deux
   nombres, ce qu'une disparition de la liste ne dirait pas.
   ⚠️ **Il ne couvre PAS `CVEP_TAPS`**, contrairement au refus rCCA : `CVEPModel.save`
   n'enregistre pas les taps, donc `_desaccord_code` ne compare que la LONGUEUR du code. Passer
   `CVEP_TAPS` de `(6, 5)` à `(6, 1)` (l'autre polynôme primitif de degré 6) laisse `code_len = 63`
   inchangé : le modèle eCCA est accepté, et son template est corrélé à une m-séquence que plus
   aucun écran n'affiche. Un modèle rCCA de la même séance est refusé, lui, parce qu'il porte ses
   codes.
3. **`decrire` rend `cv_loo`, pas `cv_auc`.** Le chiffre honnête du c-VEP est une **justesse
   leave-one-out à 6 cibles** (hasard 16,7 %), pas une AUC à deux classes ; les nommer pareil
   serait un mensonge d'étiquette (`mi_models.decrire` diverge de la même façon avec
   `cv_groupee`). Les quatre clés que les quatre modules partagent sont `chemin`, `nom`, `date`,
   `probleme`.

⚠️ **Charger un modèle rCCA coûte plus cher qu'un eCCA** : `RCCAModel.load` ne sérialise pas
l'objet pyntbci, il **ré-ajuste** depuis les époques stockées. Mesuré sur ce poste : ~0,3 s et
~750 ko par modèle rCCA, contre ~1 ms et 4 ko pour un eCCA. La liste se construit à l'ouverture du
catalogue, pas en boucle ; avec de nombreux modèles rCCA dans `data/`, c'est ici qu'il faut
regarder.

⚠️ **`pyntbci` est une dépendance du MOTEUR, pas d'un outil d'analyse.** Ré-ajuster au chargement
veut dire que sans elle, aucun modèle rCCA ne se charge ; comme `modeles_disponibles` ne garde que
ce qui se charge, ils disparaîtraient tous de la liste de la console sans un mot. Les deux moitiés
du remède vivent ici : `charger` NOMME le cas (`PyntbciManquant`, message actionnable) au lieu
d'annoncer « modèle illisible », et `modeles_disponibles` compte les retirés et le dit. Les
modèles eCCA ne dépendent de rien de tout ça.

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
from core.i18n import tr  # noqa: E402

# Deux familles de noms, une par décodeur — d'où un TUPLE là où les trois jumeaux ont une seule
# chaîne. Un motif unique élargi (`cvep*model*.npz`) attraperait la même chose aujourd'hui, mais
# aussi tout fichier futur portant « model » dans son nom ; deux motifs explicites disent quels
# fichiers sont des modèles.
MOTIFS = ("cvep_model*.npz", "cvep_rcca_model*.npz")

# Le décodeur d'un fichier qui ne déclare rien : voir le ⚠️ de la docstring.
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
    # modèles est vide (dépôt fraîchement cloné, aucun entraînement fait). `charger` ne lève
    # jamais, et `os.path.isfile(None)` lèverait. Le refus dit quoi faire.
    if not chemin:
        # Le stimulus c-VEP est verrouillé à la frame : une FENÊTRE de `src/stimulus/` le rend
        # (cf. `Calib(kind="fenetre")` du mode). Ce texte est celui de l'aide du réglage
        # « Modèle entraîné » : le même geste est dit du même mot aux deux endroits.
        return None, tr("mode.modele.aucun", mode="c-VEP")
    if not _os.path.isfile(chemin):
        return None, tr("mode.modele.introuvable", chemin=chemin)
    nom = _os.path.basename(chemin)
    try:
        # ⚠️ PAS d'`allow_pickle=True` : le format c-VEP n'a que des tableaux de types simples,
        # et `np.load(..., allow_pickle=True)` DÉPICKLE au premier accès, c'est-à-dire exécute du
        # code contenu dans le fichier. Cette fonction ouvre des fichiers dont on ne sait rien
        # (`modeles_disponibles` charge tout ce qui traîne dans `data/`). Sans le drapeau, un
        # `.npz` piégé lève, et le refus dit « modèle illisible » au lieu de l'exécuter.
        with _np.load(chemin) as d:
            presentes = set(d.files)
            # Le champ d'aiguillage. Absent = eCCA.
            decodeur = str(d["decoder"]) if "decoder" in presentes else DECODEUR_HERITE
            codes = _np.asarray(d["codes"]) if "codes" in presentes else None
    except Exception as e:      # noqa: BLE001 - un .npz casse de mille façons, toutes équivalentes
        # `np.load` refuse un fichier qui n'est pas une archive ; un `.npy` nu n'a pas de `.files`
        # (AttributeError). Les deux se disent de la même façon à l'étudiant.
        return None, tr("mode.modele.illisible", erreur=type(e).__name__, nom=nom)

    if decodeur not in _CLASSES:
        return None, tr("mode.cvep.modele.decodeur_inconnu", decodeur=repr(decodeur),
                        attendus=tr("mode.cvep.modele.ou").join(sorted(_CLASSES)), nom=nom)
    classe, requises = _CLASSES[decodeur]
    manquantes = [c for c in requises if c not in presentes]
    if manquantes:
        # Cas concret : un `cvep_calib_*.npz` (des époques de calibration) recopié sous un nom
        # de modèle. Sans ce contrôle, `load` lève un KeyError et on annonce « illisible », ce qui
        # envoie chercher une corruption là où il n'y a qu'un fichier mal rangé.
        return None, tr("mode.cvep.modele.incomplet", decodeur=decodeur,
                        manquantes=", ".join(manquantes), nom=nom)

    # Le refus de STIMULUS se pose AVANT `load` : pour un modèle rCCA, `load` ré-ajuste pyntbci
    # sur les époques stockées (~0,3 s), inutile pour un fichier qu'on va refuser. Pourquoi :
    # voir le n° 2 de la docstring du module.
    if decodeur == "rCCA":
        attendus = _codes_affiches()
        if codes is None or codes.shape != attendus.shape or not _np.array_equal(codes, attendus):
            # Dire LEQUEL des deux désaccords, parce qu'ils se réparent différemment : une
            # dimension qui change vient de la config (CVEP_BITS/CVEP_N_TARGETS), un contenu qui
            # change à dimensions égales vient d'une autre FAMILLE de codes (Gold) ou d'un autre
            # ordre de lignes (CVEP_LAG_ROTATION).
            if codes is None or codes.shape != attendus.shape:
                forme = (tr("mode.cvep.modele.aucun_code") if codes is None
                         else "x".join(str(n) for n in codes.shape))
                quoi = tr("mode.cvep.modele.codes_dimensions", forme=forme,
                          attendu="x".join(str(n) for n in attendus.shape))
            else:
                # ⚠️ Ce refus signale un VRAI défaut, à toute rotation : la calibration écrit ses
                # codes DANS L'ORDRE DU PLAN, donc un modèle frais est accepté quelle que soit
                # `CVEP_LAG_ROTATION`. Ne jamais présenter ce désaccord comme un cas normal :
                # l'étudiant apprendrait à passer outre un vrai défaut. Le message nomme les
                # causes réelles (autre famille de codes, ancien modèle aux codes par lag
                # croissant, `CVEP_LAG_ROTATION` changé qui PERMUTE les lignes).
                quoi = tr("mode.cvep.modele.codes_contenu", rotation=CVEP_LAG_ROTATION)
            return None, tr("mode.cvep.modele.autres_codes", quoi=quoi, nom=nom)

    try:
        modele = classe.load(chemin)
    except PyntbciManquant as e:
        # Capté AVANT le `except Exception` suivant, qui ne garde que `type(e).__name__` :
        # sinon un fichier sain serait annoncé « modèle illisible (PyntbciManquant) », et
        # l'étudiant chercherait une corruption là où il manque un `pip install`. Le message
        # dit quoi FAIRE (`pip install -r requirements.txt`) et que les modèles eCCA restent
        # utilisables sans cette dépendance.
        return None, tr("mode.cvep.modele.pyntbci", message=str(e), nom=nom)
    except Exception as e:      # noqa: BLE001 - un modèle sur disque casse de mille façons
        return None, tr("mode.modele.illisible", erreur=type(e).__name__, nom=nom)
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
    # La clé de tri s'évalue sur TOUS les candidats : un fichier qui disparaît (ou qu'un
    # antivirus verrouille) entre le `glob` et la clé ferait sortir un `FileNotFoundError` de
    # cette fonction, que `Param.choices_status` classerait en défaut de déclaration, alors que
    # ce n'est qu'une course bénigne (catalogue ouvert pendant qu'un entraînement écrit). D'où
    # le `isfile`, comme dans `errp_models`.
    candidats = set()
    for motif in MOTIFS:
        candidats.update(_glob.glob(_os.path.join(dossier, motif)))
    chemins = sorted(candidats,
                     key=lambda c: _os.path.getmtime(c) if _os.path.isfile(c) else 0.0,
                     reverse=True)
    # ⚠️ Une dépendance manquante ne doit pas faire DISPARAÎTRE des modèles en silence. Ce
    # filtre écarte tout ce qui ne se charge pas, ce qui est juste, sauf pour `pyntbci` : sans
    # lui, `RCCAModel.load` échoue et TOUS les modèles rCCA s'évaporeraient de la liste de la
    # console sans un mot. On les compte donc, et on le DIT une fois ; la liste reste honnête,
    # ces fichiers ne sont réellement pas chargeables ici.
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

    Aucun appelant en production pour l'instant (comme `errp_models.decrire`) : cette forme existe
    pour la parité avec les trois jumeaux, que la console lira pour afficher les listes de
    modèles.
    """
    modele, raison = charger(chemin)
    # `chemin and` court-circuite None, "" et l'entier 0, que `os.path.isfile` prendrait pour un
    # descripteur de fichier (stdin) ; même précaution que chez les jumeaux.
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
    # eCCA : `n_targets` est ce que la calibration a ENREGISTRÉ (0 = inconnu) ;
    # rCCA : c'est le nombre de codes, donc toujours connu.
    cibles = getattr(modele, "n_targets", 0)
    infos["n_targets"] = int(cibles) or None
    epoques = getattr(modele, "_labels", None)
    infos["n_epoques"] = int(len(epoques)) if epoques is not None else None
    return infos


def _selftest():
    """Sur un dossier temporaire : les deux décodeurs, un modèle hérité, un stimulus réfuté.

    Aucun fichier du vrai `data/` n'est lu ni écrit : `data/` contient des enregistrements EEG
    d'une personne identifiable. Toutes les fixtures sont fabriquées dans un dossier temporaire,
    nettoyé dans un `finally`.
    """
    import contextlib as _contextlib
    import io as _io
    import shutil
    import tempfile

    from core.cvep_code import m_sequence
    from core.config import CVEP_BAND, CVEP_CHANNELS

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

        # --- 1. Le fichier DÉCLARE son décodeur. ----------------------------------------------
        # Le moteur choisit sa classe de décodage d'après ce champ. Deviner d'après les clés
        # présentes marcherait aujourd'hui et casserait au premier champ ajouté.
        chemin_ecca = _ecca().save(_os.path.join(dossier, "cvep_model.npz"), n_targets=6)
        chemin_rcca = _rcca(codes_du_jour).save(
            _os.path.join(dossier, "cvep_rcca_model.npz"))

        # Le modèle SANS champ `decoder` : fabriqué à la main, pas par un `save()` amputé, pour
        # avoir exactement la forme d'un ancien fichier (`data/cvep_model.npz`).
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

        # --- 1 bis. Un modèle sans `secteur_hz` décode comme il a appris. -------------------
        # Un tel fichier a appris SANS coupe-bande et doit décoder sans. Un `load` qui retomberait
        # sur le secteur du poste (`... else SECTEUR_HZ`) ferait corréler son template contre un
        # signal filtré autrement que celui qu'il a appris : plausible, et faux. Vérifié sur
        # l'ATTRIBUT et sur le FILTRE réellement appliqué (espion sur `core.filtrage.sections`,
        # par où passe tout filtrage des décodeurs), au chargement (le rCCA se ré-ajuste) comme
        # au décodage (`scores`).
        import core.filtrage as _filtrage

        @_contextlib.contextmanager
        def _filtrages():
            vrai, vus = _filtrage.sections, []

            def _espion(fs, bande, secteur_hz=None, ordre=_filtrage.ORDRE):
                vus.append((tuple(float(b) for b in bande), secteur_hz))
                return vrai(fs, bande, secteur_hz, ordre)

            _filtrage.sections = _espion
            try:
                yield vus
            finally:
                _filtrage.sections = vrai

        # Le rCCA sans `secteur_hz` : avec `decoder`, sans `secteur_hz`. Dans un sous-dossier :
        # la section 5 compte la liste EXACTE.
        dossier_herite = _os.path.join(dossier, "herite")
        _os.makedirs(dossier_herite)
        vieux_r = _rcca(codes_du_jour)
        chemin_rcca_herite = _os.path.join(dossier_herite, "cvep_rcca_model_herite.npz")
        _np.savez(chemin_rcca_herite, codes=vieux_r.codes, epochs=_np.asarray(vieux_r._epochs),
                  labels=vieux_r._labels, fs=vieux_r.fs, refresh=vieux_r.refresh,
                  band=_np.asarray(vieux_r.band), channels=_np.asarray(vieux_r.channels, dtype=int),
                  event=vieux_r.event, enc=vieux_r.enc, decoder="rCCA", cv=0.5)
        for chemin_h in (chemin_herite, chemin_rcca_herite):
            with _np.load(chemin_h) as d:
                chk("secteur_hz" not in d.files,
                    f"fixture : {_os.path.basename(chemin_h)} n'a VRAIMENT pas `secteur_hz`")

        plan_h, _code_h = build_targets()
        fen_h = _np.random.default_rng(2).normal(0.0, 1.0, (2 * 262 + 250, len(CVEP_CHANNELS)))
        for chemin_h in (chemin_herite, chemin_rcca_herite):
            nom_h = _os.path.basename(chemin_h)
            with _filtrages() as vus_h:
                herite, raison_h = charger(chemin_h)
                if herite is not None:
                    if herite.decoder == "eCCA":
                        herite.scores(fen_h, 0, [c["lag"] for c in plan_h], n_cycles=2)
                    else:
                        herite.scores(fen_h, 0, 2)
            chk(herite is not None and herite.secteur_hz is None,
                f"{nom_h} : un modèle SANS `secteur_hz` se charge SANS coupe-bande, pas avec le "
                f"secteur du poste ({getattr(herite, 'secteur_hz', raison_h)})")
            chk(len(vus_h) >= 1 and set(vus_h) == {(tuple(float(b) for b in CVEP_BAND), None)},
                f"{nom_h} : ...et il FILTRE sans, au chargement comme au décodage, sur sa bande "
                f"d'origine ({len(vus_h)} filtrage(s), {sorted(set(vus_h), key=str)})")

        # --- 2. Le refus de STIMULUS : des codes que plus aucun émetteur n'affiche. ----------
        # Un modèle rCCA calibré sur d'autres codes (par exemple des codes Gold) apparaîtrait dans
        # la liste de la console et le moteur décoderait un stimulus fantôme. (Les codes de la
        # fixture viennent d'un AUTRE polynôme primitif : `core/` n'importe pas `research/`, et
        # n'importe quel jeu de codes différent fait le même travail.)
        autre = m_sequence(6, (6, 1))
        codes_etrangers = _np.stack([_np.roll(autre, -l) for l in (0, 10, 21, 32, 42, 52)])
        chk(not _np.array_equal(codes_etrangers, codes_du_jour),
            "fixture : ces codes ne sont VRAIMENT pas ceux du stimulus d'aujourd'hui")
        chemin_gold = _rcca(codes_etrangers).save(
            _os.path.join(dossier, "cvep_rcca_model_gold.npz"))
        _m, raison = charger(chemin_gold)
        chk(_m is None and "réfut" in (raison or "") and "ré-entraîne" in (raison or "").lower()
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
        # 2 ter. Le message ne doit pas EXCUSER ce refus, y compris à `CVEP_LAG_ROTATION` non nul :
        # la calibration écrit ses codes dans l'ordre du plan, donc un modèle frais est accepté
        # à toute rotation et un désaccord est un vrai défaut. ⚠️ La rotation du dépôt vaut 0 :
        # ce test DOIT la détourner, sinon l'assertion serait creuse. Assertion sur le TEXTE : un
        # message qui présenterait le désaccord comme normal apprendrait à passer outre.
        global CVEP_LAG_ROTATION
        _rot_avant = CVEP_LAG_ROTATION
        CVEP_LAG_ROTATION = 2
        try:
            _m, raison_rot = charger(chemin_permute)
        finally:
            CVEP_LAG_ROTATION = _rot_avant
        chk("ATTENDU" not in (raison_rot or "") and "ré-entraîne" in (raison_rot or "").lower()
            and "CVEP_LAG_ROTATION" in (raison_rot or ""),
            f"...et à CVEP_LAG_ROTATION NON NUL ce refus reste présenté comme un VRAI défaut à "
            f"réparer, jamais comme un cas attendu : la calibration écrit ses codes dans l'ordre "
            f"du plan, donc un modèle frais est ACCEPTÉ à toute rotation "
            f"({raison_rot})")

        # 2 quater. `pyntbci` ABSENT : le cas est NOMMÉ, et les modèles rCCA ne s'évaporent pas
        # de la liste en silence. On simule la dépendance manquante à l'endroit exact où elle
        # manquerait : `_fit_clf`, le seul `import pyntbci` du produit, appelé par `load`.
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

        # Un `.npz` au bon nom mais qui n'est pas un modèle : un `cvep_calib_*.npz` (des ÉPOQUES)
        # recopié sous un nom de modèle. Sans le contrôle de clés, `load` lève un KeyError et on
        # annonce « illisible », là où il n'y a qu'un fichier mal rangé.
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
        # ⚠️ Cette assertion protège : « aucun pickle n'est dépickle NULLE PART dans le chemin de
        # chargement ». Sur un fichier rCCA il y a DEUX `np.load` (celui de `charger`, qui lit
        # `codes`, et celui de `RCCAModel.load`) : remettre `allow_pickle=True` sur un seul
        # laisserait cette assertion verte. Sur un fichier eCCA, `charger` ne lit qu'UN champ,
        # `decoder`, une chaîne que le `.npz` piégé garde en chaîne pour franchir l'aiguillage :
        # sa `np.load` ne voit pas le piège, et `CVEPModel.load` est la seule couche. D'où la
        # fixture eCCA plus bas. La fixture rCCA vise la clé `codes`, la seule que `charger` lit
        # elle-même, avec le contenu des VRAIS codes pour que le contrôle de stimulus ne masque
        # pas le résultat.
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

        # Le jumeau eCCA du piège ci-dessus, non redondant (cf. le ⚠️) : sur ce chemin,
        # `CVEPModel.load` est la SEULE couche. Scénario : un modèle reçu d'un camarade ou produit
        # par un script tiers, sans champ `decoder` (le chemin le plus permissif) et avec `w` en
        # dtype objet. `modeles_disponibles` ouvre tout ce qui traîne dans `data/` : avec le
        # drapeau, le pickle s'exécuterait à l'OUVERTURE DU CATALOGUE de la console.
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

        # Un décodeur déclaré que ce produit ne connaît pas (fichier d'une autre version, ou
        # bricolé) : on le NOMME plutôt que de retomber en silence sur l'eCCA.
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
