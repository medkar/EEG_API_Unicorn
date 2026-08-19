# Re-revue E — verdict sur la vague de correction

Périmètre : `docs/markers.md`, `docs/SPEC.md`, `docs/recette.md`, `README.md`, `CLAUDE.md`.
Méthode : chaque affirmation vérifiable confrontée au code **d'aujourd'hui** (`src/core/lsl_io.py`,
`src/core/modes/errp.py`, `src/core/modes/p300.py`, `src/core/modes/contract.py`,
`src/core/modes/runtime.py`, `src/core/errp_decoder.py`, `src/core/errp_models.py`,
`src/core/config.py`, `src/core/server.py`, `src/console/app.py`, `src/console/mode_page.py`,
`src/console/grid.py`, `src/research/errp_calibrate.py`, `src/research/errp_stimulus.py`,
`src/research/app.py`). **Aucun programme exécuté.**

## Tableau des 17 verdicts

| # | Constatation | Verdict | Où |
|---|---|---|---|
| C1 | markers.md promet qu'une calibration n'écrase jamais la précédente | **ADDRESSED** | markers.md:346-350 + correctif CODE `errp_calibrate.py:344,401` |
| I1 | README cite `src/research/errp_decoder.py` | **ADDRESSED** | README:292 (bloc `core/`), README:271 |
| I2 | README dit que l'ErrP ne vit que dans l'appli pygame | **ADDRESSED** | README:22-23, 150-151, 219 |
| I3 | markers.md promet un nom de flux de marqueurs configurable | **RÉGRESSION** | markers.md:37-41 (voir N1) |
| I4 | Tableau de compromis : TNR obtenus donnés comme valeurs à saisir | **ADDRESSED** | markers.md:319-325 (3 colonnes) |
| I5 | Recette 1.15/2.8 : moteur headless + page de console | **ADDRESSED** | recette:361-373, 610-614 (imprécisions : N4, N5) |
| I6 | Changer le réglage recrée le flux et relance 23 s | **ADDRESSED** | recette:391-395, 610-614 |
| I7 | Recette 1.15 ne dit pas qu'un dépôt cloné ne peut pas l'exécuter | **ADDRESSED** | recette:351-356 |
| I8 | SPEC §5 : « seul mode qui exige des marqueurs entrants » | **ADDRESSED** | SPEC.md:195 |
| I9 | SPEC : « actif vs passif » ignore l'ErrP | **ADDRESSED** | SPEC.md:210-218 |
| M1 | markers.md : 15 s au lieu de 23 s | **ADDRESSED** | markers.md:266 |
| M2 | markers.md ne documente aucun compteur ErrP | **ADDRESSED** | markers.md:283-288 (imprécision : N7) |
| M3 | CLAUDE.md sans commande de lancement du 5e mode | **ADDRESSED** | CLAUDE.md:68-70 |
| M4 | SPEC §5 ne dit pas que l'ErrP refuse de démarrer sans modèle | **ADDRESSED** | SPEC.md:197 |
| M5 | Recette : « une erreur sur trois » vs 28 % | **ADDRESSED** | recette:379-380 |
| M6 | Recette : alarme 50 %, une fois, après 10 époques | **ADDRESSED** | recette:603-607 |
| M7 | README : paragraphe ErrP mal placé | **ADDRESSED** | README:55-58, 60, 62-67 |

**Décompte : 16 ADDRESSED · 1 RÉGRESSION · 0 PARTIEL · 0 NON TRAITÉ.**
**8 nouvelles faussetés** (N1-N8), dont 3 Important.

---

## Les cinq affirmations prioritaires

### P1. Le modèle horodaté — ✅ **TIENT**

`errp_calibrate.calibrate:401` fait `save_path = save_path or chemin_modele_horodate()` et
`chemin_modele_horodate:344` rend
`os.path.join(dossier, f"errp_model_{time.strftime('%Y%m%d_%H%M%S')}.joblib")` — soit exactement
le motif `data/errp_model_20260819_142230.joblib` cité par markers.md:347 (séparateur **underscore**).
`errp_models.MOTIF = "errp_model*.joblib"` (errp_models.py:28) le capture, et `modeles_disponibles`
trie par `getmtime` décroissant en filtrant par `charger` (errp_models.py:147-150). Le défaut proposé
est bien le plus récent : `Param.default_now` rend `choix[0]` pour un `choice` sans `default`
(contract.py:96-98), et le `model` de `errp.SPEC` n'en déclare pas.
La correction du CODE (commit `4a219e9`) a donc rendu vraie la phrase de la doc — le Critical est
réellement clos, pas contourné. Note : `data/errp_model_20260818-153051.joblib` (le ré-entraînement
du 18) porte un **tiret**, pas un underscore ; sans importance, `MOTIF` et le tri par date le voient.

### P2. Le réglage « Flux de marqueurs » — ⚠️ **une moitié tient, l'autre est fausse**

- **Il existe bien sur les deux modes** : `Param(key="stream_in", label="Flux de marqueurs", …)`
  en `p300.py:534-545` et `errp.py:663-674`. ✅
- **Sa liste n'a bien qu'une entrée** : `choices=(MARKER_STREAM_DEFAULT,)` des deux côtés. ✅
- **Mais la phrase qui explique pourquoi est fausse** — voir **N1** : ce n'est pas « la liste
  déroulante de la console » qui bloque, c'est le validateur du moteur.

### P3. « le moteur choisit toujours un point au moins aussi conservateur » — ⚠️ **vrai en calibration, faux en usage**

`pick_threshold` (`errp_decoder.py:80-88`) balaie tous les seuils candidats, garde ceux dont
`tnr >= tnr_target`, et parmi eux prend celui qui **maximise la TPR** — donc le plus BAS, la TNR
étant monotone croissante en seuil. La formulation « picks the lowest threshold whose measured rate
is at least what you asked for » est donc exacte. Et l'ensemble n'est jamais vide : `cand` contient
`scores.max() + 1e-6`, seuil auquel TNR = 1,0 ; le repli « max TNR » d'`errp.py:202-206` est en
pratique inatteignable. `errp.py:966` l'affirme d'ailleurs en autotest.
**Mais** la propriété ne vaut **que sur les scores de la calibration** — voir **N2**.

### P4. Recette 1.15 : la console au lieu du moteur nu — ✅ **TIENT**

L'`argparse` de `server.py:3228-3259` n'expose que `--synthetic --serial --duration --mode --no-raw
--freqs --refresh --baseline --warmup --id --smoke --verbose` : **aucun `tnr_target`**, aucune page.
`console/app.py:25-37` expose bien `--synthetic` et `--mode` : `python src/console/app.py
--synthetic --mode errp` (1.15) et `python src/console/app.py --mode errp` (2.8) existent avec ces
options exactes. La page ErrP existe et affiche score + point de fonctionnement + distinction
« pas de verdict » / « correct » (assertions `console/app.py:604-690`). Deux imprécisions de forme
subsistent : **N4** et **N5**.

### P5. « recrée le flux » + « ~23 s » — ✅ **TIENT**

`tnr_target` ne déclare pas `affecte_decodage`, donc il vaut `True` (contract.py:47). `_set_params`
(`server.py:337-363`) sort alors de la branche « en place », construit un nouveau runtime, appelle
`ancien.close()` puis `runtime.open()` (nouvel outlet), `_begin_shared_rest([runtime], …)`, et
imprime `f" ; flux {stream_name(spec.stream)} RECRÉÉ (réabonnez-vous)"` — le libellé exact cité.
`_begin_shared_rest` → `begin_rest` (runtime.py:68-84) repose `phase = "warmup"`, donc
`warmup_s = SSVEP_WARMUP_S = 15,0` (config.py:213) puis `duration_s = 8,0` (errp.py:678) = **23 s**.
Aucun implémenteur n'a touché `affecte_decodage` sur ce paramètre pendant la vague.

---

## Nouvelles faussetés

### N1 — markers.md affirme qu'un programme peut renommer le flux de marqueurs ; le moteur le refuse

**Sévérité : Important** · `docs/markers.md:37-41`

**Ce que la doc affirme.**
> ⚠️ **Today that setting offers exactly one name**, the default `EEG_API_Unicorn_stim`. **The
> plumbing that reads it is in place on both modes, so a program driving the engine directly can set
> another name** — but the console's dropdown has a single entry, so from the interface you cannot
> yet rename it.

**Ce que le code fait réellement.** La plomberie de LECTURE est bien là
(`server._nom_flux_marqueurs`, server.py:849-859), mais l'ÉCRITURE est refusée à tout le monde.
`stream_in` est un `Param(kind="choice", choices=(MARKER_STREAM_DEFAULT,))` (p300.py:535,
errp.py:664), et `contract._coerce` (contract.py:249-259) rend :

```
« Flux de marqueurs » : 'mon_flux' n'est pas un choix valide (EEG_API_Unicorn_stim)
```

pour toute valeur hors de la liste. Ce contrôle est sur **les trois** chemins d'entrée, sans
exception : le constructeur (`server.py:221`), `submit("start_mode")` (`server.py:445`) et
`submit("set_params")` (`server.py:570`). Un « program driving the engine directly » passe
obligatoirement par `submit`, qui valide **avant** de mettre en file (docstring `server.py:421-425`).
La restriction n'est donc pas la liste déroulante de la console : c'est le contrat du mode.
L'étudiant à qui la page dit « écris ton propre client, il pourra renommer » recevra un refus, et
cherchera la panne dans son code.

**Correction minimale.** Remplacer markers.md:37-41 par :
« ⚠️ **Today the setting accepts exactly one name**, the default `EEG_API_Unicorn_stim` — and that
is enforced by the engine, not by the interface: the setting is declared
`Param(kind="choice", choices=(MARKER_STREAM_DEFAULT,))` in `src/core/modes/p300.py` and
`src/core/modes/errp.py`, so `contract.validate` refuses any other value, from the console, from a
script, and from a client driving the engine. The pipe that *reads* the setting is already in place
on both modes; opening it up is a change to that one tuple, not to the marker protocol. »

### N2 — Le point de fonctionnement est vendu comme une garantie ; le flux lui-même le publie comme optimiste

**Sévérité : Important** · `docs/markers.md:310-334`, en écho `docs/SPEC.md:197`, `README.md:62-67`,
`docs/recette.md:579-581`

**Ce que la doc affirme.** markers.md:331-334 :
> The middle column is not padding. **The engine picks the lowest threshold whose measured rate is
> *at least* what you asked for, so what you get is always a little more conservative than what you
> requested.** … **Read the number the engine prints, not the number you typed.**

et markers.md:310-312 renvoie à `tnr_target`, `tpr_measured`, `tnr_measured`, `calibration_epochs`
et `measured_on` sans dire ce que ces deux derniers contiennent.

**Ce que le code fait réellement.** La garantie est une **tautologie sur l'échantillon de
calibration**, et le moteur le dit lui-même — dans le champ que la doc invite à lire.
`lsl_io.py:487-489` publie désormais :

```
measured_on = "1 person; threshold picked on these same out-of-fold scores, so tpr/tnr are optimistic"
```

avec, au-dessus (`lsl_io.py:471-480`), l'explication : « `tnr_measured >= tnr_target` est donc vrai
**PAR CONSTRUCTION**, et `tpr_measured` est un maximum sur N candidats. Une application qui règle sa
politique d'annulation sur ces deux nombres **observera en usage un taux de faux vetos plus élevé**,
sans que rien n'ait changé ». Les scores sont hors-pli (donc l'AUC 0,776 est honnête) ; le **seuil**,
lui, est choisi en regardant la réponse. « what you get is always a little more conservative than
what you requested » n'est vrai que sur les 200 essais du 24 juillet ; en séance, rien ne le
garantit, et le nombre que le moteur imprime au démarrage (`errp.py:205-206`) est justement le
nombre optimiste. Ce champ `measured_on` a changé **pendant la vague** (commit `74d78e7`) : la doc a
été écrite contre l'état d'avant.

C'est le seul endroit du périmètre où le mode est vendu **mieux qu'il n'est** : quatre documents
disent honnêtement « une erreur sur deux, une bonne commande sur sept », mais aucun ne dit que ces
deux chiffres sont eux-mêmes optimistes.

**Correction minimale.** Après markers.md:314, une phrase :
« ⚠️ These two numbers are themselves optimistic, and the stream says so: `measured_on` reads
*“threshold picked on these same out-of-fold scores, so tpr/tnr are optimistic”*. The scores are
out-of-fold, but the **threshold** was chosen by looking at them, so `tnr_measured ≥ tnr_target`
holds *by construction* on the calibration and not on your session — expect to cancel **more** good
commands in use than the number printed here. »
Et remplacer markers.md:332-333 par : « …so on the calibration data what you get is at or above what
you asked for. On live data it is an estimate, not a floor. »

### N3 — Recette 1.15 : la case « il dit avoir jeté les marqueurs » ne peut plus être cochée

**Sévérité : Important** · `docs/recette.md:377-378`

**Ce que la doc affirme.**
> - [ ] Il dit avoir **jeté** les marqueurs reçus pendant cette attente, en les comptant. C'est voulu :
>       l'offset du casque dérive encore, ces époques ne valent rien.

**Ce que le code fait réellement.** Le commit `314fa2a` de la vague (« Give the ErrP emitter the
pauses its model was trained under ») a donné à l'émetteur une attente propre :
`errp_stimulus.py:143-144` pose `ATTENTE_MOTEUR_S = SSVEP_WARMUP_S + 8.0` (= 23 s), et
`errp_stimulus.py:266-277` fait, dès que `wait_for_consumers` répond oui :

```
attente_initiale_s = ATTENTE_MOTEUR_S
note_initiale = "le moteur chauffe (~23 s) — la piste démarre après"
```

suivi de `tenir(pos, cible, attente_initiale_s, …)` (errp_stimulus.py:356), qui tient la piste
**immobile, sans pousser un seul marqueur**. Lancés dans l'ordre de la recette (moteur d'abord,
émetteur ensuite), les 23 s de l'émetteur finissent **après** celles du moteur : aucun feedback
n'arrive pendant la chauffe ou le repos, donc `_jeter_marqueurs_de_chauffe` (errp.py:466-502) ne
compte rien et n'imprime rien.

Un relecteur verra donc un silence là où la recette annonce un message, et n'aura aucun moyen de
distinguer « l'émetteur a bien attendu » (le succès) de « le garde-fou du moteur est cassé »
(l'échec). C'est exactement le faux verdict que ce document existe pour éviter.

**Correction minimale.** Remplacer la case par les deux qui décrivent l'état réel :
« - [ ] **L'émetteur**, lui, annonce qu'il attend : « le moteur écoute — mais il JETTE tout pendant
sa chauffe et son repos (~23 s) », et la piste reste **immobile** jusque-là. Le moteur ne dit donc
**rien** sur des marqueurs jetés : c'est le succès, pas une panne.
- [ ] Pour voir l'autre moitié du garde-fou, relance l'émetteur avec `--no-wait` : il marche tout de
suite, et le moteur écrit alors « N feedback(s) reçus pendant la CHAUFFE/le REPOS : jetés ». »

### N4 — Recette 1.15 : « coche “publié” sur la page ErrP » — ce contrôle n'est pas sur la page

**Sévérité : Minor** · `docs/recette.md:367`

**Ce que la doc affirme.** `# terminal 1 — la console (coche « publié » sur la page ErrP)`

**Ce que le code fait réellement.** La case à cocher `QCheckBox("publié")` est sur la **tuile de la
grille** (`src/console/grid.py:100`), pas sur la page de mode : `mode_page.py` n'affiche qu'un texte
d'état (`mode_page.py:159`, `" · non publié"`), et n'a aucun contrôle de publication. De plus, elle
est **déjà cochée** : `ModeRuntime.published = True` à la construction (`runtime.py:34`), ce que
l'autotest de la console vérifie (`console/app.py:289`). L'étudiant cherchera sur la page un contrôle
qui n'y est pas, pour une action qui n'est pas nécessaire.

**Correction minimale.** `# terminal 1 — la console (le mode démarre déjà « publié » ; la case est
sur la TUILE de la grille, pas sur la page)`.

### N5 — Recette 1.15 : « trois des cinq points » demandent la console — il n'y en a qu'un

**Sévérité : Minor** · `docs/recette.md:361-362`

**Ce que la doc affirme.** « **La console, pas le moteur nu.** Trois des cinq points ci-dessous
demandent une page et un réglage… »

**Ce que la liste contient.** Sur les cinq cases (recette:375-385), **une seule** — la cinquième,
« Sur la page ErrP, le verdict s'affiche… » — dépend de la console. Les quatre autres (chauffe/repos,
marqueurs jetés, piste et taux d'erreur, échantillon sur `decoded_errp`) s'observent au terminal ou
dans le `receiver.py`. Les deux autres besoins de console sont dans les **encadrés ⚠️**, pas dans la
liste. Le chiffre est le seul argument donné pour changer tout le montage : le laisser faux invite le
lecteur suivant à le remettre en question.

**Correction minimale.** « Le **dernier** point ci-dessous, et les deux encadrés ⚠️, demandent une
page et un réglage qui n'existent que dans la console… »

### N6 — markers.md ne cite que `p300_stimulus.py` comme exception, dans une page qui couvre les deux modes

**Sévérité : Minor** · `docs/markers.md:354-355`

**Ce que la doc affirme.**
> ⚠️ Close the pygame app before starting the engine. It opens the headset itself, and the Unicorn
> accepts exactly one connection. (`p300_stimulus.py` is the exception — it draws only.)

**Ce que le code fait réellement.** `errp_stimulus.py` a exactement la même propriété, et c'est le
premier ⚠️ de son module (`errp_stimulus.py:3-8` : « **Ce programme n'ouvre PAS le casque.** C'est ce
qui permet de le lancer EN MÊME TEMPS que le moteur »), confirmé par le montage à 3 terminaux de la
recette 2.8. La section « Before any of this works » a été réécrite pour couvrir les DEUX modes ;
laisser une seule exception nommée fait fermer pour rien le seul émetteur ErrP du dépôt.

**Correction minimale.** « (`p300_stimulus.py` and `errp_stimulus.py` are the exceptions — they draw
only.) »

### N7 — markers.md décrit `taux_rejet` comme un chiffre de séance ; il se remet à zéro à chaque repos

**Sévérité : Minor** · `docs/markers.md:286-288`

**Ce que la doc affirme.**
> `taux_rejet` is the ErrP one to watch: it is the share of epochs thrown away as artifacts, and **a
> session that sits above 50 %** is telling you about the electrodes, not about the brain.

**Ce que le code fait réellement.** `taux_rejet = artefacts / epoques_vues` (errp.py:348-349) porte
sur le **REPOS EN COURS**, pas sur la séance : `_reset_rest` (errp.py:301-321) remet `_epoques_vues`,
`_artefacts` et `_rejet_eleve_dit` à zéro à chaque « Refaire le repos » — et le commentaire du code
insiste sur le fait que c'était le défaut corrigé au tour 2. Les cumuls de séance existent, sous deux
noms **que la doc ne mentionne pas** : `epoques_vues_session` et `artefacts_session`
(errp.py:350-351). Un client qui journalise `taux_rejet` comme un chiffre de séance le verra
retomber à `null` puis repartir de zéro, sans rien pour l'expliquer.

**Correction minimale.** « …and `epoques_vues`, `artefacts`, `taux_rejet` — **all three scoped to the
current rest baseline, reset when you redo the rest** — plus the session totals
`epoques_vues_session` and `artefacts_session`, which never reset. `taux_rejet` is the one to watch:
above 50 % it is telling you about the electrodes, not about the brain. »

### N8 — CLAUDE.md ne dit pas que l'appli pygame est le seul endroit où calibrer le P300 et l'ErrP

**Sévérité : Minor** · `CLAUDE.md:28-31`

**Ce que la doc affirme.**
> L'**application pygame** (`src/research/app.py`, menu à 5 modes) reste le seul accès au **dernier
> mode que le moteur ne sait pas faire** : le c-VEP. Le SSVEP, le neuro, le **Motor Imagery**,
> l'**ErrP** et le **P300** sont publiés par le moteur et pilotés depuis la console — **la
> calibration MI aussi**…

**Ce que le code fait réellement.** L'appli pygame porte aussi les **deux seules** calibrations que
le moteur ne joue pas : `calib_errp` (`research/app.py:1104`) et son équivalent P300, déclarées
`Calib(kind="natif")` dans les deux `ModeSpec` (errp.py:681-682, p300.py:549-551). C'est le geste que
le moteur lui-même prescrit quand il refuse de démarrer — `errp_models.charger` renvoie « lance
`python src/research/app.py`, mode ErrP, et calibre » (errp_models.py:46-47, 82, 96). README:150-151
le dit maintenant correctement ; le document d'accueil est le seul des cinq à laisser croire, par le
voisinage de « la calibration MI aussi », que tout se calibre depuis la console.

**Correction minimale.** « …reste le seul accès au **dernier mode que le moteur ne sait pas faire**
(le c-VEP) **et le seul endroit où calibrer le P300 et l'ErrP** (leur stimulus doit être verrouillé à
la frame — `Calib(kind="natif")`). »

---

## Points mineurs, sans constatation dédiée

- **Durée de la calibration ErrP, deux chiffres.** README:219 annonce « ~7 min (200 trials) » ;
  markers.md:350 raisonne sur « a 5-minute protocol ». Le calcul depuis `errp_calibrate._run_block`
  (1,45 s entre deux pas, plus 0,7 + 0,9 s par fin de course, 200 pas) donne ~6 min hors briefing et
  analyse : README a raison, markers.md arrondit vers le bas. Sans conséquence (la phrase de
  markers.md ne sert qu'à dire que deux calibrations dans la même seconde sont improbables).
- **README:176-181** — le bloc `python examples/receiver.py --stream …` que l'étudiant copie liste
  ssvep, neuro, mi, p300, mais **pas** `decoded_errp`, alors que le tableau juste en dessous
  (README:196) le publie. Une ligne à ajouter.
- **Langue.** Conforme : `README.md` et `docs/markers.md` en anglais, `CLAUDE.md` et
  `docs/recette.md` en français, `docs/SPEC.md` en français — et CLAUDE.md:47-49 nomme désormais
  explicitement les deux exceptions, ce que la revue précédente recommandait. Aucune faute relevée.
  markers.md:327 glose bien le libellé français « Bonnes commandes gardées » (« share of good
  commands kept ») pour un lecteur non francophone, comme demandé.

## À vérifier par exécution

Rien dans ce rapport n'en dépend. Les trois commandes qui confirmeraient le plus directement :

- `python src/core/modes/errp.py` — attendu : vert, y compris le test de monotonie
  (errp.py:935-967), qui est la garde de I4 et de la colonne du milieu de P3.
- `python src/core/errp_models.py` — attendu : vert (refus des hérités, des noyaux hérités et des
  calibrations dégénérées, tri du plus récent au plus ancien).
- Pour N1 : `python src/core/server.py --mode errp` puis, depuis un client,
  `submit("set_params", id="errp", params={"stream_in": "mon_flux"})` — attendu :
  `{"accepted": False, "reason": "« Flux de marqueurs » : 'mon_flux' n'est pas un choix valide
  (EEG_API_Unicorn_stim)"}`, ce qui démontre le refus que markers.md:38 déclare possible.
- Pour N3 : `python src/core/server.py --synthetic --mode errp` puis
  `python src/research/errp_stimulus.py --windowed` — attendu : **aucun** message
  « feedback(s) reçus pendant la CHAUFFE/le REPOS » ; le même essai avec `--no-wait` doit le
  produire.
