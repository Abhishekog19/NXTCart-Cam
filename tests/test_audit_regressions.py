"""Failures found during the integration audit; no hardware or API calls."""
import unittest
import test_system as fixtures
import importlib.util
import queue
import time
import types
from concurrent.futures import Future
from unittest.mock import patch
import test_ros_adapters as adapters


class CaptureAuditTests(unittest.TestCase):
    setUp = fixtures.CaptureTests.setUp
    feed = fixtures.CaptureTests.feed
    start = fixtures.CaptureTests.start
    path = fixtures.CaptureTests.path
    def test_configured_regions_are_xywh_for_follower(self):
        self.pipeline.scanner_region = (.125, .25, .5, .75)
        self.start()
        self.assertEqual(self.pipeline.active.follower.scanner_box, (80, 120, 240, 240))

    def test_missing_target_cannot_count_as_rest(self):
        self.start(); self.path()
        self.pipeline.settled('a', 1, self.seq*67_000_000)
        for _ in range(5): self.feed()
        self.assertEqual(len(self.crops), 0)

    def test_blurred_rest_cannot_reuse_earlier_usable_crops(self):
        self.start(); self.path()
        self.pipeline.settled('a', 1, self.seq*67_000_000)
        self.frame[:] = 127
        for _ in range(6): self.feed(440)
        self.assertEqual(len(self.crops), 0)

    def test_settle_before_scan_is_not_placement_evidence(self):
        self.start(); self.path()
        self.pipeline.settled('a', 1, 1)
        for _ in range(6): self.feed(440)
        self.assertEqual(len(self.crops), 0)

    def test_idle_monitor_rearms_after_scene_becomes_quiet(self):
        alarms = []; self.pipeline.on_anomaly = alarms.append
        self.feed(440); self.feed(440); self.feed(380)
        self.assertEqual(len(alarms), 2)

    def test_final_three_evidence_frames_are_actual_rest_frames(self):
        self.start(); self.path()
        self.pipeline.settled('a', 1, self.seq*67_000_000)
        for _ in range(6): self.feed(440)
        capture, crops = self.crops[0]
        self.assertEqual(len(crops), 9)
        self.assertEqual([c.seq for c in capture.rest_crops], list(range(capture.rest_crops[0].seq, capture.rest_crops[0].seq+3)))
        for image, observed in zip(crops[-3:], capture.rest_crops):
            self.assertIs(image, observed.crop)

    def test_capture_deadline_is_checked_even_without_timer_callback(self):
        self.start(); self.path()
        self.pipeline.settled('a', 1, self.seq*67_000_000)
        self.pipeline.active.opened = self.clock()-13.
        for _ in range(6): self.feed(440)
        self.assertEqual(len(self.crops), 0)
        self.assertEqual(len(self.failed), 1)


class LedgerAuditTests(unittest.TestCase):
    setUp = fixtures.LedgerTests.setUp
    sample = fixtures.LedgerTests.sample
    scan = fixtures.LedgerTests.scan
    camera = fixtures.LedgerTests.camera
    add_verified = fixtures.LedgerTests.add_verified
    def test_late_camera_callback_rejected_without_timer_tick(self):
        unit = self.scan(); self.sample(150.)
        self.cart.arduino_verdict(unit.txn_id, 150., True)
        self.clock.advance(21.)
        self.assertFalse(self.camera(unit))
        self.assertNotEqual(unit.camera_status, 'PASS')

    def test_second_physical_removal_cannot_reuse_pending_transaction(self):
        a = self.add_verified(); self.add_verified('b')
        self.cart.remove(a.txn_id)
        self.sample(150.); self.sample(0.)
        self.camera(a, action='item_removed')
        self.assertTrue(self.cart.recovery)
        self.assertIn(a, self.cart.units)

    def test_arduino_failure_still_expires_pending_mass_assignment(self):
        unit = self.scan()
        self.cart.arduino_verdict(unit.txn_id, 0., False)
        self.camera(unit, 'RETRY')
        self.clock.advance(21.)
        # Keep transport healthy so this exercises transaction expiry itself.
        self.cart.last_weight_at = self.clock(); self.cart.pc_at = self.clock()
        self.cart.tick()
        self.assertFalse(unit.awaiting_weight)

    def test_arduino_failure_cannot_be_overwritten_by_later_pass(self):
        unit = self.scan()
        self.cart.arduino_verdict(unit.txn_id, 220., False)
        self.cart.arduino_verdict(unit.txn_id, 150., True)
        self.sample(150.); self.camera(unit)
        self.assertEqual(unit.status, 'FLAGGED')

    def test_removal_timeout_is_committed_once(self):
        unit = self.add_verified(); self.cart.remove(unit.txn_id)
        self.clock.advance(21.)
        self.cart.last_weight_at = self.clock(); self.cart.pc_at = self.clock()
        self.cart.tick(); revision = self.cart.revision
        self.clock.advance(21.); self.cart.tick()
        self.assertEqual(self.cart.revision, revision)

    def test_capacity_warning_clears_after_verified_removal(self):
        self.cart.max_units = 2
        first = self.add_verified(); self.add_verified('b')
        self.assertIsNone(self.scan('excess'))
        self.cart.remove(first.txn_id); self.sample(150.)
        self.camera(first, action='item_removed')
        self.assertTrue(self.cart.checkout_allowed)


class AdapterAuditTests(unittest.TestCase):
    setUp = adapters.AdapterTests.setUp
    verified = adapters.AdapterTests.verified

    def pc_node(self):
        adapters.Node.overrides = {'backend': 'ai', 'cam_root': str(fixtures.ROOT),
            'ai_model': 'test', 'ai_base_url': 'http://localhost/v1'}
        path = fixtures.ROOT/'pc/vision_ws/src/nxtcart_vision/nxtcart_vision/node.py'
        spec = importlib.util.spec_from_file_location('nxtcart_vision.node', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with patch('ml.ai_backend.VLMBackend', return_value=types.SimpleNamespace(stats=[])):
            node = module.VisionNode()
        self.addCleanup(node.destroy_node)
        return node

    def job(self, node, future, elapsed=0.):
        capture = types.SimpleNamespace(txn_id='job', attempt=1, sku='sku_a', barcode='001', action='add')
        node.jobs[('job', 1)] = (capture, future, time.monotonic()-elapsed, False)
        return capture

    def result(self):
        from ml.verifier import VerdictResult
        return VerdictResult('MATCH', .9, .9, 1., 1., 9, 'match', 'sku_a')

    def test_completed_future_after_deadline_cannot_pass(self):
        node = self.pc_node(); future = Future()
        self.job(node, future, 19.); future.set_result(self.result())
        node.tick()
        self.assertEqual(node.pub.sent[-1].verdict, 'RETRY')

    def test_cancel_running_inference_suppresses_result(self):
        node = self.pc_node(); future = Future(); future.set_running_or_notify_cancel()
        self.job(node, future)
        node.request(self.msgs.VerificationRequest(txn_id='job', attempt=1, action='cancel'))
        future.set_result(self.result()); node.tick()
        self.assertEqual(len(node.pub.sent), 0)
        self.assertEqual(node.jobs, {})

    def test_cancel_queued_inference_releases_job(self):
        node = self.pc_node(); future = Future(); self.job(node, future)
        node.request(self.msgs.VerificationRequest(txn_id='job', attempt=1, action='cancel'))
        self.assertTrue(future.cancelled()); node.tick()
        self.assertEqual(node.jobs, {})

    def test_pi_rejects_stale_transport_sample(self):
        self.verified()
        stale = types.SimpleNamespace(sec=99, nanosec=0)
        self.node.weight_cb(self.msgs.WeightSample(stream_id='scale', seq=3, grams=150.,
            stable=True, calibrated=True, stamp=stale))
        self.assertTrue(self.node.ledger.recovery)
        self.assertFalse(self.node.ledger.checkout_allowed)

    def test_serial_queue_does_not_refresh_old_samples(self):
        path = fixtures.PI/'smart_cart_ws/src/smart_cart/smart_cart/real_weight_node.py'
        spec = importlib.util.spec_from_file_location('smart_cart.real_weight_node', path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'serial': types.ModuleType('serial')}):
            spec.loader.exec_module(module)
        bridge = module.ArduinoWeightNode.__new__(module.ArduinoWeightNode)
        bridge.inbox = queue.Queue(); bridge.delivery_generation = 'original'
        bridge.pub, bridge.verdict_pub = adapters.Publisher(), adapters.Publisher()
        stamp = types.SimpleNamespace(sec=100, nanosec=123)
        bridge.inbox.put(('scale', ('sample', 1, 150., True, True), time.monotonic()-3., stamp))
        bridge.inbox.put(('scale', ('sample', 2, 150., True, True), time.monotonic(), stamp))
        bridge.tick()
        self.assertEqual(len(bridge.pub.sent), 1)
        self.assertEqual(bridge.pub.sent[0].seq, 2)
        self.assertEqual(bridge.pub.sent[0].stamp.nanosec, 123)
        self.assertNotEqual(bridge.pub.sent[0].stream_id, 'scale:original')


class ScanGateTests(unittest.TestCase):
    def setUp(self):
        from smart_cart.scan_gate import ScanGate
        self.gate = ScanGate(.8)

    def test_disconnect_does_not_scan_still_visible_code_again(self):
        self.assertEqual(self.gate.observe({'a'}, 0.), 'a')
        self.gate.gap()
        self.assertIsNone(self.gate.observe({'a'}, 5.))

    def test_observed_absence_rearms_same_sku(self):
        self.gate.observe({'a'}, 0.)
        self.gate.observe(set(), .1); self.gate.observe(set(), 1.)
        self.assertEqual(self.gate.observe({'a'}, 1.1), 'a')

    def test_gap_interrupts_absence_dwell(self):
        self.gate.observe({'a'}, 0.); self.gate.observe(set(), .1)
        self.gate.gap(); self.gate.observe(set(), 5.)
        self.assertIsNone(self.gate.observe({'a'}, 5.1))
