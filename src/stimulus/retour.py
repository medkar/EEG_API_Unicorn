"""Le RETOUR EN DIRECT : la fenêtre entoure la cible que le moteur DÉCODE (option `--retour`).

Demandé au casque le 2026-10-01 : « on regarde une cible, le logiciel entoure celle qu'il pense
qu'on regarde ». Trois fenêtres le proposent — `cvep.py`, `ssvep.py`, `p300.py` — et ce module est
leur SEULE écriture du geste, comme `garde.py` l'est pour leurs gardes : trois copies d'un fil
réseau et d'une règle de rattachement divergeraient au premier correctif.

Trois morceaux :

1. **`SourceDecisions` — la fenêtre écoute le flux DÉCODÉ PUBLIC de son mode**, exactement comme
   l'application d'un étudiant : par son NOM (`core.lsl_io.stream_name`, suffixe LU dans le
   `ModeSpec` du mode qui déclare cette fenêtre). Aucun flux nouveau, aucun contrat nouveau : notre
   propre fenêtre devient un client du contrat public, et l'éprouve à chaque séance. Voie 0 =
   `target_index`, −1 = « pas de décision ».
   ⚠️ **La résolution vit dans un FIL, jamais dans la boucle de rendu.** `resolve_byprop` attend
   jusqu'à son délai quand le flux n'existe pas encore ; dans la boucle, c'est une image figée — et
   une image figée est une cible qui cesse de clignoter (SSVEP) ou une phase qui glisse (c-VEP).
   La boucle ne fait que `pull_chunk(timeout=0.0)` : jamais une attente.

2. **`Retour` — l'état de l'anneau**, en pur (ni pygame, ni réseau : testable sans écran).
   Deux régimes :
   - **continu** (c-VEP et SSVEP en libre, ~5 Hz) : l'anneau suit la DERNIÈRE décision, disparaît
     sur −1, et s'efface si plus rien n'arrive depuis `PERIME_S` (un mode arrêté ne doit pas
     laisser un anneau figé qui aurait l'air d'une décision) ;
   - **par essai** (les tests guidés, et le P300 qui décide une fois par manche) : la fenêtre dit
     quand un essai se FERME (`mesure_finie`) et quand le suivant COMMENCE sa mesure
     (`mesure_commence`). En test, elle connaît la cible désignée : VERT si juste, ROUGE sinon.

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
   Pourquoi l'effacer au début de la mesure suivante : un anneau coloré autour d'une AUTRE cible
   pendant qu'on enregistre la suivante est un distracteur placé exactement où il ne faut pas.

3. **`dessine_anneau` / `anneaux_a_l_ecran`** — le dessin, et sa relecture dans les PIXELS pour les
   `--smoke` (même famille de sonde que la phase c-VEP ou la cible SSVEP).
   ⚠️ **L'anneau ne touche JAMAIS un pixel de cible.** Chaque fenêtre le trace dans une bande VIDE
   de sa géométrie, et ses `--smoke` le vérifient à chaque image par `pixels_non_fond_sous_anneau` :
   tout pixel que l'anneau va couvrir doit être du FOND au moment où il est tracé. Les tests qui
   lisent la phase ou la consigne dans les pixels restent donc vrais anneau affiché.

⚠️ `−1` en test guidé : AUCUN anneau. Le moteur s'est abstenu ; ce n'est ni juste ni faux — c'est
la règle des tests (« −1 = silence, jamais une erreur »), et la peindre en rouge mentirait.

Pas d'autotest propre : les trois `--smoke` de fenêtre appellent `autotest_etat` et
`autotest_source` d'ici, en plus de leurs gardes de câblage.
"""

import os
import socket
import threading
import time

from pylsl import StreamInlet, resolve_byprop

# --- Couleurs : chacune n'existe NULLE PART ailleurs dans les trois fenêtres -------------------
# C'est ce qui permet aux `--smoke` de relire l'anneau dans les pixels à la couleur EXACTE (aucun
# lissage : `pygame.draw.circle` ne lisse pas). Une couleur partagée avec un décor ferait trouver un
# anneau là où il n'y en a pas.
COULEUR_LIBRE = (255, 170, 0)    # ambre : « voici ce que le moteur décode », sans jugement
COULEUR_JUSTE = (0, 230, 0)      # test : la décision est la cible désignée
COULEUR_FAUX = (255, 40, 40)     # test : la décision est une AUTRE cible
COULEURS = (COULEUR_LIBRE, COULEUR_JUSTE, COULEUR_FAUX)
EPAISSEUR_PX = 4                 # tracée vers l'INTÉRIEUR du rayon donné (convention de pygame)

# Régime continu : passé ce délai sans décision, l'anneau s'efface. 5 publications manquées à 5 Hz.
PERIME_S = 1.0

# Une passe de résolution. Courte : avec `minimum=32`, chaque passe consomme tout son délai (on ne
# trouvera jamais 32 flux), et c'est aussi le temps que met `fermer()` à arrêter le fil.
PASSE_S = 0.5
OUVERTURE_S = 2.0


def flux_decode_de(stimulus_id):
    """Le NOM PUBLIC du flux décodé que lit la fenêtre `stimulus_id`. Lève si aucun mode ne la
    déclare.

    Lu dans le `ModeSpec` du mode dont `stimulus_id` est cette fenêtre — jamais écrit ici : le nom
    d'un flux est du contrat public, et une seconde écriture dériverait. Import TARDIF (le
    catalogue des modes coûte ~2 s) : la fenêtre l'appelle dans son fil, pas avant d'ouvrir.
    """
    from core.lsl_io import stream_name
    from core.modes import registry as modes

    suffixes = [s.stream for s in modes.MODES if s.stimulus_id == stimulus_id and s.stream]
    if len(suffixes) != 1:
        raise LookupError(f"aucun mode (ou plusieurs) ne déclare la fenêtre « {stimulus_id} » "
                          f"avec un flux décodé ({suffixes})")
    return stream_name(suffixes[0])


class SourceDecisions:
    """Le flux décodé du mode, résolu en tâche de fond. `tirer()` ne bloque JAMAIS.

    `recover=False`, comme `core.markers.MarkerInlet` et pour la raison qu'il a mesurée : un inlet
    qui « récupère » attend le retour de l'ANCIEN émetteur (même `source_id`) ; un moteur relancé
    sous une autre identité ne reviendrait jamais. Ici une disparition LÈVE dans `tirer()`, l'inlet
    est lâché, et le fil re-résout tout seul.

    Plusieurs flux du même nom (une salle de TP) : on préfère celui de CETTE machine — c'est la
    console d'ici qui a lancé cette fenêtre, et son moteur tourne ici — puis le `source_id`, pour
    un choix reproductible ; et on le DIT.
    """

    def __init__(self, stimulus_id=None, nom=None, passe_s=PASSE_S):
        self._stimulus_id = stimulus_id
        self.nom = nom
        self.passe_s = float(passe_s)
        self._inlet = None
        self._verrou = threading.Lock()
        self._arret = threading.Event()
        self.refus = ""
        self.connexions = 0
        self._fil = threading.Thread(target=self._boucle, daemon=True,
                                     name=f"retour-{stimulus_id or nom}")
        self._fil.start()

    @property
    def connecte(self):
        return self._inlet is not None

    def _boucle(self):
        if self.nom is None:
            try:
                self.nom = flux_decode_de(self._stimulus_id)
            except Exception as e:  # noqa: BLE001 - un fil qui meurt en silence serait pire
                self.refus = f"{type(e).__name__} : {e}"
                print(f"[retour] ⚠️ pas de retour : {self.refus}")
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
                    print(f"[retour] branché sur « {self.nom} » : la cible décodée sera entourée")
                elif not attente_dite:
                    attente_dite = True
                    print(f"[retour] « {self.nom} » n'existe pas encore sur le réseau — je le "
                          f"cherche en tâche de fond (le mode est-il démarré ?)")
            self._arret.wait(0.1)

    def _connecte(self):
        try:
            flux = resolve_byprop("name", self.nom, minimum=32, timeout=self.passe_s)
        except Exception as e:  # noqa: BLE001 - le réseau casse de mille façons
            self.refus = f"recherche impossible ({type(e).__name__} : {e})"
            return None
        if not flux:
            return None
        ici = socket.gethostname()
        flux = sorted(flux, key=lambda f: (f.hostname() != ici, f.source_id() or "",
                                           f.hostname() or ""))
        if len(flux) > 1:
            print(f"[retour] ⚠️ {len(flux)} flux s'appellent « {self.nom} » : j'écoute "
                  f"« {flux[0].source_id()} » sur {flux[0].hostname()} (cette machine d'abord)")
        inlet = None
        try:
            inlet = StreamInlet(flux[0], max_buflen=6, recover=False)
            # Obligatoire AVANT la première lecture : un inlet ne se connecte qu'à la première
            # lecture, et ne rejoue rien de ce qui précède (même piège que `MarkerInlet.resolve`).
            inlet.open_stream(timeout=OUVERTURE_S)
        except Exception as e:  # noqa: BLE001 - un moteur qui meurt pendant la connexion
            if inlet is not None:
                _referme(inlet)
            self.refus = f"connexion impossible ({type(e).__name__} : {e})"
            return None
        return inlet

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
        sortie = []
        for ligne, ts in zip(valeurs, horodatages):
            if ligne and ligne[0] == ligne[0]:          # NaN != NaN : une valeur illisible saute
                sortie.append((float(ts), int(round(float(ligne[0])))))
        return sortie

    def fermer(self):
        """Arrête le fil et lâche l'inlet. Ne lève jamais."""
        self._arret.set()
        with self._verrou:
            inlet, self._inlet = self._inlet, None
        if inlet is not None:
            _referme(inlet)
        self._fil.join(timeout=self.passe_s + 1.0)


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
        self._verite = None        # la cible désignée de cet essai (None = libre)
        self._t_derniere = None
        self.recues = self.rattachees = self.ignorees = 0

    @property
    def anneau(self):
        return None if self.cible is None else (self.cible, self.couleur)

    def _efface(self):
        self.cible = self.couleur = None

    def mesure_commence(self):
        """L'essai suivant commence sa MESURE : l'anneau s'efface, et une décision qui arriverait
        encore pour l'essai précédent sera ignorée (cf. la règle de rattachement)."""
        self._attente, self._verite = False, None
        self._efface()

    def mesure_finie(self, verite=None):
        """Un essai vient de se fermer : la PROCHAINE décision reçue est la sienne. `verite` = la
        cible désignée (test), None en libre (anneau ambre)."""
        self._attente = True
        self._verite = None if verite is None else int(verite)

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
            self._t_derniere = maintenant
            self.cible, self.couleur = (indice, COULEUR_LIBRE) if valide else (None, None)
            return
        if not self._attente:
            self.ignorees += 1
            return
        self._attente = False
        self.rattachees += 1
        if not valide:
            self._efface()        # −1 : le moteur s'est abstenu — ni juste ni faux, pas d'anneau
        elif self._verite is None:
            self.cible, self.couleur = indice, COULEUR_LIBRE
        else:
            self.cible = indice
            self.couleur = COULEUR_JUSTE if indice == self._verite else COULEUR_FAUX

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
            print(f"{prefixe} retour : le flux décodé n'a JAMAIS été trouvé — aucun anneau n'a pu "
                  f"être dessiné. Le mode était-il démarré ?")
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


def pixels_non_fond_sous_anneau(pygame, surface, centre, rayon, fond=(0, 0, 0)):
    """Combien des pixels que l'anneau VA couvrir ne sont pas du fond. 0 = il ne touche rien.

    Appelée par les `--smoke` JUSTE AVANT le tracé, sur l'image composée jusque-là (cibles,
    contours, consigne, étiquettes) : c'est la preuve, image par image, que l'anneau ne recouvre
    aucun pixel de cible. Le masque est celui du MÊME tracé, sur une surface vierge."""
    import numpy as np

    cx, cy, r = int(centre[0]), int(centre[1]), int(rayon)
    tampon = pygame.Surface((2 * r + 1, 2 * r + 1))
    tampon.fill((0, 0, 0))
    pygame.draw.circle(tampon, (255, 255, 255), (r, r), r, EPAISSEUR_PX)
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


def anneau_attendu(quoi, indice, verite):
    """Ce que l'écran doit montrer à la fin de la fenêtre de retour d'un essai : `[(i, couleur)]`
    ou `[]`. Écrit à partir du SCRIPT du moteur factice, pas de l'état de `Retour`."""
    if quoi in ("rien", "tard") or indice is None or indice < 0:
        return []
    if verite is None:
        return [(indice, COULEUR_LIBRE)]
    return [(indice, COULEUR_JUSTE if indice == verite else COULEUR_FAUX)]


class Instrumentation:
    """Les espions communs aux trois `--smoke`, posés et RETIRÉS (`with`) :

    • `Retour.dessiner` ajoute `("dessin",)` à `trace` — une entrée par image, ce qui situe chaque
      lecture par rapport au flip (cf. `ordre_de_lecture`) ;
    • `dessine_anneau` compte, AVANT chaque tracé, les pixels non-fond qu'il va couvrir
      (`violations`) — la preuve image par image qu'aucune cible n'est touchée ; `traces` dit que
      l'anneau a bien été tracé (une garde qui ne voit aucun anneau ne prouve rien)."""

    def __init__(self, trace, fond=(0, 0, 0)):
        self.trace, self.fond = trace, fond
        self.violations = self.traces = 0

    def __enter__(self):
        import sys

        self._mod = sys.modules[__name__]
        self._vrai_trace, self._vrai_dessiner = self._mod.dessine_anneau, Retour.dessiner

        def trace_garde(pygame, surface, centre, rayon, couleur):
            self.violations += pixels_non_fond_sous_anneau(pygame, surface, centre, rayon,
                                                           self.fond)
            self.traces += 1
            return self._vrai_trace(pygame, surface, centre, rayon, couleur)

        def dessiner(retour, *a, **k):
            self.trace.append(("dessin",))
            return self._vrai_dessiner(retour, *a, **k)

        self._mod.dessine_anneau, Retour.dessiner = trace_garde, dessiner
        return self

    def __exit__(self, *_exc):
        self._mod.dessine_anneau, Retour.dessiner = self._vrai_trace, self._vrai_dessiner
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
    chk(r.anneau == (3, COULEUR_LIBRE), f"[retour] libre : l'anneau suit la décision ({r.anneau})")
    src.donne(1)
    src.donne(4)
    r.lire()
    chk(r.anneau == (4, COULEUR_LIBRE),
        f"[retour] …la DERNIÈRE d'un paquet, pas la première ({r.anneau})")
    src.donne(-1)
    r.lire()
    chk(r.anneau is None, f"[retour] …et disparaît sur −1 ({r.anneau})")
    src.donne(9)
    r.lire()
    chk(r.anneau is None, f"[retour] …comme sur un indice hors des cibles ({r.anneau})")
    src.donne(2)
    r.lire()
    t[0] += PERIME_S * 0.9
    r.lire()
    tient = r.anneau
    t[0] += PERIME_S * 0.2
    r.lire()
    chk(tient == (2, COULEUR_LIBRE) and r.anneau is None,
        f"[retour] …et s'efface quand plus rien n'arrive depuis {PERIME_S:g} s : un mode arrêté "
        f"ne laisse pas un anneau figé ({tient} puis {r.anneau})")

    src = SourceFactice()
    r = Retour(src, 6, par_essai=True, horloge=lambda: t[0])
    src.donne(2)
    r.lire()
    chk(r.anneau is None and r.ignorees == 1,
        "[retour] par essai : une décision qui arrive PENDANT une mesure est ignorée")
    r.mesure_finie(verite=2)
    src.donne(2)
    src.donne(5)
    r.lire()
    chk(r.anneau == (2, COULEUR_JUSTE) and r.ignorees == 2,
        f"[retour] juste = VERT, et UNE décision par essai, la seconde est ignorée ({r.anneau})")
    t[0] += 30.0
    r.lire()
    chk(r.anneau == (2, COULEUR_JUSTE),
        "[retour] …l'anneau d'un essai ne périme PAS : il tient jusqu'à l'essai suivant")
    r.mesure_commence()
    chk(r.anneau is None, "[retour] …et s'efface quand l'essai suivant commence sa mesure")
    r.mesure_finie(verite=1)
    src.donne(4)
    r.lire()
    chk(r.anneau == (4, COULEUR_FAUX), f"[retour] faux = ROUGE, autour de la cible DÉCIDÉE ({r.anneau})")
    r.mesure_commence()
    r.mesure_finie(verite=0)
    r.mesure_commence()
    src.donne(0)                      # la décision de l'essai 0 arrive APRÈS le début du suivant
    r.lire()
    r.mesure_finie(verite=5)
    src.donne(5)
    r.lire()
    chk(r.anneau == (5, COULEUR_JUSTE) and r.rattachees == 3,
        f"[retour] une décision TARDIVE est perdue, elle ne décale pas les suivantes : l'essai "
        f"d'après reçoit la sienne ({r.anneau}, {r.rattachees} rattachées)")
    r.mesure_commence()
    r.mesure_finie(verite=3)
    src.donne(-1)
    r.lire()
    chk(r.anneau is None, "[retour] −1 en test : AUCUN anneau — s'abstenir n'est pas se tromper")


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
        sortie.push_sample([2.0, 0.0, 0.0])
        sortie.push_sample([-1.0, 0.0, 0.0])
        while len(recu) < 2 and time.perf_counter() < fin:
            recu += src.tirer()
            time.sleep(0.01)
        chk([i for _t, i in recu] == [2, -1], f"[retour] la voie 0 est lue comme `target_index` ({recu})")

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
