# Re-revue B — verdict sur la vague de correction

Périmètre : `src/core/errp_models.py`, `src/core/errp_decoder.py`, `src/research/errp_calibrate.py`,
`src/research/app.py` (commit `4a219e9` et la suite de la vague, HEAD = `faa19c1`).

**Lecture seule. Aucun programme lancé** (ni Python, ni calibration) ; `data/` n'a pas été touché —
seulement listé : `errp_model.joblib` = 35 115 o, 24/07 11:46, et
`errp_model_20260818-153051.joblib` = 38 451 o, 18/08 15:30, tous deux INTACTS. Tous les verdicts
ci-dessous sont établis sur le code du dépôt, pas sur le rapport de l'implémenteur.

## Décompte

**12 ADDRESSED · 1 PARTIEL · 0 NON TRAITÉ · 0 RÉGRESSION** — plus **4 défauts NOUVEAUX** (1 Important,
3 Minor), dont aucun n'est une régression fonctionnelle du code de production.

| # | Constatation | Verdict | Où |
|---|---|---|---|
| C1 | Une calibration écrase `data/errp_model.joblib` | **ADDRESSED** | `errp_calibrate.py:325-344` (`chemin_modele_horodate`) + `:401` (`save_path or chemin_modele_horodate()`) |
| C2 | `ErrPModel.load()` en direct dans l'appli | **ADDRESSED** | `app.py:952-971` (`_errp_charger`), `:1000`, `:1346` ; plus aucun `ErrPModel.load(` dans `src/` |
| I1 | Anti-test `n_epoques is None` | **ADDRESSED** | `errp_decoder.py:185` + `:200` ; assertion RETOURNÉE en `errp_models.py:482` |
| I2 | `_demo()` lève sur `f"{pp:.3f}"` | **ADDRESSED** | `errp_decoder.py:322-324` (`pp_txt`), `_rapport` extrait `:302`, testé `:405-410` |
| I3 | Message du refus hérité | **PARTIEL** | message corrigé `errp_models.py:81-83` ; le remède fantôme SURVIT en `:9-12` et `:67-68` |
| I4 | Le refus « hors-pli » invente sa cause | **ADDRESSED** | `errp_decoder.py:186`, `:231-242` (`echec_oof_`) ; cité tel quel `errp_models.py:116-119` |
| I5 | Deux tests identiques, aucun ne mord | **ADDRESSED** | doublon supprimé `errp_models.py:301-305` ; survivant refait `:514-523` |
| M6 | Le noyau `self.core` n'est vérifié par personne | **ADDRESSED** | `errp_models.py:30`, `:92-97` + fixture `_NoyauEtranger` `:266-279`, test `:413-430` |
| M7 | « ce n'est pas un modèle ErrP » non couvert | **ADDRESSED** | fixture `_ModeleP300Renomme` `errp_models.py:249-263`, test `:367-375` |
| M8 | `pick_threshold` ne se défend pas | **ADDRESSED** | `errp_decoder.py:72-79` ; 3 cas testés `:355-369` |
| M9 | `modeles_disponibles` lève sur `getmtime` | **ADDRESSED** | `errp_models.py:147-149` ; course rejouée `:525-542` |
| M10 | Fixture « 5 essais » multi-clauses | **ADDRESSED** | `errp_models.py:447` (`y_court`) ; idem `errp_decoder.py:373` |
| M11 | `decrire` est du code mort | **ADDRESSED** | `errp_models.py:157-163` |

---

## Réponse aux deux questions décisives

### 1. Ce que le code écrit VRAIMENT comme nom de fichier

`src/research/errp_calibrate.py:343-344` :

```python
dossier = os.path.dirname(ERRP_MODEL_PATH) if dossier is None else dossier
return os.path.join(dossier, f"errp_model_{time.strftime('%Y%m%d_%H%M%S')}.joblib")
```

→ **`data/errp_model_AAAAMMJJ_HHMMSS.joblib`**, par exemple `data/errp_model_20260819_142230.joblib`.
Underscore entre la date et l'heure, secondes comprises. **`docs/markers.md:346-350` dit exactement
la vérité** : le motif donné (`data/errp_model_20260819_142230.joblib`), la phrase « never overwrites
the previous one », « the engine offers the most recent loadable model as its default » et la réserve
sur la résolution d'une seconde sont toutes exactes. Aucun mensonge dans le contrat public.

Les trois vérifications demandées :

- **horodaté** : oui, calqué ligne pour ligne sur `src/research/p300_calibrate.py:238-252` (relu).
- **retrouvé par `errp_models`** : `MOTIF = "errp_model*.joblib"` (`errp_models.py:28`) correspond au
  nom produit ; `modeles_disponibles` trie `key=getmtime, reverse=True` (`:147-149`) donc du plus
  récent au plus ancien, ce que verrouille le test `:494-504` (renommage `_z`/`_a` + `utime` pour
  faire diverger tri alphabétique et tri par date). Le `Param(choices_fn=…)` du mode
  (`core/modes/errp.py:637`) prend `choix[0]` : le dernier calibré est bien le défaut proposé.
- **aucun appelant à chemin fixe** : `calib_errp` (`app.py:1104-1109`) appelle `calibrate(app)` sans
  `save_path` ; `adjust_threshold` ré-enregistre là où il a lu (`app.py:1351`, `errp_calibrate.py:460`).
  Le seul appelant qui passe un `save_path` fixe est le smoke — et il vise
  `data/errp_model_smoke.joblib`, pas `ERRP_MODEL_PATH`, donc l'invariant de C1 tient. **Mais ce
  chemin est dans le VRAI `data/` : voir NOUVEAU-1.**

Attention à ne pas confondre avec `data/errp_model_20260818-153051.joblib` déjà sur le disque, qui
porte un TIRET : il vient du script jetable de ré-entraînement, pas de ce code. Il correspond quand
même à `MOTIF`, donc il reste listé — c'est voulu.

### 2. Les deux entrées de chargement passent-elles par la garde ?

Oui, et il n'y en a pas de troisième.

- `mode_errp` (`app.py:1000`) : `model, probleme, model_path = _errp_charger(model_path)`.
- `page_errp`, « Régler le seuil » (`app.py:1346`) : `modele, probleme, chemin = _errp_charger()`.
- `_errp_charger` (`app.py:965-971`) importe `core.errp_models.charger` — celle qui refuse les hérités
  et ne lève jamais.
- Recherche sur tout `src/` : **zéro appel à `ErrPModel.load(`** et zéro `joblib.load` sur un chemin
  ErrP hors de `errp_models.charger`. Les seuls `ErrPModel(` restants sont des constructions
  légitimes (calibration `errp_calibrate.py:443`, fixtures de test).
- Bonus non demandé mais correct : l'accueil a maintenant sa ligne ErrP (`app.py:1132`, `:1136`),
  construite sur `modeles_disponibles()` comme le jumeau `_p300_status`.

Réserves honnêtes, aucune bloquante :

- `ErrPModel.load` existe toujours comme `@staticmethod` (`errp_decoder.py:257-259`), sans appelant :
  la porte est fermée, pas murée. Parité exacte avec `p300_decoder.py:152`, donc pas une divergence.
- L'assertion du smoke (`app.py:1524-1529`) ne balaie que `mode_errp` et `page_errp`. Un troisième
  site écrit ailleurs (par exemple dans `calib_errp`) ne serait pas vu. Le jumeau P300 n'a même pas
  cette assertion : divergence dans le bon sens.

### 3. Le point de conception : la promesse retirée

**Jugement : c'est le bon choix, et le nouveau message est vrai et actionnable.**
`errp_models.py:81-83` dit désormais « modèle hérité (module …, attendu …), abandonné délibérément —
recalibre (`python src/research/app.py`, mode ErrP) : errp_model.joblib ». Les trois défauts de I3
sont corrigés : le fichier est nommé, « illisible » est remplacé par « abandonné » (exact : on
n'entre dans cette branche que si `joblib.load` a RÉUSSI), et le geste prescrit est celui que la
branche « aucun modèle désigné » (`:46-47`) prescrivait déjà — les deux instructions contradictoires
n'en font plus qu'une. Le refus reste un refus : aucune passerelle, la décision figée est respectée.

**Mais le remède fantôme n'a pas disparu du fichier** — voir I3 ci-dessous, seul verdict non-ADDRESSED.

---

## I3 — PARTIEL : le remède fantôme survit deux fois dans le même fichier

Le message d'erreur est corrigé. Le reste de `src/core/errp_models.py` prescrit encore le remède
qu'aucun code du dépôt ne sait exécuter :

1. **Docstring de module, `errp_models.py:9-12`** — la première chose que lit un étudiant qui ouvre
   le fichier :
   > « les époques de calibration ayant survécu (`data/errp_calib_last.npz`, plus des horodatées),
   > **un modèle se ré-entraîne depuis le disque en quelques secondes** »

   C'est faux, et c'est la version la plus dommageable de la promesse : elle chiffre le remède
   (« quelques secondes ») là où le seul remède livré est une séance casque de 4-5 min.

2. **Commentaire dans `charger`, `errp_models.py:67-68`** :
   > « Contrairement au MI, les époques de calibration ont survécu (`errp_calib_*.npz`) : on ne
   > garde donc PAS ce modèle « en dépannage », **on dit de ré-entraîner**. »

   Or le commentaire ajouté **huit lignes plus bas** (`:76-78`) dit l'inverse : « aucun code de ce
   dépôt ne lit ces .npz (le ré-entraînement du 18/08 a été fait par un script jetable, non
   versionné) ». Les deux commentaires encadrent la même ligne de code et se contredisent.

### Scénario concret

Un étudiant se voit refuser `data/errp_model.joblib`. Le message d'erreur lui dit maintenant la
vérité : « recalibre ». Il ouvre `src/core/errp_models.py` pour comprendre pourquoi — c'est un
public qui lit et modifie ce code, CLAUDE.md le dit — et il lit en tête du fichier qu'un modèle
« se ré-entraîne depuis le disque en quelques secondes ». Il cherche la commande, ne la trouve pas,
et conclut soit qu'il lui manque un fichier, soit que l'outil est cassé. On l'a envoyé à la même
porte fermée, par un autre couloir.

### Correctif minimal (2 phrases, aucun code)

- `:9-12` → « les époques de calibration ont survécu (`data/errp_calib_*.npz`), mais **aucun script
  de ce dépôt ne sait encore les relire** : le seul remède livré est une nouvelle calibration
  (4-5 min). »
- `:67-68` → supprimer « on dit de ré-entraîner » (redondant avec `:76-78`, et faux).

---

## Défauts NOUVEAUX

### NOUVEAU-1 (Important) — Le smoke de l'appli écrit dans le VRAI `data/`, sous un nom qui correspond à `MOTIF`, et nettoie hors de tout `finally`

**Fichier : `src/research/app.py:1412-1440`.**

```python
tmp = os.path.dirname(CVEP_MODEL_PATH)          # = DATA_DIR, le VRAI data/  (config.py:19, :316)
errp_path = os.path.join(tmp, "errp_model_smoke.joblib")
...
errp_calibrate.calibrate(app, save_path=errp_path)
mode_errp(app, model_path=errp_path)
for p in (cvep_path, rcca_path, p300_path, errp_path):
    if os.path.exists(p):
        os.remove(p)                             # PAS dans un finally
```

Le fichier écrit s'appelle `errp_model_smoke.joblib` : il **correspond à `errp_models.MOTIF`**
(`errp_model*.joblib`) et il porte le mtime le plus récent de `data/`.

C'est **antérieur à la vague** (vérifié : les lignes existent déjà dans `4a219e9~1`), donc ce n'est pas
une régression introduite ici. Mais la vague le rend beaucoup plus grave : avant, l'appli lisait un
nom FIXE (`ERRP_MODEL_PATH`) et un smoke oublié lui était invisible. Maintenant, `_errp_charger(None)`
(`app.py:967-969`) et `_status` (`app.py:1132`) prennent `modeles_disponibles()[0]`, exactement comme
le `choices_fn` du moteur (`core/modes/errp.py:637`) et sa `default_now()`.

**Scénario concret.** `python src/research/app.py --smoke` sur un poste. La calibration écrit
`data/errp_model_smoke.joblib` (12 époques, board synthétique). La ligne suivante, `mode_errp(app,
model_path=errp_path)`, lève — une exception pygame headless, un `KeyboardInterrupt`, n'importe quoi.
Le `os.remove` n'est jamais atteint. Le lendemain, l'étudiant lance `python src/core/server.py
--mode errp` : le formulaire lui propose comme **défaut** `errp_model_smoke.joblib`, le plus récent
modèle chargeable, et le moteur publie sur `decoded_errp` les décisions d'un modèle entraîné sur
12 époques de bruit synthétique. Aucun message : le fichier est valide, il a des scores hors-pli, sa
géométrie concorde. Même chose pour l'appli (« ErrP : 1 (errp_model_smoke.joblib) » sur l'accueil) et
pour la console.

**Correctif minimal** : `tmp = tempfile.mkdtemp(prefix="app_smoke_")` et `shutil.rmtree(tmp,
ignore_errors=True)` dans un `finally` autour des lignes 1429-1440 — le geste que `errp_models._selftest`
(`:299`, `:545-546`) et `p300_models._selftest` appliquent déjà correctement. À défaut : envelopper la
séquence dans un `try/finally`. (Le même défaut vaut pour `p300_model_smoke.joblib`,
`cvep_model_smoke.npz` et `cvep_rcca_model_smoke.npz` — c'est une correction unique pour les quatre.)

### NOUVEAU-2 (Minor) — Sur un dépôt fraîchement cloné, l'appli ne dit plus quoi faire

**Fichier : `src/research/app.py:967-971` (`_errp_charger`), effet visible en `:1001-1003` et `:1347-1349`.**

```python
if model_path is None:
    dispo = modeles_disponibles()
    model_path = dispo[0] if dispo else ERRP_MODEL_PATH
modele, probleme = charger(model_path)
```

Quand `dispo` est vide — l'état exact d'un dépôt cloné, donc de tout nouvel étudiant — on retombe sur
`ERRP_MODEL_PATH`, un fichier qui n'existe pas, et `charger` répond
`"modèle introuvable : C:\Users\…\data\errp_model.joblib"`. Le repli `probleme or "lance d'abord
« ErrP -> Calibrer » (~4-5 min)"` de `mode_errp` **ne s'active jamais**, puisque `probleme` n'est
jamais vide. L'ancien code, lui, affichait « lance d'abord « ErrP -> Calibrer » (~4-5 min) ».

Ironie : `charger(None)` a précisément la bonne phrase pour ce cas
(`errp_models.py:46-47` : « aucun modèle désigné — lance `python src/research/app.py`, mode ErrP, et
calibre pour en produire un »), écrite dans ce chantier, et le repli sur `ERRP_MODEL_PATH` l'empêche
d'être atteinte.

**Scénario concret.** Un étudiant clone le dépôt, lance `python src/research/app.py`, va sur ErrP →
« Lancer le démonstrateur ». Il lit : *Pas de modèle ErrP utilisable — modèle introuvable :
C:\Users\Lab_IA\Documents\Projets_Dev\EEG_API_Unicorn\data\errp_model.joblib*. Un chemin absolu
Windows, aucun verbe, aucune action. Il n'a aucune raison de deviner que la réponse est le troisième
item du menu qu'il vient de quitter.

**Correctif** : `model_path = dispo[0] if dispo else None`, et laisser `charger(None)` parler.
⚠️ **Ce n'est pas une divergence avec le jumeau — c'en est une copie fidèle** : `mode_p300`
(`app.py:639-641`) fait exactement pareil avec `P300_MODEL_PATH`. À corriger aux deux endroits, ou à
assumer aux deux ; ne pas corriger l'ErrP seul.

### NOUVEAU-3 (Minor) — Une assertion ajoutée qui ne peut rougir sur aucune mutation de production

**Fichier : `src/core/errp_models.py:450-452`.**

```python
y_court = np.asarray([0, 1, 0, 1, 0])                                    # :447
...
chk(len(np.unique(y_court)) == 2 and int(np.bincount(y_court).min()) >= 2,
    f"fixture : les 2 classes sont là, avec >= 2 essais chacune — seul « moins de 10 "
    f"essais » peut refuser ce modèle ({np.bincount(y_court).tolist()})")
```

L'assertion porte sur un **littéral écrit trois lignes plus haut**, jamais sur du code de production.
Mutations essayées mentalement sur `charger`, `modeles_disponibles`, `decrire`, `ErrPModel.fit`,
`pick_threshold` : **aucune** ne la rougit. Sa seule mutation rougissante est d'éditer le test
lui-même. C'est exactement le critère par lequel la revue a condamné I5 (« un dossier vide rend [] »),
appliqué ici à une assertion écrite par la correction de I5/M10.

L'intention est bonne — documenter que « moins de 10 essais » est la seule clause en cause, ce que le
correctif de M10 demandait. Mais alors c'est un **commentaire**, pas un `chk` qui gonfle le compteur
d'assertions du verdict.

**Scénario concret.** Le prochain lecteur compte les assertions de `errp_models.py` pour juger de la
couverture du module et en crédite une qui ne peut protéger aucune ligne du produit. Pire : le jour
où quelqu'un ajuste `y_court`, il verra rougir un `ÉCHEC` estampillé « fixture », comprendra qu'il
doit « réparer le test », et le corrigera dans le sens qui le rend vert — sans jamais découvrir que
c'est la clause `len(y) >= 10` qu'il vient de cesser de tester.

**Correctif** : supprimer le `chk` et déplacer son texte dans le commentaire déjà présent
(`:442-446`), qui dit d'ailleurs déjà la même chose.

*(Note : le reste des assertions ajoutées, elles, mordent — vérifié une par une. `pick_threshold`
(3 cas) rougit sur le retrait de la garde `errp_decoder.py:74-79` ; `echec_oof_` sur le retrait de
l'une ou l'autre branche `:231-242` ; `n_epoques_` sur le retrait de `:200` ; `_rapport` sur le retour
à `f"{pp:.3f}"` ; `_NoyauEtranger` sur le retrait de `errp_models.py:92-97` ; `_ModeleP300Renomme`
sur le retrait du `hasattr` `:55` ; le test de filtre `:521` sur `MOTIF = "*.joblib"`, sur
l'inversion du filtre et sur sa suppression ; la course `glob`/`getmtime` `:540` sur le retour à
`key=_os.path.getmtime` nu. L'anti-test I1 a bien été RETOURNÉ, pas supprimé, et dans le bon sens :
`chk(d["n_epoques"] == len(y))` — identique au jumeau `p300_models.py:286-287` — rougit sur la
suppression de `self.n_epoques_ = int(len(y))`.)*

### NOUVEAU-4 (Minor) — La couverture d'exécution de `mode_errp` par le smoke est devenue conditionnelle, en silence

**Fichier : `src/research/app.py:1436-1437`.**

Avant la vague, `mode_errp` faisait `ErrPModel.load(model_path)` : ça réussissait toujours, donc la
boucle live du démonstrateur était réellement parcourue par le smoke. Maintenant elle passe par
`charger`, qui **EXIGE `oof_scores_`**. Le modèle du smoke est entraîné sur 12 époques (2 blocs × 6)
d'un board synthétique. Si les trois `nfilter` tombent au CV — une version différente de
sklearn/pyriemann, une autre machine, un jour de malchance sur la graine — `charger` le refuse,
`mode_errp` fait `app.flash(...)` puis `return` (`:1001-1004`), et `_smoke` imprime quand même
`[app] smoke OK`. Rien n'assert que `mode_errp` a fait autre chose que sortir tout de suite.

**Scénario concret.** Une mise à jour de `pyriemann` change le comportement de `XdawnCovariances` sur
de très petits effectifs. Le smoke reste vert sur les trois postes du labo. Personne ne remarque que
le démonstrateur ErrP — la boucle piste/feedback/décision, ~120 lignes — n'est plus exercée par
aucun test, jusqu'à la prochaine séance casque.

**Correctif (1 ligne)**, juste après la calibration du smoke :

```python
assert errp_models.charger(errp_path)[0] is not None, (
    "le modèle du smoke doit être ACCEPTÉ par charger(), sinon mode_errp sort avant sa boucle "
    "et le démonstrateur ErrP n'est plus testé du tout")
```

---

## Divergences avec le jumeau P300 — toutes justifiées

Vérifié dans les deux sens, aucune constatation :

- **ErrP en avance sur P300** : contrôle du noyau `self.core` (`errp_models.py:92-97` — le P300 n'en a
  pas besoin, `P300Model` n'est pas une composition) ; garde `getmtime`/`isfile` (`:147-149`, absente
  de `p300_models.py:90-91` et de `mi_models`) ; test de filtre réel au lieu du dossier vide
  (`p300_models.py:189` et `:313` portent encore les deux assertions décoratives que I5 a condamnées
  ici). Ce sont des corrections non répercutées sur les jumeaux, pas des défauts de l'ErrP.
- **Messages du refus hérité** : l'ErrP dit « recalibre », le P300 dit « ré-entraîner depuis les
  époques de calibration conservées (data/p300_calib_*.npz) ». Divergence assumée et **justifiée par
  le commentaire `errp_models.py:71-80`**. Elle pose en revanche la question symétrique, hors de mon
  périmètre : `p300_models.py:69-70` prescrit-il, lui aussi, une porte fermée ?
- **`p300_models.py:27`** (`MOTIF = … ; le ré-entraînement en écrit d'horodatés`) est devenu périmé le
  jour où `p300_calibrate.chemin_modele_horodate` a été écrit : c'est la CALIBRATION qui en écrit
  d'horodatés. L'ErrP a corrigé cette formulation chez lui (`errp_models.py:28`), pas chez le jumeau.
  Hors périmètre, une ligne.

## Contraintes du projet — toutes tenues

- **Frontière `core/`** : `errp_models.py` et `errp_decoder.py` n'importent ni `research`, ni
  `console`, ni pygame, ni Qt. `errp_calibrate.py` et `app.py` importent `core`, dans le bon sens.
- **Français** : code, commentaires et messages, partout, y compris les nouveaux.
- **Sans casque** : `errp_decoder._gardes` est purement synthétique et n'écrit aucun fichier ;
  `errp_models._selftest` n'écrit que dans deux `tempfile.mkdtemp`, tous deux `rmtree` dans un
  `finally` (`:299`/`:514`, `:543-546`). Les monkeypatchs (`_glob.glob`, `globals()["build_pipe"]`)
  sont restaurés dans un `finally`. **Le seul test qui écrit dans le vrai `data/` est le smoke de
  l'appli : NOUVEAU-1.**
- **Sortie en 1** : `errp_models.py:552-554` et `errp_decoder.py:432-434`.
- **Pas de passerelle de compatibilité** : le refus est resté un refus ; la vague n'a touché que sa
  formulation, et l'a durci d'un contrôle de plus (le noyau).

## Détail cosmétique, sans scénario

`src/research/errp_calibrate.py:18` : la phrase insérée dans la docstring de module fait ~180
caractères sur une ligne (« … (cf. `chemin_modele_horodate`). Métriques honnêtes : AUC … »), là où
tout le reste du fichier se replie vers 100. Un retour à la ligne avant « Métriques honnêtes ».
