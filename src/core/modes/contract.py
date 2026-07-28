"""Le contrat d'un mode : ce qu'il est, ce qui s'y règle, et comment un réglage est validé.

Un `ModeSpec` est déclaré **à côté de son décodeur** (`modes/ssvep.py` déclare le SSVEP), jamais
dans un fichier de configuration séparé : deux vérités finissent toujours par diverger.

Le même `Param` sert TROIS usages, et c'est tout l'intérêt de l'objet :
    1. la console en génère un champ de formulaire (`src/console/params_form.py`) ;
    2. le moteur s'en sert pour VALIDER ce qu'on lui soumet (`validate` ci-dessous) ;
    3. son `help` explique à l'étudiant ce qu'il doit comprendre avant d'y toucher.

⚠️ La validation est la pièce sérieuse. Un réglage SSVEP invalide — une fréquence hors bande
passante, deux cibles plus proches que la résolution de la fenêtre — ne lève AUCUNE erreur à
l'exécution : le décodage ne détecte simplement jamais rien, ce qui ressemble à « l'utilisateur
fixe mal ». C'est le mode de panne le plus coûteux du projet, et la raison pour laquelle un refus
part avec sa raison en clair.

Autotest :
    python src/core/modes/contract.py
"""

import os as _os
import sys as _sys
from dataclasses import dataclass

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import BANDPASS, WINDOW_S, use_utf8_console  # noqa: E402
from core.lsl_io import stream_name as _stream_name  # noqa: E402


@dataclass(frozen=True)
class Param:
    """Un réglage exposé à l'utilisateur : son type, ses bornes, son aide."""

    key: str                  # "freqs" — identifiant stable, la clé côté commande
    label: str                # "Fréquences des cibles" — ce que lit l'étudiant
    kind: str                 # "float" | "int" | "bool" | "choice" | "float_list"
    unit: str = ""            # "Hz"
    default: object = None
    min: float = None         # bornes par VALEUR (pour une liste : chaque élément)
    max: float = None
    count: tuple = None       # (mini, maxi) d'éléments, pour les listes
    choices: tuple = ()
    constraints: tuple = ()   # contraintes CROISÉES nommées, cf. _check_constraint
    proposes: str = ""        # ce paramètre en PROPOSE un autre (chantier 2 ; cf. spec §3.1)
    help: str = ""


@dataclass(frozen=True)
class Rest:
    """Le plancher de repos exigé par un mode avant de pouvoir décoder."""

    warmup_s: float      # stabilisation JETÉE : l'Unicorn sort un offset DC qui DÉRIVE pendant
    #                      des dizaines de secondes après l'ouverture de session (mesuré le
    #                      2026-07-27 : 10⁵ µV en rampe). Un plancher mesuré là-dedans hérite d'un
    #                      σ gonflé, et comme on décide sur z, le seuil devient INATTEIGNABLE.
    duration_s: float
    instruction: str     # consigne à AFFICHER pendant la mesure — sans elle, le plancher est
    #                      mesuré pendant que l'étudiant fixe une cible, et il est faux.


@dataclass(frozen=True)
class Calib:
    """Ce qu'il faudrait pour entraîner ce mode. Informatif dans ce chantier (spec §3)."""

    kind: str        # "console" (consignes rendues par la console) | "natif" (fenêtre pygame)
    reason: str = ""  # pourquoi "natif" — c'est une contrainte PHYSIQUE, pas une préférence


@dataclass(frozen=True)
class ModeSpec:
    """Tout ce que le produit sait d'un mode — y compris d'un mode qu'il ne sait pas faire.

    Le registre décrit **tous** les modes, publiés ou non. C'est lui qui porte l'honnêteté de
    l'interface : sans ça, la grille ne montrerait que ce qui est chargé, et les modes manquants
    seraient invisibles.
    """

    id: str                    # "ssvep" — clé stable, partout
    label: str                 # "SSVEP"
    family: str                # "actif" (l'utilisateur choisit) | "passif" (on observe)
    summary: str               # une phrase : ce que le mode produit
    status: str                # "moteur" | "appli_pygame" | "prevu"
    unavailable: str = ""      # POURQUOI il n'est pas dans le moteur ; "" si status == "moteur"
    params: tuple = ()
    rest: Rest = None
    calibration: Calib = None
    stream: str = None         # suffixe du flux publié, ex. "decoded_ssvep"
    channels: tuple = ()       # voies de ce flux, quand elles sont FIXES
    channels_fn: object = None  # (params) -> voies, quand elles dépendent d'un réglage (SSVEP)
    runtime_cls: object = None  # la classe ModeRuntime, ou None si le moteur ne sait pas le faire

    def defaults(self):
        """Le jeu de réglages par défaut de ce mode."""
        return {p.key: p.default for p in self.params}

    def channels_for(self, params):
        """Les voies réellement publiées pour ces réglages.

        Le SSVEP nomme ses voies d'après ses fréquences (`score_15Hz`) : une liste figée dans le
        contrat mentirait dès le premier changement de réglage.
        """
        return tuple(self.channels_fn(params)) if self.channels_fn else tuple(self.channels)


def validate(spec, params):
    """(réglages complets, None) si tout passe, sinon (None, raison en clair).

    Les clés absentes prennent leur défaut : un appelant peut ne soumettre que ce qu'il change.
    """
    known = {p.key: p for p in spec.params}
    inconnus = sorted(k for k in params if k not in known)
    if inconnus:
        return None, (f"réglage inconnu pour « {spec.label} » : {', '.join(inconnus)} "
                      f"(attendu : {', '.join(sorted(known)) or 'aucun réglage'})")

    values = spec.defaults()
    for key, param in known.items():
        if key not in params:
            continue
        value, reason = _coerce(param, params[key])
        if reason:
            return None, reason
        values[key] = value

    for param in spec.params:
        reason = _check_constraints(param, values)
        if reason:
            return None, reason
    return values, None


def _unit(param):
    return f" {param.unit}" if param.unit else ""


def _check_bounds(param, value):
    if param.min is not None and value < param.min:
        return (f"« {param.label} » : {value:g}{_unit(param)} est sous le minimum "
                f"{param.min:g}{_unit(param)}")
    if param.max is not None and value > param.max:
        return (f"« {param.label} » : {value:g}{_unit(param)} dépasse le maximum "
                f"{param.max:g}{_unit(param)}")
    return None


def _coerce(param, value):
    """(valeur convertie, None) ou (None, raison). Convertit AVANT de vérifier les bornes."""
    if param.kind == "bool":
        return bool(value), None

    if param.kind == "choice":
        if value not in param.choices:
            return None, (f"« {param.label} » : {value!r} n'est pas un choix valide "
                          f"({', '.join(str(c) for c in param.choices)})")
        return value, None

    if param.kind == "float_list":
        if isinstance(value, (str, bytes)):
            return None, f"« {param.label} » : liste de nombres attendue, reçu {value!r}"
        try:
            values = tuple(float(v) for v in value)
        except (TypeError, ValueError):
            return None, f"« {param.label} » : liste de nombres attendue, reçu {value!r}"
        if param.count:
            lo, hi = param.count
            if not lo <= len(values) <= hi:
                return None, (f"« {param.label} » : il en faut entre {lo} et {hi}, "
                              f"il y en a {len(values)}")
        for v in values:
            reason = _check_bounds(param, v)
            if reason:
                return None, reason
        return values, None

    try:
        converted = int(value) if param.kind == "int" else float(value)
    except (TypeError, ValueError):
        return None, f"« {param.label} » : nombre attendu, reçu {value!r}"
    reason = _check_bounds(param, converted)
    return (None, reason) if reason else (converted, None)


def _check_constraints(param, values):
    """Contraintes CROISÉES, nommées dans le contrat et implémentées ICI — jamais dans l'interface.

    Elles reçoivent tous les réglages du mode, pas seulement le leur : c'est ce qui permettra au
    chantier 2 de vérifier qu'un nombre de cibles s'accorde à une liste de fréquences.
    """
    for name in param.constraints:
        if name == "dans_la_bande":
            lo, hi = BANDPASS
            hors = [v for v in _as_list(values.get(param.key)) if not lo <= v <= hi]
            if hors:
                return (f"« {param.label} » : hors bande passante {lo:g}-{hi:g} Hz : "
                        + ", ".join(f"{v:g}" for v in hors)
                        + " — le filtre d'acquisition les supprime AVANT le décodage")

        elif name == "separables":
            # Résolution fréquentielle d'une fenêtre de WINDOW_S : deux cibles plus proches que
            # 1/WINDOW_S ne sont pas séparables, quelle que soit la qualité du signal.
            ecart_min = 1.0 / WINDOW_S
            ordonne = sorted(_as_list(values.get(param.key)))
            proches = [(a, b) for a, b in zip(ordonne, ordonne[1:]) if b - a < ecart_min]
            if proches:
                return (f"« {param.label} » : cibles trop proches pour une fenêtre de "
                        f"{WINDOW_S:g} s (écart minimum {ecart_min:.2f} Hz) : "
                        + ", ".join(f"{a:g} et {b:g}" for a, b in proches))

        else:
            return f"contrainte inconnue « {name} » sur « {param.label} » (défaut du contrat)"
    return None


def _as_list(value):
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _selftest():
    """Contrôle la validation : ce qui passe, ce qui est refusé, et avec quelle raison.

    Le refus DOIT porter sa raison en clair. Un paramètre invalide ne produit aucune erreur à
    l'exécution, seulement un décodage muet — le mode de panne le plus coûteux du projet.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    spec = ModeSpec(
        id="essai", label="Essai", family="actif", summary="mode de test", status="moteur",
        params=(
            Param("freqs", "Fréquences des cibles", "float_list", unit="Hz",
                  default=(15.0, 20.0, 8.57), count=(2, 8),
                  constraints=("dans_la_bande", "separables")),
            Param("gain", "Gain", "float", default=1.0, min=0.0, max=10.0),
            Param("actif", "Activé", "bool", default=True),
            Param("methode", "Méthode", "choice", default="cca", choices=("cca", "fbcca")),
        ))

    values, reason = validate(spec, {})
    chk(values == {"freqs": (15.0, 20.0, 8.57), "gain": 1.0, "actif": True, "methode": "cca"},
        f"sans rien fournir, on obtient les défauts ({values})")
    chk(reason is None, "aucune raison de refus sur les défauts")

    values, reason = validate(spec, {"gain": 3})
    chk(values is not None and values["gain"] == 3.0 and values["freqs"] == (15.0, 20.0, 8.57),
        "un réglage partiel garde les défauts des autres")

    for params, attendu in (
            ({"freqs": [15.0, 60.0]}, "hors bande passante"),
            ({"freqs": [15.0, 15.2]}, "trop proches"),
            ({"freqs": [15.0]}, "il en faut entre 2 et 8"),
            ({"freqs": [15.0] * 9}, "il en faut entre 2 et 8"),
            ({"freqs": "quinze"}, "liste de nombres attendue"),
            ({"gain": 99.0}, "dépasse le maximum"),
            ({"gain": -1.0}, "sous le minimum"),
            ({"gain": "beaucoup"}, "nombre attendu"),
            ({"methode": "magie"}, "n'est pas un choix valide"),
            ({"couleur": "rouge"}, "réglage inconnu")):
        values, reason = validate(spec, params)
        chk(values is None and reason and attendu in reason,
            f"{params} refusé : {reason}")

    # `separables` porte sur la résolution de la fenêtre, pas sur un goût : deux cibles
    # distantes de moins de 1/WINDOW_S ne sont PAS séparables, quelle que soit la qualité.
    ecart = 1.0 / WINDOW_S
    values, _ = validate(spec, {"freqs": [15.0, 15.0 + ecart + 0.01]})
    chk(values is not None, f"deux cibles à {ecart + 0.01:.2f} Hz d'écart passent")
    values, _ = validate(spec, {"freqs": [15.0, 15.0 + ecart - 0.01]})
    chk(values is None, f"deux cibles à {ecart - 0.01:.2f} Hz d'écart sont refusées")

    # Un float_list qui déclare des bornes SANS contrainte doit quand même être borné :
    # sinon un futur mode accepterait des valeurs hors plage en silence.
    borne = ModeSpec(id="borne", label="Borné", family="actif", summary="", status="moteur",
                     params=(Param("liste", "Liste bornée", "float_list", default=(1.0,),
                                   min=0.0, max=10.0),))
    values, reason = validate(borne, {"liste": [5.0, 99.0]})
    chk(values is None and reason and "dépasse le maximum" in reason,
        f"un float_list borné sans contrainte reste borné : {reason}")

    # « Brancher un client » : le texte doit être du Python VALIDE, et porter les vrais noms.
    from core.modes import ssvep as _ssvep

    extrait = client_snippet(_ssvep.SPEC, {"freqs": (15.0, 20.0, 8.57)})
    chk("EEG_API_Unicorn_decoded_ssvep" in extrait, "l'extrait nomme le vrai flux")
    chk("score_15Hz" in extrait and "score_8.57Hz" in extrait,
        "et les voies telles qu'elles seront publiées")
    chk("open_stream" in extrait,
        "et il appelle open_stream — sans ça un client perd tout ce qui précède son 1er pull")
    try:
        compile(extrait, "<extrait>", "exec")
        chk(True, "l'extrait compile : c'est du Python qu'on peut vraiment coller")
    except SyntaxError as e:
        chk(False, f"l'extrait ne compile pas : {e}")

    chk(client_snippet(ModeSpec(id="x", label="X", family="actif", summary="", status="prevu",
                                unavailable="pas encore")) == "",
        "un mode sans flux ne propose aucun extrait")

    print(f"[contract] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def client_snippet(spec, params=None):
    """Un extrait Python prêt à coller pour consommer le flux de ce mode. "" s'il n'en a pas.

    Généré depuis le contrat, jamais écrit à la main dans l'interface : les voies d'un flux
    SSVEP dépendent des fréquences réglées, et un exemple qui vieillit mal est pire que pas
    d'exemple — l'étudiant croit avoir copié le bon code.

    `open_stream()` est dans l'extrait pour une raison : un StreamInlet n'ouvre sa connexion
    qu'au premier `pull_*`, et LSL ne rejoue RIEN de ce qui a été publié avant. Sans cette
    ligne on perd la première seconde de signal. C'est le piège classique de LSL, à répéter
    dans tout ce qu'on met sous les yeux d'un étudiant.
    """
    if not spec.stream:
        return ""
    voies = spec.channels_for(spec.defaults() if params is None else params)
    return f'''"""{spec.label} - {spec.summary}

Voies publiees : {", ".join(voies)}
"""
from pylsl import StreamInlet, resolve_byprop

flux = resolve_byprop("name", "{_stream_name(spec.stream)}", timeout=10)
if not flux:
    raise SystemExit("flux introuvable - le moteur tourne-t-il, et ce mode est-il demarre ?")

inlet = StreamInlet(flux[0])
inlet.open_stream()   # AVANT le premier pull : LSL ne rejoue rien de ce qui precede

while True:
    valeurs, horodatage = inlet.pull_sample()
    print(horodatage, dict(zip({list(voies)!r}, valeurs)))
'''


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
