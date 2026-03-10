import sys
from PyPDF2 import PdfReader, PdfWriter

PDF_PATH = r"C:\Repositories\clujpugweb\ClujPugWeb\docs\2026\Regulament-PUG-actualizat_2024.pdf"
OUT_DIR = r"C:\Repositories\clujpugweb\ClujPugWeb\wwwroot\Documente"
OFFSET = 6

# (filename_without_ext, toc_start_page)
# Sorted by toc_start_page so we can compute end pages automatically
utrs = [
    # ("M1", 20),  # DONE
    # ("M2", 28),  # DONE
    # ("M3", 36),  # DONE
    # ("M4", 43),  # DONE
    ("Is_A", 50),
    ("Liu", 57),
    ("Lip", 65),
    ("Lir", 72),
    ("Lid", 80),
    ("Lc_A", 87),
    ("Lc", 95),
    ("Lcs", 104),
    ("Ei", 111),
    ("EL", 117),
    ("Em", 123),
    ("Ec", 130),
    ("Et", 135),
    ("G_p", 143),
    ("G_c", 148),
    ("G_d", 152),
    ("G_t", 155),
    ("ED", 160),
    ("Sp_TDS_MApN", 165),
    ("Tr", 170),
    ("Ta_UTa", 173),
    ("Tf", 178),
    ("A", 182),
    ("AL", 186),
    ("Aapp", 190),
    ("Va", 196),
    ("Vs", 201),
    ("Ve", 206),
    ("VPr", 210),
    ("Vp", 214),
    ("ZCP_C1", 218),
    ("ZCP_C2", 226),
    ("ZCP_M1", 234),
    ("ZCP_M2", 243),
    ("ZCP_M3", 251),
    ("ZCP_M4", 259),
    ("ZCP_Is_A", 267),
    ("ZCP_Liu", 274),
    ("ZCP_L_A", 282),
    ("ZCP_G_c", 288),
    ("ZCP_Sp_ZCP_TDS_MApN", 293),
    ("ZCP_Va", 299),
    ("ZCP_Vt", 304),
    ("ZCP_Vs", 309),
    ("ZCP_Ve", 314),
    ("ZCP_RiM", 318),
    ("RiM", 333),
    ("RrM1", 340),
    ("RrM2", 348),
    ("ZCP_Et", 352),
    ("RrM3", 356),
    ("RrM4", 364),
    ("RrEm", 372),
    ("RrEt", 379),
    ("UM1", 387),
    ("UM2", 395),
    ("UM3", 403),
    ("UM4", 411),
    ("UIs_A", 419),
    ("ULiu", 424),
    ("ULi_c", 432),
    ("ULc", 441),
    ("ULid", 449),
    ("UEc", 456),
    ("UEt", 462),
    ("UEi", 469),
    ("UEm", 475),
    ("UED", 481),
    ("UG_c", 486),
    ("UG_cmid", 491),
    ("UVa", 495),
    ("UVs", 500),
    ("UVt", 505),
    ("TDA", 510),
    ("TDA_L", 514),
    ("TDF", 517),
]

reader = PdfReader(PDF_PATH)
total_pages = len(reader.pages)
print(f"Source PDF has {total_pages} pages")

for i, (name, toc_start) in enumerate(utrs):
    # End page = next UTR start - 1, or last page of PDF for the final entry
    if i + 1 < len(utrs):
        toc_end = utrs[i + 1][1] - 1
    else:
        toc_end = total_pages - OFFSET  # last UTR goes to end of document

    # Apply offset and convert to 0-based
    pdf_start = toc_start + OFFSET - 1  # 0-based
    pdf_end = toc_end + OFFSET - 1      # 0-based, inclusive

    # Clamp to valid range
    pdf_end = min(pdf_end, total_pages - 1)

    out_path = f"{OUT_DIR}\\{name}.pdf"

    writer = PdfWriter()
    for p in range(pdf_start, pdf_end + 1):
        writer.add_page(reader.pages[p])

    with open(out_path, "wb") as f:
        writer.write(f)

    print(f"  {name}.pdf  pages {toc_start}-{toc_end} (PDF {pdf_start+1}-{pdf_end+1}, {pdf_end - pdf_start + 1} pages)")

print(f"\nDone. Extracted {len(utrs)} UTR documents.")
