# SDD ledger — plan: docs/superpowers/plans/2026-07-30-motor-imagery-moteur-B.md

Chantier 3 moitié B — la calibration Motor Imagery jouée par le moteur.
Branche : `main` (workflow établi de l'utilisateur, déjà appliqué aux chantiers 0-1, 2, 3-A).
BASE du chantier : `d598d24` (le commit du plan lui-même).

Contrainte utilisateur : le coût est le TEMPS, pas les crédits. ~40 Ko de diff max par sous-agent.

⚠️ Ne JAMAIS lancer deux sous-agents qui exécutent du code en parallèle : les smokes ouvrent une
session BrainFlow et publient sous des noms de flux PUBLICS. Erreur commise au chantier 3-A.

## Journal

- Setup : atelier créé, BASE = d598d24, 7 tâches.
- Pré-vol : une tension relevée dans le plan — la contrainte « aucun test n'écrit dans le vrai
  `data/` » contre T7 étape 3, où les smokes des fichiers ARCHIVÉS y écrivent. Ruling : la
  contrainte gouverne le code neuf ; l'archive est délibérément figée (elle garde l'ancien
  nommage à écrasement, c'est le sujet du chantier), et sa vérification est manuelle et
  ponctuelle. Pas d'escalade.
- Task 1: complete (commits d598d24..181b6a5, review clean — spec ✅, 0 critique, 0 important)
- Task 1: minor (deferred): bloc de test de `Calib` placé ~120 lignes avant la vraie fin de
  `_selftest()` (contract.py:498) au lieu de juste avant le verdict — sans effet, `chk` cumule.
- Task 1: minor (deferred): `# noqa: E402` superflu sur l'import sklearn (mi_decoder.py:31) —
  l'import précède le `sys.path.insert`, E402 ne pourrait pas se déclencher. Vient du PLAN.
- Task 1: minor (deferred): la garde `n_splits < 2` (une classe à un seul essai → `cv_groupee_`
  reste None malgré `groups` fourni) n'est exercée par aucun test. Central pour ce chantier
  (« None = honnêtement absent, jamais deviné ») — à faire triager par la revue finale.
- Task 1: minor (deferred): `Calib.defaults()` duplique le corps d'une ligne de
  `ModeSpec.defaults()` — délibéré, une classe de base irait contre le typage structurel dont
  `validate` dépend.
- Task 1: minor (deferred): le rapport ne capture pas la sortie des échecs attendus (étapes 3 et
  7), seulement les runs verts finaux.
- Task 2: implémentée (commit cdb061a). Revue : spec ✅, 0 critique, **1 IMPORTANT**.
  Constat : `MIRuntime.state()` ne supprime pas la lecture disque, il en jette le résultat —
  `super().state()` passe par `channels_for` → `_channels` → `joblib.load`, puis la ligne
  suivante écrase. La moitié « ne ment plus » du défaut parké est fermée, la moitié « ne relit
  plus le disque » ne l'est pas. Le test ne peut pas le voir : il juge la valeur rendue, jamais
  l'accès disque. Étiqueté plan-mandated par le relecteur.
  **Ruling du coordinateur : ce N'EST PAS un conflit avec le plan** — le plan EXIGE la
  suppression de la lecture (son propre docstring la promet) ; c'est le code prescrit qui ne la
  délivre pas. Donc tour de correction ordinaire, pas d'escalade humaine.
  Correction demandée : point d'extension `ModeRuntime.channels()` dans `runtime.py`, surcharge
  dans `MIRuntime`, et un test qui COMPTE les appels à `mi_models.charger` au lieu de juger la
  valeur rendue.
- Task 2: minor (deferred): double numérotation « 9. » dans le selftest de `mi.py`.
- Task 2: minor (deferred): `_ModeleDeux` n'explique pas pourquoi elle vit au niveau du module.
- Task 2: fix round 1/5 (1 addressed, 0 open ; commit 3d46273). Point d'extension
  `ModeRuntime.channels()` + surcharge dans `MIRuntime` + test qui COMPTE les appels à
  `mi_models.charger` (mi.py:533-560). Vérifié par le coordinateur, EN SÉRIE : runtime.py ·
  mi.py · calibration.py · mi_calib.py · server.py --smoke · console/app.py --smoke → six verts.
- Task 2: re-relecture cadrée (diff restreint à mi.py/runtime.py, 13 Ko — la plage
  cdb061a..3d46273 contient aussi le commit de T3, écarté à la main). Verdict : le constat
  IMPORTANT est **ADDRESSED**, et il tient sous lecture adverse du test (compteur installé avant
  la construction, restauré en `finally`, baseline prise APRÈS le constructeur donc seul le delta
  de `state()` est jugé, et `_channels` passe par l'attribut de module donc le patch intercepte
  tous les chemins). **Aucune casse nouvelle** : `SsvepRuntime`, `RawRuntime`, `NeuroRuntime` ne
  surchargent ni `channels()` ni `state()`, leur état publié est strictement inchangé ;
  `CalibrationRuntime` n'hérite pas de `ModeRuntime`.
  ⚠️ **ERREUR DE MON JOURNAL, relevée par le relecteur** : j'avais écrit « les 2 mineurs repris
  au passage » d'après le rapport de l'implémenteur, SANS vérifier. Faux pour l'un des deux.
  C'est exactement le piège déjà noté au chantier précédent — ne pas prendre un rapport pour une
  preuve. Ne plus recopier une affirmation de sous-agent dans le journal sans la constater.
- Task 2: minor (deferred, TOUJOURS OUVERT): double numérotation « 9. » dans `_selftest` de
  `mi.py` (blocs à mi.py:498 et mi.py:512, suivis d'un « 10. » à mi.py:576 qui est la 11e
  section). Le tour de correction n'a reformulé que le texte du second bloc, jamais son numéro.
- Task 2: minor (deferred): `_ModeleDeux` documente désormais pourquoi elle vit au niveau du
  module — ADDRESSED.
- Task 2: minor (deferred, hors périmètre, relevé par la re-relecture): à mi.py:528-530, la
  branche `p.choices_fn()[0] if hasattr(p, "choices_fn") else None` ne peut JAMAIS s'exécuter —
  `Param` est une dataclass gelée, `hasattr(p, "default")` est toujours vrai. Inoffensif ici
  (la valeur est écrasée à la ligne suivante) mais piège latent si le motif est recopié.
- Task 2: complete (commits 181b6a5..3d46273 pour ses fichiers, review clean après 1 tour,
  3 mineurs différés)

## VAGUE DE CORRECTION

- **LOT A : TERMINÉ.** 7 commits au total (`8e8938c` fait par le coordinateur après l'interruption
  du premier correcteur, puis `a8dd0b5`, `8775bb4`, `27ef347`, `bf632b1`, `d353276`, `673337d`).
  Les 12 commandes officielles vertes en série, `server.py --smoke` à 10 sous-verdicts sur 10,
  arbre propre, `data/` sans résidu. **Preuve ROUGE-puis-VERT fournie pour A2, A3, A10 (×3) et
  A11 comme exigé, plus A7 et A9 en prime.**
  ⚠️ **Comportement à noter, et à encourager** : le correcteur avait d'abord écrit dans son
  rapport n'avoir pas retrouvé le couple `int()`/`int(round())` d'A14 ; en revérifiant il l'a
  trouvé, corrigé, et **signalé sa propre erreur en tête de rapport plutôt que de réécrire
  discrètement**. C'est exactement ce qu'on veut d'un rapport de sous-agent.
  A13 n'est fait qu'à moitié (côté moteur) : la consommation de la constante par la console
  revient au lot B.
- **LOT B : TERMINÉ.** 5 commits (`78e8772`, `e0edd21`, `9152ef7`, `586bf93`, `491442e`), les cinq
  commandes vertes en série, rouge-puis-vert prouvé pour B1, arbre propre.
  ⚠️ **Réserve honnête et bien raisonnée du correcteur** : en corrigeant B1 il a découvert que le
  symptôme s'auto-guérit PROBABLEMENT en usage réel — la séance relancée traverse 15 s de chauffe
  (étape vide, sondée en continu) qui réinitialiseraient l'état bloqué avant le premier top. Il a
  gardé le correctif quand même, avec le bon argument : **s'appuyer sur une durée de chauffe pour
  se protéger serait exactement la « coïncidence non documentée » que ce chantier corrige
  ailleurs** (A1, A9, A10). Envoyé au jugement de la re-relecture plutôt que tranché par moi.

### Re-relecture de la vague — 4 tranches (moteur 47,6 Ko · calib 25,8 · contrat 23,4 · reste 39,1)

- **Tranche `contrat` : TOUS ADDRESSED, aucune casse critique ou importante.**
  **Comptage fait : 5 `chk` ajoutées, 0 retirée ni affaiblie.**
  - A10, le test du MÉCANISME est vraiment un test du mécanisme : le remplacement porte sur
    `StratifiedGroupKFold.split` au niveau de la CLASSE, donc il intercepte le découpage
    RÉELLEMENT utilisé par `fit()` en interne, pas une reconstruction à côté. Sous le mutant à
    décote arbitraire (qui ne regarde jamais les groupes), la liste des plis espionnés reste
    VIDE et l'assertion échoue explicitement — preuve directe que l'ancienne assertion seule
    restait verte sous ce même mutant.
  - A9 : le SENS de la comparaison est vérifié — c'est bien le cas dangereux (`epoch_s` plus
    court que `imagery_s`, donc troncature silencieuse) qui est refusé. Et le `getattr` défensif
    ne masque aucun trou réel : `imagery_s` est un attribut de CLASSE de la base, donc toute
    sous-classe en hérite.
  - A14 : la factorisation de `defaults()` n'a rien cassé — la fonction commune est appelée
    DEPUIS les méthodes de chaque classe, donc la surface que `validate` consomme par typage
    structurel est inchangée.
  - minor différé : le nouveau bloc de `check()` n'a pas l'équivalent du message « NORMAL … sans
    choix pour l'instant » de son voisin, alors que son commentaire annonce « même traitement ».
    Dormant (le seul param de calibration a des choix STATIQUES).
- **Tranche `reste` (console + research + archive + doc) : TOUS ADDRESSED, aucune casse.**
  Les six affirmations de documentation ont été vérifiées DANS LE CODE, pas dans le diff.
  - **La réserve du correcteur sur B1 est TRANCHÉE, et le relecteur est allé plus loin que je ne
    demandais** : l'auto-guérison par les 15 s de chauffe est confirmée exacte, ET il a vérifié
    que le drapeau `--warmup` de la ligne de commande **ne peut PAS** la raccourcir en usage réel
    (il alimente un mécanisme séparé, celui du repos partagé des MODES, jamais la chauffe de la
    calibration). Donc l'auto-guérison est réelle aujourd'hui et ne dépend d'aucun drapeau
    exposé — mais reste une coïncidence non protégée, rien n'empêchant ces durées de changer.
    **Verdict : le test ne saute aucune phase que la réalité impose** (pour l'abandon, il n'y en a
    aucune), et le correctif rend l'invariant vrai INCONDITIONNELLEMENT. Correctif et test
    justifiés, réserve honnête et bien cadrée.
  - B2 : la chaîne de propagation a été tracée de bout en bout — moteur → état → snapshot →
    console — sans aucune sérialisation intermédiaire, donc `None` reste `None` sur tout le
    trajet. Aucun autre chemin d'affichage trouvé dans la console.
  - B4 : le point que je demandais est vérifié — l'étiquette est bien lue APRÈS le clic et AVANT
    tout nouvel état, et le relecteur a même vérifié que la minuterie de la console est arrêtée
    dès la construction, donc aucun rafraîchissement ne peut s'intercaler. **Aucun relâchement :
    chaque changement est un ajout pur ou un resserrement** (`in` → `==`, présence de clé →
    égalité de dict complet).
  - out of scope : `plus_recent` de `mi_compare.py` n'a aucune couverture automatisée (le script
    n'a pas de `--smoke` et n'est ni l'un des trois smokes officiels ni l'une des gardes MI).
- **Tranche `calib` : TOUS ADDRESSED, aucune casse. Comptage vérifié ligne à ligne :
  `calibration.py` 16 → 17 assertions, `mi_calib.py` 25 → 30. Aucune suppression, aucun
  affaiblissement** — une assertion RENFORCÉE (`chk(True, …)` devient une vraie capture).
  - **A2 : le correcteur a trouvé et fermé LUI-MÊME un trou que sa première version aurait eu.**
    Sur la séance principale, la CV honnête (45,0 %) et la naïve (49,3 %) tombent dans le MÊME
    palier de verdict — donc un mutant `verdict(cv_naive)` y aurait survécu. Il a étendu le test à
    deux séances supplémentaires où les paliers diffèrent réellement (45,0 UTILISABLE contre 71,6
    EXCELLENT ; 41,7 FAIBLE contre 57,1 UTILISABLE), paliers que le relecteur a recalculés à la
    main contre les seuils. C'est exactement le bon réflexe : une assertion ne prouve rien si le
    mutant tombe dans la même case.
  - **A3 : vérifié avec la sévérité demandée.** Le faux moteur capture une COPIE au moment de la
    génération, donc tout filtrage inséré n'importe où en aval romprait la comparaison ; celle-ci
    est un `array_equal` EXACT, pas un `allclose`. L'exclusion de l'échauffement est vérifiée deux
    fois indépendamment — par lecture du garde, et empiriquement par le comptage des prélèvements.
    Portée correctement bornée : ce test pin que `mi_calib` ne filtre rien, pas que le VRAI
    `recent_window` rend du brut — c'est A4, une autre tranche.
  - A14 : le couple `int()`/`int(round())` n'était PAS dans cette tranche — la garde de longueur
    utilisait déjà `round` avant et après. Le bug vivait dans `server.py`.
  - minor différé : aucun test ne force artificiellement la branche « CV non mesurable ». Jugé non
    bloquant, l'arbitrage désignant lui-même le commentaire, et non un test, comme ce qui tient
    l'invariant tant que le chemin est arithmétiquement inatteignable.

## ⚠️ REPRENDRE ICI — 2e pause (limite d'usage), 2026-07-31

**État : arbre PROPRE, 12 commits locaux sur `main`, RIEN DE POUSSÉ.** `d598d24` (le plan) →
`8e8938c`. **Les 7 tâches sont faites et relues. La revue de branche est faite (8 tranches).**

**Ce qui reste, dans l'ordre :**

1. **FINIR LA VAGUE DE CORRECTION.** Tout est arbitré et écrit dans
   `.superpowers/sdd/2026-07-30-motor-imagery-moteur-B/vague-correction.md` — c'est l'artefact
   coûteux, il survit. Deux lots qui ne partagent AUCUN fichier, **jamais en parallèle** (les deux
   lancent des tests) :
   - **LOT A (`src/core/`)** : A1, A8, A12 et les commentaires jumeaux de A1/A10 sont **DÉJÀ
     FAITS** (commit `8e8938c`, vérifié par 6 tests verts). **Restent A2, A3, A4, A5, A6, A7, A9,
     A10 (les tests), A11, A13, A14.** Le plus important : **A5** (le tampon a changé la fenêtre
     de mesure d'un flux PUBLIC) et **A6** (`submit` peut lever depuis le fil Qt, et un snapshot
     peut se contredire).
   - **LOT B (`src/console/`, `src/research/`, `archive/`, doc)** : rien de fait. B1 (le premier
     top muet après un abandon) et B2 (la console effondre elle aussi la CV absente en 0,0) sont
     les deux qui comptent.
2. **Une re-relecture cadrée** de la vague, sur son diff seul.
3. **Pousser** (`git push`, 12+ commits d'avance) puis **mettre à jour la mémoire**.

⚠️ **Ce qui est PARKÉ est écrit en fin de `vague-correction.md`, avec sa raison.** Ne pas le
rouvrir — en particulier : NE PAS supprimer `MI_MODEL_PATH` ni `MI_KEY_CHANNELS`, l'archive en
dépend et doit rester exécutable.

**Méthode qui a payé, à refaire :** implémenteur haiku quand le brief porte le code complet,
sonnet sinon et pour toutes les relectures, opus sur les deux tranches les plus risquées.
Parallélisation SÛRE : un relecteur borné à son diff n'exécute rien, donc il peut tourner pendant
qu'un implémenteur lance des smokes. **Ne JAMAIS paralléliser deux agents qui exécutent du code.**
Et exiger la preuve ROUGE-puis-VERT sur tout test qu'on prétend protecteur : c'est ce qui a
démasqué le vote des tops (`['GAUCHE']`, un sur six) et l'écrasement des fichiers.

- Task 3: implémentée (commit 1b897e4), DONE_WITH_CONCERNS. Deux réserves de l'implémenteur, en
  relecture : (a) le `chk` `_mi.SPEC.calibration is CALIB` remplacé par une vérification champ
  par champ — lancé en `__main__`, `mi_calib.py` est chargé deux fois sous deux noms de module,
  donc deux objets `CALIB` distincts ; (b) `state()` teste `now` par sa valeur de vérité, donc
  `state(now=0.0)` retombe à 0 — vient du plan.
- Task 3: revue. **Spec ✅, qualité approuvée, 0 critique, 2 IMPORTANTS, 4 mineurs.** Les cinq
  invariants d'architecture sont vérifiés un par un et tiennent : aucune lecture d'horloge dans
  la machine de phases (le seul `time` sert au nommage, il ne conditionne aucune transition) ;
  l'échauffement ne prélève RIEN et le test le prouve en comptant les ACQUISITIONS, pas les
  entrées ; `groups` est bien l'indice d'essai ; `cancel` et l'échec d'entraînement n'atteignent
  jamais `save()` ; `window_s`/`step_s` lus via `self`. `calibration.py` est identique au brief
  au caractère près. Le déviation `is CALIB` est mécaniquement justifiée et reproductible.
  **Les deux IMPORTANTS viennent du PLAN**, pas de l'exécution — le code fautif est prescrit
  verbatim dans le brief. Ruling du coordinateur, comme pour T2 : ce ne sont PAS des conflits
  avec le plan (le plan EXIGE « rien n'est jamais écrasé », c'est son code qui ne le délivre
  pas), donc tour de correction ordinaire, pas d'escalade humaine.
  - **IMPORTANT 1** — `calibration.py:237` : `... if now else 0.0` confond `now=0.0` avec « pas
    de `now` ». Correctif : `if now is not None else 0.0`.
  - **IMPORTANT 2, le sérieux** — la garantie « rien n'est jamais écrasé » est PROBABILISTE, pas
    structurelle : `horodatage()` a une résolution d'une seconde, donc deux séances terminées
    dans la même seconde produisent le MÊME couple de noms, et `save()`/`np.savez()` écrasent
    sans vérification d'existence. C'est exactement la classe de panne que la tâche existe pour
    fermer (un nom FIXE a déjà fait perdre les époques d'une séance de 42 essais). Pire, le test
    ne le voit pas : son commentaire annonce « deux séances donnent deux fichiers » mais la
    seconde séance échoue exprès avant `save()` — **toutes ses assertions passeraient sur un
    mutant à nom CODÉ EN DUR**. Le paramètre injectable `horodatage(maintenant=None)`, ajouté
    « pour que le test soit reproductible », n'est jamais utilisé par `_entrainer`.
- Task 3: minor (deferred): la vérification de remplacement du `is CALIB` compare le NOM de la
  classe de runtime, pas son module — ajouter `__module__ == "core.modes.mi_calib"` la fermerait.
- Task 3: minor (deferred): `verdict` n'est testé que comme fonction pure, jamais recoupé avec la
  CV honnête qu'il résume — un mutant qui calculerait `verdict(cv_naive)` passerait tout.
- Task 3: minor (deferred): la branche « tampon pas rempli » (`calibration.py:178-183`) n'est
  exercée par aucun test — les deux faux moteurs rendent toujours une époque complète.
- Task 3: minor (deferred): cette même branche n'écrit que sur la console, jamais dans
  `self.probleme` — un client qui ne lit que `state()` ne peut pas savoir que des essais ont été
  silencieusement écartés.
- Task 3: fix round 1/5 dispatché (les 2 IMPORTANTS). Correction demandée : `if now is not None`,
  et surtout une garantie STRUCTURELLE de non-écrasement — chercher un horodatage dont les DEUX
  chemins cibles sont libres en avançant d'une seconde, le FORMAT imposé par la spec ne bougeant
  pas. Plus un test qui épingle `horodatage` sur une constante, joue DEUX séances RÉUSSIES et
  exige deux couples de fichiers distincts : il doit échouer sur le code actuel.
- Task 4: implémentée (commit 144de06, `server.py` seul), DONE_WITH_CONCERNS, en relecture.
  **Trois écarts au brief, tous forcés par des faits MESURÉS — ce sont trois erreurs de MON
  plan, pas de l'exécution :**
  (a) `trials_per_class: 6` est refusé par le contrat réel — « Essais par classe » est un
      `choice` borné à `MI_SESSIONS = (10,14,18,26)`, pas un entier libre → passé à 18 ;
  (b) `imagery_s=0.20 / window_s=0.10` est INFAISABLE : `filtfilt` d'ordre 4 a un `padlen` mesuré
      à 27 échantillons contre 25 pour une fenêtre de 0,10 s à 250 Hz → passé à 0.32/0.16/0.08,
      même rapport donc toujours 3 fenêtres par essai ;
  (c) le modèle du dossier temporaire était invisible pour `start_mode` (`choices_fn` regarde
      toujours le vrai `DATA_DIR`) → même remplacement temporaire de `modeles_disponibles` que
      celui déjà employé par l'autotest de `core/modes/mi.py`.
  ⚠️ **Fragilité statistique laissée en place, à faire juger** : l'assertion `cv_groupee_ <
  cv_naive` du smoke compare deux CV sur du BRUIT réel (board synthétique), pas sur de l'ERD
  fabriquée. ~1 violation sur 6 mesurée à `trials_per_class=18`. Le projet a pour règle de NE
  JAMAIS CONCLURE SUR DU BRUIT — une assertion qui échoue une fois sur six est à peser.
- Task 4: revue. **Spec ✅, 0 critique, 1 IMPORTANT, 1 mineur. Qualité : à corriger.** Les étapes
  1-5 (production) sont vérifiées identiques au brief et approuvables telles quelles ; le
  relecteur les a re-dérivées depuis la source plutôt que de croire le rapport. Les quatre points
  d'architecture tiennent : la calibration est bien atteignable sur un mode ARRÊTÉ (les deux
  commandes sont placées AVANT le `_one()` qui exige un mode démarré — sans ça la calibration du
  MI serait définitivement inatteignable) ; une seule à la fois, avec sa raison ; le nettoyage
  est dans le `finally` de la boucle ; le `finally` du smoke enveloppe bien son corps.
  **Les trois écarts de l'implémenteur sont VALIDÉS**, chacun re-dérivé depuis la source :
  `filtfilt` d'ordre 4 → `padlen = 3 × max(len(a), len(b)) = 27` contre 25 échantillons, et la
  contrainte porte sur `window_s` (pas `imagery_s`) parce que `fit` reçoit déjà les fenêtres
  découpées ; le remplacement temporaire de `modeles_disponibles` est SÛR parce que
  `submit("start_mode")` valide SYNCHRONEMENT sur le fil de l'appelant, avant même de mettre en
  file — aucune course avec la boucle.
  **Le dimensionnement du tampon est prouvé** par deux assertions indépendantes de la séance
  jouée : `CALIB.epoch_s` est figé à l'import (dataclass `frozen`), le monkeypatch du smoke ne
  touche QUE les attributs de protocole, donc `keep` est calculé sur les 4 s réelles.
  - **IMPORTANT** — l'assertion `cv_groupee_ < cv_naive` du smoke est la SEULE de tout le dépôt
    à tirer cette conclusion depuis du BRUIT : ses deux jumelles (`mi_calib._selftest`,
    `mi_decoder._test_cv_honnete`) l'asservissent à de l'ERD FABRIQUÉE. Conséquence que je
    n'avais pas vue : `_smoke()` enchaîne ses sous-smokes avec `and`, donc une bascule sur cette
    ligne **saute silencieusement `_smoke_cumul` et `_smoke_proposition`** — une fois sur six, et
    en se lisant comme une vraie régression. Correctif : la sortir du `ok` gatant, l'imprimer
    comme diagnostic. Une ligne.
- Task 4: minor (deferred): `server.py:1387` déréférence `calib` juste après un `chk(calib is not
  None)` qui ne court-circuite pas — sur un build déjà cassé, on obtient une trace brute au lieu
  du diagnostic ligne à ligne. Dégrade le diagnostic, pas la justesse.
- Task 3: fix round 1/5 (2 addressed selon l'implémenteur, re-relecture cadrée en cours ;
  commit 04c7773). Non-écrasement rendu STRUCTUREL + `if now is not None`. **Preuve fournie :
  le nouveau test à deux séances a été constaté ROUGE avant correctif** (mêmes noms, contenu
  écrasé, 4 `chk` en échec) puis vert après. Tests en série verts, `data/` sans résidu.
- Task 3: re-relecture cadrée du tour 1 (diff restreint aux 2 fichiers, 15,8 Ko). **Les DEUX
  IMPORTANTS sont ADDRESSED, aucune casse nouvelle.** Les quatre points de sévérité que j'avais
  demandés sont vérifiés un par un : (a) le test TUE le mutant à nom codé en dur — c'est démontré
  EMPIRIQUEMENT, le rapport contient l'exécution AVANT branchement qui échoue sur les 4
  assertions décisives, et l'assertion non décisive (« les deux modèles sont listés ») est
  explicitement écartée comme telle dans le code ; (b) l'horodatage épinglé est restauré dans un
  `finally` dans les deux blocs ; (c) l'intégrité est vérifiée par SHA-256 du CONTENU, capturé
  avant la seconde séance, pas par `os.path.exists` ; (d) le volume de données est déterministe,
  seul l'ordre des essais dépend du tirage — la seule variable qui échoue avant correctif est la
  collision de noms. Format des noms INCHANGÉ, motif `mi_model*.joblib` confirmé identique à
  `mi_models.py`, aucune horloge introduite dans la machine de phases. Compatibilité de
  `_smoke_calibration` vérifiée par lecture directe de `server.py`, pas prise sur parole.
- Task 3: minor (deferred): `_chemins_libres` garde une fenêtre check-puis-agit (TOCTOU) en
  théorie. Ce n'est PAS une régression — avant le correctif la collision était CERTAINE dans la
  même seconde, et l'invariant « au plus une calibration » exclut la concurrence dans un
  processus. Le correctif réduit la fenêtre, il ne l'élargit jamais.
- Task 3: complete (commits cdb061a..04c7773 pour ses fichiers, review clean après 1 tour,
  5 mineurs différés)
- Task 5: implémentée (commit 95a62de, `console/grid.py` + `console/app.py`), DONE sans réserve.
- Task 5: revue. **Spec ✅, 0 critique, 0 important, 2 mineurs. Approuvée.** La règle « console =
  client » est tenue : `_demarrer` poste sans validation ni réglages, et le libellé du bouton ne
  change QUE dans `update_from`, jamais dans le gestionnaire de clic — la régression classique
  (basculer l'étiquette au clic, donc MENTIR dès que le moteur refuse) n'est pas là. Le
  relecteur valide aussi le choix de NE PAS bloquer les signaux : `QPushButton.setText()` n'en
  émet aucun, contrairement à `setChecked()` sur la case à cocher voisine. Les tests cliquent
  vraiment, avec `clear()` avant chaque clic — la causalité est prouvée, pas supposée.
- Task 5: minor (deferred): le commentaire de 4 lignes que le brief donnait verbatim pour
  `grid.py:98-101` est absent du code livré. C'était le seul endroit de `grid.py` où un étudiant
  éditant ce bouton aurait été prévenu de ne pas y ajouter de validation.
- Task 5: minor (deferred): angle mort de couverture HÉRITÉ DU BRIEF — aucune des 4 assertions
  ne vérifie qu'un clic ne mute pas localement l'étiquette de SA tuile avant le prochain
  snapshot. Le code actuel n'a pas ce défaut (vérifié par lecture), mais le filet ne le prouve
  pas pour une modification future.
- Task 5: complete (commits 172f32a..95a62de, review clean du premier coup, 2 mineurs différés)
- Task 6: implémentée (commit bf586c9, +526/-1 sur 5 fichiers), DONE_WITH_CONCERNS, en relecture.
  ⚠️ **Elle a trouvé et corrigé DEUX défauts PRÉ-EXISTANTS dans `params_form.py`** : un
  `QComboBox` de type « choice » ignorait le défaut déclaré (affichait toujours le premier
  choix), et `values()` rendait toujours une CHAÎNE même pour des choix numériques — donc le
  vrai `contract.validate` refusait `trials_per_class` **même à sa valeur par défaut**. Invisible
  jusqu'ici : c'est le premier `choice` du projet à choix numériques ET à défaut non-premier.
  À faire vérifier par la relecture, y compris la non-régression des formulaires SSVEP et neuro.
  Réserve de l'implémenteur à examiner concrètement : la clé anti-répétition des tops
  `(phase, essai, etape)`, qui vient du brief, alors que `essai` NE BOUGE PAS pendant
  l'échauffement.

- Task 6: revue. **Spec ✅ pour l'essentiel, 0 critique, 1 IMPORTANT, 2 mineurs. À corriger.**
  L'architecture centrale est vérifiée contre le VRAI `CalibrationRuntime.state()` (pas contre le
  fixture) : aucun `QTimer`, aucune phase déduite, aucun champ recalculé ; `rafraichir_choix()`
  n'est atteinte que par `show_mode()`, jamais par le chemin périodique — le coût redouté sur le
  fil Qt est réel et bien hors du chemin. L'honnêteté du résultat est là et épinglée par des
  `chk` dédiés (40,1 présent / 55,6 ABSENT / 33 présent / la phrase d'honnêteté présente).
  **Les deux correctifs de `params_form.py` sont VALIDÉS** : diagnostic confirmé indépendamment
  (`trials_per_class` est bien le premier `choice` du projet à choix ENTIERS avec défaut hors
  première position), correctifs rétrocompatibles pour le réglage `model` (choix déjà des
  chaînes), et le relecteur a vérifié que le moteur FACTICE accepte tout inconditionnellement —
  donc le test du brief n'aurait rien vu, et le bloc ajouté contre le VRAI moteur comble un trou
  réel.
  - **IMPORTANT** — la clé anti-répétition des tops ne varie JAMAIS pendant l'échauffement.
    `essai` n'est incrémenté que `if self.phase == "essais"`, et `phase` est constante : la clé
    vaut littéralement `("echauffement", 0, "cue")` pour les SIX essais d'échauffement, quelle
    que soit la classe. **La classe n'entre même pas dans la clé** — ce n'est donc pas une
    coïncidence de tirage comme le rapport le présentait, mais une certitude à 100 % des
    séances : 5 tops sur 6 manqués, à chaque fois. Aucun `chk` n'exerce l'échauffement (le
    fixture démarre en `phase: "essais"`). Impact purement audio, mais c'est la justification
    MÊME de `beeps.py` qui tombe : l'étudiant ne doit rien avoir à LIRE au moment de commencer.
- Task 6: minor (deferred): « Durée estimée » vide au tout premier affichage de la page (avant
  toute calibration, `snapshot()["calibration"]` vaut `None`). ⚠️ Ruling : NON envoyé en
  correction — le correctif propre est côté MOTEUR (le contrat n'expose aucune estimation avant
  qu'un runtime existe) ; le faire côté console reviendrait à y recopier la formule de durée,
  ce que la règle du sous-système interdit. À trancher par la revue finale.
- Task 6: minor (deferred): plusieurs assertions du smoke héritées du brief prouvent moins
  qu'il n'y paraît — le `chk` du clic « Commencer » ne vérifie pas la VALEUR de
  `trials_per_class` (une page qui soumettrait 14 en dur passerait) ; la progression est testée
  par sous-chaîne (« 7 » et « 42 ») donc ne prouve pas que les nombres sont aux bonnes places ;
  le briefing est testé par présence, pas par exclusivité.
- Task 6: fix round 1/5 (1 addressed, 0 open ; commit 5aca940). Clé sur FRONT MONTANT de `etape`,
  indépendante de tout compteur. **Preuve fournie : le nouveau test rend `['GAUCHE']` sur le code
  d'avant — un seul top pour six essais — exit 1**, puis vert après.
- Task 6: re-relecture cadrée (11,8 Ko). **ADDRESSED, aucune casse nouvelle.** Les cinq points de
  sévérité sont vérifiés à la main, pas déduits :
  (1) la clé ne lit QUE `etape` et `_etape_precedente` — ni `essai` ni `phase` n'apparaissent, et
      un grep confirme qu'aucune référence à l'ancien attribut ne traîne ;
  (2) l'autre moitié de l'exigence est VRAIMENT testée : le fixture applique deux fois de suite
      le même état `cue` avant d'avancer, pour les 6 essais, et l'assertion est une égalité de
      LISTE ordonnée à 6 éléments — un rejeu parasite décalerait la liste et échouerait ;
  (3) le relecteur a re-simulé l'ancienne clé à la main sur ce fixture et retrouvé exactement
      `['GAUCHE']` — une assertion plus faible (`len > 0`, appartenance) aurait passé le vieux
      code, celle-là ne peut pas ;
  (4) `console.beeps` est restauré dans un `finally`, et aucun autre lecteur de cet attribut
      n'est laissé sans réponse ;
  (5) **le cas limite que je redoutais est prouvé impossible** : `etape` n'est mise à `"cue"`
      qu'en un seul endroit du moteur, appelé depuis trois sites, et dans les TROIS l'étape
      précédente est `""` ou `"repos"` — jamais `"cue"`. Y compris à la frontière
      échauffement → essais. Le seul moyen de défaire le front montant serait un sondage qui
      raterait une fenêtre entière d'imagerie + repos (5,5 s) à 10 Hz : marge de 15 à 40×, et
      c'est une propriété générique préexistante de l'architecture à sondage, pas quelque chose
      que ce diff introduit.
- Task 6: complete (commits 95a62de..5aca940, review clean après 1 tour, 2 mineurs différés)

- Task 7: implémentée (commit e004958, 12 fichiers, +209/-160). ⚠️ **Son agent a été coupé par
  une erreur d'API en rédigeant la fin de son rapport** — mais le travail était commité et le
  rapport écrit (311 lignes). Le coordinateur a relancé **les 14 tests EN SÉRIE lui-même** :
  8 autotests de module, `acquisition --synthetic`, les 3 smokes, et les 2 smokes d'archive →
  tous verts, arbre propre. Les deux tranches de revue concernées ont été prévenues d'être plus
  attentives à ce qui aurait pu rester à moitié fait.

## REVUE DE BRANCHE FINALE — 8 tranches par sous-système (d598d24..e004958, 185 Ko)

Découpage imposé par la mesure du chantier A : 4 relecteurs y étaient morts sur 60-210 Ko, un
seul avait tenu sur 36 Ko — l'échec venait de la TAILLE, pas du modèle. Toutes les tranches
sont sous 40 Ko. Deux d'entre elles (archive, doc) servent AUSSI de relecture de tâche pour T7.

- **Tranche `archive` (33,6 Ko) : 0 critique, 0 IMPORTANT, 2 mineurs. Prête à fusionner.**
  Le relecteur a tracé CHAQUE symbole importé par les deux fichiers archivés jusqu'à sa
  définition réelle (une quinzaine), et vérifié que le calcul de chemin corrige exactement le
  décalage d'un cran. Le README de l'archive est jugé honnête sur les trois points, y compris le
  plus piégeux — l'écrasement sous les anciens noms fixes, vérifié contre le code réel.
  `mi_compare.py` intact. Le nettoyage 6→5 modes est méthodique (imports, fonctions, docstrings,
  argparse, smoke), vérifié par plusieurs greps.
  - minor : `src/research/app.py:852` — le docstring de `mode_neuro` dit encore « Mode 5 » alors
    que son en-tête de section, 19 lignes plus haut, a été renuméroté « Mode 4 ». `mode_errp` a
    bien été traité, celui-ci a été oublié.
  - minor : `archive/mi_pilot.py:91-92` — le message d'absence de modèle dit encore
    « mi_calibrate.py » sans le préfixe `archive/`, alors que les 5 lignes d'usage du docstring
    l'ont toutes reçu. Un utilisateur suivant ce message depuis la racine ne trouverait rien.

- **Tranche `calibration` (39,7 Ko) : 0 critique, 6 IMPORTANTS, ~8 mineurs. À corriger.**
  Les CINQ points coûteux sont vérifiés JUSTES : chaîne d'époques non filtrée de bout en bout,
  orientations cohérentes, `groups` = indice d'essai, non-écrasement structurel (`_chemins_libres`
  teste les DEUX chemins, et celui du modèle ne porte pas `n_essais`, donc il rattrape aussi le
  cas « même seconde, nombre d'essais différent »), aucun fichier sur abandon ou refus.
  **Ce qui manque n'est pas du code juste, c'est de la PREUVE.**
  - **IMP-1 — l'invariant « époques BRUTES » n'est gardé par AUCUN test sur ce chemin.** La garde
    du projet (`acquisition.py --synthetic`) protège `motor_window`, que la calibration N'APPELLE
    JAMAIS. Le chantier a ouvert une SECONDE porte vers `MIModel.fit` sans y remettre la serrure.
    Mutant : insérer `bandpass(reref(...))` avant `decouper` passe les 35 assertions des deux
    autotests ET `_smoke_calibration`. Le `.npz` n'est d'ailleurs jamais relu par aucun test.
    Correctif proposé : faire mémoriser au faux moteur ce qu'il rend, puis comparer les époques
    enregistrées octet pour octet — une assertion qui pinne d'un coup le non-filtrage ET
    l'orientation.
  - **IMP-2** — `recent_window` (server.py) ne porte pas l'avertissement sur le double filtrage :
    il vit sur `motor_window`, méthode que la calibration n'utilise pas. Or `recent_window` est
    désormais À LA FOIS la source des époques d'entraînement ET celle des tracés live. Quelqu'un
    qui trouve les tracés bruyants et filtre là entraînerait le MI sur du signal doublement
    filtré, sans erreur.
  - **IMP-3 — `verdict` n'est jamais recoupé avec la CV honnête. MUTANT CONFIRMÉ SURVIVANT** :
    une implémentation qui calcule `verdict(cv_naive)` tout en gardant `cv_groupee` honnête passe
    les 19 assertions. Or le verdict est LA PHRASE QUE L'ÉTUDIANT LIT, affichée en tête du
    résultat. Correctif : une ligne.
  - **IMP-4** — le modèle est écrit AVANT l'enregistrement. Si `np.savez` échoue (disque plein,
    verrou antivirus), le `.joblib` reste sur disque et apparaît dans la console, sans `.npz` et
    sans provenance. Correctif : écrire le `.npz` d'abord — un `.npz` orphelin est inoffensif.
  - **IMP-5** — la garde de longueur ne détecte pas une époque PÉRIMÉE : `server.recent` ne
    rétrécit jamais, donc sur une coupure Bluetooth `recent_window` rend les mêmes 4 s périmées,
    de longueur PLEINE. Les 54 essais seraient acceptés, identiques, sous trois étiquettes. Le
    CSP dégénère donc le verdict dira « FAIBLE — contact des électrodes » : pas un modèle
    plausible et faux, mais **une séance de sept minutes perdue avec un diagnostic à côté**.
    → à porter au plan de séance matérielle plutôt qu'à la vague de correction.
  - **IMP-6** — la branche « tampon pas rempli » n'est exercée par aucun test, alors que c'est
    elle qui décide ce qui entre dans le jeu d'entraînement.
  - minors notables : `horodatage(maintenant or _time.time())` reproduit EXACTEMENT le bug de
    l'horloge zéro que le commit frère du même jour dit avoir fermé (`0.0` est falsy) —
    inatteignable aujourd'hui, mais c'est un piège posé pour le suivant ; `PHASES`/`ETAPES` sont
    déclarées dans le moteur et jamais importées, la console redéclarant les siennes (le
    « catalogue recopié » que CLAUDE.md interdit) ; `int()` contre `int(round())` entre
    `recent_window` et la garde de longueur divergent dès qu'une durée a une partie
    fractionnaire ≥ 0,5 ; `chk(True, "sérialisable en JSON")` ne prouve rien par elle-même ;
    et **`research/mi_compare.py` pointe encore par défaut sur `data/mi_calib_last.npz`**, le nom
    fixe que ce chantier supprime — seul consommateur des `.npz`, non touché.
  - tri des 5 mineurs différés : corriger AVANT fusion → le recoupement de `verdict`, le test de
    la branche « tampon pas rempli », et le POURQUOI des essais écartés. Ne PAS corriger → la
    comparaison par nom de classe (le vrai câblage est couvert par `_smoke_calibration`, qui
    instancie via `spec.calibration.runtime_cls`) et le TOCTOU (la règle « un seul programme à la
    fois » est une contrainte matérielle du casque).

- **Tranche `moteur` (34,4 Ko) : 0 critique, 5 IMPORTANTS, 8 mineurs. À corriger.**
  Les deux points d'architecture les plus délicats sont JUSTES : les commandes de calibration sont
  placées AVANT le `_one()` qui exige un mode démarré, et `_status_key` prend bien une copie
  locale. Bonus non prévu : la phase `entrainement` est publiée AVANT que l'entraînement ne
  bloque, donc le client reçoit la raison de la pause avant qu'elle arrive.
  - **IMP-1, LE constat de couplage inter-tâches** — agrandir `keep` a **changé la fenêtre de
    mesure de la QUALITÉ**, qui est un flux PUBLIC. `_publish_quality` passe `self.recent` EN
    ENTIER à `sigma_from_block`, qui rend tout le tampon moins la marge : le σ était mesuré sur
    500 échantillons (= `QUALITY_WINDOW_S` = 2 s), il l'est maintenant sur 1000 (= 4 s). La
    constante est devenue fausse, et le couplage est NON BORNÉ — une calibration future à
    `epoch_s = 10` mesurerait la qualité sur 10 s sans que rien ne le dise. Aucun des 14 tests ne
    le verrait (le smoke compte les lignes de qualité, jamais leurs valeurs). Ampleur réelle
    aujourd'hui : la bande 5-40 Hz retire la rampe DC, donc les verdicts ne basculeront pas — ce
    qui est cassé n'est pas la mesure, c'est qu'un consommateur non concerné change quand on
    dimensionne pour un autre. Correctif : une ligne, borner le bloc passé.
  - **IMP-2** — rien ne garantit qu'`epoch_s` reste vrai pour les calibrations À VENIR : c'est une
    DÉCLARATION, et il y a deux sources de vérité pour le même nombre (`Calib.epoch_s` qui
    dimensionne, `CalibrationRuntime.imagery_s` qui prélève). `registry.check()` ne vérifie RIEN
    sur `Calib`. Une future calibration qui déclarerait `imagery_s = 6.0` en oubliant `epoch_s`
    verrait ses époques tronquées EN SILENCE — le défaut même que ce terme existe pour fermer.
  - **IMP-3** — le garde « une seule calibration » n'existe QUE côté `submit`, jamais côté boucle.
    `_start_calibration` écrase `self.calibration` inconditionnellement, alors que ses trois
    voisines (`_set_params`, `_set_published`, `_recalibrate`) re-vérifient toutes. Un
    double-clic sur « Commencer » suffit. Et l'assertion du smoke **contourne exactement la
    fenêtre de course** : elle attend que `server.calibration` existe avant de soumettre.
  - **IMP-4** — `submit` et `snapshot` peuvent LEVER depuis le fil de l'interface : quatre
    endroits lisent `self.calibration` deux ou trois fois au lieu d'en prendre une copie, alors
    que la boucle peut le mettre à `None` entre deux lectures. `submit` promet en toutes lettres
    de ne jamais lever, et le fichier documente ce piège exact 25 lignes plus bas. Conséquence
    composée : **un même `snapshot()` peut rendre `phase: "calibrating"` ET `calibration: null`**
    — deux valeurs contradictoires dans un seul état, ce que sa docstring interdit. Déclencheur
    réaliste : fermer la console pendant une calibration. Corollaire dans `calibration.py` :
    `restant_s` lit `_echeance` deux fois.
  - **IMP-5** — TOUT le chemin d'annulation et de nettoyage ajouté est NON TESTÉ : la commande
    `cancel_calibration` de bout en bout, le retour de `calibrating` à `streaming`, le `finally`
    de la boucle, et **les quatre branches de refus** — qui sont les quatre premiers messages
    qu'un étudiant verra. Coût du comblement : très bas, `submit` ne dépend pas de la boucle.
  - Analyse assertion par assertion des 12 `chk` du smoke : **A7 (`longueurs == {80}`) ne prouve
    RIEN du défaut visé** — avec l'imagerie rabotée à 0,32 s, un tampon resté à 500 rendrait les
    80 demandés sans broncher ; et son commentaire ne le dit pas, contrairement à ses voisines.
    **A8 est LE test du défaut et il tient**, mais à l'égalité stricte (1250 ≥ 1250), sans marge.
    **A12 affirme plus qu'elle ne vérifie** : elle prouve que `validate` accepte, pas que le mode
    démarre ni que le flux apparaît.
  - Les 9 remplacements des smokes sont TOUS restaurés, vérifié un par un ; et les 7 attributs
    remplacés sont bien des attributs PROPRES de `MICalibration`, pas hérités — sinon le motif
    les figerait pour tout le processus.
  - mineurs notables : `produits[0]` sans garde (à corriger, mais pas pour la raison invoquée —
    un build cassé échoue quand même ; ce qui est en jeu est la règle que le fichier s'est donnée
    60 lignes plus haut) ; le `tick` de la calibration n'est pas protégé, donc une exception tue
    le moteur ET perd les époques d'une séance de 7 minutes ; le commentaire du `finally` promet
    plus que le code (c'est `= None` qui casse le cycle, pas `cancel()`, qui ne libère ni
    `engine` ni `_enregistre`).

- **Tranche `decodeur` (14,2 Ko) : 0 critique, 2 IMPORTANTS, 1 mineur. PRÊT TEL QUEL** — les deux
  importants sont des trous de COUVERTURE, pas des défauts du code livré. Le relecteur a REPRODUIT
  ses affirmations plutôt que de les déduire (docstring sklearn 1.9.0 installé, et deux
  reproductions isolées sur la vraie classe `CSP`).
  Les quatre axes sont vérifiés justes : `StratifiedGroupKFold` est le bon outil et il est bien
  câblé (reproduit : avec une seule classe dans un pli, c'est le CSP qui lève sur des NaN, pas la
  LDA — imprécision cosmétique du docstring ; avec deux classes sur trois, `fit` réussit EN
  SILENCE et toute fenêtre REPOS du pli de test est forcément mal classée) ; `n_splits` compte
  bien des ESSAIS uniques et non des fenêtres, doublement vérifié ; `cv_groupee_` reste `None` de
  bout en bout jusqu'à `decrire()`.
  - **IMP-1** — la garde `n_splits < 2` n'est exercée NULLE PART dans le dépôt. Sa sûreté
    actuelle tient à une coïncidence numérique NON DOCUMENTÉE entre deux fichiers : le seuil de
    5 fenêtres/classe de `mi_calib.py` et le ratio fixe de 3 fenêtres/essai de `config.py`.
  - **IMP-2, le plus instructif** — le test de l'invariant ne protège PAS contre une décote
    arbitraire : `cv_groupee_ = 0.85 * cv_`, sans regarder `groups` du tout, satisferait
    `cv_groupee_ < cv_` sur N'IMPORTE QUEL jeu de données et passerait les trois `chk`. C'est le
    défaut du chantier « faussé dans l'autre sens ». Correctif proposé, et il est bon : tester le
    MÉCANISME plutôt que d'inférer depuis un agrégat statistique — énumérer les plis et vérifier
    que les groupes d'apprentissage et de test sont DISJOINTS.
  - minor : le `# noqa: E402` superflu (aucun outil de style dans le dépôt, mais un étudiant qui
    lance flake8 verrait un `noqa` sans avertissement correspondant).
  - hors périmètre, cohérent avec la tranche `calibration` : `mi_calib.py:165` convertit un `None`
    (CV non calculable) en `0.0`, ce qui se lit « 0 % de justesse » au lieu de « non calculé » —
    rompt à cet endroit l'invariant que `decrire()` respecte rigoureusement.

- **Tranche `page` (18,9 Ko) : 0 critique, 1 IMPORTANT, 3 mineurs. À corriger (une ligne).**
  Les quatre axes sont vérifiés justes : aucun coût disque sur le chemin 10 Hz (et c'est
  STRUCTUREL — le seul `Param` de cette calibration a des choix STATIQUES, la méthode coûteuse
  n'est appelée nulle part dans ce fichier) ; l'honnêteté du résultat est tenue sur TOUS les
  chemins d'affichage, vérifiés un par un — aucun ne montre un chiffre seul ; l'audio ne peut
  rien remonter dans le fil Qt (construction ET lecture entièrement sous `try/except`) ; le
  bouton d'abandon est visible pendant les quatre phases.
  - **IMPORTANT — et c'est une CONSÉQUENCE du correctif des tops qu'on vient d'appliquer.**
    `_etape_precedente` n'est jamais réinitialisé, et `_maybe_beep` n'est appelée que si une
    séance est en cours. Le commentaire qui justifie l'absence de remise à zéro est VRAI pour la
    fin normale (qui passe par `etape=""` pendant la phase `entrainement`) mais **FAUX pour
    l'abandon** : `cancel()` fait passer `etape` de `"cue"` à `""` ET `phase` à `"annule"` dans
    le MÊME appel, sans jamais exposer d'état intermédiaire non terminal.
    Scénario : on abandonne pendant le `cue` — le moment le plus probable pour s'apercevoir
    qu'une électrode est mal placée. `_etape_precedente` reste figé à `"cue"`, la page n'est
    jamais recréée, et **le tout premier top de la séance suivante ne sonne pas**. En silence.
    Donc l'étudiant doit LIRE l'instruction du premier essai — exactement la contamination du
    regard que les tops existent pour éviter, sur la séance qu'il vient de relancer pour avoir de
    MEILLEURES données. Et ce n'est pas probabiliste : pour l'abandon la fenêtre non terminale
    n'existe JAMAIS, donc le silence est garanti, pas seulement probable.
    Correctif : une ligne, remettre `_etape_precedente = None` quand aucune séance n'est en cours.
  - minor : les chiffres de la phrase d'honnêteté sont DUPLIQUÉS entre la console et le moteur —
    deux vérités qui divergeront le jour où la séance de référence sera remesurée.
  - minor : `Beeps.disponible` est figé à la construction, donc un cordon débranché EN COURS de
    séance ferait échouer les tops sans que l'avertissement apparaisse (le cas « pas de son dès
    le début » est bien annoncé, lui).
  - tri du mineur différé « durée estimée vide » : **mon raisonnement est confirmé** — la calculer
    côté console dupliquerait exactement la formule du moteur. Mais le relecteur ÉLARGIT le
    diagnostic : ce n'est pas que le premier affichage, ce champ montre TOUJOURS la dernière
    séance ayant réellement tourné, jamais un aperçu du formulaire en cours d'édition. Piste pour
    plus tard : exposer une estimation dans le contrat SÉRIALISÉ (`registry.serialize`), pas dans
    `snapshot()` — c'est une déclaration, pas de la télémétrie, donc elle n'a rien à faire sur le
    chemin 10 Hz.

- **Tranche `doc` (37,0 Ko) : 0 critique, 1 IMPORTANT, 3 mineurs. PRÊTE À FUSIONNER.**
  Le relecteur a lu les QUATRE fichiers en entier, pas seulement le diff, et croisé chaque
  affirmation avec le code. Résultat : **aucune trace résiduelle** de « 6 modes », de
  `mi_calibrate.py` comme chemin d'entraînement, ou de « la console ne démarre pas un mode ».
  Chaque nom, chemin et commande cité existe exactement comme écrit. L'accuracy honnête est
  vérifiée JUSQUE DANS le code de l'interface (`calib_page.py` utilise bien `cv_groupee`, avec un
  commentaire qui dit « jamais `cv_naive` ») — ce n'est donc pas qu'une promesse de la doc. Chaque
  chiffre est accompagné de son niveau de hasard, et la recette porte la phrase exigée par le
  protocole du projet. La durée « 5 à 7 min » a été RECALCULÉE depuis les constantes : ≈5,35 et
  ≈7,05 min, juste.
  **Bonne surprise** : l'implémenteur a aussi corrigé une fausseté de `docs/SPEC.md` §3.1 que mon
  brief ne signalait pas — exactement la chasse que le chantier demandait.
  - **IMPORTANT** — la table « Layout » de `src/console/` dans le README omet `calib_page.py` (la
    fonctionnalité PHARE du chantier, décrite juste au-dessus) et `beeps.py`. La table itemise par
    ailleurs 6 des 8 fichiers du dossier, donc l'omission se voit. Un étudiant cherchant où vit
    l'écran « Calibrer » ne le trouverait pas. Correctif : deux lignes.
  - minor : « All six share one acquisition session and one UI core » (section non touchée) est
    devenu approximatif — le MI tourne désormais entièrement via la console PySide6, un socle
    d'interface distinct des cinq modes restés dans l'appli pygame.
  - minor : le test 1.13 de la recette parle d'un « troisième terminal » en supposant qu'un
    deuxième est resté ouvert malgré une fermeture/réouverture de console entre deux lancements.
  - recommandation : le test 2.6 gagnerait à citer directement « p = 0,082, non significatif »
    plutôt que renvoyer au README — la recette se veut auto-suffisante, et c'est exactement le
    genre de nuance que ce projet tient à ne jamais sous-entendre.

- **Tranche `contrat` (30,8 Ko) : 0 critique, 3 IMPORTANTS, 4 mineurs. Fusionnable avec correctifs.**
  Les trois questions sont répondues : `validate` ne lit que les trois membres que `Calib` déclare
  (vérifié sur TOUS les appelants réels) ; la divergence `channels()` mémoire / `_channels` disque
  est VOULUE et cohérente — chacune répond à une question différente, « que publie ce flux
  MAINTENANT » contre « que proposerait-on par défaut » ; et le seul appelant de production passe
  bien `groups`.
  - **IMP-1** — `registry.check()` ne valide JAMAIS les défauts de `spec.calibration.params`,
    alors que c'est cette tranche qui vient de donner des `params` validables à `Calib`. Or
    `check()` est appelée EN PREMIER par le smoke, explicitement parce qu'« un défaut là-dedans
    explique tous les suivants ». Un défaut invalide traverserait les QUATRE tests verts et ne
    serait découvert qu'au clic « Calibrer ».
  - **IMP-2, ET C'EST LE CONSTAT QUI CONVERGE DEPUIS TROIS RELECTEURS** (contrat, calibration,
    décodeur, chacun par un angle différent) — une CV honnête ABSENTE (`None`) est transformée en
    un chiffre précis et trompeur, à **deux endroits indépendants** : `mi_calib.py:165`
    (`else 0.0`, puis `verdict(0.0)` rend « FAIBLE — ré-essaie : contact des électrodes… », un
    diagnostic SANS RAPPORT avec la vraie cause) et `calib_page.py:244` (`or 0.0`, qui
    re-effondrerait un `None` même si le premier était corrigé). C'est exactement l'inverse de ce
    que la même tranche enseigne ailleurs : `mi_models.decrire()` préserve `None` avec un
    commentaire explicite ET un test dédié, et `mi_decoder` teste le même invariant. **La
    discipline est vérifiée à deux endroits du chantier, puis jetée au moment précis où elle
    atteindrait un étudiant.** Reachability honnête : bloquée aujourd'hui par une coïncidence
    arithmétique NON DOCUMENTÉE entre deux fichiers de deux tranches différentes (le seuil de
    5 fenêtres/classe et le seuil `n_splits >= 2`). Elle se rouvre si l'un des deux bouge, ou si
    des essais sont ignorés en cours de séance — ce que le message « essai IGNORÉ » prévoit pour
    de vraies coupures Bluetooth.
  - **IMP-3, CONVERGE avec la tranche `calibration`** — `research/mi_compare.py` cible encore
    `data/mi_calib_last.npz`, que la nouvelle calibration n'écrit plus, alors que `config.py`
    recommande cet outil « après chaque calibration ». Deux issues : erreur propre sur un dépôt
    neuf, ou **silencieuse** sur ce poste-ci, où un ancien fichier traîne — l'outil analyserait
    indéfiniment une séance périmée sans le dire.
  - minor : `MI_MODEL_PATH` et `MI_KEY_CHANNELS` ne sont plus référencées que par l'archive. Le
    plan anticipait ce nettoyage ; la condition est maintenant vraie.
  - tri : corriger avant fusion → factoriser `Calib.defaults()` / `ModeSpec.defaults()` en une
    fonction commune (coût nul, et ça transforme en garantie STRUCTURELLE ce qui n'est qu'une
    convention) ; traiter ensemble la garde `n_splits < 2` non testée et IMP-2, « le test qui
    manque est précisément celui qui aurait révélé la casse en aval ». Ne bloquent pas → la
    place du bloc de test, le `noqa`, la double numérotation, la branche morte.

- **Tranche `console` (36,6 Ko) : 0 critique, 1 IMPORTANT, 3 mineurs. Prête à fusionner.**
  Les quatre axes tiennent, chacun vérifié en remontant la chaîne d'appel : aucune lecture disque
  sur le chemin périodique (le seul point d'entrée coûteux n'est atteint que par un clic
  « Ouvrir ») ; pas de boucle de rétroaction, et le relecteur confirme que l'absence de
  `blockSignals` sur le nouveau bouton est CORRECTE, pas un oubli — `setText()` n'émet jamais
  `clicked`, contrairement à `setChecked()` ; les deux correctifs de `params_form.py` sont justes
  et prouvés non régressifs (SSVEP et neuro n'ont AUCUN paramètre de type « choix », donc
  structurellement hors d'atteinte) ; les modes hors moteur sont protégés à DEUX niveaux
  indépendants, plus une défense en profondeur côté moteur.
  - **IMPORTANT** — un refus de « Démarrer » n'a AUCUNE trace dans l'interface : la valeur de
    retour est jetée, le refus ne produit qu'un `print` terminal. Scénario le plus probable de
    tout le parcours enseigné par ce chantier : cliquer « Démarrer » sur le MI AVANT toute
    calibration. Le moteur refuse proprement, mais rien à l'écran ne bouge. Le relecteur le
    classe Important et non Critique parce que rien ne ment (le bouton ne bascule pas faussement)
    et parce que `_publier` a EXACTEMENT le même comportement, préexistant à ce chantier.
  - tri des 4 mineurs différés : **les quatre sont à corriger**, 1 à 4 lignes chacun — le
    commentaire absent (seul endroit qui préviendrait un étudiant de ne pas ajouter de validation
    locale), l'assertion « le clic ne mute pas l'étiquette », la VALEUR soumise au clic
    « Commencer », et la progression testée par égalité plutôt que par sous-chaîne (un mutant qui
    inverserait « essai 42 sur 7 » passe le test actuel).

## BILAN DE LA REVUE DE BRANCHE — 8 tranches, 0 CRITIQUE, 19 IMPORTANTS

Comparaison moitié A : 16 importants, 0 critique. Le découpage par sous-système paye une seconde
fois. **Trois constats ont CONVERGÉ depuis des relecteurs indépendants** — c'est ce qui les rend
crédibles : (a) la CV honnête absente transformée en `0.0` puis en verdict « FAIBLE », trouvée par
`contrat`, `calibration` ET `decodeur` par trois angles différents ; (b) `mi_compare.py` qui cible
un fichier que la nouvelle calibration n'écrit plus, trouvé par `contrat` et `calibration` ;
(c) plusieurs tests dont les assertions passeraient sur un mutant, signalés partout.

### ✅ LA CONSOLE A ÉTÉ OUVERTE EN VRAIE FENÊTRE (2026-07-31, une première du projet)

`timeout 25 python src/console/app.py --synthetic` → **exit 124** (tuée par le délai, donc elle a
tenu les 25 s), **aucune trace Python**, LSL initialisé et flux publiés. `Get-Process python`
ensuite : aucun processus resté. La dette la plus ancienne du projet — « tout est vérifié en Qt
`offscreen` » — est donc levée sur le point qui compte le plus : **la console démarre et survit
sur une vraie plateforme graphique**, ce qu'aucun `--smoke` ne prouvait.
⚠️ **CE QUI RESTE NON VÉRIFIÉ, et il faut être précis** : je n'ai PAS pu VOIR la fenêtre (aucune
capture d'écran depuis cette session). Le RENDU — la mise en page, la lisibilité du briefing, le
décompte qui avance, les tops audibles — n'est pas établi. C'est à l'utilisateur de regarder.
- Task 6: dispatchée (la page de calibration, les bips, la liste des modèles). ⚠️ Son étape 8
  (ouvrir la console dans une VRAIE fenêtre) a été explicitement RETIRÉE du périmètre du
  sous-agent — poste partagé. **Elle reste due, et c'est au coordinateur ou à l'utilisateur de
  la faire** : la console n'a jamais été ouverte en fenêtre de tout le projet.
- Task 4: fix round 1/5 dispatché (l'IMPORTANT + le mineur). Correction : sortir la COMPARAISON
  `cv_groupee < cv_naive` du verdict et l'imprimer comme diagnostic, en nommant les deux
  autotests qui vérifient cet invariant là où il a du sens (sur de l'ERD fabriquée) ; GARDER
  `cv_groupee is not None` comme assertion, qui est déterministe.
- Task 4: fix round 1/5 (2 addressed, 0 open ; commit 172f32a).
- Task 4: re-relecture cadrée (diff restreint à `server.py`, 5,8 Ko). **Les deux constats sont
  ADDRESSED, aucune casse nouvelle.** Le point que je craignais est vérifié : la propriété
  déterministe (`cv_groupee is not None`) est RESTÉE un `chk`, elle n'a pas glissé dans le
  `print` avec la comparaison. Le nombre de `chk` de `_smoke_calibration` est inchangé (12 avant,
  12 après) — le correctif remplace un `chk` composite par un `chk` simple plus un `print`, il
  n'en retire ni n'en affaiblit aucun autre. Le commentaire qui renvoie aux deux autotests a été
  vérifié FACTUELLEMENT exact à la source (`mi_calib.py:293`, `mi_decoder.py:327`, tous deux sur
  de l'ERD fabriquée).
- Task 4: minor (deferred): `server.py:1450` — `produits[0]` lèverait `IndexError` si
  l'entraînement échouait et laissait la liste vide. Même famille que le mineur corrigé ce tour.
- Task 4: complete (commits 3d46273..172f32a, review clean après 1 tour, 2 mineurs différés)
