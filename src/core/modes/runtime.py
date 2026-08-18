"""`ModeRuntime` — l'état vivant d'un mode qui tourne : sa phase, son décodeur, son publieur.

Ce qui est ICI est ce que **tous** les modes partagent : la séquence chauffe → repos → décodage,
la publication activable, et le compte-rendu de repos. Ce qui est dans les sous-classes est ce qui
diffère vraiment : ce qu'on collecte pendant le repos, et ce qu'on publie ensuite.

Avant, cette séquence était écrite une fois pour TOUT le moteur. Ça marchait tant qu'un seul mode
tournait ; dès que deux tournent ensemble, ils sont à des phases différentes — l'un mesure encore
son plancher pendant que l'autre décode déjà. L'état devait donc descendre dans le mode.

⚠️ **Un runtime ne lit jamais l'horloge lui-même** : `tick` reçoit `now`. C'est ce qui rend la
machine de phases testable sans dormir, et ce qui garantit que tous les modes d'un même tour de
boucle raisonnent sur le MÊME instant.

Autotest :
    python src/core/modes/runtime.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import use_utf8_console  # noqa: E402
from core.modes.contract import ModeSpec, Rest  # noqa: E402


class ModeRuntime:
    """Un mode en train de tourner. Une instance par mode actif ; le moteur en tient un dict."""

    def __init__(self, spec, params, engine):
        self.spec = spec
        self.params = dict(params)
        self.engine = engine
        self.published = True
        self.phase = "running" if spec.rest is None else "warmup"
        self.rest_report = None
        self._warmup_s = 0.0 if spec.rest is None else spec.rest.warmup_s
        self._rest_s = 0.0 if spec.rest is None else spec.rest.duration_s
        self._warmup_until = None
        self._rest_until = None
        self._opened = False

    # --- cycle de vie --------------------------------------------------------

    def open(self):
        """Crée le flux de ce mode. Idempotent : ré-ouvrir un mode ouvert ne fait rien."""
        if not self._opened:
            self._open()
            self._opened = True

    def close(self):
        """Libère le flux. Le mode continue d'exister et de décoder pour l'affichage."""
        if self._opened:
            self._close()
            self._opened = False

    def set_published(self, on):
        """Publier sur le réseau, ou décoder pour soi seul.

        Couper la publication LIBÈRE vraiment le flux : il disparaît du réseau. On préfère ça à
        un flux vivant qui n'émettrait plus rien — un client verrait un flux sain et attendrait
        indéfiniment, ce qui est exactement le genre de silence que ce projet combat. Le
        rallumer recrée le flux, donc les clients doivent se réabonner (le NOM ne change pas).
        """
        self.published = bool(on)
        self.open() if self.published else self.close()

    def begin_rest(self, now, warmup_s=None, duration_s=None):
        """(Re)part pour une chauffe puis un repos. `None` = les durées du contrat.

        Indispensable après avoir touché une électrode, et après tout changement de réglage : un
        plancher mesuré sous d'autres réglages, ou pendant qu'un contact se stabilisait, reste
        faux pour toute la séance.
        """
        self.rest_report = None
        self._reset_rest()
        if self.spec.rest is None:
            self.phase = "running"
            return
        self._warmup_s = self.spec.rest.warmup_s if warmup_s is None else float(warmup_s)
        self._rest_s = self.spec.rest.duration_s if duration_s is None else float(duration_s)
        self._warmup_until = now + self._warmup_s
        self._rest_until = None
        self.phase = "warmup"

    # --- la boucle -----------------------------------------------------------

    def period_s(self):
        """Délai minimum entre deux `tick`. 0 = à chaque tour de boucle du moteur."""
        return 0.2

    def tick(self, engine, lsl_ts, now):
        """Un pas de ce mode. Appelé par la boucle du moteur, jamais par une interface."""
        if self.phase == "warmup":
            # Chauffe : on JETTE ces secondes au lieu de les verser dans le plancher.
            if self._warmup_until is not None and now < self._warmup_until:
                return
            self.phase = "rest"

        if self.phase == "rest":
            if self._rest_until is None:
                # Le décompte part de la PREMIÈRE fenêtre exploitable, pas du démarrage : le
                # tampon met WINDOW_S + la marge de filtre à en produire une. Compter depuis le
                # lancement rognerait le repos d'autant (mesuré : 3 fenêtres au lieu de 15, donc
                # plancher rejeté faute d'effectif).
                self._rest_until = now + self._rest_s
            if self._rest_step(engine, now):
                self.phase = "running"
            return

        self._run_step(engine, lsl_ts)

    # --- état, pour l'afficheur ---------------------------------------------

    def instruction(self):
        """Ce que l'utilisateur doit faire MAINTENANT, dans ce mode."""
        if self.phase in ("warmup", "rest") and self.spec.rest is not None:
            return self.spec.rest.instruction
        return ""

    def output(self):
        """La dernière sortie du mode, pour l'affichage. None si rien encore."""
        return None

    def channels(self):
        """Les voies de ce mode, d'après le contrat et les paramètres.

        Point d'extension pour les modes dont les voies dépendent d'un MODÈLE CHARGÉ : plutôt que
        de relire le modèle via le contrat (qui n'a que le disque pour savoir), la sous-classe
        peut surcharger cette méthode pour retourner les voies du modèle EN MÉMOIRE. Utile quand
        la calibration écrit dans `data/` pendant qu'un mode tourne : l'état publié ne mentirait
        jamais sur ses voies.
        """
        return list(self.spec.channels_for(self.params))

    def state(self):
        """L'état de ce mode, en dictionnaire JSON-able. Sûr depuis un autre fil."""
        return {
            "id": self.spec.id,
            "label": self.spec.label,
            "family": self.spec.family,
            "phase": self.phase,
            "published": self.published,
            "params": {k: (list(v) if isinstance(v, tuple) else v)
                       for k, v in self.params.items()},
            "instruction": self.instruction(),
            "stream": self.spec.stream,
            "channels": self.channels(),
            "rest_report": self.rest_report,
            "output": self.output(),
        }

    # --- à redéfinir dans les sous-classes -----------------------------------

    def _open(self):
        """Créer le(s) publieur(s) de ce mode."""

    def _close(self):
        """Libérer le(s) publieur(s). Laisser tomber la référence suffit : pylsl ferme l'outlet."""

    def _reset_rest(self):
        """Jeter tout ce qui a été mesuré : échantillons du plancher, décodeur, dernière sortie."""

    def _rest_step(self, engine, now):
        """Un pas de mesure du repos. True quand le plancher tient, False pour prolonger."""
        return True

    def _run_step(self, engine, lsl_ts):
        """Un pas de décodage : mesurer, décider, publier."""

    # Un mode qui écoute des marqueurs déclare `marker_epoch_s` dans son `ModeSpec` et appelle
    # `engine.markers_murs(self.spec.id, post_s)` depuis son `_run_step`. Le moteur lui rend des
    # marqueurs SITUÉS (horodatés dans la même horloge que `engine.recent_ts`) et MÛRS. Le
    # découpage reste au mode : les bornes ne sont pas les mêmes d'un paradigme à l'autre.
    #
    # ⚠️ « MÛR » NE VEUT DIRE QUE : le POST est arrivé. `markers_murs` compare l'instant du
    # marqueur + `post_s` au dernier échantillon du tampon — elle ne regarde PAS le côté PRÉ.
    # Un marqueur peut donc être mûr et son époque déjà TRONQUÉE par la tête : le tampon est
    # glissant, et une manche qui a pris du retard (un tour de boucle long, une purge) laisse
    # sortir les plus vieux échantillons. Découper rend alors `None`.
    #
    # Conséquence pour qui écrit le prochain mode à marqueurs (l'ErrP est le premier concerné) :
    # **garder la garde `if epoque is None: continue` et COMPTER ce qu'elle jette** — c'est ce
    # que fait `_epoques_perdues` dans `modes/p300.py`. La retirer en croyant la maturité
    # suffisante ne lèverait rien : le mode perdrait des époques en silence, exactement la panne
    # muette que ce produit combat. `marker_epoch_s` dimensionne le tampon pour que ce cas soit
    # RARE, il ne le rend pas impossible.


def _selftest():
    """La machine de phases, sur une horloge FABRIQUÉE. Aucun casque, aucune attente réelle."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    class _Compteur(ModeRuntime):
        """Runtime d'essai : son repos se termine au bout de 3 pas, puis il compte ses décisions."""

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.vus, self.decisions, self.remises_a_zero = 0, 0, 0

        def _reset_rest(self):
            self.remises_a_zero += 1
            self.vus = 0

        def _rest_step(self, engine, now):
            self.vus += 1
            if self.vus < 3:
                return False
            self.rest_report = {"windows": self.vus}
            return True

        def _run_step(self, engine, lsl_ts):
            self.decisions += 1

    avec_repos = ModeSpec(id="a", label="Avec repos", family="actif", summary="", status="moteur",
                          rest=Rest(warmup_s=10.0, duration_s=20.0, instruction="ne bouge pas"),
                          stream="decoded_a", channels=("x",))
    sans_repos = ModeSpec(id="b", label="Sans repos", family="brut", summary="", status="moteur",
                          stream="raw", channels=("x",))

    # 1. Un mode SANS repos décode tout de suite : rien à mesurer avant de diffuser.
    rt = _Compteur(sans_repos, {}, engine=None)
    rt.begin_rest(now=100.0)
    chk(rt.phase == "running", f"sans repos, on démarre en « running » (phase={rt.phase})")
    rt.tick(engine=None, lsl_ts=0.0, now=100.0)
    chk(rt.decisions == 1, "et il décode dès le premier tick")

    # 2. Un mode AVEC repos passe par chauffe -> repos -> décodage, dans cet ordre.
    rt = _Compteur(avec_repos, {}, engine=None)
    rt.begin_rest(now=100.0)
    chk(rt.phase == "warmup", "avec repos, on commence par la chauffe")
    chk(rt.remises_a_zero == 1, "le début de repos remet l'état du mode à zéro")

    rt.tick(None, 0.0, now=105.0)     # encore dans la chauffe (10 s)
    chk(rt.phase == "warmup" and rt.vus == 0,
        "pendant la chauffe on ne collecte RIEN (la dérive DC fausserait le plancher)")

    rt.tick(None, 0.0, now=111.0)     # chauffe finie -> repos, 1re fenêtre
    chk(rt.phase == "rest" and rt.vus == 1, f"la chauffe finie, le repos commence (vus={rt.vus})")

    rt.tick(None, 0.0, now=112.0)
    rt.tick(None, 0.0, now=113.0)     # 3e fenêtre -> le plancher tient
    chk(rt.phase == "running", f"le plancher mesuré, on décode (phase={rt.phase})")
    chk(rt.rest_report == {"windows": 3}, f"le repos laisse un compte-rendu ({rt.rest_report})")
    chk(rt.decisions == 0, "aucune décision n'a été publiée avant la fin du repos")

    rt.tick(None, 0.0, now=114.0)
    chk(rt.decisions == 1, "puis les décisions partent")

    # 3. Refaire le repos repart de zéro — indispensable après avoir touché une électrode.
    rt.begin_rest(now=200.0)
    chk(rt.phase == "warmup" and rt.remises_a_zero == 2 and rt.rest_report is None,
        "« refaire le repos » remet chauffe, état et compte-rendu à zéro")

    # 4. Les durées peuvent être RACCOURCIES (c'est ce dont les smokes ont besoin).
    rt = _Compteur(avec_repos, {}, engine=None)
    rt.begin_rest(now=0.0, warmup_s=1.0, duration_s=2.0)
    rt.tick(None, 0.0, now=1.5)
    chk(rt.phase == "rest", "une chauffe raccourcie est bien plus courte")

    print(f"[runtime] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
