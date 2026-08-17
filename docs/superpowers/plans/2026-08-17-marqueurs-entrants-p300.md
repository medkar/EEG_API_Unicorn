# Marqueurs entrants + P300 sur le réseau — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Le moteur reçoit des marqueurs horodatés d'une application externe, époque l'EEG dessus, et publie le P300 comme 4e mode du réseau.

**Architecture:** Un tuyau générique (`MarkerInlet` → tampon d'horodatages → file de marqueurs mûrs → point d'extension du contrat de mode), dont le P300 est le premier client. Le moteur livre des marqueurs *situés* et *mûrs* ; le découpage en époques reste au décodeur, qui le fait déjà et a été validé au casque.

**Tech Stack:** Python 3, `pylsl`, `numpy`, `scipy.signal`, `scikit-learn`, `pyriemann` (xDAWN + tangent space), `joblib`.

**Spec de référence :** [docs/superpowers/specs/2026-08-17-marqueurs-entrants-p300-design.md](../specs/2026-08-17-marqueurs-entrants-p300-design.md) (commit `24599c0`).

## Global Constraints

- `src/core/` n'importe **jamais** `src/research/` ni `src/console/`, et ne contient **ni pygame ni Qt**. Vérifié par `python src/core/server.py --smoke`, qui scanne `src/core/**/*.py`.
- La console est un **client** du moteur : aucune logique qui n'existe pas déjà côté moteur.
- Code, commentaires et docstrings **en français** ; messages de commit **en anglais**.
- Tout doit être testable **sans casque** (`--synthetic`).
- **Aucun test n'écrit dans le vrai `data/`** : `tempfile.mkdtemp()` + `shutil.rmtree` dans un `finally`.
- ⚠️ **Aucun moteur ne tourne pendant un test** : les noms de flux sont un contrat public, donc identiques pour toutes les instances. Un serveur oublié répond à la place de celui qu'on teste.
- `target` est un **indice à partir de 0**, dans `[0, P300_N_TARGETS[` soit `0..5`. `-1` est réservé à la SORTIE (« pas de décision ») et n'a aucun sens en entrée.
- Valeurs figées, déjà présentes dans `src/core/config.py`, à utiliser **verbatim** : `P300_N_TARGETS = 6`, `P300_BAND = (1.0, 12.0)`, `P300_PRE_S = 0.15`, `P300_EPOCH_S = 0.80`, `P300_REPS = 8`, `P300_XDAWN_NFILTER = 4`, `P300_SELECT_MARGIN = 0.0`, `P300_MODEL_PATH`.
- Style d'autotest du projet, à respecter dans **chaque** module touché : une fonction `_selftest()` avec un `chk(cond, msg)` local, une ligne finale `print(f"[<nom>] VERDICT : {'OK' if ok else 'PROBLÈME'}")`, et `_sys.exit(0 if _selftest() else 1)` sous `if __name__ == "__main__":`.

---

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| **Créer** `src/core/markers.py` | `MarkerInlet` : résoudre un flux entrant PAR SON NOM, tirer sans bloquer, corriger l'horloge, décoder le JSON. Ne connaît aucun mode. |
| **Créer** `src/core/p300_models.py` | Les modèles P300 sur le disque : lesquels existent, lequel se charge vraiment, refus des modèles hérités. Jumeau de `mi_models.py`. |
| **Créer** `src/core/modes/p300.py` | Le MODE P300 : son `ModeSpec`, ses réglages, son `P300Runtime`. Jumeau de `modes/mi.py`. |
| **Créer** `src/research/p300_stimulus.py` | L'émetteur autonome : affiche les flashs et publie ses marqueurs. Jumeau de `ssvep_stimulus.py`. N'ouvre PAS le casque. |
| **Déplacer** `src/research/p300_decoder.py` → `src/core/p300_decoder.py` | Le décodeur, inchangé sauf son chemin d'import. |
| **Modifier** `src/core/config.py` | `MARKER_LATE_S`, `MARKER_STREAM_DEFAULT`. |
| **Modifier** `src/core/server.py` | Tampon d'horodatages, `keep` dimensionné nommément, cycle de vie du `MarkerInlet`, file des marqueurs mûrs. |
| **Modifier** `src/core/modes/contract.py` | Champ `marker_epoch_s` sur `ModeSpec`. |
| **Modifier** `src/core/modes/registry.py` | Enregistrer `p300.SPEC`, retirer `external.P300`, contrôle structurel du dimensionnement. |
| **Modifier** `src/core/modes/external.py` | Retirer l'entrée `P300` et corriger la docstring du module. |
| **Modifier** `src/core/lsl_io.py` | `p300_channel_labels` + `DecodedP300Publisher`. |
| **Modifier** `src/research/p300_calibrate.py` | Recâblage de l'import vers `core.p300_decoder`. |

---

## Task 1: `MarkerInlet` — recevoir des marqueurs

**Files:**
- Create: `src/core/markers.py`
- Modify: `src/core/config.py` (ajouter deux constantes)

**Interfaces:**
- Consumes: rien des tâches précédentes.
- Produces: `MarkerInlet(nom, timeout_s=0.0)` avec `.resolve() -> bool`, `.pull() -> list[(ts_lsl_local, dict)]`, `.connecte -> bool`, `.nom -> str`. Et `parse_marqueur(txt) -> dict | None`.

- [ ] **Step 1: Ajouter les deux constantes dans `src/core/config.py`**

À placer juste après le bloc `P300_*` (repère : la ligne `P300_MIDLINE = [0, 2, 4]`) :

```python
# --- Marqueurs ENTRANTS (§12.1 : le moteur écoute une application externe) ------------------
MARKER_STREAM_DEFAULT = "EEG_API_Unicorn_stim"   # nom du flux de marqueurs qu'on écoute par défaut
MARKER_LATE_S = 1.0       # retard toléré pour un marqueur (réseau + horloge). Dimensionne le
                          # tampon du moteur AVEC l'époque du mode : un marqueur arrivé après ce
                          # délai ne trouve plus son EEG et sera compté comme perdu, jamais ignoré.
```

- [ ] **Step 2: Écrire l'autotest d'abord, dans `src/core/markers.py`**

Le test tourne **sans réseau** pour la partie décodage, et **avec un vrai `StreamOutlet`** pour la partie bout-en-bout — c'est le seul moyen de prouver que la résolution par nom fonctionne.

```python
def _selftest():
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # 1. Le décodage d'une charge utile, sans aucun réseau.
    chk(parse_marqueur('{"mode":"p300","event":"flash","target":3}')
        == {"mode": "p300", "event": "flash", "target": 3},
        "une charge utile valide se décode telle quelle")
    chk(parse_marqueur("pas du json") is None, "une charge utile illisible rend None, sans lever")
    chk(parse_marqueur("[1, 2, 3]") is None, "du JSON qui n'est pas un objet rend None")
    chk(parse_marqueur('{"event":"flash"}') is None,
        "un marqueur sans « mode » est refusé : on ne devine pas à qui il s'adresse")
    chk(parse_marqueur('{"mode":"p300"}') is None,
        "un marqueur sans « event » est refusé : il n'y a rien à en faire")
    # Les champs inconnus sont GARDÉS, pas refusés : c'est ce qui permettra d'enrichir le
    # protocole sans casser les émetteurs déjà écrits par les étudiants.
    d = parse_marqueur('{"mode":"p300","event":"flash","target":1,"inconnu":42}')
    chk(d is not None and d.get("inconnu") == 42, f"un champ inconnu est gardé, pas refusé ({d})")

    # 2. Un flux introuvable ne lève pas, et le DIT.
    inlet = MarkerInlet("EEG_API_Unicorn_flux_qui_nexiste_pas", timeout_s=0.2)
    chk(inlet.resolve() is False, "un flux introuvable rend False")
    chk(inlet.connecte is False, "et l'inlet se déclare non connecté")
    chk(inlet.pull() == [], "tirer sur un inlet non connecté rend une liste vide, sans lever")

    # 3. Bout en bout, sur un vrai flux LSL.
    nom = "EEG_API_Unicorn_selftest_stim"
    info = StreamInfo(nom, "Markers", 1, IRREGULAR_RATE, "string", "selftest-markers")
    outlet = StreamOutlet(info)
    try:
        inlet = MarkerInlet(nom, timeout_s=5.0)
        chk(inlet.resolve() is True, "un flux publié est trouvé PAR SON NOM")
        t0 = local_clock()
        outlet.push_sample(['{"mode":"p300","event":"flash","target":2}'], timestamp=t0)
        outlet.push_sample(['{"mode":"p300","event":"round_end"}'], timestamp=t0 + 0.1)
        outlet.push_sample(["ceci n'est pas du json"], timestamp=t0 + 0.2)
        recus, essais = [], 0
        while len(recus) < 2 and essais < 50:
            recus.extend(inlet.pull())
            essais += 1
        chk(len(recus) == 2,
            f"les 2 marqueurs valides arrivent, le 3e illisible est écarté ({len(recus)})")
        chk(recus[0][1]["event"] == "flash" and recus[0][1]["target"] == 2,
            f"le premier est le flash de la cible 2 ({recus[0][1]})")
        chk(abs(recus[0][0] - t0) < 0.5,
            f"son horodatage est celui de l'émission, pas celui de la réception "
            f"(écart {recus[0][0] - t0:+.3f} s)")
        chk(recus[1][0] > recus[0][0], "et l'ordre chronologique est conservé")
        chk(inlet.illisibles == 1, f"le marqueur illisible est COMPTÉ ({inlet.illisibles})")
    finally:
        del outlet

    print(f"[markers] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok
```

- [ ] **Step 3: Lancer l'autotest pour le voir ÉCHOUER**

Run: `python src/core/markers.py`
Expected: `NameError` / `ImportError` — `parse_marqueur` et `MarkerInlet` n'existent pas.

- [ ] **Step 4: Écrire `src/core/markers.py`**

```python
"""Recevoir des marqueurs d'une application EXTERNE — l'oreille du moteur.

Le moteur publie depuis toujours ; il ne savait pas écouter. Or trois modes sur six restent
gris dans la grille pour la même raison : ils ont besoin de savoir QUAND quelque chose s'est
produit sur l'écran de quelqu'un d'autre — l'onset d'un flash P300, l'instant où un feedback
s'affiche. Ce module est ce chaînon.

Il ne connaît AUCUN mode : il reçoit des objets JSON horodatés et les rend tels quels. Le sens
des événements appartient aux modes.

⚠️ **Résolution par le NOM, jamais par le type.** Le flux `EEG_API_Unicorn_status` que le moteur
publie lui-même est de type `Markers` : une résolution par type ferait écouter le moteur à
lui-même — il se répondrait, et rien ne le signalerait.

⚠️ **`time_correction()` n'est pas une précaution théorique.** `local_clock()` compte depuis le
démarrage de CHAQUE machine : le projet a mesuré 45 JOURS d'écart entre deux postes. Sans
correction, tous les marqueurs distants tombent hors du tampon du moteur et le mode ne décode
jamais rien — sans la moindre erreur.

Autotest :
    python src/core/markers.py
"""

import json
import os as _os
import sys as _sys

from pylsl import IRREGULAR_RATE, StreamInfo, StreamInlet, StreamOutlet, local_clock, resolve_byprop

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from core.config import use_utf8_console  # noqa: E402


def parse_marqueur(txt):
    """Le JSON d'un marqueur en dictionnaire, ou None s'il est inexploitable.

    On exige `mode` et `event` : sans le premier on ne sait pas à qui le marqueur s'adresse,
    sans le second il n'y a rien à en faire. Tous les autres champs sont GARDÉS tels quels —
    c'est ce qui permettra d'enrichir le protocole sans casser les émetteurs déjà écrits.

    Ne lève jamais : une application cliente mal écrite ne doit pas pouvoir tuer le moteur.
    """
    try:
        d = json.loads(txt)
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict):
        return None
    if not isinstance(d.get("mode"), str) or not isinstance(d.get("event"), str):
        return None
    return d


class MarkerInlet:
    """Un flux de marqueurs entrant, résolu par son NOM. Ne bloque jamais la boucle du moteur."""

    def __init__(self, nom, timeout_s=0.0):
        self.nom = str(nom)
        self.timeout_s = float(timeout_s)
        self.inlet = None
        self.offset = 0.0
        self.illisibles = 0      # marqueurs reçus mais indécodables — compté, jamais tu

    @property
    def connecte(self):
        return self.inlet is not None

    def resolve(self):
        """Cherche le flux. True s'il est trouvé. Peut être rappelé : l'appli démarre parfois
        APRÈS le moteur, et c'est un usage normal, pas une erreur."""
        if self.inlet is not None:
            return True
        flux = resolve_byprop("name", self.nom, timeout=self.timeout_s)
        if not flux:
            return False
        self.inlet = StreamInlet(flux[0])
        # Obligatoire AVANT le premier pull : un inlet ne se connecte qu'à la première lecture
        # et LSL ne rejoue RIEN de ce qui précède. Sans ça, on perd les premiers marqueurs, en
        # silence — le même piège que pour le flux brut.
        self.inlet.open_stream()
        # Mesuré UNE fois, à la connexion. Le re-mesurer à chaque tirage introduirait des SAUTS
        # dans les horodatages, ce qui est bien pire qu'un décalage constant pour épocher.
        self.offset = self.inlet.time_correction()
        return True

    def pull(self, max_n=64):
        """Les marqueurs arrivés depuis le dernier appel : [(ts_lsl_local, dict), ...].

        Horodatage ramené dans l'horloge LOCALE, la même que celle du tampon EEG du moteur.
        Rend [] si rien n'est arrivé ou si l'inlet n'est pas connecté.
        """
        if self.inlet is None:
            return []
        recus = []
        for _ in range(max_n):
            txt, ts = self.inlet.pull_sample(timeout=0.0)
            if txt is None:
                break
            d = parse_marqueur(txt[0])
            if d is None:
                self.illisibles += 1
                continue
            recus.append((float(ts) + self.offset, d))
        return recus
```

- [ ] **Step 5: Lancer l'autotest pour le voir PASSER**

Run: `python src/core/markers.py`
Expected: `[markers] VERDICT : OK`, sortie 0.

- [ ] **Step 6: Commit**

```bash
git add src/core/markers.py src/core/config.py
git commit -m "Give the engine an ear: an inlet for external stimulus markers"
```

---

## Task 2: Le tampon d'horodatages, et `keep` dimensionné nommément

**Files:**
- Modify: `src/core/modes/contract.py` (champ `marker_epoch_s` sur `ModeSpec`)
- Modify: `src/core/server.py` (tampon `recent_ts`, calcul de `keep`, smoke)

**Interfaces:**
- Consumes: `MARKER_LATE_S` (Task 1).
- Produces: `EngineServer.recent_ts` (numpy 1-D, même longueur que `recent`, en temps LSL) ; `ModeSpec.marker_epoch_s: float = 0.0`.

**Contexte que l'implémenteur ne peut pas deviner :** `self.acq.get_new_data()` rend DÉJÀ `(eeg (n,8), ts (n,))` — un horodatage **par échantillon**, en temps Unix. [server.py:854](../../../src/core/server.py#L854) empile `eeg` et **jette `ts`**. Il n'y a donc rien à aller chercher : il faut cesser de jeter.

- [ ] **Step 1: Ajouter le champ au contrat**

Dans `src/core/modes/contract.py`, classe `ModeSpec`, juste après `channels_fn` :

```python
    marker_epoch_s: float = 0.0   # tranche prélevée autour d'un marqueur (pré + post), 0 = ce
                                  # mode n'écoute pas les marqueurs. Dimensionne le tampon du
                                  # moteur : sous-dimensionné, CHAQUE époque serait tronquée en
                                  # silence — le décodeur recevrait moins de signal que le
                                  # contrat n'en annonce, sans la moindre erreur.
```

- [ ] **Step 2: Écrire l'assertion de dimensionnement dans le smoke, AVANT de coder**

Dans `src/core/server.py`, ajouter cette fonction et l'appeler depuis `_smoke()` :

```python
def _smoke_dimensionnement():
    """`keep` couvre-t-il l'époque du mode le plus gourmand EN MARQUEURS, retard compris ?

    ⚠️ Assertion DIRECTE sur `server.keep`, et c'est délibéré. Observer qu'une époque « sort »
    ne prouve RIEN : un tampon sous-dimensionné rend quand même ce qu'on lui demande, juste
    plus court. Ce piège a déjà été rencontré au chantier 3B, sur la calibration MI.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    srv = EngineServer(synthetic=True, modes=(), params={})
    besoin = max([spec.marker_epoch_s for spec in registry.MODES] or [0.0])
    attendu = int(round((besoin + MARKER_LATE_S) * srv.acq.fs))
    chk(besoin > 0.0,
        f"au moins un mode déclare une époque de marqueur ({besoin:g} s)")
    chk(srv.keep >= attendu,
        f"keep={srv.keep} couvre l'époque du marqueur ({besoin:g} s) plus le retard toléré "
        f"({MARKER_LATE_S:g} s) = {attendu} échantillons")
    print(f"[smoke-dimensionnement] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok
```

- [ ] **Step 3: Lancer le smoke pour voir l'assertion ÉCHOUER**

Run: `python src/core/server.py --smoke`
Expected: ÉCHEC sur `au moins un mode déclare une époque de marqueur (0 s)` — aucun mode ne déclare encore `marker_epoch_s`, et `keep` ne le prend pas en compte.

> C'est la preuve rouge : sans elle, on ne saurait pas si le vert final prouve quoi que ce soit.
> Le second `chk` passera dès la tâche 5, quand le P300 déclarera `marker_epoch_s = 0.95`.

- [ ] **Step 4: Dimensionner `keep` nommément**

Dans `src/core/server.py`, remplacer le calcul de `self.keep` ([lignes 144-148](../../../src/core/server.py#L144-L148)) par :

```python
        # L'époque prélevée autour d'un marqueur, plus le retard qu'on tolère pour ce marqueur.
        # ⚠️ Ce besoin doit être NOMMÉ ici. Les 2 s qui suffisaient jusqu'ici venaient de
        # `QUALITY_WINDOW_S` et `MI_WINDOW_S` : personne ne pense à les protéger, et les baisser
        # un jour tronquerait CHAQUE époque P300 en silence.
        #
        # ⚠️ À ne pas confondre avec le filtre juste au-dessus : l'`epoch_s` d'une calibration
        # NATIVE ne dimensionne rien, parce que le moteur ne joue jamais ces calibrations. Ici
        # c'est l'époque du RUNTIME, que le moteur prélève lui-même à chaque marqueur.
        epoque_marqueur = max([spec.marker_epoch_s for spec in registry.MODES] or [0.0])
        self.keep = max(int(QUALITY_WINDOW_S * self.acq.fs),
                        int(NEURO_WINDOW_S * self.acq.fs),
                        int(MI_WINDOW_S * self.acq.fs),
                        int(epoque_calib * self.acq.fs),
                        int(round((epoque_marqueur + MARKER_LATE_S) * self.acq.fs)),
                        self.acq.window_n) + self.acq.margin_n
```

- [ ] **Step 5: Tenir le tampon d'horodatages en phase avec `recent`**

Dans `__init__`, à côté de `self.recent = np.zeros((0, len(CH_NAMES)))` :

```python
        # Les horodatages des mêmes échantillons, en temps LSL. Sans eux on ne peut pas SITUER
        # un marqueur dans le tampon — c'est ce qui manquait pour épocher sur un événement
        # extérieur. Tenus rigoureusement en phase avec `recent` : même longueur, même troncature.
        self.recent_ts = np.zeros((0,))
```

Et dans la boucle, remplacer les deux lignes de [server.py:853-854](../../../src/core/server.py#L853-L854) par :

```python
                        ts_lsl = self.clock.to_lsl(ts_unix)
                        self.new_block = (eeg, ts_lsl)
                        self.recent = np.vstack([self.recent, eeg])[-self.keep:]
                        self.recent_ts = np.concatenate([self.recent_ts, ts_lsl])[-self.keep:]
```

- [ ] **Step 6: Ajouter au smoke la vérification que les deux tampons restent en phase**

```python
def _smoke_tampon_horodate():
    """Les deux tampons ont-ils toujours la même longueur, et le temps y avance-t-il ?

    Un décalage d'un seul échantillon entre `recent` et `recent_ts` déplace TOUTES les époques
    sans rien casser de visible : le décodeur reçoit du signal, de la bonne taille, pris au
    mauvais endroit.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    srv = EngineServer(synthetic=True, modes=(), params={})
    srv.run(duration_s=3.0)
    chk(len(srv.recent) == len(srv.recent_ts),
        f"les deux tampons ont la même longueur ({len(srv.recent)} et {len(srv.recent_ts)})")
    chk(len(srv.recent_ts) > 0, "et ils ne sont pas vides après 3 s d'acquisition")
    diffs = np.diff(srv.recent_ts)
    chk(bool(np.all(diffs > 0)), "le temps avance strictement, sans doublon ni retour en arrière")
    attendu = 1.0 / srv.acq.fs
    chk(bool(np.median(diffs) > 0.5 * attendu and np.median(diffs) < 2.0 * attendu),
        f"et la cadence médiane vaut ~1/fs ({np.median(diffs) * 1000:.2f} ms attendu "
        f"{attendu * 1000:.2f} ms)")
    print(f"[smoke-tampon] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok
```

- [ ] **Step 7: Lancer les trois smokes**

Run: `python src/core/server.py --smoke`
Expected: `[smoke-tampon] VERDICT : OK`. `[smoke-dimensionnement]` échoue encore sur son PREMIER `chk` (aucun mode ne déclare d'époque) — c'est attendu jusqu'à la tâche 5.

Run: `python src/core/modes/registry.py` et `python src/console/app.py --smoke`
Expected: `VERDICT : OK` pour les deux — le champ ajouté au contrat ne doit rien casser.

- [ ] **Step 8: Commit**

```bash
git add src/core/server.py src/core/modes/contract.py
git commit -m "Stop throwing away the sample timestamps the engine already receives"
```

---

## Task 3: La file des marqueurs mûrs, et le point d'extension du contrat

**Files:**
- Modify: `src/core/server.py` (cycle de vie de l'inlet, file par mode, `markers_murs`)
- Modify: `src/core/modes/runtime.py` (documentation du point d'extension)

**Interfaces:**
- Consumes: `MarkerInlet` (Task 1), `recent_ts` (Task 2).
- Produces: `EngineServer.markers_murs(mode_id, post_s) -> list[(ts, dict)]`, `EngineServer.marqueurs_perdus: int`, `EngineServer.marqueurs_futurs: int`, `EngineServer.marker_inlet: MarkerInlet | None`.

**La règle de maturité, en une phrase :** un marqueur n'est exploitable que lorsque `recent_ts[-1] >= ts + post_s`. Avant, l'époque déborderait du tampon et `epoch_from_stream` rendrait `None` — silencieusement.

- [ ] **Step 1: Écrire le test d'abord, dans `_smoke_marqueurs_murs`**

Test sur une horloge et un tampon **fabriqués** : aucun réseau, aucune attente réelle.

```python
def _smoke_marqueurs_murs():
    """Un marqueur n'est rendu que quand son époque tient ENTIÈREMENT dans le tampon."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    srv = EngineServer(synthetic=True, modes=(), params={})
    fs = srv.acq.fs
    # Tampon fabriqué : 3 s de temps qui avance, à partir de t=100.
    srv.recent_ts = np.arange(100.0, 103.0, 1.0 / fs)
    srv.recent = np.zeros((len(srv.recent_ts), 8))

    srv._marqueurs = [(101.0, {"mode": "p300", "event": "flash", "target": 1}),
                      (102.9, {"mode": "p300", "event": "flash", "target": 2}),
                      (101.5, {"mode": "errp", "event": "feedback"})]
    srv._marqueur_curseur = {}

    murs = srv.markers_murs("p300", post_s=0.80)
    chk([m[1]["target"] for m in murs] == [1],
        f"seul le marqueur dont les 0,80 s suivantes sont dans le tampon est rendu ({murs})")
    chk(all(m[1]["mode"] == "p300" for m in murs),
        "et le marqueur d'un AUTRE mode n'est jamais rendu à celui-ci")

    # Le curseur avance : un marqueur mûr n'est rendu qu'UNE fois.
    chk(srv.markers_murs("p300", post_s=0.80) == [],
        "un marqueur déjà rendu ne l'est pas deux fois")

    # Le tampon avance : le second devient mûr à son tour.
    srv.recent_ts = np.arange(100.0, 104.0, 1.0 / fs)
    srv.recent = np.zeros((len(srv.recent_ts), 8))
    murs = srv.markers_murs("p300", post_s=0.80)
    chk([m[1]["target"] for m in murs] == [2],
        f"le tampon ayant avancé, le suivant mûrit à son tour ({murs})")

    # Un marqueur PLUS VIEUX que le tampon est PERDU, et compté.
    avant = srv.marqueurs_perdus
    srv._marqueurs.append((50.0, {"mode": "p300", "event": "flash", "target": 3}))
    srv.markers_murs("p300", post_s=0.80)
    chk(srv.marqueurs_perdus == avant + 1,
        f"un marqueur trop vieux pour le tampon est COMPTÉ perdu, pas ignoré "
        f"({srv.marqueurs_perdus})")

    # Un marqueur dans le FUTUR est la signature du time_correction() oublié.
    avant = srv.marqueurs_futurs
    srv._marqueurs.append((200.0, {"mode": "p300", "event": "flash", "target": 4}))
    srv.markers_murs("p300", post_s=0.80)
    chk(srv.marqueurs_futurs == avant + 1,
        f"un marqueur très en avance est compté à part : c'est le piège des deux machines "
        f"({srv.marqueurs_futurs})")

    print(f"[smoke-marqueurs] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok
```

- [ ] **Step 2: Lancer pour voir échouer**

Run: `python src/core/server.py --smoke`
Expected: `AttributeError: 'EngineServer' object has no attribute 'markers_murs'`.

- [ ] **Step 3: Implémenter dans `EngineServer`**

Dans `__init__` :

```python
        self.marker_inlet = None       # créé au démarrage si un mode écoute des marqueurs
        self._marqueurs = []           # tous les marqueurs reçus, dans l'ordre d'arrivée
        self._marqueur_curseur = {}    # mode_id -> index du prochain marqueur à examiner
        self.marqueurs_perdus = 0      # arrivés trop tard pour trouver leur EEG
        self.marqueurs_futurs = 0      # horodatés en avance : time_correction() oublié ?
```

La méthode, à placer près de `_publish_quality` :

```python
    def markers_murs(self, mode_id, post_s):
        """Les marqueurs de CE mode dont l'époque tient entièrement dans le tampon.

        « Mûr » = le tampon couvre déjà les `post_s` secondes qui SUIVENT le marqueur. Avant,
        l'époque déborderait et le découpage rendrait None — sans rien dire. Cette attente est
        générique, donc elle vit ici : chaque mode qui la réimplémenterait la referait un peu
        différemment.

        Chaque marqueur n'est rendu qu'une fois par mode (curseur par mode). Ceux d'un autre
        mode sont sautés en silence : c'est le SEUL rejet muet autorisé, parce qu'il est normal.
        """
        if not len(self.recent_ts):
            return []
        plus_vieux, plus_recent = float(self.recent_ts[0]), float(self.recent_ts[-1])
        i = self._marqueur_curseur.get(mode_id, 0)
        murs = []
        while i < len(self._marqueurs):
            ts, d = self._marqueurs[i]
            if ts + post_s > plus_recent:
                # Pas encore mûr — et les suivants le sont encore moins : on s'arrête ici.
                break
            i += 1
            if d.get("mode") != mode_id:
                continue
            if ts > plus_recent + MARKER_LATE_S:
                self.marqueurs_futurs += 1
                continue
            if ts < plus_vieux:
                self.marqueurs_perdus += 1
                continue
            murs.append((ts, d))
        self._marqueur_curseur[mode_id] = i
        return murs
```

- [ ] **Step 4: Brancher l'inlet dans la boucle**

Dans `run()`, avant la boucle, créer l'inlet **seulement si un mode actif écoute** :

```python
            # L'inlet n'existe que si un mode en a besoin : ouvrir un flux entrant qui ne sert à
            # personne ferait chercher sur le réseau à chaque tour pour rien.
            besoin_marqueurs = any(rt.spec.marker_epoch_s > 0.0 for rt in self.active.values())
            if besoin_marqueurs:
                nom = MARKER_STREAM_DEFAULT
                self.marker_inlet = MarkerInlet(nom, timeout_s=0.0)
                if self.marker_inlet.resolve():
                    print(f"[server] marqueurs entrants : connecté à « {nom} »")
                else:
                    # Pas une erreur : l'application de stimulus démarre souvent APRÈS le moteur.
                    # On réessaiera dans la boucle, et le mode dira qu'il attend.
                    print(f"[server] marqueurs entrants : « {nom} » pas encore là — j'attends. "
                          f"Lance ton application de stimulus, la connexion se fera toute seule.")
```

Dans la boucle, juste après la lecture EEG :

```python
                    if self.marker_inlet is not None:
                        if not self.marker_inlet.connecte:
                            self.marker_inlet.resolve()
                        self._marqueurs.extend(self.marker_inlet.pull())
                        # Le tampon de marqueurs ne grandit pas indéfiniment : on jette ceux que
                        # TOUS les curseurs ont dépassés. Sans ça, une séance d'une heure garde
                        # 24 000 flashs en mémoire pour rien.
                        if len(self._marqueurs) > 4096 and self._marqueur_curseur:
                            coupe = min(self._marqueur_curseur.values())
                            if coupe > 2048:
                                self._marqueurs = self._marqueurs[coupe:]
                                self._marqueur_curseur = {
                                    k: v - coupe for k, v in self._marqueur_curseur.items()}
```

- [ ] **Step 5: Documenter le point d'extension dans `runtime.py`**

Dans la docstring de la classe `ModeRuntime`, section « à redéfinir dans les sous-classes », ajouter après `_run_step` :

```python
    # Un mode qui écoute des marqueurs déclare `marker_epoch_s` dans son `ModeSpec` et appelle
    # `engine.markers_murs(self.spec.id, post_s)` depuis son `_run_step`. Le moteur lui rend des
    # marqueurs SITUÉS (horodatés dans la même horloge que `engine.recent_ts`) et MÛRS (leur
    # époque tient dans le tampon). Le découpage reste au mode : les bornes ne sont pas les
    # mêmes d'un paradigme à l'autre.
```

- [ ] **Step 6: Lancer les smokes**

Run: `python src/core/server.py --smoke`
Expected: `[smoke-marqueurs] VERDICT : OK`.

- [ ] **Step 7: Commit**

```bash
git add src/core/server.py src/core/modes/runtime.py
git commit -m "Hold markers until their epoch fits, and count the ones that never will"
```

---

## Task 4: Le P300 déménage dans `core/`, et son modèle se ré-entraîne

**Files:**
- Move: `src/research/p300_decoder.py` → `src/core/p300_decoder.py`
- Create: `src/core/p300_models.py`
- Modify: `src/research/p300_calibrate.py` (import)
- Modify: `src/research/p300_analyze.py`, `src/research/app.py` (imports, s'ils citent `p300_decoder`)

**Interfaces:**
- Produces: `core.p300_decoder.P300Model`, `epoch_from_stream`, `synth_p300_epoch` ; `core.p300_models.charger(chemin) -> (modele, raison)`, `modeles_disponibles(dossier=DATA_DIR) -> tuple[str]`.

⚠️ **Le piège central de cette tâche.** `data/p300_model.joblib` se charge sous le nom de module **NU** `p300_decoder` — vérifié le 2026-08-17. Le déplacer dans `core/` le rend **illisible**, exactement comme les 4 modèles MI perdus. **Ne PAS écrire de passerelle de compatibilité** : les époques de calibration ont survécu (`data/p300_calib_*.npz`), donc on a une source de vérité meilleure que le pickle. On ré-entraîne.

- [ ] **Step 1: Déplacer le fichier avec `git mv`, pour que l'historique suive**

```bash
git mv src/research/p300_decoder.py src/core/p300_decoder.py
```

- [ ] **Step 2: NE PAS toucher au `sys.path.insert` — vérifié, il est déjà juste**

La ligne en tête du fichier est :

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

Elle **ne change pas**, et c'est contre-intuitif au point qu'il faut le dire : `src/research/` et
`src/core/` sont à la **même profondeur**, donc deux `dirname` mènent à `src` depuis l'un comme
depuis l'autre. `mi_decoder.py`, déjà dans `core/`, porte exactement la même ligne
([mi_decoder.py:36](../../../src/core/mi_decoder.py#L36)).

⚠️ Ne pas « corriger » cette ligne : la modifier casserait l'import de `core.config`. Le seul
contrôle à faire est de lancer l'autotest du module depuis son nouvel emplacement (étape 6).

- [ ] **Step 3: Recâbler les importeurs**

```bash
grep -rn "p300_decoder" src/ --include=*.py
```

Chaque `from p300_decoder import ...` ou `import p300_decoder` dans `src/research/` devient `from core.p300_decoder import ...`. `research` a le droit d'importer `core` ; l'inverse est interdit.

- [ ] **Step 4: Écrire `src/core/p300_models.py`, avec son autotest**

Jumeau de `mi_models.py`. Le refus des modèles hérités est le cœur : il doit être **explicite et nommé**, pas un échec de chargement obscur.

```python
"""Les modèles P300 sur le disque : lesquels existent, lequel se charge vraiment.

Jumeau de `mi_models.py`, et pour la même raison : un modèle est propre à UNE personne, et le
mode doit pouvoir dire « aucun choix disponible » plutôt que démarrer muet.

⚠️ **Les modèles antérieurs au 2026-08-17 sont refusés, et c'est une décision.** Ils ont été
enregistrés quand le décodeur vivait dans `src/research/`, donc leur pickle référence le module
NU `p300_decoder`, qui n'existe plus sous ce nom. On ne fabrique PAS de passerelle : les époques
de calibration ayant survécu (`data/p300_calib_*.npz`), un modèle se ré-entraîne depuis le disque
en quelques secondes. C'est ce qui manquait au MI, dont les époques avaient été écrasées — et ce
qui a coûté ses 4 modèles.

Autotest :
    python src/core/p300_models.py
"""
```

L'API à écrire, calquée sur `mi_models` :

```python
MOTIF = "p300_model*.joblib"


def charger(chemin):
    """(modèle, None) si le modèle se charge, (None, raison) sinon. Ne lève jamais.

    La `raison` est destinée à un étudiant : elle dit quoi FAIRE, pas seulement ce qui a raté.
    """


def modeles_disponibles(dossier=DATA_DIR):
    """Les chemins des modèles lisibles, du PLUS RÉCENT au plus ancien.

    Le plus récent d'abord, parce que c'est le défaut proposé : après une calibration, c'est
    celui qu'on vient de faire qu'on veut essayer.
    """


def decrire(chemin):
    """Une ligne lisible pour la liste de la console : date, nombre d'époques, AUC honnête."""
```

L'autotest doit prouver **trois** choses, dans un dossier temporaire (jamais `data/`) :

```python
    # 1. Un modèle hérité est refusé EN LE NOMMANT, pas par une exception obscure.
    chk(modele is None and "ré-entraîner" in raison and "calibration" in raison,
        f"un modèle hérité est refusé en disant quoi faire ({raison})")
    # 2. Le tri va du plus récent au plus ancien.
    chk(dispo == (recent, ancien), f"le plus récent d'abord ({dispo})")
    # 3. Un dossier sans modèle rend un tuple vide, sans lever — l'état normal d'un dépôt cloné.
    chk(modeles_disponibles(vide) == (), "un dossier vide rend (), sans lever")
```

- [ ] **Step 5: Ré-entraîner le modèle depuis les époques conservées**

Écrire un petit programme **jetable, dans le scratchpad** (il ne rejoint pas le dépôt) qui charge
`data/p300_calib_20260722_151134_n12.npz`, entraîne un `P300Model` et l'enregistre horodaté sous
`data/p300_model_<AAAAMMJJ-HHMMSS>.joblib`.

⚠️ **Ne pas écraser `data/p300_model.joblib`.** Il reste la trace de la séance du 22 juillet, et
c'est la seule preuve que le décodage a marché au casque avant ce chantier.

Coller dans le rapport de tâche : le nombre d'époques, la répartition cible/non-cible, et l'**AUC
en validation croisée par groupe** rendue par `P300Model.fit`. Si l'AUC descend nettement sous
celle relevée en juillet, **le dire** plutôt que de continuer : ça signifierait que le
ré-entraînement n'a pas reproduit les conditions d'origine.

- [ ] **Step 6: Lancer tous les autotests touchés**

```bash
python src/core/p300_decoder.py     # le décodeur, depuis son nouvel emplacement
python src/core/p300_models.py      # le refus des modèles hérités, le tri
python src/research/app.py --smoke  # l'appli pygame ne doit pas être cassée par le déménagement
python src/core/server.py --smoke   # la frontière core/ : aucun import interdit
```

Expected: `VERDICT : OK` partout, et le smoke du serveur ne signale **aucun** import de `research` depuis `core`.

- [ ] **Step 7: Commit**

```bash
git add -A src/core/p300_decoder.py src/core/p300_models.py src/research/
git commit -m "Move the P300 decoder into the engine, and retrain rather than shim"
```

---

## Task 5: Le mode P300 — runtime, flux, et les cinq pannes bruyantes

**Files:**
- Create: `src/core/modes/p300.py`
- Modify: `src/core/lsl_io.py` (`p300_channel_labels`, `DecodedP300Publisher`)
- Modify: `src/core/modes/registry.py` (enregistrer, et le contrôle structurel)
- Modify: `src/core/modes/external.py` (retirer `P300`, corriger la docstring)

**Interfaces:**
- Consumes: `markers_murs` (Task 3), `core.p300_decoder` et `core.p300_models` (Task 4).
- Produces: `p300.SPEC` avec `marker_epoch_s = P300_PRE_S + P300_EPOCH_S`, flux `decoded_p300`.

- [ ] **Step 1: Le publieur, dans `src/core/lsl_io.py`**

À placer après `DecodedMIPublisher`, en suivant exactement la forme de `DecodedSSVEPPublisher` :

```python
def p300_channel_labels(n_targets):
    """Voies du flux `decoded_p300`. Une seule fonction pour le publieur ET le `ModeSpec`."""
    return (["target_index", "confidence", "n_flashes"]
            + [f"score_{i}" for i in range(int(n_targets))])


class DecodedP300Publisher:
    """`<PREFIX>_decoded_p300` : quelle cible l'utilisateur a sélectionnée. Une fois par manche.

    ⚠️ `target_index = -1` signifie **« pas de décision »** — jamais « la cible 0 », jamais
    « repos ». C'est mot pour mot la confusion qu'il a fallu inscrire en garde pour le MI, et
    elle se reproduira chez le premier client qui lira ce flux sans lire la doc.

    Ce flux est IRRÉGULIER et rare : un échantillon par `round_end`, pas ~5 Hz comme le SSVEP.
    Un client qui attend un débit régulier attendrait pour rien.
    """

    def __init__(self, n_targets, reps, instance=""):
        self.n_targets = int(n_targets)
        labels = p300_channel_labels(self.n_targets)
        info = StreamInfo(stream_name("decoded_p300"), "Decoded", len(labels),
                          IRREGULAR_RATE, "float32", _source_id("decoded_p300", instance))
        chans = info.desc().append_child("channels")
        for label in labels:
            ch = chans.append_child("channel")
            ch.append_child_value("label", label)
        desc = info.desc().append_child("decoding")
        desc.append_child_value("paradigm", "P300")
        desc.append_child_value("n_targets", str(self.n_targets))
        desc.append_child_value("reps", str(int(reps)))
        # « logodds » : les scores sont les log-odds moyens de la régression logistique, additifs
        # sur les répétitions. Ils ne sont ni bornés ni comparables d'une personne à l'autre —
        # sans cette indication, un seuil côté client n'aurait aucun sens.
        desc.append_child_value("decision_scale", "logodds")
        self.outlet = StreamOutlet(info)

    def push(self, target_index, confidence, n_flashes, scores, lsl_ts=None):
        """`scores` : un score par cible, dans l'ordre des indices 0..n_targets-1."""
        row = ([float(target_index), float(confidence), float(n_flashes)]
               + [float(s) for s in scores])
        block = np.ascontiguousarray(np.asarray(row).reshape(1, -1), dtype=np.float32)
        self.outlet.push_chunk(block, [float(lsl_ts) if lsl_ts else local_clock()])
```

- [ ] **Step 2: Écrire `src/core/modes/p300.py`**

Structure calquée sur `modes/mi.py`. Le `_run_step` est le cœur :

```python
    def _run_step(self, engine, lsl_ts):
        """Ramasser les flashs mûrs, les épocher, et décider à `round_end`."""
        for ts, marqueur in engine.markers_murs(self.spec.id, post_s=P300_EPOCH_S):
            event = marqueur.get("event")
            if event == "flash":
                self._encaisser_flash(engine, ts, marqueur)
            elif event == "round_end":
                self._decider(lsl_ts)
            # Tout autre événement est ignoré : le protocole s'enrichira, et un mode qui
            # refuserait ce qu'il ne connaît pas casserait au premier ajout.

    def _encaisser_flash(self, engine, ts, marqueur):
        cible = marqueur.get("target")
        if not isinstance(cible, int) or not 0 <= cible < self.n_targets:
            # Panne bruyante n°4 : une cible hors plage est un bug de l'application cliente.
            # Le dire une fois par manche suffit ; le répéter 48 fois noierait le terminal.
            self._refus_cible += 1
            if self._refus_cible == 1:
                print(f"[p300] cible « {cible} » hors de la plage attendue "
                      f"[0, {self.n_targets}[ — vérifie l'émetteur de marqueurs")
            return
        epoque = epoch_from_stream(engine.recent, engine.recent_ts, ts, engine.acq.fs,
                                   pre_s=P300_PRE_S, post_s=P300_EPOCH_S)
        if epoque is None:
            # Le marqueur était mûr mais l'époque déborde quand même : le tampon a été vidé
            # entre-temps. Compté, jamais tu.
            self._epoques_perdues += 1
            return
        self._epoques.append(epoque)
        self._cibles.append(cible)
```

Et la décision :

```python
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
            # chance d'être montrées. Refuser est la seule réponse honnête.
            print(f"[p300] manche ignorée : {len(par_cible)} cibles ont flashé sur "
                  f"{self.n_targets} — l'émetteur n'a pas fini sa séquence")
            self._publish(-1, 0.0, len(self._epoques), [0.0] * self.n_targets, lsl_ts)
            self._vider_manche()
            return

        # `select` agrège lui-même les répétitions (moyenne des log-odds) et applique la marge.
        # On ne ré-agrège rien ici : ce calcul a été validé au casque, le refaire à côté en
        # créerait une seconde version qui finirait par diverger.
        choisi, moyennes = self.model.select(par_cible, margin=P300_SELECT_MARGIN)
        scores = [float(moyennes.get(i, 0.0)) for i in range(self.n_targets)]
        if choisi is None:
            self._publish(-1, 0.0, len(self._epoques), scores, lsl_ts)
        else:
            self._publish(int(choisi), float(moyennes[choisi]), len(self._epoques),
                          scores, lsl_ts)
        self._vider_manche()
```

Le `SPEC`, avec ses deux réglages et son point clé :

```python
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
                   "flash. Le moteur l'écoute par son NOM : deux applications peuvent tourner "
                   "sur le réseau sans se mélanger."),
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
```

- [ ] **Step 3: Enregistrer le mode et retirer l'entrée « appli pygame »**

Dans `src/core/modes/registry.py` : importer `p300`, remplacer `external.P300` par `p300.SPEC` **à la place du MI dans l'ordre** — non : le placer **après** `mi.SPEC`, et retirer `external.P300` de la liste.

```python
from core.modes import external, mi, neuro, p300, raw, ssvep  # noqa: E402

MODES = (
    raw.SPEC,
    ssvep.SPEC,
    neuro.SPEC,
    mi.SPEC,
    p300.SPEC,          # le P300 a rejoint le moteur : il écoute les marqueurs d'une appli externe
    external.CVEP,      # puis les modes de l'appli pygame, dans l'ordre où ils ont été écrits
    external.ERRP,
)
```

Dans `src/core/modes/external.py` : supprimer la constante `P300`, et corriger la docstring du
module, qui cite le P300 comme exemple d'absence.

- [ ] **Step 4: Ajouter le contrôle structurel dans `registry.check()`**

Sur le modèle **exact** du contrôle `epoch_s`/`imagery_s` déjà présent ([registry.py:240-254](../../../src/core/modes/registry.py#L240-L254)) :

```python
        # Le même piège que pour la calibration, un cran plus loin : `marker_epoch_s` (ici)
        # dimensionne le tampon du moteur ; `pre_s`/`post_s` (côté runtime) décident ce qu'on en
        # PRÉLÈVE. Deux sources de vérité pour le même nombre, et rien ne les lie : un
        # `marker_epoch_s` trop court tronquerait CHAQUE époque EN SILENCE.
        pre_s = getattr(spec.runtime_cls, "pre_s", None)
        post_s = getattr(spec.runtime_cls, "post_s", None)
        if pre_s is not None and post_s is not None:
            if spec.marker_epoch_s < pre_s + post_s:
                defauts.append(f"{spec.id} : marker_epoch_s={spec.marker_epoch_s:g} s est SOUS "
                               f"pre_s+post_s={pre_s + post_s:g} s de son runtime — chaque "
                               f"époque serait tronquée en silence")
        if spec.marker_epoch_s > 0 and spec.runtime_cls is None:
            defauts.append(f"{spec.id} : déclare marker_epoch_s sans runtime pour les consommer")
```

- [ ] **Step 5: Lancer les autotests**

```bash
python src/core/modes/p300.py       # le mode : époques, décision, les 5 pannes
python src/core/modes/registry.py   # 7 modes dont 5 dans le moteur
python src/core/server.py --smoke   # dont [smoke-dimensionnement], qui doit passer AU VERT
python src/console/app.py --smoke   # la grille : la tuile P300 n'est plus grisée
```

Expected: `VERDICT : OK` partout. **`[smoke-dimensionnement]` passe maintenant ses DEUX `chk`** — c'est le vert qui prouve la tâche 2.

- [ ] **Step 6: Commit**

```bash
git add src/core/modes/p300.py src/core/lsl_io.py src/core/modes/registry.py src/core/modes/external.py
git commit -m "Publish the P300 as the engine's fourth mode, driven by external markers"
```

---

## Task 6: L'émetteur de stimulus, et LE test d'alignement

**Files:**
- Create: `src/research/p300_stimulus.py`
- Modify: `src/core/modes/p300.py` (ajouter le test d'alignement à son autotest)

**Interfaces:**
- Consumes: le contrat de marqueurs (Task 1), le mode P300 (Task 5).
- Produces: `python src/research/p300_stimulus.py [--windowed] [--reps N] [--targets N]`.

- [ ] **Step 1: Écrire LE test d'alignement, dans l'autotest de `modes/p300.py`**

⚠️ **C'est le seul test qui protège vraiment ce chantier.** Un décalage de quelques échantillons
rend tous les autres verts et décode du bruit avec une confiance de 0,92 — indiscernable d'un
succès. Il doit donc vérifier une **position**, pas une réussite.

```python
    # --- LE test d'alignement ------------------------------------------------
    # On fabrique un tampon plat, on y plante un pic d'amplitude unique à un instant CONNU, et
    # on envoie un marqueur à cet instant. L'époque extraite doit contenir ce pic exactement à
    # l'échantillon `n_pre` — c'est-à-dire à l'onset. Un décalage de 3 échantillons (12 ms) ne
    # change RIEN d'autre : l'époque a la bonne taille, le décodeur tourne, les scores sortent.
    fs = 250.0
    n_pre = int(round(P300_PRE_S * fs))       # 37
    n_post = int(round(P300_EPOCH_S * fs))    # 200
    t0 = 1000.0
    ts = np.arange(t0, t0 + 4.0, 1.0 / fs)
    eeg = np.zeros((len(ts), 8))
    instant_du_pic = t0 + 2.0
    i_pic = int(np.searchsorted(ts, instant_du_pic))
    eeg[i_pic, :] = 42.0                      # une valeur qu'aucun calcul ne produit par hasard

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
    chk(abs(epoque[n_pre, 0] - 42.0) < 1e-9,
        f"et c'est bien LA valeur plantée qu'on retrouve ({epoque[n_pre, 0]})")

    # Le même test, décalé d'une demi-période d'échantillonnage : un marqueur ne tombe jamais
    # pile sur un échantillon dans la vraie vie. On accepte 1 échantillon d'écart, pas plus.
    epoque = epoch_from_stream(eeg, ts, instant_du_pic + 0.002, fs,
                              pre_s=P300_PRE_S, post_s=P300_EPOCH_S)
    position = int(np.argmax(epoque[:, 0]))
    chk(abs(position - n_pre) <= 1,
        f"un marqueur entre deux échantillons reste aligné à ±1 ({position} vs {n_pre})")
```

- [ ] **Step 2: Lancer pour voir l'état actuel**

Run: `python src/core/modes/p300.py`
Expected: PASSE si la tâche 5 a bien câblé `engine.recent_ts` dans le bon ordre. **Si ce test échoue, ne pas le contourner** : c'est exactement le défaut qu'il existe pour attraper.

> **Preuve rouge exigée** : avant de conclure, casser volontairement l'alignement (remplacer
> `pre_s=P300_PRE_S` par `pre_s=0.0` dans `_encaisser_flash`) et vérifier que ce test **échoue**.
> Un test qui passe dans les deux cas ne prouve rien. Remettre la valeur ensuite.

- [ ] **Step 3: Écrire `src/research/p300_stimulus.py`**

Calqué sur `src/research/ssvep_stimulus.py`. Points obligatoires :

```python
"""Le stimulus P300, en programme AUTONOME qui publie ses marqueurs.

⚠️ **Ce programme n'ouvre PAS le casque.** C'est ce qui permet de le lancer EN MÊME TEMPS que le
moteur, dans deux terminaux — le même montage que pour le SSVEP :

    python src/core/server.py --mode p300          # terminal 1 : acquiert et décode
    python src/research/p300_stimulus.py           # terminal 2 : affiche et marque

C'est aussi l'exemple de référence pour qui voudra émettre depuis Unity : le protocole est ici,
et surtout l'endroit exact où prendre l'horodatage.
"""
```

Le geste critique, à écrire avec son commentaire :

```python
        pygame.display.flip()
        # ⚠️ L'HORODATAGE SE PREND ICI, juste après le basculement de frame — pas avant de
        # dessiner, pas au moment de décider quelle cible flasher. Une charge utile parfaite
        # envoyée 40 ms trop tôt décale TOUTES les époques d'une frame, et le décodeur corrèle
        # alors contre une réponse évoquée qui n'a pas encore eu lieu.
        outlet.push_sample([json.dumps({"mode": "p300", "event": "flash", "target": cible})],
                           timestamp=local_clock())
```

Et en fin de manche :

```python
    outlet.push_sample([json.dumps({"mode": "p300", "event": "round_end"})],
                       timestamp=local_clock())
```

Le flux publié :

```python
    info = StreamInfo(MARKER_STREAM_DEFAULT, "Markers", 1, IRREGULAR_RATE, "string",
                      f"p300-stim-{os.getpid()}")
    outlet = StreamOutlet(info)
```

- [ ] **Step 4: Ajouter un `--smoke` au stimulus**

Il doit tourner **sans écran** (aucune fenêtre ouverte) et vérifier que la séquence de marqueurs
est bien formée : autant de flashs que `reps × n_targets`, chaque cible vue `reps` fois, et un
`round_end` final. Aucun `pygame.display` dans ce chemin.

- [ ] **Step 5: Lancer**

```bash
python src/research/p300_stimulus.py --smoke
python src/core/modes/p300.py
python src/research/app.py --smoke
```

Expected: `VERDICT : OK` partout.

- [ ] **Step 6: Commit**

```bash
git add src/research/p300_stimulus.py src/core/modes/p300.py
git commit -m "Ship the stimulus emitter, and pin the alignment that everything rests on"
```

---

## Task 7: La documentation — le contrat devient public

**Files:**
- Create: `docs/markers.md`
- Modify: `README.md`, `docs/SPEC.md`, `docs/recette.md`, `CLAUDE.md`

**Interfaces:** consomme tout ce qui précède ; ne produit aucun code.

> **Note pour le coordinateur :** cette tâche est écrite par le coordinateur lui-même, sans
> sous-agent. Mesuré deux fois sur ce projet : un sous-agent n'apporte rien à de la documentation
> et coûte un tour de relecture.

- [ ] **Step 1: `docs/markers.md` — le contrat public**

Doit contenir, dans cet ordre : à quoi ça sert · le format exact des deux événements · **où
prendre l'horodatage**, avec le contre-exemple · un émetteur Python complet de 15 lignes,
copiable · un émetteur C#/Unity équivalent · les cinq messages d'erreur du moteur et ce qu'ils
veulent dire · le rappel `time_correction()` pour le cas deux machines.

- [ ] **Step 2: `docs/recette.md` — le niveau 2 gagne un test**

Ajouter un **2.7 — le P300 sur le réseau**, sur le modèle du 2.6 : deux terminaux, la manche qui
s'affiche, la sélection qui sort sur `decoded_p300`, et le rappel qu'**une erreur sur six est
attendue** à 6 cibles quand le modèle est faible.

Ajouter aussi au **niveau 1** un test sans casque : lancer le moteur en `--synthetic --mode p300`
et le stimulus en `--windowed`, et vérifier qu'une sélection sort — le décodage sera du hasard,
mais le **tuyau** se vérifie sans casque.

- [ ] **Step 3: `docs/SPEC.md` — la roadmap et le §5**

- §14 : marquer le chantier fait, avec sa date, et **écrire ce qui reste dehors** (control plane,
  ErrP, calibration jouée par le moteur).
- §5 : ajouter le format de `decoded_p300` au tableau des sorties décodées.
- §12.1 : noter que l'adaptateur ENTRANT existe désormais pour les marqueurs de stimulus, et que
  le control plane (commandes) reste à faire.

- [ ] **Step 4: `README.md` et `CLAUDE.md`**

- README : le moteur publie **4 modes sur 6** ; ajouter `p300_stimulus.py` aux commandes utiles.
- CLAUDE.md : la liste des autotests gagne `python src/core/markers.py`, `python src/core/p300_models.py` et `python src/core/modes/p300.py` ; l'appli pygame ne donne plus accès qu'à **c-VEP et ErrP**.

- [ ] **Step 5: Relancer la totalité des autotests, en série**

```bash
python src/core/config.py && python src/core/modes/contract.py && python src/core/modes/registry.py
python src/core/modes/ssvep.py && python src/core/modes/mi.py && python src/core/modes/p300.py
python src/core/mi_models.py && python src/core/p300_models.py && python src/core/markers.py
python src/core/modes/calibration.py && python src/core/modes/mi_calib.py
python src/core/acquisition.py --synthetic && python src/core/lsl_io.py
python src/core/server.py --smoke && python src/console/app.py --smoke && python src/research/app.py --smoke
```

⚠️ **Un par un, jamais en parallèle** : ils publient tous sur les mêmes noms de flux.

- [ ] **Step 6: Commit**

```bash
git add docs/ README.md CLAUDE.md
git commit -m "Document the marker contract, and say plainly what is still missing"
```

---

## Auto-relecture du plan

**Couverture de la spec** — chaque section a sa tâche : §4.1 → T1 · §4.2 et §4.3 → T2 · §4.4 et §4.5 → T3 · §5 → T1 (décodage) et T6 (émission) · §6 → T5 · §7 → T4 · §8 → T6 · §9 → T5 · §10 → T2, T3 et T6 · §11 → contraintes globales.

**Cohérence des types** — `markers_murs(mode_id, post_s)` rend `[(ts, dict)]` en T3 et est consommée sous cette forme en T5. `epoch_from_stream(eeg, ts, flash_ts, fs, pre_s, post_s)` garde sa signature d'origine, T4 ne fait que la déplacer. `marker_epoch_s` est déclarée en T2, remplie en T5, vérifiée en T2 (smoke) et T5 (`registry.check`).

**Le point faible connu, et il est assumé** : la tâche 4 dépend d'un ré-entraînement dont on ne connaît pas encore l'AUC. Si elle s'effondre par rapport à juillet, le mode P300 publiera des sélections faibles — le tuyau resterait juste, le décodage non. C'est pour ça que l'étape 5 de T4 demande de **coller les chiffres** plutôt que de conclure.
