"""Hello world: receive an EEG_API_Unicorn stream from Python.

This is the smallest useful client. Start the engine in one terminal:

    python src/core/server.py --synthetic

then run this in another:

    python examples/receiver.py                       # signal quality, one line per second
    python examples/receiver.py --stream raw          # the 8 raw channels
    python examples/receiver.py --stream decoded_ssvep  # which target is being looked at
    python examples/receiver.py --list                # what is currently on the network

The decoded stream only appears once the engine finishes its short rest measurement, so
start the engine with --mode ssvep and give it a few seconds before looking for it.

The only dependency is `pylsl`. The same three steps (resolve, open, pull) work identically
in Unity (LSL4Unity), MATLAB and C++ — that is the whole point of using LSL.
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
                   help="suffix: raw | quality | status | decoded_ssvep")
    p.add_argument("--list", action="store_true", help="list visible LSL streams and exit")
    args = p.parse_args(argv)

    if args.list:
        return list_streams()

    name = f"{PREFIX}_{args.stream}"
    print(f"Looking for '{name}'...")
    found = resolve_byprop("name", name, timeout=10.0)
    if not found:
        print(f"Not found. Start the engine first:  python src/core/server.py --synthetic")
        return 1

    # A machine with several network interfaces answers once per interface, so the same
    # outlet comes back two or three times. Count distinct source_ids, not replies, or the
    # warning below cries wolf on every single-engine setup.
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
            age_ms = (local_clock() - (ts + offset)) * 1000.0
            if args.stream == "status":
                print(f"{sample[0]}")
            else:
                values = "  ".join(f"{n}={v:7.2f}" for n, v in zip(labels, sample))
                print(f"[{age_ms:5.1f} ms old] {values}")
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
