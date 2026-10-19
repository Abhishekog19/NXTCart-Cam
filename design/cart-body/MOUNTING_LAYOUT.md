# Recommended component mounting — handle console

This recommendation updates the earlier low display concept for a standing user. Appearance and exact dimensions remain provisional. Illustration: recommended-mounting-layout-v3.png, generated with the built-in image generation tool. Shopper stands at the handle end; left and right refer to the shopper's view.

| Component | Recommended placement |
|---|---|
| Display | Centred between fixed handle uprights, above near basket rim, outside basket opening and forward of grip. Support from two rigid brackets connected to chassis/handle frame. Start near 30 degrees back from vertical with adjustable tilt/height; check actual user reach, readability and glare. This angle is a prototype starting point, not an ergonomic standard. |
| RFID | Immediately right of screen on fixed console, slightly upward facing. Keep antenna clear of handle metal and test with actual tags/packages. Position can be mirrored if needed. |
| Verification camera | Opposite far-left fixed corner, slightly above rim, looking diagonally across RFID presentation area and into basket. Recess lens into fixed hood; do not cover optics. Exact height/angle depend on live coverage with a partially full basket. |
| QR scanner webcam | Not needed for RFID-only demonstration once replacement input is working; retain only if keeping QR as a fallback. Do not remove the verification camera. |
| White illumination | On fixed camera/rim support, aimed inward with shielding to reduce glare into lens/display. |
| Status LED + buzzer | Fixed handle console under screen; beep once for a new valid accepted scan. |
| Pi + Arduino + USB hub | Fixed ventilated side/rear tray below basket. Screw access cover at handle end, clearance for connectors and cooling. |
| HX711 | Fixed protected bracket near sensor; keep load-cell wiring short where practical and away from power switching/wheel pinch points. Any cable crossing to a moving assembly needs a relaxed loop. |
| Battery + power distribution | Low and reasonably central on fixed chassis; keep basket travel, electronics ventilation and service clearance. |
| Power switch + charging/USB access | Accessible fixed rear panel, without lifting basket. |
| Load cell + moving platform | Preserve a correctly mounted sensor on steel chassis, moving platform on loaded side, basket only on platform; no bypass supports. |
| Handle + wheels | Structural attachments directly to fixed chassis; real casters, metal handle core, printed cosmetic covers/grips. |
| Wiring | Channels within fixed body/uprights, strain relief at connectors, removable channel covers. |

Only the basket, cradle and moving platform are weighed. All accessory mounts must be separate from the basket with clearance at sides, bottom and rim. The current photographed camera clips should move off the cardboard/tub onto the fixed frame. External handling still introduces transient effects through motion/tilt/frame flex; use settled readings.

Before full print: mock up console using a temporary rigid stand. Check grip clearance, touch operation without leaning on basket, product tapping/placement with the same hand, screen reflections, camera scan-to-rest visibility with several products inside, and known-mass readings during console use. Do not set tolerance to hide mechanical contact.

Sources consulted for general principles, not cart-specific certified dimensions:
- https://www.osha.gov/etools/computer-workstations/components/monitors/
- https://www.nxp.com/company/about-nxp/smarter-world-blog/BL-NFC-ANTENNA-DESIGN-MADE-EASY

## Generation prompt

Use case: scientific-educational product illustration. Create a clean NXTCart "Recommended component placement" concept board, landscape, white background, legible navy text, teal accents. This is a compact demonstration smart cart based on a rectangular plastic tub on a steel scale chassis, with a separate fixed light-gray cosmetic outer shell and metal-core push handle and 4 small real casters. NOT a full-size supermarket trolley. Two large panels: LEFT an accurate TOP VIEW layout map with shopper standing at bottom behind handle; RIGHT a three-quarter VIEW FROM SHOPPER showing raised display position and RFID. Title "NXTCart — recommended mounting layout". Subtitle "Display at the handle • accessories on the fixed frame". Avoid the earlier low base touchscreen design: there must be NO display on the lower base.

Fixed frame vs inner basket: a separate translucent teal inner tub is the weighed basket. Gray fixed outer frame surrounds it with a visible air gap all around. All accessories below mount to gray frame, not tub. Shopper side at bottom of top view. U-shaped handle outside rear basket wall with left and right clear handgrip areas. Small rectangular landscape touchscreen sits centered on a rigid short console bracket between handle uprights, outside basket opening and FORWARD of grip so knuckles are clear. Screen raised just above basket rim near handle level, screen faces shopper and is tilted back about 30 degrees from vertical. Show actual face and simple bill UI in the 3D shopper view. Console must not cover the basket opening or touch inner tub. Compact RFID tap pad immediately RIGHT of screen on same fixed console, thin plastic face, contactless icon, accessible from shopper side. Slightly below console a tiny buzzer grille and status LED integrated into fixed console. Whole screen and console are supported on TWO brackets connected to handle uprights and chassis, no clamp to basket.

Verification camera: ONE compact recessed camera hood in FAR LEFT corner opposite shopper, fixed to outer frame, slightly above rim, facing diagonally toward near-right RFID zone and basket interior. A subtle wide dashed viewing sector in TOP VIEW covers RFID presentation area and inner basket (illustrative field of view, not a guarantee). Small white LED bar alongside camera shining inward, shielded from screen. No camera on basket wall. No second QR camera required.
Fixed lower enclosure: show a small separated inset below top view marked "Under fixed deck — service access" with just 3 labelled zones: "Battery / power" low central toward base; "Pi + Arduino + USB hub" ventilated side tray; "HX711" close to load cell. Make clear these are in FIXED body, not inside food basket. Wires hidden in gray outer upright channels. Show one label "Wheel mounts → steel chassis" on 3D view and four real casters. No invented exact measurements or component models.
Top view must clearly show layout and labels 1 Display, 2 RFID, 3 Camera, 4 Lighting, 5 Handle, 6 Fixed electronics bay. Put "USER" with a small silhouette below handle so front/back orientation unambiguous. Three-quarter shopper view should show the screen UI facing the viewer, handle behind screen, RFID immediately viewer-right, camera at far corner with lens facing into basket. Do not mirror layout between panels.
Small bottom reminder "Only the inner basket and its platform are weighed." and "Concept placement • confirm camera coverage and screen angle on the actual rig." No load-cell sectional drawing, no duplicate touchscreen, no display low on base, no camera mast rising through merchandise volume, no external loose wiring, no fabricated ergonomic standard. Clean professional practical mount recommendation for simple 3D printed housings.

## Correction prompt

Make three targeted corrections to this NXTCart mounting board. Preserve cart geometry, screen placement, overall composition, labels and style. (1) The RFID reader is for PRODUCT IDENTIFICATION, not payment. Replace the touchscreen's bottom green button "Tap card to pay" with "Scan product tag". Replace dollar currency values with rupee values, e.g. total "₹120.00", three line prices "₹40.00", "₹30.00", "₹50.00". Do not add payment suggestions. (2) In bottom electronics inset, the HX711 label currently points at a metal load-cell block. Replace that object directly under the HX711 callout with a clearly recognizable SMALL GREEN CIRCUIT BOARD amplifier with screw terminals, mounted on a fixed bracket with thin wires. Keep HX711 caption "close to load cell". No mechanical load cell in this electronics inset; this label is about the board. (3) In top view replace the field-of-view caption with "Proposed camera view — test on rig", preserving the dashed illustrative rays. Make no other changes.

