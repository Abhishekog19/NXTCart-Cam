# DIY cart body — current fabrication direction

Updated 14 October 2026. The display mount has already been 3D printed.
The user has stopped further whole-cart printing because of time and cost.
Current follow-up: exact 300 x 220 x 300 mm internal box, built by the user.
Use DIY_BOX_BUILD.md for the proposed panel cuts and build method. The accepted
mounting compromise is camera on the box and RFID beside the fixed display;
the independent two-upright frame below is an earlier alternative.
Earlier tiled/snap-fit print plans remain historical proposals, not the current
fabrication recommendation. Handle design remains undecided.

For this proposal, the three remaining items are interpreted as the main
basket/body, camera mount and RFID mount. The completed display mount is reused.

## Recommended economical route

Reuse the current plastic tub as the load-bearing weighed basket if its volume
is suitable. Give it a clean opaque corrugated-PP sleeve, attached only to the
tub. Replace the cardboard extension with light, reinforced sheet sides only
if the height is necessary. The extension, its corner strips and sleeve are
part of the tared weighed assembly; they do not attach to the fixed frame.

Build one separate accessory frame from two short upright lengths of ready-made
metal angle or perforated strip, with a crosspiece/bracing as needed. Fix it
through existing steel-chassis holes or proper clamps. No welding or printed
connectors are required. Check rigidity with the actual camera and reader.

Camera: use its existing webcam clip on a small rigid mounting plate fixed to
the frame. Hide it in a small plastic project box with a recessed open lens
window and service access. Set the angle with the live image, including a
partly filled basket. Do not put opaque plastic over the lens.

RFID: use a small plastic enclosure or repurposed rigid container, held on the
fixed frame through a nonmetallic bracket. Keep an HF/NFC antenna away from
metal uprights/fasteners and test with the actual tags and product packaging.
Do not select an arbitrary universal antenna clearance or assume the module
reads all basket items. Use deliberate product presentation.

Keep the printed display mount attached to the fixed chassis/frame. Put boards
and power on a fixed insulated mounting tray with ventilation, using spacers
and straps/clips as appropriate. Snap-lid plastic electrical boxes are useful
for serviceable covers. A light sheet skirt around the fixed lower tray hides
electronics and cable channels.

## Alternatives

| Method | Suitable use | Tradeoff |
|---|---|---|
| Existing tub + corrugated PP finish | Preferred fastest route when current tub fits | Reuses known basket; exact CAD dimensions may not match tub |
| Ready-made opaque storage bin | Simple neat replacement basket | Fit actual bin to platform; choose dimensions and tare again |
| Cut-and-fold corrugated PP basket | Light custom walls for small demo loads | Needs rigid floor, supported seams and reinforced corners |
| PVC foam-board box cut by a sign shop | Custom rectangular appearance near CAD shape | Use a rigid supported floor; evaluate added weight and joint strength |
| Thin plywood box | Rigid custom basket if cutting tools are available | More fabrication and tare mass; not first choice for lowest effort |

If retaining the earlier 300 x 220 x 300 mm internal envelope is essential, use
the custom cut-sheet option rather than pretending the current tub matches it.
Have a local sign-board/carpentry shop cut simple panels to measured thickness;
butt joints need a cut list that accounts for that thickness. Keep support from
the existing rigid moving weighing plate, and evaluate the maximum demo payload.

## Shared material list

- Existing tub, steel base, sensor/platform assembly and printed display mount.
- Corrugated PP sheet (roughly 3–4 mm is a mockup starting material, not a rating).
- Two fixed uprights, brackets and suitable chassis fixing/clamps.
- Small plastic enclosures for camera and reader; scrap rigid plastic brackets.
- Releasable cable ties/straps, existing webcam clip and corner profiles.
- Cable sleeve/channel, edge trim, board spacers and simple removable covers.
- Optional LED strip and buzzer, mounted on fixed body.

Use tie holes/corner profiles for PP connections; do not rely on ordinary glue
as the only structural joint. Tape or wrap is appropriate for appearance.

## Build order and verification

1. Place the finished display mount on the fixed chassis; preserve service access.
2. Seat the tub on the existing moving plate and secure/locate it only there.
3. Fit the independent accessory frame; verify all-sided basket clearance.
4. Fit camera and RFID temporarily; test product presentation and camera coverage.
5. Secure boards and relaxed wiring, then add sleeves, skirts and branding.
6. Tare the final empty weighed assembly and test known masses at centre/corners.
7. With a known mass in the basket, touch the reader/display/frame and check for
   persistent settled weight changes, contact or cable tension. Rolling/bumping
   introduces transients; verify weight after settling.

All camera/reader/frame loads bypass the sensor. Any basket sleeve/extension
is weighed and tared. No cable, cover, foam pad or bracket may support the
basket from the fixed chassis. Proper mounting reduces handling interference;
it cannot eliminate acceleration, tilt, direct basket pressure or frame flex.

Sources:
- https://www.coroplast.com/products/
- https://www.nxp.com/company/about-nxp/smarter-world-blog/BL-NFC-ANTENNA-DESIGN-MADE-EASY
- https://www.hbm.com/fileadmin/mediapool/hbmdoc/technical/a1269.pdf
