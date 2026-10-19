from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen
from PIL import Image, ImageOps, ImageDraw

ROOT=Path(__file__).resolve().parent
ASSETS=ROOT/'assets'
ASSETS.mkdir(parents=True,exist_ok=True)
chapters={
 'writer':('GS24802-GettingStartedWithWriter',[2,13,17,20,28]),
 'base':('GS24808-GettingStartedWithBase',[4,5,11,12,21,24,29,30,48,61,65]),
 'calc':('GS24803-GettingStartedWithCalc',[2,3,25,44,45,46]),
 'chart':('CG2403-ChartsAndGraphs',[2,3,4,5]),
}
def fetch(item):
 key,chapter,n=item
 folder='CG24' if key=='chart' else 'GS248'
 url=f'https://books.libreoffice.org/en/{folder}/{chapter}-img/{chapter}-img{n:03d}.png'
 path=ASSETS/f'{key}_{n:03d}.png'
 try:
  path.write_bytes(urlopen(url,timeout=40).read())
  im=Image.open(path); im.verify()
  print(path.name,Image.open(path).size)
 except Exception as e: print('FAILED',url,str(e))
with ThreadPoolExecutor(max_workers=6) as pool:
 list(pool.map(fetch,[(key,c,n) for key,(c,ns) in chapters.items() for n in ns]))
files=sorted(ASSETS.glob('*.png'))
w,h=1000,((len(files)+3)//4)*205
sheet=Image.new('RGB',(w,h),'#e9edf2'); d=ImageDraw.Draw(sheet)
for i,p in enumerate(files):
 im=Image.open(p).convert('RGB'); im.thumbnail((240,170))
 x=(i%4)*250; y=(i//4)*205
 sheet.paste(im,(x+(250-im.width)//2,y+22))
 d.text((x+8,y+4),p.name,fill='black')
sheet.save(ROOT/'image_inventory.jpg')
