"""A complete application: connects to the engine with the settings of config.json, then calls
on_decision() for every decision. Replace on_decision() with what your application does.

    pip install pylsl
    python example.py                 # Ctrl+C to stop: the mode it started is stopped
"""

import sys

from eeg_api_lsl import EegApi, EegApiError, config_path, load_config


def on_decision(decision):
    """Your application. `decision` holds the channels of the mode's decoded stream, by name:
    SSVEP target_index, freq_hz, confidence; MI intent_index, confidence, p_0, p_1…; Neuro
    charge, somnolence, engagement, artifact (docs/control.md). -1 means "no decision"."""
    index = decision.get("target_index", decision.get("intent_index"))
    if index is not None and index >= 0:
        print(f"decision: {int(index)}  ({decision})")


def main():
    api = EegApi(load_config(config_path()))
    try:
        api.connect()
        api.start()
        for decision in api.decisions():
            on_decision(decision)
    except EegApiError as e:
        print(f"FAILED: {e}")
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        api.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
