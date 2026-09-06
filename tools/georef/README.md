# Georeferencing PUG plates

Fitting a plate by hand in Map Warper means clicking control points against a
basemap until the overlay looks right. It does not need to. The plates print the
numbers the fit is looking for.

Map Warper stays the tile host and nothing about how the site serves overlays
changes - `Scripts.js` still points at `mapwarper.net` tile URLs. What goes away
is the clicking.

## What the plates carry

The Apahida sheets are Romanian 1:5000 plans from 2004, and they carry:

- **A geographic coordinate at each frame corner**, in degrees, minutes and
  seconds - Dezmir's south-west corner reads `23°41'15,0"` / `46°45'00"`.
- **A Stereo 70 (EPSG:3844) kilometre grid**, ticked in the margin every 500 m.
  Pata's margin labels `406,5` and `84,0` convert to exactly the easting and
  northing its printed corner implies, which is what confirmed the reading.
- **The sheet lattice.** Corners fall on multiples of 1'52,5" of longitude and
  1'15" of latitude, the 1:5000 subdivision of the `L-34` map series. Dezmir's
  bottom edge and Pata's top edge sit on the same parallel: they are adjacent
  sheets.

Two things follow. The frames are **graticule trapezoids** - each edge is a
meridian or a parallel - so interior points come from interpolating in lat/lon,
which also sidesteps the ~0.9° tilt between the sheet and the Stereo 70 grid.
And the scans are **not the 200 dpi their TIFF tags claim**; measured off the
grid they come out near 197, and that 1.5% is 70 m across a 5 km sheet.

## The datum, which is the easy thing to get wrong

The coordinates printed on the plates are on **Pulkovo 1942(58)** (`EPSG:4179`),
the datum under Stereo 70. Google Maps and Map Warper want WGS84. Around Cluj
the two differ by **121 m east and 32 m north**.

Read a corner off the sheet, hand it to Google Maps as if it were WGS84, and the
overlay lands 125 m to the north-east - which looks like a fitting problem and is
not one. It is 190 pixels at the scan's own resolution, and it is by far the
largest error in the chain.

`Frame` therefore holds edge coordinates in the plate's datum, because that is
what the sheet is drawn and labelled in, and converts on the way out.
Interpolation happens before the shift, in the graticule the frame edges
actually follow. Every run prints the shift it applied.

pyproj's Helmert transformation is used, which leaves a few metres of residual.
ANCPI's grid-based TransDatRO would be tighter, but the remainder is already
well under the drawing accuracy of a 2004 blueprint.

## What is automatic and what is not

Automatic:

- the frame, from a projection profile - the neatline is the longest dark run in
  each margin;
- the ground resolution, measured off the tick period rather than taken from the
  DPI tag;
- any frame edge that was not read, inferred from the opposite one and snapped to
  the sheet lattice;
- control points, upload, rectification, and the `Scripts.js` entry.

Not automatic: **reading the printed corner coordinates.** One legible corner
per plate is enough, and the numbers are large and clear where a margin
survived. OCR was not worth it - these are degraded 2004 blueprints, and a
misread digit moves an overlay hundreds of metres, whereas reading one corner
takes a few seconds and the tool cross-checks it.

Not every plate has a legible corner. Of the six Apahida sheets, the title block
covers the east side of most, and `PUG-APAHIDA.tif` was scanned with its margins
trimmed off entirely, so it carries no coordinates at all.

## Use

Needs `pillow`, `numpy` and `pyproj`.

```sh
# What does the image alone give up?
python tools/georef/cli.py inspect puguri/Apahida/*.tif

# Crop the four corners so you can read the coordinates off them.
python tools/georef/cli.py corners puguri/Apahida/PUG-PATA.tif --out-dir corners

# Georeference one plate, without uploading anything.
python tools/georef/cli.py solve puguri/Apahida/PUG-PATA.tif \
    --north "46 45 00" --east "23 46 52,5"

# Same, but write an HTML page showing the plate over Google Maps - the same
# basemap and the same key as the site. This is the check worth doing before
# uploading: Map Warper applies whatever control points it is handed, so the
# only question is whether they are right.
python tools/georef/cli.py preview puguri/Apahida/PUG-PATA.tif \
    --north "46 45 00" --east "23 46 52,5" --serve

# Do a locality and publish it.
export MAPWARPER_EMAIL=... MAPWARPER_PASSWORD=...
python tools/georef/cli.py publish tools/georef/plates/apahida.json --dry-run
python tools/georef/cli.py publish tools/georef/plates/apahida.json
```

Coordinates parse in whatever form is easiest to type: `46 45 00`,
`46°45'00"`, `23 46 52,5`, `46:45:00`, or plain decimal degrees.

`publish` prints the entry to paste into the `localities` array in
`ClujPugWeb/wwwroot/Scripts.js`.

### The plates file

One entry per plate, with whatever corners could be read:

```json
{
  "locality": "apahida",
  "plates": [
    {
      "file": "puguri/Apahida/PUG-PATA.tif",
      "title": "PUG Apahida - Pata, Bodrog",
      "west": "23 43 07,5",
      "east": "23 46 52,5",
      "north": "46 45 00"
    }
  ]
}
```

Optional per plate: `south`, `description`, `source_uri`, `issue_year`,
`tag_list`, `map_id` to re-fit a map already on Map Warper rather than uploading
again, and `upload_file` to send a downsampled copy while still measuring the
frame and grid on the original.

That last one matters - the plates run to 95 MB, and the API takes uploads as
base64 inside a JSON body, which inflates them by a third. Control points are
rescaled onto the smaller image automatically.

## How far to trust it

Every run reports what it inferred rather than read, and cross-checks the
resolution the corner coordinates imply against the one measured off the
kilometre grid - independent evidence, so a disagreement means a misread digit
and says so.

`preview` is the direct test - it drops the cropped frame onto Google Maps at the
computed bounds as a `GroundOverlay`, with an opacity slider, on satellite
imagery. The frame edges are meridians and parallels, and both are straight in
Web Mercator, so this is accurate rather than merely indicative; the sheet's own
projection bends the frame by about 3 m over its full height.

The key comes from `ClujPugWeb/wwwroot/Index.html`, so there is only one copy of
it. Override with `--google-key` or `GOOGLE_MAPS_API_KEY`.

That key is restricted by HTTP referrer, and a page opened straight off disk
sends none, so Maps will refuse it. `--serve` puts the preview on localhost,
which gives the request an origin - add that origin to the key's allowed
referrers in the Google Cloud console, or pass an unrestricted key.

Run on Pata, the villages land on their labels, Strada George Coșbuc follows the
plate's main street with the building rows along it matching, Strada Vilor sits
on its road, and DC79 lines up on the east side.

Two further checks were run against known values:

- Given **only** Pata's north-east corner, the inferred west edge came out at
  `23°43'07,5"` - exactly the value printed on the corner opposite, which the
  tool never saw.
- Dezmir and Pata are already on the site, fitted by hand. The computed bounds
  agree to within 56 m, and the residual is symmetric: the computed frame sits
  about 50 m inside the site's bbox on all four sides. That is the expected
  difference rather than error - the sheet is rotated about 0.9° by meridian
  convergence, so the bounding box around it is 32 to 37 m larger per side than
  the frame itself.

  Before the datum shift was applied that worst disagreement was 177 m, and it
  was one-sided.

Both plates also independently come out spanning 2.000 lattice steps of
longitude by 1.758 of latitude, and they tile against each other exactly.

## Limits

- A plate with no legible corner and no readable horizontal grid cannot be
  placed from its own evidence. `PUG-APAHIDA.tif` is the case in hand; it needs
  anchoring against its neighbours, which this tool does not yet do.
- The horizontal tick period often fails to measure, because the bottom margin
  carries the sheet nomenclature and neighbouring place names. The vertical
  period reads cleanly on every plate seen so far and stands in for it; the
  scans are anisotropic by about 2%, well inside the lattice snap that follows.
- Interpolating interior points in graticule space ignores the curvature of the
  sheet's own projection. That is sub-metre over 5 km - far below what a scan of
  a 2004 blueprint resolves.
- Latitude spans are not lattice multiples. The meridian edges are on the
  lattice, but sheets are cropped top and bottom to fit the paper, so inferred
  edges are snapped only when they land very close.
