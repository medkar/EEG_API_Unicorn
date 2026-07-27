# Banc d'essai historique — robot TurtleBot3 Waffle

> ⚠️ **Note d'archive.** Ce robot a servi de **banc d'essai** pour valider le décodage EEG en
> conditions réelles (« est-ce qu'une intention décodée pilote vraiment quelque chose ? »). Ce
> **n'est plus un objectif du projet** : EEG_API_Unicorn diffuse des intentions neutres, et
> l'application cliente décide quoi en faire. Ce document est conservé pour pouvoir refaire une
> démonstration robot, pas comme référence d'architecture — voir [SPEC.md](SPEC.md) pour le projet.

Le TurtleBot3 Waffle est **déjà configuré et validé**. Ce document contient tout pour le reprendre en
main sans rien réinstaller. Interface : un **joystick UDP** (voir §0).

---

## 0. Contrat d'intégration (le point d'entrée de ce projet)

Le robot accepte un joystick envoyé en **UDP** sur le **port 5005** du Pi :

- **Payload** : JSON UTF-8 `{"jx": <float -1..1>, "jy": <float -1..1>}`
- `jy > 0` → **avance** (`linear.x > 0`) ; `jy < 0` → recule
- `jx > 0` → **tourne à droite** (`angular.z < 0`) ; `jx < 0` → à gauche
- **Zone morte** 0.12 : `|j| < 0.12` = neutre (utile pour un « stop » stable)
- **Cadence** : envoyer en continu ~10–20 Hz. **Watchdog** : aucun paquet pendant **0,5 s** → le robot s'arrête.
- Vitesses max côté robot : `max_linear = 0.15 m/s`, `max_angular = 0.8 rad/s` (réglables, voir §8).

> Le PC qui envoie l'UDP **n'a pas besoin de ROS2**, juste d'une socket UDP et d'être sur le **même LAN**
> que le Pi. Exemple : `examples/send_joystick_udp.py`.

Le nœud qui reçoit ce joystick s'appelle `joystick_teleop` (package `mlf_coin_teleop`) et tourne
**sur le Pi du Waffle**. Son code source vit dans le repo voisin `MLF_CoinDetector/ros2/`, et il est
**déjà buildé sur le Pi** (`~/mlf_ws`). Rien à recompiler pour ce projet.

---

## 1. Repères (état validé)

| Élément | Valeur |
|---|---|
| Pi du Waffle | Ubuntu Server 22.04, ROS2 **Humble**, aarch64 |
| Hostname / user SSH | `waffleBot` / `waffle_user` |
| IP du Pi | `10.191.69.104` — ⚠️ **DHCP**, peut changer (voir §2) ; MAC `e4-5f-01-d3-22-e1` |
| `ROS_DOMAIN_ID` | **30** — identique dans toutes les fenêtres SSH du Pi |
| Modèle / lidar | `TURTLEBOT3_MODEL=waffle_pi`, `LDS_MODEL=LDS-01` |
| Workspaces sur le Pi | `~/turtlebot3_ws` (stack turtlebot3), `~/mlf_ws` (nœud joystick) |

Les variables d'env sont déjà dans le `~/.bashrc` du Pi.

---

## 2. Trouver l'IP du Pi (PC Windows, PowerShell)

**a) Par le hostname (mDNS).** Le `-4` force l'**IPv4** (sans lui, tu peux obtenir l'IPv6 `fe80::…`,
OK pour SSH mais pas pour l'UDP) :
```powershell
ping -4 wafflebot.local
```

**b) Par scan ARP** (si `.local` ne résout pas) — remplace `10.191.69` par ton sous-réseau
(`ipconfig` → ligne IPv4 de ta carte Wi-Fi) :
```powershell
$tasks = 1..254 | ForEach-Object { (New-Object System.Net.NetworkInformation.Ping).SendPingAsync("10.191.69.$_",250) }
[System.Threading.Tasks.Task]::WaitAll($tasks); Start-Sleep 1
arp -a | Select-String "e4-5f-01|b8-27-eb|dc-a6-32|d8-3a-dd|2c-cf-67"   # préfixes MAC Raspberry Pi
```

**c) Vérifier le SSH :**
```powershell
Test-NetConnection -ComputerName 10.191.69.104 -Port 22
```

> Si l'IP a changé, mets à jour l'adresse cible de ton envoi UDP (dans ton code EEG).

---

## 3. Se connecter — deux sessions SSH

Ouvre deux terminaux (2× PowerShell ou 2 onglets VS Code) :
```powershell
ssh -o ServerAliveInterval=60 waffle_user@10.191.69.104
```
> ⚠️ Si le **PC se met en veille**, le SSH coupe et les programmes du Pi s'arrêtent. La veille secteur
> du PC a été désactivée (`powercfg /change standby-timeout-ac 0`). Pour les tâches longues, utiliser
> `tmux` sur le Pi (`tmux new -s x` ; `Ctrl+B` puis `d` pour détacher ; `tmux attach -t x`).

---

## 4. Démarrer le robot

### 🛑 Sécurité d'abord
- Robot **roues en l'air** tant que le sens n'est pas vérifié.
- Batterie LiPo **chargée** (≥ ~11,5 V). Un **bip + arrêt** = alarme de sous-tension → recharger.
- OpenCR : interrupteur **POWER sur ON** (LED rouge), câble micro-USB relié au Pi.

### Session A — bringup (drivers du robot)
```bash
ros2 launch turtlebot3_bringup robot.launch.py
```
Attends `turtlebot3_node ... Run!` et `diff_drive_controller ... Run!`. Laisse tourner.

### Session B — nœud joystick (reçoit ton UDP)
```bash
ros2 run mlf_coin_teleop joystick_teleop
```
Doit afficher `Écoute joystick UDP sur :5005 -> publie /cmd_vel`. Laisse tourner.

> Vérif : dans chaque session, `echo $ROS_DOMAIN_ID` = **30** et `ros2 node list` liste
> `/turtlebot3_node` + `/diff_drive_controller`. Si non → problème de domaine DDS (§7).

---

## 5. Envoyer le joystick (test sans EEG, depuis le PC)

Roues en l'air. Depuis PowerShell :
```powershell
$c = New-Object System.Net.Sockets.UdpClient
$ip = "10.191.69.104"; $port = 5005
$msg = '{"jx":0.0,"jy":0.6}'          # avance ; jx=droite, jy=avant
$b = [System.Text.Encoding]::UTF8.GetBytes($msg)
for ($i=0; $i -lt 20; $i++) { [void]$c.Send($b, $b.Length, $ip, $port); Start-Sleep -Milliseconds 100 }
$c.Close()
```
Variantes : `{"jx":0.6,"jy":0.0}` (virage droite), `{"jx":0.5,"jy":0.5}` (diagonale). Le robot
s'arrête ~0,5 s après la fin de l'envoi (watchdog).

Voir aussi `examples/send_joystick_udp.py` (Python, réutilisable dans l'appli EEG).

Pour visualiser la commande : 3ᵉ session SSH sur le Pi → `ros2 topic echo /cmd_vel`.

---

## 6. Arrêt

- `Ctrl+C` dans les fenêtres bringup et nœud.
- Roues qui restent en mouvement après un `ros2 topic pub` manuel → envoyer un stop :
  ```bash
  ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.0}, angular: {z: 0.0}}"
  ```
- Éteindre l'OpenCR et débrancher la batterie au rangement.

---

## 7. Dépannage (pièges rencontrés)

| Symptôme | Cause / correctif |
|---|---|
| Roues muettes, `Unknown topic '/cmd_vel'`, `ros2 node list` incomplet | **`ROS_DOMAIN_ID` différent** entre fenêtres. Vérifier `echo $ROS_DOMAIN_ID`=30 partout. |
| Bringup : `package 'ld08_driver' not found` | Mauvais lidar : `export LDS_MODEL=LDS-01` (déjà dans `~/.bashrc`). |
| Roues ne s'arrêtent pas après `ros2 topic pub` | Le contrôleur garde la dernière consigne : envoyer un Twist nul (§6). Le nœud joystick, lui, a un watchdog. |
| Robot **bipe puis s'arrête** | Batterie basse (< ~11 V) : recharger ou brancher l'alim 12 V (SMPS). |
| SSH coupé (veille PC) → programmes tués | Veille secteur désactivée ; sinon lancer dans `tmux`. |
| Le robot ne reçoit pas mon UDP | PC EEG sur le **même LAN** ? `ping 10.191.69.104`. Bon port (**5005**) et bonne IP ? Nœud `joystick_teleop` lancé (§4) ? |
| Un axe inversé | Côté CoinDetector il y a `JOY_INVERT_X/Y` ; ici tu maîtrises directement le signe de `jx`/`jy` que tu envoies — inverse-le à la source. |

---

## 8. Régler les vitesses du nœud

Au lancement du nœud (§4, session B), tu peux baisser les vitesses :
```bash
ros2 run mlf_coin_teleop joystick_teleop --ros-args -p max_linear:=0.10 -p max_angular:=0.5
```
Paramètres : `udp_port` (5005), `max_linear` (0.15 m/s), `max_angular` (0.8 rad/s),
`deadzone` (0.12), `timeout` (0.5 s), `cmd_vel_topic` (`/cmd_vel`).

---

## 9. Annexe — réinstaller le Pi from scratch (si reflash de la SD)

1. **Flasher** Ubuntu Server 22.04.5 LTS 64-bit (Raspberry Pi Imager) ; pré-régler hostname,
   user/mot de passe, Wi-Fi (+ pays), **SSH activé**.
2. **ROS2 Humble (ros-base)** :
   ```bash
   sudo apt update && sudo apt install -y locales software-properties-common curl
   sudo locale-gen en_US en_US.UTF-8 && sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
   sudo add-apt-repository universe -y
   export ROS_APT_SOURCE_VERSION=$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest | grep -F "tag_name" | awk -F\" '{print $4}')
   curl -L -o /tmp/ros2-apt-source.deb "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.$(. /etc/os-release && echo $VERSION_CODENAME)_all.deb"
   sudo apt install -y /tmp/ros2-apt-source.deb
   sudo apt update && sudo apt upgrade -y && sudo apt install -y ros-humble-ros-base ros-dev-tools
   ```
3. **Env** (`~/.bashrc`) : `source /opt/ros/humble/setup.bash`, `export ROS_DOMAIN_ID=30`,
   `export TURTLEBOT3_MODEL=waffle_pi`, `export LDS_MODEL=LDS-01`.
4. **Stack turtlebot3** :
   ```bash
   mkdir -p ~/turtlebot3_ws/src && cd ~/turtlebot3_ws/src
   git clone -b humble https://github.com/ROBOTIS-GIT/turtlebot3.git
   cd ~/turtlebot3_ws && sudo rosdep init; rosdep update
   rosdep install --from-paths src --ignore-src -r -y
   colcon build --symlink-install --parallel-workers 1
   echo 'source ~/turtlebot3_ws/install/setup.bash' >> ~/.bashrc && source ~/.bashrc
   sudo cp $(ros2 pkg prefix turtlebot3_bringup)/share/turtlebot3_bringup/script/99-turtlebot3-cdc.rules /etc/udev/rules.d/
   sudo udevadm control --reload-rules && sudo udevadm trigger
   ```
5. **Firmware OpenCR** (OpenCR alimenté + relié en USB) :
   ```bash
   sudo dpkg --add-architecture armhf && sudo apt-get update && sudo apt-get install -y libc6:armhf
   export OPENCR_PORT=/dev/ttyACM0 OPENCR_MODEL=waffle
   rm -rf ./opencr_update.tar.bz2
   wget https://github.com/ROBOTIS-GIT/OpenCR-Binaries/raw/master/turtlebot3/ROS2/latest/opencr_update.tar.bz2
   tar -xvf opencr_update.tar.bz2 && cd ./opencr_update && ./update.sh $OPENCR_PORT $OPENCR_MODEL.opencr
   ```
6. **Nœud joystick** (le pont UDP→/cmd_vel réutilisé ici) :
   ```bash
   cd ~ && git clone https://github.com/medkar/MLF_coinDetector.git
   mkdir -p ~/mlf_ws/src && cp -r ~/MLF_coinDetector/ros2/mlf_coin_teleop ~/mlf_ws/src/
   cd ~/mlf_ws && colcon build --symlink-install
   echo 'source ~/mlf_ws/install/setup.bash' >> ~/.bashrc && source ~/.bashrc
   ```

Démarrage normal = §4.
