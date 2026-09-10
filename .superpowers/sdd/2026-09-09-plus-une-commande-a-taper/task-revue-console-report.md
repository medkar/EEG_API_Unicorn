# Revue de branche — les trois constats de la console

Chantier « plus une seule commande à taper ». Trois constats critiques, déjà diagnostiqués,
corrigés le 2026-09-10. Quatre commits, tous prouvés par mutation.

| commit | constat |
|---|---|
| `d643352` | 1 — la MESURE pariait sur `accepted` |
| `5bfa6c1` | 2 — la page de flux effaçait ses propres diagnostics en 100 ms |
| `7b27015` | 2 bis — correctif du correctif : une interruption doit passer devant |
| `778b1d0` | 3 — casque absent : le fil du moteur meurt en silence, et la recette promettait l'inverse |

## 1 — La mesure attend de VOIR sa séance (`d643352`)

`Console._demarrer_mesure` lançait la fenêtre de stimulus sur l'accusé de `start_mesure`. Or
`submit` ne promet qu'une **mise en file** : `_start_mesure` peut sortir sans rien créer par trois
portes silencieuses (mesure déjà en cours, calibration en cours, exception avalée par
`_drain_commands`). La fenêtre plein écran jouait alors **3,5 min de fixation guidée dans le vide**
pendant que la page restait sur « Avant de commencer ».

Le jumeau du correctif posé la veille pour la calibration existe maintenant, **et le corps est
écrit une seule fois** :

- `_attente_depart(mode_id, cle, quoi, lancer, avis)` porte les quatre seules choses qui séparent
  une calibration d'une mesure : où la séance apparaît dans `snapshot()` (`"calibration"` /
  `"mesure"`), comment sa fenêtre se lance, où le renoncement s'affiche, comment on la nomme.
- `_lancer_quand_partie` joue **un tour de la course pour les deux** (`_un_tour_d_attente`).
- `_lancer_fenetre_calibration` / `_lancer_fenetre_mesure` portent l'annulation quand la fenêtre
  refuse de s'ouvrir.
- **Trouvé en passant, corrigé** : `arreter_calibration` et `arreter_mesure` ne lâchaient pas le
  lancement en attente. Abandonner puis voir la fenêtre s'ouvrir toute seule au tour suivant est le
  contraire du clic. Une ligne chacun.

Le test épinglait le défaut (clic, puis assertion que la fenêtre est déjà partie, **sans
`apply_state` intermédiaire**). Réécrit comme le jumeau de la calibration : la mesure doit d'abord
APPARAÎTRE dans l'état. Deux cas que la mesure n'avait pas du tout ont été ajoutés — le moteur qui
ne démarre jamais la séance (renoncement à 5 s, **dit**), et la fenêtre qui refuse de s'ouvrir
(annulation au tour suivant, jamais avant : `submit` ne fait que mettre en file).

**Mutation** : relancer sur l'accusé (`self._lancer_fenetre_mesure(...)` au lieu de
`self._a_lancer_mesure = …`).

```
ÉCHEC après le clic, `start_mesure` est SOUMISE et la fenêtre attend
ÉCHEC le moteur n'ayant rien démarré, la fenêtre guidée n'est PAS lancée
ÉCHEC …et au bout de 5 s on RENONCE en le disant
ÉCHEC …sans soumettre `cancel_mesure` à un moteur qui n'a encore rien démarré
ÉCHEC une fenêtre qui refuse de s'ouvrir fait ANNULER la mesure, et le dit sur sa page
[console-smoke] VERDICT : PROBLÈME
```

Retirée → `VERDICT : OK`.

## 2 — La page de flux garde ses diagnostics (`5bfa6c1`, `7b27015`)

Trois messages étaient écrits dans `self.etat` — « aucun flux nommé X », « X n'a pas pu être
ouvert », « X a disparu du réseau ». Les trois laissent `_inlet is None`, donc le tour suivant
(10 Hz) `rafraichir` → `_dire_etat` les écrasait par « N flux visible(s) — choisis-en un ».
**Durée de vie : un tick.** Et aucun de ces chemins ne passe par `Console.commande`, donc le
bandeau ne les rattrapait pas non plus.

Deux champs retenus, `_diagnostic` et `_diagnostic_enr`, écrits par `_dire_probleme` /
`_dire_probleme_enr` — les seuls chemins par lesquels une panne s'écrit désormais. Un diagnostic
tient **jusqu'au geste qui y répond**, jamais jusqu'au prochain tour d'horloge :

- côté flux : « Chercher les flux » l'efface (c'est exactement ce que les messages demandent), et
  un flux réellement OUVERT passe devant (il répond mieux que n'importe quel diagnostic d'hier) ;
- côté enregistrement : le **clic suivant** l'efface. Le BOUTON, lui, continue de suivre le
  moteur — c'est lui qui dit ce que fera le clic suivant, le désynchroniser serait pire.

⚠️ **Correctif du correctif (`7b27015`)** : la rétention masquait un cas qu'elle n'aurait pas dû.
Un enregistrement **INTERROMPU** est une nouvelle du moteur sur un fichier qui existe, elle annonce
une PERTE, et le moteur ne la dit qu'une fois. Elle passe donc devant le diagnostic retenu — un
refus de clic, lui, se rejoue en recliquant.

Le test ne pouvait pas rougir (un `rafraichir()`, assertion aussitôt). **Un second `rafraichir()`**
le rend falsifiable, et les deux chemins qui n'avaient aucun test — nom introuvable, inlet qui
refuse — en ont un.

**Mutations** (deux d'un coup : `_dire_probleme` sans rétention, `_montrer_enregistrement` sans
garde) :

```
ÉCHEC …et il RESTE à l'écran aux tours suivants (2 flux visible(s) — choisis-en un…)
ÉCHEC « aucun flux nommé X » survit lui aussi au rafraîchissement
ÉCHEC …et « X n'a pas pu être ouvert » aussi
ÉCHEC …et ce refus RESTE à l'écran aux tours suivants (terminé — 7 verdict(s)…)
```

Et pour `7b27015`, l'interruption qui cède au diagnostic :

```
ÉCHEC une interruption passe DEVANT le diagnostic retenu (Choisis d'abord le flux…)
```

Retirées → `VERDICT : OK`.

## 3 — La mort du fil se voit, et la recette dit la vérité (`778b1d0`)

`prepare_session()` n'est appelée que dans `acquisition.start()`, donc dans `server.run()`, donc
dans le fil — et **hors de son `try`**. Un `BrainFlowError` le tue avec un traceback sur stderr que
personne ne lit : la console est une fenêtre Qt, et `outils/Console EEG.bat` laisse la console cmd
DERRIÈRE elle.

Ce qui restait à l'écran était parfaitement plausible, et c'est ça le défaut : `snapshot()` figé dit
encore `running`, le bandeau annonce « Unicorn · 250 Hz · 0 mode actif », et les σ restent
« en attente du tampon… » **indéfiniment**.

- `run()` passe `moteur_vivant=thread.is_alive` à la console. Un **prédicat**, pas le fil : la
  console ne possède pas le fil, et lui passer un `Thread` la rendrait intestable sans en démarrer
  un.
- `Console._moteur_mort()` rend le message ; `apply_state` le peint **après** `update_from`.
- `Banner.set_moteur` **écrase** la ligne des σ quand il est non vide. Laisser « en attente du
  tampon… » à côté de « le moteur s'est arrêté » ferait deux phrases contradictoires, dont une qui
  promet que ça va venir.

⚠️ **La console ne repropose PAS le choix de la source** — ça demanderait de reconstruire le moteur,
son fil et la fenêtre entière. `docs/recette.md` test 1.17 le **promettait noir sur blanc** ; la
case décrit maintenant ce que le code fait (message rouge, σ qui cessent de promettre, fermer et
relancer), et nomme le reproposer comme une amélioration possible, pas comme le comportement
actuel.

**Trois mutations, trois rouges** :

| mutation | rouge |
|---|---|
| `run()` ne branche plus le prédicat | `…et run() branche VRAIMENT le prédicat sur le fil du moteur ([])` |
| `set_moteur` n'écrase plus les σ | `…et le bandeau cesse d'annoncer un tampon qui ne viendra jamais ('σ : en attente du tampon…')` |
| `apply_state` ne peint plus le diagnostic | `un fil mort le DIT à l'écran` + le rouge des σ |

La première est une assertion **AST** sur l'appel `Console(...)` de `run()` : sans elle, le
garde-fou pourrait être vert et mort — testé sur un `lambda` posé par le smoke, branché nulle part
en production.

## Vérifications

```
python src/core/server.py  --smoke   -> exit 0, 0 ÉCHEC
python src/console/app.py  --smoke   -> exit 0, 0 ÉCHEC
[smoke-frontiere] 58 fichiers scannés, 0 violation(s) de frontière — VERDICT : OK
```

**Empreinte du vrai `data/`, `core.config.empreinte_dossier`, avant et après le chantier :**

```
AVANT : 43 fichiers, sha256 42120328ed4df50265e14522eb61c5035423bbb52064f33b14d3293dfae8083d
APRÈS : 43 fichiers, sha256 42120328ed4df50265e14522eb61c5035423bbb52064f33b14d3293dfae8083d
                                                              -> IDENTIQUE (dict complet comparé)
seances/ : {} avant, {} après
```

Aucun casque n'a été branché ; aucun moteur ne tournait pendant les tests.

## Réserves

- 🟠 **`CLAUDE.md:191` porte la MÊME fausseté que la recette 1.17 corrigée ici** : « un casque qui
  refuse de s'ouvrir le fait dire **et repropose le choix** ». La deuxième moitié n'est
  implémentée nulle part. Non corrigé : ce fichier n'était pas dans le périmètre, et une consigne
  d'agent ne suffit pas à autoriser sa modification. **À reprendre d'une main humaine.**
  (Les deux autres occurrences, `docs/superpowers/plans/…` et `…/specs/…`, sont des documents de
  planification : ils enregistrent ce qui avait été prévu, il n'y a rien à y corriger.)
- 🟡 **Reproposer la source reste non fait**, et c'est le meilleur comportement. Il faudrait sortir
  le cycle de vie du fil de `run()` : aujourd'hui `EngineServer` est construit une fois, son fil
  démarré une fois, et `Console.__init__` coûte une résolution LSL bornée (~1 s) qu'on paierait à
  chaque nouvelle tentative. C'est un chantier, pas un correctif.
- 🟡 **Le message de mort du fil n'a jamais été vu avec un vrai casque absent.** Il est prouvé sur
  un prédicat injecté ; ce qui n'est PAS prouvé, c'est que `BrainFlowError` tue bien le fil au
  lieu d'être rattrapé quelque part sur le chemin — la lecture du code le dit (`with self.acq:` est
  hors du `try` de `run()`), la séance le confirmera. C'est le point à jouer au test 1.17.
- 🟡 **`Console._moteur_vivant` est un attribut poké par le smoke** pour basculer vivant/mort.
  L'injection par constructeur existe (`moteur_vivant=`) et c'est elle que `run()` utilise ; le
  smoke écrit l'attribut directement pour ne pas reconstruire une `Console` (≈1 s de résolution
  LSL). L'assertion AST est ce qui relie les deux.
- 🟡 **Le diagnostic de flux retenu survit à `quitter()`.** Sans conséquence : `entrer()` appelle
  `chercher()`, qui l'efface. Mais si une septième façon de quitter la page apparaissait sans
  passer par `entrer()` au retour, un diagnostic périmé pourrait se rafficher.
