# NXTCart-Cam — Context Snapshot

**Recovered:** 2026-08-24 · **Source:** five session transcripts (2026-08-22 → 2026-08-23) + `.claude/plans/logical-snacking-hollerith.md`

This file exists because the architecture work of 22–23 Aug 2026 was conducted under a standing
*"ideation only, no code"* constraint, and the session that was to write it up died on repeated
auth/API errors before producing anything. **None of Section 1 or 2 below is implemented.** The
repository is still the single-camera CV system described in Section 6.

### Status legend

| tag | meaning |
|---|---|
| **[DECIDED]** | Settled by the user, or by me and not contested. Treat as final. |
| **[MEASURED]** | A number produced by running something on this machine. |
| **[RESEARCH]** | From a fetched source. Provenance given. |
| **[ESTIMATE]** | Derived from geometry/physics, never verified. Verify before building. |
| **[REJECTED]** | Considered and dropped. Reason recorded so it isn't relitigated. |
| **[UNRESOLVED]** | Two different values were stated at different times. Must be pinned before fabrication. |

---

## 1. The finalized physical architecture

### 1.0 The governing reframe — read this before the sensors

**[DECIDED]** The cart is not a recognition system. It is an **audit system**. The question is
not *"what is this object?"* — a question with an irreducible error rate — but **"does the cart
balance?"**

Double-entry bookkeeping, two independent books:

- **Book A — the bill.** Items the system believes it has, each with a catalog mass.
- **Book B — physics.** Mass actually sitting in the basket, measured continuously.

> **The conservation invariant:** `measured basket mass == tare + Σ(expected mass of every line on the bill)`, at all times, within tolerance. Violated beyond tolerance for more than a few seconds → **UNEXPLAINED MASS → hard stop.**

Why this is the security primitive and not a fallback: every theft trick ever invented — known or
not yet invented — has the same signature, **goods that physically exist are not on the bill**.
That is a mass discrepancy by definition, so you never have to anticipate the trick. Path A
(identification) can fail *entirely* and the invariant still catches the theft.

**[DECIDED] Structural consequence, non-negotiable:** the weighed volume must be the *only*
volume. One closed basket, **one monitored aperture**. No under-basket rack, no child seat, no
side pockets — or weigh them separately, or physically seal them for the session. Open the side
of the basket and the guarantee is gone. This is a mechanical requirement, not a software
preference.

**[DECIDED] Channel discipline — the cheap unspoofable channel constrains the expensive spoofable one, never the reverse.**

| channel | genuinely good at | must never be asked to |
|---|---|---|
| Load cells | Proving *that* something happened and *how much*. Immune to occlusion, lighting, packaging, orientation. | Say *what* it is |
| Camera | Narrowing SKUs to a handful; watching the act | Make the final call between lookalikes |
| Barcode | Absolute identity, when it reads | Prove anything actually entered the cart |
| Light curtain | Counting, direction, coarse size | Identify anything |

Concretely: the barcode is **checked against physics, not trusted**. Barcode says SKU-X, SKU-X
weighs 200 g, scale measured 400 g → **reject the barcode**. That single inversion makes
ticket-switching structurally detectable instead of invisible.

### 1.1 Rim barcode — the base layer

**[DECIDED]** Barcode is the base. It is **presented at the rim to a fixed reader**, not read in
flight. Putting the barcode first converts the problem from *identification* to *verification*:
instead of "which of 1000+ SKUs is this?" the system asks "is this the 342 g rigid cylinder we
were told to expect — yes or no?" The lookalike SKU never enters the comparison. The hardest
accuracy problem is not solved, it is **deleted**.

**[REJECTED] Reading the barcode off an item in free fall.** User's call, verbatim: *"i dont
think scanning free fall objects is logical or reliabele we can stick to the curtain and row
sensor with AI as decision maker."*

The research behind that decision, kept because it justifies the rejection:

| finding | value | source |
|---|---|---|
| Laser scan line rate | **200–1200 lines/sec** | Wikipedia, barcode reader |
| Scan pattern | starburst / Lissajous, many angles, so one line crosses the code at any orientation | same |
| Tolerance | reads "poorly printed, wrinkled, or even torn" codes | same |
| Resolution | commonly 13 mil (0.33 mm), some to 3 mil | same |
| Not covered by that source | **no tunnel scanners, never uses "bioptic", no motion-tolerance figures** | same |
| Motion/blur/free-fall decoding across 30 arXiv results | **no paper addresses it** | arXiv API |

Closest prior art found: `1906.06281` Universal Barcode Detector via semantic segmentation
(0.995 detection, real-time on CPU, "in the wild"); `1807.11886` BarcodeNet / Barcode-30k
(95.36% mIoU, handles small scale, half-occlusion, deformation, illumination); `2302.02396`
OAcode (screens, 100% detection / 99.5% demodulation to 25°); `2003.09316` notes printed
barcodes are "very much environmentally dependent" so detectors transfer poorly.

**[ESTIMATE]** Physics, recorded so nobody re-derives it: a ~10 cm drop ≈ **1.4 m/s**, so ~**140 ms**
inside a 200 mm ring; at 1200 lines/s that's ~**170 attempts per reader**, and 4–5 readers give
**500+ shots** at the code. Motion blur at 1/2000 s is ~0.7 mm. **Time in zone was never the
blocker — orientation was.** Every industrial system that works constrains the motion (conveyor,
belt, deliberate swipe). Nobody lets the item tumble; it isn't that free fall was tried and
failed, it's that everyone who solved this chose not to attempt it.

**[DECIDED] The adopted alternative — chain of custody.** You don't need to read the code during
entry; you need to prove *the item scanned is the item that entered*. Scan at the rim (the
shopper naturally holds it still for a moment), then the camera keeps that item under
**continuous observation** for ~1 second until it crosses the beams. A swap **requires** a
discontinuity — a gap in observation, a second object appearing, or an appearance change — and
any of those is trivially detectable at 60 fps.

This is a one-second continuity check on a single object: no open-set matching, no lookalike
ranking, no occlusion handling, no reacquisition. **This is the one place the existing
`identity_tracker.py` machinery survives**, with a radically easier job, and it is allowed to
fail loudly — failure means "please rescan," not "lose the item forever."

**Optional upgrade, not required:** if a ring reader *also* reads a code and it disagrees with
the rim scan, the attack is caught red-handed with hard evidence. A short chute or sloped tube
would settle orientation and lengthen time in zone — a mechanical fix to a sensing problem, the
cheapest kind — but the chain-of-custody path makes it unnecessary.

### 1.2 Two-plane IR light curtain — the passive layer

**[DECIDED]** Two parallel planes of infrared beams across the cart's mouth, **sampled at ~1 kHz**,
entirely passive, a few hundred rupees of LEDs and phototransistors. The shopper never knows it
exists. It is a beam break, not an image — immune to lighting, shadows, packaging gloss, colour,
and occlusion, i.e. everything that breaks the current pipeline.

What each row buys:

- **One beam** → something crossed.
- **A row (~16 pairs)** → *which* beams are blocked. Beams 5–7 = narrow object; 2–14 = wide;
  3–5 **and** 9–11 with a clear gap = **two separate objects.** Counting discrete objects is
  what cameras are worst at and what a beam row is best at.
- **Two rows** → **direction, free.** Upper breaks first = **IN**; lower first = **OUT**. Same
  principle as a doorway people-counter or turnstile. Sequence, not inference — no motion
  estimation.
- **Two rows + 1 kHz** → speed, and speed turns time into distance, so the blocked-beam pattern
  over time **reconstructs a silhouette**. Same trick as a flatbed scanner or airport baggage
  scanner, except the sensor line stays still and the object moves past it.
- **Silhouette + mass** → **density**. A 340 g chips bag ≈ 0.1 g/cm³; a 340 g pickle jar ≈
  1.2 g/cm³. Separates things mass alone never will, at no extra cost.

**Hand-vs-item discrimination is topological:** a hand entering stays connected to the rim (the
arm) and never fully clears; an item enters and fully clears. Trivial for a curtain, genuinely
hard for a camera.

**It cannot be blinded silently.** Covering a camera produces a black frame; blocking a beam
**is** an event. Sensor health is itself a sensor.

| parameter | value | status |
|---|---|---|
| Sampling rate | ~1 kHz | **[DECIDED]** — consistent across every statement |
| Beam pairs across the gap | ~16 | **[ESTIMATE]** |
| Beam pitch within a plane | **10 mm or 20 mm** | **[UNRESOLVED]** — 20 mm stated in the ring proposal; 10 mm used in every reliability estimate. Tighten to 5 mm / 2.5 mm is possible (more emitters, more wiring, eventual beam interference). |
| Plane separation | **30 mm or 40 mm** | **[UNRESOLVED]** — 30 mm in the direction-reliability estimate; **40 mm** in the four-part removal fix statement, which is the later and more authoritative source. |
| Silhouette resolution | ~10 mm across (= beam pitch) × ~1.5 mm along the fall | **[ESTIMATE]** |
| Transit time through the ring | ~140 ms (200 mm ring @ 1.4 m/s); stated loosely elsewhere as 200–400 ms | **[UNRESOLVED]**, minor |
| Direction reliability | ~20 ms between plane breaks → ~20 samples of separation at 1 kHz → "essentially never wrong" | **[ESTIMATE]** |
| Ambient-light rejection | **Required.** Pulse the LEDs at a known frequency, receiver listens only for that frequency. Sunlight/ambient IR would swamp a naive design. | **[DECIDED]** |

**[RESEARCH] Prior art — this is a boring, proven sensor pointed at a new problem.** Light
curtains are mature industrial equipment used as machine safety guards, certified under
**IEC 61496**, specified to detect a **14 mm finger** reliably. When a sensor is trusted to
prevent amputations, basic detection reliability is not the risk. An industrial product already
does exactly what's proposed — counting and profiling objects passing on a conveyor — sold as a
**"measuring light grid."** Search terms: *"safety light curtain how it works"*, *"light curtain
working principle animation"*, *"measuring light grid object dimension conveyor"*. Vendors with
thorough technical video: SICK, Keyence, Banner Engineering, Omron, Pilz.

**[DECIDED] Hard ceiling — do not chase 3D.** One row gives a **flat silhouette**, exactly like
a torch shadow on a wall. Not 3D. Two rows crossed at 90° give front + side views (the sensible
upgrade, enough to estimate volume); four or more angles start reconstructing a cross-section,
which is the CT-scanning principle and is heavy. But **beams can never see colour, print,
texture, concavity, or a dent.** It is a shadow, permanently.

And chasing resolution buys nothing on the case that actually matters: blue and green Gatorade
are **geometrically identical**. A perfect 0.1 mm scanner would correctly report the same object,
because apart from the label they *are* the same object. Push each channel only until it's good
enough for its own job, then stop. The curtain's job is **count, direction, coarse size class**
— it is already good enough at that.

**[DECIDED] Operational cost to design for: dirt.** Grocery environments are dusty and sticky,
and grime on an emitter reads as a blocked beam. This is the genuine operational headache — it
needs recessed or wiped optics plus a self-check that reports dirty beams.

### 1.3 Load cells + IMU — and the invariants that govern them

**[DECIDED] The invariant that decides the whole design: load-cell error is specified as a
percentage of full-scale output (FSO), not of the thing being weighed.**

| configuration | absolute error | status |
|---|---|---|
| 30 kg basket, cheap cells @ 0.05% FSO | **±15 g** — a 10 g packet is below the noise floor | **[RESEARCH]** |
| Same cells, 3 kg capacity | **±1.5 g** | **[RESEARCH]** |

**The critical distinction, and the correction that killed the gate tray:** %FSO governs
**absolute** accuracy — linearity, hysteresis, temperature drift, creep, zero balance. It does
**not** govern **short-term repeatability.**

> **[ESTIMATE] Measure a *delta* over a ~300 ms window with the cart stationary and all of that cancels**, because both readings share the same thermal and creep state. What's left is short-term noise only. With a decent 24-bit converter and averaging: **±3–5 g on a 30 kg basket.**

That figure is the reason no weighing tray is needed. And because verification (not
identification) is the job, **±5 g is sufficient** — you no longer need to resolve 342 g out of a
catalog, only to confirm ~342 g arrived and not 1200 g.

**The curtain is what makes the differential clean:** it says *exactly* when the object crossed,
so the before- and after-windows are tightly bracketed around a known, sub-millisecond trigger.
Differential measurement done properly needs a trigger, and the curtain is one.

**[DECIDED] Read all four cells independently — never wire them in parallel.** Paralleling
**averages** the signals away. Four independent readings give total mass **and** the 2D **centre
of mass**, i.e. *where* mass landed. That allows cross-checking "camera saw something land at the
left rear" against "mass landed at the left rear" — two sensors auditing each other with neither
needing to recognise anything. Mass landing where the camera saw nothing is unexplained.

**[DECIDED] Keep the ringing everyone else filters out.** Abrupt load steps excite the cell's
natural frequency. Sample at **500–1000 Hz** and retain the transient: how fast the oscillation
damps distinguishes a **rigid** can from a **soft** pouch from **granular** rice or dal that
sloshes. A free material channel from hardware already present. It won't name a SKU, but it
cross-checks the vision class and splits same-mass items.

**[DECIDED] ADC selection follows directly from that.** HX711 is the default choice but runs at
**10/80 SPS** — adequate for the mass *step*, far too slow for the impulse signature. For the
material channel use an **ADS1220 (2 kSPS)** or **ADS1256 (30 kSPS)** class part. Start with
HX711 to prove the step measurement; upgrade only if pruning demands it.

**[DECIDED] IMU gates the scale.** Rolling / stationary / tilted / lifted. Only trust mass when
stationary — cheap, and it also catches tilting and lifting as tampering.

**[RESEARCH] Drift:** recalibration every 18 months–2 years. Error budget components: combined
error, non-linearity, hysteresis, repeatability, zero balance, temperature. Low-end cells have
nonlinearity.

### 1.4 Edge GBT model — the decision layer

**[DECIDED]** AI goes in the **decision layer**, not the camera layer. Placement matters more
than the model.

The per-event evidence vector is ~**20 numbers**: Δmass, expected mass, mass residual, curtain
object count, silhouette width, silhouette height, density, expected density, colour distance,
vision score, barcode present, barcode agrees, cart motion state, and so on. In → verdict +
confidence out.

**That is a tabular problem with 20 features. It does not need deep learning.** Gradient-boosted
trees handle it in microseconds, need very little data, and — critically — **report which feature
drove the decision.** Two advantages over hand-written rules:

- **They learn interactions.** "An 8 g mass error is fine on a 2 kg bag of atta but very
  suspicious on a 40 g biscuit pack" is something rules capture badly and trees capture
  naturally.
- **Every audit becomes a labelled training example**, generated precisely on the cases the
  system found hardest. Accuracy improves fastest where it is weakest.

This is what replaces the hand-tuned thresholds — `0.72`, `0.80`, `0.55`, `EXIT_CONFIRM_FRAMES = 3`
— that motivated the whole redesign. Hand-tuning those *is* manual construction of a decision
boundary, and it is exactly the "too many variables" complaint.

> **[DECIDED] THE HARD BOUNDARY: never let a learned model own the conservation invariant.**
> "Unexplained mass in the basket → stop" stays hand-coded and non-negotiable. A learned model
> drifts, can be probed and gamed, and offers no guarantees. **Rules own the extremes — clear
> pass and clear fail. The model owns only the grey zone.** That way the model can be wrong
> without the system being unsafe.

**[DECIDED] Sequencing: rules first, model second — not the reverse.** Ship with conservative
hand rules, because there is no data on day one. Collect audit labels. Introduce the model after
a few thousand real events.

**[DECIDED] Sparse VLM escalation, ~2% of events.** When the cheap stack is genuinely stuck,
send three frames to a vision-language model: *"Is this bottle blue or green Gatorade?"*
Sub-second, fractions of a paisa. **[RESEARCH]** A 2026 retail theft-detection paper gated an
expensive VLM behind cheap always-on detectors and cut model calls **240×** versus per-frame
invocation. Cheap deterministic stack handles 98%; the expensive model handles the 2% that matter.

**[DECIDED] A product requirement the model choice is downstream of.** In India, wrongly
accusing a paying customer at the exit is far worse than losing the item — socially explosive and
capable of damaging a store permanently. **False accusation is a more expensive failure than
theft.** Therefore flags must be **explainable**: "the weight was 340 g more than the item you
scanned" is a conversation you can have; "the model returned 0.31" is not. And the default
response to a flag is **quiet resolution, never confrontation.** Interpretable trees over black
boxes, for business reasons as much as technical ones.

---

## 2. The four-part removal fix

**[DECIDED]** This is the part that changes most from the current code, and the reason is a
framing error, not a tuning failure.

> The old design inferred removal from **absence**: *"I can't see it any more, so maybe it left."*
> That is **structurally unfixable.** Absence has two causes — it left, or it's hidden — and no
> amount of threshold tuning separates them. Every removal bug chased in the CV build was a
> symptom of that one wrong question.

**The new design never asks whether an item is still there.** Four parts:

**1. Direction is a physical event, not an inference.**
Two beam planes in the cart mouth, **~40 mm apart**. Break upper-then-lower → going **IN**.
Lower-then-upper → going **OUT**. Same principle as a doorway people-counter. The event fires on
the crossing and is **finished** — nothing is watched before or after. Removal stops being a
special case: same sensor, same event, opposite sign.

**2. Mass says how much left.**
2,340 g → 2,105 g means **235 g left**. A measurement, not a guess. Event-triggered differential
weighing, bracketed by the curtain's sub-millisecond trigger (§1.3).

**3. Identity comes from the bill — which is why removal is *easier* than insertion.**
On insertion you ask "which of 1000+ SKUs is this?" — open-set, and exactly what failed. On
removal you ask "which of the items on **this shopper's own bill** weighs 235 g?" **Closed set,
n ≈ 15–20.** The bill is a whitelist that shrinks the search space ~**70×**. Ties break in order:
**silhouette → density → colour.** If it still cannot decide, the screen asks — rare, and honest.

**4. Ambiguity always resolves against the shopper's financial advantage.**
If two bill items still match, **credit back the cheaper one.** This is not politeness — it is
what closes the only real removal attack: buy a ₹400 item and a ₹40 item that both weigh 300 g,
remove the cheap one, hope to be credited the expensive one. **Crediting the cheaper candidate
makes that attack net zero.** Asymmetry of complaint reinforces it: an under-credited shopper
complains and is fixed at the counter in 20 seconds; an over-credited one says nothing and walks
out with free goods.

**The shopper does nothing** — no rescan, no button, no "removal mode."

### What this retires

The occlusion machinery exists only because the old architecture had to watch objects forever.
In an event-gated design that entire problem statement disappears: `OCCLUDED`, `LOST`,
`REACQUIRE`, presence checks, visibility gating, merge guards, exit-progress accounting. **The
hardest code in the repo becomes dead code.** The exception is §1.1's chain-of-custody continuity
check, which is the one surviving use of the tracker.

---

## 3. The escalation ladder and the per-event checks

**[DECIDED] The ladder, in order.** Each rung only has to catch what the rungs above it miss —
which is why none of them individually needs to be excellent.

| # | rung | catches |
|---|---|---|
| 1 | **Barcode read at the rim** | If it reads, you're done |
| 2 | **Weight** | Wrong size, wrong quantity |
| 3 | **Curtain count + direction** | Extra objects; insertion vs removal |
| 4 | **Silhouette + density** | Wrong product category |
| 5 | **Colour** | The Gatorade case |
| 6 | **Label text** | Same-colour variants. Weakest link, last resort |

**The stacking principle that makes this work:** *the cases that defeat shape and weight are
usually the ones colour solves instantly; the cases that defeat colour are usually the ones shape
or weight solve instantly.* It isn't that each channel is strong — it's that **their blind spots
don't overlap.**

**Per-crossing checks.** The curtain is the clock: **nothing is decided without a curtain event**,
which alone eliminates every phantom detection, shadow flicker and hand-waving artefact in the
current build, because hands don't fully cross and weigh nothing.

| # | check | fails when |
|---|---|---|
| 1 | Direction — IN or OUT | — |
| 2 | Object count from the shadow pattern | Two items dropped when one was scanned |
| 3 | Cross-sectional profile ≈ expected for the scanned SKU | Different-shaped item substituted |
| 4 | Δmass ≈ expected mass for the scanned SKU | Wrong item, extra item, or multiple |
| 5 | Density (mass ÷ curtain volume) ≈ expected | Same-mass, different-material substitution |
| 6 | Camera 1-vs-1 match against the scanned SKU | Visually different item |
| 7 | A barcode read exists and is unconsumed | Nothing scanned at all |

All seven agree → **grade A, silent pass.** One disagrees → flag the line. Curtain fires with no
barcode, or mass moves with no curtain event → **hard stop.** And underneath all of it,
continuously and independently, the conservation invariant of §1.0.

**[DECIDED] Provenance grades replace confidence scores** — how a line got onto the bill, not how
confident a model felt:

| grade | evidence | treatment |
|---|---|---|
| **A** | Barcode + mass + vision all agree | Walk out |
| **B** | Mass + vision agree, no barcode (loose produce, unbarcoded goods) | Priced, low risk |
| **C** | One channel only, or marginal agreement | Priced, flagged |
| **U** | Mass with no identity, or identity with no mass | **Hard stop** |

Two consequences that matter more than they look. **Targeted partial audit:** a U-grade line
means staff verify *that one item*, not recount the basket — a 10-second intervention, which is
what makes the staffing arithmetic work at Indian labour ratios. **The failures become the
training set:** every audit produces a human-labelled ground-truth pair on precisely the cases
the system found hardest. Most systems throw their hard cases away; this one harvests them.

### Attack coverage

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

The last three rows are the attacks that beat **every camera system shipping today, including
Amazon's**, and conservation is the only thing that catches them. That is why it is the floor and
not a fallback — and why the closed-volume/one-aperture constraint of §1.0 is structural.

**[DECIDED] Counting policy — never divide.** The user proposed inferring quantity as
weight ÷ unit weight. **That creates a theft vector cheaper than the one it solves:** scan one 5 g
sachet at ₹2, drop one 50 g item worth ₹200, system computes 50 ÷ 5 = 10 and bills **₹20 for a
₹200 item.** The division is only valid if you already know everything that entered is the same
item — which is precisely the assumption an attacker breaks. So quantity is **counted by the
curtain, not divided**:

| weight says | curtain counts | verdict |
|---|---|---|
| 1× | 1 object | ✅ Normal, silent pass |
| N× | **N objects** | ✅ Genuinely N singles. Bill N, confirm on screen |
| N× | **1 object** | ⚠️ A multipack, or the wrong item. **Ask for the pack's barcode** |
| N× | fewer than N | ⚠️ Ambiguous. Ask |
| 1× | 2+ objects | ⚠️ Something extra came in. Flag |

Row three is also **commercially more correct**: a sealed pack of 4 soaps is its own SKU at its
own price, usually *cheaper* than four singles, so billing 4 singles would overcharge. Store a
**per-SKU counting policy** in the catalog — for loose sachets that clump, weight counts better;
for anything bulky, the curtain counts better; require agreement wherever both are reliable.

---

## 4. Rejected approaches, and why

| approach | status | reason |
|---|---|---|
| **Gate tray / weighing plate at the cart mouth** | **[REJECTED]** by the user | Too slow, too variable, and it **left removal entirely unaddressed.** The user's constraint: one more verification layer is acceptable *only if the shopper does not interact with it* — *"we are here to make the user at ease and not create one hassle by removing another."* |
| **Two-scale hierarchy** (precision 3 kg gate plate + coarse 30 kg basket scale auditing each other) | **[REJECTED]**, superseded | Fell with the tray. Was motivated by the %FSO wall and the ±1 g identification target; the ±3–5 g differential figure (§1.3) plus barcode-first verification removed the need. Worth remembering as the fallback if differential resolution measures far worse than estimated. |
| **Barcode reading in free fall** | **[REJECTED]** by the user | See §1.1. Orientation, not time in zone. No product or paper does it; every working system constrains the motion. |
| **Chasing a detailed 3D reconstruction from the curtain** | **[REJECTED]** | Blue vs green Gatorade are geometrically identical — a perfect scanner correctly reports the same object. Shape is the wrong channel for that problem. Two rows crossed at 90° is the sensible ceiling. |
| **Quantity by weight ÷ unit weight** | **[REJECTED]** | Creates a cheaper theft vector than it closes. See §3. |
| **Vision-first architecture** | **[REJECTED]**, empirically | See §5 — Amazon proved the ceiling with unlimited budget. |
| **Behavioural / CCTV theft detection as a security mechanism** | **[REJECTED]** | Best zero-shot result found: 89.5% precision but **59.3% recall**. A system that misses 4 in 10 thefts is not a loss-prevention product. |
| **Late fusion** (run all three channels, average the confidences) | **[REJECTED]** | Inherits every weakness. Replaced by channel discipline (§1.0) and the escalation ladder (§3). |
| **RFID everywhere** / **RFID never** | **[REJECTED]** both | **Tiered RFID** is the economically literate answer: tags run $0.04–1.00 in volume — fatal on a ₹10 packet, trivial on a ₹900 razor pack. Shrink value concentrates in a small SKU set (blades, spirits, infant formula, cosmetics, electronics accessories). Tag only that tier. Bulk reading also "lacks sufficient precision for inventory control." |
| **1% of order value as the revenue model** | **[REJECTED]**, repriced | Shrink is ~1.2% of sales in Asia Pacific (~1.5% US), ~78% of it theft. Charging 1% prices at ≈100% of the value created; the retailer nets nothing. Use **0.2–0.5% of basket value** or a flat per-cart-per-month fee (easier for a CFO than revenue share). **Do not charge the shopper an unlock fee** — trolleys have been free forever, and an unused cart earns nothing and generates no training data. **Don't sell hardware** — hardware-as-a-service. Wedge: price on outcomes (measure shrink 60 days, deploy, measure again, take a share of the reduction). Market: large-format organized retail, not kirana. |

---

## 5. Research findings that justify the architecture

**[RESEARCH]** All via WebFetch against Wikipedia and the arXiv API. **WebSearch was unavailable
on that endpoint** (`tool type 'web_search_20250305' is not supported for this model`) — stated
here so nobody assumes broader coverage than was actually obtained.

- **Amazon Go / Just Walk Out.** Overhead cameras **plus** shelf weight sensors — the densest
  retail sensing ever deployed. Broke above ~20 shoppers; confused by children moving items and
  by shoppers of similar body habitus. **April 4 2024: revealed as "powered by 1,000 Indian
  workers"** manually reviewing transactions. Amazon then swapped to Dash Carts. *That is the
  ceiling of the vision-first approach, reached by a company with unlimited budget.*
- **Shrinkage.** US ~1.52%, Europe 1.27%, Asia Pacific 1.20%. Theft = 78.3% of shrinkage
  (employee 42.7%, shoplifting 35.6%). 2008 US figure $36.3B.
- **Grocery retrieval, ICPR 2026 (arXiv 2605.18029).** 190 VLMs: **94.5% Recall@5 but a 17.5%
  drop at Recall@1** — *"embeddings cluster categories yet mis-rank lookalike SKUs."* This is the
  similar-packaging problem confirmed unsolved at the frontier, **and it dictates the pipeline
  order: mass prunes, vision ranks.**
- **The gap that is the opening.** Across every arXiv search run, four of five checkout papers
  were vision-only, and the explicit finding was: *"nothing in this result set uses load cells,
  shelf weight sensors, or physical conservation constraints for basket verification."* Nobody is
  doing rigorous physical reconciliation at the cart.
- **RFID material ID (arXiv 2504.17898).** RSSI + phase classifies 7 container types at 89% from
  1 s samples, motivated by concealed items in bags.
- **GDSN.** No attribute detail available from the source; **net-weight availability unconfirmed.**
  Assume the catalog must be weighed by hand.

**[MEASURED] Current-build performance facts — do not re-derive:**

| item | measured |
|---|---|
| `extract_embedding`, TFLite (no delegates, 1 thread) | **1618.87 ms** — the only non-crashing config |
| TFLite 4 threads / XNNPACK 1 / XNNPACK 4 | all segfault (exit 139) |
| `extract_embedding`, ONNX via `cv2.dnn` | **8.28 ms**, later **12.77 ms** |
| `process()` median (real detector + real ONNX, 5 candidates) | **19.77 ms → 50.6 fps** |
| `process()` p95 / max | 23.50 ms / 33.40 ms → 29.9 fps worst frame |
| Recognitions over 120 frames (cap 1/frame) | 118 — budget held |
| `detector.detect` | 7.96–11.98 ms |
| `match()` | 0.03 ms |
| draw + panel + hstack | 1.03 ms |
| `cap.read()` DSHOW | 34.1 ms |
| Camera open, DSHOW vs MSMF | **130 ms vs 2923 ms** |
| Leave-one-out top-1, TFLite quant / ONNX float | **19/20 both** |
| Grid search @ `SCORE_THRESHOLD=0.72`, `_MARGIN_THRESHOLD=0.03` | 17/20 true accepts, **0 wrong**, **0/20 unknowns falsely locked** |
| Unknown-object similarity ceiling (TFLite) | **0.632** — above the old `REACQUIRE_SIMILARITY = 0.60`, which is why reacquires were firing at sim 0.638/0.652/0.682 |

---

## 6. Current implementation state

**The repository implements none of Sections 1–3.** It is the single-camera CV system: MOG2 +
watershed detection, MobileNetV2 → 1280-D embeddings via ONNX/`cv2.dnn`, cosine similarity,
3-of-5 multi-frame voting, and the persistent-identity tracker documented in
`IDENTITY_TRACKING.md`. No barcode, no light curtain, no load cell, no IMU, no GBT — no sensor
I/O of any kind. The only input is `CAMERA_INDEX = 0`.

**Complete and verified (plan `logical-snacking-hollerith.md`, all 5 parts):** ONNX backend swap
(250× on the embedding call); per-frame inference budgets + settled-only verification gate;
threaded newest-frame-only `FrameGrabber`; the ROI presence check and vacated-spot removal path;
UTF-8 stdout fix in the harness. All 8 scripted runs green, **zero false cart changes** in every
mode. `ml/camera.py` and `scripts/` were untracked at the time of the snapshot; the identity
tracking work has since been committed (`3380990`).

**Honest caveat carried forward:** the synthetic harness registers **zero** occurrences of
`-> LOST`, so it proves no regression but validates none of the presence logic. Part 4 was
verified separately with a documented before/after on the identical scenario — the old path
reproduced the user's log verbatim including the number 18
(`OCCLUDED -> LOST (unseen 18 frames — STILL counted in cart)`) and then stuck at `{'soap': 1}`
forever; the new path stays `PRESENT`, then `OCCLUDED -> REMOVED (frame 485; spot vacated: ROI
matched learned background for 5 frames)` with an empty cart. **None of it has met a real webcam.**

### Do not confuse these two removal mechanisms

The current code has a **four-guard removal path** in `ml/config.py:395-450`
(`MOVING_MIN_DISPLACEMENT = 7`, `EXIT_CONFIRM_FRAMES = 3`, `EXIT_BOUNDARY_MARGIN = 45`;
`PRESENCE_ITEM_MATCH = 0.55`, `PRESENCE_BG_MATCH = 0.60`, `PRESENCE_VACATED_FRAMES = 5`;
`EXIT_EVIDENCE_GRACE_FRAMES = 2`; `EXIT_CLIP_MARGIN = 8`). **That is not the four-part removal fix
of Section 2.** It is the CV-era mitigation of the same problem — and Section 2 exists precisely
because that whole approach asks the unfixable question ("is it still there?"). Both are recorded
here deliberately; do not merge them.

### Fate of the existing code under the new architecture

| file | fate |
|---|---|
| `ml/embedding_extractor.py` | **Survives**, more valuable. Later: fine-tune on own SKUs |
| `ml/matcher.py` | **Survives**, simpler — ranks within a candidate set instead of searching all |
| `build_db.py` + `references/` | **Survives.** This is where the photo SOP lands |
| `ml/camera.py` | **Survives** |
| `test_scripted.py` | **Survives and grows** into the fusion + adversarial harness |
| `ml/cart_state.py` | **Grows** into the double-entry ledger |
| `ml/detector.py` | Mostly retired — static differencing in controlled lighting replaces MOG2 |
| `ml/identity_tracker.py`, `ml/track.py` | **Largely deleted** — except the chain-of-custody continuity check (§1.1) |

**Still owed to the user (deferred, not forgotten):** a **photo/reference-capture SOP** for
maximum accuracy and for handling similar packaging between different products. Requested twice;
never written. It lands with `build_db.py`.

---

## 7. Residual holes — stated plainly

**[DECIDED]** There is no foolproof. What is achievable, and what loss prevention actually needs:

> **No theft can happen silently.** It may be flagged rather than physically prevented, but nothing passes undetected.

The remaining gaps:

- **Items under ~5 g** fall below the mass noise floor. Curtain and camera still see them; theft
  value is negligible.
- **Two items dropped in perfect overlap**, combined mass and profile close to the scanned SKU.
  Extremely hard to execute, and the multi-beam shadow pattern makes true overlap detectable —
  two touching objects rarely produce one clean silhouette. When counting *does* fail, it fails
  loudly: twice the expected width **and** twice the expected weight both flag.
- **Same shape, same weight, same colour, different price** — "anti-dandruff" vs "regular"
  shampoo in a near-identical bottle. Nothing physical separates them; you must **read the label**.
  In fixed lighting at 60 fps you'll catch a legible frame, and you only need to verify a
  hypothesis ("does this label contain the word we expect?"), not perform general OCR. **This is
  the weakest link and where real-world failures will concentrate.**
- **Sensor sabotage** — detectable, not preventable. Becomes a staff alert, not a silent loss.
- **Staff collusion** — no sensor architecture fixes this. Needs the event log to be
  **append-only and auditable** so overrides are traceable.

**No system accuracy figure should be quoted before the red-team test.** An honest one can only
come from people actively trying to beat it; anyone quoting a percentage earlier is guessing.

---

## 8. Gating experiments, in order

**[DECIDED]** Each can kill the design cheaply. The bench rig comes before the cart; per-sensor
error curves before fusion.

1. **The light curtain — now the experiment that gates everything.** Build a two-plane beam array
   on a cardboard frame and drop **50 items** through it. Can you count them reliably? Get
   direction right every time? Recover a usable profile? Tell a hand from an item?
   **~₹1,000, one weekend.**
2. **Δmass resolution.** Differential over a ~300–400 ms window, cart still and rolling.
   **Gate: does it resolve ~5 g on a 30 kg basket?** If it's far worse, revisit the two-scale
   fallback in §4.
3. **Catalog mass separability.** ~100 real products from a kirana or supermarket, weighed **as
   sold, packaging included**, deliberately including same-brand-multiple-sizes and
   competing-brands-at-equal-declared-weight. Compute collisions at ±2 g / ±5 g / ±10 g.
   **~₹500, one afternoon.**
   **[RESEARCH] The risk this tests:** Indian FMCG uses standardised pack sizes (50/100/200/500 g,
   1 kg), so declared weights cluster hard. **The saving detail: declared net weight clusters,
   measured gross weight does not** — different packaging mass, fill tolerance, wrapper. That's
   empirical, not arguable. *Note this experiment matters far less now than under the gate-tray
   design: with barcode-first verification, mass no longer has to identify anything. The question
   shifts from "how many SKUs collide?" to the much easier "can we distinguish the scanned item's
   mass from a plausible substitution?"*
4. **Impulse separability.** 20 items across rigid / soft / granular. Is the class cleanly
   separable from the settling curve?
5. **Red-team it.** Pay people to steal from a mock-up and let them get creative. Behavioural
   datasets will not tell you what real attackers do; adversaries will. Every successful attack
   becomes a permanent regression test.

**Two costs named plainly.** First, **this is a hardware plus retail-operations business** —
mechanical design, a load-cell subsystem, an embedded controller sampling at kHz, calibration
procedures, drift management, fabrication, pilots, long sales cycles, capital. A different
discipline from the Python pipeline. Worth knowing before the first weld, not after. Second, the
unglamorous mandatory project: **you need a mass for every SKU.** GS1/GDSN will not reliably give
net weights for Indian FMCG, so plan to weigh the catalog yourself — two people, a bench scale, a
few days for 1000 items, and an ongoing process as the catalog changes. It is boring, and the
entire architecture rests on it.

---

## 9. Before writing ARCHITECTURE.md

Three **[UNRESOLVED]** items from §1.2 must be pinned, because they will be fabricated to:
**beam pitch (10 or 20 mm)**, **plane separation (30 or 40 mm — 40 mm is the later source)**, and
the **bill candidate-set size (n ≈ 15 or 20)**, which is cosmetic but appears in the ~70× pruning
claim. Everything else in this file is either decided, measured with provenance, or explicitly
labelled an estimate.

> **Resolution, 2026-08-24:** `ARCHITECTURE.md` §3.2 pins these as **[PROVISIONAL]** — beam pitch
> **10 mm**, plane separation **40 mm**, mass window **300 ms** — so the design is buildable, with
> each flagged at the point of use and settled by Phases 0–1 of `BUILD_PLAN.md`. The candidate-set
> size is written as **n ≈ 15–20** throughout.

---

**What could not be safely documented:** nothing was withheld, but three classes of content are
marked rather than asserted — the four `[UNRESOLVED]` numeric conflicts above; every
`[ESTIMATE]`, none of which has been verified on hardware (the ±3–5 g differential figure and the
curtain reliability table are the load-bearing ones); and the deferred photo-capture SOP, which
was requested but never actually produced, so there is nothing to recover.
