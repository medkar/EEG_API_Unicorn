# Task 10 — les retraits : le test de la tâche 1 passe au VERT

**Statut : complete.** Commits `1fd659d` → `ea25e62` (5), sur `main`, arbre propre.

## Le critère

```
[smoke-frontiere] 57 fichiers scannés, 0 violation(s) de frontière
[smoke-frontiere] VERDICT : OK
```

`python src/core/server.py --smoke` sort en 0, et **tous** ses blocs sont OK. Le test écrit à la
tâche 1, rouge sur six fichiers puis sur trois, est vert.

## L'ordre, tenu

Le piège annoncé était `ui.py`. Il a été traité **en premier et seul**, et les douze `--smoke` de
`archive/` étaient verts **avant** que quoi que ce soit d'autre ne bouge.

Une nuance de méthode, qui rend l'ordre plus sûr que prévu : les trois déménagements ont été faits
au `git mv`, pas en copier-puis-supprimer. **L'étape « suppressions en dernier » du plan n'a donc
pas d'objet** — il n'a jamais existé d'instant où l'original et la copie coexistaient et pouvaient
diverger. La contrainte que le plan protégeait (ne pas casser des fichiers que personne ne relance)
est tenue par la vérification, pas par l'ordre des suppressions : les smokes de l'archive sont
passés au vert dans le même commit que le déplacement.

| étape | fichier | geste | commit |
|---|---|---|---|
| 1 | `research/ui.py` → `archive/ui.py` | déménagé, 9 sites d'import corrigés dans 8 fichiers | `1fd659d` |
| 2 | `research/live_ssvep.py` → `archive/live_ssvep.py` | archivé, `--smoke` renforcé | `1a284c5` |
| 3 | `research/ssvep_analyze.py` | **reste au banc d'essai**, import retiré | `8f90e8d` |
| 4 | `archive/README.md` | 3 lignes + 2 faussetés antérieures corrigées | `5dcc6a9` |
| 5 | 7 fichiers de `src/` | 17 commentaires de provenance repointés | `ea25e62` |

## `ssvep_analyze.py` — la question à trancher : il RESTE

**Verdict : le fichier reste dans `research/`, l'import part.** C'est le cas « retirer l'import
suffit », pas le cas « écran de pilotage ».

**Pourquoi.** L'import ne sert aucun mode d'enregistrement live. La seule ligne qui s'en servait
était `flt = UnicornAcquisition(synthetic=True)`, et elle n'appelait qu'**une** méthode : `_filter`,
la chaîne detrend + passe-bande + notch. `start()` n'est jamais atteinte, donc
`board.prepare_session()` — qui est dans `start()`, pas dans `__init__` — n'est jamais appelée :
aucun casque, aucune session, pas même sur le board synthétique. Le commentaire d'origine
(« aucune session ouverte ») disait vrai. Le fichier ne fait que calculer sur des `.npz` déjà pris,
ce qui est exactement le métier du banc d'essai.

**Mais retirer l'import sans rien mettre à la place n'était pas une option.** Réécrire le filtrage
ici (scipy) aurait donné un **second** filtrage, accordé au premier le jour de son écriture puis
divergeant en silence — et cet outil existe pour *comparer des configurations*, donc ses chiffres
doivent rester comparables à ceux du moteur.

La solution était déjà écrite un fichier plus loin, par la T8/T9 :
`core/modes/ssvep_mesure.acquisition_de_reference()` rend une `UnicornAcquisition` jamais démarrée,
et sa docstring dit mot pour mot qu'elle existe « pour que le banc d'essai n'ait plus à connaître
l'acquisition ». Elle était privée ; elle est maintenant publique, pour la raison qui l'a fait
écrire, avec ses deux appelants internes mis à jour. C'est la même logique que `rejouer` et
`longueur_bloc_attendue`, publiques pour ce même banc d'essai.

**Vérifié sans rien croire sur parole** : sorties **octet pour octet identiques** entre l'ancienne
et la nouvelle version sur les **quatre** `data/ssvep_guided_*.npz` archivés. Aucun chiffre n'a
bougé.

## `live_ssvep.py` — septième écran de pilotage, archivé

Il ouvre le casque lui-même et affiche des flèches clignotantes avec le ρ en direct : même nature
que les six archivés le 2026-09-08, simplement oublié. Ses deux usages ont chacun un chemin dans
l'application (tracé ρ de la page SSVEP ; tuile « Taux d'émission SSVEP »). Gardé lançable, non
maintenu, comme référence de décodage LOCAL — et parce que son `--guided` est ce qui a écrit les
archives que `ssvep_analyze.py` sait lire.

### Le risque `data/`, traité là où il vit

C'est **le** fichier du lot qui écrit dans `data/` : `_save_raw` y dépose les fenêtres brutes d'un
run guidé. Sa garde était déjà correctement placée (retour anticipé **avant** le `np.savez`, pas
après — contrairement au bug du chantier précédent). Deux ajouts :

1. son `--smoke` joue désormais **les deux chemins**, `--guided` compris. Ne tester que le chemin
   non-écrivant aurait exercé la garde sur la branche qui ne l'appelle jamais, c'est-à-dire rien ;
2. il compare l'empreinte de `data/` avant/après et **échoue en nommant les fichiers ajoutés**.

**Preuve du rouge**, faite puis défaite : en neutralisant le retour anticipé de `_save_raw`, le
smoke rougit et nomme sa propre trace —
`ÉCHEC : l'autotest a TOUCHÉ au vrai data/ — ajouts ['ssvep_guided_20260909-144750.npz']`, exit 1.
Source restaurée, fichier supprimé, empreinte revenue à la baseline (contrôlé, 0 résidu).

## `ui.py` — la machinerie, pas un écran

Huit fichiers de `archive/` l'importent (mesuré : `cvep_calibrate` ×2, `cvep_pilot`,
`cvep_rcca_pilot`, `errp_calibrate`, `errp_demo`, `p300_pilot`, `p300_calibrate`, `ssvep_pilot`).
Import en **nom de module nu** (`from ui import …`), Python plaçant le dossier du script en tête de
`sys.path` ; le `sys.path.insert` interne du fichier a été recalé sur `../src`.

**Preuve que le vert est réel** : `archive/ui.py` caché, trois smokes testés s'arrêtent sur
`ModuleNotFoundError: No module named 'ui'`. Le vert n'est donc pas une résolution ailleurs.

Il n'a **pas** de `--smoke` à lui — il n'a rien à lancer ; il est couvert par les huit qui
l'importent. C'est dit dans le README, parce que « douze commandes pour treize fichiers » est le
genre d'écart qu'un nouvel arrivant lit comme un oubli.

## Tests

Empreinte `data/` **identique** avant/après, prise avec `core.config.empreinte_dossier` :

```
AVANT : 43 fichiers, sha1 5b6bf6c3caae7a85aefede536e523c14774c785a
APRÈS : 43 fichiers, sha1 5b6bf6c3caae7a85aefede536e523c14774c785a
ajouts : aucun · disparus : aucun · modifiés : aucun
```

`seances/` réel : 0 fichier. Arbre git propre.

Tout vert (exit 0) : `server.py --smoke`, `console/app.py --smoke`, les **12** smokes de `archive/`,
les 4 fenêtres de `stimulus/` + `registry.py`, `modes/{mesure,alpha,ssvep_mesure,calibration,
mi_calib,mi,cvep,p300,errp}.py`, `core/markers.py`, `acquisition.py --synthetic`,
`research/ssvep_guided.py --smoke`, `research/ssvep_analyze.py`.

## Réserves

- 🟡 **Trois faussetés de doc restent, pour la T11**, toutes créées ou révélées par ce chantier :
  `README.md:445` range encore `live_ssvep.py` (et `controller.py`) dans `research/` ;
  `CLAUDE.md:318` et `docs/SPEC.md:706` citent `research/ui.py:signal_check`. Les 17 références
  équivalentes **dans le code** ont été repointées (`ea25e62`) ; ces trois-là sont dans des fichiers
  que la T11 réécrit, d'où le renvoi plutôt qu'un conflit.
- 🟡 **`archive/README.md` portait deux faussetés antérieures**, corrigées et vérifiées contre la
  source : `--model` est sur **sept** fichiers et non cinq, et « neither ever defaults to a fixed
  path » était faux pour `cvep_pilot.py`, dont le défaut est `CVEP_MODEL_PATH`
  (`data/cvep_model.npz`). C'est celui qui mord en séance — c'est la référence locale à laquelle on
  compare le réseau — et `CLAUDE.md` portait déjà l'avertissement de son côté.
- 🟡 **`ssvep_analyze.py` filtre à `fs=250` quel que soit le `fs` du fichier lu.** Antérieur, et
  sans effet aujourd'hui : board synthétique et Unicorn sont tous deux à 250 Hz, ce qui est
  pourquoi la sortie est restée identique. Un enregistrement pris à un autre `fs` serait filtré de
  travers, en silence. `ssvep_mesure` a `longueur_bloc_attendue` pour refuser ce cas ; cet outil-ci
  n'a pas d'équivalent. Hors périmètre, non corrigé.
- 🟢 **Rien de ce chantier n'a vu un cerveau.** Aucune mesure, aucun chiffre de décodage n'a été
  produit ni modifié ici : uniquement des déplacements de fichiers, un import et des commentaires.
</content>
