"""La fenêtre de « Tester librement » pour le Motor Imagery : on imagine une tâche, et la fenêtre
montre ce que le modèle décode en direct.

Le Motor Imagery n'a pas de stimulus : on imagine un mouvement, rien ne clignote. Cette fenêtre
affiche donc seulement les tâches du modèle et le résultat du décodage. Elle se comporte comme
l'application d'un élève : elle écoute le flux public `decoded_mi` de cet ordinateur
(`retour.SourceDecisions`) et lit le nom des tâches dans la description de ce flux. Elle montre :

  • les tâches, en grand, une case chacune, dans l'ordre du flux ;
  • un cadre VERT autour de la tâche décodée — la même couleur et la même marge que l'anneau des
    autres fenêtres (`retour.COULEUR_DECODEE`, `retour.ANNEAU_ECART_PX`) ;
  • « rien » quand le modèle n'est pas assez sûr. Une non-réponse (−1) n'efface pas le cadre : il
    disparaît seul `retour.PERIME_S` après la dernière vraie réponse. Le moteur répond 5 fois par
    seconde : un cadre effacé à chaque non-réponse clignoterait et deviendrait illisible ;
  • une croix tant que le casque se stabilise (flux `status`, `retour.ReposDuMoteur`).

Elle n'envoie rien (ni marqueur, ni score). Les tâches viennent du flux et pas de la console : c'est
le modèle chargé par le moteur qui les connaît.

    python src/stimulus/mi.py --retour             # ce que lance « Tester librement »
    python src/stimulus/mi.py --retour --windowed  # fenêtre 1000×700 (dev)
    python src/stimulus/mi.py --smoke              # autotest headless (SDL factice), sans réseau
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import use_utf8_console  # noqa: E402
from core.i18n import tr  # noqa: E402
from stimulus import retour as _retour  # noqa: E402
from stimulus.ecran import ECRAN_SDL_PRINCIPAL  # noqa: E402 - l'écran des stimulus

FOND = (0, 0, 0)
CASE = (40, 44, 52)            # le fond d'une case de tâche : discret, jamais vert
TEXTE = (230, 230, 230)
GRIS = (140, 144, 152)
CROIX = (200, 200, 200)
TAILLE_FENETRE = (1000, 700)   # `--windowed` et `--smoke` : le test relit des pixels à cette taille
MARGE_RATIO = 0.06             # marge latérale, en part de la largeur
ESPACE_RATIO = 0.05            # espace entre deux cases, en part de la largeur
HAUTEUR_RATIO = 0.28           # hauteur d'une case, en part de la hauteur
IMAGES_S = 60                  # pas de stimulus : la cadence ne sert qu'à la réactivité


def classes_du_flux(info):
    """Les tâches que publie `decoded_mi`, dans SON ordre — lues dans la description du flux
    (`core.lsl_io.DecodedMIPublisher` : `decoding/classes`, jointes par des virgules). `()` si
    elle ne les dit pas. Ne lève jamais."""
    try:
        texte = info.desc().child("decoding").child_value("classes")
    except Exception:  # noqa: BLE001 - une description absente ou mal formée
        return ()
    return tuple(c for c in (texte or "").split(",") if c)


class DecisionsMI(_retour.SourceDecisions):
    """Le flux `decoded_mi` de cette machine, plus ses TÂCHES, lues une fois branché.

    Lues dans le fil de recherche, AVANT que l'inlet ne soit rendu à la boucle : quand la première
    décision arrive, on sait déjà ce que son indice désigne. Un moteur relancé avec un autre modèle
    recrée son flux : l'inlet est perdu, le fil re-résout, et relit les tâches.
    """

    def __init__(self, **kw):
        self.classes = ()
        super().__init__(stimulus_id="mi", **kw)

    def _connecte(self):
        inlet = super()._connecte()
        if inlet is None:
            return None
        try:
            self.classes = classes_du_flux(inlet.info(timeout=_retour.OUVERTURE_S))
        except Exception as e:  # noqa: BLE001 - un moteur qui meurt pendant la lecture
            _retour._referme(inlet)
            self.refus = f"description illisible ({type(e).__name__} : {e})"
            return None
        print(f"[mi-libre] tâches du modèle : {', '.join(self.classes) or '(aucune)'}")
        return inlet


def geometrie(taille, n):
    """Les cases des `n` tâches, `[(x, y, largeur, hauteur), ...]`, en une rangée centrée. Une
    seule écriture : le rendu et `--smoke` la partagent."""
    largeur, hauteur = taille
    if n <= 0:
        return []
    marge, espace = int(largeur * MARGE_RATIO), int(largeur * ESPACE_RATIO)
    w = (largeur - 2 * marge - (n - 1) * espace) // n
    h = int(hauteur * HAUTEUR_RATIO)
    y = (hauteur - h) // 2
    return [(marge + i * (w + espace), y, w, h) for i in range(n)]


def ligne_d_etat(connecte, en_repos, classes, decodee):
    """La phrase sous les cases : ce que l'étudiant doit lire en un coup d'œil."""
    if not connecte:
        return tr("fenetre.mi.attente")
    if en_repos:
        return tr("fenetre.mi.repos")
    if not classes:
        return tr("fenetre.mi.sans_taches")
    if decodee is None:
        return tr("fenetre.mi.rien")
    return tr("fenetre.mi.decode", tache=classes[decodee])


def _police_qui_tient(pygame, texte, largeur_max, taille_depart):
    """La plus grande police (par paliers) dans laquelle `texte` tient sur `largeur_max`."""
    taille = taille_depart
    while taille > 12:
        police = pygame.font.SysFont(None, taille)
        if police.size(texte)[0] <= largeur_max:
            return police
        taille = int(taille * 0.85)
    return pygame.font.SysFont(None, 12)


def dessiner(pygame, surface, classes, decodee, en_repos, ligne):
    """Une image. Pure par rapport à l'état reçu : `--smoke` l'appelle avec des états choisis."""
    surface.fill(FOND)
    largeur, hauteur = surface.get_size()
    if en_repos:
        _retour.dessine_croix(pygame, surface, (largeur // 2, hauteur // 2), CROIX)
    else:
        for i, (x, y, w, h) in enumerate(geometrie((largeur, hauteur), len(classes))):
            pygame.draw.rect(surface, CASE, (x, y, w, h), border_radius=12)
            police = _police_qui_tient(pygame, classes[i], w - 24, int(h * 0.38))
            rendu = police.render(classes[i], True, TEXTE)
            surface.blit(rendu, rendu.get_rect(center=(x + w // 2, y + h // 2)))
            if i == decodee:
                e = _retour.ANNEAU_ECART_PX
                pygame.draw.rect(surface, _retour.COULEUR_DECODEE,
                                 (x - e, y - e, w + 2 * e, h + 2 * e), _retour.EPAISSEUR_PX,
                                 border_radius=16)
    police = _police_qui_tient(pygame, ligne, largeur - 40, max(18, hauteur // 22))
    rendu = police.render(ligne, True, GRIS)
    surface.blit(rendu, rendu.get_rect(center=(largeur // 2, int(hauteur * 0.82))))


def run(windowed=False, secondes=None, source=None, statut=None):
    """La boucle de l'essai libre. Échap ou la croix de la fenêtre pour terminer."""
    import pygame

    source = source if source is not None else DecisionsMI()
    repos = _retour.ReposDuMoteur(statut if statut is not None else _retour.StatutDuMoteur())
    anneau = _retour.Retour(source, n_cibles=0)
    pygame.init()
    pygame.font.init()
    if windowed:
        win = pygame.display.set_mode(TAILLE_FENETRE, display=ECRAN_SDL_PRINCIPAL)
    else:
        info = pygame.display.Info()
        win = pygame.display.set_mode((info.current_w, info.current_h),
                                      pygame.FULLSCREEN | pygame.SCALED,
                                      display=ECRAN_SDL_PRINCIPAL)
    pygame.display.set_caption(tr("fenetre.mi.titre"))
    pygame.mouse.set_visible(False)
    horloge = pygame.time.Clock()
    debut = time.perf_counter()
    images = 0
    print("[mi-libre] essai libre : la fenêtre encadre la tâche que publie decoded_mi")
    try:
        while secondes is None or time.perf_counter() - debut < secondes:
            fin = False
            for e in pygame.event.get():
                if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN
                                             and e.key in (pygame.K_ESCAPE, pygame.K_q)):
                    fin = True
            if fin:
                break
            classes = tuple(getattr(source, "classes", ()))
            anneau.n_cibles = len(classes)
            repos.lire()
            anneau.lire()
            decodee = anneau.cible if anneau.cible is not None and anneau.cible < len(classes) \
                else None
            ligne = ligne_d_etat(getattr(source, "connecte", True), repos.en_repos, classes,
                                 decodee)
            dessiner(pygame, win, classes, decodee, repos.en_repos, ligne)
            pygame.display.flip()
            images += 1
            horloge.tick(IMAGES_S)
    finally:
        pygame.quit()
        anneau.bilan("[mi-libre]")
        repos.bilan("[mi-libre]")
        anneau.fermer()
        repos.fermer()
    print(f"[mi-libre] fin : essai libre terminé ({anneau.recues} décision(s) reçue(s), "
          f"{images} images)")
    return True


# --- autotest --------------------------------------------------------------------------------

class _StatutFactice:
    """Le flux `status`, sans réseau : `donne(phase)` empile une phase."""

    def __init__(self):
        self.file = []

    def donne(self, phase):
        self.file.append((0.0, phase))

    def tirer(self):
        sortie, self.file = self.file, []
        return sortie

    def fermer(self):
        pass


def _smoke():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame

    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # 1. Les tâches se lisent dans la description d'un VRAI flux `decoded_mi` — celle qu'écrit le
    #    moteur, pas une copie écrite pour le test, qui se donnerait raison.
    from core.lsl_io import DecodedMIPublisher
    pub = DecodedMIPublisher(("PIEDS", "MAINS", "REST"), instance="smoke-mi-libre")
    lues = classes_du_flux(pub.outlet.get_info())
    del pub
    chk(lues == ("PIEDS", "MAINS", "REST"),
        f"les tâches sont lues dans la description du flux publié par le moteur ({lues})")

    class _SansDescription:
        def desc(self):
            raise RuntimeError("pas de description")
    chk(classes_du_flux(_SansDescription()) == (), "…et une description illisible rend ()")

    # 2. La géométrie : de 2 à 5 tâches, les cases ET leur cadre tiennent dans la fenêtre, sans
    #    se chevaucher.
    e = _retour.ANNEAU_ECART_PX + _retour.EPAISSEUR_PX
    defauts = []
    for n in range(2, 6):
        cases = geometrie(TAILLE_FENETRE, n)
        dedans = all(x - e >= 0 and y - e >= 0 and x + w + e <= TAILLE_FENETRE[0]
                     and y + h + e <= TAILLE_FENETRE[1] for x, y, w, h in cases)
        separees = all(cases[i][0] + cases[i][2] + e <= cases[i + 1][0] - e
                       for i in range(n - 1))
        if not (len(cases) == n and dedans and separees):
            defauts.append(n)
    chk(not defauts, f"de 2 à 5 tâches, cases et cadres tiennent sans se toucher ({defauts})")

    # 3. Le rendu, lu dans les PIXELS : la croix au repos, le cadre sur la tâche décodée et elle
    #    seule, rien quand le vote ne conclut pas.
    pygame.init()
    pygame.font.init()
    surface = pygame.display.set_mode(TAILLE_FENETRE, display=ECRAN_SDL_PRINCIPAL)
    classes = ("PIEDS", "MAINS")
    cases = geometrie(TAILLE_FENETRE, len(classes))

    def cadres_verts():
        """Les cases dont le cadre est VERT, lu à mi-hauteur sur les deux bords latéraux."""
        vus = []
        for i, (x, y, w, h) in enumerate(cases):
            m = _retour.ANNEAU_ECART_PX - _retour.EPAISSEUR_PX // 2
            points = ((x - m, y + h // 2), (x + w + m - 1, y + h // 2))
            if all(tuple(surface.get_at(p))[:3] == _retour.COULEUR_DECODEE for p in points):
                vus.append(i)
        return vus

    centre = (TAILLE_FENETRE[0] // 2, TAILLE_FENETRE[1] // 2)
    dessiner(pygame, surface, classes, None, True, "")
    chk(_retour.croix_a_l_ecran(surface, centre, CROIX) and cadres_verts() == [],
        "au repos : la croix, et aucun cadre")
    dessiner(pygame, surface, classes, 1, False, "")
    chk(cadres_verts() == [1], f"MAINS décodé : son cadre est vert, et lui seul ({cadres_verts()})")
    dessiner(pygame, surface, classes, None, False, "")
    chk(cadres_verts() == [], "rien de décodé : aucun cadre")

    # 4. La boucle ENTIÈRE, sur des sources factices et une horloge à la main : la règle du
    #    cadre est celle de `retour.Retour` — un −1 ne l'efface pas, il expire seul.
    t = [0.0]
    source = _retour.SourceFactice()
    source.classes, source.connecte = classes, True
    statut = _StatutFactice()
    repos = _retour.ReposDuMoteur(statut, horloge=lambda: t[0])
    anneau = _retour.Retour(source, n_cibles=len(classes), horloge=lambda: t[0])

    def image():
        repos.lire()
        anneau.lire()
        return anneau.cible, repos.en_repos

    statut.donne("warmup")
    source.donne(0)
    _cible, au_repos = image()
    statut.donne("running")
    source.donne(0)
    t[0] = 0.1
    cible0, repos0 = image()
    source.donne(-1)
    t[0] = 0.5
    cible_moins1, _r = image()
    t[0] = 0.5 + _retour.PERIME_S + 0.2
    source.donne(-1)
    cible_expiree, _r = image()
    chk(au_repos and cible0 == 0 and not repos0 and cible_moins1 == 0 and cible_expiree is None,
        f"repos pendant la stabilisation ; PIEDS encadré ; un −1 ne l'efface pas ; il expire "
        f"{_retour.PERIME_S:g} s après la dernière décision valide ({au_repos}, {cible0}, "
        f"{cible_moins1}, {cible_expiree})")
    chk(ligne_d_etat(True, False, classes, 1) == tr("fenetre.mi.decode", tache="MAINS")
        and ligne_d_etat(True, False, classes, None) == tr("fenetre.mi.rien")
        and ligne_d_etat(False, False, (), None) == tr("fenetre.mi.attente")
        and ligne_d_etat(True, True, classes, 1) == tr("fenetre.mi.repos"),
        "la ligne d'état dit la tâche décodée, « rien », l'attente du flux, ou le repos")

    # 5. La vraie fonction `run`, quelques images, sur les sources factices : elle s'ouvre, dessine
    #    et se ferme sans lever.
    source2 = _retour.SourceFactice()
    source2.classes, source2.connecte = classes, True
    source2.donne(1)
    try:
        fait = run(windowed=True, secondes=0.3, source=source2, statut=_StatutFactice())
    except Exception as e:  # noqa: BLE001 - le test doit dire ce qui a levé
        fait = False
        print(f"    {type(e).__name__} : {e}")
    chk(fait and source2.lectures > 0, f"`run` tourne et lit le flux ({source2.lectures} lectures)")

    print(f"[mi-libre] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def main():
    use_utf8_console()
    p = argparse.ArgumentParser(description="Motor Imagery : l'essai libre (aucun stimulus)")
    p.add_argument("--retour", action="store_true",
                   help="encadre la tâche que publie decoded_mi (ce que lance « Tester librement »)")
    p.add_argument("--windowed", action="store_true", help="fenetre au lieu du plein ecran")
    p.add_argument("--seconds", type=float, default=None, help="auto-quit apres N secondes")
    p.add_argument("--smoke", action="store_true", help="test headless (SDL dummy), sans reseau")
    args = p.parse_args()
    if args.smoke:
        return 0 if _smoke() else 1
    if not args.retour:
        # Sans le flux décodé, cette fenêtre n'a RIEN à montrer : le MI n'a pas de stimulus.
        print(tr("fenetre.mi.sans_retour"))
        return 2
    run(windowed=args.windowed, secondes=args.seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
