# Tranche F — revue finale : publication LSL, contrat des réglages, console

Périmètre relu : `src/core/lsl_io.py`, `src/core/modes/contract.py`, la suppression de
`src/core/modes/external.py`, `src/console/{__init__,app,grid,live_views}.py`,
`examples/receiver.py`. Lecture seule, aucun programme exécuté.

**Décompte : 1 Critical · 3 Important · 4 Minor.**

Ce qui est solide et que je ne redis pas point par point : la suppression d'`external.py` est
complète (aucun importeur résiduel dans `src/`, `SSVEP_SPAN_SEUILS` renommé partout, zéro
occurrence restante) ; la branche « tuile grisée » est bien recouverte par un `ModeSpec` FABRIQUÉ
avec son contraste `status="moteur"` (`app.py:313-337`) ; `DecodedCVEPPublisher` publie bien les 10
voies et la distinction métadonnées-figées / voies-vivantes est dite aux deux endroits ;
`_publish` (`cvep.py:613-614`) lit `self.params` **une seule fois** pour le flux ET pour l'écran,
donc les deux ne peuvent pas diverger ; l'aiguillage de rendu est branché sur une CLÉ PRÉSENTE
(`corr_min`) et non sur l'identifiant du mode, aux deux endroits ; `examples/receiver.py` liste
bien les neuf suffixes, `status` compris. J'ai aussi vérifié la crainte de `cvep.py:368-372`
(`len(self.plan)` contre `CVEP_N_TARGETS`) : `build_targets()` dérive le plan de
`config.cvep_targets()`, jamais du modèle — les deux comptes sont égaux par construction, la voie
annoncée par le `ModeSpec` et celle publiée par le flux ne peuvent pas se contredire. Rien à
signaler.

---

## CRITICAL

### C1 — `src/core/lsl_io.py:695, 764, 784, 801, 868` — l'autotest lit de la mémoire LIBÉRÉE. C'est LA cause de l'échec transitoire, et ce n'est pas un test instable

**Verdict sur le point escaladé n°2 : ce n'est pas un quatrième test instable. C'est un
use-after-free, dont la cause est parfaitement déterministe et dont seul le SYMPTÔME est
aléatoire. L'hypothèse « contention liblsl » est fausse, et le correctif qu'elle appelle (attente,
reprise, `minimum=`) ne réparerait rien tout en enterrant le vrai défaut.**

La preuve est dans le pylsl installé
(`C:\Users\Lab_IA\AppData\Local\Programs\Python\Python312\Lib\site-packages\pylsl\`) :

- `outlet.py:226-228` — `StreamOutlet.get_info()` fait
  `return StreamInfo(handle=lib.lsl_get_info(self.obj))`. `lsl_get_info` rend une **copie
  possédée par l'appelant**.
- `info.py:71-72` — `StreamInfo(handle=...)` pose `self.obj` sans aucun drapeau « emprunté ».
- `info.py:97-103` — `StreamInfo.__del__` appelle **inconditionnellement**
  `lsl_destroy_streaminfo`, ce qui détruit l'arbre XML de cette copie.
- `info.py:247` — `StreamInfo.desc()` rend `XMLElement(lib.lsl_get_desc(self.obj))`, et
  `XMLElement.__init__` (`info.py:455-457`) ne garde **qu'un `c_void_p` brut** : aucune référence
  vers le `StreamInfo` propriétaire.

Or l'autotest écrit systématiquement :

```python
ssvep_deco = pub_ssvep.outlet.get_info().desc().child("decoding")   # lsl_io.py:784
...
assert ssvep_deco.child_value("no_decision_index") == "-1", "no_decision_index manquant (SSVEP)"
```

Le `StreamInfo` temporaire a un compteur de références nul **à la fin de la ligne 784** : CPython
appelle `__del__`, liblsl libère le document pugixml, et `ssvep_deco.e` devient un pointeur
pendant. La ligne 787 lit donc un bloc de tas déjà rendu à l'allocateur. La plupart du temps les
octets y sont encore intacts et l'assertion passe ; de temps en temps le bloc a été réutilisé et
`child_value` rend `""` — d'où exactement le message rapporté, environ 1 fois sur 6. Le
comportement est indéfini : le même code peut aussi faire tomber le processus sur une violation
d'accès, auquel cas l'autotest ne sortirait ni 0 ni 1.

Les cinq sites concernés :

| Ligne | Expression | Lectures après libération |
|---|---|---|
| 695 | `desc = inlet.info().desc()` | 8 (`node.child_value("label")` en boucle) |
| 764 | `deco = pub.outlet.get_info().desc().child("decoding")` (P300) | 4 |
| 784 | `ssvep_deco = pub_ssvep.outlet…` | 2 |
| 801 | `errp_deco = pub_errp.outlet…` | 7 |
| **868** | `cvep_deco = pub_cvep.outlet…` (**ajouté par ce chantier**) | **12** (la compréhension de dict) |

Sont SAINS, et montrent d'ailleurs la bonne forme : `lsl_io.py:895` (tout en une seule
expression), `:838` et `:903` (`…get_info().name()`, la chaîne est copiée pendant que le
temporaire vit), et `examples/receiver.py:52-53`, qui garde délibérément `info = inlet.info()`
dans une variable — la seule occurrence correcte du dépôt.

Ce chantier n'a pas introduit le motif, mais il en a ajouté l'exposition la plus large (12
lectures) et deux constructions `DecodedCVEPPublisher`/`StreamOutlet` de plus, qui font tourner
l'allocateur : ça suffit à faire passer un défaut latent au-dessus du seuil de visibilité.

**Correctif minimal** — garder le `StreamInfo` vivant. Cinq lignes, aucune logique touchée :

```python
info_cvep = pub_cvep.outlet.get_info()          # ⚠️ la référence DOIT vivre plus longtemps que
cvep_deco = info_cvep.desc().child("decoding")  #    l'XMLElement : `desc()` rend un pointeur NU
```

…et idem pour `pub` (P300, l.764), `pub_ssvep` (l.784), `pub_errp` (l.801), `inlet` (l.695, où il
suffit de remplacer `desc = inlet.info().desc()` par `info_in = inlet.info()` puis
`desc = info_in.desc()`). Écrire au-dessus le commentaire de la règle, parce qu'elle se
reproduira : *un `XMLElement` ne possède rien ; le `StreamInfo` dont il vient doit rester
référencé tant qu'on lit dedans.*

**La mesure qui tranche sans appliquer le correctif** (si on veut la preuve avant le fix) : réécrire
l'assertion l.787 en UNE seule expression —
`assert pub_ssvep.outlet.get_info().desc().child("decoding").child_value("no_decision_index") == "-1"`.
Si l'instabilité disparaît sous cette forme et persiste sous la forme en deux instructions, c'est
la durée de vie, pas liblsl. La contre-épreuve, encore plus nette : insérer
`junk = [bytes(4096) for _ in range(2000)]` entre la ligne 784 et l'assertion — si elle échoue
alors **à tous les coups**, le diagnostic est confirmé.

---

## IMPORTANT

### I1 — `src/core/modes/contract.py:47-54` — le commentaire réécrit promet pour tout le monde, et il est FAUX pour 3 des 7 réglages `affecte_decodage=False` du dépôt

Le commentaire dit désormais : « False = changer ce réglage n'exige PAS de reconstruire le runtime
(donc pas de flux recréé, pas de chauffe refaite) » et pose une condition unique : « un réglage
`False` ne doit jamais être mis en cache dans `__init__` ».

Inventaire complet des `affecte_decodage=False` dans `src/` :

| Réglage | Fichier:ligne | La promesse tient ? |
|---|---|---|
| `refresh_hz` | `modes/ssvep.py:226` | ✅ jamais lu par le décodeur (`proposes="freqs"`) |
| `alpha_hz` | `modes/ssvep.py:241` | ✅ idem |
| `corr_min` | `modes/cvep.py:683` | ✅ relu à chaque `decide` (`cvep.py:506-511`) |
| `margin` | `modes/cvep.py:692` | ✅ idem |
| `stream_in` | `modes/cvep.py:699` | ❌ **non** |
| `stream_in` | `modes/errp.py:672` | ❌ **non** |
| `stream_in` | `modes/p300.py:537` | ❌ **non** |

Pour `stream_in`, la lettre de la promesse est vraie (`server._set_params:337-344` ne reconstruit
effectivement rien) mais l'effet attendu est nul : le nom du flux de marqueurs est résolu **une
seule fois**, à la création de l'inlet unique du moteur, et `_ouvre_marker_inlet`
(`server.py:872-878`) refuse de recréer quoi que ce soit tant que `self.marker_inlet` est non-None
— sa propre docstring le dit en ⚠️ : « Changer « Flux de marqueurs » sur un mode déjà démarré ne
rouvre PAS l'inlet sur un nouveau nom ». Le moteur continue donc d'écouter l'ancien nom.

Et le message que l'opérateur lit est pire que le silence : `server.py:342-343` imprime
« *(sans effet sur le décodage : ni repos refait, ni flux recréé)* », ce qui se lit comme « c'est
appliqué, et c'était gratuit ».

Scénario : en TP, deux binômes. B s'aperçoit qu'il écoute le flux de A, corrige « Flux de
marqueurs » sur sa page P300, clique Appliquer, lit le message rassurant du terminal — et continue
d'épocher l'EEG de B autour des feedbacks affichés chez A, en publiant des verdicts plausibles et
faux. C'est nommément le défaut que `errp.py:664-669` dit exister pour empêcher.

Le vrai problème est que la **condition énoncée ne détecte pas ce cas** : `stream_in` n'est pas mis
en cache dans le `__init__` du runtime, il est mis en cache dans `EngineServer.marker_inlet`. Un
contributeur qui ajoute demain un réglage `False` en appliquant le test écrit ici livrera un no-op
silencieux et croira avoir respecté le contrat. Les `help` des trois `stream_in` sont, eux,
parfaitement honnêtes (« Le changer pendant que le mode tourne n'a AUCUN effet ») — c'est le
commentaire partagé, celui qui fait autorité pour les futurs réglages, qui les contredit.

**Correctif minimal** — élargir la condition et nommer l'exception, sans toucher au code :

```python
    affecte_decodage: bool = True   # False = changer ce réglage n'exige PAS de reconstruire le
                                    # runtime (donc pas de flux recréé, pas de chauffe refaite).
                                    # ⚠️ Ce n'est PAS « le décodeur ne le lit jamais » : le c-VEP
                                    # lit `corr_min`/`margin` à CHAQUE décision, et c'est
                                    # justement ce qui rend `False` vrai chez lui. La condition à
                                    # respecter est donc : la valeur ne doit être FIGÉE NULLE PART
                                    # — ni dans le `__init__` du runtime, ni dans un objet du
                                    # moteur construit à partir d'elle.
                                    # ⚠️ `stream_in` (cvep/errp/p300) est `False` pour une autre
                                    # raison, et NE tient PAS cette promesse : il sert à ouvrir
                                    # l'inlet de marqueurs UNIQUE du moteur, résolu une fois pour
                                    # toutes (`server._ouvre_marker_inlet`). Le changer en séance
                                    # ne fait rien : il faut ARRÊTER puis redémarrer le mode. Il
                                    # est `False` seulement pour éviter de refaire 23 s de chauffe
                                    # pour rien — son `help` le dit à l'étudiant, et c'est le seul
                                    # endroit où il l'apprend.
```

Si on veut le rendre vérifiable plutôt que documenté (mieux, et cinq lignes de plus dans
`server._set_params`) : quand le lot de réglages appliqué en place contient une clé que
`_nom_flux_marqueurs` lit, imprimer explicitement « **`stream_in` inchangé côté réseau — arrête et
redémarre ce mode pour écouter « X »** » au lieu du message rassurant actuel.

### I2 — `src/console/grid.py:240` et `src/console/live_views.py:274` — l'échelle du c-VEP est écrite DEUX FOIS, et les deux copies diffèrent déjà

```python
# grid.py:240   (la TUILE)
self.apercu.set_values(scores, span=min(SPAN_SEUILS * float(corr_min), 1.0), retenue=retenue)

# live_views.py:274   (la PAGE)
span = min(SPAN_SEUILS * corr_min, 1.0) or 1.0
```

Le `or 1.0` n'est que sur un des deux côtés. `corr_min = 0.0` est une valeur **légale**
(`cvep.py:683` déclare `min=0.0`) et **encouragée en séance** (le `help` du même réglage :
« DESCENDS cette valeur en séance si le mode reste muet malgré un bon contact — SANS risque »,
et `docs/recette.md` 2.9 fait descendre le seuil à 0,05 comme geste de routine). À `corr_min = 0` :

- page : `span = 0.0 or 1.0 = 1.0` → une corrélation de 0,33 remplit la barre à **33 %** ;
- tuile : `span = 0.0`, puis `MiniBars.set_values` (`grid.py:55`) le rattrape en
  `max(0.0, 1e-6) = 1e-6` → **toutes les barres pleines**, y compris celles à 0,08.

Mêmes données, deux lectures — mot pour mot le défaut que `console/__init__.py:57-62` raconte
pour `classement_relatif` (« Elle était écrite deux fois, mot pour mot […] La page a été corrigée
lors d'un chantier, la tuile oubliée »), et que ce chantier cite lui-même comme sa raison d'être.
La docstring conclut : « *les garder d'accord demande qu'elles appellent le MÊME code, pas
qu'elles se ressemblent* ». Ici elles se ressemblent, et elles ont déjà commencé à diverger, dans
le commit qui les écrit.

L'assertion `app.py:879-882` qui lie tuile et page ne l'attrape pas : elle ne tourne que sur
`corr_min = 0.26`.

**Correctif minimal** — remonter la formule à côté de `SPAN_SEUILS`, là où la règle sœur vit
déjà :

```python
# console/__init__.py, sous SPAN_SEUILS
def span_correlation(corr_min):
    """L'échelle absolue d'un score BORNÉ, contre le seuil publié. UNE seule écriture — la tuile
    et la page l'appliquaient chacune de leur côté et différaient déjà d'un `or 1.0` (à
    corr_min=0, réglage légal et encouragé en séance, la tuile montrait tout PLEIN et la page
    33 %). PLAFOND à 1 et non plancher, contrairement au z du SSVEP : une corrélation de Pearson
    vit dans [-1, 1], et 2 × 0,26 = 0,52 est justement l'échelle qui sépare 0,21 de 0,33.
    """
    return min(SPAN_SEUILS * float(corr_min), 1.0) or 1.0
```

puis l'appeler des deux côtés. Et ajouter au smoke le seul cas qui distingue les deux écritures :
rejouer le bloc c-VEP avec `"corr_min": 0.0` et réutiliser telle quelle l'assertion
`parts_tuile == [b.value() for _e, b in cv._barres]` de `app.py:880`.

### I3 — Les compteurs du mode ne sortent nulle part pour un opérateur, alors que `docs/recette.md` 2.9 en fait « LE point de ce test »

**Réponse au point escaladé n°3.** J'ai suivi les trois chemins :

1. **La console : rien.** Aucun fichier de `src/console/` ne lit `decodages`, `sans_reference`,
   `reference_perimee`, `sous_les_seuils`, `vote_non_conclu`, `marqueurs_refuses`,
   `age_reference_s`, `corr_gagnant` ni `corr_second`. `grid._resume:262` et
   `live_views._update_correlations:283` n'affichent que le `motif` de la **dernière fenêtre**.
   Le fixture du smoke (`app.py:832-834`) POSE ces huit valeurs et **aucune assertion ne les
   regarde** — signe que quelqu'un a prévu l'affichage puis ne l'a pas fait.
2. **`server.py` headless : rien non plus** pour les quatre causes. `cvep._log:643-657` imprime le
   motif de la dernière fenêtre ~1×/s ; seuls les `marqueurs_refuses` s'annoncent aux paliers
   (`cvep.py:125`).
3. **Le flux `status` : oui.** `snapshot()` → `modes_state[mid] = r.state()`
   (`server.py:790`), republié toutes les 2 s par le rappel périodique (`server.py:1244-1247`,
   `force=due` — les compteurs sont hors de `_status_key`, donc ils ne voyagent QUE par ce
   rappel, ce qui suffit). Lisible avec `python examples/receiver.py --stream status`, sous forme
   d'un dump JSON brut à 0,5 Hz.

Donc le seul chemin qui existe est celui que la recette présente comme le repli, et le chemin
qu'elle recommande n'existe pas. `docs/recette.md` dit, aux deux endroits :

> « **La console plutôt que le moteur nu** […] les compteurs qui font tout l'intérêt de ce test
> **s'y lisent d'un coup d'œil** » (l. 432-434)
> « **LE point de ce test.** Ouvrir la page c-VEP et regarder POURQUOI c'est -1 : c'est
> `sous_les_seuils` qui doit monter » (l. 463-464)
> « Relever lequel domine : ____________ » · « Regarder aussi `age_reference_s`, `corr_gagnant` et
> `corr_second` » (l. 856-861)

2.9 n'a **jamais été joué**, et une séance casque ne se répète pas : l'opérateur ouvrira la page
c-VEP, ne trouvera pas les compteurs, et devra choisir entre relever à l'œil quel motif domine sur
cinq minutes de lignes de terminal — ce qu'un compteur existe précisément pour éviter — et
abandonner le point.

**Correctif minimal, et il reste dans le rôle de CLIENT** (afficher des nombres que le moteur
possède, avec le vocabulaire du moteur, sans en traduire un seul) : une ligne grise sous le
verdict, dans `live_views._update_correlations`, choisie comme tout le reste sur la PRÉSENCE des
clés et non sur l'identifiant du mode —

```python
        # Les compteurs du moteur, tels quels. Ils PARTITIONNENT les fenêtres traitées (cf.
        # `cvep.CVEPRuntime.state`) : c'est leur somme qui dit ce qu'a vraiment fait la séance,
        # là où le verdict au-dessus ne décrit que la dernière fenêtre. `docs/recette.md` 2.9 en
        # fait le point central de sa lecture — sans eux, « ça ne détecte pas » n'a qu'une
        # explication apparente. Aucun mot n'est traduit ici : ce sont les clés du moteur.
        cles = ("decodages", "sans_reference", "reference_perimee", "sous_les_seuils",
                "vote_non_conclu")
        vus = [(k, (mode_state or {}).get(k)) for k in cles]
        if any(v is not None for _k, v in vus):
            self.compteurs.setText("  ".join(f"{k} {v}" for k, v in vus if v is not None))
```

(plus un `self.compteurs = QLabel("")` gris dans `__init__`, et `age_reference_s`/`corr_gagnant`/
`corr_second` sur la même ligne s'ils sont là). Une assertion au smoke sur le fixture qui les pose
déjà : `chk("sous_les_seuils 5" in cv.compteurs.text(), …)`.

**Si on préfère ne pas toucher la console**, alors 2.9 doit être corrigé pour ne plus promettre ce
qu'elle ne tient pas : remplacer « ouvrir la page c-VEP » par la commande réelle
(`python examples/receiver.py --stream status`, quatrième terminal, lire
`modes_state.cvep.*`). Ce qui n'est pas acceptable, c'est de laisser les deux en l'état pour la
séance qui reste à jouer.

---

## MINOR

### M1 — `src/console/app.py:830` — le fixture du smoke décrit l'ANCIENNE forme du flux (8 voies, sans `corr_min`/`margin`)

**Réponse au point escaladé n°1 : Minor, confirmé inerte, mais à corriger.** J'ai vérifié qu'aucun
code ne lit ce champ : `mode_page.py:53` construit la vue avec `spec["channels"]` (le `ModeSpec`
sérialisé du registre), pas avec `mode_state["channels"]`, et `live_views.build:510-514` ne
transmet `ch_names` qu'à `TracesView` (famille « brut »). La ligne est donc décorative pour la
console.

Elle n'est pas décorative pour le lecteur : `modes_state[*]["channels"]` part sur le flux `status`
et un client le lit. Les cinq autres fixtures du même smoke (`:205`, `:452`, `:501`, `:551`,
`:669`) sont, elles, exactes ; celle-ci est la seule à mentir, et rien ne la relie à sa source.
Le prochain test qui la réutilisera héritera de l'erreur.

**Correctif minimal** — la faire dériver au lieu de la recopier, ce qui la rend impossible à
périmer (`console/app.py` importe déjà `core` en toute légalité) :

```python
from core.lsl_io import cvep_channel_labels
...
        "channels": cvep_channel_labels(6),
```

### M2 — `src/console/grid.py:7-9` — la docstring du module dit encore que le c-VEP est ce que le moteur ne sait pas faire

> « Les modes que le moteur ne sait pas faire sont affichés, grisés, avec leur raison. Sans eux, un
> étudiant croirait que le produit fait trois choses et ne saurait pas qu'un décodeur c-VEP validé
> l'attend dans `src/research/app.py`. »

Les deux affirmations sont fausses depuis ce chantier : le c-VEP est dans le moteur, sa tuile est
cliquable, et « trois choses » en vaut sept. C'est le paragraphe où un étudiant apprend pourquoi
des tuiles grises existent, et il illustre la règle avec le contre-exemple qu'il a sous les yeux.

**Correctif minimal** : garder la règle, retirer l'exemple périmé — « *Un mode que le moteur ne
sait pas faire est affiché quand même, grisé, avec sa raison. Il n'y en a aucun aujourd'hui — le
c-VEP a été le dernier, et il a rejoint le moteur — mais la branche reste : sans elle, le premier
mode décrit avant d'être fait serait invisible, et l'étudiant croirait que le produit se limite à
ce qui est chargé. Elle est éprouvée sur un `ModeSpec` fabriqué (cf. `console/app.py`).* »

### M3 — `src/console/app.py:298` et `:386-389` — un compte en dur dans une prose, et une assertion devenue vide qui n'est pas signalée

- `:298` — le message d'assertion écrit « **7 modes, 7 dans le moteur** ». Deux commentaires plus
  haut (`:276-280`) le même fichier interdit exactement ça : « *Le compte attendu est LU DANS LE
  REGISTRE, pas écrit ici […] un chiffre en dur redeviendrait faux au premier mode qui migre* » —
  et la docstring supprimée d'`external.py`, que ce même diff cite ailleurs, disait « *un chiffre
  recopié dans une prose finit toujours par mentir d'un mode* ». Correctif : `f"…dégrisées, c-VEP
  compris — {len(console.grid.tuiles)} tuiles, toutes dans le moteur (…)"`.
- `:386-389` — `chk(all(t.demarrage.isHidden() … if t.spec["status"] != "moteur"), "les modes de
  l'appli pygame n'exposent aucun bouton de démarrage")` est désormais VIDE (l'itérable est vide),
  comme ses deux voisines de `:286-290` — mais contrairement à elles il n'est pas signalé comme
  tel, et son message parle encore de « l'appli pygame », un statut que plus aucun mode ne porte.
  La tuile fabriquée (`:325`) couvre déjà exactement cette propriété. Correctif : soit la retirer
  au profit de `:325`, soit lui coller le même ⚠️ « vide aujourd'hui, réveillée par le prochain
  mode décrit avant d'être fait ».

### M4 — `src/console/live_views.py:25` et `:173` — `Z_MIN` reste importé et gardé comme repli, alors que `grid.py` l'a chassé avec interdiction de retour

`grid.py:22-24` porte : « *`Z_MIN` n'est PLUS importé, et c'est le correctif […] Ne pas le
réintroduire ici — une constante d'un mode ne met pas à l'échelle la sortie d'un autre.* » Son
voisin `live_views.py` l'importe toujours et l'utilise en défaut ligne 173 :
`seuil = float(sortie.get("threshold", Z_MIN))`.

Le repli est aujourd'hui **mort** — `_update_scores` n'est atteint que via
`elif "threshold" in sortie` (`:162`), donc `.get` trouve toujours la clé. Il n'est pas nuisible,
il est trompeur : c'est littéralement la ligne de code dont la docstring du même fichier
(`:105-109`) raconte qu'elle a fait annoncer « échelle z · seuil 3 » au-dessus de log-odds pendant
deux chantiers, et le c-VEP vient d'ajouter une quatrième branche à cet aiguillage. Le jour où
quelqu'un déplacera un `elif`, le piège se réarme tout seul.

**Correctif minimal** : `seuil = float(sortie["threshold"])` — la clé est garantie présente par
l'aiguillage, et un `KeyError` bruyant vaut mieux qu'un seuil inventé. `Z_MIN` disparaît alors de
l'import, et les deux fichiers de la console tiennent enfin la même règle.
