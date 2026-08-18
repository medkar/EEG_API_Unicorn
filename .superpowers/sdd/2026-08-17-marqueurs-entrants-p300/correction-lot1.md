# LOT 1 — l'oreille et le moteur : rapport de correction

**Périmètre :** `src/core/markers.py`, `src/core/server.py`, `src/core/config.py`.
Rien d'autre n'a été touché. La docstring d'en-tête de `server.py` (lot 3) est intacte.

**Statut : TERMINÉ.** 4 critiques, 9 importants, 5 mineurs traités. Tous les tests verts.

---

## 1. La forme du correctif : un inlet n'est jamais valide pour toujours

Les critiques 1.1, 1.2, 1.4 et l'important 1.5 sont bien une seule maladie. Ils ne sont pas
corrigés comme quatre bugs : `MarkerInlet` a reçu **un cycle de vie**, et les quatre tombent avec.

| Geste | Ce qu'il règle |
|---|---|
| `resolve()` construit dans des variables LOCALES, n'affecte `self.inlet`/`self.offset` qu'à la dernière ligne, ne lève jamais, garde la raison du refus dans `self.refus` | **1.2** |
| `open_stream(timeout=…)` **et** `time_correction(timeout=TIME_CORRECTION_TIMEOUT_S=2.0)` | **1.1** |
| `StreamInlet(..., recover=False)` : la disparition d'un émetteur devient un ÉVÉNEMENT (`LostError`) au lieu d'un silence | **1.4**, **1.5** |
| `lache(raison)` : referme, remet `inlet=None` **et `offset=0.0`**, dit pourquoi | **1.4**, **1.5** |
| `pull()` lâche l'inlet AVANT de relancer l'exception | **1.4**, **1.5** |
| `EngineServer._libere_marker_inlet()` appelée par `_stop_mode` (dernier écouteur arrêté) et par le `finally` de `run()` | **1.4**, **1.6** |

Le point de bascule est `recover=False`. Mesuré avant d'écrire une ligne (sonde à deux
processus, noms de flux `lot1probe_*`) :

```
=== recover=True (le défaut, l'ancien code) ===
  [B] émetteur #1 vivant : 43 marqueurs (err=None)
  [C] émetteur #1 TUÉ    : 0 marqueurs, err=None        <-- aucune exception
  [D] émetteur #2 RELANCÉ, MÊME inlet : 0 marqueurs, err=None   <-- MUET POUR TOUJOURS
  [F] inlet NEUF sur le flux #2 : 13 marqueurs          <-- le flux était pourtant bien là
=== recover=False ===
  [C] émetteur #1 TUÉ    : 0 marqueurs, err=LostError: the stream has been lost.
  [F] inlet NEUF sur le flux #2 : 51 marqueurs, err=None
```

---

## 2. Preuves ROUGE → VERT

### 2.1 — Critique 1.4 (émetteur relancé)

Prouvé **dans un seul processus**, et ce n'est pas un raccourci : j'ai d'abord vérifié en sonde
que détruire le `StreamOutlet` côté Python produit exactement le même `LostError` et le même
enchaînement B/C/D/E/F que tuer un vrai processus émetteur. Nouveau sous-test
`_smoke_marqueurs_relance`. Trois mutations, une par cause nommée dans la revue.

**Mutation a — `recover=False` → `recover=True` :**
```
  OK   le moteur se connecte au premier émetteur
  OK   ...et ses marqueurs arrivent ([(1903942.96, {...'target': 1})])
  ÉCHEC l'émetteur disparu, l'inlet redevient NON CONNECTÉ — ...
  ÉCHEC ...et l'incident est COMPTÉ, pas avalé (0)
  ÉCHEC ...et les marqueurs du NOUVEL émetteur arrivent vraiment ([])
[smoke-marqueurs-relance] VERDICT : PROBLÈME          (EXIT=1)
```
Le `(0)` est mot pour mot le constat de la revue : « aucune exception, `marqueurs_inlet_erreurs`
reste 0 ».

**Mutation b — `pull()` ne lâche plus l'inlet sur `LostError` :**
```
  ÉCHEC l'émetteur disparu, l'inlet redevient NON CONNECTÉ — ...
  OK   ...et l'incident est COMPTÉ, pas avalé (396)
  ÉCHEC ...et les marqueurs du NOUVEL émetteur arrivent vraiment ([])
[smoke-marqueurs-relance] VERDICT : PROBLÈME          (EXIT=1)
```
Les **396 exceptions en 20 s** reproduisent la mesure de l'important 1.5 (310 en 20 s).

**Mutation c — `_stop_mode` ne libère plus l'inlet :**
```
  ÉCHEC arrêter le DERNIER écouteur libère l'inlet — ...
  ÉCHEC ...et le tampon de marqueurs part avec lui ([(1.0, {...'target': 0})])
[smoke-marqueurs-relance] VERDICT : PROBLÈME          (EXIT=1)
```

**VERT après restauration :** les 12 assertions OK, `VERDICT : OK`, `EXIT=0`.

> ⚠️ Honnêteté sur la couverture : sous la mutation *a*, l'assertion « le moteur se RECONNECTE »
> passe **à vide** (avec `recover=True` l'inlet ne se déconnecte jamais, donc `connecte` reste
> vrai). C'est l'assertion suivante — « les marqueurs du NOUVEL émetteur arrivent vraiment » —
> qui ferme réellement le trou. Idem sous la mutation *c* pour « redémarrer en ouvre un NEUF ».
> Ce que ce test ne couvre PAS : la mort BRUTALE d'un processus émetteur (Ctrl-C, plantage), où
> c'est le système qui ferme les sockets. La sonde à deux processus montre le même comportement,
> mais elle n'est pas rejouée dans le smoke.

### 2.2 — Important 1.7 (alignement `recent` / `recent_ts`)

Mutation demandée : `np.concatenate([self.recent_ts, ts_lsl + 1.0 / self.acq.fs])`.

```
  OK   les deux tampons ont la même longueur (749 et 749)
  OK   et ils ne sont pas vides après 3 s d'acquisition
  OK   le temps avance strictement, sans doublon ni retour en arrière
  OK   et la cadence médiane vaut ~1/fs (4.00 ms attendu 4.00 ms)
  OK   la QUEUE de `recent` est exactement le dernier bloc lu, valeur pour valeur (13 échantillons)
  ÉCHEC ...et la queue de `recent_ts` est exactement les horodatages de CE bloc — ...
        (écart max 4.0000 ms)
[smoke-tampon] VERDICT : PROBLÈME
```
Les **quatre assertions préexistantes restent vertes** sous la mutation : la démonstration que le
contrôle de longueurs ne pouvait pas l'attraper. L'écart mesuré vaut 4,0000 ms = exactement
1/250 s, un échantillon.

**VERT :** `écart max 0.0000 ms`, `VERDICT : OK`, `EXIT=0`.

### 2.3 — Important 1.8 (`_smoke_dimensionnement` ne pouvait pas échouer)

Mutation demandée : retirer le terme « époque de marqueur » du `max()` de `keep`.

```
  OK   keep=1250 couvre l'époque du marqueur (0.95 s) plus le retard toléré (1 s) = 488 échantillons
  OK   au moins un mode déclare une époque de marqueur (0.95 s) — ...
  ÉCHEC un mode déclarant une époque de 30 s force keep=1250 >= 7750 — ...
[smoke-dimensionnement] VERDICT : PROBLÈME            (EXIT=1)
```
Le terme a **entièrement disparu** du code et les deux assertions d'origine restent vertes : le
constat de la revue est exact au mot près.

**VERT :** `keep=8000 >= 7750`, `VERDICT : OK`, `EXIT=0`.

---

## 3. Le reste du lot

**1.3 — deux émetteurs du même nom.** Motif de la maison appliqué (`lsl_io.py:463`,
`server.py:_resolve_own`) : `resolve_byprop(minimum=32)` en **passes courtes répétées**
(`RESOLVE_PASSE_S = 0.2`), tri déterministe par `(source_id, hostname)`, et message nommant tous
les homonymes + celui qui est retenu, dit **une fois par changement** et non à 20 Hz. Mesuré :
`minimum=32, timeout=0.2` révèle bien les deux flux en 0,2 s là où `minimum=1, timeout=0.2` n'en
rend qu'un. Testé dans `markers.py` (4 assertions, dont le déterminisme du choix).

**1.6 — `_purge_marqueurs` sans écouteur.** `if not ecouteurs: return` → jette tout (« ce que TOUS
les écouteurs ont dépassé : sans écouteur, tout l'est ») **et le dit**.

**1.9** — `srv2.active = {}` en fin de `_smoke_marqueurs_inlet`, avec le commentaire du destructeur
zombie du 2026-07-28.

**1.10** — les 7 `EngineServer` sans `instance=` en ont un, distinct :
`smoke-dimensionnement`, `smoke-tampon`, `smoke-marqueurs`, `smoke-marqueurs-file`,
`smoke-marqueurs-inlet-2`, `smoke-marqueurs-stream-in`, `smoke-marqueurs-stream-in-2`.
Le moteur de 3 s de `_smoke_tampon_horodate` ne publie donc plus sous le `source_id` d'une vraie
console synthétique.

**1.11 — les compteurs sont enfin lus.** `_state()` (donc `snapshot()` ET le flux `status`) porte
`marqueurs: {perdus, futurs, illisibles, inlet_erreurs, connecte}`. `illisibles` est une
**propriété** qui cumule les inlets déjà fermés, sinon une relance d'émetteur remettrait le
compteur à zéro précisément quand il devient intéressant. En plus : `_dit_compteurs_marqueurs`
imprime **une fois par seuil franchi** (1, 10, 100, 1000, 10000). Vérifié aussi que ces compteurs
n'entrent PAS dans `_status_key` — sinon la déduplication du flux `status` tombe (les 19,6 Hz).

**1.12** — `m[1].get("target")` aux 3 endroits.

**1.13** — les deux chemins de résolution passent par `_resout_marker_inlet`, donc le message suit
l'ÉVÉNEMENT et non le chemin : « connecté à … » s'imprime quel que soit l'appel qui réussit, et
« pas encore là » une seule fois (il portait 20 messages/s de potentiel).

**Mineurs :** `except Exception` dans `parse_marqueur` · intermittence de l'autotest corrigée (il
attend maintenant les **trois** marqueurs, `illisibles >= 1` compris, au lieu de vérifier
`illisibles == 1` avec le 3e encore en vol) · `MARKER_LATE_S` documenté pour ses **deux** emplois
(retard *et* futur, une constante symétrique assumée) · `max(0, v - coupe)` dans la réindexation
des curseurs · **frontières exactes** des trois comparaisons de `markers_murs` testées (pile à la
tolérance de futur, pile sur le plus vieil échantillon, époque finissant pile sur le dernier).

---

## 4. Mesures qui ont changé le correctif

**Borner `time_correction` à 0,2 s aurait CASSÉ la connexion.** Sur un émetteur **vivant**, le
premier appel d'un inlet neuf coûte 0,44 à 0,64 s (l'échange de synchronisation doit avoir lieu) ;
les suivants 0,000 s. `timeout=0.2` lève `TimeoutError` sur un émetteur parfaitement sain. D'où
**2,0 s** : 3-4× la marge mesurée, pire cas borné à 2 s.

**`open_stream()` était NON BORNÉ lui aussi, et la revue ne l'a pas relevé.** Émetteur résolu puis
tué, les quatre combinaisons :

| `recover` | timeout | blocage de la boucle |
|---|---|---|
| `True` (ancien) | aucun (ancien) | **> 400 s, mesure interrompue** (la revue citait 26 s) |
| `True` | 2,0 s | 2,00 s (`TimeoutError`) |
| `False` | aucun | 2,01 s (`LostError`) |
| `False` (nouveau) | 2,0 s (nouveau) | 2,00 s (`TimeoutError`) |

Les deux moitiés du correctif bornent le gel indépendamment ; ensemble elles se doublent.

**`minimum=32, timeout=0.0` marche à froid.** Les 5 premiers appels d'un processus neuf rendent 0
flux (c'est le constat 1.13, reproduit), puis le cache du résolveur répond en 0,002 s — la boucle
du moteur garde donc son `timeout_s=0.0` sans rien payer.

---

## 5. Comptage des assertions (méthode : appels `chk(` **moins** les lignes `def chk(`)

| fichier | avant | après |
|---|---|---|
| `src/core/markers.py` | 22 | **40** |
| `src/core/server.py` | 91 | **116** |
| `src/core/config.py` | 10 | **10** |
| **total** | **123** | **166** |

**Aucune assertion préexistante n'a été retirée ni affaiblie** — vérifié par un contrôle
automatique (AST : extraction de tous les appels `chk`, normalisation des blancs, inclusion de
l'ancien ensemble dans le nouveau) : `DISPARUES 0` sur les trois fichiers. La seule réécriture
d'une assertion existante est `m[1]["target"]` → `m[1].get("target")` (constat 1.12), neutralisée
dans la comparaison.

---

## 6. Tests

Aucun moteur ne tournait (`Get-Process python` vérifié avant chaque lancement, 0 processus). Les
sondes publient sous `lot1probe_*`, aucun processus laissé derrière.

| commande | verdict |
|---|---|
| `python src/core/markers.py` (×3) | `OK` / `OK` / `OK`, EXIT=0, 40 assertions à chaque fois |
| `python src/core/server.py --smoke` | 17 sous-tests, tous `OK`, 0 `ÉCHEC`, EXIT=0 |
| `python src/core/modes/p300.py` | `OK`, EXIT=0 |
| `python src/console/app.py --smoke` | `OK`, EXIT=0 |

Et les cinq gardes MI (touchées indirectement, `server.py` + `config.py` ayant bougé) :
`acquisition.py --synthetic`, `modes/mi.py`, `mi_models.py`, `modes/calibration.py`,
`modes/mi_calib.py` — tous EXIT=0, tous `VERDICT : OK`.

---

## 7. Mes inquiétudes

**a) Deux textes des lots 2 et 3 sont désormais FAUX à cause de ma correction — je ne les ai pas
touchés.** Le correctif 1.4 (libérer l'inlet au dernier écouteur arrêté) **lève** une contrainte
que ces deux textes énoncent :

- `src/core/modes/p300.py:355-360` (aide du réglage `stream_in`) : « Le changer plus tard n'a
  AUCUN effet tant que le moteur lui-même tourne encore, **pas même en redémarrant ce mode** ».
- `docs/markers.md` : « Changing it later means restarting the engine, not just the mode. »

Vérifié en mesure : arrêter puis redémarrer le mode reprend bien le nouveau nom
(`flux_A` → arrêt → `flux_B`). **À corriger par les lots 2 et 3** : redémarrer le MODE suffit
désormais. J'ai mis à jour la docstring de `_ouvre_marker_inlet` (mon lot) en conséquence.

**b) Le budget de diff est dépassé.** ~850 lignes sur mes trois fichiers, au-delà des ~40 Ko
visés. La cause est assumée mais réelle : chaque panne mesurée a été écrite dans le code (la
règle du projet), et le nouveau `_smoke_marqueurs_relance` fait 130 lignes à lui seul. Une
relecture ciblée sur `markers.py` (le cœur) plutôt que sur les smokes serait le meilleur usage du
temps de relecture.

**c) `_smoke_marqueurs_relance` coûte du temps de mur et touche le réseau.** Il attend une vraie
détection de `LostError` (bornée à 20 s, observée en ~2 s) et publie sous
`EEG_API_Unicorn_smoke_relance`. Si un jour deux smokes tournent en parallèle sur le même réseau,
ce nom devient un contrat partagé comme les autres. Aujourd'hui la règle « un seul programme à la
fois » le protège.

**d) `LostError` n'est pas réexporté par `pylsl` au niveau du paquet** (1.18.2 : il vit dans
`pylsl.util`). L'import a un repli sur `RuntimeError`, qui est un **surensemble** — on lâcherait
l'inlet un peu trop souvent, jamais trop peu. C'est le bon sens de dégradation, mais c'est une
dépendance sur un chemin d'import non public : si une version future déplace `util`, le repli
s'active silencieusement et le comportement reste correct, seulement moins fin.

**e) Ce qui reste NON vérifié au casque.** Rien de ce lot n'a été essayé sur du matériel réel ni
avec un vrai émetteur P300 sur une seconde machine. En particulier : le
`time_correction` de 2,0 s a été mesuré **en local** (offset ~0) — sur deux machines, l'échange de
synchronisation peut être plus lent, et 2,0 s pourrait devenir juste. Le symptôme serait bruyant
(« pas encore là » qui persiste alors que l'émetteur tourne), pas silencieux, mais c'est le
premier chiffre à re-mesurer en salle.
