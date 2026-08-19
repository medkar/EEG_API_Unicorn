# Tranche E — revue finale : la documentation comme contrat

Périmètre : `docs/markers.md`, `docs/SPEC.md` (§5, §14), `docs/recette.md`, `README.md`, `CLAUDE.md`.
Méthode : chaque affirmation vérifiable confrontée à `src/core/lsl_io.py`, `src/core/modes/errp.py`,
`src/core/modes/registry.py`, `src/core/config.py`, `src/core/server.py`, `src/research/errp_stimulus.py`,
`src/research/errp_calibrate.py`, `src/research/app.py`, `examples/receiver.py`.
**Aucun programme n'a été exécuté** (quatre relecteurs en parallèle, noms de flux partagés).

## Ce qui tient — vérifié, pas supposé

Pour que le reste se lise à sa juste sévérité, voici ce qui a été contrôlé et qui est **juste** :

- **Flux et voies** : `EEG_API_Unicorn_decoded_errp`, voies `["error", "score", "threshold",
  "artifact"]` dans cet ordre — `lsl_io.py:428-430` (`errp_channel_labels()`, seule source), reprises
  par `SPEC.channels=tuple(errp_channel_labels())` (`errp.py:493`). README:191, SPEC.md:197 et
  markers.md:287-294 concordent tous les quatre.
- **Métadonnées** : `tnr_target`, `tpr_measured`, `tnr_measured`, `calibration_epochs`, `measured_on`
  existent bien, tous — `lsl_io.py:459-463`. `measured_on = "1 person, 1 session"` (`lsl_io.py:463`).
  markers.md:301-305 les nomme exactement.
- **Époque** : −200 ms / +700 ms (`ERRP_PRE_S = 0.2`, `ERRP_EPOCH_S = 0.7`, `config.py:688-689`),
  `marker_epoch_s = 0,9` (`errp.py:495`). Le seuil de chevauchement de markers.md:90 (« closer
  together than 0.9 s ») en découle exactement.
- **Chauffe/repos** : 15 s + 8 s (`SSVEP_WARMUP_S = 15.0` `config.py:213` ; `duration_s=8.0`
  `errp.py:482`), marqueurs consommés et comptés pendant les deux (`errp.py:327-349`). recette 1.15
  ligne 361-364 est exacte.
- **`error = -1` = « pas de verdict »** : les deux chemins `-1` (`errp.py:363` époque perdue,
  `errp.py:369` artefact) ne publient jamais `0`. Dit correctement dans les quatre documents.
- **La période réfractaire** : `ERRP_REFRACTORY_S = 1,5` (`config.py:712`) n'est appliquée **nulle
  part** dans `core/` — le moteur ne l'utilise pas. **Aucun des cinq documents ne laisse croire
  l'inverse** ; markers.md:95-97 et SPEC.md:197 disent tous deux explicitement que la réfractaire
  appartient au client. Le piège annoncé au brief n'est pas présent.
- **Chiffres mesurés** : AUC 0,776 / p = 0,0099 (README:50, SPEC.md:197, SPEC.md:489, recette:562)
  concordent avec `progress.md:9-10` et `task-1-report.md:112-125` (0,7763 ; 0,0099 ; seuil 0,5103 ;
  TPR 0,500 / TNR 0,855).
- **`ERRP_ARTIFACT_RATIO = 4.0`** (`config.py:714`) utilisé tel quel en `errp.py:394` ; palier
  d'alarme 0,5 (`errp.py:105`) — recette 2.8 ligne 584 (« s'il dépasse 50 % ») est exact.
- **Commandes** : `python src/core/errp_models.py`, `python src/core/modes/errp.py`,
  `python src/research/errp_stimulus.py --smoke` (CLAUDE.md:87-89) existent toutes trois avec un
  `__main__` ; `errp_stimulus.py --windowed` existe (`errp_stimulus.py:380`) ;
  `examples/receiver.py --stream decoded_errp` fonctionne (suffixe libre, `receiver.py:58-66`) ;
  « menu → ErrP → Calibrer » existe (`app.py:1287-1311`, `page_errp`).
- **Le point de fonctionnement est dit honnêtement** (piège de fond n°1) : README:48-49, SPEC.md:197,
  markers.md:303-305 et recette:560-565 portent tous « une erreur sur deux / une bonne commande sur
  sept » en gras. Un lecteur ne peut pas sortir de ces pages en croyant tenir un détecteur fiable —
  **sauf** par README:214, voir Important n°2.

---

# CRITICAL

## C1. markers.md promet qu'une calibration n'écrase jamais la précédente — la calibration ErrP écrase toujours

**Sévérité : Critical** · `docs/markers.md:321-333` (la phrase fautive : **ligne 331**)

**Ce que la doc affirme.** La section a été réécrite par ce chantier pour couvrir les deux modes —
markers.md:323 : « **Neither of these is SSVEP. Both need a model** of your own brain », suivi des
deux commandes (markers.md:327-328) :

```bash
python src/research/app.py     # menu -> P300 -> Calibrer
python src/research/app.py     # menu -> ErrP  -> Calibrer
```

puis, markers.md:331-333, une promesse qui porte désormais sur **les deux** :

> Each calibration writes a **new, timestamped** file (`data/p300_model_20260818_101500.joblib`); it
> **never overwrites the previous one**. The engine offers the most recent loadable model as its
> default, and the P300 page lists the others.

**Ce que le code fait réellement.** Vrai pour le P300, **faux pour l'ErrP** :

| | P300 | ErrP |
|---|---|---|
| chemin par défaut | `p300_calibrate.py:263` — `save_path = save_path or chemin_modele_horodate()` | `errp_calibrate.py:374` — `save_path = save_path or ERRP_MODEL_PATH` |
| ce que ça vaut | `p300_calibrate.py:252` → `p300_model_<AAAAMMJJ_HHMMSS>.joblib`, **nouveau fichier** | `config.py:715` → `ERRP_MODEL_PATH = data/errp_model.joblib`, **nom FIXE** |
| écriture | `model.save(save_path)` sur un nom neuf | `errp_calibrate.py:418` — `model.save(save_path)` **sur le même nom** |

La deuxième calibration ErrP d'un étudiant **détruit silencieusement la première**, à l'endroit exact
où la page publique lui garantit que c'est impossible. `errp_models.MOTIF = "errp_model*.joblib"`
(`errp_models.py:28`) sait lire des fichiers horodatés — mais seul le script de ré-entraînement en
écrit (cf. `task-1-report.md:128`) ; le chemin que la doc recommande n'en écrit jamais.

**Circonstance atténuante, qui ne sauve pas la phrase** : `errp_calibrate._archive`
(`errp_calibrate.py:311-320`) sauve bien un `.npz` **horodaté** des époques brutes, donc le modèle
est ré-entraînable. La séance n'est pas perdue ; le **modèle** l'est, et rien ne prévient.

**Correction minimale.** Deux options, la seconde préférable :

1. *Doc seule* — remplacer markers.md:331-333 par une phrase qui distingue les deux :
   « The P300 calibration writes a new, timestamped file (`data/p300_model_20260818_101500.joblib`)
   and never overwrites the previous one. ⚠️ **The ErrP calibration does not: it always writes
   `data/errp_model.joblib`, overwriting your previous model.** The raw epochs are archived
   timestamped (`data/errp_calib_*.npz`), so a model can be retrained — but copy the `.joblib`
   aside if you want to keep it. »
2. *Code* — aligner `errp_calibrate.py:374` sur son jumeau (`save_path or chemin_modele_horodate()`
   côté ErrP), ce qui rend la phrase actuelle vraie sans la toucher. `errp_models.charger` et
   `modeles_disponibles` gèrent déjà les noms horodatés (`errp_models.py:28,107`).

---

# IMPORTANT

## I1. README cite une commande qui n'existe plus : `src/research/errp_decoder.py`

**Sévérité : Important** · `README.md:291` et `README.md:266`

**Ce que la doc affirme.** README:291, dans le bloc « Self-tests (no headset needed) » que le lecteur
copie-colle en entier :

```bash
python src/research/errp_decoder.py      # ErrP pipeline on synthetic error potentials
```

et README:266 : « Mode decoders — the migration candidates | `cvep_decoder` · `cvep_code` ·
`errp_decoder` (`p300_decoder` has moved to `core/`) ».

**Ce que le code fait réellement.** `src/research/errp_decoder.py` **n'existe pas** :
`ls src/research/errp_decoder.py` → *No such file or directory*. Le module a déménagé dans
`src/core/errp_decoder.py` (15 951 octets) par le commit **b35872a « Move the ErrP decoder into the
engine, and retrain rather than shim »** — le premier commit de ce chantier. `errp.py:96` l'importe
bien depuis `core.errp_decoder`. La commande de README:291 échoue donc en `can't open file`, et
README:266 range en « candidat à la migration » un module **déjà migré**.

**Correction minimale.** README:291 → `python src/core/errp_decoder.py`, et le déplacer dans le
premier bloc (celui des modules `core/`). README:266 → « (`p300_decoder` **and `errp_decoder`** have
moved to `core/`) », en retirant `errp_decoder` de la liste des candidats.

## I2. README dit encore, à trois endroits, que l'ErrP ne vit que dans l'appli pygame

**Sévérité : Important** · `README.md:22`, `README.md:146`, `README.md:214`

**Ce que la doc affirme.**

- README:22, dans l'encadré « où en est le projet », le premier paragraphe lu :
  « c-VEP and ErrP **still live in the pygame app only**. »
- README:146 : « **The pygame app** — the original all-in-one, **still the only way to run c-VEP and
  ErrP** ».
- README:214, ligne du tableau des modes : « | **ErrP** | … | ~4 min | 🟡 **demonstrator, needs real
  calibration** | ».

**Ce que le code fait réellement.** L'ErrP est un mode **du moteur** : `errp.SPEC` est enregistré
dans `registry.MODES` (`registry.py:26`), `status="moteur"`, `stream="decoded_errp"` (`errp.py:460,
492`), et `python src/core/server.py --mode errp` publie. Les trois phrases sont donc fausses, et
**contredites par le même fichier** : README:45-51 décrit l'ErrP comme un mode publié, README:53 dit
« **Five** published modes », README:191 liste `EEG_API_Unicorn_decoded_errp` dans le tableau des
flux. README:214 est faux **deux fois** : le mode est publié, et la « real calibration » qui lui
manquerait a été faite le **2026-07-24** (n = 200, AUC 0,7763) — c'est le constat central de
SPEC.md:479-481 (« La dette qu'on croyait ouverte ne l'était pas »).

C'est le seul endroit du périmètre où le mode est **sous-vendu** au point qu'un lecteur n'essaiera
pas la fonctionnalité livrée.

**Correction minimale.**
- README:22 → « c-VEP still lives in the pygame app only. »
- README:146 → « still the only way to run c-VEP, **and the only place to calibrate P300 and ErrP**, ».
- README:214 → aligner la colonne Status sur ses voisines : « ✅ **published as a stream** — your app
  shows the feedback and sends markers, see [docs/markers.md](docs/markers.md); catches ~1 error in
  2 at the default operating point (AUC 0.776) », et la colonne Calibration → « ~7 min (200 trials) ».

## I3. markers.md promet un nom de flux de marqueurs configurable — l'ErrP n'a pas ce réglage

**Sévérité : Important** · `docs/markers.md:31-35`

**Ce que la doc affirme.** Dans « The stream you publish », section que ce chantier a explicitement
placée **au-dessus des deux décodeurs** (markers.md:14-17 : « Two decoders read this stream ») :

> The name is a setting on the engine side (`Marker stream` on the P300 page), **so you may use your
> own**.

**Ce que le code fait réellement.** Le nom écouté vient de `_nom_flux_marqueurs`
(`server.py:848-858`) : `rt.params.get("stream_in", MARKER_STREAM_DEFAULT)` pour chaque mode actif
qui consomme des marqueurs. Or **`errp.SPEC` ne déclare pas de paramètre `stream_in`** : ses `params`
sont exactement `{"model", "tnr_target"}` (`errp.py:461-479`, verrouillé par son propre autotest
`errp.py:611`). Le P300, lui, le déclare (`p300.py:536`).

Conséquences concrètes :
- **Moteur en `--mode errp` seul** : le nom retombe toujours sur `MARKER_STREAM_DEFAULT`
  (`EEG_API_Unicorn_stim`, `config.py:611`). L'étudiant qui suit markers.md et publie sous son propre
  nom n'est **jamais** écouté. Le moteur le dit (« pas encore là — j'attends », markers.md:254) —
  c'est ce qui empêche ce point d'être Critical — mais la doc lui a affirmé que c'était supporté, donc
  il cherchera la panne ailleurs.
- **Moteur en `--mode p300,errp`** avec un nom personnalisé posé sur la page P300 : les deux modes
  réclament des noms **différents**, `server.py:853-857` avertit et retient « le premier rencontré »
  dans l'ordre de démarrage. Le comportement dépend de l'ordre du `--mode`.

**Correction minimale.** Une phrase après markers.md:35 :
« ⚠️ **This setting exists on the P300 page only.** The ErrP mode has no `Marker stream` setting: an
engine running ErrP always listens on the default name `EEG_API_Unicorn_stim`. If you run both modes
at once and rename the stream on the P300 page, the two disagree and the engine says so, keeping the
first one started. » (Le correctif de fond — ajouter `stream_in` à `errp.SPEC` — est un changement de
code, hors périmètre de cette tranche, mais mérite d'être tracé.)

## I4. Le tableau de compromis de markers.md donne les TNR *obtenus* là où le texte annonce les valeurs *à saisir*

**Sévérité : Important** · `docs/markers.md:310-319`

**Ce que la doc affirme.** markers.md:310-316, colonne de gauche intitulée « **you keep this share of
good commands** » : `96 %`, `91 %`, **`85 %`** *(default)*, `81 %`, `70 %` — puis, immédiatement en
dessous (markers.md:318-319) : « **You choose where to sit with the `Bonnes commandes gardées`
setting** on the ErrP page. **You ask for a rate**, not a threshold ». La colonne se lit donc comme
la valeur à entrer dans le réglage.

**Ce que le code fait réellement.** Ces nombres sont les TNR **atteints**, pas demandés. Source :
`docs/superpowers/specs/2026-08-18-errp-moteur-design.md:33-41` — 95,7 % / 91,3 / **85,5** / 81,2 /
70,3, obtenus en visant 0,95 / 0,90 / 0,85 / 0,80 / 0,70 (`plans/2026-08-18-errp-moteur.md:27` :
« TNR 0,95→TPR 0,24 · 0,90→0,40 · **0,85→0,50** · 0,80→0,60 · 0,70→0,71 »). Le réglage, lui, est une
**cible** : `pick_threshold(..., tnr_target=cible)` (`errp.py:166-167`), bornée `[0.50, 0.99]`
(`errp.py:474`), et `pick_threshold` garantit `tnr ≥ cible` (autotest `errp.py:754`), donc viser 0,96
ne donne pas le point à 24 % de TPR mais un point plus conservateur encore.

Le tableau contredit en outre **l'aide du réglage que l'étudiant voit dans la console**
(`errp.py:475-477`) : « garder **95 %** n'attrape que 24 % des erreurs, garder 85 % en attrape 50 %,
garder **70 %** en attrape 71 % » — 95/85/70, pas 96/85/70. Trois des cinq lignes (96, 91, 81) ne
correspondent à aucune valeur documentée ailleurs.

**Correction minimale.** Donner les deux colonnes plutôt que d'en travestir une :

```
| you ask for (setting) | you actually keep | you catch |
|---|---|---|
| 95 % | 95.7 % | 24 % |
| 90 % | 91.3 % | 40 % |
| **85 %** *(default)* | **85.5 %** | **50 %** |
| 80 % | 81.2 % | 60 % |
| 70 % | 70.3 % | 71 % |
```

Cela rend au passage visible le fait, déjà implémenté et annoncé au démarrage (`errp.py:173-174`),
que le TNR obtenu n'est jamais exactement celui visé.

## I5. La recette 1.15 et 2.8 lancent le moteur *headless* puis demandent de lire et de régler une page de **console**

**Sévérité : Important** · `docs/recette.md:354-359` + `370-376`, et `docs/recette.md:570-577` + `587-588`

**Ce que la doc affirme.** Le montage de 1.15 (recette:354-359) est :

```bash
# terminal 1
python src/core/server.py --synthetic --mode errp
# terminal 2
python src/research/errp_stimulus.py --windowed
```

et deux points de la même liste exigent la console :
- recette:370-372 — « **Sur la page ErrP de la console**, le verdict s'affiche avec le score et le
  point de fonctionnement » ;
- recette:374-376 — « **Mets-le à 0,95 puis à 0,70** et regarde le seuil changer dans le terminal ».

Idem en 2.8 : terminal 1 = `python src/core/server.py --mode errp` (recette:572), puis recette:587 —
« **Change « Bonnes commandes gardées » de 0,85 à 0,70** et refais une série ».

**Ce que le code fait réellement.** `server.py` est *headless* : il n'a **aucune** page ErrP, et son
`argparse` n'expose **aucun** réglage `tnr_target` — les seules options sont `--synthetic`, `--serial`,
`--duration`, `--mode`, `--no-raw`, `--freqs`, `--refresh`, `--baseline`, `--warmup`, `--id`,
`--smoke`, `--verbose` (`server.py:3130-3160`). La page ErrP et le réglage n'existent que dans la
console (`console/app.py:550-598`), qui est un **autre programme** créant **son propre**
`EngineServer`. Lancer les deux, c'est deux moteurs publiant `decoded_errp` sous le même nom —
précisément ce que CLAUDE.md interdit (« Un seul de ces trois programmes à la fois… un programme
oublié répond à la place de celui qu'on teste »). Le test tel qu'écrit produit donc soit une case à
cocher impossible, soit un **faux verdict** si l'étudiant lance quand même la console à côté.

**Correction minimale.** Scinder le montage. Pour 1.15, remplacer le terminal 1 par la console —
`python src/console/app.py --synthetic --mode errp` — puisque trois des cinq cases (console, réglage,
seuil) en dépendent, et garder `server.py` uniquement pour la case « un échantillon sort sur
`decoded_errp` », en disant explicitement de ne pas faire tourner les deux. Pour 2.8, ajouter avant
recette:587 : « (ce point demande la console : `python src/console/app.py --mode errp` **à la place**
du terminal 1 — jamais les deux en même temps.) »

## I6. Changer « Bonnes commandes gardées » recrée le flux et relance 23 s de chauffe — la recette n'en dit rien, et le récepteur ouvert devient muet

**Sévérité : Important** · `docs/recette.md:587-588` (et `docs/recette.md:374-376`)

**Ce que la doc affirme.** recette:587-588 : « Change « Bonnes commandes gardées » de 0,85 à 0,70 et
**refais une série** : tu devrais attraper plus d'erreurs ». Le montage de 2.8 garde un
`python -u examples/receiver.py --stream decoded_errp` ouvert en terminal 3 (recette:576).

**Ce que le code fait réellement.** `tnr_target` ne déclare pas `affecte_decodage=False`, donc il
vaut `True` (défaut, `contract.py:47`). `_set_params` prend alors la branche « reconstruction »
(`server.py:345-363`) : nouveau runtime, `ancien.close()`, **nouvel outlet LSL**, puis
`_begin_shared_rest(...)`. Concrètement, après le changement de réglage :

1. le flux `decoded_errp` est **détruit et recréé** — le moteur imprime lui-même
   « flux … **RECRÉÉ (réabonnez-vous)** » (`server.py:362`). Le `receiver.py` du terminal 3, abonné à
   l'ancien outlet, **ne reçoit plus rien** ;
2. le mode repasse par **15 s de chauffe + 8 s de repos** avant de décoder à nouveau.

L'étudiant qui « refait une série » regarde donc un récepteur muet pendant au moins 23 s, puis
définitivement. La conclusion naturelle — « en baissant le réglage, le détecteur a cessé de
détecter » — est l'exact inverse de ce que le test veut démontrer. C'est un générateur de faux
verdict, dans un document dont c'est le seul rôle d'en éviter.

**Correction minimale.** Après recette:588, une note :
« > ⚠️ Changer ce réglage **recrée le flux** (le moteur écrit « RECRÉÉ (réabonnez-vous) ») et
> **refait la chauffe + le repos, ~23 s**. Relance ton `receiver.py` après le changement, et attends
> la fin du repos avant de compter quoi que ce soit — sinon tu mesureras un flux mort. »
La même note vaut pour recette:374-376.

## I7. La recette 1.15 ne dit pas qu'un dépôt fraîchement cloné ne peut pas exécuter ce test

**Sévérité : Important** · `docs/recette.md:349-376`

**Ce que la doc affirme.** Titre : « **1.15 — L'ErrP : le 5e mode, sans casque** », dans le
**Niveau 1 — sans casque**. Aucune mention d'un prérequis de modèle. Le seul encadré ⚠️ de la section
(recette:374-376) porte sur le réglage.

**Ce que le code fait réellement.** Le mode **refuse de démarrer sans modèle entraîné** :
`validate` écarte le cas « aucun modèle » et `ErrPRuntime.__init__` lève `ValueError(raison)` si
`errp_models.charger` rend `None` (`errp.py:147-152`). Le message attendu contient « aucun choix
disponible » et « research/app.py » (autotest `errp.py:583-585`). Or `data/` est gitignoré, et la
**seule** façon d'obtenir un modèle ErrP est une calibration de ~200 essais **au casque**
(`errp_calibrate.calibrate`, `ERRP_CAL_TRIALS = 200`, `config.py:709`) — c'est-à-dire du **Niveau 2**.
Un test « sans casque » exige donc un artefact que seul le casque produit.

Le voisin immédiat traite exactement ce cas, et c'est ce qui rend l'omission visible — recette:345-347 :

> ⚠️ Sans modèle P300 entraîné sur ce poste, le mode **refuse de démarrer** et dit d'aller calibrer
> dans l'appli pygame. C'est le comportement attendu sur un dépôt fraîchement cloné (`data/` est
> gitignoré), pas une panne.

Sans son équivalent, un relecteur de la recette voit un refus au démarrage et ne peut pas trancher
entre « panne » et « normal » — le faux verdict que le brief demande explicitement d'éliminer.

**Correction minimale.** Copier la note du 1.14 en tête de 1.15, adaptée :
« > ⚠️ Sans modèle ErrP entraîné sur ce poste, le mode **refuse de démarrer** et dit d'aller calibrer
> (`python src/research/app.py`, menu → ErrP → Calibrer). C'est le comportement attendu sur un dépôt
> fraîchement cloné (`data/` est gitignoré), pas une panne. ⚠️ **Cette calibration demande le
> casque** : si tu n'en as jamais fait, ce test du niveau 1 n'est jouable qu'après le 2.8. »

## I8. SPEC.md §5 affirme encore que le P300 est le seul mode à exiger des marqueurs entrants

**Sévérité : Important** · `docs/SPEC.md:195`

**Ce que la doc affirme.** Ligne P300 du tableau des sorties décodées :

> ⚠️ **Seul mode qui exige des MARQUEURS ENTRANTS** : l'application externe affiche les flashs et
> déclare l'onset de chacun — contrat public dans [markers.md](markers.md).

**Ce que le code fait réellement.** L'ErrP consomme le même tuyau : `errp.SPEC.marker_epoch_s = 0,9`
(`errp.py:495`), `_run_step` lit `engine.markers_murs(self.spec.id, ...)` (`errp.py:352`), et
`registry.py:26` le commente lui-même « **2e client du tuyau des marqueurs** ». La ligne ErrP, **deux
lignes plus bas dans le même tableau** (SPEC.md:197), décrit un « échantillon par marqueur
`feedback` » — le tableau se contredit donc à deux lignes d'intervalle. markers.md:12, réécrit par ce
chantier, dit correctement « P300 **and** ErrP ».

**Correction minimale.** SPEC.md:195 → « ⚠️ **Exige des MARQUEURS ENTRANTS** (avec l'ErrP, les deux
seuls) : l'application externe affiche les flashs et déclare l'onset de chacun ».

## I9. Le paragraphe « Actif vs passif » de SPEC.md ignore l'ErrP, alors que le tableau vient de le classer passif

**Sévérité : Important** · `docs/SPEC.md:204-208`

**Ce que la doc affirme.**

> **Actif vs passif : un client ne doit pas les traiter pareil.** SSVEP, c-VEP, P300 et MI sont
> *actifs* … **Le neuro-monitoring est *passif*** : on observe un état, il n'y a rien à choisir,
> aucun stimulus … c'est pourquoi les métadonnées portent `paradigm` (`SSVEP` / `neuro-passive`).

**Ce que le code fait réellement.** L'ErrP est déclaré `family="passif"` (`errp.py:458`, commenté
« passif : une RÉACTION observée, pas un choix fait ») et SPEC.md:197 le classe « passif » dans la
colonne Type. Le paragraphe qui **explique** cette colonne ne le mentionne nulle part : il énumère
quatre actifs et **un seul** passif. Deux conséquences pour un lecteur :

1. il ne trouve pas l'ErrP dans l'énumération et peut conclure que la ligne « passif » du tableau est
   une coquille ;
2. l'énumération des valeurs de `paradigm` est incomplète — il en existe **cinq** :
   `SSVEP` (`lsl_io.py:223`), `neuro-passive` (`:274`), `motor-imagery` (`:335`), `P300` (`:400`),
   `ErrP` (`:455`). Un client qui filtre sur `paradigm` d'après cette parenthèse ne reconnaîtra pas
   le flux ErrP.

Cas particulier à ne pas perdre : l'ErrP est passif **mais exige un stimulus côté client** (le
feedback affiché) — il ne rentre proprement dans aucune des deux moitiés telles qu'elles sont
formulées.

**Correction minimale.** Ajouter après « justesse ni erreur à mesurer » :
« L'**ErrP** est passif lui aussi — on observe une réaction, l'utilisateur ne choisit rien — mais
c'est le seul passif qui **dépend quand même d'un stimulus client** : sans feedback affiché ni
marqueur, il n'a rien à juger. » Et compléter la parenthèse finale en
`(`SSVEP` / `neuro-passive` / `motor-imagery` / `P300` / `ErrP`)`.

---

# MINOR

## M1. markers.md sous-estime la fenêtre pendant laquelle l'ErrP jette les marqueurs (15 s au lieu de 23 s)

**Sévérité : Minor** · `docs/markers.md:260`

Le tableau « When something is wrong, the engine says so » annonce : « Markers arrived during the
**15 s warm-up** | counted in `marqueurs_chauffe`, said once — they are dropped on purpose ». Exact
pour le P300 ; pour l'ErrP la fenêtre est **15 s de chauffe + 8 s de repos = 23 s**
(`errp.py:327-328` : `if self.phase in ("warmup", "rest")`), ce que la docstring du mode souligne
comme une différence délibérée (`errp.py:56-58` : « 23 s, contre 15 s pour le P300 »). Un étudiant qui
compte 15 s avant de faire confiance aux verdicts en perdra 8.

**Correction** : « Markers arrived during the warm-up (**15 s for P300; 15 s + 8 s of rest = 23 s for
ErrP**) ».

## M2. markers.md ne documente aucun compteur d'état pour l'ErrP, alors que la recette demande d'en lire un

**Sévérité : Minor** · `docs/markers.md:269-283`

« Where those numbers actually are » ne cite que les compteurs du P300 (`refus_cible`,
`epoques_perdues`, `manches_abandonnees`, `marqueurs_chauffe` « inside the **P300** mode's own
state »). L'ErrP expose les siens dans `state()` (`errp.py:271-280`) : `epoques_perdues`,
`epoques_vues`, `artefacts`, **`taux_rejet`**, `marqueurs_chauffe`, `point_de_fonctionnement`. Aucun
n'est documenté — alors que recette 2.8 (recette:584) demande précisément « Regarde le **taux de
rejet d'artefact** dans l'état du moteur ». Un client non-Python n'a aucun moyen de savoir que ce
champ existe ni comment il s'appelle.

**Correction** : ajouter une ligne au point 2 : « and `epoques_perdues`, `epoques_vues`, `artefacts`,
`taux_rejet`, `marqueurs_chauffe`, `point_de_fonctionnement` inside the ErrP mode's own state. »

## M3. CLAUDE.md n'a pas gagné la commande de lancement du 5e mode

**Sévérité : Minor** · `CLAUDE.md:57-70`

Le bloc « Commandes utiles » donne une ligne à chaque mode publié avec ses prérequis —
`--mode mi` (« EXIGE un modèle entraîné », CLAUDE.md:62), `--mode p300` (« EXIGE un modèle ET des
marqueurs entrants », :63), `p300_stimulus.py` (:64-65) — mais **aucune** ligne `--mode errp` ni
`errp_stimulus.py`, alors que le même commit a ajouté les trois autotests ErrP plus bas (:87-89).
Le mode livré est le seul publié sans commande de lancement dans le document d'accueil.

**Correction** : après CLAUDE.md:63, deux lignes sur le modèle des voisines :

```bash
python src/core/server.py --mode errp      # l'ErrP sur le réseau (EXIGE un modèle ET des marqueurs entrants)
python src/research/errp_stimulus.py       # l'émetteur de marqueurs ErrP — n'ouvre PAS le casque
```

## M4. La ligne ErrP de SPEC.md §5 ne dit pas que le mode refuse de démarrer sans modèle

**Sévérité : Minor** · `docs/SPEC.md:197`

Les lignes MI et P300 portent toutes deux l'avertissement explicite — MI : « ⚠️ Exige un **modèle
entraîné par personne** ; le mode refuse de démarrer sans, en le disant » ; P300 : « ⚠️ Exige aussi
un **modèle entraîné par personne** ». La ligne ErrP ne l'a pas : elle mentionne « les scores
hors-pli de la calibration de la personne », ce qui implique une calibration sans jamais dire que
son absence **empêche le démarrage** (`errp.py:147-152`, `ValueError`). Sur un tableau dont les
lignes voisines fixent la convention, l'omission se lit comme une différence de comportement.

**Correction** : ajouter en fin de ligne « ⚠️ Exige un **modèle entraîné par personne** (calibration
dans l'appli pygame) ; le mode refuse de démarrer sans, en le disant. »

## M5. La recette annonce « une erreur sur trois » là où l'émetteur en vise 28 %

**Sévérité : Minor** · `docs/recette.md:365`

recette:365 : « Un point avance sur une piste, **se trompe délibérément environ une fois sur trois** ».
`errp_stimulus.py` prend `ERRP_ERROR_RATE` par défaut (`errp_stimulus.py:133, 385`), soit **0,28**
(`config.py:698`) — et l'affiche à l'écran comme au terminal : « erreurs délibérées ≈ **28 %** »
(`errp_stimulus.py:178`), HUD « visé 28% » (`:239`). Le 35 % (« une fois sur trois ») est
`ERRP_DEMO_ERROR_RATE`, réservé au démonstrateur pygame, et `errp_stimulus.py:32-40` insiste sur le
fait que les deux valeurs sont distinctes **à dessein**. L'écart est petit, mais le chiffre affiché
contredit le chiffre lu.

**Correction** : « se trompe délibérément environ une fois sur quatre (28 %, affiché à l'écran) ».

## M6. « S'il dépasse 50 %, le moteur le dit » — une seule fois, et pas avant 10 époques

**Sévérité : Minor** · `docs/recette.md:584-586`

L'affirmation est exacte sur le seuil (`_TAUX_REJET_ALARME = 0.5`, `errp.py:105`) mais tait deux
conditions de `_verifie_taux_rejet` (`errp.py:410-418`) : l'alarme ne sort qu'à partir de
**10 époques vues** (`_TAUX_REJET_MIN_ECHANTILLONS`, `errp.py:108`) et **au plus une fois** par
session (`_rejet_eleve_dit`). Un étudiant qui surveille son terminal en attendant un message
récurrent conclura que le taux est redescendu alors que rien ne le lui dit plus.

**Correction** : « … le moteur le dit — **une seule fois, et seulement après 10 époques jugées**. Pour
le suivre en continu, regarde `taux_rejet` dans l'état du moteur (flux `status` ou console). »

## M7. README : le paragraphe ErrP est placé avant l'énumération qui ne le contient pas

**Sévérité : Minor** · `README.md:45-51` et `README.md:53-62`

Le paragraphe ErrP (README:45-51) précède la phrase « **Five** published modes, and a client should
not treat them alike » (README:53), dont l'énumération décrit ensuite **quatre** modes seulement —
SSVEP, Motor Imagery, P300, Neuro. Le lecteur compte cinq annoncés, quatre décrits. Sur le fond le
contenu est bon et honnête ; c'est l'ordre qui cloche.

Accessoirement, « It is **the best-validated decoder here** » (README:50) voisine avec le tableau où
le SSVEP est « ✅ **most reliable** » (README:209) : les deux sont vrais dans des sens différents
(rigueur de validation vs performance), mais rien ne le dit. La phrase suivante (« and still only
that good ») rattrape l'essentiel, d'où la sévérité basse.

**Correction** : déplacer le paragraphe ErrP **après** l'énumération (juste avant « The stream
metadata carries `paradigm` »), et préciser « the best-validated decoder here **by AUC on grouped
cross-validation** ».

---

# Note de langue

Conforme, à une réserve près : `README.md` et `docs/markers.md` sont en **anglais** ; `CLAUDE.md` et
`docs/recette.md` en **français** — comme demandé. `docs/SPEC.md` est en **français** alors que la
règle de CLAUDE.md dit « README, doc et messages de commit **en anglais** » ; c'est une convention
**préexistante** du fichier (tout le document, pas seulement les ajouts de ce chantier), et le texte
ajouté s'y conforme. **Aucune correction recommandée sur SPEC.md** ; c'est la formulation de la règle
dans CLAUDE.md qui gagnerait à nommer l'exception (« sauf `docs/SPEC.md` et `docs/recette.md`, en
français »).

markers.md:318 cite le libellé français « **Bonnes commandes gardées** » dans une page anglaise :
c'est **correct** (le libellé réel de l'interface, `errp.py:470`, doit être cité tel quel) ; une
glose entre parenthèses (« share of good commands kept ») aiderait néanmoins un lecteur non
francophone.

---

# À vérifier par exécution

Rien dans ce rapport n'en dépend — toutes les constatations ci-dessus ont été établies par lecture du
code. Les commandes suivantes confirmeraient les deux points où une exécution serait la preuve la
plus directe :

- `python src/core/errp_models.py` — attendu : vert (refus des modèles hérités et des calibrations
  dégénérées).
- `python src/core/modes/errp.py` — attendu : vert, y compris le test de monotonie du réglage
  (`errp.py:723-755`), qui est la garde de I4.
- Pour C1 : deux calibrations ErrP successives, puis `ls data/errp_model*.joblib` — attendu **un seul**
  fichier `errp_model.joblib`, dont le mtime est celui de la seconde (ce qui démontre l'écrasement
  que markers.md:331 déclare impossible).
