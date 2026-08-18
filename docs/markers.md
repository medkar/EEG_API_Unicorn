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
own. The engine resolves it when the first marker-driven mode starts, and holds one shared inlet
for every such mode. Changing the name while the mode runs has no effect — but **stopping and
restarting the mode is enough** to pick up the new one: the inlet is released as soon as no
running mode is listening any more. You do not have to restart the engine.

If two emitters publish under the same name, the engine says so and names the one it kept. Since
everyone uses the default name and LSL reaches across the whole network, this is worth reading in
a classroom: your engine can otherwise epoch on your neighbour's flashes.

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

**How many times may a target flash?** Between `2` and `8` per round. That is not advice: the
engine **enforces** the ceiling. The ninth flash of the same target inside one round means a
`round_end` went missing, so the round is dropped rather than merged into the next one — and if
your emitter systematically runs more repetitions, *every* round is dropped. Below the floor it
refuses to decide, because six flashs are not a P300. The ceiling travels with the stream, in
`decoding/max_reps_per_target`, so you can read it instead of trusting this page. Both numbers
live in `src/core/config.py` (`P300_MIN_REPS`, `P300_REPS`) if your protocol really needs others.

**Pause between rounds.** Leave a real gap — about 2.5 s — between a `round_end` and the first
flash of the next round, and show the user something during it. Without a pause the round boundary
is visually indistinguishable from the 83 ms gap between two flashes: the user has no moment to
move their gaze, so from the second selection onward the epochs contain the gaze transition and
the engine still publishes a confident, plausible target.

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
writing your own. **It opens no headset**: it only draws and publishes markers, which is why you
can run it in a second terminal while the engine holds the one Bluetooth connection the Unicorn
allows. Anything you write yourself must keep that property.

## A complete emitter, in Python

Copy it, run it next to the engine, and you have a working loop. It opens no headset, so it can run
at the same time as the engine — that is the whole point.

```python
import json
import random
import time

from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet, local_clock

N_TARGETS, REPS = 6, 8         # REPS must stay within [2, 8] — the engine enforces it
PAUSE_BETWEEN_ROUNDS = 2.5     # let the user pick and settle on a new target

info = StreamInfo("EEG_API_Unicorn_stim", "Markers", 1, IRREGULAR_RATE, "string", "my-app")
outlet = StreamOutlet(info)

# Ask, instead of sleeping and hoping. Without this you can flash for minutes at an engine that
# was never started, or that is listening to a different stream name, with nothing to show for it.
if not outlet.wait_for_consumers(5.0):
    print("nobody is listening — is the engine running with --mode p300?")

while True:
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
        time.sleep(0.150)      # SOA — 150 ms is what the models were trained on

    outlet.push_sample([json.dumps({"mode": "p300", "event": "round_end"})],
                       timestamp=local_clock())
    # The pause is part of the protocol, not politeness — see "Pause between rounds" above.
    # Show something here: "pick your target".
    time.sleep(PAUSE_BETWEEN_ROUNDS)
```

If you stop mid-round — the user pressed escape, your app is closing — **send a `round_end`
anyway**. The engine will refuse to decide on a partial round and say so, which is better than the
ten seconds of silence it otherwise spends before declaring the round abandoned.

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

And in the stream's own metadata, under `decoding/`:

| field | meaning |
|---|---|
| `paradigm`, `n_targets` | `P300`, `6` |
| `decision_scale` | `logodds` — **not** a probability, and not a z score |
| `margin` | the 1st-vs-2nd gap required to answer anything other than `-1` |
| `max_reps_per_target` | the enforced ceiling described above |
| `no_decision_index` | `-1` |

⚠️ **`target_index = -1` means "no decision".** It is not target 0, and it is not a resting state.
The stream says so in its own metadata (`decoding/no_decision_index`), so you can read it
programmatically instead of trusting this page.

⚠️ **There is no threshold on these scores.** The engine takes the argmax; `margin` constrains the
*gap* between the best two, never an absolute value. Log-odds are usually **negative** here — a
target flashes one time in six, so the classifier says "not a target" most of the time. A client
that filters on `confidence > 0` will discard every correct answer.

This stream is **irregular and rare** — one sample per round, not a steady 5 Hz like SSVEP. A
client that waits for a regular rate waits forever.

## When something is wrong, the engine says so

This project has been bitten too often by decoders that run, publish honest-looking scores, and
simply never fire. So each of these is announced, in the engine's terminal:

| What happened | What you will see |
|---|---|
| No marker stream on the network | `marqueurs entrants : « … » pas encore là — j'attends` |
| Several emitters share that name | all of them named, and the one that was kept |
| The emitter disappeared | the inlet is released and re-resolved — relaunching your emitter works |
| A marker arrived too late to find its EEG | counted in `marqueurs_perdus` |
| A marker is stamped in the future | counted in `marqueurs_futurs` — see the clock section below |
| A marker was not readable JSON | counted in `marqueurs_illisibles` |
| Markers arrived during the 15 s warm-up | counted in `marqueurs_chauffe`, said once — they are dropped on purpose |
| `target` outside `[0, 6[` | named, with the expected range, counted in `refus_cible` |
| An epoch fell out of the buffer | counted in `epoques_perdues` |
| `round_end` with too few flashes | `target_index = -1` **and** the reason |
| No `round_end` for 10 s, or a target past its ceiling | `manche ABANDONNÉE`, counted in `manches_abandonnees` |

That last one matters if your application crashes mid-round: the engine throws the orphans away
instead of stacking your next round on top of them, which would produce a confident, wrong answer.

### Where those numbers actually are

Three places, so that "watch whether this number climbs" is something you can really do:

1. **The engine's terminal**, on its own. Each counter announces itself when it crosses `1`, `10`,
   `100`, `1000`… — the first incident is the one that explains all the others, and printing every
   one of them at 6.7 flashes per second would be as unreadable as printing none.
2. **The `EEG_API_Unicorn_status` stream**, as JSON, which any client can subscribe to:
   `marqueurs: {perdus, futurs, illisibles, inlet_erreurs, connecte}` at the engine level, and
   `refus_cible`, `epoques_perdues`, `manches_abandonnees`, `marqueurs_chauffe` inside the P300
   mode's own state.
3. **The console**, which reads the same snapshot.

`connecte` is the one to look at first. If it is `false` while your emitter is running, nothing
else in this table will ever move — the engine is not hearing you at all.

## Before any of this works: a trained model

P300 is not SSVEP. It needs a model **of your own brain** — someone else's gives plausible, wrong
answers, which is the worst of both worlds. Record one with:

```bash
python src/research/app.py     # menu -> P300 -> Calibrer
```

Each calibration writes a **new, timestamped** file (`data/p300_model_20260818_101500.joblib`); it
never overwrites the previous one. The engine offers the most recent loadable model as its default,
and the P300 page lists the others.

Until then the engine refuses to start the mode, and says why.

⚠️ Close the pygame app before starting the engine. It opens the headset itself, and the Unicorn
accepts exactly one connection. (`p300_stimulus.py` is the exception — it draws only.)

## Two machines

If your application runs on a different computer than the engine, apply `time_correction()` to your
timestamps — or rather, let the engine do it, because it already does. What you must not do is
assume the two clocks agree: `local_clock()` counts from each machine's boot, and this project has
measured **45 days** of difference between two workstations on the same bench.

A marker whose timestamp lands far in the engine's future is counted in `marqueurs_futurs` — the
engine prints it at `1`, `10`, `100`… and publishes it on the `status` stream, so you can actually
watch it (see "Where those numbers actually are" above). If it climbs, a forgotten clock correction
is the first thing to suspect: the symptom is a P300 that runs, never fires, and says nothing else.
See [network.md](network.md) for the rest.
