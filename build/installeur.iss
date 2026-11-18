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
;
; L'installeur copie aussi le dossier EEG_API_Unicorn_Applications (les bibliothèques et les
; exemples, par plateforme) là où la personne le choisit, par défaut dans Documents\EEG API
; Unicorn. En silencieux : /APPLICATIONS="C:\un\dossier" choisit ce dossier.

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
; Windows 10 version 1809 (build 17763) au minimum : c'est le plus ancien Windows que prend en
; charge Qt 6.12, la bibliothèque de l'interface (doc.qt.io/qt-6/supported-platforms.html). Sur un
; Windows plus ancien, le programme s'installerait, puis refuserait de démarrer sans dire
; pourquoi. Avec cette ligne, l'installeur refuse dès le départ, avec un message clair.
; À revoir si PySide6 change de version.
MinVersion=10.0.17763
SetupIconFile=..\assets\logo\eeg-api-unicorn.ico
UninstallDisplayIcon={app}\{#ExeApp}
UninstallDisplayName={#NomApp}
OutputDir=sortie
OutputBaseFilename=EEG-API-Unicorn-Setup-{#VersionApp}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=auto
; Le dossier des applications va par défaut dans les Documents ({userdocs}) : la page qui le
; demande le montre et laisse le changer, y compris dans une installation « pour tous » (où
; {userdocs} est le dossier de l'administrateur qui a validé l'installation).
UsedUserAreasWarning=no

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
french.PareFeu=Autorisation du programme dans le pare-feu de Windows…
english.PareFeu=Allowing the program through Windows Firewall…
french.Desinstaller=Désinstaller %1
english.Desinstaller=Uninstall %1
french.ApplicationsTitre=Applications d'exemple
english.ApplicationsTitre=Example applications
french.ApplicationsSousTitre=Où copier le dossier EEG_API_Unicorn_Applications ?
english.ApplicationsSousTitre=Where should the EEG_API_Unicorn_Applications folder go?
french.ApplicationsTexte=Le dossier EEG_API_Unicorn_Applications contient, pour chaque plateforme (Python, Unity, MATLAB, Raspberry Pi, ROS 2, ESP32, Arduino), la bibliothèque qui connecte une application à EEG API Unicorn et un exemple complet. Il sera copié dans le dossier ci-dessous et mis à jour à chaque nouvelle version : copiez-en un sous-dossier ailleurs avant de le modifier.
french.ApplicationsVide=Choisissez un dossier pour EEG_API_Unicorn_Applications.
english.ApplicationsVide=Choose a folder for EEG_API_Unicorn_Applications.
english.ApplicationsTexte=The EEG_API_Unicorn_Applications folder holds, for each platform (Python, Unity, MATLAB, Raspberry Pi, ROS 2, ESP32, Arduino), the library that connects an application to EEG API Unicorn and a complete example. It will be copied into the folder below and updated with every new version: copy a sub-folder elsewhere before editing it.

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
; Les bibliothèques et les exemples, dans le dossier choisi sur la page « Applications d'exemple »
; (le [Code] plus bas). Une mise à jour les remplace ; la désinstallation les retire.
Source: "..\EEG_API_Unicorn_Applications\*"; DestDir: "{code:DossierApplications}\EEG_API_Unicorn_Applications"; Excludes: "__pycache__,secrets.h"; Flags: ignoreversion recursesubdirs createallsubdirs

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

[Code]
var
  PageApplications: TInputDirWizardPage;

// Le dossier proposé : celui de /APPLICATIONS="…" en silencieux, sinon celui d'une installation
// précédente, sinon Documents\EEG API Unicorn.
function DossierParDefaut(): String;
begin
  Result := ExpandConstant('{param:APPLICATIONS|}');
  if Result = '' then
    Result := GetPreviousData('DossierApplications', ExpandConstant('{userdocs}\{#NomApp}'));
end;

procedure InitializeWizard();
begin
  PageApplications := CreateInputDirPage(wpSelectDir, CustomMessage('ApplicationsTitre'),
    CustomMessage('ApplicationsSousTitre'), CustomMessage('ApplicationsTexte'), False, '');
  PageApplications.Add('');
  PageApplications.Values[0] := DossierParDefaut();
end;

// Retenu pour la prochaine mise à jour, qui le propose de nouveau.
procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'DossierApplications', PageApplications.Values[0]);
end;

// Un dossier vide enverrait les fichiers à la racine du disque.
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = PageApplications.ID) and (Trim(PageApplications.Values[0]) = '') then
  begin
    MsgBox(CustomMessage('ApplicationsVide'), mbError, MB_OK);
    Result := False;
  end;
end;

// Lu par la ligne [Files] des applications.
function DossierApplications(Param: String): String;
begin
  Result := PageApplications.Values[0];
end;
