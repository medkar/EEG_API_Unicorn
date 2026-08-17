# Sending stimulus markers to the engine

Some paradigms only work if the engine knows **when** something happened on *your* screen. A P300
is a wave that appears roughly 300 ms after a rare, attended flash: to find it, the engine has to
cut the EEG around the exact instant that flash was drawn. It cannot guess that instant — your
application is the only thing that knows it.

This page is the contract for telling it. It is public: once your code sends these markers, we
will not change their shape under you.

> **You do not need this page for SSVEP, neuro, or Motor Imagery.** Those decode continuously and
> need nothing from you. This is for the paradigms locked to a stimulus — P300 today, ErrP later.

## The stream you publish

One LSL stream, discovered by the engine **by name**:

| | |
|---|---|
| name | `EEG_API_Unicorn_stim` |
| type | `Markers` |
| channels | 1 |
| format | `string` |
| sampling rate | irregular |

The name is a setting on the engine side (`Marker stream` on the P300 page), so you may use your
own — but the engine resolves it **once, when the first marker-driven mode starts in that engine
process**. Changing it later means restarting the engine, not just the mode.

## The two events

Each sample is one JSON object. Verbose on purpose: you should be able to read the stream in a
terminal and understand it without this page.

```json
{"mode": "p300", "event": "flash", "target": 3}
{"mode": "p300", "event": "round_end"}
```

**`flash`** — a target has just been drawn. `target` is a **0-based index** in `[0, 6[`, so `0` to
`5`. The engine cuts an epoch from −150 ms to +800 ms around the marker's timestamp.

**`round_end`** — your selection sequence is over; decide now. This is **explicit on purpose**. You
know when your sequence ends; the engine could only guess, and it would guess wrong the day you
change your protocol.

`mode` says which decoder the marker is for. A marker addressed to another mode is ignored in
silence — that is the only silent rejection in the whole pipeline, and it is normal. Unknown fields
are kept, not refused, so the protocol can grow without breaking emitters that already exist.

## Where you take the timestamp — the one thing that matters

Everything else on this page is bookkeeping. This is the part that decides whether the decoding
works at all.

**Take the timestamp immediately after the frame is on screen**, not when you decided which target
to flash, and not before you drew it:

```python
        pygame.display.flip()
        # HERE. Not one line earlier.
        outlet.push_sample([json.dumps({"mode": "p300", "event": "flash", "target": i})],
                           timestamp=local_clock())
```

At 60 Hz one frame is 16.7 ms. A payload that is perfectly correct but stamped 40 ms early shifts
**every** epoch by two or three frames, and the decoder then averages a response that had not
happened yet. Nothing errors. Scores keep coming out. They are just noise, and they look exactly
like a subject who is not concentrating.

`src/research/p300_stimulus.py` is the reference implementation of this gesture — read it before
writing your own.

## A complete emitter, in Python

Copy it, run it next to the engine, and you have a working loop. It opens no headset, so it can run
at the same time as the engine — that is the whole point.

```python
import json
import random
import time

from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet, local_clock

N_TARGETS, REPS = 6, 8

info = StreamInfo("EEG_API_Unicorn_stim", "Markers", 1, IRREGULAR_RATE, "string", "my-app")
outlet = StreamOutlet(info)
print("waiting for the engine to find us...")
time.sleep(2.0)

ordre = []
for _ in range(REPS):
    bloc = list(range(N_TARGETS))
    random.shuffle(bloc)
    # Never let a target follow itself across the seam: an immediate repeat blunts the very
    # surprise the P300 is made of.
    while ordre and bloc[0] == ordre[-1]:
        random.shuffle(bloc)
    ordre.extend(bloc)

for cible in ordre:
    # ... draw target `cible` highlighted, then present the frame ...
    outlet.push_sample([json.dumps({"mode": "p300", "event": "flash", "target": cible})],
                       timestamp=local_clock())
    time.sleep(0.150)          # SOA — 150 ms is what the models were trained on

outlet.push_sample([json.dumps({"mode": "p300", "event": "round_end"})],
                   timestamp=local_clock())
```

## The same thing in Unity (C#)

Using [LSL4Unity](https://github.com/labstreaminglayer/LSL4Unity). ⚠️ Written against the verified
API but **never run in Unity on this machine** — the same caveat as `examples/unity/`. Tell us if
it needs fixing.

```csharp
using LSL;
using UnityEngine;

public class P300MarkerSender : MonoBehaviour
{
    private StreamOutlet outlet;

    void Start()
    {
        var info = new StreamInfo("EEG_API_Unicorn_stim", "Markers", 1,
                                  LSL.IRREGULAR_RATE, channel_format_t.cf_string, "unity-app");
        outlet = new StreamOutlet(info);
    }

    // Call this from the END of the frame in which the target lit up.
    // In Unity that means a coroutine yielding on WaitForEndOfFrame, NOT Update().
    public void SendFlash(int target)
    {
        string payload = $"{{\"mode\":\"p300\",\"event\":\"flash\",\"target\":{target}}}";
        outlet.push_sample(new string[] { payload }, LSL.local_clock());
    }

    public void SendRoundEnd()
    {
        outlet.push_sample(new string[] { "{\"mode\":\"p300\",\"event\":\"round_end\"}" },
                           LSL.local_clock());
    }
}
```

## What you get back

The engine publishes one sample per `round_end`, on `EEG_API_Unicorn_decoded_p300`:

| channel | meaning |
|---|---|
| `target_index` | the selected target, **or `-1`** |
| `confidence` | mean log-odds of the winner — unbounded, not comparable between people |
| `n_flashes` | how many epochs the decision rests on |
| `score_0` … `score_5` | one score per target, in index order |

⚠️ **`target_index = -1` means "no decision".** It is not target 0, and it is not a resting state.
The stream says so in its own metadata (`decoding/no_decision_index`), so you can read it
programmatically instead of trusting this page.

This stream is **irregular and rare** — one sample per round, not a steady 5 Hz like SSVEP. A
client that waits for a regular rate waits forever.

## When something is wrong, the engine says so

This project has been bitten too often by decoders that run, publish honest-looking scores, and
simply never fire. So each of these is announced, in the engine's terminal:

| What happened | What you will see |
|---|---|
| No marker stream on the network | `marqueurs entrants : « … » pas encore là — j'attends` |
| A marker arrived too late to find its EEG | counted in `marqueurs_perdus` |
| A marker is stamped in the future | counted in `marqueurs_futurs` — see the clock section below |
| `target` outside `[0, 6[` | named, with the expected range |
| `round_end` with too few flashes | `target_index = -1` **and** the reason |
| No `round_end` for 10 s, or too many flashes | `manche ABANDONNÉE` — the round is dropped rather than mixed into the next one |

That last one matters if your application crashes mid-round: the engine throws the orphans away
instead of stacking your next round on top of them, which would produce a confident, wrong answer.

## Before any of this works: a trained model

P300 is not SSVEP. It needs a model **of your own brain** — someone else's gives plausible, wrong
answers, which is the worst of both worlds. Record one with:

```bash
python src/research/app.py     # menu -> P300 -> Calibrer
```

Until then the engine refuses to start the mode, and says why.

## Two machines

If your application runs on a different computer than the engine, apply `time_correction()` to your
timestamps — or rather, let the engine do it, because it already does. What you must not do is
assume the two clocks agree: `local_clock()` counts from each machine's boot, and this project has
measured **45 days** of difference between two workstations on the same bench.

A marker whose timestamp lands far in the engine's future is counted in `marqueurs_futurs`. If that
number climbs, a forgotten clock correction is the first thing to suspect. See
[network.md](network.md) for the rest.
