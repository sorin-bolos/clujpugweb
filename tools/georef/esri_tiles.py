"""Serve Esri World Imagery to Map Warper as a custom basemap.

Map Warper's "Add Custom Basemap" only takes Z/X/Y-ordered templates ending in
a file extension - it drops the last three path segments and rebuilds the URL
as base + z/x/y + "." + ext. Esri's tile endpoint is ordered z/y/x with no
extension, so it cannot be pasted in directly.

This answers z/x/y.jpg on localhost with a redirect to the matching Esri tile.
Run it, then paste into Map Warper's custom basemap box:

    http://localhost:8765/{z}/{x}/{y}.jpg

The browser fetches the tiles, so it only has to run on the machine doing the
fitting. Chrome may ask to let mapwarper.net reach the local network; allow it.
"""

import argparse
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ESRI = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}")
TILE = re.compile(r"^/(\d+)/(\d+)/(\d+)\.\w+$")


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        # Chrome's local network access preflight, for a public page reaching
        # localhost.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        m = TILE.match(self.path.split("?")[0])
        if not m:
            self.send_error(404, "expected /{z}/{x}/{y}.jpg")
            return
        z, x, y = m.groups()
        self.send_response(302)
        self._cors()
        self.send_header("Location", ESRI.format(z=z, x=x, y=y))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()
    print(f"Map Warper custom basemap: http://localhost:{args.port}/{{z}}/{{x}}/{{y}}.jpg")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
