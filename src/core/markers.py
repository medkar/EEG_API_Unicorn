"""Recevoir des marqueurs d'une application EXTERNE — l'oreille du moteur.

Le moteur publie depuis toujours ; il ne savait pas écouter. Or trois modes sur six restent
gris dans la grille pour la même raison : ils ont besoin de savoir QUAND quelque chose s'est
produit sur l'écran de quelqu'un d'autre — l'onset d'un flash P300, l'instant où un feedback
s'affiche. Ce module est ce chaînon.

Il ne connaît AUCUN mode : il reçoit des objets JSON horodatés et les rend tels quels. Le sens
des événements appartient aux modes.

⚠️ **Résolution par le NOM, jamais par le type.** Le flux `EEG_API_Unicorn_status` que le moteur
publie lui-même est de type `Markers` : une résolution par type ferait écouter le moteur à
lui-même — il se répondrait, et rien ne le signalerait.

⚠️ **`time_correction()` n'est pas une précaution théorique.** `local_clock()` compte depuis le
démarrage de CHAQUE machine : le projet a mesuré 45 JOURS d'écart entre deux postes. Sans
correction, tous les marqueurs distants tombent hors du tampon du moteur et le mode ne décode
jamais rien — sans la moindre erreur.

⚠️ **Un inlet n'est JAMAIS valide pour toujours** : c'est la leçon centrale de ce module, et elle
a coûté quatre pannes distinctes (voir la docstring de `MarkerInlet`). Un émetteur meurt, une
application se relance, un réseau tombe — à chaque fois l'objet doit pouvoir être ABANDONNÉ et
reconstruit, jamais gardé « au cas où ».

Autotest :
    python src/core/markers.py
"""

import json
import os as _os
import sys as _sys
import time

from pylsl import IRREGULAR_RATE, StreamInfo, StreamInlet, StreamOutlet, local_clock, resolve_byprop

# `LostError` n'est PAS réexporté au niveau du paquet par pylsl 1.18 : il vit dans `pylsl.util`.
# C'est l'exception que lève un inlet `recover=False` dont l'émetteur a disparu — le signal, et
# non le silence, sur lequel repose tout le cycle de vie ci-dessous. Le repli est un SURENSEMBLE
# (`LostError` hérite de `RuntimeError`) : sur une version de pylsl qui le rangerait ailleurs, on
# lâche l'inlet un peu trop souvent, jamais trop peu — le sens du repli qu'il faut ici.
try:
    from pylsl.util import LostError
except ImportError:                      # pragma: no cover - dépend de la version de pylsl
    LostError = RuntimeError

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from core.config import use_utf8_console  # noqa: E402

# Borne du `time_correction()`, en secondes. MESURÉE, pas choisie au doigt mouillé : sur un
# émetteur VIVANT, le PREMIER appel d'un inlet neuf coûte 0,44 à 0,64 s (l'échange de
# synchronisation d'horloge doit avoir lieu), les suivants 0,000 s (liblsl garde le résultat).
# Borner à 0,2 s ferait donc échouer la connexion à un émetteur parfaitement sain — vérifié.
# 2,0 s laisse 3 à 4 fois la marge mesurée tout en bornant le pire cas à 2 s au lieu des 26 s
# mesurées quand l'émetteur meurt pendant l'appel.
TIME_CORRECTION_TIMEOUT_S = 2.0

# Longueur d'une passe de résolution. `minimum=32` fait consommer TOUT le délai à chaque appel
# (on ne trouvera jamais 32 flux), donc on avance par passes COURTES répétées plutôt que par une
# seule attente longue — le motif de `server._resolve_own`, pour la même raison.
RESOLVE_PASSE_S = 0.2


def parse_marqueur(txt):
    """Le JSON d'un marqueur en dictionnaire, ou None s'il est inexploitable.

    On exige `mode` et `event` : sans le premier on ne sait pas à qui le marqueur s'adresse,
    sans le second il n'y a rien à en faire. Tous les autres champs sont GARDÉS tels quels —
    c'est ce qui permettra d'enrichir le protocole sans casser les émetteurs déjà écrits.

    Ne lève jamais : une application cliente mal écrite ne doit pas pouvoir tuer le moteur.
    `except Exception` et non une liste de types : la promesse « ne lève jamais » n'est tenue
    que si elle couvre AUSSI ce qu'on n'a pas prévu. `json.loads` sur une charge utile mal
    encodée lève `UnicodeDecodeError`, un objet exotique lève `RecursionError` — un appelant qui
    lit la docstring ne doit pas avoir à connaître cette liste, ni à la maintenir.
    """
    try:
        d = json.loads(txt)
    except Exception:  # noqa: BLE001 - cf. docstring : « ne lève jamais » se prouve ici
        return None
    if not isinstance(d, dict):
        return None
    if not isinstance(d.get("mode"), str) or not isinstance(d.get("event"), str):
        return None
    return d


class MarkerInlet:
    """Un flux de marqueurs entrant, résolu par son NOM. Ne bloque jamais la boucle du moteur.

    Trois règles. Elles disent toutes la même chose — **un inlet n'est pas un objet valide pour
    toujours** — et chacune a été payée par une panne MESURÉE :

    1. **Il se construit atomiquement, ou pas du tout.** `self.inlet` n'est affecté qu'après
       `open_stream()` ET `time_correction()`, jamais avant. Un émetteur sans `source_id` (le
       défaut de LSL, donc celui qu'un étudiant écrira) qui meurt dans la fenêtre faisait lever
       `LostError` en ~4 s : au premier appel l'exception remontait dans la boucle du moteur et
       la TUAIT ; en re-tentative elle était attrapée, mais l'objet restait `connecte=True` avec
       `offset=0.0` — le moteur se croyait connecté et n'appliquait plus AUCUNE correction
       d'horloge, la catastrophe des 45 jours en silence total.

    2. **Il se LÂCHE dès qu'il ne sert plus** (`lache()`). `recover=False`, et non le défaut
       `recover=True` : un inlet qui « récupère » tout seul attend le retour de l'ANCIEN
       émetteur, identifié par son `source_id`, indéfiniment. Or l'émetteur de référence déclare
       le sien par PID — il ne revient donc JAMAIS. Mesuré : émetteur fermé puis relancé = 0
       marqueur pour toujours, sans une exception, sans un compteur qui bouge, et redémarrer le
       mode n'y changeait rien. Avec `recover=False`, la disparition lève `LostError` : on lâche,
       on re-résout, et les marqueurs reviennent (mesuré : 51 contre 0).

    3. **Il ne bloque jamais plus de quelques secondes.** `time_correction()` sans borne fige la
       boucle ENTIÈRE — 26 s mesurées quand l'émetteur meurt pendant l'appel, sans exception, et
       Ctrl-C ne peut pas interrompre un appel C bloquant. Pendant ce temps le tampon BrainFlow
       déborde et plus RIEN n'est publié : ni SSVEP, ni neuro, ni MI. Cela contredisait mot pour
       mot la promesse de cette ligne de docstring.

    ⚠️ **Plusieurs flux peuvent porter le même nom** — les étudiants utilisent tous le nom par
    défaut et LSL porte sur tout le réseau. On les résout donc TOUS (`minimum=32`, le motif de
    `lsl_io._autotest` et `server._resolve_own`), on en choisit un de façon déterministe, et
    surtout on le DIT : épocher sur les flashs du voisin publierait des sélections confiantes et
    fausses.
    """

    def __init__(self, nom, timeout_s=0.0):
        self.nom = str(nom)
        self.timeout_s = float(timeout_s)
        self.inlet = None
        self.offset = 0.0
        self.illisibles = 0      # marqueurs reçus mais indécodables — compté, jamais tu
        self.homonymes = 0       # flux portant CE nom à la dernière résolution réussie
        self.refus = ""          # pourquoi la dernière résolution a échoué, en clair
        self._homonymes_dits = ()   # ceux déjà signalés : on parle des CHANGEMENTS, pas à 20 Hz

    @property
    def connecte(self):
        return self.inlet is not None

    def resolve(self):
        """Cherche le flux et se connecte. True seulement si TOUT a réussi.

        Peut être rappelée : l'appli démarre parfois APRÈS le moteur, et c'est un usage normal,
        pas une erreur. Idempotente une fois connectée (elle rend True sans rien re-mesurer :
        re-mesurer `time_correction()` introduirait des SAUTS d'horodatage, bien pires qu'un
        décalage constant pour épocher).

        **Ne lève jamais** et **ne laisse jamais l'objet à moitié construit** : tout se fabrique
        dans des variables LOCALES, et `self.inlet`/`self.offset` ne sont affectés qu'à la
        dernière ligne. En cas d'échec, l'objet est exactement dans l'état où il était avant
        l'appel, `refus` dit pourquoi, et l'appelant peut simplement réessayer au tour suivant.
        """
        if self.inlet is not None:
            return True
        try:
            flux = self._cherche()
        except Exception as e:  # noqa: BLE001 - la découverte réseau ne doit pas tuer la boucle
            self.refus = f"la recherche a échoué ({type(e).__name__} : {e})"
            return False
        if not flux:
            self.refus = "aucun flux de ce nom sur le réseau"
            return False

        inlet = None
        try:
            # `recover=False` : cf. règle 2 de la docstring. C'est LE réglage qui transforme la
            # disparition d'un émetteur en ÉVÉNEMENT plutôt qu'en silence définitif.
            inlet = StreamInlet(flux[0], recover=False)
            # Obligatoire AVANT le premier pull : un inlet ne se connecte qu'à la première
            # lecture et LSL ne rejoue RIEN de ce qui précède. Sans ça, on perd les premiers
            # marqueurs, en silence — le même piège que pour le flux brut.
            inlet.open_stream(timeout=TIME_CORRECTION_TIMEOUT_S)
            # Mesuré UNE fois, à la connexion, et BORNÉ (cf. règle 3).
            offset = inlet.time_correction(timeout=TIME_CORRECTION_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001 - un émetteur qui meurt PENDANT la connexion est
            # le cas normal d'un TP, pas un incident du moteur : on referme ce qu'on a ouvert et
            # on réessaiera au tour suivant.
            if inlet is not None:
                try:
                    inlet.close_stream()
                except Exception:  # noqa: BLE001 - refermer un flux déjà mort ne doit rien lever
                    pass
            self.refus = f"connexion impossible ({type(e).__name__} : {e})"
            return False

        self.inlet, self.offset, self.refus = inlet, offset, ""
        return True

    def lache(self, raison=""):
        """ABANDONNE l'inlet courant. True s'il y en avait un. Ne lève jamais.

        Le geste que ce module n'avait pas, et sans lequel les trois autres pannes reviennent :
        garder un inlet dont l'émetteur a disparu, c'est rester MUET pour toujours tout en se
        croyant connecté. Après cet appel l'objet est de nouveau « non connecté », donc
        `resolve()` reprendra son travail au tour suivant — y compris sur un émetteur RELANCÉ,
        qui porte un `source_id` neuf.
        """
        if self.inlet is None:
            return False
        try:
            self.inlet.close_stream()
        except Exception:  # noqa: BLE001 - refermer un flux déjà mort ne doit rien lever
            pass
        self.inlet = None
        # Remis à zéro AVEC l'inlet : un offset mesuré sur l'émetteur d'avant n'a plus aucun sens
        # sur celui d'après, et le garder ferait épocher à côté sans rien dire.
        self.offset = 0.0
        self.refus = raison
        return True

    def _cherche(self):
        """Les flux qui portent ce nom, le choisi en tête. [] si aucun.

        `minimum=32` PUIS filtrage, c'est le motif de la maison (`lsl_io._autotest`,
        `server._resolve_own`) et il a été écrit pour exactement ce problème : `minimum=1` rend
        la main dès le PREMIER flux vu — pas même le premier lancé — et on ne saura jamais que
        l'autre existait. Mesuré : `minimum=32, timeout=0.2` révèle les deux en 0,2 s, là où
        `minimum=1` n'en montre qu'un.

        Le délai se dépense en passes COURTES répétées : avec `minimum=32`, chaque appel consomme
        TOUT son timeout (on ne trouvera jamais 32 flux), donc une passe unique de `timeout_s`
        ferait attendre le maximum même quand le flux est là depuis le début.
        """
        deadline = time.perf_counter() + self.timeout_s
        while True:
            passe = min(RESOLVE_PASSE_S, max(0.0, deadline - time.perf_counter()))
            flux = resolve_byprop("name", self.nom, minimum=32, timeout=passe)
            if flux:
                return self._arbitre(flux)
            if time.perf_counter() >= deadline:
                return []

    def _arbitre(self, flux):
        """Ordonne les homonymes de façon DÉTERMINISTE, et dit qu'il y en a plusieurs.

        Le tri (par `source_id`, puis `hostname`) importe autant que le message : sans lui, deux
        lancements du même moteur dans la même salle écouteraient deux émetteurs différents sans
        que rien ne l'explique. Avec, le choix est reproductible et l'étudiant peut le prévoir.

        Dit une fois PAR CHANGEMENT, pas à chaque résolution : le moteur re-résout à 20 Hz tant
        qu'il n'est pas connecté, et un avertissement répété 20 fois par seconde n'est plus un
        avertissement.
        """
        flux = sorted(flux, key=lambda f: (f.source_id() or "", f.hostname() or ""))
        self.homonymes = len(flux)
        signature = tuple((f.source_id() or "", f.hostname() or "") for f in flux)
        if len(flux) > 1 and signature != self._homonymes_dits:
            qui = ", ".join(f"« {sid or 'sans source_id'} » sur {hote or '?'}"
                            for sid, hote in signature)
            retenu = signature[0]
            print(f"[markers] ⚠️ {len(flux)} flux s'appellent « {self.nom} » sur le réseau : "
                  f"{qui}. J'écoute « {retenu[0] or 'sans source_id'} » sur {retenu[1] or '?'} "
                  f"et j'ignore le(s) autre(s) — si ce n'est pas le tien, arrête l'émetteur "
                  f"oublié ou donne un nom de flux distinct aux deux.")
        self._homonymes_dits = signature
        return flux

    def pull(self, max_n=64):
        """Les marqueurs arrivés depuis le dernier appel : [(ts_lsl_local, dict), ...].

        Horodatage ramené dans l'horloge LOCALE, la même que celle du tampon EEG du moteur.
        Rend [] si rien n'est arrivé ou si l'inlet n'est pas connecté.

        ⚠️ Si le flux a DISPARU (`LostError`), l'inlet est LÂCHÉ avant que l'exception ne
        reparte vers l'appelant : celui-ci la compte et la dit (`server._tire_marqueurs`), et le
        tour suivant re-résout tout seul. Lâcher AVANT de relancer, et pas après, est ce qui rend
        la réparation indépendante de ce que l'appelant fait de l'exception.
        """
        if self.inlet is None:
            return []
        recus = []
        for _ in range(max_n):
            try:
                txt, ts = self.inlet.pull_sample(timeout=0.0)
            except LostError:
                self.lache("le flux a disparu du réseau")
                raise
            except Exception:  # noqa: BLE001 - une charge utile qui ne se décode même pas au
                # niveau LSL (UnicodeDecodeError) est un marqueur ILLISIBLE de plus, pas un flux
                # perdu : on le compte comme tel et on continue de lire les suivants.
                self.illisibles += 1
                continue
            if txt is None:
                break
            d = parse_marqueur(txt[0])
            if d is None:
                self.illisibles += 1
                continue
            recus.append((float(ts) + self.offset, d))
        return recus


def _selftest():
    import io
    from contextlib import redirect_stdout

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # 1. Le décodage d'une charge utile, sans aucun réseau.
    chk(parse_marqueur('{"mode":"p300","event":"flash","target":3}')
        == {"mode": "p300", "event": "flash", "target": 3},
        "une charge utile valide se décode telle quelle")
    chk(parse_marqueur("pas du json") is None, "une charge utile illisible rend None, sans lever")
    chk(parse_marqueur("[1, 2, 3]") is None, "du JSON qui n'est pas un objet rend None")
    chk(parse_marqueur('{"event":"flash"}') is None,
        "un marqueur sans « mode » est refusé : on ne devine pas à qui il s'adresse")
    chk(parse_marqueur('{"mode":"p300"}') is None,
        "un marqueur sans « event » est refusé : il n'y a rien à en faire")
    # Un « mode »/« event » PRÉSENT mais du mauvais TYPE doit être refusé comme s'il était
    # absent : sinon un entier ou une liste remonterait jusqu'aux modes, qui attendent une
    # chaîne (comparaisons `mode == "p300"`, etc.).
    chk(parse_marqueur('{"mode":1,"event":"flash"}') is None,
        "un « mode » PRÉSENT mais qui n'est pas une chaîne est refusé, pas seulement un « mode » absent")
    chk(parse_marqueur('{"mode":"p300","event":2}') is None,
        "un « event » PRÉSENT mais qui n'est pas une chaîne est refusé, pareillement")
    # Les champs inconnus sont GARDÉS, pas refusés : c'est ce qui permettra d'enrichir le
    # protocole sans casser les émetteurs déjà écrits par les étudiants.
    d = parse_marqueur('{"mode":"p300","event":"flash","target":1,"inconnu":42}')
    chk(d is not None and d.get("inconnu") == 42, f"un champ inconnu est gardé, pas refusé ({d})")

    # 2. Un flux introuvable ne lève pas, et le DIT.
    inlet = MarkerInlet("EEG_API_Unicorn_flux_qui_nexiste_pas", timeout_s=0.2)
    chk(inlet.resolve() is False, "un flux introuvable rend False")
    chk(inlet.connecte is False, "et l'inlet se déclare non connecté")
    chk(inlet.pull() == [], "tirer sur un inlet non connecté rend une liste vide, sans lever")
    chk("aucun flux" in inlet.refus,
        f"...et il DIT pourquoi, en clair, plutôt que d'échouer sans motif ({inlet.refus!r})")
    chk(inlet.lache() is False, "lâcher un inlet qui n'a jamais été connecté rend False, sans lever")

    # 3. Bout en bout, sur un vrai flux LSL.
    nom = "EEG_API_Unicorn_selftest_stim"
    info = StreamInfo(nom, "Markers", 1, IRREGULAR_RATE, "string", "selftest-markers")
    outlet = StreamOutlet(info)
    try:
        inlet = MarkerInlet(nom, timeout_s=5.0)
        chk(inlet.resolve() is True, "un flux publié est trouvé PAR SON NOM")
        # resolve() est IDEMPOTENT : un second appel sur un inlet déjà connecté ne doit RIEN
        # re-mesurer. Sans la garde `if self.inlet is not None: return True`, un second appel
        # remplacerait l'inlet ET re-mesurerait time_correction() — le SAUT d'horodatage que la
        # docstring du module écarte explicitement. On le prouve avec une sentinelle : si le
        # second appel touchait à l'offset, il ne resterait pas à 999.0 par hasard.
        offset_reel = inlet.offset
        objet_avant = inlet.inlet
        inlet.offset = 999.0  # sentinelle : aucune mesure réelle ne tombe dessus par hasard
        chk(inlet.resolve() is True, "un second resolve() sur un inlet déjà connecté rend True aussi")
        chk(inlet.offset == 999.0,
            f"...sans RE-MESURER time_correction() (offset={inlet.offset}, "
            f"sentinelle 999.0 censée rester intacte)")
        chk(inlet.inlet is objet_avant,
            "...ni recréer l'inlet sous-jacent (identité de l'objet StreamInlet inchangée)")
        inlet.offset = offset_reel  # restauré : le vrai offset sert au test d'horodatage qui suit
        t0 = local_clock()
        outlet.push_sample(['{"mode":"p300","event":"flash","target":2}'], timestamp=t0)
        outlet.push_sample(['{"mode":"p300","event":"round_end"}'], timestamp=t0 + 0.1)
        outlet.push_sample(["ceci n'est pas du json"], timestamp=t0 + 0.2)
        # Attente BORNÉE DANS LE TEMPS, pas en nombre d'essais : `pull_sample(timeout=0.0)` rend
        # la main immédiatement, donc un compteur d'essais peut s'épuiser en moins d'une
        # milliseconde, avant que LSL ait eu le temps de livrer quoi que ce soit. Un test qui
        # échoue par intermittence est pire qu'un test qui échoue toujours.
        #
        # ⚠️ On attend les TROIS marqueurs (2 valides ET l'illisible), pas seulement les 2
        # valides. Attendre `len(recus) == 2` puis vérifier `illisibles == 1` juste après violait
        # l'avertissement ci-dessus : le 3e échantillon pouvait être encore EN VOL, et le test
        # échouait alors par intermittence sur son propre invariant. Les trois sont poussés dans
        # cet ordre et LSL préserve l'ordre : `illisibles >= 1` prouve donc que les trois sont
        # arrivés.
        recus, echeance = [], time.time() + 5.0
        while (len(recus) < 2 or inlet.illisibles < 1) and time.time() < echeance:
            recus.extend(inlet.pull())
            if len(recus) < 2 or inlet.illisibles < 1:
                time.sleep(0.02)
        chk(len(recus) == 2,
            f"les 2 marqueurs valides arrivent, le 3e illisible est écarté ({len(recus)})")
        chk(recus[0][1]["event"] == "flash" and recus[0][1]["target"] == 2,
            f"le premier est le flash de la cible 2 ({recus[0][1]})")
        chk(abs(recus[0][0] - t0) < 0.5,
            f"son horodatage est celui de l'émission, pas celui de la réception "
            f"(écart {recus[0][0] - t0:+.3f} s)")
        chk(recus[1][0] > recus[0][0], "et l'ordre chronologique est conservé")
        chk(inlet.illisibles == 1, f"le marqueur illisible est COMPTÉ ({inlet.illisibles})")

        # L'offset d'horloge doit être APPLIQUÉ aux horodatages rendus par pull(), pas
        # seulement mesuré puis ignoré. Émetteur et récepteur tournent ici dans le MÊME
        # processus : l'offset RÉEL vaut ~0, ce qui ne distingue pas un offset appliqué d'un
        # offset ignoré (`abs(recus[0][0] - t0) < 0.5` passe dans les deux cas). On en INJECTE
        # un invraisemblable comme vraie correction, et on vérifie qu'il ressort tel quel.
        inlet.offset = 12345.678
        t1 = local_clock()
        outlet.push_sample(['{"mode":"p300","event":"flash","target":9}'], timestamp=t1)
        marqueurs, echeance = [], time.time() + 5.0
        while not marqueurs and time.time() < echeance:
            marqueurs.extend(inlet.pull())
            if not marqueurs:
                time.sleep(0.02)
        chk(len(marqueurs) == 1, f"le marqueur du test d'offset arrive ({len(marqueurs)})")
        chk(abs(marqueurs[0][0] - (t1 + 12345.678)) < 1e-3,
            f"l'offset d'horloge est bien APPLIQUÉ aux horodatages rendus "
            f"(écart mesuré {marqueurs[0][0] - t1:+.3f} s, +12345.678 attendu)")

        # 4. LÂCHER puis RE-RÉSOUDRE : le cycle de vie complet, sur un flux qui existe toujours.
        # C'est le geste qui manquait au module, et sans lequel un émetteur relancé laisse le
        # moteur muet pour toujours. On vérifie qu'il RÉPARE (on relit ensuite) et qu'il ne
        # laisse RIEN derrière — en particulier pas l'offset d'avant, qui n'a plus de sens sur
        # l'émetteur d'après et ferait épocher à côté sans rien dire.
        chk(inlet.lache("test") is True, "lâcher un inlet CONNECTÉ rend True")
        chk(inlet.connecte is False, "...et il se redéclare non connecté")
        chk(inlet.offset == 0.0,
            f"...et l'offset de l'émetteur d'AVANT est oublié, pas gardé ({inlet.offset})")
        chk(inlet.pull() == [], "...et tirer dessus rend [] sans lever")
        chk(inlet.resolve() is True,
            "un inlet lâché se RE-RÉSOUT sur le même nom : c'est ce qui rend un émetteur "
            "relancé de nouveau audible")
        t2 = local_clock()
        outlet.push_sample(['{"mode":"p300","event":"flash","target":7}'], timestamp=t2)
        apres, echeance = [], time.time() + 5.0
        while not apres and time.time() < echeance:
            apres.extend(inlet.pull())
            if not apres:
                time.sleep(0.02)
        chk(len(apres) == 1 and apres[0][1].get("target") == 7,
            f"...et les marqueurs repassent VRAIMENT après la re-résolution ({apres})")
    finally:
        del outlet

    # 5. DEUX émetteurs du même nom : on les voit TOUS LES DEUX, on en choisit un, et on le DIT.
    # `minimum=1` en rendait un seul — pas même le premier lancé — et ne disait rien : un moteur
    # pouvait épocher sur les flashs du voisin et publier des sélections confiantes et fausses.
    nom2 = "EEG_API_Unicorn_selftest_homonymes"
    o_a = StreamOutlet(StreamInfo(nom2, "Markers", 1, IRREGULAR_RATE, "string", "selftest-aaa"))
    o_b = StreamOutlet(StreamInfo(nom2, "Markers", 1, IRREGULAR_RATE, "string", "selftest-bbb"))
    try:
        double = MarkerInlet(nom2, timeout_s=5.0)
        capture = io.StringIO()
        with redirect_stdout(capture):
            trouve = double.resolve()
        texte = capture.getvalue()
        print(texte, end="")
        chk(trouve is True, "deux flux homonymes : la résolution aboutit quand même")
        chk(double.homonymes == 2,
            f"...et les DEUX sont vus, pas seulement le premier venu ({double.homonymes})")
        chk("selftest-aaa" in texte and "selftest-bbb" in texte,
            f"...et c'est DIT, en nommant les deux émetteurs ({texte!r})")
        # Déterministe : le tri par source_id fait que deux lancements écoutent le même.
        chk("J'écoute « selftest-aaa »" in texte,
            f"...et le choix est DÉTERMINISTE (tri par source_id), pas au hasard ({texte!r})")
        double.lache()
    finally:
        del o_a, o_b

    # 6. ATOMICITÉ : une connexion qui échoue À MI-CHEMIN ne laisse pas un objet à moitié
    # construit. C'est la panne la plus sournoise du lot : avec `self.inlet` affecté AVANT
    # `time_correction()`, un émetteur qui meurt dans la fenêtre laissait `connecte=True` et
    # `offset=0.0` — le moteur se croyait connecté et n'appliquait plus aucune correction
    # d'horloge, donc TOUS les marqueurs distants tombaient hors du tampon, en silence total.
    # On injecte la panne en remplaçant `StreamInlet` le temps de l'appel : c'est le seul moyen
    # de la provoquer à volonté, sans dépendre du timing d'un émetteur qu'on tuerait.
    nom3 = "EEG_API_Unicorn_selftest_atomique"
    o_c = StreamOutlet(StreamInfo(nom3, "Markers", 1, IRREGULAR_RATE, "string", "selftest-ccc"))
    ferme = []

    class _InletQuiMeurtEnRoute:
        def __init__(self, info, recover=True):
            self.info = info

        def open_stream(self, timeout=None):
            pass

        def time_correction(self, timeout=None):
            raise RuntimeError("émetteur disparu pendant la connexion (simulé)")

        def close_stream(self):
            ferme.append(True)

    vrai_stream_inlet = globals()["StreamInlet"]
    try:
        casse = MarkerInlet(nom3, timeout_s=5.0)
        globals()["StreamInlet"] = _InletQuiMeurtEnRoute
        chk(casse.resolve() is False,
            "une connexion qui échoue à mi-chemin rend False, elle ne lève pas")
        chk(casse.connecte is False,
            "...et l'objet ne se croit PAS connecté (sinon : plus aucune correction d'horloge)")
        chk(casse.offset == 0.0, f"...et aucun offset bidon n'est retenu ({casse.offset})")
        chk("time_correction" in casse.refus or "RuntimeError" in casse.refus,
            f"...et la raison de l'échec est gardée, en clair ({casse.refus!r})")
        chk(ferme == [True],
            f"...et le flux ouvert à mi-chemin est REFERMÉ, pas abandonné ouvert ({ferme})")
        # Et la re-tentative marche : l'échec n'a rien laissé qui bloque la suite.
        globals()["StreamInlet"] = vrai_stream_inlet
        chk(casse.resolve() is True,
            "une re-tentative APRÈS un échec aboutit : l'échec n'a rien laissé de coincé")
        casse.lache()
    finally:
        globals()["StreamInlet"] = vrai_stream_inlet
        del o_c

    print(f"[markers] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
