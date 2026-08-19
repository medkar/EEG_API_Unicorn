# Task 4 — le flux, ses métadonnées, et le mode au registre — rapport d'implémentation

Statut : **DONE**
Commit : `8b24ea4` — "Publish the ErrP as the engine's fifth mode, operating point included"
Base : `362fee1` (HEAD de `main` avant cette tâche, correction de revue de la tâche 3)

## Ce qui a été fait

Quatre fichiers modifiés (+137/-54), le rapport et le brief restant hors du commit, comme pour les
tâches 1 à 3 (`git log` ne trouve toujours rien sous `.superpowers/sdd/2026-08-18-errp-moteur/`).

**`src/core/lsl_io.py`** — `errp_channel_labels()` et `DecodedErrPPublisher`, repris **verbatim**
du brief (Step 1), insérés juste après `DecodedP300Publisher`. Deux ajouts non demandés
littéralement mais mineurs et dans le style du fichier :
- la liste des flux dans la docstring du module passe de sept à huit (`decoded_errp` inséré à sa
  place, entre `decoded_p300` et `status`) — un fichier qui promet d'être auto-documenté ne peut
  pas omettre son propre huitième flux ;
- une section 8 dans `_autotest()`, sur le même modèle que les sections 5/6/7 (MI, P300,
  `no_decision_index` du SSVEP) : construit un `DecodedErrPPublisher` avec un point de
  fonctionnement connu, pousse un verdict et un refus, puis relit **chacun** des cinq champs de
  métadonnées (`threshold`, `tnr_target`, `tpr_measured`, `tnr_measured`, `calibration_epochs`,
  `no_decision_index`) et les compare à ce qui a été passé en entrée. C'est le SEUL endroit où la
  construction réelle du publieur est exercée : ni `errp.py::_selftest` (qui bouchonne `_out`,
  comme `p300.py` et `mi.py` le font déjà pour eux-mêmes) ni `server.py --smoke` (qui ne démarre
  jamais l'ErrP pour de vrai, faute de modèle disponible dans un dépôt cloné) ne le font.

**`src/core/modes/registry.py`** — `errp` ajouté à l'import ; `errp.SPEC` inséré dans `MODES` juste
après `p300.SPEC` (2e client du tuyau des marqueurs) et avant `external.CVEP` ; `external.ERRP`
retiré. Commentaires mis à jour verbatim sur le modèle du brief.

**`src/core/modes/external.py`** — la constante `ERRP` supprimée. Docstring du module réécrite :
elle décrivait deux entrées et citait l'ErrP nommément ; il n'en reste plus qu'une (c-VEP). La
phrase « le MI et le P300 ont rejoint le moteur » devient « le MI, le P300 et l'ErrP » (même geste
que les deux migrations précédentes avaient déjà appliqué à cette même phrase) ; le paragraphe final
sur les raisons d'absence ne parle plus que du c-VEP, et note au passage ce qui le distingue
structurellement du P300/ErrP (aucun lien avec les marqueurs, contrairement à eux).

**`src/core/modes/errp.py`** :
- import `DecodedErrPPublisher, errp_channel_labels` depuis `core.lsl_io` ;
- `_open()` construit désormais le vrai publieur : `DecodedErrPPublisher(self.
  point_de_fonctionnement, n_calib=len(self.model.oof_y_), instance=self.engine.instance)`.
  `n_calib` n'était pas spécifié par le brief (l'interface ne donne que la signature du
  constructeur) — `ErrPModel` ne porte pas d'attribut `n_epoques_` dédié (contrairement à
  `P300Model`, cf. `errp_models.decrire`), donc j'ai pris l'effectif de `self.model.oof_y_` : c'est
  exactement le nombre d'essais que `pick_threshold` a déjà consommé pour produire `self.seuil`,
  donc la mesure honnête de ce sur quoi ce point de fonctionnement repose ;
- `_publish()` fait transiter `self.seuil` jusqu'à `self._out.push(error, score, self.seuil,
  artefact, lsl_ts)` — le seuil est publié à CHAQUE échantillon, pas seulement dans les métadonnées
  de l'outlet : un client qui n'a capturé que le flux de données (un enregistrement XDF sans sa
  description LSL, par exemple) sait quand même contre quoi `score` a été comparé. `self._decoded`
  gagne une clé `"threshold"`, par symétrie avec `DecodedSSVEPPublisher`/`DecodedMIPublisher` (tous
  deux exposent déjà `threshold` dans leur sortie `output()` — le P300 seul ne le fait pas, parce
  qu'il n'a structurellement pas de seuil absolu, cf. `live_views.ActiveView`) ;
- `SPEC` gagne `stream="decoded_errp"` et `channels=tuple(errp_channel_labels())` — une seule
  fonction nomme les voies pour le publieur ET le contrat, comme demandé ;
- `_selftest` mis à jour pour la nouvelle signature `push(error, score, seuil, artefact, lsl_ts)` à
  5 arguments (`_FauxPublieur` et les quatre comparaisons de tuple qui en dépendaient), plus deux
  assertions neuves (voir comptage) ; un `unpacking` à 4 variables (`e_derive, _s_derive, art_derive,
  _t_derive = rt2._out.lignes[-1]`, dans la preuve rouge-puis-vert de la tâche 2) aurait levé
  `ValueError: too many values to unpack` sur le nouveau tuple à 5 — trouvé en relisant tout le
  fichier après les remplacements ciblés, pas par l'exécution seule (ce site n'est pas dans le
  chemin que les diffs suivants font rougir), corrigé dans la même passe.

## Comptage des assertions (méthode excluant `def chk(cond, msg):`)

`grep -c "chk("` sur `errp.py` **avant** cette tâche : 62 occurrences − 1 pour `def chk(cond, msg):`
= **61 sites**, confirmé identique au chiffre du brief et à celui du rapport de la tâche 3. **Après** :
64 occurrences − 1 = **63 sites** → **+2**. Aucun site retiré ; deux nouveaux :
- le contrat du `SPEC` (`SPEC.status == "moteur" and SPEC.stream == "decoded_errp"`) split en DEUX
  `chk` au lieu d'un (l'ancien testait `SPEC.stream is None`, devenu faux par construction ; le
  second vérifie les voies via `SPEC.channels_for(values) == errp_channel_labels()`) ;
- `seuil_pub == rt.seuil` sur le chemin du vrai modèle, juste après l'unpacking à 5, pour prouver
  que le seuil publié est bien celui contre lequel `score` vient d'être comparé, pas une constante.

Tous les autres sites touchés ont leur **tuple étendu** (seuil inséré en 3e position) ou leur
**message reformulé**, condition inchangée par ailleurs.

## Tests lancés, dans l'ordre

Garde-fou avant chaque lancement : `Get-Process python -ErrorAction SilentlyContinue` → aucun
processus (le code de sortie 1 de la commande elle-même signale l'absence de résultat, pas un
échec — vérifié dans la doc de l'outil).

1. `python src/core/lsl_io.py` → `[lsl] VERDICT : OK`, section 8 (decoded_errp) verte, `EXITCODE=0`.
2. `python src/core/modes/registry.py` → **« 7 modes, dont 6 dans le moteur »** (exactement le
   commentaire attendu par le brief), `errp` listé `● moteur`, seul `cvep` reste `○ appli_pygame`,
   `[registry] VERDICT : OK`, `EXITCODE=0`.
3. `python src/core/modes/errp.py` → **63/63 `OK`, 0 `ÉCHEC`**, `[errp] VERDICT : OK`, `EXITCODE=0`.
4. `python src/core/server.py --smoke` → lancé **deux fois** (par prudence sur l'instabilité connue
   de `[smoke-tampon]`) : les deux fois `EXITCODE=0`, les 17 sous-smokes verts chacune des deux
   fois, `[smoke-tampon] VERDICT : OK` compris — **l'instabilité mentionnée dans le brief n'a pas
   reproduit** sur mes deux lancements (rien à signaler côté `git stash`, elle ne s'est simplement
   pas manifestée).
5. `python src/console/app.py --smoke` → `EXITCODE=0`, `[console-smoke] VERDICT : OK`. Vérifié
   précisément l'assertion visée par le brief : `exactement les modes que le moteur ne fait pas ont
   une tuile grisée (['cvep'] pour ['cvep'])` — verte sans avoir touché le fichier, comme annoncé.
6. Bonus, non demandé mais peu coûteux : `python src/core/modes/contract.py` → `EXITCODE=0`,
   `[contract] VERDICT : OK`, avec 4 nouvelles lignes vertes propres à `errp` (`client_snippet`
   produit un extrait Python valide, qui nomme le vrai flux, toutes les voies annoncées, et
   `open_stream`) — confirme que le générateur d'exemple de la console fonctionne pour ce mode sans
   qu'aucune ligne n'ait eu à le savoir spécifiquement.
7. Après commit, relance de `python src/core/modes/errp.py` sur l'état commité (belt and
   suspenders) : `EXITCODE=0`, verdict OK de nouveau.

Garde-fou vérifié une seconde fois en tout fin de tâche (`Get-Process python`) : deux processus
Python trouvés, mais ni l'un ni l'autre n'est ce projet — `Get-CimInstance Win32_Process` montre
leurs lignes de commande : `scripts/run_all_tests.py` et
`...\Promptuino\promptuinoUI\scripts\test_progress_nudge.py`, un projet sans rapport. Aucun des
trois programmes d'EEG_API_Unicorn (`server.py`, `console/app.py`, `research/app.py`) n'est
concerné ; je ne les ai pas touchés (pas les miens, aucun risque de collision de flux LSL avec ce
qui a été testé ici).

## Inquiétudes

1. **Le brief ne contenait aucune erreur mesurable, contrairement aux trois tâches précédentes.**
   J'ai vérifié chaque affirmation contre le code réel (signature de `push`, comportement de
   `registry.check()`, l'assertion exacte du smoke console) plutôt que de les prendre pour
   acquises, et tout correspondait. Le seul point laissé à mon appréciation — la source de
   `n_calib` — n'est pas une « affirmation » du brief à vérifier, juste une interface à remplir ;
   justifiée ci-dessus.

2. **Trouvaille indépendante, hors périmètre de cette tâche : la page console de l'ErrP n'affichera
   RIEN en direct.** `src/console/live_views.py::PassiveView.update_from` lit
   `sortie.get("z")` — un dict imbriqué sous la clé `"z"`, la forme QUE `DecodedNeuroPublisher`/
   `NeuroRuntime` produit. La sortie de l'ErrP (`{"error", "score", "artefact", "threshold"}`) n'a
   jamais cette clé, donc `PassiveView` tombe systématiquement dans sa branche « rien à montrer » et
   affiche l'instruction de repos, puis une chaîne vide une fois en régime (aucune instruction en
   phase `running`). Aucun crash — la tuile/grille et le smoke restent verts — mais aucun verdict
   ErrP ne sera visible dans la console tant que ce fichier n'apprend pas sa forme, sur le modèle de
   ce qu'`ActiveView` fait déjà pour distinguer SSVEP/MI/P300 par les clés présentes dans `output()`.
   Non corrigé ici : `live_views.py` n'est dans la liste d'aucune tâche de ce chantier (les 6 tâches
   du plan s'arrêtent à la documentation), c'est un fichier partagé par TOUS les modes passifs/actifs
   et le modifier pour l'ErrP seul aurait débordé largement le périmètre annoncé de cette tâche («
   celle qui rend le mode visible sur le réseau et dans la grille », pas dans le rendu détaillé
   d'une page). Signalé pour qu'un chantier futur (ou un correctif ciblé) sache où regarder.

3. **`.superpowers/sdd/.gitignore` retrouvé réinitialisé à son `*` d'origine en début de tâche**,
   effaçant les règles `!*.md`/`!*/`/`!.gitignore` que ce projet a délibérément ajoutées le
   2026-07-31 pour garder les carnets de chantier suivis. Ce n'est PAS un changement que j'ai fait
   ni voulu committer — restauré via `git checkout -- .superpowers/sdd/.gitignore` avant tout `git
   add`, donc absent du commit de cette tâche (`git status` le confirme : plus aucune modification
   sur ce fichier après restauration). C'est un régression CONNUE et RÉCURRENTE de ce dépôt : `git
   log` montre au moins trois commits antérieurs de récupération pour ce même symptôme sur d'autres
   chantiers (`ec70ae7`, `1b48a5e`, `1f702f9`, tous titrés « Recover ... from an untracked .gitignore
   regression »). Les rapports/briefs des tâches 1 à 4 de CE chantier sont d'ailleurs toujours
   untracked à ce jour (confirmé : `git log --diff-filter=A` ne trouve rien sous
   `2026-08-18-errp-moteur/`) — cohérent avec le fait que chaque tâche committe uniquement son code,
   jamais son propre carnet. Je n'ai pas cherché à « réparer » ce schéma plus largement (hors
   périmètre de cette tâche), seulement à ne pas aggraver la régression ponctuelle rencontrée.

---

# Tour de correction 1 — rendre la sortie ErrP visible dans la console

Statut : **DONE**
Commit : `d08ef71` — "Give the ErrP a face in the console: score, threshold, and honesty"
Base : `8b24ea4` (le commit initial de cette tâche)

Le coordinateur a confirmé la conformité au brief d'origine SANS réserve, et a ÉTENDU ma trouvaille
hors périmètre (round précédent) : le silence n'est pas seulement dans `live_views.py`, il est
AUSSI dans `grid.py` (aperçu de la tuile + résumé), par le même défaut — un aiguillage par clé qui
ne connaît que les formes de sortie déjà existantes. Trois demandes, traitées dans l'ordre.

## Ce qui a été fait

**1. Le rendu, aux deux endroits, aiguillé sur la clé `"error"` (jamais sur l'identifiant du mode)** :

- `src/console/live_views.py::PassiveView.update_from` — nouvelle branche `if "error" in sortie:`,
  AVANT le test `z = sortie.get("z")`, qui route vers une méthode neuve `_update_errp`. Suit
  exactement le patron déjà écrit pour `ActiveView` (router sur ce que la sortie DÉCLARE), appliqué
  ici à la famille « passif », qui n'avait jamais eu qu'UNE forme de sortie jusqu'ici (le neuro).
- `src/console/grid.py::ModeTile.update_from` (aperçu `MiniBars`) — nouvelle branche
  `elif "error" in sortie:`, AVANT le `else` final.
- `src/console/grid.py::_resume` — nouvelle branche `if "error" in sortie:`, avant le repli sur
  `params`/`""`.

**2. Ce que le rendu dit — le point qui compte.** Nulle part `error=1` n'est montré seul :
- La page (`self.etat`, le verdict) distingue QUATRE textes différents, un par cas : `ERREUR
  détectée (score au-dessus du seuil)` / `correct (score sous le seuil)` / `— PAS DE VERDICT :
  époque hors du tampon` / `— PAS DE VERDICT : fenêtre rejetée (artefact...)`. Aucun des deux
  derniers ne contient jamais le mot ERREUR ; les deux premiers ne se confondent jamais avec eux.
- La page (`self.avertissement`, chiffré) montre TOUJOURS score et seuil côte à côte
  (`score +5.044 contre seuil +0.044`), suivis — quand `point_de_fonctionnement` est disponible —
  du taux RÉELLEMENT mesuré : `détecteur IMPARFAIT : garde 93% des bonnes commandes, attrape 46%
  des erreurs (visé 85%) — un verdict « erreur » est une pièce biaisée, pas une certitude.` Quand
  `error<0`, ni score ni seuil ne sont montrés (ils valent 0.0 par CONVENTION, jamais une mesure —
  cf. `ErrPRuntime._traiter_feedback` : afficher ce zéro le ferait passer pour une valeur lue).
- La tuile (aperçu `MiniBars`) montre deux valeurs signées, `[score, seuil]`, sur une échelle
  self-scaling (`span=max(abs(score), abs(seuil), 1.0)`) — JAMAIS `NEURO_Z_SPAN` (un z n'a rien à
  voir avec un log-odds) ni un axe fixe inventé. Vide quand `error<0`, pour la même raison de
  convention que ci-dessus.
- Le résumé de la tuile (`_resume`) porte le verdict ET le taux d'erreurs attrapées dans la MÊME
  ligne : `ERREUR détectée · score +5.04 · attrape 46% des erreurs`.

`point_de_fonctionnement` (tpr/tnr MESURÉS, pas seulement `tnr_target` VISÉ) n'existait nulle part
côté client avant ce tour : ajouté à `ErrPRuntime.state()` (PAS à `output()` — c'est une mesure de
SESSION, posée une fois en `__init__`, contrairement à `threshold` qui EST publié à chaque
échantillon). La console est un CLIENT du moteur : sans ce champ dans `state()`, aucun rendu,
aussi bien conçu soit-il, n'aurait pu le montrer.

**3. Le mineur : `"artefact"` (français) → `"artifact"` (anglais) dans `ErrPRuntime._decoded`**,
alignée sur `ssvep.py`/`neuro.py` et sur le libellé de voie LSL lui-même (`errp_channel_labels()`
→ `"artifact"`). C'était bien un piège prêt à mordre : mon propre premier jet de `_update_errp`
lisait `sortie.get("artifact")`, qui aurait silencieusement lu `None` (donc toujours faux) sans
cette correction faite EN AMONT.

## Preuve ROUGE-PUIS-VERT

Écrite dans l'ordre inverse de l'habitude de ce chantier (le test D'ABORD, contre le rendu
NON corrigé) plutôt que par mutation d'un code déjà correct — parce que le rendu n'existait tout
simplement pas encore.

**ROUGE** (11 assertions neuves ajoutées à `console/app.py::_smoke`, exécutées contre
`live_views.py`/`grid.py` D'AVANT ce tour — aucune touche) :
```
EXITCODE=1
  ÉCHEC un score au-dessus du seuil se lit comme une détection ('')
  ÉCHEC ...le score ET le seuil, CHIFFRÉS, côte à côte, jamais l'un sans l'autre ('z contre TON repos du jour, mesuré au démarrage du mode. Ni comparable entre personnes, ni entre séances, ni absolu. À lire en TENDANCE.')
  ÉCHEC ...ET le point de fonctionnement MESURÉ (pas seulement visé) : ... ('z contre TON repos du jour, mesuré au démarrage du mode. ...')
  ÉCHEC « pas de verdict » (-1, époque perdue) est un texte DIFFÉRENT de « correct » (0), et ne parle jamais d'erreur ('' vs correct='')
  ÉCHEC ...et un refus pour ARTEFACT se distingue lui aussi d'une époque simplement perdue ('' vs perdu='')
  ÉCHEC la tuile montre score ET seuil, signés, sans rien mettre en avant ([])
  ÉCHEC le résumé de la tuile porte le verdict ET le point de fonctionnement ("Un verdict par feedback affiché : la machine vient-elle de se tromper (potentiel d'erreur).")
[console-smoke] VERDICT : PROBLÈME
```
7 assertions rouges sur 11 : les 4 qui ne rougissaient pas le faisaient pour de bonnes raisons
(page bien de la classe `PassiveView` — la famille ne dépend pas du rendu ; `"ERREUR" not in ''`
est vacuement vrai ; la tuile vide vaut `[]` avant ET après). Le texte capturé — une chaîne VIDE
pour le verdict, le texte STATIQUE du neuro pour l'avertissement, `[]` pour l'aperçu, le résumé
STATIQUE du mode — est EXACTEMENT ce que le coordinateur avait décrit : un silence, pas un mensonge.

**VERT** (même 11 assertions, `live_views.py`/`grid.py` corrigés) :
```
EXITCODE=0
  OK   un score au-dessus du seuil se lit comme une détection ('ERREUR détectée (score au-dessus du seuil)')
  OK   ...le score ET le seuil, CHIFFRÉS, côte à côte... ('score +5.044 contre seuil +0.044 · détecteur IMPARFAIT : garde 93% des bonnes commandes, attrape 46% des erreurs (visé 85%) — un verdict « erreur » est une pièce biaisée, pas une certitude.')
  OK   un score sous le seuil ne parle plus d'erreur ('correct (score sous le seuil)')
  OK   « pas de verdict » (-1, époque perdue) est un texte DIFFÉRENT de « correct » (0)... ('— PAS DE VERDICT : époque hors du tampon' vs correct='correct (score sous le seuil)')
  OK   ...et un refus pour ARTEFACT se distingue lui aussi d'une époque simplement perdue ('— PAS DE VERDICT : fenêtre rejetée (artefact, σ au-dessus du repos)' vs perdu='— PAS DE VERDICT : époque hors du tampon')
  OK   la tuile montre score ET seuil, signés, sans rien mettre en avant ([5.044, 0.044])
  OK   ...et rien quand il n'y a rien à montrer, pas un 0.0 fabriqué ([])
  OK   le résumé de la tuile porte le verdict ET le point de fonctionnement ('ERREUR détectée · score +5.04 · attrape 46% des erreurs')
[console-smoke] VERDICT : OK
```
Les 11/11 nouvelles assertions passent ; 0 `ÉCHEC` sur l'ensemble du fichier (105 assertions
préexistantes + 11 neuves = 116, toutes vertes).

## Comptage des assertions (méthode excluant `def chk(`)

- `errp.py` : **63 avant, 63 après** — inchangé (seul le TEXTE d'une assertion déjà existante a
  été mis à jour, pour la nouvelle clé `"artifact"` ; aucun `chk(` ajouté ni retiré).
- `console/app.py` : **105 avant** (`git show 8b24ea4:src/console/app.py`, moins la ligne `def
  chk`), **116 après** → **+11**, exactement les 11 sites du bloc ErrP ci-dessus. Aucun site
  préexistant retiré ni affaibli — vérifié par diff : le nouveau bloc est une INSERTION pure entre
  la section P300 et la section calibration, aucune ligne antérieure touchée.

## Tests lancés, dans l'ordre

Garde-fou avant chaque lancement : aucun `server.py`/`console/app.py`/`research/app.py` en cours
(`Get-CimInstance Win32_Process` filtré sur `EEG_API_Unicorn`, vide à chaque fois).

1. `python src/core/modes/errp.py` → `EXITCODE=0`, `[errp] VERDICT : OK`, **65 `OK` / 0 `ÉCHEC`**
   (63 sites statiques ; le site bouclé de la tâche 3 — monotonie sur 3 cibles — en exécute 3,
   donc 65 lignes `OK` pour 63 `chk(` du source, même mécanique que documentée au rapport de la
   tâche 3).
2. `python src/console/app.py --smoke` :
   - AVANT le correctif (rendu non touché) → `EXITCODE=1`, preuve ROUGE ci-dessus.
   - APRÈS le correctif → `EXITCODE=0`, `[console-smoke] VERDICT : OK`, preuve VERTE ci-dessus.
3. `python src/core/server.py --smoke` → `EXITCODE=1` sur `[smoke-tampon]` (« et la cadence
   médiane vaut ~1/fs (0.01 ms attendu 4.00 ms) »), **les 17 autres sous-smokes verts**, quatre
   lancements de suite. Vérifié par `git stash` comme demandé : sur l'arbre COMMITÉ, propre,
   SANS aucune des modifications de ce tour (`server.py` n'a d'ailleurs jamais été touché par cette
   tâche, ni round 1 ni round 2), le MÊME échec, au mot près, reproduit à l'identique. Instabilité
   connue et préexistante, confirmée hors de mon diff — round 1 avait eu deux lancements verts sur
   deux ; ce tour en a quatre rouges sur quatre, ce qui suggère une sensibilité au CHARGEMENT du
   poste plus qu'un hasard pur (`_smoke_tampon_horodate` mesure une cadence RÉELLE, sur l'horloge
   murale — le genre de test qu'une machine partagée peut faire varier), mais le test de `git
   stash` est sans ambiguïté : le défaut n'est pas dans ce diff.

## Inquiétudes

1. **`[smoke-tampon]` a été rouge sur les quatre lancements de ce tour**, contre deux verts sur
   deux au tour précédent, dans la MÊME session. Rien dans mon diff n'explique la différence
   (aucun fichier touché par `server.py`/`acquisition.py`), et la preuve par `git stash` l'écarte
   formellement — mais la fréquence a de quoi interpeller pour quiconque suit ce test de près : si
   elle continue à grimper, une prochaine tâche voudra peut-être fiabiliser `_smoke_tampon_horodate`
   lui-même (moins sensible à la charge machine), plutôt que de la vérifier au cas par cas à chaque
   tour de correction.
2. **`.superpowers/sdd/.gitignore`** vérifié de nouveau en fin de ce tour : toujours intact (le
   correctif du round précédent tient).
3. Rien d'autre trouvé de comparable au défaut `grid.py`/`live_views.py` en auditant les DEUX
   fichiers en entier pendant ce tour — mais je ne les ai pas audités mode par mode au-delà de ce
   que ce tour demandait (l'ErrP). Le défaut symétrique repéré au tour précédent côté P300
   (`grid.py::ModeTile.update_from` retombe dans la branche `"scores"`/`threshold` avec `Z_MIN` en
   repli, faute de clé `"threshold"` dans la sortie du P300 — le même mécanisme que celui documenté
   et déjà CORRIGÉ dans `live_views.py::ActiveView`, mais pas ici) **reste NON corrigé** : toujours
   hors du périmètre confié pour ce tour (l'ErrP, nommément), et le corriger maintenant aurait
   touché un troisième mode sans qu'aucun coordinateur ne l'ait demandé.
