# Tâche 3 — le contrôle alpha, de bout en bout

**Statut : livré.** Trois commits sur `main` : `c4f3973`, `aacc13f`, `4616d48`.

| fichier | ce qui y a été fait |
|---|---|
| `src/core/modes/alpha.py` | *(créé)* `ControleAlpha`, ses constantes, son `SPEC`, son autotest (28 assertions) |
| `src/console/mesure_page.py` | *(créé)* `MesurePage` : briefing, déroulé + TOP sonore, verdict, barrière, réglage appliqué |
| `src/console/grid.py` | `MesureTile` + une seconde rangée de tuiles dans `ModeGrid` |
| `src/console/app.py` | câblage (`mesures`, `mesure_pages`, `show_mesure`, `demander_mesure`, `arreter_mesure`, `_avis_mesure`), `fake_state()["mesure"]`, ~40 assertions de smoke |
| `src/console/beeps.py` | `TOP_ETAPE` — le top NEUTRE d'une mesure, distinct des trois latéralisés du MI |
| `src/console/params_form.py` | « aucun réglage à changer ici » : ce formulaire sert aussi les mesures |
| `src/core/modes/registry.py` | `MESURES = (alpha.SPEC,)` |
| `src/core/modes/ssvep.py` | l'aide de `alpha_hz` ne renvoie plus à un script supprimé |
| `archive/alpha_check.py` | *(déménagé)* ex-`src/research/alpha_check.py`, avec un `--smoke` |
| `archive/README.md`, `src/research/__init__.py` | le retrait, écrit |

---

## Le protocole, repris tel quel

Prép. **3 s** → **8 s yeux ouverts** → prép. **3 s** → **8 s yeux fermés**, bande **8-12 Hz**,
pic cherché dans **6-14 Hz**, repère **ratio > 1,5**, moyenne sur `OCCIPITAL`. Welch (Hann, 50 %
de recouvrement, segments de 2 s) recopié **ligne pour ligne** de l'écran d'origine plutôt que
remplacé par `scipy.signal.welch` : les deux ne normalisent pas pareil, et un ratio ne survit à
une normalisation que si ses deux termes passent par la même.

Zéro réglage exposé (`SPEC.params = ()`), et c'est le point : les durées font corps avec le
repère chiffré. Un champ « durée » laisserait l'invalider en croyant gagner du temps, et le
verdict continuerait de s'afficher avec le même aplomb.

⚠️ **Une fausseté trouvée dans l'original, corrigée et documentée** : `alpha_check.py` imprimait
« moyenne PO7/Oz/PO8 » alors qu'il moyennait **quatre** voies (il lisait `acq.occ_rows`, donc
`OCCIPITAL = [4,5,6,7]`, Pz compris). La phrase avait cessé d'être vraie le jour où Pz a rejoint
`OCCIPITAL`, sans que rien ne le signale. Le moteur **calcule** maintenant cette liste
(`VOIES = [CH_NAMES[i] for i in OCCIPITAL]`) et la publie dans son résultat ; la page l'affiche
telle quelle. Le cahier des charges disait « PO7/Oz/PO8 (`OCCIPITAL`) » — les deux ne coïncident
plus, et j'ai suivi `OCCIPITAL`, qui est ce que l'écran mesurait réellement.

## Les quatre points du cahier des charges

**1. Le sujet a les yeux fermés.** `MesurePage._maybe_beep` joue `TOP_ETAPE` à chaque
**changement** de `classe` — jamais sur un compteur, même leçon que `CalibPage` (ni `essai` ni
`phase` ne bougent d'une étape à l'autre). **`classe` et non `etape`** : `etape` reste vide de
bout en bout sur une mesure (choix explicite de la tâche 2, pour ne pas faire sonner la page de
calibration au hasard) — un `_maybe_beep` recopié de `calib_page.py` serait donc **parfaitement
muet ici, sans lever quoi que ce soit**. Une assertion le dit.

Cinq tops par séance, et le cinquième est le plus important : il n'annonce pas une étape mais la
**fin** de « yeux fermés » (passage en phase `mesure`, étape vide). C'est le seul signal qui dise
de rouvrir les yeux ; sans lui la personne décide toute seule, pendant la fenêtre qu'on vient
d'enregistrer. La chauffe, elle, ne sonne pas — un top pendant la stabilisation ferait fermer les
yeux 15 s trop tôt. Les trois cas sont testés.

Machine sans son : la page le **dit**, et plus fermement que `calib_page` (« la seconde moitié de
cette mesure se fait LES YEUX FERMÉS : sans top, tu ne sauras pas quand rouvrir »). Éprouvé contre
une console factice sans audio — sinon l'avertissement ne serait jamais exercé sur un poste qui a
du son.

**2. C'est une barrière, et la page le dit.** `MesureSpec.barriere` (contrat) et
`barriere_franchie` (résultat) sont deux choses distinctes ; la page les croise. Échec →
`🛑 BARRIÈRE NON FRANCHIE — ARRÊTE LA SÉANCE ICI`, en rouge, **au-dessus** du verdict détaillé :
un chiffre lu d'abord invite à négocier avec. Le verdict lui-même nomme les trois gestes dans
l'ordre (électrodes occipitales → mastoïdes → saline) et distingue deux causes : « ça ne monte
pas » (contact) et « ça monte mais le pic est hors 8-12,5 Hz » (artefact, posture). La tuile de la
grille porte le même verdict, **sans le retraduire**.

⚠️ Une mesure **abandonnée** n'affiche ni barrière ni chiffre : « barrière non franchie »
accuserait le montage alors que rien n'a été mesuré.

**3. La boucle fermée.** Le résultat porte `reglage_propose = {mode, mode_label, cle, label,
valeur, unite}`, **rempli par le moteur** en lisant le contrat du SSVEP — la console n'écrit ni
« ssvep » ni « alpha_hz ». Un clic envoie `set_params`, et le refus du moteur s'affiche (il en
existe un vrai : `set_params` n'atteint qu'un mode démarré, et le SSVEP n'a aucune raison de
tourner pendant un contrôle alpha). **Rien n'est proposé quand la barrière échoue** : sur un
signal sans alpha, le « pic » est le plus grand bin d'un spectre de bruit. Cette décision vit dans
le moteur, pas dans l'écran.

**4. La console est un client.** Ratio, pic, verdict, phrase d'honnêteté, et jusqu'à la liste des
voies moyennées : tout vient de `snapshot()["mesure"]["resultat"]`. La page a une table
`DETAILS` indexée par **clé de résultat** (jamais par identifiant de mesure), comme `CalibPage` :
elle rendra la mesure SSVEP de la tâche 9 sans une ligne de plus. Aucune écriture disque.

## Deux gardes que l'écran d'origine n'avait pas

Les deux ont été trouvées en écrivant les tests, pas devinées.

1. **Le détrend, prouvé par mutation.** L'Unicorn sort ~10⁵ µV de DC ; sans détrend il fuit à
   travers la fenêtre de Hann jusque dans la bande alpha et **écrase l'EEG de plusieurs ordres de
   grandeur**, donc toute séance échoue à la barrière, casque parfait compris. Le code l'avait ;
   rien ne le tenait. Il est maintenant tenu :

   ```
   ÉCHEC un offset DC de 10⁵ µV ne change pas le verdict (2.26 contre 4.44 sans lui)
   [alpha] VERDICT : PROBLÈME          ← la ligne du détrend retirée
   ```
   ```
   [alpha] VERDICT : OK                ← remise
   ```
   La mutation ne fait rougir **que** cette assertion.

2. **La liaison morte.** Quatre voies plates donnent ~10⁻²⁷ de puissance des **deux** côtés : leur
   rapport est du bruit d'arrondi, il vaut 0,3 ou 4,1 selon les derniers bits, donc il **franchit
   la barrière une fois sur deux**. « Le montage est bon » affiché sur un câble débranché — le
   défaut exact qui a coûté 3,4 min de vide le 2026-07-20. Un `p_ouvert <= 0.0` ne l'attrape pas
   (mesuré : 3,3 × 10⁻²⁷ > 0). Le refus utilise `signal_verdict` / `SIGNAL_DEAD_SIGMA`, **la règle
   que le moteur applique déjà à ses huit voies** — pas un seuil inventé ici.

   Et un troisième garde, plus banal : `remove_environmental_noise` **refuse un `fs` flottant**
   (`wrong type for sampling rate`). L'original recevait `acq.fs`, un entier ; `_mesurer` reçoit
   `float(engine.acq.fs)`. Sans `int(round(fs))`, le contrôle alpha aurait levé au moment du
   calcul, après 37 s de casque. Rencontré pour de vrai en écrivant le smoke de l'archive.

## Les écarts au plan, et pourquoi

1. **`("set_params", {"id": "ssvep", "alpha_hz": 10.5})` n'est pas le contrat du moteur.**
   L'extrait de l'étape 4 attend ces kwargs ; `submit("set_params", …)` prend `id=` **et**
   `params={…}` (cf. `server.submit`, qui fusionne sur les réglages courants puis valide). Écrit
   tel quel, le test aurait vérifié une commande que le moteur rejette. L'assertion livrée est
   `("set_params", {"id": "ssvep", "params": {"alpha_hz": 10.5}})`, et la valeur attendue est
   **lue dans le résultat** (`reussi["pic_hz"]`), pas écrite en dur. Même nature d'écart que le
   `_drain_commands` de la tâche 2 : l'intention est tenue, la mécanique corrigée.

2. **Le mode et la clé viennent du RÉSULTAT, pas du code de la console.** Écrire
   `commande("set_params", id="ssvep", params={"alpha_hz": …})` dans `mesure_page.py` aurait été
   un catalogue recopié, que `CLAUDE.md` interdit. `alpha.py` importe `modes/ssvep.py` pour lire
   `label`/`unit` du `Param` (aucun cycle : `ssvep.py` n'importe ni `mesure` ni `registry`). Une
   assertion vérifie que la plage de recherche du pic (6-14 Hz) tient dans les bornes du réglage
   (6-14 Hz), donc que **tout pic mesurable est applicable** — le bouton ne peut pas proposer une
   valeur que le moteur refusera.

3. **« Commencer » passe par le CONTRÔLE DE LIAISON**, comme une calibration. Le plan ne le
   demandait pas ; c'est le patron établi de cette console, et ici il a une raison propre : les
   quatre voies plates ci-dessus se refusent en 2 s au lieu de 37. `ContactPage.viser` accepte un
   `MesureSpec` sérialisé sans modification (pas de `key_channels` → aucun surlignage, refus sur
   les huit voies, ce qui est correct). `_montrer_contact` prend maintenant un **spec** au lieu
   d'un identifiant : les deux catalogues sont distincts et un identifiant seul ne dit pas duquel
   il vient.

4. **`archive/alpha_check.py` est fait ICI, pas à la tâche 10** — c'est le point à trancher, voir
   la réserve 1.

## Ce qui reste DEHORS

- **Aucun cerveau.** Ce contrôle n'a été exercé que sur du bruit blanc et des sinusoïdes posées à
  la main. Le repère 1,5 vient toujours d'**une** personne, sur ce casque.
- **La mesure SSVEP** (tâche 9). `MesurePage` est écrite générique pour elle (table `DETAILS` par
  clé, barrière optionnelle, proposition de réglage optionnelle), mais **rien ne le prouve** tant
  qu'il n'y a qu'une mesure : `registry.MESURES` en compte une, et une table à une entrée ne
  démontre pas qu'elle en supportera deux.
- **La documentation** (tâche 11). `docs/recette.md` (test 2.1), `docs/SPEC.md` (l. 100 et 274) et
  `README.md` (l. 151 et 443) citent encore `python src/research/alpha_check.py`, qui n'existe
  plus. **La seule occurrence qui était affichée à un utilisateur** — l'aide de `alpha_hz` dans le
  contrat du SSVEP, montrée dans le formulaire de la console — est corrigée ici, parce qu'un
  chemin mort dans une chaîne d'interface n'est pas de la documentation en retard.
- **Le journal.** Une mesure n'écrit rien, donc un verdict disparaît quand on relance. La tâche 7
  (`start_enregistrement`, dossier `seances/`) est le bon endroit ; ça n'a pas été anticipé ici.

## Réserves

1. 🔴 **J'ai fait un morceau de la tâche 10, et il faut le savoir.** Mon cahier des charges dit en
   gras « ta tâche fait passer ce compteur de six fichiers à cinq », alors que le plan liste
   `archive/alpha_check.py` dans les *fichiers créés* de la **tâche 10** et n'inscrit aucune
   suppression à la tâche 3. J'ai tranché pour le déménagement, sur trois arguments : le compteur
   demandé ne pouvait bouger autrement ; l'ordre « non négociable » de la tâche 10 ne concerne que
   `research/ui.py` (huit fichiers de `archive/` l'importent — `alpha_check.py` n'importe rien de
   `research/`, vérifié) ; et laisser `python src/research/alpha_check.py` lançable était
   exactement la commande que ce chantier existe pour supprimer. **Conséquence pour la tâche 10 :
   son étape 1 bis n'a plus que deux fichiers à archiver (`live_ssvep`, `ssvep_guided`), et
   `archive/alpha_check.py` existe déjà.** Si ce n'était pas voulu, le commit `aacc13f` s'annule
   seul (`git revert`) sans toucher au reste.

2. **`archive/alpha_check.py --smoke` n'ouvre aucun board, pas même le synthétique.** Le protocole
   EST 22 s de `time.sleep` ; un smoke qui dort 22 s est un smoke qu'on désactive. Il n'exerce donc
   que l'arithmétique (`_clean`, `_welch`, `_band_power`, le pic) — c'est la seule chose pour
   laquelle ce fichier est gardé, mais c'est **moins** que les dix autres `--smoke` de l'archive,
   qui montent leur écran. `README.md` de l'archive le dit.

3. **Le seuil de voie morte est appliqué sur un σ LARGE BANDE**, alors que `signal_verdict` a été
   calibré sur le σ **filtré 5-40 Hz** du moteur. Un σ large bande est plus grand (il porte la
   dérive), donc la garde est **conservatrice** : elle refusera moins souvent qu'elle ne le
   devrait, jamais plus. Elle vise le cas franc (voies à 10⁻¹⁴ µV), pas une frontière fine.

4. **La deuxième cause d'échec — « ça monte, mais ce n'est pas de l'alpha » — n'a jamais été vue
   sur un vrai signal.** Son test la fabrique avec une raie à 7,5 Hz, à un bin de la bande, dont le
   lobe de Hann fait monter le ratio à 9,1 pendant que le pic reste hors 8-12,5 Hz. Que ce soit la
   forme qu'un artefact de mouvement prend réellement est une **hypothèse**, écrite dans le
   commentaire du test. Le critère lui-même, lui, vient de l'écran d'origine, où il existait déjà.

5. **`MesureTile` recolore le verdict d'après `barriere_franchie`.** C'est la seule chose que la
   grille déduit du résultat ; le TEXTE, lui, est copié tel quel. Recomposer une phrase à partir du
   booléen ferait dire à la grille autre chose qu'à la page sur les mêmes données — évité, mais la
   couleur reste une interprétation locale.

6. **Diff : ~52 Ko** (`alpha.py` ~24 Ko dont l'autotest, `mesure_page.py` ~17 Ko, `grid.py` +6 Ko,
   `app.py` +13 Ko de smoke, moins `research/alpha_check.py` déménagé). Au-dessus des ~40 Ko visés,
   comme la tâche 2.

---

## Tests

```
python src/core/modes/alpha.py            → [alpha] VERDICT : OK          (28 assertions)
python src/core/modes/mesure.py           → [mesure] VERDICT : OK
python src/core/modes/ssvep.py            → [ssvep] VERDICT : OK
python src/core/modes/registry.py         → [registry] VERDICT : OK
python src/core/modes/calibration.py      → OK
python src/core/modes/contract.py         → OK
python src/core/modes/mi_calib.py         → OK
python src/core/modes/marker_calib.py     → OK
python src/core/modes/{mi,p300,errp,cvep}.py → OK
python src/console/app.py --smoke         → [console-smoke] VERDICT : OK  (~40 assertions ajoutées)
python src/core/server.py --smoke         → tous les verdicts OK, SAUF [smoke-frontiere]
les 11 --smoke de archive/                → exit 0 (dont le nouveau alpha_check)
```

### `[smoke-frontiere]` : de six fichiers à cinq

```
[smoke-frontiere] ÉCHEC : research/live_ssvep.py:31 importe core.acquisition
[smoke-frontiere] ÉCHEC : research/live_ssvep.py:90 importe pygame
[smoke-frontiere] ÉCHEC : research/live_ssvep.py:180 importe pygame
[smoke-frontiere] ÉCHEC : research/live_ssvep.py:275 importe pygame
[smoke-frontiere] ÉCHEC : research/ssvep_analyze.py:30 importe core.acquisition
[smoke-frontiere] ÉCHEC : research/ssvep_guided.py:45 importe core.acquisition
[smoke-frontiere] ÉCHEC : research/ssvep_guided.py:129 importe pygame
[smoke-frontiere] ÉCHEC : research/ssvep_stimulus.py:107 importe pygame
[smoke-frontiere] ÉCHEC : research/ui.py:52 importe pygame
[smoke-frontiere] ÉCHEC : research/ui.py:88 importe core.acquisition
[smoke-frontiere] 58 fichiers scannés, 10 violation(s) de frontière
[smoke-frontiere] VERDICT : PROBLÈME
```

**12 violations sur six fichiers → 10 sur cinq.** `alpha_check.py` a disparu. **Aucune violation
hors de `research/`** : `core/modes/alpha.py` et `console/mesure_page.py` passent le scan.

### `data/` — intact

`core.config.empreinte_dossier(DATA_DIR)`, avant et après toute la batterie (autotests, deux
smokes, les onze `--smoke` de l'archive) :

```
avant : 43 fichiers, sha256 0927075203de93f4e56a438b1a16b7f4c977c3476808744a2c5d7bdcdc36037a
après : 43 fichiers, sha256 0927075203de93f4e56a438b1a16b7f4c977c3476808744a2c5d7bdcdc36037a
```
