"""Read public Crossref metadata; no paper PDFs or credentials are downloaded."""
import concurrent.futures
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOIS = '''
10.1109/ICCTIT68197.2025.11406732
10.1109/ICICICT54557.2022.9917860
10.1109/ICSTSN53084.2022.9761346
10.1109/ACCESS.2020.2986681
10.1109/JSEN.2016.2586101
10.1109/WCNC45663.2020.9120574
10.1109/ICCSP.2019.8697995
10.1109/ISAECT64333.2024.10799859
10.1109/ICOIACT67584.2025.11344991
10.1109/JSEN.2022.3210699
10.1109/TMM.2020.3037502
10.1109/JIOT.2017.2706698
10.1109/ICACCM61117.2024.11059075
10.1109/ACCESS.2025.3553854
10.1109/ICCE-Asia67487.2025.11263715
10.1109/ICWITE59797.2024.10503373
10.1109/ICETT.2016.7873753
10.1109/IVMSPW.2016.7528213
10.1109/ICSGRC.2011.5991855
10.1109/ACCESS.2023.3297889
10.1016/j.imavis.2019.03.005
10.1155/2020/2362410
10.1007/s11432-022-3513-y
10.1109/CVPR.2018.00474
10.1109/ICCV.2019.00140
10.1109/CVPR.2016.90
10.1109/CVPR.2016.91
10.1109/ICIP.2016.7533003
10.1109/JPROC.1997.554205
10.1016/j.inffus.2011.08.001
10.1126/scirobotics.abm6074
'''.strip().splitlines()

TITLES = [
 'Fast and Low-Cost, Wireless Controlled Smart Shopping Cart with Raspberry Pi and RFID Technology',
 'Advanced Smart Shopping Cart with Integration of AI and IoT',
 'RFID based Smart Trolley Billing System using IoT',
 'DeepACO: A Robust Deep Learning-Based Automatic Checkout System',
 'Improving Deep Learning-Based Automatic Checkout System Using Image Enhancement Techniques',
 'A Hierarchical Grocery Store Image Dataset with Visual and Semantic Labels',
 'Freiburg Groceries Dataset',
 'Precise Detection in Densely Packed Scenes',
 'Recognizing Groceries in Situ Using in Vitro Training Data',
 'M5Product: Self-harmonized Contrastive Learning for E-commercial Multi-modal Pretraining',
 'FAIM: Vision and Weight Sensing Fusion Framework for Autonomous Inventory Monitoring in Convenience Stores',
 'AIM3S: Autonomous Inventory Monitoring through Multi-Modal Sensing for Cashier-Less Convenience Stores',
 'Smart Cart with Automatic Billing, Product Information, Product Recommendation Using RFID & Zigbee with Anti-Theft',
 'Design and Development of Weight Sensors Based Smart Shopping Cart and Rack System for Shopping Malls',
 'HOTA: A Higher Order Metric for Evaluating Multi-object Tracking',
 'Computer Vision: Algorithms and Applications',
 'Pattern Recognition and Machine Learning',
 'RFID Handbook: Fundamentals and Applications in Contactless Smart Cards, Radio Frequency Identification and Near-Field Communication',
]

def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'NXTCart-Literature-Research/1.0 (public metadata verification)'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                return json.load(response)['message']
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)

def fetch(task):
    kind, value = task
    try:
        if kind == 'doi':
            m = get('https://api.crossref.org/works/' + urllib.parse.quote(value, safe='/'))
            return {'query': value, 'kind': kind, 'record': m}
        m = get('https://api.crossref.org/works?' + urllib.parse.urlencode({'query.title': value, 'rows': 3}))
        return {'query': value, 'kind': kind, 'candidates': m['items']}
    except Exception as exc:
        return {'query': value, 'kind': kind, 'error': str(exc)}

if __name__ == '__main__':
    tasks = [('doi', x) for x in DOIS] + [('title', x) for x in TITLES]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        for result in pool.map(fetch, tasks):
            results.append(result)
            records = [result['record']] if 'record' in result else result.get('candidates', [])
            print(json.dumps({'query': result['query'], 'error': result.get('error'), 'matches': [
                {'title': r.get('title'), 'doi': r.get('DOI'), 'year': r.get('published'), 'primary': r.get('resource')}
                for r in records]}, ensure_ascii=False), flush=True)
    (ROOT / 'crossref_metadata.json').write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
