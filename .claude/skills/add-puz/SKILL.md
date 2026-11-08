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

- Work from the repository root, `c:\Repositories\clujpugweb`, on branch `puz-cluj`.
  Check with `git branch --show-current` and `git status --short` before starting.
  If the branch is different or the tree has changes you did not make, stop and
  report. Never push, never switch branches.
- Touch only this PUZ's files:
  - `puzuri/cluj-napoca/<id>.json`;
  - `puzuri/cluj-napoca/documente/SHA256SUMS`;
  - `ClujPugWeb/wwwroot/puz/<id>/`;
  - `ClujPugWeb/wwwroot/puz/puz.json`.

  Do not edit the tools, the site code or other recipes. If a tool is in your way,
  say so in your report.
- **No beneficiaries' names**: not in the recipe, not in conditions, not in the
  commit message. Companies and public bodies named as the PUZ's purpose (for
  example "Spitalul ...") are fine; owners are not.
- Shell: use the Bash tool. Run Python as `py -3.13` (it has rasterio/GDAL,
  shapely, pyproj and pillow). `pdfinfo`, `pdfimages` and `pdftoppm` are on PATH.
- Look at images with the Read tool. Crops made by `grid`, `vertices` and
  `overlay` carry a pixel grid labelled in full-plate coordinates; read positions
  off those labels.

All commands are `py -3.13 tools/puz/puz.py <command> puzuri/cluj-napoca/<id>.json ...`,
where `<id>` is `<an>-<nr>`.

## Steps

1. **Skeleton.** `py -3.13 tools/puz/puz.py new <an> <nr>`. It prints the title,
   session date, PDF and the validity it found in the decision's text. If the
   recipe already exists, stop: someone did this PUZ.
2. **Documents.** `fetch`. Look at `puz_cache/<id>/pages.png` and the page list.
   - Find the regulations plate ("Reglementări urbanistice", "Plan reglementări",
     "zonificare"). It is usually the large-format page.
   - The PDF may hold it twice, or hold similar plates (land ownership, public
     utility works). Render the candidates small with `pdftoppm -r 25 -f N -l N`
     and read their title blocks.
   - Choose the clearest copy of the regulations plate. Set `plansa.pagina_pdf`,
     and `plansa.dpi` to the native ppi from `pdfimages -list -f N -l N <pdf>`.
   - **No plate in the PDF** (2017-2019 decisions are text only): stop and report.
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
   - **Neither.** Stop and report.
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
   - `legenda_px`: one or more boxes stacked into one image, holding the legend and
     useful tables (UTR indicators), but no signatures or stamps.
   - `decupaj.exclude_px`: tables or title blocks that the boundary buffer reaches
     into.
7. **Decision text.** Run `hcl` and `related`, and read the full text in
   `puzuri/cluj-napoca/documente/<id>/hotarare.txt`. Fill these from the text, not
   from the plate:
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
   - Optional: `http://localhost:5077/?puz=<id>` shows it on the site, if the
     local server runs. Screenshot it with headless Chrome:
     `"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless=new --disable-gpu --user-data-dir=<scratch dir> --window-size=1200,800 --virtual-time-budget=20000 --screenshot=<png> "http://localhost:5077/?puz=<id>"`.
9. **Commit.**
   - `git add` exactly: `puzuri/cluj-napoca/<id>.json`,
     `puzuri/cluj-napoca/documente/SHA256SUMS`, `ClujPugWeb/wwwroot/puz/<id>`
     and `ClujPugWeb/wwwroot/puz/puz.json`.
   - Message: `PUZ HCL <nr>/<an> – <place>`, then a short body. The body gives the
     zone(s) and key indicators, plate and page, the method, the area check, the
     residuals, and anything notable (differences, extensions, amendments). End
     with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## When to stop instead

Stop without building or committing if any of these holds, and report what you saw:

- there is no plate in the PDF, or no coordinates and no labelled grid;
- the coordinate table is illegible where it matters and the checks cannot
  settle it;
- the quality gates fail and re-picking does not fix them;
- the imagery check looks wrong and you cannot find why.

If you already ran a publishing `build`, remove `ClujPugWeb/wwwroot/puz/<id>/`
and restore `ClujPugWeb/wwwroot/puz/puz.json` with `git checkout -- <path>`. Leave
the recipe in place, uncommitted, for review.

## Report

End with a short report in Romanian:

- PUZ and outcome: committed (with hash) or stopped (with reason);
- plate page and why that one; method (inventory / grid);
- area, sides and perimeter checks; residuals (rms, worst, limit);
- imagery check, in a sentence;
- differences between text and plate; extensions and amendments; number of
  conditions;
- anything you were unsure of, so a human can look there first.
