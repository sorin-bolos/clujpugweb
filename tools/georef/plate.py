"""Image analysis of a scanned PUG plate.

The Romanian 1:5000 plans these plates are drawn on carry a Stereo 70 (EPSG:3844)
kilometre grid, ticked in the margin every 500 m, and a printed geographic
coordinate at the sheet corners. That is enough to georeference a plate exactly,
without picking control points by hand.

Two things are recovered here, both from the ticks alone:

  * the ground resolution, because the tick period is known to be 500 m. This is
    measured rather than taken from the TIFF's DPI tag - the scans come out
    around 198 dpi, not the 200 they claim, and over a 5 km sheet that 1%
    is a 50 m error.
  * the grid's rotation relative to the image, by comparing where the ticks fall
    on opposite margins.

The ticks are found by periodicity rather than by segmenting each mark. The
margin also holds the tick labels, and a digit stroke looks much like a tick
stroke; but the labels repeat with the ticks, so the period survives them.
"""

import io

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

# Stereo 70 grid interval printed in the margin of a 1:5000 plate.
GRID_INTERVAL_M = 500.0


class PlateError(Exception):
    pass


def load_gray(path):
    """Load a plate as a 2-D uint8 array of grey levels."""
    return np.asarray(open_plate(path)[0].convert("L"))


def open_plate(path):
    """Open a plate from a TIFF, a plain image, or a single-page PDF.

    Feleacu's plans arrive as PDFs wrapping one big JPEG, Apahida's as TIFFs.
    Returns (image, nominal_dpi) - the dpi being what the file claims, which is
    only ever a starting point: the Apahida scans claim 200 and measure 197.

    For a PDF the dpi is derived from the page geometry rather than any tag,
    since the raster is placed on a page whose size is the real paper size.
    """
    if not path.lower().endswith(".pdf"):
        image = Image.open(path)
        dpi = (image.info.get("dpi") or (None, None))[0]
        return image, float(dpi) if dpi else None

    import fitz

    doc = fitz.open(path)
    try:
        if doc.page_count != 1:
            raise PlateError(f"{path} has {doc.page_count} pages; expected one plan")
        page = doc[0]
        images = page.get_images(full=True)
        if len(images) != 1:
            raise PlateError(
                f"{path} holds {len(images)} images; expected one full-page scan"
            )
        raw = doc.extract_image(images[0][0])
        image = Image.open(io.BytesIO(raw["image"]))
        width_in = page.rect.width / 72.0
        return image, image.width / width_in if width_in else None
    finally:
        doc.close()


def nominal_resolution(path, scale=5000):
    """Ground metres per pixel the file implies, or None.

    Only ever used to bracket the search for the real value. Getting the bracket
    from the file rather than from a fixed guess is what lets one tool read both
    a 200 dpi Apahida sheet and a 360 dpi Feleacu one: a range wide enough to
    span both is wide enough to lock onto texture instead of ticks.
    """
    _, dpi = open_plate(path)
    return scale * 0.0254 / dpi if dpi else None


def detect_neatline(gray, thresh=110, margin=0.18):
    """Locate the plate's frame - the thick black rectangle around the drawing.

    Returns (left, right, top, bottom) in pixels. The frame is by far the
    longest continuous dark run in each margin, so a projection profile finds it
    without any edge detection.
    """
    h, w = gray.shape
    dark = gray < thresh
    colsum = dark.sum(axis=0) / h
    rowsum = dark.sum(axis=1) / w

    def edge(sig, n, near_start):
        window = int(n * margin)
        if near_start:
            return int(np.argmax(sig[:window]))
        return int(n - window + np.argmax(sig[n - window:]))

    box = (
        edge(colsum, w, True),
        edge(colsum, w, False),
        edge(rowsum, h, True),
        edge(rowsum, h, False),
    )
    left, right, top, bottom = box
    if right - left < w * 0.5 or bottom - top < h * 0.5:
        raise PlateError(f"frame {box} does not span the image; check the scan")
    return box


def _margin_profile(gray, box, edge, depth=62, gap=8, thresh=150):
    """Dark-pixel count per position in a strip alongside one frame edge.

    `gap` is the distance from the neatline outward; negative values reach back
    inside the frame. Where the ticks sit is a house style, not a standard: the
    2004 Apahida sheets hang them outside the neatline, while the 2005 Feleacu
    ones tuck them inside a double rule.

    Returns (profile, origin) where profile[i] describes position origin + i
    along the edge.
    """
    left, right, top, bottom = box
    h, w = gray.shape
    if edge in ("top", "bottom"):
        if edge == "bottom":
            y0, y1 = bottom + gap, bottom + gap + depth
        else:
            y0, y1 = top - gap - depth, top - gap
        y0, y1 = max(0, y0), min(h, y1)
        if y1 - y0 < 4:
            raise PlateError(f"no room for a {edge} margin strip at gap {gap}")
        return (gray[y0:y1, left:right] < thresh).sum(axis=0), left

    if edge == "right":
        x0, x1 = right + gap, right + gap + depth
    else:
        x0, x1 = left - gap - depth, left - gap
    x0, x1 = max(0, x0), min(w, x1)
    if x1 - x0 < 4:
        raise PlateError(f"no room for a {edge} margin strip at gap {gap}")
    return (gray[top:bottom, x0:x1] < thresh).sum(axis=1), top


def _autocorr(profile):
    """Normalised autocorrelation of a demeaned margin profile.

    Done through the FFT rather than by direct correlation. A Feleacu plate is
    16000 px along an edge, and the direct form is quadratic in that - slow
    enough to make searching for the tick band impractical.
    """
    sig = profile.astype(float)
    sig = sig - sig.mean()
    if not np.any(sig):
        raise PlateError("blank margin strip")
    n = 1 << (2 * len(sig) - 1).bit_length()
    spec = np.fft.rfft(sig, n)
    corr = np.fft.irfft(spec * np.conjugate(spec), n)[:len(sig)]
    return corr / corr[0] if corr[0] else corr


# How far either side of a candidate the correlation must fall away before it
# counts as a real period rather than an artefact of where the search stopped.
PROMINENCE_PX = 20


def _peak(corr, lo, hi, require_prominence=True):
    """Strongest period in [lo, hi], refined to sub-pixel.

    The parabolic refinement matters: one pixel of error in the period compounds
    to metres by the time it reaches the far margin.

    A search window truncates the correlation, and argmax will happily return
    whatever sits against the cut when the real peak lies outside. Such a
    candidate is still climbing as it leaves the window, so it is rejected
    unless the correlation falls away on both sides in the untruncated array.
    """
    lo, hi = int(lo), min(int(hi), len(corr) - 2)
    if hi <= lo:
        raise PlateError("margin too short to hold a grid period")
    k = lo + int(np.argmax(corr[lo:hi]))

    if require_prominence:
        a = max(1, k - PROMINENCE_PX)
        b = min(len(corr) - 1, k + PROMINENCE_PX + 1)
        if corr[a:b].max() > corr[k]:
            raise PlateError(f"period {k} is pinned to the search bound, not a peak")

    y0, y1, y2 = corr[k - 1], corr[k], corr[k + 1]
    denom = y0 - 2 * y1 + y2
    delta = 0.0 if denom == 0 else 0.5 * (y0 - y2) / denom
    return k + float(np.clip(delta, -1, 1)), float(corr[k])


def _best_phase(profile, period):
    """Offset of the first tick, as a position within [0, period).

    Found by folding the profile at the detected period and taking the circular
    mean of the resulting histogram - the ticks pile up at one phase.
    """
    sig = profile.astype(float)
    sig = np.clip(sig - np.median(sig), 0, None)
    idx = np.arange(len(sig))
    angle = 2 * np.pi * (idx % period) / period
    vec = (sig * np.exp(1j * angle)).sum()
    phase = (np.angle(vec) / (2 * np.pi)) % 1.0
    return phase * period


# A peak this weak is noise rather than a tick series.
MIN_PEAK = 0.15

# The scans are anisotropic - the plates measure about 2% finer across the sheet
# than along it, which is the scanner, not the map. Any real difference stays
# well inside this bound, so it brackets the horizontal search once the vertical
# period is known.
MAX_ANISOTROPY = 0.05


# Where to look for the tick band, as a distance from the neatline. Negative
# reaches inside the frame. Apahida's ticks hang outside it, Feleacu's sit
# inside a double rule, and nothing on the sheet says which to expect.
BAND_GAPS = (8, -20, -50, -80, 40)
BAND_DEPTHS = (62, 110)


def _best_band(gray, box, edge, lo, hi):
    """Strongest tick signal for one margin, over the plausible band positions."""
    best = (0.0, None, None)
    for gap in BAND_GAPS:
        for depth in BAND_DEPTHS:
            try:
                profile, origin = _margin_profile(gray, box, edge, depth, gap)
                corr = _autocorr(profile)
                _, strength = _peak(corr, lo, hi)
            except PlateError:
                continue
            if strength > best[0]:
                best = (strength, corr, {"gap": gap, "depth": depth, "origin": origin})
    return best


def _axis_period(gray, box, edges, lo, hi):
    """Grid period along one axis, pooled over its two margins.

    Opposite margins measure the same physical interval, so their
    autocorrelations are summed - weighted by peak strength, so a margin buried
    under the title block cannot outvote a clean one. Returns None when neither
    margin yields a convincing peak.
    """
    found = []
    for edge in edges:
        strength, corr, band = _best_band(gray, box, edge, lo, hi)
        if strength >= MIN_PEAK:
            found.append((strength, corr, edge, band))
    if not found:
        return None, 0.0, {}

    n = min(len(c) for _, c, _, _ in found)
    pooled = np.sum([s * c[:n] for s, c, _, _ in found], axis=0)
    try:
        period, strength = _peak(pooled, lo, min(hi, n - 2))
    except PlateError:
        return None, 0.0, {}
    bands = {edge: band for _, _, edge, band in found}
    return period, strength / sum(s for s, _, _, _ in found), bands


def measure_grid(gray, box, expect_res=(0.60, 0.68)):
    """Measure the Stereo 70 kilometre grid ticked in the plate's margins.

    `expect_res` bounds the plausible ground resolution in metres per pixel and
    brackets the period search. A 1:5000 sheet scanned near 200 dpi lands around
    0.64; the default range is generous either side but tight enough to keep the
    search off the false peaks that cluster at its edges.

    The vertical period reads cleanly on every plate seen so far. The horizontal
    one often does not - the bottom margin carries the sheet nomenclature and
    neighbouring place names, which are periodic enough to capture a naive
    search - so it is looked for only near the vertical period, and reported as
    None when nothing convincing turns up.

    Returns a dict with `res_x_m_px`, `res_y_m_px` (either may be None) and the
    per-edge phases needed to predict where individual ticks fall.
    """
    lo = GRID_INTERVAL_M / expect_res[1]
    hi = GRID_INTERVAL_M / expect_res[0]

    period_y, conf_y, bands_y = _axis_period(gray, box, ("left", "right"), lo, hi)
    if period_y is None:
        period_x, conf_x, bands_x = _axis_period(gray, box, ("bottom", "top"), lo, hi)
    else:
        period_x, conf_x, bands_x = _axis_period(
            gray, box, ("bottom", "top"),
            period_y * (1 - MAX_ANISOTROPY), period_y * (1 + MAX_ANISOTROPY),
        )

    bands = {**bands_y, **bands_x}
    phases = {}
    for edge in ("bottom", "top", "left", "right"):
        period = period_x if edge in ("bottom", "top") else period_y
        if period is None or edge not in bands:
            continue
        band = bands[edge]
        try:
            profile, origin = _margin_profile(
                gray, box, edge, band["depth"], band["gap"])
            phases[edge] = {
                "phase_px": _best_phase(profile, period),
                "origin": origin,
                "period_px": period,
                "gap": band["gap"],
                "depth": band["depth"],
            }
        except PlateError:
            continue

    return {
        "res_x_m_px": GRID_INTERVAL_M / period_x if period_x else None,
        "res_y_m_px": GRID_INTERVAL_M / period_y if period_y else None,
        "period_x_px": period_x,
        "period_y_px": period_y,
        "confidence_x": conf_x,
        "confidence_y": conf_y,
        "edges": phases,
    }


def grid_rotation(grid, box):
    """Rotation of the Stereo 70 grid relative to the image, in radians.

    Meridian convergence tilts the grid against a graticule-bounded frame by
    up to about a degree around Cluj - 85 m across a 5 km sheet, so it is worth
    measuring. A tick on the top margin and the matching tick on the bottom
    margin are the same grid line; the horizontal offset between them over the
    frame height is the tangent of the rotation.

    Returns None when only one of an opposing pair of margins was readable.
    """
    left, right, top, bottom = box
    edges = grid["edges"]

    def shear(a, b, span):
        pa, pb = edges[a], edges[b]
        period = 0.5 * (pa["period_px"] + pb["period_px"])
        offset = (pb["phase_px"] + pb["origin"]) - (pa["phase_px"] + pa["origin"])
        # The two phases are only known modulo the period; take the smallest
        # offset consistent with them, since the true tilt is well under one
        # tick of drift.
        offset -= period * round(offset / period)
        return offset / span

    if "top" in edges and "bottom" in edges:
        return float(np.arctan(shear("bottom", "top", bottom - top)))
    if "left" in edges and "right" in edges:
        return float(-np.arctan(shear("left", "right", right - left)))
    return None


# How far the true resolution may sit from what the file claims. The Apahida
# scans are out by 1.5%; this leaves room for worse while staying tight enough
# that the search cannot wander onto hatching or contour texture.
RESOLUTION_TOLERANCE = 0.15


def analyse(path, expect_res=None, scale=5000):
    """Everything recoverable from the image alone.

    `expect_res` brackets the search for the ground resolution. Left unset it is
    derived from the file's own dpi and the plan's scale, which is what lets the
    same code read a 200 dpi Apahida sheet and a 360 dpi Feleacu one.
    """
    gray = load_gray(path)
    box = detect_neatline(gray)
    if expect_res is None:
        nominal = nominal_resolution(path, scale)
        if nominal is None:
            raise PlateError(
                f"{path} declares no resolution, so the grid search cannot be "
                "bracketed - pass expect_res explicitly"
            )
        expect_res = (nominal * (1 - RESOLUTION_TOLERANCE),
                      nominal * (1 + RESOLUTION_TOLERANCE))
    grid = measure_grid(gray, box, expect_res)
    return {
        "path": path,
        "size": (int(gray.shape[1]), int(gray.shape[0])),
        "frame": box,
        "grid": grid,
        "expect_res": expect_res,
        "rotation_rad": grid_rotation(grid, box),
    }
