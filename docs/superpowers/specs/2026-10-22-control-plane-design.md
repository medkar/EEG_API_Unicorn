# Le control plane : l'application règle et pilote le moteur

**Statut** : conception validée en conversation le 2026-10-22, à relire avant le plan. Aucun code
écrit.
**Origine** : SPEC §14, « prochain chantier, noté le 2026-10-21 ». Le besoin, dit par
l'utilisateur : **l'application externe définit ses paramètres et les transmet à l'API pour
qu'elle décode correctement, sans que personne ne lance rien à la main depuis la console.**

---

## 1. Le problème

Aujourd'hui, une application LIT les flux décodés et ENVOIE ses marqueurs de stimulus. Mais pour
qu'elle reçoive quelque chose, quelqu'un doit, dans la console : régler le mode (fréquences,
rafraîchissement, flux de marqueurs…), puis cliquer « Démarrer ». Exemple réel : un étudiant code
son jeu Unity, découvre qu'il ne tient que 30 images/s ; il doit revenir dans la console, entrer 30,
re-proposer les fréquences, appliquer, redémarrer. Son jeu connaît pourtant son propre
rafraîchissement, ses cibles et le nom de son flux de marqueurs.

Ce qui existe déjà : l'API de commandes INTERNE du moteur, `EngineServer.submit(command,
**params)`, celle de chaque bouton de la console. Elle valide tout (`contract.validate`), refuse
avec une raison lisible, retient un réglage posé sur un mode arrêté (`differe`), et refuse les
conflits (pas de réglage pendant un test, pas de mode pendant sa calibration…). Il manque
l'adaptateur réseau, le canal de réponse, un client exemple et la doc. SPEC §12.1 l'a prévu
dès le 2026-07-24 : « l'entrée LSL n'est qu'un adaptateur ».

## 2. Décisions de l'utilisateur (2026-10-22)

1. **Ce que l'application peut faire : régler et démarrer/arrêter.** Régler un mode
   (`set_params`), demander une proposition de réglage (`propose_params`), démarrer un mode
   (`start_mode`), l'arrêter (`stop_mode`). **Les entraînements restent dans la console.**
2. **Console contre application : le dernier gagne.** Pas d'interrupteur. Le moteur applique la
   dernière commande valide, d'où qu'elle vienne. La console MONTRE ce que l'application a fait.
   Les refus existants (pas de réglage pendant un test, etc.) s'appliquent à l'application comme à
   la console.
3. **Seule une application de la MÊME machine pilote un moteur.** Même règle que les fenêtres de
   stimulus (`stimulus/retour.py`, nom d'hôte comparé sans casse). En salle, l'application d'un
   voisin ne pilote pas ton moteur. Un montage à deux PC peut toujours LIRE les flux, pas piloter.

Rappels de règles permanentes qui s'appliquent ici : le contrat réseau est en ANGLAIS, quelle que
soit la langue de l'écran ; aucun texte affiché n'est écrit en dur (`tr()`) ; la console ne
recopie aucune logique du moteur ; les tests n'écrivent jamais dans `data/`.

## 3. Périmètre

Dedans :

- l'adaptateur LSL dans le moteur (`core/`), actif en console ET avec `server.py` seul ;
- le flux de commandes entrant et le flux de réponses sortant ;
- le renommage en anglais des clés et valeurs de réglage que ce contrat rend publiques (§6) ;
- le correctif du constat ouvert n° 3 de `docs/qa.md` : `stream_in` devient un choix OUVERT (§7) ;
- des refus du moteur qui restent traduisibles jusqu'au bout (§5, « toujours en anglais ») ;
- l'affichage dans la console de ce que l'application a fait (§8) ;
- un client exemple en Python, qui sert aussi de test automatique (§9) ;
- textes FR/EN, autotests, doc publique (anglais), SPEC, CLAUDE.md, QA, recette.

Dehors (non-objectifs) :

- les entraînements par le réseau (`start_calibration`, `save_calibration`…), et les mesures ;
- arrêter le moteur entier (`stop`), `set_published`, `recalibrate`, l'enregistrement de séance ;
- piloter depuis une autre machine ;
- le flux sortant `EEG_API_Unicorn_markers` (événements API) de la table du SPEC §4 : toujours pas
  livré ;
- une page « Connecter » dans la console, et le journal de séance c-VEP (recette 2.9) ;
- un adaptateur WebSocket ; toute authentification ;
- un client Unity ou MATLAB livré : c'est l'essai réel de fin de chantier (§11), pas un livrable.

Anti-objectifs — ce qui serait un échec même si « ça marche » :

- une commande perdue SANS que l'application puisse le savoir (hors la perte avant connexion,
  documentée au §5) ;
- une réponse en français parce que l'écran est en français ;
- l'application d'un voisin qui pilote mon moteur ;
- la console qui montre d'anciens réglages après un changement venu de l'application ;
- une validation réécrite dans l'adaptateur : il APPELLE `submit`, et rien d'autre ne décide.

## 4. Les deux flux

| Flux (type LSL) | Sens | Qui crée l'outlet | Contenu |
|---|---|---|---|
| `EEG_API_Unicorn_control` (Markers, chaîne) | entrant | l'application | une commande JSON par échantillon |
| `EEG_API_Unicorn_replies` (Markers, chaîne) | sortant | le moteur, au démarrage | une réponse JSON par commande reçue |

LSL ne permet pas au moteur de recevoir sur un flux qu'il publie : c'est donc l'application qui
crée l'outlet de commandes, et le moteur qui l'écoute.

**Écoute.** Le moteur écoute TOUS les flux nommés `EEG_API_Unicorn_control` publiés par sa
machine (plusieurs applications locales possibles), et ignore ceux des autres machines (un message
au terminal, une fois par flux étranger). Un flux qui apparaît pendant que le moteur tourne est
découvert sans redémarrage (suggestion : `pylsl.ContinuousResolver`, qui découvre en tâche de fond).

**L'adaptateur a son PROPRE fil**, jamais la boucle du moteur *(choix du concepteur)*. Juger une
commande peut bloquer : `contract.validate` résout le réseau pour `stream_in` (~0,3 s,
`core/markers.py`) et charge chaque fichier de modèle pour lister les choix de `model`
(`mi_models.py`). Dans la boucle, un jeu qui renvoie ses réglages en boucle ferait hoqueter le
décodage. `submit` est déjà conçu pour être appelé d'un autre fil (la console l'appelle depuis le
fil Qt). Ce que la boucle a à dire à l'application (un échec après acceptation, §5) passe par une
file que le fil de l'adaptateur publie : un seul fil écrit dans l'outlet de réponses. Le fil
s'arrête avec le moteur.

**Le nom du flux écouté est un paramètre du moteur** (défaut `EEG_API_Unicorn_control`)
*(choix du concepteur)*. Le smoke en prend un unique ; sans ça, un moteur réel oublié sur le même
poste obéirait aux commandes du test, puisqu'il écoute ce nom sur sa machine quel que soit le
`source_id`. Le client exemple prend le même nom en option.

**Le flux `status`** liste `EEG_API_Unicorn_replies` dans `streams`, comme les autres flux publiés.

## 5. Le format

**Commande** (clés en anglais, toutes sauf `cmd` facultatives selon la commande) :

```json
{"cmd": "propose_params", "mode": "ssvep", "params": {"refresh_hz": 30}, "ref": "42"}
{"cmd": "set_params", "mode": "ssvep", "params": {"refresh_hz": 30, "freqs": [<proposées>]}, "ref": "43"}
{"cmd": "start_mode", "mode": "ssvep", "ref": "44"}
{"cmd": "stop_mode", "mode": "ssvep", "ref": "45"}
```

⚠️ `set_params {"refresh_hz": 30}` SEUL est refusé, et c'est juste : les fréquences retenues
(15, 20, 8,571 par défaut) ne divisent pas 30. Le geste est celui de la console : proposer sur le
nouveau rafraîchissement, puis poser rafraîchissement ET fréquences ensemble. Les valeurs
proposées dépendent du pic alpha (une fréquence trop proche est écartée) : la doc n'en écrit
aucune en dur.

- `cmd` : une des quatre commandes. Toute autre (y compris les commandes internes non exposées) est
  REFUSÉE avec une raison qui liste les quatre permises.
- `mode` : l'identifiant du mode (`ssvep`, `mi`, `p300`, `errp`, `cvep`, `neuro`, `raw`). La liste
  est dans `docs/control.md` (`status.modes` ne liste que les modes ACTIFS) ; un identifiant
  inconnu est refusé avec la liste.
- `params` : les réglages, par clé publique (§6). `start_mode` part, comme dans la console, des
  réglages retenus du mode, et `params` les complète.
- **`start_mode` et `stop_mode` sont IDEMPOTENTS** *(choix du concepteur)*. Aujourd'hui, `submit`
  refuse de démarrer un mode qui tourne et d'arrêter un mode arrêté. Or le cas courant est un jeu
  qui redémarre et renvoie `start_mode` avec ses réglages pendant que le mode tourne encore : le
  refus jetterait ses réglages, et un renvoi après une réponse perdue serait refusé pour une
  commande qui avait réussi. Donc : `start_mode` sur un mode qui tourne applique ses `params` comme
  `set_params` et répond accepté avec `already_running: true` ; `stop_mode` sur un mode arrêté
  répond accepté avec `already_stopped: true`. La règle vit dans le MOTEUR (un seul chemin, que la
  console partage ; elle n'envoie jamais ces cas-là), pas dans l'adaptateur.
- **`stream_in` changé sur un mode qui TOURNE** ne prend pas effet à chaud : le moteur n'a qu'un
  inlet de marqueurs, ouvert une fois (`server._ouvre_marker_inlet`, commentaire de
  `contract.Param.affecte_decodage`). Aujourd'hui c'est accepté sans un mot, hors la bulle d'aide.
  Désormais : accepté, retenu, avec un `warning` qui dit QUAND il prendra effet (au prochain
  démarrage du mode, et seulement si plus aucun mode à marqueurs ne tient l'inlet). L'ordre
  recommandé à l'application, dans la doc : `set_params` (dont `stream_in`) PUIS `start_mode`.
  *(Choix du concepteur.)*
- `propose_params` : rend la valeur proposée SANS rien appliquer (aujourd'hui, seul le SSVEP
  propose : `freqs` depuis `refresh_hz`, `alpha_hz` et la bande). `key` est facultatif quand le
  mode n'a qu'un seul réglage proposeur.
- `ref` : une étiquette libre de l'application, recopiée telle quelle dans la réponse. C'est elle
  qui permet à une application de reconnaître SA réponse parmi celles des autres.

**Réponse** — une par commande reçue, y compris illisible :

```json
{"ref": "42", "cmd": "set_params", "mode": "ssvep", "accepted": true, "deferred": true,
 "params": {...tous les réglages validés...}}
{"ref": "44", "cmd": "start_mode", "mode": "ssvep", "accepted": false,
 "reason": "\"SSVEP\": 17 Hz does not divide 60 Hz ..."}
{"ref": null, "cmd": null, "accepted": false, "reason": "Not a JSON command: ..."}
{"ref": "42", "cmd": "propose_params", "mode": "ssvep", "accepted": true,
 "key": "freqs", "value": [...], "warning": null}
```

- `reason`, `warning` : TOUJOURS en anglais, relus par `i18n.pour_le_contrat`, même console en
  français. Les nombres y partent avec un point. ⚠️ **Ce n'est pas vrai aujourd'hui pour tous les
  refus** : `pour_le_contrat` ne relit qu'un `Texte` resté intact, et plusieurs raisons sont
  aplaties en chaîne dans la langue de l'écran avant d'arriver là (`contract.py` : l'unité d'un
  refus hors bornes, les refus de diviseur du rafraîchissement ; `config.py` : la note de
  `propose_frequencies` ; `message_erreur`). Le chantier les garde traduisibles jusqu'au bout, et
  le test les fait passer écran en français (§10).
- `deferred` (le `differe` interne) : `true` quand le réglage est RETENU sur un mode arrêté et
  partira avec le prochain démarrage.
- `accepted: true` sur `start_mode` dit que la commande est ACCEPTÉE, pas que le mode décode : ça
  s'observe sur `status` (`modes`, `phase`) et à l'apparition de `decoded_<mode>`. Même règle que
  la docstring de `submit`.
- **Un échec APRÈS l'acceptation reçoit un second message, avec le même `ref`** *(choix du
  concepteur)*. La boucle peut encore refuser (`_start` : une calibration ou une mesure soumise
  dans la même fenêtre) ou lever (`_drain_commands` : un modèle qui ne se charge pas) ; aujourd'hui
  seul le terminal le sait. Sans ce message, l'application attendrait un mode qui ne démarrera
  jamais. Forme : `{"ref": "44", "cmd": "start_mode", "mode": "ssvep", "event": "failed",
  "reason": "..."}`. La commande voyage donc avec son `ref` dans la file du moteur. Une commande
  de la console n'a pas de `ref` et ne produit aucun message réseau.

**Deux pièges LSL que la doc et l'exemple doivent montrer** (et que le test vérifie) :

1. **Une commande envoyée avant que le moteur ait découvert l'outlet est PERDUE** : LSL ne rejoue
   rien. L'application attend donc le moteur avant d'envoyer (`outlet.wait_for_consumers(timeout)`
   en pylsl), et sait qu'il manque si l'attente échoue.
2. **Une réponse publiée avant que l'application écoute est perdue aussi** : l'application ouvre
   son inlet de réponses (`open_stream()`) AVANT d'envoyer sa première commande.

Une commande sans réponse au bout de quelques secondes = perdue ; l'application peut la renvoyer
(les quatre commandes sont sans danger à rejouer).

## 6. Les noms publics des réglages : en anglais

Le contrat réseau est en anglais. Le control plane rend publiques les clés de `params` des modes,
or plusieurs sont françaises. Inventaire (2026-10-22, par `registry.MODES`) :

| Mode | Clé actuelle | Clé publique proposée |
|---|---|---|
| SSVEP | `cibles` (valeurs `ecran` / `physiques`) | `targets_on` (`screen` / `physical`) |
| SSVEP | `noms` | `target_names` (le nom déjà lu sur `decoded_p300`) |
| SSVEP, et l'entraînement de MI, P300, ErrP, c-VEP | `bande_bas`, `bande_haut` | `band_low`, `band_high` |

**Un seul vocabulaire, pas une table de traduction** : la clé est renommée PARTOUT (contrat,
console, fenêtres, tests, catalogues de textes si une clé s'y réfère). Une clé partagée avec un
entraînement est renommée aussi dans l'entraînement. Les clés propres aux entraînements (`taches`,
`mise_en_route_s`, `cibles` du c-VEP et du P300) ne deviennent pas publiques : les renommer
aussi, par uniformité, est laissé au constructeur. Ce qu'un modèle déjà enregistré stocke (sa bande,
son secteur) n'est pas un contrat réseau : son format peut rester tel quel si sa relecture ne
dépend pas d'une clé renommée ; sinon, le modèle d'avant est relu ou refusé avec une raison (en
dev, réentraîner ne coûte rien).

**`model`** : sa valeur interne est un chemin sur le poste du moteur, que l'application ne connaît
pas. Publiquement, `model` accepte le **nom du fichier** (celui que la console affiche) ; le
moteur le résout parmi ses choix. Sans `model`, le mode prend le plus récent, comme aujourd'hui.
*(Choix du concepteur.)*

## 7. `stream_in` devient un choix ouvert (constat n° 3)

Prérequis du chantier : un jeu qui annonce son flux de marqueurs par `set_params` juste après
l'avoir créé serait refusé si la découverte LSL ne l'a pas encore vu. Correctif DÉCIDÉ le
2026-10-21, repris tel quel de `docs/qa.md` (constat ouvert n° 3) :

1. **Moteur** : tout nom non vide est accepté ; un nom absent du réseau l'est avec un
   AVERTISSEMENT (« not seen on the network yet: the engine will wait for it »), jamais un refus.
   Le moteur sait déjà attendre un flux absent.
2. **Console** : la liste garde TOUJOURS la valeur retenue, même absente du réseau, marquée
   « (pas vu sur le réseau) » ; plus rien n'est remplacé en silence ; la liste est éditable (on
   peut taper le nom à l'avance).

L'avertissement voyage dans la réponse (`warning`).

## 8. Ce que montre la console

- `snapshot()` porte les dernières commandes reçues du réseau (heure, commande, mode, accepté ou
  la raison), une courte liste.
- Le **bandeau** affiche la dernière quelques secondes, dans la langue de l'écran : « Application :
  démarrage de SSVEP demandé », « Application : réglage refusé — … », et l'échec après acceptation
  (§5). Un refus se voit aussi, sinon l'étudiant qui code son jeu ne comprend pas pourquoi rien ne
  se passe. Le bandeau dit « demandé », pas « démarré » : le démarrage se lit sur la tuile.
- La grille et la page du mode se mettent à jour par l'état reçu, comme aujourd'hui (la page de mode
  rafraîchit déjà son formulaire quand le moteur change ses réglages, `mode_page.update_from`).
- Aucun nouveau bouton ni page. Rien à cocher.

## 9. Le client exemple

`examples/control_client.py` : un client Python minimal, commenté pour un élève ingénieur, qui
crée l'outlet de commandes, ouvre l'inlet de réponses, attend le moteur, demande les fréquences
proposées pour un écran à 30 Hz, pose rafraîchissement et fréquences ensemble, démarre, lit
quelques décisions sur `decoded_ssvep`, arrête. Le nom du flux de commandes est une option (§4). Il est lancé, dans un processus SÉPARÉ, par le test du §10 : l'exemple
ne peut pas pourrir sans faire rougir un test.

## 10. Les tests

- **Autotest de l'adaptateur** (`python src/core/<module>.py`) : JSON illisible, commande non
  permise, `ref` recopié, filtre d'hôte (faux flux, comme `research/enregistre_brut.py`), `model`
  par nom de fichier.
- **Les refus en anglais, écran en français** : chaque famille de refus des quatre commandes (clé
  inconnue, hors bornes, diviseur du rafraîchissement, choix absent, mode inconnu, conflit avec un
  test) passe par la réponse réseau avec la langue de l'écran mise en français, et aucune ne contient
  de français ni de virgule décimale.
- **Idempotence** : `start_mode` deux fois (le second applique ses réglages), `stop_mode` sur un
  mode arrêté ; et l'échec après acceptation produit son second message.
- **Section du smoke moteur** (`server.py --smoke`, board de test) : le client exemple en
  sous-processus contre un vrai moteur, sur un nom de flux de commandes PROPRE au smoke (§4).
  Réglage différé, proposition, démarrage observé sur `status` puis `decoded_ssvep`, refus motivé
  en anglais, arrêt. Plus : une commande envoyée SANS attendre le moteur n'a pas de réponse (le
  piège du §5 est réel, la doc ne ment pas).
- **La boucle ne bloque pas** : pendant qu'un client envoie des `set_params` en rafale sur un mode
  à `model`, le flux décodé d'un mode qui tourne continue de publier à sa cadence.
- **Smoke console** : une commande venue du réseau apparaît au bandeau, le formulaire suit.
- **`[smoke-exemples]`** connaît les deux nouveaux noms de flux.
- **`[smoke-textes]`** : nouveaux textes en FR et EN.

## 11. L'essai réel, en fin de chantier

Ce que la simulation ne prouve pas : un autre langage (C# / MATLAB : autre bibliothèque LSL,
encodage des chaînes), la compréhension de la doc par un élève, la latence ressentie. Fin de
chantier : un point de QA pour l'utilisateur, piloter le moteur depuis une application d'un autre
langage sur ce poste (Unity si disponible). Le montage à deux PC est hors sujet (décision 3).

## 12. La documentation

- `docs/control.md` (anglais, public, comme `markers.md`) : le contrat des deux flux, les quatre
  commandes, les clés publiques des réglages par mode, les deux pièges du §5, un extrait de code.
- README : une section « Drive the engine from your app ».
- SPEC §4 (table des flux : `control` livré, `replies` ajouté), §12.1, §14 (fait) ; CLAUDE.md ;
  `docs/qa.md` (un point du bloc 1 joué avec l'exemple, console ouverte : le bandeau, le
  formulaire) et `docs/recette.md` (le pourquoi).

## 13. Risques

- **Pertes LSL** (§5) : la seule défense est l'attente côté application ; la doc et l'exemple la
  montrent, le test prouve qu'elle est nécessaire.
- **Le dernier gagne** : un jeu qui renvoie ses réglages en boucle écrase ce qu'on règle à la main
  dans la console. Assumé (décision 2) ; le bandeau le rend visible.
- **Renommage des clés** : un oubli ne lève rien partout (une clé inconnue est refusée par
  `contract.validate`, mais un `.get("cibles")` dans une fenêtre rendrait None en silence). Le
  constructeur cherche toutes les occurrences, et les autotests de chaque fenêtre doivent passer.
- **Deux applications locales** se partagent un seul flux de réponses : le `ref` les départage ; un
  `ref` absent rend la réponse ambiguë (documenté).
- **Idempotence dans `submit`** : la console partage ce chemin. Elle n'envoie jamais
  `start_mode` sur un mode qui tourne ni `stop_mode` sur un mode arrêté, mais des assertions de
  smoke attendent peut-être ces refus : elles changent avec la règle, pas en douce.
