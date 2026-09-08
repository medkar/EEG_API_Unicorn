# Tâche 8 — le c-VEP de bout en bout

Projet **EEG_API_Unicorn** : API BCI pour étudiants, moteur headless + LSL. Lire `CLAUDE.md`.

**Dernière des trois calibrations menées par une fenêtre.** Le P300 (tâche 4) et l'ErrP (tâche 7)
ont ouvert la voie — lis leurs rapports (`task-4-report.md`, `task-7-report.md`), tu y trouveras
deux pièges que tu vas rencontrer tels quels. Mais **le c-VEP n'est pas un troisième exemplaire du
même geste**, et la section suivante dit pourquoi.

## ⚠️ Ce qui rend le c-VEP différent des deux autres

**Ses marqueurs ne délimitent RIEN.** Ceux du P300 et de l'ErrP disent « un événement a eu lieu,
découpe autour » ; celui du c-VEP dit « à cet instant, le code affiché était à sa frame 0 ». C'est
une **HORLOGE**. Le mode décode en continu sur une fenêtre glissante, comme le SSVEP, en
reconstruisant la phase par `int((t_fin − t_ref) × refresh) % code_len`.

Conséquences, toutes les trois structurantes :

1. **Le chemin partagé entre entraînement et décodage n'est PAS `epoch_from_stream`**, c'est
   `CVEPRuntime.phase_a` — la reconstruction de la phase depuis le marqueur `cycle`. C'est
   l'invariant central du chantier, sur l'autre axe : **appelle-la, ne la réimplémente pas.**
2. **L'émetteur doit CONTINUER à publier `cycle` pendant la calibration.** Sans l'horloge il n'y a
   pas de phase, donc pas d'époque alignée : le mode ne décoderait pas mal, il ne décoderait
   **rien**. `cue` s'ajoute, il ne remplace rien.
3. **La panne caractéristique de ce mode ne casse rien.** Une phase fausse de quelques frames ne
   lève aucune exception ; les corrélations baissent juste assez pour que rien ne se déclenche, et
   c'est indiscernable de quelqu'un qui fixe mal. Deux gestes la produisent, à une ligne l'un de
   l'autre : horodater AVANT le flip, ou annoncer un `refresh` que l'écran ne tient pas.

⚠️ **`src/stimulus/cvep.py --smoke` porte LE test qui protège ce sous-système** : il rejoue une
course de rendu image par image et compare la phase que le moteur reconstruirait à celle
réellement AFFICHÉE, **lue dans les pixels de l'écran** — pas dans le compteur de l'émetteur, qui
ne peut que se donner raison. Il exige **zéro** frame d'écart tant qu'aucune image n'est sautée.
**Ne l'affaiblis pas, ne le déplace pas, n'en relâche pas la tolérance.** Étends-le.

## À livrer

1. **`src/core/modes/cvep_calib.py`** — `CVEPCalibration(MarkerCalibrationRuntime)` avec
   `runtime_cls_du_mode = CVEPRuntime` et `_entrainer(enregistre, fs)`.
2. **`src/stimulus/cvep.py`** — un mode `--calibrer`.
3. **`src/core/modes/cvep.py`** — son `Calib` gagne `runtime_cls=CVEPCalibration` et un `epoch_s`
   non nul.
4. **`src/research/cvep_calibrate.py`** — réduit : sa moitié d'entraînement monte dans `core`.

## Le protocole de marqueurs, en calibration

```json
{"mode": "cvep", "event": "calib_start", "trials": 18}
{"mode": "cvep", "event": "cue", "target": 2}
{"mode": "cvep", "event": "cycle", "refresh": 60.0}   ← CONTINUE pendant toute la séance
{"mode": "cvep", "event": "calib_end"}
```

`cue` porte la cible **réellement cerclée** à l'écran. L'émetteur dessine déjà un cercle vert
autour de la cible consignée : la vérité publiée doit être celle-là, pas celle que le tirage avait
décidée.

## Les deux décodeurs

La calibration entraîne **eCCA ET rCCA sur les MÊMES époques** et écrit **deux** fichiers horodatés.
Le gagnant est nommé par un **McNemar exact**, et « indiscernables » est la réponse attendue.

⚠️ **Ne nomme jamais un gagnant sur deux pourcentages bruts.** La mesure existante — 37 décisions
appariées à la géométrie du moteur (k = 2 cycles) — donne eCCA 59,5 % contre rCCA 64,9 %, soit
8 décisions discordantes et **McNemar p = 0,727**. Les cinq points d'écart sont du bruit. Ce dépôt
a déjà commis cette faute une fois et l'a corrigée ; ne la recommets pas.

`entraine_les_deux(epochs, labels, fs, refresh, band, …)` dans `src/research/cvep_calibrate.py` est
**déjà une fonction pure** de ses époques : c'est elle qui monte dans `core`, telle quelle.

## Deux pièges hérités, à reprendre tels quels

- **Le cycle d'import** `cvep.py` ↔ `cvep_calib.py` cassera `python src/core/modes/cvep.py`.
  Patron : import tardif dans une propriété — va le lire dans `p300.py`/`p300_calib.py`.
- **La géométrie SAUVEGARDÉE.** Côté P300, le modèle était construit avec ses valeurs par défaut
  alors que les époques étaient découpées avec celles du runtime : mêmes nombres, tous les tests
  verts, et un refus certain du modèle fraîchement calibré au premier déplacement de constante.
  Pour le c-VEP, les nombres qui décident sont `refresh`, `code_len`, `fs`, `band` et `channels` :
  **le modèle doit porter ceux avec lesquels les époques ont RÉELLEMENT été enregistrées.** Ferme
  l'aller-retour par un test — le modèle produit doit être accepté par un vrai `CVEPRuntime`.

## Le résultat de `_entrainer`

Au minimum : `{"modele", "modele_rcca", "nom", "n_essais", "acc_ecca", "acc_rcca", "mcnemar_p",
"verdict", "honnetete"}`.

⚠️ Le verdict et la phrase d'honnêteté sont indexés **par clé de résultat, jamais par identifiant de
mode** (dispositif posé en tâche 6, après que la page a affiché « 576 essais, 0 fenêtres
d'entraînement — classes : » sous un résultat P300). Ajoute tes clés, ne branche pas sur `mode_id`.

**La phrase d'honnêteté du c-VEP doit dire** — vérifie dans `docs/recette.md` §2.9 plutôt que de me
croire :
- à **6 cibles le hasard est à 16,7 %**, jamais 50 % ;
- le 59,5 / 64,9 % est un chiffre **HORS LIGNE**, en validation croisée sur les époques d'une
  calibration — ce n'est pas une justesse en direct, encore moins à travers le réseau ;
- ce que le moteur produira est un couple **~46 % d'émission / ~71 % de justesse à l'émission**
  (à k = 2, seuils 0,26/0,09), parce qu'il ajoute deux seuils et un vote ; comparer le mauvais
  dénominateur fabrique un verdict faux dans les deux sens ;
- **le c-VEP n'a jamais été décodé au casque par le moteur.**

## Les tests

Autotest par module, `python src/core/modes/cvep_calib.py`, sortie **1** si échec, `chk(cond, msg)`
avec des phrases françaises qui disent ce qui est vérifié et pourquoi.

**LE test de ta tâche** : la calibration et le décodage reconstruisent la **même phase**, vérifié
**PAR LES VALEURS** sur une course qui inclut une frame sautée — pas par l'identité des fonctions.
Une réimplémentation qui donne aujourd'hui les mêmes nombres dérivera demain ; c'est la dérive
qu'on interdit. Prouve son rouge par une translation franche d'au moins une frame.

Côté `src/stimulus/cvep.py --smoke`, en plus de l'existant (que tu conserves intact) : `calib_start`
puis `calib_end` ; un `cue` par bloc portant la cible réellement cerclée ; et **l'horloge `cycle`
continue de battre pendant la calibration**.

Côté `cvep_calib.py` : McNemar est calculé et rendu ; le verdict rend le TEST, pas seulement l'écart
entre deux pourcentages ; deux fichiers candidats sont produits ; rien n'est écrit dans `data/`.

## Contraintes qui te lient

- `src/core/` n'importe **jamais** `research`, `console` ni `stimulus`, ni pygame ni Qt.
  `src/stimulus/` n'importe **jamais** `research` ni `console`. Vérifié par
  `python src/core/server.py --smoke`.
- Une fenêtre de `src/stimulus/` **n'ouvre JAMAIS le casque**.
- **Ne touche pas au décodage du c-VEP**, ni à ses seuils (`CVEP_CORR_MIN`, `CVEP_MARGIN`), ni à sa
  géométrie de décision. **Ne rouvre pas** les hypothèses réfutées : *dynamic stopping* et **codes
  Gold distincts** sont mesurés et écartés.
- **Code et commentaires en français**, commits en anglais.
- **Aucun test n'écrit dans le vrai `data/`** — enregistrements EEG d'une personne identifiable,
  dépôt PUBLIC. `git status` ne prouve rien : `core.config.empreinte_dossier`.
- ⚠️ Aucun autre programme du projet ne tourne pendant tes tests.

## Quand tu as fini

```bash
python src/core/modes/cvep_calib.py
python src/core/modes/cvep.py
python src/core/cvep_models.py
python src/core/cvep_code.py
python src/core/cvep_decoder.py
python src/core/cvep_rcca.py
python src/core/modes/marker_calib.py
python src/stimulus/cvep.py --smoke
python src/core/server.py --smoke
python src/console/app.py --smoke
```

Commite (anglais), rapport dans `task-8-report.md`, message final réduit à : statut, hash, une
ligne de tests, réserves.
