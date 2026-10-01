# Plan — Retour en direct : la cible décodée entourée (2026-10-01)

Demandé au casque le 2026-10-01 (QA 2.3) : « quand on teste, je préférerais un système où on regarde
une cible et le logiciel analyse et entoure la cible qu'il pense qu'on regarde, comme ça on a le
retour en direct ». Choix de l'utilisateur, par question fermée : **les deux** — un test guidé AVEC
retour, et un mode libre sans score —, pour **c-VEP, SSVEP et P300**. « Fais-le maintenant. »

## Décisions (coordinateur)

1. **Le canal moteur → fenêtre est le flux DÉCODÉ PUBLIC du mode** (`decoded_cvep`,
   `decoded_ssvep`, `decoded_p300`, voie 0 = `target_index`, −1 = rien). La fenêtre l'écoute
   EXACTEMENT comme l'application d'un étudiant : par son nom (`core.lsl_io.stream_name`). Aucun
   flux nouveau, aucun contrat nouveau pour le mode libre ; et notre propre fenêtre devient un
   client du contrat public — elle l'éprouve à chaque séance.
2. **Pendant un TEST, le moteur publie les décisions du test sur ce même flux**, une par essai
   (c-VEP : un bloc ; SSVEP : un essai ; P300 : une manche), avec le publieur du mode, ses voies et
   le `source_id` du moteur. « Le test décide comme le produit » devient « et publie comme lui ».
   Conséquence assumée, à DIRE dans la doc : pendant un test, une application branchée sur
   `decoded_<mode>` reçoit les décisions du test.
3. **Un test et son mode ne publient jamais en même temps** (deux publieurs, même nom) : le moteur
   refuse un test pendant que son mode tourne, ET l'inverse, à la soumission et dans la boucle —
   la règle existe déjà pour les modes à marqueurs (P300, ErrP, c-VEP), elle s'étend au SSVEP.
4. **Fenêtres** — deux options nouvelles, déclarées dans `stimulus/registry.py` :
   - `--retour` : la fenêtre résout le flux décodé de son mode en tâche de fond (jamais de blocage
     du rendu), le lit sans attendre APRÈS chaque `flip`, et entoure la cible décodée d'un anneau
     d'une couleur à part. En test guidé, la fenêtre connaît la cible désignée : l'anneau est VERT
     si la décision est juste, ROUGE sinon, affiché jusqu'à l'essai suivant. En libre : l'anneau
     suit la dernière décision, disparaît sur −1.
   - `--libre` : aucune consigne, aucune vérité-terrain, aucun journal ; les cibles affichées, et
     c'est tout (le c-VEP et le P300 désignent des cibles en décodage aujourd'hui — vérifier).
   - ⚠️ L'anneau ne touche JAMAIS les pixels des cibles : les tests de phase c-VEP et de cible
     SSVEP lisent les pixels, et la panne caractéristique du c-VEP est une phase fausse de quelques
     frames. Le rendu de l'anneau et la lecture du flux viennent APRÈS le `flip` et le marqueur.
   - `registry.MESURE_OPTIONS` gagne `--retour` pour les trois ; nouveau
     `registry.option_libre(stimulus_id)` → `("--libre", "--retour")` (ou ce que la fenêtre exige),
     `()` si la fenêtre ne sait pas.
5. **Console** : le bloc « N. Tester » des pages c-VEP, SSVEP et P300 gagne un second bouton,
   **« Essayer librement »** — dans la séquence Tester, pas à côté. Geste : le moteur valide et
   démarre le mode (`start_mode`, réglages retenus), la console attend de le VOIR tourner dans
   `snapshot()`, puis lance la fenêtre avec `option_libre` ; à la fermeture de la fenêtre, la
   console ARRÊTE le mode (elle l'a démarré pour l'essai) et le dit. Un mode sans modèle est
   refusé par le moteur, refus affiché. Le bouton n'existe que si `option_libre` rend quelque chose.

## Tâches

- **R1 — Moteur** (`core/modes/cvep_test.py`, `p300_test.py`, `ssvep_mesure.py`,
  `mesure_marqueurs.py` si le geste est commun, `server.py` pour le refus test ↔ mode) : décisions
  des tests publiées (décision 2), refus croisé (décision 3), gardes. Docs du contrat (README/SPEC)
  : le coordinateur.
- **R2 — Fenêtres** (`stimulus/cvep.py`, `ssvep.py`, `p300.py`, `registry.py`) : `--retour`,
  `--libre`, registre (décision 4), gardes dans chaque `--smoke`.
- **R3 — Console** (après R2) : « Essayer librement » (décision 5), `--retour` passé aux tests.
- **R4 — Doc** (coordinateur) : CLAUDE.md, README (contrat : décisions de test sur le flux décodé),
  qa.md (points nouveaux), recette.

Règles communes : celles du plan `2026-09-30-filtres-reglables.md` (textes par `tr()` côté console
et moteur ; les fenêtres pygame ne sont pas encore migrées — pas de texte nouveau à l'écran si on
peut l'éviter ; mutation rouge puis verte ; `chk` comptés ; `git add` de ses fichiers ; jamais
les deux smokes en parallèle d'un autre agent).

## Passe de correction (après la revue, 2026-10-01)

Sept relecteurs, 0 critique. Constats détaillés : `.superpowers/sdd/2026-10-01-retour-en-direct/progress.md`.

**⚠️ La Décision 5 était FAUSSE.** Le plancher du SSVEP se mesure AVEC les cibles qui clignotent,
sans en fixer aucune — c'est écrit dans `stimulus/ssvep.py` (`_guide`) : « mêmes conditions visuelles
que les essais, sinon le moteur soustrait un fond qui n'est pas celui du test ». Ouvrir la fenêtre
APRÈS le repos mesurait le plancher sans clignotement, puis décodait avec. **Nouvelle décision :**
la fenêtre de l'essai libre s'ouvre dès que le mode démarre ; elle lit le flux PUBLIC `status`
(`phase`) et affiche une croix + « ne fixe aucune cible » tant que la phase est `warmup` ou `rest`.

- **K1 — Moteur** : chemin d'exception de la mesure testé et refus porté par la ressource (flux
  encore vivant) ; oubli de `_ligne_muette` refusé à la construction ; lignes −1 poussées dans le
  VRAI publieur en autotest ; c-VEP publie seulement ce que le verdict note ; fermeture vérifiée sur
  le réseau ; `cancel()` gardé ; échec de publication exposé dans l'état de la mesure ; SSVEP en
  direct éprouvé avec un `z_min` et une bande non défaut, un repos non figé et un essai à artefact ;
  calage raté = abandon immédiat ; docstrings.
- **K2 — Fenêtres** : seulement les flux de CETTE machine (nom d'hôte) ; en continu, −1 n'efface
  plus l'anneau (il expire) ; l'anneau s'efface AVANT la fenêtre que la décision suivante lit (c-VEP :
  au bord d'un cycle de settle, ≥ 3 s avant le `cue` ; P300 : avant le premier flash, pas sur lui) ;
  couleur « juste » distincte de toute consigne (le c-VEP cercle en vert, le SSVEP en bleu) ;
  dernière manche P300 : l'écran attend sa décision ; nom du flux résolu AVANT le rendu ; croix de
  repos en libre (flux `status`) ; mineurs des revues C, D, E.
- **K3 — Console** (après K2) : l'essai libre ouvre la fenêtre dès que le mode existe ; contrôle de
  liaison ; refus au clic pendant une mesure ou un entraînement, avec un flux de marqueurs non
  défaut, et sur une autre page pendant un essai ; surveillance après l'ouverture (réglages changés,
  publication coupée) ; fin en erreur dite comme une erreur ; mineurs des revues F1, F2 ; faux
  moteur conforme au vrai (`set_params` rend `params`/`differe`).
