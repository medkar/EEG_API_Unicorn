"""`stimulus/` — les fenêtres qui affichent un stimulus et publient des marqueurs.

Quatrième paquet du dépôt, créé le 2026-09-07. Ces trois fichiers vivaient dans `research/`, où ils
n'étaient plus à leur place : la console les LANCE, la calibration en DÉPEND, et `docs/markers.md`
les présente aux étudiants comme les émetteurs de référence. Ce ne sont plus des outils de banc
d'essai, ce sont des composants du produit.

**La règle de ce paquet, vérifiée par `python src/core/server.py --smoke` :**

    core       n'importe rien du dépôt hors de lui-même
    stimulus   -> core                    (jamais research, jamais console)
    console    -> core, stimulus
    research   -> core, stimulus

⚠️ **Une fenêtre de `stimulus/` n'ouvre JAMAIS le casque.** C'est ce qui lui permet de tourner en
même temps que le moteur : l'Unicorn n'accepte qu'une connexion. Elle dessine, elle publie des
marqueurs, et c'est tout. Le jour où l'une d'elles a besoin de lire l'EEG, la réponse n'est pas
d'ouvrir une seconde session — c'est que le calcul voulu appartient au moteur.

⚠️ **L'horodatage se prend APRÈS `pygame.display.flip()`**, jamais avant. Le prendre avant décale
tous les marqueurs d'une frame, ce qui ne lève aucune exception et dégrade le décodage juste assez
pour ressembler à quelqu'un qui fixe mal.
"""
