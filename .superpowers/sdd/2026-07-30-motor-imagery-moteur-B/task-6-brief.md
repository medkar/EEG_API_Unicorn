### Task 6: La console — la page de calibration, les bips, la liste des modèles

**Files:**
- Create: `src/console/beeps.py`
- Create: `src/console/calib_page.py`
- Modify: `src/console/mode_page.py` (bouton « Calibrer », rafraîchir la liste des modèles)
- Modify: `src/console/params_form.py` (`set_choices`)
- Modify: `src/console/app.py` (la page dans la pile, la navigation, le smoke)

**Interfaces:**
- **Consomme** — `snapshot()["calibration"]` (T4), `spec["calibration"]` du catalogue (T1),
  les commandes `start_calibration` / `cancel_calibration` (T4), `mi_models.decrire` (existant).
- **Produit** — `CalibPage(spec, console)` avec `update_from(state)` et le signal `retour`.

**Règle de la console, rappelée parce que cette page est celle où il est le plus tentant de
l'enfreindre** : elle RESSORT `state["calibration"]` et ne calcule rien. Pas de décompte tenu par
un `QTimer` local, pas de phase déduite, pas de verdict recalculé. Le décompte, la classe, le
numéro d'essai, le verdict : tout vient du moteur.

- [ ] **Step 1: `src/console/beeps.py`**

```python
"""Les tops latéralisés de la calibration : oreille gauche, droite, ou les deux.

Le son est de la PRÉSENTATION, pas du protocole. Si l'audio manque — machine sans carte son,
session distante, pilote absent — la calibration se déroule quand même, et la page le DIT. Un
top silencieux qui ne s'annonce pas ferait croire à l'étudiant qu'il a raté le départ.

Pourquoi latéraliser : le côté est porté par l'oreille (gauche/droite) et le repos par la durée
(les deux oreilles, plus long). L'étudiant n'a donc rien à LIRE au moment où il doit commencer à
imaginer — lire déplace le regard et contamine la fenêtre enregistrée.
"""

import numpy as np

FREQ_HZ = 880.0
SR = 44100
DUREE_COTE_S = 0.18
DUREE_CENTRE_S = 0.40


def _onde(gauche, droite, duree):
    """Un top stéréo entrelacé, en int16. Fondu de 10 ms aux deux bouts (anti-clic)."""
    t = np.linspace(0, duree, int(SR * duree), endpoint=False)
    enveloppe = np.clip(np.minimum(t / 0.01, (duree - t) / 0.01), 0, 1)
    ton = (0.35 * np.sin(2 * np.pi * FREQ_HZ * t) * enveloppe * 32767).astype(np.int16)
    stereo = np.zeros((len(ton), 2), dtype=np.int16)
    if gauche:
        stereo[:, 0] = ton
    if droite:
        stereo[:, 1] = ton
    return stereo.tobytes()


class Beeps:
    """Les trois tops. `disponible` dit franchement si le son sortira."""

    def __init__(self):
        self.disponible = False
        self.raison = ""
        self._sinks = {}
        self._données = {}
        try:
            from PySide6.QtCore import QBuffer, QByteArray
            from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

            sortie = QMediaDevices.defaultAudioOutput()
            if sortie is None or sortie.isNull():
                self.raison = "aucune sortie audio sur cette machine"
                return
            fmt = QAudioFormat()
            fmt.setSampleRate(SR)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(QAudioFormat.Int16)
            for cle, (g, d, duree) in {
                    "GAUCHE": (True, False, DUREE_COTE_S),
                    "DROITE": (False, True, DUREE_COTE_S),
                    "REPOS": (True, True, DUREE_CENTRE_S)}.items():
                octets = QByteArray(_onde(g, d, duree))
                tampon = QBuffer()
                tampon.setData(octets)
                self._données[cle] = tampon
                self._sinks[cle] = QAudioSink(sortie, fmt)
            self.disponible = True
        except Exception as e:  # noqa: BLE001 - l'audio casse de mille façons, toutes équivalentes
            self.raison = f"{type(e).__name__} : {e}"

    def jouer(self, classe):
        """Joue le top de cette classe. Ne lève jamais : un son raté n'arrête pas une séance."""
        if not self.disponible:
            return
        try:
            from PySide6.QtCore import QIODevice

            sink, tampon = self._sinks.get(classe), self._données.get(classe)
            if sink is None or tampon is None:
                return
            sink.stop()
            tampon.close()
            tampon.open(QIODevice.ReadOnly)
            tampon.seek(0)
            sink.start(tampon)
        except Exception:  # noqa: BLE001
            pass
```

- [ ] **Step 2: `set_choices` dans `params_form.py`**

Ajouter à `ParamsForm` :

```python
    def set_choices(self, cle, choix, garder=True):
        """Recharge la liste d'un champ « choice » sans reconstruire le formulaire.

        Nécessaire parce qu'une calibration fait APPARAÎTRE un modèle : la liste résolue à
        l'ouverture de la page devient fausse à la seconde où la séance se termine, et
        reconstruire tout le formulaire perdrait la saisie en cours dans les autres champs.

        ⚠️ N'est PAS appelée à chaque rafraîchissement : résoudre les choix du réglage `model`
        lit le disque (`joblib.load` par fichier). Une version antérieure de ce projet a mis
        30 % d'un cœur sur le fil Qt en résolvant un catalogue dix fois par seconde. On appelle
        ceci sur ÉVÉNEMENT — entrée dans la page, fin d'une calibration.
        """
        champ = self.champs.get(cle)
        param = self._params_par_cle.get(cle)
        if champ is None or param is None or param["kind"] != "choice":
            return
        courant = champ.currentText()
        champ.blockSignals(True)
        champ.clear()
        champ.addItems([str(c) for c in choix])
        if garder and courant in [str(c) for c in choix]:
            champ.setCurrentText(courant)
        champ.blockSignals(False)
```

- [ ] **Step 3: `src/console/calib_page.py`**

Trois écrans dans une seule page, choisis par la phase reçue :

1. **Avant** (`state["calibration"]` absent ou terminé) — le briefing du contrat, le formulaire de
   la calibration, la durée estimée, un bouton « Commencer ». Plus une ligne d'avertissement si
   l'audio manque.
2. **Pendant** — la consigne EN GRAND, la classe, le décompte, « essai *n* sur *N* », une barre de
   progression, un bouton « Abandonner ».
3. **Après** (`phase == "fini"`) — l'accuracy HONNÊTE, le niveau du hasard à côté, le verdict, le
   nom du modèle, et la phrase d'honnêteté (ci-dessous). Ou, si `phase == "annule"`, le problème.

```python
"""La page de calibration : briefing, déroulé, résultat. Elle ne décide de RIEN.

Tout ce qu'elle affiche vient de `snapshot()["calibration"]` : la phase, la consigne, la classe
cuée, le décompte, le numéro d'essai, le verdict. Aucun `QTimer` local ne tient de décompte, aucune
phase n'est déduite. C'est la règle de la console (« aucune logique que le moteur ne possède
déjà »), et ici elle a une raison de plus : le minutage d'une calibration est le protocole. Deux
horloges qui divergent donneraient un écran qui ment sur ce que le moteur enregistre vraiment.
"""
```

Points à respecter, dans l'ordre d'importance :

- **La phrase d'honnêteté, toujours affichée avec le résultat**, quelle que soit l'accuracy :

  ```python
  HONNETETE = (
      "Ce chiffre est une validation croisée PAR ESSAI : il estime ce que le modèle fera sur un "
      "essai qu'il n'a jamais vu. C'est plus bas — et plus vrai — que ce qu'affichait l'ancien "
      "écran de calibration, qui mélangeait des fenêtres d'un même essai entre apprentissage et "
      "test et se gonflait ainsi de 10 à 16 points.\n"
      "Repère : sur la seule séance de référence du projet, mesurée honnêtement, 40 % à 3 classes "
      "(pas significatif) et 63 % à 2 classes. Le Motor Imagery ne marche pas également bien chez "
      "tout le monde, et une séance modeste est un résultat ordinaire, pas une faute."
  )
  ```
- **Le niveau du hasard à côté de l'accuracy**, toujours : `f"{cv*100:.1f} % (hasard {h*100:.0f} %)"`.
  Un 40 % ne veut rien dire sans lui.
- **Le décompte** vient de `state["calibration"]["restant_s"]`, jamais d'un timer local.
- **Le bouton « Commencer »** émet `start_calibration` avec `params=self.formulaire.values()`.
- **Le bouton « Abandonner »** émet `cancel_calibration`. Il doit exister pendant TOUTE la séance :
  un étudiant qui a mal placé une électrode doit pouvoir sortir sans tuer la console.
- **Les tops** : jouer `beeps.jouer(classe)` quand `(phase, essai, etape)` passe à `etape == "cue"`
  pour un essai qu'on n'a pas encore sonné. Retenir la dernière clé jouée ; ne jamais rejouer sur
  un simple rafraîchissement (la page est mise à jour 10 fois par seconde).
- **`isEnabled` du formulaire** : désactivé pendant la séance, réactivé après. Changer la durée en
  cours de route n'aurait aucun effet, et un champ actif sans effet est un mensonge.
- Le signal `retour` ramène à la grille, comme `ModePage`.

- [ ] **Step 4: Le bouton « Calibrer » sur la page de mode**

Dans `ModePage.__init__` de `src/console/mode_page.py`, dans l'entête, avant `entete.addStretch(1)` :

```python
        # Le bouton n'existe que si le CONTRAT dit que ce mode se calibre depuis la console. Rien
        # ici ne sait qu'un MI s'entraîne et qu'un SSVEP non : c'est `Calib.kind` qui le dit.
        calib = spec.get("calibration") or {}
        self.bouton_calibrer = None
        if calib.get("kind") == "console":
            self.bouton_calibrer = QPushButton("Calibrer")
            self.bouton_calibrer.clicked.connect(
                lambda: console.show_calibration(self.mode_id))
            entete.addWidget(self.bouton_calibrer)
```

Et, à la fin de `ModePage`, une méthode pour recharger la liste des modèles :

```python
    def rafraichir_choix(self):
        """Recharge les listes de choix DYNAMIQUES de ce mode (les modèles entraînés).

        Appelée sur ÉVÉNEMENT — entrée dans la page, retour d'une calibration — jamais dans le
        rafraîchissement périodique : résoudre ces choix lit le disque, et le faire dix fois par
        seconde a déjà coûté 30 % d'un cœur à ce projet.
        """
        spec = registry.get(self.mode_id)
        if spec is None:
            return
        for param in spec.params:
            if param.choices_fn is not None:
                self.formulaire.set_choices(param.key, param.choices_now())
```

- [ ] **Step 5: Câbler dans `console/app.py`**

Dans `Console.__init__`, après la boucle qui crée les `ModePage` :

```python
        # Une page de calibration par mode qui se calibre DEPUIS la console. Les autres (c-VEP,
        # P300 : stimulus verrouillé à la frame) n'en ont pas — leur contrat le dit, et le moteur
        # refuserait la commande de toute façon.
        self.beeps = Beeps()
        self.calib_pages = {}
        for spec in registry.catalog():
            calib = spec.get("calibration") or {}
            if calib.get("kind") != "console" or spec["status"] != "moteur":
                continue
            page = CalibPage(spec, self)
            page.retour.connect(self.show_grid)
            self.calib_pages[spec["id"]] = page
            self.stack.addWidget(page)
```

Et les deux méthodes de navigation :

```python
    def show_calibration(self, mode_id):
        page = self.calib_pages.get(mode_id)
        if page is not None:
            self.stack.setCurrentWidget(page)

    def show_mode(self, mode_id):
        page = self.pages.get(mode_id)
        if page is not None:
            # Entrer dans la page est l'événement qui justifie de relire le disque : c'est là
            # qu'un modèle fraîchement entraîné doit apparaître dans la liste.
            page.rafraichir_choix()
            self.stack.setCurrentWidget(page)
```

⚠️ `apply_state` ne met à jour que `self.stack.currentWidget()`. Vérifier que la page de
calibration en bénéficie : elle est bien dans la pile, donc `currentWidget()` la désigne quand elle
est affichée. Ne pas mettre à jour toutes les pages — c'était déjà le choix, pour la même raison de
coût.

Ajouter `"calibration": None` à `fake_state()` (l'état factice doit couvrir la nouvelle clé), et
les imports en tête : `from console.beeps import Beeps` · `from console.calib_page import CalibPage`.

- [ ] **Step 6: Le test, dans `_smoke()` de `console/app.py`**

À placer après le bloc Motor Imagery existant :

```python
    # --- la page de calibration -------------------------------------------------
    # Elle est éprouvée sur des états FABRIQUÉS, phase par phase : c'est le seul moyen de
    # vérifier chaque écran sans jouer sept minutes de séance.
    console.show_calibration("mi")
    cal = console.stack.currentWidget()
    chk(cal is console.calib_pages["mi"], "« Calibrer » ouvre la page de calibration du MI")
    chk(len(console.calib_pages) == 1,
        f"et seul le MI en a une — le c-VEP et le P300 ont un stimulus natif "
        f"({sorted(console.calib_pages)})")

    # 1. Avant : le briefing du CONTRAT, pas un texte recopié dans l'interface.
    console.apply_state({**mi_state, "calibration": None})
    from core.modes import mi_calib
    chk(mi_calib.BRIEFING[0] in cal.briefing.text(),
        "le briefing affiché vient du contrat du mode")
    chk(cal.bouton_commencer.isEnabled(), "et « Commencer » est actif")

    moteur_faux.commandes.clear()
    cal.bouton_commencer.click()
    envoyees = [c for c in moteur_faux.commandes if c[0] == "start_calibration"]
    chk(envoyees and envoyees[0][1]["id"] == "mi"
        and "trials_per_class" in envoyees[0][1]["params"],
        f"cliquer « Commencer » soumet start_calibration avec la durée choisie ({envoyees})")

    # 2. Pendant : la consigne, la classe, le décompte, la progression — tous reçus, aucun calculé.
    en_cours = {**mi_state, "calibration": {
        "mode_id": "mi", "label": "Calibration Motor Imagery", "phase": "essais",
        "etape": "imagerie", "classe": "GAUCHE",
        "instruction": "Imagine : SERRE le POING GAUCHE", "rappel": "sens le serrement",
        "essai": 7, "total": 42, "restant_s": 2.4, "duree_estimee_s": 400.0,
        "params": {"trials_per_class": 14}, "classes": ["GAUCHE", "DROITE", "REPOS"],
        "resultat": None, "probleme": ""}}
    console.apply_state(en_cours)
    chk("SERRE le POING GAUCHE" in cal.consigne.text(),
        f"la consigne du moteur est affichée telle quelle ({cal.consigne.text()})")
    chk("2.4" in cal.decompte.text() or "2,4" in cal.decompte.text(),
        f"le décompte vient du moteur, pas d'un timer local ({cal.decompte.text()})")
    chk("7" in cal.progression.text() and "42" in cal.progression.text(),
        f"et la progression nomme les deux nombres ({cal.progression.text()})")
    chk(not cal.formulaire.isEnabled(),
        "le formulaire est verrouillé pendant la séance : le changer n'aurait aucun effet")

    moteur_faux.commandes.clear()
    cal.bouton_abandon.click()
    chk(("cancel_calibration", {}) in moteur_faux.commandes,
        f"« Abandonner » passe par la file de commandes ({moteur_faux.commandes})")

    # 3. Après : l'accuracy HONNÊTE, le hasard à côté, et la phrase qui dit ce que ça vaut.
    fini = {**mi_state, "calibration": {**en_cours["calibration"], "phase": "fini",
            "etape": "", "classe": "", "instruction": "", "restant_s": 0.0,
            "resultat": {"modele": "/tmp/mi_model_20260730-141205.joblib",
                         "nom": "mi_model_20260730-141205.joblib",
                         "enregistrement": "/tmp/mi_calib_20260730-141205_n42.npz",
                         "n_essais": 42, "n_fenetres": 126, "cv_groupee": 0.401,
                         "cv_naive": 0.556, "hasard": 1 / 3,
                         "classes": ["GAUCHE", "DROITE", "REPOS"],
                         "verdict": "FAIBLE — ré-essaie"}}}
    console.apply_state(fini)
    chk("40.1" in cal.resultat.text() or "40,1" in cal.resultat.text(),
        f"l'accuracy affichée est l'HONNÊTE ({cal.resultat.text()})")
    chk("55.6" not in cal.resultat.text() and "55,6" not in cal.resultat.text(),
        f"et JAMAIS la naïve, qui est gonflée de 10 à 16 points ({cal.resultat.text()})")
    chk("33" in cal.resultat.text(),
        f"le niveau du hasard est à côté — sans lui, 40 % ne veut rien dire ({cal.resultat.text()})")
    chk("mi_model_20260730-141205.joblib" in cal.details.text(),
        f"le nom du modèle produit est donné ({cal.details.text()})")
    chk("séance de référence" in cal.honnetete.text(),
        "et la page dit franchement ce qu'un résultat modeste signifie")

    # 4. Abandon : pas de modèle, et la raison.
    annule = {**mi_state, "calibration": {**en_cours["calibration"], "phase": "annule",
              "resultat": None, "probleme": "ValueError : pas assez de données"}}
    console.apply_state(annule)
    chk("pas assez de données" in cal.resultat.text(),
        f"une calibration annulée dit pourquoi ({cal.resultat.text()})")

    cal.bouton_retour.click()
    chk(console.stack.currentWidget() is console.grid,
        "et la page de calibration ramène sur la grille")
```

- [ ] **Step 7: Lancer**

Run: `python src/console/app.py --smoke`
Expected: `[console-smoke] VERDICT : OK`

- [ ] **Step 8: REGARDER la console, en vrai**

C'est la seule étape de ce plan qui demande un écran. Elle est **obligatoire** : la console n'a
**jamais été ouverte en fenêtre** de tout le projet, tout a été vérifié en Qt `offscreen`.

```bash
python src/console/app.py --synthetic
```

Vérifier de ses yeux : la tuile MI porte « Démarrer » ; sa page porte « Calibrer » ; le briefing
est lisible ; « Commencer » lance une séance dont le décompte avance ; « Abandonner » sort ; les
tops se font entendre (ou la page dit que l'audio manque). **Ne pas laisser tourner** cette console
avant de relancer un test.

- [ ] **Step 9: Commit**

```bash
git add src/console/beeps.py src/console/calib_page.py src/console/mode_page.py src/console/params_form.py src/console/app.py
git commit -m "Give the console a calibration page: brief, run, honest result"
```

---

