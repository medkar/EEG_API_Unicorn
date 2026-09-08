"""`research` — tout ce qui n'est pas (encore) dans le moteur : explorer les limites du casque.

Le nom ne dit pas « brouillon » : plusieurs de ces modes sont validés sur casque. Il dit que le
moteur ne les publie pas encore sur le réseau, donc qu'ils ne font pas partie du contrat rendu
aux étudiants et peuvent changer de forme. Un module d'ici a le droit d'importer `core` ;
l'inverse est interdit (voir `core/__init__.py`).

Quatre familles, à ne pas confondre en parcourant le dossier :

1. **Le socle pygame** — `ui.py` (la fenêtre, la session casque, l'écran de contrôle de liaison,
   et la machinerie des modes en direct : `Live`, le fil de décodage, le vote, la boucle de
   rendu), `ssvep_stimulus.py`, `viewing.py`.
   ⚠️ **Il n'y a plus d'application pygame ici.** `app.py` — le menu et ses cinq modes — a été
   supprimé le 2026-09-08 (chantier « la console, seul point d'entrée ») : le moteur publie les
   six modes, la console les pilote, et les écrans pygame qui faisaient doublon sont archivés,
   encore exécutables, dans `archive/` (voir `archive/README.md`). Ce socle-ci reste parce que
   ce sont EUX qui l'importent — plus `ssvep_guided.py` et `alpha_check.py`, deux protocoles
   chiffrés qui n'ont jamais eu de doublon.
   ⚠️ Les fenêtres de STIMULUS, elles, ont leur propre paquet : `src/stimulus/` (`p300.py`,
   `errp.py`, `cvep.py`). Elles n'ouvrent PAS le casque, elles AFFICHENT et publient des
   marqueurs — c'est ce qui permet de les lancer en même temps que le moteur, dans deux
   terminaux. `ssvep_stimulus.py` est resté ici : il ne publie aucun marqueur, il ne fournit que
   la géométrie des flèches et la mesure du rafraîchissement.
2. **Les décodeurs des modes** — **plus aucun, désormais.** `cvep_code`, `cvep_decoder` ET
   `cvep_rcca` ont fait le trajet vers `core` le 2026-08-20, comme `neuro_monitor` le
   2026-07-27, `mi_decoder` (avec `mi_models`) le 2026-07-29, `p300_decoder` (avec
   `p300_models`) le 2026-08-17, `errp_decoder` (avec `errp_models`) le 2026-08-18 : les **six**
   décodeurs du produit vivent maintenant dans `core`, et cette famille-ci est VIDE.
   ⚠️ **Le fichier `cvep_rcca.py` qui subsiste ICI n'est pas un décodeur** — c'est la fabrique de
   codes GOLD, la moitié RÉFUTÉE de l'hypothèse rCCA (voir sa docstring), donc de la famille 4.
   Le décodeur rCCA, lui, EST publié : `core/modes/cvep.py` instancie `RCCADecoder` quand le
   fichier de modèle déclare ce décodeur, et la calibration en écrit un à chaque séance.
3. **Les calibrations** — **plus aucune ici non plus.** `cvep_calibrate.py`, `p300_calibrate.py`
   et `errp_calibrate.py` sont partis dans `archive/` le 2026-09-08, avec l'appli qui les
   appelait. Ce n'était pas qu'un doublon : elles écrivaient un modèle DIRECTEMENT dans `data/`,
   sans passer par le « Refaire / Enregistrer » que la console impose depuis ce chantier — un
   modèle raté pouvait donc devenir le défaut proposé sans que personne ne le voie. Le moteur
   calibre les quatre modes à modèle (`core/modes/*_calib.py`), la console les lance et les juge.
4. **Les analyses hors ligne et les hypothèses RÉFUTÉES gardées lisibles** — `*_analyze.py`,
   `ssvep_guided.py`, `mi_compare.py`, `itr.py`, et `cvep_rcca.py` (la fabrique de codes Gold,
   seule appelée par `archive/cvep_rcca_pilot.py`) : rejouer un enregistrement, comparer,
   mesurer. C'est ici qu'on décide si une hypothèse tient, et il n'y a rien de honteux à ce
   qu'une analyse conclue « bruit ».

Reste `controller.py` et `live_ssvep.py`, hérités du banc d'essai robot : ils décodent et
envoient un `{jx,jy}` en UDP. Le produit ne fonctionne plus ainsi (l'API publie une intention
neutre sur LSL, cf. `docs/robot_testbed.md`), ils survivent comme référence de comparaison.

`mi_calibrate.py` et `mi_pilot.py` ont quitté ce dossier le jour où le moteur a appris à
calibrer et décoder le Motor Imagery lui-même (`core/modes/mi_calib.py`, `core/modes/mi.py`).
Les huit autres écrans pygame les ont suivis, mode par mode, jusqu'au 2026-09-08 : ils vivent
tous dans `archive/`, encore exécutables (`--smoke`), gardés comme la référence LOCALE contre
laquelle une séance casque compare le décodage réseau — voir `archive/README.md`.
"""
