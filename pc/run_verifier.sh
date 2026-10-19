#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
export NXTCART_CAM_PATH="$(cd .. && pwd)"
source /opt/ros/jazzy/setup.bash
source vision_ws/install/setup.bash
set -u
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
exec ros2 launch nxtcart_vision pc_processing.launch.py "$@"
