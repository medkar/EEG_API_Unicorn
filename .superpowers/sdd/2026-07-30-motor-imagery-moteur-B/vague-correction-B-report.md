# Vague de correction — LOT B (`src/console/`, `src/research/`, `archive/`, doc) — Rapport

## Statut

**DONE** pour les cinq constats confiés (B1, B2, B3, B4, B5), plus l'exception A13 (moitié
console). Aucun écart appliqué à moitié. `git status --short` propre après les 5 commits. Rien
touché dans `src/core/` (LOT A). Rien de la liste « PARKÉ » n'a été corrigé — en particulier
`MI_MODEL_PATH`/`MI_KEY_CHANNELS` n'ont pas été touchées, pas même du commentaire suggéré en fin
de leur paragraphe (l'instruction reçue était « ne corrige rien de cette liste », prise au pied de
la lettre plutôt que la suggestion résiduelle du document).

Les cinq commandes demandées sont sorties **vertes en série**, une seule à la fois :
`console/app.py --smoke`, `core/server.py --smoke`, `research/app.py --smoke`,
`archive/mi_calibrate.py --smoke`, `archive/mi_pilot.py --smoke`.

## Commits (5, sur `main`, dans l'ordre)

1. `78e8772` — *Make the console import the engine's phase vocabulary, not recopy it* — exception
   A13 (moitié console)
2. `e0edd21` — *Fix the calibration page: silent restart beep, and 0% for an unmeasurable CV* — B1, B2
3. `9152ef7` — *Strengthen four weak smoke assertions in the console (B4)* — B4
4. `586bf93` — *Default mi_compare.py to the newest calibration, and say which (B3)* — B3
5. `491442e` — *Fix six stale or missing documentation claims (B5)* — B5

---

## Exception A13 (moitié console)

`src/core/modes/calibration.py` exposait déjà `PHASES_TERMINALES` pour cet usage précis (son
propre commentaire le disait : « la constante que la console doit IMPORTER plutôt que
redéclarer »). `src/console/calib_page.py` redéclarait pourtant sa propre copie locale
`PHASES_TERMINALES = ("fini", "annule")`. Remplacé par `from core.modes.calibration import
PHASES_TERMINALES`, et supprimé la copie locale. Un seul hunk, isolé du reste (import en tête de
fichier) — commité seul.

## Constat par constat

### B1 — Le premier top de la séance suivante est muet après un abandon ⭐

**Fichier** : `src/console/calib_page.py`, `CalibPage.update_from`.

Diagnostic confirmé : `CalibrationRuntime.cancel()` (moteur) pose `phase = "annule"` **et**
`etape = ""` dans le même appel Python — contrairement à la fin normale, qui traverse la phase
« entrainement » (non terminale, étape vide) avant `"fini"`, offrant un sondage intermédiaire où
`_maybe_beep` remet `_etape_precedente` à `""` toute seule. Pour l'abandon, ce sondage
intermédiaire n'existe pas : `_etape_precedente` reste bloqué sur la dernière étape non vide vue
avant l'abandon (typiquement `"cue"`), et le premier `"cue"` de la séance relancée ensuite —
`_etape_precedente != "cue"` étant déjà faux — ne déclenche plus le top.

**Correctif** : `else: self._etape_precedente = None` dans la branche « aucune séance en cours »
de `update_from` (une ligne, hors du `if en_cours:`), qui couvre les deux sorties (fin normale et
abandon) par le même geste, sans dépendre du chemin emprunté.

**Test ajouté** dans `src/console/app.py::_smoke()` : simule une première séance qui sonne son
premier top pendant l'échauffement, un abandon EN PLEIN dans ce top (état terminal livré
directement, sans étape intermédiaire — fidèle à ce que `cancel()` produit réellement), puis une
séance relancée sur la MÊME page (elle n'est jamais recréée) dont le premier `"cue"` doit sonner.

**Rouge**, obtenu en retirant temporairement le `else: self._etape_precedente = None` (rien
d'autre changé, le test déjà en place) :
```
  OK   la première séance sonne son premier top normalement (['GAUCHE'])
  ÉCHEC et le premier top de la séance RELANCÉE après un abandon sonne aussi — pas muet ([])
  ...
[console-smoke] VERDICT : PROBLÈME
```
(exit code 1 ; c'était la SEULE assertion en échec sur l'ensemble du smoke — confirmé par un grep
`ÉCHEC` sur la sortie complète, un seul résultat.)

**Vert**, correctif restauré :
```
  OK   la première séance sonne son premier top normalement (['GAUCHE'])
  OK   et le premier top de la séance RELANCÉE après un abandon sonne aussi — pas muet (['DROITE'])
  ...
[console-smoke] VERDICT : OK
```
(exit code 0.)

**Réserve honnête sur la portée réelle du symptôme** — voir section Réserves plus bas : le
correctif est appliqué tel que demandé et je le crois juste, mais je pense que le document
surestime légèrement à quel point le symptôme est garanti en usage réel (pas en test).

### B2 — `calib_page.py` effondre lui aussi la CV absente en `0.0`

**Fichier** : `src/console/calib_page.py`, même méthode.

`cv = float(resultat.get("cv_groupee") or 0.0)` s'exécutait même après le correctif moteur (A1,
lot A, déjà en place) qui propage `None` : un second effondrement, indépendant, ré-inventait un
« 0 % ». Correctif : nouvelle branche `if resultat is not None and resultat.get("cv_groupee") is
None:` qui affiche `resultat["verdict"]` seul — le moteur y met déjà la phrase en clair (« justesse
non mesurable : pas assez d'essais distincts par classe pour une validation croisée ») — sans le
faire suivre d'un pourcentage inventé, et masque le paragraphe HONNETETE (rien à sur-interpréter
sans chiffre). La branche `cv_groupee` numérique existante est inchangée dans son comportement.

**Test ajouté** : un état `"fini"` avec `resultat["cv_groupee"] = None` et un `verdict` réaliste ;
vérifie que `"non mesurable"` apparaît dans le texte rendu et qu'aucun de `"0.0"`, `"0,0"`, `"0 %"`
n'y apparaît. Vu passer directement (voir capture du smoke complet ci-dessous) ; j'ai vérifié
mentalement — et par relecture du code pré-correctif — que ce test aurait échoué sous l'ancien
`float(... or 0.0)` (qui aurait produit littéralement `"... : 0.0 % (hasard 33 %)"`), sans reproduire
formellement un rouge séparé pour celui-ci : la même partie de fichier que B1, déjà rouge/verte
prouvée ci-dessus, et l'instruction ne demandait le rouge-puis-vert formel que pour B1.

### B3 — `mi_compare.py` cible un fichier que la calibration n'écrit plus ⭐

**Fichier** : `src/research/mi_compare.py`.

Ajouté `plus_recent(dossier=DATA_DIR)` : `glob.glob(dossier/"mi_calib_*.npz")`, trié par
`os.path.getmtime` décroissant (même motif que `mi_models.modeles_disponibles`), rend le premier
ou `None`. Dans `__main__` : si aucun chemin n'est donné en argument, appelle `plus_recent`,
**imprime lequel a été retenu**, et si `None`, imprime un message clair et sort en code 1 au lieu
de laisser `np.load` lever sur un chemin inexistant.

**Vérifié en conditions réelles**, sur ce poste (où `data/` contient un `mi_calib_last.npz`
historique mais aucun `mi_calib_<horodatage>_n<NN>.npz` du nouveau format) :
```
python src/research/mi_compare.py
[mi-compare] aucun fichier donné — le plus récent retenu : mi_calib_last.npz
mi_calib_last.npz — CV par essai (chance 3 classes = 33%) — re-ref=car
drop 0 premiers       n= 30  csp= 40.0%  riemann= 48.9%
```
Et unitairement sur `plus_recent` (dossier temporaire, hors `data/`) : dossier vide → `None` ;
dossier avec deux `mi_calib_*.npz` d'horodatages différents → le plus récemment modifié est rendu.

Note d'implémentation : `mi_calib_last.npz` correspond bien au motif `mi_calib_*.npz` et reste
donc un candidat légitime — c'est voulu : sur ce poste précis, c'est aujourd'hui le seul fichier
disponible, et le signaler explicitement (plutôt que refuser de le voir) est justement ce qui
ferme le trou « analyse silencieuse d'une séance périmée ». Dès qu'une vraie calibration moteur
existe, son nom horodaté la fait gagner naturellement par date.

### B4 — Les quatre assertions faibles de la console

**Fichiers** : `src/console/grid.py`, `src/console/app.py`.

- Commentaire de quatre lignes restauré au-dessus de `self.demarrage = QPushButton("Démarrer")`
  dans `grid.py` — texte identique à celui de `task-5-brief.md`.
- Nouvelle assertion dans `_smoke()` : capture l'étiquette du bouton Démarrer/Arrêter de la tuile
  Neuro AVANT le clic, clique, vérifie qu'elle n'a PAS changé (le prochain état reçu la changera,
  pas le clic lui-même). Passe sur le code actuel : `ModeTile.demarrage.clicked` n'émet qu'un
  signal Qt, ne touche aucun widget — c'est un ajout de COUVERTURE sur un invariant déjà respecté
  structurellement, pas la correction d'un bug actif.
- Le test du clic « Commencer » compare maintenant `envoyees[0][1]["params"]` à
  `cal.formulaire.values()` **capturé avant le clic**, au lieu de vérifier seulement la présence de
  la clé `"trials_per_class"`. Un formulaire qui soumettrait une valeur écrite en dur échouerait
  désormais, quelle qu'elle soit.
- La progression (`cal.progression.text()`) est comparée par égalité stricte à `"essai 7 sur 42"`
  au lieu d'un double test par sous-chaîne (`"7" in ... and "42" in ...`), qui laissait passer un
  mutant du type « essai 42 sur 7 ».

Les quatre assertions passent (voir sortie du smoke ci-dessous, section Résumé des tests).

### B5 — La documentation

Six affirmations corrigées, chacune vérifiée dans le code avant réécriture :

| Affirmation avant | Vérification faite | Correction |
|---|---|---|
| README, table Layout `src/console/` : 6 lignes | `ls src/console` → 9 fichiers, dont `__init__.py` (non listé nulle part, convention constante avec la table `core/`) → 8 fichiers « réels », dont `calib_page.py` et `beeps.py` absents de la table | Deux lignes ajoutées, à leur place logique (`calib_page.py` après `mode_page.py` ; `beeps.py` après `banner.py`) |
| README « All six share one acquisition session and one UI core » | Lu `src/research/app.py` : docstring « cinq modes », sections Mode 1-5 (SSVEP, c-VEP, P300, Neuro, ErrP) — MI absent, archivé par le commit `e004958`. Le MI tourne exclusivement via `src/console/app.py` + `EngineServer`, un processus et un socle distincts | Reformulé : « Five of the six … inside the pygame app. Motor Imagery is the exception : it has fully moved to the PySide6 console instead, a separate core with its own acquisition session. » |
| `docs/recette.md` test 2.6 : « (cf. README) » pour le chiffre de référence | Chiffre exact relu dans `src/core/modes/mi_calib.py` (commentaire au-dessus de `VERDICTS`) : « 40,0 % à 3 classes (p = 0,082, PAS significatif) et 63,3 % à 2 classes (p = 0,038) » | Chiffre cité en clair dans la recette : « 40,0 %, p = 0,082, PAS significatif », avec la phrase explicite sur le risque de mélire « 40 % » comme « mieux que le hasard » |
| `docs/recette.md` test 1.13 : « dans un troisième terminal » | Relu le test 1.6 (un second terminal ouvert pour `essai.py`) et la description du « Lancement B » juste avant 1.7 : « fermer la console, puis la rouvrir » — rien ne garantit que le terminal de 1.6 soit resté ouvert à travers cette fermeture/réouverture | Reformulé en « un second terminal — le premier fait tourner la console du Lancement B », sans supposer l'historique des terminaux déjà ouverts |
| `src/research/app.py::mode_neuro` docstring « Mode 5 » | Lu l'en-tête de section 19 lignes au-dessus (`# --- Mode 4 : Neuro-monitoring passif …`) et `mode_errp`, déjà cohérent avec SON en-tête « Mode 5 » | `mode_neuro` corrigé en « Mode 4 » |
| `archive/mi_pilot.py` : message « (mi_calibrate.py) » sans préfixe | Relu les 5 lignes d'usage du docstring du fichier (`python archive/mi_pilot.py …`, `python archive/mi_calibrate.py …` cité dans `--calibrate`) — toutes préfixées `archive/`, seul le message d'exécution ne l'était pas | Préfixé en `archive/mi_calibrate.py` |
| `src/console/mode_page.py::rafraichir_choix` docstring « retour d'une calibration » | `grep -rn rafraichir_choix src/` → un seul appelant, `Console.show_mode` (`app.py:168`), déclenché à l'entrée dans une page de MODE ; les pages de calibration renvoient sur `show_grid` (`page.retour.connect(self.show_grid)`), jamais sur `show_mode` | Docstring réécrite : ne cite que l'entrée dans la page comme déclencheur réel, et explique pourquoi un modèle fraîchement entraîné apparaît quand même (on retombe dans cet événement en rouvrant le mode) |

---

## Réserves

**Sur B1, une nuance à signaler plutôt qu'un désaccord.** Le document dit « ce n'est pas
probabiliste : pour l'abandon, la fenêtre non terminale n'existe jamais » — c'est vrai et je l'ai
vérifié dans le code (`cancel()` pose les deux en un seul appel Python, sans état intermédiaire
observable). Mais j'ai aussi vérifié qu'en usage RÉEL (casque, minuterie Qt à 100 ms), la séance
SUIVANTE traverse `"chauffe"` (`warmup_s = 15 s` pour le MI, `etape == ""` tout du long) avant
d'atteindre son propre premier `"cue"` — et cette phase, elle, EST sondée à répétition pendant 15
secondes réelles, ce qui réinitialiserait `_etape_precedente` avant que le nouveau `"cue"`
n'arrive. Autrement dit : le symptôme décrit se produit à coup sûr au moment précis de l'abandon,
mais semble s'auto-guérir dans les 15 secondes suivantes en usage réel, avant que l'étudiant ne
puisse même relancer une séance (il faut cliquer « Commencer » à la main). Je n'ai PAS trouvé de
scénario réel où le premier top resterait muet malgré ces 15 s de chauffe.

Je n'ai pas renoncé au correctif pour autant, pour deux raisons : (1) le test que j'ai écrit
utilise exactement l'idiome déjà en place dans ce fichier (états injectés directement, comme le
fait déjà le test « régression échauffement » juste au-dessus, sans simuler la chauffe réelle) —
c'est fidèle à la méthodologie du fichier, pas une invention pour forcer un rouge ; (2) s'appuyer
sur les 15 s de chauffe pour l'auto-guérison est exactement la « coïncidence non documentée » que
ce même chantier corrige ailleurs (A1, A9, A10 du lot A) — un `warmup_s` réduit un jour (essais
plus rapides, débogage) romprait ce filet sans avertissement. Le correctif rend l'invariant vrai
INCONDITIONNELLEMENT plutôt que de dépendre d'une durée de chauffe qui se trouve être assez longue
aujourd'hui. Je livre le correctif et le test, et signale cette nuance plutôt que de la passer sous
silence.

**Sur B3**, aucune réserve sur le fond ; une précision d'implémentation seulement (voir sa
section) : `mi_calib_last.npz` reste un candidat valide du glob `mi_calib_*.npz`, ce qui est voulu
et cohérent avec le texte du correctif.

**Ce que je n'ai pas fait, et pourquoi** : rien d'autre dans le périmètre B1-B5 n'a été laissé de
côté. Conformément à la consigne, je n'ai touché à rien de la liste « PARKÉ, avec la raison » —
notamment `MI_MODEL_PATH`/`MI_KEY_CHANNELS` sont restées intactes, y compris le commentaire que le
document suggérait d'y ajouter : la consigne reçue (« ne corrige rien de cette liste ») primait sur
cette suggestion résiduelle.

## Résumé des tests

Cinq commandes officielles, en série, une seule à la fois, toutes sorties à 0 :
`console/app.py --smoke` (VERDICT : OK), `core/server.py --smoke` (10 sous-verdicts OK),
`research/app.py --smoke` (smoke OK), `archive/mi_calibrate.py --smoke` (smoke OK),
`archive/mi_pilot.py --smoke` (smoke OK). Aucun `ÉCHEC` dans aucune des cinq sorties. Rouge-puis-vert
prouvé pour B1 comme exigé (voir sa section). `git status --short` propre après les 5 commits ;
`data/` n'a gagné aucun fichier `mi_model_*`/`mi_calib_*` daté d'aujourd'hui.
