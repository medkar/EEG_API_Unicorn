"""Lancer une fenêtre de stimulus depuis la console, et DIRE ce qu'elle devient.

Une fenêtre de `src/stimulus/` est un second processus : elle dessine un stimulus verrouillé à la
frame — ce que Qt ne sait pas rendre — et publie des marqueurs. Elle n'ouvre PAS le casque, c'est
pour ça qu'elle peut tourner à côté du moteur.

Trois règles, et chacune ferme une panne réelle :

1. **La ligne de commande vient de `stimulus.registry.commande(...)`, jamais d'ici.** Ce module ne
   sait pas qu'un P300 se lance avec `p300.py` : il demande. Un fichier renommé se corrige à un
   seul endroit, et la console ne tient aucun catalogue recopié.
2. **UNE SEULE fenêtre à la fois.** Deux fenêtres publieraient les mêmes marqueurs sous le même
   nom, et le moteur mélangerait les deux séances sans rien signaler — aucune exception, aucun
   compteur, des époques étiquetées à l'envers.
3. **Une fenêtre qui meurt anormalement le DIT.** C'est le défaut que ce chantier répare : la
   recette du projet (test 1.13) a relevé cinq clics d'affilée sur un bouton qui refusait
   correctement — mais dans le terminal, pas dans la fenêtre. Un refus qu'on ne voit pas est un
   bouton cassé.

⚠️ Ce module ne décide RIEN sur le contact des électrodes ni sur l'état du moteur : il lance un
processus et surveille sa mort. Le contrôle de liaison est dans `contact_page.py`, l'ordre
« calibration d'abord, fenêtre ensuite » dans `app.py`.
"""

import os
import sys
from collections import deque

from PySide6.QtCore import QObject, QProcess, Signal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stimulus import registry as stimulus_registry  # noqa: E402

# Combien de lignes de sortie de la fenêtre on garde pour l'écran. Assez pour porter le message
# d'erreur d'un processus qui vient de mourir (traceback Python : la dernière ligne suffit, celle
# d'avant donne le fichier), pas assez pour transformer le bandeau en journal.
LIGNES_RETENUES = 6


class LanceurFenetre(QObject):
    """Au plus UN processus de fenêtre, son état, sa mort. Rien d'autre.

    `fabrique` construit le `QProcess` — injectable pour que le smoke n'ait JAMAIS à lancer un
    vrai pygame. Un smoke qui démarre un processus graphique en CI est un smoke qu'on finit par
    désactiver, et le jour où on le désactive on perd les trois règles ci-dessus d'un coup.
    """

    change = Signal()      # l'état a bougé : la console doit repeindre son bandeau

    def __init__(self, fabrique=None):
        super().__init__()
        self._fabrique = fabrique if fabrique is not None else QProcess
        self._proc = None
        self._quoi = ""            # ce qui tourne, en clair : « P300 (calibration) »
        self._tue = False          # c'est NOUS qui l'avons arrêté -> sa mort n'est pas anormale
        self._lignes = deque(maxlen=LIGNES_RETENUES)
        self.probleme = ""         # non vide = quelque chose à AFFICHER, tel quel

    # --- lecture ----------------------------------------------------------------

    def en_cours(self):
        """Une fenêtre tourne-t-elle ? La seule question qui décide d'un refus."""
        return self._proc is not None

    def quoi(self):
        """Ce qui tourne, en clair, ou une chaîne vide."""
        return self._quoi

    def etat_texte(self):
        """(texte à afficher, est-ce une alerte). Chaîne vide = rien à dire.

        Le problème passe AVANT ce qui tourne : quand une fenêtre vient de mourir, il n'y a plus
        rien qui tourne, et c'est justement le moment où il faut parler.
        """
        if self.probleme:
            return self.probleme, True
        if self._proc is not None:
            return f"fenêtre {self._quoi} en cours — ne la ferme pas à la main pendant la séance", False
        return "", False

    # --- écriture ---------------------------------------------------------------

    def lancer(self, stimulus_id, calibrer=False, label=""):
        """Démarre la fenêtre. Rend le MÊME accusé que le moteur : `{accepted, reason}`.

        La forme est celle de `EngineServer.submit` délibérément : l'appelant traite un refus de
        fenêtre exactement comme un refus de commande, sans se demander lequel des deux il tient.
        """
        if self._proc is not None:
            return self._refuser(
                f"⚠ une fenêtre tourne déjà ({self._quoi}) — ferme-la avant d'en lancer une "
                f"autre. Deux fenêtres publieraient les mêmes marqueurs sous le même nom, et le "
                f"moteur mélangerait les deux séances sans rien signaler.")
        try:
            argv = stimulus_registry.commande(stimulus_id, calibrer=calibrer)
        except KeyError as e:
            # Une clé de contrat sans fenêtre. `stimulus/registry.py` vérifie déjà la
            # correspondance dans les deux sens, mais son autotest n'est pas la console : si on
            # arrive ici, il faut le voir à l'écran plutôt que dans un traceback.
            return self._refuser(f"⚠ {e}")

        self.probleme = ""
        self._lignes.clear()
        self._tue = False
        self._quoi = f"{label or stimulus_id}{' (calibration)' if calibrer else ''}"
        proc = self._fabrique()
        # Les deux canaux fusionnés : ce qu'on cherche à montrer est le message d'erreur d'un
        # processus qui meurt, et Python l'écrit sur stderr. Les séparer obligerait à les
        # recoller pour les afficher.
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.readyReadStandardOutput.connect(self._encaisser_sortie)
        proc.finished.connect(self._fini)
        proc.errorOccurred.connect(self._erreur)
        self._proc = proc
        proc.start(argv[0], list(argv[1:]))
        self.change.emit()
        if self._proc is None:
            # `start()` a échoué TOUT DE SUITE (exécutable introuvable) : Qt émet `errorOccurred`
            # de façon synchrone, `_erreur` a déjà remis `_proc` à None et rédigé le message. Le
            # rendre comme un refus plutôt que d'annoncer un succès — c'est cet accusé que
            # l'appelant lit pour décider s'il doit ANNULER la calibration qu'il vient de lancer.
            return {"accepted": False, "reason": self.probleme}
        return {"accepted": True, "command": "fenetre", "argv": list(argv)}

    def _refuser(self, raison):
        """Un refus qui se VOIT. La raison est aussi rangée dans `probleme`, donc affichée par le
        bandeau : un refus rendu à l'appelant et à personne d'autre est exactement le bouton
        silencieux que ce chantier répare."""
        self.probleme = raison
        self.change.emit()
        return {"accepted": False, "reason": raison}

    def arreter(self):
        """Tue la fenêtre s'il y en a une. Idempotente, et sa mort n'est PAS annoncée comme
        anormale : c'est nous qui l'avons demandée."""
        proc, self._proc = self._proc, None
        if proc is None:
            return
        self._tue = True
        # ⚠️ On COUPE ses signaux avant de le tuer. `waitForFinished` n'attend que 2 s : un
        # processus qui ne meurt pas dans ce délai pourrait émettre son `finished` bien plus tard,
        # alors qu'une AUTRE fenêtre tourne déjà — et `_fini` marquerait celle-là comme terminée,
        # remettant `_proc` à None sur un processus bien vivant. Un mort qui parle à la place d'un
        # vivant : la console croirait pouvoir en lancer une deuxième.
        for signal, receveur in ((proc.finished, self._fini),
                                 (proc.errorOccurred, self._erreur),
                                 (proc.readyReadStandardOutput, self._encaisser_sortie)):
            try:
                signal.disconnect(receveur)
            except (RuntimeError, TypeError):
                pass      # déjà déconnecté (le processus est mort entre-temps) : rien à faire
        proc.kill()
        # Attendre : sans ça, la console peut se fermer avant que le système n'ait repris le
        # processus, et une fenêtre plein écran orpheline reste devant l'écran de l'étudiant.
        if hasattr(proc, "waitForFinished"):
            proc.waitForFinished(2000)
        self._quoi = ""
        self.change.emit()

    # --- les signaux du processus ------------------------------------------------

    def _encaisser_sortie(self):
        """Garde les dernières lignes. `-u` (posé par `stimulus/registry.py`) les fait arriver
        NON TAMPONNÉES : sans lui, le message d'un processus qui vient de mourir resterait dans
        son tampon — c'est-à-dire exactement quand on en a besoin."""
        proc = self._proc
        if proc is None:
            return
        brut = bytes(proc.readAllStandardOutput())
        for ligne in brut.decode("utf-8", errors="replace").splitlines():
            if ligne.strip():
                self._lignes.append(ligne.strip())

    def _fini(self, code, statut):
        """Le processus s'est terminé. Anormal = code non nul, ou arrêt brutal non demandé."""
        self._encaisser_sortie()
        self._proc = None
        quoi, self._quoi = self._quoi, ""
        brutal = statut == QProcess.ExitStatus.CrashExit
        if self._tue:
            # Nous l'avons tué (fermeture de la console, ou geste explicite) : rien à signaler.
            self._tue = False
        elif code != 0 or brutal:
            self.probleme = (f"⚠ la fenêtre {quoi} s'est arrêtée anormalement "
                             f"(code {code}{', arrêt brutal' if brutal else ''}) — "
                             f"{self._derniere_sortie()}")
        self.change.emit()

    def _erreur(self, erreur):
        """`errorOccurred` : le cas où `finished` n'arrivera JAMAIS.

        Un exécutable introuvable ou un module absent ne produit pas un code de sortie : Qt émet
        `FailedToStart` et rien d'autre. Sans cette branche, le bouton resterait « en cours » pour
        toujours, et le clic redeviendrait silencieux.
        """
        if erreur != QProcess.ProcessError.FailedToStart or self._proc is None:
            # Les autres erreurs (crash, timeout d'écriture…) sont suivies d'un `finished`, qui
            # dira la même chose avec le code de sortie. Ne pas parler deux fois. Et un processus
            # qu'on a déjà lâché (`_proc is None`) ne doit rien annoncer du tout.
            return
        quoi, self._quoi = self._quoi, ""
        self._proc = None
        self.probleme = (f"⚠ la fenêtre {quoi} n'a pas DÉMARRÉ (exécutable introuvable ou "
                         f"dépendance manquante) — {self._derniere_sortie()}")
        self.change.emit()

    def _derniere_sortie(self):
        """Les dernières lignes du processus, pour que le message dise QUOI réparer."""
        if not self._lignes:
            return ("aucune sortie ; relance-la à la main dans un terminal pour voir son "
                    "message : `python src/stimulus/<mode>.py`")
        return " · ".join(self._lignes)

    def oublier_probleme(self):
        """Efface le message. Appelée quand on relance : un vieux problème affiché à côté d'une
        fenêtre qui tourne se lit comme un problème ACTUEL."""
        self.probleme = ""
        self.change.emit()
