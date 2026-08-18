# LOT 2 — le mode P300 et son autotest : rapport de correction

**Périmètre :** `src/core/modes/p300.py`, `src/core/lsl_io.py`. **Rien d'autre n'a été touché** —
ni `docs/markers.md`, ni `research/`, ni la console, ni `server.py` (lots 1 et 3).

**Statut : TERMINÉ.** 6 critiques, 13 importants, 7 mineurs traités. Tous les tests verts.

---

## 1. La forme des correctifs qui ne sont pas de simples corrections

### 1.1 — Le plafond d'abandon change de DISCRIMINANT (2.1)

`_MAX_EPOQUES = 6 × 8 × 2 = 96` disparaît, remplacé par **`_MAX_PAR_CIBLE = P300_REPS`**, vérifié
**dans `_encaisser_flash`** et non plus dans `_verifie_abandon`.

**Pourquoi par cible et pas par écart entre deux flashs.** Les deux discriminants proposés par la
revue ne se valent pas ici :

- l'**écart** (SOA 150 ms contre frontière de manche) suppose qu'il y ait une frontière à
  détecter. Or l'émetteur de ce dépôt n'a **aucune pause entre deux manches** — c'est le critique
  3.2 du lot 3, encore ouvert quand j'écris. Un seuil sur l'écart ne détecterait donc rien
  aujourd'hui, et punirait demain un protocole légitimement lent (un speller à SOA 1 s).
- le compte **par cible** ne dépend d'aucune horloge : dans UNE manche, une cible flashe `reps`
  fois, jamais plus.

**Pourquoi dans `_encaisser_flash` et pas dans `_verifie_abandon`.** C'est le point qui décide de
tout : `_verifie_abandon` tourne **après** le lot de marqueurs du tour, donc **après** un
`round_end` arrivé dans le même lot. Deux manches soudées suivies de leur `round_end` publieraient
la décision fausse **avant** que le garde-fou ne parle. Le contrôle par cible tombe sur le premier
flash de trop, **avant** le `round_end`.

Effet de bord voulu : le flash qui déclenche l'abandon **ouvre la manche suivante** au lieu d'être
jeté. Deux manches soudées ne perdent donc qu'une manche sur deux — la seconde est décodée juste
(prouvé : la décision porte 48 flashs et **uniquement** des époques de la manche B).

**Le prix, assumé et BRUYANT :** une application qui répète plus de `P300_REPS` fois par cible fait
abandonner ses manches, avec un message qui nomme la constante à changer. C'est le contraire de
l'ancien comportement (publier une sélection fausse sans un mot), et c'est désormais **écrit dans
les métadonnées du flux** : `reps` devient `max_reps_per_target` — un plafond que le moteur
APPLIQUE, au lieu d'une affirmation sur une application externe qu'il ne contrôle pas (2.18).

### 1.2 — Les trois assertions qui regardaient une case trop loin (2.3, 2.4, 2.5)

Même maladie, trois nets différents, tous les trois prouvés par mutation (§2) :

| ce qui était vérifié | ce qui l'est maintenant |
|---|---|
| la POSITION du pic dans l'époque | `np.array_equal(rt._epoques[-1], eeg[i_pic - n_pre:i_pic + n_post])` — position, forme, ordre des voies **et absence de tout traitement** |
| `_epoques` seul (`_cibles` lu NULLE PART) | `len(_cibles) == 0` là où l'époque est perdue, et l'appariement des deux listes après les ticks qui comptent |
| le NOMBRE d'époques par cible | leur **identité** : une amplitude unique plantée à l'onset de chaque flash, relue par cible (`v[k][N_PRE, 0]`) |

### 1.3 — La branche `choisi is None` est COUVERTE, pas supprimée (2.6)

Un quatrième faux modèle (`_ModeleIndecis`) rend `(None, scores_connus)`. Prouvé : `index == -1`
(jamais 0), les **vrais** scores publiés — c'est le seul -1 qui en a — et un motif imprimé. La
branche reste en place avec un commentaire disant pourquoi : remonter `P300_SELECT_MARGIN` ferait
sinon tomber le `else` sur `moyennes[None]` → `KeyError` → moteur à terre.

---

## 2. Preuves ROUGE → VERT

### 2.1 — Deux manches complètes soudées par un `round_end` manquant

Mutation : plafond **GLOBAL** restauré (`> P300_N_TARGETS * P300_REPS * 2`) dans
`_verifie_abandon`, contrôle par cible désarmé.

```
  ÉCHEC le plafond par cible (8) abandonne la manche A, sans attendre le délai (0 abandon(s))
  OK    une SEULE décision sort de ces deux manches soudées (1)
  ÉCHEC et elle porte sur UNE manche (48 flashs), pas sur les deux soudées (96)
  ÉCHEC le modèle reçoit 8 époques par cible, pas 16 ({0: 16, 1: 16, 2: 16, 3: 16, 4: 16, 5: 16})
  ÉCHEC ...et ce sont TOUTES des époques de la manche B : aucune amplitude de la manche A
        (<= 547) n'a survécu ([500.0, 506.0, ..., 542.0, 548.0, ..., 590.0])
[p300] VERDICT : PROBLÈME                                                          (EXIT=1)
```

Le `(0 abandon(s))` et le `(96)` sont mot pour mot le constat de la revue : **les deux garde-fous
se taisent** et la décision sort avec la moitié des époques de la manche précédente. Noter que
« une SEULE décision » reste **OK** sous la mutation : c'est bien la décision FAUSSE, pas une
décision en trop — d'où les trois autres assertions.

**VERT après restauration :**
```
[p300] manche ABANDONNÉE : la cible 0 a déjà flashé 8 fois dans cette manche (plafond par cible
       = P300_REPS) — round_end jamais reçu (application externe plantée ?). 48 flash(s)
       orphelin(s) jeté(s).
  OK   le plafond par cible (8) abandonne la manche A, sans attendre le délai (1 abandon(s))
  OK   une SEULE décision sort de ces deux manches soudées (1)
  OK   et elle porte sur UNE manche (48 flashs), pas sur les deux soudées (48)
  OK   le modèle reçoit 8 époques par cible, pas 16 ({0: 8, 1: 8, 2: 8, 3: 8, 4: 8, 5: 8})
  OK   ...aucune amplitude de la manche A (<= 547) n'a survécu ([548.0, ..., 590.0])
[p300] VERDICT : OK                                                                (EXIT=0)
```

### 2.3 — Un `bandpass()` ajouté dans `_encaisser_flash` (DOUBLE FILTRAGE)

Mutation : `epoque = bandpass(epoque.T, engine.acq.fs).T` juste avant l'`append`.

```
  OK    ⚠️ ALIGNEMENT (chemin réel _encaisser_flash) : le pic se retrouve à l'échantillon 38,
        il devait être à 38 (décalage de 0 échantillons = +0 ms)
  OK    l'époque construite par le runtime a exactement la FORME attendue ((238, 8))
  ÉCHEC ⚠️ l'époque du runtime est la tranche BRUTE du tampon, valeur pour valeur : aucun
        filtrage, aucune correction de ligne de base, aucune conversion d'unité ne s'est glissée
        dans `_encaisser_flash`
  ÉCHEC (filet n°2) la manche neuve ... ({0: [42.08, 41.24], 1: [-164.56, -164.86], ...}
        attendu {0: [503.0, 509.0], 1: [504.0, 510.0], ...})
[p300] VERDICT : PROBLÈME                                                          (EXIT=1)
```

**C'est la démonstration exacte du constat de la revue** : la position du pic et la forme restent
**vertes** sous le double filtrage (`filtfilt` est à phase nulle) ; seule la comparaison à la
tranche brute rougit. Les amplitudes plantées (503 → 42,08) montrent au passage ce que le double
filtrage fait au signal.

**VERT après retrait :** les deux assertions repassent OK, `VERDICT : OK`, `EXIT=0`.

### 2.4 — `self._cibles.append(cible)` remonté au-dessus de la garde `if epoque is None`

```
  ÉCHEC ...et sa CIBLE non plus : les deux listes ne s'allongent QUE ensemble
        (1 cible(s) pour 0 époque(s))
  OK    et les deux listes sont toujours appariées (1 époque(s), 1 cible(s))
[p300] VERDICT : PROBLÈME                                                          (EXIT=1)
```

L'assertion d'appariement générique reste verte (dans ce scénario-là l'époque est valide) : c'est
**le scénario de l'époque perdue** qui ferme le trou, celui que la revue avait nommé.

**VERT après retrait :** `(0 cible(s) pour 0 époque(s))`, `VERDICT : OK`, `EXIT=0`.

### 2.5 (bonus, non demandé) — permutation pure des cibles

Mutation : `self._cibles.append((cible + 1) % self.n_targets)`.
```
  ÉCHEC la manche neuve n'hérite d'AUCUN flash orphelin ... ({1: [503.0, 509.0], 2: [504.0,
        510.0], ..., 0: [508.0, 514.0]} attendu {0: [503.0, 509.0], ...})
```
L'ancienne capture par COMPTES (`{i: 1}`) était insensible à cette mutation ; la capture par
amplitude la voit du premier coup.

---

## 3. Le reste du lot, constat par constat

**2.2 — la chauffe consomme les marqueurs.** `P300Runtime.tick` est redéfini : hors phase
`running`, il appelle `markers_murs` (c'est l'APPEL qui fait avancer le curseur du moteur), jette
le lot, le **compte** (`_marqueurs_chauffe`, exposé dans `state()`) et le **dit une fois par
chauffe**. Écrit dans `tick` et pas dans `_rest_step` parce que `_rest_step` n'est appelé qu'en
phase `rest`, et c'est `warmup` (15 s, `Rest.duration_s` valant 0) qui laissait l'arriéré se
former. Prouvé : 7 marqueurs consommés en pleine chauffe, comptés, dits, **zéro époque** et zéro
décision.

**2.7 — l'assertion `0 == 0`.** `state()` est maintenant lu PENDANT la manche B, où
`refus_cible` vaut 1 (les deux lectures d'origine sont conservées).

**2.8 — plancher de manche.** `n_targets` → `n_targets × P300_MIN_REPS` (12 flashs). Et `_log`
imprime `n_flashes` sur **chaque** ligne, décision comprise. Les scénarios du test qui tenaient sur
une seule répétition ont été refaits à `P300_MIN_REPS` ; une manche d'UNE répétition a son propre
scénario, qui vérifie le refus.

**2.9 — horodatage de la décision.** `self._decider(ts)` (l'instant du `round_end`) au lieu de
`lsl_ts`. Le test appelle volontairement `tick` avec un `lsl_ts` 5 s plus loin et exige l'instant
du marqueur.

**2.10 — le modèle confronté au runtime.** `_desaccord_geometrie` compare `model.fs/pre_s/post_s`
à `engine.acq.fs / self.pre_s / self.post_s` et refuse au démarrage en nommant l'écart. Testé avec
un modèle entraîné à 125 Hz.

**2.11 — manche 100 % invalide.** `_verifie_abandon` entre désormais sur « une manche est EN
COURS » (`_epoques` **ou** `_refus_cible`), et `_dernier_flash_ts` avance sur tout flash **reçu**,
refusé compris. Une manche entièrement refusée est donc abandonnable au délai, ce qui **réarme**
`_refus_cible`. Et la garde anti-bruit passe de « une fois par manche » à **des paliers**
(1, 10, 100, 1000) dans la manche — le motif de `_dit_compteurs_marqueurs` du moteur.

**2.12 — le -1 par marge.** Motif imprimé, et `_log` ne fabrique plus de raison : `motif` est
donné par l'appelant, qui seul sait laquelle des trois s'applique.

**2.13 — `gagnant=3`.** Score 0,5, ni max ni min : tue les deux mutations (« le runtime recalcule
son argmax » et `confidence = max(moyennes.values())`).

**2.14 — la FORME du chemin réel** est assertée explicitement, en plus de l'égalité valeur pour
valeur.

**2.15 — voir §4 (a)** : partiellement fermé, et je le dis.

**2.16 — `margin=P300_SELECT_MARGIN`.** Les faux modèles prennent une **sentinelle** en défaut
(`"marge jamais transmise"`) : un appel qui omettrait l'argument ne peut plus passer inaperçu
derrière un `0.0 == 0.0`.

**2.17 — `0 <= index`** dans le seul test qui fait tourner le vrai décodeur.

**2.18 / 2.19 — les métadonnées du flux.** `reps` → `max_reps_per_target` (un plafond appliqué),
et `margin` publiée comme le SSVEP et le MI le font. L'autotest de `lsl_io` vérifie les trois
champs **et** que l'ancien `reps` a bien disparu.

**Mineurs :** `isinstance(cible, bool)` d'abord (un `target: true` en JSON était décodé comme la
cible 1) et deux messages distincts selon que c'est le TYPE ou la PLAGE qui cloche · commentaire
`# 37` → `# 38` (mesuré : `int(round(0,15 × 250)) == 38`) · `confidence = 0.0` sur les
non-décisions **documenté** dans la docstring du publieur (voir §4 c) · garde `None` avant de
déréférencer l'époque décalée d'une demi-période · docstring de `state()` réaccordée aux pannes
qu'elle expose réellement · `"decoded_p300"` écrit une seule fois (`DecodedP300Publisher.SUFFIXE`,
repris par `SPEC.stream`, et le lien est asserté) · `no_decision_index` ajouté aux métadonnées du
**SSVEP** · l'en-tête de `lsl_io.py` ne dit plus « trois flux au MVP » pour 7 publieurs (ce mineur
figurait dans la liste du lot 3 mais le FICHIER est dans le mien : personne d'autre ne pouvait le
corriger sans recouvrement).

**Le texte rendu FAUX par le lot 1** (aide du réglage `stream_in`) est réaccordé : redémarrer le
MODE suffit désormais à reprendre un nouveau nom de flux, il n'y a plus besoin de relancer le
moteur. Vérifié dans le code du lot 1 (`_stop_mode` → `_libere_marker_inlet` dès qu'aucun mode
actif n'a `marker_epoch_s > 0`). `docs/markers.md` porte la même phrase et reste au lot 3.

---

## 4. Mes inquiétudes

**a) Le 2.15 n'est fermé qu'à moitié, et il faut le savoir.** Le plafond par cible attrape une
contamination seulement si la manche NEUVE pousse une cible au-delà de `P300_REPS`. Une
application qui redémarre dans les 10 s et flashe une manche **courte** (moins de 8 répétitions
par cible) reste soudée aux orphelins sans que rien ne parle : à 3 orphelins + 2 répétitions, les
comptes par cible plafonnent à 3. Le discriminant par ÉCART, lui, l'attraperait — mais seulement
une fois que l'émetteur aura une pause entre manches (**3.2, lot 3**). Une fois cette pause en
place, ajouter un contrôle d'écart devient possible et fermerait le reste ; je ne l'ai pas écrit
parce qu'il ne détecterait rien aujourd'hui.

**b) `P300_REPS` gagne un second rôle : c'est maintenant un PLAFOND que le moteur applique.** Un
étudiant qui lance son émetteur avec `--reps 12` sans toucher `config.py` verra **toutes** ses
manches abandonnées. C'est bruyant, nommé, et documenté dans les métadonnées — mais c'est un
changement de comportement qui n'existait pas avant, et il n'est pas dans la doc (lot 3).

**c) `confidence = 0.0` sur les non-décisions : documenté, pas changé.** J'ai envisagé `NaN`, qui
serait la valeur honnête ; je l'ai écarté sur un fait vérifiable : `json.dumps` sérialise `NaN` en
`NaN`, qui n'est **pas** du JSON valide — or `_decoded` voyage dans `snapshot()` et dans le flux
`status`, jusqu'à des clients Unity/MATLAB. Un correctif propre demanderait de traiter le cas dans
le sérialiseur du moteur, donc hors de mon lot.

**d) Un émetteur vivant mais fautif ne fait plus expirer sa manche.** Conséquence directe du
correctif 2.11 (`_dernier_flash_ts` avance sur les flashs refusés) : une application qui n'envoie
QUE des cibles hors plage garde sa manche ouverte indéfiniment. Rien de faux ne peut en sortir
(aucune époque valide), et les paliers 1/10/100 continuent de crier — mais si des époques valides
la précédaient, elles restent orphelines. J'ai préféré ça au défaut inverse (un émetteur bien
vivant traité comme mort).

**e) Rien de ce lot n'a été vérifié au casque**, ni avec un vrai émetteur sur une seconde machine.
Tout est prouvé sur des marqueurs fabriqués et un tampon EEG synthétique. Le premier chiffre à
regarder en salle est `marqueurs_chauffe` : s'il dépasse largement 15 s × (1/SOA), c'est que le
curseur du moteur ne suit pas.

---

## 5. Comptage des assertions

Méthode : appels `chk(` **moins** la ligne `def chk(`, plus un contrôle AST (extraction du premier
argument de chaque `chk`, blancs normalisés) pour lister les disparues.

| fichier | avant | après |
|---|---|---|
| `src/core/modes/p300.py` | **52** | **87** |
| `src/core/lsl_io.py` (`assert`) | 3 | 7 |

**Six assertions préexistantes ont été RÉÉCRITES, aucune retirée ni affaiblie** (contrôle AST :
`DISPARUES telles quelles : 6`, toutes justifiées) :

| avant | après | pourquoi |
|---|---|---|
| `-1 <= index < P300_N_TARGETS` | `0 <= index < …` | 2.17, plus STRICTE |
| `n_flashes == P300_N_TARGETS` | `… == P300_N_TARGETS * P300_MIN_REPS` | 2.8 : une manche à 1 répétition est désormais refusée |
| `index == 1 and confiance == 7.0` | `index == 3 and confiance == 0.5` | 2.13, tue 2 mutations de plus |
| `capture.recu == {i: 1 …}` | comparaison des AMPLITUDES par cible | 2.5, insensible à l'ordre avant |
| `{3 compteurs} <= set(etat)` | `{4 compteurs} <= set(etat)` | sur-ensemble |
| `_MAX_EPOQUES > P300_N_TARGETS` | `_MAX_PAR_CIBLE >= P300_REPS` | la constante n'existe plus ; l'invariant utile est « ne se déclenche pas sur une manche normale » |

---

## 6. Tests

Aucun moteur ne tournait (`Get-Process python` vérifié avant chaque lancement, 0 processus), un
seul programme à la fois, aucun fichier écrit hors d'un `tempfile.mkdtemp` nettoyé en `finally`.

| commande | verdict |
|---|---|
| `python src/core/modes/p300.py` | `OK`, EXIT=0, **87 assertions** |
| `python src/core/lsl_io.py` | `OK`, EXIT=0 |
| `python src/core/modes/registry.py` | `OK`, EXIT=0 |
| `python src/core/server.py --smoke` | 17 sous-tests, tous `OK`, EXIT=0 |
| `python src/console/app.py --smoke` | `OK`, EXIT=0 |
| `python src/research/app.py --smoke` (bonus) | EXIT=0 |
