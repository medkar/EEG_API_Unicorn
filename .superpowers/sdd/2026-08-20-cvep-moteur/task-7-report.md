# Tâche 7 — les seuils réglables à chaud — la garde qui manque à l'ErrP

**Statut : terminé, tour de correction 1 inclus.** Base `e734836`. Deux commits :
`bfcb73bf15e0cf349613018ea2c608575f9f8a45` (« Read the c-VEP thresholds at each decision, so a
session can turn them » — `src/core/modes/cvep.py`, `src/core/modes/contract.py`) puis
`c8e5a810a3b464862502aa84e411796c2a4bbef0` (« Carry the c-VEP thresholds on the wire, not just in
metadata that goes stale » — `src/core/lsl_io.py`, `src/core/modes/cvep.py`). Le §5 ci-dessous
couvre le tour de correction ; les §1-4 sont la livraison initiale, inchangée.

---

## 1. Ce qui a été livré

### `src/core/modes/contract.py` — le commentaire du drapeau, corrigé AVANT tout le reste

Suivi l'ordre imposé par le brief (« à faire en premier, sinon la tâche se contredit »). L'ancien
commentaire de `Param.affecte_decodage` — « False = le décodeur ne le lit jamais » — devenait un
mensonge dès que `corr_min`/`margin` existeraient comme réglages lus à chaque décision. Remplacé
par le texte fourni par le brief : le drapeau décrit *si changer le réglage exige de reconstruire
le runtime* (ce que `server._set_params` en fait), pas qui lit la valeur, et nomme la condition qui
rend `False` honnête — ne jamais mettre le réglage en cache dans `__init__`.

### `src/core/modes/cvep.py` — `corr_min`/`margin` deviennent des `SPEC.params` tournables

- **Deux nouveaux `Param`** (`corr_min`, `margin`), `kind="float"`, bornés `[0.0, 1.0]`, défauts
  `CVEP_CORR_MIN`/`CVEP_MARGIN` (0,26/0,09, les seuils eCCA déjà validés au casque),
  `affecte_decodage=False`. Placés juste après `model`, avant `stream_in` — même position que le
  seuil équivalent chez le MI (`prob_min`, juste après `model`).
- **`CVEPRuntime.decide(fenetre, phase)`** (nouvelle méthode, juste avant `_run_step`) : relit
  `self.params["corr_min"]`/`["margin"]` à CHAQUE appel, les pose sur `self.decodeur` (attributs
  publics et mutables sur les deux classes `CVEPDecoder`/`RCCADecoder` — déjà traités comme tels
  ailleurs dans le dépôt, cf. leurs propres tests qui les passent au constructeur), puis délègue à
  `self.decodeur.classify(fenetre, phase)`. Choisi plutôt que de recopier le classement des
  corrélations dans `decide()` : une deuxième formule de décision à garder d'accord avec celle du
  décodeur aurait été exactement le genre de vérité double que ce fichier évite ailleurs (cf.
  `self._indice`, et le défaut d'appariement trouvé en revue sur le P300).
- **`_run_step`** appelle désormais `self.decide(fenetre, phase)` au lieu de
  `self.decodeur.classify(fenetre, phase)` directement.
- **`_open`, `_rest_step`, `_publish`** ne lisent plus `self.decodeur.corr_min`/`.margin` (des
  valeurs qui ne seraient à jour que par accident, selon l'ordre d'appel) mais
  `self.params["corr_min"]`/`["margin"]` directement — nécessaire parce que `_publish` est aussi
  appelé sur les chemins qui **n'appellent jamais `decide`** (`phase is None` : sans référence
  d'horloge ou référence périmée), où `self.decodeur.corr_min` daterait du dernier appel réussi,
  potentiellement un réglage déjà changé depuis.
- **Effet observable** : `src/console/grid.py` et `src/console/live_views.py` lisent déjà
  `sortie["corr_min"]`/`["margin"]` (le dict rendu par `output()`) pour mettre à l'échelle
  l'affichage des corrélations — ce chantier ne touche pas la console, mais elle reflète
  maintenant le seuil RÉEL en vigueur sans aucun changement de son côté.
- **Commentaire corrigé, trouvé en cours de travail** : le paragraphe au-dessus de `_DECODEURS`
  affirmait encore « ne pas imposer un couple de seuils commun aux deux décodeurs, leurs scores ne
  sont pas à la même échelle ». Or `core/config.py` (même chantier, tâche 3) a depuis mesuré et
  corrigé cette même affirmation ailleurs dans le dépôt : les deux décodeurs vivent à la même
  échelle empirique (gagnant médian, essais corrects, k=2 : 0,323 eCCA / 0,261 rCCA). Un couple
  `corr_min`/`margin` unique pour les deux décodeurs — ce que ce chantier introduit — n'était donc
  plus défendable à laisser contredire par un commentaire obsolète juste au-dessus du code qui le
  fait ; corrigé pour renvoyer vers la mesure de `config.py`.
- **Le test de contrat existant** (`{p.key for p in SPEC.params} == {...}`) mis à jour pour inclure
  les deux nouvelles clés — cassé sinon par construction dès que les deux `Param` existent.

---

## 2. Autotests

| Commande | Résultat |
|---|---|
| `python src/core/modes/cvep.py` | `VERDICT : OK`, exit 0, aucun ÉCHEC |
| `python src/core/modes/contract.py` | `VERDICT : OK`, exit 0, aucun ÉCHEC |
| `python src/core/server.py --smoke` | 17 sections, toutes `VERDICT : OK` (dont `smoke-registry` : 7 modes, 7 dans le moteur, OK — les deux nouveaux `Param` passent la validation générique du registre, notamment l'exigence d'un `help` non vide) |
| `python src/console/app.py --smoke` | `[console-smoke] VERDICT : OK`, exit 0 |

Chaque commande lancée seule ; `tasklist` vérifié sans `python.exe` avant chaque run. `data/`
vérifié par horodatage (`stat data/cvep_model.npz data/cvep_rcca_model.npz`) avant et après la
série de smokes : `cvep_model.npz` toujours à sa date du 21 juillet 16:15:56, `cvep_rcca_model.npz`
toujours à sa date antérieure à cette session — aucun des deux modèles n'a bougé.

---

## 3. La preuve rouge

### 3.1 — Le test de la tâche, écrit avant le code (rouge « la fonctionnalité n'existe pas »)

Le test (nouvelle section « 7bis » du `_selftest` de `cvep.py`) vérifie deux choses : que
`corr_min`/`margin` sont bien déclarés avec `affecte_decodage=False`, et qu'un même appel
`rt.decide(fenetre, phase)` sur la MÊME fenêtre change de verdict selon la seule valeur de
`rt.params["corr_min"]` — sans rien reconstruire.

Écrit avant que `SPEC.params` ni `CVEPRuntime.decide` n'existent :

```
ÉCHEC le modèle, le flux de marqueurs, le vote glissant ET les deux seuils se règlent (['min_votes', 'model', 'stream_in', 'vote_len'])
[...]
ÉCHEC les deux seuils sont déclarés SANS reconstruction du runtime (['stream_in'])
Traceback (most recent call last):
  File "C:\...\src\core\modes\cvep.py", line 1196, in <module>
    _sys.exit(0 if _selftest() else 1)
  File "C:\...\src\core\modes\cvep.py", line 1095, in _selftest
    cmd_a, _ = rt_e.decide(fenetre_seuils, 0)
AttributeError: 'CVEPRuntime' object has no attribute 'decide'
```
`EXIT=1`

Après implémentation (`SPEC.params` + `decide()` + les trois lectures corrigées) :

```
  OK   les deux seuils sont déclarés SANS reconstruction du runtime (['corr_min', 'margin', 'stream_in'])
  OK   changer le seuil change la décision SUR LA MÊME fenêtre, sans rien reconstruire
[...]
[cvep] VERDICT : OK
```
`EXIT=0`

### 3.2 — La mutation exigée par le brief : remettre les seuils en cache dans `__init__`

C'est CETTE preuve que la tâche demande explicitement de coller. Mutation (deux ajouts, aucune
suppression, dans `CVEPRuntime`) :

```diff
         self.decodeur = _DECODEURS[self.model.decoder](self.model, self.plan)
+        self.corr_min = float(params["corr_min"])
+        self.margin = float(params["margin"])
```

```diff
     def decide(self, fenetre, phase):
         ...
-        self.decodeur.corr_min = float(self.params["corr_min"])
-        self.decodeur.margin = float(self.params["margin"])
+        self.decodeur.corr_min = self.corr_min
+        self.decodeur.margin = self.margin
         return self.decodeur.classify(fenetre, phase)
```

**ROUGE** (seuils figés à la construction — changer `rt.params["corr_min"]` après coup n'a plus
aucun effet, puisque `decide` relit `self.corr_min`, jamais retouché) :

```
  OK   les deux seuils sont déclarés SANS reconstruction du runtime (['corr_min', 'margin', 'stream_in'])
  ÉCHEC changer le seuil change la décision SUR LA MÊME fenêtre, sans rien reconstruire
[...]
[cvep] VERDICT : PROBLÈME
```
`EXIT=1`

Précision utile : c'est bien la DEUXIÈME assertion qui rougit (la présence des deux `Param` dans
`SPEC` reste vraie, seule la garantie comportementale tombe) — le test cible exactement l'invariant
que le brief voulait protéger, pas un symptôme voisin.

**VERT** (mutation retirée, code identique à celui commité) :

```
  OK   les deux seuils sont déclarés SANS reconstruction du runtime (['corr_min', 'margin', 'stream_in'])
  OK   changer le seuil change la décision SUR LA MÊME fenêtre, sans rien reconstruire
[...]
[cvep] VERDICT : OK
```
`EXIT=0`

---

## 4. Doutes

1. **Le défaut de `corr_min`/`margin` est unique, partagé entre eCCA et rCCA** (`CVEP_CORR_MIN`/
   `CVEP_MARGIN`, les valeurs eCCA). `contract.py` ne permet pas à un `Param` numérique de dépendre
   d'un AUTRE réglage du mode (`model`) pour son défaut — seul `kind="choice"` a un mécanisme de
   résolution dynamique. C'est défendable (§1 : `core/config.py` a mesuré que les deux décodeurs
   vivent à la même échelle), et c'était déjà la seule option compatible avec le périmètre du
   brief (modifier `contract.py` au-delà du commentaire du drapeau n'était pas demandé) — mais un
   étudiant qui bascule sur un modèle rCCA sans y penser démarre avec le seuil calibré pour l'eCCA,
   pas `CVEP_RCCA_CORR_MIN`/`CVEP_RCCA_MARGIN`. Le vrai filet, c'est que cette tâche rend ce cas
   RATTRAPABLE en un clic au lieu d'un redémarrage : je ne l'ai pas éliminé, je l'ai rendu bénin.
2. **`decide()` mute les attributs publics `self.decodeur.corr_min`/`.margin`** juste avant
   d'appeler `classify()`, plutôt que de dupliquer le classement des corrélations. C'est un effet
   de bord assumé sur un objet que ce fichier possède entièrement (`self.decodeur` n'est exposé
   nulle part ailleurs), mais c'est un effet de bord. Je l'ai jugé préférable à une deuxième
   formule de décision à garder d'accord avec celle du décodeur — la doctrine que ce fichier
   applique déjà ailleurs (`self._indice`) — mais un relecteur pourrait préférer l'inverse.
3. **Rien vérifié au casque.** Comme pour tout ce chantier jusqu'ici : uniquement du synthétique et
   des smokes headless. Je n'ai aucune mesure de si desserrer `corr_min`/`margin` en pleine séance
   « ressent » vraiment comme réglable côté opérateur (latence de la commande LSL de la console
   jusqu'au moteur, fréquence à laquelle `_set_params` est réellement appelée) — seulement que le
   mécanisme interne (`self.params` muté, relu au tick suivant) est prouvé par test.
4. ~~Les métadonnées LSL statiques restent celles de l'ouverture du flux, et aucun CLIENT LSL
   externe (Unity, Python, MATLAB) n'avait alors aucun moyen de lire le seuil VIVANT.~~ **CORRIGÉ
   au tour de correction 1 (§5)** : la revue a confirmé que c'était Important, pas seulement à
   signaler, et étendu le périmètre à `core/lsl_io.py` pour que `corr_min`/`margin` voyagent
   PAR ÉCHANTILLON, comme `threshold` chez l'ErrP.

---

# Tour de correction 1

Commit `c8e5a810a3b464862502aa84e411796c2a4bbef0` (« Carry the c-VEP thresholds on the wire, not
just in metadata that goes stale »). Périmètre étendu par la revue à `src/core/lsl_io.py`.
Fichiers modifiés : `src/core/lsl_io.py`, `src/core/modes/cvep.py`.

## 5.1 Ce qui a été livré

### Le doute n°4 corrigé : `corr_min`/`margin` voyagent PAR ÉCHANTILLON

`cvep_channel_labels(n_targets)` (`core/lsl_io.py`) gagne deux voies, **à la fin** —
`score_i` est un bloc de longueur VARIABLE selon `n_targets`, rien ne peut s'y intercaler sans
casser l'indexation `score_<i>`. Nouvel ordre complet :

```
target_index, confidence, score_0, ..., score_{n-1}, corr_min, margin
```

`DecodedCVEPPublisher.push(target_index, confidence, scores, corr_min, margin, lsl_ts=None)` :
les deux seuils sont maintenant des paramètres REQUIS (aucun défaut) — même choix que `threshold`
chez `DecodedErrPPublisher.push`, pour la même raison : un appelant qui les oublierait doit lever,
pas publier une valeur plausible et fausse en silence.

`CVEPRuntime._publish` calcule `corr_min`/`margin` UNE fois (dans `self.params`, jamais dans
`self.decodeur`) et les passe à la fois à `self._out.push(...)` et au dict `output()` — pour que
le flux et l'écran ne puissent jamais raconter deux histoires différentes.

Les métadonnées `desc()` (figées à l'ouverture) restent en place : leur docstring, et celle de la
classe, disent maintenant explicitement qu'elles décrivent le seuil À L'OUVERTURE, et renvoient
vers les deux voies pour le seuil VIVANT — sans ça, on remplaçait une ambiguïté par une autre,
comme demandé.

### Les trois lectures non protégées, maintenant couvertes

`_open()`, `_rest_step()`, `_publish()` lisaient déjà `self.params` (livraison initiale) mais
aucun test n'aurait rougi si l'un des trois était revenu à `self.decodeur.corr_min`/`.margin`.
Deux scénarios réels, couverts chacun par un test dédié :

- **`_open`/`_rest_step`** (nouvelle section 5quater) : un client démarre le mode avec un
  `corr_min` NON défaut dès sa commande initiale (`_runtime_de_test` gagne `overrides=`/
  `engine=` pour rendre ce cas constructible). `_open()` est appelé pour de VRAI — un vrai
  `DecodedCVEPPublisher`/`StreamOutlet` — et ses métadonnées sont lues via
  `outlet.get_info().desc().child("decoding")`, comme le fait déjà `lsl_io.py` pour ses propres
  publieurs. `_rest_step()` est exercé directement (`rt._rest_until = 0.0` puis
  `rt._rest_step(engine=None, now=0.0)` — `SPEC.rest.duration_s == 0` pour ce mode, donc un seul
  pas conclut).
- **`_publish`** (extension de la section 6, COMPTEURS PAR CAUSE) : `rt_c.params["corr_min"]` est
  changé APRÈS la construction mais AVANT le tout premier `_run_step` — les trois premières
  fenêtres de cette section tombent sur le chemin `phase is None`
  (`sans_reference`/`reference_perimee`), qui publie SANS jamais appeler `decide()`. La preuve
  porte sur `rt_c._out.lignes[0]` (le tout premier refus, donc AVANT toute synchronisation par
  `decide`), pas sur l'état final.

## 5.2 Autotests

| Commande | Résultat |
|---|---|
| `python src/core/modes/cvep.py` | `VERDICT : OK`, exit 0, 0 ÉCHEC (57 `chk` OK) |
| `python src/core/modes/contract.py` | `VERDICT : OK`, exit 0 |
| `python src/core/lsl_io.py` | `VERDICT : OK`, exit 0 (voir « doute » ci-dessous sur un échec TRANSITOIRE observé une fois, hors code touché) |
| `python src/core/server.py --smoke` | 17 sections, toutes `VERDICT : OK` |
| `python src/console/app.py --smoke` | `[console-smoke] VERDICT : OK`, exit 0 |

`tasklist` vérifié sans `python.exe` avant CHAQUE commande. `data/cvep_model.npz` et
`data/cvep_rcca_model.npz` vérifiés par horodatage avant/après toute la série : aucun des deux
n'a bougé (46 entrées dans `data/`, inchangé).

## 5.3 Les nouvelles voies de `decoded_cvep`, dans l'ordre

```
['target_index', 'confidence', 'score_0', 'score_1', 'score_2', 'score_3', 'score_4', 'score_5', 'corr_min', 'margin']
```
(imprimé par `python src/core/lsl_io.py`, `n_targets=6`.)

## 5.4 La preuve rouge sur `_open` et `_publish`

Trois mutations, chacune isolée puis les trois COMBINÉES — même protocole que celui utilisé par
la revue pour trouver le trou.

**Mutation `_open`** (`corr_min=float(self.params["corr_min"])` → `corr_min=self.decodeur.corr_min`,
idem `margin`) — ROUGE :
```
  OK   fixture : le runtime démarre avec un seuil NON défaut, comme une commande initiale (0.501, 0.222)
  ÉCHEC `_open` écrit dans les métadonnées LSL le seuil SOUMIS à la construction, pas le défaut du décodeur ('0.26', '0.09')
[cvep] VERDICT : PROBLÈME
```
`EXIT=1`. VERT après retrait : `('0.501', '0.222')`, `VERDICT : OK`, `EXIT=0`.

**Mutation `_rest_step`** (même geste) — ROUGE :
```
  ÉCHEC `_rest_step` rapporte le seuil SOUMIS à la construction, pas le défaut du décodeur ({'kind': 'cvep', 'model': 'cvep_model.npz', 'decodeur': 'eCCA', 'n_targets': 6, 'corr_min': 0.26, 'margin': 0.09})
[cvep] VERDICT : PROBLÈME
```
`EXIT=1`. VERT après retrait, `corr_min`/`margin` à `0.501`/`0.222` dans `rest_report`.

**Mutation `_publish`** (même geste) — ROUGE :
```
  ÉCHEC `_publish` transporte le seuil VIVANT même sur une fenêtre qui n'est JAMAIS passée par `decide` ((-1, 0.0, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 0.26, 0.09, 108.38))
[cvep] VERDICT : PROBLÈME
```
`EXIT=1`. Précision utile, trouvée en construisant la preuve : la DEUXIÈME assertion de ce test
(`rt_c.output()["corr_min"] == 0.501`, vérifiée après les SIX fenêtres) NE rougit PAS sous cette
mutation seule — parce que les trois dernières des six fenêtres traversent bien `decide()`, qui
resynchronise `self.decodeur.corr_min` sur `self.params["corr_min"]` AVANT le dernier `_publish`.
Seule la lecture de `lignes[0]` (le tout premier appel, avant tout `decide()`) est une preuve
étanche à cette mutation ; je l'ai gardée comme LA preuve et gardé la seconde comme un filet
redondant mais honnête (son commentaire le dit).

**Les trois MUTATIONS COMBINÉES** (comme le relecteur les a rejouées) — ROUGE, les trois ÉCHEC en
même temps :
```
  ÉCHEC `_open` écrit dans les métadonnées LSL le seuil SOUMIS à la construction, pas le défaut du décodeur ('0.26', '0.09')
  ÉCHEC `_rest_step` rapporte le seuil SOUMIS à la construction, pas le défaut du décodeur ({...'corr_min': 0.26, 'margin': 0.09})
  ÉCHEC `_publish` transporte le seuil VIVANT même sur une fenêtre qui n'est JAMAIS passée par `decide` ((-1, 0.0, [...], 0.26, 0.09, 108.38))
[cvep] VERDICT : PROBLÈME
```
`EXIT=1`, puis les trois retirées ensemble : `VERDICT : OK`, `EXIT=0`.

**Régression sur la preuve de la livraison initiale** (mutation `__init__` de la tâche 7,
rejouée après tous ces changements pour vérifier qu'elle mord toujours) : ROUGE identique à la
section 3.2 (`ÉCHEC changer le seuil change la décision SUR LA MÊME fenêtre...`), et SEULE cette
assertion rougit — les trois nouvelles de ce tour restent vertes sous CETTE mutation précise,
signe que chaque test protège bien SA propre ligne et pas une zone floue.

## 5.5 Doutes (tour de correction 1)

1. **`python src/core/lsl_io.py` a échoué UNE fois, de façon non reproductible**, sur une
   assertion SSVEP (§7 du fichier, `no_decision_index manquant (SSVEP)`) — une section que je
   n'ai pas touchée. Deux relances immédiates, sans aucun changement de code, sont passées au
   vert. Je n'ai pas creusé plus loin (pas de code à moi dans la section qui a levé), mais je ne
   peux pas l'expliquer : mon hypothèse la plus probable est une contention transitoire côté
   liblsl après avoir ouvert un grand nombre de `StreamOutlet` en rafale pendant mes propres
   séries de mutations juste avant. À surveiller si `lsl_io.py` redevient flaky ailleurs.
2. **Le point de fonctionnement `push()` de la section 9 de `lsl_io.py`** pousse volontairement
   des `corr_min`/`margin` DIFFÉRENTS de ceux du constructeur (0.30/0.11 contre 0.26/0.09), pour
   rendre visible que les deux sont des choses distinctes — mais ce fichier ne fait AUCUNE
   relecture par inlet réel (aucun publieur `decoded_*` n'en fait dans ce fichier, c'est la
   convention établie) : la preuve que le CONTENU transporté est correct reste entièrement dans
   `cvep.py` (`_FauxPublieur`), pas au niveau du fil LSL lui-même.
3. **Le mineur du §4.1/§4.2 initial (défaut unique eCCA/rCCA, mutation de `self.decodeur`)
   reste reporté, inchangé par ce tour.**
4. Toujours rien vérifié au casque.
