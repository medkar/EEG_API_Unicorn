"""Drive the engine from your own program: set a mode, start it, read its decisions, stop it.

Your application talks to the engine over two LSL streams of type Markers, one JSON string per
sample (the full contract is in docs/control.md):

    your app  --- EEG_API_Unicorn_control --->  engine    commands (YOUR app creates this stream)
    your app  <-- EEG_API_Unicorn_replies ----  engine    one reply per command

LSL cannot receive on a stream it publishes: that is why YOUR program creates the command stream,
and the engine listens to it. With the console, this script may run on any computer of the
network, but the engine hears it only once someone has picked it under "Connect an
application": no other program of the network can start a mode without that click. With
`server.py` alone, only a program on the SAME computer can drive the engine.

Start the engine first, either the console (`outils\\Console EEG.bat`) or headless:

    python src/core/server.py --synthetic

then, in another terminal:

    python examples/control_client.py

It prints every command it sends (->) and every reply it gets (<-), in seven steps:
    1. create the command stream, open the reply streams, wait to be CONNECTED (with the
       console: click "Connect an application" and pick this script);
    2. set the SSVEP screen refresh to 30 Hz ALONE: refused, and that is expected;
    3. ask the engine to PROPOSE target frequencies for a 30 Hz screen;
    4. set the refresh AND the proposed frequencies together: accepted;
    5. start the SSVEP mode;
    6. wait for the mode on the `status` stream, then read 3 decisions on `decoded_ssvep`
       (with `--watch`, it then keeps reading them, one line each, until Ctrl+C);
    7. stop the mode, if this script started it.
Exit code: 0 if every step got the expected reply, 1 if one did not (it says which), 2 if no
engine was found on the network. A program the console has not connected waits, with no
time limit (Ctrl+C stops it: exit code 130).
With `--watch`, step 6 does not end after 3 decisions: the script keeps printing every decision
(one line each) so that you can watch the decoding, in the console or here, as long as you like.
Ctrl+C ends it: the script stops the mode it started (step 7), then exits with code 130.
With `--mode mi` it skips the SSVEP steps 2 to 4 and starts a mode with a MODEL: with the
console, its start_mode is accepted but "deferred" until someone chooses the model and clicks
"Start decoding". If the console disconnects us, or the engine stops, the script says so within
about a second, at whatever step it is, and stops (exit code 1): the engine tells us on the reply
stream, with a message `{"ref": null, "event": "disconnected", "app": <our source_id>, ...}`.

The engine KEEPS the settings of step 4 after the script ends (a 30 Hz screen), until it is
closed: the last line says how to set them back.

When the engine removes a decoded stream (model change, disconnection), liblsl may print
"ERR| Stream transmission broke off" in the terminal: that is liblsl, not an error of this script.

Two LSL traps lose a message WITHOUT any error. This script shows the fix for both:
  1. A command pushed before the engine has connected to your stream is LOST: LSL replays
     nothing. Wait for the engine first: `outlet.wait_for_consumers(timeout)`. With the
     console, the engine connects only once someone has clicked "Connect an application".
  2. A reply published before you listen is lost too: open your reply inlets (`open_stream()`)
     BEFORE you send your first command.
A command with no reply after a few seconds was lost: send it again. The four commands
(`start_mode`, `stop_mode`, `set_params`, `propose_params`) are safe to repeat.

The only dependency is `pylsl`: copy this file into your project. In Unity, MATLAB or C++ the
steps are the same, with their own LSL library.
"""

import argparse
import json
import os
import sys
import time
import uuid

from pylsl import IRREGULAR_RATE, StreamInfo, StreamInlet, StreamOutlet, resolve_byprop

# The public names of the streams. Every engine uses the same ones: what tells two engines apart
# is the `source_id` of their streams, "<stream name>@<engine id>".
CONTROL_STREAM = "EEG_API_Unicorn_control"
REPLIES_STREAM = "EEG_API_Unicorn_replies"
STATUS_STREAM = "EEG_API_Unicorn_status"
# The decoded stream of each mode this script can run, and the name of its channel 0.
DECODED_STREAMS = {"ssvep": "EEG_API_Unicorn_decoded_ssvep", "mi": "EEG_API_Unicorn_decoded_mi"}
FIRST_CHANNEL = {"ssvep": "target_index", "mi": "intent_index"}

# A reply that has not arrived after this long will not arrive: the command or its reply was lost.
REPLY_TIMEOUT_S = 5.0
# Every "ref" of this run starts with this. The reply streams are SHARED by every program of the
# network: "ref" is how we recognise OUR replies. The process id alone is not unique (two
# computers can share one), so a random part is added: no other copy of this script, on any
# computer, takes our replies for its own.
RUN_ID = f"{os.getpid()}-{uuid.uuid4().hex[:6]}"
REF_PREFIX = f"control-client-{RUN_ID}-"


def engine_id_of(source_id):
    """The engine id in a source_id: "EEG_API_Unicorn_replies@synthetic-PC" -> "synthetic-PC"."""
    return source_id.partition("@")[2]


class Waiting:
    """Prints a short line every few seconds during a long wait, so the script never looks
    frozen. Call `tick()` as often as you like."""

    def __init__(self, what, every_s=5.0):
        self.what = what
        self.every_s = every_s
        self.start = self.last = time.monotonic()

    def tick(self):
        now = time.monotonic()
        if now - self.last >= self.every_s:
            self.last = now
            print(f"  ... still waiting for {self.what} ({now - self.start:.0f} s)")


def stream_of_engine(engine, name, timeout):
    """Opens the stream `name` of OUR engine (`engine` is the `EngineLink` of `main`), found by
    its source_id. Returns an inlet, or None: after `timeout` seconds, or at once if we are
    disconnected (check `engine.connected()` to tell which)."""
    source_id = f"{name}@{engine.engine_id}" if engine.engine_id else name
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not engine.connected():
            return None     # an engine that stopped may have removed this stream: do not wait
        # Short slices (0.5 s), so that a disconnection never waits for the whole timeout.
        # No filter on the computer: the engine may run on another machine of the network, and
        # its source_id (which carries its engine id) already tells it apart from any other.
        for info in resolve_byprop("source_id", source_id, timeout=0.5):
            inlet = StreamInlet(info)
            try:
                inlet.open_stream(timeout=1.0)
            except Exception:   # the stream vanished meanwhile: look again
                continue
            return inlet
    return None


class EngineLink:
    """Our link to the engine: the command stream we create, the reply streams we read."""

    def __init__(self, control_stream):
        # The command stream: type Markers, 1 channel, one JSON string per sample. Its source_id
        # NAMES your application: the console lists it under "Connect an application". Unique to
        # this run.
        self.name = f"control-client-{RUN_ID}"
        info = StreamInfo(control_stream, "Markers", 1, IRREGULAR_RATE, "string", self.name)
        self.outlet = StreamOutlet(info)
        self.replies = []        # (inlet, engine id): every reply stream of the network
        self.engine_id = None    # the engine that answered us first; we only listen to it then
        self.inbox = []          # our replies, in the order they arrived
        # The engine's "disconnected" message meant for US, or None while we are connected.
        self.disconnection = None
        self.sent = 0
        self.warned = False

    def connect(self, timeout):
        """Opens the reply streams of the network, then waits until the engine connects to our
        command stream — with the console, until someone connects us ("Connect an application").
        False only when no engine runs on the network (after `timeout` seconds)."""
        deadline = time.monotonic() + timeout
        waiting = Waiting("the engine")
        while not self.replies and time.monotonic() < deadline:
            waiting.tick()
            # `minimum` is a number we never reach: the call waits the whole second and returns
            # EVERY reply stream that answered, not just the first one (there may be several
            # engines on the network, e.g. one left running).
            found = {i.uid(): i for i in resolve_byprop("name", REPLIES_STREAM, minimum=1000,
                                                       timeout=1.0)}
            for info in found.values():
                # Every engine of the network, whatever its computer: only the one the console
                # connects to us will answer our "ref" (see `poll`).
                inlet = StreamInlet(info)
                try:
                    # Trap 2: listen BEFORE the first command, or its reply is lost.
                    inlet.open_stream(timeout=2.0)
                except Exception:   # an engine that has just quit: skip it
                    continue
                self.replies.append((inlet, engine_id_of(info.source_id())))
        if not self.replies:
            return False
        # Trap 1: a command pushed before the engine has connected to our stream is LOST. With
        # the console, the engine connects only once someone clicks "Connect an application" and
        # picks us: wait as long as it takes, and say what we are waiting for. (`server.py` alone
        # listens to every application of this computer: it connects at once.)
        # Short slices (1 s): a long wait inside liblsl would delay Ctrl+C.
        slices = 0
        while not self.outlet.wait_for_consumers(1.0):
            if slices % 10 == 0:
                print(f"  Waiting to be connected: in the console, click \"Connect an "
                      f"application\", pick '{self.name}', then \"Connect\". "
                      f"(server.py alone connects at once: if it runs, check --stream)")
            slices += 1
        return True

    def connected(self):
        """Still connected? False as soon as the engine has told us it stopped reading our
        command stream: the console disconnected us (the engine stopped the modes we started),
        or the engine stopped. Call it as often as you like: it reads the waiting replies."""
        self.poll()
        if self.disconnection is not None:
            return False
        # A second sign, DELAYED: LSL only notices that the engine has left at our next push
        # (`have_consumers()` stays true as long as we push nothing). It still tells
        # us, at our next command, about an engine that died without a word (a crash).
        return self.outlet.have_consumers()

    def poll(self):
        """Reads every reply waiting on the reply streams, and keeps those meant for us."""
        for inlet, engine_id in self.replies:
            while True:
                sample, _timestamp = inlet.pull_sample(timeout=0.0)
                if sample is None:
                    break
                try:
                    reply = json.loads(sample[0])
                except ValueError:
                    continue
                if not isinstance(reply, dict):
                    continue
                if reply.get("event") == "disconnected":
                    # Not a reply: its "ref" is null. The reply stream is shared, so it is ours
                    # only if "app" is OUR source_id, and if it comes from OUR engine.
                    from_our_engine = self.engine_id is None or engine_id == self.engine_id
                    if (reply.get("app") == self.name and from_our_engine
                            and self.disconnection is None):
                        self.disconnection = reply
                        print(f"  <- {json.dumps(reply)}")
                    continue
                if not str(reply.get("ref")).startswith(REF_PREFIX):
                    continue        # a reply to ANOTHER program (of any computer)
                if self.engine_id is None:
                    self.engine_id = engine_id
                if engine_id != self.engine_id:
                    # Two engines obey the same command stream: one is probably left running.
                    if not self.warned:
                        self.warned = True
                        print(f"  WARNING: engine '{engine_id}' answers too. Only one engine "
                              f"should connect us; we keep talking to "
                              f"'{self.engine_id}'.")
                    continue
                self.inbox.append(reply)

    def why_disconnected(self):
        """(what to print, why the step failed), once `connected()` is False. "cause" is meant
        for programs; "reason" is written for people, never make your app depend on its
        wording."""
        if self.disconnection is None:
            # No message: the engine died without a word, LSL told us at our last command.
            return ("no engine reads our commands any more (it may have crashed)",
                    "no engine reads our commands")
        cause = self.disconnection.get("cause")
        if cause == "console":
            stopped = self.disconnection.get("stopped") or []
            if not stopped:
                return ("disconnected in the console: nothing we started was running",
                        "disconnected in the console")
            return (f"disconnected in the console: the engine stopped what we started "
                    f"({', '.join(str(m) for m in stopped)})", "disconnected in the console")
        if cause == "engine_stopped":
            return ("the engine stopped (the console closed, or server.py stopped): every mode "
                    "stopped", "the engine stopped")
        # A cause this script does not know yet: a later engine may add some.
        return f"disconnected: {self.disconnection.get('reason')}", "disconnected"

    def send(self, command):
        """Sends one command and returns ITS reply, or None: after REPLY_TIMEOUT_S, or at once
        if we are disconnected (then nothing is sent: nobody would read it). After None, check
        `connected()` to tell a lost reply from a disconnection."""
        if not self.connected():
            return None
        self.sent += 1
        command = dict(command, ref=f"{REF_PREFIX}{self.sent}")
        text = json.dumps(command)
        print(f"  -> {text}")
        self.outlet.push_sample([text])
        deadline = time.monotonic() + REPLY_TIMEOUT_S
        while time.monotonic() < deadline:
            connected = self.connected()     # reads the waiting replies too
            for reply in self.inbox:
                # A message with "event" is not the reply: it comes LATER (see `failure`).
                if reply.get("ref") == command["ref"] and "event" not in reply:
                    print(f"  <- {json.dumps(reply)}")
                    return reply
            if not connected:
                return None     # the engine said so: no reply will come, do not wait for it
            time.sleep(0.02)
        print(f"  (no reply after {REPLY_TIMEOUT_S:g} s: the command or its reply was lost)")
        return None

    def failure(self, ref):
        """The second message of an ACCEPTED command that failed later in the engine, or None.
        Without it you would wait forever for a mode that will never start."""
        self.poll()
        for reply in self.inbox:
            if reply.get("ref") == ref and reply.get("event") == "failed":
                return reply
        return None


def print_decision(mode, n, sample, timestamp):
    """One line per decision. Channel 0: -1 means "no decision", NEVER target (or task) 0."""
    note = " (-1 = no decision yet)" if int(sample[0]) == -1 else ""
    print(f"  decision {n}: {FIRST_CHANNEL[mode]}={int(sample[0])}{note} (t={timestamp:.3f})")


def watch_the_mode(engine, mode, start_ref, timeout, deferred=False, watch=False):
    """Step 6: waits for `mode` in the engine's status, then prints 3 decisions. True if done.
    `engine` is the `EngineLink` of `main`. A DEFERRED start (a mode with a model, with the
    console) waits for the person at the console, without a time limit. With `watch`, it then
    keeps printing decisions until Ctrl+C (KeyboardInterrupt), or until we are disconnected."""
    deadline = time.monotonic() + timeout
    # The status of OUR engine: the one whose reply stream answered us.
    status = stream_of_engine(engine, STATUS_STREAM, timeout)
    if status is None:
        if not engine.connected():
            print(f"  {engine.why_disconnected()[0]}")
        else:
            print(f"  no '{STATUS_STREAM}' stream for engine '{engine.engine_id}'")
        return False
    # "accepted" only meant the engine TOOK the command. The mode runs when `status` lists it.
    running = False
    waiting = Waiting(f"'{mode}' in the engine's status"
                      + (" (choose its model in the console)" if deferred else ""))
    while not running and (deferred or time.monotonic() < deadline):
        waiting.tick()
        # Checked at every turn (about twice a second): a deferred start waits WITHOUT a time
        # limit, and only the engine's message can end that wait.
        if not engine.connected():
            print(f"  {engine.why_disconnected()[0]}")
            return False
        failed = engine.failure(start_ref)
        if failed is not None:
            print(f"  <- {json.dumps(failed)}")
            return False
        sample, _timestamp = status.pull_sample(timeout=0.5)
        if sample is not None:
            running = mode in json.loads(sample[0]).get("modes", [])
    if not running:
        print(f"  '{mode}' never appeared in the engine's status")
        return False
    print(f"  status: '{mode}' is running. Its stream is silent during warm-up and rest "
          f"({'about 23 s for SSVEP' if mode == 'ssvep' else 'about 15 s for MI'}).")

    deadline = time.monotonic() + timeout
    stream_name = DECODED_STREAMS[mode]
    decisions = stream_of_engine(engine, stream_name, timeout)
    if decisions is None:
        if not engine.connected():
            print(f"  {engine.why_disconnected()[0]}")
        else:
            print(f"  no '{stream_name}' stream for engine '{engine.engine_id}'")
        return False
    got = 0
    waiting = Waiting("the first decisions (warm-up, then rest)")
    while got < 3 and time.monotonic() < deadline:
        waiting.tick()
        if not engine.connected():
            print(f"  {engine.why_disconnected()[0]}")
            return False
        failed = engine.failure(start_ref)
        if failed is not None:
            print(f"  <- {json.dumps(failed)}")
            return False
        sample, timestamp = decisions.pull_sample(timeout=0.5)
        if sample is None:
            continue
        got += 1
        print_decision(mode, got, sample, timestamp)
    if got < 3:
        print(f"  only {got} decision(s) in {timeout:g} s")
        return False
    if watch:
        return keep_watching(engine, mode, start_ref, decisions, got)
    return True


def keep_watching(engine, mode, start_ref, decisions, got):
    """`--watch`: after the first 3 decisions, one line per decision, with no time limit. Only
    Ctrl+C ends it normally (the caller then stops the mode). Returns False if the engine
    disconnected us or the mode failed: like the first 3, the loop checks that at every turn,
    because the engine tells us on the reply stream, not on the decoded stream."""
    print("  --watch: one line per decision, until Ctrl+C (we then stop the mode we started).")
    waiting = Waiting("the next decision")
    while True:
        waiting.tick()
        if not engine.connected():
            print(f"  {engine.why_disconnected()[0]}")
            return False
        failed = engine.failure(start_ref)
        if failed is not None:
            print(f"  <- {json.dumps(failed)}")
            return False
        sample, timestamp = decisions.pull_sample(timeout=0.5)
        if sample is None:
            continue
        got += 1
        print_decision(mode, got, sample, timestamp)
        waiting = Waiting("the next decision")


def main(argv):
    p = argparse.ArgumentParser(
        description="Drive the EEG_API_Unicorn engine over LSL: set the SSVEP mode for a 30 Hz "
                    "screen, start it, read 3 decisions, stop it.")
    p.add_argument("--stream", default=CONTROL_STREAM,
                   help="name of the command stream the engine listens to (default: "
                        "%(default)s). Keep the default: the console and server.py listen to it")
    p.add_argument("--timeout", type=float, default=60.0,
                   help="seconds to wait for the engine to show up, then for the first "
                        "decisions (default: %(default)s; an SSVEP start takes about 23 s: "
                        "warm-up, then rest). Being connected in the console and choosing "
                        "the model wait without a time limit")
    p.add_argument("--watch", action="store_true",
                   help="after the first 3 decisions, keep printing every decision (one line "
                        "each) until Ctrl+C; the script then stops the mode it started and "
                        "exits with code 130")
    p.add_argument("--mode", choices=("ssvep", "mi"), default="ssvep",
                   help="ssvep (default): the seven steps. mi: a mode with a MODEL, steps 2 to 4 "
                        "skipped; with the console, start_mode is accepted but DEFERRED until "
                        "someone chooses the model and clicks \"Start decoding\"")
    args = p.parse_args(argv)

    engine = EngineLink(args.stream)

    print(f"[1/7] Connect to the engine of the network (command stream '{args.stream}')")
    if not engine.connect(args.timeout):
        print("Engine not found: start the console or `python src/core/server.py "
              "--synthetic` on THIS computer, then run this script again.")
        return 2
    print(f"  {len(engine.replies)} reply stream(s) open; the engine listens to our commands.")
    if args.mode != "ssvep":
        print("[2/7] [3/7] [4/7] skipped: the screen refresh and the frequencies are SSVEP "
              "settings")
        return run_the_mode(engine, args.timeout, args.mode, args.watch)

    print("[2/7] set_params: SSVEP screen refresh = 30 Hz, ALONE")
    reply = engine.send({"cmd": "set_params", "mode": "ssvep", "params": {"refresh_hz": 30}})
    if reply is None:
        return fail_or_disconnected(engine, 2, "no reply")
    if reply["accepted"]:
        print("  Accepted: this engine already holds frequencies that fit 30 Hz (an earlier")
        print("  run set them). A fresh engine refuses this command; the next steps work")
        print("  either way.")
    else:
        reason = reply.get("reason") or ""
        print(f"  Reason: {reason}")
        # A reason is written for people, not for programs: never make your app depend on its
        # wording. Here we only look for one word, to explain what happened.
        if "divis" in reason.lower():
            print("  Refused, and that is expected. On a screen, a target can only blink at")
            print("  refresh / n (n a whole number), and the engine judges the WHOLE set: the")
            print("  frequencies it holds do not all fit 30 Hz. Do what the console does: ask")
            print("  for frequencies that fit (step 3), then send refresh AND frequencies")
            print("  together (step 4).")
        else:
            print("  Refused, but NOT for the expected reason (target frequencies that do not")
            print("  divide the refresh): something else blocks the SSVEP settings. Read the")
            print("  reason above; the next steps will probably be refused too.")

    print("[3/7] propose_params: which SSVEP frequencies fit a 30 Hz screen?")
    reply = engine.send({"cmd": "propose_params", "mode": "ssvep",
                         "params": {"refresh_hz": 30}})
    if reply is None or not reply["accepted"] or reply.get("key") != "freqs" \
            or not reply.get("value"):
        return fail_or_disconnected(engine, 3,
                                    "expected a list of frequencies under \"key\": \"freqs\"")
    freqs = reply["value"]
    print(f"  Proposed: {freqs} Hz. Nothing is applied yet: propose_params only computes.")
    if reply.get("warning"):
        print(f"  Note: {reply['warning']}")

    print("[4/7] set_params: refresh AND proposed frequencies, together")
    reply = engine.send({"cmd": "set_params", "mode": "ssvep",
                         "params": {"refresh_hz": 30, "freqs": freqs}})
    if reply is None or not reply["accepted"]:
        return fail_or_disconnected(engine, 4, "the engine refused its own proposal")
    if reply.get("deferred"):
        print("  \"deferred\": the mode is stopped, so the engine KEEPS these settings and the "
              "next start uses them.")
    try:
        return run_the_mode(engine, args.timeout, "ssvep", args.watch)
    finally:
        # The settings of step 4 outlive this script: say it, whatever happens next.
        print(f"Note: the engine KEEPS the SSVEP settings of step 4 (a 30 Hz screen, targets at "
              f"{freqs} Hz) until it is closed, and the console's SSVEP tests will ask for a "
              f"30 Hz screen too. To set them back without closing it: SSVEP page of the "
              f"console, \"Restore defaults\", then \"Apply\".")


def run_the_mode(engine, timeout, mode="ssvep", watch=False):
    """Steps 5 to 7: start the mode, watch it, stop it if we started it. Returns the exit code.
    With `watch`, step 6 keeps reading decisions until Ctrl+C (exit code 130)."""

    print(f"[5/7] start_mode: {mode}")
    reply = engine.send({"cmd": "start_mode", "mode": mode})
    if reply is None or not reply["accepted"]:
        return fail_or_disconnected(engine, 5, "start refused")
    start_ref = reply["ref"]
    # Stop only what YOU started: a mode that was already running belongs to someone else (the
    # console, another program), who still uses it.
    started_here = not reply.get("already_running")
    if not started_here:
        print("  It was already running: our settings were applied to it. We did not start it,")
        print("  so we will not stop it.")
    deferred = bool(reply.get("deferred"))
    if deferred:
        print("  \"deferred\": this mode needs a MODEL. The person at the console chooses it,")
        print("  then clicks \"Start decoding\": we wait for that without a time limit.")
        print("  If your app sends a \"model\", the console only uses it as a suggestion.")
    print("  \"accepted\" means the engine took the command, not that the mode decodes yet.")

    interrupted = False
    print("[6/7] Wait for the mode on 'status', then read 3 decisions"
          + (", then keep reading them until Ctrl+C (--watch)" if watch else ""))
    try:
        watched = watch_the_mode(engine, mode, start_ref, timeout, deferred, watch)
    except KeyboardInterrupt:   # Ctrl+C: still stop what we started (step 7)
        print("  Interrupted (Ctrl+C).")
        watched = False
        interrupted = True
    except Exception as e:      # e.g. a stream that vanished while we were reading it
        print(f"  error while watching the mode: {e!r}")
        watched = False

    if not engine.connected():
        print("[7/7] stop_mode: skipped, we were disconnected: the engine already stopped what "
              "we started")
        return fail(6, engine.why_disconnected()[1])
    # Step 7 runs even if step 6 failed: always stop what you started.
    if started_here:
        print(f"[7/7] stop_mode: {mode}")
        reply = engine.send({"cmd": "stop_mode", "mode": mode})
    else:
        print(f"[7/7] stop_mode: skipped, {mode} was already running before this script")
        reply = None
    if interrupted:
        return 130
    if not watched:
        return fail(6, "the mode did not run, or published no decision")
    if started_here and (reply is None or not reply["accepted"]):
        return fail_or_disconnected(engine, 7, "stop refused")
    print("OK: every step got the expected reply.")
    return 0


def fail(step, why):
    print(f"FAILED at step {step}: {why}.")
    return 1


def fail_or_disconnected(engine, step, why):
    """`fail(step, why)`, unless we were disconnected meanwhile: then the disconnection is the
    reason, and the missing or refused reply only its consequence."""
    if not engine.connected():
        what, reason = engine.why_disconnected()
        print(f"  {what}")
        return fail(step, reason)
    return fail(step, why)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("Interrupted (Ctrl+C).")
        sys.exit(130)
