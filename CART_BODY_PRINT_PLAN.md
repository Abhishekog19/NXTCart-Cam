# NXTCart demonstration body — preliminary print plan

Status: historical print concept and inventory. On 14 October 2026 the user
confirmed the display mount is printed and stopped further cart printing for
time/cost reasons. Current recommendation: design/cart-body/DIY_BODY_PLAN.md.
Recommended component layout: design/cart-body/recommended-mounting-layout-v3.png
and MOUNTING_LAYOUT.md recommend raising the screen to a fixed handle console
for a standing user; this supersedes the earlier low base display suggestion.
Preferred appearance: the compact tote-shaped mobile concept in
design/cart-body/compact-mobile-concept-v2.png, with a fixed outer surround,
separate weighed inner liner, low display console, compact fixed corner camera
hood, chassis-mounted handle, and real casters. See COMPACT_DIRECTION.md in
that folder. The earlier tall camera support is optional, subject to coverage.
Based on the two supplied prototype photos, SYSTEM_SETUP.md, and the user's
RFID demonstration direction. The newer photo shows the camera installation;
the older photo provides a clearer view of the tub and steel base. Neither
photo establishes dimensions, load-cell type, or load rating.

## Mechanical arrangement

Use two mechanically separate assemblies:

- Weighed assembly: items, inner basket/tub, basket cradle, and the existing
  moving platform. Their load reaches the chassis only through the correctly
  mounted load cell. Tare out the empty assembly.
- Fixed assembly: steel chassis, wheels, handle, outer body, electronics,
  display, RFID reader, camera support, lights, and buzzer.

Keep a clearance around and below the weighed assembly, including at maximum
demo load and during normal frame flex. No rubbing covers, foam, tight wires,
extra supporting feet, or basket-to-chassis fasteners may bridge this gap.
Avoid exposed fixed ledges that can support merchandise. Basket edges should
stand above adjacent fixed trim so products stay in the weighed volume.

Keep existing rigid metal parts in the primary load-cell mounting path.
Confirm the actual sensor's mounting instructions, capacity, permissible
platform size, and off-centre performance before sizing the basket. Do not
assume every bar load cell is suitable for a large single-point platform.

Mechanical isolation reduces handling interference, but cannot eliminate
motion, tilt, vibration, or direct pressure on the basket. Verify weight when
settled. All printed basket parts also consume sensor capacity before taring.

## Printable assembly inventory

Quantities are provisional. Large panels and rails may need multiple prints.

| ID | Assembly | Approximate quantity | Attachment / purpose |
|---|---|---:|---|
| B01 | Lower body skirt panels | 4 sides, split as needed | Fixed chassis; conceal boards and steel edges |
| B02 | Upper outer side panels | 4, split as needed | Fixed frame; clean cart silhouette around basket |
| B03 | Corner uprights and joining blocks | 4 sets | Fixed frame; connect cosmetic panels |
| B04 | Electronics deck / top cover | 1, split as needed | Fixed chassis; opening around moving platform |
| B05 | Service hatch and screw tabs | 1 set | Board, power, and USB access |
| B06 | Outer top trim / camera crossmember | 1 segmented set | Fixed frame; does not touch inner basket |
| W01 | Basket locating cradle and retainers | 1 set | Moving platform only; locate tub without bypassing sensor |
| W02 | Basket side panels and bottom insert | Optional 1 set | Replacement for temporary tub; all on weighed assembly |
| W03 | Inner basket rim and seam joiners | Optional 1 set | Finish replacement basket; no connection to fixed trim |
| H01 | Handle mounting collars / cosmetic brackets | 2 sets | Fixed structural frame; metal handle core preferred |
| H02 | Handle grips and end caps | 2 grips + caps | Finish real handle |
| C01 | Camera adjustment bracket | 1 | Fixed upper frame; set angle with slots and screws |
| C02 | Camera enclosure, rear lid, lens hood | 1 set | Recessed unobstructed lens; concealed USB cable |
| D01 | Display bezel and back cover | 1 set | Screen protection, cable exit, ventilation |
| D02 | Display tilt bracket | 1 set | Fixed handle support / upright |
| R01 | RFID reader pod, lid, tap face | 1 set | Fixed handle area; replaceable insert for actual reader |
| E01 | Electronics mounting tray and standoffs | 1 set | Pi, Arduino, hub and power parts as actually fitted |
| E02 | HX711 mounting clip / small cover | 1 | Close to sensor where practical; serviceable |
| E03 | Battery or power-bank cradle and strap loops | 1 if needed | Fixed chassis; preserve charging access |
| E04 | Cable channels, covers, clips, strain relief | As needed | Hidden fixed wiring; preserve any necessary flexible loop |
| L01 | LED channels, end caps and diffuser holders | 1–2 sets | Fixed frame; camera illumination / decorative light |
| L02 | Status light window / light pipe | Optional 1 | User feedback, can be integrated into reader pod |
| A01 | Buzzer bracket and sound grille | 1 | Fixed electronics area; can be integrated into cover |
| F01 | Wheel mounting templates / hole adapters | Only if needed | Actual casters bolt through steel, not only printed body |
| F02 | Wheel covers, corner bumpers and base edge caps | Optional set | Cosmetic finishing; no wheel interference |
| F03 | Reusable panel joiners, captive-nut pockets and blanking caps | As needed | Simplify assembly; integrate into larger parts where possible |
| F04 | NXTCart badge / nameplate | Optional 1 | Final appearance |

This is an inventory of functions, not a requirement for 28 separate designs.
Combine the buzzer grille, cable guides, joining tabs and badge with larger
panels where sensible. Use removable screws for electronics access. Avoid
complex hinges and locking mechanisms for the demonstration.

## Camera, RFID and sound

Place the verification camera in a fixed upper corner or crossmember looking
across the RFID presentation area and into the basket. Conceal its body and
wiring, but leave a recessed clear optical opening. Check the live image with
products already in the basket before committing to the housing. A small hood
must not vignette the lens. No opaque cover over the lens. Recessing discourages
casual interference; it does not make a single camera impossible to obstruct.

Use deliberate one-product-at-a-time RFID presentation for the demo. Do not
assume an unspecified RFID module supports whole-basket inventory. For an
HF/NFC reader, test the enclosure and distance from steel; nearby metal can
detune the antenna. Put the reader behind a thin nonconductive tap face with
its antenna area free of metal fasteners. Select compatible tags and test tags
on the actual product packaging before fixing geometry.

RFID needs a software adapter mapping tag identity to SKU and suppressing
repeated reads while a tag stays present. The current runtime still documents
QR/barcode input. Beep once when a new valid scan is accepted; retain separate
weight and camera verification feedback. Provide an actual suitable buzzer and
driver/power connection; only its holder and grille are printed.

## Fabrication approach

Retain the steel base, load cell, rigid weighing plate and initially the tub.
Use real casters, a metal handle/frame core, bolts, washers and nuts. Print the
body, enclosures, grips, joiners and wiring accessories. Confirm loads before
using printed parts structurally. Choose filament and wall thickness after
printer, temperatures and mechanical duties are known.

Keep the CAD parametric and split parts to the printer's usable build volume.
Start with fit coupons for joints/clearances. Suggested sequence:

1. Confirm sensor mounting and weighed-platform isolation.
2. Fit basket cradle, fixed frame/handle, display and camera brackets.
3. Test RFID pod and camera coverage in place.
4. Add electronics cover, panel set, wiring channels, lights and sound.
5. Add cosmetic details or replace the temporary tub if needed.

Before final enclosure printing, test a known mass at the basket centre and
corners, handle forces, display/RFID use, empty return, and wheel movement
followed by settling. Repeat with the enclosure fitted; check for contact.

## Measurements needed for Fusion CAD

- Steel base length/width/thickness, existing holes, and under-base clearance.
- Tub top and bottom length/width, height and rim profile; retain or replace?
- Load-cell model/rating, dimensions, hole centres, mounting orientation and
  moving-plate dimensions. A clear underside view helps establish load path.
- Desired handle height, basket opening height, and overall cart envelope.
- Camera, display, RFID module and electronics models/dimensions, including
  connectors and mounting holes; power arrangement and intended casters.
- Maximum demo payload, printer usable X/Y/Z volume and available material.

Photos establish a concept, not millimetre dimensions. Final hole sizes,
clearances, stop gaps, wall thicknesses and print counts remain unset.

## Technical references

- HBK, correct load application:
  https://cloud.hbkworld.com/en/knowledge/resource-center/articles/load-application-in-load-cells
- SparkFun, HX711 mounting examples:
  https://learn.sparkfun.com/tutorials/load-cell-amplifier-hx711-breakout-hookup-guide/all/
- NXP, NFC antenna design and metal proximity:
  https://www.nxp.com/docs/en/application-note/AN11755.pdf
