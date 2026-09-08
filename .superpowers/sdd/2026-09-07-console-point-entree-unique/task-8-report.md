# Tâche 8 — rapport

**Statut : DONE_WITH_CONCERNS.** Cinq commits, `a6af510` → `89ac439`. Tout est vert. Les réserves
sont en bas ; deux d'entre elles appellent une décision qui n'est pas la mienne.

## Ce qui est livré

| Fichier | Ce qui y est fait |
|---|---|
| `src/core/modes/cvep_calib.py` **(neuf)** | `CVEPCalibration`, `entraine_les_deux`/`gagnant` montés depuis `research`, le verdict par McNemar, les chemins horodatés |
| `src/core/modes/cvep.py` | son `Calib` gagne `runtime_cls`, `epoch_s`, `briefing` |
| `src/stimulus/cvep.py` | `--calibrer` : `calib_start`/`cue`/`block_end`/`calib_end`, le programme entrelacé, la sonde à pixels du cercle, la section C7 du smoke |
| `src/research/cvep_calibrate.py` | réduit de **1202 à 758 lignes** : sa moitié d'entraînement appelle `core` |
| `src/core/cvep_code.py` | `blocs_entrelaces` — la règle de protocole que l'appli pygame et la fenêtre partagent |
| `src/core/config.py` | `CVEP_CAL_SETTLE_CYCLES = 4`, hissée depuis la fenêtre |
| `src/core/server.py` | `modele_rcca` dans `_FICHIERS_CANDIDAT` (défaut réel, cf. plus bas) |
| `src/console/calib_page.py` | `acc_ecca` en mesure, `acc_rcca`/`n_discordantes` en détail |

Commits, dans l'ordre — chacun vert avant le suivant :

```
a6af510 Move the interleaved block plan into core, where two windows can share it
86e3312 Let the engine train the c-VEP from the window's own clock
6900296 Give the c-VEP window a calibration mode, on the clock it already publishes
8bada6d Cut research/cvep_calibrate.py down to its pygame half, and show both decoders
89ac439 Move every candidate file to data/, not just the first one
```

## Les tests demandés

```
python src/core/modes/cvep_calib.py     -> [cvep-calib]    VERDICT : OK   (~55 s)
python src/core/modes/cvep.py           -> [cvep]          VERDICT : OK
python src/core/cvep_models.py          -> [cvep-models]   VERDICT : OK
python src/core/cvep_code.py            -> [cvep] autotest : OK
python src/core/cvep_decoder.py         -> [cvep-decoder]  VERDICT : OK
python src/core/cvep_rcca.py            -> [cvep-rcca]     VERDICT : OK
python src/core/modes/marker_calib.py   -> [marker-calib]  VERDICT : OK
python src/stimulus/cvep.py --smoke     -> [cvep-stim]     VERDICT : OK   (73 assertions)
python src/core/server.py --smoke       -> tous OK, dont [smoke-frontiere] 42 fichiers, 0 violation
python src/console/app.py --smoke       -> [console-smoke] VERDICT : OK
```

En plus : `p300_calib.py`, `errp_calib.py`, `mi_calib.py`, `p300.py`, `errp.py`, `mi.py`,
`calibration.py`, `modes/registry.py`, `stimulus/registry.py`, `config.py`,
`research/cvep_calibrate.py`, `research/app.py --smoke` → tous OK.

**`data/` intact** : `core.config.empreinte_dossier` prise avant et après la batterie complète,
**identique** (43 fichiers, même empreinte `4b06d00f02f0708c`). Tous les tests écrivent dans un
`tempfile`, et ceux qui construisent un modèle par le chemin réel le font dans un
`TemporaryDirectory` en repointant `core.modes.cvep.CVEP_MODEL_PATH`.

## L'invariant, sur l'autre axe

**Le chemin partagé est `phase_a`, et il est APPELÉ, pas recopié** — littéralement :

```python
def phase_a(self, t_fin):
    return self.runtime_cls_du_mode.phase_a(self, t_fin)
```

C'est la méthode du décodage, non liée, avec la calibration pour `self`. Elle n'a besoin, sur son
`self`, que de `code_len`, `_ref_ts` et `_ref_refresh` — que `CVEPCalibration` porte sous les
**mêmes noms**, ce qui n'est pas une coïncidence mais la condition de l'appel. Un forwarder jumeau
existe pour `_phase_et_cause`, que `phase_a` consulte.

**LE test**, `[LE TEST]` dans `cvep_calib.py` : une course de rendu de 378 frames incluant une
frame sautée, les mêmes marqueurs donnés à un vrai `CVEPRuntime` et à la calibration, les deux
reconstructions comparées **par les valeurs** à chaque frame. Trois assertions l'entourent pour
qu'il ne soit pas vacant :

- la course **balaie les 63 positions du code** (63/63 distinctes), pas seulement les bords de
  cycle où la réponse est 0 par construction ;
- **le témoin de discrimination** : une phase translatée d'UNE frame ne passerait pas la
  comparaison — calculé et asserté *dans* le test ;
- et cette phase est bien celle que l'écran **affiche** : écart exact avant tout saut, ≤ 1 frame
  après.

### Les deux preuves par mutation, et ce qu'elles disent chacune

| Mutation | Résultat |
|---|---|
| `phase_a` translatée d'une frame | **ROUGE**, 378 désaccords sur 378, **plus toute la séance** : la garde de phase refuse alors chaque époque, 51 refus, 0 modèle |
| `phase_a` **réimplémentée** (mêmes nombres aujourd'hui) | **ROUGE sur la seule assertion structurelle** — la comparaison de valeurs reste verte |

La seconde est le résultat le plus utile. Une réimplémentation à l'identique passe le test de
valeurs, par construction : c'est la **dérive future** qu'on interdit, pas l'écart du jour. D'où
une assertion `ast` qui refuse toute **arithmétique modulaire** dans la classe — la phase se replie
sur `code_len`, donc toute copie de la formule en contiendrait une. Le message le dit.

### Côté fenêtre : trois mutations, toutes rouges

| Mutation | Assertion qui rougit |
|---|---|
| le `cue` annonce la cible VOISINE | `[C7] chaque cue porte la cible RÉELLEMENT CERCLÉE` (lue dans les pixels du cercle vert) |
| l'horloge se TAIT pendant le settle | trois assertions `[C7]`, dont « l'horloge bat SANS INTERRUPTION » |
| `push_sample` remonté au-dessus de `display.flip()` | **six** assertions : C1, C2 **et C7**, toutes à « position 62 au lieu de 0 » |

## Sur la tolérance du meilleur test du dépôt : elle n'a pas bougé

Le brief demandait de m'arrêter si `--calibrer` obligeait à relâcher la sonde à pixels. **Il ne l'a
pas fait.** La section C7 rejoue exactement la même table de trois images consécutives et exige
**zéro** frame d'écart, comme C1 et C2. Les marqueurs de protocole (`calib_start`, `cue`,
`block_end`, `calib_end`) sont **écartés du filtre**, pas tolérés : ils ne suivent aucun bord de
cycle, et les inclure aurait été le seul geste qui aurait obligé à desserrer quoi que ce soit. Pour
pouvoir les écarter sans affaiblir, `push_trace` retient désormais le NOM de l'événement au lieu de
`None` — C1 et C2 ne lisent pas ce champ, leurs assertions sont inchangées au caractère près.

## Ce que j'ai dû arbitrer

1. **La géométrie d'époque est REDÉCLARÉE ici, et c'est le seul cas du chantier.** `CVEPRuntime`
   n'expose ni `pre_s` ni `post_s` — délibérément, il ne découpe rien. Il n'y a donc **rien à
   lire**, et le socle aurait levé. `CVEPCalibration` les surcharge : `pre_s = code_len / refresh`
   (un cycle entier, la longueur que `CVEPModel.fit` attend), `post_s = 0`. Ce que la lecture
   perdue est remplacée par : `phase_a`.

2. **`refresh` n'est pas une constante — il vient de l'ÉMETTEUR**, marqueur par marqueur, et il
   fixe la LONGUEUR de l'époque. D'où deux décisions : `pre_s` se calcule sur le **premier**
   `refresh` de la séance (deux longueurs dans le même jeu ne s'empileraient même pas), et un
   marqueur qui s'en écarte de plus de 1 Hz est REFUSÉ — la garde de `maj_reference`, transposée
   au cas où il n'existe pas encore de modèle. Testé à **80 Hz** : la séance lit ce
   rafraîchissement, raccourcit son époque, et le modèle produit est accepté par un mode dont
   l'émetteur affiche 80 Hz **et refusé** par un émetteur à 60 — c'est ce refus-là qui rend le
   test falsifiable.

3. **La garde de phase est une DÉFENSE EN PROFONDEUR, et je l'écris comme telle.** Après que le
   marqueur a posé la référence à `ts`, `phase_a(ts)` vaut 0 par construction. Le refus ne peut
   donc pas mordre aujourd'hui. Je l'ai gardé quand même, avec ce statut écrit noir sur blanc —
   c'est exactement celui de la garde `age < 0` de `_phase_et_cause`, que `cvep.py` documente déjà
   comme « INATTEIGNABLE par le chemin du moteur, gardée quand même ». Ce que j'ai refusé de
   faire : prétendre qu'elle attrape autre chose.
   Corollaire tiré d'un échec de test : `_refresh_lisible` **rend sa raison** au lieu de la dire,
   pour qu'un marqueur refusé produise UN message et UN compteur, pas deux.

4. **`block_end` — le `round_end` du P300, transposé.** Entre deux blocs, `CVEP_CAL_SETTLE_CYCLES`
   cycles passent pendant que le regard cherche la nouvelle cible : ils n'ont aucune
   vérité-terrain. Sans `block_end` ils hériteraient de la cible du bloc précédent — même nombre
   d'époques, proportions plausibles, aucun compteur. Ils sont comptés à part
   (`cycles_hors_bloc`) et **jamais imprimés** : ~4 par bloc est le protocole, pas un incident.
   Le compteur ne sert qu'au refus, où il nomme la panne la plus banale : « la fenêtre
   tourne-t-elle bien avec `--calibrer` ? ».

5. **L'ordre au bord d'un cycle est un contrat**, et il tient à un décalage d'un cycle : `cycle`
   d'abord, puis `block_end`, puis `cue`. Le marqueur de cycle ferme le cycle PRÉCÉDENT ; publier
   le `cue` avant lui ferait entrer, à chaque bloc, une époque prise pendant que le regard se
   déplaçait encore. Asserté sur le déroulé réel.

6. **`CVEP_CAL_SETTLE_CYCLES = 4`, pas 2.** Le protocole validé de `research/cvep_calibrate.py`
   obtenait sa transition en DEUX morceaux : un écran « Change de cible » de 1,8 s **puis** 2
   cycles de settle (2,1 s). La fenêtre ne peut pas se permettre l'écran : elle doit continuer à
   faire clignoter le code, sinon l'horloge se tait et la référence du moteur périme
   (`CVEP_PEREMPTION_CYCLES` = 3,15 s — l'écran de 1,8 s passait tout juste). Les deux morceaux
   fusionnent donc en cycles jetés, à durée totale équivalente (4,2 s contre 3,9 s).

7. **Un défaut réel trouvé au passage, hors périmètre annoncé : `_FICHIERS_CANDIDAT`.** Le c-VEP
   est le seul mode à produire DEUX modèles par séance. La constante n'en connaissait qu'un : le
   `.npz` rCCA n'aurait été ni déplacé par « Enregistrer », ni supprimé par « Jeter ». Il vivait
   dans le dossier temporaire que `close()` efface — l'étudiant perd la moitié d'une calibration
   en croyant l'avoir enregistrée, sans un mot. Corrigé et testé.
   **Et le premier test que j'ai écrit pour ça était tautologique** : il construisait sa fixture
   depuis la constante qu'il vérifiait, donc retirer une clé retirait le fichier du même geste et
   le test restait VERT (mesuré). Réécrit avec la liste des clés en dur ; la mutation rougit
   maintenant deux assertions.

8. **`blocs_entrelaces` déménage dans `core/cvep_code.py`.** La fenêtre doit jouer l'entrelacement
   (mesuré 2026-07-20 : sans lui, 34 % sur le premier tiers contre 66 % sur le dernier, et les
   deux dernières cibles passaient pour les meilleures), et `stimulus` n'a pas le droit d'importer
   `research`. Le déménagement est la règle du dépôt ; une seconde copie aurait divergé sans que
   personne le voie — les deux séances seraient restées plausibles. Même geste, même raison, que
   `core/errp_track.py` à la tâche 1.

9. **Le fixture EEG choisit `fs = 240 Hz`, pas 250.** À 250 Hz, `63 × 250 / 60 = 262,5` n'est pas
   entier : un tampon fabriqué en concaténant des cycles dérive d'un demi-échantillon par cycle
   contre les horodatages des marqueurs (0,5 × 90 = 180 ms sur une séance), et le test mesurerait
   sa propre fixture. `63 × 240 / 60 = 252` pile. Écrit sur la fixture, avec les chiffres.

10. **Le test `smoke-calib-refus` du moteur a changé de sujet.** Il visait « une calibration
    déclarée dont le runtime n'est pas livré », et utilisait le c-VEP comme cobaye — le dernier
    des trois. Il n'y a désormais **plus aucun mode réel dans cet état**. Le supprimer aurait
    laissé sans test le refus qui protège le prochain mode déclaré avant d'être jouable ; il porte
    donc maintenant sur un `ModeSpec` **fabriqué**, injecté puis retiré du registre, doublé d'une
    assertion que les six calibrations réelles sont bien toutes jouables.
    ⚠️ Écart mesuré au passage : soumettre un vrai `start_calibration` accepté à ce moteur froid
    créait son dossier candidat et laissait une commande en file — deux contrôles plus bas
    rougissaient. Le pendant est donc vérifié **sans rien soumettre**.

## Sur les deux décodeurs : aucun gagnant nommé

`verdict()` compose une qualité (contre le hasard à **1/6 = 16,7 %**, jamais 50 %) et
`phrase_comparaison(mn)`, qui rend le **TEST** : « les deux décodeurs sont INDISCERNABLES sur cette
séance (McNemar p = 0,727 sur 8 décisions discordantes (3 eCCA seul, 5 rCCA seul)) : ne choisis pas
sur l'écart des deux pourcentages, il est dans le bruit ». Vérifié sur les chiffres réels de la
séance de référence (22/37 contre 24/37 → p = 0,7265625), dans les deux sens sur un écart
défendable, et sur le cas « rien à mesurer ».

La console reçoit `acc_ecca` comme mesure qui décide et `acc_rcca` en détail, à côté de
`n_discordantes`. **Choisir l'eCCA pour la ligne principale ne choisit rien** — les deux sont
indiscernables — et c'est écrit dans le commentaire de `MESURES`. Les deux tables restent indexées
**par clé de résultat**, jamais par `mode_id`.

La phrase d'honnêteté dit les quatre choses de `docs/recette.md` §2.9, vérifiées assertion par
assertion : hasard à 16,7 % ; le 59,5 / 64,9 % est **hors ligne** ; ce que le moteur produira est
un **couple ~46 % d'émission / ~71 % de justesse à l'émission** (k = 2, seuils 0,26/0,09) ; et le
c-VEP **n'a jamais été décodé au casque par le moteur**. Un test refuse explicitement les mots des
trois autres modes.

## Ce que je n'ai pas touché

Ni le décodage, ni ses seuils (`CVEP_CORR_MIN`, `CVEP_MARGIN`, `CVEP_RCCA_*`), ni sa géométrie de
décision (`CVEP_DECISION_CYCLES`, `CVEP_VOTE_LEN`, `CVEP_MIN_VOTES`), ni `phase_a` elle-même, ni la
tolérance de la sonde à pixels. Aucune hypothèse réfutée n'est rouverte : ni *dynamic stopping*, ni
codes Gold distincts.

## Réserves (le WITH_CONCERNS)

- 🔴 **Le compteur `marqueurs_chauffe` du socle est TROMPEUR pour ce mode, et je ne l'ai pas
  corrigé.** Pendant les ~15 s de chauffe, la fenêtre publie ~14 marqueurs d'horloge (elle
  continue de clignoter, exprès). Le socle les compte comme « époques jetées » et imprime « la
  dérive DC les rendrait sans valeur, la fenêtre devrait attendre avant son premier essai » — or
  ce ne sont pas des époques, et la fenêtre attend déjà (aucun bloc ne démarre avant la fin de la
  chauffe, `frame_prog0`). Le message est faux sans être dangereux. Le corriger proprement
  demanderait au socle de distinguer « marqueur qui délimite » de « marqueur qui informe », ce qui
  touche `marker_calib.py` — hors de mon périmètre, et à faire avec ses trois sous-classes sous
  les yeux.

- 🔴 **La fenêtre peut toujours prendre de l'avance sur la chauffe du moteur** (réserve héritée
  des tâches 4 et 7, entière). Elle attend `ATTENTE_MOTEUR_S` à partir de SON lancement ; le
  moteur compte ses 15 s à partir de `start_calibration`. Il n'existe aucune poignée de main. Si
  la console lance la fenêtre AVANT de soumettre la commande, les premiers blocs tombent dans la
  chauffe : jetés, comptés, dits — mais la séance est plus courte que ce que les deux écrans
  annoncent. **L'ordre correct appartient à la tâche 5/6.**

- ⚠️ **`--cycles` rend fausse la durée annoncée.** La calibration n'expose aucun `Param` : ni le
  nombre de cycles, ni le settle. `duree_protocole_s` vaut pour les défauts, et la fenêtre lancée
  à la main avec `--cycles 6` sera deux fois plus courte que ce que la console annonce. Le moteur
  ne peut pas le savoir — il ne mène pas le protocole. Le `help` de l'option le dit ; l'exposer
  comme réglage de calibration serait le geste propre, et c'est du câblage console.

- ⚠️ **Le vol de marqueurs mode ↔ calibration est maintenant COUVERT pour le c-VEP** — vérifié :
  `_calibration_lit_les_marqueurs(cvep) == True` et `marker_epoch_s = 2,1 > 0`, donc les deux
  refus de `server.submit` s'appliquent. Ce n'est pas un travail de cette tâche, c'est une
  conséquence de la livraison du `runtime_cls` ; je le note parce que la réserve 🔴 du carnet
  listait le c-VEP comme non couvert.

- ⚠️ **`research/cvep_calibrate.py` reste un SECOND chemin vers un modèle c-VEP**, avec son
  épochage propre (l'horloge pygame, `acq.get_epoch`) et une écriture directe dans `data/` qui
  contourne la garde de la tâche 5. Réduit de 444 lignes et partageant désormais tout
  l'entraînement, mais **pas l'épochage** — c'est-à-dire précisément ce que ce chantier existe
  pour retirer. Même statut que ses deux jumeaux P300 et ErrP : **à trancher à la revue finale.**

- ⚠️ **`CLAUDE.md` et `docs/` ne connaissent ni `cvep_calib.py`, ni le protocole
  `calib_start`/`cue`/`block_end`/`calib_end` du c-VEP.** `CLAUDE.md` pointe encore
  `python src/research/cvep_stimulus.py --smoke`, un chemin qui n'existe plus depuis la tâche 1.
  Le contrat PUBLIC a bougé une troisième fois (après le P300 et l'ErrP). Tâche 11.

- ⚠️ **`[C3]` du smoke de la fenêtre est sensible à la charge de la machine.** Il compte des
  frames délibérément retenues et je l'ai vu rougir une fois (« 3 cales posées → 4 comptées »)
  sous une mutation qui n'avait rien à voir, puis redevenir vert. Je n'y ai pas touché — ce n'est
  pas mon périmètre et la tolérance est déjà argumentée dans le fichier — mais c'est le genre de
  rouge intermittent que ce dépôt vient d'apprendre à ne pas ignorer.

- ⚠️ **Rien de tout ceci n'a vu un casque.** Le protocole est vérifié de bout en bout entre les
  deux processus, sur un tampon EEG fabriqué qui porte un vrai c-VEP synthétique. Ce que la séance
  réelle dira, et que ces tests ne peuvent pas dire : si 4 cycles (4,2 s) suffisent à trouver la
  nouvelle cible cerclée, si 2,8 min de grésillement sont tenables sans clignement, et si le
  modèle appris par ce chemin-là vaut celui de l'appli pygame. **Le c-VEP n'a toujours jamais été
  décodé au casque par le moteur**, et cette calibration ne change rien à ça — elle rend
  seulement la recette 2.9 exécutable sans l'appli pygame.
