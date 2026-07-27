"""Tableau de bord web du moteur — l'interface de contrôle décidée en SPEC §12.2.

Le moteur tourne sans interface ; celle-ci en est un CLIENT, servi en local. L'étudiant
ouvre une page dans son navigateur : rien à installer de plus, une techno qu'il sait déjà
modifier, et l'encadrant peut suivre la qualité du signal depuis un autre poste pendant que
l'élève porte le casque.

Trois pièces, et la frontière entre elles compte :
  - le MOTEUR tourne dans son propre thread et possède seul la session BrainFlow ;
  - les commandes du navigateur ne touchent PAS le moteur : elles passent par son API de
    commande interne (`submit`), qui les met en file pour que la boucle les applique
    elle-même. C'est le même chemin que prendra l'adaptateur de commandes LSL (SPEC §12.1) ;
  - la page est un fichier séparé (`dashboard.html`), pour qu'un étudiant l'édite sans
    ouvrir une ligne de Python.

⚠️ Le stimulus reste NATIF (`src/research/ssvep_stimulus.py`) : un navigateur ne garantit pas le
timing d'un clignotement à la frame. Il y a donc deux fenêtres, et c'est inhérent à la
contrainte temporelle, pas au choix du web.

Lancer :
    python src/core/dashboard.py --synthetic       # sans casque
    python src/core/dashboard.py --mode ssvep --refresh 60
    python src/core/dashboard.py --host 0.0.0.0    # suivi depuis un autre poste
    python src/core/dashboard.py --smoke           # test headless de bout en bout (CI)
"""

import argparse
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import use_utf8_console  # noqa: E402
from core.server import EngineServer  # noqa: E402

HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")


def build_app(engine):
    """Construit l'application web autour d'un moteur DÉJÀ démarré."""
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, JSONResponse

    app = FastAPI(title="EEG_API_Unicorn", docs_url="/docs")

    @app.get("/", include_in_schema=False)
    def page():
        # Relu à chaque requête : un étudiant qui édite le HTML rafraîchit et voit son
        # changement, sans redémarrer le moteur ni rouvrir la session casque.
        return FileResponse(HTML_PATH, media_type="text/html")

    @app.get("/api/state")
    def state():
        """État complet du moteur. Sondé par la page ~4×/s."""
        return JSONResponse(engine.snapshot())

    @app.post("/api/command")
    async def command(payload: dict):
        """Commande vers le moteur. Répond un ACCUSÉ, pas un résultat.

        La commande est appliquée par la boucle du moteur, pas ici : le résultat s'observe
        sur `/api/state`, exactement comme un client LSL l'observerait sur le flux `status`.
        Les deux chemins de contrôle se comportent donc pareil, ce qui évite qu'une
        interface prenne l'habitude d'un confort que l'autre n'offre pas.
        """
        name = payload.pop("command", None)
        return JSONResponse(engine.submit(name, **payload))

    return app


def run(args):
    engine = EngineServer(serial=args.serial, synthetic=args.synthetic, verbose=args.verbose,
                          mode=args.mode, refresh=args.refresh, instance=args.instance,
                          freqs=[float(f) for f in args.freqs.split(",")] if args.freqs else None)
    thread = threading.Thread(target=engine.run, daemon=True)
    thread.start()

    import uvicorn
    print(f"[dashboard] ouvre http://{'localhost' if args.host == '127.0.0.1' else args.host}"
          f":{args.port}   (documentation de l'API : /docs)")
    try:
        uvicorn.run(build_app(engine), host=args.host, port=args.port, log_level="warning")
    finally:
        # Ctrl+C doit fermer PROPREMENT la session BrainFlow, sinon la suivante refuse de
        # s'ouvrir (BOARD_NOT_READY au relancement).
        engine.stop()
        thread.join(timeout=5.0)


def _smoke():
    """Vérifie la chaîne complète sans navigateur : moteur -> API -> page."""
    import json
    import time
    import urllib.request

    engine = EngineServer(synthetic=True)
    thread = threading.Thread(target=engine.run, daemon=True)
    thread.start()

    import uvicorn
    config = uvicorn.Config(build_app(engine), host="127.0.0.1", port=8123, log_level="error")
    server = uvicorn.Server(config)
    web = threading.Thread(target=server.run, daemon=True)
    web.start()

    base, ok = "http://127.0.0.1:8123", True
    for _ in range(50):                      # attendre que le port réponde
        try:
            urllib.request.urlopen(base + "/api/state", timeout=0.5)
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.2)

    try:
        page = urllib.request.urlopen(base + "/", timeout=5).read().decode("utf-8")
        if "EEG_API_Unicorn" not in page:
            print("[smoke] ÉCHEC : la page ne se sert pas")
            ok = False

        state = json.loads(urllib.request.urlopen(base + "/api/state", timeout=5).read())
        for key in ("running", "phase", "channels", "streams", "instance"):
            if key not in state:
                print(f"[smoke] ÉCHEC : '{key}' absent de l'état")
                ok = False
        print(f"[smoke] état servi : phase={state['phase']} mode={state['mode']} "
              f"{len(state['streams'])} flux")

        # Une commande doit être ACCEPTÉE puis APPLIQUÉE par la boucle (pas par le web).
        req = urllib.request.Request(
            base + "/api/command", method="POST",
            data=json.dumps({"command": "set_mode", "mode": "ssvep"}).encode(),
            headers={"Content-Type": "application/json"})
        ack = json.loads(urllib.request.urlopen(req, timeout=5).read())
        if not ack.get("accepted"):
            print(f"[smoke] ÉCHEC : commande refusée ({ack})")
            ok = False

        applied = False
        for _ in range(40):
            time.sleep(0.2)
            state = json.loads(urllib.request.urlopen(base + "/api/state", timeout=5).read())
            if state["mode"] == "ssvep":
                applied = True
                break
        print(f"[smoke] commande appliquée par la boucle : {applied}")
        if not applied:
            print("[smoke] ÉCHEC : le mode n'a pas changé")
            ok = False

        # Changer les fréquences depuis le navigateur : la commande doit être appliquée ET
        # se relire dans l'état, sinon l'étudiant croirait décoder des cibles qu'il n'a pas.
        def post(payload):
            r = urllib.request.Request(
                base + "/api/command", method="POST", data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(r, timeout=5).read())

        ack = post({"command": "set_freqs", "freqs": [12.0, 15.0, 20.0]})
        if not ack.get("accepted"):
            print(f"[smoke] ÉCHEC : set_freqs refusé ({ack.get('reason')})")
            ok = False
        applied = False
        for _ in range(40):
            time.sleep(0.2)
            state = json.loads(urllib.request.urlopen(base + "/api/state", timeout=5).read())
            if [round(f, 2) for f in state.get("frequencies_hz", [])] == [12.0, 15.0, 20.0]:
                applied = True
                break
        print(f"[smoke] fréquences changées depuis l'API : {applied}")
        if not applied:
            print("[smoke] ÉCHEC : les fréquences n'ont pas changé dans l'état")
            ok = False

        # Un jeu de fréquences inexploitable doit être refusé AVEC SA RAISON, pas accepté
        # puis décodé dans le vide (le mode de panne le plus coûteux du SSVEP).
        for payload, attendu in (
                ({"command": "set_freqs", "freqs": [15.0, 60.0]}, "hors bande passante"),
                ({"command": "set_freqs", "freqs": [15.0, 15.2]}, "trop proches"),
                ({"command": "set_freqs", "freqs": [15.0]}, "au moins 2")):
            ack = post(payload)
            if ack.get("accepted") or attendu not in ack.get("reason", ""):
                print(f"[smoke] ÉCHEC : {payload['freqs']} mal refusé -> {ack}")
                ok = False
            else:
                print(f"[smoke] {payload['freqs']} refusé : {ack['reason'][:60]}...")

        # Une commande inconnue doit être refusée proprement, pas planter le moteur.
        req = urllib.request.Request(
            base + "/api/command", method="POST",
            data=json.dumps({"command": "self_destruct"}).encode(),
            headers={"Content-Type": "application/json"})
        ack = json.loads(urllib.request.urlopen(req, timeout=5).read())
        if ack.get("accepted"):
            print("[smoke] ÉCHEC : commande inconnue acceptée")
            ok = False
        else:
            print(f"[smoke] commande inconnue refusée : {ack['reason']}")

        # La qualité doit finir par apparaître (le tampon met ~3 s à se remplir).
        for _ in range(40):
            state = json.loads(urllib.request.urlopen(base + "/api/state", timeout=5).read())
            if state.get("quality"):
                break
            time.sleep(0.2)
        if not state.get("quality"):
            print("[smoke] ÉCHEC : aucune mesure de qualité dans l'état")
            ok = False
        else:
            q = state["quality"]
            print(f"[smoke] qualité : {len(q['sigmas'])} voies, "
                  f"corrélation {q['common_mode']}, référence perdue={q['reference_lost']}")
    finally:
        engine.stop()
        server.should_exit = True

    print(f"[smoke] VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return ok


def _parse_args(argv):
    p = argparse.ArgumentParser(description="EEG_API_Unicorn — tableau de bord web local.")
    p.add_argument("--synthetic", action="store_true", help="board de test BrainFlow (sans casque)")
    p.add_argument("--serial", default=None, help="numéro de série Unicorn")
    p.add_argument("--mode", choices=["ssvep"], default=None, help="décodeur au démarrage")
    p.add_argument("--freqs", default=None, help="fréquences des cibles, ex. 15,20,8.57")
    p.add_argument("--refresh", type=float, default=None, help="refresh de l'écran du stimulus")
    p.add_argument("--id", dest="instance", default=None, help="identité de cette instance")
    p.add_argument("--host", default="127.0.0.1",
                   help="0.0.0.0 pour suivre depuis un autre poste (SPEC §12.2)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--smoke", action="store_true", help="test headless de bout en bout, puis quitte")
    p.add_argument("--verbose", action="store_true", help="logs BrainFlow détaillés")
    return p.parse_args(argv)


if __name__ == "__main__":
    use_utf8_console()
    args = _parse_args(sys.argv[1:])
    sys.exit(0 if _smoke() else 1) if args.smoke else run(args)
