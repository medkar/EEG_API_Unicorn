# Vague 2 — calibration + décodeur rCCA

Base `523f0c5`. Périmètre : `src/research/cvep_calibrate.py`, `src/core/cvep_rcca.py`,
`src/research/cvep_rcca.py`, `archive/cvep_rcca_pilot.py`, `archive/README.md`.
`archive/cvep_pilot.py` était dans le périmètre mais aucune des 12 constatations assignées ne le
touche : **non modifié**.

`data/` : **43 fichiers, horodatages identiques avant/après** (`cvep_rcca_model.npz` toujours au
2026-08-21 14:17:45.283518300). Aucune calibration réelle lancée. Vérifié par `diff` de
`ls -la --time-style=full-iso data/` pris avant la première commande et après la dernière.

---

## Ce qui est traité

| # | Constatation | Fichier | Test |
|---|---|---|---|
| 1 | **E-C1** ITR doublé | `cvep_calibrate.py` | ✅ rouge-puis-vert |
| 2 | **E-C2** ordre `codes_vus` ≠ ordre du plan | `cvep_calibrate.py` | ✅ rouge-puis-vert (rotation = 2) |
| 3 | E-I1 « 64,9 contre 59,5 » inversé | `cvep_calibrate.py` | ✅ (via la fixture, #4) |
| 4 | E-M1 fixture qui ment sur ses chiffres | `cvep_calibrate.py` | ✅ rouge-puis-vert |
| 5 | C-I3 `_rejouer` compare deux pourcentages bruts | `core/cvep_rcca.py` | ✅ rouge-puis-vert |
| 6 | C-I5 seuils choisis in-sample | `core/cvep_rcca.py` | ✅ rouge-puis-vert |
| 7 | C-I4 « jeu égal » sans provenance | 4 fichiers | ✅ lecture (documentaire) |
| 8 | C-I1 `--seuils` meurt à k=2 vide | `core/cvep_rcca.py` | ✅ rouge-puis-vert |
| 9 | C-I2 `pyntbci` absent | `core/cvep_rcca.py` | ⚠️ **moitié faite** (voir « reporté ») |
| 10 | C-I6 commentaire du test 2 bis | `core/cvep_rcca.py` | ✅ (commentaire + message d'assertion) |
| 11 | C-m3 `_rejouer` rend `True` en dur | `core/cvep_rcca.py` | ✅ rouge-puis-vert |
| 12 | C-m8 lags périmés → `ValueError` | `core/cvep_rcca.py` | ✅ rouge-puis-vert |

---

## 1. E-C1 — l'ITR affiché était exactement doublé

`calibrate()` calculait `cycle_s = L / app.refresh` (**un** cycle) alors que `cv_e`/`cv_r` sont
mesurées à `CVEP_DECISION_CYCLES` depuis ce chantier.

**Correctif** : `entraine_les_deux` rend maintenant `n_cycles` **dans le même dict que la
justesse**, et `calibrate()` en dérive la durée :

```python
k_decision = res["eCCA"]["n_cycles"]      # la géométrie où cv_e/cv_r ont ÉTÉ MESURÉES
decision_s = k_decision * L / app.refresh
```

Ce n'est donc pas une constante recopiée : changer `n_cycles` déplace les deux chiffres ensemble.
La ligne imprimée redit la convention, supprimée au chantier précédent :
`… (hasard 33%), décision = 2 cycle(s) (2.10s) :`.

**ITR corrigé sur la séance de référence** (6 cibles, eCCA 22/37 = 59,5 %, rCCA 24/37 = 64,9 %,
L = 63 @ 60 Hz, T = 2,10 s) :

| | corrigé (T = 2,10 s) | ce qu'affichait HEAD (T = 1,05 s) |
|---|---|---|
| eCCA | 19,1 bits/min | 38,3 |
| rCCA | **23,8 bits/min** | **47,7** |
| verdict (seuil `ref/2` = 25,0) | **FAIBLE (contact électrodes ? regard qui décroche ?)** | PROMETTEUR |

23,8 se lit contre les 22 bits/min du README ; 47,7 ne correspondait à rien de mesuré.

**Effet de bord traité** : le contrôle à mi-parcours mesure et convertit à 1 cycle (cohérent en
soi) — la ligne imprimée le dit maintenant explicitement, puisque c'est là que les deux échelles
se croisent sous les yeux de l'étudiant.

### Preuve rouge (mutation : `decision_s = L / app.refresh`)

```
ÉCHEC la DURÉE de décision imprimée est celle où la justesse a été mesurée (2 cycles = 2.10s),
      pas un cycle (1.05s) — le facteur 2 exact ('décision = 2 cycle(s) (1.05s)')
[cvep-calibrate] VERDICT : PROBLÈME          exit 1
```

Vert après restauration : `EXIT=0`.

⚠️ **Note de conception du test** : l'assertion qui porte la preuve est celle sur la **durée
imprimée**, pas celle sur la valeur d'ITR. Sur le board de test la justesse tombe sous le hasard,
`itr()` rend alors `0.0` aux **deux** géométries et une assertion sur le seul ITR resterait verte.
L'assertion ITR est conservée en second rideau : elle vérifie que le bits/min imprimé se recalcule
à partir de la **durée imprimée à côté de lui**, donc que les deux chiffres de la même ligne
décrivent le même décodeur.

---

## 2. E-C2 — deux correctifs de la tâche 6 s'annulaient hors rotation zéro

`presentes` était trié **par valeur de lag** ; `RCCADecoder` et `cvep_models._codes_affiches`
apparient **par position dans le plan**. Les deux ordres ne coïncident qu'à
`CVEP_LAG_ROTATION = 0`, le seul cas testé.

**Correctif de la cause** :

```python
presentes = sorted(set(labels), key=lambda l: lag_a_idx[l])
```

**Correctif de la conséquence nommée** (séance tronquée) : `calibrate()` ne sauvegarde plus le
modèle rCCA quand la séance n'a pas vu toutes les cibles du plan — il porterait 3 codes pour un
stimulus qui en affiche 6, `cvep_models.charger` le refuserait, et l'écran annonçait quand même
« modèles sauvegardés : … (rCCA) » pour un artefact que rien ne peut charger. Le message le dit,
et la comparaison (qui reste valable) continue de s'afficher. Le modèle eCCA, lui, est sauvegardé
comme avant.

**Nouveau test à rotation ≠ 0** (`core.cvep_code.CVEP_LAG_ROTATION` détourné à 2, restauré dans un
`finally`) : les codes du modèle sont ceux du plan **dans l'ordre du plan**, `cvep_models.charger`
l'**accepte**, et le contrôle externe via `RCCADecoder` sur le modèle relu désigne la cible
réellement affichée.

### Preuve rouge (mutation : `presentes = sorted(set(labels))`)

```
ÉCHEC le modèle rCCA calibré à rotation 2 porte les codes du plan DANS L'ORDRE DU PLAN, pas triés
      par valeur de lag — c'est l'ordre, et lui seul, qui apparie un score à un nom de cible
ÉCHEC ...donc `cvep_models.charger` l'ACCEPTE — un modèle qu'on vient de calibrer sans rien avoir
      changé ne doit pas être refusé (ce modèle rCCA a été calibré sur d'AUTRES codes que ceux
      affichés aujourd'hui : mêmes dimensions, mais pas les mêmes codes ni le même ordre […])
[cvep-calibrate] VERDICT : PROBLÈME          exit 1
```

Preuve rouge de la moitié « séance tronquée » (mutation : `rcca.save(rcca_save_path)`
inconditionnel) :

```
ÉCHEC une séance tronquée sauvegarde l'eCCA et PAS le rCCA (['e.npz', 'r.npz'])
[cvep-calibrate] VERDICT : PROBLÈME          exit 1
```

Vert après restauration dans les deux cas : `EXIT=0`.

---

## 3-4. E-I1 (inversion) et E-M1 (fixture)

Les faits : **eCCA 22/37 = 59,5 %**, **rCCA 24/37 = 64,9 %**, b = 3 (eCCA seul), c = 5 (rCCA seul).
Les quatre emplacements sont corrigés et **nomment le décodeur** au lieu de laisser l'ordre porter
le sens : docstring de `_gagnant`, commentaire de la section McNemar du selftest, commentaire de la
fixture « cas réel », message d'assertion. La docstring de `_gagnant` porte désormais la règle :
*« écrire `<décodeur> <valeur>`, jamais une valeur nue »*.

`_corrects_fabrique` prend un quatrième paramètre `n_faux` (concordances **fausses**), et le cas
réel s'écrit `_corrects_fabrique(19, 3, 5, n_faux=10)` — la seule combinaison qui reproduise
22/37 et 24/37. Une assertion vérifie que la fixture dit vrai sur elle-même.

### Preuve rouge (mutation : retour à `_corrects_fabrique(29, 3, 5)`)

```
ÉCHEC la fixture « cas réel » reproduit VRAIMENT les chiffres qu'elle annonce : 37 décisions,
      eCCA 32/37 = 86.5 %, rCCA 34/37 = 91.9 % — une fixture qui ment sur ses propres chiffres
      est crue par le lecteur suivant
[cvep-calibrate] VERDICT : PROBLÈME          exit 1
```

---

## 5. C-I3 — McNemar dans `--seuils`

`_mcnemar_p` et `SEUIL_MCNEMAR` **déménagent** de `research/cvep_calibrate.py` vers
`core/cvep_rcca.py` (`core/` n'importe jamais `research/` : la règle du dépôt dit que c'est le
module visé qui bouge). `cvep_calibrate` les ré-importe — sens autorisé — et une assertion, du bon
côté de la frontière, vérifie que les deux appelants partagent **le même objet**.

`_rejouer` imprime maintenant, sous les deux pourcentages :

```
[seuils]   McNemar apparié (MÊMES groupes) : eCCA seul 3, rCCA seul 5 -> 8 décisions discordantes
           sur 37, p=0.727 — aucune différence détectable entre les deux décodeurs (ce qui n'est
           PAS « ils se valent »)
```

Les deux pourcentages restent, avec un commentaire disant qu'ils **décrivent** et que c'est la
ligne suivante qui **compare**.

### Preuve rouge (mutation : la ligne McNemar redevient « deux pourcentages »)

```
ÉCHEC ...et la comparaison des deux décodeurs passe par McNemar APPARIÉ, pas par les deux
      pourcentages côte à côte que `bd3b588` a bannis de l'écran de calibration ([])
[cvep-rcca] VERDICT : PROBLÈME               exit 1
```

---

## 6. C-I5 — les seuils sont choisis in-sample

La réserve est écrite **là où le chiffre est lu**, aux deux endroits :

- docstring de `point_de_fonctionnement`, juste après « Ne choisit rien, décrit. » — nomme le
  0,24/0,08 de `config.py`, nomme la famille (`measured_on` de l'ErrP), et dit que le seul chiffre
  non biaisé demanderait une seconde séance ;
- **sortie de `--seuils`**, en tête, avant le tableau qu'on lit pour choisir.

### Preuve rouge (mutation : la réserve n'est plus imprimée par `--seuils`)

```
ÉCHEC ...et le tableau dit, LÀ OÙ IL EST LU, que le couple qu'on y choisira aura un point de
      fonctionnement optimiste — sélectionné sur les décisions qui le mesurent
[cvep-rcca] VERDICT : PROBLÈME               exit 1
```

---

## 7. C-I4 — provenance de « indiscernables » / « fait jeu égal »

Quatre fichiers, la même correction : l'affirmation repose désormais sur le **McNemar apparié à
k=2** (la géométrie du moteur) et non sur la coïncidence des deux totaux à k=1, et elle est
formulée en **absence de preuve de différence**, jamais en équivalence.

- `core/cvep_rcca.py:15-32` — les deux géométries l'une sous l'autre, le McNemar, la commande qui
  le rejoue, et le ⚠️ « pas de différence détectable n'est PAS équivalents » ;
- `research/cvep_rcca.py:19-26` — « fait jeu égal (43/90 chacun) » → « n'est pas DISTINGUABLE de
  l'eCCA sur la seule séance mesurée », avec p, n et la réserve ;
- `archive/cvep_rcca_pilot.py:6` — même geste ;
- `archive/README.md` (ligne `cvep_rcca_pilot.py`) — « ~48% for both decoders » → les chiffres k=2,
  le McNemar, et « "Not detectable" is not "equivalent" » ;
- `research/cvep_calibrate.py:524` — « un jeu parfaitement égal » → « aucune différence DÉTECTABLE,
  McNemar p=0,73 sur 37 décisions ; ce qui n'est pas “ils se valent” ».

Documentaire, donc vérifié par relecture — pas de test.

---

## 8, 11, 12. C-I1 / C-m3 / C-m8 — `--seuils` refuse au lieu de mourir

Un seul refus nommé en tête de `_rejouer` couvre toute la famille « ce fichier ne décrit pas le
stimulus affiché aujourd'hui » (`KeyError` sur `d["lags"]`, `ValueError: 21 is not in list` sur
`lag_de_cible.index`, `.npz` illisible) — même formulation que `cvep_models.charger`, et
`return False`.

Un second refus, **local à la géométrie**, ferme le chemin `n_dec == 0` **avant tout calcul** — ce
qui supprime d'un coup les trois tracebacks distincts (`AxisError` côté eCCA, `nan` puis
`ValueError: cannot convert float NaN to integer` côté rCCA). k=1 continue d'être mesuré
normalement : le refus n'avale pas le rapport.

Deux gardes de plus, sur la même cause :

- `point_de_fonctionnement` rend `None` partout sur une entrée vide, au lieu d'un `nan` là où sa
  docstring promet une proportion (`RCCAModel._hors_pli` pré-alloue `(0, n)`, donc la garde de
  forme laissait passer un tableau bien formé et vide) ;
- le tableau imprime « — » plutôt que de planter sur `corrects_gardes * 100` avec `None` — le
  troisième traceback de la famille, et le plus probable des trois : 6 cibles / 12 décisions /
  zéro correcte arrive une fois sur neuf par pur hasard.

`_rejouer` rend `mesuree` au lieu de `True` en dur.

Trois fixtures de calibration **synthétiques**, écrites dans un dossier temporaire (jamais `data/`).

### Preuves rouges

```
MUTATION le try/except ne rattrape plus la lecture (retour au code d'origine)  -> exit 1
    ValueError: 53 is not in list

MUTATION le refus de fichier rend True au lieu de False                        -> exit 1
    ÉCHEC --seuils sur un fichier aux lags PÉRIMÉS refuse en le nommant et sort en 1 […] (True, …)
    ÉCHEC ...et un `.npz` qui n'est pas une calibration est refusé POUR CE QU'IL EST […] (True, …)

MUTATION pas de garde à zéro groupe (`if n_dec == 0` -> `if False`)            -> exit 1
    numpy.exceptions.AxisError: axis 1 is out of bounds for array of dimension 1
```

⚠️ **Limite mesurée, à ne pas croire couverte** : muter la ligne finale `return mesuree` en
`return True` **ne rougit rien**. Ce qui rend `sys.exit(0 if _rejouer(...) else 1)` vivant — et ce
qui est testé — c'est le `return False` du **refus de fichier**. La branche « aucune géométrie n'a
rien produit » reste défensive : `groupes_de_cycles(y, 1)` ne rend `[]` que sur un fichier à zéro
époque, que `fit` refuserait avant. C'est écrit dans le code, à la ligne concernée.

---

## 9. C-I2 — `pyntbci` absent : moitié faite

**Fait, dans le périmètre** (`core/cvep_rcca.py`) : `_fit_clf` lève une `PyntbciManquant`
(sous-classe d'`ImportError`) portant un message actionnable — `pip install -r requirements.txt`,
et « l'eCCA n'en dépend pas ». Le **nom de la classe** est choisi pour le message que l'étudiant
lira : `cvep_models.charger` n'affiche que `type(e).__name__`, donc « modèle illisible
(ModuleNotFoundError) » devient « modèle illisible (PyntbciManquant) » — moins bon qu'un vrai
message, mais il n'envoie plus chercher un fichier corrompu.

**Non fait — hors périmètre** (`core/cvep_models.py`, `requirements.txt` : ni dans la liste des
fichiers assignés, ni dans la liste des interdits ; ne pas y toucher pour ne pas entrer en
collision avec un autre lot) :

```python
# core/cvep_models.py:176-179, avant le `except Exception` générique
    except PyntbciManquant as e:
        return None, f"{e} (fichier : {nom})"
```

et surtout la **disparition silencieuse** : `modeles_disponibles` filtre sur
`charger(c)[0] is not None`, donc sans la dépendance **tous** les modèles rCCA s'évaporent de la
liste de la console, sans un mot. Un ⚠️ dans la docstring de `PyntbciManquant` porte le reste à
faire, avec le patch. `requirements.txt` liste bien `pyntbci>=1.9` ; la borne `<2` proposée par la
revue reste à poser.

---

## 10. C-I6 — le commentaire du test 2 bis

Le message d'assertion disait « les DEUX décodeurs désignent la même cible » — un test d'**accord**.
C'en est un de **justesse doublé** (les deux membres comparent à la vérité terrain), et c'est
précisément ce qui le rend robuste à une inversion **simultanée** des deux conventions : deux
conventions inversées ensemble se mettent d'accord sur la cible de lag `lag_vrai + 2p`, donc un
test d'accord resterait vert sur 8 des 9 phases parcourues. Commentaire et message réécrits, avec
un ⛔ explicite contre la « simplification » qui détruirait le garde.

---

## Reporté, avec motif

**Constatations E non assignées à ce lot** (elles concernent des fichiers de mon périmètre mais ne
figurent pas dans les 12 points reçus — je ne les ai pas traitées) :

- **E-I2** — `calibrate()` ne fait pas le contrôle de géométrie que la docstring d'`entraine_les_deux`
  lui délègue explicitement (`n_decisions` et `n_cibles` égaux pour les deux décodeurs). Seul
  `_selftest` le fait ; le chemin de production ne le fait pas. Correctif proposé : 6 lignes,
  `raise ValueError` avant tout calcul.
- **E-I3** — `ecca.save(save_path, n_targets=len(plan))` : après une séance tronquée à 3 cibles, le
  fichier eCCA affirme 6 cibles, `archive/cvep_pilot.py:84-88` le laisse piloter, et le modèle rCCA
  de la même séance dit 3. **L'asymétrie s'est accrue avec mon correctif E-C2** : le rCCA n'est
  désormais plus écrit du tout dans ce cas, l'eCCA l'est en se déclarant complet. À traiter.
- **E-I4** — `_selftest` exerce le vrai `calibrate()` deux fois sans garde `empreinte_dossier`. Les
  chemins sont bien détournés (vérifié : `data/` intact), mais rien dans ce fichier ne le
  *vérifie* — contrairement aux quatre archives.
- **E-I5** — `archive/README.md:15` : la « référence casque » de `cvep_pilot.py` n'est comparable
  qu'aux seuils par DÉFAUT, depuis que le moteur lit `corr_min`/`margin`/`vote_len`/`min_votes` de
  la console à chaque décision. `archive/cvep_pilot.py` n'a donc pas été modifié.
- **E-M2** — `archive/README.md` ne dit pas que `cvep_rcca_pilot.py` importe sept symboles (dont
  quatre privés) du module **vivant** `research/cvep_calibrate.py`.
- **E-M3** — chemin POSIX `/tmp/xyz_cvep_test` en dur dans le selftest, sur un poste Windows.

**Constatations C non assignées** : m1 (justification fausse du ré-export), m2 (`chk` inatteignables
dans `research/cvep_rcca.py`), m4 (assertion d'accord mutable des deux côtés), m5 (docstring de
`_bruit_gagnant_ecart`), m6 (`>=` non apparié vendu comme démonstration), m7
(`python src/research/cvep_rcca.py` listé nulle part).

**Effet de bord à traiter dans un autre lot** — `core/cvep_models.py:176-194` (hors périmètre) :
le message de refus explique qu'à `CVEP_LAG_ROTATION` non nul le désaccord de codes est « le cas
ATTENDU même sans rien avoir changé — la calibration écrit ses codes par lag croissant, le plan les
fait tourner ». **C'est faux depuis le correctif E-C2** : la calibration écrit maintenant dans
l'ordre du plan. Ce paragraphe dit désormais à l'étudiant qu'un vrai défaut est normal. Il faut
l'inverser.

---

## Suites exécutées (toutes vertes, une seule à la fois)

```
EXIT=0  src/research/cvep_calibrate.py              ÉCHEC=0
EXIT=0  src/core/cvep_rcca.py                       ÉCHEC=0
EXIT=0  src/research/cvep_rcca.py                   ÉCHEC=0
EXIT=0  archive/cvep_pilot.py --smoke               ÉCHEC=0
EXIT=0  archive/cvep_rcca_pilot.py --smoke          ÉCHEC=0
EXIT=0  src/research/app.py --smoke                 ÉCHEC=0
EXIT=0  src/core/modes/cvep.py                      ÉCHEC=0
EXIT=0  src/core/server.py --smoke                  ÉCHEC=0
EXIT=0  src/core/cvep_models.py                     ÉCHEC=0
EXIT=0  src/core/cvep_decoder.py                    ÉCHEC=0
EXIT=0  src/console/app.py --smoke                  (non-régression)
EXIT=0  src/core/cvep_code.py                       (non-régression)
```

`server.py --smoke` couvre la frontière `core/` → pas d'import `research/` : le déménagement de
`_mcnemar_p` la respecte, et l'assertion « même objet des deux côtés » vit du côté `research/`.
