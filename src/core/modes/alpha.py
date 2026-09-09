"""Le contrôle alpha (effet de Berger) : la BARRIÈRE d'entrée d'une séance au casque.

Le protocole tient en deux phases : **8 s les yeux ouverts**, puis **8 s les yeux fermés**. Sur
les voies occipitales, la bande 8-12 Hz doit monter FRANCHEMENT à la fermeture des yeux. Si elle
ne monte pas, trois choses sont en cause — les électrodes occipitales ne touchent pas, la
référence (mastoïdes) a lâché, ou l'ordre des voies est faux — et **aucun autre test de la séance
ne veut plus rien dire** : ni le SSVEP, ni les quatre modes à modèle, qui lisent tous ce même
signal.

D'où le mot BARRIÈRE, et le fait que le verdict soit une **phrase qui arrête** plutôt qu'un
chiffre à interpréter. Un étudiant qui lit « ratio 1,04 » ne sait pas quoi en faire ; un étudiant
qui lit « ARRÊTE, re-saline les occipitales » sait.

⚠️ **Le protocole, les durées et les bandes sont repris TELS QUELS de l'écran archivé
`archive/alpha_check.py`** (ex-`src/research/alpha_check.py`), que cette mesure remplace. Ce n'est
pas de la fidélité de principe : le repère « ratio > ~1,5 » a été observé sous CES durées, sur CE
casque. Raccourcir une phase à 4 s diviserait la résolution spectrale par deux et rendrait le
repère faux — sans qu'aucun test ne le dise, parce que le calcul, lui, continuerait à rendre un
nombre parfaitement plausible.

⚠️ **Ce que cette mesure ferme, en plus** : le pic alpha mesuré ici est exactement la valeur que
le réglage « Pic alpha » du SSVEP attend (`core/modes/ssvep.py`, `alpha_hz`, borné 6-14 Hz comme
la recherche de pic ci-dessous). La recette le faisait NOTER À LA MAIN sur un carnet, puis
RETAPER dans un autre écran. La console le renvoie maintenant au moteur d'un clic — une valeur
recopiée entre deux écrans est ce que ce dépôt a déjà vu diverger.

Autotest :
    python src/core/modes/alpha.py
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
import numpy as np  # noqa: E402
from brainflow.data_filter import DataFilter, DetrendOperations, NoiseTypes  # noqa: E402

from core.config import (CH_NAMES, OCCIPITAL, SIGNAL_DEAD_SIGMA,  # noqa: E402
                         signal_verdict, use_utf8_console)
from core.modes.mesure import Etape, MesureRuntime, MesureSpec  # noqa: E402
# ⚠️ Importé pour UNE chose : le réglage que ce pic alimente (`alpha_hz`), avec son libellé et le
# mode qui le porte. C'est ce qui permet à la console de PROPOSER l'application du pic sans écrire
# « ssvep » ni « alpha_hz » dans son propre code — le « catalogue recopié » que `CLAUDE.md`
# interdit. Aucun cycle : `modes/ssvep.py` n'importe ni `mesure` ni `registry`.
from core.modes.ssvep import SPEC as SPEC_SSVEP  # noqa: E402

# --- les constantes du protocole, reprises telles quelles ---------------------------------------
# ⚠️ Les quatre valeurs ci-dessous forment un TOUT avec le repère `RATIO_MIN`. Elles ne se règlent
# pas depuis l'interface, et `SPEC.params` est vide pour cette raison précise : un réglage
# « durée » exposé à l'étudiant lui laisserait invalider le seul repère chiffré de la mesure en
# croyant gagner du temps, et le verdict continuerait de s'afficher avec le même aplomb.
DUREE_PHASE_S = 8.0        # la partie ENREGISTRÉE de chaque phase
DUREE_PREP_S = 3.0         # « ferme les yeux dans 3… 2… 1 » — jouée, montrée, PAS enregistrée
SEGMENT_S = 2.0            # segments de Welch (Hann, 50 % de recouvrement) -> 0,5 Hz de résolution

BANDE_ALPHA = (8.0, 12.0)  # la bande dont on compare la PUISSANCE entre les deux phases
BANDE_PIC = (6.0, 14.0)    # la plage où l'on CHERCHE le pic — plus large, pour le voir sortir
# La plage où un pic est réellement de l'alpha. Plus étroite que `BANDE_PIC` À DESSEIN : c'est
# précisément parce qu'on cherche large qu'on peut constater qu'un pic est tombé à 6,5 Hz, donc
# que ce n'est pas de l'alpha mais une dérive lente. Chercher directement dans 8-12 rendrait
# toujours un pic « valide », y compris sur du bruit.
PIC_ATTENDU = (8.0, 12.5)
RATIO_MIN = 1.5            # le repère : `alpha_check.py` affichait « attendu > ~1.5 » depuis 2026-07

# Les noms des deux étapes ENREGISTRÉES. Des constantes, et pas deux chaînes écrites à deux
# endroits : `protocole()` les pose sur ses `Etape`, `_mesurer()` les cherche dans ce qu'il reçoit.
# Écrites deux fois, une faute de frappe donnerait « phase manquante » sur une séance parfaitement
# jouée — 37 s de casque pour un message qui accuse le sujet.
OUVERT = "yeux ouverts"
FERME = "yeux fermés"

# Les voies moyennées, NOMMÉES. `OCCIPITAL` vaut [4, 5, 6, 7] : Pz est dedans depuis qu'une mesure
# sur trois séances a montré qu'il aidait la projection SSVEP. ⚠️ L'écran d'origine imprimait
# « moyenne PO7/Oz/PO8 » alors qu'il moyennait DÉJÀ les quatre voies (il lisait `acq.occ_rows`,
# donc `OCCIPITAL`) : la phrase avait cessé d'être vraie sans que personne le voie. On la calcule
# donc au lieu de l'écrire.
VOIES = [CH_NAMES[i] for i in OCCIPITAL]

# Le réglage que ce pic alimente : mode SSVEP, clé `alpha_hz`. Lu dans le CONTRAT du mode, jamais
# réécrit — le libellé du bouton de la console est donc exactement celui du champ que l'étudiant
# retrouvera sur la page du SSVEP.
PARAM_CIBLE = next(p for p in SPEC_SSVEP.params if p.key == "alpha_hz")

HONNETETE = (
    "Ce contrôle dit UNE chose : les voies occipitales captent un rythme alpha qui monte quand "
    "tu fermes les yeux — donc les électrodes touchent, la référence tient, l'ordre des voies "
    "est bon. Il ne PRÉDIT rien : ni la justesse du SSVEP, ni celle d'un mode à modèle. Il est "
    "franchi ou il ne l'est pas ; un ratio de 6 ne vaut pas mieux qu'un ratio de 2.\n"
    f"Le repère « ratio > {RATIO_MIN:g} » vient des séances de ce dépôt, sur ce casque et sur UNE "
    f"personne : c'est un ordre de grandeur, pas un seuil validé. L'amplitude de l'alpha varie "
    f"beaucoup d'une personne à l'autre."
)

BRIEFING = (
    "Ce contrôle est une BARRIÈRE : s'il échoue, aucun autre test de la séance ne veut rien "
    "dire — c'est le montage qu'il faut reprendre, pas le test suivant.",
    f"Déroulé : stabilisation du casque, puis {DUREE_PHASE_S:.0f} s les yeux OUVERTS, puis "
    f"{DUREE_PHASE_S:.0f} s les yeux FERMÉS.",
    "Un TOP SONORE annonce chaque changement. C'est indispensable : la moitié de la mesure se "
    "passe les yeux fermés, où tu ne peux RIEN lire à l'écran.",
    "Reste immobile, mâchoire relâchée : un serrement de dents noie la bande alpha sous de "
    "l'EMG, et le ratio devient illisible.",
    "Yeux ouverts : fixe un point devant toi, cligne le moins possible.",
    "Yeux fermés : garde-les fermés jusqu'au TOP suivant, sans serrer les paupières.",
)


def _welch(x, fs, seg_s=SEGMENT_S):
    """PSD (Welch : segments Hann à 50 % de recouvrement) d'un signal 1D. Rend (freqs, psd).

    Repris tel quel de l'écran d'origine. Un `scipy.signal.welch` ferait la même chose en une
    ligne — on garde CETTE écriture parce que c'est elle qui a produit le repère 1,5 : les deux
    ne normalisent pas pareil, et un ratio est justement ce qui survit à une normalisation… tant
    que les deux termes passent par la MÊME.
    """
    n = len(x)
    seg = min(n, int(seg_s * fs))
    win = np.hanning(seg)
    step = max(1, seg // 2)
    powers = []
    for start in range(0, n - seg + 1, step):
        spec = np.fft.rfft(x[start:start + seg] * win)
        powers.append(np.abs(spec) ** 2)
    if not powers:                      # signal plus court qu'un segment
        spec = np.fft.rfft(x * np.hanning(n))
        return np.fft.rfftfreq(n, 1 / fs), np.abs(spec) ** 2
    return np.fft.rfftfreq(seg, 1 / fs), np.mean(powers, axis=0)


def _nettoyer(sig, fs):
    """Détrend (constant) + notch 50 Hz, voie par voie. Le large bande est GARDÉ.

    ⚠️ Le détrend n'est pas une politesse : l'Unicorn sort un offset DC de l'ordre de 10⁵ µV
    (mesuré le 2026-07-27). Une fenêtre non détrendue le fait FUIR à travers la fenêtre de Hann
    jusque dans la bande alpha, où il domine l'EEG de plusieurs ordres de grandeur — les deux
    phases y ressemblent alors à la même chose, et le ratio tombe à 1 quel que soit le sujet.
    L'autotest le vérifie en ajoutant 10⁵ µV aux deux phases.

    Et surtout : on ne filtre PAS en passe-bande. Le verdict a besoin de VOIR où tombe le pic —
    couper hors 8-12 Hz garantirait de trouver un pic dans 8-12 Hz, y compris sur du bruit.
    """
    out = np.ascontiguousarray(sig, dtype=np.float64)
    for c in range(out.shape[1]):
        col = np.ascontiguousarray(out[:, c])
        DataFilter.detrend(col, DetrendOperations.CONSTANT.value)
        DataFilter.remove_environmental_noise(col, int(round(fs)), NoiseTypes.FIFTY.value)
        out[:, c] = col
    return out


def _psd_occipitale(fenetre, fs):
    """(freqs, PSD moyennée sur les voies occipitales, σ par voie) d'une fenêtre BRUTE (n, 8).

    Les σ sortent d'ici parce qu'ils sont mesurés sur le MÊME signal nettoyé que la PSD : c'est
    ce qui permet à `_mesurer` de refuser une liaison morte au lieu d'en tirer un rapport (cf.
    son garde-fou), sans refaire un second nettoyage qui pourrait diverger du premier.
    """
    if fenetre.ndim != 2 or fenetre.shape[1] <= max(OCCIPITAL):
        raise ValueError(
            f"fenêtre de forme {getattr(fenetre, 'shape', '?')} : le contrôle alpha attend les "
            f"{len(CH_NAMES)} voies du casque pour y prendre {VOIES}")
    sig = _nettoyer(np.asarray(fenetre, dtype=np.float64)[:, OCCIPITAL], fs)
    freqs, psds = None, []
    for c in range(sig.shape[1]):
        freqs, psd = _welch(sig[:, c], fs)
        psds.append(psd)
    return freqs, np.mean(psds, axis=0), sig.std(axis=0)


def _puissance_bande(freqs, psd, lo, hi):
    return float(psd[(freqs >= lo) & (freqs < hi)].sum())


def _pic(freqs, psd, lo, hi):
    """La fréquence du maximum de `psd` dans [lo, hi]. En Hz."""
    bande = (freqs >= lo) & (freqs <= hi)
    return float(freqs[bande][int(np.argmax(psd[bande]))])


class ControleAlpha(MesureRuntime):
    """Yeux ouverts, yeux fermés, un rapport de puissances, une phrase qui arrête.

    Deux méthodes, comme tout `MesureRuntime` : `protocole()` (la suite d'étapes) et `_mesurer()`
    (le calcul). Le reste — chauffe, minutage, prélèvement, état pour l'écran, abandon — vient du
    socle et n'est pas redéfini.
    """

    def protocole(self):
        """Prép. → yeux OUVERTS → prép. → yeux FERMÉS. Les deux préparations ne prélèvent rien.

        L'ordre compte, et il n'est pas symétrique : ouvert D'ABORD. La personne arrive les yeux
        ouverts ; commencer par la fermeture obligerait à lui faire lire une consigne… qu'elle
        appliquerait pendant qu'on l'enregistre.
        """
        return (
            Etape("préparation", DUREE_PREP_S, enregistre=False,
                  instruction="Yeux OUVERTS — on commence dans un instant",
                  rappel="installe-toi, immobile ; un TOP annoncera le départ"),
            Etape(OUVERT, DUREE_PHASE_S,
                  instruction="YEUX OUVERTS — fixe un point devant toi",
                  rappel="immobile, cligne le moins possible"),
            Etape("préparation", DUREE_PREP_S, enregistre=False,
                  instruction="FERME LES YEUX au prochain TOP",
                  rappel="et garde-les fermés jusqu'au TOP suivant"),
            Etape(FERME, DUREE_PHASE_S,
                  instruction="YEUX FERMÉS — immobile",
                  rappel="un TOP dira quand rouvrir : d'ici là tu ne peux rien lire, c'est normal"),
        )

    def _mesurer(self, enregistre, fs):
        """Le verdict. Rend le dict lu par l'écran, ou lève avec un message lisible."""
        par_etape = {}
        for fenetre, nom in enregistre:
            par_etape.setdefault(nom, []).append(fenetre)
        manquantes = [nom for nom in (OUVERT, FERME) if nom not in par_etape]
        if manquantes:
            raise ValueError(
                f"phase(s) manquante(s) : {', '.join(manquantes)}. Un rapport de puissances a "
                f"besoin de SES DEUX termes — calculé sur une seule phase, il n'aurait aucun "
                f"terme de comparaison, et rien ne distinguerait ce chiffre d'un chiffre complet.")

        freqs, psd_ouvert, sigmas_ouvert = _psd_occipitale(par_etape[OUVERT][-1], fs)
        _f, psd_ferme, sigmas_ferme = _psd_occipitale(par_etape[FERME][-1], fs)

        # ⚠️ LA LIAISON MORTE, avant tout calcul. Quatre voies plates donnent une puissance de
        # l'ordre de 10⁻²⁷ des DEUX côtés, et leur rapport est alors du bruit d'arrondi : il vaut
        # 0,3 ou 4,1 au hasard des derniers bits, donc il FRANCHIT la barrière une fois sur
        # deux. C'est le pire résultat possible — « le montage est bon » affiché sur un câble
        # débranché, ce qui est exactement ce qui a coûté 3,4 min de vide le 2026-07-20.
        # Le seuil n'est pas inventé ici : c'est `signal_verdict`, la règle que le moteur applique
        # déjà à ses huit voies (`SIGNAL_DEAD_SIGMA`). Une seconde règle de qualité écrite ici
        # finirait par contredire celle du bandeau, et ce jour-là c'est l'écran qu'on croirait.
        for etiquette, sigmas in ((OUVERT, sigmas_ouvert), (FERME, sigmas_ferme)):
            if all(signal_verdict(s) == "morte" for s in sigmas):
                raise ValueError(
                    f"les {len(VOIES)} voies occipitales ({', '.join(VOIES)}) sont PLATES "
                    f"pendant « {etiquette} » : σ "
                    f"{', '.join(f'{s:.2f}' for s in sigmas)} µV, sous le seuil de voie morte du "
                    f"moteur ({SIGNAL_DEAD_SIGMA:g} µV). Ce n'est pas un résultat, c'est une "
                    f"panne de liaison — câble, électrodes, ou casque éteint.")

        p_ouvert = _puissance_bande(freqs, psd_ouvert, *BANDE_ALPHA)
        p_ferme = _puissance_bande(freqs, psd_ferme, *BANDE_ALPHA)
        ratio = p_ferme / p_ouvert
        pic_hz = _pic(freqs, psd_ferme, *BANDE_PIC)
        pic_ouvert_hz = _pic(freqs, psd_ouvert, *BANDE_PIC)

        # Les DEUX critères de l'écran d'origine, et ils ne disent pas la même chose : le ratio
        # dit que quelque chose a monté, le pic dit que ce quelque chose est bien de l'alpha.
        monte = ratio > RATIO_MIN
        au_bon_endroit = PIC_ATTENDU[0] <= pic_hz <= PIC_ATTENDU[1]
        franchie = bool(monte and au_bon_endroit)

        pic_arrondi = round(float(pic_hz), 1)
        return {
            "ratio": round(float(ratio), 2),
            "pic_hz": pic_arrondi,
            "pic_ouvert_hz": round(float(pic_ouvert_hz), 1),
            "p_ouvert": float(p_ouvert),
            "p_ferme": float(p_ferme),
            "repere_ratio": RATIO_MIN,
            "voies": list(VOIES),
            "barriere_franchie": franchie,
            "verdict": self._verdict(ratio, pic_hz, monte, au_bon_endroit),
            "honnetete": HONNETETE,
            # ⚠️ CE QUI FERME LA BOUCLE. La recette faisait NOTER ce pic sur un carnet, puis le
            # RETAPER dans « Pic alpha » de la page SSVEP. La console le renvoie maintenant au
            # moteur d'un clic — et c'est le MOTEUR qui dit vers quel mode et quelle clé, pour
            # que l'interface n'ait ni « ssvep » ni « alpha_hz » écrit dans son propre code.
            #
            # ⚠️ **Absent quand la barrière n'est pas franchie**, et la décision vit ICI plutôt
            # que dans l'écran : sur un signal sans alpha, le « pic » est le plus grand bin d'un
            # spectre de bruit. Le proposer serait pire que la boucle manuelle qu'on remplace —
            # une valeur fausse, appliquée d'un clic, sans le carnet où l'on aurait hésité.
            "reglage_propose": None if not franchie else {
                "mode": SPEC_SSVEP.id,
                "mode_label": SPEC_SSVEP.label,
                "cle": PARAM_CIBLE.key,
                "label": PARAM_CIBLE.label,
                "valeur": pic_arrondi,
                "unite": PARAM_CIBLE.unit,
            },
        }

    def _verdict(self, ratio, pic_hz, monte, au_bon_endroit):
        """LA phrase. Elle dit quoi faire, et quand s'arrêter — jamais un chiffre tout seul.

        Trois cas, parce que les deux critères appellent deux gestes différents : un alpha qui ne
        monte pas est un problème de CONTACT ; un pic qui monte hors de la plage attendue est
        presque toujours un artefact (mouvement, dérive lente), donc un problème de POSTURE.
        """
        voies = "/".join(VOIES)
        if monte and au_bon_endroit:
            return (f"Alpha NET à la fermeture des yeux : ratio {ratio:.2f} (repère "
                    f"> {RATIO_MIN:g}), pic à {pic_hz:.1f} Hz sur {voies}. Les électrodes "
                    f"occipitales touchent, la référence tient, l'ordre des voies est bon — la "
                    f"séance peut commencer.")
        if not monte:
            return (f"ARRÊTE ICI. L'alpha ne monte pas quand tu fermes les yeux : ratio "
                    f"{ratio:.2f} pour un repère de {RATIO_MIN:g}. Tant que ce n'est pas réglé, "
                    f"aucun autre test de cette séance ne voudra rien dire — tous lisent ce même "
                    f"signal. À reprendre dans cet ordre : 1) les ÉLECTRODES occipitales "
                    f"({voies}) touchent-elles le cuir chevelu, cheveux écartés ? 2) les "
                    f"MASTOÏDES (la référence) tiennent-elles ? 3) re-saline — c'est le levier "
                    f"le plus efficace mesuré sur ce casque. Vérifie aussi que les yeux étaient "
                    f"bien fermés et que tu n'as pas bougé, puis relance.")
        return (f"ARRÊTE ICI. Quelque chose monte à la fermeture des yeux (ratio {ratio:.2f}), "
                f"mais son pic tombe à {pic_hz:.1f} Hz, hors de la plage de l'alpha "
                f"({PIC_ATTENDU[0]:g}-{PIC_ATTENDU[1]:g} Hz) : ce n'est probablement pas de "
                f"l'alpha mais une dérive lente ou un artefact de mouvement. Reprends immobile, "
                f"mâchoire relâchée, et vérifie les ÉLECTRODES occipitales ({voies}) et les "
                f"mastoïdes avant de relancer.")


SPEC = MesureSpec(
    id="alpha",
    label="Contrôle alpha",
    summary="Yeux ouverts / yeux fermés : les électrodes occipitales captent-elles ? "
            "À faire EN PREMIER — tout le reste de la séance en dépend.",
    briefing=BRIEFING,
    # Aucun réglage, et c'est un choix : cf. le commentaire des constantes du protocole. Les
    # durées sont celles sous lesquelles le repère 1,5 a été observé.
    params=(),
    runtime_cls=ControleAlpha,
    barriere=True,
)


def _selftest():
    """Sur un signal dont on CONNAÎT la réponse : du bruit, plus une sinusoïde qu'on a posée.

    Aucun casque, aucune attente réelle — `tick` reçoit son horloge, donc les 37 s du protocole
    se jouent en quelques millisecondes.
    """
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}")
        ok = ok and bool(cond)

    from core.config import DATA_DIR, empreinte_dossier
    from core.modes import registry

    empreinte_avant = empreinte_dossier(DATA_DIR)
    FS = 250.0
    N = int(DUREE_PHASE_S * FS)

    def _bruit(rng, sigma=8.0):
        """Du bruit blanc sur les 8 voies. σ = 8 µV : l'ordre de grandeur d'un EEG sain."""
        return rng.normal(0.0, sigma, (N, len(CH_NAMES)))

    def _bruit_plus_alpha(rng, f_hz, gain, sigma=8.0):
        """Le même bruit, plus une sinusoïde sur les SEULES voies occipitales."""
        x = _bruit(rng, sigma)
        t = np.arange(N) / FS
        onde = gain * np.sin(2 * np.pi * f_hz * t)
        for c in OCCIPITAL:
            x[:, c] += onde
        return x

    class _FausseAcq:
        fs = FS

    class _FauxMoteur:
        """Rend la fenêtre de l'étape EN COURS. C'est ce qui rend le test de bout en bout."""

        def __init__(self, fenetres):
            self.acq = _FausseAcq()
            self.fenetres = fenetres        # {nom d'étape : fenêtre (n, 8)}
            self.rt = None
            self.demandes = []

        def recent_window(self, seconds):
            self.demandes.append(seconds)
            nom = self.rt.classe
            return self.fenetres.get(nom, np.zeros((N, len(CH_NAMES))))

    def _jouer(ouvert, ferme):
        """Joue le protocole ENTIER et rend (runtime, résultat). Pas d'appel direct à `_mesurer`.

        ⚠️ Passer par la ligne du temps est le point : les noms d'étapes que `protocole()` pose
        et ceux que `_mesurer()` cherche doivent être les MÊMES. Appeler `_mesurer` avec des
        étiquettes écrites dans le test prouverait le calcul et laisserait passer la faute de
        frappe qui rend « phase manquante » après 37 s de casque.
        """
        moteur = _FauxMoteur({OUVERT: ouvert, FERME: ferme})
        rt = ControleAlpha(SPEC, {}, moteur)
        moteur.rt = rt
        t = 0.0
        for _ in range(4000):
            rt.tick(moteur, t)
            if rt.terminee:
                break
            t += 0.25
        return rt, rt.resultat

    # === Le protocole : ce que la personne VIT ==============================================
    rt0 = ControleAlpha(SPEC, {}, None)
    etapes = rt0._etapes
    chk([e.nom for e in etapes] == ["préparation", OUVERT, "préparation", FERME],
        f"quatre étapes, ouvert AVANT fermé ({[e.nom for e in etapes]})")
    chk([e.enregistre for e in etapes] == [False, True, False, True],
        "…dont seules les deux phases sont enregistrées : le signal d'une préparation est celui "
        "d'un sujet qui bouge encore")
    chk(all(e.duree_s == DUREE_PHASE_S for e in etapes if e.enregistre)
        and all(e.duree_s == DUREE_PREP_S for e in etapes if not e.enregistre),
        f"les durées sont les CONSTANTES du protocole ({[e.duree_s for e in etapes]})")
    chk(rt0.total() == 2 and abs(rt0.duree_estimee_s() - (15.0 + 3.0 + 8.0 + 3.0 + 8.0)) < 1e-9,
        f"deux fenêtres prélevées, ≈ {rt0.duree_estimee_s():.0f} s vécues (chauffe comprise)")

    # === Le cas NOMINAL : on a POSÉ l'alpha, on doit le retrouver ============================
    rng = np.random.default_rng(20260909)
    rt, res = _jouer(_bruit(rng), _bruit_plus_alpha(rng, 10.5, gain=4.0))
    chk(rt.phase == "fini" and res is not None,
        f"la séance se termine ({rt.phase}, problème={rt.probleme!r})")
    chk(res["ratio"] > RATIO_MIN,
        f"l'alpha monte à la fermeture des yeux : ratio {res['ratio']:.2f} "
        f"(repère > ~{RATIO_MIN:g})")
    chk(abs(res["pic_hz"] - 10.5) < 1.0,
        f"…et le pic est trouvé là où on l'a mis ({res['pic_hz']:.1f} Hz pour 10,5)")
    chk(res["barriere_franchie"] is True, "la barrière est franchie")
    chk("séance peut commencer" in res["verdict"] and f"{res['ratio']:.2f}" in res["verdict"],
        f"…et le verdict le DIT, avec son chiffre ({res['verdict'][:60]}…)")
    chk(res["voies"] == VOIES and "Pz" in res["voies"],
        f"les voies moyennées sont NOMMÉES par le moteur, pas devinées par l'écran — et Pz en "
        f"fait partie, contrairement à ce qu'annonçait l'écran d'origine ({res['voies']})")

    # LA BOUCLE QUE LA RECETTE FAIT FAIRE À LA MAIN : noter le pic, le retaper dans « Pic alpha ».
    propose = res["reglage_propose"]
    chk(propose and propose["mode"] == "ssvep" and propose["cle"] == "alpha_hz"
        and propose["valeur"] == res["pic_hz"],
        f"le résultat PORTE le réglage à appliquer — mode, clé et valeur — pour que la console "
        f"n'ait ni « ssvep » ni « alpha_hz » écrit dans son propre code ({propose})")
    chk(propose and propose["label"] == PARAM_CIBLE.label,
        f"…avec le libellé EXACT du champ que l'étudiant retrouvera sur la page du SSVEP "
        f"({propose['label']!r}) — lu dans le contrat du mode, pas réécrit ici")

    # === Le cas qui ARRÊTE la séance : pas d'alpha du tout ===================================
    plat_rt, plat = _jouer(_bruit(rng), _bruit(rng))
    chk(plat["barriere_franchie"] is False,
        f"sans montée d'alpha, la barrière n'est PAS franchie (ratio {plat['ratio']:.2f})")
    chk("arrête" in plat["verdict"].lower() and "électrodes" in plat["verdict"].lower(),
        f"…et le verdict dit d'ARRÊTER et quoi vérifier, il ne rend pas qu'un chiffre "
        f"({plat['verdict'][:70]}…)")
    chk("mastoïdes" in plat["verdict"].lower() and "saline" in plat["verdict"].lower(),
        "…en nommant les TROIS gestes : occipitales, mastoïdes, saline")
    chk(plat["reglage_propose"] is None,
        f"…et RIEN n'est proposé à appliquer : sur un signal sans alpha, le « pic » est le plus "
        f"grand bin d'un spectre de bruit ({plat['pic_hz']} Hz ici). Le proposer d'un clic serait "
        f"pire que le carnet qu'on remplace — une valeur fausse, sans l'hésitation qui va avec")
    chk(plat_rt.phase == "fini",
        f"une barrière non franchie est une mesure RÉUSSIE qui rend un verdict négatif, pas une "
        f"séance en échec ({plat_rt.phase}) — sinon l'écran afficherait « mesure abandonnée » et "
        f"cacherait ce qu'il faut lire")

    # === Le second critère, celui qu'on oublie : ça monte, mais ce n'est pas de l'alpha =======
    # 7,5 Hz est DANS la plage de recherche (6-14) et HORS de la plage attendue (8-12,5) : c'est
    # la forme d'une dérive lente ou d'un artefact de mouvement. Il tombe à un bin de la bande
    # alpha, donc le lobe principal de la fenêtre de Hann y fuit largement : le ratio 8-12 Hz
    # monte à ~9 et le seul critère de ratio déclarerait « montage bon ». C'est précisément le
    # cas que le second critère existe pour attraper.
    _rt, lent = _jouer(_bruit(rng), _bruit_plus_alpha(rng, 7.5, gain=15.0))
    chk(lent["ratio"] > RATIO_MIN and lent["barriere_franchie"] is False,
        f"un pic HORS de la plage de l'alpha ne franchit pas la barrière, même avec un ratio de "
        f"{lent['ratio']:.2f} — le ratio seul ne dit pas que c'est de l'alpha")
    chk("arrête" in lent["verdict"].lower() and f"{lent['pic_hz']:.1f}" in lent["verdict"],
        f"…et le verdict nomme le pic fautif ({lent['verdict'][:70]}…)")

    # === L'OFFSET DC de l'Unicorn : 10⁵ µV, et le verdict ne doit pas bouger ==================
    # Mesuré sur ce casque le 2026-07-27. Sans détrend, il fuit à travers la fenêtre de Hann
    # jusque dans la bande alpha, où il domine l'EEG de plusieurs ordres de grandeur : les deux
    # phases se ressemblent alors, le ratio tombe vers 1, et TOUTE séance échoue à la barrière —
    # y compris celles où le casque est parfait.
    rng2 = np.random.default_rng(20260909)
    ouvert_dc = _bruit(rng2) + 1e5
    ferme_dc = _bruit_plus_alpha(rng2, 10.5, gain=4.0) + 1e5
    _rt, avec_dc = _jouer(ouvert_dc, ferme_dc)
    chk(avec_dc["barriere_franchie"] is True
        and abs(avec_dc["ratio"] - res["ratio"]) < 0.05 * res["ratio"],
        f"un offset DC de 10⁵ µV ne change pas le verdict ({avec_dc['ratio']:.2f} contre "
        f"{res['ratio']:.2f} sans lui) — c'est le détrend qui tient ça, et rien d'autre")

    # === Une phase manquante : un refus lisible, pas un chiffre calculé sur une moitié ========
    rt5 = ControleAlpha(SPEC, {}, None)
    try:
        rt5._mesurer([(np.zeros((N, len(CH_NAMES))), OUVERT)], FS)
        chk(False, "un protocole amputé d'une phase doit être REFUSÉ")
    except ValueError as e:
        chk(FERME in str(e) and "DEUX termes" in str(e),
            f"…en nommant la phase absente et pourquoi elle est indispensable ({str(e)[:60]}…)")

    # === LA LIAISON MORTE : quatre voies plates ne rendent PAS un verdict =====================
    # ⚠️ Le piège, et il est vicieux : sur des voies plates la puissance vaut ~10⁻²⁷ des deux
    # côtés, donc le rapport est du bruit d'arrondi. Mesuré sur cette implémentation, il vaut
    # 0,3 ou 4,1 selon les derniers bits — donc il FRANCHIT la barrière une fois sur deux, et
    # l'écran annonce « le montage est bon » sur un câble débranché. C'est exactement le défaut
    # qui a laissé enregistrer 3,4 min de vide le 2026-07-20.
    plat_signal = np.zeros((N, len(CH_NAMES)))
    try:
        rt5._mesurer([(plat_signal, OUVERT), (plat_signal, FERME)], FS)
        chk(False, "quatre voies PLATES doivent être refusées, pas transformées en ratio")
    except ValueError as e:
        chk("PLATES" in str(e) and "liaison" in str(e) and f"{SIGNAL_DEAD_SIGMA:g}" in str(e),
            f"…en disant que c'est une panne de liaison, au seuil de voie morte que le moteur "
            f"applique déjà à ses huit voies ({str(e)[:70]}…)")

    # === Le contrat public de la mesure ======================================================
    chk(SPEC.id == "alpha" and SPEC.runtime_cls is ControleAlpha and SPEC.barriere is True,
        f"la mesure est déclarée BARRIÈRE — c'est ce champ que l'écran lit pour dire « arrête » "
        f"au lieu de « note ce chiffre » ({SPEC.barriere})")
    # ⚠️ Par IDENTIFIANT, pas par `SPEC in registry.MESURES` : lancé en autotest, ce fichier est
    # `__main__` et `registry` importe `core.modes.alpha` — deux modules distincts, donc deux
    # classes `ControleAlpha` distinctes, donc une égalité de dataclass qui échoue alors que le
    # catalogue est parfaitement correct.
    # ⚠️ La PREMIÈRE du catalogue, et pas « la seule » : le taux SSVEP s'y est ajouté le
    # 2026-09-09, et une égalité de liste aurait fait rougir cette assertion à chaque mesure
    # nouvelle — un rouge qui ne dit rien sur l'alpha. Ce qui compte VRAIMENT ici est le rang :
    # l'alpha est la barrière d'entrée, l'écran range les tuiles dans cet ordre, et une mesure
    # jouée avant elle rendrait un chiffre qui décrit le montage plutôt que le décodage.
    ids_mesures = [s.id for s in registry.MESURES]
    chk(ids_mesures and ids_mesures[0] == "alpha",
        f"…et elle ouvre le catalogue du moteur : sans ça, `start_mesure` ne l'atteindrait "
        f"pas et aucune tuile n'existerait — et le rang dit que la barrière passe EN PREMIER "
        f"({ids_mesures})")
    sain, defauts = registry.check()
    chk(sain and not defauts, f"le registre reste sain avec elle ({defauts})")
    chk(SPEC.params == (),
        "aucun réglage : les durées et les bandes forment un tout avec le repère 1,5, et les "
        "exposer laisserait l'invalider en croyant gagner du temps")

    # Le pic rendu est DIRECTEMENT la valeur du réglage « Pic alpha » du SSVEP — c'est ce qui
    # permet à l'écran de le renvoyer au moteur d'un clic au lieu de le faire recopier à la main.
    from core.modes.ssvep import SPEC as SPEC_SSVEP

    alpha_param = next(p for p in SPEC_SSVEP.params if p.key == "alpha_hz")
    chk(alpha_param.min <= BANDE_PIC[0] and BANDE_PIC[1] <= alpha_param.max,
        f"la plage de recherche du pic ({BANDE_PIC}) tient dans les bornes du réglage "
        f"« {alpha_param.label} » ([{alpha_param.min:g} ; {alpha_param.max:g}]) : tout pic "
        f"mesurable est donc APPLICABLE, et le bouton de l'écran ne peut pas proposer une valeur "
        f"que le moteur refusera")

    chk(empreinte_dossier(DATA_DIR) == empreinte_avant,
        "et tout ce test n'a rien écrit dans `data/` — une mesure ne produit aucun fichier")

    print(f"[alpha] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


if __name__ == "__main__":
    use_utf8_console()
    _sys.exit(0 if _selftest() else 1)
