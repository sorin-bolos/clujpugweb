"""Cut the legend symbols for comuna Iclod off the 2007 (modif. 2015) "Reglementari" plates.

The five sheets - Iclod, Iclozel, Fundatura, Livada, Orman - share one legend
vocabulary, but no sheet carries all of it: Iclod alone has the zona centrala
limit and the proposed agricultural units, Fundatura and Livada the national
road and the railway, Iclozel the street symbols, Orman the waste dump, and only
Iclod draws a swatch for the forests. Each symbol is taken from the
sheet where it is drawn cleanest.

The legend boxes are printed straight over the topographic base, so a plain crop
picks up contour dots and parcel lines. The plates are vector PDFs, though, so a
symbol can be redrawn from its own paths on a blank page instead. The base is
recognisable by drawing order: it is one long run of thin (0.48 pt) black
strokes in the second half of each page's content stream, which the legend never
uses for anything but street symbols. Those, and the symbols that carry text
(Le, PUD, GEO, A), are cropped as rendered instead ("raw").

Positions are in display coordinates (after the page's /Rotate), relative to the
first line of the legend label: the symbol box runs from `left` points to the
left of the label for `width` points, centred `dy` below the label's top.

    python tools/extract_iclod_legend.py "C:/path/to/RLU si planse"
"""
import os
import sys

import fitz
import numpy as np
from PIL import Image
from scipy import ndimage

OUT = r"ClujPugWeb\wwwroot\Images\Legend\Iclod"
DPI = 288   # a 66 pt swatch comes out ~260 px, 4x the 60 px CSS box

PLATES = {
    "Iclod": "A0 lat REGLEMEN ICLOD.pdf",
    "Iclozel": "A0 lat REGLEMENT ICLOZEL.pdf",
    "Fundatura": "A0 lat REGLEMENT FUNDATURA.pdf",
    "Livada": "A0 lat REGLEMENT LIVADA.pdf",
    "Orman": "A0 lat REGLEMENT ORMAN.pdf",
}

# Where the topographic base starts, as a fraction of the page's drawing order.
BASE_FROM = {"Iclod": 0.50, "Iclozel": 0.38, "Fundatura": 0.44, "Livada": 0.43}

# (name, plate, label top, label left, left, width, height, dy, mode, drop)
# drop: colours that belong to the map under the symbol - "blue" streams,
# "yellow" dotted commune roads.
SYMBOLS = [
    # Limite
    ("LimitaIntravilan1990",   "Iclozel",   597, 1235, 105, 100, 14,  0, "redraw", ()),
    ("LimitaIntravilan1999",   "Iclozel",   620, 1235, 105, 100, 14,  0, "redraw", ()),
    ("LimitaIntravilan2007",   "Iclozel",   644, 1235, 105, 100, 14,  0, "redraw", ()),
    ("LimitaUat",              "Iclozel",   667, 1235, 105, 100, 14,  0, "redraw", ()),
    ("LimitaZonaCentrala",     "Iclod",     302, 2293, 105, 100, 18,  0, "redraw", ("blue",)),
    # Zonificare functionala
    ("ZonaLocuinte",           "Iclod",     340, 2290,  73,  67, 20,  6, "redraw", ("blue",)),
    ("ZonaLocuinteCentru",     "Iclod",     387, 2292,  78,  63, 18, 12, "redraw", ("blue",)),
    ("ZonaInstitutiiPublice",  "Iclozel",   757, 1232,  78,  69, 18,  0, "redraw", ()),
    ("ZonaIndustriala",        "Iclod",     460, 2290,  76,  69, 18,  0, "redraw", ()),
    ("ZonaAgricola",           "Fundatura", 1613, 2014, 88,  69, 18,  0, "redraw", ()),
    ("ZonaGospodarieComunala", "Iclozel",   781, 1232,  78,  69, 18,  0, "redraw", ()),
    ("SpatiiVerzi",            "Iclozel",   808, 1232,  78,  69, 18,  0, "redraw", ()),
    ("Ape",                    "Iclozel",   857, 1232,  79,  69, 18,  0, "redraw", ()),
    ("ApeCursuriMinore",       "Iclozel",   884, 1232, 105, 100, 22,  0, "redraw", ()),
    ("TerenuriForestiere",     "Iclod",     555, 2290,  77,  70, 26, -1, "redraw", ()),
    # Zone functionale propuse
    ("ExtindereLocuinte",      "Iclozel",   955, 1234,  80,  69, 22, 10, "redraw", ()),
    ("ExtindereIndustriala",   "Iclod",     730, 2290,  77,  69, 18,  0, "redraw", ()),
    ("ExtindereAgricola",      "Iclod",     754, 2290,  77,  69, 18,  0, "redraw", ()),
    ("IndicativUtr",           "Iclozel",  1005, 1232,  60,  54, 18,  2, "raw",    ()),
    # Cai de comunicatie
    ("DrumNational",           "Fundatura", 1944, 2014, 88,  79, 12,  0, "redraw", ()),
    ("DrumJudetean",           "Fundatura", 1961, 2014, 88,  79, 22,  4, "redraw", ()),
    ("DrumComunal",            "Fundatura", 1978, 2014, 88,  79, 16,  6, "redraw", ()),
    ("CaleFerata",             "Fundatura", 2004, 2014, 88,  79, 12,  0, "redraw", ()),
    ("DrumInteresLocal",       "Fundatura", 2023, 2014, 88,  79, 14,  6, "redraw", ()),
    ("StraziLargire",          "Iclozel",  1311, 1304,  55,  50, 10,  0, "raw",    ()),
    ("StraziTraseeNoi",        "Iclozel",  1328, 1304,  55,  38, 10,  0, "raw",    ("blue", "specks")),
    ("TraseePietonale",        "Iclozel",  1345, 1304,  55,  38, 10,  0, "raw",    ("blue", "specks")),
    ("CfDezafectare",          "Iclod",     160,  514,  50,  45, 14,  0, "raw",    ()),
    ("PoduriPropuse",          "Fundatura", 267, 1177,  91,  83, 28,  3, "raw",    ()),
    ("IntersectiiRutiere",     "Livada",   1930, 1544, 122, 118, 32,  0, "raw",    ()),
    ("TreceriCf",              "Livada",   1947, 1544, 126, 124, 26,  9, "raw",    ()),
    # Zone de protectie / interdictii
    ("ProtectiePatrimoniu",    "Iclozel",  1056, 1234,  80,  70, 30,  7, "redraw", ()),
    ("ProtectieSanitara",      "Iclozel",  1083, 1234,  80,  70, 32,  9, "redraw", ()),
    ("ProtectieTehnica",       "Iclozel",  1119, 1234,  80,  70, 32,  9, "redraw", ("yellow",)),
    ("InterdictieTemporara",   "Iclozel",  1165, 1234,  80,  70, 20, -5, "redraw", ("yellow",)),
    ("InterdictieDefinitiva",  "Iclozel",  1192, 1234,  80,  70, 20, -6, "redraw", ("yellow",)),
    ("SituriArheologice",      "Iclod",     842, 2290,  60,  50, 26,  0, "raw",    ()),
    ("ProtectieCf",            "Fundatura", 306,  774,  58,  53, 28, 12, "redraw", ()),
    # Reglementari
    ("ZonaPud",                "Iclozel",  1484, 1279,  55,  47, 26, 13, "raw",    ()),
    ("PanteGeo",               "Iclozel",  1434, 1279,  55,  40, 26, 10, "raw",    ()),
    ("PanteInterdictieDefinitiva", "Iclozel", 1382, 1279, 58, 48, 26, 8, "redraw", ("blue", "yellow")),
    ("ZonaInundabila",         "Fundatura", 271,  774,  58,  53, 24,  6, "redraw", ()),
    ("ExcesUmiditate",         "Fundatura", 354,  774,  58,  53, 24,  6, "redraw", ()),
    ("MasuriProtectie",        "Iclozel",  1533, 1279,  78,  71, 26,  8, "redraw", ()),
    ("ConditiiFundare",        "Orman",    1737, 1459,  59,  52, 28, 27, "raw",    ()),
    ("DepozitDeseuri",         "Orman",    2003, 1457,  75,  52, 34, 1.5, "raw",   ()),
]


def is_base(d, last, plate):
    return (d["type"] == "s" and (d.get("color") or ()) == (0.0, 0.0, 0.0)
            and abs((d.get("width") or 0) - 0.48) < 0.01
            and d["seqno"] > BASE_FROM[plate] * last)


def dropped(d, drop):
    r, g, b = d.get("color") or d.get("fill") or (1, 1, 1)
    return (("blue" in drop and b > 0.6 and r < 0.3)
            or ("yellow" in drop and r > 0.8 and g > 0.8 and b < 0.3))


def redraw(page, drawings, last, plate, box, drop):
    """Render `box` from the page's own paths, minus the base map."""
    clip = box * page.derotation_matrix
    doc = fitz.open()
    blank = doc.new_page(width=page.mediabox.width, height=page.mediabox.height)
    blank.set_rotation(page.rotation)
    shape = blank.new_shape()
    for d in drawings:
        # Grown a little: a horizontal line has an empty rect, which never intersects.
        if not (d["rect"] + (-0.5, -0.5, 0.5, 0.5)).intersects(clip):
            continue
        if is_base(d, last, plate) or dropped(d, drop):
            continue
        for item in d["items"]:
            if item[0] == "l":
                shape.draw_line(item[1], item[2])
            elif item[0] == "c":
                shape.draw_bezier(*item[1:5])
            elif item[0] == "re":
                shape.draw_rect(item[1])
            elif item[0] == "qu":
                shape.draw_quad(item[1])
        cap = d.get("lineCap") or 0
        shape.finish(
            color=d.get("color") if d["type"] != "f" else None,
            fill=d.get("fill") if d["type"] != "s" else None,
            width=d.get("width") or 0, dashes=d.get("dashes"),
            closePath=d.get("closePath", False), even_odd=d.get("even_odd", False),
            lineCap=max(cap) if isinstance(cap, (tuple, list)) else cap,
            lineJoin=d.get("lineJoin") or 0,
            fill_opacity=d.get("fill_opacity") or 1,
            stroke_opacity=d.get("stroke_opacity") or 1)
    shape.commit()
    return blank.get_pixmap(dpi=DPI, clip=box)


def despeckle(image, drop):
    """Clean a raw crop: the street symbols are thin black like the base map, so
    they cannot be redrawn without it, but what the base leaves on them is a
    stream's blue dots and specks of dotted contour."""
    a = np.asarray(image).copy()
    r, g, b = (a[..., i].astype(int) for i in range(3))
    if "blue" in drop:
        a[(b > 150) & (r < 120)] = 255
    if "specks" in drop:
        dark = a.sum(axis=2) < 384
        labels, count = ndimage.label(dark, structure=np.ones((3, 3)))
        sizes = ndimage.sum(dark, labels, range(1, count + 1))
        small = np.isin(labels, 1 + np.nonzero(sizes < 80)[0])
        a[small] = 255
    return Image.fromarray(a)


def main(src):
    os.makedirs(OUT, exist_ok=True)
    pages = {}
    for name, plate, top, left_x, left, width, height, dy, mode, drop in SYMBOLS:
        if plate not in pages:
            page = fitz.open(os.path.join(src, PLATES[plate]))[0]
            drawings = page.get_drawings()
            pages[plate] = (page, drawings, drawings[-1]["seqno"])
        page, drawings, last = pages[plate]
        cy = top + 5 + dy
        box = fitz.Rect(left_x - left, cy - height / 2, left_x - left + width, cy + height / 2)
        if mode == "raw":
            pix = page.get_pixmap(dpi=DPI, clip=box)
        else:
            pix = redraw(page, drawings, last, plate, box, drop)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        if mode == "raw" and drop:
            image = despeckle(image, drop)
        image.save(os.path.join(OUT, name + ".png"), optimize=True)
        print(f"{name:28s} {image.width:4d}x{image.height:3d}  {plate} {mode}")


if __name__ == "__main__":
    main(sys.argv[1])
