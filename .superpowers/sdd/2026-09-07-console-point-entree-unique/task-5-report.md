# Tâche 5 — rapport

**Statut : DONE_WITH_CONCERNS.** Trois commits, `c1ab963` → `2ee8911`. Tout est vert. La réserve
qui compte est en tête des réserves : **tant que la tâche 6 n'a pas câblé les deux boutons, plus
aucune calibration n'atteint `data/`**. C'est le demi-état voulu par le découpage du chantier, mais
il faut le savoir avant de brancher un casque.

## L'empreinte de `data/`, avant et après

C'est l'instrument demandé, et pas `git status` (`data/` est gitignoré : `git status --short data/`
rend une sortie vide même quand un test vient d'y écrire un modèle).

```
avant   43 fichiers   sha256(empreinte) = 42120328ed4df50265e14522eb61c5035423bbb52064f33b14d3293dfae8083d
après   43 fichiers   sha256(empreinte) = 42120328ed4df50265e14522eb61c5035423bbb52064f33b14d3293dfae8083d
```

(`sha256` du `{nom: (taille, mtime)}` rendu par `core.config.empreinte_dossier()`, sérialisé trié.)
Identique après la batterie complète — smoke du moteur inclus, qui joue une calibration MI RÉELLE
et l'enregistre. Zéro dossier temporaire laissé derrière (`calib_candidat_*`, `srv_data_*`, … : 0).

## Ce qui est livré

| Fichier | Ce qui y est fait |
|---|---|
| `src/core/server.py` | le refus du vol de marqueurs (2 sens × 2 endroits), le dossier candidat, `save_calibration` / `discard_calibration`, `close()`, l'adoption du candidat, `_candidats_visibles` |
| `src/core/config.py` | `CALIB_CANDIDAT_PREFIXE`, `nom_retenu()`, `chemin_libre()` + leurs tests |
| `src/core/modes/calibration.py` | `dossier` sur la classe de BASE, `dossier_ou_lever()` |
| `src/core/modes/marker_calib.py` | passe `dossier` au parent |
| `src/core/modes/mi_calib.py` | plus de `__init__`, plus de repli `DATA_DIR`, `prefixe=` sur `_chemins_libres` |
| `src/core/modes/p300_calib.py` | idem, `prefixe=` sur `chemins_libres` / `entrainer_dans` |

```
c1ab963 Refuse a mode and its own calibration reading the same marker queue
2ebf0f5 Let a calibration be judged before it is kept: data/ is written on one gesture
2ee8911 Let go of a finished calibration when the next one starts
```

## 🔴 Le vol de marqueurs — traité en premier, et dans les deux sens

C'est la moitié sérieuse, et elle est fermée à **quatre** endroits, pas deux.

**Le critère n'est pas `Calib.kind`.** Une calibration lit la file de marqueurs si sa classe de
runtime descend de `MarkerCalibrationRuntime` — c'est cette classe-là qui appelle `markers_murs`,
donc c'est elle qui vole. `kind == "fenetre"` est une **déclaration**, et une déclaration peut
cesser de décrire le code sans que rien ne le dise : les deux coïncident aujourd'hui, seule la
classe le garantit. Même règle côté « mode » : `spec.marker_epoch_s > 0`. Les deux conditions sont
exigées ensemble, parce que le vol suppose deux lecteurs.

| Sens | À la SOUMISSION | Dans la BOUCLE |
|---|---|---|
| `start_calibration` sur un mode qui décode | `submit` → refus nommant le mode à arrêter | `_start_calibration` |
| `start_mode` pendant sa calibration | `submit` → refus disant d'attendre ou d'abandonner | `_start` |

Les deux contrôles côté boucle ne sont pas de la ceinture-bretelles : `submit` juge sur l'état à
l'instant où la commande est **soumise**, et `start_mode` + `start_calibration` envoyées dans la
même fenêtre de sondage voient toutes les deux un moteur vierge. C'est exactement la course que
`_start_calibration` documentait déjà pour le double-clic sur « Commencer ».

**Le refus du sens 2 est placé AVANT `contract.validate`, délibérément.** Sinon un dépôt sans
modèle P300 s'entend dire « aucun choix disponible » alors que la vraie raison est qu'une
calibration tourne. Le test le prouve : il vide la liste de modèles le temps de l'appel et exige
quand même le bon message.

**Test** : `_smoke_vol_marqueurs()`, 11 assertions, sans casque ni boucle. Deux **négatifs** y
prouvent que le refus est ciblé et non un blocage général — la calibration d'un mode *sans*
marqueurs (MI) reste acceptée pendant qu'un mode à marqueurs décode, et un *autre* mode (SSVEP)
démarre pendant la calibration P300 — et une dernière assertion exige qu'une calibration
**terminée** ne bloque plus rien (un refus écrit « dès qu'une calibration existe » passerait tout
le reste et interdirait le mode P300 pour le reste de la séance).

## Le cycle du candidat

1. `_start_calibration` passe `dossier=self._dossier_candidat()` à **toutes** les calibrations sans
   distinction — l'argument vit sur `CalibrationRuntime`, pas sur telle sous-classe.
2. `_entrainer` écrit `candidat_<nom habituel>` dans ce dossier. Le préfixe rend le fichier
   invisible aux **cinq** motifs de découverte (`mi_model*.joblib`, `p300_model*.joblib`,
   `errp_model*.joblib`, `cvep_model*.npz`, `cvep_rcca_model*.npz`) : `glob` compare le nom entier.
3. La boucle **adopte** le résultat une fois (`_candidat_de`), `snapshot()["calibration"]["candidat"]`
   le porte, et le journal dit que rien n'est encore dans `data/`.
4. `save_calibration` **déplace** (`shutil.move`, pas `os.replace` : le temporaire du système peut
   vivre sur un autre volume) vers `chemin_libre(data_dir, nom_retenu(...))`. Le verdict reste à
   l'écran, `candidat` retombe à `None`.
5. `discard_calibration` supprime les fichiers **et** efface l'écran de verdict.
6. `close()` — appelée par le `finally` de `run()` — supprime le dossier entier, inconditionnellement.

**Il n'y a plus de repli sur `DATA_DIR`.** `dossier_ou_lever()` refuse avec une phrase lisible
(soldée en « annulé » par `_terminer`, donc visible à l'écran) plutôt que d'écrire quelque part que
personne n'a demandé. C'était ça, le défaut : une calibration qui choisissait son dossier écrivait
dans `data/` **avant** d'annoncer sa précision.

## Les preuves par mutation

Aucune assertion nouvelle n'a été écrite sans qu'on lui fasse la preuve de son rouge. Chaque
mutation ne fait rougir que ce qu'elle vise.

| Mutation | Résultat |
|---|---|
| `_refus_calibration_pendant_mode` → `None` | ROUGE sur les 3 assertions du **sens 1** seulement |
| `_refus_mode_pendant_calibration` → `None` | ROUGE sur les 3 du **sens 2** seulement — et le message devient « aucun choix disponible », exactement la mauvaise raison que le placement avant `validate` évite |
| `save_calibration` copie au lieu de déplacer | ROUGE sur « l'original n'existe plus » |
| `chemin_libre` remplacé par un `join` nu | ROUGE sur « sans avoir écrasé le fichier qui portait déjà ce nom » |
| la calibration MI écrit sans le préfixe | ROUGE sur 3 assertions **et** le moteur imprime son ⚠️ « candidat DÉCOUVRABLE » |
| `close()` neutralisée | ROUGE sur « aucun candidat orphelin » |
| `_efface_candidat` ne supprime plus les fichiers | ROUGE sur « le candidat est SUPPRIMÉ du disque » |
| `_adopte_candidat` neutralisée | ROUGE sur 5 assertions (rien à trancher, rien à enregistrer) |
| `cancel()` ne libère plus époques et moteur | ROUGE sur « la séance précédente est LÂCHÉE » (54 époques retenues) |

## Les sept tests du cahier des charges

Tous dans `_smoke` de `server.py`, avec le motif `chk(cond, msg)`.

1. **`data/` intact après une calibration terminée** — `_smoke_calibration` vérifie
   `os.listdir(data_dir) == []` juste après l'entraînement (`data_dir` détourné vers un
   `tempfile`), et l'empreinte du VRAI `data/` avant/après la fonction entière.
2. **Le candidat vit dans le temporaire, les quatre catalogues n'y découvrent rien** —
   `server._candidats_visibles() == []`, plus un contrôle par MOTIF (le nom du candidat fuit les 5
   motifs ; `nom_retenu` en retrouve exactement 1).
3. **`save_calibration` déplace** — l'original n'existe plus, la destination est dans `data_dir`,
   et un fichier au nom **exact** que le candidat allait réclamer est planté d'avance : il ressort
   octet pour octet intact, le modèle atterrissant à côté (`…-2.joblib`).
4. **`discard_calibration` supprime et efface le verdict** — fichier disparu,
   `snapshot()["calibration"] is None`, `data/` inchangé.
5. **Fermer sans trancher ne laisse aucun orphelin** — le moteur est arrêté avec un candidat en
   attente ; après le `join`, le dossier entier a disparu.
6. **Les deux commandes refusent proprement** — sur le moteur froid de `_smoke_calibration_refus`
   (avec le motif dans la phrase), et une seconde fois après chaque geste réussi.
7. **Les deux sens du vol de marqueurs** — `_smoke_vol_marqueurs`, détaillé plus haut.

Le test 3 est le seul qui écrit un modèle, et il le fait dans un `DATA_DIR` **détourné**
(`EngineServer(data_dir=…)`).

## Ce que j'ai dû arbitrer

1. **`data_dir` est devenu un paramètre du moteur.** Le brief demande à la fois « `save_calibration`
   dépose dans `DATA_DIR` » et « aucun test n'écrit dans le vrai `data/` » : sans point d'injection,
   les deux sont incompatibles. `EngineServer(data_dir=…)` est le jumeau exact du `dossier=` que les
   calibrations exposaient déjà pour la même raison.

2. **⚠️ ÉCART AU BRIEF — le dossier temporaire est créé à la PREMIÈRE calibration, pas à la
   construction du moteur.** Le brief écrit « à sa construction ». Sa seule différence observable
   est le déchet : `run()` balaie dans son `finally`, mais tous les `EngineServer` construits **sans
   être lancés** — une dizaine par passage de `--smoke`, plus tout `--mode` refusé — laisseraient un
   dossier vide de plus dans `%TEMP%` à chaque fois, que rien n'efface jamais sous Windows. Ce que
   le brief veut est tenu : un dossier par moteur, créé par le moteur, jamais partagé. Vérifié :
   0 reste après la batterie complète, et une assertion l'exige (« un moteur qui n'a jamais calibré
   n'a créé AUCUN dossier temporaire »).

3. **Le préfixe est posé par `chemins_libres`, pas après coup.** Vérifier la liberté d'un nom puis
   en écrire un autre ne vérifie rien. Le paramètre `prefixe=""` par défaut préserve l'autre
   appelant, `research/p300_calibrate.py`, qui écrit un modèle DÉFINITIF directement dans `data/` et
   doit garder le nom que `p300_models` cherche.

4. **Ce préfixe reste une discipline de la sous-classe — alors j'ai ajouté un témoin.** Rien ne peut
   forcer une future calibration (ErrP, c-VEP : tâches 7 et 8) à passer `prefixe=`. Le moteur
   VÉRIFIE donc, à l'adoption, que les quatre catalogues ne découvrent rien dans son dossier
   candidat, et le DIT fort en nommant le fichier et le correctif — plutôt que de jeter un modèle
   qui vaut plusieurs minutes de séance. La mutation ci-dessus montre le message.

5. **`_candidat_de` (adoption unique) et le lâcher de la séance précédente.** Sans le premier, un
   candidat enregistré (donc remis à `None`) serait ré-adopté au tour suivant avec des chemins qui
   n'existent plus. Le second est un défaut que j'ai créé puis fermé dans le même chantier : garder
   une référence vers la calibration terminée retenait ses époques (`_enregistre`, plusieurs minutes
   de signal) et le moteur entier, parce que `_terminer` n'appelle pas `cancel()`. Commit `2ee8911`,
   avec son assertion et sa mutation.

6. **Démarrer une calibration jette le candidat en attente.** Le brief ne le demandait pas. Sans ça,
   « Enregistrer » resterait actif sur un résultat qui n'est plus celui qu'on regarde, et personne
   ne saurait lequel des deux part dans `data/`.

## Réponse à l'arbitrage n°2 du brief : l'ordre fenêtre/moteur

**Je n'y ai pas touché, et mon travail ne le rend ni plus facile ni plus dur — mais il ajoute une
contrainte d'ordre voisine, que la tâche 6 doit connaître.**

Le problème d'origine (la fenêtre attend 15 s depuis SON lancement, le moteur compte sa chauffe
depuis `start_calibration`) est intact : je n'ai ni ajouté ni retiré de poignée de main.

Ce qui change pour la tâche 6 : **la console doit désormais s'assurer que le mode P300 est ARRÊTÉ
avant de soumettre `start_calibration`** — sinon la commande est refusée, avec une phrase prête à
afficher. Deux façons de le traiter, et c'est un choix de console : afficher le refus tel quel
(honnête, mais l'étudiant doit faire deux gestes), ou arrêter le mode elle-même puis relancer la
calibration. Le refus, lui, ne bouge pas : c'est le moteur qui le porte.

## Réserves (le WITH_CONCERNS)

- 🔴 **Aucune calibration n'atteint plus `data/` tant que la tâche 6 n'a pas câblé les boutons.**
  `calib_page.py` n'a aujourd'hui que « Commencer » et « Abandonner » ; il lui faut « Enregistrer »
  et « Jeter », lus sur `snapshot()["calibration"]["candidat"]` (non-`None` = il reste une décision
  à prendre ; `resultat` reste renseigné après l'enregistrement, pour que le verdict ne disparaisse
  pas de l'écran). En attendant, une calibration lancée depuis la console produit un candidat que le
  `finally` de `run()` détruira à la fermeture. **C'est le découpage voulu du chantier, pas un
  oubli — mais il ne faut pas brancher un casque entre les deux tâches.**

- 🔴 **`EngineServer.close()` existe mais personne ne l'appelle en dehors de `run()`.** C'est
  suffisant tant que la console lance la boucle dans un fil et attend sa fin ; si elle devait tuer
  le fil sans laisser `run()` finir, le dossier survivrait au processus. La console (tâche 6)
  devrait appeler `close()` dans son `closeEvent` — c'est idempotent, et prévu pour ça.

- ⚠️ **`_candidats_visibles` charge chaque fichier qui correspond à un motif.** Coût nul quand la
  réponse est vide (le cas normal), une fois par calibration. Mais si une calibration future oublie
  le préfixe, ce contrôle fera un `joblib.load` du modèle qu'on vient d'écrire, dans la boucle du
  moteur. Quelques dizaines de millisecondes, à un instant où le moteur bloque déjà pour
  l'entraînement — mesuré nulle part, jugé négligeable.

- ⚠️ **« Jeter » est éprouvé sur un candidat REFABRIQUÉ.** `_smoke_calibration` joue **une** vraie
  séance MI ; le candidat de « Jeter » et celui de « fermeture sans trancher » sont des copies du
  modèle réellement produit, replacées dans le dossier candidat. Ce qui est éprouvé est la
  suppression et le nettoyage, pas une seconde production. Une seconde séance complète coûterait
  ~30 s de smoke pour éprouver quatre lignes de `os.remove`.

- ⚠️ **`chemin_libre` décline en `-2`, `-3`… ; `chemins_libres` (les calibrations) avance d'une
  seconde.** Deux règles anti-collision différentes, pour deux étapes différentes, et je n'ai pas
  unifié : la seconde doit préserver le FORMAT de l'horodatage, la première ne le peut pas (le nom
  lui arrive tout fait). Le test exige que le nom décliné reste découvrable par son motif — c'est
  la seule propriété qui compte, et un suffixe posé après l'extension la casserait.

- ⚠️ **`research/p300_calibrate.py` écrit toujours directement dans `data/`**, sans candidat ni
  décision. C'est le SECOND chemin vers un modèle P300 que le rapport de la tâche 4 signalait déjà ;
  ma tâche ne le referme pas, et il contourne entièrement la garde posée ici. À retirer par une
  tâche ultérieure.

- ⚠️ **`docs/SPEC.md` et `docs/markers.md` ne connaissent pas `save_calibration` /
  `discard_calibration`.** `COMMANDS` est un contrat semi-public (l'adaptateur LSL entrant s'en
  servira) et il a deux entrées de plus. Hors périmètre (tâche 11), mais c'est un contrat qui a bougé.

- ⚠️ **Rien de tout ceci n'a vu un casque.** Le cycle complet est joué de bout en bout par la boucle
  réelle du moteur sur board synthétique, mais la seule chose qu'une séance dira et que ces tests ne
  peuvent pas dire : si l'étudiant comprend, devant l'écran, qu'un chiffre affiché n'est pas encore
  un modèle enregistré.

## Les tests demandés

```
python src/core/server.py --smoke          -> 18 VERDICT : OK, exit 0
      dont [smoke-calib] (cycle du candidat complet), [smoke-calib-refus], [smoke-vol-marqueurs]
      et [smoke-frontiere] VERDICT : OK
python src/core/modes/mi_calib.py          -> [mi-calib]     VERDICT : OK
python src/core/modes/p300_calib.py        -> [p300-calib]   VERDICT : OK
python src/core/modes/marker_calib.py      -> [marker-calib] VERDICT : OK
python src/core/modes/calibration.py       -> [calibration]  VERDICT : OK
python src/core/mi_models.py               -> OK
python src/core/p300_models.py             -> OK
python src/console/app.py --smoke          -> [console-smoke] VERDICT : OK
```

En plus (CLAUDE.md, et les modules touchés de près) : `src/core/config.py`, `src/core/errp_models.py`,
`src/core/cvep_models.py`, `src/core/markers.py`, `src/core/modes/p300.py`, `src/core/modes/mi.py`,
`src/core/acquisition.py --synthetic`, `src/research/app.py --smoke`, `src/stimulus/p300.py --smoke`
— tous OK, exit 0.
