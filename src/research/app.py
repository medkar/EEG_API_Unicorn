"""Application EEG_API_Unicorn : le menu pygame, réduit à son dernier mode.

    python src/research/app.py                 # plein écran, casque réel
    python src/research/app.py --windowed      # fenêtre (pour garder la console à côté)
    python src/research/app.py --synthetic     # sans casque (board de test BrainFlow)
    python src/research/app.py --smoke         # test headless (CI)

⚠️ **Ce fichier est en cours de RETRAIT** (chantier « la console, seul point d'entrée »,
2026-09-08). Les cinq modes qu'il portait ont tous quitté cette appli :

  - SSVEP, P300, ErrP : leur écran de PILOTAGE est archivé, encore exécutable, dans `archive/`
    (`ssvep_pilot.py`, `p300_pilot.py`, `errp_demo.py`) ; le décodage est publié par le moteur et
    se pilote depuis la console.
  - les trois CALIBRATIONS pygame (c-VEP, P300, ErrP) sont archivées elles aussi
    (`archive/*_calibrate.py`) : le moteur calibre désormais, et la console fait JUGER le modèle
    avant de l'enregistrer — ce que ces écrans-là court-circuitaient en écrivant droit dans `data/`.
  - le c-VEP et le Motor Imagery avaient déjà quitté le pilotage lors des chantiers précédents.

Ne reste ici que le NEURO-MONITORING passif, dont la console a désormais son propre histogramme
(tâche 9) : ce fichier disparaît au commit suivant. Voir `archive/README.md`.
"""

import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import (DATA_DIR, empreinte_dossier, NEURO_BASELINE_S,  # noqa: E402
                    NEURO_KEY_CHANNELS, NEURO_UPDATE_HZ, NEURO_WARMUP_S,
                    NEURO_WINDOW_S, NEURO_Z_SPAN, UDP_HOST, use_utf8_console)
from core.neuro_monitor import INDEX_DESCRIPTIONS, INDEX_KEYS, IndexNormalizer, NeuroDecoder  # noqa: E402
from research.ui import (ACCENT, BAR_BG, BG, DIM, FG, GO, OUTLINE,  # noqa: E402
                         WARN, Abort, App)


# BCI PASSIF : rien n'est envoyé au robot. On mesure des indices spectraux (θ/α/β) et on les
# affiche en HISTOGRAMME temps réel, normalisés en z contre un repos mesuré à l'entrée du mode.
# Voir neuro_monitor.py pour les formules et leur limite (indices corrélés, dérivants). Pas de
# thread de décodage/émission : sans stimulus clignotant, le calcul (PSD ~ms) tient dans la boucle.

# (clé, libellé, formule courte, couleur, sens de la montée)
# ⚠️ Les TEXTES viennent du moteur (`core.neuro_monitor.INDEX_DESCRIPTIONS`) depuis le 2026-09-08 :
# ils étaient écrits ici, et la console — l'autre écran du même produit — n'en avait aucun, elle
# affichait la clé brute « charge ». Seule la COULEUR reste locale : c'est de la présentation, et
# les deux interfaces n'ont pas les mêmes.
_NEURO_COULEURS = {"charge": ACCENT, "somnolence": WARN, "engagement": GO}
_NEURO_VIEW = [(cle, *INDEX_DESCRIPTIONS[cle][:2],
                _NEURO_COULEURS[cle], INDEX_DESCRIPTIONS[cle][2])
               for cle in INDEX_KEYS]


def _neuro_sample(app, decoder):
    """Une fenêtre BRUTE (n, 8) -> échantillon du décodeur, ou None si le buffer n'est pas prêt.

    Le calcul lui-même vit dans `core.neuro_monitor.NeuroDecoder`, partagé avec le moteur : ce
    mode s'affiche ici ET se publie sur le réseau, et deux copies du même calcul finiraient par
    diverger — l'écran montrerait une charge mentale, le flux LSL une autre."""
    return decoder.sample(app.acq.get_epoch(NEURO_WINDOW_S, filtered=False))


def _neuro_warmup(app, seconds):
    """Écran de stabilisation JETÉ avant le repos : laisse les électrodes sèches se poser (le settling
    d'impédance fausserait le repos et ferait dériver le zéro, cf. eeg-hardware piège #0ter)."""
    if seconds <= 0:
        return
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        app.drain()
        left = seconds - (time.perf_counter() - t0)
        app.win.fill(BG)
        h = app.size[1]
        app.center(app.big, "Stabilisation du casque...", FG, int(h * 0.40))
        app.center(app.mid, "on laisse les électrodes se poser avant de mesurer le repos",
                   DIM, int(h * 0.50))
        app.center(app.big, f"{int(left) + 1}", WARN, int(h * 0.62))
        app.pygame.display.flip()
        app.clock.tick(30)
        if app.smoke:
            return


def _neuro_baseline(app, decoder, seconds):
    """Repos yeux ouverts (précédé d'un warm-up jeté) : cale les échelles du jour sur `decoder`.

    Retourne True si le plancher a pu être mesuré."""
    _neuro_warmup(app, NEURO_WARMUP_S)
    t0, last, samples = time.perf_counter(), 0.0, []
    while True:
        app.drain()                          # ESC -> Abort -> retour menu (absorbé par _mode_page)
        now = time.perf_counter()
        left = seconds - (now - t0)
        if left <= 0:
            break
        if now - last >= 1.0 / NEURO_UPDATE_HZ:
            last = now
            s = _neuro_sample(app, decoder)
            if s is not None:
                samples.append(s)
        app.win.fill(BG)
        h = app.size[1]
        app.center(app.big, "REPOS — regarde l'écran, détends-toi", FG, int(h * 0.30))
        app.center(app.mid, "calage des échelles sur TON repos du jour (yeux ouverts, immobile)",
                   DIM, int(h * 0.40))
        app.center(app.small, f"{len(samples)} fenêtres", DIM, int(h * 0.47))
        app.center(app.big, f"{int(left) + 1}", WARN, int(h * 0.64))
        app.pygame.display.flip()
        app.clock.tick(30)
        if app.smoke and (len(samples) >= 3 or time.perf_counter() - t0 > 1.0):
            break
    if not decoder.fit_baseline(samples):
        return False
    print("[neuro] repos %d fenêtres — %s  σ_ref(moy)=%.0f  emg_ref=%.2f" % (
        len(samples), "  ".join(f"{k}:μ≈{decoder.norm.center(k):.2f}" for k in decoder.norm.mu),
        float(np.mean(decoder.sigma_ref)), decoder.emg_ref))
    return True


def _neuro_bars(app, z, artifact, arts, reason):
    """Histogramme : 3 barres verticales divergentes autour d'une ligne « repos » (z=0). Une barre
    qui monte = indice au-dessus du repos, qui descend (grise) = en dessous."""
    pg = app.pygame
    w, h = app.size
    app.win.fill(BG)
    app.center(app.big, "Neuro-monitoring passif", FG, int(h * 0.08))
    app.center(app.small, "indices relatifs à TON repos (z) — une TENDANCE, pas une mesure absolue",
               DIM, int(h * 0.14))
    y_top, y_bot = int(h * 0.26), int(h * 0.70)
    y_mid = (y_top + y_bot) // 2
    half = y_mid - y_top
    barw = int(w * 0.09)
    pg.draw.line(app.win, OUTLINE, (int(w * 0.14), y_mid), (int(w * 0.86), y_mid), 1)
    app.win.blit(app.small.render("repos (0)", True, DIM), (int(w * 0.05), y_mid - 8))
    for i, (key, label, formula, col, sense) in enumerate(_NEURO_VIEW):
        cx = int(w * (0.28 + 0.22 * i))
        pg.draw.rect(app.win, BAR_BG, (cx - barw // 2, y_top, barw, y_bot - y_top))
        zi = float(z.get(key, 0.0))
        frac = float(np.tanh(zi / NEURO_Z_SPAN))   # compression douce : pas de plafond brutal
        bh = int(abs(frac) * half)
        if frac >= 0:
            pg.draw.rect(app.win, col, (cx - barw // 2, y_mid - bh, barw, bh))
        else:
            pg.draw.rect(app.win, DIM, (cx - barw // 2, y_mid, barw, bh))
        for dy, font, text, c in ((0.055, app.mid, label, FG),
                                  (0.10, app.small, formula, DIM),
                                  (0.135, app.small, sense, DIM),
                                  (0.185, app.mid, f"z={zi:+.1f}", col)):
            s = font.render(text, True, c)
            app.win.blit(s, s.get_rect(center=(cx, y_bot + int(h * dy))))
    if artifact:
        app.center(app.mid, f"ARTEFACT ({reason}) — fenêtre ignorée", WARN, int(h * 0.20))
    app.hud(f"Neuro-monitoring PASSIF (aucun envoi robot)   artefacts ignorés={arts}   ESC=menu", DIM)


def _neuro_live(app, decoder):
    """Boucle d'affichage : recalcule les indices à NEURO_UPDATE_HZ et dessine l'histogramme.

    Le veto d'artefact, la normalisation et le re-calage lent du zéro sont dans le décodeur
    partagé — ici il ne reste que le rythme, l'affichage et le journal."""
    z = {k: 0.0 for k, *_ in _NEURO_VIEW}
    last, artifact, reason, frame, last_log = 0.0, False, "", 0, 0.0
    while True:
        app.drain()
        now = time.perf_counter()
        if now - last >= 1.0 / NEURO_UPDATE_HZ:
            last = now
            s = _neuro_sample(app, decoder)
            if s is not None:
                out = decoder.step(s)
                z, artifact, reason = out["z"], out["artifact"], out["reason"]
                if now - last_log >= 1.0:           # diagnostic : brut vs normalisé, ~1×/s
                    last_log = now
                    keys = [k for k, *_ in _NEURO_VIEW]
                    print("[neuro] brut " +
                          "  ".join(f"{k}={s['idx'][k]:.3f}" for k in keys) +
                          "  z " + "  ".join(f"{k}={z[k]:+.2f}" for k in keys) +
                          f"  centre_eng≈{decoder.norm.center('engagement'):.3f}"
                          f"  artefacts={decoder.artifacts}" + (f"  ({reason})" if artifact else ""))
        _neuro_bars(app, z, artifact, decoder.artifacts, reason)
        app.pygame.display.flip()
        app.clock.tick(30)
        frame += 1
        if app.smoke and frame >= 40:
            return


def mode_neuro(app):
    """Mode 4 : histogramme temps réel de 3 indices d'état mental. PASSIF (aucune commande robot).

    Déroulé : contrôle liaison (Fz/Pz encadrées) -> warm-up jeté -> repos yeux ouverts (cale les
    échelles z du jour) -> histogramme live jusqu'à ESC (z re-calé lentement contre la dérive)."""
    if not app.signal_check(highlight=NEURO_KEY_CHANNELS, mode_label="Neuro-monitoring"):
        return                    # liaison + voies clés (Fz/Pz) ; casque KO ou ESC -> retour
    print(f"[neuro] fenêtre PSD {NEURO_WINDOW_S}s  maj {NEURO_UPDATE_HZ:.0f}Hz  "
          f"warm-up {NEURO_WARMUP_S:.0f}s + repos {NEURO_BASELINE_S:.0f}s  (passif — aucun envoi robot)")
    decoder = NeuroDecoder(app.acq.fs)
    if not _neuro_baseline(app, decoder, NEURO_BASELINE_S):
        if app.smoke:             # pas de vraies données en headless -> normaliseur neutre
            decoder.norm = IndexNormalizer.identity([k for k, *_ in _NEURO_VIEW])
        else:
            app.flash("Repos trop court",
                      "pas assez de fenêtres pour caler les échelles — réessaie", 3.0)
            return
    _neuro_live(app, decoder)

# --- Navigation (menus aux FLÈCHES + SOURIS, retour ←/Échap) ----------------

def _status(app):
    casque = "board SYNTHÉTIQUE" if app.synthetic else "Unicorn"
    return [f"casque : {casque}    écran : {app.refresh:.0f} Hz",
            "modes SSVEP / c-VEP / P300 / ErrP : moteur + console (`src/console/app.py`)"]


def _check_signal(app):
    """Contrôle de la liaison casque (hotkey C de l'accueil). Échap y lève Abort : on l'absorbe
    pour revenir à l'accueil au lieu de quitter l'appli."""
    try:
        app.signal_check()
    except Abort:
        pass


def _navigate(app, title, options, subtitle=None, allow_back=True,
              status_fn=None, hotkeys=None):
    """Menu vertical, navigable au CLAVIER (↑↓ + Entrée/→) ET à la SOURIS (survol = surligne,
    clic = valide ; clic sur « ⟵ Retour » = reculer). Retourne l'index choisi, ou None pour
    reculer (←/Échap/clic Retour) — sur l'accueil (allow_back=False), None = quitter.

    `options` : liste de (label, description). `status_fn` : callable -> lignes d'état affichées
    sous le titre (recalculées chaque frame). `hotkeys` : {char: fn(app)} exécuté sans quitter
    (R robot, C liaison). La souris est VISIBLE dans les menus et RECACHÉE à la sortie : un
    curseur ne doit pas rester sur les cibles pendant un stimulus.
    """
    pg = app.pygame
    pg.mouse.set_visible(True)
    sel = 0
    w, h = app.size
    many = len(options) > 4          # >4 modes : on resserre pour ne pas mordre sur le bas d'écran
    oy0 = int(h * (0.36 if many else 0.42))
    ody = int(h * (0.105 if many else 0.12))
    back_y = int(h * 0.85)

    def option_at(pos):
        if abs(pos[0] - w / 2) > w * 0.42:
            return None
        for i in range(len(options)):
            if abs(pos[1] - (oy0 + i * ody)) <= ody * 0.5:
                return i
        return None

    def on_back(pos):
        return (allow_back and abs(pos[1] - back_y) <= int(h * 0.03)
                and abs(pos[0] - w / 2) <= w * 0.25)

    def leave(v):
        pg.mouse.set_visible(False)
        return v

    while True:
        for e in pg.event.get():
            if e.type == pg.QUIT:
                return leave(None)
            if e.type == pg.KEYDOWN:
                if e.key == pg.K_ESCAPE:
                    return leave(None)
                if allow_back and e.key in (pg.K_LEFT, pg.K_BACKSPACE):
                    return leave(None)
                if e.key in (pg.K_UP, pg.K_w):
                    sel = (sel - 1) % len(options)
                elif e.key in (pg.K_DOWN, pg.K_s):
                    sel = (sel + 1) % len(options)
                elif e.key in (pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE, pg.K_RIGHT):
                    return leave(sel)
                elif hotkeys and e.unicode and e.unicode.lower() in hotkeys:
                    hotkeys[e.unicode.lower()](app)
            elif e.type == pg.MOUSEMOTION:
                i = option_at(e.pos)
                if i is not None:
                    sel = i
            elif e.type == pg.MOUSEBUTTONDOWN and e.button == 1:
                i = option_at(e.pos)
                if i is not None:
                    return leave(i)
                if on_back(e.pos):
                    return leave(None)

        app.win.fill(BG)
        app.center(app.big, title, FG, int(h * 0.12))
        yy = int(h * 0.20)
        if subtitle:
            app.center(app.small, subtitle, DIM, yy)
            yy += int(h * 0.04)
        if status_fn:
            for line in status_fn():
                app.center(app.small, line, WARN if "ON ->" in line else DIM, yy)
                yy += int(h * 0.035)
        for i, (label, desc) in enumerate(options):
            act = i == sel
            cy = oy0 + i * ody
            app.center(app.mid, f"{'>  ' if act else '    '}{label}", ACCENT if act else FG, cy)
            app.center(app.small, desc, DIM, cy + int(h * 0.036))
        if allow_back:
            app.center(app.mid, "<-  Retour", ACCENT, back_y)
            app.center(app.small, "<-  ou  Échap", DIM, back_y + int(h * 0.035))
            app.center(app.small, "Flèches / souris : naviguer       Entrée / clic : valider",
                       DIM, int(h * 0.93))
        else:
            app.center(app.small, "[R] armer/désarmer robot        [C] vérifier la liaison casque",
                       DIM, int(h * 0.87))
            app.center(app.small,
                       "Flèches / souris : naviguer    ·    Entrée / clic : valider    ·    Échap : quitter",
                       ACCENT, int(h * 0.93))
        pg.display.flip()
        app.clock.tick(60)
        if app.smoke:
            return leave(None)


def _mode_page(app, title, live_fn, calib_fn=None, live_desc="", calib_desc=""):
    """Page d'un mode : « Lancer le live » et (si dispo) « Calibrer ». Boucle jusqu'au retour
    (←/Échap) ; après un live ou une calibration, on revient sur cette page."""
    while True:
        options = [("Lancer le live", live_desc or "démarre le décodage en direct")]
        if calib_fn is not None:
            options.append(("Calibrer", calib_desc or "enregistre puis entraîne le modèle"))
        sub = None if calib_fn else "Ce mode ne nécessite aucune calibration"
        idx = _navigate(app, title, options, subtitle=sub)
        if idx is None:
            return
        try:                       # Échap dans le contrôle de liaison (Abort) -> revient ICI
            if idx == 0:
                live_fn(app)
            elif idx == 1 and calib_fn is not None:
                calib_fn(app)
        except Abort:
            pass
        if app.smoke:
            return


def home(app):
    """Accueil : le mode qui reste. Retourne 'neuro', ou None pour quitter."""
    modes = [("Neuro-monitoring",
              "état mental passif (charge / somnolence / engagement) — histogramme")]
    idx = _navigate(app, "EEG_API_Unicorn — choisis un mode", modes, allow_back=False,
                    status_fn=lambda: _status(app),
                    hotkeys={"c": _check_signal})
    return None if idx is None else "neuro"


PAGES = {
    "neuro": lambda app: _mode_page(app, "Neuro-monitoring passif", mode_neuro, None,
                                    "3 indices spectraux en histogramme"),
}


def main(windowed=False, synthetic=False, send=False, smoke=False, host=UDP_HOST):
    app = App(windowed=windowed, synthetic=synthetic, smoke=smoke, send=send, host=host)
    print(f"[app] écran {app.refresh:.0f} Hz  casque={'synthétique' if app.synthetic else 'Unicorn'}")
    try:
        if smoke:   # exerce le mode restant + la navigation, sans interaction
            _smoke(app)
        else:
            while True:
                choice = home(app)         # accueil : Échap = quitter
                if choice is None:
                    break
                try:
                    PAGES[choice](app)     # page du mode ; ←/Échap = retour à l'accueil
                except Abort:
                    pass                   # filet : un mode ne doit pas laisser fuir Abort
    finally:
        app.close()
    return True


def _smoke(app):
    """Câblage de bout en bout, headless : le menu et le seul mode qui reste.

    ⚠️ Les tests des modes RETIRÉS ont déménagé AVEC eux, dans le `--smoke` de chaque fichier de
    `archive/` : les deux invariants de nom de modèle P300 et ErrP, l'invariant oddball, les trois
    défauts d'écriture du c-VEP, et le contrôle « aucun modèle chargeable » du démonstrateur ErrP.
    Ce qui reste ici n'a besoin d'aucun d'eux : le neuro-monitoring n'écrit rien.
    """
    empreinte_avant = empreinte_dossier(DATA_DIR)
    home(app)                 # accueil (rend + retour immédiat en smoke)
    mode_neuro(app)           # neuro-monitoring passif (repos + histogramme headless)
    _mode_page(app, "Neuro-monitoring passif", mode_neuro, None)   # la page qui y mène
    # `data/` est RESSORTI INTACT. Le neuro n'écrit rien, donc cette assertion devrait être
    # triviale — c'est exactement pourquoi elle est bon marché à garder : elle rougirait le jour
    # où quelqu'un ajoute un journal ici, sur un dossier qui porte des enregistrements EEG d'une
    # personne identifiable dans un dépôt public.
    empreinte_apres = empreinte_dossier(DATA_DIR)
    bouges = sorted(set(empreinte_avant) ^ set(empreinte_apres)) + \
        sorted(n for n in set(empreinte_avant) & set(empreinte_apres)
               if empreinte_avant[n] != empreinte_apres[n])
    assert not bouges, f"le smoke a touché data/ : {bouges}. Aucun test ne doit y écrire."
    print("[app] smoke OK : menu + neuro-monitoring câblés (headless).")


def _parse(argv):
    p = argparse.ArgumentParser(description="Application EEG_API_Unicorn (neuro-monitoring).")
    p.add_argument("--windowed", action="store_true", help="fenêtre au lieu du plein écran")
    p.add_argument("--synthetic", action="store_true", help="board de test (sans casque)")
    p.add_argument("--smoke", action="store_true", help="test headless (CI)")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    a = _parse(sys.argv[1:])
    main(windowed=a.windowed, synthetic=a.synthetic, smoke=a.smoke)
