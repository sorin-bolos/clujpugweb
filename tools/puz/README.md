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

1. **Recipe skeleton.** `puz.py new <an> <nr>` reads the council listing and
   writes `id`, `hcl` (nr, an, data_sedinta, pagina, pdf) and `titlu`. The title is
   cleaned: no "Aprobarea", and **no beneficiaries' names**.
2. `puz.py fetch` downloads the decision's documents: the recipe's PDF plus any
   other PDF linked from the decision page. It lists pages and images, and writes a
   contact sheet (`puz_cache/<id>/pages.png`). Find the *Reglementări urbanistice* plate.
   PDFs often contain it **twice**, scanned differently. On HCL 597/2026, page 6 is
   unreadable and page 13 is clean. Use the clearest copy as `plansa.pagina_pdf`.
3. `puz.py render` renders that page at its native dpi, plus an overview with a
   pixel grid.
4. **Transcribe the coordinate table** into `coordonate.puncte`, as printed:
   `[Nord (x), Est (Y)]`, and add `suprafata_declarata_m2`.
   - **Order.** Tables list vertices in boundary order, but the numbers need not
     run that way (HCL 604/2023: 500, 501, …, 110, 504, 505, 48, 506, …). If they
     don't, copy the table order into `coordonate.ordine`.
   - **Extra checks.** If the table prints side lengths `D(i,i+1)` and a perimeter,
     add `laturi_declarate_m` and `perimetru_declarat_m`. A misread digit then
     shows on the two sides touching that vertex. With two sides known, a hidden
     digit can be solved for; see the note in `2020-4.json`.
   - **Area only.** Large tables (HCL 571/2024 has 138 points) often print only
     the area. Then also look for spikes, and draw the result with `overlay`.
5. **Pick points.** Pick two well-separated corners from the overview into
   `gcp_px`. `puz.py predict` then says where every other vertex should be, and
   `puz.py vertices <names…>` shows zoomed, grid-labelled crops around them. Prefer
   sharp corners for `gcp_px` (at least 4, spread out). Put a few more in
   `verificare_px`: they are checked but not used in the fit.
   - **Poor control points.** Vertices along a smooth curve or a straight run make
     poor control points. So do vertices inside dark fills, or a few pixels apart
     at small scales.
   - **Thick lines.** Pick the centre of the boundary line, not its edge. At 1:2500
     the line is ~2 m wide.
   - **`overlay x0 y0 x1 y1`** draws the boundary the current fit predicts over the
     plate. Where it leaves the drawn line, a pick is off. When the residual gate
     fails, `build` prints a leave-one-out table: the point whose removal drops
     everyone else's error is the bad one (HCL 571/2024: point 84 was 15 px off).
   - **Rotation.** Plates can be rotated against the Stereo 70 grid (571/2024 by
     6.4°). The affine fit handles that, so don't assume north-up when predicting.
6. **Crops.** Set `legenda_px` (one or more `[x0, y0, x1, y1]` boxes, stacked into
   one image) and `decupaj`. The overlay is the boundary plus `buffer_m`, minus any
   `exclude_px` boxes, such as tables or title blocks that the buffer reaches into.
   Use `puz.py grid <x0 y0 x1 y1>` to read box coordinates.
7. **Read the decision's text.** `puz.py hcl` prints it laid out for the recipe:
   validity, each UTR paragraph with its indicators, and the sentences that set
   conditions. The text is authoritative, so fill these from it, not from the plate:
   - `utr`: code, name, `pot_max`, `cut_max`, `h_max`;
   - `valabilitate`: `{ani, pana_la}`, counted from the session date. `new` fills
     it when the text states it;
   - `prelungiri`: extensions, each `{hcl, pana_la}`. Search the decision listing
     for "Prelungirea valabilității" and the PUZ's name or decision number;
   - `modifica` / `modificat_de`: other PUZ decisions this one amends or that
     amend it;
   - `diferente_fata_de_plansa`: everything where the text says something other
     than the plate. Compare indicators, heights and parcel sizes one by one;
   - `conditii`: conditions and obligations, in plain words: what must happen
     before permits or before reception, land to transfer, works the investor
     pays for.

   Expired PUZ-uri stay on the map; the info window shows the date.
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

## The decision's text vs the plate

The council can amend a PUZ in session. An amendment changes the decision's
articles, but the annexed plate stays as the chief architect endorsed it. Two
examples:

- **HCL 604/2023.** It got an Art. 2, proposed by the urbanism committee and
  passed 15-0 with 3 abstentions (minutes of 12.07.2023, pp. 32-33). Houses are
  allowed only on parcels of at least 800 m², as the PUG requires for ULid, while
  the plate draws ten lots from 300 m². The chief architect said in session that
  the amendment "demolează parțial avizul".
- **HCL 4/2020.** The plate prints H max 24 m; the text sets 21 m at the cornice
  and 25 m overall.

Signs of an amendment: a short article placed after the list of annexes, or one
that contradicts the plate. The session's minutes (`proces-verbal`, linked from the
session page as "Minută") say who proposed it and why. They are scanned PDFs, so
read the relevant pages as images.

`fetch` saves the text as `documente/<id>/hotarare.txt` next to the PDFs, with a
checksum. The site shows validity, differences and conditions in the info window
and the legend card.

## Plates without a coordinate inventory

Some designers print no inventory. HCL 621/2022 is one: a Spanish firm, 17 ha at
1:1000. That plate carries a **Stereo 70 grid** of small crosses every 100 m, each
labelled with Est (vertical text) and Nord (horizontal). Then:

- list the crosses you pick under `repere` as `"C<E>_<N>": [N, E]`, and use those
  names in `gcp_px` and `verificare_px`;
- trace the PUZ boundary ("Limita zonei de reglementare") on the plate as
  `limita_px`, a list of `[x, y]`. The fit carries it into Stereo 70;
- put the total from the plate's balance table (`Bilanț teritorial`) in
  `suprafata_declarata_m2`. A traced boundary is held to 3% instead of 1%.

The published entry records which method was used.

## Quality gates

| Check | Limit |
|---|---|
| area vs plate | 1 % (inventory), 3 % (traced boundary) |
| side lengths, perimeter | 1 cm / 0.1 % |
| worst control/check residual | 1 m or 4 plate pixels, whichever is larger |

The pixel term exists because picking is good to 2-3 pixels at any scale: 1 m
covers 1:250-1:1000 plates, and 1:2500 at 200 dpi gets ~1.3 m.

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
  keeps its own legend crop. The UTR codes are the PUG's, or PUZ-specific variants
  such as `Rim_Carbochim`.
- POT/CUT are sometimes given per parcel, not per UTR (571/2024). The recipe's
  `utr` then names the zones and leaves the figures to the PDF.
- PDFs vary a lot: 15 to 91 pages, 5 to 55 MB. The plate can sit anywhere in them
  and may come in several copies (597/2026 pages 6 and 13). A neighbouring page is
  often a different plate, such as land ownership, that looks similar.
