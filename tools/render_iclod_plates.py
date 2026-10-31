"""Render the Iclod reglementari plates and georeference them off their own grid.

The Iclod sheets (PUG reactualizare 2007, modif. 2015) are vector PDFs, not
scans: the only raster on the page is the title-block logo, so the plate is
whatever the page renders to. Being vector, they also carry the Stereo 70 grid
exactly - a cross every 500 m, each labelled with its northing and easting as
real text. So nothing needs reading by eye: the labels give the coordinates, the
four arm segments of each cross give its position, and a least-squares affine
over every cross on the sheet turns pixels into Stereo 70.

Labels are only used to place the lattice. Each cross is then snapped to the
nearest node of the fitted grid, so a mistyped label (Orman has a "41100")
cannot pull the fit, and crosses that still sit off the fit - an arm merged into
a road or a hatch line - are dropped before the final solve. The grid step is
read off the labels: 500 m on most sheets, 400 m on Fundatura.

The plates also carry legend, tables and title block inside the frame, and the
sheets overlap - Iclod's covers half of Iclozel and the edge of Livada. So each
plate is masked to its proposed intravilan. That is the solid red 2.64 pt line,
"limita intravilan propus 2007" (the 1999 limit is the same red, dashed, and
comes apart into short separate segments, which a length threshold drops). The
line is not closed: where the limit runs along the commune boundary or another
sheet's limit it is drawn as that instead. A concave hull over the red line
bridges those gaps while still following the outline. EXCLUDE removes red lines
that belong to a neighbouring sheet's intravilan.

A single hull cannot hold a village in several trupuri, and on Iclozel it also
cut corners across the bends of the long T1. There CLOSE_PX is used instead:
each red line is widened by that much, so gaps up to twice it close up, the
enclosed area is filled and the result shrunk back - one polygon per trup.

Writes, per plate, the upload image and a JSON with the control points
(pixel -> WGS84), the fit residuals and the mask outline in image pixels.

    python tools/render_iclod_plates.py "C:/path/to/RLU si planse"
"""
import json
import os
import re
import sys

import fitz
import numpy as np
import shapely
from PIL import Image, ImageDraw
from pyproj import Transformer
from shapely.geometry import LineString, MultiPoint, Polygon
from shapely.ops import unary_union

Image.MAX_IMAGE_PIXELS = None

OUT = os.path.join("export", "iclod")
DPI = 150            # 1:5000 sheet, so a pixel is ~0.85 m on the ground
MAX_RESID_M = 3
STEREO70_TO_WGS84 = Transformer.from_crs("EPSG:3844", "EPSG:4326", always_xy=True)

# Red limit lines to leave out of a plate's mask, as fractions of the rendered
# image (left, top, right, bottom): on Livada, the trup with Iclod's poultry farm
# (UTR Pae Iclod, on Iclod's sheet too); on Fundatura, Iclod's limit along the
# right edge.
EXCLUDE = {"Livada": [(0, 0.55, 0.33, 1)], "Fundatura": [(0.93, 0, 1, 1)]}
HULL_RATIO = 0.04    # shapely concave_hull ratio; lower follows the line closer
HULL_PAD_PX = 12     # ~10 m outside the line, so the limit itself stays visible
CLOSE_PX = {"Iclozel": 80}   # plates masked by closing the red line, not by a hull

# (plate number on the sheet, village, file name)
PLATES = [
    ("1.2", "Iclod",     "A0 lat REGLEMEN ICLOD.pdf"),
    ("2.2", "Iclozel",   "A0 lat REGLEMENT ICLOZEL.pdf"),
    ("3.2", "Livada",    "A0 lat REGLEMENT LIVADA.pdf"),
    ("4.2", "Orman",     "A0 lat REGLEMENT ORMAN.pdf"),
    ("5.2", "Fundatura", "A0 lat REGLEMENT FUNDATURA.pdf"),
]


def labels(page):
    """Grid labels as (value, centre) in unrotated page space."""
    northings, eastings = [], []
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        if not re.fullmatch(r"\d{6}", text):
            continue
        value, centre = int(text), ((x0 + x1) / 2, (y0 + y1) / 2)
        if 590000 <= value <= 630000:
            northings.append((value, centre))
        elif 390000 <= value <= 430000:
            eastings.append((value, centre))
    return northings, eastings


def arm_segments(page):
    """Straight segments the length of a cross arm (~27 pt)."""
    segs = []
    for d in page.get_drawings():
        for item in d["items"]:
            if item[0] != "l":
                continue
            a, b = item[1], item[2]
            if 20 <= abs(b - a) <= 34:
                segs.append((a.x, a.y, b.x, b.y))
    return np.array(segs)


def cross_centre(segs, near, radius=45):
    """Where the four arms of the cross nearest `near` meet, or None.

    An arm is a segment with one end within a couple of points of another arm's
    end; the centre is the mean of those inner ends.
    """
    mid = (segs[:, :2] + segs[:, 2:]) / 2
    cand = segs[np.hypot(*(mid - near).T) < radius]
    if len(cand) < 4:
        return None
    ends = np.vstack([cand[:, :2], cand[:, 2:]])
    best = None
    for e in ends:
        close = ends[np.hypot(*(ends - e).T) < 4]
        if len(close) >= 4 and (best is None or len(close) > len(best)):
            best = close
    return None if best is None else best.mean(axis=0)


def fit_affine(src, dst):
    a = np.hstack([src, np.ones((len(src), 1))])
    coef, *_ = np.linalg.lstsq(a, dst, rcond=None)
    return coef


def apply(coef, pts):
    return np.hstack([pts, np.ones((len(pts), 1))]) @ coef


def georeference(page):
    """Crosses in rendered pixels, paired with their Stereo 70 (E, N)."""
    northings, eastings = labels(page)
    segs = arm_segments(page)
    rot = page.rotation_matrix
    scale = DPI / 72

    found = []
    for e_val, e_pos in eastings:
        n_val, n_pos = min(northings, key=lambda n: np.hypot(n[1][0] - e_pos[0],
                                                             n[1][1] - e_pos[1]))
        if np.hypot(n_pos[0] - e_pos[0], n_pos[1] - e_pos[1]) > 40:
            continue
        near = np.array([(e_pos[0] + n_pos[0]) / 2, (e_pos[1] + n_pos[1]) / 2])
        c = cross_centre(segs, near)
        if c is None:
            continue
        p = fitz.Point(*c) * rot
        found.append(((p.x * scale, p.y * scale), (e_val, n_val)))

    px = np.array([f[0] for f in found])
    en = np.array([f[1] for f in found], dtype=float)
    step = grid_step(en)
    # Fit, snap every cross to its nearest lattice node, drop the ones that
    # still disagree, refit.
    keep = np.ones(len(px), bool)
    for _ in range(4):
        coef = fit_affine(px[keep], en[keep])
        en = np.round(apply(coef, px) / step) * step
        resid = np.hypot(*(apply(coef, px) - en).T)
        keep = resid < max(MAX_RESID_M, np.median(resid) * 3)
    coef = fit_affine(px[keep], en[keep])
    resid = np.hypot(*(apply(coef, px[keep]) - en[keep]).T)
    return px[keep], en[keep], coef, resid, step, int((~keep).sum())


def grid_step(en):
    """Spacing of the labelled lattice, from the most common label difference."""
    diffs = []
    for axis in (0, 1):
        v = np.unique(en[:, axis])
        diffs += list(np.diff(v))
    diffs = [d for d in diffs if d > 0]
    return float(min(set(diffs), key=lambda d: (-diffs.count(d), d)))


def pick_gcps(px, en, n=16):
    """A spread of crosses: farthest-point sampling from the sheet's corners."""
    chosen = [int(np.argmin(px.sum(axis=1)))]
    while len(chosen) < min(n, len(px)):
        d = np.min([np.hypot(*(px - px[i]).T) for i in chosen], axis=0)
        chosen.append(int(np.argmax(d)))
    gcps = []
    for i in chosen:
        lon, lat = STEREO70_TO_WGS84.transform(en[i, 0], en[i, 1])
        gcps.append({"x": round(float(px[i, 0]), 1), "y": round(float(px[i, 1]), 1),
                     "lon": round(lon, 7), "lat": round(lat, 7),
                     "easting": int(en[i, 0]), "northing": int(en[i, 1])})
    return gcps


def is_red_limit(d):
    c, w = d.get("color"), d.get("width") or 0
    return bool(c) and abs(c[0] - 1) < 0.05 and c[1] < 0.1 and c[2] < 0.1 and 2.0 <= w <= 3.5


def mask(page, village, size):
    """Outline of the proposed intravilan, in rendered pixels."""
    W, H = size
    rot, scale = page.rotation_matrix, DPI / 72
    # The legend's own sample of the line would pull the hull out to it.
    legend = [fitz.Rect(r.x0 - 130, r.y0 - 130, r.x1 + 130, r.y1 + 130)
              for r in page.search_for("LIMITA INTRAVILAN PROPUS 2007")]
    canvas = Image.new("L", size, 0)
    draw = ImageDraw.Draw(canvas)
    lines = []
    for d in page.get_drawings():
        if not is_red_limit(d):
            continue
        length = sum(np.hypot(*(it[-1] - it[1])) for it in d["items"] if it[0] in "lc")
        centre = fitz.Point((d["rect"].x0 + d["rect"].x1) / 2, (d["rect"].y0 + d["rect"].y1) / 2)
        if length < 40 or (length < 200 and any(centre in r for r in legend)):
            continue
        c = centre * rot
        fx, fy = c.x * scale / W, c.y * scale / H
        if any(x0 <= fx <= x1 and y0 <= fy <= y1 for x0, y0, x1, y1 in EXCLUDE.get(village, [])):
            continue
        for it in d["items"]:
            if it[0] in "lc":
                pts = [((q * rot).x * scale, (q * rot).y * scale) for q in it[1:]]
                draw.line(pts, fill=255, width=5)
                lines.append(LineString(pts))
    close = CLOSE_PX.get(village)
    if close:
        widened = unary_union([line.buffer(close) for line in lines])
        filled = unary_union([Polygon(g.exterior) for g in getattr(widened, "geoms", [widened])])
        outline = filled.buffer(HULL_PAD_PX - close)
    else:
        ys, xs = np.nonzero(np.asarray(canvas)[::4, ::4])
        hull = shapely.concave_hull(MultiPoint(np.c_[xs * 4, ys * 4]), ratio=HULL_RATIO)
        outline = hull.buffer(HULL_PAD_PX)
    outline = outline.simplify(3)
    return [[(round(x, 1), round(y, 1)) for x, y in g.exterior.coords]
            for g in getattr(outline, "geoms", [outline]) if g.area > 2000]


def main(src):
    os.makedirs(OUT, exist_ok=True)
    for number, village, pdf in PLATES:
        page = fitz.open(os.path.join(src, pdf))[0]
        pix = page.get_pixmap(dpi=DPI)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        img_path = os.path.join(OUT, f"{village}.png")
        image.save(img_path, optimize=True)

        px, en, coef, resid, step, dropped = georeference(page)
        m_per_px = np.hypot(*coef[0])
        gcps = pick_gcps(px, en)
        info = {"plate": number, "village": village, "file": pdf,
                "image": img_path, "width": image.width, "height": image.height,
                "grid_m": step, "crosses": len(px), "dropped": dropped, "m_per_px": round(float(m_per_px), 4),
                "rms_m": round(float(np.sqrt((resid ** 2).mean())), 2),
                "max_m": round(float(resid.max()), 2),
                "affine_px_to_stereo70": coef.round(6).tolist(),
                "gcps": gcps,
                "mask": mask(page, village, image.size)}
        with open(os.path.join(OUT, f"{village}.json"), "w", encoding="utf-8") as fh:
            json.dump(info, fh, indent=2)
        print(f"{village:10s} {image.width}x{image.height}  "
              f"{os.path.getsize(img_path) / 1e6:.1f} MB  grid {step:.0f} m  "
              f"{len(px)} crosses ({dropped} dropped)  "
              f"{m_per_px:.3f} m/px  rms {info['rms_m']} m  max {info['max_m']} m")


if __name__ == "__main__":
    main(sys.argv[1])
