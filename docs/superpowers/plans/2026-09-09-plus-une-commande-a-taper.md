# Plus une seule commande à taper — plan d'implémentation

> **Pour les agents :** SOUS-COMPÉTENCE REQUISE — utiliser `superpowers:subagent-driven-development`
> (recommandé) ou `superpowers:executing-plans` pour exécuter ce plan tâche par tâche. Les étapes
> utilisent des cases à cocher (`- [ ]`).

**But :** à la fin, tout l'usage réel — contrôler le casque, mesurer, calibrer, décoder, regarder le
flux sortant, enregistrer une séance — se pilote depuis la console. Et la règle cesse d'être une
promesse : un test la vérifie.

**Architecture :** deux mesures (contrôle alpha, taux SSVEP) montent dans le moteur sous la forme
d'un `MesureRuntime` — un protocole minuté qui rend un **verdict** au lieu d'un modèle, partageant
le contrat public de `CalibrationRuntime`, donc affiché par la page générique de la console sans
une ligne de plus. La console gagne un écran de départ, une page « flux sortant » qui lit par LSL
comme un client, et la capacité de passer des options à ses fenêtres.

**Pile technique :** numpy, scipy, pylsl, pygame (fenêtres seulement), PySide6 (console seulement).

**Spec :** [docs/superpowers/specs/2026-09-09-plus-une-commande-a-taper-design.md](../specs/2026-09-09-plus-une-commande-a-taper-design.md) (commit `f12ff78`)

---

## Contraintes globales

Elles lient **toutes** les tâches, sans être répétées dans chacune.

- **Tout l'usage réel se pilote depuis l'interface.** Une capacité livrée sans chemin graphique est
  une tâche **INCOMPLÈTE**, pas une tâche à compléter plus tard. C'est la contrainte que ce
  chantier existe pour rendre vérifiable — elle a été redemandée cinq fois faute d'être écrite.
- `src/core/` n'importe **jamais** `research`, `console` ni `stimulus`, et ne contient ni pygame ni
  Qt. `src/stimulus/` n'importe **jamais** `research` ni `console`, et **n'ouvre jamais le casque**
  (`brainflow` et `core.acquisition` sont interdits par le scanner). Vérifié par
  `python src/core/server.py --smoke`.
- **La console est un CLIENT** : aucune logique que le moteur ne possède déjà, aucun catalogue
  recopié, **aucune écriture disque** — elle envoie des commandes.
- Code et commentaires **en français** ; `README.md`, `docs/markers.md` et les messages de commit
  **en anglais** ; `CLAUDE.md`, `docs/SPEC.md`, `docs/recette.md` en français.
- Tout testable **sans casque**. Un autotest **sort en 1** quand il échoue.
- **Aucun test n'écrit dans le vrai `data/`** — enregistrements EEG d'une personne identifiable sur
  un dépôt PUBLIC. `git status` ne prouve rien (`data/` est gitignoré) : vérifier par
  `core.config.empreinte_dossier` avant et après.
- ⚠️ **Un seul programme du projet à la fois** pendant les tests : les noms de flux LSL sont un
  contrat public.
- **La contrainte est le TEMPS.** ~40 Ko de diff au maximum par sous-agent.

---

## ⚠️ La règle vérifiable, affinée par l'inventaire

La spec §10 proposait « aucun programme lançable dans `src/` hors de la console et de ses
fenêtres ». **L'inventaire des 52 points d'entrée montre que c'est trop grossier** : `src/research/`
garde des outils d'analyse hors ligne parfaitement légitimes (`cvep_analyze.py`, `p300_analyze.py`,
`mi_compare.py`, `itr.py`, `viewing.py`, `calibrate.py`), qui ne touchent ni au casque ni à un
écran et ne s'adressent qu'au développeur.

Le critère retenu est **mécanique et colle exactement au périmètre donné par l'utilisateur** :

> **Rien dans `src/research/` ne doit ouvrir le casque ni afficher un stimulus.**
> Acquisition et stimulus = usage réel = dans l'application. Calcul sur des fichiers archivés =
> banc d'essai = libre.

Concrètement : aucun fichier de `src/research/` n'importe `core.acquisition`, `brainflow` ou
`pygame`. C'est la même forme que la frontière de `src/stimulus/`, donc le même scanner.

**Les SIX fichiers qui violent la règle aujourd'hui** — mesuré, pas supposé — et que ce chantier
traite :

| fichier | ce qu'il importe | devient |
|---|---|---|
| `research/alpha_check.py` | `brainflow` + `core.acquisition` | une mesure du moteur + une page (tâche 3) |
| `research/ssvep_guided.py` | `core.acquisition` + pygame | fenêtre (tâche 8) + mesure (tâche 9) |
| `research/ssvep_stimulus.py` | pygame | **déménage** en `stimulus/ssvep.py` (tâche 8) |
| `research/live_ssvep.py` | `core.acquisition` + pygame | **archivé** (tâche 10) — c'est un 7e écran de pilotage, oublié par le chantier précédent |
| `research/ssvep_analyze.py` | `core.acquisition` | l'import est retiré ou le fichier est archivé (tâche 10) — à trancher en le lisant |
| **`research/ui.py`** | pygame + `core.acquisition` | **déménage en `archive/ui.py`** (tâche 10) |

⚠️ **`research/ui.py` est le piège de ce chantier, et c'est le même qu'au précédent.** C'est la
machinerie pygame partagée — `App`, qui possède l'acquisition, et `Abort` — et **huit des dix
fichiers de `archive/` l'importent**. Elle ne sert plus qu'à eux : après ce chantier, plus rien de
vivant dans `research/` ne dessine ni n'acquiert. Elle appartient donc à `archive/`, avec les écrans
qu'elle porte. **L'ordre est contraint** : déménager d'abord, corriger les imports de l'archive,
faire passer ses dix `--smoke`, et seulement ensuite supprimer l'original. Le chantier précédent a
appris cette leçon en la vivant.

---

## Structure des fichiers

| fichier | responsabilité |
|---|---|
| `src/core/modes/mesure.py` | *(créé)* `MesureRuntime` : un protocole minuté qui rend un verdict |
| `src/core/modes/alpha.py` | *(créé)* `ControleAlpha` : yeux ouverts / yeux fermés, ratio, pic |
| `src/core/modes/ssvep_mesure.py` | *(créé)* `MesureSSVEP` : essais entrelacés, un essai = une décision |
| `src/core/server.py` | *(modifié)* `self.mesure`, refus d'une 2e activité, commandes d'enregistrement, **test d'inventaire** |
| `src/stimulus/ssvep.py` | *(déménagé + modifié)* ex-`research/ssvep_stimulus.py`, gagne `--guide` |
| `src/stimulus/registry.py` | *(modifié)* la commande porte des OPTIONS, pas seulement `--calibrer` |
| `src/console/fenetres.py` | *(modifié)* `LanceurFenetre` passe des options |
| `src/console/demarrage.py` | *(créé)* l'écran de départ : casque ou board de test |
| `src/console/flux_page.py` | *(créé)* « Ce que voit ton application » — lit par LSL, comme un client |
| `src/console/mesure_page.py` | *(créé)* le lancement et le verdict des deux mesures |
| `src/console/app.py` | *(modifié)* le câblage |
| `archive/ui.py` | *(déménagé)* la machinerie pygame partagée, que huit fichiers de `archive/` importent |
| `archive/live_ssvep.py`, `archive/alpha_check.py`, `archive/ssvep_guided.py` | *(créés)* les retraits |

---

## Task 1 : le test d'inventaire — ROUGE à la fin, et c'est le but

**Files:**
- Modify: `src/core/server.py` (`_FRONTIERE_RESEARCH_INTERDITS`, `_smoke_frontiere`), `CLAUDE.md`

**Interfaces:**
- Consumes: `_imports_interdits(source, nom_fichier, interdits, interdits_re, exacts)` et le helper
  `_scanner(racine_dir, etiquette, interdits, interdits_re, exacts)`, tous deux déjà dans
  `server.py` — la tâche 1 du chantier précédent les a paramétrés exactement pour ça.
- Produces: un scan de `src/research/` qui échoue sur `core.acquisition`, `brainflow` et `pygame`.

⚠️ **Cette tâche se termine sur un test ROUGE, volontairement.** Écrit en dernier, il constaterait
un état déjà propre et ne prouverait rien. Écrit en premier, il **nomme les six fichiers à
traiter**, et chaque tâche suivante le fait verdir d'un cran. La tâche 10 le rend vert.

- [ ] **Étape 1 : poser la règle, à côté de celle de `stimulus`**

```python
# Ce que `src/research/` n'a pas le droit d'importer. Le banc d'essai peut tout calculer sur des
# fichiers archivés — c'est son métier — mais il ne touche NI au casque NI à un écran : ces deux
# gestes-là sont de l'USAGE RÉEL, et l'usage réel se pilote depuis la console.
#
# ⚠️ Cette règle existe parce qu'elle a été demandée CINQ FOIS entre juillet et septembre 2026 sans
# jamais être écrite nulle part. Chaque chantier la redécouvrait par l'échec : on ajoutait un
# bouton, le chantier suivant repartait sans la règle, un nouveau trou apparaissait. Une contrainte
# tenue par la discipline n'est pas tenue.
_FRONTIERE_RESEARCH_INTERDITS = ("pygame", "brainflow")
_FRONTIERE_RESEARCH_MODULES_INTERDITS = ("core.acquisition",)
```

- [ ] **Étape 2 : le scan, avec un message qui PORTE la règle**

Dans `_smoke_frontiere`, après la partie 3 (`src/stimulus/`) :

```python
    # 4. `src/research/` : le banc d'essai ne touche ni au casque ni à un écran.
    racine_res = os.path.join(os.path.dirname(racine), "research")
    if os.path.isdir(racine_res):
        fautes_res, vus_res = _scanner(racine_res, "research", _FRONTIERE_RESEARCH_INTERDITS,
                                       "", _FRONTIERE_RESEARCH_MODULES_INTERDITS)
        for faute in fautes_res:
            print(f"[smoke-frontiere] ÉCHEC : {faute}")
            print("[smoke-frontiere]   → un utilisateur ne tape pas de commande. Si cette "
                  "capacité lui est destinée, elle doit avoir un chemin dans la console ; "
                  "sinon elle appartient à `archive/`.")
        fautes += fautes_res
        fichiers_vus += vus_res
```

- [ ] **Étape 3 : les extraits fabriqués, pour que la garde ne soit pas muette**

```python
    for source, attendu in (
            ("from core.acquisition import UnicornAcquisition\n", ["core.acquisition"]),
            ("import pygame\n", ["pygame"]),
            ("import brainflow\n", ["brainflow"]),
            ("from core.config import DATA_DIR\n", []),        # calculer reste libre
            ("import numpy as np\n", []),
            ("from stimulus.refresh import measure_refresh\n", [])):   # research -> stimulus, OK
        trouve = [p for _l, p in _imports_interdits(
            source, interdits=_FRONTIERE_RESEARCH_INTERDITS, interdits_re="",
            exacts=_FRONTIERE_RESEARCH_MODULES_INTERDITS)]
        chk(trouve == attendu,
            f"règle research — « {source.strip()} » -> {trouve or 'rien'} "
            f"(attendu {attendu or 'rien'})")
```

- [ ] **Étape 4 : lancer, et CONSTATER LE ROUGE**

```bash
python src/core/server.py --smoke
```

Attendu : **PROBLÈME**, en nommant **six** fichiers — `alpha_check.py`, `ssvep_guided.py`,
`ssvep_stimulus.py`, `live_ssvep.py`, `ssvep_analyze.py` et `ui.py`. **Colle cette liste dans ton
rapport : c'est la liste de travail des tâches 3, 8, 9 et 10.** Si tu en trouves d'autres, dis-le —
la liste ci-dessus a été mesurée le 2026-09-09, elle n'est pas devinée, mais elle peut avoir bougé.

- [ ] **Étape 5 : `CLAUDE.md`**

Ajouter la contrainte dans la section « Ce qu'il faut savoir en arrivant », au même rang que la
frontière entre paquets, avec sa raison en une phrase et le nom du test qui la vérifie.

- [ ] **Étape 6 : commit**

```bash
git add src/core/server.py CLAUDE.md
git commit -m "Make 'no command to type' a rule a test can fail on"
```

---

## Task 2 : `MesureRuntime` — un protocole qui rend un verdict

**Files:**
- Create: `src/core/modes/mesure.py`
- Modify: `src/core/server.py` (`self.mesure`, refus d'une seconde activité)

**Interfaces:**
- Consumes: `core.modes.calibration.PHASES`, `PHASES_TERMINALES` ; `engine.recent_window(seconds)` ;
  `engine.acq.fs`.
- Produces: `MesureRuntime(spec, params, engine)` avec `tick(engine, now)`, `cancel()`, `terminee`,
  `resultat`, `probleme`, `phase`, `instruction()`, `rappel()`, `duree_estimee_s()`, et le hook
  `_mesurer(enregistre, fs)`. Commandes moteur `start_mesure` / `cancel_mesure`.

**Lis en premier** `src/core/modes/calibration.py` : c'est le contrat public à répliquer **à
l'identique**, pour que `src/console/calib_page.py` — générique, pilotée par `snapshot()` — affiche
une mesure sans une ligne de plus. C'est le geste qui a fait tenir les quatre calibrations sur une
seule page.

**Ce qui diffère d'une calibration :** aucun modèle écrit, donc ni dossier candidat, ni
`save_calibration`. Le résultat est un verdict lu à l'écran, et **rien sur le disque**.

- [ ] **Étape 1 : écrire le test du refus d'une seconde activité**

⚠️ Même raison que le refus du vol de marqueurs livré au chantier précédent : **il n'y a qu'un
casque**, et deux protocoles minutés se voleraient les fenêtres de signal. Le refus doit tenir dans
les **deux sens**, et à la **soumission** comme dans la **boucle** — deux commandes soumises dans la
même fenêtre de sondage voient toutes deux un moteur vierge.

```python
    r = srv.submit("start_mesure", id="alpha")
    chk(r.get("accepted"), f"une mesure démarre sur un moteur libre ({r})")
    r2 = srv.submit("start_calibration", id="mi")
    chk(not r2.get("accepted") and "mesure" in (r2.get("reason") or "").lower(),
        f"…et une CALIBRATION est alors refusée, en nommant la mesure en cours ({r2})")
    srv.mesure = None
    srv.calibration = _CalibrationFactice()
    r3 = srv.submit("start_mesure", id="alpha")
    chk(not r3.get("accepted") and "calibration" in (r3.get("reason") or "").lower(),
        f"et RÉCIPROQUEMENT — c'est le sens qu'on oublie en croyant avoir fermé la porte ({r3})")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `python src/core/modes/mesure.py`.

- [ ] **Étape 3 : écrire `MesureRuntime`** — ligne du temps : `chauffe` → `essais` → `mesure` →
  `fini`/`annule`. Le hook `_mesurer` remplace `_entrainer`.

- [ ] **Étape 4 : prouver le rouge** — retirer le refus du sens 2 (le plus facile à oublier),
  relancer, constater le rouge, remettre. Colle les deux sorties.

- [ ] **Étape 5 : lancer les tests**

```bash
python src/core/modes/mesure.py
python src/core/modes/calibration.py
python src/core/server.py --smoke
```

- [ ] **Étape 6 : commit**

```bash
git add src/core/modes/mesure.py src/core/server.py
git commit -m "Let the engine play a protocol that returns a verdict, not a model"
```

---

## Task 3 : le contrôle alpha, de bout en bout

**Files:**
- Create: `src/core/modes/alpha.py`, `src/console/mesure_page.py`
- Modify: `src/console/app.py`, `src/console/grid.py`

**Interfaces:**
- Consumes: `MesureRuntime`.
- Produces: `ControleAlpha(MesureRuntime)` ; `_mesurer` rend
  `{"ratio": float, "pic_hz": float, "p_ouvert": float, "p_ferme": float, "verdict": str,
  "honnetete": str, "barriere_franchie": bool}`.

**Le protocole, repris tel quel de `src/research/alpha_check.py`** — ce sont les durées sous
lesquelles le repère « ratio > ~1,5 » a été observé : préparation **3 s**, **8 s yeux ouverts**,
préparation, **8 s yeux fermés**. Bande **8-12 Hz**, moyenne sur **PO7/Oz/PO8** (`OCCIPITAL`), pic
cherché entre **6 et 14 Hz**.

⚠️ **C'est une BARRIÈRE, et la page doit le dire comme telle.** Si l'alpha ne monte pas, aucun
autre test du niveau 2 ne veut rien dire. Le verdict est une phrase qui **arrête**, pas un chiffre
à interpréter.

⚠️ **Il ferme une boucle aujourd'hui manuelle.** La recette fait noter le pic à la main pour le
retaper dans « Pic alpha » de la page SSVEP. La page de résultat propose de l'appliquer — une
valeur recopiée entre deux écrans est exactement ce que ce dépôt a déjà vu diverger.

- [ ] **Étape 1 : écrire le test, sur un signal dont on connaît la réponse**

```python
    # Un signal SYNTHÉTIQUE : bruit blanc partout, plus une sinusoïde à 10,5 Hz sur les voies
    # occipitales pendant la SEULE phase « yeux fermés ». On connaît donc la réponse attendue.
    res = _mesurer_sur(ouvert=_bruit(), ferme=_bruit_plus_alpha(10.5, gain=3.0))
    chk(res["ratio"] > 1.5,
        f"l'alpha monte à la fermeture des yeux : ratio {res['ratio']:.2f} (repère > ~1,5)")
    chk(abs(res["pic_hz"] - 10.5) < 1.0,
        f"…et le pic est trouvé là où on l'a mis ({res['pic_hz']:.1f} Hz pour 10,5)")
    chk(res["barriere_franchie"] is True, "la barrière est franchie")

    # Et le cas qui ARRÊTE la séance : pas d'alpha du tout.
    plat = _mesurer_sur(ouvert=_bruit(), ferme=_bruit())
    chk(plat["barriere_franchie"] is False,
        f"sans montée d'alpha, la barrière n'est PAS franchie (ratio {plat['ratio']:.2f})")
    chk("arrête" in plat["verdict"].lower() or "électrodes" in plat["verdict"].lower(),
        f"…et le verdict dit d'ARRÊTER et quoi vérifier, il ne rend pas qu'un chiffre "
        f"({plat['verdict']})")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `python src/core/modes/alpha.py`.

- [ ] **Étape 3 : écrire la mesure**, puis `src/console/mesure_page.py` et sa tuile dans la grille.

- [ ] **Étape 4 : le test de la console**

```python
    page.appliquer_pic.click()
    chk(("set_params", {"id": "ssvep", "alpha_hz": 10.5}) in moteur_faux.commandes,
        "« Appliquer ce pic au SSVEP » envoie le RÉGLAGE au moteur — la valeur ne se recopie "
        "plus à la main d'un écran à l'autre")
```

- [ ] **Étape 5 : lancer les tests**

```bash
python src/core/modes/alpha.py
python src/core/modes/mesure.py
python src/console/app.py --smoke
python src/core/server.py --smoke
```

Le scan de la tâche 1 doit maintenant nommer **quatre** fichiers, plus `alpha_check.py`.

- [ ] **Étape 6 : commit**

```bash
git add src/core/modes/alpha.py src/console/ 
git commit -m "Bring the Berger check into the app, and close the loop it left open"
```

---

## Task 4 : la source, choisie à l'ouverture

**Files:**
- Create: `src/console/demarrage.py`
- Modify: `src/console/app.py`

**Interfaces:**
- Produces: `DialogueDemarrage` rendant `"unicorn"` ou `"synthetic"`, ou `None` si annulé ;
  `Console._ouvrir_source(source, ouvrir=None)` — `ouvrir` est injectable pour que le test simule
  un casque qui refuse de s'ouvrir sans en avoir un ; `Console.dernier_message` (str), ce que
  l'écran a dit en dernier.

⚠️ **Jamais de repli automatique.** Un basculement silencieux vers le board de test ferait
enregistrer une séance entière de faux signal en croyant tenir du vrai — et ce dépôt a déjà dû
corriger un écran qui laissait croire qu'un board de test était observé. Si le casque ne s'ouvre
pas : on le **dit**, et on repropose le choix.

- [ ] **Étape 1 : écrire les tests**

```python
    chk(console.banner.source.text() and "test" in console.banner.source.text().lower(),
        f"le bandeau annonce la source EN PERMANENCE ({console.banner.source.text()})")
    # Le casque refuse de s'ouvrir : on ne bascule PAS en douce.
    console._ouvrir_source("unicorn", ouvrir=_qui_leve)
    chk(console.engine is None and console.dernier_message,
        "un casque qui ne s'ouvre pas ne fait PAS basculer en synthétique : on le dit et on "
        "repropose. Une séance de faux signal prise pour du vrai ne se rattrape pas après coup")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `python src/console/app.py --smoke`.
- [ ] **Étape 3 : implémenter.** `--synthetic` reste accepté en ligne de commande (les smokes s'en
  servent) mais **saute le dialogue** : c'est un raccourci de développeur, pas le chemin normal.
- [ ] **Étape 4 : lancer les tests** — `python src/console/app.py --smoke`.
- [ ] **Étape 5 : commit**

```bash
git add src/console/
git commit -m "Ask which source to open, and never fall back in silence"
```

---

## Task 5 : les options de lancement, et le journal de séance

**Files:**
- Modify: `src/stimulus/registry.py`, `src/console/fenetres.py`, `src/console/mode_page.py`

**Interfaces:**
- Produces: `commande(stimulus_id, calibrer=False, options=())` — `options` est une séquence
  d'arguments déjà formés (`["--log", chemin]`).

⚠️ **La case « Journal de séance » est COCHÉE PAR DÉFAUT.** La recette 2.9 dit noir sur blanc
qu'une séance sans ce fichier **ne se dépouille pas** ; décochée par défaut, ce serait une séance
perdue par omission. **La fenêtre choisit elle-même son nom horodaté** — la console affiche où il
est, et n'écrit rien.

- [ ] **Étape 1 : écrire les tests**

```python
    argv = commande("cvep", calibrer=True, options=["--log", "s.jsonl"])
    chk(argv[-2:] == ["--log", "s.jsonl"] and "--calibrer" in argv,
        f"les options s'ajoutent à --calibrer, elles ne le remplacent pas ({argv[-3:]})")

    page = console.show_mode("cvep")
    chk(page.journal.isChecked(),
        "« Journal de séance » est COCHÉE par défaut : sans ce fichier la séance ne se dépouille "
        "pas, et une case décochée serait une séance perdue par omission")
    page.bouton_stimulus.click()
    chk("--log" in faux.argv,
        f"…et la case arrive VRAIMENT dans la commande lancée ({faux.argv[-3:]})")
    page.journal.setChecked(False)
    page.lanceur.arreter(); page.bouton_stimulus.click()
    chk("--log" not in faux.argv, "décochée, elle n'y arrive pas — la case n'est pas décorative")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `python src/stimulus/registry.py` puis
  `python src/console/app.py --smoke`.
- [ ] **Étape 3 : implémenter.**
- [ ] **Étape 4 : lancer les tests**

```bash
python src/stimulus/registry.py
python src/console/app.py --smoke
python src/stimulus/cvep.py --smoke
```

- [ ] **Étape 5 : commit**

```bash
git add src/stimulus/registry.py src/console/
git commit -m "Let the console hand its windows an option, starting with the session log"
```

---

## Task 6 : « Ce que voit ton application »

**Files:**
- Create: `src/console/flux_page.py`
- Modify: `src/console/app.py`, `src/console/grid.py`

**Interfaces:**
- Consumes: `pylsl.resolve_byprop`, `StreamInlet` ; `core.markers.flux_de_marqueurs_visibles` pour
  le patron de découverte.
- Produces: `FluxPage` avec `.rafraichir()`, `.choisir(nom)`, `.lignes` (les derniers échantillons).

⚠️ **Elle lit par LSL, comme un client — jamais l'état interne du moteur.** C'est la version
honnête : si le panneau montre des données, un vrai client en verrait aussi. Lire l'état interne
donnerait un panneau qui marche pendant que le réseau est muet, c'est-à-dire exactement la panne
qu'on veut voir.

- [ ] **Étape 1 : écrire le test**

```python
    page = FluxPage(console)
    page._inlet = _FauxInlet(voies=["target_index", "confidence"], echantillons=[[2.0, 0.81]])
    page.rafraichir()
    chk("target_index" in page.entetes.text() and "0.81" in page.lignes.toPlainText(),
        "le panneau montre les VOIES et les VALEURS du flux choisi")
    chk(not hasattr(page, "engine") and "engine" not in page.__dict__,
        "…et il ne tient AUCUNE référence vers le moteur : il lit le réseau comme un client, "
        "sinon il afficherait des données pendant que le réseau est muet")
    page._inlet = None
    page.rafraichir()
    chk(page.etat.text() and "aucun" in page.etat.text().lower(),
        f"aucun flux visible se DIT, plutôt qu'un panneau vide ({page.etat.text()})")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `python src/console/app.py --smoke`.
- [ ] **Étape 3 : implémenter**, en réutilisant l'extrait « Brancher un client » qui existe déjà :
  le panneau montre le flux, l'extrait montre le code qui le lit.
- [ ] **Étape 4 : lancer les tests** — `python src/console/app.py --smoke`.
- [ ] **Étape 5 : commit**

```bash
git add src/console/
git commit -m "Show the outgoing stream the way a client sees it, over LSL"
```

---

## Task 7 : enregistrer une séance

**Files:**
- Modify: `src/core/server.py`, `src/console/flux_page.py`

**Interfaces:**
- Produces: commandes `start_enregistrement` / `stop_enregistrement`, mêmes conventions d'acceptation
  que `save_calibration` (`{"accepted": bool, "reason": str}`) ;
  `snapshot()["enregistrement"]` = `{"actif": bool, "chemin": str, "lignes": int}` ou `None`.

⚠️ **C'est le MOTEUR qui écrit**, sur commande de la console — la console reste un client qui ne
touche jamais au disque, exactement comme pour `save_calibration`.

⚠️ **Le fichier ne va PAS dans `data/`.** Ce sont des verdicts de séance, pas des enregistrements
EEG ni des modèles : `data/` garde son autorité unique. Un dossier `seances/`, gitignoré, à côté.

- [ ] **Étape 1 : écrire les tests dans `server.py::_smoke`**

```python
    empreinte_avant = empreinte_dossier(DATA_DIR)
    srv.submit("start_enregistrement", stream="decoded_ssvep")
    _tourner(srv, secondes=2.0)
    r = srv.submit("stop_enregistrement")
    chk(r.get("accepted") and os.path.isfile(r["chemin"]),
        f"l'enregistrement produit un fichier ({r.get('chemin')})")
    chk(empreinte_dossier(DATA_DIR) == empreinte_avant,
        "…et data/ est INTACT : une séance n'est ni un modèle ni un enregistrement EEG, et data/ "
        "garde son autorité unique")
    chk(DATA_DIR not in r["chemin"],
        f"le fichier vit hors de data/ ({r['chemin']})")
    r2 = srv.submit("stop_enregistrement")
    chk(not r2.get("accepted") and r2.get("reason"),
        f"arrêter deux fois est refusé avec un motif ({r2})")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `python src/core/server.py --smoke`.
- [ ] **Étape 3 : implémenter**, côté moteur puis le bouton côté console.
- [ ] **Étape 4 : lancer les tests**

```bash
python src/core/server.py --smoke
python src/console/app.py --smoke
```

- [ ] **Étape 5 : commit**

```bash
git add src/core/server.py src/console/
git commit -m "Record a session from a button, with the engine holding the pen"
```

---

## Task 8 : la fenêtre SSVEP

**Files:**
- Create (déménagé) : `src/stimulus/ssvep.py` depuis `src/research/ssvep_stimulus.py`
- Modify: `src/stimulus/registry.py`, `src/research/ssvep_guided.py` (sa moitié rendu part)
- Delete: `src/research/ssvep_stimulus.py`

**Interfaces:**
- Produces: `python src/stimulus/ssvep.py [--windowed] [--refresh N] [--seconds N] [--guide]
  [--seed N] [--smoke]` ; en mode `--guide`, publie `calib_start` / `cue` / `calib_end` sur le flux
  de marqueurs, comme les trois autres fenêtres.

⚠️ **`research/ssvep_stimulus.py` EST déjà cette fenêtre** — 4 flèches clignotantes, `--windowed`,
`--refresh`, `--seconds`, `--smoke`, et elle n'ouvre pas le casque. La tâche est un **déménagement**
plus le mode guidé, pas une écriture.

⚠️ **L'horodatage se prend APRÈS `pygame.display.flip()`**, comme dans les trois sœurs. Le prendre
avant décale tous les marqueurs d'une frame, ce qui ne lève aucune exception.

- [ ] **Étape 1 : écrire le test du mode guidé**

```python
    marqueurs, cibles = _rejouer_guide(essais=12, seed=5)
    evenements = [m["event"] for m, _ts in marqueurs]
    chk(evenements[0] == "calib_start" and evenements[-1] == "calib_end",
        f"la séance s'ouvre et se ferme comme les trois autres fenêtres ({evenements[:2]}…)")
    cues = [m for m, _ts in marqueurs if m["event"] == "cue"]
    chk([c["target"] for c in cues] == cibles,
        "la cible annoncée est celle que l'écran a réellement DÉSIGNÉE")
    # L'ENTRELACEMENT : aucune cible deux fois de suite, et chacune vue autant de fois.
    suite = [c["target"] for c in cues]
    chk(all(a != b for a, b in zip(suite, suite[1:])),
        f"aucune cible deux fois de suite ({suite})")
    comptes = {t: suite.count(t) for t in set(suite)}
    chk(len(set(comptes.values())) == 1,
        f"…et chacune est vue le même nombre de fois ({comptes}) — un bloc contigu rendrait "
        f"« quelle cible » inséparable de « quand », et la dérive d'impédance se confondrait "
        f"avec l'effet cherché. Le c-VEP a payé ce confond 76 % de débit")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `python src/stimulus/ssvep.py --smoke`.
- [ ] **Étape 3 : déménager et implémenter le mode guidé.**
- [ ] **Étape 4 : lancer les tests**

```bash
python src/stimulus/ssvep.py --smoke
python src/stimulus/registry.py
python src/core/server.py --smoke
```

Le scan de la tâche 1 doit maintenant nommer **trois** fichiers.

- [ ] **Étape 5 : commit**

```bash
git add -A src/stimulus src/research
git commit -m "Move the SSVEP window where the console can launch it, and give it cues"
```

---

## Task 9 : la mesure SSVEP

**Files:**
- Create: `src/core/modes/ssvep_mesure.py`
- Modify: `src/console/mesure_page.py`, `src/research/ssvep_guided.py` (réduit à son analyse)

**Interfaces:**
- Consumes: `MesureRuntime`, `core.cca_decoder.CCADecoder`.
- Produces: `MesureSSVEP(MesureRuntime)` ; `_mesurer` rend
  `{"n_essais": int, "n_emis": int, "taux_emission": float, "justesse_emission": float,
  "ic_bas": float, "ic_haut": float, "verdict": str, "honnetete": str}`.

**Les trois invariants à ne pas perdre**, chacun écrit dans `ssvep_guided.py` avec sa raison :

1. **Chauffe avant tout** — l'Unicorn sort un offset DC énorme et dérivant après ouverture ;
   mesurer le plancher là-dedans revient à étalonner sur le transitoire d'un filtre.
2. **Essais entrelacés et tirés au sort** — invariant tenu côté fenêtre (tâche 8), à ne pas défaire
   ici.
3. **UN ESSAI = UNE DÉCISION** — les fenêtres du moteur se chevauchent (1,5 s toutes les 0,2 s) ;
   les compter comme indépendantes gonfle l'effectif d'un facteur **~7** et donne un intervalle de
   confiance faux. **On archive UNE fenêtre par essai, la dernière de la fixation.**

⚠️ **La phrase d'honnêteté doit porter les deux repères du 2026-07-27** — 100 % de justesse quand le
moteur émet, mais **44 % d'émission seulement** — et dire qu'un long silence entre deux verdicts
justes est le régime NORMAL de ce mode.

- [ ] **Étape 1 : écrire LE test de cette tâche**

```python
    # 24 essais, une décision par essai. Le moteur a vu ~7 fenêtres par essai : si l'effectif
    # annoncé les comptait, il vaudrait ~168 et l'intervalle de confiance serait faux d'un
    # facteur √7. C'est la faute que ce protocole existe pour éviter.
    res = _mesurer_sur_essais(n_essais=24, fenetres_par_essai=7)
    chk(res["n_essais"] == 24,
        f"l'effectif annoncé est le nombre d'ESSAIS ({res['n_essais']}), jamais celui des "
        f"fenêtres (168 ici) — les fenêtres se chevauchent, les compter gonfle l'effectif d'un "
        f"facteur ~7 et rétrécit l'intervalle de confiance d'autant")
    chk(res["ic_haut"] - res["ic_bas"] > 0.15,
        f"…et l'intervalle est large comme il doit l'être à n=24 "
        f"([{res['ic_bas']:.2f} ; {res['ic_haut']:.2f}])")
    chk("44" in res["honnetete"] and "100" in res["honnetete"],
        "la phrase d'honnêteté porte les DEUX repères — 100 % de justesse à l'émission, mais "
        "44 % d'émission : le second sans le premier fait passer un silence normal pour une panne")
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `python src/core/modes/ssvep_mesure.py`.
- [ ] **Étape 3 : implémenter**, et réduire `research/ssvep_guided.py` à sa moitié d'analyse.
- [ ] **Étape 4 : prouver le rouge** — faire compter les fenêtres au lieu des essais, relancer,
  constater, remettre. Colle les deux sorties.
- [ ] **Étape 5 : lancer les tests**

```bash
python src/core/modes/ssvep_mesure.py
python src/core/modes/mesure.py
python src/console/app.py --smoke
python src/core/server.py --smoke
```

- [ ] **Étape 6 : commit**

```bash
git add src/core/modes/ssvep_mesure.py src/console/ src/research/ssvep_guided.py
git commit -m "Measure the SSVEP rate from the app, one trial per decision"
```

---

## Task 10 : les retraits — le test de la tâche 1 passe au VERT

**Files:**
- Create: `archive/ui.py`, `archive/alpha_check.py`, `archive/ssvep_guided.py`,
  `archive/live_ssvep.py`
- Modify: les huit fichiers de `archive/` qui importent `research.ui`, `archive/README.md`,
  `src/research/ssvep_analyze.py`
- Delete: `src/research/ui.py` et les trois originaux archivés — **en dernier**

⚠️ **L'ORDRE, et il n'est pas négociable.** Huit des dix fichiers de `archive/` importent
`research.ui`. Supprimer avant de déménager casse des fichiers que personne ne relance jamais —
donc personne ne le verra avant le jour où on en a besoin, en séance. **Déménage `ui.py` d'abord,
corrige les imports, fais passer les dix `--smoke` de `archive/`, et seulement ensuite touche au
reste.**

⚠️ **`live_ssvep.py` est un SEPTIÈME écran de pilotage**, oublié par le chantier précédent : il
ouvre le casque et affiche des flèches clignotantes avec le ρ en direct. Même traitement que les
six autres — archivé, gardé lançable, non maintenu.

⚠️ **`ssvep_analyze.py` importe `core.acquisition` alors que sa docstring annonce « sans casque ».**
Le lire avant de trancher : si l'import sert un mode d'enregistrement live, le fichier est un écran
de pilotage et part dans `archive/` ; s'il ne sert qu'une constante, retirer l'import suffit et le
fichier reste au banc d'essai. **Dis lequel dans ton rapport.**

- [ ] **Étape 1 : déménager `research/ui.py` en `archive/ui.py`**, corriger les imports des huit
  fichiers de `archive/` qui s'en servent, puis lancer **les dix `--smoke` de `archive/`**. Ils
  doivent tous être verts **avant** de toucher à autre chose.
- [ ] **Étape 1 bis : archiver les trois autres**, un fichier à la fois, chacun autonome et gardant
  son `--smoke`.
- [ ] **Étape 2 : `archive/README.md`** — trois lignes de plus, sur le modèle des dix existantes.
- [ ] **Étape 3 : LE contrôle de cette tâche**

```bash
python src/core/server.py --smoke
```

Attendu : **`[smoke-frontiere] VERDICT : OK`**. Le test écrit à la tâche 1, rouge sur six fichiers,
est maintenant vert. **Colle la ligne dans ton rapport.**

- [ ] **Étape 4 : les smokes de l'archive** — les dix existants plus les trois nouveaux.
- [ ] **Étape 5 : commit**

```bash
git add -A src/research archive
git commit -m "Retire the last programs a user would have had to type"
```

---

## Task 11 : la documentation

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `docs/recette.md`, `docs/SPEC.md`

⚠️ **Mesuré sur ce dépôt : 0 régression dans 2000 lignes de code relu, contre 1 régression et 8
faussetés dans la doc écrite sans relecteur.** Une phrase de documentation est une assertion :
**lance chaque commande que tu cites.**

- [ ] **Étape 1 : `CLAUDE.md`** — la section « Commandes utiles » perd les cinq entrées retirées.
  ⚠️ La contrainte posée à la tâche 1 y est déjà : vérifier qu'elle dit vrai après les dix tâches.
- [ ] **Étape 2 : `docs/recette.md`** — le test **2.1 devient un clic** (page Contrôle alpha), le
  **2.2** aussi (page Mesure SSVEP). ⚠️ **Ne touche à AUCUN repère chiffré** : 100 %/44 %,
  46 %/71 %, AUC 0,776, 0,71, 40 % à trois classes. Ce chantier n'a rien mesuré.
- [ ] **Étape 3 : `README.md`** et `docs/SPEC.md`.
- [ ] **Étape 4 : la phrase qui doit survivre** — *rien de ce chantier n'a vu un cerveau*, et
  quatre modes sur six n'ont jamais été décodés au casque à travers le moteur. Une réécriture fait
  disparaître ce genre de phrase sans intention.
- [ ] **Étape 5 : lancer TOUTES les commandes citées**, et coller la liste avec son résultat.
- [ ] **Étape 6 : commit**

```bash
git add -A
git commit -m "Document an application you drive, not a list of commands you type"
```

---

## Le chantier est fini à la tâche 11

Ce qui reste **dehors** : la séance casque ; le dépouillement automatique du test 2.9 ; et les
**huit constats parqués** de la revue précédente, dont deux mordront en séance — la console prend
`accepted` pour « la séance a démarré », et les refus de la grille ne vont encore que dans le
terminal.
