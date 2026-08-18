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
| 1 | un écran | ~30 min | la console marche pour un humain — **déjà passé le 2026-08-17** |
| 2 | le casque | ~60 min | le décodage n'a pas régressé (dont 2.6 : la calibration MI, ~15 min) |
| 3 | une 2e machine | ~15 min | c'est bien une API, pas un programme |

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
python src/core/server.py --smoke    # le moteur : frontière core/, cumul, repos partagé, flux
python src/console/app.py --smoke    # la console : grille, page de mode, formulaire (Qt offscreen)
python src/research/app.py --smoke   # l'appli pygame : menu + 5 modes + calibrations (~3 min)
```

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
- [ ] En dessous, une **grille de 7 tuiles** dans cet ordre : Brut, SSVEP, Neuro, Motor
      Imagery, c-VEP, P300, ErrP.
- [ ] La tuile « Brut » est **en marche** (le brut démarre par défaut) ; SSVEP, Neuro et Motor
      Imagery affichent « arrêté ».

> Rien ne peut être lu ? Le bandeau et les tuiles sont dimensionnés pour 1100 px de large. Note la
> taille de police du système si c'est illisible : c'est un vrai défaut, pas un détail.

### 1.2 — Les 3 tuiles grisées disent *pourquoi*

C'est le point qui t'a fait croire que le produit était cassé. Une tuile grisée doit être grisée
**et lisible**, et donner sa raison, jamais rester muette.

- [ ] c-VEP, P300, ErrP sont grisées, marquées « appli pygame », **sans** case « publié » ni
      bouton « Ouvrir ».
- [ ] Chacune affiche sa raison propre, pas un texte générique. Attendu :
  - **c-VEP** — « Demande un stimulus verrouillé à la FRAME… »
  - **P300** — « Demande des MARQUEURS entrants (l'onset de chaque flash)… »
  - **ErrP** — « Demande un MARQUEUR entrant : l'instant exact où le feedback s'affiche. »
- [ ] **Motor Imagery n'est PLUS grisé** : il a rejoint le moteur. Sa tuile est active, avec sa
      case « publié » et son bouton « Ouvrir », comme SSVEP et Neuro. Si tu la vois grise, c'est
      une régression.

> **Sans modèle MI entraîné sur ce poste, c'est normal** : la tuile reste active, mais lancer le
> mode sera refusé avec « aucun choix disponible » et l'aide qui dit de calibrer. `data/` est
> gitignoré, donc un dépôt fraîchement cloné est toujours dans cet état. Le modèle s'obtient au
> niveau 2 (test 2.6).

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
  [83.0 ms old] target_index=-1.00  freq_hz=0.00  confidence=1.23  score_15Hz=-0.61 …
  ```

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

- **3 modes de décodage sur 6 ne sont pas sur le réseau.** c-VEP, P300 et ErrP sont décodés par
  l'appli pygame, pour elle-même, à l'écran. **Rien dans `src/research/` ne publie sur LSL** —
  aucun `StreamOutlet`. Aucun test ci-dessus ne peut donc les couvrir côté API. Les trois
  attendent des **marqueurs entrants** ou un stimulus verrouillé à la frame, que le moteur ne
  sait pas encore faire. Le Motor Imagery, lui, a fait le trajet le 2026-07-29 : le moteur charge
  un modèle entraîné et publie `decoded_mi` (test 2.6).
- **Le MI n'a jamais été décodé au casque À TRAVERS LE MOTEUR.** Le pont modèle → moteur → flux
  est vérifié sans casque (`server.py --smoke`), et le décodage lui-même l'a été dans l'appli
  pygame. Les deux bouts ensemble, sur une tête, restent à faire : c'est 2.6.
- **La garde de 1,9 Hz autour de l'alpha repose sur une seule personne.** Elle est encadrée par les
  deux seules mesures du projet : 12 Hz à 1,50 Hz du pic échoue, 8,571 Hz à 1,93 Hz marche. n = 1.
  À réviser dès que plusieurs personnes auront été mesurées — c'est exactement le genre de chiffre
  qu'on croit acquis parce qu'il est écrit.
- **Le contenu du mode neuro n'a jamais été validé.** Cf. 2.5.
- **Les marqueurs entrants n'existent pas.** Ils débloqueraient P300 et ErrP d'un coup.
- **L'appli pygame n'est couverte que par son smoke.** Les trois modes qu'elle seule sait faire se
  testent avec `python src/research/app.py`, mode par mode, au casque. C'est une autre séance —
  celle-ci vérifie l'API, pas l'appli d'expérimentation.

---

Les résultats chiffrés (2.2, 2.3) méritent d'être recopiés dans
[docs/SPEC.md](SPEC.md) ou dans un commit : ce sont les seules références auxquelles la prochaine
séance pourra se comparer.
