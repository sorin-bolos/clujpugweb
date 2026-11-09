#!/usr/bin/env bash
# Installs what the PUZ pipeline needs on a Claude Code cloud machine (Ubuntu 24.04):
# poppler-utils (pdfinfo, pdfimages, pdftoppm), DejaVu fonts for the labels on crops,
# and the Python packages (rasterio's wheels bundle GDAL).
#
# Self-contained, so it can be uploaded as the cloud environment's setup script
# (claude.ai/code, environment settings, "Setup script"); the environment is then
# cached with everything installed. It also works as a SessionStart hook, run from
# the repository. It does nothing on Windows or macOS (the laptop has its own setup),
# skips what is already installed, and always exits 0, so a failed install never
# keeps a session from starting: `tools/puz/puz.sh doctor` then says what is missing.

if [ "$(uname -s)" != "Linux" ] && [ "$1" != "--force" ]; then
  exit 0
fi

# Keep in step with tools/puz/requirements.txt.
PACKAGES="rasterio>=1.4,<2 shapely>=2.0,<3 pyproj>=3.6,<4 pillow>=10.1 numpy>=1.26"

sudo=""
if [ "$(id -u)" != "0" ] && command -v sudo >/dev/null 2>&1; then
  sudo="sudo -n"
fi

if ! command -v pdftoppm >/dev/null 2>&1 || [ ! -d /usr/share/fonts/truetype/dejavu ]; then
  if ! ($sudo apt-get update -qq && DEBIAN_FRONTEND=noninteractive $sudo apt-get install -y -qq \
        poppler-utils fonts-dejavu-core) >/tmp/puz-apt.log 2>&1; then
    echo "puz setup: apt-get failed (see /tmp/puz-apt.log)" >&2
  fi
fi

if ! python3 -c "import numpy, PIL, rasterio, shapely, pyproj" >/dev/null 2>&1; then
  # Ubuntu's own Python refuses system-wide pip installs (PEP 668); the image's may not.
  # shellcheck disable=SC2086
  python3 -m pip install -q $PACKAGES >/tmp/puz-pip.log 2>&1 \
    || python3 -m pip install -q --break-system-packages $PACKAGES >>/tmp/puz-pip.log 2>&1 \
    || echo "puz setup: pip install failed (see /tmp/puz-pip.log)" >&2
fi

# One line saying what is ready (a SessionStart hook's output reaches the session).
python3 - <<'EOF' 2>/dev/null || echo "puz setup: python3 packages missing"
import shutil, rasterio, shapely, pyproj, PIL, numpy
print("PUZ pipeline ready: rasterio %s (GDAL %s), shapely %s, pyproj %s, pillow %s, numpy %s; pdftoppm %s"
      % (rasterio.__version__, rasterio.__gdal_version__, shapely.__version__, pyproj.__version__,
         PIL.__version__, numpy.__version__, "ok" if shutil.which("pdftoppm") else "MISSING"))
EOF
exit 0
