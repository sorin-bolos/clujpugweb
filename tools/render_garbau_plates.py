"""Render the Garbau reglementari plates as whole-sheet images.

`cli.py extract` is no use here: each sheet arrives as six or seven overlapping
rasters, not one, so the plate only exists once the page is composed. The tiles
are placed at ~293 dpi on the page, so rendering at that dpi is 1:1 with the
scan - no upsampling, nothing thrown away.

Writes the full-res plate plus an 8000px copy, which is what gets uploaded.
"""
import os
import fitz
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

SRC = r"puguri\Garbau"
OUT = "export"
DPI = 293          # measured off the embedded tiles
MAX_DIM = 8000     # upload copy
QUALITY = 88

PLATES = [
    ("3.1", "Garbau",   "GARBAU_dec 2017_reglementari.pdf"),
    ("3.2", "Cornesti", "CORNESTI_dec 2017_reglementari.pdf"),
    ("3.3", "Nadaselu", "NADASELU_dec 2017_reglementari.pdf"),
    ("3.4", "Turea",    "TUREA_dec_2017_reglementari.pdf"),
    ("3.5", "Vistea",   "VISTEA_dec 2017_reglementari.pdf"),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    for number, locality, pdf in PLATES:
        page = fitz.open(os.path.join(SRC, pdf))[0]
        pix = page.get_pixmap(dpi=DPI)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        stem = f"{number}-Reglementari-sat-{locality}"
        full = os.path.join(OUT, stem + ".jpg")
        image.save(full, quality=QUALITY, optimize=True)
        print(f"{full}  {image.width}x{image.height}  "
              f"{os.path.getsize(full)/1e6:.1f} MB")

        scale = min(1.0, MAX_DIM / max(image.size))
        if scale < 1.0:
            small = image.resize(
                (round(image.width * scale), round(image.height * scale)),
                Image.LANCZOS)
            out = os.path.join(OUT, f"{stem}-{MAX_DIM}.jpg")
            small.save(out, quality=QUALITY, optimize=True)
            print(f"{out}  {small.width}x{small.height}  "
                  f"{os.path.getsize(out)/1e6:.1f} MB")


if __name__ == "__main__":
    main()
