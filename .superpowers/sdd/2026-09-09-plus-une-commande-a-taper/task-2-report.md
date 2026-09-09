# Tâche 2 — `MesureRuntime` : un protocole qui rend un verdict

**Statut : livré.** Commit `ea0c6b6`, sur `main`.

| fichier | ce qui y a été fait |
|---|---|
| `src/core/modes/mesure.py` | *(créé)* `Etape`, `MesureSpec`, `MesureRuntime`, et son autotest (43 assertions) |
| `src/core/server.py` | `self.mesure`, `_UNE_SEULE_ACTIVITE`, les deux refus, `start_mesure`/`cancel_mesure`, `_start_mesure`, le tick dans `run()`, `snapshot()["mesure"]`, `_smoke_mesure()` |
| `src/core/modes/registry.py` | `MESURES`, `get_mesure`, `catalogue_mesures`, `_params_serialises`, et le contrôle des mesures dans `check()` |
| `src/core/modes/calibration.py` | `_journal` / `_nom_du_calcul` : le message d'échec de `_terminer`, hérité, ne dit plus « entraînement » sous une mesure |

---

## Ce qui a été livré

### La forme, répliquée par HÉRITAGE et non par copie

`MesureRuntime` hérite de `CalibrationRuntime`. C'est l'argument de `marker_calib.py`, repris tel
quel : `console/calib_page.py` est générique et pilotée par `snapshot()`, **un champ manquant ne
lève rien** — la page reste simplement vide. `state()`, `restant_s()`, `terminee` et `_terminer()`
(avec son traitement d'exception) viennent donc du parent, non redéfinis. L'assertion qui le tient
est une ÉGALITÉ, pas une inclusion :

```
OK   …et c'est EXACTEMENT celui d'une calibration : `state()` n'est pas redéfinie ici, elle est
     héritée (aucun écart)
```

Le seul obstacle à l'héritage était `CalibrationRuntime.__init__`, qui fait
`self.calib = spec.calibration`. Une mesure n'a pas de mode au-dessus d'elle : `MesureSpec` expose
donc une propriété `calibration` qui rend `self`. C'est documenté sur place comme « son propre
`Calib` » — et c'est ce qui évite de réécrire `__init__` et `state()` pour un seul libellé.

### La ligne du temps

`chauffe` → `essais` → `mesure` → `fini`/`annule`, comme demandé. `PHASES` est **propre au
module** ; `PHASES_TERMINALES` est **importée** de `calibration.py`, jamais recopiée — c'est
l'objet que `calib_page.py` importe pour décider quand montrer l'écran de résultat, et le test
vérifie l'identité (`is`), pas l'égalité.

⚠️ **J'ai refusé de réutiliser la phase `entrainement` du parent.** C'était le chemin le plus
court (aucune surcharge de `tick`), mais `snapshot()["mesure"]["phase"] == "entrainement"` sur un
protocole qui n'entraîne rien est un mensonge dans l'état publié, pour un confort d'héritage.

### Le protocole : des étapes, dont certaines seulement sont enregistrées

Le socle est une suite d'`Etape(nom, duree_s, enregistre, instruction, rappel)`. À la fin d'une
étape enregistrée, `engine.recent_window(etape.duree_s)` est prélevée et empilée avec son
étiquette — même geste, même garde de longueur que `CalibrationRuntime._pas_essai`.

Cette forme couvre les deux mesures à venir sans rien deviner :
prép. 3 s → **8 s yeux ouverts** → prép. 3 s → **8 s yeux fermés** pour la tâche 3 ; une paire
cue/fixation par essai pour la tâche 9, où seule la fixation est prélevée.

Deux unités distinctes, et c'est délibéré : `total()` compte les étapes **enregistrées**
(l'avancement), `duree_estimee_s()` compte **tout** (la personne vit aussi les préparations). Un
test tient la paire : à la 4e étape sur 4, l'écran affiche « 1 sur 2 ».

### Rien, absolument rien, sur le disque

`dossier_ou_lever()` est **neutralisée** : elle refuse au lieu de rendre un chemin. Sans ça, une
mesure future aurait pu écrire un fichier que `save_calibration` déplacerait dans `data/`. Le
runtime n'accepte même pas l'argument `dossier=` dans sa signature — un ajout distrait échoue
bruyamment. Vérifié par empreinte de `data/` avant et après une séance complète.

### Le refus d'une seconde activité — la moitié sérieuse

Le patron est celui de `_smoke_vol_marqueurs` : une phrase écrite **une fois**
(`_UNE_SEULE_ACTIVITE`), deux méthodes qui rendent une raison ou `None`
(`_refus_pour_calibration_en_cours`, `_refus_pour_mesure_en_cours`), servies **aux deux
instants** — `submit()` et la boucle (`_start_calibration`, `_start_mesure`).

Quatre portes, plus le contrôle qui rend la garde falsifiable (une activité **terminée** ne bloque
plus rien — sans lui, un refus écrit « dès qu'une calibration existe » passerait tout le reste).

**La preuve du rouge** (étape 4 du plan) — refus du sens 2 retiré aux deux endroits :

```
  OK   sens 1, côté BOUCLE — la course est rattrapée : aucune calibration n'est construite (None)
  ÉCHEC et RÉCIPROQUEMENT — c'est le sens qu'on oublie en croyant avoir fermé la porte
        ({'accepted': True, 'command': 'start_mesure', …})
  ÉCHEC sens 2, côté BOUCLE — la course symétrique est rattrapée elle aussi
  ÉCHEC une calibration TERMINÉE ne bloque plus rien   ← cascade : la mesure interdite tourne encore
  ÉCHEC …et annuler sans mesure en cours est refusé avec un motif (None)   ← même cascade
[mesure] VERDICT : PROBLÈME        (code de sortie 1)
```

Remis en place :

```
  OK   et RÉCIPROQUEMENT — c'est le sens qu'on oublie en croyant avoir fermé la porte
  OK   sens 2, côté BOUCLE — la course symétrique est rattrapée elle aussi
[mesure] VERDICT : OK
```

---

## Les trois écarts au plan, et pourquoi

1. **`srv.submit("start_mesure")` ne suffit pas à peupler `srv.mesure`.** L'extrait du plan
   enchaîne `submit("start_mesure")` puis `submit("start_calibration")` en attendant un refus —
   or `submit` ne fait que **mettre en file** (c'est sa docstring), donc `srv.mesure` est encore
   `None` et le second `submit` testerait un moteur vierge, c'est-à-dire rien. J'ai inséré
   `srv._drain_commands()` entre les deux, avec le pourquoi en commentaire. Le test est resté
   fidèle à l'intention ; il l'est devenu à la mécanique.

2. **L'identifiant `"alpha"` n'existe pas encore** (c'est la tâche 3). Le test enregistre une
   mesure factice sous l'id `"essai"` en remplaçant `registry.MESURES` le temps du passage — le
   patron que `registry._selftest` emploie déjà pour `MODES`.

3. **Le catalogue des mesures vit dans `registry.py`, pas dans `mesure.py`.** Contrainte
   d'imports : une mesure concrète importera `MesureRuntime` de `mesure.py`, donc `mesure.py` ne
   peut pas importer les mesures en retour. C'est exactement ce que `registry.py` fait déjà pour
   les modes. `get_mesure()` **parcourt** `MESURES` au lieu d'un index figé à l'import,
   précisément pour que le remplacement du point 2 soit vu.

---

## Ce qui reste DEHORS

- **Aucune mesure concrète.** Ni le contrôle alpha (tâche 3), ni le taux SSVEP (tâche 9).
  `registry.MESURES` est un tuple **vide** ; les deux tâches y ajoutent leur `SPEC`.
- **Aucun écran.** Pas de `mesure_page.py`, pas de tuile dans la grille. La tâche 2 ne livre donc
  **aucun chemin graphique** — c'est conforme au découpage du plan (tâche 3 : « puis
  `src/console/mesure_page.py` et sa tuile dans la grille »), mais la contrainte globale « une
  capacité livrée sans chemin graphique est une tâche INCOMPLÈTE » n'est satisfaite qu'**à la fin
  de la tâche 3**. Si la tâche 3 devait sauter, ce socle serait du code que personne ne peut
  atteindre.
- **`snapshot()["mesure"]` n'est lu par personne** aujourd'hui, pour la même raison.
- **Rien n'a vu un cerveau.** Ce socle n'a été exercé que sur un moteur factice et du signal nul.

---

## Ce que j'ai livré au-delà du strict cahier des charges

Trois choses, chacune parce que son absence forçait la tâche 3 à recopier quelque chose :

- **`catalogue_mesures()` + `_params_serialises()`** dans `registry.py`. Sans le premier, la
  console réécrirait libellés et briefings dans son propre code — le « catalogue recopié » que
  `CLAUDE.md` interdit. Le second extrait le bloc de sérialisation des `Param` que la calibration
  et la mesure partagent maintenant (le bloc des params d'un *mode* garde son écriture : il tire
  son `default` d'une résolution unique, cf. son commentaire).
- **Le contrôle des mesures dans `registry.check()`** : identifiant en double, collision avec un
  identifiant de MODE, `runtime_cls` absent, défauts hors bornes, aide manquante. Cinq défauts qui
  ne lèveraient rien à l'exécution.
- **`_journal` / `_nom_du_calcul` sur `CalibrationRuntime`.** `_terminer` est héritée telle
  quelle : un contrôle alpha raté s'annonçait « `[calib] entraînement impossible` », et un
  étudiant y chercherait un modèle que personne n'a demandé. Deux attributs de classe, aucun
  comportement changé pour les calibrations (`[calib]` reste `[calib]`).

---

## Réserves

1. **`MesureSpec.calibration` qui rend `self` est le point discutable du fichier.** C'est le prix
   payé pour hériter de `state()` sans le recopier, et je le crois bien payé — mais c'est une
   entorse à la lisibilité, et un relecteur qui trébuche dessus aura raison de le dire. La
   solution structurellement propre serait d'extraire une base commune
   « protocole minuté » de `CalibrationRuntime`, ce qui toucherait les quatre calibrations et
   `marker_calib.py` : hors budget de cette tâche, et à faire quand une troisième famille de
   protocole apparaîtra, pas avant.

2. **Le socle n'a jamais joué autre chose que sa propre mesure factice.** Sa forme (`Etape` +
   `_mesurer`) est déduite des deux protocoles à venir tels que le plan les décrit, pas d'une
   mesure écrite. La tâche 3 est le premier vrai client, et c'est elle qui dira si le hook suffit
   — notamment sur un point que j'ai laissé ouvert : **une mesure dont le sujet a les yeux fermés
   ne peut RIEN lire à l'écran.** Le contrôle alpha en dépend, et le socle ne fournit
   volontairement aucun top audio (cf. point 3).

3. **`etape` reste vide de bout en bout**, comme dans `marker_calib.py` : `CalibPage._maybe_beep`
   joue un son sur le front montant de `etape` vers « cue », et le nom d'étape voyage donc dans
   `classe`. Conséquence assumée : **aucune mesure ne peut faire biper la console aujourd'hui**.
   La tâche 3 devra le demander explicitement si elle en a besoin (et je pense qu'elle en a
   besoin) — le socle n'ouvre pas cette porte par accident, mais il ne l'a pas ouverte du tout.

4. **`_phase_of` n'a pas bougé** : une mesure en cours ne change pas la phase publique du flux
   `status`. Choisi, pas oublié — une mesure n'empêche aucun décodage, et la mesure SSVEP a
   justement besoin que le mode tourne. Un client qui se met en pause sur `calibrating` continuera
   donc pendant une mesure. Si ça devait changer, ça ajouterait une valeur au vocabulaire public
   de la spec §6, ce qui n'est pas une décision de tâche 2.

5. **Diff plus volumineux que la cible.** ~39 Ko pour `mesure.py` (dont l'autotest et le
   commentaire, au format du dépôt — `marker_calib.py` fait 871 lignes pour un rôle comparable) et
   ~15 Ko pour les trois fichiers modifiés. Au-dessus des ~40 Ko visés.

---

## Tests

```
python src/core/modes/mesure.py        → [mesure] VERDICT : OK        (43 assertions)
python src/core/modes/calibration.py   → OK
python src/core/modes/marker_calib.py  → OK
python src/core/modes/mi_calib.py      → OK
python src/core/modes/registry.py      → OK
python src/core/modes/contract.py      → OK
python src/stimulus/registry.py        → [stim-registry] VERDICT : OK
python src/console/app.py --smoke      → [console-smoke] VERDICT : OK
python src/core/server.py --smoke      → tous les verdicts OK, SAUF [smoke-frontiere]
```

`python src/research/app.py --smoke` (listé dans `CLAUDE.md`) **n'existe plus** : le fichier a été
retiré par le chantier précédent. Signalé ici pour la tâche 11, qui met la doc à jour.

L'état de `[smoke-frontiere]`, inchangé par cette tâche — **12 violations, les mêmes six
fichiers qu'à la tâche 1** :

```
[smoke-frontiere] ÉCHEC : research/alpha_check.py:21 importe brainflow
[smoke-frontiere] ÉCHEC : research/alpha_check.py:24 importe core.acquisition
[smoke-frontiere] ÉCHEC : research/live_ssvep.py:31 importe core.acquisition
[smoke-frontiere] ÉCHEC : research/live_ssvep.py:90 importe pygame
[smoke-frontiere] ÉCHEC : research/live_ssvep.py:180 importe pygame
[smoke-frontiere] ÉCHEC : research/live_ssvep.py:275 importe pygame
[smoke-frontiere] ÉCHEC : research/ssvep_analyze.py:30 importe core.acquisition
[smoke-frontiere] ÉCHEC : research/ssvep_guided.py:45 importe core.acquisition
[smoke-frontiere] ÉCHEC : research/ssvep_guided.py:129 importe pygame
[smoke-frontiere] ÉCHEC : research/ssvep_stimulus.py:107 importe pygame
[smoke-frontiere] ÉCHEC : research/ui.py:52 importe pygame
[smoke-frontiere] ÉCHEC : research/ui.py:88 importe core.acquisition
[smoke-frontiere] 58 fichiers scannés, 12 violation(s) de frontière
[smoke-frontiere] VERDICT : PROBLÈME
```

**Aucune violation hors de `research/`** : le nouveau `core/modes/mesure.py` est le 58e fichier
scanné (57 au départ) et il passe.
