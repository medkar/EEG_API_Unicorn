# Revue de branche — trois constats du moteur, corrigés

Chantier « plus une seule commande à taper ». Tâche hors plan : les trois constats *important* de
la revue de branche du 2026-09-10, déjà diagnostiqués. Aucune conception, trois correctifs.

**Statut : les trois sont faits, prouvés par mutation, et commités séparément.**

| # | constat | commit |
|---|---|---|
| 1 | un `calib_end` perdu pouvait détruire une séance complète | `7569997` |
| 2 | les essais jetés disparaissaient du dénominateur en silence | `fef5173` |
| 3 | `src/console/` n'était scanné par aucune règle de frontière | `4168924` |

---

## 1 — `_verifie_silence` comparait le mauvais compteur (`7569997`)

`src/core/modes/ssvep_mesure.py`.

La docstring promettait de ne pas jeter une séance dont **tous les essais annoncés sont arrivés**
et dont seul le `calib_end` manque. La condition comparait `self.essai`, qui ne compte que les
essais dont l'**époque** a pu être prélevée — il est plus petit de `_epoques_perdues`, et un seul
tour de boucle ralenti suffit à en perdre une. Les deux compteurs coïncident tant qu'aucune époque
n'est perdue : c'est exactement pourquoi le défaut n'était pas visible, et pourquoi le test qui
existait déjà (`rt3`, un essai annoncé, un reçu) restait vert quel que soit le compteur comparé.

La condition lit désormais `_essais_vus`, le nombre de `cue` LISIBLES — la seule grandeur
comparable au `trials` que la fenêtre annonce dans son `calib_start`. Les deux messages (attente et
abandon) impriment maintenant les DEUX nombres.

**Test ajouté** — `moteur4` : 12 essais annoncés, 12 `cue` reçus, un seul (au milieu, pas au bord)
dont l'EEG précède le tampon. Plus un contrôle de sens, `moteur5` : à un `cue` de moins, la fenêtre
n'a pas fini et le silence doit bien tuer la séance — sans lui, une garde rendue muette passerait.

**Preuve par mutation** (condition remise à `self.essai`) :

```
ÉCHEC …et une époque perdue ne transforme PAS une séance complète en fenêtre morte : la séance
      ATTEND son `calib_end` et ses 0 essais valides sont INTACTS (annule, 11/12).
[mesure-ssvep] VERDICT : PROBLÈME
```

`annule`, et **0** époques restantes sur 11 : `cancel()` les a détruites, ce que la méthode existe
pour empêcher. Et c'est le SEUL rouge du dépôt — `server.py --smoke` reste vert sur ses 22 sections
sous la même mutation.

## 2 — Les essais jetés sont publiés et nommés (`fef5173`)

`src/core/modes/ssvep_mesure.py`, `src/console/mesure_page.py`.

`_epoques_perdues` et `_marqueurs_chauffe` étaient comptés et **imprimés sur stdout**, que la
console ne montre pas. `n_essais = len(decisions)` ne compte que les essais retenus : une séance de
36 dont 10 époques débordent rend « Sur **26** ESSAIS… », intervalle calculé sur 26, sans un mot
sur les 10.

`rejouer` prend `perdus`/`chauffe`, publie `n_perdus`/`n_chauffe`, et `verdict` les **nomme**.
L'ordre compte : les perdus AVANT les artefacts, parce que les artefacts SONT dans `n_essais` (ils
y comptent comme « aucune cible ») et les perdus n'y sont pas. `MesurePage.DETAILS` gagne les deux
lignes correspondantes, à côté de `n_artefacts`.

Les deux valent **0 par défaut** : c'est ce que sait honnêtement `research/ssvep_guided.py`, qui
rejoue un fichier archivé et ne peut pas connaître ce que la séance a perdu le jour où elle a été
prise. Dit dans la docstring de `rejouer`.

**Preuve par mutation, les deux moitiés du défaut** :

- arguments retirés de l'appel dans `_mesurer` (*compté, pas publié*) → **3 assertions rouges**,
  `26 retenus, 0 perdus, 0 jetés` ;
- arguments gardés, phrase retirée de `verdict` (*publié, pas nommé*) → **1 assertion rouge**.

Un gabarit constant passerait les deux : une quatrième assertion vérifie qu'une séance qui n'a rien
perdu n'en parle pas.

## 3 — La quatrième section de frontière (`4168924`)

`src/core/server.py`, `CLAUDE.md`.

`_smoke_frontiere` avait trois sections — `core`, `stimulus`, `research`. `src/console/` n'était
scanné nulle part et `console` n'était pas dans `_FRONTIERE_RESEARCH_INTERDITS` : **deux des quatre
flèches du tableau passaient**, dans les deux sens. C'est la forme exacte du défaut trouvé le
2026-09-08 sur `core` (« ni pygame **ni Qt** » écrit, seul pygame vérifié) : la règle écrite plus
large que sa vérification.

Ajouté : `_FRONTIERE_CONSOLE_INTERDITS = ("research",)`, la section 1 quater d'extraits fabriqués,
la section 5 de scan, le `chk` d'existence et l'assertion d'effectif. `console` entre dans la liste
de `research`. La liste de la console tient en un nom, et les **trois cas autorisés** comptent
autant que le cas interdit : ils pinnent `interdits_re=""`, sans quoi le motif par défaut
(`PySide\d+`) déclarerait la console fautive de haut en bas.

**Preuve par mutation, quatre fois** :

| mutation | résultat |
|---|---|
| `from research.itr import …` dans `console/grid.py` | `ÉCHEC : console/grid.py:21 importe research` |
| `from console.grid import …` dans `research/itr.py` | `ÉCHEC : research/itr.py:29 importe console` |
| dossier renommé (`src/ui_renomme`) | **0 violation**, rouge sur le `chk` d'existence |
| dossier vide | **0 violation**, rouge sur `…contient bien ses pages (0 fichiers)` |

Les deux dernières sont le point : sans ces deux `chk`, le scanner rendrait « 0 violation » et
« VERDICT : OK » en n'ayant rien vérifié.

`[smoke-frontiere] 72 fichiers scannés, 0 violation(s)` (58 auparavant : +14 fichiers de console).

**`CLAUDE.md` accordé** : « les INTERDITS des QUATRE lignes sont vérifiés », les quatre paquets
nommés, la vérification présent-et-non-vide dite, la réciproque `console ↛ research` ajoutée au
paragraphe de l'usage réel, et le commentaire de `server.py --smoke` corrigé.

---

## Vérifications

- **`data/` intact.** Empreinte `core.config.empreinte_dossier` avant et après :
  `43 fichier(s), sha256=1d33bfeddd236ec239372bf6557ae156d2f6e5825cdb5469abf4fc48c88dfe67` — la
  même aux deux instants. `seances/` à **0 fichier** aux deux instants
  (`sha256=4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`).
- **25 autotests de module** à exit 0, dont les cinq du MI, les sept du c-VEP, les six des
  marqueurs entrants, `research/ssvep_guided.py` (l'autre appelant de `rejouer`) et
  `core/acquisition.py --synthetic`.
- **Les deux smokes** à exit 0 : `server.py --smoke` (22 sections) et `console/app.py --smoke`.
- **Les quatre `--smoke` de `src/stimulus/`** à exit 0.
- Arbre propre, aucun fichier de test laissé derrière.

## Réserves

- 🟡 **`n_chauffe` reste TROMPEUR par nature**, et le verdict le dit sans pouvoir le corriger : il
  compte des MARQUEURS reçus pendant la chauffe, pas des essais — un `repos` ou un événement futur
  du protocole y entre aussi. Pour le SSVEP guidé, tout ce qui précède les essais est effectivement
  jeté, donc le nombre est utile ; la phrase parle bien de « marqueur(s) », jamais d'« essai(s) ».
  C'est le même travers que celui déjà noté dans `CLAUDE.md` pour le c-VEP.
- 🟡 **Le compteur `n_perdus` ne remonte pas dans un rejeu hors ligne.** Il vaut 0 par défaut, donc
  `research/ssvep_guided.py` annonce « aucune perte » sur un archive dont on ne sait rien. C'est
  documenté dans `rejouer`, mais un `.npz` de séance ne porte pas ce compte : le rendre exact
  demanderait de l'archiver au moment de la prise, ce qui touche le format de fichier.
- 🟡 **Une séance qui perd assez d'époques pour tomber sous 6 essais est refusée par `rejouer`,
  et la raison affichée dit « pas de quoi conclure » sans citer les perdus.** Le compteur existe,
  mais ce chemin-là lève avant de construire le résultat. Cas de bord non traité (hors périmètre) :
  il faudrait passer les perdus au message d'erreur.
- 🟡 **La règle de la console s'arrête à `research`.** `pygame` et `brainflow` n'y sont PAS
  interdits, délibérément : ce n'est pas ce que le tableau des quatre flèches dit, et l'ajouter
  serait une décision de conception, pas un correctif de revue. La console ouvre le casque par
  `EngineServer` — c'est son métier — et lance les fenêtres en sous-processus, pas par import.
- 🔵 **Le nombre 72 n'est écrit que dans les commits et ici**, jamais dans `CLAUDE.md` : un compte
  en prose n'est tenu par rien, et celui du chantier précédent était déjà faux deux commits plus
  tard. L'assertion qui compte est `vus_con >= 10`, dans le test.
