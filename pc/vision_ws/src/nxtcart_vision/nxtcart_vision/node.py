"""ROS transport and bounded background inference on the PC."""
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import String
from smart_cart_interfaces.msg import VerificationRequest, CameraFrame, VisionEvent


def ns(stamp):
    return stamp.sec*1_000_000_000+stamp.nanosec


class VisionNode(Node):
    def __init__(self):
        super().__init__('pc_product_verifier')
        defaults = {'cam_root': os.environ.get('NXTCART_CAM_PATH', os.path.expanduser('~/NXTCart-Cam')),
                    'backend': 'local', 'ai_model': '', 'ai_base_url': '',
                    'ai_timeout': 8.0, 'capture_timeout': 12.0, 'result_timeout': 18.0,
                    'max_inflight': 8, 'scanner_region': [0., 0., .45, 1.],
                    'cart_region': [.55, 0., 1., 1.], 'preview': False}
        for name, value in defaults.items():
            self.declare_parameter(name, value)
        p = lambda name: self.get_parameter(name).value
        root = Path(p('cam_root')).resolve(); sys.path.insert(0, str(root))
        from .pipeline import CapturePipeline
        self.backend, self.backend_error = None, ''
        try:
            if p('backend') == 'local':
                from ml.recognizer import EmbeddingRecognizer
                from ml.matcher import load_database
                from ml.verifier import ProductVerifier, load_colour_db
                self.backend = ProductVerifier(EmbeddingRecognizer(),
                    load_database(str(root/'embedding_db.pkl')), load_colour_db(str(root/'embedding_db.pkl')))
            elif p('backend') == 'ai':
                from ml.ai_backend import VLMBackend
                if not p('ai_model') or not p('ai_base_url'):
                    raise ValueError('AI mode needs an explicitly chosen vision model and endpoint')
                self.backend = VLMBackend(model=p('ai_model'), base_url=p('ai_base_url'),
                                         timeout_sec=p('ai_timeout'), references_dir=str(root/'references'))
            else:
                raise ValueError('backend must be local or ai')
        except Exception as exc:
            self.backend_error = str(exc)
            self.get_logger().error(f'Backend unavailable: {exc}')
        self.pub = self.create_publisher(VisionEvent, '/cart/vision_event', 50)
        self.health_pub = self.create_publisher(String, '/cart/vision_health', 10)
        self.anomaly_pub = self.create_publisher(String, '/cart/scene_anomaly', 10)
        self.inference_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='product-inference')
        self.jobs = {}
        self.done = set()
        self.early_settles = {}
        self.pipeline = CapturePipeline(self.failure, self.submit,
            scanner_region=p('scanner_region'), cart_region=p('cart_region'), timeout=p('capture_timeout'),
            on_anomaly=self.anomaly)
        self.create_subscription(VerificationRequest, '/cart/verification_request', self.request, 50)
        self.create_subscription(VerificationRequest, '/cart/placement_settled', self.settled, 50)
        self.create_subscription(CameraFrame, '/cart/camera/frame', self.frame, qos_profile_sensor_data)
        self.create_timer(.05, self.tick)
        self.last_health = 0.0
        self.boot_id = uuid.uuid4().hex
        self.last_frame = None

    def request(self, msg):
        key = (msg.txn_id, msg.attempt)
        if not msg.txn_id:
            return
        if msg.action == 'cancel':
            self.pipeline.cancel(*key)
            job = self.jobs.get(key)
            if job:
                capture, future, started, _ = job
                future.cancel()
                self.jobs[key] = (capture, future, started, True)
            self.early_settles.pop(key, None)
            self.done.add(key)
            return
        if key in self.done or key in self.jobs:
            return
        if msg.action not in ('add', 'remove'):
            return
        self.pipeline.start(msg.txn_id, msg.attempt, msg.sku, msg.barcode, ns(msg.started_at), msg.action)
        early = self.early_settles.pop(key, None)
        if early:
            self.pipeline.settled(*key, early[0])

    def settled(self, msg):
        if (msg.txn_id, msg.attempt) in self.done:
            return
        if not self.pipeline.active or (self.pipeline.active.txn_id, self.pipeline.active.attempt) != (msg.txn_id, msg.attempt):
            if len(self.early_settles) < 50:
                self.early_settles[(msg.txn_id, msg.attempt)] = (ns(msg.started_at), time.monotonic())
        self.pipeline.settled(msg.txn_id, msg.attempt, ns(msg.started_at))

    def frame(self, msg):
        if not msg.jpeg or len(msg.jpeg) > 1_000_000:
            self.pipeline.fail('Invalid image packet'); return
        try:
            frame = cv2.imdecode(np.frombuffer(bytes(msg.jpeg), dtype=np.uint8), cv2.IMREAD_COLOR)
        except cv2.error:
            self.pipeline.fail('Invalid verification camera image'); return
        if frame is None or frame.shape[0] > 1080 or frame.shape[1] > 1920:
            self.pipeline.fail('Invalid verification camera image'); return
        self.pipeline.frame(msg.stream_id, msg.seq, ns(msg.stamp), frame)
        if self.get_parameter('preview').value:
            for region, color in [(self.pipeline.scanner_region, (0, 180, 255)),
                                  (self.pipeline.cart_region, (0, 180, 0))]:
                h, w = frame.shape[:2]
                x1, y1, x2, y2 = [int(v*s) for v, s in zip(region, (w, h, w, h))]
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.imshow('PC verification geometry: amber scan, green rest', frame)
            cv2.waitKey(1)

    def failure(self, capture, reason):
        self.publish(capture, 'RETRY', reason)

    def anomaly(self, reason):
        msg = String(); msg.data = reason
        self.anomaly_pub.publish(msg)

    def submit(self, capture, crops):
        if self.backend is None:
            self.publish(capture, 'UNAVAILABLE', self.backend_error); return
        if len(self.jobs) >= self.get_parameter('max_inflight').value:
            self.publish(capture, 'RETRY', 'Inference queue full; remove this unit and scan again'); return
        key = (capture.txn_id, capture.attempt)
        # A single worker protects the shared MobileNet interpreter from concurrent use.
        future = self.inference_pool.submit(self.verify_job, capture.sku, crops)
        self.jobs[key] = (capture, future, time.monotonic(), False)

    def verify_job(self, sku, crops):
        if self.get_parameter('backend').value == 'local':
            from .journey_verifier import verify_journey
            return verify_journey(self.backend, sku, crops)
        result = self.backend.verify(sku, crops)
        if len(self.backend.stats) > 1000:
            del self.backend.stats[:-1000]
        return result

    def publish(self, capture, verdict, reason, result=None):
        key = (capture.txn_id, capture.attempt)
        if key in self.done:
            return
        msg = VisionEvent()
        msg.txn_id, msg.attempt = key
        msg.barcode, msg.name = capture.barcode, capture.sku
        msg.action = 'item_removed' if capture.action == 'remove' else 'item_placed'
        msg.verdict, msg.verified, msg.detected = verdict, verdict == 'MATCH', True
        msg.reason = reason[:300]
        if result is not None:
            msg.appearance_score = float(result.appearance_score)
            msg.colour_score = float(result.colour_score)
        self.pub.publish(msg); self.done.add(key)
        self.get_logger().info(f'{capture.txn_id} {capture.sku}: {verdict} {reason[:100]}')

    def tick(self):
        self.pipeline.tick()
        now = time.monotonic()
        self.early_settles = {k: v for k, v in self.early_settles.items() if now-v[1] < 20.}
        for key, (capture, future, started, expired) in list(self.jobs.items()):
            if not expired and now-started > self.get_parameter('result_timeout').value:
                self.publish(capture, 'RETRY', 'Inference deadline exceeded')
                future.cancel()
                expired = True
                self.jobs[key] = (capture, future, started, True)
            if future.done():
                if not expired:
                    try:
                        result = future.result()
                        self.publish(capture, result.verdict, result.reason, result)
                    except Exception as exc:
                        self.publish(capture, 'UNAVAILABLE', f'Verification failed: {type(exc).__name__}')
                del self.jobs[key]
        if now-self.last_health >= .5:
            self.last_health = now
            health = String()
            worker_stalled = any(expired and not future.done() for _, future, _, expired in self.jobs.values())
            health.data = json.dumps({'ready': self.pipeline.ready and self.backend is not None and not worker_stalled,
                                      'generation': self.boot_id + ':' + str(self.pipeline.stream),
                                      'backend': self.get_parameter('backend').value,
                                      'inflight': len(self.jobs), 'error': self.backend_error[:200]})
            self.health_pub.publish(health)
        if len(self.done) > 2000:
            self.done = set(list(self.done)[-1000:])

    def destroy_node(self):
        self.inference_pool.shutdown(wait=False, cancel_futures=True)
        if self.get_parameter('preview').value:
            cv2.destroyAllWindows()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args); node = VisionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node(); rclpy.shutdown()
