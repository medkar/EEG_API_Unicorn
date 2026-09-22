"""`MesureMarqueurs` — le socle des mesures menées par une FENÊTRE, subies par le moteur.

Le jumeau, côté MESURES, de `modes/marker_calib.py` (à lire avant) : une fenêtre de
`src/stimulus/` DÉSIGNE ce que l'utilisateur doit faire, le moteur écoute ses marqueurs. À la fin,
une calibration APPREND ; une mesure NOTE — le moteur décide avec les règles réelles du mode, on
compare à ce que la fenêtre avait désigné, et rien n'est écrit sur le disque. Ce socle existe
parce que `MesureSSVEP` réimplémentait seule tout le tuyau, et que trois mesures de test allaient
le refaire chacune : quatre copies d'un épochage divergent.

LE SOCLE POSSÈDE la ligne du temps (chauffe, `calib_start`, `calib_end`, les trois abandons), les
compteurs (`_essais_vus` ARRIVÉS contre `essai` RETENUS, pertes, chauffe), l'épochage par le
chemin du décodage (`_prelever` : `pre_s`/`post_s` LUS sur le runtime de décodage, MÊME appel
`epoch_from_stream`), et 🔴 **la CLOISON DE VÉRITÉ** : le champ de vérité-terrain est RETIRÉ du
marqueur avant que la sous-classe ne le voie, et ne rejoint la décision qu'au moment de NOTER
(`_consigner`). Le décodeur ne peut pas recevoir ce qu'on ne lui a jamais donné.

LA SOUS-CLASSE POSSÈDE la forme de son essai et l'appel à son décodeur. Quatre formes :
  • SSVEP — `cue` = un essai = une époque ; décision dans `_mesurer` (le plancher de repos n'est
    ajusté qu'à la fin), donc elle consigne l'ÉPOQUE ;
  • P300  — `cue` ouvre la manche, chaque `flash` est une époque, décision au `round_end` ;
  • ErrP  — `feedback` = un essai, la vérité voyage SUR lui (`error`) : la sous-classe le reçoit
    NU, comme en décodage — c'est le cas que la cloison protège ;
  • c-VEP — `cue` ouvre le bloc, chaque `cycle` est horloge ET époque, décision au `block_end`.
D'où UN point d'extension, `_encaisser_protocole(engine, ts, marqueur)` : il reçoit tout le
protocole (vérité retirée) et décide lui-même quand l'essai est clos, par `_consigner(observation)`.
« Une époque -> une décision » aurait interdit le P300 et le c-VEP ; recevoir la vérité en argument
aurait mis la fuite de l'ErrP à une ligne d'inattention.

🔴 **La décision passe par le décodeur RÉEL du mode, jamais par une réécriture** : une règle
locale mesurerait un décodeur que personne n'utilise, cité comme s'il décrivait le produit.

Autotest :
    python src/core/modes/mesure_marqueurs.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import (CALIB_FENETRE_ATTENTE_S, CALIB_FENETRE_SILENCE_S,  # noqa: E402
                         MARKER_STREAM_DEFAULT, use_utf8_console)
from core.modes.mesure import MesureRuntime  # noqa: E402
from core.p300_decoder import epoch_from_stream  # noqa: E402

# --- Le flux qu'un TEST écoute : TOUJOURS le flux par défaut ------------------------------------
# « Tester » lance NOTRE fenêtre, et elle publie sur `MARKER_STREAM_DEFAULT`. Jusqu'au 2026-09-22 un
# test déclarait le « Flux de marqueurs » du mode — que l'étudiant règle sur SON appli pour
# « Connecter » — et la console le lui recopiait : le moteur écoutait l'appli, la fenêtre publiait
# ailleurs, et le test abandonnait à 30 s pendant que la fenêtre jouait plein écran dans le vide.
# Un test n'offre donc pas ce réglage (le contrat REFUSE la clé), et le runtime du mode qu'il fait
# décider le reçoit fixé au défaut. Brancher une application tierce, c'est « Connecter ».
CLE_FLUX = "stream_in"


def params_du_mode_pour_un_test(spec_du_mode):
    """Les `Param` du MODE qu'un test déclare — les MÊMES objets —, sauf le flux de marqueurs."""
    return tuple(p for p in spec_du_mode.params if p.key != CLE_FLUX)


def reglages_du_decideur(spec_du_mode, params):
    """Les réglages que reçoit le runtime du MODE dans un test : ceux du test, flux PAR DÉFAUT."""
    return {p.key: (MARKER_STREAM_DEFAULT if p.key == CLE_FLUX else params.get(p.key))
            for p in spec_du_mode.params}


# Paliers auxquels une perte se DIT. Même motif que `marker_calib._PALIERS` : une séance P300 fait
# des centaines d'époques, le dire à chaque perte noierait le terminal ; le dire une seule fois
# ferait imprimer à une panne massive la même ligne qu'à une perte isolée.
_PALIERS = (1, 10, 100, 1000)


class MesureMarqueurs(MesureRuntime):
    """Une mesure dont la ligne du temps est tenue par une fenêtre de stimulus.

    À DÉCLARER par la sous-classe (attributs de classe) :
      `marker_mode_id`      le `mode` que portent les marqueurs de la fenêtre (« p300 »…) ;
      `runtime_cls_du_mode` la classe qui DÉCODE ce mode : `pre_s`/`post_s` y sont LUS ;
      `evenement_verite`, `champ_verite`  l'événement et le champ qui portent la vérité-terrain ;
      `evenement_unite`     l'événement que la fenêtre compte dans le `trials` de `calib_start` ;
      `epoque_marqueur_s`   ≥ `pre_s + post_s` : c'est sur lui que le moteur dimensionne son tampon.

    À ÉCRIRE : `_encaisser_protocole` et `_mesurer`. Le reste est optionnel (cf. plus bas).
    """

    marker_mode_id = ""
    runtime_cls_du_mode = None
    unite = "essai"          # ce que compte `essai` ; la sous-classe le redéclare au besoin
    evenement_verite = "cue"
    champ_verite = "target"
    evenement_unite = "cue"
    # L'ancre de l'époque est `ts + decalage_s`. 0 partout, sauf au SSVEP, dont le `cue` ouvre une
    # fixation qu'on prélève ENTIÈRE, donc ancrée à sa FIN. La maturité s'en DÉDUIT (cf.
    # `maturite_s`) : deux réglages indépendants finiraient par se contredire.
    decalage_s = 0.0
    # Ce que la sous-classe sait de la durée du protocole, hors chauffe. 0 = « je ne sais pas » :
    # c'est la fenêtre qui mène, le moteur ne peut que lire les constantes de `core/config.py`.
    duree_protocole_s = 0.0

    def __init__(self, spec, params, engine, rng=None):
        super().__init__(spec, params, engine, rng=rng)
        self._annonce_recue = False      # un `calib_start` est arrivé : la fenêtre est VIVANTE
        self._essais_annonces = 0        # le champ `trials` de cette annonce ; 0 = inconnu
        self._debut = None               # instant du premier tick (horloge de l'appelant)
        self._dernier_marqueur_s = None  # dernier tour où un marqueur est arrivé, MÊME horloge
        self._essais_vus = 0             # unités JOUÉES par la fenêtre, époque perdue comprise
        self._epoques_perdues = 0        # unités mûres dont l'EEG avait déjà quitté le tampon
        self._marqueurs_chauffe = 0      # jetés parce que reçus pendant la chauffe
        self._verites_illisibles = 0     # marqueurs de vérité sans valeur exploitable
        self._essais_sans_verite = 0     # décisions consignées alors qu'aucune vérité n'attendait
        self._chauffe_dite = False
        self._attente_fin_dite = False
        # 🔴 La vérité EN ATTENTE, côté CORRECTEUR. Deux soulignés : Python la renomme
        # `_MesureMarqueurs__verite`, donc une sous-classe qui écrirait `self.__verite` obtient
        # une AttributeError au lieu de la valeur. Ce n'est pas une coquetterie — c'est la cloison
        # de l'ErrP, tenue par la langue plutôt que par la relecture. La sous-classe n'en voit
        # que `_essai_ouvert` (un booléen) et, au moment de noter, `_etiquette_d_essai`.
        self.__verite = None

        # Les deux oublis qui ne lèveraient RIEN plus tard, refusés ici, bruyamment.
        if not self.marker_mode_id:
            raise ValueError(
                f"{type(self).__name__} ne déclare pas `marker_mode_id` : le moteur écouterait "
                f"une file vide, et la séance s'annulerait au bout de "
                f"{CALIB_FENETRE_ATTENTE_S:.0f} s en accusant une fenêtre qui publie très bien")
        besoin = self.pre_s + self.post_s          # lève si aucune géométrie n'est lisible
        if float(self.epoque_marqueur_s) + 1e-9 < besoin:
            raise ValueError(
                f"{type(self).__name__}.epoque_marqueur_s = {self.epoque_marqueur_s:g} s, sous "
                f"l'époque qu'elle prélève ({besoin:g} s) : le moteur dimensionne son tampon sur ce "
                f"nombre, et chaque époque en déborderait — toutes perdues, séance jetée")

    # --- ce que la sous-classe fournit ---------------------------------------

    def _encaisser_protocole(self, engine, ts, marqueur):
        """LE point d'extension, côté DÉCODEUR. Un marqueur du protocole, un seul.

        Reçoit tout ce qui n'est ni `calib_start` ni `calib_end`, pendant les essais seulement,
        et **jamais le champ de vérité** : il a été retiré (`champ_verite` sur
        `evenement_verite`). La sous-classe y fait trois choses, dans l'ordre qui convient à SA
        forme d'essai : prélever (`_prelever`), décider par le décodeur RÉEL du mode, et — quand
        l'essai est clos — `_consigner(observation)`. Un événement inconnu s'ignore : le protocole
        grandira.
        """
        raise NotImplementedError

    def _verite_lisible(self, valeur):
        """La vérité si elle est exploitable, None sinon. Défaut : un indice de cible entier.

        `isinstance(valeur, bool)` d'abord : en Python `bool` HÉRITE de `int`, et un `true` JSON
        passerait pour la cible 1. L'ErrP remplace ceci (sa vérité EST un booléen) ; une
        sous-classe qui connaît son nombre de cibles peut y ajouter la borne.
        """
        if isinstance(valeur, bool) or not isinstance(valeur, int):
            return None
        return valeur

    def _etiquette_d_essai(self, verite):
        """Ce qui accompagne l'observation dans `_enregistre`, côté CORRECTEUR. Défaut : la vérité."""
        return verite

    def _lire_annonce(self, marqueur):
        """Les champs PROPRES à ce protocole dans `calib_start` (le SSVEP y lit ses fréquences)."""

    def _pendant_les_essais(self, engine, now):
        """Appelée à chaque tour de la phase « essais », avant la garde de silence."""

    # --- les outils offerts à la sous-classe ----------------------------------

    def _geometrie(self):
        """La classe du runtime de DÉCODAGE. Lève avec une phrase lisible si elle manque."""
        if self.runtime_cls_du_mode is None:
            raise ValueError(
                f"{type(self).__name__} ne déclare pas `runtime_cls_du_mode` : aucune géométrie "
                f"d'époque à LIRE, et la seule autre façon d'en obtenir une serait de redéclarer "
                f"pre_s/post_s ici — le second chemin de découpage que ce socle existe pour fermer")
        return self.runtime_cls_du_mode

    @property
    def pre_s(self):
        return float(self._geometrie().pre_s)

    @property
    def post_s(self):
        return float(self._geometrie().post_s)

    @property
    def maturite_s(self):
        """Combien le tampon doit couvrir APRÈS le marqueur pour que son époque existe."""
        return float(self.decalage_s) + self.post_s

    @property
    def _essai_ouvert(self):
        """Une vérité attend-elle sa décision ? Un booléen : la valeur, elle, reste au correcteur."""
        return self.__verite is not None

    def _prelever(self, engine, ts):
        """L'époque de ce marqueur, par le chemin du DÉCODAGE — ou None, perte comptée et dite.

        ⚠️ LE point de ce socle, jumeau de `marker_calib.encaisser` : même fonction, mêmes bornes
        LUES sur le runtime de décodage, même tampon horodaté. Une géométrie recopiée ici pourrait
        dériver de celle du mode sans qu'aucun test ne rougisse, et le décodeur jugerait alors des
        époques décalées — du bruit, avec l'assurance d'un signal.
        """
        epoque = epoch_from_stream(engine.recent, engine.recent_ts,
                                   float(ts) + float(self.decalage_s), engine.acq.fs,
                                   pre_s=self.pre_s, post_s=self.post_s)
        if epoque is None:
            self._epoques_perdues += 1
            if self._epoques_perdues in _PALIERS:
                print(f"[{self._prefixe}] {self._epoques_perdues} époque(s) perdue(s) : le "
                      f"marqueur était mûr mais son EEG avait déjà quitté le tampon du moteur")
            return None
        self.essai += 1
        return epoque

    def _consigner(self, observation):
        """Clôt l'essai : range `(observation, étiquette)` pour `_mesurer`. Rend True si noté.

        `observation` est la DÉCISION du moteur (P300, ErrP, c-VEP), ou ce qu'il faut pour la
        prendre plus tard (le SSVEP y range l'époque). La vérité est CONSOMMÉE : un essai dont la
        vérité s'est perdue ne peut pas hériter de celle du précédent — une manche P300 sans `cue`
        lisible serait sinon notée contre la cible de la manche d'avant, en silence.
        """
        verite, self.__verite = self.__verite, None
        if verite is None:
            self._essais_sans_verite += 1
            if self._essais_sans_verite in _PALIERS:
                print(f"[{self._prefixe}] {self._essais_sans_verite} décision(s) sans vérité-terrain "
                      f"en attente : non notée(s) — la fenêtre n'a rien désigné pour cet essai")
            return False
        self._enregistre.append((observation, self._etiquette_d_essai(verite)))
        return True

    @property
    def _prefixe(self):
        return f"mesure-{self.marker_mode_id}"

    # --- ce que le socle de `MesureRuntime` attend -------------------------------

    def protocole(self):
        """AUCUNE étape : la ligne du temps est tenue par la fenêtre, pas par le moteur."""
        return ()

    def total(self):
        """Ce que la FENÊTRE a annoncé (`trials` de `calib_start`), dans l'unité de `self.essai`."""
        return self._essais_annonces

    def duree_estimee_s(self):
        return float(self.warmup_s) + float(self.duree_protocole_s)

    def instruction(self):
        """Le vrai protocole est dans l'AUTRE fenêtre, et le dire est le plus utile ici."""
        if self.phase == "chauffe":
            return "Le casque se stabilise — la fenêtre de stimulus prend la main dans un instant."
        if self.phase == "essais":
            return "La séance se déroule dans la fenêtre de stimulus : suis SES consignes."
        if self.phase == "mesure":
            return "Calcul du verdict…"
        return ""

    def rappel(self):
        return ""

    def cancel(self):
        super().cancel()
        self.__verite = None

    # --- la ligne du temps, menée par la fenêtre ---------------------------------

    def tick(self, engine, now):
        """Un pas. Appelée par la boucle du moteur, jamais par une interface.

        ⚠️ Les marqueurs sont consommés à CHAQUE TOUR, chauffe comprise : c'est l'APPEL qui fait
        avancer le curseur du moteur. Sans lui, l'arriéré s'empile, et le premier tour des essais
        avale 15 s de marqueurs dont l'EEG a quitté le tampon — panne n°7 de `modes/p300.py`.
        """
        if self.terminee:
            return
        if not self._demarre:
            self._demarre = True
            self._debut = now
            self._echeance = now + self.warmup_s
            return

        phase_avant = self.phase
        lot = engine.markers_murs(self.marker_mode_id, post_s=self.maturite_s)
        for ts, marqueur in lot:
            self.encaisser(engine, ts, marqueur)
        if lot:
            self._dernier_marqueur_s = now

        if self.phase == "chauffe":
            if self._annonce_recue and now - self._debut >= self.warmup_s:
                self._ouvrir_les_essais(now)
            elif not self._annonce_recue and now - self._debut >= CALIB_FENETRE_ATTENTE_S:
                flux = self.params.get("stream_in") or MARKER_STREAM_DEFAULT
                self._abandonne(
                    f"aucun « calib_start » reçu en {CALIB_FENETRE_ATTENTE_S:.0f} s : la fenêtre "
                    f"de stimulus ne s'est pas lancée, ou elle publie ses marqueurs sous un autre "
                    f"nom que « {flux} »")
            return

        if self.phase == "essais":
            self._pendant_les_essais(engine, now)
            self._verifie_silence(now)
            return

        if self.phase == "mesure" and phase_avant == "mesure":
            # Un tour APRÈS `calib_end`, jamais dans le même : `_terminer` bloque la boucle le
            # temps du calcul, et la console doit avoir pu peindre « Calcul… » avant.
            self._terminer(engine)

    def _ouvrir_les_essais(self, now):
        """Fin de la chauffe. Ce qui a été publié pendant est jeté, et dit."""
        self.phase = "essais"
        self.etape, self.classe, self._echeance = "", "", None
        self._dernier_marqueur_s = now
        print(f"[{self._prefixe}] chauffe terminée, {self.total()} essai(s) annoncé(s) par la "
              f"fenêtre — enregistrement en cours")

    def _verifie_silence(self, now):
        """Abandonne si la fenêtre s'est tue ALORS QU'elle annonçait davantage.

        Une séance dont toutes les unités annoncées sont arrivées et dont seul le `calib_end`
        manque n'est pas une fenêtre morte : c'est une séance complète dont le dernier marqueur
        s'est perdu. Elle ATTEND (« Abandonner » en sort) au lieu de détruire des minutes de signal.

        ⚠️ **« Arrivées » se compte sur `_essais_vus`, JAMAIS sur `self.essai`.** Les deux
        coïncident tant qu'aucune époque n'est perdue et se séparent dès la première : 36 essais
        annoncés, 36 reçus, UN sans époque, `calib_end` perdu — comparer `self.essai` faisait
        abandonner, et `cancel()` détruisait les 35 essais valides (revue de branche du
        2026-09-10, sur `ssvep_mesure.py`). Un total annoncé de 0 (`trials` illisible) rend le
        silence mortel, faute de pouvoir prouver que la séance est complète.
        """
        if self._dernier_marqueur_s is None:
            return
        silence = now - self._dernier_marqueur_s
        if silence <= CALIB_FENETRE_SILENCE_S:
            return
        if self._essais_annonces > 0 and self._essais_vus >= self._essais_annonces:
            if not self._attente_fin_dite:
                self._attente_fin_dite = True
                print(f"[{self._prefixe}] les {self._essais_vus} essais annoncés sont TOUS arrivés "
                      f"({self.essai} époque(s) retenue(s), {self._epoques_perdues} perdue(s)), "
                      f"mais aucun « calib_end » depuis {silence:.0f} s : la séance ATTEND. Si la "
                      f"fenêtre est morte, « Abandonner » dans la console — aucun verdict ne sera "
                      f"calculé.")
            return
        self._abandonne(
            f"aucun marqueur depuis {silence:.0f} s (> {CALIB_FENETRE_SILENCE_S:.0f} s) : la "
            f"fenêtre de stimulus s'est arrêtée en pleine séance. {self._essais_vus} essai(s) "
            f"reçu(s) — dont {self.essai} enregistré(s) — sur les "
            f"{self._essais_annonces or '?'} annoncés ; aucun verdict n'est calculé, un score sur "
            f"une séance tronquée serait indiscernable d'un score complet")

    def _abandonne(self, raison):
        """Jette la séance en le DISANT, par le MÊME geste que l'abandon depuis la console."""
        print(f"[{self._prefixe}] mesure ABANDONNÉE : {raison}")
        self.cancel()
        # APRÈS `cancel()` : lui seul décide de la phase, et il ne pose aucun `probleme`.
        self.probleme = raison

    # --- les marqueurs -----------------------------------------------------------

    def encaisser(self, engine, ts, marqueur):
        """Un marqueur, un seul — séparé de `tick` pour qu'un test le nourrisse un par un."""
        if self.terminee or not self._demarre:
            return
        event = marqueur.get("event")

        # L'annonce est retenue MÊME pendant la chauffe : c'est elle qui dit que la fenêtre est
        # vivante, et la refuser obligerait la fenêtre à deviner la durée de la chauffe.
        if event == "calib_start":
            self._encaisse_annonce(marqueur)
            return

        if self.phase == "chauffe":
            self._marqueurs_chauffe += 1
            if not self._chauffe_dite:
                self._chauffe_dite = True
                print(f"[{self._prefixe}] marqueur(s) reçus pendant la CHAUFFE : jetés — l'offset "
                      f"DC du casque dérive encore ({self.warmup_s:.0f} s), rien de ce qui s'y "
                      f"prélève ne vaut quelque chose.")
            return

        if self.phase != "essais":
            return      # la fenêtre parle encore après son `calib_end` : cas normal, rien à faire

        if event == "calib_end":
            self.phase = "mesure"
            self.etape, self.classe, self._echeance = "", "", None
            print(f"[{self._prefixe}] « calib_end » reçu : {self.essai} essai(s) sur les "
                  f"{self._essais_annonces or '?'} annoncés — calcul du verdict")
            return

        # 🔴 LA CLOISON. La vérité part au CORRECTEUR (`self.__verite`), le marqueur part au
        # DÉCODEUR sans elle. Une COPIE, jamais un `pop` : le dictionnaire appartient à la file du
        # moteur, que d'autres lisent (l'enregistreur de séance, un autre mode).
        if event == self.evenement_verite:
            valeur = marqueur.get(self.champ_verite)
            self.__verite = self._verite_lisible(valeur)
            if self.__verite is None:
                self._verites_illisibles += 1
                print(f"[{self._prefixe}] « {event} » sans {self.champ_verite} lisible "
                      f"({valeur!r}) : essai ignoré — sans vérité-terrain, rien à noter")
                return
            marqueur = {k: v for k, v in marqueur.items() if k != self.champ_verite}

        # Une unité ANNONCÉE n'arrive que dans un essai ouvert : c'est la définition de `trials`
        # côté fenêtre (les cycles c-VEP du « settle », hors bloc, n'y sont pas).
        if event == self.evenement_unite and self._essai_ouvert:
            self._essais_vus += 1

        self._encaisser_protocole(engine, ts, marqueur)

    def _encaisse_annonce(self, marqueur):
        """`calib_start` : la fenêtre est vivante, et voici combien d'unités elle promet."""
        trials = marqueur.get("trials")
        if isinstance(trials, bool) or not isinstance(trials, (int, float)):
            print(f"[{self._prefixe}] « calib_start » sans nombre d'essais lisible ({trials!r}) : "
                  f"l'avancement ne pourra pas s'afficher, et un silence en cours de séance sera "
                  f"traité comme une fenêtre morte faute de pouvoir prouver qu'elle a fini")
            self._essais_annonces = 0
        else:
            self._essais_annonces = max(0, int(trials))
        self._lire_annonce(marqueur)
        if self._annonce_recue:
            print(f"[{self._prefixe}] ⚠️ second « calib_start » sans « calib_end » : les "
                  f"{self.essai} essai(s) déjà enregistrés RESTENT dans le calcul. Si la fenêtre a "
                  f"redémarré, abandonne et recommence la mesure.")
        self._annonce_recue = True


def _selftest():
    """Le socle sur une horloge FABRIQUÉE et un tampon HORODATÉ. Aucun casque, aucune fenêtre."""
    import numpy as np

    from core.config import DATA_DIR, empreinte_dossier
    from core.modes.mesure import MesureSpec

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    empreinte_avant = empreinte_dossier(DATA_DIR)

    class _FausseAcq:
        fs = 250.0

    class _Moteur:
        """Un tampon HORODATÉ portant une RAMPE sur sa voie 0 : tout décalage d'un échantillon
        change la valeur, donc l'accord des épochages ne dépend pas du tirage."""

        def __init__(self, secondes=30.0, t0=1000.0):
            self.acq = _FausseAcq()
            self.t0 = t0
            self.recent_ts = np.arange(t0, t0 + secondes, 1.0 / self.acq.fs)
            self.recent = np.random.default_rng(0).normal(0.0, 5.0, (len(self.recent_ts), 8))
            self.recent[:, 0] = np.arange(len(self.recent_ts), dtype=float)
            self._lots, self.appels = [], []

        def file(self, lot):
            self._lots.append(list(lot))

        def markers_murs(self, mode_id, post_s):
            self.appels.append((mode_id, post_s))
            return self._lots.pop(0) if self._lots else []

    # Deux géométries de runtime de DÉCODAGE. Pas celle du P300 : à 0,15 s × 250 Hz l'arrondi
    # bancaire absorbe un décalage d'un échantillon (cf. `marker_calib._selftest`), et le test
    # d'accord ne saurait plus rougir.
    class _Geo:
        pre_s, post_s = 0.30, 0.40

    class _AutreGeo:
        pre_s, post_s = 0.20, 0.50

    class _DecodeurEspion:
        """Note TOUT ce qu'on lui passe : la seule façon de tester une ABSENCE."""

        def __init__(self):
            self.vu = []

        def __call__(self, *args):
            self.vu.append(args)
            return len(self.vu) % 2 == 0

    # Forme P300 : la vérité sur `cue`, l'unité sur `flash`, la décision au `round_end`. C'est la
    # forme la plus exigeante — trois marqueurs différents pour trois rôles.
    class _MesureManches(MesureMarqueurs):
        marker_mode_id = "essai"
        runtime_cls_du_mode = _Geo
        evenement_unite = "flash"
        epoque_marqueur_s = 0.70

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.recus, self._manche, self.calculs = [], [], 0

        def _encaisser_protocole(self, engine, ts, marqueur):
            self.recus.append(dict(marqueur))
            event = marqueur.get("event")
            if event == "cue":
                self._manche = []
            elif event == "flash":
                epoque = self._prelever(engine, ts)
                if epoque is not None:
                    self._manche.append((marqueur.get("target"), epoque))
            elif event == "round_end":
                # Le « décodeur » : la cible la plus flashée. Factice, mais DÉTERMINISTE.
                cibles = [c for c, _e in self._manche]
                self._consigner(max(set(cibles), key=cibles.count) if cibles else -1)
                self._manche = []

        def _mesurer(self, enregistre, fs):
            self.calculs += 1
            return {"couples": list(enregistre), "verdict": "ESSAI", "honnetete": "factice"}

    # Forme ErrP : la vérité voyage SUR l'unité elle-même. C'est le cas de la cloison.
    class _MesureFeedback(MesureMarqueurs):
        marker_mode_id = "essai"
        runtime_cls_du_mode = _Geo
        evenement_verite = evenement_unite = "feedback"
        champ_verite = "error"
        epoque_marqueur_s = 0.70

        def __init__(self, *args, espion=None, **kwargs):
            super().__init__(*args, **kwargs)
            self.espion, self.recus = espion, []

        def _verite_lisible(self, valeur):
            return valeur if isinstance(valeur, bool) else None

        def _encaisser_protocole(self, engine, ts, marqueur):
            self.recus.append(dict(marqueur))
            if marqueur.get("event") == "feedback":
                epoque = self._prelever(engine, ts)
                if epoque is not None:
                    self._consigner(self.espion(epoque, marqueur))

        def _mesurer(self, enregistre, fs):
            return {"couples": list(enregistre), "verdict": "ESSAI", "honnetete": "factice"}

    SPEC = MesureSpec(id="essai_marqueurs", label="Mesure d'essai", runtime_cls=_MesureManches)

    def m(event, **champs):
        return {"mode": "essai", "event": event, **champs}

    def demarree(moteur, trials, cls=_MesureManches, **kw):
        """Lancée, annonce reçue, chauffe PASSÉE — l'état normal d'une séance."""
        rt = cls(SPEC, {}, moteur, **kw)
        rt.tick(moteur, moteur.t0)
        rt.encaisser(moteur, moteur.t0, m("calib_start", trials=trials))
        rt.tick(moteur, moteur.t0 + rt.warmup_s + 0.1)
        return rt

    # === Les oublis qui ne lèveraient rien plus tard ========================================
    for attrs, mot in (({"marker_mode_id": ""}, "marker_mode_id"),
                       ({"runtime_cls_du_mode": None}, "runtime_cls_du_mode"),
                       ({"epoque_marqueur_s": 0.5}, "epoque_marqueur_s")):
        try:
            type("_Oubli", (_MesureManches,), attrs)(SPEC, {}, _Moteur())
            chk(False, f"une sous-classe sans `{mot}` valable doit être refusée à la construction")
        except ValueError as e:
            chk(mot in str(e), f"sans `{mot}` valable : refus À LA CONSTRUCTION, qui le nomme")

    # === L'épochage par le chemin du DÉCODAGE ===============================================
    def accord(geo):
        moteur = _Moteur()
        cls = type("_G", (_MesureManches,), {"runtime_cls_du_mode": geo})
        rt = demarree(moteur, 12, cls=cls)
        rt.encaisser(moteur, moteur.t0 + 4.0, m("cue", target=1))
        instants = [moteur.t0 + 5.0 + 0.37 * i for i in range(12)]
        for i, ts in enumerate(instants):
            rt.encaisser(moteur, ts, m("flash", target=i % 6))
        prelevees = [e for _c, e in rt._manche]
        # La géométrie est lue sur le runtime de DÉCODAGE, ici comme dans le mode.
        decodees = [epoch_from_stream(moteur.recent, moteur.recent_ts, ts, moteur.acq.fs,
                                      pre_s=geo.pre_s, post_s=geo.post_s) for ts in instants]
        return rt, moteur, prelevees, decodees

    for geo in (_Geo, _AutreGeo):
        rt, moteur, prelevees, decodees = accord(geo)
        chk(len(prelevees) == 12 and all(a.shape == b.shape and np.abs(a - b).max() == 0
                                         for a, b in zip(prelevees, decodees)),
            f"[{geo.pre_s:g}/{geo.post_s:g} s] les époques de la mesure sont IDENTIQUES à "
            f"l'échantillon près à celles du décodage — un seul échantillon d'écart ferait juger "
            f"au décodeur des époques décalées, sans rien lever")
    rt_a, _mo, ep_a, _d = accord(_Geo)
    rt_b, _mo, ep_b, _d = accord(_AutreGeo)
    chk(rt_a.pre_s == _Geo.pre_s and len(ep_a[0]) == 175 and len(ep_b[0]) == 175
        and np.abs(ep_a[0] - ep_b[0]).max() > 0,
        "pre_s/post_s sont LUS sur le runtime de décodage : changer lui seul DÉPLACE l'époque")
    moteur = _Moteur()
    rt = _MesureManches(SPEC, {}, moteur)
    rt.tick(moteur, moteur.t0)
    rt.tick(moteur, moteur.t0 + 1.0)
    chk(moteur.appels == [("essai", _Geo.post_s)],
        f"le moteur est interrogé sous le `mode` de la FENÊTRE, avec la maturité de l'époque — et "
        f"DÈS la chauffe, pour que l'arriéré ne s'empile pas ({moteur.appels})")

    # === Les deux compteurs : ARRIVÉS contre RETENUS ========================================
    moteur = _Moteur()
    rt = demarree(moteur, 12)
    rt.encaisser(moteur, moteur.t0 + 4.0, m("cue", target=2))
    for i in range(12):
        # Le 6e flash date d'AVANT le tampon : `epoch_from_stream` rend None, l'époque est perdue.
        ts = moteur.t0 + 0.05 if i == 5 else moteur.t0 + 5.0 + 0.3 * i
        rt.encaisser(moteur, ts, m("flash", target=i % 6))
    chk(rt._essais_vus == 12 and rt.essai == 11 and rt._epoques_perdues == 1,
        f"`_essais_vus` compte les unités ARRIVÉES (12), `essai` les époques RETENUES (11), et "
        f"l'écart est la perte ({rt._essais_vus}, {rt.essai}, {rt._epoques_perdues})")

    # === Garde de silence : `calib_end` perdu, TOUT est arrivé -> la séance ATTEND ===========
    t = moteur.t0 + rt.warmup_s + 0.1
    moteur.file([(moteur.t0 + 9.0, m("round_end"))])
    rt.tick(moteur, t + 1.0)
    rt.tick(moteur, t + 1.0 + CALIB_FENETRE_SILENCE_S + 0.5)
    chk(rt.phase == "essais" and len(rt._enregistre) == 1,
        f"toutes les unités annoncées sont arrivées, une époque perdue, `calib_end` perdu : la "
        f"séance ATTEND et garde son essai ({rt.phase}, {len(rt._enregistre)}) — comparer `essai` "
        f"au total annoncé abandonnerait ici, et `cancel()` détruirait tout")

    moteur = _Moteur()
    rt = demarree(moteur, 12)
    t = moteur.t0 + rt.warmup_s + 0.1
    moteur.file([(moteur.t0 + 4.0, m("cue", target=2))]
                + [(moteur.t0 + 5.0 + 0.3 * i, m("flash", target=i % 6)) for i in range(11)]
                + [(moteur.t0 + 9.0, m("round_end"))])
    rt.tick(moteur, t + 1.0)
    rt.tick(moteur, t + 1.0 + CALIB_FENETRE_SILENCE_S - 0.5)
    chk(rt.phase == "essais", f"un silence PLUS COURT que le seuil ne tue rien ({rt.phase})")
    rt.tick(moteur, t + 1.0 + CALIB_FENETRE_SILENCE_S + 0.5)
    chk(rt.phase == "annule" and rt._enregistre == [] and rt.resultat is None
        and "11 essai(s) reçu(s)" in rt.probleme,
        f"…mais une unité annoncée JAMAIS arrivée, c'est une fenêtre morte : la séance s'annule "
        f"sans calcul, en disant combien sont arrivées ({rt.phase}, {rt.probleme[:60]}…)")

    moteur = _Moteur()
    rt = _MesureManches(SPEC, {}, moteur)
    rt.tick(moteur, moteur.t0)
    rt.tick(moteur, moteur.t0 + CALIB_FENETRE_ATTENTE_S + 1.0)
    chk(rt.phase == "annule" and MARKER_STREAM_DEFAULT in rt.probleme,
        f"sans `calib_start`, la séance s'annule en nommant le flux écouté ({rt.probleme[:50]}…)")

    # === La chauffe : comptée, jamais des essais =============================================
    moteur = _Moteur()
    rt = _MesureManches(SPEC, {}, moteur)
    rt.tick(moteur, moteur.t0)
    moteur.file([(moteur.t0 + 1.0, m("calib_start", trials=6)),
                 (moteur.t0 + 1.5, m("cue", target=0)),
                 (moteur.t0 + 2.0, m("flash", target=0)),
                 (moteur.t0 + 2.2, m("round_end"))])
    rt.tick(moteur, moteur.t0 + 3.0)
    chk(rt.total() == 6 and rt.phase == "chauffe",
        f"le `calib_start` reçu pendant la chauffe est RETENU ({rt.total()})")
    chk(rt._marqueurs_chauffe == 3 and rt.essai == 0 and rt._essais_vus == 0
        and rt.recus == [] and rt._enregistre == [],
        f"…les autres marqueurs sont COMPTÉS et jetés : aucune époque, aucune unité, et le "
        f"décodeur ne les voit même pas ({rt._marqueurs_chauffe} jetés, {rt.essai} essai)")

    # === 🔴 LA CLOISON DE VÉRITÉ (forme ErrP) =================================================
    espion = _DecodeurEspion()
    moteur = _Moteur()
    rt = demarree(moteur, 2, cls=_MesureFeedback, espion=espion)
    dans_la_file = m("feedback", error=True)
    rt.encaisser(moteur, moteur.t0 + 5.0, dans_la_file)
    rt.encaisser(moteur, moteur.t0 + 6.0, m("feedback", error=False))
    chk(len(espion.vu) == 2,
        f"le décodeur a bien été appelé ({len(espion.vu)} fois) — sinon ce qui suit serait vrai "
        f"à vide")
    chk(all("error" not in str(arg) for appel in espion.vu for arg in appel[1:])
        and all("error" not in r for r in rt.recus),
        f"…et l'étiquette ne lui est JAMAIS parvenue, ni à la sous-classe : un décodeur qui la "
        f"recevrait rendrait un score parfait et faux, en silence ({rt.recus})")
    chk([lab for _o, lab in rt._enregistre] == [True, False],
        f"…tandis que le CORRECTEUR l'a reçue, appariée à chaque décision "
        f"({[lab for _o, lab in rt._enregistre]})")
    chk(dans_la_file.get("error") is True,
        "et le marqueur de la FILE n'est pas amputé : on retire sur une COPIE, d'autres le lisent")

    # === La vérité est CONSOMMÉE par la décision qu'elle note =================================
    moteur = _Moteur()
    rt = demarree(moteur, 12)
    rt.encaisser(moteur, moteur.t0 + 4.0, m("cue", target=2))
    for i in range(6):
        rt.encaisser(moteur, moteur.t0 + 5.0 + 0.3 * i, m("flash", target=2))
    rt.encaisser(moteur, moteur.t0 + 7.0, m("round_end"))
    # Manche 2 : son `cue` s'est PERDU (jamais arrivé). Manche 3 : son `cue` est ILLISIBLE.
    for i in range(6):
        rt.encaisser(moteur, moteur.t0 + 8.0 + 0.3 * i, m("flash", target=4))
    rt.encaisser(moteur, moteur.t0 + 10.0, m("round_end"))
    rt.encaisser(moteur, moteur.t0 + 11.0, m("cue", target=True))
    for i in range(6):
        rt.encaisser(moteur, moteur.t0 + 12.0 + 0.3 * i, m("flash", target=5))
    rt.encaisser(moteur, moteur.t0 + 14.0, m("round_end"))
    chk(rt._enregistre == [(2, 2)] and rt._essais_sans_verite == 2
        and rt._verites_illisibles == 1,
        f"une manche sans `cue` (perdu ou illisible) n'hérite PAS de la vérité de la précédente : "
        f"sa décision n'est pas notée, elle est comptée — sinon elle serait jugée contre la cible "
        f"d'AVANT, en silence ({rt._enregistre}, {rt._essais_sans_verite} sans vérité)")
    chk(rt._essais_vus == 6,
        f"…et leurs flashs, hors de tout essai ouvert, ne sont pas des unités annoncées "
        f"({rt._essais_vus})")

    # === La séance NOMINALE, par la vraie porte ==============================================
    moteur = _Moteur()
    rt = demarree(moteur, 6)
    t = moteur.t0 + rt.warmup_s + 0.1
    moteur.file([(moteur.t0 + 4.0, m("cue", target=3))]
                + [(moteur.t0 + 5.0 + 0.3 * i, m("flash", target=3 if i < 4 else 1))
                   for i in range(6)]
                + [(moteur.t0 + 7.0, m("round_end")), (moteur.t0 + 7.5, m("calib_end"))])
    rt.tick(moteur, t + 1.0)
    chk(rt.phase == "mesure" and rt.calculs == 0,
        f"`calib_end` ouvre le calcul sans l'exécuter dans le même tour ({rt.phase})")
    rt.tick(moteur, t + 1.1)
    chk(rt.phase == "fini" and rt.calculs == 1 and rt.resultat["couples"] == [(3, 3)],
        f"le tour suivant calcule UNE fois, sur les couples (décision, vérité) "
        f"({rt.phase}, {(rt.resultat or {}).get('couples')})")
    etat = rt.state(now=t + 2.0)
    chk({"phase", "essai", "total", "instruction", "resultat", "probleme"} <= set(etat)
        and etat["etape"] == "" and (etat["essai"], etat["total"]) == (6, 6),
        f"l'instantané est celui du parent, `etape` vide, l'avancement dans l'unité annoncée "
        f"({etat['essai']} sur {etat['total']})")

    # === Rien sur le disque ==================================================================
    try:
        rt.dossier_ou_lever()
        chk(False, "une mesure n'a pas de dossier : le lui demander doit être REFUSÉ")
    except ValueError as e:
        chk("MESURE" in str(e), "une mesure menée par une fenêtre n'a AUCUN dossier d'écriture")
    chk(empreinte_dossier(DATA_DIR) == empreinte_avant, "et tout ce test n'a rien écrit dans data/")

    print(f"[mesure-marqueurs] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
