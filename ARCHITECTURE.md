# NXTCart-Cam — System Architecture

**Status:** design of record. Nothing in Sections 3–7 is implemented.
**Companion documents:** `CONTEXT_SNAPSHOT.md` (decision provenance, rejected approaches, measured facts), `BUILD_PLAN.md` (phase order, gates, costs), `IDENTITY_TRACKING.md` (the current CV layer, most of which this architecture retires).
**Scope of this document:** what the system is, how the parts divide responsibility, what each interface carries, and what tolerances govern each decision. It does not contain a schedule — that is `BUILD_PLAN.md`.

Tags used throughout: **[DECIDED]** settled · **[MEASURED]** run on hardware/this machine · **[RESEARCH]** sourced, provenance in the snapshot · **[ESTIMATE]** derived from physics, unverified · **[PROVISIONAL]** pinned here so the design is buildable, to be confirmed by the bench test.

---

## 1. What this system is

A shopping cart that produces a **correct bill** without a checkout counter, and that cannot be robbed silently.

It is **not** a product-recognition system. Recognition has an irreducible error rate and the state of the art still mis-ranks lookalike SKUs (**[RESEARCH]** 94.5% Recall@5, −17.5% at Recall@1). This architecture never asks "what is this object?" as a load-bearing question. It asks:

> **Does the cart balance?**

Everything else is machinery for answering that cheaply and for explaining the answer to a human.

### 1.1 The three design axioms

**A1 — Double-entry bookkeeping.** Two independent books are maintained at all times.

| book | content | source |
|---|---|---|
| **Book A** — the bill | one line per item the system believes it holds, each with a catalog mass | identification path |
| **Book B** — physics | mass actually present in the basket | load cells |

> **The conservation invariant:**
> `measured_basket_mass == tare + Σ(expected_mass(line) for line in bill)` — within tolerance, continuously.
> Violated beyond tolerance for more than a few seconds → **UNEXPLAINED MASS → hard stop.**

Every theft technique — known, or not yet invented — has the same signature: **goods that physically exist are not on the bill.** That is a mass discrepancy by definition, so the system never has to anticipate the technique. **[DECIDED]**

**A2 — Verification, not identification.** The barcode goes first. That converts "which of 1000+ SKUs is this?" into "is this the 342 g rigid cylinder we were told to expect — yes or no?" The lookalike SKU never enters the comparison. The hardest accuracy problem is not solved, it is **deleted**. Verification also tolerates far more sensor noise: mass precision needed drops from ±1 g (identify) to ±5 g (verify). **[DECIDED]**

**A3 — The cheap unspoofable channel constrains the expensive spoofable one, never the reverse.**

| channel | genuinely good at | must never be asked to |
|---|---|---|
| Load cells | proving *that* something happened and *how much*; immune to occlusion, lighting, packaging, orientation | say *what* it is |
| Light curtain | counting objects, direction, coarse size | identify anything |
| Camera | narrowing to a handful of SKUs; watching the act | make the final call between lookalikes |
| Barcode | absolute identity, when it reads | prove anything actually entered the cart |

Concretely: **the barcode is checked against physics, not trusted.** Barcode says SKU-X, SKU-X weighs 200 g, scale measured 400 g → **reject the barcode.** That single inversion makes ticket-switching structurally detectable instead of invisible. **[DECIDED]**

### 1.2 The mechanical precondition — not a preference

**[DECIDED]** The weighed volume must be the *only* volume: **one closed basket, one monitored aperture.** No under-basket rack, no child seat, no side pockets — or weigh them separately, or physically seal them for the session. Open the side of the basket and the guarantee in A1 is gone. This constrains the chassis before any electronics exist.

### 1.3 The guarantee, stated honestly

There is no foolproof. What is achievable, and what loss prevention actually needs:

> **No theft can happen silently.** It may be flagged rather than physically prevented, but nothing passes undetected.

The design goal is not impossibility. It is making an attack require satisfying **four independent physical channels simultaneously, in ~300 ms, on camera.**

---

## 2. Block diagram

```
                    ┌──────────── THE APERTURE (one, monitored) ────────────┐
                    │                                                       │
  [S1] rim barcode  │   [S5] custody camera        [S2] two-plane curtain   │
   fixed reader ────┼──►  60 fps, fixed light   ──►  ~1 kHz, 16 pairs/plane │
                    │         │                            │                │
                    └─────────┼────────────────────────────┼────────────────┘
                              │                            │  crossing event
                              │                            │  (the CLOCK)
                              ▼                            ▼
        ┌──────────────────────────────────────────────────────────────┐
        │  MCU / sensor node  —  hard real time, no learning, no OS    │
        │  · samples curtain @1 kHz, load cells @500–1 kHz             │
        │  · timestamps every edge, owns the pre/post mass windows      │
        │  · emits CrossingEvent + MassDelta + health                   │
        └──────────────────────────────────────────────────────────────┘
                    ▲                        ▲                    │
        [S3] 4× load cell            [S4] IMU                     │ serial
         read INDEPENDENTLY      still/rolling/tilt/lift          │ framed msgs
         (never paralleled)                                       ▼
        ┌──────────────────────────────────────────────────────────────┐
        │  HOST (SBC)                                                  │
        │                                                              │
        │  ┌── PATH 1: IDENTIFICATION ────────────────────────────┐    │
        │  │  candidate set → escalation ladder → EvidenceVector  │    │
        │  │  → adjudicator (rules now, GBT later)                │    │
        │  │  → VLM escalation on ~2% of events                   │    │
        │  └──────────────────────────────────────────────────────┘    │
        │                                                              │
        │  ┌── PATH 2: CONSERVATION ──────────────────────────────┐    │
        │  │  hand-coded, always on, INDEPENDENT of Path 1         │    │
        │  │  measured mass vs Σ bill  →  OK | DRIFT | HARD STOP   │    │
        │  └──────────────────────────────────────────────────────┘    │
        │                                                              │
        │  LEDGER (Book A) · append-only EVENT LOG · shopper screen     │
        └──────────────────────────────────────────────────────────────┘
                              │
                              ▼  exit gate: grade summary, targeted audit
```

**Path 1 can fail entirely** — misidentify everything, miss an item completely — **and Path 2 still catches the theft.** The two paths share no code and no state beyond the ledger. That independence is the architecture; do not "simplify" it by fusing them.

---

## 3. Sensor layer

### 3.1 S1 — Rim barcode reader

**[DECIDED]** The barcode is the base layer, **presented at the rim to a fixed reader**, not read in flight.

| property | value | status |
|---|---|---|
| Mounting | fixed, at the rim, angled so a held item's face is naturally presented | **[DECIDED]** |
| Class | omnidirectional starburst/Lissajous laser or 2D imager; 200–1200 scan lines/s | **[RESEARCH]** |
| Tolerance | reads poorly printed, wrinkled, torn codes; commonly 13 mil (0.33 mm) | **[RESEARCH]** |
| Output | `{code, timestamp, symbology}` — one message per read, consumed exactly once | **[DECIDED]** |

**Reading a code off a tumbling item in free fall is out of scope.** **[DECIDED]** (User's call. The blocker is orientation, not time in zone — a 200 mm ring at ~1.4 m/s gives ~140 ms and 500+ read attempts, yet no product or paper does it, and every working industrial system constrains the motion. See snapshot §1.1.)

**Chain of custody is the adopted mechanism instead.** The requirement is not "read the code during entry"; it is "prove the item scanned is the item that entered." Scan at the rim (the shopper naturally holds it still), then S5 keeps that one object under **continuous observation for ~1 s** until it crosses the curtain. A swap *requires* a discontinuity — a gap in observation, a second object appearing, or an appearance change — and each is trivially detectable at 60 fps.

**Optional, not required:** a ring reader that *also* reads a code and disagrees with the rim scan catches ticket-switching red-handed with hard evidence. A short chute or sloped tube would settle orientation and lengthen time in zone — a mechanical fix to a sensing problem, the cheapest kind. Chain of custody makes it unnecessary.

### 3.2 S2 — Two-plane IR light curtain (**the clock**)

**[DECIDED]** Two parallel planes of pulsed infrared beams across the aperture. Passive, a few hundred rupees of LEDs and phototransistors, invisible to the shopper. A beam break, not an image — immune to lighting, shadows, packaging gloss, colour and occlusion, i.e. everything that breaks the current CV pipeline.

| parameter | value | status |
|---|---|---|
| Sample rate | **~1 kHz** | **[DECIDED]** |
| Emitter/receiver pairs per plane | ~16 | **[ESTIMATE]** |
| Beam pitch within a plane | **10 mm** | **[PROVISIONAL]** — 20 mm also stated; 10 mm is what every reliability estimate assumed, so build to 10 mm |
| Plane separation | **40 mm** | **[PROVISIONAL]** — 30 mm stated earlier; 40 mm is the later, more authoritative statement |
| Silhouette resolution | ~10 mm across (= pitch) × ~1.5 mm along the fall | **[ESTIMATE]** |
| Transit time through the ring | ~140 ms (200 mm @ 1.4 m/s) | **[ESTIMATE]** |
| Ambient-light rejection | **mandatory** — modulate the LEDs at a known frequency, receiver demodulates and ignores steady light | **[DECIDED]** |

**What each increment buys.** One beam → something crossed. A row of 16 → *which* beams are blocked: 5–7 = narrow; 2–14 = wide; **3–5 and 9–11 with a clear gap = two separate objects.** Counting discrete objects is what cameras are worst at and what a beam row is best at. Two rows → **direction, free**: upper breaks first = **IN**, lower first = **OUT**, the doorway people-counter / turnstile principle. Sequence, not inference. Two rows + 1 kHz → speed; speed turns time into distance, so the blocked-beam pattern over time **reconstructs a silhouette** — the flatbed-scanner trick, except the sensor line stays still and the object moves past it. Silhouette + mass → **density**: a 340 g chips bag ≈ 0.1 g/cm³, a 340 g pickle jar ≈ 1.2 g/cm³.

**Hand-vs-item discrimination is topological. [DECIDED]** A hand stays connected to the rim (the arm) and never fully clears; an item enters and fully clears. Trivial for a curtain, genuinely hard for a camera.

**It cannot be blinded silently.** Covering a camera produces a black frame; blocking a beam **is** an event. Sensor health is itself a sensor.

**[ESTIMATE] Direction reliability:** at ~1.4 m/s with 40 mm separation the planes break ~29 ms apart — ~29 samples of separation at 1 kHz. Essentially never wrong.

**[DECIDED] Hard ceiling — do not chase 3D.** One row gives a **flat silhouette**, exactly like a torch shadow on a wall. Two rows crossed at 90° give front + side views (the sensible upgrade, enough to estimate volume); four or more angles begin CT-style cross-section reconstruction and are heavy. **Beams can never see colour, print, texture or concavity.** And resolution buys nothing on the case that matters: blue and green Gatorade are *geometrically identical*, so a perfect 0.1 mm scanner would correctly report the same object. Push each channel only until it is good enough for its own job, then stop. The curtain's job is **count, direction, coarse size class**.

**[RESEARCH] Prior art:** light curtains are mature industrial safety equipment certified under **IEC 61496**, specified to detect a **14 mm finger**. When a sensor is trusted to prevent amputations, basic detection reliability is not the risk. An industrial product already counts and profiles objects passing on a conveyor, sold as a **"measuring light grid."**

**Operational cost to design for: dirt.** Grocery environments are dusty and sticky; grime on an emitter reads as a blocked beam. Requires recessed or wiped optics **plus a self-check that reports dirty beams.**

### 3.3 S3 — Load cells (**the truth**)

**[DECIDED] The invariant that shapes the whole design:** load-cell error is specified as a **percentage of full-scale output (FSO)**, not of the thing being weighed.

| configuration | absolute error | status |
|---|---|---|
| 30 kg basket, cheap cells @ 0.05% FSO | **±15 g** — a 10 g packet is below the noise floor | **[RESEARCH]** |
| Same cells at 3 kg capacity | ±1.5 g | **[RESEARCH]** |

**The distinction that matters.** %FSO governs **absolute** accuracy — linearity, hysteresis, temperature drift, creep, zero balance. It does **not** govern **short-term repeatability.**

> **[ESTIMATE]** Measure a **delta over a ~300 ms window with the cart stationary** and all of that cancels — both readings share the same thermal and creep state. What remains is short-term noise. With a 24-bit converter and averaging: **±3–5 g on a 30 kg basket.**

That figure is why there is no weighing tray. And because the job is verification, **±5 g is sufficient.** The curtain is what makes the differential clean: it says *exactly* when the object crossed, so the pre- and post-windows are tightly bracketed around a known sub-millisecond trigger. Differential measurement done properly needs a trigger, and the curtain is one.

| parameter | value | status |
|---|---|---|
| Cells | 4, one per basket corner, **read independently — never wired in parallel** | **[DECIDED]** |
| Why independent | paralleling *averages the signals away*; four readings give total mass **and** 2D **centre of mass** | **[DECIDED]** |
| Sample rate | **500–1000 Hz**, to retain the load-step transient | **[DECIDED]** |
| ADC | HX711 (10/80 SPS) proves the mass *step* only; the impulse channel needs **ADS1220 (2 kSPS)** or **ADS1256 (30 kSPS)** class | **[DECIDED]** |
| Recalibration interval | 18 months – 2 years | **[RESEARCH]** |

**Centre of mass is a free cross-check.** "Camera saw something land left-rear" vs "mass landed left-rear" — two sensors auditing each other, neither needing to recognise anything. Mass landing where the camera saw nothing is unexplained.

**Keep the ringing everyone else filters out. [DECIDED]** An abrupt load step excites the cell's natural frequency; how fast the oscillation damps distinguishes a **rigid** can from a **soft** pouch from **granular** rice or dal that sloshes. A free material channel from hardware already present. It will not name a SKU; it cross-checks the vision class and splits same-mass items.

### 3.4 S4 — IMU

**[DECIDED]** Classifies cart motion into **stationary / rolling / tilted / lifted**. Mass is trusted only when stationary. Cheap, and it doubles as tamper detection: tilting and lifting are attacks (dump the basket), not just noise.

### 3.5 S5 — Custody camera

**[DECIDED]** One fixed camera under fixed lighting, 60 fps, with three narrow jobs and no open-set responsibility:

1. **Chain of custody** — hold one object under continuous observation for ~1 s between rim scan and crossing (§3.1).
2. **1-vs-1 verification** — does this look like the scanned SKU? A hypothesis test, not a ranking.
3. **Colour** — the Gatorade discriminator. *"Is this bottle mostly blue or mostly green?"* is a hue histogram under white balance, not a neural network.

Fixed lighting is what lets MOG2 retire in favour of static differencing, and what makes the colour channel trustworthy. **Camera blindness is an alarm, not a degraded mode.**

---

## 4. Event model and timing

**[DECIDED] The curtain is the clock. Nothing is decided without a curtain event.** That single rule eliminates every phantom detection, shadow flicker and hand-waving artefact in the current build — hands do not fully cross, and they weigh nothing.

### 4.1 Aperture state machine

```
   IDLE
    │  rim barcode read
    ▼
   ARMED ────────────── custody timeout (~3 s) ─────────────► IDLE (code expires)
    │  custody open: one object tracked, ~1 s
    │  custody broken (gap / 2nd object / appearance change) ─► CUSTODY_FAIL
    │                                                            → "please rescan"
    ▼  plane break
   CROSSING            (~140 ms; both planes, all beams, @1 kHz)
    │  last beam clears
    ▼
   SETTLING            (mass post-window; IMU must report stationary)
    │
    ▼
   ADJUDICATE  ──► ledger commit (grade A/B/C) | flag | HARD STOP
    │
    ▼
   IDLE
```

Notes. A crossing with **no ARMED code** is still a full event — it adjudicates as grade U or a hard stop, never as nothing. `CUSTODY_FAIL` is a *loud, cheap* failure: it means "rescan," not "lose the item." That is the whole reason the surviving tracker code can be simple.

### 4.2 Mass windowing

```
        pre-window            crossing            settle       post-window
   ├──── 300 ms ────┤   ├─── ~140 ms ───┤   ├── 200 ms ──┤   ├── 300 ms ──┤
   │ IMU stationary │                                          │ IMU stationary │
   └── mean → m_pre ┘                                          └─ mean → m_post ┘

   Δmass = m_post − m_pre          (sign gives direction, independently of S2)
```

**[PROVISIONAL]** 300 ms pre/post. 200 ms and 400 ms were both stated at different times for different design variants; 300 ms is the value the ±3–5 g estimate was made against, so build and measure at 300 ms and tune from the error curve. If either window cannot complete with IMU stationary, the event is deferred, then adjudicated at reduced grade — never silently dropped.

The impulse/ringing signature is extracted from the **crossing + settle** span, which is why the ADC rate in §3.3 matters.

### 4.3 Wire format, MCU → host

The MCU owns hard real time and emits one framed message per event. It performs **no identification and no learning** — deliberately, so timing is provable.

```json
{
  "type": "crossing",
  "seq": 10432,
  "t_first_break_us": 918273645,
  "direction": "IN",
  "objects": 1,
  "silhouette": {
    "width_mm": 68, "height_mm": 210,
    "profile": [[0,3],[1,7],[2,7], "..."]
  },
  "mass": {
    "pre_g": 2340.4, "post_g": 2575.1, "delta_g": 234.7,
    "sigma_g": 4.1,
    "com_pre": [0.48, 0.51], "com_post": [0.31, 0.62],
    "impulse_class": "rigid", "damping_ratio": 0.19
  },
  "imu": "stationary",
  "health": { "dirty_beams": [], "cell_faults": [], "cam_ok": true }
}
```

`direction` comes from beam-plane ordering, not inference. `profile` is a list of `(sample_index, beams_blocked)` pairs. `health` is a first-class field, not diagnostics — a dirty beam or a dead cell degrades the grade ceiling for every subsequent event until cleared.

---

## 5. Path 1 — Identification

### 5.1 The evidence vector

**[DECIDED]** One ~20-feature vector per crossing. This is the sole input to adjudication, which is what makes the decision auditable and the model swappable.

| # | feature | source |
|---|---|---|
| 1–3 | `delta_g`, `expected_g`, `residual_g` | S3 + catalog |
| 4 | `residual_ratio` = residual ÷ expected | derived |
| 5 | `sigma_g` | S3 |
| 6 | `direction` (IN / OUT) | S2 |
| 7 | `object_count` | S2 |
| 8–9 | `silhouette_width_mm`, `silhouette_height_mm` | S2 |
| 10–11 | `density`, `expected_density` | S2 + S3 + catalog |
| 12–13 | `impulse_class`, `expected_material` | S3 + catalog |
| 14 | `com_shift` | S3 |
| 15 | `colour_distance` | S5 |
| 16 | `vision_score` (1-vs-1) | S5 |
| 17–18 | `barcode_present`, `barcode_agrees` | S1 |
| 19 | `custody_intact` | S5 |
| 20 | `cart_motion_state` | S4 |
| 21 | `sensor_health_ok` | MCU |

### 5.2 The escalation ladder

**[DECIDED]** In order. Each rung only has to catch what the rungs above it miss — which is why none of them individually needs to be excellent.

| # | rung | catches |
|---|---|---|
| 1 | **Barcode at the rim** | if it reads and physics agrees, done |
| 2 | **Weight** | wrong size, wrong quantity |
| 3 | **Curtain count + direction** | extra objects; insertion vs removal |
| 4 | **Silhouette + density** | wrong product category |
| 5 | **Colour** | the Gatorade case |
| 6 | **Label text** | same-colour variants. **Weakest link, last resort** |

**Why stacking works:** *the cases that defeat shape and weight are usually the ones colour solves instantly; the cases that defeat colour are usually the ones shape or weight solve instantly.* It is not that each channel is strong — it is that **their blind spots do not overlap.**

Rung 6 is hypothesis verification (*"does this label contain the word we expect?"*), not general OCR — a far easier task, and the honest end of the road for identical packaging differing only in print.

### 5.3 The seven per-crossing checks

| # | check | fails when |
|---|---|---|
| 1 | Direction — IN or OUT | — |
| 2 | Object count from the shadow pattern | two items dropped when one was scanned |
| 3 | Cross-sectional profile ≈ expected for the scanned SKU | different-shaped item substituted |
| 4 | Δmass ≈ expected mass for the scanned SKU | wrong item, extra item, or multiple |
| 5 | Density (mass ÷ curtain volume) ≈ expected | same-mass, different-material substitution |
| 6 | Camera 1-vs-1 match against the scanned SKU | visually different item |
| 7 | A barcode read exists and is unconsumed | nothing scanned at all |

All seven agree → **grade A, silent pass.** One disagrees → flag the line. **Curtain fires with no barcode, or mass moves with no curtain event → hard stop.**

### 5.4 Counting policy — count, never divide

**[DECIDED]** Quantity is **counted by the curtain, never derived as weight ÷ unit weight.** The division creates a theft vector cheaper than the one it solves: scan one 5 g sachet at ₹2, drop one 50 g item worth ₹200, the system computes 50 ÷ 5 = 10 and bills **₹20 for a ₹200 item.** The division is valid only if you already know everything that entered is the same item — precisely the assumption an attacker breaks.

| weight says | curtain counts | verdict |
|---|---|---|
| 1× | 1 object | ✅ normal, silent pass |
| N× | **N objects** | ✅ genuinely N singles. Bill N, confirm on screen |
| N× | **1 object** | ⚠️ a multipack, or the wrong item. **Ask for the pack's barcode** |
| N× | fewer than N | ⚠️ ambiguous. Ask |
| 1× | 2+ objects | ⚠️ something extra came in. Flag |

Row three is also **commercially more correct**: a sealed pack of 4 soaps is its own SKU at its own price, usually *cheaper* than four singles, so billing 4 singles would overcharge.

**Per-SKU counting policy in the catalog. [DECIDED]** Loose sachets clump and are undercounted by the curtain, so weight counts them better; anything bulky is counted better by the curtain. Mark each SKU with the channel to trust, and require agreement wherever both are reliable.

### 5.5 Provenance grades

**[DECIDED]** Grades replace confidence scores. A grade records **how a line got onto the bill**, not how confident a model felt.

| grade | evidence | treatment |
|---|---|---|
| **A** | barcode + mass + vision all agree | walk out |
| **B** | mass + vision agree, no barcode (loose produce, unbarcoded goods) | priced, low risk |
| **C** | one channel only, or marginal agreement | priced, flagged |
| **U** | mass with no identity, or identity with no mass | **hard stop** |

Two consequences matter more than they look. **Targeted partial audit:** a U line means staff verify *that one item*, not recount the basket — a 10-second intervention, which is what makes the staffing arithmetic work at Indian labour ratios. **The failures become the training set:** every audit yields a human-labelled ground-truth pair on exactly the cases the system found hardest. Most systems discard their hard cases; this one harvests them.

### 5.6 Adjudicator

**[DECIDED] Rules first, model second — not the reverse.** Ship with conservative hand rules; there is no data on day one. Collect audit labels. Introduce the model after **a few thousand real audited events.**

**Model choice: gradient-boosted trees on the edge.** A 20-feature tabular problem does not need deep learning. GBTs infer in microseconds, need very little data, and — the reason for the choice — **report which feature drove the decision.** Two advantages over hand-written rules: they learn **interactions** ("an 8 g mass error is fine on a 2 kg bag of atta but very suspicious on a 40 g biscuit pack" — captured badly by rules, naturally by trees), and **every audit becomes a labelled training example** generated precisely where the system is weakest.

This is what replaces the hand-tuned constants — `0.72`, `0.80`, `0.55`, `EXIT_CONFIRM_FRAMES = 3` — whose tuning motivated the redesign. Hand-tuning those *is* manual construction of a decision boundary.

> ### The hard boundary
> **A learned model may never own the conservation invariant.**
> "Unexplained mass in the basket → stop" stays hand-coded and non-negotiable. A learned model drifts, can be probed, and offers no guarantees.
> **Rules own the extremes — clear pass and clear fail. The model owns only the grey zone.** The model can then be wrong without the system being unsafe.

**VLM escalation, ~2% of events. [DECIDED]** When the cheap stack is genuinely stuck, send three frames: *"Is this bottle blue or green Gatorade?"* Sub-second, fractions of a paisa. **[RESEARCH]** A 2026 retail theft-detection paper gated an expensive VLM behind cheap always-on detectors and cut model calls **240×** versus per-frame invocation. Cheap deterministic stack handles 98%; the expensive model handles the 2% that matter.

**A product requirement the model choice is downstream of. [DECIDED]** In India, wrongly accusing a paying customer at the exit is far worse than losing the item — socially explosive, and capable of damaging a store permanently. **False accusation is a more expensive failure than theft.** Therefore: flags must be **explainable** — "the weight was 340 g more than the item you scanned" is a conversation you can have, "the model returned 0.31" is not — and the default response to a flag is **quiet resolution, never confrontation.** Interpretable trees over black boxes, for business reasons as much as technical ones.

---

## 6. Path 2 — Conservation

**[DECIDED]** Runs continuously, hand-coded, sharing no code with Path 1.

```
residual(t) = measured_mass(t) − (tare + Σ expected_mass(line))

tolerance    = max(BASE_TOL_G, K · sqrt(Σ σ_i²))      # grows with basket size
```

**[PROVISIONAL]** `BASE_TOL_G ≈ 15 g`, `K ≈ 3`. Both are placeholders until the measured per-cell error curve exists; the *form* — a floor plus a term that grows as the root-sum-square of per-line uncertainty — is the decided part, because per-line errors are independent and must not be summed linearly.

| condition | state | action |
|---|---|---|
| `abs(residual) ≤ tolerance` | **BALANCED** | silent |
| exceeded, IMU not stationary | **INDETERMINATE** | wait; do not judge a moving cart |
| exceeded > few seconds, stationary | **UNEXPLAINED MASS** | **hard stop**, staff alert, log |
| mass step with **no** curtain event | **BREACH** | hard stop — something entered off-aperture |
| curtain event with **no** mass step | **BREACH** | hard stop — sensor fault or spoof |
| IMU reports tilt/lift with mass loss | **DUMP** | hard stop |

Everything is written to an **append-only, auditable event log**. **[DECIDED]** No sensor architecture fixes staff collusion; a log where overrides are traceable is what does.

---

## 7. Removal — the four-part fix

**[DECIDED]** This is where the design departs most from the current code, and the reason is a framing error, not a tuning failure.

> The old design inferred removal from **absence**: *"I can't see it any more, so maybe it left."* That is **structurally unfixable.** Absence has two causes — it left, or it's hidden — and no threshold separates them. Every removal bug chased in the CV build was a symptom of that one wrong question.

**The new design never asks whether an item is still there.**

**1. Direction is a physical event, not an inference.** Two beam planes **40 mm** apart. Upper-then-lower = **IN**; lower-then-upper = **OUT**. The doorway people-counter principle. The event fires on the crossing and is **finished** — nothing is watched before or after. Removal stops being a special case: same sensor, same event, opposite sign.

**2. Mass says how much left.** 2,340 g → 2,105 g means **235 g left.** A measurement, not a guess — the §4.2 differential, bracketed by the curtain trigger.

**3. Identity comes from the bill — which is why removal is *easier* than insertion.** Insertion asks "which of 1000+ SKUs is this?" (open set, and exactly what failed). Removal asks "which of the items on **this shopper's own bill** weighs 235 g?" **Closed set, n ≈ 15–20.** The bill is a whitelist that shrinks the search space ~**70×**. Ties break in order: **silhouette → density → colour.** If it still cannot decide, the screen asks — rare, and honest.

**4. Ambiguity always resolves against the shopper's financial advantage.** If two bill lines still match, **credit back the cheaper one.** This is not politeness — it closes the only real removal attack: buy a ₹400 item and a ₹40 item of equal mass, remove the cheap one, hope to be credited the expensive one. Crediting the cheaper candidate makes that attack **net zero.** Asymmetry of complaint reinforces it: an under-credited shopper complains and is fixed at the counter in 20 seconds; an over-credited one says nothing and walks out with free goods.

**The shopper does nothing** — no rescan, no button, no "removal mode."

---

## 8. Attack coverage

| trick | curtain | mass | camera | barcode | conservation |
|---|---|---|---|---|---|
| Nothing scanned, item dropped in | ✅ | ✅ | ✅ | ✅ missing | ✅ |
| Scan cheap, drop expensive | ✅ profile | ✅ | ✅ | ✅ contradicted | ✅ |
| Scan one, drop two together | ✅ **counts 2** | ✅ 2× mass | ✅ | — | ✅ |
| Scan one, drop two separately | ✅ two events | ✅ | ✅ | ✅ one code | ✅ |
| Substitute same-mass item | — | — | ✅ | ✅ | — |
| Same mass *and* similar look | ✅ profile | ✅ density | — | ✅ | — |
| Hand in, palm an item out | ✅ **OUT event** | ✅ | ✅ | — | ✅ |
| Cover the camera | ✅ still fires | ✅ | ✅ blindness = alarm | — | ✅ |
| Block the curtain | ✅ **block = event** | ✅ | ✅ | — | ✅ |
| Items into own bag inside cart | — | — | — | — | ✅ **only this layer** |
| Throw items over the side | — | — | — | — | ✅ **only this layer** |
| Tilt cart and dump | — | — | — | — | ✅ + IMU |

The last three rows are the attacks that beat **every camera system shipping today, including Amazon's.** Conservation is the only thing that catches them — which is why it is the floor, not a fallback, and why §1.2 is structural.

### 8.1 Residual holes, stated plainly

- **Items under ~5 g** fall below the mass noise floor. Curtain and camera still see them; theft value is negligible.
- **Two items in perfect overlap**, combined mass and profile close to the scanned SKU. Extremely hard to execute, and the multi-beam shadow pattern makes true overlap detectable — two touching objects rarely produce one clean silhouette. When counting *does* fail it fails loudly: twice the expected width **and** twice the expected weight both flag. **One layer's blind spot is another layer's obvious error** — that property, not any single number, is what makes the stack strong.
- **Same shape, same weight, same colour, different price** — "anti-dandruff" vs "regular" shampoo in a near-identical bottle. Nothing physical separates them; rung 6 is the only answer. **This is the weakest link and where real-world failures will concentrate.**
- **Sensor sabotage** — detectable, not preventable. Becomes a staff alert, not a silent loss.
- **Staff collusion** — needs the append-only log, not a sensor.

**No system-level accuracy figure should be quoted before the red-team test.** An honest one can only come from people actively trying to beat it; anyone quoting a percentage earlier is guessing.

---

## 9. Software architecture

### 9.1 Layering

```
firmware/                MCU. Hard real time. No identification, no learning.
  curtain.c              1 kHz scan, modulated drive, edge timestamps, dirty-beam self-check
  loadcell.c             4 independent channels, 500–1 kHz, ring buffer, COM, impulse features
  imu.c                  motion classification
  event.c                windowing, framing, health rollup

ml/                      HOST.
  ledger.py              Book A. Lines, grades, append-only log.       <- grows from cart_state.py
  conservation.py        Path 2. Hand-coded. Owns the invariant.       <- NEW, and never learned
  adjudicator.py         rules now, GBT later. Consumes EvidenceVector.<- NEW
  evidence.py            vector assembly from sensor + catalog + vision<- NEW
  candidates.py          closed-set generation (bill for OUT, barcode for IN)
  catalog.py             SKU: mass, sigma, dimensions, density, material, counting policy, price
  custody.py             ~1 s single-object continuity check           <- the surviving tracker
  colour.py              hue histogram under fixed lighting            <- NEW, trivial
  embedding_extractor.py 1-vs-1 verification                           <- survives, unchanged
  matcher.py             ranks within a candidate set                  <- survives, simpler
  camera.py              frame grabber                                 <- survives
  sensors/               MCU link, message parsing, health tracking    <- NEW
test_scripted.py         fusion + adversarial harness                  <- survives and grows
build_db.py              reference DB; the photo SOP lands here        <- survives
```

### 9.2 Fate of the existing code

**This reframe shrinks the codebase rather than restarting it.**

| file | fate |
|---|---|
| `ml/embedding_extractor.py` | **survives**, more valuable. Later: fine-tune on own SKUs |
| `ml/matcher.py` | **survives**, simpler — ranks within a candidate set instead of searching all |
| `build_db.py` + `references/` | **survives.** Where the photo/reference SOP lands |
| `ml/camera.py` | **survives** |
| `test_scripted.py` | **survives and grows** into the fusion + adversarial harness |
| `ml/cart_state.py` | **grows** into the double-entry ledger |
| `ml/detector.py` | mostly retired — static differencing in controlled lighting replaces MOG2 |
| `ml/identity_tracker.py`, `ml/track.py` | **largely deleted** — except the ~1 s chain-of-custody check |

That last row is the point. The thousand lines of occlusion and reacquisition logic exist **only** because the old architecture had to watch objects forever: `OCCLUDED`, `LOST`, `REACQUIRE`, presence checks, visibility gating, merge guards, exit-progress accounting. In an event-gated design that entire problem statement disappears. **The hardest code in the repo becomes dead code.**

### 9.3 Do not confuse the two removal mechanisms

The current code has a **four-guard removal path** at `ml/config.py:395-450` — motion exit (`MOVING_MIN_DISPLACEMENT = 7`, `EXIT_CONFIRM_FRAMES = 3`, `EXIT_BOUNDARY_MARGIN = 45`), presence check (`PRESENCE_ITEM_MATCH = 0.55`, `PRESENCE_BG_MATCH = 0.60`, `PRESENCE_VACATED_FRAMES = 5`), hand-cover grace (`EXIT_EVIDENCE_GRACE_FRAMES = 2`), clip disambiguation (`EXIT_CLIP_MARGIN = 8`).

**That is not the four-part removal fix of Section 7.** It is the CV-era mitigation of the same problem, and Section 7 exists precisely because that approach asks the unfixable question. Both are documented deliberately. Do not merge them.

### 9.4 Test architecture

`test_scripted.py` already has the right shape: an oracle mode and a synthetic mode. Extend it to consume **scripted sensor event streams** — mass steps, curtain patterns, barcode reads, vision scores, including adversarial ones — and assert the ledger verdict and the conservation state. This develops and red-teams the entire fusion logic **before a single load cell arrives**, and every row of §8 becomes a permanent regression test. Every successful red-team attack is added here forever.

**[MEASURED] Current harness state:** all documented runs show **zero false cart changes**, with one safe missed ADD in `synthetic/basic_overlap`. Honest caveat carried forward: the synthetic harness registers **zero** `-> LOST` transitions, so it proves no regression but validates none of the presence logic. **Nothing has met a real webcam.**

### 9.5 Measured performance of the current stack

Retained so nobody re-derives it. **[MEASURED]**

| item | value |
|---|---|
| `process()` median / p95 / max | 19.77 ms (50.6 fps) / 23.50 ms / 33.40 ms |
| `extract_embedding` — ONNX via `cv2.dnn` | 8.28–12.77 ms |
| `extract_embedding` — TFLite (1 thread, no delegate) | **1618.87 ms** — its only non-crashing config; 4-thread and both XNNPACK variants segfault (exit 139) |
| `detector.detect` | 7.96–11.98 ms |
| `match()` | 0.03 ms |
| Recognitions over 120 frames, cap 1/frame | 118 — budget held |
| Camera open, DSHOW vs MSMF | 130 ms vs 2923 ms |
| Leave-one-out top-1 (TFLite quant / ONNX float) | 19/20 both |
| Grid search @ `0.72` / margin `0.03` | 17/20 true accepts, **0 wrong**, **0/20** unknowns falsely locked |
| Unknown-object similarity ceiling | 0.632 |

---

## 10. Non-goals

Recorded so they are not relitigated. Full reasoning in `CONTEXT_SNAPSHOT.md` §4.

- **A gate tray or weighing plate at the mouth**, and the two-scale hierarchy that went with it — rejected as too slow and too variable, and it left removal unaddressed. Superseded once differential weighing reached ±3–5 g. Keep only as the fallback if measured differential resolution is far worse than estimated.
- **Reading barcodes off items in free fall** — orientation, not time in zone.
- **A detailed 3D reconstruction from the curtain** — geometrically identical SKUs make it worthless.
- **Quantity by weight ÷ unit weight** — creates a cheaper theft vector.
- **A vision-first architecture** — Amazon proved the ceiling with unlimited budget: overhead cameras *plus* shelf weight sensors, broken above ~20 shoppers, and on 2024-04-04 revealed as *"powered by 1,000 Indian workers"* reviewing transactions manually, then replaced by Dash Carts.
- **Behavioural/CCTV theft detection as a security mechanism** — best zero-shot result found was 89.5% precision at **59.3% recall.** A system that misses 4 in 10 thefts is not a loss-prevention product.
- **Late fusion** (run every channel, average the confidences) — inherits every weakness. Replaced by A3 and the ladder.
- **RFID on everything, or on nothing** — tiered by SKU value. Tags run $0.04–1.00: fatal on a ₹10 packet, trivial on a ₹900 razor pack. Shrink concentrates in a small SKU set (blades, spirits, infant formula, cosmetics, electronics accessories); tag that tier only.
- **Charging the shopper anything, or selling the hardware** — hardware-as-a-service, billed to the retailer at 0.2–0.5% of basket value or a flat per-cart-per-month fee. (Shrink is only ~1.2% of sales in APAC, so the once-considered 1% priced at ~100% of the value created.)

---

## 11. Open questions gating construction

Each can kill or reshape the design cheaply. Bench rig before cart; per-sensor error curves before fusion. Phase numbering and gate criteria are in `BUILD_PLAN.md`.

1. **The light curtain — now the experiment that gates everything.** Two-plane beam array on a cardboard frame; drop **50 items** through it. Can you count reliably? Get direction right every time? Recover a usable profile? Tell a hand from an item? **~₹1,000, one weekend.** This also settles the two **[PROVISIONAL]** geometry values in §3.2.
2. **Δmass resolution.** Differential over the §4.2 windows, cart still and rolling. **Gate: does it resolve ~5 g on a 30 kg basket?** If far worse, revisit the two-scale fallback.
3. **Catalog mass separability.** ~100 real products weighed **as sold, packaging included**, deliberately including same-brand-multiple-sizes and competing-brands-at-equal-declared-weight. Collisions at ±2 / ±5 / ±10 g. **~₹500, one afternoon.** **[RESEARCH]** The risk: Indian FMCG uses standardised pack sizes (50/100/200/500 g, 1 kg) so declared weights cluster hard — the saving detail is that **declared net weight clusters, measured gross weight does not** (different packaging mass, fill tolerance, wrapper). *This matters far less than under the gate-tray design: with barcode-first verification the question shifts from "how many SKUs collide?" to the much easier "can we distinguish the scanned item's mass from a plausible substitution?"*
4. **Impulse separability.** 20 items across rigid / soft / granular. Is the class cleanly separable from the settling curve?
5. **Red-team it.** Pay people to steal from a mock-up and let them get creative. Behavioural datasets will not tell you what real attackers do; adversaries will.

### 11.1 Two costs named plainly

**This is a hardware plus retail-operations business.** Mechanical design, a load-cell subsystem, an embedded controller sampling at kHz, calibration procedures, drift management, fabrication, pilots, long sales cycles, capital. A different discipline from the Python pipeline — worth knowing before the first weld, not after.

**You need a mass for every SKU.** **[RESEARCH]** GS1/GDSN net-weight availability for Indian FMCG is **unconfirmed**, so plan to weigh the catalog in-house: two people, a bench scale, a few days for 1000 items, and an ongoing process as the catalog changes. It is boring, and the entire architecture rests on it.

### 11.2 Still owed

A **photo/reference-capture SOP** for maximum accuracy and for handling similar packaging between different products. Requested twice, never written. It lands with `build_db.py`.

---

## 12. Provenance

Sections 1–8 and 10–11 derive from the ideation sessions of 22–23 August 2026, conducted under an explicit *"ideate only, no changing code"* constraint, recovered from session transcripts on 24 August 2026 and recorded with per-claim status tags in `CONTEXT_SNAPSHOT.md`. Section 9 derives from the current repository and from plan `logical-snacking-hollerith.md`, all five parts of which are implemented and green.

Research citations were obtained via WebFetch against Wikipedia and the arXiv API. **WebSearch was unavailable on that endpoint** — stated so nobody assumes broader coverage than was actually obtained. Key sources: Amazon Go / Just Walk Out (Wikipedia); retail shrinkage figures (Wikipedia); barcode reader scan rates and omnidirectional patterns (Wikipedia); IEC 61496 light-curtain class and 14 mm detection (industrial safety literature); grocery retrieval benchmark ICPR 2026 / arXiv 2605.18029; RFID material identification arXiv 2504.17898; barcode detection arXiv 1906.06281, 1807.11886, 2302.02396, 2003.09316.

Three values were pinned **[PROVISIONAL]** in this document where the transcripts stated two figures at different times — beam pitch (10 mm), plane separation (40 mm), and the mass window (300 ms). They are marked at each point of use and are settled by experiment 1 and 2 of §11. Every other estimate is tagged **[ESTIMATE]** and has not been verified on hardware; the load-bearing ones are the ±3–5 g differential figure and the curtain reliability table.
