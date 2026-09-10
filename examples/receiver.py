"""Hello world: receive an EEG_API_Unicorn stream from Python.

This is the smallest useful client. Start the engine in one terminal — either the console
(`outils\\Console EEG.bat`, then start a mode from its grid) or headless:

    python src/core/server.py --synthetic --mode ssvep

then run this in another:

    python examples/receiver.py                         # signal quality, one line per second
    python examples/receiver.py --stream raw            # the 8 raw channels
    python examples/receiver.py --stream decoded_ssvep  # which target is being looked at
    python examples/receiver.py --stream decoded_neuro  # workload / drowsiness / engagement
    python examples/receiver.py --stream decoded_mi     # imagined left / right hand movement
    python examples/receiver.py --stream decoded_p300   # which of 6 targets was selected
    python examples/receiver.py --stream decoded_errp   # did the machine just get it wrong
    python examples/receiver.py --stream decoded_cvep   # which coded target is being fixated
    python examples/receiver.py --list                  # what is currently on the network

A decoded stream exists from the moment its mode is STARTED, and stays SILENT until the engine
has finished warming up and measuring its rest floor — about 23 s for SSVEP, 40 s for neuro. So
`--list` shows it immediately while this script prints nothing: that is the normal start, not a
fault. Without `--mode`, the engine publishes `raw`, `quality` and `status` and nothing else.

⚠️ Every decoded stream uses `-1` for "no decision" in its first channel (`target_index`,
`intent_index`, `error`). It is NEVER target 0, never "no error", never rest. This script prints
the number raw, on purpose: interpreting it is your application's job, and getting it wrong is
the single most expensive mistake a client of this API can make.

Every line starts with `t=`, the sample's LSL timestamp corrected to this machine's clock. That
number is what makes a session scorable afterwards: the stimulus programs stamp their cues on the
same clock, so `python -u examples/receiver.py --stream decoded_cvep > seance.txt` and the
emitter's `--log` file join on it. Without it you only know how OLD a sample is, which cannot be
compared to anything.

The only dependency is `pylsl`. The same three steps (resolve, open, pull) work identically
in Unity (LSL4Unity), MATLAB and C++ — that is the whole point of using LSL.

To simply LOOK at what is on the network, the console's "What your app sees" page does this
without a second terminal. This file is the thing you COPY into your own application.
"""

import argparse
import sys

from pylsl import StreamInlet, local_clock, resolve_byprop, resolve_streams

PREFIX = "EEG_API_Unicorn"


def list_streams():
    """Show every LSL stream visible on this network — the first thing to run when stuck."""
    streams = resolve_streams(wait_time=2.0)
    if not streams:
        print("No LSL stream found. Is the engine running? Is a firewall blocking UDP?")
        return 1
    for info in streams:
        print(f"  {info.name():<32} type={info.type():<10} "
              f"{info.channel_count()} ch @ {info.nominal_srate()} Hz")
    return 0


def channel_labels(inlet):
    """Read channel names out of the stream metadata rather than hardcoding them.

    The engine ships the montage with the data, so a client never has to be told that
    channel 3 is C4. Hardcode the order and your code silently breaks the day it changes.
    """
    info = inlet.info()
    labels, node = [], info.desc().child("channels").child("channel")
    for _ in range(info.channel_count()):
        labels.append(node.child_value("label"))
        node = node.next_sibling()
    return labels


def main(argv):
    p = argparse.ArgumentParser(description="Minimal EEG_API_Unicorn LSL client.")
    p.add_argument("--stream", default="quality",
                   help="suffix: raw | quality | status | decoded_ssvep | decoded_neuro | "
                        "decoded_mi | decoded_p300 | decoded_errp | decoded_cvep. Any suffix "
                        "works — it is just appended to the prefix, so a new mode needs no "
                        "change here")
    p.add_argument("--list", action="store_true", help="list visible LSL streams and exit")
    args = p.parse_args(argv)

    if args.list:
        return list_streams()

    name = f"{PREFIX}_{args.stream}"
    print(f"Looking for '{name}'...")
    found = resolve_byprop("name", name, timeout=10.0)
    if not found:
        # A `decoded_*` stream exists only while ITS mode runs: naming the mode is the part
        # people forget. `--stream raw` needs no mode at all.
        print("Not found. Start the engine and its mode first, e.g.:")
        print("    python src/core/server.py --synthetic --mode ssvep")
        print("...or start the mode from the console's grid. `--list` shows what IS there.")
        return 1

    # A machine with several network interfaces answers once per interface, so the same
    # outlet comes back two or three times. Count distinct source_ids, not replies, or the
    # warning below cries wolf on every single-engine setup.
    # ⚠️ Best effort only: `resolve_byprop` returns as soon as ONE stream answers
    # (`minimum=1`), so a second engine that replies a few ms later is simply not in `found`.
    # Forcing the full 10 s wait to be sure would make every normal start feel broken. When it
    # matters — a classroom — give each engine an `--id` and pick by `source_id()`.
    engines = {info.source_id(): info for info in found}
    if len(engines) > 1:
        # Genuinely several engines: a whole classroom, or a server left running. Attaching
        # to whichever answered first means reading someone else's EEG.
        print(f"WARNING: {len(engines)} engines publish '{name}'. Using the first one.")
        for source_id, info in engines.items():
            print(f"  - {source_id} on {info.hostname()}")

    inlet = StreamInlet(found[0], max_buflen=30)
    # Open the connection BEFORE the interesting data arrives. An inlet only connects on its
    # first pull, and LSL never replays what was sent before you connected: skip this and you
    # lose the first second of the recording.
    inlet.open_stream(timeout=5.0)

    labels = channel_labels(inlet)
    print(f"Connected: {inlet.info().channel_count()} channels "
          f"@ {inlet.info().nominal_srate()} Hz  {labels}")
    # Clock offset between this machine and the engine's clock. Zero when both run on the
    # same computer; add it to every timestamp when they do not.
    offset = inlet.time_correction(timeout=5.0)
    print(f"Clock offset: {offset * 1000:+.3f} ms. Ctrl+C to stop.\n")

    try:
        while True:
            sample, ts = inlet.pull_sample(timeout=5.0)
            if sample is None:
                print("(no data for 5 s — is the engine still running?)")
                continue
            # `ts + offset` is this sample's timestamp in THIS machine's `local_clock()` domain —
            # the same clock a stimulus program stamps its markers with. Print it, do not just use
            # it to compute an age: the age alone cannot be matched against anything. Scoring a
            # c-VEP session means answering "was this sample after the cue at t=12348.378?", and
            # that question needs the absolute number (docs/recette.md 2.9).
            t_abs = ts + offset
            age_ms = (local_clock() - t_abs) * 1000.0
            if args.stream == "status":
                print(f"{sample[0]}")
            else:
                values = "  ".join(f"{n}={v:7.2f}" for n, v in zip(labels, sample))
                print(f"[t={t_abs:.3f}  {age_ms:5.1f} ms old] {values}")
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
