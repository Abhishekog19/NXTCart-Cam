# NXTCart-Cam — Build Plan

**Companion documents:** `ARCHITECTURE.md` (the design of record) · `CONTEXT_SNAPSHOT.md` (decision provenance, rejected approaches, measured facts) · `IDENTITY_TRACKING.md` (the current CV layer, most of which this plan retires).

> **Document-set status, 2026-08-24:** `CONTEXT_SNAPSHOT.md` and `ARCHITECTURE.md` were produced in session but are **not yet committed to the repo**. This plan references them as if present; commit both before Phase 3 starts, or the gate criteria below have no authority to appeal to.

**What this document is.** The order of work, the money and time each step costs, and — the important part — **the number that decides whether the next step happens.** Every phase has a gate. A gate that cannot be evaluated is not a gate, so each one names a measurement, not a feeling.

**What it is not.** It is not the architecture (see `ARCHITECTURE.md`) and it does not re-argue settled decisions (see `CONTEXT_SNAPSHOT.md` §4).

Tags: **[MEASURED]** run on hardware · **[ESTIMATE]** derived, unverified · **[PROVISIONAL]** pinned so work can proceed, settled by a named phase.

---

## 0. The three rules this plan obeys

**R1 — Bench before cart.** Nothing gets welded, mounted or fabricated until the sensing works on a table. A cart is an expensive way to discover that a beam array miscounts.

**R2 — Per-sensor error curves before fusion.** Each channel gets characterised alone, with a documented error curve, before any adjudicator consumes it. Fusing two channels whose error you have not measured produces a system whose error you cannot measure.

**R3 — Software runs ahead of hardware, on simulated sensors.** The decision engine, the ledger, the conservation invariant and the adversarial harness need no load cells. They can be built and red-teamed against scripted event streams while the sensor work proceeds. `test_scripted.py` already has the right shape for this.

**Consequence of R3:** this is not a serial plan. Workstream **B (software)** runs in parallel with **A (sensing)** from day one, and they meet at Phase 4.

---

## 1. Phase map

```
        WORKSTREAM A — sensing                    WORKSTREAM B — software
        ─────────────────────────                 ────────────────────────
  P0    Curtain bench rig          ◄── GATE 0
        ~₹1,000 · 1 weekend
           │                                      P3  Decision engine, simulated
           ▼                                          sensors. Ledger, conservation,
  P1    Mass differential rig      ◄── GATE 1          adjudicator, adversarial harness
        ~₹4,000 · 2 weeks                             2–4 weeks · ₹0
           │                                              │
           │  P2  Catalog weighing (100 SKUs)             │
           │      ~₹500 · 1 afternoon  ◄── GATE 2         │
           │      + photo/reference SOP                   │
           ▼                                              ▼
        ┌──────────────────────────────────────────────────────┐
  P4    │  BENCH APERTURE — first end-to-end system            │  ◄── GATE 4
        │  curtain + 1 cell + barcode + camera, on a table     │
        │  ~₹8,000 · 3–4 weeks                                 │
        └──────────────────────────────────────────────────────┘
           │
           ├─► P5  Impulse/material channel        ◄── GATE 5   (optional, gated on need)
           │       ~₹2,000 · 1 week
           ▼
  P6    Sealed cart integration    ◄── GATE 6
        4 cells + IMU + one aperture. Conservation goes live.
        ~₹35,000 · 6–10 weeks
           │
           ▼
  P7    RED TEAM                   ◄── GATE 7
        Pay people to beat it. ~₹15,000 · 2 weeks
           │
           ├─► P8  GBT adjudicator  (requires a few thousand audited events)
           ▼
  P9    Store pilot — one aisle, one chain, measured shrink delta
```

**[ESTIMATE]** Every cost and duration in this document. They are order-of-magnitude figures for planning, not quotes. Total to end of Phase 7: **~₹65,000** and **~4–6 months** at part-time intensity.

---

## Phase 0 — Curtain bench rig

**This is the experiment that gates everything.** It replaced the catalog-separability study as the critical first test the moment the design went barcode-first: mass no longer has to identify anything, but **the curtain is the clock**, and if it cannot count and direct reliably then the event model in `ARCHITECTURE.md` §4 has no foundation.

**Build.** Two parallel rows of modulated IR emitter/receiver pairs on a cardboard or foam-board frame sized to a cart aperture. Target geometry: **10 mm pitch, ~16 pairs per plane, 40 mm plane separation, 1 kHz scan** — the `[PROVISIONAL]` values from `ARCHITECTURE.md` §3.2. Drive the LEDs at a known frequency and demodulate at the receiver; a naive DC design will be swamped by ambient IR and will produce beautiful, meaningless results indoors.

**Protocol.** Drop **50 assorted real products** through it — varied size, shape, gloss, transparency, and deliberately including thin flat packets, transparent bottles, and dark matte packaging. Then repeat four specific adversarial sets:

| set | n | what it tests |
|---|---|---|
| Singles, varied orientation | 50 | count, direction, profile |
| Two items touching | 20 | the known overlap weakness |
| Two items separated by 10–30 mm | 20 | pitch-limited resolution |
| Hand in, hand out, hand in-with-item | 30 | topological hand/item discrimination |
| Removals (item withdrawn) | 20 | direction on the OUT path |

**Instrument it.** Log raw beam state at full rate to disk for every trial. The logs become the simulated input for Workstream B, so this phase produces *data*, not just a verdict.

### GATE 0

| metric | pass | investigate | kill |
|---|---|---|---|
| Direction correct (IN vs OUT) | ≥ 99.5% | 98–99.5% | < 98% |
| Object count correct, non-touching | ≥ 99% | 95–99% | < 95% |
| Object count correct, touching pairs | ≥ 80% | 50–80% | < 50% |
| Hand vs item classified | ≥ 98% | — | < 95% |
| Silhouette usable — bottle vs packet separable | yes | — | no |
| Transparent/dark packaging detected at all | 100% | — | any miss |

**Notes on the gate.** Touching pairs are *expected* to be the weak column — that is why the architecture has the twice-the-width-and-twice-the-weight cross-check. 80% is a pass, not a triumph. A **transparent-bottle miss is a kill-level defect**, not a tuning issue: an item the curtain cannot see at all breaks the clock, and the fix is an emitter/receiver or wavelength change, not software.

**If GATE 0 kills:** the fallback is the two-scale hierarchy from `CONTEXT_SNAPSHOT.md` §4 — rejected on UX grounds, but the mass channel can carry counting if the curtain cannot. Do not proceed to Phase 1 pretending otherwise.

**Deliverables.** Working rig · raw beam logs for all 140 trials · a one-page error table · the two `[PROVISIONAL]` geometry values settled with evidence.

---

## Phase 1 — Mass differential rig

**Purpose.** Produce the load-cell error curve, and specifically confirm or refute the single most load-bearing estimate in the whole architecture:

> **[ESTIMATE]** A delta over a ~300 ms window with the cart stationary reaches **±3–5 g on a 30 kg basket**, because both readings share the same thermal and creep state, leaving only short-term noise.

That figure is why there is no weighing tray. If it is wrong by 3×, the tray comes back.

**Build.** One 30 kg-class cell (or a 4-cell set if budget allows — the geometry work in Phase 6 needs it eventually) on a rigid plate, 24-bit ADC, MCU. **Start with HX711** at 10/80 SPS: it is adequate for the mass *step* and it is what you can buy today. Do **not** buy the fast ADC yet — that is Phase 5, and only if Phase 5 is triggered.

**Protocol.** Characterise, in this order — each is a curve, not a number:

1. **Noise floor.** Static, 10 minutes, cart still. σ vs averaging window (50/100/200/300/400/600 ms).
2. **Step resolution.** Add known masses — 5, 10, 20, 50, 100, 250, 500, 1000 g — at basket preloads of 0, 5, 10, 20, 30 kg. **This is the core table.** It answers "can we resolve 5 g when the basket already holds 25 kg?"
3. **Window sweep.** Repeat step resolution at 200 / 300 / 400 ms. Settles the `[PROVISIONAL]` window in `ARCHITECTURE.md` §4.2 with data instead of recollection.
4. **Rolling.** Same steps with the rig pushed on a trolley over tile, then over a bump. Establishes how hard the IMU gate has to bite, and how long a deferred event waits.
5. **Thermal/creep.** Load 10 kg, leave 2 hours, log drift. Confirms that the *absolute* reading drifts while the *differential* does not — the distinction the whole design rests on.
6. **Off-centre.** Same mass at 9 plate positions. First evidence for the centre-of-mass channel.

### GATE 1

| metric | pass | investigate | kill |
|---|---|---|---|
| Δmass resolution @ 30 kg preload, 300 ms, still | ≤ 5 g | 5–15 g | > 15 g |
| Δmass resolution @ 30 kg preload, rolling | ≤ 15 g, or reliably gated out by IMU | — | mass unusable while rolling *and* IMU cannot detect it |
| Differential immune to 2 h thermal drift | residual drift ≤ 2 g | 2–10 g | > 10 g |
| Centre of mass locates a 250 g item | within ~1 quadrant | — | no signal |

**If Δmass lands in 5–15 g:** the system still works — verification tolerates it for anything above ~50 g — but the small-item floor rises, more events land at grade C, and the audit rate goes up. Quantify that cost before proceeding rather than absorbing it silently.

**If GATE 1 kills:** reinstate the two-scale hierarchy (precision plate + coarse basket scale auditing each other). This is the one place the rejected design is the correct fallback, and Phase 1 is deliberately cheap so this decision is cheap.

**Deliverables.** Six error curves · the settled mass window · a documented `sigma_g` model the adjudicator can call · recalibration procedure v0.

---

## Phase 2 — Catalog: weigh 100 SKUs, and write the photo SOP

Runs in parallel; blocks nothing except Phase 4's realism.

**Why it matters less than it used to.** Under the gate-tray design, mass had to *identify* — so SKU mass collisions were existential. With barcode-first verification the question softens from *"how many SKUs collide?"* to *"can we distinguish the scanned item's mass from a plausible substitution?"* Do it anyway: Phase 4 needs a real catalog, and the collision number sizes the tie-break burden on silhouette/density/colour.

**Protocol.** 1 g kitchen scale. 100 products from a kirana or supermarket, weighed **as sold, packaging included.** Deliberately include the nasty cases: same brand in multiple sizes, competing brands at identical declared weight, and the lookalike pairs already known. Record SKU, declared net weight, measured gross weight, dimensions, and a material class guess.

**[RESEARCH] The risk being tested:** Indian FMCG uses standardised pack sizes — 50/100/200/500 g, 1 kg — so declared weights cluster hard. **The saving detail is that declared net weight clusters and measured gross weight does not:** different packaging mass, fill tolerance, wrapper. That is empirical, not arguable, which is exactly why this phase exists.

**Compute one number:** at ±2 g, ±5 g and ±10 g, how many other SKUs does each item collide with?

### GATE 2

| median collisions @ ±5 g | meaning |
|---|---|
| ≤ 5 | mass prunes hard. Tie-breaks will be rare. |
| 5–20 | works; silhouette, density and colour carry more load. Budget for it. |
| > 20 | mass barely prunes. Not fatal under barcode-first verification, but every unbarcoded item (loose produce, grade B) becomes materially harder. Reconsider the grade-B path before Phase 6. |

**Second deliverable, owed twice and still unwritten: the photo/reference-capture SOP.** How to shoot reference images for maximum matching accuracy, and specifically how to handle similar packaging across different products. It lands next to `build_db.py`. Content to cover: fixed lighting and white balance, cross-polarisation for gloss, angle set per SKU, how many references per SKU, distinguishing-region annotation for lookalike pairs, and a re-shoot trigger when packaging changes.

**Third deliverable, boring and mandatory.** **[RESEARCH]** GS1/GDSN net-weight availability for Indian FMCG is **unconfirmed** — assume the catalog must be weighed in-house. Write the operational process now: two people, a bench scale, a few days per 1000 items, and a standing procedure for catalog churn. The entire architecture rests on having a mass for every SKU.

---

## Phase 3 — Decision engine on simulated sensors

**₹0. Starts today. Needs no hardware.** This is the highest-value-per-rupee phase in the plan, and it is where the existing codebase earns its keep.

**Build, in dependency order:**

1. **`ml/catalog.py`** — SKU record: mass, σ, dimensions, density, material class, counting policy, price. Loaded from the Phase 2 spreadsheet.
2. **`ml/ledger.py`** — Book A, grown from `ml/cart_state.py`. Lines with grades. **Append-only event log** from the first commit, because retrofitting auditability is how you end up unable to investigate the first real dispute.
3. **`ml/conservation.py`** — Path 2. Hand-coded, no learned component, ever. Implements `residual = measured − (tare + Σ expected)` with `tolerance = max(BASE_TOL_G, K·sqrt(Σσᵢ²))`. **[PROVISIONAL]** `BASE_TOL_G ≈ 15 g`, `K ≈ 3`, replaced by the Phase 1 σ model. The root-sum-square form is decided; the constants are not.
4. **`ml/evidence.py`** — assembles the ~21-feature vector of `ARCHITECTURE.md` §5.1.
5. **`ml/candidates.py`** — closed-set generation: the bill for OUT events, the scanned barcode for IN.
6. **`ml/adjudicator.py`** — **conservative hand rules only.** No model. The seven checks, the counting-policy table, the grade assignment, and the resolve-toward-the-shopper rule for removal ties.
7. **`ml/custody.py`** — the ~1 s single-object continuity check, salvaged from `identity_tracker.py`. Allowed to fail loudly.
8. **`test_scripted.py` extension** — the adversarial harness.

**The harness is the real deliverable.** Feed it scripted sensor event streams — mass steps, curtain patterns, barcode reads, vision scores — and assert the ledger verdict *and* the conservation state. Then encode **every row of `ARCHITECTURE.md` §8 as a test case**, including the three that only conservation catches (own bag, over the side, tilt-and-dump). Once Phase 0 finishes, replay its raw beam logs through the same harness so the curtain parser is tested against real signals, not synthetic ones.

**Deletion is part of the work.** `ml/identity_tracker.py` and `ml/track.py` lose the occlusion machinery — `OCCLUDED`, `LOST`, `REACQUIRE`, presence checks, visibility gating, merge guards, exit-progress accounting. Keep the removal on a branch until Phase 4 proves the event-gated path, then delete it and say so in the commit. The four CV-era removal guards at `ml/config.py:395-450` are **not** the four-part removal fix and must not be merged into it (`ARCHITECTURE.md` §9.3).

### GATE 3

- Every attack row in `ARCHITECTURE.md` §8 has a failing-before/passing-after test.
- Conservation triggers on all three bypass attacks in simulation.
- No test asserts a *silent* pass on an ambiguous event — ambiguity always produces a grade, a flag, or a stop.
- **The adjudicator contains no learned component.** If it does, Phase 8 arrived early and the hard boundary was crossed.

---

## Phase 4 — Bench aperture: first end-to-end system

**On a table. Not a cart.** One aperture, one load cell, the Phase 0 curtain, one fixed barcode reader, one camera under fixed lighting, the Phase 3 software behind it. 100 SKUs from Phase 2.

**Why this phase is the real milestone:** it is the first time the clock (curtain), the truth (mass), identity (barcode), and custody (camera) run against each other on real objects. Everything before it characterises channels in isolation, per R2. Everything after it is integration and productisation.

**Build order matters.** Wire the MCU event pipeline first — `ARCHITECTURE.md` §4.3 framed messages, including the `health` field — and prove the host receives well-formed events with correct timestamps *before* connecting the adjudicator. A timestamp bug discovered after fusion looks like an accuracy problem and costs a week.

**Protocol.** 500 scripted transactions across four categories:

| category | n | expectation |
|---|---|---|
| Honest single-item adds | 200 | ≥ 98% grade A, zero false flags |
| Honest removals | 100 | correct line credited; ties resolve to the cheaper item |
| Multipacks and multi-drops | 100 | counting policy table behaves; row-three cases ask for the pack barcode |
| Scripted attacks (§8 rows, executed physically) | 100 | **zero silent passes** |

### GATE 4

| metric | pass | investigate | kill |
|---|---|---|---|
| Silent passes on scripted attacks | **0** | — | any |
| Grade A rate on honest single adds | ≥ 95% | 85–95% | < 85% |
| False flags on honest transactions | ≤ 2% | 2–8% | > 8% |
| Custody failures on honest scans | ≤ 3% | 3–10% | > 10% |
| End-to-end latency, crossing → screen | ≤ 800 ms | 0.8–2 s | > 2 s |

**The false-flag column is the commercial gate, not the security one.** Per `ARCHITECTURE.md` §5.6, **false accusation is a more expensive failure than theft** — an 8% false-flag rate means one in twelve honest shoppers is stopped, which is an unshippable product regardless of how well it catches thieves.

**Do not quote a system accuracy figure after this phase.** An honest one comes only from Phase 7.

**Deliverables.** Working bench system · the 500-transaction result table · a latency budget · the first audited-event corpus (feeds Phase 8) · every discovered failure added to the Phase 3 harness permanently.

---

## Phase 5 — Impulse / material channel *(conditional)*

**Trigger condition — do not build this speculatively.** Enter Phase 5 only if Phase 2 showed median collisions > 5 at ±5 g, **or** Phase 4 showed same-mass substitutions surviving to grade B/C often enough to matter. Otherwise skip it; the channel is a nice-to-have, and `ARCHITECTURE.md` is explicit that each channel should be pushed only until it is good enough for its own job.

**Build.** Replace HX711 with an **ADS1220 (2 kSPS)** or **ADS1256 (30 kSPS)** class ADC and sample the load step transient at 500–1000 Hz. Extract damping ratio and settling signature.

**Protocol.** 20 items across rigid / soft / granular, 10 drops each, at 3 basket preloads.

### GATE 5

- Three-way material class separable at ≥ 90% → adopt as a cross-check feature.
- 70–90% → keep the feature, weight it low, never let it flip a verdict alone.
- < 70% → abandon the channel, revert to HX711, record the negative result.

---

## Phase 6 — Sealed cart integration

**First fabrication. First real money.** Only now, and only with Gates 0/1/4 passed.

**Scope.** Chassis with **one closed basket volume and one monitored aperture** — the structural precondition from `ARCHITECTURE.md` §1.2, and the thing that makes conservation meaningful. No under-basket rack, no child seat, no side pockets, or each weighed separately, or physically sealed for the session.

**Subsystems.** Four load cells at the corners, **read independently — never wired in parallel**, because paralleling averages away the centre-of-mass signal. IMU. The curtain in a **recessed or wiped optical housing** with the dirty-beam self-check enabled, because grime reading as a blocked beam is the genuine operational headache in a grocery environment. Barcode reader at the rim. Camera with fixed lighting. Compute, battery, screen.

**Conservation goes live here** — Path 2 against a real sealed volume, continuously, for the first time.

**Protocol.** 50 full shopping trips of 15–25 items each, over tile and over thresholds, by people who did not build it. Then a 2-week soak: dirt accumulation, battery cycles, calibration drift.

### GATE 6

| metric | pass |
|---|---|
| Conservation false-stop rate over 50 honest trips | ≤ 1 stop per 20 trips |
| Conservation catches all three bypass attacks physically | 100% |
| Centre-of-mass cross-check functional | yes |
| Dirty-beam self-check fires before counting degrades | yes |
| Calibration drift over 2 weeks | within the Phase 1 differential budget |
| Battery endurance | ≥ one full store day |

**Named cost, plainly.** **This is a hardware plus retail-operations business** — mechanical design, a load-cell subsystem, an embedded controller sampling at kHz, calibration procedures, drift management, fabrication, pilots, long sales cycles, capital. A different discipline from the Python pipeline. Worth knowing before the first weld, not after.

---

## Phase 7 — Red team

**The only phase that produces an honest accuracy number.**

**Protocol.** Pay people to steal from the cart and let them get creative. Brief them on the architecture — an informed attacker is the point. Cash bounty per successful undetected theft, scaled by value extracted. Two weeks. Behavioural datasets will not tell you what real attackers do; adversaries will.

Log every attempt, successful or not. Categorise each success: sensor gap, logic gap, or integration gap.

### GATE 7

| metric | pass |
|---|---|
| Silent thefts (undetected, unflagged) | **0** |
| Thefts flagged but not prevented | acceptable — this is the stated guarantee |
| Every success reproduced as a Phase 3 regression test | 100% |
| Attacks requiring > 1 attempt to succeed | ≥ 90% |

**The guarantee being tested is not "no theft."** It is:

> **No theft can happen silently.** It may be flagged rather than physically prevented, but nothing passes undetected.

**Every successful attack becomes a permanent regression test.** That is what makes the red team compound in value rather than being a one-off audit.

---

## Phase 8 — GBT adjudicator *(data-gated, not time-gated)*

**Entry condition: a few thousand audited events.** Not a date. Phases 4, 6 and 7 generate them; the store pilot generates the rest. **Rules first, model second — never the reverse**, because there is no data on day one.

**Build.** Gradient-boosted trees over the ~21-feature vector. Microsecond inference on the edge, low data requirement, and — the reason for the choice — **feature attribution for customer disputes.** Trees learn the interactions rules capture badly: "an 8 g mass error is fine on a 2 kg bag of atta but very suspicious on a 40 g biscuit pack."

**The audit flywheel is the training set.** Every grade-U or grade-C audit yields a human-labelled ground-truth pair on precisely the cases the system found hardest. Most systems discard their hard cases; this one harvests them.

**Also in scope: VLM escalation on ~2% of events.** Three frames, one narrow question — *"is this bottle blue or green Gatorade?"* — sub-second, fractions of a paisa. **[RESEARCH]** A 2026 retail theft-detection paper gated an expensive VLM behind cheap always-on detectors and cut model calls **240×** versus per-frame invocation.

### GATE 8 — the hard boundary, restated because this is the phase that could violate it

> **A learned model may never own the conservation invariant.**
> "Unexplained mass in the basket → stop" stays hand-coded and non-negotiable. A learned model drifts, can be probed and gamed, and offers no guarantees.
> **Rules own the extremes — clear pass and clear fail. The model owns only the grey zone.** The model can then be wrong without the system being unsafe.

Additional gates: the model must beat the Phase 4 hand rules on held-out audited events on **both** false-flag rate and silent-pass rate; every flag must remain explainable in one sentence a shopper can hear; and `conservation.py` must contain no import from the model layer, enforced by a test.

---

## Phase 9 — Store pilot

**Market wedge:** large-format organized retail — chains with long queues, big baskets, and a shrink number someone is accountable for. Not kirana; there is no queue there worth ₹30,000 of hardware per cart.

**Commercial structure, decided in `CONTEXT_SNAPSHOT.md` §4 and repeated here because the pilot is where it gets committed to a contract:**

- **Do not charge the shopper.** Trolleys have been free forever; any fee or friction at pickup means people take the ordinary cart, and an unused cart earns nothing and generates no training data. Adoption is the whole game.
- **Do not sell the hardware.** Hardware-as-a-service — you own the carts, the retailer pays monthly. No retailer will capex a fleet of an unproven product.
- **Price at 0.2–0.5% of basket value, or a flat per-cart-per-month fee.** **[RESEARCH]** Shrink is ~1.2% of sales in APAC (~1.5% US), ~78% of it theft — so the once-considered 1% of order value prices at roughly *the entire problem being solved* and leaves the retailer nothing. Flat monthly is also easier for a CFO to approve than a revenue share.
- **The wedge to lead with:** price on outcomes. *"We measure your shrink for 60 days, deploy, measure again, and you pay a share of the reduction."* Provable, self-funding, moves the conversation from your technology to their P&L — and it forces the product to genuinely work.

**Pilot design.** One store, 5–10 carts, 60 days of baseline shrink measurement *before* deployment, 60 days after. The delta is the product.

### GATE 9

- Measurable shrink reduction against the pre-deployment baseline.
- Shopper adoption rate ≥ 30% of eligible trips without incentives.
- Staff intervention rate low enough that one person can cover the aisle.
- Zero escalated false-accusation incidents.

---

## 2. Risk register

| # | risk | phase that resolves it | if it materialises |
|---|---|---|---|
| 1 | Curtain misses transparent or dark packaging | P0 | wavelength/emitter change; possibly a second detection modality at the aperture |
| 2 | Δmass resolution far worse than ±5 g | P1 | reinstate the two-scale hierarchy (the rejected fallback) |
| 3 | Indian FMCG mass clustering worse than hoped | P2 | lean harder on silhouette/density/colour; restrict the grade-B unbarcoded path |
| 4 | No GS1/GDSN net weights available | P2 | in-house catalog weighing — already assumed, budget the labour |
| 5 | Dirt degrades the curtain faster than the self-check catches | P6 soak | recessed/wiped optics; scheduled cleaning in the service contract |
| 6 | False-flag rate socially unacceptable | P4, P7 | widen tolerances, raise the grade-C threshold, accept more shrink. **False accusation is the more expensive failure** |
| 7 | Same-colour same-mass variants (shampoo) | P7 | rung 6 label-text verification. The acknowledged weakest link |
| 8 | Staff collusion | ongoing | append-only auditable log; no sensor fixes this |
| 9 | Fabrication and pilot cycles dominate the timeline | P6, P9 | expected. This is a hardware business |

---

## 3. What is explicitly out of scope for v1

Recorded so scope creep has to argue against a written line. Full reasoning in `CONTEXT_SNAPSHOT.md` §4.

Free-fall barcode reading · a gate tray or weighing plate · detailed 3D reconstruction from the curtain · quantity by weight ÷ unit weight · vision-first identification · behavioural/CCTV theft detection · late fusion of confidence scores · RFID on all SKUs (tiered by value, later) · charging the shopper · selling hardware outright.

---

## 4. Definition of done, per workstream

**Sensing (A) is done when** each channel has a documented error curve, the curtain settles its geometry with evidence, and the sealed cart holds calibration through a 2-week soak.

**Software (B) is done when** every attack row in `ARCHITECTURE.md` §8 is a regression test, every red-team success is a regression test, `conservation.py` has no learned dependency (enforced by a test), and the append-only log can answer "why was this shopper flagged?" in one sentence.

**The product is done when** the shrink delta in Phase 9 is measurable and the false-accusation count is zero.

---

## 5. Immediate next actions

1. **Commit `ARCHITECTURE.md` and `CONTEXT_SNAPSHOT.md`** to the repo. This plan's gates reference them.
2. **Order Phase 0 parts** (~₹1,000): IR emitter/receiver pairs, an MCU, foam board. Order 2× the pairs needed — some will be dead or mismatched.
3. **Start Workstream B today** (₹0): `ml/catalog.py`, then `ml/ledger.py` with the append-only log, then `ml/conservation.py`. None of it needs a sensor.
4. **Buy a 1 g scale and weigh 100 products** (~₹500, one afternoon). Phase 2 blocks nothing and unblocks Phase 4.
5. **Write the photo/reference-capture SOP.** Owed twice, still unwritten, and cheap.

**The single most informative rupee is still Phase 0.** Two rows of beams on cardboard, 50 items dropped through, one weekend. It settles the clock the entire architecture is timed against.
