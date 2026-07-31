"""`CalibrationRuntime` — la ligne du temps d'une calibration, jouée par le MOTEUR.

Ce qui est ICI est ce que **toute** calibration partage : la chauffe, l'échauffement non
enregistré, la suite d'essais tirés au hasard, l'entraînement, le résultat. Ce qui est dans les
sous-classes est ce qui diffère : les classes à cuer, les consignes, et ce qu'on fait des époques
à la fin.

⚠️ **Une calibration n'est PAS un mode.** Elle vit dans un emplacement propre du moteur
(`EngineServer.calibration`), pas dans `self.active`. La raison est concrète : le mode Motor
Imagery REFUSE de démarrer sans modèle entraîné, donc une calibration hébergée par ce mode serait
inatteignable pour la seule personne qui en a besoin — celle qui n'a pas encore de modèle.

⚠️ **Un runtime ne lit jamais l'horloge lui-même** : `tick` reçoit `now`, comme `ModeRuntime`.
C'est ce qui permet de jouer une séance de sept minutes en quelques millisecondes dans un test.

Autotest :
    python src/core/modes/calibration.py
"""

import os as _os
import random as _random
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import use_utf8_console  # noqa: E402

# Les phases publiques, dans l'ordre où elles s'enchaînent. Elles sortent telles quelles dans
# `snapshot()["calibration"]["phase"]` : la console les traduit, elle n'en invente aucune.
PHASES = ("chauffe", "echauffement", "essais", "entrainement", "fini", "annule")

# Les étapes À L'INTÉRIEUR d'un essai.
ETAPES = ("cue", "imagerie", "repos")


class CalibrationRuntime:
    """Une calibration en cours. Le moteur en tient AU PLUS UNE — le casque est unique."""

    # --- à renseigner par la sous-classe ------------------------------------
    classes = ()            # les étiquettes à cuer, dans l'ordre de déclaration
    cue_s = 3.0             # mise en route, JETÉE
    imagery_s = 4.0         # la partie ENREGISTRÉE
    rest_s = 1.5            # pause entre deux essais
    warmup_s = 15.0         # stabilisation du casque, JETÉE (dérive DC de l'Unicorn)
    warmup_per_class = 2    # essais d'échauffement NON enregistrés

    def __init__(self, spec, params, engine, rng=None):
        """`spec` : le `ModeSpec` du mode calibré. `params` : les réglages VALIDÉS de la calibration.

        `rng` est injectable pour que le test obtienne un ordre reproductible. En séance il est
        tiré au hasard, et il DOIT l'être : un ordre fixe apprendrait au sujet à anticiper la
        classe suivante, ce qui contamine l'imagerie par de l'attente motrice.
        """
        self.spec = spec
        self.calib = spec.calibration
        self.params = dict(params)
        self.engine = engine
        self.rng = rng or _random.Random()

        self.phase = "chauffe"
        self.etape = ""
        self.classe = ""
        self.essai = 0            # essais ENREGISTRÉS déjà terminés
        self.resultat = None
        self.probleme = ""
        self._echeance = None     # instant de fin de l'étape en cours (horloge de l'appelant)
        self._suite = []          # les étiquettes restantes de la phase en cours
        self._enregistre = []     # [(époque (n, 8), étiquette)]
        self._demarre = False

    # --- ce que la sous-classe fournit ---------------------------------------

    def instruction(self):
        """La consigne à afficher MAINTENANT, en grand."""
        return ""

    def rappel(self):
        """La ligne secondaire, sous la consigne. "" s'il n'y en a pas."""
        return ""

    def _entrainer(self, enregistre, fs):
        """Entraîne et sauvegarde. Rend le dict de résultat, ou lève avec un message lisible."""
        raise NotImplementedError

    # --- la ligne du temps ---------------------------------------------------

    @property
    def terminee(self):
        return self.phase in ("fini", "annule")

    def trials_per_class(self):
        return int(self.params.get("trials_per_class", 0))

    def total(self):
        """Le nombre d'essais ENREGISTRÉS de la séance. L'échauffement n'en fait pas partie."""
        return self.trials_per_class() * len(self.classes)

    def duree_estimee_s(self):
        """Le temps total, échauffement et chauffe compris. Calculé, jamais stocké."""
        par_essai = self.cue_s + self.imagery_s + self.rest_s
        n = self.total() + self.warmup_per_class * len(self.classes)
        return self.warmup_s + n * par_essai

    def cancel(self):
        """Abandon. Ce qui est déjà enregistré n'est PAS entraîné ni sauvegardé.

        Choix délibéré : une séance interrompue à cinq essais produirait un modèle que rien ne
        distingue d'un modèle complet dans la liste, et qui donnerait des probabilités plausibles
        et fausses. L'écran pygame, lui, entraînait sur ce qui restait — comportement qu'on ne
        reprend pas.
        """
        if not self.terminee:
            self.phase = "annule"
            self.etape, self.classe, self._echeance = "", "", None

    def tick(self, engine, now):
        """Un pas. Appelé par la boucle du moteur, jamais par une interface."""
        if self.terminee:
            return
        if not self._demarre:
            self._demarre = True
            self._echeance = now + self.warmup_s
            return

        if self._echeance is not None and now < self._echeance:
            return

        if self.phase == "chauffe":
            self._commencer_echauffement(now)
        elif self.phase in ("echauffement", "essais"):
            self._pas_essai(engine, now)
        elif self.phase == "entrainement":
            self._terminer(engine)

    def _commencer_echauffement(self, now):
        self._suite = self._tirage(self.warmup_per_class)
        if not self._suite:
            self._commencer_essais(now)
            return
        self.phase = "echauffement"
        self._prochain_essai(now)

    def _commencer_essais(self, now):
        self.phase = "essais"
        self._suite = self._tirage(self.trials_per_class())
        if not self._suite:
            self.phase = "entrainement"
            self.etape, self.classe, self._echeance = "", "", now
            return
        self._prochain_essai(now)

    def _tirage(self, par_classe):
        """Les étiquettes d'une phase, MÉLANGÉES. Un ordre fixe s'anticipe (cf. `__init__`)."""
        suite = [c for c in self.classes for _ in range(par_classe)]
        self.rng.shuffle(suite)
        return suite

    def _prochain_essai(self, now):
        self.classe = self._suite.pop(0)
        self.etape = "cue"
        self._echeance = now + self.cue_s

    def _pas_essai(self, engine, now):
        if self.etape == "cue":
            self.etape = "imagerie"
            self._echeance = now + self.imagery_s
            return

        if self.etape == "imagerie":
            # L'époque est prélevée À LA FIN de l'imagerie, pas au fil de l'eau : le tampon
            # glissant du moteur contient les `imagery_s` dernières secondes, et c'est exactement
            # celles-là qu'on veut. `epoch_s` du contrat garantit que le tampon est assez long.
            if self.phase == "essais":
                epoque = engine.recent_window(self.imagery_s)
                attendu = int(round(self.imagery_s * engine.acq.fs))
                if epoque is not None and len(epoque) >= attendu:
                    self._enregistre.append((epoque, self.classe))
                    self.essai += 1
                else:
                    # On le DIT plutôt que d'enregistrer une époque courte : un essai tronqué
                    # produit moins de fenêtres d'entraînement, en silence.
                    obtenu = 0 if epoque is None else len(epoque)
                    print(f"[calib] essai IGNORÉ ({self.classe}) : {obtenu} échantillons au lieu "
                          f"de {attendu} — le tampon du moteur n'était pas encore rempli")
            self.etape = "repos"
            self._echeance = now + self.rest_s
            return

        # repos terminé
        if self._suite:
            self._prochain_essai(now)
        elif self.phase == "echauffement":
            self._commencer_essais(now)
        else:
            self.phase = "entrainement"
            self.etape, self.classe, self._echeance = "", "", now

    def _terminer(self, engine):
        """L'entraînement. Bloque la boucle du moteur le temps du `fit` — quelques secondes.

        C'est assumé : à cet instant, plus rien ne doit être acquis pour cette séance, et
        déporter l'entraînement dans un fil ferait toucher `data/` par deux fils. Le décodage des
        autres modes est simplement suspendu pendant ce temps.
        """
        try:
            self.resultat = self._entrainer(self._enregistre, float(engine.acq.fs))
            self.phase = "fini"
        except Exception as e:  # noqa: BLE001 - l'échec de l'entraînement ne tue pas le moteur
            self.probleme = f"{type(e).__name__} : {e}"
            self.phase = "annule"
            print(f"[calib] entraînement impossible : {self.probleme}")
        self.etape, self.classe, self._echeance = "", "", None

    # --- l'état, pour l'afficheur -------------------------------------------

    def restant_s(self, now):
        """Secondes restantes sur l'étape en cours. 0 quand il n'y a rien à décompter."""
        if self._echeance is None:
            return 0.0
        return max(0.0, self._echeance - now)

    def state(self, now=None):
        """L'état complet, en dictionnaire JSON-able. Sûr depuis un autre fil.

        `now` est facultatif : sans lui, le décompte vaut 0. Le moteur le passe depuis sa boucle,
        et c'est la seule horloge qui fait foi.
        """
        return {
            "mode_id": self.spec.id,
            "label": self.calib.label or f"Calibration {self.spec.label}",
            "phase": self.phase,
            "etape": self.etape,
            "classe": self.classe,
            "instruction": self.instruction(),
            "rappel": self.rappel(),
            "essai": self.essai,
            "total": self.total(),
            "restant_s": round(self.restant_s(now), 1) if now is not None else 0.0,
            "duree_estimee_s": round(self.duree_estimee_s(), 1),
            "params": dict(self.params),
            "classes": list(self.classes),
            "resultat": self.resultat,
            "probleme": self.probleme,
        }


def _selftest():
    """La ligne du temps sur une horloge FABRIQUÉE. Aucune séance, aucune attente réelle."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    import numpy as np

    from core.modes.contract import Calib, ModeSpec, Param

    class _FausseAcq:
        fs = 250.0

    class _FauxMoteur:
        """Rend toujours une époque de la bonne longueur : on teste la LIGNE DU TEMPS, pas
        l'acquisition."""

        def __init__(self):
            self.acq = _FausseAcq()
            self.demandes = []

        def recent_window(self, seconds):
            self.demandes.append(seconds)
            return np.zeros((int(round(seconds * self.acq.fs)), 8))

    class _Essai(CalibrationRuntime):
        classes = ("A", "B")
        cue_s, imagery_s, rest_s, warmup_s, warmup_per_class = 3.0, 4.0, 1.5, 15.0, 2

        def instruction(self):
            return f"Fais {self.classe}" if self.classe else ""

        def _entrainer(self, enregistre, fs):
            return {"n_essais": len(enregistre), "fs": fs,
                    "classes": sorted({lab for _e, lab in enregistre})}

    spec = ModeSpec(
        id="essai", label="Essai", family="actif", summary="", status="moteur",
        calibration=Calib(kind="console", label="Calibration d'essai", epoch_s=4.0,
                          params=(Param("trials_per_class", "Essais par classe", "int",
                                        default=3, min=1, max=40),),
                          runtime_cls=_Essai))

    moteur = _FauxMoteur()
    rt = _Essai(spec, {"trials_per_class": 3}, moteur, rng=_random.Random(0))

    chk(rt.total() == 6, f"3 essais par classe sur 2 classes = 6 essais enregistrés ({rt.total()})")
    chk(abs(rt.duree_estimee_s() - (15.0 + 10 * 8.5)) < 1e-6,
        f"la durée estimée compte l'échauffement ET la chauffe ({rt.duree_estimee_s():.1f} s)")

    # La chauffe est JETÉE : rien n'est enregistré pendant, et elle dure ce qu'elle annonce.
    t = 100.0
    rt.tick(moteur, t)
    chk(rt.phase == "chauffe", f"on commence par la chauffe ({rt.phase})")
    # `now=0.0` est une horloge VALIDE (l'instant zéro d'une séance), pas une absence d'horloge —
    # confusion qu'un `if now else ...` ferait puisque 0.0 est aussi FALSY en Python. La
    # distinction que documente `state(now=None)` (« sans lui, le décompte vaut 0 ») porte sur
    # l'ABSENCE de l'argument, jamais sur sa valeur.
    chk(rt.state(now=0.0)["restant_s"] == round(rt.restant_s(0.0), 1) > 0.0,
        f"now=0.0 est une horloge valide, distincte de l'absence d'horloge "
        f"({rt.state(now=0.0)['restant_s']})")
    rt.tick(moteur, t + 14.9)
    chk(rt.phase == "chauffe" and not moteur.demandes,
        "pendant la chauffe, RIEN n'est prélevé (la dérive DC fausserait les époques)")

    # Une horloge fabriquée, pas à pas : on avance par petits sauts jusqu'à la fin de la séance.
    t = 115.0
    for _ in range(4000):
        rt.tick(moteur, t)
        if rt.terminee:
            break
        t += 0.25

    chk(rt.phase == "fini", f"la séance se termine ({rt.phase}, problème={rt.probleme!r})")
    chk(rt.essai == 6, f"6 essais enregistrés, pas un de plus ({rt.essai})")
    chk(rt.resultat and rt.resultat["n_essais"] == 6,
        f"et c'est ce qui part à l'entraînement ({rt.resultat})")
    chk(rt.resultat and sorted(rt.resultat["classes"]) == ["A", "B"],
        f"les deux classes sont représentées ({rt.resultat})")
    # 10 essais joués (4 d'échauffement + 6 enregistrés), 6 prélèvements : l'échauffement ne
    # prélève RIEN. C'est le seul test qui distingue « non enregistré » de « enregistré puis jeté ».
    chk(len(moteur.demandes) == 6,
        f"l'échauffement ne prélève aucune époque ({len(moteur.demandes)} prélèvements pour "
        f"{4 + 6} essais joués)")
    chk(all(abs(s - 4.0) < 1e-9 for s in moteur.demandes),
        f"et chaque prélèvement demande imagery_s, pas la durée de l'essai ({set(moteur.demandes)})")

    # L'abandon : ni entraînement, ni modèle. Une séance à moitié faite ne doit pas produire un
    # modèle indiscernable d'un modèle complet.
    rt2 = _Essai(spec, {"trials_per_class": 3}, _FauxMoteur(), rng=_random.Random(1))
    t = 0.0
    for _ in range(200):
        rt2.tick(rt2.engine, t)
        t += 0.25
    rt2.cancel()
    chk(rt2.phase == "annule" and rt2.resultat is None,
        f"un abandon ne produit AUCUN modèle ({rt2.phase}, {rt2.resultat})")
    avant = rt2.essai
    rt2.tick(rt2.engine, t + 100.0)
    chk(rt2.essai == avant and rt2.phase == "annule",
        "et une calibration annulée ne repart pas toute seule au tick suivant")

    # Un entraînement qui lève ne doit pas tuer le moteur : il se solde en « annulé » + raison.
    class _Casse(_Essai):
        def _entrainer(self, enregistre, fs):
            raise ValueError("pas assez de données")

    rt3 = _Casse(spec, {"trials_per_class": 1}, _FauxMoteur(), rng=_random.Random(2))
    t = 0.0
    for _ in range(4000):
        rt3.tick(rt3.engine, t)
        if rt3.terminee:
            break
        t += 0.25
    chk(rt3.phase == "annule" and "pas assez de données" in rt3.probleme,
        f"un entraînement qui lève se solde par un refus lisible ({rt3.phase}, {rt3.probleme})")

    # L'état est JSON-able : il part dans `snapshot()`, que la console sérialise.
    import json

    json.dumps(rt.state(now=t))
    chk(True, "l'état est sérialisable en JSON")
    etat = rt.state(now=t)
    chk(set(etat) >= {"phase", "etape", "classe", "instruction", "essai", "total", "restant_s",
                      "resultat", "probleme"},
        f"et il porte tout ce que la console doit peindre ({sorted(etat)})")

    print(f"[calibration] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
