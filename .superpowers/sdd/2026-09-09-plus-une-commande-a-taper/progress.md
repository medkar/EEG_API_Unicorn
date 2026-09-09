# SDD ledger — plan: docs/superpowers/plans/2026-09-09-plus-une-commande-a-taper.md

Chantier « plus une seule commande à taper ». Spec `f12ff78`, plan `79508cf`/`fef9f43`.

**Mode d'exécution choisi par l'utilisateur (2026-09-09) : HYBRIDE, sans point d'arrêt, et il veut
MINIMISER LE TEMPS.** Donc **quatre dispatches seulement** (contre huit au chantier précédent) :

| tâche | qui |
|---|---|
| T1 test d'inventaire + CLAUDE.md | **en ligne** — le scanner de `server.py` est du terrain connu |
| T2 `MesureRuntime` | sous-agent |
| T3 contrôle alpha de bout en bout | sous-agent |
| T4 source à l'ouverture | **en ligne** |
| T5 options de lancement + journal | **en ligne** |
| T6 page « flux sortant » | **en ligne** |
| T7 enregistrement de séance | **en ligne** |
| T8+T9 SSVEP de bout en bout | sous-agent (un seul brief, fenêtre + mesure) |
| T10 les retraits | sous-agent — piège d'ordre sur `ui.py` |
| T11 documentation | **en ligne**, relue |

⚠️ **T1 se termine ROUGE, volontairement**, en nommant six fichiers. T10 doit le rendre VERT.

## Journal

- **T1 : complete** — `e293dbd`, en ligne. Le scan de `research/` est ROUGE sur six fichiers, comme
  voulu : `alpha_check`, `live_ssvep`, `ssvep_analyze`, `ssvep_guided`, `ssvep_stimulus`, `ui`.
  ⚠️ **Six, pas cinq** : `ui.py` s'est ajouté à l'inventaire, et huit fichiers de `archive/`
  l'importent. La contrainte est aussi entrée dans `CLAUDE.md`.
- **T2 : complete** — `ea0c6b6`, sous-agent. `MesureRuntime` + refus d'une 2e activité dans les deux
  sens et aux deux instants. Réserve portée : `etape` reste vide sur une mesure, donc un
  `_maybe_beep` recopié serait muet.
- **T3 : complete** — `c4f3973`→`9399dbd`, sous-agent. Contrôle alpha de bout en bout. **Deux gardes
  que l'original n'avait pas** : le détrend est tenu (sans lui un offset DC de 10⁵ µV fait tomber le
  ratio de 4,44 à 2,26 et ferait échouer toute séance, casque parfait compris), et quatre voies
  plates sont refusées (leur ratio 10⁻²⁷/10⁻²⁷ franchissait la barrière une fois sur deux — « le
  montage est bon » sur un câble débranché). Le top sonore est assis sur `classe`, pas `etape`.
  ⚠️ Il a archivé `alpha_check.py` lui-même : la T10 n'a plus que deux fichiers à archiver.
  Compteur : **six → cinq**.
- **T4 : complete** — `b91b1a0`, en ligne. Écran de départ, aucun repli automatique.
  ⚠️ Vérifié : **aucun repli n'existait déjà** dans `acquisition.py`/`server.py` — la garde sert à
  empêcher qu'on en ajoute un.
- **T5 : complete** — `3e3a51d`, en ligne. Options de lancement + case « Journal de séance »,
  cochée par défaut, et seulement là où le registre déclare que la fenêtre sait journaliser.
  ⚠️ Seul le c-VEP a `--log` ; le P300 et l'ErrP ne l'ont pas, et ce n'est pas un oubli.
  `seances/` gitignoré, hors de `data/`.
- **Correctif hors plan** — `36fdc5c` : le test de cadence c-VEP rougissait 1 fois sur 3 (cause
  connue depuis la revue du 2026-09-08, jamais corrigée). Borne inférieure au lieu d'une égalité ;
  la garde mord toujours (0 cale → rouge), six lancements propres après.
- **T6 : complete** — `0bbf656`, en ligne. `console/flux_page.py` : les flux LSL du réseau, lus
  COMME UN CLIENT. Trois assertions ferment la porte de l'état interne, dont celle qui prouve
  vraiment (un état complet arrive, le panneau reste vide) — mutation faite, elle seule rougit.
  ⚠️ Deux coutures injectables (`decouvrir`, `ouvrir`) ajoutées **après un premier jet qui n'en
  avait pas** : le smoke résolvait pour de vrai et trouvait les 5 flux du moteur qu'un AUTRE bloc
  du même smoke fait tourner.
- **T7 : complete** — `5634cec`, en ligne. `start_enregistrement`/`stop_enregistrement`, JSONL dans
  `seances/`, **une ligne par décision PUBLIÉE** (identité de `output()` — sinon un mode qui émet
  44 % du temps se relirait à 100 %). `stimulus/cvep.py` importe désormais `config.SEANCES_DIR` au
  lieu de recomposer le chemin. Empreinte du vrai `data/` identique avant/après
  (43 fichiers, `42120328…`), `seances/` réel intact (0 fichier).
  🔴 **Trouvé en testant** : l'accusé de `start_enregistrement` promettait un `chemin` qui pouvait
  ne jamais exister — deux clics dans la même fenêtre de sondage sont tous deux acceptés, la boucle
  refuse le second. Le nom du fichier est maintenant décidé par la BOUCLE et lu dans `snapshot()`.
  C'est une instance de plus du constat parqué « la console prend `accepted` pour “ça a démarré” ».

- **T8+T9 : complete** — `f648d74`, sous-agent. **UN seul commit** : le selftest de
  `stimulus/registry.py` refuse une fenêtre orpheline ET une mesure sans fenêtre, donc chaque
  moitié seule est ROUGE. La fenêtre déménage en `stimulus/ssvep.py` et gagne `--guide`
  (`calib_start`/`repos`/`cue`/`calib_end`) ; `core/modes/ssvep_mesure.py` porte la mesure.
  Compteur frontière : **cinq → trois** (restent `live_ssvep`, `ssvep_analyze`, `ui`).
  ⚠️ **Trouvé un chantier INTERROMPU en arrivant** (`git status` sale, snapshot du prompt périmé) :
  l'essentiel était écrit, mais `console/app.py --smoke` **plantait** sur un `MARKER_STREAM_DEFAULT`
  jamais importé, et `alpha.py` rougissait (il affirmait `MESURES == ["alpha"]`, remplacé par le
  RANG : l'alpha est la première, parce que c'est la barrière).
  Les **deux preuves du rouge** faites : compter les fenêtres → n=24 devient **168** et l'intervalle
  s'effondre de 0,19 à **0,03**, et c'est **le seul rouge du dépôt** (console, server et
  ssvep_guided restent verts sous la mutation) ; bloc contigu → la garde d'entrelacement mord des
  deux côtés. Empreinte du vrai `data/` identique (43 fichiers, mtime max inchangé), `seances/` à 0.
  🔴 **Désaccord protocole/mode trouvé, DIT, non corrigé** : le σ du rejet d'artefact est pris sur
  **8 voies** dans la mesure et sur les **4 occipitales filtrées** dans le mode. Écart ANTÉRIEUR
  (le monolithe utilisait déjà `sigma_from_block`), donc c'est la règle sous laquelle 100 %/44 %
  ont été mesurés — l'aligner rendrait le prochain chiffre incomparable. Documenté en tête de
  `ssvep_mesure.py` ; **décision à prendre hors chantier**.

- **T10 : complete** — `1fd659d`→`ea25e62` (5 commits), sous-agent. **`[smoke-frontiere] VERDICT :
  OK`** : 57 fichiers scannés, **0 violation**. Le test de la T1 est vert, compteur **trois → zéro**.
  L'ordre contraint a été tenu : `ui.py` traité seul et en premier, les **12** smokes de `archive/`
  verts avant tout le reste. ⚠️ Déménagements faits au `git mv` : **l'étape « suppressions en
  dernier » n'a pas d'objet**, il n'a jamais existé d'instant où original et copie coexistaient.
  🔵 **`ssvep_analyze.py` RESTE au banc d'essai** — question tranchée en le lisant : son import ne
  servait aucun enregistrement live, seulement `_filter` sur une acquisition jamais démarrée
  (`prepare_session()` est dans `start()`, jamais atteinte). Il emprunte désormais le filtrage du
  moteur via `ssvep_mesure.acquisition_de_reference()`, rendue **publique** pour la raison écrite
  dans sa propre docstring (« pour que le banc d'essai n'ait plus à connaître l'acquisition »).
  Sorties **octet pour octet identiques** sur les 4 `ssvep_guided_*.npz` : aucun chiffre n'a bougé.
  🔴 **Le risque `data/` était réel et il est traité** : `live_ssvep.py --guided` ÉCRIT dans `data/`.
  Sa garde était déjà bien placée (avant le `np.savez`), mais son smoke ne jouait pas ce chemin-là.
  Il joue maintenant **les deux** et vérifie l'empreinte. Preuve du rouge faite : garde neutralisée
  → le smoke rougit en nommant `ssvep_guided_20260909-144750.npz` ; restauré, fichier supprimé,
  empreinte revenue à la baseline. Empreinte du vrai `data/` **identique** début/fin
  (43 fichiers, sha1 `5b6bf6c3…`), `seances/` à 0.
  🟡 `archive/README.md` portait **deux faussetés antérieures**, corrigées contre la source :
  `--model` est sur **sept** fichiers (pas cinq), et `cvep_pilot.py` **défaut vers un chemin FIXE**
  (`CVEP_MODEL_PATH`) — c'est la référence locale de la séance, et `CLAUDE.md` le disait déjà.

## Réserve à porter

- 🔴 **La T3 a empiété sur la T10** en archivant `alpha_check.py`. C'est justifié (le compteur ne
  pouvait pas bouger autrement) mais la T10 doit en tenir compte : il lui reste `live_ssvep.py`,
  `ssvep_analyze.py`, `ssvep_guided.py` (après T8/T9) et surtout **`ui.py`, dont l'ordre est
  contraint**.
- 🟡 **T7 : la règle « une ligne par décision publiée » n'est pas structurelle.** Elle repose sur
  une propriété des six modes (publier reconstruit le dict de sortie), documentée dans
  `_Enregistrement` et pinnée par un runtime factice — pas sur un contrat déclaré. Le mode #7 qui
  muterait sa sortie en place perdrait des lignes EN SILENCE. La version étanche serait un
  compteur de publications dans `ModeRuntime` ; ça touche les six modes.
- 🔴 **Pour la T10, ordre confirmé** : après T8/T9 il ne reste QUE `live_ssvep.py`,
  `ssvep_analyze.py` et **`ui.py`, dont l'ordre est contraint**. `ssvep_guided.py` n'est plus à
  archiver — il est réduit à son analyse et ne viole plus la règle.
- 🟡 **Pour la T11, deux faussetés que T8/T9 ont CRÉÉES** : `README.md:441` range encore
  `ssvep_stimulus.py` dans le socle pygame de `research/` (le fichier n'y est plus), et
  `docs/markers.md` ne dit rien des marqueurs du run guidé — décision assumée (personne ne
  réimplémente cet émetteur, le mode SSVEP de décodage ne consomme aucun marqueur), mais le tableau
  « chauffe » de `markers.md:353` gagnerait une ligne. ⚠️ `examples/unity/README.md` citait une
  commande **cassée** par le déménagement : corrigé dans `f648d74`, mais **ce dossier n'est dans la
  liste de fichiers d'aucune tâche et n'est couvert par aucun test**.
- 🟡 **Pour la T11** : la page « Ce que voit ton application » et le bouton d'enregistrement n'ont
  aucune ligne dans `README.md`, `docs/SPEC.md` ni `docs/recette.md`. Le test **2.9 doit citer les
  DEUX fichiers**, pas seulement le journal de la fenêtre. Et `CLAUDE.md` cite encore
  `python src/research/app.py`, qui n'existe plus.
- 🟡 **Pour la T11, trois chemins morts laissés par la T10**, à jour dans le code mais pas dans les
  trois documents que la T11 réécrit : `README.md:445` range encore `live_ssvep.py` (et
  `controller.py`) dans `research/` ; `CLAUDE.md:318` et `docs/SPEC.md:706` citent
  `research/ui.py:signal_check`, désormais `archive/ui.py:signal_check`. Les **17** références
  équivalentes dans le code ont été repointées (`ea25e62`).
- 🟡 **`ssvep_analyze.py` filtre à `fs=250` quel que soit le `fs` du fichier lu.** Antérieur à la
  T10 et sans effet aujourd'hui (board synthétique et Unicorn sont tous deux à 250 Hz — c'est
  pourquoi la sortie est restée identique après le changement d'import). Un enregistrement pris à
  un autre `fs` serait filtré de travers **en silence** ; `ssvep_mesure` a `longueur_bloc_attendue`
  pour refuser ce cas, cet outil-ci n'a pas d'équivalent. Hors périmètre T10.
