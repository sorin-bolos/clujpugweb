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
    py -3.13 tools/puz/puz.py overlay  puzuri/cluj-napoca/2026-597.json x0 y0 x1 y1 [--without 84]
    py -3.13 tools/puz/puz.py hcl      puzuri/cluj-napoca/2026-597.json   # the decision text, laid out
    py -3.13 tools/puz/puz.py related  puzuri/cluj-napoca/2026-597.json   # later decisions extending/amending it
    py -3.13 tools/puz/puz.py geocode  --streets "Buftea" "Scor.arilor"   # rough position, for unlabelled grids
    py -3.13 tools/puz/puz.py caroiaj  puzuri/cluj-napoca/2026-24.json [--write]   # label unlabelled grid crosses
    py -3.13 tools/puz/puz.py osm      puzuri/cluj-napoca/2026-24.json [x0 y0 x1 y1]  # OSM drawn over the plate
    py -3.13 tools/puz/puz.py osm-snap puzuri/cluj-napoca/2026-24.json NAME x y [--write]  # OSM control point
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
# Control points from OpenStreetMap: street centrelines and building outlines are
# good to a few metres, and the result is published as approximate.
MAX_RESIDUAL_OSM_M = 5.0
OUTPUT_RES_3857 = 0.07         # metres (EPSG:3857 units) per output pixel, ~z21
LEGEND_MAX_W = 1000            # px
LEGEND_MEDIAN_MIN_DPI = 250    # despeckle legends only from this scan resolution up

Image.MAX_IMAGE_PIXELS = None


# --- recipe and paths ------------------------------------------------------------

def load(recipe_path):
    with open(recipe_path, encoding="utf-8") as f:
        r = json.load(f)
    r["_path"] = recipe_path
    return r


def dump_recipe(r, path):
    """JSON with two-space indent, but number lists - coordinate pairs, pixel boxes -
    kept on one line, so a recipe stays readable and diffs stay small."""
    r = {k: v for k, v in r.items() if not k.startswith("_")}
    s = json.dumps(r, ensure_ascii=False, indent=2)
    s = re.sub(r"\[\s+([-\d.,\s]+?)\s+\]", lambda m: "[" + ", ".join(x.strip() for x in m.group(1).split(",")) + "]", s)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(s + "\n")


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


def plate_pdf_url(r):
    """The PDF the plate comes from: the decision's own, unless an amending decision
    replaced the plate (`plansa.pdf`, with `plansa.sursa_hcl`)."""
    return (r.get("plansa") or {}).get("pdf") or r["hcl"]["pdf"]


def pdf_path(r):
    return os.path.join(docs_dir(r), doc_name(plate_pdf_url(r)))


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
    recipe["_path"] = out
    years = parse_validity_years(read_decision_text(recipe))
    if years and date:
        recipe["valabilitate"] = {"ani": years, "pana_la": add_years(date, years)}
    recipe.update({"prelungiri": [], "modifica": [], "modificat_de": [], "diferente_fata_de_plansa": [], "conditii": []})
    dump_recipe(recipe, out)
    print("recipe:", out)
    print("  ", recipe["titlu"]); print("   session", date, "| pdf", pdfs[0], "| other pdfs:", len(pdfs) - 1)
    print("   valid:", recipe.get("valabilitate", "not found in the decision text - set it by hand"))


# --- the decision's text -------------------------------------------------------------
# The council can amend a PUZ in session. Amendments change the decision's articles,
# not the annexed plates: HCL 604/2023 got an Art. 2 allowing houses only on parcels of
# at least 800 m2 while its plate still draws lots of 326 m2. So the text is read next
# to the plate, and kept in the backup with the PDFs.

NUMBERS_RO = {"un": 1, "unu": 1, "doi": 2, "doua": 2, "două": 2, "trei": 3, "patru": 4, "cinci": 5,
              "sase": 6, "șase": 6, "şase": 6, "sapte": 7, "șapte": 7, "şapte": 7, "opt": 8,
              "noua": 9, "nouă": 9, "zece": 10}


def decision_text_from_page(url):
    raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode("utf-8", "replace")
    m = re.search(r"<main.*?</main>", raw, re.S)
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", m.group(0) if m else raw, flags=re.S)
    txt = re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
    txt = re.sub(r"^.*?Vezi document oficial\s*", "", txt)
    return re.sub(r"\s*\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d\s*$", "", txt)


def text_path(r):
    return os.path.join(docs_dir(r), "hotarare.txt")


NO_PAGE_TEXT = "[Pagina hotărârii nu are text."
NO_PAGE_TEXT_NOTE = (NO_PAGE_TEXT + " Transcrie aici, din PDF-ul scanat, preambulul pe scurt și articolele"
                     " integral, apoi înlocuiește acest paragraf cu: Transcris din PDF, paginile N-M.]")


def save_decision_text(r):
    """The decision as published on its page, wrapped for reading. Kept once: like the
    PDFs, it is a backup of what was published, not refreshed. Some pages carry no
    text (HCL 24/2021); the file then says so, and the decision has to be transcribed
    from the scanned PDF into it."""
    p = text_path(r)
    if not os.path.exists(p):
        import textwrap
        txt = decision_text_from_page(r["hcl"]["pagina"])
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write("Sursa: %s\n\n" % r["hcl"]["pagina"])
            if len(txt) < 400:
                f.write("\n".join(textwrap.wrap(NO_PAGE_TEXT_NOTE, 110)) + "\n")
            else:
                f.write("\n".join(textwrap.wrap(txt, 110, break_long_words=False, break_on_hyphens=False)) + "\n")
    return p


def read_decision_text(r):
    try:
        p = save_decision_text(r)
    except Exception as e:
        print("decision text not available (%s)" % e)
        return ""
    with open(p, encoding="utf-8") as f:
        lines = f.read().split("\n")
    text = " ".join(l for l in lines[2:] if l)
    if text.startswith(NO_PAGE_TEXT):
        print("WARNING: the decision's page has no text. Read the decision in the scanned PDF and transcribe it"
              " into %s (see the note inside)." % p)
        return ""
    return text


def parse_validity_years(text):
    m = re.search(r"valabilitate a documenta\w+ de (\w+) ani", text, re.I)
    if not m:
        return None
    w = m.group(1).lower()
    return int(w) if w.isdigit() else NUMBERS_RO.get(w)


def add_years(iso, years):
    y, mo, d = map(int, iso.split("-"))
    if mo == 2 and d == 29:
        d = 28
    return "%04d-%02d-%02d" % (y + years, mo, d)


def cmd_hcl(r, args):
    """What the decision's text says, laid out for writing the recipe: validity, each
    UTR's paragraph with its indicators, and the sentences that set conditions. Read it
    against the plate: anything the text adds, restricts or changes goes in the recipe."""
    text = read_decision_text(r)
    if not text:
        sys.exit("no decision text")
    print("text:", text_path(r), "(%d characters)" % len(text))
    years = parse_validity_years(text)
    date = r["hcl"].get("data_sedinta")
    print("\nVALABILITATE: %s ani -> până la %s" % (years, add_years(date, years) if years and date else "?"))
    art = r"(?=\bA\s?rt\s?\.\s?%s\s?[.–-])"
    m1 = re.search(art % "1", text)
    body = text[m1.start():] if m1 else text
    print("\nUTR:")
    blocks = re.split(r"(?=U\.\s?T\.\s?R\.\s)", body)
    for b in blocks[1:]:
        b = re.split(art % r"\d+", b)[0]
        head = re.match(r"U\.\s?T\.\s?R\.\s*(.{1,40}?)\s*[–-]\s*(.{0,140})", b)
        ind = re.findall(r"(P\.\s?O\.\s?T\.?[^;]{0,60}|C\.\s?U\.\s?T\.?[^;,]{0,30}|[îi]n[ăa]l[țţ]imea maxim[ăa][^;]{0,160}"
                         r"|H\s?max[^;]{0,40}|suprafa[țţ]a (?:minim|parcelei)[^;]{0,80})", b, re.I)
        print("  - %s | %s" % (head.group(1) if head else "?", (head.group(2) if head else b[:140]).strip()))
        for i in ind:
            print("      " + re.sub(r"\s+", " ", i).strip())
    print("\nCONDIȚII (fraze care condiționează, obligă sau restrâng):")
    keys = re.compile(r"anterior|condi[țţ]ion|prin grija|pe cheltuiala|obliga|interzis|doar |numai |nu mai târziu|"
                      r"ulterior|se rectific|modific|derog|excep[țţ]", re.I)
    for s in re.split(r"(?<=[.;])\s+(?=[A-ZĂÂÎȘŞȚŢ])", body):
        if keys.search(s) and not s.startswith("U.T.R"):
            print("  - " + s.strip()[:400])
    print("\nARTICOLE:")
    for a in re.split(art % r"\d+", body)[1:]:
        print("  - " + a.strip()[:300])
    print("\nUn articol scurt pus după lista anexelor, sau unul care contrazice planșa, e de obicei un amendament"
          "\nvotat în ședință: procesul-verbal al ședinței spune cine l-a propus și de ce.")


def cmd_related(r, args):
    """Decisions in the index whose title points at this PUZ - extensions of validity,
    amendments, corrections - and the decision this one amends, if its title says so."""
    nr, an = r["hcl"]["nr"], r["hcl"]["an"]
    path = os.path.join(os.path.dirname(os.path.abspath(r["_path"])), "hotarari-puz.json")
    with open(path, encoding="utf-8") as f:
        index = json.load(f)
    ref = re.compile(r"Hot[ăa]r[âa]r(?:ea|ii)\s+nr\.?\s*%d\s*(?:/\s*%d|din\s+[\d.\s]+\.?\s*%d)" % (nr, an, an), re.I)
    hits = [h for h in index["hotarari"] if ref.search(h["titlu"]) and (h["an"], h["nr"]) != (an, nr)]
    print("index:", path, "- updated", index.get("actualizat"), "- %d decisions" % len(index["hotarari"]))
    print("\nLater decisions referring to HCL %d/%d:" % (nr, an))
    for h in hits:
        kind = ("PRELUNGIRE" if re.search(r"Prelungirea valabilit", h["titlu"], re.I) else
                "MODIFICARE" if re.search(r"Modific", h["titlu"], re.I) else
                "RECTIFICARE" if re.search(r"rectific|[îi]ndrept|eroare", h["titlu"], re.I) else "ALTA")
        print("  %-11s HCL %d/%d  %s" % (kind, h["nr"], h["an"], h["titlu"][:200]))
    if not hits:
        print("  none")
    own = re.findall(r"Hot[ăa]r[âa]r(?:ea|ii)\s+nr\.?\s*(\d+)\s*(?:/\s*(\d{4})|din\s+[\d.]+?(\d{4}))", r.get("titlu", ""), re.I)
    if own:
        print("\nThis PUZ's own title refers to:", ", ".join("HCL %s/%s" % (n, a or b) for n, a, b in own),
              "- if it amends that PUZ, list it under `modifica`.")
    print("\nThe index only knows titles up to its update date; for newer decisions check the council listing.")


# --- unlabelled grids --------------------------------------------------------------
# Some plates show Stereo 70 grid crosses with their labels cut off (HCL 24/2026).
# The crosses still sit on exact multiples of the grid step, so knowing roughly where
# the plate is - within half a step - pins every label. `geocode` gives that rough
# position from OpenStreetMap (two streets that meet on the plate); `caroiaj` turns
# picked crosses plus that anchor into labelled control points. The imagery check then
# has the last word: a label off by one step shows as the whole plate shifted 50 m.

OVERPASS = "https://overpass-api.de/api/interpreter"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
CLUJ_BBOX = (46.70, 23.45, 46.86, 23.75)   # S, W, N, E


def to_stereo70(lon, lat):
    from pyproj import Transformer
    return Transformer.from_crs(4326, 3844, always_xy=True).transform(lon, lat)


def street_lines(pattern):
    """All OSM ways in Cluj-Napoca whose name matches the regex (case-insensitive),
    as Stereo 70 lines. A regex copes with diacritics: "Scor.arilor"."""
    from shapely.geometry import LineString, MultiLineString
    q = '[out:json][timeout:60];way["highway"]["name"~"%s",i](%f,%f,%f,%f);out tags geom;' % ((pattern,) + CLUJ_BBOX)
    data = overpass(q)
    lines, names = [], set()
    for el in data.get("elements", []):
        pts = [to_stereo70(p["lon"], p["lat"]) for p in el.get("geometry", [])]
        if len(pts) >= 2:
            lines.append(LineString(pts))
            names.add(el.get("tags", {}).get("name", "?"))
    return MultiLineString(lines) if lines else None, sorted(names)


def cmd_geocode(args):
    from shapely.ops import nearest_points
    from pyproj import Transformer
    back = Transformer.from_crs(3844, 4326, always_xy=True)
    if args.streets:
        a, na = street_lines(args.streets[0])
        b, nb = street_lines(args.streets[1])
        if a is None or b is None:
            sys.exit("street not found in OSM: %s" % (args.streets[0] if a is None else args.streets[1]))
        print("OSM names:", na, "/", nb)
        inter = a.intersection(b)
        if not inter.is_empty:
            pts = [inter] if inter.geom_type == "Point" else list(getattr(inter, "geoms", [inter.centroid]))
            for p in pts:
                lon, lat = back.transform(p.x, p.y)
                print("intersection: E %.1f  N %.1f   (lat %.6f, lon %.6f)" % (p.x, p.y, lat, lon))
        else:
            p, q = nearest_points(a, b)
            m = ((p.x + q.x) / 2, (p.y + q.y) / 2)
            lon, lat = back.transform(*m)
            print("streets do not cross; closest approach %.1f m apart, midpoint E %.1f  N %.1f   (lat %.6f, lon %.6f)"
                  % (p.distance(q), m[0], m[1], lat, lon))
        print("OSM street centrelines are good to a few metres; pick the same point (centreline crossing) on the plate.")
    else:
        url = NOMINATIM + "?" + urllib.parse.urlencode({"q": args.address, "format": "json", "countrycodes": "ro", "limit": 3})
        for res in json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()):
            E, N = to_stereo70(float(res["lon"]), float(res["lat"]))
            print("%-12s E %.1f  N %.1f   %s" % (res.get("type"), E, N, res.get("display_name", "")[:120]))
        print("An address point may be the building or the street's middle; prefer --streets when two streets meet on the plate.")


def cmd_caroiaj(r, args):
    """Label the picked crosses of an unlabelled grid. Needs in the recipe:
    caroiaj = {pas_m, nord (direction of north on the plate, degrees clockwise from up),
               ancora: {px: [x, y], en: [E, N]}, cruci_px: {name: [x, y], ...}}."""
    c = r.get("caroiaj") or sys.exit("no `caroiaj` in the recipe")
    step = float(c["pas_m"]); crosses = c["cruci_px"]
    if len(crosses) < 2:
        sys.exit("pick at least two crosses (four or more, spread out, is better)")
    P = {k: np.array(v, float) for k, v in crosses.items()}
    names = list(P)
    # The grid lines run exactly north-south and east-west, so two crosses on the same
    # grid line give the plate's rotation. With the north arrow as a hint (+-8 deg),
    # those pairs are the ones whose direction is a multiple of 90 deg from it.
    ang = lambda v: math.atan2(v[0], -v[1])          # clockwise from "up"
    hint = math.radians(float(c.get("nord", 0)))
    axis_pairs = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            v = P[b] - P[a]; d = float(np.hypot(*v))
            dev = (math.degrees(ang(v) - hint) + 45) % 90 - 45
            if d > 5 and abs(dev) <= 8:
                axis_pairs.append((d, dev))
    if not axis_pairs:
        sys.exit("no two crosses on the same grid line - pick crosses that share a row or a column")
    devs = sorted(x for _, x in axis_pairs)
    north = hint + math.radians(devs[len(devs) // 2])
    uN = np.array([math.sin(north), -math.cos(north)]); uE = np.array([math.sin(north + math.pi / 2), -math.cos(north + math.pi / 2)])
    # Scale: whole steps between crosses on a line. `px_per_m`, measured on the plate
    # (a dimension line, or the printed scale and the dpi), settles how many steps;
    # without it the closest such pair is taken as one step.
    unit = step * float(c["px_per_m"]) if c.get("px_per_m") else min(d for d, _ in axis_pairs)
    ks = [max(1, round(d / unit)) for d, _ in axis_pairs]
    s = sum(d / k for (d, _), k in zip(axis_pairs, ks)) / len(ks) / step   # px per metre
    print("grid: %d cross pairs on grid lines; north at %.2f deg clockwise from up; %.2f px/m (one %g m step = %.0f px)"
          % (len(axis_pairs), math.degrees(north), s, step, step * s))
    if not c.get("px_per_m"):
        print("      no px_per_m given: check it against a dimension line on the plate before trusting the labels")
    elif abs(s / float(c["px_per_m"]) - 1) > 0.05:
        print("WARNING: crosses imply %.2f px/m, the plate %.2f - wrong step or a wrong cross?" % (s, float(c["px_per_m"])))
    ax, ay = c["ancora"]["px"]; aE, aN = c["ancora"]["en"]
    labels, worst = {}, 0.0
    for k, p in P.items():
        v = p - np.array([ax, ay], float)
        E = aE + (v @ uE) / s; N = aN + (v @ uN) / s
        gE, gN = round(E / step) * step, round(N / step) * step
        off = math.hypot(E - gE, N - gN)
        worst = max(worst, off)
        labels[k] = (gE, gN)
        print("  %-6s px %-12s -> E %.0f N %.0f  (predicted %.1f, %.1f; %.1f m from the node)" % (k, list(p.astype(int)), gE, gN, E, N, off))
    # Each cross lands off its node by the anchor's error (modulo a step). With an
    # anchor good to well under half a step, a small offset means the labels are right.
    print("crosses land up to %.1f m from grid nodes - that is the anchor's error, provided the anchor is good to"
          " under %g m (half a step)" % (worst, step / 2))
    if worst > step / 4:
        print("WARNING: more than a quarter step - the labels may be one step off; get a better anchor"
              " (street centrelines crossing, picked carefully on the plate)")
    else:
        print("labels safe; confirm with the imagery check (a one-step error shows as the plate shifted %g m)" % step)
    if args.write:
        r.setdefault("repere", {}); r.setdefault("gcp_px", {})
        for k, (gE, gN) in labels.items():
            name = "C%d_%d" % (gE, gN)
            r["repere"][name] = [gN, gE]
            r["gcp_px"][name] = [int(P[k][0]), int(P[k][1])]
        dump_recipe(r, r["_path"])
        print("written to repere and gcp_px")


# --- OpenStreetMap control points ---------------------------------------------------
# When a plate has no usable coordinates - an illegible table (754/2021), crosses that
# belong to the sheet rather than the drawing (24/2026) - its streets and buildings are
# still drawn to scale. OSM has the same streets and buildings, good to a few metres.
# `osm` draws OSM over the plate from a rough anchor or the current fit; `osm-snap`
# turns a corner picked on the plate into a control point at the nearest OSM building
# corner or street crossing. The fit is a similarity and the result is published as
# approximate (MAX_RESIDUAL_OSM_M).

def plate_transform(r):
    """(pe, pn) for pixel -> Stereo70: from the control points once there are enough
    (2 for the OSM similarity, 3 otherwise), else from `osm_ancora` = {px, en,
    px_per_m, nord}."""
    names = list(r.get("gcp_px", {}))
    if len(names) >= (2 if osm_method(r) else 3):
        return fit_affine(r, names)
    a = r.get("osm_ancora") or sys.exit("need `osm_ancora` {px, en, px_per_m, nord} or two control points")
    t = math.radians(float(a.get("nord", 0))); s = float(a["px_per_m"])
    uN = (math.sin(t), -math.cos(t)); uE = (math.sin(t + math.pi / 2), -math.cos(t + math.pi / 2))
    (ax, ay), (aE, aN) = a["px"], a["en"]
    pe = np.array([uE[0] / s, uE[1] / s, aE - (ax * uE[0] + ay * uE[1]) / s])
    pn = np.array([uN[0] / s, uN[1] / s, aN - (ax * uN[0] + ay * uN[1]) / s])
    return pe, pn


def ground_to_px(pe, pn):
    M = np.array([[pe[0], pe[1]], [pn[0], pn[1]]]); t = np.array([pe[2], pn[2]]); Mi = np.linalg.inv(M)
    return lambda E, N: tuple(Mi @ (np.array([E, N]) - t))


def overpass(query, tries=4):
    import time
    for k in range(tries):
        try:
            req = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({"data": query}).encode(), headers=UA)
            return json.loads(urllib.request.urlopen(req, timeout=120).read().decode("utf-8"))
        except Exception as e:
            print("Overpass: %s%s" % (e, " - retrying" if k < tries - 1 else ""))
            time.sleep(10 * (k + 1))
    sys.exit("Overpass unavailable - try again later")


def osm_features(r, center, radius):
    """Buildings and streets around a Stereo 70 point, cached in puz_cache/<id>/osm.json."""
    from pyproj import Transformer
    path = os.path.join(cache_dir(r), "osm.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cached = json.load(f)
        if math.dist(cached["center"], center) + radius <= cached["radius"] + 1:
            return cached
    lon, lat = Transformer.from_crs(3844, 4326, always_xy=True).transform(*center)
    q = ('[out:json][timeout:90];(way["building"](around:{r},{la},{lo});way["highway"](around:{r},{la},{lo}););'
         'out tags geom;').format(r=int(radius), la=lat, lo=lon)
    data = overpass(q)
    feats = {"center": list(center), "radius": radius, "buildings": [], "streets": []}
    for el in data.get("elements", []):
        pts = [list(to_stereo70(p["lon"], p["lat"])) for p in el.get("geometry", [])]
        tags = el.get("tags", {})
        if "building" in tags and len(pts) >= 3:
            feats["buildings"].append({"id": el["id"], "pts": pts})
        elif "highway" in tags and len(pts) >= 2:
            feats["streets"].append({"id": el["id"], "name": tags.get("name", ""), "kind": tags["highway"], "pts": pts})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(feats, f)
    print("OSM: %d buildings, %d street segments within %d m" % (len(feats["buildings"]), len(feats["streets"]), radius))
    return feats


def osm_candidates(feats):
    """Points a control point can snap to: building corners and street crossings."""
    from shapely.geometry import LineString
    cands = []
    for b in feats["buildings"]:
        for k, p in enumerate(b["pts"][:-1] if b["pts"][0] == b["pts"][-1] else b["pts"]):
            cands.append(("b%d_%d" % (b["id"], k), p, "colț de clădire"))
    named = [s for s in feats["streets"] if s["kind"] not in ("footway", "path", "steps", "cycleway", "service")]
    lines = [(s, LineString(s["pts"])) for s in named]
    for i, (s1, l1) in enumerate(lines):
        for s2, l2 in lines[i + 1:]:
            if s1["name"] and s1["name"] == s2["name"]:
                continue        # consecutive segments of one street
            inter = l1.intersection(l2)
            for g in ([inter] if inter.geom_type == "Point" else getattr(inter, "geoms", [])):
                if g.geom_type == "Point":
                    cands.append(("x%d_%d" % (s1["id"], s2["id"]), [g.x, g.y],
                                  "intersecție %s / %s" % (s1["name"] or s1["kind"], s2["name"] or s2["kind"])))
    # One physical point may come out several times: three streets meeting in a node,
    # or a corner shared by two buildings. Keep one, listing what meets there.
    merged = {}
    for k, p, kind in cands:
        key = (round(p[0] * 2) / 2, round(p[1] * 2) / 2)
        if key in merged:
            mk, mp, mkind = merged[key]
            if kind.startswith("intersecție") and mkind.startswith("intersecție"):
                names = sorted(set(mkind[len("intersecție "):].split(" / ") + kind[len("intersecție "):].split(" / ")))
                merged[key] = (mk, mp, "intersecție " + " / ".join(names))
        else:
            merged[key] = (k, p, kind)
    return list(merged.values())


def plate_radius(r, pe, pn):
    W, H = Image.open(plate_path(r)).size
    corners = [(pe @ [x, y, 1], pn @ [x, y, 1]) for x, y in ((0, 0), (W, 0), (0, H), (W, H))]
    c = (pe @ [W / 2, H / 2, 1], pn @ [W / 2, H / 2, 1])
    return c, min(800.0, max(math.dist(c, k) for k in corners) + 30)


def cmd_osm(r, args):
    pe, pn = plate_transform(r)
    center, radius = plate_radius(r, pe, pn)
    feats = osm_features(r, center, radius)
    to_px = ground_to_px(pe, pn)
    src = Image.open(plate_path(r))
    box = (args.x0, args.y0, args.x1, args.y1) if args.x1 else (0, 0, src.width, src.height)
    s = args.scale or min(1.0, 1500 / max(box[2] - box[0], box[3] - box[1]))
    im = grid_image(src, None, box, s, args.step).convert("RGB")
    d = ImageDraw.Draw(im)
    P = lambda p: ((to_px(*p)[0] - box[0]) * s, (to_px(*p)[1] - box[1]) * s)
    for st in feats["streets"]:
        d.line([P(p) for p in st["pts"]], fill=(0, 170, 0), width=2)
    for b in feats["buildings"]:
        d.line([P(p) for p in b["pts"]], fill=(220, 0, 0), width=2)
    for k, p, kind in osm_candidates(feats):
        if k.startswith("x"):
            X, Y = P(p); d.ellipse([X - 4, Y - 4, X + 4, Y + 4], outline=(200, 0, 200), width=2)
    for k, (x, y) in {**r.get("gcp_px", {}), **r.get("verificare_px", {})}.items():
        X, Y = (x - box[0]) * s, (y - box[1]) * s
        d.line([(X - 7, Y), (X + 7, Y)], fill=(0, 0, 255), width=2); d.line([(X, Y - 7), (X, Y + 7)], fill=(0, 0, 255), width=2)
    out = os.path.join(cache_dir(r), "osm_%d_%d.png" % box[:2])
    im.save(out)
    print(out, im.size, "- OSM streets green, buildings red, street crossings magenta, control points blue")


def cmd_osm_snap(r, args):
    pe, pn = plate_transform(r)
    E, N = pe @ [args.x, args.y, 1], pn @ [args.x, args.y, 1]
    center, radius = plate_radius(r, pe, pn)
    cands = [(math.dist(p, (E, N)), k, p, kind) for k, p, kind in osm_candidates(osm_features(r, center, radius))]
    cands = sorted(c for c in cands if c[0] <= args.max and (args.kind == "any" or c[3].startswith(
        "colț" if args.kind == "building" else "intersecție")))
    print("pixel (%d, %d) -> E %.1f N %.1f with the current fit" % (args.x, args.y, E, N))
    for i, (dist, k, p, kind) in enumerate(cands[:6]):
        print("  [%d] %5.1f m  %-24s %s" % (i, dist, k, kind))
    if not cands:
        sys.exit("nothing within %g m - pick a clearer corner, or improve the fit first" % args.max)
    if len(cands) > 1 and cands[1][0] - cands[0][0] < 1.5 and args.pick is None:
        print("WARNING: two candidates within 1.5 m of each other - pass --pick N after looking at the overlay")
        if args.write:
            sys.exit("not written")
    if args.write:
        dist, k, p, kind = cands[args.pick or 0]
        r.setdefault("repere", {})[args.name] = [round(p[1], 2), round(p[0], 2)]
        r.setdefault("verificare_px" if args.check else "gcp_px", {})[args.name] = [args.x, args.y]
        r.setdefault("repere_osm", {})[args.name] = "%s (%s)" % (kind, k)
        dump_recipe(r, r["_path"])
        print("written: %s = %s, %s" % (args.name, kind, "check point" if args.check else "control point"))


# --- fetch / render ----------------------------------------------------------------

# Linked from every page of primariaclujnapoca.ro, not part of any decision.
SITE_WIDE_PDF = re.compile(r"Politica-Anti-Mita", re.I)


def decision_documents(r):
    """The recipe's PDF plus every other PDF linked from the decision's page, and the
    PDF of an amending decision whose plate replaced the original."""
    urls = [r["hcl"]["pdf"]]
    if plate_pdf_url(r) not in urls:
        urls.append(plate_pdf_url(r))
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
    A downloaded file that no longer matches its recorded sum is reported, not
    re-recorded. hotarare.txt is the exception: it may be a transcription, completed
    after the first fetch."""
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
        if name in sums and sums[name] != digest and not name.endswith("/hotarare.txt"):
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
    try:
        paths.append(save_decision_text(r))
        print("decision text:", text_path(r))
    except Exception as e:
        print("decision text not saved (%s)" % e)
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


def osm_method(r):
    """Control points taken from OpenStreetMap features (street crossings, building
    corners) instead of coordinates printed on the plate."""
    return r.get("georef_metoda") == "osm"


def fit_affine(r, names):
    """Least-squares pixel -> Stereo70 from the named control points: affine, or for
    OSM control points a similarity (scale, rotation, shift). A plate's scale is the
    same in every direction, and with points good only to a few metres an affine
    fit would turn their noise into shear."""
    pts = known_en(r)
    px = {**r.get("gcp_px", {}), **r.get("verificare_px", {})}
    if osm_method(r):
        # E = p*x + q*y + c,  N = q*x - p*y + d  (image y runs down)
        A, b = [], []
        for n in names:
            x, y = px[n]
            A.append([x, y, 1, 0]); b.append(pts[n][0])
            A.append([-y, x, 0, 1]); b.append(pts[n][1])
        p, q, c, d = np.linalg.lstsq(np.array(A, float), np.array(b, float), rcond=None)[0]
        return np.array([p, q, c]), np.array([q, -p, d])
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


def cmd_overlay(r, args):
    """Draw the boundary the current fit predicts over a crop of the plate. Where it
    leaves the drawn boundary line, a control point is off - or the line is not the
    one the coordinates describe."""
    names = [n for n in r["gcp_px"] if n not in args.without]
    if len(names) < 3:
        sys.exit("need at least three control points")
    pe, pn = fit_affine(r, names)
    M = np.array([[pe[0], pe[1]], [pn[0], pn[1]]]); t = np.array([pe[2], pn[2]]); Mi = np.linalg.inv(M)
    to_px = lambda E, N: tuple(Mi @ (np.array([E, N]) - t))
    box = (args.x0, args.y0, args.x1, args.y1); s = args.scale
    im = grid_image(Image.open(plate_path(r)), None, box, s, args.step)
    d = ImageDraw.Draw(im); f = font(12)
    pts = points_en(r)
    order = r["coordonate"].get("ordine") or sorted(pts, key=lambda k: int(re.sub(r"\D", "", k) or 0))
    ring = [pts[k] for k in order] if pts else ring_en(r, pe, pn)
    labels = order if pts else [""] * len(ring)
    P = [((to_px(*p)[0] - args.x0) * s, (to_px(*p)[1] - args.y0) * s) for p in ring]
    d.line(P + P[:1], fill=(0, 170, 0), width=1)
    for k, (X, Y) in zip(labels, P):
        if -20 < X < im.width + 20 and -20 < Y < im.height + 20:
            d.ellipse([X - 2, Y - 2, X + 2, Y + 2], outline=(0, 120, 0))
            d.text((X + 3, Y - 13), k, fill=(0, 110, 0), font=f)
    for k, (x, y) in r["gcp_px"].items():   # picked control points as blue crosses
        X, Y = (x - args.x0) * s, (y - args.y0) * s
        d.line([(X - 6, Y), (X + 6, Y)], fill=(0, 0, 255)); d.line([(X, Y - 6), (X, Y + 6)], fill=(0, 0, 255))
    out = os.path.join(cache_dir(r), "overlay_%d_%d.png" % (args.x0, args.y0))
    im.save(out)
    print(out, im.size)


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
    limit = max(MAX_RESIDUAL_OSM_M if osm_method(r) else MAX_RESIDUAL_M, MAX_RESIDUAL_PX * sx)
    ok = worst <= limit
    print("rms %.2f m, worst %.2f m, limit %.2f m -> %s" % (rms, worst, limit, "OK" if ok else "TOO LARGE"))
    if not ok and len(names) >= 4:
        # A single misplaced point drags the whole fit; refitting without each one in
        # turn shows which: leaving it out drops everyone else's error.
        print("  leave-one-out (refit without the point -> rms of the others, its own residual):")
        for out in names:
            rest = [n for n in names if n != out]
            qe, qn = fit_affine(r, rest)
            err = {n: math.hypot(qe @ [*r["gcp_px"][n], 1] - pts[n][0], qn @ [*r["gcp_px"][n], 1] - pts[n][1])
                   for n in names}
            print("    without %-14s rms %.2f m, its residual %.2f m" % (
                out, math.sqrt(sum(err[n] ** 2 for n in rest) / len(rest)), err[out]))
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
    # GDAL gets the fitted model itself, as the plate's four corners: it then warps
    # with exactly the transform the checks judged, affine or similarity alike.
    gcps = [GroundControlPoint(row=y, col=x, x=float(pe @ [x, y, 1]), y=float(pn @ [x, y, 1]))
            for x, y in ((0, 0), (W, 0), (0, H), (W, H))]
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
    """Legend boxes [x0, y0, x1, y1], stacked. A fifth number turns a box clockwise by
    that many degrees, for plates printed sideways (24/2026: text reading upwards
    needs 90)."""
    src = Image.open(plate_path(r)).convert("RGB")
    crops = []
    for b in r.get("legenda_px", []):
        c = src.crop(tuple(b[:4]))
        if len(b) > 4 and b[4]:
            c = c.rotate(-float(b[4]), expand=True, fillcolor="white")
        crops.append(c)
    if not crops:
        return None
    w = max(c.width for c in crops); h = sum(c.height for c in crops) + 12 * (len(crops) - 1)
    out = Image.new("RGB", (w, h), "white")
    y = 0
    for c in crops:
        out.paste(c, (0, y)); y += c.height + 12
    # Scan grain compresses badly. A 3x3 median removes it, but it also removes any
    # stroke thinner than 2 px: on a 96 ppi scan that is all the small print (594/2026
    # came out unreadable). So only on fine scans, and before downscaling, while the
    # strokes are still several pixels wide.
    from PIL import ImageFilter
    if (r.get("plansa") or {}).get("dpi", 0) >= LEGEND_MEDIAN_MIN_DPI:
        out = out.filter(ImageFilter.MedianFilter(3))
    # The legend card shows it at most ~600 px wide; 300 ppi scans gave 1 MB legends
    # (627/2026). 1000 px keeps small print legible when zoomed.
    if out.width > LEGEND_MAX_W:
        out = out.resize((LEGEND_MAX_W, round(out.height * LEGEND_MAX_W / out.width)), Image.LANCZOS)
    return paper_to_white(out)


def paper_to_white(im):
    """Stretch levels so that the paper (the brightest quarter of a legend, which is
    mostly paper) becomes white. Faint grey print gets darker with it instead of being
    cut away, as a fixed threshold did."""
    a = np.asarray(im).astype(np.float32)
    paper = max(float(np.percentile(a.mean(axis=2), 75)), 160.0)
    a = np.clip(a * (255.0 / paper), 0, 255)
    a[a > 246] = 255
    return Image.fromarray(a.astype(np.uint8))


def legend_target(r):
    return os.path.join(WWW, "puz", r["id"], "legenda.webp")


def cmd_legend(r, args):
    """Rebuild only the legend of a PUZ, after changing `legenda_px`. Published PUZ:
    rewrites its legenda.webp and its puz.json entry; otherwise (or with --dry-run)
    writes to the cache for a look."""
    legend = legend_image(r)
    index = []
    if os.path.exists(INDEX):
        with open(INDEX, encoding="utf-8") as f:
            index = json.load(f)
    entry = next((e for e in index if e["id"] == r["id"]), None)
    if args.dry_run or entry is None:
        if legend is None:
            print("no legend boxes in the recipe")
            return
        path = os.path.join(cache_dir(r), "legenda.webp")
        legend.save(path, quality=80, method=6)
        print("%s (%dx%d) - %s" % (path, legend.width, legend.height,
                                    "dry run" if entry else "not published, nothing else changed"))
        return
    target = legend_target(r)
    if legend is None:
        if os.path.exists(target):
            os.remove(target)
        entry.pop("legenda", None)
        print("legend removed:", r["id"])
    else:
        legend.save(target, quality=80, method=6)
        entry["legenda"] = "puz/%s/legenda.webp" % r["id"]
        print("%s (%dx%d, %d kB)" % (target, legend.width, legend.height, os.path.getsize(target) // 1024))
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
        f.write("\n")


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
            "metoda": ("repere OpenStreetMap, limită trasată pe planșă" if osm_method(r)
                       else "caroiaj Stereo70, limită trasată pe planșă" if boundary_digitized(r)
                       else "inventar de coordonate Stereo70"),
            "puncte": len(r["gcp_px"]), "rms_m": round(rms, 2)},
    }
    if osm_method(r):
        # OSM's own error comes on top of the fit's: never claim better than 3 m.
        entry["georeferentiere"].update({"aproximativ": True, "precizie_m": int(round(max(3.0, 2 * rms)))})
    if legend is not None:
        legend.save(os.path.join(d, "legenda.webp"), quality=80, method=6)
        entry["legenda"] = "puz/%s/legenda.webp" % r["id"]
    # What the decision's text adds to the plate. Validity runs to the last extension.
    v = r.get("valabilitate") or {}
    ext = r.get("prelungiri", [])
    ends = [x for x in [v.get("pana_la")] + [p.get("pana_la") for p in ext] if x]
    if ends:
        entry["valabilitate"] = {"ani": v.get("ani"), "pana_la": max(ends)}
        if ext:
            entry["valabilitate"].update({"initial_pana_la": v.get("pana_la"), "prelungiri": ext})
    for key in ("diferente_fata_de_plansa", "conditii", "modifica", "modificat_de"):
        if r.get(key):
            entry[key] = r[key]
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
    # `stare`: absent while being worked on; "oprit" when it cannot be done (with
    # `motiv`), "integrat" when it is an amendment folded into its base PUZ
    # (`integrat_in`). Neither has a map entry of its own.
    stare = r.get("stare")
    if stare in ("oprit", "integrat") and not args.force:
        sys.exit("recipe is '%s' (%s) - nothing to build" % (
            stare, r.get("motiv") or ("integrat în " + str(r.get("integrat_in")))))
    if not os.path.exists(plate_path(r)):
        if not os.path.exists(pdf_path(r)):
            cmd_fetch(r, args)
        cmd_render(r, args)
    if not (r.get("valabilitate") or {}).get("pana_la"):
        print("WARNING: no validity in the recipe - run `hcl` and set `valabilitate`")
    if not r.get("gcp_px"):
        # Right after transcribing an inventory, before any point is picked: the
        # area, side and perimeter checks need no fit, so run them alone.
        if points_en(r):
            check_area(r, ring_en(r))
        sys.exit("no control points yet - geometry checks above; pick gcp_px to go on")
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
            legend.save(os.path.join(cache_dir(r), "legenda.webp"), quality=80)
        print("dry run: outputs left in", cache_dir(r))
        return
    publish(r, overlay, legend, bounds, boundary, area, rms)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new", help="recipe skeleton from the decision listing")
    s.add_argument("an", type=int); s.add_argument("nr", type=int)
    s.add_argument("--folder", default="cluj-napoca"); s.add_argument("--localitate", default="cluj")
    for name in ("fetch", "render", "predict", "hcl", "related"):
        s = sub.add_parser(name); s.add_argument("recipe")
    s = sub.add_parser("grid"); s.add_argument("recipe")
    for a in ("x0", "y0", "x1", "y1"):
        s.add_argument(a, type=int)
    s.add_argument("--scale", type=float, default=1.0); s.add_argument("--step", type=int, default=50)
    s = sub.add_parser("overlay", help="draw the fitted boundary over a crop of the plate")
    s.add_argument("recipe")
    for a in ("x0", "y0", "x1", "y1"):
        s.add_argument(a, type=int)
    s.add_argument("--scale", type=float, default=1.0); s.add_argument("--step", type=int, default=100)
    s.add_argument("--without", nargs="*", default=[], help="control points to leave out of the fit")
    s = sub.add_parser("vertices"); s.add_argument("recipe"); s.add_argument("names", nargs="+")
    s.add_argument("--radius", type=int, default=90); s.add_argument("--scale", type=float, default=2.6)
    s.add_argument("--step", type=int, default=20)
    s = sub.add_parser("build"); s.add_argument("recipe")
    s.add_argument("--force", action="store_true"); s.add_argument("--dry-run", action="store_true")
    s.add_argument("--no-check", action="store_true"); s.add_argument("--zoom", type=int, default=18)
    s = sub.add_parser("legend", help="rebuild only the legend (published PUZ: legenda.webp + puz.json)")
    s.add_argument("recipe"); s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("geocode", help="rough Stereo70 position from OpenStreetMap")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--streets", nargs=2, metavar="REGEX", help='two street names meeting on the plate, e.g. "Buftea" "Scor.arilor"')
    g.add_argument("--address", help="an address, e.g. \"Strada Buftea 2, Cluj-Napoca\"")
    s = sub.add_parser("osm", help="draw OpenStreetMap streets and buildings over the plate")
    s.add_argument("recipe")
    for a in ("x0", "y0", "x1", "y1"):
        s.add_argument(a, type=int, nargs="?", default=None)
    s.add_argument("--scale", type=float, default=None); s.add_argument("--step", type=int, default=100)
    s = sub.add_parser("osm-snap", help="control point at the OSM corner/crossing nearest a picked plate pixel")
    s.add_argument("recipe"); s.add_argument("name"); s.add_argument("x", type=int); s.add_argument("y", type=int)
    s.add_argument("--max", type=float, default=6.0, help="metres to search around the predicted position")
    s.add_argument("--kind", choices=("any", "building", "street"), default="any")
    s.add_argument("--pick", type=int, default=None); s.add_argument("--check", action="store_true")
    s.add_argument("--write", action="store_true")
    s = sub.add_parser("caroiaj", help="label the crosses of an unlabelled Stereo70 grid")
    s.add_argument("recipe"); s.add_argument("--write", action="store_true", help="store the labelled crosses as repere/gcp_px")
    args = ap.parse_args()
    if args.cmd == "new":
        return cmd_new(args)
    if args.cmd == "geocode":
        return cmd_geocode(args)
    r = load(args.recipe)
    {"fetch": cmd_fetch, "render": cmd_render, "grid": cmd_grid, "predict": cmd_predict,
     "vertices": cmd_vertices, "overlay": cmd_overlay, "hcl": cmd_hcl, "related": cmd_related,
     "caroiaj": cmd_caroiaj, "osm": cmd_osm, "osm-snap": cmd_osm_snap, "build": cmd_build,
     "legend": cmd_legend}[args.cmd](r, args)


if __name__ == "__main__":
    main()
