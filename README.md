# MLF_EEG_Waffle — piloter le TurtleBot3 Waffle avec un casque EEG Unicorn

POC : contrôler un **TurtleBot3 Waffle** à partir d'un **casque EEG Unicorn (g.tec Hybrid Black)**.

C'est le **même robot** que le projet voisin [`../MLF_CoinDetector`](../MLF_CoinDetector) (détection de
palet). Ce robot est **déjà entièrement configuré** et expose une interface générique :

```
Casque EEG Unicorn ──(acquisition + décodage d'intention)──►  {jx, jy}  ──UDP :5005──►  Waffle
```

## L'idée en une phrase

Le Waffle accepte déjà un **« joystick » envoyé en UDP** : un datagramme JSON `{"jx": …, "jy": …}`
(chaque valeur dans `[-1, 1]`) sur le **port 5005** du Pi du robot. Un nœud ROS2 (`joystick_teleop`)
tourne déjà sur le Pi et traduit ça en mouvement (`/cmd_vel`).

> **Ton seul travail dans ce projet = transformer les signaux EEG en `{jx, jy}` et les envoyer en UDP.**
> Rien à installer côté robot, **pas besoin de ROS2 sur le PC EEG** — juste une socket UDP.

- `jy > 0` → le robot **avance** ; `jy < 0` → recule
- `jx > 0` → le robot **tourne à droite** ; `jx < 0` → à gauche
- silence > 0,5 s → le robot **s'arrête** (watchdog de sécurité)

## Contrat d'intégration (le strict nécessaire)

| | |
|---|---|
| Cible | IP du Pi du Waffle, **port UDP 5005** |
| Payload | JSON UTF-8 : `{"jx": <float -1..1>, "jy": <float -1..1>}` |
| Cadence | envoyer en continu, ~**10–20 Hz** (au moins 2 Hz, sinon watchdog) |
| Réseau | le PC EEG doit être sur le **même LAN WiFi** que le Pi |

Exemple prêt à l'emploi : [`examples/send_joystick_udp.py`](examples/send_joystick_udp.py).

## Démarrer le robot (rappel)

Sur le Pi, deux sessions SSH (`echo $ROS_DOMAIN_ID` = **30** dans les deux). Détails, sécurité
et dépannage : [WAFFLE.md](WAFFLE.md) §4.

> **Le Pi est en DHCP, son IP change.** Connecte-toi par le nom mDNS :
> `ssh waffle_user@wafflebot.local` (c'est aussi ce que vise `config.UDP_HOST`).
> Si SSH refuse avec « REMOTE HOST IDENTIFICATION HAS CHANGED » après un changement de bail
> ou une réinstallation du Pi : vérifie d'abord `ping -4 wafflebot.local`, puis
> `ssh-keygen -R <ip>` pour retirer l'entrée périmée de `known_hosts`.

```bash
# Session A — bringup (drivers du robot) ; attendre "... Run!"
ros2 launch turtlebot3_bringup robot.launch.py

# Session B — pont UDP -> /cmd_vel (vitesses réduites pour tester)
ros2 run mlf_coin_teleop joystick_teleop --ros-args -p max_linear:=0.10 -p max_angular:=0.5
```

## Où trouver quoi

- **[WAFFLE.md](WAFFLE.md)** — TOUT sur le robot : trouver son IP, s'y connecter, le démarrer
  (bringup + nœud joystick), le contrat UDP, sécurité, dépannage, et réinstallation from scratch.
  **À lire en premier** pour reprendre le contrôle du robot.
- **[CLAUDE.md](CLAUDE.md)** — contexte pour démarrer une session Claude propre dans ce dossier.
- **[examples/](examples/)** — code minimal pour envoyer le joystick UDP + tester le robot sans EEG.
- **[src/](src/)** — l'appli EEG. Point d'entrée unique : **[`src/app.py`](src/app.py)** (menu →
  SSVEP / Motor Imagery / c-VEP). Les autres modules sont les briques et les outils de diagnostic.

## Lancer l'appli

```bash
python src/app.py                 # plein écran, casque réel — menu d'accueil
python src/app.py --windowed      # fenêtre (pour garder la console visible à côté)
python src/app.py --send          # envoi UDP au robot armé dès le départ (roues en l'air !)
python src/app.py --synthetic     # sans casque (board de test BrainFlow)
```

Au menu : `1` SSVEP · `2` Motor Imagery · `3` c-VEP · `4` calibrer MI · `5` calibrer c-VEP ·
`R` armer/désarmer l'envoi robot · `ESC` quitter. Dans un mode, `ESC` **revient au menu** — la
session BrainFlow et le socket UDP restent ouverts, donc changer de mode est instantané.

## Status & roadmap (EEG side)

The EEG→`{jx, jy}` pipeline lives in [`src/`](src/), built in small hardware-tested steps.
Three decoding paradigms share one app, one BrainFlow session and one UDP socket.

| Mode | How it works | Calibration | Status |
|---|---|---|---|
| **SSVEP** | Arrows flicker at 8.57 / 12 / 15 Hz, CCA picks the fixated frequency | 8 s rest baseline | ✅ **works, drives the robot** |
| **Motor Imagery** | Imagined left/right fist squeeze, ERD on C3/C4, CSP+LDA | 5–7 min | 🟡 ~48% per trial (chance 33%, usable ~60%) — needs practice |
| **c-VEP** | **6 targets on a ring**, one m-sequence at 6 circular shifts, learned template | ~3.5 min | 🟡 68% on 6 targets / 2.1 s = **27 bits/min** (best c-VEP so far) |

Frequencies/codes auto-adapt to the display refresh. Fixating nothing = no detection = watchdog stop.

**Why three modes.** SSVEP is the reliable workhorse but competes with the user's strong ~10.5 Hz
alpha peak and requires staring at a flicker. c-VEP spreads its spectrum, so it dodges alpha
entirely and separates targets by a sharply-peaked autocorrelation — at the price of a short
calibration. Motor Imagery needs no screen at all, but is by far the hardest.

| Brick | Module |
|---|---|
| Shared config — commands, frequencies, codes, channels, mapping, network | [`src/config.py`](src/config.py) |
| Acquisition — Unicorn via BrainFlow, sliding windows / epochs | [`src/acquisition.py`](src/acquisition.py) |
| SSVEP stimulus + CCA decoder + vote/mapping/UDP | [`ssvep_stimulus`](src/ssvep_stimulus.py) · [`cca_decoder`](src/cca_decoder.py) · [`controller`](src/controller.py) |
| Motor Imagery — CSP+LDA (or Riemannian), calibration, offline compare | [`mi_decoder`](src/mi_decoder.py) · [`mi_calibrate`](src/mi_calibrate.py) · [`mi_compare`](src/mi_compare.py) |
| c-VEP — m-sequence, spatial filter + template, calibration | [`cvep_code`](src/cvep_code.py) · [`cvep_decoder`](src/cvep_decoder.py) · [`cvep_calibrate`](src/cvep_calibrate.py) |
| Shared window / headset session / UDP sender | [`src/ui.py`](src/ui.py) |

**Diagnostics & self-tests (no headset needed):**

```bash
python src/app.py --smoke            # whole app headless: menu + 3 modes + c-VEP calibration
python src/cvep_code.py              # m-sequence properties (balance, autocorrelation, lags)
python src/cvep_decoder.py           # c-VEP accuracy vs SNR on synthetic responses
python src/cca_decoder.py            # CCA accuracy on synthetic SSVEP
python src/controller.py             # decode -> vote -> UDP, checked over local loopback
python src/live_ssvep.py --guided    # scripted SSVEP protocol (calibrates rho_min / margin)
python src/alpha_check.py            # eyes open/closed alpha — electrode contact sanity check
python src/mi_compare.py --sweep     # MI: per-trial cross-validation, warm-up effect
python src/cvep_analyze.py           # c-VEP: replay a calibration offline (jitter, cycles, thresholds)
python src/itr.py                    # information transfer rate — common yardstick across paradigms
```

**Note on intent.** This is an *exploration* of what an 8-channel dry headset can do, not a
product. The robot is a measurement pretext. Paradigms are therefore compared on **information
transfer rate** (`itr.py`) rather than ranked, and a mode being slower or less accurate than
another is not a reason to drop it — the question is what it lets you measure that the others
cannot. Current standing: SSVEP 3 targets / 95% / 1.5 s ≈ **50 bits/min**, which is the bar.
c-VEP's only structural edge is target count (63 available lags vs ~4 usable flicker
frequencies on a 60 Hz screen); it would need ~8 targets at 85% to pass SSVEP.

**Per-frequency noise floor (important).** Each target sits on a different amount of background
alpha, so its resting ρ floor differs — and the floor *moves between sessions*. Measured:
GAUCHE (12 Hz) had a 0.28 floor on the session that worked and 0.36 on a degraded one, where it
emitted 3/27 despite a fixation mean above the global threshold. A single global threshold is
therefore structurally unfair. SSVEP mode now measures μ/σ at rest for 8 s at startup and decides
on **z = (ρ−μ)/σ** (`Z_MIN`, `SSVEP_BASELINE_S`). Offline on the validated session this took AVANT
from 61% to 100% and GAUCHE from 80% to 100%; **confirmed on hardware — all three targets improved,
not just the contaminated one.** Do **not** retune frequencies on the strength of one bad session —
the frequency was never the problem, the floor was.

**The open experiment — how many targets?** SSVEP is capped by the integer divisors of the
refresh rate (~4 usable frequencies off the alpha peak at 60 Hz). c-VEP has as many lags as the
code has bits (63), so target count is the one axis where it can structurally win. Neighbouring
lags must stay further apart than a VEP response (~150 ms), which sets the ceiling at 60 Hz:

| targets | 3 | 4 | **6** | 8 |
|---|---|---|---|---|
| lag separation | 350 ms | 262 ms | **175 ms** | 131 ms ✗ |

`CVEP_N_TARGETS = 6` is the retained compromise — it also buys reverse and arcs, which the
3-target SSVEP cannot express. Target: ~8 targets at 85% would pass SSVEP's 50 bits/min, but 8 is
below the VEP-width limit on a 60 Hz screen (a longer code would fix the separation at the cost of
cycle time). Calibration now reports ITR directly, against the SSVEP reference.

**Measured so far (c-VEP, 6 targets):** 3 targets → 6.1 bits/min; 6 targets → 15.4; 6 targets with
an **interleaved, order-randomised** calibration → **27.1**. That last +76% came purely from fixing
a protocol confound: recording each target as one contiguous block made "which target" inseparable
from "when" (accuracy ran 34% / 28% / 66% across thirds of the session). Calibration now shuffles
`CVEP_CAL_BLOCKS` blocks per target. Errors are *not* concentrated on neighbouring lags, so lag
separation is not the limiting factor — SNR is, and more targets would not cost in neighbour
confusion.

**Next:**

1. **Open question**: one target (lower-left, lag 42) sits at chance — 29% [14-50] vs 67% [45-83]
   for the top one, at 21 decisions each. Not explained by presentation order, neighbour
   confusion, or lag→sample rounding (which is exactly zero for lag 42). Re-calibrate with
   `CVEP_LAG_ROTATION = 1` to separate *screen position* from *lag*. Lifting that one target to
   the others' level would give ~34 bits/min.
2. Arm the robot with SSVEP (`app.py`, `R` then `1`) — wheels up first, then on the ground.
   Thresholds are still synthetic placeholders — ρ did *not* separate correct from wrong
   decisions on the first real session, so the sliding vote carries the safety, not `CVEP_CORR_MIN`.
3. MI: one rested, warmed-up session; if per-trial CV ≥ ~55%, arm the robot.
4. Verify whether left/right are inverted on the robot too (`JOY_INVERT_X`).

> Dependencies: `pip install pygame brainflow numpy scipy scikit-learn pyriemann joblib`.
