# Marqueurs entrants — le moteur écoute une application externe, et le P300 sort sur le réseau

**Date** : 2026-08-17 · **État** : conception validée, prête pour le plan d'implémentation

## 1. Le but, en une phrase

Le moteur doit pouvoir **recevoir** des marqueurs horodatés d'une application externe — l'onset de
chaque flash P300 — pour épocher l'EEG dessus, décoder, et republier une **intention neutre**.

C'est le dernier chantier nommé par la spec (§12.1, « control plane », figé le 2026-07-24 et jamais
implémenté). Il fait passer le moteur de **3 modes publiés sur 6 à 4 sur 6**.

## 2. Ce qui est dedans, et surtout ce qui reste dehors

**Dedans** : le tuyau des marqueurs entrants (générique) · le P300 déménagé dans `core/` avec son
runtime et son flux · le contrat public de ce qu'une application doit envoyer · un émetteur de
stimulus autonome qui montre le geste exact · la calibration pygame **recâblée** pour survivre au
déménagement du décodeur.

**Dehors, et il faut le dire en livrant** :

- **Le control plane** (`EEG_API_Unicorn_control`, commandes JSON entrantes pour piloter le moteur à
  distance). Ça partage le mot « marqueurs » et rien d'autre : aucune contrainte de timing, et ça ne
  débloque aucun mode. Chantier séparé.
- **L'ErrP.** Il réutilisera ce même tuyau sans rien redécouvrir, mais il coûte son décodeur
  déménagé, son runtime, son contrat d'événement et ses tests. Il traîne en plus une dette propre :
  **sa calibration réelle n'a jamais été faite**, donc ses verdicts ne sont pas encore fiables.
- **La calibration P300 jouée par le moteur** (évolution F2 de la spec, §13). Elle reste dans
  l'appli pygame, qui la joue déjà et bien. Conséquence à assumer : **le mode P300 exige un modèle
  entraîné**, exactement comme le MI — un étudiant calibre en pygame, puis le moteur décode sur le
  réseau.
- **L'arrêt dynamique** (`P300_STOP_MARGIN`, `P300_MIN_REPS` existent dans la config). Le c-VEP a
  déjà réfuté l'arrêt dynamique sur ce matériel : SNR-limité. On ne le rouvre pas ici.

## 3. Trois décisions structurelles, à ne pas rouvrir

**(1) Le tuyau est générique, le P300 n'en est que le premier client.** L'ErrP arrive derrière avec
le même besoin d'alignement d'horloges. Une deuxième implémentation du même alignement divergerait
de la première — c'est une dette qu'on paie deux fois. Le moteur livre des marqueurs *situés* et
*mûrs* ; le découpage en époques reste au décodeur, qui sait déjà le faire.

**(2) Le flux entrant se résout par son NOM, jamais par son type.** Le flux `EEG_API_Unicorn_status`
que le moteur publie est lui-même de type `Markers` : une résolution par type ferait **écouter le
moteur à lui-même**. Le nom est un réglage du mode, pour qu'un étudiant puisse pointer vers le sien.

**(3) `round_end` est explicite, envoyé par l'application.** Le moteur ne le déduit pas. Déduire
imposerait de recompter les répétitions côté moteur, qui divergerait de l'application le jour où
elle change son protocole — et ce jour arrive toujours.

## 4. Architecture

### 4.1 `MarkerInlet` — recevoir

Nouveau module `src/core/markers.py`. Il résout un `StreamInlet` par nom, tire les marqueurs sans
bloquer, et **applique `time_correction()` à chaque horodatage**.

⚠️ `time_correction()` n'est pas une précaution théorique : `local_clock()` compte depuis le
démarrage de **chaque** machine, et le projet a mesuré **45 jours** d'écart entre deux postes. Sans
correction, tous les marqueurs distants tombent hors du tampon et le mode ne décode jamais rien.

### 4.2 Le tampon EEG gagne ses horodatages

C'est l'ajout central, et rien ne marche sans lui. Aujourd'hui
[`server.py:854`](../../../src/core/server.py#L854) empile **les valeurs seules** :

```python
self.recent = np.vstack([self.recent, eeg])[-self.keep:]
```

On ne peut donc pas *situer* un marqueur dans le tampon. Il faut un tampon d'horodatages parallèle,
tenu exactement en phase avec `self.recent` — même longueur, même troncature.

**Une seule base de temps, et c'est LSL.** Le moteur vit déjà en temps LSL : il publie avec
`self.clock.to_lsl(...)` et passe `lsl_ts` à chaque `runtime.tick`. Les marqueurs entrants arrivent
en temps LSL corrigé. Mélanger deux bases ici produirait un décalage constant, silencieux, et
indiscernable d'un mauvais contact d'électrode.

### 4.3 Le dimensionnement de `keep`, rendu explicite

Une époque P300 est `[-P300_PRE_S, +P300_EPOCH_S]` = `[-0,15 s, +0,80 s]` = **0,95 s**. Un marqueur
peut de plus arriver en retard : on déclare une tolérance **`MARKER_LATE_S = 1.0`**, nouvelle
constante de `src/core/config.py` — au même endroit que les autres constantes de protocole, pas en
dur dans le moteur.

Le tampon doit donc couvrir **1,95 s** de rétrospective. Les 2 s actuelles suffisent — par accident,
et c'est précisément le problème : elles viennent de `QUALITY_WINDOW_S` et `MI_WINDOW_S`, que
personne ne pense à protéger. `keep` doit porter le besoin du P300 **nommément**, sinon quelqu'un
baissera un jour une constante sans rapport et tronquera toutes les époques **en silence**.

⚠️ Cette règle **complète sans le contredire** l'avertissement de
[`server.py:136-143`](../../../src/core/server.py#L136-L143) : l'`epoch_s` d'une calibration
**native** ne doit dimensionner aucun tampon, puisque le moteur ne joue jamais ces calibrations.
Ça reste vrai. C'est l'époque du **runtime**, une autre chose, qui doit compter ici.

### 4.4 La file des marqueurs mûrs

Un marqueur n'est pas exploitable à son arrivée : il faut attendre que le tampon couvre sa fenêtre
**post-stimulus**, soit 0,80 s après lui. Cette attente est générique — elle appartient au moteur,
pas à chaque mode, sinon chaque mode la réimplémentera à sa façon.

Le moteur tient donc une file de marqueurs en attente et n'expose que ceux dont l'époque est
entièrement couverte. Un marqueur trop vieux pour le tampon est **compté et annoncé**, jamais jeté
en silence.

### 4.5 Le contrat de mode

`ModeRuntime` gagne un point d'extension pour consommer les marqueurs mûrs, sur le modèle du
`channels()` ajouté au chantier précédent. Chaque mode époque avec ses propres bornes :
`epoch_from_stream` existe déjà, est validé au casque, et prend `(eeg, ts, flash_ts, fs, pre_s,
post_s)` — exactement ce que le moteur saura fournir.

## 5. Le contrat public des marqueurs entrants

Il devient **public au même titre que les noms de flux** : le changer casserait le code des
étudiants. Du JSON dans un flux de marqueurs LSL, comme le flux `status` que le moteur publie déjà.
Verbeux à dessein — un étudiant qui lit le flux dans un terminal doit comprendre sans documentation.

```json
{"mode": "p300", "event": "flash", "target": 3}
{"mode": "p300", "event": "round_end"}
```

Le champ `mode` sert dès l'ErrP : un même flux portera les deux sortes d'événements. Un runtime
**ignore silencieusement** les marqueurs dont le `mode` n'est pas le sien — c'est le seul rejet muet
autorisé, parce qu'il est normal et attendu. Les champs inconnus sont eux aussi ignorés : c'est ce
qui permettra d'enrichir le protocole sans casser les émetteurs existants.

**`target` est un indice à partir de 0**, dans `[0, P300_N_TARGETS[` — donc `0..5` avec la valeur
figée `P300_N_TARGETS = 6`. La valeur `-1` est réservée à la sortie (« pas de décision ») et n'a
aucun sens en entrée : un `target` négatif est refusé comme hors plage.

⚠️ **Le point sur lequel tout se joue n'est pas dans la charge utile : c'est l'horodatage du
marqueur.** L'application doit pousser le marqueur **à l'instant du flash**, l'horodatage pris juste
après le basculement de frame :

```python
outlet.push_sample([charge], timestamp=local_clock())   # JUSTE APRÈS le flip
```

Une charge utile parfaite envoyée 40 ms trop tard décale toutes les époques d'une frame. C'est la
première chose que dit la doc, et l'émetteur d'exemple montre le geste exact.

## 6. Ce que le moteur publie en retour

`EEG_API_Unicorn_decoded_p300`, une **intention neutre** comme tous les autres modes — jamais une
commande d'actionneur :

```json
{"target_index": 3, "confidence": 0.82, "scores": [...], "n_flashes": 48}
```

⚠️ `target_index = -1` signifie **« pas de décision »**, jamais « la cible 0 » ni « repos ». C'est
mot pour mot la confusion qu'on a dû inscrire en garde pour le MI, et elle se reproduira chez le
premier client qui lira ce flux sans lire la doc.

## 7. Le P300 déménage dans `core/` — et le piège qui a tué les modèles MI

`src/research/p300_decoder.py` → `src/core/p300_decoder.py`. Ses constantes vivent **déjà** dans
`core/config.py` (`P300_BAND`, `P300_PRE_S`, `P300_EPOCH_S`, `P300_XDAWN_NFILTER`, `P300_N_TARGETS`,
`P300_REPS`) : rien à déplacer de ce côté.

⚠️ **Vérifié le 2026-08-17 : `data/p300_model.joblib` se charge sous le nom de module NU
`p300_decoder`.** Le déplacer dans `core/` rendrait le modèle illisible — c'est exactement ce qui a
coûté **les 4 modèles MI**, abandonnés sur décision.

**La différence qui sauve tout : les époques de calibration sont conservées**
(`data/p300_calib_20260722_151134_n12.npz` et deux autres, 8,8 Mo). Le modèle se **ré-entraîne
depuis le disque**, sans séance casque. C'est précisément ce qui manquait au MI, dont les époques
avaient été écrasées.

Le ré-entraînement fait donc partie du chantier, et il doit produire un modèle horodaté lisible sous
le nouveau chemin. **Ne pas écrire de shim de compatibilité** pour l'ancien nom de module : on a une
source de vérité meilleure que le pickle, il faut s'en servir.

Enfin, `src/research/p300_calibrate.py` doit être **recâblé** pour importer depuis `core/` — sinon
le déménagement le casse, et avec lui le seul chemin de calibration qui reste.

## 8. L'émetteur de stimulus autonome

Le stimulus P300 vit aujourd'hui dans l'appli pygame. On l'en sort en programme autonome qui
**affiche les flashs et publie ses marqueurs**, sur le patron déjà éprouvé de
`src/research/ssvep_stimulus.py`.

Ce qui rend ça possible sans conflit : **un stimulus n'ouvre pas le casque**. Moteur d'un côté,
stimulus de l'autre, deux terminaux — c'est déjà comme ça qu'on teste le SSVEP au casque.

C'est aussi l'exemple de référence pour un étudiant qui voudra émettre depuis Unity : il y lira le
protocole et, surtout, **où placer l'horodatage**.

## 9. Les pannes à rendre bruyantes

C'est le point où ce projet s'est déjà fait avoir plusieurs fois : un décodeur qui tourne, publie
des scores honnêtes, et **ne déclenche simplement jamais**. Chacune de ces situations doit se dire :

| Situation | Ce que le moteur doit faire |
|---|---|
| Aucun flux de marqueurs trouvé | Le dire, et ne pas prétendre décoder |
| Marqueur plus vieux que le tampon | Le compter et l'annoncer — jamais un rejet muet |
| Marqueur dans le futur | Nommer la cause : `time_correction()` oublié, piège des 2 machines |
| Cible hors de la plage déclarée | Refus explicite, avec la plage attendue |
| `round_end` avec trop peu de flashs | `target_index = -1` **et** la raison |

## 10. La stratégie de test — sans casque

Board synthétique d'un côté, émetteur de marqueurs de l'autre, dans le même processus de test.
`synth_p300_epoch` existe déjà pour fabriquer des époques cible / non-cible.

⚠️ **Le test qui compte n'est pas « ça publie quelque chose », c'est l'ALIGNEMENT.** On injecte un
motif reconnaissable dans l'EEG à un instant connu, on envoie un marqueur à cet instant, et on
vérifie que l'époque extraite contient le motif **à la bonne position**.

Sans ce test, un décalage de quelques échantillons passe tous les autres au vert et décode du bruit
avec une confiance de 0,92 — la panne la plus coûteuse imaginable ici, parce qu'elle est
**indiscernable d'un succès**. C'est le pendant exact de l'invariant « la fenêtre MI n'est pas
filtrée », qu'un seul test protège.

Un second test doit vérifier le **dimensionnement de `keep`** par une assertion directe sur sa
valeur — pas en observant qu'une époque sort, car un tampon sous-dimensionné rend quand même ce
qu'on lui demande. Ce piège a déjà été rencontré au chantier 3B.

## 11. Contraintes globales

- `src/core/` n'importe **jamais** `src/research/` ni `src/console/`, et ne contient ni pygame ni Qt.
  Vérifié par `python src/core/server.py --smoke`, qui scanne `src/core/**/*.py`.
- La console est un **client** du moteur : aucune logique qui n'existe pas déjà côté moteur, pas de
  validation côté interface, pas de catalogue de modes recopié.
- Code et commentaires **en français** ; messages de commit, README et doc étudiante **en anglais**.
- Tout doit être testable **sans casque** (`--synthetic`).
- Les constantes de protocole ne bougent pas.
- Aucun test n'écrit dans le vrai `data/` : répertoire temporaire et nettoyage dans un `finally`.
- ⚠️ **Aucun moteur ne tourne pendant un test** : les noms de flux sont un contrat public, donc
  identiques pour toutes les instances.

## 12. Découpage indicatif pour le plan

1. `MarkerInlet` (résolution par nom, `time_correction`, tirage non bloquant) + son autotest.
2. Le tampon d'horodatages du moteur + `keep` dimensionné nommément + l'assertion directe.
3. La file des marqueurs mûrs + le point d'extension du contrat de mode.
4. Déménagement de `p300_decoder.py` dans `core/`, ré-entraînement du modèle depuis les époques
   conservées, recâblage de `p300_calibrate.py`.
5. `P300Runtime` + le flux `decoded_p300` + les cinq pannes bruyantes.
6. L'émetteur de stimulus autonome + le test d'alignement.
7. Documentation : le contrat public des marqueurs, la tuile P300 qui n'est plus grisée, la recette.
