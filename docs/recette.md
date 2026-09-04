# Recette — vérifier ce qui a été livré

Ce document existe pour une raison précise : le produit a été construit par chantiers successifs, et
**personne ne peut retenir de tête ce que chacun a ajouté**. Chaque test ci-dessous rappelle d'abord
ce qu'il vérifie et pourquoi ça a coûté du travail, puis donne la commande exacte et le résultat
attendu. Coche au fur et à mesure.

Les tests sont rangés **par coût croissant**. Tu peux t'arrêter à la fin de n'importe quel niveau :
chacun se suffit à lui-même.

| Niveau | Ce qu'il faut | Durée | Ce qu'il prouve |
|---|---|---|---|
| 0 | rien | 5 min | le code n'est pas cassé — **déjà passé le 2026-07-29** |
| 1 | un écran | ~45 min | la console marche pour un humain — **passé le 2026-08-17, sauf 1.14 à 1.16** |
| 2 | le casque | ~2 h | le décodage n'a pas régressé (dont 2.6 : la calibration MI, ~15 min ; et 2.9 : calibration c-VEP ~3 min + A 5 + B 5 + A' 5, montages compris) |
| 3 | une 2e machine | ~15 min | c'est bien une API, pas un programme |

⚠️ **Les quatre derniers tests du niveau 2 (2.6 à 2.9) n'ont JAMAIS été joués**, et ce sont eux qui
portent tout ce que le produit affirme sur les quatre modes à modèle. Une seule séance casque les
couvre — c'est le travail qui reste.

## Avant toute séance — trois pièges qui ont déjà coûté des heures

- [ ] **Un seul programme à la fois.** Le casque n'accepte qu'une connexion, et les noms de flux
  sont un contrat public, donc identiques pour toutes les instances. Un moteur oublié répond à la
  place de celui que tu testes. Vérifier d'abord :

  ```powershell
  Get-Process python
  ```

  Attendu : rien. Sinon, identifier avant de tuer — c'est peut-être ta propre console.

- [ ] **Saliner les électrodes.** C'est le principal levier de qualité du signal, gain mesuré très
  net. Et vérifier le contact **avant** d'enregistrer : une référence décollée produit une séance
  entière inexploitable.

- [ ] **Ne pas fermer/rouvrir l'application en cours de séance de CASQUE.** C3 et Cz saturent à la
  réouverture (redémarrage de l'amplificateur). Une seule session ouverte, du début à la fin. En
  synthétique (niveau 1) ce piège n'existe pas : on peut relancer autant qu'on veut.

---

## Niveau 0 — sans casque ni écran

**✅ Passé le 2026-07-29, les 8 verts.** Tu n'as pas besoin de le refaire, sauf après une modif du
code. Il est ici pour que tu saches ce qui est couvert automatiquement — et donc ce que les niveaux
suivants n'ont pas à revérifier.

Les commandes, une par une (jamais en parallèle : elles publient toutes sur les mêmes noms de flux) :

```bash
python src/core/config.py            # proposition de fréquences, choix des diviseurs
python src/core/modes/contract.py    # validation des réglages, messages de refus
python src/core/modes/registry.py    # catalogue des 7 modes, ce qui sort vers la console
python src/core/modes/ssvep.py       # les réglages du mode SSVEP
python src/core/modes/mi.py          # le mode MI : seuil, vote, appariement p_<classe> ↔ classe
python src/core/mi_models.py         # les modèles MI sur le disque : lesquels se chargent vraiment
python src/core/modes/calibration.py # la ligne du temps d'une calibration : chauffe, essais, entraînement, abandon
python src/core/modes/mi_calib.py    # calibration MI : accuracy HONNÊTE (CV par essai), jamais d'écrasement
python src/core/acquisition.py --synthetic   # acquisition seule + fenêtre MI NON filtrée
python src/core/lsl_io.py            # publication LSL, pont d'horloge, verdicts qualité
python src/core/modes/cvep.py        # le mode c-VEP : la PHASE, les 4 causes de -1, le vote
python src/core/cvep_models.py       # les modèles c-VEP : refus des hérités, quel décodeur, tri par date
python src/research/cvep_stimulus.py --smoke  # l'émetteur c-VEP : la phase lue dans les PIXELS
python src/core/server.py --smoke    # le moteur : frontière core/, cumul, repos partagé, flux
python src/console/app.py --smoke    # la console : grille, page de mode, formulaire (Qt offscreen)
python src/research/app.py --smoke   # l'appli pygame : menu + 5 modes + calibrations (~3 min)
```

⚠️ **Les trois lignes c-VEP ne sont pas décoratives non plus**, et la troisième moins que les
autres : `cvep_stimulus.py --smoke` est le **seul** test du dépôt qui compare, image par image, la
phase que le moteur reconstruirait à celle réellement affichée — lue dans les **pixels**, pas dans le
compteur de l'émetteur. C'est la panne caractéristique de ce mode, celle qui ne lève aucune
exception et ressemble à un étudiant qui fixe mal. La liste complète est dans `CLAUDE.md`.

Attendu : `VERDICT : OK` pour tous, **sauf `acquisition.py`** qui n'imprime pas de ligne de verdict
— pour celui-là, lire les `OK` ligne à ligne et le code de sortie (`$LASTEXITCODE` sous PowerShell,
qui doit valoir 0) — et `smoke OK : menu + SSVEP + c-VEP … câblés (headless)` pour le dernier.

⚠️ **Les cinq lignes MI ne sont pas décoratives.** Aucun des trois smokes ne les exécute, et le
**non-filtrage de la fenêtre MI** — l'invariant central du mode, un double filtrage décoderait du
bruit avec des probabilités à 0,99 — n'est vérifié que par `acquisition.py --synthetic`.

**Ce que le niveau 0 ne peut pas voir** : rien de ce qui s'affiche. Qt tourne en `offscreen`, et un
écran hors écran répond même à des questions absurdes — il annonce par exemple un rafraîchissement
de 60 Hz qu'il fabrique. D'où le niveau 1.

---

## Niveau 1 — la console à l'écran, sans casque

**✅ Passé le 2026-08-17, les 13 tests.** C'était le niveau le plus rentable des trois et il l'a
prouvé : jusque-là la console n'avait jamais été ouverte dans une fenêtre, donc tout était vérifié
mécaniquement sans avoir jamais été *vu*. Trois défauts en sont sortis, dont **aucun** ne pouvait
être attrapé par les autotests du niveau 0.

- **1.13 — le seul défaut fonctionnel.** Démarrer depuis une tuile de la grille un mode qui va être
  refusé est **silencieux** : le moteur produit bien son refus, la console l'écrit dans le terminal,
  et rien n'apparaît dans la fenêtre. Depuis le formulaire de réglages (test 1.8) le même refus
  s'affiche en rouge — c'est la grille qui n'a pas de destination visuelle.
- **1.3** — les 8 tracés du brut sont trop resserrés et se chevauchent.
- **1.10** — le texte d'aide gris est tronqué en bas, et trop verbeux pour un étudiant.

Les défauts d'affichage sont groupés et traités en dernier ; le refus invisible de 1.13 ne l'est pas.

⚠️ **Le test 1.14 est arrivé APRÈS ce passage** (chantier des marqueurs entrants, livré le même
jour) : il n'a jamais été joué à l'écran. C'est le seul du niveau 1 qui reste à faire.

Le board synthétique de BrainFlow remplace le casque : signal artificiel, aucun matériel.

**Deux choses à savoir avant de commencer, sinon tu vas chercher un bug qui n'existe pas :**

1. **La console sait démarrer/arrêter un mode depuis la grille** (bouton **Démarrer**/**Arrêter**
   par tuile) — ce n'était PAS le cas avant ce chantier, où il fallait la relancer avec `--mode`
   pour voir quoi que ce soit tourner. `--mode` au lancement reste un raccourci utile : il démarre
   plusieurs modes d'un coup, ce qu'on exploite au test 1.7 pour le repos partagé.
2. **« Appliquer » est refusé sur un mode arrêté** — « SSVEP n'est pas démarré ». Le bouton
   « Proposer », lui, répond même arrêté. D'où les **deux lancements** ci-dessous.

**Lancement A** — pour les tests 1.1 à 1.6 :

```bash
python src/console/app.py --synthetic
```

### 1.1 — Elle s'ouvre et elle est lisible

- [ ] La fenêtre s'ouvre, titre « EEG_API_Unicorn — console d'expérimentation », 1100×720.
- [ ] En haut, un **bandeau permanent** : liaison casque, fréquence d'échantillonnage, et σ par voie.
- [ ] En dessous, une **grille de 7 tuiles** sur deux rangées de 4 : **Brut, SSVEP, c-VEP, Neuro**
      puis **Motor Imagery, P300, ErrP**. *(L'ordre suit `registry.MODES`, et il se lit : la
      première rangée est ce qu'on peut lancer sans rien avoir appris du sujet, la seconde ce qui
      exige un modèle entraîné par personne. SSVEP et c-VEP sont côte à côte parce que ce sont les
      deux seuls modes où l'on fixe une cible qui clignote — c'est la paire que le test 2.9 compare.
      ⚠️ Le c-VEP est en première rangée pour cette comparaison, pas parce qu'il serait immédiat :
      lui aussi exige un modèle, et en plus une horloge.)*
- [ ] La tuile « Brut » est **en marche** (le brut démarre par défaut) ; les six autres affichent
      « arrêté ».

> Rien ne peut être lu ? Le bandeau et les tuiles sont dimensionnés pour 1100 px de large. Note la
> taille de police du système si c'est illisible : c'est un vrai défaut, pas un détail.

### 1.2 — Plus AUCUNE tuile grisée

⚠️ **Ce test a changé de sens le 2026-08-21, et il faut le lire avant de conclure à une
régression.** Il vérifiait autrefois que les trois tuiles grisées (c-VEP, P300, ErrP) disaient
*pourquoi* elles l'étaient. Elles ne le sont plus : les trois ont rejoint le moteur, le c-VEP en
dernier. **Le moteur publie les six modes.** Le module qui portait les entrées « appli pygame »
(`core/modes/external.py`) a été supprimé avec sa dernière entrée.

- [ ] **Aucune des 7 tuiles n'est grisée.** Chacune porte sa case « publié » et son bouton
      « Ouvrir ». Si tu en vois une grise, c'est une régression — et la console le tient du
      contrat, pas d'une liste écrite à la main (`spec["status"] != "moteur"`).
- [ ] Le bouton **Calibrer** n'apparaît que sur la page **Motor Imagery**. C'est voulu, et ce
      n'est pas un oubli : `Calib(kind="natif")` dans les `ModeSpec` du c-VEP, du P300 et de
      l'ErrP dit que leur protocole a besoin d'un stimulus verrouillé à la frame, que Qt ne sait
      pas rendre. On calibre ces trois-là dans l'appli pygame.

> **Sans modèle entraîné sur ce poste, c'est normal** : la tuile reste active, mais lancer le mode
> sera refusé avec « aucun choix disponible » et l'aide qui dit de calibrer. Ça vaut pour les
> **quatre** modes à modèle : MI, P300, ErrP et c-VEP. `data/` est gitignoré, donc un dépôt
> fraîchement cloné est toujours dans cet état.

### 1.3 — Le mode brut montre vraiment le signal

- [ ] Cliquer « Ouvrir » sur **Brut** → 8 tracés qui défilent, une étiquette par voie
      (Fz, C3, Cz, C4, Pz, PO7, Oz, PO8).
- [ ] « ← Modes » revient à la grille.

> 🐛 **2026-08-17** : les 8 tracés sont là et correctement étiquetés, mais **trop resserrés — ils se
> chevauchent**. Rangé dans le lot d'affichage.

### 1.4 — Le bandeau vit

- [ ] Les σ se mettent à jour (~1 Hz), une valeur par voie.
- [ ] ⚠️ Sur board synthétique, la corrélation inter-voies monte à ~0,80-0,83 : c'est **normal**
      (signal artificiel corrélé), le seuil d'alarme est à 0,90. **N'en tire aucune conclusion.**
      Sur casque réel, c'est 0,31-0,50.

### 1.5 — Couper la diffusion sans arrêter le mode

- [ ] Décocher « publié » sur la tuile Brut → le tracé continue de défiler, mais le flux
      n'est plus sur le réseau.
- [ ] Recocher → il repart.

> ⚠️ **Angle mort de ce test, découvert le 2026-08-17** : la moitié qui compte — « le flux n'est
> plus sur le réseau », puis « il repart » — **ne se voit pas depuis la fenêtre**. On peut cocher ce
> test en n'ayant regardé que le tracé, et laisser la case décochée sans s'en apercevoir (c'est
> arrivé, et le test 1.6 a échoué juste après pour cette raison). Vérifier des deux côtés :
>
> ```bash
> python -u examples/receiver.py --list
> ```
>
> Attendu : `EEG_API_Unicorn_raw` **absent** quand la case est décochée, **présent** quand elle
> est cochée. `_quality` et `_status` restent là dans les deux cas.

### 1.6 — « Brancher un client » : l'extrait marche vraiment

C'est ce qu'un étudiant va copier. S'il ne tourne pas, tout le reste ne sert à rien.

- [ ] Ouvrir Brut → bloc « Brancher un client » → il nomme le flux `EEG_API_Unicorn_raw` et
      liste les 8 voies.
- [ ] Cliquer « Copier », coller dans un fichier `essai.py`, et **le lancer dans un autre terminal**
      pendant que la console tourne :

  ```bash
  python essai.py
  ```

  Attendu : des valeurs qui défilent. Pas une exception, pas un blocage muet.

> ✅ **2026-08-17** : **2931 échantillons en 11,7 s = 250,1 Hz**, les 8 voies nommées. L'extrait
> tourne tel quel, sans retouche. Il appelle `open_stream()` avant le premier `pull`, ce qui est le
> détail qui faisait perdre la première seconde en silence dans les premières versions.

**Lancement B** — fermer la console, puis la rouvrir avec les modes démarrés. Le test 1.7 s'observe
**dès le lancement**, alors garde un œil sur la fenêtre tout de suite.

```bash
python src/console/app.py --synthetic --mode ssvep,neuro
```

### 1.7 — Le repos partagé

Deux modes lancés dans la même commande partagent une seule phase de repos. Facile à casser sans que
rien ne le signale : un mode dont le plancher n'a pas été mesuré ne lève aucune erreur, il ne détecte
simplement jamais rien.

- [ ] Chronomètre en main : **15 s de chauffe**, puis **25 s de repos** — le maximum des deux (le
      SSVEP en demande 8, le neuro 25), puis les deux modes décodent.
- [ ] **Une seule consigne** s'affiche, celle du mode au repos le plus long — le neuro :
      « Repos : regarde l'écran, immobile et détendu — on cale TON zéro du jour. »
- [ ] À la fin, **les deux** tuiles passent à « décode ». Si une seule le fait, c'est le défaut que
      ce test existe pour attraper.

### 1.8 — Le moteur REFUSE une fréquence impossible

**C'est le cœur du chantier 2.** Une fréquence qui ne divise pas le rafraîchissement de l'écran fait
sauter des cycles à l'affichage : le décodeur corrèle alors contre une sinusoïde que personne
n'affiche. Zéro détection, aucune erreur, rien à déboguer. Avant, c'était accepté en silence.

- [ ] Ouvrir **SSVEP** → bloc Réglages → champ « Fréquences des cibles ».
- [ ] Taper `15, 17` → **Appliquer**.
- [ ] Attendu : un refus **en rouge**, qui nomme le coupable et propose les deux voisins :

  > « Fréquences des cibles » : 17 Hz n'est pas un diviseur entier de 60 Hz — l'affichage sauterait
  > des cycles et le décodeur corrélerait contre une sinusoïde que personne n'affiche. Les plus
  > proches sont 15 et 20 Hz

### 1.9 — Le bouton « Proposer » répond, et l'alpha change la réponse

Le fait scientifique derrière ce réglage : le **pic alpha est propre à chaque personne** (moyenne de
population ≈ 9,6 Hz, plage 7-13 Hz). Une cible posée sur ton pic ne se distingue pas de ton propre
fond au repos. Le trio validé sur casque (15 · 20 · 8,571) est accordé à un pic à 10,5 Hz — celui du
développeur. **Le distribuer tel quel à une promotion poserait une cible sur le pic d'une bonne
partie des étudiants.**

- [ ] Champ « Pic alpha » laissé à sa valeur par défaut **9,6** (la moyenne de population).
- [ ] Cliquer **Proposer « freqs »**.
- [ ] Attendu : le champ des fréquences se remplit avec **12, 15, 20**. Aucun avertissement.
- [ ] Cliquer **Appliquer** → accepté. *(Ce que le moteur propose, il doit l'accepter — ça n'a pas
      toujours été vrai : la tolérance refusait la valeur que son propre message affichait.)*
- [ ] Maintenant mettre « Pic alpha » à **10,5**, cliquer **Proposer** à nouveau.
- [ ] Attendu : **8,571 · 15 · 20** — le trio validé casque, régénéré. C'est la meilleure preuve
      disponible que la règle n'est pas arbitraire.

### 1.10 — Un écran qui n'est pas à 60 Hz

Le blocage qui a été corrigé en fin de chantier : déclarer un écran 144 Hz était refusé (les
anciennes fréquences ne le divisent plus) **et** la proposition continuait de calculer sur 60 — sans
porte de sortie.

- [ ] Sous le champ « Rafraîchissement », lire l'aide grise : elle annonce le rafraîchissement de
      **cette** fenêtre, et précise que c'est celui de l'écran qui **affiche les cibles** qui compte.
      Vérifier qu'elle dit quelque chose de sensé sur ta machine.
- [ ] Mettre « Rafraîchissement » à **144**, cliquer **Proposer**.
- [ ] Attendu : **12 · 14,4 · 18**.
- [ ] Cliquer **Appliquer** → accepté, sans avoir eu à toucher aux fréquences d'abord.

> 🐛 **2026-08-17** : le contenu est juste — l'aide annonce bien le rafraîchissement réel de la
> fenêtre (60,0028 Hz sur le poste de dev) et renvoie vers l'écran des cibles. C'est le rendu qui
> pèche : **texte tronqué en bas**, et trop verbeux pour un étudiant. Lot d'affichage.

### 1.11 — Un avertissement n'est pas un refus

- [ ] Taper **4** fréquences dans le champ (n'importe lesquelles, par exemple `12, 15, 20, 30`),
      remettre « Rafraîchissement » à **60** et « Pic alpha » à **9,6**, puis **Proposer**.
- [ ] Attendu : le champ se remplit avec **5 · 12 · 20 · 30**, accompagné d'un message
      **orange** (pas rouge) : « hors de la plage confortable 8-20 Hz : 5, 30 — scintillement plus
      pénible, réponse plus bruitée ».
- [ ] Vérifier que ce message est **visuellement distinct** du refus rouge du test 1.8. Un succès
      peint en rouge se lit comme un échec.
- [ ] **Appliquer** → accepté.

### 1.12 — Un réglage qui ne change rien ne coûte rien

Le contrat déclare quels réglages le **décodeur** lit. Changer les fréquences invalide le plancher de
repos (il est mesuré **par fréquence**) et les étiquettes du flux : il faut donc tout refaire.
Changer le rafraîchissement ou le pic alpha ne sert qu'à proposer et à valider — refaire 23 secondes
de repos pour ça apprendrait surtout à ne plus toucher aux réglages.

Regarder le **terminal** derrière la fenêtre pendant ces deux manipulations :

- [ ] Appliquer de **nouvelles fréquences** → la tuile SSVEP repasse par chauffe puis repos (~23 s)
      avant de redécoder. C'est voulu.
- [ ] Appliquer un **rafraîchissement ou un alpha seuls**, sans toucher aux fréquences → aucun repos,
      et le terminal écrit : « (sans effet sur le décodage : ni repos refait, ni flux recréé) ».

### 1.13 — Démarrer / arrêter un mode depuis la grille

Toujours dans la fenêtre du **Lancement B** (SSVEP et Neuro tournent depuis le test 1.7) : c'est la
capacité que ce chantier a ajoutée à la console — avant, il fallait fermer et relancer avec `--mode`
pour changer l'ensemble des modes actifs.

- [ ] Revenir à la grille (« ← Modes ») → la tuile **Neuro** affiche « décode » et propose un
      bouton **Arrêter**.
- [ ] Cliquer **Arrêter** sur la tuile Neuro → elle repasse à « arrêté », et
      `EEG_API_Unicorn_decoded_neuro` disparaît du réseau (vérifiable avec
      `python -u examples/receiver.py --list` dans un second terminal — le premier fait tourner
      la console du Lancement B).
- [ ] Cliquer **Démarrer** sur la même tuile → elle repart, chauffe puis repos compris, **sans
      qu'il ait été nécessaire de fermer la console**.
- [ ] La tuile **Motor Imagery** porte le même bouton **Démarrer** ; elle n'est grisée nulle part
      (cf. 1.2). Sans modèle entraîné sur ce poste, cliquer dessus redonne le refus déjà vu en
      1.2 (« aucun choix disponible »), pas un bouton inactif.

> 🐛 **2026-08-17 — LE défaut du niveau 1, et le seul qui ne soit pas cosmétique.** Ce dernier point
> échoue : le clic est **silencieux**. Le moteur refuse correctement, avec le message complet —
> `refusé : « Modèle entraîné » : aucun choix disponible … bouton « Calibrer » sur cette page` —
> mais la console l'écrit **dans le terminal**, pas dans la fenêtre. Rien n'apparaît à l'écran.
>
> Signature relevée dans le journal : **cinq clics d'affilée**, cinq refus identiques. C'est ce que
> fait quelqu'un devant un bouton qui ne répond pas.
>
> Le refus lancé depuis le formulaire de réglages (test 1.8) s'affiche, lui, en rouge. C'est donc la
> **grille** qui n'a pas de destination visuelle pour un refus, pas le moteur qui se tait.

### 1.14 — Le P300 : le tuyau des marqueurs, sans casque

C'est le chantier du 2026-08-17, et c'est la première fois que le moteur **écoute** au lieu de
seulement publier. Le décodage sera du hasard en synthétique — ce n'est pas ce qu'on teste. Ce qu'on
vérifie, c'est que les marqueurs partent, arrivent, trouvent leur EEG, et qu'une décision sort.

**Deux terminaux**, et c'est le point : le stimulus **n'ouvre pas le casque**, donc les deux
programmes cohabitent — impossible avec l'appli pygame.

```bash
# terminal 1
python src/core/server.py --synthetic --mode p300
# terminal 2
python src/research/p300_stimulus.py --windowed
```

- [ ] Le moteur dit qu'il attend le flux de marqueurs, **puis** qu'il s'y connecte quand le
      stimulus démarre. S'il reste muet, c'est le défaut que ce test existe pour attraper.
- [ ] Les 6 cibles clignotent une par une, en ordre mélangé.
- [ ] À la fin de la manche, **une sélection sort** sur `decoded_p300` — vérifiable dans un
      troisième terminal avec `python -u examples/receiver.py --stream decoded_p300`.
- [ ] La cible désignée sera fausse cinq fois sur six : **c'est normal**, le board synthétique ne
      produit aucun P300. On teste le tuyau, pas le cerveau.

> ⚠️ Sans modèle P300 entraîné sur ce poste, le mode **refuse de démarrer** et dit d'aller calibrer
> dans l'appli pygame. C'est le comportement attendu sur un dépôt fraîchement cloné (`data/` est
> gitignoré), pas une panne.

### 1.15 — L'ErrP : le 5e mode, sans casque

> ⚠️ **Sans modèle ErrP entraîné sur ce poste, le mode refuse de démarrer** et dit d'aller calibrer
> (`python src/research/app.py`, menu → ErrP → Calibrer). C'est le comportement attendu sur un dépôt
> fraîchement cloné (`data/` est gitignoré), pas une panne. ⚠️ **Mais cette calibration-là exige le
> casque** : ~200 essais, il n'existe aucun moyen d'en fabriquer un sans. Si tu n'en as jamais fait,
> ce test du niveau 1 n'est jouable **qu'après le 2.8** — c'est la seule entorse à la règle « le
> niveau 1 ne demande pas de matériel », et elle est dans la nature du mode, pas dans son code.

Le décodage sera du hasard en synthétique — ce qu'on vérifie, c'est que le tuyau porte le second
paradigme sans qu'on ait rien redécouvert.

⚠️ **La console, pas le moteur nu.** Le **dernier** point ci-dessous, et les deux encadrés ⚠️,
demandent une page et un réglage qui n'existent que dans la console ; `server.py` est *headless*, il
n'a ni page ErrP ni option `tnr_target`. La console crée son propre moteur, donc **lancer les deux
publierait `decoded_errp` deux fois sous le même nom** — exactement le piège que CLAUDE.md interdit.

```bash
# terminal 1 — la console (le mode démarre déjà « publié » ; la case est sur la TUILE, pas sur la page)
python src/console/app.py --synthetic --mode errp
# terminal 2
python src/research/errp_stimulus.py --windowed
# terminal 3
python -u examples/receiver.py --stream decoded_errp
```

- [ ] Le moteur passe par **15 s de chauffe puis 8 s de repos** avant de décoder, et annonce le σ
      par voie qu'il a mesuré. C'est sa référence de rejet d'artefact — sans elle, pas de décodage.
- [ ] **L'émetteur**, lui, annonce qu'il attend : le moteur écoute, mais il **jette tout pendant sa
      chauffe et son repos (~23 s)** — et la piste reste **immobile** jusque-là. Le moteur ne dit
      donc **rien** sur des marqueurs jetés : ce silence est le succès, pas une panne.
- [ ] Pour voir l'autre moitié du garde-fou, relance l'émetteur avec `--no-wait` : il démarre tout de
      suite, et le moteur écrit alors « N feedback(s) reçus pendant la CHAUFFE/le REPOS : jetés ».
      C'est voulu : l'offset du casque dérive encore, ces époques ne valent rien.
- [ ] Un point avance sur une piste, se trompe délibérément **environ une fois sur quatre** (28 %,
      le chiffre est affiché à l'écran), et montre son résultat une seconde.
- [ ] À chaque résultat affiché, **un échantillon sort** sur `decoded_errp`, visible dans le
      terminal 3. Y compris quand le moteur ne peut pas juger : il publie alors `error = -1`,
      jamais `0`.
- [ ] Sur la page ErrP, le verdict s'affiche **avec le score et le point de fonctionnement**, pas
      comme une sentence. Et « pas de verdict » se distingue visuellement de « pas d'erreur ».

> ⚠️ **Le réglage « Bonnes commandes gardées » n'est pas décoratif.** Mets-le à 0,95 puis à 0,70 et
> regarde le seuil changer : c'est le compromis, et il est raide — garder 95 % des bonnes commandes
> ne laisse attraper qu'une erreur sur quatre.
>
> ⚠️ **Mais ce réglage recrée le flux.** Le moteur écrit lui-même « RECRÉÉ (réabonnez-vous) », et le
> mode **refait chauffe + repos, ~23 s**, avant de décoder à nouveau. Ton `receiver.py` du terminal 3
> est abonné à l'ancien flux : **il devient muet définitivement**. Relance-le après chaque changement
> et attends la fin du repos avant de compter quoi que ce soit — sinon tu mesureras un flux mort et
> tu concluras que baisser le réglage a cassé le détecteur, ce qui est l'inverse de la vérité.

### 1.16 — Le c-VEP : une HORLOGE dans le tuyau, sans casque

C'est le chantier du 2026-08-21, le **6e et dernier mode**. Même montage à trois terminaux que le
1.15, et pourtant ce test ne vérifie pas la même chose — parce que **ces marqueurs-là ne délimitent
aucune époque : ils tiennent une horloge**. Le P300 et l'ErrP demandent au moteur de découper autour
d'un instant ; le c-VEP décode en continu, comme le SSVEP, et ses marqueurs lui disent seulement
**où en est le code affiché**. Sans eux il ne décode rien du tout — pas « mal », *rien*.

> ⚠️ **Il faut un modèle c-VEP sur ce poste**, sinon le mode refuse de démarrer et dit d'aller
> calibrer (`python src/research/app.py`, menu → c-VEP → Calibrer). Contrairement à l'ErrP (1.15),
> cette calibration-là **se joue en synthétique** : `python src/research/app.py --synthetic`, page
> c-VEP → Calibrer, **~3 min** (la durée exacte est calculée et imprimée au lancement : ≈ 2,7 min
> aux réglages du dépôt). Le modèle obtenu est **chargeable et dépourvu de tout sens** — il n'a vu
> aucun cerveau. Il suffit pour ce test, qui vérifie le tuyau et pas le décodage. Elle écrit **deux**
> fichiers horodatés (`data/cvep_model_*.npz` pour l'eCCA, `data/cvep_rcca_model_*.npz` pour le
> rCCA) et n'écrase jamais rien.

**La console plutôt que le moteur nu**, comme au 1.15 : les deux seuils qu'on manipule au dernier
point n'existent que là, et les compteurs qui font tout l'intérêt de ce test s'y lisent d'un coup
d'œil. Jamais les deux à la fois — ils publieraient `decoded_cvep` deux fois sous le même nom.

```bash
# terminal 1 — la console
python src/console/app.py --synthetic --mode cvep
# terminal 2 — l'émetteur : n'ouvre PAS le casque, donc il cohabite
python src/research/cvep_stimulus.py --windowed
# terminal 3
python -u examples/receiver.py --stream decoded_cvep
```

- [ ] Le moteur annonce qu'il attend le flux de marqueurs, **puis** qu'il s'y connecte quand
      l'émetteur démarre.
- [ ] Il annonce aussi, en une ligne, **quel modèle, quel décodeur et sur quel flux il écoute
      l'horloge** — par exemple `[cvep] modèle « cvep_model_….npz » (eCCA, seuils 0.26/0.09) —
      horloge attendue sur « EEG_API_Unicorn_stim »`. C'est le réglage le plus facile à se tromper.
- [ ] Six disques clignotent, **un cercle vert** entoure la cible consignée, et elle change toutes
      les ~8,4 s. Le bandeau du haut dit en direct `moteur À L'ÉCOUTE` ou `PERSONNE n'écoute`.
- [ ] ⚠️ **Le clignotement démarre TOUT DE SUITE, pendant la chauffe de 15 s du moteur** — un
      bandeau vert le dit. C'est l'inverse de l'ErrP, qui fige son écran. Le c-VEP **encaisse** ses
      marqueurs de chauffe : une horloge n'a pas besoin d'être bonne pour être à l'heure. Si tu vois
      l'écran s'immobiliser, c'est une régression.
- [ ] L'émetteur imprime sa **graine** (`--seed N` rejoue la séance à l'identique) et, pour chaque
      consigne, **deux** horodatages : `t=` et « compter à partir de t=… (+2,7 s de transition) ».
      Le second est celui qui sert à dépouiller — voir le 2.9.
- [ ] Sur `decoded_cvep`, terminal 3 : **10 voies**, nommées
      `target_index`, `confidence`, `score_0`…`score_5`, puis `corr_min` et `margin`, à ~5 Hz.
- [ ] `target_index` vaut **-1** en permanence : **c'est le résultat attendu**, le board synthétique
      ne produit aucune réponse c-VEP. On teste le tuyau, pas le cerveau.
- [ ] **LE point de ce test.** Ouvrir la page c-VEP et regarder POURQUOI c'est -1 : c'est
      `sous_les_seuils` qui doit **dominer** (le décodage tourne, les corrélations sont trop
      faibles). Quelques `vote_non_conclu` ne sont pas une panne : sur le board synthétique une
      fenêtre peut franchir 0,26/0,09 par hasard et échouer ensuite au vote. Si c'est
      `sans_reference` qui monte, **l'horloge n'arrive pas** — l'émetteur publie sous un autre nom,
      ou il n'est pas lancé. Les deux ressemblent à « ça ne détecte pas » et appellent des gestes
      opposés ; c'est exactement ce que ces compteurs existent pour séparer. (Les quatre causes et
      les quatre gestes sont tabulés une seule fois, au **2.9** — ce sont les mêmes compteurs.)
- [ ] Fermer l'émetteur (ESC) sans arrêter le mode. Après ~3 s, `reference_perimee` se met à monter
      à la place : l'horloge s'est tue et le moteur cesse de décoder plutôt que de continuer en roue
      libre. Relancer l'émetteur → ça repart tout seul.
- [ ] Relancer l'émetteur avec **`--refresh 75`**. Attendu : le moteur **refuse tous les marqueurs**,
      le dit en nommant les deux rafraîchissements, et **`marqueurs_refuses` monte** (annoncé à 1,
      10, 100…). ⚠️ **C'est ce compteur-là, et lui seul, qui identifie ce cas.** ⚠️ **Le mode ne
      s'arrête pas pour autant** : il continue de tourner et de publier -1, sous
      **`reference_perimee`** — pas `sans_reference`. L'horloge valide du point précédent est
      encore en mémoire (un marqueur refusé ne l'efface pas) ; elle expire au bout de 3,15 s et
      c'est `reference_perimee` qui monte ensuite, indéfiniment. Ce serait `sans_reference`
      seulement si le mode venait d'être redémarré. Ne suis pas le geste que la table du 2.9
      associe à `reference_perimee` (« relance l'émetteur ») : ici il est déjà lancé, et c'est son
      `--refresh` qui est en cause. Le refus est délibéré — un moteur qui s'arrêterait emmènerait
      les autres modes avec lui. Ne guette pas un plantage : lis les premières lignes du terminal.
- [ ] Sur la page c-VEP, changer **« Corrélation minimale »** de 0,26 à 0,05 puis **Appliquer**.
      Attendu, et c'est la différence avec le réglage ErrP du 1.15 : le terminal écrit « sans effet
      sur le décodage : ni repos refait, ni flux recréé », **le flux n'est PAS recréé** et ton
      `receiver.py` du terminal 3 continue de recevoir sans rien relancer. Le seuil bas fait sortir
      des cibles au hasard : c'est normal, et c'est le but — on vérifie que le réglage mord.
- [ ] Toujours dans le terminal 3, les deux dernières voies **`corr_min` et `margin` ont suivi**
      (0,05 sur la première), alors que les métadonnées du flux, elles, portent encore 0,26. Les
      deux disent bien deux choses différentes : la métadonnée décrit le réglage **à l'ouverture**
      du flux, la voie celui **en vigueur pour cet échantillon**. C'est ce qui permet de dépouiller
      un enregistrement six mois plus tard sans sa description LSL. Remettre 0,26 avant de partir.

---

## Niveau 2 — au casque

⚠️ Casque salé, contact vérifié, une seule application ouverte, aucun `python` résiduel.

### 2.1 — Ton pic alpha (à faire en premier : tout le reste en dépend)

```bash
python src/research/alpha_check.py
```

Suivre les consignes yeux ouverts / yeux fermés. Test de référence = effet de Berger : l'alpha monte
franchement quand tu fermes les yeux.

- [ ] L'alpha monte à la fermeture des yeux sur PO7/Oz/PO8. **Si non, arrête tout** : électrodes ou
      référence mal placées, aucun autre test du niveau 2 ne voudra rien dire.
- [ ] Noter la fréquence du pic : ______ Hz.
- [ ] La saisir dans « Pic alpha » (console → SSVEP), cliquer **Proposer**, noter le jeu proposé :
      ______ . S'il diffère de 8,571/15/20, c'est attendu et c'est l'intérêt du réglage.

### 2.2 — Non-régression du SSVEP

Le seul point où une régression silencieuse coûterait vraiment cher. Référence mesurée le
2026-07-27 : **100 % de justesse quand le moteur émet (0 confusion sur 36 essais), mais il n'émet
que 44 % du temps**.

```bash
python src/research/ssvep_guided.py
```

- [ ] Justesse quand le moteur émet : ______ % (référence : 100 %).
- [ ] Taux d'émission : ______ % (référence : 44 %).
- [ ] Aucun avertissement « cible quasi INDÉTECTABLE » au démarrage. S'il apparaît, le plancher de
      repos est trop bruité : re-saliner, revérifier les mastoïdes, refaire la chauffe.

### 2.3 — Le cumul sous charge réelle

Deux décodeurs sur le même tampon est trivial en synthétique. Ce qui ne l'est pas : la charge CPU et
son effet sur la cadence d'acquisition.

**L'un APRÈS l'autre, jamais en même temps** — deux moteurs publient sous les mêmes noms de flux.

```bash
python src/core/server.py --mode ssvep --duration 120
python src/core/server.py --mode ssvep,neuro --duration 120
```

- [ ] Relever la ligne de fin (`échantillons publiés … Hz effectif`) des deux runs :
      un mode ______ Hz, deux modes ______ Hz.
- [ ] Attendu : les deux proches de 250 Hz. Un écart net signifie que la boucle n'absorbe pas deux
      décodeurs → il faudra espacer les `period_s`.

  Référence en synthétique, mesurée le 2026-07-29 avec un seul mode :
  `18741 échantillons publiés en 75.1 s (249.6 Hz effectif)`.

> ⚠️ **Un bruit de sortie à ne pas confondre avec une panne.** Après la ligne d'arrêt, BrainFlow
> peut afficher `ctypes.ArgumentError … Python is likely shutting down`, venant de son finaliseur
> `BoardShim.__del__` exécuté trop tard pendant l'extinction de l'interpréteur. Observé le
> 2026-07-29 avec un **code de sortie 0** et un arrêt propre. Ça n'invalide aucun relevé.

### 2.4 — Le repos partagé, vécu

Refaire le test 1.7, mais au casque et en le vivant : la consigne doit être tenable pendant 25 s
sans que tu te demandes ce que tu es censé faire.

- [ ] Une seule consigne, compréhensible sans explication extérieure.
- [ ] Les deux modes décodent à la fin.

### 2.5 — Le mode neuro, jamais validé au casque

⚠️ Le mode neuro **publie** depuis le 2026-07-27, mais **son contenu n'a jamais été vérifié sur
casque**. Il sort des indices, personne n'a confirmé qu'ils veulent dire quelque chose.

- [ ] Ouvrir sa page pendant qu'il tourne, et regarder les indices bouger dans un sens plausible
      (yeux fermés, calcul mental, relâchement). Ce n'est **pas** une validation — c'est un premier
      regard, à consigner tel quel.

### 2.6 — Motor Imagery : calibrer PUIS décoder, dans la MÊME console

C'est le chemin complet du chantier : une calibration écrit un modèle dans `data/`, la même
console le propose, le charge et publie `decoded_mi`. Chaque bout a été testé séparément ; les
trois ensemble, sur une tête, jamais.

Ce que ce chantier a changé : la calibration est maintenant **jouée par le moteur** et affichée
par la console elle-même, sur sa page Motor Imagery — plus de bascule entre deux programmes pour
cette étape, donc plus de risque de saturation C3/Cz à la réouverture rien que pour calibrer.

```bash
python src/console/app.py --mode mi
```

- [ ] Ouvrir **Motor Imagery** → bouton **Calibrer**. La page affiche la consigne en cours
      (GAUCHE / DROITE / REPOS), l'essai en cours et le temps restant — 5 à 7 min par défaut,
      fatigant : sujet frais.
- [ ] La calibration va au bout et annonce avoir écrit un modèle horodaté. Noter l'accuracy
      affichée : ______ %.
- [ ] **Ce qu'il faut attendre — à lire AVANT de regarder ce chiffre.** Il est désormais
      **honnête** (validation croisée groupée PAR ESSAI, jamais par fenêtre — l'ancien écran
      pygame affichait un chiffre gonflé de 10 à 16 points) et porte sur les **trois classes**
      (GAUCHE/DROITE/REPOS, hasard 33 %). **≈ 40 % est un résultat NORMAL**, pas un échec : c'est
      le chiffre de référence mesuré honnêtement sur la seule séance archivée du projet —
      **40,0 %, p = 0,082, PAS significatif**. Un « 40 % » lu à côté d'un hasard à 33 % donne
      naturellement envie de conclure que c'est mieux que le hasard ; ce n'est **pas** le cas avec
      cette mesure. Le Motor Imagery ne marche pas également bien chez tout le monde.
- [ ] Revenir sur la page **Motor Imagery** (rien à relancer, toujours la même console) → le
      champ « Modèle entraîné » propose le fichier qui vient d'être écrit, en tête de liste (le
      plus récent d'abord).
- [ ] Cliquer **Démarrer**. Après la chauffe de 15 s, la page affiche une barre par classe et un
      verdict qui alterne entre « vote non conclu » et « INTENTION … ». La règle affichée
      au-dessus des barres doit nommer le **vote** (« seuil 0,6 par fenêtre, puis 3 fenêtres
      d'accord sur les 5 dernières »), pas « la classe gagnante doit dépasser le seuil ».
- [ ] Imaginer 10 fois la main gauche, 10 fois la droite, en alternant. Compter les intentions
      justes : ______ / 20. Le repère honnête à deux classes est **63 %** (cf. README) — un
      résultat proche d'une erreur sur trois est donc CONFORME. Ne conclus rien d'un écart sur
      20 essais : c'est du bruit à cette taille d'échantillon.
- [ ] En parallèle, sur un autre terminal, vérifier que l'intention sort **vraiment** sur le
      réseau : `python -u examples/receiver.py --stream decoded_mi`. Attendu : `intent_index`,
      `confidence`, puis `p_GAUCHE`, `p_DROITE`, `p_REPOS`.
- [ ] ⚠️ `intent_index = -1` (« le vote n'a pas conclu ») et l'indice de REPOS (« la personne se
      repose ») ne veulent **pas** dire la même chose. Le flux donne les deux dans ses
      métadonnées (`no_decision_index`, `rest_index`) : vérifier qu'ils diffèrent.

**Au besoin seulement — l'ancien écran, en comparaison.** `archive/mi_calibrate.py` existe encore,
justement pour ça : comparer minutage, consignes et époques enregistrées si un doute apparaît un
jour sur la calibration du moteur. Ne PAS le lancer juste après ce test par curiosité : il écrit
sous les anciens noms FIXES (`data/mi_model.joblib`, `data/mi_calib_last.npz`), donc il
**écraserait** un enregistrement, sans toucher aux modèles horodatés que ce test vient de produire
— et il faut fermer la console avant de l'ouvrir (cf. `archive/README.md`).

### 2.7 — P300 : sélectionner une cible par la pensée, via le réseau

Le mode le plus exigeant du produit, et le seul où **ton application doit parler au moteur**. Il
demande un modèle entraîné : si tu n'en as pas sur ce poste, calibre d'abord dans l'appli pygame
(menu → P300 → Calibrer, ~4 min), puis **ferme-la** avant de lancer le moteur. La calibration
écrit un fichier **horodaté** (`data/p300_model_AAAAMMJJ_HHMMSS.joblib`) : elle n'écrase jamais la
précédente, et le moteur propose la plus récente par défaut.

```bash
# terminal 1
python src/core/server.py --mode p300
# terminal 2 — n'ouvre PAS le casque, d'où les deux terminaux
python src/research/p300_stimulus.py
# terminal 3
python -u examples/receiver.py --stream decoded_p300
```

- [ ] Au lancement, le terminal 2 dit **« le moteur écoute — on peut commencer »**. S'il dit
      « PERSONNE n'écoute », arrête tout : le moteur n'est pas là, ou le nom du flux diffère.
      L'écran garde cet indicateur en haut, en direct, pendant toute la séance.
- [ ] Entre deux manches, l'écran affiche **« choisis ta cible et fixe-la »** pendant 2,5 s, rien
      ne clignote. C'est **le seul moment** où déplacer le regard : le faire pendant les flashs met
      la transition dans les époques, et le moteur publie quand même une cible plausible.
- [ ] Choisis une cible **pendant cette pause**, fixe-la, et **compte ses flashs** en silence. Le
      comptage n'est pas indispensable (mesuré au chantier P300) mais il aide à tenir l'attention.
- [ ] À la fin de la manche, la cible sortie sur `decoded_p300` est **celle que tu fixais**.
- [ ] Recommence **six fois, en changeant de cible à chaque pause**. ⚠️ **Une erreur ou deux sur six
      est attendue** : l'AUC mesurée est de 0,71, pas de 1,0. Un sans-faute serait une bonne
      surprise, pas la norme — et deux erreurs ne veulent pas dire que quelque chose est cassé.
- [ ] Regarde le terminal du moteur pendant ce temps. Les compteurs s'annoncent tout seuls au
      franchissement de 1, 10, 100… : aucun `marqueurs_perdus`, aucun `marqueurs_futurs`, aucune
      `manche ABANDONNÉE`. S'ils montent, le problème est dans l'horloge ou le réseau, pas dans ta
      concentration. Les mêmes chiffres sont sur le flux `status` (`marqueurs.*`) si tu préfères
      les lire depuis un client.
- [ ] Si tu ouvres la console sur la page P300 (⚠️ **pas en même temps que le moteur en terminal
      1** — un seul programme à la fois), l'écran doit annoncer des **log-odds** et « AUCUN
      seuil », jamais « échelle z ». Six barres étiquetées `cible 0 … cible 5`, et la cible retenue
      avec le nombre de flashs sur lequel elle repose.

> ⚠️ **`--reps` et `--targets` ne sont pas libres.** Le moteur code 6 cibles en dur et applique
> `P300_REPS` comme plafond par cible : à `--reps 12`, il abandonnerait **toutes** les manches.
> L'émetteur refuse maintenant ces valeurs au lancement, en nommant la constante — si tu vois
> « REFUSÉ », c'est ça.

> ⚠️ **Ne conclus rien sur une seule manche.** Six essais, c'est déjà peu ; ce projet a pour règle
> de ne jamais conclure sur du bruit. Si tu veux un chiffre, il faut un protocole, pas une
> impression.

### 2.8 — ErrP : le moteur voit-il que la machine s'est trompée ?

⚠️ **Lis ceci avant de commencer, sinon tu vas mal interpréter ce que tu vois.**

Ce détecteur, au réglage par défaut, **attrape une erreur sur deux** et annule une bonne commande
sur sept. Ce n'est pas un défaut de réglage : c'est ce que vaut un ERP mono-essai sur ce matériel,
mesuré honnêtement (AUC 0,776, p = 0,0099 sur 100 permutations, 200 essais, une personne).

⚠️ **Et ces deux taux-là sont eux-mêmes optimistes.** L'AUC est honnête — elle vient de scores
hors-pli. Mais le **seuil** qui produit « une sur deux / une sur sept » a été choisi en regardant ces
mêmes scores, donc le TNR obtenu dépasse la cible *par construction* sur les 200 essais du 24
juillet, et sur eux seuls. En séance, attends-toi à annuler **plus** d'une bonne commande sur sept,
pas moins. Le moteur le dit lui-même dans le champ `measured_on` de son flux.

**Donc : ne conclus rien d'un essai, ni de dix.** Sur dix erreurs délibérées, en attraper cinq est
le résultat *attendu*. En attraper huit ou deux tient dans le bruit.

Il faut un modèle entraîné. Si tu n'en as pas sur ce poste, calibre d'abord dans l'appli pygame
(menu → ErrP → Calibrer, ~200 essais), puis **ferme-la** avant de lancer le moteur.

```bash
# terminal 1
python src/core/server.py --mode errp
# terminal 2
python src/research/errp_stimulus.py
# terminal 3
python -u examples/receiver.py --stream decoded_errp
```

- [ ] Regarde la piste et laisse-toi surprendre par les erreurs — **ne les anticipe pas**. L'ErrP
      est une réaction à une surprise ; si tu sais que la machine va se tromper, il n'y a plus rien
      à détecter.
- [ ] Compte tes erreurs délibérées et les `error = 1` publiés. **Vise l'ordre de grandeur, pas le
      score.**
- [ ] Regarde le taux de rejet d'artefact dans l'état du moteur. **S'il dépasse 50 %, le moteur le
      dit — une seule fois, et pas avant 10 époques jugées.** Ne guette donc pas un message
      récurrent : son silence ne veut pas dire que le taux est redescendu. Pour le suivre en continu,
      lis `taux_rejet` dans l'état du moteur (flux `status`, ou la console). Un taux haut veut dire
      que le contact s'est dégradé ou que tu bouges, pas que le décodeur est cassé.
- [ ] Change « Bonnes commandes gardées » de 0,85 à 0,70 et refais une série : tu devrais attraper
      plus d'erreurs, et annuler plus de bonnes commandes. C'est le compromis, en vrai.
      ⚠️ **Ce point demande la console** — `python src/console/app.py --mode errp` **à la place** du
      terminal 1, jamais les deux en même temps : `server.py` n'a pas ce réglage. Et changer le
      réglage **recrée le flux** (« RECRÉÉ (réabonnez-vous) ») puis **refait les 23 s de chauffe et de
      repos** : relance ton `receiver.py` et attends la fin du repos, sinon tu comptes sur un flux
      mort.

> ⚠️ **Un point ouvert que ce test peut trancher** : la référence de rejet d'artefact est mesurée
> sur du signal BRUT après 15 s de chauffe, et ce délai n'a jamais été vérifié pour cet usage
> précis — il est hérité du SSVEP. Si le taux de rejet est anormalement haut dès le début de séance
> et redescend ensuite, c'est que la chauffe est trop courte. **Note-le, c'est une mesure utile.**

### 2.9 — c-VEP : le moteur lit-il la phase d'un vrai cerveau ?

⚠️⚠️ **Lis les trois encadrés qui suivent AVANT de lancer quoi que ce soit.** Ce mode est le seul du
produit dont la panne caractéristique **ne casse rien** : une phase fausse de quelques frames ne
lève aucune exception, les corrélations baissent juste assez pour que la détection ne se déclenche
presque jamais, et à l'écran c'est **indiscernable de quelqu'un qui fixe mal**. Sans ces trois
lectures, un opérateur conclut à la panne en regardant le comportement attendu — ou à la réussite en
regardant une horloge décalée.

#### ⚠️ 1. Ce qu'est un résultat NORMAL

À **6 cibles, le hasard est à 16,7 %**. Jamais 50 %.

La seule mesure qui existe pour ce décodeur vient de la **séance de référence du 2026-07-21**,
dépouillée hors ligne : sur **37 décisions appariées** à la géométrie du moteur (k = 2 cycles),
**eCCA 59,5 %, rCCA 64,9 %** — soit **8 décisions discordantes** entre les deux, et **McNemar
p = 0,727**. Traduction : les deux décodeurs sont **indiscernables**, et l'écart de 5 points entre
les deux pourcentages est du bruit. Ne choisis pas ton décodeur là-dessus.

**Donc : environ UNE désignation sur TROIS est fausse, et c'est le comportement attendu.** Une cible
sur six mal désignée n'est pas une panne — c'est la moitié d'une erreur de moins que la référence.
Un sans-faute sur six essais serait une bonne surprise, pas la norme.

⚠️ **Et ce 60-65 % est un chiffre HORS LIGNE, mesuré en validation croisée sur les époques d'une
calibration.** Ce n'est pas une justesse en direct, encore moins à travers le réseau : **le c-VEP
n'a jamais été décodé au casque par le moteur**, c'est précisément ce que ce test fait pour la
première fois. Attends-toi à **moins**, pas à plus.

⚠️⚠️ **CE 59,5 / 64,9 % N'EST PAS LE CHIFFRE QUE TU VAS COMPTER, et confondre les deux fabrique un
verdict faux.** C'est l'`argmax` hors-pli sur **TOUTES** les décisions — **sans les deux seuils ni
le vote** que le moteur ajoute. Le moteur, lui, n'émet une cible qu'après `corr_min` **et**
`margin`, puis **2 des 3 dernières fenêtres** ; tout le reste devient un `-1`, que tu comptes à
part en « silences ». Le repère qui correspond à ce que tu vas relever existe, mesuré, dans
`core/config.py` :

| à k=2, seuils 0,26/0,09 (les défauts) | valeur |
|---|---|
| **taux d'ÉMISSION** (fenêtres où une cible sort) | **46 %** |
| **justesse PARMI LES VERDICTS ÉMIS** | **71 %** (donc 29 % de faux) |
| bruit qui franchit quand même les seuils | 10 % |

**C'est ce couple-là — ~46 % d'émission, ~71 % de justesse à l'émission — qu'il faut comparer à
ton relevé**, pas le 59,5/64,9. Avec le mauvais dénominateur, 70 % de justesse sur 45 % d'émission
(c'est-à-dire le comportement attendu) se lit « mieux que prévu », et 60 % sur 90 % d'émission se
lit « conforme » alors que ça signalerait des seuils qui ne mordent plus.

⚠️ **Le moteur va donc se taire plus d'une fois sur deux, et ce n'est pas une panne.** Le repère du
projet est le SSVEP : **100 % de justesse quand il émet, mais il n'émet que 44 % du temps**. Un
long silence entre deux verdicts justes est un régime normal ici.

**Ne conclus rien de six essais, ni de dix.** Si tu veux un chiffre, il faut un protocole — c'est
`--seed` et le dépouillement ci-dessous, pas une impression.

#### ⚠️ 2. La période à JETER après chaque changement de consigne

C'est le générateur de faux verdict de ce test, et il est purement arithmétique.

L'émetteur tient chaque consigne **8 cycles de code, soit 8,4 s** à 60 Hz. Mais le moteur a **deux
mémoires** en amont de chaque échantillon publié :

| | durée |
|---|---|
| la fenêtre de décision — 2 cycles de code repliés | 2,10 s |
| le vote glissant — 3 fenêtres espacées de 0,2 s | 0,60 s |
| **total : la TRANSITION** | **2,70 s** |

Pendant ces **2,70 s**, chaque échantillon publié est calculé sur du signal **à cheval sur DEUX
cibles**. Rien dans le flux ne le dit. Ça fait **32 % des échantillons de chaque consigne**, et les
compter tire mécaniquement la justesse mesurée vers le hasard.

> **Ce n'est pas une précaution théorique.** À l'ancien réglage (4 cycles, 4,2 s par consigne) la
> transition couvrait **64 %** de l'intervalle : quelqu'un qui notait tous les verdicts mesurait
> **~40 %** quel que soit le décodeur, et concluait que le c-VEP ne marche pas — en regardant une
> transition. La consigne a été rallongée à 8 cycles pour cette raison, et il en reste 32 % à jeter.

**Chaque ligne du terminal de l'émetteur imprime l'instant exact à partir duquel les échantillons
comptent** :

```text
[cvep-stim] t=12345.678  cycle 9 : fixe « AR-DROITE » (cible 2)  —  compter à partir de t=12348.378 (+2.7 s de transition)
```

- [ ] **Ne note QUE les `decoded_cvep` postérieurs à ce second horodatage.** C'est la seule règle de
      dépouillement de ce test, et l'ignorer suffit à fabriquer un échec.

⚠️ **Cette règle ne s'applique QUE si tu écris les deux côtés dans des fichiers.** Le dépouillement
se fait **après** la séance, sur un journal — jamais en direct, et jamais en comparant deux fenêtres
de terminal à l'œil (~1 500 lignes à 5 Hz pour 5 min, contre ~35 consignes). Les deux moitiés
existent, et elles portent le **même horodatage `local_clock()`**, ce qui rend la jointure purement
numérique :

| côté | quoi | comment |
|---|---|---|
| vérité-terrain | une ligne JSON par consigne, avec `t` et `compter_a_partir_de` | `cvep_stimulus.py --log seance_stim.jsonl` |
| verdicts | une ligne par échantillon, préfixée `t=…` | `python -u examples/receiver.py --stream decoded_cvep > seance_recv.txt` |

- [ ] **Lance l'émetteur avec `--log` et redirige le terminal 3 dans un fichier.** Sans ces deux
      fichiers, la séance n'est **pas dépouillable** : le scrollback est le seul autre exemplaire,
      le 2.9 demande plus bas de fermer les trois terminaux entre ses blocs, et une séance casque ne
      se répète pas.

#### ⚠️ 3. Il faut un modèle, et il est propre à TA personne

Le modèle de quelqu'un d'autre donne des corrélations plausibles et fausses — le pire des deux
mondes. Si tu n'en as pas :

```bash
python src/research/app.py     # menu → c-VEP → Calibrer, ~3 min, fixer chaque cible
```

La durée exacte est **calculée et imprimée au lancement** (`[cvep-cal] … ≈ 2.7 min`) : 6 cibles ×
15 cycles en 18 blocs entrelacés, hors briefing et hors contrôle de liaison. Budgète-la comme telle
— la « ~1 min » qui traînait dans cette recette datait d'un ancien réglage, et un facteur 3 sur un
préalable de séance se paie en fatigue et en électrodes qui sèchent.

Elle entraîne **eCCA ET rCCA sur les mêmes époques**, affiche les deux justesses et nomme le gagnant
par McNemar — « indiscernables » est la réponse attendue. Elle écrit **deux** fichiers horodatés
(`data/cvep_model_AAAAMMJJ-HHMMSS.npz` et `data/cvep_rcca_model_*.npz`) et n'écrase jamais rien.

- [ ] **Note le nom exact du fichier eCCA** : ______________________ . Tu en auras besoin pour la
      comparaison, qui n'a de sens que sur le **même modèle**.
- [ ] **Ferme l'appli pygame** avant de lancer le moteur. Elle ouvre le casque, et l'Unicorn
      n'accepte qu'une connexion.

#### La séance

⚠️ **Ne retire pas le casque, ne resaline pas, ne referme pas la session entre les deux moitiés de
ce test.** La comparaison du dernier point ne vaut que si les deux décodages voient le même montage
sur la même tête.

```bash
# terminal 1 — le moteur (15 s de chauffe, PAS de repos : le c-VEP ne mesure aucun plancher)
python src/core/server.py --mode cvep
# terminal 2 — l'émetteur : n'ouvre PAS le casque, d'où les deux terminaux.
#              --log est OBLIGATOIRE ici : c'est la vérité-terrain, et rien d'autre ne la porte.
python src/research/cvep_stimulus.py --log seance_A_stim.jsonl
# terminal 3 — redirigé dans un fichier, pour la même raison
python -u examples/receiver.py --stream decoded_cvep > seance_A_recv.txt
```

⚠️ Le terminal 3 **n'affiche donc plus rien** : c'est voulu, il écrit. Pour surveiller en direct,
regarde le terminal 1 (une ligne par seconde, verdict + corrélations) et le bandeau de l'émetteur.

- [ ] Le terminal 2 dit **« le moteur écoute. »**. S'il dit « PERSONNE n'écoute », arrête tout : le
      moteur n'est pas là, ou le nom du flux diffère. Le bandeau du haut de l'écran garde cet
      indicateur en direct pendant toute la séance.
- [ ] Il imprime aussi sa **graine** (`graine 1234567 — REJOUE cette séance à l'identique avec
      --seed 1234567`). **Note-la** : ______________ . Une séance casque ne se répète pas ; sans la
      graine, elle ne se dépouille pas deux fois.
- [ ] Le terminal 1 annonce en une ligne le **modèle, le décodeur, les seuils et le flux d'horloge**.
      Vérifie que c'est bien le modèle que tu viens de calibrer.
- [ ] Le clignotement **démarre tout de suite**, pendant la chauffe, avec un bandeau qui le dit.
      C'est voulu : le moteur encaisse l'horloge pendant ce temps. Fixe déjà la cible entourée.
- [ ] Fixe la cible entourée, **sans bouger les yeux**, et laisse tourner **~5 min** (c'est le
      bloc A ; note la durée réelle, tu la rejoueras à l'identique en A'). Le terminal 1 imprime une
      ligne par seconde : le verdict et les six corrélations à côté.
- [ ] ⚠️ **Quitte l'émetteur par ESC, jamais par Ctrl+C.** La ligne de cadence et le bilan ne
      s'impriment qu'à la sortie propre — et c'est le seul verdict de validité de la séance.
- [ ] **Lis la ligne de cadence** de l'émetteur : `cadence : … ms par cycle mesuré contre 1050,0 ms
      annoncés`. Si un avertissement apparaît (« l'écran ne tient PAS les 60 Hz publiés »), **la
      séance est à refaire** : le moteur a extrapolé la phase à la mauvaise vitesse et tout ce que
      tu viens de mesurer est faux, sans que rien d'autre ne l'ait signalé. Regarde aussi le compte
      de frames sautées — quelques-unes sont sans gravité, chacune est résorbée au marqueur suivant.
      (Le même bilan est aussi la dernière ligne de `seance_A_stim.jsonl`, `"kind":"bilan"`.)
- [ ] **Dépouille, après la séance, sur les deux fichiers.** Pour chaque ligne `"kind":"consigne"`
      de `seance_A_stim.jsonl`, prends les lignes de `seance_A_recv.txt` dont le `t=` est **≥ son
      `compter_a_partir_de`** et **< le `t` de la consigne suivante** ; compare leur `target_index`
      au champ `cible`. Trois colonnes : cible juste, cible fausse, `-1`.
      Justes : ______ · fausses : ______ · silences : ______ .
      ⚠️ Les deux `t` sont dans le **même domaine** (`local_clock()`) : c'est une comparaison de
      nombres, pas un rapprochement à l'œil. Si tu n'as qu'un seul des deux fichiers, ce point n'est
      pas faisable — reprends la séance avec `--log` et la redirection.
- [ ] **Compare au repère chiffré de l'encadré 1** : `émis / total` proche de **46 %**, et
      `justes / émis` proche de **71 %**. Ce sont ces deux ratios-là, pas le 59,5/64,9 %.
      Émission mesurée : ______ % · justesse à l'émission : ______ % .
      En dessous, va lire les compteurs avant de conclure.

> **La méthode de secours, à l'œil, quand il n'y a pas de journal** (c'est le cas du bloc B
> ci-dessous : l'écran archivé n'écrit rien). Le **terminal 1** imprime **une ligne par seconde**.
> Après chaque changement de consigne, **jette les 3 premières lignes** (2,70 s de transition) et
> compte les **~5 suivantes** : une consigne de 8,4 s en donne ~8, dont ~5 comptables. C'est
> grossier — les lignes ne sont pas horodatées et le comptage se fait au fil de l'eau — mais c'est
> exécutable sans rien d'autre, et ça donne les mêmes deux ratios. Ne mélange pas les deux méthodes
> dans un même relevé.

#### Quand ça ne détecte pas : LIS LA CAUSE, elle est comptée

⚠️ **`target_index = -1` a quatre causes, et elles appellent quatre gestes OPPOSÉS.** Le flux ne
porte que le `-1` ; les compteurs qui les séparent sont dans l'état du moteur (flux `status`, ou la
console), et le motif en clair est imprimé à côté de chaque ligne du terminal 1. Une séance casque
ne se répète pas : « ça ne détecte pas » sans la cause envoie chercher au mauvais endroit.

| Ce qui monte | Ce que ça veut dire | Ce qu'il faut faire |
|---|---|---|
| `sans_reference` | aucun marqueur d'horloge n'est jamais arrivé | relancer l'émetteur · vérifier le nom du flux |
| `reference_perimee` | l'horloge s'est tue (émetteur planté, fenêtre fermée) | relancer l'émetteur |
| `sous_les_seuils` | ça décode, les corrélations ne passent pas | **saliner**, vérifier le contact, fixer UNE cible |
| `vote_non_conclu` | elles passent, les fenêtres récentes ne s'accordent pas | tenir le regard immobile |

- [ ] Relever lequel domine : ____________________ . Ces quatre-là plus `decodages`
      **partitionnent** les fenêtres traitées — chacune en incrémente exactement un, donc la somme
      doit couvrir toute la séance. `marqueurs_refuses`, lui, compte des **marqueurs** : s'il monte,
      c'est l'émetteur qui est mal réglé, pas le cerveau.
- [ ] Regarder aussi `age_reference_s`, `corr_gagnant` et `corr_second` : ils disent en une ligne si
      l'horloge est vivante et à quelle hauteur les corrélations passent réellement.

> **Si `sous_les_seuils` domine avec des `corr_gagnant` proches de 0,26**, tu peux **descendre le
> seuil sans interrompre la séance** — c'est le seul réglage du produit qui le permette. Il faut la
> console à la place du terminal 1 (`python src/console/app.py --mode cvep`, **jamais les deux**),
> page c-VEP, champ « Corrélation minimale ». Le flux n'est **pas** recréé et la chauffe n'est
> **pas** refaite : ton `receiver.py` continue de recevoir, et les deux dernières voies
> (`corr_min`, `margin`) portent la nouvelle valeur dès l'échantillon suivant. **Note la valeur
> retenue dans ton relevé** — les métadonnées du flux, elles, garderont l'ancienne, puisqu'elles
> sont figées à l'ouverture.
>
> ⚠️⚠️ **Mais fais l'A-B-A du point suivant D'ABORD, aux seuils par DÉFAUT.** `archive/cvep_pilot.py`
> décode toujours à **0,26/0,09** et n'expose aucun réglage : une séance où A tourne à 0,15 et B à
> 0,26 compare deux **règles de décision**, pas deux **chemins de décodage** — exactement la
> confusion que l'A-B-A existe pour éliminer. Ne desserre le seuil qu'après, et note-le comme un
> **bloc séparé**, jamais comme une amélioration de A.

#### LA mesure de ce test : comparer à l'écran archivé, même personne, même séance

C'est **le seul point de 2.9 qui produise une conclusion**, et il coûte deux blocs de plus (~10 min
de casque). Tout le reste dit « ça marche » ou « ça ne marche pas » sans pouvoir dire *par rapport à
quoi*.

`archive/cvep_pilot.py` est l'écran pygame que ce chantier a retiré : **même modèle, mêmes cibles,
même vote 2-sur-3** — la géométrie de décision est identique (2 cycles repliés, 2 votes sur 3, à
5 Hz) —, mais il décode en local, dans le programme qui affiche. Deux chemins indépendants qui
doivent désigner la **même cible sur la même fixation**. Sans cette comparaison, un mauvais résultat
a deux explications qu'on ne peut pas séparer : *« le décodage réseau est moins bon »* et *« la
séance est moins bonne »* (contact qui s'est dégradé, fatigue, saline qui a séché).

⚠️⚠️ **Même modèle, mêmes cibles, même vote — mais PAS le même protocole, et c'est à toi de le
compenser.** A est **cerclé et à l'aveugle** : une consigne tirée au sort t'impose la cible, tu ne
vois jamais la réponse du décodeur. B est **libre et en boucle fermée** : l'écran archivé n'affiche
**aucune consigne**, ne tire rien, n'horodate rien, n'écrit aucun journal — et il montre la réponse
du décodeur **en direct**, dans un panneau de scores. Sans protocole écrit d'avance, B n'a **aucune
vérité-terrain** et son « ____ % » ne repose sur rien. D'où les trois règles ci-dessous, à lire
avant de lancer B.

**Fais-le en A-B-A**, dans cet ordre, sans retirer le casque, **et aux seuils par défaut
(0,26/0,09) pour les trois blocs** :

```bash
# A  — déjà fait ci-dessus : moteur + émetteur, ~5 min, avec --log, noter les deux ratios
# B  — fermer les trois terminaux, PUIS :
python archive/cvep_pilot.py --model data/cvep_model_AAAAMMJJ-HHMMSS.npz    # ~5 min
# A' — refermer, relancer EXACTEMENT le montage A (même durée, --log seance_Ap_stim.jsonl), ~5 min
```

- [ ] **`--model` explicite, obligatoire.** Le défaut de ce fichier archivé pointe sur l'ancien nom
      FIXE `data/cvep_model.npz`, que la calibration n'écrit plus. Sans cet argument tu comparerais
      deux modèles différents et l'écart mesuré ne voudrait rien dire.
- [ ] **Le protocole de B, à préparer AVANT de le lancer** (il n'en fournit aucun) :
      1. **Écris ta liste de fixations sur papier d'avance** — 6 cibles × 3 passages, dans un ordre
         mélangé, jamais deux fois la même de suite. C'est ta seule vérité-terrain pour B.
      2. **Fixe chaque cible 10 s**, et **ignore les 3 premières secondes** : la même transition
         qu'en A s'applique ici (2,10 s de fenêtre + 0,60 s de vote), pour la même raison.
      3. ⚠️ **Ne regarde le panneau de scores qu'à la FIN de chaque fixation**, et note ce qu'il
         affiche à cet instant. Le regarder pendant te dit la réponse et biaise ta fixation — c'est
         la différence de protocole avec A, et la seule que tu puisses réduire.
      Le comptage de B suit alors la **méthode de secours** décrite plus haut (jeter le début,
      compter la fin), avec les mêmes deux ratios qu'en A.
- [ ] A : ______ % émis / ______ % justes · B (écran archivé) : ______ % / ______ %
      · A' : ______ % / ______ % .
- [ ] **Comment lire ces trois nombres**, et c'est tout l'intérêt du A' :
      - A ≈ A' ≈ B → le décodage réseau vaut l'écran local. **C'est le résultat attendu.**
      - A ≈ A' **et** nettement < B → le décodage **réseau** est en cause. C'est un vrai défaut,
        à rapporter avec les compteurs de la section précédente.
      - A > A' → **la séance s'est dégradée** en cours de route. L'écart A-vs-B ne conclut rien :
        resaline et refais, ou note-le comme non concluant. Ne blâme pas le moteur.
- [ ] ⚠️ **Le seul biais connu de ce protocole** : passer de A à B ferme et rouvre la session
      BrainFlow, et l'amplificateur redémarre — le piège documenté qui fait **saturer C3/Cz**. Le
      c-VEP décode sur **Pz, PO7, Oz, PO8** (`CVEP_CHANNELS`), donc il devrait y échapper, mais ça
      n'a **jamais été mesuré**. C'est justement ce que le retour en A' contrôle. Note l'ordre réel
      dans lequel tu as joué les trois blocs.

> ⚠️ **Ne conclus rien sur une seule fixation, ni sur six.** À 6 cibles et ~60 % de justesse, six
> essais donnent un intervalle de confiance qui couvre à peu près tout ce qui est plausible. Ce
> projet a pour règle de ne jamais conclure sur du bruit ; la règle vaut aussi quand le résultat
> fait plaisir.

---

## Niveau 3 — le réseau

### 3.1 — Un client sur la même machine — ✅ passé le 2026-07-29

Refait ce jour en synthétique, résultat conservé ici comme référence.

```bash
python src/core/server.py --mode ssvep --synthetic     # terminal 1
python -u examples/receiver.py --list                  # terminal 2
python -u examples/receiver.py --stream decoded_ssvep  # terminal 2
```

- [ ] `--list` montre les flux : `_raw`, `_quality`, `_status`, `_decoded_ssvep`. ⚠️ **Attendre
      ~25 s** avant de lister : le flux décodé n'est créé qu'à la fin de la chauffe et du repos —
      ses métadonnées sont figées à la création, et les publier avant le plancher les rendrait
      fausses.
- [ ] `--stream decoded_ssvep` affiche des valeurs qui défilent. Attendu, tel qu'obtenu ce jour :

  ```text
  Connected: 6 channels  ['target_index', 'freq_hz', 'confidence',
                          'score_15Hz', 'score_20Hz', 'score_8.57143Hz']
  Clock offset: -0.014 ms
  [t=3303867.957   83.0 ms old] target_index=-1.00  freq_hz=0.00  confidence=1.23  score_15Hz=-0.61 …
  ```

  Le `t=` est l'horodatage LSL de l'échantillon, corrigé sur l'horloge de cette machine. C'est lui
  qui rend une séance dépouillable après coup : les émetteurs de stimulus horodatent leurs consignes
  sur la MÊME horloge, donc les deux fichiers se joignent dessus (cf. 2.9).

  `target_index=-1` signifie « aucune cible » : normal en synthétique, personne ne regarde rien.
  Les noms de voies **portent les fréquences réglées** — c'est pour ça que les changer recrée le
  flux.

### 3.2 — Depuis une deuxième machine

Validé le 2026-07-27 entre deux postes, sans aucune configuration. À refaire **sur le réseau de
l'école**, qui est un autre réseau : c'est le risque n°1 de la spec.

- [ ] Sur la machine B, ni dépôt ni casque : `pip install pylsl`, puis `receiver.py` copié à la main.
- [ ] La découverte trouve le flux et les **valeurs** arrivent. ⚠️ Découverte OK ≠ données OK : les
      ports diffèrent (UDP 16571 pour la découverte, TCP 16572-16604 pour les données).
- [ ] Si ça échoue : lire [docs/network.md](network.md) — ping d'abord, isolation client sur WiFi
      d'invités, `lsl_api.cfg` + `KnownPeers` si le multicast est bloqué.

### 3.3 — Unity

⚠️ Les deux scripts C# de [examples/unity/](../examples/unity/) sont écrits contre l'API vérifiée
mais **n'ont jamais été compilés** : il n'y a pas d'Unity sur ce poste.

- [ ] Projet Unity neuf + package LSL4Unity + les deux scripts → **ça compile**.
- [ ] `SsvepIntentReceiver` reçoit les intentions pendant que le moteur tourne.

---

## Ce que cette recette ne teste pas — et pourquoi

À lire avant de conclure que « tout marche ».

- **QUATRE des six modes n'ont jamais été décodés au casque À TRAVERS LE MOTEUR.** Le moteur publie
  maintenant les six — le c-VEP a fermé la marche le 2026-08-21 — mais publier n'est pas décoder un
  cerveau. Le pont modèle → moteur → flux est vérifié sans casque pour tous ; les deux bouts
  ensemble, sur une tête, restent à faire pour le **MI (2.6)**, le **P300 (2.7)**, l'**ErrP (2.8)**
  et le **c-VEP (2.9)**. Ces quatre tests sont l'essentiel de ce qui reste, et une seule séance les
  couvre.
- **La garde de 1,9 Hz autour de l'alpha repose sur une seule personne.** Elle est encadrée par les
  deux seules mesures du projet : 12 Hz à 1,50 Hz du pic échoue, 8,571 Hz à 1,93 Hz marche. n = 1.
  À réviser dès que plusieurs personnes auront été mesurées — c'est exactement le genre de chiffre
  qu'on croit acquis parce qu'il est écrit.
- **Tous les chiffres de ce projet viennent d'UNE personne.** SSVEP, MI, P300, ErrP, c-VEP : une
  tête, souvent une séance. Ce ne sont pas des moyennes, ce sont des points.
- **Le contenu du mode neuro n'a jamais été validé.** Cf. 2.5.
- **Aucune application CLIENTE n'affiche encore un stimulus.** Les trois émetteurs
  (`p300_stimulus.py`, `errp_stimulus.py`, `cvep_stimulus.py`) sont des références écrites ici, dans
  ce dépôt, en Python et en pygame. Qu'un moteur de jeu tienne la frame comme le c-VEP l'exige n'est
  vérifié nulle part — c'est le 3.3, et il n'a jamais été joué.
- **L'appli pygame n'est couverte que par son smoke.** Elle n'est plus le seul accès à aucun mode :
  il lui reste les **calibrations** que le moteur ne sait pas jouer (c-VEP, P300, ErrP),
  l'histogramme neuro, **et trois écrans de PILOTAGE que ce chantier n'a pas retirés — SSVEP,
  sélection P300, démonstrateur ErrP**. Ces trois-là font double emploi avec le moteur et ne
  doivent jamais tourner en même temps que lui ; seuls le c-VEP et le MI y ont perdu leur pilotage.
  Les tester au casque est une autre séance — celle-ci vérifie l'API, pas l'appli
  d'expérimentation.

---

Les résultats chiffrés (2.2, 2.3) méritent d'être recopiés dans
[docs/SPEC.md](SPEC.md) ou dans un commit : ce sont les seules références auxquelles la prochaine
séance pourra se comparer.
