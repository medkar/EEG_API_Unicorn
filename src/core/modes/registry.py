"""Le catalogue de TOUS les modes — ceux que le moteur fait tourner, et les autres.

L'ordre de `MODES` est celui de l'affichage dans la grille, et il sert aussi d'arbitre : quand
deux modes lancés ensemble demandent un repos de même durée, c'est le premier d'ici qui donne la
consigne affichée. Une règle déterministe vaut mieux qu'un « ça dépend » (spec §4.2).

Autotest :
    python src/core/modes/registry.py
"""

import os as _os
import sys as _sys
from dataclasses import replace

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import use_utf8_console  # noqa: E402
from core.modes import external, mi, neuro, p300, raw, ssvep  # noqa: E402
from core.modes.contract import validate  # noqa: E402

MODES = (
    raw.SPEC,           # le brut d'abord : c'est ce qui existe même sans décodage
    ssvep.SPEC,
    neuro.SPEC,
    mi.SPEC,            # le MI a rejoint le moteur : il n'est plus une entrée « appli pygame »
    p300.SPEC,          # le P300 a rejoint le moteur : il écoute les marqueurs d'une appli externe
    external.CVEP,      # puis les modes de l'appli pygame, dans l'ordre où ils ont été écrits
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
    # Défauts résolus UNE SEULE fois, et réutilisés pour DEUX usages : le repli quand `params`
    # est absent (juste en dessous), et la clé "default" plus bas (qui doit rester le défaut
    # DÉCLARÉ même quand `params` est fourni — voir son commentaire).
    #
    # ⚠️ Ce n'est PAS une optimisation de chemin chaud : le catalogue a quitté `snapshot()`, donc
    # cette fonction n'est plus appelée qu'à l'ouverture de la console. Une seule résolution parce
    # qu'une source dynamique (`choices_fn`) peut lire le disque et que deux appels pourraient
    # rendre deux réponses DIFFÉRENTES — un modèle apparu entre les deux, et un catalogue qui se
    # contredirait lui-même. C'est de la cohérence, pas de la vitesse : ne pas « ré-optimiser ».
    #
    # Il reste malgré tout DEUX résolutions par choix dynamique par appel, pas une seule :
    # default_now() appelle choices_now() en interne pour un « choice » sans défaut déclaré, et
    # la clé "choices" plus bas a besoin de la liste ENTIÈRE, pas seulement du premier élément
    # que default_now() en tire. Recopier ici la logique de default_now() pour descendre à un
    # seul appel créerait deux vérités qui finiraient par diverger — la dépense reste à 2, pas 1.
    defauts = {p.key: p.default_now() for p in spec.params}
    params = defauts if params is None else params

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
                # Le défaut DÉCLARÉ, jamais la valeur courante : toujours tiré de `defauts`,
                # jamais de `params`, même quand l'appelant a soumis des `params` explicites.
                "default": list(defauts[p.key]) if isinstance(defauts[p.key], tuple) else defauts[p.key],
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
            "kind": spec.calibration.kind,
            "reason": spec.calibration.reason,
            "label": spec.calibration.label,
            "briefing": list(spec.calibration.briefing),
            "epoch_s": spec.calibration.epoch_s,
            # Même forme que les `params` d'un mode, juste au-dessus : la console réutilise
            # `ParamsForm` sans une ligne de code particulière.
            "params": [
                {
                    "key": p.key, "label": p.label, "kind": p.kind, "unit": p.unit,
                    "default": p.default_now(), "min": p.min, "max": p.max,
                    "count": list(p.count) if p.count else None, "proposes": p.proposes,
                    "choices": list(p.choices_now()), "help": p.help,
                }
                for p in spec.calibration.params
            ],
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

    Un seul réglage échappe au contrôle de son défaut : celui dont la liste de choix est VIDE
    (aucun modèle entraîné). Les autres réglages du même mode, eux, restent vérifiés — voir le
    commentaire dans la boucle.
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
        #
        # Une seule exception, et elle porte sur LE PARAMÈTRE, pas sur le mode : un choix
        # dynamique peut être vide (aucun modèle entraîné encore), ce qui est l'état normal de
        # tout dépôt fraîchement cloné — `data/` est gitignoré. Exempter le mode ENTIER, comme
        # c'était fait, faisait cesser toute vérification de ses autres défauts (`prob_min`,
        # `vote_len`, `min_votes`…) dans l'état le plus courant qui soit. On retire donc le seul
        # paramètre sans choix, et on valide tout le reste.
        #
        # Une source de choix qui LÈVE, elle, n'est pas une situation normale : c'est un défaut
        # de déclaration, et il part dans `defauts`. `choices_now()` rend `()` dans les deux cas
        # (à dessein : un affichage ne doit pas tomber), d'où `choices_status()`.
        sans_choix, sources_cassees = [], []
        for p in spec.params:
            if not p.choices_fn:
                continue
            choix, erreur = p.choices_status()
            if erreur:
                sources_cassees.append(f"{spec.id}.{p.key} : la source de choix a levé — {erreur}")
            elif not choix:
                sans_choix.append(p.key)
        defauts.extend(sources_cassees)

        if sans_choix:
            print(f"  NORMAL {spec.id}: {', '.join(sans_choix)} sans choix pour l'instant "
                  f"(aucun modele encore - sera valide quand rempli) ; les autres defauts du "
                  f"mode sont verifies")
        verifiable = replace(spec, params=tuple(p for p in spec.params if p.key not in sans_choix))
        values, reason = validate(verifiable, {})
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

        # La calibration de ce mode, si le moteur sait la jouer. `check()` est appelée EN
        # PREMIER par le smoke, précisément parce qu'« un défaut là-dedans explique tous les
        # suivants » (cf. sa docstring) — mais elle ignorait `spec.calibration` : un défaut
        # invalide dans un `Calib.params` traversait les quatre tests verts et n'était
        # découvert qu'au clic « Calibrer ». Une calibration « native » (kind="natif",
        # runtime_cls=None) n'est en revanche JAMAIS jouée par le moteur — c'est
        # `src/research/app.py` qui la joue — donc vérifier ses défauts ici n'aurait aucun
        # sens et signalerait des « défauts » qui n'en sont pas.
        calib = spec.calibration
        if calib is not None and calib.runtime_cls is not None:
            # Même traitement que les params du MODE juste au-dessus : un choix dynamique
            # vide reste normal sur un dépôt fraîchement cloné, une source qui LÈVE ne l'est
            # jamais.
            calib_sans_choix, calib_sources_cassees = [], []
            for p in calib.params:
                if not p.choices_fn:
                    continue
                choix, erreur = p.choices_status()
                if erreur:
                    calib_sources_cassees.append(
                        f"{spec.id}.calibration.{p.key} : la source de choix a levé — {erreur}")
                elif not choix:
                    calib_sans_choix.append(p.key)
            defauts.extend(calib_sources_cassees)

            calib_verifiable = replace(
                calib, params=tuple(p for p in calib.params if p.key not in calib_sans_choix))
            calib_values, calib_reason = validate(calib_verifiable, {})
            if calib_values is None:
                defauts.append(f"{spec.id} : les défauts de sa calibration sont refusés — "
                               f"{calib_reason}")

            # Le contrôle qui empêche le défaut de REVENIR : `epoch_s` (ici) dimensionne le
            # tampon du moteur (et, via lui, la fenêtre de mesure de la qualité — cf. A5) ;
            # `imagery_s` (côté runtime) décide combien on en PRÉLÈVE à la fin de chaque essai.
            # Deux sources de vérité pour le MÊME nombre, et rien ne les liait : un `epoch_s`
            # sous `imagery_s` tronquerait CHAQUE époque enregistrée EN SILENCE — un modèle
            # entraîné sur moins de signal que l'écran ne l'annonce, sans la moindre erreur.
            imagery_s = getattr(calib.runtime_cls, "imagery_s", None)
            if calib.epoch_s <= 0:
                defauts.append(f"{spec.id} : sa calibration a un runtime_cls mais "
                               f"epoch_s={calib.epoch_s:g} — le moteur ne dimensionnerait "
                               f"aucun tampon pour elle")
            elif imagery_s is not None and calib.epoch_s < imagery_s:
                defauts.append(f"{spec.id} : epoch_s={calib.epoch_s:g} s de sa calibration est "
                               f"SOUS imagery_s={imagery_s:g} s de son runtime — chaque époque "
                               f"serait tronquée en silence")

        # Le même piège que pour la calibration, un cran plus loin : `marker_epoch_s` (ici)
        # dimensionne le tampon du moteur ; `pre_s`/`post_s` (côté runtime) décident ce qu'on en
        # PRÉLÈVE. Deux sources de vérité pour le même nombre, et rien ne les lie : un
        # `marker_epoch_s` trop court tronquerait CHAQUE époque EN SILENCE.
        pre_s = getattr(spec.runtime_cls, "pre_s", None)
        post_s = getattr(spec.runtime_cls, "post_s", None)
        if pre_s is not None and post_s is not None:
            if spec.marker_epoch_s < pre_s + post_s:
                defauts.append(f"{spec.id} : marker_epoch_s={spec.marker_epoch_s:g} s est SOUS "
                               f"pre_s+post_s={pre_s + post_s:g} s de son runtime — chaque "
                               f"époque serait tronquée en silence")
        if spec.marker_epoch_s > 0 and spec.runtime_cls is None:
            defauts.append(f"{spec.id} : déclare marker_epoch_s sans runtime pour les consommer")

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

    # --- l'assouplissement des choix vides, sur un registre PIÉGÉ ---------------
    # Il n'était couvert par rien, alors que c'est l'état par défaut de tout dépôt fraîchement
    # cloné (`data/` est gitignoré, donc zéro modèle MI). On ne peut pas le prouver sur les
    # vrais modes — leur état dépend du poste — donc on remplace le registre le temps du test.
    from core.modes.contract import ModeSpec, Param

    def defauts_de(*params):
        """Les défauts que `check()` signale sur un registre fabriqué d'un seul mode."""
        global MODES
        vrais = MODES
        MODES = (ModeSpec(id="piege", label="Piégé", family="actif", summary="",
                          status="moteur", params=params, stream="decoded_piege",
                          channels=("x",)),)
        try:
            return check()[1]
        finally:
            MODES = vrais

    vide = Param(key="modele", label="Modèle", kind="choice", choices_fn=lambda: [],
                 help="aucun modèle entraîné pour l'instant")
    d = defauts_de(vide, Param(key="gain", label="Gain", kind="float", default=99.0, max=10.0,
                               help="entre 0 et 10"))
    chk(any("dépasse le maximum" in x for x in d),
        f"un choix vide n'exempte plus les AUTRES défauts du mode ({d})")

    d = defauts_de(vide,
                   Param(key="vote_len", label="Fenêtres du vote", kind="int", default=3,
                         min=1, max=15, help="fenêtres"),
                   Param(key="min_votes", label="Votes concordants", kind="int", default=10,
                         min=1, max=15, constraints=("votes_atteignables",), help="votes"))
    chk(any("jamais atteignable" in x for x in d),
        f"les contraintes croisées sont évaluées elles aussi ({d})")

    d = defauts_de(Param(key="modele", label="Modèle", kind="choice",
                         choices_fn=lambda: 1 / 0, help="source cassée"))
    chk(any("a levé" in x and "ZeroDivisionError" in x for x in d),
        f"une source de choix qui LÈVE est un défaut, pas une situation normale ({d})")

    print(f"[registry] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
