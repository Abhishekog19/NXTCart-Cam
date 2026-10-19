"""Read the supplied FreeCAD archive without executing embedded content.

Produces a topology-edge preview and a dimensional inventory, not meshed solids
or print files. Circular edges are approximated by endpoint chords in preview.
"""
from pathlib import Path
import json
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SOURCE = Path(r"C:\Users\ADMIN\Downloads\3D model.zip")


def read_brep(text):
    lines = text.splitlines()
    pos = next(i for i, line in enumerate(lines) if line.startswith("Locations "))
    count = int(lines[pos].split()[1])
    locations = [np.eye(4)]
    pos += 1
    for _ in range(count):
        parts = lines[pos].split()
        pos += 1
        if parts[0] == "1":
            mat = np.eye(4)
            for row in range(3):
                mat[row] = list(map(float, lines[pos].split()))
                pos += 1
        elif parts[0] == "2":
            mat = np.eye(4)
            values = list(map(int, parts[1:]))
            for index in range(0, len(values) - 1, 2):
                loc, power = values[index:index + 2]
                # OCCT serializes the datum chain in the reverse of the
                # resulting matrix application order.
                mat = np.linalg.matrix_power(locations[loc], power) @ mat
        else:
            raise ValueError(f"Unexpected location: {parts}")
        locations.append(mat)
    match = re.search(r"(?m)^TShapes (\d+)\s*$", text)
    count = int(match[1])
    body = text[match.end():]
    starts = list(re.finditer(r"(?m)^(Ve|Ed|Wi|Fa|Sh|So|Co|CS)\s*$", body))
    assert len(starts) == count, (len(starts), count)
    shapes = {}
    root = None
    for i, start in enumerate(starts):
        block = body[start.end():starts[i + 1].start() if i + 1 < count else None]
        flags = re.search(r"(?m)^[01]{7}\s*$", block)
        assert flags, block[:200]
        geom, tail = block[:flags.start()].strip(), block[flags.end():]
        refs, after = tail.split("*", 1)
        children = [(int(a), int(b)) for a, b in re.findall(r"[+-](\d+)\s+(\d+)", refs)]
        shape = {"type": start[1], "children": children}
        if start[1] == "Ve":
            shape["point"] = np.array(list(map(float, geom.splitlines()[1].split())) + [1.0])
        shapes[count - i] = shape
        if i + 1 == count:
            ref = re.search(r"[+-](\d+)\s+(\d+)", after)
            root = (int(ref[1]), int(ref[2]))

    def vertices(index, mat):
        shape = shapes[index]
        if shape["type"] == "Ve":
            return [(mat @ shape["point"])[:3]]
        return [v for child, loc in shape["children"] for v in vertices(child, mat @ locations[loc])]

    segments = []

    def edges(index, mat):
        shape = shapes[index]
        if shape["type"] == "Ed":
            pts = vertices(index, mat)
            if len(pts) >= 2 and np.linalg.norm(pts[0] - pts[1]) > 1e-7:
                segments.append([pts[0].tolist(), pts[1].tolist()])
            return
        for child, loc in shape["children"]:
            edges(child, mat @ locations[loc])

    mat = locations[root[1]]
    points = np.array(vertices(root[0], mat))
    edges(root[0], mat)
    assert len(points) > 0
    return {"min": points.min(axis=0).tolist(), "max": points.max(axis=0).tolist(),
            "size": np.ptp(points, axis=0).tolist(), "segments": segments}


NAMES = {
    "Body": ("Base reference plate", "#657184"),
    "Extrude": ("Central support placeholder", "#996641"),
    "Extrude001": ("Upper support plate", "#bd8740"),
    "Thickness": ("Weighed basket", "#127f87"),
    "Cut003": ("Lower display / electronics housing", "#4e63b4"),
    "Thickness001": ("Small side pocket (camera candidate)", "#ba5a75"),
    "Cut004": ("Large side pocket (RFID candidate)", "#8951b4"),
}


def font(size, bold=False):
    path = Path("C:/Windows/Fonts") / ("arialbd.ttf" if bold else "arial.ttf")
    return ImageFont.truetype(str(path), size)


def preview(objects):
    im = Image.new("RGB", (2200, 1680), "#f5f7fa")
    draw = ImageDraw.Draw(im)
    draw.text((55, 35), "Your supplied CAD — geometry inspection", font=font(48, True), fill="#18263b")
    draw.text((55, 100), "Native topology edges; hidden edges shown. Units: mm. No model edits or snap joints added.", font=font(26), fill="#536174")
    panels = [(45, 165, 1075, 770), (1125, 165, 2155, 770), (45, 815, 1075, 1420), (1125, 815, 2155, 1420)]
    views = [
        ("ISOMETRIC", np.array([[0.83, -0.56, 0.0], [-0.28, -0.41, 0.87]])),
        ("FRONT — looking from display side", np.array([[1., 0., 0.], [0., 0., 1.]])),
        ("TOP — display housing at bottom", np.array([[1., 0., 0.], [0., 1., 0.]])),
        ("SIDE — basket above lower housing", np.array([[0., 1., 0.], [0., 0., 1.]])),
    ]
    for box, (title, projection) in zip(panels, views):
        left, top, right, bottom = box
        draw.rounded_rectangle(box, radius=15, fill="white", outline="#ccd4df", width=2)
        draw.text((left + 25, top + 20), title, font=font(27, True), fill="#24334b")
        all_pts = np.array([point for obj in objects.values() for edge in obj["segments"] for point in edge])
        projected = all_pts @ projection.T
        low, high = projected.min(0), projected.max(0)
        width, height = right - left - 110, bottom - top - 130
        scale = min(width / (high[0] - low[0]), height / (high[1] - low[1]))
        center = (low + high) / 2
        origin = np.array([(left + right) / 2, (top + bottom + 40) / 2])
        for name, obj in objects.items():
            for edge in obj["segments"]:
                projected_edge = (np.array(edge) @ projection.T - center) * scale
                projected_edge[:, 1] *= -1
                coords = projected_edge + origin
                draw.line([tuple(coords[0]), tuple(coords[1])], fill=NAMES[name][1], width=3)
    y = 1450
    for i, (name, (label, color)) in enumerate(NAMES.items()):
        x = 55 + (i % 3) * 720
        yy = y + (i // 3) * 53
        draw.rectangle((x, yy + 6, x + 25, yy + 25), fill=color)
        draw.text((x + 38, yy), label, font=font(22), fill="#24334b")
    draw.text((55, 1620), "Preview uses edge endpoints; curved corners are simplified. Pocket purpose is inferred from size/location.", font=font(22), fill="#536174")
    im.save(HERE / "source-cad-edge-preview.png")


def main():
    if not (HERE / "original-concept.FCStd").exists():
        shutil.copyfile(SOURCE, HERE / "original-concept.FCStd")
    results = {}
    with zipfile.ZipFile(SOURCE) as archive:
        doc = ET.fromstring(archive.read("Document.xml"))
        for name in NAMES:
            obj = doc.find(f'./ObjectData/Object[@name="{name}"]')
            part = obj.find('./Properties/Property[@name="Shape"]/Part')
            results[name] = read_brep(archive.read(part.attrib["file"]).decode())
        fusion = read_brep(archive.read("Fusion.Shape.brp").decode())
        # A subtraction must not enlarge its starting solid. This independently
        # checks compound-location interpretation for the tilted display cuts.
        assert np.all(np.array(results["Cut003"]["min"]) >= np.array(fusion["min"]) - 1e-6)
        assert np.all(np.array(results["Cut003"]["max"]) <= np.array(fusion["max"]) + 1e-6)
        assert np.allclose(results["Extrude"]["size"], [45, 45, 110])
        assert np.allclose(results["Thickness001"]["size"], [12, 44, 62])
        assert np.allclose(results["Cut004"]["size"], [18, 78, 110])
        # Transform-aware edges verify extrusion heights even when a BREP reuses
        # the same vertex at multiple locations rather than storing new points.
        summary = {name: {k: v for k, v in data.items() if k != "segments"} for name, data in results.items()}
        summary["document_version"] = doc.attrib
        summary["method"] = "BRep topology traversal, including instance-location transforms; vertex bounds, no CAD-kernel solid validation"
        summary["display_cutout_sketch_mm"] = [120, 78]
        summary["wall_thickness_feature_mm"] = 2
        (HERE / "dimensions.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (HERE / "edges.json").write_text(json.dumps(results), encoding="utf-8")
        preview(results)
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
