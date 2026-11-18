# ROS 2 client (UDP)

A ROS 2 package, `eeg_api_ros`, whose bridge node connects to the EEG_API_Unicorn console over UDP
and publishes every decision as topics. It runs on a Raspberry Pi as on any computer with ROS 2,
and needs no LSL. This folder is the bridge alone, for your own nodes; for a complete example (a
decoded target becomes a velocity on `cmd_vel`), see [`../exemple/`](../exemple/).

| File | Role |
|---|---|
| `eeg_api_ros/config/params.yaml` | the settings of the bridge: edit this one |
| `eeg_api_ros/eeg_api_ros/bridge.py` | the bridge node: the connection, then the topics |
| `eeg_api_ros/eeg_api_ros/eeg_api_udp.py` | the UDP library (the same file as the Raspberry Pi client's) |
| `eeg_api_ros/launch/eeg_api.launch.py` | starts the bridge with `params.yaml` |

## Build and run

Copy `eeg_api_ros/` into the `src/` folder of a colcon workspace, then:

```bash
cd ~/ros2_ws
colcon build --packages-select eeg_api_ros
source install/setup.bash
ros2 launch eeg_api_ros eeg_api.launch.py
```

`params.yaml` is installed with the package: after editing it, run `colcon build` again (or
build with `--symlink-install` once).

The bridge announces itself every second. In the console: **Connect an application**, pick
`my-robot` (shown with its identifier), then **Connect**.

## Topics of the bridge

| Topic | Type | Content |
|---|---|---|
| `eeg/decision` | `std_msgs/String` | the whole decision, as JSON: `{"mode": "ssvep", "target_index": 1.0, "freq_hz": 15.0, …}` |
| `eeg/target` | `std_msgs/Int32` | `target_index` (SSVEP) or `intent_index` (MI); `-1` = no decision, never target 0 |
| `eeg/confidence` | `std_msgs/Float32` | the score of the decision |
| `eeg/state` | `std_msgs/String` | `announcing`, `connected`, `decoding`, `disconnected`, `failed` |

The bridge publishes an intent ("target 1 is looked at"), never a robot command. Turning it into a
motion is the job of your own node, subscribed to `eeg/target`.

## `params.yaml`

`eeg_api_bridge` takes the keys of the Raspberry Pi client (`app_name`, `device_id`,
`device_port`, `engine_host`, `engine_port`, `mode`, `propose_refresh_hz`, `stop_mode_on_exit`),
with one difference: the settings of the mode are a JSON text, `settings`, since a ROS parameter
cannot hold a free-form object.

## Things to know

- Only the console listens to UDP; `server.py` alone does not. Modes served: `ssvep`, `mi`,
  `neuro`.
- Stopping the bridge (Ctrl+C) stops the mode it started and tells the console it leaves.
- `package.xml` carries a placeholder license and maintainer: set yours before publishing the
  package.
