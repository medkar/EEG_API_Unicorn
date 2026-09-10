# QA — le tour complet, action par action

Feuille d'exécution. Chaque point donne **ce que tu fais**, **ce que tu dois voir** (✅) et **ce qui
compte pour un échec** (❌). Elle se coche telle quelle, dans l'ordre.

Le détail, l'histoire des défauts et les chiffres de référence vivent dans
[docs/recette.md](recette.md) ; chaque point d'ici renvoie à sa section là-bas quand il y en a une.
Cette feuille-ci est ce qu'on tient à la main ; la recette est ce qu'on relit quand un point tombe.

## Deux mots de vocabulaire, et ils ne sont pas interchangeables

- **❌ Régression** — ça a déjà marché ici. Si ça tombe, quelque chose s'est cassé, et le point est
  bloquant.
- **❌ Échec** — ça n'a **jamais** été vérifié. Si ça tombe, c'est peut-être une découverte, pas une
  casse : note ce que tu as vu, ne conclus pas, et continue. **Tout le bloc 2 sauf le SSVEP est
  dans ce cas** — quatre modes n'ont jamais décodé un cerveau à travers le moteur.

## Trois règles qui tiennent pendant toute la feuille

1. ⚠️ **Un seul programme du projet à la fois.** Les noms de flux LSL sont un contrat public, donc
   identiques pour toutes les instances : un moteur oublié répond à la place de celui qu'on teste.
   Les fenêtres de `src/stimulus/` sont l'exception — elles n'ouvrent pas le casque, et la console
   les lance elle-même.
2. ⚠️ **Ne jamais fermer/rouvrir la console en cours de séance.** C3 et Cz saturent à la
   réouverture (redémarrage de l'amplificateur). C'est exactement ce que le point d'entrée unique
   rend évitable : calibrer et décoder sans fermer la fenêtre qui tient le casque.
3. ⚠️ **Un utilisateur ne tape aucune commande.** Si un point du bloc 1 ou 2 t'oblige à ouvrir un
   terminal pour de l'usage réel (acquisition, décodage, flux sortant), **c'est le point qui a
   échoué**, pas toi. Les autotests du bloc 0 sont hors de cette règle : ils s'adressent au
   développeur.

---

# Bloc 0 — sans casque, sans écran (les autotests)

À passer avant de brancher quoi que ce soit. Environ 3 minutes en tout. **Aucun moteur ne doit
tourner pendant ces tests.**

### ☐ 0.1 — Les deux autotests principaux

```bash
python src/core/server.py --smoke
python src/console/app.py --smoke
```

✅ Les deux finissent par `VERDICT : OK` et sortent en **0** (`echo $?` / `echo %ERRORLEVEL%`).
✅ `[smoke-frontiere] … 0 violation(s) de frontière`, et la ligne annonce bien **quatre** paquets
scannés (`core`, `stimulus`, `research`, `console`).
✅ `[smoke-exemples] … 0 faute(s)`, avec un nombre de fichiers **non nul** et au moins 5 noms de
flux trouvés.

❌ Régression : un seul `ÉCHEC`, ou une sortie ≠ 0. Ne pas continuer : tout le reste de la feuille
suppose ce bloc vert.
❌ Régression **silencieuse à surveiller** : `0 fichier(s)` ou `0 nom(s) de flux` dans
`[smoke-exemples]`, ou `0 violation` avec un compte de fichiers qui a chuté. « Rien trouvé » n'est
pas « rien à trouver » — c'est la garde muette que ces compteurs existent pour rendre visible.

### ☐ 0.2 — Les quatre fenêtres de stimulus

```bash
python src/stimulus/ssvep.py --smoke
python src/stimulus/cvep.py --smoke
python src/stimulus/p300.py --smoke
python src/stimulus/errp.py --smoke
```

✅ Quatre `VERDICT : OK`, quatre sorties à 0. Aucune fenêtre ne s'ouvre (pilote SDL factice).

❌ Régression : n'importe lequel en rouge. `cvep.py --smoke` en particulier porte **le** test du
sous-système c-VEP (la phase relue dans les pixels, frame par frame) ; `ssvep.py --smoke` porte
depuis le 2026-09-10 le test d'**ordre** flip → marqueur.

### ☐ 0.3 — Les gardes de module que les deux gros autotests n'exécutent pas

La liste complète est dans [CLAUDE.md](../CLAUDE.md) (« Commandes utiles »). Le minimum avant une
séance, parce que ce sont les sous-systèmes que la séance va exercer :

```bash
python src/core/modes/mesure.py
python src/core/modes/alpha.py
python src/core/modes/ssvep_mesure.py
python src/core/modes/marker_calib.py
python src/core/modes/p300.py
python src/core/modes/cvep.py
python src/core/acquisition.py --synthetic
```

✅ Sept sorties à 0.

❌ Régression : n'importe lequel en rouge. `modes/p300.py` et `modes/cvep.py` sont ceux dont
l'échec compte le plus : leur panne caractéristique fait décoder du bruit **avec une confiance
élevée**, ce qui est indiscernable d'un succès à l'écran.

### ☐ 0.4 — Aucun test n'a touché `data/`

```bash
python -c "import sys;sys.path.insert(0,'src');from core.config import DATA_DIR,empreinte_dossier;e=empreinte_dossier(DATA_DIR);print(len(e),'fichiers')"
```

✅ Le même nombre de fichiers **avant et après** le bloc 0.

❌ Régression : le compte a bougé. ⚠️ **`git status --short data/` ne prouve RIEN** — le dossier est
gitignoré, il rend une sortie vide même après une écriture. `data/` porte des enregistrements EEG
d'une personne identifiable sur un dépôt public : un test n'y écrit jamais.

---

# Bloc 1 — la console à l'écran, sans casque

Board de test BrainFlow : signal artificiel, aucun matériel. **Un seul lancement pour tout le
bloc** — on ne ferme pas la fenêtre entre deux points.

Lancement : **double-clic sur `outils/Console EEG.bat`**. (Le `--synthetic` de la recette est un
raccourci de développeur qui saute l'écran de départ ; ici on veut justement voir cet écran.)

### ☐ 1.1 — L'écran de départ, et l'absence de repli

La console s'ouvre sur une question : sur quoi ouvrir la session ?

✅ Deux choix explicites : **« Casque Unicorn Hybrid Black »** et **« Board de test, SANS casque »**.
✅ Choisir le board de test → la grille s'ouvre, et **le bandeau du haut répète la source** tant que
la console tourne.

❌ Régression : la console ouvre directement la grille sans demander ; ou le bandeau ne dit pas la
source ; ou — le plus grave — un casque introuvable **bascule tout seul** sur le board de test.
Un repli silencieux fait enregistrer une séance entière de signal fabriqué en croyant tenir du vrai.

→ recette 1.17

### ☐ 1.2 — La grille : sept tuiles, puis une seconde rangée

✅ **Sept tuiles** : SSVEP · Neuro · Motor Imagery · P300 · ErrP · c-VEP · Brut.
✅ Une seconde rangée titrée **« Contrôles et mesures »**, avec **« Contrôle alpha »** (marquée
*BARRIÈRE*) et **« Taux d'émission SSVEP »**.
✅ Sur un dépôt sans modèle entraîné, les quatre modes à modèle (MI, P300, ErrP, c-VEP) sont
**grisés avec leur raison écrite**, pas simplement absents.

❌ Régression : une tuile manquante ; une tuile grisée **sans raison affichée** (un étudiant ne peut
pas deviner qu'il lui manque un modèle) ; la seconde rangée absente.

→ recette 1.2

### ☐ 1.3 — Le brut montre vraiment le signal, et les tracés ne se chevauchent pas

Tuile **Brut** → « Ouvrir ».

✅ Huit tracés qui défilent, une étiquette par voie (Fz, C3, Cz, C4, Pz, PO7, Oz, PO8).
✅ **Les huit tracés restent séparés** — aucun ne passe devant son voisin, quelle que soit
l'amplitude.
✅ La ligne grise sous le graphe annonce l'écart **en vigueur** (« un couloir = … µV ») et **ce
chiffre change** quand l'amplitude du signal change. Il n'est plus figé à 100 µV.
✅ « ← Modes » revient à la grille.

❌ Régression : les tracés se chevauchent (c'est le défaut 1.3, corrigé le 2026-09-10) ; ou l'écart
annoncé ne bouge jamais ; ou une voie hors échelle est rognée **sans que la ligne grise la nomme** —
une voie rognée est le signal qu'on vient chercher ici, pas un défaut à cacher.

→ recette 1.3

### ☐ 1.4 — Le bandeau vit

✅ Les σ se mettent à jour (~1 Hz), une valeur par voie.
✅ ⚠️ Sur board de test, la corrélation inter-voies monte à ~0,80-0,83 : c'est **normal** (signal
artificiel corrélé), le seuil d'alarme est à 0,90. **N'en tire aucune conclusion.** Sur casque réel
c'est 0,31-0,50.

❌ Régression : les σ restent figés, ou le bandeau alarme sur un montage sain.

→ recette 1.4

### ☐ 1.5 — La page d'un mode : rien n'est tronqué, l'aide est lisible

Grille → **c-VEP** (le cas extrême : six réglages). Puis **réduis la fenêtre en hauteur**, à la
taille d'un écran de portable.

✅ Trois blocs : « Sortie en direct », « Réglages », « Brancher un client ».
✅ **Le corps de la page défile.** Rien n'est coupé en bas : « Brancher un client » se rejoint en
faisant défiler.
✅ **L'en-tête ne défile pas** : « ← Modes » reste atteignable même en bas de page.
✅ L'aide grise sous chaque réglage tient en **une phrase**. Une case **« Aide détaillée »** est
présente ; la cocher affiche le texte complet, la décocher le replie.
✅ Survoler un champ ou son aide montre le texte complet en infobulle, sans rien cocher.

❌ Régression : le bas de la page est **inatteignable** (c'est le défaut 1.10, corrigé le
2026-09-10 — Qt écrase les blocs du bas, il ne les rend pas défilables) ; ou la case « Aide
détaillée » apparaît sur la page **Brut**, qui n'a aucun réglage — un bouton qui ne change rien à
l'écran est un réglage-décor.

### ☐ 1.6 — Un refus s'affiche À L'ÉCRAN, jamais seulement dans le terminal

Deux chemins à essayer, et **les deux** doivent parler :

1. Page **SSVEP** → champ « Fréquences des cibles » → taper `15, 17` → **Appliquer**.
2. Grille → tuile d'un mode qui va être refusé (ex. un mode à modèle sans modèle) → **Démarrer**.

✅ (1) Un refus **en rouge sur la page**, qui nomme le coupable et propose les voisins :
« 17 Hz n'est pas un diviseur entier de 60 Hz […] Les plus proches sont 15 et 20 Hz ».
✅ (1) La saisie fautive **reste dans le champ** (on la corrige, on ne la retape pas), et le refus
rappelle **ce qui reste en vigueur**.
✅ (2) Le refus apparaît **dans la fenêtre**, pas seulement dans la console cmd.

❌ Régression : (2) écran strictement immobile après le clic. C'est le défaut 1.13, et la grille est
désormais le **seul** chemin de démarrage — un refus muet y est un cul-de-sac.

→ recette 1.8, 1.13

### ☐ 1.7 — Le contrôle de liaison REFUSE, et ne se contourne pas

Page d'un mode à stimulus → **« Lancer le stimulus »** (ou **« Calibrer »**).

✅ Un écran intermédiaire montre **le σ de chacune des huit voies**, avec les **voies clés du mode
surlignées**, et un verdict par voie.
✅ Sur board de test, les huit passent (σ mesurés de 7 à 73 µV) et on continue.

❌ Régression : l'écran n'apparaît pas, ou il laisse passer une voie hors de **[0,5 ; 500] µV**.
⚠️ **Il n'y a AUCUNE porte de sortie, et c'est délibéré** — un contournement à un clic est un
contournement qu'on prend par réflexe. Si au casque une électrode refuse de descendre sous le
seuil, **c'est une décision à prendre devant le casque**, pas un bug à corriger dans l'urgence.

### ☐ 1.8 — Une calibration bout en bout, sans casque

Le P300 est le plus court (~2,2 min annoncées). Page **P300** → **« Calibrer »**.

✅ Un **briefing** s'affiche, puis les réglages, puis **« Commencer »**.
✅ La console **lance elle-même la fenêtre P300** : rien à taper dans un second terminal.
✅ L'ordre est le bon : le moteur démarre, **puis** la fenêtre s'ouvre. Ses premières manches ne
doivent pas tomber dans les 15 s de chauffe.
✅ À la fin : **un chiffre s'affiche**, avec **« Enregistrer le modèle »** et **« Refaire »**.
✅ **Cliquer « Refaire »** → rien n'a été écrit dans `data/`.
✅ Refaire, puis **« Enregistrer le modèle »** → le modèle apparaît dans la liste déroulante
« Modèle » de la page P300, horodaté.

❌ Régression : le chiffre s'affiche **après** que le modèle a été écrit (une calibration ratée
deviendrait le défaut en silence) ; ou « Refaire » laisse un fichier derrière lui ; ou le modèle
enregistré n'apparaît pas dans la liste sans redémarrer la console.
⚠️ **Vérifie `data/` par empreinte**, pas par `git status` — le dossier est gitignoré.

→ recette 1.14

### ☐ 1.9 — « Ce que voit ton application » : le flux sortant, vu comme un client

Bas de la grille → **« Ce que voit ton application »**. Démarrer le SSVEP d'abord.

✅ Les flux LSL **du réseau** apparaissent, avec leurs voies et des valeurs qui défilent.
✅ ⚠️ Le panneau lit **par LSL, comme un client** — pas l'état interne du moteur. Coupe la diffusion
du mode : le panneau doit **se taire**. S'il continue de défiler, il regarde le mauvais endroit, et
c'est exactement la panne qu'on vient regarder.
✅ **« Enregistrer les verdicts »** → un fichier apparaît dans `seances/`
(`moteur_<flux>_AAAAMMJJ-HHMMSS.jsonl`), **une ligne par décision publiée**, et l'écran dit **où et
combien**. Le même bouton l'arrête.
✅ ⚠️ `seances/` est **hors de `data/`** : un verdict de séance n'est ni un modèle ni un
enregistrement EEG.

❌ Régression : le panneau défile alors que le réseau est muet ; ou le chemin du fichier n'est pas
affiché (sans lui, la séance ne se dépouille pas).

→ recette 1.18

### ☐ 1.10 — Le journal de séance, coché par défaut

Page **c-VEP**.

✅ Une case **« Journal de séance »** est présente et **cochée**.
✅ Lancer le stimulus → l'écran dit **où** le fichier est écrit, dans `seances/`, avec un nom
horodaté choisi par la fenêtre.
✅ La case **n'apparaît pas** sur les pages P300 et ErrP : c'est le registre des stimulus qui
déclare quelle fenêtre sait journaliser, pas une liste tenue dans l'interface.

❌ Régression : la case est décochée par défaut. Une séance c-VEP sans ce fichier **ne se dépouille
pas** (recette 2.9) — décochée, c'est une séance perdue par omission, et une séance casque ne se
répète pas.

### ☐ 1.11 — La mort du moteur se dit à l'écran

Difficile à provoquer proprement sans casque ; le cas réel est un casque éteint ou non appairé.
À rejouer au bloc 2, à froid : **choisir « Casque Unicorn » avec le casque ÉTEINT**.

✅ La console **DIT à l'écran** que le moteur n'a pas démarré.
⚠️ **Elle ne repropose PAS le choix de la source** — c'est connu, écrit, et assumé. Reproposer
exigerait de sortir le cycle de vie du fil moteur de `run()` : c'est un chantier, pas un correctif.

❌ Régression : la fenêtre reste là, vide et muette, avec le traceback dans une console cmd que
personne ne regarde.

---

# Bloc 2 — au casque

⚠️ **Sauf le SSVEP, rien de ce bloc n'a jamais décodé un vrai cerveau à travers le moteur.** Les
autotests prouvent le câblage, jamais l'ergonomie ni le décodage. Un point qui tombe ici est
**❌ Échec**, pas régression : note ce que tu vois, ne conclus pas.

**Ordre arrêté, à ne pas rouvrir : Contact → SSVEP → c-VEP → P300 → ErrP.** Le SSVEP en référence
du jour : s'il échoue, c'est la séance qui est mauvaise, pas le mode. Le c-VEP tôt, sur sujet frais,
parce que sa panne caractéristique est un décodage *dégradé mais plausible*.

⚠️ **On réentraîne TOUT.** Aucun modèle déjà sur le disque n'est utilisé, même vérifié chargeable.

### ☐ 2.0 — Le montage (chaque point a déjà coûté une séance)

✅ **Saliner les électrodes** — c'est le levier de qualité le plus fort mesuré ici (+130 % d'ITR sur
le c-VEP).
✅ **Les mastoïdes sont posées** — oubliées au moins deux fois. Une référence décollée produit un
signal qui *ressemble* à du signal.
✅ Casque bien serré, câble dégagé, sujet assis et calé.

❌ Échec : une corrélation inter-voies à **+1,000** au bandeau = la référence flotte. Ne rien
enregistrer, reprendre le montage.

### ☐ 2.1 — Contrôle alpha — **BARRIÈRE** (à faire en PREMIER)

Grille → seconde rangée → **« Contrôle alpha »** → briefing → **« Commencer »**. ~37 s.
Déroulé : stabilisation, 8 s **yeux ouverts**, 8 s **yeux fermés**. Un **top sonore** annonce chaque
changement (la moitié de la mesure se passe les yeux fermés, où l'écran ne sert à rien).

✅ Un verdict s'affiche, avec le **ratio** et le **pic** mesurés.
✅ Ratio **> ~1,5** → l'alpha monte à la fermeture des yeux. La page propose d'**appliquer le pic
mesuré** au réglage « Pic alpha » du SSVEP : **accepte**, c'est le geste que la recette faisait
noter à la main puis retaper ailleurs.
✅ Si le son est coupé, la page **le dit** et prévient qu'on ne saura pas quand rouvrir les yeux.

❌ **ARRÊTE ICI** si le ratio ne monte pas. Ce n'est pas un test qu'on repasse plus tard : sans
alpha, **aucun autre test de la séance ne veut rien dire**. Reprendre le montage (saline,
mastoïdes, serrage), puis refaire ce point.
⚠️ Le repère « > ~1,5 » vient de **UNE personne, sur ce casque**. Un ratio à 1,4 n'est pas une
preuve d'échec — c'est une raison de reprendre le montage et de remesurer, pas de conclure.
⚠️ La seconde cause d'échec — « ça monte, mais ce n'est pas de l'alpha » (pic hors bande) — **n'a
jamais été vue sur un vrai signal**. Si elle sort, c'est une première : note tout.

→ recette 2.1

### ☐ 2.2 — SSVEP : non-régression, la référence du jour

Page **SSVEP** → vérifier que les fréquences en vigueur sont celles du dépôt (15 · 20 · 8,571) et
que « Pic alpha » porte **ton** pic (point 2.1) → **Démarrer**. Laisser passer la chauffe (15 s) et
le repos (8 s), puis fixer chaque flèche à tour de rôle.

✅ Le mode passe à « décode », et la sortie en direct montre une cible retenue quand tu fixes.
✅ Aucune cible n'est posée **sur ton pic alpha** — si le trio du dépôt tombe dessus, utilise le
bouton **« Proposer »** et applique ce que le moteur propose.

❌ Régression : rien ne se déclenche jamais, ou la cible retenue ne correspond pas à ce que tu
fixes. C'est le **seul** mode qui a déjà décodé un vrai cerveau à travers le moteur : s'il tombe,
suspecte la séance (contact, saline, fatigue) avant de suspecter le code.

→ recette 2.2

### ☐ 2.3 — Taux d'émission SSVEP : le chiffre comparable

Grille → seconde rangée → **« Taux d'émission SSVEP »** → briefing → **« Commencer »**. ~3,6 min.
Une fenêtre s'ouvre et **désigne** une cible par essai (entourée de bleu) ; fixe celle-là.
⚠️ **Ne ferme pas la fenêtre à la main** : sans son marqueur de fin, aucun verdict n'est calculé.

✅ Deux chiffres au verdict : **le taux d'émission** (à quelle fréquence le moteur annonce quelque
chose) et **la justesse à l'émission** (quand il annonce, est-ce la bonne).
✅ Le verdict dit aussi **combien d'essais ont été jetés** (époques hors tampon, artefacts) — le
taux porte sur l'effectif réellement retenu, et il le dit.
✅ Comparer aux repères du **2026-07-27** : **100 % de justesse à l'émission** (0 confusion sur 36)
et **44 % d'émission**.

❌ Échec : la justesse s'effondre (le moteur annonce souvent, et souvent faux) — c'est plus grave
qu'un taux d'émission bas, qui ne fait que ralentir.
⚠️ **Un essai = UNE décision.** Si un chiffre annonce un effectif ~7× plus grand que le nombre
d'essais joués, c'est que les fenêtres glissantes ont été comptées comme indépendantes : le
résultat est faux et l'intervalle de confiance l'est encore plus.
⚠️ Le σ du rejet d'artefact est pris sur les **8 voies** ici et sur les **4 occipitales filtrées**
dans le mode SSVEP. **C'est connu, dit, et laissé tel quel exprès** : aligner maintenant rendrait ce
chiffre incomparable au seul repère existant.

### ☐ 2.4 — c-VEP : calibrer puis décoder, sans fermer la console

Page **c-VEP** → **« Calibrer »** (~3,1 min annoncées, chauffe comprise) → « Commencer ».

✅ La fenêtre c-VEP s'ouvre **toute seule**, blocs entrelacés.
✅ À la fin : un chiffre de **justesse hors-pli** contre **son** hasard (1/6 ≈ 17 %, jamais 50 %),
et le test **McNemar** qui compare les deux décodeurs — pas l'écart des deux pourcentages, qui est
du bruit. Repères du dépôt : **59,5 / 64,9 %** sur la séance de référence.
✅ **« Enregistrer le modèle »**, puis **Démarrer** le mode c-VEP avec ce modèle, **case « Journal
de séance » cochée**, et **« Enregistrer les verdicts »** depuis la page de flux.
✅ Fixer chaque cible à tour de rôle, ~5 min.

❌ Échec : rien ne se déclenche jamais **et** aucune erreur n'apparaît. ⚠️ **C'est la panne
caractéristique du c-VEP** : une phase fausse de quelques frames ne lève aucune exception, les
corrélations baissent juste assez pour que rien ne se déclenche, et c'est **indiscernable d'un
étudiant qui fixe mal**. Deux causes possibles, à une ligne l'une de l'autre dans le code :
horodatage avant le flip, ou un `refresh` que l'écran ne tient pas.
❌ Échec de dépouillement : **pas de journal de séance** → la séance ne se dépouille pas, point. Le
terminal en est le seul autre exemplaire, et il n'est pas conservé.
⚠️ Le compteur `marqueurs_chauffe` est **trompeur** ici : la fenêtre clignote pendant la chauffe
(exprès — une horloge n'a pas besoin d'être bonne pour être à l'heure), le moteur compte ces ~14
marqueurs comme « époques jetées » et conseille à la fenêtre d'attendre. **Elle attend déjà.**
Message faux, sans danger.

→ recette 2.9

### ☐ 2.5 — P300 : sélectionner une cible par la pensée

Page **P300** → **« Calibrer »** (~2,2 min) → « Commencer » → 12 manches.

✅ Le chiffre s'affiche, **« Enregistrer le modèle »**, puis **Démarrer** le mode et **« Lancer le
stimulus »**.
✅ Fixer une cible : la sortie en direct doit la retenir, avec son score et son seuil **côte à
côte**.
✅ ⚠️ **Le comptage mental n'est PAS requis** (validé casque) — une bonne fixation suffit.

❌ Échec : la cible retenue est systématiquement décalée d'une position, ou la confiance est élevée
et la cible fausse. C'est la signature d'un décalage à l'épochage — et c'est justement la panne qui
rend tous les autres tests verts.

→ recette 2.7

### ☐ 2.6 — ErrP : le moteur voit-il que la machine s'est trompée ?

Page **ErrP** → **« Calibrer »** (~5,7 min, 200 essais) → « Commencer ».

✅ Le chiffre s'affiche ; **enregistrer**, puis **Démarrer** + **« Lancer le stimulus »**.
✅ La sortie en direct montre le score **et** le seuil, **et** le point de fonctionnement mesuré :
« garde X % des bonnes commandes / attrape Y % des erreurs ».
✅ Repère du dépôt : **AUC 0,776** (p = 0,0099).

❌ Échec : le détecteur annonce « erreur » sur presque tout, ou sur rien.
⚠️ **Un verdict « erreur » est une pièce biaisée, pas une certitude** : TPR 0,500 / TNR 0,855 — et
**ces deux taux sont eux-mêmes optimistes**, le seuil ayant été choisi sur les scores qui le
mesurent. Ne pas lire un verdict isolé comme une preuve.
⚠️ En décodage, le marqueur `feedback` est **nu** : pas de `error: true|false`. C'est une BCI
**passive** — lui donner la réponse rendrait faux tout ce qu'on mesure. Si l'étiquette apparaît en
décodage, **c'est un échec**, pas un confort.

→ recette 2.8

### ☐ 2.7 — Motor Imagery

Page **Motor Imagery** → **« Calibrer »** (5-7 min selon les essais/classe) → « Commencer ». Le
moteur mène : il tire les classes, affiche les consignes, décompte. Aucune fenêtre à ouvrir.

✅ Le chiffre annoncé est une **accuracy honnête** (validation croisée **par essai**), pas un
chiffre gonflé par la fuite entre fenêtres du même essai.
✅ Repères ré-mesurés honnêtement : **40,0 % à 3 classes** (p = 0,082, **PAS** significatif) et
**63,3 % en gauche/droite** (p = 0,038).

❌ Échec : un chiffre nettement au-dessus de ces repères doit **éveiller un soupçon**, pas
enthousiasmer — c'est exactement ce que la fuite entre fenêtres produisait (79 % non reproductible).
⚠️ En décodage, **`-1` veut dire « vote non conclu »**, jamais « repos ». Une application qui lit
`-1` comme un indice de classe est fausse.

→ recette 2.6

### ☐ 2.8 — Neuro : le mode dont le CONTENU n'a jamais été validé

Page **Neuro** → **Démarrer**. Repos de 25 s, puis les indices défilent.

✅ Les trois indices bougent, et le bandeau ne se contredit pas.

❌ Échec : les indices restent collés à zéro, ou dérivent sans jamais revenir.
⚠️ **Sa plomberie est testée, son contenu ne l'a jamais été — ni au casque, ni ailleurs.** Un indice
d'engagement qui « a l'air juste » n'est pas une validation. Ce point sert à vérifier qu'il
*fonctionne*, pas qu'il *dit vrai*.

→ recette 2.5

---

# Bloc 3 — le réseau, vu d'une application cliente

C'est le produit. Un mode doit tourner dans la console pendant tout ce bloc.

### ☐ 3.1 — Un client Python sur la même machine

Page du mode → bloc **« Brancher un client »** → **« Copier »** → coller dans un fichier et
l'exécuter. (Ou `python -u examples/receiver.py --stream decoded_ssvep`.)

✅ Le client trouve le flux **par son nom complet** (`EEG_API_Unicorn_decoded_…`) et affiche des
décisions.
✅ Le nom affiché sur la page est le nom **complet**, celui qu'un `resolve_byprop` demande — pas le
suffixe.
✅ Mode arrêté → la page dit **« mode ARRÊTÉ — ce flux n'est pas publié en ce moment »**.

❌ Régression : l'extrait copié ne marche pas tel quel ; ou il nomme un flux qui n'existe pas.
⚠️ Un flux décodé **existe dès le démarrage du mode** et reste **silencieux** pendant la chauffe et
le repos (~23 s pour le SSVEP). Ne pas relancer le moteur en croyant le flux absent.

→ recette 1.6, 3.1

### ☐ 3.2 — Depuis une deuxième machine

Même client, sur un autre PC du réseau.

✅ Le flux est trouvé, et `time_correction()` est **appliqué** — l'écart entre les deux horloges se
compte en **semaines** (`local_clock()` part du démarrage de chaque machine), pas en millisecondes.

❌ Échec : les horodatages reçus sont inutilisables pour joindre deux fichiers. Sans
`time_correction`, le dépouillement d'une séance à deux machines est faux, sans rien pour le dire.

→ recette 3.2

### ☐ 3.3 — Unity

`examples/unity/` : `SsvepIntentReceiver.cs` + `IntentToMotion.cs`, avec LSL4Unity.

✅ Les deux scripts **compilent**.
✅ La scène trouve le flux par son nom, et l'objet **s'arrête** quand le flux se tait (chien de
garde) au lieu de continuer sur une intention périmée.
✅ `-1` arrête l'objet — il ne le fait **pas** partir vers la cible 0.

❌ **Échec, et c'est le seul point de cette feuille dont on sait d'avance qu'il n'a jamais été
vérifié : les deux `.cs` n'ont JAMAIS été compilés.** Il n'y a pas d'Unity sur la machine de dev, et
aucun autotest ne peut le remplacer. Tout ce qui a été vérifié l'a été **par lecture**.
⚠️ `LSL.LSL.resolve_stream` n'est pas une faute de frappe : LSL4Unity déclare une classe statique
`LSL` dans un namespace lui aussi nommé `LSL`.

→ recette 3.3

---

## Ce que cette feuille ne teste pas, et il faut le savoir

- **L'ergonomie.** Aucun autotest ne dit si un étudiant comprend qu'un chiffre affiché n'est pas
  encore un modèle enregistré, ni si le contrôle de liaison est **lu** ou **cliqué au travers**.
  Ce sont trois questions qui n'ont de réponse qu'en séance, devant quelqu'un qui découvre l'outil.
- **L'écart de lancement fenêtre/moteur.** La console soumet la commande **puis** lance la fenêtre —
  l'ordre est figé par un test — et ce sont l'initialisation de pygame et l'attente de la fenêtre
  qui couvrent les 15 s de chauffe du moteur. **Ça tient, ce n'est pas garanti** : les deux
  processus comptent sur deux horloges différentes, et il n'existe **aucune poignée de main**. Si la
  fenêtre prend de l'avance, ses premières manches tombent dans la chauffe — jetées, comptées,
  dites, mais la séance est plus courte que ce que les deux écrans annoncent.
- **`--cycles` sur le c-VEP.** Une fenêtre lancée à la main avec `--cycles 6` sera deux fois plus
  courte que ce que la console annonce. Le moteur ne peut pas le savoir : ce n'est pas lui qui mène
  le protocole.
- **Les douze écrans archivés** (`archive/`) gardent chacun leur propre `--smoke` et ne sont couverts
  par aucun des autotests du bloc 0. `archive/cvep_pilot.py` reste utile en séance : il décode **en
  local**, ce qui sépare « le décodage réseau est moins bon » de « la séance est moins bonne ».
