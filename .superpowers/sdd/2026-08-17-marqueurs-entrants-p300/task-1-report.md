# Task 1 — `MarkerInlet` : recevoir des marqueurs — rapport d'implémentation

Statut : **DONE**
Commit : `a1d24be` — "Give the engine an ear: an inlet for external stimulus markers"
Base : `43a9807` (HEAD de `main` avant cette tâche)

## Ce qui a été fait

1. **`src/core/config.py`** — ajout des deux constantes juste après `P300_MIDLINE = [0, 2, 4]`
   (ligne 608), verbatim par rapport au brief :

   ```python
   # --- Marqueurs ENTRANTS (§12.1 : le moteur écoute une application externe) ------------------
   MARKER_STREAM_DEFAULT = "EEG_API_Unicorn_stim"   # nom du flux de marqueurs qu'on écoute par défaut
   MARKER_LATE_S = 1.0       # retard toléré pour un marqueur (réseau + horloge). Dimensionne le
                             # tampon du moteur AVEC l'époque du mode : un marqueur arrivé après ce
                             # délai ne trouve plus son EEG et sera compté comme perdu, jamais ignoré.
   ```

   Espacement retenu : 1 ligne vide entre `P300_MIDLINE` et le nouveau bloc de commentaire, 2 lignes
   vides avant `def p300_targets` — cohérent avec le reste du fichier (2 lignes vides devant un
   `def` de niveau module). Ces deux constantes ne sont **consommées par rien encore** dans cette
   tâche (le brief le dit explicitement : « Consumes: rien des tâches précédentes ») — elles
   attendent une tâche ultérieure du chantier (probablement le câblage dans `server.py`).

2. **`src/core/markers.py`** (nouveau fichier, 175 lignes) — transcription fidèle du code du brief
   (Step 4 pour le module, Step 2 pour l'autotest), avec **une seule modification assumée** :
   la boucle de réception bout-en-bout de la section 3 de l'autotest, remplacée par une attente
   bornée dans le temps plutôt que par un compteur d'essais. Détail plus bas.

   Contenu du module :
   - `parse_marqueur(txt)` : décode une charge JSON, exige `mode` + `event` (str), garde tous les
     autres champs, ne lève jamais.
   - `MarkerInlet` : résolution par **nom** (jamais par type — évite que le moteur s'écoute
     lui-même via son propre flux `Markers` de statut), `resolve()` idempotent et rappelable,
     `pull()` non bloquant qui applique `time_correction()` mesuré une fois à la connexion,
     `.connecte`, `.nom`, `.illisibles` (compteur des marqueurs reçus mais indécodables).
   - `_selftest()` dans le style du projet (`chk(cond, msg)` local, verdict `[markers] VERDICT : ...`,
     `_sys.exit(0 if _selftest() else 1)` sous `__main__`, `use_utf8_console()` appelé en premier).

## L'ambiguïté du brief — résolution appliquée

Le brief donnait, section 3 de l'autotest :

```python
recus, essais = [], 0
while len(recus) < 2 and essais < 50:
    recus.extend(inlet.pull())
    essais += 1
```

Instruction reçue : remplacer par une attente bornée dans le **temps**, `pull_sample(timeout=0.0)`
rendant la main immédiatement, si bien que 50 tours peuvent s'exécuter en moins d'une milliseconde
avant que LSL n'ait eu le temps de livrer quoi que ce soit — un test qui échouerait par
intermittence, pire qu'un test qui échoue toujours.

Code appliqué (identique à celui fourni dans la consigne), avec `import time` ajouté en tête du
module, non préfixé (`import time`, pas `import time as _time`) — tel qu'explicitement demandé :

```python
recus, echeance = [], time.time() + 5.0
while len(recus) < 2 and time.time() < echeance:
    recus.extend(inlet.pull())
    if len(recus) < 2:
        time.sleep(0.02)
```

J'ai vérifié le raisonnement en le rejouant mentalement : `resolve_byprop` a déjà consommé jusqu'à
5 s dans `inlet.resolve()`, donc la 2ᵉ échéance de 5 s ici est bien pour l'attente de réception, pas
un doublon. Je confirme le diagnostic du brief — je l'ai d'ailleurs vu se matérialiser partiellement
en pratique : sur les 3 runs, `pull()` a toujours renvoyé les 2 marqueurs valides **dès le premier
passage de la boucle** (voir logs plus bas, aucun `time.sleep(0.02)` déclenché), mais ça ne prouve
pas l'absence du risque décrit — juste que sur cette machine, en LSL loopback local, la livraison
est en pratique plus rapide que l'ancien budget de 50 itérations à vide ne le laissait courir. Le
correctif reste la bonne défense : rien ne garantit ce temporal sur une autre machine, un réseau
réel, ou une machine chargée. Note : `parse_marqueur` a bien vu passer le 3ᵉ échantillon (« ceci
n'est pas du json ») puisque `inlet.illisibles == 1` est vérifié — il est rejeté silencieusement
côté `pull()`, pas simplement jamais arrivé.

Aucun autre écart avec le brief. Le reste de l'autotest (sections 1 et 2, et le corps de
`parse_marqueur`/`MarkerInlet`) est repris tel quel.

## Commandes lancées, dans l'ordre

### 0. Garde-fou : aucun moteur qui tourne

```
PowerShell> Get-Process python -ErrorAction Stop
No python process running.
```

### 1–3. Autotest `markers.py`, trois passages consécutifs

```
python src/core/markers.py
```

Résultat **identique et stable** sur les 3 passages — `VERDICT : OK`, code de sortie `0` à chaque
fois. Sortie du 3ᵉ passage (les deux précédents ne diffèrent que par l'horodatage LSL en en-tête) :

```
  OK   une charge utile valide se décode telle quelle
  OK   une charge utile illisible rend None, sans lever
  OK   du JSON qui n'est pas un objet rend None
  OK   un marqueur sans « mode » est refusé : on ne devine pas à qui il s'adresse
  OK   un marqueur sans « event » est refusé : il n'y a rien à en faire
  OK   un champ inconnu est gardé, pas refusé ({'mode': 'p300', 'event': 'flash', 'target': 1, 'inconnu': 42})
  OK   un flux introuvable rend False
  OK   et l'inlet se déclare non connecté
  OK   tirer sur un inlet non connecté rend une liste vide, sans lever
  OK   un flux publié est trouvé PAR SON NOM
  OK   les 2 marqueurs valides arrivent, le 3e illisible est écarté (2)
  OK   le premier est le flash de la cible 2 ({'mode': 'p300', 'event': 'flash', 'target': 2})
  OK   son horodatage est celui de l'émission, pas celui de la réception (écart -0.000 s)
  OK   et l'ordre chronologique est conservé
  OK   le marqueur illisible est COMPTÉ (1)
[markers] VERDICT : OK
EXITCODE=0
```

Les 3 passages ont donné le **même écart d'horodatage** (`-0.000 s`) et la même valeur
`illisibles == 1` — pas de flakiness observée.

Bruit constaté, identique sur les 3 passages, avant les lignes `OK` : liblsl (bibliothèque C++
sous pylsl) journalise sur la console un cycle `netinterfaces` (normal, énumération des interfaces
réseau au premier `resolve_byprop`/`StreamOutlet`) suivi d'une ligne :

```
[R_EEG_API_Unic  ]  data_receiver.cpp:344  ERR| Stream transmission broke off (Input stream error.); re-connecting...
```

Voir « Ce dont je doute » ci-dessous — ce n'est pas un défaut introduit par ce module.

### 4. `python src/core/server.py --smoke`

Sortie complète redirigée vers un fichier du scratchpad puis grep sur les verdicts :

```
[smoke] VERDICT : OK
[smoke-frontiere] 0 violation(s) de frontière
[smoke-frontiere] VERDICT : OK
[smoke-repos] VERDICT : OK
[smoke-ssvep] VERDICT : OK
[smoke-neuro] VERDICT : OK
[smoke-mi] VERDICT : OK
[smoke-calib] VERDICT : OK
[smoke-calib-refus] VERDICT : OK
[smoke-cumul] VERDICT : OK
[smoke-proposition] VERDICT : OK
EXITCODE=0
```

`smoke-frontiere` (qui scanne `src/core/**/*.py`, dont le nouveau `markers.py`, à la recherche
d'un `import research|console|pygame`) rend **0 violation** : la frontière `core/` reste propre.
Le même bruit liblsl (« Stream transmission broke off... re-connecting ») apparaît aussi dans ce
smoke — qui n'importe pourtant pas `markers.py` — ce qui confirme qu'il est indépendant de cette
tâche (voir plus bas).

### 5. Commit

```
git add src/core/markers.py src/core/config.py
git commit -m "Give the engine an ear: an inlet for external stimulus markers"
```

```
[main a1d24be] Give the engine an ear: an inlet for external stimulus markers
 2 files changed, 181 insertions(+)
 create mode 100644 src/core/markers.py
```

`git status --short` après coup : seul le fichier `.superpowers/sdd/.gitignore` reste modifié
(pré-existant, non lié — voir ci-dessous). Rien d'autre en attente.

## Ce dont je doute / observations pour le coordinateur

1. **Bruit liblsl répété, mais pré-existant et non lié à ce module.** La ligne
   `Stream transmission broke off (Input stream error.); re-connecting...` apparaît à l'identique
   sur les 3 passages de `markers.py` **et** dans `server.py --smoke` (qui n'importe pas
   `markers.py`). C'est donc un comportement de liblsl/pylsl sur cette machine (probablement lié à
   la façon dont liblsl teste ses interfaces réseau au tout premier `resolve`/`StreamOutlet` du
   process), pas une régression de cette tâche. Je le signale seulement pour qu'un futur agent ne
   le prenne pas, à tort, comme un symptôme de son propre changement — tous les verdicts restent
   `OK` malgré cette ligne, sur les 4 lancements (3× `markers.py` + 1× `server.py --smoke`).

2. **`.superpowers/sdd/.gitignore` modifié, mais HORS PÉRIMÈTRE de cette tâche — pas touché.**
   En regardant `git status` avant de commencer, ce fichier était déjà modifié dans l'arbre de
   travail (pas par moi) : réduit à la seule ligne `*`, alors que son contenu suivi par git
   contient des règles `!*/`, `!*.md`, `!.gitignore` (pour garder les carnets/briefs/rapports
   visibles à git) et un avertissement explicite dans ses propres commentaires : « Si le carnet
   d'un futur chantier redevient invisible, c'est que le skill [subagent-driven-development] a
   réécrit ce fichier avec son `*` d'origine : remettre ce qui suit. » C'est exactement ce qui
   s'est produit. Effet concret : ce présent rapport (`task-1-report.md`) et `task-1-brief.md`
   sont pour l'instant **ignorés par git** dans leur état actuel sur le disque (`git add` ciblé
   les laisserait de côté sans `-f`). Je n'ai pas restauré ce fichier ni forcé l'ajout des `.md` :
   la tâche 1 ne me demande de commiter que `markers.py`/`config.py`, et ce fichier est un réglage
   partagé de tout le chantier (potentiellement touché par d'autres tâches/agents en parallèle) —
   pas à moi de trancher unilatéralement. À signaler au coordinateur.

3. **Constantes ajoutées mais pas encore branchées.** `MARKER_STREAM_DEFAULT` et `MARKER_LATE_S`
   existent dans `config.py` mais aucun code ne les lit encore (conforme au brief — cette tâche ne
   consomme rien des tâches précédentes et personne en aval n'existe encore). À vérifier dans la
   tâche qui les consommera que le nom et la valeur sont bien repris depuis `config` et non
   redéfinis en dur ailleurs.

4. **Étape « voir l'autotest échouer » (Step 3 du brief) non rejouée à l'identique.** Le brief
   décompose en TDD strict (écrire le test, le voir échouer avec `NameError`/`ImportError`, écrire
   le code, le voir passer). J'ai écrit le module complet directement (code + test dans le même
   fichier neuf) plutôt que de committer un état intermédiaire rouge — la consigne reçue («*Ce que
   j'attends de toi*») ne demandait que d'écrire le module, de le lancer 3× et de voir `OK`, pas de
   reproduire la preuve par l'échec initial. Je le note pour que ce ne soit pas lu comme un TDD
   sauté sans y penser.

5. **Aucun autre moteur/process Python n'était actif** avant, pendant, ni après ces lancements
   (vérifié par `Get-Process python` avant de commencer ; aucun des scripts lancés ne laisse de
   process résiduel — chacun s'est terminé de lui-même avec le code de sortie attendu).

Rien dans le brief ne m'a semblé faux : le constat sur la fragilité de la boucle à 50 essais est
correct et vérifiable (`pull_sample(timeout=0.0)` est non bloquant par construction), et le reste
du code/autotest fourni est cohérent avec les autres modules `core/` (mêmes conventions
`resolve_byprop`/`time_correction`/`local_clock` que `lsl_io.py`).

---

## Tour de correction 1 — trois gardes non éprouvées

Statut : **DONE**
Commit : `ecfa67c` — "Prove the three markers guards a mutation could silently break"

### Vérification des trois constats

Avant de coder quoi que ce soit, relecture du fichier réel (`src/core/markers.py` tel que committé
en `a1d24be`) pour confirmer chaque constat plutôt que de le prendre pour acquis :

- **Constat 1** (ligne 50, `parse_marqueur`) : confirmé. Aucun des payloads testés (sections 1 de
  l'autotest) ne fournit `mode`/`event` PRÉSENT mais non-chaîne. Une mutation affaiblissant
  `isinstance(d.get("mode"), str)` en `d.get("mode") is not None` passait bien tous les tests
  existants — vérifié en la reproduisant (voir preuve rouge ci-dessous).
- **Constat 2** (lignes 69-73, `resolve()`) : confirmé. Le selftest n'appelait `resolve()` sur
  l'inlet connecté qu'une seule fois (ligne 143 de l'ancienne version) ; jamais une seconde fois
  pour exercer la branche `if self.inlet is not None: return True`. Une régression qui retirerait
  cette garde ferait re-mesurer `time_correction()` — précisément l'invariant que la docstring du
  module qualifie de « pas une précaution théorique ».
- **Constat 3** (ligne 104, `pull()`) : confirmé, et la méthode d'injection proposée est la bonne
  réponse technique à l'objection du relecteur (« non corrigeable en mono-machine ») : émetteur et
  récepteur étant dans le même processus, `time_correction()` réel vaut ~0, donc
  `abs(recus[0][0] - t0) < 0.5` ne distingue pas un offset appliqué d'un offset ignoré. Vérifié
  concrètement pendant la preuve rouge (voir plus bas) : avec `+ self.offset` retiré, cette
  assertion PRÉEXISTANTE reste verte (écart mesuré `+0.000 s`) — la preuve en direct que l'ancien
  test ne protégeait rien sur ce point.

Aucun désaccord technique avec le coordinateur : les trois constats tiennent, et la parade au
jugement du relecteur sur le constat 3 est correcte. J'implémente les trois tests tels que décrits,
avec les messages `chk(...)` adaptés au style du fichier.

### Les trois tests ajoutés

1. **Type de `mode`/`event`** (dans la section 1, sans réseau) : deux nouvelles assertions,
   `{"mode":1,"event":"flash"}` et `{"mode":"p300","event":2}`, chacune attendue `None` — l'une
   éprouve la garde de type sur `mode`, l'autre celle sur `event` (le brief n'en donnait qu'un
   exemple ; les deux champs partagent la même ligne de code reliée par un `or`, donc les deux
   sont couverts séparément).
2. **Idempotence de `resolve()`** (dans la section 3, juste après le premier `resolve()` réussi) :
   capture l'offset réel et l'identité de `inlet.inlet`, écrase l'offset par une sentinelle
   invraisemblable (`999.0`), appelle `resolve()` une seconde fois, et vérifie que l'offset ET
   l'identité de l'objet `StreamInlet` sont restés inchangés — puis restaure le vrai offset avant
   de poursuivre (sinon les assertions d'horodatage suivantes hériteraient de la sentinelle).
3. **Application de l'offset** (en fin de section 3, après les assertions existantes, pour ne pas
   perturber `recus`) : injecte `inlet.offset = 12345.678`, pousse un nouveau marqueur, le tire, et
   vérifie que l'horodatage rendu vaut bien `t1 + 12345.678` à `1e-3` près — repris quasi-verbatim
   de la méthode donnée par le coordinateur.

### Comptage des assertions

`grep -c "chk("` sur le fichier, moins 1 pour la ligne `def chk(cond, msg):` :

- **Avant** (commit `a1d24be`) : **15** assertions.
- **Après** : **22** assertions (+7 : 2 pour le constat 1, 3 pour le constat 2, 2 pour le
  constat 3).
- Aucune assertion existante retirée ni affaiblie : `git diff --stat src/core/markers.py` contre
  `a1d24be` confirme **40 insertions(+), 0 deletions(-)** — un diff strictement additif.

### Preuve ROUGE-PUIS-VERT, constat par constat

Méthode : pour chaque constat, la garde correspondante est cassée SEULE (les deux autres restent
correctes), le fichier est lancé, puis la garde est restaurée à l'identique et relancé. Vérifié
après coup qu'aucune trace de mutation ne subsiste (`grep -n "MUTATION" src/core/markers.py` ne
rend rien, et le diff final contre `a1d24be` ne contient que des lignes `+`).

#### Constat 1 — `parse_marqueur`, type de `mode`/`event`

Mutation (celle suggérée par le coordinateur, appliquée à la ligne qui teste les deux champs) :

```python
# avant
if not isinstance(d.get("mode"), str) or not isinstance(d.get("event"), str):
    return None
# cassé
if d.get("mode") is None or d.get("event") is None:
    return None
```

ROUGE (`python src/core/markers.py`, extrait — le reste du fichier, non montré ici, restait à `OK`) :

```
  OK   un marqueur sans « event » est refusé : il n'y a rien à en faire
  ÉCHEC un « mode » PRÉSENT mais qui n'est pas une chaîne est refusé, pas seulement un « mode » absent
  ÉCHEC un « event » PRÉSENT mais qui n'est pas une chaîne est refusé, pareillement
  OK   un champ inconnu est gardé, pas refusé ({'mode': 'p300', 'event': 'flash', 'target': 1, 'inconnu': 42})
  ...
[markers] VERDICT : PROBLÈME
EXITCODE=1
```

Code restauré à l'identique. VERT :

```
  OK   un marqueur sans « event » est refusé : il n'y a rien à en faire
  OK   un « mode » PRÉSENT mais qui n'est pas une chaîne est refusé, pas seulement un « mode » absent
  OK   un « event » PRÉSENT mais qui n'est pas une chaîne est refusé, pareillement
  OK   un champ inconnu est gardé, pas refusé ({'mode': 'p300', 'event': 'flash', 'target': 1, 'inconnu': 42})
  ...
[markers] VERDICT : OK
EXITCODE=0
```

#### Constat 2 — `resolve()`, idempotence

Mutation (garde retirée, exactement comme demandé) :

```python
# avant
if self.inlet is not None:
    return True
flux = resolve_byprop("name", self.nom, timeout=self.timeout_s)
# cassé
flux = resolve_byprop("name", self.nom, timeout=self.timeout_s)
```

ROUGE :

```
  OK   un flux publié est trouvé PAR SON NOM
  OK   un second resolve() sur un inlet déjà connecté rend True aussi
  ÉCHEC ...sans RE-MESURER time_correction() (offset=-1.9149971194565296e-05, sentinelle 999.0 censée rester intacte)
  ÉCHEC ...ni recréer l'inlet sous-jacent (identité de l'objet StreamInlet inchangée)
  OK   les 2 marqueurs valides arrivent, le 3e illisible est écarté (2)
  ...
[markers] VERDICT : PROBLÈME
EXITCODE=1
```

Remarque : `resolve()` continue de rendre `True` (l'assertion juste au-dessus reste verte) — le
défaut n'est pas que la fonction échoue, c'est qu'elle retravaille EN SILENCE, exactement le risque
que le constat décrit. L'offset mesuré une seconde fois (`-1.9e-05`, un vrai `time_correction()` en
boucle locale) écrase bien la sentinelle, ce qui confirme le mécanisme du bug.

Code restauré à l'identique. VERT :

```
  OK   un flux publié est trouvé PAR SON NOM
  OK   un second resolve() sur un inlet déjà connecté rend True aussi
  OK   ...sans RE-MESURER time_correction() (offset=999.0, sentinelle 999.0 censée rester intacte)
  OK   ...ni recréer l'inlet sous-jacent (identité de l'objet StreamInlet inchangée)
  OK   les 2 marqueurs valides arrivent, le 3e illisible est écarté (2)
  ...
[markers] VERDICT : OK
EXITCODE=0
```

#### Constat 3 — `pull()`, application de l'offset

Mutation (`+ self.offset` retiré, exactement comme demandé) :

```python
# avant
recus.append((float(ts) + self.offset, d))
# cassé
recus.append((float(ts), d))
```

ROUGE :

```
  OK   le premier est le flash de la cible 2 ({'mode': 'p300', 'event': 'flash', 'target': 2})
  OK   son horodatage est celui de l'émission, pas celui de la réception (écart +0.000 s)
  OK   et l'ordre chronologique est conservé
  OK   le marqueur illisible est COMPTÉ (1)
  OK   le marqueur du test d'offset arrive (1)
  ÉCHEC l'offset d'horloge est bien APPLIQUÉ aux horodatages rendus (écart mesuré +0.000 s, +12345.678 attendu)
[markers] VERDICT : PROBLÈME
EXITCODE=1
```

Ligne clé : l'assertion PRÉEXISTANTE juste au-dessus (« son horodatage est celui de l'émission… »)
reste `OK` avec l'offset retiré — la démonstration en direct que ce test-là ne prouvait pas
l'application de l'offset, exactement le diagnostic du constat 3. Seule la nouvelle assertion, avec
sa sentinelle injectée, détecte la régression.

Code restauré à l'identique. VERT :

```
  OK   le premier est le flash de la cible 2 ({'mode': 'p300', 'event': 'flash', 'target': 2})
  OK   son horodatage est celui de l'émission, pas celui de la réception (écart -0.000 s)
  OK   et l'ordre chronologique est conservé
  OK   le marqueur illisible est COMPTÉ (1)
  OK   le marqueur du test d'offset arrive (1)
  OK   l'offset d'horloge est bien APPLIQUÉ aux horodatages rendus (écart mesuré +12345.678 s, +12345.678 attendu)
[markers] VERDICT : OK
EXITCODE=0
```

### Incident de méthode, corrigé avant de conclure

Pour la relance finale « trois fois de suite », mes deux premiers essais sont partis dans le MÊME
message d'outils, donc en parallèle (deux process Python lançant chacun un `StreamOutlet` nommé
`EEG_API_Unicorn_selftest_stim` en même temps). Les deux ont rendu `OK`, mais j'ai jugé cette
preuve-là inutilisable : deux flux de même nom en même temps est exactement le risque que le projet
interdit (contrat de nom public, cf. CLAUDE.md) — `resolve_byprop` aurait pu accrocher le flux de
l'AUTRE process sans qu'aucun message ne le signale. Plutôt que de garder ce résultat par
commodité, je l'ai écarté et j'ai relancé les 3 passages strictement en séquentiel (un seul process
Python à la fois, vérifié entre chaque lancement).

### Relance finale, 3 passages strictement séquentiels

Les 3 lancements ci-dessous sont allés l'un après l'autre, chacun attendu jusqu'à sa fin avant le
suivant. Sortie identique aux trois passages (seul l'horodatage liblsl en en-tête change) :

```
  OK   une charge utile valide se décode telle quelle
  OK   une charge utile illisible rend None, sans lever
  OK   du JSON qui n'est pas un objet rend None
  OK   un marqueur sans « mode » est refusé : on ne devine pas à qui il s'adresse
  OK   un marqueur sans « event » est refusé : il n'y a rien à en faire
  OK   un « mode » PRÉSENT mais qui n'est pas une chaîne est refusé, pas seulement un « mode » absent
  OK   un « event » PRÉSENT mais qui n'est pas une chaîne est refusé, pareillement
  OK   un champ inconnu est gardé, pas refusé ({'mode': 'p300', 'event': 'flash', 'target': 1, 'inconnu': 42})
  OK   un flux introuvable rend False
  OK   et l'inlet se déclare non connecté
  OK   tirer sur un inlet non connecté rend une liste vide, sans lever
  OK   un flux publié est trouvé PAR SON NOM
  OK   un second resolve() sur un inlet déjà connecté rend True aussi
  OK   ...sans RE-MESURER time_correction() (offset=999.0, sentinelle 999.0 censée rester intacte)
  OK   ...ni recréer l'inlet sous-jacent (identité de l'objet StreamInlet inchangée)
  OK   les 2 marqueurs valides arrivent, le 3e illisible est écarté (2)
  OK   le premier est le flash de la cible 2 ({'mode': 'p300', 'event': 'flash', 'target': 2})
  OK   son horodatage est celui de l'émission, pas celui de la réception (écart -0.000 s)
  OK   et l'ordre chronologique est conservé
  OK   le marqueur illisible est COMPTÉ (1)
  OK   le marqueur du test d'offset arrive (1)
  OK   l'offset d'horloge est bien APPLIQUÉ aux horodatages rendus (écart mesuré +12345.678 s, +12345.678 attendu)
[markers] VERDICT : OK
EXITCODE=0
```

Répété identiquement 3/3, `EXITCODE=0` à chaque fois. `Get-Process python` vérifié vide avant le
premier des 3 passages séquentiels.

### `server.py --smoke` rejoué

Non explicitement redemandé pour ce tour de correction, mais relancé par prudence (convention du
projet : tout changement dans `src/core/` passe les trois smokes headless). Tous les verdicts
restent `OK`, dont `smoke-frontiere` à **0 violation** :

```
[smoke] VERDICT : OK
[smoke-frontiere] 0 violation(s) de frontière
[smoke-frontiere] VERDICT : OK
[smoke-repos] VERDICT : OK
[smoke-ssvep] VERDICT : OK
[smoke-neuro] VERDICT : OK
[smoke-mi] VERDICT : OK
[smoke-calib] VERDICT : OK
[smoke-calib-refus] VERDICT : OK
[smoke-cumul] VERDICT : OK
[smoke-proposition] VERDICT : OK
EXITCODE=0
```

### Ce dont je doute, pour ce tour

- Les constats Mineurs listés par le coordinateur (RecursionError JSON pathologique, `import time`
  non préfixé, `timeout_s=0.0` non exercé, disparition de l'émetteur en séance) n'ont pas été
  touchés, comme demandé.
- Le message `chk` du constat 2 (« sentinelle 999.0 censée rester intacte ») se lit un peu
  bizarrement dans le cas VERT (« offset=999.0, sentinelle 999.0... » répète la même valeur) —
  assumé : c'est le prix de vouloir un message qui reste lisible dans les deux issues (rouge ET
  vert) sans dupliquer la logique d'affichage. Je le signale au cas où une formulation plus nette
  vous paraîtrait utile, sans y voir un problème fonctionnel.
- Je n'ai compté que les lignes `chk(` par `grep`, en retranchant à la main la ligne de la
  définition locale (`def chk(cond, msg):`) : pas de compteur automatique dédié dans le fichier. Si
  un futur tour ajoute une autre fonction locale contenant la sous-chaîne `chk(` dans son nom, ce
  comptage manuel cesserait d'être fiable tel quel — sans enjeu aujourd'hui, juste noté.
