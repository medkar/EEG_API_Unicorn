# Tranche B — corrections de la revue finale

Périmètre édité : `src/core/errp_models.py`, `src/core/errp_decoder.py`,
`src/research/errp_calibrate.py`, `src/research/app.py` (ses seuls appels au modèle ErrP).
`src/core/modes/errp.py` **n'a pas été touché** (lu seulement).

**Traité : 2 Critical + 5 Important + 6 Minor = 13 constatations sur 13. Aucune reportée.**

Autotests, un par un, aucun autre programme lancé :

| commande | verdict |
|---|---|
| `python src/core/errp_models.py` | **OK** — 30 assertions, sortie 0 |
| `python src/core/errp_decoder.py` | **OK** — pipeline validé + 7 gardes, sortie 0 |
| `python src/research/app.py --smoke` | **OK** — sortie 0 |
| `python src/core/modes/errp.py` (contrôle de non-régression, fichier d'un autre implémenteur) | **OK**, sortie 0 |

`data/` n'a été ni écrit ni modifié : `errp_model.joblib` (35 115 o, 24/07 11:46) et
`errp_model_20260818-153051.joblib` (38 451 o, 18/08 15:30) ont leurs mtimes d'origine après tous
les essais. Chaque test qui écrit passe par `tempfile.mkdtemp` + `shutil.rmtree` dans un `finally`.

---

## Réponse à la question sur `docs/markers.md`

> *Après le correctif, une seconde calibration ErrP écrase-t-elle encore `data/errp_model.joblib` ?*

**Non. La phrase « never overwrites the previous one » est désormais vraie pour l'ErrP** — elle
était fausse avant ce correctif. Vérifié par exécution (dossier temporaire, aucune écriture dans
`data/`, aucune calibration réelle) :

```
ERRP_MODEL_PATH (la trace du 24 juillet) : errp_model.joblib
ce qu'une calibration ecrit maintenant  : errp_model_20260819_141921.joblib
  ecrase-t-il ERRP_MODEL_PATH ?          : False
  correspond a errp_models.MOTIF ?       : True (errp_model*.joblib)

deux calibrations de suite -> ['errp_model_20260819_141922.joblib', 'errp_model_20260819_141923.joblib']
  la premiere existe encore ?           : True
  modeles_disponibles les retrouve ?    : ['errp_model_20260819_141923.joblib', 'errp_model_20260819_141922.joblib']
  charger() accepte le plus recent ?    : True | defaut propose = errp_model_20260819_141923.joblib
```

- **Nom exact écrit** : `data/errp_model_AAAAMMJJ_HHMMSS.joblib` — `strftime("%Y%m%d_%H%M%S")`,
  underscore entre date et heure, exactement le motif du jumeau `p300_calibrate`.
  (⚠️ à ne pas confondre avec `data/errp_model_20260818-153051.joblib`, déjà sur le disque, qui
  porte un TIRET : il vient du script jetable de ré-entraînement, pas de ce code.)
- **`errp_models.charger` / `modeles_disponibles` le retrouvent** : le nom correspond à
  `MOTIF = "errp_model*.joblib"`, la liste le rend en PREMIER (tri par date décroissante), donc
  c'est le défaut proposé au mode ErrP du moteur, à la console et à l'appli pygame.
- **Seule réserve honnête** : l'horodatage a une résolution d'une seconde ; deux calibrations
  terminées dans la MÊME seconde se marcheraient dessus. Une calibration dure 4-5 min — c'est
  hors d'atteinte en pratique, et c'est la même propriété que le P300 et le MI.

Deux assertions du smoke tiennent cette promesse (`horodate != ERRP_MODEL_PATH`, et
`fnmatch(basename, errp_models.MOTIF)`), plus une troisième qui vérifie que `calibrate()` s'en
sert bien quand `save_path` est `None`.

---

# CRITICAL

## C1 — Une calibration écrasait `data/errp_model.joblib`

**Fait.** `src/research/errp_calibrate.py` :

- nouvelle fonction `chemin_modele_horodate(dossier=None)`, copie du geste du jumeau
  (`p300_calibrate.py:238`), docstring qui dit POURQUOI (la trace du 24 juillet, l'AUC 0,7763 /
  p = 0,0099 sur 200 essais et 5 blocs, les 4 modèles que le MI a perdus ainsi) ;
- `calibrate()` : `save_path = save_path or chemin_modele_horodate()` (au lieu de
  `or ERRP_MODEL_PATH`) ;
- docstring de module corrigée : la sortie n'est plus annoncée comme `data/errp_model.joblib`.

Conséquences traitées ailleurs : `errp_models.MOTIF` portait un commentaire faux (« le
ré-entraînement en écrit d'horodatés » — aucun code ne le faisait) → il dit maintenant « la
calibration en écrit d'HORODATÉS », ce qui est vrai ; et le défaut de `mode_errp` a cessé d'être
un nom fixe (cf. C2).

### Preuve rouge → vert

Trois mutations, chacune sur une ligne, autotest `python src/research/app.py --smoke` :

**(a) retour au chemin fixe dans `calibrate()`** — `save_path or chemin_modele_horodate()` →
`save_path or ERRP_MODEL_PATH` :

```
AssertionError: calibrate() doit retomber sur chemin_modele_horodate() quand save_path est None :
un défaut à ERRP_MODEL_PATH écrase la trace du 24 juillet dès la première calibration de démonstration
EXIT=1
```

**(b) `chemin_modele_horodate` rend le chemin fixe** — première ligne du corps remplacée par
`return ERRP_MODEL_PATH` :

```
AssertionError: une calibration ErrP écrirait dans data/errp_model.joblib et écraserait la trace
du 24 juillet (C:\...\data\errp_model.joblib)
EXIT=1
```

**Vert après retrait** : `[app] smoke OK : … + ErrP(cal+démo) câblés (headless).` / `EXIT=0`.

*(Note de méthode : l'assertion (a) lit le TEXTE SOURCE de `calibrate`. C'est délibéré et c'est
écrit dans le commentaire : la vérifier en exécutant `calibrate(app)` sans `save_path` pour voir
où il écrit, c'est commettre exactement l'accident qu'on interdit.)*

---

## C2 — L'appli chargeait le modèle sans passer par `charger()`

**Fait.** Vérifié d'abord que le défaut était réel, sans casque ni flux :

```
$ python -c "import sys; sys.path.insert(0,'src'); import joblib; joblib.load('data/errp_model.joblib')"
REFUS: ModuleNotFoundError No module named 'errp_decoder'
```

(et `data/errp_model_20260818-153051.joblib` se charge, lui : `core.errp_decoder.ErrPModel`,
noyau `core.p300_decoder`, 200 scores hors-pli, `cv_auc_=0.7762973…`, `perm_p_=0.00990…`,
`threshold_=0.51029…` — les chiffres du chantier, intacts.)

`src/research/app.py` :

- nouvelle fonction `_errp_charger(model_path=None)` → `(modèle, raison, chemin)`. `None` →
  le plus récent des modèles réellement chargeables (`errp_models.modeles_disponibles()`), sinon
  `errp_models.charger(...)`, qui ne lève jamais et dit quoi faire ;
- `mode_errp` : `model_path=ERRP_MODEL_PATH` → `model_path=None`, et
  `os.path.exists` + chargement direct → `_errp_charger` + `app.flash("Pas de modèle ErrP
  utilisable", probleme, 4.0)` ;
- `page_errp`, « Régler le seuil » : même remplacement, et le seuil est ré-enregistré **là où le
  modèle a été lu** (`save_path=chemin`), jamais sous un nom fixe ;
- `_errp_status(dispo)` + une ligne ErrP dans `_status` (l'accueil n'en avait aucune), jumelle de
  `_p300_status`. Sur ce poste elle affiche `ErrP : 1 (errp_model_20260818-153051.joblib)` : le
  modèle de juillet est correctement exclu, le ré-entraîné correctement proposé.

### Preuve rouge → vert

**(a) retour à `os.path.exists` + chargement direct dans `mode_errp`** :

```
AssertionError: mode_errp doit charger par `_errp_charger` (donc `errp_models.charger`, qui NOMME
le problème) et jamais par ErrPModel.load, un joblib.load nu
EXIT=1
```

**(b) suppression de la ligne ErrP de l'accueil** :

```
AssertionError: l'accueil doit porter une ligne « ErrP : … » : sans elle, un étudiant lance le mode
pour découvrir sur place qu'aucun modèle n'est utilisable (['casque : board SYNTHÉTIQUE …',
'modèles — c-VEP : oui    P300 : 1 (p300_model_20260817-135716.joblib)', 'envoi robot : OFF …'])
EXIT=1
```

**Vert après retrait** : `EXIT=0`.

⚠️ **Anecdote utile au prochain lecteur, laissée dans le code** : l'assertion (a) a rougi dès sa
première exécution — sur un COMMENTAIRE que je venais d'écrire dans `page_errp` et qui contenait le
nom interdit pour dire de ne pas s'en servir. Le commentaire a été reformulé, le nom interdit est
maintenant construit (`interdit = "ErrPModel" + ".load"`) et l'avertissement est écrit dans le
smoke. Le test mord, c'est mesuré et pas supposé.

---

# IMPORTANT

## I1 — L'anti-test `n_epoques is None` : assertion RETOURNÉE, pas supprimée

**Fait.** `ErrPModel.__init__` pose `self.n_epoques_ = None`, `ErrPModel.fit` pose
`self.n_epoques_ = int(len(y))` (une ligne, à côté de `y = np.asarray(y).astype(int)`), et
l'assertion de `errp_models._selftest` dit maintenant ce que dit son jumeau :

```python
chk(d["n_epoques"] == len(y), f"et le nombre d'époques d'entraînement est retenu ({d['n_epoques']})")
```

Le commentaire de `decrire` qui affirmait « ce serait modifier `ErrPModel.fit`, hors périmètre »
a été remplacé par ce qui est vrai. L'ancienne assertion n'a pas été supprimée en silence : le
commentaire au-dessus explique qu'elle a été retournée, et pourquoi (« sa seule mutation
rougissante était le correctif »).

### Preuve rouge → vert

Mutation : suppression de `self.n_epoques_ = int(len(y))` dans `ErrPModel.fit`.

```
ÉCHEC et le nombre d'époques d'entraînement est retenu (None)
[errp-models] VERDICT : PROBLÈME
EXIT=1
```

La même mutation rougit aussi `python src/core/errp_decoder.py`
(`...et le nombre d'époques d'entraînement aussi (None)`). **Vert après retrait** :
`OK et le nombre d'époques d'entraînement est retenu (40)` / `EXIT=0`.

## I2 — `_demo()` levait sur `f"{pp:.3f}"` quand la p-value est `None`

**Fait.** `pp_txt = "non testée" if pp is None else f"{pp:.3f}"`, et le bloc de verdict a été
extrait dans `_rapport(m)` — sans cette extraction, la correction n'aurait eu **aucun test**, parce
que `_demo` ne produit jamais lui-même un modèle sans p-value.

### Preuve rouge → vert

Mutation : retour à `print(f"    test de permutation : p={pp:.3f}" + …)`.

```
ÉCHEC le rapport d'un modèle SANS AUC ni p-value s'imprime au lieu de lever
      (TypeError: unsupported format string passed to NoneType.__format__)
[errp-gardes] VERDICT : PROBLÈME
EXIT=1
```

C'est mot pour mot l'exception annoncée par la constatation. **Vert après retrait** :
`OK le rapport d'un modèle SANS AUC ni p-value s'imprime au lieu de lever (None)` / `EXIT=0`.

## I3 — Le message du refus hérité

**Fait**, les trois points (a), (b) et (c). Nouveau texte :

```python
return None, (f"modèle hérité (module {module!r}, attendu {_MODULE_ATTENDU!r}), abandonné "
              f"délibérément — recalibre (`python src/research/app.py`, mode ErrP) : "
              f"{_os.path.basename(chemin)}")
```

— il NOMME le fichier (comme les trois autres refus de la fonction et comme les deux jumeaux), il
dit « abandonné délibérément » et non « illisible » (on n'entre ici que si `joblib.load` a RÉUSSI),
et il prescrit le seul remède qui existe dans ce dépôt. **Le refus reste un refus** : aucune
passerelle, seule sa formulation change. Les deux assertions qui vérifiaient l'ancien texte ont été
mises à jour (`"recalibre" in raison.lower()`), et celle du modèle étranger exige désormais aussi
le nom du fichier.

*(La promesse « ré-entraîner depuis `data/errp_calib_*.npz` » a été retirée plutôt que tenue :
livrer le script de ré-entraînement est un chantier à part, hors de ce périmètre. C'est signalé
comme dépendance en fin de rapport.)*

### Preuve rouge → vert

Mutation : le message perd `{_os.path.basename(chemin)}`.

```
ÉCHEC un modèle hérité est refusé en disant quoi faire ET sur QUEL fichier (modèle hérité
      (module '__main__', attendu 'core.errp_decoder'), abandonné délibérément — recalibre
      (`python src/research/app.py`, mode ErrP))
[errp-models] VERDICT : PROBLÈME
EXIT=1
```

**Vert après retrait** : `… ErrP) : errp_model_etranger.joblib` / `EXIT=0`.

## I4 — Le refus « pas de scores hors-pli » inventait sa cause

**Fait**, par la **seconde possibilité** (la préférable) : c'est le modèle qui porte la raison.

- `ErrPModel.__init__` : `self.echec_oof_ = None` ;
- `ErrPModel.fit` : la garde non atteinte pose
  `"calibration trop courte : {n} essais ({c} corrects / {e} erreurs) — il en faut au moins 10, des
  DEUX classes, et au moins 2 de chaque"` ; le cas `best is None` (les trois `nfilter` tombés au CV)
  pose une phrase **distincte**, qui nomme la vraie piste (« voir les lignes `[errp] nfilter=… :
  CV échouée` », voie plate / électrode décollée / dérive de version) et dit explicitement
  « **ce n'est PAS un manque d'essais** » ;
- `errp_models.charger` ne devine plus : il cite `echec_oof_` tel quel (avec un repli nommé pour
  les modèles antérieurs à cette ligne). Il garde les sous-chaînes `hors-pli` et `recalibre`, dont
  dépend le filet jumeau du moteur.

Le scénario de la constatation — 200 essais, une électrode qui lâche, deux séances casque perdues
sur un diagnostic inventé — ne se produit plus.

### Preuve rouge → vert

**(a)** Mutation : `charger` récite la liste de causes au lieu de citer `echec_oof_`.

```
ÉCHEC ...et la raison RECOPIE le diagnostic posé par fit lui-même, mot pour mot
      ('calibration trop courte : 5 essais (3 corrects / 2 erreurs) — il en faut au moins 10, …')
[errp-models] VERDICT : PROBLÈME
EXIT=1
```

**(b)** Mutation : le cas « CV échouée » réutilise le diagnostic « trop courte » (le défaut décrit).

```
ÉCHEC CV échouée sur tous les nfilter : la cause dit CE QUI s'est passé, et surtout PAS
      « trop courte » — 24 essais n'ont pas manqué d'essais (calibration trop courte — recalibre
      avec plus d'essais)
[errp-gardes] VERDICT : PROBLÈME
EXIT=1
```

**(c)** Mutation : la garde non atteinte n'enregistre plus sa cause.

```
ÉCHEC 5 essais : pas de scores hors-pli, et la cause est ENREGISTRÉE (None)
EXIT=1
```

**Vert après retrait** dans les trois cas. Le cas « CV échouée » est produit **réellement**, pas
simulé : `_gardes` remplace `build_pipe` par une fonction qui lève, exactement là où `fit` l'appelle
(le modèle est construit AVANT le remplacement, donc son pipeline interne reste le vrai et le fit
final aboutit). L'autotest imprime bien les trois lignes `[errp] nfilter=N : CV échouée (…)`.

## I5 — Deux tests identiques, aucun ne mordait

**Fait.** Le premier (`errp_models.py:220`) est **supprimé**, et un commentaire à sa place dit
pourquoi (avec la liste des mutations qui le laissaient vert). Le second est **remplacé** par un
test du FILTRE : un dossier neuf contenant (a) un modèle parfaitement valide sous un nom **hors
motif** (`modele_errp.joblib`) et (b) un fichier **illisible** sous un nom conforme ; attendu `[]`.

### Preuve rouge → vert

**(a)** `MOTIF = "errp_model*.joblib"` → `"*.joblib"` :

```
ÉCHEC un dossier sans AUCUN modèle utilisable rend [], sans lever — ni le fichier hors-motif,
      ni l'illisible (['…\errp_models_vide_igadcmh5\modele_errp.joblib'])
EXIT=1
```

**(b)** filtre inversé (`charger(c)[0] is None`) :

```
ÉCHEC un dossier sans AUCUN modèle utilisable rend [], sans lever — ni le fichier hors-motif,
      ni l'illisible (['…\errp_models_vide_f4b_8lm5\errp_model_illisible.joblib'])
EXIT=1
```

Les deux mutations laissaient l'ancienne version **verte**. **Vert après retrait** : `OK … ([])`.

---

# MINOR — les six corrigées, aucune reportée

## M6 — Le noyau `self.core` n'était vérifié par personne

**Fait**, ~6 lignes dans `charger` (constante `_NOYAU_ATTENDU = "core.p300_decoder"` + contrôle
placé juste après celui de la classe extérieure), plus une fixture. La fixture part d'un **vrai**
modèle (module extérieur correct, scores hors-pli présents) dont seul `.core` est remplacé par un
`_NoyauEtranger` : c'est le seul contrôle qui peut le refuser, donc le test ne prouve que lui.

**Rouge** (suppression du contrôle) :

```
ÉCHEC un modèle à coquille neuve mais NOYAU hérité est refusé — c'est le noyau qui calcule les scores (None)
ÉCHEC ...et il n'apparaît donc pas dans la liste
ÉCHEC le plus récent d'abord ([… 'errp_model_noyau.joblib' …])
EXIT=1
```

(le modèle à noyau étranger se glisse jusque dans la liste proposée à l'étudiant). **Vert après
retrait.**

## M7 — La ligne « ce n'est pas un modèle ErrP » n'était pas couverte

**Fait** : fixture `_ModeleP300Renomme` (interface `scores`/`select`, pas `score`/`is_error`),
déposée sous `errp_model_vieux.joblib` — le scénario exact du rangement de `data/`.

**Rouge** (suppression du `hasattr`) : le fichier est refusé comme « modèle hérité (module
`'__main__'`) — recalibre », c'est-à-dire qu'on envoie l'étudiant recalibrer le **mauvais mode** :

```
ÉCHEC un modèle P300 rangé sous un nom d'ErrP est refusé POUR CE QU'IL EST, pas comme un hérité
      (modèle hérité (module '__main__', attendu 'core.errp_decoder'), abandonné délibérément — …)
EXIT=1
```

**Vert après retrait** : `(ce n'est pas un modèle ErrP : errp_model_vieux.joblib)`.

## M8 — `pick_threshold` ne se défendait pas elle-même

**Fait** : garde en tête de fonction (1-D, non vide, aligné sur `y`) + message qui NOMME la
fonction et renvoie aux deux filets amont. Trois cas testés dans `_gardes`.

**Rouge** (garde neutralisée) — les trois exceptions brutes, dont les deux annoncées par la
constatation :

```
ÉCHEC pick_threshold refuse (None, None) … (zero-dimensional arrays cannot be concatenated)
ÉCHEC pick_threshold refuse des scores VIDES … (zero-size array to reduction operation minimum …)
ÉCHEC pick_threshold refuse y et scores de longueurs différentes … (!! IndexError: boolean index did not match …)
EXIT=1
```

**Vert après retrait.**

## M9 — `modeles_disponibles` pouvait lever sur `getmtime`

**Fait** : `key=lambda c: _os.path.getmtime(c) if _os.path.isfile(c) else 0.0`.

Contrairement à ce que je pensais d'abord, **c'est testable sans simuler un mock du système de
fichiers** : la course se rejoue en faisant rendre à `glob` un chemin qui n'existe plus — ce qu'il
rend précisément quand le fichier part juste après.

**Rouge** (retour à `key=_os.path.getmtime` nu) :

```
ÉCHEC un fichier disparu entre le glob et le tri par date ne fait pas lever la liste
      (FileNotFoundError: [WinError 2] Le fichier spécifié est introuvable: '…\errp_model_disparu.joblib')
EXIT=1
```

**Vert après retrait** : `OK … ([])`.

## M10 — La fixture « 5 essais » ne prouvait qu'une clause sur trois

**Fait** : la fixture est **construite** (`y_court = [0, 1, 0, 1, 0]`, 5 époques) au lieu d'être
tranchée dans le jeu (`y[:5]`), plus une assertion préalable qui affirme que les deux autres
clauses sont satisfaites — donc « moins de 10 essais » est la **seule** cause possible. Ça règle
aussi le second point de la constatation (une classe unique faisait mourir l'autotest sur un
traceback au lieu d'un `ÉCHEC` lisible).

**Rouge** — la mutation que l'ancienne fixture laissait **verte** : `len(y) >= 10` → `len(y) >= 4` :

```
ÉCHEC fixture : 5 essais (< 10) ne posent PAS de scores hors-pli, la dégénérescence est réelle,
      pas simulée ([-1.41592849  0.61202377  0.70115201 -1.8735076   0.44505335])
ÉCHEC un modèle sans scores hors-pli est refusé EN LE NOMMANT, avec quoi faire (None)
ÉCHEC ...et la raison RECOPIE le diagnostic posé par fit lui-même, mot pour mot (None)
ÉCHEC ...et il n'apparaît donc pas dans la liste proposée à l'étudiant ([… 'errp_model_degenere.joblib' …])
EXIT=1
```

La valeur `10` que le message cite est maintenant réellement protégée. **Vert après retrait** :
`OK fixture : les 2 classes sont là, avec >= 2 essais chacune ([3, 2])`.

## M11 — `decrire` est du code mort et sa docstring disait le contraire

**Fait** : la docstring dit maintenant « aucun appelant en production aujourd'hui », nomme le seul
jumeau réellement appelé (`mi_models.decrire`, par `core/modes/mi_calib.py`), et explique ce que ça
implique pour le prochain lecteur (changer la forme du dict ne casse aucun affichage aujourd'hui —
mais casserait les trois d'un coup le jour où il y en aura un). Pas de test : c'est de la prose,
et une assertion sur une docstring n'aurait aucune mutation rougissante utile.

---

# Dépendances hors périmètre — à traiter par quelqu'un d'autre

1. **`src/core/modes/errp.py` (fichier d'un autre implémenteur, `e56e45f`) — deux commentaires
   devenus faux, aucun comportement cassé** :
   - `_open()` (~ligne 281) explique `n_calib=len(self.model.oof_y_)` par « `ErrPModel` ne pose pas
     d'attribut `n_epoques_` dédié, contrairement à `P300Model` ». **Il le pose maintenant.** Le
     chiffre publié reste correct (c'est l'effectif sur lequel `pick_threshold` a réglé le seuil),
     mais la justification est périmée ; `n_epoques_` serait le chiffre naturel.
   - `_sans_scores_oof()` (~ligne 271) énumère encore les trois causes (« moins de 10 essais, une
     seule classe, ou une classe à moins de 2 membres ») — c'est le **même défaut que I4**, au
     second filet. Il peut maintenant citer `self.model.echec_oof_`, comme `charger`.
   - Sa fixture dégénérée (~ligne 872) est encore `epochs[:5], y[:5]` : **même défaut que M10**.
   - Vérifié : `python src/core/modes/errp.py` reste **vert** avec mes modifications.
2. **Le script de ré-entraînement depuis `data/errp_calib_*.npz` n'existe toujours pas.** J'ai
   retiré du message de refus la promesse qu'il existe (I3b) plutôt que d'inventer un remède ;
   le seul remède livré reste une séance casque de 4-5 min. Si ce script est écrit un jour,
   `charger` pourra le nommer.
3. **`docs/markers.md`** : la phrase « never overwrites the previous one » est **maintenant vraie**
   pour l'ErrP (elle ne l'était pas). Le nom écrit est `data/errp_model_AAAAMMJJ_HHMMSS.joblib`.
4. **Rien de tout ceci n'a été vu au casque** : synthétique et headless seulement, conformément à
   la consigne.
