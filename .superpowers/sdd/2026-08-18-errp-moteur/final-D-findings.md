# Tranche D — revue finale : `errp_stimulus.py`, `app.py`, `research/__init__.py`

Périmètre relu : `src/research/errp_stimulus.py` (créé, 398 l.), `src/research/app.py` (2 imports),
`src/research/__init__.py` (1 ligne). Patron de comparaison : `src/research/p300_stimulus.py`.
Sources de vérité du protocole : `src/research/errp_calibrate.py` (`_run_block`), `src/research/app.py`
(`mode_errp`), `src/core/modes/errp.py`.

**Lecture seule — aucun programme exécuté.** Les trois points qui demandent une exécution sont
signalés « À VÉRIFIER PAR EXÉCUTION ».

Ce qui est BON et que je n'ai pas retenu comme constatation : aucune trace de BrainFlow dans
l'émetteur (0 occurrence de `brainflow|BoardShim|prepare_session`) — l'exigence « n'ouvre PAS le
casque » est tenue ; `--smoke` appelle bien le VRAI `run()` sous `SDL_VIDEODRIVER=dummy` posé AVANT
l'import tardif de pygame ; `local_clock()` n'est appelé qu'à UN seul endroit (`emet`, l. 210) et
`emet` n'est appelé qu'après `pygame.display.flip()` (l. 257 → 263) — un seul appel d'horloge par
événement, pas deux ; sortie en 1 sur échec (l. 398) ; aucune écriture dans `data/` ; frontière
`research → core` respectée ; `src/research/errp_decoder.py` a bien DISPARU du disque (l'original ne
se maintient pas en double, conformément à la règle du projet).

Récapitulatif : **1 Critical · 6 Important · 4 Minor**.

---

## C1 — Critical — La fin de course téléporte le point ET déplace la cible DANS la frame du marqueur

**Fichier : `src/research/errp_stimulus.py:247-277`** (le cœur : l. 272-277 pour la remise à zéro,
l. 248-257 pour le pas suivant), en contradiction avec la docstring l. 42-47.

### Ce qui casse

Quand une course se termine (cible atteinte ou `ERRP_MAX_RUN_STEPS`), la boucle fait, **sans afficher
une seule frame intermédiaire** :

```python
        if pos == cible or n_pas_course >= ERRP_MAX_RUN_STEPS:   # l. 272
            pos = n_cells // 2                                    # l. 275  téléportation
            cible = nouvelle_cible(n_cells, rng)                  # l. 276  la cible change de côté
            n_pas_course = 0
    # ... retour en haut du while :
        nouvelle_pos, erreur = decide_pas(...)                    # l. 248
        pos = nouvelle_pos
        ...
            draw(pos, cible)                                      # l. 256
            pygame.display.flip()                                 # l. 257
            if f == 0:
                emet({"mode": "errp", "event": "feedback"}, erreur)  # l. 263
```

La **première frame de la nouvelle course est aussi la frame horodatée** du premier `feedback` de
cette course. Ce que l'écran fait à cet instant précis n'est PAS un pas d'une case : le curseur
saute de l'extrémité au centre ±1 (2 à 4 cases d'un coup) **et**, avec p = 0,5, la pastille verte de
la cible traverse tout l'écran d'une extrémité à l'autre (`nouvelle_cible` retire à 50/50, l. 108).

**Les DEUX implémentations qui produisent et exploitent réellement le modèle intercalent un écran
statique exactement là** :

- `src/research/errp_calibrate.py:223-227` — `_track_hold(..., 0.7, note="atteinte"/"on recommence")`
  puis `:211` `_track_hold(..., 0.9, note="nouvelle cible")` après la remise au centre ;
- `src/research/app.py:1024-1029` (`mode_errp`) — `_track_hold(..., 1.0, note="cible atteinte")` puis
  `_track_hold(..., 0.9, note="nouvelle cible")`.

La docstring du module affirme le contraire, en toutes lettres, avec un argument qui ne s'applique
pas (l. 44-47) : « Cible atteinte, ou `ERRP_MAX_RUN_STEPS` dépassés -> nouvelle course, **sans aucune
pause** : contrairement au P300, il n'y a pas de « manche » à protéger d'une contamination ». Le
problème n'est pas une contamination ENTRE époques (celle-là, en effet, n'existe pas ici) : c'est un
transitoire visuel plein écran placé **à t=0 DANS** l'époque.

### Scénario concret

Réglages par défaut, `python src/core/server.py --mode errp` + `python src/research/errp_stimulus.py`,
modèle valide. Piste de 7 cases, départ case 3, cible tirée en 6.

1. Le point atteint la case 6 → `pos == cible` → remise à `pos = 3`, `cible = 0` (tirage à 50/50).
2. Frame suivante : `decide_pas` renvoie 2 (pas correct vers 0) → `draw(2, 0)` → `flip()` → marqueur.
3. Ce que l'utilisateur a vu à t=0 : le curseur a fait **4 cases vers la gauche** (6 → 2) et la
   pastille verte a sauté de x≈1476 px à x≈444 px (écran 1920, `dx=172`, l. 195-196).
4. Le moteur épochera `[-0,2 s ; +0,7 s]` autour de cette frame (`core/modes/errp.py:357-360`), le
   rejet d'artefact ne le sauvera pas — il compare un σ à 4× le σ de repos BRUT
   (`core/modes/errp.py:382-394`), et une réponse visuelle évoquée pèse quelques µV contre des
   dizaines de µV de bruit de fond — donc `model.score()` tourne et `decoded_errp` publie un verdict
   confiant sur un stimulus que le modèle n'a **jamais** vu à l'entraînement.

**Fréquence : ~1 époque sur 7.** Dérive nette vers la cible = 1 − 2×0,28 = +0,44 case/pas pour une
distance de 3 → longueur moyenne d'une course ≈ 7 pas (plafonnée à 14). Soit **~13-14 % des verdicts
publiés** qui portent sur une frame hors protocole. Sur un détecteur mono-essai dont l'AUC honnête
est 0,776 (`docs/recette.md:560`), 13 % d'époques hors distribution n'est pas un détail : c'est
l'ordre de grandeur de l'effet qu'on mesure.

### Correctif minimal

Après la remise à zéro (l. 272-277), tenir la piste STATIQUE ~0,9 s avant de repartir — la même
forme que la boucle de feedback, **sans `emet`** :

```python
        if pos == cible or n_pas_course >= ERRP_MAX_RUN_STEPS:
            print(...)
            pos, cible, n_pas_course = n_cells // 2, nouvelle_cible(n_cells, rng), 0
            # ⚠️ La nouvelle course DOIT être vue AVANT son premier pas : sans cet écran, le curseur
            # saute de 4 cases et la cible change de côté DANS la frame horodatée du feedback
            # suivant. Même geste que errp_calibrate._run_block et app.mode_errp.
            for _ in range(max(1, int(round(0.9 * refresh)))):
                poll()
                if not running:
                    break
                draw(pos, cible)
                pygame.display.flip()
                clock.tick(int(refresh) + 5)
```

Le même écran statique règle au passage le cas de la **toute première course** : aujourd'hui `pos`
(l. 243) n'est jamais affiché avant le premier saut, l'utilisateur ne voit donc pas d'où le point
part et ne peut former aucune attente à violer.

**À VÉRIFIER PAR EXÉCUTION** (après correctif) : `python src/research/errp_stimulus.py --smoke` —
attendu : `ecarts` (l. 364-367) sortant de la fourchette actuelle sur le pas qui suit une fin de
course, donc la borne haute de ce `chk` doit être relâchée en même temps, ou l'assertion découpée
en « écarts intra-course » vs « écart de transition ».

---

## I1 — Important — Cadence 1,0 s alors que le modèle a été entraîné à 1,45 s

**Fichier : `src/research/errp_stimulus.py:247-268`**, contre `src/research/errp_calibrate.py:229`.

### Ce qui casse

L'émetteur enchaîne les pas sans respiration : `n_fr = round(ERRP_FEEDBACK_S * refresh)` frames
(l. 251), puis directement le pas suivant. **SOA entre deux onsets = 1,0 s.**

Les deux références en ont une :

| Source | Fenêtre de feedback | Pause inter-pas | **SOA réel** |
|---|---|---|---|
| `errp_calibrate._run_block` (**produit le modèle**) | `_step(ERRP_FEEDBACK_S)` = 1,0 s | `_track_hold(..., 0.45)` l. 229 « pause inter-pas / settle » | **1,45 s** |
| `app.mode_errp` (démonstrateur) | `_step(ERRP_FEEDBACK_S)` = 1,0 s | `_track_hold(ERRP_EPOCH_S + 0.2)` = 0,9 s (l. 999) | **1,9 s** |
| `errp_stimulus.run` (cette tranche) | 1,0 s | aucune | **1,0 s** |

La docstring du module (l. 24-30) affirme que le protocole est « repris **TELLE QUELLE** des DEUX
endroits qui la jouent déjà ». C'est faux sur le **seul paramètre temporel qui compte pour un
décodeur d'ERP**. Le tour 1 de revue a déjà corrigé une affirmation d'identité fausse au même
endroit (le taux d'erreur, l. 32-40) — la cadence est le second exemplaire du même défaut, non vu.

### Scénario concret

Modèle entraîné par `errp_calibrate` (200 essais à 1,45 s de SOA), moteur `--mode errp`, émetteur
lancé avec ses défauts.

- L'époque vaut `ERRP_PRE_S + ERRP_EPOCH_S` = 0,9 s (`core/modes/errp.py:495`). À 1,0 s de SOA, il ne
  reste **0,1 s** de piste libre entre la fin d'une époque et le début de la ligne de base de la
  suivante.
- La ligne de base `[-0,2 s ; 0]` de l'époque n+1 est donc prélevée **0,8-1,0 s après le saut
  précédent**, contre **1,25-1,45 s** dans les données d'entraînement. `ERRP_BAND = (1,0 ; 10,0)`
  laisse passer le 1 Hz : une composante à 1 Hz a une période de 1 s, la queue de la réponse
  précédente est donc encore présente dans cette ligne de base, et elle ne l'était pas à
  l'entraînement.
- Rien ne lève d'exception. Le moteur publie des scores. Ils sont décalés en distribution par
  rapport au seuil réglé sur les scores hors-pli de la calibration
  (`core/modes/errp.py:166-169`) — c'est exactement la panne canonique décrite dans le fichier
  moteur : « des scores plausibles et faux ».

**Et le smoke ne peut pas l'attraper** : sa tolérance est `0.5 * ERRP_FEEDBACK_S < e < 1.5 *
ERRP_FEEDBACK_S` (l. 365), soit `]0,5 s ; 1,5 s[`. Un SOA de 1,45 s y passerait **vert**. La seule
assertion qui touche à la cadence accepte donc une erreur de +45 %.

### Correctif minimal

```python
PAUSE_INTER_PAS_S = 0.45   # « pause inter-pas / settle » : la MÊME que errp_calibrate._run_block:229,
#                            celle sous laquelle les époques du modèle ont été enregistrées.
```

et, après la boucle de feedback, une boucle d'attente statique de `PAUSE_INTER_PAS_S` (même forme
que celle du correctif C1 — les deux se factorisent en une seule fonction `tenir(pos, cible,
secondes)`). Resserrer alors le `chk` de la l. 365 autour de `ERRP_FEEDBACK_S + PAUSE_INTER_PAS_S`
avec une marge de ±20 %, pour qu'une régression de cadence redevienne détectable.

---

## I2 — Important — Le protocole est RECOPIÉ une 3e fois, alors que le jumeau P300 fait l'inverse et l'INTERDIT par un test

**Fichier : `src/research/errp_stimulus.py:100-128`** (`nouvelle_cible`, `decide_pas`) contre
`src/research/errp_calibrate.py:70-89` (`_new_goal`, `_decide_step`).

### Ce qui casse

Les deux fonctions sont une transcription ligne à ligne de `_new_goal`/`_decide_step` (mêmes
variables renommées en français, même rebond, même règle d'étiquette). La docstring l. 24-30 le
revendique même : « ce protocole ne s'invente pas ici, il **se reproduit** ». Reproduire, ici, veut
dire recopier : la fonction est réécrite, pas appelée.

**Le jumeau P300 a tranché exactement l'inverse, dans la même situation**, et le dit :

- `src/research/p300_stimulus.py:107-111` — « Cette fonction est donc le SEUL endroit où ce mélange
  s'écrit […] Une contrainte tenue à un seul endroit sur trois n'est pas une contrainte. » ;
- `src/research/p300_calibrate.py:32` — `from research.p300_stimulus import blocs_melanges` ;
- `src/research/app.py:631` — même import ;
- `src/research/app.py:1443-1447` — **une assertion sur le SOURCE** qui interdit qu'un `rng.shuffle`
  local réapparaisse dans l'un des trois sites.

Le module léger (l'émetteur) possède l'invariant, les modules lourds l'importent. L'ErrP fait le
contraire sans le justifier : la docstring explique l'absence de `valide_reglages` (l. 58-63), la
divergence de taux d'erreur (l. 32-40), mais jamais la duplication.

### Scénario concret

Quelqu'un corrige la dégénérescence à `--cells ≤ 2` (cf. M2) dans `errp_calibrate._decide_step`, ou
ajoute une troisième position de cible pour équilibrer autrement. La calibration change, le
démonstrateur change (il importe `_decide_step`, `app.py:959`), **l'émetteur réseau ne change pas**.
Le modèle est alors entraîné sous le protocole A pendant que la référence publique — celle que la
doc désigne comme « l'exemple pour Unity » (l. 10-11) — joue le protocole B. Aucun test ne le dit :
le smoke de l'émetteur ne vérifie que sa propre copie.

### Correctif minimal

Déplacer `nouvelle_cible`/`decide_pas` ici (c'est déjà le module léger : pas de numpy, pas de
sklearn, pas de `research.ui`), et faire de `errp_calibrate._new_goal`/`_decide_step` des adaptateurs
de 2 lignes qui traduisent le `bool` en `ERROR`/`CORRECT` :

```python
# errp_calibrate.py
from research.errp_stimulus import decide_pas, nouvelle_cible   # LA seule écriture du protocole

def _decide_step(rng, pos, goal, n_cells, error_rate, force=None):
    new_pos, erreur = decide_pas(rng, pos, goal, n_cells, error_rate, force=force)
    return new_pos, (ERROR if erreur else CORRECT)
```

Le précédent existe et fonctionne : `p300_calibrate.py` importe déjà `p300_stimulus`, donc `pylsl` au
passage. Ajouter dans `app.py:_smoke` la même assertion de source que pour `blocs_melanges`, étendue
à `errp_calibrate._decide_step` et `mode_errp`.

---

## I3 — Important — La vérité-terrain n'est récupérable par AUCUN moyen après la séance

**Fichier : `src/research/errp_stimulus.py:263-267`** (l'horodatage renvoyé par `emet` est jeté),
`:202` (`rng = random.Random()`, sans graine), `:378-390` (pas de `--seed`).

### Ce qui casse

Le marqueur ne porte volontairement aucune vérité-terrain — et c'est la bonne décision, longuement
argumentée (l. 18-22). Mais alors la trace LOCALE devient la seule, et elle est inexploitable :

```python
            if f == 0:
                emet({"mode": "errp", "event": "feedback"}, erreur)   # l. 263 : le `ts` renvoyé est JETÉ
                pas_total += 1
                erreurs_total += int(erreur)
                print(f"[errp-stim] pas {pas_total} : point -> case {pos} "      # l. 266-267
                      f"({'ÉLOIGNÉ (erreur)' if erreur else 'rapproché (correct)'})")
```

`emet` (l. 208-214) calcule et **retourne** `ts` — l'appelant l'ignore. La ligne imprimée ne porte
donc ni horodatage LSL, ni rien qui permette de la raccrocher à un échantillon de `decoded_errp`.
Et sans `--seed`, deux exécutions ne jouent pas la même séquence : impossible de rejouer.

Le raisonnement de la docstring l. 136-141 s'arrête à mi-chemin : `journal` existe « pour permettre à
`--smoke` de vérifier » — mais l'usage RÉEL, celui de la recette, n'a rien.

### Scénario concret

`docs/recette.md:582` demande à l'étudiant : « **Compte tes erreurs délibérées et les `error = 1`
publiés.** » Il lance les trois terminaux du 4.x. Puis :

1. Il ne peut pas compter en direct : le point saute toutes les secondes (cf. I1) et la recette lui
   demande dans la même liste de « se laisser surprendre, **ne pas anticiper** » — regarder l'écran
   et tenir un décompte sont deux tâches incompatibles.
2. Il ne peut pas non plus compter APRÈS : la seule façon serait d'apparier le n-ième `[errp-stim]
   pas N` avec le n-ième échantillon `decoded_errp`. Or le moteur **jette** tous les marqueurs de
   ses 15 s de chauffe + 8 s de repos (`core/modes/errp.py:331-349`, cf. I4) : à 1 s de SOA,
   ~23 lignes `pas 1 … pas 23` n'ont **aucun** échantillon en face. L'appariement par index est
   décalé d'un nombre que seul le terminal du moteur connaît.
3. Résultat : on ne peut pas calculer un TPR/TNR de séance. Or c'est précisément ce que les erreurs
   DÉLIBÉRÉES existent pour rendre possible.

### Correctif minimal

Trois lignes, aucune dépendance nouvelle :

```python
    p.add_argument("--seed", type=int, default=None,
                   help="graine du tirage des erreurs — pour rejouer EXACTEMENT la même séquence")
    ...
    rng = random.Random(seed)                                    # l. 202
    ...
            if f == 0:
                ts = emet({"mode": "errp", "event": "feedback"}, erreur)   # on GARDE l'horodatage
                ...
                print(f"[errp-stim] t={ts:.3f} pas {pas_total} : point -> case {pos} ...")
```

`t` est l'horodatage LSL exact du marqueur : il suffit pour rejoindre a posteriori la séquence
`decoded_errp` (dont chaque échantillon est estampillé par le moteur), donc pour mesurer TPR/TNR
hors ligne — sans jamais mettre la vérité-terrain sur le réseau.

---

## I4 — Important — L'émetteur démarre pendant les 23 s où le moteur jette tout, et affiche l'inverse

**Fichier : `src/research/errp_stimulus.py:182-191`** (le message l. 191 : « le moteur écoute — on
peut commencer. »), et `:237` (le HUD « moteur À L'ÉCOUTE »).

### Ce qui casse

`outlet.wait_for_consumers()` répond « oui » dès que l'inlet du moteur est résolu — ce qui arrive au
DÉMARRAGE du moteur, pas à la fin de sa chauffe. Le mode ErrP, lui, n'accepte rien pendant :

```
Rest(warmup_s=SSVEP_WARMUP_S,   # 15,0 s (core/config.py:213)
     duration_s=8.0, ...)       # core/modes/errp.py:480-484   ->  23 s au total
```

et pendant ces 23 s, `_jeter_marqueurs_de_chauffe` (`core/modes/errp.py:331-349`) **vide et compte**
tout ce qui arrive. Le mode ErrP est celui dont l'attente est la plus longue des cinq (sa propre
docstring le souligne, l. 55-57 : « 23 s, contre 15 s pour le P300 »). L'émetteur, lui, ne sait rien
de cette phase et affirme le contraire de ce qui se passe.

### Scénario concret

Recette 1.15 (`docs/recette.md:355-360`), à la lettre :

1. Terminal 1 : `python src/core/server.py --synthetic --mode errp`.
2. Terminal 2 : `python src/research/errp_stimulus.py --windowed`.
3. `wait_for_consumers` rend `True` en moins d'une seconde → l'émetteur imprime **« le moteur écoute
   — on peut commencer. »** et attaque le premier pas.
4. Pendant 23 s : le point saute 23 fois, le terminal imprime 23 lignes « pas N : point -> case X »
   avec leur étiquette, le HUD affiche « moteur À L'ÉCOUTE » — et **aucun** de ces 23 feedbacks n'est
   décodé. Le seul indice est une ligne dans l'AUTRE terminal.
5. Cas particulier plus vicieux : les 8 s de repos du moteur sont l'instant où il mesure sa
   **référence de rejet d'artefact** sur signal brut (`core/modes/errp.py:282-317`), avec pour
   consigne affichée « Repos : regarde l'écran, immobile ». Pendant ce repos, l'écran que le sujet
   regarde fait sauter un curseur toutes les secondes. *(Impact sur le σ : probablement faible — une
   réponse visuelle pèse quelques µV contre des dizaines de µV de bruit brut — je le signale comme
   incohérence de protocole, pas comme effet mesuré.)*

Le jumeau P300 a le même trou, mais il coûte 15 s et une seule manche perdue, annoncée par un
`round_end` ; ici il coûte 23 pas et rien ne l'annonce.

### Correctif minimal

Après le `wait_for_consumers` réussi (l. 190-191), dire la vérité **et** tenir la piste statique le
temps de l'attente — ce qui donne en prime l'écran « nouvelle cible » que les deux références ont et
que celui-ci n'a pas (cf. C1) :

```python
from core.config import SSVEP_WARMUP_S          # + le 8.0 s de SPEC.rest du mode errp
ATTENTE_MOTEUR_S = SSVEP_WARMUP_S + 8.0         # 23 s : chauffe + repos du mode errp

    elif attente_consommateur_s > 0:
        print(f"[errp-stim] le moteur écoute — mais il JETTE tout pendant sa chauffe et son repos "
              f"(~{ATTENTE_MOTEUR_S:g} s, cf. core/modes/errp.py). Piste statique en attendant : "
              f"les premiers pas décodés seront ceux d'après.")
```

suivi d'une boucle `tenir(pos, cible, ATTENTE_MOTEUR_S)` (la même fonction que C1/I1), avec ESC
actif. Un `--no-wait` pour qui lance l'émetteur seul.

---

## I5 — Important — L'ordre `flip()` → `push_sample`, la seule chose que ce fichier existe pour enseigner, n'est vérifié par aucune assertion

**Fichier : `src/research/errp_stimulus.py:256-263`** (le geste), `:285-375` (le smoke qui prétend le
couvrir), `:295-298` (la docstring qui l'affirme).

### Ce qui casse

Le smoke revendique explicitement cette couverture (l. 295-298) : « un `--smoke` qui retournerait
avant l'import de pygame laisserait SANS AUCUNE COUVERTURE les lignes qui contiennent le geste
flip->horodatage, **la seule chose que ce fichier existe pour enseigner** ». Exécuter les lignes
n'est pas les vérifier. Passage en revue mutation par mutation des 8 `chk` :

| `chk` (ligne) | Mutation d'UNE ligne de production qui le fait rougir |
|---|---|
| `hors_piste` (323) | supprimer le rebond l. 125-126 → le point sort en `-1` ✅ |
| taux à 5σ (330) | `rng.random() < taux_erreur` → `< taux_erreur / 2` (l. 122) ✅ |
| rebond au bord (340) | calculer `erreur_reelle` depuis `erreur` au lieu des positions (l. 127) ✅ |
| `fait` (353) | `return True` → `return False` (l. 280) ✅ |
| `len(journal) >= 3` (355) | supprimer le `if f == 0` → **plus** de marqueurs, reste vert ; supprimer `emet` → rouge ✅ (faible) |
| charge utile exacte (356) | ajouter `"erreur": erreur` au dict l. 263 ✅ — c'est la bonne garde |
| horodatages croissants (361) | `ts = local_clock()` → `ts = 0.0` (l. 210) ✅ (faible) |
| écarts ≈ 1 s (365) | `if f == 0` → `if f % 10 == 0` (l. 262) ✅ ; **mais** `n_fr * 1.45` reste vert (cf. I1) |

**Aucune ligne du tableau ne couvre l'ordre flip/push.** Mutation : remonter la l. 263 (`emet(...)`)
au-dessus de la l. 257 (`pygame.display.flip()`). Les 8 `chk` restent verts, le verdict imprime
`OK`, la sortie est 0 — et toutes les époques du moteur sont décalées d'une frame, exactement la
panne que la docstring décrit l. 258-261 (« Rien ne lève d'erreur ; les scores sortent, et ils sont
du bruit »).

### Scénario concret

Un étudiant réorganise la boucle pour « émettre au plus tôt » et déplace `emet` avant `flip`. Il
lance `python src/research/errp_stimulus.py --smoke` : `VERDICT : OK`. Il branche le casque. À
60 Hz, tous les onsets sont 16,7 ms trop tôt (et jusqu'à 33 ms si le pilote met la frame en file) ;
le décodeur corrèle contre une réponse évoquée qui n'a pas encore eu lieu. Les scores sortent, le
flux vit, personne ne voit rien.

### Correctif minimal

Vérifiable en headless, `flip` étant un no-op mesurable sous le pilote `dummy` — on n'a pas besoin
que l'écran change, seulement que l'APPEL précède :

```python
    # --- B. run() POUR DE VRAI ---
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame
    flips = []
    vrai_flip = pygame.display.flip
    pygame.display.flip = lambda *a, **k: (vrai_flip(*a, **k), flips.append(local_clock()))[0]
    try:
        fait = run(...)
    finally:
        pygame.display.flip = vrai_flip
    ...
    # ⚠️ LE test de ce fichier : chaque marqueur part APRÈS le flip qui a mis le feedback à l'écran.
    chk(bool(flips) and all(any(f <= ts for f in flips) for _m, ts, _e in journal)
        and all(ts >= max(f for f in flips if f <= ts) for _m, ts, _e in journal),
        "chaque horodatage suit le flip qui l'a produit — jamais l'inverse")
```

Plus simplement et tout aussi rouge : faire renvoyer à `emet` le nombre de flips vus au moment de
l'appel et asserter `len(flips) >= 1` **avant** chaque push (`chk(all(n >= 1 for n in flips_au_push))`).

*(Le jumeau `p300_stimulus.py` a exactement le même trou : la mutation `emet` avant `flip` y passe
aussi. Le correctif vaut pour les deux, et c'est le seul endroit de cette revue où je recommande de
toucher au jumeau.)*

---

## I6 — Important — `research/__init__.py` : les deux mises à jour exigées par le plan sont à moitié faites

**Fichier : `src/research/__init__.py:13-15` et `:16-19`.** Le plan les demandait explicitement
(`docs/superpowers/plans/2026-08-18-errp-moteur.md:665` : « `src/research/__init__.py` :
`errp_decoder` a migré, `errp_stimulus.py` n'ouvre pas le casque »).

### Ce qui casse

**(a) L'avertissement qui liste les programmes SANS casque ne cite pas le nouveau.** Lignes 13-15,
inchangées :

> ⚠️ `p300_stimulus.py` est l'exception qui confirme la règle : il n'ouvre PAS le casque […] C'est ce
> qui permet de le lancer en même temps que le moteur, dans deux terminaux — comme `ssvep_stimulus.py`.

`errp_stimulus.py` n'y figure pas. Or c'est la carte du dossier, et la règle voisine (`CLAUDE.md` :
« ⚠️ **Un seul de ces trois programmes à la fois** — le casque n'accepte qu'une connexion ») est une
règle de sécurité matérielle.

**(b) La migration du décodeur n'est comptée qu'à moitié.** Lignes 16-19, la ligne MODIFIÉE par ce
chantier :

> 2. **Les décodeurs des modes** — `cvep_*` seulement, désormais. […] `neuro_monitor` […]
> `mi_decoder` […] `p300_decoder` (avec `p300_models`) le 2026-08-17 : **tous trois** vivent
> maintenant dans `core`.

`errp_decoder` a été RETIRÉ de la famille 2 (c'est le diff) mais n'a jamais été AJOUTÉ à la liste
des migrations : ils sont quatre, le texte dit « tous trois ». Le fichier ne dit donc nulle part où
`errp_decoder` est parti, alors que c'est le déplacement central du chantier (commit b35872a).

### Scénario concret

Un étudiant ouvre `src/research/` pour comprendre le dossier — c'est le point d'entrée documentaire
prévu. Il lit le ⚠️ : deux programmes sont déclarés sans casque, `errp_stimulus.py` n'en est pas. Il
applique la règle « un seul programme à la fois », **ne lance donc jamais l'émetteur en même temps
que le moteur** — c'est-à-dire la seule façon dont il est prévu de fonctionner (`errp_stimulus.py:3-8`,
`docs/recette.md:355-360`). Il conclut que le mode ErrP ne marche pas. Puis il cherche
`research/errp_decoder.py`, ne le trouve pas, et le fichier qui devrait le renseigner ne mentionne
pas son départ.

### Correctif minimal

```
   ⚠️ `p300_stimulus.py` et `errp_stimulus.py` sont les exceptions qui confirment la règle : ils
   n'ouvrent PAS le casque, ils ne font qu'AFFICHER et publier leurs marqueurs. C'est ce qui permet
   de les lancer en même temps que le moteur, dans deux terminaux — comme `ssvep_stimulus.py`.
2. **Les décodeurs des modes** — `cvep_*` seulement, désormais. […] `p300_decoder` (avec
   `p300_models`) le 2026-08-17, `errp_decoder` (avec `errp_models`) le 2026-08-18 : tous quatre
   vivent maintenant dans `core`.
```

---

## M1 — Minor — `--cells 1` sort le point de la piste, `--cells 2` étiquette un pas correct en erreur

**Fichier : `src/research/errp_stimulus.py:111-128`** (`decide_pas`), documenté « librement » l. 60-63
et l. 382-384.

### Ce qui casse

Le rebond (l. 125-126) ne repositionne qu'UNE fois et ne revérifie pas :

- `--cells 1` : `pos = 0`, `cible = 0`. `vers = -1` (car `cible > pos` est faux) → `pas = ±1` →
  `nouvelle_pos` hors piste → rebond → `pos - pas`, **hors piste elle aussi**. `decide_pas` renvoie
  `1` sur une piste de 1 case : le point est dessiné en dehors (`draw`, l. 234), et l'invariant que
  le smoke assure pour `n_cells = 7` (l. 323) est violé pour de bon.
- `--cells 2` : `pos = n_cells // 2 = 1`, qui est **aussi une extrémité**, donc `cible` peut valoir 1
  = `pos`. `vers = -1`, un tirage NON-erreur donne `pas = -1` → le point s'éloigne, et
  `erreur_reelle` vaut `True` : un pas tiré « correct » est publié comme erreur. La garde `if pos ==
  cible` (l. 272) n'intervient qu'en FIN d'itération, jamais au départ d'une course.

La docstring l. 58-63 justifie l'absence de `valide_reglages` par le contrat RÉSEAU — argument juste
— mais en conclut que `--cells` « peut varier librement », ce qui est faux du programme lui-même.
Le jumeau P300, lui, refuse `--targets 0` et `--targets 2` en nommant la constante
(`p300_stimulus.py:147-171`).

### Scénario concret

Un étudiant essaie `python src/research/errp_stimulus.py --cells 2` pour « voir le cas le plus
simple ». Le point oscille entre deux cases, toutes les étiquettes imprimées sont fausses, et il
apprend un protocole inversé. Aucun message.

### Correctif minimal

Une garde de 3 lignes en tête de `run` (et non un `valide_reglages` complet — le raisonnement de la
docstring reste bon pour le reste) :

```python
    if int(n_cells) < 3:
        print(f"[errp-stim] REFUSÉ — --cells {n_cells} : il faut au moins 3 cases pour qu'un départ "
              f"au CENTRE soit distinct des DEUX extrémités (sinon le point démarre sur sa cible et "
              f"chaque pas correct est étiqueté erreur). Le contrat réseau, lui, s'en moque.")
        return False
```

et compléter l. 60-63 : « `--cells` ≥ 3 » plutôt que « librement ».

---

## M2 — Minor — Le smoke n'est pas reproductible et ne couvre jamais `ERRP_MAX_RUN_STEPS`

**Fichier : `src/research/errp_stimulus.py:202`** (`rng = random.Random()` sans graine, y compris
sous smoke), `:311-323` (partie A), `:350-352` (partie B), `:272` (la branche non couverte).

### Ce qui casse

1. **Partie B non graine.** `_smoke` appelle `run()` (l. 350) qui construit `random.Random()` sans
   graine. Deux `--smoke` successifs jouent des trajectoires différentes. Les assertions actuelles
   sont, elles, insensibles à la trajectoire — donc pas de flakiness — mais la **couverture** varie :
   la branche « nouvelle course » (l. 272-277) n'est atteinte que si le point rejoint sa cible en
   ≈7 pas (à p = 0,72 par pas, distance 3 : ~2 exécutions sur 3). Un tiers des `--smoke` ne
   l'exécutent jamais.
   Comparaison : `app.mode_errp` graine explicitement en smoke (`_random.Random(0) if app.smoke`,
   `app.py:971`).
2. **`ERRP_MAX_RUN_STEPS` n'est JAMAIS couvert**, ni en A ni en B. En B, 6,5 s ≈ 7 pas contre un
   plafond de 14. En A (l. 314-322), la boucle pure **ne modélise pas du tout le plafond** : elle ne
   remet à zéro que sur `pos == cible`. Mutation : remplacer `n_pas_course >= ERRP_MAX_RUN_STEPS`
   par `n_pas_course >= 10**9` (l. 272) → **les 8 `chk` restent verts**. Le garde-fou est décoratif.
3. **Division par zéro possible** l. 371 (`n_err_reel / len(journal)`) si `journal` est vide : on
   sort bien en 1 (la trace remonte jusqu'à l'interpréteur), mais par un traceback au lieu de
   `VERDICT : PROBLÈME`.

### Scénario concret

Quelqu'un remplace `n_pas_course >= ERRP_MAX_RUN_STEPS` par `>` — ou supprime la condition en
pensant qu'elle est redondante avec `pos == cible`. `--smoke` : `VERDICT : OK`. En séance avec
`--error-rate 0.5`, le point fait une marche aléatoire pure : la cible n'est **jamais** atteinte, la
course ne se termine jamais, et un étudiant qui voulait « voir ce que donne 50 % » regarde un point
errer indéfiniment sans jamais comprendre que le plafond aurait dû le sauver.

### Correctif minimal

- Ajouter `seed=None` à la signature de `run` (partagé avec I3) et appeler `run(..., seed=0)` depuis
  `_smoke` : couverture reproductible.
- Ajouter `max_run_steps=ERRP_MAX_RUN_STEPS` en paramètre de `run`, et un second appel court dans
  `_smoke` avec `max_run_steps=2` + `taux_erreur=1.0` (le point ne peut jamais atteindre la cible) :
  `chk(len(journal) >= 4, "le plafond de pas termine bien une course qui ne converge pas")`.
- `chk(bool(journal), ...)` avant la l. 369, et sortir tôt de `_smoke` si vide.

---

## M3 — Minor — Quitter en pleine fenêtre de feedback laisse une époque dont l'écran disparaît au milieu

**Fichier : `src/research/errp_stimulus.py:252-280`** (`poll` à chaque frame, puis `pygame.quit()`).

### Ce qui casse

`poll()` (l. 216-227) coupe `running` à n'importe quelle frame — c'est voulu et bien argumenté
(tenir `--seconds` à la seconde près). Mais le marqueur du pas en cours est déjà parti : le moteur
va épocher `[-0,2 s ; +0,7 s]` autour de lui, et `pygame.quit()` (l. 279) fait disparaître la fenêtre
quelque part au milieu de cette fenêtre de 0,7 s. Le jumeau P300 traite explicitement le cas de
l'interruption (`p300_stimulus.py:392-400` : un `round_end` est émis pour que le moteur sache tout de
suite) ; ici, rien — pas même l'attente des 0,7 s restantes.

### Scénario concret

`python src/research/errp_stimulus.py --seconds 20`. À t = 20,0 s l'émetteur s'arrête ; le dernier
`feedback` est parti à t ≈ 19,4 s. Le moteur épochera jusqu'à t = 20,1 s — donc 0,1 s après que
l'écran est devenu noir et que la fenêtre a disparu. Il publie un verdict sur cette époque comme sur
n'importe quelle autre. Une époque sur toute une séance : impact réel faible, mais c'est la dernière,
donc celle qu'on regarde.

### Correctif minimal

Sortir de la boucle **à la fin** de la fenêtre en cours plutôt qu'au milieu :

```python
        for f in range(n_fr):
            poll()
            if not running and f == 0:      # rien n'est encore parti : on peut couper net
                break
            draw(pos, cible)
            pygame.display.flip()
            ...
            clock.tick(int(refresh) + 5)
        # `running` peut être devenu False en cours de fenêtre : on la TERMINE quand même, le
        # marqueur est déjà parti et le moteur épochera 0,7 s après lui.
```

---

## M4 — Minor — `app.py` : deux imports migrés, aucun garde-fou contre le retour de l'ancien chemin

**Fichier : `src/research/app.py:966` et `:1289`** (`from core.errp_decoder import …`).

### Ce qui casse

Les deux imports pointent maintenant vers `core` et `src/research/errp_decoder.py` a bien disparu du
disque — le chantier est propre. Mais rien n'empêche le chemin inverse de réapparaître : le smoke de
`app.py` protège l'invariant oddball du P300 par une assertion sur le SOURCE (`app.py:1443-1447`) et
n'a aucun équivalent ici, alors que c'est le même risque et la même règle de projet (« quand un mode
migre dans le moteur, l'original se RETIRE »).

### Scénario concret

Quelqu'un restaure un `research/errp_decoder.py` depuis l'historique pour « tester une variante »
et remet l'import local dans `mode_errp`. Le démonstrateur pygame décode alors avec une pile,
le moteur avec une autre, et les deux affichent des scores plausibles. `python src/research/app.py
--smoke` : vert. Aucun test du dépôt ne compare les deux chemins.

### Correctif minimal

Ajouter une ligne au smoke d'`app.py`, à côté de l'assertion `blocs_melanges` existante :

```python
    for fonction in (mode_errp, page_errp):
        assert "research.errp_decoder" not in inspect.getsource(fonction), (
            f"{fonction.__name__} doit décoder avec core.errp_decoder — l'ErrP a migré dans le "
            f"moteur le 2026-08-18, l'original ne se maintient pas en double")
```

---

## Vérifications qui demandent une exécution (à lancer EN SÉRIE par le coordinateur)

1. `python src/research/errp_stimulus.py --smoke` — attendu **avant tout correctif** : `VERDICT : OK`,
   sortie 0, et un nombre de pas RÉELS entre 6 et 8. Confirme que la ligne 371 ne divise pas par zéro
   sur ce poste (M2.3).
2. Preuve de I5, **mutation à faire puis à défaire** : déplacer la l. 263 (`emet(...)`) au-dessus de
   la l. 257 (`pygame.display.flip()`), relancer `--smoke` — attendu : **`VERDICT : OK`, sortie 0**
   (le test ne voit rien). Puis rétablir.
3. Preuve de M2.2, **mutation à faire puis à défaire** : remplacer `ERRP_MAX_RUN_STEPS` par `10**9`
   l. 272, relancer `--smoke` — attendu : **`VERDICT : OK`, sortie 0**. Puis rétablir.
