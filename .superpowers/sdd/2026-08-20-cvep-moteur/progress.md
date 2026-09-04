# SDD ledger — plan: docs/superpowers/plans/2026-08-20-cvep-moteur.md

**Chantier « le c-VEP sur le réseau »** — 6e et DERNIER mode du moteur. Base `c34e326`.
Travail directement sur `main` : workflow établi de l'utilisateur, trois chantiers de suite.

**Balayage préalable du plan — une contradiction trouvée et corrigée AVANT la tâche 1.**
La tâche 7 déclare `corr_min`/`margin` en `affecte_decodage=False`, alors que `contract.py`
documente ce drapeau par « False = le décodeur ne le lit jamais » — or le c-VEP les lit à chaque
décision. Poser `False` sans toucher au commentaire écrirait un mensonge dans le contrat, et chaque
relecteur aurait eu raison de le signaler. Le drapeau décrit en réalité « changer ce réglage
exige-t-il de RECONSTRUIRE le runtime », ce qu'en fait `server._set_params`. Plan amendé : la tâche 7
corrige le commentaire d'abord, et nomme la condition qui rend `False` honnête — **un réglage
`False` ne doit jamais être mis en cache dans `__init__`**, sans quoi le changer n'a plus d'effet,
en silence.

⚠️ **Accident évité au démarrage** : `scripts/sdd-workspace` a RÉÉCRIT `.superpowers/sdd/.gitignore`
avec son `*` d'origine, ce qui aurait rendu les carnets de ce chantier invisibles sans un mot. La
note laissée dans ce fichier au chantier précédent a permis de l'attraper immédiatement ; restauré
par `git checkout --`. À revérifier si un carnet disparaît.

---

**Task 1 — déménager le décodage dans `core/`** (commit `a0fd4ab`, 8 fichiers, +67/−17, les deux
fichiers reconnus par git comme des RENOMMAGES).

🎯 **Le résultat que la tâche cherchait : le modèle SURVIT.** `data/cvep_model.npz` (2026-07-21,
6 cibles) se charge à travers `core.cvep_decoder` — `n_targets=6 refresh=60.0 code_len=63
cv=0.4778` — et son SHA256 est identique avant/après
(`d66859856b91375ad2226bb24ee63b1f39e9a05c51ded69489f918d2720ec2de`), fichier non modifié.

⚠️ **Pourquoi ça n'allait PAS de soi** : les deux modes qui ont fait ce trajet avant lui ont perdu
leur modèle en route. Le P300 et l'ErrP écrivaient des pickles `joblib` référençant
`research.p300_decoder` / `research.errp_decoder`, disparus au déplacement — deux ré-entraînements,
et le second a failli coûter le seul modèle ErrP du dépôt. Le c-VEP écrit du `np.savez` de tableaux
purs, sans nom de classe : c'est ce qui le sauve, et c'est maintenant **mesuré** au lieu d'être
supposé. Le test l'épingle par une égalité bit-à-bit ET par l'absence de tout nom de module dans les
2 Ko d'en-tête du fichier.

Preuve rouge-puis-vert : mutation de `CVEPModel.save` (corruption du `template` écrit) → rouge sur
l'assertion bit-à-bit, sortie 1 ; retirée → vert, sortie 0.

4 autotests verts : `cvep_code.py`, `cvep_decoder.py`, `research/app.py --smoke`,
`server.py --smoke` (dont `smoke-frontiere`, qui confirme qu'il ne reste aucun import `research`/
`console`/pygame/Qt dans les deux fichiers déplacés).

**Deux écarts au brief, signalés par l'implémenteur au lieu d'être masqués** — aucun ne change le
résultat : l'erreur attendue à l'étape 2 est « No such file or directory » (le lanceur Python) et
non littéralement `ModuleNotFoundError` ; et l'insertion `sys.path` n'a eu besoin d'aucune
correction, `research/` et `core/` étant tous deux enfants directs de `src/` — mon brief supposait
une profondeur différente, à tort.

**Revue T1 : spec ✅, qualité approuvée, 0 constatation.** Le relecteur n'a pas cru le rapport : il a
relancé les 4 autotests, **rejoué la mutation à la main** (`template + 1.0` dans `save` → rouge
exact, exit 1 hors pipe, puis restauré → vert, `git diff` vide), rechargé le vrai modèle, et élargi
le grep de recâblage à `docs/` et `archive/`.

À garder : `smoke-frontiere` scanne par **AST**, pas par grep naïf — 29 fichiers, 0 violation.

**Arbitrage du relecteur, juste** : l'implémenteur a ajouté `sys.exit(0 if _selftest() else 1)`, que
le brief ne demandait pas. Ce n'est PAS du hors-périmètre : sans lui `cvep_decoder.py` sortait en 0
quoi qu'il arrive (défaut PRÉ-EXISTANT, vérifié à `c34e326`), donc son autotest était décoratif.
C'est le même défaut que celui trouvé sur `p300_decoder.py` au chantier précédent — il court dans ce
dépôt, il faudra le chercher ailleurs.

**Task 1: complete (commits c34e326..a0fd4ab, review clean)**

---

**Task 2 — le runtime du mode** (commit `4315d00`, `core/modes/cvep.py` créé + `config.py`).
20/20 assertions vertes, `registry.py` et `server.py --smoke` verts en non-régression
(`smoke-frontiere` : 30 fichiers, 0 violation). **4 mutations prouvées rouge→vert**, dont les 3 des
tests ajoutés au-delà du mandat.

⚠️ **DÉFAUT DANS MON BRIEF, trouvé par la mesure et non par la lecture.** La formule littérale que
j'avais écrite — `int(age * refresh) % code_len`, sans tolérance — **échoue sur son propre test de
bord de cycle** : `age` calcule à `1,0499999999999972` au lieu de `1,05`, donc la phase attendue à 0
sort à 62. C'est la même classe de bug que `registry._EPS_S`, DÉJÀ connue de ce dépôt, et je l'ai
quand même écrite. Corrigé par un epsilon `1e-9` nommé et documenté.

**Dépendance inter-tâches à ne pas perdre** : `stream_in` n'est PAS déclaré sur `SPEC.params` — ce
mode ne consomme pas encore `engine.markers_murs()`. ⚠️ Il DEVRA l'être : le chantier ErrP a montré
qu'un mode qui consomme des marqueurs sans déclarer `stream_in` voit son flux entrant GELÉ sur le
défaut (`contract.validate` refuse la clé) **et casse la voie de secours que l'aide du P300
promet** — `_libere_marker_inlet` ne lâche l'inlet que si aucun mode actif n'écoute. À porter dans
le dispatch de la tâche où le décodage se câble.

Deux protections ajoutées hors mandat strict, signalées au lieu d'être masquées : désaccord de
`code_len` entre modèle et config, et un 3e état muet sur `age < 0` (un marqueur dans le futur).

**Revue T2 : spec ✅, qualité approuvée, 0 constatation.** Trois des quatre mutations rejouées à la
main par le relecteur, chacune faisant rougir EXACTEMENT l'assertion annoncée. Code de sortie
vérifié **hors pipe**.

**Verdict sur l'epsilon (le point que je craignais)** : correction juste, et pour une raison
vérifiable — `_EPS_FRAME` n'intervient QUE dans la troncature finale
(`int(age * refresh + _EPS_FRAME) % code_len`), tandis que la péremption et `age < 0` comparent
`age` BRUT. Les deux logiques sont découplées, donc l'epsilon **ne peut pas** faire accepter une
référence périmée d'une frame.

**Verdict sur le 3e état muet** : ce n'était pas un ajout de comportement — la garde `age < 0`
figurait déjà dans le `phase_a` de mon brief ; seule sa couverture de TEST manquait. Combler un trou
de test sur une logique déjà mandatée est de l'hygiène, pas du hors-périmètre.

⚠️ **Point de méthode à retenir** : `git status --short data/` ne prouve RIEN sur ce dépôt, `data/`
étant entièrement gitignoré. Le relecteur a vérifié par l'HORODATAGE du fichier (mtime du
2026-07-21 inchangé après tous les runs du jour). À réutiliser partout où l'on veut prouver que
`data/` n'a pas bougé.

⚠️ **Question ouverte léguée à la tâche 4, du relecteur** : le marqueur c-VEP est une **horloge
continue par cycle**, pas un événement discret par essai comme le P300 et l'ErrP. Faut-il qu'il
partage la même sémantique d'inlet (`server._nom_flux_marqueurs`) que ses deux aînés ? À trancher en
câblant la consommation, pas avant.

**Task 2: complete (commits a0fd4ab..4315d00, review clean)**

---

**Task 3 — deux décodeurs, seuils MESURÉS** (commits `f79efac` puis `c0ffb06`). 10 autotests verts,
codes de sortie relevés hors pipe, `data/` intact. 20 mutations analysées, 18 rouges→vertes, 2
équivalentes et expliquées.

🎯 **LE RÉSULTAT QUI VALIDE LA SPEC** : sur le stimulus DÉCALÉ, le rCCA fait **exactement jeu égal
avec l'eCCA — 43/90 chacun**, sur les mêmes époques. La réfutation historique portait donc bien sur
les **codes Gold seuls**, et non sur la reconvolution. Rouvrir était justifié, et c'est maintenant
mesuré au lieu d'être argumenté.

🐛 **DÉFAUT LATENT TROUVÉ AU PASSAGE, et c'est la vraie trouvaille de la tâche** :
`RCCAModel.scores` recalait la phase **DANS LE MAUVAIS SENS** — mesuré 2/21 contre 21/21. Pourquoi
personne ne l'avait vu : la calibration n'époque qu'à la **phase 0**, donc `cv_` restait juste. Seul
le **pilotage en séance** aurait décodé à travers un alignement retourné, en publiant des scores
plausibles. Corrigé, et la convention est désormais épinglée à celle de l'eCCA par une assertion.

⚠️ **MON BRIEF ÉTAIT FAUX SUR LES SEUILS, et la mesure l'a rattrapé.** Je demandais « le quantile
qui garde 95 % des essais corrects » : c'est un critère de SENSIBILITÉ, alors qu'un seuil de décision
sert à REJETER LE BRUIT. Appliqué, il donnait 0,080/0,011 — **83 % des fenêtres de bruit pur
passent**, et la justesse à l'émission (48 %) égale celle qu'on a **sans aucun seuil** (47,8 %). Un
seuil qui ne change rien n'est pas un seuil. L'implémenteur l'a mesuré et me l'a renvoyé au lieu de
le livrer.

**Arbitrage rendu : 0,26 / 0,09** (71 % de justesse à l'émission, 27 % d'émission, 10 % de bruit
passé). Raison écrite dans le code : les deux excès échouent, mais **trop STRICT est une panne
VISIBLE** (« ça ne se déclenche jamais », trente secondes pour la voir, c'est le vécu du SSVEP)
tandis que **trop PERMISSIF est une panne INVISIBLE** (émission confiante sur du bruit). On part
strict ; la tâche 7 rend ces seuils réglables à chaud pour desserrer en séance.

Reproductible par une commande versionnée, en lecture seule :
`python src/core/cvep_rcca.py --seuils data/cvep_calib_last.npz`, qui affiche les DEUX couples avec
leur point de fonctionnement pour que le prochain compare sans refaire l'analyse.

⚠️ **Dépendance léguée à la tâche 4** : `core/modes/cvep.py` n'est PAS recâblé sur `cvep_models`.
Piège signalé par l'implémenteur — son fixture repointe la constante `CVEP_MODEL_PATH`, donc le
recâblage sans douleur est `cvep_models.modeles_disponibles(os.path.dirname(CVEP_MODEL_PATH))` ;
autrement le test lira le VRAI `data/`. La garde `code_len` a été gardée dans le mode plutôt que
déplacée (raison dans la docstring de `cvep_models`).

**Revue T3 : spec ✅ (avec la déviation que j'ai tranchée), 2 Important, 9 Minor.** Le relecteur a
relancé les autotests, rejoué la commande de seuils, et **retourné le signe de la phase lui-même** :
`EXIT=1` avec les deux chiffres exacts du rapport (2/9 et 1/9). Le correctif tient, et l'assertion
croisée avec l'eCCA est la bonne garde au bon endroit — c'est elle qui interdit à deux conventions
opposées de s'annuler à nouveau, ce qui est exactement ce qui s'était passé.

**Important 1** — le point de fonctionnement est mesuré à **1 cycle** alors que le mode décidera à
`CVEP_DECISION_CYCLES = 2`. Le rapport avait LUI-MÊME mesuré que la géométrie déplace les seuils
(q05 0,113/0,005 à k=2 contre 0,080/0,011 à k=1) sans en tirer la conséquence. Les trois chiffres
livrés ne décrivent donc pas le décodeur que les tâches 4-5 brancheront. → tour 1.

**Important 2** — le **43/90 de l'eCCA**, qui porte toute la justification de réintégrer le rCCA,
n'est reproductible par **aucune commande du dépôt**. C'est le reproche « un chiffre sans
provenance » retourné contre l'affirmation principale. → tour 1.

**Trois mineurs promus au tour 1** : `d["decoder"]` sans garde (traceback au lieu d'un ÉCHEC nommé,
durcissement fait ailleurs et oublié ici) · ⚠️ **`research/cvep_rcca.py:250` écrit puis supprime
`data/cvep_rcca_smoke.npz` dans le VRAI `data/`** — pré-existant, mais c'est la contrainte la plus
grave du projet et un smoke interrompu laisse le fichier · `allow_pickle=True` dans le module dont
la docstring vante l'absence de pickle.

**Task 3: minor (deferred)** — `_rejouer` lève en exception nue sur trois entrées plausibles ·
`--seuils` sans fichier retombe silencieusement sur le selftest et sort en 0 · un « regret » mal
attribué à `errp_models` · 5e divergence avec les jumeaux (`MOTIFS` tuple vs `MOTIF` str) absente de
la liste qui promet de toutes les lister · `cvep_models.py` (487 lignes) n'a **aucun importateur** et
ses autotests ne sont dans aucun smoke agrégé ni dans CLAUDE.md — rien ne rougira si quelqu'un le
casse avant le recâblage de la tâche 4.

**Les 4 divergences avec les jumeaux, jugées une par une : toutes justifiées.** Le refus « module
hérité » est INAPPLICABLE ici (`np.savez` de tableaux purs, mesuré) · le refus de stimulus n'a pas
d'équivalent chez les jumeaux et sa place est bien dans le catalogue, pas dans le mode (le fichier ne
doit jamais être PROPOSÉ) · `cv_loo` au lieu de `cv_auc` est honnête, `mi_models` diverge déjà avec
`cv_groupee` · la liste au lieu du tuple aligne sur les trois jumeaux.

**Task 3: fix round 1/5 (5 addressed, 0 open ; commits `c0ffb06`..`0398913`)**

Seuils **re-mesurés à k = `CVEP_DECISION_CYCLES` = 2** : **0,24 / 0,08** — 69 % de justesse à
l'émission, 35 % d'émission, 10 % de bruit passé, sur 37 décisions issues des 90 cycles.

🎯 **La phrase que je veux garder, parce qu'elle est le standard du projet** : l'écart de justesse
avec l'ancien couple « porte sur **2 décisions sur 37** : il n'est pas interprétable, et personne ne
doit s'en servir pour affirmer que l'un décode mieux que l'autre. Ce qui tranche ici est le **taux de
bruit**, estimé lui sur 300 fenêtres. » Écrite dans `config.py`, pas seulement dans un rapport.

`allow_pickle` **retiré** des deux sites après vérification que les trois fichiers réels se relisent
sans lui. Il n'apportait rien et faisait exécuter le contenu d'un fichier dans la fonction même qui
ouvre tout ce qui traîne dans `data/`. Un `.npz` à tableau d'objets est désormais refusé comme
« illisible ».

Le 43/90 de l'eCCA est devenu **reproductible** : `CVEPModel.hors_pli` ajouté en jumeau, et
`--seuils` imprime les deux décodeurs côte à côte, mêmes époques, même mécanique (k=2 : rCCA 24/37,
eCCA 22/37).

**Re-revue : les 5 ADDRESSED, aucune casse nouvelle.** Vérifié par mutation live (`allow_pickle`
réintroduit sur les deux sites → exactement 3 assertions rouges, dont l'effet de cascade annoncé) et
par **instantané de `data/`** — 43 fichiers, taille ET horodatage, avant et après la suite complète :
strictement identiques. La prudence de formulation n'a pas été durcie : aucun « équivalents » ni
« aussi bons » introduit.

Le défaut par défaut `RCCADecoder(n_cycles=…)` a été vérifié sur les **6 sites d'appel** du dépôt :
tous passent la valeur explicitement, aucun ne dépendait de l'ancien défaut.

**Task 3: minor (deferred)** — le tableau des mutations du rapport titre « 9 » et n'en liste que 7.

**Task 3: complete (commits 4315d00..0398913, review clean)**

---

**Task 4 — publication, compteurs, bout en bout** (commits `d8fd7f7` → `19118eb` → `39c249c`).
48 assertions dans le mode (32 au départ), console 147 (140), `data/` intact par horodatage.
⚠️ `src/core/modes/external.py` est **SUPPRIMÉ** : sa dernière entrée était le c-VEP.

🎯 **La preuve rouge la plus parlante du chantier.** Sous la mutation d'appariement score↔cible
(`lag_to_cmd` décalé d'un cran), le mode désigne la cible **VOISINE avec une confiance de 0,82** — et
**seul `modes/cvep.py` l'attrape** : `cvep_decoder`, `cvep_models`, `server --smoke` et
`console --smoke` restent tous verts. C'est ce qui prouve que le test porte quelque chose.
Ce qui le rend capable de rougir : l'indice publié vient DU DÉCODEUR et les scores sont relus par le
nom que le décodeur a attaché. Une recherche par `lag` refaite dans le mode aurait créé une SECONDE
table d'appariement, qui aurait continué de désigner la bonne cible — mutation indétectable.

**Choix de conception tranché par l'implémenteur, et il décide si le mode marche** : les marqueurs
sont demandés avec `post_s=0.0`, pas avec `marker_epoch_s` (2,1 s). Raison juste : `post_s` est un
**argument d'appel**, pas une propriété du mode, et il n'y a rien à attendre APRÈS un tic d'horloge.
⚠️ Sa seconde raison était fausse et a été réécrite : avec `post_s=2,1` la péremption ne serait
jamais atteinte avec un émetteur parfait, mais **sans la moindre marge** (âge dans [2,1 ; 3,15[,
seuil à 3,15) — le premier marqueur sauté bascule.

**Revue : spec ❌ sur un point, 3 Important, 6 Minor.** Le relecteur a exécuté **11 mutations** et en
a isolé **deux que personne n'attrapait**.

⚠️ **La lacune de spec : le VOTE GLISSANT n'existait pas dans le moteur.** `CVEP_VOTE_LEN`/
`CVEP_MIN_VOTES` n'étaient lus que par `research/app.py` — l'écran que la tâche 6 archive. La spec §5
l'exige. **Pourquoi j'ai tranché pour l'implémenter** malgré l'argument « le SSVEP du moteur n'en a
pas non plus » : l'écran pygame décode à la MÊME cadence sur la MÊME géométrie, PLUS un 2-sur-3 —
le moteur aurait donc été **strictement moins sélectif que la référence qu'il remplace**, et la
tâche 6 archive précisément cette référence pour que la séance casque **compare les deux sur la même
personne**. Une version plus bruyante par construction fausserait la seule comparaison chiffrée
prévue. Implémenté dans le runtime sur le patron de `mi.py`, avec deux `Param(kind="int")` que
`contract.validate` croise déjà (`min_votes > vote_len` → refus).

**Renommage** : `vote_non_conclu` ne comptait aucun vote. Deux compteurs désormais —
`sous_les_seuils` (aucun candidat → regarder le SIGNAL) et `vote_non_conclu` (des candidats qui se
contredisent → regarder la STABILITÉ DU REGARD). Les cinq compteurs **partitionnent** les fenêtres :
chacune en incrémente exactement un, vérifié ligne à ligne et par exécution.

⚠️ **La suppression d'`external.py` a vidé la branche « tuile grisée » de toute couverture** —
mesuré : retirer `setEnabled(False)` laissait la console à EXIT=0. Or c'est le point d'honnêteté de
l'interface, ce qui montre à l'étudiant les modes que le moteur ne sait pas faire ET pourquoi. Le
c-VEP était le dernier mode grisé ; en le publiant on a rendu invisible le mécanisme qui servira au
prochain. Fermé par une tuile bâtie sur un `ModeSpec` fabriqué.

🔁 **Le même défaut est revenu DEUX FOIS dans cette tâche, sur deux morceaux d'état différents** :
`_reset_rest` doit tout oublier — la référence de phase ET les votes — et les deux fois l'oubli était
écrit correctement mais laissé **sans test**. Mécanisme identique : on ajoute de l'état à un runtime,
on pense à le nettoyer, et on ne pense pas à prouver qu'on y a pensé. Les deux sont maintenant
épinglés, et l'assertion sur les votes est **comportementale** (ce que le mode publie après le repos)
plutôt qu'écrite sur `len(_votes)` — un test sur l'attribut laisserait passer une file vidée par un
autre chemin.

**Constatation léguée à la revue finale** : `core/modes/mi.py` porte **le même angle mort** — ses
tests vident `_votes` à la main au lieu de repasser par `begin_rest`/`_reset_rest`.

**Task 4: minor (deferred)** — `confidence=0.0` sur `vote_non_conclu` alors que le SSVEP publie
`max(scores)` dans le même cas · un motif inconnu devient `""` à l'écran mais s'imprime brut au
terminal · les compteurs ne vivent que dans `state()`, ni la console ni `server.py` ne les affichent ·
le rCCA n'est exercé par aucun test DU MODE (la colle mode-niveau est correcte aujourd'hui, non
garantie demain ; la branche est inatteignable, le seul modèle rCCA du dépôt étant refusé).

**Task 4: fix round 1/5 (6 addressed ; commits `d8fd7f7`..`19118eb`)**
**Task 4: fix round 2/5 (1 addressed + 2 docstrings ; commits `19118eb`..`39c249c`)** — re-revue :
les 3 ADDRESSED, `EXIT=1` obtenu sous mutation par le re-relecteur, aucune casse nouvelle. Il a
vérifié que la fixture ne se contente pas de poser un vote mais prouve qu'il est **réel et franchit
les seuils** — sans quoi l'assertion aurait réussi pour une mauvaise raison.

**Task 4: complete (commits 0398913..39c249c, review clean)**

---

**Task 5 — l'émetteur et LE test de phase** (commits `a4921e3` puis `9bf2953`). 50 assertions
(29 au premier jet), `app.py --smoke` vert, `data/` intact par horodatage.

🎯 **LE RÉSULTAT DE MÉTHODE DU CHANTIER : le critère hérité de l'ErrP est VIDE DE SENS ici, et c'est
mesuré.** L'émetteur ErrP vérifie que le flip précédant un marqueur est celui qui a CHANGÉ l'écran.
Sur du c-VEP, **l'écran change à 62 frames sur 63** — le critère serait donc vert quoi qu'on fasse.
Le relecteur a mesuré la propriété exacte : sur 63 positions, **1 seule** laisse l'écran identique à
la précédente.

La sonde livrée lit à la place **les pixels des six disques** pour identifier quelle frame du code
était affichée. Propriétés vérifiées indépendamment : une image identifie **32/63** positions, une
fenêtre de 2 les identifie **toutes**. Et la discrimination est prouvée plus fortement que le rapport
ne l'annonçait — en remontant `push_sample` au-dessus du `flip`, **6 marqueurs sur 7 satisfont le
critère d'ORDRE** (le piège exact), et **la sonde pixel rougit les six**, en lisant la position 62
au lieu de 0. **100 % de ce que le critère d'ordre laisse passer.**

⚠️ **TROISIÈME défaut de mes briefs sur cinq tâches.** Ma tolérance `max(pires) <= 1` reste **VERTE
sous une mutation `−1`** : le décalage systématique et le retard de la frame sautée se COMPENSENT,
le pire écart reste à 1. Les assertions livrées exigent **zéro là où zéro est dû**, ce qui mord dans
les deux sens — vérifié par le relecteur, `+1` → 5 échecs, `−1` → 3 échecs.

**Pire écart mesuré** sur 504 frames (8 cycles, une frame sautée à la 206) : **1 frame**, entièrement
contenu dans les **45 frames** entre le saut et le marqueur suivant. **0** sur les 207 d'avant, **0**
sur les 252 d'après, **0** sur 504 pour une course sans saut. C'est exactement ce que le marqueur par
cycle devait garantir : la dérive bornée à un cycle, et résorbée.

**Revue : spec ✅ 11/11, 2 Important, 6 Minor.**

⚠️ **L'important n°2 visait la séance que ce chantier prépare.** La consigne tournait toutes les
**4,2 s** alors que la fenêtre de décision PLUS le vote couvre **2,70 s** — donc ~65 % des
échantillons publiés après un changement étaient calculés sur une fenêtre **à cheval sur deux
cibles**, sans que rien ne prévienne celui qui dépouille. Quelqu'un suivant la recette 2.9 aurait
mesuré ~40 % et conclu que le décodeur ne marche pas, en regardant une période de transition qu'il
fallait jeter. **C'est très exactement le faux verdict que la recette existe pour empêcher**, et il
serait apparu à la première séance — après quoi on aurait cherché le défaut dans le décodeur.
Fermé des deux côtés : consigne portée à **8,4 s** (68 % exploitable contre 36 %) ET chaque ligne
`t=` imprime l'instant « compter à partir de ». Le 2,70 s est **arrimé à sa source par une
assertion** (`ModeRuntime.period_s()`), pas recopié en constante.

**Important n°1** : le bilan de fin — seul garde-fou de la 2e panne muette du fichier — n'était gardé
par aucune assertion. **Trois** mutations d'une ligne le laissaient vert (inverser le test de dérive,
neutraliser le compteur de frames sautées, supprimer le bloc). Un écran 144 Hz lancé en
`--refresh 60` aurait décodé contre une phase dérivant de ~8 %/cycle en silence.

Détail qui en dit long sur la méthode : écrire le passage de test a attrapé un défaut du **propre
harnais** de l'implémenteur — 3 cales posées, 2 comptées, le premier flip d'une séance n'ayant pas
de prédécesseur à mesurer.

**Décision de conception ratifiée par moi, pour éviter qu'on la relitige** : l'émetteur **affiche une
consigne**, ce que le brief ne demandait pas. Gardée — sans vérité-terrain, le test 2.9 ne pourrait
mesurer aucune justesse, on ne saurait pas ce que la personne visait. Même rôle que les erreurs
délibérées de l'émetteur ErrP.

**Task 5: minor (deferred)** — vérité-terrain seulement sur stdout, aucun fichier (patron maison,
mais c'est ici le seul mode dont la justesse en dépend) · le HUD affiche le refresh ANNONCÉ étiqueté
« fps », et `sautées` ne compte que les intervalles trop LONGS : un écran plus rapide qu'annoncé
affiche « 60 fps | sautées 0 » toute la séance · `ATTENTE_MOTEUR_S` est re-dérivé de
`SSVEP_WARMUP_S` au lieu d'être LU dans `SPEC.rest` comme l'affirme sa docstring · fragilité du
`chk` sur les consignes (exige ≥42 fps soutenus).

⚠️ **Ce que la revue déclare NON VÉRIFIABLE, et qui ira dans l'annonce finale** : le rendu réel n'a
jamais été affiché (taille des disques, lisibilité, position du bandeau — tout est inféré des ratios
de `ui.py`) · le verrouillage à la frame sur du vrai matériel n'a aucune mesure · la sonde pixel lit
`get_surface()` après `flip()`, ce qui est correct sous `dummy` (pas d'échange de tampon) mais **ne
se transpose pas à un pilote à double tampon matériel** · les deux programmes n'ont jamais tourné
ensemble.

**Task 5: fix round 1/5 (4 addressed ; commits `a4921e3`..`9bf2953`)** — 29 → 50 assertions.
**Task 5: fix round 2/5 (1 instabilité + 1 résidu ; commits `9bf2953`..`1995b22`)** — 51 assertions,
**sept exécutions consécutives vertes**, re-revue : ADDRESSED, trois exécutions à 0, aucune casse.

🎯 **La leçon de méthode de ce tour, et elle dépasse ce test.** Le contrôle de rejeu bornait ses
passages par un TEMPS RÉEL ; l'implémenteur a mesuré l'**ÉTENDUE** au lieu de compter les verts :
borné en temps la course rendait **291 à 298 images (étendue 7)**, borné en images **378 à chaque
fois (étendue 0)**. Or sur cette machine, la fenêtre 291-298 **ne contient AUCUN multiple de 63**
(63×4 = 252, 63×5 = 315, vérifié indépendamment par le re-relecteur) — donc le compte de consignes y
restait bon quoi qu'il arrive : douze exécutions bornées en temps sont sorties identiques, gigue
injectée comprise.

**« Le test ne devenait pas vert parce qu'il était bon, il l'était par chance de calibrage. »**
Relancer et compter les verts n'aurait donc RIEN prouvé — c'est exactement ainsi qu'un test instable
survit des mois, et ce projet vient d'en enterrer un qui traînait depuis cinq tâches. Le remède
retenu supprime la CAUSE (borne en images, déterministe par construction) au lieu de l'accommoder
(comparer des préfixes), et l'assertion exige désormais la **longueur** autant que le contenu.

**Task 5: minor (deferred)** — `max_frames` n'est pas exposé en ligne de commande : reproduire une
séance à l'image près depuis le terminal demande de passer par `run()` en Python. Délibéré, l'option
est à une ligne si la recette en montre le besoin.

**Task 5: complete (commits 39c249c..1995b22, review clean)**

---

**Task 6 — la calibration entraîne les deux** (`2dcaf0c` → `e3754fd` → `bd3b588` → `e734836`).
**Trois tours de correction**, 11 → 40 assertions. La revue initiale a rendu **3 Critical**.

🎯 **LE DÉFAUT LE PLUS GRAVE DU CHANTIER, et il visait ce que la tâche existe pour faire.**
L'écran nommait un gagnant dès que l'écart de justesse n'était pas exactement nul. Sur la vraie
séance : « gagnant rCCA », **64,9 % contre 59,5 %**. Or les décisions sont **APPARIÉES** — 37
décisions, 29 concordantes, 3 discordances eCCA seul contre 5 rCCA seul. **McNemar exact bilatéral :
p = 0,727.** L'écart est du BRUIT, et l'écran aurait conseillé un décodeur à un étudiant sur une
différence de **deux décisions**.
⚠️ **J'y ai contribué** : j'avais demandé « le chiffre du gagnant à k=2 » et relayé 64,9/59,5 comme
un résultat. C'est exactement le piège que la mémoire du projet documente depuis le MI — prendre un
écart de petits nombres pour une différence.
Corrigé : McNemar apparié, formule générale (`math.comb`), vérifié produire `0,7265625` par le bon
chemin — j'ai refait le calcul à la main (2 × 93/256 = 186/256). L'écran affiche désormais
**« indiscernables sur cette séance (McNemar p=0,727) — 8 décisions discordantes sur 37 »**. C'est
la réponse honnête ET la réponse juste : c'est parce que les deux se valent qu'on a rouvert le rCCA.

**Les deux autres Critical** : une séance INTERROMPUE truquait la comparaison (eCCA noté parmi les
cibles VUES, rCCA parmi les 6 codes → 71,1 % contre 51,1 % sur 3 cibles, « gagnant eCCA » sur 20
points fabriqués) ; et l'appariement lag→index de code n'était testé par rien (mutation : justesse
**1,0/1,0**, VERDICT OK, exit 0, le modèle nommant systématiquement la cible voisine).

⚠️ **UNE GÉOMÉTRIE DE MESURE FAUSSE, POUR LA TROISIÈME FOIS DU CHANTIER.** La tâche 3 mesurait ses
seuils à 1 cycle quand le moteur en utilise 2 ; la tâche 6 mesurait la justesse au même mauvais
endroit. Et cette fois ça changeait le verdict montré : à k=1 égalité parfaite 43/90 et aucun
conseil ; à k=2, 24/37 contre 22/37. Même famille que le double filtrage du P300 et la fenêtre de
repos de l'ErrP — **mesurer ailleurs que là où ça sert**, et obtenir un chiffre honnête qui décrit
autre chose.

🔁 **LE MOTIF CENTRAL DU CHANTIER, mis au jour par la re-revue du tour 2** : trois correctifs JUSTES
n'étaient protégés par AUCUN test. Muter le niveau de hasard vers `len(plan)`, ou remettre le chemin
de production par défaut dans le pilote archivé : les suites restaient **vertes**. Parce que les
smokes passent toujours un chemin explicite, ne tronquent jamais une séance, et n'atteignent donc
jamais le repli qu'on vient de réparer. **Un correctif juste mais non protégé est un correctif
temporaire** — c'est ainsi que le défaut d'écrasement est revenu après avoir déjà coûté 4 modèles au
MI. Fermé au tour 3 : un test permanent par cas, chacun exerçant `calibrate()` par un chemin que le
smoke n'atteignait pas.

⚠️⚠️ **DEUX ÉCRASEMENTS DU MÊME FICHIER EN UNE TÂCHE, le second en écrivant le test censé
l'empêcher.** `data/cvep_rcca_model.npz` (seul modèle Gold calibré au casque) détruit une première
fois par un smoke héritant du chemin de production, une seconde fois par une mutation de preuve.
**Cause du second, à retenir** : `CVEP_RCCA_MODEL_PATH` est importé **indépendamment** dans
`archive/cvep_rcca_pilot.py` et dans `research/cvep_calibrate.py` — **deux liaisons de nom
distinctes**, détourner l'une ne détourne pas l'autre.
**Récupéré les deux fois, et vérifié par moi** : `cv_ = 35,6 %` (valeur documentée), codes Gold
(6×63), 90 époques stockées, les 5 fichiers sources du 21/07 intacts, 43 fichiers au total. Le
format rCCA stocke ses époques et ré-ajuste au chargement — **c'est ce qui rend l'accident
rattrapable, et c'est une chance de conception, pas une sauvegarde.**

**Le garde a déménagé** : `empreinte_dossier` vit désormais dans `core/config.py`, à côté de
`DATA_DIR`, donc appelable depuis `archive/` — il était dans `research/app.py`, invisible de là où
ça a cassé. Branché sur 5 appelants dont `archive/mi_calibrate.py` et `mi_pilot.py`, le couple qui
avait déjà perdu 4 modèles ainsi.
⚠️ **Limite mesurée du garde, à porter à la revue finale** : sa forme `{nom: (taille, mtime)}` est
**aveugle à un créer-puis-effacer**. `server.py --smoke` crée et efface `data/mi_model_smoke.joblib`
dans le VRAI `data/` (attrapé par un guetteur à 5 ms) — le garde ne le verrait pas même branché.

**Task 6: minor (deferred)** — `CVEPModel.hors_pli` rend `(0,)` et `RCCAModel.hors_pli` rend
`(0, n_targets)` sur entrée vide : toujours divergents, contournés côté appelant (`len(sc) == 0`).
À trancher en revue finale : les deux jumeaux doivent-ils s'aligner ?

**Task 6: fix round 1/5** (3 Critical + 4 Important + 2 mineurs ; `2dcaf0c`..`e3754fd`)
**Task 6: fix round 2/5** (McNemar + 2 réserves + casse déplacée ; `e3754fd`..`bd3b588`)
**Task 6: fix round 3/5** (3 correctifs enfin protégés ; `bd3b588`..`e734836`) — re-revue : les 3
ADDRESSED, **double détournement COUVERT** (vérifié par lecture : les deux liaisons
`CVEP_RCCA_MODEL_PATH` plus `CVEP_MODEL_PATH`, dont dépend réellement le chemin horodaté),
mutation rejouée à exit 1, `data/` identique avant/après (43 fichiers, nom+taille+mtime).
⚠️ Le re-relecteur n'a PAS exécuté `archive/cvep_rcca_pilot.py --smoke` — bloqué par le
classificateur de permissions, cohérent avec ma consigne de lecture seule. Il le dit au lieu de le
laisser croire : son verdict sur ce fichier repose sur la LECTURE.

**Task 6: complete (commits 1995b22..e734836, review clean)**

---

**Task 7 — les seuils réglables à chaud** (`bfcb73b` puis `c8e5a81`). Revue : spec ✅ pleine, un
Important. Re-revue : les deux ADDRESSED, mutations rejouées, `lsl_io.py` 3×0.

**Le commentaire du contrat corrigé EN PREMIER**, comme le balayage préalable l'exigeait :
`affecte_decodage` ne dit plus « le décodeur ne le lit jamais » mais « changer ce réglage n'exige pas
de RECONSTRUIRE le runtime », avec la condition qui le rend honnête — **un réglage ainsi marqué ne
doit jamais être mis en cache dans `__init__`**. Mutation prescrite (remise en cache) rejouée par le
relecteur : `EXIT=1`.

🎯 **UNE CONSÉQUENCE QUE NI LA SPEC NI LE PLAN N'AVAIENT VUE, et c'est la trouvaille de la tâche.**
**Rendre un réglage ajustable à chaud rend CADUQUES les métadonnées qui l'annoncent.** LSL fige sa
description à la création du flux : un réglage qui bouge et une description qui ne bouge pas ne
peuvent pas coexister honnêtement.
⚠️ Le relecteur l'a formulé mieux que le rapport : **avant cette tâche, la péremption était
impossible PAR CONSTRUCTION** (changer un seuil exigeait un redémarrage → nouveau flux → métadonnées
fraîches). C'est la tâche 7 qui rend le problème réel pour la première fois — tension structurelle
de son propre but, pas une erreur.
Conséquence mesurée : `decoded_cvep` ne transportait **jamais** ses seuils, ni frais ni périmés. Ils
n'existaient que dans les métadonnées figées et dans `output()`, que **seule la console** sonde. Un
client Unity/Python/MATLAB — le public visé — n'avait aucun moyen de savoir contre quoi une décision
avait été prise.
**Le dépôt avait déjà résolu ça pour l'ErrP sans en tirer la règle** : publier le seuil COMME VOIE,
à chaque échantillon, pour qu'un enregistrement dépouillé sans sa description reste interprétable.
Appliqué : `decoded_cvep` = `target_index · confidence · score_0…score_5 · corr_min · margin`.
**Corrigé MAINTENANT et pas après** parce que la tâche 8 documente ce contrat : changer une forme
après l'avoir décrite est le meilleur moyen de livrer une documentation fausse le jour de sa sortie.

**L'Important** : `_open`, `_rest_step` et `_publish` lisaient encore le décodeur au lieu de
`self.params`, et **rien ne le protégeait** — reverter les trois ensemble laissait les trois suites
vertes. Deux scénarios réalistes : tourner un seuil pendant que l'horloge est périmée (aucun
`decide()` entre les deux) publie l'ancien ; démarrer le mode avec un seuil non défaut fait écrire
au flux le défaut du décodeur. **Encore le motif du chantier** : un correctif juste mais non protégé
est temporaire.

**Honnêteté de l'implémenteur à relever** : sur la mutation de `_publish` seule, **une de ses deux
assertions ne rougit pas** — les trois dernières fenêtres passant par `decide()` qui resynchronise.
Seule la lecture de la PREMIÈRE fenêtre (jamais décidée) est étanche. Il l'a signalé et gardé la
bonne comme preuve. Le re-relecteur l'a confirmé en rejouant.

**Task 7: minor (deferred)** — défaut unique `corr_min`/`margin` partagé eCCA/rCCA (rattrapable en un
clic ; `config.py` a mesuré que les deux vivent à la même échelle) · `console/app.py:830` garde dans
sa fixture l'ancienne liste à 8 voies, lue par aucun code mais ne décrivant plus la forme réelle ·
un échec **transitoire non reproductible** de `lsl_io.py` sur une assertion SSVEP non touchée, suivi
de 2 + 3 relances vertes (hypothèse : contention liblsl après ouverture de nombreux `StreamOutlet`
en rafale).

**Task 7: complete (commits e734836..c8e5a81, review clean)**

---

**Task 8 — la documentation et le script de la séance** (commit `b0f857c`, 6 fichiers, +755/−117).
**Suite complète : 40 commandes, 0 échec.** `data/` intact par horodatage (43 fichiers, plus récent
au 21/08 14:17:45). Deux coupures d'infrastructure en route, reprises depuis le transcript, zéro
travail perdu.

🎯 **DIX affirmations FAUSSES trouvées en vérifiant contre le code** — la raison d'être de la
consigne « ne recopie rien sans le confirmer » :
1. ⚠️ **Mon propre brief était faux** : un désaccord de `refresh` ne refuse pas le DÉMARRAGE — le
   marqueur est refusé, compté, annoncé par paliers, et **le mode continue en publiant `-1`**.
   Documenté avec « ne guette pas un plantage ».
2. Le « ~40 % si on compte tout » était le chiffre de l'ANCIEN réglage ; au réglage actuel c'est
   **32,1 %** (2,70 s de transition sur 8,4 s de consigne). Chiffre actuel écrit, l'ancien gardé
   comme histoire.
3-5. La recette mentait sur l'ordre des tuiles, sur « 3 tuiles grisées » (il n'y en a AUCUNE, les 7
   specs sont `status="moteur"`), et sur « 3 modes sur 6 pas sur le réseau ».
6. ⚠️ SPEC §5 disait « CINQ valeurs de `paradigm` » : il y en a **SIX**, `c-VEP` manquait — un
   client qui filtre sur ce champ ignorait le flux en silence. C'est le défaut exact que la doc ErrP
   avait corrigé pour cinq, reproduit à six.
7-8. SPEC §7/§13 (« c-VEP externalisé : bloqué ») et §3.1 (« P300 et c-VEP dans research/ ») :
   renversés/faux depuis les chantiers.
9. `examples/receiver.py` ne documentait que 5 suffixes sur 8 — la commande citée dans quatre
   documents n'existait nulle part dans le fichier que l'étudiant lit.
10. `cvep_calibrate.py` écrit « 64,9 % contre 59,5 % » sans dire qui est qui (c'est rCCA = 64,9).

Les **73 lignes `python …`** des six documents extraites et vérifiées : toutes existent.

⚠️ **Constatation transverse confirmée une 2e fois, pour la revue finale** : `server.py --smoke`
écrit puis supprime `data/mi_model_smoke.joblib` dans le VRAI `data/` — l'angle mort exact
(créer-puis-effacer) que `archive/README.md` documente pour `empreinte_dossier`. Un Ctrl+C
laisserait le fichier, que `mi_models` proposerait ensuite comme modèle.

**Doutes honnêtes du rapport, à porter dans l'annonce finale** : le 2.9 n'a JAMAIS été joué (écrit
contre le code) et son point fragile est le dépouillement MANUEL — un script de dépouillement est le
prochain geste utile · le biais A-B-A documenté est une déduction de `CVEP_CHANNELS`, pas une
mesure · le repère « ~60-65 % » est hors ligne, le moteur ajoute un vote que la mesure n'avait pas ·
la recette approche les 1000 lignes.

**Task 8: complete (commits c8e5a81..b0f857c, review clean — la revue de cette tâche est déléguée à
la revue FINALE : la doc est le contrat, c'est elle que la tranche E relira en entier)**

---

**REVUE FINALE DE BRANCHE** — base `c34e326`, tête `b0f857c`, les 8 tâches. Découpage par
sous-système, relecteurs en LECTURE SEULE (cinq programmes parallèles sous les mêmes noms de flux se
répondraient). Les reportés des 8 tâches sont dans ce registre, à trier par la revue.

**Résultat des 7 tranches : 8 Critical, 36 Important, 41 Minor** — sur du code ayant passé huit
revues de tâche et neuf tours de correction. Une fois de plus, les trouvailles majeures sont
INVISIBLES depuis une tâche isolée :

- **A-C1** : le vote glissant SURVIT à la perte de l'horloge — la première fenêtre après le retour
  de l'émetteur peut émettre une cible sur des votes arbitrairement vieux. (`_reset_rest` vide les
  votes, mais la PÉREMPTION de la référence ne les vide pas.)
- **B-C1** : `empreinte_dossier` — le garde de la contrainte la plus grave du dépôt — n'est
  lui-même éprouvé par AUCUN test. Un garde-fou dont rien ne prouve qu'il mord.
- **D-C1 = G-C1 (trouvé indépendamment par deux tranches)** : la règle de dépouillement du 2.9
  n'est exécutable avec AUCUN outil du dépôt — `receiver.py` calcule `ts + offset` et ne l'imprime
  JAMAIS. La clé de jointure n'existe nulle part.
- **E-C1** : l'ITR affiché en fin de calibration est DOUBLÉ (`cycle_s` = 1 cycle, justesse mesurée
  à k=2) : 48 bits/min « PROMETTEUR » affiché au lieu de 24 « FAIBLE ». **Quatrième géométrie de
  mesure fausse du chantier**, cette fois sur le chiffre-titre.
- **E-C2** : interaction entre deux correctifs de T6 — `codes_vus` réordonné PAR LAG, le rCCA
  apparie PAR POSITION ; coïncide uniquement à rotation 0, le seul cas testé. Tout modèle rCCA
  tronqué ou tourné est refusé par `charger` APRÈS l'annonce « modèles sauvegardés ».
- **F-C1** : l'échec « transitoire » de `lsl_io.py` était un **USE-AFTER-FREE** (5 sites) —
  `get_info()` rend un StreamInfo possédé, `desc()` un pointeur nu, le temporaire meurt en fin de
  ligne. Intact 5 fois sur 6. Mon hypothèse « contention liblsl » était FAUSSE et son correctif
  n'aurait rien réparé. C'est pourquoi on ne laisse pas vivre les échecs transitoires.
- **G-C2** : le A-B-A du 2.9 n'a ni protocole ni base de calcul — l'écran archivé n'a ni consigne
  ni vérité-terrain ni journal, et décode en boucle FERMÉE là où le test moteur est à l'aveugle.

**Verdict A sur le point escaladé : OUI AUX DEUX.** La branche rCCA du mode est devenue ATTEIGNABLE
(la calibration écrit des modèles rCCA que `charger` accepte, candidats au défaut juste après une
séance) et AUCUN test ne la traverse. Lecture statique propre — le correctif est de la FAIRE TOURNER
une fois, pas de réparer à l'aveugle. Réserves : à `CVEP_LAG_ROTATION != 0` le refus accuse à tort
un changement de config ; `CVEP_RCCA_CORR_MIN/MARGIN` sont MORTS côté moteur (`decide` impose le
couple eCCA).

**Rigueur statistique (tranche C)** : `_rejouer` — la commande de provenance du « jeu égal » —
compare deux pourcentages BRUTS, la comparaison que cette même branche a bannie dans `bd3b588` ·
les seuils 0,24/0,08 sont CHOISIS sur les 37 décisions qui mesurent leur point de fonctionnement
(même optimisme in-sample que le `measured_on` de l'ErrP) · « indiscernables » cité à k=1, la
géométrie que `config.py` déclare non représentative · l'assertion de convention de phase TIENT
(vérité terrain, 8 phases non nulles) mais c'est LA SEULE du dépôt — la mutation jumelle du bug
rCCA laisse `cvep_decoder.py` entièrement vert.

**Décision de vague** : 3 lots séquentiels (les correcteurs exécutent) — W1 core (cvep.py, lsl_io,
contract, config, server, console), W2 calibration+rCCA, W3 émetteur+receiver+docs. Critiques + les
importants nommés dans les dispatches ; le reste PARQUÉ ci-dessous avec ruling. UNE re-revue cadrée
de la vague ensuite, puis suite complète et push.

**Parked (rulings)** :
- sautees ne compte que les intervalles trop longs — le bilan de dérive couvre déjà les deux sens
  au niveau global ; HUD relabellisé en W3 suffit.
- Affichage des compteurs DANS la console (page de mode) — UI nouvelle, hors vague ; la recette
  bascule sur le flux `status` (W3). À reconsidérer après la séance.
- Compaction de la recette (~1000 lignes) — après la première séance réelle, pas avant.
- `MOTIFS`/divergences jumeaux non listées, `mi_models.decrire`, `with` sur les `load`,
  `CVEPModel.save` sans dossier vs jumeau — hygiène, aucun scénario de séance ; laissés au registre.
- Fenêtre fabriquée par le test de convention (mutation test+prod simultanée) — mutation de test,
  hors modèle de menace.

---

**VAGUE W1 — le cœur** (commit `523f0c5`). **12 points sur 12, aucun report.** `modes/cvep.py`
58 → 70 assertions, `config.py` 10 → 17, `cvep_models.py` 35. `data/` INTACT : empreinte complète
(nom · taille · ticks 100 ns) avant/après, **0 différence sur 43 lignes**, et `server.py --smoke`
n'y écrit désormais plus rien, **même transitoirement**.

⚠️ **MON ARBITRAGE SUR A-I1 ÉTAIT INSUFFISANT, et l'implémenteur l'a mesuré.** J'avais tranché
« capturer les seuils dans `decide()` ». Ça ne suffit pas : si la file de votes mélange des votes
jugés sous DEUX couples de seuils, leur moyenne peut rester sous le `corr_min` que la décision
courante applique. Il a ajouté la moitié manquante — vider la file au changement de couple — et sa
preuve rouge montre l'échantillon fautif : **confiance 0,783 publiée à côté de `corr_min = 0,816`,
sur la même ligne**.

🎯 **F-C1 : le use-after-free est DÉMONTRÉ, ce n'était pas un test instable.** Avec l'allocation
intercalée (`junk = [bytes(4096) for _ in range(2000)]`) : **3 échecs sur 3 AVANT** le correctif
(`no_decision_index : ''`), **3 succès sur 3 APRÈS**. Cause déterministe, symptôme aléatoire.
Mon hypothèse « contention liblsl » était fausse, et son correctif — attendre, relancer — n'aurait
**rien** réparé. C'est la raison pour laquelle ce projet ne laisse pas vivre un échec « transitoire ».

**A-C1** (le vote survivant à la perte d'horloge) fermé : une fenêtre non décodable pour raison
d'HORLOGE vide la file. Preuve rouge : sans le vidage, l'échantillon publie `target_index=2`,
`confidence=0,831` — **indiscernable d'une sélection franche**.
**B-C1** : `empreinte_dossier` a enfin ses tests (4 mutations, dont « réécrit à taille égale »).
**Escalade rCCA** : la colle mode-niveau traverse maintenant un vrai `RCCAModel` au moins une fois.

---

**VAGUE W2 — calibration et rCCA** (commit `352f3e7`). **12 points**, C-I2 à moitié (la seconde
moitié touchait `cvep_models.py`, hors périmètre → passée à W3).

🎯 **E-C1 : LE CHIFFRE QUE L'ÉTUDIANT RETIENT ÉTAIT LE DOUBLE DE LA VÉRITÉ.** `cycle_s` valait UN
cycle alors que la justesse est mesurée à **k=2** depuis ce chantier. Sur la séance de référence :

| | corrigé | ce qu'affichait HEAD |
|---|---|---|
| eCCA | 19,1 bits/min | 38,3 |
| rCCA | **23,8** | **47,7** |
| verdict | **FAIBLE** (contact ? regard ?) | PROMETTEUR |

Les 23,8 se lisent enfin contre les 22 du README : **la doc et le code disent la même chose pour la
première fois**. ⚠️ **Quatrième géométrie de mesure fausse du chantier** — après les seuils rCCA
(T3), la justesse de calibration (T6), et la fenêtre de décision. Même famille que le double
filtrage du P300 : *mesurer ailleurs que là où ça sert, et obtenir un chiffre honnête qui décrit
autre chose.*

**E-C2** : deux correctifs de T6 s'annulaient hors rotation zéro — `codes_vus` réordonné PAR LAG, le
rCCA appariant PAR POSITION. Testé uniquement à rotation 0, le seul cas où les deux coïncident.
Corrigé **avec un test à rotation ≠ 0** : c'est l'absence de ce cas qui rendait le défaut invisible.

**Effet de bord signalé par l'implémenteur lui-même** (bon réflexe) : son correctif rend FAUX le
paragraphe de `cvep_models.py:176-194`, qui explique qu'à rotation ≠ 0 le refus est « le cas ATTENDU
même sans rien avoir changé ». Il dirait maintenant à l'étudiant qu'un vrai défaut est normal.
→ passé à W3.

---

**VAGUE W3 — le dépouillement et les documents** (commit `1afb501`). 12 points, **25 commandes,
0 échec**. La **clé de jointure existe enfin** : `--log` JSONL opt-in côté émetteur (sans défaut, le
smoke ne peut rien écrire), horodatage LSL absolu côté récepteur, **même domaine d'horloge vérifié
de bout en bout**. Six affirmations fausses de plus trouvées en vérifiant — dont un test qui
annonçait `sans_reference` là où c'est `reference_perimee` qui monte.

**RE-REVUE DE LA VAGUE : les 8 Critical ADDRESSED, aucune casse nouvelle.** Tout recalculé
indépendamment — ITR 19,13 et 23,83 bits/min, rapport k1/k2 = **2,000000 exact**. La mesure du
use-after-free refaite dans les deux sens : **3/3 verts** avec le correctif, **3/3 rouges** sans.
`server.py --smoke` : **5 passages, 5 zéros** → l'hypothèse de la collision tient, pas de chasse.

⚠️ **Mais la re-revue a MESURÉ ce que W3 ne pouvait que soupçonner** : `cvep_stimulus.py --smoke`
rougit sur ses assertions de **cadence** quand la machine est chargée, et repasse 5/5 vert relancé
seul. Le D-I2 reporté passe de « soupçonné » à **établi**. Conséquence à retenir : la collision de
flux n'est plus le seul mécanisme plausible pour un rouge orphelin dans ce dépôt.
**PARKÉ avec ruling** : réel, non bloquant (aucun faux VERT possible, seulement un faux rouge sous
charge), et le correctif — borner ces assertions autrement que par le temps mural, comme la tâche 5
l'a fait pour le rejeu — appartient au prochain passage sur ce fichier. À traiter avant la séance si
quelqu'un le relance sur une machine chargée.

**SUITE DE CONTRÔLE lancée par le coordinateur** (pas déléguée) : **35 commandes en 3 tranches,
0 échec**, `data/` intact (43 fichiers, empreinte identique), aucun python résiduel.

---

# CHANTIER c-VEP TERMINÉ

**Base `c34e326` → `1afb501`.** 8 tâches, 9 tours de correction, une revue finale en 7 tranches
(8 Critical, 36 Important, 41 Minor), 3 vagues de correction, 1 re-revue. Le moteur publie **6 modes
sur 6**.

⚠️ **CE QUE LE CHANTIER NE PROUVE PAS** : que le c-VEP décode un vrai cerveau à travers le réseau.
Seul le SSVEP l'a fait. La séance casque couvrira d'un coup P300 (2.7), ErrP (2.8) et c-VEP (2.9).
