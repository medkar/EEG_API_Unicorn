"""Ce qu'un mode produit, rendu selon sa FAMILLE — pas selon son identifiant.

Un mode **actif** propose des cibles et un seuil : l'utilisateur choisit, il y a une bonne
réponse. Un mode **passif** rend des indices qui divergent autour d'un repos : il n'y a rien à
choisir, et aucune bonne réponse. Les afficher pareil laisserait croire qu'un z d'engagement est
une sélection, ce qui est exactement le contresens que le contrat des flux cherche à éviter.
"""

import os
import sys

import numpy as np
from PySide6.QtWidgets import (QFormLayout, QLabel, QProgressBar, QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import NEURO_Z_SPAN, Z_MIN  # noqa: E402


class TracesView(QWidget):
    """Les 8 voies en direct. La seule vue qui lit le SIGNAL et pas une décision.

    Elle ne touche pas au tampon du moteur : `set_source` lui donne un accesseur
    (`engine.recent_window`) qui rend une COPIE. Le tampon est réécrit par le fil d'acquisition ;
    le lire depuis le fil Qt donnerait, tôt ou tard, une vue à moitié écrite.

    Les voies sont DÉCALÉES verticalement plutôt que superposées : superposées, une seule voie
    qui dérive écrase les sept autres et on ne voit plus rien — or la dérive d'une voie est
    précisément ce qu'on cherche à repérer ici.
    """

    SECONDES = 4.0
    ECART_UV = 100.0     # décalage vertical entre deux voies

    def __init__(self, ch_names):
        super().__init__()
        import pyqtgraph as pg

        self.source = None
        self.ch_names = list(ch_names)
        self.plot = pg.PlotWidget()
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.showGrid(x=True, y=False, alpha=0.2)
        self.plot.setLabel("bottom", "secondes")
        self.plot.getAxis("left").setTicks([[
            (-i * self.ECART_UV, nom) for i, nom in enumerate(self.ch_names)]])
        self.courbes = [self.plot.plot(pen=pg.mkPen(width=1)) for _ in self.ch_names]

        self.echelle = QLabel(f"signal BRUT, non filtré · une graduation = {self.ECART_UV:g} µV "
                              f"· {self.SECONDES:g} dernières secondes")
        self.echelle.setStyleSheet("color: #8a8f9c; font-size: 11px;")
        layout = QVBoxLayout(self)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.echelle)

    def set_source(self, source):
        """`source(seconds) -> (n, 8) ou None`. En pratique : `engine.recent_window`."""
        self.source = source

    def update_from(self, _mode_state):
        if self.source is None:
            return
        bloc = self.source(self.SECONDES)
        if bloc is None or len(bloc) < 2:
            return
        t = np.arange(len(bloc)) / max(len(bloc) / self.SECONDES, 1e-9)
        for i, courbe in enumerate(self.courbes):
            if i >= bloc.shape[1]:
                break
            # Centré voie par voie : l'Unicorn sort un offset DC énorme (10⁵ µV, en rampe après
            # l'ouverture de session). Sans ce centrage, les 8 courbes sortiraient de l'écran.
            voie = bloc[:, i] - float(np.median(bloc[:, i]))
            courbe.setData(t, voie - i * self.ECART_UV)


class ActiveView(QWidget):
    """Une barre par cible, plus le seuil de décision, plus la cible retenue.

    Le seuil est affiché À CÔTÉ des scores, et pas seulement la décision : c'est ce qui permet
    de dire si une non-détection vient d'un signal absent ou d'un seuil trop haut. Sans ça, une
    séance muette n'a qu'une explication apparente — « l'utilisateur fixe mal ».

    ⚠️ **La famille « actif » recouvre TROIS formes de sortie, pas une.** Chacune a sa propre
    échelle, et les confondre produit un écran qui a l'air de marcher :

    | mode | ce que la sortie porte | échelle |
    |---|---|---|
    | SSVEP | `scores`, `target_index`, `freq_hz`, **`threshold`** | z contre le repos du jour |
    | Motor Imagery | **`probas`**, `intent_index`, `label`, `threshold` | probabilité, bornée à 1 |
    | P300 | `scores`, `target_index`, `confidence`, **`n_flashes`** | log-odds moyens, SANS seuil |

    Le rendu est choisi sur une **CLÉ PRÉSENTE DANS LA SORTIE**, jamais sur l'identifiant du
    mode : la console est un client du moteur, et recopier ici une liste de modes ferait deux
    catalogues qui divergeraient au prochain mode ajouté. La question posée à la sortie est donc
    « qu'est-ce que tu déclares ? » — `probas` pour un vote de classes, `threshold` pour une
    échelle absolue avec un déclenchement, et à défaut une accumulation de preuves dont seul le
    CLASSEMENT a un sens.

    Deux pannes réelles, dans cet ordre, sont la raison d'être de cet aiguillage :

    1. **le MI** afficherait « aucune cible » en PERMANENCE, `target_index` n'existant pas dans
       sa sortie ;
    2. **le P300** tombait dans le rendu du SSVEP : `params["freqs"]` absent donnait six barres
       SANS ÉTIQUETTE, `threshold` absent retombait sur `Z_MIN`, et l'écran annonçait
       « échelle z · seuil 3 — un score au-dessus déclenche » AU-DESSUS de log-odds (qui sont
       normalement NÉGATIFS, donc toutes les barres à zéro), puis « CIBLE 3 · 0 Hz ». Aucune de
       ces quatre affirmations n'était vraie, et rien ne le disait.

    La panne n°2 est la n°1 recommencée un mode plus tard. C'est pourquoi le troisième rendu
    n'est pas branché sur `"p300"` : la prochaine sortie d'une forme inconnue doit tomber dans le
    rendu le plus PRUDENT (celui qui n'invente ni seuil ni unité), pas dans celui du SSVEP.
    """

    def __init__(self):
        super().__init__()
        self.verdict = QLabel("en attente")
        self.verdict.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.seuil = QLabel("")
        self.seuil.setStyleSheet("color: #8a8f9c;")
        self.barres = QFormLayout()
        layout = QVBoxLayout(self)
        layout.addWidget(self.verdict)
        layout.addWidget(self.seuil)
        layout.addLayout(self.barres)
        layout.addStretch(1)
        self._barres = []

    def _assure(self, n, etiquettes):
        """Exactement `n` barres : on en ajoute, et surtout on en RETIRE.

        Le retrait compte autant que l'ajout : régler moins de fréquences en cours de séance
        laisserait sinon une barre orpheline, figée sur le score d'une cible qui n'existe plus.
        """
        while len(self._barres) < n:
            barre = QProgressBar()
            barre.setRange(0, 100)
            barre.setTextVisible(False)
            self._barres.append((QLabel(""), barre))
            self.barres.addRow(self._barres[-1][0], barre)
        while len(self._barres) > n:
            self._barres.pop()
            self.barres.removeRow(self.barres.rowCount() - 1)
        for i, (etiquette, _b) in enumerate(self._barres):
            etiquette.setText(etiquettes[i] if i < len(etiquettes) else "")

    def update_from(self, mode_state):
        sortie = (mode_state or {}).get("output") or {}
        if not sortie:
            self.verdict.setText(mode_state["instruction"] if mode_state else "en attente")
            return
        # L'ordre compte, et il va du plus SPÉCIFIQUE au plus prudent. `threshold` est la clé qui
        # autorise à parler de seuil : sans elle, aucun repli sur une constante — c'est
        # exactement ce repli (`Z_MIN`) qui faisait annoncer « seuil 3 » au-dessus de log-odds.
        if "probas" in sortie:
            self._update_probas(mode_state, sortie)
        elif "threshold" in sortie:
            self._update_scores(mode_state, sortie)
        else:
            self._update_selection(mode_state, sortie)

    def _update_scores(self, mode_state, sortie):
        """SSVEP (et tout futur mode à score continu) : un score par cible, sur l'échelle z."""
        freqs = (mode_state.get("params") or {}).get("freqs") or []
        scores = sortie.get("scores") or []
        seuil = float(sortie.get("threshold", Z_MIN))
        self._assure(len(scores), [f"{f:g} Hz" for f in freqs])
        self.seuil.setText(f"échelle z · seuil {seuil:g} — un score au-dessus déclenche")

        # L'échelle du remplissage va jusqu'à 2× le seuil : une barre pleine à ras le seuil
        # laisserait croire qu'on est au maximum alors qu'on vient à peine de déclencher.
        for i, (_e, barre) in enumerate(self._barres):
            valeur = scores[i] if i < len(scores) else 0.0
            barre.setValue(int(max(0.0, min(valeur / (2 * seuil), 1.0)) * 100))

        index = sortie.get("target_index", -1)
        if sortie.get("artifact"):
            self.verdict.setText("ARTEFACT — fenêtre rejetée (mouvement ou clignement)")
        elif index < 0:
            self.verdict.setText(f"aucune cible (rien au-dessus de z={seuil:g})")
        else:
            self.verdict.setText(f"CIBLE {index} · {sortie.get('freq_hz', 0):g} Hz")

    def _update_probas(self, mode_state, sortie):
        """Motor Imagery (et tout futur mode à vote de classe) : une probabilité par classe.

        Pas d'échelle 2× ici : une probabilité est déjà bornée à 1, contrairement au z du
        SSVEP qui n'a pas de plafond naturel.

        ⚠️ **Les barres et le verdict ne décrivent pas le même instant.** Les barres montrent la
        dernière fenêtre, le verdict sort du VOTE sur les `vote_len` dernières. Il est donc
        NORMAL de les voir se contredire pendant que l'utilisateur change d'intention — d'où la
        règle affichée en toutes lettres au-dessus des barres.

        Cette règle est celle du MOTEUR, écrite avec les valeurs que le moteur publie
        (`threshold` dans la sortie, `min_votes` et `vote_len` dans les réglages) : rien n'est
        décidé ici. L'écran annonçait « la classe gagnante doit dépasser le seuil », ce qui est
        faux — le seuil filtre CHAQUE fenêtre, puis c'est le vote qui décide — et il affichait
        donc « 0,99 » à côté de « vote non conclu », sur le même écran.
        """
        params = (mode_state or {}).get("params") or {}
        probas = sortie.get("probas") or {}
        classes = list(probas.keys())
        seuil = float(sortie.get("threshold", 0.0))
        min_votes, vote_len = params.get("min_votes"), params.get("vote_len")
        vote_connu = min_votes is not None and vote_len is not None
        self._assure(len(classes), classes)
        regle = (f"puis {min_votes} fenêtres d'accord sur les {vote_len} dernières"
                 if vote_connu else "puis un vote sur les fenêtres récentes")
        self.seuil.setText(f"échelle probabilité · seuil {seuil:g} par fenêtre, {regle}")

        for i, (_e, barre) in enumerate(self._barres):
            valeur = probas.get(classes[i], 0.0) if i < len(classes) else 0.0
            barre.setValue(int(max(0.0, min(valeur, 1.0)) * 100))

        index = sortie.get("intent_index", -1)
        if index < 0:
            manque = (f"moins de {min_votes} des {vote_len} dernières fenêtres d'accord"
                      if vote_connu else "pas assez de fenêtres récentes d'accord")
            self.verdict.setText(f"— (vote non conclu : {manque})")
        else:
            # « du vote » n'est pas décoratif : le moteur publie ici la moyenne des fenêtres qui
            # ont voté pour cette classe, pas la probabilité de la dernière fenêtre affichée
            # au-dessus. Sans ce mot, les deux chiffres semblent devoir coïncider.
            self.verdict.setText(f"INTENTION {sortie.get('label', '')} "
                                 f"· confiance du vote {sortie.get('confidence', 0.0):.2f}")

    def _update_selection(self, mode_state, sortie):
        """P300 (et tout futur mode qui ACCUMULE des preuves) : un score par cible, sans seuil.

        Trois choses distinguent ce rendu de celui du SSVEP, et toutes les trois viennent de la
        sortie elle-même :

        1. **Aucun seuil.** Le moteur ne compare ces scores à rien : il prend l'argmax (la marge
           `P300_SELECT_MARGIN` porte sur l'ÉCART 1er-2e, pas sur une valeur absolue). Afficher
           un seuil ici — a fortiori le `Z_MIN` du SSVEP — inventerait une règle de décision qui
           n'existe pas.
        2. **Aucune échelle absolue.** Ce sont des log-odds moyens : non bornés, **négatifs le
           plus souvent** (une cible flashe une fois sur six, le classifieur dit « non-cible »
           presque toujours), et non comparables entre personnes ni entre manches. Une barre
           remplie « à 40 % d'un maximum » n'aurait donc aucun sens. Les barres sont **relatives
           entre elles** : la plus faible vide, la plus forte pleine — ce qui montre ce qui
           décide vraiment, l'écart entre la 1re et la 2e. La valeur chiffrée est à côté du nom,
           parce que la barre seule ne dit plus rien d'absolu.
        3. **Un échantillon par MANCHE**, pas 5 Hz. L'écran reste figé sur la dernière sélection
           entre deux manches ; c'est normal, et `n_flashes` dit sur combien d'époques elle
           repose — 48 pour une manche complète, 12 pour le plancher.
        """
        scores = list(sortie.get("scores") or [])
        n_flashes = sortie.get("n_flashes")
        index = sortie.get("target_index", -1)

        # Échelle RELATIVE, recalculée à chaque manche : c'est le classement qu'on montre, pas
        # une position sur une règle graduée. `etendue <= 0` (scores tous égaux, ou une seule
        # cible) laisse tout à mi-hauteur plutôt que de diviser par zéro ou de désigner un
        # gagnant qui n'en est pas un.
        bas, haut = (min(scores), max(scores)) if scores else (0.0, 0.0)
        etendue = haut - bas
        self._assure(len(scores), [f"cible {i} · {v:+.2f}" for i, v in enumerate(scores)])
        for i, (_e, barre) in enumerate(self._barres):
            part = 0.5 if etendue <= 0 else (scores[i] - bas) / etendue
            barre.setValue(int(max(0.0, min(part, 1.0)) * 100))

        sur = "" if n_flashes is None else f" sur {n_flashes} flash(s)"
        self.seuil.setText(f"log-odds moyens par cible{sur} · AUCUN seuil : le moteur prend "
                           f"celle qui domine. Barres relatives entre elles, pas une échelle "
                           f"absolue")

        if index < 0:
            # ⚠️ Jamais « aucune cible (rien au-dessus de z=…) » : il n'y a pas de z ici, et
            # surtout -1 n'est pas la cible 0. Cf. `no_decision_index` dans les métadonnées du
            # flux, que ce texte ne fait que rendre lisible.
            self.verdict.setText(f"— (manche non conclue{sur} : aucune cible ne s'est détachée)")
        else:
            self.verdict.setText(f"CIBLE {index}{sur} · log-odds moyens "
                                 f"{sortie.get('confidence', 0.0):+.2f}")


class PassiveView(QWidget):
    """Un indice par ligne, en ÉCART au repos. Aucune sélection, aucune bonne réponse.

    ⚠️ L'échelle est un z contre le repos du jour de CET utilisateur. `+1` veut dire « au-dessus
    de mon propre repos », pas « chargé ». Les trois indices dérivent du même calcul spectral et
    restent corrélés. C'est écrit sous les barres, pas dans une documentation que personne
    n'ouvrira : un affichage qui présenterait ça comme une mesure de fatigue mentirait.
    """

    # Au-delà de ±NEURO_Z_SPAN, la barre est pleine. La constante vient de `core/config.py`,
    # comme celle de l'appli pygame : la recopier ici ferait diverger les deux affichages le jour
    # où quelqu'un la retouche pour rendre les barres plus ou moins sensibles.
    SPAN = NEURO_Z_SPAN

    def __init__(self):
        super().__init__()
        self.etat = QLabel("en attente")
        self.barres = QFormLayout()
        self.avertissement = QLabel(
            "z contre TON repos du jour, mesuré au démarrage du mode. Ni comparable entre "
            "personnes, ni entre séances, ni absolu. À lire en TENDANCE.")
        self.avertissement.setWordWrap(True)
        self.avertissement.setStyleSheet("color: #8a8f9c; font-size: 11px;")
        layout = QVBoxLayout(self)
        layout.addWidget(self.etat)
        layout.addLayout(self.barres)
        layout.addWidget(self.avertissement)
        layout.addStretch(1)
        self._barres = {}

    def update_from(self, mode_state):
        sortie = (mode_state or {}).get("output") or {}
        # ⚠️ Correction de revue (tour 1, tâche 4) : la famille « passif » a une DEUXIÈME forme de
        # sortie, celle de l'ErrP — `{"error", "score", "threshold", "artifact"}` — qui n'a JAMAIS
        # de clé "z". Router uniquement sur "z" (comme avant ce correctif) laissait cette page
        # perpétuellement muette pour l'ErrP : ni crash ni mensonge, un SILENCE (le défaut
        # symétrique du P300 rendu comme un SSVEP dans `ActiveView`, qui LUI affirmait du faux).
        # On aiguille donc ICI AUSSI sur ce que la sortie DÉCLARE, jamais sur l'identifiant du
        # mode — même principe que `ActiveView.update_from` juste au-dessus.
        if "error" in sortie:
            self._update_errp(mode_state, sortie)
            return
        z = sortie.get("z") or {}
        if not z:
            self.etat.setText(mode_state["instruction"] if mode_state else "en attente")
            return

        # Un indice qui cesse d'être rapporté perd sa barre. Sans ça elle resterait à l'écran,
        # figée sur sa dernière valeur, sans rien pour dire qu'elle ne mesure plus rien.
        for disparu in [c for c in self._barres if c not in z]:
            self.barres.removeRow(self._barres.pop(disparu))

        for cle, valeur in z.items():
            if cle not in self._barres:
                barre = QProgressBar()
                barre.setRange(-100, 100)
                barre.setFormat("%v")
                self._barres[cle] = barre
                self.barres.addRow(QLabel(cle), barre)
            part = max(-1.0, min(float(valeur) / self.SPAN, 1.0))
            self._barres[cle].setValue(int(part * 100))

        artefacts = sortie.get("artifacts", 0)
        if sortie.get("artifact"):
            self.etat.setText(f"fenêtre rejetée ({sortie.get('reason', 'artefact')}) — "
                              f"les derniers z valides sont maintenus")
        else:
            self.etat.setText(f"{artefacts} fenêtre(s) rejetée(s) depuis le début du mode")

    def _update_errp(self, mode_state, sortie):
        """ErrP : un verdict par feedback, jamais montré comme un interrupteur propre.

        ⚠️ Ce détecteur, au réglage courant, n'attrape qu'une partie des erreurs et annule une
        part des bonnes commandes — `error=1` seul affirmerait un verdict fiable. Le score ET le
        POINT DE FONCTIONNEMENT (`tpr`/`tnr` MESURÉS, pas seulement `tnr_target` VISÉ) voyagent
        donc CÔTE À CÔTE, dans le même texte. `point_de_fonctionnement` vit dans `mode_state`
        (posé par `ErrPRuntime.state()`) et pas dans `sortie` : c'est une mesure de SESSION,
        constante d'un échantillon à l'autre, contrairement à `threshold` qui EST sur le flux.

        ⚠️ `error = -1` (pas de verdict : époque perdue ou artefact) est un texte VISUELLEMENT
        DISTINCT de `error = 0` (verdict « correct ») : les confondre affirmerait un « pas
        d'erreur » qu'on n'a pas observé. `score`/`threshold` valent alors 0.0 par CONVENTION,
        jamais une mesure (cf. `ErrPRuntime._traiter_feedback`) — on ne les affiche donc pas.
        """
        error = sortie.get("error", -1)
        if sortie.get("artifact"):
            self.etat.setText("— PAS DE VERDICT : fenêtre rejetée (artefact, σ au-dessus du repos)")
        elif error < 0:
            self.etat.setText("— PAS DE VERDICT : époque hors du tampon")
        elif error == 1:
            self.etat.setText("ERREUR détectée (score au-dessus du seuil)")
        else:
            self.etat.setText("correct (score sous le seuil)")

        if error < 0:
            self.avertissement.setText(
                "aucune mesure sur ce feedback : époque perdue ou rejetée, score et seuil ne "
                "comptent pas ici.")
            return
        score = float(sortie.get("score", 0.0))
        seuil = float(sortie.get("threshold", 0.0))
        pdf = mode_state.get("point_de_fonctionnement") or {}
        if pdf:
            self.avertissement.setText(
                f"score {score:+.3f} contre seuil {seuil:+.3f} · détecteur IMPARFAIT : garde "
                f"{pdf.get('tnr', 0.0):.0%} des bonnes commandes, attrape "
                f"{pdf.get('tpr', 0.0):.0%} des erreurs (visé {pdf.get('tnr_target', 0.0):.0%}) "
                f"— un verdict « erreur » est une pièce biaisée, pas une certitude.")
        else:
            self.avertissement.setText(f"score {score:+.3f} contre seuil {seuil:+.3f}")


def build(family, ch_names=()):
    """Le rendu qui convient à cette famille — jamais à un identifiant de mode."""
    if family == "brut":
        return TracesView(ch_names)
    return PassiveView() if family == "passif" else ActiveView()
