"""Source unique de vérité pour l'appli EEG : commandes, mapping {jx,jy}, voies, réseau.

Importé par le stimulus (`ssvep_stimulus.py`), le décodeur (`cca_decoder.py`) et la boucle
d'intégration (`controller.py`) pour qu'ils ne divergent JAMAIS (une seule table à éditer).
"""

import math as _math
import os as _os
import sys as _sys
import time as _time
import itertools as _itertools

# Racine du dépôt, déduite de l'emplacement de CE fichier (src/core/config.py -> ../../).
# Tout le monde passe par ces trois constantes plutôt que de recompter des `dirname` : le jour
# où un module change de dossier, seul ce fichier est à corriger. C'est exactement le piège que
# la restructuration `core/`/`research/` a failli déclencher — dix calculs de racine dispersés,
# qui auraient tous pointé sur `src/` au lieu du dépôt, silencieusement.
PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
DATA_DIR = _os.path.join(PROJECT_ROOT, "data")          # modèles entraînés, enregistrements
EXAMPLES_DIR = _os.path.join(PROJECT_ROOT, "examples")  # clients d'exemple (récepteur LSL, UDP)

FS_UNICORN = 250.0  # échantillonnage de l'Unicorn Hybrid Black (Hz)


# --- Contrôle de la liaison casque -------------------------------------------
# σ par voie (après filtrage) délimitant un signal EEG plausible. Sous le seuil bas la voie est
# PLATE : câble débranché, électrode décollée, casque éteint — c'est ce qui a fait enregistrer
# 3,4 min de vide le 2026-07-20 sans le moindre avertissement. Au-dessus du seuil haut la voie
# flotte ou sature. Entre les deux, l'EEG réel (typiquement 5-20 en bande 5-40 Hz).
SIGNAL_DEAD_SIGMA = 0.5
SIGNAL_SAT_SIGMA = 500.0


# Corrélation médiane entre voies au-delà de laquelle la RÉFÉRENCE (mastoïde) est décrochée.
# Défaut invisible au σ : les 8 voies mesurent alors la même référence flottante avec des
# amplitudes plausibles, et l'écran de contrôle affiche 8 barres rassurantes sur un signal vide.
# Mesuré sur casque le 2026-07-27 : mastoïdes absentes -> médiane +1,000 (mode commun pur) ;
# mastoïdes en place -> +0,31 à +0,50. Le seuil est posé à mi-chemin, avec une marge énorme des
# deux côtés — ce n'est pas un réglage statistique fin mais la détection d'un régime physique.
# ⚠️ Calibré sur UNE séance ; si un montage sain déclenchait l'alerte, c'est ce seuil qu'il faut
# revoir en premier (et non l'ignorer).
COMMON_MODE_MAX = 0.90


def reference_lost(common_mode):
    """True si la corrélation inter-voies trahit une référence décrochée. None -> False."""
    return common_mode is not None and common_mode > COMMON_MODE_MAX


def signal_verdict(sigma):
    """'morte' | 'saturée' | 'ok' pour une voie, depuis son σ filtré."""
    if sigma < SIGNAL_DEAD_SIGMA:
        return "morte"
    if sigma > SIGNAL_SAT_SIGMA:
        return "saturée"
    return "ok"


def json_float(value, digits=2):
    """Arrondi sûr pour un état destiné à JSON : rend None au lieu d'un NaN ou d'un infini.

    JSON n'a pas de NaN. Python l'écrit quand même (`NaN` nu, invalide), mais les sérialiseurs
    stricts lèvent une exception — et le prix d'UNE seule valeur indéfinie serait alors la perte
    de TOUT l'état : plus de qualité, plus de phase, plus de flux, un écran vide et rien pour
    comprendre. Vécu le 2026-07-27 : une voie constante suffisait à faire sortir un NaN de
    `np.corrcoef`, et toute la page devenait blanche.
    """
    if value is None:
        return None
    value = float(value)
    return None if not _math.isfinite(value) else round(value, digits)


def use_utf8_console():
    """Force stdout/stderr en UTF-8. PowerShell est en cp1252 par défaut et plante sur
    les caractères non-latins (σ, →, ...). À appeler au début de chaque `__main__`."""
    for stream in (_sys.stdout, _sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # flux déjà redirigé / non reconfigurable
            pass


def empreinte_dossier(dossier=DATA_DIR):
    """`{nom: (taille, mtime)}` d'un dossier — ce qu'un test ne doit JAMAIS faire bouger.

    Vit ICI (`core/`, pas `research/app.py`) pour être appelable depuis N'IMPORTE QUEL smoke du
    dépôt, `archive/` compris — c'est précisément ce qui manquait le 2026-08-21 : les deux smokes
    c-VEP archivés n'avaient AUCUN moyen de se garder eux-mêmes contre une écriture dans le vrai
    `data/`, parce que la seule fonction qui le vérifiait vivait dans `research/app.py` et n'était
    appelée que par SON PROPRE smoke. Un dossier gitignoré ne se protège pas fichier par fichier :
    un garde-fou qui ne couvre qu'UN appelant sur plusieurs n'en couvre aucun avec certitude.

    `data/` porte des enregistrements EEG d'une personne identifiable, sur un dépôt public. Il
    porte aussi les modèles du casque, dont le plus récent CHARGEABLE est le défaut proposé par le
    moteur, la console et les applis pygame : un fichier de test oublié là ne se contente pas
    d'encombrer, il se fait ÉLIRE.

    Rendre le dossier absent comme un dictionnaire vide, et non lever : un dépôt fraîchement cloné
    n'a pas de `data/`, et un smoke doit y tourner quand même.

    ⚠️ **CE GARDE EST AVEUGLE À UN CRÉER-PUIS-EFFACER DANS LA MÊME FENÊTRE DE MESURE.** Mesuré
    (revue de tâche 6, tour 2) : `server.py --smoke` crée puis efface `data/mi_model_smoke.joblib`
    dans le VRAI `data/` — l'empreinte avant et après sont IDENTIQUES, parce que le fichier n'existe
    déjà plus au second appel. Une comparaison `{nom: (taille, mtime)}` avant/après ne voit QUE ce
    qui reste sur le disque au moment des deux instantanés ; elle ne voit pas ce qui est passé
    entre les deux. Elle protège contre l'accident mesuré ce tour-ci (un fichier de test qui SURVIT
    et se fait élire comme le plus récent modèle chargeable) — pas contre toute écriture, aussi
    brève soit-elle. Un garde étanche demanderait de surveiller le dossier PENDANT l'exécution
    (`watchdog`, ou un stub qui intercepte les appels d'écriture), pas seulement avant/après.
    """
    if not _os.path.isdir(dossier):
        return {}
    return {nom: (_os.path.getsize(_os.path.join(dossier, nom)),
                  _os.path.getmtime(_os.path.join(dossier, nom)))
            for nom in sorted(_os.listdir(dossier))}

# Ordre des 8 voies de l'Unicorn Hybrid Black (montage standard g.tec).
CH_NAMES = ["Fz", "C3", "Cz", "C4", "Pz", "PO7", "Oz", "PO8"]
# Voies occipitales = les plus réactives au SSVEP. Indices dans CH_NAMES.
# Pz (4) ajouté le 2026-07-20 après TROIS runs guidés concordants (ssvep_analyze.py) :
# +7,2 / +4,9 / +9,9 points d'accuracy, toujours dans le même sens, y compris sur un run
# saturé d'artefacts. C'était le critère fixé d'avance (2-3 runs concordants) — les fenêtres
# se chevauchent (1,5 s toutes les 0,25 s) donc l'effectif indépendant vaut ~5 essais/cible
# et non 27 : une seule séance n'aurait rien prouvé.
# ⚠️ Limite assumée : les 3 runs viennent de la MÊME séance, donc du même montage. Ce qui
# rend le changement acceptable malgré ça, c'est qu'il ne peut pas surapprendre — la CCA
# n'apprend rien, elle corrèle contre des sinusoïdes de référence. Ajouter une voie utile
# améliore la projection, une voie inutile est simplement pondérée à ~0.
OCCIPITAL = [4, 5, 6, 7]  # Pz, PO7, Oz, PO8

# Table maîtresse des commandes. `desired_hz` sera arrondi au diviseur entier du refresh
# écran (voir choose_frequencies). `jx, jy` = consigne à deux axes pour l'actionneur d'exemple
# (l'API LSL, elle, ne publie QUE l'intention : quelle cible — jamais de commande d'actionneur).
#   jy>0 avance, jy<0 recule ; jx>0 droite, jx<0 gauche.
# 3 cibles (avant + 2 rotations ; demi-tour = tourner). Fréquences choisies pour ENJAMBER le
# pic alpha de l'utilisateur (~10.5 Hz) SANS cible dessus. Une cible pile sur le pic (10 Hz)
# explosait au repos ET écrasait sa voisine — cf. session 3.
# GAUCHE : 12 -> **20 Hz** (2026-07-21). À 12 Hz (1,5 Hz de l'alpha) sa réponse n'émergeait pas
# de son propre bruit même après normalisation z (séparabilité 0,3-0,5 vs 2-6 pour les autres) ;
# testée à 20 Hz via le sélecteur, elle marche NETTEMENT mieux (retour utilisateur). 20 Hz =
# diviseur entier de 60 (n=3), loin de l'alpha, sans collision d'harmonique avec 15/8,57.
# Compromis assumé : amplitude SSVEP plus faible en haute fréquence, mais compensé par la
# sortie de la zone alpha. Réserve : confirmé sur 1 séance ; le sélecteur de fréquences SSVEP
# permet d'y revenir. Les 8.57/12/15 restent l'historique de référence pour rejouer les vieux logs.
COMMANDS = [
    {"name": "AVANT",  "dir": "up",    "desired_hz": 15.0, "jx": 0.0,  "jy": 0.6},
    {"name": "GAUCHE", "dir": "left",  "desired_hz": 20.0, "jx": -0.6, "jy": 0.0},
    {"name": "DROITE", "dir": "right", "desired_hz": 8.57, "jx": 0.6,  "jy": 0.0},
]

COMMON_REFRESH = [60, 75, 90, 100, 120, 144, 165, 240]  # pour « snapper » la mesure

# ⚠️ MESURE PERSONNELLE, pas une constante universelle. C'est le pic alpha du développeur.
# Le pic alpha individuel varie fortement d'une personne à l'autre (moyenne de population ~9,6 Hz,
# écart-type ~1 Hz, plage 7-13 Hz, décroissant avec l'âge). Un seul consommateur aujourd'hui :
# `research/app.py`, pour ses propres séances. Tout ce qui s'adresse à QUELQU'UN D'AUTRE doit
# passer par le réglage `alpha_hz` du mode SSVEP, pas par cette valeur.
ALPHA_PEAK_HZ = 10.5

# Hôte par défaut de l'ACTIONNEUR d'exemple (examples/actuator_udp.py). Rien dans l'API n'en
# dépend : le moteur publie une intention neutre sur LSL, traduire ça en action appartient au
# client. Cette valeur est celle du banc d'essai robot historique, gardée parce qu'un montage
# existant l'écoute encore. On vise le NOM mDNS, pas une IP : le Pi est en DHCP et son adresse
# change (observé : .104 -> .102 le 2026-07-20, ce qui aurait envoyé les commandes dans le vide
# SANS message d'erreur — l'UDP ne signale rien). Résolution vérifiée depuis Python sous Windows.
# Si le mDNS venait à ne plus répondre : `ping -4 wafflebot.local` puis remettre l'IP en dur ici.
UDP_HOST = "wafflebot.local"
UDP_PORT = 5005

# Numéro de série de l'Unicorn appairé (Bluetooth). Sélectionne le casque si plusieurs sont
# appairés ; None => auto-découverte par BrainFlow.
UNICORN_SERIAL = "UN-2023.08.50"

# --- Fenêtre & décision ------------------------------------------------------
# Cibles hors du pic alpha (8.57/12/15) => ρ propre. MARGE (1er-2e) + LISSAGE trient repos
# vs fixation. 1 s s'était révélé trop bruité (le ρ alpha explosait) -> 1.5 s = compromis
# bruit/réactivité. À re-valider via `live_ssvep.py --guided`.
WINDOW_S = 1.5     # longueur de la fenêtre CCA (s) — courte = plus réactif, mais plus bruité
RHO_MIN = 0.45     # corrélation mini du gagnant
MARGIN = 0.18      # écart mini entre ρ du 1er et du 2e
VOTE_LEN = 4       # fenêtres du vote glissant (~0.8 s à 5 Hz de décodage)
MIN_VOTES = 3      # votes concordants requis pour émettre une commande

# Le SSVEP décroît avec la fréquence : sans leurs harmoniques, 12/15 Hz sont sous-détectées
# vs 8.57 Hz. Passe-bande large (capte 15->30, 12->24&36) + 3 harmoniques dans la CCA
# renforcent SÉLECTIVEMENT les fréquences hautes. Zéro latence ajoutée.
BANDPASS = (5.0, 40.0)   # passe-bande acquisition (Hz)
# Marge jetée après filtrage, pour le SSVEP. Le filtre de BrainFlow (`perform_bandpass`) est à
# PASSE UNIQUE : il met ~50 échantillons à s'établir, soit 13 % d'une fenêtre de 375 (1,5 s),
# contaminés à chaque décodage. On récupère donc `WINDOW_S + FILTER_MARGIN_S`, on filtre, et on
# ne garde que la fin — le transitoire tombe dans la partie jetée. Coût : ~1 s au démarrage.
# NB : ne s'applique PAS au c-VEP ni au MI, qui filtrent avec `scipy.filtfilt` — celui-ci pade
# déjà les bords, et surtout leur template/modèle est appris sur des époques filtrées SANS marge :
# en ajouter en ligne créerait un décalage entre calibration et usage, pour un gain nul.
FILTER_MARGIN_S = 1.0
N_HARMONICS = 3          # harmoniques (fondamentale incluse) des références CCA

# --- Proposition de fréquences SSVEP (chantier 2) ------------------------------------------
# Écart minimum entre une cible et le pic alpha de la personne. Une cible posée sur le pic ne se
# distingue pas du fond : la corrélation de repos y est déjà élevée, donc la normalisation z ne
# fait plus émerger la réponse.
#
# 1,9 Hz est ENCADRÉ par les deux seules mesures dont ce projet dispose, sur une personne dont le
# pic est à 10,5 Hz :
#   12 Hz    (à 1,50 Hz du pic) ÉCHOUE — séparabilité 0,3-0,5 contre 2-6 pour les autres cibles
#   8,571 Hz (à 1,93 Hz du pic) MARCHE — c'est une des trois fréquences validées casque
# 1,9 est la valeur RETENUE dans l'intervalle [1,50 ; 1,93] que ces deux mesures encadrent — ce
# n'est PAS la plus grande valeur compatible avec les deux (qui serait 1,9286 Hz, l'écart exact de
# 8,571 Hz au pic). ⚠️ n = 1 personne : à réviser dès qu'on aura mesuré sur plusieurs. Elle
# n'interdit rien, elle oriente seulement la proposition.
ALPHA_GARDE_HZ = 1.9

# Pic alpha par défaut : la MOYENNE DE POPULATION, délibérément pas celle du développeur.
ALPHA_DEFAUT_HZ = 9.6

# Plage où l'on propose en priorité. En dessous, le scintillement est pénible et la réponse
# chevauche le thêta ; au-dessus, l'amplitude SSVEP décroît nettement. ⚠️ Seul choix de la règle
# qui ne s'adosse à AUCUNE mesure de ce projet — il vient de la pratique courante du SSVEP. Isolé
# ici pour être révisable. La proposition en sort d'elle-même quand il le faut, en le disant.
CONFORT_HZ = (8.0, 20.0)

# Tolérance RELATIVE pour reconnaître un diviseur du refresh dans une valeur SAISIE À LA MAIN.
# Elle ne peut pas confondre deux diviseurs voisins : à 60 Hz, les plus proches sont 60/7 = 8,571
# et 60/8 = 7,5, soit 12 % d'écart — cent fois cette tolérance.
# ⚠️ Une tolérance ABSOLUE sur le rapport `refresh/f` a été essayée, et elle s'est retournée contre
# elle-même : réglée à 1e-6, elle refusait « 8.57143 » — la valeur que son PROPRE message de refus
# affichait — et n'acceptait que le flottant exact à seize chiffres. Le garde-fou censé supprimer
# une panne silencieuse en devenait une.
TOLERANCE_DIVISEUR = 1e-3

# --- Normalisation par le bruit propre à chaque fréquence --------------------
# Chaque cible a un plancher de ρ DIFFÉRENT au repos : celles proches du pic alpha héritent
# d'un fond élevé (mesuré : AVANT 0.23 / GAUCHE 0.36 / DROITE 0.36 le 2026-07-20). Un seuil
# global est donc structurellement injuste. On mesure μ et σ du repos au lancement, puis on
# décide sur z = (ρ-μ)/σ, comparable entre cibles. Gain mesuré sur la session validée :
# AVANT 61→100%, GAUCHE 80→100% (cf. `calibrate.py`, section débiaisage).
# Le plancher étant re-mesuré à CHAQUE session, le réglage s'adapte à l'alpha du jour —
# c'est ce qui manquait quand « ça marchait la semaine dernière ».
SSVEP_BASELINE_S = 8.0   # durée de la mesure du plancher au repos (0 = désactiver la normalisation)
# Stabilisation JETÉE avant de mesurer le plancher, comme NEURO_WARMUP_S. L'Unicorn sort un offset
# DC énorme qui DÉRIVE pendant des dizaines de secondes après l'ouverture de session (mesuré le
# 2026-07-27 : 10⁵ µV en rampe) ; un plancher mesuré là-dedans hérite d'un σ très dispersé, et comme
# on décide sur z=(ρ-μ)/σ, un σ gonflé rend le seuil INATTEIGNABLE. Vu sur casque : σ=0,19 sur 15 et
# 8,57 Hz => il aurait fallu ρ≈0,94 pour déclencher, impossible en électrodes sèches — ces cibles ne
# pouvaient pas être détectées, quoi que l'utilisateur fixe. `app.py` échappait au piège sans le
# savoir : son écran `signal_check` s'intercale et laisse le casque se stabiliser.
SSVEP_WARMUP_S = 15.0
# Rejet d'artefact. Mesuré le 2026-07-20 sur un run guidé : σ médian 8,5 mais **max 429** (50×),
# et 12 % des fenêtres au-dessus de 3× la médiane — mouvements/clignements au changement de
# fixation. Une fenêtre pareille ne contient pas d'EEG : décoder dessus produit des ρ aléatoires.
# On la rejette et on vote None (un artefact doit tendre vers l'ARRÊT, pas maintenir la commande).
# Le σ de référence est celui mesuré pendant la baseline de repos, donc adapté au montage du jour.
ARTIFACT_SIGMA_RATIO = 4.0
Z_MIN = 2.5              # écarts-types au-dessus du bruit pour accepter une détection
Z_MARGIN = 0.0           # marge sur l'échelle z (la normalisation rend la marge quasi inutile)

# --- Correction du sens (le PC maîtrise le signe envoyé — cf. docs/robot_testbed.md) ---
# Observé le 2026-07-17 : avant/arrière inversés sur ce robot -> on inverse jy à la source.
# Vérifier gauche/droite au prochain essai ; si inversé aussi, passer JOY_INVERT_X à True.
JOY_INVERT_X = False
JOY_INVERT_Y = True


def apply_invert(jx, jy):
    """Applique la correction de sens juste avant l'envoi UDP."""
    return (-jx if JOY_INVERT_X else jx, -jy if JOY_INVERT_Y else jy)


# --- Motor Imagery (2e mode : contrôle « par la pensée », main gauche/droite) -
# CSP+LDA entraîné (voir mi_decoder.py). Voies : les 8 EEG (le CSP fait le tri spatial).
MI_WINDOW_S = 2.0        # fenêtre de décodage MI (s) — training ET online (doivent coïncider)
MI_PROB_MIN = 0.60       # proba mini pour retenir une classe active (sinon None = indécis/repos)
# "csp" (CSP+LDA) ou "riemann" (covariances + tangent space). Les deux sont installés ; sur les
# données réelles de la session 1 ils étaient à égalité (~48% par essai) -> défaut CSP. Re-trancher
# après chaque calibration avec `python src/research/mi_compare.py`.
MI_METHOD = "csp"
# Re-référencement spatial appliqué AVANT le CSP : "none" | "car" (Common Average Reference =
# soustraire à chaque instant la moyenne des 8 voies). Retire le MODE COMMUN (dérive lente,
# EMG, dérive de la référence mastoïde) qui, en online, décale les log-variances du CSP et
# BLOQUE le décodeur sur une classe au repos (symptôme « GAUCHE en permanence »). Validé hors
# ligne le 2026-07-22 (scratchpad mi_reref.py, mi_calib_last.npz, décision par essai) : 3-classes
# CSP 47,6 -> 59,5 % (p<0,001), GAUCHE-vs-DROITE 57 -> 61 % (Riemann+CAR jusqu'à 64 %, p=0,09 —
# mieux mais pas encore significatif : la latéralisation demande une calibration plus longue).
# Sur ce montage 8 voies, CAR ≡ laplacien (les deux annulent le mode commun, le CSP est invariant
# au reste) -> on garde le CAR, plus simple. Doit être IDENTIQUE en calibration et en online.
MI_REREF = "car"
MI_VOTE_LEN = 5          # vote glissant online (MI plus bruité que SSVEP -> un peu plus de lissage)
MI_MIN_VOTES = 3         # votes concordants requis pour retenir une classe active
MI_MODEL_PATH = _os.path.join(DATA_DIR, "mi_model.joblib")   # modèle entraîné (calibration)
# Voies CLÉS du MI (indices dans CH_NAMES) : cortex moteur C3/Cz/C4. Le CSP utilise les 8 voies,
# mais ce sont ces trois-là (sous les cheveux, les plus dures à mouiller) qu'il faut vérifier en
# priorité — encadrées au contrôle de liaison avant un run/calibration MI.
MI_KEY_CHANNELS = [1, 2, 3]


# --- Calibration Motor Imagery : le protocole, tel qu'il a été validé au casque ---------------
# CUE = mise en route NON enregistrée après le top (le temps d'établir l'imagerie), puis on garde
# les IMAGERY secondes suivantes. 2026-07-22 : le CUE est passé de 2 à 3 s — il faut « environ
# 2 s » pour bien lancer le poing, et 2 s ne laissaient aucune marge (le début de l'enregistrement
# attrapait la fin de la montée). IMAGERY reste à 4 s : allonger n'aiderait pas, le facteur
# limitant MESURÉ est la FATIGUE, pas la durée par essai (le 3 classes tombe de 57 % à 33 % en
# deuxième moitié de séance).
MI_CUE_S = 3.0             # mise en route, jetée
MI_IMAGERY_S = 4.0         # la partie ENREGISTRÉE d'un essai
MI_REST_S = 1.5            # pause entre deux essais
MI_WARMUP_PER_CLASS = 2    # essais d'échauffement NON enregistrés (le MI s'améliore en séance)
MI_TRAIN_STEP_S = 1.0      # pas du découpage en fenêtres -> 3 fenêtres par essai de 4 s
# Durées de séance proposées, en essais PAR CLASSE. Le temps estimé se calcule, il ne se stocke
# pas : il dépend de CUE + IMAGERY + REST, qui sont juste au-dessus.
MI_SESSIONS = (10, 14, 18, 26)


# --- Calibrations menées par une FENÊTRE de stimulus (P300, ErrP, c-VEP) ----------------------
# Le Motor Imagery est ENDOGÈNE : le moteur mène sa calibration lui-même (les trois durées
# ci-dessus). Les trois autres exigent un stimulus verrouillé à la frame, donc une fenêtre de
# `src/stimulus/`, et le moteur y est PASSIF : il n'affiche rien, ne tire aucune consigne, ne
# décompte aucun essai. Il ne voit la fenêtre QUE par les marqueurs qu'elle publie.
#
# Ces deux délais sont donc sa SEULE façon de distinguer « la séance se déroule » de « il ne se
# passe plus rien ». Sans eux, une fenêtre qui ne se lance pas ou qui plante en plein milieu
# laisserait la calibration en attente pour toujours, en affichant « séance en cours ».

# Délai laissé à une fenêtre pour S'ANNONCER (`calib_start`) après le lancement de la calibration.
# 30 s parce qu'une fenêtre pygame en PLEIN ÉCRAN met plusieurs secondes à s'initialiser (bascule
# de mode vidéo, création du contexte, chargement des polices) et que la console la lance en même
# temps qu'elle demande la calibration au moteur : le délai court donc à partir d'un instant où
# la fenêtre n'existe pas encore. Passé ce délai, le diagnostic est binaire et il n'y en a pas
# d'autre : ou la fenêtre ne s'est pas lancée, ou elle publie ses marqueurs sous un autre nom que
# celui que le moteur écoute (cf. MARKER_STREAM_DEFAULT).
CALIB_FENETRE_ATTENTE_S = 30.0

# Silence au-delà duquel la fenêtre est réputée MORTE, une fois la séance commencée.
# 15 s parce que le plus long silence NORMAL des trois protocoles est la pause entre deux manches
# P300 — `PAUSE_ENTRE_MANCHES_S = 2,5 s` dans `src/stimulus/p300.py` — soit six fois la marge. Ce
# qu'on cherche ici n'est pas un ralentissement mais un processus DISPARU : un seuil serré tuerait
# des séances parfaitement saines (et une séance de calibration ne se refait pas gratuitement,
# c'est plusieurs minutes de fixation), là où un seuil large ne coûte que 15 s d'attente dans le
# seul cas où la fenêtre est déjà morte.
CALIB_FENETRE_SILENCE_S = 15.0

# Préfixe du dossier TEMPORAIRE où une calibration écrit avant que son résultat ne soit retenu.
# Posé ici par le chantier « la console, seul point d'entrée » (tâche 3) et consommé par la tâche
# 5 : la constante vit dans `core/config.py` plutôt que dans le module qui s'en sert, pour la même
# raison que tout le reste de ce fichier — deux endroits qui nomment la même chose finissent par
# diverger, et ici le second endroit serait celui qui NETTOIE.
# Un préfixe EXPLICITE plutôt que le défaut de `tempfile` : un dossier oublié se reconnaît alors
# d'un coup d'œil et se retrouve par son nom, au lieu de se confondre avec les temporaires du
# système. ⚠️ Écrire d'abord ailleurs que dans `data/` n'est pas une précaution de style : `data/`
# est un dépôt PUBLIC d'enregistrements EEG d'une personne identifiable, et son fichier le plus
# récent est celui que le moteur ÉLIT par défaut — un modèle à moitié écrit y serait donc proposé.
CALIB_TMP_PREFIX = "calib_candidat_"


# --- c-VEP (3e mode : code-VEP, codes pseudo-aléatoires) ---------------------
# Toutes les cibles affichent LE MÊME code (m-séquence), décalé circulairement. Le décodage
# compare la réponse EEG au template appris, décalé de chaque lag -> la cible fixée gagne.
# Avantage sur le SSVEP : autocorrélation piquée => cibles très séparables, potentiellement
# plus rapide et sans concurrence avec le pic alpha. Coût : une calibration (~1 min).
CVEP_BITS = 6                 # registre LFSR -> longueur du code = 2^6-1 = 63 frames
CVEP_TAPS = (6, 5)            # polynôme primitif x^6+x^5+1 (séquence de longueur maximale)
CVEP_CHANNELS = [4, 5, 6, 7]  # Pz, PO7, Oz, PO8 — le filtre spatial fait le tri
CVEP_BAND = (2.0, 45.0)       # la réponse c-VEP est LARGE bande (≠ SSVEP) : ne pas la rogner
# 10 cycles/cible s'est révélé TROP PEU : à 3 cycles moyennés il ne restait que 9 décisions
# pour estimer l'accuracy, d'où des écarts de 20 points entre séances purement dus au bruit
# d'échantillonnage (cf. cvep_analyze.py, intervalles de Wilson).
# 2026-07-21 : ramené de 21 à 15. Le bake-off d'efficacité en données (bench hors ligne vs
# pyntbci, courbes accuracy-vs-cycles sur 3 séances saines) montre un PLATEAU dès ~12 cycles/
# cible à k=2 : 6c/8c/4c gagnent ~0 point entre 12 et 15 cycles, et le passage 15->21 est dans
# le bruit. 15 garde une marge au-dessus du genou (~12) tout en raccourcissant la calibration
# d'~28 % (moins de fatigue = séance plus propre, cf. la variance de séance ×9). 15/3 = 5
# cycles par bloc entrelacé (CVEP_CAL_BLOCKS), entier — pas de reste à gérer.
CVEP_CAL_CYCLES = 15          # cycles enregistrés PAR cible
# Blocs entrelacés : chaque cible est enregistrée en CVEP_CAL_BLOCKS blocs, dans un ordre
# MÉLANGÉ. Sans ça, chaque cible occupe sa propre tranche de temps — et comme l'accuracy monte
# fortement en cours de séance (mesuré : 34% / 28% / 66% sur les trois tiers du 2026-07-20),
# les dernières cibles paraissaient bien meilleures. C'était un artefact de protocole.
CVEP_CAL_BLOCKS = 3
# Cycles moyennés par décision. Mesuré à 6 cibles sur 150 cycles (2026-07-20, cvep_analyze.py) :
#   1 cycle 42.7% -> 15.4 bits/min | 2 : 48.6% -> 11.2 | 3 : 56.2% -> 11.1 | 4 : 66.7% -> 12.8
# L'accuracy monte avec k, mais l'ITR PLAFONNE À k=1 : quadrupler la latence pour gagner 24
# points d'accuracy est une perte nette d'information. Contre-intuitif, d'où le réglage à 1.
# (Pour piloter un robot, où une erreur coûte cher, k=2 reste un choix défendable.)
# Re-mesuré avec le protocole ENTRELACÉ (126 cycles) : 1 cyc 46.8% -> 20.2 bits/min |
# 2 cyc 68.3% -> 27.1 | 3 cyc 71.4% -> 20.2 | 4 cyc 73.3% -> 16.1. L'optimum se déplace à k=2.
CVEP_DECISION_CYCLES = 2
# Seuils issus des décisions réelles : ρ moyen 0.327 (correct) vs 0.212 (faux) — ρ discrimine.
CVEP_CORR_MIN = 0.26          # corrélation mini du gagnant
CVEP_MARGIN = 0.09            # écart mini 1er - 2e
CVEP_VOTE_LEN = 3             # vote glissant (décodage ~5 Hz)
CVEP_MIN_VOTES = 2
CVEP_MODEL_PATH = _os.path.join(DATA_DIR, "cvep_model.npz")

# Au-delà de CVEP_PEREMPTION_CYCLES cycles sans nouveau marqueur de cycle, la référence de phase
# (le dernier `{"mode":"cvep","event":"cycle"}` reçu) est PÉRIMÉE : le moteur cesse de décoder
# plutôt que de dériver en silence. Continuer en « roue libre » (extrapoler indéfiniment depuis le
# dernier marqueur) est l'approche que la spec écarte : à 59,94 Hz réels affichés contre 60 Hz
# supposés — un écran ordinaire, pas un cas extrême — l'erreur atteint déjà 3,6 frames au bout
# d'une minute, sur un code qui n'en fait que 63. 3 cycles = 3,15 s à 60 Hz : assez pour absorber
# une frame sautée ou un marqueur en retard, trop court pour laisser la dérive d'horloge dépasser
# une fraction de frame.
CVEP_PEREMPTION_CYCLES = 3

# --- c-VEP, 2e décodeur : rCCA (reconvolution) sur LE MÊME stimulus ----------
# Le c-VEP utilise UNE m-séquence décalée circulairement (un lag par cible). Longtemps ce dépôt a
# écrit que « la reconvolution n'apporte rien » — c'était mesuré de « rCCA + CODES GOLD DISTINCTS »,
# les deux moitiés de l'hypothèse n'ayant jamais été testées séparément. Or `RCCAModel` prend ses
# codes en PARAMÈTRE. Rebranché sur le stimulus décalé (2026-08-20, mêmes époques que l'eCCA,
# data/cvep_calib_last.npz) : eCCA 43/90 = 47,8 %, rCCA 43/90 = 47,8 %, hasard 16,7 %. Les deux
# décodeurs sont indiscernables ; les codes Gold, eux, restent réfutés et hors du produit.
CVEP_RCCA_MODEL_PATH = _os.path.join(DATA_DIR, "cvep_rcca_model.npz")
CVEP_RCCA_EVENT = "refe"      # évènements du modèle rCCA : "refe" = fronts montants+descendants
CVEP_RCCA_ENC = 0.30          # durée (s) de la réponse transitoire apprise (~1 réponse VEP)

# Seuils de rejet du rCCA — MESURÉS, et voici exactement comment, parce qu'un seuil sans
# provenance est un seuil que personne n'osera changer. La commande est versionnée, elle affiche
# les DEUX couples candidats avec leur point de fonctionnement, et elle ne modifie rien :
#
#   python src/core/cvep_rcca.py --seuils data/cvep_calib_last.npz
#
#   fichier data/cvep_calib_last.npz — séance du 2026-07-21, UNE personne, 6 cibles, 90 cycles
#   (15 par cible, parfaitement équilibré), stimulus décalé, voies [4,5,6,7] = Pz/PO7/Oz/PO8.
#   Leave-one-out : 43/90 = 47,8 % (hasard 16,7 % ; p = 0,0005 par permutation, 2000 tirages).
#   Tous les chiffres ci-dessous sortent des scores HORS-PLI de cette validation croisée — un
#   modèle qui note un essai ne l'a jamais vu — plus 300 fenêtres de bruit blanc de même σ que
#   les époques filtrées, la convention de « regard nulle part » de `cvep_decoder._demo`.
#
# ⚠️ **UNE personne, UNE séance, 43 essais corrects sur 90.** Ce sont les seuls chiffres qui
# existent ; ce n'est pas une vérité générale, et ça vaut jusqu'à ce qu'une seconde personne soit
# mesurée — exactement la même réserve que pour l'eCCA au-dessus.
#
# ⚠️ **MESURÉS À LA GÉOMÉTRIE DE DÉCISION DU MOTEUR** (k = CVEP_DECISION_CYCLES = 2 cycles
# moyennés par décision), et pas à celle d'une époque de calibration (k = 1). Ce n'est pas un
# détail : la géométrie déplace tout. Aux mêmes seuils 0,26/0,09, le rCCA passe de 71 % de justesse
# à k=1 à 64 % à k=2, et le bruit passé de 10 % à 7 %. Des seuils mesurés à k=1 décriraient un
# décodeur qui n'existe pas — celui du moteur décide sur deux cycles.
# À k=2 il reste **37 décisions** sur les 90 cycles (24 correctes) : les groupes à cheval sur un
# changement de cible sont écartés, pas rognés (cf. `cvep_decoder.groupes_de_cycles`).
#
# POINT DE FONCTIONNEMENT DES VALEURS LIVRÉES (0,24 / 0,08) à k=2, mesuré :
#     69 % de justesse quand le décodeur émet   (9 décisions justes sur 13 émises)
#     35 % de taux d'émission                   (13 décisions sur 37)
#     10 % des fenêtres de bruit pur passent    (38 % des décisions correctes sont gardées)
#
# ⚠️ **LE 69 % EST OPTIMISTE PAR CONSTRUCTION, et c'est la réserve qui manquait ici.** Il se lit
# contre 64,9 % sans aucun seuil (24/37) — soit 4 points adossés à **13 décisions**, quand la
# comparaison entre les deux couples de seuils, déclarée non interprétable dix lignes plus bas,
# en a 37. Les deux échantillons ne sont même pas indépendants : les 13 émissions SONT un
# sous-ensemble des 37. Et les seuils ont été choisis SUR ces 37 décisions, donc sur les mêmes
# scores qui mesurent leur point de fonctionnement : c'est la même famille de réserve que le
# `measured_on` de l'ErrP (« threshold chosen on these same out-of-fold scores, optimistic »,
# cf. `lsl_io.DecodedErrPPublisher`). Aucun de ces deux chiffres ne dit que le seuil décode mieux.
# Ce qui justifie ces seuils est le TAUX DE BRUIT, estimé lui sur 300 fenêtres — pas la justesse.
#
# ⚠️ **Pourquoi 0,24/0,08 et pas 0,26/0,09** (les seuils de l'eCCA, retenus au tour précédent quand
# la mesure était faite à k=1) : à k=2, les deux tiennent le bruit au même ordre (10 % contre 7 %),
# mais 0,24/0,08 émet sur 35 % des décisions au lieu de 30 % — plus de décisions utilisables pour
# le même budget de bruit. ⚠️ En revanche, l'écart de JUSTESSE entre les deux (69 % contre 64 %)
# porte sur **2 décisions sur 37** : il n'est pas interprétable, et personne ne doit s'en servir
# pour affirmer que l'un décode mieux que l'autre. Ce qui tranche ici est le taux de bruit, estimé
# lui sur 300 fenêtres.
#
# ⚠️ **POURQUOI CES VALEURS ET PAS LE QUANTILE À 5 %** — à lire avant de « corriger » ceci.
# Une première procédure visait « le quantile qui garde 95 % des essais corrects », et donnait
# 0,080 / 0,011. C'est un critère de SENSIBILITÉ (ne pas rater ce qui est bon), pas un critère de
# REJET, qui est le travail réel d'un seuil de décision ici — et mesuré, il rate son but : il fait
# émettre sur 89 % des essais avec 48 % de justesse (soit la justesse qu'on a SANS aucun seuil) et
# laisse passer 83 % du bruit pur, parce que le gagnant sur du bruit a une médiane de 0,163, donc
# AU-DESSUS de ce plancher. Un seuil qui ne change rien n'est pas un seuil.
# L'argument qui tranche entre trop strict et trop permissif : les deux échouent, mais un seuil
# trop STRICT produit une panne VISIBLE (« ça ne se déclenche jamais », repéré en trente secondes
# — c'est ce qu'a vécu le SSVEP), tandis qu'un seuil trop PERMISSIF produit une panne INVISIBLE :
# le mode émet avec assurance sur du bruit, les scores ont l'air normaux, personne ne s'en aperçoit.
# Ce projet existe en grande partie pour éliminer la seconde. On part donc STRICT, et la tâche 7
# rend ces deux seuils réglables à chaud pour desserrer en séance si le mode se révèle trop muet.
# `core.cvep_rcca.seuils_hors_pli` reste livrée et testée : elle chiffre la borne basse (le plus
# bas qu'on puisse descendre sans perdre de bons essais), et `--seuils` l'affiche à côté.
#
# ⚠️ Ce n'est PAS une différence d'ÉCHELLE avec l'eCCA : mesurées, les corrélations des deux
# décodeurs vivent au même endroit (gagnant médian, essais corrects, k=2 : 0,261 pour le rCCA,
# 0,323 pour l'eCCA), et les mêmes seuils y donnent des points de fonctionnement voisins. L'ancien
# commentaire de ces deux constantes — « scores rCCA sur une autre échelle » — était faux ; il est
# corrigé ici. Ce qui trancherait vraiment : enregistrer une fois, au casque, ce que valent ces
# scores quand la personne ne fixe RIEN. Ce fichier n'existe pas, et le bruit blanc n'en est
# qu'une approximation (un EEG de repos yeux ouverts porte de l'alpha, pas du bruit blanc).
#
# ⚠️ Les seuils eCCA au-dessus (CVEP_CORR_MIN/CVEP_MARGIN = 0,26/0,09) N'ONT PAS été retouchés :
# ils sont validés au casque, et ce chantier n'a pas mandat de les rejuger. `--seuils` imprime
# leur point de fonctionnement à côté (k=2 : 55 % gardés, 46 % d'émission, 71 % de justesse, 10 %
# de bruit) — c'est une donnée pour la séance qui viendra, pas une proposition de les changer.
# ⚠️ **CES DEUX CONSTANTES NE SONT PAS LUES PAR LE MOTEUR**, et il faut le dire ici parce que tout
# ce qui précède laisse croire l'inverse. `CVEPRuntime.decide` (`core/modes/cvep.py`) impose à
# CHAQUE décision le couple réglé du mode — `SPEC.params["corr_min"/"margin"]`, dont les défauts
# sont ceux de l'eCCA (`CVEP_CORR_MIN`/`CVEP_MARGIN`, 0,26/0,09) — et l'écrase donc sur le
# `RCCADecoder` quel que soit son défaut de construction. Ce n'est pas un oubli mais un choix :
# mesurés, les deux décodeurs vivent à la même échelle empirique (cf. le ⚠️ juste au-dessus), et
# un couple commun réglable à chaud vaut mieux que deux couples figés que l'étudiant ne peut pas
# tourner en séance. Où elles servent VRAIMENT, aujourd'hui :
#   • `python src/core/cvep_rcca.py --seuils <calib.npz>`, qui imprime leur point de fonctionnement
#     à côté de celui de l'eCCA — c'est LA commande de provenance de ces chiffres ;
#   • les constructions directes de `RCCADecoder(model, plan)` hors du mode (analyses hors ligne).
# Les changer ne change donc RIEN au décodage du moteur. Pour cela, c'est le réglage
# « Corrélation minimale » de la page c-VEP, ou `CVEP_CORR_MIN`/`CVEP_MARGIN` plus haut.
CVEP_RCCA_CORR_MIN = 0.24     # corrélation mini du gagnant  (69 % de justesse à l'émission, k=2)
CVEP_RCCA_MARGIN = 0.08       # écart mini 1er - 2e          (35 % d'émission, 10 % de bruit passé)


# Nombre de cibles c-VEP. C'EST le paramètre d'exploration : le SSVEP est plafonné par les
# diviseurs entiers du refresh (~4 fréquences utilisables hors alpha à 60 Hz), alors que le
# c-VEP dispose d'autant de lags que le code a de bits (63). Écart entre lags voisins à 60 Hz :
#   n=3 -> 350 ms | n=4 -> 262 ms | n=6 -> 175 ms | n=8 -> 131 ms
# Une réponse VEP dure ~150 ms : au-delà de 6 cibles les réponses voisines se recouvrent et
# deviennent confusables. 6 est le compromis retenu (cf. itr.py --scale pour l'enjeu en bits/min).
# 6 retenu. J'étais passé à 4 sur la foi de `itr.py --project`, qui prédisait un optimum PLAT
# entre 4 et 6 — c'était FAUX. L'analyse à séance constante (cvep_analyze.py §2b, qui rejoue les
# mêmes enregistrements en restreignant la décision à un sous-ensemble de lags) montre une ITR
# strictement CROISSANTE avec le nombre de cibles, sur les deux séances mesurées :
#   séance 6 cibles : 2->7.6  3->10.5  4->12.1  5->13.3  6->14.4 bits/min
#   séance 4 cibles : 2->4.7  3->6.5   4->7.1
# Le modèle de projection supposait les concurrents INDÉPENDANTS (acc = q^(N-1)) ; en réalité
# leurs bruits sont corrélés (même fenêtre EEG, même template), donc ajouter une cible coûte
# bien moins que prédit. Mesuré : 90% à 2 cibles -> l'indépendance prédirait 59% à 6, on observe
# 70%. => plus de cibles = plus d'information.
#
# 2026-07-20 : passage à 8 (lags 0/8/16/24/32/39/47/55, écart 131 ms). C'est SOUS la durée d'une
# réponse VEP (~150 ms), donc l'endroit où la confusion de voisinage devrait apparaître — sauf que
# la mesure à 6 cibles l'a RÉFUTÉE : les erreurs n'étaient pas concentrées sur les voisins (36 %
# des erreurs à distance 1 contre 40 % attendus si uniforme), c'est le SNR qui limite, pas la
# séparation des lags. On teste donc l'hypothèse là où elle prédit quelque chose de mesurable :
#   - si l'ITR continue de monter -> le plafond n'est pas la séparation temporelle ;
#   - si elle plafonne ET que §4 montre enfin des erreurs de voisinage -> on a trouvé la limite.
# Le NON-choix délibéré : garder le code à 63 frames (cycle 1,05 s) plutôt que passer à n_bits=7
# (L=127, écart 262 ms) — allonger le code doublerait la latence pour résoudre une confusion de
# voisinage dont on a la preuve qu'elle n'existe pas encore. À garder en réserve si §4 bascule.
#
# 15:45 — 1re calibration à 8 : 3,0 bits/min. INCONCLUANT, et il ne faut pas l'imputer aux 8
# cibles : sur les MÊMES données, §2b donne 2,4 bits/min à 6 cibles et 2,2 à 4, contre 27,1 et
# 7,1 mesurés précédemment. À configuration égale la séance était 3× pire — donc le facteur
# dominant n'est PAS le nombre de cibles. Non-régression du code vérifiée en rejouant la séance
# à 4 cibles : 4,7 / 7,1 / 4,0 / 5,6, identique au dixième près.
# ⚠️ CE QU'ON NE SAIT PAS : la CAUSE de l'effondrement. Aucun indicateur disponible ne la
# prédit. Le ratio alpha valait 18,93, le MEILLEUR jamais mesuré (il se mesure yeux fermés sur
# les occipitales : il dit que le cerveau va bien, pas que le montage tient). Et la dérive brute
# ne discrimine pas non plus — 196-716 sur la séance à 27,1 bits/min contre 71-792 ici, les
# plages se recouvrent. Ne pas réutiliser ces seuils comme critère : c'est de la lecture après
# coup. Candidats non départagés : contact d'électrodes, fatigue OCULAIRE (4,5 min de fixation
# continue, notre calibration la plus longue), ou difficulté réelle des 8 cibles.
# 15:59 — contrôle à 6 cibles APRÈS remplacement des électrodes : 18,0 bits/min. Le montage
# était bien en cause. Signature du montage neuf : amplitude filtrée ×14 (σ 138/36/124/65
# contre 9,9/7,7/7,2/6,6), SNR par cycle plus bas mais signal propre — l'accuracy à 4 cycles
# (76,7 %) DÉPASSE la séance de référence (73,3 %), seule la vitesse de montée a baissé, d'où
# l'optimum ITR qui glisse de k=2 à k=4. Compatible avec des électrodes fraîchement posées
# (gel qui n'a pas fini de diffuser) ; le §6 monte 66,7 -> 87,5 % au fil de la séance mais
# p≈0,6, ce n'est PAS significatif — hypothèse, pas fait établi.
# 16:25 — 8 CIBLES SUR SÉANCE SAINE : 38,1 % à k=1 -> 17,3 bits/min. C'est la mesure qui
# TRANCHE la question du plafond, ouverte depuis le début du c-VEP. §2b sur ces données :
#   2->11,2  3->15,0  4->16,5  5->17,2  6->17,5  7->17,6  8->17,3 bits/min
# PREMIER PLATEAU observé (les séances précédentes croissaient strictement jusqu'à 6) : au-delà
# de 5 cibles les valeurs sont indistinguables. Ajouter des cibles n'apporte plus rien.
# ⚠️ MAIS §4 réfute la cause qu'on soupçonnait : les 104 erreurs se répartissent 27/29/27/17 %
# par distance, contre 29/29/29/14 attendus si uniformes. À 131 ms d'écart — SOUS la durée
# d'une réponse VEP — il n'y a TOUJOURS aucune confusion de voisinage. C'est notre effectif le
# plus solide sur cette question (104 erreurs contre 39 et 7 auparavant), et il confirme la
# prédiction faite à 6 cibles. Le facteur limitant est le SNR, pas la séparation des lags.
# => CONSÉQUENCE DIRECTE : allonger le code (n_bits=7, L=127, écart 262 ms) ne servirait à
#    RIEN. Cette piste, gardée en réserve depuis le début, est MORTE — elle aurait doublé la
#    latence pour résoudre un problème qui n'existe pas. Ne pas la ressortir sans une mesure
#    §4 qui bascule d'abord.
# Retour à 6 : à ITR équivalente (17,5 contre 17,3, écart = bruit), 6 cibles donne 44,6 %
# d'accuracy contre 38,1 % — 6,5 points de moins d'erreurs pour piloter, et la couronne à 6
# couvre déjà marche arrière et arcs. Le choix se fait donc sur l'accuracy, pas sur l'ITR.
CVEP_N_TARGETS = 6

# Rotation de l'affectation lag <-> POSITION à l'écran. Servait à tester si une cible faible
# suivait sa POSITION ou son LAG. EXPÉRIENCE CLOSE (2026-07-20) : les deux prédictions ont été
# réfutées, et surtout le test du khi-deux montre que les écarts entre cibles n'ont JAMAIS été
# significatifs (p=0.53 sur la séance qui avait lancé l'hypothèse, p=0.39 sur celle de contrôle).
# Il n'y a pas de cible faible : c'est du bruit d'échantillonnage à 21 décisions par cible.
# Le paramètre reste disponible si une vraie asymétrie apparaît un jour (χ² < 0.05 dans
# cvep_analyze.py §3), mais ne PAS repartir en chasse sans ce test d'abord.
CVEP_LAG_ROTATION = 0

_COMPASS8 = ["AVANT", "AV-DROITE", "DROITE", "AR-DROITE",
             "ARRIERE", "AR-GAUCHE", "GAUCHE", "AV-GAUCHE"]
_DIR_ANGLE = {"up": 0.0, "right": _math.pi / 2, "down": _math.pi, "left": -_math.pi / 2}


def cvep_targets(n=None, speed=0.6):
    """`n` cibles réparties sur un cercle (angle 0 = haut = avant, sens horaire).

    L'angle donne DIRECTEMENT la consigne joystick, donc ajouter des cibles enrichit aussi le
    pilotage : à 6 cibles on gagne la marche arrière et les arcs (avancer en tournant), que les
    3 cibles SSVEP ne permettent pas.

    `n=3` reprend exactement COMMANDS, pour que la mesure à 3 cibles reste directement
    comparable aux sessions déjà enregistrées (sinon on changerait deux choses à la fois).
    """
    n = CVEP_N_TARGETS if n is None else int(n)
    if n == 3:
        return [{**c, "angle": _DIR_ANGLE[c["dir"]]} for c in COMMANDS]
    out = []
    for i in range(n):
        ang = 2 * _math.pi * i / n
        out.append({"name": _COMPASS8[round(ang / (2 * _math.pi) * 8) % 8], "angle": ang,
                    "jx": round(_math.sin(ang) * speed, 2),
                    "jy": round(_math.cos(ang) * speed, 2)})
    if len({t["name"] for t in out}) != n:   # n=5, 7... : la rose des vents ne suffit plus
        for i, t in enumerate(out):
            t["name"] = f"C{i + 1}"
    return out


def available_frequencies(refresh, fmin=None):
    """Toutes les fréquences affichables SANS jitter à ce refresh = diviseurs entiers
    `refresh/n`. Bornée en bas par le passe-bande (une fondamentale sous BANDPASS[0] serait
    filtrée). Retourne [(frames_per_cycle, freq_hz), ...] de la plus HAUTE à la plus basse.

    Sert au sélecteur manuel de l'appli SSVEP : on veut pouvoir tester TOUTES ces fréquences,
    y compris celles qui entrent en conflit d'harmoniques — le tri se fait à l'œil, pas ici.
    À 60 Hz : 30 · 20 · 15 · 12 · 10 · 8,571 · 7,5 · 6,667 · 6 · 5,455 · 5 Hz (n = 2..12).
    """
    fmin = BANDPASS[0] if fmin is None else fmin
    out = []
    n = 2                       # n=1 = refresh entier => pas de clignotement
    while refresh / n >= fmin:
        out.append((n, refresh / n))
        n += 1
    return out


def _plus_ecartees(candidats, n):
    """Les `n` fréquences dont le PLUS PETIT écart mutuel est le plus grand. `None` si impossible.

    Pourquoi ce critère : la séparabilité est la seule propriété qu'on puisse affirmer depuis la
    résolution fréquentielle (`1/WINDOW_S`), sans rien supposer de la physiologie. Deux cibles plus
    proches que cette résolution ne sont pas distinguables, quelle que soit la qualité du signal.

    Pourquoi pas en force brute : à 240 Hz et 8 cibles, énumérer les combinaisons en ferait 314
    MILLIONS. On procède donc par écart décroissant + placement glouton depuis la plus basse, ce
    qui est exact ici (c'est le schéma classique « maximiser la distance minimale ») et instantané.

    À égalité, le jeu aux fréquences les plus basses l'emporte : la fonction DESCEND les écarts
    candidats du plus grand au plus petit et renvoie le PREMIER jeu faisable qu'elle trouve, sans
    jamais comparer deux jeux entre eux — c'est l'implémentation de RÉFÉRENCE de l'autotest, en
    force brute, qui elle ne remplace qu'à écart STRICTEMENT meilleur (le test 3 vérifie que les
    deux s'accordent). Ce départage n'a rien de profond : il rend la fonction DÉTERMINISTE, sans
    quoi ni le test de non-régression ni le compte rendu d'un étudiant ne voudraient dire quoi que
    ce soit.
    """
    xs = sorted(candidats)
    if n < 1 or len(xs) < n:
        return None
    if n == 1:
        return [xs[0]]
    ecart_min = 1.0 / WINDOW_S

    def place(g):
        """Le jeu le plus bas espacé d'au moins `g`, ou None s'il n'y a pas la place."""
        out = [xs[0]]
        for f in xs[1:]:
            if f - out[-1] >= g:
                out.append(f)
                if len(out) == n:
                    return out
        return None

    for g in sorted({b - a for i, a in enumerate(xs) for b in xs[i + 1:]}, reverse=True):
        if g < ecart_min:
            break               # même le meilleur écart possible est sous la résolution
        jeu = place(g)
        if jeu is not None:
            return jeu
    return None


def propose_frequencies(refresh, n, alpha=ALPHA_DEFAUT_HZ):
    """`(fréquences, note)` : `n` cibles affichables à ce refresh ET décodables pour cet alpha.

    `note` est vide si tout va bien, porte un avertissement si l'on a dû sortir de la plage
    confortable, et porte la raison si c'est impossible — auquel cas la liste est VIDE. On ne rend
    jamais une liste plus courte que demandé : rendre 3 cibles à qui en demande 4 est un mensonge
    silencieux, exactement le genre de panne que ce chantier existe pour supprimer.

    L'alpha est un PARAMÈTRE, jamais une constante : le pic varie fortement d'une personne à
    l'autre, et le jeu accordé à quelqu'un pose une cible sur le pic de quelqu'un d'autre.
    """
    # ⚠️ `available_frequencies` ne borne QUE le bas (son `fmin`) : à 100 Hz elle rend 50 Hz, que
    # le passe-bande d'acquisition supprime AVANT le décodage. Le haut se borne donc ici.
    divisibles = [f for _k, f in available_frequencies(refresh)
                  if BANDPASS[0] <= f <= BANDPASS[1] and abs(f - alpha) >= ALPHA_GARDE_HZ]

    lo, hi = CONFORT_HZ
    jeu = _plus_ecartees([f for f in divisibles if lo <= f <= hi], n)
    if jeu is not None:
        return jeu, ""

    jeu = _plus_ecartees(divisibles, n)
    if jeu is not None:
        hors = [f for f in jeu if not lo <= f <= hi]
        return jeu, (f"hors de la plage confortable {lo:g}-{hi:g} Hz : "
                     + ", ".join(f"{f:g}" for f in hors)
                     + " — scintillement plus pénible, réponse plus bruitée")

    for k in range(n - 1, 1, -1):
        if _plus_ecartees(divisibles, k) is not None:
            return [], (f"impossible : {k} cibles au maximum à {refresh:g} Hz avec un alpha à "
                        f"{alpha:g} Hz — il faut un écran plus rapide")
    return [], f"impossible : aucun jeu de {n} cibles à {refresh:g} Hz"


def cvep_lags(n_targets, code_len):
    """Lags équirépartis sur la période du code (max de séparation entre cibles)."""
    return [round(i * code_len / n_targets) for i in range(n_targets)]


def cvep_lag_gap_ms(n_targets, code_len, refresh=60.0):
    """Écart temporel entre deux lags voisins. Sous ~150 ms (durée d'une réponse VEP), les
    cibles voisines deviennent difficilement séparables."""
    return code_len / n_targets / refresh * 1000.0


def choose_frequencies(refresh, commands=COMMANDS):
    """Associe à chaque commande une fréquence réellement affichable à ce refresh.

    Une fréquence n'est stable (sans jitter) que si c'est un diviseur entier du refresh.
    Retourne les commandes enrichies de `frames_per_cycle` (période ON+OFF) et `actual_hz`.
    Périodes garanties distinctes (sinon deux cibles clignoteraient à l'identique).
    """
    used = set()
    out = []
    for cmd in commands:
        n = max(2, round(refresh / cmd["desired_hz"]))
        while n in used:
            n += 1
        used.add(n)
        out.append({**cmd, "frames_per_cycle": n, "actual_hz": refresh / n})
    return out


# --- P300 (4e mode : oddball P300, SÉLECTION DISCRÈTE par attention) ----------
# Onde positive ~300 ms après un stimulus RARE et ATTENDU. On fait clignoter les cibles une à
# une ; l'utilisateur FIXE + COMPTE celle qu'il veut : son flash devient l'"oddball" -> P300 ->
# on l'identifie. Maximal sur la LIGNE MÉDIANE Fz/Cz/Pz (indices 0,2,4 de CH_NAMES) — les trois
# voies qu'on a, et les plus faciles à mouiller (hors cheveux) : montage FAVORABLE au P300,
# contrairement au MI (C3/C4 sous les cheveux) ou au SSVEP (occipital seul).
# Décodage xDAWN (filtres spatiaux P300) + covariances riemanniennes + LR (pyriemann, installé).
# GÉOMÉTRIE : on REPREND la couronne c-VEP (cvep_targets) -> cibles IDENTIQUES au c-VEP à 6
# cibles, donc comparaison d'ITR directe entre les deux paradigmes (seul le décodage change).
# Pas de cible STOP dédiée : entre deux sélections le robot est à l'arrêt (modèle en RAFALES),
# et une marge de confiance (P300_SELECT_MARGIN) peut refuser une sélection ambiguë.
P300_N_TARGETS = 6            # aligné sur CVEP_N_TARGETS pour la comparaison à cibles égales
P300_BAND = (1.0, 12.0)       # bande ERP : le P300 est LENT (1-8 Hz) — à NE PAS confondre avec
#                               la bande SSVEP (5-40) qui couperait justement le P300.
P300_PRE_S = 0.15             # pré-stimulus conservé pour la correction de ligne de base (s)
P300_EPOCH_S = 0.80           # fenêtre post-onset analysée (s) — couvre le P300 (~300 ms) + retour
# SOA (temps entre deux onsets) = ON+OFF. Ramené 250 -> 150 ms le 2026-07-22 (12 s/sélection =
# trop long). Littérature : SOA classique 175-250 ms, mais les spellers rapides descendent à 125 ms
# sans perte de précision et l'ITR ~double en accélérant (Xue 2021, IOP 10.1088/1741-2552/ac2f04) ;
# un ISI un peu plus long favorise la précision par flash (Sellers, PMC3595069) -> on met le gap
# (OFF) > flash (ON). 60 Hz : 4 frames ON (67 ms) + 5 OFF (83 ms) = 9 frames = 150 ms.
# ⚠️ le SOA change le RECOUVREMENT des flashs dans l'époque de 0,8 s -> RECALIBRER après ce changement.
P300_FLASH_ON_FR = 4          # frames cible ALLUMÉE (~67 ms à 60 Hz)
P300_FLASH_OFF_FR = 5         # frames éteint entre deux flashs -> SOA = 9 frames = 150 ms à 60 Hz
# flashs PAR cible et par sélection (moyennage : + sûr / - rapide). Courbe accuracy-vs-répétitions
# (p300_analyze.py, run live 100 %, 2026-07-22) : genou vers 7-8 rép (~95 %) -> 8 retenu.
# Temps/sélection = REPS × 6 cibles × SOA = 8 × 6 × 0,15 s ≈ **7,2 s** (contre 12 s avant le SOA 150).
# ⚠️ la courbe a été mesurée à SOA 250 ms ; le SOA est maintenant 150 ms (recouvrement des flashs
# changé) -> RE-MESURER la courbe après la prochaine calibration, et réduire REPS si possible.
# Repasser à 12 pour du zéro-erreur robot. Prochain gros gain = ARRÊT DYNAMIQUE (~2-4 rép, ~3 s).
P300_REPS = 8                 # sert aussi de PLAFOND de répétitions en arrêt dynamique
# --- Arrêt dynamique (EXPÉRIMENTAL, cochable en live) : on accumule les scores répétition par
# répétition et on s'arrête dès que la cible de tête se détache assez, au lieu de faire les 8 rép.
# Littérature : Riemann+xDAWN + accumulation -> ~2-4 rép en moyenne (cf. eeg-p300). ⚠️ le SEUIL de
# marge dépend de la calibration : à RÉGLER sur données (l'arrêt dynamique s'était révélé FAUX pour
# le c-VEP — la marge n'y prédisait pas la justesse ; on vérifie avant de faire confiance).
P300_MIN_REPS = 2             # jamais moins de N rép avant de pouvoir stopper (bruit sinon)
P300_STOP_MARGIN = 0.6        # marge (log-odds moyens) 1er-2e requise pour stopper — À TUNER
P300_CAL_ROUNDS = 12          # manches de calibration (chaque cible cuée 2× à 6 cibles)
# La PAUSE entre deux manches — l'écran où rien ne clignote, où l'on choisit (en décodage) ou lit
# (en calibration) la cible à fixer. Ce n'est pas du confort : sans elle, la frontière entre deux
# manches est visuellement identique à un intervalle entre deux flashs (~150 ms), et les époques de
# la manche suivante contiennent la transition du regard. Valeur calée sur les deux écrans validés
# au casque (2,2 s dans `research/app.py`, 2,5 s dans `research/p300_calibrate.py`).
# ⚠️ Elle vit ICI, dans `core/`, parce que DEUX programmes en ont besoin et qu'aucun des deux ne
# peut importer l'autre : la fenêtre `src/stimulus/p300.py` la JOUE, et `core/modes/p300_calib.py`
# en a besoin pour ESTIMER la durée d'une séance — le moteur ne voit pas l'écran. Recopiée des deux
# côtés, elle dériverait, et la console annoncerait une durée que la fenêtre ne tient pas.
P300_PAUSE_MANCHE_S = 2.5
P300_SELECT_MARGIN = 0.0      # marge de score mini 1er-2e pour émettre (0 = toujours l'argmax)
P300_BURST_S = 1.2            # durée d'exécution d'une commande sélectionnée puis STOP (s)
P300_XDAWN_NFILTER = 4        # composantes xDAWN par classe
P300_MODEL_PATH = _os.path.join(DATA_DIR, "p300_model.joblib")
P300_MIDLINE = [0, 2, 4]      # Fz, Cz, Pz — indices des voies où le P300 est maximal (info/diagnostic)

# --- Marqueurs ENTRANTS (§12.1 : le moteur écoute une application externe) ------------------
MARKER_STREAM_DEFAULT = "EEG_API_Unicorn_stim"   # nom du flux de marqueurs qu'on écoute par défaut
MARKER_LATE_S = 1.0       # DÉSACCORD toléré entre l'horloge de l'émetteur et celle du moteur,
                          # dans les DEUX sens — c'est une seule constante pour deux emplois, et
                          # les confondre a déjà trompé une relecture :
                          #   • vers le PASSÉ (le retard) : elle dimensionne le tampon du moteur
                          #     AVEC l'époque du mode (`EngineServer.__init__`), pour qu'un
                          #     marqueur arrivé en retard trouve encore son EEG. Au-delà il est
                          #     compté comme perdu (`marqueurs_perdus`), jamais ignoré.
                          #   • vers le FUTUR : `markers_murs` compte à part (`marqueurs_futurs`)
                          #     tout marqueur horodaté plus de MARKER_LATE_S APRÈS le dernier
                          #     échantillon acquis. C'est la signature du `time_correction()`
                          #     oublié entre deux machines — le projet a mesuré 45 jours d'écart.
                          # La symétrie est volontaire : une horloge qui dérive ne choisit pas
                          # son sens, et deux constantes finiraient par diverger.
# Délai au-delà duquel une manche P300 sans nouveau flash est ABANDONNÉE plutôt que gardée en
# attente indéfiniment — le cas normal d'un plantage de l'application de stimulus en pleine
# manche (jamais de `round_end`). Largement au-dessus d'une manche normale à SOA 150 ms (8 rép ×
# 6 cibles ≈ 7,2 s) : ne se déclenche pas sur un ralentissement, seulement sur un abandon réel.
P300_ROUND_TIMEOUT_S = 10.0


def p300_targets(n=None):
    """Cibles P300 = la MÊME couronne que le c-VEP (cvep_targets), pour comparer les deux
    paradigmes à cibles identiques. name/angle/jx/jy fournis ; l'angle donne la consigne joystick."""
    return cvep_targets(P300_N_TARGETS if n is None else n)


# --- Mode 5 : Neuro-monitoring passif (workload / vigilance / attention) -------
# BCI PASSIF : AUCUNE commande n'est envoyée au robot. On mesure des puissances de bande
# θ/α/β et on en dérive 3 indices affichés en HISTOGRAMME temps réel (voir neuro_monitor.py +
# app.mode_neuro). Faisable en 8 voies — le monitoring passif se fait couramment sur casques
# grand-public à 1-4 voies (Muse, Emotiv) ; vérifié dans la littérature le 2026-07-22.
# ⚠️ Les 3 indices reposent tous sur les MÊMES puissances de bande (un seul calcul PSD) : ils
# sont donc CORRÉLÉS et surtout ils DÉRIVENT (individuels, sensibles au montage/à l'heure). Ce
# ne sont PAS des mesures absolues -> on les NORMALISE en z contre un repos mesuré en début de
# mode, on les LISSE (EMA) et on REJETTE les fenêtres à σ aberrant (le clignement/l'EMG polluent
# le θ frontal en premier). À lire comme « au-dessus / en-dessous de mon repos », jamais en brut.
# (cf. rigueur-statistique-eeg en mémoire : ne pas conclure sur du bruit.)
NEURO_WINDOW_S = 2.0          # fenêtre PSD glissante (s) — assez longue pour une résolution ~1 Hz
NEURO_UPDATE_HZ = 5.0         # cadence de recalcul des indices
NEURO_BASELINE_S = 25.0       # repos yeux ouverts en début de mode : cale les échelles (z du jour)
NEURO_WARMUP_S = 15.0         # stabilisation JETÉE avant le repos (transitoire des électrodes sèches)
NEURO_SMOOTH = 0.85           # lissage EMA des z (0 = brut, ->1 = très lisse) : ces indices sont bruités
# --- v2 (2026-07-23, après revue littérature multi-agent — cf. eeg-modes-a-venir) ---
# Bandes : β BORNÉ À 25 Hz (au lieu de 30) car l'EMG culmine à 20-30 Hz au frontal (Goncharova 2003)
# et gonflait l'engagement sur électrodes sèches ; bande "emg" 30-45 Hz = PROXY EMG pour le veto
# (hors 50 Hz secteur). θ 4-8 = standard workload (Chikhi 2022), α 8-13 convention Pope.
NEURO_BANDS = {"theta": (4.0, 8.0), "alpha": (8.0, 13.0), "beta": (13.0, 25.0), "emg": (30.0, 45.0)}
NEURO_FRONTAL = [0, 2]        # Fz + Cz — θ frontal-médian MOYENNÉ (Fz seul = trop sensible au clignement)
NEURO_PARIETAL = [4, 5, 6, 7] # Pz, PO7, Oz, PO8 — α pariéto-occipital (dénominateur charge + somnolence)
NEURO_ENGAGEMENT_CH = [2, 4, 5, 6, 7]  # Cz, Pz, PO7, Oz, PO8 — sites POSTÉRO-CENTRAUX de Pope (EXCLUT Fz)
# Rejet d'artefact PAR VOIE (v2) : σ (signal détendu) d'UNE voie > ratio × son σ repos -> fenêtre
# ignorée. Par voie (pas la moyenne) : attrape un clignement LOCALISÉ sur Fz que la moyenne noyait.
NEURO_ARTIFACT_RATIO = 4.0
NEURO_EMG_RATIO = 3.0         # veto EMG SPECTRAL : puissance bande 30-45 Hz > ratio × repos -> fenêtre ignorée
NEURO_HIGHPASS_HZ = 0.5       # passe-haut léger avant la PSD (dérive électrode SÈCHE) ; 0 = aucun
# Re-calage LENT du zéro de repos contre la dérive multi-minutes (settling d'impédance sèche,
# non-stationnarité de séance) : constante de temps en s (EMA très lente de la médiane, sur fenêtres
# propres). 0 = baseline FIGÉ. ~180 s suit la dérive sans effacer les états mentaux (plus rapides).
NEURO_REBASELINE_S = 180.0
# Voies CLÉS du mode (encadrées au contrôle de liaison) : Fz porte le θ frontal, Pz l'α pariétal.
NEURO_KEY_CHANNELS = [0, 4]   # Fz, Pz
# Échelle de l'histogramme : le z (normalisé en LOG, cf. neuro_monitor.IndexNormalizer) passe par
# une COMPRESSION tanh(z / NEURO_Z_SPAN) au lieu d'un écrêtage sec -> pas de « plafond » brutal,
# la barre garde de la gradation au-delà de ce z (z=SPAN -> ~76 % de barre, 2×SPAN -> ~96 %).
# Monter NEURO_Z_SPAN = barres MOINS sensibles (montent moins vite) ; descendre = plus sensibles.
NEURO_Z_SPAN = 3.0


# --- Mode 6 : ErrP (potentiel d'erreur — auto-correction d'une commande) -------
# On DÉTECTE l'INTERACTION-ErrP : l'utilisateur perçoit que la MACHINE s'est trompée -> onde
# fronto-centrale médiane (FCz/Cz, source ACC), +200/-250/+320/-450 ms après le FEEDBACK. On ANNULE
# alors la dernière commande (veto). Revue littérature 2026-07-23 (cf. eeg-modes-a-venir) : RÉUTILISER
# la pile P300 (xDAWN+Riemann+LR, = famille gagnante Kaggle NER 2015) avec 4 changements seulement.
# ⚠️ Décodage MONO-ESSAI (une action = une époque, PAS de moyennage comme le P300) -> AUC réaliste
# ~0,65-0,78 en sec ; onset = FEEDBACK À L'ÉCRAN horodaté (JAMAIS le mouvement robot, jitter UDP/ROS2).
ERRP_BAND = (1.0, 10.0)       # ErrP = onde LENTE ; couper >10 Hz réduit le bruit (Yasemin 2023)
ERRP_PRE_S = 0.2              # pré-feedback pour la ligne de base (-200..0 ms)
ERRP_EPOCH_S = 0.7           # post-feedback (composantes jusqu'à ~450-530 ms ; +bruit au-delà)
ERRP_XDAWN_NFILTER = 2        # défaut/repli SEULEMENT — sur ~55 époques erreur, nfilter=4 = rang
# plein (covariances 16x16, 136 features tangent-space) -> surapprentissage probable (revue littérature
# 2026-07-23). ErrPModel.fit() BALAYE ERRP_XDAWN_NFILTER_CANDIDATES et tranche par AUC out-of-fold ;
# cette constante ne sert que si le balayage échoue (trop peu de données pour un CV honnête).
ERRP_XDAWN_NFILTER_CANDIDATES = (2, 3, 4)
ERRP_PERM_N = 100             # permutations pour le test de significativité de l'AUC (piège « conclure
# sur du bruit » à ~55 époques erreur, cf. rigueur-statistique-eeg) ; monter à ~500-1000 hors ligne
# pour une p-value plus fine, 100 suffit pour un premier avis rapide en calibration.
ERRP_ERROR_RATE = 0.28       # erreurs DÉLIBÉRÉES en calibration (~25-30 %, Chavarriaga/Yasemin)
ERRP_DEMO_ERROR_RATE = 0.35  # démonstrateur (mode solo) : erreurs fréquentes (~1/3) MAIS le point
# progresse encore vers la cible (drift net +0,3/pas) ; à 0,5 c'est une marche aléatoire qui n'arrive
# jamais. Le taux ne change pas la détection par pas (seuil sur le score), juste le rythme vécu.
# --- Tâche d'élicitation = CURSEUR-VERS-CIBLE (Ferrez & Millán 2008, Chavarriaga 2010) : l'ErrP naît
# d'une attente violée QUI TE CONCERNE. Une étiquette imposée isolée (« prépare : GAUCHE ») est un
# élicitateur FAIBLE (pas de but, pas d'enjeu) ; un point qui doit REJOINDRE une cible et part parfois
# à l'envers = erreur RESSENTIE. Cible à une extrémité (tirage 50/50) -> erreurs équilibrées gauche/
# droite -> le SENS du mouvement est décorrélé de l'étiquette (xDAWN apprend l'ErrP, pas la direction).
ERRP_TRACK_CELLS = 7         # nombre de cases de la piste (départ au centre, cible à une extrémité)
ERRP_MAX_RUN_STEPS = 14      # garde-fou : si le point n'a pas atteint la cible en 14 pas, on recommence
ERRP_CAL_TRIALS = 200        # événements de feedback en calibration -> ~55 époques erreur (plancher ~50)
ERRP_CAL_BLOCKS = 5          # blocs courts (fatigue front-loadée) = groupes GroupKFold
ERRP_TNR_TARGET = 0.85       # seuil ASYMÉTRIQUE : viser TNR>=85 % (annuler une BONNE commande coûte cher)
ERRP_REFRACTORY_S = 1.5      # après un veto : pas de 2e détection avant ce délai (anti-rebond)
ERRP_FEEDBACK_S = 1.0        # affichage du feedback écran = fenêtre de décision (~800 ms-1 s)
ERRP_ARTIFACT_RATIO = 4.0    # rejet d'une époque si σ (par voie) > ratio × repos (clignement sur l'erreur)
ERRP_MODEL_PATH = _os.path.join(DATA_DIR, "errp_model.joblib")
ERRP_MIDLINE = [0, 2, 4]     # Fz, Cz, Pz — voies clés (surlignage contrôle liaison ; xDAWN utilise les 8)


def _selftest():
    """La proposition de fréquences, et le GARDE de `data/` (`empreinte_dossier`)."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # 0. `empreinte_dossier` est le seul garde-fou automatique contre une écriture dans le VRAI
    # `data/` — la contrainte la plus dure du dépôt (enregistrements EEG d'une personne
    # identifiable sur un dépôt public, et deux modèles réellement écrasés en août 2026). Cinq
    # programmes l'appellent (les quatre `archive/*.py` et `research/app.py`) et tous font la même
    # chose : comparer l'empreinte avant et après. **Personne ne vérifiait qu'il DÉTECTE quoi que
    # ce soit** — `return {}` en tête de la fonction laissait les cinq appelants verts, et sa
    # docstring de trente lignes le rendait plus crédible qu'il ne l'était.
    #
    # ⚠️ UNE ASSERTION PAR COMPOSANTE, sinon chaque mutation survit séparément : avec le seul
    # « ça change quand j'ajoute un fichier », retirer `getmtime` du couple resterait vert et un
    # fichier RÉÉCRIT à taille égale ne serait plus vu — exactement le geste qui a coûté les deux
    # modèles. Le diff est calculé comme chez l'appelant réel (`research/app.py::_smoke`) :
    # symétrique sur les noms, puis les valeurs des noms communs.
    import shutil as _shutil
    import tempfile as _tempfile

    def _bouges(avant, apres):
        return sorted(set(avant) ^ set(apres)) + \
            sorted(n for n in set(avant) & set(apres) if avant[n] != apres[n])

    d = _tempfile.mkdtemp(prefix="empreinte_")
    try:
        chk(empreinte_dossier(_os.path.join(d, "absent")) == {},
            "un dossier ABSENT rend {} sans lever — un dépôt fraîchement cloné n'a pas de data/")
        vide = empreinte_dossier(d)
        chk(_bouges(vide, empreinte_dossier(d)) == [],
            f"un dossier INCHANGÉ ne bouge pas : c'est le cas normal, et le rendre faux ferait "
            f"rougir tous les smokes du dépôt ({_bouges(vide, empreinte_dossier(d))})")

        f = _os.path.join(d, "x.npz")
        with open(f, "wb") as fh:
            fh.write(b"aa")
        cree = empreinte_dossier(d)
        chk(_bouges(vide, cree) == ["x.npz"],
            f"un fichier AJOUTÉ est vu, et NOMMÉ — c'est l'accident mesuré : un modèle de test "
            f"oublié dans data/ s'y fait ÉLIRE comme le plus récent chargeable ({_bouges(vide, cree)})")

        with open(f, "wb") as fh:
            fh.write(b"aaaa")
        grossi = empreinte_dossier(d)
        chk(_bouges(cree, grossi) == ["x.npz"],
            f"un fichier GROSSI aussi : la TAILLE est dans le couple ({_bouges(cree, grossi)})")

        # Le cas SOURNOIS, et celui qui a réellement coûté deux modèles : un fichier ÉCRASÉ par un
        # autre de même taille. Sans `getmtime` dans le couple, il passe sans un mot.
        with open(f, "wb") as fh:
            fh.write(b"bbbb")
        _os.utime(f, (1_600_000_000, 1_600_000_000))
        chk(_bouges(grossi, empreinte_dossier(d)) == ["x.npz"],
            f"un fichier RÉÉCRIT À TAILLE ÉGALE aussi : le MTIME est dans le couple — c'est LA "
            f"forme de l'accident d'août 2026 ({_bouges(grossi, empreinte_dossier(d))})")

        # ...et TOUS les fichiers sont surveillés, pas seulement le premier trié.
        with open(_os.path.join(d, "y.npz"), "wb") as fh:
            fh.write(b"b")
        avec_deux = empreinte_dossier(d)
        chk(len(avec_deux) == 2 and set(avec_deux) == {"x.npz", "y.npz"},
            f"le dossier est listé EN ENTIER ({sorted(avec_deux)})")

        _os.remove(f)
        chk(_bouges(avec_deux, empreinte_dossier(d)) == ["x.npz"],
            f"un fichier SUPPRIMÉ est vu aussi : un test qui efface un modèle réel doit rougir "
            f"autant qu'un test qui en ajoute un ({_bouges(avec_deux, empreinte_dossier(d))})")
    finally:
        _shutil.rmtree(d, ignore_errors=True)

    # 1. LE test de non-régression : la règle doit régénérer le trio validé sur casque réel.
    # Les deux constantes viennent d'ailleurs (mesures pour la garde, pratique pour la plage) ;
    # que le trio en tombe est le seul argument dont on dispose qu'elle n'est pas arbitraire.
    trio, note = propose_frequencies(60.0, 3, 10.5)
    attendu = sorted([15.0, 20.0, 60.0 / 7])
    chk([round(f, 6) for f in sorted(trio)] == [round(f, 6) for f in attendu],
        f"60 Hz, alpha 10,5, n=3 régénère le trio validé casque ({[f'{f:.3f}' for f in trio]})")
    chk(note == "", f"et sans avertissement ({note!r})")

    # 2. Les invariants, sur une grille dense : 7 refresh (60-240 Hz), 6 pics alpha, 7 nombres
    # de cibles. Pas sur UN seul cas où elle tient par accident — ce projet en a déjà subi deux fois.
    # (Grille dense, pas "tout le domaine" — mais suffisant pour attraper les régressions.)
    mauvais = []
    for refresh in (60.0, 75.0, 100.0, 120.0, 144.0, 165.0, 240.0):
        for alpha in (7.5, 8.5, 9.6, 10.5, 11.5, 13.0):
            for n in range(2, 9):
                jeu, note = propose_frequencies(refresh, n, alpha)
                if not jeu:
                    if not note.startswith("impossible"):
                        mauvais.append(("vide sans raison", refresh, alpha, n))
                    continue
                if len(jeu) != n:
                    mauvais.append(("mauvais compte", refresh, alpha, n, len(jeu)))
                for f in jeu:
                    k = refresh / f
                    if abs(k - round(k)) > 1e-9:
                        mauvais.append(("pas un diviseur", refresh, n, f))
                    if not BANDPASS[0] <= f <= BANDPASS[1]:
                        mauvais.append(("hors bande passante", refresh, n, f))
                    if abs(f - alpha) < ALPHA_GARDE_HZ:
                        mauvais.append(("sur le pic alpha", refresh, alpha, n, f))
                trie = sorted(jeu)
                if any(b - a < 1.0 / WINDOW_S - 1e-9 for a, b in zip(trie, trie[1:])):
                    mauvais.append(("cibles non séparables", refresh, alpha, n))
    chk(not mauvais, f"7 refresh x 6 alpha x 7 nombres de cibles : {len(mauvais)} violation(s)")
    for m in mauvais[:5]:
        print(f"       {m}")

    # 3. L'accélération ne doit pas changer le RÉSULTAT : là où la force brute est calculable,
    # elle doit tomber d'accord. Sans ça, « c'est plus rapide » ne vaudrait rien.
    def brute(pool, n):
        best = None
        for jeu in _itertools.combinations(sorted(pool), n):
            ec = [b - a for a, b in zip(jeu, jeu[1:])]
            if min(ec) < 1.0 / WINDOW_S:
                continue
            if best is None or min(ec) > best[0]:
                best = (min(ec), list(jeu))
        return None if best is None else best[1]

    desaccords = 0
    for refresh in (60.0, 75.0, 120.0, 144.0):
        for alpha in (8.5, 9.6, 10.5, 12.0):
            pool = [f for _k, f in available_frequencies(refresh)
                    if BANDPASS[0] <= f <= BANDPASS[1] and abs(f - alpha) >= ALPHA_GARDE_HZ]
            if len(pool) > 20:
                continue                      # au-delà, la force brute n'est plus calculable
            for n in (2, 3, 4, 5):
                if _plus_ecartees(pool, n) != brute(pool, n):
                    desaccords += 1
    chk(desaccords == 0, f"l'algorithme rapide donne le même résultat que la force brute "
                         f"({desaccords} désaccord(s))")

    # 4. Un écran rapide et beaucoup de cibles : la force brute ferait 314 millions de
    # combinaisons. Ce test échoue en TIMEOUT si quelqu'un la réintroduit un jour.
    debut = _time.perf_counter()
    jeu, _note = propose_frequencies(240.0, 8, 9.6)
    duree = _time.perf_counter() - debut
    chk(len(jeu) == 8 and duree < 0.5,
        f"240 Hz et 8 cibles en {duree * 1000:.1f} ms ({len(jeu)} cibles)")

    # 5. L'élargissement et l'impossibilité DISENT ce qui se passe.
    _jeu, note = propose_frequencies(60.0, 5, 10.5)
    chk("hors de la plage confortable" in note,
        f"sortir de la plage confortable est annoncé ({note[:60]}…)")
    jeu, note = propose_frequencies(60.0, 12, 10.5)
    chk(jeu == [] and note.startswith("impossible") and "maximum" in note,
        f"un nombre impossible est refusé, avec le maximum atteignable ({note})")

    # 6. Cas limites : refresh trop bas, n=0, n=1. Ces branches ne sont jamais exercées
    # par les grilles du test 2 ; elles méritent une couverture explicite.

    # Refresh trop bas : à 10 Hz, seul 5 Hz est dans la bande, donc n>=2 est impossible.
    jeu, note = propose_frequencies(10.0, 2, 9.6)
    chk(jeu == [] and note.startswith("impossible") and "aucun jeu" in note,
        f"refresh trop bas (10 Hz, n=2) : liste vide avec raison "
        f"({note[:50]}…)")

    # n=0 : demander 0 cibles est un cas dégénéré. Retour cohérent : liste vide, raison "impossible".
    jeu, note = propose_frequencies(60.0, 0, 9.6)
    chk(jeu == [] and note.startswith("impossible"),
        f"n=0 : liste vide signalée impossible ({note[:50]}…)")

    # n=1 : demander 1 cible doit toujours réussir si au moins 1 fréquence est disponible.
    # À 60 Hz avec alpha 9.6, il y a plusieurs candidats -> devrait retourner le premier.
    jeu, note = propose_frequencies(60.0, 1, 9.6)
    chk(len(jeu) == 1 and note == "",
        f"n=1 : une seule fréquence retournée ({jeu[0] if jeu else 'ÉCHOUÉ'})")

    print(f"[config] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
