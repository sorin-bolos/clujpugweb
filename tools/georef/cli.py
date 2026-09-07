"""Georeference PUG plates and publish them as Map Warper overlays.

Usage
-----
Inspect a plate - finds the frame and measures the kilometre grid, so you can
see what the image gives up before reading anything off it:

    python tools/georef/cli.py inspect puguri/Apahida/*.tif

Georeference from the coordinates printed at the plate's corners, without
uploading anything. One legible corner is enough; more is better:

    python tools/georef/cli.py solve puguri/Apahida/PUG-PATA.tif \
        --north "46 45 00" --east "23 46 52,5"

Do a whole locality from a plates file, and publish:

    python tools/georef/cli.py publish tools/georef/plates/apahida.json

The plates file lists one entry per plate with whatever corner coordinates could
be read off it:

    {
      "locality": "apahida",
      "plates": [
        {"file": "puguri/Apahida/PUG-PATA.tif", "title": "PUG Apahida - Pata",
         "north": "46 45 00", "east": "23 46 52,5", "west": "23 43 07,5"}
      ]
    }

Publishing needs MAPWARPER_EMAIL and MAPWARPER_PASSWORD in the environment.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Coordinates print with a degree sign, which the Windows console codepage does
# not carry by default.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image

import georef
import mask as mask_mod
import plate as plate_mod

Image.MAX_IMAGE_PIXELS = None
from mapwarper import MapWarper, MapWarperError

EDGE_KEYS = ("west", "east", "north", "south")


def _analyse(path):
    return plate_mod.analyse(path)


def _describe_grid(analysis):
    grid = analysis["grid"]
    parts = []
    for axis in ("x", "y"):
        res = grid[f"res_{axis}_m_px"]
        conf = grid[f"confidence_{axis}"]
        parts.append(f"{axis}={res:.4f} m/px (conf {conf:.2f})" if res
                     else f"{axis}=unmeasured")
    return ", ".join(parts)


def cmd_inspect(args):
    for path in args.plates:
        try:
            analysis = _analyse(path)
        except plate_mod.PlateError as exc:
            print(f"{os.path.basename(path)}\n   FAILED: {exc}\n")
            continue
        left, right, top, bottom = analysis["frame"]
        w, h = analysis["size"]
        print(f"{os.path.basename(path)}")
        print(f"   image  {w} x {h}")
        print(f"   frame  left={left} right={right} top={top} bottom={bottom} "
              f"({right-left} x {bottom-top} px)")
        print(f"   grid   {_describe_grid(analysis)}")
        if analysis["grid"]["res_y_m_px"]:
            res = analysis["grid"]["res_y_m_px"]
            print(f"   scan   about {5000 * 0.0254 / res:.0f} dpi at 1:5000")
        print()


def cmd_corners(args):
    """Write enlarged crops of the four frame corners, to read coordinates off.

    The printed coordinates sit just outside the frame, and which corners
    survive varies by plate - the title block covers the bottom right on most of
    them, and some scans lost a margin altogether.
    """
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    os.makedirs(args.out_dir, exist_ok=True)
    pad, scale = args.pad, args.scale

    for path in args.plates:
        try:
            analysis = _analyse(path)
        except plate_mod.PlateError as exc:
            print(f"{os.path.basename(path)}: {exc}")
            continue
        left, right, top, bottom = analysis["frame"]
        image = plate_mod.open_plate(path)[0].convert("RGB")
        w, h = image.size
        stem = os.path.splitext(os.path.basename(path))[0]
        for name, (cx, cy) in {
            "nw": (left, top), "ne": (right, top),
            "sw": (left, bottom), "se": (right, bottom),
        }.items():
            box = (max(0, cx - pad), max(0, cy - pad),
                   min(w, cx + pad), min(h, cy + pad))
            crop = image.crop(box)
            crop = crop.resize((crop.width * scale, crop.height * scale), Image.LANCZOS)
            out = os.path.join(args.out_dir, f"{stem}_{name}.png")
            crop.save(out)
            print(out)


def _rescale_gcps(gcps, measured_size, upload_path, notes):
    """Move control points onto a downsampled copy of the plate.

    The plates run to 95 MB, which the API's base64 upload does not take kindly
    to. Measuring on the original and uploading a smaller copy keeps the
    precision where it matters, as long as the pixel coordinates come along.
    """
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    with Image.open(upload_path) as img:
        up_w, up_h = img.size
    mw, mh = measured_size
    sx, sy = up_w / mw, up_h / mh
    if abs(sx - sy) > 0.01 * max(sx, sy):
        raise georef.GeorefError(
            f"{os.path.basename(upload_path)} is {up_w}x{up_h}, not a uniform "
            f"scaling of the {mw}x{mh} original - re-export it keeping the aspect ratio"
        )
    notes.append(
        f"control points rescaled by {sx:.4f} onto {os.path.basename(upload_path)} "
        f"({up_w}x{up_h})"
    )
    return [dict(p, x=round(p["x"] * sx, 2), y=round(p["y"] * sy, 2)) for p in gcps]


def _anchor_from_args(args):
    """A Stereo 70 grid anchor from the command line, if one was given."""
    parts = {k: getattr(args, k, None)
             for k in ("easting", "at_x", "northing", "at_y")}
    if all(v is None for v in parts.values()):
        return None
    return parts


def _solve(path, edges, gcp_grid, upload_path=None, anchor=None):
    analysis = _analyse(path)
    if anchor:
        frame, notes = georef.build_grid_frame(analysis, anchor)
    else:
        frame, notes = georef.build_frame(analysis, edges)
    nx, ny = gcp_grid
    gcps = frame.gcps(nx, ny)
    if upload_path and os.path.abspath(upload_path) != os.path.abspath(path):
        gcps = _rescale_gcps(gcps, analysis["size"], upload_path, notes)
    return analysis, frame, notes, gcps


def _report(path, analysis, frame, notes, gcps):
    b = frame.bounds()
    print(f"{os.path.basename(path)}")
    print(f"   grid    {_describe_grid(analysis)}")
    if isinstance(frame, georef.GridFrame):
        left, right, top, bottom = frame.pixels
        e0, n0 = frame.to_stereo70(left, bottom)
        e1, n1 = frame.to_stereo70(right, top)
        print(f"   stereo70 E {e0:.0f}..{e1:.0f}  N {n0:.0f}..{n1:.0f}  "
              f"(anchored on the kilometre grid)")
    else:
        dx, dy = frame.datum_shift()
        print(f"   frame   {georef.format_dms(frame.west)} .. {georef.format_dms(frame.east)}  /  "
              f"{georef.format_dms(frame.south)} .. {georef.format_dms(frame.north)}   "
              f"(as printed, {frame.crs})")
        print(f"   datum   shifted {dx:+.0f} m east, {dy:+.0f} m north to WGS84")
        res_x, res_y = frame.resolution()
        print(f"   implied {res_x:.4f} x {res_y:.4f} m/px from those coordinates")
        print(f"   spans   {(frame.east-frame.west)*3600/georef.LON_STEP_SEC:.3f} lon x "
              f"{(frame.north-frame.south)*3600/georef.LAT_STEP_SEC:.3f} lat lattice steps")
    print(f"   wgs84   {georef.format_dms(b['west'])} .. {georef.format_dms(b['east'])}  /  "
          f"{georef.format_dms(b['south'])} .. {georef.format_dms(b['north'])}")
    for note in notes:
        print(f"   note    {note}")
    print(f"   {len(gcps)} control points")


def cmd_solve(args):
    edges = {k: getattr(args, k) for k in EDGE_KEYS}
    try:
        analysis, frame, notes, gcps = _solve(
            args.plate, edges, args.gcp_grid, anchor=_anchor_from_args(args))
    except (georef.GeorefError, plate_mod.PlateError) as exc:
        raise SystemExit(f"{args.plate}: {exc}")
    _report(args.plate, analysis, frame, notes, gcps)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"file": args.plate, "bounds": frame.bounds(), "gcps": gcps},
                      fh, indent=2)
        print(f"   wrote   {args.json}")


PREVIEW_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>%(title)s - georeference preview</title>
<style>
  html, body { margin: 0; height: 100%%; font: 13px system-ui, sans-serif; }
  #map { height: 100%%; }
  #panel {
    position: absolute; top: 10px; right: 10px; z-index: 5;
    background: #fff; padding: 10px 12px; border-radius: 6px;
    box-shadow: 0 1px 6px rgba(0,0,0,.3); min-width: 240px;
  }
  #panel h1 { font-size: 13px; margin: 0 0 6px; }
  #panel dl { margin: 6px 0 0; display: grid; grid-template-columns: auto 1fr;
              gap: 2px 8px; font-size: 12px; }
  #panel dt { color: #666; }
  #panel dd { margin: 0; font-variant-numeric: tabular-nums; }
  input[type=range] { width: 100%%; }
  #error { position: absolute; inset: 0; z-index: 10; display: none;
           background: #fff; padding: 40px; max-width: 40em; line-height: 1.5; }
</style>
</head>
<body>
<div id="map"></div>
<div id="panel">
  <h1>%(title)s</h1>
  <input id="opacity" type="range" min="0" max="100" value="70">
  <dl>
    <dt>north</dt><dd>%(north_dms)s</dd>
    <dt>south</dt><dd>%(south_dms)s</dd>
    <dt>west</dt><dd>%(west_dms)s</dd>
    <dt>east</dt><dd>%(east_dms)s</dd>
  </dl>
</div>
<div id="error">
  <h2>Google Maps refused to load</h2>
  <p>The site's API key is restricted by HTTP referrer, and a page opened
  straight off disk sends none. Serve the folder over localhost instead:</p>
  <pre>python tools/georef/cli.py preview ... --serve</pre>
  <p>and add that localhost origin to the key's allowed referrers in the Google
  Cloud console, or use an unrestricted key with
  <code>--google-key</code>.</p>
</div>
<script>
// Google Maps reports load failures through this global rather than by throwing.
function gm_authFailure() { document.getElementById('error').style.display = 'block'; }

var south = %(south).8f, west = %(west).8f, north = %(north).8f, east = %(east).8f;

function initPreview() {
  var bounds = new google.maps.LatLngBounds(
    new google.maps.LatLng(south, west), new google.maps.LatLng(north, east));
  var map = new google.maps.Map(document.getElementById('map'), {
    scaleControl: true,
    mapTypeId: google.maps.MapTypeId.HYBRID,
    mapTypeControlOptions: { position: google.maps.ControlPosition.LEFT_TOP }
  });
  map.fitBounds(bounds);

  // A GroundOverlay stretches one image across the bounds, which is what a
  // plate is before Map Warper cuts it into tiles.
  var overlay = new google.maps.GroundOverlay('%(image)s', bounds, { opacity: 0.7 });
  overlay.setMap(map);

  new google.maps.Rectangle({
    bounds: bounds, map: map, fillOpacity: 0,
    strokeColor: '#e00', strokeWeight: 1
  });

  document.getElementById('opacity').addEventListener('input', function (e) {
    overlay.setOpacity(e.target.value / 100);
  });
}
</script>
<script async defer
        src="https://maps.googleapis.com/maps/api/js?key=%(google_key)s&callback=initPreview">
</script>
</body>
</html>
"""


def _google_key(explicit=None):
    """Resolve the Maps API key, preferring the one the site already uses.

    Reading it out of Index.html keeps a single source of truth rather than
    pasting a copy into the tool.
    """
    if explicit:
        return explicit
    if os.environ.get("GOOGLE_MAPS_API_KEY"):
        return os.environ["GOOGLE_MAPS_API_KEY"]

    index = os.path.join("ClujPugWeb", "wwwroot", "Index.html")
    if os.path.exists(index):
        with open(index, encoding="utf-8", errors="replace") as fh:
            match = re.search(r"maps\.googleapis\.com/maps/api/js\?key=([\w-]+)", fh.read())
        if match:
            return match.group(1)
    raise SystemExit(
        "could not find a Google Maps key; pass --google-key or set "
        "GOOGLE_MAPS_API_KEY"
    )


def cmd_preview(args):
    """Render the plate over Google Maps, to eyeball the georeferencing.

    Same basemap and the same key as the site, so what you see here is what the
    overlay will look like in place.

    The frame edges are meridians and parallels, and both are straight in Web
    Mercator, so dropping the cropped frame into a lat/lon rectangle is accurate
    here rather than merely indicative - the sheet's own projection bends the
    frame by about 3 m over its full height.

    This is the check worth doing before uploading anything: Map Warper will
    apply whatever control points it is handed, so the question is whether they
    are right, and that is answered against a basemap.
    """
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    edges = {k: getattr(args, k) for k in EDGE_KEYS}
    try:
        analysis, frame, notes, gcps = _solve(
            args.plate, edges, args.gcp_grid, anchor=_anchor_from_args(args))
    except (georef.GeorefError, plate_mod.PlateError) as exc:
        raise SystemExit(f"{args.plate}: {exc}")

    _report(args.plate, analysis, frame, notes, gcps)

    os.makedirs(args.out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.plate))[0]

    # Crop to the frame - the margins and title block are not part of the map,
    # and leaving them in would push the drawing off its coordinates.
    src = plate_mod.open_plate(args.plate)[0]
    crop = src.convert("RGB").crop(frame.pixels_lrtb_box())
    if crop.width > args.max_width:
        scale = args.max_width / crop.width
        crop = crop.resize((args.max_width, round(crop.height * scale)), Image.LANCZOS)
    image_name = f"{stem}.jpg"
    crop.save(os.path.join(args.out_dir, image_name), quality=85)

    b = frame.bounds()
    html = PREVIEW_HTML % {
        "title": stem, "image": image_name,
        "google_key": _google_key(args.google_key),
        "north": b["north"], "south": b["south"],
        "west": b["west"], "east": b["east"],
        "north_dms": georef.format_dms(b["north"]),
        "south_dms": georef.format_dms(b["south"]),
        "west_dms": georef.format_dms(b["west"]),
        "east_dms": georef.format_dms(b["east"]),
    }
    html_path = os.path.join(args.out_dir, f"{stem}.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"   preview {html_path}")
    print(f"   check the roads and the built-up edge line up")

    if args.serve:
        _serve(args.out_dir, f"{stem}.html", args.port)
    else:
        print("   the site's key is referrer-restricted, so opening this straight "
              "off disk may be refused; re-run with --serve if so")


def _serve(directory, page, port):
    """Serve the preview over localhost.

    A page opened from the filesystem sends no referrer, which a referrer-
    restricted Maps key rejects. Serving it gives the request an origin the key
    can be allowed to accept.
    """
    import functools
    import http.server
    import webbrowser

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=directory)
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        url = f"http://localhost:{port}/{page}"
        print(f"\n   serving {url}  (ctrl-c to stop)")
        print("   if Maps refuses the key, add this origin to its allowed "
              "referrers in the Google Cloud console")
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n   stopped")


def cmd_extract(args):
    """Pull the embedded images out of PDFs.

    Council PDFs come in two shapes. Some are scanned documents - one full-page
    raster per page, so the "images" are just the pages. Others carry real
    figures, and a plan sheet arrives as a single big raster on one page, which
    is what the rest of this tool wants.

    Images are deduplicated by xref: the same logo repeated on every page is one
    file, not eighty.
    """
    import fitz

    for path in args.pdfs:
        stem = os.path.splitext(os.path.basename(path))[0]
        out_dir = os.path.join(args.out_dir, stem)
        doc = fitz.open(path)
        try:
            first_page = {}
            for number, page in enumerate(doc, start=1):
                for info in page.get_images(full=True):
                    first_page.setdefault(info[0], number)

            written, skipped = 0, 0
            for xref, page_no in sorted(first_page.items(), key=lambda kv: kv[1]):
                raw = doc.extract_image(xref)
                width, height = raw["width"], raw["height"]
                if width * height < args.min_pixels:
                    skipped += 1
                    continue
                if not written:
                    os.makedirs(out_dir, exist_ok=True)
                name = f"p{page_no:03d}_x{xref}_{width}x{height}.{raw['ext']}"
                with open(os.path.join(out_dir, name), "wb") as fh:
                    fh.write(raw["image"])
                written += 1
            note = f", {skipped} below {args.min_pixels} px skipped" if skipped else ""
            print(f"{os.path.basename(path)}: {written} images{note}"
                  + (f" -> {out_dir}" if written else ""))
        finally:
            doc.close()


def cmd_export(args):
    """Write a web-sized copy of a plate, for uploading.

    The originals run to 95 MB, and a PDF is not something to hand the API at
    all. Control points are computed on the original and rescaled onto whatever
    is uploaded, so the copy only has to be a uniform scaling of the whole
    plate - not cropped.
    """
    os.makedirs(args.out_dir, exist_ok=True)
    for path in args.plates:
        image = plate_mod.open_plate(path)[0].convert("RGB")
        scale = min(1.0, args.max_dim / max(image.size))
        if scale < 1.0:
            image = image.resize(
                (round(image.width * scale), round(image.height * scale)),
                Image.LANCZOS)
        stem = os.path.splitext(os.path.basename(path))[0]
        out = os.path.join(args.out_dir, f"{stem}.jpg")
        image.save(out, quality=args.quality, optimize=True)
        print(f"{out}  {image.width}x{image.height}  "
              f"{os.path.getsize(out)/1e6:.1f} MB")


def cmd_mask(args):
    """Mask a plate to its proposed built-up area and re-warp.

    Overlaid on a slippy map, a whole plate covers real geography with its
    title block, legend and balance-sheet table, plus a lot of countryside that
    the plan says nothing about. Masking leaves the zoned area.
    """
    import numpy as np

    spec = _load_plates_file(args.plates_file)
    warper = None
    if not args.dry_run:
        warper = MapWarper()
        try:
            warper.sign_in()
        except MapWarperError as exc:
            raise SystemExit(str(exc))

    for entry in spec["plates"]:
        path = entry["file"]
        title = entry.get("title") or os.path.basename(path)
        cfg = entry.get("mask")
        if not cfg:
            print(f"{title}: no \"mask\" settings, skipped")
            continue
        map_id = entry.get("map_id")
        if not map_id and not args.dry_run:
            print(f"{title}: no map_id, skipped")
            continue

        image = plate_mod.open_plate(path)[0].convert("RGB")
        rgb = np.asarray(image)
        try:
            regs = mask_mod.regions(
                rgb,
                open_px=cfg.get("open_px", 8),
                close_px=cfg.get("close_px", 70),
                min_area_px=cfg.get("min_area_px", 20000),
                exclude=[tuple(b) for b in cfg.get("exclude", [])],
            )
        except mask_mod.MaskError as exc:
            print(f"{title}: {exc}")
            continue

        # The mask is in the uploaded image's pixels, which may be a scaled copy.
        scale = cfg.get("scale", 1.0)
        rings, covered = [], 0
        for region in regs:
            ring, tol = mask_mod.simplify(mask_mod.trace(region), cfg.get("tolerance", 6.0))
            rings.append([(x * scale, y * scale) for x, y in ring])
            covered += int(region.sum())
        height = int(round(rgb.shape[0] * scale))
        gml = mask_mod.to_gml(rings, height, flip_y=not args.no_flip)

        pct = 100.0 * covered / (rgb.shape[0] * rgb.shape[1])
        print(f"{title}: {len(rings)} area(s), {pct:.1f}% of the sheet, "
              f"{sum(len(r) for r in rings)} points, {len(gml)/1024:.0f} KB of GML")
        if args.dry_run:
            continue
        try:
            warper.mask_crop_rectify(map_id, gml)
            state = warper.wait_until_warped(map_id)
            bounds = warper.bbox(map_id)
        except MapWarperError as exc:
            print(f"{title}: {exc}")
            continue
        print(f"   {state}; new bounds "
              f"{{ west: {bounds['west']:.7f}, south: {bounds['south']:.7f}, "
              f"east: {bounds['east']:.7f}, north: {bounds['north']:.7f} }}")


def _load_plates_file(path):
    with open(path, encoding="utf-8") as fh:
        spec = json.load(fh)
    if "plates" not in spec:
        raise SystemExit(f"{path}: no 'plates' list")
    return spec


def _js_snippet(locality, layers):
    """Render the entry to paste into the localities array in Scripts.js."""
    lines = [f"    {{", f"        id: '{locality}',", "        layers: ["]
    for i, layer in enumerate(layers):
        b = layer["bounds"]
        tail = "" if i == len(layers) - 1 else ","
        lines += [
            "            {",
            f"                // {layer['title']}",
            f"                tileUrl: '{layer['tileUrl']}',",
            f"                bounds: {{ west: {b['west']:.7f}, south: {b['south']:.7f}, "
            f"east: {b['east']:.7f}, north: {b['north']:.7f} }}",
            f"            }}{tail}",
        ]
    lines += ["        ]", "    }"]
    return "\n".join(lines)


def cmd_publish(args):
    spec = _load_plates_file(args.plates_file)
    locality = spec.get("locality", "unnamed")

    prepared, blocked = [], []
    for entry in spec["plates"]:
        path = entry["file"]
        if not os.path.exists(path):
            blocked.append((path, "file not found"))
            continue
        edges = {k: entry.get(k) for k in EDGE_KEYS}
        upload = entry.get("upload_file")
        if upload and not os.path.exists(upload):
            blocked.append((path, f"upload_file {upload} not found"))
            continue
        try:
            analysis, frame, notes, gcps = _solve(
                path, edges, args.gcp_grid, upload, entry.get("grid_anchor"))
        except (georef.GeorefError, plate_mod.PlateError) as exc:
            # Report every plate that needs attention, rather than stopping at
            # the first - reading corners is a batch job.
            blocked.append((path, str(exc)))
            continue
        _report(path, analysis, frame, notes, gcps)
        print()
        prepared.append((entry, frame, gcps))

    if blocked:
        print("these plates still need coordinates read off them:")
        for path, reason in blocked:
            print(f"   {os.path.basename(path)}: {reason}")
        print("   run:  python tools/georef/cli.py corners <plate>\n")

    if args.dry_run:
        print(f"dry run - {len(prepared)} plate(s) ready, nothing uploaded")
        return
    if blocked and not args.skip_blocked:
        raise SystemExit(
            "refusing to publish a partial locality; fix the plates above or "
            "pass --skip-blocked"
        )
    if not prepared:
        raise SystemExit("nothing to publish")

    warper = MapWarper()
    try:
        warper.sign_in()
    except MapWarperError as exc:
        raise SystemExit(str(exc))

    layers = []
    for entry, frame, gcps in prepared:
        path = entry["file"]
        title = entry.get("title") or os.path.splitext(os.path.basename(path))[0]
        try:
            map_id = entry.get("map_id")
            if map_id:
                removed = warper.clear_gcps(map_id)
                print(f"{title}: reusing map {map_id} ({removed} old control points cleared)")
            else:
                upload_url = entry.get("upload_url")
                if not upload_url:
                    raise MapWarperError(
                        "no upload_url. Map Warper's base64 upload returns 500, so "
                        "the image has to be somewhere the server can fetch it - "
                        "put the file from `export` on the site and give its URL, "
                        "or upload it through mapwarper.net and set \"map_id\" instead"
                    )
                print(f"{title}: creating from {upload_url} ...")
                map_id = warper.create_map(
                    upload_url, title,
                    description=entry.get("description"),
                    source_uri=entry.get("source_uri"),
                    scale=entry.get("scale", "1:5000"),
                    issue_year=entry.get("issue_year"),
                    tag_list=entry.get("tag_list", f"pug, {locality}"),
                )
                print(f"{title}: map {map_id}")

            warper.add_gcps(map_id, gcps)
            warper.rectify(map_id)
            warper.wait_until_warped(map_id)
            bounds = warper.bbox(map_id)
        except MapWarperError as exc:
            # Uploads are slow and large, so hand back what already went up -
            # putting these map_ids in the plates file makes a retry re-fit
            # rather than upload a second copy.
            if map_id:
                print(f"{title}: uploaded as map {map_id}, but then failed")
            if layers:
                print("already published, add these as \"map_id\" before retrying:")
                for done in layers:
                    print(f"   {done['title']}: {done['map_id']}")
            raise SystemExit(f"{title}: {exc}")

        # The warped extent should land near the coordinates we computed. It
        # will not land on them exactly: the sheet sits a little askew to the
        # graticule, so its bounding box is legitimately wider than the frame.
        # A gross disagreement means the control points were wrong.
        drift = max(abs(bounds[k] - frame.bounds()[k]) for k in EDGE_KEYS)
        flag = "  <-- CHECK, far from the computed frame" if drift > 0.005 else ""
        print(f"{title}: warped, bbox differs from frame by {drift * 3600:.1f} arcsec{flag}")

        layers.append({"title": title, "map_id": map_id,
                       "tileUrl": warper.tile_url(map_id), "bounds": bounds})

    print("\nPaste into the localities array in ClujPugWeb/wwwroot/Scripts.js:\n")
    print(_js_snippet(locality, layers))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"locality": locality, "layers": layers}, fh, indent=2)
        print(f"\nwrote {args.json}")


def _grid_arg(text):
    try:
        nx, ny = (int(v) for v in text.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError("expected something like 4x4")
    return nx, ny


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="georef", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gcp-grid", type=_grid_arg, default=(4, 4),
                        help="control point grid over the plate (default 4x4)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="report the frame and grid found in a plate")
    p.add_argument("plates", nargs="+")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("corners", help="crop the frame corners so you can read them")
    p.add_argument("plates", nargs="+")
    p.add_argument("--out-dir", default="corners")
    p.add_argument("--pad", type=int, default=420,
                   help="pixels either side of each corner (default 420)")
    p.add_argument("--scale", type=int, default=2, help="enlargement (default 2)")
    p.set_defaults(func=cmd_corners)

    p = sub.add_parser("solve", help="georeference one plate without uploading")
    p.add_argument("plate")
    for key in EDGE_KEYS:
        p.add_argument(f"--{key}", help=f"coordinate printed on the {key} edge")
    p.add_argument("--easting", type=float,
                   help="Stereo 70 easting printed beside a tick, in metres")
    p.add_argument("--at-x", type=float, dest="at_x",
                   help="roughly where along the top margin that tick sits, in pixels")
    p.add_argument("--northing", type=float,
                   help="Stereo 70 northing printed beside a tick, in metres")
    p.add_argument("--at-y", type=float, dest="at_y",
                   help="roughly where down the side margin that tick sits, in pixels")
    p.add_argument("--json", help="write bounds and control points here")
    p.set_defaults(func=cmd_solve)

    p = sub.add_parser("preview", help="render a plate over OSM to check the fit")
    p.add_argument("plate")
    for key in EDGE_KEYS:
        p.add_argument(f"--{key}", help=f"coordinate printed on the {key} edge")
    p.add_argument("--easting", type=float,
                   help="Stereo 70 easting printed beside a tick, in metres")
    p.add_argument("--at-x", type=float, dest="at_x",
                   help="roughly where along the top margin that tick sits, in pixels")
    p.add_argument("--northing", type=float,
                   help="Stereo 70 northing printed beside a tick, in metres")
    p.add_argument("--at-y", type=float, dest="at_y",
                   help="roughly where down the side margin that tick sits, in pixels")
    p.add_argument("--out-dir", default="preview")
    p.add_argument("--max-width", type=int, default=2600,
                   help="downsample the overlay to this width (default 2600)")
    p.add_argument("--google-key",
                   help="Maps API key (default: the one in Index.html)")
    p.add_argument("--serve", action="store_true",
                   help="serve the preview over localhost and open it")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("extract", help="pull embedded images out of PDFs")
    p.add_argument("pdfs", nargs="+")
    p.add_argument("--out-dir", default="export/pdf-images")
    p.add_argument("--min-pixels", type=int, default=160000,
                   help="skip images smaller than this many pixels (default 400x400)")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("mask", help="crop plates to the proposed built-up area")
    p.add_argument("plates_file")
    p.add_argument("--dry-run", action="store_true", help="trace but do not upload")
    p.add_argument("--no-flip", action="store_true",
                   help="send mask y as image rows rather than flipped")
    p.set_defaults(func=cmd_mask)

    p = sub.add_parser("export", help="write a web-sized copy of a plate for upload")
    p.add_argument("plates", nargs="+")
    p.add_argument("--out-dir", default="export")
    p.add_argument("--max-dim", type=int, default=8000,
                   help="longest side of the exported copy (default 8000)")
    p.add_argument("--quality", type=int, default=88)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("publish", help="georeference and upload a locality's plates")
    p.add_argument("plates_file")
    p.add_argument("--dry-run", action="store_true",
                   help="solve and report, but do not upload")
    p.add_argument("--skip-blocked", action="store_true",
                   help="publish the plates that solved, leaving the rest")
    p.add_argument("--json", help="write the resulting layers here")
    p.set_defaults(func=cmd_publish)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
