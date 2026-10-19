from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.platypus import Paragraph
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader
import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output' / 'pdf'
OUT.mkdir(parents=True, exist_ok=True)
QA = ROOT / 'tmp' / 'pdfs' / 'nxtcart_brief_qa'
QA.mkdir(parents=True, exist_ok=True)
for name, filename in [('Arial', 'arial.ttf'), ('ArialBold', 'arialbd.ttf')]:
    pdfmetrics.registerFont(TTFont(name, str(Path('C:/Windows/Fonts') / filename)))
pdfmetrics.registerFontFamily('Arial', normal='Arial', bold='ArialBold')

pdf_path = OUT / 'NXTCart_Objective_and_Outcomes.pdf'
c = canvas.Canvas(str(pdf_path), pagesize=letter)
c.setTitle('NXTCart Project Objective and Expected Outcomes')
c.setAuthor('NXTCart')
c.setSubject('One page project brief for presentation visitors')
W, H = letter
M = 49
CW = W - 2 * M
y = H - 47
all_text = []

def para(text, size=11, leading=15.4, after=8, font='Arial', color='#202020', indent=0):
    global y
    p = Paragraph(text, ParagraphStyle('body', fontName=font, fontSize=size,
                  leading=leading, textColor=HexColor(color)))
    _, height = p.wrap(CW - indent, H)
    if y - height < 48:
        raise RuntimeError(f'Content exceeds one page at {text[:50]}')
    p.drawOn(c, M + indent, y - height)
    y -= height + after
    all_text.append(text)

def heading(text):
    global y
    y -= 6
    para(text, size=12, leading=16, after=5, font='ArialBold', color='#000000')

def bullet(text):
    global y
    c.setFillColor(HexColor('#202020'))
    c.circle(M + 3, y - 6.5, 1.5, fill=1, stroke=0)
    para(text, after=5, indent=13)

para('NXTCart', size=29, leading=34, after=5, font='ArialBold', color='#000000')
para('Project Objective and Expected Outcomes', size=14, leading=19,
     after=17, color='#000000')

heading('Project overview')
para('NXTCart is a smart shopping cart designed to build and verify a customer\'s '
     'bill while they shop. It brings product scanning, weight sensing, camera '
     'verification, and a touchscreen display into one system. The project '
     'addresses checkout queues, limited visibility of spending during shopping, '
     'and discrepancies between the goods in a cart and the items on its bill.')

heading('Objective')
para('To develop a shopping cart that makes purchasing more convenient while '
     'helping retailers maintain an accurate, verifiable bill. The key objectives are to:')
bullet('Show product details, quantities, and a running total as customers shop.')
bullet('Check that each scanned product matches the item placed in the cart '
       'using both weight and visual evidence.')
bullet('Support verified item removal and flag unexplained additions, '
       'substitutions, or incorrect quantities for review.')
bullet('Reduce repeated scanning at checkout and support faster completion '
       'once the basket is verified.')

heading('How it works')
para('The shopper presents a product\'s barcode or QR code to the cart\'s scanner '
     'and places the product in the basket. Its details appear on the screen '
     'while the system checks the weight change and compares camera images '
     'with reference images of that product. The display shows whether each '
     'check is pending, passed, or needs attention. Verified removals update '
     'the bill, and checkout is enabled only after the required checks pass '
     'and outstanding discrepancies are resolved.')

heading('Expected outcomes')
bullet('<b>For shoppers</b>  Clearer spending visibility, easier basket changes, '
       'and less time spent at conventional checkout counters.')
bullet('<b>For retailers</b>  Earlier detection of billing discrepancies and '
       'potential product substitutions, with staff attention directed to '
       'items that need review.')
bullet('<b>For the project</b>  A prototype that connects sensing, computer '
       'vision, and live billing, providing a basis for testing and improving '
       'assisted self checkout in retail stores.')

y -= 7
para('Prototype status  Benefits are intended outcomes. Recognition accuracy, '
     'checkout time savings, and reliability require validation on the physical '
     'cart under realistic shopping conditions.', size=9.2, leading=12.5,
     after=0, color='#545454')
c.save()
reader = PdfReader(str(pdf_path))
assert len(reader.pages) == 1, 'Brief must have exactly one page'
text = reader.pages[0].extract_text()
assert all(s in text for s in ['Project overview', 'Objective', 'How it works', 'Expected outcomes'])
doc = pdfium.PdfDocument(str(pdf_path))
doc[0].render(scale=1.7).to_pil().save(QA / 'page-1.png')
print(f'PDF: {pdf_path}')
print(f'Pages: {len(reader.pages)}; words: {len(text.split())}; content bottom: {y:.1f} pt')
print(f'Preview: {QA / "page-1.png"}')
