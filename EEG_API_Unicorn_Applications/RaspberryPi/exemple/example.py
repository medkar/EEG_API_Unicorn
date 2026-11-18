"""A complete device: announces itself, is connected by the console, sends the settings of
config.json, then calls on_decision() for every decision. When the console disconnects it, it
announces itself again. Replace on_decision() (and on_identify()) with what your device does.

    python3 example.py                # Ctrl+C to stop: the mode it started is stopped
"""

import sys

from eeg_api_udp import EegApiDevice, EegApiError, config_path, load_config


def on_decision(decision):
    """Your device. `decision` holds "mode", then the channels of the mode's decoded stream, by
    name: SSVEP target_index, freq_hz, confidence; MI intent_index, confidence, p_0, p_1…;
    Neuro charge, somnolence, engagement, artifact. Every value is a number; -1.0 means
    "no decision"."""
    index = decision.get("target_index", decision.get("intent_index"))
    if index is not None and index >= 0:
        print(f"decision: {int(index)}  ({decision})")


def on_identify():
    """"Identify" in the console: show which device this is (blink a LED, for example)."""
    print("IDENTIFY: this is the device")


def main():
    device = EegApiDevice(load_config(config_path()), on_identify=on_identify)
    try:
        while True:                 # announce again after each disconnection
            device.connect()
            try:
                device.start()
            except EegApiError as e:
                print(f"FAILED: {e}")
                return 1
            for decision in device.decisions():
                on_decision(decision)
    except KeyboardInterrupt:
        return 130
    finally:
        device.close()


if __name__ == "__main__":
    sys.exit(main())
