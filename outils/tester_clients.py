"""Vérifie les applications prêtes à l'emploi d'EEG_API_Unicorn_Applications/ : chaque exemple
contre un VRAI moteur (board de test) quand il tourne ici, sinon sa compilation, et que les copies
d'une même bibliothèque (client/ et exemple/) sont identiques.

    python outils/tester_clients.py            # tout ce que ce poste sait vérifier
    python outils/tester_clients.py --vite     # sans les moteurs (copies et compilations)

⚠️ Comme les autres autotests, il publie sous les noms de flux publics : aucune console ni aucun
moteur ne doit tourner pendant qu'il s'exécute.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "src"))
from core.server import DOSSIER_APPLICATIONS, copies_divergentes  # noqa: E402

APPLICATIONS = os.path.join(RACINE, DOSSIER_APPLICATIONS)

resultats = []


def chk(cond, msg):
    resultats.append(bool(cond))
    print(f"  {'OK  ' if cond else 'ÉCHEC'} {msg}", flush=True)
    return bool(cond)


def moteur(ecoute, **kwargs):
    """Un moteur sur le board de test, dans un fil, avec ses dossiers à lui. Rend (moteur, fil)."""
    from core.server import EngineServer
    tmp = tempfile.mkdtemp(prefix="tester-clients-")
    srv = EngineServer(synthetic=True, modes=("raw",), instance=f"tester-clients-{os.getpid()}",
                       data_dir=os.path.join(tmp, "data"), seances_dir=os.path.join(tmp, "seances"),
                       ecoute=ecoute, **kwargs)
    fil = threading.Thread(target=srv.run, daemon=True, kwargs={"duration_s": 300.0})
    fil.start()
    fin = time.time() + 30
    while not (srv.acquisition_ouverte and srv.pilotage.vivant) and time.time() < fin:
        time.sleep(0.1)
    return srv, fil


def arreter(srv, fil):
    srv.stop()
    fil.join(15)
    srv.retirer_flux()
    srv.close()


def tester_python_lsl():
    """Python/exemple contre le moteur seul (écoute permanente : aucun clic)."""
    print("[clients] Python (LSL)", flush=True)
    dossier = os.path.join(APPLICATIONS, "Python", "exemple")
    sys.path.insert(0, dossier)
    import eeg_api_lsl
    config = eeg_api_lsl.load_config(os.path.join(dossier, "config.json"))
    chk(config["mode"] == "ssvep" and config["propose_refresh_hz"] == 60,
        "config.json se lit, complété par les valeurs par défaut")
    srv, fil = moteur("permanente")
    journal, decisions = [], []
    api = eeg_api_lsl.EegApi(dict(config, app_name="tester-lsl"), log=journal.append)
    try:
        api.connect()
        reponse = api.start()
        chk(reponse.get("accepted") and api.started_here,
            "propose_params, set_params, puis start_mode : acceptés")
        reglages = srv.reglages.get("ssvep") or {}
        chk(float(reglages.get("refresh_hz", 0)) == 60.0 and len(reglages.get("freqs") or ()) == 3
            and list(reglages.get("target_names") or ()) == ["haut", "droite", "gauche"],
            f"le moteur a retenu les réglages de config.json ({reglages.get('freqs')})")
        fin = time.time() + 90
        for decision in api.decisions():
            decisions.append(decision)
            if len(decisions) >= 3 or time.time() > fin:
                break
        chk(len(decisions) >= 3 and "target_index" in decisions[0] and "freq_hz" in decisions[0],
            f"trois décisions, voies par nom ({sorted(decisions[0]) if decisions else 'aucune'})")
        api.close()
        time.sleep(1.0)
        chk("ssvep" not in srv.active, "close() arrête le mode que le client a démarré")
        tester_echec_dans_la_boucle(srv, eeg_api_lsl, config)
    finally:
        arreter(srv, fil)


def tester_echec_dans_la_boucle(srv, eeg_api_lsl, config):
    """Un réglage ACCEPTÉ puis refusé quand la boucle l'applique (le mode tourne déjà) : le moteur
    remet les réglages d'avant et ne le dit que par un second message, « event: failed ». Sans
    lui, l'application croirait ses réglages en vigueur et décoderait sur ceux d'avant."""
    srv.submit("start_mode", ids=["ssvep"])
    fin = time.time() + 10
    while "ssvep" not in srv.active and time.time() < fin:
        time.sleep(0.1)
    original = srv._set_params

    def refuse(*_a, **_k):
        raise RuntimeError("réglage refusé par le runtime (panne simulée)")

    srv._set_params = refuse
    api = eeg_api_lsl.EegApi(dict(config, app_name="tester-lsl-echec"), log=lambda _m: None)
    leve = None
    try:
        api.connect()
        api.start()
    except eeg_api_lsl.EegApiError as e:
        leve = str(e)
    finally:
        srv._set_params = original
        api.close()
        srv.submit("stop_mode", id="ssvep")
    chk(leve is not None and leve.startswith("set_params") and "panne simulée" in leve,
        f"un set_params accepté puis refusé dans la boucle : start() lève EegApiError ({leve})")


def tester_raspberry_pi():
    """RaspberryPi/exemple (UDP) contre un moteur en écoute sur demande, comme la console."""
    print("[clients] RaspberryPi (UDP)", flush=True)
    dossier = os.path.join(APPLICATIONS, "RaspberryPi", "exemple")
    sys.path.insert(0, dossier)
    import eeg_api_udp
    config = eeg_api_udp.load_config(os.path.join(dossier, "config.json"))
    srv, fil = moteur("sur_demande", port_udp=0)
    port = (srv.snapshot().get("udp") or {}).get("port")
    journal, decisions, fini = [], [], threading.Event()
    device = eeg_api_udp.EegApiDevice(dict(config, app_name="tester-udp", engine_host="127.0.0.1",
                                           engine_port=port, device_port=0),
                                      log=journal.append)

    def jouer():
        try:
            device.connect()
            device.start()
            for decision in device.decisions():
                decisions.append(decision)
        except Exception as e:      # noqa: BLE001 - le test le lit dans le journal
            journal.append(f"EXCEPTION {e!r}")
        finally:
            fini.set()

    try:
        srv.submit("chercher_applications", on=True)
        threading.Thread(target=jouer, daemon=True).start()
        uid, fin = None, time.time() + 15
        while uid is None and time.time() < fin:
            uid = next((a["uid"] for a in srv.snapshot()["applications"]
                        if a.get("nom") == "tester-udp"), None)
            time.sleep(0.2)
        chk(uid is not None, f"l'appareil s'annonce : la recherche le liste ({uid})")
        srv.submit("connecter", uid=uid)
        fin = time.time() + 90
        while len(decisions) < 3 and time.time() < fin and not fini.is_set():
            time.sleep(0.2)
        reglages = srv.reglages.get("ssvep") or {}
        chk(reglages.get("targets_on") == "physical"
            and [float(f) for f in reglages.get("freqs") or ()] == [13.0, 15.0],
            f"le moteur a retenu les réglages de config.json ({reglages.get('freqs')})")
        chk(len(decisions) >= 3 and decisions[0].get("mode") == "ssvep"
            and "target_index" in decisions[0],
            f"trois décisions poussées, voies par nom ({sorted(decisions[0]) if decisions else 'aucune'})")
        srv.submit("deconnecter")
        fini.wait(8)
        chk(fini.is_set() and "disconnected in the console" in journal,
            "« Déconnecter » : decisions() s'arrête et le dit")
        chk("ssvep" not in srv.active, "le moteur a arrêté le mode que l'appareil avait démarré")
    finally:
        device.close()
        arreter(srv, fil)
    if not all(resultats[-4:]):
        print("  --- journal de l'appareil :\n    " + "\n    ".join(journal[-25:]))


def doublures_ros(surcharges):
    """De quoi importer les nœuds ROS 2 sans ROS : rclpy, std_msgs et geometry_msgs réduits à ce
    que les nœuds utilisent. Les publications sont gardées dans `publie[topic]`. Ce n'est pas
    ROS : l'API réelle (rclpy, launch) n'est vérifiée que sur une machine ROS 2."""
    import types
    publie = {}

    class Message:
        def __init__(self, data=None):
            self.data = data

    class Vecteur:
        def __init__(self):
            self.x = self.y = self.z = 0.0

    class Twist:
        def __init__(self):
            self.linear, self.angular = Vecteur(), Vecteur()

    class Instant:
        def __init__(self, t):
            self.t = t

        def __sub__(self, autre):
            return types.SimpleNamespace(nanoseconds=int((self.t - autre.t) * 1e9))

    class Node:
        def __init__(self, nom):
            self.nom, self.parametres, self.abonnements = nom, {}, {}

        def declare_parameter(self, nom, defaut):
            self.parametres[nom] = surcharges.get(nom, defaut)

        def get_parameter(self, nom):
            return types.SimpleNamespace(value=self.parametres[nom])

        def create_publisher(self, _type, topic, _profondeur):
            return types.SimpleNamespace(publish=lambda m: publie.setdefault(topic, []).append(m))

        def create_subscription(self, _type, topic, rappel, _profondeur):
            self.abonnements[topic] = rappel

        def create_timer(self, _periode, _rappel):
            return None

        def get_clock(self):
            return types.SimpleNamespace(now=lambda: Instant(time.monotonic()))

        def get_logger(self):
            return types.SimpleNamespace(info=lambda m: None, error=lambda m: None)

        def destroy_node(self):
            pass

    rclpy = types.ModuleType("rclpy")
    rclpy.init = rclpy.shutdown = lambda *a, **k: None
    rclpy.ok = lambda: False
    noeud = types.ModuleType("rclpy.node")
    noeud.Node = Node
    executeurs = types.ModuleType("rclpy.executors")
    executeurs.ExternalShutdownException = type("ExternalShutdownException", (Exception,), {})
    std = types.ModuleType("std_msgs.msg")
    std.String = std.Int32 = std.Float32 = Message
    geo = types.ModuleType("geometry_msgs.msg")
    geo.Twist = Twist
    for nom, module in {"rclpy": rclpy, "rclpy.node": noeud, "rclpy.executors": executeurs,
                        "std_msgs": types.ModuleType("std_msgs"), "std_msgs.msg": std,
                        "geometry_msgs": types.ModuleType("geometry_msgs"),
                        "geometry_msgs.msg": geo}.items():
        sys.modules[nom] = module
    return publie, Message


def tester_ros2():
    """ROS2/exemple : params.yaml, puis le pont (paquet eeg_api_ros) et intent_to_twist (paquet
    eeg_api_ros_example), avec des doublures de rclpy, contre un moteur en écoute sur demande."""
    print("[clients] ROS2 (doublures de rclpy : ce n'est pas ROS)", flush=True)
    exemple = os.path.join(APPLICATIONS, "ROS2", "exemple")
    paquet = os.path.join(exemple, "eeg_api_ros")
    paquet_exemple = os.path.join(exemple, "eeg_api_ros_example")
    try:
        import yaml
        with open(os.path.join(paquet_exemple, "config", "params.yaml"), encoding="utf-8") as f:
            params = yaml.safe_load(f)
        pont = params["eeg_api_bridge"]["ros__parameters"]
        import json
        chk(isinstance(json.loads(pont["settings"]), dict) and "intent_to_twist" in params,
            "le params.yaml de l'exemple se lit (les deux nœuds), `settings` est un objet JSON")
    except ImportError:
        pont = None
        print("  (PyYAML absent : params.yaml non lu)")
    srv, fil = moteur("sur_demande", port_udp=0)
    port = (srv.snapshot().get("udp") or {}).get("port")
    surcharges = dict(app_name="tester-ros", engine_host="127.0.0.1", engine_port=port,
                      device_port=0)
    if pont:
        surcharges["settings"] = pont["settings"]
    publie, Message = doublures_ros(surcharges)
    sys.path.insert(0, paquet)
    sys.path.insert(0, paquet_exemple)
    from eeg_api_ros import bridge
    from eeg_api_ros_example import intent_to_twist
    noeud = None
    try:
        srv.submit("chercher_applications", on=True)
        noeud = bridge.Bridge()
        uid, fin = None, time.time() + 15
        while uid is None and time.time() < fin:
            uid = next((a["uid"] for a in srv.snapshot()["applications"]
                        if a.get("nom") == "tester-ros"), None)
            time.sleep(0.2)
        chk(uid is not None, f"le nœud s'annonce : la recherche le liste ({uid})")
        srv.submit("connecter", uid=uid)
        fin = time.time() + 90
        while len(publie.get("eeg/target", [])) < 3 and time.time() < fin:
            time.sleep(0.2)
        etats = [m.data for m in publie.get("eeg/state", [])]
        chk(etats[:3] == ["announcing", "connected", "decoding"], f"eeg/state : {etats}")
        chk(len(publie.get("eeg/target", [])) >= 3 and len(publie.get("eeg/decision", [])) >= 3
            and "target_index" in publie["eeg/decision"][0].data,
            f"eeg/decision et eeg/target publiés ({len(publie.get('eeg/target', []))} décisions)")
        noeud.shutdown()
        noeud = None
        time.sleep(1.0)
        fin_cx = srv.snapshot().get("fin_connexion") or {}
        chk("ssvep" not in srv.active and fin_cx.get("raison") == "bye",
            f"l'arrêt du nœud arrête le mode et dit « bye » ({fin_cx.get('raison')})")
    finally:
        if noeud is not None:
            noeud.shutdown()
        arreter(srv, fil)
    vitesse = intent_to_twist.IntentToTwist()
    vitesse.on_target(Message(1))
    vitesse.tick()
    v1 = publie["cmd_vel"][-1]
    vitesse.on_target(Message(-1))
    vitesse.tick()
    v2 = publie["cmd_vel"][-1]
    vitesse.on_target(Message(1))
    vitesse.last = types_vieux = vitesse.get_clock().now()
    types_vieux.t -= 5.0
    vitesse.tick()
    v3 = publie["cmd_vel"][-1]
    chk(v1.angular.z == 0.5 and v2.angular.z == 0.0 and v2.linear.x == 0.0 and v3.angular.z == 0.0,
        "intent_to_twist : cible 1 → 0,5 rad/s ; -1 et une décision périmée → vitesse nulle")


# Les croquis et la carte pour laquelle chacun se compile. Un croquis qui lit `secrets.h` (ignoré
# par git) se compile sur une copie où `secrets.example.h` en tient lieu.
CROQUIS = (
    ("ESP32/exemple", "esp32:esp32:esp32doit-devkit-v1"),
    ("ESP32/exemple_leds", "esp32:esp32:esp32doit-devkit-v1"),
    ("ArduinoR4WiFi/exemple", "arduino:renesas_uno:unor4wifi"),
)


def tester_copies():
    """Chaque exemple/ porte sa copie de la bibliothèque : la même liste que [smoke-exemples]."""
    print("[clients] copies d'une même bibliothèque (client/ et exemple/)", flush=True)
    ecarts = copies_divergentes(APPLICATIONS)
    for ecart in ecarts:
        print(f"  {ecart}")
    chk(not ecarts, f"copies identiques ({len(ecarts)} écart(s))")


def tester_compilations():
    """Les croquis Arduino, compilés par arduino-cli s'il est installé (sinon : dit, pas compté)."""
    print("[clients] compilation des croquis", flush=True)
    cli = shutil.which("arduino-cli") or r"C:\Program Files\Arduino CLI\arduino-cli.exe"
    if not os.path.exists(cli):
        print("  SAUTÉ arduino-cli absent : croquis non compilés", flush=True)
        return
    for dossier, carte in CROQUIS:
        croquis = os.path.join(APPLICATIONS, dossier)
        copie = None
        if os.path.exists(os.path.join(croquis, "secrets.example.h")):
            copie = os.path.join(tempfile.mkdtemp(prefix="tester-clients-"),
                                 os.path.basename(croquis))
            shutil.copytree(croquis, copie)
            shutil.copy(os.path.join(copie, "secrets.example.h"), os.path.join(copie, "secrets.h"))
        # Un dossier de construction qui reste d'une fois sur l'autre : la seconde passe est rapide.
        build = os.path.join(tempfile.gettempdir(), "tester-clients-"
                             + dossier.replace("/", "_") + "-" + carte.replace(":", "_"))
        r = subprocess.run([cli, "compile", "--fqbn", carte, "--build-path", build,
                            copie or croquis],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if copie:
            shutil.rmtree(os.path.dirname(copie), ignore_errors=True)
        if r.returncode != 0:
            print("\n".join((r.stdout + r.stderr).splitlines()[-15:]))
        chk(r.returncode == 0, f"{dossier} se compile pour {carte}")


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--vite", action="store_true", help="sans les moteurs")
    args = p.parse_args(argv)
    os.environ.setdefault("EEG_LANGUE", "fr")
    tester_copies()
    tester_compilations()
    if not args.vite:
        tester_python_lsl()
        tester_raspberry_pi()
        tester_ros2()
    ok = all(resultats) and resultats
    print(f"[clients] {sum(resultats)}/{len(resultats)} — VERDICT : {'OK' if ok else 'PROBLÈME'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
