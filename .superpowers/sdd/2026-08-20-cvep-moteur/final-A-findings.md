# Revue finale de branche — tranche A : `src/core/modes/cvep.py`

Relecture intégrale du fichier (1336 lignes, 58 assertions dans `_selftest`), lu contre ses voisins
`modes/p300.py`, `modes/errp.py`, `modes/mi.py`, `modes/contract.py`, `modes/runtime.py`,
`core/config.py`, `core/lsl_io.py`, `core/cvep_models.py`, `core/cvep_rcca.py`,
`core/cvep_decoder.py`, `core/server.py` et `research/cvep_calibrate.py`.

**Aucun programme n'a été exécuté** (six relecteurs en parallèle, noms de flux LSL partagés). Les
constatations qui demandent une exécution portent une ligne « À VÉRIFIER PAR EXÉCUTION ».

Décompte : **1 Critical · 6 Important · 6 Minor**.

Ce que je cherchais et que les revues par tâche ne pouvaient pas voir : les invariants qui tiennent
dans chaque fonction prise seule mais pas dans leur **composition** — l'état qui survit à une
transition de phase, et les interactions entre le vote, les compteurs et l'horloge. Les trois
premières constatations sont exactement de cette forme.

---

## CRITICAL

### C1. Le vote glissant SURVIT à la perte de l'horloge — la première fenêtre après le retour de l'émetteur émet une cible sur des votes arbitrairement vieux

**Fichier** : `src/core/modes/cvep.py:541-556` (branche `phase is None` de `_run_step`), à comparer à
`src/core/modes/cvep.py:352-363` (`_reset_rest`).

**Ce qui casse.** `_reset_rest` a été durci pour vider `self._votes` (ligne 363), avec un commentaire
qui dit précisément pourquoi : « ses fenêtres décrivent un montage qu'on vient de toucher, elles ne
doivent pas peser sur la première décision d'après », et la section 9 de l'autotest (`rt_p`, lignes
1316-1328) le prouve. **Le même raisonnement s'applique mot pour mot à la perte d'horloge, et là il
n'est appliqué nulle part.** La branche `phase is None` remet à zéro `_corr_gagnant`/`_corr_second`,
incrémente son compteur, publie `-1`, et **retourne sans toucher `self._votes`**. La file de votes
n'est donc ni vidée, ni vieillie : elle est **gelée** pendant toute la coupure — une seconde ou une
heure, rien ne la borne dans le temps.

**Scénario concret** (réglages par défaut : `CVEP_VOTE_LEN=3`, `CVEP_MIN_VOTES=2`, `corr_min=0,26`).

1. L'étudiant fixe la cible 2. Trois fenêtres passent les seuils :
   `_votes = [(cible_2, 0.31), (cible_2, 0.29), (cible_2, 0.33)]`. Le mode publie « cible 2 ».
2. L'émetteur c-VEP est fermé (fenêtre pygame fermée, plantage, ou simplement le second terminal
   coupé — le cas normal : l'émetteur tourne dans un terminal séparé, cf. `CLAUDE.md`).
3. Après `CVEP_PEREMPTION_CYCLES` cycles (3,15 s), `_phase_et_cause` rend `reference_perimee`. Le
   mode publie `-1` à ~5 Hz pendant dix minutes. `_votes` reste **exactement** `[(cible_2, 0.31),
   (cible_2, 0.29), (cible_2, 0.33)]` du début à la fin.
4. L'émetteur est relancé. La toute première fenêtre décodée note la **cible 5** à 0,28 (au-dessus
   des seuils). `_votes` devient `[(cible_2, 0.29), (cible_2, 0.33), (cible_5, 0.28)]`.
5. `Counter` (ligne 580) : cible_2 = 2, cible_5 = 1 → `gagnant = cible_2`, `compte = 2 >= min_votes`.
   Le test de la ligne 581 ne mord pas.
6. **Le moteur publie `target_index = 2`, `confidence = (0.29+0.33)/2 = 0.31`, et incrémente
   `decodages`** — sur la première fenêtre d'après une coupure de dix minutes, alors que cette
   fenêtre-là avait choisi la cible 5.

Sur le flux, l'échantillon est indiscernable d'une sélection franche et stable : indice valide,
confiance au-dessus de `corr_min`, scores plausibles. C'est très exactement la panne muette que le
fichier existe pour éliminer, et c'est le même défaut que celui que la section 9 garde déjà, sur un
chemin qui n'a pas été gardé. Le chemin non gardé est en outre **le plus fréquent des deux** :
relancer l'émetteur arrive plusieurs fois par séance, « refaire le repos » une ou deux fois.

Aucune assertion ne couvre ce cas : la section 6 exerce bien `phase is None`, mais sur un runtime au
`template` PLAT (corrélations nulles), donc avec une file de votes qui n'a **jamais** contenu autre
chose que `None`.

**Correctif minimal** — vider la file sur le chemin sans phase, symétriquement à `_reset_rest` :

```python
        phase, cause = self._phase_et_cause(t_fin)
        if phase is None:
            self._corr_gagnant = self._corr_second = None
            # ...et la FILE DE VOTES avec, pour la même raison que `_reset_rest` : ces fenêtres
            # décrivent un instant où l'horloge tenait encore. Sans ça, la première fenêtre
            # d'après la coupure conclut sur des votes arbitrairement vieux, avec une confiance
            # parfaitement normale.
            self._votes.clear()
```

**Test à ajouter** (jumeau littéral du bloc `rt_p` de la section 9, ~10 lignes) : une fenêtre franche,
puis une fenêtre `reference_perimee`, puis une fenêtre franche → `target_index == -1` et
`decodages == 0`. Mutation qui doit le rougir : supprimer le `self._votes.clear()` ci-dessus.

---

## IMPORTANT

### I1. Tourner `corr_min` en pleine séance casse l'invariant `confidence >= corr_min` — sur l'échantillon qui porte les deux

**Fichier** : `src/core/modes/cvep.py:595-604` (le commentaire qui affirme l'invariant) et
`src/core/modes/cvep.py:606-621` (`_publish`, qui publie les deux valeurs côte à côte).
Confirmé côté moteur : `src/core/server.py:337-344` (`_set_params` met `rt.params` à jour **en
place**, sans reconstruire le runtime ni appeler `begin_rest`).

**Ce qui casse.** Le fichier écrit, lignes 599-601 :

> « Chacune de ces corrélations valant au moins `corr_min` par construction (sinon la fenêtre aurait
> voté None), leur moyenne aussi : l'invariant est tenu par CONSTRUCTION. »

C'est vrai **à seuil constant**. Or ce chantier vient précisément de rendre `corr_min`/`margin`
réglables **sans reconstruire le runtime** (`affecte_decodage=False`, lignes 683 et 692). Chaque vote
de la file a été jugé contre le seuil en vigueur **au moment où il a été empilé** ; `_publish` (ligne
613) relit le seuil **courant**. Les deux ne sont plus le même nombre pendant `vote_len - 1` fenêtres
après tout changement — et rien ne les réconcilie.

C'est l'inverse exact du MI, où l'invariant tient : `prob_min` y est `affecte_decodage=True`, donc
un changement reconstruit le runtime et vide la file (`mi.py:64-65`). Le bloc 8 de `mi.py::_selftest`
existe pour épingler cet invariant ; le c-VEP l'affirme sans l'épingler, et l'a cassé en gagnant le
réglage à chaud.

**Scénario concret** (défauts 3/2, `corr_min = 0,26`).

1. Fenêtres 1 et 2 : cible 2 à ρ = 0,30 puis 0,31 (les deux passent 0,26).
   `_votes = [(cible_2, 0.30), (cible_2, 0.31)]`.
2. Le mode émet trop de faux positifs ; l'opérateur monte `corr_min` à **0,40** depuis la console.
   L'aide du réglage invite explicitement à le faire en séance (ligne 688 : « DESCENDS cette valeur
   en séance… SANS risque »). `server._set_params` met `rt.params` à jour en place : ni flux recréé,
   ni chauffe, **ni file vidée**.
3. Fenêtre 3 : cible 2 à ρ = 0,45 → passe le nouveau seuil, empilée.
   `_votes = [(cible_2, 0.30), (cible_2, 0.31), (cible_2, 0.45)]`, compte = 3.
4. `_publish(index_cible_2, (0.30+0.31+0.45)/3 = 0.3533, scores, corr_min=0.40, margin=…)`.

L'échantillon LSL annonce donc, **sur ses propres voies**, `confidence = 0,353` et `corr_min = 0,40`.
Un client qui refiltre sur `confidence >= corr_min` — le geste que `cvep_channel_labels`
(`lsl_io.py:429-442`) et la docstring de `DecodedCVEPPublisher` (lignes 468-473) l'invitent
explicitement à faire, puisque les deux voies existent **pour ça** — jette une fixation stable et
valide. Et un enregistrement dépouillé plus tard porte un échantillon auto-contradictoire.

Symétriquement pour `margin` : un vote empilé sous une marge lâche pèse encore quand la marge a été
resserrée.

**Correctif minimal** — mémoriser le couple de seuils sous lequel la file a été constituée, et la
vider quand il change (une ligne dans `__init__`, trois dans `_run_step`) :

```python
        # __init__
        self._seuils_du_vote = None

        # _run_step, juste avant `self._votes.append(...)`
        seuils = (float(self.params["corr_min"]), float(self.params["margin"]))
        if self._seuils_du_vote != seuils:
            # Les votes déjà empilés ont été jugés contre l'ANCIEN couple : les garder ferait
            # publier une confiance SOUS le `corr_min` que le même échantillon annonce.
            self._votes.clear()
            self._seuils_du_vote = seuils
```

**Test à ajouter** : deux fenêtres franches à 0,30 sous `corr_min=0,26`, puis `rt.params["corr_min"]
= 0,40`, puis une fenêtre à 0,45 → aucune ligne publiée ne doit porter `index >= 0` avec
`confidence < corr_min`. C'est le jumeau du bloc 8 de `mi.py`, transposé au seul mode qui règle son
seuil à chaud.

---

### I2. Un `refresh` NaN traverse les DEUX gardes de `maj_reference` et fait lever `int()` plus tard — hors du `try/except`, donc il arrête le moteur ENTIER

**Fichier** : `src/core/modes/cvep.py:282-283` (les gardes), `src/core/modes/cvep.py:328`
(`int(age * self._ref_refresh + _EPS_FRAME)`), `src/core/modes/cvep.py:466-472` (le `try/except` qui
ne couvre pas ce cas).

**Ce qui casse.** `_encaisser_marqueurs` type-checke `refresh` avec soin (lignes 461-465, avec le
piège `bool`-hérite-de-`int` traité) et enveloppe `maj_reference` dans un `try/except ValueError`,
avec ce commentaire, ligne 470-471 :

> « laisser l'exception remonter arrêterait le moteur ENTIER, donc les autres modes actifs avec lui »

C'est le bon réflexe, et il est contourné par une valeur qui est **acceptée** à l'ingestion et
**explose à l'usage**, un tour de boucle plus tard, en dehors du `try` :

* `isinstance(nan, float)` → `True`, et ce n'est pas un `bool` → la garde de type passe ;
* `abs(nan - 60.0) > 1.0` → **`False`** (toute comparaison avec NaN est fausse) → la garde de
  rafraîchissement passe. `self._ref_refresh = nan` est posé (ligne 289) ;
* `_phase_et_cause` : `age < 0.0` → `False` ; `age > CVEP_PEREMPTION_CYCLES * code_len / nan` →
  `age > nan` → **`False`** ; on tombe donc ligne 328 sur
  `int(nan * ... ) % 63` → **`ValueError: cannot convert float NaN to integer`**.

Cette `ValueError` sort de `_run_step` → `tick` → et **la boucle du moteur n'attrape rien** :
`server.py:1221-1224` appelle `runtime.tick(...)` sans `try/except` (seul le `tick` de calibration
est protégé, lignes 1228-1240). L'exception casse le `while`, le `finally` ferme tout : **le moteur
s'arrête, avec le SSVEP, le neuro, le MI et tout ce qui tournait avec lui.** Et la référence est
empoisonnée définitivement : chaque fenêtre suivante lèverait pareil.

`Infinity` est refusé (par chance : `abs(inf-60) > 1` est vrai). Seul NaN passe.

**Scénario concret.** `core/markers.py:174` utilise `json.loads` **sans** `parse_constant`, donc les
littéraux non standards `NaN`/`Infinity` sont acceptés par défaut en Python. Deux chemins réalistes :

* un émetteur tiers — c'est le point du produit, `stream_in` est réglable et le protocole est public
  (`research/cvep_stimulus.py`, docstring : « protocole publié (figé) ») — qui calcule
  `refresh = 1 / mean(frame_dts)` et rencontre un `0/0` sur sa première frame ;
* plus court encore : `python src/research/cvep_stimulus.py --refresh nan`. Le garde-fou de
  l'émetteur est `if refresh is not None and float(refresh) <= 0.0` (`cvep_stimulus.py:345`) —
  `nan <= 0` vaut `False`, donc il passe, et l'émetteur publie `{"mode":"cvep","event":"cycle",
  "refresh": NaN}` (ce que `json.dumps` écrit tel quel).

Le moteur meurt à la première fenêtre décodée, avec un traceback `ValueError` dans `int()` — un
message qui n'oriente vers rien.

**Correctif minimal** — refuser explicitement le non-fini dans `maj_reference`, là où le refus est
déjà compté et annoncé par paliers :

```python
import math   # en tête du module

    def maj_reference(self, ts, refresh):
        refresh = float(refresh)
        ts = float(ts)
        # ⚠️ `isfinite` D'ABORD : NaN rend FAUSSE toute comparaison, donc `abs(nan - 60) > 1`
        # n'attrape rien. La valeur serait acceptée ici et ferait lever `int()` dans
        # `_phase_et_cause` — hors du `try/except` de `_encaisser_marqueurs`, donc en arrêtant
        # le moteur entier. (`json.loads` accepte le littéral `NaN` par défaut, cf. `markers.py`.)
        if not (math.isfinite(refresh) and math.isfinite(ts)):
            raise ValueError(f"horodatage ou rafraîchissement non fini ({ts!r}, {refresh!r}) — "
                             f"le marqueur de cycle est inutilisable")
        if abs(refresh - self.model.refresh) > 1.0:
            ...
```

**Test à ajouter** : `rt.maj_reference(ts=100.0, refresh=float("nan"))` doit lever, et
`rt.phase_a(101.0)` doit rendre `None` derrière — jumeau de la section 3, dont le test « ...et le
refus n'a laissé AUCUNE référence utilisable » existe déjà.

---

### I3. Tout le sous-système de REFUS de marqueur n'a AUCUNE assertion — et l'une de ses mutations arrête le moteur

**Fichier** : `src/core/modes/cvep.py:435-481` (`_encaisser_marqueurs` + `_refuse_marqueur`),
`src/core/modes/cvep.py:249` et `389` (`marqueurs_refuses`), `src/core/modes/cvep.py:128`
(`_PALIERS_REFUS`).

**Ce qui casse.** La docstring du module présente ce refus comme le **« Second refus, propre à ce
mode »** (lignes 48-53) et lui consacre un paragraphe entier. Il représente ~45 lignes de production.
Aucune des 58 assertions ne l'exerce :

* `_encaisser_marqueurs` n'est jamais appelée avec un marqueur **défectueux**. La section 3 appelle
  `maj_reference` **en direct** et attrape l'exception dans le test — elle prouve que `maj_reference`
  lève, jamais que `_encaisser_marqueurs` l'attrape ;
* `marqueurs_refuses` **n'est pas dans le jeu de clés vérifié** ligne 1096-1098 (`set(st) >= {…}`), et
  sa valeur n'est asserée nulle part ;
* `_refuse_marqueur` et `_PALIERS_REFUS` (128) ne sont jamais atteints ;
* la garde `isinstance(refresh, bool)` (461), commentée sur cinq lignes, n'est exercée par rien.

Mutations qui laissent les **58 assertions vertes** :

| mutation d'UNE ligne | conséquence en séance |
|---|---|
| supprimer le `try/except ValueError` (466-472) | **un seul** marqueur au mauvais refresh — le cas que le module documente comme attendu — arrête le moteur entier (cf. I2 pour l'absence de filet dans `server.py:1221-1224`) |
| supprimer `not isinstance(refresh, (int, float))` (461) | un marqueur sans champ `refresh` donne `float(None)` → `TypeError`, **non attrapée** par `except ValueError` → moteur arrêté |
| supprimer `self._marqueurs_refuses += 1` (478) | l'état n'annonce plus jamais un émetteur mal réglé ; la séance est muette et la cause invisible |
| remplacer `_PALIERS_REFUS` par `(1,)` | un émetteur mal réglé se dit une fois, à ~1 marqueur/s pendant une heure |

Les deux premières transforment un incident **prévu et documenté** en arrêt du moteur, donc en perte
de la séance de tous les autres modes actifs.

**Correctif minimal** — une section 6bis de ~15 lignes, sur le `_FauxMoteur` qui existe déjà :

```python
    # --- 6bis. Les marqueurs REFUSÉS : comptés, dits par paliers, et jamais propagés -----------
    rt_r = _runtime_de_test(code_len=63, refresh=60.0)
    rt_r._out = _FauxPublieur()
    rt_r._opened = True
    moteur_r = _FauxMoteur(rng_c.normal(0.0, 8.0, (8 * n_cyc, 8)), ts_c)
    moteur_r._lots = [[(t_fin_c - 0.5, {"mode": "cvep", "event": "cycle", "refresh": 75.0}),
                       (t_fin_c - 0.4, {"mode": "cvep", "event": "cycle"}),          # champ absent
                       (t_fin_c - 0.3, {"mode": "cvep", "event": "cycle", "refresh": True})]]
    rt_r._run_step(moteur_r, lsl_ts=t_fin_c)      # ne doit PAS lever
    chk(rt_r.state()["marqueurs_refuses"] == 3 and rt_r._ref_ts is None,
        f"trois marqueurs inutilisables sont COMPTÉS et n'installent aucune référence — et "
        f"surtout ils ne remontent pas : une exception ici arrêterait le moteur entier "
        f"({rt_r.state()['marqueurs_refuses']}, {rt_r._ref_ts})")
    chk(rt_r.state()["sans_reference"] == 1,
        f"...la fenêtre compte donc en « sans_reference », pas en « sous_les_seuils »")
```

et ajouter `"marqueurs_refuses"` au jeu de clés de la ligne 1096.

---

### I4. `output()` n'est épinglé nulle part : supprimer la clé `motif` — la raison d'être annoncée du mode — laisse les 58 assertions vertes

**Fichier** : `src/core/modes/cvep.py:622-640` (`_publish`), `src/core/modes/cvep.py:368-372`
(`channels()`), `src/core/modes/cvep.py:660-665` (`_channels`). Consommateur :
`src/console/live_views.py:160-167` et `237-286`.

**Ce qui casse.** Trois trous du même genre, tous fermés chez le voisin `mi.py` et ouverts ici :

1. **La clé `motif` n'est lue par aucune assertion.** Le module lui consacre son plus long ⚠️ (lignes
   55-69 : « QUATRE façons de ne pas décider… quatre gestes OPPOSÉS ») et `live_views.py:279-283`
   n'affiche QUE ça sur un `-1`. La supprimer de `_publish` (ligne 639) laisse tout vert, et la page
   c-VEP retombe sur `'pas de décision'` — le mode perd en silence sa fonctionnalité annoncée.
   *Scénario* : une refonte de `_publish` déplace le motif dans le journal ; les trois smokes passent ;
   la séance casque suivante affiche « — (pas de décision) » pendant vingt minutes sans jamais dire
   que l'émetteur n'a jamais été lancé.

2. **Le jeu de clés d'`output()` n'est pas figé.** `mi.py:509` fait
   `chk(set(rt.output()) == {…})` avec un commentaire qui explique exactement pourquoi : la console
   aiguille son rendu sur une **clé présente**. Ici la chaîne est
   `probas` → `threshold` → `corr_min` (`live_views.py:160-167`) : ajouter une clé `threshold` à
   `_publish` — le réflexe naturel quand on aligne le c-VEP sur le SSVEP — fait basculer la page
   c-VEP sur `_update_scores`, donc sur « échelle z · seuil … » appliqué à des corrélations. C'est
   la panne que le commentaire des lignes 627-631 dit vouloir empêcher, sans qu'aucune assertion ne
   la fasse « rougir ».

3. **`channels()` (368-372) et `_channels` (660-665) ne sont exercés par rien.** Les **10 voies**
   annoncées par le contrat (`target_index, confidence, score_0…5, corr_min, margin`) ne sont figées
   nulle part dans ce fichier : le faux publieur (1017) épingle l'ordre des **arguments** de `push`,
   pas les étiquettes. Muter `channels()` en `cvep_channel_labels(4)` laisse tout vert, et l'état
   publié annoncerait quatre voies pendant que le flux en publie dix — exactement la divergence que
   la docstring de `channels()` dit prévenir, et que `mi.py` bloc 10 épingle chez son voisin.

**Correctif minimal** — trois assertions, à glisser en section 5 :

```python
    chk(set(rt_c.output()) == {"target_index", "confidence", "scores", "corr_min", "margin",
                               "motif"},
        f"la sortie du moteur porte exactement les clés attendues — la console aiguille son "
        f"rendu sur `corr_min`, et affiche `motif` (et RIEN d'autre) sur un -1 "
        f"({sorted(rt_c.output())})")
    chk(rt_c.output()["motif"] == _MOTIFS_FR["sous_les_seuils"],
        f"...et le motif est le texte EN CLAIR du moteur, pas la clé du compteur "
        f"({rt_c.output()['motif']!r})")
    chk(rt_c.channels() == _channels(rt_c.params)
        == ["target_index", "confidence"] + [f"score_{i}" for i in range(CVEP_N_TARGETS)]
        + ["corr_min", "margin"],
        f"les 10 voies publiées, et l'état dit les MÊMES que le catalogue ({rt_c.channels()})")
```

---

### I5. La branche rCCA du mode est devenue ATTEIGNABLE et reste exercée par aucun test (point escaladé n° 1)

**Fichier** : `src/core/modes/cvep.py:123` (`_DECODEURS`), `:199` (l'instanciation), `:497`
(`self.decodeur.n_cycles * self.model.n_cyc`), `:520-522` (`.corr_min`/`.margin` posés sur le
décodeur), `:342-347` (`cv_`, `code_len`, `refresh` lus sur le modèle).

**Verdict : oui aux deux.** Voir la section « Verdict sur le point escaladé n° 1 » plus bas pour la
chaîne de preuve complète. Résumé :

* `research/cvep_calibrate.calibrate()` (ligne 528) sauvegarde désormais un
  `cvep_rcca_model_<horodatage>.npz` à **chaque** calibration, via `RCCAModel.save`, qui écrit le
  champ `decoder="rCCA"` (`core/cvep_rcca.py:235`) ;
* `cvep_models.charger` **accepte** ce fichier dès lors que ses `codes` égalent
  `_codes_affiches()` ligne pour ligne. Avec la config livrée (`CVEP_LAG_ROTATION = 0`, lags
  `[0,11,21,32,42,53]` **croissants**, `cvep_lags` à `config.py:647-649`), `presentes =
  sorted(set(labels))` reproduit exactement l'ordre du plan, donc **une calibration complète produit
  un modèle rCCA accepté** ;
* `MOTIFS` (`cvep_models.py:69`) le liste, et le tri est par date : **c'est le fichier le plus récent,
  donc le DÉFAUT proposé** par `Param(key="model", choices_fn=_modeles_disponibles)` juste après une
  calibration — une chance sur deux, selon lequel des deux `save()` a la mtime la plus haute.
* Aucun test du dépôt ne construit un `CVEPRuntime` sur un `RCCAModel` : `_runtime_de_test`
  (cvep.py:798-828) fabrique toujours un `CVEPModel`, `modele_appris` (1150) est un `CVEPModel`, et
  `server.py --smoke` ne démarre jamais le mode c-VEP (sa seule mention, lignes 2004-2006, teste le
  refus de calibration).

**Ce qui casse.** La colle de niveau mode — `_DECODEURS["rCCA"]`, `.corr_min`/`.margin`/`.n_cycles`
posés sur `RCCADecoder`, `model.n_cyc`, `model.channels`, `model.code_len`, `model.refresh`,
`cv_` — **n'a jamais tourné une seule fois**, ni en test ni au casque, sur le chemin qu'un étudiant
prendra par défaut à sa prochaine calibration.

**Lecture statique : je ne trouve pas de défaut dans la colle.** Tous les attributs existent avec les
bons types, `RCCADecoder.classify` a exactement le contrat de `CVEPDecoder.classify`, `_fold` prend
bien les `n_cycles` derniers cycles d'une fenêtre plus longue, et `entraine_les_deux`
(`cvep_calibrate.py:240`) construit le modèle avec `channels=list(ecca.channels)` = `CVEP_CHANNELS`,
donc `_fenetre`'s `[:, self.model.channels]` sélectionne les bonnes colonnes. Le risque est
« jamais exécuté », pas « cassé connu ».

**Deux effets de bord réels, tout de même :**

* les seuils propres au rCCA (`CVEP_RCCA_CORR_MIN = 0,24` / `CVEP_RCCA_MARGIN = 0,08`, mesurés à la
  géométrie du moteur, `config.py:440-441`) sont **écrasés dès la première décision** par
  `decide` (lignes 520-521), qui impose le couple eCCA `0,26/0,09`. Le module l'annonce (« ne servent
  plus que de repli », ligne 117) — mais ce n'est même pas un repli : `_open` et `_rest_step` lisent
  déjà `self.params`. Ces deux constantes sont donc **mortes** côté moteur. C'est un choix défendable
  et documenté ; il mérite d'être écrit tel quel dans `config.py`, qui laisse croire l'inverse ;
* `charger` d'un modèle rCCA **ré-ajuste pyntbci** (~0,3 s, `cvep_models.py:39-43`) et
  `modeles_disponibles` charge **tout** pour lister. Voir M5.

**Correctif minimal** — faire tourner la colle une fois. Le plus court, en réutilisant les fixtures
déjà présentes dans `_selftest` (section 7), est de rejouer le bloc de bout en bout sur un
`RCCAModel` :

```python
    # --- 7ter. La MÊME chaîne, avec l'AUTRE décodeur. -----------------------------------------
    # `cvep_models.charger` accepte désormais les modèles rCCA que la calibration écrit
    # (tâche 6) : `_DECODEURS["rCCA"]` est donc un chemin de PRODUCTION, pris par défaut juste
    # après une calibration. Sans ce bloc il n'aurait jamais tourné — ni ici, ni au casque.
    from core.cvep_rcca import RCCAModel
    codes = np.stack([np.asarray(c["code"], dtype=int) for c in plan])
    rcca = RCCAModel(codes, fs=fs, refresh=60.0, channels=list(CVEP_CHANNELS))
    rcca.fit([synth_cvep(code, l, len(CVEP_CHANNELS), fs, 60.0, -6.0, rng_e)
              for l in lags for _ in range(6)],
             [i for i in range(len(plan)) for _ in range(6)], compute_cv=False)
    rcca.cv_ = 0.5
    rt_r = _runtime_de_test(modele=rcca)
    chk(rt_r.model.decoder == "rCCA" and type(rt_r.decodeur).__name__ == "RCCADecoder",
        f"le décodeur suit le MODÈLE, pas un réglage ({rt_r.model.decoder}, {type(rt_r.decodeur).__name__})")
    rt_r._out, rt_r._opened = _FauxPublieur(), True
    moteur_r = _moteur_sur(lag_vrai)
    for _ in range(CVEP_MIN_VOTES):
        rt_r._run_step(moteur_r, lsl_ts=float(moteur_r.recent_ts[-1]))
    chk(rt_r.output()["target_index"] == cible and len(rt_r.output()["scores"]) == len(plan),
        f"...et la chaîne entière tourne avec lui : phase, fenêtre, seuils, vote, publication "
        f"({rt_r.output()})")
```

> **À VÉRIFIER PAR EXÉCUTION** : `python src/core/modes/cvep.py` après ajout du bloc ci-dessus —
> attendu `[cvep] VERDICT : OK`. Ce bloc importe `pyntbci` (via `RCCAModel.fit`) : si l'autotest
> doit rester exécutable sans cette dépendance, l'entourer d'un `try: import pyntbci / except
> ImportError: chk(True, "rCCA non testé : pyntbci absent")` **avec l'échec rendu visible**.
> Coût mesuré ailleurs dans le dépôt : ~0,3 s pour l'ajustement.

---

### I6. Un modèle eCCA issu d'une calibration INTERROMPUE est accepté sans un mot, là où son jumeau rCCA de la MÊME séance est refusé

**Fichier** : `src/core/modes/cvep.py:254-272` (`_desaccord_code`, le seul contrôle de stimulus du
mode) et `:187-206` (`__init__`, qui ne regarde jamais `model.n_targets`).
Sources : `research/cvep_calibrate.py:518` (le seuil de sauvegarde) et `:527`.

**Ce qui casse.** `calibrate()` sauvegarde dès que `len(set(lags)) >= 2` et `len(epochs) >= 4` — donc
une calibration abandonnée à l'ESC après **deux cibles sur six** produit deux modèles :

* le **rCCA** est écrit sur `codes_vus` (2×63), et `cvep_models.charger` le refuse proprement, en
  disant quoi faire (« il porte 2x63 codes, le stimulus actuel en affiche 6x63 ») ;
* le **eCCA** est écrit avec `n_targets=len(plan)` — c'est-à-dire **6**, le plan complet, pas les 2
  cibles réellement vues (`cvep_calibrate.py:527`). Il est accepté, il est le plus récent donc
  proposé par défaut, et `CVEPRuntime` le démarre sans un mot.

Le template eCCA est **commun à tous les lags** : le mode publie donc `score_0…score_5`, dont quatre
sortent de lags que la calibration n'a jamais présentés. `cvep_decoder.py:242-245` prévoit exactement
ce cas et écrit « on le mémorise **pour pouvoir prévenir** » — personne ne prévient.

**Scénario concret.** Un étudiant lance la calibration c-VEP, la trouve longue, appuie sur ESC après
la deuxième cible. La console affiche un modèle horodaté tout neuf, en tête de liste. Il démarre le
mode. Le flux publie six corrélations plausibles ; les cibles 2 à 5 « fonctionnent » à l'écran avec
des scores du même ordre que les deux cibles apprises. Rien, nulle part, ne dit que quatre d'entre
elles n'ont jamais été validées. Le compte-rendu de repos (`_rest_step`, lignes 408-414) annonce
`n_targets: 6` — celui du **plan**, pas celui du modèle.

Le mode ne peut pas détecter le cas aujourd'hui, parce que le champ qui devrait le porter ment :
`n_targets` vaut 6 quoi qu'il arrive. C'est une constatation qui traverse deux fichiers, donc
typiquement une constatation de revue finale.

**Correctif minimal**, en deux moitiés :

* `research/cvep_calibrate.py:527` → `ecca.save(save_path, n_targets=len(set(lags)))` (ce que le
  champ prétend décrire) ;
* `src/core/modes/cvep.py`, dans `_desaccord_code`, un second contrôle qui refuse en nommant les
  deux nombres :

```python
        cibles = int(getattr(self.model, "n_targets", 0) or 0)
        if cibles and cibles != len(self.plan):
            # 0 = modèle antérieur au champ, on ne peut rien en dire. Sinon, le template eCCA est
            # commun à tous les lags : un modèle à 2 cibles « marche » techniquement à 6, mais les
            # quatre autres n'ont JAMAIS été validées et leurs corrélations sont plausibles.
            return (f"ce modèle a été calibré sur {cibles} cible(s), le stimulus actuel en "
                    f"affiche {len(self.plan)} — les autres n'ont jamais été validées. "
                    f"Recalibre (`python src/research/app.py`, mode c-VEP) sans interrompre.")
```

Et, tant qu'on y est, faire dire à `_rest_step` la **justesse honnête du modèle** (`self.model.cv_`,
déjà publiée dans les métadonnées LSL par `_open`) : c'est le seul chiffre qui permette de lire un
journal de séance a posteriori, et il n'apparaît ni au terminal ni dans `rest_report`.

---

## MINOR

### M1. `confidence = 0.0` sur `vote_non_conclu` — verdict sur le point escaladé n° 2 : garder, et documenter la voisine

**Fichier** : `src/core/modes/cvep.py:593` (et `:555`), contre `src/core/modes/ssvep.py:152`.

**Verdict : le c-VEP a raison, le SSVEP est l'exception.** Le c-VEP publie `0.0` comme `mi.py:153` et
comme `DecodedP300Publisher` (dont la docstring, `lsl_io.py:381-384`, écrit explicitement « Quand
`target_index` vaut -1, ni `confidence` ni les `score_*` ne sont des mesures »). Trois modes sur
quatre disent la même chose ; le SSVEP est le seul à publier `max(scores)` derrière un `-1`, et sa
valeur y est de toute façon **redondante** avec les voies `score_*` qu'il publie au même moment.
Aligner le c-VEP sur le SSVEP ferait au contraire du mal : `DecodedCVEPPublisher` promet
(`lsl_io.py:468-470`) que « `confidence` … est toujours `>= corr_min` quand `target_index >= 0` », et
publier `max(scores)` sur un `-1` mettrait des valeurs de la même échelle des deux côtés de la
frontière, en invitant un client à seuiller sur `confidence` sans regarder `target_index`.

**Le vrai manque est ailleurs, et il est petit** : sur le chemin `phase is None` (ligne 555) le mode
publie `[0.0] * len(self.plan)` comme scores, et **`0,0` est une corrélation parfaitement plausible**.
Le commentaire (548-549) affirme que « `no_decision_index` dit dans les métadonnées qu'ils ne sont pas
à lire » — `no_decision_index` dit ce que vaut « pas de décision », pas que les scores sont muets.
La docstring de `DecodedCVEPPublisher` décrit les `score_*` comme « la dernière fenêtre seule » sans
mentionner ce cas.

**Correctif minimal** : reprendre la phrase du P300 dans la docstring de `DecodedCVEPPublisher`
(`lsl_io.py`, après la ligne 473) — « Quand `target_index` vaut `-1` pour perte d'horloge, les
`score_*` valent 0 et ne sont PAS des mesures : 0 est une corrélation plausible. » Aucun changement
de code.

---

### M2. Un motif inconnu : `""` à l'écran, la clé BRUTE au terminal — point escaladé n° 3

**Fichier** : `src/core/modes/cvep.py:639` (`_MOTIFS_FR.get(motif, "")`) contre `:654`
(`_MOTIFS_FR.get(motif, motif or 'pas de décision')`).

**Confirmé, et latent aujourd'hui** : les quatre seuls motifs passés (`sans_reference`,
`reference_perimee`, `sous_les_seuils`, `vote_non_conclu`) sont tous dans `_MOTIFS_FR`. Mais les deux
lectures ont des **replis différents**, ce qui contredit directement le commentaire des lignes
634-638 (« l'écran finirait par ne plus dire la même chose que le terminal — pendant une séance, sur
la seule ligne qui indique QUEL geste faire »).

**Scénario concret.** Une cinquième cause est ajoutée demain — c'est déjà arrivé une fois, `brief` en
prévoyait trois et il y en a quatre (cf. le commentaire lignes 237-246) — et l'auteur oublie une
entrée dans `_MOTIFS_FR`. Le terminal imprime `— (artefact_rejete)` ; la console imprime
`— (pas de décision)` (`live_views.py:283`, via `sortie.get('motif') or …`). Deux opérateurs devant
deux écrans lisent deux choses différentes de la même fenêtre. Pas de crash, pas de fausse donnée :
d'où le Minor.

**Correctif minimal** — une seule fonction de traduction, avec un repli qui NOMME le trou :

```python
def _motif_en_clair(motif):
    """Le motif EN CLAIR, ou la clé elle-même si la table l'a oubliée. UNE seule lecture pour
    l'écran ET le terminal : deux replis différents feraient dire deux choses de la même fenêtre.
    """
    return _MOTIFS_FR.get(motif, motif or "") if motif else ""
```

appelée aux deux endroits (`_publish` ligne 639, `_log` ligne 654), + une assertion
`chk(_motif_en_clair("inconnu") == "inconnu")`.

---

### M3. `mi.py` a le même angle mort sur `_reset_rest`, et il est encore ouvert — point escaladé n° 4

**Fichier** : `src/core/modes/mi.py:82-84` (`_reset_rest`), `src/core/modes/mi.py:373`, `:381`,
`:417` (les tests qui vident la file **à la main**).

**Confirmé.** `MIRuntime._reset_rest` vide bien `self._votes`, mais **aucune assertion ne le prouve** :

* ligne 373, `rt.begin_rest(...)` est appelée quand `_votes` est **déjà vide** (aucun `tick` en phase
  `running` ne l'a précédée) ;
* tous les blocs suivants (4 à 8) vident la file eux-mêmes — `rt._votes.clear()` ligne 381, et
  `rejoue()` ligne 417 le refait à chaque appel.

**Mutation** : supprimer `self._votes.clear()` de `mi.py:83`. Les **27** assertions de
`python src/core/modes/mi.py` restent vertes. Rien d'autre ne couvre le cas : `server.py --smoke` ne
démarre pas de mode MI avec un modèle, `console/app.py --smoke` n'instancie pas de runtime.

**Conséquence en séance** : identique à C1 — après « Refaire le repos » (donc après avoir touché les
électrodes, saliné, remis le casque), une **seule** fenêtre neuve suffit à atteindre `min_votes` sur
des votes qui décrivent le montage d'avant, et `decoded_mi` publie une intention franche avec une
confiance normale.

**Où le fermer** : dans `mi.py::_selftest`, pas ailleurs — c'est le fichier que `CLAUDE.md` liste
comme garde du sous-système MI (`python src/core/modes/mi.py`), et le seul endroit où un futur
lecteur du MI ira. Bloc de 8 lignes, transposition littérale de la section 9 du c-VEP (lignes
1316-1328), à glisser entre les blocs 8 et 9 :

```python
        # 8bis. « Refaire le repos » VIDE la file de votes. Sans ça, une seule fenêtre neuve
        # atteint `min_votes` sur des votes qui décrivent un montage qu'on vient de démonter —
        # une intention publiée avec une confiance parfaitement normale. (Le c-VEP a exactement
        # la même garde, `modes/cvep.py` section 9 : ici elle n'était prouvée par rien, tous les
        # blocs ci-dessus vidant `_votes` à la main.)
        rejoue([GAUCHE_SUR] * (min_votes - 1), t0=100.0)   # la file est PLEINE, à un vote près
        rt._out.lignes.clear()
        rt.begin_rest(now=100.0, warmup_s=0.0, duration_s=0.0)
        rt.tick(moteur, lsl_ts=110.0, now=110.0)           # warmup nul -> rest -> running
        rt.decoder.scores = lambda window: dict(GAUCHE_SUR)
        try:
            rt.tick(moteur, lsl_ts=111.0, now=111.0)
        finally:
            rt.decoder.scores = vrais_scores
        chk(rt._out.lignes and rt._out.lignes[-1][0] == -1,
            f"« refaire le repos » vide la file de votes : la première fenêtre d'après ne peut "
            f"pas conclure sur des votes d'avant ({[l[0] for l in rt._out.lignes]})")
```

> **À VÉRIFIER PAR EXÉCUTION** : `python src/core/modes/mi.py` — attendu `[mi] VERDICT : OK`, puis
> la même commande après avoir commenté `self._votes.clear()` de `mi.py:83` — attendu
> `[mi] VERDICT : PROBLÈME` sur cette seule assertion.

---

### M4. `_reset_rest` n'oublie pas `_last_log` : la première décision d'après le repos peut ne pas être tracée

**Fichier** : `src/core/modes/cvep.py:214` (`self._last_log = 0.0`) et `:352-363` (`_reset_rest`).

`_reset_rest` remet tout à zéro — référence, votes, compteurs, `_decoded` — sauf `_last_log`.
**Scénario** : l'opérateur clique « Refaire le repos » moins d'une seconde après la dernière ligne de
journal ; la chauffe de 15 s passe ; la première décision d'après tombe dans la fenêtre de silence
de `_log` **uniquement si** moins d'une seconde s'est écoulée — donc en pratique jamais, la chauffe
durant 15 s. Le trou n'est réel qu'avec une chauffe raccourcie (les smokes, `begin_rest(warmup_s=0)`),
où la première décision d'après un repos peut être avalée. Conséquence : nulle en séance, gênante
quand on dépouille un log de smoke. Correctif : `self._last_log = 0.0` dans `_reset_rest`.

---

### M5. La liste de modèles coûte désormais ~0,3 s **par calibration passée**, et le fichier le prédisait

**Fichier** : `src/core/modes/cvep.py:157-167` (`_modeles_disponibles`, le `choices_fn` du réglage
« Modèle entraîné »), `core/cvep_models.py:39-43` et `:210`.

`cvep_models.py` écrit : « si un jour `data/` contient dix modèles rCCA, c'est ici qu'il faudra
regarder ». La tâche 6 a fait de « un jour » un **compteur de calibrations** : `chemin_modele_horodate`
écrit un fichier NEUF à chaque fois (à raison, cf. l'incident d'écrasement documenté), donc `data/`
accumule un `cvep_rcca_model_*.npz` par séance. `modeles_disponibles` **charge tout pour lister**, et
`RCCAModel.load` **ré-ajuste pyntbci** (~0,3 s + ~750 ko chacun).

**Scénario** : après dix séances de calibration, ouvrir la page « c-VEP » de la console appelle
`_modeles_disponibles()` → ~3 s de ré-ajustement pyntbci, plus la RAM. Si cet appel a lieu sur le fil
Qt, l'interface gèle pendant ce temps ; s'il a lieu au démarrage du mode (`validate`), le démarrage
traîne d'autant, en pleine séance casque.

Second effet, plus sournois : si `pyntbci` n'est pas installé, `charger` attrape l'`ImportError`
(`except Exception`, ligne 133/178), rend « modèle illisible (ModuleNotFoundError) », et
`modeles_disponibles` **jette la raison** (ligne 210 ne garde que les chemins). Le modèle rCCA que
l'étudiant vient de calibrer **disparaît de la liste sans un mot**.

> **À VÉRIFIER PAR EXÉCUTION** (chronométrage, pas une assertion) :
> `python -c "import time,sys; sys.path.insert(0,'src'); from core import cvep_models; t=time.perf_counter(); n=len(cvep_models.modeles_disponibles()); print(n, time.perf_counter()-t)"`
> — attendu : un temps qui croît linéairement avec le nombre de `cvep_rcca_model_*.npz` dans `data/`.

**Correctif minimal** (hors de ce fichier, mais c'est ce fichier qui paie) : dans
`cvep_models.charger`, séparer « valider » de « charger », et ne faire le `RCCAModel.load` complet
qu'à la demande — `modeles_disponibles` n'a besoin que de la validation (champs présents + codes du
jour), qui se fait déjà **avant** le `load` (lignes 138-174).

---

### M6. Petites dettes de l'autotest et de la doc

Regroupées ici parce qu'aucune ne mérite sa propre section, et qu'aucune n'a de conséquence en séance.

1. **Assertion décorative**, `cvep.py:941-943` : `chk(SPEC.marker_epoch_s > 0.0, …)` est strictement
   impliquée par `chk(abs(SPEC.marker_epoch_s - 2.1) < 1e-9, …)` (ligne 913). Aucune mutation d'une
   ligne de production ne rougit l'une sans l'autre. C'est la seule des 58 dans ce cas (les cinq
   `chk(..., "fixture : …")` sont, elles, des auto-contrôles du test, correctement étiquetés).
2. **`_fenetre` non filtrée : invariant central, garde absente.** La docstring (lignes 488-493)
   reprend mot pour mot l'avertissement de `acquisition.motor_window` — « le défaut qui a déjà coûté
   un décodage au MI ». Or le MI a une garde DÉDIÉE pour ça (`python src/core/acquisition.py
   --synthetic`, listée dans `CLAUDE.md`), et le c-VEP n'en a pas : la section 7 décode à SNR 0 dB
   avec un signal synthétique franc, où un double `filtfilt` 2-45 Hz est presque idempotent en
   bande. Il est probable qu'ajouter `bloc = bandpass(bloc, ...)` dans `_fenetre` laisse tout vert.
   > **À VÉRIFIER PAR EXÉCUTION** : muter `cvep.py:501` en
   > `return bandpass(np.asarray(bloc[-besoin:], dtype=float)[:, self.model.channels], self.model.fs, self.model.band)`
   > (`from core.cvep_decoder import bandpass`) puis `python src/core/modes/cvep.py` — **attendu
   > `PROBLÈME`** ; si le verdict reste `OK`, l'invariant n'est gardé par rien et il faut une
   > assertion dédiée (comparer `_fenetre(engine)` à `engine.recent[-besoin:][:, channels]` terme à
   > terme).
3. **`period_s()` n'est pas redéfini** (le mode hérite les 0,2 s de `ModeRuntime.period_s`) et rien
   ne l'épingle. Le « ~5 Hz » de la spec, la latence annoncée du vote (« 3 fenêtres = 0,6 s »,
   ligne 717) et le dimensionnement du vote en dépendent tous. Le MI, lui, déclare son
   `MI_DECODE_HZ = 5.0` explicitement (`mi.py:37, 86-87`). Une ligne : `chk(abs(rt_c.period_s() -
   0.2) < 1e-9, "le c-VEP décode à ~5 Hz, comme le SSVEP et le MI")`.
4. **Docstring périmée**, `cvep.py:779-782` : « ici il n'existe pas encore de module `cvep_models` à
   monkey-patcher (tâche 3) ». Le module existe et est importé ligne 103. Le mécanisme retenu
   (repointer `CVEP_MODEL_PATH`) reste valide, mais sa justification ne l'est plus — et le fichier
   s'adresse à des étudiants qui liront cette phrase comme un fait.
5. **`_log` peut produire des lignes de ~150 caractères** : `f"{verdict:<46}"` (ligne 657) est un
   plancher, et les textes de `_MOTIFS_FR` font 90 à 110 caractères. Sur un terminal 80 colonnes en
   séance, la colonne des corrélations — la raison d'être de cette ligne (lignes 645-647) — passe à
   la ligne suivante. Un `verdict[:44]` ou un motif court pour le terminal réglerait la chose ; le
   texte long reste utile à l'écran, qui a la place.

---

## Verdict sur le point escaladé n° 1 (chaîne de preuve)

**La branche rCCA est devenue atteignable, et elle n'est exercée par aucun test.**

| maillon | fichier:ligne | état |
|---|---|---|
| la calibration écrit un modèle rCCA à chaque séance | `research/cvep_calibrate.py:412, 528` | ✅ oui, nom **horodaté**, donc jamais écrasé |
| le fichier porte le champ `decoder` | `core/cvep_rcca.py:235` (`decoder=self.decoder`) | ✅ oui, `"rCCA"` |
| `charger` accepte ce champ | `core/cvep_models.py:131, 138-142` | ✅ oui |
| le refus de STIMULUS le laisse passer | `core/cvep_models.py:154-174` | ✅ **oui pour une calibration complète** : `codes_vus` (`cvep_calibrate.py:235`) est indexé par `sorted(set(labels))`, et `cvep_lags` (`config.py:649`) rend `[0,11,21,32,42,53]` **croissants** avec `CVEP_LAG_ROTATION = 0` — l'ordre du plan et l'ordre trié coïncident |
| il apparaît dans la liste du réglage « Modèle » | `core/cvep_models.py:69, 210` + `cvep.py:167` | ✅ oui, et **trié par date**, donc candidat au défaut proposé juste après une calibration |
| `_DECODEURS["rCCA"]` est instancié | `cvep.py:199` | ✅ chemin de production |
| un test le construit | `cvep.py:798-828, 1150, 1246, 1261, 1278, 1316` | ❌ **jamais** : `_runtime_de_test` fabrique toujours un `CVEPModel`, et `modele_appris` en est un |
| `server.py --smoke` le construit | `server.py` (seule occurrence : 2004-2006) | ❌ le mode c-VEP n'y est jamais démarré |
| `console/app.py --smoke` le construit | — | ❌ le smoke console n'instancie pas de runtime |

**Donc oui aux deux**, et c'est la constatation I5 : `.corr_min`/`.margin`/`.n_cycles` posés sur
`RCCADecoder`, `model.n_cyc`, `model.channels`, `model.code_len`, `model.refresh` et `cv_` n'ont
jamais tourné. La relecture statique ne trouve pas de défaut dans cette colle — tous les attributs
existent, les contrats de `classify` coïncident, `_fold` prend bien les derniers cycles d'une fenêtre
plus longue que sa décision, et `entraine_les_deux` pose `channels=list(ecca.channels)` =
`CVEP_CHANNELS`, ce qui rend `_fenetre`'s `[:, model.channels]` correct. Le correctif est donc de
**faire tourner la branche une fois** (bloc 7ter de I5), pas de la réparer à l'aveugle.

**Deux réserves à porter au procès-verbal de la branche**, découvertes en établissant cette chaîne :

* **`CVEP_LAG_ROTATION != 0` casse la reconnaissance des modèles rCCA fraîchement calibrés.** Avec
  une rotation non nulle, `build_targets` (`cvep_code.py:69-70`) fait tourner l'ordre des lags dans
  le plan, tandis que `cvep_calibrate.py:235` empile `codes_vus` par `sorted(set(labels))`,
  c'est-à-dire **toujours croissant**. Les deux ordres divergent, `charger` refuse — avec un message
  qui accuse « un `CVEP_LAG_ROTATION` changé » alors que **rien n'a changé**. Latent
  (`CVEP_LAG_ROTATION = 0` aujourd'hui), mais `config.py:516` annonce ce réglage comme « disponible
  si une vraie asymétrie apparaît un jour ». Correctif d'une ligne dans `cvep_calibrate.py:234-235` :
  ordonner `presentes` par position dans le plan (`sorted(set(labels), key=lag_a_idx.get)`) plutôt
  que par valeur de lag.
* **`CVEP_RCCA_CORR_MIN`/`CVEP_RCCA_MARGIN` sont morts côté moteur** (cf. I5) : `decide` impose le
  couple commun à chaque décision. Leur commentaire dans `config.py:374-441` — quarante lignes de
  mesures — devrait dire qu'ils ne servent plus qu'à `cvep_rcca.py --seuils` et aux constructions
  directes de `RCCADecoder`, pas au mode.
