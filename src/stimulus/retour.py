"""Le RETOUR EN DIRECT : la fenêtre entoure la cible que le moteur DÉCODE (option `--retour`).

Demandé au casque le 2026-10-01 : « on regarde une cible, le logiciel entoure celle qu'il pense
qu'on regarde ». Trois fenêtres le proposent — `cvep.py`, `ssvep.py`, `p300.py` — et ce module est
leur SEULE écriture du geste, comme `garde.py` l'est pour leurs gardes : trois copies d'un fil
réseau et d'une règle de rattachement divergeraient au premier correctif.

Quatre morceaux :

1. **`SourceDecisions` — la fenêtre écoute le flux DÉCODÉ PUBLIC de son mode**, exactement comme
   l'application d'un étudiant : par son NOM (`core.lsl_io.stream_name`, suffixe LU dans le
   `ModeSpec` du mode qui déclare cette fenêtre). Aucun flux nouveau, aucun contrat nouveau : notre
   propre fenêtre devient un client du contrat public, et l'éprouve à chaque séance. Voie 0 =
   `target_index`, −1 = « pas de décision ».
   ⚠️ **La recherche vit dans un FIL, jamais dans la boucle de rendu.** `resolve_byprop` attend
   jusqu'à son délai quand le flux n'existe pas encore ; dans la boucle, c'est une image figée — et
   une image figée est une cible qui cesse de clignoter (SSVEP) ou une phase qui glisse (c-VEP).
   La boucle ne fait que `pull_chunk(timeout=0.0)` : jamais une attente. Le NOM, lui, se lit dans
   le constructeur, que la fenêtre appelle AVANT `pygame.init()` : il importe le catalogue des modes
   (1 à 2 s de calcul), qui dans un fil voisin volait le GIL au rendu (revue C-M5).
   🔴 **Seulement un flux de CETTE machine** (revues C-I1, E-I1). En salle, chaque étudiant fait
   tourner son moteur sous les MÊMES noms de flux : un homonyme d'une autre machine est ignoré, et
   le fil cherche jusqu'à trouver celui d'ici. Le nom d'hôte est celui que liblsl publie
   (`StreamInfo.hostname()`), comparé sans casse à `socket.gethostname()` — égaux sur le poste,
   vérifié le 2026-10-01.

2. **`Retour` — l'état de l'anneau**, en pur (ni pygame, ni réseau : testable sans écran).
   Deux régimes :
   - **continu** (c-VEP et SSVEP en libre, ~5 Hz) : l'anneau suit la DERNIÈRE décision VALIDE, et
     s'efface `PERIME_S` après elle (un mode arrêté ne doit pas laisser un anneau figé qui aurait
     l'air d'une décision). ⚠️ Un −1 ne l'efface PAS : un anneau qui clignote à 5 Hz à côté de la
     cible fixée est un stimulus, et le SSVEP s'abstient une fenêtre sur deux (revue C-I3) ;
   - **par essai** (les tests guidés, et le P300 qui décide une fois par manche) : la fenêtre dit
     quand un essai se FERME (`mesure_finie`) et quand le suivant COMMENCE sa mesure
     (`mesure_commence`).

   **UNE seule couleur, VERTE, en test comme en libre** (2026-10-02, demandé par l'utilisateur) :
   l'anneau montre la cible DÉCODÉE, il ne juge pas. Une erreur se voit d'elle-même — l'anneau
   n'est pas sur la cible désignée. Une première version peignait « juste » et « faux » de deux
   couleurs, et le libre d'une troisième : trois codes à apprendre pour une information déjà à
   l'écran.

   ⚠️ **Le RATTACHEMENT d'une décision à son essai — la règle, et pourquoi.** Le moteur ne décide
   un essai qu'APRÈS sa fermeture (il attend le marqueur de fin et la maturité de la dernière
   époque) ; sa décision arrive donc pendant l'inter-essai — le settle du c-VEP, la consigne de la
   manche P300 suivante, le retour à la croix du SSVEP. La règle : **une décision appartient à
   l'essai FERMÉ le plus récent, si elle arrive avant que l'essai suivant ne commence sa mesure ;
   au plus une par essai ; toute autre est IGNORÉE** (comptée, jamais affichée).
   Pourquoi l'ordre d'arrivée et pas l'horodatage : le contrat ne dit pas QUEL instant porte une
   décision (sa publication ? la fermeture de l'essai ?), et une règle bâtie sur un choix non
   écrit casserait en silence le jour où il change. L'ordre, lui, est garanti par construction :
   la latence du moteur (~1 s) est bien plus courte qu'un essai (≥ 5 s). Et l'échec est BORNÉ :
   une décision trop tardive est perdue (un essai sans anneau), elle ne décale jamais les
   suivantes — là où « la plus ancienne en attente » ferait colorier TOUTE la suite à contretemps
   après une seule décision manquante.
   Pourquoi l'effacer BIEN AVANT la mesure suivante (revue D-I1) : un anneau autour d'une AUTRE
   cible pendant qu'on enregistre la suivante est un distracteur, et sa DISPARITION est un
   transitoire visuel — calée sur un flash ou une frame 0 de cycle, elle s'imprime dans les données
   notées. Chaque fenêtre appelle donc `mesure_commence()` avec la marge de son paradigme.

3. **`dessine_anneau` / `anneaux_a_l_ecran`** — le dessin, et sa relecture dans les PIXELS pour les
   `--smoke` (même famille de sonde que la phase c-VEP ou la cible SSVEP).
   ⚠️ **L'anneau ne touche JAMAIS un pixel de cible.** Chaque fenêtre le trace dans une bande VIDE
   de sa géométrie, et ses `--smoke` le vérifient à chaque image par `pixels_non_fond_sous_anneau` :
   tout pixel que l'anneau va couvrir doit être du FOND au moment où il est tracé. Les tests qui
   lisent la phase ou la consigne dans les pixels restent donc vrais anneau affiché. Même garde
   pour la croix (`dessine_croix`).

4. **`ReposDuMoteur` — la croix de l'essai LIBRE.** La console ouvre la fenêtre dès que le mode
   démarre : le plancher du SSVEP se mesure AVEC les cibles qui clignotent, sans en fixer aucune
   (`ssvep.py`, `_guide`). La fenêtre lit le flux PUBLIC `status` du moteur d'ici et montre une
   croix tant que sa `phase` dit chauffe ou plancher — de nouveau si le moteur REFAIT son repos.
   Pourquoi `status` et pas le silence du flux décodé : il dit la phase en toutes lettres (contrat
   public), à chaque changement ET toutes les `STATUS_PERIOD_S` (2 s, `core/server.py`) — un
   abonné tardif l'apprend en 2 s ; un silence, lui, ne se distingue pas d'un mode qui ne
   publierait qu'au changement. Sans aucun `status` : croix (on s'ouvre en chauffe), qui tombe
   après `STATUT_ABSENT_S` — une croix éternelle bloquerait l'essai.

⚠️ `−1` en test guidé : AUCUN anneau. Le moteur s'est abstenu ; ce n'est ni juste ni faux — c'est
la règle des tests (« −1 = silence, jamais une erreur »).

Pas d'autotest propre : les trois `--smoke` de fenêtre appellent les `autotest_*` d'ici, en plus
de leurs gardes de câblage.
"""

import colorsys
import json
import math
import os
import socket
import threading
import time

from pylsl import StreamInlet, resolve_byprop

# --- La couleur : elle n'existe NULLE PART ailleurs dans les trois fenêtres ---------------------
# C'est ce qui permet aux `--smoke` de relire l'anneau dans les pixels à la couleur EXACTE (aucun
# lissage : `pygame.draw.circle` ne lisse pas). Une couleur partagée avec un décor ferait trouver un
# anneau là où il n'y en a pas. ⚠️ Et elle ne RESSEMBLE à aucune consigne (revue D-I2) : les trois
# fenêtres désignent leur cible en BLEU — le c-VEP la cerclait en vert jusqu'au 2026-10-02, à 13° de
# teinte de cet anneau ; `autotest_couleurs` compare les TEINTES aux couleurs de consigne LUES dans
# les trois fenêtres.
COULEUR_DECODEE = (0, 230, 0)    # vert : « voici la cible que le moteur décode », sans jugement
COULEURS = (COULEUR_DECODEE,)
EPAISSEUR_PX = 4                 # tracée vers l'INTÉRIEUR du rayon donné (convention de pygame)
ECART_TEINTE_MIN = 45.0          # degrés ; l'anneau vert était à 13° du cercle VERT du c-VEP d'avant
CROIX_PX, CROIX_EPAISSEUR_PX = 14, 3   # la croix du repos : demi-branche, épaisseur

# Régime continu : passé ce délai sans décision VALIDE, l'anneau s'efface. 5 publications à 5 Hz.
PERIME_S = 1.0

# `status.phase` pendant le repos du moteur : ce que `core/server.py:EngineServer._PHASES_PUBLIQUES`
# publie pour « warmup » et « rest » (copie : importer le moteur coûterait brainflow — l'accord est
# tenu par `autotest_statut`). Sans un seul `status` en `STATUT_ABSENT_S`, la croix tombe.
PHASES_DE_REPOS = ("warmup", "baseline")
STATUT_ABSENT_S = 10.0

# Une passe de résolution. Courte : avec `minimum=32`, chaque passe consomme tout son délai (on ne
# trouvera jamais 32 flux), et c'est aussi le temps que met `fermer()` à arrêter le fil.
PASSE_S = 0.5
OUVERTURE_S = 2.0


def flux_decode_de(stimulus_id):
    """Le NOM PUBLIC du flux décodé que lit la fenêtre `stimulus_id`. Lève si aucun mode ne la
    déclare.

    Lu dans le `ModeSpec` du mode dont `stimulus_id` est cette fenêtre — jamais écrit ici : le nom
    d'un flux est du contrat public, et une seconde écriture dériverait. Import TARDIF (le
    catalogue des modes coûte ~2 s) : appelé par le constructeur de `SourceDecisions`, que la
    fenêtre construit AVANT de s'ouvrir — jamais dans un fil pendant le rendu.
    """
    from core.lsl_io import stream_name
    from core.modes import registry as modes

    suffixes = [s.stream for s in modes.MODES if s.stimulus_id == stimulus_id and s.stream]
    if len(suffixes) != 1:
        raise LookupError(f"aucun mode (ou plusieurs) ne déclare la fenêtre « {stimulus_id} » "
                          f"avec un flux décodé ({suffixes})")
    return stream_name(suffixes[0])


def flux_de_cette_machine(flux, hote):
    """Les flux publiés par la machine `hote` (nom d'hôte SANS casse), triés par `source_id`."""
    return sorted((f for f in flux if (f.hostname() or "").casefold() == hote.casefold()),
                  key=lambda f: f.source_id() or "")


class SourceDecisions:
    """Le flux décodé du mode, résolu en tâche de fond. `tirer()` ne bloque JAMAIS.

    `recover=False`, comme `core.markers.MarkerInlet` et pour la raison qu'il a mesurée : un inlet
    qui « récupère » attend le retour de l'ANCIEN émetteur (même `source_id`) ; un moteur relancé
    sous une autre identité ne reviendrait jamais. Ici une disparition LÈVE dans `tirer()`, l'inlet
    est lâché, et le fil re-résout tout seul.

    🔴 Seulement un flux de CETTE machine (cf. la docstring du module) : un homonyme d'ailleurs est
    compté dans `etrangers`, dit, et le fil continue de chercher. `hote` n'existe que pour
    l'autotest, qui fait passer le flux d'ici pour celui d'un autre poste.
    """

    def __init__(self, stimulus_id=None, nom=None, passe_s=PASSE_S, hote=None):
        self.nom = nom
        self.passe_s = float(passe_s)
        self.hote = socket.gethostname() if hote is None else hote
        self._inlet = None
        self._verrou = threading.Lock()
        self._arret = threading.Event()
        self.refus = ""
        self.connexions = self.etrangers = 0
        if self.nom is None:
            try:   # ⚠️ ICI, dans le fil de la fenêtre : cf. `flux_decode_de`
                self.nom = flux_decode_de(stimulus_id)
            except Exception as e:  # noqa: BLE001 - une fenêtre sans anneau vaut mieux qu'aucune
                self.refus = f"{type(e).__name__} : {e}"
                print(f"[retour] ⚠️ pas de retour : {self.refus}")
        self._fil = threading.Thread(target=self._boucle, daemon=True,
                                     name=f"retour-{stimulus_id or nom}")
        self._fil.start()

    @property
    def connecte(self):
        return self._inlet is not None

    def _boucle(self):
        if self.nom is None:
            return
        attente_dite = False
        while not self._arret.is_set():
            if self._inlet is None:
                inlet = self._connecte()
                if inlet is not None:
                    with self._verrou:
                        if self._arret.is_set():
                            _referme(inlet)
                            break
                        self._inlet = inlet
                    self.connexions += 1
                    attente_dite = False
                    print(f"[retour] branché sur « {self.nom} » de cette machine")
                elif not attente_dite:
                    attente_dite = True
                    print(f"[retour] « {self.nom} » n'existe pas encore sur cette machine — je le "
                          f"cherche en tâche de fond (le mode est-il démarré ?)")
            self._arret.wait(0.1)

    def _connecte(self):
        try:
            flux = resolve_byprop("name", self.nom, minimum=32, timeout=self.passe_s)
        except Exception as e:  # noqa: BLE001 - le réseau casse de mille façons
            self.refus = f"recherche impossible ({type(e).__name__} : {e})"
            return None
        locaux = flux_de_cette_machine(flux, self.hote)
        if len(flux) - len(locaux) > self.etrangers:
            self.etrangers = len(flux) - len(locaux)
            print(f"[retour] {self.etrangers} flux « {self.nom} » d'une AUTRE machine ignoré(s) : "
                  f"seul celui de « {self.hote} » compte")
        if not locaux:
            return None
        inlet = None
        try:
            inlet = StreamInlet(locaux[0], max_buflen=6, recover=False)
            # Obligatoire AVANT la première lecture : un inlet ne se connecte qu'à la première
            # lecture, et ne rejoue rien de ce qui précède (même piège que `MarkerInlet.resolve`).
            inlet.open_stream(timeout=OUVERTURE_S)
        except Exception as e:  # noqa: BLE001 - un moteur qui meurt pendant la connexion
            if inlet is not None:
                _referme(inlet)
            self.refus = f"connexion impossible ({type(e).__name__} : {e})"
            return None
        return inlet

    def _valeur(self, ligne):
        """`target_index`, ou None si illisible : NaN et ±inf sautent (`int(inf)` lèverait dans la
        boucle de rendu, revue C-M7)."""
        v = float(ligne[0])
        return int(round(v)) if math.isfinite(v) else None

    def tirer(self):
        """Les décisions arrivées depuis l'appel précédent : `[(horodatage, target_index), ...]`.
        `[]` si rien, si pas encore connecté, ou si le flux vient d'être perdu. Ne lève jamais."""
        inlet = self._inlet
        if inlet is None:
            return []
        try:
            valeurs, horodatages = inlet.pull_chunk(timeout=0.0, max_samples=64)
        except Exception as e:  # noqa: BLE001 - `LostError` (pylsl.util) et ses cousins
            with self._verrou:
                if self._inlet is inlet:
                    self._inlet = None
            _referme(inlet)
            print(f"[retour] flux « {self.nom} » perdu ({type(e).__name__}) — je le re-cherche")
            return []
        lues = [(float(ts), self._valeur(ligne)) for ligne, ts in zip(valeurs, horodatages) if ligne]
        return [(ts, v) for ts, v in lues if v is not None]

    def fermer(self):
        """Arrête le fil et lâche l'inlet. Ne lève jamais."""
        self._arret.set()
        with self._verrou:
            inlet, self._inlet = self._inlet, None
        if inlet is not None:
            _referme(inlet)
        self._fil.join(timeout=self.passe_s + 1.0)


class StatutDuMoteur(SourceDecisions):
    """Le flux PUBLIC `status` du moteur de CETTE machine : `tirer()` → `[(horodatage, phase)]`."""

    def __init__(self, nom=None, passe_s=PASSE_S, hote=None):
        from core.lsl_io import stream_name   # léger : pylsl et config, pas le catalogue
        super().__init__(nom=nom or stream_name("status"), passe_s=passe_s, hote=hote)

    def _valeur(self, ligne):
        try:
            phase = json.loads(ligne[0]).get("phase")
        except (ValueError, TypeError, AttributeError):
            return None
        return phase if isinstance(phase, str) else None


class ReposDuMoteur:
    """`en_repos` : vrai tant que le moteur chauffe ou mesure son plancher (cf. le point 4 de la
    docstring du module). Pur : `source` = `StatutDuMoteur`, ou une source factice en `--smoke`."""

    def __init__(self, source, absent_s=STATUT_ABSENT_S, horloge=time.perf_counter):
        self.source, self.absent_s, self._horloge = source, float(absent_s), horloge
        self._t0, self.phase, self.recus = horloge(), None, 0

    def lire(self):
        """APRÈS le flip et le marqueur de l'image, comme `Retour.lire`."""
        for _ts, phase in self.source.tirer():
            self.phase, self.recus = phase, self.recus + 1

    @property
    def en_repos(self):
        if self.phase is None:
            return self._horloge() - self._t0 < self.absent_s
        return self.phase in PHASES_DE_REPOS

    def bilan(self, prefixe):
        if self.recus == 0:
            print(f"{prefixe} repos : le flux « status » n'a JAMAIS été lu — croix retirée après "
                  f"{self.absent_s:g} s sans savoir si le repos était fini")

    def fermer(self):
        self.source.fermer()


def _referme(inlet):
    try:
        inlet.close_stream()
    except Exception:  # noqa: BLE001 - refermer un flux déjà mort est le cas NORMAL
        pass


class Retour:
    """L'état de l'anneau. Pur : aucune dépendance à pygame ni au réseau (cf. docstring du module).

    `source` : tout objet qui a `tirer()` et `fermer()` — `SourceDecisions` en séance, une source
    FACTICE dans les `--smoke`. `horloge` est injectable pour la même raison.
    """

    def __init__(self, source, n_cibles, par_essai=False, perime_s=PERIME_S,
                 horloge=time.perf_counter):
        self.source = source
        self.n_cibles = int(n_cibles)
        self.par_essai = bool(par_essai)
        self.perime_s = float(perime_s)
        self._horloge = horloge
        self.cible = None
        self.couleur = None
        self._attente = False      # un essai est FERMÉ et attend SA décision
        self._t_derniere = None
        self.recues = self.rattachees = self.ignorees = 0

    @property
    def anneau(self):
        return None if self.cible is None else (self.cible, self.couleur)

    @property
    def attend(self):
        """Vrai tant qu'un essai FERMÉ attend encore sa décision — ce que l'écran final du P300
        guette pour que la dernière manche ait son anneau."""
        return self._attente

    def _efface(self):
        self.cible = self.couleur = None

    def mesure_commence(self):
        """L'essai suivant va commencer sa MESURE : l'anneau s'efface, et une décision qui
        arriverait encore pour l'essai précédent sera ignorée (cf. la règle de rattachement). La
        fenêtre l'appelle avec une MARGE avant les données que la décision suivante lira."""
        self._attente = False
        self._efface()

    def mesure_finie(self):
        """Un essai vient de se fermer : la PROCHAINE décision reçue est la sienne."""
        self._attente = True

    def lire(self):
        """APRÈS le flip et le marqueur de l'image : tire sans attendre, met l'anneau à jour."""
        maintenant = self._horloge()
        for _ts, indice in self.source.tirer():
            self._applique(int(indice), maintenant)
        if (not self.par_essai and self.cible is not None
                and maintenant - self._t_derniere > self.perime_s):
            self._efface()

    def _applique(self, indice, maintenant):
        self.recues += 1
        valide = 0 <= indice < self.n_cibles
        if not self.par_essai:
            # ⚠️ Un −1 ne touche à rien : l'anneau tient jusqu'à `PERIME_S` après la dernière
            # décision VALIDE (cf. la docstring du module — un anneau qui clignote à 5 Hz à côté
            # de la cible fixée est un stimulus).
            if valide:
                self._t_derniere = maintenant
                self.cible, self.couleur = indice, COULEUR_DECODEE
            return
        if not self._attente:
            self.ignorees += 1
            return
        self._attente = False
        self.rattachees += 1
        if not valide:
            self._efface()        # −1 : le moteur s'est abstenu — ni juste ni faux, pas d'anneau
        else:
            self.cible, self.couleur = indice, COULEUR_DECODEE

    def dessiner(self, pygame, surface, centres, rayon):
        """Appelée à CHAQUE image, après les cibles et avant le texte. Ne dessine que s'il y a un
        anneau ; un appel sans anneau est une image sans anneau, et c'est ce que les gardes de
        l'ordre de lecture comptent."""
        if self.cible is not None:
            dessine_anneau(pygame, surface, centres[self.cible], rayon, self.couleur)

    def bilan(self, prefixe):
        """Une ligne au terminal : combien de décisions, combien rattachées, combien ignorées."""
        connu = getattr(self.source, "connexions", None)
        if connu == 0:
            ailleurs = getattr(self.source, "etrangers", 0)
            print(f"{prefixe} retour : le flux décodé n'a JAMAIS été trouvé sur cette machine — "
                  f"aucun anneau n'a pu être dessiné. Le mode était-il démarré ?"
                  + (f" ({ailleurs} flux du même nom, publiés par une AUTRE machine, ignorés)"
                     if ailleurs else ""))
        elif self.par_essai:
            print(f"{prefixe} retour : {self.recues} décision(s) reçue(s), {self.rattachees} "
                  f"rattachée(s) à un essai, {self.ignorees} ignorée(s) (hors de la fenêtre de "
                  f"retour de l'essai fermé)")
        else:
            print(f"{prefixe} retour : {self.recues} décision(s) reçue(s)")

    def fermer(self):
        self.source.fermer()


def dessine_anneau(pygame, surface, centre, rayon, couleur):
    """L'anneau, tracé vers l'intérieur de `rayon`. UN seul geste de dessin pour les trois
    fenêtres — c'est aussi lui que les `--smoke` instrumentent pour garder le fond."""
    pygame.draw.circle(surface, couleur, (int(centre[0]), int(centre[1])), int(rayon),
                       EPAISSEUR_PX)


def anneaux_a_l_ecran(surface, centres, rayon):
    """`[(indice, couleur), ...]` des cibles RÉELLEMENT entourées, lues dans les PIXELS.

    Quatre points sur l'anneau (droite, gauche, bas, haut), à mi-épaisseur : un texte posé plus
    tard sur l'un d'eux n'efface pas les trois autres. On ne demande pas à `Retour` ce qu'il croit
    afficher — il ne peut que se donner raison."""
    largeur, hauteur = surface.get_width(), surface.get_height()
    rho = int(rayon) - EPAISSEUR_PX // 2
    vus = []
    for i, (x, y) in enumerate(centres):
        x, y = int(x), int(y)
        for px, py in ((x + rho, y), (x - rho, y), (x, y + rho), (x, y - rho)):
            if 0 <= px < largeur and 0 <= py < hauteur:
                c = tuple(surface.get_at((px, py)))[:3]
                if c in COULEURS:
                    vus.append((i, c))
                    break
    return vus


def dessine_croix(pygame, surface, centre, couleur):
    """La croix de fixation : celle du repos du SSVEP guidé, et celle de l'essai libre tant que le
    moteur se repose. UN geste de dessin, instrumenté comme l'anneau par les `--smoke` — d'où
    l'appel par le MODULE dans les fenêtres (`_retour.dessine_croix`), jamais un nom importé."""
    _trace_croix(pygame, surface, centre, couleur)


def _trace_croix(pygame, surface, centre, couleur):
    x, y = int(centre[0]), int(centre[1])
    pygame.draw.line(surface, couleur, (x - CROIX_PX, y), (x + CROIX_PX, y), CROIX_EPAISSEUR_PX)
    pygame.draw.line(surface, couleur, (x, y - CROIX_PX), (x, y + CROIX_PX), CROIX_EPAISSEUR_PX)


def croix_a_l_ecran(surface, centre, couleur):
    """La croix est-elle RÉELLEMENT affichée ? Lue dans les PIXELS, aux bouts de ses branches (le
    centre suffirait, mais un bout tient compte d'une croix tronquée)."""
    x, y = int(centre[0]), int(centre[1])
    return all(tuple(surface.get_at(p))[:3] == tuple(couleur)
               for p in ((x, y), (x - CROIX_PX + 1, y), (x, y + CROIX_PX - 1)))


def pixels_non_fond_sous_anneau(pygame, surface, centre, rayon, fond=(0, 0, 0)):
    """Combien des pixels que l'anneau VA couvrir ne sont pas du fond. 0 = il ne touche rien.

    Appelée par les `--smoke` JUSTE AVANT le tracé, sur l'image composée jusque-là (cibles,
    contours, consigne, étiquettes) : c'est la preuve, image par image, que l'anneau ne recouvre
    aucun pixel de cible. Le masque est celui du MÊME tracé, sur une surface vierge."""
    r = int(rayon)
    return _pixels_non_fond_sous(
        pygame, surface, centre, r, fond,
        lambda tampon: pygame.draw.circle(tampon, (255, 255, 255), (r, r), r, EPAISSEUR_PX))


def pixels_non_fond_sous_croix(pygame, surface, centre, fond=(0, 0, 0)):
    """Le jumeau pour la croix : combien des pixels qu'elle VA couvrir ne sont pas du fond."""
    r = CROIX_PX + CROIX_EPAISSEUR_PX
    return _pixels_non_fond_sous(
        pygame, surface, centre, r, fond,
        lambda tampon: _trace_croix(pygame, tampon, (r, r), (255, 255, 255)))


def _pixels_non_fond_sous(pygame, surface, centre, r, fond, trace):
    import numpy as np

    cx, cy = int(centre[0]), int(centre[1])
    tampon = pygame.Surface((2 * r + 1, 2 * r + 1))
    tampon.fill((0, 0, 0))
    trace(tampon)
    masque = pygame.surfarray.array3d(tampon)[:, :, 0] > 0
    zone = pygame.Rect(cx - r, cy - r, 2 * r + 1, 2 * r + 1).clip(surface.get_rect())
    if zone.width == 0 or zone.height == 0:
        return 0
    pixels = pygame.surfarray.array3d(surface.subsurface(zone))
    dx, dy = zone.x - (cx - r), zone.y - (cy - r)
    masque = masque[dx:dx + zone.width, dy:dy + zone.height]
    return int((np.any(pixels != np.array(fond), axis=2) & masque).sum())


# --- Ce que les trois `--smoke` appellent ---------------------------------------------------

class SourceFactice:
    """Une source de décisions SANS réseau, pilotée par le test. `donne()` empile des décisions ;
    `tirer()` les rend toutes. `trace`, si fournie, reçoit `("lecture",)` à chaque tirage — c'est
    ce qui permet de vérifier QUAND la fenêtre lit."""

    def __init__(self, trace=None):
        self.file = []
        self.trace = trace
        self.lectures = 0
        self.fermee = False

    def donne(self, indice, ts=0.0):
        self.file.append((float(ts), int(indice)))

    def tirer(self):
        self.lectures += 1
        if self.trace is not None:
            self.trace.append(("lecture",))
        sortie, self.file = self.file, []
        return sortie

    def fermer(self):
        self.fermee = True


class SourceScriptee(SourceFactice):
    """Rend la décision `script[n]` à la n-ième lecture (1 = la première). Pour le régime CONTINU :
    la lecture n suit l'image n-1 (0-based), donc l'anneau change à l'image n."""

    def __init__(self, script, trace=None):
        super().__init__(trace)
        self.script = dict(script)

    def tirer(self):
        sortie = super().tirer()
        if self.lectures in self.script:
            sortie.append((0.0, int(self.script[self.lectures])))
        return sortie


class StatutScripte:
    """Un flux `status` FACTICE : rend la phase `script[n]` à la n-ième lecture (même convention
    que `SourceScriptee` : la croix change à l'image n). Aucune trace : seule la lecture des
    DÉCISIONS est comptée par `ordre_de_lecture`, et celle-ci la suit dans le même geste."""

    def __init__(self, script):
        self.script, self.lectures, self.fermee = dict(script), 0, False

    def tirer(self):
        self.lectures += 1
        return [(0.0, self.script[self.lectures])] if self.lectures in self.script else []

    def fermer(self):
        self.fermee = True


class MoteurFactice(SourceFactice):
    """Une source FACTICE qui RÉPOND aux marqueurs de la fenêtre comme le ferait le moteur.

    À chaque marqueur `depart`, l'entrée suivante du `script` devient la décision de l'essai, rendue
    `delai` plus tard — en LECTURES (images : insensible à la charge de la machine) ou en secondes
    (`secondes=True`, pour le SSVEP, dont la fixation n'a pas de marqueur de fin). Entrées :
    "juste" (la cible du dernier `cue`), "faux" (une autre), "rien" (−1), "tard" (juste, mais rendue
    2 lectures APRÈS le marqueur `ouverture` suivant — l'essai d'après a commencé), ou un entier.
    `attendues` garde, par essai, `(entrée, indice rendu, cible désignée)` : c'est la vérité du
    test, construite par le MOTEUR factice et jamais lue dans `Retour`."""

    def __init__(self, n_cibles, script, depart, ouverture, delai, secondes=False, trace=None):
        super().__init__(trace)
        self.n_cibles, self.script = int(n_cibles), list(script)
        self.depart, self.ouverture = depart, ouverture
        self.delai, self.secondes = delai, bool(secondes)
        self.verite = None
        self.attendues = []
        self._dues = []          # [(unité, échéance, indice)]
        self._tardives = []

    def marqueur(self, m):
        evenement = m.get("event")
        if evenement == self.ouverture and self._tardives:
            self._dues += [("lectures", self.lectures + 2, i) for i in self._tardives]
            self._tardives = []
        if evenement == "cue":
            self.verite = int(m["target"])
        if evenement == self.depart and self.script:
            quoi, v = self.script.pop(0), self.verite
            indice = (int(quoi) if not isinstance(quoi, str) else
                      {"juste": v, "tard": v, "rien": -1}.get(quoi, None))
            if quoi == "faux":
                indice = (v + 1) % self.n_cibles
            self.attendues.append((quoi, indice, v))
            if quoi == "tard":
                self._tardives.append(indice)
            elif self.secondes:
                self._dues.append(("secondes", time.perf_counter() + self.delai, indice))
            else:
                self._dues.append(("lectures", self.lectures + self.delai, indice))

    def tirer(self):
        sortie = super().tirer()
        maintenant = {"secondes": time.perf_counter(), "lectures": self.lectures}
        pretes = [d for d in self._dues if d[1] <= maintenant[d[0]]]
        self._dues = [d for d in self._dues if d[1] > maintenant[d[0]]]
        return sortie + [(0.0, int(i)) for _u, _e, i in pretes]


def anneau_attendu(quoi, indice, _verite=None):
    """Ce que l'écran doit montrer à la fin de la fenêtre de retour d'un essai : `[(i, couleur)]`
    ou `[]`. Écrit à partir du SCRIPT du moteur factice, pas de l'état de `Retour`. La cible
    désignée (3e champ de `attendues`) ne change plus rien : l'anneau est vert, juste ou faux —
    il entoure la cible DÉCIDÉE (« faux » = autour d'une autre que la désignée)."""
    if quoi in ("rien", "tard") or indice is None or indice < 0:
        return []
    return [(indice, COULEUR_DECODEE)]


class Instrumentation:
    """Les espions communs aux trois `--smoke`, posés et RETIRÉS (`with`) :

    • `Retour.dessiner` ajoute `("dessin",)` à `trace` — une entrée par image, ce qui situe chaque
      lecture par rapport au flip (cf. `ordre_de_lecture`) ;
    • `dessine_anneau` compte, AVANT chaque tracé, les pixels non-fond qu'il va couvrir
      (`violations`) — la preuve image par image qu'aucune cible n'est touchée ; `traces` dit que
      l'anneau a bien été tracé (une garde qui ne voit aucun anneau ne prouve rien) ;
    • `dessine_croix`, de même : ses pixels non-fond comptent dans `violations`, ses tracés dans
      `croix`."""

    def __init__(self, trace, fond=(0, 0, 0)):
        self.trace, self.fond = trace, fond
        self.violations = self.traces = self.croix = 0

    def __enter__(self):
        import sys

        self._mod = sys.modules[__name__]
        self._vrai_trace, self._vrai_dessiner = self._mod.dessine_anneau, Retour.dessiner
        self._vraie_croix = self._mod.dessine_croix

        def trace_garde(pygame, surface, centre, rayon, couleur):
            self.violations += pixels_non_fond_sous_anneau(pygame, surface, centre, rayon,
                                                           self.fond)
            self.traces += 1
            return self._vrai_trace(pygame, surface, centre, rayon, couleur)

        def croix_gardee(pygame, surface, centre, couleur):
            self.violations += pixels_non_fond_sous_croix(pygame, surface, centre, self.fond)
            self.croix += 1
            return self._vraie_croix(pygame, surface, centre, couleur)

        def dessiner(retour, *a, **k):
            self.trace.append(("dessin",))
            return self._vrai_dessiner(retour, *a, **k)

        self._mod.dessine_anneau, Retour.dessiner = trace_garde, dessiner
        self._mod.dessine_croix = croix_gardee
        return self

    def __exit__(self, *_exc):
        self._mod.dessine_anneau, Retour.dessiner = self._vrai_trace, self._vrai_dessiner
        self._mod.dessine_croix = self._vraie_croix
        return False


def ordre_de_lecture(trace, evenements_d_image):
    """Les violations de « la lecture vient APRÈS le flip et le marqueur de son image ».

    `trace` : suite de `("dessin",)`, `("flip", …)`, `("push", evenement)`, `("lecture",)`.
    Deux fautes possibles, et ce sont les deux mutations qu'on veut voir rougir :
    • lire entre le dessin et le flip — l'événement image qui PRÉCÈDE la lecture est un dessin ;
    • lire entre le flip et le marqueur de cette image — un marqueur `evenements_d_image` SUIT la
      lecture avant le prochain dessin. (`round_end`, `calib_end`… ne sont attachés à aucune
      image : ils peuvent légitimement suivre.)"""
    fautes = []
    dernier_image = None          # "dessin" ou "flip" : le dernier geste d'image vu
    lecture_ouverte = None        # rang de la dernière lecture, tant qu'aucun dessin ne la suit
    for rang, e in enumerate(trace):
        quoi = e[0]
        if quoi == "dessin":
            dernier_image, lecture_ouverte = "dessin", None
        elif quoi == "flip":
            dernier_image, lecture_ouverte = "flip", None
        elif quoi == "lecture":
            if dernier_image == "dessin":
                fautes.append((rang, "lecture AVANT le flip"))
            lecture_ouverte = rang
        elif quoi == "push" and lecture_ouverte is not None and e[1] in evenements_d_image:
            fautes.append((rang, f"marqueur « {e[1]} » APRÈS la lecture"))
    return fautes


def autotest_etat(chk):
    """La machine à états de `Retour`, en pur, avec une horloge et une source factices."""
    t = [0.0]
    src = SourceFactice()
    r = Retour(src, 6, horloge=lambda: t[0])
    src.donne(3)
    r.lire()
    chk(r.anneau == (3, COULEUR_DECODEE), f"[retour] libre : l'anneau suit la décision ({r.anneau})")
    src.donne(1)
    src.donne(4)
    r.lire()
    chk(r.anneau == (4, COULEUR_DECODEE),
        f"[retour] …la DERNIÈRE d'un paquet, pas la première ({r.anneau})")
    t[0] += PERIME_S * 0.5
    src.donne(-1)
    r.lire()
    chk(r.anneau == (4, COULEUR_DECODEE),
        f"[retour] …un −1 ne l'efface PAS : il tient (un anneau qui clignote à 5 Hz à côté de la "
        f"cible fixée serait un stimulus) ({r.anneau})")
    src.donne(9)
    r.lire()
    chk(r.anneau == (4, COULEUR_DECODEE),
        f"[retour] …ni un indice hors des cibles ({r.anneau})")
    t[0] += PERIME_S * 0.6
    src.donne(-1)
    r.lire()
    chk(r.anneau is None,
        f"[retour] …mais il s'efface {PERIME_S:g} s après la dernière décision VALIDE, même sous "
        f"une pluie de −1 : un −1 ne le prolonge pas ({r.anneau})")
    src.donne(2)
    r.lire()
    t[0] += PERIME_S * 0.9
    r.lire()
    tient = r.anneau
    t[0] += PERIME_S * 0.2
    r.lire()
    chk(tient == (2, COULEUR_DECODEE) and r.anneau is None,
        f"[retour] …et quand plus rien n'arrive depuis {PERIME_S:g} s : un mode arrêté ne laisse "
        f"pas un anneau figé ({tient} puis {r.anneau})")

    src = SourceFactice()
    r = Retour(src, 6, par_essai=True, horloge=lambda: t[0])
    src.donne(2)
    r.lire()
    chk(r.anneau is None and r.ignorees == 1,
        "[retour] par essai : une décision qui arrive PENDANT une mesure est ignorée")
    r.mesure_finie()
    src.donne(2)
    src.donne(5)
    r.lire()
    chk(r.anneau == (2, COULEUR_DECODEE) and r.ignorees == 2,
        f"[retour] l'anneau VERT entoure la décision, et UNE décision par essai : la seconde est "
        f"ignorée ({r.anneau})")
    chk(r.attend is False, "[retour] …et l'essai n'attend plus rien une fois sa décision reçue")
    t[0] += 30.0
    r.lire()
    chk(r.anneau == (2, COULEUR_DECODEE),
        "[retour] …l'anneau d'un essai ne périme PAS : il tient jusqu'à l'essai suivant")
    r.mesure_commence()
    chk(r.anneau is None, "[retour] …et s'efface quand l'essai suivant commence sa mesure")
    r.mesure_finie()
    src.donne(4)
    r.lire()
    chk(r.anneau == (4, COULEUR_DECODEE),
        f"[retour] une décision sur une AUTRE cible : même anneau vert, autour de la cible DÉCIDÉE "
        f"— pas de rouge, l'erreur se voit d'elle-même ({r.anneau})")
    r.mesure_commence()
    r.mesure_finie()
    r.mesure_commence()
    src.donne(0)                      # la décision de l'essai 0 arrive APRÈS le début du suivant
    r.lire()
    r.mesure_finie()
    src.donne(5)
    r.lire()
    chk(r.anneau == (5, COULEUR_DECODEE) and r.rattachees == 3,
        f"[retour] une décision TARDIVE est perdue, elle ne décale pas les suivantes : l'essai "
        f"d'après reçoit la sienne ({r.anneau}, {r.rattachees} rattachées)")
    r.mesure_commence()
    r.mesure_finie()
    chk(r.attend, "[retour] un essai fermé ATTEND sa décision (ce que guette l'écran final P300)")
    src.donne(-1)
    r.lire()
    chk(r.anneau is None, "[retour] −1 en test : AUCUN anneau — s'abstenir n'est pas se tromper")

    # La croix de repos : `ReposDuMoteur`, en pur.
    class _Phases:
        def __init__(self):
            self.file = []

        def tirer(self):
            sortie, self.file = self.file, []
            return sortie

        def fermer(self):
            pass

    t = [0.0]
    ph = _Phases()
    rep = ReposDuMoteur(ph, absent_s=10.0, horloge=lambda: t[0])
    chk(rep.en_repos, "[repos] avant tout `status` : croix (la fenêtre s'ouvre en chauffe)")
    vus = []
    for phase in ("warmup", "baseline", "decoding", "baseline", "decoding", "calibrating"):
        ph.file.append((0.0, phase))
        rep.lire()
        vus.append(rep.en_repos)
    chk(vus == [True, True, False, True, False, False],
        f"[repos] croix en chauffe et au plancher, aucune en décodage — et de NOUVEAU quand le "
        f"moteur refait son repos ({vus})")
    t2 = [0.0]
    muet = ReposDuMoteur(_Phases(), absent_s=10.0, horloge=lambda: t2[0])
    t2[0] = 9.0
    avant = muet.en_repos
    t2[0] = 11.0
    chk(avant and not muet.en_repos,
        "[repos] sans un seul `status` en 10 s, la croix TOMBE : une croix éternelle bloquerait "
        "l'essai")


def autotest_source(chk):
    """`SourceDecisions` sur un VRAI flux LSL, au nom unique : la résolution en tâche de fond, la
    lecture qui n'attend jamais, la perte qui se re-résout, et l'arrêt du fil."""
    from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet

    nom = f"EEG_API_Unicorn_retour_smoke_{os.getpid()}"
    src = SourceDecisions(nom=nom, passe_s=0.2)
    sortie = None
    try:
        t0 = time.perf_counter()
        vide = src.tirer()
        chk(vide == [] and time.perf_counter() - t0 < 0.05,
            "[retour] tant que le flux n'existe pas, `tirer()` rend [] SANS attendre")
        sortie = StreamOutlet(StreamInfo(nom, "Decoded", 3, IRREGULAR_RATE, "float32",
                                         f"retour-smoke-{os.getpid()}"))
        pire, fin = 0.0, time.perf_counter() + 10.0
        while not src.connecte and time.perf_counter() < fin:
            t0 = time.perf_counter()
            src.tirer()
            pire = max(pire, time.perf_counter() - t0)
            time.sleep(0.01)
        chk(src.connecte, "[retour] le fil trouve, PAR SON NOM, un flux apparu après lui")
        chk(pire < 0.05, f"[retour] …sans qu'une lecture n'attende jamais (pire {pire * 1000:.1f} ms)")
        recu, fin = [], time.perf_counter() + 5.0
        for v in (float("inf"), float("nan"), 2.0, float("-inf"), -1.0):
            sortie.push_sample([v, 0.0, 0.0])
        while len(recu) < 2 and time.perf_counter() < fin:
            recu += src.tirer()
            time.sleep(0.01)
        time.sleep(0.1)
        recu += src.tirer()
        chk([i for _t, i in recu] == [2, -1],
            f"[retour] la voie 0 est lue comme `target_index`, et ±inf/NaN sautent SANS lever dans "
            f"la boucle de rendu ({recu})")

        # 🔴 Un flux homonyme d'une AUTRE machine : simulé en se déclarant ailleurs — le flux de ce
        # processus devient alors, pour cette source, celui d'un autre poste de la salle.
        ailleurs = SourceDecisions(nom=nom, passe_s=0.2, hote="poste-voisin-smoke")
        try:
            fin = time.perf_counter() + 2.0
            while time.perf_counter() < fin and not ailleurs.connecte:
                time.sleep(0.05)
            chk(not ailleurs.connecte and ailleurs.connexions == 0 and ailleurs.etrangers >= 1
                and ailleurs._fil.is_alive(),
                f"[retour] un flux du même nom publié par une AUTRE machine est IGNORÉ, et le fil "
                f"continue de chercher un flux d'ici (branché {ailleurs.connecte}, "
                f"{ailleurs.etrangers} étranger(s) vu(s))")
        finally:
            ailleurs.fermer()

        class _Info:
            def __init__(self, hote, sid):
                self._h, self._s = hote, sid

            def hostname(self):
                return self._h

            def source_id(self):
                return self._s

        choix = flux_de_cette_machine([_Info("autre", "a"), _Info("Ici", "c"), _Info("ICI", "b")],
                                      "ici")
        chk([f.source_id() for f in choix] == ["b", "c"],
            "[retour] `flux_de_cette_machine` garde ceux d'ici (nom d'hôte SANS casse), triés par "
            "source_id")

        class _Morte:
            def pull_chunk(self, **_k):
                raise RuntimeError("flux perdu (simulé)")

            def close_stream(self):
                pass

        vrai = src._inlet
        src._inlet = _Morte()
        _referme(vrai)
        perdu = src.tirer()
        chk(perdu == [] and not src.connecte, "[retour] un flux PERDU est lâché, sans lever")
        fin = time.perf_counter() + 10.0
        while not src.connecte and time.perf_counter() < fin:
            time.sleep(0.02)
        chk(src.connecte and src.connexions == 2, "[retour] …et le fil le re-résout tout seul")
    finally:
        src.fermer()
        del sortie
    chk(not src._fil.is_alive(), "[retour] `fermer()` arrête le fil de résolution")


def autotest_resolution(chk, run, stimulus_id):
    """C-M5 : le NOM du flux se résout dans le fil APPELANT, et la fenêtre construit sa source
    AVANT `pygame.init()` — jamais un import du catalogue dans un fil pendant le rendu.

    Deux preuves : le constructeur rend une source dont le nom est DÉJÀ connu (résolu par lui, pas
    par son fil) ; et dans le texte de `run`, la construction précède l'ouverture de l'écran. La
    source se déclare d'une autre machine : elle cherche le flux de production sans jamais s'y
    brancher, donc sans rien perturber d'une console ouverte ici."""
    import inspect

    src = SourceDecisions(stimulus_id=stimulus_id, passe_s=0.2, hote="poste-voisin-smoke")
    try:
        nom = src.nom
    finally:
        src.fermer()
    chk(nom == flux_decode_de(stimulus_id),
        f"[retour] le nom du flux est connu dès le CONSTRUCTEUR (résolu dans le fil de la fenêtre, "
        f"pas dans le fil réseau) ({nom})")
    texte = inspect.getsource(run)
    ici, ecran = texte.find(f'SourceDecisions(stimulus_id="{stimulus_id}")'), texte.find(
        "pygame.init()")
    chk(0 <= ici < ecran,
        f"[retour] …et `run` construit sa source AVANT `pygame.init()` : l'import du catalogue ne "
        f"tombe jamais pendant le rendu (rangs {ici} < {ecran})")


def _teinte(rgb):
    return colorsys.rgb_to_hsv(*(c / 255.0 for c in rgb))[0] * 360.0


def _ecart_teinte(a, b):
    d = abs(_teinte(a) - _teinte(b)) % 360.0
    return min(d, 360.0 - d)


def autotest_couleurs(chk):
    """D-I2 : aucun anneau ne ressemble à une CONSIGNE. Les couleurs de consigne sont LUES dans
    les trois fenêtres (import tardif : elles importent ce module), jamais recopiées ici."""
    from stimulus import cvep, p300, ssvep

    consignes = {"cercle c-VEP": cvep.CUE, "liseré SSVEP": ssvep.CUE, "cercle P300": p300.CUE}
    ecarts = {c: round(_ecart_teinte(COULEUR_DECODEE, cc)) for c, cc in consignes.items()}
    chk(min(ecarts.values()) >= ECART_TEINTE_MIN,
        f"[retour] l'anneau n'est à moins de {ECART_TEINTE_MIN:g}° de teinte d'AUCUNE couleur de "
        f"CONSIGNE des trois fenêtres — l'anneau vert à côté du cercle vert du c-VEP d'avant se "
        f"lisait comme une consigne (écarts {ecarts})")
    partagees = [(m.__name__, k) for m in (cvep, p300, ssvep) for k, v in vars(m).items()
                 if isinstance(v, tuple) and v in COULEURS]
    chk(not partagees,
        f"[retour] …et aucune n'est employée par une fenêtre pour autre chose : la lecture des "
        f"anneaux dans les pixels se fait à la couleur EXACTE ({partagees})")


def autotest_statut(chk):
    """La croix de repos sur un VRAI flux `status` (JSON, sous un nom de TEST), et l'accord de
    `PHASES_DE_REPOS` avec la table du moteur — la seule copie de ce module, gardée ici."""
    from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet

    from core.server import EngineServer

    table = EngineServer._PHASES_PUBLIQUES
    chk({table["warmup"], table["rest"]} == set(PHASES_DE_REPOS)
        and table["running"] not in PHASES_DE_REPOS,
        f"[repos] `PHASES_DE_REPOS` {PHASES_DE_REPOS} = ce que le moteur publie pour sa chauffe et "
        f"son plancher, et pas pour son décodage ({table})")
    nom = f"EEG_API_Unicorn_statut_smoke_{os.getpid()}"
    sortie = StreamOutlet(StreamInfo(nom, "Markers", 1, IRREGULAR_RATE, "string",
                                     f"statut-smoke-{os.getpid()}"))
    src = StatutDuMoteur(nom=nom, passe_s=0.2)
    try:
        fin = time.perf_counter() + 10.0
        while not src.connecte and time.perf_counter() < fin:
            time.sleep(0.02)
        for message in ('{"phase":"baseline","running":true}', "pas du json", '{"phase":3}',
                        '[1, 2]', '{"phase":"decoding"}'):
            sortie.push_sample([message])
        recu, fin = [], time.perf_counter() + 5.0
        while len(recu) < 2 and time.perf_counter() < fin:
            recu += src.tirer()
            time.sleep(0.01)
        chk(src.connecte and [p for _t, p in recu] == ["baseline", "decoding"],
            f"[repos] le flux `status` RÉEL se lit : la `phase` de chaque message JSON, un message "
            f"illisible ou sans phase saute sans lever ({recu})")
    finally:
        src.fermer()
        del sortie
