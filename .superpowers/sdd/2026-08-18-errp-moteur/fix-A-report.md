# Correction de la revue finale — tranche A : `src/core/modes/errp.py`

Commit : **`e56e45f`** (sur `main`, parent `b05292a`), 503 insertions / 105 suppressions, 1 fichier.
Périmètre : **ce fichier seul**. Aucun autre fichier édité.
Bilan : **11 constatations sur 11 traitées** (2 Critical, 5 Important, 4 Minor — aucun report).
Autotest : **64 → 84 assertions**, `python src/core/modes/errp.py` sort en 0.
Non-régression : `python src/core/server.py --smoke` vert (18 verdicts, exit 0).

Toutes les preuves rouges ci-dessous ont été produites par un harnais qui applique la mutation,
lance `python src/core/modes/errp.py`, note les `ÉCHEC`, puis **restaure le fichier**. Aucun autre
programme ne tournait ; `Get-Process python` rend 0 après coup.

---

## CRITICAL 1 — L'horodatage publié était celui de la boucle du moteur

### Ce qui a été fait

- `_traiter_feedback(self, engine, ts, lsl_ts)` → `_traiter_feedback(self, engine, ts)`. Les trois
  `_publish` passent désormais `lsl_ts=ts`, l'horodatage du **feedback**.
- `_run_step` ne transmet plus `lsl_ts` du tout — il ne peut donc plus être publié par accident.
  Sa docstring dit pourquoi il le reçoit quand même (`ModeRuntime.tick` le passe à tous les modes).
- La docstring de `_traiter_feedback` et un ⚠️ en tête de module expliquent le décalage
  structurel (0,7 s de maturité + 0,2 s de granularité de boucle, pour un feedback affiché 1,0 s)
  et renvoient à `p300.py`, qui a tranché pareil pour son `round_end`.

### Le test, rendu discriminant

Tous les `tick` du chemin de publication passent maintenant un `lsl_ts` **volontairement décalé de
+0,8 s** (l'ordre de grandeur réel), sur le patron de `p300.py:859`. L'assertion `chk(ts_reel ==
t_reel, …)` cesse d'être tautologique, et **deux assertions neuves** ferment le trou :

- sur le lot à DEUX marqueurs (110,0 et 110,1) ramassés au même tour de boucle :
  `chk([l[-1] for l in rt._out.lignes[-2:]] == [110.0, 110.1], …)` ;
- au bout du test d'alignement, désormais passé par `tick` (cf. MINOR 11) :
  `chk(rt._out.lignes[-1][-1] == instant, …)`.

### Preuve ROUGE (mutation : republier `lsl_ts` comme avant)

```
### C1-horodatage : exit=1  ['[errp] VERDICT : PROBLÈME']
   ÉCHEC l'horodatage publié est celui du FEEDBACK, PAS le tour de boucle qui l'a traité (105.8 attendu 105.0, lsl_ts valait 105.8) …
   ÉCHEC score >= seuil -> error=1, … ((1, 5.044411023237179, 0.04441102323717849, 0, 106.8))
   ÉCHEC score < seuil -> error=0, … ((0, -4.955588976762821, 0.04441102323717849, 0, 107.8))
   ÉCHEC une époque perdue publie -1, … ((-1, 0.0, 0.04441102323717849, 0, 5.8))
   ÉCHEC une époque artefact publie -1, … ((-1, 0.0, 0.04441102323717849, 1, 108.8))
   ÉCHEC ...CHACUN horodaté à SON feedback, pas les deux au même tour de boucle ([110.9, 110.9], lsl_ts valait 110.9 pour les deux)
   ÉCHEC ...et l'époque prélevée AUTOUR de `ts` est publiée AVEC `ts` … (1002.8 attendu 1002.0, lsl_ts valait 1002.8)
```

Sept assertions rouges, dont celle des deux feedbacks qui **reçoivent le même horodatage 110,9** —
exactement la panne décrite. VERT après retrait : `[errp] VERDICT : OK`, exit 0.

---

## CRITICAL 2 — Le σ du repos était mesuré sur 5,0 s, l'époque sur 0,9 s

### Le chiffrage, AVANT correction (demandé)

Deux scripts jetables, hors dépôt, sans casque.

**1. Le biais de support brut** — médiane de `σ(5,0 s) / σ(0,9 s)`, les deux fenêtres prises dans
**un même signal continu**, 400 tirages par cas :

| cas | médiane | p10 | p90 |
|---|---|---|---|
| bruit blanc pur (contrôle) | **1,00** | 0,95 | 1,06 |
| marche aléatoire pure | 2,31 | 1,16 | 4,50 |
| rampe DC linéaire pure | 5,56 | 5,56 | 5,56 |
| **EEG + dérive lente (20 µV sur 5 s)** | **1,94** | 1,21 | 3,29 |
| EEG + dérive faible (5 µV sur 5 s) | 1,11 | 1,00 | 1,33 |
| board synthétique BrainFlow, 8 voies | **0,98 – 1,00** | | |

Les deux cas théoriques tombent sur leur valeur attendue (√(5,0/0,9) = 2,36 ; 5,0/0,9 = 5,56), ce
qui valide la mesure.

**2. La conséquence opérationnelle** — 20 séances synthétiques, repos mesuré par 40 fenêtres
glissantes puis médiane, comme le vrai `_rest_step` ; époques tirées **du même tampon** :

```
sigma_repos(5 s) / sigma_repos(0,9 s) : mediane x2.01 (min x1.22, max x2.57)

Balayage de l'amplitude du clignement (600 epoques par point) :
  amplitude uV     actuel    corrige
            60        0%        0%
           100        0%        1%
           150        9%      100%
           200       29%      100%
           250       51%      100%
           300       92%      100%
           400      100%      100%
```

**Le biais n'est PAS négligeable : ×2,01 de référence en trop** (le mode se comportait comme si
`ERRP_ARTIFACT_RATIO` valait 8 au lieu de 4). Le plancher de détection à 50 % passe de ~250 µV à
~130 µV. Un clignement franc de 150 µV n'était rejeté que **9 %** du temps, contre **100 %** une
fois le support borné.

⚠️ Et le contrôle explique pourquoi rien ne le voyait : sur du **bruit blanc** le ratio vaut 1,00,
et sur le **board synthétique de BrainFlow** (celui de `--synthetic`) aussi, 8 voies sur 8. Aucun
smoke ne pouvait attraper ça sans une fixture qui porte une dérive.

### Ce qui a été fait

```python
n_epoque = int(round((self.pre_s + self.post_s) * engine.acq.fs))
bloc = engine.recent
if bloc is None or len(bloc) < n_epoque:
    return False
sig = np.asarray(bloc[-n_epoque:], dtype=float).std(axis=0)
```

Le plancher `engine.acq.margin_n` disparaît au profit de `n_epoque`, qui est le bon. La docstring
de `_rest_step` est réécrite : les deux corrections (représentation, support) y sont posées comme
**une seule règle** — « ce σ n'existe que pour être comparé à celui d'une époque, donc il doit
être mesuré COMME elle » — avec les chiffres ci-dessus et le renvoi à l'interdiction déjà écrite
dans `server.py._publish_quality`.

### Le test, refait sur UN tampon continu

L'ancienne preuve rouge-puis-vert donnait au repos et à l'époque **deux tampons distincts avec la
dérive renormalisée sur chacun** — le seul cas où le biais disparaît. Elle est remplacée par : un
seul tampon continu de 20 s, dérive calibrée à 20 µV **sur une fenêtre de référence de 5 s**
(`sous_5hz(..., ref_n=)`, pour qu'on ne puisse plus renormaliser tampon par tampon), le repos qui
**glisse dedans par pas de 0,2 s** comme la boucle du moteur, puis deux époques tranchées dans ce
même tampon :

- une époque SAINE **n'est pas** rejetée (c'est l'ancienne preuve du tour 1, conservée) ;
- une époque avec un clignement de 150 µV crête **est** rejetée (la preuve neuve du tour 2).

### Preuve ROUGE (mutation : `sig = np.asarray(bloc, …)`, le tampon entier)

```
### C2-support : exit=1  ['[errp] VERDICT : PROBLÈME']
   ÉCHEC ⚠️ SUPPORT : un clignement franc (150 µV crête) DANS le même tampon continu EST rejeté … (publié : error=0, artifact=0)
```

`error=0, artifact=0` : le clignement part au modèle et ressort en « la machine avait raison » —
la panne muette, telle quelle. VERT après retrait.

---

## IMPORTANT 3 — La branche « rest » de `tick` n'était jamais exercée

`_FauxMoteur.appels_murs` était incrémenté et jamais lu. Ajouté, après la bascule en « rest » et
avec une file NON vide :

```python
appels_avant_repos = moteur.appels_murs
moteur._lots = [[marqueur(101.3)]]
rt.tick(moteur, lsl_ts=102.1, now=2.0)          # phase == "rest" À L'ENTRÉE
chk(rt.phase == "rest" and rt._marqueurs_chauffe == 4
    and moteur.appels_murs == appels_avant_repos + 1, …)
```

Le message de l'ancienne assertion (« le REPOS jette et compte lui aussi »), qui décrivait en fait
la branche warmup, est corrigé en « celui reçu PILE à la bascule est jeté lui aussi ». La docstring
de `tick` dit maintenant pourquoi `in ("warmup", "rest")` n'est pas simplifiable.

### Preuve ROUGE (mutation : `if self.phase == "warmup":`)

```
### I3-garde-rest : exit=1  ['[errp] VERDICT : PROBLÈME']
   ÉCHEC le REPOS jette et compte lui aussi … (rest, 3, 0 appel(s))
   ÉCHEC ...mais seuls les FEEDBACKS sont comptés … (3, 5 attendu)
   ÉCHEC ...et les feedbacks jetés pendant la chauffe restent, eux, un compteur de SÉANCE (3)
```

`0 appel(s)` : `markers_murs` n'est plus appelé du tout pendant le repos. VERT après retrait.

---

## IMPORTANT 4 — La panne n°8 n'était reliée au chemin réel par aucune assertion

Deux ajouts, tous deux **par `tick`** :

1. **La valeur des compteurs après trafic réel** (le fil `_epoques_vues += 1` avant la garde) :
   `chk(rt._epoques_vues == 6 and rt._epoques_perdues == 1 and rt._artefacts == 1, …)`.
2. **Le franchissement du palier par le chemin réel** (le fil `self._verifie_taux_rejet()`) : une
   plage entière du tampon est saturée, 10 feedbacks y sont envoyés en un lot, stdout est capturé.
   L'alarme sort **une** fois, au premier franchissement (« 5/10 (50 %) », pas « 11/16 » : le but
   est d'alerter TÔT), et ne se répète pas pour les 6 artefacts suivants.

### Preuve ROUGE — mutation A (retirer `self._verifie_taux_rejet()`)

```
### I4b-alarme-debranchee : exit=1  ['[errp] VERDICT : PROBLÈME']
   ÉCHEC ...et l'alarme de sur-rejet part DEPUIS `tick`, au premier franchissement du palier, une seule fois pour les 10 (0 occurrence(s) : …10 lignes « écarté : artefact » et RIEN d'autre…)
```

### Preuve ROUGE — mutation B (`_epoques_vues += 1` déplacé APRÈS la garde d'artefact)

```
### I4a-denominateur : exit=1  ['[errp] VERDICT : PROBLÈME']
   ÉCHEC le dénominateur du taux compte les époques EXTRAITES, artefacts COMPRIS, perdues EXCLUES (5 vues, 1 perdues, 1 artefacts)
   ÉCHEC les 10 feedbacks saturés sont tous comptés comme artefacts par le chemin réel (11/5)
   ÉCHEC ...et l'alarme de sur-rejet part DEPUIS `tick` … (0 occurrence(s))
   ÉCHEC ...sans perdre l'historique de la séance … (5, 11)
```

`11/5` = le `taux_rejet = 2,2` (« 220 % ») annoncé par la revue. VERT après retrait des deux.

---

## IMPORTANT 5 — La médiane portait sur ~40 fenêtres recouvrantes à 96 %

Réglé par le même correctif que le CRITICAL 2, comme la revue l'indiquait : le recouvrement entre
deux appels passe de 96 % (5,0 s glissés de 0,2 s) à **78 %** (0,9 s), et un clignement pendant le
repos ne pollue plus ~26 fenêtres sur 40 mais ~5 — la médiane redevient robuste. C'est écrit dans
la docstring de `_rest_step`, avec le calcul. Pas d'assertion propre : le comportement testé est
celui du CRITICAL 2, et une assertion sur le recouvrement testerait `period_s()`, qui appartient à
`runtime.py`.

---

## IMPORTANT 6 — `errp` consommait des marqueurs sans exposer `stream_in`

`Param(key="stream_in", …)` ajouté à `SPEC.params`, **identique à celui du P300** (même
`choices`, même `default`, `affecte_decodage=False`), avec une aide adaptée au feedback et un
commentaire qui nomme les deux pannes : le mode inconfigurable (deux binômes dans la même salle)
et la voie de secours du P300 cassée en `--mode errp,p300`.

Assertions : `{p.key for p in SPEC.params} == {"model", "tnr_target", "stream_in"}`, le défaut
retenu par `validate`, `SPEC.marker_epoch_s > 0` (ce qui fait que le moteur le LIT), et surtout le
**câblage** : `chk(rt.params.get("stream_in") == MARKER_STREAM_DEFAULT, …)` — c'est là que
`server._nom_flux_marqueurs` va le chercher.

⚠️ Je n'ai **pas** ajouté d'assertion « un nom personnalisé est accepté » : `contract._coerce`
refuse toute valeur hors `choices`, et le P300 a exactement la même limite. Ce n'est pas propre à
ce fichier ; cf. « dépendances » en bas.

### Preuve ROUGE (mutation : la clé renommée `stream_in_ABSENT`)

```
### I6-stream_in-absent : exit=1
   ÉCHEC le modèle, le taux de bonnes commandes à garder ET le flux de marqueurs se règlent
   ÉCHEC ...et le flux de marqueurs prend le défaut du protocole, comme le P300 (None)
   ÉCHEC le RUNTIME porte le nom du flux entrant, là où le moteur va le chercher (None)
```

VERT après retrait.

*Effet de bord vérifié :* le commentaire `server.py:3094` (« un mode marqueur qui NE DÉCLARE PAS
`stream_in` — aucun aujourd'hui ») redevient **vrai** avec ce correctif ; il n'y a donc rien à
corriger là-bas.

---

## IMPORTANT 7 — « Refaire le repos » désarmait l'alarme qu'il devait résoudre

`_reset_rest` remet maintenant à zéro `_epoques_vues`, `_artefacts` et `_rejet_eleve_dit` (plus
`_repos_mort_dit`), et **deux cumuls de séance** apparaissent, exposés à part dans `state()` :
`epoques_vues_session` / `artefacts_session`. L'historique n'est donc pas perdu, il est juste
cessé d'être mélangé au taux courant. Les commentaires de `__init__` qui déclaraient ces trois
compteurs « de SESSION » sont réécrits, docstring de `_reset_rest` à l'appui.

Invariant qui en découle et qui est maintenant vrai : dans `state()`,
`artefacts / epoques_vues == taux_rejet`, **toujours**, sur le repos en cours.

### Preuve ROUGE (mutation : `_reset_rest` sans les trois remises à zéro)

```
### I7-reset-sans-rearmement : exit=1  ['[errp] VERDICT : PROBLÈME']
   ÉCHEC « Refaire le repos » remet le taux à « rien mesuré » et RÉARME l'alarme … (0.688, 11/16, dite=True)
```

C'est mot pour mot le scénario de la revue : « 11/16 » encore affiché alors que le nouveau repos
n'a rien jugé, et `dite=True` — plus aucune alarme possible de la séance. VERT après retrait.

---

## MINOR 8 — `_marqueurs_chauffe` comptait tous les événements — **CORRIGÉ**

`self._marqueurs_chauffe += sum(1 for _ts, m in jetes if m.get("event") == "feedback")`, et un
`return` anticipé si le lot ne contenait aucun feedback (sans quoi un lot de `run_start`
imprimerait « 0 feedback(s) jetés » et brûlerait le message unique). `len(jetes)` reste la garde
qui déclenche l'appel, donc le curseur du moteur avance toujours.

Assertion : un lot `[run_start, feedback]` pendant le repos fait passer le compteur de 4 à **5**,
pas 6.

### Preuve ROUGE (mutation : `feedbacks = len(jetes)`)

```
### M8-compte-brut : exit=1  ['[errp] VERDICT : PROBLÈME']
   ÉCHEC ...mais seuls les FEEDBACKS sont comptés … (6, 5 attendu)
   ÉCHEC ...et les feedbacks jetés pendant la chauffe restent, eux, un compteur de SÉANCE (6)
```

---

## MINOR 9 — « le premier reçu APRÈS le repos » était faux — **CORRIGÉ**

Le message dit maintenant « le premier dont l'**ÉPOQUE COMPLÈTE** tombe après le repos », avec un
commentaire qui explique la maturité (`ts + post_s`) et le cas du repos raccourci. Je n'ai **pas**
ajouté le refus dans `_traiter_feedback` (la « garantie forte » que la revue proposait en
alternative) : elle exigerait de mémoriser l'instant de fin de repos et changerait le
comportement, alors que dire la vérité suffit — et l'effet est bénin en usage nominal, de l'aveu
même de la constatation.

### Preuve ROUGE (mutation : le vieux libellé)

```
### M9-message-faux : exit=1  ['[errp] VERDICT : PROBLÈME']
   ÉCHEC ...et il promet ce qui est VRAI : « le premier dont l'ÉPOQUE COMPLÈTE tombe après le repos », pas « le premier reçu après » ("… Le premier feedback décodé sera le premier dont l'ÉPOQUE reçu APRÈS le repos.")
```

---

## MINOR 10 — Aucun plancher sur le σ de référence — **CORRIGÉ**

Le repos **refuse de conclure** quand une voie est à σ nul, le dit une fois en nommant la ou les
voies, vide ses échantillons et **redémarre une fenêtre entière** (`_rest_until = now +
self._rest_s`) plutôt que de répéter le message 5 fois par seconde. Constante nommée
`_SIGMA_VOIE_MORTE = 1e-6`, panne n°9 ajoutée à la liste du module.

Assertion : un tampon dont la voie 3 est bloquée à 42,0 laisse le mode en phase « rest » avec
`_sigmas_repos is None`, et le message sort **une** fois avec `[3]` dedans.

### Preuve ROUGE (mutation : `mortes = []`)

```
### M10-voie-morte-ignoree : exit=1  ['[errp] VERDICT : PROBLÈME']
   ÉCHEC une voie à σ NUL empêche le repos de conclure … (running, sigmas=[5.32 5.53 5.39 0. 5.55 5.48 …])
   ÉCHEC ...et l'étudiant l'apprend UNE fois, avec la VOIE nommée … ("[errp] repos mesuré (1 fenêtres …) — σ par voie (brut) : [5.3 5.5 5.4 0.  5.5 5.5 5.5 5.7]")
```

Le `0.` au milieu du σ publié est précisément le seuil de rejet à zéro qui aurait écarté toute la
séance.

---

## MINOR 11 — Le test d'alignement court-circuitait `tick` — **CORRIGÉ**

```python
moteur.recent, moteur.recent_ts = eeg, ts
moteur._lots = [[marqueur(instant)]]
rt.tick(moteur, lsl_ts=instant + 0.8, now=12.0)   # lsl_ts VOLONTAIREMENT différent
```

L'assertion de contenu est inchangée ; elle couvre désormais aussi la couche qui **fournit** `ts`,
et une assertion d'horodatage la suit (cf. CRITICAL 1).

### Preuve ROUGE (mutation : `self._traiter_feedback(engine, lsl_ts)` dans `_run_step`)

```
### M11-alignement-lsl_ts : exit=1  ['[errp] VERDICT : PROBLÈME']
   … 10 assertions rouges, dont :
   ÉCHEC ⚠️ ALIGNEMENT : l'époque constituée par le runtime est EXACTEMENT la tranche brute du tampon …
   ÉCHEC ...et l'époque prélevée AUTOUR de `ts` est publiée AVEC `ts` … (1002.8 attendu 1002.0)
```

C'est exactement la mutation que la constatation annonçait comme invisible : elle est maintenant
rouge sur l'assertion d'alignement elle-même.

---

## Contraintes vérifiées

- **Frontière `core/`** : aucun import de `research`/`console`/pygame/Qt ajouté. Le seul import
  neuf est `MARKER_STREAM_DEFAULT` depuis `core.config`. `scipy.signal` reste dans `_selftest`.
- **Français** partout, code et commentaires ; message de commit en anglais.
- **Aucune écriture dans le vrai `data/`** : le `tempfile.mkdtemp` + `shutil.rmtree` dans le
  `finally` est intact, et rien de neuf n'écrit sur disque. Vérifié : `git status` ne montre que
  `src/core/modes/errp.py`.
- **L'autotest sort en 1** quand il échoue : les 11 mutations rendent toutes `exit=1`.
- **`ERRP_REFRACTORY_S`** n'est toujours ni importé ni référencé ; le test des deux feedbacks à
  100 ms est conservé et **renforcé** (il assert maintenant leurs deux horodatages).
- **`error = -1`** reste « pas de verdict » : les deux chemins de non-verdict publient `-1`, le
  modèle n'est pas consulté, et les assertions de compteur d'appels sont conservées.
- **Sans casque** : tout tourne sur du synthétique, y compris les deux mesures chiffrées.

## Dépendances vers des fichiers hors périmètre

Une seule, et c'est une **observation**, pas un blocage :

- `src/core/modes/contract.py` (`_coerce`, `kind == "choice"`) refuse toute valeur absente de
  `choices`. Le `Param.stream_in` de l'ErrP — comme celui du **P300**, qui a exactement la même
  déclaration — n'accepte donc aujourd'hui que `MARKER_STREAM_DEFAULT` par `validate`. Le scénario
  « deux binômes renomment leur émetteur » est donc débloqué côté **moteur** (`_nom_flux_marqueurs`
  lit bien `rt.params["stream_in"]` sur l'ErrP maintenant), mais reste inatteignable **via la
  console** tant que ce `Param` n'a qu'un seul choix. Le correctif serait un `kind="text"` ou un
  `choices_fn` qui liste les flux `Markers` visibles sur le réseau — il touche `contract.py`
  et/ou `p300.py` autant qu'`errp.py`, donc il n'est pas de mon ressort.

Aucune autre dépendance : `server.py:3094` redevient vrai tout seul, et `p300.py:541-544` (la voie
de secours) redevient tenable puisque l'ErrP déclare enfin son `stream_in`.
