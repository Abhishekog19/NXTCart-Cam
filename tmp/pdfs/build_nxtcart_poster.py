from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor, Color
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader
import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output' / 'pdf'
OUT.mkdir(parents=True, exist_ok=True)
for name, filename in [('Body','segoeui.ttf'),('Bold','segoeuib.ttf'),('Light','segoeuil.ttf')]:
    pdfmetrics.registerFont(TTFont(name,str(Path('C:/Windows/Fonts')/filename)))
pdfmetrics.registerFontFamily('Body',normal='Body',bold='Bold')
W,H = A4
pdf = OUT/'NXTCart_Project_Poster.pdf'
c=canvas.Canvas(str(pdf),pagesize=A4)
c.setTitle('NXTCart Smart Shopping Cart Project Poster')
c.setAuthor('NXTCart')
NAVY='#202641'; BLUE='#3048C8'; GRAY='#5E6478'; PALE='#EEF1FF'; WHITE='#FFFFFF'

def fill(color): c.setFillColor(HexColor(color))
def stroke(color): c.setStrokeColor(HexColor(color))
def text(x,y,s,size=11,font='Body',color=NAVY):
    fill(color); c.setFont(font,size); c.drawString(x,y,s)
def para(x,top,w,s,size=11,leading=15,font='Body',color=GRAY):
    p=Paragraph(s,ParagraphStyle('p',fontName=font,fontSize=size,leading=leading,textColor=HexColor(color)))
    _,h=p.wrap(w,H); p.drawOn(c,x,top-h); return h
def path(points,color,closed=True,stroke_color=None,width=1.5):
    p=c.beginPath(); p.moveTo(*points[0])
    for xy in points[1:]: p.lineTo(*xy)
    if closed:p.close()
    fill(color); stroke(stroke_color or color); c.setLineWidth(width)
    c.drawPath(p,fill=1,stroke=bool(stroke_color))
def line(x1,y1,x2,y2,color=BLUE,width=1.7):
    stroke(color);c.setLineWidth(width);c.setLineCap(1);c.line(x1,y1,x2,y2)
def check(x,y,col=BLUE,scale=1):
    line(x,y,x+3*scale,y-3*scale,col,1.6);line(x+3*scale,y-3*scale,x+9*scale,y+5*scale,col,1.6)
def rr(x,y,w,h,r,color):
    fill(color);c.roundRect(x,y,w,h,r,fill=1,stroke=0)

# A quiet paper background, clear blue brand accents, generous negative space.
fill('#FAFBFF');c.rect(0,0,W,H,fill=1,stroke=0)
fill(BLUE);c.rect(0,H-7,W,7,fill=1,stroke=0)
c.drawImage(str(ROOT/'design/logo/final/nxtcart-logo-transparent.png'),33,H-91,
            width=173,height=57.67,mask='auto')
text(405,H-57,'PROJECT SHOWCASE',9,'Bold',BLUE)
text(405,H-72,'SMART SHOPPING CART',8,'Body',GRAY)

text(39,715,'Smart shopping,',31,'Bold')
text(39,677,'with a live bill.',31,'Bold',BLUE)
para(40,653,283,'A cart that checks products and updates your bill while you shop.',12,17)

# Central product illustration: an enclosed basket, handle, touchscreen and products.
c.saveState();c.translate(355,658);c.scale(.88,.88)
fill('#E8EDFF');c.circle(95,-68,92,fill=1,stroke=0)
fill('#D9E1FC');c.ellipse(3,-183,205,-163,fill=1,stroke=0)
line(19,-5,41,-5,NAVY,5);line(41,-5,62,-144,NAVY,5)
line(62,-144,179,-144,NAVY,5)
line(72,-144,67,-159,NAVY,3);line(171,-144,179,-159,NAVY,3)
for wx in (67,179):
    fill(NAVY);c.circle(wx,-165,11,fill=1,stroke=0)
    fill('#FAFBFF');c.circle(wx,-165,4,fill=1,stroke=0)
# Packages above the rim.
rr(82,-48,31,65,4,'#F3BC71');line(87,2,107,2,'#D99039',2)
rr(119,-49,31,45,4,'#7CC8B8');rr(127,-6,15,11,2,'#459C8B')
path([(154,-48),(154,8),(181,15),(188,-48)],'#F6DCE8')
line(160,-5,177,-1,'#CF8BA9',3)
path([(51,-31),(199,-31),(181,-124),(68,-124)],BLUE)
path([(186,-31),(199,-31),(181,-124),(169,-124)],'#25399F')
rr(62,-38,124,7,3,'#526AE4')
rr(80,-76,83,28,5,'#FFFFFF')
text(90,-65,'NXTCART',10,'Bold',BLUE)
text(89,-91,'scan  +  verify  +  bill',6.5,'Body',WHITE)
# Touchscreen mounted at handle.
line(40,3,58,20,NAVY,3)
rr(24,11,54,47,5,NAVY);rr(29,16,44,36,2,WHITE)
text(34,40,'YOUR CART',5.6,'Bold',BLUE)
line(34,33,66,33,'#D7DDF4',1)
line(34,27,59,27,'#D7DDF4',1)
check(58,21,'#459C8B',.65)
c.restoreState()

text(40,582,'THE OBJECTIVE',9,'Bold',BLUE)
para(40,571,273,'Make shopping easier<br/>and billing more reliable.',18,24,'Bold',NAVY)

# Four short, visual process steps on a single reading line.
text(40,482,'HOW IT WORKS',9,'Bold',BLUE)
steps=[('01','Scan','Present the product\'s\nbarcode or QR code.'),
       ('02','Add','Place the scanned\nitem in the basket.'),
       ('03','Verify','Weight and camera\ncheck the product.'),
       ('04','View bill','See your items and\nrunning total.')]
for i,(n,title,body) in enumerate(steps):
    x=40+i*133
    rr(x,438,27,27,8,BLUE)
    text(x+6,447,n,10,'Bold',WHITE)
    if i<3:
        line(x+37,451,x+113,451,'#CCD4F6',1.3)
        line(x+108,455,x+113,451,'#CCD4F6',1.3)
        line(x+108,447,x+113,451,'#CCD4F6',1.3)
    text(x,420,title,14,'Bold')
    para(x,408,121,body.replace('\n','<br/>'),10,14)

line(40,359,W-40,359,'#DCE2F5',.8)
text(40,334,'KEY FEATURES',9,'Bold',BLUE)
text(311,334,'EXPECTED OUTCOMES',9,'Bold',BLUE)
features=[('Live billing','Item details, quantities and total.'),
          ('Product verification','Weight and visual checks work together.'),
          ('Verified removals','Confirmed removals update the bill.'),
          ('Review before checkout','Unresolved checks need attention.')]
outcomes=[('Less checkout waiting','Reduce repeated scanning at the counter.'),
          ('Better budget control','Know your spending as you shop.'),
          ('Fewer billing discrepancies','Spot mismatched or unscanned goods.'),
          ('Focused staff assistance','Review only the items needing help.')]
for i,(left,right) in enumerate(zip(features,outcomes)):
    yy=306-i*47
    for x,(title,body) in [(40,left),(311,right)]:
        check(x+1,yy-1,BLUE,.8)
        text(x+16,yy,title,11,'Bold')
        para(x+16,yy-7,225,body,9.2,12.5)

# Compact system summary and restrained prototype qualification.
rr(40,76,W-80,46,11,NAVY)
text(55,105,'BUILT WITH',7.5,'Bold','#BFC9FF')
text(55,88,'Barcode / QR scanning   +   Weight sensing   +   Camera vision   +   Touchscreen',8.3,'Body',WHITE)
text(40,51,'Prototype project',8,'Bold',GRAY)
text(118,51,'|  Expected benefits to be validated in real shopping conditions.',8,'Body',GRAY)
c.save()
reader=PdfReader(str(pdf))
assert len(reader.pages)==1
pd=pdfium.PdfDocument(str(pdf))
png=OUT/'NXTCart_Project_Poster.png'
pd[0].render(scale=2).to_pil().save(png)
print(f'PDF: {pdf}\nPNG: {png}\nPages: {len(reader.pages)}\nWords: {len(reader.pages[0].extract_text().split())}')
