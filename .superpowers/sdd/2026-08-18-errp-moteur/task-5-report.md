# Task 5 — l'émetteur d'exemple, et LE test d'alignement — rapport d'implémentation

Statut : **DONE**
Commit : `527867e` — "Ship the ErrP stimulus, and pin the epoch by its content"
Base : `d08ef71` (HEAD de `main` avant cette tâche, tour de correction 1 de la tâche 4)

## Ce qui a été fait

Deux fichiers touchés (+424/-0), le rapport et le brief restant hors du commit, comme pour les
tâches 1 à 4.

**`src/research/errp_stimulus.py` (nouveau, 385 lignes)** — émetteur autonome sur le patron de
`p300_stimulus.py` : n'ouvre JAMAIS le casque, se lance dans un second terminal pendant que
`server.py --mode errp` tourne dans le premier. Reproduit le protocole curseur-vers-cible déjà en
service dans `research/app.py` (démonstrateur) et `research/errp_calibrate.py` (calibration) —
`ERRP_TRACK_CELLS=7` cases, `ERRP_ERROR_RATE=0.28` erreurs délibérées, `ERRP_FEEDBACK_S=1,0 s` de
tenue — via ses propres fonctions pures `decide_pas`/`nouvelle_cible` plutôt qu'en important
`errp_calibrate.py` (qui tire `research.ui`, non neutre pygame à l'import). Le marqueur publié est
EXACTEMENT `{"mode": "errp", "event": "feedback"}` — aucune cible, aucune vérité-terrain : c'est
justement ce que le moteur doit deviner depuis l'EEG, la publier casserait la BCI passive. Pas de
`valide_reglages` (à la différence du P300) : documenté comme un choix, pas un oubli — le moteur ne
lit que l'horodatage du marqueur, rien d'autre ne peut le dérégler.

`--smoke` exécute `run()` pour de vrai sur `SDL_VIDEODRIVER=dummy` (le geste flip→horodatage est
couvert), en deux parties : **A** fait tourner `decide_pas` 5000 fois SANS écran et compare le taux
d'erreur réalisé à `ERRP_ERROR_RATE` avec une marge à 5σ (loi binomiale) — la seule étendue où une
tolérance sur ce taux est honnête, vu que la boucle réelle (B) ne tient que ~7 pas en ~6,5 s (chaque
pas tient un `ERRP_FEEDBACK_S` complet). **B** vérifie donc autre chose sur le run réel : forme
exacte du JSON, horodatages strictement croissants, écarts inter-feedback dans `[0,5 ; 1,5] ×
ERRP_FEEDBACK_S` — jamais le taux d'erreur (trop peu d'échantillons pour trancher).

**`src/core/modes/errp.py`** :
- `ErrPRuntime.__init__` gagne `self._derniere_epoque = None` ;
- `_traiter_feedback` pose `self._derniere_epoque = epoque` au tout dernier moment avant le
  scorage — après le test d'artefact, juste avant `self.model.score(...)` — pour qu'un traitement
  inséré par erreur entre extraction et scorage se reflète DANS cette valeur ;
- `_selftest` gagne le test d'alignement (nouvelle section « 6. »), inséré juste après la section 5
  (compteurs), le dernier point qui touche encore `moteur.recent`/`recent_ts` à leurs valeurs
  d'origine — placé APRÈS pour ne pas invalider les tests à t=105..110 qui suivent dans le fichier.
  Code du test repris tel que donné par le brief (pic à 42,0 planté à un instant connu, comparaison
  `np.array_equal` contre la tranche brute).

## Preuve ROUGE-PUIS-VERT — et une erreur réelle trouvée dans la consigne

**Le premier essai littéral a CRASHÉ, pas rougi proprement.** La consigne dit d'ajouter
`bandpass(epoque, engine.acq.fs)` juste avant le scorage. Fait tel quel :

```
ValueError: The length of the input vector x must be greater than padlen, which is 27.
  (filtfilt, appelé depuis core/p300_decoder.py:41, depuis bandpass())
```

Cause : `epoch_from_stream` rend `(n_échantillons, n_voies)` = `(225, 8)` ; `bandpass()` filtre le
long de `axis=-1`, en supposant `(voies, temps)` — exactement la forme que `P300Model._prep`
transpose EN INTERNE avant d'appeler `bandpass` (`core/p300_decoder.py:94-95`). Appelé directement
sur l'époque brute comme littéralement écrit, `bandpass` filtre donc le long de l'axe des VOIES
(longueur 8, < padlen 27 par défaut de `filtfilt`) au lieu du temps (225) : `filtfilt` lève avant
même d'atteindre l'assertion d'alignement. **C'est une des erreurs réelles de la consigne** — pas
appliquée à moitié : corrigée pour la preuve par la version qui type-check, la même erreur plausible
mais avec la transposition qu'un développeur buterait dessus puis ajouterait :
`bandpass(epoque.T, engine.acq.fs).T`.

**ROUGE** (`python src/core/modes/errp.py`, avec cette version corrigée injectée) :
```
  ÉCHEC ⚠️ ALIGNEMENT : l'époque constituée par le runtime est EXACTEMENT la tranche brute du
        tampon — même position, même forme, même ordre de voies, et AUCUN traitement appliqué en
        chemin (un filtrage ajouté ici laisserait le pic au même échantillon et passerait une
        assertion de position)
[errp] VERDICT : PROBLÈME
EXIT_CODE=1
```
Une seule assertion rouge (les 63 préexistantes restent vertes) — pas de collatéral, pas de crash.

**Décalage mesuré, comme demandé** (script jetable reproduisant exactement la construction du test,
`bandpass(epoque.T, fs).T`) :
```
position du pic DANS l'époque brute (indice attendu = n_pre = 50)  : [50, 50, 50, 50, 50, 50, 50, 50]
position du pic APRÈS bandpass(), par voie                         : [50, 50, 50, 50, 50, 50, 50, 50]
toutes les voies au même échantillon que le brut (=50) ?             True
valeurs au brut[50]   : [42.0, 42.0, 42.0, 42.0, 42.0, 42.0, 42.0, 42.0]
valeurs au filtré[50] : [3.776, 3.776, 3.776, 3.776, 3.776, 3.776, 3.776, 3.776]
contenu identique (ce que teste _selftest) ?                         False
```
**Le pic reste EXACTEMENT au même échantillon (50) sur les 8 voies, avant et après filtrage** —
seule l'amplitude bouge (42,0 → 3,776, ≈9 % de l'original). Une assertion de position (« argmax au
bon échantillon ») serait donc restée VERTE malgré le double filtrage ; seule l'égalité de contenu
(`np.array_equal`) le détecte. C'est exactement la démonstration demandée.

**VERT** (bug retiré — import temporaire de `bandpass` et l'appel injecté, tous deux enlevés) :
```
  OK   ⚠️ ALIGNEMENT : l'époque constituée par le runtime est EXACTEMENT la tranche brute du
       tampon — même position, même forme, même ordre de voies, et AUCUN traitement appliqué en
       chemin (...)
[errp] VERDICT : OK
EXIT_CODE=0
```
Diff final relu : aucune trace du bug injecté (`git diff` ne montre plus que les commentaires qui
en parlent au conditionnel).

## Comptage des assertions (méthode excluant `def chk(cond, msg):`)

`grep -c "chk("` sur `errp.py` **avant** cette tâche (`git show HEAD~1:...`) : 64 occurrences − 1
pour `def chk(cond, msg):` = **63 sites**, confirmé identique au chiffre annoncé par le brief.
**Après** : 65 occurrences − 1 = **64 sites** → **+1**, exactement le nouveau test d'alignement.
Aucun site retiré ni affaibli.

(Note : le VERDICT du run vert affiche 66 lignes `OK`, pas 64 — la boucle de monotonie tâche-3
`for cible in (0.70, 0.85, 0.95):` exécute son unique site de `chk` trois fois à l'exécution ; même
mécanique que documentée aux rapports des tâches 3 et 4. Le comptage qui compte, statique, reste
63 → 64.)

## Tests lancés, dans l'ordre

Garde-fou avant chaque lancement : `Get-Process python` (PowerShell, forme propre avec try/catch) →
aucun processus à chaque contrôle.

1. `python src/research/errp_stimulus.py --smoke` → partie A (5000 pas, taux mesuré 28,0 % pour
   28 % visé, marge ±3,2 % à 5σ) verte, partie B (7 pas réels sur écran factice, JSON exact,
   horodatages croissants, écarts 0,93-0,96 s) verte. `[errp-stim] VERDICT : OK`, `EXIT_CODE=0`.
2. `python src/core/modes/errp.py` → **0 ÉCHEC**, `[errp] VERDICT : OK`, `EXIT_CODE=0`.
3. `python src/research/app.py --smoke` → inchangé par cette tâche (le démonstrateur ErrP de
   `app.py` pilote `errp_decoder`/`ErrPModel` directement, jamais `ErrPRuntime`) : `[app] smoke OK :
   menu + SSVEP + c-VEP (eCCA & rCCA) + P300 + neuro + ErrP(cal+démo) câblés (headless).`,
   `EXIT_CODE=0`.
4. `python src/core/server.py --smoke` → tous les sous-smokes verts, **`[smoke-tampon]` compris**
   (VERDICT OK dès ce lancement — l'instabilité mentionnée dans le brief ne s'est pas manifestée) ;
   `EXIT_CODE=0`.

## Inquiétudes

1. **Erreur réelle trouvée dans la consigne** (détaillée ci-dessus) : `bandpass(epoque,
   engine.acq.fs)` tel qu'écrit littéralement dans le Step 4 ne type-check pas contre ce dépôt
   (`epoch_from_stream` rend `(temps, voies)`, `bandpass` filtre `axis=-1` en supposant
   `(voies, temps)` — la forme que `P300Model._prep` transpose avant d'appeler `bandpass`, jamais
   après). Pris littéralement, ça fait planter `filtfilt` au lieu de rougir proprement sur
   l'assertion visée. Corrigé pour la preuve par la transposition (`bandpass(epoque.T, fs).T`),
   documentée dans le commentaire du code injecté puis retiré — ne change rien au fichier final,
   seulement à la façon dont j'ai PRODUIT la preuve rouge.

2. **Choix discrétionnaire non spécifié par le brief** : `self._derniere_epoque` n'est mis à jour
   QUE sur le chemin de succès (ni pour une époque perdue, ni pour un artefact) — il garde donc la
   valeur du dernier feedback SCORÉ avec succès si le feedback courant est rejeté. Le brief ne
   précise pas ce cas ; j'ai choisi de ne pas l'écraser à `None` sur les deux autres chemins, parce
   que rien d'autre ne lit cet attribut (seul le test d'alignement le fait, dans un scénario qui ne
   passe jamais par ces deux branches). Si un futur test veut vérifier l'ABSENCE d'update sur ces
   chemins, ce comportement devra peut-être être rendu explicite.

3. **Message de commit corrompu au premier jet** (deux passages de prose mal composés en
   l'écrivant), corrigé par `git commit --amend` avant tout autre travail — commit jamais partagé,
   aucune perte, mentionné ici par transparence plutôt que par nécessité.

4. **`.superpowers/sdd/.gitignore`** retrouvé réinitialisé à son `*` d'origine en tout début de
   tâche (régression connue et récurrente de ce dépôt, cf. rapports des tâches précédentes) —
   restauré via `git checkout` avant tout `git add`, absent du commit.

5. Rien d'autre trouvé à redire aux Steps 1-3 du brief (protocole, constantes, code du test
   d'alignement) : vérifiés contre le code réel plutôt que pris pour acquis, et tout correspondait.

---

# Tour de correction 1 — la fixture doit attraper un échange de voies

Statut : **DONE**
Commit : `431ca89` — "Make the epoch fixture catch a channel swap, in both alignment tests"
Base : `527867e` (le commit initial de cette tâche)

Le coordinateur a confirmé la conformité au brief d'origine, rapporté que le relecteur avait
reproduit indépendamment la trouvaille du tour précédent (mêmes chiffres à la décimale près :
pic à l'échantillon 50, amplitude 42,0 → 3,7763011283990444) — cinquième erreur réelle du
chantier — et signalé un angle mort dans l'assertion elle-même, hérité du brief et déjà présent,
identique, dans `p300.py` (code livré).

## Ce qui a été fait

**1. La fixture ne discriminait pas l'ordre des voies.** `eeg[i_pic, :] = 42.0` plante la MÊME
valeur sur les 8 voies : un échange complet de colonnes, y compris un simple échange de deux
voies, laisse ce vecteur inchangé valeur pour valeur, donc `np.array_equal` reste VRAI que le
runtime ait ou non respecté l'ordre des voies. Les deux commentaires affirmaient pourtant «
épingle position, forme, ordre des voies ET absence de traitement » — vrai sur trois points, pas
le quatrième.

**`src/core/modes/errp.py`** — fixture remplacée par `np.arange(1, 9) * 10.0` (10, 20, ..., 80,
suggestion du relecteur) : une valeur DISTINCTE par voie, qu'un échange de colonnes change bel et
bien. Commentaire de la section 6 et message de l'assertion réécrits pour dire EXACTEMENT ce qui
est désormais vérifié, pas par dictée — expliqué en mes propres termes pourquoi une valeur
répétée ne pouvait pas attraper ça et pourquoi une valeur distincte le peut. `self._derniere_epoque`
renommé `self._derniere_epoque_scoree` (init, assignation, bannière du test, lecture dans
`_selftest` — 4/4 sites) : le nom laissait croire qu'il reflète TOUT feedback, alors qu'il ne
reflète que le dernier SCORÉ (une époque perdue ou un artefact le laissent intact) — exactement le
piège que mon propre rapport du tour précédent avait flagué comme « choix discrétionnaire non
spécifié ». Les deux commentaires (init + assignation) le disent maintenant explicitement.

**`src/core/modes/p300.py`** — **code livré et poussé, touché au minimum** : la ligne de fixture
(même remplacement), la SEULE assertion dont le `42.0` codé en dur était directement couplé à
cette fixture (`epoque[n_pre, 0]` compare désormais à `10.0`, voie 0 = `1 * 10.0`), et le seul
commentaire sur-promettant (lignes ~1309-1314 avant ce tour). Rien d'autre dans le fichier n'a été
touché.

**2. Attribution corrigée dans `src/research/errp_stimulus.py`.** Le brief, mon rapport et mon
message de commit du tour précédent attribuaient `ERRP_ERROR_RATE = 0.28` au « démonstrateur » —
faux : `research/app.py::mode_errp` utilise `ERRP_DEMO_ERROR_RATE = 0.35` (`core/config.py:699`),
délibérément plus haut pour que la démo solo reste vivante malgré une dérive nette vers la cible
(son propre commentaire dans `config.py`). Seule la calibration (`errp_calibrate.py`) vise 0,28
(`config.py:698`, la valeur de littérature). La MÉCANIQUE reproduite (piste, rebond, `decide_pas`)
est fidèle aux deux sources ; seule l'attribution du TAUX était fausse. Docstring corrigée pour
attribuer 0,28 à la calibration, et j'y dis pourquoi cet émetteur garde quand même 0,28 par
défaut : il se veut la référence RÉSEAU du protocole (citée pour Unity plus haut dans le même
fichier), donc la valeur ancrée dans la littérature plutôt que celle réglée pour l'agrément d'une
démo solo. `--error-rate` reste libre. Le rapport et le message de commit du tour précédent
gardent leur texte d'origine (non réécrits, cf. inquiétude 3 ci-dessous).

## Preuve ROUGE-PUIS-VERT sur la nouvelle propriété (ErrP)

Fixture discriminante déjà en place. Injecté dans `_traiter_feedback`, juste avant la capture :
`epoque = epoque[:, [1, 0] + list(range(2, epoque.shape[1]))]` (échange les voies 0 et 1).

**ROUGE** (`python src/core/modes/errp.py`) :
```
  ÉCHEC ⚠️ ALIGNEMENT : l'époque constituée par le runtime est EXACTEMENT la tranche brute du
        tampon — même position, même forme, même ordre de voies, et AUCUN traitement appliqué en
        chemin (...)
[errp] VERDICT : PROBLÈME
EXIT_CODE=1
```
Une seule assertion rouge, aucune autre touchée, aucun crash.

**VERT** (mutation retirée) :
```
  OK   ⚠️ ALIGNEMENT : ...
[errp] VERDICT : OK
EXIT_CODE=0
```
`git diff` relu : aucune trace de la mutation dans le fichier final.

Pour le P300, conformément à la demande, pas de preuve rouge-vert séparée : son autotest complet
a simplement été relancé après le changement de fixture (résultat ci-dessous).

## Comptage des assertions (méthode excluant `def chk(cond, msg):`)

- `errp.py` : **64 avant, 64 après** — inchangé. Le nouveau site de la tâche 5 reste le seul ajout
  du chantier à ce jour ; ce tour ne fait que changer une VALEUR de fixture et un NOM d'attribut
  dans des sites déjà existants.
- `p300.py` : **87 avant** (88 occurrences de `chk(` moins la ligne `def chk`, vérifié avant toute
  modification), **87 après** — inchangé. Deux sites existants ont leur valeur/commentaire ajustés
  (le comparatif `42.0`→`10.0`, et le commentaire sur-promettant), aucun ajouté ni retiré.

## Tests lancés, dans l'ordre demandé

Garde-fou avant chacun : `Get-Process python` (try/catch) → aucun processus à chaque contrôle.

1. `python src/core/modes/errp.py` → **0 ÉCHEC**, `[errp] VERDICT : OK`, `EXIT_CODE=0`.
2. `python src/core/modes/p300.py` → **0 ÉCHEC** (87/87), `[p300] VERDICT : OK`, `EXIT_CODE=0`.
3. `python src/research/errp_stimulus.py --smoke` → inchangé fonctionnellement par ce tour (seule
   la docstring a bougé) : `[errp-stim] VERDICT : OK`, `EXIT_CODE=0`.
4. `python src/core/server.py --smoke` → les 17 sous-smokes verts, **`[smoke-tampon]` compris**
   (encore vert ce tour-ci), `EXIT_CODE=0`.

## Inquiétudes

1. **La correction du commentaire P300 cite cette tâche 5 (ErrP) comme origine de la trouvaille**,
   ce qui est correct chronologiquement (la fixture d'ErrP est la copie, celle de P300
   l'originale) mais vaut la peine d'être noté explicitement pour qui relira `p300.py` seul, sans
   le contexte de ce rapport.
2. **`self._derniere_epoque` → `self._derniere_epoque_scoree` : rien en dehors de `errp.py` ne
   référence cet attribut** (vérifié par recherche), donc ce renommage est sans risque pour
   d'autres fichiers — mais si un futur test ou une future page console venait à vouloir lire
   « le dernier feedback, quoi qu'il lui soit arrivé » (perdu, artefact, ou scoré), l'attribut
   actuel ne le permettrait toujours pas : il faudrait un compagnon dédié, pas seulement un nom
   plus honnête.
3. **Message de commit et rapport du tour précédent conservent l'attribution erronée
   d'`ERRP_ERROR_RATE`** au démonstrateur (signalé par le coordinateur). Choix délibéré de ne PAS
   réécrire ces textes déjà committés/rapportés : ce chantier n'a, à aucun tour précédent,
   réécrit un commit ou un rapport pour corriger une trouvaille de revue — chaque tour ajoute une
   correction, il ne falsifie pas l'historique de ce qui a été dit avant. Le TEXTE EN VIGUEUR (la
   docstring du fichier) est corrigé ; l'ARCHIVE (rapport et message de commit passés) ne l'est
   pas, et c'est assumé.
4. `.superpowers/sdd/.gitignore` revérifié en fin de ce tour : toujours intact.
