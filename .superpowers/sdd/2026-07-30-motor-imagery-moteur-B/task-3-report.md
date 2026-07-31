# Task 3 Report: `CalibrationRuntime` — la ligne du temps, et le protocole MI

## Statut
**DONE**

## Commit
- Hash : voir section « Commit final » en bas de ce rapport (créé après la rédaction de ce fichier,
  puisque le rapport lui-même fait partie du commit — comme pour T1/T2).

## Ce qui a été fait, fichier par fichier

### Créé : `src/core/modes/calibration.py`
Recopié **verbatim** depuis le brief (`task-3-brief.md`, lignes 25-401, hors les balises de
bloc de code markdown) : la classe `CalibrationRuntime` (la ligne du temps générique de toute
calibration — chauffe → échauffement non enregistré → essais tirés au hasard → entraînement →
résultat), plus son autotest sur horloge fabriquée. Vérifié par diff automatique contre le brief
(cf. section « Vérification de fidélité ») : **identique au caractère près**.

### Créé : `src/core/modes/mi_calib.py`
Recopié verbatim depuis le brief (lignes 410-719), avec **UN seul écart assumé** : la vérification
d'identité `_mi.SPEC.calibration is CALIB` dans `_selftest()`, remplacée par une vérification par
champs. Détails et justification dans « Écart par rapport au brief » ci-dessous.

### Modifié : `src/core/modes/mi.py`
Deux lignes, exactement comme demandé à l'étape 4 du brief :
- ajout de `from core.modes import mi_calib  # noqa: E402`, juste après
  `from core.modes.runtime import ModeRuntime  # noqa: E402` (le dernier import `core.modes.*`) ;
- remplacement de `calibration=None,   # la calibration est la moitié B ; le mode consomme un
  modèle déjà entraîné` par `calibration=mi_calib.CALIB,   # la calibration est jouée par le
  MOTEUR (moitié B)`.

Diff complet (`git diff` avant commit) :
```diff
@@ -32,6 +32,7 @@ from core.lsl_io import DecodedMIPublisher, mi_channel_labels, stream_name  # no
 from core.mi_decoder import MIDecoder  # noqa: E402
 from core.modes.contract import ModeSpec, Param, Rest, validate  # noqa: E402
 from core.modes.runtime import ModeRuntime  # noqa: E402
+from core.modes import mi_calib  # noqa: E402
 
 MI_DECODE_HZ = 5.0     # cadence de décodage — la même que le SSVEP, pour que les deux se lisent pareil
 
@@ -271,7 +272,7 @@ SPEC = ModeSpec(
         duration_s=0.0,
         instruction="Le casque se stabilise — reste immobile.",
     ),
-    calibration=None,   # la calibration est la moitié B ; le mode consomme un modèle déjà entraîné
+    calibration=mi_calib.CALIB,   # la calibration est jouée par le MOTEUR (moitié B)
     stream="decoded_mi",
     channels_fn=_channels,
     runtime_cls=MIRuntime,
```

### Rien d'autre à toucher
Vérifié avant d'écrire : `core/modes/registry.py::serialize()` sait déjà sérialiser
`spec.calibration` (kind, reason, label, briefing, epoch_s, params) — aucune modification
nécessaire là. `core/modes/__init__.py` ne liste aucun import explicite à compléter.
`EngineServer` (server.py) ne porte encore aucun attribut `.calibration` — confirmé volontairement
hors périmètre de cette tâche (câblage prévu à une tâche suivante du chantier).

## Écart par rapport au brief : le check d'identité de `mi_calib.py`

### Le symptôme
Au premier lancement de `python src/core/modes/mi_calib.py` (code recopié tel quel), un seul
`chk` sur 21 échouait :
```
ÉCHEC le mode MI déclare CETTE calibration dans son contrat
```
Tout le reste (protocole, entraînement, CV honnête < CV naïve, horodatage, non-écrasement,
verdicts, refus sur séance trop courte) passait au premier essai.

### Le diagnostic
J'ai instrumenté temporairement la ligne fautive (`id()` des deux côtés + `sys.modules`), relancé,
puis retiré l'instrumentation. Résultat :
```
[diag] __name__='__main__' id(CALIB)=1653485086544 id(_mi.SPEC.calibration)=1653003336304
       _mi.__name__='core.modes.mi'
       'core.modes.mi_calib' in sys.modules -> <module 'core.modes.mi_calib' from '...\mi_calib.py'>
```
Mécanisme confirmé : lancé directement, `mi_calib.py` s'exécute sous le nom `__main__` et n'est
JAMAIS enregistré dans `sys.modules['core.modes.mi_calib']`. Quand `_selftest()` fait
`from core.modes import mi as _mi`, ceci charge `core/modes/mi.py` pour la première fois, qui exécute
à son tour `from core.modes import mi_calib` (l'import ajouté à l'étape 4) : Python ne trouve
PAS ce nom dans `sys.modules` (puisque la copie en cours d'exécution y est sous `__main__`, pas
sous son nom de paquet) et réexécute donc **une seconde fois, intégralement**, `mi_calib.py`, sous
le nom `core.modes.mi_calib` cette fois. Cette seconde exécution construit sa PROPRE instance de
`CALIB` (mêmes valeurs de champs, objet Python différent). `is` compare des objets ; il ne peut
donc structurellement jamais passer dans cette configuration précise — ce n'est pas un défaut de
câblage entre `mi.py` et `mi_calib.py` (le contrat porte bien la bonne calibration, avec les bonnes
valeurs), c'est un artefact du couple « fichier exécutable directement » + « réimporté ailleurs
par son nom de paquet PENDANT sa propre exécution », qui ne s'était jamais présenté avant dans ce
dépôt (aucun autre module `core/` ne fait un aller-retour pareil dans son propre autotest).

Remarque : un passage de `is` à `==` n'aurait pas suffi — `Calib` est un dataclass gelé dont
l'égalité compare TOUS les champs, y compris `runtime_cls` (la classe `MICalibration`), qui est
elle aussi redéfinie par la seconde exécution et donc elle-même un objet différent (les classes se
comparent par identité par défaut). `==` aurait donc échoué pour la même raison.

### Le correctif
Remplacé le test d'identité par une vérification des champs qui identifient réellement « cette
calibration-là » — présence, étiquette, et nom (pas objet) de la classe de runtime :
```python
calib_mi = _mi.SPEC.calibration
chk(calib_mi is not None and calib_mi.label == CALIB.label
    and calib_mi.runtime_cls is not None
    and calib_mi.runtime_cls.__name__ == MICalibration.__name__,
    f"le mode MI déclare CETTE calibration dans son contrat ({calib_mi!r})")
```
avec un commentaire expliquant le mécanisme (pour qu'un étudiant qui relance ce test dans un autre
contexte ne soit pas surpris de ne pas voir `is`). Le reste du fichier est inchangé. Ce n'est PAS un
assouplissement de seuil de qualité (aucune probabilité, aucune séparation de classes en jeu) : le
test vérifie toujours que le mode MI pointe réellement vers CETTE calibration et pas vers `None` ni
une autre — juste sans dépendre d'une identité d'objet qui ne peut pas survivre au double chargement.

Fichier de diagnostic temporaire créé et supprimé dans le scratchpad de session (jamais dans le
dépôt) : aucune trace résiduelle.

## Commandes de test lancées, EN SÉRIE, avec leur sortie réelle

**1. `python src/core/modes/calibration.py`** (avant tout autre changement)
```
[calibration] VERDICT : OK
```
Exit code 0. Les 17 `chk` passent au premier essai (aucune correction nécessaire sur ce fichier).

**2. `python src/core/modes/mi_calib.py`** — premier essai, ÉCHEC attendu (cf. ci-dessus) :
```
  ÉCHEC le mode MI déclare CETTE calibration dans son contrat
  OK   et annonce la longueur d'époque dont le moteur devra dimensionner son tampon (4.0 s)
[mi-calib] accuracy HONNÊTE (validation croisée par essai) : 45.0% — hasard 33% — UTILISABLE
[mi-calib] (pour mémoire, la CV naïve, fenêtres mélangées : 49.3% — gonflée, ne pas s'y fier)
  ... (19 autres chk, tous OK)
[mi-calib] VERDICT : PROBLÈME
```
Exit code 1. Après le correctif ci-dessus, relancé :
```
  OK   le mode MI déclare CETTE calibration dans son contrat (Calib(kind='console', ...,
       runtime_cls=<class 'core.modes.mi_calib.MICalibration'>))
  OK   et annonce la longueur d'époque dont le moteur devra dimensionner son tampon (4.0 s)
[mi-calib] accuracy HONNÊTE (validation croisée par essai) : 45.0% — hasard 33% — UTILISABLE
[mi-calib] (pour mémoire, la CV naïve, fenêtres mélangées : 49.3% — gonflée, ne pas s'y fier)
  OK   la séance aboutit (fini ; problème='')
  OK   6 essais × 3 classes = 18 enregistrés (18)
  OK   et 3 fenêtres par essai de 4 s (54)
  OK   les deux CV sont rapportées (0.45, 0.4927272727272728)
  OK   et c'est l'HONNÊTE qui est affichée, plus basse que la naïve (45.0% contre 49.3%)
  OK   le niveau du hasard est rapporté à côté (0.3333333333333333)
  OK   le modèle est horodaté (mi_model_20260730-163536.joblib)
  OK   l'enregistrement porte le nombre d'essais (mi_calib_20260730-163536_n18.npz)
  OK   et le modèle produit est VISIBLE dans la liste (...)
  OK   la description du modèle porte la CV HONNÊTE, pas None (0.45)
  OK   et le nombre d'essais (18)
[calib] entraînement impossible : ValueError : pas assez de données pour entraîner : ...
  OK   une séance trop courte refuse d'entraîner, en disant pourquoi (...)
  OK   et n'ajoute AUCUN modèle à la liste
  OK   les verdicts sont calés sur l'échelle HONNÊTE : 40 % n'est pas « utilisable »
[mi-calib] VERDICT : OK
```
Exit code 0. Les 21 `chk` passent, y compris l'invariant central du chantier : CV groupée (45,0 %)
strictement inférieure à la CV naïve (49,3 %) sur signal ERD synthétique — et le seuil « au moins 5
fenêtres par classe » (aucun assouplissement demandé ni fait : les seuils du brief, `>= 5` fenêtres
pour entraîner et les paliers 0,60/0,45 des verdicts, sont restés tels quels et passent sans
ajustement).

**3. `python src/core/modes/calibration.py`** — reconfirmé vert après le correctif (le fichier n'a
pas été touché, mais je voulais la paire au vert au même instant) : `VERDICT : OK`, exit 0.

**4. `python src/core/modes/mi.py`** (non-régression, étape 6)
```
[mi] VERDICT : OK
```
Exit code 0. Les 27 `chk` passent, y compris ceux qui dépendent du contrat (chauffe, `decoded_mi`,
bornes d'index, ordre `p_<classe>`, `votes_atteignables`).

**5. `python src/core/modes/registry.py`** (non-régression, étape 6)
```
[registry] 7 modes, dont 4 dans le moteur
[registry] VERDICT : OK
```
Exit code 0. `mi` reste listé « ● moteur », son unique paramètre dynamique (`model`) toujours
signalé « NORMAL ... sans choix pour l'instant » (dépôt sans modèle entraîné) — le nouveau
`calibration=mi_calib.CALIB` n'introduit aucun défaut de catalogue.

**6. `python src/core/server.py --smoke`** (non-régression, étape 6)
```
[smoke] VERDICT : OK
[smoke-frontiere] 0 violation(s) de frontière
[smoke-frontiere] VERDICT : OK
[smoke-repos] VERDICT : OK
[smoke-ssvep] VERDICT : OK
[smoke-neuro] VERDICT : OK
[smoke-mi] VERDICT : OK
[smoke-cumul] VERDICT : OK
[smoke-proposition] VERDICT : OK
```
Exit code 0. Le scan de frontière (`0 violation(s)`) confirme que `calibration.py` et `mi_calib.py`
respectent l'interdit pygame/Qt/`research` dans `src/core/**/*.py` — leurs imports se limitent à
`os`, `random`, `sys`, `time`, `numpy`, `core.config`, `core.mi_decoder`, `core.modes.calibration`,
`core.modes.contract`.

**7. `python src/console/app.py --smoke`** (non-régression, étape 6)
```
[console-smoke] VERDICT : OK
```
Exit code 0. Tous les `chk` passent (grille des 7 modes, page MI, formulaires, live views).

## Vérification de fidélité au brief

`diff` entre le bloc de code cité dans `task-3-brief.md` (lignes 25-401 pour `calibration.py`,
410-719 pour `mi_calib.py`) et les fichiers réellement écrits :
- `calibration.py` : **aucune différence** (hormis les balises \`\`\`python de bloc markdown, hors
  sujet).
- `mi_calib.py` : **une seule différence**, exactement le correctif documenté ci-dessus (remplace
  8 lignes par 13, dont 8 lignes de commentaire explicatif).

## Auto-relecture

### Ce qui fonctionne
- Les trois pièges signalés dans la consigne sont respectés :
  1. Pas de cycle d'import : `mi_calib.py` n'importe `core.modes.mi` qu'à l'intérieur de
     `_selftest()` ; `mi.py` importe `mi_calib` en tête de fichier sans réciproque au niveau
     module. Confirmé par l'exécution même (un cycle aurait levé une `ImportError` claire, pas
     l'échec d'identité observé — les deux sont bien des symptômes différents).
  2. `window_s` / `step_s` sont des attributs de CLASSE sur `MICalibration` (`MI_WINDOW_S`,
     `MI_TRAIN_STEP_S`), et `_entrainer` les lit via `self.window_s` / `self.step_s`, jamais les
     constantes du module directement.
  3. Aucun `time.perf_counter()` ni équivalent dans `calibration.py` ni `mi_calib.py` : `tick`
     reçoit `now` partout, y compris dans `_pas_essai`, `_terminer` (pas d'horloge lue), et les
     deux autotests jouent des séances de plusieurs minutes en une fraction de seconde réelle.
- Aucun test n'a touché au vrai `data/` : les deux autotests utilisent `tempfile.mkdtemp` et
  nettoient dans un `finally` (`shutil.rmtree(..., ignore_errors=True)`). Vérifié aussi à l'œil :
  `git status` ne montre aucun fichier sous `data/` après les runs.
- Les valeurs de protocole (`MI_CUE_S=3.0`, `MI_IMAGERY_S=4.0`, `MI_REST_S=1.5`,
  `MI_WARMUP_PER_CLASS=2`, `MI_TRAIN_STEP_S=1.0`, `MI_SESSIONS=(10,14,18,26)`, `MI_WINDOW_S=2.0`,
  `SSVEP_WARMUP_S=15.0`) n'ont pas bougé — reprises telles quelles depuis `core/config.py`,
  aucune n'a été redéfinie localement.
- `registry.serialize()` gère déjà `spec.calibration` sans changement : vérifié en lisant le code
  AVANT d'écrire quoi que ce soit, pour ne pas dupliquer une sérialisation qui existait déjà.

### Écart par rapport au brief
Un seul, détaillé plus haut : le check d'identité `is CALIB` de `mi_calib._selftest()`, remplacé
par une vérification par champs (présence, étiquette, nom de la classe de runtime). Root cause
mécanique (Python recharge un module lancé en `__main__` s'il est réimporté par son nom de paquet
pendant sa propre exécution), pas un défaut de câblage entre les fichiers, et pas un relâchement
de seuil de qualité — aucune probabilité, aucun seuil de CV, aucun `VERDICTS` touché.

### Réserve mineure observée, non corrigée
Dans `CalibrationRuntime.state()` (verbatim du brief) :
```python
"restant_s": round(self.restant_s(now or 0.0), 1) if now else 0.0,
```
`now` étant testé par sa valeur de vérité, un appel explicite `state(now=0.0)` retomberait sur
`0.0` au lieu de calculer `restant_s(0.0)` — confond « `now` non fourni » (le cas que la docstring
documente : « sans lui, le décompte vaut 0 ») et « `now` vaut exactement zéro ». Sans conséquence
pratique : le moteur passe toujours un timestamp réel (jamais exactement `0.0`), et aucun test
(du brief ou existant) n'appelle `state(now=0.0)` en attendant un `restant_s` non nul à cet
instant — les deux autotests écrits passent sans toucher ce cas. Je ne l'ai pas corrigé
silencieusement : le brief demandait du code verbatim, ce n'est pas un défaut qui casse un test,
et corriger des détails hors del périmètre demandé sans le signaler est justement ce qu'on m'a
demandé d'éviter. Signalé ici pour triage éventuel par la revue finale du chantier, dans le même
esprit que les « minor deferred » de T1.

### Ce qui reste hors périmètre (volontairement)
- `EngineServer.calibration` : aucun attribut de ce nom sur `server.py` à ce stade — `CalibrationRuntime`
  n'est pas encore instanciée ni pilotée par le moteur. C'est cohérent avec le brief, qui ne
  demande de toucher que `calibration.py`, `mi_calib.py` et le contrat de `mi.py`. Câblage dans
  `EngineServer` (fils de commande, `snapshot()`, endpoint console) laissé à une tâche suivante.
- La console (`src/console/`) ne propose encore aucun bouton « Calibrer » qui déclenche
  concrètement une séance — seul le CONTRAT (`Calib`) est maintenant renseigné et sérialisable.

## Résumé des tests (une ligne)
6 commandes lancées EN SÉRIE (`calibration.py`, `mi_calib.py`, `mi.py`, `registry.py`,
`server.py --smoke`, `console/app.py --smoke`), toutes en exit code 0 / VERDICT OK au moment du
commit ; un seul `chk` a échoué en cours de route (identité d'objet due à un double-import Python,
corrigé et documenté), aucun seuil de qualité MI n'a été touché.

---

# Tour de correction 1/5

Commit : `04c7773a240438025ddcfda56b0c48b5d8389e41`. Périmètre imposé par le coordinateur :
`src/core/modes/calibration.py` et `src/core/modes/mi_calib.py` uniquement — `mi.py`, `runtime.py`
(commit `3d46273`) et `server.py` (commit `144de06`), déjà modifiés par ailleurs entre-temps, ne
sont pas touchés.

## IMPORTANT 1 — `state()` confondait `now=0.0` avec « pas de `now` »

### Le correctif
`src/core/modes/calibration.py`, dans `CalibrationRuntime.state()` :
```diff
-            "restant_s": round(self.restant_s(now or 0.0), 1) if now else 0.0,
+            "restant_s": round(self.restant_s(now), 1) if now is not None else 0.0,
```
Exactement le correctif demandé. `now or 0.0` est devenu inutile une fois la condition externe
corrigée (dans la branche `now is not None`, `now or 0.0` valait de toute façon `now` — le seul
flottant falsy est `0.0`, et `0.0 or 0.0 == 0.0`) : simplifié en `self.restant_s(now)` pour ne pas
laisser une trace de l'ancien bug qui aurait interrogé un futur lecteur.

### Le test ajouté
Dans `_selftest()`, juste après le premier `tick` qui pose `_echeance = 115.0` (chauffe de 15 s
démarrée à t=100) :
```python
chk(rt.state(now=0.0)["restant_s"] == round(rt.restant_s(0.0), 1) > 0.0,
    f"now=0.0 est une horloge valide, distincte de l'absence d'horloge "
    f"({rt.state(now=0.0)['restant_s']})")
```
Sur le code fautif, `state(now=0.0)["restant_s"]` valait `0.0` (branche `if now` fausse) au lieu du
restant réel (115.0) : le test aurait échoué. Je ne l'ai pas rejoué explicitement sur l'ancien code
séparément — le correctif est celui donné mot pour mot par le coordinateur, la seule variable étant
le test qui le prouve. Sortie réelle, code corrigé :
```
  OK   now=0.0 est une horloge valide, distincte de l'absence d'horloge (115.0)
```
`115.0` est le restant RÉEL à cet instant (démarrage à t=100, chauffe de 15 s) — la preuve que
`now=0.0` n'est plus retombé sur `0.0`.

## IMPORTANT 2 — la garantie « rien n'est jamais écrasé » rendue STRUCTURELLE

### Le correctif
`src/core/modes/mi_calib.py`. Nouvelle fonction, juste après `horodatage()`, format de nom
INCHANGÉ :
```python
def _chemins_libres(dossier, n_essais):
    """Le couple (chemin du modèle, chemin de l'enregistrement) pour CETTE séance — les DEUX
    chemins sont GARANTIS libres au moment du retour, sans changer le FORMAT du nom.

    `horodatage()` n'a qu'une résolution d'une seconde : deux séances qui finissent la même
    seconde produiraient sinon le MÊME couple de noms, et `save`/`savez` écrasent sans vérifier —
    exactement la panne que l'horodatage existe pour fermer (cf. docstring du module, point 2).
    On avance donc d'une seconde tant que l'un des deux fichiers existe déjà : un décalage de
    quelques secondes sur l'estampille est un prix dérisoire devant la perte d'une séance.
    """
    maintenant = _time.time()
    while True:
        stamp = horodatage(maintenant)
        chemin_modele = _os.path.join(dossier, f"mi_model_{stamp}.joblib")
        chemin_npz = _os.path.join(dossier, f"mi_calib_{stamp}_n{n_essais:02d}.npz")
        if not _os.path.exists(chemin_modele) and not _os.path.exists(chemin_npz):
            return chemin_modele, chemin_npz
        maintenant += 1.0
```
`_entrainer` : `stamp = horodatage()` + construction manuelle des deux chemins remplacés par
`chemin_modele, chemin_npz = _chemins_libres(self.dossier, len(enregistre))`. Le paramètre
`horodatage(maintenant=None)` — « ajouté pour que le test soit reproductible » mais jamais utilisé —
est maintenant réellement consommé, par `_chemins_libres`.

Le commentaire trompeur (« deux séances donnent deux fichiers ») a été remplacé par un commentaire
qui décrit ce que le bloc EN DESSOUS prouve réellement (une seule séance : nommage, visibilité), et
renvoie vers le nouveau bloc à deux séances pour la preuve de non-écrasement.

### Le test qui tue le mutant — ÉCHEC AVANT, SUCCÈS APRÈS

Séquence suivie, dans l'ordre :

**Étape A — ajouter UNIQUEMENT le test à deux séances, `_entrainer` pas encore corrigé.**
Épinglage de `_time.time` (pas `horodatage` directement : `_entrainer` appelait `horodatage()` sans
argument, qui retombe en interne sur `_time.time()` — le même point d'ancrage marche donc sur
l'ancien ET le nouveau code). Deux séances RÉUSSIES (`trials_per_class=6`, comme le premier bloc du
fichier) jouées à la suite dans le même dossier, avec la même horloge épinglée. Empreinte SHA-256
du modèle et de l'enregistrement de la première séance prise IMMÉDIATEMENT après qu'elle termine,
AVANT que la seconde ne tourne.

Run : `python src/core/modes/mi_calib.py` (code non corrigé). Sortie réelle (extrait) :
```
[mi-calib] modèle : ...\mi_model_20231114-231320.joblib
[mi-calib] enregistrement : ...\mi_calib_20231114-231320_n18.npz
  OK   la première des deux séances à la même seconde aboutit (fini)
[mi-calib] modèle : ...\mi_model_20231114-231320.joblib
[mi-calib] enregistrement : ...\mi_calib_20231114-231320_n18.npz
  OK   la seconde des deux séances à la même seconde aboutit (fini)
  ÉCHEC deux séances à la MÊME seconde produisent deux modèles DISTINCTS (mi_model_20231114-231320.joblib vs mi_model_20231114-231320.joblib)
  ÉCHEC et deux enregistrements DISTINCTS (mi_calib_20231114-231320_n18.npz vs mi_calib_20231114-231320_n18.npz)
  OK   et les DEUX modèles sont listés, aucun n'a chassé l'autre (['mi_model_20231114-231320.joblib', 'mi_model_20260731-094918.joblib'])
  ÉCHEC le modèle de la PREMIÈRE séance est resté OCTET POUR OCTET intact après la seconde
  ÉCHEC et son enregistrement aussi
[mi-calib] VERDICT : PROBLÈME
```
Exit code 1. Exactement le mode de panne annoncé : même nom pour les deux séances, la seconde
écrase la première EN SILENCE (les deux `tick` réussissent, `save`/`savez` n'ont jamais protesté).
Le check « les deux modèles sont listés » passe quand même — normal et sans valeur ici : les deux
séances pointent vers le MÊME fichier sur disque, donc ce fichier unique EST dans la liste, ce qui
ne prouve rien sur la collision (c'est la raison pour laquelle ce n'était pas le check décisif ;
les quatre autres le sont).

**Étape B — ajouter `_chemins_libres`, brancher `_entrainer`, ajouter la sonde isolée.**
Run : `python src/core/modes/mi_calib.py` (code corrigé). Sortie réelle (extrait) :
```
  OK   une collision force une avance sur les DEUX chemins (mi_model_20270115-090000.joblib -> mi_model_20270115-090001.joblib)
  OK   et l'avance est de exactement 1 s, pas plus (mi_model_20270115-090001.joblib)
[mi-calib] modèle : ...\mi_model_20231114-231320.joblib
[mi-calib] enregistrement : ...\mi_calib_20231114-231320_n18.npz
  OK   la première des deux séances à la même seconde aboutit (fini)
[mi-calib] modèle : ...\mi_model_20231114-231321.joblib
[mi-calib] enregistrement : ...\mi_calib_20231114-231321_n18.npz
  OK   la seconde des deux séances à la même seconde aboutit (fini)
  OK   deux séances à la MÊME seconde produisent deux modèles DISTINCTS (mi_model_20231114-231320.joblib vs mi_model_20231114-231321.joblib)
  OK   et deux enregistrements DISTINCTS (mi_calib_20231114-231320_n18.npz vs mi_calib_20231114-231321_n18.npz)
  OK   et les DEUX modèles sont listés, aucun n'a chassé l'autre (['mi_model_20231114-231321.joblib', 'mi_model_20231114-231320.joblib', 'mi_model_20260731-095315.joblib'])
  OK   le modèle de la PREMIÈRE séance est resté OCTET POUR OCTET intact après la seconde
  OK   et son enregistrement aussi
[mi-calib] VERDICT : OK
```
Exit code 0. La seconde séance a bien été repoussée de `...320` à `...321` (une seconde plus tard,
exactement l'avance minimale) au lieu d'écraser la première.

### Écart par rapport à la demande, assumé
En plus du test à deux séances explicitement demandé, j'ai ajouté un test ISOLÉ de
`_chemins_libres` seule (bloc « sonde », dossier dédié `dossier/sonde/`, horloge épinglée à une
autre valeur pour ne pas interagir avec le test à deux séances) : collision provoquée à la main
sur les deux chemins, vérifie l'avance exacte d'1 s. Ce n'était pas demandé littéralement, mais le
point 2 de la consigne (« pour qu'elle soit testable seule ») en faisait une conséquence directe du
design voulu — je l'ai jugé cohérent de le vérifier plutôt que de laisser cette propriété
seulement implicite. Pas de seuil touché, pas de logique de production changée par ce choix.

### Vérification de non-régression, EN SÉRIE, sortie réelle finale
```
1. python src/core/modes/calibration.py     -> [calibration] VERDICT : OK   (exit 0)
2. python src/core/modes/mi_calib.py        -> [mi-calib] VERDICT : OK      (exit 0)
3. python src/core/modes/mi.py              -> [mi] VERDICT : OK            (exit 0)
4. python src/core/server.py --smoke        -> tous les [smoke*] VERDICT : OK (exit 0), y compris
   [smoke-calib] VERDICT : OK — le monkeypatch de server.py sur MICalibration.__init__ et ses
   attributs de classe reste compatible : `_chemins_libres` ne change ni la signature de
   `__init__`, ni celle de `_entrainer`.
```
`git status --short` après le commit : propre (aucune sortie). `data/` vérifié : les seuls
`mi_model_*`/`mi_calib_*` présents (`mi_calib_last.npz`, `mi_model_full42.joblib`,
`mi_model_pre_car.joblib`, `mi_model_short30.joblib`) sont des artefacts historiques non trackés
par git, datés du 20-22 juillet — antérieurs à cette session, aucun ne porte le nouveau format
d'horodatage produit aujourd'hui. Toutes les écritures de ce tour de correction sont passées par
`tempfile.mkdtemp()`.

## Statut de ce tour
DONE. Les deux constats IMPORTANTS sont fermés, avec un test qui échouait avant correction et
passe après pour le second (démonstration demandée). Aucun seuil de qualité MI modifié. Aucune
ligne touchée hors du périmètre `calibration.py` / `mi_calib.py`.
