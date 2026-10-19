"""Exercise shipped ROS callbacks against the shipped message schemas, without DDS."""
import copy
import importlib.util
import json
import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PI = Path(os.environ.get('NXTCART_PI_PATH', ROOT.parent/'Cart-RestCode'))
sys.path[:0] = [str(ROOT), str(PI/'smart_cart_ws/src/smart_cart'),
                str(ROOT/'pc/vision_ws/src/nxtcart_vision')]
from smart_cart.catalog import import_catalog


class Stamp:
    sec = 100
    nanosec = 0


def message_type(path):
    fields = []
    for line in path.read_text().splitlines():
        line = line.split('#')[0].strip()
        if line:
            kind, name = line.split(); fields.append((kind, name))
    def init(self, **kwargs):
        for kind, name in fields:
            value = [] if kind.endswith('[]') else '' if kind == 'string' else False if kind == 'bool' else Stamp() if kind.endswith('/Time') else 0.0 if kind.startswith('float') else 0
            setattr(self, name, kwargs.get(name, value))
    return type(path.stem, (), {'__slots__': [name for kind, name in fields], '__init__': init})


class Publisher:
    def __init__(self): self.sent = []
    def publish(self, msg): self.sent.append(copy.deepcopy(msg))


class Node:
    overrides = {}
    def __init__(self, name): self.params = {}; self.pubs = {}
    def declare_parameter(self, name, value): self.params[name] = self.overrides.get(name, value)
    def get_parameter(self, name): return types.SimpleNamespace(value=self.params[name])
    def create_publisher(self, kind, topic, qos):
        pub = Publisher(); self.pubs[topic] = pub; return pub
    def create_subscription(self, *args): pass
    def create_timer(self, *args): pass
    def get_logger(self): return types.SimpleNamespace(info=lambda *a: None, error=lambda *a: None, warn=lambda *a: None)
    def get_clock(self): return types.SimpleNamespace(now=lambda: types.SimpleNamespace(to_msg=Stamp))
    def destroy_node(self): pass


def ros_stubs():
    msgs = types.ModuleType('smart_cart_interfaces.msg')
    for path in (PI/'smart_cart_ws/src/smart_cart_interfaces/msg').glob('*.msg'):
        setattr(msgs, path.stem, message_type(path))
    qos = types.ModuleType('rclpy.qos')
    qos.QoSProfile = lambda **kw: kw
    qos.DurabilityPolicy = types.SimpleNamespace(TRANSIENT_LOCAL=1)
    qos.ReliabilityPolicy = types.SimpleNamespace(RELIABLE=1)
    qos.qos_profile_sensor_data = object()
    node = types.ModuleType('rclpy.node'); node.Node = Node
    std = types.ModuleType('std_msgs.msg'); std.String = lambda: types.SimpleNamespace(data='')
    return {'rclpy': types.ModuleType('rclpy'), 'rclpy.node': node, 'rclpy.qos': qos,
            'std_msgs': types.ModuleType('std_msgs'), 'std_msgs.msg': std,
            'smart_cart_interfaces': types.ModuleType('smart_cart_interfaces'), 'smart_cart_interfaces.msg': msgs}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT/'tests'); self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)
        catalogue = folder/'products.json'
        catalogue.write_text(json.dumps([{'barcode': '001', 'name': 'A', 'sku': 'sku_a',
            'expected_weight': 150., 'price': 35., 'tolerance_g': 10.}]))
        db = folder/'inventory.db'; import_catalog(catalogue, db)
        Node.overrides = {'catalog_path': str(db), 'state_path': str(folder/'state.db'), 'upi_payee': 'merchant@example'}
        stubs = ros_stubs(); self.msgs = stubs['smart_cart_interfaces.msg']
        self.patcher = patch.dict(sys.modules, stubs); self.patcher.start(); self.addCleanup(self.patcher.stop)
        spec = importlib.util.spec_from_file_location('smart_cart.core_logic', PI/'smart_cart_ws/src/smart_cart/smart_cart/core_logic.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.node = module.CartVerificationEngine()
        self.addCleanup(self.node.ledger.journal.db.close)
        self.node.weight_cb(self.msgs.WeightSample(stream_id='scale', seq=1, grams=0., stable=True, calibrated=True))
        self.node.health_cb(types.SimpleNamespace(data='{"ready":true,"generation":"pc"}'))

    def verified(self):
        self.node.scan_cb(self.msgs.ScannedItem(barcode='001', scan_id='scan-a', price=999.))
        request = self.node.vision_pub.sent[-1]
        self.node.weight_cb(self.msgs.WeightSample(stream_id='scale', seq=2, grams=150., stable=True, calibrated=True))
        self.node.arduino_cb(self.msgs.WeightVerdict(txn_id=request.txn_id, delta_g=150., passed=True))
        self.node.vision_cb(self.msgs.VisionEvent(txn_id=request.txn_id, attempt=request.attempt,
            name=request.sku, barcode='001', action='item_placed', verdict='MATCH', verified=True))
        return request

    def test_callbacks_bind_weight_camera_and_authoritative_price(self):
        request = self.verified()
        state = self.node.ui_pub.sent[-1]
        self.assertTrue(state.checkout_allowed)
        self.assertEqual(state.items[0].price, 35.)
        self.assertEqual(state.total_price, 35.)
        self.assertEqual(state.items[0].txn_id, request.txn_id)
        self.assertEqual(self.node.settled_pub.sent[-1].txn_id, request.txn_id)
        self.assertEqual(self.node.expect_pub.sent[-1].expected_g, 150.)

    def test_server_rejects_stale_checkout_revision(self):
        self.verified()
        self.node.checkout_cb(types.SimpleNamespace(data=json.dumps({'revision': -1, 'request_id': 'old'})))
        self.assertFalse(json.loads(self.node.quote_pub.sent[-1].data)['allowed'])
        revision = self.node.ledger.revision
        self.node.checkout_cb(types.SimpleNamespace(data=json.dumps({'revision': revision, 'request_id': 'fresh'})))
        quote = json.loads(self.node.quote_pub.sent[-1].data)
        self.assertTrue(quote['allowed'])
        self.assertEqual(quote['amount'], 35.)
        self.assertEqual(quote['request_id'], 'fresh')

    def test_pending_and_sensor_disconnect_never_produce_payment_quote(self):
        self.node.scan_cb(self.msgs.ScannedItem(barcode='001', scan_id='scan-a'))
        self.node.checkout_cb(types.SimpleNamespace(data=json.dumps({'revision': self.node.ledger.revision})))
        self.assertFalse(json.loads(self.node.quote_pub.sent[-1].data)['allowed'])

    def test_remove_requests_have_new_attempt_and_remove_action(self):
        original = self.verified()
        self.node.remove_cb(types.SimpleNamespace(data=original.txn_id))
        request = self.node.vision_pub.sent[-1]
        self.assertEqual(request.action, 'remove')
        self.assertEqual(request.attempt, original.attempt+1)

    def test_pc_ai_backend_and_background_result_use_real_wire_fields(self):
        from ml.verifier import VerdictResult
        gate = threading.Event()
        def verify(sku, crops):
            gate.wait(1.)
            return VerdictResult('MATCH', .9, .9, 1., 1., 3, 'same product', sku)
        backend = types.SimpleNamespace(verify=verify, stats=[])
        Node.overrides = {'backend': 'ai', 'cam_root': str(ROOT), 'ai_model': 'test', 'ai_base_url': 'http://localhost/v1'}
        spec = importlib.util.spec_from_file_location('nxtcart_vision.node', ROOT/'pc/vision_ws/src/nxtcart_vision/nxtcart_vision/node.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with patch('ml.ai_backend.VLMBackend', return_value=backend):
            node = module.VisionNode()
        self.addCleanup(node.destroy_node)
        capture = types.SimpleNamespace(txn_id='job-a', attempt=1, sku='sku_a', barcode='001', action='add')
        try:
            node.submit(capture, [])
            node.tick()  # Must return while the inference worker is blocked.
            self.assertEqual(node.pub.sent, [])
            gate.set()
            node.jobs[('job-a', 1)][1].result(timeout=2.)
            node.tick()
            self.assertEqual(node.pub.sent[-1].name, 'sku_a')
            self.assertEqual(node.pub.sent[-1].txn_id, 'job-a')
            self.assertTrue(node.pub.sent[-1].verified)
        finally:
            gate.set()


if __name__ == '__main__': unittest.main()
