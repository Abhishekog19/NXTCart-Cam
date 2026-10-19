"""Collect references from the actual Pi verification webcam, over ROS."""
import os
from pathlib import Path
import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from smart_cart_interfaces.msg import CameraFrame


class ReferenceCapture(Node):
    def __init__(self):
        super().__init__('reference_capture')
        self.declare_parameter('cam_root', os.environ.get('NXTCART_CAM_PATH', os.path.expanduser('~/NXTCart-Cam')))
        self.declare_parameter('sku', '')
        sku = self.get_parameter('sku').value
        if not sku or sku in ('.', '..') or any(c in sku for c in '/\\'):
            raise ValueError('Pass -p sku:=your_catalogue_sku')
        self.folder = Path(self.get_parameter('cam_root').value)/'references'/sku
        self.folder.mkdir(parents=True, exist_ok=True)
        self.frame, self.seq, self.saved_seq = None, None, None
        self.create_subscription(CameraFrame, '/cart/camera/frame', self.receive, qos_profile_sensor_data)
        self.create_timer(.03, self.tick)
        self.get_logger().info('Empty cart. Hold ONE product, varied angles. SPACE: save; Q: exit.')

    def receive(self, msg):
        self.frame = cv2.imdecode(np.frombuffer(bytes(msg.jpeg), dtype=np.uint8), cv2.IMREAD_COLOR)
        self.seq = (msg.stream_id, msg.seq)

    def tick(self):
        if self.frame is None:
            return
        cv2.imshow('Reference camera: one product, empty cart. SPACE save, Q exit', self.frame)
        key = cv2.waitKey(1) & 255
        if key == ord('q'):
            raise KeyboardInterrupt
        if key == ord(' ') and self.saved_seq != self.seq:
            import sys
            sys.path.insert(0, self.get_parameter('cam_root').value)
            from ml.product_crop import crop_product
            result = crop_product(self.frame)
            if not result.ok:
                self.get_logger().warn(f'Reference rejected: {result.reason}'); return
            from uuid import uuid4
            path = self.folder/f'{uuid4().hex}.jpg'
            if not cv2.imwrite(str(path), self.frame):
                raise OSError(f'Could not save reference {path}')
            self.saved_seq = self.seq
            self.get_logger().info(f'Saved {path}')


def main(args=None):
    rclpy.init(args=args); node = ReferenceCapture()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows(); node.destroy_node(); rclpy.shutdown()
