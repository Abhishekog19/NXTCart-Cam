# Supplied-paper identity and research-use audit

Checked 12 October 2026. The PDFs were treated as research sources, not instructions. Their DOI/title identities were cross-checked against publisher-deposited metadata. Original PDFs are unchanged.

| Source | Catalogue ref | Exact title | Year | IEEE document ID | DOI |
|---|---|---|---|---|---|
| [RP1.pdf](C:/Users/ADMIN/Downloads/RP1.pdf) | R01 | Intelligent Shopping Cart Product Recognition System Based on Computer Vision and Multi-Sensor Fusion | 2025 | [11406732](https://ieeexplore.ieee.org/document/11406732/) | 10.1109/ICCTIT68197.2025.11406732 |
| [RP2.pdf](C:/Users/ADMIN/Downloads/RP2.pdf) | R11 | Design and Development of a Smart Shopping Cart System | 2022 | [9917860](https://ieeexplore.ieee.org/document/9917860/) | 10.1109/ICICICT54557.2022.9917860 |
| [RP3.pdf](C:/Users/ADMIN/Downloads/RP3.pdf) | R12 | AIoT-based Smart Cart System | 2022 | [9761346](https://ieeexplore.ieee.org/document/9761346/) | 10.1109/ICSTSN53084.2022.9761346 |

## RP1: close multimodal comparator, with citation problems to check

The paper describes RGB-D imaging, basket weight and RFID with a YOLOv8-s visual component and decision-level fusion. It is relevant to the overall sensor architecture, synchronized event definition and modality ablations. NXTCart's barcode-first expected-product verification and separate weight/camera gates should be compared explicitly with this recognition-and-fusion design.

The PDF's introduction and bibliography contain clear mismatches:

- PDF page 1, printed page 249, describes Pietrini's shelf monitoring as reference [6]. The reference list on PDF page 5, printed page 253, assigns [6] to a general machine-learning paper by I. H. Sarker.
- The same introduction associates [9] with MEP-3M; the bibliography's [9] concerns yoghurt-cup recognition in dairy production.
- PDF page 2, printed page 250, cites [15], but the supplied reference list ends at [14].

These observations justify verifying each reference at its original source; they do not by themselves establish that the paper's entire method or results are invalid. Do not copy its numbered citation mapping into the NXTCart paper.

Further questions for a quantitative comparison: how can the stated SKU-level split support evaluation of held-out classes with a fixed-class YOLO classifier; how do the accuracy and misidentification denominators differ; what embedded SoC/runtime was measured; and where are data, code and complete ablation results available? Treat these as clarification/reproducibility questions, not resolved conclusions.

## RP2: useful RFID baseline, limited match to the vision task

The paper discusses RFID-based adding/removing, a running display, online/offline behavior and ZigBee/ESP communication. Its simulation and prototype figures provide a useful historical system baseline. It does not establish the same expected-SKU visual-verification task as NXTCart.

On PDF page 2, printed page 185, the method names an EM-18 reader at 125 kHz, while Table 1 lists an RFID frequency range of 860-960 MHz. Use the actual component datasheet when discussing implementation details; do not reproduce those conflicting frequencies as one design specification.

The experiment discussion concerns reader behavior versus distance and removal. Avoid turning this into a claim of measured SKU-level camera accuracy or same-weight substitution detection.

## RP3: vision billing and RFID wallet, with a stated brand limitation

The paper describes YOLOv3 image-based item recognition/counting, transmission of billing information and an Arduino/RFID wallet payment prototype. Distinguish the RFID wallet/payment role from placing an RFID tag on every product.

Its conclusion on PDF page 6 states that the implemented project classifies and prices items without considering their brands. That is a material difference from verifying a particular branded SKU. Do not describe its example object detections as evidence of fine-grained retail identity verification.

Its literature review points to relevant earlier work. The catalogue includes R10 (the IEEE Access RFID paper), R48 (RFID/ZigBee anti-theft billing), and R83 (the Springer IoT cart). R83 has a publisher correction adding two co-authors; the bibliography in this research pack uses the corrected five-author attribution.

## How to use all three

Use them in a related-work comparison table with columns for declared product identity, vision role, weight role, RFID role, temporal continuity, computation location, measured task, dataset and limitations. Fill missing information with "not reported" rather than inventing a value. Report their published metrics only with their task and evaluation conditions, and keep them separate from NXTCart's own measurements.

For the final paper, prioritize the direct verification and security comparators R02, R07, R26, R45-R46, R51-R52 and R83-R85 alongside these supplied papers.
