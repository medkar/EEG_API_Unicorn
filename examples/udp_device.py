"""A fake network device: it plays the ESP32 that drives LEDs, over UDP, without LSL.

A microcontroller cannot speak LSL. It can send and receive UDP datagrams: the engine of the
CONSOLE listens to them on port 5010. Every datagram is ONE JSON object, in UTF-8, carrying
`"v": 1` (the version of the protocol). The full contract is in docs/control.md.

This script does, in Python and with the standard library only, what the ESP32 program does:

    1. it ANNOUNCES itself every second (hello), until a console connects it:
           device -> {"v": 1, "hello": "EEG_API_Unicorn", "app": <name>, "id": <id>, "port": <port>}
       In the console: "Connect an application", pick this device, "Connect". "Identify" sends
       {"v": 1, "identify": true}: a real device blinks its LEDs, this one prints "IDENTIFY".
    2. the console connects it:
           engine -> {"v": 1, "connect": <engine instance>, "host": <PC name>}
           device -> {"v": 1, "connected": true}
       Already connected to another console, it answers {"v": 1, "connected": false,
       "busy": <PC name of that console>}.
    3. it sends its settings, then starts the SSVEP mode (one command per datagram, the same
       commands as over LSL): targets on LEDs ("targets_on": "physical"), its frequencies,
       the names of its targets;
    4. it prints every decision the engine pushes ("decision: target=… freq=…"): a real device
       lights the chosen LED. Without --watch, it stops after 3 decisions with a target (or
       after --timeout seconds), stops the mode, says "bye" and exits.

Both sides send {"v": 1, "alive": true} every second while connected. 5 s without any news
from the engine: the device considers itself disconnected (with --watch it announces itself
again, like the ESP32; without, it exits with code 1). The engine does the same: 5 s without
news from the device, and it stops what the device started.

On the same computer as the console:

    python examples/udp_device.py --engine-host 127.0.0.1

On another computer (or to play an ESP32 on the network), the default sends the hello to the
whole local network (broadcast). If the console never lists the device, give the IP address
of the console's computer with --engine-host, and check the firewall of that computer (UDP
port 5010, incoming).

Exit code: 0 if the run went to its end (the mode is stopped), 1 if it failed (it says which:
"FAILED: …"), 2 if its UDP port is taken. Being connected in the console waits with no time
limit. Ctrl+C sends "bye" (the engine stops what we started) and exits with code 130.
With --watch it prints every decision, and when the console disconnects it (or the engine
goes silent) it announces itself again, like the ESP32. It ends by itself only when the engine
refuses our settings or our mode, or the mode fails (code 1): announcing ourselves again
would only be refused again.

Five rules that an ESP32 program must follow too, or the engine ignores it WITHOUT a reply:
  1. send EVERYTHING from the one socket bound to the port you announce: the engine
     recognises the device by the address its datagrams come FROM;
  2. put "v": 1 in every datagram;
  3. once connected, answer to the address the "connect" came from (not to the broadcast
     address): that is where the engine is;
  4. every message the engine pushes carries a "seq" number that grows: ignore one whose
     "seq" is not greater than the last one (UDP can deliver an old message late). Start
     again from 0 at every "connect";
  5. UDP can LOSE a datagram: a command with no reply after a while is sent again. The
     commands are safe to repeat (`start_mode` on a running mode answers "already_running").
"""

import argparse
import json
import socket
import sys
import time
import uuid

ENGINE_PORT = 5010             # the port the console's engine listens to
BROADCAST = "255.255.255.255"  # "every computer of this local network"
HELLO = "EEG_API_Unicorn"      # the word that tells the engine "this is a device for you"
VERSION = 1

HELLO_EVERY_S = 1.0       # one hello per second until connected
ALIVE_EVERY_S = 1.0       # one "alive" per second once connected
ENGINE_SILENCE_S = 5.0    # no news from the engine for this long: we are disconnected
REPLY_TIMEOUT_S = 2.0     # a command with no reply after this long is sent again...
TRIES = 3                 # ...at most this many times in all
MAX_DATAGRAM = 8192       # the engine ignores a bigger datagram; we do the same


def default_id():
    """An identifier for this device: the end of this computer's network (MAC) address, as an
    ESP32 would use the end of its own. It tells two devices of the same program apart."""
    mac = uuid.getnode()
    return f"{(mac >> 8) & 0xFF:02X}:{mac & 0xFF:02X}"


class Device:
    """The device: one UDP socket, and what it knows about the engine that connected it."""

    def __init__(self, name, ident, port, engine_host, engine_port):
        self.name = name
        self.ident = ident
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Needed to send to the broadcast address (the default --engine-host).
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # "" = every network interface of this computer: we hear the engine whatever the
        # network it answers on. Port 0 = a free port, chosen by the system.
        self.sock.bind(("", port))
        self.port = self.sock.getsockname()[1]
        self.sock.settimeout(0.05)       # never wait long: we have hellos and alives to send
        self.announce_to = (engine_host, engine_port)
        self.engine = None          # (ip, port) of the engine that connected us, or None
        self.console = None         # the PC name of that console (for "busy")
        self.last_seq = 0           # the "seq" of the last message we accepted
        self.heard = 0.0            # when we last heard from the engine
        self.next_hello = 0.0
        self.next_alive = 0.0
        self.sent = 0               # commands sent, to number their "ref"
        self.replies = {}           # ref -> the engine's reply
        self.failures = {}          # ref -> the "failed" message of an accepted command
        self.decisions = []         # decisions received, not yet shown
        self.phase = None           # the last phase of the engine's status
        self.ended = None           # why the connection ended: the "disconnected" message,
                                    # or "silent"; None while connected
        self.reconnected = False    # the console connected us AGAIN (it had lost us)
        self.warned = set()

    # --- sending -------------------------------------------------------------------------------

    def send(self, message, to):
        """Sends one message (one JSON object, one datagram), with "v": 1."""
        data = json.dumps({"v": VERSION, **message}).encode("utf-8")
        try:
            self.sock.sendto(data, to)
        except OSError as e:     # no network, for example: say it once, keep going
            if to not in self.warned:
                self.warned.add(to)
                print(f"  (cannot send to {to[0]}:{to[1]}: {e})")

    def command(self, command):
        """Sends one command of docs/control.md and returns its reply, or None: no reply after
        TRIES attempts, or the connection ended meanwhile (see `ended`, `reconnected`)."""
        self.sent += 1
        # The engine answers to OUR address only: a counter is enough to recognise our replies.
        # (Over LSL the reply stream is shared by every program, hence the random part of
        # control_client.py.)
        message = dict(command, ref=f"{self.name}-{self.sent}")
        for attempt in range(TRIES):
            if attempt:
                print(f"  (no reply after {REPLY_TIMEOUT_S:g} s: UDP may have lost the command "
                      f"or its reply; sending it again, safely)")
            print(f"  -> {json.dumps(message)}")
            self.send(message, self.engine)
            deadline = time.monotonic() + REPLY_TIMEOUT_S
            while time.monotonic() < deadline:
                self.poll()
                if self.ended is not None or self.reconnected:
                    return None
                reply = self.replies.pop(message["ref"], None)
                if reply is not None:
                    print(f"  <- {json.dumps(reply)}")
                    return reply
        return None

    def bye(self):
        """Says we stop: the engine ends the connection at once, and stops what we started.
        Not connected (Ctrl+C while we wait), it goes where the hellos go: the console removes
        us from its list at once instead of 5 s later."""
        self.send({"bye": True}, self.engine or self.announce_to)

    # --- receiving -----------------------------------------------------------------------------

    def poll(self):
        """One short turn (about 0.05 s): sends the hello or the alive that is due, reads what
        arrived, and notices a silent engine. Call it all the time."""
        now = time.monotonic()
        if self.engine is None and now >= self.next_hello:
            self.next_hello = now + HELLO_EVERY_S
            self.send({"hello": HELLO, "app": self.name, "id": self.ident, "port": self.port},
                      self.announce_to)
        if self.engine is not None and now >= self.next_alive:
            self.next_alive = now + ALIVE_EVERY_S
            self.send({"alive": True}, self.engine)
        for _ in range(100):        # everything that is waiting, in one turn
            try:
                # A buffer big enough for any datagram. On an ESP32, use at least 8 KB, not the
                # 255 bytes of the usual WiFiUDP example: the engine's replies list every setting
                # of the mode, and a cut datagram is not valid JSON.
                data, source = self.sock.recvfrom(65536)
            except socket.timeout:
                break               # nothing more for now
            except ConnectionResetError:
                # Windows reports here that an EARLIER datagram reached a closed port (no
                # engine there yet). It is not a datagram: keep going.
                continue
            except OSError as e:
                # Something else (the network went down, for example): say it once, and try
                # again at the next turn.
                if "reading" not in self.warned:
                    self.warned.add("reading")
                    print(f"  (cannot read the network: {e})")
                break
            self.received(data, source)
        if self.engine is not None and time.monotonic() - self.heard >= ENGINE_SILENCE_S:
            print(f"  no news from the engine for {ENGINE_SILENCE_S:g} s: we consider "
                  f"ourselves disconnected")
            self.engine = None
            self.ended = "silent"

    def received(self, data, source):
        """One datagram from `source` = (ip, port)."""
        if len(data) > MAX_DATAGRAM:
            return
        try:
            message = json.loads(data.decode("utf-8"))
        except ValueError:          # not UTF-8, or not JSON: ignored
            return
        if not isinstance(message, dict) or message.get("v") != VERSION:
            return                  # not for us, or another version of the protocol
        if message.get("identify") is True:
            # A real device blinks its LEDs, so that the person at the console sees which
            # device of the list is this one.
            print("IDENTIFY: blink now (the console asks this device to show itself)")
            return
        if "connect" in message:
            self.asked_to_connect(message, source)
            return
        if source != self.engine:
            return                  # not from OUR engine (another console, a late datagram)
        self.heard = time.monotonic()      # any message of the engine is a sign of life
        if "alive" in message:
            return
        seq = message.get("seq")
        if isinstance(seq, int) and not isinstance(seq, bool):
            if seq <= self.last_seq:
                return              # older than the last one: UDP delivered it late
            self.last_seq = seq
        event = message.get("event")
        if event == "disconnected":
            print(f"  <- {json.dumps(message)}")
            self.engine = None
            self.ended = message
        elif event == "failed":
            print(f"  <- {json.dumps(message)}")
            self.failures[message.get("ref")] = message
        elif "status" in message:
            self.status(message["status"])
        elif "decision" in message:
            self.decisions.append(message["decision"])
        elif "ref" in message:
            self.replies[message["ref"]] = message

    def asked_to_connect(self, message, source):
        """A console wants to connect us. We accept if we are free, or if it is OUR engine
        again (it lost us: we start over); otherwise we answer "busy"."""
        host = message.get("host")
        if self.engine is not None and source != self.engine:
            self.send({"connected": False, "busy": self.console}, source)
            print(f"  '{host}' asked to connect us, but '{self.console}' already has: "
                  f"answered busy")
            return
        if self.engine == source:
            self.reconnected = True
        self.engine = source        # from now on, everything goes to this address
        self.console = host
        self.last_seq = 0           # a new connection: its "seq" starts again
        self.heard = self.next_alive = time.monotonic()
        self.ended = None
        self.phase = None
        self.send({"connected": True}, source)
        print(f"connected: by the console of '{host}' (engine at {source[0]}:{source[1]})")

    def status(self, status):
        """The phase of the modes we started, pushed at every change and every second."""
        phase = status.get("phase")
        if phase != self.phase:
            self.phase = phase
            print(f"status: {phase}" + (f" - {status['instruction']}"
                                        if status.get("instruction") else ""))

    def close(self):
        self.sock.close()


def show(decision, names):
    """One line per decision. A decision carries, by name, the channels of the LSL stream
    EEG_API_Unicorn_decoded_ssvep: target_index, freq_hz, confidence, score_<f>Hz.
    target_index is a number (-1.0 travels as a float): -1 means "no decision", NEVER target 0.
    A real device lights the chosen LED (steady), and keeps it lit on -1 or turns it off: that
    is the rule of YOUR game."""
    index = decision.get("target_index")
    target = int(index) if isinstance(index, (int, float)) else -1
    freq = decision.get("freq_hz") or 0.0
    confidence = decision.get("confidence")
    what = "no decision" if target < 0 else (names[target] if target < len(names) else "?")
    print(f"decision: target={target} freq={freq:g} Hz ({what}"
          + (f", confidence {confidence:.2f})" if isinstance(confidence, (int, float)) else ")"))
    return target


def wait_for_a_console(device):
    """Step 1: announces the device every second until a console connects it."""
    print(f"[1/4] Announcing '{device.name}' (id {device.ident}, UDP port {device.port}) to "
          f"{device.announce_to[0]}:{device.announce_to[1]}, every second")
    shown = 0.0
    while device.engine is None:
        if time.monotonic() - shown >= 10.0:
            shown = time.monotonic()
            print(f"  Waiting to be connected: in the console, click \"Connect an "
                  f"application\", pick '{device.name}', then \"Connect\".")
        device.poll()


def one_session(device, args, names):
    """Steps 2 to 4, once connected. Returns the exit code, or None when the console connected
    us again (the caller starts over). With --watch, returns only when disconnected."""
    device.reconnected = False
    print("[2/4] set_params: SSVEP targets on LEDs (\"targets_on\": \"physical\"), our "
          "frequencies and names")
    reply = device.command({"cmd": "set_params", "mode": "ssvep",
                            "params": {"targets_on": "physical", "freqs": args.freqs,
                                       "target_names": names}})
    if reply is None or not reply.get("accepted"):
        return ended_or_failed(device, args, "set_params refused, or no reply")

    print("[3/4] start_mode: ssvep")
    reply = device.command({"cmd": "start_mode", "mode": "ssvep"})
    if reply is None or not reply.get("accepted"):
        return ended_or_failed(device, args, "start_mode refused, or no reply")
    start_ref = reply["ref"]
    # Stop only what WE started: a mode that was already running belongs to someone else.
    # One case stays unknown: the engine started the mode but its reply was LOST, so our
    # second try answers "already_running". The "bye" at the end covers it: the engine keeps
    # the list of what we started, and stops exactly that.
    started_here = not reply.get("already_running")
    print("  \"accepted\" means the engine took the command: the mode first warms up, then "
          "measures the rest (about 23 s), then decides.")

    print("[4/4] Decisions" + (": every one, until Ctrl+C (--watch)" if args.watch else
                               f": until 3 with a target, or {args.timeout:g} s"))
    got = with_target = 0
    deadline = time.monotonic() + args.timeout
    while args.watch or (with_target < 3 and time.monotonic() < deadline):
        device.poll()
        if device.ended is not None or device.reconnected:
            return ended_or_failed(device, args, "")
        if start_ref in device.failures:
            return ended_or_failed(device, args, "the mode failed in the engine")
        while device.decisions:
            got += 1
            if show(device.decisions.pop(0), names) >= 0:
                with_target += 1
    if got == 0:
        return fail(f"no decision in {args.timeout:g} s")
    if with_target < 3:
        print(f"  {got} decision(s) in {args.timeout:g} s, {with_target} with a target "
              f"(-1 = no target: look at one LED)")

    if started_here:
        print("Stopping the mode we started")
        reply = device.command({"cmd": "stop_mode", "mode": "ssvep"})
        if reply is None or not reply.get("accepted"):
            return ended_or_failed(device, args, "stop_mode refused, or no reply")
    print("OK: connected, set, started, decisions received"
          + (", stopped." if started_here else " (the mode was already running: left on)."))
    return 0


def ended_or_failed(device, args, why):
    """What to do when a step did not go as planned: the end of the connection is the reason
    if there is one (the refused or missing reply is then only its consequence)."""
    if device.reconnected:
        print("  The console connected us again (it had lost us): starting over.")
        return None
    ended = device.ended
    if ended is None:
        return fail(why)
    if ended == "silent":
        why = f"no news from the engine for {ENGINE_SILENCE_S:g} s"
    elif ended.get("cause") == "console":
        why = "disconnected in the console"
    elif ended.get("cause") == "engine_stopped":
        why = "the engine stopped (the console closed)"
    else:       # a cause this script does not know yet: a later engine may add some
        why = f"disconnected ({ended.get('cause')})"
    if args.watch:
        print(f"  {why}: announcing ourselves again, like the ESP32 (Ctrl+C to stop)")
        return None
    return fail(why)


def fail(why):
    print(f"FAILED: {why}.")
    return 1


def main(argv):
    p = argparse.ArgumentParser(
        description="A fake network device (it plays the ESP32 that drives LEDs): announces "
                    "itself over UDP, is connected by the console, sets and starts the SSVEP "
                    "mode on physical targets, prints the decisions. Standard library only.")
    p.add_argument("--name", default="udp-device",
                   help="the name of this application, shown by the console (default: "
                        "%(default)s)")
    p.add_argument("--id", dest="ident", default=default_id(),
                   help="the identifier of this device, shown by the console next to the "
                        "name (default: the end of this computer's MAC address, %(default)s)")
    p.add_argument("--port", type=int, default=5011,
                   help="the UDP port this device listens to, and announces (default: "
                        "%(default)s; 0 = a free port chosen by the system)")
    p.add_argument("--engine-host", default=BROADCAST,
                   help="where to send the hellos (default: %(default)s, the whole local "
                        "network). Broadcast is not guaranteed on a computer with several "
                        "networks (Wi-Fi, VPN): give the console's IP address, or 127.0.0.1 "
                        "on the same computer")
    p.add_argument("--engine-port", type=int, default=ENGINE_PORT,
                   help="the UDP port the console's engine listens to (default: %(default)s)")
    p.add_argument("--freqs", type=float, nargs="+", default=[13.0, 15.0],
                   help="the blinking frequency of each LED, in Hz (default: 13 15)")
    p.add_argument("--names", nargs="+", default=None,
                   help="the name of each target, one per frequency (default: LED1, LED2...)")
    p.add_argument("--timeout", type=float, default=60.0,
                   help="seconds to wait for 3 decisions with a target, once the mode is "
                        "started (default: %(default)s; an SSVEP start takes about 23 s). "
                        "Being connected waits with no time limit")
    p.add_argument("--watch", action="store_true",
                   help="print every decision, and announce itself again when disconnected, "
                        "like the ESP32 (Ctrl+C to stop: code 130). Ends by itself only when "
                        "the engine refuses our settings or our mode (code 1)")
    args = p.parse_args(argv)
    names = args.names or [f"LED{i + 1}" for i in range(len(args.freqs))]

    try:
        device = Device(args.name, args.ident, args.port, args.engine_host, args.engine_port)
    except OSError as e:
        print(f"FAILED: cannot listen on UDP port {args.port} ({e}). Another program uses it? "
              f"Give another --port (0 = any free port).")
        return 2
    try:
        while True:
            wait_for_a_console(device)
            code = None
            while code is None and device.engine is not None:
                code = one_session(device, args, names)
            if code is not None:
                if device.engine is not None:
                    # Still connected (the run ended, or a step failed): say we stop, or the
                    # engine would only notice our silence 5 s from now.
                    device.bye()
                    print("  -> bye: the console sees this device leave at once")
                return code
    except KeyboardInterrupt:
        device.bye()
        print("Interrupted (Ctrl+C): sent bye, the engine stops what we started.")
        return 130
    finally:
        device.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
