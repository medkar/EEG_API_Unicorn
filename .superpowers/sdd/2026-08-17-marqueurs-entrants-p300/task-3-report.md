# Tâche 3 — rapport de SUBSTITUTION, écrit par le coordinateur

⚠️ **L'implémenteur (`afb7005b01b4585ff`, sonnet) est mort d'une erreur d'API** (« Connection closed
mid-response ») au moment précis où il allait écrire son rapport. Son dernier message était : « Now
I have everything needed. Let me write the full report. »

**Son travail était intégralement commité** : `a85b105`, 2 fichiers, 200 insertions. C'est la
deuxième fois sur ce projet qu'un agent meurt en fin de course avec son travail sauvé — vérifier
l'état du dépôt AVANT de conclure à l'échec reste la bonne réaction.

Ce rapport remplace le sien. Il ne contient **que ce que j'ai constaté moi-même**, jamais ce que
l'agent aurait pu affirmer : aucune de ses mesures n'a survécu.

## Ce qui a été livré (constaté sur le diff)

- `EngineServer.markers_murs(mode_id, post_s)`, les compteurs `marqueurs_perdus` /
  `marqueurs_futurs`, le cycle de vie du `MarkerInlet` dans `run()`, la purge du tampon.
- Le point d'extension documenté dans `src/core/modes/runtime.py` (6 lignes).
- Deux nouveaux sous-tests, branchés dans la liste `resultats` de `_smoke()` comme la tâche 2 l'a
  refait : `_smoke_marqueurs` et `_smoke_marqueurs_file_coincee`.

## La correction d'ordre que j'avais transmise EST appliquée

Vérifié à la lecture, `server.py:802-810` : le contrôle du **futur** (802-805) précède bien le
`break` de **maturité** (806-809). Et le traitement asymétrique est correct — le futur avance le
curseur (`i += 1` avant `continue`), la non-maturité ne l'avance pas (`break` sec).

## Les tests, relancés par moi, un par un

| Commande | Sortie |
|---|---|
| `python src/core/modes/runtime.py` | `[runtime] VERDICT : OK`, exit 0 |
| `python src/core/markers.py` | `[markers] VERDICT : OK`, exit 0 |
| `python src/core/server.py --smoke` | 14 sous-verdicts `OK`, exit 0 |
| `python src/console/app.py --smoke` | `[console-smoke] VERDICT : OK`, exit 0 |

## La preuve ROUGE, faite par moi faute de rapport

J'avais exigé une preuve rouge-puis-vert sur le test de la file coincée. Sans rapport, je l'ai
refaite : j'ai remis l'**ordre fautif** (maturité avant futur) dans `markers_murs`, lancé le smoke,
puis restauré par `git checkout --`.

Sortie obtenue avec la mutation :

```
ÉCHEC un marqueur très en avance est compté à part : c'est le piège des deux machines (0)
[smoke-marqueurs] VERDICT : PROBLÈME
ÉCHEC un marqueur futur placé DEVANT un marqueur valide ne le bloque pas : le valide sort quand même ([])
ÉCHEC ...et le futur est COMPTÉ au passage, pas seulement sauté en silence (0)
[smoke-marqueurs-file] VERDICT : PROBLÈME
```

**Les deux sous-tests sont donc réellement protecteurs** : ils attrapent la file coincée ET
l'inatteignabilité du compteur. Le `[]` du message est la file bloquée, prise sur le fait.

**Effet de bord instructif** : les 12 autres sous-tests se sont exécutés et affichés malgré ces
deux échecs. C'est la correction du chaînage de `_smoke()` faite à la tâche 2 (collecte puis
`all()`) qui se vérifie ici en conditions réelles, sur un échec qu'on n'avait pas provoqué pour ça.

## Ce qui manque, et qu'il faut assumer

- **Aucune preuve rouge-puis-vert sur le premier sous-test** (`_smoke_marqueurs`, les six attentes
  du brief). J'ai prouvé le second, pas le premier. À signaler à la relecture.
- **Aucun comptage d'assertions avant/après** de la main de l'implémenteur.
- Rien ne dit si l'implémenteur a rencontré d'autres difficultés, ni s'il doutait de quelque chose.

## Tour de correction 1

Six défauts trouvés à la relecture de `a85b105`, deux critiques. Corrigés dans `9fd3499`.
Statut : **tous les six traités, aucun contesté** — les six m'ont paru réels à la mesure.

### CRITIQUE 1 — un mode marqueur démarré après le début de la boucle ne recevait jamais d'inlet

`besoin_marqueurs` et la création de `self.marker_inlet` étaient évalués une seule fois, juste
après `_start()`, avant `while not self._stop:`. Un mode démarré ensuite (`_drain_commands`
traitant `start_mode` pendant que la boucle tourne — le chemin de la console) trouvait
`marker_inlet is None` pour toujours, sans log ni compteur.

**Fix** : extrait dans `_ouvre_marker_inlet()`, appelée à CHAQUE tour de boucle (juste après
`_drain_commands`) au lieu d'une fois avant `while`. Elle ne crée l'inlet que si un mode ACTIF en
a besoin et qu'il n'existe pas déjà — le message d'attente existant est conservé tel quel.

**Rouge** (mutation : l'appel remis avant `while`, une seule fois) :
```
  OK   tant qu'aucun mode actif n'écoute les marqueurs, aucun inlet n'est créé
[server] Écoute (test) démarré — flux EEG_API_Unicorn_decoded_smoke_ecoute
[server] arrêt : 0 échantillons publiés en 5.0 s (0.0 Hz effectif)
  ÉCHEC un mode marqueur démarré APRÈS le début de la boucle obtient quand même un inlet — le CRITIQUE 1 : évalué hors boucle, ce `marker_inlet` resterait None pour toujours
[smoke-marqueurs-inlet] VERDICT : PROBLÈME
```
Seule cette assertion échoue (les 9 autres du même sous-test restent OK) ; `python src/core/server.py --smoke` sort en code 1.

**Vert** (fix restauré) :
```
[server] board=SYNTHETIC_BOARD fs=250 Hz instance=smoke-marqueurs-inlet
...
[smoke-marqueurs-inlet] VERDICT : OK
```
Exit code 0, aucun ÉCHEC dans tout le fichier.

### CRITIQUE 2 — la purge pouvait jeter des marqueurs qu'un mode n'avait pas encore consommés

`coupe = min(self._marqueur_curseur.values())` ne considérait que les modes ayant DÉJÀ appelé
`markers_murs`. Un mode encore en chauffe (actif, marqueur-écoutant, mais sans entrée dans le
dict) était absent du calcul : la purge tranchait alors devant lui, perdant en silence tout ce qui
lui était adressé, sans passer par `marqueurs_perdus`.

**Fix** : `_purge_marqueurs()` calcule `coupe` sur les modes ACTIFS qui écoutent des marqueurs
(dérivés de `self.active`, pas des clés de `_marqueur_curseur`), avec `.get(mode_id, 0)` — un mode
sans entrée compte comme curseur 0, ce qui bloque la purge tant qu'il n'a pas commencé à consommer.

**Rouge** (mutation : retour à `min(self._marqueur_curseur.values())`, modes non considérés) :
```
  ÉCHEC « b » actif sans curseur compte comme 0 : la purge n'a PAS lieu, rien n'est jeté avant qu'il ait pu consommer (2000 marqueurs restants)
  ÉCHEC ...et une fois que LES DEUX ont un curseur, la coupe reprend à leur MINIMUM (2000 marqueurs, curseurs {'smoke-marqueur-a': 0, 'smoke-marqueur-b': 2500})
[smoke-marqueurs-inlet] VERDICT : PROBLÈME
```
3000 marqueurs adressés à « b » (encore sans curseur) disparaissent silencieusement (5000 → 2000)
au lieu des 5000 attendus. Les deux seules assertions touchées sont celles du CRITIQUE 2 ; le reste
du sous-test (A, C, D, E) reste vert — la mutation est bien isolée à ce défaut précis.

**Vert** (fix restauré) : exit code 0, `[smoke-marqueurs-inlet] VERDICT : OK`.

### IMPORTANT 3 — le curseur d'un mode arrêté n'était jamais nettoyé

`_stop_mode` retirait l'entrée de `self.active` mais laissait celle de `_marqueur_curseur`.

**Fix** : `self._marqueur_curseur.pop(mode_id, None)` ajouté dans `_stop_mode`.

**Rouge** (mutation : la ligne de nettoyage retirée) :
```
  ÉCHEC _stop_mode retire le curseur du mode qu'il arrête ({'smoke-marqueur-a': 12345, 'smoke-marqueur-b': 0})
[smoke-marqueurs-inlet] VERDICT : PROBLÈME
```
Seule cette assertion échoue.

**Vert** (fix restauré) : exit code 0, `[smoke-marqueurs-inlet] VERDICT : OK`.

⚠️ **Constat en cours de route** : avec le CRITIQUE 2 corrigé (coupe dérivée de `self.active`, pas
des clés de `_marqueur_curseur`), le curseur mort laissé par ce défaut ne bloque PLUS la purge (il
n'est simplement plus consulté, son mode n'étant plus dans `active`) — sa conséquence pratique
principale est donc déjà neutralisée par le fix du CRITIQUE 2. Le nettoyage explicite reste
implémenté tel que demandé (hygiène du dict sur une longue séance à cycles démarrer/arrêter
répétés), et sa preuve rouge/vert ci-dessus porte directement sur l'effet demandé (l'entrée
disparaît de `_marqueur_curseur`), pas sur un blocage de purge qui ne se produit plus.

### IMPORTANT 4 — `pull()` sans garde d'exception

Comme le tick de calibration juste à côté dans `run()`, `_tire_marqueurs()` encapsule maintenant
`resolve()`+`pull()` dans un `try/except`, comptant l'incident dans le nouveau
`marqueurs_inlet_erreurs` plutôt que de le laisser remonter. Testé dans `_smoke_marqueurs_inlet`
(bloc D) avec un faux inlet dont `pull()` lève : `marqueurs_inlet_erreurs` passe de 0 à 1, le
moteur ne tombe pas. Pas de preuve rouge/vert exigée pour ce point ; non faite (le défaut n'a pas
été réintroduit puisqu'il s'agit d'un ajout, pas d'un ordre à inverser).

### IMPORTANT 5 — l'assertion n°2 de `_smoke_marqueurs_murs` ne testait rien à cet endroit

Au moment où elle s'exécutait, le `break` de maturité arrêtait déjà la boucle à l'index 1 : le
marqueur `errp` (index 2) n'était jamais atteint. Elle aurait passé à l'identique avec le filtre
`if d.get("mode") != mode_id: continue` purement supprimé.

**Fix** : ajout d'un scénario dédié, isolé (tampon et file neufs), où le marqueur d'un autre mode
est placé AVANT un marqueur p300 — tous deux mûrs dans le même appel — pour qu'il soit réellement
MÛR et EXAMINÉ avant qu'un `break` puisse jamais l'atteindre. Assertion existante intégralement
conservée (rien retiré ni réécrit) ; le nouveau bloc s'ajoute à la fin de la fonction.

**Auto-vérification** (suggérée par le brief, pas une preuve exigée) : filtre mode supprimé en
mutation temporaire pour confirmer que mon assertion échoue proprement. Résultat inattendu et
instructif : le crash (`KeyError: 'target'`) survient AVANT d'atteindre mon nouveau bloc, sur une
assertion PRÉEXISTANTE et non touchée (`_smoke_marqueurs_murs`, ligne « le tampon ayant avancé, le
suivant mûrit à son tour », qui indexe `m[1]["target"]` sans `.get`). Ma propre assertion, elle,
utilise `.get("target")` et n'a jamais été atteinte pour être mise à l'épreuve dans ce run précis —
mais son écriture évite structurellement le même piège. Mutation entièrement annulée ensuite
(`if d.get("mode") != mode_id: continue` restauré à l'identique). Voir « inquiétudes » plus bas.

### IMPORTANT 6 — cycle de vie de l'inlet non couvert par un test

**Fix** : nouvelle fonction `_smoke_marqueurs_inlet()`, ajoutée à `resultats`. Couvre :
- (A) le CRITIQUE 1 sur un VRAI `run()` threadé : spec de test injectée dans `registry.MODES` le
  temps du test, commande `start_mode` mise directement dans la file thread-safe de l'engine
  (jamais de mutation croisée de `self.active` entre fils) ;
- (B) le CRITIQUE 2, plus un contrôle positif (la purge reprend normalement une fois tous les
  curseurs présents) ;
- (C) l'IMPORTANT 3 ;
- (D) l'IMPORTANT 4 ;
- (E) le chemin nominal : `resolve()` échoue proprement sans publisher, `pull()` sur un inlet non
  connecté ne lève pas, un second appel à `_ouvre_marker_inlet` n'en recrée pas un autre.

### Comptage des assertions

- Entrées dans `resultats` de `_smoke()` : **15 → 16** (`_smoke_marqueurs_inlet` ajoutée).
- Appels `chk(` dans tout `server.py` (définitions de la fonction locale incluses) : **81 → 93**.
- Vérifié par `git diff a85b105 -- src/core/server.py | grep '^-'` : toutes les lignes retirées
  appartiennent au bloc fautif de `run()` remplacé par les trois nouvelles méthodes — aucune ligne
  `chk(` existante, aucun `resultats.append`/entrée de liste, n'a été retirée ou modifiée.

### Tests finaux (dans cet ordre, aucun moteur laissé tournant entre les deux premiers)

```
python src/core/server.py --smoke     -> exit 0, 16/16 sous-verdicts OK
python src/core/modes/runtime.py      -> exit 0, [runtime] VERDICT : OK (fichier non modifié)
python src/console/app.py --smoke     -> exit 0, [console-smoke] VERDICT : OK
```

### Inquiétudes

- **Fragilité préexistante découverte, non corrigée** : dans `_smoke_marqueurs_murs`, l'assertion
  « le tampon ayant avancé, le suivant mûrit à son tour » indexe `m[1]["target"]` sans garde. Si le
  filtre `if d.get("mode") != mode_id: continue` de `markers_murs` disparaissait un jour (mutation,
  refactor maladroit), CETTE assertion plante par `KeyError` — pas de `ÉCHEC` propre, tout le smoke
  s'arrête net sans imprimer les verdicts suivants. Hors des six défauts confiés, donc non touchée ;
  mais elle mérite un `.get("target")` le jour où quelqu'un repasse par là.
- **IMPORTANT 3 relu à la lumière du CRITIQUE 2** : les deux se recouvrent partiellement (voir
  l'encart dans son bloc ci-dessus) — le fix du CRITIQUE 2 neutralise déjà la conséquence pratique
  principale de l'IMPORTANT 3 (blocage de la purge). Le nettoyage du curseur reste fait, correct et
  prouvé sur l'effet demandé, mais je signale le recouvrement plutôt que de le taire.
- Rien d'autre : les six constats du brief m'ont paru exacts, mesurés tels quels, aucun contesté.
