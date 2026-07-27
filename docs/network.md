# Running the engine and the client on two machines

Everything works out of the box when the engine and your application run on the **same**
computer, and that is the normal case for a student. This page is for the other one: the
engine on the machine wearing the headset, your application — or an instructor watching the
signal quality — somewhere else on the network.

## How LSL finds streams

A client never knows where the engine is. It shouts a query over the network and any engine
that hears it answers. Concretely, liblsl uses:

| Purpose | Protocol and port |
|---|---|
| Discovery | **UDP 16571**, broadcast *and* multicast (224.0.0.1, 224.0.0.183, 239.255.172.215, plus IPv6) |
| Data transfer | **TCP and UDP 16572-16604** |

This is why a locked-down campus network can break it: many block multicast between hosts by
default. Nothing crashes — the client simply finds nothing.

## Both machines must be on the same subnet

Same Wi-Fi network, normally. Discovery relies on broadcast and multicast, and the addresses
involved (`224.0.0.1`, `224.0.0.183`) are *link-local*: routers never forward them between
subnets, by design. Two different VLANs, two different SSIDs, or one machine behind another
router, and discovery cannot work — that is IP, not a limitation of this tool.

**Check reachability first, it takes ten seconds:**

```powershell
ping <ip-of-the-other-machine>
```

If the ping fails, stop looking at LSL. The most common cause on campus and guest Wi-Fi is
**client isolation**: same SSID, same subnet, but the access point forbids clients from
talking to each other. Neither discovery nor the `KnownPeers` workaround can help there,
because plain unicast is blocked too.

Working alternatives, in increasing order of hassle: a phone hotspot with both machines on
it (perfect for a demo), a cable into the same switch, or a network your IT department has
opened between hosts.

## Test it before you need it

You do **not** need the headset for this. The synthetic board exercises the whole network
path, so any two laptops will do.

On machine A:

```powershell
python src/core/server.py --synthetic --id testA
```

On machine B — **you do not need the repository**. The client depends on `pylsl` and
nothing else, which is rather the point of shipping an API rather than a program:

```powershell
pip install pylsl
python -c "from pylsl import resolve_streams; [print(s.name(), s.source_id(), s.hostname()) for s in resolve_streams(wait_time=3)]"
```

Copy `examples/receiver.py` over if you want to read actual values; it imports nothing
from `src/`:

```powershell
python examples/receiver.py --list
python examples/receiver.py --stream quality
```

Expect each stream to be listed **once per network interface** on the answering machine —
same name, same `source_id`. That is normal; count distinct source ids, not lines.

If `--list` shows `EEG_API_Unicorn_raw`, `_quality` and `_status`, you are done. If it shows
nothing while the same command works on machine A itself, discovery is being blocked.

**Discovery working does not mean data flows.** Discovery is UDP 16571, transfer is TCP
16572-16604, and a firewall can allow one and block the other. Read actual values to be sure:

```powershell
python -c "from pylsl import resolve_byprop, StreamInlet, local_clock; i = StreamInlet(resolve_byprop('name','EEG_API_Unicorn_quality',timeout=5)[0]); i.open_stream(5); off = i.time_correction(timeout=5); print('clock offset %.3f s' % off); [print('age %6.1f ms  %s' % ((local_clock()-(t+off))*1000, [round(v,1) for v in s])) for s, t in (i.pull_sample(timeout=5) for _ in range(5))]"
```

## Always add the clock correction to a remote timestamp

`local_clock()` counts from each machine's own start, so two computers have unrelated
origins — an offset of *weeks* between them is perfectly normal, not a bug. `time_correction()`
returns the value to **add** to a remote timestamp to express it in your local clock:

```python
age_seconds = local_clock() - (timestamp + inlet.time_correction())
```

Forget the correction and your timestamps look absurd (measured between two machines here:
an apparent age of 45 days). This is also the whole reason LSL is worth using across
machines: it measures and corrects that offset for you, which is what makes EEG and markers
from different computers line up to the millisecond.

Measured on this network once corrected: end-to-end latency in the tens of milliseconds,
comfortably inside the 1-2 s decision window of every mode.

## When discovery is blocked

**First, the firewall.** On Windows, allow `python.exe` (and Unity, if that is your client)
on the network profile in use. A campus network is often classified as *Public*, where
Windows blocks inbound connections by default — check that profile specifically.

**If multicast is blocked at the network level**, skip discovery entirely and name the peers.
Create a file called exactly `lsl_api.cfg` — liblsl silently ignores any other name — next to
the program, or in the user or system config directory:

```ini
[lab]
KnownPeers = {192.168.1.42, 192.168.1.43}
SessionID = eeg_api_unicorn_room_b12
```

Put **both** addresses (the engine's and the client's) in `KnownPeers`, on **both** machines.
This replaces multicast with direct unicast between those hosts.

`SessionID` splits one physical network into independent groups: only machines sharing a
session id can see each other. In a classroom that is worth setting anyway — it stops one
student's engine from showing up in another's stream list, which the per-instance `--id`
alone does not prevent.

## Several engines on one network

Every engine publishes the *same stream names*; that is the point of a stable contract. What
distinguishes them is the instance id, which defaults to the headset serial number:

```powershell
python src/core/server.py --mode ssvep --id alice
```

Clients should then select on it — `examples/receiver.py` warns when more than one engine
answers, and the Unity component has an `Instance Id` field. Without this, a client attaches
to whichever engine replied first, which may well be someone else's headset, and nothing in
the data would look wrong.

Sources: [LSL network troubleshooting](https://labstreaminglayer.readthedocs.io/info/network-connectivity.html),
[lsl_api.cfg reference](https://labstreaminglayer.readthedocs.io/info/lslapicfg.html)
