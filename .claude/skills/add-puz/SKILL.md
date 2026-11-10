---
name: add-puz
description: Add one approved PUZ (Plan Urbanistic Zonal) of Cluj-Napoca to the clujpug.ro map - from the council decision's PDF to a georeferenced plate, legend and decision notes, verified and committed. Use when asked to add or process a PUZ given its decision year and number, e.g. "/add-puz 2021 24".
---

# Add a PUZ to the map

Input: the decision's year and number, e.g. `2021 24` for HCL 24/2021.

You work alone. Do every step yourself, check your own work, and either commit a
PUZ that passes every check or stop and report why it cannot be done. Never publish
something you are unsure of: a wrong overlay on a public map is worse than none.

**Read `tools/puz/README.md` first.** It explains the method, the recipe fields,
the quality gates and the lessons from the PUZ-uri done so far. This file is the
checklist; the README is the reference.

## Ground rules

- Work from the repository root, on branch `puz-cluj`: on the Windows laptop or in
  a Claude Code cloud session (Linux). Check with `git branch --show-current` and
  `git status --short` before starting. If the branch is different or the tree has
  changes you did not make, stop and report. Never push, never switch branches.
- If `puzuri/cluj-napoca/<id>.json` already exists, check its `stare`:
  - `"oprit"`: an earlier attempt stopped. Read `motiv` and the notes, keep
    everything still valid, and pick up from where it stopped. Usually a new method
    now covers the case.
  - `"integrat"`: the decision was folded into its base PUZ. Stop.
  - no `stare`, and the PUZ is in `ClujPugWeb/wwwroot/puz/puz.json`: already
    published. Stop.
  - no `stare`, and not in `puz.json`: an earlier run was interrupted. The recipe
    may be uncommitted; any leftover published files under
    `ClujPugWeb/wwwroot/puz/<id>/` are its, too. Resume: check each filled field
    against the documents before relying on it, then carry on from the first step
    that is not done.
- Touch only this PUZ's files:
  - `puzuri/cluj-napoca/<id>.json`;
  - `puzuri/cluj-napoca/documente/SHA256SUMS`;
  - `ClujPugWeb/wwwroot/puz/<id>/`;
  - `ClujPugWeb/wwwroot/puz/puz.json`.

  When the decision amends another PUZ, also that base PUZ's recipe and published
  folder (see "Amending decisions"). Do not edit the tools, the site code or other
  recipes. If a tool is in your way, say so in your report.
- **No beneficiaries' names**: not in the recipe, not in conditions, not in the
  commit message. Companies and public bodies named as the PUZ's purpose (for
  example "Spitalul ...") are fine; owners are not.
- Shell: use the Bash tool. Run the pipeline as `tools/puz/puz.sh`. It picks
  `py -3.13` on the laptop and `python3` elsewhere; both have rasterio/GDAL,
  shapely, pyproj and pillow. `pdfinfo`, `pdfimages` and `pdftoppm` are on PATH.
  `tools/puz/puz.sh doctor` checks all of it, and the network.
- Look at images with the Read tool. Crops made by `grid`, `vertices` and
  `overlay` carry a pixel grid labelled in full-plate coordinates; read positions
  off those labels.

All commands are `tools/puz/puz.sh <command> puzuri/cluj-napoca/<id>.json ...`,
where `<id>` is `<an>-<nr>`.

## Steps

1. **Skeleton.** `tools/puz/puz.sh new <an> <nr>`. It prints the title,
   session date, PDF and the validity it found in the decision's text. If the
   recipe already exists, the ground rules above say whether to resume or stop.
2. **Documents.** `fetch`. Look at `puz_cache/<id>/pages.png` and the page list.
   - Find the regulations plate ("Reglementări urbanistice", "Plan reglementări",
     "zonificare"). It is usually the large-format page.
   - The PDF may hold it twice, or hold similar plates (land ownership, public
     utility works). Render the candidates small with `pdftoppm -r 25 -f N -l N`
     and read their title blocks.
   - Choose the clearest copy of the regulations plate. Set `plansa.pagina_pdf`,
     and `plansa.dpi` to the native ppi from `pdfimages -list -f N -l N <pdf>`.
   - **No plate in the PDF.** If the decision amends another PUZ ("Modificare
     P.U.Z. aprobat prin Hotărârea nr. …"; `related` also says so), follow
     "Amending decisions". Otherwise, as with the text-only 2017-2019 decisions,
     stop.
3. **Render.** Run `render`, then look at `plate-overview.png`. Fill
   `plansa.denumire` and `plansa.scara` from the title block.
4. **Coordinates.**
   - **Inventory.** Find the "Inventar de coordonate" table and zoom on it with
     `grid x0 y0 x1 y1 --scale 2 --step 20`. Transcribe `[Nord, Est]` in table
     order, then add `ordine` if the numbering is not boundary order, plus
     `suprafata_declarata_m2` and, when printed, `laturi_declarate_m` and
     `perimetru_declarat_m`. Use the plate's own figures.
   - **No inventory but a labelled Stereo 70 grid.** Use `repere`, trace
     `limita_px` on the boundary line, and take the area from the balance table
     (README, "Plates without a coordinate inventory").
   - **Grid crosses without labels.** Follow "Unlabelled grids" below, and trace
     `limita_px` if there is no inventory either. First make sure the crosses
     belong to the drawing: if the PDF has another plate on the same base map,
     the crosses must move with the drawing.
   - **No usable coordinates at all** (illegible table, crosses not tied to the
     drawing, nothing printed): follow "OpenStreetMap control points" below.
   - **Check before going on.** Run `build --dry-run --no-check`. The area, the
     side lengths and the perimeter must pass. A failed side points at a misread
     vertex: re-read that row, zooming harder. If a digit is hidden, solve it from
     the two sides; leave a note in `coordonate.nota`.
5. **Control points.**
   - Put two well-separated corners in `gcp_px`. `predict` gives where the others
     should be; `vertices <names>` shows zoomed crops around them.
   - Pick at least 4 sharp corners spread over the whole boundary, on the centre
     of the boundary line. Put 2 or more others in `verificare_px`.
   - Don't trust a north-up assumption: plates can be rotated.
   - `overlay x0 y0 x1 y1` draws the fitted boundary over the plate. It must follow
     the drawn PUZ boundary everywhere.
   - When `build --dry-run --no-check` fails the residual gate, read its
     leave-one-out table and re-pick the culprit. Never loosen a gate or delete
     points just to pass.
6. **Crops.**
   - `legenda_px`: one or more boxes stacked into one image. Put in:
     - the symbol key;
     - the UTR blocks: codes, names, and the POT/CUT/height/regime they allow,
       including a "posibilități maxime" or "reglementări urbanistice" table;
     - short regulatory notes printed with the legend.

     Leave out:
     - bilanțuri teritoriale (existing/proposed areas);
     - zonificare tables that only give areas;
     - parking calculations;
     - street profiles;
     - the title block and the plate's name/scale header;
     - signatures and stamps.

     Box each part you keep, with no gap above or below. When the legend sits
     between left-out tables, split it into several boxes. On a plate printed
     sideways, add a fifth number to each box: degrees to turn it clockwise (90 when
     the text reads upwards).
   - Look at `legenda.webp` (`legend <recipe> --dry-run` rebuilds only it) at the
     size the site shows it, about 600 px wide. If the legend can't be read in the
     PDF itself (754/2021: a plate shrunk onto A4), leave `legenda_px` empty and
     say why in `plansa.nota`. An unreadable image doesn't help anyone.
   - `decupaj.exclude_px`: tables or title blocks that the boundary buffer reaches
     into.
7. **Decision text.** Run `hcl` and `related`, and read the full text in
   `puzuri/cluj-napoca/documente/<id>/hotarare.txt`. If the decision's page had no
   text, the file says so. Then transcribe the decision from the scanned PDF into
   it: the preamble briefly, the articles in full, and a line saying which pages you
   transcribed. Run `fetch` again to record its checksum.
   - In a cloud session, `documente/` is gone when the session ends: git ignores it.
     The laptop gets the PDFs back with `sync-docs`, but not your transcription.
     So whatever the map needs from the text goes into the recipe.

   Fill these from the text, not from the plate:
   - `utr`: `cod`, `denumire`, `pot_max`, `cut_max`, `h_max`, plainly worded;
   - `valabilitate`: check what `new` filled in;
   - `prelungiri`: each extension found by `related`, as `{hcl, pana_la}`. Read the
     extending decision's page for the new term, or compute it from its text;
   - `modifica` / `modificat_de`;
   - `diferente_fata_de_plansa`: compare the text against the plate item by item
     (indicators, heights, parcel sizes, zones). Name the article if the
     difference comes from one.
   - `conditii`: conditions and obligations in plain words.

   An article that looks appended, or that contradicts the plate, is likely an
   amendment. Say so in the difference only if the session minutes confirm it,
   otherwise just state what the text says.
8. **Build.** Run `build`, without `--dry-run`, then look at
   `puz_cache/<id>/check_imagery.png`.
   - The boundary must sit on the real place: roads, plot edges and neighbouring
     buildings drawn on the plate must fall on the real ones within a few metres.
   - If it is plainly off (wrong place, mirrored, scaled wrong), you made a
     mistake. Find it; don't commit.
   - Optional, on the laptop only: `http://localhost:5077/?puz=<id>` shows it on
     the site, if the local server runs. Screenshot it with headless Chrome:
     `"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless=new --disable-gpu --user-data-dir=<scratch dir> --window-size=1200,800 --virtual-time-budget=20000 --screenshot=<png> "http://localhost:5077/?puz=<id>"`.
9. **Commit.**
   - `git add` exactly: `puzuri/cluj-napoca/<id>.json`,
     `puzuri/cluj-napoca/documente/SHA256SUMS`, `ClujPugWeb/wwwroot/puz/<id>`
     and `ClujPugWeb/wwwroot/puz/puz.json`.
   - Message: `PUZ HCL <nr>/<an> – <place>`, then a short body. The body gives the
     zone(s) and key indicators, plate and page, the method, the area check, the
     residuals, and anything notable (differences, extensions, amendments). End
     with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
   - Then run `audit puzuri/cluj-napoca/<id>.json`. It re-checks the gates and the
     files the commit touched, and looks for the owners' names.
     - `PROBLEMĂ`: fix it and `git commit --amend`. Your commit isn't pushed yet.
     - `VERIFICĂ`: a word of an owner's name appears somewhere. Fine in a street
       name or the project's own name; an owner named is a problem. If it says the
       names couldn't be read, look for them yourself and say so in your report.
     - Say in your report what the audit printed.

## Amending decisions

A decision may amend an earlier PUZ: change its obligations, its indicators, or its
plate. The map shows the base PUZ with the amendment applied, not the amendment on
its own.

1. Find the base decision, `<an>-<nr>`, in the title or the text. `related` prints
   it.
2. **Base not yet published.** Add the base PUZ with this whole procedure (`new`
   for the base's year and number), taking the amendment into account:
   - If the amendment's PDF carries a new plate of the same kind (regulations),
     georeference that plate instead of the base's. Set `plansa.pdf` to the
     amendment's PDF URL, `plansa.sursa_hcl` to `"<nr>/<an>"`, and `pagina_pdf`
     to the page in that PDF. Otherwise use the base's own plate.
   - Where the amendment changes something, its text wins: indicators,
     conditions, obligations. Write the base's `utr`, `conditii` and
     `diferente_fata_de_plansa` as they stand after the amendment, and mark
     changed items "(modificat prin HCL <nr>/<an>)".
3. **Base already published.** Update it if the amendment changes published
   fields (`utr`, `conditii`, validity) or is otherwise notable. If it brings a new
   regulations plate, replace the plate, re-georeferencing as in step 2. Rebuild
   the base.
4. Either way, add the amendment to the base's `modificat_de` as `{hcl, data,
   rezumat, plansa_noua}`:
   - `rezumat`: one or two sentences on what changed;
   - `plansa_noua`: true if the shown plate is the amendment's;
   - mention the amendment's own validity in the summary if it differs.

   Then mark the amendment's recipe `"stare": "integrat"`, `"integrat_in": "<base
   id>"`, keeping its notes and conditions. It gets no build.
5. Commit everything in one commit: both recipes, the base's published files,
   `puz.json` and `SHA256SUMS`. Message: `PUZ HCL <base nr>/<an> – <place> (cu
   modificarea HCL <nr>/<an>)`, or `… – actualizat cu modificarea HCL …` when the
   base was already published.

## Unlabelled grids

Some plates show the Stereo 70 grid crosses but with their labels cut off. The
crosses sit on exact multiples of the grid step, so a rough position of the plate,
good to under half a step, fixes every label:

1. **Crosses.** Pick at least 4, spread out, including pairs on the same grid line
   (same row or column). Put them in `caroiaj.cruci_px`, as `{name: [x, y]}`.
2. **Step and scale.** `caroiaj.pas_m` is usually 50 m on 1:500 plans and 100 m on
   1:1000-1:2000. Measure `caroiaj.px_per_m` on a dimension line: pixels between
   its ticks divided by the metres it reads. Plates are often printed reduced, so
   don't trust the printed scale. `caroiaj` warns if the crosses disagree.
3. **North.** `caroiaj.nord` is the north arrow's direction in degrees, clockwise
   from up: 0 up, 90 right, 270 left.
4. **Anchor.** Run `geocode --streets "<street A regex>" "<street B regex>"` for
   two streets that meet on the plate; it gives their centrelines' crossing in
   Stereo 70. Pick the same crossing on the plate. Set `caroiaj.ancora` to
   `{px: [x, y], en: [E, N], sursa: "..."}`.
5. **Labels.** Run `caroiaj` and read its verdict. If it says the labels are safe,
   run `caroiaj --write`: the labelled crosses go into `repere` and `gcp_px`. If
   it warns, get a better anchor.
6. **Build.** The imagery check is decisive. A label one step off shows as the
   whole plate shifted by one step against roads and buildings. Fix the anchor and
   redo it. Say in `coordonate.sursa` that the grid was labelled this way.

## OpenStreetMap control points

The fallback when the plate has no usable coordinates. The result is published as
approximate (±3-5 m), and the info window says so.

1. Set `"georef_metoda": "osm"`. The fit becomes a similarity and the residual
   gate 5 m.
2. **Anchor.**
   - Run `geocode --streets "<A>" "<B>"` for two streets meeting on the plate, and
     pick the same centreline crossing on the plate.
   - Measure `px_per_m` on a dimension line and read `nord` off the north arrow
     (degrees clockwise from up).
   - Set `osm_ancora` = `{px: [x, y], en: [E, N], px_per_m, nord}`.
3. **Overlay.** Run `osm`. OSM streets and buildings should land near the drawn
   ones. If they are rotated or scaled wrong, fix `nord` or `px_per_m`.
4. **Control points.** Pick 4-8 points spread over the plate:
   - existing buildings' corners drawn on the plate, and street crossings;
   - never proposed buildings, never stamps or text.

   For each, read its pixel position with `grid` or `vertices`, then run
   `osm-snap NAME x y --write` (`--check` for check points). Read what it snapped
   to: a corner of the same building, the same crossing. If two candidates are
   close, look at `osm` again and use `--pick N`. After the first two points the
   fit replaces the anchor: run `osm` again to see it tighten.
5. **Boundary.** Trace `limita_px` (unless an inventory is legible). The area
   comes from the balance table, with a 3% tolerance.
6. **Build and imagery check** as usual. Put the method and the points used in
   `coordonate.sursa`.

## When to stop instead

Stop without building if any of these holds, and report what you saw:

- there is no plate in the PDF, and the decision amends no PUZ;
- not even the OpenStreetMap method works: no existing street or building on the
  plate can be matched to OSM;
- the coordinate table is illegible where it matters and the checks cannot
  settle it;
- the quality gates fail and re-picking does not fix them;
- the imagery check looks wrong and you cannot find why.

If you already ran a publishing `build`, remove `ClujPugWeb/wwwroot/puz/<id>/`
and restore `ClujPugWeb/wwwroot/puz/puz.json` with `git checkout -- <path>`.

Then set in the recipe `"stare": "oprit"` and `"motiv": "<what is missing, in a
sentence>"`, keeping everything you did fill in. Commit the recipe and
`SHA256SUMS` as `PUZ HCL <nr>/<an> – oprit: <motiv scurt>`. A stopped recipe is a
record: the next attempt starts from it, and a batch run won't retry it blindly.

## Report

End with a short report in Romanian:

- PUZ and outcome: published, integrated into its base, or stopped (with reason);
  the commit hash;
- plate page and why that one; method (inventory / grid);
- area, sides and perimeter checks; residuals (rms, worst, limit);
- imagery check, in a sentence;
- differences between text and plate; extensions and amendments; number of
  conditions;
- anything you were unsure of, so a human can look there first.
