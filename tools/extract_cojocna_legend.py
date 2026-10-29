"""Crop the legend symbols for comuna Cojocna off the 1999 "Regulament" plates.

The Cojocna plates carry their legend in three places instead of one block: a
small LEGENDA box with the three boundary lines, a "CAI DE COMUNICATIE SI
TRANSPORT" box with the road symbols, and the colour-coded "INDICATIV U.T.R."
column of the bilant table, which is what the zone colours on the map mean.
Symbols are taken from whichever plate scanned best - Straja-Huci is 5742 px
wide, Cojocna 3093, the other five only 1786 - so the shared boundary and road
symbols come off Straja-Huci and the zone colours off Cojocna, which is the only
plate that carries all eight zones.

Line symbols keep their aspect ratio; colour swatches are stretched to a flat
block because that is all they are on the plate.
"""
import os
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

SRC = r"C:\Repositories\clujpugweb\puguri\Cojocna"
OUT = r"C:\Repositories\clujpugweb\ClujPugWeb\wwwroot\Images\Legend\Cojocna"

COJOCNA = "Cojocna.png"
STRAJA = "StrajaHuci.png"

BLOCK = (240, 104)   # 4x the CSS box, flat colour so the stretch does not show
LINE_WIDTH = 240     # line symbols scale to this width, height follows

# (name, plate, x0, y0, x1, y1, mode)
SYMBOLS = [
    # Limite - LEGENDA box, identical on all seven plates
    ("LimitaIntravilanStabilit",   STRAJA, 3746, 1798, 3812, 1810, "line"),
    ("LimitaIntravilanActualizat", STRAJA, 3746, 1831, 3812, 1850, "line"),
    ("LimitaUtr",                  STRAJA, 3765, 1885, 3792, 1920, "line"),
    # Cai de comunicatie si transport
    ("DrumJudetean",               COJOCNA, 2533,  895, 2579,  905, "line"),
    ("DrumComunal",                STRAJA,  4919, 1129, 5008, 1150, "line"),
    ("StraziUlite",                STRAJA,  4919, 1161, 5008, 1176, "line"),
    # Zonificare functionala - colour column of the bilant table. The column
    # carries the U.T.R. code printed over the fill, so each swatch is a strip
    # of the band that the lettering misses, stretched back out to a block.
    ("ZonaCentrala",               COJOCNA, 2313,  359, 2355,  363, "block"),
    ("ZonaVerdeCentru",            COJOCNA, 2313,  519, 2355,  528, "block"),
    ("ZonaLocuinte",               COJOCNA, 2313,  544, 2355,  555, "block"),
    ("LocuinteInterdictie",        COJOCNA, 2310,  631, 2358,  634, "block"),
    ("ZonaProductieAgricola",      COJOCNA, 2313,  663, 2355,  666, "block"),
    ("ZonaProductieIndustriala",   COJOCNA, 2313,  719, 2355,  722, "block"),
    ("ZonaGospodarieComunala",     COJOCNA, 2340,  761, 2355,  778, "block"),
    ("ZonaVerde",                  COJOCNA, 2313,  831, 2355,  835, "block"),
    ("ZonaBalneara",               COJOCNA, 2313,  864, 2355,  875, "block"),
    # Thin coloured lines further down the same column
    ("CaleFerata",                 COJOCNA, 2342,  919, 2356,  922, "line"),
    ("ZonaApe",                    COJOCNA, 2316,  929, 2356,  933, "line"),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    plates = {}
    for name, plate, x0, y0, x1, y1, mode in SYMBOLS:
        if plate not in plates:
            plates[plate] = Image.open(os.path.join(SRC, plate)).convert("RGB")
        crop = plates[plate].crop((x0, y0, x1, y1))
        if mode == "block":
            out = crop.resize(BLOCK, Image.LANCZOS)
        else:
            scale = LINE_WIDTH / crop.width
            out = crop.resize((LINE_WIDTH, max(1, round(crop.height * scale))),
                              Image.LANCZOS)
        path = os.path.join(OUT, name + ".png")
        out.save(path)
        print(f"{name:28s} {out.width:4d}x{out.height:3d}  {plate}")


if __name__ == "__main__":
    main()
