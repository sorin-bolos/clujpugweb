"""Turn a plate's printed edge coordinates into ground control points.

The plates are graticule trapezoids: each frame edge follows a meridian or a
parallel, and the corners sit on round values of the Romanian 1:5000 sheet
lattice. Pata's two top corners both read 46 deg 45' 00", and Dezmir's bottom
edge sits on that same parallel - they are adjacent sheets.

That makes the whole job four numbers per plate: the longitude of the left and
right edges and the latitude of the top and bottom ones. Everything else -
where the frame is, how big a pixel is on the ground - comes off the image.
Interior points follow by interpolating in graticule space, which is what a
trapezoidal sheet actually is; the sheet's own projection bends interior
graticule lines by well under a metre across 5 km, far below what a scan of a
2004 blueprint can resolve anyway.

Working in lat/lon also sidesteps the rotation problem. The frame is tilted
against the Stereo 70 grid by the meridian convergence, about 0.9 degrees around
Cluj - enough to throw interior points by 40 m if it were ignored - but in
graticule space the frame is axis-aligned by construction, and Map Warper wants
lat/lon anyway.
"""

import functools
import math
import re

from pyproj import Transformer

# The coordinates printed on the plates are on Pulkovo 1942(58) - the datum
# under Stereo 70 - not WGS84. Around Cluj the two differ by about 121 m east
# and 32 m north, and skipping the conversion puts every overlay that far to the
# north-east. It is the single largest error in the chain: eighty times the
# ground resolution of the scan.
PLATE_CRS = "EPSG:4179"
WGS84_CRS = "EPSG:4326"


@functools.lru_cache(maxsize=4)
def _to_wgs84(src_crs):
    return Transformer.from_crs(src_crs, WGS84_CRS, always_xy=True)

# Sheet lattice for the Romanian 1:5000 series, in arcseconds. A 1:100000 sheet
# is 20' x 30' and halves three times down to this.
LAT_STEP_SEC = 75.0     # 1'15"
LON_STEP_SEC = 112.5    # 1'52.5"

# Lattice origin: the corner of the 1:1000000 sheet row L / column 34, which is
# the one Cluj falls in.
LAT_ORIGIN_DEG = 44.0
LON_ORIGIN_DEG = 18.0

# How far a coordinate read off the plate may sit from a lattice value and still
# be snapped to it. Absorbs a misread digit in the seconds while staying well
# under half a lattice step.
SNAP_TOLERANCE_SEC = 20.0

# Inferred edges get a much tighter tolerance, as a fraction of the lattice
# step, because not every edge is on the lattice to begin with. The meridian
# edges are - Pata spans exactly two lattice steps of longitude - but the sheets
# are cropped top and bottom to fit the paper, and Pata's own latitude span is
# about 1.76 steps. Snapping an inferred edge as freely as a read one would drag
# it 500 m onto a lattice line the sheet was never drawn to.
INFER_SNAP_FRACTION = 0.10


class GeorefError(Exception):
    pass


_DMS = re.compile(
    r"""^\s*(-?\d+(?:[.,]\d+)?)\s*(?:d|deg|°)?          # degrees
         (?:\s*[:\s]?\s*(\d+(?:[.,]\d+)?)\s*(?:m|'|′)?  # minutes
         (?:\s*[:\s]?\s*(\d+(?:[.,]\d+)?)\s*(?:s|"|″)?  # seconds
         )?)?\s*$""",
    re.VERBOSE,
)


def parse_dms(text):
    """Parse a coordinate as printed on a plate.

    Accepts the forms the margins actually use, decimal comma included:
    `46 45 00`, `46°45'00"`, `23 46 52,5`, `46:45:00`, or a plain `46.75`.
    """
    if isinstance(text, (int, float)):
        return float(text)
    m = _DMS.match(str(text))
    if not m:
        raise GeorefError(f"cannot read {text!r} as a coordinate")
    deg, minute, sec = (float(g.replace(",", ".")) if g else 0.0 for g in m.groups())
    sign = -1.0 if deg < 0 else 1.0
    return sign * (abs(deg) + minute / 60.0 + sec / 3600.0)


def format_dms(deg):
    """Render a degree value the way the plates print it."""
    sign = "-" if deg < 0 else ""
    deg = abs(deg)
    d = int(deg)
    rem = (deg - d) * 60
    m = int(rem)
    s = (rem - m) * 60
    return f"{sign}{d}°{m:02d}'{s:04.1f}\""


def snap_to_lattice(deg, axis, tolerance_sec=SNAP_TOLERANCE_SEC):
    """Snap a coordinate to the 1:5000 sheet lattice.

    Frame edges fall on lattice values by construction, so snapping quietly
    repairs a seconds digit lost to a bad scan. Returns the value unchanged, and
    flags it, when it is too far off for the correction to be trustworthy -
    silently moving a coordinate 200 m would be worse than leaving it alone.

    Returns (snapped_degrees, was_snapped, offset_in_arcseconds).
    """
    if axis == "lat":
        step, origin = LAT_STEP_SEC, LAT_ORIGIN_DEG
    elif axis == "lon":
        step, origin = LON_STEP_SEC, LON_ORIGIN_DEG
    else:
        raise ValueError(axis)

    sec = (deg - origin) * 3600.0
    nearest = round(sec / step) * step
    offset = sec - nearest
    if abs(offset) <= tolerance_sec:
        return origin + nearest / 3600.0, True, offset
    return deg, False, offset


class Frame:
    """A plate's frame, with a geographic coordinate on each edge.

    `pixels` is the frame box (left, right, top, bottom) found in the image.
    The edge coordinates are in degrees on the plate's own datum - Pulkovo
    1942(58) unless told otherwise - which is what the sheet is drawn and
    labelled in. Everything handed outward is converted to WGS84.
    """

    def __init__(self, pixels, west, east, north, south, crs=PLATE_CRS):
        self.crs = crs
        self.pixels = tuple(int(v) for v in pixels)
        self.west, self.east = float(west), float(east)
        self.north, self.south = float(north), float(south)
        left, right, top, bottom = self.pixels
        if right <= left or bottom <= top:
            raise GeorefError(f"degenerate frame {self.pixels}")
        if self.east <= self.west or self.north <= self.south:
            raise GeorefError(
                "frame coordinates are not oriented north-up / east-right: "
                f"W={format_dms(self.west)} E={format_dms(self.east)} "
                f"N={format_dms(self.north)} S={format_dms(self.south)}"
            )

    def to_plate_lonlat(self, px, py):
        """Map a pixel to lon/lat on the plate's own datum.

        Interpolating here rather than after the datum shift is the right order:
        the sheet is drawn to this graticule, and it is these lines the frame
        edges follow.
        """
        left, right, top, bottom = self.pixels
        u = (px - left) / (right - left)
        v = (py - top) / (bottom - top)
        return (
            self.west + u * (self.east - self.west),
            self.north - v * (self.north - self.south),
        )

    def to_lonlat(self, px, py):
        """Map a pixel to WGS84 lon/lat, ready for Map Warper or Google Maps."""
        lon, lat = self.to_plate_lonlat(px, py)
        return _to_wgs84(self.crs).transform(lon, lat)

    def datum_shift(self):
        """The datum correction at the frame centre, in metres east and north.

        Reported so the size of it is visible rather than buried.
        """
        left, right, top, bottom = self.pixels
        cx, cy = (left + right) / 2, (top + bottom) / 2
        lon, lat = self.to_plate_lonlat(cx, cy)
        wlon, wlat = _to_wgs84(self.crs).transform(lon, lat)
        return (
            (wlon - lon) * 111320.0 * math.cos(math.radians(lat)),
            (wlat - lat) * 111132.0,
        )

    def pixels_lrtb_box(self):
        """The frame as a PIL crop box (left, top, right, bottom)."""
        left, right, top, bottom = self.pixels
        return (left, top, right, bottom)

    def resolution(self):
        """Ground resolution implied by the frame, in metres per pixel (x, y).

        Independent of anything measured off the ticks, so comparing the two is
        a real check rather than a restatement.
        """
        left, right, top, bottom = self.pixels
        mid_lat = math.radians(0.5 * (self.north + self.south))
        lon_m = (self.east - self.west) * 111320.0 * math.cos(mid_lat)
        lat_m = (self.north - self.south) * 111132.0
        return lon_m / (right - left), lat_m / (bottom - top)

    def gcps(self, nx=4, ny=4, inset=0.0):
        """Ground control points spread evenly over the frame.

        Map Warper fits its own polynomial, so it wants points spread over the
        sheet rather than only at the corners. `inset` pulls them in from the
        frame edge as a fraction of the frame, which helps when the outermost
        pixels of a scan are unreliable.
        """
        if nx < 2 or ny < 2:
            raise GeorefError("need at least a 2x2 grid of control points")
        left, right, top, bottom = self.pixels
        pts = []
        for j in range(ny):
            for i in range(nx):
                u = inset + (1 - 2 * inset) * i / (nx - 1)
                v = inset + (1 - 2 * inset) * j / (ny - 1)
                px = left + u * (right - left)
                py = top + v * (bottom - top)
                lon, lat = self.to_lonlat(px, py)
                pts.append({"x": round(px, 2), "y": round(py, 2),
                            "lon": round(lon, 8), "lat": round(lat, 8)})
        return pts

    def bounds(self):
        """WGS84 bounds, in the shape Scripts.js wants.

        The datum shift bends the rectangle very slightly out of square - by
        about a tenth of a metre across a sheet - so the corners are taken and
        the extremes kept, rather than assuming two corners describe it.
        """
        left, right, top, bottom = self.pixels
        corners = [self.to_lonlat(x, y)
                   for x in (left, right) for y in (top, bottom)]
        lons = [lon for lon, _ in corners]
        lats = [lat for _, lat in corners]
        return {"west": min(lons), "south": min(lats),
                "east": max(lons), "north": max(lats)}

    def plate_bounds(self):
        """Bounds on the plate's own datum, as printed on the sheet."""
        return {"west": self.west, "south": self.south,
                "east": self.east, "north": self.north}


STEREO70_CRS = "EPSG:3844"


class GridFrame:
    """A plate placed from its Stereo 70 kilometre grid rather than its corners.

    The 2005 Feleacu sheets print no graticule coordinates, but `sat_Feleacu`
    ticks its margins with grid values - `96,0` and `96,5` along the top for
    easting, `81,0` and `80,5` down the right for northing. One labelled tick on
    each axis fixes the plate absolutely, because the ticks are a 500 m lattice
    and the spacing between them is already measured off the image.

    Working straight in Stereo 70 also gets the sheet's rotation for free.
    The grid is what the plate is drawn to, so its axes are the image's axes;
    the roughly 0.9° tilt against the graticule falls out of the projection
    rather than having to be modelled.
    """

    def __init__(self, pixels, res_x, res_y, easting, at_x, northing, at_y):
        self.pixels = tuple(int(v) for v in pixels)
        self.res_x, self.res_y = float(res_x), float(res_y)
        self.easting, self.at_x = float(easting), float(at_x)
        self.northing, self.at_y = float(northing), float(at_y)
        self.crs = STEREO70_CRS
        if self.res_x <= 0 or self.res_y <= 0:
            raise GeorefError("resolution must be positive")

    def to_stereo70(self, px, py):
        return (self.easting + (px - self.at_x) * self.res_x,
                self.northing - (py - self.at_y) * self.res_y)

    def to_lonlat(self, px, py):
        return _to_wgs84(self.crs).transform(*self.to_stereo70(px, py))

    def pixels_lrtb_box(self):
        left, right, top, bottom = self.pixels
        return (left, top, right, bottom)

    def gcps(self, nx=4, ny=4, inset=0.0):
        if nx < 2 or ny < 2:
            raise GeorefError("need at least a 2x2 grid of control points")
        left, right, top, bottom = self.pixels
        pts = []
        for j in range(ny):
            for i in range(nx):
                u = inset + (1 - 2 * inset) * i / (nx - 1)
                v = inset + (1 - 2 * inset) * j / (ny - 1)
                px = left + u * (right - left)
                py = top + v * (bottom - top)
                lon, lat = self.to_lonlat(px, py)
                pts.append({"x": round(px, 2), "y": round(py, 2),
                            "lon": round(lon, 8), "lat": round(lat, 8)})
        return pts

    def bounds(self):
        left, right, top, bottom = self.pixels
        corners = [self.to_lonlat(x, y)
                   for x in (left, right) for y in (top, bottom)]
        lons = [lon for lon, _ in corners]
        lats = [lat for _, lat in corners]
        return {"west": min(lons), "south": min(lats),
                "east": max(lons), "north": max(lats)}


# How far the detected phase may pull the anchor before the correction is
# refused. The phase comes from a circular mean over the whole margin, and the
# tick labels sit between the ticks, so on a busy margin it can land between two
# of them rather than on one. A snap that large is a sign the phase is wrong,
# not that the reading was: accepting it would move the plate a couple of
# hundred metres without saying so.
MAX_SNAP_FRACTION = 0.20


def _snap_to_tick(value_px, phase, period, origin):
    """Nudge a roughly-placed anchor onto the nearest tick actually detected.

    Returns (position, correction, refused). A refused snap keeps the position
    as read and leaves the caller to say so.
    """
    if phase is None or not period:
        return float(value_px), None, False
    first = origin + phase
    k = round((value_px - first) / period)
    snapped = first + k * period
    delta = snapped - value_px
    if abs(delta) > MAX_SNAP_FRACTION * period:
        return float(value_px), delta, True
    return snapped, delta, False


def build_grid_frame(analysis, anchor):
    """Place a plate from one labelled grid tick on each axis.

    `anchor` carries `easting`/`at_x` and `northing`/`at_y` - the value printed
    beside a tick, and roughly where along the margin that tick sits.
    """
    grid = analysis["grid"]
    res_x = anchor.get("res_x") or grid["res_x_m_px"] or grid["res_y_m_px"]
    res_y = anchor.get("res_y") or grid["res_y_m_px"] or grid["res_x_m_px"]
    if res_x is None:
        raise GeorefError(
            "no kilometre grid could be measured, so there is nothing to anchor "
            "against - this plate needs a control point instead"
        )

    for key in ("easting", "at_x", "northing", "at_y"):
        if anchor.get(key) is None:
            raise GeorefError(f"grid anchor is missing {key}")

    notes = []
    if grid["res_x_m_px"] is None or grid["res_y_m_px"] is None:
        notes.append("only one axis of the grid was measurable; assuming square pixels")

    axes = (
        ("easting", "at_x", ("top", "bottom"), grid["period_x_px"] or grid["period_y_px"]),
        ("northing", "at_y", ("left", "right"), grid["period_y_px"] or grid["period_x_px"]),
    )
    placed = {}
    snap = anchor.get("snap", True)
    if not snap:
        notes.append("anchor taken as given; tick snapping disabled")
    for label, key, edge_names, period in axes:
        edge = next((grid["edges"][e] for e in edge_names if e in grid["edges"]), {})
        pos, delta, refused = _snap_to_tick(
            anchor[key], edge.get("phase_px") if snap else None,
            period, edge.get("origin", 0))
        placed[key] = pos
        if refused:
            notes.append(
                f"{label} anchor left where you put it: the detected tick phase "
                f"wanted to move it {delta:+.0f} px ({abs(delta) * (grid['res_x_m_px'] or 0):.0f} m), "
                "which is too far to be a correction - check the anchor against "
                "the preview"
            )
        elif delta is not None and abs(delta) > 0.5:
            notes.append(f"{label} anchor snapped {delta:+.0f} px onto the nearest tick")

    frame = GridFrame(analysis["frame"], res_x, res_y,
                      anchor["easting"], placed["at_x"],
                      anchor["northing"], placed["at_y"])
    return frame, notes


def build_frame(analysis, edges, snap=True, crs=PLATE_CRS):
    """Assemble a Frame from image analysis plus whatever edges could be read.

    `edges` maps any of west/east/north/south to a printed coordinate. A missing
    edge is filled in from the one opposite it, using the scale measured off the
    kilometre grid, and then snapped to the sheet lattice - which is what makes
    a plate with only one legible corner usable.

    Returns (frame, notes) where notes records what was inferred rather than
    read, so it can be reported rather than hidden.
    """
    left, right, top, bottom = analysis["frame"]
    grid = analysis["grid"]
    notes = []

    have = {}
    for key in ("west", "east", "north", "south"):
        if edges.get(key) not in (None, ""):
            have[key] = parse_dms(edges[key])

    if not have:
        raise GeorefError(
            "no edge coordinates given; read at least one corner off the plate"
        )

    def span_deg(axis):
        """Frame extent in degrees, from the measured ground resolution.

        The vertical scale reads off the kilometre grid on every plate seen so
        far; the horizontal one often does not, because the bottom margin
        carries the sheet nomenclature and neighbouring place names. When it is
        missing the vertical scale stands in for it. The scans are anisotropic
        by about 2%, but a longitude lattice step is some 2.4 km, so 2% of a
        sheet width stays far inside the snap that follows.
        """
        if axis == "lat":
            res = grid["res_y_m_px"]
            if res is None:
                raise GeorefError(
                    "the vertical scale could not be measured off the kilometre "
                    "grid, so a missing edge cannot be inferred - read the "
                    "opposite corner off the plate and pass it in"
                )
            return (bottom - top) * res / 111132.0

        res = grid["res_x_m_px"] or grid["res_y_m_px"]
        if res is None:
            raise GeorefError(
                "no scale could be measured off the kilometre grid, so a missing "
                "edge cannot be inferred - read the opposite corner off the plate "
                "and pass it in"
            )
        if grid["res_x_m_px"] is None:
            notes.append(
                "horizontal scale unreadable in the margins; using the vertical "
                "one to infer longitude"
            )
        lat = have.get("north", have.get("south"))
        if lat is None:
            raise GeorefError("need a latitude before longitude span can be scaled")
        return (right - left) * res / (111320.0 * math.cos(math.radians(lat)))

    # Snap what was actually read, before anything is derived from it.
    if snap:
        for key in list(have):
            axis = "lon" if key in ("west", "east") else "lat"
            value, ok, off = snap_to_lattice(have[key], axis)
            if ok and abs(off) > 1e-6:
                notes.append(f"{key} snapped {off:+.1f}\" to the sheet lattice")
                have[key] = value
            elif not ok:
                notes.append(
                    f"{key} reads {format_dms(have[key])}, {off:+.1f}\" off the sheet "
                    "lattice - check the digits"
                )

    # Fill each missing edge from its opposite, using the measured scale.
    inferred = set()
    for missing, present, axis, sign in (
        ("east", "west", "lon", +1), ("west", "east", "lon", -1),
        ("north", "south", "lat", +1), ("south", "north", "lat", -1),
    ):
        if missing in have or present not in have:
            continue
        value = have[present] + sign * span_deg(axis)
        step = LON_STEP_SEC if axis == "lon" else LAT_STEP_SEC
        snapped, ok, off = snap_to_lattice(value, axis, INFER_SNAP_FRACTION * step)
        have[missing] = snapped if ok else value
        inferred.add(missing)
        notes.append(
            f"{missing} not read; inferred {format_dms(have[missing])} from {present} "
            f"via the measured scale"
            + (f", snapped {off:+.1f}\" to the sheet lattice" if ok else "")
        )

    missing = [k for k in ("west", "east", "north", "south") if k not in have]
    if missing:
        raise GeorefError(f"could not determine {', '.join(missing)}")

    frame = Frame((left, right, top, bottom),
                  have["west"], have["east"], have["north"], have["south"], crs)

    # The frame implies a ground resolution; the ticks measured one directly.
    # They come from independent evidence, so a disagreement is worth surfacing.
    res_x, res_y = frame.resolution()
    for label, implied, measured in (
        ("x", res_x, grid["res_x_m_px"]), ("y", res_y, grid["res_y_m_px"]),
    ):
        if measured is None:
            continue
        drift = abs(implied - measured) / measured
        if drift > 0.02:
            notes.append(
                f"{label} scale from the frame ({implied:.4f} m/px) disagrees with "
                f"the kilometre grid ({measured:.4f} m/px) by {drift*100:.1f}% - "
                "one of the edge coordinates is probably misread"
            )
    return frame, notes
