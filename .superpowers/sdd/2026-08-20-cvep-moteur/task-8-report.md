# Task 8 — la documentation, et la procédure de la séance

**Statut : terminé.** SHA `b0f857c` (base `c8e5a81`), 6 fichiers, +755/−117.
`docs/superpowers/plans/2026-08-20-cvep-moteur.md` laissé **non commité**, comme demandé.

## Suite complète des autotests

**40 commandes lancées une par une, 0 échec.** Aucun python du projet ne tournait pendant la
suite (le seul `python.exe` du poste appartient à un autre dépôt, `Promptuino`).

`core/` (26) : `config` · `modes/{contract,registry,runtime,raw,ssvep,neuro,mi,calibration,mi_calib,p300,errp,cvep}` ·
`{mi_models,mi_decoder,cca_decoder,neuro_monitor,markers,p300_models,p300_decoder,errp_models,errp_decoder,cvep_code,cvep_decoder,cvep_rcca,cvep_models,lsl_io}` ·
`acquisition --synthetic` · `server --smoke`
`console/` (1) : `app --smoke`
`research/` (8) : `app --smoke` · `{p300,errp,cvep}_stimulus --smoke` · `itr` · `controller`
`archive/` (4) : `{mi_calibrate,mi_pilot,cvep_pilot,cvep_rcca_pilot} --smoke`

**`data/` intact** : 43 fichiers, tailles et horodatages identiques avant/après, le plus récent
toujours `cvep_rcca_model.npz` au **2026-08-21 14:17:45**. Vérifié par horodatage, pas par
`git status`.

⚠️ **Un point relevé au passage, pré-existant et hors périmètre** : le mtime du dossier `data/`
bouge pendant la suite. Bissection : c'est **`server.py --smoke`**, qui écrit
`data/mi_model_smoke.joblib` dans le VRAI `data/` puis le supprime dans un `finally`
(`server.py:1650`). Aucun modèle réel ne peut être écrasé (le nom est distinct), mais c'est
exactement l'angle mort que `archive/README.md` documente pour `empreinte_dossier` — écriture puis
suppression à l'intérieur d'une même exécution. Un `Ctrl+C` au mauvais moment laisserait le fichier,
et `mi_models.modeles_disponibles` le proposerait alors comme modèle.

## Affirmations trouvées FAUSSES en les vérifiant dans le code

**1. « Un désaccord de `refresh` avec le modèle fait refuser le DÉMARRAGE. »** (brief) — **Faux, et
c'est la correction la plus importante.** `CVEPRuntime.__init__` ne lève que sur deux causes :
modèle absent/illisible, ou `code_len` en désaccord avec la config. Le désaccord de rafraîchissement
est levé par `maj_reference` (`cvep.py:283`) et **rattrapé** par `_encaisser_marqueurs`, qui le
transforme en `_refuse_marqueur` : le marqueur est jeté, compté dans `marqueurs_refuses`, annoncé
par paliers 1/10/100/1000 — et **le mode continue de tourner et de publier `-1`** sous
`sans_reference`. Laisser l'exception remonter arrêterait le moteur entier, donc les autres modes
avec lui. Documenté partout comme un refus **des marqueurs, pas du démarrage**, avec la consigne
explicite « ne guette pas un plantage, lis les premières lignes du terminal » : quelqu'un qui attend
un crash conclurait que tout va bien.

**2. « ~40 % si on compte tous les verdicts. »** (brief) — **Chiffre périmé.** Il vaut pour
l'**ancien** réglage (4 cycles = 4,2 s par consigne, transition = 64 % de l'intervalle). Au réglage
actuel `CYCLES_PAR_CIBLE = 8` → consigne 8,4 s, transition 2,70 s = **32,1 %** (recalculé, pas lu).
Le 2.9 donne le chiffre actuel et garde le ~40 % comme *raison historique* du rallongement.

**3. `docs/recette.md` 1.1 — l'ordre des tuiles.** Annonçait « Brut, SSVEP, Neuro, MI, c-VEP, P300,
ErrP ». `registry.MODES` donne **Brut, SSVEP, Neuro, MI, P300, ErrP, c-VEP** — le c-VEP ferme la
marche. Un opérateur aurait signalé une régression.

**4. `docs/recette.md` 1.2 — « Les 3 tuiles grisées ».** Entièrement faux : `grid.py:129` grise sur
`status != "moteur"`, et les **sept** specs sont `status="moteur"`. Aucune tuile n'est grisée.
`core/modes/external.py` a été supprimé avec sa dernière entrée. Test réécrit — il vérifie
maintenant l'inverse, plus le fait que le bouton **Calibrer** n'apparaît que sur la page MI
(`mode_page.py:44` teste `calib.kind == "console"`, et c-VEP/P300/ErrP sont `"natif"`).

**5. `docs/recette.md`, section finale — « 3 modes de décodage sur 6 ne sont pas sur le réseau »**
et **« Les marqueurs entrants n'existent pas »**. Les deux étaient faux depuis le 2026-08-17.

**6. `docs/SPEC.md` §5 — « il existe CINQ valeurs de `paradigm` ».** Il y en a **six** :
`c-VEP` manquait. Un client qui filtre sur ce champ aurait ignoré le flux en silence.

**7. `docs/SPEC.md` §7 — « c-VEP : stimulus externalisé NON (MVP) »** et **§13 F1 « bloqué par le
couplage frame-par-frame »**. Renversés le 2026-08-21. La contrainte n'a pas disparu, elle a changé
de camp — c'est écrit comme tel, et la **calibration** reste native.

**8. `docs/SPEC.md` §3.1 — « le P300 et le c-VEP sont validés sur casque dans `research/` ».** Les
deux décodeurs ont déménagé dans `core/`.

**9. `examples/receiver.py` — l'aide de `--stream` ne listait que 5 suffixes sur 8.** Le code accepte
n'importe quel suffixe (pas de `choices=`), donc `--stream decoded_cvep` marchait déjà ; mais la
commande que je cite dans quatre documents n'était documentée nulle part dans le fichier que
l'étudiant lit. Aide et docstring complétées, avec la mention que le champ est libre.

**10. Attribution eCCA/rCCA sur la séance de référence — incohérence interne du dépôt.**
`cvep_calibrate.py:754` et `:776` écrivent « 64,9 % contre 59,5 % » sans dire qui est qui, tandis
que la fixture `:778` passe `eCCA: 22/37` (59,5 %) et `rCCA: 24/37` (64,9 %) — donc **rCCA est le
64,9 %**, confirmé par `b=3` (eCCA seul) < `c=5` (rCCA seul) et par `progress.md:392`. J'ai écrit
l'attribution dans ce sens. Le commentaire du code reste ambigu ; je ne l'ai pas touché (hors
périmètre documentaire), mais il mérite une ligne un jour.

**Aucune commande citée ne s'est révélée inexistante.** Les 73 lignes `python …` des six documents
ont été extraites et vérifiées : `--mode` accepte bien `ssvep, neuro, mi, p300, errp, cvep` ;
`cvep_stimulus.py` porte `--windowed --refresh --seconds --seed --no-wait --smoke` ;
`archive/cvep_pilot.py` porte `--model`.

## Numéros recalculés depuis le code (pas recopiés)

`code_len` 63 · fenêtre 2 cycles = **2,10 s** · `period_s` 0,2 → vote 3 × 0,2 = **0,60 s** ·
**transition 2,70 s** · consigne 8 cycles = **8,4 s** · part à jeter **32,1 %** · péremption
3 cycles = **3,15 s** · seuils **0,26 / 0,09** · vote **2 sur 3** · 6 cibles, hasard **16,7 %** ·
voies **Pz, PO7, Oz, PO8** · chauffe **15 s**, repos **0 s** · calibration **natif** ·
flux `decoded_cvep`, **10 voies** dans l'ordre `target_index, confidence, score_0…score_5,
corr_min, margin` · McNemar `b=3, c=5` → **0,7265625**, 8 discordantes sur 37.

## Doutes

- **Le 2.9 n'a jamais été joué.** C'est un script écrit contre le code, pas une procédure éprouvée.
  Le point le plus fragile est le **dépouillement manuel** : compter à la main les `decoded_cvep`
  postérieurs à un horodatage, à 5 Hz sur ~5 min, est pénible et faux la première fois. Un petit
  script de dépouillement (lire le journal de l'émetteur + le flux, appliquer la fenêtre) rendrait
  ce test bien plus fiable — je ne l'ai pas écrit, il n'était pas au périmètre.
- **Le biais A-B-A que je documente n'est pas mesuré.** J'affirme que la saturation C3/Cz à la
  réouverture devrait épargner le c-VEP puisqu'il décode sur Pz/PO7/Oz/PO8 — c'est une déduction de
  `CVEP_CHANNELS`, jamais une mesure. Je l'ai écrit comme telle, mais quelqu'un pourrait la lire
  comme un fait établi.
- **Le repère « ~60-65 % » du 2.9 est hors ligne**, en leave-one-out sur une calibration. Rien ne
  garantit qu'il tienne en direct à travers le réseau — le moteur ajoute un vote 2-sur-3 que la
  mesure hors ligne n'avait pas. C'est dit dans le test, mais c'est le chiffre qu'un opérateur
  retiendra, et il est le plus susceptible d'être démenti par la séance.
- **La calibration c-VEP en synthétique (test 1.16) n'a pas été exécutée par moi.** Je l'affirme
  possible parce que `research/app.py --smoke` exerce `cvep_calibrate.calibrate` et que
  `--synthetic` existe ; je n'ai pas joué le chemin interactif complet, qui écrirait dans `data/`.
- **`docs/recette.md` grossit** (710 → ~980 lignes). Le 2.9 fait à lui seul 200 lignes. C'est
  défendable — une séance casque ne se répète pas — mais il approche du seuil où personne ne le lit
  en entier avant de commencer.
