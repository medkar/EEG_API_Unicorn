from setuptools import setup

PACKAGE = "eeg_api_ros"

setup(
    name=PACKAGE,
    version="1.0.0",
    packages=[PACKAGE],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + PACKAGE]),
        ("share/" + PACKAGE, ["package.xml"]),
        ("share/" + PACKAGE + "/config", ["config/params.yaml"]),
        ("share/" + PACKAGE + "/launch", ["launch/eeg_api.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="EEG_API_Unicorn",
    maintainer_email="maintainer@example.com",
    description="Connects ROS 2 to the EEG_API_Unicorn console over UDP and publishes its "
                "decisions as topics.",
    license="TODO",
    entry_points={
        "console_scripts": [
            "bridge = eeg_api_ros.bridge:main",
            "intent_to_twist = eeg_api_ros.intent_to_twist:main",
        ],
    },
)
