; Script Inno Setup de « EEG API Unicorn » : fabrique l'installeur Windows
; (EEG-API-Unicorn-Setup-<version>.exe) à partir du dossier que PyInstaller a produit.
;
; ⚠️ Ce fichier est enregistré en UTF-8 AVEC BOM : sans lui, Inno Setup le lit dans l'ancien
; codage de Windows et les accents de nos messages se perdent.
;
; Construire : `build\construire_installeur.ps1` fait tout (PyInstaller puis ce script). À la main,
; depuis la racine du dépôt, une fois `dist\EEG API Unicorn\` construit :
;
;     ISCC.exe /DVersionApp=1.0.0 build\installeur.iss
;
; Résultat : `build\sortie\EEG-API-Unicorn-Setup-1.0.0.exe`.

#define NomApp "EEG API Unicorn"
#define ExeApp "EEG API Unicorn.exe"
#define ExeConsole "eeg-api-unicorn-cli.exe"
#define EditeurApp "medkar"
; Le dépôt PUBLIC du logiciel : c'est l'adresse que Windows affiche dans « Applications installées ».
#define UrlApp "https://github.com/medkar/EEG_API_Unicorn"

; La version est donnée par le script de construction, qui la lit dans `src/core/version.py` (le
; seul endroit où elle est écrite). Sans elle, on s'arrête plutôt que d'inventer un numéro.
#ifndef VersionApp
  #error La version manque : lance build\construire_installeur.ps1, ou ISCC /DVersionApp=X.Y.Z build\installeur.iss
#endif

; Les avis de licence, que `construire_installeur.ps1` pose dans le dossier construit : LICENSE
; (la licence MIT du programme) et THIRD-PARTY-NOTICES.txt (les licences de tout ce que le
; programme embarque). Sans eux, l'installeur distribuerait le code d'autres auteurs sans leurs
; licences : on s'arrête.
#define DossierConstruit AddBackslash(SourcePath) + "..\dist\" + NomApp
#if !FileExists(DossierConstruit + "\LICENSE")
  #error LICENSE manque dans le dossier construit : lance build\construire_installeur.ps1
#endif
#if !FileExists(DossierConstruit + "\THIRD-PARTY-NOTICES.txt")
  #error THIRD-PARTY-NOTICES.txt manque dans le dossier construit : lance build\construire_installeur.ps1
#endif

[Setup]
; L'identité du logiciel pour Windows. ⚠️ NE JAMAIS LA CHANGER : c'est grâce à elle qu'une
; nouvelle version remplace l'ancienne au lieu de s'installer à côté.
AppId={{F6F468C7-2363-435C-9C0F-3736D15FAC5F}
AppName={#NomApp}
AppVersion={#VersionApp}
AppVerName={#NomApp} {#VersionApp}
AppPublisher={#EditeurApp}
AppPublisherURL={#UrlApp}
AppSupportURL={#UrlApp}
AppUpdatesURL={#UrlApp}
VersionInfoVersion={#VersionApp}
; « Program Files » pour tout le monde, ou le dossier des programmes de l'utilisateur
; (%LOCALAPPDATA%\Programs) quand on installe pour soi seul.
DefaultDirName={autopf}\{#NomApp}
DefaultGroupName={#NomApp}
DisableProgramGroupPage=yes
; Par défaut, installation pour TOUS les utilisateurs (droits d'administrateur) : c'est ce qui
; permet d'ajouter la règle du pare-feu. L'assistant propose aussi « pour moi seulement », sans
; droits d'administrateur, mais alors sans règle de pare-feu (voir [Run]).
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
; Le programme est construit en 64 bits.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\assets\logo\eeg-api-unicorn.ico
UninstallDisplayIcon={app}\{#ExeApp}
UninstallDisplayName={#NomApp}
OutputDir=sortie
OutputBaseFilename=EEG-API-Unicorn-Setup-{#VersionApp}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=auto

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
french.PareFeu=Autorisation du programme dans le pare-feu de Windows…
english.PareFeu=Allowing the program through Windows Firewall…
french.Desinstaller=Désinstaller %1
english.Desinstaller=Uninstall %1

[Tasks]
Name: "bureau"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Une mise à jour efface d'abord les bibliothèques de la version précédente : Inno ne retire pas
; un fichier que la nouvelle version n'a plus, et des bibliothèques de deux versions mélangées
; dans `_internal\` font planter le programme au démarrage.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; Tout le dossier construit : les deux exécutables, `_internal\`, et les deux avis de licence
; (LICENSE, THIRD-PARTY-NOTICES.txt), à côté des exécutables.
Source: "..\dist\{#NomApp}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; ⚠️ Les modèles entraînés et les séances de l'utilisateur vivent dans
; `Documents\EEG API Unicorn\` (`modeles\`, `seances\`), jamais dans le dossier d'installation.
; Ce script n'y touche NULLE PART : désinstaller ou mettre à jour garde les modèles et les séances.

[Icons]
Name: "{group}\{#NomApp}"; Filename: "{app}\{#ExeApp}"
Name: "{group}\{cm:Desinstaller,{#NomApp}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#NomApp}"; Filename: "{app}\{#ExeApp}"; Tasks: bureau

[Run]
; La règle du PARE-FEU : sans elle, Windows bloque ce qui arrive du réseau vers le programme — les
; applications LSL d'une autre machine et les appareils réseau (UDP, port 5010) ne le joignent
; jamais. Une règle par exécutable : la console, et l'exécutable en mode console (le moteur seul,
; `--serveur`, et les fenêtres de stimulus).
; On retire d'abord une éventuelle règle du même nom (une mise à jour réinstalle par-dessus) : sans
; ça, les règles s'empileraient. `netsh` sort en erreur s'il n'y en avait pas : Inno l'ignore.
; Seulement pour une installation « pour tous » : ajouter une règle exige les droits
; d'administrateur. Installé « pour moi seulement », c'est Windows qui demandera l'autorisation la
; première fois que le programme écoute le réseau.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#NomApp}"" program=""{app}\{#ExeApp}"""; Flags: runhidden; StatusMsg: "{cm:PareFeu}"; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#NomApp}"" program=""{app}\{#ExeConsole}"""; Flags: runhidden; StatusMsg: "{cm:PareFeu}"; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#NomApp}"" dir=in action=allow program=""{app}\{#ExeApp}"" enable=yes"; Flags: runhidden; StatusMsg: "{cm:PareFeu}"; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#NomApp}"" dir=in action=allow program=""{app}\{#ExeConsole}"" enable=yes"; Flags: runhidden; StatusMsg: "{cm:PareFeu}"; Check: IsAdminInstallMode
; Lancer le programme à la fin de l'installation (case cochée par défaut ; jamais en silencieux).
; `runasoriginaluser` : lancé avec les droits de la personne, pas ceux de l'administrateur qui a
; validé l'installation — sinon ses modèles iraient dans les Documents de l'administrateur.
Filename: "{app}\{#ExeApp}"; Description: "{cm:LaunchProgram,{#NomApp}}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
; Les mêmes règles, retirées à la désinstallation. Le désinstalleur tourne dans le mode de
; l'installation : une installation « pour moi seulement » n'a pas ajouté de règle, elle n'en
; retire pas.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#NomApp}"" program=""{app}\{#ExeApp}"""; Flags: runhidden; RunOnceId: "PareFeuConsole"; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#NomApp}"" program=""{app}\{#ExeConsole}"""; Flags: runhidden; RunOnceId: "PareFeuCli"; Check: IsAdminInstallMode
