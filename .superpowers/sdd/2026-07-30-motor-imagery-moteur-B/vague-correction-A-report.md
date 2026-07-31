# Vague de correction — LOT A (`src/core/`) — Rapport

## Statut

**DONE** pour les onze constats confiés (A2, A3, A4, A5, A6, A7, A9, A10, A11, A13, A14).
A13 est appliqué **pour sa seule moitié `src/core/`** — la moitié `src/console/` appartient au
Lot B par construction de la mission (« ne touche ni `src/console/` ») ; voir sa section pour le
détail et pourquoi ce n'est pas une correction à moitié mais tout ce qui est faisable dans ce lot.
Aucun autre écart. `git status --short` propre, `data/` n'a gagné aucun `mi_model_*` ni
`mi_calib_*`.

Les douze commandes demandées (contract, registry, runtime, calibration, mi_calib, mi, mi_decoder,
mi_models, acquisition --synthetic, server --smoke, console --smoke, research --smoke) sont
sorties **vertes en série**, une seule à la fois, jamais deux programmes en même temps.

⚠️ Un aller-retour à signaler : ma première rédaction de ce rapport affirmait n'avoir pas retrouvé
le couple `int()`/`int(round())` du premier tiret d'A14. C'était une erreur de relecture, pas un
fait — en revérifiant avant d'envoyer le rapport je l'ai retrouvé (`server.py::recent_window`
contre `calibration.py::_pas_essai`), corrigé, vérifié, et commité à part (commit 6). Voir sa
section plus bas pour le détail ; gardé ici en toute franchise plutôt que discrètement réécrit.

## Commits (6, sur `main`, dans l'ordre)

1. `a8dd0b5` — *Cross-check MI calibration verdict against honest CV, pin raw epochs* — A2, A3
2. `8775bb4` — *Fix calibration base: TOCTOU on restant_s, dead cancel() cleanup, coverage* —
   A6 (corollaire `restant_s`), A10-1, A13 (moitié core), A14 (`chk(True)`, `cancel()` libère
   `engine`/`_enregistre`)
3. `27ef347` — *Cover the n_splits<2 guard and the CV-honesty mechanism in mi_decoder* — A10-2,
   A10-3, A14 (`noqa` superflu)
4. `bf632b1` — *Validate mode calibrations in registry.check(), remove dead code* — A9 (partie
   registre), A14 (`defaults()` factorisé, numérotation + branche morte de `mi.py`)
5. `d353276` — *Fix calibration thread-safety and coverage gaps in the engine* — A4, A5, A6
   (les 4 endroits + `_state`/`snapshot`/`_phase_of`), A7, A9 (partie `keep`), A11, A14
   (`duration_s`, garde `produits[0]`, `tick` protégé)
6. `673337d` — *Round, don't truncate, recent_window's sample count* — A14 (le tiret int/round,
   retrouvé après coup — voir plus haut)

Parent commun : `8e8938c` (HEAD de `main` au démarrage, celui qui couvre déjà A1/A8/A12).

---

## Constat par constat

### A2 — Le verdict n'est jamais recoupé avec la CV honnête

**Fichier** : `src/core/modes/mi_calib.py`.

Ajouté `chk(res["verdict"] == verdict(res["cv_groupee"]), ...)`. Fait à la première tentative sur
la SEULE session principale (`res`, 6 essais/classe) : ses deux CV (45,0 % honnête / 49,3 % naïve)
tombent dans le **même palier** (`UTILISABLE`), donc un mutant `verdict(cv_naive)` n'y change rien
— un test qui n'aurait rien prouvé. Étendu aux deux sessions « rien n'est jamais écrasé » du même
fichier (`premiere`/`seconde`, res1/res2), dont les deux CV **encadrent** une frontière de
`VERDICTS` sur la graine fixe de ce test (45,0 %→71,6 % ; 41,7 %→57,1 %).

**Rouge** (mutant : `verdict_txt = verdict(modele.cv_)` au lieu de `verdict(cv)`) :
```
  OK   le verdict est recalculé depuis la CV HONNÊTE, pas depuis la naïve ('UTILISABLE' == verdict(0.45))
  ÉCHEC et sur ces deux séances aussi, le verdict recoupe la CV honnête, pas la naïve (séance 1 : 'EXCELLENT' pour honnête 0.45, naïve 0.7163636363636363 ; séance 2 : 'UTILISABLE' pour honnête 0.41666666666666663, naïve 0.5709090909090908)
[mi-calib] VERDICT : PROBLÈME
```
(la toute première assertion, sur la session principale, reste verte — confirmant qu'elle seule
n'aurait rien détecté, d'où l'extension aux deux autres sessions.)

**Vert** (mutant retiré) :
```
  OK   le verdict est recalculé depuis la CV HONNÊTE, pas depuis la naïve ('UTILISABLE' == verdict(0.45))
  OK   et sur ces deux séances aussi, le verdict recoupe la CV honnête, pas la naïve (séance 1 : 'UTILISABLE' pour honnête 0.45, naïve 0.7163636363636363 ; séance 2 : 'FAIBLE — ré-essaie : ...' pour honnête 0.41666666666666663, naïve 0.5709090909090908)
[mi-calib] VERDICT : OK
```

### A3 — L'invariant « époques BRUTES » n'est gardé sur aucun des deux chemins

**Fichier** : `src/core/modes/mi_calib.py`.

`_FauxMoteur.recent_window` mémorise maintenant chaque époque rendue (`self.rendus`). Après la
session principale : (1) `len(rendus) == n_essais` (l'échauffement n'appelle jamais
`recent_window`, vérifié par construction de `calibration.py`), (2) le `.npz` est **relu** et sa
forme comparée à `(n_essais, attendu, 8)`, (3) comparaison **octet pour octet**
(`np.array_equal`) entre le `.npz` relu et `rendus`.

**Rouge** (mutant : `enregistre = [(bandpass(reref(e.T), fs).T, l) for e, l in enregistre]` en tête
de `_entrainer`, donc tout ce qui part au `.npz` est filtré) :
```
  OK   le faux moteur a rendu exactement une époque par essai ENREGISTRÉ (18 pour 18 essais)
  OK   le .npz persiste la forme (essais, échantillons, voies), jamais transposée ((18, 1000, 8))
  ÉCHEC et son contenu est OCTET POUR OCTET celui rendu par recent_window — rien ne l'a filtré entre la capture et la sauvegarde
[mi-calib] VERDICT : PROBLÈME
```
(la forme reste identique — bandpass/reref ne changent pas les dimensions — donc seule
l'assertion de contenu tombe : exactement le trou que la version orientation-seule aurait laissé.)

**Vert** (mutant retiré) :
```
  OK   le faux moteur a rendu exactement une époque par essai ENREGISTRÉ (18 pour 18 essais)
  OK   le .npz persiste la forme (essais, échantillons, voies), jamais transposée ((18, 1000, 8))
  OK   et son contenu est OCTET POUR OCTET celui rendu par recent_window — rien ne l'a filtré entre la capture et la sauvegarde
```

Note technique : mon premier essai de mutant appliquait `bandpass(reref(...))` directement sur
l'époque `(n_samp, n_ch)` sans transposer — ça lève (`padlen` de `filtfilt` > la voie de 8
échantillons vue comme « temps »). Corrigé en transposant avant/après, comme le fait `decouper`.
Détail gardé ici parce qu'il illustre concrètement pourquoi l'orientation est aussi fragile que le
filtrage — les deux moitiés de l'invariant se touchent.

### A4 — `recent_window` ne porte pas l'avertissement sur le double filtrage

**Fichier** : `src/core/server.py`. Docstring complétée : elle est désormais présentée comme la
source des époques d'entraînement MI en plus de l'usage afficheur, avec le même avertissement que
`UnicornAcquisition.motor_window` (double filtrage = CSP entraîné sur autre chose que ce qu'il
verra en ligne). Pas de test dédié demandé pour ce constat ; vérifié par lecture croisée avec
`motor_window` et par le fait que `mi_calib.py` (A3 ci-dessus) pinne maintenant l'absence de
filtrage sur ce chemin précis.

### A5 — Le tampon agrandi a changé la fenêtre de mesure de la QUALITÉ

**Fichier** : `src/core/server.py`, `_publish_quality`.

`n = int(round(QUALITY_WINDOW_S * fs)) + margin_n` puis `bloc = self.recent[-n:]`, passé à
`sigma_from_block`/`common_mode` au lieu de `self.recent` entier. La fenêtre de qualité redevient
2 s (+ marge de filtre), indépendante de `self.keep` — donc indépendante d'un futur `epoch_s` de
calibration plus long.

**Vérification « aucun autre consommateur n'a le même défaut »** (demandée explicitement) : grep de
tous les usages de `.recent`/`engine.recent` dans `src/core/`. `neuro.py::_window` borne déjà
(`recent[-n:]`) ; `ssvep.py` et `mi.py` passent par `acq.occipital_window`/`acq.motor_window`, qui
bornent en interne (`block[-need:]`) ; `calibration.py` passe par `engine.recent_window(imagery_s)`,
elle-même bornée. `_publish_quality` était bien la seule fonction à consommer le tampon entier.

Pas de red/green formel demandé ici (item hors de la liste A2/A3/A10/A11) ; la correction est
mécanique et directement lisible sur le nombre d'échantillons passés au filtrage.

### A6 — `submit` et `snapshot` peuvent LEVER depuis le fil de l'interface

**Fichiers** : `src/core/server.py`, `src/core/modes/calibration.py`.

Repris le motif déjà présent dans `_status_key` (copie locale unique, puis usage exclusif de la
copie) aux quatre endroits cités :
- `submit`, branche `start_calibration` : `en_cours = self.calibration` en tête, trois lectures
  (`is not None`, `.terminee`, `.spec.label`) réduites à une.
- `submit`, branche `cancel_calibration` : même motif.
- `_phase_of` : ne lit plus `self.calibration`, reçoit un paramètre `calibration` — signature
  changée en `_phase_of(self, active, calibration)`.
- `_state`/`snapshot` : `_state` exige maintenant un paramètre **nommé, sans défaut**
  `calibration=` (pas `calibration=None` par défaut comme `active=None` : `None` est ICI aussi la
  vraie valeur « aucune calibration », donc un défaut-relit-en-douce aurait annulé la copie prise
  par l'appelant — exactement le bug à fermer). `snapshot()` prend une seule copie
  (`calib = self.calibration`) et la réutilise pour `_state(...)` ET pour le champ
  `"calibration"` du dictionnaire rendu — plus possible d'avoir `phase: "calibrating"` et
  `calibration: null` dans le même appel. Les trois appels internes de `run()` passent
  `calibration=self.calibration` (lecture unique, sûre : c'est le fil qui écrit).

**Corollaire `calibration.py::restant_s`** : copie locale de `self._echeance` avant le test
`is None`, avec le même commentaire de motif que `_status_key`.

Pas de red/green formel demandé (hors liste), la fenêtre de course est réelle mais rare
(uniquement à l'arrêt du moteur) et le changement de signature (paramètre obligatoire) fait qu'un
appelant qui oublierait `calibration=` casse à l'exécution — vérifié par les 12 commandes
officielles et par la relecture complète du diff.

### A7 — Le garde « une seule calibration » n'existe que côté `submit`

**Fichier** : `src/core/server.py`.

`_start_calibration` (côté boucle) refuse maintenant si `self.calibration is not None and not
self.calibration.terminee`, avec un message imprimé et un retour sans effet — même motif que
`_set_params`/`_set_published`/`_recalibrate`. Le smoke `_smoke_calibration` a été réécrit : les
deux premières commandes `start_calibration` (18 puis 10 essais/classe) partent **dos à dos, sans
attendre** — l'ancienne version attendait `server.calibration is not None` avant la seconde, ce
qui la faisait passer par le refus **côté `submit`**, jamais par la fenêtre de course côté boucle.
Une troisième commande, soumise après coup, exerce maintenant le chemin `submit`-refuse que
l'ancienne assertion croyait déjà couvrir.

Pas dans la liste des quatre items à red/green obligatoire, mais j'ai fait la preuve quand même
(la mission souligne que c'est la technique qui a le mieux payé sur ce chantier, et le coût était
nul puisque le smoke existe déjà) :

**Rouge** (mutant : `if False:` à la place du garde dans `_start_calibration`) —
`python -c "..._smoke_calibration()..."` :
```
[server] Calibration Motor Imagery : 54 essais, ...
[server] Calibration Motor Imagery : 30 essais, ...
  ÉCHEC mais côté BOUCLE, la seconde est ignorée : c'est bien la PREMIÈRE (18) qui tourne, pas la seconde (10) ({'trials_per_class': 10})
  ...
  ÉCHEC et snapshot() porte l'état complet, celui de la PREMIÈRE (18×3=54) ({... 'total': 30 ...})
  ÉCHEC 54 essais enregistrés (30)
[smoke-calib] VERDICT : PROBLÈME
```
(la seconde commande écrase bien la première en silence, exactement le défaut décrit — le reste du
test continue et diagnostique en cascade, sans crash brut.)

**Vert** (garde restauré) : `[smoke-calib] VERDICT : OK`, avec « la PREMIÈRE (18) qui tourne » et
54 essais enregistrés — sortie complète dans la section « Tests » plus bas.

### A9 — `registry.check()` ne valide rien sur les calibrations

**Fichiers** : `src/core/modes/registry.py`, `src/core/server.py` (calcul de `keep`).

Dans `check()`, pour chaque mode dont `spec.calibration is not None and
spec.calibration.runtime_cls is not None` : (1) même traitement que les params de mode pour les
défauts de `Calib.params` (y compris la tolérance « choix dynamique vide sur dépôt neuf ») ; (2)
`epoch_s <= 0` → défaut ; sinon (3) `epoch_s < runtime_cls.imagery_s` → défaut nommant les deux
nombres. Les calibrations « natives » (c-VEP, P300, ErrP — `runtime_cls is None`) sont exclues
explicitement : le moteur ne les joue jamais, leur `epoch_s` documentaire n'a rien à valider ici.

Dans `server.py`, le calcul de `epoque_calib` (qui dimensionne `keep`) filtre maintenant sur
`spec.calibration.runtime_cls is not None` en plus de `spec.calibration is not None` — une
calibration native ne peut plus gonfler le tampon (et, via A5, la fenêtre de qualité). **Sans
effet visible aujourd'hui** : aucune calibration native ne déclare `epoch_s` (toutes valent 0.0 par
défaut), donc `keep` reste à 1250 avant et après — vérifié en isolant l'ancien calcul. Le
correctif ferme un trou qui ne s'est pas encore ouvert, pas un bug déjà actif.

Hors de la liste des quatre items obligatoires, mais vérifié par mutation quand même (la mission
insiste sur ce constat précis — « c'est ce qui compte ») :

**Rouge** (mutant : `epoch_s=MI_IMAGERY_S - 1.0` dans `mi_calib.CALIB`) :
```
  ÉCHEC mi : epoch_s=3 s de sa calibration est SOUS imagery_s=4 s de son runtime — chaque époque serait tronquée en silence
[registry] VERDICT : PROBLÈME
```
**Vert** (mutant retiré) : `[registry] VERDICT : OK`, sans ce défaut.

### A10 — Trois trous de couverture, tous confirmés par mutation

**Bullet 1 — branche « tampon pas rempli »** (`src/core/modes/calibration.py`). Sous-classe
`_MoteurTronque(_FauxMoteur)` qui rend une fenêtre UN échantillon plus courte au tout premier
appel de `recent_window` (donc au premier essai de la phase « essais », l'échauffement n'appelant
jamais cet accesseur). Assertion : `essai == total() - 1`.

**Rouge** (mutant : `if epoque is not None:` au lieu de `if epoque is not None and len(epoque) >=
attendu:`) :
```
  ÉCHEC un tampon pas encore rempli au premier essai en ignore UN, pas plus (6 sur 6)
[calibration] VERDICT : PROBLÈME
```
**Vert** :
```
[calib] essai IGNORÉ (A) : 999 échantillons au lieu de 1000 — le tampon du moteur n'était pas encore rempli
  OK   un tampon pas encore rempli au premier essai en ignore UN, pas plus (5 sur 6)
[calibration] VERDICT : OK
```

**Bullet 2 — garde `n_splits < 2`** (`src/core/mi_decoder.py`, nouvelle fonction
`_test_n_splits_insuffisant`). GAUCHE/DROITE : 8 essais distincts chacune (comme d'habitude) ;
REPOS : 10 fenêtres mais UN SEUL essai (même indice de groupe répété).

**Rouge** (mutant : `n_splits = 5` en dur, ignore `par_classe`) :
```
  ÉCHEC mais la CV honnête reste ABSENTE : REPOS n'a qu'UN essai distinct malgré ses 10 fenêtres, `n_splits` tomberait à 1, sous le plancher de 2 (0.65)
[mi-cv-n_splits] VERDICT : PROBLÈME
```
(sans la garde, `StratifiedGroupKFold(n_splits=5, ...)` ne lève pas — elle rend un nombre
plausible et FAUX, 0.65, exactement le mode de panne le plus coûteux du projet.)

**Vert** : `cv_groupee_ = None`, `[mi-cv-n_splits] VERDICT : OK`.

**Bullet 3 — le test d'invariant ne protège pas contre une décote arbitraire**
(`src/core/mi_decoder.py`, dans `_test_cv_honnete`). Espionne `StratifiedGroupKFold.split`
(monkeypatch de la méthode de classe, restauré en `finally`) pendant l'appel réel de `fit()`,
enregistre les groupes train/test de chaque pli, vérifie qu'ils sont disjoints.

**Rouge** (mutant : `self.cv_groupee_ = 0.85 * self.cv_`, sans toucher aux plis) :
```
  OK   la CV groupée est INFÉRIEURE à la naïve : 45.3% contre 53.2% ...
  ÉCHEC le VRAI découpage utilisé par fit() a bien produit au moins 2 plis (0)
[mi-cv] VERDICT : PROBLÈME
```
(preuve directe que l'ancienne assertion, `cv_groupee_ < cv_`, reste VERTE sous ce mutant — 45,3 %
< 53,2 % — exactement le défaut que le relecteur décrit : elle ne regarde jamais `groups`.)

**Vert** : `len(plis_espionnes) == 5`, tous disjoints, `[mi-cv] VERDICT : OK`.

### A11 — Le chemin d'annulation et les quatre refus ne sont pas testés

**Fichier** : `src/core/server.py`, nouvelle fonction `_smoke_calibration_refus`, ajoutée à la
chaîne de `_smoke()`. Six blocs : (1-4) les quatre refus de `submit` sur un moteur **jamais
démarré** (mode inconnu, mode sans calibration — SSVEP —, calibration native — c-VEP, avec le
message qui renvoie vers `python src/research/app.py` —, `cancel_calibration` sans rien en cours) ;
(5) annulation de bout en bout sur un moteur qui tourne : `start_calibration` → boucle l'applique
→ `cancel_calibration` → phase publique revient à `streaming` → `calibration.phase == "annule"` et
`resultat is None` ; (6) arrêt du moteur **en pleine calibration sans annulation explicite** —
prouve que c'est le `finally` de `run()`, pas `cancel()` tout seul, qui libère
`self.calibration`.

**Rouge** (mutant : commente `self.calibration = None` dans le `finally` de `run()`) :
```
  OK   elle est bien appliquée avant l'arrêt du moteur
[server] arrêt : 0 échantillons publiés en 0.1 s (0.0 Hz effectif)
  ÉCHEC arrêter le moteur EN PLEINE calibration, sans l'annuler explicitement, la coupe quand même — c'est le `finally` de run() qui le fait, pas cancel() tout seul
[smoke-calib-refus] VERDICT : PROBLÈME
```
(seul le bloc 6 tombe — les blocs 1-5 restent verts, confirmant qu'ils ne dépendent pas de cette
ligne précise et que le bloc 6 est le seul à l'exercer.)

**Vert** (mutant retiré) : les 12 `chk` passent, `[smoke-calib-refus] VERDICT : OK`.

### A13 — Le vocabulaire des phases est déclaré puis recopié

**Fait, côté `src/core/` uniquement** : `calibration.py` déclare maintenant
`PHASES_TERMINALES = PHASES[-2:]` (dérivée, pas recopiée) et `terminee` s'en sert au lieu du
littéral `("fini", "annule")`. Ça ferme la moitié « `PHASES`/`ETAPES` ne sont importées nulle part,
même pas dans `core` » — `PHASES_TERMINALES` est maintenant un usage réel, avec un nom choisi pour
correspondre exactement à ce que `src/console/calib_page.py` redéclare aujourd'hui de son côté
(`PHASES_TERMINALES = ("fini", "annule")`, vérifié par lecture — pas de modification).

**Non fait, et volontairement** : le correctif que le relecteur écrit en toutes lettres — « que la
console importe la constante » — modifie `src/console/calib_page.py`, explicitement hors
périmètre du Lot A (« ne touche ni `src/console/` »). Je n'ai pas appliqué ce correctif à moitié en
touchant quand même le fichier console ; j'ai fait tout ce qui est faisable côté `core` et je
signale ici, plutôt que d'empiéter, que le dernier pas (un `from core.modes.calibration import
PHASES_TERMINALES` remplaçant la ligne locale dans `calib_page.py`) revient au Lot B — et qu'il est
maintenant trivial grâce au nom déjà aligné.

### A14 — Les petits, groupés

- `int()` contre `int(round())` entre `recent_window` et la garde de longueur — **fait**, commit 6
  séparé. `server.py::recent_window` faisait `n = max(1, int(seconds * self.acq.fs))` (TRONQUE)
  alors que son seul consommateur réel, `calibration.py::_pas_essai`, compare le résultat à
  `attendu = int(round(self.imagery_s * engine.acq.fs))` (ARRONDIT) — et que toute autre
  conversion du même genre dans le fichier (`motor_window`, `occipital_window`, `window_n`,
  `margin_n`) arrondit déjà. À `imagery_s * fs` fractionnaire ≥ 0,5, `n` aurait été strictement
  inférieur à `attendu` : **tous** les essais auraient été jetés comme « tampon pas rempli », pas
  seulement un occasionnel. Inatteignable à 4,0 s × 250 Hz (produit entier — d'où l'absence de
  symptôme aujourd'hui), mais `imagery_s` est explicitement conçue pour être raccourcie. Corrigé
  en `int(round(...))` ; vérifié directement (buffer 250 Hz fabriqué, `seconds = 100.6/250` :
  rend 101 échantillons après le correctif contre 100 avant).
- `produits[0]` sans garde dans le smoke — fait (`server.py`, `_smoke_calibration`).
- Le `tick` de la calibration protégé par `try/except` — fait (`server.py::run`) : marque
  « annulé » avec la raison, laisse le moteur vivre.
- `chk(True, ...)` — fait (`calibration.py`) : capture réellement le résultat de `json.dumps`.
- Le commentaire du `finally` de `run()` / libération dans `cancel()` — fait (`calibration.py`).
- `duration_s=60` → `120` dans le smoke — fait (`server.py`).
- `# noqa: E402` superflu sur l'import sklearn — fait (`mi_decoder.py`).
- Double numérotation « 9. » + branche `hasattr` morte dans `mi.py` — fait.
- `Calib.defaults()`/`ModeSpec.defaults()` factorisées — fait (`contract.py`, `_defaults_of`).

---

## Réserves

Aucune réserve non résolue à date de ce rapport. La seule chose à signaler honnêtement : ma
première passe sur le premier tiret d'A14 (int/round) concluait, à tort, que je ne retrouvais pas
la paire décrite — corrigé avant l'envoi (voir l'avertissement en tête de document et sa section
A14). Après la correction, le smoke complet (`server.py --smoke`, 10/10, et `console/app.py
--smoke`) a été **rejoué intégralement** pour confirmer qu'aucune régression n'a été introduite,
plutôt que de me fier au raisonnement seul.

## Résumé des tests

Douze commandes officielles, en série, toutes sorties à 0 :
`contract.py`, `registry.py`, `runtime.py`, `calibration.py`, `mi_calib.py`, `mi.py`,
`mi_decoder.py`, `mi_models.py`, `acquisition.py --synthetic`, `server.py --smoke` (10/10
sous-verdicts OK), `console/app.py --smoke`, `research/app.py --smoke`. Red/green prouvé pour
A2, A3, A10 (×3), A11 comme exigé, plus A7 et A9 en bonus (hors obligation, mêmes preuves
fournies ci-dessus). `server.py --smoke` et `console/app.py --smoke` rejoués une seconde fois
après le commit 6 (fix int/round), toujours 10/10 et OK. `git status --short` propre après les 6
commits ; `data/` ne contient aucun fichier `mi_model_*`/`mi_calib_*` daté d'aujourd'hui (seuls
des fichiers historiques préexistants à la vague).
