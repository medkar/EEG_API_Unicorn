"""`console` — la console d'expérimentation (PySide6). Un CLIENT du moteur, pas le moteur.

Elle crée un `EngineServer`, lance sa boucle dans un fil, et sonde `snapshot()` par un `QTimer`.
Aucun HTTP, aucun navigateur.

**Deux règles, et elles ne sont pas négociables :**

1. *Le fil Qt ne touche jamais la session BrainFlow.* Toute action passe par `engine.submit()`,
   qui met la commande en file pour que la boucle du moteur l'applique elle-même. C'est ce qui
   protège l'acquisition.
2. *Aucune logique ici que le moteur ne possède pas déjà.* Pas de validation seulement côté
   console, pas de catalogue de modes en dur, pas de règle métier dans le code d'affichage. La
   console rend et envoie des commandes. C'est ce qui garde la majorité du travail testable sans
   écran, et ce qui rendrait un futur changement d'interface peu coûteux.

`console` importe `core`. `core` ne sait pas que `console` existe.
"""
