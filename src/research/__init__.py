"""`research` — tout ce qui n'est pas (encore) dans le moteur : explorer les limites du casque.

Le nom ne dit pas « brouillon » : plusieurs de ces modes sont validés sur casque. Il dit que le
moteur ne les publie pas encore sur le réseau, donc qu'ils ne font pas partie du contrat rendu
aux étudiants et peuvent changer de forme. Un module d'ici a le droit d'importer `core` ;
l'inverse est interdit (voir `core/__init__.py`).

Quatre familles, à ne pas confondre en parcourant le dossier :

1. **L'application pygame** — `app.py` (menu, 6 modes), `ui.py`, `ssvep_stimulus.py`,
   `viewing.py`. Elle ouvre le casque ELLE-MÊME : ne jamais la lancer en même temps que le
   moteur, le casque n'accepte qu'une connexion.
2. **Les décodeurs des modes** — `cvep_*`, `p300_decoder`, `errp_decoder`. Ce sont eux qui
   migreront vers `core` quand leur mode sera publié — `neuro_monitor` a fait le trajet le
   2026-07-27, `mi_decoder` (avec `mi_models`) le 2026-07-29 : tous deux vivent maintenant
   dans `core`.
3. **Les calibrations** — `*_calibrate.py` : protocoles longs qui entraînent un modèle dans
   `data/`. Coûteuses en fatigue, à lancer sur un sujet frais.
4. **Les analyses hors ligne** — `*_analyze.py`, `ssvep_guided.py`, `mi_compare.py`, `itr.py` :
   rejouer un enregistrement, comparer, mesurer. C'est ici qu'on décide si une hypothèse tient,
   et il n'y a rien de honteux à ce qu'une analyse conclue « bruit ».

Reste `controller.py` et `live_ssvep.py`, hérités du banc d'essai robot : ils décodent et
envoient un `{jx,jy}` en UDP. Le produit ne fonctionne plus ainsi (l'API publie une intention
neutre sur LSL, cf. `docs/robot_testbed.md`), ils survivent comme référence de comparaison.
"""
