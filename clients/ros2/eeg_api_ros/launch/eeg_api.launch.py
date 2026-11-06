"""Starts the bridge, and the intent_to_twist example unless with_example:=false.

    ros2 launch eeg_api_ros eeg_api.launch.py
    ros2 launch eeg_api_ros eeg_api.launch.py with_example:=false
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    params = os.path.join(get_package_share_directory("eeg_api_ros"), "config", "params.yaml")
    return LaunchDescription([
        DeclareLaunchArgument("with_example", default_value="true",
                              description="also start the intent_to_twist example"),
        Node(package="eeg_api_ros", executable="bridge", name="eeg_api_bridge",
             parameters=[params], output="screen"),
        Node(package="eeg_api_ros", executable="intent_to_twist", name="intent_to_twist",
             parameters=[params], output="screen",
             condition=IfCondition(LaunchConfiguration("with_example"))),
    ])
