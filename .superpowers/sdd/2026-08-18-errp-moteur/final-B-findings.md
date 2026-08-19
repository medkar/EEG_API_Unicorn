# Tranche B — revue finale : `core/errp_models.py`, `core/errp_decoder.py`, `research/errp_calibrate.py`

Lecture seule, aucun programme lancé. Les constats appuyés sur le contenu binaire des `.joblib`
viennent d'un vidage d'octets (`grep -a` sur le pickle), pas d'un `joblib.load`.

**Ce qui est correct et vérifié ligne à ligne** (pour ne pas y revenir) :

- **Aucun test n'écrit dans le vrai `data/`.** `errp_models._selftest` crée deux `tempfile.mkdtemp`,
  passe le dossier explicitement à *chaque* appel de `modeles_disponibles`, et les efface dans un
  `finally` (`errp_models.py:218-373`). `charger(None/""/0)` sort avant tout accès disque.
  `errp_decoder._demo` n'écrit rien. Le faux `sys.modules["errp_decoder"]` est retiré dans un
  `finally` (`errp_models.py:296-302`).
- **Sortie en 1 sur échec** : `errp_models.py:381` et `errp_decoder.py:297`.
- **Frontière `core/`** : ni pygame, ni Qt, ni import de `research`/`console` dans les deux fichiers
  de `core/`. Français partout.
- **Chiffres de la séance réelle** : rien ne les contredit (AUC 0,7763 / p=0,0099 / seuil 0,5103 /
  TPR 0,500 / TNR 0,855 restent compatibles avec « AUC réaliste ~0,65-0,78 » de la docstring).
- **Le refus par nom de module fonctionne**, et le test `_ModeleHerite` n'est pas décoratif : la
  mutation `module.endswith("errp_decoder")` fait tomber le modèle sur le refus « hors-pli », dont
  le message ne contient pas `'errp_decoder'` → rouge. Vérifié aussi que `'core.errp_decoder'` ne
  contient pas la sous-chaîne `'errp_decoder'` (apostrophes comprises) : le commentaire dit vrai.
- **Le tri « plus récent d'abord » est bien celui qui décide** : `Param.default_now()`
  (`core/modes/contract.py:96-98`) prend `choix[0]`. Et l'interaction demandée — le plus récent est
  hérité, un ancien est valide — se comporte correctement : le tri se fait AVANT le filtre, le
  hérité disparaît, l'ancien valide devient le défaut proposé.

---

# CRITICAL

## C1 — Une calibration ErrP écrase `data/errp_model.joblib`, le modèle du 24 juillet que ce chantier a décidé de préserver. Le jumeau P300 a corrigé exactement ça la veille, et l'a verrouillé par une assertion.

**Sévérité : Critical**
**Fichier : `src/research/errp_calibrate.py:374`** (`save_path = save_path or ERRP_MODEL_PATH`),
avec **`src/core/errp_models.py:28`** (le commentaire de `MOTIF` qui affirme le contraire).

### Ce qui casse

`ERRP_MODEL_PATH` = `data/errp_model.joblib` (`config.py:715`). C'est le fichier du 24 juillet
(35 115 octets, mtime 24/07 11:46, même minute que `errp_calib_last.npz`) — celui dont le message de
commit `b35872a` dit : *« The July 24 model is left untouched as proof the decoder worked on
hardware »*, et autour duquel toute la docstring de `errp_models.py` est écrite (c'est LE spécimen
hérité). `calibrate()` l'écrase sans avertissement.

Le jumeau a précisément cette fonction, avec cette docstring
(`src/research/p300_calibrate.py:238-252`) :

> `chemin_modele_horodate()` — *« La calibration écrivait dans `P300_MODEL_PATH`, un nom FIXE : la
> calibration suivante effaçait donc la précédente. […] le MI a déjà perdu ses quatre modèles de
> cette façon. Rien n'appliquait cet invariant : seule une prose l'affirmait. »*

et une assertion de smoke qui interdit la régression (`src/research/app.py:1408-1417`). L'ErrP n'a ni
l'un ni l'autre.

### Scénario concret

1. Un étudiant lance `python src/research/app.py` (le seul accès à l'ErrP, cf. CLAUDE.md), page
   ErrP → « Calibrer ».
2. `app.py:1069 calib_errp` appelle `errp_calibrate.calibrate(app)` **sans `save_path`**.
3. `save_path = ERRP_MODEL_PATH` → `model.save(...)` (`errp_calibrate.py:418`) écrit par-dessus
   `data/errp_model.joblib`.
4. La seule trace matérielle du décodeur ErrP disparaît. (Les époques survivent — `_archive`
   horodate les `.npz` — donc c'est récupérable *si quelqu'un écrit le script de ré-entraînement,
   qui n'existe pas : cf. I3b*.)

Conséquence dérivée, dans mon fichier : **le commentaire de `MOTIF` (`errp_models.py:28`) est faux.**
« *le ré-entraînement en écrit d'horodatés* » — aucun chemin de code n'écrit jamais
`errp_model_<horodatage>.joblib`. Le `data/errp_model_20260818-153051.joblib` présent sur le disque a
été produit par un script jetable non versionné (cf. `b35872a`). Donc tout l'appareillage
« du plus récent au plus ancien » de `modeles_disponibles` trie, en pratique, **un seul fichier qui se
fait réécrire à chaque séance**.

### Correctif minimal

Dans `errp_calibrate.py`, copier le geste du jumeau (4 lignes) :

```python
def chemin_modele_horodate(dossier=None):
    """`data/errp_model_AAAAMMJJ_HHMMSS.joblib` — un fichier NEUF, jamais un écrasement."""
    dossier = os.path.dirname(ERRP_MODEL_PATH) if dossier is None else dossier
    return os.path.join(dossier, f"errp_model_{time.strftime('%Y%m%d_%H%M%S')}.joblib")
```

puis `save_path = save_path or chemin_modele_horodate()` ligne 374, et l'assertion jumelle dans
`_smoke` (`horodate != ERRP_MODEL_PATH` et `fnmatch(basename(horodate), errp_models.MOTIF)`).

---

## C2 — L'appli pygame charge `data/errp_model.joblib` par `ErrPModel.load()` sans passer par `charger()` : traceback `ModuleNotFoundError`, jamais le message « ré-entraîne » que ce chantier a écrit pour ça.

**Sévérité : Critical**
**Fichiers : `src/research/app.py:966-972` (`mode_errp`) et `src/research/app.py:1305-1306`
(`page_errp`), rendus atteignables par `src/core/errp_decoder.py:215-217` (`ErrPModel.load` = un
`joblib.load` nu) et par le déménagement du décodeur (cette tranche).**

### Ce qui casse

Les deux sites font `os.path.exists(ERRP_MODEL_PATH)` puis `ErrPModel.load(ERRP_MODEL_PATH)`. Or ce
fichier existe *et* est le pickle hérité. Vidage d'octets, sans exécution :

```
data/errp_model.joblib              : \x8c\x0c errp_decoder       .ErrPModel   (module NU)
data/errp_model_20260818-153051     : \x8c\x11 core.errp_decoder  .ErrPModel
```

Sous `python src/research/app.py`, `sys.path[0]` vaut `src/research` et le second insert donne
`src/` : **le module nu `errp_decoder` n'est importable ni par l'un ni par l'autre** (le fichier vit
dans `src/core/`). `joblib.load` lève `ModuleNotFoundError: No module named 'errp_decoder'`.

Rien ne l'attrape : `page_errp` n'attrape que `Abort` (`app.py:1310-1311`), la boucle de `main`
aussi. L'appli meurt sur un traceback.

C'est mot pour mot le défaut que le chantier P300 a éliminé la veille — `_p300_status`
(`app.py:1079-1088`) : *« L'accueil disait “P300 : oui” sur un simple `os.path.exists` — 3e site du
même défaut, et le plus visible : c'est l'écran MÊME depuis lequel on lance le mode, alors que
`mode_p300` passe par `charger()`, qui REFUSE tout modèle antérieur au 2026-08-17. »* L'ErrP le
reproduit à deux sites, et l'accueil (`_status`, `app.py:1091-1100`) n'a aucune ligne ErrP du tout.

### Scénario concret

1. `python src/research/app.py` → ErrP → « Lancer le démonstrateur ».
2. `os.path.exists(data/errp_model.joblib)` → **True** (le fichier de juillet est là) ⇒ pas de
   `app.flash("Pas de modèle ErrP", …)`.
3. `app.signal_check(...)` passe (l'étudiant a son casque).
4. `ErrPModel.load(...)` → `ModuleNotFoundError` non attrapé → l'appli quitte sur un traceback, au
   milieu d'une séance casque, en ayant déjà fait mettre le casque et saliner les électrodes.
5. Idem pour « Régler le seuil (TPR / TNR) » (`app.py:1305`).

Le message soigneusement écrit dans `errp_models.charger` (« modèle hérité … à ré-entraîner ») n'est
donc **jamais montré à l'endroit où il compte** : `errp_models` n'est importé nulle part dans
`src/research/`.

> À VÉRIFIER PAR EXÉCUTION (aucune ouverture de flux LSL, aucun casque) :
> `python -c "import sys; sys.path.insert(0,'src'); import joblib; joblib.load('data/errp_model.joblib')"`
> depuis la racine — attendu : `ModuleNotFoundError: No module named 'errp_decoder'`.
> (Le `--smoke` de `app.py` ne le reproduit PAS : `_navigate` rend `None` en smoke, `page_errp`
> retourne avant d'appeler `mode_errp`, et le smoke passe ensuite un `save_path` temporaire.)

### Correctif minimal

Aux deux sites, remplacer `os.path.exists` + `ErrPModel.load` par :

```python
from core import errp_models
modele, raison = errp_models.charger(model_path)
if modele is None:
    app.flash("Modèle ErrP inutilisable", raison, 4.0)
    return
```

et ajouter une ligne ErrP à `_status` construite sur `errp_models.modeles_disponibles()`, comme
`_p300_status`.

---

# IMPORTANT

## I1 — L'assertion `n_epoques is None` verrouille le manque : la seule mutation d'une ligne qui la fait rougir est le correctif.

**Sévérité : Important**
**Fichier : `src/core/errp_models.py:341-343`** (avec `errp_models.py:141-147` et
`errp_decoder.py:166-202`).

### Ce qui casse

```python
chk(d["n_epoques"] is None,
    f"n_epoques reste None ({d['n_epoques']}) : ErrPModel ne pose pas cet attribut …")
```

Analyse de mutation demandée : je ne trouve **aucune** mutation d'une ligne de `charger`/`decrire`
qui rougisse ce test. La seule chose qui le rougit est d'ajouter `self.n_epoques_ = int(len(y))` à
`ErrPModel.fit` — c'est-à-dire **le correctif**. Un test dont l'unique mode d'échec est une
amélioration correcte est pire que décoratif : il l'interdit.

Le jumeau assert l'inverse : `chk(d["n_epoques"] == len(y), …)` (`p300_models.py:286-287`), parce que
`P300Model.fit` pose l'attribut en une ligne (`p300_decoder.py:100`). La justification donnée ici
(« ce serait modifier `ErrPModel.fit`, hors périmètre de ce fichier ») ne tient pas : `errp_decoder.py`
est dans la **même tranche et la même série de commits**.

### Scénario concret

Un étudiant ouvre le catalogue de la console : la colonne « époques » est vide pour l'ErrP et
remplie pour le P300, sans que rien ne dise pourquoi. Côté moteur, `ErrPRuntime._open`
(`core/modes/errp.py:242-244`) a dû contourner l'absence par `n_calib=len(self.model.oof_y_)` —
un second chiffre, calculé autrement, pour la même quantité. Le jour où quelqu'un pose enfin
`n_epoques_`, `python src/core/errp_models.py` sort en 1 et le fait passer pour une régression.

### Correctif minimal

Une ligne dans `ErrPModel.fit` (`errp_decoder.py:172`, à côté de `y = np.asarray(y).astype(int)`) :
`self.n_epoques_ = int(len(y))` — plus `self.n_epoques_ = None` dans `__init__` — et l'assertion
alignée sur le jumeau : `chk(d["n_epoques"] == len(y), …)`. À défaut, supprimer l'anti-assertion.

---

## I2 — `_demo()` casse sur `f"{pp:.3f}"` quand la p-value est `None` — exactement le TypeError que le jumeau P300 a documenté et corrigé.

**Sévérité : Important**
**Fichier : `src/core/errp_decoder.py:277-278`.**

### Ce qui casse

```python
print(f"    test de permutation : p={pp:.3f}" + ("" if pp is None else
      (" (significatif)" if pp < 0.05 else " (NON significatif — prudence)")))
```

Le garde-fou `("" if pp is None else …)` prouve que l'auteur savait `pp` nullable — mais il est posé
sur le **mauvais opérande** : la f-string qui formate `pp` est évaluée la première, sans condition.
`f"{None:.3f}"` lève `TypeError: unsupported format string passed to NoneType.__format__`.

`p300_decoder.py:224-227` porte le commentaire écrit pour ce cas précis : *« le formatage doit donc
encaisser None, sinon la seule chose qu'on lirait serait un TypeError dans une f-string, qui masque
la vraie cause imprimée deux lignes plus haut. »* Le jumeau a corrigé ; l'ErrP le refait.

### Scénario concret

`perm_p_` reste `None` dès que `best is None` (`errp_decoder.py:191`), c'est-à-dire quand les trois
`nfilter` échouent au CV : dérive de version pyriemann/sklearn, voie plate rendant la SCM
singulière, `GroupKFold` inconstructible. Alors :

```
[errp] nfilter=2 : CV échouée (…)        <- la vraie cause, imprimée
[errp] nfilter=3 : CV échouée (…)
[errp] nfilter=4 : CV échouée (…)
[1] balayage nfilter (AUC OOF) :   -> RETENU nfilter=2
[2] AUC erreur/correct (GroupKFold par bloc) : 0.0%  (hasard 50%)
Traceback … TypeError: unsupported format string passed to NoneType.__format__
```

`_demo()` ne rend jamais `False` : il **lève**. Le diagnostic est noyé, et le verdict propre
(« à ajuster ») que les 4 lignes suivantes savaient écrire n'est jamais atteint.

> À VÉRIFIER PAR EXÉCUTION (une seconde, aucun import projet) :
> `python -c "pp=None; print(f'p={pp:.3f}')"` — attendu : `TypeError`.

### Correctif minimal

```python
pp_txt = "non testée" if pp is None else f"{pp:.3f}"
print(f"    test de permutation : p={pp_txt}" + ("" if pp is None else …))
```

---

## I3 — Le message du refus hérité ne nomme pas le fichier (les DEUX jumeaux le nomment), ordonne une action que le dépôt ne sait pas faire, et se contredit avec l'autre message de la même fonction.

**Sévérité : Important**
**Fichier : `src/core/errp_models.py:70-72`.**

```python
return None, (f"modèle hérité (module {module!r}, attendu {_MODULE_ATTENDU!r}), "
              f"illisible depuis le déménagement du décodeur — à ré-entraîner depuis "
              f"les époques conservées : data/errp_calib_*.npz")
```

### (a) Aucun nom de fichier — divergence non justifiée avec les deux jumeaux

Les trois autres branches de refus de la **même fonction** finissent par le nom du fichier
(`:48`, `:53`, `:55`, `:86`). `p300_models.py:70` et `mi_models.py:62` le font aussi pour CETTE
branche-là. Ici, non.

*Scénario* : un étudiant a `errp_model.joblib` et `errp_model_backup.joblib`, tous deux hérités. La
liste de la console (via `decrire`) affiche **deux lignes au texte strictement identique**, sans
moyen de savoir laquelle concerne quel fichier — alors que la ligne « calibration trop courte » juste
à côté, elle, nomme le sien.

### (b) L'action prescrite n'existe nulle part dans le dépôt

« à ré-entraîner depuis les époques conservées : `data/errp_calib_*.npz` » : **aucun code ne lit ces
`.npz`**. Vérifié par recherche sur tout `src/` — les seules occurrences de `errp_calib` sont dans
`errp_calibrate._archive`, qui les *écrit*. Le ré-entraînement du 18/08 a été fait par un script
jetable non versionné (cf. `b35872a`). Le seul remède livré est une séance casque complète de
4-5 min.

*Scénario* : l'étudiant lit « ré-entraîne depuis `data/errp_calib_*.npz` », cherche la commande, n'en
trouve aucune — pendant que **l'autre branche de la même fonction** (`:45-46`) lui dit le vrai
remède : « lance `python src/research/app.py`, mode ErrP, et calibre ». Deux instructions
contradictoires pour la même panne, à 25 lignes d'écart.

### (c) « illisible » est faux dans cette branche

On n'entre dans cette branche **que si `joblib.load` a réussi** (c'est comme ça qu'on connaît
`type(modele).__module__`). Les jumeaux écrivent « abandonné délibérément », qui est exact.

### Correctif minimal

```python
return None, (f"modèle hérité (module {module!r}, attendu {_MODULE_ATTENDU!r}), abandonné "
              f"délibérément — recalibre (`python src/research/app.py`, mode ErrP) : "
              f"{_os.path.basename(chemin)}")
```

(et, si l'on tient à la promesse des époques conservées : livrer le script de ré-entraînement, ce qui
est un chantier à part.)

---

## I4 — Le refus « pas de scores hors-pli » affirme une cause qu'il n'a jamais vérifiée, et envoie l'étudiant refaire 5 minutes de casque pour rien.

**Sévérité : Important**
**Fichiers : `src/core/errp_models.py:82-86` et son filet jumeau `core/modes/errp.py:227-231`.**

### Ce qui casse

Le message énumère trois causes — « moins de 10 essais, une seule classe, ou une classe à moins de
2 membres » — et conclut « recalibre **avec plus d'essais** ». Mais `fit` laisse
`oof_scores_ = None` dans **deux** situations (`errp_decoder.py:179-195`) :

1. la garde `len(np.unique(y)) == 2 and len(y) >= 10 and bincount(y).min() >= 2` — les trois causes
   citées ;
2. `best is None` (`:191`) : la garde est passée, mais **les trois `nfilter` ont levé au CV** et ont
   été avalés par le `except … continue` de `:185-187`.

Le cas 2 n'est nommé nulle part, et le remède prescrit (« plus d'essais ») ne le corrige pas.

### Scénario concret

Séance réelle de 200 essais, 5 blocs, une électrode qui a lâché en cours de route → une voie
quasi constante → `XdawnCovariances` sur une SCM singulière lève pour `nfilter` 2, 3 et 4.

```
[errp] nfilter=2 : CV échouée (…)
[errp] nfilter=3 : CV échouée (…)
[errp] nfilter=4 : CV échouée (…)
[errp-cal] 58/200 erreurs  AUC=—  …  modèle -> errp_model.joblib
```

Le modèle est **quand même enregistré** (`fit` finit par `self.core.pipe.fit(Xf, y)` ligne 201, et
`calibrate` par `model.save`). Cinq minutes plus tard, la console ou le moteur le refuse avec :

> « calibration trop courte pour régler un seuil (moins de 10 essais, une seule classe, ou une
> classe à moins de 2 membres — pas de scores hors-pli) : recalibre **avec plus d'essais** »

L'étudiant, qui vient d'en faire 200, rallonge la séance et recommence — et se fait renvoyer le même
message. Deux séances casque perdues sur un diagnostic inventé.

### Correctif minimal

Deux possibilités, la seconde préférable :

1. reformuler : « pas de scores hors-pli (calibration trop courte, **ou validation croisée échouée —
   voir les lignes `[errp] nfilter=… : CV échouée` de l'entraînement**) : … » ;
2. faire porter la raison par le modèle : dans `fit`, `self.echec_oof_ = "garde non atteinte"` /
   `"tous les nfilter ont échoué au CV"`, et laisser `charger` la citer telle quelle. C'est le
   principe déjà appliqué partout ailleurs dans ce chantier (dire ce qu'il faut FAIRE, à partir de
   ce qu'on a réellement observé).

---

## I5 — Deux tests identiques, tous deux insensibles à n'importe quelle mutation d'une ligne du code de production.

**Sévérité : Important** (règle de la méthode : test sans mutation rougissante = décoratif)
**Fichier : `src/core/errp_models.py:220-221` et `:366-371`.**

### Ce qui casse

```python
chk(modeles_disponibles(dossier) == [], "un dossier sans modèle rend une liste vide, il ne lève pas")
…
chk(modeles_disponibles(vide) == [], "un dossier vide rend [], sans lever")
```

C'est **la même assertion deux fois** (au premier appel, `dossier` est vide lui aussi). Mutations
essayées, une ligne chacune, sur `modeles_disponibles`/`charger` :

| mutation | résultat |
|---|---|
| `MOTIF = "*.joblib"` / `"p300_model*.joblib"` | vert (dossier vide) |
| suppression de `key=_os.path.getmtime` | vert |
| suppression de `reverse=True` | vert |
| filtre inversé (`charger(c)[0] is None`) | vert |
| suppression complète du filtre | vert |
| `_glob.glob(dossier)` au lieu du `join` | vert |

Seule une exception inconditionnelle les rougit — et **tous les autres tests du fichier la rougissent
déjà**. Les deux assertions ne protègent donc rien.

### Correctif minimal

Supprimer l'une des deux, et faire mordre l'autre — la faire tester le **filtre** plutôt que
l'absence de fichiers : déposer dans un dossier neuf (a) un fichier au bon motif mais illisible et
(b) un fichier au mauvais motif (`errp_modele.joblib`), puis assert `== []`. Cette version rougit sur
« filtre inversé » et sur « filtre supprimé ».

---

# MINOR

## M6 — Le refus ne regarde que la classe EXTÉRIEURE ; `ErrPModel` est une composition, et le module de son `self.core` n'est vérifié par personne.

**Sévérité : Minor** (trou latent : aucun chemin de code ne le produit aujourd'hui)
**Fichiers : `src/core/errp_models.py:68-72` et `src/core/errp_decoder.py:153`.**

### Ce qui casse

`ErrPModel` n'hérite pas de `P300Model`, il le **contient** (`self.core = P300Model(...)`). Un pickle
d'`ErrPModel` porte donc **deux** chemins de module. Vidage d'octets des deux modèles du disque :

```
data/errp_model.joblib            :  errp_decoder.ErrPModel       + core → p300_decoder.P300Model
data/errp_model_20260818-…        :  core.errp_decoder.ErrPModel  + core → core.p300_decoder.P300Model
```

`charger` ne teste que le premier. Or c'est le second qui SCORE : `ErrPModel.score` →
`self.core.scores` → `self.core.pipe`.

### Scénario concret

La passerelle que ce chantier refuse d'écrire finit par être écrite un jour, mais **à moitié** — par
exemple un script « de dépannage » qui recharge sous un `sys.modules["errp_decoder"] =
core.errp_decoder` puis re-`save()` : la classe extérieure devient `core.errp_decoder.ErrPModel` et
passe le contrôle, pendant que `self.core` reste `p300_decoder.P300Model`, ressuscité depuis le
module fantôme. `_desaccord_geometrie` (`modes/errp.py:198-204`) ne le voit pas non plus : `fs`,
`pre_s`, `post_s` sont posés sur l'objet extérieur. Résultat : le moteur décode avec les
probabilités de quelqu'un d'autre, en silence — le « pire des deux mondes » que ce module existe pour
éliminer. `_ModeleHerite` ne peut pas l'attraper : il n'a pas d'attribut `core`.

### Correctif minimal

Deux lignes après le contrôle existant, plus une fixture :

```python
noyau = type(getattr(modele, "core", None)).__module__
if noyau != "core.p300_decoder":
    return None, (f"le noyau P300 de ce modèle vient du module {noyau!r} … : "
                  f"{_os.path.basename(chemin)}")
```

---

## M7 — La ligne « ce n'est pas un modèle ErrP » n'est couverte par aucune assertion.

**Sévérité : Minor**
**Fichier : `src/core/errp_models.py:54-55`.**

Supprimer entièrement `if not hasattr(modele, "score") or not hasattr(modele, "is_error")` laisse
**tout l'autotest vert** : `_ModeleEtranger` et `_ModeleHerite` possèdent les deux méthodes, et le
fichier corrompu meurt plus haut, dans `joblib.load`. Aucune fixture ne présente un objet dépourvu
de l'interface.

*Scénario* : un `p300_model.joblib` renommé `errp_model_vieux.joblib` (ça arrive quand on range
`data/`). Aujourd'hui il est refusé avec le bon mot (« ce n'est pas un modèle ErrP »). Après la
suppression, il tombe sur le contrôle de module et devient « modèle hérité (module
`'core.p300_decoder'`) — à ré-entraîner » : on envoie l'étudiant recalibrer le **mauvais mode**.

*Correctif* : une fixture de trois lignes — `joblib.dump(object(), …)` ou une classe sans `is_error` —
et `chk("pas un modèle ErrP" in raison, …)`.

## M8 — `pick_threshold` ne se défend toujours pas elle-même : les deux gardes ont été posées chez ses appelants, pas dans la fonction qui produit l'erreur obscure.

**Sévérité : Minor**
**Fichier : `src/core/errp_decoder.py:62-63`.**

Le commit `362fee1` (« Refuse a model with no out-of-fold scores by name, **in two places** ») a
placé la garde dans `errp_models.charger` et dans `ErrPRuntime._sans_scores_oof`. La fonction qui
lève reste nue : `np.asarray(None, dtype=float)` donne un tableau 0-d, et `np.concatenate` lève
`ValueError: zero-dimensional arrays cannot be concatenated`. Un tableau **vide** lève encore
autrement (`scores.min()` → « zero-size array to reduction operation minimum »), et ce cas-là n'est
gardé nulle part.

*Scénario* : le troisième appelant arrive (une page de console, un script d'analyse hors ligne, la
future calibration ErrP côté moteur) et reçoit exactement l'exception que les deux gardes ont été
écrites pour cacher — parce que la protection est chez les appelants, pas à la source.

*Correctif* (2 lignes, en tête de `pick_threshold`) :

```python
scores = np.asarray(scores, dtype=float)
if scores.ndim != 1 or scores.size == 0 or len(np.asarray(y)) != scores.size:
    raise ValueError("pick_threshold : il faut des scores hors-pli 1-D non vides, alignés sur y")
```

## M9 — `modeles_disponibles` peut lever sur `getmtime`, et cette exception est rapportée à l'étudiant comme un « DÉFAUT de déclaration ».

**Sévérité : Minor** (partagé avec les deux jumeaux)
**Fichier : `src/core/errp_models.py:107-108`.**

`sorted(glob(...), key=_os.path.getmtime)` évalue `getmtime` sur **tous** les candidats. Si un
fichier disparaît ou est verrouillé entre le `glob` et la clé, `OSError`/`FileNotFoundError` sort de
la fonction. `Param.choices_status` (`core/modes/contract.py:61-64`) l'attrape, mais la classe
explicitement comme « un `choices_fn` qui lève est un DÉFAUT de déclaration » — c'est-à-dire un bug
du produit.

*Scénario* : l'étudiant ouvre le catalogue de la console pendant qu'une calibration écrit son modèle
(ou pendant qu'un antivirus tient le fichier). Le formulaire annonce un défaut de déclaration du mode
ErrP là où il n'y a qu'une course bénigne.

*Correctif* : `key=lambda c: _os.path.getmtime(c) if _os.path.isfile(c) else 0.0`.

## M10 — La fixture « 5 essais » ne prouve qu'une clause sur trois de la garde, et repose sur une propriété non affirmée.

**Sévérité : Minor**
**Fichier : `src/core/errp_models.py:324-327` (fixture dupliquée à `core/modes/errp.py:675-678`).**

`ErrPModel(fs=fs).fit(epochs[:5], y[:5], n_perm=0)` viole **plusieurs** clauses de la garde
`errp_decoder.py:179` à la fois : `len(y) >= 10` ET (très probablement) `bincount(y).min() >= 2`.
Conséquence pour l'analyse de mutation : muter `len(y) >= 10` en `>= 4` — ou supprimer cette clause —
**laisse le test vert**, parce que la clause de la classe minoritaire refuse toute seule. Le test ne
protège donc que la garde *dans son ensemble*, pas la valeur `10` que son propre message cite.

Second point : si un changement de graine ou de `synth_errp_epoch` faisait que `y[:5]` ne contient
qu'une classe, `fit` lèverait dans `self.core.pipe.fit` (`LogisticRegression: needs samples of at
least 2 classes`) et l'autotest mourrait sur un traceback au lieu d'imprimer `ÉCHEC` — la sortie
resterait 1, donc le dégât est diagnostique, pas fonctionnel.

*Correctif* : construire la fixture explicitement — `y_court = [0, 1, 0, 1, 0]` et les 5 époques
correspondantes — de sorte que « moins de 10 essais » soit la **seule** clause en cause, et que la
mutation de la valeur `10` rougisse.

## M11 — `decrire` est du code mort, et sa docstring affirme le contraire.

**Sévérité : Minor** (hérité du jumeau P300)
**Fichier : `src/core/errp_models.py:112-148`.**

Recherche sur tout `src/` : `errp_models.decrire` n'est appelée que par son propre `_selftest`.
`errp_models` lui-même n'est importé que par `core/modes/errp.py`, qui utilise `charger` et
`modeles_disponibles`, jamais `decrire`. La console (`src/console/`) n'importe pas `errp_models` du
tout. Pourtant la docstring dit : « *c'est sa fonction sœur, et la console appelle les deux depuis le
même formulaire* ». (`p300_models.decrire` est dans le même état ; `mi_models.decrire`, lui, est
réellement appelé — `core/modes/mi_calib.py:356`.)

*Conséquence* : six assertions de l'autotest (`:337-352`) ne testent qu'elles-mêmes, et l'anti-test
I1 vit là-dedans. Ce n'est pas grave en soi — c'est une API prête pour la console — mais la docstring
doit dire « prévue pour », pas « appelée par », sans quoi le prochain lecteur croira qu'un
changement de forme du dict casserait un affichage existant.

*Correctif* : une phrase dans la docstring (« aucun appelant en production aujourd'hui : cette forme
existe pour la parité avec `p300_models.decrire`, que la console lira quand elle affichera les
listes de modèles »).

---

# Récapitulatif des mutations testées (angle 2)

| Test | Mutation d'une ligne qui le rougit | Verdict |
|---|---|---|
| dossier vide == [] (×2, `:220`, `:366`) | aucune | **décoratif** (I5) |
| modèle valide listé (`:242`) | `MOTIF` faux ; filtre inversé ; `_MODULE_ATTENDU` faux | solide |
| illisible absent de la liste (`:250`) | suppression du `try/except` de `joblib.load` | solide |
| raison au lieu d'une levée (`:253`) | idem | solide |
| « introuvable » (`:257`) | suppression du `isfile` → message « illisible (FileNotFoundError) » | solide |
| `charger(None/""/0)` (`:264`) | suppression du `if not chemin` → TypeError | solide |
| `_ModeleEtranger` (`:272`) | suppression du contrôle de module → message « hors-pli », sans « ré-entraîner » | solide |
| `_ModeleHerite` (`:306-312`) | `module.endswith("errp_decoder")` → message sans `'errp_decoder'` | **solide, et c'est LE test du fichier** |
| fixture dégénérée (`:325`) | suppression de la garde entière | partielle (M10) |
| refus « hors-pli » (`:330`) | suppression du contrôle `oof_scores_` | solide |
| `decrire` nom / date / cv_auc (`:338-344`) | `basename` supprimé ; `getmtime` supprimé ; `cv_auc` mal converti | solide |
| `decrire` n_epoques (`:341`) | **seule mutation rougissante = le correctif** | **anti-test** (I1) |
| `decrire(None/""/0)` (`:350`) | suppression du `chemin and` → TypeError | solide |
| tri par date (`:364`) | suppression de `key=getmtime` ou de `reverse` | solide |
| `hasattr score/is_error` (`:54`) | *aucun test ne couvre cette ligne* | **non couvert** (M7) |
| `errp_decoder._demo` verdict (`:289`) | `auc > 0.65` / `tnr` / `pp` — mais le `print` casse avant sur `pp is None` | fragile (I2) |
