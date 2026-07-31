# Vague de correction — revue de branche du chantier 3 moitié B

Huit relecteurs ont couvert la branche par sous-système. **0 critique, 19 importants.** Ce
document est la liste ARBITRÉE : ce qui se corrige, ce qui reste parké, et pourquoi.

Deux lots qui ne partagent AUCUN fichier. Chacun est confié à un correcteur distinct, **jamais en
parallèle** — les deux lancent des tests, et ce projet interdit deux programmes à la fois.

---

## LOT A — `src/core/` (le moteur, le contrat, la calibration, le décodeur)

### A1. La CV honnête absente devient « 0 % — FAIBLE » ⭐ *converge depuis 3 relecteurs*

`src/core/modes/mi_calib.py` — `cv = modele.cv_groupee_ if ... is not None else 0.0`, puis
`verdict(cv)` rend « FAIBLE — ré-essaie : contact des électrodes, immobilité, imagerie
kinesthésique ». Un diagnostic précis, actionnable, et **sans aucun rapport avec la vraie cause** :
il n'y avait pas assez d'essais distincts d'une classe pour former deux plis.

C'est l'inverse exact de ce que le même chantier enseigne ailleurs : `mi_models.decrire()` préserve
`None` avec un commentaire explicite ET un test dédié, et `mi_decoder._test_cv_honnete` vérifie le
même invariant. **La discipline est prouvée à deux endroits, puis jetée là où elle atteindrait un
étudiant.**

Correctif : propager `None` jusqu'au résultat (`cv_groupee: None`), et n'appeler `verdict()` que
s'il y a un chiffre. Quand il n'y en a pas, le résultat doit porter une raison en clair — « justesse
non mesurable : pas assez d'essais distincts par classe pour une validation croisée ». Ajoute un
test qui l'épingle.

⚠️ Ce chemin est aujourd'hui bloqué par une **coïncidence arithmétique non documentée** entre deux
fichiers : le seuil « 5 fenêtres par classe » de `_entrainer` et le seuil `n_splits >= 2` de `fit`.
Il se rouvre si l'un des deux bouge, ou si des essais sont ignorés en cours de séance (ce que le
message « essai IGNORÉ » prévoit pour de vraies coupures Bluetooth). **Écris la dépendance en
commentaire** aux deux endroits — c'est elle qui tient l'invariant, pas un test.

### A2. Le verdict n'est jamais recoupé avec la CV honnête — *mutant confirmé survivant*

Une implémentation qui calcule `verdict(cv_naive)` tout en gardant `cv_groupee` honnête **passe les
19 assertions**. Or le verdict est la phrase que l'étudiant lit en tête de son résultat.
Correctif : `chk(res["verdict"] == verdict(res["cv_groupee"]), ...)`.

### A3. L'invariant « époques BRUTES » n'est gardé sur aucun des deux chemins

La garde du projet (`acquisition.py --synthetic`) protège `motor_window`, que la calibration
**n'appelle jamais**. Le chantier a ouvert une SECONDE porte vers `MIModel.fit` sans y remettre la
serrure. Mutant confirmé : insérer `bandpass(reref(...))` avant le découpage passe les 35
assertions des deux autotests ET le smoke. Le `.npz` n'est d'ailleurs relu par aucun test.

Correctif (une assertion qui pinne d'un coup le non-filtrage ET l'orientation) : faire mémoriser au
faux moteur de `mi_calib._selftest` ce qu'il rend, puis après la séance comparer les époques
enregistrées au signal rendu, octet pour octet. `rendus` ne contient que les essais enregistrés
(l'échauffement ne prélève rien), donc la comparaison est exacte.

### A4. `recent_window` ne porte pas l'avertissement sur le double filtrage

`src/core/server.py` — sa docstring dit « accesseur PUBLIC pour un afficheur ». Elle est désormais
À LA FOIS la source des époques d'entraînement ET celle des tracés live de la console. Le grand
avertissement vit sur `motor_window`, que la calibration n'utilise pas. Quelqu'un qui trouve les
tracés bruyants et filtre ici entraînerait le MI sur du signal doublement filtré, sans erreur, avec
des probabilités plausibles. Correctif : recopier l'avertissement dans sa docstring.

### A5. Le tampon agrandi a changé la fenêtre de mesure de la QUALITÉ — un flux PUBLIC

`src/core/server.py` — `_publish_quality` passe `self.recent` **en entier** à `sigma_from_block` /
`common_mode`, qui rendent tout le tampon moins la marge. Le σ était mesuré sur 500 échantillons
(= `QUALITY_WINDOW_S` = 2 s), il l'est maintenant sur 1000 (= 4 s), parce qu'on a agrandi `keep`
pour la calibration. La constante est devenue fausse, son commentaire aussi, et **le couplage n'est
pas borné** : une calibration future à `epoch_s = 10` mesurerait la qualité sur 10 s sans que rien
ne le dise. Aucun des 14 tests ne le verrait — le smoke compte les lignes de qualité, jamais leurs
valeurs.

Ampleur réelle aujourd'hui : la bande 5-40 Hz retire la rampe DC, donc les verdicts ne basculeront
pas. Ce qui est cassé n'est pas la mesure, c'est **qu'un consommateur non concerné change quand on
dimensionne pour un autre**.

Correctif : borner explicitement le bloc passé à `QUALITY_WINDOW_S + la marge`. Tous les autres
lecteurs prennent déjà une queue bornée — `_publish_quality` était le seul à consommer le tampon
entier.

### A6. `submit` et `snapshot` peuvent LEVER depuis le fil de l'interface

Quatre endroits de `server.py` lisent `self.calibration` deux ou trois fois au lieu d'en prendre une
copie locale, alors que la boucle peut le mettre à `None` entre deux lectures : la branche
`cancel_calibration` de `submit`, la branche `start_calibration`, `_phase_of`, et `snapshot`.

`submit` promet **en toutes lettres** de ne jamais lever — et le fichier documente ce piège exact
25 lignes plus bas, pour `set_params`. Conséquence composée, et c'est celle qui fait mal : un même
`snapshot()` peut rendre `phase: "calibrating"` **et** `calibration: null`, deux valeurs
contradictoires dans un seul état publié, ce que sa propre docstring interdit. Déclencheur
réaliste : fermer la console pendant une calibration.

Correctif : une copie locale en tête de chacune des quatre, puis n'utiliser que la locale — c'est
déjà ce que fait `_status_key`. Passer aussi la copie à `_phase_of` pour rétablir l'invariant du
fichier. **Corollaire dans `calibration.py`** : `restant_s` lit `self._echeance` deux fois, et la
boucle le met à `None` dans `cancel()` et `_terminer()` → `TypeError` chez l'appelant.

### A7. Le garde « une seule calibration » n'existe que côté `submit`, jamais côté boucle

`_start_calibration` écrase `self.calibration` **inconditionnellement**. C'est la seule des trois
nouvelles opérations à ne pas re-vérifier côté boucle : `_set_params`, `_set_published` et
`_recalibrate` le font toutes les trois, avec le commentaire qui explique pourquoi. Deux
`start_calibration` soumis dans la même fenêtre de sondage sont tous deux acceptés et la boucle les
applique tous deux. Un double-clic sur « Commencer » suffit.

⚠️ **L'assertion du smoke contourne exactement la fenêtre de course** : elle attend
`server.calibration is not None` avant de soumettre la seconde. Correctif : reprendre le motif des
trois voisines, ET corriger le test pour qu'il n'attende plus.

### A8. Le modèle est écrit AVANT l'enregistrement

`src/core/modes/mi_calib.py` — si `np.savez` échoue (disque plein, verrou antivirus), l'exception
est attrapée, la séance passe « annulée » et `resultat` vaut `None` — mais le `.joblib` **reste sur
disque et apparaît dans la liste de la console**, sans `.npz`, sans provenance. Ça viole « l'échec
ne produit AUCUN fichier ». Correctif : écrire le `.npz` d'abord — un `.npz` orphelin est
inoffensif, un modèle orphelin non.

### A9. `registry.check()` ne valide rien sur les calibrations

`check()` est appelée EN PREMIER par le smoke, explicitement parce qu'« un défaut là-dedans explique
tous les suivants ». Elle vérifie exhaustivement les défauts de `spec.params` mais ignore
`spec.calibration`. Un défaut invalide dans un `Calib.params` traverserait les quatre tests verts et
ne serait découvert qu'au clic « Calibrer ».

Ajoute-lui, pour chaque mode dont la calibration a un `runtime_cls` :
- la validation des défauts, comme pour les params de mode ;
- **le contrôle qui empêche le défaut de revenir** : `epoch_s >= runtime_cls.imagery_s`, sinon les
  époques seraient tronquées EN SILENCE. Il y a aujourd'hui deux sources de vérité pour le même
  nombre (`Calib.epoch_s` qui dimensionne le tampon, `imagery_s` qui prélève) et rien ne les lie ;
- le fait que `epoch_s > 0` quand `runtime_cls` existe.

Et corrige le calcul de `keep` pour ne retenir que les calibrations **que le moteur sait jouer**
(`runtime_cls is not None`) : sinon un `epoch_s` documentaire sur une calibration « native »
gonflerait le tampon — et, via A5, la fenêtre de qualité.

### A10. Trois trous de couverture, tous confirmés par mutation

- **La branche « tampon pas rempli »** (`calibration.py`) n'est exercée par aucun test, alors que
  c'est elle qui décide ce qui entre dans le jeu d'entraînement. Un faux moteur qui rend une fenêtre
  courte au premier essai, puis vérifier `essai == total - 1` : ~6 lignes.
- **La garde `n_splits < 2`** (`mi_decoder.py`) n'est exercée nulle part. Sa sûreté tient à la même
  coïncidence non documentée qu'en A1.
- **Le test de l'invariant de CV honnête ne protège pas contre une décote arbitraire** :
  `cv_groupee_ = 0.85 * cv_`, sans regarder `groups` du tout, satisfait `cv_groupee_ < cv_` sur
  n'importe quel jeu de données. Correctif proposé par le relecteur, et il est bon : **tester le
  MÉCANISME plutôt que d'inférer depuis un agrégat** — énumérer `cv.split(...)` et vérifier que les
  groupes d'apprentissage et de test sont disjoints à chaque pli.

### A11. Le chemin d'annulation et les quatre refus ne sont pas testés

Rien n'exerce : la commande `cancel_calibration` de bout en bout, le retour de `calibrating` à
`streaming`, le `finally` de la boucle, et **les quatre branches de refus de `submit`** — mode
inconnu, mode sans calibration, calibration « native » (le seul endroit qui dit « passe par
`python src/research/app.py` »), et « aucune calibration en cours ». Ce sont les quatre premiers
messages qu'un étudiant verra. Coût du comblement : très bas, `submit` ne dépend pas de la boucle et
se teste sur un moteur NON démarré.

### A12. Le piège de l'horloge zéro, reposé

`src/core/modes/mi_calib.py` — `horodatage(maintenant or _time.time())` reproduit **exactement** le
bug que le commit frère du même jour dit avoir fermé (`0.0` est falsy), et dont la leçon est écrite
dans le fichier d'à côté. Inatteignable aujourd'hui, mais la docstring promet « le paramètre existe
pour que le test soit reproductible » : c'est un piège posé pour le suivant.
Correctif : `_time.time() if maintenant is None else maintenant`.

### A13. Le vocabulaire des phases est déclaré puis recopié

`calibration.py` déclare `PHASES` et `ETAPES` et affirme en docstring que « la console les traduit,
elle n'en invente aucune ». Or elles ne sont **importées nulle part**, et la console redéclare les
siennes. C'est le « catalogue recopié » que CLAUDE.md interdit : renommer une phase côté moteur
laisserait la console sans écran de résultat. Correctif : que la console importe la constante.

### A14. Les petits, groupés

- `int()` contre `int(round())` entre `recent_window` et la garde de longueur : divergent dès
  qu'une durée a une partie fractionnaire ≥ 0,5, et **tous** les essais seraient alors écartés.
  Inatteignable à 4,0 × 250, mais `imagery_s` est explicitement conçue pour être raccourcie.
- `produits[0]` sans garde dans le smoke — cinq caractères. Pas pour éviter un faux vert (un build
  cassé échoue de toute façon) mais pour la règle que le fichier s'est donnée 60 lignes plus haut :
  rendre le diagnostic ligne à ligne jusqu'au bout.
- Le `tick` de la calibration n'est pas protégé : une exception tue le moteur ET perd les époques
  d'une séance de sept minutes. Marquer la calibration « annulée » avec sa raison et laisser le
  moteur vivre.
- `chk(True, "l'état est sérialisable en JSON")` ne prouve rien par elle-même.
- Le commentaire du `finally` de `run()` promet plus que le code : c'est `= None` qui casse le
  cycle, pas `cancel()`, qui ne libère ni `engine` ni les époques. Libère-les dans `cancel()`.
- `duration_s=60` dans le smoke est juste : la séance mesure ~27 s mais le pas de boucle ajoute
  ~8,5 s, et un dépassement tue le moteur en pleine séance. Passer à 120.
- Le `# noqa: E402` superflu sur l'import sklearn.
- La double numérotation « 9. » dans le selftest de `mi.py`, et la branche `hasattr` morte.
- Factoriser `Calib.defaults()` et `ModeSpec.defaults()` en une fonction commune : coût nul, et ça
  transforme en garantie STRUCTURELLE ce qui n'est aujourd'hui qu'une convention en commentaire.

---

## LOT B — `src/console/`, `src/research/`, `archive/`, la documentation

### B1. Le premier top de la séance suivante est muet après un abandon

`src/console/calib_page.py` — `_etape_precedente` n'est jamais réinitialisé, et `_maybe_beep` n'est
appelée que si une séance est en cours. Le commentaire qui justifie l'absence de remise à zéro est
VRAI pour la fin normale (qui passe par une étape vide pendant la phase d'entraînement) mais **FAUX
pour l'abandon** : `cancel()` vide l'étape ET pose la phase terminale dans le MÊME appel, sans
jamais exposer d'état intermédiaire.

Scénario : on abandonne pendant la mise en route — le moment le plus probable pour s'apercevoir
qu'une électrode est mal placée. La page n'est jamais recréée, donc **le tout premier top de la
séance suivante ne sonne pas**, en silence. L'étudiant doit LIRE l'instruction du premier essai,
exactement la contamination du regard que les tops existent pour éviter, sur la séance qu'il vient
de relancer pour avoir de MEILLEURES données. Et ce n'est pas probabiliste : pour l'abandon, la
fenêtre non terminale n'existe jamais.

Correctif : remettre `_etape_precedente` à `None` quand aucune séance n'est en cours. Une ligne.
**Ajoute le test** : abandonner pendant la mise en route, relancer, vérifier que le premier top sonne.

### B2. `calib_page.py` effondre lui aussi la CV absente en `0.0`

`cv = float(resultat.get("cv_groupee") or 0.0)` — un second effondrement, **indépendant** de celui
du moteur : même une fois A1 corrigé, cette ligne re-transformerait `None` en `0.0`. Correctif :
distinguer les deux cas et afficher « justesse non mesurable » avec la raison, jamais « 0 % ».

### B3. `mi_compare.py` cible un fichier que la calibration n'écrit plus ⭐ *converge depuis 2 relecteurs*

`src/research/mi_compare.py` pointe par défaut sur `data/mi_calib_last.npz`, le nom FIXE que ce
chantier supprime — alors que `config.py` recommande cet outil « après chaque calibration ». Deux
issues : erreur propre sur un dépôt neuf, ou **silencieuse** sur ce poste-ci, où un ancien fichier
traîne — l'outil analyserait indéfiniment une séance périmée sans jamais le dire.

Correctif : par défaut, prendre le `mi_calib_*.npz` **le plus récent** du dossier de données, et
imprimer lequel a été retenu. S'il n'y en a aucun, le dire en clair.

### B4. Les quatre assertions faibles de la console

Toutes signalées « à corriger avant fusion » par le relecteur, 1 à 4 lignes chacune :
- le commentaire de quatre lignes absent au-dessus du bouton Démarrer — c'est le seul endroit de
  `grid.py` qui préviendrait un étudiant de ne pas y ajouter de validation locale ; le texte existe
  verbatim dans `task-5-brief.md` ;
- aucune assertion ne vérifie qu'un clic **ne mute pas** l'étiquette de sa tuile avant le prochain
  état reçu — c'est le test le plus directement lié à la règle centrale du sous-système ;
- le test du clic « Commencer » ne vérifie pas la VALEUR soumise (un formulaire qui enverrait 999 en
  dur passerait) ;
- la progression est testée par sous-chaîne : un mutant qui inverserait en « essai 42 sur 7 »
  contient toujours « 7 » et « 42 » et passe. Remplacer par une égalité.

### B5. La documentation

- **README, table « Layout » de `src/console/`** : `calib_page.py` (la fonctionnalité phare du
  chantier, décrite juste au-dessus) et `beeps.py` manquent, alors que la table itemise 6 des 8
  fichiers du dossier. Un étudiant cherchant où vit l'écran « Calibrer » ne le trouverait pas.
- **README, « All six share one acquisition session and one UI core »** : devenu approximatif — le
  MI tourne entièrement via la console PySide6, un socle distinct des cinq modes pygame.
- **`docs/recette.md`, test 2.6** : citer directement **« p = 0,082, non significatif »** plutôt que
  renvoyer au README. La recette se veut auto-suffisante, et c'est exactement la nuance que ce
  projet tient à ne jamais sous-entendre — un étudiant qui lit « 40 % » à côté de « hasard 33 % »
  conclut naturellement que c'est mieux que le hasard. Ça ne l'est pas, pas avec cette mesure.
- **`docs/recette.md`, test 1.13** : parle d'un « troisième terminal » en supposant qu'un deuxième
  est resté ouvert malgré une fermeture/réouverture de console entre deux lancements.
- **`src/research/app.py`** : le docstring de `mode_neuro` dit encore « Mode 5 » alors que son
  en-tête de section, 19 lignes plus haut, a été renuméroté « Mode 4 ». `mode_errp` a bien été
  traité, celui-ci a été oublié.
- **`archive/mi_pilot.py`** : le message d'absence de modèle dit encore « mi_calibrate.py » sans le
  préfixe `archive/`, alors que les cinq lignes d'usage du docstring l'ont toutes reçu. Un
  utilisateur qui suivrait ce message depuis la racine ne trouverait rien.
- **`mode_page.py`** : la docstring de `rafraichir_choix` annonce être appelée « au retour d'une
  calibration », ce qu'aucun code ne fait — le retour ramène à la grille.

---

## PARKÉ, avec la raison

- **L'époque PÉRIMÉE sur coupure Bluetooth.** `server.recent` ne rétrécit jamais, donc sur une
  coupure `recent_window` rend les mêmes secondes périmées, de longueur PLEINE. Tous les essais
  seraient acceptés, identiques, sous trois étiquettes. **Ruling : réel, mais l'échec est audible**
  — le CSP dégénère, donc le verdict dira « FAIBLE, contact des électrodes ». Ce n'est pas un modèle
  plausible et faux, c'est une séance perdue avec un diagnostic à côté. Le correctif (compteur de
  fraîcheur) mérite d'être conçu, pas bricolé en fin de chantier. → **porté à la recette matérielle**.
- **Un refus de commande n'a aucune trace dans l'interface.** Réel, et c'est le scénario le plus
  probable du parcours (« Démarrer » sur le MI avant toute calibration). **Ruling : parké** — le
  relecteur note que `_publier` a exactement le même comportement, préexistant, et que corriger
  proprement demande de décider OÙ vit un refus générique de commande. C'est un petit chantier
  d'interface à part entière, pas une ligne à glisser ici.
- **`MI_MODEL_PATH` et `MI_KEY_CHANNELS` « constantes mortes ».** **Ruling : NE PAS SUPPRIMER.** Le
  relecteur les dit « référencées seulement par `archive/` » — mais l'archive doit rester
  EXÉCUTABLE, c'est la condition qui lui donne son sens. Les retirer casserait les deux fichiers
  archivés et leurs smokes. Ajouter un commentaire disant qui les utilise.
- **`Beeps.disponible` figé à la construction** (cordon débranché en cours de séance) : improbable,
  et le cas visé par la conception — poste sans carte son — est couvert.
- **Les chiffres de la phrase d'honnêteté dupliqués** entre console et moteur : du texte informatif,
  pas une décision. À penser le jour où la séance de référence sera remesurée.
- **`self.engine` écrit et jamais lu en production** : cosmétique.
- **Le TOCTOU de `_chemins_libres`** : la règle « un seul programme à la fois » est une contrainte
  MATÉRIELLE du casque, et rien d'autre n'écrit ce motif.
- **La divergence catalogue / runtime pendant une calibration concurrente** : les deux répondent à
  des questions différentes, aucun ne ment. Nice-to-have.
- **Le double-clic non débouncé sur « Démarrer »** : à vérifier côté moteur un jour ; le refus est
  propre aujourd'hui.
