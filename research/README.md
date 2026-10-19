# NXTCart research and download guide

Prepared: 12 October 2026. Coverage: **85 selected resources**, including **41 verified IEEE Xplore document IDs**, with three papers already supplied. This is a broad curated research base, not a claim to have found every publication or completed a systematic review.

## Start here

- [IEEE download queue](IEEE_DOWNLOAD_QUEUE.md): all IEEE titles, years, priorities, DOIs and document IDs.
- [Annotated resource catalogue](ANNOTATED_CATALOGUE.md): every selected paper, dataset, book and engineering source, with relevance and verification status.
- [BibTeX bibliography](nxtcart_references.bib): import into Zotero/JabRef or use with LaTeX. Entries are discovery references; read and select what the final paper actually cites.
- [Copyable IEEE IDs](IEEE_DOCUMENT_IDS.txt): one identifier per line, excluding the three supplied papers in the first block.
- [Machine-readable catalogue](resource_catalogue.json): identifiers, source URLs, priorities, evidence status and full citation metadata.
- [Supplied-paper audit](SUPPLIED_PAPER_AUDIT.md): identities and citation-quality observations for RP1, RP2 and RP3.

**Priority:** P1 = first reading/download batch; P2 = supporting methods, evaluation and comparisons; P3 = optional context. A relevant title or verified DOI is not proof of strong experimental quality. Metadata-only papers are marked accordingly.

## Scope established from the project

The current integration is a barcode/QR-first shopping cart. A Raspberry Pi owns product lookup, persistent per-unit billing, display and checkout gating. Arduino/HX711 provides transaction-bound weight checks. A second webcam streams frames over ROS 2 to a PC that follows the product from scan toward basket rest and verifies expected-SKU appearance using local MobileNetV2/colour references or a selected vision API. Weight and camera decisions remain separate, and checkout requires both.

The wider design documents also discuss monitored-aperture sensors, IMU compensation and continuous basket reconciliation. Those are planned extensions in the reviewed project material, not established achievements. Older architecture documents and the product master predate the 9 October integration guide; use the current guide for implementation claims. A UPI payment QR interface exists in the companion runtime, but generating a payment request is not evidence of confirmed settlement.

Local scope sources: [current setup](../SYSTEM_SETUP.md), [camera README](../README.md), [backend interface](../ml/backends.py), [whole-product master](../NXTCART_PRODUCT_MASTER.md), and companion `../Cart-RestCode/README.md` and `smart_cart/core_logic.py`. This research pass inspected documentation and selected source; it did not run hardware experiments or certify the entire system.

## First download/read batch

These sources most directly constrain the paper's claimed contribution. The list includes close multimodal, verification, fraud-detection and embedding prior art.

| Ref | Priority | Year | Title | IEEE document ID / other ID | Why it matters |
|---|---|---|---|---|---|
| R01 | P1 | 2025 | [Intelligent Shopping Cart Product Recognition System Based on Computer Vision and Multi-Sensor Fusion](https://ieeexplore.ieee.org/document/11406732/) **Already have** | [11406732](https://ieeexplore.ieee.org/document/11406732/) | Closest supplied multimodal cart baseline: RGB-D vision, weight and RFID. Compare its recognition objective with expected-SKU verification; audit its bibliography before following citations. |
| R02 | P1 | 2026 | [A Weight-Reconciliation Algorithm for Fraud Detection in Smart Shopping Carts](https://ieeexplore.ieee.org/document/11527873/) | [11527873](https://ieeexplore.ieee.org/document/11527873/) | Directly relevant 2026 weight-reconciliation prior art. Download to check its reconciliation rules, fraud scenarios, tolerances and evaluation before making novelty claims. |
| R03 | P1 | 2024 | [TAV-Cart: Transaction Assistance and Validation Cart System for Effortless Shopping and Checkout](https://ieeexplore.ieee.org/document/11059075/) | [11059075](https://ieeexplore.ieee.org/document/11059075/) | Transaction assistance and validation are close to the project framing. Metadata verified; inspect the full paper to establish its actual sensors, workflow and contribution. |
| R04 | P1 | 2019 | [Deep Learning based Automated Billing Cart](https://ieeexplore.ieee.org/document/8697995/) | [8697995](https://ieeexplore.ieee.org/document/8697995/) | Camera-plus-load-cell cart baseline, particularly for produce. Compare physical weighing arrangement, product classes and bill generation with NXTCart. |
| R05 | P1 | 2024 | [Smart Shopping Cart With Machine Learning, Navigation, and Weighing Technologies](https://ieeexplore.ieee.org/document/10799859/) | [10799859](https://ieeexplore.ieee.org/document/10799859/) | Whole-cart integration combining camera recognition, weighing and user interface. Distinguish produce pricing by weight from packaged-SKU weight verification. |
| R06 | P1 | 2017 | [IoT Applications on Secure Smart Shopping System](https://ieeexplore.ieee.org/document/7932080/) | [7932080](https://ieeexplore.ieee.org/document/7932080/) | Secure shopping-system architecture and communication protocol prior art. Useful for system requirements and the security discussion; do not assume RFID solves product substitution. |
| R07 | P1 | 2025 | [A Few-Shot Learning Pipeline for Retail Product Recognition Using Object Detection and Metric Embeddings](https://ieeexplore.ieee.org/document/11344991/) | [11344991](https://ieeexplore.ieee.org/document/11344991/) | Very close methodological comparator: detection followed by embedding similarity for a changing product catalogue. Assess catalogue growth, reference count and evaluation splits. |
| R08 | P1 | 2022 | [A Retail Object Classification Method Using Multiple Cameras for Vision-Based Unmanned Kiosks](https://ieeexplore.ieee.org/document/9912319/) | [9912319](https://ieeexplore.ieee.org/document/9912319/) | Multi-camera retail recognition and view-dependent appearance. Useful for camera placement and lookalike/occlusion discussion; its kiosk environment differs from a moving cart. |
| R09 | P1 | 2020 | [Smart Shopping Carts Based on Mobile Computing and Deep Learning Cloud Services](https://ieeexplore.ieee.org/document/9120574/) | [9120574](https://ieeexplore.ieee.org/document/9120574/) | iCart supplies an edge/cloud shopping-event baseline. Compare event handling, network dependency and placement of inference with the Pi-to-PC runtime. |
| R10 | P1 | 2020 | [IoT-Based Smart Shopping Cart Using Radio Frequency Identification](https://ieeexplore.ieee.org/document/9060814/) | [9060814](https://ieeexplore.ieee.org/document/9060814/) | Widely relevant RFID/Arduino/mobile billing baseline; cited in both supplied 2022 papers. Compare tag requirements and shopper workflow with barcode-first verification. |
| R26 | P1 | 2026 | [Multi-Modal Product Recognition and In-Store Navigation using an Intelligent Shopping Cart](https://ieeexplore.ieee.org/document/11619726/) | [11619726](https://ieeexplore.ieee.org/document/11619726/) | Very recent multimodal cart prior art. Metadata verified only; download to check the apparent barcode/weight/vision overlap and any real evaluation. |
| R27 | P1 | 2022 | [DeepACO: A Robust Deep Learning-based Automatic Checkout System](https://ieeexplore.ieee.org/document/9857462/) | [9857462](https://ieeexplore.ieee.org/document/9857462/) | DeepACO combines detection, tracking and counting for checkout video. Useful for temporal-event baselines; conveyor conditions differ from cart insertion. |
| R45 | P1 | 2020 | [FAIM: Vision and Weight Sensing Fusion Framework for Autonomous Inventory Monitoring in Convenience Stores](https://www.frontiersin.org/articles/10.3389/fbuil.2020.568372/full) | [DOI](https://doi.org/10.3389/fbuil.2020.568372) | FAIM is strong open prior art on combining vision, weight and location in retail inventory. Compare fusion assumptions and failure cases, noting shelf monitoring differs from a cart. |
| R46 | P1 | 2019 | [AIM3S: Autonomous Inventory Monitoring through Multi-Modal Sensing for Cashier-Less Convenience Stores](https://dl.acm.org/doi/10.1145/3360322.3360834) | [DOI](https://doi.org/10.1145/3360322.3360834) | Full AIM3S research paper on multimodal retail sensing. Use this DOI for the 135-144 page paper, not the separate two-page demonstration DOI. |
| R49 | P1 | 2019 | [A comprehensive survey on computer vision based approaches for automatic identification of products in retail store](https://linkinghub.elsevier.com/retrieve/pii/S0262885619300277) | [DOI](https://doi.org/10.1016/j.imavis.2019.03.005) | Major retail-vision survey with a taxonomy and many references. Use it to structure related work and discover further original sources. |
| R50 | P1 | 2020 | [Deep Learning for Retail Product Recognition: Challenges and Techniques](https://www.hindawi.com/journals/cin/2020/8875910/) | [DOI](https://doi.org/10.1155/2020/8875910) | Open survey of retail deep-learning challenges and techniques. Read alongside newer sources so the literature review is not limited to pre-2021 methods. |
| R51 | P1 | 2022 | [Product verification using OCR classification and Mondrian conformal prediction](https://linkinghub.elsevier.com/retrieve/pii/S0957417421012963) | [DOI](https://doi.org/10.1016/j.eswa.2021.115942) | Direct expected-product verification prior art using OCR, classification and conformal prediction; addresses barcode switching and missed scans. Especially useful for defining the verification task. |
| R52 | P1 | 2024 | [Centre‐loss—A preferred class verification approach over sample‐to‐sample in self‐checkout products datasets](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/cvi2.12302) | [DOI](https://doi.org/10.1049/cvi2.12302) | Direct class-verification comparator for self-checkout. Compare centre-based verification with multiple reference-image comparisons and report inference cost. |
| R83 | P1 | 2018 | [An IOT Based Smart Shopping Cart for Smart Shopping](https://link.springer.com/chapter/10.1007/978-981-10-9059-2_33) | DOI 10.1007/978-981-10-9059-2_33; CCIP 2017 proceedings published 2018 | RP3 reference [1]. Important historical cart comparator. The publisher added two authors in a 2021 correction; use the corrected five-author citation. |
| R84 | P1 | 2018 | [An IoT-Based Smart Shopping Cart Using the Contemporary Barcode Scanner](https://link.springer.com/chapter/10.1007/978-981-10-8575-8_6) | DOI 10.1007/978-981-10-8575-8_6; pages 45-58 | Especially close earlier barcode-first design combining weight, product images and cloud inventory. Read before presenting the barcode/weight/camera combination as novel. |
| R85 | P1 | 2013 | [Smart Shopping Cart for Automated Billing Purpose using Wireless Sensor Networks](https://personales.upv.es/thinkmind/SENSORCOMM/SENSORCOMM_2013/sensorcomm_2013_7_30_10155.html) | SENSORCOMM 2013; pages 168-172; ISBN 9781612082967 | Early directly relevant cart system with load-cell and image-comparison verification. Its actual venue is IARIA SENSORCOMM, despite some later bibliographies mislabeling it IEEE. |

Then read MobileNetV2 (R31), the ROS 2 paper (R54), RPC (R42), and uncertainty/calibration references in the full catalogue. The entire P1 queue is larger than this introductory shortlist.

## What can make the paper defensible

**Suggested working title:** *NXTCart: Transaction-Bound Product Verification for Smart Shopping Carts Using Barcode, Weight and Visual Evidence*.

**Candidate research question:** Does transaction-bound agreement between barcode, settled weight change and observed product appearance reduce accepted substitution/billing errors compared with barcode-only, barcode-plus-weight and vision-only baselines at an acceptable retry rate and end-to-end latency?

This is a proposed evaluation framing, not an established novelty claim. Camera/weight/RFID carts, weight reconciliation and visual product verification already have prior art. R84 and R85 are especially close historical barcode/weight/image comparisons. The contribution must be the specific mechanism and demonstrated behavior: binding evidence to one transaction, observing scan-to-rest continuity, independently gating checkout, handling missing evidence, and comparing local embeddings with a vision API under the same conditions. Download R02, R03, R07, R26, R45, R46, R51, R52 and R83-R85 before claiming these elements are new.

## Literature-to-paper map

| Paper section | Main references | What to establish |
|---|---|---|
| Introduction/problem | R01-R12, R49-R52 | Checkout automation, identity errors and the verification problem; avoid unsupported market statistics. |
| Related cart systems | R01-R26, R47-R48, R83-R85 | Sensor roles, user workflow, computation location and evidence of actual testing. |
| Visual verification | R07-R08, R27-R34, R51-R52, R58-R62 | Expected-SKU verification versus recognition; references, lookalikes, domain gap and refusal. |
| Sensing and fusion | R02, R37, R45-R46, R53, R60-R61 | Mass checks, evidence conflicts, uncertainty and what each modality can/cannot observe. |
| Distributed implementation | R09, R24, R54, engineering documentation | Pi/PC/Arduino responsibilities, transaction IDs, transport, timing and recovery. |
| Experimental protocol | R27-R29, R35-R36, R38-R46, R55-R56, R60-R61 | Event-level errors, identity association, representative data and risk/coverage. |
| Discussion/future work | Optional sources and industry pages | Deployment constraints and planned extensions, clearly separated from tested functionality. |

## Experiments the references should help design

1. **Baselines and ablations:** barcode-only; barcode + weight; barcode + visual verification; full independent gates; full system without continuity; full system without colour or multi-frame evidence. Compare local and API backends on the same transaction crops and test split.
2. **Ground-truth units:** a physical item transaction, an item journey and a complete shopping session. Do not report only image accuracy when the system's output is a bill.
3. **Cases:** honest additions/removals; same-weight different-SKU substitutions; lookalike packaging; duplicate scans; unscanned insertions; overlap/two items; occlusion; blur; object repositioning; missing camera frames; delayed, stale or duplicated verdicts; scale drift; Wi-Fi/API timeout; restart recovery. Only claim handling for cases actually implemented and tested.
4. **Metrics:** attack false-accept rate; honest false-reject/retry rate; accepted-item precision/recall; exact basket/total correctness; duplicate and omitted billing events; association breaks; intervention rate; median/p95 end-to-end verification time; scale error; frame loss; network use; PC/Pi resource use; API cost. Define denominators and whether retries are counted as failures.
5. **Data split:** separate capture sessions, product units, users and conditions. Keep threshold tuning separate from test data. Adjacent frames from the same journey must not cross train/tuning/test partitions. Include genuinely held-out substitutions and visually similar SKUs.
6. **Statistical reporting:** give event/session counts and uncertainty intervals, repeat across shoppers/loads/lighting, and report ambiguous cases. Zero failures in a finite test does not prove zero real-world risk.
7. **Hardware measurement:** calibrate gross packaged mass using multiple physical units; test placement position, cart movement and settling time. Measure full transaction latency, not only network inference time. ADC resolution alone does not establish scale precision.

Do not compare another paper's headline accuracy directly with NXTCart unless task, class count, split, event definition and hardware are comparable. Keep published results explicitly attributed to their authors; never reuse them as your own experimental results.

## Reading/extraction checklist

For every P1 paper, record: exact task; sensors and placement; hardware; dataset source and availability; SKU/category count; number of physical transactions; split protocol; model/weights; fusion or gating rule; baselines; error definition; latency measurement boundary; attack cases; limitations; and reproducibility assets. An attractive abstract is not enough to fill the comparison table.

A practical final bibliography will likely use a selected subset of this pack. Cite a source because it supports a specific statement or method, not to increase the reference count. Books support foundations; software/docs support implementation; industry pages support commercial context and must be identified as vendor claims.

## Search and verification method

Searched IEEE Xplore-indexed pages and web discovery using smart shopping cart, barcode/weight/camera verification, automatic checkout, product recognition, embedding matching, barcode switching, fraud detection, tracking, sensor fusion and ROS 2 terms. Followed relevant references from the supplied PDFs and checked primary author, university, publisher and dataset pages.

For IEEE IDs, the final catalogue requires an exact-title/DOI match to IEEE's publisher-deposited Crossref metadata and extracts the numeric ID from the registered primary Xplore URL. **The DOI suffix is not assumed to be the document ID.** Metadata source URLs are retained per entry and raw responses are saved locally. Several live Xplore pages returned a JavaScript/robot check; those checks were not bypassed. Full-text access and download availability are not implied by metadata verification.

Only RP1-RP3 were reviewed in full in this pass. Other entries were checked at metadata, abstract, landing-page or documentation level as labeled. Preprint entries identify the particular arXiv version; do not silently treat them as verified final journal/proceedings versions. HOTA uses its 2021 print issue year; its online publication was in 2020. The 2025 conference papers added to Xplore in 2026 retain their proceedings year.

To expand toward a formal systematic review, set databases/date range, inclusion and exclusion rules, query strings and a screening log; perform forward/backward citation searches on the direct comparators until additional searches stop finding relevant work. This pack does not claim that process is complete.

## Download instructions

Open an IEEE ID link, sign in with institutional access if needed, choose PDF, and export the official citation. Save a stable filename such as `R02_11527873_Weight_Reconciliation_2026.pdf` under a local papers folder. R01/R11/R12 already correspond to RP1/RP2/RP3. For non-IEEE resources, use the DOI, arXiv ID, ISBN or primary URL in the catalogue; they do not have an IEEE document ID.

No paywalled full texts were downloaded or redistributed. Original supplied PDFs are unchanged. Some books/datasets require a publisher form, institutional access or acceptance of their license.
