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

