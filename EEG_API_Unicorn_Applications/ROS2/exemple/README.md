# ROS 2 example (UDP)

A complete ROS 2 application: the bridge connects to the EEG_API_Unicorn console over UDP, and an
example node turns the decoded target into a velocity on `cmd_vel`. It runs on a Raspberry Pi as
on any computer with ROS 2, and needs no LSL. This folder holds two colcon packages, everything
the example needs: copy it into your workspace and build it.

| File | Role |
|---|---|
| `eeg_api_ros_example/config/params.yaml` | the settings of both nodes: edit this one |
| `eeg_api_ros_example/eeg_api_ros_example/intent_to_twist.py` | your application: a decoded target becomes a velocity |
| `eeg_api_ros_example/launch/example.launch.py` | starts both nodes with `params.yaml` |
| `eeg_api_ros/` | the bridge package (node `bridge` and the UDP library). Do not edit it |

## Build and run

Copy the two folders `eeg_api_ros/` and `eeg_api_ros_example/` into the `src/` folder of a colcon
workspace, then:

```bash
cd ~/ros2_ws
colcon build --packages-select eeg_api_ros eeg_api_ros_example
source install/setup.bash
ros2 launch eeg_api_ros_example example.launch.py
```

`params.yaml` is installed with the package: after editing it, run `colcon build` again (or
build with `--symlink-install` once).

The bridge announces itself every second. In the console: **Connect an application**, pick
`my-robot` (shown with its identifier), then **Connect**.

## Topics

| Topic | Type | Content |
|---|---|---|
| `eeg/decision` | `std_msgs/String` | the whole decision, as JSON: `{"mode": "ssvep", "target_index": 1.0, "freq_hz": 15.0, …}` |
| `eeg/target` | `std_msgs/Int32` | `target_index` (SSVEP) or `intent_index` (MI); `-1` = no decision, never target 0 |
| `eeg/confidence` | `std_msgs/Float32` | the score of the decision |
| `eeg/state` | `std_msgs/String` | `announcing`, `connected`, `decoding`, `disconnected`, `failed` |
| `cmd_vel` | `geometry_msgs/Twist` | the velocity published by `intent_to_twist`, ten times a second |

The bridge publishes an intent ("target 1 is looked at"), never a robot command: `intent_to_twist`
is where the example decides what a target means.

## `params.yaml`

`eeg_api_bridge` takes the keys of the Raspberry Pi client (`app_name`, `device_id`,
`device_port`, `engine_host`, `engine_port`, `mode`, `propose_refresh_hz`, `stop_mode_on_exit`),
with one difference: the settings of the mode are a JSON text, `settings`, since a ROS parameter
cannot hold a free-form object. The provided file drives two physical targets (LEDs blinking at
13 and 15 Hz).

`intent_to_twist`:

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
  packages.
- To use the bridge alone with your own nodes: [`../client/`](../client/).
