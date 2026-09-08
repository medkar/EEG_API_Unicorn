# Sending stimulus markers to the engine

Some paradigms only work if the engine knows **when** something happened on *your* screen. A P300
is a wave that appears roughly 300 ms after a rare, attended flash: to find it, the engine has to
cut the EEG around the exact instant that flash was drawn. It cannot guess that instant — your
application is the only thing that knows it.

This page is the contract for telling it. It is public: once your code sends these markers, we
will not change their shape under you.

> **You do not need this page for SSVEP, neuro, or Motor Imagery.** Those decode continuously and
> need nothing from you. This is for the paradigms locked to a stimulus — **P300, ErrP and c-VEP**.

**Three decoders read this stream, and they are not alike.** P300 answers *which of six targets you
chose*, once per round of flashes. ErrP answers *did the machine just get it wrong*, once per
feedback you display. c-VEP answers *which target are you fixating right now*, continuously, five
times a second. They share the transport and nothing else: different events, different streams,
different guarantees. Read the section for the one you need.

⚠️ **c-VEP is the odd one out, and it is the distinction to get right before reading further.** A
P300 or ErrP marker says *"an event happened, cut an epoch around it"* — it delimits a slice of EEG.
A c-VEP marker delimits **nothing**. It says *"at this instant the code on screen was back at its
first frame"*, and the engine uses it as a **clock**: it decodes on a sliding window like SSVEP, and
your markers are the only thing telling it where in the code that window sits. Everything else on
this page — the epoch lengths, the pauses, the refractory advice — is about the first two.

## The stream you publish

One LSL stream, discovered by the engine **by name**:

| | |
|---|---|
| name | `EEG_API_Unicorn_stim` |
| type | `Markers` |
| channels | 1 |
| format | `string` |
| sampling rate | irregular |

The name is a setting on the engine side — **Flux de marqueurs**, on the P300, ErrP and c-VEP
pages, one each. The engine resolves it when the first marker-driven mode starts, and holds one
shared inlet for every such mode. Changing the name while the mode runs has no effect — but
**stopping and restarting the mode is enough** to pick up the new one: the inlet is released as
soon as no running mode is listening any more. You do not have to restart the engine.

The dropdown lists the marker streams **visible on the network** when you open the page, plus the
default name, which is always offered. That last part matters: the documented order starts the
engine *before* the emitter, so when you first open the page nothing is publishing yet. If your
emitter is not in the list, leave the page and come back — the list is rebuilt on every entry.

Two details worth knowing, because both are traps the engine already handles for you. The engine's
own `EEG_API_Unicorn_status` stream is *also* of type `Markers`, and it is filtered out — otherwise
the engine would offer itself as a marker source and you would never receive a single usable
marker. And LSL answers once per network interface, so the same emitter arrives two or three times;
the list shows one entry per **name**, because a name is what you select. Two genuinely different
emitters sharing one name still collapse to one entry — the engine says so at resolve time and
tells you which one it kept.

If two emitters publish under the same name, the engine says so and names the one it kept. Since
everyone uses the default name and LSL reaches across the whole network, this is worth reading in
a classroom: your engine can otherwise epoch on your neighbour's flashes.

## P300 — the two events

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

## ErrP — one event

Simpler than the P300: no target, no round. One marker each time you **show the user a result**.

```json
{"mode": "errp", "event": "feedback"}
```

The engine cuts an epoch from −200 ms to +700 ms around it and answers: did the brain react as it
does when a machine gets something wrong.

**Send it for every feedback, not only the ones you think are wrong.** You are not labelling —
you are asking. The engine has no idea which of your commands was correct, and that is the point.

⚠️ **Two feedbacks closer together than 0.9 s produce overlapping epochs**, so the same ErrP can be
scored twice. That is a property of the signal, not a bug we hide: the engine publishes both
verdicts and lets you decide. If your protocol can display results that fast, space them or expect
the duplication.

**The refractory period is yours, not ours.** After a detected error you probably want to ignore
the next second or so — that decision belongs to your application, which knows its own command
cadence. The engine publishes what it sees and never cancels anything.

## c-VEP — one event, and it is a clock

```json
{"mode": "cvep", "event": "cycle", "refresh": 60.0}
```

Send it **every time the code restarts** — every 63 frames, so roughly once per second (1.05 s at
60 Hz). Nothing is epoched around it. It tells the engine one thing: *at this instant, the displayed
code was back at frame 0*. From there the engine extrapolates, at `refresh` Hz, where the code is at
any later moment. That position is the **phase**, and without it there is nothing to correlate
against — the mode publishes `-1` forever and counts it under `sans_reference`.

**`refresh` is mandatory, and it must be a number.** Not a string, not `true` — `true` would pass
for 1 Hz in most languages, so the engine checks the type explicitly. A marker without a usable
`refresh` is refused, counted in `marqueurs_refuses`, and announced in the engine's terminal at
1, 10, 100, 1000 refusals. It is announced by tiers rather than every time because these arrive at
~1 Hz, and a misconfigured emitter gets *all* of them refused.

⚠️ **A `refresh` that disagrees with the model by more than 1 Hz is refused too — and the mode does
not stop.** This one is deliberate and it is worth understanding, because the failure it prevents is
invisible. A model is calibrated at one refresh rate; the emitter is the side that owns the screen,
so the engine cannot know the rate until a marker arrives. Without the check, a 144 Hz screen
announcing 60 would be accepted, the phase would drift inside every cycle, correlations would sag,
and **nothing would ever fire** — indistinguishable from a student who is not fixating. So: markers
refused, reason printed, mode still running and still publishing `-1`. Do not wait for a crash; read
the engine's first lines.

The engine's own message names the fix — recalibrate, or relaunch the emitter with the model's
refresh rate.

**Stop sending, and the clock goes stale.** After **3 cycles** without a new marker (3.15 s at
60 Hz, 63 frames per cycle) the engine declares its phase reference expired and stops decoding,
counting `reference_perimee`. It does not coast: on a code only 63 frames long, a small clock drift
between screen and engine eats a frame fast, and a wrong phase produces perfectly normal-looking
correlations. Send one marker per cycle and this never comes up.

**Unlike P300 and ErrP, c-VEP markers sent during the warm-up are *kept*.** Those two drop
everything until the engine has settled, because an epoch cut while the DC offset is still drifting
is worthless. A clock does not need to be good to be on time, so the c-VEP mode banks them: its
marker cursor keeps up (otherwise the backlog would count as genuinely lost markers at every start),
and the first decoded window gets a fresh phase instead of waiting up to 1.05 s for the next one.
Keep flickering through the 15 s warm-up.

**One target must be fixated, and the engine never learns which.** While *decoding*, the marker
carries `{mode, event, refresh}` and nothing else — no target field, deliberately. If you are
running a session you intend to score, your emitter has to log which target it asked for, with the
LSL timestamp, on its own side. `src/stimulus/cvep.py --log seance.jsonl` writes exactly that, one
JSON line per cue. (While *calibrating* there is a target field, on a separate `cue` event — see
[Training a model through the markers](#training-a-model-through-the-markers) below. The clock
marker itself never carries one.)

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

**For c-VEP the same line is stricter still**, because the marker is a clock rather than an event:
the flip you stamp must be the one that showed **frame 0 of the code**, not frame 62 and not frame 1.
One frame early shifts every phase the engine reconstructs, and it never recovers — each new marker
re-establishes the same wrong offset.

```python
        pygame.display.flip()
        if frame % len(code) == 0:
            outlet.push_sample([json.dumps({"mode": "cvep", "event": "cycle",
                                            "refresh": refresh})], local_clock())
```

Lock the flicker to vsync while you are at it. The engine extrapolates the phase at `refresh` Hz
between two markers; without vsync the screen draws at whatever rate the CPU allows, and the
reconstructed phase is wrong from the second frame on, with no exception to tell you.

`src/stimulus/p300.py`, `src/stimulus/errp.py` and `src/stimulus/cvep.py` are the reference
implementations of this gesture — read one before writing your own. **They open no headset**: they
only draw and publish markers, which is why you can run one in a second terminal while the engine
holds the one Bluetooth connection the Unicorn allows. Anything you write yourself must keep that
property.

Those three files are a package of their own, `src/stimulus/`, and the boundary is enforced by
`python src/core/server.py --smoke`: they may import `core`, never `research` and never the console.
The engine, for its part, never imports them — it must run on a machine with no screen.

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

### From the P300

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
| Markers arrived during the warm-up (**15 s for P300; 15 s + 8 s of rest = 23 s for ErrP**) | counted in `marqueurs_chauffe`, said once — they are dropped on purpose. **c-VEP is the exception: it keeps them** |
| `target` outside `[0, 6[` | named, with the expected range, counted in `refus_cible` |
| An epoch fell out of the buffer | counted in `epoques_perdues` |
| `round_end` with too few flashes | `target_index = -1` **and** the reason |
| No `round_end` for 10 s, or a target past its ceiling | `manche ABANDONNÉE`, counted in `manches_abandonnees` |
| A c-VEP `cycle` marker has no usable `refresh`, or one the model was not calibrated at | refused and named, counted in `marqueurs_refuses`, printed at 1/10/100/1000 |
| No c-VEP clock for 3 cycles (3.15 s at 60 Hz) | the phase reference expires, counted in `reference_perimee` |

That last one matters if your application crashes mid-round: the engine throws the orphans away
instead of stacking your next round on top of them, which would produce a confident, wrong answer.

### Where those numbers actually are

Three places, so that "watch whether this number climbs" is something you can really do:

1. **The engine's terminal**, on its own. Each counter announces itself when it crosses `1`, `10`,
   `100`, `1000`… — the first incident is the one that explains all the others, and printing every
   one of them at 6.7 flashes per second would be as unreadable as printing none.
2. **The `EEG_API_Unicorn_status` stream**, as JSON, which any client can subscribe to:
   `marqueurs: {perdus, futurs, illisibles, inlet_erreurs, connecte}` at the engine level;
   `refus_cible`, `epoques_perdues`, `manches_abandonnees`, `marqueurs_chauffe` inside the P300
   mode's own state; and `epoques_perdues`, `epoques_vues`, `artefacts`, `taux_rejet`,
   `marqueurs_chauffe`, `point_de_fonctionnement` inside the ErrP mode's own state — **those three
   counts are scoped to the current rest baseline and reset when you redo the rest**, so the session
   totals live separately, under `epoques_vues_session` and `artefacts_session`, which never reset.
   `taux_rejet` is the ErrP one to watch: above 50 % it is telling you about the electrodes, not
   about the brain. Log it as a session figure and you will see it drop to `null` and restart from
   zero with nothing to explain why. The c-VEP mode's own state carries the five counters that
   partition its windows plus `marqueurs_refuses` and three live gauges — see
   [From the c-VEP](#from-the-c-vep) for what each one means and what to do about it.
3. **The console**, which reads the same snapshot.

`connecte` is the one to look at first. If it is `false` while your emitter is running, nothing
else in this table will ever move — the engine is not hearing you at all.

### From the ErrP

One sample per `feedback`, on `EEG_API_Unicorn_decoded_errp`:

| channel | meaning |
|---|---|
| `error` | `1` an error was detected · `0` nothing · **`-1` no verdict** |
| `score` | log-odds of "error" — unbounded, not comparable between people |
| `threshold` | the current decision threshold |
| `artifact` | `1` if the epoch was rejected |

⚠️ **`-1` is not `0`.** It means the engine could not judge — the epoch fell outside the buffer, or
was rejected because the signal moved too much. A blink at the exact moment a machine gets
something wrong is the *common* case, not the rare one, so this happens. Publishing `0` there would
claim there was no error when nothing was seen.

⚠️ **Read the operating point before you trust `error = 1`.** The stream carries it, under
`decoding/`: `tnr_target` (what was asked), `tpr_measured` and `tnr_measured` (what it actually
achieves), plus `calibration_epochs` and `measured_on`. At the default setting this detector
**catches one error in two, and cancels one good command in seven**. That is a useful hint and a
terrible verdict. Design accordingly.

The trade-off is real and there is no free lunch anywhere on it — measured on the reference
session, 200 trials, one person:

| you ask for this | you actually keep this share of good commands | you catch this share of errors |
|---|---|---|
| 95 % | 95.7 % | 24 % |
| 90 % | 91.3 % | 40 % |
| **85 %** *(default)* | **85.5 %** | **50 %** |
| 80 % | 81.2 % | 60 % |
| 70 % | 70.3 % | 71 % |

You choose where to sit with the **Bonnes commandes gardées** setting (share of good commands kept)
on the ErrP page. You ask for a rate, not a threshold — the engine derives the threshold from your
own calibration, and announces the rate it actually reached at start-up.

The middle column is not padding. The engine picks the lowest threshold whose measured rate is *at
least* what you asked for, so on the calibration data what you get is at or above what you asked
for. Asking for 95 % does not put you at the 24 % row by rounding. Read the number the engine
prints, not the number you typed.

⚠️ **But those two numbers are themselves optimistic, and the stream says so.** Its `measured_on`
field reads *"threshold picked on these same out-of-fold scores, so tpr/tnr are optimistic"*. The
scores are out-of-fold — that part is honest, and it is why the AUC of 0.776 means something — but
the **threshold** was chosen by looking at them. So `tnr_measured ≥ tnr_target` holds *by
construction* on the 200 trials of the reference session, and not on yours. On live data the middle
column is an estimate, not a floor: expect to cancel **more** good commands than it says, not fewer.

This is the one number in this page you should distrust, and it is worth saying why it is published
anyway: a client that knows the operating point is roughly one-in-two and roughly one-in-seven can
design around it. A client that knows nothing treats `error = 1` as a verdict.

### From the c-VEP

Continuous, about **5 samples per second** — one per decoded window, not one per marker — on
`EEG_API_Unicorn_decoded_cvep`. Ten channels at the repository's six targets:

| channel | meaning |
|---|---|
| `target_index` | the fixated target, **or `-1`** |
| `confidence` | mean correlation of the windows that voted for the winner |
| `score_0` … `score_5` | one correlation per target, in index order, **for the last window alone** |
| `corr_min`, `margin` | the two thresholds actually in force **for this decision** |

And in the stream's metadata, under `decoding/`:

| field | meaning |
|---|---|
| `paradigm`, `n_targets` | `c-VEP`, `6` |
| `decoder` | `eCCA` or `rCCA` — the model file declares it, the engine does not choose |
| `decision_scale` | `correlation` — a Pearson r in `[-1, 1]`. **Not** the SSVEP z, **not** the P300 log-odds |
| `corr_min`, `margin` | the winner must clear `corr_min` **and** beat the runner-up by `margin` |
| `min_votes`, `vote_len` | and `min_votes` of the last `vote_len` windows must agree |
| `code_len`, `refresh` | the stimulus geometry the model was trained on — 63 frames at 60 Hz |
| `cv` | leave-one-out accuracy of the calibration, or **empty** if the model carries none |
| `no_decision_index` | `-1` |

⚠️ **`corr_min` and `margin` appear twice on purpose, and the two do not say the same thing.** LSL
freezes stream metadata when the stream opens, and these two thresholds can be retuned *mid-session*
without rebuilding the stream. So the metadata copy describes what was in force **when the stream
opened**; the two **channels** of the same name carry what was in force **for that individual
sample**. Read the metadata to know how the session was set up. Read the channels when you are
scoring a recording six months later without its LSL description — that is the case this exists for.
ErrP does the same thing with its `threshold` channel, for the same reason.

⚠️ **`confidence` and `score_*` describe different instants.** `confidence` describes the *vote*:
the mean correlation of the windows that agreed. The `score_*` describe the *last window alone*. So
while your gaze moves from one target to the next, it is normal to read a high `score_4` beside a
`target_index` of 2 — the vote has not swung yet. Filter on `confidence`, never on `score_*`.

⚠️ **`target_index = -1` here has four distinct causes, and they call for opposite actions.** The
stream carries only the `-1`; the counters that separate them are in the engine's state (the
`status` stream, or the console):

| counter | what happened | what to do |
|---|---|---|
| `sans_reference` | no clock marker has ever arrived | start the emitter; check the stream name |
| `reference_perimee` | the clock went silent — emitter crashed, window closed | restart the emitter |
| `sous_les_seuils` | it decoded, but nothing cleared `corr_min`/`margin` | check contact, add saline, fixate *one* target |
| `vote_non_conclu` | something cleared them, but recent windows disagree | hold the gaze still |

Those four plus `decodages` (windows that did name a target) **partition** every window processed:
each window increments exactly one. `marqueurs_refuses` counts *markers*, not windows, so it is not
part of that sum. Three more gauges describe the last window only: `age_reference_s` (is the clock
alive?), `corr_gagnant` and `corr_second` (how high are the correlations actually landing?).

"It is not detecting" without the cause sends you looking in the wrong place, and a headset session
does not repeat. Read the counters first.

## Before any of this works: a trained model

None of these three is SSVEP. All need a model **of your own brain** — someone else's gives
plausible, wrong answers, which is the worst of both worlds. Until you have one the engine refuses
to start the mode, and says why.

**Recording one is a button.** Open the console (`outils\Console EEG.bat`, or
`python src/console/app.py`), go to the mode's page and click **Calibrer**; read the briefing, then
**Commencer**. A link check stands between that click and anything expensive — per-channel σ, and a
refusal if any of the eight channels is outside [0.5, 500] µV. Past it, the console tells the engine
to start the session and launches the stimulus window itself, in that order. When it is over you see
the figure the session actually earned, and *then* decide: **Enregistrer le modèle** or **Refaire**.
Nothing reaches `data/` before that click — the engine offers the most recent loadable model as a
default, so a bad calibration saved automatically would silently become everyone's default.

(The console's own labels are in French; the rest of this page is not, because the marker contract
is what a third-party application implements.)

Each calibration writes a **new, timestamped** file — `data/p300_model_20260818_101500.joblib`,
`data/errp_model_20260819_142230.joblib`, `data/cvep_model_20260821-093000.npz` — and **never
overwrites the previous one**. Each mode's page lists the others. The timestamp goes down to the
second, so the only way to lose a model is to finish two calibrations within the same second, which
a multi-minute protocol makes hard.

The c-VEP calibration is the one that writes **two** models from a single recording: it trains both
decoders on the same epochs and saves each (`cvep_model_*.npz` for eCCA, `cvep_rcca_model_*.npz` for
rCCA). Both show up in the mode's model list; the file itself declares which decoder it is, so
picking a model is picking an algorithm without having to think about it. On the reference session
the two were **indistinguishable** — 37 paired decisions, 8 of them discordant, McNemar p = 0.727 —
so there is no default worth arguing about yet.

⚠️ **A mode and its own calibration cannot run at the same time**, and the engine refuses both
orders. They would read the same marker queue under the same mode id, so each would see a random
half of it — two silent, wrong decodings and no error anywhere. The console stops the mode for you
before opening its calibration; you restart it afterwards, which you would do anyway to pick up the
new model.

⚠️ Run only one program that opens the headset: the console, or the engine, or an archived screen
from [`archive/`](../archive/README.md). The Unicorn accepts exactly one connection. The three
windows in `src/stimulus/` are the exception — they draw only.

## Training a model through the markers

Everything above is about *decoding*. This section is the other half of the contract, and it is new
on 2026-09-08: **the same marker stream can now train the model, not just use it.** The engine plays
the calibration; the window that owns the screen plays the timeline. If your application can render
the stimulus, it can train a model — the protocol is no longer locked to our pygame windows.

The engine is **passive** here. It shows nothing, draws no cue, counts no trial. It waits for the
window to announce itself, banks the markers, cuts an epoch around the ones that delimit one — with
**the same call the decoder uses**, so the training alignment cannot drift from the decoding one —
and trains when the window says the session is over.

### The three events

```json
{"mode": "p300", "event": "calib_start", "trials": 576}
{"mode": "p300", "event": "cue", "target": 3}
{"mode": "p300", "event": "calib_end"}
```

**`calib_start`** — *the window is alive, and here is what it promises.* Send it **before** you
start showing anything: the engine keeps it through its 15 s warm-up (it is the only marker that
survives that phase), and it has a 30 s deadline after which it declares the window absent and
cancels the session, naming both possible causes — window not launched, or publishing under a
different stream name.

⚠️ **`trials` counts EPOCHS, not rounds.** It is the unit the engine increments: one recorded epoch,
one trial. A P300 session of 12 rounds × 6 targets × 8 repetitions announces **576**, not 12. The
wrong unit does not break anything — it shows a false progress bar, and it mis-tunes the dead-window
detector described below. `trials` must be a real number: `true` is rejected on purpose, because
`bool` subclasses `int` in Python and a 300-epoch session would then be declared complete at its
first epoch.

**`cue`** — *the ground truth of this round.* It carries the target the screen has just designated,
and it is the one thing decoding never gives the engine. It is stamped **after the flip that showed
it**, exactly like a flash, and for the same reason. It labels; it does not delimit — the epoch is
still cut around the `flash` (P300) or the `cycle` (c-VEP) that follows.

**`calib_end`** — *the session is over, train now.* This is the **only** trigger for training.

⚠️ **An interrupted session must NOT send `calib_end`.** If the user hits escape, or your emitter
exits early, stay silent: the engine will train nothing and say so. A model learnt on a third of a
session is indistinguishable from a complete one in the console's model list, and everything
downstream then rests on it. All three reference windows behave this way.

### What each mode expects, exactly

| mode | announces | labels with | epoch is cut at | closes with |
|---|---|---|---|---|
| **P300** | `calib_start` | `cue` (`target`) | each `flash` | `round_end` per round, then `calib_end` |
| **ErrP** | `calib_start` | **the `feedback` itself** (`error`) | each `feedback` | `calib_end` |
| **c-VEP** | `calib_start` | `cue` (`target`) | each `cycle` | `block_end` per block, then `calib_end` |

⚠️ **ErrP does not use `cue`, and that asymmetry is deliberate.** Its label rides on the event that
delimits the epoch:

```json
{"mode": "errp", "event": "feedback", "error": true}
```

`error` exists **in calibration only**. ErrP is a *passive* BCI: its whole job is to work out from
the EEG alone that the machine got something wrong. The field is the ground truth — required to
label training epochs, forbidden while decoding. An emitter that published it during decoding would
be handing the engine the answer, and **nothing would signal it**: `decoded_errp` would keep exactly
the same shape, the scores would stay plausible, and every claim this product makes about that mode
would become false. Build the marker in one place, and test both directions.

⚠️ And publish the label of the step **actually displayed**, not the one your random draw decided.
In the reference track a "deliberate error" drawn at the edge bounces the cursor *toward* its goal,
so the user experiences no error at all: it is published `error: false`. The label follows the
effect, never the intention.

⚠️ **c-VEP keeps its clock running throughout.** Its `cycle` markers do not stop during calibration,
not even between two blocks while the gaze is looking for the next circled target. Without the clock
there is no phase, so there is no epoch to label — the mode would not train badly, it would not
train at all. `block_end` closes a block and makes the engine forget the target: the few cycles
spent moving the gaze then belong to no block, instead of inheriting the previous one's label —
same number of epochs, plausible proportions, and a model trained on a lie.

⚠️ **Order matters at a cycle boundary**: `cycle`, then `block_end`, then `cue`. The `cycle` marker
closes the cycle that just *ended*. Publishing the `cue` before it would let one epoch per block —
recorded while the gaze was still moving — into the training set.

### The three ways a session is abandoned

The engine drops the whole session rather than train on part of it. All three go through the same
door, print the reason, and free the epochs:

| what happened | how long | what you see |
|---|---|---|
| no `calib_start` arrived | 30 s | *"the stimulus window did not launch, or it publishes under a name other than …"* |
| markers stopped mid-session | 15 s of silence | *"N trial(s) recorded out of the M announced — nothing is trained or saved"* |
| the user clicked **Abandonner** | — | the same path, no reason |

One case is frozen on purpose: if **every announced trial arrived** but `calib_end` was lost, the
engine **waits** instead of dropping minutes of good signal — and instead of training on its own,
which would be a second source of truth about when a session ends. It says so once; **Abandonner**
is the way out.

⚠️ Markers received during the 15 s warm-up are **dropped and counted** (`marqueurs_chauffe`), for
the same reason epochs are dropped during decoding: the Unicorn's DC offset is still ramping and
those epochs are worthless. `calib_start` is the one exception — it is banked, so your window does
not have to guess how long the warm-up is in order not to be declared absent. A window that starts
its first trial immediately loses that many epochs; the three reference windows wait.

⚠️ **The c-VEP is a known false alarm here, and it is worth recognising rather than chasing.** Its
window keeps flickering — and keeps publishing `cycle` — right through the warm-up, on purpose: a
clock does not need to be good to be on time. The engine counts those ~14 clock markers under
`marqueurs_chauffe` and prints *"the window should wait before its first trial"*. It already does:
no block starts before the warm-up ends. The message is wrong; nothing else is.

### What this buys you

A third-party application that already renders the stimulus can now **train the model too**, without
this repository's pygame anywhere in the loop. Four things are required of it, and they are the same
four the reference windows meet:

1. stamp every marker **after** the flip that showed the frame (the section above);
2. announce a truthful `trials` **in epochs**, before the stimulus starts;
3. send `calib_end` **only** on a complete session;
4. open **no** headset — the engine holds the one connection the Unicorn allows.

**Two things this section cannot promise, and they belong here rather than in a design document
nobody outside this repository reads.** This path has **never been run against a headset** -- the
engine's own autotests prove the wiring, not the decoding -- and **no third-party application has
used it yet**. The three windows in `src/stimulus/` are the only emitters that have ever driven it,
and they were written here.

Nothing else is needed for the protocol itself. The epochs never travel: they are cut by the engine, out of its own buffer,
by the same code path that cuts them while decoding. That is the point of doing it this way —
training and decoding cannot disagree about where an epoch starts, because there is only one place
where that is decided.

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
