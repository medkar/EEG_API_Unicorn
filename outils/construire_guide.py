"""Construit le guide d'intégration : recopie les fichiers de configuration des clients dans les
deux guides, puis fabrique leurs PDF.

    python outils/construire_guide.py              # recopie les fichiers, puis fabrique les PDF
    python outils/construire_guide.py --md         # recopie les fichiers seulement (sans pandoc)
    python outils/construire_guide.py --verifier   # vérifie seulement : 1 si un fichier a divergé

Un bloc de code du guide n'est JAMAIS tapé à la main : chaque bloc est encadré par deux marqueurs,
et ce script le remplace par le contenu actuel du fichier qu'il nomme. La configuration montrée par
le guide est donc celle que les clients lisent vraiment.

    <!-- code: clients/python-lsl/config.json -->     le fichier entier
    <!-- code: examples/udp_device.py#Device.send -->  une méthode (ou une fonction) Python
    <!-- code: examples/esp32_leds/esp32_leds.ino#hello -->   une fonction C++, avec les
                                                      commentaires // juste au-dessus
    ```json
    (ici, le contenu recopié par ce script)
    ```
    <!-- /code -->

Le PDF passe par pandoc et typst (`--pdf-engine=typst`), avec la mise en page de
`docs/guide/style.typ`. `--verifier` n'a besoin ni de l'un ni de l'autre : c'est ce que lance
`python src/core/server.py --smoke` (`[smoke-exemples]`).
"""

import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
import textwrap

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOSSIER = os.path.join(RACINE, "docs", "guide")
GUIDES = ("guide-fr.md", "guide-en.md")
STYLE = os.path.join(DOSSIER, "style.typ")

# Un bloc : le marqueur d'ouverture, un bloc de code clôturé, le marqueur de fermeture.
BLOC = re.compile(r"(?P<debut><!-- code: (?P<chemin>[^#\s]+)(?:#(?P<quoi>[\w.]+))? -->\n)"
                  r"```(?P<langue>\w*)\n(?P<code>.*?)```\n"
                  r"(?P<fin><!-- /code -->)", re.S)
LANGUES = {".py": "python", ".ino": "cpp", ".h": "cpp", ".json": "json", ".yaml": "yaml"}


def extrait_python(source, quoi):
    """Le texte de la fonction (ou de la méthode `Classe.methode`) `quoi`, sans son retrait."""
    noeuds = ast.parse(source).body
    trouve = None
    for nom in quoi.split("."):
        trouve = next((n for n in noeuds if isinstance(n, (ast.FunctionDef, ast.ClassDef))
                       and n.name == nom), None)
        if trouve is None:
            raise ValueError(f"« {quoi} » introuvable")
        noeuds = trouve.body
    lignes = source.splitlines()[trouve.lineno - 1:trouve.end_lineno]
    return textwrap.dedent("\n".join(lignes))


def extrait_cpp(source, quoi):
    """La fonction C++ `quoi` d'un croquis Arduino : de sa signature (en colonne 0) jusqu'à
    l'accolade fermante en colonne 0, avec les commentaires // collés au-dessus."""
    lignes = source.splitlines()
    signature = re.compile(r"^[A-Za-z_][\w\s\*&:<>,]*\b" + re.escape(quoi) + r"\s*\(")
    debut = next((i for i, l in enumerate(lignes) if signature.match(l)), None)
    if debut is None:
        raise ValueError(f"« {quoi} » introuvable")
    fin = next(i for i in range(debut, len(lignes)) if lignes[i] == "}")
    while debut > 0 and lignes[debut - 1].startswith("//"):
        debut -= 1
    return "\n".join(lignes[debut:fin + 1])


def code_de(chemin, quoi):
    """Le code que le bloc doit montrer, lu dans le dépôt."""
    with open(os.path.join(RACINE, chemin), encoding="utf-8") as f:
        source = f.read()
    if not quoi:
        return source.rstrip("\n")
    if chemin.endswith(".py"):
        return extrait_python(source, quoi)
    return extrait_cpp(source, quoi)


def rafraichir(texte):
    """(le guide avec chaque bloc refait d'après son fichier, la liste des blocs qui avaient
    divergé)."""
    divergents = []

    def refaire(m):
        code = code_de(m["chemin"], m["quoi"])
        langue = LANGUES.get(os.path.splitext(m["chemin"])[1], "")
        if m["code"].rstrip("\n") != code or m["langue"] != langue:
            divergents.append(m["chemin"] + (f"#{m['quoi']}" if m["quoi"] else ""))
        return f"{m['debut']}```{langue}\n{code}\n```\n{m['fin']}"

    return BLOC.sub(refaire, texte), divergents


def verifier():
    """Rend la liste des (guide, bloc) dont le code a divergé de son fichier, et le nombre de
    blocs vus : zéro bloc vu serait une garde muette (un marqueur cassé, un guide vidé)."""
    fautes, vus = [], 0
    for nom in GUIDES:
        with open(os.path.join(DOSSIER, nom), encoding="utf-8") as f:
            texte = f.read()
        vus += len(BLOC.findall(texte))
        _, divergents = rafraichir(texte)
        fautes += [(nom, d) for d in divergents]
    return fautes, vus


def construire_pdf(nom):
    """Le PDF d'un guide, à côté de lui, par pandoc et typst."""
    md = os.path.join(DOSSIER, nom)
    pdf = os.path.splitext(md)[0] + ".pdf"
    pandoc = shutil.which("pandoc")
    if pandoc is None:
        sys.exit("pandoc est introuvable : installe-le (winget install JohnMacFarlane.Pandoc), "
                 "ainsi que typst (winget install Typst.Typst)")
    # Le format de page (A4, marges, taille du texte, numérotation) est dans l'en-tête YAML de
    # chaque guide : pandoc n'accepte pas les marges en ligne de commande.
    commande = [pandoc, md, "-o", pdf, "--pdf-engine=typst", "--toc",
                "--include-in-header", STYLE, "--resource-path", DOSSIER]
    resultat = subprocess.run(commande, capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
    if resultat.returncode != 0:
        sys.exit(f"pandoc a échoué sur {nom} :\n{resultat.stderr}")
    print(f"[guide] {os.path.relpath(pdf, RACINE)}")


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--verifier", action="store_true", help="vérifie seulement, sans rien écrire")
    p.add_argument("--md", action="store_true", help="recopie le code, sans fabriquer les PDF")
    args = p.parse_args(argv)

    if args.verifier:
        fautes, vus = verifier()
        for nom, bloc in fautes:
            print(f"  ÉCHEC {nom} : le code de « {bloc} » n'est plus celui du fichier")
        ok = not fautes and vus > 0
        print(f"[guide] {vus} bloc(s) de code vérifié(s) dans {len(GUIDES)} guide(s), "
              f"{len(fautes)} divergent(s) — VERDICT : {'OK' if ok else 'PROBLÈME'}")
        if vus == 0:
            print("  ÉCHEC aucun bloc trouvé : un marqueur cassé ne vérifierait plus rien")
        return 0 if ok else 1

    for nom in GUIDES:
        chemin = os.path.join(DOSSIER, nom)
        with open(chemin, encoding="utf-8") as f:
            texte = f.read()
        neuf, divergents = rafraichir(texte)
        if neuf != texte:
            with open(chemin, "w", encoding="utf-8", newline="\n") as f:
                f.write(neuf)
        print(f"[guide] {nom} : {len(BLOC.findall(neuf))} bloc(s) de code, "
              f"{len(divergents)} recopié(s)")
    if not args.md:
        for nom in GUIDES:
            construire_pdf(nom)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
