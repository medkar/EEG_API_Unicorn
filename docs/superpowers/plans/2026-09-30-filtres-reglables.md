# Plan — Filtres réglables, coupe-bande secteur, FBCSP (2026-09-30)

Demandé par l'utilisateur le 2026-09-30, après la question « le coupe-bande 50 Hz devrait-il servir
aux autres modes ? » : « implémente tes recommandations », et FBCSP « en option désactivable, comme
ça au moins c'est là ». Pas de spec séparée : les décisions sont ci-dessous, prises par le
coordinateur et annoncées à l'utilisateur.

## Décisions

1. **Un seul filtre de décodage** : `core/filtrage.py:passe_bande(x, fs, bande, secteur_hz, axis)`
   — Butterworth ordre 4 en sections, zéro phase, puis coupe-bande `iirnotch` (Q 30). Les trois
   `bandpass` (MI, P300/ErrP, c-VEP) y délèguent et prennent `secteur_hz=`. **FAIT** (`f2055d8`).
2. **Le modèle porte son filtre** : `band` (existait) et `secteur_hz` (nouveau) dans MIModel,
   P300Model, ErrPModel, CVEPModel, RCCAModel. L'entraînement les fixe, le décodage les relit. Un
   fichier d'avant n'a pas de secteur → décodé sans coupe-bande, comme il a appris. **FAIT**.
3. **Une bande réglable = deux `Param` float** `bande_bas` / `bande_haut`, déclarés par
   `contract.params_bande(defaut, bas, haut, aide)` ; `contract.bande_de(params, defaut)` la relit.
   Les bornes garantissent que la bande contient le cœur du signal du paradigme (donc bas < haut
   par construction). **FAIT** (l'outil ; aucun mode ne l'utilise encore).
4. **Où se règle la bande** : dans « Entraîner » pour les modes à modèle (MI, P300, ErrP, c-VEP),
   jamais dans « Régler » — la changer au décodage ferait décoder un modèle sur un autre filtre
   que celui qu'il a appris, sans erreur. Dans « Régler » pour le SSVEP (pas de modèle).
5. **Bornes** (défaut = la bande de toujours) :

   | mode | défaut | coupure basse | coupure haute | toujours dedans |
   |---|---|---|---|---|
   | MI | 8–30 | 1 à 10 | 20 à 45 | 10–20 Hz (haut du mu, bas du bêta) |
   | P300 | 1–12 | 0,1 à 2 | 8 à 40 | 2–8 Hz |
   | ErrP | 1–10 | 0,1 à 2 | 8 à 40 | 2–8 Hz |
   | c-VEP | 2–45 | 0,5 à 5 | 20 à 60 | 5–20 Hz |
   | SSVEP | 5–40 | 1 à 8 | 20 à 60 | + chaque fréquence cible dans la bande (contrainte existante) |

6. **Le secteur (50/60 Hz) est un réglage du POSTE** : `config.SECTEUR_HZ` (défaut 50),
   `EngineServer(secteur_hz=…)`, choisi sur l'écran de départ et retenu (`Memoire`), `--secteur`
   pour le moteur seul. Le suivent : chaque entraînement (enregistré dans le modèle), le filtre
   d'acquisition (σ du bandeau, SSVEP : `NoiseTypes.FIFTY/SIXTY`), le contrôle alpha, le rejet
   d'artefact du Neuro, les tracés du Brut.
7. **FBCSP** (Ang et al. 2008) pour le MI, **option d'entraînement, décochée par défaut** (non
   mesurée ici ; la seule séance MI archivée est à 40 % à 3 classes). Le banc découpe la BANDE
   réglée en sous-bandes d'~4 Hz, un CSP par sous-bande, sélection des caractéristiques par
   information mutuelle, LDA. La sélection vit DANS le pipeline, donc dans chaque pli de la CV.
8. **Bouton fantôme** : `calib_page` montre le bouton « Appliquer » du formulaire générique, que
   rien ne branche (la calibration MI l'a depuis toujours, et le smoke l'EXIGE). Il se cache,
   comme sur `mesure_page` : les réglages d'un entraînement partent avec « Commencer ».

## Règles communes à toutes les tâches

- Lire `CLAUDE.md`. Textes affichés : `tr("clé")` + `src/core/langues/fr/*.json` (clé LITTÉRALE,
  `{valeurs}` exactes, aucun texte orphelin) ; **éditer les JSON avec l'outil Edit uniquement**
  (d'autres tâches les éditent en même temps : un script qui réécrit le fichier entier écraserait
  leurs clés). Aides de réglage = le `help` du `Param` (bulle ⓘ).
- Tests : chaque garde nouvelle est vue ROUGE sur une mutation, puis verte — le dire dans le
  rapport avec la mutation. Compter les `chk` avant/après : aucun retiré sans le dire.
- ⚠️ **D'autres tâches tournent en même temps sur le même dépôt.** Ne lancer QUE les autotests
  listés dans ta tâche. **Jamais** `server.py --smoke` ni `console/app.py --smoke` : le
  coordinateur les lance seul, après. Si un autotest rougit sur un flux LSL introuvable ou un
  délai, relance-le une fois ; s'il rougit encore, dis-le sans chercher plus loin.
- Commit : `git add` de TES fichiers seulement (jamais `-A`), message en anglais terminé par
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Si `index.lock`
  existe, attends 10 s et réessaie. Ne pas pousser.
- Si une consigne de ce plan te semble fausse face au code, dis-le dans ton rapport plutôt que de
  l'appliquer à moitié.

## T1 — Fondations — FAIT (`f2055d8`)

## T2 — Motor Imagery : bande réglable + FBCSP

Fichiers : `src/core/mi_decoder.py`, `src/core/modes/mi_calib.py`, `src/research/mi_compare.py`,
`src/core/langues/fr/modes.json` (clés `calib.mi.param.*`), éventuellement `src/core/mi_models.py`.

1. `mi_decoder.py` : méthode `"fbcsp"` dans `build_pipe` / `MIModel`.
   - `sous_bandes(bande)` : `n = max(2, round((haut - bas) / 4))` sous-bandes égales entre les
     deux coupures (8–30 → 6 × 3,67 Hz ; 4–40 → 9 × 4 Hz).
   - Un transformer `FilterBankCSP(fs, sous_bandes, n_per_class=2, secteur_hz=None)` : pour chaque
     sous-bande, `bandpass(..., secteur_hz)` puis le `CSP` existant ; `transform` concatène les
     log-variances. Picklable (joblib) : pas de lambda.
   - Pipeline : `FilterBankCSP → SelectKBest(mutual_info_classif avec random_state=0 via
     functools.partial, k = 2 × n_per_class × n_classes, soit la dimension d'UN CSP) → LDA`.
   - `MIModel(method="fbcsp")` : `_prep` fait le re-référencement CAR SANS passe-bande global
     (le banc filtre lui-même) ; le passe-bande par sous-bande porte le coupe-bande.
   - `predict_proba`, `save`/`load`, `cv_`, `cv_groupee_` inchangés dans leur forme.
   - Autotest : (a) sur ERD synthétique (mu à 10 Hz) avec une bande 4–40, FBCSP sépare
     (`cv_groupee_` nettement au-dessus du hasard) ; (b) **espion** : `mutual_info_classif` ne
     reçoit, dans chaque pli de la CV groupée, QUE des lignes d'apprentissage (moins que le total)
     — c'est ce qui prouve que la sélection ne fuit pas ; mutation : sélection faite une fois sur
     tout le jeu avant la CV → rouge ; (c) aller-retour joblib d'un modèle FBCSP.
2. `modes/mi_calib.py` : `CALIB.params` gagne `*params_bande(MI_BAND, (1, 10), (20, 45), aide)`
   et `Param(key="fbcsp", kind="bool", default=False, …)`. `_entrainer` construit
   `MIModel(fs=fs, band=bande_de(self.params, MI_BAND), method="fbcsp" if self.params.get("fbcsp")
   else MI_METHOD, secteur_hz=getattr(self.engine, "secteur_hz", SECTEUR_HZ))`. Le résultat
   affiché (détails) nomme la méthode et la bande. Autotest : une séance jouée avec une bande
   non défaut + fbcsp produit un modèle qui PORTE cette bande, cette méthode et le secteur du
   moteur ; mutation « `_entrainer` ignore la bande » → rouge.
3. Aides (`modes.json`) : bande = « le Motor Imagery lit le rythme mu (8-12 Hz) et bêta (13-30 Hz)
   du cortex moteur ; le filtre est enregistré dans le modèle ». FBCSP = « découpe ta bande en
   sous-bandes d'environ 4 Hz et garde celles qui séparent le mieux TES classes ; élargis la bande
   (par exemple 4-40 Hz) pour lui laisser le choix. Non mesuré sur ce casque : compare avec
   « Tester » ».
4. `research/mi_compare.py` : ajouter `fbcsp` à la comparaison, sur le signal NON filtré
   (re-référencé), avec la même CV groupée.
5. `mi_models.decrire` : si un champ de description existe, y ajouter la méthode (FBCSP ou CSP).
6. Autotests à lancer : `python src/core/mi_decoder.py`, `python src/core/modes/mi_calib.py`,
   `python src/core/mi_models.py`, `python src/core/modes/mi_test.py`, `python src/core/i18n.py`.

## T3 — P300 et ErrP : bande réglable à l'entraînement

Fichiers : `src/core/modes/p300_calib.py`, `src/core/modes/errp_calib.py`, `src/core/modes/p300.py`
et `src/core/modes/errp.py` (leur `Calib(...)` gagne `params=`), `modes.json`.

- `Calib(params=params_bande(P300_BAND, (0.1, 2), (8, 40), aide))`, idem ErrP avec `ERRP_BAND`.
- `_entrainer` → `entrainer(...)` / `selection_loro(...)` reçoivent `band` et `secteur_hz`
  (`getattr(self.engine, "secteur_hz", SECTEUR_HZ)`) et les passent à CHAQUE `P300Model(...)` /
  `ErrPModel(...)` construit, y compris ceux de la validation (leave-one-round-out, balayage) :
  un modèle de CV filtré autrement que le modèle final mesurerait autre chose que lui.
- Archiver la bande et le secteur dans le `.npz` d'époques s'il y a un champ de géométrie à côté
  de `pre_s`/`post_s` (ré-entraînement futur).
- Autotests : le modèle produit porte bande + secteur ; mutation « un modèle de CV construit avec
  les défauts » → rouge. Lancer : `python src/core/modes/p300_calib.py`,
  `python src/core/modes/errp_calib.py`, `python src/core/p300_models.py`,
  `python src/core/errp_models.py`, `python src/core/modes/marker_calib.py`,
  `python src/core/i18n.py`.

## T4 — c-VEP : bande réglable à l'entraînement

Fichiers : `src/core/modes/cvep_calib.py`, `src/core/modes/cvep.py` (`Calib(params=…)`),
`modes.json`.

- `Calib(params=params_bande(CVEP_BAND, (0.5, 5), (20, 60), aide))`.
- `_entrainer` → `entrainer_dans(..., band=…, secteur_hz=…)` → `entraine_les_deux(...)` passe
  `secteur_hz` à `CVEPModel(...)` ET `RCCAModel(...)` (et partout où la CV en construit).
- Autotests : les DEUX modèles écrits portent bande + secteur, relus par `cvep_models.charger` ;
  mutation → rouge. Lancer : `python src/core/modes/cvep_calib.py`,
  `python src/core/cvep_models.py`, `python src/core/i18n.py`.

## T5 — SSVEP : bande réglable dans « Régler »

Fichiers : `src/core/modes/ssvep.py`, `src/core/modes/contract.py` (contrainte `dans_la_bande`),
`src/core/acquisition.py` (`_filter`/`occipital_window` acceptent une bande), `src/core/config.py`
(`propose_frequencies`/`available_frequencies` acceptent une bande), `src/core/server.py`
(UNIQUEMENT `propose_params`, pour passer la bande courante), `modes.json`.

- `SPEC.params` gagne `*params_bande(BANDPASS, (1, 8), (20, 60), aide)` (affecte le décodage :
  repos refait). `dans_la_bande` lit `bande_bas`/`bande_haut` dans les valeurs quand elles
  existent, `BANDPASS` sinon.
- Le runtime filtre sa fenêtre avec SA bande : `acq.occipital_window(block, bande=(bas, haut))`
  (le σ du bandeau garde `BANDPASS` : ce n'est pas un choix de décodage). `CCADecoder(max_freq=
  haut)` : les harmoniques au-dessus de la coupure haute sont ignorées, comme aujourd'hui à 40.
- « Proposer » respecte la bande courante.
- `ssvep_mesure.py` (le « Tester ») reprend les réglages du mode : vérifier que la bande y passe.
- Autotests : `python src/core/modes/contract.py`, `python src/core/modes/ssvep_mesure.py`,
  `python src/core/config.py`, `python src/core/i18n.py` (PAS `modes/ssvep.py` : il ouvre des
  flux — le coordinateur le lance). Mutation « le runtime ignore la bande » → rouge quelque part.

## T6 — Le secteur du poste (après T2-T5 : touche `server.py` et la console)

Fichiers : `src/core/server.py`, `src/core/modes/alpha.py`, `src/core/neuro_monitor.py` et/ou
`src/core/modes/neuro.py`, `src/console/demarrage.py`, `src/console/app.py`,
`src/console/mode_page.py`, `src/console/live_views.py`, `console.json`.

- `EngineServer(..., secteur_hz=SECTEUR_HZ)` → `self.secteur_hz` ; `UnicornAcquisition(notch=
  NoiseTypes.FIFTY si 50 sinon SIXTY)` ; `snapshot()["secteur_hz"]` ; `--secteur {50,60}`.
- Alpha, Neuro : leur coupe-bande suit `engine.secteur_hz`.
- Écran de départ : une liste « Secteur électrique » (50 Hz Europe / 60 Hz Amériques), retenue
  dans `Memoire` ; `_lancer_moteur` la passe au moteur. Tracés du Brut : `secteur_hz` du moteur.
- Tests : smoke moteur (un entraînement à 60 Hz produit un modèle à 60), autotest de
  `demarrage.py`, smoke console. Le coordinateur lance les smokes.

## T7 — Console : le bouton fantôme des entraînements (coordinateur)

`calib_page` cache `formulaire.bouton` comme `mesure_page` ; l'assertion du smoke qui exige le
bouton de la calibration MI est retournée (aucune page d'entraînement ne le montre).

## T8 — Revue par sous-système, correctifs, documentation (coordinateur)

Tranches ≤ 40 Ko. Doc : `CLAUDE.md`, `docs/qa.md` (points nouveaux : bande à l'entraînement,
FBCSP, secteur à l'écran de départ), `docs/recette.md`, README si la section des modes cite les
bandes.
