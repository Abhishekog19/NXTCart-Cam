"""Build a curated reading/download pack from verified public metadata."""
import html
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATE = '2026-10-12'
metadata = {}
for filename in ['crossref_metadata.json', 'crossref_supplement.json', 'crossref_corrections.json', 'crossref_additional.json']:
    for result in json.loads((ROOT / filename).read_text(encoding='utf-8')):
        records = [result['record']] if 'record' in result else result.get('candidates', [])
        for record in records:
            metadata[record['DOI'].lower()] = record

# Selection is deliberate: unrelated Crossref search candidates are excluded.
# Reasons below are relevance assessments, not claims that NXTCart implements these methods.
SELECTION = [
('10.1109/ICCTIT68197.2025.11406732','P1','Cart systems','Closest supplied multimodal cart baseline: RGB-D vision, weight and RFID. Compare its recognition objective with expected-SKU verification; audit its bibliography before following citations.'),
('10.1109/ICKECS70176.2026.11527873','P1','Cart systems','Directly relevant 2026 weight-reconciliation prior art. Download to check its reconciliation rules, fraud scenarios, tolerances and evaluation before making novelty claims.'),
('10.1109/ICACCM61117.2024.11059075','P1','Cart systems','Transaction assistance and validation are close to the project framing. Metadata verified; inspect the full paper to establish its actual sensors, workflow and contribution.'),
('10.1109/ICCSP.2019.8697995','P1','Cart systems','Camera-plus-load-cell cart baseline, particularly for produce. Compare physical weighing arrangement, product classes and bill generation with NXTCart.'),
('10.1109/ISAECT64333.2024.10799859','P1','Cart systems','Whole-cart integration combining camera recognition, weighing and user interface. Distinguish produce pricing by weight from packaged-SKU weight verification.'),
('10.1109/JIOT.2017.2706698','P1','Cart systems','Secure shopping-system architecture and communication protocol prior art. Useful for system requirements and the security discussion; do not assume RFID solves product substitution.'),
('10.1109/ICOIACT67584.2025.11344991','P1','Retail vision','Very close methodological comparator: detection followed by embedding similarity for a changing product catalogue. Assess catalogue growth, reference count and evaluation splits.'),
('10.1109/JSEN.2022.3210699','P1','Retail vision','Multi-camera retail recognition and view-dependent appearance. Useful for camera placement and lookalike/occlusion discussion; its kiosk environment differs from a moving cart.'),
('10.1109/WCNC45663.2020.9120574','P1','Cart systems','iCart supplies an edge/cloud shopping-event baseline. Compare event handling, network dependency and placement of inference with the Pi-to-PC runtime.'),
('10.1109/ACCESS.2020.2986681','P1','Cart systems','Widely relevant RFID/Arduino/mobile billing baseline; cited in both supplied 2022 papers. Compare tag requirements and shopper workflow with barcode-first verification.'),
('10.1109/ICICICT54557.2022.9917860','P1','Cart systems','Supplied RP2: RFID cart with adding/removing items, display and ZigBee/IoT billing. Use for historical cart-system comparison.'),
('10.1109/ICSTSN53084.2022.9761346','P1','Cart systems','Supplied RP3: image processing/YOLO with RFID-assisted billing. Check exactly how its proposed counting and identification are tested before quoting effectiveness.'),
('10.1109/IISEC56263.2022.9998221','P2','Cart systems','Raspberry Pi/RFID cart comparator. Download to check its weight-based theft control, cost assumptions and communication arrangement.'),
('10.1109/ICECAA58104.2023.10212323','P2','Cart systems','Additional AI/IoT integration baseline. Only metadata/title verified in this pass; extract actual hardware and measured results after download.'),
('10.1109/ICICCS65191.2025.10984823','P2','Cart systems','RFID plus load-cell monitoring and billing. Compare independent checks and failure handling rather than treating a component list as equivalent performance.'),
('10.1109/ICWITE59797.2024.10503373','P2','Cart systems','Recent RFID/cloud billing design; useful for system-level literature comparison and product-data flow.'),
('10.1109/ICETT.2016.7873753','P2','Cart systems','Early theft-control cart comparator. Metadata verified; inspect the attack model and validation mechanism before characterizing security coverage.'),
('10.1109/ICICES.2014.7033996','P2','Cart systems','Historical RFID/ZigBee automated billing baseline. Helps establish that wireless cart billing predates the proposed project.'),
('10.1109/ICSGRC.2011.5991855','P3','Cart systems','Early multi-tag RFID auto-checkout. Useful background on automatic identification; lower priority than direct camera/weight cart comparisons.'),
('10.1109/JSEN.2016.2586101','P3','Cart systems','3S-cart covers modular sensing and shopper interaction. Its promotion/navigation focus is peripheral to billing integrity.'),
('10.1109/ACCESS.2025.3553854','P3','Cart systems','Broader AI cart context including navigation and forecasting. Include only if the paper discusses those adjacent capabilities; they are outside the current core scope.'),
('10.1109/ICCE-Asia67487.2025.11263715','P3','Cart systems','ROS 2 cart integration example using shopper-intent prediction. Useful systems context, but prediction/navigation should not be added to NXTCart claims.'),
('10.1109/ACCESS.2023.3297889','P3','Cart systems','Radar/sensor-fusion self-following cart. Background on adjacent cart research; its mobility problem differs from product verification.'),
('10.1109/ICACCI.2016.7732405','P2','Cart systems','RFID/cloud cart, web interface and anti-theft gates. Useful for separating on-cart billing, store services and exit checks.'),
('10.1109/ICEECE71300.2026.11709931','P2','Cart systems','Recent 2026 billing/anti-theft paper. Metadata verified only; download before citing its technical approach or results.'),
('10.1109/ICCBI68589.2026.11619726','P1','Cart systems','Very recent multimodal cart prior art. Metadata verified only; download to check the apparent barcode/weight/vision overlap and any real evaluation.'),
('10.1109/CVPRW56347.2022.00350','P1','Retail vision','DeepACO combines detection, tracking and counting for checkout video. Useful for temporal-event baselines; conveyor conditions differ from cart insertion.'),
('10.1109/CVPRW59228.2023.00562','P2','Retail vision','Checkout-video detection/tracking with image enhancement and synthetic training data. Useful for blur, counting and augmentation comparisons.'),
('10.1109/TMM.2020.3037502','P2','Retail vision','Automatic-checkout domain adaptation/distillation comparator. Relevant to the mismatch between clean reference photos and cluttered live views.'),
('10.1109/IVMSPW.2016.7528213','P2','Retail vision','Fine-grained retail recognition using visual/context information. Useful context for why near-identical SKUs remain difficult.'),
('10.1109/CVPR.2018.00474','P1','Methods and tracking','MobileNetV2 is the local feature extractor in the current code. Cite the original architecture and report pretrained weights, preprocessing and embedding extraction separately.'),
('10.1109/ICCV.2019.00140','P3','Methods and tracking','Optional lightweight backbone alternative for an accuracy/latency comparison. Cite only if evaluated or substantively discussed.'),
('10.1109/CVPR.2016.90','P3','Methods and tracking','ResNet is a standard feature-extractor baseline. It is not evidence that the current project uses a ResNet model.'),
('10.1109/CVPR.2016.91','P3','Methods and tracking','Original YOLO architecture paper, useful background when comparing detector-based cart literature. It does not document YOLOv8 or prove its use in NXTCart.'),
('10.1109/ICIP.2016.7533003','P2','Methods and tracking','SORT supplies a lightweight temporal association baseline. Evaluate scanned-object continuity and identity switches, rather than assuming general tracking equals custody proof.'),
('10.1109/ICIP.2017.8296962','P2','Methods and tracking','Deep SORT adds appearance-based association through occlusion. Its pretrained person association metric needs adaptation/evaluation for retail items.'),
('10.1109/5.554205','P2','Sensor fusion and reliability','Foundational sensor-fusion tutorial for describing evidence combination and uncertainty. General fusion theory does not establish independence of the cart sensors.'),
('10.1109/CVPR.2019.00537','P2','Datasets','SKU-110K supports dense product detection/counting. It is class-agnostic product detection, not a benchmark for verifying a specific retail SKU.'),
('10.1109/WACV.2019.00058','P2','Datasets','Hierarchical grocery dataset with natural images and semantic information. Useful for visual generalization; category recognition does not establish packaged-SKU substitution detection.'),
('10.1109/CVPR.2007.383486','P2','Datasets','GroZi-120 studies clean-training to in-store recognition. Useful historical support for the reference-to-live domain gap.'),
('10.1109/CVPR52688.2022.02057','P3','Datasets','Large e-commerce multimodal pretraining resource. Useful background for reference embeddings; web product images differ from cart camera crops.'),
('10.1007/s11432-022-3513-y','P1','Datasets','RPC is a core fine-grained checkout benchmark. Use its official splits and shopping-list metrics for recognition/counting baselines; add real cart sensor data separately.'),
('10.1007/978-3-030-01249-6_35','P2','Datasets','D2S provides instance masks and controlled visual variation for grocery checkout. Useful for occlusion/segmentation analysis, not event timing or weight validation.'),
('10.1016/j.patcog.2023.109519','P3','Datasets','MEP-3M is a large image-text e-commerce dataset with fine-grained subsets. Confirm the particular checkout subset and task rather than assuming all samples are cart data.'),
('10.3389/fbuil.2020.568372','P1','Sensor fusion and reliability','FAIM is strong open prior art on combining vision, weight and location in retail inventory. Compare fusion assumptions and failure cases, noting shelf monitoring differs from a cart.'),
('10.1145/3360322.3360834','P1','Sensor fusion and reliability','Full AIM3S research paper on multimodal retail sensing. Use this DOI for the 135-144 page paper, not the separate two-page demonstration DOI.'),
('10.1016/j.matpr.2017.12.367','P2','Cart systems','Weight-sensor cart and rack system comparator. Inspect mechanical mounting, calibration and mass tolerance experiments for the hardware section.'),
('10.1016/j.procs.2016.03.107','P2','Cart systems','Open RFID/ZigBee billing and anti-theft baseline also cited by supplied papers. Separate design promises from measured validation.'),
('10.1016/j.imavis.2019.03.005','P1','Surveys','Major retail-vision survey with a taxonomy and many references. Use it to structure related work and discover further original sources.'),
('10.1155/2020/8875910','P1','Surveys','Open survey of retail deep-learning challenges and techniques. Read alongside newer sources so the literature review is not limited to pre-2021 methods.'),
('10.1016/j.eswa.2021.115942','P1','Sensor fusion and reliability','Direct expected-product verification prior art using OCR, classification and conformal prediction; addresses barcode switching and missed scans. Especially useful for defining the verification task.'),
('10.1049/cvi2.12302','P1','Retail vision','Direct class-verification comparator for self-checkout. Compare centre-based verification with multiple reference-image comparisons and report inference cost.'),
('10.1016/j.inffus.2011.08.001','P2','Sensor fusion and reliability','Broad multisensor-fusion review. Use to justify the selected fusion level and discuss uncertain, missing or conflicting evidence.'),
('10.1126/scirobotics.abm6074','P1','Systems','ROS 2 design and architecture paper. Supports the distributed implementation section; record actual middleware, QoS and network settings in your experiments.'),
('10.1007/978-3-031-20047-2_1','P2','Methods and tracking','ByteTrack is an additional association baseline. Useful when evaluating detection dropouts; accepting weak detections must not silently certify an uncertain product journey.'),
('10.1007/s11263-020-01375-2','P2','Methods and tracking','HOTA separates detection and association quality. Supplement with cart-specific event correctness, substitution acceptance and duplicate-billing metrics.'),
]

catalog = []
for doi, priority, group, reason in SELECTION:
    m = metadata[doi.lower()]
    title = html.unescape(': '.join(m.get('title', []) + m.get('subtitle', [])))
    primary = m.get('resource', {}).get('primary', {}).get('URL', 'https://doi.org/' + doi)
    match = re.search(r'ieeexplore\.ieee\.org/document/(\d+)', primary)
    pub = m.get('published-print') or m.get('published') or m.get('published-online')
    catalog.append(dict(title=title, year=pub['date-parts'][0][0], priority=priority, group=group,
                        doi=m['DOI'], ieee_id=match.group(1) if match else '', url=primary.replace('http://ieeexplore','https://ieeexplore'),
                        reason=reason, kind='paper', metadata_source='https://api.crossref.org/works/'+m['DOI'],
                        evidence='Publisher-deposited metadata verified; full text pending', access='Check publisher/institutional access; PDF access not tested',
                        authors=m.get('author', []), venue='; '.join(m.get('container-title', [])), raw=m,
                        already_have='', alternate_url=''))

def manual(title, year, priority, group, reason, url, authors='', kind='paper', identifier='', access='Open landing page; check download terms', venue='', evidence='Primary abstract/landing page checked'):
    names = []
    for name in [n.strip() for n in authors.split(' and ') if n.strip()]:
        if kind in ['paper', 'book'] and name != 'others':
            parts = name.rsplit(' ', 1)
            names.append(dict(given=parts[0], family=parts[1]) if len(parts) == 2 else dict(family=name))
        else:
            names.append(dict(literal=name))
    catalog.append(dict(title=title, year=year, priority=priority, group=group, reason=reason, url=url,
                        authors=names, kind=kind, ieee_id='', doi='', identifier=identifier,
                        access=access, venue=venue, evidence=evidence, metadata_source=url,
                        already_have='', alternate_url='', raw={}))

manual('EfficientNet: Rethinking Model Scaling for Convolutional Neural Networks',2019,'P3','Methods and tracking','Optional accuracy/compute backbone baseline. Record input resolution and runtime if evaluated.', 'https://proceedings.mlr.press/v97/tan19a.html','Mingxing Tan and Quoc V. Le',identifier='PMLR 97:6105-6114',venue='Proceedings of the 36th International Conference on Machine Learning')
manual('Learning Transferable Visual Models From Natural Language Supervision',2021,'P2','Methods and tracking','CLIP foundation for image-text embeddings and a possible alternative to the local embedding backend. Its generic zero-shot performance does not prove SKU-level verification.', 'https://proceedings.mlr.press/v139/radford21a.html','Alec Radford and Jong Wook Kim and Chris Hallacy and Aditya Ramesh and Gabriel Goh and Sandhini Agarwal and Girish Sastry and Amanda Askell and Pamela Mishkin and Jack Clark and Gretchen Krueger and Ilya Sutskever',identifier='PMLR 139:8748-8763',venue='Proceedings of the 38th International Conference on Machine Learning')
manual('DINOv2: Learning Robust Visual Features without Supervision',2023,'P2','Methods and tracking','Alternative general-purpose visual embeddings for a controlled backend comparison. This entry identifies the arXiv version, not a verified final proceedings version.', 'https://arxiv.org/abs/2304.07193','Maxime Oquab and others',identifier='arXiv:2304.07193',venue='arXiv preprint')
manual('On Calibration of Modern Neural Networks',2017,'P1','Sensor fusion and reliability','Explains why model confidence needs calibration. A cosine similarity or model-generated confidence score is not automatically a probability of correct verification.', 'https://proceedings.mlr.press/v70/guo17a.html','Chuan Guo and Geoff Pleiss and Yu Sun and Kilian Q. Weinberger',identifier='PMLR 70:1321-1330',venue='Proceedings of the 34th International Conference on Machine Learning')
manual('Selective Classification for Deep Neural Networks',2017,'P1','Sensor fusion and reliability','Theory for rejecting uncertain predictions and reporting risk against coverage. Useful for MATCH versus RETRY behavior; cart-specific guarantees still require suitable assumptions and measurements.', 'https://arxiv.org/abs/1705.08500','Yonatan Geifman and Ran El-Yaniv',identifier='arXiv:1705.08500; NeurIPS 2017',venue='Advances in Neural Information Processing Systems 30')
manual('What Matters for Grocery Product Retrieval with Open Source Vision Language Models',2026,'P1','Retail vision','Current SKU-level retrieval comparison directly relevant to an AI-versus-local-backend study. Use the verified May 2026 arXiv version; do not cite a future-dated proceedings record.', 'https://arxiv.org/abs/2605.18029','Emmanuel G. Maminta and Rowel O. Atienza',identifier='arXiv:2605.18029',venue='arXiv preprint')
manual('Training with Product Digital Twins for AutoRetail Checkout',2023,'P2','Datasets','Synthetic retail training data and user-viewpoint bias. Useful for future data generation; distinguish synthetic results from real-cart validation.', 'https://arxiv.org/abs/2308.09708','Yue Yao and Xinyu Tian and Zheng Tang and Sujit Biswas and Huan Lei and Tom Gedeon and Liang Zheng',identifier='arXiv:2308.09708',venue='arXiv preprint')
manual('The Freiburg Groceries Dataset',2016,'P2','Datasets','Real grocery images across viewpoints, lighting and clutter. Broad food categories do not test discrimination between visually similar branded SKUs.', 'https://arxiv.org/abs/1611.05799','Philipp Jund and Nichola Abdo and Andreas Eitel and Wolfram Burgard',identifier='arXiv:1611.05799',venue='arXiv preprint')
manual('AI City Challenge 2023: Track 4 data and evaluation',2023,'P2','Datasets','Multi-class product counting and recognition in checkout video. Review event definitions and data licenses before reuse.', 'https://www.aicitychallenge.org/2023-data-and-evaluation/','AI City Challenge',kind='dataset documentation',identifier='AI City Challenge 2023 Track 4',access='Dataset request/license may be required')

manual('Computer Vision: Algorithms and Applications',2022,'P2','Books','Reference for imaging, feature matching, tracking and camera setup. Cite the specific method/chapter actually used.', 'https://szeliski.org/Book/','Richard Szeliski',kind='book',identifier='2nd edition; ISBN 9783030343712; DOI 10.1007/978-3-030-34372-9',venue='Springer',access='Author offers a personal-use PDF through a form')
manual('Deep Learning',2016,'P2','Books','Background on CNNs, representation learning and regularization. Prefer original method papers for MobileNet and experiment-specific claims.', 'https://www.deeplearningbook.org/','Ian Goodfellow and Yoshua Bengio and Aaron Courville',kind='book',identifier='ISBN 9780262035613',venue='MIT Press',access='Free official online reading')
manual('Pattern Recognition and Machine Learning',2006,'P2','Books','Background on Bayesian reasoning, classification and probabilistic inference. Useful for a principled uncertainty discussion.', 'https://link.springer.com/book/9780387310732','Christopher M. Bishop',kind='book',identifier='ISBN 9780387310732',venue='Springer',access='Check publisher/library access')
manual('RFID Handbook: Fundamentals and Applications in Contactless Smart Cards, Radio Frequency Identification and Near-Field Communication',2010,'P3','Books','Technical background on RFID limitations and infrastructure costs when comparing tagged-item alternatives.', 'https://onlinelibrary.wiley.com/doi/book/10.1002/9780470665121','Klaus Finkenzeller',kind='book',identifier='3rd edition; ISBN 9780470695067; DOI 10.1002/9780470665121',venue='Wiley',access='Check publisher/library access')
manual('Handbook of Multisensor Data Fusion: Theory and Practice',2009,'P2','Books','Reference on fusion architectures, uncertainty and association. Editors are Martin E. Liggins II, David L. Hall and James Llinas.', 'https://www.routledge.com/Handbook-of-Multisensor-Data-Fusion-Theory-and-Practice-Second-Edition/Liggins-II-Hall-Llinas/p/book/9781315219486','',kind='book',identifier='2nd edition; print ISBN 9781420053081',venue='CRC Press',access='Check publisher/library access')
manual('Introduction to Embedded Systems: A Cyber-Physical Systems Approach',2016,'P2','Books','Models of state, timing, concurrency and physical interaction for the Pi/Arduino/sensor system.', 'https://mitpress.mit.edu/9780262533812/introduction-to-embedded-systems/','Edward Ashford Lee and Sanjit Arunkumar Seshia',kind='book',identifier='2nd edition; ISBN 9780262533812',venue='MIT Press',access='Publisher page; check available formats')

manual('ROS 2 Jazzy: About Quality of Service settings','living','P1','Engineering documentation','Primary reference for image-stream delivery, reliability, deadlines and stale-evidence handling. Official docs URL encountered an automated access block; an indexed ROS documentation mirror was inspected.', 'https://docs.ros.org/en/jazzy/Concepts/Intermediate/About-Quality-of-Service-Settings.html','Open Robotics',kind='documentation',identifier='ROS 2 Jazzy',evidence='Official URL identified; indexed ROS documentation checked')
manual('ROS 2 Jazzy: Setting up security','living','P2','Engineering documentation','DDS-Security setup for deployment discussion. Security mechanisms must be configured and tested; ordinary ROS messaging alone does not establish authenticated communications.', 'https://docs.ros.org/en/jazzy/Tutorials/Advanced/Security/Introducing-ros2-security.html','Open Robotics',kind='documentation',identifier='ROS 2 Jazzy / sros2',evidence='Official URL identified; indexed ROS documentation checked')
manual('HX711: 24-Bit Analog-to-Digital Converter for Weigh Scales','undated','P1','Engineering documentation','Manufacturer datasheet for gain, sample-rate options and electrical behavior. ADC bit depth is not the accuracy of the completed weighing mechanism.', 'https://cdn.sparkfun.com/assets/b/f/5/a/e/hx711F_EN.pdf','Avia Semiconductor',kind='datasheet',identifier='HX711',access='Public manufacturer datasheet hosted by SparkFun')
manual('HX711 Arduino library','living','P1','Engineering documentation','Actual scale library named by the setup guide; documents calibration, tare, gain and acquisition behavior. Pin the library version/commit used in experiments.', 'https://github.com/bogde/HX711','Bogdan Necula and contributors',kind='software',identifier='bogde/HX711',access='Public source repository')
manual('GS1 General Specifications','2026','P1','Engineering documentation','Authoritative barcode/identifier specification for product-catalog mapping. A valid GTIN identifies the declared product; it does not prove the physical item matches.', 'https://www.gs1ie.org/standards/resources/general-specifications/','GS1',kind='standard',identifier='Release 26, ratified January 2026')
manual('OpenCV: Deep Learning in OpenCV','living','P1','Engineering documentation','Implementation reference for the ONNX/OpenCV DNN inference path in this code. Record the actual OpenCV version, backend and target.', 'https://github.com/opencv/opencv/wiki/Deep-Learning-in-OpenCV','OpenCV',kind='documentation',identifier='OpenCV DNN')
manual('pyzbar: barcode and QR decoding','living','P1','Engineering documentation','Actual Python barcode/QR decoding dependency. Record pyzbar and native ZBar versions and test lighting, motion and duplicate scans.', 'https://github.com/NaturalHistoryMuseum/pyzbar','Natural History Museum and contributors',kind='software',identifier='NaturalHistoryMuseum/pyzbar',access='Public source repository')
manual('Arduino: A guide to EEPROM','living','P2','Engineering documentation','Implementation reference for persistent scale calibration. Verify behavior on the actual Arduino board and core.', 'https://github.com/arduino/docs-content/blob/main/content/learn/03.programming/07.eeprom-guide/eeprom-guide.md','Arduino',kind='documentation',identifier='Arduino EEPROM guide')
manual('NPCI: UPI Frequently Asked Questions','living','P2','Engineering documentation','Payment-system context for the UPI QR interface. The cart must distinguish displaying a payment request from verified payment completion.', 'https://www.npci.org.in/what-we-do/upi/faqs','National Payments Corporation of India',kind='documentation',identifier='UPI FAQ')
manual('Caper Carts: official product overview','living','P3','Industry context','Commercial context for cart vision and weight verification. Treat vendor descriptions as product claims, not peer-reviewed evidence of accuracy or loss reduction.', 'https://company.instacart.com/enterprise-platform/connected-stores/caper-carts','Instacart',kind='industry page',identifier='Caper Carts')
manual('Amazon: 5 ways the newest Dash Cart can save time and money',2026,'P3','Industry context','January 2026 commercial context for camera/weight/sensor-fusion carts. Do not use vendor claims as an independent experimental baseline.', 'https://www.aboutamazon.com/news/retail/amazon-redesigned-dash-cart-whole-foods-market','Amazon',kind='industry page',identifier='Amazon Dash Cart; 2026-01-07')

# Appended to keep existing reference numbers stable after citation chasing.
manual('An IOT Based Smart Shopping Cart for Smart Shopping',2018,'P1','Cart systems','RP3 reference [1]. Important historical cart comparator. The publisher added two authors in a 2021 correction; use the corrected five-author citation.', 'https://link.springer.com/chapter/10.1007/978-981-10-9059-2_33','Srinidhi Karjol and Anusha K. Holla and C. B. Abhilash and P. V. Amrutha and Y. V. Manohar',identifier='DOI 10.1007/978-981-10-9059-2_33; CCIP 2017 proceedings published 2018',venue='Cognitive Computing and Information Processing; Communications in Computer and Information Science 801',access='Check Springer institutional access')
manual('An IoT-Based Smart Shopping Cart Using the Contemporary Barcode Scanner',2018,'P1','Cart systems','Especially close earlier barcode-first design combining weight, product images and cloud inventory. Read before presenting the barcode/weight/camera combination as novel.', 'https://link.springer.com/chapter/10.1007/978-981-10-8575-8_6','V. N. Prithvish and Shraddha Agrawal and John Sahaya Rani Alex',identifier='DOI 10.1007/978-981-10-8575-8_6; pages 45-58',venue='Intelligent Embedded Systems; Lecture Notes in Electrical Engineering 492',access='Check Springer institutional access')
manual('Smart Shopping Cart for Automated Billing Purpose using Wireless Sensor Networks',2013,'P1','Cart systems','Early directly relevant cart system with load-cell and image-comparison verification. Its actual venue is IARIA SENSORCOMM, despite some later bibliographies mislabeling it IEEE.', 'https://personales.upv.es/thinkmind/SENSORCOMM/SENSORCOMM_2013/sensorcomm_2013_7_30_10155.html','Udita Gangwal and Sanchita Roy and Jyotsna Bapat',identifier='SENSORCOMM 2013; pages 168-172; ISBN 9781612082967',venue='SENSORCOMM 2013, IARIA',access='Public conference paper; publisher PDF also linked in source notes')
catalog[-1]['alternate_url']='https://personales.upv.es/thinkmind/dl/conferences/sensorcomm/sensorcomm_2013/sensorcomm_2013_7_30_10155.pdf'
for r in catalog[-3:-1]:
    doi = r['identifier'].split('DOI ')[1].split(';')[0]
    r['doi']=doi
    r['metadata_source']='https://api.crossref.org/works/'+doi
    r['raw']=metadata[doi.lower()]
    r['evidence']='Publisher metadata verified; publisher abstract and citation checked'

by_doi = {r['doi'].lower():r for r in catalog if r['doi']}
supplied = {'10.1109/icctit68197.2025.11406732':'RP1.pdf','10.1109/icicict54557.2022.9917860':'RP2.pdf','10.1109/icstsn53084.2022.9761346':'RP3.pdf'}
for doi, filename in supplied.items():
    by_doi[doi]['already_have'] = str(Path('C:/Users/ADMIN/Downloads') / filename)
    by_doi[doi]['evidence'] = 'Supplied full text reviewed; DOI/title also verified in publisher metadata'
    by_doi[doi]['access'] = 'Already supplied locally'

# These primary-source pages/abstracts were inspected in this research pass.
evidence_urls = {
'9060814':'https://doi.org/10.1109/ACCESS.2020.2986681',
'7501897':'https://people.cs.nycu.edu.tw/~wangyc/publications/journals/j028-sensors16-3Scart.pdf',
'9120574':'https://scholar.nycu.edu.tw/en/publications/smart-shopping-carts-based-on-mobile-computing-and-deep-learning-/',
'8697995':'https://www.amrita.edu/publication/deep-learning-based-automated-billing-cart/',
'10799859':'https://faculty.pmu.edu.sa/pmufaculties/Details/salhuwaidi',
'11344991':'https://ieeexplore.ieee.org/abstract/document/11344991',
'9912319':'https://ieee-sensorsalert.org/articles/a-retail-object-classification-method-using-multiple-cameras-for-vision-based-unmanned-kiosks/',
'10937485':'https://ieeexplore.ieee.org/abstract/document/10937485',
'11263715':'https://doi.org/10.1109/ICCE-Asia67487.2025.11263715',
'10984823':'https://ieeexplore.ieee.org/document/10984823/',
'10503373':'https://doi.org/10.1109/ICWITE59797.2024.10503373',
'7732405':'https://research.nu.edu.kz/en/publications/rfid-cloud-smart-cart-system/',
'9857462':'https://openaccess.thecvf.com/content/CVPR2022W/AICity/papers/Pham_DeepACO_A_Robust_Deep_Learning-Based_Automatic_Checkout_System_CVPRW_2022_paper.pdf',
'10208503':'https://openaccess.thecvf.com/content/CVPR2023W/AICity/html/Pham_Improving_Deep_Learning-Based_Automatic_Checkout_System_Using_Image_Enhancement_Techniques_CVPRW_2023_paper.html',
'9257112':'https://isrc.iscas.ac.cn/zhanglibo/pdfs/2020/IEEE_Transactions_on_Multimedia.pdf',
'7528213':'https://research.sabanciuniv.edu/id/eprint/30357/',
'8296962':'https://ieeexplore.ieee.org/abstract/document/8296962/authors',
'554205':'https://researchconnect.buffalo.edu/en/publications/an-introduction-to-multisensor-data-fusion/',
'8953496':'https://openaccess.thecvf.com/content_CVPR_2019/html/Goldman_Precise_Detection_in_Densely_Packed_Scenes_CVPR_2019_paper.html',
'4270484':'https://escholarship.org/uc/item/7w80w06s',
}
for r in catalog:
    if r['ieee_id'] in evidence_urls and not r['already_have']:
        r['alternate_url'] = evidence_urls[r['ieee_id']]
        r['evidence'] = ('Publisher metadata verified; primary abstract/landing page checked' if r['ieee_id'] != '9060814' else 'Publisher metadata verified; full text pending')
    if r['doi'] == '10.3389/fbuil.2020.568372':
        r['alternate_url']='https://www.frontiersin.org/journals/built-environment/articles/10.3389/fbuil.2020.568372/full'
        r['evidence']='Publisher metadata verified; primary abstract/landing page checked'
        r['access']='Open access publisher article'
    if r['doi'] == '10.1016/j.imavis.2019.03.005':
        r['alternate_url']='https://home.iitj.ac.in/~bikash/pdfs/Product%20Detection%20Survey%20Paper%20IVC%20PP.pdf'
        r['evidence']='Publisher metadata verified; author/publisher abstract checked'
    if r['doi'] == '10.1155/2020/8875910':
        r['alternate_url']='https://pmc.ncbi.nlm.nih.gov/articles/PMC7676964/'
        r['evidence']='Publisher metadata verified; primary abstract/landing page checked'
        r['access']='Open access publisher article; PMC full-text copy'
    if r['doi'] == '10.1016/j.eswa.2021.115942':
        r['alternate_url']='https://his.diva-portal.org/smash/get/diva2%3A1606938/FULLTEXT01.pdf'
        r['evidence']='Publisher metadata verified; publisher abstract checked'
    if r['doi'] == '10.1049/cvi2.12302':
        r['evidence']='Publisher metadata verified; publisher abstract checked'
        r['access']='Open access publisher article'
    if r['doi'] == '10.1007/s11432-022-3513-y':
        r['alternate_url']='https://rpc-dataset.github.io/'
        r['evidence']='Publisher metadata and official dataset page checked'
    if r['doi'] == '10.1007/978-3-030-01249-6_35':
        r['alternate_url']='https://www.mvtec.com/research-teaching/datasets/mvtec-d2s'
        r['evidence']='Publisher metadata and official dataset page checked'
    if r['doi'] == '10.1016/j.patcog.2023.109519':
        r['alternate_url']='https://github.com/ChenDelong1999/MEP-3M'
        r['evidence']='Publisher metadata and author dataset page checked'
    if r['ieee_id'] in ['9857462','10208503']:
        r['access']='Open CVF author PDF/page available; Xplore access not tested'

for i,r in enumerate(catalog,1):
    r['ref'] = f'R{i:02d}'
    r['checked_date'] = DATE
    if r['kind']=='book' and 'DOI ' in r.get('identifier',''):
        r['doi']=r['identifier'].split('DOI ')[1]

def clean(s):
    return str(s).replace('|','\\|').replace('\n',' ')

def table(rows, detailed=False):
    header = '| Ref | Priority | Year | Title | IEEE document ID / other ID |'
    sep = '|---|---|---|---|---|'
    if detailed:
        header+=' Why it matters |'; sep+='---|'
    lines=[header,sep]
    for r in rows:
        ident = f"[{r['ieee_id']}]({r['url']})" if r['ieee_id'] else r.get('identifier') or f"[DOI](https://doi.org/{r['doi']})"
        have = ' **Already have**' if r['already_have'] else ''
        line=f"| {r['ref']} | {r['priority']} | {r['year']} | [{clean(r['title'])}]({r['url']}){have} | {ident} |"
        if detailed: line+=f" {clean(r['reason'])} |"
        lines.append(line)
    return '\n'.join(lines)

ieee=[r for r in catalog if r['ieee_id']]
counts=Counter(r['kind'] for r in catalog)
guide = f'''# NXTCart research and download guide

Prepared: 12 October 2026. Coverage: **{len(catalog)} selected resources**, including **{len(ieee)} verified IEEE Xplore document IDs**, with three papers already supplied. This is a broad curated research base, not a claim to have found every publication or completed a systematic review.

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

{table([r for r in catalog if r['ref'] in ['R01','R02','R03','R04','R05','R06','R07','R08','R09','R10','R26','R27','R45','R46','R49','R50','R51','R52','R83','R84','R85']],True)}

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
'''
(ROOT/'README.md').write_text(guide,encoding='utf-8')

ieee_md=f'''# IEEE Xplore download queue

Checked 12 October 2026. **{len(ieee)} exact-title/DOI document IDs verified from IEEE publisher-deposited metadata.** P1 first, P2 supporting, P3 optional. Three entries are already supplied.

{table(ieee,True)}

## DOIs and verification

'''
for r in ieee:
    ieee_md+=f"- **{r['ref']} / {r['ieee_id']}**: DOI [{r['doi']}](https://doi.org/{r['doi']}); [metadata]({r['metadata_source']}). {r['evidence']}.\n"
(ROOT/'IEEE_DOWNLOAD_QUEUE.md').write_text(ieee_md,encoding='utf-8')

catalogue=f'''# Annotated NXTCart resource catalogue

Checked: 12 October 2026. {len(catalog)} resources; {len(ieee)} have IEEE document IDs. Relevance notes are assessments for NXTCart, not endorsements of paper quality or claims of implementation. Read the full text before extracting quantitative results.

'''
groups=list(dict.fromkeys(r['group'] for r in catalog))
for group in groups:
    catalogue+=f'## {group}\n\n'
    for r in [x for x in catalog if x['group']==group]:
        names='; '.join(x.get('literal') or ' '.join(filter(None,[x.get('given'),x.get('family')])) for x in r['authors'])
        ids = ('IEEE document ID **'+r['ieee_id']+'**; ' if r['ieee_id'] else '')
        if r['doi']: ids+=f"DOI [{r['doi']}](https://doi.org/{r['doi']})"
        if r.get('identifier'): ids+=('; ' if ids else '')+r['identifier']
        catalogue+=f"### {r['ref']} - {r['title']}\n\n**{r['priority']} | {r['year']} | {r['kind']}**\n\n"
        if names: catalogue+=f"Authors/organization: {names}.\n\n"
        if r['venue']: catalogue+=f"Publication: {r['venue']}.\n\n"
        catalogue+=f"Identifiers: {ids or 'Primary URL; no IEEE document ID'}.\n\nRelevance: {r['reason']}\n\n"
        catalogue+=f"[Primary source]({r['url']})"
        if r['alternate_url'] and r['alternate_url']!=r['url']: catalogue+=f" | [Author/open/alternate source]({r['alternate_url']})"
        if r['metadata_source']!=r['url']: catalogue+=f" | [Publisher-deposited metadata]({r['metadata_source']})"
        catalogue+=f"\n\nVerification: {r['evidence']}. Access: {r['access']}.\n\n"
        if r['already_have']: catalogue+=f"Already supplied: `{r['already_have']}`.\n\n"
(ROOT/'ANNOTATED_CATALOGUE.md').write_text(catalogue,encoding='utf-8')

idlines=['IEEE Xplore IDs checked 2026-10-12','P1=new first-priority downloads; P2=supporting; P3=optional','']
for priority in ['P1','P2','P3']:
    idlines += [priority+' - NOT ALREADY SUPPLIED']+[r['ieee_id'] for r in ieee if r['priority']==priority and not r['already_have']]+['']
idlines += ['ALREADY SUPPLIED (RP1, RP2, RP3)','11406732','9917860','9761346','', 'TITLE KEY']
idlines += [f"{r['ieee_id']} | {r['ref']} | {r['year']} | {r['title']}" for r in ieee]
(ROOT/'IEEE_DOCUMENT_IDS.txt').write_text('\n'.join(idlines)+'\n',encoding='utf-8')

def esc(s):
    return str(s).replace('\\',r'\textbackslash{}').replace('&',r'\&').replace('%',r'\%').replace('#',r'\#').replace('_',r'\_')

bib=['% NXTCart discovery bibliography; checked 2026-10-12. Read/select before citing.','% Metadata-only entries are identified in notes; original PDFs remain authoritative.','']
for r in catalog:
    raw=r['raw']; typ='book' if r['kind']=='book' else 'article' if raw.get('type')=='journal-article' else 'incollection' if raw.get('type')=='book-chapter' else 'inproceedings' if raw.get('type')=='proceedings-article' or 'PMLR' in r.get('identifier','') or 'NeurIPS' in r.get('identifier','') else 'misc'
    fields={'title':'{'+esc(r['title'])+'}'}
    if r['authors']:
        fields['author']=' and '.join(('others' if x['literal']=='others' else '{'+esc(x['literal'])+'}') if 'literal' in x else esc((x.get('family','')+', '+x.get('given','')).strip(', ')) for x in r['authors'])
    if isinstance(r['year'],int): fields['year']=str(r['year'])
    if r['kind']=='book' and 'Handbook of Multisensor' in r['title']:
        fields['editor']='Liggins II, Martin E. and Hall, David L. and Llinas, James'
    if r['venue']: fields['journal' if typ=='article' else 'publisher' if typ=='book' else 'booktitle' if typ in ('inproceedings','incollection') else 'howpublished']=esc(r['venue'])
    for key in ['volume','issue','page']:
        if raw.get(key): fields[{'issue':'number','page':'pages'}.get(key,key)]=str(raw[key]).replace('-', '--') if key=='page' else str(raw[key])
    if r['doi']: fields['doi']=r['doi']
    fields['url']=r['url']
    fields['urldate']=DATE
    if r['kind']=='book':
        ident=r.get('identifier',''); isbn=re.search(r'ISBN (\d+)',ident)
        if isbn: fields['isbn']=isbn.group(1)
        if '2nd edition' in ident: fields['edition']='2'
        if '3rd edition' in ident: fields['edition']='3'
    if 'arXiv:' in r.get('identifier',''):
        fields['eprint']=r['identifier'].split('arXiv:')[1].split(';')[0]
        fields['archivePrefix']='arXiv'
    fields['note']=esc(f"{r['ref']}; {r['priority']}; "+(f"IEEE document ID {r['ieee_id']}; " if r['ieee_id'] else '')+r['evidence'])
    bib += ['@'+typ+'{NXTCart'+r['ref']+',']+['  '+k+' = {'+v+'},' for k,v in fields.items()]+['}','']
(ROOT/'nxtcart_references.bib').write_text('\n'.join(bib),encoding='utf-8')

public=[{k:v for k,v in r.items() if k!='raw'} for r in catalog]
(ROOT/'resource_catalogue.json').write_text(json.dumps(public,ensure_ascii=False,indent=2),encoding='utf-8')
assert len(set(r['ref'] for r in catalog))==len(catalog)
assert len(set(r['ieee_id'] for r in ieee))==len(ieee)
assert all(metadata[r['doi'].lower()] for r in ieee)
assert len([r for r in ieee if r['already_have']])==3
print(json.dumps({'resources':len(catalog),'ieee_ids':len(ieee),'by_kind':dict(counts),'priority':dict(Counter(r['priority'] for r in catalog)),'metadata_only_ieee':[r['ieee_id'] for r in ieee if 'full text pending' in r['evidence']]},indent=2))
