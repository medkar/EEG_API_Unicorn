"""Ce qu'un écran AFFICHE d'un résultat — décidé ici, par le moteur, et seulement peint ailleurs.

Un résultat de calibration, de mesure ou de test porte, en plus de ses chiffres bruts, QUATRE clés
qui sont tout ce qu'on montre par défaut :

    niveau    "bon" | "moyen" | "faible" — que la console peint en vert, orange, rouge
    mot       le verdict en un mot ou deux : « UTILISABLE », « FAIBLE »
    chiffres  UNE ligne : la mesure ET son point de comparaison, jamais un pourcentage seul
    reserve   UNE phrase : celle qui changerait la décision qu'on s'apprête à prendre

Tout le reste — la phrase de verdict complète, la phrase d'honnêteté, les tests statistiques, les
repères historiques, le nom du fichier — va derrière « Détails ». Rien n'est supprimé : chacune de
ces phrases a été écrite après une conclusion fausse réellement tirée sur ce projet. Elles sont
RANGÉES.

⚠️ **Pourquoi c'est le moteur qui décide du niveau, et pas la console.** Chaque protocole a déjà sa
table de seuils (`VERDICTS`) et c'est elle qui produit « FAIBLE ». Laisser la console déduire une
couleur du TEXTE du verdict — ou pire, d'un pourcentage — reviendrait à tenir une seconde table de
seuils côté écran. Le jour où les deux divergent, l'écran peint en vert ce que le moteur juge
faible. Le niveau est donc calculé par la MÊME table que le mot, dans le même appel.

⚠️ **Pourquoi ce fichier existe** (séance casque du 2026-09-22) : l'écran de résultat du c-VEP
enterrait « 25,0 % pour un hasard à 17 % » au milieu d'une phrase, après une subordonnée sur
McNemar, elle-même après un conseil de resalinage, suivie du nom du fichier et de six lignes
grises. Tout y était vrai, et rien n'était lisible — mot pour mot : « c'est pas clair du tout et
beaucoup trop verbeux ».

Autotest :
    python src/core/modes/affichage.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from core.config import use_utf8_console  # noqa: E402

# L'ordre compte : c'est celui des tables `VERDICTS`, de la meilleure ligne à la pire. La console
# importe ce tuple pour vérifier qu'elle sait peindre chacun des niveaux — elle n'en invente aucun.
NIVEAUX = ("bon", "moyen", "faible")

# La réserve d'une calibration qui a réussi. C'est la seule phrase d'honnêteté qui reste EN FACE,
# parce qu'elle change la décision suivante : le chiffre d'une calibration vient d'une validation
# croisée sur les essais d'ENTRAÎNEMENT, et le moteur, en décodage, ajoute des seuils et un vote
# qui le font se taire souvent. Sur le c-VEP : 59,5 % hors ligne, 46 % d'émission en direct.
RESERVE_HORS_LIGNE = ("Chiffre calculé sur les essais d'entraînement : c'est « Tester » qui dira "
                      "ce que le mode fait vraiment.")


def pct(x, decimales=0):
    """`0.385` -> `"38 %"`. Virgule décimale et espace : c'est un écran pour des étudiants
    francophones, pas un journal. Zéro décimale par défaut — sur 90 essais, l'intervalle de
    confiance fait ±10 points, et une décimale de plus afficherait une précision qu'on n'a pas."""
    return f"{x * 100:.{decimales}f}".replace(".", ",") + " %"


def lignes(niveau, mot, chiffres, reserve):
    """Les quatre clés d'affichage, VÉRIFIÉES. Un niveau hors vocabulaire lève tout de suite.

    Lever plutôt que tolérer : un niveau inconnu arriverait à la console, qui ne saurait pas le
    peindre et le laisserait gris — un résultat affiché sans couleur, donc sans jugement, sans
    que rien ne dise pourquoi.
    """
    if niveau not in NIVEAUX:
        raise ValueError(f"niveau inconnu : {niveau!r} (connus : {', '.join(NIVEAUX)})")
    return {"niveau": niveau, "mot": str(mot), "chiffres": str(chiffres),
            "reserve": str(reserve or "")}


def niveau_par_seuils(valeur, table):
    """Le niveau d'une valeur, par la MÊME table que celle qui écrit le verdict.

    `table` est un `VERDICTS` : des couples `(seuil, texte)` du meilleur au pire. La PREMIÈRE
    ligne est « bon », la DERNIÈRE est « faible », tout ce qui est entre les deux est « moyen ».

    ⚠️ Pas « le rang donne le niveau » : c'était la première écriture, et son autotest l'a pris
    en défaut — une table à DEUX lignes rangeait sa dernière en « moyen ». Or la dernière ligne
    d'une table de verdicts est toujours celle du « ré-essaie », quelle que soit la longueur de
    la table : c'est elle qui doit être rouge.
    """
    dernier = len(table) - 1
    for rang, (seuil, _texte) in enumerate(table):
        if valeur >= seuil:
            if rang == dernier:
                return "faible"
            return "bon" if rang == 0 else "moyen"
    return "faible"


def texte_par_seuils(valeur, table):
    """Le texte de la ligne atteinte — exactement ce que rendent les fonctions `verdict()`."""
    for seuil, texte in table:
        if valeur >= seuil:
            return texte
    return table[-1][1]


def mot_de(texte):
    """Le verdict en MAJUSCULES qui ouvre la phrase : « FAIBLE — ré-essaie… » -> « FAIBLE ».

    La suite de mots entièrement en capitales, lue depuis le début : « BON pour un ErrP » -> « BON »,
    « AU NIVEAU DU REPÈRE DU PROJET (59,5… » -> « AU NIVEAU DU REPÈRE DU PROJET ». Le mot à l'écran
    et la phrase dans « Détails » disent donc la même chose, puisqu'ils viennent du même texte.
    """
    mots = []
    for brut in texte.split():
        mot = brut.strip(",;:.")
        if not mot or not any(c.isalpha() for c in mot) or mot != mot.upper():
            break
        mots.append(mot)
    return " ".join(mots)


def conseil_de(texte):
    """Ce qui suit le premier « — » : « FAIBLE — ré-essaie : saline… » -> « ré-essaie : saline… ».
    Vide s'il n'y en a pas."""
    _avant, sep, apres = texte.partition(" — ")
    return apres.strip() if sep else ""


def depuis_table(valeur, table, chiffres):
    """Les quatre clés d'une calibration, depuis sa table `VERDICTS`.

    La réserve dépend du niveau, et c'est délibéré : FAIBLE porte son CONSEIL (quoi reprendre avant
    de recommencer), un bon résultat porte `RESERVE_HORS_LIGNE` (ne crois pas ce chiffre avant de
    l'avoir testé). Dans les deux cas, c'est la phrase qui change le geste suivant.
    """
    niveau = niveau_par_seuils(valeur, table)
    texte = texte_par_seuils(valeur, table)
    reserve = (conseil_de(texte) or RESERVE_HORS_LIGNE) if niveau == "faible" \
        else RESERVE_HORS_LIGNE
    return lignes(niveau, mot_de(texte) or niveau.upper(), chiffres, reserve)


def non_mesure(raison, conseil):
    """Les quatre clés quand RIEN n'a pu être mesuré. Rouge : un chiffre absent ne se garde pas.

    ⚠️ Pas « FAIBLE » : faible dit « ton signal est mauvais », non mesuré dit « il n'y avait pas de
    quoi calculer ». Les deux ne se corrigent pas pareil — l'un demande de resaliner, l'autre plus
    d'essais —, et les annoncer d'un même mot enverrait resaliner des électrodes qui vont très bien.
    """
    return lignes("faible", "NON MESURÉ", raison, conseil)


def verifier(resultat):
    """Les défauts d'affichage d'un résultat, en clair. Liste vide = rien à redire.

    Appelée par l'autotest de CHAQUE producteur de résultat. Elle tient l'invariant central : le
    MOT montré en face et la phrase de VERDICT rangée dans « Détails » viennent du même calcul —
    le verdict commence par le mot. Si un jour quelqu'un change un seuil dans une table sans
    toucher l'autre chemin, l'écran dirait « UTILISABLE » au-dessus d'une phrase qui commence par
    « FAIBLE ». C'est exactement la divergence que ce fichier existe pour empêcher.
    """
    manque = [c for c in ("niveau", "mot", "chiffres", "reserve", "verdict")
              if c not in (resultat or {})]
    if manque:
        return [f"clé(s) absente(s) : {', '.join(manque)}"]
    defauts = []
    if resultat["niveau"] not in NIVEAUX:
        defauts.append(f"niveau inconnu : {resultat['niveau']!r}")
    if not resultat["mot"]:
        defauts.append("mot vide")
    if not resultat["chiffres"]:
        defauts.append("ligne de chiffres vide")
    elif "%" in resultat["chiffres"] and "hasard" not in resultat["chiffres"] \
            and "repère" not in resultat["chiffres"]:
        defauts.append(f"un pourcentage SEUL, sans son point de comparaison : "
                       f"{resultat['chiffres']!r}")
    if resultat["mot"] != "NON MESURÉ" and \
            not str(resultat["verdict"]).lower().startswith(resultat["mot"].lower()):
        defauts.append(f"le mot {resultat['mot']!r} n'ouvre pas le verdict "
                       f"{str(resultat['verdict'])[:50]!r} — deux calculs ont divergé")
    return defauts


def _selftest():
    use_utf8_console()
    resultats = []

    def chk(cond, msg):
        resultats.append(bool(cond))
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")

    table = ((0.55, "AU NIVEAU DU REPÈRE DU PROJET (59,5 / 64,9 % sur la séance de référence)"),
             (0.33, "UTILISABLE"),
             (0.00, "FAIBLE — ré-essaie : saline Pz/PO7/Oz/PO8"))

    # Le niveau suit la table du VERDICT, pas une seconde table — c'est tout l'objet du fichier.
    chk([niveau_par_seuils(v, table) for v in (0.60, 0.40, 0.10)] == ["bon", "moyen", "faible"],
        "le niveau est le RANG de la ligne atteinte dans la table du verdict")
    chk(niveau_par_seuils(0.55, table) == "bon" and niveau_par_seuils(0.33, table) == "moyen",
        "…et un seuil atteint pile est atteint (>=), comme dans les fonctions `verdict()`")

    fort = depuis_table(0.60, table, "60 % de cibles justes (hasard 17 %) sur 90 essais")
    chk(fort["mot"] == "AU NIVEAU DU REPÈRE DU PROJET",
        f"le mot est la suite de CAPITALES qui ouvre le texte, sans la parenthèse ({fort['mot']!r})")
    chk(fort["reserve"] == RESERVE_HORS_LIGNE,
        "un bon résultat de calibration rappelle que le chiffre est HORS LIGNE — c'est la réserve "
        "qui change la décision suivante (tester avant d'y croire)")

    faible = depuis_table(0.25, table, "25 % de cibles justes (hasard 17 %) sur 90 essais")
    chk(faible["niveau"] == "faible" and faible["mot"] == "FAIBLE",
        f"FAIBLE est rouge et dit FAIBLE ({faible['niveau']}, {faible['mot']!r})")
    chk(faible["reserve"] == "ré-essaie : saline Pz/PO7/Oz/PO8",
        f"…et sa réserve est le CONSEIL de la table, pas la phrase générique ({faible['reserve']!r})")

    chk(mot_de("BON pour un ErrP mono-essai — au niveau du repère") == "BON",
        "le mot s'arrête au premier mot qui n'est pas en capitales")
    chk(mot_de("Alpha NET à la fermeture des yeux") == "",
        "une phrase qui ne s'ouvre pas en capitales n'a pas de mot : on ne l'invente pas")
    chk(depuis_table(0.10, ((0.5, "UTILISABLE"), (0.0, "texte sans capitales")), "x")["mot"]
        == "FAIBLE",
        "…et `depuis_table` retombe alors sur le NOM du niveau, jamais sur une chaîne vide")
    # La DERNIÈRE ligne d'une table est toujours rouge, quelle que soit la longueur de la table.
    # Écrit après que la première version (« le rang donne le niveau ») a rangé la dernière ligne
    # d'une table à deux lignes en « moyen ».
    deux = ((0.5, "UTILISABLE"), (0.0, "FAIBLE — refais"))
    quatre = ((0.9, "EXCELLENT"), (0.7, "BON"), (0.5, "UTILISABLE"), (0.0, "FAIBLE — refais"))
    chk(niveau_par_seuils(0.1, deux) == "faible" and niveau_par_seuils(0.1, quatre) == "faible",
        "la dernière ligne est ROUGE à deux lignes comme à quatre — c'est celle du « ré-essaie »")
    chk([niveau_par_seuils(v, quatre) for v in (0.95, 0.8, 0.6)] == ["bon", "moyen", "moyen"],
        "…la première est verte, et tout l'entre-deux est orange")

    rien = non_mesure("pas assez d'essais distincts", "refais une séance plus longue")
    chk(rien["niveau"] == "faible" and rien["mot"] == "NON MESURÉ",
        "« non mesuré » est rouge, mais ne se dit pas FAIBLE : les deux ne se corrigent pas pareil")

    try:
        lignes("vert", "X", "y", "z")
        chk(False, "un niveau hors vocabulaire doit LEVER, pas arriver gris à la console")
    except ValueError:
        chk(True, "un niveau hors vocabulaire LÈVE, au lieu d'arriver gris à la console")

    # `verifier` : ce que chaque producteur de résultat appelle dans son propre autotest.
    bon = {**depuis_table(0.60, table, "60 % de cibles justes (hasard 17 %)"),
           "verdict": "AU NIVEAU DU REPÈRE DU PROJET (59,5 / 64,9 %) — les deux décodeurs…"}
    chk(verifier(bon) == [], f"un résultat cohérent ne lève aucun défaut ({verifier(bon)})")
    diverge = {**bon, "verdict": "FAIBLE — ré-essaie"}
    chk(any("divergé" in d for d in verifier(diverge)),
        "…mais un MOT qui n'ouvre pas le verdict est signalé : deux calculs ont divergé")
    seul = {**bon, "chiffres": "38 % de cibles justes"}
    chk(any("SEUL" in d for d in verifier(seul)),
        "…et un pourcentage sans son point de comparaison aussi")
    chk(verifier({"verdict": "x"}) and "absente" in verifier({"verdict": "x"})[0],
        "…et un résultat qui n'a pas ses quatre clés d'affichage")

    chk(pct(0.385) == "38 %" and pct(1 / 6) == "17 %" and pct(0.385, 1) == "38,5 %",
        f"les pourcentages s'écrivent à la française ({pct(0.385)}, {pct(1 / 6)}, {pct(0.385, 1)})")

    ok = all(resultats)
    print(f"[affichage] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    _sys.exit(0 if _selftest() else 1)
