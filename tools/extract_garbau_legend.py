"""Crop the legend symbols for comuna Garbau off the 2017 reglementari plates.

The base set comes from the Garbau plate (3.1); the entries that only appear on
the other localities' plates are taken from those plates instead. Every crop is
40pt wide so the line weights stay consistent between symbols.
"""
import os
import fitz

SRC = r"C:\Repositories\clujpugweb\puguri\Garbau"
OUT = r"C:\Repositories\clujpugweb\ClujPugWeb\wwwroot\Images\Legend\Garbau"
DPI = 600
WIDTH = 40.0  # pt, measured from the label's left edge minus 44.7

GARBAU = "GARBAU_dec 2017_reglementari.pdf"
CORNESTI = "CORNESTI_dec 2017_reglementari.pdf"
NADASELU = "NADASELU_dec 2017_reglementari.pdf"
TUREA = "TUREA_dec_2017_reglementari.pdf"

# (name, pdf, label_x0, symbol_top, symbol_bottom, window_height)
SYMBOLS = [
    # Limite
    ("LimitaIntravilan1990",      GARBAU,   302.2, 1210.72, 1211.20, 11.5),
    ("LimitaIntravilan2010",      GARBAU,   302.2, 1225.96, 1228.36, 11.5),
    ("LimitaUat",                 GARBAU,   302.2, 1240.24, 1244.56, 11.5),
    ("LimitaRezervatieNaturala",  TUREA,   1333.84, 139.40,  143.60, 11.5),
    # Zonificare functionala
    ("ZonaCentrala",              GARBAU,   302.2, 1293.40, 1303.00, 11.0),
    ("ZonaLocuinte",              GARBAU,   302.2, 1304.44, 1314.04, 11.0),
    ("ZonaAgricolaSilvica",       GARBAU,   302.2, 1315.48, 1325.08, 11.0),
    ("ZonaIndustriala",           GARBAU,   302.2, 1326.52, 1336.24, 11.0),
    ("ZonaGospodarieComunala",    GARBAU,   302.2, 1337.56, 1347.28, 11.0),
    ("ZonaSportAgrement",         GARBAU,   302.2, 1348.72, 1358.32, 11.0),
    ("ZonaCaiRutiere",            GARBAU,   302.2, 1359.76, 1369.36, 11.0),
    ("ZonaCaiFeroviare",          GARBAU,   302.2, 1370.80, 1380.40, 11.0),
    ("ZonaPlantatiiProtectie",    GARBAU,   302.2, 1381.84, 1391.44, 11.0),
    ("Ape",                       GARBAU,   302.2, 1392.88, 1402.48, 11.0),
    ("ZonaEchipamenteEdilitare",  NADASELU, 146.81, 1139.04, 1148.64, 11.0),
    ("IndicativUtr",              GARBAU,   302.2, 1405.48, 1418.80, 15.3),
    # Zone de protectie / interdictie
    ("ProtectiePatrimoniu",       GARBAU,   302.2, 1475.44, 1478.80, 11.5),
    ("ProtectieSanitara",         GARBAU,   302.2, 1496.08, 1497.16, 11.5),
    ("ProtectieConstructii",      GARBAU,   302.2, 1506.64, 1509.04, 11.5),
    ("ProtectieRiscTehnologic",   CORNESTI, 201.74,  423.72,  425.04, 11.5),
    ("InterdictieTemporara",      GARBAU,   302.2, 1525.72, 1535.32, 11.0),
    ("InterdictieDefinitiva",     GARBAU,   302.2, 1537.24, 1546.84, 11.0),
    # Drumuri
    ("AutostradaTransilvania",    NADASELU, 146.81, 1384.60, 1392.88, 11.5),
    ("DrumNational",              NADASELU, 146.81, 1397.44, 1401.76, 11.5),
    ("DrumJudetean",              GARBAU,   302.2, 1596.04, 1600.36, 11.5),
    ("DrumComunal",               GARBAU,   302.2, 1606.00, 1610.32, 11.5),
    ("StraziModernizare",         GARBAU,   302.2, 1616.44, 1619.80, 11.5),
    ("StraziTraseeNoi",           GARBAU,   302.2, 1628.92, 1632.28, 11.5),
    # Nadaselu and Turea draw this one as a bold dashed line instead
    ("StraziTraseeNoiPunctat",    TUREA,   1333.84,  512.28,  516.60, 11.5),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    pages = {}
    for name, pdf, label_x0, top, bottom, height in SYMBOLS:
        if pdf not in pages:
            pages[pdf] = fitz.open(os.path.join(SRC, pdf))[0]
        page = pages[pdf]
        x0 = label_x0 - 44.7
        cy = (top + bottom) / 2.0
        clip = fitz.Rect(x0, cy - height / 2.0, x0 + WIDTH, cy + height / 2.0)
        pix = page.get_pixmap(dpi=DPI, clip=clip)
        path = os.path.join(OUT, name + ".png")
        pix.save(path)
        print(f"{name:28s} {pix.width:4d}x{pix.height:3d}  {os.path.basename(pdf)}")


if __name__ == "__main__":
    main()
