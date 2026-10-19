import concurrent.futures
import json
from fetch_metadata import ROOT, fetch

DOIS = '''
10.1109/JPROC.1997.554205
10.1155/2020/2362410
10.1109/ICKECS70176.2026.11527873
10.1145/3360322.3360834
10.1007/978-3-030-01249-6_35
10.1016/j.patcog.2023.109519
10.1109/AVSS.2017.8078516
10.1007/s11263-020-01375-2
10.1007/978-3-031-20047-2_1
10.1007/978-3-030-34372-9
10.1002/9780470665121
10.1109/ICICES.2014.7033996
10.1049/cvi2.12302
'''.strip().splitlines()
TITLES = [
 'Product verification using OCR classification and Mondrian conformal prediction',
 'RFID-Cloud smart cart system',
 'The Smart Cart with Automatic Billing and Anti-Theft',
 'Multi-Modal Product Recognition and In-Store Navigation using an Intelligent Shopping Cart',
 'Training with Product Digital Twins for AutoRetail Checkout',
]
if __name__ == '__main__':
    results=[]
    tasks=[('doi',d) for d in DOIS]+[('title',t) for t in TITLES]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(fetch,tasks):
            results.append(result)
            records=[result['record']] if 'record' in result else result.get('candidates',[])
            print(json.dumps({'query':result['query'],'error':result.get('error'),'matches':[
                {'title':r.get('title'),'doi':r.get('DOI'),'year':r.get('published'),'primary':r.get('resource')} for r in records]},ensure_ascii=False),flush=True)
    (ROOT/'crossref_supplement.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
