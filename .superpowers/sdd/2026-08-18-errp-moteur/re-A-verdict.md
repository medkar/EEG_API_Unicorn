# Re-revue de la tranche A — `src/core/modes/errp.py`

Lecture seule, **aucun programme exécuté**. État relu : `HEAD` (`faa19c1`), c'est-à-dire
`e56e45f` (implémenteur) + `0dd318a` (coordinateur) + les retouches suivantes. Références
croisées relues : `modes/p300.py`, `modes/contract.py`, `modes/runtime.py`, `modes/registry.py`,
`core/server.py` (`_nom_flux_marqueurs`, `_ouvre_marker_inlet`, `_libere_marker_inlet`),
`core/errp_decoder.py`, `core/p300_decoder.py` (`epoch_from_stream`), `core/lsl_io.py`,
`core/config.py`, `console/live_views.py`, `console/params_form.py`, `console/app.py`.

**Bilan : 11 ADDRESSED · 0 PARTIEL · 0 NON TRAITÉ · 0 RÉGRESSION · 3 défauts NOUVEAUX
(tous des affirmations de commentaire, aucun défaut de comportement).**

Les deux corrections décisives ont été vérifiées ligne à ligne, pas sur la foi du rapport : la
première est réellement discriminante (les fixtures passent maintenant un `lsl_ts` volontairement
décalé de +0,8 s, sur le patron de `p300.py:859`), la seconde borne réellement le support ET la
fixture porte réellement une dérive sur **un seul tampon continu**, la renormalisation par tampon
ayant disparu.

---

## Le tableau des 11 verdicts

| # | Constatation | Verdict | Par quelle ligne |
|---|---|---|---|
| C1 | Horodatage publié = boucle du moteur, pas le feedback | **ADDRESSED** | `errp.py:514`, `:516`, `:535`, `:543`, `:554` ; tests `:1056`+`:1063`, `:1145`+`:1156`, `:1282`+`:1293` |
| C2 | σ du repos mesuré sur 5,0 s contre une époque de 0,9 s | **ADDRESSED** | `errp.py:414-418` ; fixture `:1315-1402`, assertion `:1397` |
| I3 | La branche « rest » de `tick` jamais exercée | **ADDRESSED** | test `:995-1003` (phase « rest » À L'ENTRÉE, file non vide, `appels_murs`) |
| I4 | Panne n°8 non reliée au chemin réel | **ADDRESSED** | tests `:1174` (valeur des compteurs) et `:1187-1204` (alarme par `tick`) |
| I5 | Médiane sur ~40 fenêtres recouvrantes à 96 % | **ADDRESSED** | même correctif que C2 : `errp.py:418` (recouvrement 96 % → 78 %) |
| I6 | `errp` consomme des marqueurs sans exposer `stream_in` | **ADDRESSED** | `errp.py:663-674` ; assertions `:807`, `:813`, `:816`, `:931` (mais cf. **N2**) |
| I7 | « Refaire le repos » désarme l'alarme | **ADDRESSED** | `errp.py:318-321` + cumuls `:228-229`/`:537-541`/`:350-351` ; test `:1225-1243` |
| M8 | `_marqueurs_chauffe` compte tous les événements | **ADDRESSED** | `errp.py:486-489` ; test `:1008-1012` |
| M9 | « le premier reçu APRÈS le repos » est faux | **ADDRESSED** | `errp.py:499-502` + commentaire `:492-498` ; test `:1022` |
| M10 | Aucun plancher sur le σ de référence | **ADDRESSED** | `errp.py:140`, `:429-439` ; test `:1408-1426` |
| M11 | Le test d'alignement court-circuite `tick` | **ADDRESSED** | `errp.py:1280-1282` → `:1287` et `:1293` |

Aucune constatation n'est PARTIEL, NON TRAITÉ ni RÉGRESSION : il n'y a donc pas de section par
constatation ci-dessous, seulement les trois défauts nouveaux. Le détail de vérification des deux
Critical suit quand même, parce que c'est ce qui décidait du reste.

---

## Vérification prioritaire n°1 — CRITICAL 1, l'horodatage : la correction TIENT

**La production.** `_run_step` (`:504-514`) ne transmet plus `lsl_ts` : `self._traiter_feedback(engine, ts)`.
La signature de `_traiter_feedback` (`:516`) n'a plus de paramètre `lsl_ts` — aucune ligne du corps
ne peut donc republier « maintenant » par accident. Les trois `_publish` passent `lsl_ts=ts`
(`:535` époque perdue, `:543` artefact, `:554` verdict). `DecodedErrPPublisher.push`
(`lsl_io.py:492-495`) le pose bien en horodatage du chunk.

**Le test est-il devenu discriminant ?** Oui — c'était la question. Tous les `tick` du chemin de
publication passent désormais un `lsl_ts` volontairement éloigné :

| appel | marqueur | `lsl_ts` passé |
|---|---|---|
| `:1056` | 105,0 | 105,8 |
| `:1083` | 106,0 | 106,8 |
| `:1093` | 107,0 | 107,8 |
| `:1105` | 5,0 | 5,8 |
| `:1123` | 108,0 | 108,8 |
| `:1145` | 110,0 **et** 110,1 (même lot) | 110,9 |
| `:1282` | 1002,0 | 1002,8 |
| `:1362`/`:1373`/`:1395` | fixture dérive | +0,8 s |

Les trois assertions correspondantes rougissent bien si l'on republie `lsl_ts` :
`:1063` (`105,8 ≠ 105,0`), `:1156` (`[110.9, 110.9] ≠ [110.0, 110.1]` — c'est elle qui ferme le
trou des deux feedbacks du même lot) et `:1293` (`1002,8 ≠ 1002,0`). L'assertion `:1063` n'est
donc plus tautologique. Le patron est bien celui de `p300.py:859` (« `lsl_ts` VOLONTAIREMENT loin
du round_end »), qui a été relu pour comparaison.

## Vérification prioritaire n°2 — CRITICAL 2, le σ du repos : la correction TIENT

**Le support est borné.** `:414-418` :

```python
n_epoque = int(round((self.pre_s + self.post_s) * engine.acq.fs))
bloc = engine.recent
if bloc is None or len(bloc) < n_epoque:
    return False
sig = np.asarray(bloc[-n_epoque:], dtype=float).std(axis=0)
```

225 échantillons (0,9 s) au lieu de `EngineServer.keep` = 1250 (5,0 s), et le plancher
`engine.acq.margin_n` a disparu au profit de `n_epoque`. Le couplage au `MI_IMAGERY_S` d'un autre
mode est rompu. Le message du repos (`:441-443`) annonce maintenant le nombre d'échantillons de la
fenêtre, donc l'erreur redeviendrait lisible dans le journal.

*(Nuance sans conséquence ici : `int(round((pre+post)*fs))` peut différer d'UN échantillon de ce
que `epoch_from_stream` découpe, `int(round(pre*fs)) + int(round(post*fs))` — identiques à 250 Hz
(50+175 = 225), écart de 1 à 125 Hz. Sans effet sur un σ.)*

**La fixture porte-t-elle une DÉRIVE, sur un seul tampon ?** Oui, et c'est vérifiable sans
exécuter :

- `:1348` un **unique** tampon continu de 20 s : `continu = bruit_avec_derive(5000, 250, rng, drift_uv=20.0, ref_n=n_keep)` ;
- `:1317-1333` `sous_5hz` prend désormais `ref_n` et calibre l'amplitude sur une fenêtre de
  **1250 échantillons** — c'est-à-dire que la renormalisation tampon-par-tampon, le geste exact
  qui effaçait le biais, n'est plus possible ;
- `:1358-1362` le repos **glisse dans ce tampon** par pas de 0,2 s (11 fenêtres), comme
  `period_s()` le ferait ;
- `:1371` et `:1393` les deux époques sont des **tranches du même tampon**, pas un tirage neuf.

**L'assertion peut-elle rougir ?** Oui, avec une marge confortable. Le clignement injecté
(`:1389`, gaussienne de 150 µV crête, σ_t = 0,12 s) porte σ ≈ 53 µV sur les 225 échantillons de
l'époque. Avec le support borné, σ_repos ≈ 10 µV → seuil 4 × 10 ≈ 41 µV → **rejeté**. Avec le
support de 5,0 s (la mutation), la dérive de 20 µV gonfle σ_repos à ≈ 20 µV → seuil ≈ 80 µV →
**non rejeté**, donc `:1397` (`art_clign == 1 and e_clign == -1`) rouge. Le facteur ×2 annoncé par
l'implémenteur est cohérent avec la calibration de la fixture.

L'ancienne preuve (l'époque SAINE non rejetée, `:1375`) est conservée : les deux défauts,
représentation et support, poussent en sens opposés et sont donc tenus par deux assertions
opposées dans **la même** fixture. C'est la bonne construction.

> **À VÉRIFIER PAR EXÉCUTION** (rien ne l'a été de mon côté) :
> `python src/core/modes/errp.py` — attendu : `[errp] VERDICT : OK`, exit 0, ~84 lignes `OK`.
> Puis, pour la non-régression du contrat de mode :
> `python src/core/server.py --smoke` — attendu exit 0 (l'ajout de `Param(stream_in)` traverse
> `registry.check()`, qui exige un `help` non vide et des `choices` non vides : les deux sont
> satisfaits, `errp.py:663-674`).

## Cohérence avec ce que les autres tranches ont livré

- **`echec_oof_`** — lu correctement : `errp.py:276` `cause = getattr(self.model, "echec_oof_", None)`,
  avec repli sur une formulation générale. Le `getattr` est justifié : `ErrPModel.__init__`
  (`errp_decoder.py:186`) pose l'attribut, mais un modèle sérialisé avant cette version ne l'a pas.
  Les deux causes réellement posées par `fit` (`errp_decoder.py:231` et `:239`) sont des phrases
  complètes, donc l'interpolation `({cause})` reste lisible. La correction du coordinateur
  (`0dd318a`) est juste.
- **`n_epoques_`** — `_open` (`:288-296`) **ne** l'utilise **pas**, et le commentaire dit
  pourquoi : `n_calib=len(self.model.oof_y_)`. C'est le bon choix, et le commentaire est exact —
  `fit` pose `n_epoques_ = int(len(y))` (`errp_decoder.py:200`) et `oof_y_ = y.copy()` (`:218`),
  donc les deux sont bien égaux aujourd'hui et répondent bien à deux questions différentes.
- **Le moteur** — `server.py:849` lit `rt.params.get("stream_in", MARKER_STREAM_DEFAULT)` pour
  tout mode actif dont `marker_epoch_s > 0`. `errp.SPEC` déclare `marker_epoch_s = 0,9` (`:691`)
  ET `stream_in` (`:663`) : les deux sont enfin d'accord, et le commentaire de
  `_nom_flux_marqueurs` (« un mode qui ne le déclare pas — aucun aujourd'hui ») redevient vrai.
- **La console** — `live_views.py:435-440` lit déjà `taux_rejet`/`epoques_vues`/`artefacts` et les
  affiche « époques **de ce repos** » : la nouvelle sémantique par-repos de l'IMPORTANT 7 est
  cohérente avec le seul client qui les lit. Aucun client ne lit
  `epoques_vues_session`/`artefacts_session` pour l'instant — ils ne mentent pas pour autant.
- **Frontière et contraintes** — aucun import de `research`/`console`/pygame/Qt (`:114-127`,
  `:713-719`, `:1315`) ; français partout ; `tempfile.mkdtemp` + `shutil.rmtree` dans le `finally`
  (`:771`, `:1474-1476`) et les deux monkeypatchs restaurés (`:1475`, `:896`) — rien n'écrit dans
  le vrai `data/` ; `_sys.exit(0 if _selftest() else 1)` (`:1484`) ; `ERRP_REFRACTORY_S` n'est ni
  importé ni référencé ailleurs que dans trois commentaires (`:29`, `:150`, `:1142`) ; `error = -1`
  reste « pas de verdict » sur les deux chemins, modèle non consulté (`:1111`, `:1129`).

---

# Défauts NOUVEAUX

Trois, tous introduits ou aggravés par cette vague, tous des **affirmations de commentaire qui
disent autre chose que le code**. Aucun défaut de comportement nouveau trouvé.

## N1 — Le module annonce « Cinq pannes bruyantes » et en liste SIX

**Fichier:ligne** — `src/core/modes/errp.py:42` (l'en-tête) contre `:70-72` (la panne n°9 ajoutée
par le correctif du MINOR 10).

La vague a ajouté l'entrée « 9. une voie à σ NUL au repos » à la liste numérotée du module sans
toucher la phrase qui l'introduit. Vérifié contre `b05292a` : à ce moment-là la liste comptait
bien cinq entrées (4 à 8) et « Cinq » était juste ; elle en compte six (4 à 9) et « Cinq » ne
l'est plus.

**Le scénario concret.** Le fichier s'ouvre sur « lire `p300.py` avant celui-ci » et son en-tête de
liste est *le* résumé que lit un étudiant qui arrive : il compte les pannes que ce mode sait dire à
voix haute. Entrées : il lit « Cinq pannes bruyantes propres à ce mode » et six items numérotés
4-9. Comportement faux : soit il conclut qu'une entrée est en trop et cherche laquelle a été
dépubliée (aucune), soit — le cas coûteux — il conclut que la numérotation 4-9 est décalée d'un et
que la panne n°9 n'est pas vraiment câblée, alors que c'est justement le refus de conclure le
repos, celui qui immobilise le mode en phase « rest ». C'est exactement le genre d'écart que ce
fichier passe 100 lignes à dénoncer ailleurs.

*Correctif :* « Six pannes bruyantes » en `:42`.

## N2 — Le `Param(stream_in)` ne débloque PAS le scénario que son commentaire lui attribue

**Fichier:ligne** — `src/core/modes/errp.py:653-662` (le commentaire) et `:663-664` (le `Param`),
contre `src/core/modes/contract.py:249-259` (`_coerce`, `kind == "choice"`). Même affirmation
recopiée dans l'autotest, `:809-812`.

Le commentaire écrit, pour justifier l'ajout :

> « Sans ce réglage, `contract.validate` REFUSE la clé (« réglage inconnu pour « ErrP » ») et le
> flux entrant **reste gelé sur `MARKER_STREAM_DEFAULT`** — deux binômes dans la même salle ne
> peuvent plus se séparer, et le moteur du binôme B épocherait l'EEG de B autour des feedbacks
> affichés chez A… »

La conséquence annoncée (« reste gelé sur `MARKER_STREAM_DEFAULT` ») est **inchangée par le
correctif**. Le `Param` est déclaré `kind="choice"` avec `choices=(MARKER_STREAM_DEFAULT,)`, et
`contract._coerce` refuse toute valeur absente de `choices` :
`return None, "« Flux de marqueurs » : 'X' n'est pas un choix valide (EEG_API_Unicorn_stim)"`.
Côté console, `params_form.py:89-91` rend un `kind="choice"` en liste déroulante remplie depuis
`param["choices"]` — donc **une** entrée, non éditable. Côté ligne de commande, `server.py:3229-3259`
n'expose aucun `--stream-in`. Il n'existe aujourd'hui aucun chemin, dans tout le produit, pour
poser une autre valeur.

**Le scénario concret.** Deux binômes dans la même salle — le cas exact pour lequel `stream_in`
existe. Entrées : le binôme B renomme son `errp_stimulus.py` en `EEG_API_Unicorn_stim_B`, ouvre la
console, va sur la page ErrP, et cherche « Flux de marqueurs ». Comportement faux : la liste
déroulante ne propose que `EEG_API_Unicorn_stim`, il ne peut rien y taper ; s'il force la commande
`set_params` à la main, `validate` refuse « n'est pas un choix valide ». Le moteur de B résout donc
`EEG_API_Unicorn_stim`, trouve **le flux du binôme A**, et épocher l'EEG de B autour des feedbacks
affichés chez A — la panne décrite mot pour mot par le commentaire, **avec** le correctif appliqué.

Ce que l'ajout apporte réellement, et qui n'est pas rien : la clé cesse d'être refusée comme
inconnue, `server._nom_flux_marqueurs` a enfin quelque chose à lire sur ce mode, et le commentaire
de `server.py` (« un mode marqueur qui ne déclare pas `stream_in` — aucun aujourd'hui ») redevient
vrai. C'est ce que la constatation IMPORTANT 6 demandait littéralement, et c'est pourquoi son
verdict reste ADDRESSED. Mais le commentaire promet la suite du chemin, qui n'existe pas.

L'implémenteur le sait : il l'écrit dans la section « dépendances » de `fix-A-report.md`. Le
problème est que cette réserve est **dans le rapport et pas dans le code** — et c'est le code que
lira l'étudiant. Le `Param` du P300 a la même limite, donc le correctif de fond
(`kind="text"`, ou un `choices_fn` qui liste les flux `Markers` visibles) touche `contract.py` et
`p300.py` autant qu'`errp.py` ; il n'est pas de la tranche A.

*Correctif minimal, dans ce fichier :* couper la promesse en deux — dire que sans ce réglage le
moteur n'a rien à lire, et ajouter que la liste de choix n'a **qu'une valeur aujourd'hui**, donc
que deux binômes doivent encore se séparer par le `--id` du moteur ou par des salles distinctes.
L'aide publique (`:666-674`) doit le dire aussi : telle qu'elle est écrite (« Le nom du flux LSL
sur lequel ton application publie… »), elle se lit comme un champ libre.

## N3 — Le commentaire du plancher de `_rest_step` se lit comme l'inverse du code

**Fichier:ligne** — `src/core/modes/errp.py:402-404` contre `:416`.

> « Le plancher est `n_epoque` lui-même, **plus** `engine.acq.margin_n` : ce dernier était
> emprunté "comme ordre de grandeur commode"… »

Le code teste `if bloc is None or len(bloc) < n_epoque:` — `margin_n` n'intervient plus du tout.
La phrase veut dire « et non plus `margin_n` » (ellipse du `ne`), mais au premier degré elle
annonce un plancher de `n_epoque + margin_n`, soit 225 + `margin_n` échantillons.

**Le scénario concret.** Un étudiant instrumente le démarrage du repos parce que sa première
fenêtre lui semble arriver trop tôt. Entrées : il lit ce commentaire, en déduit que le repos
n'accepte sa première fenêtre qu'à partir de `225 + margin_n` échantillons dans le tampon, et
calcule son budget de chauffe là-dessus. Comportement faux : le repos commence à mesurer dès 225
échantillons, ses premières fenêtres tombent plus tôt qu'annoncé, et le diagnostic qu'il en tire
(« le tampon met plus longtemps que prévu à se remplir ») vise la mauvaise couche. C'est le défaut
le plus léger des trois — la seconde moitié de la phrase corrige la lecture — mais la phrase
d'ouverture d'un commentaire est ce qu'on lit en diagonale.

*Correctif :* « Le plancher est `n_epoque` lui-même, et **non plus** `engine.acq.margin_n` ».

*Au passage, dans la même famille et encore plus léger* (pas compté comme un quatrième défaut) :
`state()` affirme en `:342-344` que « `artefacts / epoques_vues` vaut **TOUJOURS** `taux_rejet` »,
alors que `:348` rend `round(..., 3)` — l'égalité est vraie à 10⁻³ près, pas exactement. Et
`epoques_perdues` (`:340`), lui, reste un compteur de SÉANCE dans le même dictionnaire que trois
compteurs devenus par-repos, sans que rien ne le dise à cet endroit.

---

## Ce que j'ai regardé et qui ne donne rien

Pour que ce rapport se lise comme une couverture et pas comme une liste de reproches.

- **Un test ajouté qui ne peut pas rougir** : cherché sur les 20 assertions neuves. Chacune a une
  mutation d'une ligne de production qui la fait échouer, et je les ai identifiées une par une
  (détaillées dans les deux sections prioritaires pour C1/C2 ; pour I3 c'est
  `if self.phase == "warmup":`, pour I4a le déplacement de `_epoques_vues += 1`, pour I4b le
  retrait de `self._verifie_taux_rejet()`, pour I7 le retour de `_reset_rest` sans ses trois
  remises à zéro, pour M8 `feedbacks = len(jetes)`, pour M9 l'ancien libellé, pour M10
  `mortes = []`, pour M11 `self._traiter_feedback(engine, lsl_ts)`).
  Deux assertions sont **redondantes** sans être tautologiques : `:816` (`marker_epoch_s > 0`,
  déjà impliqué par `:826`) et `:931` (`rt.params.get("stream_in")`, conséquence stricte de `:813`
  puisque `ModeRuntime.__init__` fait `self.params = dict(params)`). Elles ne coûtent rien et leur
  message documente le câblage ; je ne les compte pas comme un défaut, mais `:931` ne prouve pas
  ce que son message annonce — le vrai câblage vit dans `server.py:849` et n'est pas testé ici.
- **Une correction qui en casse une autre** : `Param(stream_in)` traverse `registry.check()`
  (`registry.py:206-212` exige un `kind` connu, des `choices` non vides pour un « choice », et un
  `help` non vide — les trois sont satisfaits) et `validate(spec, {})` (défaut présent dans
  `choices`). Le smoke de la console (`console/app.py:584-660`) construit son état ErrP **à la
  main**, sans passer par `SPEC.params` : il ne peut pas être cassé par cet ajout.
- **Le déroulé du nouveau test de `tick`** rejoué à la main pas par pas (`:971` à `:1034`) : les
  deux premiers `tick` ont bien la phase « warmup » à l'entrée (la bascule a lieu **dans**
  `super().tick`, après la garde — `runtime.py:94-98`), le troisième a bien « rest », et
  `_rest_step` n'appelle jamais `markers_murs` — c'est ce qui rend le compteur `appels_murs`
  discriminant.
- **Les comptes annoncés dans les messages** recomptés : `7` publications (`:1163`), `6/1/1`
  compteurs (`:1174`), `11/16` après les 10 saturés (`:1195`), `5/10` au premier franchissement
  (`:1201`, atteint au 4ᵉ des 10 feedbacks), `5` marqueurs de chauffe (`:1239`), `16`/`11` en
  cumuls de séance (`:1235`). Tous exacts.
- **La fixture d'artefact et la fixture d'alignement ne se marchent pas dessus** : après le
  « Refaire le repos » de `:1227`, le nouveau σ est mesuré sur la plage saturée (σ ≈ 200), donc le
  seuil vaut ~800 et le pic à 10-80 µV de la fixture d'alignement n'est pas pris pour un artefact.
  L'assertion `:1287` reste donc atteignable.
- **`_publish` / `output()`** : la clé anglaise `"artifact"` (`:610`) est bien celle que
  `live_views` et les modes voisins lisent, et `threshold` est bien publié à chaque échantillon
  (`:601`, `lsl_io.py:492`).
