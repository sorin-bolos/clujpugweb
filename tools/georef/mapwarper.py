"""A small Map Warper API client, covering just the upload-and-rectify path.

Map Warper stays the tile host - nothing about how the site serves overlays
changes. What goes away is the manual fitting: the control points are computed
from the plate's printed coordinates and posted, rather than clicked in one at a
time against a basemap.

Credentials come from the environment, MAPWARPER_EMAIL and MAPWARPER_PASSWORD,
so they stay out of the repository and out of shell history.
"""

import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://mapwarper.net"

# Rectifying a large plate takes a while server-side.
POLL_INTERVAL_S = 5
POLL_TIMEOUT_S = 900


class MapWarperError(Exception):
    pass


class MapWarper:
    def __init__(self, base_url=BASE_URL, timeout=120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.user_id = None
        self.token = None

    # -- plumbing ---------------------------------------------------------

    def _raw(self, method, path, body=None, params=None):
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        if self.token:
            req.add_header("X-User-Id", str(self.user_id))
            req.add_header("X-User-Token", self.token)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:600]
            raise MapWarperError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise MapWarperError(f"{method} {path} failed: {exc.reason}") from exc

    def _request(self, method, path, body=None, params=None):
        raw = self._raw(method, path, body, params)
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MapWarperError(f"{method} {path} returned non-JSON: {raw[:300]}") from exc

    # -- session ----------------------------------------------------------

    def sign_in(self, email=None, password=None):
        email = email or os.environ.get("MAPWARPER_EMAIL")
        password = password or os.environ.get("MAPWARPER_PASSWORD")
        if not email or not password:
            raise MapWarperError(
                "set MAPWARPER_EMAIL and MAPWARPER_PASSWORD in the environment"
            )
        payload = {"user": {"email": email, "password": password}}
        result = self._request("POST", "/api/v1/auth/sign_in.json", payload)
        token = (result.get("meta") or {}).get("auth_token")
        user_id = (result.get("data") or {}).get("id")
        if not token or not user_id:
            raise MapWarperError(f"sign-in returned no token: {result}")
        self.token, self.user_id = token, user_id
        return user_id

    # -- maps -------------------------------------------------------------

    # Uploads go up as base64 inside a JSON body, which inflates them by a third.
    # The raw plates run to 95 MB, so warn before pushing one at full size.
    LARGE_UPLOAD_BYTES = 40 * 1024 * 1024

    def create_map(self, image_path, title, **attributes):
        """Upload a plate and return its map id."""
        size = os.path.getsize(image_path)
        if size > self.LARGE_UPLOAD_BYTES:
            print(
                f"  warning: {os.path.basename(image_path)} is {size/1e6:.0f} MB and "
                f"goes up as ~{size*4/3/1e6:.0f} MB of base64. If this times out, "
                "point the plate's \"upload_file\" at a downsampled copy - the frame "
                "and grid are still measured on the original and the control points "
                "are rescaled to match."
            )
        mime = mimetypes.guess_type(image_path)[0] or "image/tiff"
        with open(image_path, "rb") as fh:
            encoded = base64.b64encode(fh.read()).decode()
        attrs = {
            "title": title,
            "upload": f"data:{mime};base64,{encoded}",
            "upload_file_name": os.path.basename(image_path),
        }
        attrs.update({k: v for k, v in attributes.items() if v is not None})
        result = self._request(
            "POST", "/api/v1/maps", {"data": {"type": "maps", "attributes": attrs}}
        )
        map_id = (result.get("data") or {}).get("id")
        if not map_id:
            raise MapWarperError(f"upload returned no map id: {result}")
        return map_id

    def get_map(self, map_id):
        return self._request("GET", f"/api/v1/maps/{map_id}")

    def add_gcps(self, map_id, gcps):
        """Post control points in one call.

        Map Warper refuses a duplicate point rather than replacing it, so a
        re-run against a map that already has points needs them cleared first.
        """
        payload = {
            "gcps": [
                {"mapid": int(map_id), "x": p["x"], "y": p["y"],
                 "lat": str(p["lat"]), "lon": str(p["lon"])}
                for p in gcps
            ]
        }
        return self._request("POST", "/api/v1/gcps/add_many", payload)

    def list_gcps(self, map_id):
        result = self._request("GET", f"/api/v1/maps/{map_id}/gcps")
        return result.get("data", [])

    def delete_gcp(self, gcp_id):
        return self._request("DELETE", f"/api/v1/gcps/{gcp_id}")

    def clear_gcps(self, map_id):
        removed = 0
        for gcp in self.list_gcps(map_id):
            self.delete_gcp(gcp["id"])
            removed += 1
        return removed

    def rectify(self, map_id, resample="cubic", transform="p1"):
        """Warp the map from its control points.

        A first-order polynomial is the right fit here: the control points come
        from a regular graticule, so a higher order would only chase scanning
        noise. Cubic resampling because these plates are line drawings and
        nearest-neighbour leaves the contours ragged.
        """
        params = {"format": "json", "use_mask": "false",
                  "resample_options": resample, "transform_options": transform}
        return self._request(
            "PATCH", f"/api/v1/maps/{map_id}/rectify", body={}, params=params
        )

    def status(self, map_id):
        """One of unloaded, loading, available, warping, warped, published.

        This endpoint answers in plain text rather than JSON, unlike the rest of
        the API.
        """
        raw = self._raw("GET", f"/api/v1/maps/{map_id}/status").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip('"')
        if isinstance(parsed, dict):
            attrs = (parsed.get("data") or {}).get("attributes", parsed)
            return attrs.get("status", raw) if isinstance(attrs, dict) else raw
        return str(parsed)

    def wait_until_warped(self, map_id, timeout=POLL_TIMEOUT_S, interval=POLL_INTERVAL_S):
        """Block until the server reports the map warped."""
        deadline = time.time() + timeout
        state = None
        while time.time() < deadline:
            state = self.status(map_id)
            if state in ("warped", "published"):
                return state
            time.sleep(interval)
        raise MapWarperError(
            f"map {map_id} was still '{state}' after {timeout}s; it may still be "
            f"warping - check {self.base_url}/maps/{map_id}"
        )

    def bbox(self, map_id):
        """The warped extent, as Scripts.js wants it.

        Map Warper reports bbox as west,south,east,north.
        """
        attrs = (self.get_map(map_id).get("data") or {}).get("attributes", {})
        raw = attrs.get("bbox")
        if not raw:
            raise MapWarperError(f"map {map_id} has no bbox yet")
        west, south, east, north = (float(v) for v in str(raw).split(","))
        return {"west": west, "south": south, "east": east, "north": north}

    def tile_url(self, map_id):
        return f"{self.base_url}/maps/tile/{map_id}/{{z}}/{{x}}/{{y}}.png"
