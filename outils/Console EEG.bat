@echo off
rem La derniere ligne de commande du parcours utilisateur, et elle est ecrite une fois pour toutes.
rem Double-clic depuis l'explorateur : la console s'ouvre, et tout le reste s'y fait aux boutons —
rem calibrer, choisir un modele, afficher un stimulus, decoder, lire les resultats.
rem
rem Les arguments sont transmis tels quels : "Console EEG.bat" --synthetic ouvre la console sur le
rem board de test de BrainFlow, sans casque.
cd /d "%~dp0.."
rem Si un environnement virtuel .venv existe a la racine du depot, c'est lui qui lance la
rem console : il porte la version de Python et les dependances du projet. Sans .venv, le
rem python du PATH, comme avant.
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" src\console\app.py %*
rem Sans cette pause, une console qui meurt au demarrage (Python absent, PySide6 non installe,
rem casque introuvable) ferme sa fenetre avant que le message ne soit lisible : le clic silencieux
rem que ce chantier repare, reintroduit par son propre raccourci.
if errorlevel 1 pause
