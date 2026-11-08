# PUZ-uri pe hartă

Each approved PUZ (Plan Urbanistic Zonal) gets three things on the site: its
regulations plate warped onto the map, its boundary, and its legend. They are built
from a **recipe** - `puzuri/<localitate>/<an>-<nr>.json` - by `tools/puz/puz.py`.
The recipe holds what someone (or an agent) has to read off the documents. The
script does the rest and checks the reading.

Needs Python 3.13 with `rasterio` (it bundles GDAL 3.12), `shapely`, `pyproj`,
`numpy` and `pillow`, plus `pdfinfo`/`pdfimages`/`pdftoppm` on PATH.

## Why no clicking

Since about 2020, Cluj-Napoca's PUZ plates print an **Inventar de coordonate**: the
boundary vertices, numbered, in Stereo 70, with the same numbers drawn next to the
vertices on the plate. Each one is already a ground control point. All it needs is
the pixel position of a handful of them.

Two checks catch mistakes:

- **Area.** The plate also prints the area (`S=2447mp`). The shoelace area of the
  transcribed coordinates has to match it within 1 %. One misread digit breaks the
  match by far more than that.
- **Residuals.** An affine fit through the picked points has to leave every
  control and check point within 1 m. On the pilot it was 0.21 m RMS, 0.41 m worst.
  At 1:250 scanned at 200 dpi a pixel is 3 cm, so a misplaced point shows up in
  metres.

`build` refuses to publish if either check fails.

## Steps for one PUZ

1. **Recipe skeleton.** Take `id`, `hcl` (nr, an, data_sedinta, pagina, pdf) and
   `titlu` from the council decision listing. Write the title **without the
   beneficiaries' names**.
2. `puz.py fetch` downloads the decision's documents: the recipe's PDF plus any
   other PDF linked from the decision page. It lists pages and images, and writes a
   contact sheet (`puz_cache/<id>/pages.png`). Find the *Reglementări urbanistice* plate.
   PDFs often contain it **twice**, scanned differently. On HCL 597/2026, page 6 is
   unreadable and page 13 is clean. Use the clearest copy as `plansa.pagina_pdf`.
3. `puz.py render` renders that page at its native dpi, plus an overview with a
   pixel grid.
4. **Transcribe the coordinate table** into `coordonate.puncte`, as printed:
   `[Nord (x), Est (Y)]`. Add `suprafata_declarata_m2`. If the vertex numbers do not
   run in boundary order, set `coordonate.ordine`.
5. **Pick points.** Pick two well-separated corners from the overview into
   `gcp_px`. `puz.py predict` then says where every other vertex should be, and
   `puz.py vertices <names…>` shows zoomed, grid-labelled crops around them. Prefer
   sharp corners for `gcp_px` (at least 4, spread out). Put a few more in
   `verificare_px`: they are checked but not used in the fit. Points along a smooth
   curve are poor control points.
6. **Crops.** Set `legenda_px` (one or more `[x0, y0, x1, y1]` boxes, stacked into
   one image) and `decupaj`. The overlay is the boundary plus `buffer_m`, minus any
   `exclude_px` boxes, such as tables or title blocks that the buffer reaches into.
   Use `puz.py grid <x0 y0 x1 y1>` to read box coordinates.
7. **Regulations as text.** Put the UTR code, its name, POT and CUT (and H max if
   given) in `utr`. They show in the info window and in the legend card.
8. `puz.py build` runs both checks, warps with GDAL, writes the legend, and draws
   `puz_cache/<id>/check_imagery.png`: Esri imagery next to the overlay on top of
   it. **Look at it.** The boundary should sit on the real plot, with drawn roads
   and neighbouring houses over the real ones. Expect 1-3 m of disagreement: the
   Stereo 70 → WGS84 transformation PROJ has (EPSG "Pulkovo 1942(58) to WGS 84
   (19)") is good to about 3 m, imagery has its own error, and roofs lean in aerial
   photos. Esri has no zoom 19 here; 18 is the default.
9. **Check on the site:** `http://localhost:5000/?puz=<id>` opens in PUZ mode,
   zoomed to it.
10. **Commit** the recipe, `ClujPugWeb/wwwroot/puz/<id>/` and `puz/puz.json`, as
    `PUZ HCL <nr>/<an> – <location>`. `puz_cache/` stays out of git.

## Where files live

| Folder | What | In git | Served |
|---|---|---|---|
| `puzuri/<localitate>/<id>.json` | the recipe | yes | no |
| `puzuri/<localitate>/documente/<id>/` | backup of the decision's original documents | no | no |
| `puzuri/<localitate>/documente/SHA256SUMS` | their checksums | yes | no |
| `puz_cache/<id>/` | renders, picking aids, imagery checks; rebuildable | no | no |
| `ClujPugWeb/wwwroot/puz/` | what the site shows | yes | yes |

The documents are kept in case the city hall moves or removes them. `fetch` only
downloads what is missing, so a rebuild still works once the links are dead. Check
the backup with `cd puzuri/cluj-napoca/documente && sha256sum -c SHA256SUMS`. Being
ignored by git, the backup exists only on this machine: copy `documente/` somewhere
else too.

## What is published

- `ClujPugWeb/wwwroot/puz/<id>/plansa.webp` - the plate, warped to Web Mercator,
  clipped to the boundary. The site draws it as a `GroundOverlay`, which lines up
  because the image is already in Web Mercator.
- `ClujPugWeb/wwwroot/puz/<id>/legenda.webp` - the legend crop.
- An entry in `ClujPugWeb/wwwroot/puz/puz.json`: decision, title, UTR/POT/CUT,
  bounds, boundary in WGS84, fit quality.

## Known gaps

- Decisions from 2017-2019 are published as text only, with no plates in the PDF.
  Links for 2015-2016 return 404. Those PUZ-uri need another source.
- Legends are not standardised. Each designer draws their own symbols, so every PUZ
  keeps its own legend crop. The UTR codes are the PUG's.
