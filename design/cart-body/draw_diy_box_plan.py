"""Dimensioned concept diagram for the hand-built basket, not a cutting template."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
im = Image.new('RGB', (1600, 1100), '#f4f7fa')
d = ImageDraw.Draw(im)

def font(n, bold=False):
    return ImageFont.truetype('C:/Windows/Fonts/arial' + ('bd' if bold else '') + '.ttf', n)

def text(x, y, value, n=26, bold=False, color='#24364c'):
    d.text((x, y), value, font=font(n, bold), fill=color)

def arrow(a, b, label, label_at):
    d.line((a, b), fill='#44566b', width=2)
    if a[1] == b[1]:
        for x, sign in [(a[0], 1), (b[0], -1)]:
            d.line([(x + sign * 10, a[1] - 5), (x, a[1]), (x + sign * 10, a[1] + 5)], fill='#44566b', width=2)
    else:
        for y, sign in [(a[1], 1), (b[1], -1)]:
            d.line([(a[0] - 5, y + sign * 10), (a[0], y), (a[0] + 5, y + sign * 10)], fill='#44566b', width=2)
    text(*label_at, label, 24, True)

text(45, 35, 'DIY basket — five panels, simple corner joints', 43, True)
text(45, 99, 'Target clear interior: 300 L x 220 W x 300 H mm', 30, True, '#117e87')
text(45, 145, 'Example: 4 mm foamed-PVC walls + 6 mm plywood floor. Measure actual thickness before cutting.', 23)
d.rounded_rectangle((35, 205, 795, 800), 16, fill='white', outline='#cbd5df', width=2)
d.rounded_rectangle((825, 205, 1565, 800), 16, fill='white', outline='#cbd5df', width=2)
text(65, 230, 'TOP VIEW — how the corners meet', 27, True)

scale = 1.6
x, y = 170, 340
w, h, t = 308 * scale, 228 * scale, 4 * scale
# All wall geometry is to scale; long walls span both end walls.
d.rectangle((x, y, x + w, y + h), fill='#f3efe6', outline='#876b40', width=2)
d.rectangle((x, y, x + w, y + t), fill='#1c8490')
d.rectangle((x, y + h - t, x + w, y + h), fill='#1c8490')
d.rectangle((x, y + t, x + t, y + h - t), fill='#df9a4c')
d.rectangle((x + w - t, y + t, x + w, y + h - t), fill='#df9a4c')
d.rectangle((x + t, y + t, x + w - t, y + h - t), fill='#ffffff')
arrow((x + t, y + h / 2), (x + w - t, y + h / 2), '300 mm clear', (x + 145, y + h / 2 - 36))
arrow((x + w / 2, y + t), (x + w / 2, y + h - t), '220 mm', (x + w / 2 + 15, y + h / 2 + 45))
arrow((x, y - 45), (x + w, y - 45), '308 mm outside', (x + 135, y - 80))
text(65, 737, 'Orange end walls fit BETWEEN teal long walls.', 24, True)

text(855, 230, 'CUT LIST — all sizes in millimetres', 27, True)
rows = [
    ('2 long walls', '308 x 300', '#1c8490'),
    ('2 end walls', '220 x 300', '#df9a4c'),
    ('1 plywood floor', '308 x 228', '#876b40'),
    ('4 external corner trims', '300 long', '#68798e'),
]
for i, (name, size, color) in enumerate(rows):
    yy = 305 + i * 82
    d.rounded_rectangle((852, yy, 1535, yy + 64), 8, fill='#f4f7fa')
    d.rectangle((866, yy + 18, 886, yy + 40), fill=color)
    text(902, yy + 16, name, 25)
    text(1300, yy + 16, size, 27, True)
text(855, 656, 'Walls stand ON TOP of the floor.', 28, True)
text(855, 702, 'Clear height = 300; outside height = 306.', 25)
text(855, 744, 'Outside sizes exclude applied corner trim.', 22)

d.rounded_rectangle((35, 835, 1565, 1055), 16, fill='#e4f2f3')
text(65, 860, 'BUILD ORDER', 26, True)
text(65, 904, 'Cut and dry-fit  >  square the box  >  reinforce outside corners  >  secure to moving plate', 25)
text(65, 949, 'Camera mounts on box; RFID mounts beside fixed display. No box support from the fixed chassis.', 24)
text(65, 995, 'Prototype cut plan, not a payload rating. Test the intended load and tare the finished empty basket.', 23)
im.save(OUT / 'diy-box-cut-plan.png')
print(OUT / 'diy-box-cut-plan.png')
