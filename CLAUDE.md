# Contexte projet — MLF_EEG_Waffle

Projet : **piloter un TurtleBot3 Waffle avec un casque EEG Unicorn** (g.tec Hybrid Black).

## Ce qu'il faut savoir en arrivant

- Le **robot est déjà entièrement configuré et validé** (voir [WAFFLE.md](WAFFLE.md)). Il a été mis en
  place dans le projet voisin `../MLF_CoinDetector`. **Ne PAS refaire le setup du robot.**
- Le Waffle expose une interface générique : il accepte un **joystick en UDP** — datagramme JSON
  `{"jx": <-1..1>, "jy": <-1..1>}` sur le **port 5005** du Pi. Un nœud ROS2 (`joystick_teleop`) déjà
  installé sur le Pi le traduit en `/cmd_vel`.
  - `jy>0` = avance, `jx>0` = tourne à droite, silence > 0,5 s = stop (watchdog).
- **Le PC EEG n'a PAS besoin de ROS2.** Juste une socket UDP. Voir `examples/send_joystick_udp.py`.
- Le travail de ce projet est **entièrement côté EEG** : acquisition Unicorn → décodage → `{jx, jy}` → UDP.

## Façon de travailler (préférences de l'utilisateur)

- Répondre en **français** ; README et messages de commit **en anglais** pour GitHub.
- Avancer par **petits pas testés sur le matériel** : éditer → (push/pull si besoin) → lancer → coller les logs.
- **Vérifier la doc** (SDK Unicorn, ROS2) avant d'affirmer ; citer les sources sur les points incertains.
- Recommander **une option claire** plutôt qu'un catalogue ; privilégier la simplicité.
- Sécurité robot : **roues en l'air** d'abord, vitesses basses, batterie chargée.

## Démarrage rapide du robot

Voir [WAFFLE.md](WAFFLE.md) §« Démarrer le robot ». En résumé : trouver l'IP du Pi
(`ping -4 wafflebot.local`), 2 sessions SSH → `ros2 launch turtlebot3_bringup robot.launch.py`
puis `ros2 run mlf_coin_teleop joystick_teleop`, et envoyer l'UDP depuis le PC.

## Matériel

Casque **Unicorn Hybrid Black** (8 voies EEG, 250 Hz, Bluetooth) + **TurtleBot3 Waffle**
(Raspberry Pi sous Ubuntu 22.04 + ROS2 Humble). PC de dev sous **Windows** (PowerShell).
