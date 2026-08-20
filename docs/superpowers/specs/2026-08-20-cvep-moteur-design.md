# Le c-VEP sur le réseau — conception

**Date** : 2026-08-20 · **État** : validé, prêt pour le plan d'implémentation

Publier le **c-VEP** comme 6e et **dernier** mode du moteur. À la fin de ce chantier, le moteur
publie les six modes de décodage du projet et l'appli pygame n'est plus qu'un lieu de calibration.

---

## 1. Ce qui est déjà mesuré, et qu'il ne faut PAS redécouvrir

Le c-VEP est le mode le mieux mesuré du projet côté performance :

- **eCCA classique : 22 bits/min électrodes salées** — le meilleur ITR du dépôt, devant le SSVEP.
- **Réfutés, mesurés, ne pas rouvrir** : le *dynamic stopping* et les **codes Gold distincts**. Les
  deux échouent pour la même raison — le SNR de huit électrodes sèches ne les porte pas.

⚠️ **Une nuance découverte en écrivant cette spec, et c'est elle qui justifie la section 6.** La
réfutation du **rCCA** est en réalité celle de « rCCA **+ codes distincts** » : les deux hypothèses
ont toujours été testées ensemble. Or `RCCAModel.__init__(codes, …)` prend ses codes en
**paramètre** — `make_distinct_codes` n'est qu'un helper d'appelant. Le décodeur par reconvolution
peut donc tourner sur le stimulus décalé qu'on garde, et **sur ce stimulus-là il n'a jamais été
mesuré**. On rouvre parce que la question posée n'était pas celle qu'on croyait, pas par optimisme.

## 2. Ce que le c-VEP a de différent, et pourquoi il est resté dehors

Le décodeur a besoin de la **phase exacte du code**, alignée frame par frame sur l'EEG. Les trois
autres modes évoqués s'en sortent autrement : le SSVEP par un couplage lâche (le client déclare ses
fréquences), le P300 et l'ErrP par des marqueurs d'événement isolés.

Aujourd'hui, la phase est lue dans le même processus que le rendu :

```python
def phase(self, refresh, code_len):
    f, t = self.frame, self.t_flip
    return int(f + (time.perf_counter() - t) * refresh) % code_len
```

L'indice de la dernière frame affichée, extrapolé par le temps écoulé — avec l'hypothèse que
l'époque EEG finit « maintenant ». Vraie dans un seul processus, fausse dès qu'on sépare.

**Ce qui a changé depuis que cette difficulté a été parkée** (piste F1 de la spec initiale) : le
moteur possède désormais un **tampon EEG horodaté en temps LSL** et un **tuyau de marqueurs
horodatés au flip**, livrés pour le P300 et étendus à l'ErrP. Les deux instants sont devenus
comparables. Le verrou n'a pas été forcé, il a été dissous par un autre chantier.

## 3. Architecture — trois programmes, le patron des deux chantiers précédents

| programme | ce qu'il possède |
|---|---|
| `src/core/server.py --mode cvep` | le casque, le décodage, la publication de `decoded_cvep` |
| `src/research/cvep_stimulus.py` | l'écran : le clignotement et les marqueurs. **N'ouvre PAS le casque** → se lance en même temps que le moteur, dans deux terminaux |
| `src/research/app.py` | la **calibration** seule (stimulus verrouillé à la frame, `Calib(kind="natif")`) |

**Le déménagement** : `cvep_decoder.py` et `cvep_code.py` passent dans `src/core/`. C'est la règle du
projet — publier un mode, c'est déménager son décodeur, pas y tirer un import.

🎯 **Et cette fois, aucun ré-entraînement.** `CVEPModel.save` écrit du `np.savez` de tableaux purs
(`w`, `template`, `fs`, `refresh`, `code_len`, `channels`, `n_targets`, `cv`), **sans pickle d'une
référence de module**. Contrairement au P300 et à l'ErrP, dont les `.joblib` ont cassé au
déménagement, `data/cvep_model.npz` (2026-07-21, n=6) se chargera tel quel. À vérifier par un test
au premier commit, pas à supposer.

## 4. Le contrat de marqueurs — une ligne de plus dans `docs/markers.md`

```json
{"mode": "cvep", "event": "cycle", "refresh": 60.0}
```

**Un marqueur au redémarrage du code**, horodaté APRÈS `pygame.display.flip()` comme les deux
émetteurs existants. Le code fait 63 frames, soit **1,05 s à 60 Hz** : environ un marqueur par
seconde.

**Pourquoi par cycle et pas autrement** — les deux autres formes ont été écartées, et pour des
raisons qu'il faut garder écrites :

- **Un marqueur par frame** serait exact sans extrapolation, mais c'est 60 marqueurs/s et surtout un
  `push_sample` **dans la boucle de rendu à chaque frame** : du travail supplémentaire à l'endroit
  précis où l'on ne peut pas s'en permettre. Le chantier ErrP vient de montrer que l'ordre
  `flip()` → `push_sample` est déjà délicat à un marqueur par seconde.
- **Un seul marqueur au départ**, puis roue libre, est écarté par la physique : à 59,94 Hz réels
  contre 60 supposés, l'erreur atteint **3,6 frames en une minute**, sur un code qui n'en fait que
  63. Le marqueur par cycle **borne la dérive à un cycle** et absorbe une frame sautée.

⚠️ **`refresh` n'est pas décoratif.** Le modèle est calibré à un rafraîchissement donné, et c'est
l'**émetteur** qui tient l'écran — le moteur ne peut pas le voir. L'appli s'en sortait par
`abs(model.refresh - app.refresh) > 1.0`, impossible une fois les deux séparés. L'émetteur déclare
donc son rafraîchissement à chaque cycle, et le moteur **refuse bruyamment** en cas de désaccord.
Sans cette garde : décodage qui tourne, scores d'apparence honnête, et **jamais aucune détection** —
exactement la panne qui a coûté une séance au SSVEP.

## 5. Le mode moteur — `src/core/modes/cvep.py`

**Le premier mode HYBRIDE du moteur, et il faut le nommer.** Le P300 et l'ErrP découpent une époque
*autour* de chaque marqueur ; le c-VEP décode **en continu sur une fenêtre glissante**, comme le
SSVEP, et ses marqueurs ne servent qu'à **tenir l'horloge du code**. `marker_epoch_s` n'y a donc pas
le sens qu'il a chez les deux autres : il dimensionne le tampon, il ne décrit pas une époque.

**La boucle** : à ~5 Hz, prendre les `CVEP_DECISION_CYCLES = 2` derniers cycles du tampon (2,1 s),
calculer la phase de la fin de fenêtre, scorer les six lags, appliquer le vote glissant existant
(`CVEP_VOTE_LEN = 3`, `CVEP_MIN_VOTES = 2`).

**La phase**, pour une fenêtre finissant à l'instant LSL `E` :

```
phase = int((E - T_dernier_cycle) * refresh) % code_len
```

**Trois états à traiter explicitement**, faute de quoi ils deviennent des pannes muettes :

1. **Aucun marqueur reçu** — pas de référence de phase, rien à décoder. Publier `-1` et le dire une
   fois, sur le patron de l'ErrP avant la fin de son repos.
2. **Marqueurs périmés** — l'émetteur a été fermé ou sa fenêtre perdue. Continuer en roue libre
   serait l'approche écartée en §4. **Péremption à 3 cycles** : au-delà, cesser de décoder, publier
   `-1`, l'annoncer une fois. L'ordre de grandeur est calculé : un rafraîchissement faux de 0,1 %
   dérive de 0,06 frame/s, donc 3 s coûtent moins d'un cinquième de frame, là où 30 s en coûteraient
   près de deux.
3. **Désaccord de rafraîchissement** — refus au démarrage, en nommant les deux valeurs.

Le mode **refuse de démarrer sans modèle**, comme le MI, le P300 et l'ErrP, en disant où calibrer.

## 6. Deux décodeurs, un seul stimulus

Le réglage `model` (patron `choices_fn` déjà en place sur le MI, le P300 et l'ErrP) liste les
modèles disponibles ; **le fichier de modèle déclare son décodeur**, et le moteur suit. L'étudiant
choisit un modèle, pas un algorithme.

**Comment le fichier le déclare, précisément** : les deux `save` gagnent un champ `decoder`
(`"eCCA"` | `"rCCA"`) dans leur `np.savez`. Un fichier **sans ce champ** est un modèle antérieur à ce
chantier, donc un eCCA — c'est le seul décodeur qui existait sous ce nom de fichier. Inférer le
décodeur de la présence de telle ou telle clé serait deviner ; un champ explicite se lit et se teste.

- **eCCA** (`cvep_decoder.CVEPModel`) — corrélation à un template appris. Le décodeur mesuré à
  22 bits/min. Défaut.
- **rCCA** (`cvep_rcca.RCCAModel`) — reconvolution : apprend une réponse transitoire courte
  (`CVEP_RCCA_ENC = 0,30 s`) et la reconvolue avec le code.

**Le stimulus est IDENTIQUE pour les deux** : la même m-séquence de 63 frames, six lags. C'est ce
qui rend l'ajout bon marché — **l'émetteur ne change pas, le contrat de marqueurs ne change pas**, et
surtout les deux décodeurs s'ajustent sur **les mêmes époques**.

🎯 **La conséquence la plus utile de ce chantier** : la calibration entraîne **les deux** et affiche
**les deux justesses en validation croisée**, à chaque séance, pour chaque personne — les deux
chiffres étant stockés dans le fichier de modèle. La question « le rCCA est-il meilleur pour cette
personne ? » reçoit donc une réponse mesurée **automatiquement**, sans que personne n'ait à faire
remonter quoi que ce soit. Et si le rCCA gagne chez quelqu'un, cette personne peut l'utiliser sur le
réseau le jour même.

⚠️ **Ce qu'on n'intègre PAS** : les **codes Gold distincts**. Ils restent réfutés, et ils sont la
partie chère — stimulus différent, donc émetteur en double.

**`cvep_rcca.py` se coupe donc en deux**, et il faut le dire pour que personne ne déplace le fichier
en bloc : `RCCAModel` et `RCCADecoder` partent dans `src/core/cvep_rcca.py` (c'est le décodeur, il
suit la règle du déménagement) ; `make_distinct_codes` et `build_targets_rcca` **restent dans
`src/research/`** comme trace de l'hypothèse testée et réfutée. Après ce découpage, leurs seuls
appelants vivent dans `archive/` — c'est voulu : une hypothèse réfutée se garde lisible, pas
branchée.

⚠️ **Deux dettes à payer dans le chantier** :
- **`pyntbci` devient une dépendance DÉCLARÉE** (`requirements.txt`), et du **moteur**, pas de la
  recherche. Elle est absente aujourd'hui : elle traîne sur ce poste par accident d'historique.
  `RCCAModel.save` ne sérialise pas l'objet pyntbci — il stocke les époques et **ré-ajuste au
  chargement** — donc le moteur en a réellement besoin. Même nature que `pyriemann`, déjà présent
  pour le P300.
- **Les seuils du rCCA sont des placeholders assumés** : `CVEP_RCCA_CORR_MIN = 0.0`,
  `CVEP_RCCA_MARGIN = 0.0`, avec le commentaire « à régler sur données réelles ; ne pas se fier au
  seuil ». Ils doivent être posés sur le stimulus décalé. Publier un mode dont le seuil n'a jamais
  été réglé serait publier du hasard avec une barre de confiance.

## 7. Le flux publié — `EEG_API_Unicorn_decoded_cvep`

`{target_index, confidence, score_0 … score_5}`, sur le patron du P300. La SPEC §5 annonçait
`{target_index, confidence}` : on étend avec les scores par cible, sans quoi un étudiant ne peut pas
voir **pourquoi** rien n'est décidé.

⚠️ **`target_index = -1` signifie « pas de décision », JAMAIS la cible 0.** Trois causes possibles
(vote non conclu, pas de référence de phase, référence périmée) que les compteurs d'état
distinguent — même choix que l'ErrP, où `-1` recouvre l'époque perdue et l'artefact.

Métadonnées : `paradigm = "c-VEP"`, `decision_scale = "correlation"`, `no_decision_index = "-1"`,
plus `code_len`, `refresh`, `n_targets`, `decoder` (`eCCA` | `rCCA`), les seuils `corr_min` /
`margin`, et la justesse en validation croisée du modèle chargé.

## 8. Ce qui se retire

| ce qui part | où | pourquoi |
|---|---|---|
| l'écran de **pilotage c-VEP** (eCCA) | `archive/`, exécutable | remplacé par le moteur. Reste la référence contre laquelle comparer le décodage réseau |
| l'écran de **pilotage rCCA** (codes Gold) | `archive/`, exécutable | son stimulus est réfuté ; le décodeur rCCA, lui, survit dans le moteur |
| la **calibration rCCA** (codes Gold) | `archive/` | remplacée : la calibration c-VEP entraîne désormais les deux décodeurs sur les mêmes époques |

La **calibration c-VEP reste au menu** : elle est le seul moyen d'obtenir un modèle.

## 9. Les tests

**Le test de phase porte le chantier**, comme le test d'alignement portait le P300.

Comparer la phase que le moteur calcule à celle que l'émetteur a **réellement affichée**, sur une
longue course incluant une **frame sautée**, et exiger qu'un décalage d'**UNE SEULE frame** le fasse
rougir.

⚠️ **Pourquoi celui-là et pas un autre** : une erreur de phase de quelques frames **ne casse rien**.
Les corrélations baissent, le mode continue de publier, les scores restent d'apparence honnête, et
la détection se contente de ne presque jamais se déclencher. C'est indiscernable d'un étudiant qui
ne fixe pas la cible — et donc invisible à tout test qui vérifie seulement que « ça tourne ».

Autour de lui, quatre gardes :

- **Bout en bout synthétique** : EEG c-VEP synthétique à lag connu + marqueurs de cycle → le moteur
  doit désigner CETTE cible. Prouve la chaîne entière sans casque.
- **La garde de rafraîchissement** : l'émetteur déclare 144, le modèle dit 60 → refus, en nommant
  les deux valeurs.
- **La péremption** : les marqueurs s'arrêtent → le décodage s'arrête, `-1`, dit une fois.
- **Le modèle survit au déménagement** : `data/cvep_model.npz` se charge depuis `core/` — le test
  qui aurait évité deux ré-entraînements s'il avait existé avant.

Et pour les deux décodeurs : **la comparaison de calibration ne doit pas mentir**. Validation croisée
groupée sur les mêmes époques, jamais deux protocoles différents comparés entre eux.

## 10. La séance casque — la dette la plus vieille du projet

Trois chantiers ont été livrés sans qu'un casque soit branché : marqueurs+P300, ErrP, et celui-ci.
Le chantier se termine par une **séance qui couvre les trois** — les tests 2.7 et 2.8 existent déjà,
le 2.9 est à écrire.

Le c-VEP en a plus besoin que les autres, pour la raison donnée en §9 : sa panne caractéristique est
un décodage **dégradé mais plausible**, que le synthétique ne montre pas.

Le 2.9 doit inclure la **comparaison contre l'écran pygame archivé**, sur la même personne, dans la
même séance. C'est la raison pour laquelle on archive au lieu de supprimer.

## 11. Découpage indicatif

1. Déménager `cvep_decoder.py` + `cvep_code.py` dans `core/` ; **prouver que le modèle se charge**.
2. `core/modes/cvep.py` : le mode, la phase, les trois états muets, le refus sans modèle.
3. Le réglage `model` à deux décodeurs + `pyntbci` déclaré + les seuils rCCA posés.
4. `DecodedCVEPPublisher` + enregistrement au registre + la tuile console.
5. `research/cvep_stimulus.py` : l'émetteur + **le test de phase**.
6. La calibration entraîne les deux et affiche les deux chiffres.
7. Documentation (`markers.md`, SPEC §5 et §14, recette 1.16 et 2.9, README, CLAUDE.md).
8. La séance casque : 2.7, 2.8, 2.9.

## 12. Ce qui reste DEHORS

- **Les codes Gold distincts** — réfutés, et chers (stimulus en double).
- **Le dynamic stopping** — réfuté.
- **Le c-VEP rendu par une appli cliente** (l'ancienne piste F1 dans sa forme forte) : on livre un
  émetteur, pas un contrat de rendu pour Unity. Un client qui voudrait afficher lui-même devra tenir
  le verrouillage frame, et rien ne l'y aiderait aujourd'hui.
- **La calibration jouée par le moteur** — comme le P300 et l'ErrP, elle reste dans l'appli pygame :
  son stimulus doit être verrouillé à la frame.
- **Une seconde personne mesurée** — tous les chiffres du c-VEP viennent d'une personne.

## 13. Contraintes qui lient tout le chantier

- `src/core/` n'importe jamais `src/research/` ni `src/console/`, ni pygame ni Qt — vérifié par
  `server.py --smoke`.
- La console est un **CLIENT** du moteur : aucune logique qu'il ne possède déjà.
- Code et commentaires en **français** ; README, `docs/markers.md` et commits en **anglais**.
- Tout testable **sans casque**.
- **Aucun test n'écrit dans le vrai `data/`** — enregistrements EEG d'une personne identifiable sur
  un dépôt public.
- Un autotest **sort en 1** quand il échoue.
- ⚠️ **Un seul programme du projet à la fois** pendant les tests : les noms de flux sont un contrat
  public, donc identiques pour toutes les instances.
