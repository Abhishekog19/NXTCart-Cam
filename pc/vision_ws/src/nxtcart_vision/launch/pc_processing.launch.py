import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    defaults = {'cam_root': os.environ.get('NXTCART_CAM_PATH', os.path.expanduser('~/NXTCart-Cam')),
                'backend': 'local', 'ai_model': '', 'ai_base_url': '', 'preview': 'false'}
    args = [DeclareLaunchArgument(k, default_value=v) for k, v in defaults.items()]
    params = {k: ParameterValue(LaunchConfiguration(k), value_type=bool if k == 'preview' else str) for k in defaults}
    return LaunchDescription(args+[Node(package='nxtcart_vision', executable='vision_verify_node',
                                       output='screen', parameters=[params])])
