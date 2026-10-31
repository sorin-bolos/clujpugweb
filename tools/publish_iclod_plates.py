"""Put the Iclod plates on Map Warper: control points, rectify, mask.

Reads what render_iclod_plates.py wrote to export/iclod/<Village>.json. Each plate
needs a Map Warper map to land on, given one of two ways:

    --map-id Iclod=112300 ...      maps already uploaded by hand at mapwarper.net
                                   (the uploaded file must be export/iclod/<Village>.png,
                                   unchanged, so the pixel control points still fit)
    --base-url https://...         a public folder holding the <Village>.png files,
                                   which Map Warper fetches itself

Map Warper's base64 upload answers 500 (see tools/georef/README.md), hence the
choice. Credentials come from MAPWARPER_EMAIL and MAPWARPER_PASSWORD.

Prints the entry for the localities array in ClujPugWeb/wwwroot/Scripts.js.

    python tools/publish_iclod_plates.py --map-id Iclod=1 Iclozel=2 Fundatura=3 Livada=4 Orman=5
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "georef"))
from mapwarper import MapWarper, MapWarperError  # noqa: E402
from mask import to_gml  # noqa: E402

SRC = os.path.join("export", "iclod")
VILLAGES = ["Iclod", "Iclozel", "Livada", "Orman", "Fundatura"]
TITLES = {
    "Iclod": "Iclod - plansa 1.2 Reglementari",
    "Iclozel": "Iclod_Iclozel - plansa 2.2 Reglementari",
    "Livada": "Iclod_Livada - plansa 3.2 Reglementari",
    "Orman": "Iclod_Orman - plansa 4.2 Reglementari",
    "Fundatura": "Iclod_Fundatura - plansa 5.2 Reglementari",
}


def publish(warper, village, map_id=None, base_url=None):
    with open(os.path.join(SRC, village + ".json"), encoding="utf-8") as fh:
        info = json.load(fh)
    title = TITLES[village]
    if map_id:
        removed = warper.clear_gcps(map_id)
        print(f"{village}: reusing map {map_id} ({removed} old control points cleared)")
    else:
        url = f"{base_url.rstrip('/')}/{village}.png"
        print(f"{village}: creating from {url} ...")
        map_id = warper.create_map(url, title, scale="1:5000", issue_year=2015,
                                   tag_list="pug, iclod")
        print(f"{village}: map {map_id}")

    warper.add_gcps(map_id, info["gcps"])
    # Not warper.rectify(): on a map that was never warped, /rectify answers with
    # the map unchanged and it stays "available" (seen 2026-10-31).
    # mask_crop_rectify warps from the same control points, and does it before
    # answering.
    warper.mask_crop_rectify(map_id, to_gml(info["mask"], info["height"]))
    warper.wait_until_warped(map_id)
    bounds = warper.bbox(map_id)
    print(f"{village}: warped and masked, {warper.base_url}/maps/{map_id}")
    return {"village": village, "plate": info["plate"], "map_id": map_id,
            "tileUrl": warper.tile_url(map_id), "bounds": bounds}


def snippet(layers):
    lines = ["    {", "        id: 'iclod',", "        layers: ["]
    for i, layer in enumerate(layers):
        b = layer["bounds"]
        lines += [
            "            {",
            f"                // {layer['village']} - plansa {layer['plate']}",
            f"                tileUrl: '{layer['tileUrl']}',",
            f"                bounds: {{ west: {b['west']}, south: {b['south']}, "
            f"east: {b['east']}, north: {b['north']} }}",
            "            }" + ("," if i < len(layers) - 1 else ""),
        ]
    lines += ["        ]", "    }"]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--map-id", nargs="*", default=[], metavar="VILLAGE=ID")
    parser.add_argument("--base-url")
    parser.add_argument("--only", nargs="*", choices=VILLAGES)
    args = parser.parse_args()

    ids = dict(pair.split("=", 1) for pair in args.map_id)
    villages = args.only or VILLAGES
    missing = [v for v in villages if v not in ids and not args.base_url]
    if missing:
        raise SystemExit(f"no map id and no --base-url for: {', '.join(missing)}")

    warper = MapWarper()
    try:
        warper.sign_in()
    except MapWarperError as exc:
        raise SystemExit(str(exc))

    layers = []
    for village in villages:
        try:
            layers.append(publish(warper, village, ids.get(village), args.base_url))
        except MapWarperError as exc:
            done = ", ".join(f"{l['village']}={l['map_id']}" for l in layers)
            raise SystemExit(f"{village}: {exc}\nalready done: {done or 'none'}")

    with open(os.path.join(SRC, "published.json"), "w", encoding="utf-8") as fh:
        json.dump(layers, fh, indent=2)
    print("\nPaste into the localities array in ClujPugWeb/wwwroot/Scripts.js:\n")
    print(snippet(layers))


if __name__ == "__main__":
    main()
