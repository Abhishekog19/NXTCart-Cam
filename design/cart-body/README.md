# NXTCart body concept visuals

Created with the built-in image generation tool. These are discussion illustrations, not dimensioned Fusion CAD or print-ready files. Part numbers in the 24-tile menu are the preferred reference when selecting components; grouped assemblies include small joiners and caps from CART_BODY_PRINT_PLAN.md.

- cart-body-concept-v1.png: assembled appearance and exploded concept. Main assembly callouts are illustrative, not an exact construction drawing. The external camera upright must attach to the fixed chassis, fully outside the tub; no load path may bypass the load cell. The actual sensor and weighing plate must be modelled from measured hardware rather than from the illustration.
- printable-parts-menu-v1.png: 24 numbered printable groups. Tiles 08 and 09 replace the tub and can be skipped if retaining it. Tiles 23 and 24 are optional finishing pieces. Any wheel adapter must be assessed for the real load and mounting; real casters attach to the steel chassis.

The full inventory and mechanical requirements remain in ../../CART_BODY_PRINT_PLAN.md.

## Concept generation prompt

Use case: product-mockup / scientific-educational illustration.
Create a polished, mechanically plausible NXTCart smart shopping cart concept board, landscape 3:2, high resolution. This is a SMALL SIMPLE TABLETOP-SIZE DEMONSTRATION PROTOTYPE, based on a rectangular translucent plastic household storage tub over a black steel plate with scale underneath, not a large supermarket trolley. Show two equally useful large views on a warm white background: LEFT assembled finished concept, RIGHT vertically exploded assembly with discreet leader lines and large readable labels. Title "NXTCart — body concept". Subtitle "Concept only • dimensions to be measured".
Design language: clean satin light gray 3D printed segmented shell with modest teal accents, four real black small casters, sturdy two-upright metal-cored rear push handle with printed grips, rear tilted small touchscreen, thin plastic RFID tap pod near display, fixed tall corner/crossmember housing with recessed camera looking across tap area and down into basket, concealed wiring and subtle white LED illumination. Basket remains open topped and merchandise volume unobstructed. Make the same cart geometry in both views.
CRITICAL mechanical structure: the translucent inner tub and its cradle rest ONLY on a rigid floating weighing plate on the loaded side of ONE load cell. The load cell fixed side bolts to lower steel chassis. A distinct outer fixed frame supports handle, screen, camera, RFID reader and outer shell independently, directly on chassis. Clearly show visible air gaps around the tub and floating platform, no supports underneath bypassing load cell. Camera must be above basket opening for useful view. Fixed frame must NOT touch basket rim. Tub lip stands above outer cosmetic trim. The exploded view must visually distinguish basket cradle and floating plate from fixed shell deck with a generous central opening, so fixed deck cannot contact moving plate. Do not invent extra load cells or extra feet supporting basket.
Use only 9 clear labels with short leader lines on exploded side: "Inner tub — retained", "Printed basket cradle", "Floating weighing plate — retained", "Load cell — retained", "Fixed steel chassis — retained", "Printed body panels", "Printed electronics cover", "Fixed handle + display mounts", "Camera + RFID housings". Reference hardware dark charcoal or translucent, printed parts light gray/teal. Subtle amber highlight only around weighed cradle and one small legend "Amber: weighed assembly   Teal: fixed printed mounts   Gray: retained hardware".
Small bottom inset: simple side cutaway with two arrows "Items → basket → load cell → chassis" and "Handle / wheels → chassis"; do not imply the basket floats unsupported. Bottom footer "Hidden electronics • removable service cover • real casters and metal handle core". No measurements, no production claims, no sci-fi, no enormous basket, no cardboard, no dangling exposed wires, no opaque camera window. Prioritize spatial understanding over photorealism.

## Concept correction prompt

Edit this NXTCart concept board. Keep the overall layout, clean rendering, labels and two views. Correct the camera mounting geometry carefully: in BOTH assembled and exploded views put the camera upright OUTSIDE the plastic tub, behind its far outer corner, attached directly to the FIXED chassis/frame. The camera support must never pass through the tub, touch its walls or floor, or occupy the basket's merchandise volume. Show the tub completely uninterrupted with a clean visible gap from the external camera column. Camera head may cantilever inward above the opening to look across RFID tap area and down into basket. The complete tub must remain removable upward past the support. Remove the duplicate RFID pad from camera column; keep one RFID pod beside the rear display. Change callout 9 to "External camera housing". Change callout 8 to "Handle / display / RFID mounts". Correct callout 7 leader to a genuine fixed lower electronics deck/cover with large clearance opening around the moving weighing plate, rather than calling the upper rail electronics cover. Preserve the one load cell between fixed steel chassis and moving plate, no extra platform supports. Preserve concept-only subtitle. In the small side cutaway show camera support outside basket as well if present. Do not add new features.

## Printable menu generation prompt

Use case: product-mockup infographic. Create a highly legible 3D printed parts catalogue board for NXTCart demonstration shopping cart. Portrait 2:3 high resolution, white background, polished neutral studio orthographic/isometric miniature product renders, navy typography and teal accents. This is a VISUAL PARTS MENU for deciding what to 3D print, not manufacturing CAD. Show exactly 24 equal numbered tiles in a precise 4 columns by 6 rows grid; each tile contains its own separated component/assembly render and exact short label below, with no missing tiles, no duplicate numbers and no cross-tile objects. Use generous whitespace. Small reasonable assemblies in each tile, not complex whole carts. All parts plain light-gray plastic with teal highlight surfaces, optional tiles amber border and visible "OPTIONAL" badge. Small quantity multiplicity can be shown via paired parts. Title "NXTCart — printable parts menu". Subtitle "Choose the body, mounts and finishing pieces". Footer "Concept shapes only • final fit needs measurements" then "Retain: steel chassis, load cell, weighing plate, tub, real casters, metal handle core".
Tile content and exact labels:
01 "Lower skirt panels": 4 low rectangular wall segments, one front panel with subtle NXTCart text.
02 "Outer side panels": four taller flat modular surround panels with joining holes.
03 "Corner posts + joiners": four hollow corner uprights and a few small angle connector blocks and panel tabs.
04 "Deck cover": segmented flat electronics cover with conspicuous large rectangular central opening for independently moving weighing platform, no solid tray bridging it.
05 "Service hatch": flat removable access lid with four screw ears, separated from little matching flange.
06 "Upper trim": four slim segmented rectangular outer rim rails with corner connections.
07 "Tub cradle": four low locating corner cups linked by two support strips, amber plastic to indicate weighed assembly; no additional legs extending to floor.
08 "Basket walls": four flat printable basket wall panels, OPTIONAL badge, alternative to existing plastic tub.
09 "Basket floor + rim": flat basket bottom and separate segmented rim and seam joiners, OPTIONAL badge, alternative to existing plastic tub.
10 "Handle collars": two paired split clamps for fixing a real metal tubular handle to frame, screw holes visible.
11 "Grips + end caps": two short cylindrical hand grips with textured surface and separate end caps.
12 "Camera angle mount": simple two-piece slotted screw-adjustable bracket.
13 "Camera enclosure": small box hood with open circular lens aperture, detached rear lid, simple hollow external corner column channel with open end for cables. No actual camera electronics.
14 "Display case": rectangular touchscreen bezel and detached vented back enclosure; screen hole visible, no actual screen.
15 "Display tilt mount": two simple triangular screw brackets and a mounting plate, no elaborate mechanism.
16 "RFID tap pod": small angled reader enclosure with thin nonmetallic teal tap face and detached rear lid with internal board standoffs, contactless icon.
17 "Board tray + spacers": perforated electronics tray with board standoffs and a few separate spacer posts.
18 "HX711 cover": very small rectangular board holder and detached protective cover with wire openings.
19 "Power cradle": simple power bank tray with strap slots and separate keeper; no printed battery.
20 "Cable guides + clips": U-shaped cable channel with snap-on lid, 3 small cable clips and strain-relief block.
21 "LED channels + diffuser": two short slim LED holders, translucent diffuser strips and end caps, no huge lighting equipment.
22 "Buzzer + status grille": small round buzzer holder, perforated front grille and small status LED window; no actual speaker electronics.
23 "Wheel covers + bumpers": two small caster cosmetic guards, corner bumpers and simple optional hole-pattern adapter plate, OPTIONAL badge. Do NOT render printable wheels; real wheels are retained hardware.
24 "Badge + finishing caps": small flat NXTCart plaque, screw-hole plugs and blanking caps, OPTIONAL badge.
Every label must remain readable. Illustrations must actually correspond to labels. Make all 24 tiles match stylistically. No fake dimensions, no filament spools, no bolts sold as printable parts, no production certification, no whole cart thumbnail replacing the individual parts. Keep content focused on simple feasible printed plastic demonstration assemblies.

