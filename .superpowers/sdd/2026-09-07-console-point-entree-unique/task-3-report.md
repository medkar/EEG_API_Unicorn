# Tâche 3 — rapport

**Statut : DONE_WITH_CONCERNS.** Commit `e309202`. Tout est vert ; les réserves sont en bas, et
l'une d'elles change une phrase du brief.

## Ce qui est livré

- `src/core/modes/marker_calib.py` (nouveau) — `MarkerCalibrationRuntime`.
- `src/core/config.py` — `CALIB_FENETRE_ATTENTE_S = 30.0`, `CALIB_FENETRE_SILENCE_S = 15.0`,
  `CALIB_TMP_PREFIX = "calib_candidat_"`, chacune avec sa justification en commentaire.

`MarkerCalibrationRuntime` **hérite** de `CalibrationRuntime` au lieu de le recopier. C'est
l'arbitrage #1 rendu structurel plutôt que testé : `state()`, `cancel()`, `_terminer()`,
`restant_s()`, `terminee` et le vocabulaire des phases viennent du parent, donc la forme de
`snapshot()["calibration"]` ne PEUT pas diverger de ce que `console/calib_page.py` lit. Ce qui est
réécrit est la seule chose qui diffère : la ligne du temps.

La géométrie de l'époque est lue, jamais redéclarée (`pre_s`/`post_s` en `@property` sur
`runtime_cls_du_mode`), et l'époque est prélevée par `core.p300_decoder.epoch_from_stream` — le
même appel, mot pour mot, que `core/modes/p300.py::_encaisser_flash`.

Les trois causes d'abandon passent toutes par le **même** `cancel()` hérité. Une seule porte, donc
une seule règle : rien d'entraîné, rien de sauvegardé, époques libérées.

## La preuve de mutation

Le brief demande de décaler l'époque de la calibration d'un échantillon (`pre_s=self.pre_s + 1.0 /
fs`), de constater le rouge, de retirer, de relancer. **La première tentative est restée VERTE**,
et c'est le résultat le plus utile de la tâche.

### Tour 1 — la mutation du brief, sur la seule géométrie P300 : VERT

```
  OK   …de MÊME FORME : même nombre d'échantillons, mêmes voies ((238, 8) contre (238, 8))
  OK   et IDENTIQUES À L'ÉCHANTILLON PRÈS : … (0 époque(s) différente(s) sur 12 comparables)
  ÉCHEC changer la géométrie du runtime de décodage DÉPLACE la calibration du même coup :
        176 échantillons prélevés pour 175 attendus
[marker-calib] VERDICT : PROBLÈME
```

**Pourquoi.** `epoch_from_stream` calcule `int(round(pre_s * fs))`, et `round()` de Python arrondit
la moitié vers le PAIR. À `pre_s = 0,15` et `fs = 250`, `round(37,5) = 38` ; à `pre_s + 1/fs =
0,154`, `round(38,5) = 38` **aussi**. La mutation n'est pas mal détectée : elle ne déplace
littéralement RIEN. Un « décalage d'un échantillon » n'est pas exprimable par `pre_s + 1/fs` à ces
nombres-là, et un test écrit sur cette seule géométrie serait **infalsifiable** — exactement le
défaut que ce fichier existe pour ne pas avoir.

**Correctif apporté au test** : l'accord des deux épochages est désormais vérifié sur **deux**
géométries — celle du P300 (0,15 / 0,80 s) et une seconde (0,30 / 0,40 s) où l'absorption n'a pas
lieu (75 → 76). Le seul écart entre les deux jeux d'assertions est `runtime_cls_du_mode`, ce qui
fait d'ailleurs de la seconde géométrie la preuve que `pre_s`/`post_s` sont bien LUS et pas
recopiés.

### Tour 2 — la même mutation, test durci : ROUGE

```
  OK   [géométrie P300 (0,15 / 0,80 s)] …de MÊME FORME : ((238, 8) contre (238, 8))
  OK   [géométrie P300 (0,15 / 0,80 s)] et IDENTIQUES À L'ÉCHANTILLON PRÈS : (0 sur 12)
  ÉCHEC [géométrie 0,30 / 0,40 s] …de MÊME FORME : ((176, 8) contre (175, 8))
  ÉCHEC [géométrie 0,30 / 0,40 s] et IDENTIQUES À L'ÉCHANTILLON PRÈS : (0 sur 0 comparables)
  ÉCHEC changer la géométrie du runtime de décodage DÉPLACE la calibration du même coup
        (238 échantillons contre 176)
[marker-calib] VERDICT : PROBLÈME
```

### Tour 3 — mutation par TRANSLATION PURE (`pre_s + 1/fs`, `post_s − 1/fs`) : ROUGE

Faite en plus, parce que le tour 2 laisse un doute légitime : est-ce la FORME qui rougit, ou le
CONTENU ? Cette mutation-ci garde la longueur (175 = 175) et ne déplace que la fenêtre.

```
  ÉCHEC [géométrie P300 (0,15 / 0,80 s)] …de MÊME FORME : ((237, 8) contre (238, 8))
  ÉCHEC [géométrie P300 (0,15 / 0,80 s)] et IDENTIQUES À L'ÉCHANTILLON PRÈS : (0 sur 0)
  OK   [géométrie 0,30 / 0,40 s] …de MÊME FORME : ((175, 8) contre (175, 8))
  ÉCHEC [géométrie 0,30 / 0,40 s] et IDENTIQUES À L'ÉCHANTILLON PRÈS :
        (12 époque(s) différente(s) sur 12 comparables)
[marker-calib] VERDICT : PROBLÈME
```

La ligne qui compte est l'avant-dernière : **la forme reste verte, le contenu rougit sur 12/12
époques.** L'assertion d'alignement porte donc bien toute seule.

### Tour 4 — mutation retirée : VERT

```
[marker-calib] VERDICT : OK       (exit 0)
[calibration]  VERDICT : OK       (exit 0)
[config]       VERDICT : OK       (exit 0)
```

## Les quatre commandes demandées

```
python src/core/modes/marker_calib.py    -> [marker-calib] VERDICT : OK        exit 0
python src/core/modes/calibration.py     -> [calibration]  VERDICT : OK        exit 0
python src/core/server.py --smoke        -> tous les VERDICT : OK              exit 0
      dont [smoke-frontiere] 39 fichiers scannés, 0 violation(s) de frontière
```

En plus (CLAUDE.md : « après toute modification ») : `python src/console/app.py --smoke` → OK,
`python src/research/app.py --smoke` → OK, `python src/core/config.py` → OK.
Aucun test n'écrit sur le disque : le `_selftest` de ce module ne crée ni fichier ni dossier
temporaire, et `git status` ne montre que les deux fichiers de la tâche.

## Un bug attrapé par le test, pas par la relecture

Première version : `calib_end` faisait passer en `entrainement` **et** l'entraînement s'exécutait
dans le **même** tour, parce que `encaisser` tourne en tête de `tick`. La console sonde à 10 Hz un
état qui serait alors passé directement des essais au résultat — l'écran serait resté figé sur le
dernier essai pendant tout le `fit`, ce qui a exactement la tête d'un moteur planté. Corrigé en
comparant la phase à ce qu'elle était **avant** le lot du tour (`phase_avant`).

## Ce que j'ai dû arbitrer

1. **La chauffe est un PLANCHER, et `calib_start` est retenu pendant.** Le brief dit « les
   marqueurs reçus pendant la chauffe sont JETÉS » ; pris à la lettre, `calib_start` serait jeté
   aussi, et la fenêtre devrait DEVINER la durée de la chauffe pour ne pas être déclarée absente —
   un accord tacite à 15 s entre deux processus, sans poignée de main. Or la justification que le
   brief donne lui-même du délai de 30 s (« une fenêtre pygame plein écran met plusieurs secondes à
   s'initialiser ») ne tient que si l'on attend l'annonce **peu après le lancement**, donc pendant
   la chauffe. J'ai donc tranché : l'annonce est retenue quand elle arrive, la phase `essais` ne
   s'ouvre qu'une fois les 15 s écoulées, et tout marqueur d'ÉPOQUE reçu entre-temps est jeté,
   compté (`marqueurs_chauffe`, exposé dans l'instantané) et dit une fois au journal.
   **Conséquence pour les tâches 4, 7 et 8** : la fenêtre doit occuper les ~15 premières secondes
   avec son briefing avant son premier essai, sinon ces essais-là sont perdus — silencieusement du
   point de vue de l'étudiant, bruyamment dans le terminal.

2. **`imagery_s = None` sur la classe, et c'est un contrôle, pas un ménage.** `registry.check()`
   fait `getattr(calib.runtime_cls, "imagery_s", None)` et refuse un `Calib.epoch_s` inférieur.
   L'héritage donnait `imagery_s = 4.0` : les trois calibrations à fenêtre auraient été refusées en
   bloc (« epoch_s=0,95 s est SOUS imagery_s=4 s ») pour une grandeur que personne n'y prélève.
   Le tampon reste correctement dimensionné par l'autre chemin, déjà vérifié :
   `marker_epoch_s + MARKER_LATE_S` du MODE, que `check()` lie déjà à `pre_s + post_s`.
   **Pour les tâches 4/7/8** : `Calib.epoch_s` d'une calibration « fenetre » ne dimensionne rien de
   plus, il doit seulement être `> 0` — mettre `pre_s + post_s` est le choix lisible.

3. **`etape` reste VIDE de bout en bout**, et c'est testé. `CalibPage._maybe_beep` joue un top au
   front montant de `etape` vers « cue ». Recopier ici le nom de l'événement reçu ferait sonner la
   console à chaque `cue` du P300 ou du c-VEP, par-dessus un stimulus visuel verrouillé à la frame,
   dans une séance où le sujet doit rester immobile et fixer. Le seul rôle du son ici serait de
   gêner.

4. **`duree_estimee_s()` = chauffe + `duree_protocole_s`** (attribut de classe, 0,0 par défaut). Le
   moteur ne peut PAS deviner la durée d'un protocole qu'il ne mène pas. La sous-classe la calcule
   depuis `core/config.py` (P300_CAL_ROUNDS, P300_REPS, SOA en frames…) — jamais depuis
   `src/stimulus/`, que `core` n'a pas le droit d'importer. Laissée à 0, la page de calibration
   affichera « ≈ 0,2 min pour 576 essais », ce qui est faux à l'œil : **c'est aux tâches 4/7/8 de
   la renseigner.**

5. **`total()` compte des ÉPOQUES, pas des manches.** Le champ `trials` de `calib_start` doit être
   annoncé dans la même unité que ce que `essai` incrémente (une époque enregistrée = un essai).
   Une autre unité ne casse rien mais affiche un avancement faux et fait mal régler la détection de
   fenêtre morte.

6. **La fenêtre morte ne s'annule QUE si des essais manquent.** Condition littérale du brief
   (« alors que `calib_start` annonçait davantage d'essais »). Un total annoncé de 0 ou illisible
   est traité comme « inconnu », donc le silence redevient une mort — sans quoi une fenêtre muette
   sur son `trials` gèlerait la séance pour toujours.

## Réserves (le WITH_CONCERNS)

- **Un cas gèle encore la séance, par construction** : tous les essais annoncés sont arrivés et
  seul `calib_end` s'est perdu. La calibration attend alors indéfiniment. Je n'ai pas voulu
  entraîner toute seule dans ce cas : ce serait un **second** déclencheur d'entraînement à côté de
  `calib_end`, donc une seconde vérité sur « quand la séance est finie ». La sortie est le bouton
  « Abandonner » de la console, et le journal le dit une fois pour qu'on ne cherche pas ailleurs.
  À rouvrir si la séance au casque montre que le `calib_end` se perd vraiment.

- **Le mode et sa calibration se voleraient les marqueurs.** `EngineServer.markers_murs` tient UN
  curseur par `mode_id`, et l'appel le fait avancer. Si le mode P300 décode pendant que sa
  calibration tourne, chaque marqueur n'est vu que par l'un des deux, au hasard du tour de boucle —
  deux décodages muets, sans la moindre erreur. Je le DIS bruyamment à la construction (un `print`
  quand `spec.id in engine.active`), mais je ne peux pas le REFUSER depuis `core/modes/` : c'est
  `server.submit("start_calibration")` qui devrait rejeter, et `server.py` n'est pas dans mon
  périmètre. **À traiter par la tâche 5** (console) ou par un refus côté `submit`.

- **Commentaire périmé laissé en place, hors périmètre** : `src/core/server.py` (~l. 179-184 et
  ~l. 244-247 de `registry.py`) parle encore de calibrations « natives » et de
  `kind="natif"` / `research/app.py`, vocabulaire supprimé par les tâches 1-2. Le CODE est juste
  (le filtre `runtime_cls is not None` reste le bon) ; seule la prose ment. Je n'ai pas touché ces
  fichiers, le brief listant `config.py` comme seul fichier à modifier.

- **Rien de tout ceci n'a vu un casque.** Les deux délais (30 s / 15 s) sont raisonnés, pas
  mesurés : le 30 s vaut ce que vaut l'estimation « une fenêtre pygame plein écran met plusieurs
  secondes », et le 15 s tient six fois la plus longue pause connue (2,5 s). Ils se révéleront
  justes ou non à la première séance réelle, et ce sont deux constantes de `core/config.py`,
  faciles à bouger.
