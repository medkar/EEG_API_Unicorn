"""Starts the bridge with config/params.yaml.

    ros2 launch eeg_api_ros eeg_api.launch.py
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    params = os.path.join(get_package_share_directory("eeg_api_ros"), "config", "params.yaml")
    return LaunchDescription([
        Node(package="eeg_api_ros", executable="bridge", name="eeg_api_bridge",
             parameters=[params], output="screen"),
    ])
