"""Static construction details; illustrative proportions, not fabrication CAD."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

out = Path(__file__).resolve().parent
im = Image.new('RGB', (1700, 1100), '#f4f7fa')
d = ImageDraw.Draw(im)

def f(n, bold=False):
    return ImageFont.truetype('C:/Windows/Fonts/arial' + ('bd' if bold else '') + '.ttf', n)

def txt(x, y, s, n=25, bold=False, color='#26384f'):
    d.multiline_text((x, y), s, font=f(n, bold), fill=color, spacing=8)

def lead(points, color='#586b7f'):
    d.line(points, fill=color, width=3)
    x,y = points[-1]
    d.ellipse((x-4,y-4,x+4,y+4),fill=color)

def arrow_up(x, y1, y2):
    d.line((x,y1,x,y2),fill='#147f89',width=5)
    d.polygon([(x,y2),(x-11,y2+18),(x+11,y2+18)],fill='#147f89')

txt(45, 30, 'DIY details — square corners and a removable camera', 43, True)
txt(45, 93, 'Use rigid PVC foam-board walls. These close-ups show the joint shape, not exact dimensions.', 26)
for box in [(35,155,820,875),(860,155,1665,875)]:
    d.rounded_rectangle(box,16,fill='white',outline='#cbd5df',width=2)
txt(65,185,'1. BOX CORNER — view from above',29,True)
txt(65,235,'Two square-cut panels meet at 90 degrees.',24)

# Long wall encloses the end of the short wall; angle trim on exterior faces.
d.rectangle((250,390,735,420),fill='#23848e')
d.rectangle((250,420,280,745),fill='#d9954c')
d.polygon([(232,372),(435,372),(435,390),(250,390),(250,602),(232,602)],fill='#58697e')
d.line((350,420,350,490,280,490),fill='#57677a',width=3)
txt(367,451,'90°',31,True)
txt(385,565,'INSIDE\nBASKET',29,True)
txt(65,315,'External L-angle\ncorner trim',25,True)
lead([(210,360),(235,385)])
txt(478,318,'Long wall',25,True)
lead([(554,355),(554,402)])
txt(65,660,'Short wall',25,True)
lead([(202,690),(265,690)])
txt(468,670,'Bond both legs\nto the outer faces.',24)
lead([(469,720),(245,548)])
txt(65,799,'One trim strip runs the full 300 mm wall height.',24,True)

txt(890,185,'2. CAMERA — view from the side',29,True)
txt(890,235,'Remove camera and its existing clip together.',24)
# Box wall and local reinforcement pad; U jaw simplification.
d.rectangle((1200,490,1230,770),fill='#23848e')
d.rectangle((1230,490,1250,650),fill='#90c1c6')
d.polygon([(1184,450),(1266,450),(1266,585),(1250,585),(1250,470),(1200,470),(1200,602),(1184,602)],fill='#394a5e')
d.rectangle((1210,424,1238,450),fill='#394a5e')
d.rounded_rectangle((1150,348,1290,424),12,fill='#394a5e')
d.ellipse((1168,362,1225,412),fill='#e2e9ed',outline='#152b3e',width=4)
d.ellipse((1181,375,1212,404),fill='#152b3e')
arrow_up(1322,493,343)
txt(1346,357,'Open clip,\nthen lift off.',24)
txt(890,493,'Existing webcam\nclip / hinged clamp',24,True)
lead([(1103,537),(1192,537)])
txt(1340,595,'Reinforcement pad\nstays on the box.',23)
lead([(1350,655),(1242,620)])
txt(1340,723,'Box wall',25,True)
lead([(1340,760),(1215,748)])
txt(890,800,'Keep lens above the rim; leave the camera view clear.',23,True)

d.rounded_rectangle((35,905,1665,1060),16,fill='#e4f2f3')
txt(65,930,'CORNER: square panels  >  hold at 90°  >  fit L-angle  >  bond and let cure',26,True)
txt(65,976,'CAMERA: reinforce rim  >  fit existing clip  >  check view  >  unplug USB and open clip to remove',25)
txt(65,1020,'Mount concept: check your clip fits. Remove during empty-basket setup; tare after reinstalling.',22)
im.save(out/'diy-corner-and-camera-details.png')
print(out/'diy-corner-and-camera-details.png')
