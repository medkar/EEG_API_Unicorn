"""ROS 2 node, an EXAMPLE of what an application does with the intent: turns eeg/target into a
velocity on cmd_vel. Replace it with your own node; its settings are in config/params.yaml.

    eeg/target (std_msgs/Int32)  -->  cmd_vel (geometry_msgs/Twist)

Target i gives linear_x[i] and angular_z[i]. -1 (no decision), an unknown target, or no decision
for `timeout_s` seconds gives a zero velocity: silence is not an intent, and a robot must never
coast on a stale decision.
"""

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from std_msgs.msg import Int32

try:
    from rclpy.executors import ExternalShutdownException
except ImportError:                     # pragma: no cover - older distributions
    ExternalShutdownException = KeyboardInterrupt


class IntentToTwist(Node):
    def __init__(self):
        super().__init__("intent_to_twist")
        self.declare_parameter("linear_x", [0.1, 0.0])
        self.declare_parameter("angular_z", [0.0, 0.5])
        self.declare_parameter("timeout_s", 1.0)
        self.declare_parameter("cmd_vel_topic", "cmd_vel")
        self.linear = list(self.get_parameter("linear_x").value)
        self.angular = list(self.get_parameter("angular_z").value)
        self.timeout_s = float(self.get_parameter("timeout_s").value)
        self.pub = self.create_publisher(Twist, self.get_parameter("cmd_vel_topic").value, 10)
        self.create_subscription(Int32, "eeg/target", self.on_target, 10)
        self.target = -1
        self.last = self.get_clock().now()
        self.create_timer(0.1, self.tick)

    def on_target(self, msg):
        self.target = msg.data
        self.last = self.get_clock().now()

    def tick(self):
        twist = Twist()
        fresh = (self.get_clock().now() - self.last).nanoseconds / 1e9 < self.timeout_s
        if fresh and 0 <= self.target < min(len(self.linear), len(self.angular)):
            twist.linear.x = float(self.linear[self.target])
            twist.angular.z = float(self.angular[self.target])
        self.pub.publish(twist)


def main(args=None):
    rclpy.init(args=args)
    node = IntentToTwist()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.pub.publish(Twist())       # stop the robot
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
