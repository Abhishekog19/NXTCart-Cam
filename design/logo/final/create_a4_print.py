from pathlib import Path

from PIL import Image
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "nxtcart-logo-transparent.png"
OUTPUT = ROOT / "nxtcart-logo-a4-print.pdf"

image = Image.open(SOURCE).convert("RGBA")
left, top, right, bottom = image.getchannel("A").getbbox()
page_width, page_height = landscape(A4)
scale = (260 * mm) / (right - left)
draw_width, draw_height = image.width * scale, image.height * scale
x = page_width / 2 - (left + right) * scale / 2
y = page_height / 2 - (image.height - (top + bottom) / 2) * scale

pdf = canvas.Canvas(str(OUTPUT), pagesize=(page_width, page_height))
pdf.setTitle("NXTCART - A4 printable logo")
pdf.setAuthor("NXTCART")
pdf.setSubject("A4 landscape; logo artwork 260 mm wide; print at 100% actual size")
pdf.setFillColorRGB(1, 1, 1)
pdf.rect(0, 0, page_width, page_height, fill=1, stroke=0)
pdf.drawImage(ImageReader(image), x, y, draw_width, draw_height, mask="auto")
pdf.showPage()
pdf.save()

reader = PdfReader(OUTPUT)
assert len(reader.pages) == 1
box = reader.pages[0].mediabox
assert abs(float(box.width) - page_width) < 0.01
assert abs(float(box.height) - page_height) < 0.01
print(f"Saved: {OUTPUT}")
print(f"Page: {page_width / mm:.0f} x {page_height / mm:.0f} mm")
print(f"Logo: 260 x {(bottom - top) * scale / mm:.1f} mm")
