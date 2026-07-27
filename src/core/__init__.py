"""`core` — le moteur : casque Unicorn -> décodage -> flux LSL. C'est le produit.

**Le critère d'appartenance est vérifiable, pas une question de goût : un module est ici si et
seulement si `server.py` en a besoin pour tourner.** Le graphe est donc volontairement plat et
sans cycle :

    config  <-  acquisition, cca_decoder, lsl_io  <-  server  <-  dashboard

- `config.py`      constantes partagées + chemins du dépôt (`PROJECT_ROOT`, `DATA_DIR`)
- `acquisition.py` BrainFlow : ouverture du casque, filtrage, tampon, contrôle de liaison
- `cca_decoder.py` SSVEP par CCA (aucun entraînement) + normalisation z contre un plancher
- `lsl_io.py`      publication LSL et pont d'horloge — **le contrat public** avec les clients
- `server.py`      la boucle headless qui relie tout ça
- `dashboard.py`   tableau de bord web (FastAPI) au-dessus du moteur, dans le même processus

**Rien ici ne doit importer `research`.** Aucune dépendance à pygame non plus : le moteur tourne
sur une machine sans écran. Si un import de `research` devient nécessaire, c'est le signe que le
module visé a fini de mûrir — il DÉMÉNAGE dans `core`, on ne tire pas un fil à travers la
frontière. C'est ainsi qu'un mode passe de l'exploration au produit (roadmap SPEC §14.6 : MI,
P300, neuro, ErrP).
"""
