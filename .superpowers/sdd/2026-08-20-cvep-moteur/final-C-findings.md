# Revue finale — tranche C (`src/core/cvep_rcca.py`, `src/research/cvep_rcca.py`)

**Décompte : 0 Critical · 6 Important · 8 Minor.**

Aucun programme n'a été exécuté (six relecteurs en parallèle, mêmes noms de flux). Tout ce qui
demande une exécution est marqué « À VÉRIFIER PAR EXÉCUTION ».

---

## VERDICT SUR L'ASSERTION DE CONVENTION DE PHASE (2 bis)

**Elle tient. Une inversion SIMULTANÉE des deux conventions la fait rougir.**

`src/core/cvep_rcca.py:582-591`

```python
accord += int(max(sc_e, key=sc_e.get) == plan[cible]["lag"]
              and int(np.argmax(modele.scores(w, p, 1))) == cible)
```

Les deux membres comparent à la **vérité terrain** (`plan[cible]["lag"]`, `cible`), pas l'un à
l'autre. Ce n'est donc pas un test d'accord, c'est un test de justesse doublé. Démonstration :

Convention établie (vérifiée sur `cvep_code.build_targets`, qui rend `code: np.roll(code, -lag)`,
donc `codes[j][f] = code[(f + lag_j) % L]`) : la fenêtre fabriquée par le test,
`np.roll(synth_cvep(...), -shift(p))`, porte à son échantillon `k` la réponse à la position
`p + lag_vrai + k`.

| | rCCA `scores` | eCCA `_scores_filtered` |
|---|---|---|
| sain | `roll(avg, +shift(p))[k] = avg[k−shift(p)]` → position `k` → cible `lag_vrai` ✓ | `roll(tmpl, −shift(p+lag))[k] = tmpl[k+p+lag]` → coïncide si `lag = lag_vrai` ✓ |
| inversé | → désigne la cible de lag `lag_vrai + 2p` | → désigne la cible de lag `lag_vrai + 2p` |

Les deux inversés désignent **la même cible fausse**. Un test d'accord seul resterait donc vert ;
celui-ci exige la cible **réellement affichée**, et rougit. La seule phase où l'inversion est
invisible est `2p ≡ 0 mod 63`, c'est-à-dire `p = 0` (63 est impair). La boucle parcourt
`range(0, 63, 7)` = 9 phases, dont 8 non nulles, avec une tolérance de `essais − 1 = 8`. Donc au
mieux 1-2 succès accidentels sur 9 → **ÉCHEC**.

**Trois réserves à connaître :**

1. **Le commentaire de l'assertion décrit un test d'accord** (« les DEUX décodeurs désignent la
   même cible »), pas un test de justesse. C'est ce qui la rendrait facile à affaiblir en la
   « simplifiant ». → Important 6 ci-dessous.
2. **La fenêtre est fabriquée par le test** (`np.roll(..., -modele._shift(p))`). Une mutation qui
   inverserait la production *et* cette ligne de fixture resterait verte — mais c'est une mutation
   de test, hors périmètre de l'analyse de mutation.
3. **C'est la SEULE assertion du dépôt qui épingle la convention de phase de l'eCCA.**
   `cvep_decoder._demo` fait le même geste (ligne 357) mais **imprime sans affirmer** (ligne 361) et
   `_demo()` n'est pas branché sur `sys.exit` (ligne 452 : son résultat est jeté). `_selftest`,
   `_loo` et `hors_pli` de `cvep_decoder.py` n'épochent qu'à `phase=0`. Donc la mutation
   `shift(phase + lag)` → `shift(lag − phase)` (invisible à phase 0, fatale en ligne — le jumeau
   exact du bug rCCA corrigé ici) laisse `python src/core/cvep_decoder.py` **entièrement vert** et
   n'est attrapée que par `python src/core/cvep_rcca.py`. Ce couplage mérite d'être écrit là où on
   le lira, c'est-à-dire dans `cvep_decoder.py`.

**Correctif minimal (2 lignes de commentaire, aucune logique) :**

- `core/cvep_rcca.py:589-591` — remplacer le message de `chk` par : *« les DEUX décodeurs désignent
  la cible RÉELLEMENT AFFICHÉE à la même phase. ⚠️ Exiger la JUSTESSE et pas l'ACCORD est
  délibéré : deux conventions inversées ENSEMBLE se mettent d'accord sur la cible de lag
  `lag_vrai + 2p` et un test d'accord resterait vert. Ne pas « simplifier » en comparant les deux
  sorties entre elles. »*
- `core/cvep_decoder.py:212` — ajouter : *« ⚠️ Le signe de ce `-` n'est vérifié par AUCUNE
  assertion de ce fichier (`_loo`/`hors_pli` n'époquent qu'à phase 0, `_demo` imprime sans
  affirmer). Il l'est par `core/cvep_rcca.py::_selftest` §2 bis. »*

---

## IMPORTANT

### I1 — `--seuils` meurt sur un traceback quand la géométrie k=2 ne rend aucun groupe, et les deux jumeaux `hors_pli` produisent DEUX tracebacks différents pour la même cause

*(C'est le tranchant du point escaladé n° 1.)*

`src/core/cvep_rcca.py:450-457` et `:476-486`

`groupes_de_cycles(y, 2)` peut rendre `[]` — c'est mesuré, pas théorique : le commentaire de
`research/cvep_calibrate.py:261-263` rapporte que le protocole `--smoke` d'origine coupait
systématiquement toute paire de cycles consécutifs. `--seuils` accepte n'importe quel chemin tapé
par un étudiant (une archive `cvep_rcca_calib_*.npz`, un fichier de démo, une séance interrompue).

Ce qui se passe alors, ligne par ligne :

- `sc_e, y_e, _ = ecca.hors_pli(...)` rend `(0,)` (`np.asarray([])`), donc ligne 453
  `sc_e.argmax(axis=1)` → **`AxisError: axis 1 is out of bounds for array of dimension 1`** ;
- si l'eCCA était réparé, `sc_r` rend `(0, n_targets)` (pré-allouée), qui **passe** la garde de
  forme ; `loo_r` devient `nan`, et ligne 489 `int(round(loo_r * n_dec))` → **`ValueError: cannot
  convert float NaN to integer`** ;
- et si celle-là était guardée, ligne 484 `pf['corrects_gardes']*100` → **`TypeError: NoneType * int`**
  (`justesse_si_emis` est protégé lignes 479-480, `corrects_gardes` ne l'est pas).

Trois tracebacks différents pour un seul cas : « il n'y a rien à mesurer à cette géométrie ».
`research/cvep_calibrate.py:269` a écrit noir sur blanc que « l'appelant DOIT fermer ce chemin avant
tout calcul, pas le deviner » — `_rejouer` **est** cet appelant, et il ne le ferme pas.

Et `point_de_fonctionnement` sur `(0, n)` rend `emission = nan` (`np.mean` d'un booléen vide), alors
que sa docstring promet « un dict de proportions dans [0, 1] ». La forme *rCCA*, celle qui a l'air la
plus correcte, est celle qui produit le nan silencieux ; la forme *eCCA*, mal formée, lève au moins.

**Tranche demandée : OUI, les deux jumeaux doivent s'aligner** — sur la forme rCCA `(0, n_cibles)`,
parce que la largeur d'une matrice de scores est une propriété du MODÈLE et pas des données, et
qu'elle doit survivre à zéro ligne. Le commentaire de contournement ne suffit pas : il documente la
divergence pour UN appelant (`cvep_calibrate`), alors que le deuxième appelant (`_rejouer`, dans
`core/`) meurt dessus.

**Correctif minimal (3 endroits) :**

1. `core/cvep_decoder.py:195-204` — pré-allouer comme le jumeau :
   ```python
   groupes = groupes_de_cycles(lags, n_cycles)
   scores, y = np.zeros((len(groupes), len(uniq))), np.zeros(len(groupes), dtype=int)
   for j, g in enumerate(groupes):
       ...
       scores[j] = [sc[l] for l in uniq]
       y[j] = uniq.index(lags[g[0]])
   return scores, y, uniq
   ```
   `len(sc) == 0` reste le bon test côté `cvep_calibrate` ; son long ⚠️ (lignes 271-286) se réduit
   alors à une phrase et la trace « à trancher en revue finale » disparaît.
2. `core/cvep_rcca.py:333` (`point_de_fonctionnement`) — première ligne après la garde de forme :
   `if len(y) == 0: return {"corrects_gardes": None, "emission": None, "justesse_si_emis": None,
   "n": 0, "n_corrects": 0}` — jamais un `nan` là où la docstring promet une proportion.
3. `core/cvep_rcca.py:445` (`_rejouer`) — après `n_dec = len(groupes_de_cycles(y, k))` :
   `if n_dec == 0: print(f"[seuils] === k = {k} : AUCUN groupe de {k} cycles consécutifs de la même
   cible dans ce fichier — rien à mesurer à cette géométrie ==="); continue`, et rendre `False` en
   fin de fonction si aucune géométrie n'a rien produit (cf. Minor m3).

**À VÉRIFIER PAR EXÉCUTION** : `python src/core/cvep_rcca.py` — attendu vert (l'alignement de
`CVEPModel.hors_pli` ne change rien aux formes non vides) ; `python src/core/cvep_decoder.py` —
attendu vert ; `python src/research/cvep_calibrate.py` (ou le smoke qui le couvre) — attendu vert.

---

### I2 — `pyntbci` absent : le moteur annonce « modèle illisible », et la console fait disparaître tous les modèles rCCA sans un mot

*(Point escaladé n° 3 : le message d'erreur n'est PAS actionnable.)*

`src/core/cvep_rcca.py:111` — `from pyntbci.classifiers import rCCA`, import nu, aucune garde.
Aucun `except ImportError` nulle part dans `src/` (grep vérifié).

Chaîne réelle quand la dépendance manque :

- `RCCAModel.load` → `fit` → `_fit_clf` → `ModuleNotFoundError` ;
- `cvep_models.charger:176-179` attrape `Exception` et rend
  **`"modèle illisible (ModuleNotFoundError) : cvep_rcca_model.npz"`** — l'étudiant part chercher un
  fichier corrompu là où il manque un `pip install` ;
- `cvep_models.modeles_disponibles:210` filtre sur `charger(c)[0] is not None` → **tout modèle rCCA
  disparaît silencieusement de la liste de la console**, sans aucune raison affichée nulle part.

C'est exactement la panne muette que `cvep_models.py` a été écrit pour éliminer (« un fichier au bon
nom mais au mauvais format apparaîtrait dans le formulaire… le genre de "ça a l'air bon" que ce
produit cherche à supprimer »), retournée : ici c'est un fichier PARFAITEMENT bon qui disparaît.

Sur la borne `pyntbci>=1.9` : elle est cohérente avec la maison (`>=` partout) et le commentaire dit
« mesuré avec la 1.9.0 sur ce poste ». Mais la surface d'API utilisée est étroite et non triviale —
`rCCA(stimulus=, fs=, event="refe", encoding_length=, onset_event=True)` et
`pyntbci.stimulus.make_gold_codes()` — et c'est désormais une dépendance du **moteur**, pas de
`research/`. Un `<2` coûte un caractère et ferme la seule casse silencieuse restante.

**Correctif minimal :**

- `core/cvep_rcca.py:110-115` :
  ```python
  def _fit_clf(self, X, y):
      try:
          from pyntbci.classifiers import rCCA
      except ImportError as e:      # dépendance du MOTEUR : le dire, pas laisser deviner
          raise ImportError(
              "le décodeur c-VEP rCCA exige pyntbci — `pip install -r requirements.txt` "
              "(ou `pip install \"pyntbci>=1.9,<2\"`). L'eCCA, lui, n'en dépend pas.") from e
  ```
- `core/cvep_models.py:178-179` — nommer le cas plutôt que de le noyer dans « illisible » :
  ```python
  except ImportError as e:
      return None, (f"ce modèle rCCA a besoin de pyntbci, qui n'est pas installé "
                    f"(`pip install -r requirements.txt`) — l'eCCA reste utilisable : {nom}")
  except Exception as e: ...
  ```
- `requirements.txt:11` — `pyntbci>=1.9,<2`.

**À VÉRIFIER PAR EXÉCUTION** (dans un venv sans pyntbci) : `python src/core/cvep_models.py` —
attendu : le refus nomme pyntbci, pas « illisible ».

---

### I3 — `_rejouer`, la commande citée comme PROVENANCE du « jeu égal », compare deux pourcentages bruts — la comparaison que le commit `bd3b588` de cette même branche a bannie

`src/core/cvep_rcca.py:452-457`

```python
loo_r = float((sc_r.argmax(axis=1) == y_r).mean())
loo_e = float((sc_e.argmax(axis=1) == y_e).mean())
print(f"[seuils]   leave-one-out   rCCA {loo_r*100:5.1f} % ... eCCA {loo_e*100:5.1f} % ...")
```

Et la docstring vend la commande ainsi (lignes 403-406) :

> 1. **le jeu égal eCCA/rCCA**, l'affirmation qui justifie de réintégrer le rCCA.

Or la branche a justement établi (`bd3b588` « Stop naming a winner on noise: McNemar exact test, not
two raw percentages », et `research/cvep_calibrate.py::_mcnemar_p`) que **deux pourcentages côte à
côte sont le mauvais test sur des décisions appariées**. Deux pourcentages ÉGAUX ne sont pas plus un
test que deux pourcentages différents : à k=1 chacun fait 43/90, mais rien n'établit que ce sont les
43 MÊMES cycles.

Le pire est que les données appariées sont déjà là, à trois lignes : `groupes_de_cycles(y, k)` et
`groupes_de_cycles(lags, k)` parcourent des étiquettes en **bijection** (`y[i] = lag_de_cible.index(lags[i])`),
donc rendent la MÊME liste de tuples dans le MÊME ordre — vérifié. `sc_r[j]` et `sc_e[j]` notent donc
le même groupe de cycles, et `b`/`c` se comptent en deux lignes.

L'obstacle est structurel et il faut le nommer : `_mcnemar_p` vit dans `research/cvep_calibrate.py`,
et **`core/` n'importe jamais `research/`**. C'est un argument pour DÉMÉNAGER `_mcnemar_p` (12
lignes, `math.comb`, zéro dépendance) dans `core/`, exactement selon la règle du dépôt : « si l'envie
s'en présente, c'est que le module visé doit DÉMÉNAGER dans `core` ».

**Correctif minimal :**

1. Déplacer `_mcnemar_p` (et `SEUIL_MCNEMAR`) de `research/cvep_calibrate.py:302-333` vers
   `core/cvep_rcca.py`, et le ré-importer depuis `cvep_calibrate` (le sens autorisé).
2. `core/cvep_rcca.py:457`, après la ligne leave-one-out :
   ```python
   ok_r, ok_e = sc_r.argmax(axis=1) == y_r, sc_e.argmax(axis=1) == y_e
   b, c = int((ok_e & ~ok_r).sum()), int((ok_r & ~ok_e).sum())
   p = _mcnemar_p(b, c)
   print(f"[seuils]   McNemar apparié (MÊMES groupes) : b={b} c={c}, {b+c} décisions "
         f"discordantes sur {n_dec}, p={p:.3f} — "
         + ("aucune différence détectable" if p >= SEUIL_MCNEMAR else "écart défendable"))
   ```
3. `core/cvep_rcca.py:405` — la docstring dit alors « le jeu égal… **testé par McNemar apparié**,
   pas par deux pourcentages côte à côte ».

**À VÉRIFIER PAR EXÉCUTION** : `python src/core/cvep_rcca.py --seuils data/cvep_calib_last.npz` —
attendu à k=2 : `b=3 c=5, 8 discordantes sur 37, p=0.727`, identique à `research/cvep_calibrate.py`.

---

### I4 — « indiscernables » / « fait jeu égal » reposent sur deux totaux égaux à k=1, pas sur le test qui justifie le mot ; et `research/cvep_rcca.py` n'en porte AUCUNE réserve

*(Point escaladé n° 4.)*

Deux endroits, deux problèmes différents.

**(a) `src/core/cvep_rcca.py:15-23`** — la docstring du module ne cite QUE les chiffres à k=1 :

```
      eCCA  leave-one-out 43/90 = 47,8 %
      rCCA  leave-one-out 43/90 = 47,8 %
Les deux décodeurs sont **indiscernables** sur ces données ;
```

Deux frictions :

- **Le mot est porté par une coïncidence de totaux, pas par un test.** McNemar (p = 0,727) n'est pas
  mentionné dans ce fichier — ni le nombre de discordances (8/37). Or c'est LUI qui autorise
  « indiscernables ».
- **La géométrie citée est celle que la branche déclare non représentative.** `config.py:391-395` dit
  explicitement : « Des seuils mesurés à k=1 décriraient un décodeur qui n'existe pas — celui du
  moteur décide sur deux cycles. » Les chiffres à k=2, ceux du moteur, sont 24/37 contre 22/37 —
  pas une égalité. Citer le k=1 parce qu'il tombe juste, quand le fichier lui-même dit que le k=2
  est la bonne géométrie, est un choix de chiffre.

Le garde-fou d'à côté (lignes 21-23, « UNE personne, UNE séance : ça n'établit pas que les deux
décodeurs se valent en général, seulement que rien ne justifie de jeter celui-ci ») est **exactement
la bonne formulation** — absence de preuve de différence, pas preuve d'équivalence. Il n'est pas en
cause ; c'est la phrase qu'il corrige qui est trop courte.

**(b) `src/research/cvep_rcca.py:21-22`** — durcissement franc, et sans aucun garde-fou :

```
Rebranché sur le stimulus décalé, le rCCA fait jeu égal avec
l'eCCA (43/90 chacun, cf. `core/cvep_rcca.py`).
```

« fait jeu égal » est une affirmation d'équivalence positive. Ni « une personne, une séance », ni la
p-value, ni le « rien ne justifie de le jeter » ne sont repris. Un étudiant qui ouvre ce fichier-là
(le fichier de l'hypothèse réfutée, donc celui où il vient chercher ce qu'on sait et ce qu'on ne sait
pas) lit une équivalence établie.

**Correctif minimal :**

- `core/cvep_rcca.py:15-20` — remplacer par :
  ```
      fichier data/cvep_calib_last.npz (2026-07-21, 1 personne, 90 cycles, 6 cibles, stimulus décalé)
        k=1 (géométrie d'une époque)      eCCA 43/90 = 47,8 %   rCCA 43/90 = 47,8 %
        k=2 (géométrie DU MOTEUR)         eCCA 22/37 = 59,5 %   rCCA 24/37 = 64,9 %
        McNemar apparié à k=2 : 8 décisions discordantes sur 37, p = 0,727

  Aucune différence n'est détectable entre les deux décodeurs sur ces données. ⚠️ « Pas de
  différence détectable » n'est PAS « équivalents » : à 37 décisions, McNemar ne verrait qu'un
  écart énorme. C'est une raison de ne pas JETER le rCCA, pas une preuve qu'il vaut l'eCCA.
  ```
  (et l'égalité exacte 43/90 se lit alors pour ce qu'elle est : une coïncidence à la géométrie qui
  n'est pas celle du moteur).
- `research/cvep_rcca.py:21-22` — « …le rCCA n'est pas distinguable de l'eCCA sur la seule séance
  mesurée (k=2 : 24/37 contre 22/37, McNemar p = 0,727 — **une personne, une séance** ; cf.
  `core/cvep_rcca.py`). »
- Même geste, hors périmètre mais à signaler aux tranches concernées : `config.py:369`
  (« Les deux décodeurs sont indiscernables » sur les seuls chiffres k=1), `archive/cvep_rcca_pilot.py:6`
  (« il fait jeu égal »), `research/cvep_calibrate.py:524` (« un jeu parfaitement égal »).

---

### I5 — Les seuils livrés 0,24/0,08 ont été CHOISIS sur les 37 décisions qui mesurent leur point de fonctionnement, et le chiffre est publié comme une mesure

`src/core/cvep_rcca.py:367-399` (`point_de_fonctionnement`), `:476-486` (`_rejouer`),
`src/core/config.py:399-410` (le chiffre publié).

`point_de_fonctionnement` est honnête sur le plan *hors-pli* : les scores viennent d'un modèle qui
n'a pas vu l'essai. Mais le **seuil**, lui, est in-sample : `_rejouer` imprime un tableau de couples
candidats sur ces 37 décisions, un humain lit la ligne la plus flatteuse, et le chiffre de cette
ligne devient le « point de fonctionnement mesuré » de `config.py:399-402` (69 % de justesse,
35 % d'émission). C'est une valeur **sélectionnée sur l'échantillon qui la mesure** — un optimisme
de sélection, de la même famille que le « chiffre gonflé » de la calibration MI que ce fichier cite
lui-même ligne 86-87 pour un autre motif.

L'ampleur est mesurable dans le texte de `config.py` : le départage se joue sur 13 décisions émises
contre 11, soit **2 décisions sur 37** — exactement l'écart que le même paragraphe déclare
« pas interprétable » deux lignes plus bas quand il s'agit de la justesse. Le même étalon n'est pas
appliqué aux deux chiffres.

Rien dans mes deux fichiers ne le dit. Les réserves présentes (« UNE personne, UNE séance », ligne
441-442 de `_rejouer`) portent sur la **généralisation** et sur le **petit n**, pas sur la
**sélection**. Ce sont trois faiblesses distinctes et seules deux sont écrites.

**Correctif minimal (aucune logique, deux ⚠️) :**

- `core/cvep_rcca.py:342` (docstring de `point_de_fonctionnement`), après « Ne choisit rien,
  décrit. » :
  > ⚠️ **Décrit — mais si vous CHOISISSEZ un couple en lisant ce tableau, le chiffre de la ligne
  > retenue n'est plus une mesure : il est optimiste, parce qu'il a été sélectionné sur les mêmes
  > décisions qui le produisent. C'est le cas des 0,24/0,08 livrés (`core/config.py`). Le seul
  > chiffre non biaisé serait mesuré sur une SECONDE séance, qui n'existe pas.**
- `core/cvep_rcca.py:441-442` — ajouter à la ligne imprimée par `--seuils` : `« …et le couple que
  vous retiendrez en lisant ce tableau aura un point de fonctionnement OPTIMISTE : il est choisi
  sur ces décisions-là. »`
- `core/config.py:404-410` (autre tranche) — trancher la contradiction : le paragraphe annonce que
  « ce qui tranche ici est le taux de bruit », puis retient le couple dont le taux de bruit est le
  **pire** (10 % contre 7 %), sur un argument d'émission qui vaut 2 décisions sur 37. Soit le
  départage est le bruit et c'est 0,26/0,09, soit il est l'émission et il faut écrire que 2
  décisions ne tranchent rien et que le choix est un pari assumé.

---

### I6 — Le commentaire de 2 bis décrit un test d'ACCORD ; c'est un test de JUSTESSE, et c'est ce qui le rend robuste

`src/core/cvep_rcca.py:572-576` et `:589-591`

Le commentaire dit « deux conventions opposées se seraient annulées dans n'importe quel test écrit
pour le seul rCCA » (vrai, et bien vu), puis le message d'assertion dit « les DEUX décodeurs
**désignent la même cible** sur la même fenêtre à la même phase ». Un lecteur qui prend le message
au mot et « simplifie » en

```python
accord += int(plan[int(np.argmax(modele.scores(w, p, 1)))]["lag"] == max(sc_e, key=sc_e.get))
```

obtient un test d'accord pur — qui reste **vert** sous une inversion simultanée (les deux inversés
désignent la cible de lag `lag_vrai + 2p`, cf. le verdict en tête). C'est la seule voie par laquelle
le garde central de cette tranche peut être détruit sans que rien ne le signale.

Correctif : le commentaire proposé dans le verdict en tête (2 lignes, aucune logique).

---

## MINOR

**m1 — `research/cvep_rcca.py:41-43` : la justification du ré-export est fausse.**
« Ré-exporté ici pour que `archive/cvep_rcca_pilot.py` continue de tourner **sans dépendre
directement de `core/`** » — or `archive/cvep_rcca_pilot.py:32` fait déjà
`from core.config import (...)`, deux lignes avant l'import de `research.cvep_rcca`. Le ré-export
est bon (compatibilité de l'archive), sa raison ne l'est pas. → Écrire la vraie : « pour ne pas
casser l'import de l'archive au déménagement ».

**m2 — `research/cvep_rcca.py:122` et `:170` : les gardes `cv_ is not None` des `chk` sont
inatteignables.** `print(f"… LOO {model.cv_*100:5.1f}%")` (122) et `back.cv_*100` (170) déréférencent
AVANT le `chk` qui teste `is not None` (124, 172). Si `cv_` valait `None`, le fichier mourrait sur un
`TypeError` — un traceback au lieu d'un ÉCHEC nommé, précisément ce que la docstring de
`core/cvep_rcca.py:839-842` dit avoir corrigé ailleurs. → Déplacer le `chk` avant le `print`, ou
formater via `'—' if model.cv_ is None else f'{model.cv_*100:.1f}'`.

**m3 — `core/cvep_rcca.py:487` et `:867` : `_rejouer` rend `True` EN DUR.** `sys.exit(0 if
_rejouer(...) else 1)` a donc une branche morte — le défaut exact que la tâche 3 vient de corriger
dans le jumeau `research/cvep_rcca.py::_demo`, survivant dans le fichier `core/`. Ce n'est pas un
autotest, mais « aucune décision à cette géométrie » (cf. I1) est un échec qui mérite un 1. → Rendre
`False` si aucune géométrie n'a produit de décision, et le documenter dans la docstring.

**m4 — `core/cvep_rcca.py:790` : assertion d'accord, mutable des deux côtés.**
`chk((dec_strict.classify(...)[0] is not None) == (pf_reel["emission"] == 1.0))` : passer `>=` à `>`
dans `RCCADecoder.classify:281` **et** dans `point_de_fonctionnement:358` rend les deux membres
`False`, et `False == False` reste vert. Impact production faible (égalité exacte de flottants), mais
c'est structurellement le même piège qu'en 2 bis. → Affirmer les deux séparément :
`chk(dec_strict.classify(fenetre, 0)[0] is not None and pf_reel["emission"] == 1.0, …)`.

**m5 — `core/cvep_rcca.py:376-379` : la docstring de `_bruit_gagnant_ecart` sur-décrit son bruit.**
(a) Le bruit est engendré à `sigma` **brut** puis re-filtré par `scores`, donc ce qui arrive au
décodeur n'a PAS « le même écart-type que les époques filtrées » (bruit blanc filtré [2-45] Hz sur
125 Hz ≈ 0,6·σ). Sans conséquence — les deux `decision_function` rendent des corrélations, donc
invariantes en amplitude — mais alors il faut le dire ainsi. (b) La convention citée
(« celle que `cvep_decoder._demo` utilise déjà ») ne correspond pas : `cvep_decoder.py:344` tire
`rng.normal(0, 1, …)`, σ = 1 en dur, sans lien avec les époques. → Corriger les deux phrases, ou
filtrer le bruit une seule fois.

**m6 — `core/cvep_rcca.py:723-725` : un `>=` non apparié vendu comme une démonstration.**
« moyenner deux cycles ne DÉGRADE pas la justesse (…) — c'est tout l'intérêt du repli » compare deux
justesses issues d'échantillons de tailles différentes (48 groupes contre ~24), chevauchants, sur UNE
exécution à graine fixe, sans test. Comme garde de non-régression c'est acceptable ; le message, lui,
conclut. Et sur ces données de synthèse à −6 dB la justesse est très probablement saturée à 1,00 des
deux côtés, ce qui rend l'assertion quasi vide. → Message : « garde de non-régression : le repli à
k=2 ne fait pas CHUTER la justesse sur ce jeu de synthèse (graine fixe). Ce n'est pas une mesure du
gain du repli — pour ça, `--seuils` sur une séance réelle. »
**À VÉRIFIER PAR EXÉCUTION** : `python src/core/cvep_rcca.py` — relever les deux chiffres imprimés
par cette ligne ; s'ils valent 1,00 et 1,00, l'assertion est effectivement vide.

**m7 — `python src/research/cvep_rcca.py` n'est listé dans AUCUNE liste de commandes.**
`CLAUDE.md:145` et `README.md:377` listent `python src/core/cvep_rcca.py` ; le jumeau `research/`
n'apparaît que dans sa propre docstring (ligne 31). Le correctif de la tâche 3 (le fichier peut
enfin sortir en 1) n'est donc exercé par rien de documenté. → L'ajouter au bloc « Après toute
modification » de `CLAUDE.md`, ou le brancher dans `python src/research/app.py --smoke`.

**m8 — `core/cvep_rcca.py:425-429` : `--seuils` sur un fichier aux lags périmés meurt sur
`ValueError: 21 is not in list`.** `lag_de_cible.index(l)` lève dès que le fichier a été calibré avec
un autre `CVEP_LAG_ROTATION` / `CVEP_N_TARGETS` / `CVEP_BITS` — le cas que `cvep_models.charger`
prend soin de NOMMER (`:162-174`, en distinguant même les deux désaccords). Idem `d["lags"]` →
`KeyError` sur un `.npz` qui n'est pas une calibration. → Un `try/except` qui renvoie le même message
que `charger` : « ce fichier a été enregistré sur d'AUTRES cibles que celles affichées aujourd'hui ».

---

## Ce qui a été vérifié et tient (pour ne pas le re-vérifier)

- **`_hors_pli` est un VRAI leave-group-out** : `tr = [i for i in range(len(X)) if i not in dehors]`,
  ré-ajustement complet par groupe, notation du groupe moyenné exclu. Le test de fuite (bruit pur,
  ligne 733-742) est un jumeau exact de celui de `cvep_decoder`, et il peut rougir.
- **`_loo` et `hors_pli(k=1)` sortent de la MÊME boucle** — assertion `np.allclose(sc1,
  modele.oof_scores_)` ligne 720, donc les deux chiffres ne peuvent pas diverger. Vérifié.
- **Le défaut `n_cycles` est épinglé par `inspect.signature` contre celui de `CVEPDecoder`** (ligne
  637-641) : une asymétrie de défaut rougit, ce qu'aucun test passant ses paramètres ne verrait.
- **La géométrie de `_rejouer` est commune aux deux décodeurs** : `groupes_de_cycles(y, k)` et
  `groupes_de_cycles(lags, k)` opèrent sur des étiquettes en bijection, donc rendent la même liste
  de groupes dans le même ordre. La comparaison est bien appariée (ce qui est ce qui rend I3
  réparable en 3 lignes).
- **`load` sans `allow_pickle`**, `save` sans nom de classe, assertion `"RCCAModel" not in …` :
  le format survit à un déménagement. Vérifié.
- **Frontière `core/` ↔ `research/`** : `core/cvep_rcca.py` n'importe que `core.*` + numpy + pyntbci.
  `research/cvep_rcca.py` importe `core.*` (sens autorisé). Aucune violation.
- **Aucun test n'écrit dans le vrai `data/`** : `tempfile.mkdtemp` + `finally` dans les deux
  `_selftest`/`_demo`, et `_rejouer` est en lecture seule. Vérifié par lecture.
