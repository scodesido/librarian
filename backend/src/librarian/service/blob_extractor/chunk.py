import re
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader, PdfWriter


@dataclass
class PdfChunk:
    # 0-based half-open page range: pages [start_page, end_page).
    start_page: int
    end_page: int
    pdf_bytes: bytes


@dataclass
class TextChunk:
    # 0-based half-open character range: text[start_char:end_char].
    start_char: int
    end_char: int
    text: str


def chunk_pdf(pdf_bytes: bytes, pages_per_blob: int) -> list[PdfChunk]:
    reader = PdfReader(BytesIO(pdf_bytes))
    n_pages = len(reader.pages)
    chunks: list[PdfChunk] = []
    for start_idx in range(0, n_pages, pages_per_blob):
        end_idx = min(start_idx + pages_per_blob, n_pages)
        writer = PdfWriter()
        for i in range(start_idx, end_idx):
            writer.add_page(reader.pages[i])
        out = BytesIO()
        writer.write(out)
        chunks.append(
            PdfChunk(
                start_page=start_idx,
                end_page=end_idx,
                pdf_bytes=out.getvalue(),
            )
        )
    return chunks


def chunk_text(text: str, words_per_blob: int) -> list[TextChunk]:
    matches = list(re.finditer(r"\S+", text))
    chunks: list[TextChunk] = []
    for i in range(0, len(matches), words_per_blob):
        group = matches[i : i + words_per_blob]
        if not group:
            continue
        start = group[0].start()
        end = group[-1].end()
        chunks.append(TextChunk(start_char=start, end_char=end, text=text[start:end]))
    return chunks
