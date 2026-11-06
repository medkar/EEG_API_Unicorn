# Construire l'installeur Windows

Ce dossier fabrique `EEG-API-Unicorn-Setup-<version>.exe`, un installeur qui pose le programme
sur un Windows 64 bits **sans Python installé**.

| Fichier | Rôle |
|---|---|
| `eeg_api_unicorn.spec` | la recette PyInstaller : sources Python → dossier `dist\EEG API Unicorn\` |
| `licences_tierces.py` | écrit `THIRD-PARTY-NOTICES.txt` dans ce dossier : la licence de tout ce qu'il embarque ; et `sortie\sources-lgpl.md`, l'adresse du code source des parties sous LGPL |
| `licences\` | les textes de licence que les paquets installés ne portent pas (voir « Les licences ») |
| `installeur.iss` | le script Inno Setup : ce dossier → l'installeur |
| `construire_installeur.ps1` | enchaîne tout, vérifie le résultat, affiche les tailles |

## Construire

Prérequis, une fois par poste :

- l'environnement du projet : `python -m venv .venv`, puis
  `.venv\Scripts\python.exe -m pip install -r requirements.txt -c build\contraintes.txt pyinstaller==6.22.3`
  (`contraintes.txt` fixe la version EXACTE de chaque bibliothèque : celles avec lesquelles le
  logiciel a été testé, et que le workflow de release installe aussi). Sans `.venv`, le
  script prend le `python` du PATH : c'est ce que fait le workflow de release
  (`.github/workflows/release.yml`), qui construit l'installeur de chaque version sur une machine
  de GitHub ;
- Inno Setup 6 : `winget install --id JRSoftware.InnoSetup -e`. Il peut s'installer pour tous
  (`Program Files (x86)\Inno Setup 6\`) ou pour l'utilisateur seul
  (`AppData\Local\Programs\Inno Setup 6\`) : le script le cherche aux deux endroits.

Puis, depuis la racine du dépôt :

```powershell
powershell -ExecutionPolicy Bypass -File build\construire_installeur.ps1
```

Le script :

1. vérifie que PyInstaller et Inno Setup sont là, et dit comment installer celui qui manque ;
2. lit la version dans `src\core\version.py` (le seul endroit où elle est écrite) ;
3. efface `dist\EEG API Unicorn\`, le brouillon de PyInstaller (`build\eeg_api_unicorn\`) et
   `build\sortie\` ;
4. lance PyInstaller ;
5. pose les avis de licence à côté des exécutables : copie `LICENSE`, puis lance
   `licences_tierces.py`, qui écrit `THIRD-PARTY-NOTICES.txt`. S'il manque la licence d'un
   composant, on s'arrête (voir « Les licences »). Puis `licences_tierces.py --sources-lgpl`
   écrit `build\sortie\sources-lgpl.md`, le bloc des sources LGPL pour les notes de la Release ;
6. lance `eeg-api-unicorn-cli.exe --verifier-modules` sur le programme construit : il importe les
   bibliothèques, vérifie que `brainflow\lib\` contient exactement les trois DLL voulues, fait
   servir chaque DLL (il ouvre le board de test de BrainFlow et lit son signal, applique un
   filtre, trouve la fonction du SDK du casque qui liste les casques, interroge LSL), puis
   entraîne, enregistre et relit un petit modèle de chaque sorte (MI, P300, ErrP, c-VEP eCCA et
   rCCA) dans un dossier temporaire. S'il échoue, on s'arrête : un module oublié par PyInstaller
   se voit ici, pas chez l'utilisateur ;
7. lance Inno Setup, qui écrit `build\sortie\EEG-API-Unicorn-Setup-<version>.exe`. Il refuse de
   compiler si l'un des deux avis de licence manque dans le dossier construit.

Compter environ 4 minutes en tout (mesuré : 248 s sur le poste de développement).

Aucun de ces dossiers produits n'est versionné (`.gitignore`).

## Ce qui est embarqué

- **Deux exécutables** (voir plus bas pourquoi) et le dossier `_internal\` qu'ils partagent :
  Python, les bibliothèques, les données.
- **Les textes affichés** : `src\core\langues\` → `_internal\core\langues\`.
- **L'icône** : `assets\logo\` → `_internal\assets\logo\`.
- **Trois DLL de BrainFlow** → `_internal\brainflow\lib\` : `BoardController.dll` (les sessions,
  avec le casque ou le board de test), `DataHandler.dll` (les filtres) et `Unicorn.dll` (le SDK du
  casque, publié par g.tec sous licence MIT). La liste est écrite à un seul endroit,
  `DLL_BRAINFLOW` dans `src\core\acquisition.py`, que la recette lit. Pourquoi ces trois-là, et
  pas les autres DLL du paquet BrainFlow :
  - leurs tables d'import (lues avec `pefile`) ne demandent que des DLL de Windows ;
  - `BoardController.dll` charge `Unicorn.dll` par son nom au moment d'ouvrir un Unicorn ; les
    autres noms de DLL qu'il contient sont ceux des casques d'autres fabricants ;
  - côté Python, BrainFlow ne charge une DLL qu'au premier appel qui en a besoin
    (`BoardControllerDLL`, `DataHandlerDLL`, `MLModuleDLL`) : le produit n'appelle jamais son module
    d'apprentissage (`MLModule.dll`, qui tire `onnxruntime_x64.dll`) ;
  - les autres sont les SDK de casques que le produit n'ouvre jamais (BrainBit, Muse, Ganglion,
    Synchroni, gForce, NeuroSDK, ANT Neuro) et la pile Bluetooth basse consommation de BrainFlow
    (`BrainFlowBluetooth.dll`, `simpleble-c.dll`), dont l'Unicorn ne se sert pas. Les embarquer
    obligerait à distribuer leurs licences, et celle d'ANT Neuro (`eego-SDK.dll`) impose en plus
    une clause de publicité.

  Vérifié : un paquet BrainFlow réduit à ces trois DLL ouvre le board de test, filtre, et charge
  `Unicorn.dll` à l'ouverture d'un casque (« device not found » sans casque, la réponse attendue).
  Pas encore essayé avec un vrai casque.
- **Les avis de licence**, à côté des exécutables : `LICENSE`, `THIRD-PARTY-NOTICES.txt`.
- **La DLL de LSL** (`lsl.dll`) → `_internal\pylsl\lib\`.
- **Tous les sous-modules** du produit (`core`, `console`, `stimulus`) et des bibliothèques de
  décodage (scikit-learn, pyriemann, pyntbci, et `array_api_compat` / `array_api_extra` dont
  pyriemann se sert) : un modèle enregistré désigne ses classes par leur nom, et PyInstaller ne
  peut pas deviner lesquelles il faudra pour le relire.
- matplotlib, parce que pyntbci l'importe (sans lui, pas de décodeur rCCA).

Ne sont **pas** embarqués : les tests des bibliothèques, tkinter, pytest, les autres DLL de
BrainFlow, ni aucun dossier du dépôt hors de `src\core`, `src\console`, `src\stimulus` et
`assets\logo` (l'icône). Ni aucune DLL que PyInstaller trouverait ailleurs que dans
l'environnement Python et le dépôt : il cherche aussi dans le `PATH` de la machine qui construit,
et le crochet de Qt y trouvait l'OpenSSL de Git for Windows (`libssl-3-x64.dll`,
`libcrypto-3-x64.dll`), dont Qt ne se servirait que pour une connexion HTTPS. La recette les écarte
et l'écrit dans le journal de PyInstaller (« écartée (hors de l'environnement Python) »).

### Tailles mesurées (version 1.0.0)

| | Taille |
|---|---|
| dossier `dist\EEG API Unicorn\` (= le programme installé) | 337 Mo |
| dont Qt (PySide6) | 125 Mo |
| dont scipy (avec ses DLL) | 70 Mo |
| dont numpy (avec ses DLL) | 26 Mo |
| dont matplotlib et ce qu'il tire (PIL, fontTools…) | 25 Mo |
| dont BrainFlow (ses trois DLL) | 3 Mo |
| dont scikit-learn | 13 Mo |
| dont les avis de licence (`THIRD-PARTY-NOTICES.txt`) | 1 Mo |
| chaque exécutable | 20 Mo (il contient le code Python compilé) |
| **installeur** `EEG-API-Unicorn-Setup-1.0.0.exe` | **92 Mo** |

Rien n'a été retiré pour gagner de la place : 92 Mo se téléchargent sans peine, et chaque
bibliothèque retirée serait un risque de module manquant au moment de relire un modèle.

## Les licences

Le programme est sous **licence MIT** (`LICENSE`, « Copyright (c) 2026 medkar »), comme tout le
dépôt : les clients, les exemples, les outils. Aucune bibliothèque embarquée n'impose sa licence
au programme : elles sont sous MIT, BSD ou LGPL, et les rares morceaux sous GPL ont une exception
ou restent des fichiers à part (la bibliothèque d'exécution de GCC dans NumPy et SciPy, la police
de pygame). La bibliothèque du casque de g.tec (`Unicorn.dll`, sous MIT, sans sources publiées)
ne demande que son avis.

`THIRD-PARTY-NOTICES.txt` (en anglais) est **écrit à chaque construction** par
`licences_tierces.py`, avec le Python qui vient de construire. Il contient :

1. **les paquets Python** : ceux de `contraintes.txt`, moins les outils de construction
   (PyInstaller, pyinstaller-hooks-contrib, altgraph, pefile, pywin32-ctypes). Pour chacun : nom,
   version, licence, et le texte COMPLET de chaque fichier de licence que ses métadonnées
   installées déclarent ou rangent (`*.dist-info`). Quatre paquets n'en portent pas, ou pas le
   bon : array-api-compat, pylsl, pygame, et PySide6/Shiboken6 (seulement le renvoi à la licence
   commerciale de Qt). Leur texte est gardé dans `licences\` (`COMPLEMENTS` du script) ;
2. **les autres composants** : Python lui-même (le `LICENSE.txt` de son installation), la
   bibliothèque du casque de g.tec (`licences\unicorn-c-api.txt`), liblsl (`lsl.dll`, dans pylsl),
   les bibliothèques que pygame transporte (SDL 2, SDL_image, SDL_mixer, SDL_ttf, FreeType,
   libpng, libjpeg, libtiff, libwebp, zlib, Ogg, Opus, PortMidi… : `licences\pygame.txt`), Qt et
   le code tiers de chacun de ses modules embarqués, FFmpeg compris (`licences\qt.txt`), et
   l'environnement d'exécution de Microsoft ;
3. **les textes partagés** (LGPL 2.1 et 3, GPL 3), écrits une seule fois. La GPL 3 y est parce
   que la LGPL 3 de Qt et de PySide6 la complète et demande les deux textes, et pour la police
   FreeSans que pygame embarque.

**Les sources des parties sous LGPL** : Qt, PySide6/Shiboken6, FFmpeg (dans Qt Multimedia) et
pygame. La LGPL demande d'offrir leur code source ; sa version 3 admet qu'il soit sur le serveur
d'un tiers si des indications claires accompagnent le programme (la 2.1 demandait de l'offrir au
même endroit que lui : pygame et FFmpeg, sous « 2.1 ou ultérieure », sont donc distribués sous la
version 3, et les avis le disent). La table `SOURCES_LGPL` du script
donne, pour chacun, la version et l'adresse de son code source officiel (pour FFmpeg, l'archive
de ffmpeg.org que Qt construit, et le script de Qt qui la construit). Ces adresses sont écrites
dans `THIRD-PARTY-NOTICES.txt`, à côté de chaque composant, et `--sources-lgpl` en fait un bloc
Markdown (`build\sortie\sources-lgpl.md`) que le workflow de release recopie dans les notes de
chaque Release, à côté de l'installeur.

Le script **refuse** (et la construction s'arrête), en nommant le coupable :

- un paquet embarqué sans aucun texte de licence ;
- un paquet installé absent de `contraintes.txt`, ou à une autre version ;
- un texte de `licences\` relevé pour une autre version du paquet que celle installée ;
- une DLL ou un module natif du programme construit qui ne vient d'aucun paquet installé ni de
  Python ;
- une DLL de Qt que sa table `DLL_QT` ne connaît pas, ou une section de la page de Qt que
  `licences\qt.txt` ne recopie pas ;
- un composant sous LGPL (lu dans les métadonnées des paquets, les textes LGPL de ses tables et
  `licences\qt.txt`) que `SOURCES_LGPL` ne couvre pas, ou dont la version embarquée (le paquet
  installé, ou la « ProductVersion » de la DLL, lue avec `pefile`) n'est pas celle des adresses
  relevées.

Ainsi une nouvelle dépendance ne part jamais sans sa licence. Après une mise à jour :

- **d'un paquet** : refaire `contraintes.txt` ; si le script refuse un texte de `licences\`,
  relire la licence de la nouvelle version, mettre le fichier à jour, puis la version notée dans
  `COMPLEMENTS` ou `AUTRES` ;
- **de PySide6** : `python build\licences_tierces.py --rafraichir-qt` relève sur doc.qt.io le
  code tiers des modules embarqués et réécrit `licences\qt.txt` (le seul geste qui demande le
  réseau ; la construction, elle, ne lit que le fichier du dépôt) ;
- **de PySide6 ou de pygame** (ou du FFmpeg de Qt) : trouver le code source de la nouvelle
  version, ouvrir ses adresses une fois, puis mettre à jour `SOURCES_LGPL`.

`python build\licences_tierces.py --autotest` vérifie chacun de ces refus sur des paquets
fabriqués.

## Deux exécutables : la mesure

Une fois installé, il n'y a plus d'interpréteur Python : pour ouvrir une fenêtre de stimulus, la
console relance le programme lui-même avec `--fenetre <clé>`, et lit ce que la fenêtre écrit pour
dire pourquoi elle s'est fermée. La question était : un programme « fenêtré » (sans terminal)
écrit-il quelque chose que la console peut lire ?

Mesuré sur ce poste (Windows 11, PyInstaller 6.22, PySide6 6.12) :

| Essai | Programme fenêtré | Programme en mode console |
|---|---|---|
| sortie lue par un `QProcess` (canaux fusionnés, comme la console), parent sans terminal | oui : `--version`, `--fenetre ssvep --help` (3 215 octets), code de sortie juste (0, 2) | oui |
| sortie lue par `subprocess` avec des tubes | oui, sortie et erreurs | oui |
| exception non rattrapée | l'erreur arrive sur la sortie d'erreur, **puis une boîte « Unhandled exception in script » garde le processus en vie** jusqu'à un clic (toujours vivant après 8 s ; même avec `disable_windowed_traceback`) | l'erreur arrive, le processus s'arrête aussitôt (code 1, 0,3 s) |
| lancé dans un terminal | n'écrit rien dans le terminal, qui rend la main tout de suite | écrit dans le terminal, comme `python script.py` |
| fenêtre de terminal ouverte quand la console le lance | sans objet | **aucune** : un programme en mode console lancé par un `QProcess` depuis un parent sans terminal n'a pas de fenêtre de terminal (il le constate lui-même : `GetConsoleWindow() = 0`, mesuré avec `python.exe` comme enfant) — Qt le démarre avec `CREATE_NO_WINDOW` |

**Décision : deux exécutables dans le même dossier**, un seul `_internal\` :

- `EEG API Unicorn.exe` (fenêtré) : la console, celui des raccourcis. S'il plante au démarrage,
  sa boîte d'erreur montre l'erreur, que l'utilisateur ne verrait pas autrement.
- `eeg-api-unicorn-cli.exe` (mode console) : la console le relance pour chaque fenêtre de
  stimulus (`stimulus/registry.py`, `programme_installe`). Une fenêtre qui plante s'arrête en
  écrivant son erreur, que la console affiche ; avec l'exécutable fenêtré, une boîte d'erreur
  serait restée cachée derrière une fenêtre de stimulus plein écran, et la console aurait attendu.
  C'est aussi lui qu'on tape dans un terminal :

  ```powershell
  & "C:\Program Files\EEG API Unicorn\eeg-api-unicorn-cli.exe" --serveur --mode ssvep
  & "C:\Program Files\EEG API Unicorn\eeg-api-unicorn-cli.exe" --version
  & "C:\Program Files\EEG API Unicorn\eeg-api-unicorn-cli.exe" --verifier-modules
  ```

Le prix : 20 Mo de plus dans le dossier (chaque exécutable contient le code Python compilé).

## Installer

### Pour tous, ou pour moi seulement

L'assistant demande d'abord :

- **pour tous les utilisateurs** (le défaut, droits d'administrateur demandés) : le programme va
  dans `C:\Program Files\EEG API Unicorn\`, et l'installeur **ajoute une règle au pare-feu de
  Windows** pour les deux exécutables (entrées autorisées). Sans elle, les applications LSL d'une
  autre machine et les appareils réseau (UDP, port 5010) ne joignent jamais le programme ;
- **pour moi seulement** (sans droits d'administrateur) : le programme va dans
  `%LOCALAPPDATA%\Programs\EEG API Unicorn\`, **sans** règle de pare-feu : ajouter une règle exige
  les droits d'administrateur. Windows demandera l'autorisation la première fois que le programme
  écoute le réseau (et cette autorisation peut, elle aussi, demander un administrateur). Sur une
  seule machine (application et console sur le même PC), rien de cela ne gêne.

En ligne de commande : `/ALLUSERS` ou `/CURRENTUSER` choisit sans poser la question ;
`/VERYSILENT /SUPPRESSMSGBOXES` installe sans fenêtre ; `/DIR="…"` change le dossier.

### SmartScreen

L'installeur n'est pas signé : au premier lancement, Windows affiche « Windows a protégé votre
ordinateur ». Cliquer **Informations complémentaires**, puis **Exécuter quand même**.

### Les données de l'utilisateur

Les modèles entraînés et les séances enregistrées vivent dans `Documents\EEG API Unicorn\`
(`modeles\` et `seances\`), jamais dans le dossier d'installation. **Désinstaller ou mettre à jour
n'y touche pas** : les modèles et les séances restent. Pour tout effacer, supprimer ce dossier à
la main après la désinstallation.

### Le journal

Lancé par son raccourci, `EEG API Unicorn.exe` n'a pas de terminal où écrire : ce qu'il écrit
(les messages du moteur, l'erreur qui l'arrête) va dans
`Documents\EEG API Unicorn\journaux\console.log`, et le journal du lancement d'avant reste dans
`console.precedent.log`. Quand le moteur s'arrête, la console donne ce chemin. Si le dossier
n'est pas accessible en écriture, le programme démarre quand même, sans journal.
`eeg-api-unicorn-cli.exe`, lui, écrit dans le terminal qui le lance.

### Mettre à jour, désinstaller

Un installeur plus récent s'installe par-dessus l'ancien (il le reconnaît à son identifiant,
`AppId`, qui ne change jamais). Désinstaller : Paramètres → Applications → EEG API Unicorn, ou
`unins000.exe` dans le dossier d'installation ; la règle du pare-feu est retirée avec le programme.
