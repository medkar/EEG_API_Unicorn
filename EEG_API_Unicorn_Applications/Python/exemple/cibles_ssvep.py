"""Une application SSVEP complète : elle affiche les cibles qui clignotent, se connecte à la
console avec les réglages de config.json, puis entoure en vert la cible décodée.

    pip install pylsl pygame
    python cibles_ssvep.py            # Échap pour quitter : le mode démarré est arrêté

Votre code va dans on_decision() : elle est appelée chaque fois qu'une nouvelle cible est
décodée. Le reste (affichage, connexion) s'utilise tel quel.
"""

import math
import sys
import threading
import time

import pygame

from eeg_api_lsl import EegApi, EegApiError, config_path, load_config

REPOS_S = 25          # chauffe (15 s) + repos (8 s) du moteur : ne fixer aucune cible
FOND = (0, 0, 0)
CIBLE = (255, 255, 255)
POINT = (220, 0, 0)
DECODEE = (0, 220, 0)
TEXTE = (150, 150, 150)


def on_decision(index, nom):
    """Votre application. Appelée chaque fois que le moteur décode une NOUVELLE cible :
    `index` est son numéro (0, 1, 2…), `nom` son nom dans config.json."""
    print(f"cible décodée : {index} ({nom})")


def lire_decisions(api, etat, noms):
    """Tourne à côté de l'affichage : lit les décisions et garde la dernière cible décodée.
    -1 veut dire « pas de décision » : ce n'est jamais la cible 0."""
    try:
        for decision in api.decisions():
            index = int(decision.get("target_index", -1))
            if index != etat["cible"]:
                etat["cible"] = index
                if 0 <= index < len(noms):
                    on_decision(index, noms[index])
    except EegApiError as e:
        print(f"ÉCHEC : {e}")
    etat["fin"] = True


def main():
    config = load_config(config_path())
    api = EegApi(config)
    try:
        api.connect()
        reponse = api.start()
    except EegApiError as e:
        print(f"ÉCHEC : {e}")
        api.close()
        return 1

    # Le moteur a choisi les fréquences : elles sont dans sa réponse au démarrage.
    reglages = reponse.get("params") or {}
    freqs = [float(f) for f in reglages["freqs"]]
    rafraichissement = float(reglages.get("refresh_hz") or config["propose_refresh_hz"])
    noms = list(reglages.get("target_names") or config["params"].get("target_names") or [])
    noms = noms[:len(freqs)]
    noms += [str(i) for i in range(len(noms), len(freqs))]
    # Une cible clignote en comptant les images : allumée la première moitié de son cycle.
    images_par_cycle = [max(2, round(rafraichissement / f)) for f in freqs]
    print("Cibles : " + ", ".join(f"{n} {f:g} Hz" for n, f in zip(noms, freqs)))

    etat = {"cible": -1, "fin": False}
    threading.Thread(target=lire_decisions, args=(api, etat, noms), daemon=True).start()

    pygame.init()
    taille = pygame.display.get_desktop_sizes()[0]
    # vsync=1 : une image par rafraîchissement de l'écran, sinon les fréquences sont fausses.
    ecran = pygame.display.set_mode(taille, pygame.FULLSCREEN | pygame.SCALED, vsync=1)
    pygame.display.set_caption("Cibles SSVEP")
    pygame.mouse.set_visible(False)
    police = pygame.font.SysFont(None, 36)
    largeur, hauteur = ecran.get_size()
    rayon = int(hauteur * 0.09)
    # Les cibles sur un cercle, la première en haut.
    centres = [(int(largeur / 2 + hauteur * 0.3 * math.sin(2 * math.pi * i / len(freqs))),
                int(hauteur / 2 - hauteur * 0.3 * math.cos(2 * math.pi * i / len(freqs))))
               for i in range(len(freqs))]

    debut = time.monotonic()
    image, fps, compte, chrono = 0, 0.0, 0, time.monotonic()
    while not etat["fin"]:
        if any(e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE)
               for e in pygame.event.get()):
            break
        ecran.fill(FOND)
        for i, (centre, cycle) in enumerate(zip(centres, images_par_cycle)):
            if image % cycle < cycle / 2:
                pygame.draw.circle(ecran, CIBLE, centre, rayon)
            pygame.draw.circle(ecran, POINT, centre, 4)
            if i == etat["cible"]:
                pygame.draw.circle(ecran, DECODEE, centre, rayon + 18, 6)
            # Le texte SOUS le disque, jamais dessus : il changerait son clignotement.
            nom = police.render(f"{noms[i]}  {freqs[i]:g} Hz", True, TEXTE)
            ecran.blit(nom, nom.get_rect(midtop=(centre[0], centre[1] + rayon + 28)))
        reste = REPOS_S - (time.monotonic() - debut)
        consigne = (f"Ne fixe aucune cible : le casque se stabilise ({math.ceil(reste)} s)"
                    if reste > 0 else "Fixe le point rouge d'une cible  ·  Échap = quitter")
        ecran.blit(police.render(consigne, True, TEXTE), (20, 20))
        ecran.blit(police.render(f"{fps:.0f} images/s (attendu : {rafraichissement:g})",
                                 True, TEXTE), (20, hauteur - 50))
        pygame.display.flip()
        image += 1
        compte += 1
        if time.monotonic() - chrono >= 1.0:
            fps, compte, chrono = compte / (time.monotonic() - chrono), 0, time.monotonic()

    pygame.quit()
    api.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
