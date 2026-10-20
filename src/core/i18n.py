"""Les textes affichés, lus dans un fichier par langue — jamais écrits en dur dans le code.

Aucun texte affiché n'est écrit en dur dans le code : il vit dans un fichier séparé, pour
pouvoir ajouter des langues facilement.

    src/core/langues/fr/console.json    # ce que la console écrit elle-même
    src/core/langues/fr/modes.json      # libellés, résumés, aides et briefings des modes
    src/core/langues/fr/mesures.json    # les mesures et les tests : briefings, verdicts
    src/core/langues/fr/moteur.json     # refus et réponses du moteur
    src/core/langues/fr/fenetres.json   # les fenêtres de `src/stimulus/`

Un dossier par langue, plusieurs fichiers par dossier (ils sont FUSIONNÉS ; une clé présente
dans deux fichiers est une faute). Le français est la langue SOURCE : celle des autotests, et
celle où retombe une clé absente. **Ajouter une langue = copier `fr/` et traduire les valeurs** :
elle apparaît dans le menu de langue de la console. Le moteur seul la lit dans `EEG_LANGUE`.

Dans le code, un texte s'écrit `tr("mode.ssvep.label")`, ou avec des valeurs :
`tr("moteur.refus.frequence", f=17, ecran=60)` pour `"{f} Hz ne divise pas {ecran} Hz"`.

⚠️ Pourquoi dans `core` : le moteur produit lui-même une bonne part de ce que la console affiche
(refus, verdicts, aides des réglages, briefings), et `core` n'importe rien du dépôt hors de
lui-même. La console, elle, a le droit d'importer `core` : un seul chargeur sert les deux.

Changer de langue EN COURS de route : les libellés des contrats (modes, réglages, aides) sont
résolus à l'import, dans la langue de départ. Chaque texte rendu par `tr` est donc un `Texte`, qui
se souvient de sa clé et de ses valeurs, et `retraduit()` le relit dans la langue courante : le
catalogue que le moteur sérialise pour la console passe par lui, et la console reconstruit ses
pages. Seul l'AFFICHAGE change : noms de flux, voies et marqueurs ne se traduisent jamais.

Ce que `controle()` vérifie, et que `server.py --smoke` exécute (`[smoke-textes]`) :
  - chaque `tr("…")` du dépôt nomme une clé qui EXISTE, avec une clé LITTÉRALE (une clé calculée
    échapperait à toute vérification) et exactement les `{valeurs}` que le texte attend ;
  - aucune clé du français n'est orpheline (un texte que plus rien n'affiche se traduirait pour
    rien) ;
  - une autre langue a TOUTES les clés du français, et aucune autre, avec les mêmes `{valeurs}` ;
  - la console ne passe aucun texte EN DUR à un widget (`setText`, `QLabel`, `QPushButton`…) ;
  - la console ne lit aucun texte au CHARGEMENT (`tr` hors de toute fonction) : il resterait dans
    la langue de départ.
"""

import ast as _ast
import json as _json
import os as _os
import string as _string

DOSSIER = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "langues")
LANGUE_DEFAUT = "fr"

_cache = {}


def langue():
    """La langue demandée (`EEG_LANGUE`), ou le français."""
    return _os.environ.get("EEG_LANGUE", LANGUE_DEFAUT) or LANGUE_DEFAUT


def langues_disponibles():
    """Les codes des langues livrées (un dossier de catalogue non vide), triés."""
    if not _os.path.isdir(DOSSIER):
        return []
    return sorted(code for code in _os.listdir(DOSSIER)
                  if _os.path.isdir(_os.path.join(DOSSIER, code))
                  and any(n.endswith(".json") for n in _os.listdir(_os.path.join(DOSSIER, code))))


def choisir_langue(code):
    """Passe l'affichage dans la langue `code`. Lève `ValueError` sur une langue non livrée.

    Par la variable d'environnement : `langue()` la relit à chaque `tr`, le fil du moteur compris,
    et les fenêtres de stimulus lancées ENSUITE en héritent.
    """
    if code not in langues_disponibles():
        raise ValueError(f"langue inconnue : {code!r} (livrées : {', '.join(langues_disponibles())})")
    _os.environ["EEG_LANGUE"] = code


def nom_de_langue(code):
    """Le nom d'une langue écrit DANS cette langue (« English », « Français ») : c'est sous ce nom
    qu'on la reconnaît dans un menu, quelle que soit la langue affichée."""
    return catalogue(code).get("console.langue.nom", code)


class Texte(str):
    """Un texte affiché qui se souvient de sa clé et de ses valeurs, pour être RETRADUIT.

    C'est un `str` : il s'affiche, se compare et se concatène comme tel. Mais une concaténation,
    un f-string ou un `.format` rendent un `str` ordinaire, qui ne se retraduit plus : seul ce que
    `tr` rend TEL QUEL change de langue avec `retraduit()`.
    """

    def __new__(cls, texte, cle, valeurs):
        objet = super().__new__(cls, texte)
        objet.cle = cle
        objet.valeurs = valeurs
        return objet

    def __reduce__(self):
        # Copié ou enregistré (pickle, joblib), il redevient un `str` : un modèle sur le disque ne
        # doit pas dépendre de cette classe.
        return (str, (str(self),))


def retraduit(x):
    """`x` dans la langue COURANTE. Un `Texte` est relu dans le catalogue, valeurs comprises ; un
    dict, une liste ou un tuple le sont élément par élément ; le reste est rendu tel quel."""
    if isinstance(x, Texte):
        return _resoudre(x.cle, {nom: retraduit(v) for nom, v in x.valeurs.items()})
    if isinstance(x, dict):
        return {k: retraduit(v) for k, v in x.items()}
    if isinstance(x, list):
        return [retraduit(v) for v in x]
    if isinstance(x, tuple):
        return tuple(retraduit(v) for v in x)
    return x


def catalogue(code):
    """{clé: texte} pour une langue, tous ses fichiers fusionnés. Lève sur une clé en double."""
    if code in _cache:
        return _cache[code]
    textes, origine = {}, {}
    dossier = _os.path.join(DOSSIER, code)
    if _os.path.isdir(dossier):
        for nom in sorted(_os.listdir(dossier)):
            if not nom.endswith(".json"):
                continue
            with open(_os.path.join(dossier, nom), encoding="utf-8") as f:
                for cle, texte in _json.load(f).items():
                    if cle in textes:
                        raise ValueError(f"langue « {code} » : la clé « {cle} » est dans "
                                         f"{origine[cle]} ET dans {nom}")
                    textes[cle], origine[cle] = texte, nom
    _cache[code] = textes
    return textes


def tr(cle, /, **valeurs):
    """Le texte `cle` dans la langue courante, ses `{valeurs}` remplies.

    `cle` est positionnel seulement : un texte peut donc avoir une valeur nommée `{cle}` sans
    entrer en collision avec lui.

    Ne lève jamais : une clé introuvable s'affiche `⟦clé⟧`, visible à l'écran sans emporter le fil
    Qt. `controle()` garantit qu'aucune ne manque dans le dépôt.
    """
    return _resoudre(cle, valeurs)


def _resoudre(cle, valeurs):
    """Le corps de `tr`, pour une clé connue seulement à l'exécution (`retraduit`). Ailleurs, on
    écrit `tr("…")` : `controle()` ne vérifie que les clés écrites en toutes lettres."""
    for code in (langue(), LANGUE_DEFAUT):
        texte = catalogue(code).get(cle)
        if texte is not None:
            try:
                return Texte(texte.format(**valeurs), cle, valeurs)
            except (KeyError, IndexError, ValueError):
                return Texte(texte, cle, valeurs)
    return f"⟦{cle}⟧"


def message_erreur(e):
    """Ce qu'une exception montre à l'ÉCRAN.

    Une `ValueError` levée par le code du projet porte une phrase déjà écrite pour l'utilisateur
    (un refus, une séance trop pauvre) : on l'affiche seule, sans le « ValueError : » de Python,
    qui n'est que du jargon à l'écran. Toute autre exception est un DÉFAUT : on le dit comme tel,
    avec son type, pour qu'il se signale au lieu de passer pour une consigne.
    """
    if isinstance(e, ValueError) and str(e):
        return str(e)
    return tr("moteur.erreur_interne", type=type(e).__name__, detail=str(e))


def nombre(x, format_="g"):
    """Un nombre écrit dans la langue de l'écran : `1.5` -> « 1,5 » en français.

    Le séparateur décimal appartient à la LANGUE, pas au code : il est lu dans le catalogue.
    Seulement pour du texte affiché — jamais pour une valeur qu'un champ de saisie relira.
    """
    return f"{x:{format_}}".replace(".", tr("moteur.format.decimale"))


def champs(texte):
    """Les noms des `{valeurs}` qu'un texte attend."""
    return {nom for _, nom, _, _ in _string.Formatter().parse(texte) if nom}


# --- le contrôle du dépôt ---------------------------------------------------------------------

# Les widgets et méthodes Qt par lesquels un texte arrive à l'écran. Un littéral passé ici est un
# texte en dur. (Les symboles seuls — « ← », « ⓘ », « · » — ne sont pas du texte : il faut une
# lettre pour compter.)
_WIDGETS = {"QLabel", "QPushButton", "QCheckBox", "QGroupBox", "QRadioButton", "QToolButton"}
_METHODES = {"setText", "setTitle", "setToolTip", "setPlaceholderText", "setWindowTitle",
             "addItem", "addItems", "addRow", "setPlainText", "setHtml", "showMessage"}


def _a_une_lettre(noeud):
    """Le nœud porte-t-il un morceau de texte LITTÉRAL avec au moins une lettre ?"""
    if isinstance(noeud, _ast.Constant) and isinstance(noeud.value, str):
        return any(c.isalpha() for c in noeud.value)
    if isinstance(noeud, _ast.JoinedStr):
        return any(_a_une_lettre(v) for v in noeud.values)
    if isinstance(noeud, _ast.BinOp):
        return _a_une_lettre(noeud.left) or _a_une_lettre(noeud.right)
    if isinstance(noeud, _ast.IfExp):
        return _a_une_lettre(noeud.body) or _a_une_lettre(noeud.orelse)
    if isinstance(noeud, (_ast.List, _ast.Tuple)):
        return any(_a_une_lettre(e) for e in noeud.elts)
    return False


def _nom_appel(appel):
    f = appel.func
    return f.id if isinstance(f, _ast.Name) else (f.attr if isinstance(f, _ast.Attribute) else "")


def _hors_autotest(arbre):
    """Les nœuds d'un module, SAUF le corps de ses fonctions d'autotest (`_smoke*`, `_selftest*`).

    Les messages d'un autotest s'adressent au développeur, dans le terminal : ils ne sont pas
    affichés par l'application, et les traduire n'aurait aucun sens.
    """
    exclus = set()
    for n in _ast.walk(arbre):
        if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and \
                n.name.lstrip("_").startswith(("smoke", "selftest")):
            exclus.update(id(m) for m in _ast.walk(n))
    return [n for n in _ast.walk(arbre) if id(n) not in exclus]


def _fichiers_py(racine):
    for dossier, _, fichiers in _os.walk(racine):
        if "__pycache__" in dossier:
            continue
        for nom in sorted(fichiers):
            if nom.endswith(".py"):
                yield _os.path.join(dossier, nom)


def textes_en_dur(racine_console):
    """[(fichier, ligne, extrait)] : les textes passés EN DUR à un widget de la console."""
    trouves = []
    for chemin in _fichiers_py(racine_console):
        with open(chemin, encoding="utf-8") as f:
            arbre = _ast.parse(f.read())
        for n in _hors_autotest(arbre):
            if not isinstance(n, _ast.Call):
                continue
            nom = _nom_appel(n)
            if nom in _WIDGETS or nom in _METHODES:
                if n.args and _a_une_lettre(n.args[0]):
                    trouves.append((chemin, n.lineno, _ast.unparse(n.args[0])[:60]))
    return trouves


def textes_figes(racine_console):
    """[(chemin, ligne, clé)] : les `tr(…)` de la console lus HORS de toute fonction.

    Au niveau d'un module ou d'une classe, un texte est lu au CHARGEMENT : avant que la console ait
    choisi sa langue, et jamais relu quand on en change. La console lit ses textes au moment de
    les afficher (le moteur, lui, a `retraduit`).
    """
    figes = []
    for chemin in _fichiers_py(racine_console):
        with open(chemin, encoding="utf-8") as f:
            arbre = _ast.parse(f.read(), chemin)

        def parcourt(noeud, dans_une_fonction):
            for enfant in _ast.iter_child_nodes(noeud):
                fonction = dans_une_fonction or isinstance(
                    enfant, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.Lambda))
                if (not fonction and isinstance(enfant, _ast.Call)
                        and _nom_appel(enfant) == "tr"):
                    cle = enfant.args[0].value if enfant.args and isinstance(
                        enfant.args[0], _ast.Constant) else "?"
                    figes.append((chemin, enfant.lineno, cle))
                parcourt(enfant, fonction)

        parcourt(arbre, False)
    return figes


def appels_tr(racine_src):
    """[(fichier, ligne, clé ou None, {noms des valeurs})] : chaque `tr(…)` du dépôt."""
    appels = []
    for chemin in _fichiers_py(racine_src):
        with open(chemin, encoding="utf-8") as f:
            arbre = _ast.parse(f.read())
        for n in _hors_autotest(arbre):
            if isinstance(n, _ast.Call) and _nom_appel(n) == "tr":
                cle = (n.args[0].value if n.args and isinstance(n.args[0], _ast.Constant)
                       and isinstance(n.args[0].value, str) else None)
                # `**valeurs` : `k.arg` est None — noté "**", pour que le contrôle le REFUSE (il
                # ne peut pas savoir quelles valeurs un dict portera).
                appels.append((chemin, n.lineno, cle,
                               {k.arg if k.arg else "**" for k in n.keywords}))
    return appels


def controle(racine_src, exiger_zero_en_dur=True):
    """La liste des fautes de traduction du dépôt — vide si tout va bien."""
    fautes = []
    try:
        fr = catalogue(LANGUE_DEFAUT)
    except (ValueError, OSError, _json.JSONDecodeError) as e:
        return [f"le catalogue français ne se charge pas : {e}"]
    if not fr:
        return [f"le catalogue français est VIDE ({_os.path.join(DOSSIER, LANGUE_DEFAUT)}) — "
                f"sans lui, « 0 faute » ne voudrait rien dire"]

    utilisees = set()
    for chemin, ligne, cle, noms in appels_tr(racine_src):
        ou = f"{_os.path.relpath(chemin, racine_src)}:{ligne}"
        if cle is None:
            fautes.append(f"{ou} : clé CALCULÉE — une clé doit être écrite en toutes lettres, "
                          f"sinon rien ne peut vérifier qu'elle existe")
            continue
        utilisees.add(cle)
        if "**" in noms:
            fautes.append(f"{ou} : « {cle} » reçoit ses valeurs par `**` — écris-les une à une, "
                          f"sinon rien ne peut vérifier qu'elles correspondent au texte")
            continue
        if cle not in fr:
            fautes.append(f"{ou} : la clé « {cle} » n'existe pas en français")
            continue
        attendus = champs(fr[cle])
        if noms != attendus:
            fautes.append(f"{ou} : « {cle} » attend {sorted(attendus)}, reçoit {sorted(noms)}")

    for cle in sorted(set(fr) - utilisees):
        fautes.append(f"« {cle} » n'est affichée nulle part (texte orphelin)")

    if _os.path.isdir(DOSSIER):
        for code in sorted(os_ for os_ in _os.listdir(DOSSIER)
                           if _os.path.isdir(_os.path.join(DOSSIER, os_))):
            if code == LANGUE_DEFAUT:
                continue
            try:
                autre = catalogue(code)
            except (ValueError, OSError, _json.JSONDecodeError) as e:
                fautes.append(f"la langue « {code} » ne se charge pas : {e}")
                continue
            manquantes = sorted(set(fr) - set(autre))
            if manquantes:
                fautes.append(f"langue « {code} » : {len(manquantes)} clé(s) du français "
                              f"manquent (ex. {', '.join(manquantes[:3])}) — elles s'afficheraient "
                              f"en français")
            for cle, texte in autre.items():
                if cle not in fr:
                    fautes.append(f"langue « {code} » : « {cle} » n'existe pas en français")
                elif champs(texte) != champs(fr[cle]):
                    fautes.append(f"langue « {code} » : « {cle} » n'a pas les mêmes valeurs que "
                                  f"le français ({sorted(champs(texte))} ≠ "
                                  f"{sorted(champs(fr[cle]))})")

    for chemin, ligne, cle in textes_figes(_os.path.join(racine_src, "console")):
        fautes.append(f"{_os.path.relpath(chemin, racine_src)}:{ligne} : « {cle} » est lu au "
                      f"CHARGEMENT (hors de toute fonction) — il resterait dans la langue de "
                      f"départ ; lis-le au moment de l'afficher")

    en_dur = textes_en_dur(_os.path.join(racine_src, "console"))
    if exiger_zero_en_dur:
        for chemin, ligne, extrait in en_dur:
            fautes.append(f"{_os.path.relpath(chemin, racine_src)}:{ligne} : texte EN DUR "
                          f"passé à un widget ({extrait})")
    return fautes


def _selftest():
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    import tempfile

    global DOSSIER
    vrai = DOSSIER
    with tempfile.TemporaryDirectory() as tmp:
        DOSSIER = tmp
        _cache.clear()
        _os.makedirs(_os.path.join(tmp, "fr"))
        _os.makedirs(_os.path.join(tmp, "en"))
        with open(_os.path.join(tmp, "fr", "a.json"), "w", encoding="utf-8") as f:
            _json.dump({"x.bonjour": "Bonjour {nom}", "x.seul": "Seul en français"}, f)
        with open(_os.path.join(tmp, "en", "a.json"), "w", encoding="utf-8") as f:
            _json.dump({"x.bonjour": "Hello {nom}"}, f)
        chk(tr("x.bonjour", nom="Léa") == "Bonjour Léa", "une valeur est remplie")
        _os.environ["EEG_LANGUE"] = "en"
        chk(tr("x.bonjour", nom="Léa") == "Hello Léa", "une autre langue est lue")
        chk(tr("x.seul") == "Seul en français",
            "une clé absente d'une langue retombe sur le français")
        del _os.environ["EEG_LANGUE"]
        chk(tr("x.absente") == "⟦x.absente⟧", "une clé introuvable se VOIT, sans lever")
        chk(tr("x.bonjour") == "Bonjour {nom}", "une valeur oubliée ne fait pas tomber l'écran")
        # Un texte résolu en français se RETRADUIT après un changement de langue, valeurs comprises.
        figee = tr("x.bonjour", nom="Léa")
        _os.environ["EEG_LANGUE"] = "en"
        chk(isinstance(figee, Texte) and figee == "Bonjour Léa"
            and retraduit({"a": [figee, 3]}) == {"a": ["Hello Léa", 3]},
            f"un texte résolu avant le changement se retraduit ({retraduit(figee)!r})")
        del _os.environ["EEG_LANGUE"]
        import pickle as _pickle
        chk(type(_pickle.loads(_pickle.dumps(figee))) is str,
            "enregistré (pickle), un `Texte` redevient un `str` : un modèle n'en dépend pas")
        with open(_os.path.join(tmp, "fr", "c.json"), "w", encoding="utf-8") as f:
            _json.dump({"x.cle": "la clé {cle}"}, f)
        _cache.clear()
        chk(tr("x.cle", cle="k") == "la clé k", "une valeur peut s'appeler `cle`")
        with open(_os.path.join(tmp, "fr", "b.json"), "w", encoding="utf-8") as f:
            _json.dump({"x.seul": "doublon"}, f)
        _cache.clear()
        try:
            catalogue("fr")
            chk(False, "une clé présente dans DEUX fichiers d'une langue est refusée")
        except ValueError as e:
            chk("a.json" in str(e) and "b.json" in str(e),
                f"une clé présente dans DEUX fichiers d'une langue est refusée ({e})")

    DOSSIER = vrai
    _cache.clear()

    # Le scanner des textes en dur : il doit voir les formes courantes, et ignorer les symboles.
    code = ('QLabel("Bonjour")\nw.setText(f"{n} essais")\nw.setText("←")\n'
            'w.setText(tr("x"))\nQPushButton("ⓘ")\nw.setToolTip("a" if c else "")\n')
    arbre = _ast.parse(code)
    vus = [n.lineno for n in _hors_autotest(arbre) if isinstance(n, _ast.Call)
           and _nom_appel(n) in (_WIDGETS | _METHODES) and n.args and _a_une_lettre(n.args[0])]
    chk(vus == [1, 2, 6], f"le scanner voit les textes en dur, pas les symboles ni `tr` ({vus})")
    # Un texte lu au CHARGEMENT (module, classe) est vu ; un texte lu dans une fonction, non.
    import tempfile as _tempfile
    with _tempfile.TemporaryDirectory() as dossier:
        with open(_os.path.join(dossier, "page.py"), "w", encoding="utf-8") as f:
            f.write("\n".join(['TITRE = tr("a")', "class P:", '    X = tr("b")',
                               "    def f(self):", '        return tr("c")', ""]))
        figes = sorted(cle for _c, _l, cle in textes_figes(dossier))
    chk(figes == ["a", "b"],
        f"un texte lu au chargement est repéré, pas celui d'une fonction ({figes})")
    # …et `tr(…, **d)` est vu comme tel, pour que `controle` le refuse.
    appel = _ast.parse('tr("x", **d)').body[0].value
    chk([k.arg for k in appel.keywords] == [None], "un `**` dans `tr` est repérable")
    return ok


if __name__ == "__main__":
    import sys as _sys
    racine = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    _sys.path.insert(0, racine)
    from core.config import use_utf8_console
    use_utf8_console()
    if "--reste" in _sys.argv:
        # La liste de travail d'une migration : ce qui reste en dur dans la console.
        for chemin, ligne, extrait in textes_en_dur(_os.path.join(racine, "console")):
            print(f"{_os.path.relpath(chemin, racine)}:{ligne}  {extrait}")
        _sys.exit(0)
    bon = _selftest()
    fautes = controle(racine)
    for faute in fautes:
        print(f"  ÉCHEC {faute}")
    print(f"[i18n] {len(fautes)} faute(s) — VERDICT : {'OK' if bon and not fautes else 'ÉCHEC'}")
    _sys.exit(0 if bon and not fautes else 1)
