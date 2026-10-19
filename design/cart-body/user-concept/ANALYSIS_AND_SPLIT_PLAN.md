# Supplied concept — analysis and proposed screw-free split

Date: 13 October 2026. Discussion proposal only; the source geometry has not
been modified or split, and no print-ready parts have been produced.

## Confirmed scope

- The user supplied `C:/Users/ADMIN/Downloads/3D model.zip`.
- The archive contains FreeCAD document data (version 1.1), not a folder of STL
  exports. A byte-for-byte copy is preserved as `original-concept.FCStd`.
- The tall box is the actual weighed basket, not a cover around the old tub.
- Printer/build volume and filament are not yet decided.
- The user requests analysis and discussion first; retain the rough concept's
  dimensions, component positions and lower display. Handle design is deferred.
- Printable body joints should assemble without screws or nuts. Do not quietly
  replace the existing metal load-cell fixing with unvalidated plastic snaps.

## Inspected geometry

Dimensions come from dimensional sketches and the stored BRep geometry,
including location transforms. `dimensions.json` contains coordinate bounds;
`source-cad-edge-preview.png` shows orthographic and isometric topology edges.
Preview includes hidden edges and simplifies curved edges to endpoint chords.
No CAD-kernel watertightness, interference, stress or print validation was run.

| Source feature | Geometry / envelope, mm | Interpretation |
|---|---|---|
| Body / Pad | 300 x 365 x 1.5 | Base reference; retain real steel base rather than duplicating in thin plastic |
| Extrude | 45 x 45 x 110 | Central support placeholder; not a validated load-cell model |
| Extrude001 | 220 x 170 x 2 | Upper support/platform reference |
| Thickness | 304 x 224 x 302 outside | Basket, originally a 300 x 220 x 300 volume with 2 mm outward thickness |
| Cut003 | 300 x 110 x 65 | Lower display/electronics housing envelope |
| Sketch007 | 120 x 78 rectangle; 30 deep cutter | Display recess geometry, not measured display specification |
| Sketch007 placement | About 15.52 degrees from horizontal | Current display-plane slope; retain pending later ergonomic/handle decisions |
| Thickness001 | 12 x 44 x 62 outside | Small top-open side pocket; camera purpose inferred from size/location |
| Cut004 | 18 x 78 x 110 outside | Larger top-open side pocket; RFID purpose inferred from size/location |
| Sketch008 / 009 / 010 | 30 x 15; 45 x 20; 27 x 13 | Additional lower-housing openings; confirm connector purpose later |

Overall envelope of these principal shapes is approximately 330 x 365 x 413.5
mm including side pockets, before wheels and handle. Do not confuse the internal
basket size with the thicker external envelope when preserving dimensions.

## Issues to resolve before a printable split

1. The side pockets occupy/contact the basket wall region. Attaching RFID here
   can transmit presentation/touch forces into the scale. Prefer separate fixed
   supports from the lower chassis with clearance to the weighed basket. Preserve
   approximate positions, but discuss any small local offset needed for clearance.
   The camera should also be fixed independently so its USB cable does not form
   a changing mechanical connection to the weighed assembly. The alternate is
   to weigh these accessories and use relaxed cables, but this does not isolate
   reader presses and is not the recommended direction.
2. The basket bottom and upper support plate share z = 111.5 to 113.5 mm. The
   plate footprint lies inside the basket floor, so these are duplicate solids
   in that region, not two physically seated separate components. Decide which
   part is the real floor/support and represent actual mating surfaces before
   exporting. Do not automatically shift the real load cell or change basket
   dimensions to fix a drawing overlap.
3. The main basket is a plain shell and the small side pocket has no dedicated
   lens cut in its feature chain. Confirm a clear view through an optical window
   or above the rim; a camera sitting below an opaque rim cannot observe the
   intended product path. Test actual scan-to-rest coverage before fixing angle.
4. The lower housing is modelled as a block with cutouts rather than a separately
   defined thin-walled electronics enclosure. Convert it to a hollow printed
   shell with a removable cover and display retaining bezel, preserving the
   external envelope and recess until actual hardware fit is confirmed.
5. Large 2 mm flat walls need local seam, corner and rim stiffness. Keep 2 mm as
   a starting thickness, but do not treat it as a proven payload rating. Local
   ribs/bearing shoulders and controlled joint engagement are preferable to
   arbitrarily making every wall thick.
6. FreeCAD feature history is not a ready parts list: hidden cutter extrusions,
   duplicated Body/Pad shapes and old stages must not become separate prints.

## Proposed joining system

Use a small reusable family of screw-free joints:

- Panel seams: tongue-and-groove or keyed sliding seams to align the surfaces,
  broad bearing shoulders to transfer load, and accessible snap keys to lock.
- Floor/corner connections: interlocking structural rebates/keys with a separate
  snap lock. A thin flexible hook must not be the only support for merchandise.
- Electronics, camera, RFID and display covers: short cantilever snap latches,
  with finger/tool release access for servicing. A tool-free release tab is
  preferred where access permits. Use seating ledges so a latch is not constantly
  bent by the component's weight or touchscreen pressure.

Separate small replaceable clips are useful: a failed clip can be reprinted
without discarding a wall. Integrate clips only where print orientation and
service access make it sensible. Smooth the inside of the basket; locate joint
ribs and releases on its outside, still entirely part of the weighed assembly.
Do not make literal LEGO friction studs the default for long basket seams.
Avoid a closed set of opposing slide directions that cannot be assembled; plan
the insertion order and final removable locking member before modelling joints.

The retained load-cell mount and rigid platform must remain correctly fixed and
stiff. Screw-free printed shells can latch onto an existing fixed assembly;
changing load-cell attachment itself requires separate mechanical evaluation.

## Provisional printable breakdown

| Group | Proposed separate pieces |
|---|---|
| Basket floor | Four keyed quarters if a small common FDM bed is chosen; reduce count for a larger bed |
| Basket walls | Four wall assemblies, each tiled to printer size; reinforced mating edges, smooth inner faces |
| Basket corners / rim | Integrate corner/rim features where possible, with short split joining keys as needed |
| Lower enclosure | Left/right shell sections and removable service lid; keep joins away from screen aperture where possible |
| Display | Separate snap bezel and seating cradle; no need to move it to handle now |
| Camera | Independent fixed support plus enclosure and removable retaining cover / lens surround |
| RFID | Independent fixed support plus holder and removable thin tap face / lid |
| Fixed wiring | Snap-covered channels and small cable/strain-relief clips |
| Base finishing | Segmented snap-on trim only, using real steel base as structural reference |

Example ONLY for a printer around 220 x 220 mm: dividing both dimensions of
each 300 mm-high wall into two gives 16 wall tiles, nominally about 152 x 151 mm
for wider walls and 112 x 151 mm for shorter walls, plus four floor tiles about
152 x 112 mm. These are envelope-based planning sizes before joint overlaps,
corner allocation, tolerances, brim and print orientation. A larger printer can
reduce the count substantially. Do not commit to 20 basket prints while the
printer remains undecided.

## Development sequence after discussion

1. Confirm actual sensor/support arrangement and maximum demonstration payload.
2. Select printer/material and make an exploded seam map with an assembly order.
3. Print a small seam/latch coupon with several clearances on that printer.
4. Fit one basket corner and floor connection, checking strength and release.
5. Build the full basket and fixed accessory supports; check known masses at
   centre and corners, empty return, reader/display presses, and cable influence.
6. Fit covers and verify no contact between fixed supports and basket under load.

PETG is a candidate for resilient clips; PLA can be used for rigid panels if the
clips are separate. Material choice is provisional. Choose actual clearances
from coupons, not a promised universal gap. Print orientation affects joint
strength and fit. Maximum demo payload and real load-cell mounting dimensions
remain necessary before designing the floor and loaded joints.

## References

- Prusa, modelling for printing (orientation, tolerances and material dependence):
  https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135
- Prusa, PETG material properties:
  https://help.prusa3d.com/article/petg_2059
- Formlabs, snap-fit design principles (process-specific tolerance values are
  not adopted as FDM specifications):
  https://formlabs.com/eu/blog/designing-3d-printed-snap-fit-enclosures/
