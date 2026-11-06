"""`stimulus/` — les fenêtres qui affichent un stimulus et publient des marqueurs.

Ces fenêtres sont des composants du produit, pas des outils de banc d'essai : la console les
LANCE, la calibration en DÉPEND, et `docs/markers.md` les présente aux étudiants comme les
émetteurs de référence.

**La règle de ce paquet, vérifiée par `python src/core/server.py --smoke` :**

    core       n'importe rien du dépôt hors de lui-même
    stimulus   -> core                    (jamais research, jamais console)
    console    -> core, stimulus
    research   -> core, stimulus

⚠️ **Une fenêtre de `stimulus/` n'ouvre JAMAIS le casque.** C'est ce qui lui permet de tourner en
même temps que le moteur : l'Unicorn n'accepte qu'une connexion. Elle dessine, elle publie des
marqueurs, et c'est tout. Le jour où l'une d'elles a besoin de lire l'EEG, la réponse n'est pas
d'ouvrir une seconde session — c'est que le calcul voulu appartient au moteur.

Une seule chose qu'elles LISENT : le flux DÉCODÉ public de leur mode (`--retour`, `retour.py`),
pour entourer la cible décodée — comme l'application d'un étudiant, par le nom du flux. Jamais
l'EEG : ce que le moteur a décidé, pas ce que le casque a mesuré.

⚠️ **L'horodatage se prend APRÈS `pygame.display.flip()`**, jamais avant. Le prendre avant décale
tous les marqueurs d'une frame, ce qui ne lève aucune exception et dégrade le décodage juste assez
pour ressembler à quelqu'un qui fixe mal.
"""
