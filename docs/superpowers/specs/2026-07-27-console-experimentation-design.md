# Console d'expérimentation — conception

> Document de conception (français, interne). Écrit le 2026-07-27, validé section par section
> avec l'utilisateur. Couvre le **chantier 0+1** ; les chantiers 2 à 4 y sont nommés mais non
> spécifiés.

## 1. Ce qui change, et pourquoi ce document existe

`docs/SPEC.md` décrit un **moteur qui décode et diffuse**, avec une interface en périphérie.
L'usage réel demandé est l'inverse : une **console d'expérimentation** où un étudiant règle des
paramètres, lance des entraînements, gère des modèles et observe le signal — la **diffusion
réseau devenant une sortie parmi d'autres**, qu'on active mode par mode.

Formulation de l'utilisateur : « je veux un outil qui permette facilement d'expérimenter avec un
fort niveau d'abstraction. Ensuite on peut choisir d'exposer les résultats (ou le brut) pour les
utiliser dans des apps externes. » Et le motif : « ce qui a été vrai pour moi ne le sera peut-être
pas pour eux » — les réglages figés dans `config.py` doivent devenir manipulables.

### Le point dur

Aujourd'hui, **« un mode » n'existe pas comme objet**. C'est une suite de `if mode == "ssvep" …
elif mode == "neuro"` dans `server.py`, et des cartes écrites à la main dans `dashboard.html`.
Tout ce qui est demandé — cumuler, régler, entraîner, publier à la carte — bute sur cette absence.
Le « fort niveau d'abstraction » demandé **est** cette pièce manquante, et c'est une pièce de
moteur, pas d'interface.

## 2. Décisions prises

| Décision | Choix | Motif |
|---|---|---|
| Cadrage | Console d'expérimentation ; diffusion = une sortie activable par mode | Demande explicite |
| Découpage | 0+1 (contrat + coquille) d'abord ; 2 params, 3 entraînements, 4 déjà absorbé | Livrer utilisable sans dette |
| Navigation | **Grille-tableau de bord** → **page de mode** | Le mode devient le cadre ; la grille montre ce qui tourne, ce qui est publié, ce qui manque |
| Contrat de mode | Objet Python déclaré **près du décodeur** | Une seule source de vérité ; JSON séparé écarté (deux vérités qui divergent) |
| Cumul de modes | **Dans le chantier 0** | L'extraction du runtime par mode est le chantier ; le cumul en découle. Le reporter obligerait à refaire la même extraction plus une migration d'API |
| Interface | **PySide6 + pyqtgraph**, en remplacement du tableau de bord web | Tracé EEG temps réel exigé ; formulaires et tableaux propres ; le plus documenté pour un étudiant qui modifiera |

### Renversement à enregistrer

**SPEC §12.2 est renversée** : elle avait figé « tableau de bord web servi en local », sur le
critère « modifiable par un élève » (HTML/CSS/JS étant la techno la mieux connue des étudiants).
L'utilisateur choisit Python en connaissance de cause. Ce qui est perdu, et assumé :

- **l'installation zéro** — PySide6 ajoute ~100 Mo aux dépendances ;
- **le suivi à distance** — plus d'encadrant observant la qualité du signal depuis un autre poste ;
- **la modifiabilité par un élève** — Qt est moins connu que le web.

Ce qui est gagné : un seul langage ; le tracé temps réel devient facile au lieu d'être un chantier ;
et surtout **les consignes de calibration et le stimulus local peuvent vivre dans la même
application**, ce qui supprime la couture « navigateur pour le MI, fenêtre native pour le c-VEP ».

`docs/SPEC.md` §12.2 doit être amendée, pas réécrite : la décision d'origine et son renversement
doivent rester lisibles côte à côte.

## 3. Le contrat `ModeSpec`

Le registre décrit **tous** les modes, **y compris ceux sans implémentation**. C'est lui qui porte
l'honnêteté de l'interface : sans ça, la grille ne montrerait que ce qui est chargé et les modes
manquants seraient invisibles — le défaut que l'utilisateur a pointé en premier.

```python
@dataclass(frozen=True)
class ModeSpec:
    id: str                    # "ssvep" — identifiant stable, sert de clé partout
    label: str                 # "SSVEP"
    family: str                # "actif" (l'utilisateur choisit) | "passif" (on observe)
    summary: str               # une phrase : ce que le mode produit
    status: str                # "moteur" | "appli_pygame" | "prevu"
    unavailable: str           # POURQUOI il n'est pas dans le moteur ; "" si status == "moteur"
    params: tuple[Param, ...]
    rest: Rest | None          # plancher de repos requis, ou None
    calibration: Calib | None  # None = rien à entraîner
    stream: str | None         # suffixe du flux publié, ex. "decoded_ssvep"
    channels: tuple[str, ...]  # noms des voies de ce flux
```

`status` a exactement trois valeurs et elles ne sont pas décoratives :

- `"moteur"` — un runtime existe, le mode peut démarrer ;
- `"appli_pygame"` — décodé par `src/research/app.py`, pas par le moteur ; `unavailable` dit
  pourquoi (ex. « demande des marqueurs entrants ») ;
- `"prevu"` — ni l'un ni l'autre, listé pour la carte du produit.

**Le MI est `"appli_pygame"` dans ce chantier**, comme le c-VEP, le P300 et l'ErrP. La maquette
validée le montrait « prêt » avec un modèle daté et un bouton de calibration : ces blocs étaient
annotés « chantier 3 » et illustraient l'état futur de la page de mode, pas ce qui est livré ici.
Le MI est le **premier candidat** à la migration (fenêtre glissante, aucun marqueur requis, modèle
à 79 % déjà entraîné), mais il n'a pas de runtime dans ce chantier.

### `Param` : le formulaire ET la validation

```python
@dataclass(frozen=True)
class Param:
    key: str            # "freqs"
    label: str          # "Fréquences des cibles"
    kind: str           # "float" | "int" | "bool" | "choice" | "float_list"
    unit: str = ""      # "Hz"
    default: object = None
    min: float | None = None
    max: float | None = None
    count: tuple[int, int] | None = None   # pour les listes : (mini, maxi) d'éléments
    choices: tuple = ()
    constraint: str = ""                   # contrainte croisée nommée, ex. "separables"
    proposes: str = ""                     # ce paramètre en PROPOSE un autre (cf. §3.1)
    help: str = ""                         # ce qu'un étudiant doit comprendre avant d'y toucher
```

Un seul objet sert **trois** usages, et c'est tout l'intérêt : générer le champ de formulaire,
valider côté moteur, et afficher l'aide. La validation écrite à la main pour `set_freqs` le
2026-07-27 (bande passante, écart minimum entre cibles) devient une contrainte **déclarée**,
appliquée par le même code pour tous les modes.

Les contraintes croisées sont nommées et implémentées dans le moteur, jamais dans l'interface :

- `"separables"` — deux cibles doivent être distantes d'au moins `1/WINDOW_S` (résolution
  fréquentielle de la fenêtre). Sans ça, aucune erreur : juste un décodage qui ne détecte rien.
- `"dans_la_bande"` — chaque valeur doit tomber dans `BANDPASS`, sinon le filtre d'acquisition la
  supprime avant le décodage.

### 3.1 Un paramètre qui en propose un autre

L'utilisateur veut régler le **nombre de cibles** *et* les **fréquences**. Les deux sont liés : les
fréquences affichables sans jitter sont les diviseurs entiers du refresh écran. Le contrat déclare
donc `n_targets` avec `proposes="freqs"` : changer le nombre **propose** un jeu de fréquences
valides, que l'utilisateur peut ensuite modifier. La proposition est calculée par le moteur
(`choose_frequencies`), jamais par l'interface. La mécanique complète est du chantier 2 ; le
contrat doit seulement la permettre dès maintenant.

### `Rest` et `Calib`

```python
@dataclass(frozen=True)
class Rest:
    warmup_s: float     # stabilisation JETÉE (dérive DC des électrodes sèches)
    duration_s: float
    instruction: str    # consigne à afficher pendant la mesure

@dataclass(frozen=True)
class Calib:
    kind: str      # "console" (consignes rendues par la console) | "natif" (fenêtre pygame)
    reason: str    # pourquoi "natif" : "clignement verrouillé à la frame"
```

`kind` encode une contrainte physique, pas une préférence : le MI donne ses consignes à l'échelle
de la seconde, la console suffit ; le c-VEP exige que **chaque frame** affiche le bon bit, une seule
frame sautée décale le code et détruit la corrélation.

Dans ce chantier, `Calib` est **informatif** : aucun mode doté d'un runtime n'exige de calibration
(brut, SSVEP et neuro n'en demandent pas). Il sert à la grille pour dire d'un mode externe ce qu'il
faudrait pour l'entraîner. Les champs nécessaires à la gestion des modèles (emplacement, historique)
seront ajoutés au chantier 3, quand on saura ce dont ils ont besoin.

## 4. Architecture

### 4.1 Paquets

```
src/core/modes/
    registry.py     le catalogue : tous les ModeSpec, publiés ou non
    ssvep.py        ModeSpec + runtime, s'appuie sur core/cca_decoder.py
    neuro.py        ModeSpec + runtime, s'appuie sur core/neuro_monitor.py
    raw.py          ModeSpec + runtime : diffuser le brut est un mode comme un autre
    external.py     c-VEP, P300, ErrP, MI : ModeSpec seuls, sans runtime
src/console/        l'application PySide6
```

**L'algorithme et le mode sont séparés.** `cca_decoder.py` reste l'algorithme — une CCA, testable
sur du synthétique, indifférente au produit. `modes/ssvep.py` est le contrat : comment ça s'appelle,
ce qui se règle, ce qui se publie. Les mélanger était le défaut du `server.py` actuel.

`src/console/` est un **troisième paquet**, ni `core` ni `research`. La règle posée le 2026-07-27
tient : un module est dans `core` si et seulement si `server.py` en a besoin pour tourner, et le
moteur doit continuer à tourner sans écran. `console` importe `core` ; `core` n'importe ni
`research` ni `console`.

### 4.2 Runtime par mode et cumul

L'état d'un mode descend du moteur vers un runtime :

```python
class ModeRuntime:
    spec: ModeSpec
    params: dict            # valeurs courantes, validées contre spec.params
    phase: str              # "warmup" | "rest" | "running"
    published: bool         # publier sur le réseau, ou décoder pour soi seul
    decoder / publisher / état du plancher
    def tick(self, engine, lsl_ts): ...
```

Le moteur ne garde que le vraiment commun : session casque, tampon glissant `_recent`, horloge,
qualité du signal. Sa boucle itère sur `self.active: dict[str, ModeRuntime]` au lieu de tester un
mode unique.

**Flux toujours publiés, hors modes** : `quality` et `status` décrivent la santé du moteur, pas un
mode ; ils restent publiés en permanence. `raw` en revanche **devient un mode** : on peut donc
arrêter de diffuser le brut, ce qui n'était pas possible.

**Repos partagé.** Deux modes lancés **dans la même commande** et ayant tous deux besoin d'un repos
partagent une seule phase de repos — les consignes sont compatibles (« ne fixe aucune cible » et
« immobile et détendu » décrivent le même moment). Lancés séparément, chacun fait le sien : un mode
démarré alors qu'un autre tourne déjà ne peut pas réutiliser un repos qu'il n'a pas observé.

Règles déterministes, pour qu'il n'y ait rien à interpréter : la **durée** retenue est le maximum
des `duration_s` demandées, la **chauffe** le maximum des `warmup_s`, et la **consigne affichée**
est celle du mode dont le `duration_s` est le plus long (à égalité, le premier dans l'ordre du
registre). Chaque mode calcule ensuite **son propre** plancher sur les fenêtres de ce repos commun.

### 4.3 API de commande

Les commandes passent par l'API interne existante (`submit()`), qui reste le seul chemin vers la
session BrainFlow. Elle est étendue :

| Commande | Paramètres | Effet |
|---|---|---|
| `start_mode` | `id`, `params?` | démarre un mode (chauffe + repos si `spec.rest`) |
| `stop_mode` | `id` | arrête un mode, libère son flux |
| `set_params` | `id`, `params` | valide contre `spec.params`, applique ; **relance le repos si le mode en a un**, sinon prend effet immédiatement |
| `set_published` | `id`, `on` | publie ou non le flux de ce mode |
| `recalibrate` | `id` | refait chauffe + repos de ce mode seul |
| `stop` | — | arrête le moteur |

`set_mode` et `set_freqs` disparaissent, remplacées par `start_mode`/`stop_mode` et `set_params`.
La validation reste **à la soumission** avec sa raison en clair, comme `set_freqs` aujourd'hui : un
paramètre invalide ne produit aucune erreur à l'exécution, seulement un décodage muet — le mode de
panne le plus coûteux du projet.

`snapshot()` rend désormais l'état global (casque, qualité, phase) **plus une entrée par mode
actif**, et le catalogue complet des `ModeSpec` sérialisés.

### 4.4 Console

Elle crée le moteur, lance sa boucle dans un fil, et sonde `snapshot()` via un `QTimer` à ~10 Hz.
Aucun HTTP.

**Règle stricte, déjà en place : le fil Qt ne touche jamais la session BrainFlow.** Toute action
passe par la file de commandes. C'est ce qui protège l'acquisition, et c'est non négociable.

Pour les tracés, le moteur expose un **accesseur public** (`recent_window(seconds)`) plutôt que de
laisser la console lire `_recent` : ce tampon est écrit par le fil d'acquisition.

**Règle de conception, à respecter partout : aucune logique dans l'interface que le moteur ne
possède pas déjà.** Pas de validation seulement côté console, pas de catalogue de modes en dur,
pas de règle métier dans le code d'affichage. La console rend et envoie des commandes. C'est ce qui
garde la majorité du travail testable sans écran, et ce qui rendrait un futur changement
d'interface peu coûteux.

### 4.5 Suppression du tableau de bord web

`src/core/dashboard.py` et `src/core/dashboard.html` sont supprimés. Maintenir deux interfaces sur
la même API doublerait le travail et les tests pour un usage écarté.

**Le travail moteur du 2026-07-27 reste intégralement** : `set_freqs` (devenu `set_params`), la
validation déclarée, le flux `decoded_neuro`, le correctif NaN→null. Seul le rendu HTML part.

## 5. Interface

### 5.1 Grille — le tableau de bord

Écran d'accueil. Une tuile par mode du registre, portant quatre informations pour éviter d'avoir à
cliquer : **l'état réel**, un **aperçu vivant** de ce que le mode produit, **s'il est publié**, et
pour les non publiés **pourquoi**.

Au-dessus, un **bandeau permanent** qui ne disparaît sur aucun écran : liaison casque, σ par voie,
et l'**alarme de référence décrochée**. Ce défaut rend une séance entière inexploitable sans autre
symptôme ; il ne doit jamais être hors de vue.

### 5.2 Page de mode

Trois blocs, tous générés depuis le `ModeSpec` :

1. **Sortie en direct** — ce que le mode produit, rendu selon `family` : barres de z par cible pour
   un mode actif, indices divergents autour du repos pour un mode passif, tracés pour le brut.
2. **Réglages** — formulaire généré depuis `spec.params`, avec le texte d'aide de chaque paramètre
   et le refus du moteur affiché en clair s'il y a lieu.
3. **Brancher un client** — nom du flux, voies, et un extrait Python à copier, **généré depuis le
   `ModeSpec`** qui connaît déjà tout ça.

Les chantiers 2 et 3 viendront enrichir les blocs 2 et 3 sans toucher à la coquille. C'est le test
de la structure.

### 5.3 Le mode « brut »

Sa page **est** la vue des tracés EEG en direct (pyqtgraph). Le manque n°1 signalé par
l'utilisateur, sans introduire de concept nouveau : le brut est un mode, sa page montre ce qu'il
produit.

## 6. Cas limites à traiter explicitement

| Situation | Comportement exigé |
|---|---|
| Mode sans modèle (MI non calibré) | La tuile **dit pourquoi** il ne peut pas démarrer ; pas d'échec silencieux |
| Casque absent / `BOARD_NOT_READY` | Affiché franchement ; pas de grille vide sans explication |
| Paramètre changé sur un mode qui tourne | Le repos de ce mode repart (un plancher mesuré sous d'autres réglages est faux) |
| Publication coupée en cours | Le mode continue de décoder pour l'affichage, ne publie rien |
| Référence décrochée | Bandeau permanent ; les modes continuent, l'utilisateur est prévenu |
| Dernier mode arrêté | Le moteur reste vivant, `quality` et `status` continuent, plus aucun flux de données |

## 7. Tests

Côté moteur, sans écran :

- **Intégrité du registre** — identifiants et suffixes de flux uniques ; **chaque valeur par défaut
  respecte les bornes de son propre paramètre**. Un défaut ici ne lève aucune erreur au démarrage :
  le mode refuse simplement d'appliquer ses réglages, et on le découvre en séance.
- **Contraintes déclarées** — la version générique des refus déjà testés (hors bande, trop proches,
  moins de deux cibles).
- **Cumul** — deux modes lancés ensemble publient tous les deux, chacun avec sa phase ; arrêter
  l'un ne perturbe pas l'autre.
- **Repos partagé** — deux modes lancés ensemble n'imposent qu'une phase de repos ; lancés
  séparément, chacun la sienne.
- **Frontière** — aucun import `core` → `research` ni `core` → `console`.

Côté console, `QT_QPA_PLATFORM=offscreen` : `python src/console/app.py --smoke` monte la grille
depuis un état factice, entre dans une page de mode, applique un réglage, ressort. Même philosophie
que `app.py --smoke`.

## 8. Périmètre

**Dedans** : contrat `ModeSpec` et registre complet ; runtime par mode ; cumul ; publication par
mode ; console PySide6 (grille + page de mode) ; formulaire de paramètres généré **en
lecture-écriture** ; mode « brut » avec tracés en direct ; panneau « brancher un client » ;
suppression du tableau de bord web ; tests ci-dessus ; mise à jour de `SPEC.md` et du `README`.

**Dehors** : entraînements et gestion des modèles (chantier 3) ; historique des décisions ;
publication des modes c-VEP, P300, ErrP, MI (ils restent des tuiles honnêtes renvoyant vers l'appli
pygame) ; marqueurs entrants ; control plane LSL.

Le formulaire en lecture-écriture est **délibérément** avancé depuis le chantier 2 : un contrat dont
les paramètres ne sont jamais rendus n'est pas validé. C'est la preuve que l'abstraction fonctionne.

## 9. Risques

**Le plus sérieux : la régression silencieuse.** On refond le moteur qui a été validé sur casque
aujourd'hui même. Les smokes existants (`server.py --smoke`, `app.py --smoke`) doivent passer à
chaque étape, et le comportement observable d'un mode seul doit rester identique à celui d'avant.

**PySide6 sur ce poste.** Jamais installé ici ; à vérifier tôt, avant d'écrire du code qui en
dépend.

**Le cumul n'a jamais tourné sur casque.** Deux décodeurs sur le même tampon est trivial en
synthétique ; la charge CPU réelle et l'effet sur la cadence d'acquisition restent à mesurer.

**L'appli pygame partage `core`.** La refonte du moteur la touche indirectement ; `app.py --smoke`
est le garde-fou.
