# Re-revue D — verdict : `src/research/errp_stimulus.py`, `src/research/__init__.py` (`314fa2a`)

**Lecture seule — aucun programme exécuté.** Les vérifications qui demandent une exécution sont
signalées « À VÉRIFIER PAR EXÉCUTION » et laissées au coordinateur (en série).

Décompte : **9 ADDRESSED · 1 PARTIEL · 1 NON TRAITÉ · 0 RÉGRESSION**, plus **4 défauts NOUVEAUX**
(1 Important, 3 Minor).

| # | Gravité | Annoncé | Verdict | Preuve |
|---|---|---|---|---|
| C1 | Critical | ✅ | **ADDRESSED** | `errp_stimulus.py:400-405` (deux `tenir` de fin de course) + `:356` (écran avant le 1er pas) ; gardé par `:651-663` |
| I1 | Important | ✅ | **ADDRESSED** | `:135` `PAUSE_INTER_PAS_S = 0.45`, `:407` `tenir(..., PAUSE_INTER_PAS_S)` ; assertion `:647-650` (±20 %) |
| I2 | Important | ⚠️ partielle | **PARTIEL** (report honnête, garde-fou réel) | `:510-536` test différentiel 500 pas ; la fusion reste à faire |
| I3 | Important | ✅ | **ADDRESSED** | `:704-706` `--seed`, `:289` `random.Random(seed)`, `:375`+`:381` `t={ts:.3f}` |
| I4 | Important | ✅ | **ADDRESSED** | `:143-144` `ATTENTE_MOTEUR_S`, `:266-277` le message vrai, `:356` la piste statique, `:707-708` `--no-wait` |
| I5 | Important | ✅ | **ADDRESSED** — le test tient | `:415-424` `_empreinte_ecran`, `:560-576` instrumentation, `:628-639` les deux assertions |
| I6 | Important | ✅ | **ADDRESSED** | `research/__init__.py:13-16` (a) et `:17-21` « tous quatre » (b) |
| M1 | Minor | ✅ | **ADDRESSED** | `:147` `MIN_CELLS = 3`, `:206-212` la garde, `:539-542` le test, `:722` sortie 1 |
| M2 | Minor | ✅ | **ADDRESSED** | `seed=0` `:581/589/597`, `max_run_steps=2` `:589` + assertion `:666-669`, garde liste vide `:605-608`, min/max hors f-string `:658-659` |
| M3 | Minor | ✅ | **ADDRESSED** | `:366-367` `if not running and f == 0`, `:384-387` le pourquoi, test B3 `:592-598` + `:676-683` |
| M4 | Minor | ❌ reportée | **NON TRAITÉ** — report légitime, mais **personne ne l'a repris** | voir §M4 |

---

## Les trois corrections qui décidaient du reste

### 1. Le test de l'ordre `flip()` → `push_sample` (I5) — **il tient**

Vérifié par le raisonnement, ligne à ligne (`errp_stimulus.py:628-639`).

**L'instrumentation porte bien sur les deux gestes RÉELS**, pas sur un proxy : `pygame.display.flip`
est remplacé par `flip_trace` (`:560-567`) et `pylsl.StreamOutlet.push_sample` par `push_trace`
(`:569-573`), les deux écrivant dans **une seule** liste `trace` — donc l'ordre enregistré est
l'ordre d'exécution, pas deux horloges comparées après coup. Le patch est posé sur la CLASSE
`pylsl.StreamOutlet`, et `errp_stimulus` importe `StreamOutlet` par `from pylsl import …` : c'est le
même objet classe, l'appel réel passe donc bien par le patch. Restauration dans un `finally`
(`:599-601`).

**L'assertion (1) seule serait effectivement restée verte — la démonstration de l'implémenteur est
correcte.** Mutation : remonter le bloc `if f == 0: emet(...)` au-dessus de `pygame.display.flip()`
(`:369` / `:374-375`). Ce qui précède immédiatement le push devient alors la **dernière frame du
`tenir`** qui vient de s'écouler (pause inter-pas de 0,45 s, ou l'écran « nouvelle cible » de 0,9 s,
ou l'écran initial `:356`) — soit ~27 ou ~54 frames. `tr[i-1][0] == "flip"` est donc toujours vrai :
l'assertion d'ordre brut **ne peut pas** attraper cette mutation. Le commentaire `:621-624` le dit
avec le chiffre mesuré.

**L'assertion (2) mord, et sur tous les marqueurs.** `empreintes[-1] != empreintes[-2]` compare les
deux derniers flips avant le push :

- code correct → `empreintes[-1]` = la frame qui vient de dessiner le point à sa **nouvelle** case
  (et de faire disparaître la `note`), `empreintes[-2]` = la dernière frame du `tenir` → différentes ;
- sous la mutation → les deux sont des frames de `tenir` **consécutives**, donc pixel-identiques
  (`draw` n'y varie sur rien : `pas_total` et `erreurs_total` ne bougent qu'après le push,
  `have_consumers()` est constamment faux en smoke, la `note` ne change pas) → `False` pour
  **chaque** marqueur, d'où le `0/4` du rapport.

Deux détails qui auraient pu rendre le test creux et qui sont bons : `len(empreintes) >= 2` est
satisfait parce que **tout** premier pas est précédé d'un `tenir` d'au moins 0,45 s (~27 frames) —
c'est l'écran initial ajouté par C1 qui garantit ce ≥ 2 même pour le tout premier marqueur ; et le
point se déplace **toujours** d'exactement une case (`decide_pas` rebondit, ne fait jamais du
sur-place), donc l'empreinte change toujours dans le code correct — pas de faux rouge.

**L'instrumentation ne change pas ce qu'elle mesure.** Arithmétique de vérification : la fenêtre de
feedback fait 60 frames plafonnées par `clock.tick(65)` → ≥ 60/65 = 0,923 s ; plus `tenir(0,45)` →
plancher théorique ≈ 1,38 s. Le rapport mesure **1,42 s**, soit ~40 ms d'écart réparti sur ~89
frames ≈ **0,45 ms/frame** d'excédent total (empreinte comprise) — l'annonce « ~20 µs » est
optimiste d'un ordre de grandeur, mais l'ordre de grandeur réel reste sans effet : la borne haute de
l'assertion est 1,74 s, il reste ~0,32 s de marge, soit ~22 %. Le risque n'est donc **pas** un faux
vert, c'est un faux rouge sur machine lente → cf. **N4**.

**La seule mutation voisine que le test ne voit pas** : garder `emet` après le flip mais lire
l'horloge plus tôt (`ts` capturé avant `draw`, passé à `push_sample`). La trace n'enregistre que
l'instant de l'APPEL à `push_sample`, pas celui de `local_clock()`. Ce n'est pas une mutation d'UNE
ligne (il faut restructurer `emet`, qui lit l'horloge lui-même `:297`), donc je ne le compte pas
comme défaut — mais c'est la limite exacte du test, et elle mérite une ligne de commentaire.

### 2. Le Critical : la fin de course (C1) — **corrigé**, mais l'argument d'autorité est faux

`:391-405` intercale bien un écran statique **avant** la remise à zéro (`PAUSE_FIN_COURSE_S` = 0,7 s,
à la position finale) **et** un second **après** (`PAUSE_NOUVELLE_COURSE_S` = 0,9 s, note « nouvelle
cible »). La téléportation du point et le changement d'extrémité de la cible se produisent donc
0,9 s avant l'onset suivant, très à l'extérieur de la fenêtre d'époque `[-0,2 s ; +0,7 s]` du moteur
(`core/modes/errp.py`) et à l'extérieur de la ligne de base `[-0,2 s ; 0]`. Le défaut Critical est
fermé, et l'écran initial `:356` règle en prime le cas de la toute première course.

C'est gardé par deux assertions non triviales : `:651-654` (toute transition ≥ 2,08 s) et `:660-663`
(la PLUS COURTE transition > le PLUS LONG pas ordinaire) — la seconde ne peut pas être satisfaite
par accident si les `tenir` disparaissent.

⚠️ En revanche l'affirmation qui justifie le correctif — docstring `:64` « les mêmes deux écrans que
`errp_calibrate._run_block` et que `app.mode_errp` », commentaire `:399` « Mêmes durées, même
découpe », et le message du commit `314fa2a` — est **fausse pour `errp_calibrate`**, c'est-à-dire
pour la seule des deux qui produise le modèle. Voir **N1**.

### 3. La cadence (I1) — **1,45 s réel**, assertion resserrée, mais auto-référentielle

- SOA intra réel = `ERRP_FEEDBACK_S` (60 frames) + `tenir(PAUSE_INTER_PAS_S = 0,45)` = **1,45 s**
  (`:363-407`), identique à `errp_calibrate._run_block:217` + `:230`. ✓
- L'ancienne tolérance ±50 % autour de 1 s a disparu ; `:647-650` exige `|e − 1,45| ≤ 0,29 s`. Un
  retour à 1,0 s tombe à 0,95-0,97 s → hors fourchette → rouge (le rapport le montre). ✓
- La transition est bien mesurée **séparément** (`_ecarts` `:427-438`, via le 4e champ
  `debut_de_course` `:362`) et non plus noyée dans une moyenne unique. ✓

Réserve : `soa_intra` est **calculé à partir des mêmes constantes que la production**
(`:642`). L'assertion vérifie donc que la boucle honore `PAUSE_INTER_PAS_S`, pas que
`PAUSE_INTER_PAS_S` vaut ce que la calibration joue. Voir **N3**.

---

## Constatations non-ADDRESSED

### I2 — PARTIEL — le protocole reste écrit deux fois ; le garde-fou, lui, est réel

Le rapport annonce « partielle » et c'est exact. **Le garde-fou attrape bien une divergence entre
les deux copies, pas une divergence de l'une avec elle-même** — vérifié : `:517` construit **deux
générateurs indépendants** `random.Random(7)`, `:524-525` fait jouer un pas à chacune des deux
implémentations, et `:526` compare le **couple (position, étiquette)** de A à celui de B, pas A à un
attendu écrit sur place. Une modification du rebond, de la règle d'étiquette, du nombre de tirages
consommés ou du tirage de cible dans `errp_calibrate._decide_step`/`_new_goal` fait diverger les
trajectoires au premier pas concerné. La cible initiale est comparée explicitement (`:520`) ; les
cibles suivantes ne le sont pas directement, mais une divergence de cible inverse le sens du pas
suivant, donc se voit sur la position. Le test est donc **différentiel au sens fort**.

Trois angles morts, à connaître :

1. **Il ne couvre que le protocole des PAS, pas le protocole du TEMPS.** Les trois constantes
   `PAUSE_*_S` (`:135-137`) sont, elles aussi, une recopie de `_run_block` — et rien ne les compare
   (cf. N1 et N3). Or c'est précisément le TEMPS que le tour 2 vient de déclarer « paramètre du
   modèle, pas réglage de confort ».
2. **Il ne couvre pas le choix du taux.** Les deux côtés reçoivent le **même** `taux_erreur` en
   argument (`:524-525`) : remplacer le défaut `taux_erreur=ERRP_ERROR_RATE` par
   `ERRP_DEMO_ERROR_RATE` en `:188` laisse le test vert. La correction du tour 1 (l'émetteur prend
   0,28, pas 0,35) n'est donc gardée par aucune assertion.
3. **Coût :** `--smoke` importe désormais `research.errp_calibrate` (`:516`), qui tire numpy,
   scikit-learn/pyriemann (via `core.errp_decoder`) et `research.ui`. L'argument écrit trois lignes
   plus haut (`:512`, « il doit rester lançable à côté du moteur, sur une machine minimale ») ne vaut
   plus pour son propre autotest : sur une machine sans sklearn, `--smoke` meurt en ImportError. Rien
   n'est ouvert côté casque (aucun `BoardShim`, aucune instanciation d'`App`) et rien n'écrit dans
   `data/` : l'import est inerte. C'est un coût, pas un défaut.

**Scénario concret (ce qui reste ouvert).** Quelqu'un corrige la dégénérescence `--cells ≤ 2` dans
`errp_calibrate._decide_step` : cette fois le smoke de l'émetteur **rougit** (bien), mais il rougit
en disant « ne dérivez pas », pas « fusionnez ». La correction consiste alors à recopier le
changement une seconde fois — le défaut d'origine, avec un rappel. Le correctif complet reste celui
de la revue : `errp_calibrate._decide_step`/`_new_goal` deviennent des adaptateurs de 2 lignes autour
de `errp_stimulus.decide_pas`/`nouvelle_cible`, plus une assertion sur le source dans `app.py:_smoke`
à côté de celle de `blocs_melanges` (`app.py:1486-1490`).

### M4 — NON TRAITÉ — le report est légitime, mais la constatation reste ouverte dans le dépôt

Le report est justifié : le correctif vit dans `src/research/app.py`, propriété d'un autre
implémenteur (`4a219e9`), et cet implémenteur ne devait pas y toucher.

**Mais j'ai vérifié `app.py` après la vague, et personne ne l'a repris.** `app.py:1492-1532` a bien
reçu de nouvelles assertions ErrP (non-écrasement du modèle du 24 juillet, interdiction d'un
`ErrPModel.load` nu), mais **aucune** n'interdit le retour de `research.errp_decoder` :
`assert "_errp_charger" in src and interdit not in src` (`app.py:1527`) est vrai avec un import
local ressuscité. `mode_errp` importe aujourd'hui `from core.errp_decoder import ERROR`
(`app.py:994`) — un `from research.errp_decoder import ERROR` remis à la place passe tous les tests
du dépôt.

**Scénario concret.** Quelqu'un restaure `src/research/errp_decoder.py` depuis l'historique pour
« tester une variante » et remet l'import local dans `mode_errp`. Le démonstrateur pygame décode avec
une pile, le moteur avec l'autre ; les deux affichent des scores plausibles. `python
src/research/app.py --smoke` : vert. Le correctif est le même qu'annoncé, 4 lignes, et le patron
existe déjà juste au-dessus (`app.py:1486-1490`, `:1525-1529`).

---

## Défauts NOUVEAUX

### N1 — Important — « les mêmes deux écrans que `errp_calibrate` » : le second n'existe pas dans `errp_calibrate`

**Fichiers :** `src/research/errp_stimulus.py:61-69` (docstring), `:399` (commentaire), `:137`
(`PAUSE_NOUVELLE_COURSE_S`), et le message du commit `314fa2a`, contre
`src/research/errp_calibrate.py:204-231`.

`_run_block` place son `_track_hold(…, 0.9, note="nouvelle cible")` **ligne 212, AVANT le `while`** :
une fois par BLOC. Quand une course se termine EN COURS de bloc, la calibration fait exactement
ceci :

```python
        if pos == goal or steps >= ERRP_MAX_RUN_STEPS:
            _track_hold(app, n_cells, pos, goal, 0.7, ...)        # errp_calibrate.py:225  (le SEUL écran)
            pos, goal, steps = start, _new_goal(rng, n_cells), 0  # :228  téléportation + cible qui change
        else:
            _track_hold(app, n_cells, pos, goal, 0.45, ...)       # :230
    # retour en haut du while -> _decide_step puis _step(...) : l'ONSET est cette frame-là
```

Autrement dit **la calibration a, aujourd'hui encore, le défaut C1** : le point saute de 2 à 4 cases
et la cible change d'extrémité (p = 0,5) dans la frame horodatée du premier pas de chaque nouvelle
course. Le démonstrateur `app.mode_errp:1061-1067`, lui, fait bien deux écrans — mais 1,0 s puis
0,9 s, pas 0,7 + 0,9.

Conséquences, dans l'ordre d'importance :

1. **L'affirmation est factuellement fausse**, à l'endroit même où le fichier justifie son
   correctif, et c'est le **troisième** exemplaire de la même faute dans la même docstring : le taux
   d'erreur (corrigé au tour 1, `:41-49`), la cadence (corrigée au tour 2, `:51-59`), la découpe de
   fin de course (celui-ci). Le fichier est de la documentation exécutable : un étudiant qui écrit
   son émetteur Unity lira « mêmes deux écrans que la calibration » et ira vérifier.
2. **Le SOA de transition diverge de l'entraînement** : 1,0 + 0,7 = **1,7 s** en calibration,
   1,0 + 0,7 + 0,9 = **2,6 s** dans l'émetteur.
3. **La distribution des époques diverge** dans l'autre sens que le défaut d'origine : ~1 époque sur
   7 du jeu d'entraînement porte un transitoire plein écran à t = 0 ; **aucune** de celles que
   l'émetteur produit n'en porte. Le comportement de l'émetteur est le bon physiologiquement, mais
   l'argument « reproduire les conditions d'entraînement » — celui de tout le tour 2 — n'est pas
   tenu, et l'écart n'est signalé nulle part.

**Scénario concret.** Séance réelle : modèle entraîné par `errp_calibrate` (200 essais, 5 blocs),
moteur `--mode errp`, émetteur aux défauts. Le seuil du modèle est réglé sur les scores hors-pli de
la calibration (`core/modes/errp.py:166-169`), scores dont ~14 % viennent d'époques à transitoire.
En ligne, cette sous-population n'existe plus : la distribution des scores publiés est décalée par
rapport à celle qui a fixé le seuil, dans un sens qu'aucun test ne mesure. Sur un détecteur dont
l'AUC honnête est 0,776 (`docs/recette.md:560`), ce n'est pas négligeable — et l'étudiant qui
comparerait TPR de séance et TPR annoncé conclurait « le modèle ne généralise pas ».

**Correctif.** Deux options, l'une ou l'autre, pas les deux :
(a) **la bonne** — ajouter à `errp_calibrate._run_block:228` le `_track_hold(…, 0.9, note="nouvelle
cible")` après la remise à zéro, ce qui aligne les trois sites et supprime C1 là où il reste ; les
modèles déjà entraînés restent alors imparfaitement représentatifs, ce qui doit être écrit ;
(b) **le minimum** — corriger les trois phrases (`:64`, `:399`, et le commentaire de `:137`) pour
dire ce qui est : « `errp_calibrate` ne tient cet écran qu'en tête de BLOC ; l'émetteur le tient à
chaque course, à dessein — c'est un écart ASSUMÉ avec les conditions d'entraînement ».

### N2 — Minor (régression de comportement introduite par I4) — `--seconds` inférieur à 23 s produit une séance à ZÉRO marqueur, en silence, sortie 0

**Fichier :** `src/research/errp_stimulus.py:293` (`t_start`), `:356` (le `tenir` d'attente),
`:314-315` (`poll`), `:409-410`.

`t_start` est posé **avant** l'attente moteur. Avec le moteur lancé, `attente_initiale_s` vaut
`ATTENTE_MOTEUR_S` = 23 s ; si `--seconds` est inférieur, `poll()` met `running` à False **pendant**
ce `tenir`, le `while running:` n'est jamais exécuté, aucun marqueur ne part, `run` retourne `True`
et le programme sort en **0**. Aucune ligne de bilan n'est imprimée (l'émetteur n'en a pas).

**Scénario concret.** Terminal 1 : `python src/core/server.py --mode errp`. Terminal 2 :
`python src/research/errp_stimulus.py --seconds 20` (la valeur donnée en exemple dans la docstring,
`:100`). L'étudiant regarde une piste immobile 20 s, la fenêtre se ferme, l'invite revient sans
erreur, `echo $LASTEXITCODE` → 0, et `decoded_errp` n'a rien reçu. Avant cette vague, la même
commande produisait ~20 pas. Rien ne lui dit que sa durée est passée entièrement dans l'attente.

**Correctif minimal :** partir `t_start` **après** l'attente (`--seconds` compte le temps de
stimulation, ce que le nom promet), ou refuser au lancement un `--seconds` inférieur à
`ATTENTE_MOTEUR_S` quand l'attente est active, ou au minimum imprimer en sortie
`f"[errp-stim] fin : {pas_total} pas joués"` — un zéro visible vaut mieux qu'un silence.

**À VÉRIFIER PAR EXÉCUTION :** `python src/research/errp_stimulus.py --seconds 5 --windowed` avec un
**récepteur** (pas un moteur) abonné aux marqueurs — attendu : 0 ligne `[errp-stim] t=…`, sortie 0.
Sans consommateur, l'attente retombe à 0,9 s et le défaut ne se reproduit pas.

### N3 — Minor — aucun test n'arrime les trois durées à `errp_calibrate` : l'assertion de cadence mesure la boucle contre sa propre constante

**Fichier :** `src/research/errp_stimulus.py:642-643` (`soa_intra`, `soa_transition`) et `:647-663`.

`soa_intra = ERRP_FEEDBACK_S + PAUSE_INTER_PAS_S` est construit avec **la constante de production**.
Mutation d'UNE ligne : `PAUSE_INTER_PAS_S = 0.45` → `0.1` (`:135`). L'attendu devient 1,1 s, le
mesuré ~1,02 s, l'écart 0,08 s contre une tolérance de 0,22 s → **les 18 contrôles restent verts**,
`VERDICT : OK`, sortie 0. Le défaut I1 — le défaut exact que ce tour vient de corriger — se
réintroduit sans qu'un seul test bouge. Idem pour `PAUSE_FIN_COURSE_S` et `PAUSE_NOUVELLE_COURSE_S`,
dont le seul lien avec la calibration est un commentaire (`:135-137`).

**Scénario concret.** Un étudiant trouve la cadence lente (« 1,45 s, c'est long »), passe la pause à
0,1 s pour « en voir plus », lance `--smoke` par acquit de conscience : OK. Il branche le casque. Le
moteur publie des scores plausibles et faux — la panne canonique décrite deux écrans plus haut dans
le même fichier.

**Correctif minimal**, et le patron existe déjà dans ce dépôt (`app.py:1511-1515`, assertion sur le
texte source) : `_run_block` écrit ses durées en littéraux, donc

```python
    src_bloc = inspect.getsource(errp_calibrate._run_block)
    chk(f"{PAUSE_INTER_PAS_S}" in src_bloc and f"{PAUSE_FIN_COURSE_S}" in src_bloc,
        "les pauses de l'émetteur sont CELLES sous lesquelles le modèle a été entraîné "
        "(errp_calibrate._run_block) — sinon le moteur décode une distribution jamais apprise")
```

(à écrire en même temps que N1, puisque `PAUSE_NOUVELLE_COURSE_S` n'a volontairement pas d'équivalent
au même endroit dans `_run_block`.)

### N4 — Minor — deux assertions du smoke dépendent du budget horloge, avec ~20 % de marge, et l'instrumentation en consomme une part

**Fichier :** `src/research/errp_stimulus.py:587-589` (B2, `seconds=7.0`) et `:667-669`
(`len(journal2) >= 4`), plus `:647-650` (borne haute ±20 %).

La fenêtre de feedback est comptée en **frames** (60, `:363`) mais bornée par `clock.tick(65)`
(`:383`) : sa durée réelle W dépend de la machine. Le 4e marqueur de B2 tombe à
`0,9 + 3·W + 0,45 + 1,6 + 0,45` = `3,4 + 3W` — il faut donc **W < 1,2 s** pour que `debuts2[:4]`
existe. W nominal ≈ 0,92-0,97 s : la marge est de ~20-25 %, et c'est dans cette marge que vivent
l'empreinte d'écran, les deux `SysFont.render` par frame et le `print` par pas. Même famille de
marge pour la borne haute de l'assertion intra (1,74 s contre 1,42 s mesuré).

**Scénario concret.** Machine chargée (une compilation en fond), ou poste plus lent que celui de
l'implémenteur : `--smoke` sort en 1 avec `ÉCHEC le PLAFOND de pas (ici 2) termine une course qui ne
converge JAMAIS … ([True, False, True])` alors que le code est irréprochable. Un test qui crie au
loup sur une machine lente est un test qu'on finit par ignorer — et c'est celui qui garde le plafond
de pas.

**Correctif minimal :** allonger le budget de B2 (`seconds=9.0` donne ~50 % de marge, +2 s de smoke),
ou remplacer la borne temporelle par une borne en nombre de pas (couper B2 dès `len(journal2) >= 5`
via le `journal`), ce qui rend le test indépendant de l'horloge — le même geste que celui déjà
adopté pour B3 (coupure comptée en FRAMES, `:555-558`, et c'est le bon patron).

---

## Contrôles de non-régression menés au-delà des 11 constatations

- **Aucune ouverture de casque.** 0 occurrence de `brainflow`, `BoardShim`, `prepare_session` dans
  l'émetteur. L'import de `research.errp_calibrate` par `--smoke` (`:516`) est inerte : ce module
  n'instancie ni `App` ni carte au chargement, et `research/ui.py` ne fait qu'un
  `sys.path.insert`. ✓
- **`--smoke` exécute le VRAI `run()`**, trois fois, sous `SDL_VIDEODRIVER=dummy` posé avant tout
  import de pygame (`:474`, désormais remonté avant l'import de `errp_calibrate` — c'est ce qui
  empêche cet import d'ouvrir une fenêtre). Aucun sous-ensemble simulé. ✓
- **Aucune écriture dans `data/`** ; flux de test au nom distinct `MARKER_STREAM_DEFAULT + "_smoke"`
  dans les quatre appels (`:540, 580, 588, 596`). ✓
- **Sortie 1 sur échec** (`:722`), y compris pour un réglage refusé hors smoke. ✓
- **Frontière `research → core` respectée** ; français partout. ✓
- **`ERRP_ERROR_RATE` (0,28) reste le défaut de l'émetteur** (`:188`), distinct de
  `ERRP_DEMO_ERROR_RATE` (0,35) qui n'apparaît pas dans le fichier. ✓ (mais non gardé, cf. I2.2)
- **Le 4e champ du `journal` ne casse aucun appelant** : `errp_stimulus` n'est importé par aucun
  module de `src/` (vérifié) — seul son `__main__` et son `_smoke` appellent `run`. ✓
- **Les 8 `chk` d'origine sont tous conservés**, le 8e (écarts ≈ 1 s, ±50 %) étant remplacé par trois
  assertions strictement plus fortes. Aucune couverture perdue. ✓
- **Trou de couverture non signalé jusqu'ici :** la branche d'attente moteur (`:261-277`) n'est
  exercée par **aucun** test — les quatre appels de `run` en smoke passent
  `attente_consommateur_s=0.0`. Ni le message, ni `ATTENTE_MOTEUR_S`, ni le `tenir` de 23 s ne sont
  couverts. Je ne le compte pas comme défaut (l'attente exige un consommateur LSL, donc un second
  processus, ce qu'un smoke ne doit pas lancer), mais c'est à savoir : c'est le seul code de ce
  fichier qui ne soit vérifié que par relecture.
- **I4, dépendance à l'ordre de lancement** (à savoir, pas un défaut) : si l'émetteur démarre AVANT
  le moteur, `wait_for_consumers(5)` expire, le message « PERSONNE n'écoute » s'affiche et l'attente
  retombe à 0,9 s — le moteur jettera quand même ses 23 premières secondes. La prémisse du correctif
  (`_ouvre_marker_inlet` est appelé dès le premier tour de `run()`, `server.py:1200-1202`, donc
  l'inlet se résout pendant la chauffe) est en revanche **vérifiée** : la garde fonctionne bien dans
  l'ordre documenté par `docs/recette.md:589-593` (moteur d'abord).

## Vérifications qui demandent une exécution (coordinateur, en série)

1. `python src/research/errp_stimulus.py --smoke` — attendu : **`VERDICT : OK`, sortie 0, 18
   contrôles**. Relever la liste `intra` imprimée dans le message de l'assertion de cadence : elle
   doit rester **≤ 1,60 s** pour que N4 reste théorique (borne d'échec : 1,74 s).
2. Preuve de **N3**, mutation à faire puis à défaire : `PAUSE_INTER_PAS_S = 0.45` → `0.1`
   (`errp_stimulus.py:135`), relancer `--smoke` — attendu : **`VERDICT : OK`, sortie 0**, c'est-à-dire
   que la cadence hors protocole passe inaperçue. Puis rétablir.
3. Preuve de **N2** : `python src/research/errp_stimulus.py --seconds 5 --windowed` **avec un
   consommateur de marqueurs abonné** — attendu : aucune ligne `[errp-stim] t=…`, sortie 0.
