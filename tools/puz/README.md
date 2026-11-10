# PUZ-uri pe hartă

Each approved PUZ (Plan Urbanistic Zonal) gets three things on the site: its
regulations plate warped onto the map, its boundary, and its legend. They are built
from a **recipe** - `puzuri/<localitate>/<an>-<nr>.json` - by `tools/puz/puz.py`.
The recipe holds what someone (or an agent) has to read off the documents. The
script does the rest and checks the reading.

Needs Python with `rasterio` (it bundles GDAL), `shapely`, `pyproj`, `numpy` and
`pillow` (`requirements.txt`), plus `pdfinfo`/`pdfimages`/`pdftoppm` (poppler) on
PATH. Run it through `tools/puz/puz.sh`: it uses `py -3.13` on the Windows laptop
and `python3` elsewhere. `setup.sh` installs everything on a Linux machine, and
`puz.sh doctor` checks packages, poppler and the network.

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
   one image; a fifth number turns a box clockwise, for sideways plates) and
   `decupaj`. The overlay is the boundary plus `buffer_m`, minus any
   `exclude_px` boxes, such as tables or title blocks that the buffer reaches into.
   Use `puz.py grid <x0 y0 x1 y1>` to read box coordinates.
   - **What goes in the legend.** The symbol key and the UTR blocks: codes, names
     and allowed POT/CUT/height. Leave out bilanțuri teritoriale, area-only
     zonificare tables, parking calculations, street profiles, the title block, and
     stamps. 627/2026 first went out with all of these, which made it three times
     longer.
   - **An unreadable legend is left out.** 754/2021's plate is shrunk onto A4 and
     its legend can't be read even in the PDF, so `legenda_px` stays empty and
     `plansa.nota` says why.
   - **Image clean-up.** A 3×3 median filter removes scan grain, but it also
     removes strokes thinner than 2 px. So it runs only on scans of 250 ppi or
     more, and before downscaling. Levels are then stretched so the paper turns
     white. On the 96 ppi scan of 594/2026, the old fixed threshold had erased
     the small print.
   - `puz.py legend <recipe>` rebuilds only the legend, also for a PUZ already
     published. `--dry-run` writes it to the cache instead.
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

## Plates with an unlabelled grid

Some plates keep the grid crosses but lose their labels with the topographic plan's
frame (HCL 24/2026). The crosses still sit on exact multiples of the step, so a
rough position good to under half a step fixes every label:

- `geocode --streets "<A>" "<B>"` takes two streets that meet on the plate from
  OpenStreetMap and gives their centrelines' crossing in Stereo 70;
- `caroiaj` takes the picked crosses, the step, the north direction, the measured
  px/m and that anchor, and labels each cross. It warns when a label could be one
  step off, and `--write` stores the result as `repere` and `gcp_px`.

The imagery check confirms: a wrong label shows as the whole plate shifted by one
step. Tested on HCL 621/2022's labelled crosses, with an anchor off by up to 46 m on
a 100 m grid, it recovered all six labels.

## Plates without usable coordinates: OpenStreetMap control points

When a plate's coordinates cannot be used, its streets and buildings are still drawn
to scale. That happens when the table is illegible in a reduced scan (754/2021), or
when the crosses belong to the sheet template and not to the drawing (24/2026: they
sit in the same places on two plates whose drawings are offset). OpenStreetMap has
the same streets and buildings, good to a few metres:

- `"georef_metoda": "osm"` switches the fit to a similarity (scale, rotation,
  shift) and the residual gate to 5 m;
- `osm_ancora` = `{px, en, px_per_m, nord}` gives a first placement: one street
  crossing from `geocode`, the scale from a dimension line, and the north arrow;
- `osm [x0 y0 x1 y1]` draws OSM streets (green), buildings (red) and street
  crossings (magenta) over the plate, from the anchor or from the current fit;
- `osm-snap NAME x y --write` takes a corner picked on the plate and stores the
  nearest OSM building corner or street crossing as a control point (`--check`
  for a check point). It warns when two candidates are too close to tell apart.

Use 4-8 points spread over the plate. Buildings that exist both on the plate and
in OSM are best; drawn proposed buildings don't exist yet. The boundary is traced
(`limita_px`) unless an inventory is legible. The published entry is marked
approximate, with a precision of at least 3 m, and the info window says so.

## Amending decisions

A decision may amend an earlier PUZ ("Modificare P.U.Z. aprobat prin Hotărârea nr.
…"). Such decisions often carry no plate: HCL 642/2025 changes only obligations of
754/2021. The map shows the base PUZ as amended:

- the base recipe's `modificat_de` holds `{hcl, data, rezumat, plansa_noua}`;
- its `utr`, `conditii` and differences are written as they stand after the
  amendment;
- if the amendment brings a new regulations plate, `plansa.pdf` and
  `plansa.sursa_hcl` point at it and the base shows that plate.

The amendment's own recipe gets `"stare": "integrat"` and `"integrat_in"`.

## Recipe states

| `stare` | Meaning | `build` |
|---|---|---|
| absent | being worked on, or published | builds |
| `"oprit"` + `motiv` | cannot be done with what was published; kept as a record, and the next attempt starts from it | refuses |
| `"integrat"` + `integrat_in` | an amendment folded into its base PUZ | refuses |

Stopped recipes are committed, so the working tree stays clean for the next run.

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

PUZ-uri added in a cloud session leave their documents behind on the cloud machine.
After pulling, `puz.sh sync-docs` downloads whatever is missing for every recipe and
checks it against `SHA256SUMS`, without changing the manifest. A transcription
written into `hotarare.txt` in the cloud can't be recovered; the page text is saved
instead. That's why the recipe has to carry everything the map needs.

## What is published

- `ClujPugWeb/wwwroot/puz/<id>/plansa.webp` - the plate, warped to Web Mercator,
  clipped to the boundary. The site draws it as a `GroundOverlay`, which lines up
  because the image is already in Web Mercator.
- `ClujPugWeb/wwwroot/puz/<id>/legenda.webp` - the legend crop.
- An entry in `ClujPugWeb/wwwroot/puz/puz.json`: decision, title, UTR/POT/CUT,
  bounds, boundary in WGS84, fit quality.

## Batch runs, on the laptop or in the cloud

The `/puz-batch N` skill (`.claude/skills/puz-batch`) coordinates a batch. For each
of the next N decisions it runs one fresh agent on the `/add-puz` skill, waits for
it, audits its commit, and moves on. Agents never run in parallel: they share
`puz.json` and `SHA256SUMS`. The batch uses these commands:

- `puz.sh next [--count N] [--retry-stopped]` lists the decisions still to do in
  2020-2026, newest first, and how many are published, integrated or stopped. It
  takes approvals and amendments of PUZ-uri. Extensions are left out: the base
  PUZ's agent finds them with `related`. Interrupted runs (a recipe with no map
  entry and no `stare`) come back first.
- `puz.sh audit <recipe> [--commit C]` checks one agent's work:
  - the outcome matches the recipe (published / `oprit` with a reason /
    `integrat` and listed by its base);
  - the quality gates pass, and `puz.json` is up to date;
  - the commit touches only that PUZ's files (and a base or amendment folded in);
  - the tree is clean;
  - no owner is named. The names after "beneficiar(i):" in the decision's text are
    looked for in the recipe, the map entry and the commit message. Words the
    page's text breaks up ("R oșca") are put back together first.

  It exits 0 (`OK`), 1 (`PROBLEME`: the batch moves the commit aside to
  `puz-review/<id>`) or 2 (`DE VERIFICAT`). Exit 2 means a word of an owner's name
  turned up, maybe in a street name or the project's own name (Ansamblu „Noroc”).
  It is printed in context, for someone to judge. Exit 2 also comes when the
  decision has a "beneficiar(i):" but no name could be read after it: then nothing
  was checked, and someone looks for the names by hand.

### In a Claude Code cloud session

The laptop can be off. The session runs on an Anthropic Ubuntu 24.04 machine, works
on a fresh clone, and pushes each PUZ to `puz-cluj` as soon as it is audited.
Setting up the cloud environment (claude.ai/code, environment settings):

1. **GitHub.** The repository must be connected (Claude GitHub app). The session
   clones it and needs push access to `puz-cluj`.
2. **Setup script.** Upload `tools/puz/setup.sh`. It installs poppler-utils,
   DejaVu fonts and the Python packages, and the environment is cached with them.
   Alternatively, add a SessionStart hook to `.claude/settings.json` running
   `bash "$CLAUDE_PROJECT_DIR"/tools/puz/setup.sh`. It skips what is installed, so
   it costs little on resume.
3. **Network.** Choose "Custom", keep "Also include default list of common package
   managers" (PyPI, Ubuntu, GitHub), and allow:
   ```
   primariaclujnapoca.ro
   *.primariaclujnapoca.ro
   overpass-api.de
   nominatim.openstreetmap.org
   server.arcgisonline.com
   ```
4. **Run.** Start a session on the repository, branch `puz-cluj`, with
   `/puz-batch 6`. Or make it a scheduled task (at most hourly; each run is a new
   session) whose prompt says: `/puz-batch 4 - lucrează pe branch-ul puz-cluj și
   împinge acolo fiecare PUZ`. The session can be followed, or stopped, from the
   web or the Claude app.
5. **After.** On the laptop, `git pull`, then `puz.sh sync-docs` for the documents
   backup.

What the cloud costs: a PUZ takes about 15-25 minutes and 200 k tokens of an
agent's work, counted against the plan's usage like a local session. A batch
stops on its own when two agents in a row are cut off, as happens at a usage
limit. Nothing is lost when it stops: every audited PUZ is already pushed, and an
interrupted one is committed as unfinished, so the next run resumes it.

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
