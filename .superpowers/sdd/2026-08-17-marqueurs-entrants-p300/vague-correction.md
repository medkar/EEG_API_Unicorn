# Vague de correction — revue finale de branche (2026-08-18)

Sept tranches relues en parallèle sur le modèle le plus capable. **8 critiques, ~25 importants**,
sur du code qui avait déjà passé 7 relectures par tâche ET leurs tours de correction.

⚠️ **Aucun de ces défauts n'était visible depuis une seule tâche.** C'est ce que la revue finale
existe pour attraper, et c'est vérifié une quatrième fois sur ce projet.

Découpage en **3 lots par sous-système**, sans recouvrement de fichiers. Ils lancent tous des
smokes, donc ils s'exécutent **en séquence**, jamais en parallèle.

---

## LOT 1 — l'oreille et le moteur

**Fichiers : `src/core/markers.py`, `src/core/server.py`, `src/core/config.py`.**

### Critiques

**1.1 — `markers.py:84` : `time_correction()` sans timeout FIGE LE MOTEUR ENTIER. (mesuré)**
Émetteur tué dans la fenêtre, avec `source_id` : appel **toujours bloqué au bout de 26 s**, sans
exception (`recover=True` attend le retour du fournisseur). `resolve()` étant appelé depuis `run()`,
plus de `get_new_data()` (le tampon BrainFlow déborde), plus un seul flux publié — **y compris pour
le SSVEP, le neuro et le MI qui tournaient à côté** — et Ctrl-C ne peut pas interrompre un appel C
bloquant. Contredit mot pour mot la docstring de la classe : « Ne bloque jamais la boucle du
moteur ». → Borner `time_correction(timeout=…)`.

**1.2 — `markers.py:77-84` : `resolve()` n'est pas atomique.** `self.inlet` est affecté AVANT
`open_stream()` et `time_correction()`. Mesuré : un émetteur SANS `source_id` (le défaut de LSL,
donc l'émetteur qu'un étudiant écrira) mourant dans la fenêtre lève `LostError` en ~4 s. Deux
issues, toutes deux mauvaises :
- au **premier** appel, `server.py:830` appelle `resolve()` **hors de tout `try`** et `run()` n'a
  aucun `except` → **l'exception tue la boucle du moteur** ; en console le fil meurt et la fenêtre
  Qt reste gelée. L'invariant « une application cliente mal écrite ne doit jamais pouvoir tuer le
  moteur » tombe.
- en **re-tentative**, `_tire_marqueurs` attrape, mais l'objet reste `connecte=True` avec
  `offset=0.0` → **le moteur se croit connecté et n'applique plus aucune correction d'horloge** :
  la catastrophe des 45 jours, en silence total.
→ Construire dans une variable LOCALE, borner le timeout, n'affecter `self.inlet`/`self.offset`
qu'après succès complet, rendre `False` sinon.

**1.3 — `markers.py:74-77` : deux émetteurs du même nom, `minimum=1` puis `flux[0]`, sans un mot.**
Mesuré : rend l'un des deux — pas même le premier lancé — et ne lit que celui-là. Or les étudiants
utilisent tous le nom par défaut et LSL porte sur tout le réseau : **un moteur peut épocher sur les
flashs du voisin** (ou d'un stimulus oublié, le piège récurrent de ce projet) et publier des
sélections confiantes et fausses. **Le projet a déjà le motif inverse côté sortant** (`lsl_io.py:463`
et `server.py:1152` : `minimum=32` puis filtre sur `source_id`) — l'oreille est le seul endroit qui
ne l'applique pas. Mesuré : `minimum=32, timeout=0.2` révèle les deux en 0,2 s.
→ Appliquer le motif de la maison, et **DIRE** quand plusieurs flux du même nom sont vus.

**1.4 — `server.py:847-857` + `:256-269` : relancer l'émetteur rend le moteur MUET pour toujours.
(mesuré)** L'inlet n'est re-résolu que `if not connecte` ; `connecte` reste `True` à vie ;
`recover=True` fait retenter l'ANCIEN `source_id` ; et l'émetteur le déclare par PID, donc il ne
revient jamais. Aucune exception, `marqueurs_inlet_erreurs` reste 0, **et redémarrer le mode n'y
change rien**.
```
[B] emetteur #1 vivant : 13 marqueurs | [C] ferme : 1 | [D] #2 RELANCE : 0 -> MUET POUR TOUJOURS
[E] un inlet NEUF : 13 -> le flux #2 est bien present sur le reseau
```
« Je ferme le stimulus et je le relance » est un geste de routine en TP.
→ Libérer `self.marker_inlet = None` (et vider `_marqueurs`) dans `_stop_mode` dès qu'aucun mode
actif n'écoute, ET lâcher l'inlet sur `LostError` pour que la re-résolution reprenne.

### Importants

**1.5 — un inlet perdu ne redevient jamais « non connecté ».** Mesuré : 310 exceptions en 20 s,
`server.py:856` imprime **20 fois par seconde sans limitation**, et le moteur ne re-résout jamais.
→ Même correctif que 1.4, plus une limitation du message.

**1.6 — `_marqueurs` croît sans borne dès que le dernier écouteur s'arrête.** `_purge_marqueurs`
fait `if not ecouteurs: return`, **l'inverse exact de sa propre docstring** (« ce que TOUS les
écouteurs ont dépassé » : sans écouteur, tout l'est). ~5 Mo / 30 min, sans compteur ni message.

**1.7 — l'ALIGNEMENT de `recent`/`recent_ts` n'est prouvé NULLE PART.** Le seul contrôle est une
égalité de **longueurs**, qui (a) ne détecte aucun décalage temporel à longueur égale et (b) devient
vide dès que les deux tampons saturent à `keep` — c'est-à-dire **toujours, en séance réelle**. Le
test d'alignement du P300 travaille sur des tableaux FABRIQUÉS. Mutation qui passe toute la suite :
`np.concatenate([self.recent_ts, ts_lsl + 1.0 / self.acq.fs])`.
→ `_smoke_tampon_horodate` a déjà `srv.new_block` = `(eeg, ts_lsl)` du dernier bloc sous la main :
asserter que la **queue** des deux tampons est exactement ce bloc, valeurs ET horodatages.

**1.8 — `_smoke_dimensionnement` ne peut PAS échouer.** `attendu` = 488 contre `keep` = 1250 : vrai
par construction, et vrai encore si le terme est supprimé.
→ Patcher `registry.MODES` avec une spec déclarant `marker_epoch_s=30.0` (le motif existe déjà dans
`_smoke_marqueurs_inlet`), reconstruire un `EngineServer`, asserter `keep >= (30+1)*fs`.

**1.9 — `_smoke_marqueurs_inlet` laisse vivant un cycle `EngineServer ↔ ModeRuntime`.** `srv2` n'est
jamais `run()`, or c'est le `finally` de `run()` qui casse ce cycle. C'est le **destructeur zombie
documenté le 2026-07-28** (`BOARD_NOT_CREATED_ERROR`). Inoffensif seulement parce qu'aucun sous-test
ne démarre de board après lui. → `srv2.active = {}` en fin de fonction.

**1.10 — 7 des 8 nouveaux `EngineServer` n'ont pas d'`instance=`** (14/14 des préexistants en ont).
Pire : `_smoke_tampon_horodate` **fait tourner** un moteur 3 s publiant `quality`/`status` sous le
même nom ET le même `source_id` qu'une vraie console synthétique.

**1.11 — les compteurs sont comptés et lus par PERSONNE.** `marqueurs_perdus`, `marqueurs_futurs`,
`marqueurs_inlet_erreurs` (`server.py:119-121`) et **`MarkerInlet.illisibles`** — aucun n'apparaît
dans `_state()`, `snapshot()`, le flux `status`, ni un `print`. Or `modes/p300.py:27-29` les
**annonce** comme le moyen par lequel les pannes 2 et 3 sont dites, et **`docs/markers.md` dit à
l'étudiant « si ce nombre grimpe »** : la chaîne ne mène nulle part. Le cas le plus probable en vrai
(`time_correction()` oublié → tout part dans `marqueurs_futurs`) produit un P300 qui tourne, ne
déclenche jamais, et ne dit rien.
→ Les quatre dans `_state()`/`snapshot()`, plus un `print` **une fois** au franchissement d'un seuil.
⚠️ **Convergence de trois relecteurs indépendants** sur ce point.

**1.12 — `m[1]["target"]` sans `.get`, 3 occurrences** (`server.py:2329`, `:2343`, `:2426`).
Requalifié : **pas cosmétique**. La liste `resultats` est construite EN AMONT, donc une exception
dans un sous-test fait sauter **tous** les suivants — exactement le court-circuit que le passage de
`and` à `all()` venait de supprimer, et sans même imprimer un verdict.

**1.13 — le message « connecté » est sur le chemin qui n'aboutit presque jamais.** Mesuré :
`resolve_byprop(timeout=0.0)` échoue aux premiers appels d'un processus neuf (0/5 en rafale), puis
marche. Or `_ouvre_marker_inlet` ne donne qu'UNE chance puis imprime « pas encore là », tandis que
la re-tentative de `_tire_marqueurs`, celle qui connecte réellement, **n'imprime rien**. L'étudiant
qui lance le moteur avec son stimulus déjà en route lit « pas encore là » et n'a jamais de
confirmation.

### Mineurs de ce lot

`except (ValueError, TypeError)` → `except Exception` (rend vraie la docstring « ne lève jamais » et
couvre `UnicodeDecodeError` de `pull_sample`) · **l'autotest de `markers.py` est intermittent sur
son propre invariant** (attend 2 marqueurs puis vérifie `illisibles == 1`, alimenté par un 3e encore
en vol) — exactement ce que son propre commentaire interdit · `MARKER_LATE_S` est documenté comme
tolérance de RETARD mais utilisé comme tolérance de FUTUR · `max(0, v - coupe)` dans la réindexation
des curseurs · les frontières exactes des compteurs ne sont pas testées.

---

## LOT 2 — le mode P300 et son autotest

**Fichiers : `src/core/modes/p300.py`, `src/core/lsl_io.py`.**

### Critiques

**2.1 — le plafond d'abandon vaut EXACTEMENT deux manches, et la comparaison est stricte.**
Manche normale = 48 époques ; `_MAX_EPOQUES = 6 × 8 × 2 = 96` ; et **`96 > 96` est FAUX**. Un seul
`round_end` manquant colle deux manches complètes, **les deux garde-fous se taisent**, `select()`
reçoit 96 époques dont 16 par cible — la moitié portant l'intention de la manche précédente — et le
moteur publie une cible plausible avec une confiance normale, **silencieusement fausse**. Trois
manches (144) déclenchent bien : le garde attrape l'invraisemblable et rate le seul cas crédible.
⚠️ **Ce n'est PAS un `>=` à corriger.** Un compteur GLOBAL ne peut pas à la fois tolérer un
protocole à plus de 8 répétitions (l'intention écrite l. 68) et détecter deux manches soudées.
→ Prendre un discriminant **PAR CIBLE** (une cible vue plus de `P300_REPS` fois) **ou l'ÉCART**
entre deux flashs consécutifs (SOA 150 ms contre une frontière de manche).

**2.2 — pendant les 15 s de CHAUFFE, personne ne consomme les marqueurs.** `markers_murs` n'est
appelée que depuis `_run_step`, jamais en `warmup`/`rest`. Le curseur ne bouge pas, puis le premier
`_run_step` avale l'arriéré — tout ce qui dépasse le tampon (~4 s) part en `marqueurs_perdus`,
**`round_end` compris**. L'émetteur flashe 2 s après son lancement et `docs/markers.md` dit de le
lancer à côté du moteur : **c'est le comportement PAR DÉFAUT de la première manche de chaque
séance**, et de chaque « Refaire le repos ».

**2.3 — le test d'alignement ne compare que la POSITION du pic, jamais son CONTENU.** `filtfilt` est
à phase nulle, sa réponse impulsionnelle équivalente est une autocorrélation maximale au lag 0 :
**ajouter un `bandpass()` dans `_encaisser_flash` laisse le pic exactement à l'échantillon 38**. Or
`P300Model._prep` filtre déjà — donc **le DOUBLE FILTRAGE passe cet autotest sans un mot**, la panne
exacte contre laquelle ce projet a écrit un garde dédié pour le MI (« bruit à p=0,99 »). Idem pour
une correction de ligne de base ou une conversion d'unité.
→ **UNE assertion qui en remplace trois** :
`chk(np.array_equal(rt._epoques[-1], eeg[i_pic - n_pre:i_pic + n_post]))` — épingle d'un coup
position, forme, ordre des voies et absence de traitement.

**2.4 — `_cibles` n'est lu NULLE PART dans les 478 lignes de test.** `_decider` fait
`zip(self._epoques, self._cibles)` : remonter `self._cibles.append(cible)` au-dessus de la garde
`if epoque is None: return` — une édition d'une ligne — décale les deux listes pour tout le reste de
la manche, et chaque flash suivant est classé sous la cible du précédent. Cible fausse, confiance
normale, déclenché par un événement qui a son propre compteur donc connu pour arriver.
→ `chk(len(rt._cibles) == 0, …)` là où l'époque est perdue, et l'invariant
`len(_epoques) == len(_cibles)` après chaque tick.

**2.5 — `_ModeleCapture` ne capture que des COMPTES, donc rien ne relie une époque à sa cible.**
Une permutation pure (`_cibles.append((cible + 1) % n_targets)`) donne `{1:1, 2:1, …, 0:1}`, **égal**
à `{i: 1 for i in range(6)}` — l'égalité de dict ignore l'ordre. Vérifié : la permutation survit à
TOUS les autres scénarios. L'appariement est prouvé en SORTIE, jamais en ENTRÉE.
→ Planter une amplitude distincte par instant de flash et faire relire `v[0][n_pre, 0]` par clé.

**2.6 — la branche `choisi is None` n'est exercée par aucun test.** `P300_SELECT_MARGIN = 0` la rend
structurellement inatteignable avec le vrai `select`, et aucun faux modèle ne rend `None`. La
mutation `if choisi is None: self._publish(0, …)` est **littéralement la confusion « -1 = la cible
0 »** autour de laquelle toute la docstring du module est construite.
→ Un quatrième faux modèle rendant `(None, scores_connus)`, avec `index == -1` **et** les vrais
scores publiés (pas des zéros — c'est le seul cas où `-1` s'accompagne de vrais scores).
⚠️ **NE PAS supprimer la branche** : lever la constante ferait alors tomber sur `moyennes[None]` →
`KeyError` → moteur à terre.

### Importants

**2.7 — une assertion que rien ne peut faire échouer** : `etat["refus_cible"] == rt._refus_cible`
vaut `0 == 0` à cet instant (deux remises à zéro l'ont précédée). Un `state()` qui écrirait
`0` en dur passe. → Lire `state()` 20 lignes plus haut, où le compteur vaut 1.

**2.8 — le plancher de manche vaut UNE répétition** (6 flashs) alors que le flux annonce `reps=8` et
que la config situe le genou à 7-8. Et `_log` n'imprime `n_flashes` que sur les `-1` : **une
décision sur 6 flashs s'affiche EXACTEMENT comme une sur 48**. → Plancher à `P300_MIN_REPS` (2,
déjà dans la config), et `n_flashes` sur CHAQUE ligne.

**2.9 — la décision est horodatée « maintenant »** alors que l'instant du `round_end` est dans la
variable d'à côté. ~0,9-1,1 s de retard, et comme l'émetteur enchaîne sans pause, l'horodatage tombe
**dans la manche suivante**. → `self._decider(ts)`, trois caractères.

**2.10 — le modèle chargé n'est jamais confronté à ce que le runtime découpe.** Ni `model.fs`, ni
`model.pre_s`, ni `model.post_s` ne sont comparés à `engine.acq.fs` / `self.pre_s` / `self.post_s`,
alors que `P300Model` les porte en attributs. C'est le jumeau exact du contrôle déjà rendu
STRUCTUREL entre `marker_epoch_s` et `pre_s+post_s` — mais celui-là compare le contrat au runtime,
jamais le runtime au MODÈLE.

**2.11 — une manche 100 % invalide est inabandonnable, et la garde anti-bruit redevient « une fois
par SESSION ».** `if not self._epoques: return` empêche `_verifie_abandon` de tourner ; `_refus_cible`
n'est réarmé que par `_vider_manche`. Un étudiant qui numérote ses cibles autrement voit UN
avertissement au début de la séance et plus rien. Et `_dernier_flash_ts` n'avançant que sur les
flashs ACCEPTÉS, un émetteur bien vivant mais fautif est indiscernable d'un émetteur mort.

**2.12 — le refus par marge est le seul `-1` sans motif imprimé, et `_log` lui en invente un FAUX**
(« manche non conclue, 48 flash(s) valides » — 48 flashs, c'est conclusif).

**2.13 — `gagnant=1` est AUSSI l'argmax** : deux mutations passent (le runtime recalcule son propre
argmax ; `confidence = max(moyennes.values())`). → `gagnant=3` (score 0,5, ni max ni min).

**2.14 — le test « chemin réel » n'assert jamais la FORME.** Une troncature passe et n'explose
qu'incidemment, 280 lignes plus loin, en traceback plutôt qu'en ÉCHEC.

**2.15 — la non-contamination n'est prouvée que pour un redémarrage PLUS LENT que le délai de 10 s.**
Une appli qui repart dans les 10 s rafraîchit `_dernier_flash_ts`, les orphelins s'empilent,
`len(par_cible) == 6` est satisfait, et une cible fausse sort avec une confiance normale. Le 2.1
règle ce cas s'il est traité par cible ou par écart.

**2.16 — `margin=P300_SELECT_MARGIN` n'est vérifié nulle part** (les faux modèles ont `0.0` en
défaut et la constante vaut 0,0 : supprimer l'argument passe tout).

**2.17 — `-1 <= index` accepte la non-décision** dans le seul test qui fait tourner le VRAI
décodeur : il passe quoi qu'il arrive. La manche est complète et la marge nulle → `0 <= index` est
exigible ici.

**2.18 — `reps` est la seule métadonnée qui décrive une chose que le moteur ne contrôle pas.** C'est
l'appli EXTERNE qui décide (`--reps`) : à `--reps 12`, les métadonnées annoncent 8. → La retirer, ou
la publier pour ce qu'elle est (un plafond).

**2.19 — le P300 est le seul publieur `decoded_*` sans seuil ni marge dans ses métadonnées** (le
SSVEP publie `threshold`+`margin`, le MI `threshold`+`min_votes`+`vote_len`), alors que
`P300_SELECT_MARGIN` est bel et bien appliquée.

### Mineurs de ce lot

`isinstance(cible, int)` accepte `True`/`False` (bool hérite d'int) et le message nomme le mauvais
problème quand c'est le TYPE qui cloche · le commentaire `# 37` est faux, la valeur est **38**, et la
ligne 823 du même fichier dit bien 38 · `confidence = 0.0` sur les non-décisions, sur une échelle où
0.0 est une valeur HAUTE (un gagnant P300 a normalement des log-odds négatifs) · `epoque`
déréférencé sans garde `None` · la docstring de `state()` désigne les mauvaises pannes ·
`"decoded_p300"` écrit DEUX fois (spec + littéral du publieur), rien ne les lie · `-1` manque aussi
aux métadonnées du **SSVEP** (lacune préexistante, une ligne).

---

## LOT 3 — ce que le produit raconte, et l'émetteur

**Fichiers : `src/core/modes/external.py`, `src/core/modes/runtime.py`, `src/core/modes/registry.py`,
`src/core/server.py` (docstring d'en-tête SEULEMENT), `src/core/p300_decoder.py`,
`src/core/p300_models.py`, `src/console/live_views.py`, `src/console/app.py`, `src/research/`,
`docs/`.**

### Critiques

**3.1 — la console affiche le P300 comme un SSVEP.** `ActiveView.update_from` aiguille sur
`"probas" in sortie`, donc la sortie P300 tombe dans `_update_scores` : `params["freqs"]` absent → 6
barres **sans étiquette**, `threshold` absent → `Z_MIN`, et l'écran annonce **« échelle z · seuil 3 —
un score au-dessus déclenche » AU-DESSUS de log-odds**, puis « CIBLE 3 · 0 Hz ». C'est mot pour mot
la panne que la docstring d'`ActiveView` dit avoir été écrite pour éliminer, un mode plus tard.

**3.2 — l'émetteur n'a aucune pause ni signal visuel entre deux manches.** La frontière est
visuellement identique à un intervalle inter-flash (83 ms). Or **`docs/recette.md` §2.7 demande
« recommence six fois en changeant de cible »** : physiquement impossible — dès la 2e sélection les
époques contiennent la transition du regard, et le moteur publie quand même. **Les DEUX
implémentations validées au casque du même protocole ont cet écran** (`app.py:524` : 2,2 s « choisis
ta cible » + 0,95 s de settle + 1,2 s de résultat ; `p300_calibrate.py:65` : 2,5 s). L'émetteur est
le seul à l'avoir perdu.

### Importants

**3.3 — `server.py:29-31` : la docstring d'en-tête du MOTEUR dit encore que le P300 n'y est pas ET
que les marqueurs entrants n'existent pas.** Les deux moitiés fausses. Aucun des 7 diffs ne touche
cette ligne, et l'inventaire des flux publiés (l. 18-20) omet `decoded_p300`. **Un étudiant qui ouvre
le fichier central apprend que le chantier n'a pas eu lieu.**

**3.4 — `external.py:39` : le champ `unavailable` de l'ErrP contredit la docstring corrigée trois
lignes plus haut.** La docstring dit « l'infrastructure existe désormais (le P300 s'en sert) » ; le
champ dit toujours « Demande un MARQUEUR entrant ». Et c'est le **champ** que l'étudiant lit :
`grid.py:129` le pose sur la tuile grisée, `server.py:547` le ressort comme refus de `--mode errp`.
Le fichier dont la raison d'être est « le point d'honnêteté de l'interface » se contredit sur ses
42 lignes.

**3.5 — `runtime.py:173-174` : le commentaire d'orientation promet une garantie que le moteur ne
donne pas.** Il annonce des marqueurs « MÛRS (leur époque tient dans le tampon) » ; `markers_murs`
ne vérifie que le côté **POST**. La fenêtre PRÉ peut être déjà sortie — d'où `_epoques_perdues` dans
le P300. C'est **le seul cahier des charges qu'aura l'auteur de l'ErrP** : s'il le croit, il retire
la garde `if epoque is None` et perd des époques en silence.

**3.6 — `p300_decoder.py:245-247` : `__main__` jette le verdict de `_demo()` et sort TOUJOURS en 0.**
Donc `python src/core/p300_decoder.py` réussit même en échec, une chaîne `&&` continue, et **le
« exit 0 » du rapport de la tâche 4 ne prouve rien**. Ses deux voisins dans `core/` font
`sys.exit(0 if … else 1)`.

**3.7 — `p300_models.py:196-201` : l'assertion sur laquelle repose TOUTE la décision de conception
ne peut pas attraper son assouplissement.** `_ModeleEtranger.__module__` vaut `"__main__"`, **jamais
`"p300_decoder"`** : la mutation `endswith("p300_decoder")` — précisément la petite passerelle de
compatibilité qu'un contributeur écrira un jour — laisse les 16 assertions vertes pendant que
`data/p300_model.joblib` redevient acceptable. → Enregistrer un `types.ModuleType("p300_decoder")`
dans `sys.modules` avant le `joblib.dump` (retiré dans un `finally`), puis asserter que la raison
cite `p300_decoder`.

**3.8 — `p300_models.py:96` : `decrire(None)` LÈVE** `TypeError`, alors que `charger` a été durcie
pour exactement ça, avec une boucle dédiée et un commentaire « une exception ici remonterait jusqu'au
fil Qt ». `decrire` est la fonction sœur, publique, destinée à la liste de modèles de la console.
Le durcissement s'est arrêté une fonction trop tôt.

**3.9 — `research/app.py:1070` : 3e site du bug `os.path.exists`, non recâblé.** ⚠️ **Convergence de
deux relecteurs indépendants.** `_status()` affiche « modèles — P300 : oui » dès que le fichier
existe, alors que `mode_p300` et `p300_analyze.py`, corrigés par ce chantier, passent par
`charger()` qui refuse tout modèle hérité. L'indicateur du menu contredit le moteur **sur l'écran
même depuis lequel l'étudiant lance le mode**.

**3.10 — `research/p300_calibrate.py:231` : la prochaine calibration ÉCRASE `data/p300_model.joblib`**,
la trace de juillet que le message de commit affirme préserver. Rien n'applique l'invariant.

**3.11 — l'invariant anti-répétition n'existe QUE dans l'émetteur.** La calibration — **seul chemin
vers un modèle** — remélange sans garde de jonction, et le P300 live pygame non plus. Mesuré sur
20 000 manches : **72,0 % des manches de calibration contiennent au moins une répétition immédiate,
1,17 par manche = 2,44 % des époques**. L'ampleur est faible et personne ne prétend que ça change
l'AUC : ce qui casse, c'est qu'un invariant est affirmé et testé à un endroit et violé aux deux
endroits qui touchent réellement le sujet.

**3.12 — le `--smoke` de l'émetteur n'exécute jamais `run()`.** Il retourne avant l'import de pygame :
les ~90 lignes contenant **le geste flip→horodatage que ce fichier existe pour enseigner** n'ont
aucune couverture. Le patron dont il se réclame fait l'inverse (`SDL_VIDEODRIVER=dummy` + 30 frames
réellement rendues).

**3.13 — rien n'indique si le moteur écoute.** Aucun `have_consumers()` dans le HUD, aucun
`wait_for_consumers()` avant le premier flash (les deux existent dans le pylsl installé), et
l'émetteur flashe immédiatement. Un étudiant qui a oublié de démarrer le moteur — ou tapé un autre
nom de flux — regarde un écran parfaitement fonctionnel **pendant des minutes** sans le moindre signe.

**3.14 — `--targets` est accepté sans validation alors que le moteur code `P300_N_TARGETS = 6` en
dur.** `--targets 4` tourne sans un mot : les indices 0-3 sont dans la plage donc la garde ne se
déclenche pas, et la probabilité oddball passe de 1/6 à 1/4 — le modèle décode avec les probabilités
de quelqu'un d'autre. Documenter n'est pas vérifier.

**3.15 — `registry.check()` : même message que `marker_epoch_s` soit sous-dimensionné ou ABSENT**,
là où son jumeau distingue les deux cas. Or le champ vaut `0.0` par défaut, donc **l'oubli EST le cas
par défaut** pour le prochain auteur, et « marker_epoch_s=0 s est SOUS pre_s+post_s=0,95 s » se lit
comme une erreur de calcul : ça envoie vérifier une arithmétique au lieu d'ajouter un champ.

**3.16 — `docs/markers.md` promet une observation impossible** (« si ce nombre grimpe ») : voir 1.11.
À réaccorder une fois les compteurs exposés. Et **la recette §2.7 est infaisable** tant que 3.2 n'est
pas corrigé.

### Mineurs de ce lot

`--targets 0` → `IndexError` nu · `--targets 2` rend une séquence **parfaitement alternée donc 100 %
prévisible**, et le smoke dit OK · la géométrie est recalculée au lieu d'être lue dans
`p300_targets(n)` (diverge dès n=3) · **le rayon du point de fixation est 3 contre `FIX_DOT_R = 2`
— 2,25× la surface sous laquelle les données d'entraînement ont été enregistrées** · `--seconds`
n'est testé qu'en fin de manche · ESC en pleine manche n'émet pas de `round_end` · le SOA imprimé
est dérivé de `--refresh` et non mesuré · comptes en dur en prose (`external.py:3-4`,
`console/app.py:271` et `:479-481` et `:91-93`, `lsl_io.py:8-11` « trois flux au MVP » pour 7
publieurs) · `research/__init__.py` et README classent `p300_stimulus.py` dans la famille « ouvre le
casque » · `p300_decoder.py:216` `{auc*100:.1f}` sans garde `None` · `select({})` lève `IndexError`
· `p300_models` rend un `tuple` là où son jumeau rend une `list` · le message « depuis la console »
de `p300_models.py` (la console n'a pas de page de CALIBRATION P300 ; le bon texte est déjà dans le
`help` du `Param`, à recopier).

---

## Dette assumée, à NE PAS traiter dans cette vague

**`marker_epoch_s` est une seconde source de vérité.** Un futur mode dont le runtime consommerait
des marqueurs sans déclarer `pre_s`/`post_s`, et dont le `SPEC` oublierait `marker_epoch_s`,
passerait `registry.check()` **sans un mot** — et sans `marker_epoch_s > 0` le moteur n'ouvre jamais
d'inlet, `markers_murs` rend `[]` pour toujours, le mode tourne et ne publie rien. C'est mot pour mot
la panne que ce contrôle a été écrit pour empêcher, laissée ouverte par le contrôle lui-même. Le
premier à pouvoir tomber dedans est nommé : l'ErrP.

**Le vrai correctif n'est pas un garde de plus** : c'est de **dériver `marker_epoch_s` de
`runtime_cls.pre_s + runtime_cls.post_s`** au lieu de le redéclarer et de le surveiller — la
préférence affichée du projet partout ailleurs (« deux façons finiraient par diverger »). C'est un
changement de contrat, donc un chantier, pas une correction de fin de revue.
