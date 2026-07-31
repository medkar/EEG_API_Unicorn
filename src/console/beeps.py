"""Les tops latéralisés de la calibration : oreille gauche, droite, ou les deux.

Le son est de la PRÉSENTATION, pas du protocole. Si l'audio manque — machine sans carte son,
session distante, pilote absent — la calibration se déroule quand même, et la page le DIT. Un
top silencieux qui ne s'annonce pas ferait croire à l'étudiant qu'il a raté le départ.

Pourquoi latéraliser : le côté est porté par l'oreille (gauche/droite) et le repos par la durée
(les deux oreilles, plus long). L'étudiant n'a donc rien à LIRE au moment où il doit commencer à
imaginer — lire déplace le regard et contamine la fenêtre enregistrée.
"""

import numpy as np

FREQ_HZ = 880.0
SR = 44100
DUREE_COTE_S = 0.18
DUREE_CENTRE_S = 0.40


def _onde(gauche, droite, duree):
    """Un top stéréo entrelacé, en int16. Fondu de 10 ms aux deux bouts (anti-clic)."""
    t = np.linspace(0, duree, int(SR * duree), endpoint=False)
    enveloppe = np.clip(np.minimum(t / 0.01, (duree - t) / 0.01), 0, 1)
    ton = (0.35 * np.sin(2 * np.pi * FREQ_HZ * t) * enveloppe * 32767).astype(np.int16)
    stereo = np.zeros((len(ton), 2), dtype=np.int16)
    if gauche:
        stereo[:, 0] = ton
    if droite:
        stereo[:, 1] = ton
    return stereo.tobytes()


class Beeps:
    """Les trois tops. `disponible` dit franchement si le son sortira."""

    def __init__(self):
        self.disponible = False
        self.raison = ""
        self._sinks = {}
        self._données = {}
        try:
            from PySide6.QtCore import QBuffer, QByteArray
            from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

            sortie = QMediaDevices.defaultAudioOutput()
            if sortie is None or sortie.isNull():
                self.raison = "aucune sortie audio sur cette machine"
                return
            fmt = QAudioFormat()
            fmt.setSampleRate(SR)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(QAudioFormat.Int16)
            for cle, (g, d, duree) in {
                    "GAUCHE": (True, False, DUREE_COTE_S),
                    "DROITE": (False, True, DUREE_COTE_S),
                    "REPOS": (True, True, DUREE_CENTRE_S)}.items():
                octets = QByteArray(_onde(g, d, duree))
                tampon = QBuffer()
                tampon.setData(octets)
                self._données[cle] = tampon
                self._sinks[cle] = QAudioSink(sortie, fmt)
            self.disponible = True
        except Exception as e:  # noqa: BLE001 - l'audio casse de mille façons, toutes équivalentes
            self.raison = f"{type(e).__name__} : {e}"

    def jouer(self, classe):
        """Joue le top de cette classe. Ne lève jamais : un son raté n'arrête pas une séance."""
        if not self.disponible:
            return
        try:
            from PySide6.QtCore import QIODevice

            sink, tampon = self._sinks.get(classe), self._données.get(classe)
            if sink is None or tampon is None:
                return
            sink.stop()
            tampon.close()
            tampon.open(QIODevice.ReadOnly)
            tampon.seek(0)
            sink.start(tampon)
        except Exception:  # noqa: BLE001
            pass
