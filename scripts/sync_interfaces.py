"""Copy the one canonical ROS interface source into the PC build workspace."""
import shutil
import argparse
from pathlib import Path

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument('--pi-root', type=Path, default=root.parent/'Cart-RestCode')
    args = parser.parse_args()
    source = args.pi_root/'smart_cart_ws'/'src'/'smart_cart_interfaces'
    destination = root/'pc'/'vision_ws'/'src'/'smart_cart_interfaces'
    shutil.copytree(source, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
    print(f'PC interfaces synchronized: {destination}')
