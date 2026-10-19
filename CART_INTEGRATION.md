# Camera ↔ Cart Integration (`NXTCart-Cam` ↔ `smart_cart_ws`)

> **Superseded runtime:** use [`SYSTEM_SETUP.md`](SYSTEM_SETUP.md) for the
> per-unit background verification flow, PC-only inference and checkout gate.
> The older flow below added items only after verification and is historical.

How the camera module joins the ROS 2 cart, what changed in the cart code and
why, and how to run the two together.

> Camera setup, mounting and product photography: [`SETUP_AND_TEST.md`](SETUP_AND_TEST.md).

---

## 1. The gap this closes (read this first)

The cart was already wired for a camera, but the contract carried **no identity**:

```
VisionEvent.msg  (before)
  string action      # 'item_placed' | 'item_removed'
  bool   detected
```

`core_logic.py` only ever did `'item_placed' in self.pending_vision_events` — a
**presence** check. And presence cannot stop the attack the camera exists for:

> Scan a cheap 150 g item. Put in an expensive 150 g item.
> Net weight change = 150 g ✓ · something was placed ✓ → **billed as a success.**

So the camera's verdict had nowhere to go, and `esp32_vision_node.py` did not
produce one anyway — it counted blobs (and imported `ml.identity_tracker` /
`ml.cart_state`, two **superseded** modules). The integration therefore needed
three things, not just a new node:

1. a message that can carry a verdict,
2. a node that actually produces one,
3. a fusion rule in `core_logic` that **requires** it.

---

## 2. Topic map

```
dummy_scan_node ──┐                      (later: qr_scanner_node, USB-HID gun)
 /cart/scanned_item│  ScannedItem{barcode,name,expected_weight,price}
                   ├──────────────► core_logic ──► /cart/ui_display  (CartState) ──► gui_display
dummy_weight_node ─┤                   ▲      └──► /cart/alerts      (String)    ──► gui_display
 /cart/current_weight  Float32         │
                   │                   │ /cart/vision_event  VisionEvent{+verdict,+verified}
vision_verify_node ┴───────────────────┘
      ▲   subscribes: /cart/scanned_item (expected SKU)
      │               /cart/current_weight (its own settle gate)
      └── webcam      /cart/ui_display (cart contents, for removals)
```

`vision_verify_node` is the only new producer; everything else keeps its topics.

---

## 3. What changed

### 3.1 `smart_cart_interfaces/msg/VisionEvent.msg` — extended (backward compatible)

`action` and `detected` keep their meaning, so any existing subscriber still
works. Added:

| Field | Meaning |
|---|---|
| `verdict` | `MATCH` / `SUSPECT` / `MISMATCH` / `RETRY` / `UNAVAILABLE` / `UNVERIFIED` |
| `verified` | **true only for `MATCH`** — the one accepting verdict |
| `barcode`, `name`, `txn_id` | which scan this verdict belongs to |
| `appearance_score`, `colour_score` | the two channels, for logs and tuning |
| `reason` | human-readable text, surfaced to the shopper on refusal |

> Changing a `.msg` means a rebuild: `colcon build --packages-select
> smart_cart_interfaces smart_cart` then re-source `install/setup.bash`.

### 3.2 `smart_cart/vision_verify_node.py` — **new**, replaces `esp32_vision_node.py`

Runs the real verification pipeline: a scan opens a transaction → one item is
locked and followed scanner→cart → the scale must change and settle → the item's
crops are scored on **appearance + colour** against that SKU's reference photos →
a verdict is published.

- **Webcam by default** (`camera_source:=webcam`, `camera_index:=N`);
  `camera_source:=mjpeg` + `camera_url:=…` for an ESP32-CAM later.
- **SKU resolution.** The inventory DB names items `Amul Butter 100g`; reference
  photos live in `references/<folder>`. The node tries, in order: an explicit
  `sku_map_path` JSON entry, the barcode, the exact name, then a normalised name
  (`lower`, spaces→`_`). No match → it publishes **`UNAVAILABLE`** with a clear
  reason rather than guessing a SKU. Simplest setup: **name each reference folder
  exactly the DB `name`.**
- **It consumes weight too.** The camera's own gate needs "mass actually landed",
  so an item merely waved past the cart cannot complete a transaction.
  `core_logic` still does its own independent weight reconciliation — two checks
  on purpose, not duplicated authority.
- `esp32_vision_node` is left in place but is **superseded**; do not launch both.

### 3.3 `smart_cart/core_logic.py` — the identity gate

| Change | Why |
|---|---|
| `vision_callback` stores the **whole event**, not just `msg.action` | The verdict and `verified` flag are what distinguish presence from identity |
| New `_claim_vision()` | Matches one vision event per item, preferring a barcode/name match, so two concurrent actions cannot borrow each other's evidence — and an event is **consumed**, never reused for a second add |
| **An add is billed only when `verified` is true** | Closes the same-weight swap. Gated by the `require_vision_match` parameter (default **true**) |
| A removal needs only to have been **seen** | Taking an item *out* cannot fraudulently add value, so demanding identity there would only punish honest shoppers |
| New third branch: weight-valid but unverified | Gets its own alert — `ITEM MISMATCH: …` with the camera's reason, logged `[SECURITY]` — instead of the generic weight warning. The scan stays pending and **the weight baseline is not advanced**, so a correct re-placement still completes |
| `MAX_SIMULTANEOUS = 3` bounds the combination search | It was `O(2^n)` over cart items: a 20-item cart built **over a million** tuples per weight reading, a real hang on a 2 GB Pi. Now `O(n^3)`, and one shopper action only ever involves a few items |

### 3.4 Stand-ins for missing hardware — **new**

`/cart/current_weight` had **no publisher at all** (no Arduino yet), so nothing
could be tested end to end.

- **`dummy_weight_node`** — type `+150`, `-150`, `150`, `t`, `q`. Publishes the
  same `Float32` grams the Arduino will, at a steady rate.
- **`dummy_scan_node`** — type a row number or barcode; reads name/weight from
  the same `inventory.db` and publishes the same `ScannedItem`.

Why a dummy scanner: `qr_scanner_node` opens `cv2.VideoCapture(0)`. **Two
processes cannot share one webcam**, so with a single camera the QR node and the
vision node fight over it. The dummy frees the webcam for vision.

### 3.5 `bench.launch.py` — **new**

Today's rig: real `core_logic` + real `vision_verify_node` + real `gui_display`,
with the two dummies.

---

## 4. Run it

```bash
# once
cd ~/smart_cart_ws
python3 src/smart_cart/database/setup_db.py
colcon build --packages-select smart_cart_interfaces smart_cart
source install/setup.bash
export NXTCART_CAM_PATH=~/NXTCart-Cam      # if not at the default
```

```bash
# everything, with typed sensors
ros2 launch smart_cart bench.launch.py camera_index:=1
```

The two dummy nodes read **stdin**, so to type into both give each its own
terminal:

```bash
ros2 launch smart_cart bench.launch.py camera_index:=1 with_dummies:=false
ros2 run smart_cart dummy_scan_node       # terminal 2
ros2 run smart_cart dummy_weight_node     # terminal 3
```

### A genuine add
1. `dummy_scan_node`: `1` → scans a 150 g item.
2. Carry that product past the camera, scanner side → cart side.
3. `dummy_weight_node`: `+150`.
4. Expect `[verdict] MATCH`, `[SUCCESS] … verified by weight + camera`, GUI updates.

### The swap (the test that matters)
1. Scan the 150 g item.
2. Carry a **different** 150 g product across.
3. `+150` — the scale is perfectly happy.
4. Expect `[SECURITY] Weight matches … but the camera did NOT verify it`,
   alert `ITEM MISMATCH …` in the GUI, and **nothing billed**.

### A removal
With an item in the cart, carry it back out and enter `-150`. Expect the cart and
bill to drop.

### Bring-up without a camera
`require_vision_match:=false` restores presence-only behaviour. It is
**swap-vulnerable** and logs a warning at startup — bring-up only.

---

## 5. Is item removal handled? — **Yes**

You asked specifically. It was already handled in `core_logic`, and it still is:

- `check_weight_change` builds **removal combinations** from `cart_items`
  alongside add combinations, so a weight *drop* that matches items in the cart
  removes them and the bill goes down (`print_cart` recomputes the total).
- It requires a vision `item_removed` event, so mass vanishing with no camera
  event is **not** a free removal — it alerts instead (tested).
- `vision_verify_node` now publishes `item_removed` **with the SKU it saw
  leaving**: on a weight drop it runs a *closed-set* `classify()` over the cart's
  current contents (from `/cart/ui_display`) and names the item — or publishes
  `UNVERIFIED` with a reason when it cannot tell, rather than guessing.

What removal is **not**: identity-*gated*. `core_logic` accepts a seen removal
without demanding a `MATCH`, deliberately — a removal cannot inflate the bill, so
gating it would only block honest shoppers whose item the camera failed to
recognise on the way out. The camera's removal identity is published and logged,
and is available to tighten later if you want strict reconciliation.

Standalone (non-ROS) the same thing is modelled in `ml/lane.py` +
`ml/cart.py`, which `cart_sim.py` uses: a weight drop is matched against the
recorded weight of each unit in the cart, and when two cart lines share that
weight the camera disambiguates — flagging `AMBIGUOUS_REMOVAL`,
`REMOVAL_MISMATCH` or `UNEXPECTED_REMOVAL` rather than de-billing a guess.

---

## 6. Verify the integration without hardware

```bash
cd /path/to/NXTCart-Cam
py -3 test_verify.py                                   # camera logic
py -3 test_cart_logic.py --ws /path/to/smart_cart_ws    # cart billing + anti-swap
```

`test_cart_logic.py` stubs `rclpy` and the messages and drives the **real**
`core_logic.py`, asserting on what gets billed: the genuine add, the blocked
swap, the recovery after a refusal, weight-alone holds, unscanned mass, the
removal flow, the disabled-gate path, the bounded search, and that a vision event
cannot be reused for two adds.

---

## 7. Known gaps, honestly

| Gap | Impact | Note |
|---|---|---|
| Thresholds unmeasured on your catalogue | Unknown FAR/FRR | `0.72 / 0.55 / 0.50` are seeded guesses. `DEPLOYMENT.md` §6 is the measurement procedure |
| One webcam can't serve QR **and** vision | Can't run both nodes | Use `dummy_scan_node`, or a second camera / real barcode gun |
| `inventory.db` has no price column | `price` is a hardcoded `35.0` in both scanner nodes | Add a `price` column and read it |
| GUI shows an **average** unit price | Per-row price is wrong with mixed prices | `gui_display.update_cart` divides `total_price` by item count; `CartState` carries no per-line prices. Fixing it means extending `CartState` with `CartItem[]` |
| Reference SKU ↔ DB name coupling | A rename silently → `UNAVAILABLE` | Use `sku_map_path`, or keep folder names equal to DB names |
| `esp32_vision_node.py` still present | Confusion | Superseded; don't launch it |
| Frame drops not detected | Custody hole | `frame_source` keeps newest-frame-only; gaps aren't detected (pre-existing, tracked) |
| Pi performance | Unknown | Two cameras' worth of work removed, detector now runs once per frame, but unmeasured on the 2 GB Pi |
