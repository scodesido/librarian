import re
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader, PdfWriter


@dataclass
class PdfBlob:
    start_page: int  # 1-indexed inclusive
    end_page: int  # 1-indexed inclusive
    pdf_bytes: bytes


@dataclass
class TextBlob:
    start_char: int
    end_char: int
    text: str


def chunk_pdf(pdf_bytes: bytes, pages_per_blob: int) -> list[PdfBlob]:
    reader = PdfReader(BytesIO(pdf_bytes))
    n_pages = len(reader.pages)
    blobs: list[PdfBlob] = []
    for start_idx in range(0, n_pages, pages_per_blob):
        end_idx = min(start_idx + pages_per_blob, n_pages)
        writer = PdfWriter()
        for i in range(start_idx, end_idx):
            writer.add_page(reader.pages[i])
        out = BytesIO()
        writer.write(out)
        blobs.append(
            PdfBlob(
                start_page=start_idx + 1,
                end_page=end_idx,
                pdf_bytes=out.getvalue(),
            )
        )
    return blobs


def chunk_text(text: str, words_per_blob: int) -> list[TextBlob]:
    matches = list(re.finditer(r"\S+", text))
    blobs: list[TextBlob] = []
    for i in range(0, len(matches), words_per_blob):
        group = matches[i : i + words_per_blob]
        if not group:
            continue
        start = group[0].start()
        end = group[-1].end()
        blobs.append(TextBlob(start_char=start, end_char=end, text=text[start:end]))
    return blobs
