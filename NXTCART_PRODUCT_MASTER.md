# NXTCart — Whole Product Master Document

**The idea, shopper experience, operating model, business direction, and development status**  
Prepared: 7 October 2026 · Version 1.0  
Scope: the full NXTCart product vision documented in this workspace, including the camera module and its relationship to the wider cart.

> **NXTCart is a smart shopping cart that builds and verifies the bill while the customer shops. The customer scans a product at the cart, places it inside, sees the bill update, and can take it out again when they change their mind. The cart checks that the physical basket agrees with the digital bill, helping the retailer reduce losses while making shopping and checkout easier.**

This document brings the existing project material into one product narrative. **Existing prototype**, **planned design**, and **open decision** are distinguished throughout. A design decision is an intended direction, not proof that the hardware works. Targets and commercial estimates below come from project planning; they are not measured product results or current supplier quotations.

## 1. The purpose and opportunity

NXTCart aims to move the work of checkout into the shopping journey. Instead of collecting everything and then having every item scanned again at a counter, customers build a verified basket as they shop.

The product addresses two connected problems:

- **For shoppers:** checkout queues, delayed visibility of the total, and the inconvenience of correcting a basket at the end of a trip.
- **For retailers:** unscanned goods, product substitutions, incorrect quantities, billing mistakes, and the staff effort needed to resolve questionable transactions.

The intended result is a continuously updated bill with evidence behind each item. Normal shopping should need little intervention; exceptions should be resolved early and quietly.

The project’s central question is **“Does what is physically in the cart agree with what is on the bill?”** Product recognition supports that question, alongside scanning, weighing, and observation of items entering or leaving.

## 2. Who the product serves

| Audience | What they need from NXTCart |
|---|---|
| Shopper | Easy scanning, a clear running bill, straightforward removal, quick completion, and respectful help when something goes wrong |
| Retailer or chain | Measurable loss reduction, useful checkout capacity, acceptable operating costs, and reliable integration with store systems |
| Store associate | Clear explanations of exceptions and the ability to check the affected item without unnecessarily recounting the basket |
| Store manager | Visibility into cart availability, intervention rates, overrides, recurring failures, and pilot outcomes |
| NXTCart service team | Maintainable hardware, repeatable calibration, current product data, and evidence that helps diagnose failures |

**Recorded market direction:** large-format organized retail in India, especially stores with substantial baskets, queues, and a measurable inventory-loss problem. Small neighborhood shops are not the initial target in the existing plan.

## 3. The intended shopper journey

### Start shopping

The customer picks up an available cart without paying a cart-use or unlock fee. The precise session-start process—anonymous use, account, phone, or another mechanism—has not been decided in the supplied material.

### Add a product

1. Present the product’s barcode to a reader mounted at the cart rim.
2. Move the same product through the monitored opening into the basket.
3. The cart checks the scan against the object’s movement, appearance, and weight change.
4. When the evidence agrees, the item is accepted and the displayed basket and total update.

The customer deliberately presents the barcode. Reading a barcode while a product tumbles into the basket is outside the chosen design. No separate weighing tray is intended in the normal journey.

### Keep track of the purchase

The screen provides the current basket and bill, plus understandable prompts when an action needs attention. Product name, quantity, correct line price, and total are necessary for a trustworthy shopping experience. The prototype has a running basket and subtotal; the wider integration documentation records pricing and display gaps that still need resolution.

### Remove a product

The intended experience is to take the item back out through the same opening, with no removal button or routine rescan. The cart detects an outward crossing and a decrease in basket weight, identifies which billed item left, and reduces the bill.

Moving an item around inside the basket, covering it with another product, or putting a hand over it must not by itself remove it from the bill.

### Resolve an exception

A failed verification should produce a useful next step: present the item again, scan the pack’s barcode, wait briefly for a stable reading, or request assistance. A flag represents inconsistent or incomplete evidence; it is not a declaration that the customer stole something.

Where assistance is needed, the intended approach is a targeted check of the affected item. Staff corrections should leave an auditable record.

### Finish shopping and pay

The wider vision is a correct bill without conventional item-by-item checkout. Payment is mentioned as part of the cart backend, but the files do not establish a complete payment and exit process.

**Still open:** payment methods and provider, customer confirmation, receipts, failed payments, payment-to-exit authorization, changes after payment, returns, and recovery from interrupted sessions. Basket verification alone does not establish that payment has occurred.

## 4. What makes up the whole cart

The planned product combines a physical cart, several sensors, an on-cart display and computing unit, product data, billing decisions, and a store-service process.

| Part | Product responsibility | Current evidence |
|---|---|---|
| Enclosed basket and monitored opening | Keep merchandise within the volume being checked and make entry/exit observable | Planned physical design |
| Rim barcode reader | State which product the shopper intends to add | Scan input exists in the prototype; real hardware integration remains to be demonstrated here |
| Basket weight sensors | Measure additions, removals, and the physical total | Simulated input in the local demo; full weighing hardware is planned |
| Two-plane infrared beam array, or “light curtain” | Detect crossings, direction, object count, and coarse shape | Planned; bench validation required |
| Camera and controlled lighting | Check appearance and watch the scanned item move into the basket | Existing camera-module prototype |
| Motion and tilt sensor | Distinguish a stable cart from rolling, lifting, or tilting | Planned |
| On-cart computing unit | Combine evidence, maintain the basket, and manage decisions | A 2 GB Raspberry Pi is the documented deployment target; hardware performance remains unproven in this review |
| Shopper screen | Show the basket, bill, and actionable messages | Local demo exists; wider display integration is described in another workspace |
| Battery and charging arrangement | Keep carts available throughout store operations | Planned; full-store-day endurance is a target |
| Product catalog and price source | Supply product identity, price, physical expectations, and reference images | Small demo catalog exists; store-scale catalog remains work |
| Billing, payment, and store connection | Turn a verified basket into a completed retail transaction | Basket logic exists; payment and store integration are incomplete or unspecified here |
| Audit and maintenance process | Resolve disputes, trace overrides, and keep the fleet reliable | Planned operating model |

The mechanical design matters as much as the electronics. The intended basket has one monitored opening. An unmonitored lower rack, side pocket, or other merchandise area defeats the coverage assumption unless it is separately weighed or closed off.

The camera choice is still open between the documented USB-webcam and ESP32-CAM candidates. The plan is to choose using measurements of genuine products and substitutions under representative conditions.

## 5. How the cart decides what belongs on the bill

### Two independent records

The intended system keeps a digital record of the accepted items and an independent measurement of the physical basket. The expected combined weight of the billed products should agree with the measured contents within a tested tolerance.

If the cart is moving, it may need to wait for a stable reading. If an unexplained discrepancy persists while stationary, the planned response is to hold completion and request resolution. Here, **“stop” means a transaction or verification hold**; a wheel lock or physical restraint mechanism is not specified.

Weight agreement is essential evidence, but **it does not prove identity**. A cheap item and an expensive item can weigh the same. This is why the design also checks appearance and the path from scan to insertion.

### Each sensor answers a different question

- **Barcode:** what product was declared?
- **Camera:** does the entering item look like that product, and was it continuously observed after scanning?
- **Light curtain:** did something cross the opening, in which direction, and with what count and coarse profile?
- **Weight sensors:** how much mass entered or left, and does the overall basket reconcile?
- **Motion sensor:** is the cart stable enough for the weight measurement to be meaningful?

The design combines these checks because each has different weaknesses. Their combined performance must still be established experimentally; multiple sensors do not create a universal guarantee.

### One scan must correspond to the correct physical action

A scan cannot authorize repeated additions, and evidence from one action must not complete another. If the view is lost, two items compete for the camera’s attention, or the object is swapped between scanning and insertion, the intended response is a retry or review.

The current prototype includes this short item-following process. Its documentation also records a remaining concern about undetected dropped camera frames, so continuous observation should not yet be advertised as proven under every operating condition.

## 6. Product rules for difficult cases

| Situation | Intended product behavior |
|---|---|
| Correct product scanned and added | Accept once the required checks agree; update the bill |
| Product scanned but never placed inside | Do not complete an addition merely because a barcode was read |
| Unscanned product enters | Hold or flag the event for resolution |
| Cheap product scanned, different product inserted | Check weight and visual evidence; flag conflicting evidence even if weights match |
| One scan followed by multiple products | Reconcile object count, product identity, and weight; do not assume all objects are the scanned product |
| Sealed multipack | Treat it as its own product and price; ask for the pack barcode when necessary |
| Item becomes hidden inside the basket | Keep it on the bill unless there is evidence that it physically left |
| Genuine item removed | Identify the departing billed item and reduce the bill |
| Camera cannot judge or reference data is missing | Retry or request review; do not silently treat missing evidence as a match |
| Cart rolls or passes over a bump | Defer weight judgment until the reading is trustworthy |
| Sensor obstructed, dirty, or unavailable | Surface a health or verification problem and use an explicit recovery process |

**Quantity policy:** weight divided by the scanned unit weight is not sufficient proof of quantity. Otherwise, one heavier and more expensive product could be billed as several cheap light products. The catalog may eventually support carefully validated product-specific counting policies, including awkward small packets, but that exception must not become unrestricted weight-only billing.

**Loose produce and unbarcoded goods:** the design mentions a route using weight and visual evidence. It does not fully define customer selection, variable-weight pricing, packaging tare, or verification for these categories. Treat this as planned support with unresolved rules, not a demonstrated launch capability.

### Removal ambiguity needs a final policy

The documents describe three different behaviors:

- The standalone prototype holds ambiguous same-weight removals for review.
- The wider cart integration guide describes a less strict removal identity gate.
- The future architecture proposes crediting the cheaper candidate when identity remains ambiguous, to avoid an expensive-item credit for a cheap-item removal.

That future fallback can leave an honest customer under-credited. It needs explicit screen messaging and a correction route. The final unified customer policy remains a decision to close before a pilot; these behaviors should not be presented as one finished system.

## 7. Trust, loss prevention, and customer treatment

The loss-prevention objective is to detect and explain discrepancies before an incorrect basket is completed. The source documents express this ambition as **“no theft can happen silently.”** In this master document, that is a validation goal, not an achieved guarantee.

The planned checks address unscanned additions, substitutions, extra products, disputed removals, sensor obstruction, and unexplained changes to basket weight. Some cases remain difficult: nearly identical packages with the same weight, tiny items near the sensor noise floor, overlapping objects, deliberate obstruction, and goods outside the monitored basket.

The cart also cannot solve staff collusion by sensing alone. Overrides and corrections need a traceable history.

The recorded customer-service principle is clear: **a false accusation is a more expensive failure than a routine exception that needs quiet resolution.** Messages should explain what the cart observed and what the shopper can do next.

Suggested wording, rather than finalized interface copy:

- “Please present that item once more.”
- “The basket weight changed, but we could not match the item.”
- “Please scan the barcode on the whole pack.”
- “An associate can help confirm this item.”

### Evidence levels and targeted checks

The future design proposes recording how each line was accepted:

| Level | Meaning in the design | Intended handling |
|---|---|---|
| A | Barcode, weight, and visual evidence agree | Normal completion, subject to payment and overall reconciliation |
| B | Weight and appearance agree without a barcode | Proposed route for approved unbarcoded categories |
| C | Evidence is partial or marginal | Mark for review under a defined store policy |
| U | Physical goods lack a satisfactory billing explanation, or a claimed item lacks physical evidence | Hold and resolve |

There is a source inconsistency between allowing level B and treating every unscanned crossing as a hard stop. The product needs explicit approved exceptions before unbarcoded goods can be supported consistently.

## 8. The role of AI

The existing camera prototype compares the observed item against reference images and color information for the expected product. This supports verification after a scan.

The broader design begins with explicit rules. Once enough real, human-reviewed events exist, a learned decision model may help resolve borderline cases and reduce unnecessary interventions. Difficult label differences may eventually be escalated to a vision-language model.

The current repository includes tools to compare local verification with an external AI service on recorded transactions. That comparison capability is not evidence that a cloud model already controls live checkout.

**The intended boundary:** AI may help interpret uncertain evidence, but it must not override the independent rule that unexplained basket contents require resolution. Reviews also produce useful labeled examples for improving the product.

The local camera path can operate without a cloud call. Complete offline shopping, payment, synchronization, and recovery behavior have not been specified as an end-to-end product capability.

## 9. Product data and store operations

### Catalog onboarding

Each supported product needs a stable identity, barcode mapping where applicable, correct price, expected gross weight including packaging, acceptable variation, and suitable reference photos. The planned catalog also includes coarse dimensions, packaging/material category, and quantity policy where useful.

Printed net weight is not a substitute for measuring the packaged item as it enters the cart. Changes in packaging, pack size, price, or assortment need an ongoing update process.

The project assumes in-house catalog weighing where reliable supplier data is unavailable. Its first planned catalog exercise covers about 100 representative products, deliberately including lookalike and same-weight pairs.

Reference images should be captured using the selected camera, mounting position, and lighting. A written reference-capture procedure already exists, despite older planning documents listing it as still owed.

### Daily operation and service

The following operating outline is a synthesis of the maintenance requirements in the files; the final store procedure remains to be written.

1. Prepare charged carts, check sensor health, clean optics, and establish a trustworthy empty-basket baseline.
2. Ensure the store’s active products, prices, and reference data are available.
3. Assist shoppers with specific unresolved items and record corrections or overrides.
4. Take faulty carts out of service, diagnose recurring problems, and retain the relevant event history.
5. Recharge, clean, inspect, and maintain carts between operating periods.

Longer-term service includes calibration checks, battery maintenance, packaging updates, replacement parts, and staff training. The frequency and ownership of these activities must be established through testing and the service agreement.

### Data handling still to define

The planned audit trail covers item events, evidence, decisions, and staff actions. The project does not yet set final image-retention periods, access permissions, customer notice, cloud-image rules, or deletion procedures. These are open deployment requirements.

## 10. Business model and commercial direction

**Recorded direction: hardware as a service, paid for by the retailer.** NXTCart owns and supplies the carts, with recurring retailer payments rather than an upfront cart sale. Shoppers are not charged for using the cart.

The planning documents discuss these pricing options:

| Option | Recorded concept | Status |
|---|---|---|
| Flat subscription | Fee per cart per month | Amount and service terms undecided |
| Usage-linked pricing | Approximately 0.2–0.5% of basket value | Planning range, not an approved tariff |
| Outcome-linked pilot | Share of demonstrated reduction in store losses | Proposed sales approach; attribution and contract terms unresolved |

A previously considered 1% basket-value fee was rejected in the project discussion as leaving too little retailer benefit. This records the commercial decision without treating old market statistics as current evidence.

The retailer’s case should be demonstrated through reduced loss, shopper adoption, lower checkout friction, and manageable staff effort. These are value hypotheses to measure.

The unit economics must account for cart hardware, financing and replacement, maintenance, charging, catalog onboarding, connectivity, any paid AI use, support, and sales/deployment effort. Cart availability and utilization matter: an unused or frequently unavailable cart produces little value.

**No validated unit economics, production bill of materials, contracted price, or proven return on investment is established in this workspace.**

## 11. What exists today

This workspace is named NXTCart-Cam and contains the camera-centered prototype plus substantial documentation of the full cart. Its folder name should not narrow the overall product story, but its contents should not be mistaken for a complete deployed cart.

| Area | Status established by this review |
|---|---|
| Camera verification | Source exists for expected-product checks, visual/color comparison, image-quality gating, and retry/refusal outcomes |
| Scan-to-basket observation | Source exists for following one scanned item and requiring evidence of arrival |
| Running basket | Standalone item quantities, per-unit recorded weights, and subtotal logic exist |
| Removal | Standalone weight-based candidate matching and visual disambiguation exist, including ambiguity flags |
| Demonstration | Webcam-based demo tools exist with simulated barcode and weight inputs |
| Product references | 20 local reference images across five demo product folders; example price and weight data are present |
| Evaluation | Logic tests, scripted overlap/hide/reposition scenarios, reference capture, and camera/model comparison tools exist |
| Wider cart integration | Documentation describes a separate cart backend, inventory, screen, and sensor connections in `smart_cart_ws`; that workspace is not included here and was not independently reviewed |
| Full physical audit design | Documented, but the proposed light-curtain, full weighing, motion sensing, and continuous reconciliation system is not established as implemented here |
| Payment and production operations | Not demonstrated by the supplied workspace |

These are source-review findings. No new hardware experiment or runtime test was performed to create this document. Existing test scripts and historical measurements do not prove live-store reliability.

Known integration issues recorded in the files include placeholder prices, incorrect per-row display pricing in the wider backend, unsettled camera performance, missing real sensor validation, and the frame-gap concern. Their current state in the separate backend needs verification.

## 12. Roadmap from prototype to full product

The existing plan follows **bench before cart**: prove the sensing cheaply before committing to a fabricated fleet.

| Stage | What it establishes |
|---|---|
| 1. Opening-sensor experiment | Whether varied products and hands can be detected, counted, and assigned an entry/exit direction |
| 2. Weight experiment | Whether small additions and removals can be measured at realistic basket loads, with motion and drift understood |
| 3. Representative catalog | Real packaged weights, lookalike cases, and consistent reference images |
| 4. Decision rules with simulated events | Correct handling of additions, removals, uncertainty, and deliberate attack scenarios |
| 5. Integrated bench setup | Scanner, camera, crossing detection, weighing, and billing working together on real transactions |
| 6. Full cart integration | Enclosed basket, four weight sensors, motion sensing, computing, display, battery, and maintainability |
| 7. Adversarial testing | People deliberately attempt to obtain an incorrect accepted basket; discovered failures become repeatable checks |
| 8. Optional learned decision layer | Introduced after enough audited data exists and only if it improves measured outcomes |
| 9. Store pilot | Evidence of shopper adoption, operational viability, and retailer value |

Material/impact sensing is a conditional enhancement if the simpler evidence remains insufficient. Selective RFID for high-value products is a later option, not a requirement to tag the entire assortment.

### Existing targets to validate

These are internal acceptance targets from the build plan, not achieved performance:

- Bench transaction feedback within about **800 milliseconds** of crossing.
- At least **95%** straightforward acceptance on honest single-item additions at the bench gate, with a stricter 98% aspiration also present in its test protocol.
- No more than **2%** false flags on honest bench transactions.
- Zero silent passes in the defined scripted-attack and red-team tests; passing those tests does not establish immunity to all attacks.
- At most one reconciliation false stop per **20 honest cart trips** in the planned cart trial.
- Battery operation for at least one full store day, with the actual operating-day duration still to be defined.

The earlier plan estimates roughly **₹65,000 and 4–6 months at part-time intensity through adversarial testing**. These are historical planning allowances, not a current budget or delivery commitment. They are not a production per-cart cost and do not establish fleet or store-pilot expenditure.

## 13. Pilot and definition of success

The proposed pilot is **one store with 5–10 carts**, preceded by **60 days of baseline loss measurement** and followed by **60 days of measurement after deployment**.

Recorded pilot goals include measurable loss reduction, at least **30% adoption among eligible trips without incentives**, manageable staff intervention, and zero escalated false-accusation incidents.

A useful pilot should distinguish:

| Dimension | What to measure |
|---|---|
| Shopper experience | Adoption, completed trips, scan retries, removal corrections, time to finish, and complaints |
| Billing integrity | Wrong additions, wrong removals, quantity errors, and incorrect line prices |
| Loss prevention | Known substitutions accepted, unexplained contents, and results of deliberate attack tests |
| Store workload | Interventions per trip, resolution time, and staff needed to support the carts |
| Reliability | Cart availability, battery endurance, sensor faults, cleaning effort, and calibration drift |
| Commercial value | Measured benefit compared with the full cost of operating and supplying the service |

The detailed measurement method remains to be agreed. Before-and-after loss figures can be affected by changes in assortment, promotions, staffing, and shopper traffic; attribution should be defined before using the pilot to set outcome-based fees.

## 14. Decisions and limitations still to close

| Topic | What remains unresolved |
|---|---|
| Payment and exit | Payment methods, receipts, settlement confirmation, failed-payment recovery, and exit authorization |
| Session lifecycle | Pickup/start, abandonment, handover, completion, and restart after power loss |
| Retail billing | Authoritative prices, discounts, taxes, promotions, and accurate line-item presentation |
| Store integration | Catalog ownership, updates, inventory effects, and reconciliation with the retailer’s checkout system |
| Removal policy | One consistent rule for ambiguous identity and an easy correction process |
| Unbarcoded categories | Approved products, selection flow, variable-weight pricing, and exception policy |
| Physical usability | Aperture size, bulky/fragile items, customer bags, accessibility, and loading comfort |
| Sensor performance | Thin, transparent, dark, overlapping, and very light objects under actual store conditions |
| Hardware and service | Final components, charging method, endurance, durability, service intervals, and replacement cost |
| Network and failures | Offline behavior, loss of power or connectivity, and recovery without losing or duplicating bill entries |
| Privacy and access | Stored evidence, retention, staff access, cloud processing, and customer communication |
| Commercial agreement | Pricing choice, service responsibilities, support commitments, and measurement of retailer benefit |

Mass reconciliation cannot detect every substitution, and a flat silhouette is not a reliable measurement of arbitrary object volume. Shape, density estimates, and material clues remain supporting evidence to validate. None should be presented as a solved identity guarantee.

Features such as autonomous driving, customer-following motion, store navigation, loyalty personalization, or advertising are not established requirements in these files. They should not be included in the committed product scope without a separate decision.

## 15. Boundaries already established in the project

The documented direction avoids routine customer interaction with an extra weighing tray, barcode reading in free fall, camera-only basket recognition, detailed 3D reconstruction, unrestricted quantity inference from weight, and an architecture that simply averages conflicting sensor confidence scores.

The product is not intended to charge shoppers for cart access or sell hardware outright under the current business direction. RFID for every product is also outside the initial scope.

The previously rejected weighing-tray/two-scale approach is retained only as a fallback if the simpler weighing arrangement fails its experiments. A fallback should be revisited against the original requirement to keep shopping easy.

## 16. Source map and maintenance of this master document

This review inventoried the workspace, including hidden project entries and local reference/model assets, and scanned the documentation, source modules, tests, scripts, and example data for product-relevant information. Binary model/database files and reference photos were inventoried as assets, not treated as product specifications. Git internals and generated caches were excluded from the product-content review.

| Source | What it contributes |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Whole-cart physical design, sensor roles, reconciliation, evidence levels, removal policy, and limitations |
| [CONTEXT_SNAPSHOT.md](CONTEXT_SNAPSHOT.md) | Recovered product decisions, customer principles, business direction, alternatives, and historical estimates |
| [BUILD_PLAN.md](BUILD_PLAN.md) | Development stages, validation gates, budget assumptions, and pilot structure |
| [CART_INTEGRATION.md](CART_INTEGRATION.md) | Relationship to the separate cart backend, display/billing behavior, and known integration gaps |
| [SETUP_AND_TEST.md](SETUP_AND_TEST.md) | What can be demonstrated locally and what requires real hardware |
| [DEPLOYMENT.md](DEPLOYMENT.md) | On-cart computing direction, camera comparison, and operational verification behavior |
| [REFERENCE_SOP.md](REFERENCE_SOP.md) | Product-image onboarding and reference maintenance |
| [IDENTITY_TRACKING.md](IDENTITY_TRACKING.md) | Earlier camera-only design, overlap/removal lessons, and its validation limits |
| [README.md](README.md), source, tests, scripts, and sample data | Evidence of the current prototype and its boundaries |

When sources disagree, this document preserves the distinction between current behavior and future intent, and lists unresolved customer-policy conflicts explicitly. Historical competitor claims, broad market statistics, and quoted AI costs have not been independently refreshed and are not used here as current market evidence.

Update this master when a product decision changes or a validation stage is completed. In particular, replace planned capabilities with measured status only when there is supporting evidence, and add the separate cart backend and payment findings when those materials are reviewed.
