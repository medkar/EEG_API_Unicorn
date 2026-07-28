# Console d'expérimentation — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

> Écrit le 2026-07-28 à partir de
> [docs/superpowers/specs/2026-07-27-console-experimentation-design.md](../specs/2026-07-27-console-experimentation-design.md),
> validée section par section. Document interne, en français comme la spec.

**Goal :** remplacer le moteur mono-mode et son tableau de bord web par un **contrat de mode**
déclaré, un moteur qui fait tourner **plusieurs modes à la fois**, et une **console PySide6**
(grille + page de mode) où un étudiant règle, observe et publie mode par mode.

**Architecture :** chaque mode devient un `ModeSpec` (ce qu'il est, ce qui s'y règle, ce qu'il
publie) posé à côté de son `ModeRuntime` (l'état vivant : phase, décodeur, publieur). Le moteur ne
garde que le vraiment commun — session casque, tampon glissant, horloge, qualité — et sa boucle
itère sur `self.active: dict[str, ModeRuntime]`. La console lit `snapshot()` par `QTimer` et
n'envoie que des commandes : **aucune logique qui ne soit déjà dans le moteur**.

**Tech Stack :** Python 3.12 · numpy/scipy · BrainFlow · pylsl · **PySide6 + pyqtgraph** (nouveau) ·
plus de FastAPI/uvicorn.

## Global Constraints

Ces règles s'appliquent à **toutes** les tâches. Elles ne sont pas répétées ensuite.

- **Frontière de paquets** : `core` n'importe **ni `research` ni `console`**, et **aucun pygame** —
  le moteur tourne sans écran. `console` importe `core`. `research` importe `core`. Vérifié par un
  test à la tâche 8.
- **Les deux smokes doivent rester verts à CHAQUE tâche** :
  `python src/core/server.py --smoke` et `python src/research/app.py --smoke`. C'est le garde-fou
  contre le risque n°1 de la spec (§9, régression silencieuse sur un moteur validé casque).
- ⚠️ **Ne laisser tourner AUCUN moteur pendant un test** : les noms de flux sont un contrat public,
  donc identiques pour toutes les instances.
- **Contrat public inchangé** : noms de flux (`EEG_API_Unicorn_*`), noms de voies, unités, et les
  valeurs de `phase` publiées sur `status` (`streaming` / `warmup` / `baseline` / `decoding`).
- **Langue** : code, commentaires et docstrings en **français** ; messages de commit en **anglais**.
- **Public** : des étudiants qui liront et modifieront ce code. Un commentaire explique *pourquoi*,
  pas *quoi*.
- **Constantes à reprendre telles quelles** depuis `src/core/config.py`, jamais recopiées en dur :
  `WINDOW_S = 1.5` · `BANDPASS = (5.0, 40.0)` · `SSVEP_WARMUP_S = 15.0` · `SSVEP_BASELINE_S = 8.0` ·
  `NEURO_WARMUP_S = 15.0` · `NEURO_BASELINE_S = 25.0` · `NEURO_SMOOTH = 0.85` ·
  `NEURO_REBASELINE_S = 180.0` · `CH_NAMES` (8 voies).
- **`status` d'un `ModeSpec` a exactement trois valeurs** : `"moteur"` · `"appli_pygame"` ·
  `"prevu"`. Invariant vérifié : `status == "moteur"` ⟺ le mode a un runtime ; sinon `unavailable`
  est non vide.
- **Commit à la fin de chaque tâche**, avec les deux smokes verts.

## Structure des fichiers

**Créés**

| Fichier | Responsabilité |
|---|---|
| `src/core/modes/__init__.py` | docstring du paquet : ce qu'est un mode, la règle de frontière |
| `src/core/modes/contract.py` | `ModeSpec` / `Param` / `Rest` / `Calib`, validation, `client_snippet` |
| `src/core/modes/runtime.py` | `ModeRuntime` : la machine de phases commune (chauffe → repos → décodage) |
| `src/core/modes/registry.py` | le catalogue : tous les `ModeSpec`, publiés ou non ; sérialisation |
| `src/core/modes/raw.py` | `SPEC` + `RawRuntime` — diffuser le brut est un mode comme un autre |
| `src/core/modes/ssvep.py` | `SPEC` + `SsvepRuntime` — s'appuie sur `core/cca_decoder.py` |
| `src/core/modes/neuro.py` | `SPEC` + `NeuroRuntime` — s'appuie sur `core/neuro_monitor.py` |
| `src/core/modes/external.py` | c-VEP, P300, ErrP, MI : `ModeSpec` seuls, sans runtime |
| `src/console/__init__.py` | docstring : la console est un CLIENT du moteur |
| `src/console/app.py` | point d'entrée, fil du moteur, `QTimer`, `--smoke` |
| `src/console/banner.py` | bandeau permanent : liaison, σ, référence décrochée |
| `src/console/grid.py` | la grille-tableau de bord et ses tuiles |
| `src/console/mode_page.py` | la page d'un mode : sortie en direct · réglages · brancher un client |
| `src/console/params_form.py` | formulaire généré depuis `spec.params`, en lecture-écriture |
| `src/console/live_views.py` | les trois rendus de sortie : barres actives, indices passifs, tracés |

**Modifiés**

| Fichier | Changement |
|---|---|
| `src/core/server.py` | boucle multi-modes, nouvelle API de commande, `snapshot`, `recent_window`, CLI, smokes |
| `src/core/lsl_io.py` | extraire `ssvep_channel_labels(freqs)` pour une seule vérité sur les voies |
| `src/core/__init__.py` | le graphe de dépendances : `modes/` entre, `dashboard` sort |
| `requirements.txt` | + PySide6, pyqtgraph ; − fastapi, uvicorn |
| `docs/SPEC.md` | §12.2 amendée (décision d'origine ET son renversement), §3.1 : le paquet `console` |
| `README.md` | commandes, dépendances, ce qu'un étudiant lance |
| `CLAUDE.md` | les commandes utiles |

**Supprimés** : `src/core/dashboard.py`, `src/core/dashboard.html`.

## Écarts assumés par rapport à la spec

Trois points où le plan précise ou dévie de la spec. Chacun est un choix, pas un oubli.

1. **`Param.constraint` (str) devient `Param.constraints` (tuple)**. La spec nomme deux contraintes
   croisées, `"separables"` et `"dans_la_bande"` — or les fréquences SSVEP ont besoin **des deux**.
   Un seul champ texte ne peut pas les porter.
2. **`n_targets` n'est pas exposé dans ce chantier.** Le champ `Param.proposes` existe, est vérifié
   par le test d'intégrité, et reste inutilisé : c'est ce que demande la spec §3.1 (« le contrat doit
   seulement la permettre »). Le nombre de cibles se règle malgré tout — c'est la **longueur** de la
   liste `freqs`, bornée par `count=(2, 8)`. L'étudiant contrôle donc bien le nombre ET les
   fréquences, sans demi-mécanique de proposition livrée à moitié.
3. **`ModeSpec.channels_fn`**, un champ optionnel absent de la spec. Les voies du flux SSVEP
   dépendent des fréquences réglées (`score_15Hz`…) : une liste figée mentirait dès le premier
   changement de réglage. Les modes à voies fixes (brut, neuro) n'en ont pas besoin.

---

## Tâche 0 : lever le risque PySide6 avant d'écrire du Qt

La spec §9 nomme ce risque : « PySide6 sur ce poste. Jamais installé ici ; à vérifier tôt, avant
d'écrire du code qui en dépend. » Vérifié le 2026-07-28 : **absent**, comme pyqtgraph. Python 3.12.10.

Cette tâche ne produit aucun code d'application — elle produit la **certitude** que le pari de la
spec tient sur ce poste. Si elle échoue, tout le chantier 1 est à re-décider, et il vaut mieux
l'apprendre maintenant qu'après avoir refondu le moteur.

**Files:**
- Modify: `requirements.txt`
- Create: `C:\Users\Lab_IA\AppData\Local\Temp\claude\...\scratchpad\qt_check.py` (jetable, non commité)

**Interfaces:**
- Consumes: rien.
- Produces: `PySide6` et `pyqtgraph` importables ; `QT_QPA_PLATFORM=offscreen` fonctionnel (c'est le
  mode dans lequel tournera `src/console/app.py --smoke`).

- [ ] **Step 1 : installer**

```powershell
pip install PySide6 pyqtgraph
```

~100 Mo. Sans droits administrateur (l'utilisateur n'en a pas) — `pip` en user scope suffit.

- [ ] **Step 2 : écrire le test de fumée Qt** dans le scratchpad, fichier `qt_check.py`

```python
"""Vérifie que Qt démarre SANS écran — le mode dans lequel tournera le smoke de la console."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"   # AVANT l'import de PySide6, sinon sans effet

from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtCore import QTimer
import pyqtgraph as pg

app = QApplication([])
w = QLabel("EEG_API_Unicorn")
w.resize(320, 120)
w.show()

plot = pg.PlotWidget()
plot.plot([0, 1, 2, 3], [0.0, 1.0, -1.0, 0.5])
plot.resize(320, 120)
plot.show()

QTimer.singleShot(300, app.quit)
app.exec()
print("[qt] OK — QApplication, widget et courbe pyqtgraph montés en offscreen")
```

- [ ] **Step 3 : lancer**

Run: `python <scratchpad>/qt_check.py`
Expected: `[qt] OK — QApplication, widget et courbe pyqtgraph montés en offscreen`, code de retour 0.

Si ça échoue, **arrêter le plan ici** et remonter l'erreur : le choix PySide6 de la spec est à
rouvrir, pas à contourner.

- [ ] **Step 4 : mettre `requirements.txt` à jour**

Remplacer les deux lignes fastapi/uvicorn par :

```
PySide6>=6.6         # console d'expérimentation (src/console/) — remplace le tableau de bord web
pyqtgraph>=0.13      # tracés EEG temps réel dans la console (mode « brut »)
```

⚠️ `fastapi` et `uvicorn` ne sont retirés **qu'ici** : `src/core/dashboard.py` les utilise encore
et n'est supprimé qu'à la tâche 9. Entre les deux, le tableau de bord web reste lançable sur un
poste où ils sont déjà installés — c'est le cas de celui-ci. On ne casse rien qu'on n'ait remplacé.

- [ ] **Step 5 : vérifier que rien n'a bougé**

Run: `python src/core/server.py --smoke`
Expected: `[smoke] VERDICT : OK`, `[smoke-ssvep] VERDICT : OK`, `[smoke-neuro] VERDICT : OK`

- [ ] **Step 6 : commit**

```bash
git add requirements.txt
git commit -m "Prove PySide6 runs headless here before betting the UI on it"
```

---

## Tâche 1 : le contrat d'un mode

Le point dur de la spec §1 : « un mode n'existe pas comme objet ». Cette tâche crée l'objet. Elle ne
touche à rien d'existant — c'est du code neuf, testable seul.

L'intérêt du `Param` est qu'**un seul objet sert trois usages** : générer le champ de formulaire,
valider côté moteur, afficher l'aide. La validation écrite à la main pour `set_freqs` le 2026-07-27
devient ici une contrainte **déclarée**, appliquée par le même code pour tous les modes.

**Files:**
- Create: `src/core/modes/__init__.py`
- Create: `src/core/modes/contract.py`

**Interfaces:**
- Consumes: `core.config` (`BANDPASS`, `WINDOW_S`).
- Produces:
  - `ModeSpec(id, label, family, summary, status, unavailable="", params=(), rest=None,
    calibration=None, stream=None, channels=(), channels_fn=None, runtime_cls=None)`
    avec les méthodes `defaults() -> dict` et `channels_for(params) -> tuple[str, ...]`
  - `Param(key, label, kind, unit="", default=None, min=None, max=None, count=None, choices=(),
    constraints=(), proposes="", help="")`
  - `Rest(warmup_s, duration_s, instruction)` · `Calib(kind, reason="")`
  - `validate(spec, params) -> (dict, None) | (None, str)`

- [ ] **Step 1 : écrire le test qui échoue**

Créer `src/core/modes/contract.py` avec, **pour l'instant, seulement** le bloc de test en fin de
fichier (le reste vient à l'étape 3) :

```python
def _selftest():
    """Contrôle la validation : ce qui passe, ce qui est refusé, et avec quelle raison.

    Le refus DOIT porter sa raison en clair. Un paramètre invalide ne produit aucune erreur à
    l'exécution, seulement un décodage muet — le mode de panne le plus coûteux du projet.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    spec = ModeSpec(
        id="essai", label="Essai", family="actif", summary="mode de test", status="moteur",
        params=(
            Param("freqs", "Fréquences des cibles", "float_list", unit="Hz",
                  default=(15.0, 20.0, 8.57), min=BANDPASS[0], max=BANDPASS[1], count=(2, 8),
                  constraints=("dans_la_bande", "separables")),
            Param("gain", "Gain", "float", default=1.0, min=0.0, max=10.0),
            Param("actif", "Activé", "bool", default=True),
            Param("methode", "Méthode", "choice", default="cca", choices=("cca", "fbcca")),
        ))

    values, reason = validate(spec, {})
    chk(values == {"freqs": (15.0, 20.0, 8.57), "gain": 1.0, "actif": True, "methode": "cca"},
        f"sans rien fournir, on obtient les défauts ({values})")
    chk(reason is None, "aucune raison de refus sur les défauts")

    values, reason = validate(spec, {"gain": 3})
    chk(values is not None and values["gain"] == 3.0 and values["freqs"] == (15.0, 20.0, 8.57),
        "un réglage partiel garde les défauts des autres")

    for params, attendu in (
            ({"freqs": [15.0, 60.0]}, "hors bande passante"),
            ({"freqs": [15.0, 15.2]}, "trop proches"),
            ({"freqs": [15.0]}, "il en faut entre 2 et 8"),
            ({"freqs": [15.0] * 9}, "il en faut entre 2 et 8"),
            ({"freqs": "quinze"}, "liste de nombres attendue"),
            ({"gain": 99.0}, "dépasse le maximum"),
            ({"gain": -1.0}, "sous le minimum"),
            ({"gain": "beaucoup"}, "nombre attendu"),
            ({"methode": "magie"}, "n'est pas un choix valide"),
            ({"couleur": "rouge"}, "réglage inconnu")):
        values, reason = validate(spec, params)
        chk(values is None and reason and attendu in reason,
            f"{params} refusé : {reason}")

    # `separables` porte sur la résolution de la fenêtre, pas sur un goût : deux cibles
    # distantes de moins de 1/WINDOW_S ne sont PAS séparables, quelle que soit la qualité.
    ecart = 1.0 / WINDOW_S
    values, _ = validate(spec, {"freqs": [15.0, 15.0 + ecart + 0.01]})
    chk(values is not None, f"deux cibles à {ecart + 0.01:.2f} Hz d'écart passent")
    values, _ = validate(spec, {"freqs": [15.0, 15.0 + ecart - 0.01]})
    chk(values is None, f"deux cibles à {ecart - 0.01:.2f} Hz d'écart sont refusées")

    print(f"[contract] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
```

- [ ] **Step 2 : lancer, constater l'échec**

Run: `python src/core/modes/contract.py`
Expected: `NameError: name 'ModeSpec' is not defined`

- [ ] **Step 3 : écrire le contrat**

En tête de `src/core/modes/contract.py`, **avant** le bloc de test :

```python
"""Le contrat d'un mode : ce qu'il est, ce qui s'y règle, et comment un réglage est validé.

Un `ModeSpec` est déclaré **à côté de son décodeur** (`modes/ssvep.py` déclare le SSVEP), jamais
dans un fichier de configuration séparé : deux vérités finissent toujours par diverger.

Le même `Param` sert TROIS usages, et c'est tout l'intérêt de l'objet :
    1. la console en génère un champ de formulaire (`src/console/params_form.py`) ;
    2. le moteur s'en sert pour VALIDER ce qu'on lui soumet (`validate` ci-dessous) ;
    3. son `help` explique à l'étudiant ce qu'il doit comprendre avant d'y toucher.

⚠️ La validation est la pièce sérieuse. Un réglage SSVEP invalide — une fréquence hors bande
passante, deux cibles plus proches que la résolution de la fenêtre — ne lève AUCUNE erreur à
l'exécution : le décodage ne détecte simplement jamais rien, ce qui ressemble à « l'utilisateur
fixe mal ». C'est le mode de panne le plus coûteux du projet, et la raison pour laquelle un refus
part avec sa raison en clair.

Autotest :
    python src/core/modes/contract.py
"""

import os as _os
import sys as _sys
from dataclasses import dataclass

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import BANDPASS, WINDOW_S, use_utf8_console  # noqa: E402


@dataclass(frozen=True)
class Param:
    """Un réglage exposé à l'utilisateur : son type, ses bornes, son aide."""

    key: str                  # "freqs" — identifiant stable, la clé côté commande
    label: str                # "Fréquences des cibles" — ce que lit l'étudiant
    kind: str                 # "float" | "int" | "bool" | "choice" | "float_list"
    unit: str = ""            # "Hz"
    default: object = None
    min: float = None         # bornes par VALEUR (pour une liste : chaque élément)
    max: float = None
    count: tuple = None       # (mini, maxi) d'éléments, pour les listes
    choices: tuple = ()
    constraints: tuple = ()   # contraintes CROISÉES nommées, cf. _check_constraint
    proposes: str = ""        # ce paramètre en PROPOSE un autre (chantier 2 ; cf. spec §3.1)
    help: str = ""


@dataclass(frozen=True)
class Rest:
    """Le plancher de repos exigé par un mode avant de pouvoir décoder."""

    warmup_s: float      # stabilisation JETÉE : l'Unicorn sort un offset DC qui DÉRIVE pendant
    #                      des dizaines de secondes après l'ouverture de session (mesuré le
    #                      2026-07-27 : 10⁵ µV en rampe). Un plancher mesuré là-dedans hérite d'un
    #                      σ gonflé, et comme on décide sur z, le seuil devient INATTEIGNABLE.
    duration_s: float
    instruction: str     # consigne à AFFICHER pendant la mesure — sans elle, le plancher est
    #                      mesuré pendant que l'étudiant fixe une cible, et il est faux.


@dataclass(frozen=True)
class Calib:
    """Ce qu'il faudrait pour entraîner ce mode. Informatif dans ce chantier (spec §3)."""

    kind: str        # "console" (consignes rendues par la console) | "natif" (fenêtre pygame)
    reason: str = ""  # pourquoi "natif" — c'est une contrainte PHYSIQUE, pas une préférence


@dataclass(frozen=True)
class ModeSpec:
    """Tout ce que le produit sait d'un mode — y compris d'un mode qu'il ne sait pas faire.

    Le registre décrit **tous** les modes, publiés ou non. C'est lui qui porte l'honnêteté de
    l'interface : sans ça, la grille ne montrerait que ce qui est chargé, et les modes manquants
    seraient invisibles.
    """

    id: str                    # "ssvep" — clé stable, partout
    label: str                 # "SSVEP"
    family: str                # "actif" (l'utilisateur choisit) | "passif" (on observe)
    summary: str               # une phrase : ce que le mode produit
    status: str                # "moteur" | "appli_pygame" | "prevu"
    unavailable: str = ""      # POURQUOI il n'est pas dans le moteur ; "" si status == "moteur"
    params: tuple = ()
    rest: Rest = None
    calibration: Calib = None
    stream: str = None         # suffixe du flux publié, ex. "decoded_ssvep"
    channels: tuple = ()       # voies de ce flux, quand elles sont FIXES
    channels_fn: object = None  # (params) -> voies, quand elles dépendent d'un réglage (SSVEP)
    runtime_cls: object = None  # la classe ModeRuntime, ou None si le moteur ne sait pas le faire

    def defaults(self):
        """Le jeu de réglages par défaut de ce mode."""
        return {p.key: p.default for p in self.params}

    def channels_for(self, params):
        """Les voies réellement publiées pour ces réglages.

        Le SSVEP nomme ses voies d'après ses fréquences (`score_15Hz`) : une liste figée dans le
        contrat mentirait dès le premier changement de réglage.
        """
        return tuple(self.channels_fn(params)) if self.channels_fn else tuple(self.channels)


def validate(spec, params):
    """(réglages complets, None) si tout passe, sinon (None, raison en clair).

    Les clés absentes prennent leur défaut : un appelant peut ne soumettre que ce qu'il change.
    """
    known = {p.key: p for p in spec.params}
    inconnus = sorted(k for k in params if k not in known)
    if inconnus:
        return None, (f"réglage inconnu pour « {spec.label} » : {', '.join(inconnus)} "
                      f"(attendu : {', '.join(sorted(known)) or 'aucun réglage'})")

    values = spec.defaults()
    for key, param in known.items():
        if key not in params:
            continue
        value, reason = _coerce(param, params[key])
        if reason:
            return None, reason
        values[key] = value

    for param in spec.params:
        reason = _check_constraints(param, values)
        if reason:
            return None, reason
    return values, None


def _unit(param):
    return f" {param.unit}" if param.unit else ""


def _check_bounds(param, value):
    if param.min is not None and value < param.min:
        return (f"« {param.label} » : {value:g}{_unit(param)} est sous le minimum "
                f"{param.min:g}{_unit(param)}")
    if param.max is not None and value > param.max:
        return (f"« {param.label} » : {value:g}{_unit(param)} dépasse le maximum "
                f"{param.max:g}{_unit(param)}")
    return None


def _coerce(param, value):
    """(valeur convertie, None) ou (None, raison). Convertit AVANT de vérifier les bornes."""
    if param.kind == "bool":
        return bool(value), None

    if param.kind == "choice":
        if value not in param.choices:
            return None, (f"« {param.label} » : {value!r} n'est pas un choix valide "
                          f"({', '.join(str(c) for c in param.choices)})")
        return value, None

    if param.kind == "float_list":
        if isinstance(value, (str, bytes)):
            return None, f"« {param.label} » : liste de nombres attendue, reçu {value!r}"
        try:
            values = tuple(float(v) for v in value)
        except (TypeError, ValueError):
            return None, f"« {param.label} » : liste de nombres attendue, reçu {value!r}"
        if param.count:
            lo, hi = param.count
            if not lo <= len(values) <= hi:
                return None, (f"« {param.label} » : il en faut entre {lo} et {hi}, "
                              f"il y en a {len(values)}")
        for v in values:
            reason = _check_bounds(param, v)
            if reason:
                return None, reason
        return values, None

    try:
        converted = int(value) if param.kind == "int" else float(value)
    except (TypeError, ValueError):
        return None, f"« {param.label} » : nombre attendu, reçu {value!r}"
    reason = _check_bounds(param, converted)
    return (None, reason) if reason else (converted, None)


def _check_constraints(param, values):
    """Contraintes CROISÉES, nommées dans le contrat et implémentées ICI — jamais dans l'interface.

    Elles reçoivent tous les réglages du mode, pas seulement le leur : c'est ce qui permettra au
    chantier 2 de vérifier qu'un nombre de cibles s'accorde à une liste de fréquences.
    """
    for name in param.constraints:
        if name == "dans_la_bande":
            lo, hi = BANDPASS
            hors = [v for v in _as_list(values.get(param.key)) if not lo <= v <= hi]
            if hors:
                return (f"« {param.label} » : hors bande passante {lo:g}-{hi:g} Hz : "
                        + ", ".join(f"{v:g}" for v in hors)
                        + " — le filtre d'acquisition les supprime AVANT le décodage")

        elif name == "separables":
            # Résolution fréquentielle d'une fenêtre de WINDOW_S : deux cibles plus proches que
            # 1/WINDOW_S ne sont pas séparables, quelle que soit la qualité du signal.
            ecart_min = 1.0 / WINDOW_S
            ordonne = sorted(_as_list(values.get(param.key)))
            proches = [(a, b) for a, b in zip(ordonne, ordonne[1:]) if b - a < ecart_min]
            if proches:
                return (f"« {param.label} » : cibles trop proches pour une fenêtre de "
                        f"{WINDOW_S:g} s (écart minimum {ecart_min:.2f} Hz) : "
                        + ", ".join(f"{a:g} et {b:g}" for a, b in proches))

        else:
            return f"contrainte inconnue « {name} » sur « {param.label} » (défaut du contrat)"
    return None


def _as_list(value):
    return list(value) if isinstance(value, (list, tuple)) else [value]
```

Et `src/core/modes/__init__.py` :

```python
"""`core.modes` — le catalogue des modes et leur runtime.

Un **mode** est deux choses posées côte à côte :
  - un `ModeSpec` (contract.py) : ce qu'il est, ce qui s'y règle, ce qu'il publie ;
  - un `ModeRuntime` (runtime.py) : son état vivant — phase, décodeur, publieur.

**L'algorithme et le mode sont séparés.** `core/cca_decoder.py` reste l'algorithme : une CCA,
testable sur du synthétique, indifférente au produit. `modes/ssvep.py` est le contrat : comment ça
s'appelle, ce qui se règle, ce qui se publie. Les mélanger était le défaut de l'ancien `server.py`,
où « un mode » n'était qu'une suite de `if mode == "ssvep" … elif mode == "neuro"`.

Le registre décrit **tous** les modes, y compris ceux que le moteur ne sait pas faire : c'est ce
qui permet à la console de dire « c-VEP : demande un stimulus verrouillé à la frame » au lieu de
faire comme s'il n'existait pas.
"""
```

- [ ] **Step 4 : lancer, vérifier que ça passe**

Run: `python src/core/modes/contract.py`
Expected: toutes les lignes en `OK`, puis `[contract] VERDICT : OK`

- [ ] **Step 5 : vérifier que rien d'existant n'a bougé**

Run: `python src/core/server.py --smoke` puis `python src/research/app.py --smoke`
Expected: les deux `VERDICT : OK`

- [ ] **Step 6 : commit**

```bash
git add src/core/modes/__init__.py src/core/modes/contract.py
git commit -m "Make a mode an object, so its settings can be declared and refused with a reason"
```

---

## Tâche 2 : le registre — tous les modes, y compris ceux qu'on ne sait pas faire

Sept `ModeSpec`, dont quatre sans runtime. C'est **le** point d'honnêteté de l'interface : le
premier défaut que l'utilisateur a pointé sur l'ancien tableau de bord était qu'il ne montrait que
ce qui tournait.

Les runtimes n'existent pas encore : les trois modes du moteur portent `runtime_cls=None` **pour
cette tâche seulement**, et le test d'intégrité en tient compte. Les tâches 4 à 6 les branchent.

**Files:**
- Create: `src/core/modes/raw.py`, `src/core/modes/ssvep.py`, `src/core/modes/neuro.py`,
  `src/core/modes/external.py`, `src/core/modes/registry.py`
- Modify: `src/core/lsl_io.py` (extraire `ssvep_channel_labels`)

**Interfaces:**
- Consumes: `contract.ModeSpec/Param/Rest/Calib` (tâche 1) ; `core.config` ; `core.lsl_io.stream_name`.
- Produces:
  - `lsl_io.ssvep_channel_labels(freqs) -> list[str]`
  - `registry.MODES: tuple[ModeSpec, ...]` (ordre d'affichage ET ordre de résolution des égalités)
  - `registry.get(mode_id) -> ModeSpec | None` · `registry.runnable() -> tuple[ModeSpec, ...]`
  - `registry.serialize(spec) -> dict` (JSON-able, sans callable) · `registry.catalog() -> list[dict]`
  - `registry.check() -> (bool, list[str])` — le test d'intégrité, appelé aussi par `server.py --smoke`

- [ ] **Step 1 : écrire le test d'intégrité qui échoue**

Créer `src/core/modes/registry.py` avec **seulement** ceci pour l'instant :

```python
def check():
    """(tout va bien, liste des défauts). Un défaut ici ne lève AUCUNE erreur au démarrage.

    C'est pour ça que ce test existe : un `default` hors de ses propres bornes ne casse rien
    visiblement — le mode refuse simplement d'appliquer ses réglages, et on le découvre en
    séance, casque sur la tête. Deux modes qui publieraient le même suffixe de flux seraient
    pires encore : LSL les accepterait tous les deux, et un client recevrait un mélange.
    """
    defauts = []
    vus_id, vus_stream = set(), {}

    for spec in MODES:
        if spec.id in vus_id:
            defauts.append(f"identifiant en double : {spec.id}")
        vus_id.add(spec.id)

        if spec.status not in ("moteur", "appli_pygame", "prevu"):
            defauts.append(f"{spec.id} : status « {spec.status} » inconnu")
        if spec.family not in ("actif", "passif", "brut"):
            defauts.append(f"{spec.id} : family « {spec.family} » inconnue")
        if spec.status != "moteur" and not spec.unavailable:
            defauts.append(f"{spec.id} : status « {spec.status} » sans explication (unavailable vide)")
        if spec.status == "moteur" and spec.unavailable:
            defauts.append(f"{spec.id} : status « moteur » mais unavailable renseigné")

        if spec.stream:
            if spec.stream in vus_stream:
                defauts.append(f"suffixe de flux en double : {spec.stream} "
                               f"({vus_stream[spec.stream]} et {spec.id})")
            vus_stream[spec.stream] = spec.id
        if spec.status == "moteur" and not spec.stream:
            defauts.append(f"{spec.id} : mode du moteur sans flux à publier")

        # Chaque défaut doit respecter les bornes de son PROPRE paramètre. Sinon le mode
        # démarre et refuse ses propres réglages à la première soumission.
        values, reason = validate(spec, {})
        if values is None:
            defauts.append(f"{spec.id} : ses valeurs par défaut sont refusées — {reason}")

        cles = {p.key for p in spec.params}
        for p in spec.params:
            if p.proposes and p.proposes not in cles:
                defauts.append(f"{spec.id}.{p.key} : propose « {p.proposes} », "
                               f"qui n'est pas un paramètre de ce mode")
            if p.kind not in ("float", "int", "bool", "choice", "float_list"):
                defauts.append(f"{spec.id}.{p.key} : kind « {p.kind} » inconnu")
            if p.kind == "choice" and not p.choices:
                defauts.append(f"{spec.id}.{p.key} : un choix sans choices")
            if not p.help:
                defauts.append(f"{spec.id}.{p.key} : pas de texte d'aide "
                               f"(un étudiant doit savoir ce qu'il règle)")

        # Les voies annoncées doivent correspondre à ce qui sera réellement publié.
        if spec.stream and not spec.channels_for(spec.defaults()):
            defauts.append(f"{spec.id} : publie {spec.stream} sans annoncer ses voies")

    return (not defauts), defauts


def _selftest():
    ok, defauts = check()
    for spec in MODES:
        marque = {"moteur": "●", "appli_pygame": "○", "prevu": "·"}[spec.status]
        detail = f" — {spec.unavailable}" if spec.unavailable else ""
        print(f"  {marque} {spec.id:<7} {spec.label:<14} {spec.family:<7} {spec.status}{detail}")
    for d in defauts:
        print(f"  ÉCHEC {d}")
    print(f"[registry] {len(MODES)} modes, dont {len(runnable())} dans le moteur")
    print(f"[registry] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
```

- [ ] **Step 2 : lancer, constater l'échec**

Run: `python src/core/modes/registry.py`
Expected: `NameError: name 'MODES' is not defined`

- [ ] **Step 3 : extraire les voies SSVEP dans `lsl_io.py`**

Les noms de voies du flux SSVEP sont décidés à deux endroits dès qu'on les déclare aussi dans le
contrat. On les extrait donc en **une** fonction, dont le publieur et le contrat se servent tous
les deux.

Dans `src/core/lsl_io.py`, juste avant `class DecodedSSVEPPublisher` :

```python
def ssvep_channel_labels(freqs):
    """Voies du flux `decoded_ssvep` pour ce jeu de fréquences.

    Une seule fonction pour le publieur ET pour le `ModeSpec` : les voies sont du contrat public
    (un client les lit dans les métadonnées), et deux façons de les construire finiraient par
    diverger d'un espace ou d'une décimale.
    """
    return (["target_index", "freq_hz", "confidence"]
            + [f"score_{float(f):g}Hz" for f in freqs])
```

Puis dans `DecodedSSVEPPublisher.__init__`, remplacer les deux lignes

```python
        labels = ["target_index", "freq_hz", "confidence"]
        labels += [f"score_{f:g}Hz" for f in self.freqs]
```

par

```python
        labels = ssvep_channel_labels(self.freqs)
```

- [ ] **Step 4 : écrire les quatre fichiers de modes**

`src/core/modes/raw.py` :

```python
"""Mode « brut » : diffuser les 8 voies telles que le casque les rend.

C'est un mode comme un autre, et c'est le changement : on peut donc **arrêter** de diffuser le
brut, ce qui n'était pas possible avant. Les flux `quality` et `status` décrivent la santé du
MOTEUR, pas un mode : eux restent publiés en permanence, hors registre.
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import CH_NAMES  # noqa: E402
from core.modes.contract import ModeSpec  # noqa: E402

SPEC = ModeSpec(
    id="raw",
    label="Brut",
    family="brut",
    summary="Les 8 voies EEG telles que le casque les rend, en µV à 250 Hz.",
    status="moteur",
    params=(),          # rien à régler : « brut » veut dire brut
    rest=None,          # aucun plancher à mesurer : on ne décide de rien
    calibration=None,
    stream="raw",
    channels=tuple(CH_NAMES),
)
```

`src/core/modes/ssvep.py` — pour cette tâche, **le SPEC seul** :

```python
"""Mode SSVEP : quelle cible clignotante l'utilisateur regarde. BCI **active**.

Le décodage lui-même est dans `core/cca_decoder.py` — une CCA, sans entraînement. Ici on décrit
le MODE : ce qui se règle, ce qui se publie, ce qu'il faut mesurer avant de décider.

⚠️ Le moteur ne rend AUCUN stimulus. C'est l'application cliente qui fait clignoter les cibles ;
elle déclare simplement leurs fréquences ici. Le couplage est lâche — aucune synchronisation à la
frame n'est nécessaire, contrairement au c-VEP.
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (BANDPASS, SSVEP_BASELINE_S, SSVEP_WARMUP_S,  # noqa: E402
                         choose_frequencies)
from core.lsl_io import ssvep_channel_labels  # noqa: E402
from core.modes.contract import ModeSpec, Param, Rest  # noqa: E402

# Le défaut vient de `choose_frequencies`, la MÊME fonction que le stimulus : passer le même
# refresh des deux côtés garantit l'accord sans recopier des décimales à la main.
FREQS_60HZ = tuple(c["actual_hz"] for c in choose_frequencies(60))   # 15 · 20 · 8,571 Hz


def _channels(params):
    return ssvep_channel_labels(params["freqs"])


SPEC = ModeSpec(
    id="ssvep",
    label="SSVEP",
    family="actif",
    summary="Quelle cible clignotante l'utilisateur regarde, ~5 fois par seconde.",
    status="moteur",
    params=(
        Param(
            key="freqs",
            label="Fréquences des cibles",
            kind="float_list",
            unit="Hz",
            default=FREQS_60HZ,
            min=BANDPASS[0], max=BANDPASS[1],
            count=(2, 8),
            constraints=("dans_la_bande", "separables"),
            help="Les fréquences que TON application fait clignoter. Le nombre de cibles est la "
                 "longueur de cette liste. Une fréquence n'est stable que si c'est un diviseur "
                 "entier du refresh de ton écran (à 60 Hz : 30, 20, 15, 12, 10, 8,57…). Évite le "
                 "voisinage de ton pic alpha (~10 Hz) : le fond de corrélation y est élevé au "
                 "repos. Changer cette liste RECRÉE le flux — les clients doivent se réabonner.",
        ),
        # `proposes` est déclaré nulle part dans ce chantier : le nombre de cibles se règle par la
        # LONGUEUR de la liste ci-dessus. La proposition automatique de fréquences est le
        # chantier 2 (spec §3.1) ; le contrat la permet déjà, on ne la livre pas à moitié.
    ),
    rest=Rest(
        warmup_s=SSVEP_WARMUP_S,
        duration_s=SSVEP_BASELINE_S,
        instruction="Ne fixe AUCUNE cible : on mesure le bruit de fond de chaque fréquence.",
    ),
    calibration=None,   # la CCA n'apprend rien ; le repos est un étalonnage, pas un modèle
    stream="decoded_ssvep",
    channels_fn=_channels,
)
```

`src/core/modes/neuro.py` — le SPEC seul :

```python
"""Mode neuro-monitoring : charge / somnolence / engagement. BCI **passive**.

Passif = l'utilisateur ne commande rien, on observe un état. Il n'y a donc ni cible, ni bonne
réponse, et un client ne doit PAS traiter ces valeurs comme une sélection.

⚠️ L'échelle est un z contre le repos du jour de CET utilisateur. `+1` veut dire « au-dessus de
mon propre repos », pas « chargé ». Les trois indices dérivent du même calcul spectral et restent
corrélés. À lire en TENDANCE.
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (NEURO_BASELINE_S, NEURO_REBASELINE_S, NEURO_SMOOTH,  # noqa: E402
                         NEURO_WARMUP_S)
from core.lsl_io import DecodedNeuroPublisher  # noqa: E402
from core.modes.contract import ModeSpec, Param, Rest  # noqa: E402

SPEC = ModeSpec(
    id="neuro",
    label="Neuro",
    family="passif",
    summary="Charge mentale, somnolence et engagement, en écart au repos du jour.",
    status="moteur",
    params=(
        Param(
            key="smoothing", label="Lissage", kind="float",
            default=NEURO_SMOOTH, min=0.0, max=0.99,
            help="Moyenne glissante (EMA) sur les z. 0 = brut et très nerveux, 0,95 = très lisse "
                 "et lent à réagir. Ces indices sont bruités : le défaut lisse beaucoup.",
        ),
        Param(
            key="rebaseline_s", label="Re-calage du repos", kind="float", unit="s",
            default=NEURO_REBASELINE_S, min=0.0, max=1800.0,
            help="Constante de temps du re-calage LENT du zéro, contre la dérive des électrodes "
                 "sèches sur plusieurs minutes. 0 = zéro figé. Trop court, ça effacerait les "
                 "états mentaux eux-mêmes, qui sont plus rapides que la dérive.",
        ),
    ),
    rest=Rest(
        warmup_s=NEURO_WARMUP_S,
        duration_s=NEURO_BASELINE_S,
        # Plus long que le SSVEP : les échelles sont calées sur une MÉDIANE et une MAD, qui
        # demandent plus de fenêtres qu'une moyenne.
        instruction="Repos : regarde l'écran, immobile et détendu — on cale TON zéro du jour.",
    ),
    calibration=None,
    stream="decoded_neuro",
    channels=tuple(DecodedNeuroPublisher.KEYS) + ("artifact",),
)
```

`src/core/modes/external.py` :

```python
"""Les modes que le MOTEUR ne sait pas faire — décrits quand même.

C'est le point d'honnêteté de l'interface. Sans ces quatre entrées, la grille ne montrerait que
ce qui est chargé : un étudiant croirait que le produit ne fait que trois choses, et ne saurait
pas qu'un décodeur c-VEP validé existe dans `src/research/app.py`.

Chacun porte la RAISON de son absence, et c'est presque toujours la même famille de raison : le
moteur ne reçoit pas de marqueurs entrants, et ne rend pas de stimulus verrouillé à la frame.
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.modes.contract import Calib, ModeSpec  # noqa: E402

_PYGAME = "Lance `python src/research/app.py` — jamais en même temps que le moteur, le casque " \
          "n'accepte qu'une connexion."

MI = ModeSpec(
    id="mi", label="Motor Imagery", family="actif",
    summary="Imagination d'un mouvement main gauche / main droite (CSP+LDA).",
    status="appli_pygame",
    unavailable="Le moteur ne sait pas encore charger un modèle MI entraîné. " + _PYGAME,
    # Premier candidat à la migration vers le moteur : fenêtre glissante, aucun marqueur requis,
    # modèle à 79 % déjà entraîné. C'est le chantier 3 (entraînements et gestion des modèles).
    calibration=Calib(kind="console",
                      reason="consignes à l'échelle de la seconde — la console suffit à les rendre"),
)

CVEP = ModeSpec(
    id="cvep", label="c-VEP", family="actif",
    summary="Cible fixée parmi N, par codes pseudo-aléatoires décalés (le plus rapide).",
    status="appli_pygame",
    unavailable="Demande un stimulus verrouillé à la FRAME : une seule frame sautée décale le "
                "code et détruit la corrélation. " + _PYGAME,
    calibration=Calib(kind="natif",
                      reason="chaque frame doit afficher le bon bit du code"),
)

P300 = ModeSpec(
    id="p300", label="P300", family="actif",
    summary="Sélection parmi 6 cibles par onde P300 (oddball attentionnel).",
    status="appli_pygame",
    unavailable="Demande des MARQUEURS entrants (l'onset de chaque flash), que le moteur ne "
                "reçoit pas encore. " + _PYGAME,
    calibration=Calib(kind="natif",
                      reason="époques calées sur l'onset exact de chaque flash"),
)

ERRP = ModeSpec(
    id="errp", label="ErrP", family="passif",
    summary="Détecte que la machine vient de se tromper (potentiel d'erreur).",
    status="appli_pygame",
    unavailable="Demande un MARQUEUR entrant : l'instant exact où le feedback s'affiche. " + _PYGAME,
    calibration=Calib(kind="natif",
                      reason="l'onset du feedback écran doit être horodaté à la frame"),
)
```

- [ ] **Step 5 : écrire le registre lui-même**

En tête de `src/core/modes/registry.py`, **avant** `check()` :

```python
"""Le catalogue de TOUS les modes — ceux que le moteur fait tourner, et les autres.

L'ordre de `MODES` est celui de l'affichage dans la grille, et il sert aussi d'arbitre : quand
deux modes lancés ensemble demandent un repos de même durée, c'est le premier d'ici qui donne la
consigne affichée. Une règle déterministe vaut mieux qu'un « ça dépend » (spec §4.2).

Autotest :
    python src/core/modes/registry.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import use_utf8_console  # noqa: E402
from core.modes import external, neuro, raw, ssvep  # noqa: E402
from core.modes.contract import validate  # noqa: E402

MODES = (
    raw.SPEC,           # le brut d'abord : c'est ce qui existe même sans décodage
    ssvep.SPEC,
    neuro.SPEC,
    external.MI,        # puis les modes de l'appli pygame, dans l'ordre où ils ont été écrits
    external.CVEP,
    external.P300,
    external.ERRP,
)

BY_ID = {spec.id: spec for spec in MODES}


def get(mode_id):
    """Le `ModeSpec` de cet identifiant, ou None."""
    return BY_ID.get(mode_id)


def runnable():
    """Les modes que le moteur sait faire tourner, dans l'ordre du registre."""
    return tuple(spec for spec in MODES if spec.runtime_cls is not None)


def serialize(spec, params=None):
    """Le `ModeSpec` en dictionnaire JSON-able — ce que la console reçoit.

    On sérialise plutôt que de passer l'objet : la console lit un ÉTAT, pas des références vers
    l'intérieur du moteur, et ce même dictionnaire pourra partir sur le flux `status` le jour où
    un client voudra découvrir les modes tout seul.
    """
    params = spec.defaults() if params is None else params
    return {
        "id": spec.id,
        "label": spec.label,
        "family": spec.family,
        "summary": spec.summary,
        "status": spec.status,
        "unavailable": spec.unavailable,
        "stream": spec.stream,
        "channels": list(spec.channels_for(params)),
        "params": [
            {"key": p.key, "label": p.label, "kind": p.kind, "unit": p.unit,
             "default": list(p.default) if isinstance(p.default, tuple) else p.default,
             "min": p.min, "max": p.max,
             "count": list(p.count) if p.count else None,
             "choices": list(p.choices), "help": p.help}
            for p in spec.params
        ],
        "rest": None if spec.rest is None else {
            "warmup_s": spec.rest.warmup_s,
            "duration_s": spec.rest.duration_s,
            "instruction": spec.rest.instruction,
        },
        "calibration": None if spec.calibration is None else {
            "kind": spec.calibration.kind, "reason": spec.calibration.reason,
        },
    }


def catalog():
    """Tout le registre, sérialisé. C'est ce qui remplit la grille de la console."""
    return [serialize(spec) for spec in MODES]
```

- [ ] **Step 6 : lancer le test d'intégrité**

Run: `python src/core/modes/registry.py`
Expected : les 7 modes listés, puis `[registry] 7 modes, dont 0 dans le moteur` et
`[registry] VERDICT : OK`.

Le `0 dans le moteur` est normal ici : les runtimes arrivent aux tâches 4 à 6. Deux défauts
attendus **doivent** être absents — un `default` hors bornes et un `help` manquant sont
précisément ce que ce test attrape.

- [ ] **Step 7 : vérifier le contrat public inchangé**

Run: `python src/core/lsl_io.py`
Expected: `[lsl] VERDICT : OK` — l'extraction de `ssvep_channel_labels` ne doit rien changer aux
voies annoncées.

Run: `python src/core/server.py --smoke` puis `python src/research/app.py --smoke`
Expected: les deux `VERDICT : OK`

- [ ] **Step 8 : commit**

```bash
git add src/core/modes/ src/core/lsl_io.py
git commit -m "Describe every mode, including the four the engine cannot run"
```

---

## Tâche 3 : `ModeRuntime`, la machine de phases commune

Aujourd'hui la séquence chauffe → repos → décodage est écrite **une fois pour tout le moteur**
(`_warmup_until`, `_baseline_done`, `_baseline_warned`…), avec des `if self.neuro is not None`
dedans. Deux modes qui tournent ensemble en sont à des phases différentes : l'état doit donc
descendre **dans** le mode.

Le point de conception qui rend tout ça testable : **le runtime ne lit jamais l'horloge lui-même**,
il reçoit `now`. On peut donc vérifier une transition de phase sans dormir une seule seconde.

**Files:**
- Create: `src/core/modes/runtime.py`

**Interfaces:**
- Consumes: `contract.ModeSpec` (tâche 1).
- Produces: `ModeRuntime(spec, params, engine)` avec
  - attributs : `spec` · `params: dict` · `phase: str` ∈ `{"warmup","rest","running"}` ·
    `published: bool` · `rest_report: dict | None`
  - `open()` · `close()` · `set_published(on)` · `begin_rest(now, warmup_s=None, duration_s=None)` ·
    `period_s() -> float` · `tick(engine, lsl_ts, now)` · `state() -> dict` · `output() -> dict | None`
  - hooks des sous-classes : `_open()` · `_close()` · `_reset_rest()` · `_rest_step(engine, now) -> bool` ·
    `_run_step(engine, lsl_ts)`

- [ ] **Step 1 : écrire le test qui échoue**

En fin de `src/core/modes/runtime.py` :

```python
def _selftest():
    """La machine de phases, sur une horloge FABRIQUÉE. Aucun casque, aucune attente réelle."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _Compteur(ModeRuntime):
        """Runtime d'essai : son repos se termine au bout de 3 pas, puis il compte ses décisions."""

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.vus, self.decisions, self.remises_a_zero = 0, 0, 0

        def _reset_rest(self):
            self.remises_a_zero += 1
            self.vus = 0

        def _rest_step(self, engine, now):
            self.vus += 1
            if self.vus < 3:
                return False
            self.rest_report = {"windows": self.vus}
            return True

        def _run_step(self, engine, lsl_ts):
            self.decisions += 1

    avec_repos = ModeSpec(id="a", label="Avec repos", family="actif", summary="", status="moteur",
                          rest=Rest(warmup_s=10.0, duration_s=20.0, instruction="ne bouge pas"),
                          stream="decoded_a", channels=("x",))
    sans_repos = ModeSpec(id="b", label="Sans repos", family="brut", summary="", status="moteur",
                          stream="raw", channels=("x",))

    # 1. Un mode SANS repos décode tout de suite : rien à mesurer avant de diffuser.
    rt = _Compteur(sans_repos, {}, engine=None)
    rt.begin_rest(now=100.0)
    chk(rt.phase == "running", f"sans repos, on démarre en « running » (phase={rt.phase})")
    rt.tick(engine=None, lsl_ts=0.0, now=100.0)
    chk(rt.decisions == 1, "et il décode dès le premier tick")

    # 2. Un mode AVEC repos passe par chauffe -> repos -> décodage, dans cet ordre.
    rt = _Compteur(avec_repos, {}, engine=None)
    rt.begin_rest(now=100.0)
    chk(rt.phase == "warmup", "avec repos, on commence par la chauffe")
    chk(rt.remises_a_zero == 1, "le début de repos remet l'état du mode à zéro")

    rt.tick(None, 0.0, now=105.0)     # encore dans la chauffe (10 s)
    chk(rt.phase == "warmup" and rt.vus == 0,
        "pendant la chauffe on ne collecte RIEN (la dérive DC fausserait le plancher)")

    rt.tick(None, 0.0, now=111.0)     # chauffe finie -> repos, 1re fenêtre
    chk(rt.phase == "rest" and rt.vus == 1, f"la chauffe finie, le repos commence (vus={rt.vus})")

    rt.tick(None, 0.0, now=112.0)
    rt.tick(None, 0.0, now=113.0)     # 3e fenêtre -> le plancher tient
    chk(rt.phase == "running", f"le plancher mesuré, on décode (phase={rt.phase})")
    chk(rt.rest_report == {"windows": 3}, f"le repos laisse un compte-rendu ({rt.rest_report})")
    chk(rt.decisions == 0, "aucune décision n'a été publiée avant la fin du repos")

    rt.tick(None, 0.0, now=114.0)
    chk(rt.decisions == 1, "puis les décisions partent")

    # 3. Refaire le repos repart de zéro — indispensable après avoir touché une électrode.
    rt.begin_rest(now=200.0)
    chk(rt.phase == "warmup" and rt.remises_a_zero == 2 and rt.rest_report is None,
        "« refaire le repos » remet chauffe, état et compte-rendu à zéro")

    # 4. Les durées peuvent être RACCOURCIES (c'est ce dont les smokes ont besoin).
    rt = _Compteur(avec_repos, {}, engine=None)
    rt.begin_rest(now=0.0, warmup_s=1.0, duration_s=2.0)
    rt.tick(None, 0.0, now=1.5)
    chk(rt.phase == "rest", "une chauffe raccourcie est bien plus courte")

    print(f"[runtime] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
```

- [ ] **Step 2 : lancer, constater l'échec**

Run: `python src/core/modes/runtime.py`
Expected: `NameError: name 'ModeRuntime' is not defined`

- [ ] **Step 3 : écrire la machine de phases**

En tête de `src/core/modes/runtime.py` :

```python
"""`ModeRuntime` — l'état vivant d'un mode qui tourne : sa phase, son décodeur, son publieur.

Ce qui est ICI est ce que **tous** les modes partagent : la séquence chauffe → repos → décodage,
la publication activable, et le compte-rendu de repos. Ce qui est dans les sous-classes est ce qui
diffère vraiment : ce qu'on collecte pendant le repos, et ce qu'on publie ensuite.

Avant, cette séquence était écrite une fois pour TOUT le moteur. Ça marchait tant qu'un seul mode
tournait ; dès que deux tournent ensemble, ils sont à des phases différentes — l'un mesure encore
son plancher pendant que l'autre décode déjà. L'état devait donc descendre dans le mode.

⚠️ **Un runtime ne lit jamais l'horloge lui-même** : `tick` reçoit `now`. C'est ce qui rend la
machine de phases testable sans dormir, et ce qui garantit que tous les modes d'un même tour de
boucle raisonnent sur le MÊME instant.

Autotest :
    python src/core/modes/runtime.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import use_utf8_console  # noqa: E402
from core.modes.contract import ModeSpec, Rest  # noqa: E402


class ModeRuntime:
    """Un mode en train de tourner. Une instance par mode actif ; le moteur en tient un dict."""

    def __init__(self, spec, params, engine):
        self.spec = spec
        self.params = dict(params)
        self.engine = engine
        self.published = True
        self.phase = "running" if spec.rest is None else "warmup"
        self.rest_report = None
        self._warmup_s = 0.0 if spec.rest is None else spec.rest.warmup_s
        self._rest_s = 0.0 if spec.rest is None else spec.rest.duration_s
        self._warmup_until = None
        self._rest_until = None
        self._opened = False

    # --- cycle de vie --------------------------------------------------------

    def open(self):
        """Crée le flux de ce mode. Idempotent : ré-ouvrir un mode ouvert ne fait rien."""
        if not self._opened:
            self._open()
            self._opened = True

    def close(self):
        """Libère le flux. Le mode continue d'exister et de décoder pour l'affichage."""
        if self._opened:
            self._close()
            self._opened = False

    def set_published(self, on):
        """Publier sur le réseau, ou décoder pour soi seul.

        Couper la publication LIBÈRE vraiment le flux : il disparaît du réseau. On préfère ça à
        un flux vivant qui n'émettrait plus rien — un client verrait un flux sain et attendrait
        indéfiniment, ce qui est exactement le genre de silence que ce projet combat. Le
        rallumer recrée le flux, donc les clients doivent se réabonner (le NOM ne change pas).
        """
        self.published = bool(on)
        self.open() if self.published else self.close()

    def begin_rest(self, now, warmup_s=None, duration_s=None):
        """(Re)part pour une chauffe puis un repos. `None` = les durées du contrat.

        Indispensable après avoir touché une électrode, et après tout changement de réglage : un
        plancher mesuré sous d'autres réglages, ou pendant qu'un contact se stabilisait, reste
        faux pour toute la séance.
        """
        self.rest_report = None
        self._reset_rest()
        if self.spec.rest is None:
            self.phase = "running"
            return
        self._warmup_s = self.spec.rest.warmup_s if warmup_s is None else float(warmup_s)
        self._rest_s = self.spec.rest.duration_s if duration_s is None else float(duration_s)
        self._warmup_until = now + self._warmup_s
        self._rest_until = None
        self.phase = "warmup"

    # --- la boucle -----------------------------------------------------------

    def period_s(self):
        """Délai minimum entre deux `tick`. 0 = à chaque tour de boucle du moteur."""
        return 0.2

    def tick(self, engine, lsl_ts, now):
        """Un pas de ce mode. Appelé par la boucle du moteur, jamais par une interface."""
        if self.phase == "warmup":
            # Chauffe : on JETTE ces secondes au lieu de les verser dans le plancher.
            if self._warmup_until is not None and now < self._warmup_until:
                return
            self.phase = "rest"

        if self.phase == "rest":
            if self._rest_until is None:
                # Le décompte part de la PREMIÈRE fenêtre exploitable, pas du démarrage : le
                # tampon met WINDOW_S + la marge de filtre à en produire une. Compter depuis le
                # lancement rognerait le repos d'autant (mesuré : 3 fenêtres au lieu de 15, donc
                # plancher rejeté faute d'effectif).
                self._rest_until = now + self._rest_s
            if self._rest_step(engine, now):
                self.phase = "running"
            return

        self._run_step(engine, lsl_ts)

    # --- état, pour l'afficheur ---------------------------------------------

    def instruction(self):
        """Ce que l'utilisateur doit faire MAINTENANT, dans ce mode."""
        if self.phase in ("warmup", "rest") and self.spec.rest is not None:
            return self.spec.rest.instruction
        return ""

    def output(self):
        """La dernière sortie du mode, pour l'affichage. None si rien encore."""
        return None

    def state(self):
        """L'état de ce mode, en dictionnaire JSON-able. Sûr depuis un autre fil."""
        return {
            "id": self.spec.id,
            "label": self.spec.label,
            "family": self.spec.family,
            "phase": self.phase,
            "published": self.published,
            "params": {k: (list(v) if isinstance(v, tuple) else v)
                       for k, v in self.params.items()},
            "instruction": self.instruction(),
            "stream": self.spec.stream,
            "channels": list(self.spec.channels_for(self.params)),
            "rest_report": self.rest_report,
            "output": self.output(),
        }

    # --- à redéfinir dans les sous-classes -----------------------------------

    def _open(self):
        """Créer le(s) publieur(s) de ce mode."""

    def _close(self):
        """Libérer le(s) publieur(s). Laisser tomber la référence suffit : pylsl ferme l'outlet."""

    def _reset_rest(self):
        """Jeter tout ce qui a été mesuré : échantillons du plancher, décodeur, dernière sortie."""

    def _rest_step(self, engine, now):
        """Un pas de mesure du repos. True quand le plancher tient, False pour prolonger."""
        return True

    def _run_step(self, engine, lsl_ts):
        """Un pas de décodage : mesurer, décider, publier."""
```

- [ ] **Step 4 : lancer, vérifier que ça passe**

Run: `python src/core/modes/runtime.py`
Expected: toutes les lignes en `OK`, puis `[runtime] VERDICT : OK`

- [ ] **Step 5 : commit**

```bash
git add src/core/modes/runtime.py
git commit -m "Give each mode its own phase machine, so two can run out of step"
```

---

## Tâche 4 : le brut devient un mode

Le plus simple des trois runtimes, et celui qui valide la forme : si diffuser le brut passe par le
même objet que décoder du SSVEP, l'abstraction tient.

Une subtilité qui compte : le moteur doit continuer à **lire** le casque même quand le brut n'est
pas publié — `get_new_data()` VIDE le tampon BrainFlow, et c'est lui qui alimente `_recent`, donc
tous les autres modes. Le mode « brut » ne décide que de la **publication**, jamais de la lecture.

**Files:**
- Modify: `src/core/modes/raw.py`

**Interfaces:**
- Consumes: `ModeRuntime` (tâche 3) · `lsl_io.RawPublisher` · l'attribut `engine.new_block`
  (le bloc d'échantillons du tour courant, `(eeg, lsl_ts)` ou `None`) et `engine.samples`,
  tous deux posés par le moteur à la tâche 7.
- Produces: `raw.RawRuntime` · `raw.SPEC.runtime_cls = RawRuntime`

- [ ] **Step 1 : écrire le test qui échoue**

En fin de `src/core/modes/raw.py` :

```python
def _selftest():
    """Le brut publie ce que le moteur vient de lire — et rien du tout s'il est coupé."""
    import numpy as np

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _FauxPublieur:
        def __init__(self):
            self.blocs = []

        def push(self, eeg, lsl_ts):
            self.blocs.append(np.asarray(eeg))
            return len(eeg)

    class _FauxMoteur:
        samples = 0
        new_block = None

    moteur = _FauxMoteur()
    rt = RawRuntime(SPEC, {}, moteur)
    rt._out = _FauxPublieur()      # on court-circuite LSL : ici on teste le CÂBLAGE, pas le réseau
    rt._opened = True

    chk(rt.phase == "running", "le brut n'a pas de repos : il diffuse tout de suite")
    chk(rt.period_s() == 0.0, "et il est servi à chaque tour de boucle, pas échantillonné")

    bloc = np.zeros((25, 8))
    moteur.new_block = (bloc, np.arange(25, dtype=float))
    rt.tick(moteur, lsl_ts=0.0, now=0.0)
    chk(len(rt._out.blocs) == 1 and rt._out.blocs[0].shape == (25, 8),
        f"le bloc du tour est publié tel quel ({len(rt._out.blocs)} bloc)")
    chk(moteur.samples == 25, f"et compté ({moteur.samples} échantillons)")

    # Un tour sans nouvel échantillon (BrainFlow n'a rien rendu) ne doit rien publier.
    moteur.new_block = None
    rt.tick(moteur, lsl_ts=0.0, now=0.0)
    chk(len(rt._out.blocs) == 1, "un tour sans données ne publie rien")

    print(f"[raw] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
```

Ajouter `use_utf8_console` à l'import de `core.config` en tête du fichier.

- [ ] **Step 2 : lancer, constater l'échec**

Run: `python src/core/modes/raw.py`
Expected: `NameError: name 'RawRuntime' is not defined`

- [ ] **Step 3 : écrire le runtime**

Dans `src/core/modes/raw.py`, entre les imports et `SPEC` :

```python
class RawRuntime(ModeRuntime):
    """Publie le bloc d'échantillons que le moteur vient de lire, sans le toucher.

    « Brut » = tel que le casque le rend, SANS filtrage : c'est un choix, pas un oubli. Chaque
    mode a besoin d'une bande différente (le passe-bande SSVEP 5-40 Hz couperait le P300 et le
    bas du thêta) — filtrer ici imposerait à tous les clients le compromis d'un seul mode.

    ⚠️ Arrêter ce mode arrête la PUBLICATION, pas la lecture du casque : `get_new_data()` vide le
    tampon de BrainFlow et alimente le tampon glissant dont tous les autres modes se servent.
    C'est le moteur qui lit, toujours ; ce mode ne fait que diffuser.
    """

    def __init__(self, spec, params, engine):
        super().__init__(spec, params, engine)
        self._out = None

    def _open(self):
        self._out = RawPublisher(ch_names=CH_NAMES, fs=self.engine.acq.fs,
                                 instance=self.engine.instance)

    def _close(self):
        self._out = None

    def period_s(self):
        # Zéro : le brut est servi à CHAQUE tour de boucle. L'échantillonner introduirait des
        # trous dans un flux continu à 250 Hz, ce qu'aucun client ne pardonnerait.
        return 0.0

    def _run_step(self, engine, lsl_ts):
        if engine.new_block is None or self._out is None:
            return
        eeg, stamps = engine.new_block
        engine.samples += self._out.push(eeg, stamps)
```

Ajouter à l'import de `core.lsl_io` : `from core.lsl_io import RawPublisher` ; et
`from core.modes.runtime import ModeRuntime`.

Enfin, dans `SPEC`, ajouter `runtime_cls=RawRuntime,`.

- [ ] **Step 4 : lancer, vérifier que ça passe**

Run: `python src/core/modes/raw.py`
Expected: `[raw] VERDICT : OK`

- [ ] **Step 5 : le registre voit maintenant un mode exécutable**

Run: `python src/core/modes/registry.py`
Expected: `[registry] 7 modes, dont 1 dans le moteur`, `VERDICT : OK`

- [ ] **Step 6 : commit**

```bash
git add src/core/modes/raw.py
git commit -m "Make streaming the raw signal a mode, so it can be turned off"
```

---

## Tâche 5 : `SsvepRuntime`

Portage de `EngineServer._tick_ssvep`, `_collect_baseline`, `_remember_decision` et
`_log_decision`. **Aucun changement de comportement** : ce code a été validé sur casque le
2026-07-27 (16/16 de justesse quand le moteur émet, 0 confusion sur 36 essais). On le déplace, on
ne l'améliore pas.

Deux différences de forme, sans effet sur le décodage : l'horloge arrive en paramètre, et
`self.freqs` devient `self.params["freqs"]`.

**Files:**
- Modify: `src/core/modes/ssvep.py`

**Interfaces:**
- Consumes: `ModeRuntime` (tâche 3) · `CCADecoder` · `DecodedSSVEPPublisher` ·
  `engine.acq.occipital_window(engine.recent)` · `engine.recent` (tâche 7).
- Produces: `ssvep.SsvepRuntime` · `ssvep.SPEC.runtime_cls = SsvepRuntime`

- [ ] **Step 1 : écrire le test qui échoue**

En fin de `src/core/modes/ssvep.py` :

```python
def _selftest():
    """Le repos, puis la décision — sur du signal FABRIQUÉ, avec un faux moteur.

    On ne juge PAS la justesse du décodage : du bruit synthétique n'a pas de SSVEP, donc la
    cible « détectée » n'a aucun sens. On vérifie l'ENCHAÎNEMENT et le CONTRAT : que le plancher
    se mesure, qu'une fenêtre d'artefact est rejetée plutôt que décodée, et qu'une décision
    publiée porte bien un index dans les bornes.
    """
    import numpy as np

    from core.acquisition import UnicornAcquisition

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _FauxPublieur:
        def __init__(self):
            self.lignes = []

        def push(self, index, freq_hz, confidence, scores, lsl_ts=None):
            self.lignes.append((index, freq_hz, confidence, list(scores)))

    class _FauxMoteur:
        """Juste ce dont un runtime a besoin : une acquisition et un tampon récent."""

        def __init__(self, recent):
            self.acq = UnicornAcquisition(synthetic=True)
            self.instance = "selftest"
            self.recent = recent

    rng = np.random.default_rng(0)
    fs = 250
    bruit = rng.normal(0.0, 8.0, (int(4.0 * fs), 8))
    moteur = _FauxMoteur(bruit)

    values, reason = validate(SPEC, {})
    chk(values is not None, f"les réglages par défaut du SSVEP sont valides ({reason})")

    rt = SsvepRuntime(SPEC, values, moteur)
    rt._out = _FauxPublieur()
    rt._opened = True
    chk(rt.phase == "warmup", "le SSVEP commence par une chauffe")
    chk(len(rt.params["freqs"]) == 3, f"3 cibles par défaut ({rt.params['freqs']})")

    # Repos : on force des durées courtes, comme le fait `--baseline` / `--warmup`.
    rt.begin_rest(now=0.0, warmup_s=0.0, duration_s=1.0)
    now = 0.0
    for _ in range(40):
        now += 0.2
        moteur.recent = rng.normal(0.0, 8.0, (int(4.0 * fs), 8))
        rt.tick(moteur, lsl_ts=now, now=now)
        if rt.phase == "running":
            break
    chk(rt.phase == "running", f"le plancher finit par tenir (phase={rt.phase})")
    chk(rt.rest_report and rt.rest_report["kind"] == "ssvep"
        and len(rt.rest_report["targets"]) == 3,
        f"le repos rend un compte-rendu par cible ({rt.rest_report})")
    chk(rt._sigma_ref and rt._sigma_ref > 0,
        f"un σ de référence est mesuré pour le rejet d'artefact ({rt._sigma_ref})")

    # Décision sur du bruit : l'index doit rester dans les bornes, quoi qu'il décide.
    avant = len(rt._out.lignes)
    rt.tick(moteur, lsl_ts=now, now=now + 0.2)
    chk(len(rt._out.lignes) == avant + 1, "une décision est publiée à chaque pas")
    index, _freq, _conf, scores = rt._out.lignes[-1]
    chk(-1 <= index < 3, f"index de cible dans les bornes ({index})")
    chk(len(scores) == 3, f"un score par cible ({scores})")

    # Artefact : une fenêtre dont l'amplitude explose ne contient pas d'EEG. On publie
    # « aucune cible » plutôt que des corrélations calculées sur un clignement.
    moteur.recent = rng.normal(0.0, 8.0 * 50, (int(4.0 * fs), 8))
    rt.tick(moteur, lsl_ts=now, now=now + 0.4)
    index, _f, _c, scores = rt._out.lignes[-1]
    chk(index == -1 and rt.output()["artifact"],
        f"une fenêtre d'artefact est rejetée, pas décodée (index={index})")

    print(f"[ssvep] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
```

Compléter les imports en tête : `use_utf8_console` depuis `core.config`,
`from core.modes.contract import validate`.

- [ ] **Step 2 : lancer, constater l'échec**

Run: `python src/core/modes/ssvep.py`
Expected: `NameError: name 'SsvepRuntime' is not defined`

- [ ] **Step 3 : porter le runtime**

Dans `src/core/modes/ssvep.py`, entre `FREQS_60HZ` et `SPEC` :

```python
class SsvepRuntime(ModeRuntime):
    """Mesure d'abord le plancher de repos, décide ensuite. Publie sur l'échelle z, toujours.

    Pourquoi un plancher alors que le SSVEP est réputé « sans calibration » : chaque fréquence a
    un fond de corrélation DIFFÉRENT au repos, selon sa proximité au pic alpha du jour. Un seuil
    commun est donc structurellement injuste — mesuré sur ce casque, une cible proche de l'alpha
    n'émettait jamais alors que son ρ moyen dépassait le seuil. Ce n'est pas un modèle appris,
    juste un étalonnage de quelques secondes, à refaire à chaque séance.
    """

    def __init__(self, spec, params, engine):
        super().__init__(spec, params, engine)
        self._out = None
        self.decoder = None
        self._samples, self._sigmas = [], []
        self._sigma_ref = None
        self._warned = False
        self._decoded = None
        self._last_log = 0.0
        self._new_decoder()

    def _new_decoder(self):
        self.decoder = CCADecoder(list(self.params["freqs"]), fs=self.engine.acq.fs)

    def _open(self):
        # Le flux est créé TOUT DE SUITE, avant même la mesure du repos, et reste silencieux
        # jusqu'à ce que le décodage commence. Le faire apparaître seulement à la fin du repos
        # serait un piège : un client qui cherche le flux au lancement ne le trouve pas et
        # abandonne (`resolve_byprop` a un délai fini) — vécu au premier essai casque.
        #
        # L'échelle de décision fait partie du contrat et ne change donc jamais : on décide
        # TOUJOURS sur z, quitte à prolonger le repos jusqu'à pouvoir le mesurer.
        self._out = DecodedSSVEPPublisher(
            list(self.params["freqs"]), decision_scale="z",
            thresholds=(self.decoder.z_min, self.decoder.z_margin),
            instance=self.engine.instance)

    def _close(self):
        self._out = None

    def _reset_rest(self):
        self._samples, self._sigmas = [], []
        self._sigma_ref = None
        self._warned = False
        self._decoded = None
        self._new_decoder()   # un décodeur neuf : son plancher est TOUT ce qu'il a appris

    def period_s(self):
        return 1.0 / (SSVEP_DECODE_HZ if self.phase == "running" else SSVEP_BASELINE_SAMPLE_HZ)

    def output(self):
        return self._decoded

    def _rest_step(self, engine, now):
        window = engine.acq.occipital_window(engine.recent)
        if window is None:
            return False

        self._samples.append(self.decoder.scores(window))
        self._sigmas.append(float(window.std(axis=0).mean()))
        if now < self._rest_until:
            return False

        if not self.decoder.fit_baseline(self._samples):
            # Pas encore assez de fenêtres. On PROLONGE le repos au lieu de basculer sur les ρ
            # bruts : l'échelle de décision est annoncée dans les métadonnées du flux, en
            # changer en cours de route casserait le contrat. Les fenêtres arrivent à 5 Hz.
            if not self._warned:
                self._warned = True
                print(f"[ssvep] repos prolongé : {len(self._samples)} fenêtres, "
                      f"pas encore de quoi mesurer un plancher fiable")
            return False

        self._sigma_ref = float(np.median(self._sigmas))
        line = "  ".join(f"{f:g}Hz: μ={m:.2f} σ={s:.2f}"
                         for f, (m, s) in self.decoder.baseline.items())
        print(f"[ssvep] plancher de repos ({len(self._samples)} fenêtres) — {line}")

        # Un plancher trop DISPERSÉ rend le seuil inatteignable, en silence : on décide sur
        # z=(ρ-μ)/σ, donc un σ gonflé exige un ρ que le SSVEP ne produit jamais en électrodes
        # sèches. Vécu sur casque : σ=0,19 => il aurait fallu ρ≈0,94. Mieux vaut le dire tout de
        # suite que laisser l'utilisateur fixer une cible qui ne peut pas sortir.
        for f, (mu, sd) in self.decoder.baseline.items():
            needed = mu + self.decoder.z_min * sd
            if needed > 0.85:
                print(f"[ssvep] ⚠️  {f:g} Hz : plancher trop dispersé (μ={mu:.2f} σ={sd:.2f}) "
                      f"-> il faudrait ρ={needed:.2f} pour détecter. Cible quasi INDÉTECTABLE : "
                      f"contact des électrodes occipitales, ou refaire le repos immobile.")
        print(f"[ssvep] σ de référence {self._sigma_ref:.1f} -> rejet d'artefact au-delà "
              f"de {ARTIFACT_SIGMA_RATIO * self._sigma_ref:.0f}")
        self.rest_report = {
            "kind": "ssvep",
            "windows": len(self._samples),
            "targets": [{"freq_hz": float(f), "mu": round(mu, 3), "sigma": round(sd, 3),
                         "rho_needed": round(mu + self.decoder.z_min * sd, 2)}
                        for f, (mu, sd) in self.decoder.baseline.items()],
        }
        return True

    def _run_step(self, engine, lsl_ts):
        window = engine.acq.occipital_window(engine.recent)
        if window is None:
            return
        freqs = list(self.params["freqs"])

        # Rejet d'artefact : une fenêtre dont l'amplitude explose par rapport au repos ne
        # contient pas d'EEG (mouvement, clignement). En décoder des ρ produirait des
        # détections aléatoires ; on publie « aucune cible » plutôt que du bruit habillé.
        sd = float(window.std(axis=0).mean())
        if self._sigma_ref and sd > ARTIFACT_SIGMA_RATIO * self._sigma_ref:
            zeros = [0.0] * len(freqs)
            self._publish(-1, 0.0, 0.0, zeros, lsl_ts, artifact=True)
            return

        freq, scores = self.decoder.classify(window)
        ordered = [scores[f] for f in freqs]
        if freq is None:
            self._publish(-1, 0.0, max(ordered), ordered, lsl_ts)
        else:
            index = freqs.index(freq)
            self._publish(index, freq, scores[freq], ordered, lsl_ts)

    def _publish(self, index, freq_hz, confidence, scores, lsl_ts, artifact=False):
        if self._out is not None:
            self._out.push(index, freq_hz, confidence, scores, lsl_ts)
        self._decoded = {
            "target_index": int(index),
            "freq_hz": float(freq_hz),
            "scores": [round(float(v), 2) for v in scores],
            "artifact": bool(artifact),
            "threshold": float(self.decoder.z_min),
        }
        self._log(index, scores, artifact)

    def _log(self, index, scores, artifact):
        """Trace la décision en console ~1×/s.

        Le moteur est fait pour être consommé par un client, mais pendant une séance casque on
        veut voir ce qu'il décode SANS dépendre d'un troisième terminal branché au bon moment.
        Les scores sont affichés à côté de la décision : c'est ce qui permet de dire si une
        non-détection vient d'un signal absent ou d'un seuil trop haut.
        """
        now = _time.perf_counter()
        if now - self._last_log < 1.0:
            return
        self._last_log = now
        freqs = list(self.params["freqs"])
        detail = "  ".join(f"{f:g}Hz z={s:+5.2f}" for f, s in zip(freqs, scores))
        if artifact:
            verdict = "ARTEFACT (fenêtre rejetée)"
        elif index < 0:
            verdict = f"— (rien au-dessus de z={self.decoder.z_min})"
        else:
            verdict = f"CIBLE {index} ({freqs[index]:g} Hz)"
        print(f"[ssvep] {verdict:<34} {detail}")
```

Imports à compléter en tête du fichier :

```python
import time as _time

import numpy as np

from core.cca_decoder import CCADecoder  # noqa: E402
from core.config import ARTIFACT_SIGMA_RATIO  # (ajouter à l'import existant)
from core.lsl_io import DecodedSSVEPPublisher, ssvep_channel_labels  # noqa: E402
from core.modes.runtime import ModeRuntime  # noqa: E402
```

Les cadences vivent avec le mode, plus dans `server.py`. Ajouter après `FREQS_60HZ` :

```python
SSVEP_DECODE_HZ = 5.0            # cadence de décodage (fenêtres glissantes de WINDOW_S)
SSVEP_BASELINE_SAMPLE_HZ = 5.0   # cadence d'échantillonnage du plancher de repos
```

Et dans `SPEC`, ajouter `runtime_cls=SsvepRuntime,`.

- [ ] **Step 4 : lancer, vérifier que ça passe**

Run: `python src/core/modes/ssvep.py`
Expected: `[ssvep] VERDICT : OK`

- [ ] **Step 5 : commit**

```bash
git add src/core/modes/ssvep.py
git commit -m "Move SSVEP decoding into its mode, unchanged"
```

---

## Tâche 6 : `NeuroRuntime`

Portage de `EngineServer._tick_neuro`. Même consigne : on déplace, on ne modifie pas. Ce mode a été
publié le 2026-07-27 mais **son contenu n'a jamais été validé sur casque** — raison de plus pour
n'y toucher qu'en déplacement.

Différence avec le SSVEP : ses deux réglages (`smoothing`, `rebaseline_s`) sont figés dans les
métadonnées du flux et dans le décodeur, donc les changer **recrée** l'un et l'autre.

**Files:**
- Modify: `src/core/modes/neuro.py`

**Interfaces:**
- Consumes: `ModeRuntime` (tâche 3) · `NeuroDecoder` · `DecodedNeuroPublisher` · `engine.recent`.
- Produces: `neuro.NeuroRuntime` · `neuro.SPEC.runtime_cls = NeuroRuntime`

- [ ] **Step 1 : écrire le test qui échoue**

En fin de `src/core/modes/neuro.py` :

```python
def _selftest():
    """Chauffe, repos, publication — sur du bruit fabriqué, avec un faux moteur.

    Le CONTENU n'a aucun sens sur du bruit (il n'y a ni charge mentale ni somnolence dans du
    bruit blanc) : on vérifie le câblage, les phases, et que les z publiés sont FINIS — un NaN
    passerait inaperçu jusque chez le client.
    """
    import math

    import numpy as np

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _FauxPublieur:
        def __init__(self):
            self.lignes = []

        def push(self, z, artifact=False, lsl_ts=None):
            self.lignes.append((dict(z), bool(artifact)))

    class _FauxMoteur:
        instance = "selftest"

        class acq:
            fs = 250

        recent = None

    rng = np.random.default_rng(0)
    moteur = _FauxMoteur()
    moteur.recent = rng.normal(0.0, 10.0, (int(4.0 * 250), 8))

    values, reason = validate(SPEC, {})
    chk(values is not None, f"les réglages par défaut du neuro sont valides ({reason})")
    chk(values["smoothing"] == NEURO_SMOOTH, f"lissage par défaut {values['smoothing']}")

    rt = NeuroRuntime(SPEC, values, moteur)
    rt._out = _FauxPublieur()
    rt._opened = True
    rt.begin_rest(now=0.0, warmup_s=0.0, duration_s=1.0)

    now = 0.0
    for _ in range(60):
        now += 0.2
        moteur.recent = rng.normal(0.0, 10.0, (int(4.0 * 250), 8))
        rt.tick(moteur, lsl_ts=now, now=now)
        if rt.phase == "running":
            break
    chk(rt.phase == "running", f"les échelles finissent par se caler (phase={rt.phase})")
    chk(rt.rest_report and rt.rest_report["kind"] == "neuro",
        f"le repos rend un compte-rendu ({rt.rest_report})")

    for _ in range(5):
        now += 0.2
        moteur.recent = rng.normal(0.0, 10.0, (int(4.0 * 250), 8))
        rt.tick(moteur, lsl_ts=now, now=now)
    chk(len(rt._out.lignes) >= 3, f"{len(rt._out.lignes)} publications après le repos")

    z, _artefact = rt._out.lignes[-1]
    chk(set(z) == set(DecodedNeuroPublisher.KEYS), f"les trois indices attendus ({sorted(z)})")
    chk(all(math.isfinite(v) for v in z.values()), f"tous les z sont finis ({z})")

    sortie = rt.output()
    chk(sortie and set(sortie["z"]) == set(DecodedNeuroPublisher.KEYS),
        "la sortie pour l'affichage porte les trois indices")

    print(f"[neuro] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
```

- [ ] **Step 2 : lancer, constater l'échec**

Run: `python src/core/modes/neuro.py`
Expected: `NameError: name 'NeuroRuntime' is not defined`

- [ ] **Step 3 : porter le runtime**

Dans `src/core/modes/neuro.py`, avant `SPEC` :

```python
class NeuroRuntime(ModeRuntime):
    """Trois indices d'état mental, en z contre le repos du jour. Aucun stimulus, aucune commande.

    C'est le mode le moins exigeant côté client — rien à afficher, rien à synchroniser, aucun
    modèle à entraîner. Il ne demande qu'une chose, mais elle est impérative : un REPOS en début
    de mode, parce que les indices sont des ratios spectraux individuels et dérivants, qui ne
    veulent rien dire sans un zéro personnel.
    """

    def __init__(self, spec, params, engine):
        super().__init__(spec, params, engine)
        self._out = None
        self.decoder = None
        self._samples = []
        self._state = None
        self._warned = False
        self._last_log = 0.0
        self._new_decoder()

    def _new_decoder(self):
        self.decoder = NeuroDecoder(self.engine.acq.fs,
                                    rebaseline_s=self.params["rebaseline_s"])

    def _open(self):
        self._out = DecodedNeuroPublisher(instance=self.engine.instance,
                                          smoothing=self.params["smoothing"],
                                          rebaseline_s=self.params["rebaseline_s"])

    def _close(self):
        self._out = None

    def _reset_rest(self):
        # Un NeuroDecoder neuf : ses échelles (médiane/MAD des indices, σ et EMG de référence)
        # sont TOUTES issues du repos. En garder une partie mélangerait deux états du casque,
        # ce qui est précisément ce qu'un « refaire le repos » corrige.
        self._samples = []
        self._state = None
        self._warned = False
        self._new_decoder()

    def period_s(self):
        return 1.0 / NEURO_UPDATE_HZ

    def output(self):
        return self._state

    def _window(self, engine):
        """Fenêtre BRUTE : le passe-bande d'acquisition couperait le bas du θ. Le décodeur
        applique lui-même son propre passe-haut avant la PSD."""
        n = int(NEURO_WINDOW_S * engine.acq.fs)
        recent = engine.recent
        return None if recent is None or len(recent) < n else recent[-n:]

    def _rest_step(self, engine, now):
        window = self._window(engine)
        if window is None:
            return False
        sample = self.decoder.sample(window)
        if sample is None:
            return False

        self._samples.append(sample)
        if now < self._rest_until:
            return False

        if not self.decoder.fit_baseline(self._samples):
            if not self._warned:
                self._warned = True
                print(f"[neuro] repos prolongé : {len(self._samples)} fenêtres, "
                      "pas encore de quoi caler les échelles")
            return False

        centres = "  ".join(f"{k}: repos≈{self.decoder.norm.center(k):.3f}"
                            for k in self.decoder.norm.mu)
        print(f"[neuro] échelles calées ({len(self._samples)} fenêtres) — {centres}")
        print("[neuro] z contre CE repos — ni comparable entre personnes, ni absolu")
        self.rest_report = {
            "kind": "neuro",
            "windows": len(self._samples),
            "targets": [{"index": k, "rest_center": round(float(self.decoder.norm.center(k)), 4)}
                        for k in self.decoder.norm.mu],
        }
        return True

    def _run_step(self, engine, lsl_ts):
        window = self._window(engine)
        if window is None:
            return
        sample = self.decoder.sample(window)
        if sample is None:
            return

        out = self.decoder.step(sample)
        if self._out is not None:
            self._out.push(out["z"], out["artifact"], lsl_ts)
        self._state = {
            "z": {k: round(float(v), 2) for k, v in out["z"].items()},
            "raw": {k: round(float(v), 4) for k, v in (out["raw"] or {}).items()},
            "artifact": bool(out["artifact"]),
            "reason": out["reason"],
            "artifacts": self.decoder.artifacts,
        }
        now = _time.perf_counter()
        if now - self._last_log >= 2.0:
            self._last_log = now
            print("[neuro] z " + "  ".join(f"{k}={v:+.2f}" for k, v in out["z"].items())
                  + f"  artefacts={self.decoder.artifacts}"
                  + (f"  ({out['reason']})" if out["artifact"] else ""))
```

Imports à compléter en tête :

```python
import time as _time

from core.config import (NEURO_UPDATE_HZ, NEURO_WINDOW_S, use_utf8_console)  # + à l'import existant
from core.modes.contract import validate  # noqa: E402
from core.modes.runtime import ModeRuntime  # noqa: E402
from core.neuro_monitor import NeuroDecoder  # noqa: E402
```

Et dans `SPEC`, ajouter `runtime_cls=NeuroRuntime,`.

⚠️ Le lissage EMA vit dans `NeuroDecoder.norm` (`IndexNormalizer(smooth=...)`). Vérifier à
l'écriture que `NeuroDecoder.__init__` accepte de transmettre `smoothing` ; s'il ne le fait pas
encore, poser `self.decoder.norm.smooth = self.params["smoothing"]` juste après `_new_decoder()`,
avec un commentaire disant pourquoi ce réglage ne peut pas être changé après le repos sans le
refaire.

- [ ] **Step 4 : lancer, vérifier que ça passe**

Run: `python src/core/modes/neuro.py`
Expected: `[neuro] VERDICT : OK`

- [ ] **Step 5 : le registre voit trois modes exécutables**

Run: `python src/core/modes/registry.py`
Expected: `[registry] 7 modes, dont 3 dans le moteur`, `VERDICT : OK`

- [ ] **Step 6 : commit**

```bash
git add src/core/modes/neuro.py
git commit -m "Move passive neuro monitoring into its mode, unchanged"
```

---

## Tâche 7 : le moteur fait tourner N modes

La tâche centrale, et la seule qu'on ne peut pas couper en deux : un moteur à moitié refondu ne
passe aucun test. Elle est longue en pas, pas en risque — chaque morceau de logique a déjà été
déplacé et testé aux tâches 4 à 6.

Le moteur ne garde que le **vraiment commun** : session casque, tampon glissant `_recent`, horloge,
qualité du signal, et la file de commandes. Tout le reste descend dans les runtimes.

**Files:**
- Modify: `src/core/server.py`

**Interfaces:**
- Consumes: `registry` (tâche 2) · `contract.validate` (tâche 1) · les trois runtimes (tâches 4-6).
- Produces:
  - `EngineServer(serial=None, synthetic=False, verbose=False, modes=("raw",), params=None,
    instance=None)`
  - `engine.active: dict[str, ModeRuntime]` · `engine.recent` (le tampon, usage interne) ·
    `engine.new_block: tuple | None` · `engine.samples: int`
  - `engine.recent_window(seconds) -> np.ndarray | None` — **copie**, pour un afficheur
  - `engine.submit(command, **params) -> {"accepted": bool, ...}` : `start_mode` · `stop_mode` ·
    `set_params` · `set_published` · `recalibrate` · `stop`
  - `engine.snapshot() -> dict` avec les clés `running`, `board`, `instance`, `fs_hz`, `channels`,
    `phase`, `samples_published`, `streams`, `quality`, `rest_instruction`, `modes`, `catalog`
  - `engine.run(duration_s=None, baseline_s=None, warmup_s=None) -> int`

- [ ] **Step 1 : nouveau constructeur et état du moteur**

Remplacer `EngineServer.__init__` et supprimer `_setup_ssvep`, `_setup_ssvep_durations`,
`_setup_neuro`, `_validate_freqs`, `_set_freqs`, `_restart_baseline`, `_tick_ssvep`, `_tick_neuro`,
`_collect_baseline`, `_remember_decision`, `_log_decision`, et la propriété `decoding`.

```python
    def __init__(self, serial=None, synthetic=False, verbose=False, modes=("raw",),
                 params=None, instance=None):
        """`modes` : les identifiants à démarrer. `params` : {mode_id: {clé: valeur}}, facultatif.

        Un identifiant inconnu ou un réglage invalide lève ici, au démarrage — bruyamment et
        tout de suite, plutôt qu'en séance sur un décodage qui ne détecte jamais rien.
        """
        self.synthetic = synthetic
        self.acq = UnicornAcquisition(serial=serial, synthetic=synthetic, verbose=verbose)
        self.clock = ClockBridge()
        self.instance = instance or default_instance_id(serial, synthetic)
        self.quality_out = QualityPublisher(ch_names=CH_NAMES, instance=self.instance)
        self.status_out = StatusPublisher(instance=self.instance)
        self.samples = 0
        self.new_block = None       # le bloc lu au tour courant : (eeg, horodatages LSL) ou None
        self.recent = np.zeros((0, len(CH_NAMES)))
        self.active = {}            # {mode_id: ModeRuntime}, dans l'ordre du registre
        self.rest_instruction = ""  # la consigne du repos en cours, partagée s'il l'est
        self._stop = False
        self._last_tick = {}
        self._commands = queue.Queue()
        self._quality = None
        self._reference_lost = None
        self._warmup_override = None
        self._rest_override = None

        # Le tampon doit satisfaire le plus gourmand des consommateurs : la qualité veut
        # QUALITY_WINDOW_S, le SSVEP WINDOW_S, le neuro NEURO_WINDOW_S — chacun plus la marge de
        # filtre. On dimensionne sur TOUS les modes, pas sur ceux qui tournent : démarrer un mode
        # en cours de séance ne doit pas dépendre de la taille d'un tampon.
        self.keep = max(int(QUALITY_WINDOW_S * self.acq.fs),
                        int(NEURO_WINDOW_S * self.acq.fs),
                        self.acq.window_n) + self.acq.margin_n

        self._pending = self._prepare(modes or (), params or {})

    def _prepare(self, modes, params):
        """Valide les modes demandés au démarrage. Retourne [(spec, réglages), ...]."""
        prepared = []
        for spec in registry.MODES:            # l'ordre du registre, toujours
            if spec.id not in modes:
                continue
            if spec.runtime_cls is None:
                raise ValueError(f"« {spec.label} » ne tourne pas dans le moteur : "
                                 f"{spec.unavailable}")
            values, reason = contract.validate(spec, params.get(spec.id, {}))
            if values is None:
                raise ValueError(reason)
            prepared.append((spec, values))
        inconnus = sorted(set(modes) - {s.id for s, _ in prepared})
        if inconnus:
            connus = ", ".join(s.id for s in registry.runnable())
            raise ValueError(f"mode inconnu : {', '.join(inconnus)} (disponibles : {connus})")
        return prepared
```

- [ ] **Step 2 : démarrer, arrêter, régler — les opérations sur les modes**

```python
    def _start(self, ids, values, now):
        """Démarre des modes. Ceux lancés ENSEMBLE partagent une seule phase de repos."""
        demarres = []
        for spec in registry.MODES:            # ordre du registre : il arbitre les égalités
            if spec.id not in ids:
                continue
            runtime = spec.runtime_cls(spec, values[spec.id], self)
            runtime.open()
            self.active[spec.id] = runtime
            self._last_tick[spec.id] = 0.0
            demarres.append(runtime)
        self._begin_shared_rest(demarres, now)
        for runtime in demarres:
            if runtime.spec.stream:
                print(f"[server] {runtime.spec.label} démarré — flux "
                      f"{stream_name(runtime.spec.stream)}"
                      + (" (silencieux pendant le repos)" if runtime.spec.rest else ""))

    def _begin_shared_rest(self, runtimes, now):
        """Un seul repos pour tous ceux qui en demandent un, si on les lance ensemble.

        Les consignes sont compatibles — « ne fixe aucune cible » et « immobile et détendu »
        décrivent le même moment — donc imposer deux repos de suite ferait attendre l'étudiant
        pour rien. Lancés SÉPARÉMENT, chacun fait le sien : un mode démarré alors qu'un autre
        tourne déjà ne peut pas réutiliser un repos qu'il n'a pas observé.

        Trois règles déterministes, pour qu'il n'y ait rien à interpréter : la durée retenue est
        le MAXIMUM des durées demandées, la chauffe le MAXIMUM des chauffes, et la consigne
        affichée celle du mode dont le repos est le plus long. À égalité, `max` rend le premier
        de la liste — qui est dans l'ordre du registre.
        """
        for runtime in runtimes:
            if runtime.spec.rest is None:
                runtime.begin_rest(now)        # met la phase à « running », rien de plus
        au_repos = [r for r in runtimes if r.spec.rest is not None]
        if not au_repos:
            return

        chauffe = max(r.spec.rest.warmup_s for r in au_repos)
        duree = max(r.spec.rest.duration_s for r in au_repos)
        if self._warmup_override is not None:
            chauffe = self._warmup_override
        if self._rest_override is not None:
            duree = self._rest_override
        meneur = max(au_repos, key=lambda r: r.spec.rest.duration_s)
        self.rest_instruction = meneur.spec.rest.instruction
        for runtime in au_repos:
            runtime.begin_rest(now, warmup_s=chauffe, duration_s=duree)
        quoi = ", ".join(r.spec.label for r in au_repos)
        print(f"[server] repos ({quoi}) : stabilisation {chauffe:.0f} s puis {duree:.0f} s — "
              f"{self.rest_instruction}")

    def _stop_mode(self, mode_id):
        runtime = self.active.pop(mode_id, None)
        if runtime is None:
            return
        runtime.close()
        self._last_tick.pop(mode_id, None)
        if not any(r.phase in ("warmup", "rest") for r in self.active.values()):
            self.rest_instruction = ""
        print(f"[server] {runtime.spec.label} arrêté — son flux disparaît du réseau")

    def _set_params(self, mode_id, values):
        """Applique des réglages. Le repos de CE mode repart s'il en a un.

        Un plancher mesuré sous d'autres réglages est faux : pour le SSVEP il est mesuré PAR
        FRÉQUENCE, le garder après changement comparerait le ρ d'une cible au bruit de fond
        d'une autre. On recrée aussi le flux, parce que les métadonnées LSL sont figées à la
        création et que les voies portent les fréquences (`score_15Hz`) — garder l'ancien flux
        publierait des étiquettes fausses. Les clients doivent se réabonner ; le NOM ne change
        pas, un nouveau `resolve_byprop` suffit.
        """
        ancien = self.active[mode_id]
        spec = ancien.spec
        avant = dict(ancien.params)
        ancien.close()
        runtime = spec.runtime_cls(spec, values, self)
        runtime.published = ancien.published
        if runtime.published:
            runtime.open()
        self.active[mode_id] = runtime
        self._last_tick[mode_id] = 0.0
        self._begin_shared_rest([runtime], time.perf_counter())
        changes = ", ".join(f"{k} : {avant[k]} -> {v}" for k, v in values.items()
                            if avant.get(k) != v)
        print(f"[server] {spec.label} — {changes or 'aucun changement'}"
              + (f" ; flux {stream_name(spec.stream)} RECRÉÉ (réabonnez-vous)"
                 if spec.stream else ""))

    def _set_published(self, mode_id, on):
        runtime = self.active[mode_id]
        runtime.set_published(on)
        print(f"[server] {runtime.spec.label} : "
              + ("publié sur le réseau" if on else "décodé pour l'affichage seulement, "
                                                   "son flux disparaît du réseau"))

    def _recalibrate(self, mode_id):
        self._begin_shared_rest([self.active[mode_id]], time.perf_counter())
```

- [ ] **Step 3 : l'API de commande**

Remplacer `submit` et `_apply`. La validation reste **à la soumission**, avec sa raison en clair.

```python
    # --- API de commande interne (SPEC §12.1) --------------------------------
    # La console et, plus tard, l'adaptateur de commandes LSL passent tous les deux PAR ICI.
    # Un seul chemin à tester, et le protocole de contrôle reste remplaçable sans réécrire le
    # moteur.
    #
    # Les commandes ne sont PAS appliquées par le fil qui les soumet : elles sont mises en file
    # et exécutées par la boucle. C'est ce qui garantit que la session BrainFlow n'est touchée
    # que depuis un seul fil — la partager entre l'interface et l'acquisition produirait des
    # corruptions qu'aucun test ne rattraperait.

    COMMANDS = ("start_mode", "stop_mode", "set_params", "set_published", "recalibrate", "stop")

    def submit(self, command, **params):
        """Met une commande en file. Retourne un accusé, PAS le résultat (appliqué plus tard).

        Une exception à la règle « accusé seulement » : la VALIDITÉ est vérifiée ici, tout de
        suite. Le refus d'une commande mal formée est une propriété du message, pas de l'état du
        moteur, et la renvoyer immédiatement évite à l'étudiant de chercher pourquoi son réglage
        n'a rien fait. Ce que `submit` ne promet toujours pas, c'est que la commande ait été
        APPLIQUÉE : ça s'observe sur `snapshot()` ou sur le flux `status`.
        """
        if command not in self.COMMANDS:
            return {"accepted": False,
                    "reason": f"commande inconnue : {command} "
                              f"(connues : {', '.join(self.COMMANDS)})"}

        if command == "stop":
            self._commands.put(("stop", {}))
            return {"accepted": True, "command": "stop"}

        if command == "start_mode":
            ids = params.get("ids") or ([params["id"]] if params.get("id") else [])
            if not ids:
                return {"accepted": False, "reason": "aucun mode demandé (id ou ids)"}
            specs, reason = self._resolve(ids, doit_tourner=False)
            if specs is None:
                return {"accepted": False, "reason": reason}
            wanted, values = params.get("params") or {}, {}
            for spec in specs:
                v, reason = contract.validate(spec, wanted.get(spec.id, {}))
                if v is None:
                    return {"accepted": False, "reason": reason}
                values[spec.id] = v
            ids = [s.id for s in specs]
            self._commands.put(("start_mode", {"ids": ids, "params": values}))
            return {"accepted": True, "command": "start_mode", "ids": ids}

        spec, reason = self._one(params.get("id"))
        if spec is None:
            return {"accepted": False, "reason": reason}

        if command == "stop_mode":
            self._commands.put(("stop_mode", {"id": spec.id}))
        elif command == "set_published":
            self._commands.put(("set_published",
                                {"id": spec.id, "on": bool(params.get("on", True))}))
        elif command == "recalibrate":
            if spec.rest is None:
                return {"accepted": False,
                        "reason": f"« {spec.label} » n'a pas de repos à refaire"}
            self._commands.put(("recalibrate", {"id": spec.id}))
        elif command == "set_params":
            # On fusionne sur les réglages COURANTS : un appelant peut n'envoyer que ce qu'il
            # change, sans avoir à relire et renvoyer tout le reste.
            merged = dict(self.active[spec.id].params)
            merged.update(params.get("params") or {})
            values, reason = contract.validate(spec, merged)
            if values is None:
                return {"accepted": False, "reason": reason}
            self._commands.put(("set_params", {"id": spec.id, "params": values}))
        return {"accepted": True, "command": command, "id": spec.id}

    def _resolve(self, ids, doit_tourner):
        """(specs dans l'ordre du registre, None) ou (None, raison). Refuse tôt et en clair."""
        for mode_id in ids:
            spec = registry.get(mode_id)
            if spec is None:
                connus = ", ".join(s.id for s in registry.runnable())
                return None, f"mode inconnu : {mode_id} (disponibles : {connus})"
            if spec.runtime_cls is None:
                # C'est exactement ce que la tuile doit dire à l'étudiant : POURQUOI ça ne
                # démarre pas, jamais un échec silencieux.
                return None, f"« {spec.label} » ne tourne pas dans le moteur : {spec.unavailable}"
            if not doit_tourner and spec.id in self.active:
                return None, (f"« {spec.label} » est déjà démarré — utilise « refaire le repos » "
                              f"pour le relancer")
            if doit_tourner and spec.id not in self.active:
                return None, f"« {spec.label} » n'est pas démarré"
        return [s for s in registry.MODES if s.id in ids], None

    def _one(self, mode_id):
        specs, reason = self._resolve([mode_id] if mode_id else [], doit_tourner=True)
        if specs is None:
            return None, reason
        if not specs:
            return None, "aucun mode désigné (id manquant)"
        return specs[0], None

    def _apply(self, command, params):
        if command == "stop":
            self.stop()
        elif command == "start_mode":
            self._start(params["ids"], params["params"], time.perf_counter())
        elif command == "stop_mode":
            self._stop_mode(params["id"])
        elif command == "set_params":
            self._set_params(params["id"], params["params"])
        elif command == "set_published":
            self._set_published(params["id"], params["on"])
        elif command == "recalibrate":
            self._recalibrate(params["id"])
```

⚠️ Une commande peut être soumise sur un mode que la boucle a arrêté entre-temps.
`_apply` doit donc être tolérant : `_set_params`, `_set_published` et `_recalibrate` accèdent à
`self.active[mode_id]`. Envelopper chacun d'un `if mode_id not in self.active: return`, ou
laisser `_drain_commands` attraper l'exception — il le fait déjà et affiche « commande rejetée ».
**Choisir la garde explicite** : un message qui dit « le mode a été arrêté entre-temps » vaut mieux
qu'un `KeyError` imprimé.

- [ ] **Step 4 : la phase globale et l'état publié**

```python
    # Le contrat public de `status` emploie « baseline » et « decoding » depuis le début ; les
    # runtimes emploient le vocabulaire de la spec (« rest », « running »). On traduit ici
    # plutôt que de renommer une valeur du contrat pour un confort interne.
    _PHASES_PUBLIQUES = {"warmup": "warmup", "rest": "baseline", "running": "decoding"}

    @property
    def phase(self):
        """La phase la MOINS avancée parmi les modes qui mesurent un repos.

        « streaming » quand aucun mode actif n'a de repos à faire : c'est le cas du brut seul.
        """
        phases = [r.phase for r in self.active.values() if r.spec.rest is not None]
        if not phases:
            return "streaming"
        for interne in ("warmup", "rest", "running"):
            if interne in phases:
                return self._PHASES_PUBLIQUES[interne]
        return "streaming"

    def _status_key(self, running):
        """Ce qui constitue un vrai CHANGEMENT d'état — hors compteurs (cf. StatusPublisher.push).

        Un compteur glissé ici défait la déduplication : mesuré une fois à 19,6 Hz de messages
        d'état au lieu de 0,5 Hz, assez discret pour passer inaperçu, assez bruyant pour noyer
        un client.
        """
        return (running, self.synthetic, self.phase,
                tuple((mid, r.phase, r.published) for mid, r in sorted(self.active.items())))

    def _state(self, running):
        streams = ["quality", "status"]
        for spec in registry.MODES:
            runtime = self.active.get(spec.id)
            if runtime is not None and runtime.published and spec.stream:
                streams.append(spec.stream)
        actifs = [mid for mid in self.active]
        # `mode` (au singulier) reste publié pour ne pas casser un client écrit contre le flux
        # `status` d'hier : il porte le premier mode DÉCODÉ actif, ou null. `modes` porte la
        # vérité complète. Le jour où plusieurs modes décodent, `mode` en montre un seul — c'est
        # assumé, et c'est pour ça que `modes` existe.
        decodes = [mid for mid in actifs if mid != "raw"]
        state = {
            "running": running,
            "board": "synthetic" if self.synthetic else "unicorn",
            "instance": self.instance,
            "fs_hz": float(self.acq.fs),
            "channels": list(CH_NAMES),
            "mode": decodes[0] if decodes else None,
            "modes": actifs,
            "phase": self.phase,
            "samples_published": self.samples,
            "streams": [stream_name(s) for s in streams],
        }
        if self.rest_instruction and self.phase in ("warmup", "baseline"):
            state["instruction"] = self.rest_instruction
        return state

    def snapshot(self):
        """État complet pour un afficheur, en lecture seule. Sûr depuis un autre fil.

        On rend un dictionnaire déjà construit plutôt que des références vers l'état vivant :
        l'appelant ne peut donc pas lire une valeur à moitié écrite par la boucle.
        """
        state = self._state(not self._stop)
        state.update({
            "quality": self._quality,
            "rest_instruction": self.rest_instruction,
            "modes_state": {mid: r.state() for mid, r in self.active.items()},
            "catalog": registry.catalog(),
        })
        return state

    def recent_window(self, seconds):
        """Copie des `seconds` dernières secondes de signal BRUT (n, 8), ou None.

        Accesseur PUBLIC pour un afficheur. Le tampon est réécrit par le fil d'acquisition : le
        lire directement depuis le fil Qt donnerait, tôt ou tard, une vue à moitié écrite. On
        rend donc une copie — c'est quelques centaines de Ko, payés une fois par rafraîchissement.
        """
        buffer = self.recent
        if buffer is None or len(buffer) == 0:
            return None
        n = max(1, int(seconds * self.acq.fs))
        return np.array(buffer[-n:], dtype=float, copy=True)
```

⚠️ `snapshot()` expose `modes_state` (l'état vivant) **en plus** de `modes` (la liste d'ids, qui
part aussi sur `status`). Deux clés au lieu d'une pour ne pas publier un gros dictionnaire sur un
flux LSL qui doit rester léger.

- [ ] **Step 5 : la boucle**

```python
    def run(self, duration_s=None, baseline_s=None, warmup_s=None):
        """Boucle principale. `duration_s=None` = jusqu'à Ctrl+C.

        `baseline_s` / `warmup_s` à None = les durées PROPRES À CHAQUE MODE, posées par son
        contrat. Les passer explicitement les remplace, pour tous les modes — ce dont les tests
        headless ont besoin pour ne pas durer 40 s chacun.
        """
        self._warmup_override = warmup_s
        self._rest_override = baseline_s
        # Le moteur écrit des µ, des σ et des accents. Sous PowerShell, stdout est en cp1252 par
        # défaut : un simple print tuait alors le fil d'acquisition sur un UnicodeEncodeError. On
        # le fait ici plutôt que dans le seul `__main__`, parce que le moteur est aussi utilisé
        # comme bibliothèque (console, tests) — et qu'un échec d'AFFICHAGE ne doit jamais
        # interrompre une ACQUISITION.
        use_utf8_console()

        started = time.perf_counter()
        last_quality = last_status = 0.0

        with self.acq:
            print(f"[server] board={self.acq.board_id.name} fs={self.acq.fs} Hz "
                  f"instance={self.instance}")
            for suffix in ("quality", "status"):
                print(f"[server] flux LSL publie : {stream_name(suffix)}")
            self._start([s.id for s, _ in self._pending],
                        {s.id: v for s, v in self._pending}, time.perf_counter())
            self.status_out.push(self._state(True), key=self._status_key(True), force=True)

            while not self._stop:
                self._drain_commands()
                now = time.perf_counter()
                if duration_s is not None and now - started >= duration_s:
                    break

                # UNE seule lecture par tour, quels que soient les modes actifs :
                # `get_new_data()` VIDE le tampon de BrainFlow. C'est l'invariant central du
                # moteur — c'est aussi pourquoi le tampon glissant est tenu ICI et pas là-bas.
                eeg, ts_unix = self.acq.get_new_data()
                self.new_block = None
                if eeg is not None and len(eeg):
                    self.new_block = (eeg, self.clock.to_lsl(ts_unix))
                    self.recent = np.vstack([self.recent, eeg])[-self.keep:]

                if now - last_quality >= QUALITY_PERIOD_S:
                    self._publish_quality(self.clock.to_lsl(time.time()))
                    last_quality = now

                for mode_id, runtime in list(self.active.items()):
                    if now - self._last_tick.get(mode_id, 0.0) >= runtime.period_s():
                        runtime.tick(self, self.clock.to_lsl(time.time()), now)
                        self._last_tick[mode_id] = now

                # Publié quand l'état change, plus un rappel périodique pour les clients qui se
                # connectent après le démarrage (LSL ne rejoue pas le passé).
                due = now - last_status >= STATUS_PERIOD_S
                if self.status_out.push(self._state(True), key=self._status_key(True),
                                        force=due) and due:
                    last_status = now

                time.sleep(POLL_S)

            self.status_out.push(self._state(False), key=self._status_key(False), force=True)
            for runtime in self.active.values():
                runtime.close()

        elapsed = time.perf_counter() - started
        print(f"[server] arrêt : {self.samples} échantillons publiés en {elapsed:.1f} s "
              f"({self.samples / max(elapsed, 1e-9):.1f} Hz effectif)")
        return self.samples
```

⚠️ `_publish_quality` ne change pas, sauf `self._recent` → `self.recent`. Même remarque pour
`_json_float`, qui reste.

- [ ] **Step 6 : la ligne de commande**

Remplacer `--mode` (`choices=["ssvep","neuro"]`) par une liste, et `--freqs` par un réglage du
mode SSVEP.

```python
    p.add_argument("--mode", default=None,
                   help="décodeurs à démarrer, séparés par des virgules : "
                        + ", ".join(s.id for s in registry.runnable() if s.id != "raw")
                        + ". Ils tournent EN MÊME TEMPS et partagent une seule phase de repos. "
                          "Le brut est diffusé en plus, sauf avec --no-raw")
    p.add_argument("--no-raw", action="store_true",
                   help="ne pas diffuser le signal brut (le décodage continue)")
```

Et la construction :

```python
    modes = [m.strip() for m in (args.mode or "").split(",") if m.strip()]
    if not args.no_raw:
        modes.insert(0, "raw")
    params = {}
    if args.freqs:
        params["ssvep"] = {"freqs": [float(f) for f in args.freqs.split(",")]}
    elif args.refresh:
        params["ssvep"] = {"freqs": [c["actual_hz"] for c in choose_frequencies(args.refresh)]}
    engine = EngineServer(serial=args.serial, synthetic=args.synthetic, verbose=args.verbose,
                          modes=modes, params=params, instance=args.instance)
```

⚠️ **Le brut reste diffusé par défaut** : `python src/core/server.py --mode ssvep` publie
`raw` + `decoded_ssvep`, exactement comme hier. Les commandes documentées dans `CLAUDE.md` et
`README.md` gardent donc leur comportement, et la capacité nouvelle — couper le brut — passe par
un drapeau explicite.

⚠️ `params["ssvep"]` est posé même si le SSVEP n'est pas demandé (`--freqs` sans `--mode ssvep`).
`_prepare` ignore les réglages d'un mode non démarré ; le vérifier à l'écriture, sinon filtrer
`params` sur `modes`.

- [ ] **Step 7 : adapter les trois smokes existants**

Trois changements mécaniques, identiques dans `_smoke`, `_smoke_ssvep` et `_smoke_neuro` :

```python
    # avant : EngineServer(synthetic=True, instance=instance)
    server = EngineServer(synthetic=True, instance=instance)               # inchangé (raw seul)

    # avant : EngineServer(synthetic=True, mode="ssvep", freqs=freqs, instance=instance)
    server = EngineServer(synthetic=True, modes=("raw", "ssvep"),
                          params={"ssvep": {"freqs": freqs}}, instance=instance)

    # avant : EngineServer(synthetic=True, mode="neuro", instance=instance)
    server = EngineServer(synthetic=True, modes=("raw", "neuro"), instance=instance)
```

Les attentes sur `server.phase` (`!= "decoding"`) restent valables : la traduction de vocabulaire
de l'étape 4 les préserve. C'est précisément le test de cette traduction.

- [ ] **Step 8 : lancer les smokes**

Run: `python src/core/server.py --smoke`
Expected: `[smoke] VERDICT : OK` · `[smoke-ssvep] VERDICT : OK` · `[smoke-neuro] VERDICT : OK`

Run: `python src/research/app.py --smoke`
Expected: `VERDICT : OK` — l'appli pygame ne touche pas au moteur, mais elle partage `core` ;
c'est le garde-fou nommé par la spec §9.

- [ ] **Step 9 : essai à la main, pour voir ce que ça donne**

Run: `python src/core/server.py --synthetic --mode ssvep,neuro --duration 25 --baseline 4 --warmup 1`
Expected: **un seul** bloc `[server] repos (SSVEP, Neuro)` avec la consigne du neuro (repos le plus
long), puis les deux modes qui publient — `[ssvep]` et `[neuro]` alternent dans la console. Quatre
flux annoncés : `raw`, `quality`, `status`, plus `decoded_ssvep` et `decoded_neuro`.

C'est la première fois que le cumul tourne. Il est vérifié pour de bon à la tâche 8 ; ici on
regarde.

- [ ] **Step 10 : commit**

```bash
git add src/core/server.py
git commit -m "Run modes side by side, each with its own phase"
```

---

## Tâche 8 : les tests que la refonte rend nécessaires

Quatre vérifications nommées par la spec §7, toutes dans `server.py --smoke` — la commande que
`CLAUDE.md` désigne comme le test à passer après toute modification. Aucune ne doit pouvoir être
oubliée en lançant un fichier isolé.

**Files:**
- Modify: `src/core/server.py`

**Interfaces:**
- Consumes: tout ce qui précède.
- Produces: `_smoke_cumul()` · `_smoke_repos_partage()` · `_smoke_frontiere()`, et `_smoke()`
  qui appelle en plus `registry.check()` et les autotests de contrat.

- [ ] **Step 1 : écrire le test du cumul**

```python
def _smoke_cumul():
    """Deux modes qui tournent ENSEMBLE : chacun publie, arrêter l'un ne perturbe pas l'autre.

    C'est la propriété neuve de ce chantier, et celle qu'on ne peut pas déduire des tests par
    mode : deux décodeurs sur le même tampon glissant, deux flux, deux phases.
    """
    import threading

    from pylsl import StreamInlet

    instance = "smoke-cumul"
    server = EngineServer(synthetic=True, modes=("raw", "ssvep", "neuro"), instance=instance)
    thread = threading.Thread(
        target=server.run,
        kwargs={"duration_s": 20.0, "baseline_s": 3.0, "warmup_s": 1.0}, daemon=True)
    thread.start()

    ok = True
    inlets = {}
    for suffix in ("decoded_ssvep", "decoded_neuro"):
        found = _resolve_own(suffix, instance, 6.0)
        if not found:
            print(f"[smoke-cumul] ÉCHEC : {suffix} introuvable — les deux modes doivent "
                  f"publier en même temps")
            server.stop()
            return False
        inlets[suffix] = StreamInlet(found)
        inlets[suffix].open_stream(timeout=5.0)

    t0 = time.perf_counter()
    while server.phase != "decoding" and time.perf_counter() - t0 < 15.0 and thread.is_alive():
        for inlet in inlets.values():
            inlet.pull_chunk(timeout=0.05, max_samples=64)
    if server.phase != "decoding":
        print(f"[smoke-cumul] ÉCHEC : toujours en « {server.phase} » après 15 s")
        server.stop()
        return False

    recu = {suffix: 0 for suffix in inlets}
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 3.0 and thread.is_alive():
        for suffix, inlet in inlets.items():
            chunk, _ts = inlet.pull_chunk(timeout=0.1, max_samples=64)
            recu[suffix] += len(chunk)
    print(f"[smoke-cumul] reçu {recu} pendant que les deux décodent")
    for suffix, n in recu.items():
        if n < 3:
            print(f"[smoke-cumul] ÉCHEC : {suffix} n'a publié que {n} fois")
            ok = False

    # Arrêter l'un ne doit pas perturber l'autre : c'est ce qui rend le cumul utilisable.
    ack = server.submit("stop_mode", id="ssvep")
    if not ack.get("accepted"):
        print(f"[smoke-cumul] ÉCHEC : stop_mode refusé ({ack})")
        ok = False
    arrete = False
    for _ in range(40):
        time.sleep(0.1)
        if "ssvep" not in server.snapshot()["modes"]:
            arrete = True
            break
    if not arrete:
        print("[smoke-cumul] ÉCHEC : le SSVEP est toujours actif après stop_mode")
        ok = False

    apres, t0 = 0, time.perf_counter()
    while time.perf_counter() - t0 < 2.0 and thread.is_alive():
        chunk, _ts = inlets["decoded_neuro"].pull_chunk(timeout=0.1, max_samples=64)
        apres += len(chunk)
    print(f"[smoke-cumul] le neuro a publié {apres} fois APRÈS l'arrêt du SSVEP")
    if apres < 3:
        print("[smoke-cumul] ÉCHEC : arrêter un mode a perturbé l'autre")
        ok = False

    # Dernier mode décodé arrêté : le moteur reste vivant, quality et status continuent.
    server.submit("stop_mode", id="neuro")
    time.sleep(0.5)
    state = server.snapshot()
    if not state["running"] or stream_name("quality") not in state["streams"]:
        print(f"[smoke-cumul] ÉCHEC : le moteur ne survit pas au dernier mode arrêté ({state})")
        ok = False

    server.stop()
    thread.join(timeout=5.0)
    print(f"[smoke-cumul] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok
```

- [ ] **Step 2 : écrire le test du repos partagé**

Sans LSL ni fil : c'est de la logique pure, et un test qui ne dort pas se relance sans hésiter.

```python
def _smoke_repos_partage():
    """Lancés ENSEMBLE : un seul repos. Lancés SÉPARÉMENT : chacun le sien.

    La règle vient du terrain : « ne fixe aucune cible » et « immobile et détendu » décrivent le
    même moment, donc enchaîner deux repos ferait attendre l'étudiant pour rien. Mais un mode
    démarré alors qu'un autre tourne déjà ne peut PAS réutiliser un repos qu'il n'a pas observé.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    ssvep, neuro = registry.get("ssvep"), registry.get("neuro")

    # 1. Ensemble : durée = max, chauffe = max, consigne = celle du repos le plus long.
    server = EngineServer(synthetic=True, modes=("ssvep", "neuro"), instance="smoke-repos")
    server._start(["ssvep", "neuro"], {s.id: v for s, v in server._pending}, now=0.0)
    a, b = server.active["ssvep"], server.active["neuro"]
    chk(a._rest_s == b._rest_s == max(ssvep.rest.duration_s, neuro.rest.duration_s),
        f"une seule durée de repos, la plus longue ({a._rest_s:g} s)")
    chk(a._warmup_s == b._warmup_s == max(ssvep.rest.warmup_s, neuro.rest.warmup_s),
        f"une seule chauffe, la plus longue ({a._warmup_s:g} s)")
    chk(server.rest_instruction == neuro.rest.instruction,
        f"la consigne est celle du repos le plus long — « {server.rest_instruction[:40]}… »")
    chk(a._warmup_until == b._warmup_until,
        "les deux modes sortent de chauffe au MÊME instant (un seul repos, pas deux)")

    # 2. Séparément : chacun garde la sienne.
    server = EngineServer(synthetic=True, modes=("ssvep",), instance="smoke-repos-2")
    server._start(["ssvep"], {s.id: v for s, v in server._pending}, now=0.0)
    seul_a = server.active["ssvep"]._rest_s
    values, _ = contract.validate(neuro, {})
    server._start(["neuro"], {"neuro": values}, now=100.0)
    seul_b = server.active["neuro"]._rest_s
    chk(seul_a == ssvep.rest.duration_s and seul_b == neuro.rest.duration_s,
        f"lancés séparément, chacun garde sa durée ({seul_a:g} s et {seul_b:g} s)")
    chk(server.active["ssvep"]._warmup_until != server.active["neuro"]._warmup_until,
        "et leurs repos ne sont pas alignés")

    # 3. Un mode sans repos ne déclenche rien et démarre tout de suite.
    server = EngineServer(synthetic=True, modes=("raw",), instance="smoke-repos-3")
    server._start(["raw"], {s.id: v for s, v in server._pending}, now=0.0)
    chk(server.active["raw"].phase == "running" and server.rest_instruction == "",
        "le brut seul ne déclenche aucun repos")

    print(f"[smoke-repos] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok
```

⚠️ Ces trois `EngineServer` ouvrent des `StreamOutlet` sans jamais tourner. C'est sans danger
(aucune session BrainFlow n'est ouverte : `self.acq` n'est démarré que par `run`), mais les
instances doivent être **distinctes** pour ne pas se confondre entre elles sur le réseau — d'où
les `instance=` différents.

- [ ] **Step 3 : écrire le test de frontière**

```python
def _smoke_frontiere():
    """`core` n'importe ni `research`, ni `console`, ni pygame.

    La règle est vérifiable, c'est tout son intérêt : un module est dans `core` si et seulement
    si `server.py` en a besoin pour tourner, et le moteur doit tourner sur une machine sans
    écran. Le jour où un import de `research` devient nécessaire, ce n'est pas ce test qu'il
    faut assouplir — c'est le module visé qui doit DÉMÉNAGER dans `core`.
    """
    import re

    racine = os.path.dirname(os.path.abspath(__file__))
    interdits = re.compile(r"^\s*(?:from|import)\s+(research|console|pygame)\b", re.MULTILINE)
    fautes = []
    for dossier, _sous, fichiers in os.walk(racine):
        if "__pycache__" in dossier:
            continue
        for nom in fichiers:
            if not nom.endswith(".py"):
                continue
            chemin = os.path.join(dossier, nom)
            with open(chemin, encoding="utf-8") as f:
                for m in interdits.finditer(f.read()):
                    rel = os.path.relpath(chemin, racine)
                    fautes.append(f"core/{rel} importe {m.group(1)}")

    for faute in fautes:
        print(f"[smoke-frontiere] ÉCHEC : {faute}")
    print(f"[smoke-frontiere] {len(fautes)} violation(s) de frontière")
    print(f"[smoke-frontiere] VERDICT : {'OK' if not fautes else 'PROBLÈME'}")
    return not fautes
```

- [ ] **Step 4 : brancher le tout sur `_smoke()`**

Remplacer la dernière ligne de `_smoke()` :

```python
    # avant : return ok and _smoke_ssvep() and _smoke_neuro()
    # Le contrat et le registre d'abord : un défaut là-dedans explique tous les suivants, et
    # c'est instantané. `and` court-circuite, donc l'ordre est aussi celui du diagnostic.
    integre, defauts = registry.check()
    for d in defauts:
        print(f"[smoke-registry] ÉCHEC : {d}")
    print(f"[smoke-registry] {len(registry.MODES)} modes, "
          f"dont {len(registry.runnable())} dans le moteur — "
          f"{'OK' if integre else 'PROBLÈME'}")
    return (ok and integre and _smoke_frontiere() and _smoke_repos_partage()
            and _smoke_ssvep() and _smoke_neuro() and _smoke_cumul())
```

- [ ] **Step 5 : lancer**

Run: `python src/core/server.py --smoke`
Expected, dans cet ordre : `[smoke] VERDICT : OK` · `[smoke-registry] 7 modes, dont 3 dans le
moteur — OK` · `[smoke-frontiere] 0 violation(s)` · `[smoke-repos] VERDICT : OK` ·
`[smoke-ssvep] VERDICT : OK` · `[smoke-neuro] VERDICT : OK` · `[smoke-cumul] VERDICT : OK`

⚠️ Ce smoke dure maintenant ~1 min. C'est le prix de six vérifications de bout en bout sur LSL ;
ne pas le raccourcir en sautant le cumul, qui est la propriété neuve.

- [ ] **Step 6 : vérifier que la frontière détecte vraiment quelque chose**

Un test qui ne peut pas échouer ne teste rien. Ajouter temporairement `import pygame` en tête de
`src/core/modes/raw.py`, relancer, **constater l'échec**, puis retirer la ligne.

Run: `python src/core/server.py --smoke`
Expected: `[smoke-frontiere] ÉCHEC : core/modes/raw.py importe pygame`

- [ ] **Step 7 : commit**

```bash
git add src/core/server.py
git commit -m "Test the two things the refactor made possible: cumulation and a shared rest"
```

---

## Tâche 9 : supprimer le tableau de bord web

Maintenir deux interfaces sur la même API doublerait le travail et les tests pour un usage écarté.
**Le travail moteur du 2026-07-27 reste intégralement** — la validation déclarée, le flux
`decoded_neuro`, le correctif NaN→null. Seul le rendu HTML part.

Cette tâche vient **après** que le moteur tourne, et **avant** la console : entre les deux, le
projet n'a aucune interface. C'est voulu — supprimer plus tôt aurait laissé le moteur sans aucun
moyen d'être piloté à la main pendant six tâches.

**Files:**
- Delete: `src/core/dashboard.py`, `src/core/dashboard.html`
- Modify: `src/core/__init__.py`

**Interfaces:**
- Consumes: rien.
- Produces: rien. `fastapi` et `uvicorn` ne sont plus importés nulle part.

- [ ] **Step 1 : vérifier que personne ne s'en sert**

Run: `grep -rn "dashboard" --include=*.py --include=*.md --include=*.txt . | grep -v "^./docs/superpowers"`
Expected: seulement `src/core/__init__.py`, `docs/SPEC.md`, `README.md` et `CLAUDE.md` — c'est-à-dire
de la documentation, traitée à la tâche 16. Aucun **import** Python.

- [ ] **Step 2 : supprimer**

```bash
git rm src/core/dashboard.py src/core/dashboard.html
```

- [ ] **Step 3 : corriger le graphe de dépendances**

Dans `src/core/__init__.py`, remplacer la ligne du graphe et les deux entrées concernées :

```python
    config  <-  acquisition, cca_decoder, neuro_monitor, lsl_io  <-  modes/  <-  server
```

et remplacer la ligne `- dashboard.py …` par :

```python
- `modes/`         un mode = un contrat (`ModeSpec`) + son état vivant (`ModeRuntime`)
```

Puis ajouter, après le paragraphe sur `research` :

```python
**Ni `console` non plus.** L'interface (`src/console/`, PySide6) est un CLIENT du moteur : elle
crée un `EngineServer`, lit son `snapshot()` et lui soumet des commandes. Le moteur, lui, ne sait
pas qu'elle existe — c'est ce qui lui permet de tourner sur une machine sans écran, et ce qui
rendrait un futur changement d'interface peu coûteux.
```

- [ ] **Step 4 : vérifier**

Run: `python src/core/server.py --smoke` puis `python src/research/app.py --smoke`
Expected: les deux `VERDICT : OK`

- [ ] **Step 5 : commit**

```bash
git add -A src/core
git commit -m "Drop the web dashboard: one interface on this API, not two"
```

---

## Tâche 10 : « brancher un client », généré depuis le contrat

Le troisième bloc de la page de mode. C'est de la **logique**, donc elle vit dans le moteur et se
teste sans écran : la console ne fera qu'afficher le texte.

Le contrat connaît déjà tout ce qu'il faut — le nom du flux, les voies, ce que le mode produit.
C'est le test que l'abstraction sert vraiment à quelque chose.

**Files:**
- Modify: `src/core/modes/contract.py`

**Interfaces:**
- Consumes: `ModeSpec` (tâche 1) · `lsl_io.stream_name`.
- Produces: `contract.client_snippet(spec, params=None) -> str`

- [ ] **Step 1 : écrire le test qui échoue**

Ajouter dans `_selftest()` de `contract.py`, avant l'impression du verdict :

```python
    # « Brancher un client » : le texte doit être du Python VALIDE, et porter les vrais noms.
    from core.modes import ssvep as _ssvep

    extrait = client_snippet(_ssvep.SPEC, {"freqs": (15.0, 20.0, 8.57)})
    chk("EEG_API_Unicorn_decoded_ssvep" in extrait, "l'extrait nomme le vrai flux")
    chk("score_15Hz" in extrait and "score_8.57Hz" in extrait,
        "et les voies telles qu'elles seront publiées")
    chk("open_stream" in extrait,
        "et il appelle open_stream — sans ça un client perd tout ce qui précède son 1er pull")
    try:
        compile(extrait, "<extrait>", "exec")
        chk(True, "l'extrait compile : c'est du Python qu'on peut vraiment coller")
    except SyntaxError as e:
        chk(False, f"l'extrait ne compile pas : {e}")

    chk(client_snippet(ModeSpec(id="x", label="X", family="actif", summary="", status="prevu",
                                unavailable="pas encore")) == "",
        "un mode sans flux ne propose aucun extrait")
```

- [ ] **Step 2 : lancer, constater l'échec**

Run: `python src/core/modes/contract.py`
Expected: `NameError: name 'client_snippet' is not defined`

- [ ] **Step 3 : écrire la fonction**

À la fin de la partie code de `contract.py` :

```python
def client_snippet(spec, params=None):
    """Un extrait Python prêt à coller pour consommer le flux de ce mode. "" s'il n'en a pas.

    Généré depuis le contrat, jamais écrit à la main dans l'interface : les voies d'un flux
    SSVEP dépendent des fréquences réglées, et un exemple qui vieillit mal est pire que pas
    d'exemple — l'étudiant croit avoir copié le bon code.

    `open_stream()` est dans l'extrait pour une raison : un StreamInlet n'ouvre sa connexion
    qu'au premier `pull_*`, et LSL ne rejoue RIEN de ce qui a été publié avant. Sans cette
    ligne on perd la première seconde de signal. C'est le piège classique de LSL, à répéter
    dans tout ce qu'on met sous les yeux d'un étudiant.
    """
    if not spec.stream:
        return ""
    voies = spec.channels_for(spec.defaults() if params is None else params)
    return f'''"""{spec.label} — {spec.summary}

Voies publiées : {", ".join(voies)}
"""
from pylsl import StreamInlet, resolve_byprop

flux = resolve_byprop("name", "{_stream_name(spec.stream)}", timeout=10)
if not flux:
    raise SystemExit("flux introuvable — le moteur tourne-t-il, et ce mode est-il demarre ?")

inlet = StreamInlet(flux[0])
inlet.open_stream()   # AVANT le premier pull : LSL ne rejoue rien de ce qui precede

while True:
    valeurs, horodatage = inlet.pull_sample()
    print(horodatage, dict(zip({list(voies)!r}, valeurs)))
'''
```

Import à ajouter en tête de `contract.py` :

```python
from core.lsl_io import stream_name as _stream_name  # noqa: E402
```

⚠️ **Pas d'accent dans le corps de l'extrait généré** : ce texte est destiné à être copié dans un
fichier dont on ne connaît pas l'encodage, et il finit dans un presse-papiers puis dans un éditeur
quelconque. Les docstrings du projet, elles, restent accentuées.

- [ ] **Step 4 : lancer, vérifier que ça passe**

Run: `python src/core/modes/contract.py`
Expected: `[contract] VERDICT : OK`

- [ ] **Step 5 : commit**

```bash
git add src/core/modes/contract.py
git commit -m "Generate the client snippet from the contract, so it cannot go stale"
```

---

## Tâche 11 : la console — squelette, bandeau permanent, `--smoke`

Le premier code Qt du projet. Cette tâche livre une fenêtre qui **tourne au-dessus d'un vrai
moteur** et n'affiche encore que le bandeau : liaison casque, σ par voie, alarme de référence
décrochée. Le bandeau vient en premier parce que c'est la seule chose qui ne doit jamais
disparaître de l'écran, quel qu'il soit.

**Règle de conception, à tenir partout à partir d'ici** : le fil Qt ne touche **jamais** la session
BrainFlow. Toute action passe par `engine.submit()`. Et aucune logique dans l'interface que le
moteur ne possède pas déjà : pas de validation côté console, pas de catalogue en dur, pas de règle
métier dans le code d'affichage.

**Files:**
- Create: `src/console/__init__.py`, `src/console/app.py`, `src/console/banner.py`

**Interfaces:**
- Consumes: `EngineServer` (tâche 7) — `snapshot()`, `submit()`, `run()`.
- Produces:
  - `banner.Banner(QWidget)` avec `update_from(state: dict)`
  - `app.Console(QMainWindow)` avec `engine`, `refresh()`, `show_grid()`, `show_mode(mode_id)`
  - `app.fake_state()` — un `snapshot()` fabriqué depuis le VRAI registre, pour le smoke
  - `python src/console/app.py --smoke` → code de retour 0

- [ ] **Step 1 : écrire le bandeau**

`src/console/banner.py` :

```python
"""Le bandeau permanent : liaison casque, σ par voie, référence décrochée.

Il ne disparaît sur aucun écran, et c'est délibéré. Une référence décrochée rend une séance
entière inexploitable **sans autre symptôme** : les 8 voies mesurent alors la même référence
flottante avec des amplitudes parfaitement plausibles, et un écran de contrôle affiche 8 barres
rassurantes sur un signal vide. Ça a coûté 3,4 minutes d'enregistrement dans le vide le
2026-07-20, sans le moindre avertissement.
"""

import os
import sys

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import SIGNAL_DEAD_SIGMA, SIGNAL_SAT_SIGMA  # noqa: E402


class Banner(QWidget):
    """Une ligne, trois informations, jamais masquée."""

    def __init__(self):
        super().__init__()
        self.liaison = QLabel("moteur non démarré")
        self.sigmas = QLabel("")
        self.alarme = QLabel("")
        self.alarme.setStyleSheet("color: #e2603f; font-weight: bold;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        for widget in (self.liaison, self.sigmas, self.alarme):
            layout.addWidget(widget)
        layout.addStretch(1)

    def update_from(self, state):
        board = state.get("board", "?")
        casque = "board de test" if board == "synthetic" else "Unicorn"
        actifs = len(state.get("modes") or ())
        self.liaison.setText(f"{casque} · {state.get('fs_hz', 0):.0f} Hz · "
                             f"{actifs} mode{'s' if actifs > 1 else ''} actif"
                             f"{'s' if actifs > 1 else ''}")

        quality = state.get("quality")
        if not quality:
            self.sigmas.setText("σ : en attente du tampon…")
            self.alarme.setText("")
            return

        valeurs = [v for v in quality["sigmas"] if v is not None]
        mortes = sum(1 for v in valeurs if v < SIGNAL_DEAD_SIGMA)
        saturees = sum(1 for v in valeurs if v > SIGNAL_SAT_SIGMA)
        detail = f"σ {min(valeurs):.1f}–{max(valeurs):.1f} µV sur {len(valeurs)} voies" \
            if valeurs else "σ indisponible"
        if mortes:
            detail += f" · {mortes} morte{'s' if mortes > 1 else ''}"
        if saturees:
            detail += f" · {saturees} saturée{'s' if saturees > 1 else ''}"
        self.sigmas.setText(detail)

        if quality.get("reference_lost"):
            self.alarme.setText(
                f"⚠ RÉFÉRENCE DÉCROCHÉE (corrélation inter-voies "
                f"{quality.get('common_mode')}) — remets les MASTOÏDES : "
                f"tout ce qui suit est inexploitable")
        else:
            self.alarme.setText("")
```

- [ ] **Step 2 : écrire le squelette et son smoke**

`src/console/__init__.py` :

```python
"""`console` — la console d'expérimentation (PySide6). Un CLIENT du moteur, pas le moteur.

Elle crée un `EngineServer`, lance sa boucle dans un fil, et sonde `snapshot()` par un `QTimer`.
Aucun HTTP, aucun navigateur.

**Deux règles, et elles ne sont pas négociables :**

1. *Le fil Qt ne touche jamais la session BrainFlow.* Toute action passe par `engine.submit()`,
   qui met la commande en file pour que la boucle du moteur l'applique elle-même. C'est ce qui
   protège l'acquisition.
2. *Aucune logique ici que le moteur ne possède pas déjà.* Pas de validation seulement côté
   console, pas de catalogue de modes en dur, pas de règle métier dans le code d'affichage. La
   console rend et envoie des commandes. C'est ce qui garde la majorité du travail testable sans
   écran, et ce qui rendrait un futur changement d'interface peu coûteux.

`console` importe `core`. `core` ne sait pas que `console` existe.
"""
```

`src/console/app.py` :

```python
"""La console d'expérimentation : régler, observer, publier — mode par mode.

Lancer :
    python src/console/app.py --synthetic          # sans casque (board de test BrainFlow)
    python src/console/app.py                      # vrai Unicorn, brut seul
    python src/console/app.py --mode ssvep         # + décodage SSVEP
    python src/console/app.py --mode ssvep,neuro   # les deux en même temps
    python src/console/app.py --smoke              # test headless (CI), puis quitte

⚠️ Ne jamais la lancer en même temps que `src/core/server.py` ni que `src/research/app.py` : le
casque n'accepte qu'une connexion, et les noms de flux sont un contrat public — deux moteurs
publient sous le même nom.
"""

import argparse
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse_args(argv):
    p = argparse.ArgumentParser(description="EEG_API_Unicorn — console d'expérimentation.")
    p.add_argument("--synthetic", action="store_true", help="board de test BrainFlow (sans casque)")
    p.add_argument("--serial", default=None, help="numéro de série Unicorn")
    p.add_argument("--mode", default=None, help="modes à démarrer, séparés par des virgules")
    p.add_argument("--no-raw", action="store_true", help="ne pas diffuser le signal brut")
    p.add_argument("--id", dest="instance", default=None, help="identité de cette instance")
    p.add_argument("--baseline", type=float, default=None,
                   help="raccourcir le repos — pour REGARDER l'interface sans attendre. Jamais "
                        "pour une vraie séance : le plancher serait mesuré sur trop peu de "
                        "fenêtres et fausserait toute la suite")
    p.add_argument("--warmup", type=float, default=None,
                   help="raccourcir la stabilisation (même réserve que --baseline)")
    p.add_argument("--smoke", action="store_true", help="test headless, puis quitte")
    p.add_argument("--verbose", action="store_true", help="logs BrainFlow détaillés")
    return p.parse_args(argv)


# QT_QPA_PLATFORM doit être posé AVANT le premier import de PySide6 : Qt choisit son backend
# d'affichage à l'import, pas à la création de la QApplication. Posé après, il n'a aucun effet
# et le test headless échoue sur une machine sans écran (la CI, plus tard).
_ARGS = _parse_args(sys.argv[1:])
if _ARGS.smoke:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import (QApplication, QMainWindow, QStackedWidget,  # noqa: E402
                               QVBoxLayout, QWidget)

from console.banner import Banner  # noqa: E402
from core.config import use_utf8_console  # noqa: E402
from core.modes import registry  # noqa: E402
from core.server import EngineServer  # noqa: E402

REFRESH_MS = 100    # ~10 Hz : le moteur décide à 5 Hz, sonder plus vite ne montrerait rien de plus


class Console(QMainWindow):
    """La fenêtre. Elle ne fait que deux choses : lire un état, envoyer des commandes."""

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("EEG_API_Unicorn — console d'expérimentation")
        self.resize(1100, 720)

        self.banner = Banner()
        self.stack = QStackedWidget()

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.banner)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_MS)

    def refresh(self):
        """Sonde le moteur et redistribue l'état. Le SEUL endroit qui appelle `snapshot()`."""
        self.apply_state(self.engine.snapshot())

    def apply_state(self, state):
        self.banner.update_from(state)


def fake_state():
    """Un `snapshot()` fabriqué, pour monter l'interface sans casque ni moteur.

    Construit depuis le VRAI registre : si un `ModeSpec` change, ce qu'on teste change avec lui.
    Un état factice écrit à la main deviendrait faux en silence — exactement le défaut qu'on
    reproche à un catalogue de modes recopié dans l'interface.
    """
    return {
        "running": True, "board": "synthetic", "instance": "faux", "fs_hz": 250.0,
        "channels": ["Fz", "C3", "Cz", "C4", "Pz", "PO7", "Oz", "PO8"],
        "mode": "ssvep", "modes": ["raw", "ssvep"], "phase": "decoding",
        "samples_published": 12345,
        "streams": ["EEG_API_Unicorn_raw", "EEG_API_Unicorn_quality",
                    "EEG_API_Unicorn_status", "EEG_API_Unicorn_decoded_ssvep"],
        "quality": {"sigmas": [7.2, 8.1, 6.9, 9.4, 5.5, 11.2, 6.1, 7.8],
                    "verdicts": ["ok"] * 8, "common_mode": 0.38, "reference_lost": False},
        "rest_instruction": "",
        "modes_state": {
            "raw": {"id": "raw", "label": "Brut", "family": "brut", "phase": "running",
                    "published": True, "params": {}, "instruction": "", "stream": "raw",
                    "channels": ["Fz", "C3", "Cz", "C4", "Pz", "PO7", "Oz", "PO8"],
                    "rest_report": None, "output": None},
            "ssvep": {"id": "ssvep", "label": "SSVEP", "family": "actif", "phase": "running",
                      "published": True, "params": {"freqs": [15.0, 20.0, 8.57]},
                      "instruction": "", "stream": "decoded_ssvep",
                      "channels": ["target_index", "freq_hz", "confidence",
                                   "score_15Hz", "score_20Hz", "score_8.57Hz"],
                      "rest_report": {"kind": "ssvep", "windows": 40, "targets": []},
                      "output": {"target_index": 0, "freq_hz": 15.0,
                                 "scores": [3.1, 0.4, 0.9], "artifact": False,
                                 "threshold": 2.5}},
        },
        "catalog": registry.catalog(),
    }


def _smoke():
    """Monte l'interface sans écran, depuis un état factice. Même philosophie que app.py --smoke.

    Ce qu'on vérifie ici est ce qui casse le plus souvent dans une interface : qu'elle se monte,
    qu'elle encaisse un état où tout est absent (moteur pas encore démarré), et qu'elle survit à
    une alarme. Le contenu métier, lui, est testé côté moteur — il n'y en a pas ici.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    app = QApplication.instance() or QApplication([])
    console = Console(engine=None)
    console.timer.stop()          # pas de moteur : on pilote l'état à la main
    console.show()

    state = fake_state()
    console.apply_state(state)
    chk("Unicorn" not in console.banner.liaison.text(),
        f"le bandeau dit que c'est un board de test — « {console.banner.liaison.text()} »")
    chk("σ" in console.banner.sigmas.text(), f"et les σ — « {console.banner.sigmas.text()} »")
    chk(console.banner.alarme.text() == "", "aucune alarme sur un montage sain")

    # Référence décrochée : le défaut qui rend une séance inexploitable sans autre symptôme.
    state["quality"] = {**state["quality"], "reference_lost": True, "common_mode": 1.0}
    console.apply_state(state)
    chk("RÉFÉRENCE DÉCROCHÉE" in console.banner.alarme.text(),
        "l'alarme de référence s'affiche, en clair")

    # Moteur pas encore démarré : rien ne doit lever.
    console.apply_state({"running": False, "board": "unicorn", "fs_hz": 250.0,
                         "modes": [], "quality": None, "catalog": []})
    chk("attente" in console.banner.sigmas.text(),
        f"un état vide est encaissé — « {console.banner.sigmas.text()} »")

    app.processEvents()
    print(f"[console-smoke] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def run(args):
    modes = [m.strip() for m in (args.mode or "").split(",") if m.strip()]
    if not args.no_raw:
        modes.insert(0, "raw")
    engine = EngineServer(serial=args.serial, synthetic=args.synthetic, verbose=args.verbose,
                          modes=modes, instance=args.instance)

    # Le moteur tourne dans SON fil et possède seul la session BrainFlow. Le fil Qt ne fait que
    # lire `snapshot()` et poser des commandes en file.
    thread = threading.Thread(
        target=engine.run,
        kwargs={"baseline_s": args.baseline, "warmup_s": args.warmup}, daemon=True)
    thread.start()

    app = QApplication([])
    console = Console(engine)
    console.show()
    try:
        app.exec()
    finally:
        # Ctrl+C ou fermeture de la fenêtre doivent fermer PROPREMENT la session BrainFlow :
        # une session laissée ouverte empêche la suivante de s'ouvrir (BOARD_NOT_READY).
        engine.stop()
        thread.join(timeout=5.0)


if __name__ == "__main__":
    use_utf8_console()
    sys.exit(0 if _smoke() else 1) if _ARGS.smoke else run(_ARGS)
```

- [ ] **Step 3 : lancer le smoke**

Run: `python src/console/app.py --smoke`
Expected: quatre lignes `OK`, puis `[console-smoke] VERDICT : OK`, code de retour 0.

- [ ] **Step 4 : regarder la fenêtre pour de vrai**

Run: `python src/console/app.py --synthetic --baseline 4 --warmup 1`
Expected: une fenêtre s'ouvre, le bandeau affiche « board de test · 250 Hz · 1 mode actif » puis
des σ au bout de ~3 s. Fermer la fenêtre doit rendre la main sans laisser de processus.

- [ ] **Step 5 : commit**

```bash
git add src/console/
git commit -m "Open the console on the one thing that must never leave the screen"
```

---

## Tâche 12 : la grille-tableau de bord

L'écran d'accueil. Une tuile par mode du registre — **y compris les quatre que le moteur ne sait
pas faire**. C'est le défaut que l'utilisateur a pointé en premier sur l'ancien tableau de bord :
il ne montrait que ce qui tournait.

Quatre informations par tuile, pour éviter d'avoir à cliquer : **l'état réel**, un **aperçu vivant**
de ce que le mode produit, **s'il est publié**, et pour les non publiés **pourquoi**.

**Files:**
- Create: `src/console/grid.py`
- Modify: `src/console/app.py`

**Interfaces:**
- Consumes: `state["catalog"]` · `state["modes_state"]` (tâche 7) · `engine.submit` (tâche 7).
- Produces:
  - `grid.MiniBars(QWidget)` avec `set_values(values, span)` — l'aperçu, dessiné au `QPainter`
  - `grid.ModeTile(QFrame)` avec `update_from(spec, mode_state)`, signaux `ouvrir(str)` et
    `publier(str, bool)`
  - `grid.ModeGrid(QWidget)` avec `update_from(state)`, mêmes signaux relayés

- [ ] **Step 1 : écrire la grille**

`src/console/grid.py` :

```python
"""La grille : une tuile par mode, l'état du produit d'un seul coup d'œil.

Elle a cessé d'être un menu. Une tuile porte les quatre choses qu'on veut savoir sans cliquer :
l'état réel, un aperçu vivant de ce que le mode produit, s'il est publié, et pour les non publiés
POURQUOI (« demande des marqueurs », « verrouillé à la frame »).

Les modes que le moteur ne sait pas faire sont affichés, grisés, avec leur raison. Sans eux, un
étudiant croirait que le produit fait trois choses et ne saurait pas qu'un décodeur c-VEP validé
l'attend dans `src/research/app.py`.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

COLONNES = 4
VERT, BLEU, GRIS = QColor("#4ac97e"), QColor("#4c8dff"), QColor("#8a8f9c")


class MiniBars(QWidget):
    """Quelques barres, dessinées à la main. L'aperçu vivant d'une tuile.

    Au QPainter plutôt qu'en pyqtgraph : une tuile en montre trois ou quatre, elles sont
    redessinées 10 fois par seconde, et un widget de tracé complet par tuile coûterait cher
    pour trois rectangles.
    """

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(26)
        self._values, self._span = [], 1.0

    def set_values(self, values, span=1.0):
        self._values = [float(v) for v in (values or [])]
        self._span = max(float(span), 1e-6)
        self.update()

    def paintEvent(self, _event):
        if not self._values:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        largeur = self.width() / max(len(self._values), 1)
        haut = self.height()
        meilleur = max(range(len(self._values)), key=lambda i: self._values[i])
        for i, valeur in enumerate(self._values):
            part = min(abs(valeur) / self._span, 1.0)
            h = max(2.0, part * haut)
            painter.fillRect(int(i * largeur) + 2, int(haut - h),
                             int(largeur) - 4, int(h),
                             BLEU if i == meilleur else GRIS)


class ModeTile(QFrame):
    """Une tuile. Elle ne décide de rien : elle rend un `ModeSpec` et un état."""

    ouvrir = Signal(str)
    publier = Signal(str, bool)

    def __init__(self, spec):
        super().__init__()
        self.spec = spec
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumHeight(130)

        self.titre = QLabel(f"<b>{spec['label']}</b>")
        self.etat = QLabel("")
        self.detail = QLabel(spec["summary"])
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color: #8a8f9c; font-size: 11px;")
        self.apercu = MiniBars()
        self.publie = QCheckBox("publié")
        self.bouton = QPushButton("Ouvrir")
        self.bouton.clicked.connect(lambda: self.ouvrir.emit(self.spec["id"]))
        self.publie.toggled.connect(lambda on: self.publier.emit(self.spec["id"], on))

        haut = QHBoxLayout()
        haut.addWidget(self.titre)
        haut.addStretch(1)
        haut.addWidget(self.etat)
        bas = QHBoxLayout()
        bas.addWidget(self.publie)
        bas.addStretch(1)
        bas.addWidget(self.bouton)

        layout = QVBoxLayout(self)
        layout.addLayout(haut)
        layout.addWidget(self.detail)
        layout.addWidget(self.apercu, 1)
        layout.addLayout(bas)

        if spec["status"] != "moteur":
            # Grisée mais LISIBLE, et surtout : elle dit pourquoi.
            self.setEnabled(False)
            self.detail.setText(spec["unavailable"])
            self.etat.setText({"appli_pygame": "appli pygame", "prevu": "prévu"}[spec["status"]])
            self.publie.hide()
            self.bouton.hide()

    def update_from(self, mode_state):
        """`mode_state` = None quand le mode n'est pas démarré."""
        if self.spec["status"] != "moteur":
            return
        if mode_state is None:
            self.etat.setText("arrêté")
            self.publie.setChecked(False)
            self.publie.setEnabled(False)
            self.apercu.set_values([])
            self.detail.setText(self.spec["summary"])
            return

        libelle = {"warmup": "chauffe", "rest": "repos", "running": "décode"}
        self.etat.setText(libelle.get(mode_state["phase"], mode_state["phase"]))
        self.publie.setEnabled(True)
        self.publie.blockSignals(True)     # sinon régler la case RÉÉMET la commande, en boucle
        self.publie.setChecked(bool(mode_state["published"]))
        self.publie.blockSignals(False)

        if mode_state["instruction"]:
            self.detail.setText(mode_state["instruction"])
        else:
            self.detail.setText(_resume(mode_state) or self.spec["summary"])

        sortie = mode_state.get("output") or {}
        if "scores" in sortie:
            self.apercu.set_values(sortie["scores"], span=max(sortie.get("threshold", 2.5), 1.0))
        elif "z" in sortie:
            self.apercu.set_values(list(sortie["z"].values()), span=3.0)
        else:
            self.apercu.set_values([])


def _resume(mode_state):
    """Une ligne : ce que le mode produit en ce moment. "" si rien de parlant."""
    sortie = mode_state.get("output") or {}
    if "scores" in sortie:
        index = sortie["target_index"]
        if sortie.get("artifact"):
            return "artefact — fenêtre rejetée"
        return "aucune cible" if index < 0 else f"cible {index} · {sortie['freq_hz']:g} Hz"
    if "z" in sortie:
        return "  ".join(f"{k} {v:+.1f}" for k, v in sortie["z"].items())
    params = mode_state.get("params") or {}
    if "freqs" in params:
        return " · ".join(f"{f:g} Hz" for f in params["freqs"])
    return ""


class ModeGrid(QWidget):
    """Toutes les tuiles, construites UNE FOIS depuis le catalogue, mises à jour ensuite."""

    ouvrir = Signal(str)
    publier = Signal(str, bool)

    def __init__(self, catalog):
        super().__init__()
        self.tuiles = {}
        layout = QGridLayout(self)
        layout.setSpacing(10)
        for i, spec in enumerate(catalog):
            tuile = ModeTile(spec)
            tuile.ouvrir.connect(self.ouvrir)
            tuile.publier.connect(self.publier)
            self.tuiles[spec["id"]] = tuile
            layout.addWidget(tuile, i // COLONNES, i % COLONNES)
        layout.setRowStretch(len(catalog) // COLONNES + 1, 1)

    def update_from(self, state):
        etats = state.get("modes_state") or {}
        for mode_id, tuile in self.tuiles.items():
            tuile.update_from(etats.get(mode_id))
```

- [ ] **Step 2 : brancher la grille dans la console**

Dans `src/console/app.py`, `Console.__init__`, après la création du `QStackedWidget` :

```python
        self.grid = ModeGrid(registry.catalog())
        self.grid.ouvrir.connect(self.show_mode)
        self.grid.publier.connect(self._publier)
        self.stack.addWidget(self.grid)
```

et les deux méthodes :

```python
    def _publier(self, mode_id, on):
        """Publier ou non le flux de ce mode. Passe par la file de commandes, comme tout."""
        self._commande("set_published", id=mode_id, on=on)

    def _commande(self, name, **params):
        """Soumet une commande et retient le refus, s'il y en a un, pour l'afficher."""
        if self.engine is None:
            return {"accepted": False, "reason": "aucun moteur (mode test)"}
        ack = self.engine.submit(name, **params)
        if not ack.get("accepted"):
            print(f"[console] refusé : {ack.get('reason')}")
        return ack

    def show_grid(self):
        self.stack.setCurrentWidget(self.grid)

    def show_mode(self, mode_id):
        """À compléter à la tâche 13 : pour l'instant on reste sur la grille."""
        self.show_grid()
```

et dans `apply_state`, après le bandeau :

```python
        self.grid.update_from(state)
```

- [ ] **Step 3 : compléter le smoke**

Ajouter dans `_smoke()`, après les vérifications du bandeau :

```python
    console.apply_state(state)
    chk(len(console.grid.tuiles) == len(registry.MODES),
        f"une tuile par mode du registre ({len(console.grid.tuiles)})")

    # Les modes que le moteur ne sait pas faire sont MONTRÉS, grisés, avec leur raison.
    externes = [t for t in console.grid.tuiles.values() if t.spec["status"] != "moteur"]
    chk(len(externes) == 4, f"{len(externes)} tuiles pour les modes de l'appli pygame")
    chk(all(not t.isEnabled() and t.detail.text() for t in externes),
        "chacune est grisée ET dit pourquoi elle ne démarre pas")

    chk(console.grid.tuiles["ssvep"].etat.text() == "décode",
        f"le SSVEP est annoncé « {console.grid.tuiles['ssvep'].etat.text()} »")
    chk(console.grid.tuiles["neuro"].etat.text() == "arrêté",
        "un mode non démarré est annoncé arrêté, pas absent")
    chk(console.grid.tuiles["ssvep"].publie.isChecked(), "et coché comme publié")

    # Pendant un repos, la tuile porte la CONSIGNE — sans elle, le plancher est mesuré pendant
    # que l'étudiant fixe une cible, et il est faux pour toute la séance.
    en_repos = {**state, "modes_state": {**state["modes_state"], "ssvep": {
        **state["modes_state"]["ssvep"], "phase": "rest",
        "instruction": "Ne fixe AUCUNE cible : on mesure le bruit de fond."}}}
    console.apply_state(en_repos)
    chk("AUCUNE cible" in console.grid.tuiles["ssvep"].detail.text(),
        "pendant le repos, la tuile affiche la consigne")
```

- [ ] **Step 4 : lancer**

Run: `python src/console/app.py --smoke`
Expected: toutes les lignes `OK`, `[console-smoke] VERDICT : OK`

- [ ] **Step 5 : regarder**

Run: `python src/console/app.py --synthetic --mode ssvep --baseline 4 --warmup 1`
Expected: 7 tuiles, le SSVEP qui passe de « chauffe » à « repos » puis « décode » avec un aperçu
qui bouge, 4 tuiles grisées portant leur raison. Décocher « publié » sur le brut doit faire
disparaître `EEG_API_Unicorn_raw` du réseau — le vérifier dans un second terminal avec
`python examples/receiver.py --list`.

- [ ] **Step 6 : commit**

```bash
git add src/console/
git commit -m "Show every mode on the grid, including the ones we cannot run"
```

---

## Tâche 13 : la page de mode — sortie en direct et « brancher un client »

Deux des trois blocs de la page. Le mode devient le cadre : c'est là que les chantiers 2 et 3
viendront se brancher, et le fait qu'ils n'aient rien à changer à la coquille sera le test de la
structure.

Le rendu de la sortie dépend de `family`, jamais d'un `if mode_id == "ssvep"` : un mode **actif** a
des cibles et un seuil, un mode **passif** a des indices qui divergent autour d'un repos. C'est une
différence de nature, pas de présentation — un client ne doit pas les traiter pareil, et
l'interface non plus.

**Files:**
- Create: `src/console/live_views.py`, `src/console/mode_page.py`
- Modify: `src/console/app.py`

**Interfaces:**
- Consumes: `state["modes_state"][id]` (tâche 7) · `contract.client_snippet` (tâche 10).
- Produces:
  - `live_views.ActiveView(QWidget)` / `live_views.PassiveView(QWidget)`, toutes deux avec
    `update_from(mode_state)`
  - `live_views.build(family) -> QWidget` — choisit le rendu depuis `family`
  - `mode_page.ModePage(QWidget)` avec `update_from(state)`, signal `retour()`

- [ ] **Step 1 : écrire les deux rendus**

`src/console/live_views.py` :

```python
"""Ce qu'un mode produit, rendu selon sa FAMILLE — pas selon son identifiant.

Un mode **actif** propose des cibles et un seuil : l'utilisateur choisit, il y a une bonne
réponse. Un mode **passif** rend des indices qui divergent autour d'un repos : il n'y a rien à
choisir, et aucune bonne réponse. Les afficher pareil laisserait croire qu'un z d'engagement est
une sélection, ce qui est exactement le contresens que le contrat des flux cherche à éviter.
"""

from PySide6.QtWidgets import (QFormLayout, QLabel, QProgressBar, QVBoxLayout, QWidget)


class ActiveView(QWidget):
    """Une barre par cible, plus le seuil de décision, plus la cible retenue.

    Le seuil est affiché À CÔTÉ des scores, et pas seulement la décision : c'est ce qui permet
    de dire si une non-détection vient d'un signal absent ou d'un seuil trop haut. Sans ça, une
    séance muette n'a qu'une explication apparente — « l'utilisateur fixe mal ».
    """

    def __init__(self):
        super().__init__()
        self.verdict = QLabel("en attente")
        self.verdict.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.seuil = QLabel("")
        self.seuil.setStyleSheet("color: #8a8f9c;")
        self.barres = QFormLayout()
        layout = QVBoxLayout(self)
        layout.addWidget(self.verdict)
        layout.addWidget(self.seuil)
        layout.addLayout(self.barres)
        layout.addStretch(1)
        self._barres = []

    def _assure(self, n, etiquettes):
        while len(self._barres) < n:
            barre = QProgressBar()
            barre.setRange(0, 100)
            barre.setTextVisible(False)
            self._barres.append((QLabel(""), barre))
            self.barres.addRow(self._barres[-1][0], barre)
        for i, (etiquette, _b) in enumerate(self._barres):
            etiquette.setText(etiquettes[i] if i < len(etiquettes) else "")

    def update_from(self, mode_state):
        sortie = (mode_state or {}).get("output") or {}
        if not sortie:
            self.verdict.setText(mode_state["instruction"] if mode_state else "en attente")
            return

        freqs = (mode_state.get("params") or {}).get("freqs") or []
        scores = sortie.get("scores") or []
        seuil = float(sortie.get("threshold", 2.5))
        self._assure(len(scores), [f"{f:g} Hz" for f in freqs])
        self.seuil.setText(f"échelle z · seuil {seuil:g} — un score au-dessus déclenche")

        # L'échelle du remplissage va jusqu'à 2× le seuil : une barre pleine à ras le seuil
        # laisserait croire qu'on est au maximum alors qu'on vient à peine de déclencher.
        for i, (_e, barre) in enumerate(self._barres):
            valeur = scores[i] if i < len(scores) else 0.0
            barre.setValue(int(max(0.0, min(valeur / (2 * seuil), 1.0)) * 100))

        index = sortie.get("target_index", -1)
        if sortie.get("artifact"):
            self.verdict.setText("ARTEFACT — fenêtre rejetée (mouvement ou clignement)")
        elif index < 0:
            self.verdict.setText(f"aucune cible (rien au-dessus de z={seuil:g})")
        else:
            self.verdict.setText(f"CIBLE {index} · {sortie.get('freq_hz', 0):g} Hz")


class PassiveView(QWidget):
    """Un indice par ligne, en ÉCART au repos. Aucune sélection, aucune bonne réponse.

    ⚠️ L'échelle est un z contre le repos du jour de CET utilisateur. `+1` veut dire « au-dessus
    de mon propre repos », pas « chargé ». Les trois indices dérivent du même calcul spectral et
    restent corrélés. C'est écrit sous les barres, pas dans une documentation que personne
    n'ouvrira : un affichage qui présenterait ça comme une mesure de fatigue mentirait.
    """

    SPAN = 3.0     # au-delà de ±3 z, la barre est pleine

    def __init__(self):
        super().__init__()
        self.etat = QLabel("en attente")
        self.barres = QFormLayout()
        self.avertissement = QLabel(
            "z contre TON repos du jour, mesuré au démarrage du mode. Ni comparable entre "
            "personnes, ni entre séances, ni absolu. À lire en TENDANCE.")
        self.avertissement.setWordWrap(True)
        self.avertissement.setStyleSheet("color: #8a8f9c; font-size: 11px;")
        layout = QVBoxLayout(self)
        layout.addWidget(self.etat)
        layout.addLayout(self.barres)
        layout.addWidget(self.avertissement)
        layout.addStretch(1)
        self._barres = {}

    def update_from(self, mode_state):
        sortie = (mode_state or {}).get("output") or {}
        z = sortie.get("z") or {}
        if not z:
            self.etat.setText(mode_state["instruction"] if mode_state else "en attente")
            return

        for cle, valeur in z.items():
            if cle not in self._barres:
                barre = QProgressBar()
                barre.setRange(-100, 100)
                barre.setFormat("%v")
                self._barres[cle] = barre
                self.barres.addRow(QLabel(cle), barre)
            part = max(-1.0, min(float(valeur) / self.SPAN, 1.0))
            self._barres[cle].setValue(int(part * 100))

        artefacts = sortie.get("artifacts", 0)
        if sortie.get("artifact"):
            self.etat.setText(f"fenêtre rejetée ({sortie.get('reason', 'artefact')}) — "
                              f"les derniers z valides sont maintenus")
        else:
            self.etat.setText(f"{artefacts} fenêtre(s) rejetée(s) depuis le début du mode")


def build(family):
    """Le rendu qui convient à cette famille. Le brut a le sien, ajouté à la tâche 15."""
    return PassiveView() if family == "passif" else ActiveView()
```

- [ ] **Step 2 : écrire la page**

`src/console/mode_page.py` :

```python
"""La page d'un mode : sortie en direct · réglages · brancher un client.

Les trois blocs sont générés depuis le `ModeSpec`. Rien ici ne sait qu'un SSVEP a des fréquences
ou qu'un neuro a un lissage : c'est le contrat qui le dit. C'est ce qui permettra aux chantiers 2
et 3 d'enrichir les blocs sans toucher à la coquille.
"""

import os
import sys

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from console import live_views  # noqa: E402
from core.modes import registry  # noqa: E402
from core.modes.contract import client_snippet  # noqa: E402


class ModePage(QWidget):
    """Une page par mode, construite une fois, mise à jour à chaque rafraîchissement."""

    retour = Signal()

    def __init__(self, spec, console):
        super().__init__()
        self.spec = spec
        self.console = console
        self.mode_id = spec["id"]

        entete = QHBoxLayout()
        bouton = QPushButton("← Modes")
        bouton.clicked.connect(self.retour)
        entete.addWidget(bouton)
        entete.addWidget(QLabel(f"<b>{spec['label']}</b> — {spec['summary']}"))
        entete.addStretch(1)
        self.etat = QLabel("")
        entete.addWidget(self.etat)

        self.vue = live_views.build(spec["family"])
        bloc_sortie = QGroupBox("Sortie en direct")
        QVBoxLayout(bloc_sortie).addWidget(self.vue)

        self.reglages = QGroupBox("Réglages")
        QVBoxLayout(self.reglages).addWidget(
            QLabel("aucun réglage pour ce mode"))   # remplacé à la tâche 14

        self.client = QGroupBox("Brancher un client")
        self.extrait = QPlainTextEdit()
        self.extrait.setReadOnly(True)
        self.extrait.setMaximumHeight(220)
        self.flux = QLabel("")
        self.copier = QPushButton("Copier")
        self.copier.clicked.connect(self._copier)
        client_layout = QVBoxLayout(self.client)
        client_layout.addWidget(self.flux)
        client_layout.addWidget(self.extrait)
        client_layout.addWidget(self.copier)

        layout = QVBoxLayout(self)
        layout.addLayout(entete)
        layout.addWidget(bloc_sortie, 1)
        layout.addWidget(self.reglages)
        layout.addWidget(self.client)

        self._remplir_extrait(None)

    def _copier(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.extrait.toPlainText())

    def _remplir_extrait(self, params):
        """L'extrait est regénéré quand les réglages changent : les voies SSVEP en dépendent."""
        spec = registry.get(self.mode_id)
        texte = client_snippet(spec, params)
        self.extrait.setPlainText(texte or "ce mode ne publie aucun flux")
        voies = ", ".join(spec.channels_for(params or spec.defaults()))
        self.flux.setText(f"{self.spec['stream'] or '—'} · voies : {voies}"
                          if self.spec["stream"] else "aucun flux publié")

    def update_from(self, state):
        mode_state = (state.get("modes_state") or {}).get(self.mode_id)
        if mode_state is None:
            self.etat.setText("arrêté")
            self.vue.update_from(None)
            return
        libelle = {"warmup": "chauffe", "rest": "repos", "running": "décode"}
        self.etat.setText(libelle.get(mode_state["phase"], mode_state["phase"])
                          + ("" if mode_state["published"] else " · non publié"))
        self.vue.update_from(mode_state)
        params = mode_state.get("params") or {}
        if params != getattr(self, "_derniers_params", None):
            self._derniers_params = dict(params)
            self._remplir_extrait(params)
```

- [ ] **Step 3 : brancher les pages dans la console**

Dans `Console.__init__`, après la grille :

```python
        self.pages = {}
        for spec in registry.catalog():
            if spec["status"] != "moteur":
                continue          # pas de page pour un mode que le moteur ne sait pas faire
            page = ModePage(spec, self)
            page.retour.connect(self.show_grid)
            self.pages[spec["id"]] = page
            self.stack.addWidget(page)
```

et remplacer `show_mode` :

```python
    def show_mode(self, mode_id):
        page = self.pages.get(mode_id)
        if page is not None:
            self.stack.setCurrentWidget(page)
```

et dans `apply_state`, après la grille :

```python
        page = self.stack.currentWidget()
        if page is not self.grid:
            page.update_from(state)
```

- [ ] **Step 4 : compléter le smoke**

```python
    # Entrer dans une page de mode, en ressortir.
    console.apply_state(state)
    console.show_mode("ssvep")
    page = console.stack.currentWidget()
    chk(page is console.pages["ssvep"], "on entre dans la page du SSVEP")
    page.update_from(state)
    chk("CIBLE 0" in page.vue.verdict.text(),
        f"la sortie en direct montre la cible ({page.vue.verdict.text()})")
    chk("seuil" in page.vue.seuil.text(), "et le seuil, à côté des scores")
    chk("score_15Hz" in page.extrait.toPlainText(),
        "l'extrait client porte les voies réellement publiées")
    chk("decoded_ssvep" in page.flux.text(), f"et le nom du flux ({page.flux.text()})")

    # Un mode PASSIF ne se rend pas comme un mode actif.
    neuro_state = {**state, "modes_state": {**state["modes_state"], "neuro": {
        "id": "neuro", "label": "Neuro", "family": "passif", "phase": "running",
        "published": True, "params": {"smoothing": 0.85, "rebaseline_s": 180.0},
        "instruction": "", "stream": "decoded_neuro",
        "channels": ["charge", "somnolence", "engagement", "artifact"], "rest_report": None,
        "output": {"z": {"charge": 1.2, "somnolence": -0.4, "engagement": 0.3},
                   "raw": {}, "artifact": False, "reason": "", "artifacts": 2}}}}
    console.show_mode("neuro")
    console.apply_state(neuro_state)
    page = console.pages["neuro"]
    chk(isinstance(page.vue, live_views.PassiveView), "le neuro a le rendu PASSIF, pas des cibles")
    chk("TENDANCE" in page.vue.avertissement.text(),
        "et l'avertissement sur l'échelle est sous les yeux, pas dans une doc")

    console.show_grid()
    chk(console.stack.currentWidget() is console.grid, "et on ressort sur la grille")
```

Ajouter `from console import live_views` aux imports de `app.py`.

- [ ] **Step 5 : lancer**

Run: `python src/console/app.py --smoke`
Expected: `[console-smoke] VERDICT : OK`

- [ ] **Step 6 : regarder**

Run: `python src/console/app.py --synthetic --mode ssvep,neuro --baseline 4 --warmup 1`
Expected: entrer dans SSVEP montre trois barres qui bougent et un verdict ; entrer dans Neuro
montre trois indices centrés ; « Copier » met un extrait Python valide dans le presse-papiers.

- [ ] **Step 7 : commit**

```bash
git add src/console/
git commit -m "Make the mode the frame: what it produces, and how to consume it"
```

---

## Tâche 14 : le formulaire de réglages, en lecture-écriture

Le bloc 2, et **la preuve que l'abstraction fonctionne**. La spec l'a délibérément avancé depuis le
chantier 2 : un contrat dont les paramètres ne sont jamais rendus n'est pas validé.

Le formulaire est **généré** depuis `spec.params` — il ne sait pas qu'un SSVEP a des fréquences. Et
il ne valide **rien** : il envoie, et affiche le refus du moteur en clair s'il y en a un.

**Files:**
- Create: `src/console/params_form.py`
- Modify: `src/console/mode_page.py`, `src/console/app.py`

**Interfaces:**
- Consumes: `spec["params"]` sérialisé (tâche 2) · `engine.submit("set_params", …)` (tâche 7).
- Produces: `params_form.ParamsForm(QWidget)` avec `set_values(params)`, `values() -> dict`,
  `show_refus(reason)`, signal `appliquer(dict)`

- [ ] **Step 1 : écrire le formulaire**

`src/console/params_form.py` :

```python
"""Le formulaire d'un mode, GÉNÉRÉ depuis son contrat. Il ne valide rien : le moteur s'en charge.

C'est délibéré, et c'est la règle de conception la plus importante de la console : aucune logique
ici que le moteur ne possède pas déjà. Une validation recopiée côté interface diverge tôt ou tard
de celle du moteur, et le jour où elle diverge, elle laisse passer un réglage qui ne décodera
rien — sans erreur, comme toujours avec ce genre de panne.

Le formulaire envoie donc, et affiche la RAISON du refus telle que le moteur l'a formulée.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)


class ParamsForm(QWidget):
    """Un champ par `Param`, plus son aide, plus un bouton et une ligne de refus."""

    appliquer = Signal(dict)

    def __init__(self, params):
        super().__init__()
        self.params = list(params)
        self.champs = {}

        formulaire = QFormLayout()
        for param in self.params:
            champ = self._champ(param)
            self.champs[param["key"]] = champ
            etiquette = param["label"] + (f" ({param['unit']})" if param["unit"] else "")
            formulaire.addRow(etiquette, champ)
            if param["help"]:
                aide = QLabel(param["help"])
                aide.setWordWrap(True)
                aide.setStyleSheet("color: #8a8f9c; font-size: 11px;")
                formulaire.addRow("", aide)

        self.bouton = QPushButton("Appliquer")
        self.bouton.clicked.connect(lambda: self.appliquer.emit(self.values()))
        self.refus = QLabel("")
        self.refus.setWordWrap(True)
        self.refus.setStyleSheet("color: #e2603f;")

        bas = QHBoxLayout()
        bas.addWidget(self.bouton)
        bas.addStretch(1)

        layout = QVBoxLayout(self)
        if not self.params:
            layout.addWidget(QLabel("aucun réglage pour ce mode"))
        layout.addLayout(formulaire)
        layout.addLayout(bas)
        layout.addWidget(self.refus)

    def _champ(self, param):
        kind = param["kind"]
        if kind == "bool":
            champ = QCheckBox()
            champ.setChecked(bool(param["default"]))
            return champ
        if kind == "choice":
            champ = QComboBox()
            champ.addItems([str(c) for c in param["choices"]])
            return champ
        if kind == "float_list":
            # Une ligne de valeurs séparées par des virgules : c'est la MÊME écriture que
            # `--freqs 15,20,8.57` en ligne de commande, et le nombre d'éléments se règle en
            # ajoutant ou retirant une valeur — c'est ainsi qu'on choisit le nombre de cibles.
            champ = QLineEdit(", ".join(f"{float(v):g}" for v in (param["default"] or ())))
            bornes = param["count"] or [0, 0]
            champ.setPlaceholderText(f"entre {bornes[0]} et {bornes[1]} valeurs, séparées "
                                     f"par des virgules")
            return champ
        champ = QSpinBox() if kind == "int" else QDoubleSpinBox()
        # Des bornes larges par défaut : les vraies bornes sont dans le contrat et c'est le
        # moteur qui refuse. Un widget qui EMPÊCHE de saisir une valeur hors bornes priverait
        # l'étudiant du message qui lui dit pourquoi elle est hors bornes.
        champ.setRange(param["min"] if param["min"] is not None else -1e9,
                       param["max"] if param["max"] is not None else 1e9)
        if kind != "int":
            champ.setDecimals(3)
            champ.setSingleStep(0.05)
        champ.setValue(param["default"] if param["default"] is not None else 0)
        return champ

    def set_values(self, values):
        """Recharge les champs depuis l'état du moteur (après application ou refus)."""
        for param in self.params:
            if param["key"] not in values:
                continue
            champ, valeur = self.champs[param["key"]], values[param["key"]]
            if param["kind"] == "bool":
                champ.setChecked(bool(valeur))
            elif param["kind"] == "choice":
                champ.setCurrentText(str(valeur))
            elif param["kind"] == "float_list":
                champ.setText(", ".join(f"{float(v):g}" for v in valeur))
            else:
                champ.setValue(valeur)

    def values(self):
        """Ce que l'utilisateur a saisi, tel quel. Aucune conversion « intelligente ».

        Une liste illisible part en texte brut : c'est le moteur qui dira « liste de nombres
        attendue », avec les mêmes mots que pour toutes les autres erreurs.
        """
        out = {}
        for param in self.params:
            champ = self.champs[param["key"]]
            if param["kind"] == "bool":
                out[param["key"]] = champ.isChecked()
            elif param["kind"] == "choice":
                out[param["key"]] = champ.currentText()
            elif param["kind"] == "float_list":
                morceaux = [m.strip() for m in champ.text().split(",") if m.strip()]
                try:
                    out[param["key"]] = [float(m) for m in morceaux]
                except ValueError:
                    out[param["key"]] = champ.text()      # tel quel : le moteur refusera
            else:
                out[param["key"]] = champ.value()
        return out

    def show_refus(self, reason):
        self.refus.setText(reason or "")
```

- [ ] **Step 2 : brancher le formulaire dans la page**

Dans `ModePage.__init__`, remplacer le bloc `self.reglages` :

```python
        self.formulaire = ParamsForm(spec["params"])
        self.formulaire.appliquer.connect(self._appliquer)
        self.reglages = QGroupBox("Réglages")
        QVBoxLayout(self.reglages).addWidget(self.formulaire)
```

et ajouter :

```python
    def _appliquer(self, values):
        """Envoie les réglages. Le moteur accepte ou refuse ; on affiche ce qu'il dit.

        ⚠️ Appliquer un réglage RELANCE le repos de ce mode. C'est obligatoire, pas prudent : un
        plancher mesuré sous d'autres réglages est faux, et pour le SSVEP il est mesuré PAR
        FRÉQUENCE. Le flux est recréé au passage — les clients doivent se réabonner.
        """
        ack = self.console.commande("set_params", id=self.mode_id, params=values)
        self.formulaire.show_refus("" if ack.get("accepted") else ack.get("reason", ""))
```

Dans `update_from`, quand les réglages changent, recharger le formulaire depuis l'état du moteur —
c'est ce qui fait qu'un refus laisse voir les valeurs **réellement en vigueur** :

```python
        if params != getattr(self, "_derniers_params", None):
            self._derniers_params = dict(params)
            self._remplir_extrait(params)
            self.formulaire.set_values(params)
```

Renommer `Console._commande` en `Console.commande` (elle est appelée depuis la page).

- [ ] **Step 3 : compléter le smoke, avec un vrai moteur**

Le formulaire n'a d'intérêt que si sa sortie est acceptée par le moteur. On monte donc un
`EngineServer` **sans le faire tourner** : `submit()` valide tout de suite, c'est justement ce
qu'on veut éprouver.

```python
    # Le formulaire contre un VRAI moteur : c'est le seul moyen de prouver que ce qu'il produit
    # est ce que le moteur attend. Le moteur n'est pas démarré — `submit` valide à la
    # soumission, sans avoir besoin de la boucle.
    from core.server import EngineServer

    moteur = EngineServer(synthetic=True, modes=("raw", "ssvep"), instance="console-smoke")
    reelle = Console(moteur)
    reelle.timer.stop()
    page = reelle.pages["ssvep"]
    chk(len(page.formulaire.champs) == 1, "le SSVEP expose un réglage : ses fréquences")
    chk(page.formulaire.champs["freqs"].text().startswith("15"),
        f"pré-rempli avec le défaut du contrat ({page.formulaire.champs['freqs'].text()})")

    # `submit` ne peut valider que sur un mode DÉMARRÉ : on applique la commande à la main,
    # comme la boucle le ferait.
    moteur._start(["raw", "ssvep"], {s.id: v for s, v in moteur._pending}, now=0.0)

    page.formulaire.champs["freqs"].setText("12, 15, 20")
    page._appliquer(page.formulaire.values())
    chk(page.formulaire.refus.text() == "",
        f"un jeu valide est accepté ({page.formulaire.refus.text()})")

    page.formulaire.champs["freqs"].setText("15, 60")
    page._appliquer(page.formulaire.values())
    chk("hors bande passante" in page.formulaire.refus.text(),
        f"et un jeu hors bande est refusé AVEC sa raison — « {page.formulaire.refus.text()[:60]}… »")

    page.formulaire.champs["freqs"].setText("15, 15.2")
    page._appliquer(page.formulaire.values())
    chk("trop proches" in page.formulaire.refus.text(),
        "deux cibles trop proches pour la fenêtre : refusées, avec l'écart minimum indiqué")

    page.formulaire.champs["freqs"].setText("quinze, vingt")
    page._appliquer(page.formulaire.values())
    chk("liste de nombres" in page.formulaire.refus.text(),
        "une saisie illisible est refusée par le MOTEUR, pas par le formulaire")

    # Le mode « brut » n'a aucun réglage : la page doit le dire, pas afficher un cadre vide.
    chk(len(reelle.pages["raw"].formulaire.champs) == 0,
        "le brut n'a aucun réglage, et le formulaire l'assume")
```

- [ ] **Step 4 : lancer**

Run: `python src/console/app.py --smoke`
Expected: `[console-smoke] VERDICT : OK`

- [ ] **Step 5 : le faire pour de vrai**

Run: `python src/console/app.py --synthetic --mode ssvep --baseline 4 --warmup 1`

Dans la page SSVEP, saisir `15, 60` puis Appliquer : le refus s'affiche en rouge sous le bouton,
et les fréquences ne changent pas. Saisir `12, 15, 20` : le repos repart (l'état passe à
« chauffe »), et l'extrait client se met à jour avec `score_12Hz`.

- [ ] **Step 6 : commit**

```bash
git add src/console/
git commit -m "Let students change what only the code could change before"
```

---

## Tâche 15 : le mode « brut » et ses tracés

Le manque n°1 signalé par l'utilisateur sur l'ancien tableau de bord — voir le signal — sans
introduire de concept nouveau : le brut est un mode, sa page montre ce qu'il produit.

C'est aussi le seul endroit qui justifie pyqtgraph plutôt que du `QPainter` : huit voies à 250 Hz
redessinées 10 fois par seconde, c'est exactement ce pour quoi il existe.

**Files:**
- Modify: `src/console/live_views.py`, `src/console/mode_page.py`

**Interfaces:**
- Consumes: `engine.recent_window(seconds)` (tâche 7).
- Produces: `live_views.TracesView(QWidget)` avec `update_from(mode_state)` et
  `set_source(callable)` ; `live_views.build(family)` rend un `TracesView` pour `family == "brut"`.

- [ ] **Step 1 : écrire la vue**

Dans `src/console/live_views.py` :

```python
class TracesView(QWidget):
    """Les 8 voies en direct. La seule vue qui lit le SIGNAL et pas une décision.

    Elle ne touche pas au tampon du moteur : `set_source` lui donne un accesseur
    (`engine.recent_window`) qui rend une COPIE. Le tampon est réécrit par le fil d'acquisition ;
    le lire depuis le fil Qt donnerait, tôt ou tard, une vue à moitié écrite.

    Les voies sont DÉCALÉES verticalement plutôt que superposées : superposées, une seule voie
    qui dérive écrase les sept autres et on ne voit plus rien — or la dérive d'une voie est
    précisément ce qu'on cherche à repérer ici.
    """

    SECONDES = 4.0
    ECART_UV = 100.0     # décalage vertical entre deux voies

    def __init__(self, ch_names):
        super().__init__()
        import pyqtgraph as pg

        self.source = None
        self.ch_names = list(ch_names)
        self.plot = pg.PlotWidget()
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.showGrid(x=True, y=False, alpha=0.2)
        self.plot.setLabel("bottom", "secondes")
        self.plot.getAxis("left").setTicks([[
            (-i * self.ECART_UV, nom) for i, nom in enumerate(self.ch_names)]])
        self.courbes = [self.plot.plot(pen=pg.mkPen(width=1)) for _ in self.ch_names]

        self.echelle = QLabel(f"signal BRUT, non filtré · une graduation = {self.ECART_UV:g} µV "
                              f"· {self.SECONDES:g} dernières secondes")
        self.echelle.setStyleSheet("color: #8a8f9c; font-size: 11px;")
        layout = QVBoxLayout(self)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.echelle)

    def set_source(self, source):
        """`source(seconds) -> (n, 8) ou None`. En pratique : `engine.recent_window`."""
        self.source = source

    def update_from(self, _mode_state):
        if self.source is None:
            return
        bloc = self.source(self.SECONDES)
        if bloc is None or len(bloc) < 2:
            return
        import numpy as np

        t = np.arange(len(bloc)) / max(len(bloc) / self.SECONDES, 1e-9)
        for i, courbe in enumerate(self.courbes):
            if i >= bloc.shape[1]:
                break
            # Centré voie par voie : l'Unicorn sort un offset DC énorme (10⁵ µV, en rampe après
            # l'ouverture de session). Sans ce centrage, les 8 courbes sortiraient de l'écran.
            voie = bloc[:, i] - float(np.median(bloc[:, i]))
            courbe.setData(t, voie - i * self.ECART_UV)
```

Et remplacer `build` :

```python
def build(family, ch_names=()):
    """Le rendu qui convient à cette famille — jamais à un identifiant de mode."""
    if family == "brut":
        return TracesView(ch_names)
    return PassiveView() if family == "passif" else ActiveView()
```

- [ ] **Step 2 : brancher la source dans la page**

Dans `ModePage.__init__`, remplacer la construction de la vue :

```python
        self.vue = live_views.build(spec["family"], spec["channels"])
        if hasattr(self.vue, "set_source") and console.engine is not None:
            # L'accesseur PUBLIC du moteur, qui rend une copie. Jamais `engine.recent`.
            self.vue.set_source(console.engine.recent_window)
```

- [ ] **Step 3 : compléter le smoke**

```python
    # Les tracés, contre un vrai tampon. `recent_window` rend une COPIE : la modifier ne doit
    # rien changer au moteur — c'est ce qui protège l'acquisition du fil Qt.
    import numpy as np

    moteur.recent = np.random.default_rng(0).normal(0.0, 20.0, (1000, 8))
    bloc = moteur.recent_window(2.0)
    chk(bloc is not None and bloc.shape == (500, 8),
        f"recent_window rend 2 s de signal ({None if bloc is None else bloc.shape})")
    bloc[0, 0] = 999999.0
    chk(moteur.recent[-500, 0] != 999999.0,
        "et c'est une COPIE : l'afficheur ne peut pas abîmer le tampon d'acquisition")

    page = reelle.pages["raw"]
    page.update_from({"modes_state": {"raw": {
        "id": "raw", "label": "Brut", "family": "brut", "phase": "running", "published": True,
        "params": {}, "instruction": "", "stream": "raw", "channels": list(moteur_channels),
        "rest_report": None, "output": None}}})
    chk(len(page.vue.courbes) == 8, f"huit courbes, une par voie ({len(page.vue.courbes)})")
    chk(page.vue.courbes[0].xData is not None and len(page.vue.courbes[0].xData) > 100,
        "et elles portent des données après un rafraîchissement")
```

Avec `moteur_channels = ["Fz", "C3", "Cz", "C4", "Pz", "PO7", "Oz", "PO8"]` défini juste avant.

- [ ] **Step 4 : lancer**

Run: `python src/console/app.py --smoke`
Expected: `[console-smoke] VERDICT : OK`

- [ ] **Step 5 : regarder le signal**

Run: `python src/console/app.py --synthetic`
Ouvrir la tuile « Brut ». Expected: huit tracés décalés qui défilent, étiquetés `Fz … PO8`.

Puis, **avec le casque** :

Run: `python src/console/app.py`
Expected: huit tracés d'EEG réel. C'est le moment de vérifier que les σ du bandeau et ce qu'on
voit racontent la même histoire — une voie plate au tracé doit être annoncée « morte ».

- [ ] **Step 6 : commit**

```bash
git add src/console/
git commit -m "Show the signal itself, on the page of the mode that produces it"
```

---

## Tâche 16 : la documentation dit ce que le code fait

Trois documents portent des affirmations que ce chantier vient de rendre fausses. Les corriger
n'est pas de la cosmétique : `docs/SPEC.md` est le document que `CLAUDE.md` dit de lire en premier,
et une décision figée qui a été renversée sans être amendée est un piège pour la prochaine session.

**Files:**
- Modify: `docs/SPEC.md`, `README.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: tout ce qui précède.
- Produces: rien de programmatique.

- [ ] **Step 1 : amender SPEC §12.2 — sans effacer la décision d'origine**

La spec le demande explicitement : « §12.2 doit être amendée, pas réécrite : la décision d'origine
et son renversement doivent rester lisibles côte à côte. »

Changer le titre en :

```markdown
### 12.2 Interface de contrôle : ~~tableau de bord web servi en local~~ → **console PySide6** ⚠️ RENVERSÉE le 2026-07-27
```

Insérer juste après le titre, **avant** le contenu existant :

```markdown
> **Cette décision a été renversée.** Ce qui suit décrit le choix d'origine et pourquoi il avait
> été fait ; le renversement est en fin de section. Les deux restent ici volontairement : la
> décision web était bien argumentée et pourrait redevenir la bonne le jour où le suivi à
> distance comptera plus que le tracé temps réel.
```

Puis, à la fin de la section, ajouter :

```markdown
#### Renversement (2026-07-27) : Python + PySide6

Le tableau de bord web a été implémenté, utilisé, et écarté après usage. Le cadrage du produit a
changé en même temps : d'un **moteur qui diffuse** avec une interface en périphérie, on passe à une
**console d'expérimentation** où la diffusion réseau devient une sortie parmi d'autres, activable
mode par mode. Conception complète :
[docs/superpowers/specs/2026-07-27-console-experimentation-design.md](superpowers/specs/2026-07-27-console-experimentation-design.md).

**Ce qui est perdu, et assumé :**
- **l'installation zéro** — PySide6 ajoute ~100 Mo aux dépendances ;
- **le suivi à distance** — plus d'encadrant observant la qualité du signal depuis un autre poste ;
- **la modifiabilité par un élève** — Qt est moins connu que HTML/CSS/JS, ce qui était l'argument
  numéro un du choix web.

**Ce qui est gagné :** un seul langage ; le tracé EEG temps réel devient facile au lieu d'être un
chantier ; et surtout **les consignes de calibration et le stimulus local peuvent vivre dans la
même application**, ce qui supprime la couture « navigateur pour le MI, fenêtre native pour le
c-VEP » que la section ci-dessus assumait comme inhérente.

`src/core/dashboard.py` et `src/core/dashboard.html` sont **supprimés**. Le travail moteur du
2026-07-27 reste intégralement : la validation déclarée des réglages, le flux `decoded_neuro`, le
correctif NaN→null. Seul le rendu HTML est parti.

#### Commandes exposées (API interne, §12.1) — table à jour

| Commande | Paramètres | Effet |
|---|---|---|
| `start_mode` | `id` ou `ids`, `params?` | démarre un ou plusieurs modes ; ceux lancés **ensemble** partagent une seule phase de repos |
| `stop_mode` | `id` | arrête un mode, son flux disparaît du réseau |
| `set_params` | `id`, `params` | valide contre `spec.params`, applique ; **relance le repos** si le mode en a un |
| `set_published` | `id`, `on` | publie ou non le flux de ce mode ; le décodage continue pour l'affichage |
| `recalibrate` | `id` | refait chauffe + repos de ce mode seul |
| `stop` | — | arrête le moteur |

`set_mode` et `set_freqs` **n'existent plus** : la première est remplacée par
`start_mode`/`stop_mode`, la seconde par `set_params`. Leurs deux conséquences documentées
ci-dessus (flux recréé, plancher refait) valent toujours, et s'appliquent désormais à **tout**
réglage de **tout** mode, pas seulement aux fréquences SSVEP.
```

- [ ] **Step 2 : SPEC §3.1 — le troisième paquet**

Ajouter à la fin de §3.1 :

```markdown
**Depuis le 2026-07-28, il y a un troisième paquet : `src/console/`** (la console PySide6). La
règle ne change pas, elle s'étend : `console` importe `core`, et `core` n'importe **ni `research`,
ni `console`, ni pygame**. Le moteur doit continuer à tourner sur une machine sans écran.
C'est vérifié par un test, pas par la discipline : `python src/core/server.py --smoke` scanne
`src/core/**/*.py` et échoue sur le moindre import interdit.

`src/core/modes/` est arrivé en même temps : un mode y est un **contrat** (`ModeSpec` : ce qu'il
est, ce qui s'y règle, ce qu'il publie) posé à côté de son **runtime**. L'algorithme reste
séparé — `cca_decoder.py` est une CCA, indifférente au produit ; `modes/ssvep.py` est le mode.
```

- [ ] **Step 3 : SPEC §10 et §14 — l'état d'avancement**

Dans §10, remplacer la ligne v2 sur le tableau de bord :

```markdown
**v2 :** `ErrP` (marqueurs) · ~~tableau de bord web (§12.2)~~ **[fait 2026-07-27, puis SUPPRIMÉ 2026-07-28]** remplacé par la **console d'expérimentation** `src/console/` (PySide6) · évolutions parkées F1/F2 (§13).
```

Ajouter en tête de la roadmap §14 une entrée :

```markdown
0. **[fait 2026-07-28]** **Console d'expérimentation** : contrat de mode (`src/core/modes/`),
   moteur multi-modes avec cumul et repos partagé, console PySide6 (grille + page de mode,
   réglages en lecture-écriture, tracés EEG). Tableau de bord web supprimé.
   - **[à faire — chantier 2]** proposition automatique de fréquences (`Param.proposes`) et
     réglages des autres modes.
   - **[à faire — chantier 3]** lancer une calibration et gérer les modèles depuis la console ;
     le MI est le premier candidat à migrer vers le moteur.
```

- [ ] **Step 4 : README — ce qu'un étudiant lance**

Remplacer toute mention de `dashboard.py` par la console, et mettre les commandes à jour :

```markdown
```bash
python src/console/app.py --mode ssvep        # la console : régler, observer, publier
python src/console/app.py --synthetic         # sans casque (board de test BrainFlow)
python src/core/server.py --mode ssvep,neuro  # le moteur seul, sans interface (headless)
python src/core/server.py --no-raw --mode neuro   # décoder sans diffuser le brut
```
```

Et dans la section dépendances : PySide6 + pyqtgraph à la place de fastapi/uvicorn.

- [ ] **Step 5 : CLAUDE.md — les commandes utiles**

Remplacer le bloc de commandes :

```bash
python src/console/app.py --mode ssvep     # LA console : grille des modes, réglages, tracés
python src/core/server.py --mode ssvep     # le moteur seul (headless) : décode et publie sur LSL
python src/core/server.py --mode ssvep,neuro   # deux modes en même temps
python src/research/app.py                 # l'appli pygame : c-VEP, P300, MI, ErrP
python src/research/app.py --synthetic     # sans casque (board de test BrainFlow)
```

et le bloc des tests :

```bash
python src/core/server.py --smoke          # moteur : registre, frontière, repos partagé, cumul, flux
python src/console/app.py --smoke          # console : grille, page de mode, réglages (offscreen)
python src/research/app.py --smoke         # appli : menu + les 6 modes + les calibrations
```

Ajouter à la liste des choses à savoir en arrivant :

```markdown
- **Le code se divise en TROIS paquets** : `src/core/` = le moteur (`server.py` et ce dont il a
  besoin, dont `core/modes/`) ; `src/console/` = la console PySide6 ; `src/research/` = tout le
  reste. `console` et `research` importent `core`, **jamais l'inverse**, et aucun pygame ni Qt dans
  `core` : le moteur tourne sans écran. Vérifié par `server.py --smoke`.
```

- [ ] **Step 6 : vérifier qu'aucune référence morte ne subsiste**

Run: `grep -rn "dashboard\|set_freqs\|set_mode" README.md CLAUDE.md docs/SPEC.md`
Expected: uniquement dans §12.2, dans la partie explicitement marquée comme la décision d'origine
ou comme remplacée.

- [ ] **Step 7 : lancer les trois smokes une dernière fois**

Run: `python src/core/server.py --smoke`
Run: `python src/console/app.py --smoke`
Run: `python src/research/app.py --smoke`
Expected: trois `VERDICT : OK`

- [ ] **Step 8 : commit**

```bash
git add README.md CLAUDE.md docs/SPEC.md
git commit -m "Record the reversal next to the decision it overturns"
```

---

## Après le plan : ce qui reste à vérifier sur le casque

Trois choses que **seul le matériel peut trancher**, et qu'aucun test synthétique ne remplace.
À faire dans cet ordre, en une séance.

1. **Non-régression du SSVEP.** Le moteur a été validé casque le 2026-07-27 : 16/16 de justesse
   quand il émet, 0 confusion sur 36 essais. Rejouer un run guidé
   (`python src/research/ssvep_guided.py`) et vérifier que la justesse n'a pas bougé. C'est le
   risque n°1 de la spec, et c'est le seul point où une régression silencieuse serait vraiment
   coûteuse.
2. **Le cumul sous charge réelle.** Deux décodeurs sur le même tampon est trivial en synthétique.
   Ce qui ne l'est pas : la charge CPU et son effet sur la cadence d'acquisition. Lancer
   `--mode ssvep,neuro` sur casque et comparer la cadence effective annoncée à l'arrêt
   (`échantillons publiés … Hz effectif`) avec celle d'un mode seul. Un écart net signifie que la
   boucle n'absorbe pas deux décodeurs, et il faudra alors espacer les `period_s`.
3. **Le repos partagé, vécu.** Vérifier qu'une seule consigne s'affiche, qu'elle dure bien 25 s
   (le maximum), et que **les deux** modes se mettent à décoder à la fin. C'est la règle la plus
   facile à casser sans que rien ne le signale : un mode dont le plancher n'a pas été mesuré ne
   lève aucune erreur, il ne détecte simplement jamais rien.

⚠️ Avant la séance : **saliner les électrodes** (c'est le principal levier de qualité du signal,
gain mesuré très net) et vérifier le contact **avant** d'enregistrer. Et ne pas fermer/rouvrir
l'application en cours de séance : C3/Cz saturent à la réouverture.

## Auto-relecture

**Couverture de la spec** — chaque section a sa tâche :

| Spec | Tâches |
|---|---|
| §3 contrat `ModeSpec`, `Param`, `Rest`, `Calib` | 1 |
| §3 registre complet, honnêteté de l'interface | 2 |
| §3.1 `proposes` permis, non livré | 1, 2 (test d'intégrité) — écart n°2 assumé |
| §4.1 paquets `core/modes/`, `src/console/` | 1-6, 11-15 |
| §4.2 runtime par mode, cumul, repos partagé | 3-8 |
| §4.3 API de commande étendue | 7 |
| §4.4 console, `recent_window`, règle « aucune logique dans l'interface » | 7, 11, 14, 15 |
| §4.5 suppression du tableau de bord web | 9 |
| §5.1 grille + bandeau permanent | 11, 12 |
| §5.2 page de mode, trois blocs | 13, 14 |
| §5.3 mode brut et ses tracés | 15 |
| §6 cas limites (6 lignes) | 7 (garde `_apply`, `_resolve`), 8 (dernier mode arrêté), 12 (tuile qui dit pourquoi), 14 (refus affiché) |
| §7 tests (intégrité, contraintes, cumul, repos partagé, frontière, smoke console) | 1, 2, 8, 11-15 |
| §8 périmètre : formulaire en lecture-écriture, `SPEC.md` et `README` à jour | 14, 16 |
| §9 risques : PySide6, régression, cumul jamais testé casque | 0, contrainte globale, « après le plan » |

**Cohérence des noms** — vérifiés d'une tâche à l'autre : `spec.runtime_cls` (2 → 7) ·
`engine.recent` interne vs `recent_window()` public (7 → 15) · `engine.new_block` (4 → 7) ·
`state["modes"]` liste d'ids vs `state["modes_state"]` détaillé (7 → 12, 13) ·
`Console.commande` renommée depuis `_commande` (12 → 14) ·
`live_views.build(family, ch_names)` gagne un argument à la tâche 15 (13 → 15).

**Deux points à surveiller à l'exécution**, signalés à leur tâche plutôt que résolus d'avance :

- `NeuroDecoder.__init__` accepte-t-il le lissage en paramètre ? (tâche 6, étape 3). À vérifier
  dans le code plutôt qu'à supposer.
- `params["ssvep"]` posé alors que le SSVEP n'est pas démarré (tâche 7, étape 6) : `_prepare`
  doit l'ignorer, sinon filtrer.

