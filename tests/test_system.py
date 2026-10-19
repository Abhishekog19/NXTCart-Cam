"""Integration and fault tests, runnable without ROS, sensors or paid APIs."""
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PI = Path(os.environ.get('NXTCART_PI_PATH', ROOT.parent/'Cart-RestCode'))
sys.path[:0] = [str(ROOT), str(PI/'smart_cart_ws/src/smart_cart'),
                str(ROOT/'pc/vision_ws/src/nxtcart_vision')]
from smart_cart.catalog import Product, Catalog, import_catalog
from smart_cart.verification import Journal, VerificationLedger
from smart_cart.serial_protocol import parse_line
from nxtcart_vision.pipeline import CapturePipeline
from ml.detector import Detection
from ml.verifier import ProductVerifier, ColourReference
from nxtcart_vision.journey_verifier import verify_journey
import numpy as np


class Clock:
    now = 100.0
    def __call__(self): return self.now
    def advance(self, amount): self.now += amount


PRODUCT = Product('001', 'Product A', 150., 35., 'product_a', 10.)
OTHER = Product('002', 'Product B', 150., 90., 'product_b', 10.)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.journal = Journal(':memory:')
        self.addCleanup(self.journal.db.close)
        self.cart = VerificationLedger(self.journal, clock=self.clock)
        self.seq = 0
        self.sample(0.)
        self.cart.heartbeat()

    def sample(self, grams, stable=True, calibrated=True, stream='scale'):
        self.seq += 1
        self.cart.weight(stream, self.seq, grams, stable, calibrated)

    def scan(self, token='a', product=PRODUCT):
        return self.cart.scan(token, product)

    def camera(self, unit, verdict='MATCH', **kwargs):
        return self.cart.vision(unit.txn_id, kwargs.get('attempt', unit.attempt),
                                kwargs.get('sku', unit.sku), verdict, verdict == 'MATCH',
                                'camera result', kwargs.get('action', 'item_placed'))

    def add_verified(self, token='a', product=PRODUCT):
        u = self.scan(token, product)
        self.sample(self.cart.anchor + product.expected_weight)
        self.cart.arduino_verdict(u.txn_id, product.expected_weight, True)
        self.camera(u)
        return u

    def test_scan_appears_immediately_and_checkout_waits_for_both_gates(self):
        u = self.scan()
        self.assertEqual(self.cart.units, [u])
        self.assertEqual(u.status, 'VERIFYING')
        self.assertFalse(self.cart.checkout_allowed)
        self.sample(150.)
        self.assertEqual(u.weight_status, 'CHECKING')
        self.camera(u)
        self.assertFalse(self.cart.checkout_allowed)
        self.cart.arduino_verdict(u.txn_id, 150., True)
        self.assertTrue(self.cart.checkout_allowed)

    def test_camera_before_weight_is_supported(self):
        u = self.scan(); self.camera(u)
        self.cart.arduino_verdict(u.txn_id, 150., True)
        self.assertFalse(self.cart.checkout_allowed)
        self.sample(150.)
        self.assertTrue(self.cart.checkout_allowed)

    def test_arduino_failure_before_sample_is_bound_to_physical_delta(self):
        u = self.scan()
        self.cart.arduino_verdict(u.txn_id, 210., False)
        self.sample(210.)
        self.assertEqual(u.measured_g, 210.)
        self.assertEqual(u.status, 'FLAGGED')
        self.assertEqual(self.cart.anchor, 210.)

    def test_failed_weight_does_not_block_later_shopping(self):
        bad = self.scan(); self.sample(220.)
        good = self.add_verified('b', OTHER)
        self.assertEqual(bad.status, 'FLAGGED')
        self.assertEqual(good.status, 'VERIFIED')
        self.assertEqual(len(self.cart.units), 2)
        self.assertFalse(self.cart.checkout_allowed)

    def test_camera_latency_does_not_block_next_weight_transaction(self):
        first = self.scan(); self.sample(150.)
        self.cart.arduino_verdict(first.txn_id, 150., True)
        second = self.add_verified('b', OTHER)
        self.assertEqual(second.status, 'VERIFIED')
        self.assertFalse(self.cart.checkout_allowed)
        self.camera(first)
        self.assertTrue(self.cart.checkout_allowed)

    def test_equal_weight_swap_is_red(self):
        u = self.scan(); self.sample(150.)
        self.cart.arduino_verdict(u.txn_id, 150., True)
        self.camera(u, 'MISMATCH')
        self.assertEqual(u.status, 'FLAGGED')
        self.assertFalse(self.cart.checkout_allowed)

    def test_every_uncertain_camera_verdict_blocks_payment(self):
        for verdict in ('RETRY', 'SUSPECT', 'UNAVAILABLE', 'UNVERIFIED', ''):
            with self.subTest(verdict=verdict):
                u = self.scan(verdict or 'empty'); self.sample(self.cart.anchor+150.)
                self.cart.arduino_verdict(u.txn_id, 150., True)
                self.camera(u, verdict)
                self.assertEqual(u.status, 'FLAGGED')
                self.assertFalse(self.cart.checkout_allowed)

    def test_overlapping_unsettled_scans_are_ambiguous_not_guessed(self):
        a, b = self.scan(), self.scan('b')
        self.sample(300.)
        self.assertEqual(a.weight_status, 'FAIL')
        self.assertEqual(b.weight_status, 'FAIL')
        self.camera(a); self.camera(b)
        self.assertFalse(self.cart.checkout_allowed)

    def test_scan_id_replay_is_idempotent_but_same_sku_can_repeat(self):
        first = self.add_verified()
        self.assertIsNone(self.scan())
        second = self.scan('new')
        self.assertNotEqual(first.txn_id, second.txn_id)
        self.assertEqual(len(self.cart.units), 2)

    def test_verdict_cannot_be_reused_for_another_same_sku_unit(self):
        first = self.add_verified()
        second = self.scan('new'); self.sample(300.)
        self.cart.arduino_verdict(second.txn_id, 150., True)
        self.assertFalse(self.camera(first))
        self.assertEqual(second.camera_status, 'PENDING')
        self.assertFalse(self.cart.checkout_allowed)

    def test_wrong_sku_attempt_and_action_are_ignored(self):
        u = self.scan()
        self.assertFalse(self.camera(u, sku='other'))
        self.assertFalse(self.camera(u, attempt=2))
        self.assertFalse(self.camera(u, action='item_removed'))
        self.assertEqual(u.camera_status, 'PENDING')

    def test_timeout_is_terminal_and_late_match_cannot_turn_green(self):
        u = self.scan(); self.clock.advance(21.); self.cart.tick()
        self.assertFalse(self.camera(u))
        self.assertEqual(u.status, 'FLAGGED')

    def test_weight_mismatch_is_not_hidden_by_later_camera_match(self):
        u = self.scan(); self.sample(230.); self.camera(u)
        self.assertEqual(u.status, 'FLAGGED')

    def test_no_mock_or_stale_scale_can_enable_checkout(self):
        self.add_verified()
        self.clock.advance(3.); self.cart.heartbeat()
        self.assertFalse(self.cart.checkout_allowed)

    def test_moving_scale_blocks_even_if_items_were_green(self):
        self.add_verified(); self.sample(150., stable=False)
        self.assertFalse(self.cart.checkout_allowed)

    def test_pc_disconnect_blocks_checkout(self):
        self.add_verified(); self.cart.heartbeat(False)
        self.assertFalse(self.cart.checkout_allowed)

    def test_pc_reconnect_never_restores_trust_after_unobserved_window(self):
        self.add_verified(); self.clock.advance(3.); self.cart.tick()
        self.cart.heartbeat(True)
        self.assertFalse(self.cart.checkout_allowed)
        self.assertTrue(self.cart.recovery)

    def test_pc_restart_generation_requires_reconciliation(self):
        self.cart.heartbeat(True, 'boot-a')
        self.add_verified(); self.cart.heartbeat(True, 'boot-b')
        self.assertTrue(self.cart.recovery)

    def test_unscanned_mass_blocks_then_removal_restores_checkout(self):
        self.add_verified(); self.sample(210.)
        self.assertFalse(self.cart.checkout_allowed)
        self.sample(150.)
        self.assertTrue(self.cart.checkout_allowed)

    def test_duplicate_and_nan_samples_are_rejected(self):
        self.add_verified()
        self.assertFalse(self.cart.weight('scale', self.seq, 0., True, True))
        self.assertFalse(self.cart.weight('scale', self.seq+1, math.nan, True, True))
        self.assertEqual(self.cart.latest, 150.)

    def test_reconnected_scale_cannot_silently_adopt_loaded_cart(self):
        self.add_verified(); self.sample(150., stream='new')
        self.assertFalse(self.cart.ready)
        self.assertFalse(self.cart.checkout_allowed)

    def test_restart_requires_empty_cart_reconciliation(self):
        u = self.add_verified()
        restored = VerificationLedger(self.journal, clock=self.clock)
        restored.weight('new', 1, 150., True, True); restored.heartbeat()
        self.assertFalse(restored.checkout_allowed)
        restored.weight('new', 2, 0., True, True)
        self.assertTrue(restored.remove(u.txn_id))
        self.assertEqual(restored.units, [])

    def test_loaded_startup_never_tares_away_unscanned_products(self):
        other = VerificationLedger(Journal(':memory:'), clock=self.clock)
        self.addCleanup(other.journal.db.close)
        other.weight('scale', 1, 500., True, True)
        self.assertFalse(other.ready)

    def test_selected_removal_needs_weight_and_camera_identity(self):
        a = self.add_verified(); b = self.add_verified('b', OTHER)
        self.assertTrue(self.cart.remove(a.txn_id))
        self.sample(150.)
        self.assertEqual(len(self.cart.units), 2)
        self.assertFalse(self.cart.checkout_allowed)
        self.camera(a, action='item_removed')
        self.assertEqual(self.cart.units, [b])
        self.assertTrue(self.cart.checkout_allowed)

    def test_same_weight_wrong_removal_does_not_discount_selected_product(self):
        a = self.add_verified(); self.add_verified('b', OTHER)
        self.cart.remove(a.txn_id); self.sample(150.)
        self.camera(a, 'MISMATCH', action='item_removed')
        self.assertEqual(len(self.cart.units), 2)
        self.assertFalse(self.cart.checkout_allowed)
        self.assertTrue(self.cart.recovery)

    def test_remove_failed_unplaced_scan(self):
        u = self.scan(); self.camera(u, 'RETRY')
        self.assertTrue(self.cart.remove(u.txn_id))
        self.assertEqual(self.cart.units, [])


class Detector:
    frames_seen = 100
    warmup_frames = 0
    detections = []
    def detect(self, frame): self.frames_seen += 1; return self.detections
    def reset(self): self.frames_seen = 0


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.failed, self.crops = Clock(), [], []
        self.detector = Detector()
        self.pipeline = CapturePipeline(lambda c, r: self.failed.append((c, r)),
            lambda c, crops: self.crops.append((c, crops)), clock=self.clock, detector=self.detector)
        self.frame = np.random.default_rng(44).integers(0, 256, (480, 640, 3), dtype=np.uint8)
        self.seq = 0
        self.feed()

    def feed(self, x=None, extra=False, stream='camera', skip=0):
        self.clock.advance(.067); self.seq += 1+skip
        self.detector.detections = [] if x is None else [Detection((x, 150, 100, 100))]
        if extra: self.detector.detections.append(Detection((300, 250, 80, 80)))
        self.pipeline.frame(stream, self.seq, self.seq*67_000_000, self.frame)

    def start(self, txn='a', action='add'):
        self.pipeline.start(txn, 1, 'product_a', '001', self.seq*67_000_000, action)

    def path(self):
        for x in (80, 140, 200, 260, 320, 380, 440): self.feed(x)

    def test_full_path_plus_scale_settle_plus_rest_submits_crops(self):
        self.start(); self.path()
        self.assertEqual(self.crops, [])
        self.pipeline.settled('a', 1, self.seq*67_000_000)
        for _ in range(6): self.feed(440)
        self.assertEqual(len(self.crops), 1)
        self.assertGreaterEqual(len(self.crops[0][1]), 3)
        self.assertEqual(self.failed, [])

    def test_weight_without_full_path_never_submits(self):
        self.start(); self.pipeline.settled('a', 1, self.seq*67_000_000)
        for _ in range(6): self.feed(440)
        self.assertEqual(self.crops, [])

    def test_path_without_weight_never_submits(self):
        self.start(); self.path()
        for _ in range(6): self.feed(440)
        self.assertEqual(self.crops, [])

    def test_frame_loss_breaks_custody(self):
        self.start(); self.feed(80); self.feed(140, skip=1)
        self.assertEqual(len(self.failed), 1)
        self.assertIsNone(self.pipeline.active)

    def test_camera_restart_breaks_custody(self):
        self.start(); self.feed(80); self.feed(140, stream='new')
        self.assertEqual(len(self.failed), 1)

    def test_multiple_objects_are_ambiguous(self):
        self.start(); self.feed(80, extra=True)
        self.assertEqual(len(self.failed), 1)

    def test_network_stall_is_failure_not_match(self):
        self.start(); self.clock.advance(1.); self.pipeline.tick()
        self.assertEqual(len(self.failed), 1)

    def test_new_scan_aborts_only_active_capture_not_submitted_ai_job(self):
        self.start(); self.path(); self.pipeline.settled('a', 1, self.seq*67_000_000)
        for _ in range(6): self.feed(440)
        self.start('b')
        self.assertEqual(len(self.crops), 1)
        self.assertEqual(self.pipeline.active.txn_id, 'b')
        self.assertEqual(self.failed, [])

    def test_removal_reverses_path_and_keeps_transaction_action(self):
        self.start(action='remove')
        for x in (440, 380, 320, 260, 200, 140, 80): self.feed(x)
        self.pipeline.settled('a', 1, self.seq*67_000_000)
        for _ in range(6): self.feed(80)
        self.assertEqual(len(self.crops), 1)
        self.assertEqual(self.crops[0][0].action, 'remove')

    def test_stationary_products_in_partly_filled_cart_do_not_break_next_add(self):
        old = Detection((480, 350, 80, 80))
        self.detector.detections = [old]
        self.seq += 1; self.clock.advance(.067)
        self.pipeline.frame('camera', self.seq, self.seq*67_000_000, self.frame)
        self.start()
        for x in (80, 140, 200, 260, 320, 380, 440, 440, 440, 440, 440, 440):
            self.seq += 1; self.clock.advance(.067)
            self.detector.detections = [old, Detection((x, 150, 100, 100))]
            self.pipeline.settled('a', 1, self.seq*67_000_000)
            self.pipeline.frame('camera', self.seq, self.seq*67_000_000, self.frame)
        self.assertEqual(self.failed, [])
        self.assertEqual(len(self.crops), 1)

    def test_zero_net_mass_handling_in_idle_basket_is_reported(self):
        anomalies = []; self.pipeline.on_anomaly = anomalies.append
        self.feed(440)
        self.assertEqual(len(anomalies), 1)


class CatalogSerialTests(unittest.TestCase):
    def test_strict_serial_packet_contract(self):
        self.assertEqual(parse_line('W,5,150.5,1,1'), ('sample', 5, 150.5, True, True))
        self.assertEqual(parse_line('V,txn,160,FAIL'), ('verdict', 'txn', 160., False))
        for line in ('Weight: 0.15 kg', 'W,1,nan,1,1', 'W,1,150,yes,1', 'V,txn,inf,PASS'):
            with self.subTest(line=line), self.assertRaises(ValueError): parse_line(line)

    def test_catalog_import_upserts_and_reads_real_prices(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as tmp:
            path, db = Path(tmp)/'products.json', Path(tmp)/'inventory.db'
            row = {'barcode': '001', 'name': 'A', 'sku': 'product_a',
                   'expected_weight': 153.5, 'price': 37., 'tolerance_g': 8.}
            path.write_text(json.dumps([row])); import_catalog(path, db)
            row['barcode'] = '002'; path.write_text(json.dumps([row])); import_catalog(path, db)
            self.assertEqual(Catalog(db).lookup('001').price, 37.)
            self.assertEqual(Catalog(db).lookup('002').expected_weight, 153.5)
            self.assertIsNone(Catalog(db).lookup('unknown'))


class JourneyTests(unittest.TestCase):
    def setUp(self):
        class Recognizer:
            def embed(self, crop): return np.array([float(crop[0, 0, 0] == 1)])
            def similarity(self, a, b): return float(a[0])
        self.backend = ProductVerifier(Recognizer(), {'sku': [np.array([1.])]},
            {'sku': ColourReference([np.array([1.])])}, colour_hist_fn=lambda crop: np.array([1.]))
        rng = np.random.default_rng(90)
        self.crops = [rng.integers(0, 256, (96, 96, 3), dtype=np.uint8) for _ in range(9)]
        for crop in self.crops: crop[0, 0, 0] = 1

    def test_early_matching_majority_cannot_hide_wrong_product_at_rest(self):
        for crop in self.crops[-3:]: crop[0, 0, 0] = 0
        self.assertEqual(self.backend.verify('sku', self.crops).verdict, 'MATCH')
        self.assertEqual(verify_journey(self.backend, 'sku', self.crops).verdict, 'MISMATCH')

    def test_all_temporal_windows_matching_accepts(self):
        self.assertEqual(verify_journey(self.backend, 'sku', self.crops).verdict, 'MATCH')

    def test_even_one_nonmatching_rest_view_cannot_be_outvoted(self):
        self.crops[-1][0, 0, 0] = 0
        self.assertEqual(self.backend.verify('sku', self.crops).verdict, 'MATCH')
        self.assertEqual(verify_journey(self.backend, 'sku', self.crops).verdict, 'SUSPECT')

    def test_insufficient_temporal_evidence_retries(self):
        self.assertEqual(verify_journey(self.backend, 'sku', self.crops[:6]).verdict, 'RETRY')


if __name__ == '__main__':
    unittest.main(verbosity=2)
