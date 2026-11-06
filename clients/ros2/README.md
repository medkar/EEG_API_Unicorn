# ROS 2 client (UDP)

A ROS 2 package, `eeg_api_ros`, that connects to the EEG_API_Unicorn console over UDP and
publishes every decision as topics. It runs on a Raspberry Pi as on any computer with ROS 2, and
needs no LSL: the connection is the library of [`../raspberry-pi/`](../raspberry-pi/), unchanged.

| File | Role |
|---|---|
| `eeg_api_ros/config/params.yaml` | the settings of both nodes: edit this one |
| `eeg_api_ros/eeg_api_ros/bridge.py` | the bridge node: the connection, then the topics |
| `eeg_api_ros/eeg_api_ros/eeg_api_udp.py` | the UDP library (the same file as `clients/raspberry-pi/eeg_api_udp.py`) |
| `eeg_api_ros/eeg_api_ros/intent_to_twist.py` | an example node: a decoded target becomes a velocity |
| `eeg_api_ros/launch/eeg_api.launch.py` | starts both nodes with `params.yaml` |

## Build and run

Copy `eeg_api_ros/` into the `src/` folder of a colcon workspace, then:

```bash
cd ~/ros2_ws
colcon build --packages-select eeg_api_ros
source install/setup.bash
ros2 launch eeg_api_ros eeg_api.launch.py                       # bridge + intent_to_twist
ros2 launch eeg_api_ros eeg_api.launch.py with_example:=false   # the bridge alone
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
motion is the job of your own node, subscribed to `eeg/target`: `intent_to_twist` is an example.

## `params.yaml`

`eeg_api_bridge` takes the keys of the Raspberry Pi client (`app_name`, `device_id`,
`device_port`, `engine_host`, `engine_port`, `mode`, `propose_refresh_hz`, `stop_mode_on_exit`),
with one difference: the settings of the mode are a JSON text, `settings`, since a ROS parameter
cannot hold a free-form object.

`intent_to_twist` publishes a `geometry_msgs/Twist` on `cmd_vel_topic`, ten times a second:

| Key | Meaning |
|---|---|
| `linear_x` | the forward speed (m/s) of target 0, target 1… |
| `angular_z` | the turn speed (rad/s) of target 0, target 1… |
| `timeout_s` | no decision for this long: zero velocity |
| `cmd_vel_topic` | where the velocity goes (`cmd_vel`) |

`-1`, an unknown target and a decision older than `timeout_s` all give a zero velocity, and the
node publishes a zero velocity when it stops.

## Things to know

- Only the console listens to UDP; `server.py` alone does not. Modes served: `ssvep`, `mi`,
  `neuro`.
- Stopping the bridge (Ctrl+C) stops the mode it started and tells the console it leaves.
- `package.xml` carries a placeholder license and maintainer: set yours before publishing the
  package.
