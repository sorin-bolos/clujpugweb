import argparse
from PyPDF2 import PdfReader, PdfWriter


def extract_pages(input_path, start_page, end_page, output_path):
    reader = PdfReader(input_path)
    writer = PdfWriter()

    total = len(reader.pages)
    if start_page < 0 or end_page >= total or start_page > end_page:
        raise ValueError(f"Invalid page range {start_page}-{end_page}. PDF has {total} pages (0-indexed).")

    for i in range(start_page, end_page + 1):
        writer.add_page(reader.pages[i])

    with open(output_path, "wb") as f:
        writer.write(f)

    print(f"Extracted pages {start_page}-{end_page} to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract a page range from a PDF.")
    parser.add_argument("input", help="Path to the source PDF")
    parser.add_argument("start", type=int, help="Start page index (0-based)")
    parser.add_argument("end", type=int, help="End page index (0-based, inclusive)")
    parser.add_argument("output", help="Path for the output PDF")
    args = parser.parse_args()

    extract_pages(args.input, args.start, args.end, args.output)
