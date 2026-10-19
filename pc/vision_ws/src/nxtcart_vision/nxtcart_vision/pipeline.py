"""Continuous custody capture, independent of ROS and inference latency."""
import math
import time
from dataclasses import dataclass, field
from ml.detector import BackgroundSubtractorDetector
from ml.frame_source import FrameMeta
from ml.item_follower import ItemFollower, FollowStatus
from ml.item_follower import _iou, _region_px


@dataclass
class Capture:
    txn_id: str
    attempt: int
    sku: str
    barcode: str
    started_ns: int
    opened: float
    follower: object
    action: str = 'add'
    settled_ns: int = 0
    still: int = 0
    last_center: object = None
    stationary_boxes: tuple = ()
    rest_crops: list = field(default_factory=list)


class CapturePipeline:
    def __init__(self, on_failure, on_crops, scanner_region=(0., 0., .45, 1.),
                 cart_region=(.55, 0., 1., 1.), clock=time.monotonic,
                 detector=None, follower_factory=ItemFollower, timeout=12.,
                 max_gap_sec=.35, still_frames=4, still_pixels=8., on_anomaly=None):
        self.on_failure, self.on_crops = on_failure, on_crops
        self.clock, self.detector, self.follower_factory = clock, detector or BackgroundSubtractorDetector(), follower_factory
        self.scanner_region, self.cart_region = scanner_region, cart_region
        for box in (scanner_region, cart_region):
            if len(box) != 4 or not all(math.isfinite(x) and 0 <= x <= 1 for x in box) or box[0] >= box[2] or box[1] >= box[3]:
                raise ValueError('regions must be normalized left,top,right,bottom boxes')
        self.timeout, self.max_gap_sec, self.still_frames, self.still_pixels = timeout, max_gap_sec, still_frames, still_pixels
        self.active = None
        self.stream, self.seq, self.stamp_ns, self.last_frame_at = None, -1, 0, -math.inf
        self.frame_size = (640, 480)
        self.cancelled = set()
        self.last_detections = []
        self.on_anomaly = on_anomaly
        self.idle_cart_boxes = None
        self.idle_changed = False

    @property
    def ready(self):
        return self.clock()-self.last_frame_at < 1.0 and self.detector.frames_seen >= self.detector.warmup_frames

    def start(self, txn_id, attempt, sku, barcode, started_ns, action='add'):
        if (txn_id, attempt) in self.cancelled:
            return
        if self.active and self.active.txn_id == txn_id and self.active.attempt == attempt:
            return
        if self.active:
            self.fail('A second placement started before the first completed; custody is ambiguous')
        f = self.follower_factory(self.frame_size)
        w, h = self.frame_size
        start, end = (self.cart_region, self.scanner_region) if action == 'remove' else (self.scanner_region, self.cart_region)
        f._scanner_box = _region_px(start, w, h)
        f._cart_box = _region_px(end, w, h)
        self.active = Capture(txn_id, attempt, sku, barcode, started_ns, self.clock(), f, action)
        # Ignore previously stationary contents, never a moving target or a new region.
        self.active.stationary_boxes = tuple(d.bbox for d in self.last_detections
            if self.inside(d.centroid, self.cart_region))
        if not self.ready:
            self.fail('Camera disconnected or warming up; remove this unit and scan again')

    def settled(self, txn_id, attempt, stamp_ns):
        if self.active and (self.active.txn_id, self.active.attempt) == (txn_id, attempt):
            if stamp_ns >= self.active.started_ns:
                self.active.settled_ns = stamp_ns

    def cancel(self, txn_id, attempt):
        self.cancelled.add((txn_id, attempt))
        if len(self.cancelled) > 1000:
            self.cancelled.pop()
        if self.active and (self.active.txn_id, self.active.attempt) == (txn_id, attempt):
            self.active = None

    def fail(self, reason):
        active, self.active = self.active, None
        if active:
            self.on_failure(active, reason)

    def frame(self, stream, seq, stamp_ns, frame):
        if stream == self.stream and seq <= self.seq:
            return
        now = self.clock()
        if self.active and now-self.active.opened > self.timeout:
            self.fail('Capture deadline exceeded before a complete resting view')
        if self.stream is not None:
            if stream != self.stream:
                self.fail('Camera restarted during placement')
                if self.on_anomaly:
                    self.on_anomaly('Verification camera restarted; reconcile basket contents')
                self.detector.reset()
            elif seq != self.seq+1 or stamp_ns <= self.stamp_ns or (stamp_ns-self.stamp_ns)/1e9 > self.max_gap_sec or now-self.last_frame_at > self.max_gap_sec:
                self.fail('Missing or delayed camera frames broke the custody chain')
                if self.on_anomaly:
                    self.on_anomaly('Camera observation gap; reconcile basket contents')
        if frame.shape[1::-1] != self.frame_size:
            self.fail('Camera resolution changed during placement')
            if self.stream is not None and self.on_anomaly:
                self.on_anomaly('Verification camera geometry changed; reconcile basket contents')
            self.frame_size = frame.shape[1::-1]
            self.detector.reset()
        self.stream, self.seq, self.stamp_ns, self.last_frame_at = stream, seq, stamp_ns, now
        dets = self.detector.detect(frame)
        self.last_detections = dets
        c = self.active
        if not c:
            # Do not overlook a zero-net-weight swap after the previous verdict.
            # A new/moving region within the basket without an authorized action
            # is review evidence; it can never automatically grant a discount.
            boxes = [d.bbox for d in dets if self.inside(d.centroid, self.cart_region)]
            if self.idle_cart_boxes is not None and self.ready:
                new_motion = any(not any(self.same_stationary(b, old) for old in self.idle_cart_boxes) for b in boxes)
                if new_motion and not self.idle_changed and self.on_anomaly:
                    self.on_anomaly('Unscanned handling inside the basket; reconcile contents before payment')
                    self.idle_changed = True
                elif not new_motion:
                    self.idle_changed = False
            self.idle_cart_boxes = boxes
            return
        self.idle_cart_boxes, self.idle_changed = None, False
        if stamp_ns < c.started_ns:
            return
        dets = [d for d in dets if not any(self.same_stationary(d.bbox, b) for b in c.stationary_boxes)]
        # Extra objects cannot be quietly discarded just because one looks expected.
        if len(dets) > 1:
            self.fail('Multiple moving regions: product identity is ambiguous')
            return
        status = c.follower.update(dets, frame, FrameMeta(seq, stamp_ns/1e9))
        if status in FollowStatus.BROKEN:
            self.fail(f'Item path could not be followed ({status})')
            return
        bbox = c.follower.target_bbox
        if bbox and status == FollowStatus.REACHED_CART and c.follower.observed_seq == seq:
            center = (bbox[0]+bbox[2]/2, bbox[1]+bbox[3]/2)
            still = c.last_center is not None and math.dist(center, c.last_center) <= self.still_pixels
            c.still = c.still+1 if still else 0
            c.last_center = center
            crop = c.follower.current_crop
            if not still or crop is None:
                c.rest_crops.clear()
            if crop is not None:
                c.rest_crops.append(crop)
                c.rest_crops = c.rest_crops[-3:]
        else:
            c.still, c.last_center = 0, None
            c.rest_crops.clear()
        if c.settled_ns and stamp_ns >= c.settled_ns and c.still >= self.still_frames and len(c.rest_crops) == 3:
            self.active = None
            # Explicit final three views come from observed, clear resting frames.
            # Earlier views stay distinct; they cannot vote as resting evidence.
            earlier = c.follower.crops_before(c.rest_crops[0].seq)
            self.on_crops(c, earlier + [k.crop for k in c.rest_crops])

    def inside(self, center, region):
        w, h = self.frame_size
        return region[0]*w <= center[0] <= region[2]*w and region[1]*h <= center[1] <= region[3]*h

    @staticmethod
    def same_stationary(a, b):
        return _iou(a, b) >= .75 and math.dist((a[0]+a[2]/2, a[1]+a[3]/2),
                                               (b[0]+b[2]/2, b[1]+b[3]/2)) <= 6.

    def tick(self):
        if self.active and self.clock()-self.active.opened > self.timeout:
            self.fail('No continuous scan-to-rest path and settled weight within capture deadline')
        elif self.active and self.clock()-self.last_frame_at > self.max_gap_sec:
            self.fail('Verification camera stopped during placement')
