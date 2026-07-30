"""Le catalogue de TOUS les modes — ceux que le moteur fait tourner, et les autres.

L'ordre de `MODES` est celui de l'affichage dans la grille, et il sert aussi d'arbitre : quand
deux modes lancés ensemble demandent un repos de même durée, c'est le premier d'ici qui donne la
consigne affichée. Une règle déterministe vaut mieux qu'un « ça dépend » (spec §4.2).

Autotest :
    python src/core/modes/registry.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import use_utf8_console  # noqa: E402
from core.modes import external, neuro, raw, ssvep  # noqa: E402
from core.modes.contract import validate  # noqa: E402

MODES = (
    raw.SPEC,           # le brut d'abord : c'est ce qui existe même sans décodage
    ssvep.SPEC,
    neuro.SPEC,
    external.MI,        # puis les modes de l'appli pygame, dans l'ordre où ils ont été écrits
    external.CVEP,
    external.P300,
    external.ERRP,
)

BY_ID = {spec.id: spec for spec in MODES}


def get(mode_id):
    """Le `ModeSpec` de cet identifiant, ou None."""
    return BY_ID.get(mode_id)


def runnable():
    """Les modes que le moteur sait faire tourner, dans l'ordre du registre."""
    return tuple(spec for spec in MODES if spec.runtime_cls is not None)


def serialize(spec, params=None):
    """Le `ModeSpec` en dictionnaire JSON-able — ce que la console reçoit.

    On sérialise plutôt que de passer l'objet : la console lit un ÉTAT, pas des références vers
    l'intérieur du moteur, et ce même dictionnaire pourra partir sur le flux `status` le jour où
    un client voudra découvrir les modes tout seul.
    """
    params = spec.defaults() if params is None else params
    return {
        "id": spec.id,
        "label": spec.label,
        "family": spec.family,
        "summary": spec.summary,
        "status": spec.status,
        "unavailable": spec.unavailable,
        "stream": spec.stream,
        "channels": list(spec.channels_for(params)),
        "params": [
            {
                "key": p.key, "label": p.label, "kind": p.kind, "unit": p.unit,
                "default": (lambda dflt: list(dflt) if isinstance(dflt, tuple) else dflt)(p.default_now()),
                "min": p.min, "max": p.max,
                "count": list(p.count) if p.count else None,
                "proposes": p.proposes,
                "choices": list(p.choices_now()), "help": p.help
            }
            for p in spec.params
        ],
        "rest": None if spec.rest is None else {
            "warmup_s": spec.rest.warmup_s,
            "duration_s": spec.rest.duration_s,
            "instruction": spec.rest.instruction,
        },
        "calibration": None if spec.calibration is None else {
            "kind": spec.calibration.kind, "reason": spec.calibration.reason,
        },
    }


def catalog():
    """Tout le registre, sérialisé. C'est ce qui remplit la grille de la console."""
    return [serialize(spec) for spec in MODES]


def check():
    """(tout va bien, liste des défauts). Un défaut ici ne lève AUCUNE erreur au démarrage.

    C'est pour ça que ce test existe : un `default` hors de ses propres bornes ne casse rien
    visiblement — le mode refuse simplement d'appliquer ses réglages, et on le découvre en
    séance, casque sur la tête. Deux modes qui publieraient le même suffixe de flux seraient
    pires encore : LSL les accepterait tous les deux, et un client recevrait un mélange.
    """
    defauts = []
    vus_id, vus_stream = set(), {}

    for spec in MODES:
        if spec.id in vus_id:
            defauts.append(f"identifiant en double : {spec.id}")
        vus_id.add(spec.id)

        if spec.status not in ("moteur", "appli_pygame", "prevu"):
            defauts.append(f"{spec.id} : status « {spec.status} » inconnu")
        if spec.family not in ("actif", "passif", "brut"):
            defauts.append(f"{spec.id} : family « {spec.family} » inconnue")
        if spec.status != "moteur" and not spec.unavailable:
            defauts.append(f"{spec.id} : status « {spec.status} » sans explication (unavailable vide)")
        if spec.status == "moteur" and spec.unavailable:
            defauts.append(f"{spec.id} : status « moteur » mais unavailable renseigné")

        if spec.stream:
            if spec.stream in vus_stream:
                defauts.append(f"suffixe de flux en double : {spec.stream} "
                               f"({vus_stream[spec.stream]} et {spec.id})")
            vus_stream[spec.stream] = spec.id
        if spec.status == "moteur" and not spec.stream:
            defauts.append(f"{spec.id} : mode du moteur sans flux à publier")

        # Chaque défaut doit respecter les bornes de son PROPRE paramètre. Sinon le mode
        # démarre et refuse ses propres réglages à la première soumission.
        # Exception : les choix dynamiques peuvent être vides (aucun modèle entraîné encore) ;
        # c'est normal après un git clone, pas un défaut de contrat.
        sans_choix = [p.key for p in spec.params if p.choices_fn and not p.choices_now()]
        if sans_choix:
            # Indiquer informativement qu'on saute la vérification : le mode est normal, l'état du
            # poste est en attente (aucun modèle entraîné pour ce(s) paramètre(s) encore).
            clés_str = ", ".join(sans_choix)
            print(f"  NORMAL {spec.id}: defaults not checked for {clés_str} "
                  f"(no trained models yet — will validate when populated)")
        else:
            values, reason = validate(spec, {})
            if values is None:
                defauts.append(f"{spec.id} : ses valeurs par défaut sont refusées — {reason}")

        cles = {p.key for p in spec.params}
        for p in spec.params:
            if p.proposes and p.proposes not in cles:
                defauts.append(f"{spec.id}.{p.key} : propose « {p.proposes} », "
                               f"qui n'est pas un paramètre de ce mode")
            if p.kind not in ("float", "int", "bool", "choice", "float_list"):
                defauts.append(f"{spec.id}.{p.key} : kind « {p.kind} » inconnu")
            if p.kind == "choice" and not p.choices and not p.choices_fn:
                defauts.append(f"{spec.id}.{p.key} : un choix sans choices")
            if not p.help:
                defauts.append(f"{spec.id}.{p.key} : pas de texte d'aide "
                               f"(un étudiant doit savoir ce qu'il règle)")

        # Les voies annoncées doivent correspondre à ce qui sera réellement publié.
        if spec.stream and not spec.channels_for(spec.defaults()):
            defauts.append(f"{spec.id} : publie {spec.stream} sans annoncer ses voies")

    return (not defauts), defauts


def _selftest():
    ok, defauts = check()

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    for spec in MODES:
        marque = {"moteur": "●", "appli_pygame": "○", "prevu": "·"}[spec.status]
        detail = f" — {spec.unavailable}" if spec.unavailable else ""
        print(f"  {marque} {spec.id:<7} {spec.label:<14} {spec.family:<7} {spec.status}{detail}")
    for d in defauts:
        print(f"  ÉCHEC {d}")
    print(f"[registry] {len(MODES)} modes, dont {len(runnable())} dans le moteur")

    # Le catalogue doit porter `proposes`, sinon la console ne peut pas savoir qu'un réglage en
    # propose un autre — et le bouton correspondant n'apparaîtrait jamais, sans erreur.
    ssvep_serialise = serialize(get("ssvep"))
    par_cle = {p["key"]: p for p in ssvep_serialise["params"]}
    chk(par_cle["refresh_hz"]["proposes"] == "freqs",
        f"le catalogue transmet `proposes` ({par_cle['refresh_hz'].get('proposes')!r})")
    chk("affecte_decodage" not in par_cle["freqs"],
        "et NE transmet PAS `affecte_decodage`, qui ne regarde que le moteur")

    print(f"[registry] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
