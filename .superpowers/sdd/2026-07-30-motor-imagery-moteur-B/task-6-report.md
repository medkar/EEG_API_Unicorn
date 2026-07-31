# Task 6 Report: la console — page de calibration, bips, liste des modèles

## Statut
**DONE_WITH_CONCERNS** — tout est vert (les trois smokes, en série, aucun résidu), mais deux
écarts au brief : deux bugs pré-existants dans `params_form.py`, découverts et corrigés en
construisant cette page, et l'étape 8 (fenêtre réelle) sciemment NON FAITE sur consigne explicite.

## Commit
`bf586c9` — *Give the console a calibration page: brief, run, honest result*
(parent `95a62de` — task 5 — HEAD de `main` au moment du travail). 5 fichiers, +526/-1.

## Ce qui a été fait, fichier par fichier

### `src/console/beeps.py` (créé)
Copié VERBATIM depuis le brief — les trois tops latéralisés (`GAUCHE`/`DROITE`/`REPOS`),
`QAudioSink`/`QBuffer`, `disponible`/`raison` francs, `jouer()` qui ne lève jamais. Aucune
modification.

### `src/console/params_form.py` (modifié)
Trois changements :
1. **`set_choices(cle, choix, garder=True)`** — copié VERBATIM depuis le brief, ajouté en fin de
   classe.
2. **`_champ()`, branche `"choice"`** — ajout de `if param["default"] is not None:
   champ.setCurrentText(str(param["default"]))`. **Écart au brief, pas demandé explicitement,
   mais nécessaire** : voir « Écarts » ci-dessous.
3. **`values()`, branche `"choice"`** — remplacé `out[param["key"]] = champ.currentText()` par une
   recherche du choix d'ORIGINE (son type inclus) parmi `param["choices"]`, avec repli sur le texte
   brut si rien ne correspond. **Même écart, même raison.**

### `src/console/calib_page.py` (créé)
`CalibPage(spec, console)`, avec le signal `retour` et `update_from(state)`. Trois blocs
(`QGroupBox`) construits une fois dans `__init__`, montrés/cachés dans `update_from` selon la
phase — jamais reconstruits :
- `bloc_avant` (« Avant de commencer ») : `briefing` (texte du CONTRAT, `Calib.briefing`, JAMAIS
  recopié), `audio_avertissement` (fixé une fois, si `console.beeps.disponible` est faux),
  `formulaire` (`ParamsForm` sur `Calib.params`), `duree` (estimée, LUE dans `calib_state`, jamais
  calculée), `bouton_commencer`.
- `bloc_pendant` (« Séance en cours ») : `consigne`, `classe_cuee`, `rappel`, `decompte`,
  `progression`, `barre` (QProgressBar), `bouton_abandon`.
- `bloc_apres` (« Résultat ») : `resultat` (verdict + accuracy HONNÊTE + hasard, ou le problème
  si annulée), `details` (nom du modèle, essais, fenêtres, classes — jamais `cv_naive`),
  `honnetete` (le texte HONNETETE verbatim du brief, visible seulement s'il y a un résultat).

`update_from` filtre sur `calib_state["mode_id"] == self.mode_id` (défensif : le moteur n'a
qu'une seule calibration, mais une page ne doit jamais afficher celle d'un autre mode si ce
filtre venait à compter un jour). Règle retenue pour la visibilité, motivée par la formulation du
brief elle-même (« Avant… absent OU **terminé** » — le mot exact de
`CalibrationRuntime.terminee`) : `bloc_avant` est visible chaque fois qu'AUCUNE séance ne tourne
(calibration absente OU phase `fini`/`annule`), `bloc_pendant` uniquement pendant une séance
active, `bloc_apres` uniquement une fois terminée. `bloc_avant` et `bloc_apres` sont donc VISIBLES
ENSEMBLE juste après la fin d'une séance : l'étudiant lit son résultat et peut relancer sans
naviguer ailleurs — sans ce chevauchement, rien ne permettrait de démarrer une deuxième
calibration depuis cette page (le seul bouton « Commencer » vivrait dans un bloc jamais montré
en même temps que le résultat).

`_maybe_beep` retient `(phase, essai, etape)` du dernier top JOUÉ et ne rejoue que si cette clé
change ET que `etape == "cue"` — remis à `None` dès que la séance n'est plus en cours, pour
qu'une séance ultérieure sonne de nouveau son tout premier essai.

### `src/console/mode_page.py` (modifié)
Bouton « Calibrer » (visible seulement si `spec["calibration"]["kind"] == "console"`) ajouté dans
l'entête, avant `entete.addStretch(1)` ; méthode `rafraichir_choix()` ajoutée en fin de classe.
Les deux blocs copiés VERBATIM depuis le brief.

### `src/console/app.py` (modifié)
- Imports : `from console.beeps import Beeps`, `from console.calib_page import CalibPage`.
- `Console.__init__` : `self.beeps = Beeps()` + boucle qui construit une `CalibPage` par mode
  `status == "moteur"` dont `calibration.kind == "console"`, chacune ajoutée à `self.stack` et
  connectée à `show_grid`. Copié VERBATIM.
- `show_calibration(mode_id)` ajoutée ; `show_mode(mode_id)` modifiée pour appeler
  `page.rafraichir_choix()` avant de changer de page. Copié VERBATIM.
- `fake_state()` : `"calibration": None` ajouté.
- `_smoke()` : le bloc du brief (Step 6) inséré tel quel juste après le bloc Motor Imagery
  existant, plus **un bloc de régression que j'ai ajouté moi-même**, décrit dans « Écarts ».

## Écarts par rapport au brief

### 1. Deux bugs dans `ParamsForm`, trouvés AVANT d'écrire un seul écran

En construisant le formulaire de calibration à partir du contrat réel (`mi_calib.CALIB.params`,
`trials_per_class` avec `choices=MI_SESSIONS=(10, 14, 18, 26)`, `default=MI_SESSIONS[1]=14`),
j'ai vérifié empiriquement — avant d'écrire `calib_page.py` — que `ParamsForm` ne gérait pas ce
cas :

```
$ python -c "... contract.validate(mi_calib.CALIB, {'trials_per_class': '14'})"
string "14": None | « Essais par classe » : '14' n'est pas un choix valide (10, 14, 18, 26)
int 14     : {'trials_per_class': 14} | None
```

```
$ python -c "... ParamsForm(calib_params) ; form.champs['trials_per_class'].currentText() ..."
texte affiche par defaut avant fix : '10'
values() avant fix                 : {'trials_per_class': '10'}
```

Deux défauts distincts, jamais visibles avant ce chantier parce que `trials_per_class` est le
PREMIER « choice » du projet dont les choix sont des ENTIERS (pas des chemins de fichiers, comme
`model`, seul autre « choice » existant) et dont le défaut n'est PAS le premier choix (14, pas 10) :
1. `_champ()` ne plaçait jamais le `QComboBox` sur `param["default"]` — il affichait toujours son
   premier élément. Un étudiant qui ouvre la page pour la première fois et clique « Commencer »
   sans toucher au menu déroulant aurait lancé 10 essais/classe, pas 14, en contradiction directe
   avec l'aide du contrat (« Commence par la valeur par défaut »).
2. `values()` rendait `champ.currentText()`, TOUJOURS une chaîne. Même le défaut correctement
   affiché ("14") aurait été refusé par `contract.validate`, qui compare contre des ENTIERS.

Les deux sont corrigés dans `params_form.py` (voir ci-dessus), vérifiés à la fois par un script
jetable (ci-dessus) et par un ajout dans `_smoke()` de `app.py`, contre le VRAI moteur et le VRAI
`contract.validate` — le bloc de calibration donné par le brief utilise le moteur FACTICE, qui
n'appelle jamais `contract.validate` et n'aurait rien détecté :

```python
cal_reelle = reelle.calib_pages["mi"]
chk(cal_reelle.formulaire.champs["trials_per_class"].currentText() == "14", ...)
valeurs_calib = cal_reelle.formulaire.values()
chk(valeurs_calib["trials_per_class"] == 14 and isinstance(valeurs_calib["trials_per_class"], int), ...)
ack_calib = reelle.commande("start_calibration", id="mi", params=valeurs_calib)
chk(ack_calib.get("accepted"), ...)
```

**Pourquoi je l'ai fait plutôt que de le signaler seulement** : c'est dans un fichier explicitement
sur ma liste (`params_form.py`), le correctif est minimal et rétrocompatible (vérifié : aucun
changement de comportement pour `model`, le seul autre « choice » du projet, choix vides compris),
et sans lui le bouton « Commencer » — l'action CENTRALE de cette tâche — aurait été refusé par le
vrai moteur à chaque clic sur le défaut, alors que le smoke (moteur factice) serait resté vert.
Une tâche qui « a l'air de marcher » mais ne marche pas contre le vrai moteur est exactement le
défaut que ce produit cherche à éliminer ailleurs.

### 2. Étape 8 (fenêtre réelle) — NON FAITE, sur consigne explicite

Le brief la marque « obligatoire ». Je ne l'ai PAS exécutée : l'agent qui m'a confié la tâche a
explicitement demandé de la sauter, poste partagé, casque physique impliqué. Notée ici comme non
faite ; au coordinateur de la faire quand la machine est libre. Tout ce qui suit dans le brief
(consigne visible, décompte qui avance, tops audibles ou avertissement honnête si l'audio manque)
n'a donc été vérifié que par lecture de code et par les scripts ad hoc ci-dessus (`Beeps()` réel,
`disponible=True`, `jouer()` ne lève pas) — jamais par les yeux sur un écran réel.

### 3. Réordonnancement visuel (ajout personnel, mineur)

Le brief ne précise pas l'ordre d'empilement des trois blocs. Comme `bloc_avant` et `bloc_apres`
sont visibles ensemble une fois la séance terminée (cf. ci-dessus), je les ai ordonnés
`bloc_pendant`, `bloc_apres`, `bloc_avant` (au lieu de l'ordre de déclaration) : un étudiant qui
revient sur cette page après une séance lit son résultat AVANT de retomber sur le briefing d'une
nouvelle séance. Aucun impact sur le smoke (qui ne teste que le contenu des attributs, jamais leur
position) ; un choix cosmétique documenté dans un commentaire à l'endroit du changement.

## Commandes de test lancées, EN SÉRIE, avec leur sortie réelle

### 1. `python src/console/app.py --smoke`
89 lignes `OK`, zéro `ÉCHEC` :
```
  OK   « Calibrer » ouvre la page de calibration du MI
  OK   et seul le MI en a une — le c-VEP et le P300 ont un stimulus natif (['mi'])
  OK   le briefing affiché vient du contrat du mode
  OK   et « Commencer » est actif
  OK   cliquer « Commencer » soumet start_calibration avec la durée choisie ([('start_calibration', {'id': 'mi', 'params': {'trials_per_class': 14}})])
  OK   la consigne du moteur est affichée telle quelle (Imagine : SERRE le POING GAUCHE)
  OK   le décompte vient du moteur, pas d'un timer local (2.4 s)
  OK   et la progression nomme les deux nombres (essai 7 sur 42)
  OK   le formulaire est verrouillé pendant la séance : le changer n'aurait aucun effet
  OK   « Abandonner » passe par la file de commandes ([('cancel_calibration', {})])
  OK   l'accuracy affichée est l'HONNÊTE (FAIBLE — ré-essaie — accuracy honnête (validation croisée par essai) : 40.1 % (hasard 33 %))
  OK   et JAMAIS la naïve, qui est gonflée de 10 à 16 points (...)
  OK   le niveau du hasard est à côté — sans lui, 40 % ne veut rien dire (...)
  OK   le nom du modèle produit est donné (Modèle : mi_model_20260730-141205.joblib ...)
  OK   et la page dit franchement ce qu'un résultat modeste signifie
  OK   une calibration annulée dit pourquoi (Calibration abandonnée : ValueError : pas assez de données)
  OK   et la page de calibration ramène sur la grille
  ...
  OK   le formulaire de calibration affiche le DÉFAUT déclaré (14), pas le premier choix (14)
  OK   et rend un ENTIER, pas '14' — sinon le moteur le refuse comme choix invalide (14)
  OK   soumis au VRAI validateur (pas au moteur factice), ce défaut est accepté ({'accepted': True, 'command': 'start_calibration', 'id': 'mi', 'params': {'trials_per_class': 14}})
  ...
[console-smoke] VERDICT : OK
```
`CONSOLE_EXIT_CODE=0`.

### 2. `python src/core/server.py --smoke` (non-régression)
```
[smoke] VERDICT : OK
[smoke-frontiere] VERDICT : OK
[smoke-repos] VERDICT : OK
[smoke-ssvep] VERDICT : OK
[smoke-neuro] VERDICT : OK
[smoke-mi] VERDICT : OK
[smoke-calib] VERDICT : OK
[smoke-cumul] VERDICT : OK
[smoke-proposition] VERDICT : OK
```
`SERVER_EXIT_CODE=0`, zéro `ÉCHEC`.

### 3. `python src/research/app.py --smoke` (non-régression)
```
[app] smoke OK : menu + SSVEP + c-VEP (eCCA & rCCA) + MI + P300 + neuro + ErrP(cal+démo) câblés (headless).
```
`RESEARCH_EXIT_CODE=0`, zéro `ÉCHEC`.

Les trois commandes ont été lancées STRICTEMENT en série (jamais deux moteurs/applis en même
temps), comme l'exige le projet.

## Vérification d'absence de résidu
```
$ git status --porcelain
 M src/console/app.py
 M src/console/mode_page.py
 M src/console/params_form.py
?? src/console/beeps.py
?? src/console/calib_page.py
```
(avant `git add`/`commit` — exactement les 5 fichiers attendus, rien d'autre).
```
$ ls data/ | grep 2026073   # rien daté d'aujourd'hui (2026-07-31)
$ ls data/*smoke*           # No such file or directory
```
Aucun fichier `data/` daté d'aujourd'hui ; les `mi_model_*`/`mi_calib_*` existants sont tous
antérieurs (20–22 juillet), préexistants. Après `git add` + `commit` : `git status --porcelain`
vide, arbre propre.

## Auto-relecture

### Les trois pièges signalés dans la consigne
1. **Listes dynamiques jamais résolues dans le rafraîchissement périodique** — respecté :
   `CalibPage` ne référence AUCUN `choices_fn`/`set_choices` (les réglages de calibration,
   `trials_per_class`, sont un `choice` STATIQUE, pas dynamique) ; `rafraichir_choix()`
   (`mode_page.py`) n'est appelée QUE depuis `show_mode()` (entrée dans la page) — jamais depuis
   `update_from()`/le `QTimer`. Vérifié en relisant le fichier après coup : aucun appel à
   `rafraichir_choix` ni à `set_choices` en dehors de ce seul point.
2. **Les tops ne se rejouent pas à chaque rafraîchissement** — `_maybe_beep` compare
   `(phase, essai, etape)` au dernier top JOUÉ, pas au dernier état VU ; un rafraîchissement qui
   répète le même `etape == "cue"` ne rejoue rien. **Limite connue, non couverte par un test** :
   pendant l'ÉCHAUFFEMENT (`phase == "echauffement"`), `essai` (le compteur d'essais ENREGISTRÉS)
   ne bouge pas d'un tirage à l'autre — `core/modes/calibration.py::_pas_essai` ne l'incrémente
   que pendant `phase == "essais"`. Deux tirages consécutifs de la MÊME classe pendant
   l'échauffement produiraient donc la MÊME clé `(phase, essai, etape)` et le second top ne
   sonnerait pas. J'ai suivi le brief à la lettre (la clé qu'il donne, verbatim) plutôt que
   d'improviser une clé plus robuste (par ex. sur une transition `etape != "cue" -> "cue"`, qui
   couvrirait ce cas mais n'est pas ce que le brief décrit) : l'impact réel est mineur (un top
   d'échauffement manqué, sur une classe déjà annoncée par la CONSIGNE affichée à l'écran ; les
   essais ENREGISTRÉS, en phase `"essais"`, ne sont pas concernés puisque `essai` y change à
   chaque tirage) et non exercé par le smoke donné. Signalé plutôt que corrigé en silence.
3. **La phrase d'honnêteté et le hasard, obligatoires avec le résultat** — `honnetete` (texte
   HONNETETE verbatim) n'est visible QUE quand `resultat is not None` (phase `fini`) ; `resultat`
   formate TOUJOURS `f"{cv*100:.1f} % (hasard {hasard*100:.0f} %)"`, jamais `cv_naive`. Vérifié par
   les 3 `chk` dédiés du smoke (40.1 présent, 55.6 absent, 33 présent) plus la présence de
   « séance de référence ».

### Ce qui n'a pas été touché en dehors du périmètre
- Aucun fichier hors des 5 listés (`beeps.py`, `calib_page.py`, `mode_page.py`,
  `params_form.py`, `app.py`).
- `src/core/server.py`, `src/core/modes/*`, `src/console/grid.py` : non touchés, comme demandé
  (d'autres agents y travaillaient).
- Étape 8 : sciemment sautée, sur consigne explicite du briefing de tâche (pas du brief lui-même).

### Point resté ouvert, volontairement
La limite n°2 ci-dessus (tirages consécutifs identiques en échauffement) : je ne l'ai pas corrigée
pour rester fidèle à la clé EXACTE donnée par le brief, plutôt que d'introduire silencieusement une
règle différente de celle décrite. Si le coordinateur préfère la couverture complète, la clé la
plus robuste serait un simple bord montant sur `etape` (`"cue"` alors qu'elle ne l'était pas au
rafraîchissement précédent), indépendant de `essai`.

## Résumé des tests (une ligne)
3 commandes lancées EN SÉRIE (`console/app.py --smoke`, `core/server.py --smoke`,
`research/app.py --smoke`), toutes en exit code 0 / VERDICT OK, zéro `ÉCHEC`, `git status` propre
après commit, aucun fichier `data/` daté d'aujourd'hui ; 2 bugs pré-existants de `params_form.py`
trouvés et corrigés (défaut d'un `choice` jamais sélectionné, type perdu par `values()`), vérifiés
contre le VRAI moteur en plus du bloc de calibration factice donné par le brief ; étape 8 non
faite sur consigne explicite ; une limite mineure et non testée documentée (tops d'échauffement
consécutifs de même classe).

---

## Tour de correction 1/5 — le diagnostic que j'avais signalé était juste en NATURE, faux en AMPLEUR

### Statut
**DONE**

### Commit
`5aca940` — *Sound every warmup beep, not just the first of six*
(parent `bf586c9` — mon propre commit de la tâche 6 ; 2 fichiers, `src/console/calib_page.py` et
`src/console/app.py`, +85/-15).

### Ce que la relecture a corrigé dans mon propre diagnostic
Mon rapport initial disait : « deux tirages consécutifs de la MÊME classe pendant l'échauffement
produiraient la même clé » — une coïncidence de tirage, rare, à impact mineur. **C'était faux.**
La classe ne fait même pas partie de la clé `(phase, essai, etape)` : `essai` (compteur d'essais
ENREGISTRÉS) ne bouge JAMAIS pendant `phase == "echauffement"` — seule `core/modes/
calibration.py::_pas_essai` l'incrémente, et seulement `if self.phase == "essais":` — et `phase`
elle-même reste `"echauffement"` tout du long. La clé au moment `etape == "cue"` valait donc
LITTÉRALEMENT `("echauffement", 0, "cue")` pour les SIX essais d'échauffement du MI
(`MI_WARMUP_PER_CLASS = 2` × 3 classes), quelle que soit la classe tirée. Un seul top sur six —
à CHAQUE séance, pas par malchance. Aucun `chk` de mon diff ne l'exerçait : la fixture
« en_cours » démarre directement en `phase: "essais"`.

### Ce qui a été fait, dans l'ordre demandé (l'échec AVANT, puis le correctif)

**1. Ajout du test, contre le code encore BUGUÉ.** Dans `_smoke()` de `app.py`, juste après le
bloc de calibration existant (après le `cal.bouton_retour.click()` qui referme la page) : je
rouvre la page de calibration, remplace `console.beeps` par un enregistreur (`_BeepsEnregistreur`,
juste un `.jouer(classe)` qui empile), rejoue une séquence de 6 essais d'échauffement
(`phase: "echauffement"`, `essai` figé à 0, classes `["GAUCHE", "DROITE", "REPOS", "GAUCHE",
"DROITE", "REPOS"]` — délibérément pas toutes distinctes d'un essai à l'autre, pour prouver que la
clé ne dépend NI de la classe NI d'un compteur figé), chaque `cue` REJOUÉ une deuxième fois avant
de passer à `imagerie` (pour vérifier dans la même passe qu'un rafraîchissement à état identique
ne sonne pas deux fois), puis restaure `console.beeps` dans un `finally`.

**Lancé AVANT toute correction** (`python src/console/app.py --smoke`) :
```
  ÉCHEC chacun des SIX essais d'échauffement sonne son propre top, pas un seul sur six, et sans
        doublon sur le rafraîchissement répété du même cue (['GAUCHE'])
[console-smoke] VERDICT : PROBLÈME
```
`EXIT_CODE=1` — un seul top enregistré (`['GAUCHE']`) sur les six attendus, exactement comme
diagnostiqué : le test échoue bien pour la RAISON attendue, pas pour une autre.

**2. Le correctif, dans `calib_page.py`.** `_maybe_beep` ne retient plus `(phase, essai, etape)`
mais la seule `etape` du rafraîchissement PRÉCÉDENT (`self._etape_precedente`), et sonne sur le
FRONT MONTANT : `etape == "cue"` alors qu'elle ne l'était pas juste avant. Indépendant de `essai`
et de `phase`, donc insensible au fait que l'un ou l'autre reste figé pendant l'échauffement.
Retiré aussi la remise à zéro dans `update_from` (`if not en_cours: self._derniere_cue_sonnee =
None`) : elle n'a plus d'utilité — `_maybe_beep` n'est appelée QUE si `en_cours`, et le moteur ne
quitte jamais `etape == "cue"` directement vers une phase terminale
(`_pas_essai`/`_commencer_essais`/`_terminer` posent tous `etape = ""` avant
`entrainement`/`fini`/`annule`), donc `_etape_precedente` ne peut structurellement jamais valoir
« cue » au moment où une nouvelle séance démarre — pas besoin de la forcer.

### Commandes de test lancées, EN SÉRIE, avec leur sortie réelle (APRÈS correction)

**1. `python src/console/app.py --smoke`**
```
  OK   chacun des SIX essais d'échauffement sonne son propre top, pas un seul sur six, et sans
       doublon sur le rafraîchissement répété du même cue (['GAUCHE', 'DROITE', 'REPOS', 'GAUCHE',
       'DROITE', 'REPOS'])
  OK   et la page de calibration ramène sur la grille, après ce test aussi
  ...
[console-smoke] VERDICT : OK
```
`EXIT_CODE=0`. Les six classes reviennent dans l'ordre exact où elles ont été cuées, une seule
fois chacune — la répétition du même `cue` (deuxième `apply_state` avant de passer à `imagerie`)
n'a produit AUCUN top supplémentaire. `grep ÉCHEC` sur la sortie complète : aucune occurrence.

**2. `python src/core/server.py --smoke`** (non-régression, imposée par la consigne de correction) :
```
[smoke] VERDICT : OK
[smoke-frontiere] VERDICT : OK
[smoke-repos] VERDICT : OK
[smoke-ssvep] VERDICT : OK
[smoke-neuro] VERDICT : OK
[smoke-mi] VERDICT : OK
[smoke-calib] VERDICT : OK
[smoke-cumul] VERDICT : OK
[smoke-proposition] VERDICT : OK
```
`EXIT_CODE=0`. Les deux commandes ont été lancées STRICTEMENT en série.

### Vérification d'absence de résidu et de périmètre
```
$ git status --short
 M src/console/app.py
 M src/console/calib_page.py
```
Exactement les 2 fichiers autorisés (`calib_page.py`, et `app.py` pour le test), rien d'autre —
confirmé avant `git add`. Après commit, `git status --short` vide.

### Auto-relecture de ce tour
1. **L'échec AVANT correction a été capturé pour la BONNE raison** : `['GAUCHE']` — un seul top,
   le premier — et pas un `AttributeError` ou une autre panne accidentelle qui aurait, par
   coïncidence, fait échouer le même `chk`.
2. **La correction ne dépend d'aucun compteur** : revérifié à la lecture que `_maybe_beep` ne lit
   plus que `calib_state.get("etape")` et `self._etape_precedente` — ni `essai` ni `phase`
   n'apparaissent plus dans sa logique.
3. **Le « no double beep » reste tenu** : prouvé par construction (le rafraîchissement répété du
   même `cue` dans le test n'ajoute rien à la liste) et par la relecture du code (`etape ==
   "cue" and self._etape_precedente != "cue"` — faux dès le deuxième passage, puisque
   `self._etape_precedente` vaut alors déjà `"cue"`).
4. **Portée respectée à la lettre** : seuls `src/console/calib_page.py` et `src/console/app.py`
   touchés ; `core/modes/calibration.py` (cité dans le constat) lu, jamais modifié ; le constat
   MINEUR sur la durée estimée absente, explicitement laissé de côté par le coordinateur, non
   traité.
5. **Le rapport initial est corrigé, pas seulement le code** : la section « Auto-relecture » de la
   tâche 6 (plus haut dans ce fichier) sous-estimait la fréquence du défaut (« impact mineur, non
   corrigé pour rester fidèle à la clé exacte donnée ») — ce tour de correction documente
   l'ampleur réelle (5 tops sur 6 manqués, à CHAQUE séance) à l'endroit où le constat a été fait,
   plutôt que de laisser la sous-estimation initiale sans contradicteur plus haut dans ce même
   fichier.

### Résumé des tests (une ligne)
2 commandes lancées EN SÉRIE (`console/app.py --smoke`, `core/server.py --smoke`), la première
capturée AVANT correction en échec attendu (`['GAUCHE']`, un top sur six, EXIT_CODE=1) puis APRÈS
correction en succès (les six classes dans l'ordre, sans doublon, EXIT_CODE=0), la seconde en
non-régression (VERDICT OK, EXIT_CODE=0) ; `git status --short` limité aux 2 fichiers autorisés
avant et vide après commit.
