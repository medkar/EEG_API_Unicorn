# Task 2 — le mode ErrP : runtime, repos, rejet d'artefact — rapport d'implémentation

Statut : **DONE**
Commit : `df751f0` — "Give the ErrP a runtime, a rest baseline, and a verdict per feedback"
Base : `b35872a` (HEAD de `main` avant cette tâche, commit de la tâche 1)

## Ce qui a été fait

Un seul fichier créé : `src/core/modes/errp.py` (624 lignes), sur le modèle de forme
`src/core/modes/p300.py`, lu en entier avant d'écrire.

**`ErrPRuntime(ModeRuntime)`** :
- `pre_s`/`post_s` en **attributs de classe** (`ERRP_PRE_S`, `ERRP_EPOCH_S`), lisibles par
  `registry.check()` une fois ce mode enregistré (tâche 4).
- `__init__` charge le modèle (`core.errp_models.charger`), refuse en levant `ValueError` si
  absent, et fixe `self.seuil = self.model.threshold_` (le seuil APPRIS par la calibration — la
  tâche 3 le remplacera par un recalcul sur un réglage `tnr_target`).
- **Ajout non demandé littéralement par le brief, mais délibéré** : `_desaccord_geometrie`,
  jumeau exact de `P300Runtime._desaccord_geometrie`, refuse au démarrage un modèle entraîné à une
  autre `fs`/`pre_s`/`post_s` que ce que le runtime prélève — sinon des scores plausibles et faux,
  sans la moindre exception. `ErrPModel` porte déjà `fs`/`pre_s`/`post_s` (composés depuis
  `P300Model`), donc le contrôle est immédiat à écrire. Testé (3bis) avec un `ErrPModel(fs=125.0)`
  non entraîné, sauvé puis rechargé — refusé en nommant l'écart.
- `_rest_step`/`Rest(...)` : verbatim le patron du brief (chauffe 15 s, repos 8 s, σ par voie
  médian sur les fenêtres du repos).
- `tick()` : reprend `_jeter_marqueurs_de_chauffe` de `p300.py`, élargi à `("warmup", "rest")` —
  ici le repos dure 8 s (pas 0 comme le P300) et c'est PENDANT lui que la référence d'artefact se
  mesure, donc le piège du critique n°2 de la revue P300 y est encore plus probable.
- `_run_step`/`_traiter_feedback`/`_est_artefact`/`_publish` : verbatim le code du brief (Steps
  4-5). Un feedback perdu ou rejeté publie toujours `-1`, jamais `0`.
- `state()` expose `epoques_perdues`/`artefacts`/`marqueurs_chauffe`, même filet que `P300Runtime`.

**`SPEC = ModeSpec(...)`** : `status="moteur"`, un seul `Param` (`model` — PAS de `stream_in` : le
plan lui-même qualifie ce réglage de « cosmétique » dans sa note sur la tâche 3, et rien dans le
code de la tâche 2 n'en a besoin, l'inlet retombant sur `MARKER_STREAM_DEFAULT` en son absence).
`stream=None`, pas de `channels` : `DecodedErrPPublisher` n'existe pas encore et ce mode n'est pas
dans `registry.MODES` — les deux sont explicitement le travail de la tâche 4, qui modifie ce même
fichier (le plan le liste noir sur blanc). `calibration=Calib(kind="natif", ...)`, repris
d'`external.ERRP`.

## Comptage des assertions (méthode excluant `def chk(cond, msg):`)

`grep -n "chk(" src/core/modes/errp.py` rend 43 lignes ; moins 1 pour la ligne `def chk(cond,
msg):` = **42 sites d'assertion**. Toutes s'exécutent exactement une fois (aucune boucle
`for ... in (...)` autour d'un `chk`), donc 42 lignes `OK`/`ÉCHEC` à l'exécution aussi — confirmé
en comptant les lignes du run VERT (42 `OK`, 0 `ÉCHEC`).

Elles couvrent : le refus sans modèle (avec la bonne aide) ; la prise du modèle une fois présent ;
le contrat (`pre_s`/`post_s` classe, `marker_epoch_s`, `Rest`, `Calib`, `status`/`stream`) ; le
refus d'un modèle de géométrie étrangère ; la chauffe ET le repos qui consomment et comptent les
marqueurs, avertissement dit UNE fois sur les deux phases ; le repos qui conclut avec un σ par voie
sur 8 voies ; le chemin réel (vrai modèle entraîné) qui respecte le contrat sans qu'on juge lequel
des deux verdicts il rend ; la logique score/seuil sur un faux modèle à score connu (au-dessus ->
1, en-dessous -> 0) ; l'époque perdue (`-1`, `artefact=0`, modèle NON consulté) ; l'époque artefact
(`-1`, `artefact=1`, modèle NON consulté) ; un événement inconnu ignoré sans publication ; **deux
feedbacks à 100 ms d'écart qui publient chacun leur verdict** (preuve directe que la période
réfractaire n'est pas appliquée par le moteur) ; le flux qui ne se tait jamais (7 feedbacks envoyés
= 7 lignes publiées) ; `state()` qui expose et reflète les trois compteurs.

## Tests lancés, dans l'ordre

Garde-fou avant chaque lancement : `Get-Process python -ErrorAction SilentlyContinue` — vide à
chaque fois (aucun moteur, aucune appli qui traîne).

```
python src/core/modes/errp.py
```
`[errp] VERDICT : OK`, `EXITCODE=0` (42/42 assertions `OK`).

```
python src/core/server.py --smoke
```
Un premier lancement a échoué sur `[smoke-tampon]` (« cadence médiane 0.02 ms attendu 4.00 ms »),
précédé dans le log de `data_receiver.cpp ERR| Stream transmission broke off ... re-connecting`
— un incident BrainFlow/synthétique en temps réel, sans rapport avec ce fichier (`errp.py` n'est
importé ni par `server.py` ni par `registry.py` à ce stade du chantier — `git diff --stat` confirme
que seul `src/core/modes/errp.py` a changé). Relancé aussitôt : **VERDICT : OK** sur les 17
sous-smokes, `[smoke-frontiere] 0 violation(s) de frontière` (donc aucun import interdit dans
`errp.py`), `EXITCODE=0`. Aucun processus Python résiduel avant ni après (`Get-Process python`
vide dans les deux cas).

## Mes inquiétudes

1. **`_est_artefact` compare un σ RAW à un σ FILTRÉ, et c'est le code du brief, repris verbatim.**
   `_sigmas_repos` vient de `engine.acq.sigma_from_block()`, qui filtre (passe-bande ACQUISITION
   `BANDPASS=(5,40)` Hz, pas la bande ErrP `ERRP_BAND=(1,10)` Hz) avant de calculer l'écart-type.
   `_est_artefact`, lui, calcule `epoque.std()` sur la tranche BRUTE rendue par
   `epoch_from_stream` (aucun filtrage). Sur mon bruit blanc synthétique, le rapport tient
   largement sous `ERRP_ARTIFACT_RATIO=4.0` pour un feedback normal (σ raw ~2,0 contre σ repos
   filtré ~1,06 — un facteur ~1,9, loin sous 4,0) et très au-dessus pour mon artefact fabriqué (σ
   ~200). Mais du vrai EEG (dérive basse fréquence, 50 Hz) a un écart RAW/FILTRÉ potentiellement
   bien plus marqué que du bruit blanc — je n'ai aucune garantie que la marge ×4 encaisse ce
   décalage sur le casque. `core/modes/neuro.py`'s cousin (`neuro_monitor.py`, ligne 219) note
   d'ailleurs que « le projet a déjà payé ce genre de divergence » sur une mesure de σ analogue. Je
   n'ai PAS changé ce code (c'est explicitement celui du brief, et il n'a rien de démontrablement
   faux), mais je recommande de le vérifier au casque avant de faire confiance au seuil par défaut
   — c'est très exactement le genre de vérification que la tâche 5 (au casque) ou la recette
   devrait faire, pas quelque chose que ce fichier peut prouver seul en synthétique.

2. **`SPEC.status="moteur"` avec `SPEC.stream=None` est un choix, pas une prescription du brief.**
   Le brief ne montre aucun `SPEC = ModeSpec(...)` complet (contrairement aux autres champs, très
   précisément donnés). J'ai choisi `status="moteur"` parce que le runtime décode déjà de bout en
   bout — et laissé `stream`/`channels` vides parce que `DecodedErrPPublisher` n'existe pas encore.
   Ni `registry.py` ni aucun test ne lisent ce `SPEC` avant la tâche 4 (il n'est pas encore dans
   `registry.MODES`), donc rien ne l'a mis à l'épreuve ici. Si la tâche 4 attendait plutôt
   `status="prevu"` en attendant d'être câblé, c'est un changement d'une ligne — je le signale
   plutôt que de trancher en silence.

3. **Je n'ai PAS ajouté le test d'alignement par le contenu** (comparer l'époque construite à la
   tranche brute attendue, comme `p300.py` le fait). Ce n'est pas un oubli : le plan assigne
   explicitement ce test à la **tâche 5** (« LE TEST D'ALIGNEMENT, par le CONTENU », avec un nouvel
   attribut `self._derniere_epoque` introduit à ce moment-là, branché sur le vrai émetteur de
   stimulus). L'ajouter ici aurait dupliqué ou anticipé une décision de structure qui n'est pas la
   mienne à ce stade. Mes tests couvrent en revanche le CONTRAT du chemin réel (forme, bornes,
   horodatage) sans re-prouver la position du pic — délibérément laissé à la tâche 5.

4. Le brief ne montrait aucune consigne fausse cette fois-ci (contrairement à la tâche 1) : les
   quatre extraits de code fournis (squelette, repos, chauffe, décodage/artefact) fonctionnent tels
   quels, verbatim, et passent leurs propres tests au premier essai.

---

# Tour de correction 1 — le rejet d'artefact comparait deux échelles différentes

Statut : **DONE**
Commit : `3e190ef` — "Stop comparing a raw epoch to a filtered rest baseline, and surface when
rejection runs high"
Base : `df751f0` (le commit initial de cette tâche, ci-dessus)

## Ce que le relecteur a trouvé

Mon inquiétude n°1 était fondée, et le relecteur a tranché le SENS de l'erreur, que je n'avais pas
osé conclure : `sigma_from_block` FILTRE (passe-bande ACQUISITION 5-40 Hz), l'époque jugée par
`_est_artefact` est BRUTE. Un filtre ne peut que RETIRER de la puissance — jamais en ajouter — donc
σ_brut ≥ σ_filtré **toujours**, à état électrique identique. L'erreur ne pouvait aller que dans un
sens : le SUR-rejet. Et le budget ×4 de `ERRP_ARTIFACT_RATIO` était déjà à moitié consommé par le
seul effet de bande passante, avant toute contribution du casque.

## Mesure des deux options — chiffres à l'appui

Script jetable, avec le VRAI filtre d'acquisition (`UnicornAcquisition`, pas une approximation) :

**1. Bruit blanc seul** (aucune dérive) : le rapport σ_brut(époque)/σ_filtré(repos) vaut **~1,9**,
exactement `√(125/35)` (la perte de bande à elle seule, Nyquist 125 Hz contre la bande acquisition
35 Hz de large). Ni ce scénario ni son pendant brut/brut ne rejettent quoi que ce soit — l'effet
de bande seul ne suffit pas à franchir ×4.

**2. Avec 10 µV de dérive ORDINAIRE sous 5 Hz** (marche aléatoire lissée à ~0,5 Hz — PAS un
clignement, juste ce que ce casque fait en continu d'après `acquisition.py`), ajoutée
indépendamment au repos et à une époque saine (rien de spécial ne s'est produit entre les deux) :

| | brut / **filtré** (ACTUEL, buggé) | brut / **brut** (option retenue) |
|---|---|---|
| ratio (30 tirages) | ~9 | ~1,0-1,1 |
| époques SAINES rejetées à tort | **30/30** | **0/30** |

**3. Un vrai clignement** (60 µV, 0,3 s, gaussienne, canaux frontaux) reste détecté par l'option
brut/brut (ratio ~10,2-10,5, largement au-dessus de ×4). J'ai aussi mesuré la troisième option
(filtrer l'ÉPOQUE avec la même bande que le repos, pour comparer filtré à filtré) : elle **rate ce
même clignement** — ratio ~2,2-2,9, SOUS le seuil — parce qu'un clignement est une déflexion LENTE
dont l'essentiel de l'énergie est sous 5 Hz : la filtrer l'efface presque entièrement. Cette
option est donc écartée, mesure à l'appui, pas seulement par argument.

**Conclusion, confirmée par la mesure et pas seulement par préférence** : mesurer les deux σ sur le
BRUT (la préférence du relecteur) est la seule des trois options qui à la fois (a) n'a rejeté aucune
des 30 époques saines et (b) continue de détecter un vrai clignement.

## Correctif

- `_rest_step` ne passe plus par `engine.acq.sigma_from_block()` (qui filtre) : il calcule
  `np.asarray(bloc, dtype=float).std(axis=0)` directement sur `engine.recent`, comme `_est_artefact`
  le fait déjà pour l'époque. `engine.acq.margin_n` reste utilisé, mais seulement comme plancher
  arbitraire (« assez d'échantillons pour qu'un σ veuille dire quelque chose »), plus pour sa raison
  d'être (un transitoire de filtre qu'il n'y a plus à écarter, puisqu'il n'y a plus de filtre).
- Docstrings mises à jour (module, `_rest_step`) avec le mécanisme ET les chiffres mesurés, pour
  qu'un futur lecteur ne soit pas tenté de « corriger » ce choix en réintroduisant
  `sigma_from_block` par réflexe (c'est le choix qui semble évident et qui est faux).

## Le sur-rejet est maintenant détectable (panne n°8)

Nouveaux : `self._epoques_vues` (dénominateur, feedbacks dont l'époque a pu être extraite),
`self._rejet_eleve_dit` (alarme au plus une fois), `_verifie_taux_rejet()` (appelée à chaque
artefact). Palier `_TAUX_REJET_ALARME = 0,5` (bien avant l'extrême — un détecteur sain rejette une
minorité, pas la moitié), plancher `_TAUX_REJET_MIN_ECHANTILLONS = 10` (en dessous, un taux est du
bruit d'échantillonnage). `state()` expose `epoques_vues`, `artefacts` et un `taux_rejet` calculé
(`None` tant qu'aucune époque n'a été jugée — jamais `0`, qui affirmerait « aucun rejet » à tort).
Les deux compteurs sont des compteurs de SESSION, comme `_artefacts`/`_epoques_perdues` déjà en
place : `_reset_rest` ne les efface pas.

## Preuve ROUGE-PUIS-VERT

Construite : un repos (8 s) et une époque saine (0,9 s) tirés indépendamment, avec le MÊME niveau
de dérive ordinaire (10 µV) — le scénario exact de la mesure ci-dessus, rejoué via le VRAI chemin
(`ErrPRuntime.begin_rest` → `tick` → `_rest_step` → `_traiter_feedback` → `_est_artefact`), pas un
calcul à côté.

**ROUGE** (`_rest_step` remis temporairement en `engine.acq.sigma_from_block(bloc)`, soit le code
d'avant ce tour) :
```
[errp] repos mesuré (6 fenêtres) — σ par voie (brut) : [1.2 1.2 1.2 1.2 1.2 1.1 1.2 1.2]
  OK   repos conclu (dérive ordinaire comprise) pour la preuve rouge-puis-vert (running)
  ÉCHEC ⚠️ une époque SAINE (dérive ORDINAIRE ~10 µV, rien d'anormal) n'est PAS rejetée à tort — AVANT ce correctif (brut contre filtré), le même scénario rejetait à tort 30 fois sur 30 en répétition (artefact publié=1)
  ÉCHEC ...et un VRAI verdict sort (score comparé au seuil), pas un -1 déguisé (-1)
[errp] VERDICT : PROBLÈME
EXITCODE=1
```
(Le label du print dit encore « brut » ici — c'est un résidu du revert PARTIEL et TEMPORAIRE, la
valeur affichée, elle, est bien la sortie FILTRÉE de `sigma_from_block` : 1,2, l'échelle filtrée
mesurée dans tout ce rapport, pas les ~10 de l'échelle brute.)

**VERT** (correctif remis) :
```
[errp] repos mesuré (6 fenêtres) — σ par voie (brut) : [10.3 10.2 10.2 10.2 10.2 10.2 10.2 10.1]
  OK   repos conclu (dérive ordinaire comprise) pour la preuve rouge-puis-vert (running)
  OK   ⚠️ une époque SAINE (dérive ORDINAIRE ~10 µV, rien d'anormal) n'est PAS rejetée à tort — AVANT ce correctif (brut contre filtré), le même scénario rejetait à tort 30 fois sur 30 en répétition (artefact publié=0)
  OK   ...et un VRAI verdict sort (score comparé au seuil), pas un -1 déguisé (0)
[errp] VERDICT : OK
EXITCODE=0
```

Un piège rencontré EN CONSTRUISANT cette preuve, réglé avant d'arriver au ROUGE ci-dessus : ma
première version générait la dérive sur tout un tampon de 20 s puis en extrayait une tranche de
0,9 s — `sous_5hz` la met à l'échelle sur la longueur qu'on lui donne, donc une dérive « mise à
10 µV sur 20 s » DILUE cette amplitude dans n'importe quelle tranche de 0,9 s qu'on en extrait
ensuite, et l'effet à démontrer disparaissait (le test passait même avec le code buggé — un faux
négatif de test, pas une preuve). Corrigé en donnant au repos et à l'époque chacun un tampon taillé
à SA propre durée (8 s et 0,9 s), comme dans le script de mesure.

## Comptage des assertions (méthode excluant `def chk(cond, msg):`)

`grep -n "chk(" src/core/modes/errp.py` rend **52** lignes ; moins 1 pour `def chk(cond, msg):` =
**51 sites d'assertion**, contre **42 avant** ce tour → **+9**. Toutes s'exécutant exactement une
fois, 51 lignes `OK` à l'exécution (0 `ÉCHEC`) — confirmé en comptant le run final. Aucune
assertion existante n'a été retirée ni modifiée ; les 9 nouvelles couvrent la preuve rouge-puis-
verte (2) et le mécanisme d'alarme de sur-rejet : sous le plancher d'échantillons même à 100 % de
rejet (1), un taux plausible qui ne déclenche rien (1), un taux élevé qui déclenche l'alarme avec
le compte exact dans le message (1), l'alarme qui ne se répète pas (1), `state()` qui expose le
taux calculé (1), et `taux_rejet` à `None` (pas `0`) tant que rien n'a été jugé (1).

## Tests relancés

```
python src/core/modes/errp.py
```
`[errp] VERDICT : OK`, `EXITCODE=0` (51/51 `OK`).

```
python src/core/server.py --smoke
```
`[smoke-tampon]` (cadence temps réel du board synthétique — sans rapport avec ce fichier) a échoué
de façon intermittente pendant ce tour, jusqu'à 4 fois de suite un moment donné. Vérifié que ce
n'est PAS une régression de ce correctif : `git stash` de `errp.py` (retour à l'état exact
`df751f0`, déjà revu au tour précédent) reproduit l'ÉCHEC IDENTIQUE sur le même test, et une
exécution ISOLÉE de la même mesure (un seul `EngineServer`, hors de la longue suite `--smoke`) rend
une cadence médiane de 3,95 ms contre 4,00 ms attendus — conforme. La panne semble liée à
l'accumulation de nombreuses sessions BrainFlow synthétiques dans un même processus long
(`--smoke` en enchaîne plus d'une douzaine), pas à une régression de code — mais je ne l'affirme
pas plus que ça, n'ayant pas creusé plus loin que cette double vérification. `git stash pop` a
restauré le correctif ensuite (confirmé par grep sur `_TAUX_REJET_ALARME`). Dernière exécution
propre : `EXITCODE=0`, 17/17 sous-smokes `OK`, `[smoke-frontiere] 0 violation(s)`. Aucun processus
Python résiduel à aucun moment (`Get-Process python` vide avant/après chaque lancement).

## Mes inquiétudes (ce tour)

1. **`smoke-tampon` reste fragile sur ce poste**, pour des raisons qui semblent étrangères à ce
   fichier (confirmé par le test `git stash` ci-dessus) mais que je n'ai pas pleinement expliquées
   — juste assez creusé pour être sûr de ne pas signer une régression que je n'aurais pas vue. Si ça
   persiste au-delà de ce chantier, ça vaudrait un ticket séparé : soit desserrer sa tolérance
   temps réel, soit isoler les sous-smokes coûteux en process séparés.
2. **`_TAUX_REJET_ALARME=0,5` et `_TAUX_REJET_MIN_ECHANTILLONS=10` sont mes choix**, non dictés par
   la demande (qui donnait « 90 % » comme exemple illustratif, pas comme seuil à coder). Je les ai
   justifiés en commentaire ; à ajuster si l'usage réel (séance au casque, tâche 5) montre qu'ils
   sonnent trop tôt ou trop tard.
3. Les compteurs `_epoques_vues`/`_artefacts`/`_rejet_eleve_dit` restent des compteurs de SESSION
   (jamais réarmés par `_reset_rest`), par cohérence avec `_artefacts` déjà en place avant ce tour —
   mais ça veut dire qu'un « Refaire le repos » qui corrige un mauvais contact ne fait PAS taire une
   alarme déjà déclenchée avant la reprise. Choix assumé et documenté en commentaire, pas testé
   contre l'alternative (réarmer comme `_chauffe_dite`) faute d'instruction explicite dessus.
