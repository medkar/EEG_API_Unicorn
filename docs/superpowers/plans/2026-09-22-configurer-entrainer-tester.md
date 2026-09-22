# Configurer · Entraîner · Tester — plan d'implémentation

> **Pour les exécutants :** SOUS-COMPÉTENCE REQUISE — `superpowers:subagent-driven-development`.
> Les étapes sont des cases à cocher (`- [ ]`).

**Spec** : [docs/superpowers/specs/2026-09-22-configurer-entrainer-tester-design.md](../specs/2026-09-22-configurer-entrainer-tester-design.md) (commit `39a709e`), validée.

**But** : une page de mode devient trois blocs — **1. Régler · 2. Entraîner · 3. Tester** — où
« Tester » est UN bouton borné qui possède toute la séquence et rend un score avec son niveau de
hasard.

**Architecture** : on GÉNÉRALISE `core/modes/mesure.py` (`MesureRuntime`), qui sert aujourd'hui un
mode sur six. On en extrait d'abord un socle pour les mesures menées par une fenêtre — ce que
`MesureSSVEP` réimplémente déjà seul — puis on écrit quatre mesures de test par-dessus. Côté
console, `calib_page.py` et `mesure_page.py` fusionnent, et `mode_page.py` est réécrit.

**Pile** : Python 3.12, PySide6, pygame (fenêtres), pylsl, numpy. Pas de framework de test : chaque
module porte son autotest en `__main__`, qui sort en 1 quand il échoue.

## Contraintes globales

Tout ce qui suit s'applique à CHAQUE tâche, sans être répété dans les tâches.

- **Frontière des paquets, vérifiée par `python src/core/server.py --smoke`** : `core` n'importe ni
  `research`, ni `console`, ni `stimulus`, ni `pygame`, ni Qt — le moteur tourne sans écran.
  `stimulus` n'importe ni `research` ni `console`, et n'ouvre **jamais** le casque (`brainflow` et
  `core.acquisition` interdits). `console` n'importe pas `research`.
- **La console est un CLIENT** : aucune logique que le moteur ne possède déjà, aucun catalogue
  recopié, **aucune écriture disque**.
- **Tout l'usage réel se pilote depuis l'interface.** Une capacité livrée sans chemin graphique est
  une tâche INCOMPLÈTE.
- Code et commentaires **en français**. README, `docs/markers.md`, `archive/README.md` et messages
  de commit **en anglais**. `CLAUDE.md`, `docs/SPEC.md`, `docs/recette.md`, `docs/qa.md` en français.
- **Tout testable sans casque** (board synthétique BrainFlow, `SDL_VIDEODRIVER=dummy` pour pygame).
- 🔴 **AUCUN test n'écrit dans le vrai `data/`** — enregistrements EEG d'une personne identifiable
  sur un dépôt PUBLIC. `git status --short data/` ne prouve RIEN : le dossier est gitignoré et rend
  une sortie vide même après écriture. Vérifier par empreinte :
  `python -c "import sys;sys.path.insert(0,'src');from core.config import DATA_DIR,empreinte_dossier;print(len(empreinte_dossier(DATA_DIR)))"` → **43** avant et après.
- **Un seul programme du projet à la fois** pendant les tests : les noms de flux LSL sont un contrat
  public, un moteur oublié répond à la place de celui qu'on teste.
- 🔴 **Chaque correctif se prouve par MUTATION** : remettre le défaut, montrer le rouge, retirer,
  montrer le vert, et dire QUELLES assertions rougissent. Le motif dominant des revues de ce dépôt
  est le test vert qui ne teste rien.
- **Le moteur décode exactement comme aujourd'hui.** Aucun seuil, aucune fenêtre glissante, aucun
  modèle, aucun chiffre ne bouge. Repères à ne pas altérer : SSVEP 100 % justesse / 44 % émission ·
  c-VEP 59,5 / 64,9 % hors-pli · ErrP AUC 0,776 · P300 0,71 · MI 40,0 % à 3 classes.
- **~40 Ko de diff maximum par tâche.**

## Hors périmètre, explicitement

« Connecter » et l'interface avec une application tierce · le décodage continu publié sur le réseau
(l'actuel « Démarrer ») · le dépouillement automatique d'une séance · la déclaration de paramètres
PAR le client · la séance casque elle-même.

---

## Structure des fichiers

| Fichier | Responsabilité | Tâche |
|---|---|---|
| `src/core/modes/contract.py` | `ModeSpec` gagne `test_id: str = ""` | 1 |
| `src/core/modes/registry.py` | `serialize` porte `test_id` ; `MESURES` s'allonge | 1, 3-6 |
| `src/core/modes/mesure_marqueurs.py` **(neuf)** | `MesureMarqueurs` — socle d'une mesure menée par une FENÊTRE : écoute des marqueurs, épochage par le chemin du décodage, compteurs de pertes, causes d'abandon | 2 |
| `src/core/modes/ssvep_mesure.py` | Reposé sur le socle ; son verdict et sa règle de décision ne bougent pas | 2 |
| `src/core/modes/p300_test.py` **(neuf)** | Mesure de test du P300 — justesse de sélection, hasard 1/6 | 3 |
| `src/core/modes/cvep_test.py` **(neuf)** | Mesure de test du c-VEP — justesse + taux d'émission, hasard 1/6 | 4 |
| `src/core/modes/errp_test.py` **(neuf)** | Mesure de test de l'ErrP — COUPLE (bonnes gardées / erreurs attrapées) ; 🔴 cloison d'étiquette | 5 |
| `src/core/modes/mi_test.py` **(neuf)** | Mesure de test du MI — menée par le MOTEUR, sans fenêtre ; hasard 1/3 | 6 |
| `src/console/resultat.py` **(neuf)** | Le bloc de résultat : verdict coloré + chiffres + réserve + repli « Détails » | 7 |
| `src/console/protocole_page.py` **(neuf)** | Fusion de `calib_page.py` et `mesure_page.py` | 8 |
| `src/console/mode_page.py` | Réécrit : trois blocs, ou « Observer » | 9 |
| `src/console/grid.py` | Seconde rangée réduite à « Vérifier le casque » | 10 |
| `docs/qa.md`, `docs/recette.md`, `CLAUDE.md` | Vocabulaire et bloc 1 réécrits | 11 |

---

## Task 1 : le contrat déclare qu'un mode est testable

**Files**
- Modify: `src/core/modes/contract.py` (dataclass `ModeSpec`, après `stimulus_id`)
- Modify: `src/core/modes/registry.py` (`serialize`, le dict de retour)
- Modify: `src/core/server.py` (`_smoke_frontiere` voisinage — section d'assertions du registre)

**Interfaces**
- Produit : `ModeSpec.test_id: str` — la clé d'un `MesureSpec` de `registry.MESURES`, ou `""`.
  Consommé par les tâches 3-6 (qui la posent) et 9 (qui l'affiche).

- [ ] **Étape 1 : écrire l'assertion qui échoue**, dans `_smoke_frontiere` de `src/core/server.py`,
      juste après les assertions de `stimulus_id` :

```python
    # `test_id` désigne une MESURE du registre, jamais un mode : ce sont deux catalogues distincts
    # et `registry.check` interdit déjà qu'un même mot serve aux deux. Une clé qui ne désigne rien
    # donnerait un bouton « Tester » qui refuse au clic, c'est-à-dire un bouton cassé.
    connus = {m.id for m in registry.MESURES}
    orphelins = [s.id for s in registry.MODES if s.test_id and s.test_id not in connus]
    chk(not orphelins,
        f"chaque `test_id` déclaré par un mode désigne une mesure du registre "
        f"({orphelins or 'aucun orphelin'})")
    chk("test_id" in registry.serialize(registry.get("ssvep")),
        "…et le contrat SÉRIALISÉ le porte : sans ça la console ne peut pas savoir qui est testable")
```

- [ ] **Étape 2 : lancer, vérifier que ça échoue**
      `python src/core/server.py --smoke` → `ÉCHEC` sur `AttributeError: 'ModeSpec' object has no attribute 'test_id'`.

- [ ] **Étape 3 : ajouter le champ** dans `src/core/modes/contract.py`, juste après `stimulus_id` :

```python
    test_id: str = ""          # la CLÉ de la MESURE qui éprouve ce mode, ou "" s'il n'est pas
                               # testable. ⚠️ Un mode n'est testable que s'il existe une VÉRITÉ-
                               # TERRAIN à comparer : le Neuro (charge, somnolence, engagement)
                               # et le Brut n'en ont aucune, donc ils n'ont pas de test — ils
                               # s'OBSERVENT. Annoncer un score là où il n'y a pas de bonne
                               # réponse serait une mesure inventée.
```

- [ ] **Étape 4 : le sérialiser** dans `src/core/modes/registry.py`, à côté de `"stimulus_id"` :

```python
        "test_id": spec.test_id,
```

- [ ] **Étape 5 : vert**
      `python src/core/server.py --smoke` → exit 0. (`test_id` est vide partout : l'assertion
      d'orphelins est vraie à vide, celle de sérialisation mord déjà.)

- [ ] **Étape 6 : mutation** — retirer `"test_id": spec.test_id` de `serialize` → la seconde
      assertion rougit. Remettre.

- [ ] **Étape 7 : commit**

```bash
git add src/core/modes/contract.py src/core/modes/registry.py src/core/server.py
git commit -m "Let a mode declare which measure tests it"
```

---

## Task 2 : extraire le socle des mesures menées par une fenêtre

**Files**
- Create: `src/core/modes/mesure_marqueurs.py`
- Modify: `src/core/modes/ssvep_mesure.py` (`MesureSSVEP` hérite du socle)

**Interfaces**
- Consomme : `core.modes.mesure.MesureRuntime`, `core.modes.mesure.MesureSpec`.
- Produit : `MesureMarqueurs(MesureRuntime)` avec — attributs `_essais_vus`, `_epoques_perdues`,
  `_marqueurs_chauffe`, `_essais_annonces` ; méthodes `protocole() -> ()`, `tick(engine, now)`,
  `encaisser(engine, ts, marqueur)`, `total()`, `_abandonne(raison)`, `_verifie_silence(now)` ;
  et **DEUX points d'extension abstraits** que les tâches 3-5 implémentent :

```python
    def _essai_depuis(self, epoque, marqueur):
        """La DÉCISION du moteur pour cet essai, plus la vérité-terrain lue dans le marqueur.

        Rend un objet quelconque que `_mesurer` saura compter, ou `None` si l'essai est perdu.
        C'est ICI, et seulement ici, que le décodeur du mode est appelé.
        """
        raise NotImplementedError

    def _mesurer(self, enregistre, fs):
        """Le verdict, à partir des essais retenus. Hérité de `MesureRuntime`."""
        raise NotImplementedError
```

**Pourquoi cette tâche existe** : `MesureSSVEP` réimplémente seule tout le tuyau (écoute,
épochage, compteurs, silence, abandon). Sans extraction, les quatre mesures des tâches 3-6 le
referaient chacune — et quatre copies d'un épochage divergent, ce qui est exactement la panne que
`modes/marker_calib.py` existe pour empêcher côté calibrations.

🔴 **L'invariant à ne pas perdre en extrayant** : `pre_s` / `post_s` ne sont **pas** redéclarés, ils
sont LUS sur la classe du runtime de DÉCODAGE, et l'époque est prélevée par le **même appel**
(`core.p300_decoder.epoch_from_stream`). C'est ce que `modes/marker_calib.py` tient déjà pour les
calibrations ; le socle des mesures doit le tenir pareil, et pour la même raison : un décalage de
quelques échantillons rend tous les autres tests verts et fait décoder du bruit avec assurance.

- [ ] **Étape 1 : écrire l'autotest du socle** dans `src/core/modes/mesure_marqueurs.py`, section
      `__main__`, AVANT toute extraction — il doit décrire le socle qu'on veut :

```python
    # Le socle compte ce qui ARRIVE, pas ce qui est RETENU, et la distinction a déjà coûté une
    # séance : un `calib_end` perdu après 36 `cue` dont un seul a débordé du tampon faisait
    # abandonner une séance de 3,6 min qui portait 35 essais valides.
    rt = _MesureDEssai(_SPEC_ESSAI, {}, _FauxMoteur())
    for i in range(3):
        rt.encaisser(None, 100.0 + i, {"event": "cue", "target": i})
    rt._epoques_perdues = 1          # une époque a débordé du tampon
    chk(rt._essais_vus == 3 and rt.essai == 2,
        f"`_essais_vus` compte les cue ARRIVÉS (3), `essai` les époques RETENUES (2) — "
        f"({rt._essais_vus}, {rt.essai})")
```

- [ ] **Étape 2 : lancer, vérifier que ça échoue**
      `python src/core/modes/mesure_marqueurs.py` → `ModuleNotFoundError`.

- [ ] **Étape 3 : écrire le socle** en DÉPLAÇANT depuis `ssvep_mesure.py` — ne pas réécrire —
      les méthodes `tick`, `encaisser`, `_encaisse_annonce`, `_verifie_silence`, `_abandonne`,
      `protocole`, `total`, et les attributs de compteurs du `__init__`. Ce qui reste dans
      `ssvep_mesure.py` : `_decision_de_l_essai` (devient `_essai_depuis`), `_mesurer`,
      `duree_estimee_s`, `instruction`, `rappel`, `_echantillonne_le_repos`, `SPEC`.

- [ ] **Étape 4 : reposer `MesureSSVEP` sur le socle** — `class MesureSSVEP(MesureMarqueurs)`.

- [ ] **Étape 5 : vert, et c'est LA preuve de l'extraction**

```bash
python src/core/modes/mesure_marqueurs.py     # le socle
python src/core/modes/ssvep_mesure.py         # 🔴 doit rester vert SANS qu'une assertion change
python src/core/server.py --smoke
```

🔴 **Aucune assertion de `ssvep_mesure.py` ne doit être modifiée.** Si l'une doit l'être,
l'extraction a changé un comportement — c'est un défaut, pas un ajustement. En particulier
`UN ESSAI = UNE DÉCISION` doit rester vert tel quel.

- [ ] **Étape 6 : mutation** — dans le socle, remplacer `self._essais_vus` par `self.essai` dans la
      condition d'attente de `_verifie_silence` → l'assertion du `calib_end` perdu rougit dans
      `ssvep_mesure.py`. Remettre.

- [ ] **Étape 7 : commit**

```bash
git add src/core/modes/mesure_marqueurs.py src/core/modes/ssvep_mesure.py
git commit -m "Extract the base for window-led measures, as marker_calib did for calibrations"
```

---

## Task 3 : la mesure de test du P300

**Files**
- Create: `src/core/modes/p300_test.py`
- Modify: `src/core/modes/registry.py` (`MESURES`), `src/core/modes/p300.py` (`SPEC.test_id`)

**Interfaces**
- Consomme : `MesureMarqueurs` (tâche 2), `core.modes.p300.P300Runtime` (le décodeur réel).
- Produit : `SPEC = MesureSpec(id="p300_test", …, stimulus_id="p300", …)`.

**Ce que le test fait** : rejoue le protocole d'entraînement du P300 — la fenêtre cercle une cible
par manche et publie `cue` — pendant que le moteur **décode** avec le modèle sélectionné au lieu
d'apprendre. Score : **justesse de sélection**, hasard **1/6**.

⚠️ **Le hasard est 1/6, jamais 50 %.** Se tromper de hasard produit un verdict faux sans rien
casser : à 1/2, une justesse de 25 % passerait pour « sous le hasard » alors qu'elle est au-dessus.

⚠️ **Un test EXIGE un modèle.** Le refus vient du moteur (`contract.validate` sur le `Param`
`model`), jamais de l'interface — sinon l'ordre Entraîner → Tester serait une convention d'écran.

- [ ] **Étape 1 : écrire l'autotest**, section `__main__` de `src/core/modes/p300_test.py` :

```python
    # LE test de ce module : le hasard annoncé est celui de la GÉOMÉTRIE, pas un 1/2 par réflexe.
    res = _mesurer_sur(justes=9, essais=12)
    chk(abs(res["hasard"] - 1.0 / 6) < 1e-9,
        f"le hasard d'une sélection parmi 6 est 1/6, jamais 1/2 ({res['hasard']})")
    chk(f"{res['justesse'] * 100:.0f} %" in res["verdict"]
        and f"{res['hasard'] * 100:.0f} %" in res["verdict"],
        f"le verdict porte la mesure ET son hasard, jamais l'un sans l'autre ({res['verdict']})")
    chk(res["n_essais"] == 12,
        f"l'effectif est un nombre de MANCHES, pas de flashs ({res['n_essais']})")
```

- [ ] **Étape 2 : lancer, vérifier que ça échoue** — `python src/core/modes/p300_test.py`.
- [ ] **Étape 3 : écrire `MesureP300(MesureMarqueurs)`** : `_essai_depuis` appelle le décodeur du
      mode sur l'époque et compare au `target` du `cue` ; `_mesurer` compte et rend
      `{n_essais, n_justes, justesse, hasard, ic_bas, ic_haut, verdict, honnetete}`.
- [ ] **Étape 4 : vert** — `python src/core/modes/p300_test.py` et `python src/core/server.py --smoke`.
- [ ] **Étape 5 : mutation** — poser `"hasard": 0.5` → la première assertion rougit. Remettre.
- [ ] **Étape 6 : commit** — `git commit -m "Add the P300 test measure: selection accuracy against 1/6"`

---

## Task 4 : la mesure de test du c-VEP

Même forme que la tâche 3. **Files** : `src/core/modes/cvep_test.py`, `registry.py`, `cvep.py`.

**Ce qui diffère** : le c-VEP a des **seuils** (`corr_min`, `margin`) et un **vote glissant**, donc
il se tait souvent. Le score est un **couple** — justesse **et** taux d'émission — comme le SSVEP,
et pour la même raison : « 71 % de justesse » sans « 46 % d'émission » décrit une BCI qu'on n'a pas.

- [ ] **Étape 1 : l'autotest**

```python
    res = _mesurer_sur(emis=11, justes=8, essais=24)
    chk("46 %" not in res["verdict"] or res["taux_emission"] > 0,
        "le taux d'émission est MESURÉ sur cette séance, pas recopié du repère du projet")
    chk(f"{res['taux_emission'] * 100:.0f} %" in res["verdict"]
        and f"{res['justesse'] * 100:.0f} %" in res["verdict"],
        f"les DEUX chiffres sont dans le verdict, ensemble ({res['verdict']})")
    chk(res["n_emis"] <= res["n_essais"],
        f"on n'émet pas plus souvent qu'on n'a d'essais ({res['n_emis']}/{res['n_essais']})")
```

- [ ] **Étape 2** : échoue. **Étape 3** : implémenter. **Étape 4** : vert.
- [ ] **Étape 5 : mutation** — retirer le taux d'émission du verdict → la deuxième assertion rougit.
- [ ] **Étape 6 : commit** — `git commit -m "Add the c-VEP test measure: accuracy and emission rate together"`

---

## Task 5 : la mesure de test de l'ErrP — 🔴 LA CLOISON D'ÉTIQUETTE

**Files** : `src/core/modes/errp_test.py`, `registry.py`, `errp.py`.

🔴 **Le risque numéro un de tout le chantier.** L'étiquette de l'ErrP voyage sur le marqueur
`feedback`, avec `error: true|false`, **en calibration seulement** : en décodage le marqueur est nu,
délibérément, parce que c'est une BCI **passive** et que donner la réponse au décodeur rendrait faux
tout ce qu'on mesure sur ce mode.

Un TEST a besoin de cette étiquette pour **noter**. Elle doit donc atteindre le **correcteur** et
**JAMAIS le décodeur**. Une fuite produit un score parfait et faux, **en silence**, et aucun autre
test du dépôt ne le verrait.

**Le score est un COUPLE** : part des BONNES commandes gardées / part des ERREURS attrapées. Pas de
hasard unique — c'est un détecteur, pas un sélecteur. Les deux taux se lisent ensemble : sur la
séance de référence, garder 95 % des bonnes n'attrape que 24 % des erreurs ; garder 70 % en attrape
71 %. **Il n'y a pas de repas gratuit**, et annoncer un seul des deux le laisserait croire.

- [ ] **Étape 1 : écrire LE test de la cloison** — celui-ci d'abord, avant tout le reste :

```python
    # 🔴 LE test de ce module. On donne au runtime des marqueurs ÉTIQUETÉS, et on vérifie que
    # l'étiquette n'est jamais passée au décodeur. La preuve est faite sur un décodeur ESPION qui
    # note tout ce qu'on lui donne : c'est la seule façon de tester une ABSENCE.
    espion = _DecodeurEspion()
    rt = MesureErrP(SPEC, {"model": "x"}, _FauxMoteur(decodeur=espion))
    rt.encaisser(None, 100.0, {"event": "feedback", "error": True})
    chk(espion.vu,
        "le décodeur a bien été appelé (sinon l'assertion suivante serait vraie à vide)")
    chk(all("error" not in str(arg) for arg in espion.vu),
        f"…et l'étiquette de vérité-terrain ne lui a JAMAIS été passée ({espion.vu})")
    # Et la réciproque : le correcteur, lui, DOIT l'avoir — sinon il n'y a rien à noter.
    chk(rt._verites == [True],
        f"…tandis que le correcteur l'a reçue ({rt._verites})")
```

- [ ] **Étape 2** : échoue. **Étape 3** : implémenter `MesureErrP(MesureMarqueurs)`.
- [ ] **Étape 4 : vert.**
- [ ] **Étape 5 : DEUX mutations**
  - passer le marqueur entier au décodeur → la deuxième assertion rougit (la fuite) ;
  - ne pas ranger l'étiquette dans `_verites` → la troisième rougit (rien à noter).
- [ ] **Étape 6 : commit** — `git commit -m "Add the ErrP test measure, with the label firewall it needs"`

---

## Task 6 : la mesure de test du Motor Imagery

**Files** : `src/core/modes/mi_test.py`, `registry.py`, `mi.py`.

**Ce qui diffère des trois précédentes** : le MI est **endogène**, il n'a pas de fenêtre. Le moteur
mène lui-même — il tire la classe, l'annonce, décompte — donc `MesureMI` hérite de **`MesureRuntime`
directement** (comme le contrôle alpha), et son `protocole()` rend de vraies `Etape`.

**Hasard** : **1/3** à trois classes, **1/2** en gauche/droite. Il se DÉDUIT du nombre de classes du
modèle chargé, jamais d'une constante.

- [ ] **Étape 1 : l'autotest**

```python
    chk(abs(_hasard_de(["GAUCHE", "DROITE", "REPOS"]) - 1 / 3) < 1e-9,
        "trois classes -> hasard 1/3")
    chk(abs(_hasard_de(["GAUCHE", "DROITE"]) - 1 / 2) < 1e-9,
        "deux classes -> hasard 1/2 : il se DÉDUIT du modèle, il n'est pas écrit en dur")
```

- [ ] **Étape 2** : échoue. **Étape 3** : implémenter. **Étape 4** : vert.
- [ ] **Étape 5 : mutation** — écrire `1/3` en dur → la seconde assertion rougit.
- [ ] **Étape 6 : commit** — `git commit -m "Add the MI test measure, engine-led, chance from the model"`

---

## Task 7 : le bloc de résultat, coloré

**Files** : Create `src/console/resultat.py` · Modify `src/console/app.py` (assertions du smoke).

**Interfaces**
- Produit : `BlocResultat(QWidget)` avec `montrer(resultat: dict)`, et les attributs testables
  `verdict` (QLabel), `chiffres` (QLabel), `reserve` (QLabel), `details` (QCheckBox), `corps`.
- Produit : `couleur_du_verdict(texte: str) -> str` — rend `"#3fae5a"` / `"#b8860b"` / `"#e2603f"`.

🔴 **Les SEUILS viennent du MOTEUR.** Les verdicts disent déjà « FAIBLE », « UTILISABLE », « AU
NIVEAU DU REPÈRE » : la console **colore** le mot, elle ne recalcule **rien**. Une seconde table de
seuils côté écran peindrait un jour en vert ce que le moteur juge faible.

⚠️ **Inventaire AVANT de replier** : chaque phrase d'honnêteté du dépôt a été écrite après une
conclusion fausse réellement tirée. Replier n'est pas supprimer. Une seule survit en face : celle
qui changerait la décision qu'on s'apprête à prendre.

- [ ] **Étape 1 : l'autotest**, dans le smoke de `src/console/app.py` :

```python
    bloc = BlocResultat()
    bloc.montrer({"verdict": "FAIBLE — ré-essaie : saline Pz/PO7/Oz/PO8",
                  "justesse": 0.25, "hasard": 1 / 6, "n_essais": 90,
                  "honnetete": "ces chiffres sont HORS LIGNE…"})
    chk("e2603f" in bloc.verdict.styleSheet(),
        f"un verdict FAIBLE est peint en rouge par le MOT du moteur ({bloc.verdict.styleSheet()})")
    chk("25" in bloc.chiffres.text() and "17" in bloc.chiffres.text(),
        f"la mesure et son hasard sont sur la MÊME ligne, jamais un pourcentage seul "
        f"({bloc.chiffres.text()})")
    chk(not bloc.corps.isVisibleTo(bloc),
        "le détail est REPLIÉ par défaut")
    bloc.details.setChecked(True)
    chk("HORS LIGNE" in bloc.corps.text(),
        "…et la phrase d'honnêteté est RANGÉE, pas supprimée — elle revient d'un clic")
```

- [ ] **Étape 2** : échoue. **Étape 3** : implémenter. **Étape 4** : vert.
- [ ] **Étape 5 : DEUX mutations** — (a) une table de seuils locale (`if justesse < 0.3: rouge`) au
      lieu du mot du moteur : construire un résultat dont le mot dit « UTILISABLE » avec une
      justesse de 0,25, et vérifier qu'il reste **orange** ; (b) supprimer `honnetete` du corps →
      la quatrième assertion rougit.
- [ ] **Étape 6 : commit** — `git commit -m "A result block: coloured verdict, both figures, details folded"`

---

## Task 8 : fusionner les deux pages de protocole

**Files** : Create `src/console/protocole_page.py` · Delete `src/console/calib_page.py`,
`src/console/mesure_page.py` · Modify `src/console/app.py`.

Les deux pages consomment déjà le **même contrat public** (`state()` hérité, `PHASES_TERMINALES`
importé et non recopié) : c'est tout l'intérêt du socle, et la fusion ne fait que le constater.

**Ce que la page unique porte** : briefing · réglages (`ParamsForm`) · « Commencer » · l'écran
d'exécution (consigne en grand, décompte, avancement) · `BlocResultat` (tâche 7) · et, **seulement
si le protocole produit un modèle**, les boutons « Enregistrer le modèle » / « Refaire ».

- [ ] **Étape 1 : l'autotest** — une page construite sur une CALIBRATION montre les deux boutons ;
      construite sur une MESURE, elle ne les montre pas et n'écrit rien.
- [ ] **Étape 2** : échoue. **Étape 3** : fusionner. **Étape 4** : `python src/console/app.py --smoke`.
- [ ] **Étape 5 : mutation** — montrer « Enregistrer » sur une mesure → rouge.
- [ ] **Étape 6 : commit** — `git commit -m "Merge the calibration and measure pages: one protocol page"`

---

## Task 9 : la page de mode, en trois blocs

**Files** : Modify `src/console/mode_page.py` (réécriture), `src/console/app.py`.

🔴 **Le critère d'acceptation de tout le chantier** : « Tester » possède TOUTE la séquence —
démarrer le mode, ouvrir la fenêtre, collecter, fermer, conclure. Il ne doit plus exister d'ordre à
respecter, donc plus moyen de fixer dix minutes dans le vide.

- [ ] **Étape 1 : l'autotest**

```python
    page = console.pages["ssvep"]
    chk(page.bouton_tester is not None and page.bouton_marche is None
        and page.bouton_stimulus is None,
        "la page SSVEP a « Tester », et plus ni « Démarrer » ni « Lancer le stimulus »")
    journal.clear()
    page.bouton_tester.click()
    console.contact.bouton_lancer.click()
    noms = [e[0] for e in journal]
    chk(noms == ["commande", "fenetre"],
        f"UN clic soumet la mesure PUIS ouvre la fenêtre, dans cet ordre ({journal})")
    chk(console.pages["neuro"].bouton_tester is None
        and console.pages["neuro"].bouton_observer is not None,
        "…tandis qu'un mode sans vérité-terrain n'a pas de « Tester », mais un « Observer »")
```

- [ ] **Étape 2** : échoue. **Étape 3** : réécrire. **Étape 4** : vert.
- [ ] **Étape 5 : mutation** — inverser l'ordre (fenêtre avant commande) → la deuxième rougit.
- [ ] **Étape 6 : commit** — `git commit -m "A mode page in three blocks: Set, Train, Test"`

---

## Task 10 : le pic alpha se mesure depuis la page SSVEP

**Files** : Modify `src/console/mode_page.py`, `src/console/grid.py`, `src/console/app.py`.

Le contrôle alpha a **deux rôles** : une BARRIÈRE de séance, et un chercheur de paramètre. **Même
runtime, deux portes** — la tuile « Vérifier le casque » de la grille, et un bouton « Mesurer » à
côté du champ « Pic alpha ». Aucun second runtime, aucune logique recopiée.

- [ ] **Étape 1 : l'autotest** — le bouton « Mesurer » soumet `start_mesure` avec `id="alpha"`, et
      le résultat REMPLIT le champ sans qu'on retape rien ; la tuile s'appelle « Vérifier le
      casque » et porte toujours sa marque *BARRIÈRE*.
- [ ] **Étape 2** : échoue. **Étape 3** : implémenter. **Étape 4** : vert.
- [ ] **Étape 5 : mutation** — ne pas remplir le champ au retour → rouge.
- [ ] **Étape 6 : commit** — `git commit -m "Measure the alpha peak from the SSVEP page itself"`

---

## Task 11 : le vocabulaire et la documentation

**Files** : Modify `docs/qa.md`, `docs/recette.md`, `CLAUDE.md`, plus les libellés restants.

- [ ] **Étape 1** : remplacer partout — Calibrer → **Entraîner** · Taux d'émission SSVEP →
      **Tester** · Contrôle alpha → **Vérifier le casque**. « mesure », « calibration »,
      « marqueurs », « plancher de repos » **n'apparaissent plus à l'écran** (ils restent dans le
      code, où ils sont justes).
- [ ] **Étape 2** : réécrire le **bloc 1 de `docs/qa.md`** autour des trois gestes. Le point
      **1.6 bis disparaît** — ses six correctifs sont absorbés par la nouvelle forme.
- [ ] **Étape 3** : dans `CLAUDE.md`, ajouter la règle au même rang que la frontière :
      **une page de mode a trois gestes et pas un de plus ; « Tester » possède sa séquence entière.**
      Dire aussi POURQUOI — les dix minutes perdues du 2026-09-22.
- [ ] **Étape 4** : `python src/core/server.py --smoke` · `python src/console/app.py --smoke` ·
      les quatre `src/stimulus/*.py --smoke` · empreinte `data/` = **43**.
- [ ] **Étape 5 : commit** — `git commit -m "Rename the interface around what a student does"`

---

## Auto-revue du plan

**Couverture de la spec** — §3 forme de la page → tâches 9, 10 ; §4 « Tester » par mode →
tâches 2-6 ; §5 affichage → tâche 7 ; §6 vocabulaire → tâche 11 ; §7 grille → tâche 10 ;
§8 ce qui casse → tâches 8, 9 ; §9 risques → tâches 5 (ErrP), 3-6 (hasards), 7 (réserves),
3-6 (comparabilité, dite dans « Détails »). **Aucun trou.**

**Deux décisions de la spec §10, tranchées ici** :
- le nombre d'essais d'un test est un `Param` de type « choice » du bloc « Régler », défaut COURT,
  et le verdict affiche l'INTERVALLE DE CONFIANCE — le prix d'un test court est VISIBLE plutôt que
  caché (tâches 3-6) ;
- le contrôle de liaison RESTE en travers de « Tester », inchangé (tâche 9, étape 1 : le clic passe
  par `console.contact.bouton_lancer`). Son absence de porte de sortie est un constat déjà parké,
  et ce chantier ne le rouvre pas.

**Ordre** : 1 → 2 sont des fondations ; 3-6 sont **indépendantes entre elles** et peuvent être
revues séparément ; 7 → 8 → 9 → 10 sont l'interface, dans cet ordre ; 11 ferme.
