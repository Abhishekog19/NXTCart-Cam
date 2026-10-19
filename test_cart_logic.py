# ---------------------------------------------------------------
# test_cart_logic.py  --  DOES THE CART ACTUALLY REFUSE THE SWAP?
#
# WHY THIS FILE EXISTS
# ─────────────────────
# test_verify.py proves the CAMERA reaches the right verdict.  That is only
# half the system: the verdict then has to survive the trip into the cart's
# fusion brain (smart_cart/core_logic.py) and actually stop the billing.  A
# camera that correctly shouts MISMATCH into a node that ignores it buys
# nothing -- and that was exactly the state of the integration before this
# change, because VisionEvent carried no identity at all.
#
# So this file drives the REAL core_logic.py with fake ROS messages and asserts
# on what gets billed.  ROS 2 is not installed on a dev laptop, so rclpy and
# the smart_cart_interfaces messages are stubbed just enough to import and run
# the node's own logic -- the decision code under test is the shipped file,
# not a copy of it.
#
# Run:  py -3 test_cart_logic.py
#       py -3 test_cart_logic.py --ws /path/to/smart_cart_ws
# ---------------------------------------------------------------

from __future__ import annotations

import argparse
import os
import sys
import types

DEFAULT_WS = os.path.expanduser(
    r"~/Downloads/Archive/smart_cart_ws")

_failures = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)


# ═════════════════════════════════════════════════════════════════
# the smallest ROS that core_logic can run on
# ═════════════════════════════════════════════════════════════════

class _Logger:
    def __init__(self):
        self.lines = []

    def _log(self, level, msg):
        self.lines.append((level, str(msg)))

    def info(self, m):  self._log("info", m)
    def warn(self, m):  self._log("warn", m)
    def error(self, m): self._log("error", m)
    def fatal(self, m): self._log("fatal", m)

    def text(self):
        return "\n".join(m for _, m in self.lines)

    def of(self, level):
        return [m for lv, m in self.lines if lv == level]


class _Param:
    def __init__(self, value):
        self.value = value


class _Pub:
    def __init__(self, topic):
        self.topic = topic
        self.sent = []

    def publish(self, msg):
        self.sent.append(msg)


class _Node:
    """Stands in for rclpy.node.Node: parameters, publishers, logger."""

    # Parameters the test wants the node to come up with.  declare_parameter
    # consults this, so an override survives the node's own super().__init__()
    # -- which really does run a second time through this class.
    PARAM_OVERRIDES = {}

    def __init__(self, name):
        self._name = name
        self._logger = _Logger()
        self._params = {}
        self.pubs = {}
        self.subs = {}

    def declare_parameter(self, name, default):
        if name in _Node.PARAM_OVERRIDES:
            default = _Node.PARAM_OVERRIDES[name]
        self._params.setdefault(name, _Param(default))
        return self._params[name]

    def get_parameter(self, name):
        return self._params[name]

    def set_param(self, name, value):
        self._params[name] = _Param(value)

    def create_publisher(self, msg_type, topic, qos):
        p = _Pub(topic)
        self.pubs[topic] = p
        return p

    def create_subscription(self, msg_type, topic, cb, qos):
        self.subs[topic] = cb
        return types.SimpleNamespace(topic=topic)

    def create_timer(self, period, cb):
        return types.SimpleNamespace(period=period, callback=cb)

    def get_logger(self):
        return self._logger

    def destroy_node(self):
        pass


def _msg(**fields):
    """Build a tiny message class whose fields default like ROS defaults."""
    class M:
        def __init__(self, **kw):
            for k, v in fields.items():
                setattr(self, k, v)
            for k, v in kw.items():
                setattr(self, k, v)
    return M


def install_ros_stubs():
    rclpy = types.ModuleType("rclpy")
    rclpy.init = lambda *a, **k: None
    rclpy.spin = lambda *a, **k: None
    rclpy.shutdown = lambda *a, **k: None
    rclpy.ok = lambda: True
    node_mod = types.ModuleType("rclpy.node")
    node_mod.Node = _Node
    rclpy.node = node_mod
    sys.modules["rclpy"] = rclpy
    sys.modules["rclpy.node"] = node_mod

    std = types.ModuleType("std_msgs")
    std_msg = types.ModuleType("std_msgs.msg")
    std_msg.Float32 = _msg(data=0.0)
    std_msg.String = _msg(data="")
    std.msg = std_msg
    sys.modules["std_msgs"] = std
    sys.modules["std_msgs.msg"] = std_msg

    iface = types.ModuleType("smart_cart_interfaces")
    iface_msg = types.ModuleType("smart_cart_interfaces.msg")
    iface_msg.ScannedItem = _msg(barcode="", name="", expected_weight=0.0,
                                 price=0.0)
    # The EXTENDED VisionEvent this integration introduces.
    iface_msg.VisionEvent = _msg(action="", detected=False, verdict="",
                                 verified=False, barcode="", name="",
                                 txn_id="", appearance_score=0.0,
                                 colour_score=0.0, reason="")
    iface_msg.CartItem = _msg(barcode="", name="", weight=0.0, price=0.0,
                              quantity=0)
    iface_msg.CartState = _msg(names=[], total_weight=0.0, total_price=0.0,
                               total_items=0)
    iface.msg = iface_msg
    sys.modules["smart_cart_interfaces"] = iface
    sys.modules["smart_cart_interfaces.msg"] = iface_msg
    return iface_msg


# ═════════════════════════════════════════════════════════════════
# a tiny driver for the node under test
# ═════════════════════════════════════════════════════════════════

class Lane:
    """Drives core_logic the way the real topics would."""

    def __init__(self, Engine, M, require_vision_match=True):
        self.M = M
        # Seed the parameter BEFORE construction so the node's own __init__
        # sees it (and logs the matching startup banner), exactly as a ROS
        # launch parameter would.
        _Node.PARAM_OVERRIDES = {
            "require_vision_match": require_vision_match}
        try:
            self.node = Engine()
        finally:
            _Node.PARAM_OVERRIDES = {}

    # inbound topics
    def scan(self, barcode, name, weight, price=35.0):
        self.node.scan_callback(self.M.ScannedItem(
            barcode=barcode, name=name, expected_weight=weight, price=price))

    def vision(self, action, verified, verdict="MATCH", name="", barcode="",
               reason=""):
        self.node.vision_callback(self.M.VisionEvent(
            action=action, detected=True, verdict=verdict, verified=verified,
            name=name, barcode=barcode, reason=reason))

    def weigh(self, grams):
        # core_logic only reads msg.data off the Float32.
        self.node.weight_callback(types.SimpleNamespace(data=float(grams)))

    # outbound state
    @property
    def cart(self):
        return [i["name"] for i in self.node.cart_items]

    @property
    def bill(self):
        return sum(i.get("price", 0) for i in self.node.cart_items)

    @property
    def alerts(self):
        pub = self.node.pubs.get("/cart/alerts")
        return [m.data for m in pub.sent] if pub else []

    @property
    def log(self):
        return self.node.get_logger()


# ═════════════════════════════════════════════════════════════════
# the tests that matter
# ═════════════════════════════════════════════════════════════════

def test_genuine_add(Engine, M):
    print("\n[cart] a verified item is billed")
    lane = Lane(Engine, M)
    lane.scan("123456789", "Britannia Marie Gold", 150.0, price=55.0)
    lane.vision("item_placed", verified=True, verdict="MATCH",
                barcode="123456789", name="Britannia Marie Gold")
    lane.weigh(150.0)
    check("verified add lands in the cart",
          lane.cart == ["Britannia Marie Gold"], str(lane.cart))
    check("the bill went up", lane.bill == 55.0, str(lane.bill))
    check("no alert was raised", lane.alerts == [], str(lane.alerts))
    check("the weight baseline advanced",
          lane.node.last_stable_weight == 150.0,
          str(lane.node.last_stable_weight))


def test_same_weight_swap_is_blocked(Engine, M):
    print("\n[cart] THE ATTACK: right weight, wrong item -> refused")
    lane = Lane(Engine, M)
    # Shopper scans the cheap 150 g item...
    lane.scan("123456789", "Britannia Marie Gold", 150.0, price=55.0)
    # ...but puts in a DIFFERENT 150 g item.  The camera says MISMATCH.
    lane.vision("item_placed", verified=False, verdict="MISMATCH",
                barcode="123456789", name="Britannia Marie Gold",
                reason="Item does not match the scanned product.")
    # The scale is perfectly happy: exactly the expected 150 g arrived.
    lane.weigh(150.0)

    check("the swapped item is NOT billed", lane.cart == [], str(lane.cart))
    check("the bill stays at zero", lane.bill == 0.0, str(lane.bill))
    check("the shopper is alerted", len(lane.alerts) == 1, str(lane.alerts))
    check("the alert names an item mismatch, not a weight problem",
          lane.alerts and "MISMATCH" in lane.alerts[0].upper()
          and "WEIGHT MISMATCH" not in lane.alerts[0].upper(),
          str(lane.alerts))
    check("it is logged as a SECURITY event",
          "[SECURITY]" in lane.log.text(), "no [SECURITY] line")
    check("the camera's reason reaches the log",
          "does not match" in lane.log.text(), "reason not surfaced")
    check("the weight baseline did NOT advance (mass unaccounted for)",
          lane.node.last_stable_weight == 0.0,
          str(lane.node.last_stable_weight))
    check("the scan stays pending so a correct re-place can still complete",
          len(lane.node.pending_scans) == 1,
          str(len(lane.node.pending_scans)))


def test_swap_then_correct_item(Engine, M):
    print("\n[cart] after a refused swap, the RIGHT item still completes")
    lane = Lane(Engine, M)
    lane.scan("123456789", "Marie Gold", 150.0, price=55.0)
    lane.vision("item_placed", verified=False, verdict="MISMATCH",
                name="Marie Gold", reason="wrong item")
    lane.weigh(150.0)
    check("refused first", lane.cart == [], str(lane.cart))
    # Shopper removes the wrong item and places the right one.
    lane.weigh(0.0)
    lane.vision("item_placed", verified=True, verdict="MATCH",
                name="Marie Gold")
    lane.weigh(150.0)
    check("the genuine placement is billed", lane.cart == ["Marie Gold"],
          str(lane.cart))


def test_no_vision_event_holds(Engine, M):
    print("\n[cart] weight alone never bills (camera silent -> hold)")
    lane = Lane(Engine, M)
    lane.scan("123456789", "Marie Gold", 150.0, price=55.0)
    lane.weigh(150.0)            # no vision event at all
    check("nothing is billed on weight alone", lane.cart == [], str(lane.cart))
    check("the shopper is told to show the item",
          lane.alerts and "VERIFY" in lane.alerts[0].upper(), str(lane.alerts))
    check("it is a HOLD, not a security accusation",
          "[HOLD]" in lane.log.text(), "no [HOLD] line")


def test_unscanned_item_still_caught(Engine, M):
    print("\n[cart] an unscanned item is still a weight mismatch")
    lane = Lane(Engine, M)
    lane.vision("item_placed", verified=True, verdict="MATCH", name="whatever")
    lane.weigh(500.0)            # mass with no scan behind it
    check("unscanned mass is not billed", lane.cart == [], str(lane.cart))
    check("the classic weight alert fires",
          lane.alerts and "WEIGHT MISMATCH" in lane.alerts[0].upper(),
          str(lane.alerts))


def test_removal_flow(Engine, M):
    print("\n[cart] removal: cart and bill go back down")
    lane = Lane(Engine, M)
    lane.scan("111", "Soap", 150.0, price=35.0)
    lane.vision("item_placed", verified=True, verdict="MATCH", name="Soap")
    lane.weigh(150.0)
    check("item added first", lane.cart == ["Soap"], str(lane.cart))

    # Shopper takes it back out: the scale drops and the camera saw it leave.
    lane.vision("item_removed", verified=True, verdict="MATCH", name="Soap")
    lane.weigh(0.0)
    check("the item is removed from the cart", lane.cart == [], str(lane.cart))
    check("the bill goes back to zero", lane.bill == 0.0, str(lane.bill))
    check("removal needs no identity proof to protect the shopper",
          not lane.alerts, str(lane.alerts))


def test_removal_without_vision_is_held(Engine, M):
    print("\n[cart] mass vanishing with no vision event is not a free removal")
    lane = Lane(Engine, M)
    lane.scan("111", "Soap", 150.0, price=35.0)
    lane.vision("item_placed", verified=True, verdict="MATCH", name="Soap")
    lane.weigh(150.0)
    lane.weigh(0.0)              # mass gone, camera said nothing
    check("the item stays on the bill until the removal is seen",
          lane.cart == ["Soap"], str(lane.cart))
    check("an alert is raised", len(lane.alerts) >= 1, str(lane.alerts))


def test_gate_can_be_disabled_for_bringup(Engine, M):
    print("\n[cart] require_vision_match:=false restores presence-only")
    lane = Lane(Engine, M, require_vision_match=False)
    lane.scan("123456789", "Marie Gold", 150.0, price=55.0)
    lane.vision("item_placed", verified=False, verdict="MISMATCH",
                name="Marie Gold")
    lane.weigh(150.0)
    check("with the gate OFF an unverified add is billed (documented risk)",
          lane.cart == ["Marie Gold"], str(lane.cart))
    check("and the operator was warned at startup",
          "presence-only" in lane.log.text(), "no startup warning")


def test_combination_search_is_bounded(Engine, M):
    print("\n[cart] the combination search is bounded (2 GB Pi)")
    lane = Lane(Engine, M)
    check("MAX_SIMULTANEOUS caps the search",
          getattr(Engine, "MAX_SIMULTANEOUS", None) == 3,
          str(getattr(Engine, "MAX_SIMULTANEOUS", None)))
    # Fill the cart well past the old explosion point and make sure a weight
    # reading still resolves promptly (the old code built 2**30 tuples here).
    for i in range(30):
        lane.node.cart_items.append(
            {"barcode": f"b{i}", "name": f"item{i}", "weight": 100.0,
             "price": 10.0})
    lane.node.last_stable_weight = 3000.0
    import time
    t0 = time.perf_counter()
    lane.vision("item_removed", verified=True, verdict="MATCH", name="item0")
    lane.weigh(2900.0)
    dt = time.perf_counter() - t0
    check("a 30-item cart resolves fast", dt < 1.0, f"{dt:.2f}s")
    check("one item was removed", len(lane.node.cart_items) == 29,
          str(len(lane.node.cart_items)))


def test_vision_events_are_consumed(Engine, M):
    print("\n[cart] a vision event cannot be reused for two adds")
    lane = Lane(Engine, M)
    lane.scan("111", "Soap", 150.0, price=35.0)
    lane.scan("222", "Gel", 150.0, price=120.0)
    # Only ONE verified placement arrives, so only ONE item may be billed.
    lane.vision("item_placed", verified=True, verdict="MATCH", name="Soap")
    lane.weigh(150.0)
    check("first add billed", len(lane.node.cart_items) == 1,
          str(lane.cart))
    lane.weigh(300.0)            # second 150 g lands, still no new vision event
    check("the second add is NOT billed on a reused event",
          len(lane.node.cart_items) == 1, str(lane.cart))
    check("the stale event was consumed, not left in the queue",
          len(lane.node.pending_vision_events) == 0,
          str(lane.node.pending_vision_events))


def main():
    ap = argparse.ArgumentParser(
        description="Drive the real smart_cart core_logic with fake ROS "
                    "messages and check what gets billed.")
    ap.add_argument("--ws", default=os.environ.get("SMART_CART_WS", DEFAULT_WS),
                    help="path to smart_cart_ws")
    args = ap.parse_args()

    pkg = os.path.join(args.ws, "src", "smart_cart")
    if not os.path.isdir(pkg):
        print(f"ERROR: smart_cart package not found under {args.ws}")
        print("Pass --ws /path/to/smart_cart_ws (or set SMART_CART_WS).")
        return 2
    sys.path.insert(0, pkg)

    print("=" * 62)
    print("  smart_cart core_logic - billing + anti-swap behaviour")
    print(f"  workspace: {args.ws}")
    print("=" * 62)

    M = install_ros_stubs()
    from smart_cart.core_logic import CartVerificationEngine as Engine

    test_genuine_add(Engine, M)
    test_same_weight_swap_is_blocked(Engine, M)
    test_swap_then_correct_item(Engine, M)
    test_no_vision_event_holds(Engine, M)
    test_unscanned_item_still_caught(Engine, M)
    test_removal_flow(Engine, M)
    test_removal_without_vision_is_held(Engine, M)
    test_gate_can_be_disabled_for_bringup(Engine, M)
    test_combination_search_is_bounded(Engine, M)
    test_vision_events_are_consumed(Engine, M)

    print("\n" + "=" * 62)
    if _failures:
        print(f"  {len(_failures)} CHECK(S) FAILED: {_failures}")
        print("=" * 62)
        return 1
    print("  ALL CHECKS PASSED")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
