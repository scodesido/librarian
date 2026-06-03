from io import BytesIO

from pypdf import PdfReader, PdfWriter


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract plain text from a (sub-)PDF for use as embedder input.

    Images are silently dropped — that is intentional. The LLM still sees the
    raw PDF bytes (so charts/diagrams contribute to the Abstract), and the
    Abstract is concatenated with this text before embedding, so an
    image-only blob still produces a meaningful embedding via the Abstract.
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_pdf_pages_text(pdf_bytes: bytes, start_page: int, end_page: int) -> str:
    """Extract plain text from the half-open page range [start_page, end_page)
    of a PDF. Used by retrieval to materialise a blob's content range without
    re-chunking the file.
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(
        reader.pages[i].extract_text() or "" for i in range(start_page, end_page)
    )


def extract_pdf_pages_bytes(pdf_bytes: bytes, start_page: int, end_page: int) -> bytes:
    """Reconstruct a standalone PDF holding only the half-open page range
    [start_page, end_page) of the source. Used by retrieval's binary output
    mode: a blob is a *fragment*, so we return its page range as a valid PDF
    rather than the whole source file or an un-sliceable byte range.
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    for i in range(start_page, end_page):
        writer.add_page(reader.pages[i])
    out = BytesIO()
    writer.write(out)
    return out.getvalue()
