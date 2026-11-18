"""Starts the bridge of eeg_api_ros and the intent_to_twist node, both with the config/params.yaml
of THIS package.

    ros2 launch eeg_api_ros_example example.launch.py
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    params = os.path.join(get_package_share_directory("eeg_api_ros_example"), "config",
                          "params.yaml")
    return LaunchDescription([
        Node(package="eeg_api_ros", executable="bridge", name="eeg_api_bridge",
             parameters=[params], output="screen"),
        Node(package="eeg_api_ros_example", executable="intent_to_twist", name="intent_to_twist",
             parameters=[params], output="screen"),
    ])
