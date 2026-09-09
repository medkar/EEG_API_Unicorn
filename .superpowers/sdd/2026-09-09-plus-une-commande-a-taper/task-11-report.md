# Tâche 11 — la documentation

**Statut : complete.** Commit unique `cdcf8d8`, 5 fichiers, +707/−147.

| fichier | ce qui y a été fait |
|---|---|
| `docs/recette.md` | **2.1 et 2.2 réécrits en clics** ; **2.9 cite les DEUX fichiers** ; **1.17 et 1.18 créés** ; niveau 0 gagne les 4 autotests neufs ; encadré de chantier ; « ce que cette recette ne teste pas » |
| `README.md` | statut, écran de départ, « Checks and measurements », « What your app sees », 4e fenêtre, tables `console/`/`stimulus/`/`research/`/`archive/`, frontière `research/`, autotests |
| `CLAUDE.md` | paquets, les deux mesures, les trois entrées neuves de la console, les 4 gardes, `archive/ui.py`, « ce qui n'a jamais été vérifié » |
| `docs/SPEC.md` | **§3.2** (la règle vérifiable) et **§6.2** (les mesures) créés ; §3.1, §5, §12.2 (4 commandes) et §14 mis à jour |
| `docs/markers.md` | **une ligne** : la mesure SSVEP est le 4e mode qui jette ses marqueurs de chauffe (réserve portée par la T8/T9) |

---

## 1. Les commandes citées qui ne marchaient plus

Les trois signalées par le carnet, **plus deux** trouvées en balayant :

| # | où | ce qui était faux | traitement |
|---|---|---|---|
| 1 | `README.md:151` | `python src/research/alpha_check.py` mesure ton pic alpha | → la tuile **Contrôle alpha**, qui mesure *et* propose d'appliquer |
| 2 | `README.md:441-445` | table `research/` : `ui.py`, `ssvep_stimulus.py`, `alpha_check.py`, `live_ssvep.py` | table refaite : plus rien qui ouvre le casque ou dessine |
| 3 | `CLAUDE.md:318` | `research/ui.py:signal_check` | → `archive/ui.py:signal_check` |
| 4 | `docs/SPEC.md:274` | `python src/research/alpha_check.py` | → renvoi au §6.2 |
| 5 | `docs/SPEC.md:706` | `research/ui.py:signal_check` | → `archive/ui.py:signal_check` |
| 6 | `docs/recette.md:607` | `python src/research/alpha_check.py` (test **2.1**) | → page de la console |
| 7 | `docs/recette.md:626` | `python src/research/ssvep_guided.py` (test **2.2**) | → page de la console |
| 8 | `docs/recette.md:995` | « le bouton ne passe **aucune** option, donc pas de `--log` » | **faux depuis la T5** : la case passe `--log`. Seul `--seed` reste hors des boutons |
| 9 | `README.md:326` · `recette` | « `--log` … hand-launch only » | corrigé partout |

⚠️ **`CLAUDE.md` ne citait PAS `python src/research/app.py` comme commande.** Le constat de la
T6/T7 (« c'est l'étape 1 de la T11 ») était **périmé** : le chantier précédent avait déjà retiré la
ligne. Les trois occurrences restantes de `src/research/app.py` sont des phrases au passé
(« est SUPPRIMÉE », « a disparu de cette liste »), et je les ai laissées telles quelles.

### Vérification mécanique

Extraction de **tous** les `python …/*.py` des cinq documents + `examples/unity/README.md`, puis
test d'existence : **44 chemins, 42 existent.** Les deux absents sont
`src/research/alpha_check.py` et `src/research/app.py`, tous deux cités **au passé** (relu un par
un). Aucune commande vivante ne pointe sur un fichier absent.

---

## 2. Tests 2.1 et 2.2 : le déroulé réécrit

**2.1 — Contrôle alpha.** Chemin console (grille → *Contrôles et mesures* → tuile marquée
`BARRIÈRE — à passer AVANT le reste` → *Ouvrir* → *Commencer*), contrôle de liaison intercalé,
**les cinq tops sonores** et le fait que le dernier soit le seul signal disant de rouvrir les yeux,
la machine sans son qui se **dit**, le verdict qui **arrête** et nomme trois gestes dans l'ordre, et
la **boucle fermée** (bouton composé par le moteur, `set_params`, refus possible, rien de proposé
si la barrière échoue).

⚠️ **Une fausseté héritée corrigée au passage** : la recette disait « l'alpha monte … sur
**PO7/Oz/PO8** ». Le moteur moyenne `OCCIPITAL = [4,5,6,7]`, soit **Pz, PO7, Oz, PO8** — vérifié à
l'exécution. La phrase avait cessé d'être vraie le jour où Pz a rejoint la liste ; c'est le même
constat que la T3 avait fait dans le code, il vivait aussi dans la recette.

**2.2 — Taux d'émission SSVEP.** Chemin console, durée **3,6 min** (`duree_estimee_s` = 214,2 s,
calculé à l'exécution : 15 s + 12 s + 36 × 5,2 s), consignes de fixation, l'avertissement « ne ferme
pas la fenêtre » (sans `calib_end` aucun verdict), les **deux chiffres lus ensemble**, et
l'invariant **un essai = une décision** avec la conséquence lisible à l'écran (l'intervalle doit
être LARGE à n = 36). Les deux repères 100 % et 44 % sont recopiés **inchangés**.

---

## 3. Test 2.9 : les deux fichiers

Le tableau du dépouillement porte maintenant **quatre colonnes** — côté, ce que c'est, **où il
naît**, comment l'obtenir — et les deux lignes disent le geste console *et* la commande :

- vérité-terrain ← la **fenêtre**, case « Journal de séance » cochée par défaut ;
- verdicts ← le **moteur**, bouton « Enregistrer les verdicts ».

Sont dits : les deux vivent dans `seances/` (`cvep_*.jsonl` et `moteur_decoded_cvep_*.jsonl`,
noms lus dans le code), **jamais dans `data/`**, ils portent le **même `local_clock()`**, et
l'enregistrement écrit **une ligne par décision publiée** — donc comparable au relevé cherché.

Le bloc « La séance » propose désormais **deux montages** : (a) tout depuis la console, un seul
programme, aucune commande — mais **pas de `--seed`** ; (b) trois terminaux, le seul qui rejoue à
l'identique, donc celui que **A et A'** doivent utiliser. L'étape de dépouillement nomme les
fichiers des deux montages (`target_index` sous `sortie` en (a), `t=` en tête de ligne en (b)).

---

## 4. Les trois interdits

1. **Aucun repère chiffré touché.** Contrôlé mécaniquement : `git diff -U0 | grep '^-'` ne contient
   **aucune** ligne supprimée portant `%`, `AUC`, `p = ` ou `bits/min`. Les chiffres présents dans
   les lignes **ajoutées** sont exclusivement des recopies des repères du projet : 100 %, 44 %
   (×7), AUC 0,776, 46 %, 71 %, 40 %. Aucun repère inventé. Vérifié aussi que les six familles
   citées dans le brief sont toujours présentes dans les quatre documents.
2. **La phrase négative survit, et elle a grossi.** Elle est maintenant à **six** endroits :
   README (bandeau de statut + le ⚠️ sous la table des modes), `CLAUDE.md` (« Ce qui n'a jamais été
   vérifié », avec un point neuf sur ce chantier), `docs/recette.md` (encadré de chantier + « ce que
   cette recette ne teste pas »), `docs/SPEC.md` §6.2 et §14. Le **neuro** garde son statut à part
   (« plomberie testée, contenu jamais validé, **nulle part** ») dans les trois documents qui le
   portaient. Ajouté partout : **ce chantier n'a rien mesuré**, et les deux mesures neuves n'ont vu
   que du bruit blanc et des sinusoïdes.
3. **Aucun fichier de `src/`, `archive/` ou `examples/` modifié.** `git show --stat cdcf8d8` : cinq
   fichiers, tous `.md` à la racine ou dans `docs/`.

---

## 5. 🐛 Une fausseté DANS LE CODE, dite et non corrigée

**`src/stimulus/ssvep.py` et le briefing de `core/modes/ssvep_mesure.py` annoncent « quatre
flèches ». Le jeu de fréquences par défaut n'en a que TROIS.**

Mesuré, pas supposé :

```
>>> choose_frequencies(60.0)
3 [('AVANT','up',15.0), ('GAUCHE','left',20.0), ('DROITE','right',8.571)]
   (idem à 75, 120 et 144 Hz)
```

et le rendu ne dessine que le plan (`polys = {c["dir"]: … for c in plan}`), donc **trois flèches à
l'écran**. Le « 4 » est le reliquat de la géométrie du banc d'essai robot (AVANT/GAUCHE/DROITE/
ARRIÈRE). C'est un **message faux, sans danger** — mais le briefing est affiché à l'étudiant qui
s'assoit pour 3,6 min.

Conformément à l'interdit n°3, **je ne l'ai pas corrigé** : la doc dit « trois au défaut du dépôt,
la géométrie en prévoit quatre » et la recette porte une note 🐛 explicite. **Deux lignes de code
suffiraient** (`stimulus/ssvep.py:1` et le `BRIEFING` de `ssvep_mesure.py`).

---

## 6. Les deux réserves, consignées

- 🔴 **σ 8 voies vs 4 occipitales filtrées.** Écrit **trois fois**, à chaque profondeur de lecture :
  `docs/recette.md` (encadré à la fin du 2.2 — l'endroit où quelqu'un relève un taux),
  `docs/SPEC.md` §6.2 (avec « décision à prendre hors chantier ») et §14 (ligne **[à faire]**), et
  `CLAUDE.md` (bloc des mesures). Les trois disent la même chose : l'écart est **antérieur**, c'est
  la règle sous laquelle 100 %/44 % ont été mesurés, l'aligner rendrait le prochain chiffre
  incomparable.
- 🟠 **Huit constats parqués.** Les deux qui mordent en séance sont nommés dans `CLAUDE.md` et dans
  « ce que cette recette ne teste pas » : `accepted` pris pour « la séance a démarré » (l'instance
  de l'enregistrement traitée à la source par la T7, **le motif reste**) et les refus de la grille
  qui ne vont que dans le terminal — avec le conseil opérationnel « si un clic paraît sans effet,
  regarde le terminal avant de conclure à une panne ». Le correctif de la T7 est aussi documenté
  dans `docs/SPEC.md` §12.2, sous la table des commandes.

---

## 7. Toutes les commandes citées, lancées

**Aucun moteur ne tournait** (contrôlé : `examples/receiver.py --list` → *No LSL stream found*).
Lancées **une par une**, séquentiellement.

### Les 42 autotests et smokes de `src/`

| commande | verdict |
|---|---|
| `python src/core/config.py` | `[config] VERDICT : OK` |
| `python src/core/modes/contract.py` | `[contract] VERDICT : OK` |
| `python src/core/modes/registry.py` | `[registry] VERDICT : OK` |
| `python src/core/modes/ssvep.py` | `[ssvep] VERDICT : OK` |
| `python src/core/modes/mi.py` | `[mi] VERDICT : OK` |
| `python src/core/mi_models.py` | `[mi-models] VERDICT : OK` |
| `python src/core/modes/calibration.py` | `[calibration] VERDICT : OK` |
| `python src/core/modes/mi_calib.py` | `[mi-calib] VERDICT : OK` |
| `python src/core/acquisition.py --synthetic` | exit 0 (pas de ligne VERDICT — c'est dit dans la recette) |
| `python src/core/lsl_io.py` | `[lsl] VERDICT : OK` |
| `python src/core/modes/cvep.py` | `[cvep] VERDICT : OK` |
| `python src/core/cvep_models.py` | `[cvep-models] VERDICT : OK` |
| **`python src/core/modes/mesure.py`** | `[mesure] VERDICT : OK` |
| **`python src/core/modes/alpha.py`** | `[alpha] VERDICT : OK` |
| **`python src/core/modes/ssvep_mesure.py`** | `[mesure-ssvep] VERDICT : OK` |
| `python src/core/modes/marker_calib.py` | `[marker-calib] VERDICT : OK` |
| `python src/core/modes/p300_calib.py` | `[p300-calib] VERDICT : OK` |
| `python src/core/modes/errp_calib.py` | `[errp-calib] VERDICT : OK` |
| `python src/core/modes/cvep_calib.py` | `[cvep-calib] VERDICT : OK` |
| `python src/core/errp_track.py` | `[errp-track] VERDICT : OK` |
| `python src/core/markers.py` | `[markers] VERDICT : OK` |
| `python src/core/p300_models.py` | `[p300-models] VERDICT : OK` |
| `python src/core/modes/p300.py` | `[p300] VERDICT : OK` |
| `python src/core/errp_models.py` | `[errp-models] VERDICT : OK` |
| `python src/core/modes/errp.py` | `[errp] VERDICT : OK` |
| `python src/core/cvep_code.py` | `[cvep] autotest : OK` |
| `python src/core/cvep_decoder.py` | `[cvep-decoder] VERDICT : OK` |
| `python src/core/cvep_rcca.py` | `[cvep-rcca] VERDICT : OK` |
| `python src/core/cca_decoder.py` | exit 0 |
| `python src/core/neuro_monitor.py` | `[neuro] auto-test OK` |
| `python src/core/errp_decoder.py` | `[errp-gardes] VERDICT : OK` |
| `python src/stimulus/registry.py` | `[stim-registry] VERDICT : OK` |
| **`python src/stimulus/ssvep.py --smoke`** | `[ssvep-stim] VERDICT : OK` |
| `python src/stimulus/p300.py --smoke` | `[p300-stim] VERDICT : OK` |
| `python src/stimulus/errp.py --smoke` | `[errp-stim] VERDICT : OK` |
| `python src/stimulus/cvep.py --smoke` | `[cvep-stim] VERDICT : OK` |
| `python src/research/ssvep_guided.py --smoke` | `[guidé] VERDICT : OK` |
| `python src/research/ssvep_analyze.py` | exit 0 |
| `python src/research/controller.py` | exit 0 |
| `python src/research/itr.py` | exit 0 |
| **`python src/core/server.py --smoke`** | exit 0, **23 verdicts OK** |
| **`python src/console/app.py --smoke`** | `[console-smoke] VERDICT : OK` |

Le verdict que la tâche 1 avait posé en rouge :

```
[smoke-frontiere] 57 fichiers scannés, 0 violation(s) de frontière
[smoke-frontiere] VERDICT : OK
```

### Les 12 `--smoke` de `archive/`

`alpha_check` · `cvep_calibrate` · `cvep_pilot` · `cvep_rcca_pilot` · `errp_calibrate` ·
`errp_demo` · `live_ssvep` · `mi_calibrate` · `mi_pilot` · `p300_calibrate` · `p300_pilot` ·
`ssvep_pilot` — **exit 0, les douze.** `archive/ui.py` n'a pas de `--smoke` : c'est la machinerie
partagée, et c'est écrit ainsi dans les trois documents qui la comptent (**13 fichiers, 12 smokes**).

### Les `--help` et le client

- `python src/stimulus/ssvep.py --help` → `--windowed --refresh --seconds --guide --trials --seed
  --smoke` (c'est ce qui m'a servi à écrire « `--seed` reste hors des boutons »).
- `python src/core/server.py --help` → `--mode --no-raw --freqs --refresh --baseline --warmup
  --synthetic --smoke` : toutes les options citées existent.
- `python src/console/app.py --help` → `--synthetic --mode --no-raw --baseline --warmup --smoke`.
- `python examples/receiver.py --list` → `No LSL stream found.` (attendu : aucun moteur).
- `outils/Console EEG.bat` : présent.

### Empreinte de `data/`

`core.config.empreinte_dossier(DATA_DIR)`, avant la campagne et après le commit :

```
AVANT : 43 fichiers · sha256 42120328ed4df502…
APRÈS : 43 fichiers · sha256 42120328ed4df502…
seances/ : 0 fichier avant, 0 fichier après
```

Identique — et identique aussi à l'empreinte relevée par la T6/T7. Aucun fichier créé, modifié ou
supprimé.

---

## 8. ⚠️ Ce que je n'ai PAS pu vérifier

Par honnêteté, et parce que c'est la partie du rapport qui compte :

1. **Aucun écran, aucun casque.** Tout ce que j'écris sur le déroulé des pages
   (2.1, 2.2, 1.17, 1.18) vient de la **lecture du code** et des rapports T2/T3/T6-7/T8-9, **pas
   d'une session ouverte**. Qt n'a tourné qu'en `offscreen`. Concrètement, les affirmations
   suivantes sont **plausibles et non observées** :
   - que les cinq tops sonores s'entendent, et que le cinquième arrive au bon moment ;
   - que l'écran de départ soit lisible, et que le refus d'ouverture du casque s'affiche
     réellement (le chemin est testé avec un `ouvrir` injecté qui lève, jamais avec un vrai casque) ;
   - que le panneau de flux se taise quand on décoche « publié » — **le test du smoke prouve
     l'inverse du symptôme** (un état complet ne remplit rien), pas ce comportement-ci ;
   - que les deux fichiers de séance se joignent vraiment (la T6/T7 le dit aussi : **le
     dépouillement n'existe nulle part, pas même en script**).
2. **Les durées annoncées sont CALCULÉES, pas chronométrées** : 37 s et 214,2 s viennent de
   `duree_estimee_s()` exécutée ici, pas d'une séance jouée. Elles supposent que la fenêtre tienne
   son minutage — ce qu'aucune poignée de main ne garantit (constat parqué).
3. **Le format du fichier d'enregistrement** (`header` / `verdict` / `fin`, champs `t`, `phase`,
   `sortie`, `voies`, `params`, `publie`, `verdicts`) est lu dans `server.py` et pinné par
   `_smoke_enregistrement`. **Je n'ai pas ouvert un fichier produit en séance** — le smoke écrit
   dans un `tempfile`, jamais dans le vrai `seances/`, qui est resté à 0 fichier.
4. **Les tests 1.17 et 1.18 que j'ai écrits n'ont jamais été joués**, et le document le dit deux
   fois. Je les ai rédigés depuis le code ; leur ergonomie peut être mauvaise sans que je puisse
   le savoir. Le point « casque introuvable » du 1.17 **exige un casque** : c'est signalé comme
   à faire au niveau 2.
5. **« Huit constats parqués »** : je reprends le compte du brief et du carnet ; **je n'ai pas
   relu la revue du 2026-09-08** pour le recompter. Les **deux** que je nomme, eux, sont vérifiés
   (le motif `accepted` dans `server.py`/`console`, et le défaut 1.13 tel que la recette le décrit).
6. **`docs/markers.md`** : j'ai ajouté la ligne « chauffe » recommandée par la T8/T9, mais **je n'ai
   pas relu tout le document**. Il n'était dans la liste de fichiers d'aucune tâche. Même remarque
   pour **`examples/unity/README.md`** : corrigé par la T8/T9, non revu ici, **couvert par aucun
   test** — c'est un angle mort qui survit au chantier.
7. **`docs/network.md`, `docs/robot_testbed.md`, `archive/README.md`** : non relus. Le premier n'a
   pas bougé de périmètre ; le troisième a été corrigé par la T10 (deux faussetés antérieures), et
   je me fie à son rapport pour les comptes que je cite (`--model` sur sept fichiers,
   `cvep_pilot.py` par défaut sur un chemin fixe).
8. **Je n'ai pas relancé les 42 autotests après les éditions de documentation** — seulement les deux
   smokes (exit 0) et l'empreinte. Ce sont des `.md` : aucun code n'a changé entre les deux passes.
