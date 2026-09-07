"""Trace the proposed built-up area on a plate, for use as a Map Warper mask.

The plates are drawn on a full topographic sheet: contours, neighbouring
villages, a title block, a legend and a balance-sheet table all sit inside the
frame. Overlaid on a slippy map that furniture covers real geography. What is
wanted is the zoned area - what the plates bound with the `limita intravilanului
propus`.

Tracing that line directly does not work. It is hand-drawn and breaks up in the
scan, and worse, wherever it runs alongside the commune boundary the draughtsman
painted orange over it, so the magenta simply is not there to follow. On Casele
Micesti that leaves a gap no amount of morphological bridging closes without
swallowing the shape.

What does work is the other side of the same boundary: everything inside the
intravilan is washed with a functional-zone colour, and everything outside is
bare topographic linework. Segmenting the wash gives the same area without
depending on an unbroken line.

The order matters. An opening first removes the coloured *lines* - the orange
commune boundary especially, which otherwise connects every trup on the sheet
into one blob - while leaving the washes, which are hundreds of pixels across.
Only then does closing merge the separate zone colours within a trup.

The result goes to Map Warper as GML in image pixel coordinates.
"""

import numpy as np
from scipy import ndimage
from shapely.geometry import Polygon

class MaskError(Exception):
    pass


def zone_wash(rgb, min_saturation=0.22, min_value=110):
    """Pixels carrying a functional-zone colour wash.

    Saturation separates the washes from the white sheet and the black linework.
    Blue-dominant pixels are dropped: streams and water run through the sheet
    regardless of whether they are inside the intravilan.
    """
    a = rgb.astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    return (sat > min_saturation) & (mx > min_value) & ~((b >= r) & (b >= g))


def regions(rgb, open_px=8, close_px=60, min_area_px=20000, exclude=()):
    """Filled built-up areas on the plate, largest first.

    `open_px` must exceed half the width of the coloured boundary lines and stay
    well under the smallest trup. `close_px` bridges the roads and forest belts
    that split a single trup into several patches of colour.

    `exclude` is a list of (left, top, right, bottom) pixel boxes. The legend
    swatches and the balance-sheet colour column are zone colours too, and sit
    inside the frame, so nothing in the image itself distinguishes them - they
    have to be named.
    """
    wash = zone_wash(rgb)
    if not wash.any():
        raise MaskError("no zone colours found on this plate")

    opened = ndimage.binary_opening(wash, structure=np.ones((3, 3)), iterations=open_px)
    closed = ndimage.binary_closing(opened, structure=np.ones((3, 3)), iterations=close_px)
    closed = ndimage.binary_fill_holes(closed)

    labels, count = ndimage.label(closed)
    if not count:
        raise MaskError("nothing survived the opening; try a smaller open_px")

    out = []
    for i in range(1, count + 1):
        blob = labels == i
        if blob.sum() < min_area_px:
            continue
        ys, xs = np.nonzero(blob)
        box = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
        if any(box[0] >= ex[0] and box[1] >= ex[1] and box[2] <= ex[2] and box[3] <= ex[3]
               for ex in exclude):
            continue
        out.append(blob)
    if not out:
        raise MaskError(f"no area reached {min_area_px} px outside the excluded boxes")
    out.sort(key=lambda m: -m.sum())
    return out


def trace(mask):
    """Outer boundary of one filled region, as a list of (x, y) pixel points.

    Moore-neighbour tracing. The region comes from a fill so it is solid and
    simply connected, which is the case this handles.
    """
    ys, xs = np.nonzero(mask)
    if not len(ys):
        raise MaskError("empty region")
    start = (int(ys.min()), int(xs[ys == ys.min()].min()))
    h, w = mask.shape

    # clockwise from west
    nbrs = [(0, -1), (-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1)]
    contour = [start]
    current, backtrack = start, 0
    for _ in range(8 * int(mask.sum()) + 1000):
        found = False
        for k in range(8):
            d = nbrs[(backtrack + k) % 8]
            ny, nx = current[0] + d[0], current[1] + d[1]
            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx]:
                prev = current
                current = (ny, nx)
                came = (prev[0] - current[0], prev[1] - current[1])
                backtrack = (nbrs.index(came) + 1) % 8
                contour.append(current)
                found = True
                break
        if not found:
            break
        if current == start and len(contour) > 2:
            break
    return [(float(x), float(y)) for y, x in contour]


def simplify(points, tolerance=6.0, max_points=400):
    """Reduce a traced outline to something worth sending over the wire.

    A traced boundary is one point per pixel step - tens of thousands of them.
    The tolerance is in pixels, so at these scales 6 px is under 4 m on the
    ground, far inside the accuracy of a hand-drawn line.
    """
    poly = Polygon(points)
    if not poly.is_valid:
        poly = poly.buffer(0)
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda p: p.area)
    for _ in range(12):
        out = poly.simplify(tolerance, preserve_topology=True)
        coords = list(out.exterior.coords)
        if len(coords) <= max_points:
            return coords, tolerance
        tolerance *= 1.6
    return coords, tolerance


GML_HEAD = ('<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs">')
GML_TAIL = "</wfs:FeatureCollection>"
GML_MEMBER = (
    '<gml:featureMember xmlns:gml="http://www.opengis.net/gml">'
    '<feature:features xmlns:feature="http://mapserver.gis.umn.edu/mapserver" '
    'fid="OpenLayers.Feature.Vector_{fid}"><feature:geometry><gml:Polygon>'
    '<gml:outerBoundaryIs><gml:LinearRing>'
    '<gml:coordinates decimal="." cs="," ts=" ">{coords}</gml:coordinates>'
    "</gml:LinearRing></gml:outerBoundaryIs></gml:Polygon>"
    "</feature:geometry></feature:features></gml:featureMember>"
)


def to_gml(rings, image_height, flip_y=True):
    """Render traced rings as the GML Map Warper stores masks in.

    Map Warper draws masks in an OpenLayers view of the unwarped image, whose y
    axis runs up from the bottom, while image rows run down. `flip_y` converts.
    """
    members = []
    for i, ring in enumerate(rings):
        pts = " ".join(
            f"{x:.3f},{(image_height - y) if flip_y else y:.3f}" for x, y in ring
        )
        members.append(GML_MEMBER.format(fid=200 + i, coords=pts))
    return GML_HEAD + "".join(members) + GML_TAIL
