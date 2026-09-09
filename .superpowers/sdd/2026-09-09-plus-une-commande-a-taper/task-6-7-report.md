# Tâches 6 et 7 — « Ce que voit ton application » + enregistrer une séance

**Statut : terminées, vertes.**
Commits `0bbf656` (T6) puis `5634cec` (T7), sur `main`.

---

## Ce qui est livré

### T6 — `src/console/flux_page.py` (nouveau, 525 lignes)

Une page qui **résout les flux LSL du réseau, en ouvre un, et montre ses voies et ses valeurs
défiler**. Elle lit *comme un client* : `resolve_streams` puis `StreamInlet`, jamais
`engine.snapshot()`.

- Découverte : le patron de `core/markers.flux_de_marqueurs_visibles`, avec ses raisons reprises —
  fusion des doublons (LSL répond une fois **par interface réseau**), tri stable, **ne lève
  jamais**. Les flux des voisins sont montrés eux aussi (une application voit tout le réseau), les
  nôtres en tête.
- `recover=False` sur l'inlet, comme `MarkerInlet`, pour la raison qu'il a mesurée : un émetteur
  disparu doit **lever**, pas se taire pour toujours. La page lâche alors l'inlet et le dit.
- L'extrait « Brancher un client » **n'est pas recopié** : la page renvoie vers celui de
  `mode_page.py`, généré par `contract.client_snippet`.
- Entrée par un bouton en bas de la grille (`grid.ouvrir_flux`). Quitter la page **lâche l'inlet**,
  via `stack.currentChanged` — un seul endroit, quel que soit le chemin de sortie.

### T7 — `start_enregistrement` / `stop_enregistrement`

Le moteur écrit un JSONL dans `seances/`, **une ligne par décision publiée**, horodatée dans
l'horloge LSL. La console envoie deux commandes et lit `snapshot()["enregistrement"]` ; elle ne
compose aucun chemin et n'ouvre aucun fichier.

Format : `header` (flux complet, mode, voies, réglages en vigueur, `publie`, `fs_hz`, `instance`)
→ N × `verdict` (`{"t": <lsl>, "phase": …, "sortie": {…}}`) → `fin` (`{"verdicts": N}`).

La sortie du mode est écrite **sous ses propres clés**, jamais aplatie en colonnes : un mode qui
gagnerait un champ ne décalerait rien, et un dépouillement écrit contre ce fichier lit des noms,
pas des positions.

---

## Les trois arbitrages du brief, tenus

1. **Le couple avec le journal de la fenêtre.** Les deux fichiers portent `local_clock()` et vivent
   dans le **même dossier** : `stimulus/cvep.py` ne recompose plus son chemin, il importe
   `config.SEANCES_DIR` (3 lignes changées). Deux façons de nommer le même dossier auraient fini
   par diverger, et ce jour-là les deux moitiés d'une séance ne seraient plus côte à côte. Le
   **dépouillement lui-même reste DEHORS** — rien n'a été écrit qui joigne les deux fichiers.
2. **Aucun vrai flux LSL dans le smoke.** Deux coutures injectables sur `FluxPage`
   (`decouvrir`, `ouvrir`), du même genre que `fabrique_fenetre` / `horloge` / `_ouvrir_source`.
   ⚠️ Elles ont été ajoutées **après** un premier jet qui n'en avait pas : le smoke résolvait pour
   de vrai et **trouvait les 5 flux du moteur qu'un autre bloc du même smoke fait tourner**. Le
   test était donc dépendant de l'ordre d'exécution et du poste.
3. **`empreinte_dossier`** : voir ci-dessous.

---

## Preuve que `data/` n'a pas bougé

Empreinte du **vrai** `data/`, `sha256` de `{nom: (taille, mtime)}` :

| moment | fichiers | sha256 |
|---|---|---|
| avant toute la batterie | 43 | `42120328ed4df50265e14522eb61c5035423bbb52064f33b14d3293dfae8083d` |
| après toute la batterie | 43 | `42120328ed4df50265e14522eb61c5035423bbb52064f33b14d3293dfae8083d` |

`seances/` (le vrai) : **0 fichier** avant et après — les tests écrivent dans un `tempfile.mkdtemp`
via le nouveau paramètre `seances_dir`.

Et le smoke le vérifie lui-même : `_smoke_enregistrement` prend `empreinte_dossier(DATA_DIR)` de
part et d'autre d'une séance réellement enregistrée.

---

## Tests

```
python src/core/server.py --smoke      EXIT=1  -> [smoke-frontiere] SEUL rouge (5 fichiers de
                                                  research/, 10 violations : live_ssvep,
                                                  ssvep_analyze, ssvep_guided, ssvep_stimulus, ui)
                                                  Tous les autres VERDICT : OK, dont le nouveau
                                                  [smoke-enregistrement] VERDICT : OK
python src/console/app.py --smoke      EXIT=0  (lancé 2 fois)
python src/stimulus/cvep.py --smoke    EXIT=0  (touché : SEANCES_DIR)
python src/stimulus/registry.py        EXIT=0
python src/core/markers.py             EXIT=0  (touché : DECOUVERTE_TIMEOUT_S importée)
python src/core/modes/mesure.py        EXIT=0
```

Compté sur la dernière exécution : **10 lignes `ÉCHEC`, 10 sous `[smoke-frontiere]`, 0 ailleurs.**
`_smoke_enregistrement` lancé 3 fois de suite : vert 3 fois (il fait tourner un vrai moteur
synthétique ~7 s, c'est le seul de mes tests qui dépende d'un timing).

### Les deux rouges prouvés par mutation

| mutation | ce qui rougit |
|---|---|
| `FluxPage.update_from` remplit le panneau depuis `state["modes_state"]` | **1 seule** assertion : « un état complet du moteur ne remplit RIEN sans inlet » |
| `_Enregistrement.noter` écrit à chaque tour (identité retirée) | **2** assertions : « deux tours sans NOUVELLE décision = UNE ligne » et sa jumelle |

Les deux ont été remises en état et la batterie relancée verte.

---

## Ce que j'ai trouvé en écrivant les tests

🔴 **L'accusé de `start_enregistrement` promettait un chemin de fichier qui pouvait ne jamais
exister.** Premier jet : `submit` calculait le nom du fichier pour le rendre tout de suite (l'écran
doit dire où ça écrit). Or deux commandes soumises dans la **même fenêtre de sondage** voient
toutes les deux `self.enregistrement is None` — donc les deux sont acceptées, et la boucle refuse
la seconde. Le second accusé annonçait donc un fichier que la boucle venait de refuser de créer.
Mesuré : `accepted: True` avec un `chemin` inexistant.

Correctif : **le nom du fichier est décidé par la BOUCLE**, et l'écran le lit dans
`snapshot()["enregistrement"]["chemin"]` — le seul endroit écrit par le fil qui écrit le fichier.
`submit` ne promet plus rien qu'il ne puisse tenir. C'est une instance de plus du constat parqué de
la revue précédente (« la console prend `accepted` pour “la séance a démarré” »), traitée à la
source plutôt qu'à l'écran.

---

## Deux règles que j'ai dû poser, et qui méritent d'être relues

1. **Une ligne par décision PUBLIÉE, pas par tour de boucle.** Le critère est l'**identité** de
   l'objet rendu par `runtime.output()` : les six modes reconstruisent leur dict à chaque
   publication, donc un tour muet rend le même objet. Sans ça, un mode qui n'émet que **44 % du
   temps** — le régime normal du SSVEP, mesuré le 2026-07-27 — se relirait à 100 %, et le fichier
   mentirait sur la seule grandeur qu'on vient y chercher.
   ⚠️ **Cette règle repose sur une propriété des modes, pas sur un contrat déclaré.** Le mode #7
   qui muterait son dict en place perdrait des lignes **en silence**. C'est écrit dans la docstring
   de `_Enregistrement` et pinné par un runtime factice dans le smoke — mais ce n'est pas une
   garantie structurelle, et c'est ma principale réserve.

2. **On refuse d'enregistrer un mode qui n'est pas démarré.** Un fichier vide se relit après coup
   comme une séance ratée, pas comme un mode qu'on a oublié de lancer. Le refus est donc explicite
   et nomme le mode.

---

## Réserves

- 🟡 **La règle « identité = nouvelle décision » n'est pas structurelle** (ci-dessus, point 1).
  Un `ModeRuntime.publications` incrémenté dans la classe de base serait la version étanche ;
  ça touche les six modes et sortait du périmètre.
- 🟡 **Rien de tout ceci n'a vu un cerveau.** Le fichier de séance a été produit contre un board
  synthétique. Ce qu'un test sans casque peut prouver de lui — et qui est prouvé — c'est son
  **domaine d'horloge**, sa forme et son compte. Que la jointure avec le journal de la fenêtre
  fonctionne vraiment reste à vérifier en séance (recette 2.9).
- 🟡 **Le dépouillement est dehors**, comme demandé. Il n'existe nulle part, pas même en script.
- 🟡 **Diff de 88 Ko pour les deux tâches** (44 Ko chacune) : sur le budget d'un brief à deux
  tâches, au-dessus de celui d'une seule. `flux_page.py` (525 lignes) en est la moitié.
- 🟡 **Pour la T11** : la page « Ce que voit ton application » et le bouton d'enregistrement n'ont
  aucune ligne dans `README.md`, `docs/SPEC.md` ni `docs/recette.md`. Le test 2.9 en particulier
  devrait citer les DEUX fichiers, pas seulement le journal de la fenêtre.
- 🟡 **Constat en passant, hors périmètre** : `CLAUDE.md` cite encore `python src/research/app.py`
  dans « Commandes utiles ». Le fichier n'existe plus (archivé au chantier précédent). C'est
  l'étape 1 de la T11.
