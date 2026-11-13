"""PUZ pipeline: from a council decision PDF to a georeferenced overlay on the site.

Every PUZ is described by a small recipe, puzuri/<localitate>/<id>.json: where the
decision lives, which PDF page holds the regulations plate, the boundary coordinates
transcribed from the plate's "Inventar de coordonate", the pixel position of some of
those points on the plate, and the crops (legend, areas to mask out). Everything else
is derived from it and can be rebuilt at any time:

    tools/puz/puz.sh new      2026 597                           # recipe skeleton from the listing
    tools/puz/puz.sh fetch    puzuri/cluj-napoca/2026-597.json   # PDF + page contact sheet
    tools/puz/puz.sh render   puzuri/cluj-napoca/2026-597.json   # plate page at full resolution
    tools/puz/puz.sh grid     puzuri/cluj-napoca/2026-597.json x0 y0 x1 y1 [--scale S --step N]
    tools/puz/puz.sh predict  puzuri/cluj-napoca/2026-597.json   # where the other points should be
    tools/puz/puz.sh vertices puzuri/cluj-napoca/2026-597.json 10 12 13 ...
    tools/puz/puz.sh overlay  puzuri/cluj-napoca/2026-597.json x0 y0 x1 y1 [--without 84]
    tools/puz/puz.sh hcl      puzuri/cluj-napoca/2026-597.json   # the decision text, laid out
    tools/puz/puz.sh related  puzuri/cluj-napoca/2026-597.json   # later decisions extending/amending it
    tools/puz/puz.sh geocode  --streets "Buftea" "Scor.arilor"   # rough position, for unlabelled grids
    tools/puz/puz.sh caroiaj  puzuri/cluj-napoca/2026-24.json [--write]   # label unlabelled grid crosses
    tools/puz/puz.sh osm      puzuri/cluj-napoca/2026-24.json [x0 y0 x1 y1]  # OSM drawn over the plate
    tools/puz/puz.sh osm-snap puzuri/cluj-napoca/2026-24.json NAME x y [--write]  # OSM control point
    tools/puz/puz.sh osm-extract                                 # refresh the OSM extract (laptop)
    tools/puz/puz.sh build    puzuri/cluj-napoca/2026-597.json   # checks, warp, legend, publish
    tools/puz/puz.sh legend   puzuri/cluj-napoca/2026-597.json   # rebuild only the legend
    tools/puz/puz.sh audit    puzuri/cluj-napoca/2026-597.json   # check an agent's commit (batch runs)
    tools/puz/puz.sh next     [--count 6]                        # what a batch does next, and progress
    tools/puz/puz.sh doctor                                      # packages, poppler, network, git
    tools/puz/puz.sh sync-docs                                   # fill this machine's documents backup
    tools/puz/puz.sh merge-index BASE OURS THEIRS                # git merge driver for puz.json
    tools/puz/puz.sh retire-expired [--write]                    # take expired PUZ-uri off the map

puz.sh runs this file with `py -3.13` on the Windows laptop and `python3` elsewhere
(Claude Code cloud sessions); setup.sh installs the dependencies on Linux.

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
import warnings

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
# shapely 2.2 deprecates ops.transform (still fine below 3, see requirements.txt); the
# warning would only distract whoever reads the output.
warnings.filterwarnings("ignore", message=r".*shapely\.ops\.transform", category=DeprecationWarning)


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
    """Arial on Windows, DejaVu on Linux (cloud sessions), else Pillow's own scalable
    font. The grid labels on crops must stay readable: they are how positions are read."""
    names = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
    names.append("/usr/share/fonts/truetype/dejavu/" + names[1])
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size)
    except TypeError:
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


def validity_end(r):
    """The PUZ's last day of validity, extensions included; None when not known."""
    v = r.get("valabilitate") or {}
    ends = [x for x in [v.get("pana_la")] + [p.get("pana_la") for p in r.get("prelungiri", [])] if x]
    return max(ends) if ends else None


def today_iso():
    import datetime
    return datetime.date.today().isoformat()


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

# The OSM commands read OpenStreetMap from an extract kept in the repository: the
# buildings and streets of the Cluj-Napoca area, cut from Geofabrik's daily Romania
# extract by `osm-extract`. Public Overpass servers are often busy, and cloud sessions
# sometimes can't reach them at all, so they are only the fallback: for a place
# outside the extract, or with --live for features newer than it.
OSM_EXTRACT = os.path.join(ROOT, "puzuri", "cluj-napoca", "osm.json.gz")
GEOFABRIK_PBF = "https://download.geofabrik.de/europe/romania-latest.osm.pbf"
OSM_EXTRACT_MAX_AGE_DAYS = 120
OVERPASS_SERVERS = ("https://overpass-api.de/api/interpreter",
                    "https://maps.mail.ru/osm/tools/overpass/api/interpreter")
NOMINATIM = "https://nominatim.openstreetmap.org/search"
CLUJ_BBOX = (46.70, 23.45, 46.86, 23.75)   # S, W, N, E
LIVE_HELP = "ask the public Overpass servers instead of the extract (for features newer than it)"

_to70 = None


def to_stereo70(lon, lat):
    global _to70
    if _to70 is None:
        from pyproj import Transformer
        _to70 = Transformer.from_crs(4326, 3844, always_xy=True)
    return _to70.transform(lon, lat)


_osm_extract = None


def osm_extract():
    """The extract ({bbox, data_osm, buildings: [[id, [lon, lat, ...]]],
    streets: [[id, name, highway, [lon, lat, ...]]]}), or None when it is missing."""
    global _osm_extract
    if _osm_extract is None:
        _osm_extract = False
        if os.path.exists(OSM_EXTRACT):
            import gzip
            with gzip.open(OSM_EXTRACT, "rt", encoding="utf-8") as f:
                _osm_extract = json.load(f)
    return _osm_extract or None


def extract_elements(box=None, name=None, buildings=True):
    """Ways of the extract shaped like Overpass's `out tags geom` elements: those whose
    bounds meet box (S, W, N, E), or the streets whose name matches the regex `name`.
    None when there is no extract or it doesn't cover the box."""
    x = osm_extract()
    if not x:
        return None
    if box:
        bs, bw, bn, be = x["bbox"]
        if not (bs <= box[0] and bw <= box[1] and box[2] <= bn and box[3] <= be):
            return None
    rx = re.compile(name, re.I) if name else None

    def meets(flat):
        lons, lats = flat[0::2], flat[1::2]
        return not (max(lats) < box[0] or min(lats) > box[2] or max(lons) < box[1] or min(lons) > box[3])

    def element(wid, tags, flat):
        return {"type": "way", "id": wid, "tags": tags,
                "geometry": [{"lon": flat[i], "lat": flat[i + 1]} for i in range(0, len(flat), 2)]}
    out = []
    for wid, nm, kind, flat in x["streets"]:
        if (rx is None or (nm and rx.search(nm))) and (box is None or meets(flat)):
            out.append(element(wid, {"highway": kind, **({"name": nm} if nm else {})}, flat))
    if buildings and rx is None:
        out += [element(wid, {"building": "yes"}, flat) for wid, flat in x["buildings"] if box is None or meets(flat)]
    return {"elements": out}


def osm_extract_note():
    x = osm_extract()
    return "extrasul OSM din %s" % x.get("data_osm", "?")[:10] if x else "Overpass"


def street_lines(pattern, live=False):
    """All OSM ways in Cluj-Napoca whose name matches the regex (case-insensitive),
    as Stereo 70 lines. A regex copes with diacritics: "Scor.arilor"."""
    from shapely.geometry import LineString, MultiLineString
    data = None if live else extract_elements(name=pattern, buildings=False)
    if data is None:
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
        a, na = street_lines(args.streets[0], args.live)
        b, nb = street_lines(args.streets[1], args.live)
        if a is None or b is None:
            sys.exit("street not found in OSM (%s): %s%s" % (
                "Overpass" if args.live else osm_extract_note(), args.streets[0] if a is None else args.streets[1],
                "" if args.live else " - a new street may be missing from the extract: try --live"))
        print("OSM names (%s):" % ("Overpass" if args.live else osm_extract_note()), na, "/", nb)
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


def overpass(query, tries=2):
    """A query to the public Overpass servers, each in turn. The fallback for the
    extract: these servers are often busy, and cloud sessions can't always reach them."""
    import time
    for k in range(tries):
        for url in OVERPASS_SERVERS:
            try:
                req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": query}).encode(), headers=UA)
                return json.loads(urllib.request.urlopen(req, timeout=90).read().decode("utf-8"))
            except Exception as e:
                print("Overpass %s: %s" % (urllib.parse.urlparse(url).netloc, e))
        if k < tries - 1:
            print("Overpass: retrying in %d s" % (20 * (k + 1)))
            time.sleep(20 * (k + 1))
    sys.exit("Overpass unavailable on every server - try again later (the extract covers Cluj-Napoca without it)")


def osm_features(r, center, radius, live=False):
    """Buildings and streets within radius of a Stereo 70 point: from the extract, or
    from Overpass (live, or outside the extract), written to puz_cache/<id>/osm.json.
    Overpass answers are reused from there while they cover the circle."""
    from pyproj import Transformer
    from shapely.geometry import LineString, Point
    path = os.path.join(cache_dir(r), "osm.json")
    lon, lat = Transformer.from_crs(3844, 4326, always_xy=True).transform(*center)
    dlat = radius / 111000.0 * 1.05
    dlon = dlat / math.cos(math.radians(lat))
    data = None if live else extract_elements((lat - dlat, lon - dlon, lat + dlat, lon + dlon))
    source = osm_extract_note()
    if data is None:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("sursa", "Overpass") == "Overpass" and math.dist(cached["center"], center) + radius <= cached["radius"] + 1:
                return cached
        q = ('[out:json][timeout:90];(way["building"](around:{r},{la},{lo});way["highway"](around:{r},{la},{lo}););'
             'out tags geom;').format(r=int(radius), la=lat, lo=lon)
        data, source = overpass(q), "Overpass"
    feats = {"center": list(center), "radius": radius, "sursa": source, "buildings": [], "streets": []}
    c = Point(center)
    for el in data.get("elements", []):
        pts = [list(to_stereo70(p["lon"], p["lat"])) for p in el.get("geometry", [])]
        tags = el.get("tags", {})
        if len(pts) < 2 or (source != "Overpass" and LineString(pts).distance(c) > radius):
            continue        # the extract is cut by bounds; Overpass's `around` is a distance
        if "building" in tags and len(pts) >= 3:
            feats["buildings"].append({"id": el["id"], "pts": pts})
        elif "highway" in tags:
            feats["streets"].append({"id": el["id"], "name": tags.get("name", ""), "kind": tags["highway"], "pts": pts})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(feats, f)
    print("OSM (%s): %d buildings, %d street segments within %d m"
          % (source, len(feats["buildings"]), len(feats["streets"]), radius))
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
    feats = osm_features(r, center, radius, args.live)
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
    cands = [(math.dist(p, (E, N)), k, p, kind) for k, p, kind in osm_candidates(osm_features(r, center, radius, args.live))]
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


def cmd_osm_extract(args):
    """Refresh OSM_EXTRACT: download Geofabrik's Romania extract (~330 MB, into
    puz_cache/osm/) and keep the buildings and highways with a node in CLUJ_BBOX. Takes
    some minutes; run on the laptop every month or two, or when an agent finds the
    extract missing something, and commit the file."""
    import gzip
    import time
    try:
        import osmium
    except ImportError:
        sys.exit("osm-extract needs pyosmium: py -3.13 -m pip install osmium")
    t0 = time.time()
    pbf = args.pbf
    if not pbf:
        pbf = os.path.join(CACHE, "osm", "romania-latest.osm.pbf")
        os.makedirs(os.path.dirname(pbf), exist_ok=True)
        print("downloading", GEOFABRIK_PBF)
        with urllib.request.urlopen(urllib.request.Request(GEOFABRIK_PBF, headers=UA), timeout=120) as resp, \
                open(pbf + ".part", "wb") as f:
            while True:
                block = resp.read(1 << 20)
                if not block:
                    break
                f.write(block)
        os.replace(pbf + ".part", pbf)
    stamp = osmium.io.Reader(pbf, osmium.osm.osm_entity_bits.NOTHING).header().get("osmosis_replication_timestamp", "")
    print("cutting %s (OSM data of %s) to %s" % (os.path.basename(pbf), stamp or "?", CLUJ_BBOX))
    S, W, N, E = CLUJ_BBOX
    buildings, streets = [], []
    fp = (osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY)
          .with_locations("flex_mem")
          .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
          .with_filter(osmium.filter.KeyFilter("building", "highway")))
    for w in fp:
        try:
            pts = [(round(n.lon, 6), round(n.lat, 6)) for n in w.nodes]
        except osmium.InvalidLocationError:
            continue
        if len(pts) < 2 or not any(S <= la <= N and W <= lo <= E for lo, la in pts):
            continue
        flat = [c for p in pts for c in p]
        if "building" in w.tags:
            buildings.append([w.id, flat])
        else:
            streets.append([w.id, w.tags.get("name", ""), w.tags["highway"], flat])
    buildings.sort(); streets.sort()
    doc = {"bbox": list(CLUJ_BBOX), "data_osm": stamp, "sursa": GEOFABRIK_PBF,
           "licenta": "© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)",
           "buildings": buildings, "streets": streets}
    tmp = OSM_EXTRACT + ".part"
    with open(tmp, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as f:
        f.write(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    os.replace(tmp, OSM_EXTRACT)
    print("%s: %d buildings, %d streets, %.1f MB, %.0f s"
          % (os.path.relpath(OSM_EXTRACT, ROOT), len(buildings), len(streets), os.path.getsize(OSM_EXTRACT) / 1e6,
             time.time() - t0))


# --- fetch / render ----------------------------------------------------------------

# Linked from every page of primariaclujnapoca.ro, not part of any decision.
SITE_WIDE_PDF = re.compile(r"Politica-Anti-Mita", re.I)


def decision_documents(r):
    """The recipe's PDF plus every other PDF linked from the decision's page, and the
    PDF of an amending decision whose plate replaced the original. Some decision pages
    link no PDF at all (5/2020, 123/2021): the recipe's `pdf` is then null."""
    urls = []
    for u in (r["hcl"]["pdf"], plate_pdf_url(r)):
        if u and u not in urls:
            urls.append(u)
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


def download_documents(r, verbose=True):
    """Download whatever is missing of the decision's documents into documente/<id>/."""
    paths = []
    for url in decision_documents(r):
        dst = os.path.join(docs_dir(r), doc_name(url))
        if not os.path.exists(dst):
            quoted = urllib.parse.quote(url, safe=":/()%?=&")
            with urllib.request.urlopen(urllib.request.Request(quoted, headers=UA), timeout=180) as resp:
                data = resp.read()
            with open(dst, "wb") as f:
                f.write(data)
        if verbose:
            print("document:", dst, os.path.getsize(dst) // 1024, "KB")
        paths.append(dst)
    return paths


def cmd_fetch(r, args):
    paths = download_documents(r)
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


def independent_checks(r):
    """Check points that are not also control points: the only test of a fit beyond
    its own residuals. Four control points leave an affine fit two equations to
    spare, and four built as a parallelogram none: their residuals come out 0
    wherever the points sit (496/2026)."""
    gcp = r.get("gcp_px", {})
    return [n for n in r.get("verificare_px", {}) if n not in gcp]


def fit_places_boundary(r):
    """True when the fit carries the boundary itself onto the map (a boundary traced on
    the plate, or OSM control points), not just the plate's image under an inventory."""
    return boundary_digitized(r) or osm_method(r)


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
    if not independent_checks(r):
        if not fit_places_boundary(r):
            print("no check points: the boundary comes from the inventory; only the plate's placement is untested")
        elif r.get("verificare_umana"):
            print("no check points; position confirmed by a person: %s" % r["verificare_umana"])
        else:
            print("no check points: the traced boundary is placed by this fit alone and nothing tests it"
                  " -> NOT VERIFIED (add a check point read off the plate, or from OSM with osm-snap --check)")
            ok = False
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
    # Boxes painted over with the paper around them, before warping: owners' names
    # written on the lots must not reach the map (590/2021).
    for x0, y0, x1, y1 in cut.get("acopera_px", []):
        edge = np.concatenate([img[max(y0 - 2, 0):y0, x0:x1].reshape(-1, 3), img[y1:y1 + 2, x0:x1].reshape(-1, 3),
                               img[y0:y1, max(x0 - 2, 0):x0].reshape(-1, 3), img[y0:y1, x1:x1 + 2].reshape(-1, 3)])
        paper = edge[edge.max(axis=1) > 110]
        img[y0:y1, x0:x1] = np.median(paper if len(paper) else edge, axis=0).astype(np.uint8)
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
    index = load_index()
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
    save_index(index)


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
    # The listing names the owners after "; beneficiar(i):", ", beneficiari:" or ". Beneficiar:".
    t = re.split(r"[;,.]\s*beneficiar", t, flags=re.I)[0]
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
    if validity_end(r):
        entry["valabilitate"] = {"ani": v.get("ani"), "pana_la": validity_end(r)}
        if ext:
            entry["valabilitate"].update({"initial_pana_la": v.get("pana_la"), "prelungiri": ext})
    for key in ("diferente_fata_de_plansa", "conditii", "modifica", "modificat_de"):
        if r.get(key):
            entry[key] = r[key]
    index = [e for e in load_index() if e["id"] != r["id"]] + [entry]
    save_index(index)
    print("published:", d, "| index entries:", len(index))


def cmd_retire_expired(args):
    """Takes off the map the published PUZ-uri whose validity, extensions included, has
    ended: since 2026-11-11 expired PUZ-uri are not on the map. Removes the puz.json
    entry and ClujPugWeb/wwwroot/puz/<id>/, and marks the recipe "expirat"; the recipe
    keeps all its work, so should an extension turn up, add it to `prelungiri`, drop
    `stare` and build again. Amendments folded into the base stay "integrat" in it.
    Lists only, unless --write."""
    import shutil
    def dmy(iso):
        return "%s.%s.%s" % tuple(reversed(iso.split("-"))) if iso else "?"
    today, index, gone = today_iso(), load_index(), []
    for e in index:
        p = os.path.join(ROOT, "puzuri", args.folder, e["id"] + ".json")
        if not os.path.exists(p):
            continue
        r = load(p)
        end = validity_end(r)
        if not end or end >= today:
            continue
        v = r.get("valabilitate") or {}
        term = "%s ani de la ședința din %s" % (v.get("ani"), dmy(r["hcl"].get("data_sedinta"))) if v.get("ani") else ""
        ext = ", ".join("HCL " + x["hcl"] for x in r.get("prelungiri", []) if x.get("hcl"))
        term = "; ".join(t for t in (term, ext and "prelungit prin " + ext) if t)
        motiv = "Valabilitate expirată la %s%s. Fusese publicat; scos de pe hartă la %s." % (
            dmy(end), " (%s)" % term if term else "", dmy(today))
        print("%-10s expirat la %s  %s" % (e["id"], dmy(end), e.get("titlu", "")[:70]))
        if args.write:
            # Two lines after "localitate", the rest of the file as it was (some recipes
            # were laid out by hand; dump_recipe would reflow them).
            with open(p, encoding="utf-8", newline="") as f:
                text = f.read()
            nl = "\r\n" if "\r\n" in text else "\n"
            m = re.search(r'^([ \t]*)"localitate": .*,(?=\r?$)', text, re.M)
            if m and "stare" not in r and "motiv" not in r:
                text = text[:m.end()] + "".join(
                    '%s%s%s: %s,' % (nl, m.group(1), json.dumps(k), json.dumps(val, ensure_ascii=False))
                    for k, val in (("stare", "expirat"), ("motiv", motiv))) + text[m.end():]
                with open(p, "w", encoding="utf-8", newline="") as f:
                    f.write(text)
            else:
                r.update({"stare": "expirat", "motiv": motiv}); dump_recipe(r, p)
            assert load(p).get("stare") == "expirat", p
            shutil.rmtree(os.path.join(WWW, "puz", e["id"]), ignore_errors=True)
        gone.append(e["id"])
    if args.write and gone:
        save_index([e for e in index if e["id"] not in gone])
    print("%d PUZ-uri publicate au expirat%s" % (len(gone), (
        ": scoase de pe hartă" if args.write else "; --write le scoate") if gone else ""))


def cmd_build(r, args):
    # `stare`: absent while being worked on; "oprit" when it cannot be done (with
    # `motiv`), "integrat" when it is an amendment folded into its base PUZ
    # (`integrat_in`), "expirat" when its validity ended before it was published
    # (since 2026-11-11 expired PUZ-uri are not put on the map). None has a map entry.
    stare = r.get("stare")
    if stare in ("oprit", "integrat", "expirat") and not args.force:
        sys.exit("recipe is '%s' (%s) - nothing to build" % (
            stare, r.get("motiv") or ("integrat în " + str(r.get("integrat_in")))))
    end = validity_end(r)
    if (end and end < today_iso() and not args.dry_run and not args.force
            and not any(e["id"] == r["id"] for e in load_index())):
        sys.exit("validity ended on %s (extensions included): expired PUZ-uri are not published. Set "
                 "\"stare\": \"expirat\" (add-puz skill). --force only if an amendment in force keeps it valid."
                 % end)
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
        if not r.get("verificare_umana"):
            sys.exit("quality gate failed - fix the recipe (or --force to build anyway)")
        # A person looked at the result on the map and accepted it as it is.
        print("quality gate failed, published on a person's approval: %s" % r["verificare_umana"])
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


# --- batch runs: what to do next, checking an agent's commit, the local backup ---------
# A batch (the puz-batch skill) runs one fresh agent per PUZ, locally or in a Claude Code
# cloud session. `next` picks the work, `audit` checks each agent's commit before it is
# pushed, `doctor` checks a new machine, and `sync-docs` fills the laptop's backup of the
# documents downloaded in the cloud, which git does not carry.

PUZ_APPROVAL = re.compile(r"\baprob\w*\s+(?:a\s+)?(?:P\.?\s?U\.?\s?Z|Planului\s+Urbanistic\s+Zonal)", re.I)
NOT_A_PUZ = re.compile(r"^Aprobarea\s+încheierii", re.I)


def load_index():
    if not os.path.exists(INDEX):
        return []
    with open(INDEX, encoding="utf-8") as f:
        return json.load(f)


def save_index(index, path=INDEX):
    """Writes puz.json newest first, with CRLF line ends, the ones it has had in git
    since the laptop first wrote it: left to the system, a build on Linux writes LF and
    the diff covers the whole file."""
    index.sort(key=lambda e: (e.get("data") or "", e["id"]), reverse=True)
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
        f.write("\n")


def cmd_merge_index(args):
    """Git merge driver for puz.json (see .gitattributes). Parallel batch sessions each
    add their own PUZ-uri; when two add an entry at the same place, a line merge
    conflicts, but entry by entry the merge is plain: keep what each side added or
    changed. Exits 1, leaving the file alone, when both sides changed the same entry
    differently, or a file doesn't parse."""
    def read(path):
        try:
            with open(path, encoding="utf-8") as f:
                return {e["id"]: e for e in json.load(f)}
        except (OSError, ValueError, KeyError, TypeError):
            return None
    base, ours, theirs = read(args.base), read(args.ours), read(args.theirs)
    if ours is None or theirs is None:
        print("merge-index: puz.json doesn't parse on one side", file=sys.stderr)
        sys.exit(1)
    base = base or {}
    merged, clashes = [], []
    for pid in sorted(set(base) | set(ours) | set(theirs)):
        b, o, t = base.get(pid), ours.get(pid), theirs.get(pid)
        if o == t or t == b:
            pick = o
        elif o == b:
            pick = t
        else:
            clashes.append(pid)
            continue
        if pick is not None:
            merged.append(pick)
    if clashes:
        print("merge-index: both sides changed %s" % ", ".join(clashes), file=sys.stderr)
        sys.exit(1)
    save_index(merged, args.ours)


def recipe_paths(folder):
    d = os.path.join(ROOT, "puzuri", folder)
    return sorted(os.path.join(d, f) for f in os.listdir(d) if re.match(r"\d{4}-\d+\.json$", f))


def batch_candidates(folder):
    """Decisions that approve a PUZ or amend one. Extensions are not here: the base
    PUZ's agent finds them with `related`. Neither are street names, land transfers,
    association agreements or rejected drafts."""
    with open(os.path.join(ROOT, "puzuri", folder, "hotarari-puz.json"), encoding="utf-8") as f:
        listing = json.load(f)["hotarari"]
    return [h for h in listing if not NOT_A_PUZ.search(h["titlu"])
            and (PUZ_APPROVAL.search(h["titlu"]) or re.match(r"Modificarea\b", h["titlu"], re.I))]


def recipe_state(folder, pid, published):
    """None (no recipe), "publicat", "oprit", "integrat", "expirat", or "început" (a
    recipe without a map entry or a stop: an interrupted run)."""
    p = os.path.join(ROOT, "puzuri", folder, pid + ".json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        r = json.load(f)
    return r.get("stare") or ("publicat" if pid in published else "început")


def cmd_next(args):
    """The next decisions to process, newest first, and how far the batch has come."""
    import collections
    published = {e["id"] for e in load_index()}
    cands = sorted((h for h in batch_candidates(args.folder) if args.from_year <= h["an"] <= args.to_year),
                   key=lambda h: (h["an"], h["nr"]), reverse=True)
    counts = collections.Counter()
    todo = []
    for h in cands:
        pid = "%d-%d" % (h["an"], h["nr"])
        state = recipe_state(args.folder, pid, published)
        counts[state or "de făcut"] += 1
        if state in (None, "început") or (state == "oprit" and args.retry_stopped):
            todo.append((h, state))
    print("%d-%d, cele mai noi întâi: %s" % (args.from_year, args.to_year, ", ".join(
        "%s %d" % (k, counts[k]) for k in ("publicat", "integrat", "oprit", "expirat", "început", "de făcut")
        if counts[k])))
    for h, state in todo[:args.count]:
        print("%d %d  %s%s" % (h["an"], h["nr"], clean_title(h["titlu"])[:110],
                               "  [reluare: rulare întreruptă]" if state == "început" else
                               "  [reluare: oprit]" if state == "oprit" else ""))


def git(*cmd):
    return subprocess.run(["git"] + list(cmd), cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout


def normalize_ro(text):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c)).lower()


# "beneficiari: A B, C D și E F, pentru un teren ...": the names run until the first
# part with a lower-case word.
# The pages' text breaks words, the keyword too: "beneficiar ă :", "beneficiar e :",
# "beneficia ri:", "beneficia re:".
BENEFICIARY_WORD = r"benefici\s?a\s?r\w*(?:\s[ăaie]{1,2}\b)?"
BENEFICIARY_CLAUSE = re.compile(BENEFICIARY_WORD + r"\s*:?\s+(.{3,300})", re.I | re.S)
NAME_TOKEN = re.compile(r"^(?:[A-ZĂÂÎȘŞȚŢ][\wăâîșşțţĂÂÎȘŞȚŢ.\-]*|S\.?C\.?|S\.?R\.?L\.?|S\.?A\.?)$")
NOT_A_NAME = {normalize_ro(w) for w in (
    "S.R.L", "SRL", "S.A", "SA", "S.C", "SC", "SNC", "PFA", "II", "Cluj", "Napoca", "Cluj-Napoca", "Municipiul",
    "Municipiului", "Consiliul", "Local", "Hotărâre", "Hotărârea", "Art", "Având", "Vezi", "Pagina", "Strada",
    "Str", "P.U.Z", "PUZ", "U.T.R", "UTR", "Prin", "Prezenta", "Primarul", "Primăria", "Direcția", "Ordinul",
    "Legea", "Nr", "Proiectant", "Elaborator", "Beneficiar", "Beneficiari", "Examinând", "Proiectul", "Referatul",
    "Raportul", "Comisia", "Arhitect", "Arhitectul", "Șef", "Avizul", "Planul", "Urbanistic", "Zonal", "Aprobarea",
    "Statul", "Român", "Județul", "Ministerul", "Agenția", "Compania", "Societatea", "Asociația", "Parohia")}


def decision_text(r):
    """The decision's text, from hotarare.txt or else the decision's page; None when
    there is none."""
    try:
        with open(text_path(r), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        try:
            text = decision_text_from_page(r["hcl"]["pagina"])
        except Exception:
            return None
    if NO_PAGE_TEXT in text or len(text) < 400:
        return None
    return text


def name_tokens(part):
    """The words of one name, with the pieces the pages' text breaks words into put
    back together: "R oșca" -> "Roșca", "R i mbașiu" -> "Rimbașiu". A piece is a
    lower-case word after one of at most two letters, or a lone lower-case letter."""
    tokens = []
    for t in part.strip(" .").split():
        if tokens and t[:1].islower() and (len(tokens[-1]) <= 2 or len(t) == 1):
            tokens[-1] += t
        else:
            tokens.append(t)
    return tokens


def beneficiary_words(text):
    """Words of the names after "beneficiar(i):" in the decision's text: the owners,
    which must not appear on the public map or in the repository. Also says whether
    some "beneficiar(i):" was followed by something not read as a name, so that an
    empty set can tell "no owners named" from "owners not read"."""
    words, unread = set(), False
    for m in BENEFICIARY_CLAUSE.finditer(text):
        for i, part in enumerate(re.split(r",|;|\s+și\s+", re.sub(r"\s+", " ", m.group(1)))):
            tokens = name_tokens(part)
            if not tokens or not all(NAME_TOKEN.match(t) for t in tokens):
                # Only a clause with a colon: "suportate de beneficiarii acesteia" is prose.
                unread |= i == 0 and ":" in text[m.start():m.start(1)]
                break
            for t in tokens:
                n = normalize_ro(t.strip(".-"))
                if len(n) >= 3 and n not in NOT_A_NAME:
                    words.add(n)
    return words, unread


def cmd_audit(r, args):
    """Checks an agent's work on one PUZ before it is pushed: the outcome, the quality
    gates, which files the commit touched, and that no owner is named."""
    pid, folder = r["id"], os.path.dirname(os.path.relpath(r["_path"], ROOT)).replace("\\", "/")
    problems, checks, notes = [], [], []
    entry = next((e for e in load_index() if e["id"] == pid), None)
    stare = r.get("stare")
    pub_dir = "ClujPugWeb/wwwroot/puz/%s/" % pid
    if stare == "oprit":
        checks.append("oprit: %s" % r.get("motiv"))
        if not r.get("motiv"):
            problems.append("oprit fără `motiv`")
        if entry or os.path.isdir(os.path.join(ROOT, pub_dir)):
            problems.append("oprit, dar a rămas publicat (puz.json sau %s)" % pub_dir)
    elif stare == "expirat":
        end = validity_end(r)
        checks.append("expirat la %s" % end)
        if not end:
            problems.append("expirat fără `valabilitate.pana_la`")
        elif end >= today_iso():
            problems.append("marcat expirat, dar valabil până la %s" % end)
        if entry or os.path.isdir(os.path.join(ROOT, pub_dir)):
            problems.append("expirat, dar publicat (puz.json sau %s)" % pub_dir)
    elif stare == "integrat":
        base = r.get("integrat_in")
        base_entry = next((e for e in load_index() if e["id"] == base), None)
        ref = "%d/%d" % (r["hcl"]["nr"], r["hcl"]["an"])
        mods = [m if isinstance(m, str) else m.get("hcl") for m in (base_entry or {}).get("modificat_de", [])]
        checks.append("integrat în %s" % base)
        base_path = os.path.join(ROOT, folder, "%s.json" % base)
        base_expired = os.path.exists(base_path) and load(base_path).get("stare") == "expirat"
        if not base_entry and base_expired:
            checks.append("baza %s a expirat și e scoasă de pe hartă" % base)
        elif not base_entry:
            problems.append("integrat în %s, care nu e publicat" % base)
        elif ref not in mods:
            problems.append("%s nu apare în `modificat_de` la %s" % (ref, base))
    elif not entry:
        problems.append("fără `stare` și nepublicat: rulare neterminată")
    else:
        ok_fit, pe, pn, rms, worst = check_fit(r)
        ok_area, area = check_area(r, ring_en(r, pe, pn))
        checks.append("porți: potrivire %s (rms %.2f m), arie %s" % (
            "OK" if ok_fit else "EȘUAT", rms, "OK" if ok_area else "EȘUAT"))
        if not (ok_fit and ok_area):
            if r.get("verificare_umana"):
                notes.append("porțile nu trec; publicat cu aprobarea unui om: %s" % r["verificare_umana"])
            else:
                problems.append("porțile de calitate nu trec")
        if not independent_checks(r):
            if not fit_places_boundary(r):
                notes.append("niciun punct de verificare: limita vine din inventar, dar așezarea planșei nu e verificată")
            elif r.get("verificare_umana"):
                notes.append("niciun punct de verificare; poziția confirmată de un om: %s" % r["verificare_umana"])
            else:
                problems.append("limita trasată nu e verificată de nimic independent: niciun punct în `verificare_px`")
        if abs(entry.get("suprafata_m2", 0) - area) > 1:
            problems.append("puz.json are altă arie (%s) decât rețeta (%.0f): build nerulat după ultima modificare"
                            % (entry.get("suprafata_m2"), area))
        if not os.path.exists(os.path.join(ROOT, pub_dir, "plansa.webp")):
            problems.append("lipsește %splansa.webp" % pub_dir)
        if bool(r.get("legenda_px")) != bool(entry.get("legenda")):
            problems.append("legenda din puz.json nu corespunde cu `legenda_px`")

    # The commit: this PUZ's files only, plus a base or amendment it was folded into.
    commit = args.commit
    msg = git("log", "-1", "--format=%B", commit)
    files = [f for f in git("show", "--name-only", "--format=", commit).splitlines() if f]
    related = {pid, r.get("integrat_in")} | {"%s-%s" % (m.split("/")[1], m.split("/")[0])
                                             for m in r.get("modifica", []) if isinstance(m, str) and "/" in m}
    for p in recipe_paths(os.path.basename(folder)):
        with open(p, encoding="utf-8") as f:
            if json.load(f).get("integrat_in") == pid:
                related.add(os.path.basename(p)[:-5])
    allowed = {"%s/documente/SHA256SUMS" % folder, "ClujPugWeb/wwwroot/puz/puz.json"}
    allowed |= {"%s/%s.json" % (folder, x) for x in related if x}
    outside = [f for f in files if f not in allowed
               and not any(f.startswith("ClujPugWeb/wwwroot/puz/%s/" % x) for x in related if x)]
    ref = "HCL %d/%d" % (r["hcl"]["nr"], r["hcl"]["an"])
    checks.append("commit %s: %d fișiere" % (git("rev-parse", "--short", commit).strip(), len(files)))
    if not msg.startswith("PUZ "):
        problems.append("ultimul commit nu e al unui PUZ: %s" % (msg.splitlines() or [""])[0])
    elif ref not in msg and not stare == "integrat":
        notes.append("mesajul commit-ului nu pomenește %s" % ref)
    if outside:
        problems.append("commit-ul atinge fișiere din afara PUZ-ului: %s" % ", ".join(outside))
    if "Co-Authored-By:" not in msg:
        notes.append("mesajul commit-ului n-are linia Co-Authored-By")
    # Only a person confirms a position no check point tests; an agent's commit must not.
    recipe_diff = git("show", "--format=", commit, "--", os.path.relpath(r["_path"], ROOT).replace("\\", "/"))
    if re.search(r'^\+\s*"verificare_umana"', recipe_diff, re.M):
        problems.append("commit-ul adaugă `verificare_umana`: o confirmare pe care doar un om o poate da")
    dirty = [l for l in git("status", "--porcelain").splitlines() if l.strip()]
    if dirty:
        problems.append("modificări necomise: %s" % ", ".join(l[3:] for l in dirty[:8]))

    # Owners' names. A word of an owner's name can also be a street's or the project's
    # (Ansamblu „Noroc” is built by Noroc Com), so a hit is shown in context, to judge.
    text = decision_text(r)
    raw = (json.dumps({k: v for k, v in r.items() if not k.startswith("_")}, ensure_ascii=False) + "\n"
           # Not "bounds": numbers under the keys north/south/east/west, which an
           # owner's name can contain (North Area Development).
           + json.dumps({k: v for k, v in (entry or {}).items() if k != "bounds"}, ensure_ascii=False)
           + "\n" + msg)
    published_text = normalize_ro(re.sub(r"\S+@\S+|https?://\S+", " ", raw))
    to_check = []
    if text is None:
        notes.append("textul hotărârii nu e disponibil: numele beneficiarilor nu au putut fi verificate")
    else:
        words, unread = beneficiary_words(text)
        checks.append("nume de beneficiari căutate: %d cuvinte" % len(words))
        if unread and not words:
            m = re.search(BENEFICIARY_WORD + r"\s*:\s*(.{0,80})", text, re.I | re.S)
            to_check.append("numele beneficiarilor n-au putut fi citite din textul hotărârii (…%s…): "
                            "caută-le de mână în rețetă, în puz.json și în mesajul commit-ului"
                            % re.sub(r"\s+", " ", m.group(1) if m else "").strip())
        for w in sorted(words):
            for m in list(re.finditer(r"\b%s\b" % re.escape(w), published_text))[:2]:
                to_check.append("„%s”: …%s…" % (w, published_text[max(0, m.start() - 50):m.end() + 50].replace("\n", " ")))
    if re.search(r"beneficiar\w*\s*:\s*(?:S\.?C\.?\s+)?[A-ZĂÂÎȘŞȚŢ]", raw):
        problems.append("rețeta, puz.json sau commit-ul conține „beneficiar(i): <Nume>”")

    for c in checks:
        print("     ", c)
    for n in notes:
        print("NOTĂ ", n)
    for c in to_check:
        print("VERIFICĂ", c)
    for p in problems:
        print("PROBLEMĂ", p)
    verdict = "PROBLEME" if problems else "DE VERIFICAT" if to_check else "OK"
    print("AUDIT %s: %s" % (pid, verdict))
    sys.exit(1 if problems else 2 if to_check else 0)


def cmd_sync_docs(args):
    """Download the documents of every recipe that are missing here (after cloud runs,
    which do not keep them), and check them against SHA256SUMS. The manifest itself is
    not changed. A transcription written into hotarare.txt in a cloud session is not
    recoverable; the page text is saved in its place."""
    manifest = os.path.join(ROOT, "puzuri", args.folder, "documente", "SHA256SUMS")
    sums = {}
    if os.path.exists(manifest):
        with open(manifest, encoding="utf-8") as f:
            for line in f:
                digest, _, name = line.rstrip("\n").partition("  ")
                sums[name] = digest
    bad = 0
    for p in recipe_paths(args.folder):
        r = load(p)
        before = set(os.listdir(docs_dir(r)))
        try:
            paths = download_documents(r, verbose=False)
            if not os.path.exists(text_path(r)):
                save_decision_text(r)
            paths.append(text_path(r))
        except Exception as e:
            print("%-10s EROARE: %s" % (r["id"], e)); bad += 1
            continue
        new = [os.path.basename(x) for x in paths if os.path.basename(x) not in before]
        issues = []
        for x in paths:
            name = r["id"] + "/" + os.path.basename(x)
            if name not in sums:
                issues.append("%s nu e în SHA256SUMS" % os.path.basename(x))
            elif sha256(x) != sums[name]:
                issues.append("hotarare.txt diferă de cel înregistrat (transcriere făcută în altă sesiune?)"
                              if name.endswith("/hotarare.txt") else
                              "%s NU corespunde sumei înregistrate" % os.path.basename(x))
        bad += bool(issues)
        print("%-10s %s%s" % (r["id"], ("descărcat: " + ", ".join(new)) if new else "complet",
                              "".join("\n           - " + i for i in issues)))
    print("gata; %s" % ("toate în regulă" if not bad else "%d cu observații" % bad))


def cmd_doctor(args):
    """Is this machine ready for the pipeline: packages, poppler, network, git."""
    import importlib
    import shutil
    ok = True

    def line(good, text, fatal=True):
        nonlocal ok
        ok = ok and (good or not fatal)
        print("%-5s %s" % ("OK" if good else ("FAIL" if fatal else "WARN"), text))
    print("python", sys.version.split()[0], sys.executable)
    for mod in ("numpy", "PIL", "rasterio", "shapely", "pyproj"):
        try:
            m = importlib.import_module(mod)
            line(True, "%s %s" % (mod, getattr(m, "__version__", "")))
        except Exception as e:
            line(False, "%s: %s" % (mod, e))
    for tool in ("pdfinfo", "pdfimages", "pdftoppm"):
        where = shutil.which(tool)
        line(bool(where), "%s %s" % (tool, where or "lipsește (poppler-utils)"))
    # OpenStreetMap comes from the extract; the public servers are only a fallback.
    try:
        x = osm_extract()
        if x:
            import datetime
            age = (datetime.datetime.now(datetime.timezone.utc)
                   - datetime.datetime.fromisoformat(x["data_osm"].replace("Z", "+00:00"))).days
            line(age <= OSM_EXTRACT_MAX_AGE_DAYS, "extras OSM: %d clădiri, %d străzi, date din %s%s"
                 % (len(x["buildings"]), len(x["streets"]), x["data_osm"][:10],
                    "" if age <= OSM_EXTRACT_MAX_AGE_DAYS else " - vechi de %d zile: osm-extract pe laptop" % age), False)
        else:
            line(False, "extras OSM lipsește (%s): metoda OSM depinde de Overpass" % os.path.relpath(OSM_EXTRACT, ROOT), False)
    except Exception as e:
        line(False, "extras OSM ilizibil: %s" % e, False)
    for name, url, method, fatal in (
            ("primăria, pagini", "https://primariaclujnapoca.ro/consiliu-local/hotarare-de-consiliu/hotararea-594-din-2026/", "GET", True),
            ("primăria, PDF-uri", "https://files.primariaclujnapoca.ro/2026/09/18/HCL-594.pdf", "HEAD", True),
            ("Esri World Imagery", "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer?f=json", "GET", True),
            ("Overpass, rezervă (OSM)", "https://overpass-api.de/api/status", "GET", False),
            ("Overpass, rezervă 2 (OSM)", "https://maps.mail.ru/osm/tools/overpass/api/status", "GET", False),
            ("Nominatim (OSM)", "https://nominatim.openstreetmap.org/status", "GET", False)):
        host = urllib.parse.urlparse(url).netloc
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA, method=method), timeout=30) as resp:
                line(resp.status == 200, "%s (%s): HTTP %d" % (name, host, resp.status), fatal)
        except urllib.error.HTTPError as e:
            if e.code >= 500:   # the server answered: reachable, just busy right now
                line(False, "%s (%s): HTTP %d - serverul răspunde, dar e ocupat acum" % (name, host, e.code), False)
            else:
                line(False, "%s (%s): HTTP %d - în cloud, verifică lista de domenii permise a mediului"
                     % (name, host, e.code), fatal)
        except Exception as e:
            if "timed out" in str(e):
                line(False, "%s (%s): nu răspunde în 30 s - ocupat acum, sau blocat" % (name, host), fatal)
            else:
                line(False, "%s (%s): %s - în cloud, adaugă domeniul în lista de domenii permise a mediului"
                     % (name, host, e), fatal)
    branch = git("branch", "--show-current").strip()
    line(branch == "puz-cluj", "branch %s" % (branch or "?"), fatal=False)
    dirty = [l for l in git("status", "--porcelain").splitlines() if l.strip()]
    line(not dirty, "arbore curat" if not dirty else "modificări necomise: %d fișiere" % len(dirty), fatal=False)
    print("cloud session" if os.environ.get("CLAUDE_CODE_REMOTE") == "true" else "local machine")
    sys.exit(0 if ok else 1)


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
    s = sub.add_parser("next", help="the next decisions for a batch, newest first, and progress")
    s.add_argument("--count", type=int, default=6); s.add_argument("--folder", default="cluj-napoca")
    s.add_argument("--from-year", type=int, default=2020); s.add_argument("--to-year", type=int, default=2026)
    s.add_argument("--retry-stopped", action="store_true", help="also list recipes marked oprit")
    s = sub.add_parser("audit", help="check an agent's commit for one PUZ before pushing it")
    s.add_argument("recipe"); s.add_argument("--commit", default="HEAD")
    s = sub.add_parser("sync-docs", help="download the documents missing here and check them against SHA256SUMS")
    s.add_argument("--folder", default="cluj-napoca")
    sub.add_parser("doctor", help="is this machine ready: packages, poppler, network, git")
    s = sub.add_parser("geocode", help="rough Stereo70 position from OpenStreetMap")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--streets", nargs=2, metavar="REGEX", help='two street names meeting on the plate, e.g. "Buftea" "Scor.arilor"')
    g.add_argument("--address", help="an address, e.g. \"Strada Buftea 2, Cluj-Napoca\"")
    s.add_argument("--live", action="store_true", help=LIVE_HELP)
    s = sub.add_parser("osm", help="draw OpenStreetMap streets and buildings over the plate")
    s.add_argument("recipe")
    for a in ("x0", "y0", "x1", "y1"):
        s.add_argument(a, type=int, nargs="?", default=None)
    s.add_argument("--scale", type=float, default=None); s.add_argument("--step", type=int, default=100)
    s.add_argument("--live", action="store_true", help=LIVE_HELP)
    s = sub.add_parser("osm-snap", help="control point at the OSM corner/crossing nearest a picked plate pixel")
    s.add_argument("recipe"); s.add_argument("name"); s.add_argument("x", type=int); s.add_argument("y", type=int)
    s.add_argument("--max", type=float, default=6.0, help="metres to search around the predicted position")
    s.add_argument("--kind", choices=("any", "building", "street"), default="any")
    s.add_argument("--pick", type=int, default=None); s.add_argument("--check", action="store_true")
    s.add_argument("--write", action="store_true"); s.add_argument("--live", action="store_true", help=LIVE_HELP)
    s = sub.add_parser("osm-extract", help="refresh the OSM extract from Geofabrik (laptop; needs pyosmium)")
    s.add_argument("--pbf", help="an already downloaded romania-latest.osm.pbf")
    s = sub.add_parser("retire-expired", help="take expired PUZ-uri off the map (lists only, unless --write)")
    s.add_argument("--folder", default="cluj-napoca"); s.add_argument("--write", action="store_true")
    s = sub.add_parser("merge-index", help="git merge driver for puz.json (set up by the batch skill)")
    s.add_argument("base"); s.add_argument("ours"); s.add_argument("theirs")
    s = sub.add_parser("caroiaj", help="label the crosses of an unlabelled Stereo70 grid")
    s.add_argument("recipe"); s.add_argument("--write", action="store_true", help="store the labelled crosses as repere/gcp_px")
    args = ap.parse_args()
    if args.cmd == "new":
        return cmd_new(args)
    if args.cmd in ("geocode", "next", "sync-docs", "doctor", "osm-extract", "merge-index", "retire-expired"):
        return {"geocode": cmd_geocode, "next": cmd_next, "sync-docs": cmd_sync_docs, "doctor": cmd_doctor,
                "osm-extract": cmd_osm_extract, "merge-index": cmd_merge_index,
                "retire-expired": cmd_retire_expired}[args.cmd](args)
    r = load(args.recipe)
    {"fetch": cmd_fetch, "render": cmd_render, "grid": cmd_grid, "predict": cmd_predict,
     "vertices": cmd_vertices, "overlay": cmd_overlay, "hcl": cmd_hcl, "related": cmd_related,
     "caroiaj": cmd_caroiaj, "osm": cmd_osm, "osm-snap": cmd_osm_snap, "build": cmd_build,
     "legend": cmd_legend, "audit": cmd_audit}[args.cmd](r, args)


if __name__ == "__main__":
    main()
