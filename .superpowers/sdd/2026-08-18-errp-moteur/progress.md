# SDD ledger — plan: docs/superpowers/plans/2026-08-18-errp-moteur.md

Chantier « l'ErrP sur le réseau ». 6 tâches. Travail directement sur `main` — workflow établi de
l'utilisateur, pas de worktree. BASE du chantier : `02ac710`.

## Ce qui rend ce chantier différent : le chiffre existait avant le code

La calibration réelle datait du 2026-07-24 et son résultat n'avait jamais été lu. Ré-entraîné le
2026-08-18 : **AUC 0,7763** (CV groupée par bloc), **p = 0,0099** sur 100 permutations, 200 époques
(62 erreurs / 138 bonnes, 5 blocs), seuil 0,5103 → **TPR 0,500 / TNR 0,855**.

**C'est le mieux validé des modes non publiés**, devant le P300 (0,714). Mais le point de
fonctionnement est modeste — une erreur sur deux attrapée, une bonne commande sur sept annulée — et
c'est ce fait qui structure la conception : **le flux publie son propre point de fonctionnement**.

## Pré-vol du plan (coordinateur, avant la tâche 1)

Deux prescriptions RETIRÉES du plan parce que le pré-vol a montré qu'il n'y avait rien à faire :

- **Le smoke de la console n'a rien à changer.** Il portait un compte en dur (`== 3`, puis `== 2`)
  que la revue du P300 a fait réécrire en identités dérivées de `registry.catalog()` : il s'adapte
  seul quand `external.ERRP` disparaît. Le plan le dit en toutes lettres — prescrire une édition
  inutile est ce qui a failli faire casser l'import du P300.
- **La ligne `sys.path` du décodeur déplacé ne bouge pas** : `research/` et `core/` sont à la même
  profondeur sous `src/`. Même fait non évident qu'au chantier précédent.

Et une confirmation qui a simplifié la tâche 3 : **`ErrPModel` prend DÉJÀ `tnr_target` et stocke
DÉJÀ `oof_scores_`/`oof_y_`**, avec le commentaire « pour régler le seuil a posteriori · recalcul
TPR/TNR à tout seuil ». Le réglage conçu à la spec est ce pour quoi le décodeur a été écrit.

## Journal

### Task 1 — le décodeur déménage, le modèle se ré-entraîne

- Implémenteur `abc06a18ed42d4ba4` (sonnet). **DONE** — commit `b35872a`.
- Revue (`a5462be271bf896d8`) : **spec ✅, 0 critique, 0 important**, 2 mineurs.

🎯 **Le ré-entraînement reproduit EXACTEMENT** : AUC 0,7763 · p 0,0099 · nfilter 4 · seuil 0,5103 ·
TPR 0,500 / TNR 0,855. Aucun écart. `data/errp_model.joblib` (24 juillet) intact, nouveau modèle
horodaté à côté — vérifié sur le disque par le relecteur, pas seulement déclaré.

⚠️ **DEUX erreurs de MON brief, trouvées par l'implémenteur en MESURANT, confirmées par le
relecteur qui a retracé la mécanique interne de `pickle` :**
1. Mon snippet définissait la classe de test DANS `_selftest()` → `PicklingError` (le `__qualname__`
   contient `<locals>`, et `_getattribute` lève **avant** toute consultation de `sys.modules`).
   Le test n'atteignait donc jamais le mécanisme qu'il prétendait éprouver.
2. Mon message de refus disait « **R**é-entraîne » alors que mon propre test cherchait
   « ré-entraîn » en minuscule — **le test aurait échoué sur mon propre texte.**

**Task 1: minor (deferred)** — le docstring de `modeles_disponibles` parle au présent d'un patron
que les tâches 2-4 n'ont pas encore câblé (se corrigera seul) · `decrire()["n_epoques"]` reste
`None` pour l'ErrP (`ErrPModel` ne pose pas `n_epoques_`, contrairement à `P300Model`) — clé gardée
pour la parité de forme.

⚠️ **Task 1: minor (deferred) — À REMONTER À LA REVUE FINALE, plus grave que son étiquette :**
`server.py:2083`, `_smoke_frontiere()` ne cherche que `research|console|pygame` dans son motif
d'interdiction — **pas `PySide6` ni `Qt` nommément**. Or la règle du projet est « ni pygame ni Qt
dans `core` ». Un import Qt direct dans le moteur passerait le test qui existe pour l'interdire.
Angle mort **préexistant** (le diff ne le touche pas), mais la garantie est plus faible que ce que
tout le monde croit — y compris moi quand j'écris « vérifié par un test » dans chaque brief.

**Task 1: complete (commits 02ac710..b35872a, review clean)**

### Task 2 — le mode : runtime, repos, rejet d'artefact

- Implémenteur `a8fbb16751d5f6b71` (sonnet). **DONE** — `df751f0`, puis correction `3e190ef`.
- Revue (`a4c694183eeee9ebe`) : spec ✅, 0 critique, **1 important**. Re-relecture
  (`aa75e957d0805c997`) : **les 2 ADDRESSED**, aucune casse, comptage recompté (42→51, +9).

⚠️ **L'IMPORTANT venait de MON brief, recopié verbatim** : `_est_artefact` comparait un σ d'époque
**BRUT** à un σ de repos **FILTRÉ** (`sigma_from_block` applique le passe-bande 5-40 Hz). Un
passe-bande ne peut que RETIRER de la puissance → σ_brut ≥ σ_filtré **systématiquement**, donc
l'erreur ne pouvait aller que vers le **sur-rejet**.

🔬 **Ce qui a fait basculer le diagnostic : l'implémenteur avait mesuré 1,9 et conclu que la marge
×4 l'absorbait. Le relecteur a reconnu dans ce 1,9 la valeur exacte de la seule perte de bande**
(√(125/35) ≈ 1,89) — donc la moitié du budget était consommée par un effet banal, AVANT toute
contribution du casque. **La mesure « rassurante » était le signal d'alarme.** Leçon : demander
d'où vient un nombre, pas seulement s'il tient dans la marge.

**La mesure comparée, décisive** (protocole jugé honnête par le re-relecteur, qui note que
l'implémenteur documente lui-même un piège de dilution rencontré et corrigé en construisant sa
preuve) :

| scénario | brut/filtré (avant) | **brut/brut** (retenu) | filtré/filtré |
|---|---|---|---|
| 10 µV de dérive ORDINAIRE <5 Hz, 30 tirages | **30/30 saines rejetées** | **0/30** | — |
| vrai clignement (60 µV, 0,3 s) | détecté (~18) | détecté (~10,5) | **RATÉ** (~2,2-2,9) |

⚠️ **L'alternative que j'avais écartée dans mon message de correction — filtrer les deux — aurait
rendu le détecteur AVEUGLE à l'artefact qu'il vise**, pour exactement la raison soupçonnée : un
clignement est une déflexion LENTE, largement sous 5 Hz. La mesure confirme le raisonnement.

Ajouté au passage : `_epoques_vues`, `taux_rejet` dans `state()`, et une alarme **dite une fois**
(verrou vérifié mécaniquement par le re-relecteur, indépendant des constantes).

**Task 2: minor (deferred)** — ⚠️ **la protection contre la rampe DC repose maintenant ENTIÈREMENT
sur les 15 s de chauffe, et ce chiffre n'a jamais été mesuré pour un σ NON filtré** : il est hérité
du SSVEP pour que les modes partagent leur repos. La preuve rouge-vert tourne avec `warmup_s=0.0`,
donc elle valide « même représentation », pas « 15 s suffisent ». **À vérifier au casque.**
· `rest_report["sigma"]` publie désormais un σ BRUT (~10 µV) là où il publiait du filtré (~1-2 µV) ;
le print terminal est relabellisé, `rest_report` non — vigilance si un écran l'affiche à côté du σ
d'un autre mode · le palier d'alarme à 50 % contredit son propre commentaire (« alerter TÔT ») :
une séance qui plafonne à 35-40 % de rejet, contact franchement dégradé, n'alerterait jamais ;
le re-relecteur suggère 25-30 %, le plancher de 10 échantillons étant bon · si `sigma_from_block`
rendait `None` en continu le repos resterait bloqué sans message dédié (sécurité correcte, silence
sur la raison).

**Task 2: complete (commits b35872a..3e190ef, review clean)**

### Task 3 — le réglage `tnr_target`

- Implémenteur `a659454506803a3b7` (sonnet). **DONE** — commit `67e121e`, 51→59 assertions.
- Revue (`ada57ee5ee5fe5f34`) : **spec ✅, 0 critique, 1 important**, 1 mineur.

⚠️ **QUATRIÈME erreur de mes briefs sur ce chantier, et c'est la MÊME que la revue du P300 avait
trouvée il y a deux jours** : mon code de test appelait `pick_threshold` **en direct**, sans jamais
instancier `ErrPRuntime` — donc il ne pouvait pas rougir sur la mutation que le pas suivant
exigeait, puisqu'elle ne touche que `__init__`. **Un test qui éprouve la fonction partagée, pas le
câblage qui l'alimente.** L'implémenteur l'a rejoué tel quel avec la mutation et vu qu'il RESTAIT
VERT ; le relecteur a retracé la mécanique à la main et confirmé indépendamment.

Détail qui corrobore l'authenticité de la preuve : sous la mutation, **le point à 0,85 reste vert
par coïncidence** (`0.85 == ERRP_TNR_TARGET`), et seuls les points à 0,70 et 0,95 divergent — motif
exact que le relecteur a prédit avant de lire la sortie.

**Task 3: fix round 1/5** — IMPORTANT : aucune garde sur `oof_scores_ is None`. Un modèle issu
d'une calibration DÉGÉNÉRÉE (< 10 époques, ou une classe à < 2 membres) a ses scores out-of-fold à
`None`, et `charger()` ne le détecte pas (il ne vérifie que la présence des méthodes) — donc ce
modèle **apparaît normalement dans la liste de la console**. `pick_threshold(None, None, …)` lève
alors `ValueError: zero-dimensional arrays cannot be concatenated` — **vérifié en isolation par le
relecteur, pas supposé**. ⚠️ **C'est une régression de CETTE tâche** : avant, le mode retombait sur
`threshold_ = 0.0` et démarrait. Correction demandée en DEUX endroits : le refus nommé dans
`charger()` (la porte qui décide ce qui apparaît dans la liste), et le second filet dans
`__init__` pour la course validation→démarrage.

**Task 3: minor (deferred)** — le rapport diagnostiquait un `TypeError` là où c'est un `ValueError`
une ligne plus loin (`np.asarray(None)` ne lève pas, il rend `nan`) : seul endroit du rapport où
l'implémenteur SUPPOSE au lieu de MESURER, transmis tel quel · la branche de repli de
`pick_threshold` est **mathématiquement inatteignable** en usage normal (`cand` contient toujours
`max+1e-6`, qui donne TNR=1,0), donc le test ne peut pas l'exercer — fait à connaître, pas défaut.

### ⚠️ INSTABILITÉ À REMONTER À LA REVUE FINALE — `[smoke-tampon]`

**Trois tâches de suite** l'ont vu échouer par intermittence dans `server.py --smoke`, et **deux
implémenteurs ont vérifié indépendamment, par `git stash`, que l'échec reproduit à l'identique sur
l'arbre non modifié** — donc préexistant à ce chantier, hérité de « marqueurs entrants ». Isolé en
processus seul il passe (~4 s de médiane).

Ce n'est pas un détail : **un test instable ruine l'autorité de toute la suite.** Chaque fois qu'il
rougit, l'implémenteur doit dépenser du temps à prouver que ce n'est pas lui — trois fois sur ce
chantier — et la fois où ce SERA lui, personne ne le croira. À traiter comme un vrai constat, pas
comme du bruit de fond.

Correction livrée : `362fee1`. Les deux filets nommés, prouvés rouge-puis-vert — **l'exception brute
a été retrouvée MOT POUR MOT** comme le relecteur l'avait prédite. Re-relecture (`a389d70b3abf16a5b`)
: **ADDRESSED**, aucune casse, comptages confirmés par grep direct (`errp.py` 59→61,
`errp_models.py` 18→21).

**Effet de bord trouvé par l'implémenteur EN RELANÇANT, pas en l'anticipant** : un fixture du test
voisin « 3bis » (la géométrie) n'était **jamais entraîné**, donc lui aussi sans scores hors-pli — le
nouveau filet l'interceptait avant le contrôle que ce test vise. Réparé en l'entraînant réellement.
Le re-relecteur a vérifié que **la seule ligne supprimée de TOUT le diff** est ce fixture, et que
l'assertion apparaît en contexte pur — donc inchangée. Le test éprouve toujours ce qu'il éprouvait.

**Task 3: complete (commits 3e190ef..362fee1, review clean)**

### Task 4 — le publieur, les métadonnées, le registre

- Implémenteur `a547080104671db39` (sonnet). **DONE** — commit `8b24ea4`, 61→63 assertions.
- Revue (`afcc8916f4fa934d1`) : **spec ✅, 0 critique, 1 important**, 1 mineur.
- Le registre annonce désormais **7 modes, dont 6 dans le moteur**.

⚠️ **Premier brief du chantier SANS erreur mesurable** — l'implémenteur le signale explicitement,
après trois tâches où mes consignes en contenaient.

**Vérifié solide par le relecteur** : le point de fonctionnement publié est **réellement calculé**
(`pick_threshold` sur les scores hors-pli de CETTE calibration) et pas recopié · `n_calib` est un
compte honnête (`oof_y_ = y.copy()`, donc l'effectif total) · `stream` corrigé pour la BONNE raison
(le garde-fou passe parce que le flux existe, pas parce qu'il a été affaibli) · la docstring
d'`external.py` intégralement reprise, **le défaut que la revue précédente avait trouvé sur ce même
fichier ne s'est pas reproduit** · une seule fonction construit les voies, et l'ordre matche
positionnellement `push()` des deux côtés.

**Task 4: fix round 1/5** — IMPORTANT : **la console est MUETTE pour l'ErrP, à DEUX endroits.**
L'implémenteur avait vu `live_views.py:308-313` (`PassiveView` ne lit que `sortie.get("z")`) ; le
relecteur a trouvé le second en vérifiant le même mécanisme ailleurs — **`grid.py:163-201`**, même
aiguillage par présence de clé, donc **l'aperçu vivant de la tuile reste vide** et le résumé retombe
sur le texte statique, alors que `grid.py:3-5` promet cet aperçu comme l'une des « quatre choses
qu'on veut savoir sans cliquer ».

⚠️ **ARBITRAGE DU COORDINATEUR, CONTRE la recommandation du relecteur — et sa position était bien
argumentée.** Il classait Important et non Critique, sur une distinction juste : le P300 rendu comme
un SSVEP **affirmait du faux** (seuil inventé, « CIBLE 3 · 0 Hz ») ; ici c'est un **silence**, pas un
mensonge. Et il a relu le plan entier pour établir que `live_views.py` et `grid.py` n'apparaissent
dans **aucune** des 6 tâches — donc hors périmètre déclaré.
**J'ai tranché de corriger quand même.** Motif : ce chantier prétend PUBLIER un mode, et « publié »
ne peut pas vouloir dire « le flux existe, la page et la tuile sont mortes ». La différence est
exactement ce que l'utilisateur découvre à l'écran — et il a déjà cru le produit terminé une fois,
devant des tuiles grisées. Exigé au passage : le rendu doit montrer le **point de fonctionnement**,
pas un verdict, et distinguer visuellement `-1` de `0`.

**Mineur replié dans la même correction** (il devient un piège au moment précis où on corrige le
défaut principal) : `errp.py:407` écrit `"artefact"` en français dans `output()`, là où
`ssvep.py:164` et `neuro.py:125` écrivent `"artifact"`, aligné sur le libellé de voie LSL.

Correction livrée : `d08ef71`. Re-relecture (`aa5c3a4fc2144f265`) : **ADDRESSED**, aucune casse,
comptages confirmés (`errp.py` 63→63, `console/app.py` 105→116, **aucune ligne `- … chk(`** dans le
diff).

**La méthode employée est la bonne, à retenir** : les 11 assertions ont été écrites **AVANT** toute
correction du rendu ; 7 ont rougi en capturant exactement le silence décrit (verdict vide,
avertissement statique du neuro, aperçu de tuile vide, résumé statique). Le relecteur a vérifié à la
main que les 4 qui ne rougissaient pas avaient chacune une raison légitime — au lieu de conclure que
le test était faible.

Les assertions portent sur des **sous-chaînes chiffrées exactes** (`"5.044"`, `"46%"`, `"93%"`) et
une égalité de liste, pas sur « un texte non vide ». Et l'aiguillage se fait par clé (`"error" in
sortie`), pas par une liste de modes recopiée : le relecteur a vérifié qu'aucune autre sortie de
mode ne porte cette clé.

**Task 4: complete (commits 362fee1..d08ef71, review clean)**

### ⚠️ À REMONTER À LA REVUE FINALE — un défaut VIVANT hérité du chantier précédent

**`grid.py:166` — la tuile P300 dimensionne ses barres avec le seuil du SSVEP.**
`span=max(sortie.get("threshold", Z_MIN), 1.0)`, et la sortie du P300 ne porte **aucune** clé
`threshold` → repli silencieux sur `Z_MIN`, la constante du SSVEP.

C'est **le même défaut que la revue du chantier « marqueurs entrants » avait classé CRITIQUE** il y a
trois jours (« la console affiche le P300 comme un SSVEP »)… mais **son correctif n'a couvert que
`live_views.ActiveView`, jamais `grid.ModeTile`.** Personne ne l'a vu parce que la revue finale
découpait par fichier et que `grid.py` n'était pas dans le périmètre de la vague de correction.

Confirmé sur le code actuel par l'implémenteur ET par le relecteur, indépendamment. **Ni aggravé ni
corrigé par ce chantier** — c'est du code livré et poussé qui affiche faux aujourd'hui.

Leçon de méthode : **une correction classée critique doit être vérifiée sur TOUS les sites du même
mécanisme, pas sur celui que le constat citait.** Le constat nommait `live_views.py` ; le mécanisme
vivait à deux endroits.

### Task 5 — l'émetteur et LE test d'alignement

- Implémenteur `aac2f4871790563b0` (sonnet). **DONE** — `527867e`, puis correction `431ca89`.
- Revue (`ae2de127a7e4ad9a2`) : spec ✅, 0 critique, **1 important**, 2 mineurs. Re-relecture
  (`a15366ddbde47a208`) : **les 5 ADDRESSED**, aucune casse.

🎯 **La démonstration que le chantier cherchait, en chiffres** : avec un `bandpass()` ajouté au
chemin d'épochage, **le pic reste EXACTEMENT à l'échantillon 50 sur les 8 voies** — seule l'amplitude
bouge (42,0 → 3,7763). Une assertion de POSITION serait restée verte. Seule l'égalité au CONTENU
l'attrape. Le relecteur a reproduit ces chiffres indépendamment, à la décimale.

⚠️ **CINQUIÈME erreur de mes briefs** : ma mutation littérale `bandpass(epoque, fs)` **plante** au
lieu de rougir — `epoch_from_stream` rend `(temps, voies)` et `bandpass` filtre le dernier axe en
supposant `(voies, temps)`, donc `filtfilt` lève sur `padlen=27` avant d'atteindre l'assertion, en
emportant toutes les suivantes.

⚠️ **L'IMPORTANT vise le test phare LUI-MÊME, et c'est un angle mort HÉRITÉ.**
La fixture plantait `eeg[i_pic, :] = 42.0` — **la même valeur sur les 8 voies** — donc permuter les
colonnes laissait `np.array_equal` VRAI. Le test tenait 3 de ses 4 promesses (traitement ajouté,
troncature, décalage), **pas l'ordre des voies que son commentaire revendiquait**.
Et **la même fixture avec le même commentaire trop généreux existait déjà dans `p300.py`** — le test
sur lequel reposait tout le chantier précédent. Corrigé dans **les deux** fichiers
(`np.arange(1,9)*10.0`), avec preuve rouge-vert sur un échange de voies.

Argument du re-relecteur, qui vaut d'être gardé : avec des valeurs **deux à deux distinctes** sur la
seule ligne non nulle, une permutation ne peut laisser le tableau inchangé que si c'est l'identité
(un cycle non trivial exigerait des valeurs égales) — donc **toute** permutation est attrapée, pas
seulement un échange de voisines.

**Task 5: minor (deferred)** — `_derniere_epoque_scoree` ne peut toujours pas représenter « le
dernier feedback quel qu'il soit » (perdu/artefact/scoré) : un futur besoin demandera un compagnon
dédié, pas seulement le renommage fait ici.

**Task 5: complete (commits d08ef71..431ca89, review clean)**

---

**Task 6 — documentation** (écrite par le coordinateur, sans sous-agent : mesuré trois fois qu'un
sous-agent n'apporte rien sur de la doc et coûte un tour de revue).

`docs/markers.md` a changé de nature : ce n'était plus la page d'un mode mais **le contrat de deux
décodeurs qui partagent un transport et rien d'autre**. D'où le recadrage d'entrée, les sections
`## P300 — les deux événements` / `## ErrP — un seul événement`, et un « avant que ça marche » qui
couvre les deux. La partie ErrP mène par ce qu'un client se trompera sinon : `-1` n'est pas `0`, et
`error = 1` est un indice, pas un verdict. Le tableau de compromis complet y est (96 %→24 %,
91 %→40 %, **85 %→50 %**, 81 %→60 %, 70 %→71 %) pour que personne n'ait à croire le point de
fonctionnement sur parole.

`docs/SPEC.md` §5 : ligne ErrP au vrai format. §14 : chantier marqué fait, avec **ce qui reste
dehors** — la calibration ErrP jouée par le moteur, et une **seconde personne mesurée** (tous les
chiffres du mode viennent d'une personne et d'une séance).

⚠️ **La dette qu'on croyait ouverte ne l'était pas.** Le §14 disait « sa calibration réelle n'a
jamais été faite » : elle datait du 2026-07-24 et **son résultat n'avait jamais été lu**. C'est
d'ailleurs tout le chantier : le nombre était sur le disque depuis trois semaines.

`docs/recette.md` : tests **1.15** (sans casque) et **2.8** (au casque). Le 2.8 ouvre par
« ⚠️ Lis ceci avant de commencer, sinon tu vas mal interpréter ce que tu vois » et dit qu'attraper
**cinq erreurs délibérées sur dix est le résultat ATTENDU** — sans ça un opérateur conclut à la
panne. Il note aussi la question ouverte qu'il peut trancher : 15 s de chauffe suffisent-elles
maintenant que la ligne de base d'artefact se mesure sur du signal brut.

`README.md` : ligne `decoded_errp`, « cinq modes publiés », et le paragraphe qui dit que l'ErrP
« attrape une erreur sur deux et annule une bonne commande sur sept ».
`CLAUDE.md` : l'appli pygame n'est plus le seul accès qu'au **c-VEP** ; trois autotests ajoutés.

**23 autotests lancés un par un (jamais en parallèle — mêmes noms de flux) : 0 échec**, aucun
python résiduel. `[smoke-tampon]` est passé cette fois — il reste instable, remonté à la revue.

Fausse alerte levée au passage : `errp_decoder.py` n'imprime pas de ligne `VERDICT :` (il imprime
`[errp] pipeline …`), mais il fait bien `sys.exit(0 if _demo() else 1)` — le verdict n'est pas jeté,
contrairement au défaut trouvé sur son jumeau P300. Divergence de format, notée mineure.

**Task 6: complete (commit b05292a, pas de revue par sous-agent — assumé)**

---

**REVUE FINALE DE BRANCHE** — base `9a30bec`, tête `b05292a`, 21 fichiers, 3256 insertions.
Cinq tranches par sous-système, **en lecture seule** (aucun relecteur n'exécute de python : cinq
programmes en parallèle sous les mêmes noms de flux LSL se répondraient entre eux) :
A `modes/errp.py` (1077 l., lu en entier) · B modèles+décodeur (41 Ko) · C publication+console
(38 Ko) · D émetteur (28 Ko) · E documentation (33 Ko). Les trois remontées inter-tâches
(tuile P300 `Z_MIN`, `_smoke_frontiere` aveugle à Qt, `[smoke-tampon]` instable) sont confiées à C.

**Résultat des cinq tranches : 7 Critical, 31 Important, 26 Minor** — sur du code qui avait déjà
passé six revues par tâche. Deux relecteurs ont trouvé **le même critique indépendamment** (la
calibration ErrP écrasait le modèle du 24 juillet), ce qui est le meilleur signal de sévérité qu'on
puisse avoir sans exécuter.

**Ce que j'ai vérifié moi-même avant de dispatcher quoi que ce soit** (les critiques sont la classe
d'affirmation qu'un relecteur lit de travers) : les quatre vérifiables par lecture directe sont
RÉELS. Le pire est une **régression par rapport au jumeau** : `p300.py:293` porte le commentaire
« l'instant du `round_end`, PAS `lsl_ts` », publie l'horodatage de l'ÉVÉNEMENT et le protège par un
test qui écarte volontairement les deux valeurs — l'ErrP publiait celui de la BOUCLE. Le patron
existait, avec sa justification écrite, et il n'a pas été suivi.

---

**VAGUE DE CORRECTION** — un implémenteur à la fois (ils exécutent des autotests, et deux programmes
sous les mêmes noms de flux se répondent entre eux). Les documents, je les ai faits moi-même en
parallèle : je n'exécute rien, donc pas de collision.

**F1 — `modes/errp.py` (commit `e56e45f`) : 11/11, aucune reportée.** Autotest 64 → 84 assertions,
onze mutations prouvées rouges une à une.
🎯 **Le chiffrage du critique n°2 est le résultat le plus utile de la revue.** Le σ du repos se
mesurait sur le tampon ENTIER (5,0 s) contre une époque de 0,9 s : biais de support **×2,01**, donc
le mode se comportait comme si `ERRP_ARTIFACT_RATIO` valait 8 au lieu de 4. Conséquence mesurée :
un clignement de **150 µV n'était rejeté que 9 % du temps, contre 100 %** une fois le support borné ;
le plancher de détection passe de ~250 µV à ~130 µV. Contrôles qui valident la mesure : bruit blanc
1,00 · marche aléatoire 2,31 (théorie 2,36) · rampe DC 5,56 (théorie 5,56).
⚠️ **Et voici pourquoi aucun test ne pouvait le voir** : sur le board synthétique de BrainFlow, ce
ratio vaut **0,98-1,00 sur 8 voies sur 8**. Le défaut était invisible à tout smoke ne portant pas une
fixture à dérive. L'ancienne preuve « rouge-vert » utilisait deux tampons distincts avec la dérive
renormalisée sur chacun — le seul cas de figure où le biais disparaît.
F1 a aussi ajouté `Param(key="stream_in")` à l'ErrP : le moteur lisait `rt.params["stream_in"]` pour
choisir le flux entrant, et `contract.validate` REFUSAIT la clé — le flux de marqueurs de l'ErrP
était gelé sur le défaut, et en `--mode errp,p300` l'ErrP maintenait l'inlet ouvert sur l'ancien nom,
ce qui cassait la voie de secours que l'aide du P300 PROMET.

**F2 — modèles, décodeur, calibration, appli (commit `4a219e9`) : 13/13, aucune reportée.**
⚠️ **Interrompu par une erreur d'API au moment d'écrire son rapport.** Vérifié par `git` avant de
conclure quoi que ce soit : 484 insertions présentes dans l'arbre, rien de commité, pas de rapport.
Repris depuis son transcript — contexte intact, aucun travail refait.
Le critique : `errp_calibrate.py` écrivait sur `ERRP_MODEL_PATH` fixe. `chemin_modele_horodate()`
côté ErrP, comme le P300. **Vérifié par exécution en dossier temporaire** : deux calibrations de
suite laissent deux fichiers, `modeles_disponibles` rend le plus récent en premier, et `data/` a
gardé ses mtimes d'origine (`errp_model.joblib`, 24/07 11:46) après tous les essais.
Second critique : l'appli chargeait le modèle sans passer par `charger()`, donc un modèle hérité y
produisait un traceback brut au lieu du message « ré-entraîne ». `_errp_charger()` aux deux entrées.
⚠️ F2 a **retiré une promesse** plutôt que d'inventer un remède : le message de refus prescrivait un
ré-entraînement depuis les `.npz` **qu'aucun code ne sait lire**. Le seul remède livré reste une
séance casque, et le message le dit maintenant.

**Documentation (par moi, non commité à cette heure)** — les 9 Important et les 7 Minor de la
tranche E. Trois changent le contrat, pas la prose :
- le tableau de compromis donnait les TNR **obtenus** sous un intitulé « ce que tu demandes ». Deux
  colonnes désormais, parce que le moteur choisit toujours un point **au moins aussi conservateur**
  que la demande : demander 95 % ne place pas SUR la ligne à 24 %, ça place à 24 % ou moins.
- la recette 1.15 lançait `server.py` (headless) puis demandait de lire une page de console : soit
  une case impossible, soit **deux moteurs publiant `decoded_errp` sous le même nom**. Montage
  refait autour de la console.
- changer « Bonnes commandes gardées » **recrée le flux et relance 23 s** : le `receiver.py` ouvert
  devient muet, et l'étudiant conclut que baisser le réglage a cassé le détecteur — l'inverse exact
  de ce que le test démontre.
`markers.md` promettait qu'une calibration n'écrase jamais la précédente : phrase laissée en suspens
jusqu'au retour de F2, puis écrite d'après ce que le code fait VRAIMENT, pas d'après l'intention.

**Dette ouverte, à traiter avant de pousser** — F2 a signalé dans `modes/errp.py` (fichier de F1,
non touché) deux commentaires devenus faux : `_open()` justifie `n_calib=len(oof_y_)` par
« ErrPModel ne pose pas `n_epoques_` » alors qu'il le pose maintenant, et `_sans_scores_oof()` récite
encore trois causes alors qu'il peut lire `echec_oof_`. Plus une fixture `epochs[:5]` portant le même
défaut que le Minor 10 de la tranche B.

---

**RE-REVUE CIBLÉE DE LA VAGUE** — 5 tranches en lecture seule, chacune avec ses constatations
d'origine, le rapport de l'implémenteur, et le diff réel. Consigne centrale : **ne pas faire
confiance au rapport**. Un rapport qui affirme une preuve rouge n'est pas une preuve rouge — c'est
la classe d'erreur qui a produit tous les défauts de cette revue.

| tranche | ADDRESSED | PARTIEL | NON TRAITÉ | RÉGRESSION | défauts NOUVEAUX |
|---|---|---|---|---|---|
| A — runtime | 11 | 0 | 0 | 0 | 3 (tous des commentaires) |
| B — modèles | 12 | 1 | 0 | 0 | 4 (dont 1 Important) |
| C — console/serveur | 9 | 2 | 1 | 0 | 5 |
| D — émetteur | 9 | 1 | 1 | 0 | 4 (dont 1 Important) |
| E — documentation | 16 | 0 | 0 | 1 | 8 (dont 3 Important) |

**Aucune régression de comportement dans le code** ; la seule régression est dans la documentation,
que j'ai écrite moi-même et que personne n'avait relue.

**Les trois dettes inter-chantiers sont payées et vérifiées** : la tuile P300 reproduit le calcul de
la page terme à terme (mêmes valeurs, `Z_MIN` sorti jusqu'à l'import) ; `_smoke_frontiere` attrape
les cinq formes d'import Qt avec zéro faux positif sur 32 mentions en prose ; et `[smoke-tampon]`
**teste encore `server.py`** — le double ne remplace que `__enter__`/`__exit__`/`get_new_data`,
restent réels le dimensionnement de `keep`, `ClockBridge.to_lsl`, les `vstack`/`concatenate` et les
vrais `sigma_from_block`/`common_mode`.

🎯 **Ce que la re-revue a rapporté que la revue ne pouvait pas voir** : la vague elle-même en
introduit.
- Le smoke de l'appli **écrit dans le vrai `data/`** sous un nom qui correspond à `errp_models.MOTIF`,
  et nettoie hors de tout `finally`. Antérieur à la vague, mais **aggravé par elle** : depuis que les
  modèles sont horodatés, un fichier de test oublié peut être proposé comme **modèle par défaut du
  moteur**.
- `[smoke-tampon]`, le test qu'on venait de réparer, **annonce vérifier une troncature qu'il ne
  vérifie pas** : 104 échantillons pour `keep = 1250`, donc retirer les deux `[-self.keep:]` de
  `server.py` le laisse vert.
- `_smoke_frontiere`, la garde qu'on venait d'élargir, **scanne sa propre docstring**, qui contient
  désormais `from PySide6.QtCore import QTimer` en exemple : un reflow du paragraphe la ferait
  échouer sur de la prose.
- L'émetteur affirme reproduire « les deux écrans d'`errp_calibrate` » : **le second n'existe pas**.
  `_run_block` ne tient son écran statique qu'en tête de BLOC ; en cours de bloc il téléporte le
  point dans la frame d'onset. ⚠️ **La calibration a donc encore le défaut qu'on vient de corriger
  dans l'émetteur** — et l'émetteur ne reproduit plus les conditions d'entraînement du modèle. Ne
  PAS aligner l'un sur l'autre sans décision : changer le protocole de calibration invaliderait le
  modèle du 24 juillet.

⚠️ **Et le défaut le plus important de tous est dans ma documentation, sur la valeur centrale du
projet.** `docs/markers.md` vendait le point de fonctionnement comme une garantie (« what you get is
always a little more conservative than what you requested »). Or `lsl_io.py` publie, dans le champ
que ma page invite à lire : `measured_on = "1 person; threshold picked on these same out-of-fold
scores, so tpr/tnr are optimistic"`. **F3 a changé ce champ PENDANT la vague** ; ma page a été écrite
contre l'état d'avant. L'AUC 0,776 est honnête (scores hors-pli) ; le **seuil**, lui, est choisi en
regardant ces mêmes scores, donc `tnr_measured ≥ tnr_target` est vrai PAR CONSTRUCTION sur les 200
essais du 24 juillet et sur eux seuls. Corrigé aux trois endroits (page publique, SPEC, recette) :
en séance, on annulera **plus** d'une bonne commande sur sept, pas moins.
