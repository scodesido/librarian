from io import BytesIO

from pypdf import PdfReader


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract plain text from a (sub-)PDF for use as embedder input.

    Images are silently dropped — that is intentional. The LLM still sees the
    raw PDF bytes (so charts/diagrams contribute to the Abstract), and the
    Abstract is concatenated with this text before embedding, so an
    image-only blob still produces a meaningful embedding via the Abstract.
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)
