# Tranche B — revue finale, constats

Périmètre : `src/core/cvep_decoder.py`, `src/core/cvep_code.py`, `src/core/cvep_models.py`,
`src/core/config.py`. Jumeaux comparés : `p300_models.py`, `errp_models.py`, `mi_models.py`.
Trois points escaladés traités (n° 1 en tête de la section « Point transverse », n° 2 = I5,
n° 3 = M1 + M2).

**Aucun programme n'a été exécuté** (six relecteurs en parallèle, mêmes noms de flux LSL). Les
quelques vérifications qui exigeraient une exécution sont écrites « À VÉRIFIER PAR EXÉCUTION ».

Décompte : **1 Critical, 5 Important, 6 Minor.**

---

## Ce qui est bon, et qui ne doit pas être défait par mégarde

Pour que la liste ci-dessous ne donne pas une fausse impression : le chemin de refus de
`cvep_models.charger` est solide, et il l'est par construction, pas par chance.

- L'ordre des contrôles est le bon : chemin vide → introuvable → `np.load` (illisible) → décodeur
  déclaré inconnu → clés manquantes → **stimulus** → `classe.load`. Le contrôle de stimulus se pose
  bien AVANT `RCCAModel.load` (`cvep_models.py:151-174`), ce qui évite un ré-ajustement pyntbci pour
  un fichier qu'on refuse.
- `modeles_disponibles` (`:204-210`) filtre par `charger(c)[0] is not None` sans court-circuit :
  **si le plus récent est illisible, l'ancien valide sort quand même, et en tête** — le cas que la
  méthode de revue demandait de vérifier. Le tri est protégé dans les deux sens (section 5 du
  `_selftest`, `:474-482` : le renommage `_z`/`_herite` fait DIVERGER tri alphabétique et
  chronologique, donc retirer `key=getmtime` OU `reverse=True` rougit).
- Les deux motifs de `MOTIFS` sont chacun protégés : supprimer l'un fait disparaître une entrée de
  la liste attendue `:479-480`. L'élargissement `("*.npz",)` est rougi par la section 6 (`:492-499`).
- Le refus de stimulus attrape le cas SOURNOIS — mêmes codes, autre ORDRE (`:367-373`) — donc
  écrire la comparaison en `set(...)`/`sorted(...)` rougit. C'est le bon test.
- `cvep_decoder._selftest` (`:378-...`) mesure vraiment ce qu'il annonce : hors-pli sur BRUIT PUR,
  16,7 % contre 91,7 % si l'exclusion saute. C'est le test qui protège tout le reste du fichier.
- `charger` refuse `None`, `""` et `0` (`:108-114` + `_selftest:389-392`), et `decrire` aussi
  (`:226-233`) — durcissement repris à l'identique d'`errp_models`/`p300_models`.

---

## CRITICAL

### C1 — `empreinte_dossier` garde la contrainte la plus grave du dépôt, et AUCUN test ne le fait rougir

**Fichier :** `src/core/config.py:84-116` (fonction) ; `src/core/config.py:830-944` (`_selftest`, qui
ne le couvre pas).

**Le constat.** `empreinte_dossier` est le seul garde-fou automatique contre l'écriture dans le vrai
`data/` — la contrainte que ce chantier qualifie de plus grave (EEG identifiable, dépôt public, et
**deux modèles réellement écrasés pendant ce chantier**). Il est appelé par cinq programmes :
`archive/cvep_pilot.py:129,175`, `archive/cvep_rcca_pilot.py:259,355`, `archive/mi_calibrate.py:401`,
`archive/mi_pilot.py:224`, `src/research/app.py:1306,1338,1514`. Les cinq font la même chose :
comparer l'empreinte avant et après.

**Personne ne vérifie qu'il DÉTECTE quoi que ce soit.** Aucune assertion, nulle part dans le dépôt,
ne lui présente un dossier modifié pour exiger qu'il le voie. `config._selftest` (`:830-944`) ne
traite que la proposition de fréquences alpha, et — vérifié — il n'est chaîné dans aucun des trois
smokes documentés (`server.py:1447-1462` liste ses quinze `_smoke_*`, `config` n'y est pas ;
`CLAUDE.md` ne liste pas `python src/core/config.py` non plus).

**Mutations qui laissent TOUT vert :**

| Mutation d'une ligne de production | Effet | Ce qui rougit |
|---|---|---|
| `return {}` en tête de la fonction | le garde ne voit plus rien | **rien** — `{} == {}` chez les 5 appelants |
| `(getsize(...),)` au lieu de `(getsize(...), getmtime(...))` | un fichier ÉCRASÉ à taille égale passe | **rien** |
| `(getmtime(...),)` au lieu du couple | un fichier réécrit à la même seconde passe | **rien** |
| `sorted(_os.listdir(dossier))[:1]` | un seul fichier surveillé sur 43 | **rien** |
| `if not _os.path.isdir(dossier): return {}` → `raise` | un dépôt cloné plante | **rien** (aucun test sur dossier absent) |

C'est exactement le reproche que ce dépôt s'applique ailleurs, mot pour mot :
`errp_models.py:307-311` — « aucune mutation d'une ligne de `modeles_disponibles` ne les rougissait :
MOTIF faux, tri supprimé, filtre inversé, filtre supprimé, tous verts ».

**Aggravant.** La docstring fait trente lignes et promet beaucoup (`:85-110`), y compris une limite
soigneusement mesurée. Un lecteur en déduit que la fonction a été éprouvée. Elle ne l'a pas été. Une
docstring longue sur un code non testé rend le garde **plus** crédible qu'il ne l'est — c'est pire
que pas de docstring.

**Correctif minimal** (~12 lignes, dans `config._selftest`, plus une ligne pour le chaîner). Une
assertion PAR COMPOSANTE, sinon chaque mutation du tableau ci-dessus survit :

```python
    # `empreinte_dossier` est le garde de `data/`. Une assertion par composante du tuple :
    # avec une seule assertion « ça change quand j'ajoute un fichier », retirer `mtime` du
    # couple resterait vert, et un fichier RÉÉCRIT à taille égale ne serait plus vu.
    import tempfile as _tf, shutil as _sh
    d = _tf.mkdtemp(prefix="empreinte_")
    try:
        chk(empreinte_dossier(_os.path.join(d, "absent")) == {},
            "un dossier absent rend {} et ne lève pas — un dépôt cloné n'a pas de data/")
        vide = empreinte_dossier(d)
        f = _os.path.join(d, "x.npz")
        with open(f, "wb") as fh: fh.write(b"aa")
        cree = empreinte_dossier(d)
        chk(cree != vide, "un fichier CRÉÉ change l'empreinte")
        with open(f, "wb") as fh: fh.write(b"aaaa")
        chk(empreinte_dossier(d) != cree, "un fichier GROSSI aussi — la TAILLE est dans le couple")
        grossi = empreinte_dossier(d)
        _os.utime(f, (1_600_000_000, 1_600_000_000))
        chk(empreinte_dossier(d) != grossi,
            "un fichier RÉÉCRIT à taille égale aussi — le MTIME est dans le couple")
        with open(_os.path.join(d, "y.npz"), "wb") as fh: fh.write(b"b")
        chk(len(empreinte_dossier(d)) == 2, "tous les fichiers sont listés, pas seulement le premier")
    finally:
        _sh.rmtree(d, ignore_errors=True)
```

Puis, pour qu'il tourne : soit ajouter `python src/core/config.py` à la liste de `CLAUDE.md`, soit —
mieux, parce que c'est ce que tout le monde lance — appeler `config._selftest()` depuis
`server.py::_smoke` (`:1447`). Je recommande le second : un garde qui ne tourne que sur commande
explicite est un garde qui ne tourne pas.

À VÉRIFIER PAR EXÉCUTION après correctif : `python src/core/config.py` — attendu VERDICT OK, exit 0 ;
puis avec `return {}` injecté dans `empreinte_dossier` — attendu ≥ 4 ÉCHEC et exit 1.

---

## IMPORTANT

### I5 — `config.py:400` : le chiffre qui JUSTIFIE les seuils livrés est le seul du bloc sans réserve, et c'est le plus fragile

**Fichier :** `src/core/config.py:399-410`.

Le bloc « POINT DE FONCTIONNEMENT DES VALEURS LIVRÉES » ouvre sur :

```
#     69 % de justesse quand le décodeur émet   (contre 64,9 % sans aucun seuil)
```

Sept lignes plus bas, une réserve explicite protège une AUTRE comparaison :

```
# ⚠️ En revanche, l'écart de JUSTESSE entre les deux (69 % contre 64 %)
# porte sur **2 décisions sur 37** : il n'est pas interprétable [...]
```

**La réserve garde le mauvais couple.** Elle porte sur 0,24/0,08 contre 0,26/0,09 (deux couples de
seuils). Le chiffre de la ligne 400 — « 69 % **contre 64,9 % sans aucun seuil** » — n'en a aucune,
et c'est pourtant LUI qui dit « le seuil sert à quelque chose », donc lui que l'étudiant retiendra.

Or il est au moins aussi fragile, et sans doute davantage. En reprenant les effectifs donnés juste
au-dessus (`:396` « 37 décisions, 24 correctes » ; `:401` « 13 décisions sur 37 ») :

- sans seuil : 24/37 = 64,9 %
- avec seuil : 69 % de 13 émissions ≈ **9/13**

Soit 4,1 points d'écart adossés à **13 décisions**, contre 37 pour la comparaison qui, elle, est
déclarée non interprétable. Le lecteur en déduit, par contraste, que la première est solide. Elle ne
l'est pas — un test exact sur 9/13 contre 24/37 n'a aucune chance d'approcher un seuil de
significativité, et les deux échantillons ne sont même pas indépendants (le second contient le
premier).

Ça heurte directement la règle du projet (« ne jamais conclure sur du bruit », `CLAUDE.md`), et
d'autant plus que tout le reste de ce bloc est exemplaire de rigueur.

**Ce que ça ne remet pas en cause :** le CHOIX de 0,24/0,08 reste bien fondé — il repose sur le taux
de bruit (10 %, estimé sur 300 fenêtres, `:410`) et sur le taux d'émission (35 % contre 30 %), pas
sur la justesse. C'est écrit, et c'est juste. Seule la présentation de la ligne 400 induit en erreur.

**Correctif minimal** (2 lignes, `:400`) :

```
#     69 % de justesse quand le décodeur émet   (9 décisions justes sur 13 émises)
#     ⚠️ à comparer à 64,9 % sans aucun seuil (24 sur 37) : 4 points sur 13 décisions,
#        PAS interprétable non plus. Ce qui justifie ces seuils est le taux de bruit, plus bas.
```

### I1 — Le chemin de chargement eCCA n'a QU'UNE couche anti-pickle, et elle n'est couverte par aucun test

**Fichiers :** `src/core/cvep_decoder.py:259` (`CVEPModel.load`) ; `src/core/cvep_models.py:406-435`
(le test qui affirme le contraire).

Le commentaire de `cvep_models.py:411-418` annonce, analyse de mutation à l'appui :

> « Il y a deux `np.load` sur ce chemin — celui de `charger` et celui de `RCCAModel.load` — et
> remettre `allow_pickle=True` sur UN SEUL laisse le test vert [...] C'est de la défense en
> profondeur, pas un trou : remettre le drapeau sur les DEUX rougit 3 assertions. »

**C'est exact pour le rCCA, et faux pour l'eCCA.** La fixture `pickle_piege` (`:419-425`) vise la clé
`codes` — « parce que c'est la seule que `charger` lit elle-même » (`:417-418`). Mais un modèle eCCA
**n'a pas de clé `codes`**. Sur le chemin eCCA, `charger` ne lit donc qu'`un seul` champ du fichier :
`decoder` (`cvep_models.py:131`), une chaîne, qu'un `.npz` piégé garderait évidemment en chaîne pour
franchir le contrôle. La première couche est traversée **par construction**, pas par accident.

Conséquence : `CVEPModel.load` est la seule et unique couche, et **aucune fixture eCCA à tableau
d'objets n'existe** dans le dépôt.

**Mutation qui reste verte partout :** ajouter `allow_pickle=True` à `cvep_decoder.py:259`. Vérifié
par lecture : aucune assertion de `cvep_models._selftest`, `cvep_decoder._selftest`,
`modes/cvep.py::_selftest`, ni des trois smokes, ne présente un `.npz` eCCA à dtype objet.

**Scénario concret.** `data/cvep_model_dupote.npz` — reçu d'un camarade, ou produit par un script
tiers — porte `w` en `dtype=object` et **pas** de champ `decoder` (donc « eCCA hérité », le chemin le
plus permissif). `modeles_disponibles` ouvre tout ce qui traîne dans `data/` (`:204-210`) :
`charger` lit `decoder` (absent → eCCA), vérifie les clés (toutes présentes), saute le contrôle de
stimulus (réservé au rCCA, `:154`), puis appelle `CVEPModel.load`. Si le drapeau est revenu, le
pickle s'exécute — **à l'ouverture du catalogue de la console**, avant tout choix de l'étudiant.

**Correctif minimal** (~9 lignes dans `cvep_models._selftest`, juste après le bloc `pickle_piege`) :

```python
        # Le jumeau eCCA du piège ci-dessus, et il n'est PAS redondant : sur un fichier eCCA,
        # `charger` ne lit qu'UN champ du fichier (`decoder`, une chaîne), donc sa propre
        # `np.load` ne peut PAS voir le piège — la seule couche est `CVEPModel.load`. Sans
        # cette fixture, y remettre `allow_pickle=True` ne rougit RIEN dans tout le dépôt.
        piege_ecca = _os.path.join(dossier, "cvep_model_pickle.npz")
        me = _ecca()
        _np.savez(piege_ecca, w=_np.asarray([me.w], dtype=object), template=me.template,
                  fs=me.fs, refresh=me.refresh, code_len=me.code_len,
                  band=_np.asarray(me.band), n_targets=6,
                  channels=_np.asarray(me.channels, dtype=int), cv=me.cv_)
        _m, raison = charger(piege_ecca)
        chk(_m is None and "illisible" in (raison or "")
            and "cvep_model_pickle.npz" in (raison or ""),
            f"un .npz eCCA qui contient du PICKLE est refusé, pas dépickle ({raison})")
        chk(piege_ecca not in modeles_disponibles(dossier),
            "...et il n'apparaît donc pas dans la liste proposée à l'étudiant")
```

Et corriger la phrase `:411-418`, qui décrit aujourd'hui une profondeur que seul le rCCA possède.

À VÉRIFIER PAR EXÉCUTION : `python src/core/cvep_models.py` — attendu VERDICT OK ; puis avec
`allow_pickle=True` sur `cvep_decoder.py:259` seul — attendu 2 ÉCHEC, exit 1.

### I2 — `n_targets` est enregistré « pour pouvoir prévenir », et rien ne prévient jamais

**Fichiers :** `src/core/cvep_decoder.py:130` et `:242-245` (la promesse) ;
`src/core/cvep_models.py:245-249` et `:221-223` (le seul consommateur, sans appelant) ;
`src/core/modes/cvep.py:254-272` (l'endroit où le contrôle devrait vivre).

`CVEPModel.save` écrit, en toutes lettres :

> « Le template est commun à tous les lags, donc un modèle à 3 cibles « marche » techniquement à 6 —
> mais les lags supplémentaires n'auront jamais été validés. **On le mémorise pour pouvoir
> prévenir.** »

Le champ est bien écrit (`:248`) et bien relu (`:265`). Il ressort par `cvep_models.decrire`
(`:247-249`) — dont la docstring reconnaît elle-même n'avoir **aucun appelant en production**
(`:221-223`, vérifié : `grep -n '\bdecrire\b' src/` ne trouve que les `_selftest` et l'appel MI de
`modes/mi_calib.py:356`). Et ni `charger`, ni `CVEPRuntime.__init__` (`modes/cvep.py:179-222`), ni
`_desaccord_code` (`:254-272`) ne comparent `model.n_targets` à `len(self.plan)`.

**Personne ne prévient. La promesse n'est tenue nulle part.**

**Scénario concret.** Le fichier de config documente lui-même des allers-retours 4 → 6 → 8 → 6
(`config.py:444-508`) : ce n'est pas une hypothèse d'école. Un étudiant calibre à 3 cibles pour aller
vite, remet `CVEP_N_TARGETS = 6`, lance `--mode cvep`. Le moteur accepte le modèle sans un mot ;
`CVEPDecoder` note six lags (`cvep_decoder.py:276`) dont trois n'ont jamais été validés ; le vote
glissant et la confiance publiée ont l'apparence normale. C'est la « panne INVISIBLE » que
`config.py:419-423` dit vouloir éliminer.

**Correctif minimal** (4 lignes dans `_desaccord_code`, ou une branche sœur — un AVERTISSEMENT et
non un refus, conformément à ce que dit `save`) :

```python
        # `n_targets` vaut 0 pour un modèle antérieur au champ : on ne peut alors rien dire.
        if self.model.n_targets and self.model.n_targets != len(self.plan):
            return (f"ce modèle a été calibré sur {self.model.n_targets} cibles, l'écran en "
                    f"affiche {len(self.plan)} (CVEP_N_TARGETS) : le template marche pour tous "
                    f"les lags, mais les cibles supplémentaires n'ont JAMAIS été validées — "
                    f"recalibre, ou remets CVEP_N_TARGETS à {self.model.n_targets}.")
```

À défaut, retirer la phrase « on le mémorise pour pouvoir prévenir » : un champ qu'on garde sans
jamais le lire est un mensonge à retardement.

### I3 — Le refus de stimulus ne couvre pas `CVEP_TAPS` côté eCCA, et `cvep_models` laisse croire le contraire

**Fichiers :** `src/core/cvep_models.py:30-33` (le renvoi) ; `src/core/modes/cvep.py:267` (le contrôle
réel) ; `src/core/cvep_decoder.py:247-254` (la cause racine).

La divergence n° 2 de la docstring renvoie le contrôle eCCA à `_desaccord_code`, « un modèle eCCA ne
porte pas de codes, seulement un `code_len` ». Vrai — et c'est justement le problème :
`_desaccord_code` ne compare QUE `code_len` (`modes/cvep.py:267`).

**Passer `CVEP_TAPS = (6, 5)` à `(6, 1)`** — l'autre polynôme primitif de degré 6, et **exactement
celui que `cvep_models._selftest:348` utilise pour fabriquer ses « codes étrangers »** — laisse
`code_len = 63` inchangé. `_desaccord_code` rend `None`, le modèle eCCA est accepté, et son template
est corrélé à une m-séquence que plus aucun écran n'affiche. Scores d'apparence normale, décodage
sans rapport. C'est **mot pour mot** la panne que le refus de stimulus rCCA existe pour empêcher
(`cvep_models.py:23-29`) — sauf qu'ici elle passe.

**Cause racine :** `CVEPModel.save` (`cvep_decoder.py:247-254`) n'enregistre pas les taps.
`RCCAModel`, lui, porte ses codes, donc `charger` peut comparer. L'asymétrie n'est pas un choix de
conception documenté : c'est un champ qui manque.

**Correctif minimal** (1 ligne dans `save`, 1 dans `load`, 4 dans `_desaccord_code`) :

```python
# cvep_decoder.py, dans save(), à côté de code_len :
                 taps=np.asarray(CVEP_TAPS, dtype=int),
# dans load() :
        m.taps = tuple(int(t) for t in d["taps"]) if "taps" in d else None   # None = hérité
# modes/cvep.py, dans _desaccord_code() :
        if self.model.taps is not None and tuple(self.model.taps) != tuple(CVEP_TAPS):
            return (f"ce modèle a été calibré avec CVEP_TAPS={tuple(self.model.taps)}, la config "
                    f"actuelle affiche {tuple(CVEP_TAPS)} : même longueur de code, mais PAS le "
                    f"même code — recalibre, ou restaure CVEP_TAPS.")
```

**Réserve honnête, à écrire dans le commentaire :** `data/cvep_model.npz` est antérieur au champ,
donc il restera `taps=None` et non contrôlable — comme `n_targets=0`. Le contrôle ne mordra que sur
les modèles produits à partir de maintenant. C'est mieux que rien, et il faut le dire plutôt que
laisser croire à une couverture complète.

### I4 — `--seuils` sans argument retombe en silence sur l'autotest et sort en 0 *(point escaladé n° 2)*

**Fichier :** `src/core/cvep_rcca.py:832-834` *(hors de mes quatre fichiers, mais escaladé — et la
constante qu'il justifie est dans les miens)*.

```python
    if len(sys.argv) > 2 and sys.argv[1] == "--seuils":
        sys.exit(0 if _rejouer(sys.argv[2]) else 1)
    sys.exit(0 if _selftest() else 1)
```

Trois invocations plausibles tombent toutes sur `_selftest()` et **sortent en 0** :

| Commande tapée | Ce qui se passe | Sortie |
|---|---|---|
| `python src/core/cvep_rcca.py --seuils` (fichier oublié) | autotest synthétique | **0** |
| `python src/core/cvep_rcca.py --seuil data/cvep_calib_last.npz` (faute de frappe) | autotest | **0** |
| `python src/core/cvep_rcca.py data/cvep_calib_last.npz` (drapeau oublié) | autotest | **0** |

**Pourquoi ce n'est pas cosmétique.** `config.py:374-378` désigne cette commande comme **LA
provenance** des seuils livrés — « un seuil sans provenance est un seuil que personne n'osera
changer », et « la commande est versionnée [...] Ici, la commande est la trace »
(`cvep_rcca.py:411-414`). Une commande de provenance qui fait silencieusement autre chose **en
annonçant un succès** annule le bénéfice qu'on est allé chercher. Et le sort de l'ErrP, cité juste
au-dessus (seuils posés par un script jetable non versionné), est le contre-exemple qui motive tout
ce dispositif.

**Correctif minimal** (7 lignes) :

```python
    if sys.argv[1:2] == ["--seuils"]:
        if len(sys.argv) < 3:
            print("usage : python src/core/cvep_rcca.py --seuils <data/cvep_calib_*.npz>")
            sys.exit(2)
        sys.exit(0 if _rejouer(sys.argv[2]) else 1)
    if len(sys.argv) > 1:
        print(f"argument inconnu {sys.argv[1]!r} — sans argument : autotest ; "
              f"« --seuils <fichier> » : mesure des seuils sur une calibration.")
        sys.exit(2)
    sys.exit(0 if _selftest() else 1)
```

(`2` et non `1` : distinguer « mal appelé » de « autotest en échec » — sinon un script d'intégration
ne peut pas faire la différence.)

---

## MINOR

### M1 — `_rejouer` lève des exceptions nues sur trois entrées plausibles *(point escaladé n° 3, 1re moitié)*

**Fichier :** `src/core/cvep_rcca.py:421-429`.

| Entrée | Ligne | Ce que l'utilisateur lit |
|---|---|---|
| chemin fauté / fichier absent | `:421` `np.load(chemin)` | `FileNotFoundError` nu |
| un `.npz` qui n'est pas une calibration (typiquement `data/cvep_model.npz`, le voisin de nom le plus probable) | `:426-428` `d["lags"]`, `d["channels"]`, `d["epochs"]` | `KeyError: 'lags'` nu |
| une calibration faite sous d'autres `CVEP_BITS`/`CVEP_N_TARGETS`/`CVEP_LAG_ROTATION` | `:429` `lag_de_cible.index(l)` | `ValueError: 21 is not in list` |

Le troisième est le plus fâcheux : c'est **le désaccord de configuration**, celui que
`cvep_models.charger:157-175` sait justement dire en une phrase utile pour le rCCA (« la config a
changé depuis la calibration (CVEP_BITS, CVEP_TAPS, CVEP_N_TARGETS) »). Ici, le même diagnostic sort
en traceback numpy.

Sévérité **Minor** assumée : `_rejouer` est une commande de mesure, tapée par quelqu'un qui sait ce
qu'il fait, pas un chemin étudiant. Mais la réparation est mécanique.

**Correctif minimal** (~8 lignes en tête de `_rejouer`, réutilisant le vocabulaire de `charger`) :

```python
    if not _os.path.isfile(chemin):
        raise SystemExit(f"fichier introuvable : {chemin}")
    d = np.load(chemin)
    manque = [c for c in ("epochs", "lags", "channels", "fs", "refresh") if c not in d.files]
    if manque:
        raise SystemExit(f"ce n'est pas une calibration c-VEP (il manque {', '.join(manque)}) : "
                         f"{_os.path.basename(chemin)} — attendu un data/cvep_calib_*.npz")
    inconnus = sorted({int(l) for l in d["lags"]} - set(lag_de_cible))
    if inconnus:
        raise SystemExit(f"cette calibration porte des lags {inconnus} que le stimulus actuel "
                         f"n'affiche pas ({sorted(lag_de_cible)}) : la config a changé depuis "
                         f"(CVEP_BITS, CVEP_TAPS, CVEP_N_TARGETS, CVEP_LAG_ROTATION).")
```

### M2 — La liste « Trois divergences ASSUMÉES » n'est pas exhaustive, alors qu'elle promet de l'être *(point escaladé n° 3, 2e moitié)*

**Fichier :** `src/core/cvep_models.py:16-37`.

L'en-tête annonce « **Trois** divergences ASSUMÉES avec les trois jumeaux, à ne pas prendre pour des
oublis » — une formule qui dit au lecteur « ce qui n'est pas là est un oubli ». Or il en manque deux :

1. **`MOTIFS` est un TUPLE** là où `mi_models.py:22`, `p300_models.py:27` et `errp_models.py:34` ont
   `MOTIF`, une **chaîne**. C'est un changement de type sur un nom quasi identique, dans quatre
   modules explicitement présentés comme jumeaux. Justifié à son point de définition (`:65-69`),
   mais absent de la liste qui prétend tout recenser.
2. **`decrire` diverge de plus que ne l'admet l'item 3** : il ajoute `decodeur`, `n_targets` et
   `n_epoques` (`:234-238`), pas seulement `cv_loo` à la place de `cv_auc`.

**Correctif minimal :** passer à « **Cinq** divergences », y intégrer `MOTIFS` et compléter l'item 3.
Coût : 6 lignes de docstring. Une liste qui s'annonce exhaustive et ne l'est pas apprend au prochain
lecteur à ne pas s'y fier — et c'est précisément ce document-là qui doit inspirer confiance.

### M3 — `mi_models.decrire` n'a pas reçu le durcissement que ses trois jumeaux ont, et `cvep_models` affirme la parité

**Fichiers :** `src/core/mi_models.py:87` et `:90` (le manque) ; `src/core/cvep_models.py:36-37`
(l'affirmation).

`cvep_models.py:36-37` écrit : « Les quatre clés que les **quatre** modules partagent restent
`chemin`, `nom`, `date`, `probleme`. » Les clés, oui. Le **contrat**, non :

```python
# mi_models.py:87, :90 — PAS de `chemin and`
    horodatage = _os.path.getmtime(chemin) if _os.path.isfile(chemin) else 0.0
    ...
        "nom": _os.path.basename(chemin),
```

contre `cvep_models.py:229,232` / `errp_models.py:182,185` / `p300_models.py:111,114`, qui portent
tous `if chemin and _os.path.isfile(chemin)` et `_os.path.basename(chemin) if chemin else ""`.
`mi_models.decrire(None)` lève donc `TypeError`, là où les trois autres rendent un dict — la
divergence est chez `mi_models`, pas dans ma tranche, mais elle contredit la phrase de `cvep_models`.

Risque réel faible : le seul appelant en production (`modes/mi_calib.py:356`) passe le chemin d'une
calibration qui vient d'aboutir, jamais `None`. C'est de la dette de symétrie, pas un défaut vivant.
Et `errp_models.py:177-181` documente ce durcissement comme motivé par « un fil Qt de distance ».

**Correctif minimal :** deux fois `chemin and` dans `mi_models.py:87,90`, plus l'ajout de `mi` à la
boucle `for entree in (None, "", 0)` de son `_selftest` (les trois autres l'ont déjà).

### M4 — `CVEPModel.save` lève sur un chemin sans dossier ; son jumeau `RCCAModel.save` non

**Fichiers :** `src/core/cvep_decoder.py:246` contre `src/core/cvep_rcca.py:227`.

```python
# cvep_decoder.py:246
        os.makedirs(os.path.dirname(path), exist_ok=True)
# cvep_rcca.py:227  (le jumeau, correct)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
```

`CVEPModel(...).save("cvep_model.npz")` — un chemin relatif nu, ce qu'écrit n'importe quel script
d'analyse lancé depuis la racine — appelle `os.makedirs("")` et lève `FileNotFoundError`. Le jumeau a
la garde ; celui-ci ne l'a pas. Aucune justification n'est donnée à la divergence, et aucun test ne
la couvre (les deux `_selftest` passent toujours par `os.path.join(tmp, ...)`).

**Correctif minimal :** ajouter ` or "."` — un token.

### M5 — Un `CVEPModel` jamais ajusté s'écrit en PICKLE, sans le dire ; le jumeau refuse

**Fichiers :** `src/core/cvep_decoder.py:247-254` contre `src/core/cvep_rcca.py:225-226`.

`RCCAModel.save` commence par :

```python
        if self._epochs is None:
            raise ValueError("modèle rCCA jamais ajusté : rien à sauvegarder (appelle `fit`)")
```

`CVEPModel.save` n'a pas l'équivalent. Avec `self.w is None` et `self.template is None` (l'état
sortant de `__init__`, `:127-128`), `np.savez` sérialise deux tableaux d'objets — **`np.savez`
autorise le pickle par défaut**, contrairement à `np.load` — et grave un `.npz` piégé dans `data/`,
au nom d'un modèle.

Ce fichier est ensuite correctement refusé (`charger` → `CVEPModel.load` → `ValueError` sur
`allow_pickle=False`), mais **avec le mauvais diagnostic** : « modèle illisible (ValueError) ». Le
fichier n'est pas corrompu — il n'a simplement jamais été entraîné. On envoie l'étudiant chercher une
corruption là où il y a un `fit` manquant, exactement le type d'erreur d'aiguillage que le contrôle
de clés de `charger:143-149` a été écrit pour supprimer.

**Correctif minimal** (3 lignes, symétriques du jumeau) :

```python
        if self.w is None or self.template is None:
            raise ValueError("modèle eCCA jamais ajusté : rien à sauvegarder (appelle `fit`)")
```

### M6 — `CVEPModel.load` / `RCCAModel.load` n'utilisent pas `with`, contrairement à `charger`

**Fichiers :** `src/core/cvep_decoder.py:259` ; `src/core/cvep_rcca.py:245` ; à comparer à
`src/core/cvep_models.py:128` (`with _np.load(chemin) as d:`).

`d = np.load(path)` laisse le `NpzFile` — donc le handle du zip — ouvert jusqu'au ramassage. Sous
CPython, `d` sort du scope au `return` et le compteur de références le ferme immédiatement : **aucun
défaut observable aujourd'hui**. Mais `charger`, dans le même chantier, prend explicitement la peine
de fermer ; et sous un interpréteur sans comptage de références, le `.npz` resterait ouvert — ce qui,
sous Windows, ferait échouer un `os.rename`/`os.remove` ultérieur (le geste exact que
`cvep_models._selftest:475-477` exécute juste après une série de `charger`).

**Correctif minimal :** deux `with`, quatre lignes réindentées. À traiter comme de l'hygiène, pas
comme un bug.

---

## Point transverse n° 1 — `server.py --smoke` écrit dans le VRAI `data/`

**Fichiers :** `src/core/server.py:1618-1746` (`_smoke_mi`), en particulier `:1650` et `:1732-1739` ;
`src/core/config.py:102-110` (la limite du garde) ; `archive/README.md:39-44` (elle y est documentée).

### La question posée

Détourner le smoke vers un dossier temporaire, changer la forme du garde, ou les deux ?

### Recommandation : **détourner le smoke. Ne pas toucher à la forme du garde. Et — c'est le vrai manque — TESTER le garde (C1).**

Trois raisons, dans cet ordre.

**1. Le remède existe déjà, il est appliqué partout ailleurs dans ce chantier, et il coûte six
lignes.** `_smoke_mi` est le dernier tenant : son voisin immédiat, `_smoke_calibration`, annonce
déjà en docstring « Tout est écrit dans un dossier temporaire. Le vrai `data/` n'est jamais
approché » (`server.py:1757`). Et le levier est déjà en place, délibérément :
`modes/mi.py:227-231` déclare `choices_fn=lambda: mi_models.modeles_disponibles()` avec le
commentaire « Le lambda est délibéré : il résout `modeles_disponibles` À L'APPEL [...] l'autotest ne
pourrait plus rediriger la recherche vers un dossier temporaire sans toucher à `data/` ».
`mi.py::_selftest` s'en sert déjà (`:350`, `:357`, `:585`). Le smoke passe d'ailleurs le chemin du
modèle explicitement (`server.py:1664`) : le dossier `data/` ne lui sert qu'à faire passer le
contrôle d'appartenance de `validate` sur un `kind="choice"`.

```python
    dossier = tempfile.mkdtemp(prefix="smoke_mi_")
    chemin = os.path.join(dossier, "mi_model_smoke.joblib")
    vrai_dispo = mi_models.modeles_disponibles
    mi_models.modeles_disponibles = lambda d=dossier: vrai_dispo(d)
    try:
        ...                      # inchangé
    finally:
        mi_models.modeles_disponibles = vrai_dispo
        shutil.rmtree(dossier, ignore_errors=True)
        ...                      # server.stop() / thread.join() inchangés
```

Ça ne réduit pas la fenêtre d'exposition : **ça la supprime.** Il n'y a plus rien à détecter, donc
plus rien qui dépende de la finesse du garde. Le meilleur garde est celui qui n'a rien à attraper.

**2. Changer la forme du garde ne peut PAS être fait à bon marché, et un demi-correctif serait pire
que l'état actuel.** Voir un créer-puis-effacer exige de surveiller le dossier **pendant**
l'exécution : `watchdog` (une dépendance de plus, pour du test), ou l'interposition des appels
d'écriture (un stub sur `open`/`joblib.dump`/`np.savez`, qui rate tout ce qui écrit par un autre
chemin). Tout ce qui est moins cher — échantillonner plus souvent, prendre l'empreinte dans un fil —
n'est qu'un raffinement de l'échantillonnage : ça rétrécit la fenêtre sans la fermer, et ça produirait
alors une docstring qui annonce l'étanchéité sans l'avoir. L'état actuel est meilleur que ça : la
limite est écrite noir sur blanc (`config.py:102-110`) et reprise dans `archive/README.md:43-44`.
**Un garde honnête sur sa portée vaut mieux qu'un garde ambigu.**

**3. La prémisse de l'escalade est un cran trop pessimiste, ce qui renforce la conclusion.** « Un
Ctrl+C laisserait le fichier » n'est pas exact : `KeyboardInterrupt` est une exception, donc le
`finally` de `server.py:1732` **s'exécute**, et l'ordre y est déjà délibéré — le `os.remove` passe
AVANT `server.stop()` et le `join`, avec le commentaire qui l'explique (`:1733-1737`). Le fichier ne
survit qu'à un arrêt DUR : `Ctrl+Break`, `taskkill`, coupure de courant, ou un second `Ctrl+C` qui
tomberait à l'intérieur du `finally`. Le risque résiduel est donc étroit — trop étroit pour justifier
une dépendance `watchdog`, et largement assez pour justifier six lignes qui l'annulent.

### Ce qu'il faut faire, dans l'ordre

1. **Détourner `_smoke_mi`** vers un dossier temporaire (6 lignes ci-dessus). L'accident mesuré
   disparaît, définitivement.
2. **Laisser `empreinte_dossier` tel quel**, docstring comprise : sa limite est correctement décrite,
   et c'est sa qualité principale.
3. **Tester `empreinte_dossier`** — voir C1. C'est là qu'est le vrai défaut : le dépôt possède
   aujourd'hui un garde non éprouvé qui défend contre une écriture qu'il suffirait de ne plus faire.
   Une fois (1) fait, ce garde ne protège plus que les quatre `archive/*.py`, et il n'aura toujours
   jamais été prouvé capable de voir quoi que ce soit.

Formulé autrement, pour le prochain lecteur : **le garde n'a pas besoin de changer de forme, il a
besoin d'une preuve — et le smoke n'a pas besoin d'être surveillé, il a besoin de ne plus écrire là.**
