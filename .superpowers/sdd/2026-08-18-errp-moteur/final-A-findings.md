# Revue finale de branche — tranche A : `src/core/modes/errp.py` (1077 lignes, entier)

Lecture seule, aucun programme exécuté. Références croisées lues : `modes/p300.py`,
`modes/contract.py`, `modes/runtime.py`, `modes/registry.py`, `core/server.py`,
`core/errp_decoder.py`, `core/lsl_io.py`, `core/acquisition.py`, `core/config.py`,
`console/app.py`, plus `task-2-brief.md` / `task-*-report.md` de ce chantier.

**Bilan : 2 Critical · 5 Important · 4 Minor.** 64 assertions `chk()` comptées dans `_selftest`.

Le fil conducteur des deux Critical est le même, et c'est exactement ce qu'une revue
tâche-par-tâche ne pouvait pas voir : **chaque fonction est juste isolément, et l'autotest
fabrique ses fixtures de telle sorte que la composition ne peut pas mentir.** Dans les deux cas
le fixture rend deux grandeurs artificiellement égales, ce qui rend l'assertion tautologique.

---

## CRITICAL 1 — L'horodatage publié est celui de la BOUCLE du moteur, pas celui du feedback

**Fichier:ligne** — `src/core/modes/errp.py:351-355` (`_run_step`), `:357-380`
(`_traiter_feedback`), `:420-427` (`_publish`). Assertion aveugle : `:810`.

### Ce qui casse

```python
def _run_step(self, engine, lsl_ts):
    for ts, marqueur in engine.markers_murs(self.spec.id, post_s=self.post_s):
        ...
        self._traiter_feedback(engine, ts, lsl_ts)   # ts = l'onset ; lsl_ts = « maintenant »

def _traiter_feedback(self, engine, ts, lsl_ts):
    epoque = epoch_from_stream(..., ts, ...)          # ts sert à ÉPOCHER
    ...
    self._publish(..., lsl_ts=lsl_ts)                 # mais c'est lsl_ts qui est PUBLIÉ
```

`ts` sert à découper l'époque (correct) et n'est **jamais** transmis au publieur. Ce qui part
sur le réseau via `DecodedErrPPublisher.push(..., lsl_ts)` puis
`outlet.push_chunk(block, [float(lsl_ts)])` est l'instant où la boucle du moteur a traité le
marqueur — `self.clock.to_lsl(time.time())` de `server.py:1223`.

Le jumeau `p300.py` fait explicitement l'inverse, et dit pourquoi (`p300.py:293-296`) :

> « L'instant du `round_end`, PAS `lsl_ts` : la boucle du moteur tourne à ~5 Hz […] donc
> "maintenant" tombe 0,9 à 1,1 s plus tard […] Un client qui aligne cette décision sur autre
> chose (une vidéo, un log de jeu) lirait un décalage constant. »

Le décalage est ici **structurellement au moins `post_s`** : `markers_murs` ne rend un marqueur
que quand `ts + post_s <= recent_ts[-1]` (`server.py:1092`), donc un feedback n'est jamais
traitable avant `ts + 0,7 s` ; s'ajoutent la granularité de `period_s()` = 0,2 s et le délai de
lecture du bloc. **Décalage attendu : 0,7 à 1,0 s, avec ~0,2 s de gigue.** `ERRP_FEEDBACK_S`
vaut 1,0 s : le verdict tombe donc sur la fenêtre d'affichage du feedback **suivant**.

### Le scénario concret

Une application externe (le `errp_stimulus.py` de ce dépôt, ou du Unity) affiche un feedback
toutes les ~0,95 s et publie son onset. Le moteur ramasse deux feedbacks mûrs dans le **même**
lot `markers_murs` — cas ordinaire, la boucle tourne à 5 Hz et l'émetteur à ~1 Hz, et c'est
littéralement le scénario que l'autotest met en scène (`:885-892`, deux feedbacks à 100 ms) :

- entrées : marqueurs à `ts = 110,0` et `ts = 110,1` ; la boucle les traite au tour `lsl_ts = 110,85` ;
- comportement faux : **deux échantillons publiés avec le MÊME horodatage LSL `110,85`**, tous
  deux ~0,8 s après leur feedback.

Un client qui veut savoir *à quel feedback* se rapporte un verdict n'a que l'horodatage LSL. Il
ne peut ni les distinguer l'un de l'autre, ni les rattacher au bon événement de son propre
journal : il attribuera systématiquement le verdict au feedback suivant. Or le seul contenu
utile de ce flux est « la machine s'est trompée **à cet instant-là** » — un verdict binaire
détaché de son événement ne vaut rien. Et rien ne le signale : les valeurs sont plausibles.

### Pourquoi l'autotest ne le voit pas

Tous les tests de publication appellent `tick` avec `lsl_ts` **égal** à l'horodatage du
marqueur — `:803`, `:827`, `:837`, `:849`, `:867`, `:941`, `:1012`. L'assertion `:810` :

```python
chk(ts_reel == t_reel, f"l'horodatage publié est celui du FEEDBACK ({ts_reel})")
```

est donc **tautologique** : elle serait verte que le runtime publie `ts` ou `lsl_ts`. Le seul
appel où les deux diffèrent (`:889`, `lsl_ts=110.1` pour un marqueur à `110.0`) n'assert que le
*nombre* de lignes, pas leurs horodatages. **Aucune mutation d'une ligne de production ne rend
ce test rouge — dans les deux sens : corriger le bug le laisse vert aussi.** Le squelette vient
tel quel de `task-2-brief.md:84-96` ; rien nulle part n'argumente en faveur de `lsl_ts`, ce
n'est pas une décision, c'est un recopiage.

### Correctif minimal

Dans `_traiter_feedback`, publier `ts` :

```python
self._publish(-1, 0.0, artefact=0, lsl_ts=ts)     # époque perdue
self._publish(-1, 0.0, artefact=1, lsl_ts=ts)     # artefact
self._publish(1 if score >= self.seuil else 0, score, artefact=0, lsl_ts=ts)
```

Le paramètre `lsl_ts` de `_traiter_feedback` devient inutile : le retirer (et l'argument de
`_run_step`) plutôt que de le laisser traîner. Et **rendre l'assertion discriminante** : dans
`_selftest`, appeler chaque `tick` avec un `lsl_ts` volontairement décalé, ex.
`rt.tick(moteur, lsl_ts=t_reel + 0.8, now=4.0)`, puis garder `chk(ts_reel == t_reel, ...)`.
Ajouter, sur le lot à deux marqueurs de `:888`, une assertion sur les **deux** horodatages :
`chk([l[-1] for l in rt._out.lignes[-2:]] == [110.0, 110.1], ...)` — c'est elle qui ferme
définitivement le trou.

---

## CRITICAL 2 — Le σ du repos est mesuré sur 5 s de tampon, l'époque sur 0,9 s : sous-rejet systématique

**Fichier:ligne** — `src/core/modes/errp.py:305-308` (`_rest_step`) contre `:382-394`
(`_est_artefact`). Preuve « rouge-puis-vert » aveugle : `:953-1019`.

### Ce qui casse

```python
def _rest_step(self, engine, now):
    bloc = engine.recent                                  # ← le tampon ENTIER
    if bloc is None or len(bloc) < engine.acq.margin_n:
        return False
    sig = np.asarray(bloc, dtype=float).std(axis=0)
```

contre

```python
def _est_artefact(self, epoque):
    sig = np.asarray(epoque, dtype=float).std(axis=0)     # ← 0,9 s
    return bool(np.any(sig > ERRP_ARTIFACT_RATIO * self._sigmas_repos))
```

La correction du tour 1 a réglé la **représentation** (brut contre brut). Elle a laissé le
**support** : `engine.recent` fait `EngineServer.keep` échantillons, soit
`max(2,0·250, 2,0·250, 2,0·250, 4,0·250, round(1,95·250), 375) + 250 = 1250` = **5,0 secondes**
(`server.py:197-202`). Le terme dominant est `epoque_calib = MI_IMAGERY_S = 4,0 s`, c'est-à-dire
**l'époque d'entraînement de la calibration Motor Imagery**. Le seuil de rejet d'artefact de
l'ErrP est donc réglé, aujourd'hui, par une constante d'un autre mode.

`server.py:1117-1124` a déjà identifié **exactement** cet anti-patron, pour la mesure de
qualité, et l'interdit en toutes lettres :

> « ⚠️ On ne passe PAS `self.recent` en entier : ce tampon est dimensionné (`self.keep`) pour le
> plus gourmand de TOUS ses consommateurs […] Passer le tampon entier mesurait donc le σ sur
> `self.keep` (4 s dès que le MI est calibrable), un **couplage NON borné** : demain un
> `epoch_s` de calibration plus long élargirait encore la fenêtre […] SANS que rien ne le dise. »

`_rest_step` fait précisément ce que ce commentaire interdit.

Le sens du biais est **systématique**, comme celui qui a été corrigé, mais **inversé** : pour
toute composante lente (dérive DC résiduelle, 1/f — la signature documentée de ce casque), σ
croît avec la longueur de la fenêtre. Pour une rampe DC quasi linéaire, σ ∝ T, soit un facteur
**5,0/0,9 = 5,6×** ; pour une marche aléatoire, σ ∝ √T, soit **2,4×**. Dans les deux cas
σ_repos est gonflé par rapport à ce qu'il mesurerait sur le même support que l'époque, donc le
ratio jugé est **déflaté**, donc le mode **sous-rejette**.

### Le scénario concret

Séance ordinaire. Après les 15 s de chauffe il reste une rampe DC résiduelle — le projet la
documente comme la panne matérielle n°1 (`config.py` sur `SSVEP_WARMUP_S`, `acquisition.py` sur
`sigma_from_block` : 10⁵ µV en rampe sur des dizaines de secondes). Supposons qu'il en reste de
quoi contribuer 20 µV de σ sur 5 s, l'EEG propre valant 10 µV :

- σ_repos = √(20² + 10²) ≈ 22,4 µV → seuil de rejet = 4,0 × 22,4 = **89,6 µV** ;
- sur une époque de 0,9 s, la même rampe ne contribue que 20/5,6 ≈ 3,6 µV → σ_époque ≈ 10,6 µV ;
- un **clignement franc** de 60-100 µV crête sur 0,9 s donne σ ≈ 20-35 µV — **très en dessous de
  89,6 µV : il n'est PAS rejeté.**

Comportement faux : l'époque contaminée part au modèle, qui rend un score, et le moteur publie
`error = 0` ou `error = 1` avec `artifact = 0`. C'est la panne muette que ce produit existe pour
éliminer, et elle est ici pire que le défaut corrigé au tour 1 : le sur-rejet se voyait (30/30),
le sous-rejet ne se voit **jamais** — ni sur le flux, ni dans `state()`, ni dans
`_verifie_taux_rejet` (qui, par construction, ne s'alarme que d'un taux TROP HAUT).

La docstring du module (`:76-79`) promet le contraire — « un vrai clignement de 60 µV toujours
détecté », « ratio ~×10 » — mais ce chiffre a été mesuré sur la fixture ci-dessous, pas sur la
configuration réelle.

### Pourquoi l'autotest ne le voit pas

La preuve rouge-puis-vert (`:953-1019`) donne au repos et à l'époque **deux tampons distincts,
taillés chacun à sa propre échelle**, et `sous_5hz` **renormalise la dérive à 10 µV sur chacun**
(`:966-981`). Les deux supports portent donc, par construction, la **même** amplitude de dérive
— le seul cas où le biais de support disparaît. Le commentaire `:983-987` le dit lui-même :

> « lui donner tout de suite un grand tampon de 20 s DILUE la dérive dans chaque tranche de
> 0,9 s qu'on en extraira ensuite — et **ferait disparaître l'effet à démontrer**. »

Autrement dit : l'effet de support a été identifié, et neutralisé dans la fixture pour rendre le
test vert, au lieu d'être testé. Aucune assertion du fichier ne compare σ_repos et σ_époque
**sur un signal continu unique** — la seule configuration qui existe en séance.

### Correctif minimal

Borner explicitement le bloc du repos à la longueur d'une époque, dans `_rest_step` :

```python
n_epoque = int(round((self.pre_s + self.post_s) * engine.acq.fs))
bloc = engine.recent
if bloc is None or len(bloc) < n_epoque:
    return False
sig = np.asarray(bloc[-n_epoque:], dtype=float).std(axis=0)
```

(le plancher `margin_n` disparaît au passage : il était emprunté « comme ordre de grandeur
commode » de son propre aveu `:301-303`, alors que le bon plancher est précisément
`n_epoque`.) Ce correctif règle aussi l'IMPORTANT 3 ci-dessous.

Et rendre le test capable de le voir : construire **UN** tampon continu de 20 s avec dérive,
mesurer le repos dessus, puis épocher dans le **même** tampon (pas un tirage neuf renormalisé),
et vérifier qu'un clignement injecté à 60 µV est bien rejeté.

> **À VÉRIFIER PAR EXÉCUTION** (aucune, si le correctif est appliqué avant) :
> `python src/core/server.py --synthetic --mode errp --rest 8` puis lire le `[errp] repos mesuré
> … σ par voie (brut)` — attendu, aujourd'hui : un σ mesuré sur 1250 échantillons (5 s) et non
> sur 225. Confirmable sans casque.

---

## IMPORTANT 3 — La branche « rest » de `tick` n'est jamais exercée : la mutation qui la retire reste verte

**Fichier:ligne** — `src/core/modes/errp.py:327-329` (la garde) ; test aveugle `:757-795`.

### Ce qui casse

```python
def tick(self, engine, lsl_ts, now):
    if self.phase in ("warmup", "rest"):
        self._jeter_marqueurs_de_chauffe(engine)
    super().tick(engine, lsl_ts, now)
```

L'élargissement de la garde du P300 (`!= "running"`) à la phase « rest » est **la raison d'être
déclarée** de ce `tick` redéfini : la docstring du module (`:53-60`) explique que ce mode attend
23 s (15 + 8) contre 15 s pour le P300, et que « c'est pendant le repos que ce mode mesure sa
référence d'artefact ». Or aucune assertion ne distingue `in ("warmup", "rest")` de
`== "warmup"`.

Déroulé exact du test :

| appel | phase À L'ENTRÉE de `tick` | `_lots` | effet |
|---|---|---|---|
| `tick(now=0.5)` `:763` | `warmup` | `[101.0, 101.1]` | jetés → compteur 2 |
| `tick(now=1.5)` `:770` | **`warmup`** (la bascule a lieu dans `super().tick`, APRÈS la garde) | `[101.2]` | jetés → compteur 3 |
| `tick(now=2.0/2.7/3.5)` `:787-788` | `rest` | **`[]` — vidé en `:786`** | rien |

Le marqueur de `:768`, dont le commentaire dit « pile à la bascule vers "rest" » et dont
l'assertion `:772-774` affirme « **le REPOS jette et compte lui aussi** les feedbacks reçus
pendant qu'il mesure », est en réalité consommé par la branche **warmup**. Et pendant les trois
ticks où la phase EST « rest », la file est vide.

### Le scénario concret

Un développeur simplifie la garde en `if self.phase == "warmup":` (elle a l'air redondante avec
`ModeRuntime.tick`, qui teste `warmup` en premier). Les 64 assertions restent vertes.

En séance : l'émetteur `errp_stimulus.py` tourne à côté du moteur et publie ~1 feedback/s. Les
8 s de repos accumulent ~8 marqueurs derrière un curseur immobile. Au premier `_run_step`, ils
arrivent tous d'un coup ; ceux dont l'EEG a quitté le tampon de 5 s partent en
`engine.marqueurs_perdus` — comptés par le moteur, sans que rien ne dise à quel mode ni
pourquoi ; les autres publient des verdicts fondés sur de l'EEG de repos. C'est mot pour mot la
panne n°7 que ce `tick` existe pour empêcher, et qui a coûté un critique à la revue du P300.

### Correctif minimal

Le fixture est déjà là mais désarmé : `_FauxMoteur.appels_murs` est incrémenté (`:550`, `:553`)
et **jamais lu** — alors que `p300.py:821-830` s'en sert précisément pour cette preuve. Ajouter,
après la bascule en « rest » (`:786`) :

```python
moteur._lots = [[marqueur(101.3)]]
rt.tick(moteur, lsl_ts=101.3, now=2.0)          # phase == "rest" À L'ENTRÉE
chk(rt.phase == "rest" and rt._marqueurs_chauffe == 4,
    f"le REPOS jette et compte lui aussi ({rt.phase}, {rt._marqueurs_chauffe})")
```

et remettre `moteur._lots = []` avant la boucle `:787`. C'est la seule assertion qui distingue
les deux versions de la garde.

---

## IMPORTANT 4 — La panne bruyante n°8 n'est reliée au chemin réel par aucune assertion

**Fichier:ligne** — `src/core/modes/errp.py:365-368` (les deux fils), `:396-418`
(`_verifie_taux_rejet`), `:276-277` (`taux_rejet`) ; tests `:1021-1066`.

### Ce qui casse

Les quatre tests de la panne n°8 **posent les compteurs à la main** puis appellent la méthode
privée en direct :

```python
rt3._epoques_vues = rt3._artefacts = _TAUX_REJET_MIN_ECHANTILLONS - 1
rt3._verifie_taux_rejet()          # :1028
rt3._epoques_vues, rt3._artefacts = 20, 3   ; rt3._verifie_taux_rejet()   # :1033-1034
rt3._epoques_vues, rt3._artefacts = 20, 12  ; rt3._verifie_taux_rejet()   # :1038-1041
rt3._epoques_vues, rt3._artefacts = 40, 30  ; rt3._verifie_taux_rejet()   # :1048-1051
```

Ils prouvent la **règle** (plancher d'échantillons, palier, une seule fois) — ce qui est utile —
mais **jamais le câblage**. Les deux fils qui relient cette règle au runtime réel sont :

1. `self._verifie_taux_rejet()` appelé depuis la branche artefact de `_traiter_feedback` (`:368`) ;
2. `self._epoques_vues += 1` **avant** la garde d'artefact (`:365`), qui fait de ce compteur le
   dénominateur correct.

Sur le chemin réel, `rt` ne voit au maximum que 7 époques (`:897` le compte lui-même), soit sous
le plancher de 10 : **aucun** des quatre tests ne s'exécute jamais via `tick`.

### Le scénario concret

Deux mutations d'une seule ligne, toutes deux plausibles à la relecture, laissent **les 64
assertions vertes** :

- **Mutation A** — supprimer `self._verifie_taux_rejet()` de `:368` (elle a l'air d'être un
  détail d'affichage). Conséquence en séance : un casque mal salé rejette 9 époques sur 10 ; le
  flux publie `-1` en boucle avec `artifact = 1` ; **rien n'est jamais dit**. La docstring
  `:401-405` décrit exactement cette panne comme « la panne canonique de ce projet […] sous un
  autre visage ». Le garde-fou existe et n'est plus branché.
- **Mutation B** — déplacer `self._epoques_vues += 1` **après** la garde d'artefact (ce qui se
  lit comme « ne compter que les époques réellement jugées »). Conséquence :
  `taux_rejet = artefacts / vues` avec un dénominateur qui **exclut** les artefacts →
  30 artefacts pour 10 époques propres donnent `taux_rejet = 3.0`, un « 300 % » affiché dans la
  console. Et l'alarme se déclenche beaucoup trop tôt.

Aucune assertion ne vérifie la **valeur** de `_epoques_vues` après trafic réel : `:902` ne teste
que `{"epoques_perdues", "artefacts", "marqueurs_chauffe"}`, et `:904-909` ne fait que comparer
`state()` aux attributs (tautologique pour la valeur, utile seulement contre un croisement de
fils).

### Correctif minimal

Une assertion de valeur après le trafic réel, juste avant `:900` :

```python
chk(rt._epoques_vues == 6 and rt._epoques_perdues == 1 and rt._artefacts == 1,
    f"le dénominateur du taux compte les époques EXTRAITES, artefacts compris, perdues exclues "
    f"({rt._epoques_vues}, {rt._epoques_perdues}, {rt._artefacts})")
```

(6 = 1 réel + 2 espions + 1 artefact + 2 rapprochés ; l'époque perdue est exclue.) Et un
scénario qui franchit vraiment le palier **par `tick`** : envoyer 10 marqueurs dont 6 tombent
sur une plage de tampon saturée (le geste de `:862-865` répété), capturer stdout, et assertir
que l'alarme sort. C'est la seule façon de tuer la mutation A.

---

## IMPORTANT 5 — La médiane du repos porte sur ~40 fenêtres recouvrantes à 96 % : elle n'est robuste à rien

**Fichier:ligne** — `src/core/modes/errp.py:305-312`.

### Ce qui casse

`_rest_step` est appelé une fois par `period_s()` = 0,2 s (`runtime.py:90`, jamais surchargée ;
ordonnancement `server.py:1222`). Sur 8 s de repos → **~40 appels**. Chacun calcule un σ sur
`engine.recent`, un tampon de **5,0 s** qui n'a glissé que de 0,2 s depuis le précédent :
**96 % de recouvrement**. La médiane de `:312` porte donc sur 40 quasi-doublons.

Le mot « médiane » annonce une robustesse aux valeurs aberrantes. Elle n'existe pas : une
perturbation reste dans le tampon **5 s**, donc contamine **25 des 40 fenêtres** — soit 62,5 %,
au-dessus de la médiane. La médiane est alors elle-même contaminée.

### Le scénario concret

L'étudiant cligne des yeux une fois pendant les 8 s de repos (la consigne dit « regarde l'écran,
immobile » — elle n'interdit pas de cligner, et l'ErrP est justement le mode où l'on sursaute).
Le clignement tombe à τ = 2 s dans le repos :

- il reste dans `engine.recent` de τ = 2 s à τ = 7 s → il pollue les fenêtres 10 à 35, soit **26
  sur 40** ;
- la médiane par voie retient donc un σ **contaminé** — sur Fz/Cz, un clignement de 60 µV sur un
  tampon de 5 s remonte facilement σ de 10 à 20 µV ;
- seuil de rejet = 4 × 20 = 80 µV au lieu de 40 µV, **pour toute la séance** ;
- comportement faux : plus aucun clignement n'est rejeté, `artifact` reste à 0, et chaque époque
  contaminée reçoit un verdict plausible. Se cumule avec le CRITICAL 2, dans le même sens.

Il suffit que le clignement tombe dans les **4 premières secondes** du repos pour contaminer la
majorité — soit une chance sur deux pour un clignement à instant aléatoire.

### Correctif minimal

Le même que le CRITICAL 2 : mesurer sur `bloc[-n_epoque:]` (0,9 s). Le recouvrement entre deux
appels tombe alors à 0,7/0,9 = 78 %, un clignement ne pollue plus que ~5 fenêtres sur 40, et la
médiane redevient robuste — c'est-à-dire qu'elle fait enfin ce que son nom promet.

---

## IMPORTANT 6 — `errp` consomme des marqueurs sans exposer `stream_in` : mode non configurable, et voie de secours du P300 cassée

**Fichier:ligne** — `src/core/modes/errp.py:461-479` (`SPEC.params`), `:495`
(`marker_epoch_s`) ; assertion qui grave l'omission : `:611-612`.

### Ce qui casse

`errp.SPEC` déclare `marker_epoch_s = 0,9 > 0` : le moteur le compte donc parmi les modes qui
écoutent des marqueurs (`server.py:850`, `:879`, `:923`, `:1041`). Mais ses `params` valent
`{"model", "tnr_target"}` — **pas de `stream_in`**, contrairement au P300 (`p300.py:534-545`).

Deux conséquences distinctes.

**(a) Le mode est inconfigurable.** `contract.validate` refuse toute clé inconnue
(`contract.py:208-211`) : soumettre `stream_in` à l'ErrP donne
« réglage inconnu pour « ErrP » : stream_in ». Le flux de marqueurs de l'ErrP est donc gelé sur
`MARKER_STREAM_DEFAULT` (`server.py:849`, via le `.get(..., défaut)`).

*Scénario :* deux binômes travaillent dans la même salle — le cas exact pour lequel `stream_in`
existe. Le binôme B renomme son émetteur pour ne pas entrer en collision. Lancé en `--mode errp`,
le moteur ne peut pas être pointé dessus : il résout `EEG_API_Unicorn_stim`, trouve **le flux du
binôme A**, et épocher l'EEG du sujet B autour des feedbacks affichés à l'écran de A. Comportement
faux : des verdicts parfaitement plausibles, totalement décorrélés de ce que le sujet a vu, sans
une seule erreur ni un seul avertissement.

**(b) Il casse la voie de secours documentée du P300.** L'aide publique de `p300.py:541-544`
promet : « ARRÊTER puis redémarrer ce mode suffit en revanche à reprendre le nouveau — l'inlet
est lâché dès que plus aucun mode actif ne l'écoute ». Or `_ferme_marker_inlet` ne lâche l'inlet
que si **aucun** mode actif n'a `marker_epoch_s > 0` (`server.py:921-927`), et
`_ouvre_marker_inlet` sort immédiatement si l'inlet existe déjà (`server.py:877-878`).

*Scénario :* `--mode errp,p300`. L'utilisateur veut changer le `stream_in` du P300. Il arrête le
P300 → l'ErrP maintient l'inlet ouvert sur l'ancien nom. Il redémarre le P300 avec le nouveau
nom → l'inlet n'est pas rouvert. Comportement faux : le P300 continue d'écouter l'ancien flux,
la console affiche fièrement le nouveau nom dans ses réglages, et la seule procédure de secours
documentée ne marche plus. Le commentaire `server.py:3094` (« un mode marqueur qui NE DÉCLARE
PAS `stream_in` (**aucun aujourd'hui**, un futur mode…) ») est devenu faux avec ce chantier.

### Correctif minimal

Ajouter à `errp.SPEC.params` le même `Param` que le P300 :

```python
Param(key="stream_in", label="Flux de marqueurs", kind="choice",
      choices=(MARKER_STREAM_DEFAULT,), default=MARKER_STREAM_DEFAULT,
      affecte_decodage=False,
      help="Le nom du flux LSL sur lequel ton application publie l'onset de chaque feedback. …"),
```

et passer `:611` à `== {"model", "tnr_target", "stream_in"}`. Si l'omission est au contraire
délibérée, alors c'est le commentaire de `server.py:3094` et l'aide de `p300.py:541-544` qui
doivent être corrigés — mais laisser les trois en désaccord est ce qui rend la panne (b)
invisible.

---

## IMPORTANT 7 — « Refaire le repos » désarme l'alarme qu'il est censé résoudre, et rend `taux_rejet` illisible

**Fichier:ligne** — `src/core/modes/errp.py:249-253` (`_reset_rest`), `:183-186`, `:276-277`,
`:416-418`.

### Ce qui casse

`_reset_rest` remet `_sigmas_repos`, `_echantillons`, `_decoded` et `_chauffe_dite` à zéro, mais
**pas** `_artefacts`, `_epoques_vues` ni `_rejet_eleve_dit` — choix documenté `:183-186` comme
« compteurs de SESSION ». Or le message de l'alarme (`:418`) recommande explicitement :

> « Vérifie le contact des électrodes, ou « **Refaire le repos** ». »

L'action recommandée par l'alarme est donc précisément celle qui (1) l'empêche de se redéclencher
et (2) rend impossible de mesurer si elle a servi.

### Le scénario concret

- σ de repos mesuré pendant un instant anormalement calme → seuil trop bas → 30 artefacts sur
  40 époques ;
- l'alarme sort une fois (`_rejet_eleve_dit = True`), disant « 30/40 (75 %) », et conseille
  « Refaire le repos » ;
- l'étudiant refait le repos. Nouveau σ, correct. Les 40 époques suivantes passent toutes ;
- `state()["taux_rejet"]` affiche `30/80 = 0,375` — encore élevé, alors que **le taux courant est
  0 %**. Conclusion fausse tirée en séance : « le nouveau repos n'a rien changé, le casque est
  mauvais » ;
- et si le repos avait au contraire empiré la situation (rejet à 90 %), `_rejet_eleve_dit` étant
  déjà `True`, **plus aucune alarme ne sortirait jamais** de la séance.

C'est un défaut de composition, pas de fonction : `_verifie_taux_rejet` est juste, `_reset_rest`
est juste, c'est leur enchaînement qui ment. Le patron dont ce fichier est calqué a d'ailleurs
tranché dans l'autre sens pour le cas analogue — `p300.py:473-485` réarme `_refus_cible` à chaque
manche, avec un commentaire qui explique exactement ce risque (« sinon la garde `== 1` ne se
déclenche plus jamais […] silencieusement, pour le reste de la séance »).

### Correctif minimal

Réarmer l'alarme et sa fenêtre de mesure dans `_reset_rest`, en gardant les totaux de session
pour l'historique :

```python
def _reset_rest(self):
    ...
    # Le taux se juge CONTRE LE REPOS EN COURS : le mesurer par-dessus l'ancien σ mêle deux
    # références et empêche de voir si « Refaire le repos » a servi (le geste que l'alarme
    # elle-même recommande).
    self._epoques_vues = 0
    self._artefacts = 0
    self._rejet_eleve_dit = False
```

et, si l'historique de session compte, ajouter deux cumuls séparés
(`_artefacts_session`, `_epoques_vues_session`) exposés à part dans `state()`. Corriger au
passage les commentaires `:183-186`. Test associé : après `begin_rest`, vérifier que
`state()["taux_rejet"] is None` et qu'une nouvelle alarme peut sortir.

---

## MINOR 8 — `_marqueurs_chauffe` compte tous les événements du mode, pas seulement les `feedback`

**Fichier:ligne** — `src/core/modes/errp.py:341-349`.

`_jeter_marqueurs_de_chauffe` fait `self._marqueurs_chauffe += len(jetes)` sur le retour brut de
`markers_murs`, qui ne filtre que par `mode_id` (`server.py:1066-1068`). `_run_step`, lui, filtre
sur `event == "feedback"` (`:353-354`).

*Scénario :* le protocole grandit (le commentaire `:354` l'annonce : « un événement inconnu
s'ignore : le protocole grandira ») et l'émetteur publie un `{"mode": "errp", "event":
"run_start"}` par piste. Pendant la chauffe, chacun est compté comme un « feedback jeté ».
`state()["marqueurs_chauffe"]` et le message `:347-349` annoncent alors plus de feedbacks perdus
qu'il n'y en a eu — un chiffre qui sert justement à décider si l'émetteur a été lancé trop tôt.

*Correctif :* compter après filtrage —
`self._marqueurs_chauffe += sum(1 for _t, m in jetes if m.get("event") == "feedback")`, en
gardant `len(jetes)` pour la garde `if not jetes`.

---

## MINOR 9 — « Le premier feedback décodé sera le premier reçu APRÈS le repos » est faux

**Fichier:ligne** — `src/core/modes/errp.py:348-349` (le message imprimé à l'utilisateur).

Un marqueur n'est rendu par `markers_murs` que s'il est **mûr**, c'est-à-dire
`ts + post_s <= recent_ts[-1]` (`server.py:1092`). Un feedback affiché moins de `post_s` = 0,7 s
avant la fin de la phase de repos n'est donc **pas** mûr pendant le repos : il échappe au rejet,
reste en file, et est décodé au premier `_run_step`.

*Scénario :* avec un override de repos court (`--rest 0`, ce que font les smokes, cf.
`_rest_override` `server.py:167`), un feedback affiché 0,5 s avant la fin de la **chauffe** est
décodé sur de l'EEG prélevé pendant la chauffe — exactement l'EEG que le message affirme jeter
(« l'offset DC du casque dérive encore »). En usage nominal (repos 8 s) l'effet est bénin — le
débordement se fait sur de l'EEG de repos, exploitable — mais le message reste faux et il est lu
par un étudiant qui s'en sert pour savoir quand lancer son émetteur.

*Correctif :* dire ce qui est vrai — « Le premier feedback décodé sera le premier dont l'époque
complète tombe après le repos » — ou, si la garantie forte est voulue, refuser dans
`_traiter_feedback` tout `ts` antérieur à l'instant de fin de repos (à mémoriser dans
`_rest_step`).

---

## MINOR 10 — Aucun plancher sur le σ de référence : une voie à σ = 0 rejette 100 % des époques

**Fichier:ligne** — `src/core/modes/errp.py:391-394`.

`return bool(np.any(sig > ERRP_ARTIFACT_RATIO * self._sigmas_repos))` : si une voie a un σ de
repos nul, son seuil vaut `4,0 × 0 = 0`, et toute valeur non constante le franchit.

*Scénario :* une voie de l'Unicorn se bloque à une valeur constante pendant les 5 s de tampon
mesurées au repos (électrode arrachée, saturation ADC en butée — le projet documente C3/Cz qui
saturent à la réouverture, `CLAUDE.md` « Pièges matériels »). σ_repos[c] = 0 → **toutes** les
époques de la séance sont rejetées → le flux publie `-1, artifact=1` en boucle. L'alarme n°8 le
dit une fois (message correct : « vérifie le contact »), puis plus rien — et se cumule avec
l'IMPORTANT 7 : après un « Refaire le repos », elle ne se redéclenche plus.

*Correctif :* refuser de conclure le repos quand une voie est morte, en le nommant — dans
`_rest_step`, après le calcul de la médiane :

```python
mortes = [i for i, s in enumerate(self._sigmas_repos) if s <= 1e-6]
if mortes:
    print(f"[errp] repos INEXPLOITABLE : voie(s) {mortes} à σ nul (électrode décollée ou "
          f"amplificateur en butée) — le rejet d'artefact écarterait TOUTE époque. "
          f"Vérifie le contact, puis « Refaire le repos ».")
    self._echantillons = []
    return False
```

---

## MINOR 11 — Le test d'alignement court-circuite `tick` / `_run_step` / `markers_murs`

**Fichier:ligne** — `src/core/modes/errp.py:941`.

```python
rt._traiter_feedback(moteur, instant, lsl_ts=instant)
```

L'assertion d'alignement `:946-951` — présentée comme « LE test » du sous-système, avec raison —
appelle la méthode privée en direct plutôt que de passer par le chemin réel
`tick` → `_run_step` → `markers_murs` → filtrage `event == "feedback"` → `_traiter_feedback`.
Elle ne peut donc rien dire de la couche qui **fournit** `ts`, alors que c'est précisément là que
vit le CRITICAL 1 (le `ts` reçu ici est correct ; c'est celui qui est *publié* qui ne l'est pas)
et le filtrage d'événement.

*Scénario :* une mutation dans `_run_step` qui passerait `lsl_ts` au lieu de `ts` en 2ᵉ argument
(`self._traiter_feedback(engine, lsl_ts, lsl_ts)`) décalerait **chaque** époque de 0,7 à 1,0 s —
le défaut exact que cette assertion existe pour attraper (« −38 échantillons, −152 ms » côté
P300, en pire) — et resterait verte, puisque le test n'emprunte pas ce chemin.

*Correctif :* passer par `tick`, en gardant tout le reste identique :

```python
moteur.recent, moteur.recent_ts = eeg, ts
moteur._lots = [[marqueur(instant)]]
rt.tick(moteur, lsl_ts=instant + 0.8, now=8.0)   # lsl_ts VOLONTAIREMENT différent
```

Combiné au correctif du CRITICAL 1, la même assertion couvre alors position, forme, ordre des
voies, absence de traitement **et** provenance du `ts`.

---

## Ce que j'ai vérifié et qui tient

Pour que le rapport soit lisible comme une couverture, et pas seulement comme une liste de
reproches :

- **Frontière `core/`** : aucun import de `research`, `console` ni `pygame`
  (`server.py:2083` en donne le motif exact). `scipy.signal` importé dans `_selftest` seulement.
  Code et commentaires en français. ✓
- **Aucune écriture dans le vrai `data/`** : `tempfile.mkdtemp` + `shutil.rmtree` dans un
  `finally` (`:575`, `:1067-1069`), `errp_models.modeles_disponibles` et `errp_models.charger`
  restaurés (le second dans son propre `finally` imbriqué, `:689-690`). ✓
- **L'autotest sort en 1** : `_sys.exit(0 if _selftest() else 1)` (`:1077`), `ok` propagé par
  `chk` via `nonlocal`. ✓
- **`ERRP_REFRACTORY_S` n'est pas appliqué** : la constante n'est ni importée ni référencée, et
  le test `:885-892` le prouve par deux publications à 100 ms d'écart. Mutation « ajouter un
  réfractaire » → rouge. ✓
- **Test de monotonie du seuil** (`:735-755`) : il passe par un **vrai** `ErrPRuntime`
  reconstruit à chaque cible, pas par `pick_threshold` en direct. Mutation « `__init__` ignore
  `params["tnr_target"]` » → rouge sur les trois cibles. C'est le meilleur test du fichier. ✓
- **Les deux filets de démarrage** (géométrie `:188-209`, scores hors-pli `:211-232`) sont
  indépendants et testés séparément, avec le monkeypatch de `charger` (`:681`) qui isole
  correctement le second. Le fixture `ErrPModel(fs=125.0).fit(...)` est bien **entraîné**, sans
  quoi il serait arrêté par le premier filet. ✓
- **`-1` n'est jamais `0`** : les deux chemins de non-verdict publient `-1` et le modèle n'est
  jamais consulté (`:855-856`, `:873-875`, prouvé par compteur d'appels sur l'espion). ✓
- **`epoch_from_stream`** rend `None` sur `i0 < 0` (`p300_decoder.py:53`) : pas d'indexation
  négative qui repartirait de la fin du tampon. ✓
- **`point_de_fonctionnement` est JSON-able** : `pick_threshold` renvoie `float(th)` et `rates`
  renvoie des `float` Python (`errp_decoder.py:52-53`, `:67`) — `state()` ne peut donc pas faire
  tomber `StatusPublisher` sur un `np.float64`. Vérifié parce que ce dict traverse
  `snapshot()` → JSON. ✓
- **`_selftest` : 64 `chk()`**, aucune sur-déclaration numérique trouvée. Les comptes annoncés
  sont exacts : « les 2 feedbacks » (`:765`), « == 3 » (`:772`), « 7 » (`:897`, décomposé en
  commentaire `:895-896` et vérifié), « les 4 clés » de `point_de_fonctionnement` (`:715-718`,
  = les 4 que `DecodedErrPPublisher.__init__` lit en `lsl_io.py:458-461`), « les trois
  compteurs » (`:902`), « 8 voies » (`:793`). ✓
- **`registry.check()`** : `marker_epoch_s = 0,9 == pre_s + post_s`, `pre_s`/`post_s` bien en
  attributs de CLASSE (`:133-134`). ✓
