# Tâches 8 et 9 — la fenêtre SSVEP et la mesure qu'elle sert

**Statut : complete.** Commit unique `f648d74`.

---

## Pourquoi UN commit et non deux

Les deux tâches sont structurellement inséparables, et ça se constate au test, pas à l'opinion :
`src/stimulus/registry.py::_selftest` refuse **une fenêtre que personne ne réclame** *et* **une
mesure dont la fenêtre n'existe pas**. Donc :

- tâche 8 seule → `FENETRES["ssvep"]` est orpheline → `[stim-registry] PROBLÈME` ;
- tâche 9 seule → `MesureSSVEP.stimulus_id = "ssvep"` ne désigne aucun fichier → même rouge.

Un commit intermédiaire aurait été **rouge**. La consigne était « ce qui est vert sera déjà sauf » :
j'ai livré un seul incrément vert plutôt que deux dont un faux.

---

## ⚠️ État trouvé en arrivant : un chantier interrompu, pas un dépôt vierge

`git status` n'était **pas propre** (le snapshot du prompt était périmé). Une session précédente
avait déjà écrit l'essentiel des deux tâches et s'était arrêtée **en plein test** :

```
File "src\console\app.py", line 2423, in _smoke
    chk(("start_mesure", {"id": "ssvep_taux", "params": {"stream_in": MARKER_STREAM_DEFAULT}})
NameError: name 'MARKER_STREAM_DEFAULT' is not defined
```

J'ai donc **audité** le travail existant plutôt que de le réécrire, puis terminé. Ce que j'ai
ajouté par-dessus :

| # | ce qui manquait | fichier |
|---|---|---|
| 1 | `MARKER_STREAM_DEFAULT` jamais importé → `console/app.py --smoke` plantait | `src/console/app.py` |
| 2 | `alpha.py` affirmait `MESURES == ["alpha"]` → rouge dès l'ajout de `ssvep_taux` | `src/core/modes/alpha.py` |
| 3 | les **deux preuves du rouge**, jamais faites (voir plus bas) | — |
| 4 | l'écart de σ entre la mesure et le mode, **non documenté** | `src/core/modes/ssvep_mesure.py` |
| 5 | quatre références mortes à `ssvep_stimulus.py`, dont **une commande cassée** | voir §« références mortes » |

Le point 2 mérite une note : l'assertion était `[s.id for s in registry.MESURES] == ["alpha"]`,
c'est-à-dire « l'alpha est la SEULE mesure ». Elle aurait rougi à chaque mesure nouvelle, pour une
raison qui ne dit rien sur l'alpha. Je l'ai remplacée par ce qu'elle voulait vraiment dire — **le
rang** : l'alpha est la PREMIÈRE, parce que c'est la barrière et qu'un taux mesuré sur des
occipitales qui ne captent pas décrit le montage, pas le décodage.

---

## Le critère de la mission : `[smoke-frontiere]` seul en rouge

```
$ python src/core/server.py --smoke
[smoke-frontiere] ÉCHEC : research/live_ssvep.py:31 importe core.acquisition
[smoke-frontiere] ÉCHEC : research/live_ssvep.py:90 importe pygame
[smoke-frontiere] ÉCHEC : research/live_ssvep.py:180 importe pygame
[smoke-frontiere] ÉCHEC : research/live_ssvep.py:275 importe pygame
[smoke-frontiere] ÉCHEC : research/ssvep_analyze.py:30 importe core.acquisition
[smoke-frontiere] ÉCHEC : research/ui.py:52 importe pygame
[smoke-frontiere] ÉCHEC : research/ui.py:88 importe core.acquisition
[smoke-frontiere] VERDICT : PROBLÈME
```

**Compteur : cinq → trois.** `ssvep_stimulus.py` (déménagé) et `ssvep_guided.py` (réduit à son
analyse) ont quitté la liste. Il reste à la T10 : `live_ssvep.py`, `ssvep_analyze.py`, `ui.py`.

**Les 20 autres verdicts de `server.py --smoke` sont OK**, sans exception. Le seul rouge du dépôt
est celui que la tâche 1 a posé exprès.

---

## Les deux preuves du rouge

### Invariant n°3 — UN ESSAI = UNE DÉCISION (LE test de la tâche 9)

Mutation : dans `_mesurer`, remplacer « une fenêtre par essai, la dernière » par « toutes les
fenêtres glissantes de l'époque ». C'est **l'amélioration plausible** — « plus de données,
intervalle plus serré » — et elle est fausse.

```
  ÉCHEC l'effectif annoncé est le nombre d'ESSAIS (168), jamais celui des fenêtres (168 ici)
  ÉCHEC …et l'intervalle est LARGE comme il doit l'être à cet effectif ([0.97 ; 1.00], largeur 0.03)
  ÉCHEC doubler la longueur de chaque fixation ne change PAS l'effectif (336 contre 168)
  ÉCHEC …ni la largeur de l'intervalle ([0.98 ; 1.00])
  ÉCHEC doubler le nombre d'ESSAIS, lui, rétrécit bien l'intervalle (0.033 à n=48 contre 0.033 à n=24)
  ÉCHEC le tour suivant calcule, sur les 6 ESSAIS (fini, 48)
[mesure-ssvep] VERDICT : PROBLÈME
```

n = 24 → **168** (× 7 exactement), et l'intervalle **s'effondre de 0,19 à 0,03** de large. Après
retrait de la mutation : `[mesure-ssvep] VERDICT : OK`.

**Et c'est le SEUL rouge du dépôt.** Vérifié, mutation en place :

| test lancé avec la mutation | verdict |
|---|---|
| `python src/console/app.py --smoke` | **OK** |
| `python src/core/server.py --smoke` | **OK** partout (0 verdict non-OK hors `[smoke-frontiere]`) |
| `python src/research/ssvep_guided.py --smoke` | **OK** |
| `python src/core/modes/ssvep_mesure.py` | **PROBLÈME** ← lui seul |

C'est la propriété qui compte : la faute ne lève aucune exception, ne casse aucun autre test, et
publierait un taux **juste** avec un intervalle **faux d'un facteur 2,6**.

### Invariant n°2 — essais entrelacés (tâche 8)

Mutation : `schedule` rend un bloc contigu par cible.

```
  ÉCHEC sur 50 tirages, jamais plus de 2 fois la même cible d'affilée (série max : 12)
  ÉCHEC jamais plus de 2 fois la même cible d'affilée : c'est le BLOC contigu qu'on interdit,
        celui qui confond « quelle cible » et « quand » ([0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2])
[ssvep-stim] VERDICT : PROBLÈME
```

La garde mord **des deux côtés** : sur le tirage pur *et* sur la séance réellement rejouée. À noter
que l'assertion d'**équilibre** (« chacune vue le même nombre de fois ») reste verte sous cette
mutation — c'est correct, équilibre et entrelacement sont deux propriétés distinctes, et le test
porte bien les deux séparément.

---

## 🔴 Le désaccord entre le protocole et le mode — constaté, DIT, non corrigé

L'arbitrage n°1 demandait de le signaler plutôt que de le corriger en silence. En voici un.

**Le σ du rejet d'artefact ne se mesure pas sur les mêmes voies des deux côtés.**

| | où le σ est pris | voies |
|---|---|---|
| le MODE (`modes/ssvep.py::_run_step`) | `window.std(axis=0).mean()` sur la fenêtre occipitale **filtrée** | **4** (PO7, Oz, PO8, Pz) |
| la MESURE (`rejouer`) | `acq.sigma_from_block(bloc)` → `sigma_source` | **8** |

Les deux filtrent et écartent le transitoire de la même façon (`occipital_window` prend
`[-window_n:]` après filtrage, `sigma_source` prend `[margin_n:]`) : **la seule différence est le
jeu de voies.**

Conséquences :

1. Le seuil reste **cohérent avec lui-même** — numérateur et dénominateur sortent du même
   estimateur — donc le chiffre n'est pas absurde.
2. Mais le rejet ne tombe **pas forcément sur les mêmes essais** que celui du mode, et il est
   vraisemblablement plus sensible aux artefacts **frontaux** (le clignement, que Fz voit et qu'Oz
   voit peu). Le taux d'émission rendu est donc, sur ce point, **légèrement conservateur**.

**Vérifié : l'écart est ANTÉRIEUR à ce chantier.** `git show HEAD~1:src/research/ssvep_guided.py`
utilisait déjà `acq.sigma_from_block` (lignes 257-258, 281-282, 430, 435). C'est donc **la règle
sous laquelle les repères 100 %/44 % du 2026-07-27 ont été obtenus**. L'aligner maintenant sur les
4 occipitales changerait la règle et rendrait le prochain chiffre incomparable au seul dont on
dispose — un correctif de décodage glissé dans un chantier de déménagement, exactement ce que
l'arbitrage interdit.

**Laissé tel quel, et documenté à trois endroits** : en tête de `ssvep_mesure.py` (deux paragraphes
⚠️), et au point d'usage dans `rejouer`. La docstring affirmait « reconstruit le chemin du mode **à
l'identique** » — c'était **faux** sur ce point, et c'est corrigé.

👉 **Décision à prendre hors de ce chantier** : aligner le σ de la mesure sur les 4 occipitales
(plus fidèle au mode) *ou* aligner le mode sur les 8 (plus sensible aux clignements). Les deux se
défendent ; ce qui ne se défend pas, c'est de continuer sans le savoir.

---

## Ce qui a été livré

### Tâche 8 — `src/stimulus/ssvep.py` (713 lignes)

Déménagement de `research/ssvep_stimulus.py` **+ le mode `--guide`**. La fenêtre n'ouvre toujours
pas le casque (confirmé : le scan de `src/stimulus/` est vert).

Le mode guidé publie `calib_start` → `repos` → `cue`×N → `calib_end`, sur le patron de
`stimulus/p300.py`. **Le `repos` est propre au SSVEP** et n'est pas un ajout gratuit : le mode
décide sur z = (ρ − μ) / σ, et μ/σ se mesurent cible par cible pendant cette phase. Sans elle il
n'y a **aucune décision à mesurer** — le décodeur refuse de se caler et la mesure le dit.

Ce que le `--smoke` prouve, et qui va plus loin que le plan :

- la cible annoncée par `cue` est **lue dans les PIXELS** de la surface rendue, pas dans le
  compteur de l'émetteur — qui ne peut que se donner raison (même famille que le test c-VEP) ;
- horodatage **après** `display.flip()`, horodatages strictement croissants ;
- une séance **interrompue** ne publie **aucun** `calib_end`, donc aucun verdict n'est calculé : un
  taux sur séance tronquée serait indiscernable d'un taux complet ;
- les durées viennent de `core/config.py`, **aucune copie locale** (assertion explicite).

### Tâche 9 — `src/core/modes/ssvep_mesure.py` (1135 lignes)

`MesureSSVEP(MesureRuntime)`. Redéfinit `tick` sur le patron de `modes/marker_calib.py`, parce que
c'est **la fenêtre qui minute et le moteur qui subit** — le stimulus doit être verrouillé au
rafraîchissement.

- **Invariant 1 (chauffe)** : `warmup_s` hérité du socle ; les marqueurs reçus pendant sont **jetés
  ET comptés ET dits**. L'annonce `calib_start`, elle, est retenue même pendant la chauffe (sinon
  la fenêtre devrait deviner la durée de celle-ci pour ne pas être déclarée morte).
- **Invariant 2** : tenu par la fenêtre ; le moteur ne fait que l'apprendre. Il ne peut donc pas le
  défaire, et c'est voulu.
- **Invariant 3** : `_decision_de_l_essai` — **la dernière** fenêtre de la fixation, pas la
  première ni la moyenne (la réponse SSVEP met ~1 s à s'établir après la saccade).

La phrase d'honnêteté porte **les deux repères dans la même phrase**, et le test l'exige
explicitement (`"100" in honnetete.split("Ce que cette mesure ne dit PAS")[0]`) — pour qu'on ne
puisse pas les séparer en mettant l'un en note de bas de page.

**Le décodage n'a pas été touché** : ni `CCADecoder`, ni `Z_MIN`, ni le plancher de repos.
`core/cca_decoder.py` et `core/modes/ssvep.py` ne sont pas dans le diff.

### Effets de bord assumés

- `core/server.py` : le tampon **nomme** l'époque des mesures (`epoque_mesure`) au lieu de
  l'hériter par accident de l'`epoch_s` de la calibration MI — le jour où le MI raccourcirait la
  sienne, chaque époque de la mesure serait tronquée **en silence**.
- `core/server.py` : `_cle_marqueurs` — la mesure s'appelle `ssvep_taux` mais écoute sous `ssvep`
  (c'est le stimulus qu'elle mesure). Sans cette lecture, la purge coupait devant elle.
- `console/app.py` : `start_mesure` **d'abord**, la fenêtre **ensuite**, et l'ordre est **asserté**.
  L'inverse ferait tomber les premiers essais dans la chauffe, qui les jette — séance plus courte
  que ce que l'écran annonce, et rien pour le dire.
- `console/app.py` : `arreter_mesure` ferme **aussi** la fenêtre. Elle ne fermait rien, parce
  qu'aucune mesure n'avait de fenêtre avant celle-ci.

---

## Références mortes à `ssvep_stimulus.py`, corrigées

Le déménagement en laissait cinq dans du code ou de la doc **vivante** :

| fichier | état | traitement |
|---|---|---|
| `examples/unity/README.md:27` | **commande CASSÉE** proposée à l'étudiant | corrigé → `src/stimulus/ssvep.py` |
| `src/research/__init__.py` | l'inventaire du paquet nommait un fichier absent | réécrit (§1) |
| `src/core/config.py:3` | « Importé par le stimulus (`ssvep_stimulus.py`) » | corrigé |
| `src/core/cvep_code.py:76` | renvoi de navigation vers `ssvep_stimulus.is_on` | corrigé |
| `src/core/server.py` (×2) | deux commandes citées en docstring/`--help` | corrigées |

⚠️ **`examples/unity/README.md` n'est dans la liste de fichiers d'AUCUNE tâche, T11 comprise.**
Sans cette correction, une commande cassée partait en production. À vérifier au prochain
déménagement : ce dossier n'est couvert par aucun test.

---

## 🟡 Réserves à porter

1. **`README.md:441` est maintenant FAUX** et c'est ma modification qui l'a rendu tel. Il range
   `ssvep_stimulus.py` dans le « pygame scaffolding » de `research/`. **Pour la T11.**
2. **`src/research/live_ssvep.py:3`** dit encore « stimulus (ssvep_stimulus) ». Je n'y ai touché
   que l'import (obligé). Le fichier part en `archive/` à la **T10**, qui réécrira son en-tête.
3. **`docs/markers.md` ne documente pas les marqueurs du run guidé** — décision assumée, à
   confirmer : ce doc s'adresse à l'étudiant **qui écrit son propre émetteur**, or ces marqueurs-là
   circulent entre deux de nos programmes et le mode SSVEP **de décodage n'en consomme aucun**
   (couplage lâche, aucune synchro frame). Personne n'a à les réimplémenter. Mais le tableau
   « chauffe » de `markers.md:353` énumère les modes qui jettent leurs marqueurs pendant la chauffe,
   et la mesure en est un quatrième. **Une ligne y suffirait — à trancher en T11.**
4. **`archive/mi_pilot.py` et `archive/ssvep_pilot.py`** importent désormais `stimulus.ssvep`.
   Leurs `--smoke` passent (exit 0), mais ils n'impriment aucun `VERDICT` — je n'ai vérifié que le
   **code de sortie**, pas le contenu. La **T10** les relancera de toute façon.
5. **`etape` reste vide sur cette mesure** (réserve héritée de la T2, toujours vraie) : la console
   joue son top sonore au front montant de `etape`. Voulu ici — un bip par-dessus un stimulus
   visuel serait nuisible — et **asserté**, donc protégé.

---

## Tests — tous lancés, tous collés

| commande | verdict |
|---|---|
| `python src/stimulus/ssvep.py --smoke` | `[ssvep-stim] VERDICT : OK` |
| `python src/stimulus/registry.py` | `[stim-registry] VERDICT : OK` |
| `python src/core/modes/ssvep_mesure.py` | `[mesure-ssvep] VERDICT : OK` |
| `python src/core/modes/mesure.py` | `[mesure] VERDICT : OK` |
| `python src/core/modes/alpha.py` | `[alpha] VERDICT : OK` |
| `python src/core/modes/ssvep.py` | `[ssvep] VERDICT : OK` |
| `python src/core/modes/calibration.py` | `[calibration] VERDICT : OK` |
| `python src/core/cvep_code.py` | exit 0 |
| `python src/research/ssvep_guided.py --smoke` | `[guidé] VERDICT : OK` |
| `python src/console/app.py --smoke` | `[console-smoke] VERDICT : OK` |
| `python src/core/server.py --smoke` | **20 verdicts OK**, `[smoke-frontiere] PROBLÈME` **voulu** |

### `data/` — empreinte avant / après

`core.config.empreinte_dossier(DATA_DIR)`, encadrant **toute** la campagne de tests :

```
AVANT : 43 fichiers · mtime max 1787314665.2835183 (cvep_rcca_model.npz)
APRÈS : 43 fichiers · mtime max 1787314665.2835  · somme des tailles 89 225 633
INTACT : True
seances/ : 0 fichier avant, 0 fichier après
```

Aucun fichier créé, aucun modifié, aucun supprimé. `git status` ne prouvait rien (`data/` est
gitignoré) — l'empreinte, si.
