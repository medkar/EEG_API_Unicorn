"""Ce que la console sait lancer. Le SEUL endroit du dépôt qui nomme un module de fenêtre.

Deux règles se rencontrent ici, et ce fichier existe pour les satisfaire toutes les deux :

- **`core` ne nomme aucune fenêtre.** Le contrat d'un mode porte une CLÉ (`Calib.stimulus_id`,
  par exemple `"p300"`), jamais un chemin. C'est ce qui garde l'arête `core -> stimulus`
  inexistante — le moteur doit tourner sur une machine sans écran.
- **La console ne tient aucun catalogue recopié.** Elle ne sait pas que le P300 se lance avec
  `p300.py` : elle demande, à ce module, la commande correspondant à la clé que le contrat lui a
  donnée. Un fichier renommé se corrige ICI, à un seul endroit.

Autotest :
    python src/stimulus/registry.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from core.config import use_utf8_console  # noqa: E402

_ICI = _os.path.dirname(_os.path.abspath(__file__))

# clé du contrat -> fichier de ce paquet. Les clés sont celles de `Calib.stimulus_id` et de
# `MesureSpec.stimulus_id` : une MESURE peut avoir besoin d'une fenêtre elle aussi (le taux SSVEP
# n'a rien à décoder sans cibles qui clignotent).
FENETRES = {
    "p300": "p300.py",
    "errp": "errp.py",
    "cvep": "cvep.py",
    "ssvep": "ssvep.py",
    # Le MI : AUCUN stimulus — le paradigme est endogène. Sa fenêtre ne sert qu'à
    # l'essai libre : elle encadre la tâche que publie `decoded_mi`.
    "mi": "mi.py",
}


# Les OPTIONS que la console ajoute pour une mesure donnée. Déclaré ici, avec les fenêtres : le
# `--guide` du SSVEP est le nom d'un argument de `stimulus/ssvep.py`, donc il appartient au module
# qui connaît les fenêtres. La console demande, elle ne sait pas.
#
# ⚠️ Ce n'est PAS `--calibrer` : une mesure n'entraîne rien. La fenêtre guidée joue le même
# clignotement que le décodage, avec des consignes en plus — c'est la même distinction qu'entre
# `--calibrer` et le décodage pour les trois autres fenêtres, sous un autre mot parce que le
# résultat est un verdict et pas un modèle.
MESURE_OPTIONS = {
    # `--retour` : la fenêtre entoure la cible que le moteur DÉCIDE pour chaque essai,
    # lue sur le flux décodé public du mode (le moteur y publie les décisions du test) — vert si
    # juste, rouge sinon. Pas pour l'ErrP : il n'y a pas de cible à entourer, la décision est
    # « erreur ou non » sur un feedback que la fenêtre a elle-même choisi.
    "ssvep": ("--guide", "--retour"),
    # `--tester` : le protocole de `--calibrer` (qui désigne la cible et publie la vérité-terrain),
    # mais une fenêtre qui dit « TEST » et « le moteur note » au lieu de « CALIBRATION » et « le
    # moteur entraîne ». Le bandeau de la console affiche ces lignes à la fermeture de la fenêtre :
    # un étudiant qui vient de cliquer « Tester » ne doit pas y lire qu'il entraîne un modèle.
    "p300": ("--tester", "--retour"),   # le TEST du P300 : une cible cerclée par manche, `cue`
    "cvep": ("--tester", "--retour"),   # le TEST du c-VEP : une cible par bloc, garde son HORLOGE
    "errp": ("--tester",),      # le TEST de l'ErrP : erreurs délibérées, `feedback` étiqueté
    # Une entrée n'existe que si une mesure la réclame : l'autotest refuse une option de mesure
    # qu'aucune mesure n'utilise (configuration morte).
}


def options_de_mesure(stimulus_id):
    """Les arguments à ajouter pour lancer la fenêtre AU SERVICE d'une mesure. () par défaut."""
    return tuple(MESURE_OPTIONS.get(stimulus_id, ()))


# Les arguments de l'ESSAI LIBRE (« Tester librement ») : le mode tourne, la fenêtre
# affiche ses cibles SANS rien désigner, et entoure ce que le moteur décode. Ce que chaque fenêtre
# exige pour ça, et pas un mot de plus :
#   • c-VEP : `--libre` — sans option elle DÉSIGNE des cibles (le protocole de dépouillement de la
#     recette 2.9), et un essai libre ne doit rien désigner ;
#   • SSVEP et P300 : rien — sans option, elles n'affichent déjà que leurs cibles (« choisis ta
#     cible » pour le P300). Un `--libre` sans effet chez elles serait une option-décor.
# L'ErrP n'y figure pas : sa fenêtre choisit elle-même ses erreurs, il n'y a pas de cible libre.
LIBRE = {
    "cvep": ("--libre", "--retour"),
    "ssvep": ("--retour",),
    "p300": ("--retour",),
    "mi": ("--retour",),     # sans lui, la fenêtre du MI n'a rien à montrer et le dit
}


def option_libre(stimulus_id):
    """Les arguments qui lancent la fenêtre en ESSAI LIBRE. `()` si elle ne sait pas — la console
    n'offre alors pas le bouton (elle le DEMANDE, elle ne le sait pas)."""
    return tuple(LIBRE.get(stimulus_id, ()))


# Quelles fenêtres savent tenir un JOURNAL DE SÉANCE, et sous quel argument. Déclaré ICI, comme
# les fenêtres elles-mêmes : la console demande « celle-ci sait-elle ? » au lieu de savoir, sinon
# elle tiendrait un second catalogue qui divergerait au premier ajout.
#
# ⚠️ Seul le c-VEP en a un aujourd'hui, et ce n'est pas un oubli : c'est le seul mode dont la
# recette dise qu'une séance sans journal NE SE DÉPOUILLE PAS (test 2.9). Le P300 et l'ErrP
# publient une vérité-terrain que le moteur reçoit déjà par marqueurs.
JOURNAL = {"cvep": "--log"}


def sait_journaliser(stimulus_id):
    """Cette fenêtre sait-elle écrire un journal de séance ? La console le DEMANDE, elle ne le
    sait pas : une case à cocher sur une fenêtre qui ignore l'option serait un réglage-décor."""
    return stimulus_id in JOURNAL


# 🔴 Quelles fenêtres acceptent qu'on leur DICTE les fréquences du mode, et sous quel argument.
#
# ⚠️ Sans ça, la fenêtre SSVEP afficherait le jeu de fréquences du DÉPÔT quel que soit le réglage
# de la console : un étudiant qui pose 12 · 15 · 20 verrait 15 · 20 · 8,571, et le moteur
# corrélerait contre des sinusoïdes que personne n'affiche. Rien ne lève, le mode ne détecte
# simplement plus rien — la panne caractéristique de ce produit.
#
# Seul le SSVEP y figure, et ce n'est pas un oubli : les trois autres fenêtres n'affichent pas des
# FRÉQUENCES. Le P300 et l'ErrP montrent des événements, le c-VEP un code pseudo-aléatoire dont la
# séparation est une PHASE, pas une période.
FREQUENCES = {"ssvep": "--freqs"}


# L'argument qui fixe la LONGUEUR d'une séance guidée, par fenêtre — et donc la durée d'un test.
# ⚠️ Chaque fenêtre compte dans SA propre unité, et le `Param` de la mesure qui la sert doit être
# exprimé dans la même : des essais PAR CIBLE pour le SSVEP, des MANCHES pour le P300, des ESSAIS
# pour l'ErrP, des CYCLES enregistrés PAR CIBLE pour le c-VEP (répartis en trois blocs, donc pas
# « par bloc »). Une valeur passée dans la mauvaise unité ne lève rien : la séance est juste
# beaucoup trop courte, ou trop longue, par rapport à ce que l'écran annonce.
#
# Pourquoi ça existe : l'ErrP s'entraîne en 200 essais, 5,7 minutes. Un bouton « Tester » qu'on
# refait à chaque réglage ne peut pas coûter ça — la boucle régler → tester → ajuster doit être
# RAPIDE.
COMPTES = {"ssvep": "--trials", "p300": "--rounds", "errp": "--essais", "cvep": "--cycles"}


def option_compte(stimulus_id, n):
    """Les arguments qui fixent la longueur d'une séance guidée. () si la fenêtre n'en a pas, ou si
    `n` n'est pas un entier positif — la fenêtre garde alors sa longueur par défaut plutôt que de
    planter au démarrage sur une valeur absurde."""
    argument = COMPTES.get(stimulus_id)
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ()
    if not argument or n <= 0:
        return ()
    return (argument, str(n))


def option_frequences(stimulus_id, freqs):
    """Les arguments qui DICTENT ses fréquences à une fenêtre. () si elle n'en accepte pas.

    Rend `()` aussi quand `freqs` est vide : une option sans valeur ferait planter la fenêtre au
    démarrage, et un stimulus qui ne s'ouvre pas au milieu d'une séance coûte la séance.
    """
    argument = FREQUENCES.get(stimulus_id)
    if not argument or not freqs:
        return ()
    return (argument, ",".join(f"{float(f):g}" for f in freqs))


# Les fenêtres qui font passer l'écran principal au rafraîchissement voulu (`--ecran-hz`), et
# d'où vient ce rafraîchissement hors entraînement : le RÉGLAGE du mode pour le SSVEP, le MODÈLE
# choisi pour le c-VEP, qui ne marche qu'au rafraîchissement de son entraînement. À
# l'entraînement, il vient des réglages d'« Entraîner ». La console demande, elle ne sait pas.
ECRAN = {"ssvep": "reglage", "cvep": "modele"}


def option_ecran(stimulus_id, hz):
    """Les arguments qui font passer l'écran à `hz` Hz. `()` si la fenêtre ne sait pas, ou si `hz`
    n'est pas un nombre positif : la fenêtre mesure alors l'écran, comme avant."""
    if stimulus_id not in ECRAN:
        return ()
    try:
        hz = float(hz)
    except (TypeError, ValueError):
        return ()
    if hz <= 0:
        return ()
    return ("--ecran-hz", f"{hz:g}")


# Les fenêtres dont les CIBLES (leur nombre et leurs noms) sont un réglage d'entraînement porté
# par le modèle : la console leur passe les noms (`--noms`), ceux d'« Entraîner » ou du modèle.
CIBLES = {"cvep", "p300", "ssvep"}


def option_cibles(stimulus_id, noms):
    """Les arguments qui font afficher ces cibles, sous ces noms. `()` si la fenêtre ne sait pas,
    ou sans noms lisibles : la fenêtre garde alors ses cibles par défaut."""
    if stimulus_id not in CIBLES or isinstance(noms, (str, bytes)) or not noms:
        return ()
    try:
        noms = [str(n).strip() for n in noms]
    except TypeError:
        return ()
    return ("--noms", ",".join(noms)) if all(noms) else ()


# Les fenêtres qui savent tenir des CIBLES PHYSIQUES — des LED pilotées par un microcontrôleur —,
# le réglage du mode qui le dit, et l'argument qui le leur dit. Une telle fenêtre ne dessine alors
# aucune cible, et n'a aucun rafraîchissement à tenir : rien ne clignote à l'écran. La valeur est
# `contract.CIBLES_PHYSIQUES`, RECOPIÉE pour garder ce module léger (le contrat traîne pylsl) ;
# l'autotest vérifie l'accord.
PHYSIQUES = {"ssvep": ("cibles", "physiques", "--physiques")}


def option_physiques(stimulus_id, reglages):
    """`("--physiques",)` si les réglages du mode disent des cibles physiques et que la fenêtre
    sait les tenir, sinon `()`."""
    cle, valeur, argument = PHYSIQUES.get(stimulus_id, (None, None, None))
    if argument is None or (reglages or {}).get(cle) != valeur:
        return ()
    return (argument,)


def commande(stimulus_id, calibrer=False, options=()):
    """La ligne de commande complète d'une fenêtre. Lève `KeyError` si la clé est inconnue.

    `-u` n'est pas décoratif : la sortie de la fenêtre doit arriver NON TAMPONNÉE à la console,
    sinon le message d'erreur d'un processus qui vient de mourir reste bloqué dans son tampon —
    c'est-à-dire exactement quand on en a besoin.
    """
    if stimulus_id not in FENETRES:
        raise KeyError(
            f"aucune fenêtre pour « {stimulus_id} » (connues : {', '.join(sorted(FENETRES))})")
    argv = [_sys.executable, "-u", _os.path.join(_ICI, FENETRES[stimulus_id])]
    if calibrer:
        argv.append("--calibrer")
    # `options` s'AJOUTE à `--calibrer`, elle ne le remplace pas : une calibration c-VEP a besoin
    # des deux à la fois (le mode calibration ET son journal de vérité-terrain). Les éléments sont
    # des arguments DÉJÀ FORMÉS (`["--log", chemin]`) — ce module ne connaît pas les options de
    # chaque fenêtre, et n'a pas à les connaître : il assemble une ligne de commande.
    argv.extend(str(o) for o in options)
    return argv


def _selftest():
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # Chaque argument que CE registre ajoute à une fenêtre doit exister dans SON analyseur : sinon
    # argparse la tue au démarrage (« unrecognized arguments »), et un « Tester » qui ne s'ouvre pas
    # au milieu d'une séance coûte la séance. On lit la source de la fenêtre plutôt que de l'importer
    # (elle importe pygame).
    def _declare(cle, argument):
        with open(_os.path.join(_ICI, FENETRES[cle]), encoding="utf-8") as f:
            return f'add_argument("{argument}"' in f.read()

    inconnus = [(k, a) for table in (COMPTES, FREQUENCES) for k, a in table.items()
                if not _declare(k, a)]
    inconnus += [(k, a) for k, args in MESURE_OPTIONS.items() for a in args if not _declare(k, a)]
    inconnus += [(k, a) for k, args in LIBRE.items() for a in args if not _declare(k, a)]
    inconnus += [(k, "--ecran-hz") for k in ECRAN if not _declare(k, "--ecran-hz")]
    inconnus += [(k, "--noms") for k in CIBLES if not _declare(k, "--noms")]
    inconnus += [(k, a) for k, (_cle, _valeur, a) in PHYSIQUES.items() if not _declare(k, a)]
    chk(not inconnus,
        f"chaque argument ajouté par la console EXISTE dans la fenêtre visée "
        f"({inconnus or 'aucun inconnu'}) — sinon elle meurt au démarrage sur « unrecognized "
        f"arguments »")
    chk(option_compte("errp", 40) == ("--essais", "40") and option_compte("p300", "6") == ("--rounds", "6"),
        f"la longueur d'un test part dans l'unité de SA fenêtre ({option_compte('errp', 40)}, "
        f"{option_compte('p300', '6')})")
    chk(option_compte("errp", None) == () and option_compte("errp", 0) == ()
        and option_compte("inconnue", 5) == (),
        "…et une longueur absente, nulle, ou une fenêtre sans option de longueur n'ajoute RIEN : "
        "la fenêtre garde sa longueur par défaut plutôt que de planter")

    manquants = [k for k, f in FENETRES.items() if not _os.path.isfile(_os.path.join(_ICI, f))]
    chk(not manquants,
        f"chaque clé déclarée pointe un fichier qui EXISTE ({manquants or 'aucun manquant'}) — "
        f"sinon le bouton « Calibrer » lancerait un processus qui meurt aussitôt, et le clic "
        f"redeviendrait silencieux")

    argv = commande("p300")
    chk(argv[0] == _sys.executable and argv[1] == "-u" and argv[2].endswith("p300.py"),
        f"la commande passe par l'interpréteur COURANT et -u ({argv[1:]})")
    chk("--calibrer" not in argv, "…sans --calibrer par défaut : le décodage est le cas normal")
    chk(commande("p300", calibrer=True)[-1] == "--calibrer",
        "…et avec, quand on le demande")

    # Les options s'AJOUTENT à `--calibrer` : une calibration c-VEP a besoin des deux à la fois.
    avec = commande("cvep", calibrer=True, options=[JOURNAL["cvep"]])
    chk("--calibrer" in avec and avec[-1] == "--log",
        f"une option s'ajoute à --calibrer au lieu de le remplacer ({avec[-2:]})")
    chk(sait_journaliser("cvep") and not sait_journaliser("p300"),
        "le registre dit QUI sait journaliser — la console le demande au lieu de le savoir, "
        "sinon une case à cocher apparaîtrait sur une fenêtre qui ignore l'option")
    chk(_os.path.isabs(argv[2]),
        "le chemin est ABSOLU : la console ne partage pas forcément le dossier courant de la "
        "fenêtre qu'elle lance")

    try:
        commande("inconnu")
        chk(False, "une clé inconnue doit lever")
    except KeyError as e:
        chk("connues" in str(e), f"…en disant lesquelles sont connues ({e})")

    # --- La correspondance avec le CONTRAT, dans les deux sens ---------------------
    # ⚠️ Ce contrôle est ici et pas dans `core/modes/registry.py::check()` : `core` ne connaît que
    # des CLÉS, jamais des fenêtres, et la frontière AST de `server.py --smoke` refuse l'import.
    # C'est ce module qui détient la correspondance, c'est donc lui qui la vérifie.
    # `stimulus -> core` est autorisé.
    from core.modes import registry as modes

    attendues = {s.calibration.stimulus_id for s in modes.MODES
                 if s.calibration is not None and s.calibration.kind == "fenetre"}
    # Les MESURES demandent des fenêtres elles aussi, par le même champ et pour la même raison :
    # `core` ne nomme aucun fichier, il ne connaît que des clés.
    attendues |= {s.stimulus_id for s in modes.MESURES if s.stimulus_id}
    # …et les fenêtres de DÉCODAGE des modes (`ModeSpec.stimulus_id`) : celle du MI n'est ni
    # une calibration ni une mesure, et passerait sinon pour orpheline.
    attendues |= {s.stimulus_id for s in modes.MODES if s.stimulus_id}
    orphelines = sorted(attendues - set(FENETRES))
    chk(not orphelines,
        f"chaque `stimulus_id` déclaré par un mode OU une mesure a sa fenêtre "
        f"({orphelines or 'aucun orphelin'}) — sinon le bouton qui la lance ouvre un processus qui "
        f"meurt aussitôt, et le clic redevient SILENCIEUX, le défaut que ce chantier répare")
    inutilisees = sorted(set(FENETRES) - attendues)
    chk(not inutilisees,
        f"…et réciproquement, aucune fenêtre déclarée ici n'est orpheline "
        f"({inutilisees or 'aucune'}) : une entrée que plus personne ne demande est une entrée "
        f"que personne ne corrigera")

    # Les options de mesure désignent des fenêtres qui existent, et seulement des mesures qui en
    # demandent une. Une entrée pour une clé inconnue serait un `--guide` jamais passé à personne.
    mesures_avec_fenetre = {s.stimulus_id for s in modes.MESURES if s.stimulus_id}
    chk(set(MESURE_OPTIONS) <= mesures_avec_fenetre,
        f"les options de mesure ne visent que des fenêtres RÉCLAMÉES par une mesure "
        f"({sorted(set(MESURE_OPTIONS) - mesures_avec_fenetre) or 'aucune orpheline'})")
    argv_guide = commande("ssvep", options=options_de_mesure("ssvep"))
    chk("--guide" in argv_guide and argv_guide[2].endswith("ssvep.py"),
        f"…et la commande du run guidé porte bien son option ({argv_guide[3:]})")

    # --- Le RETOUR et l'ESSAI LIBRE ---------------------------------------
    # Un test des trois fenêtres à cible entoure la décision du moteur ; l'ErrP n'a pas de cible.
    chk(all("--retour" in options_de_mesure(k) for k in ("cvep", "ssvep", "p300"))
        and "--retour" not in options_de_mesure("errp"),
        f"les tests c-VEP, SSVEP et P300 lancent leur fenêtre AVEC le retour, pas l'ErrP "
        f"({ {k: options_de_mesure(k) for k in sorted(MESURE_OPTIONS)} })")
    chk(option_libre("cvep") == ("--libre", "--retour") and option_libre("ssvep") == ("--retour",)
        and option_libre("p300") == ("--retour",) and option_libre("mi") == ("--retour",)
        and option_libre("errp") == () and option_libre("inconnue") == (),
        f"l'essai libre : `--libre` là où la fenêtre désigne sinon des cibles (c-VEP), `--retour` "
        f"partout, et RIEN pour une fenêtre qui ne sait pas — la console n'offre alors pas le "
        f"bouton ({ {k: option_libre(k) for k in sorted(FENETRES)} })")
    # Un essai libre DÉCODE : il lui faut un mode qui affiche CETTE fenêtre et publie un flux
    # décodé à entourer. Lu dans le contrat, dans le sens fenêtre -> mode.
    sans_flux = sorted(k for k in LIBRE
                       if not any(s.stimulus_id == k and s.stream for s in modes.MODES))
    chk(set(LIBRE) <= set(FENETRES) and not sans_flux,
        f"chaque fenêtre d'essai libre est celle d'un MODE qui publie un flux décodé "
        f"({sans_flux or 'aucune orpheline'}) — sinon l'anneau n'aurait rien à lire")
    chk(not any("--libre" in a for a in MESURE_OPTIONS.values()),
        "…et `--libre` n'est JAMAIS passé à un test : il retire la vérité-terrain que le test note")

    # --- L'ÉCRAN DU STIMULUS ----------------------------------------------
    chk(option_ecran("cvep", 60.0) == ("--ecran-hz", "60")
        and option_ecran("ssvep", "59.94") == ("--ecran-hz", "59.94"),
        f"le rafraîchissement part sous `--ecran-hz`, écrit sans zéro inutile "
        f"({option_ecran('cvep', 60.0)}, {option_ecran('ssvep', '59.94')})")
    chk(option_ecran("cvep", None) == () and option_ecran("cvep", 0) == ()
        and option_ecran("cvep", "abc") == () and option_ecran("p300", 60.0) == (),
        "…et rien sans valeur, sur une valeur absurde, ou pour une fenêtre qui ne fait pas "
        "passer l'écran : elle mesure alors l'écran, comme avant")
    chk(all(option_cibles(k, ["Haut", "Bas"]) == ("--noms", "Haut,Bas") for k in CIBLES)
        and option_cibles("cvep", None) == () and option_cibles("cvep", "Haut") == ()
        and option_cibles("errp", ["Haut", "Bas"]) == () and CIBLES == {"cvep", "p300", "ssvep"},
        f"les noms des cibles partent aux fenêtres c-VEP, P300 et SSVEP, et seulement s'ils sont "
        f"lisibles ({option_cibles('cvep', ['Haut', 'Bas'])}, {option_cibles('errp', ['Haut', 'Bas'])})")
    chk(set(ECRAN) == {"ssvep", "cvep"} and set(ECRAN.values()) <= {"reglage", "modele"},
        f"seuls le SSVEP et le c-VEP font passer l'écran, et chacun dit d'où vient la valeur "
        f"({ECRAN})")

    # --- LES CIBLES PHYSIQUES ----------------------------------------------
    chk(option_physiques("ssvep", {"cibles": "physiques", "freqs": [6.0, 8.0]}) == ("--physiques",)
        and option_physiques("ssvep", {"cibles": "ecran"}) == ()
        and option_physiques("ssvep", {}) == () and option_physiques("ssvep", None) == ()
        and option_physiques("cvep", {"cibles": "physiques"}) == (),
        f"des cibles PHYSIQUES dans les réglages du mode partent sous `--physiques`, à la seule "
        f"fenêtre qui sait les tenir ({option_physiques('ssvep', {'cibles': 'physiques'})}, "
        f"{option_physiques('ssvep', {'cibles': 'ecran'})}, "
        f"{option_physiques('cvep', {'cibles': 'physiques'})})")
    from core.modes.contract import CIBLES_PHYSIQUES
    from core.modes.ssvep import SPEC as _SSVEP
    choix = {p.key: p.choices for p in _SSVEP.params}
    chk(all(v == CIBLES_PHYSIQUES and v in (choix.get(c) or ()) for c, v, _a in PHYSIQUES.values()),
        f"…et le réglage lu est celui du CONTRAT : la clé est un paramètre du mode et la valeur "
        f"est `contract.CIBLES_PHYSIQUES` — recopiée ici, elle pourrait sinon diverger sans bruit "
        f"({PHYSIQUES}, {CIBLES_PHYSIQUES!r})")

    print(f"[stim-registry] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
