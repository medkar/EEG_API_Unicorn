from setuptools import setup

PACKAGE = "eeg_api_ros_example"

setup(
    name=PACKAGE,
    version="1.0.0",
    packages=[PACKAGE],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + PACKAGE]),
        ("share/" + PACKAGE, ["package.xml"]),
        ("share/" + PACKAGE + "/config", ["config/params.yaml"]),
        ("share/" + PACKAGE + "/launch", ["launch/example.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="EEG_API_Unicorn",
    maintainer_email="maintainer@example.com",
    description="An example application of eeg_api_ros: a decoded target becomes a velocity "
                "on cmd_vel.",
    license="TODO",
    entry_points={
        "console_scripts": [
            "intent_to_twist = eeg_api_ros_example.intent_to_twist:main",
        ],
    },
)
