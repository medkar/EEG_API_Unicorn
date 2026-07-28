"""`core` — le moteur : casque Unicorn -> décodage -> flux LSL. C'est le produit.

**Le critère d'appartenance est vérifiable, pas une question de goût : un module est ici si et
seulement si `server.py` en a besoin pour tourner.** Le graphe est donc volontairement plat et
sans cycle :

    config  <-  acquisition, cca_decoder, neuro_monitor, lsl_io  <-  modes/  <-  server

- `config.py`      constantes partagées + chemins du dépôt (`PROJECT_ROOT`, `DATA_DIR`)
- `acquisition.py` BrainFlow : ouverture du casque, filtrage, tampon, contrôle de liaison
- `cca_decoder.py` SSVEP par CCA (aucun entraînement) + normalisation z contre un plancher
- `neuro_monitor.py` indices passifs charge/somnolence/engagement, z contre le repos du jour
- `lsl_io.py`      publication LSL et pont d'horloge — **le contrat public** avec les clients
- `server.py`      la boucle headless qui relie tout ça
- `modes/`         un mode = un contrat (`ModeSpec`) + son état vivant (`ModeRuntime`)

**Rien ici ne doit importer `research`.** Aucune dépendance à pygame non plus : le moteur tourne
sur une machine sans écran. Si un import de `research` devient nécessaire, c'est le signe que le
module visé a fini de mûrir — il DÉMÉNAGE dans `core`, on ne tire pas un fil à travers la
frontière. C'est ainsi qu'un mode passe de l'exploration au produit (roadmap SPEC §14.6 : MI,
P300, neuro, ErrP).

**Ni `console` non plus.** L'interface (`src/console/`, PySide6) est un CLIENT du moteur : elle
crée un `EngineServer`, lit son `snapshot()` et lui soumet des commandes. Le moteur, lui, ne sait
pas qu'elle existe — c'est ce qui lui permet de tourner sur une machine sans écran, et ce qui
rendrait un futur changement d'interface peu coûteux.
"""
