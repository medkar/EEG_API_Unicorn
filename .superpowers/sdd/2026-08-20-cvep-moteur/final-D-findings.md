# Tranche D — revue finale : `research/cvep_stimulus.py` + `research/__init__.py`

Lecture seule. Aucun programme Python lancé (six relecteurs en parallèle, mêmes noms de flux LSL).
Tout chiffre ci-dessous est **calculé depuis le code lu**, pas mesuré à l'exécution ; les vérifications
qui exigeraient une exécution sont marquées « À VÉRIFIER PAR EXÉCUTION ».

**Décompte : 1 Critical · 4 Important · 6 Minor.**

## Ce qui tient (vérifié, pour ne pas le re-suspecter)

- **Aucun BrainFlow, ni direct ni transitif.** `cvep_stimulus.py` importe `core.config`,
  `core.cvep_code`, `pylsl`, `pygame` (tardif) et `research.ssvep_stimulus.measure_refresh` ;
  `ssvep_stimulus.py` n'importe que `core.config`. Le programme ne peut pas ouvrir le casque.
- **Le geste flip → horodatage est correct** (`cvep_stimulus.py:530-537`) et **la sonde PIXEL le
  garde vraiment**. Vérifié en suivant la mutation : en remontant `emet()` au-dessus de
  `pygame.display.flip()`, la fenêtre des `fen_sonde=3` derniers flips précédant le `push` se
  termine sur la position `L-1 = 62`, donc `table[fen] == 62 ≠ 0` → l'assertion `:1013` rougit sur
  **tous** les marqueurs. Le critère d'ordre seul (`:1005`) ne rougit que sur le tout premier
  (`i >= 1` échoue parce qu'aucun flip ne précède le marqueur de la frame 0) — soit 1 sur N, ce qui
  confirme le chiffre du brief. La fixture `:988` (63/63 motifs distincts sur 3 images) et le témoin
  `:999` (l'écran change 62 fois sur 63) justifient correctement le détour par les pixels.
- **La mise en garde sur `get_surface()` après `flip()` est écrite** (`:661-669`), avec la bonne
  raison (double tampon matériel) et le bon remède (empreinte AVANT le flip).
- **Le test de phase (partie A) mord.** Simulé à la main : `avant` = 207 entrées à écart 0,
  `pendant` = 45 entrées à écart 1, `apres` = 252 entrées à écart 0. Un `int(age*refresh)+1`
  systématique fait rougir `:747` et `:767` ; supprimer `_EPS_FRAME` fait rougir `:747` au bord de
  chaque cycle. Les seuils `== 0` (et non « ≤ 1 ») sont ce qui rend le test non creux.
- **`--smoke` n'écrit pas dans le vrai `data/`** : `_runtime_de_test` repointe
  `core.modes.cvep.CVEP_MODEL_PATH` sur un `tempfile.mkdtemp()`, restaure dans le `finally` et
  `rmtree` derrière lui ; `run()` n'écrit aucun fichier. L'autotest sort en 1 (`:1160`).
- **Le contrat du marqueur est celui que le moteur lit.** `core/modes/cvep.py:452` filtre sur
  `event == "cycle"` ; `:461` refuse `bool` avant `int/float` — l'émetteur pousse
  `float(refresh)` (`:536`), le smoke `:961` interdit explicitement `bool`. La péremption
  (`CVEP_PEREMPTION_CYCLES=3`, soit 3,15 s) laisse 3× de marge sur une horloge à ~1,05 s.
- **La conservativité de `TRANSITION_S` est du bon côté.** Le vote strictement nécessaire vaut
  `(CVEP_VOTE_LEN − 1) × period_s = 0,4 s` (les fenêtres du deque sont à `t`, `t−0,2`, `t−0,4`),
  pas 0,6 s : l'émetteur jette 0,2 s de plus que le minimum. C'est la bonne direction et ça absorbe
  presque exactement la latence de saccade (cf. M6).

---

## CRITICAL

### C1 — La vérité-terrain ne vit que sur stdout, et le flux décodé n'a AUCUN horodatage absolu : le dépouillement du 2.9 n'est pas exécutable tel qu'écrit

`src/research/cvep_stimulus.py:548-550` (l'unique sortie de la vérité-terrain)
· `examples/receiver.py:116` (l'autre moitié du raccord, hors tranche)
· `docs/recette.md` § 2.9 « Dépouille : pour chaque consigne, compte les `decoded_cvep` postérieurs
au "compter à partir de" »

**Le scénario.** L'opérateur joue le 2.9. Terminal 2 (émetteur) imprime, ~une fois toutes les 8,4 s :

```text
[cvep-stim] t=12345.678  cycle 9 : fixe « DROITE » (cible 2)  —  compter à partir de t=12348.378 (+2.7 s de transition)
```

Terminal 3 (`examples/receiver.py --stream decoded_cvep`) imprime, 5 fois par seconde :

```text
[ 12.3 ms old] target_index=   2.00  confidence=   0.31  score_0=  ...
```

`receiver.py:111,116` calcule `age_ms = (local_clock() − (ts + offset)) * 1000` et **n'imprime que
cet âge relatif** — l'horodatage LSL absolu `ts + offset` est calculé puis jeté. Le terminal 1 du
moteur (`core/modes/cvep.py:657`) n'imprime pas d'horodatage non plus.

**Conséquence : la clé de jointure n'existe pas.** Les deux moitiés du dépouillement sont dans deux
systèmes de coordonnées différents — un instant LSL absolu d'un côté, un âge relatif de l'autre.
Il n'y a aucun moyen, à partir des sorties livrées, de décider si une ligne `decoded_cvep` est
postérieure à `t=12348.378`. L'opérateur ne peut que comparer l'ordre d'apparition à l'œil entre
deux fenêtres, sur ~1 500 lignes pour 5 min, à 5 Hz — c'est exactement ce que T8 a annoncé
(« pénible et faux la première fois », task-8-report.md:99-103), et c'est la **seule étape du 2.9
qui produise un chiffre**. Vérifié : `examples/receiver.py` est le SEUL consommateur de flux du
dépôt (`grep -l "pull_sample\|StreamInlet"` → `core/lsl_io.py`, `core/markers.py`,
`core/modes/contract.py`, `core/server.py`, `examples/receiver.py`), et `docs/recette.md` ne
contient aucune redirection, aucun `tee`, aucun `--log`.

S'y ajoute que **le scrollback du terminal est la seule copie** : un `Ctrl+C` malheureux, une
fenêtre fermée par réflexe entre les blocs A / B / A′ (que le 2.9 demande explicitement de fermer :
« B — fermer les trois terminaux, PUIS : »), ou un tampon de console dépassé, et la séance est
définitivement non dépouillable. Une séance casque ne se répète pas — c'est la prémisse de tout ce
fichier.

### Correctif minimal — oui, il faut un journal, et voici le format

**Côté émetteur (cette tranche) : `--log CHEMIN`, opt-in, sans défaut, en JSONL.**

Opt-in et sans valeur par défaut pour trois raisons : `--smoke` ne doit jamais pouvoir écrire quoi
que ce soit (contrainte globale de la revue), le vrai `data/` reste interdit d'écriture, et
l'opérateur nomme son fichier comme il nomme sa séance. JSONL parce que c'est **append + flush** :
un `Ctrl+C` au milieu laisse un fichier complet jusqu'à la dernière ligne, ce qu'un JSON global ne
permet pas.

Trois genres de ligne, et rien d'autre :

```jsonl
{"kind":"header","t":12340.000,"iso":"2026-09-03T14:02:11","seed":874512,"refresh":60.0,
 "code_len":63,"n_targets":6,"cycles_par_cible":8,"transition_s":2.700,
 "stream":"EEG_API_Unicorn_stim","cibles":["HAUT","HAUT_DROITE","DROITE","BAS","BAS_GAUCHE","GAUCHE"]}
{"kind":"consigne","t":12345.678,"compter_a_partir_de":12348.378,"cible":2,"nom":"DROITE","cycle":9,"frame":504}
{"kind":"consigne","t":12354.078,"compter_a_partir_de":12356.778,"cible":5,"nom":"GAUCHE","cycle":17,"frame":1008}
{"kind":"bilan","cycles":286,"frames":18018,"sautees":3,"cadence_s":1.0501,"derive":0.0001,
 "avertissement":null,"graine":874512}
```

- **`t` et `compter_a_partir_de` sont des `local_clock()`**, c'est-à-dire exactement le domaine des
  horodatages de `decoded_cvep` : le dépouillement devient une comparaison numérique, et rien d'autre.
- **Une ligne par CONSIGNE**, pas par cycle : ~36 lignes pour 5 min, et c'est toute la vérité-terrain.
  (Journaliser aussi les ~300 marqueurs de cycle est optionnel ; ça permettrait à un script de
  revérifier la cadence hors ligne, mais ce n'est pas nécessaire au verdict.)
- **La ligne `bilan` est le dictionnaire de `bilan_de_seance` recopié verbatim** — il existe déjà
  (`:291-292`), un seul `json.dumps(resume)` suffit, et il n'y a donc toujours qu'UNE source pour
  ce qui s'imprime et ce qui s'écrit, exactement l'argument que `:266-272` fait déjà valoir.

Coût : ~10 lignes (ouverture en `a`, trois `write`+`flush`, fermeture), plus une assertion `--smoke`
qui écrit dans `tempfile.mkdtemp()`, relit, et vérifie qu'il y a autant de lignes `consigne` que de
changements de consigne dans le `journal` — le même patron que les autres gardes du fichier.

**Côté récepteur (hors tranche, mais sans lui le journal ne sert à rien) :** `examples/receiver.py`
doit imprimer l'horodatage absolu, pas seulement l'âge. Une f-string :

```python
print(f"[t={ts + offset:.3f}  {age_ms:5.1f} ms old] {values}")
```

Idéalement, le même `--log` JSONL de l'autre côté (`{"t": ts+offset, "values": [...]}`), et le
« script de dépouillement » que T8 appelle de ses vœux devient trois lignes : charger les deux
fichiers, pour chaque `consigne` compter les échantillons dont `t ≥ compter_a_partir_de` et
`t < t_consigne_suivante`, tabuler `target_index` contre `cible`.

**À VÉRIFIER PAR EXÉCUTION** (après correctif) :
`python src/research/cvep_stimulus.py --smoke` — attendu VERDICT : OK, et une assertion de plus sur
le journal de fichier.

---

## IMPORTANT

### I1 — `research/__init__.py` documente `cvep_rcca` comme un décodeur d'exploration resté dans `research/` ; le décodeur rCCA vit dans `core/` et il EST publié

`src/research/__init__.py:22-27` (lignes AJOUTÉES par ce chantier)

Le texte livré dit :

> 2. **Les décodeurs des modes** — `cvep_rcca` seulement, désormais. […] `cvep_rcca` reste ici —
>    c'est la variante à CODES DISTINCTS (rCCA), jamais publiée, gardée en exploration

Trois affirmations, trois fois faux, vérifié fichier par fichier :

1. **`RCCADecoder` n'est plus ici.** Il vit dans `src/core/cvep_rcca.py` (52 Ko, dernier commit
   `0398913`), et `src/core/modes/cvep.py:106` l'importe : `from core.cvep_rcca import RCCADecoder`.
2. **Il EST publié.** `core/modes/cvep.py:123` : `_DECODEURS = {"eCCA": CVEPDecoder,
   "rCCA": RCCADecoder}` — le moteur instancie l'un ou l'autre selon ce que le FICHIER de modèle
   déclare. `docs/recette.md` § 2.9 dit d'ailleurs à l'opérateur que la calibration écrit
   **deux** modèles (`cvep_model_*.npz` ET `cvep_rcca_model_*.npz`) et que McNemar les déclare
   indiscernables. Le paquet `research` dit donc l'inverse de la recette, sur le même objet.
3. **Ce qui reste dans `research/cvep_rcca.py` n'est pas un décodeur.** Sa propre docstring
   (ligne 3-5) l'écrit : « Ce fichier ne contient plus le décodeur, ni la calibration. » Ce qui
   reste est la **fabrique de codes Gold** — l'hypothèse réfutée, donc la famille 4 (« analyses
   hors ligne »), pas la famille 2. La famille 2 est aujourd'hui **vide**.

Corollaire arithmétique : « cinq décodeurs vivent maintenant dans `core` » en compte désormais
**six** (`cvep_decoder`, `cvep_rcca`, `neuro_monitor`, `mi_decoder`, `p300_decoder`, `errp_decoder`).

**Scénario.** Un étudiant veut comprendre pourquoi le moteur décode parfois en rCCA. Il lit le
`__init__` du paquet — le fichier qui existe pour répondre à « où vit quoi » —, en conclut que le
rCCA est une exploration non publiée, ouvre `research/cvep_rcca.py`, n'y trouve aucun décodeur, et
soit abandonne, soit modifie la fabrique de codes Gold en croyant toucher au décodeur du moteur.
C'est exactement la confusion que la règle mémorisée du dépôt interdit (« quand un mode migre dans
le moteur, l'original se RETIRE, il ne se maintient pas »).

**Correctif minimal.** Réécrire les deux phrases :

```
2. **Les décodeurs des modes** — plus aucun, désormais. `cvep_code`, `cvep_decoder` et `cvep_rcca`
   ont fait le trajet vers `core` le 2026-08-20, comme `neuro_monitor` le 2026-07-27, `mi_decoder`
   (avec `mi_models`) le 2026-07-29, `p300_decoder` (avec `p300_models`) le 2026-08-17,
   `errp_decoder` (avec `errp_models`) le 2026-08-18 : les six décodeurs du produit vivent
   maintenant dans `core`. ⚠️ Le fichier `cvep_rcca.py` qui subsiste ICI n'est PAS un décodeur —
   c'est la fabrique de codes GOLD, la moitié RÉFUTÉE de l'hypothèse rCCA (voir sa docstring). Le
   décodeur rCCA, lui, est publié : `core/modes/cvep.py` l'instancie quand le fichier de modèle le
   déclare.
```

### I2 — `chk(etendue > C2_SECONDES)` a 16 % de marge de cadence, échoue franchement sur machine chargée, et repasse au vert plus bas : c'est un test instable

`src/research/cvep_stimulus.py:1043` (assertion), `:680-681` (les deux durées), `:915-917` (le passage C2)

**L'arithmétique.** C2 tourne `attente_moteur_s=0,8` puis `seconds=1,5`, soit ~2,3 s de boucle,
plafonnée par `clock.tick(int(60)+5)` = **65 fps**. Les marqueurs partent aux frames 0, 63, 126…
`etendue` doit dépasser 1,5 s :

| cadence soutenue | frames en 2,3 s | marqueurs | `etendue` | verdict |
|---|---|---|---|---|
| 65 fps (plafond) | 149 | 0, 63, 126 | 126/65 = **1,94 s** | OK |
| 55 fps | 126 | 0, 63, 126 | 2,29 s | OK (tout juste) |
| **50 fps** | 115 | 0, 63 | 63/50 = **1,26 s** | **ÉCHEC** |
| **45 fps** | 103 | 0, 63 | 1,40 s | **ÉCHEC** |
| 40 fps | 92 | 0, 63 | 1,58 s | OK (à nouveau !) |

La cadence minimale est `126 / 2,3 = 54,8 fps` contre un plafond de 65 : **15,7 % de marge**, sur un
test qui tourne en troisième position dans le même processus, sous `dummy`, sur Windows. Une pause
du ramasse-miettes ou une machine occupée suffisent. Et la bande de panne est **[42 ; 54,8) fps** :
en dessous de 42 fps l'assertion repasse au vert (`63/42 = 1,5`), ce qui la rend non monotone —
elle ne mesure pas ce qu'elle prétend mesurer, elle mesure un rapport entre deux durées de test.

C'est précisément le défaut que le commit `1995b22` (« Bound the seed-replay check in frames, so it
cannot flake ») vient de corriger sur C4/C5, et que `:929-935` documente longuement — il est resté
sur C2. Le commentaire `:1036-1040` a raison sur le fond (l'étendue, pas les trous), mais le seuil
choisi est une durée de test, pas une propriété de l'émetteur.

**Correctif minimal.** Observer la propriété littéralement plutôt que par une durée. `run()` a déjà
`note` dans son scope ; ajouter un paramètre `journal_chauffe=None` (même statut que `journal` et
`bilan`) et, dans `emet()` :

```python
if journal_chauffe is not None and note is not None:
    journal_chauffe.append(ts)
```

puis, en C2 :

```python
chk(len(chauffe_c2) >= 1 and len(journal2) > len(chauffe_c2),
    f"[C2] {len(chauffe_c2)} marqueur(s) sont partis PENDANT le bandeau de chauffe et "
    f"{len(journal2) - len(chauffe_c2)} après — le clignotement ne s'arrête pas pendant la "
    f"chauffe (le moteur les ENCAISSE, `CVEPRuntime.tick`)")
```

Indépendant de la cadence, mord exactement sur la mutation visée (tenir un écran statique pendant
la chauffe, à la mode `errp_stimulus.py`), et supprime la bande de panne.

**À VÉRIFIER PAR EXÉCUTION** : `python src/research/cvep_stimulus.py --smoke` cinq fois de suite,
attendu 5/5 OK — et pendant que la machine est chargée, ce que la version actuelle ne garantit pas.

### I3 — Le HUD affiche le refresh ANNONCÉ étiqueté « fps », et `sautees` ne compte que les intervalles trop LONGS : un écran plus rapide que l'annonce affiche « 60 fps | sautées 0 » pendant toute la séance

`src/research/cvep_stimulus.py:513-517` (le HUD), `:551-554` (le compteur), `:200` (`SEUIL_SAUT`)

```python
f"cycles {cycles}  |  {refresh:.0f} fps  |  sautées {sautees}  |  "
```

`refresh` est la valeur **publiée dans les marqueurs**, pas la cadence mesurée. Et
`(t_flip − t_flip_precedent) > SEUIL_SAUT / refresh` ne se déclenche que sur un intervalle **trop
long**. Les deux indicateurs sont donc structurellement aveugles au sens « écran plus rapide
qu'annoncé » — qui est exactement la **seconde panne muette** que la docstring du module nomme
(`:31-32`, point 2) et que `diagnostic_cadence` existe pour attraper.

**Scénario concret, et il est déjà décrit dans le fichier** (`:242-244`) : `--refresh 60` sur une
machine dont la boucle n'est pas bloquée par le balayage (repli sans vsync, cf. M2). `clock.tick(65)`
impose 65 fps ; les intervalles font 15,4 ms, le seuil est `1,5/60 = 25 ms` → **zéro sautée**. Le HUD
affiche « 60 fps | sautées 0 » pendant les 5 minutes, l'indicateur d'écoute dit « moteur À
L'ÉCOUTE », l'écran est parfait — et la phase glisse de 5 frames par cycle. L'opérateur ne
l'apprend qu'à la **ligne de bilan, après coup**, quand la séance est déjà perdue : le 2.9 dit alors
« la séance est à refaire ».

Le fichier écrit lui-même (`:510-511`) que l'indicateur d'écoute est « la seule chose de cet écran
qui distingue "ça marche" de "ça a l'air de marcher" ». C'est vrai, et c'est le problème : la
seconde panne muette n'a, elle, aucun signal live.

**Correctif minimal** — réutiliser la fonction qui existe déjà, sur les derniers `onsets` :

```python
# juste après `onsets.append(ts)` :
if len(onsets) > 1:
    cadence_live = statistics.median(b - a for a, b in zip(onsets[-6:], onsets[-5:]))
    _d, alerte_cadence = diagnostic_cadence(cadence_live, L / refresh, refresh, L)
```

et dans le HUD :

```python
f"cycles {cycles}  |  {refresh:.0f} Hz annoncés"
+ ("" if cadence_live is None else f" / {L / cadence_live:.0f} mesurés")
+ ("" if alerte_cadence is None else "  ⚠️ CADENCE")
+ f"  |  sautées {sautees}  |  ..."
```

Deux nombres au lieu d'un, l'étiquette honnête (« Hz annoncés », pas « fps »), et le même verdict
que le bilan de fin — mais pendant la séance, pas après.

### I4 — `ATTENTE_MOTEUR_S` est re-dérivé de `SSVEP_WARMUP_S` alors que deux docstrings affirment qu'il est LU dans `SPEC.rest`, et rien ne l'arrime

`src/research/cvep_stimulus.py:190-194` (la constante), `:64-66` (docstring du module)

```python
# Valeurs LUES dans `core/modes/cvep.py` (SPEC.rest) : `warmup_s=SSVEP_WARMUP_S`, `duration_s=0.0`
ATTENTE_MOTEUR_S = SSVEP_WARMUP_S + 0.0
```

et, dans la docstring du module : « La durée est **LUE** dans `core/modes/cvep.py` (`SPEC.rest`),
pas devinée ». C'est faux : la valeur est **recopiée depuis `core.config.SSVEP_WARMUP_S`**, et le
`+ 0.0` est un littéral, pas `SPEC.rest.duration_s`. La valeur est correcte aujourd'hui
(`core/modes/cvep.py:727-733` : `Rest(warmup_s=SSVEP_WARMUP_S, duration_s=0.0)`), mais rien ne
l'y attache.

**Ce qui la ferait diverger en silence** : donner au c-VEP un plancher de repos propre
(`duration_s=5.0`) ou une chauffe propre (`warmup_s=CVEP_WARMUP_S`) — le geste naturel le jour où
on mesurera un plancher. L'émetteur continuerait d'annoncer « le moteur chauffe ~15 s », le bandeau
tomberait 5 s trop tôt, et **`--seconds` commencerait son décompte pendant que le moteur ne décode
pas encore** : la séance rendrait moins de stimulation décodable que demandé, sans un mot.

C'est le seul des trois nombres empruntés au moteur qui ne soit pas arrimé : `PERIODE_MOTEUR_S` et
`TRANSITION_S` le sont explicitement (`:799-808`), avec la bonne justification en commentaire
(« recopiées ici, elles dériveraient en silence »).

**Correctif minimal** — deux gestes, aucun import lourd ajouté au chemin de la séance
(`core.modes.cvep` tire numpy et les quatre décodeurs ; `_smoke` l'importe déjà, `run()` non) :

1. corriger les deux docstrings : « recopiée ici, ARRIMÉE à `SPEC.rest` par `--smoke` » ;
2. ajouter l'assertion manquante, juste à côté des deux autres (`:799`) :

```python
chk(abs(ATTENTE_MOTEUR_S - (mode_cvep.SPEC.rest.warmup_s + mode_cvep.SPEC.rest.duration_s)) < 1e-9,
    f"l'attente annoncée ({ATTENTE_MOTEUR_S:g} s) est bien la chauffe + le repos de "
    f"`core/modes/cvep.py` SPEC.rest ({mode_cvep.SPEC.rest.warmup_s:g} + "
    f"{mode_cvep.SPEC.rest.duration_s:g})")
```

---

## MINOR

### M1 — `--seed` promet à l'étudiant un rejeu que seul `max_frames` garantit, et `max_frames` n'est pas exposé

`:1143-1145` (l'aide de `--seed`), `:332-337` et `:472-479` (la justification), `:929-935`

L'aide dit « rejoue exactement la même séquence de cibles ». Le fichier lui-même établit le
contraire pour une séance bornée en TEMPS : « deux exécutions bornées par le temps ne s'arrêtent pas
forcément sur la même image, donc la seconde peut avoir une consigne de plus. Mesuré par la revue :
1 exécution sur ~8 ». Le smoke a dû border C4/C5 en **images** pour cette raison précise — mais
`--seconds` reste la seule borne de la CLI. Le rejeu réel est donc « même préfixe, longueur
possiblement différente d'une consigne », ce que l'aide ne dit pas.

L'impact est faible (le préfixe est identique, et chaque consigne est de toute façon horodatée), mais
c'est un écart entre ce que le test prouve et ce que la CLI promet.

**Correctif minimal** : une demi-phrase dans l'aide (« la SÉQUENCE est identique ; sa LONGUEUR peut
différer d'une consigne selon la charge machine — borne en images si tu veux l'égalité stricte »).
Exposer `--frames` serait mieux mais dépasse le « minimal ».

### M2 — Le repli sans vsync est silencieux

`:374-377`

```python
try:
    win = pygame.display.set_mode(size, flags, vsync=1)
except (TypeError, pygame.error):
    win = pygame.display.set_mode(size, flags)
```

Aucun message. Or `:370-373` explique que sans vsync « la phase reconstruite est fausse dès la
deuxième frame, sans qu'aucune exception ne le signale ». Le chemin auto-mesuré s'en sort par
accident (sans vsync, `measure_refresh` mesure une cadence libre et snappe haut, le moteur refuse
alors bruyamment les marqueurs) ; avec `--refresh 60` explicite, personne ne dit rien avant la fin
de la séance. À noter aussi que SDL peut **accorder** `vsync=1` sans l'honorer : le `try/except`
n'est pas une preuve.

**Correctif minimal** : un `print("[cvep-stim] ⚠️ vsync REFUSÉ par le pilote — la cadence n'est plus
verrouillée au balayage ; lis la ligne de cadence en fin de séance")` dans le `except`.

### M3 — L'assertion « pendant » resterait verte si l'écart valait 0 partout

`:751`

`chk(bool(pendant) and max(pendant) <= 1, …)` passe aussi bien avec `max == 0` qu'avec `max == 1`.
Une mutation qui rendrait l'émetteur magiquement immunisé aux frames sautées ne rougirait pas ici
(elle rougirait ailleurs, ce qui limite les dégâts). Une assertion `max(pendant) == 1` dirait ce que
le commentaire annonce (« l'émetteur a une image de retard sur l'horloge murale, et c'est tout »).

### M4 — La transition imprimée est figée sur `CVEP_VOTE_LEN` de config, alors que `vote_len` est un réglage de la console

`:405`, `:487` — `transition_s = CVEP_DECISION_CYCLES * L / refresh + CVEP_VOTE_LEN * PERIODE_MOTEUR_S`

`vote_len` est un `Param` du mode (`core/modes/cvep.py:713-718`, `min=1 max=15`). Un opérateur qui
le passe de 3 à 8 dans la console allonge la transition de 0,6 s à 1,6 s ; l'émetteur, qui ne peut
pas le savoir, continue d'imprimer « compter à partir de t + 2,7 » — trop tôt d'une seconde, donc
5 échantillons contaminés comptés par consigne.

**Correctif minimal** : une incise dans la ligne imprimée `:406-411` — « (calculé pour le réglage par
défaut `vote_len=3` ; si tu le changes dans la console, ajoute
`(nouveau − 3) × 0,2 s` ) ».

### M5 — Le `print` de consigne est DANS l'intervalle que `sautees` mesure

`:548-550` puis `:551`

L'ordre est `flip → emet → print(...) → t_flip = perf_counter()`. Le coût du `print` (console
Windows, UTF-8, guillemets français) tombe donc dans l'intervalle mesuré. S'il dépasse ~25 ms —
plausible quand la console défile ou qu'elle est redirigée —, une **fausse frame sautée** est
comptée à chaque changement de consigne, soit ~36 sur une séance de 5 min. Sans gravité pour le
décodage (le compteur est affiché, jamais corrigé), mais il pollue le seul indicateur qui doit
rester crédible.

**Correctif minimal** : prendre `t_flip = time.perf_counter()` **immédiatement** après
`pygame.display.flip()`, avant le bloc marqueur, et déplacer la comparaison plus bas (elle n'utilise
que `t_flip` et `t_flip_precedent`).

### M6 — La saccade vers la nouvelle consigne n'est pas comptée dans la transition (et c'est compensé par hasard) — à écrire

`:183` (`TRANSITION_S`), `:160-181` (le raisonnement)

Le calcul compte les deux mémoires du moteur, pas la troisième : l'utilisateur. La consigne apparaît
à `t` et le regard ne s'y pose qu'à `t + 0,2…0,3 s` ; toute fenêtre finissant avant
`t + 0,3 + 2,1` contient encore de l'ancienne fixation. Symétriquement, la contribution stricte du
vote est `(vote_len − 1) × period_s = 0,4 s` et non `0,6 s` (le deque tient `t`, `t−0,2`, `t−0,4`),
donc le fichier jette déjà **0,2 s de trop**. Net : le « compter à partir de » est optimiste
d'environ 0,1 s, soit un demi-échantillon à 5 Hz. Négligeable — mais le raisonnement mérite d'être
écrit, parce qu'il défend le 2,7 s au lieu de le laisser paraître arbitraire, et parce que
quelqu'un qui « corrigerait » le 0,6 s en 0,4 s ferait apparaître le biais de saccade.

**Correctif minimal** : deux phrases dans le commentaire de `TRANSITION_S`.

---

## Contraintes globales — état

| contrainte | état |
|---|---|
| `research/` → `core/`, jamais l'inverse | ✅ `core.config`, `core.cvep_code`, et `core.modes.cvep` dans `_smoke` seulement |
| français dans le code, commits en anglais | ✅ |
| testable sans casque | ✅ aucun BrainFlow, `SDL_VIDEODRIVER=dummy` |
| aucun test n'écrit dans le vrai `data/` | ✅ `tempfile.mkdtemp` + `finally` + `rmtree` |
| autotest sort en 1 | ✅ `:1160` |
| documentation exécutable pour étudiants | ⚠️ I1 (le paquet dit le contraire de la recette), I4 (docstring fausse) |
