# Tâche 6 — rapport

**Statut : DONE_WITH_CONCERNS.** Quatre commits, `a7784b5` → `0c5e939`. Tout est vert, `data/`
intact. La réserve qui compte : **rien de tout ceci n'a vu un casque**, et c'est justement la moitié
que ce chantier ne peut pas tester — l'ergonomie.

## Ce qui est livré

| Fichier | Ce qui y est fait |
|---|---|
| `src/console/fenetres.py` **(neuf)** | `LanceurFenetre` : un `QProcess`, une seule fenêtre, la mort dite à l'écran |
| `src/console/contact_page.py` **(neuf)** | le contrôle de liaison : σ par voie, voies clés surlignées, refus en toutes lettres |
| `src/console/calib_page.py` | « Enregistrer » / « Refaire », l'avis du moteur, le verdict rendu sur ce que le résultat PORTE |
| `src/console/mode_page.py` | « Calibrer » (critère corrigé) et « Lancer le stimulus » |
| `src/console/app.py` | le câblage, l'ORDRE, l'arrêt du mode, `closeEvent` → `close()`, ~55 assertions de plus |
| `src/console/banner.py` | l'état de la fenêtre de stimulus, jamais masqué |
| `src/console/grid.py` | un mode publié qui s'arrête n'émet plus `set_published` depuis son repaint |
| `src/core/modes/mi_calib.py` | `HONNETETE` y déménage et voyage dans le résultat |

```
a7784b5 Make the console the place a calibration is started, judged and kept
f819d48 Prove the launcher against a real QProcess, and stop mutants from silencing the suite
006d370 Do not announce a cancellation the engine has not been able to perform yet
0c5e939 Cut a killed window's signals, so a late corpse cannot report the living one dead
```

## 🔴 L'ordre de lancement — traité, et le seul endroit où j'ai dû inventer quelque chose

`start_calibration` **D'ABORD**, la fenêtre **ENSUITE** (`Console._demarrer_calibration`), et un
test le fige : les deux mécanismes écrivent dans **un journal partagé** — le faux moteur y note
`("commande", nom)`, le faux `QProcess` y note `("fenetre", argv)`. Deux listes séparées diraient
que les deux ont eu lieu, jamais lequel a précédé l'autre. La mutation qui inverse les deux lignes
fait rougir **2** assertions, et seulement elles.

Marge réelle en séance : `submit` met en file, la boucle applique ~50 ms plus tard, donc la chauffe
du moteur démarre **après** le lancement de la fenêtre. La fenêtre est du bon côté de l'écart.

**⚠️ Ce que le brief ne disait pas, et qui a forcé une machine à états.** « Arrêter le mode avant de
soumettre `start_calibration` » ne peut PAS s'écrire en deux appels d'affilée : `stop_mode` est mis
en FILE, donc `submit("start_calibration")` juge un moteur où le mode est **encore actif** et
refuse. La console pose donc `stop_mode`, **attend de voir le mode disparaître de l'état**, et
soumet alors la calibration — avec un délai de 5 s au bout duquel elle **renonce en le disant**,
plutôt que d'attendre en silence (indiscernable d'une chauffe qui démarre). Horloge injectable pour
que ce délai soit testable sans attendre 5 s.

**La règle appliquée est uniforme : un mode est arrêté avant SA calibration, quel que soit le mode.**
La console ne recopie pas la table du moteur disant lesquels se voleraient les marqueurs — ce serait
exactement le catalogue dupliqué que `CLAUDE.md` interdit.

## Les neuf tests du cahier des charges

Tous dans `_smoke` de `src/console/app.py`, Qt offscreen, motif `chk(cond, msg)`.

1. **la commande vient de `stimulus/registry.py`** — comparaison à l'identique avec
   `stim_registry.commande("p300", calibrer=True)`, plus l'absence de `--calibrer` en mode décodage.
2. **le second lancement est refusé** — et aucun processus de plus n'est créé.
3. **une fenêtre morte le dit** — code de sortie **et** dernière ligne de stderr dans le bandeau ;
   et une fenêtre qu'on tue soi-même ne crie pas.
4. **le contact mauvais empêche ET dit** — voie morte (la voie est NOMMÉE), référence décrochée,
   tampon pas encore rempli. Trois refus distincts, trois textes non vides.
5. **`start_calibration` avant la fenêtre** — le journal partagé, ci-dessus.
6. **le mode est arrêté avant** — `stop_mode` seul d'abord, aucune fenêtre lancée, l'écran dit ce
   qu'on attend ; puis la calibration part toute seule quand le mode a rendu la main.
7. **« Enregistrer » / « Refaire » envoient leur commande** — et leur refus s'affiche.
8. **la console n'écrit pas sur le disque** — `empreinte_dossier(DATA_DIR)` avant/après les deux
   clics, servis par un moteur factice.
9. **`closeEvent` appelle `close()`** — et tue la fenêtre restée ouverte.

## Les douze preuves par mutation

Aucune assertion nouvelle n'a été écrite sans qu'on lui fasse la preuve de son rouge. Chaque
mutation ne fait rougir que ce qu'elle vise.

| Mutation | Rouges |
|---|---|
| la fenêtre lancée AVANT `start_calibration` | **2** — les deux assertions d'ordre |
| le mode n'est pas arrêté avant sa calibration | 8 |
| `closeEvent` n'appelle plus `close()` | 1 |
| le contrôle de liaison ne refuse jamais | 4 |
| une seconde fenêtre est autorisée | 2 |
| une fenêtre morte ne dit rien | 1 |
| la phrase d'honnêteté redevient une constante d'interface | 3 |
| les détails du MI sont écrits en dur | 2 (« 0 fenêtres d'entraînement » sous un P300) |
| « Enregistrer » n'envoie plus sa commande | 2 |
| la console écrit elle-même dans `data/` | 1 |
| les boutons de décision sont toujours cachés | 2 |
| le refus du moteur n'est plus affiché (stdout seul) | 3 |

## Les trois défauts trouvés en chemin

1. **🔴 Le bouton « Calibrer » avait DISPARU de tous les modes, MI compris.** `mode_page.py` le
   créait sous `calib["kind"] == "console"` — une valeur que le vocabulaire du contrat n'a plus
   depuis la tâche 2 (`moteur` | `fenetre`). Aucun test ne l'a vu : le smoke appelait
   `console.show_calibration()` **directement**, sans jamais cliquer. Le critère est désormais
   `jouable`, le même que celui qui décide de l'existence de la page.

2. **La grille émettait une commande depuis un simple AFFICHAGE.** `ModeTile.update_from(None)`
   décochait « publié » **sans `blockSignals`** — la branche jumelle, dix lignes plus bas, l'avait.
   Un mode publié qu'on arrête postait donc `set_published(id, False)` que personne n'avait
   demandé. Bénin tant que le moteur répond « arrêté entre-temps » ; mais redémarré dans la même
   seconde, la commande en file arrive APRÈS et retire silencieusement le flux du réseau. Trouvé
   par le test d'ordre, où ce `set_published` fantôme s'intercalait entre `stop_mode` et
   `start_calibration`.

3. **Une phrase d'annulation qui aurait été FAUSSE.** Quand la fenêtre refuse de s'ouvrir, la
   calibration doit être annulée — mais `cancel_calibration` soumise dans la foulée s'entend dire
   « aucune calibration en cours » (`start_calibration` n'est encore qu'en file). L'écran aurait
   annoncé une annulation qui n'a pas eu lieu, décompte de chauffe à l'appui. L'annulation est
   maintenant retenue et soumise dès que la séance existe (`006d370`).

## Ce que j'ai dû arbitrer

1. **La phrase d'honnêteté a DÉMÉNAGÉ dans `mi_calib.py`** (arbitrage n°2 du brief, appliqué à la
   lettre). Elle était une constante de `calib_page.py`, donc affichée sous **tous** les résultats
   de calibration — la page ne connaît aucun mode. Depuis que le P300 se calibre ici, ce « 40 % à
   trois classes, hasard 33 % » se serait affiché mot pour mot sous une **sélection parmi six
   cibles**. Chaque calibration porte désormais la sienne dans son résultat, comme
   `p300_calib.HONNETETE` le faisait déjà. Deux assertions de plus dans `mi_calib.py`.

2. **⚠️ ÉCART AU BRIEF, même cause : le VERDICT aussi était écrit aux mesures du MI.** La page
   affichait `n_fenetres` et `classes` en dur — deux clés que le résultat P300 n'a pas. Elle aurait
   donc écrit **« 576 essais enregistrés, 0 fenêtres d'entraînement — classes : »** sous le seul
   écran qui sert à décider si on garde le modèle : deux chiffres fabriqués et une liste vide. Deux
   petites tables (`MESURES`, `DETAILS`) indexées **par clé de résultat, jamais par identifiant de
   mode** remplacent ça — la même discipline que `live_views`, qui route sur la forme de la sortie.
   Le comportement du MI est inchangé (mêmes assertions, mêmes textes) ; le « 0 % » impossible
   quand `cv_groupee` vaut `None` reste fermé, par construction cette fois.

3. **Le contrôle de liaison est un ÉCRAN, pas un test silencieux.** Il s'interpose entre
   « Commencer » et le lancement, comme `signal_check` le faisait avant chaque mode de l'appli
   pygame. Il refuse sur **n'importe quelle** voie en défaut, pas seulement les voies clés du mode
   (les voies clés sont surlignées, et l'écran dit que le refus porte sur les huit) : ce sont les
   verdicts du moteur, la console n'en calcule aucun. Un état **sans** qualité refuse aussi —
   lancer là reviendrait à enregistrer à l'aveugle, l'accident du 2026-07-20.

4. **L'état de la fenêtre vit dans le BANDEAU**, pas sur une page. Une fenêtre qui meurt pendant
   qu'on regarde la grille doit se voir quand même. C'est le sixième fichier touché, non prévu au
   brief, pour huit lignes.

5. **⚠️ ÉCART AU BRIEF : le smoke lance UN vrai processus.** Le brief dit « aucun VRAI processus ».
   Le faux `QProcess` prouve la logique du lanceur et **rien** de son contact avec Qt : une
   signature qui change (`finished(int, ExitStatus)`, un `readAllStandardOutput` qui rend un
   `QByteArray`) laisserait tout vert et n'échouerait qu'en séance — sous la forme exacte du défaut
   qu'on répare. Le processus lancé est un `python -c` qui écrit sur stderr et sort en 3, borné par
   `waitForFinished(5000)` : **aucun pygame, aucune fenêtre, ~100 ms**. C'est l'esprit de
   l'interdiction (« un smoke qui lance pygame en CI est un smoke qu'on désactive ») sans sa lettre.
   La seconde moitié éprouve `errorOccurred(FailedToStart)`, le cas où `finished` n'arrive JAMAIS.

6. **`list.index` remplacé par un helper qui rend −1.** Une assertion qui LÈVE emporte toutes celles
   qui la suivent — précisément quand on en a besoin. Mesuré : la mutation « le mode n'est pas
   arrêté » sautait la moitié du smoke sur un `index()` d'ordre ; elle rapporte maintenant 8 rouges.

## Réserves (le WITH_CONCERNS)

- 🔴 **Rien n'a vu un casque, et c'est la moitié que ces tests ne peuvent pas atteindre.** Le smoke
  prouve le câblage, pas l'ergonomie. Trois questions n'ont de réponse qu'en séance : est-ce que les
  ~15 s couvrent vraiment l'écart de lancement fenêtre/moteur *sur cette machine* ; est-ce qu'un
  étudiant comprend, devant l'écran, qu'un chiffre affiché n'est pas encore un modèle enregistré ;
  et est-ce que le contrôle de liaison est lu ou cliqué au travers.

- 🔴 **Le contrôle de liaison peut BLOQUER une séance légitime.** Il refuse dès qu'une voie sort de
  `[0,5 ; 500] µV` — et il n'y a **aucune porte de sortie**. `research/ui.py:signal_check` laissait
  passer sur n'importe quelle touche (« à toi de juger ») ; ici, non. C'est délibéré (un
  contournement à un clic est un contournement qu'on prend par réflexe), mais si une électrode
  refuse de descendre sous le seuil, la console devient inutilisable **et c'est moi qui l'aurai
  fait**. À trancher en séance, pas avant.

- ✅ **Levée après vérification : `--synthetic` passe le contrôle de liaison.** Le smoke ne joue que
  sur des états fabriqués ; un board de test aux σ hors bande aurait bloqué tout lancement de
  fenêtre sans casque. Mesuré sur un vrai `EngineServer(synthetic=True)`, 5 s de boucle :
  `σ = [7,1 · 20,0 · 30,1 · 40,0 · 50,4 · 59,6 · 74,8 · 67,0] µV`, huit verdicts « ok »,
  `common_mode = −0,002`, `reference_lost = False`. Rien ne refuse.

- ⚠️ **La console ARRÊTE le mode avant toute calibration, même quand le moteur ne l'exigerait pas**
  (le MI, qui ne lit aucun marqueur). C'est le prix de la règle uniforme : ne pas recopier côté
  interface la table des conflits que le moteur possède. Conséquence visible : un MI qui décodait
  s'arrête quand on ouvre sa calibration, et il faut le redémarrer depuis la grille ensuite — ce
  qu'on ferait de toute façon, pour prendre le nouveau modèle.

- ⚠️ **`duree_estimee_s` d'une calibration à fenêtre vaut pour les réglages PAR DÉFAUT de la
  fenêtre** (réserve héritée de la tâche 4, intacte). La console lance `p300.py --calibrer` sans
  `--rounds` : les deux sont donc d'accord aujourd'hui. Le jour où la calibration exposera `rounds`
  comme réglage, il faudra le passer à la ligne de commande — `stimulus/registry.commande()` ne
  prend qu'un booléen.

- ⚠️ **Aucun `--windowed` n'est passé à la fenêtre.** Elle s'ouvre donc en plein écran, par-dessus
  la console. `closeEvent` la tue, mais rien ne la ramène au premier plan si l'étudiant alt-tabe. En
  séance, c'est le comportement voulu (le stimulus doit occuper l'écran) ; en développement, il
  faudra la lancer à la main.

- ⚠️ **`CLAUDE.md` est maintenant faux sur un point** : il dit que l'appli pygame garde « les
  calibrations que le moteur ne sait pas jouer — c-VEP, P300, ErrP ». Le P300 se calibre depuis la
  console depuis la tâche 4, et depuis ce commit on peut y arriver. `docs/` ne connaît ni le
  contrôle de liaison, ni les deux boutons, ni `save_calibration`. Hors périmètre (tâche 11), mais
  la liste s'allonge.

- ⚠️ **L'ErrP et le c-VEP montrent un bouton « Calibrer » GRISÉ**, avec une infobulle qui dit
  pourquoi (leur runtime n'est pas livré — tâches 7 et 8). C'est la même honnêteté que les tuiles
  grisées de la grille, mais une infobulle se survole ; elle ne se lit pas. Si les tâches 7 et 8
  n'aboutissaient pas, il faudrait écrire la raison en clair sur la page.

- ⚠️ **`_a_annuler` n'a pas de délai.** Si la calibration soumise n'apparaît jamais (moteur arrêté
  entre-temps), le drapeau reste posé jusqu'à la prochaine calibration, qu'il annulerait. Fenêtre
  étroite — il faut que la fenêtre de stimulus refuse ET que le moteur meure dans la même seconde —
  mais elle existe. Le geste explicite (« Abandonner ») le remet à zéro.

## Les tests demandés

```
python src/console/app.py --smoke          -> [console-smoke] VERDICT : OK   (~200 assertions)
python src/core/server.py --smoke          -> 18 VERDICT : OK, dont [smoke-frontiere]
python src/stimulus/registry.py            -> [stim-registry] VERDICT : OK
python src/core/modes/p300_calib.py        -> [p300-calib]    VERDICT : OK
python src/research/app.py --smoke         -> exit 0
```

En plus (CLAUDE.md, et les modules touchés de près), tous à exit 0 : `modes/mi_calib.py`,
`modes/calibration.py`, `modes/marker_calib.py`, `modes/mi.py`, `modes/p300.py`, `modes/errp.py`,
`modes/cvep.py`, `modes/registry.py`, `modes/contract.py`, `mi_models.py`, `p300_models.py`,
`errp_models.py`, `cvep_models.py`, `markers.py`, `config.py`, `acquisition.py --synthetic`,
`cvep_code.py`, `cvep_decoder.py`, `cvep_rcca.py`.

**`data/` intact** : `core.config.empreinte_dossier(DATA_DIR)` prise avant et après la batterie
complète — **43 fichiers**, `sha256 = 1d33bfed…8dfe67`, identique. (Le sha256 est celui du dict
sérialisé trié ; il n'est comparable qu'à lui-même, pas à celui du rapport de la tâche 5, qui
sérialisait autrement.) Zéro dossier temporaire laissé derrière (`calib_candidat_*` : 0).
Une mutation délibérée — « la console écrit elle-même dans `data/` » — y a bien déposé son fichier
témoin, ce qui prouve que le contrôle voit ce genre d'écriture ; il a été retiré et l'empreinte est
revenue à l'identique.
