"""Le taux d'émission du SSVEP : **combien de fois le moteur parle, et a-t-il raison quand il parle**.

Le mode SSVEP décode en continu et publie une décision cinq fois par seconde — mais rien, dans ce
flux, ne dit s'il a RAISON : personne ne sait où le regard se pose. Cette mesure le dit, parce
qu'une fenêtre DÉSIGNE la cible à fixer (`src/stimulus/ssvep.py --guide`) et publie cette
vérité-terrain sur le flux de marqueurs. Le moteur écoute, prélève **une** fenêtre par essai,
applique **exactement sa propre règle de décision**, et rend deux chiffres :

  • le **taux d'émission** — sur combien d'essais le moteur a produit une cible plutôt que rien ;
  • la **justesse à l'émission** — quand il en produit une, à quelle fréquence est-ce la bonne.

⚠️ **Ces deux chiffres se lisent ENSEMBLE, toujours.** Mesuré sur casque le 2026-07-27 : **100 % de
justesse quand le moteur émet, mais 44 % d'émission seulement**. Le second sans le premier fait
passer un régime parfaitement normal pour une panne ; le premier sans le second fait croire à un
sans-faute. Un long silence entre deux verdicts justes EST le régime normal de ce mode.

⚠️ **Cette mesure ne change RIEN au décodage : elle le fait faire par le MODE.** Le plancher de
repos passe par `SsvepRuntime._rest_step`, chaque décision par `SsvepRuntime._run_step` — le
runtime du mode lui-même (`_DecideurSSVEP`, dont seuls les messages sont coupés) : fenêtre
occipitale, CCA calée sur le plancher, seuil z, rejet d'artefact au-delà de
`ARTIFACT_SIGMA_RATIO` × le σ du repos. Un correctif futur du mode (seuil, rejet, fenêtre) est donc
mesuré ici sans une ligne à reporter.

⚠️ **Jusqu'au 2026-09-22 la règle était RÉÉCRITE ici, avec un écart** : le σ du rejet d'artefact
pris sur les **8** voies (`acq.sigma_from_block`) là où le mode le prend sur les 4 occipitales
FILTRÉES. Un clignement frontal fort faisait rejeter au test un essai que le mode décode (taux
sous-estimé) ; un artefact de nuque, dilué dans 8 voies, passait au test et pas au mode (taux
sur-estimé). L'écart avait été GARDÉ parce que les repères du 2026-07-27 (100 %/44 %) ont été
mesurés sous cette règle-là. La spec « Configurer · Entraîner · Tester » (§4, §9) tranche : un
« Tester » décide comme le produit, et la comparabilité devient une NOTE — elle est dans
`HONNETETE`, pas dans le protocole. Les chiffres de ce test ne se comparent donc plus tels quels à
ces repères.

--- LES TROIS INVARIANTS DU PROTOCOLE -----------------------------------------------------------

Ils viennent de `research/ssvep_guided.py`, le monolithe (stimulus + acquisition + analyse) que ce
module et `src/stimulus/ssvep.py` remplacent. Chacun ferme une façon de se tromper en beauté.

1. **CHAUFFE AVANT TOUT.** L'Unicorn sort un offset DC énorme et DÉRIVANT pendant des dizaines de
   secondes après l'ouverture de session (10⁵ µV en rampe, mesuré le 2026-07-27). Mesurer le
   plancher de repos là-dedans revient à étalonner sur le transitoire d'un filtre — et tout le
   reste de la séance se compare ensuite à ce plancher-là. Tenu par `warmup_s`, hérité du socle.

2. **ESSAIS ENTRELACÉS ET TIRÉS AU SORT.** Un bloc contigu par cible rend « quelle cible »
   inséparable de « quand » : la dérive d'impédance, la fatigue et l'installation des électrodes se
   confondent avec l'effet cherché. **Le c-VEP a payé ce confond 76 % de débit** (cf. README).
   Tenu côté FENÊTRE (`stimulus/ssvep.py::schedule`), qui décide de l'ordre — le moteur ne fait que
   l'apprendre par les marqueurs. Ce module ne peut donc pas le défaire, et c'est voulu.

3. **UN ESSAI = UNE DÉCISION.** C'est l'invariant que ce fichier existe pour tenir, et le seul des
   trois qui puisse se perdre ICI. Les fenêtres du moteur se CHEVAUCHENT — 1,5 s glissées toutes
   les 0,2 s — donc une fixation de 3 s en contient sept ou huit. Les compter comme sept essais
   indépendants gonfle l'effectif d'un facteur ~7 et **rétrécit l'intervalle de confiance d'un
   facteur √7**, sans rien apporter : sept fenêtres qui partagent 80 % de leurs échantillons ne
   sont pas sept observations. On archive donc la fixation ENTIÈRE, et `_decision_de_l_essai` n'en
   retient qu'UNE fenêtre — **la dernière**, celle où la réponse SSVEP est la mieux établie.
   L'effectif annoncé est le nombre d'ESSAIS.

⚠️ **Ce que cette mesure ne mesure PAS** : le trajet réseau (publication LSL, horloges, deux
machines). Il est validé séparément. Ici on isole le décodage.

Autotest :
    python src/core/modes/ssvep_mesure.py
"""

import os as _os
import sys as _sys
from dataclasses import dataclass

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
import numpy as np  # noqa: E402

from core.config import (ARTIFACT_SIGMA_RATIO, CALIB_FENETRE_ATTENTE_S,  # noqa: E402
                         CALIB_FENETRE_SILENCE_S, FILTER_MARGIN_S, MARKER_STREAM_DEFAULT,
                         SSVEP_GUIDE_CUE_S, SSVEP_GUIDE_FIX_S, SSVEP_GUIDE_GAP_S,
                         SSVEP_GUIDE_REPOS_S, SSVEP_GUIDE_TRIALS_PER_TARGET, WINDOW_S, Z_MIN,
                         use_utf8_console)
from core.i18n import tr  # noqa: E402
from core.modes.affichage import (au_dessus_du_hasard, lignes, p_hasard, pct,  # noqa: E402
                                  texte_p)
from core.modes.affichage import verifier as _verifier_affichage  # noqa: E402
from core.modes.mesure import MesureSpec  # noqa: E402
from core.modes.mesure_marqueurs import MesureMarqueurs  # noqa: E402
# La cadence de décodage du MODE, importée et jamais recopiée : c'est elle qui dit combien de
# fenêtres chevauchantes une fixation contient, donc de combien l'effectif serait gonflé si on les
# comptait. Le test s'en sert pour fabriquer un essai réaliste.
from core.modes.ssvep import SSVEP_DECODE_HZ  # noqa: E402
# Le runtime du MODE : c'est LUI qui mesure le plancher et qui décide, dans ce test (I-3).
from core.modes.ssvep import SPEC as SPEC_SSVEP  # noqa: E402
from core.modes.ssvep import SsvepRuntime  # noqa: E402
from core.p300_decoder import epoch_from_stream  # noqa: E402

# L'étiquette des fenêtres du PLANCHER de repos. Une chaîne, là où un essai porte un `Essai` :
# `_mesurer` sépare les deux sur le TYPE, ce qui rend impossible de confondre un numéro d'essai
# avec le repos par une coïncidence d'étiquette.
REPOS = "repos"


@dataclass(frozen=True)
class Essai:
    """L'étiquette d'un essai : son rang dans la séance, et la cible que l'écran a DÉSIGNÉE.

    `numero` n'est pas décoratif : c'est la clé qui regroupe les fenêtres d'un même essai, donc
    ce qui rend l'invariant « un essai = une décision » exprimable. Sans lui, `_mesurer` ne verrait
    qu'une liste de fenêtres et n'aurait plus aucun moyen de savoir lesquelles se chevauchent.
    """

    numero: int
    cible: int


def wilson(k, n, z=1.96):
    """Intervalle de confiance de Wilson à 95 % pour une proportion. Rend (bas, haut).

    Préféré à l'intervalle normal parce qu'il reste dans [0, 1] et tient debout sur de petits
    effectifs — précisément notre cas : 36 essais, dont une moitié seulement produit une décision.

    ⚠️ **L'effectif `n` doit être un nombre d'ESSAIS**, jamais de fenêtres. C'est ici que la faute
    se paierait : la largeur de l'intervalle décroît en 1/√n, donc compter sept fenêtres
    chevauchantes par essai le rétrécit d'un facteur 2,6 et fait passer un « on ne sait pas » pour
    un « c'est mesuré ».
    """
    if n <= 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    demi = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - demi), min(1.0, centre + demi)


# --- Les repères, et la phrase qui les porte ----------------------------------------------------
# Mesurés sur casque le 2026-07-27, sur UNE personne et UNE séance. Ce sont les deux chiffres
# auxquels un résultat se compare — et ils ne se citent jamais l'un sans l'autre.
REFERENCE_JUSTESSE = 1.00      # 100 % de justesse QUAND le moteur émet (0 confusion sur 36)
REFERENCE_EMISSION = 0.44      # …mais 44 % d'essais seulement produisent une décision

HONNETETE = tr("mesure.ssvep_taux.honnetete", ref_justesse=pct(REFERENCE_JUSTESSE),
               ref_emission=pct(REFERENCE_EMISSION))

BRIEFING = (
    tr("mesure.ssvep_taux.briefing.1"),
    tr("mesure.ssvep_taux.briefing.2"),
    tr("mesure.ssvep_taux.briefing.3", repos=f"{SSVEP_GUIDE_REPOS_S:.0f}"),
    tr("mesure.ssvep_taux.briefing.4"),
    tr("mesure.ssvep_taux.briefing.5"),
)


class MesureSSVEP(MesureMarqueurs):
    """Le taux d'émission, mesuré sur une séance menée par la FENÊTRE.

    La ligne du temps — chauffe, annonce, `calib_end`, les trois abandons, les compteurs, la
    cloison de vérité, l'épochage — vient ENTIÈRE de `modes/mesure_marqueurs.py`, le socle des
    mesures menées par une fenêtre. Ce qui reste ICI est la forme d'un essai SSVEP : un `cue` = une
    fixation = UNE époque, le plancher de repos échantillonné à la cadence du mode, et la règle de
    décision du mode rejouée dans `_mesurer` — pas plus tôt, puisque le plancher de repos n'est
    ajusté qu'une fois le repos entier reçu. On consigne donc l'ÉPOQUE, et on décide à la fin.

    Ce qui reste hérité, et qui est tout l'intérêt d'en hériter : `state()`, `cancel()`,
    `_terminer()`, `restant_s()`, `terminee`, le vocabulaire des phases, le refus d'écrire quoi que
    ce soit sur le disque. `src/console/mesure_page.py` est GÉNÉRIQUE : un seul champ manquant dans
    l'instantané la laisserait vide, sans lever la moindre erreur.
    """

    # Le `mode` que portent les marqueurs de la fenêtre guidée, et donc la clé sous laquelle le
    # moteur tient son curseur (`markers_murs`). C'est « ssvep » et pas l'identifiant de la mesure :
    # ces marqueurs décrivent un stimulus SSVEP, un étudiant qui lit `docs/markers.md` les cherche
    # sous ce nom-là, et le mode SSVEP lui-même ne consomme aucun marqueur — aucun vol possible.
    marker_mode_id = "ssvep"
    unite = tr("mesure.unite.essai")     # une fixation désignée = un essai = une époque
    # Un `cue` porte la cible désignée (la vérité) ET ouvre la fixation (l'unité de `trials`).
    evenement_verite, champ_verite, evenement_unite = "cue", "target", "cue"

    # Ce qu'on prélève autour de chaque `cue` : la FIXATION ENTIÈRE, plus la marge de filtre.
    # ⚠️ La fixation entière, et pas la seule fenêtre de décision, précisément pour que le choix
    # « une décision par essai » soit un CHOIX visible dans `_decision_de_l_essai` — et donc
    # testable — plutôt qu'un effet de bord de la longueur prélevée. Cette valeur dimensionne le
    # tampon du moteur (cf. `MesureRuntime.epoque_marqueur_s`).
    epoque_marqueur_s = SSVEP_GUIDE_FIX_S + FILTER_MARGIN_S

    # ⚠️ L'ancrage. L'époque se termine `SSVEP_GUIDE_FIX_S` APRÈS le `cue`, c'est-à-dire à la FIN
    # de la fixation — la fenêtre publie ce marqueur au premier flip de celle-ci. Un ancrage sur le
    # marqueur lui-même prélèverait la seconde de saccade qui le précède, où aucune réponse SSVEP
    # n'est encore établie : le taux s'effondrerait sans qu'une seule exception ne soit levée. Le
    # socle en déduit la maturité : un `cue` n'est mûr que lorsque le tampon couvre sa fixation.
    decalage_s = SSVEP_GUIDE_FIX_S

    # ⚠️ **La seule géométrie REDÉCLARÉE du socle, et voici pourquoi elle est inévitable** : le mode
    # SSVEP ne découpe aucune époque autour d'un marqueur (il décode une fenêtre glissante), donc
    # il n'y a pas de `pre_s`/`post_s` à LIRE sur son runtime. Le chemin du décodage est ailleurs,
    # et il est bien LU : `_decision_de_l_essai` garde de la fixation exactement
    # `acq.window_n + acq.margin_n` échantillons, la géométrie même d'`occipital_window`.
    @property
    def pre_s(self):
        return float(self.epoque_marqueur_s)

    @property
    def post_s(self):
        return 0.0

    def __init__(self, spec, params, engine, rng=None):
        super().__init__(spec, params, engine, rng=rng)
        self._freqs = []                 # les fréquences que l'écran AFFICHE, telles qu'annoncées
        self._refresh_hz = 0.0
        self._repos_fin_ts = None        # fin du plancher de repos, en horloge LSL
        self._dernier_repos_s = 0.0      # dernier prélèvement de repos (horloge de l'appelant)
        # L'acquisition du moteur, retenue à la construction. `_mesurer` en a besoin pour appliquer
        # EXACTEMENT le filtrage du mode (`occipital_window`) et sa définition du σ
        # (`sigma_from_block`) — or `cancel()` met `self.engine` à None, et une mesure abandonnée
        # puis relancée ne doit pas dépendre de l'ordre des deux.
        self._acq = getattr(engine, "acq", None)

    # --- ce que le socle attend --------------------------------------------------

    def duree_estimee_s(self):
        """La chauffe, plus ce que le moteur SAIT du protocole par ses constantes partagées.

        `SSVEP_GUIDE_*` vivent dans `core/config.py` justement pour ça : la fenêtre les JOUE, le
        moteur les lit pour annoncer une durée AVANT qu'on ne s'asseye. Deux copies feraient
        annoncer à l'écran une séance que la fenêtre ne tient pas.
        """
        essais = self._essais_annonces or (SSVEP_GUIDE_TRIALS_PER_TARGET * 3)
        par_essai = SSVEP_GUIDE_CUE_S + SSVEP_GUIDE_FIX_S + SSVEP_GUIDE_GAP_S
        return float(self.warmup_s) + SSVEP_GUIDE_REPOS_S + essais * par_essai

    def instruction(self):
        """Ce que la console affiche en grand. Le vrai protocole est dans l'AUTRE fenêtre, et le
        dire est le plus utile qu'on puisse faire ici : un étudiant qui cherche la consigne sur
        l'écran de la console pendant que le stimulus tourne à côté perd sa séance."""
        if self.phase == "chauffe":
            return tr("mesure.fenetre.chauffe")
        if self.phase == "essais":
            if self._essais_vus == 0:
                return tr("mesure.ssvep_taux.consigne.repos")
            return tr("mesure.ssvep_taux.consigne.essais")
        if self.phase == "mesure":
            return tr("mesure.ssvep_taux.consigne.calcul")
        return ""

    def rappel(self):
        if self.phase == "essais" and self._essais_vus == 0:
            return tr("mesure.ssvep_taux.rappel.repos")
        if self.phase == "essais":
            return tr("mesure.ssvep_taux.rappel.essais")
        return ""

    def _lire_annonce(self, marqueur):
        """Les fréquences et le rafraîchissement de `calib_start`.

        ⚠️ LES FRÉQUENCES VIENNENT DE L'ÉCRAN, jamais des réglages du mode. La fenêtre les déduit
        du rafraîchissement qu'elle MESURE : sur un écran 120 Hz elle n'affichera pas celles d'un
        60 Hz. Un moteur qui garderait les siennes corrélerait contre des sinusoïdes que personne
        ne montre, et rendrait un taux nul en accusant le montage.
        """
        freqs = marqueur.get("freqs")
        if isinstance(freqs, (list, tuple)) and freqs:
            self._freqs = [float(f) for f in freqs]
        self._refresh_hz = float(marqueur.get("refresh_hz") or 0.0)

    def _ouvrir_les_essais(self, now):
        super()._ouvrir_les_essais(now)
        self._dernier_repos_s = now

    def _pendant_les_essais(self, engine, now):
        self._echantillonne_le_repos(engine, now)

    def _echantillonne_le_repos(self, engine, now):
        """Le PLANCHER de repos, échantillonné à la cadence du mode pendant la phase « repos ».

        ⚠️ Ce n'est pas une commodité : le SSVEP décide sur z = (ρ − μ) / σ, et μ/σ sont mesurés
        ICI, cible par cible. Chaque fréquence a un fond de corrélation DIFFÉRENT au repos selon sa
        proximité au pic alpha du jour ; sans ce plancher, il n'y a pas de décision à mesurer.

        ⚠️ La borne de fin est lue dans l'horloge des MARQUEURS (`recent_ts`), pas dans `now` :
        le marqueur `repos` n'est libéré qu'une fois mûr, donc `SSVEP_GUIDE_FIX_S` après avoir été
        publié. Compter la durée du repos à partir de sa RÉCEPTION ferait mordre l'échantillonnage
        sur les premières secondes du premier essai — le moteur mesurerait alors son « fond » sur
        une fixation, et le seuil de cette cible-là deviendrait inatteignable.
        """
        if self._repos_fin_ts is None or self._essais_vus:
            return
        if not len(engine.recent_ts) or float(engine.recent_ts[-1]) >= self._repos_fin_ts:
            return
        if now - self._dernier_repos_s < 1.0 / SSVEP_DECODE_HZ:
            return
        self._dernier_repos_s = now
        bloc = engine.recent_window(self._duree_bloc_s())
        attendu = int(round(self._duree_bloc_s() * engine.acq.fs))
        if bloc is not None and len(bloc) >= attendu:
            self._enregistre.append((bloc, REPOS))

    def _duree_bloc_s(self):
        """La longueur d'un bloc de repos : la fenêtre de décision PLUS la marge de filtre.

        Lue sur l'acquisition (`window_n + margin_n`) et non recalculée depuis `WINDOW_S` : c'est
        exactement la longueur qu'`occipital_window` exige, et deux arithmétiques pour le même
        nombre finiraient par diverger d'un échantillon — donc par rendre None en silence.
        """
        acq = self._acq
        return float(acq.window_n + acq.margin_n) / float(acq.fs)

    # --- les marqueurs : la forme d'un essai SSVEP ----------------------------------

    def _encaisser_protocole(self, engine, ts, marqueur):
        """`repos` ouvre le plancher ; chaque `cue` est une fixation, prélevée ENTIÈRE.

        Le `cue` arrive ici SANS sa cible (le socle l'a retirée et la garde pour le correcteur) :
        l'époque est rangée par `_consigner`, qui l'apparie à la cible désignée. La décision,
        elle, n'est prise que dans `_mesurer`.
        """
        event = marqueur.get("event")
        if event == "repos":
            self._repos_fin_ts = float(ts) + SSVEP_GUIDE_REPOS_S
            return
        if event != "cue":
            # Un événement que ce protocole ne connaît pas est ignoré, pas refusé : le protocole
            # s'enrichira, et un moteur qui casserait au premier ajout serait inutilisable.
            return
        self.classe = tr("mesure.ssvep_taux.classe", n=self._essais_vus)
        epoque = self._prelever(engine, ts)
        if epoque is not None:
            self._consigner(epoque)

    def _etiquette_d_essai(self, verite):
        """`Essai(numéro, cible)` : le numéro regroupe les fenêtres d'un essai dans `_mesurer`."""
        return Essai(self._essais_vus, int(verite))

    # --- le calcul ---------------------------------------------------------------

    def _decision_de_l_essai(self, epoque):
        """**LA fenêtre de décision d'un essai : la DERNIÈRE de la fixation. Une seule.**

        ⚠️ C'est ici que vit l'invariant n°3, et c'est la seule ligne de ce fichier qu'on peut
        « améliorer » en cassant tout. L'époque reçue couvre la fixation ENTIÈRE : à 3 s de
        fixation et une fenêtre de 1,5 s glissée toutes les 0,2 s, elle contient sept ou huit
        fenêtres de décision valides. Les rendre TOUTES est tentant — « plus de données, intervalle
        plus serré » — et c'est faux : elles partagent 80 % de leurs échantillons, donc elles ne
        sont pas sept observations. L'effectif serait multiplié par ~7 et l'intervalle de confiance
        divisé par √7 ≈ 2,6, sans qu'aucun test de ce dépôt ne rougisse — sauf celui-ci.

        La DERNIÈRE, et pas la première ni la moyenne : la réponse SSVEP met environ une seconde à
        s'établir après la saccade, donc les premières fenêtres de la fixation contiennent une
        montée, pas un régime établi.
        """
        acq = self._acq
        besoin = acq.window_n + acq.margin_n
        return np.asarray(epoque, dtype=float)[-besoin:]

    def _mesurer(self, enregistre, fs):
        """L'adaptateur entre les MARQUEURS et le calcul : il groupe, choisit, puis délègue.

        Tout ce qui est décodage vit dans `rejouer`, partagé avec le banc d'essai. Ici il ne reste
        que ce qui appartient à une séance en direct : séparer le repos des essais, et appliquer
        l'invariant n°3.
        """
        acq = self._acq
        if acq is None:
            raise ValueError(tr("mesure.commun.sans_acquisition"))
        if not self._freqs:
            # Les fréquences viennent de l'ÉCRAN (il les déduit du rafraîchissement qu'il mesure) :
            # les deviner ici reviendrait à mesurer un décodeur que personne n'utilise.
            raise ValueError(tr("mesure.ssvep_taux.erreur.sans_frequence"))

        repos = [f for f, lab in enregistre if lab == REPOS]
        etiquetes = [(lab, f) for f, lab in enregistre if isinstance(lab, Essai)]

        # --- UNE décision par essai -----------------------------------------------------------
        # ⚠️ Le regroupement par `numero` d'abord : deux fenêtres du même essai ne sont pas deux
        # observations. C'est ce regroupement, et le `blocs[-1]` qui le suit, qui rendent
        # l'invariant EXPRIMABLE — et donc testable (cf. `_selftest`).
        par_essai = {}
        for lab, bloc in etiquetes:
            par_essai.setdefault(lab.numero, (lab.cible, []))[1].append(bloc)
        essais = [(self._decision_de_l_essai(blocs[-1]), cible)
                  for cible, blocs in (par_essai[n] for n in sorted(par_essai))]

        # ⚠️ **Les deux pertes voyagent avec le chiffre.** `n_essais` ne compte que les essais
        # RETENUS ; ceux dont l'époque a débordé du tampon disparaissent du dénominateur sans
        # laisser de trace. Ils étaient comptés et imprimés sur stdout — que la console ne montre
        # pas — donc un verdict « Sur 26 ESSAIS… » se citait ensuite comme s'il décrivait la
        # séance de 36. C'est le même geste que `n_artefacts`, qui est publié ET nommé dans la
        # phrase depuis toujours. Trouvé par la revue de branche du 2026-09-10.
        resultat = rejouer(essais, repos, self._freqs, fs, acq=acq,
                           perdus=self._epoques_perdues, chauffe=self._marqueurs_chauffe,
                           z_min=float(self.params.get("z_min", Z_MIN)))
        resultat["refresh_hz"] = self._refresh_hz
        return resultat


# --- Le calcul, PARTAGÉ avec le banc d'essai ----------------------------------------------------

class _DecideurSSVEP(SsvepRuntime):
    """Le runtime du MODE SSVEP, rejoué. Seuls `_log` (« [ssvep] CIBLE… ») et `_dire` (« décodage en
    cours sur decoded_ssvep ») sont coupés : ils feraient croire que le mode tourne et publie.
    `_rest_step`, `_run_step` et `_publish` sont hérités tels quels (vérifié par l'autotest) ; jamais
    ouvert, donc rien ne part sur le réseau."""

    def _log(self, index, scores, artifact):
        pass

    def _dire(self, texte):
        pass


class _Vue:
    """Ce que `SsvepRuntime` lit d'un moteur : `acq` (fenêtre occipitale, fs), `instance`, et
    `recent` — le bloc qu'on lui fait juger, reposé à chaque appel."""

    def __init__(self, acq):
        self.acq, self.instance, self.recent = acq, "ssvep_taux", None


def acquisition_de_reference():
    """Une `UnicornAcquisition` JAMAIS démarrée : on n'emprunte que ses filtres et sa géométrie.

    ⚠️ Elle n'ouvre aucune session — `start()` n'est jamais appelée — et ne touche donc à aucun
    casque. Ce qu'on lui prend est `occipital_window` et `sigma_from_block`, c'est-à-dire
    EXACTEMENT le chemin que le mode SSVEP emprunte en direct. Les rebâtir ailleurs créerait un
    second filtrage, qui coïnciderait le jour de son écriture et divergerait ensuite en silence —
    et c'est la seule chose qui rendrait ce module inutile, puisqu'il existe pour mesurer la règle
    du PRODUIT. C'est déjà le geste que faisait `research/ssvep_guided.analyze` ; il vit ici
    désormais, du côté du moteur, pour que le banc d'essai n'ait plus à connaître l'acquisition.

    ⚠️ **Publique, et c'est le point.** `src/research/` n'a plus le droit d'importer
    `core.acquisition` (règle vérifiée par `python src/core/server.py --smoke`), or ses analyses
    hors ligne doivent filtrer leurs fenêtres archivées EXACTEMENT comme le moteur filtre les
    siennes — sinon leurs chiffres cessent de décrire le produit. C'est ce point d'entrée-ci qui
    leur donne le bon filtrage sans leur donner le casque : `ssvep_analyze.py` s'en sert depuis le
    2026-09-09, `rejouer` et `longueur_bloc_attendue` sont publiques pour la même raison.

    ⚠️ Neuve à chaque appel, et NON mise en cache : un `BoardShim` gardé jusqu'à la fermeture de
    l'interpréteur y lève dans son `__del__` (« sys.meta_path is None »), et un étudiant lit ce
    traceback comme une panne. La construction ne fait que deux appels natifs de lecture.
    """
    from core.acquisition import UnicornAcquisition

    return UnicornAcquisition(synthetic=True)


def longueur_bloc_attendue(acq=None):
    """Le nombre d'échantillons qu'une fenêtre de décision doit porter : fenêtre PLUS marge.

    Publique pour que le banc d'essai puisse REFUSER un enregistrement pris sous d'autres
    constantes (`WINDOW_S`, `FILTER_MARGIN_S`) au lieu d'en tirer un taux. Le rejeu ne
    reproduirait alors plus la règle du moteur, et rien ne le dirait : `occipital_window` rendrait
    simplement None, chaque essai compterait comme « aucune cible », et le taux serait de 0 % —
    lu comme une panne de casque plutôt que comme un désaccord de réglages.
    """
    acq = acq or acquisition_de_reference()
    return int(acq.window_n + acq.margin_n)


def rejouer(essais, repos, freqs, fs, acq=None, perdus=0, chauffe=0, z_min=Z_MIN):
    """**La règle du moteur, rejouée sur des fenêtres — une décision par essai.** Rend le verdict.

    `essais`  : `[(fenêtre BRUTE (n, 8), indice de la cible fixée), ...]`, **une par essai**.
    `repos`   : `[fenêtre BRUTE (n, 8), ...]`, les fenêtres du plancher.
    `freqs`   : les fréquences AFFICHÉES, dans l'ordre des indices de cible.
    `perdus`  : essais JOUÉS mais absents de `essais` — leur époque a débordé du tampon.
    `chauffe` : marqueurs reçus pendant la chauffe du moteur, jetés avant la mesure.

    ⚠️ **`perdus` et `chauffe` ne changent aucun calcul : ils rendent le dénominateur HONNÊTE.**
    L'effectif reste `len(essais)`, parce qu'un essai sans époque ne peut produire aucune décision
    — mais sans ces deux nombres, une séance de 36 essais dont 10 ont débordé rend « Sur 26
    ESSAIS… », avec un intervalle calculé sur 26, et rien ne dit que 10 ont été jetés. Le chiffre
    est ensuite cité comme s'il décrivait la séance entière. Ils sont donc publiés ET nommés dans
    la phrase de verdict, exactement comme `n_artefacts`.

    ⚠️ Ils valent **0 par défaut**, et c'est ce que voit le banc d'essai : un enregistrement
    archivé ne porte pas le compte de ce que la séance a perdu au moment où elle a été prise. Un
    rejeu hors ligne dit donc « aucune perte » faute de mieux — il décrit le FICHIER, pas la
    séance.

    ⚠️ Cette fonction est le SEUL chemin de décodage de la mesure, et elle est publique pour que le
    banc d'essai (`src/research/ssvep_guided.py`) rejoue un enregistrement archivé **par le même
    code**, avec d'autres réglages, sans le réécrire. Une seconde écriture serait un second
    décodeur : les deux s'accorderaient le jour de leur écriture, puis l'un des deux serait corrigé.

    ⚠️ Elle attend **une fenêtre par essai**, déjà choisie. Le choix (la dernière de la fixation)
    appartient à l'appelant, et c'est délibéré : c'est là qu'il est visible et testable.
    """
    acq = acq or acquisition_de_reference()
    freqs = [float(f) for f in freqs]
    if not freqs:
        raise ValueError("aucune fréquence : il n'y a rien contre quoi corréler")
    if abs(float(fs) - float(acq.fs)) > 1e-6:
        raise ValueError(f"fs = {float(fs):g} Hz, mais l'acquisition qui filtre travaille à "
                         f"{float(acq.fs):g} Hz : le mode corrélerait contre des sinusoïdes à la "
                         f"mauvaise cadence")
    if len(essais) < 6:
        raise ValueError(tr("mesure.ssvep_taux.erreur.trop_peu", n=len(essais)))

    # --- Le plancher de repos, par le `_rest_step` du MODE -----------------------------------
    # Chaque bloc de repos est posé comme tampon, dans l'ordre ; l'échéance n'est atteinte qu'au
    # DERNIER, qui déclenche le calage — exactement comme en direct, où la dernière fenêtre du
    # repos est celle qui le clôt. La médiane du σ (sur la fenêtre occipitale filtrée) et la CCA
    # calée cible par cible sont celles du mode : rien n'est recalculé ici.
    vue = _Vue(acq)
    decideur = _DecideurSSVEP(SPEC_SSVEP, {"freqs": tuple(freqs), "z_min": float(z_min)}, vue)
    pret = False
    for i, bloc in enumerate(repos):
        vue.recent = bloc
        decideur._rest_until = 0.0 if i == len(repos) - 1 else float("inf")
        pret = decideur._rest_step(vue, 0.0)
    if not pret:
        # Le SSVEP décide sur z = (ρ − μ) / σ, μ et σ mesurés cible par cible pendant le repos.
        raise ValueError(tr("mesure.ssvep_taux.erreur.sans_repos", n=len(decideur._samples)))

    # --- UNE décision par essai, par le `_run_step` du MODE ------------------------------------
    # Rejet d'artefact compris : le mode prend son σ sur les 4 occipitales FILTRÉES, et c'est ce
    # σ-là qui juge ici — plus celui des 8 voies (cf. l'avertissement en tête de module).
    decisions, artefacts = [], 0
    for fenetre_brute, cible in essais:
        vue.recent = fenetre_brute
        decideur._decoded = None
        decideur._run_step(vue, 0.0)
        sortie = decideur.output()
        if sortie is None:                    # fenêtre trop courte : le mode ne publierait rien
            decisions.append((cible, None))
            continue
        if sortie["artifact"]:
            artefacts += 1
        index = int(sortie["target_index"])
        decisions.append((cible, None if index < 0 else index))

    n_essais = len(decisions)
    emis = [(cible, decide) for cible, decide in decisions if decide is not None]
    n_emis = len(emis)
    n_justes = sum(1 for cible, decide in emis if decide == cible)
    taux_emission = n_emis / n_essais
    justesse = (n_justes / n_emis) if n_emis else 0.0
    # ⚠️ L'intervalle porte sur la JUSTESSE À L'ÉMISSION, et son effectif est `n_emis` — un nombre
    # d'ESSAIS ayant produit une décision, jamais un nombre de fenêtres.
    ic_bas, ic_haut = wilson(n_justes, n_emis)
    _affichage = _lignes(len(freqs), n_essais, n_emis, justesse, taux_emission, ic_bas, ic_haut)

    return {
        "n_essais": int(n_essais),
        "n_emis": int(n_emis),
        "n_justes": int(n_justes),
        "n_artefacts": int(artefacts),
        # Les deux pertes, publiées à côté de l'effectif qu'elles qualifient. `n_artefacts` compte
        # des essais QUI SONT dans `n_essais` (ils comptent comme « aucune cible ») ; `n_perdus`
        # et `n_chauffe` comptent des essais qui n'y sont PAS. La nuance est dans le verdict.
        "n_perdus": int(perdus),
        "n_chauffe": int(chauffe),
        "n_cibles": len(freqs),
        "taux_emission": round(float(taux_emission), 3),
        "justesse_emission": round(float(justesse), 3),
        "ic_bas": round(float(ic_bas), 3),
        "ic_haut": round(float(ic_haut), 3),
        "hasard": round(1.0 / len(freqs), 3),
        "p_hasard": round(p_hasard(n_justes, n_emis, 1.0 / len(freqs)), 4),
        "freqs_hz": [round(f, 3) for f in freqs],
        "refresh_hz": 0.0,
        "fenetres_repos": len(decideur._samples),
        # Le compte-rendu du plancher, celui que le mode imprime : μ, σ et le ρ qu'il faudrait
        # atteindre, par cible. C'est lui qui dit POURQUOI une cible ne sort jamais.
        "plancher": decideur.rest_report,
        "decisions": [(int(c), None if d is None else int(d)) for c, d in decisions],
        **_affichage,
        # Le verdict s'OUVRE sur le mot affiché en face : c'est l'invariant que
        # `affichage.verifier` tient pour chaque protocole — les deux viennent du même calcul.
        "verdict": f"{_affichage['mot']} — " + verdict(
            len(freqs), n_essais, n_emis, n_justes, taux_emission, justesse, ic_bas, ic_haut,
            artefacts, perdus=perdus, chauffe=chauffe),
        "honnetete": HONNETETE,
    }


# Le seuil de « bon » pour la JUSTESSE à l'émission. Le repère du projet est 100 % (0 confusion sur
# 36) ; l'exiger à la lettre rangerait en orange une séance à 35 justes sur 36. 90 % laisse une
# confusion pour dix annonces, ce qui reste très loin du hasard à trois cibles.
JUSTESSE_MIN_BON = 0.90


def _lignes(n_cibles, n_essais, n_emis, justesse, taux, ic_bas, ic_haut):
    """Les quatre clés d'affichage (cf. `core/modes/affichage.py`). MÊMES mots que le test du MI
    (`mi_test.py`) : deux boutons « Tester » qui jugeraient avec deux vocabulaires apprendraient à
    l'étudiant que « UTILISABLE » veut dire deux choses.

    Rouge si le moteur s'est tu, ou si le test binomial EXACT ne distingue pas sa justesse du
    hasard (`affichage.au_dessus_du_hasard` — la MÊME porte que la phrase de `verdict`, et que les
    autres tests) ; vert s'il a raison presque toujours ET parle au moins aussi souvent que le
    repère du 2026-07-27 ; orange entre les deux. Wilson (`ic_bas`/`ic_haut`) reste l'intervalle
    AFFICHÉ, il ne décide plus : sa borne basse passait 1/3 dès deux annonces justes.
    """
    hasard = 1.0 / n_cibles
    # `justesse` vaut exactement n_justes / n_emis : l'arrondi rend l'entier sans perte.
    n_justes = int(round(justesse * n_emis))
    p = p_hasard(n_justes, n_emis, hasard)
    if n_emis == 0 or not au_dessus_du_hasard(n_justes, n_emis, hasard):
        niveau, mot = "faible", tr("mesure.mot.muet") if n_emis == 0 else tr("mesure.mot.faible")
    elif justesse >= JUSTESSE_MIN_BON and taux >= REFERENCE_EMISSION:
        niveau, mot = "bon", tr("mesure.mot.repere")
    else:
        niveau, mot = "moyen", tr("mesure.mot.utilisable")

    if n_emis == 0:
        chiffres = tr("mesure.ssvep_taux.chiffres.muet", n=n_essais, hasard=pct(hasard))
        reserve = tr("mesure.ssvep_taux.reserve.muet")
    else:
        chiffres = tr("mesure.ssvep_taux.chiffres", justesse=pct(justesse), hasard=pct(hasard),
                      taux=pct(taux), n=n_essais, emis=n_emis, justes=n_justes,
                      muets=n_essais - n_emis)
        if niveau == "faible":
            reserve = tr("mesure.ssvep_taux.reserve.faible", p=texte_p(p))
        elif taux < REFERENCE_EMISSION:
            reserve = tr("mesure.ssvep_taux.reserve.silencieux")
        elif niveau == "moyen":
            reserve = tr("mesure.ssvep_taux.reserve.moyen")
        else:
            reserve = tr("mesure.ssvep_taux.reserve.bon")
    # « Ta configuration tient » CONCLUT : sans ⚠ à l'écran. Toutes les autres réserves mettent en
    # garde, y compris « trop silencieux » sous un vert.
    return lignes(niveau, mot, chiffres, reserve,
                  conclusion=reserve == tr("mesure.ssvep_taux.reserve.bon"))


def verdict(n_cibles, n_essais, n_emis, n_justes, taux, justesse, ic_bas, ic_haut, artefacts,
            perdus=0, chauffe=0):
    """LA phrase. Les DEUX chiffres, toujours ensemble, et l'effectif qui les porte.

    ⚠️ `perdus` et `chauffe` sont NOMMÉS ici, pas seulement publiés. C'est toute la thèse de ce
    module : l'effectif doit être visible et honnête. `n_essais` ne compte que les essais retenus,
    donc dire « Sur 26 ESSAIS » sans dire que 10 ont été jetés laisse citer ce chiffre comme s'il
    décrivait la séance de 36 — et la phrase de verdict est la SEULE chose que la console affiche
    en entier.
    """
    hasard = 1.0 / n_cibles
    phrase = tr("mesure.ssvep_taux.verdict.base", n=n_essais, emis=n_emis, taux=pct(taux),
                justes=n_justes, justesse=pct(justesse), bas=f"{ic_bas * 100:.0f}",
                haut=f"{ic_haut * 100:.0f}", hasard=pct(hasard))
    # ⚠️ AVANT les artefacts, parce que ces deux-là qualifient l'effectif lui-même : les artefacts
    # SONT dans `n_essais` (ils y comptent comme « aucune cible »), les perdus n'y sont PAS.
    if perdus:
        phrase += tr("mesure.ssvep_taux.verdict.perdus", perdus=perdus, n=n_essais,
                     total=n_essais + perdus)
    if chauffe:
        phrase += tr("mesure.ssvep_taux.verdict.chauffe", n=chauffe)
    if artefacts:
        phrase += tr("mesure.ssvep_taux.verdict.artefacts", n=artefacts,
                     ratio=f"{ARTIFACT_SIGMA_RATIO:g}")
    if n_emis == 0:
        return phrase + tr("mesure.ssvep_taux.verdict.muet")
    # ⚠️ La MÊME porte que `_lignes` (`affichage.au_dessus_du_hasard`), jamais une seconde : la
    # phrase disait « le décodage marche » sur 2 annonces justes, au-dessus d'un mot calculé autrement.
    p = p_hasard(n_justes, n_emis, hasard)
    if not au_dessus_du_hasard(n_justes, n_emis, hasard):
        return phrase + tr("mesure.ssvep_taux.verdict.faible", justes=n_justes, emis=n_emis,
                           p=texte_p(p))
    return phrase + tr("mesure.ssvep_taux.verdict.marche", p=texte_p(p),
                       ref_justesse=pct(REFERENCE_JUSTESSE), ref_emission=pct(REFERENCE_EMISSION))


SPEC = MesureSpec(
    id="ssvep_taux",
    label=tr("mesure.ssvep_taux.label"),
    summary=tr("mesure.ssvep_taux.summary"),
    briefing=BRIEFING,
    # Les fréquences sont celles du MODE, que la console passe à la fenêtre guidée et que celle-ci
    # annonce dans `calib_start`. Le SEUIL DE DÉTECTION, lui, est le `Param` du mode — le MÊME
    # objet —, que la console pré-remplit (grisé) avec la valeur réglée sur la page SSVEP : c'est
    # le motif de tous les autres tests. Pas de « Flux de marqueurs » : un test écoute toujours
    # la fenêtre qu'il lance, sur le flux par défaut (`mesure_marqueurs.CLE_FLUX`).
    params=tuple(p for p in SPEC_SSVEP.params if p.key == "z_min"),
    runtime_cls=MesureSSVEP,
    # Pas une BARRIÈRE : c'est un chiffre à lire, pas un feu rouge. Le contrôle alpha, lui, arrête
    # la séance — sans alpha, plus rien ne veut dire quoi que ce soit. Un taux d'émission bas ne
    # dit rien de tel : à 44 % d'émission, le mode est dans son régime NORMAL.
    barriere=False,
    stimulus_id="ssvep",
)


def _selftest():
    """LE test de ce module : **un essai = une décision**, et il doit rougir si on compte les
    fenêtres.

    Aucun casque, aucune attente réelle : `tick` reçoit `now`, et le tampon EEG est fabriqué mais
    HORODATÉ, comme celui du vrai moteur.
    """
    import json

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    from core.acquisition import UnicornAcquisition
    from core.config import DATA_DIR, empreinte_dossier
    from core.modes import registry
    from core.modes.calibration import PHASES_TERMINALES
    from core.modes.mesure import PHASES

    empreinte_avant = empreinte_dossier(DATA_DIR)

    # Une acquisition JAMAIS démarrée : on ne veut que ses filtres et sa géométrie de fenêtre —
    # exactement ce que faisait `research/ssvep_guided.analyze`.
    acq = UnicornAcquisition(synthetic=True)
    FS = float(acq.fs)
    BESOIN = acq.window_n + acq.margin_n              # 625 échantillons = 2,5 s
    FREQS = [15.0, 20.0, 60.0 / 7.0]

    def _bruit(rng, n, sigma=8.0):
        return rng.normal(0.0, sigma, (n, 8))

    def _ssvep(rng, n, f_hz, gain=4.0, sigma=8.0):
        """Du bruit, plus une sinusoïde sur les seules voies occipitales. On CONNAÎT la réponse."""
        x = _bruit(rng, n, sigma)
        t = np.arange(n) / FS
        onde = gain * np.sin(2 * np.pi * f_hz * t)
        for c in (4, 5, 6, 7):
            x[:, c] += onde
        return x

    # === LE TEST : l'effectif est le nombre d'ESSAIS ==========================================
    def _mesurer_sur_essais(n_essais=24, fenetres_par_essai=7, gain=4.0, sur_trois=2, graine=0,
                            params=None):
        """Joue `_mesurer` sur `n_essais` essais, chacun assez LONG pour contenir
        `fenetres_par_essai` fenêtres de décision chevauchantes.

        ⚠️ C'est la situation RÉELLE, pas une construction de test : la fixation dure 3 s et le
        moteur décode toutes les 0,2 s, donc chaque essai contient bel et bien sept ou huit
        fenêtres valides. La seule question est combien on en COMPTE.

        `sur_trois` : combien d'essais sur trois portent réellement un SSVEP. Les autres sont du
        bruit — l'étudiant a cligné, regardé ailleurs, ou la réponse n'est pas montée. C'est le
        régime NORMAL de ce mode (44 % d'émission le 2026-07-27), et le prendre comme cas de test
        plutôt qu'un sans-faute est ce qui donne un intervalle de confiance de taille réaliste :
        à 24 essais tous justes, l'intervalle est le plus ÉTROIT qu'il puisse être, donc le cas le
        moins représentatif de ce qu'on mesure vraiment.
        """
        rng = np.random.default_rng(graine)
        pas = int(round(FS / SSVEP_DECODE_HZ))                     # 50 échantillons = 0,2 s
        longueur = BESOIN + (fenetres_par_essai - 1) * pas
        # ⚠️ Le signal est fabriqué à une longueur FIXE, puis TRONQUÉ PAR LA FIN. C'est ce qui rend
        # la comparaison entre deux `fenetres_par_essai` exacte : la dernière fenêtre — la seule
        # que la mesure doit retenir — est alors rigoureusement la même. Générer deux longueurs
        # différentes tirerait deux bruits différents, et l'écart observé ne dirait plus si c'est
        # l'effectif qui a bougé ou le tirage.
        maximum = BESOIN + 20 * pas
        rt = MesureSSVEP(SPEC, dict(params or {}), _FauxMoteur())
        rt._freqs = list(FREQS)
        enregistre = [(_bruit(rng, BESOIN), REPOS) for _ in range(40)]
        for i in range(1, n_essais + 1):
            cible = (i - 1) % len(FREQS)
            porte_un_ssvep = (i % 3) < sur_trois
            bloc = (_ssvep(rng, maximum, FREQS[cible], gain=gain) if porte_un_ssvep
                    else _bruit(rng, maximum))
            enregistre.append((bloc[-longueur:], Essai(i, cible)))
        return rt._mesurer(enregistre, FS), longueur, pas

    class _FausseAcq:
        fs = FS

    class _FauxMoteur:
        """Le strict nécessaire : l'acquisition (pour les filtres) et un tampon horodaté."""

        def __init__(self, secondes=30.0, t0=1000.0, graine=0):
            self.acq = acq
            self.t0 = t0
            self.recent_ts = np.arange(t0, t0 + secondes, 1.0 / FS)
            rng = np.random.default_rng(graine)
            self.recent = rng.normal(0.0, 8.0, (len(self.recent_ts), 8))
            self._lots = []

            def _rw(seconds):
                n = max(1, int(round(seconds * FS)))
                return np.array(self.recent[-n:], dtype=float, copy=True)

            self.recent_window = _rw

        def file(self, lot):
            self._lots.append(list(lot))

        def markers_murs(self, mode_id, post_s):
            return self._lots.pop(0) if self._lots else []

    res, longueur, pas = _mesurer_sur_essais(n_essais=24, fenetres_par_essai=7)
    fenetres_dispo = (longueur - BESOIN) // pas + 1
    chk(fenetres_dispo == 7,
        f"chaque essai contient bien {fenetres_dispo} fenêtres de décision chevauchantes — c'est "
        f"la situation réelle d'une fixation de {SSVEP_GUIDE_FIX_S:g} s décodée à "
        f"{SSVEP_DECODE_HZ:g} Hz, pas une construction de test")
    chk(res["n_essais"] == 24,
        f"l'effectif annoncé est le nombre d'ESSAIS ({res['n_essais']}), jamais celui des fenêtres "
        f"({24 * fenetres_dispo} ici) — les fenêtres se chevauchent, les compter gonfle "
        f"l'effectif d'un facteur ~{fenetres_dispo} et rétrécit l'intervalle de confiance d'autant")
    chk(res["n_emis"] <= res["n_essais"],
        f"…et le nombre d'émissions ne peut pas dépasser le nombre d'essais "
        f"({res['n_emis']} sur {res['n_essais']})")
    chk(res["ic_haut"] - res["ic_bas"] > 0.15,
        f"…et l'intervalle est LARGE comme il doit l'être à cet effectif "
        f"([{res['ic_bas']:.2f} ; {res['ic_haut']:.2f}], largeur "
        f"{res['ic_haut'] - res['ic_bas']:.2f})")
    # LE chiffre que la faute ferait gagner, calculé sur les mêmes proportions : si l'on comptait
    # les fenêtres, le même taux serait annoncé avec un intervalle 2,6 fois plus serré. C'est
    # exactement ce qu'on refuse — et sans cette ligne, « largeur > 0,15 » pourrait passer pour une
    # exigence arbitraire plutôt que pour la conséquence d'un effectif honnête.
    gonfle = wilson(res["n_justes"] * fenetres_dispo, res["n_emis"] * fenetres_dispo)
    chk((res["ic_haut"] - res["ic_bas"]) > 2.0 * (gonfle[1] - gonfle[0]),
        f"…et compter les fenêtres l'aurait rétréci d'un facteur ~√{fenetres_dispo} : "
        f"[{gonfle[0]:.2f} ; {gonfle[1]:.2f}] au lieu de "
        f"[{res['ic_bas']:.2f} ; {res['ic_haut']:.2f}] — le MÊME taux annoncé avec une précision "
        f"qu'aucune observation supplémentaire ne justifie")
    chk("44" in res["honnetete"] and "100" in res["honnetete"],
        "la phrase d'honnêteté porte les DEUX repères — 100 % de justesse à l'émission, mais "
        "44 % d'émission : le second sans le premier fait passer un silence normal pour une panne")
    chk("Ce que ce test ne dit pas" in res["honnetete"]
        and "100" in res["honnetete"].split("Ce que ce test ne dit pas")[0]
        and "44" in res["honnetete"].split("Ce que ce test ne dit pas")[0],
        "…et les deux dans la MÊME phrase, pas l'un en tête et l'autre en note de bas de page")

    # Le contrôle qui rend l'assertion précédente FALSIFIABLE : le même calcul sur des essais deux
    # fois plus longs (donc deux fois plus de fenêtres) doit rendre EXACTEMENT le même effectif.
    res_long, longueur2, _pas = _mesurer_sur_essais(n_essais=24, fenetres_par_essai=14)
    chk(res_long["n_essais"] == res["n_essais"] == 24,
        f"doubler la longueur de chaque fixation ne change PAS l'effectif ({res_long['n_essais']} "
        f"contre {res['n_essais']}) : c'est la définition même d'« un essai = une décision »")
    chk(res_long["ic_haut"] - res_long["ic_bas"] == res["ic_haut"] - res["ic_bas"],
        f"…ni la largeur de l'intervalle ([{res_long['ic_bas']:.2f} ; {res_long['ic_haut']:.2f}]) "
        f"— sinon un protocole plus long ferait « gagner » de la précision sans une observation "
        f"de plus")

    # Et le contrôle de sens : à 48 essais, l'intervalle doit RÉTRÉCIR. Sans lui, un `_mesurer`
    # qui rendrait une largeur constante passerait les deux assertions ci-dessus.
    res48, _l, _p = _mesurer_sur_essais(n_essais=48, fenetres_par_essai=7)
    chk(res48["n_essais"] == 48
        and (res48["ic_haut"] - res48["ic_bas"]) < (res["ic_haut"] - res["ic_bas"]),
        f"doubler le nombre d'ESSAIS, lui, rétrécit bien l'intervalle "
        f"({res48['ic_haut'] - res48['ic_bas']:.3f} à n=48 contre "
        f"{res['ic_haut'] - res['ic_bas']:.3f} à n=24)")

    # === La règle mesurée est celle du MODE ===================================================
    # Sur un SSVEP synthétique FORT, le moteur doit émettre et avoir raison ; sur du bruit pur, il
    # doit se TAIRE plutôt que deviner. Les deux ensemble prouvent que le seuil z est bien appliqué.
    fort, _l, _p = _mesurer_sur_essais(n_essais=24, fenetres_par_essai=7, gain=6.0, sur_trois=3)
    chk(fort["n_emis"] > 0 and fort["justesse_emission"] > 0.8,
        f"sur un SSVEP synthétique franc, le moteur émet et a raison ({fort['n_emis']} émissions, "
        f"{fort['justesse_emission'] * 100:.0f} % justes)")

    # === Le SEUIL DE DÉTECTION est un réglage, et le test le reçoit du mode (2026-09-24) ==========
    # Mêmes essais, deux seuils : un seuil bas doit annoncer PLUS de cibles qu'un seuil haut. C'est
    # la seule preuve que le réglage atteint la décision — un seuil perdu en chemin (le test qui
    # retombe sur la constante) rendrait deux résultats identiques, et tout le reste resterait vert.
    chk([p.key for p in SPEC.params] == ["z_min"] and SPEC.params[0] is SPEC_SSVEP.params[-1],
        "le test déclare le « Seuil de détection » du MODE — le même objet —, que la console "
        "pré-remplit avec la valeur réglée sur la page SSVEP")
    _bas_seuil, _l, _p = _mesurer_sur_essais(n_essais=24, fenetres_par_essai=7, params={"z_min": 1.0})
    _haut_seuil, _l, _p = _mesurer_sur_essais(n_essais=24, fenetres_par_essai=7,
                                              params={"z_min": 6.0})
    chk(_bas_seuil["n_emis"] > _haut_seuil["n_emis"],
        f"un seuil de détection plus BAS fait annoncer plus de cibles, sur les mêmes essais "
        f"({_bas_seuil['n_emis']} à z=1,0 contre {_haut_seuil['n_emis']} à z=6,0)")

    rng = np.random.default_rng(7)
    rt_bruit = MesureSSVEP(SPEC, {}, _FauxMoteur())
    rt_bruit._freqs = list(FREQS)
    enregistre_bruit = [(_bruit(rng, BESOIN), REPOS) for _ in range(40)]
    pas = int(round(FS / SSVEP_DECODE_HZ))
    for i in range(1, 25):
        enregistre_bruit.append((_bruit(rng, BESOIN + 6 * pas), Essai(i, (i - 1) % 3)))
    plat = rt_bruit._mesurer(enregistre_bruit, FS)
    chk(plat["taux_emission"] < 0.3,
        f"sur du bruit pur, le moteur se TAIT plutôt que de deviner ({plat['taux_emission'] * 100:.0f} "
        f"% d'émission) — c'est le seuil z du mode, pas un seuil écrit ici")

    # === I-3 : la DÉCISION est celle du RUNTIME DU MODE, rejet d'artefact compris ==============
    # Le test réécrivait la règle du mode, avec UN écart connu : le σ du rejet d'artefact pris sur
    # les 8 voies (`sigma_from_block`) là où le mode le prend sur les 4 occipitales FILTRÉES. Un
    # clignement frontal fort faisait rejeter au test un essai que le mode décode (taux SOUS-estimé) ;
    # un artefact de nuque sur PO7/PO8, dilué dans 8 voies, passait au test et pas au mode (taux
    # SUR-estimé). Deux fixtures, calibrées pour tomber ENTRE les deux règles, et un `SsvepRuntime`
    # qui décode EN DIRECT par son propre `tick` : le test doit rendre, essai par essai, SA décision.
    import contextlib as _ctx
    import io as _io

    from core.modes.ssvep import SPEC as _SPEC_MODE
    from core.modes.ssvep import SsvepRuntime as _SsvepRuntime

    _rng3 = np.random.default_rng(31)
    _repos3 = [_bruit(_rng3, BESOIN) for _ in range(30)]
    _essais3, _genre = [], []
    for _i in range(12):
        _cible = _i % len(FREQS)
        if _i < 6:                                            # propre
            _x, _g = _ssvep(_rng3, BESOIN, FREQS[_cible], gain=6.0), "propre"
        elif _i < 9:                                          # clignement FRONTAL (Fz/C3/Cz/C4)
            _x = _ssvep(_rng3, BESOIN, FREQS[_cible], gain=6.0)
            _x[:, :4] += _rng3.normal(0.0, 150.0, (BESOIN, 4))
            _g = "frontal"
        else:                                                 # artefact OCCIPITAL (nuque)
            _x = _bruit(_rng3, BESOIN)
            _x[:, 4:] += _rng3.normal(0.0, 45.0, (BESOIN, 4))
            _g = "occipital"
        _essais3.append((_x, _cible))
        _genre.append(_g)

    class _MoteurDirect:
        def __init__(self):
            self.acq, self.instance, self.recent = acq, "selftest", None

    _md = _MoteurDirect()
    _direct = _SsvepRuntime(_SPEC_MODE, {"freqs": tuple(FREQS)}, _md)
    _direct._log = lambda *a, **k: None
    _direct.begin_rest(now=0.0, warmup_s=0.0, duration_s=(len(_repos3) - 1) * 0.2 - 0.01)
    _t, _sorties = 0.0, []
    with _ctx.redirect_stdout(_io.StringIO()):
        for _b in _repos3:
            _md.recent = _b
            _direct.tick(_md, _t, _t)
            _t += 0.2
        for _x, _cible in _essais3:
            _md.recent = _x
            _direct.tick(_md, _t, _t)
            _t += 0.2
            _o = _direct.output()
            _sorties.append((_cible, None if _o["target_index"] < 0 else _o["target_index"],
                             bool(_o["artifact"])))
    chk(_direct.phase == "running" and len(_sorties) == 12,
        f"le mode, EN DIRECT, a mesuré son plancher sur les {len(_repos3)} fenêtres de repos puis "
        f"décodé les 12 essais ({_direct.phase})")
    chk(any(d is not None and g == "frontal" for (_c, d, _a), g in zip(_sorties, _genre))
        and any(a and g == "occipital" for (_c, _d, a), g in zip(_sorties, _genre)),
        f"…et la fixture DISCRIMINE : le mode décode des essais à clignement frontal, et rejette "
        f"des essais à artefact occipital ({[(g, d, a) for (_c, d, a), g in zip(_sorties, _genre)]})")
    chk(all(getattr(_DecideurSSVEP, m) is getattr(_SsvepRuntime, m)
            for m in ("_rest_step", "_run_step", "_publish", "_reset_rest", "_new_decoder")),
        "le décideur EST le runtime du mode : plancher, décision, rejet et publication hérités, "
        "seuls ses messages sont coupés")
    _res3 = rejouer(_essais3, _repos3, FREQS, FS, acq=acq)
    chk([(c, d) for c, d in _res3["decisions"]] == [(c, d) for c, d, _a in _sorties]
        and _res3["n_artefacts"] == sum(a for _c, _d, a in _sorties),
        f"🔴 le test décide EXACTEMENT comme le mode, essai par essai, rejet d'artefact compris — "
        f"test {[d for _c, d in _res3['decisions']]} ({_res3['n_artefacts']} artefacts), mode "
        f"{[d for _c, d, _a in _sorties]} ({sum(a for _c, _d, a in _sorties)} artefacts)")
    chk("comparable" in _res3["honnetete"] and "2026-07-27" in _res3["honnetete"],
        "…et la phrase d'honnêteté DIT que ces chiffres ne se comparent plus tels quels au "
        "100 %/44 % du 2026-07-27, pris sous l'ancienne règle (σ sur 8 voies, trio du dépôt)")

    # === Le verdict : les DEUX chiffres, et l'effectif qui les porte ==========================
    chk(f"{res['n_essais']} essais" in res["verdict"],
        f"le verdict dit l'effectif et son UNITÉ ({res['verdict'][:80]}…)")
    # Les trois lignes affichées EN FACE viennent du même calcul que ce verdict, qui s'ouvre sur le
    # mot ; les chiffres portent leur hasard (`affichage.verifier`, tenu par chaque protocole).
    chk(not _verifier_affichage(res),
        f"l'affichage du résultat est cohérent avec son verdict ({_verifier_affichage(res)})")
    # Une séance comme celle du 2026-09-22 (18 annonces sur 36, 18 justes) : AU NIVEAU DU REPÈRE.
    _seance = _lignes(3, 36, 18, 1.0, 0.5, 0.82, 1.0)
    chk(_seance["niveau"] == "bon" and "hasard 33 %" in _seance["chiffres"],
        f"18 justes sur 18 annonces, 50 % d'émission : vert, avec son hasard ({_seance})")
    # I-2 : 2 annonces, 2 justes, sur 24 essais. Wilson [34 ; 100] passe 1/3 : la porte peignait
    # ORANGE, et la phrase disait « Le décodage marche sur CETTE séance ». Le test exact : p = 0,111.
    _bas, _haut = wilson(2, 2)
    _deux = _lignes(3, 24, 2, 1.0, 2 / 24, _bas, _haut)
    _phrase = verdict(3, 24, 2, 2, 2 / 24, 1.0, _bas, _haut, 0)
    chk(_deux["niveau"] == "faible" and "Le décodage marche" not in _phrase
        and "p = 0,111" in _phrase,
        f"2/2 annonces justes : FAIBLE, et la phrase ne dit PAS que le décodage marche "
        f"({_deux['mot']} | {_phrase[-120:]!r})")
    # La porte et la phrase disent la MÊME chose, sur tout un balayage — une seule fonction.
    _accord = []
    for _n_emis in range(1, 13):
        for _n_justes in range(0, _n_emis + 1):
            _b, _h = wilson(_n_justes, _n_emis)
            _niv = _lignes(3, 24, _n_emis, _n_justes / _n_emis, _n_emis / 24, _b, _h)["niveau"]
            _ph = verdict(3, 24, _n_emis, _n_justes, _n_emis / 24, _n_justes / _n_emis, _b, _h, 0)
            _accord.append(("Le décodage marche" in _ph) == (_niv != "faible"))
    chk(all(_accord),
        f"sur {len(_accord)} couples (émis, justes), la phrase dit « marche » EXACTEMENT quand la "
        f"porte n'est pas rouge ({_accord.count(False)} désaccord(s))")
    chk(_lignes(3, 36, 0, 0.0, 0.0, 0.0, 0.0)["mot"] == "MUET",
        "un moteur qui ne dit rien est MUET, pas FAIBLE : les deux ne se corrigent pas pareil")
    chk(f"{res['taux_emission'] * 100:.0f} %" in res["verdict"]
        and f"{res['justesse_emission'] * 100:.0f} %" in res["verdict"],
        "…et les deux chiffres, jamais l'un sans l'autre")
    chk("hasard" in res["verdict"].lower(),
        f"…avec le hasard, sans lequel un taux ne veut rien dire ({res['hasard']})")

    # Une séance où rien ne sort ne doit pas se lire comme un mauvais score : c'est l'ABSENCE de
    # score, et le verdict doit le dire autrement.
    muet = verdict(3, 24, 0, 0, 0.0, 0.0, 0.0, 0.0, 0)
    chk("n'a rien annoncé" in muet and "absence de score" in muet,
        f"zéro émission se lit comme une ABSENCE de score, pas comme un mauvais score ({muet[:70]}…)")

    # === Les essais JETÉS sont DANS le résultat, et NOMMÉS dans le verdict =====================
    # ⚠️ `n_essais` ne compte que les essais RETENUS. Une séance de 36 dont 10 époques débordent le
    # tampon (moteur chargé, `calib_start` tardif) annonce « Sur 26 ESSAIS… », avec un intervalle
    # calculé sur 26 — et ce chiffre-là se cite ensuite comme s'il décrivait les 36. Les deux
    # compteurs n'existaient que sur stdout, que la console ne montre pas. Ils voyagent maintenant
    # avec le chiffre, comme `n_artefacts`.
    rt_perdu = MesureSSVEP(SPEC, {}, _FauxMoteur())
    rt_perdu._freqs = list(FREQS)
    rt_perdu._epoques_perdues = 10
    rt_perdu._marqueurs_chauffe = 4
    rng_p = np.random.default_rng(11)
    enr_perdu = [(_bruit(rng_p, BESOIN), REPOS) for _ in range(40)]
    for i in range(1, 27):                      # 26 RETENUS, sur les 36 que la séance a joués
        enr_perdu.append((_ssvep(rng_p, BESOIN, FREQS[(i - 1) % 3]), Essai(i, (i - 1) % 3)))
    res_perdu = rt_perdu._mesurer(enr_perdu, FS)
    chk(res_perdu["n_essais"] == 26 and res_perdu["n_perdus"] == 10
        and res_perdu["n_chauffe"] == 4,
        f"les essais jetés sont PUBLIÉS à côté de l'effectif qu'ils qualifient "
        f"({res_perdu['n_essais']} retenus, {res_perdu['n_perdus']} perdus, "
        f"{res_perdu['n_chauffe']} jetés à la chauffe) — comptés et imprimés ne suffit pas, la "
        f"console ne lit pas stdout")
    chk("10 essai(s) de plus ont été joués" in res_perdu["verdict"]
        and "pas les 36 que la séance a joués" in res_perdu["verdict"],
        f"…et NOMMÉS dans la phrase de verdict, avec le total qu'ils reconstituent — la phrase "
        f"est la seule chose que la console affiche en entier ({res_perdu['verdict'][80:230]}…)")
    chk("4 marqueur(s) de plus" in res_perdu["verdict"]
        and "stabilisation du casque" in res_perdu["verdict"],
        f"…les marqueurs de la chauffe aussi, et pour une raison DIFFÉRENTE des perdus : la "
        f"fenêtre a pris de l'avance sur la stabilisation ({res_perdu['verdict'][-260:-120]}…)")
    # Ce qui rend les deux assertions ci-dessus falsifiables : une phrase CONSTANTE les passerait
    # toutes les deux. Sans perte, le verdict n'en dit rien — et `res` vient d'une séance jouée
    # sans perdre une seule époque.
    chk(res["n_perdus"] == 0 and res["n_chauffe"] == 0
        and "de plus ont été joués" not in res["verdict"]
        and "stabilisation du casque" not in res["verdict"],
        f"…et une séance qui n'a RIEN perdu n'en parle pas : la phrase n'est pas un gabarit "
        f"constant ({res['n_perdus']}, {res['n_chauffe']})")

    # === Les refus, avant tout calcul ==========================================================
    rt_vide = MesureSSVEP(SPEC, {}, _FauxMoteur())
    try:
        rt_vide._mesurer([], FS)
        chk(False, "une séance sans fréquences annoncées doit être REFUSÉE")
    except ValueError as e:
        chk("aucune fréquence" in str(e),
            f"…en disant que les fréquences viennent de l'ÉCRAN ({str(e)[:60]}…)")

    rt_court = MesureSSVEP(SPEC, {}, _FauxMoteur())
    rt_court._freqs = list(FREQS)
    try:
        rt_court._mesurer([(_bruit(rng, BESOIN), Essai(1, 0))], FS)
        chk(False, "une séance de 1 essai doit être REFUSÉE")
    except ValueError as e:
        chk("pas de quoi conclure" in str(e),
            f"…en disant qu'il n'y a pas de quoi conclure ({str(e)[:60]}…)")

    rt_sans_repos = MesureSSVEP(SPEC, {}, _FauxMoteur())
    rt_sans_repos._freqs = list(FREQS)
    try:
        rt_sans_repos._mesurer(
            [(_bruit(rng, BESOIN), Essai(i, 0)) for i in range(1, 13)], FS)
        chk(False, "une séance sans plancher de repos doit être REFUSÉE")
    except ValueError as e:
        chk("plancher de repos" in str(e) and "z" in str(e),
            f"…en disant que le SSVEP décide sur z et que le plancher lui manque ({str(e)[:70]}…)")

    # === La ligne du temps, menée par la FENÊTRE ==============================================
    def marqueur(event, **champs):
        return {"mode": "ssvep", "event": event, **champs}

    moteur = _FauxMoteur(secondes=40.0)
    rt = MesureSSVEP(SPEC, {}, moteur)
    t0 = moteur.t0
    rt.tick(moteur, t0)
    chk(rt.phase == "chauffe" and rt.state(now=t0)["restant_s"] > 14.0,
        f"on commence par la chauffe, et elle se décompte à l'écran ({rt.phase}, "
        f"{rt.state(now=t0)['restant_s']} s)")

    # L'annonce ARRIVE PENDANT la chauffe — le cas normal : la console lance la fenêtre au moment
    # même où elle demande la mesure.
    moteur.file([(t0 + 1.0, marqueur("calib_start", trials=6, freqs=FREQS, refresh_hz=60.0)),
                 (t0 + 1.5, marqueur("cue", target=0))])
    rt.tick(moteur, t0 + 2.0)
    chk(rt.phase == "chauffe" and rt.total() == 6 and rt._freqs == FREQS,
        f"l'annonce reçue pendant la chauffe est RETENUE, fréquences comprises ({rt.total()} "
        f"essais, {rt._freqs})")
    chk(rt.essai == 0 and rt._marqueurs_chauffe == 1,
        f"…mais les essais de cette période sont JETÉS et comptés : l'offset DC dérive encore "
        f"({rt.essai} enregistré(s), {rt._marqueurs_chauffe} jeté(s))")

    rt.tick(moteur, t0 + rt.warmup_s + 0.1)
    chk(rt.phase == "essais", f"la chauffe écoulée ouvre les essais ({rt.phase})")

    # Le REPOS, puis les essais. ⚠️ L'horodatage du `repos` est choisi pour que la fin de la phase
    # (`ts + SSVEP_GUIDE_REPOS_S`) tombe APRÈS le dernier échantillon du tampon fabriqué : c'est
    # l'état d'un repos EN COURS, le seul pendant lequel le plancher s'échantillonne. Le tampon de
    # ce faux moteur est figé sur 30 s, il ne « coule » pas comme celui du vrai.
    moteur.file([(t0 + 32.0, marqueur("repos"))])
    rt.tick(moteur, t0 + rt.warmup_s + 0.2)
    chk(rt._repos_fin_ts == t0 + 32.0 + SSVEP_GUIDE_REPOS_S,
        f"le `repos` fixe la fin du plancher dans l'horloge des MARQUEURS ({rt._repos_fin_ts}) — "
        f"la compter depuis sa RÉCEPTION la ferait mordre sur le premier essai")
    avant_repos = len(rt._enregistre)
    for i in range(1, 20):
        rt.tick(moteur, t0 + rt.warmup_s + 0.2 + 0.25 * i)
    chk(len(rt._enregistre) - avant_repos >= 10 and rt.essai == 0,
        f"le plancher s'échantillonne à la cadence du mode pendant le repos, et ce ne sont PAS des "
        f"essais ({len(rt._enregistre) - avant_repos} fenêtres de repos, {rt.essai} essais)")

    instants = [t0 + 6.0 + 5.0 * i for i in range(6)]
    moteur.file([(ts, marqueur("cue", target=i % 3)) for i, ts in enumerate(instants)])
    rt.tick(moteur, t0 + rt.warmup_s + 6.0)
    chk(rt.essai == 6 and rt.total() == 6,
        f"les six essais annoncés sont enregistrés ({rt.essai}/{rt.total()})")
    etiquettes = [lab for _f, lab in rt._enregistre if isinstance(lab, Essai)]
    chk([lab.cible for lab in etiquettes] == [i % 3 for i in range(6)],
        f"…étiquetés par la cible que l'écran a DÉSIGNÉE ({[lab.cible for lab in etiquettes]})")
    chk(all(len(f) == int(round(rt.epoque_marqueur_s * FS))
            for f, lab in rt._enregistre if isinstance(lab, Essai)),
        f"…et chaque époque couvre la FIXATION ENTIÈRE plus la marge de filtre "
        f"({rt.epoque_marqueur_s:g} s), pas la seule fenêtre de décision")

    # ⚠️ L'ANCRAGE : l'époque se termine à la FIN de la fixation, donc `SSVEP_GUIDE_FIX_S` APRÈS le
    # marqueur. Vérifié sur le tampon HORODATÉ, en comparant à l'appel de référence.
    attendu = epoch_from_stream(moteur.recent, moteur.recent_ts,
                                instants[0] + SSVEP_GUIDE_FIX_S, FS,
                                pre_s=rt.epoque_marqueur_s, post_s=0.0)
    premiere = next(f for f, lab in rt._enregistre if isinstance(lab, Essai) and lab.numero == 1)
    chk(attendu is not None and np.abs(np.asarray(premiere) - attendu).max() == 0,
        "l'époque est ancrée à la FIN de la fixation (cue + SSVEP_GUIDE_FIX_S) — ancrée sur le "
        "marqueur lui-même, elle prélèverait la saccade, où aucune réponse SSVEP n'est établie")

    moteur.file([(t0 + 20.0, marqueur("calib_end"))])
    rt.tick(moteur, t0 + rt.warmup_s + 7.0)
    chk(rt.phase == "mesure" and rt.resultat is None,
        f"`calib_end` ouvre le calcul mais ne l'exécute PAS dans le même tour : la console doit "
        f"pouvoir peindre « Calcul… » avant que la boucle ne bloque ({rt.phase})")
    rt.tick(moteur, t0 + rt.warmup_s + 7.1)
    chk(rt.phase == "fini" and rt.resultat and rt.resultat["n_essais"] == 6,
        f"le tour suivant calcule, sur les 6 ESSAIS ({rt.phase}, "
        f"{(rt.resultat or {}).get('n_essais')})")

    # === Les deux abandons ====================================================================
    moteur1 = _FauxMoteur()
    rt1 = MesureSSVEP(SPEC, {}, moteur1)
    rt1.tick(moteur1, moteur1.t0)
    rt1.tick(moteur1, moteur1.t0 + CALIB_FENETRE_ATTENTE_S - 1.0)
    chk(rt1.phase == "chauffe", f"avant le délai, la mesure attend encore la fenêtre ({rt1.phase})")
    rt1.tick(moteur1, moteur1.t0 + CALIB_FENETRE_ATTENTE_S + 1.0)
    chk(rt1.phase == "annule" and rt1.resultat is None
        and "fenêtre" in rt1.probleme and MARKER_STREAM_DEFAULT in rt1.probleme,
        f"sans `calib_start`, la mesure s'annule en disant les DEUX causes possibles : pas "
        f"lancée, ou publiant sous un autre nom ({rt1.probleme[:70]}…)")

    moteur2 = _FauxMoteur()
    rt2 = MesureSSVEP(SPEC, {}, moteur2)
    rt2.tick(moteur2, moteur2.t0)
    rt2.encaisser(moteur2, moteur2.t0, marqueur("calib_start", trials=10, freqs=FREQS))
    rt2.tick(moteur2, moteur2.t0 + rt2.warmup_s + 0.1)
    t2 = moteur2.t0 + rt2.warmup_s + 0.1
    moteur2.file([(moteur2.t0 + 5.0, marqueur("cue", target=0))])
    rt2.tick(moteur2, t2 + 1.0)
    chk(rt2.phase == "essais" and rt2.essai == 1,
        f"un marqueur arrive : la séance vit et compte son essai ({rt2.phase}, {rt2.essai})")
    rt2.tick(moteur2, t2 + 1.0 + CALIB_FENETRE_SILENCE_S - 0.5)
    chk(rt2.phase == "essais",
        f"un silence PLUS COURT que le seuil ne tue rien — le repos entre deux essais est normal "
        f"({rt2.phase})")
    rt2.tick(moteur2, t2 + 1.0 + CALIB_FENETRE_SILENCE_S + 0.5)
    chk(rt2.phase == "annule" and rt2.resultat is None and rt2._enregistre == [],
        f"au-delà du seuil, la fenêtre est réputée morte : la séance s'annule SANS calculer, et "
        f"les fenêtres déjà prélevées sont libérées ({rt2.phase}, {len(rt2._enregistre)})")

    # Le pendant : tous les essais annoncés SONT arrivés, seul `calib_end` manque. Ce n'est pas une
    # fenêtre morte — jeter la séance détruirait quatre minutes de signal bon.
    moteur3 = _FauxMoteur()
    rt3 = MesureSSVEP(SPEC, {}, moteur3)
    rt3.tick(moteur3, moteur3.t0)
    rt3.encaisser(moteur3, moteur3.t0, marqueur("calib_start", trials=1, freqs=FREQS))
    rt3.tick(moteur3, moteur3.t0 + rt3.warmup_s + 0.1)
    t3 = moteur3.t0 + rt3.warmup_s + 0.1
    moteur3.file([(moteur3.t0 + 5.0, marqueur("cue", target=1))])
    rt3.tick(moteur3, t3 + 1.0)
    rt3.tick(moteur3, t3 + 1.0 + CALIB_FENETRE_SILENCE_S + 0.5)
    chk(rt3.essai == 1 and rt3.phase == "essais",
        f"tous les essais annoncés reçus, `calib_end` manquant : la séance ATTEND au lieu de "
        f"jeter ({rt3.phase}, {rt3.essai}/{rt3.total()})")

    # === LE test qui SÉPARE les deux compteurs ================================================
    # ⚠️ `self.essai` et `self._essais_vus` coïncident tant qu'aucune époque n'est perdue — c'est
    # pour ça que le cas ci-dessus (rt3) reste vert quel que soit celui des deux qu'on compare, et
    # c'est pour ça que le défaut avait survécu à la revue. Ici on en perd UNE, ce qui suffit à
    # les séparer : la garde doit continuer d'ATTENDRE, parce que la fenêtre a bel et bien joué
    # tous les essais qu'elle avait annoncés. Comparer `self.essai` au nombre annoncé fait
    # abandonner, donc appeler `cancel()`, donc DÉTRUIRE les onze essais valides — 3,6 min de
    # signal bon jetées pour une seule époque manquée et un `calib_end` perdu.
    moteur4 = _FauxMoteur()
    rt4 = MesureSSVEP(SPEC, {}, moteur4)
    rt4.tick(moteur4, moteur4.t0)
    rt4.encaisser(moteur4, moteur4.t0, marqueur("calib_start", trials=12, freqs=FREQS))
    rt4.tick(moteur4, moteur4.t0 + rt4.warmup_s + 0.1)
    t4 = moteur4.t0 + rt4.warmup_s + 0.1
    # Onze `cue` prélevables, plus UN — au milieu, pas au bord — dont l'EEG précède le début du
    # tampon : `epoch_from_stream` rend None et l'essai est perdu. C'est ce que produit un tour de
    # boucle ralenti, ou un `calib_start` reçu tard.
    lot4 = [(moteur4.t0 + 4.0 + 1.5 * i, marqueur("cue", target=i % 3)) for i in range(11)]
    lot4.insert(5, (moteur4.t0 + 0.5, marqueur("cue", target=2)))   # EEG hors du tampon
    moteur4.file(lot4)
    rt4.tick(moteur4, t4 + 1.0)
    chk(rt4._essais_vus == 12 and rt4.essai == 11 and rt4._epoques_perdues == 1,
        f"les DEUX compteurs divergent dès la première époque perdue : {rt4._essais_vus} `cue` "
        f"lisibles reçus, {rt4.essai} époque(s) prélevée(s), {rt4._epoques_perdues} perdue(s) — "
        f"c'est `_essais_vus` qui se compare au `trials` annoncé, jamais `essai`")
    rt4.tick(moteur4, t4 + 1.0 + CALIB_FENETRE_SILENCE_S + 0.5)
    chk(rt4.phase == "essais" and rt4.resultat is None and len(rt4._enregistre) == 11,
        f"…et une époque perdue ne transforme PAS une séance complète en fenêtre morte : la "
        f"séance ATTEND son `calib_end` et ses {len(rt4._enregistre)} essais valides sont INTACTS "
        f"({rt4.phase}, {rt4.essai}/{rt4.total()}). Comparer `self.essai` au nombre annoncé "
        f"abandonnerait ici, et `cancel()` détruirait les 11")
    # Le contrôle de sens, sans lequel « la séance attend » passerait en rendant la garde muette :
    # à un `cue` de moins, la fenêtre n'a PAS fini, et le silence doit bien tuer la séance.
    moteur5 = _FauxMoteur()
    rt5 = MesureSSVEP(SPEC, {}, moteur5)
    rt5.tick(moteur5, moteur5.t0)
    rt5.encaisser(moteur5, moteur5.t0, marqueur("calib_start", trials=12, freqs=FREQS))
    rt5.tick(moteur5, moteur5.t0 + rt5.warmup_s + 0.1)
    t5 = moteur5.t0 + rt5.warmup_s + 0.1
    moteur5.file(lot4[:-1])                     # 11 `cue` sur les 12 annoncés
    rt5.tick(moteur5, t5 + 1.0)
    rt5.tick(moteur5, t5 + 1.0 + CALIB_FENETRE_SILENCE_S + 0.5)
    chk(rt5._essais_vus == 11 and rt5.phase == "annule" and rt5._enregistre == [],
        f"…mais un essai annoncé qui n'est JAMAIS arrivé reste une fenêtre morte : la séance "
        f"s'annule ({rt5._essais_vus}/{rt5.total()} reçus, {rt5.phase}) — sinon la garde "
        f"attendrait pour toujours, et « elle attend » se lirait comme « elle a fini »")

    # === Le contrat public ====================================================================
    lus_par_la_console = {"mode_id", "phase", "etape", "classe", "instruction", "rappel",
                          "essai", "total", "unite", "restant_s", "duree_estimee_s", "resultat",
                          "probleme"}
    etat = rt.state(now=t0 + 40.0)
    chk(etat.get("unite") == "essai",
        f"l'avancement affiché compte des ESSAIS, pas des « fenêtres prélevées » "
        f"({etat.get('unite')!r})")
    chk(set(etat) >= lus_par_la_console,
        f"l'instantané porte tout ce qu'un écran de protocole lit "
        f"({sorted(lus_par_la_console - set(etat)) or 'aucun champ manquant'})")
    try:
        json.dumps(etat)
        serialisable = True
    except (TypeError, ValueError):
        serialisable = False
    chk(serialisable, "l'instantané est sérialisable en JSON — il part dans `snapshot()`")
    chk(etat["phase"] in PHASES and rt2.phase in PHASES_TERMINALES,
        f"les phases sont celles du vocabulaire PUBLIC de `modes/mesure.py` ({etat['phase']})")
    chk(etat["etape"] == "",
        f"`etape` reste VIDE : la console joue un top au front montant de `etape`, et cette "
        f"mesure ne doit pas biper par-dessus un stimulus visuel ({etat['etape']!r})")

    # === C2 : un TEST écoute le flux PAR DÉFAUT, et n'offre pas d'en choisir un autre ============
    # « Tester » lance TOUJOURS notre fenêtre, qui publie sur `MARKER_STREAM_DEFAULT`. Un test qui
    # héritait le « Flux de marqueurs » du mode (réglé sur l'appli de l'étudiant) écoutait un flux
    # où personne ne publiait : abandon à 30 s, fenêtre plein écran jouant dans le vide.
    from core.config import MARKER_STREAM_DEFAULT as _DEFAUT
    from core.modes.contract import validate as _valider
    from core.server import EngineServer as _Moteur_
    chk("stream_in" not in {p.key for p in SPEC.params},
        f"le test ne déclare PAS « Flux de marqueurs » ({[p.key for p in SPEC.params]})")
    _v, _raison = _valider(SPEC, {"stream_in": "MonAppli_SSVEP"})
    chk(_v is None and "stream_in" in (_raison or ""),
        f"…et le contrat REFUSE qu'on le lui passe : brancher une appli, c'est « Connecter » "
        f"({_raison})")
    chk(_Moteur_._flux_attendu(rt) == _DEFAUT,
        f"le moteur écoute, pour ce test, le flux PAR DÉFAUT — celui de la fenêtre qu'il lance "
        f"({_Moteur_._flux_attendu(rt)})")
    chk(SPEC.stimulus_id == "ssvep" and SPEC.barriere is False,
        f"la mesure DÉCLARE sa fenêtre et n'est PAS une barrière : un taux d'émission bas est le "
        f"régime normal de ce mode, pas un feu rouge ({SPEC.stimulus_id}, {SPEC.barriere})")
    _ids = [s.id for s in registry.MESURES]
    # La PROPRIÉTÉ, pas la liste : la barrière alpha d'abord, cette mesure après. Une liste figée
    # rougissait dès qu'une mesure de test s'ajoutait au registre (le MI, le 2026-09-22), sans que
    # rien de ce que ce test protège n'ait changé.
    chk(_ids[:1] == ["alpha"] and "ssvep_taux" in _ids
        and _ids.index("ssvep_taux") > _ids.index("alpha"),
        f"…et elle est dans le catalogue du moteur, APRÈS la barrière alpha, qui se fait en "
        f"premier ({[s.id for s in registry.MESURES]})")
    sain, defauts = registry.check()
    chk(sain and not defauts, f"le registre reste sain avec elle ({defauts})")

    # Le tampon du moteur doit couvrir l'époque de cette mesure. Assertion DIRECTE sur `keep` :
    # observer qu'une époque « sort » ne prouve rien — un tampon sous-dimensionné rend quand même
    # ce qu'on lui demande, juste plus court.
    from core.server import EngineServer

    srv = EngineServer(synthetic=True, modes=(), instance="selftest-ssvep-mesure")
    try:
        chk(srv.keep >= int(round(MesureSSVEP.epoque_marqueur_s * srv.acq.fs)) + srv.acq.margin_n,
            f"le tampon du moteur couvre l'époque de cette mesure ({srv.keep} échantillons pour "
            f"{int(round(MesureSSVEP.epoque_marqueur_s * srv.acq.fs))} + "
            f"{srv.acq.margin_n} de marge) — sans ce terme NOMMÉ dans `keep`, chaque époque serait "
            f"tronquée en silence le jour où la calibration MI raccourcirait la sienne")
    finally:
        srv.close()

    chk(empreinte_dossier(DATA_DIR) == empreinte_avant,
        "et tout ce test n'a rien écrit dans `data/` — une mesure ne produit aucun fichier")

    print(f"[mesure-ssvep] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
