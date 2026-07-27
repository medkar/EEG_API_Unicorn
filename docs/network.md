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

## Test it before you need it

You do **not** need the headset for this. The synthetic board exercises the whole network
path, so any two laptops will do.

On machine A:

```powershell
python src/server.py --synthetic --id testA
```

On machine B:

```powershell
python examples/receiver.py --list
python examples/receiver.py --stream quality
```

If `--list` shows `EEG_API_Unicorn_raw`, `_quality` and `_status`, you are done. If it shows
nothing while the same command works on machine A itself, discovery is being blocked.

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
python src/server.py --mode ssvep --id alice
```

Clients should then select on it — `examples/receiver.py` warns when more than one engine
answers, and the Unity component has an `Instance Id` field. Without this, a client attaches
to whichever engine replied first, which may well be someone else's headset, and nothing in
the data would look wrong.

Sources: [LSL network troubleshooting](https://labstreaminglayer.readthedocs.io/info/network-connectivity.html),
[lsl_api.cfg reference](https://labstreaminglayer.readthedocs.io/info/lslapicfg.html)
