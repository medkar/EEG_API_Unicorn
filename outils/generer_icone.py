"""Génère l'icône de l'application, `assets/logo/eeg-api-unicorn.ico`, depuis deux dessins SVG.

    python outils/generer_icone.py              # (ré)écrit le .ico
    python outils/generer_icone.py --verifier   # le .ico du dépôt correspond-il aux SVG ?
    python outils/generer_icone.py --autotest   # relit un .ico fabriqué en mémoire

Pourquoi DEUX dessins : sous 32 px, le dessin complet (douze nœuds et leurs liens) devient une
bouillie de pixels. `eeg-api-unicorn-petit.svg` garde la même idée (un cerveau en réseau)
avec moins de points et des traits plus épais. Un `.ico` peut contenir une image PAR TAILLE
et Windows choisit celle qui convient à l'endroit où il affiche l'icône : le petit dessin
sert donc aux tailles 16, 24 et 32, le complet aux tailles 48 à 256.

Pourquoi le script assemble le conteneur lui-même : l'écrivain `.ico` de Qt ne stocke
qu'UNE image. Le format est simple : un en-tête (ICONDIR), une entrée par image
(ICONDIRENTRY), puis les images, ici en PNG (admis par Windows depuis Vista).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # aucun écran requis

RACINE = Path(__file__).resolve().parent.parent
LOGO = RACINE / "assets" / "logo"
SVG_COMPLET = LOGO / "eeg-api-unicorn.svg"
SVG_PETIT = LOGO / "eeg-api-unicorn-petit.svg"
CIBLE = LOGO / "eeg-api-unicorn.ico"

TAILLES = (16, 24, 32, 48, 64, 128, 256)
TAILLE_MAX_PETIT = 32          # jusqu'à cette taille incluse, on utilise le dessin simplifié

# Tolérance de `--verifier` : l'anticrénelage varie un peu d'une version de Qt à l'autre.
TOLERANCE_NIVEAU = 8           # écart toléré par canal (sur 255)
TOLERANCE_PIXELS = 0.005       # part des pixels autorisés à dépasser

_app = None


def _qt():
    """Crée (une fois) l'application Qt sans fenêtre dont le rendu a besoin."""
    global _app
    from PySide6.QtGui import QGuiApplication
    _app = QGuiApplication.instance() or QGuiApplication([])


def _svg_pour(taille: int) -> Path:
    return SVG_PETIT if taille <= TAILLE_MAX_PETIT else SVG_COMPLET


def rendre(svg: Path, taille: int):
    """Rend un SVG en `QImage` ARGB32 transparente, `taille` x `taille`."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    _qt()
    rendu = QSvgRenderer(str(svg))
    if not rendu.isValid():
        raise ValueError(f"SVG illisible : {svg}")
    img = QImage(taille, taille, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    rendu.render(p)
    p.end()
    return img


def _png(img) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    donnees = QByteArray()
    tampon = QBuffer(donnees)
    tampon.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(tampon, "PNG")
    tampon.close()
    return bytes(donnees)


def fabriquer_ico() -> bytes:
    """Assemble le `.ico` : ICONDIR, une ICONDIRENTRY par taille, puis les images PNG."""
    images = [(n, _png(rendre(_svg_pour(n), n))) for n in TAILLES]
    sortie = struct.pack("<HHH", 0, 1, len(images))       # réservé, type 1 = icône, nombre
    decalage = 6 + 16 * len(images)
    for n, png in images:
        octet = 0 if n >= 256 else n                      # 0 veut dire 256
        sortie += struct.pack("<BBBBHHII", octet, octet, 0, 0, 1, 32, len(png), decalage)
        decalage += len(png)
    return sortie + b"".join(png for _, png in images)


def relire_ico(donnees: bytes):
    """Relit un `.ico` : rend une liste de (taille déclarée, `QImage` décodée)."""
    from PySide6.QtGui import QImage
    reserve, type_, nombre = struct.unpack_from("<HHH", donnees, 0)
    if (reserve, type_) != (0, 1):
        raise ValueError("en-tête ICO invalide")
    _qt()
    trouvees = []
    for i in range(nombre):
        l, h, _c, _r, plans, bits, taille_octets, decalage = struct.unpack_from(
            "<BBBBHHII", donnees, 6 + 16 * i)
        l, h = l or 256, h or 256
        brut = donnees[decalage:decalage + taille_octets]
        if brut[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"l'image {i} n'est pas un PNG")
        img = QImage.fromData(brut, "PNG")
        if (img.width(), img.height()) != (l, h):
            raise ValueError(f"image {i} : {img.width()}x{img.height()} au lieu de {l}x{h}")
        trouvees.append((l, img))
    return trouvees


def _ecart(a, b) -> float:
    """Part des pixels de a et b qui diffèrent de plus de TOLERANCE_NIVEAU sur un canal.

    Les images sont comparées en couleurs PRÉMULTIPLIÉES (chaque couleur déjà multipliée par
    son opacité) : un pixel totalement transparent vaut alors toujours 0, 0, 0, 0. Sans ça, les
    coins transparents de la tuile peuvent garder des couleurs invisibles qui changent d'une
    version de Qt à l'autre, et la comparaison échouerait pour une image identique à l'œil."""
    from PySide6.QtGui import QImage
    a = a.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    b = b.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    pa, pb = bytes(a.constBits()), bytes(b.constBits())
    if len(pa) != len(pb):
        return 1.0
    mauvais = 0
    for i in range(0, len(pa), 4):
        if any(abs(pa[i + k] - pb[i + k]) > TOLERANCE_NIVEAU for k in range(4)):
            mauvais += 1
    return mauvais / (len(pa) // 4)


def _ecart_moyen(a, b) -> float:
    pa, pb = bytes(a.constBits()), bytes(b.constBits())
    return sum(abs(x - y) for x, y in zip(pa, pb)) / max(1, len(pa))


def autotest() -> int:
    erreurs = []

    def chk(ok, quoi):
        print(f"  [{'ok' if ok else 'ÉCHEC'}] {quoi}")
        if not ok:
            erreurs.append(quoi)

    donnees = fabriquer_ico()
    reserve, type_, nombre = struct.unpack_from("<HHH", donnees, 0)
    chk((reserve, type_) == (0, 1), "en-tête : réservé 0, type 1 (icône)")
    chk(nombre == len(TAILLES) == 7, f"7 entrées ({nombre})")
    images = relire_ico(donnees)
    chk([t for t, _ in images] == list(TAILLES), f"tailles {[t for t, _ in images]}")
    for t, img in images:
        c = img.pixelColor(t // 2, t // 2)
        chk(c.alpha() == 255, f"{t} px : pixel central opaque")
    # Le 16 px vient du dessin simplifié : plus proche de lui que du complet.
    img16 = images[0][1]
    d_petit = _ecart_moyen(img16, rendre(SVG_PETIT, 16))
    d_complet = _ecart_moyen(img16, rendre(SVG_COMPLET, 16))
    chk(d_petit < d_complet, f"16 px : dessin simplifié (écart {d_petit:.2f} < {d_complet:.2f})")
    img48 = images[3][1]
    chk(_ecart_moyen(img48, rendre(SVG_COMPLET, 48)) < _ecart_moyen(img48, rendre(SVG_PETIT, 48)),
        "48 px : dessin complet")
    # Garde du contrôle lui-même : deux dessins différents doivent être vus comme différents.
    chk(_ecart(rendre(SVG_PETIT, 16), rendre(SVG_COMPLET, 16)) > TOLERANCE_PIXELS,
        "la tolérance de --verifier distingue les deux dessins")
    # Une option inconnue (ou `--help`) ne doit JAMAIS réécrire le .ico : sans analyse des
    # options, tout ce qui n'était pas `--verifier` ni `--autotest` l'écrivait.
    if CIBLE.exists():
        avant = CIBLE.stat().st_mtime_ns
        aide = subprocess.run([sys.executable, __file__, "--help"], capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        inconnue = subprocess.run([sys.executable, __file__, "--inconnue"], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace")
        chk(aide.returncode == 0 and "usage" in aide.stdout.lower(),
            f"--help imprime l'usage (code {aide.returncode})")
        chk(inconnue.returncode == 2, f"une option inconnue est refusée (code {inconnue.returncode})")
        chk(CIBLE.stat().st_mtime_ns == avant, "… et le .ico n'a pas été réécrit")
    print("AUTOTEST", "ÉCHEC" if erreurs else "ok")
    return 1 if erreurs else 0


def verifier() -> int:
    if not CIBLE.exists():
        print(f"absent : {CIBLE}")
        return 1
    voulues = [(n, rendre(_svg_pour(n), n)) for n in TAILLES]
    try:
        presentes = relire_ico(CIBLE.read_bytes())
    except ValueError as e:
        print(f"illisible : {e}")
        return 1
    if [t for t, _ in presentes] != list(TAILLES):
        print(f"tailles différentes : {[t for t, _ in presentes]} au lieu de {list(TAILLES)}")
        return 1
    for (n, voulue), (_, presente) in zip(voulues, presentes):
        part = _ecart(voulue, presente)
        if part > TOLERANCE_PIXELS:
            print(f"{n} px : {part:.2%} des pixels diffèrent (tolérance {TOLERANCE_PIXELS:.1%})")
            return 1
    print(f"{CIBLE.name} correspond aux SVG ({len(TAILLES)} tailles)")
    return 0


def ecrire() -> int:
    donnees = fabriquer_ico()
    CIBLE.write_bytes(donnees)
    print(f"{CIBLE.relative_to(RACINE)} : {len(donnees)} octets, tailles {TAILLES}")
    return 0


def main(argv: "list[str] | None" = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    quoi = p.add_mutually_exclusive_group()
    quoi.add_argument("--verifier", action="store_true",
                      help="vérifie que le .ico du dépôt correspond aux SVG, sans rien écrire")
    quoi.add_argument("--autotest", action="store_true",
                      help="relit un .ico fabriqué en mémoire, sans rien écrire")
    # Une option inconnue arrête le programme ICI (code 2), avant toute écriture.
    a = p.parse_args(argv)
    if a.autotest:
        return autotest()
    if a.verifier:
        return verifier()
    return ecrire()


if __name__ == "__main__":
    sys.exit(main())
