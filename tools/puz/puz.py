"""PUZ pipeline: from a council decision PDF to a georeferenced overlay on the site.

Every PUZ is described by a small recipe, puzuri/<localitate>/<id>.json: where the
decision lives, which PDF page holds the regulations plate, the boundary coordinates
transcribed from the plate's "Inventar de coordonate", the pixel position of some of
those points on the plate, and the crops (legend, areas to mask out). Everything else
is derived from it and can be rebuilt at any time:

    py -3.13 tools/puz/puz.py new      2026 597                           # recipe skeleton from the listing
    py -3.13 tools/puz/puz.py fetch    puzuri/cluj-napoca/2026-597.json   # PDF + page contact sheet
    py -3.13 tools/puz/puz.py render   puzuri/cluj-napoca/2026-597.json   # plate page at full resolution
    py -3.13 tools/puz/puz.py grid     puzuri/cluj-napoca/2026-597.json x0 y0 x1 y1 [--scale S --step N]
    py -3.13 tools/puz/puz.py predict  puzuri/cluj-napoca/2026-597.json   # where the other points should be
    py -3.13 tools/puz/puz.py vertices puzuri/cluj-napoca/2026-597.json 10 12 13 ...
    py -3.13 tools/puz/puz.py build    puzuri/cluj-napoca/2026-597.json   # checks, warp, legend, publish

The decision's documents are kept as a backup in puzuri/<localitate>/documente/<id>/
(ignored by git, never served), in case the city hall moves or removes them; their
checksums go in puzuri/<localitate>/documente/SHA256SUMS, which is tracked. Renders
and checks go to puz_cache/<id>/ (ignored, rebuildable). Published files go to
ClujPugWeb/wwwroot/puz/<id>/ and an entry in ClujPugWeb/wwwroot/puz/puz.json.

Coordinates in recipes are written the way Romanian plates print them:
[Nord (x), Est (Y)] in Stereo 70 (EPSG:3844).
"""

import argparse
import hashlib
import html as htmlmod
import io
import json
import math
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CACHE = os.path.join(ROOT, "puz_cache")
WWW = os.path.join(ROOT, "ClujPugWeb", "wwwroot")
INDEX = os.path.join(WWW, "puz", "puz.json")
UA = {"User-Agent": "clujpug.ro PUZ pipeline"}

# Quality gates. A transcription error shows up as an area mismatch; a misplaced
# control point or a misread digit shows up as a residual of metres, not decimetres.
AREA_TOLERANCE = 0.01          # relative
# Picking a vertex is good to 2-3 pixels whatever the scale, so the residual gate is
# 1 m or 4 plate pixels, whichever is larger: 1 m at 1:250-1:1000, ~1.3 m at 1:2500.
MAX_RESIDUAL_M = 1.0
MAX_RESIDUAL_PX = 4
OUTPUT_RES_3857 = 0.07         # metres (EPSG:3857 units) per output pixel, ~z21

Image.MAX_IMAGE_PIXELS = None


# --- recipe and paths ------------------------------------------------------------

def load(recipe_path):
    with open(recipe_path, encoding="utf-8") as f:
        r = json.load(f)
    r["_path"] = recipe_path
    return r


def cache_dir(r):
    d = os.path.join(CACHE, r["id"])
    os.makedirs(d, exist_ok=True)
    return d


def docs_dir(r):
    d = os.path.join(os.path.dirname(os.path.abspath(r["_path"])), "documente", r["id"])
    os.makedirs(d, exist_ok=True)
    return d


def doc_name(url):
    return urllib.parse.unquote(os.path.basename(url.split("?")[0]))


def pdf_path(r):
    return os.path.join(docs_dir(r), doc_name(r["hcl"]["pdf"]))


def plate_path(r):
    p = r["plansa"]
    return os.path.join(cache_dir(r), "plate-p%d-%ddpi.png" % (p["pagina_pdf"], p.get("dpi", 200)))


def points_en(r):
    """Boundary vertices from the coordinate inventory, {name: (E, N)} from [N, E] pairs."""
    return {k: (v[1], v[0]) for k, v in r["coordonate"].get("puncte", {}).items()}


def known_en(r):
    """Every point with known ground coordinates: the boundary vertices plus `repere`,
    such as labelled Stereo 70 grid crosses on plates that print no inventory."""
    pts = points_en(r)
    pts.update({k: (v[1], v[0]) for k, v in r.get("repere", {}).items()})
    return pts


def boundary_digitized(r):
    return not points_en(r) and bool(r.get("limita_px"))


def ring_en(r, pe=None, pn=None):
    """The PUZ boundary in Stereo 70: the inventory if the plate has one, otherwise the
    boundary traced on the plate (`limita_px`) carried over by the pixel fit."""
    pts = points_en(r)
    if pts:
        order = r["coordonate"].get("ordine") or sorted(pts, key=lambda k: int(re.sub(r"\D", "", k) or 0))
        return [pts[k] for k in order]
    if r.get("limita_px") and pe is not None:
        return [(float(pe @ [x, y, 1]), float(pn @ [x, y, 1])) for x, y in r["limita_px"]]
    sys.exit("recipe has neither coordonate.puncte nor limita_px")


def font(size, bold=False):
    try:
        return ImageFont.truetype("arialbd.ttf" if bold else "arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


# --- new recipe ----------------------------------------------------------------------

LISTING = "https://primariaclujnapoca.ro/consiliu-local/hotarari-de-consiliu/?_sfm_hotarare_an={an}&_sfm_hotarare_nr={nr}"
MONTHS_RO = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august",
             "septembrie", "octombrie", "noiembrie", "decembrie"]


def page_lines(url):
    html_text = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode("utf-8", "replace")
    txt = re.sub(r"<script.*?</script>|<style.*?</style>", "", html_text, flags=re.S)
    return html_text, [l.strip() for l in htmlmod.unescape(re.sub(r"<[^>]+>", "\n", txt)).split("\n") if l.strip()]


def cmd_new(args):
    """Recipe skeleton from the council's decision listing: title, session date, page, PDF."""
    out = os.path.join(ROOT, "puzuri", args.folder, "%d-%d.json" % (args.an, args.nr))
    if os.path.exists(out):
        sys.exit("already exists: " + out)
    raw, lines = page_lines(LISTING.format(an=args.an, nr=args.nr))
    i = next((k for k, l in enumerate(lines) if l == "Hotărârea %d/%d" % (args.nr, args.an)), None)
    if i is None:
        sys.exit("decision %d/%d not found in the listing" % (args.nr, args.an))
    title, date_ro = lines[i + 2], lines[i - 1]
    m = re.match(r"(\d{1,2}) (\w+) (\d{4})$", date_ro)
    date = "%s-%02d-%02d" % (m.group(3), MONTHS_RO.index(m.group(2).lower()) + 1, int(m.group(1))) if m else None
    page = "https://primariaclujnapoca.ro/consiliu-local/hotarare-de-consiliu/hotararea-%d-din-%d/" % (args.nr, args.an)
    page_html, _ = page_lines(page)
    pdfs = [urllib.parse.urljoin(page, h) for h in re.findall(r'href="([^"]+\.pdf)"', page_html, re.I)
            if not SITE_WIDE_PDF.search(h)]
    if not pdfs:
        sys.exit("no PDF linked from " + page)
    recipe = {
        "id": "%d-%d" % (args.an, args.nr),
        "localitate": args.localitate,
        "hcl": {"nr": args.nr, "an": args.an, "data_sedinta": date, "pagina": page, "pdf": pdfs[0]},
        "titlu": clean_title(title),
        "plansa": {"pagina_pdf": None, "dpi": 200, "denumire": "", "scara": ""},
        "coordonate": {"crs": "EPSG:3844", "sursa": "Inventar de coordonate, Nord(x) / Est(Y)",
                       "suprafata_declarata_m2": None, "puncte": {}},
        "gcp_px": {},
        "verificare_px": {},
        "decupaj": {"buffer_m": 1.5, "exclude_px": []},
        "legenda_px": [],
        "utr": [],
    }
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(recipe, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("recipe:", out)
    print("  ", recipe["titlu"]); print("   session", date, "| pdf", pdfs[0], "| other pdfs:", len(pdfs) - 1)


# --- fetch / render ----------------------------------------------------------------

# Linked from every page of primariaclujnapoca.ro, not part of any decision.
SITE_WIDE_PDF = re.compile(r"Politica-Anti-Mita", re.I)


def decision_documents(r):
    """The recipe's PDF plus every other PDF linked from the decision's page."""
    urls = [r["hcl"]["pdf"]]
    page = r["hcl"].get("pagina")
    if page:
        try:
            html = urllib.request.urlopen(urllib.request.Request(page, headers=UA), timeout=60).read().decode("utf-8", "replace")
        except Exception as e:  # the page may be gone - that is what the backup is for
            print("decision page not reachable (%s); keeping to the recipe's PDF" % e)
            html = ""
        for href in re.findall(r'href="([^"]+\.pdf)"', html, re.I):
            u = urllib.parse.urljoin(page, href)
            if not SITE_WIDE_PDF.search(u) and doc_name(u) not in [doc_name(x) for x in urls]:
                urls.append(u)
    return urls


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def record_checksums(r, paths):
    """Keep documente/SHA256SUMS (sha256sum format) in step with the backup.
    A file that no longer matches its recorded sum is reported, not re-recorded."""
    manifest = os.path.join(os.path.dirname(docs_dir(r)), "SHA256SUMS")
    sums = {}
    if os.path.exists(manifest):
        with open(manifest, encoding="utf-8") as f:
            for line in f:
                digest, _, name = line.rstrip("\n").partition("  ")
                if name:
                    sums[name] = digest
    for p in paths:
        name = r["id"] + "/" + os.path.basename(p)
        digest = sha256(p)
        if name in sums and sums[name] != digest:
            print("WARNING: %s does not match its recorded checksum" % name)
            continue
        sums[name] = digest
    with open(manifest, "w", encoding="utf-8", newline="\n") as f:
        for name in sorted(sums):
            f.write("%s  %s\n" % (sums[name], name))


def cmd_fetch(r, args):
    paths = []
    for url in decision_documents(r):
        dst = os.path.join(docs_dir(r), doc_name(url))
        if not os.path.exists(dst):
            quoted = urllib.parse.quote(url, safe=":/()%?=&")
            with urllib.request.urlopen(urllib.request.Request(quoted, headers=UA), timeout=180) as resp:
                data = resp.read()
            with open(dst, "wb") as f:
                f.write(data)
        print("document:", dst, os.path.getsize(dst) // 1024, "KB")
        paths.append(dst)
    record_checksums(r, paths)
    dst = pdf_path(r)
    info = subprocess.run(["pdfinfo", "-f", "1", "-l", "999", dst], capture_output=True, text=True).stdout
    sizes = dict(re.findall(r"Page\s+(\d+) size:\s+(.+)", info))
    imgs = subprocess.run(["pdfimages", "-list", dst], capture_output=True, text=True).stdout.splitlines()[2:]
    per_page = {}
    for line in imgs:
        f = line.split()
        per_page.setdefault(f[0], []).append("%sx%s" % (f[3], f[4]))
    for p in sorted(sizes, key=int):
        print("  p%-3s %-32s images: %s" % (p, sizes[p], ", ".join(per_page.get(p, [])) or "-"))
    # contact sheet to spot the plate(s) and pick the clearest copy
    tmp = os.path.join(cache_dir(r), "thumb")
    subprocess.run(["pdftoppm", "-r", "14", "-png", dst, tmp], check=True)
    thumbs = sorted(f for f in os.listdir(cache_dir(r)) if f.startswith("thumb-"))
    ims = [Image.open(os.path.join(cache_dir(r), f)).convert("RGB") for f in thumbs]
    cw = max(i.width for i in ims); ch = max(i.height for i in ims) + 18
    cols = min(6, len(ims)); rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cw, rows * ch), "white")
    d = ImageDraw.Draw(sheet)
    for n, (name, im) in enumerate(zip(thumbs, ims)):
        x, y = (n % cols) * cw, (n // cols) * ch
        sheet.paste(im, (x, y + 18))
        d.text((x + 4, y + 2), "p" + str(int(re.findall(r"(\d+)\.png", name)[0])), fill=(200, 0, 120), font=font(14, True))
    out = os.path.join(cache_dir(r), "pages.png")
    sheet.save(out)
    for f in thumbs:
        os.remove(os.path.join(cache_dir(r), f))
    print("contact sheet:", out)


def cmd_render(r, args):
    p = r["plansa"]
    out = plate_path(r)
    base = out[:-4]
    subprocess.run(["pdftoppm", "-r", str(p.get("dpi", 200)), "-f", str(p["pagina_pdf"]), "-l", str(p["pagina_pdf"]),
                    "-png", "-singlefile", pdf_path(r), base], check=True)
    im = Image.open(out)
    print("plate:", out, im.size)
    sx = min(1.0, 1500 / max(im.size))
    grid_image(im, os.path.join(cache_dir(r), "plate-overview.png"), (0, 0, im.width, im.height), sx, 200)
    print("overview with pixel grid:", os.path.join(cache_dir(r), "plate-overview.png"))


# --- picking helpers -----------------------------------------------------------------

def grid_image(src, out, box, scale, step):
    """Crop `box`, scale it, draw a pixel grid labelled in full-plate coordinates.
    Saves to `out` unless it is None; returns the image."""
    x0, y0, x1, y1 = box
    im = src.convert("RGB").crop(box)
    im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    f = font(12)
    for g in range((x0 // step + 1) * step, x1, step):
        X = (g - x0) * scale
        d.line([(X, 0), (X, im.height)], fill=(0, 160, 255), width=1)
        d.text((X + 2, 2), str(g), fill=(0, 80, 200), font=f)
    for g in range((y0 // step + 1) * step, y1, step):
        Y = (g - y0) * scale
        d.line([(0, Y), (im.width, Y)], fill=(0, 160, 255), width=1)
        d.text((2, Y + 2), str(g), fill=(0, 80, 200), font=f)
    if out:
        im.save(out)
    return im


def cmd_grid(r, args):
    src = Image.open(plate_path(r))
    out = os.path.join(cache_dir(r), "grid_%d_%d.png" % (args.x0, args.y0))
    im = grid_image(src, out, (args.x0, args.y0, args.x1, args.y1), args.scale, args.step)
    print(out, im.size)


def fit_affine(r, names):
    """Least-squares affine pixel -> Stereo70 from the named control points."""
    pts = known_en(r)
    px = {**r.get("gcp_px", {}), **r.get("verificare_px", {})}
    A = np.array([[px[n][0], px[n][1], 1.0] for n in names])
    pe = np.linalg.lstsq(A, [pts[n][0] for n in names], rcond=None)[0]
    pn = np.linalg.lstsq(A, [pts[n][1] for n in names], rcond=None)[0]
    return pe, pn


def similarity_from_two(r, a, b):
    """North-up-agnostic similarity from two points, enough to predict the rest."""
    pts = known_en(r); px = r["gcp_px"]
    za = complex(*px[a]); zb = complex(*px[b])
    wa = complex(pts[a][0], -pts[a][1]); wb = complex(pts[b][0], -pts[b][1])   # flip N so both are y-down
    k = (zb - za) / (wb - wa)
    return lambda E, N: (lambda z: (z.real, z.imag))(za + k * (complex(E, -N) - wa))


def cmd_predict(r, args):
    names = list(r.get("gcp_px", {}))
    if len(names) < 2:
        sys.exit("need at least two points in gcp_px")
    if len(names) == 2:
        f = similarity_from_two(r, *names)
    else:
        pe, pn = fit_affine(r, names)
        M = np.array([[pe[0], pe[1]], [pn[0], pn[1]]]); t = np.array([pe[2], pn[2]]); Mi = np.linalg.inv(M)
        f = lambda E, N: tuple(Mi @ (np.array([E, N]) - t))
    for n, (E, N) in known_en(r).items():
        x, y = f(E, N)
        tag = "gcp" if n in r.get("gcp_px", {}) else ("chk" if n in r.get("verificare_px", {}) else "")
        print("  %-4s %7.0f %7.0f  %s" % (n, x, y, tag))


def cmd_vertices(r, args):
    """Zoomed crops around predicted positions (or picked ones), for precise picking."""
    names = list(r.get("gcp_px", {}))
    pe, pn = fit_affine(r, names) if len(names) >= 3 else (None, None)
    if pe is not None:
        M = np.array([[pe[0], pe[1]], [pn[0], pn[1]]]); t = np.array([pe[2], pn[2]]); Mi = np.linalg.inv(M)
        f = lambda E, N: tuple(Mi @ (np.array([E, N]) - t))
    else:
        f = similarity_from_two(r, *names[:2])
    src = Image.open(plate_path(r)).convert("RGB")
    rad, s, step = args.radius, args.scale, args.step
    tiles = []
    for n in args.names:
        x, y = map(int, f(*known_en(r)[n]))
        box = (x - rad, y - rad, x + rad, y + rad)
        tmp = grid_image(src, None, box, s, step)
        d = ImageDraw.Draw(tmp)
        d.rectangle([0, 0, tmp.width - 1, tmp.height - 1], outline=(0, 0, 0))
        d.text((tmp.width - 44, 4), n, fill=(255, 0, 180), font=font(16, True))
        tiles.append(tmp)
    cols = min(3, len(tiles)); rows = (len(tiles) + cols - 1) // cols
    w, h = tiles[0].size
    sheet = Image.new("RGB", (cols * w, rows * h), "white")
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * w, (i // cols) * h))
    out = os.path.join(cache_dir(r), "vertices_%s.png" % "-".join(args.names))
    sheet.save(out)
    print(out, sheet.size)


# --- build ---------------------------------------------------------------------------

def check_area(r, ring):
    """Area, and - where the table prints them - side lengths and perimeter. A side
    that disagrees points at the misread vertex: both sides touching it are off.
    A boundary traced by hand is held to a looser area tolerance than an inventory."""
    a = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        a += x1 * y2 - x2 * y1
    a = abs(a) / 2
    c = r["coordonate"]
    declared = c.get("suprafata_declarata_m2")
    tol = 0.03 if boundary_digitized(r) else AREA_TOLERANCE
    ok = declared is None or abs(a - declared) <= max(2.0, declared * tol)
    print("area of %s: %.1f m2, declared: %s (%.1f%%) -> %s" % (
        "traced boundary" if boundary_digitized(r) else "coordinates", a, declared,
        100 * (a - declared) / declared if declared else 0, "OK" if ok else "MISMATCH"))

    sides = c.get("laturi_declarate_m")   # {"10": length from 10 to the next vertex, ...}
    if sides:
        pts = points_en(r)
        order = c.get("ordine") or sorted(pts, key=lambda k: int(re.sub(r"\D", "", k) or 0))
        bad = []
        for i, n in enumerate(order):
            if n in sides:
                m = order[(i + 1) % len(order)]
                d = math.dist(pts[n], pts[m])
                if abs(d - sides[n]) > 0.01:
                    bad.append("%s->%s %.3f (table %.3f)" % (n, m, d, sides[n]))
        print("side lengths: %d checked -> %s" % (len(sides), "OK" if not bad else "MISMATCH " + "; ".join(bad)))
        ok = ok and not bad
    per = c.get("perimetru_declarat_m")
    if per:
        p = sum(math.dist(u, v) for u, v in zip(ring, ring[1:] + ring[:1]))
        p_ok = abs(p - per) <= max(0.05, per * 0.001)
        print("perimeter: %.3f m, declared %.3f -> %s" % (p, per, "OK" if p_ok else "MISMATCH"))
        ok = ok and p_ok
    return ok, a


def check_fit(r):
    names = list(r["gcp_px"])
    pe, pn = fit_affine(r, names)
    pts = known_en(r)
    sx = math.hypot(pe[0], pn[0]); rot = math.degrees(math.atan2(pn[0], pe[0]))
    print("fit: %d control points, %.1f px/m, rotation %.2f deg" % (len(names), 1 / sx, rot))
    res = {}
    for group in ("gcp_px", "verificare_px"):
        for n, (x, y) in r.get(group, {}).items():
            e = pe @ [x, y, 1] - pts[n][0]; nn = pn @ [x, y, 1] - pts[n][1]
            res[n] = math.hypot(e, nn)
            print("  %-8s %-4s residual %.2f m" % ("control" if group == "gcp_px" else "check", n, res[n]))
    ctrl = [res[n] for n in names]
    rms = math.sqrt(sum(v * v for v in ctrl) / len(ctrl))
    worst = max(res.values())
    limit = max(MAX_RESIDUAL_M, MAX_RESIDUAL_PX * sx)
    ok = worst <= limit
    print("rms %.2f m, worst %.2f m, limit %.2f m -> %s" % (rms, worst, limit, "OK" if ok else "TOO LARGE"))
    return ok, pe, pn, rms, worst


def warp(r, pe, pn, ring):
    import rasterio
    from rasterio.control import GroundControlPoint
    from rasterio.crs import CRS
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject, transform as tr
    from shapely.geometry import Polygon, box
    from shapely.ops import transform as shp_transform

    img = np.array(Image.open(plate_path(r)).convert("RGB"))
    H, W, _ = img.shape
    pts = known_en(r)
    gcps = [GroundControlPoint(row=y, col=x, x=pts[n][0], y=pts[n][1]) for n, (x, y) in r["gcp_px"].items()]
    src_crs, dst_crs = CRS.from_epsg(3844), CRS.from_epsg(3857)

    M = np.array([[pe[0], pe[1]], [pn[0], pn[1]]]); t = np.array([pe[2], pn[2]]); Mi = np.linalg.inv(M)

    def to_px(E, N):
        p = Mi @ (np.vstack([np.asarray(E), np.asarray(N)]) - t[:, None])
        return p[0], p[1]

    cut = r.get("decupaj", {})
    clip = Polygon(ring).buffer(cut.get("buffer_m", 1.5), join_style=2)
    clip_px = shp_transform(to_px, clip)
    for b in cut.get("exclude_px", []):
        clip_px = clip_px.difference(box(*b))
    mask = rasterize([(clip_px, 255)], out_shape=(H, W), fill=0, dtype="uint8")
    rgba = np.dstack([img, mask]).transpose(2, 0, 1)

    minE, minN, maxE, maxN = clip.bounds
    xs, ys = tr(src_crs, dst_crs, [minE, maxE, minE, maxE], [minN, minN, maxN, maxN])
    # No finer than the scan itself: ground metres per plate pixel, times the Web
    # Mercator stretch at this latitude.
    _, lat_c = tr(src_crs, "EPSG:4326", [(minE + maxE) / 2], [(minN + maxN) / 2])
    src_m_per_px = math.hypot(pe[0], pn[0])
    res = max(OUTPUT_RES_3857, src_m_per_px / math.cos(math.radians(lat_c[0])))
    left, top = min(xs), max(ys)
    w = int(math.ceil((max(xs) - left) / res)); h = int(math.ceil((top - min(ys)) / res))
    dt = from_origin(left, top, res, res)
    out = np.zeros((4, h, w), np.uint8)
    reproject(source=rgba, destination=out, gcps=gcps, src_crs=src_crs, dst_transform=dt, dst_crs=dst_crs,
              resampling=Resampling.lanczos, dst_nodata=0)
    right, bottom = left + w * res, top - h * res
    lons, lats = tr(dst_crs, "EPSG:4326", [left, right], [bottom, top])
    bounds = dict(west=round(lons[0], 7), south=round(lats[0], 7), east=round(lons[1], 7), north=round(lats[1], 7))
    pl, pa = tr(src_crs, "EPSG:4326", [p[0] for p in ring], [p[1] for p in ring])
    boundary = [[round(a, 7), round(b, 7)] for a, b in zip(pl, pa)]
    merc = dict(left=left, top=top, res=res)
    return Image.fromarray(out.transpose(1, 2, 0), "RGBA"), bounds, boundary, merc


def legend_image(r):
    src = Image.open(plate_path(r)).convert("RGB")
    crops = [src.crop(tuple(b)) for b in r.get("legenda_px", [])]
    if not crops:
        return None
    w = max(c.width for c in crops); h = sum(c.height for c in crops) + 12 * (len(crops) - 1)
    out = Image.new("RGB", (w, h), "white")
    y = 0
    for c in crops:
        out.paste(c, (0, y)); y += c.height + 12
    return out


def imagery_check(r, overlay, merc, boundary, zoom=18, pad=30.0):
    """Side by side: Esri World Imagery, and the overlay + coordinate boundary on top of it."""
    R = 6378137.0; ORIG = math.pi * R
    L, T = merc["left"], merc["top"]
    Rt = L + overlay.width * merc["res"]; B = T - overlay.height * merc["res"]
    L -= pad; B -= pad; Rt += pad; T += pad
    ts = 2 * ORIG / 2 ** zoom
    tx0, tx1 = int((L + ORIG) // ts), int((Rt + ORIG) // ts)
    ty0, ty1 = int((ORIG - T) // ts), int((ORIG - B) // ts)
    mos = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            u = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/%d/%d/%d" % (zoom, ty, tx)
            data = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read()
            mos.paste(Image.open(io.BytesIO(data)).convert("RGB"), ((tx - tx0) * 256, (ty - ty0) * 256))
    k = 256 / ts
    ox = (L - (tx0 * ts - ORIG)) * k; oy = ((ORIG - ty0 * ts) - T) * k
    W, H = int((Rt - L) * k), int((T - B) * k)
    base = mos.crop((int(ox), int(oy), int(ox) + W, int(oy) + H))
    scale = 3 if W < 500 else 2
    base = base.resize((W * scale, H * scale), Image.LANCZOS); k *= scale
    ov = overlay.resize((int(overlay.width * merc["res"] * k), int(overlay.height * merc["res"] * k)), Image.LANCZOS)
    a = np.array(ov); a[..., 3] = (a[..., 3] * 0.55).astype(np.uint8)
    blend = base.convert("RGBA")
    blend.alpha_composite(Image.fromarray(a), (int(pad * k), int(pad * k)))

    def m(lon, lat):
        x = R * math.radians(lon); y = R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
        return ((x - L) * k, (T - y) * k)
    ImageDraw.Draw(blend).line([m(*p) for p in boundary + boundary[:1]], fill=(0, 255, 255, 255), width=2)
    out = Image.new("RGB", (base.width * 2 + 10, base.height), "white")
    out.paste(base, (0, 0)); out.paste(blend.convert("RGB"), (base.width + 10, 0))
    path = os.path.join(cache_dir(r), "check_imagery.png")
    out.save(path)
    return path


def clean_title(t):
    t = re.sub(r"^Aprobarea\s+", "", t.strip())
    t = re.split(r";\s*beneficiar", t)[0]
    return t.rstrip(" .;")


def publish(r, overlay, legend, bounds, boundary, area, rms):
    d = os.path.join(WWW, "puz", r["id"])
    os.makedirs(d, exist_ok=True)
    overlay.save(os.path.join(d, "plansa.webp"), quality=82, method=6)
    entry = {
        "id": r["id"],
        "localitate": r.get("localitate", "cluj"),
        "hcl": "%d/%d" % (r["hcl"]["nr"], r["hcl"]["an"]),
        "data": r["hcl"].get("data_sedinta"),
        "titlu": clean_title(r["titlu"]),
        "pagina": r["hcl"].get("pagina"),
        "pdf": r["hcl"]["pdf"],
        "utr": r.get("utr", []),
        "suprafata_m2": round(area),
        "imagine": "puz/%s/plansa.webp" % r["id"],
        "bounds": bounds,
        "limita": boundary,
        "georeferentiere": {
            "metoda": ("caroiaj Stereo70, limită trasată pe planșă" if boundary_digitized(r)
                       else "inventar de coordonate Stereo70"),
            "puncte": len(r["gcp_px"]), "rms_m": round(rms, 2)},
    }
    if legend is not None:
        legend.save(os.path.join(d, "legenda.webp"), quality=85, method=6)
        entry["legenda"] = "puz/%s/legenda.webp" % r["id"]
    index = []
    if os.path.exists(INDEX):
        with open(INDEX, encoding="utf-8") as f:
            index = json.load(f)
    index = [e for e in index if e["id"] != r["id"]] + [entry]
    index.sort(key=lambda e: (e.get("data") or "", e["id"]), reverse=True)
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("published:", d, "| index entries:", len(index))


def cmd_build(r, args):
    if not os.path.exists(plate_path(r)):
        if not os.path.exists(pdf_path(r)):
            cmd_fetch(r, args)
        cmd_render(r, args)
    ok_fit, pe, pn, rms, worst = check_fit(r)
    ring = ring_en(r, pe, pn)
    ok_area, area = check_area(r, ring)
    if not (ok_area and ok_fit) and not args.force:
        sys.exit("quality gate failed - fix the recipe (or --force to build anyway)")
    overlay, bounds, boundary, merc = warp(r, pe, pn, ring)
    legend = legend_image(r)
    print("overlay %dx%d px, bounds %s" % (overlay.width, overlay.height, bounds))
    if not args.no_check:
        print("imagery check:", imagery_check(r, overlay, merc, boundary, zoom=args.zoom))
    if args.dry_run:
        overlay.save(os.path.join(cache_dir(r), "plansa.webp"), quality=82)
        if legend is not None:
            legend.save(os.path.join(cache_dir(r), "legenda.webp"), quality=85)
        print("dry run: outputs left in", cache_dir(r))
        return
    publish(r, overlay, legend, bounds, boundary, area, rms)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new", help="recipe skeleton from the decision listing")
    s.add_argument("an", type=int); s.add_argument("nr", type=int)
    s.add_argument("--folder", default="cluj-napoca"); s.add_argument("--localitate", default="cluj")
    for name in ("fetch", "render", "predict"):
        s = sub.add_parser(name); s.add_argument("recipe")
    s = sub.add_parser("grid"); s.add_argument("recipe")
    for a in ("x0", "y0", "x1", "y1"):
        s.add_argument(a, type=int)
    s.add_argument("--scale", type=float, default=1.0); s.add_argument("--step", type=int, default=50)
    s = sub.add_parser("vertices"); s.add_argument("recipe"); s.add_argument("names", nargs="+")
    s.add_argument("--radius", type=int, default=90); s.add_argument("--scale", type=float, default=2.6)
    s.add_argument("--step", type=int, default=20)
    s = sub.add_parser("build"); s.add_argument("recipe")
    s.add_argument("--force", action="store_true"); s.add_argument("--dry-run", action="store_true")
    s.add_argument("--no-check", action="store_true"); s.add_argument("--zoom", type=int, default=18)
    args = ap.parse_args()
    if args.cmd == "new":
        return cmd_new(args)
    r = load(args.recipe)
    {"fetch": cmd_fetch, "render": cmd_render, "grid": cmd_grid, "predict": cmd_predict,
     "vertices": cmd_vertices, "build": cmd_build}[args.cmd](r, args)


if __name__ == "__main__":
    main()
