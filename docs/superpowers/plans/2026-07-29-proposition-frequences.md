# Proposition de fréquences SSVEP — plan d'implémentation (chantier 2)

> **Pour un agent :** SOUS-COMPÉTENCE REQUISE — utiliser `superpowers:subagent-driven-development`
> (recommandé) ou `superpowers:executing-plans` pour exécuter ce plan tâche par tâche. Les étapes
> sont des cases à cocher (`- [ ]`).

**But :** supprimer le principal mode de panne silencieuse du SSVEP — une fréquence qui ne divise
pas le rafraîchissement écran ne détecte jamais rien, sans la moindre erreur — en **proposant** des
jeux valides et en **refusant** les invalides.

**Architecture :** une fonction pure dans `core/config.py` calcule les fréquences ; le contrat
gagne deux champs (`affecte_decodage`, et l'usage de `proposes` déjà déclaré) et une contrainte
(`divise_le_refresh`) ; le mode SSVEP gagne deux réglages (`refresh_hz`, `alpha_hz`) ; le moteur
gagne une commande `propose_params` ; la console gagne un bouton. Aucune logique nouvelle dans
l'interface.

**Pile :** Python 3.12 · PySide6 · pas de dépendance nouvelle.

**Spec de référence :** [docs/superpowers/specs/2026-07-29-proposition-frequences-design.md](../specs/2026-07-29-proposition-frequences-design.md)

## Global Constraints

Ces règles s'appliquent à **toutes** les tâches. Elles ne sont pas répétées ensuite.

- **Frontière de paquets** : `core` n'importe **ni `research`, ni `console`, ni pygame, ni Qt**.
  `console` importe `core`. Vérifié par un test à `python src/core/server.py --smoke`.
- **Les trois smokes doivent rester verts à CHAQUE tâche** : `python src/core/server.py --smoke`,
  `python src/console/app.py --smoke`, `python src/research/app.py --smoke`.
- ⚠️ **Ne laisser tourner AUCUN moteur pendant un test** : les noms de flux sont un contrat public,
  donc identiques pour toutes les instances. Vérifier `Get-Process python` avant et après.
- **Contrat public inchangé** : noms de flux (`EEG_API_Unicorn_*`), noms de voies, unités, valeurs
  de `phase` publiées sur `status` (`streaming` / `warmup` / `baseline` / `decoding`).
- **Langue** : code, commentaires et docstrings en **français** ; messages de commit en **anglais**.
- **Public** : des étudiants qui liront et modifieront ce code. Un commentaire explique *pourquoi*,
  pas *quoi*.
- **Constantes à reprendre telles quelles** depuis `src/core/config.py`, jamais recopiées en dur :
  `WINDOW_S = 1.5` · `BANDPASS = (5.0, 40.0)` · `Z_MIN = 2.5` · `NEURO_Z_SPAN = 3.0`.
- **Les fréquences par défaut du SSVEP ne changent pas** : `FREQS_60HZ` reste ce que rend
  `choose_frequencies(60)`, soit 15 · 20 · 8,571 Hz. La proposition est une ACTION, jamais un
  recalcul au démarrage.
- **`choose_frequencies` et la table `COMMANDS` de `config.py` ne bougent pas** : neuf appelants en
  dépendent, dont `ssvep_stimulus.py`. La nouvelle fonction vit à côté.
- **Convention de tests du dépôt : PAS de pytest.** Chaque module porte son autotest sous
  `if __name__ == "__main__":`, avec un helper `chk(cond, msg)` qui imprime `OK`/`ÉCHEC`, un
  `VERDICT` final et `sys.exit(0/1)`. Les tests de bout en bout sont des drapeaux `--smoke`.
- **Commit à la fin de chaque tâche**, avec les trois smokes verts.

## Structure des fichiers

| Fichier | Ce qui change |
|---|---|
| `src/core/config.py` | + `ALPHA_GARDE_HZ`, `CONFORT_HZ`, `ALPHA_DEFAUT_HZ`, `propose_frequencies()`, `_plus_ecartees()` ; commentaire sur `ALPHA_PEAK_HZ` ; **premier autotest du fichier** |
| `src/core/modes/contract.py` | + champ `affecte_decodage` sur `Param` ; + contrainte `divise_le_refresh` |
| `src/core/modes/ssvep.py` | + `Param` `refresh_hz` et `alpha_hz` ; + contrainte sur `freqs` |
| `src/core/server.py` | + commande `propose_params` ; `_set_params` ne relance le repos que si utile |
| `src/console/params_form.py` | + bouton « Proposer » et signal `proposer(str)` ; + aide sur le rafraîchissement détecté |
| `src/console/mode_page.py` | + `_proposer()` qui soumet la commande et remplit le champ |
| `docs/SPEC.md`, `README.md` | la proposition et les deux réglages |

---

## Tâche 1 : la règle de proposition, seule et testée

Le cœur du chantier. Une fonction **pure** : pas de moteur, pas d'interface, pas d'état. Elle est
donc entièrement éprouvable sans casque et sans écran.

**Files:**
- Modify: `src/core/config.py`

**Interfaces:**
- Consumes: `available_frequencies(refresh)` et `BANDPASS`, `WINDOW_S` (déjà dans ce fichier).
- Produces: `propose_frequencies(refresh, n, alpha=ALPHA_DEFAUT_HZ) -> (list[float], str)`
  — la liste est vide si c'est impossible, et la chaîne porte alors la raison ; sinon la chaîne est
  vide ou porte un avertissement. Constantes `ALPHA_GARDE_HZ = 1.9`, `CONFORT_HZ = (8.0, 20.0)`,
  `ALPHA_DEFAUT_HZ = 9.6`.

- [ ] **Étape 1 : annoter la constante personnelle**

Dans `src/core/config.py`, remplacer la ligne `ALPHA_PEAK_HZ = 10.5` par :

```python
# ⚠️ MESURE PERSONNELLE, pas une constante universelle. C'est le pic alpha du développeur.
# Le pic alpha individuel varie fortement d'une personne à l'autre (moyenne de population ~9,6 Hz,
# écart-type ~1 Hz, plage 7-13 Hz, décroissant avec l'âge). Un seul consommateur aujourd'hui :
# `research/app.py`, pour ses propres séances. Tout ce qui s'adresse à QUELQU'UN D'AUTRE doit
# passer par le réglage `alpha_hz` du mode SSVEP, pas par cette valeur.
ALPHA_PEAK_HZ = 10.5
```

- [ ] **Étape 2 : ajouter les trois constantes de la proposition**

Juste après `BANDPASS` dans `src/core/config.py` :

```python
# --- Proposition de fréquences SSVEP (chantier 2) ------------------------------------------
# Écart minimum entre une cible et le pic alpha de la personne. Une cible posée sur le pic ne se
# distingue pas du fond : la corrélation de repos y est déjà élevée, donc la normalisation z ne
# fait plus émerger la réponse.
#
# 1,9 Hz est ENCADRÉ par les deux seules mesures dont ce projet dispose, sur une personne dont le
# pic est à 10,5 Hz :
#   12 Hz    (à 1,50 Hz du pic) ÉCHOUE — séparabilité 0,3-0,5 contre 2-6 pour les autres cibles
#   8,571 Hz (à 1,93 Hz du pic) MARCHE — c'est une des trois fréquences validées casque
# C'est donc la plus grande valeur compatible avec les deux. ⚠️ n = 1 personne : à réviser dès
# qu'on aura mesuré sur plusieurs. Elle n'interdit rien, elle oriente seulement la proposition.
ALPHA_GARDE_HZ = 1.9

# Pic alpha par défaut : la MOYENNE DE POPULATION, délibérément pas celle du développeur.
ALPHA_DEFAUT_HZ = 9.6

# Plage où l'on propose en priorité. En dessous, le scintillement est pénible et la réponse
# chevauche le thêta ; au-dessus, l'amplitude SSVEP décroît nettement. ⚠️ Seul choix de la règle
# qui ne s'adosse à AUCUNE mesure de ce projet — il vient de la pratique courante du SSVEP. Isolé
# ici pour être révisable. La proposition en sort d'elle-même quand il le faut, en le disant.
CONFORT_HZ = (8.0, 20.0)
```

- [ ] **Étape 3 : écrire les deux fonctions**

À la fin de `src/core/config.py`, après `available_frequencies` (ajouter `import itertools` en tête
du fichier si absent) :

```python
def _plus_ecartees(candidats, n):
    """Les `n` fréquences dont le PLUS PETIT écart mutuel est le plus grand. `None` si impossible.

    Pourquoi ce critère : la séparabilité est la seule propriété qu'on puisse affirmer depuis la
    résolution fréquentielle (`1/WINDOW_S`), sans rien supposer de la physiologie. Deux cibles plus
    proches que cette résolution ne sont pas distinguables, quelle que soit la qualité du signal.

    Pourquoi pas en force brute : à 240 Hz et 8 cibles, énumérer les combinaisons en ferait 314
    MILLIONS. On procède donc par écart décroissant + placement glouton depuis la plus basse, ce
    qui est exact ici (c'est le schéma classique « maximiser la distance minimale ») et instantané.

    À égalité, le jeu aux fréquences les plus basses l'emporte — on ne remplace qu'à écart
    STRICTEMENT meilleur, et les candidats sont parcourus triés. Ce départage n'a rien de profond :
    il rend la fonction DÉTERMINISTE, sans quoi ni le test de non-régression ni le compte rendu
    d'un étudiant ne voudraient dire quoi que ce soit.
    """
    xs = sorted(candidats)
    if n < 1 or len(xs) < n:
        return None
    if n == 1:
        return [xs[0]]
    ecart_min = 1.0 / WINDOW_S

    def place(g):
        """Le jeu le plus bas espacé d'au moins `g`, ou None s'il n'y a pas la place."""
        out = [xs[0]]
        for f in xs[1:]:
            if f - out[-1] >= g:
                out.append(f)
                if len(out) == n:
                    return out
        return None

    for g in sorted({b - a for i, a in enumerate(xs) for b in xs[i + 1:]}, reverse=True):
        if g < ecart_min:
            break               # même le meilleur écart possible est sous la résolution
        jeu = place(g)
        if jeu is not None:
            return jeu
    return None


def propose_frequencies(refresh, n, alpha=ALPHA_DEFAUT_HZ):
    """`(fréquences, note)` : `n` cibles affichables à ce refresh ET décodables pour cet alpha.

    `note` est vide si tout va bien, porte un avertissement si l'on a dû sortir de la plage
    confortable, et porte la raison si c'est impossible — auquel cas la liste est VIDE. On ne rend
    jamais une liste plus courte que demandé : rendre 3 cibles à qui en demande 4 est un mensonge
    silencieux, exactement le genre de panne que ce chantier existe pour supprimer.

    L'alpha est un PARAMÈTRE, jamais une constante : le pic varie fortement d'une personne à
    l'autre, et le jeu accordé à quelqu'un pose une cible sur le pic de quelqu'un d'autre.
    """
    # ⚠️ `available_frequencies` ne borne QUE le bas (son `fmin`) : à 100 Hz elle rend 50 Hz, que
    # le passe-bande d'acquisition supprime AVANT le décodage. Le haut se borne donc ici.
    divisibles = [f for _k, f in available_frequencies(refresh)
                  if BANDPASS[0] <= f <= BANDPASS[1] and abs(f - alpha) >= ALPHA_GARDE_HZ]

    lo, hi = CONFORT_HZ
    jeu = _plus_ecartees([f for f in divisibles if lo <= f <= hi], n)
    if jeu is not None:
        return jeu, ""

    jeu = _plus_ecartees(divisibles, n)
    if jeu is not None:
        hors = [f for f in jeu if not lo <= f <= hi]
        return jeu, (f"hors de la plage confortable {lo:g}-{hi:g} Hz : "
                     + ", ".join(f"{f:g}" for f in hors)
                     + " — scintillement plus pénible, réponse plus bruitée")

    for k in range(n - 1, 1, -1):
        if _plus_ecartees(divisibles, k) is not None:
            return [], (f"impossible : {k} cibles au maximum à {refresh:g} Hz avec un alpha à "
                        f"{alpha:g} Hz — il faut un écran plus rapide")
    return [], f"impossible : aucun jeu de {n} cibles à {refresh:g} Hz"
```

- [ ] **Étape 4 : donner son premier autotest à `config.py`**

`config.py` n'en avait pas — il ne portait que des constantes. Il porte maintenant un algorithme,
donc il en gagne un, à la même forme que `contract.py` ou `registry.py`. À la fin du fichier :

```python
def _selftest():
    """La proposition de fréquences : les invariants, la non-régression, et la tenue en charge."""
    import itertools as _it
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    # 1. LE test de non-régression : la règle doit régénérer le trio validé sur casque réel.
    # Les deux constantes viennent d'ailleurs (mesures pour la garde, pratique pour la plage) ;
    # que le trio en tombe est le seul argument dont on dispose qu'elle n'est pas arbitraire.
    trio, note = propose_frequencies(60.0, 3, 10.5)
    attendu = sorted([15.0, 20.0, 60.0 / 7])
    chk([round(f, 6) for f in sorted(trio)] == [round(f, 6) for f in attendu],
        f"60 Hz, alpha 10,5, n=3 régénère le trio validé casque ({[f'{f:.3f}' for f in trio]})")
    chk(note == "", f"et sans avertissement ({note!r})")

    # 2. Les invariants, sur TOUT le domaine — pas sur un échantillon. Une propriété vérifiée sur
    # un seul cas où elle tient par accident, ce projet en a déjà fait les frais deux fois.
    mauvais = []
    for refresh in (60.0, 75.0, 100.0, 120.0, 144.0, 165.0, 240.0):
        for alpha in (7.5, 8.5, 9.6, 10.5, 11.5, 13.0):
            for n in range(2, 9):
                jeu, note = propose_frequencies(refresh, n, alpha)
                if not jeu:
                    if not note.startswith("impossible"):
                        mauvais.append(("vide sans raison", refresh, alpha, n))
                    continue
                if len(jeu) != n:
                    mauvais.append(("mauvais compte", refresh, alpha, n, len(jeu)))
                for f in jeu:
                    k = refresh / f
                    if abs(k - round(k)) > 1e-9:
                        mauvais.append(("pas un diviseur", refresh, n, f))
                    if not BANDPASS[0] <= f <= BANDPASS[1]:
                        mauvais.append(("hors bande passante", refresh, n, f))
                    if abs(f - alpha) < ALPHA_GARDE_HZ:
                        mauvais.append(("sur le pic alpha", refresh, alpha, n, f))
                trie = sorted(jeu)
                if any(b - a < 1.0 / WINDOW_S - 1e-9 for a, b in zip(trie, trie[1:])):
                    mauvais.append(("cibles non séparables", refresh, alpha, n))
    chk(not mauvais, f"7 refresh x 6 alpha x 7 nombres de cibles : {len(mauvais)} violation(s)")
    for m in mauvais[:5]:
        print(f"       {m}")

    # 3. L'accélération ne doit pas changer le RÉSULTAT : là où la force brute est calculable,
    # elle doit tomber d'accord. Sans ça, « c'est plus rapide » ne vaudrait rien.
    def brute(pool, n):
        best = None
        for jeu in _it.combinations(sorted(pool), n):
            ec = [b - a for a, b in zip(jeu, jeu[1:])]
            if min(ec) < 1.0 / WINDOW_S:
                continue
            if best is None or min(ec) > best[0]:
                best = (min(ec), list(jeu))
        return None if best is None else best[1]

    desaccords = 0
    for refresh in (60.0, 75.0, 120.0, 144.0):
        for alpha in (8.5, 9.6, 10.5, 12.0):
            pool = [f for _k, f in available_frequencies(refresh)
                    if BANDPASS[0] <= f <= BANDPASS[1] and abs(f - alpha) >= ALPHA_GARDE_HZ]
            if len(pool) > 20:
                continue                      # au-delà, la force brute n'est plus calculable
            for n in (2, 3, 4, 5):
                if _plus_ecartees(pool, n) != brute(pool, n):
                    desaccords += 1
    chk(desaccords == 0, f"l'algorithme rapide donne le même résultat que la force brute "
                         f"({desaccords} désaccord(s))")

    # 4. Un écran rapide et beaucoup de cibles : la force brute ferait 314 millions de
    # combinaisons. Ce test échoue en TIMEOUT si quelqu'un la réintroduit un jour.
    debut = time.perf_counter()
    jeu, _note = propose_frequencies(240.0, 8, 9.6)
    duree = time.perf_counter() - debut
    chk(len(jeu) == 8 and duree < 0.5,
        f"240 Hz et 8 cibles en {duree * 1000:.1f} ms ({len(jeu)} cibles)")

    # 5. L'élargissement et l'impossibilité DISENT ce qui se passe.
    _jeu, note = propose_frequencies(60.0, 5, 10.5)
    chk("hors de la plage confortable" in note,
        f"sortir de la plage confortable est annoncé ({note[:60]}…)")
    jeu, note = propose_frequencies(60.0, 12, 10.5)
    chk(jeu == [] and note.startswith("impossible") and "maximum" in note,
        f"un nombre impossible est refusé, avec le maximum atteignable ({note})")

    print(f"[config] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    sys.exit(0 if _selftest() else 1)
```

⚠️ Vérifier que `import sys`, `import time` et `import itertools` sont bien en tête de
`config.py` ; les ajouter s'ils manquent.

- [ ] **Étape 5 : lancer**

Run: `python src/core/config.py`
Expected: `[config] VERDICT : OK`

- [ ] **Étape 6 : les trois smokes ne bougent pas**

Run: `python src/core/server.py --smoke` · `python src/console/app.py --smoke` · `python src/research/app.py --smoke`
Expected: trois `VERDICT : OK`. Rien n'a encore changé pour eux — c'est le but.

- [ ] **Étape 7 : commit**

```bash
git add src/core/config.py
git commit -m "Propose target frequencies from the person's alpha, not the developer's"
```

---

## Tâche 2 : le contrat sait quels réglages comptent

**Files:**
- Modify: `src/core/modes/contract.py`

**Interfaces:**
- Consumes: `propose_frequencies` n'est PAS utilisée ici — le contrat ne propose rien, il valide.
- Produces: `Param.affecte_decodage: bool = True` ; la contrainte nommée `divise_le_refresh`,
  utilisable dans `Param.constraints`.

- [ ] **Étape 1 : le champ**

Dans `src/core/modes/contract.py`, classe `Param`, juste après `proposes` :

```python
    affecte_decodage: bool = True   # False = le décodeur ne le lit jamais (cf. _set_params)
```

- [ ] **Étape 2 : le test qui échoue d'abord**

Dans `_selftest()` de `contract.py`, ajouter (avant le `VERDICT`) :

```python
    # `divise_le_refresh` : la contrainte regarde un AUTRE réglage du mode. C'est ce que
    # `_check_constraints` permet depuis le chantier 1 ; c'est ici qu'on s'en sert enfin.
    ecran = ModeSpec(
        id="essai_refresh", label="Essai", family="actif", summary="",
        status="prevu", unavailable="jeu d'essai du contrat",
        params=(
            Param(key="refresh_hz", label="Rafraîchissement", kind="float", unit="Hz",
                  default=60.0, affecte_decodage=False),
            Param(key="freqs", label="Fréquences des cibles", kind="float_list", unit="Hz",
                  default=(15.0, 20.0), count=(2, 8), constraints=("divise_le_refresh",)),
        ),
    )
    _v, raison = validate(ecran, {"freqs": [15.0, 20.0]})
    chk(raison is None, f"des diviseurs de 60 Hz passent ({raison})")

    _v, raison = validate(ecran, {"freqs": [15.0, 17.0]})
    chk(raison is not None and "17" in raison and "60" in raison,
        f"17 Hz est refusé, en nommant le refresh déclaré ({raison})")
    chk(raison is not None and "20" in raison and "15" in raison,
        f"et le refus donne les diviseurs les plus proches ({raison})")

    _v, raison = validate(ecran, {"freqs": [24.0, 18.0], "refresh_hz": 144.0})
    chk(raison is None, f"les mêmes valeurs jugées contre 144 Hz passent ({raison})")

    chk(ecran.params[0].affecte_decodage is False and ecran.params[1].affecte_decodage is True,
        "un Param déclare s'il affecte le décodage, et le défaut est « oui »")
```

- [ ] **Étape 3 : lancer, et voir échouer**

Run: `python src/core/modes/contract.py`
Expected: ÉCHEC sur `contrainte inconnue « divise_le_refresh »`.

- [ ] **Étape 4 : la contrainte**

Dans `_check_constraints` de `contract.py`, avant la branche `else:` finale :

```python
        elif name == "divise_le_refresh":
            # Une fréquence n'est affichable sans jitter que si c'est un diviseur ENTIER du
            # rafraîchissement : sinon l'écran saute des cycles, et le décodeur corrèle contre une
            # sinusoïde que personne n'affiche. Panne parfaitement silencieuse — aucune erreur,
            # juste zéro détection — donc on la refuse ICI plutôt que de la laisser en séance.
            refresh = float(values.get("refresh_hz") or 0.0)
            if refresh > 0:
                for v in _as_list(values.get(param.key)):
                    k = refresh / v if v else 0.0
                    if not v or abs(k - round(k)) > 1e-6:
                        proches = sorted((f for _n, f in available_frequencies(refresh)),
                                         key=lambda f: abs(f - v))[:2]
                        return (f"« {param.label} » : {v:g} Hz n'est pas un diviseur entier de "
                                f"{refresh:g} Hz — l'affichage sauterait des cycles et le décodeur "
                                f"corrélerait contre une sinusoïde que personne n'affiche. Les "
                                f"plus proches sont "
                                + " et ".join(f"{f:g}" for f in proches) + " Hz")
```

Et ajouter `available_frequencies` à l'import de `core.config` en tête de `contract.py`.

- [ ] **Étape 5 : lancer**

Run: `python src/core/modes/contract.py`
Expected: `[contract] VERDICT : OK`

- [ ] **Étape 6 : les trois smokes**

Run: les trois `--smoke`. Expected: trois `VERDICT : OK`.

- [ ] **Étape 7 : commit**

```bash
git add src/core/modes/contract.py
git commit -m "Refuse a frequency the screen cannot display, and say which ones it can"
```

---

## Tâche 3 : le mode SSVEP expose les deux réglages

**Files:**
- Modify: `src/core/modes/ssvep.py`

**Interfaces:**
- Consumes: `Param.affecte_decodage` et la contrainte `divise_le_refresh` (tâche 2) ;
  `ALPHA_DEFAUT_HZ` (tâche 1).
- Produces: `ssvep.SPEC` expose désormais `freqs`, `refresh_hz`, `alpha_hz`.

- [ ] **Étape 1 : les deux Param**

Dans `src/core/modes/ssvep.py`, ajouter `ALPHA_DEFAUT_HZ` à l'import de `core.config`, puis
remplacer le commentaire « `proposes` est déclaré nulle part dans ce chantier… » par :

```python
        Param(
            key="refresh_hz",
            label="Rafraîchissement de l'écran du stimulus",
            kind="float",
            unit="Hz",
            default=60.0,
            min=20.0, max=480.0,
            proposes="freqs",
            affecte_decodage=False,
            help="Le rafraîchissement de l'écran qui AFFICHE les cibles — pas celui de cette "
                 "fenêtre : ton jeu tourne peut-être sur un autre écran, ou une autre machine. "
                 "Les fréquences affichables sans saut de cycle en sont les diviseurs entiers. "
                 "Le changer PROPOSE un nouveau jeu de fréquences ; il ne relance pas le repos, "
                 "parce que le décodeur ne le lit jamais.",
        ),
        Param(
            key="alpha_hz",
            label="Pic alpha de la personne",
            kind="float",
            unit="Hz",
            default=ALPHA_DEFAUT_HZ,
            min=6.0, max=14.0,
            affecte_decodage=False,
            help="Le pic alpha varie FORTEMENT d'une personne à l'autre (moyenne ~9,6 Hz, plage "
                 "7-13 Hz) et il est stable chez chacun. Une cible posée dessus ne se distingue "
                 "pas du fond au repos. La proposition s'en écarte. Pour mesurer le tien : "
                 "`python src/research/alpha_check.py`. Ne relance pas le repos.",
        ),
```

Et ajouter la contrainte au `Param` `freqs` existant :

```python
            constraints=("dans_la_bande", "separables", "divise_le_refresh"),
```

- [ ] **Étape 2 : le test**

Dans `_selftest()` de `ssvep.py`, avant le `VERDICT` :

```python
    # Les défauts du mode ne bougent PAS : ils sont validés sur casque réel. La proposition est
    # une action que l'étudiant déclenche, jamais un recalcul silencieux au démarrage.
    defauts = SPEC.defaults()
    chk(tuple(round(f, 6) for f in defauts["freqs"]) == tuple(round(f, 6) for f in FREQS_60HZ),
        f"les fréquences par défaut sont inchangées ({defauts['freqs']})")
    chk(defauts["refresh_hz"] == 60.0 and defauts["alpha_hz"] == ALPHA_DEFAUT_HZ,
        f"le refresh et l'alpha ont leurs défauts ({defauts['refresh_hz']}, {defauts['alpha_hz']})")

    # Et les défauts doivent être COHÉRENTS entre eux : 15/20/8,571 sont bien des diviseurs de 60.
    _v, raison = validate(SPEC, {})
    chk(raison is None, f"les défauts du mode passent leur propre validation ({raison})")

    # Aucun des deux nouveaux réglages ne relance le repos.
    par_cle = {p.key: p for p in SPEC.params}
    chk(par_cle["freqs"].affecte_decodage is True, "changer les fréquences affecte le décodage")
    chk(par_cle["refresh_hz"].affecte_decodage is False
        and par_cle["alpha_hz"].affecte_decodage is False,
        "le refresh et l'alpha, non")
    chk(par_cle["refresh_hz"].proposes == "freqs", "et le refresh PROPOSE les fréquences")

    # Le refus qui ferme le trou.
    _v, raison = validate(SPEC, {"freqs": [15.0, 17.0]})
    chk(raison is not None and "diviseur entier" in raison,
        f"17 Hz sur un écran 60 Hz est refusé ({raison})")
```

- [ ] **Étape 3 : faire passer `proposes` jusqu'à la console**

`registry.serialize()` ne recopie **pas tous** les champs d'un `Param` : il en construit un
dictionnaire clé par clé. `proposes` n'y est pas. Or la console lit ce dictionnaire — sans cette
étape, elle ne saurait jamais qu'un réglage en propose un autre, et le bouton de la tâche 5
n'apparaîtrait **jamais, sans la moindre erreur**.

Dans `src/core/modes/registry.py`, fonction `serialize`, ajouter la clé à la construction du
dictionnaire de chaque paramètre :

```python
             "proposes": p.proposes,
```

⚠️ Ne PAS y ajouter `affecte_decodage` : ce champ ne sert qu'au moteur, pour décider s'il refait le
repos. La console n'en a aucun usage, et un champ exposé sans usage est une invitation à ce qu'une
interface s'en serve un jour à la place du moteur.

Et dans `_selftest()` de `registry.py`, avant le `VERDICT` :

```python
    # Le catalogue doit porter `proposes`, sinon la console ne peut pas savoir qu'un réglage en
    # propose un autre — et le bouton correspondant n'apparaîtrait jamais, sans erreur.
    ssvep_serialise = serialize(get("ssvep"))
    par_cle = {p["key"]: p for p in ssvep_serialise["params"]}
    chk(par_cle["refresh_hz"]["proposes"] == "freqs",
        f"le catalogue transmet `proposes` ({par_cle['refresh_hz'].get('proposes')!r})")
    chk("affecte_decodage" not in par_cle["freqs"],
        "et NE transmet PAS `affecte_decodage`, qui ne regarde que le moteur")
```

- [ ] **Étape 4 : réparer l'assertion que cette tâche casse, dans le smoke de la console**

Ajouter deux réglages au SSVEP invalide une affirmation écrite au chantier précédent.
`src/console/app.py` ligne 366 dit aujourd'hui :

```python
    chk(len(page.formulaire.champs) == 1, "le SSVEP expose un réglage : ses fréquences")
```

La remplacer par une assertion qui décrit le NOUVEL état, et qui reste juste si un réglage
s'ajoute encore un jour :

```python
    chk(set(page.formulaire.champs) == {"freqs", "refresh_hz", "alpha_hz"},
        f"le SSVEP expose ses trois réglages ({sorted(page.formulaire.champs)})")
```

⚠️ Ne pas se contenter d'un `== 3` : compter les champs ne dit pas LESQUELS, et c'est exactement
le genre d'assertion qui reste verte pendant qu'un réglage disparaît et qu'un autre apparaît.

- [ ] **Étape 5 : lancer**

Run: `python src/core/modes/ssvep.py`
Expected: `[ssvep] VERDICT : OK`

- [ ] **Étape 6 : l'intégrité du registre**

Run: `python src/core/modes/registry.py`
Expected: `[registry] VERDICT : OK` — c'est ce test qui vérifie qu'aucun `default` ne sort de ses
propres bornes.

- [ ] **Étape 7 : les trois smokes**

Run: les trois `--smoke`. Expected: trois `VERDICT : OK`.

- [ ] **Étape 8 : commit**

```bash
git add src/core/modes/ssvep.py src/core/modes/registry.py src/console/app.py
git commit -m "Let the SSVEP mode carry the screen and the person it is tuned for"
```

---

## Tâche 4 : le moteur propose, et ne refait le repos que s'il le faut

**Files:**
- Modify: `src/core/server.py`

**Interfaces:**
- Consumes: `propose_frequencies` (tâche 1) ; `Param.proposes` et `Param.affecte_decodage`
  (tâches 2-3).
- Produces: commande `propose_params(id, key)` dont l'accusé porte `value` (liste) et `warning`
  (chaîne) ; `_set_params` ne relance le repos que si un réglage à `affecte_decodage=True` a changé.

- [ ] **Étape 1 : le test qui échoue d'abord**

Dans `src/core/server.py`, ajouter un smoke dédié appelé depuis le `--smoke` existant :

```python
def _smoke_proposition():
    """La proposition et le repos sélectif, contre un VRAI moteur — jamais une maquette."""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    server = EngineServer(synthetic=True, modes=("ssvep",), instance="smoke-proposition")
    server._start(["ssvep"], {s.id: v for s, v in server._pending}, now=0.0)

    ack = server.submit("propose_params", id="ssvep", key="refresh_hz")
    chk(ack.get("accepted") and len(ack.get("value") or []) == 3,
        f"proposer rend autant de cibles qu'il y en a réglées ({ack.get('value')})")
    chk(all(abs(60.0 / f - round(60.0 / f)) < 1e-6 for f in ack["value"]),
        "et toutes divisent le refresh déclaré")

    # La proposition doit être ACCEPTABLE par le moteur : c'est ce qui prouve que la règle et la
    # validation sont d'accord. Deux morceaux qui divergeraient produiraient un bouton qui propose
    # des valeurs aussitôt refusées — le pire des deux mondes.
    ack2 = server.submit("set_params", id="ssvep", params={"freqs": ack["value"]})
    chk(ack2.get("accepted"), f"et le moteur accepte ce qu'il vient de proposer ({ack2}) ")

    # Un réglage sans effet sur le décodage ne reconstruit RIEN. On compare l'objet lui-même et
    # pas la phase : les deux chemins laissent le mode en « warmup » juste après un démarrage, donc
    # la phase ne prouverait rien. L'identité du runtime, si — et c'est elle qui porte le plancher
    # de repos déjà mesuré.
    avant = server.active["ssvep"]
    server._set_params("ssvep", {**avant.params, "refresh_hz": 144.0})
    chk(server.active["ssvep"] is avant,
        "changer le refresh seul garde le MÊME runtime, donc son plancher de repos")
    chk(server.active["ssvep"].params["refresh_hz"] == 144.0,
        f"et le réglage est bien pris ({server.active['ssvep'].params['refresh_hz']})")

    # Un réglage que le décodeur lit, lui, reconstruit et refait le repos.
    avant = server.active["ssvep"]
    server._set_params("ssvep", {**avant.params, "freqs": [12.0, 18.0], "refresh_hz": 60.0})
    chk(server.active["ssvep"] is not avant,
        "changer les fréquences reconstruit le mode")
    chk(server.active["ssvep"].phase == "warmup",
        f"et relance le repos (phase {server.active['ssvep'].phase})")

    # Une clé qui ne propose rien est refusée AVEC sa raison : la commande reste atteignable
    # depuis un client LSL même quand la console n'affiche aucun bouton.
    ack3 = server.submit("propose_params", id="ssvep", key="alpha_hz")
    chk(not ack3.get("accepted") and "propose" in (ack3.get("reason") or ""),
        f"un réglage qui ne propose rien est refusé ({ack3.get('reason')})")

    # Proposer AVANT d'avoir démarré le mode doit marcher : on se règle puis on lance.
    arrete = EngineServer(synthetic=True, modes=(), instance="smoke-proposition-2")
    ack4 = arrete.submit("propose_params", id="ssvep", key="refresh_hz")
    chk(ack4.get("accepted") and ack4.get("value"),
        f"on peut demander une proposition sur un mode PAS ENCORE démarré ({ack4.get('reason')})")

    # Ce moteur n'est jamais passé par `run()` : on casse le cycle à la main, comme les autres
    # smokes de ce fichier, sinon un `__del__` tardif du BoardShim libère la session BrainFlow.
    for runtime in server.active.values():
        runtime.close()
    server.active = {}
    print(f"[smoke-proposition] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok
```

⚠️ Le brancher dans le `--smoke` existant, à côté des autres smokes, et faire échouer le tout si
celui-ci échoue.

- [ ] **Étape 2 : lancer, et voir échouer**

Run: `python src/core/server.py --smoke`
Expected: ÉCHEC sur `commande inconnue : propose_params`.

- [ ] **Étape 3 : la commande**

Dans `src/core/server.py`, ajouter `"propose_params"` au tuple `COMMANDS`, importer
`propose_frequencies` depuis `core.config`, et insérer dans `submit`, **après** le bloc
`if command == "start_mode":` et **avant** la ligne `spec, reason = self._one(...)` :

```python
        if command == "propose_params":
            # Une commande en LECTURE : elle ne met rien en file et ne touche pas la session
            # BrainFlow, donc elle peut répondre tout de suite. Elle reste ici pour que la console
            # et un client LSL empruntent le même chemin — un seul endroit à tester.
            spec = registry.get(params.get("id"))
            if spec is None:
                connus = ", ".join(s.id for s in registry.runnable())
                return {"accepted": False,
                        "reason": f"mode inconnu : {params.get('id')} (disponibles : {connus})"}
            cle = params.get("key")
            source = next((p for p in spec.params if p.key == cle and p.proposes), None)
            if source is None:
                proposeurs = [p.key for p in spec.params if p.proposes]
                return {"accepted": False,
                        "reason": f"« {cle} » ne propose aucun réglage pour « {spec.label} » "
                                  f"(qui propose : {', '.join(proposeurs) or 'aucun'})"}
            runtime = self.active.get(spec.id)
            courant = dict(runtime.params) if runtime is not None else spec.defaults()
            cible = source.proposes
            n = len(courant.get(cible) or spec.defaults().get(cible) or ())
            valeurs, note = propose_frequencies(float(courant.get("refresh_hz") or 60.0), n,
                                                float(courant.get("alpha_hz") or ALPHA_DEFAUT_HZ))
            if not valeurs:
                return {"accepted": False, "reason": note}
            return {"accepted": True, "command": command, "id": spec.id,
                    "key": cible, "value": valeurs, "warning": note}
```

⚠️ **On n'utilise ni `_one` ni `_resolve`, et ce n'est pas un oubli.** Les deux imposent un état :
`_one` exige un mode DÉMARRÉ, et `_resolve(..., doit_tourner=False)` fait l'inverse — il **refuse**
un mode déjà démarré, parce que c'est la règle de `start_mode`. Or proposer doit marcher dans les
deux cas : avant de lancer, pour se régler ; et pendant, pour changer d'avis. On interroge donc
directement le registre. Ajouter `ALPHA_DEFAUT_HZ` à l'import de `core.config` (`registry` est
déjà importé).

- [ ] **Étape 4 : le repos sélectif**

**Attention à la solution qui ne marche pas.** On pourrait croire qu'il suffit de sauter l'appel à
`_begin_shared_rest`. C'est faux : `_set_params` **reconstruit** le runtime
(`spec.runtime_cls(spec, values, self)`), et un runtime neuf n'a **aucun plancher de repos mesuré**
— il ne peut donc pas décoder. Copier la phase par-dessus donnerait un mode qui se dit « décode »
et ne décide jamais rien. La bonne correction est de **ne pas reconstruire du tout**.

Dans `_set_params` de `server.py`, insérer juste après la ligne `avant = dict(ancien.params)` :

```python
        # Le décodeur ne lit pas tous les réglages : le rafraîchissement de l'écran et le pic
        # alpha ne servent qu'à proposer et à valider. Quand rien de ce qu'il lit n'a bougé, on
        # met les réglages à jour EN PLACE. Reconstruire le runtime jetterait le plancher de repos
        # déjà mesuré et recréerait le flux — 23 secondes et un réabonnement des clients, pour un
        # changement qui n'affecte ni l'un ni l'autre. Et ça apprendrait à l'étudiant à ne plus
        # toucher aux réglages, ce qui est l'inverse du but.
        comptent = {p.key for p in spec.params if p.affecte_decodage}
        if not [k for k, v in values.items() if k in comptent and avant.get(k) != v]:
            ancien.params = dict(values)
            hors = ", ".join(f"{k} : {avant.get(k)} -> {v}"
                             for k, v in values.items() if avant.get(k) != v)
            print(f"[server] {spec.label} — {hors or 'aucun changement'} "
                  f"(sans effet sur le décodage : ni repos refait, ni flux recréé)")
            return
```

Le reste de la méthode — fermeture, reconstruction, `_begin_shared_rest` — ne bouge pas : c'est le
chemin normal dès qu'un réglage lu par le décodeur change.

- [ ] **Étape 5 : lancer**

Run: `python src/core/server.py --smoke`
Expected: `[smoke-proposition] VERDICT : OK` et le verdict global `OK`.

- [ ] **Étape 6 : les deux autres smokes**

Run: `python src/console/app.py --smoke` · `python src/research/app.py --smoke`
Expected: deux `VERDICT : OK`.

- [ ] **Étape 7 : commit**

```bash
git add src/core/server.py
git commit -m "Answer what to display, and stop rebuilding the noise floor for nothing"
```

---

## Tâche 5 : le bouton, dans la console

**Files:**
- Modify: `src/console/params_form.py`, `src/console/mode_page.py`, `src/console/app.py`

**Interfaces:**
- Consumes: la commande `propose_params` (tâche 4) ; `spec["params"]` porte désormais `proposes`.
- Produces: `ParamsForm.proposer` (signal `str`, la clé source) ; `ParamsForm.remplir(cle, valeurs)`.

⚠️ **Écart assumé par rapport à la spec §7.** La spec écrit « `refresh_hz` est pré-rempli depuis
l'écran réel ». On affiche la valeur détectée **en aide sous le champ** au lieu de l'y écrire : la
remplir voudrait dire que la console modifie l'état du moteur sans qu'on le lui demande, alors que
l'écran de cette fenêtre n'est **pas forcément** celui du stimulus (le §11 de la spec le liste comme
un risque). La spec dit elle-même « la valeur est proposée, jamais imposée » — c'est cette
phrase-là qu'on implémente.

- [ ] **Étape 1 : le bouton et l'aide, dans le formulaire**

Dans `src/console/params_form.py`, ajouter le signal à côté de `appliquer` :

```python
    proposer = Signal(str)      # la clé du réglage qui en PROPOSE un autre
```

Dans `__init__`, à l'intérieur de la boucle `for param in self.params:`, juste après
`formulaire.addRow(etiquette, champ)` :

```python
            if param.get("proposes"):
                bouton = QPushButton(f"Proposer « {param['proposes']} »")
                bouton.clicked.connect(lambda _c=False, k=param["key"]: self.proposer.emit(k))
                formulaire.addRow("", bouton)
```

Et, toujours dans la boucle, pour le seul champ du rafraîchissement, l'aide qui dit ce que Qt voit :

```python
            if param["key"] == "refresh_hz":
                ecran = QApplication.primaryScreen()
                if ecran is not None:
                    detecte = QLabel(f"cette fenêtre est sur un écran à "
                                     f"{ecran.refreshRate():g} Hz — mais c'est le rafraîchissement "
                                     f"de l'écran qui AFFICHE les cibles qu'il faut mettre ici")
                    detecte.setWordWrap(True)
                    detecte.setStyleSheet("color: #8a8f9c; font-size: 11px;")
                    formulaire.addRow("", detecte)
```

Ajouter `QApplication` à l'import PySide6 de ce fichier. Et la méthode de remplissage :

```python
    def remplir(self, cle, valeurs):
        """Écrit une proposition dans un champ, SANS l'appliquer.

        L'étudiant voit ce qu'on lui propose et clique « Appliquer » lui-même. Appliquer à sa
        place lui retirerait la seule occasion de comprendre ce qui vient de changer.
        """
        champ = self.champs.get(cle)
        if champ is None:
            return
        champ.setText(", ".join(f"{float(v):g}" for v in valeurs))
```

- [ ] **Étape 2 : brancher dans la page**

Dans `src/console/mode_page.py`, après `self.formulaire.appliquer.connect(self._appliquer)` :

```python
        self.formulaire.proposer.connect(self._proposer)
```

Et la méthode :

```python
    def _proposer(self, cle):
        """Demande une proposition au MOTEUR et la met dans le champ. La console ne calcule rien.

        Le refus et l'avertissement passent par le même endroit que ceux d'« Appliquer » : un
        étudiant n'a pas à apprendre deux façons de lire un message d'erreur.
        """
        ack = self.console.commande("propose_params", id=self.mode_id, key=cle)
        if not ack.get("accepted"):
            self.formulaire.show_refus(ack.get("reason", ""))
            return
        self.formulaire.remplir(ack["key"], ack["value"])
        self.formulaire.show_refus(ack.get("warning", ""))
```

- [ ] **Étape 3 : le test**

Dans `_smoke()` de `src/console/app.py`, dans le bloc qui utilise le VRAI moteur (`reelle`), après
les vérifications de refus existantes :

```python
    # Le bouton « Proposer » de bout en bout : clic -> commande au moteur -> champ rempli -> et la
    # valeur obtenue est ACCEPTÉE. C'est ce dernier point qui compte : une proposition que la
    # validation refuse serait le pire des deux mondes.
    page = reelle.pages["ssvep"]
    page.formulaire.champs["freqs"].setText("15, 20, 8.57143")
    page._proposer("refresh_hz")
    propose = page.formulaire.values()["freqs"]
    chk(len(propose) == 3, f"« Proposer » remplit le champ ({propose})")
    chk(all(abs(60.0 / f - round(60.0 / f)) < 1e-6 for f in propose),
        "avec des diviseurs du rafraîchissement déclaré")
    page._appliquer(page.formulaire.values())
    chk(page.formulaire.refus.text() == "",
        f"et le moteur accepte ce qu'il a lui-même proposé ({page.formulaire.refus.text()})")

    # Le refus qui ferme le trou, vu depuis l'interface.
    page.formulaire.champs["freqs"].setText("15, 17")
    page._appliquer(page.formulaire.values())
    chk("diviseur entier" in page.formulaire.refus.text(),
        f"17 Hz est refusé avec sa raison ({page.formulaire.refus.text()[:70]}…)")
```

- [ ] **Étape 4 : lancer**

Run: `python src/console/app.py --smoke`
Expected: `[console-smoke] VERDICT : OK`

- [ ] **Étape 5 : les deux autres smokes**

Run: `python src/core/server.py --smoke` · `python src/research/app.py --smoke`
Expected: deux `VERDICT : OK`.

- [ ] **Étape 6 : NE PAS lancer la console en fenêtre**

Un sous-agent n'a pas d'écran, et une console laissée vivante tient une session BrainFlow tout en
publiant sous les noms de flux PUBLICS. **Ne lancer aucun processus long.** L'essai fenêtré est
noté pour la séance matérielle.

- [ ] **Étape 7 : commit**

```bash
git add src/console/
git commit -m "Give the form a button that asks the engine what the screen can display"
```

---

## Tâche 6 : la documentation dit ce que le code fait

**Files:**
- Modify: `docs/SPEC.md`, `README.md`

- [ ] **Étape 1 : SPEC §12.2, la table des commandes**

Ajouter une ligne à la table « Commandes exposées (API interne, §12.1) — table à jour » :

```markdown
| `propose_params` | `id`, `key` | rend un jeu de valeurs proposé pour le réglage que `key` propose ; **ne l'applique pas** |
```

- [ ] **Étape 2 : SPEC §14, la roadmap**

Remplacer la ligne « **[à faire — chantier 2]** proposition automatique de fréquences… » par :

```markdown
   - **[fait 2026-07-29 — chantier 2]** proposition de fréquences SSVEP accordée au pic alpha de
     la personne (`refresh_hz` propose `freqs`), et refus d'une fréquence qui ne divise pas le
     rafraîchissement déclaré. Conception :
     [docs/superpowers/specs/2026-07-29-proposition-frequences-design.md](superpowers/specs/2026-07-29-proposition-frequences-design.md).
     - **[à faire]** mesurer le pic alpha au casque plutôt que le faire saisir — la vraie bonne
       réponse, écartée pour tenir le chantier court.
     - **[à faire]** réglages des autres modes, quand ils auront un runtime.
```

- [ ] **Étape 3 : README, la section SSVEP**

Après le paragraphe qui explique que changer les fréquences recrée le flux, ajouter :

```markdown
Frequencies must be **integer divisors of the refresh rate of the screen showing the targets** — at
60 Hz: 30, 20, 15, 12, 10, 8.571. Anything else makes the display skip cycles, and the decoder
correlates against a sinusoid nobody is displaying: no error, no detection, nothing to debug. The
engine now refuses those, and the console has a **Propose** button that asks it for a valid set.

The proposal steers away from the **individual alpha peak**, which is a per-person trait (population
mean ≈ 9.6 Hz, range 7–13). A target sitting on someone's peak does not stand out from their own
resting background — so the set that works for one person can fail for the next. Set `alpha_hz` per
person; `python src/research/alpha_check.py` measures it.
```

- [ ] **Étape 4 : vérifier**

Run: `grep -rn "propose_params\|alpha_hz\|refresh_hz" README.md docs/SPEC.md`
Expected: les trois mentions ci-dessus, et rien d'orphelin.

- [ ] **Étape 5 : les trois smokes une dernière fois**

Run: les trois `--smoke`. Expected: trois `VERDICT : OK`.

- [ ] **Étape 6 : commit**

```bash
git add README.md docs/SPEC.md
git commit -m "Document the trap the proposal exists to close"
```

---

## Après le plan : ce qui reste à vérifier sur le casque

Rien dans ce chantier n'est vérifiable sans matériel — mais deux choses méritent la séance :

1. **Ouvrir la console en fenêtre** (dette héritée du chantier 1, jamais faite) et vérifier que le
   bouton « Proposer » remplit bien le champ, et que l'aide sur le rafraîchissement détecté dit
   quelque chose de sensé sur ta machine.
2. **Mesurer ton pic alpha** avec `alpha_check.py`, le mettre dans `alpha_hz`, cliquer « Proposer »
   et vérifier que ça régénère bien 8,571 / 15 / 20 Hz — la non-régression, vécue plutôt que testée.

## Auto-relecture

- **Couverture de la spec** : §4 → tâche 2 · §5 → tâche 3 · §6 → tâche 1 · §7 → tâche 5 ·
  §8 → tâche 2 (contrainte) et tâche 5 (affichage) · §9 → tâche 3 étape 2 (test des défauts) ·
  §10 → périmètre respecté, rien hors sujet · §11 → tests répartis sur les tâches 1 à 5 ·
  §12 → constantes nommées et commentées en tâche 1.
- **Un écart assumé, écrit noir sur blanc** : le pré-remplissage du rafraîchissement devient une
  aide affichée (tâche 5), pour ne pas faire modifier l'état du moteur par la console sans demande.
- **Deux inconnues levées pendant l'auto-relecture**, plutôt que laissées à l'implémenteur :
  `EngineServer._one` n'accepte **pas** de mode arrêté (le plan passe donc par `_resolve`), et la
  première rédaction de la tâche 4 était **fausse** — sauter `_begin_shared_rest` aurait laissé un
  runtime reconstruit sans plancher de repos, qui se serait dit « décode » sans jamais rien
  décider. La correction ne reconstruit plus le runtime du tout.
- **L'algorithme de la tâche 1 a été écrit et éprouvé AVANT d'entrer dans ce plan** : identique à
  la force brute là où elle est calculable, il régénère le trio validé casque, tient 8 cibles à
  240 Hz en moins d'une milliseconde, et respecte les quatre invariants sur 294 cas. La première
  version oubliait de borner le HAUT de la bande passante (`available_frequencies` ne borne que le
  bas) et proposait 50 Hz à 100 Hz de rafraîchissement — corrigé.
