import pymupdf


def pdf_pages_to_pngs(pdf_bytes: bytes, dpi: int) -> list[bytes]:
    """Render every page of a PDF to a PNG byte string.

    Used by the `images` llm_pdf_mode to leverage vision-capable local
    LLMs (gemma3, llama3.2-vision, …) that can't ingest application/pdf
    directly but can ingest images. The DPI controls the rasterization
    resolution before any downscaling the vision model does internally;
    150 is enough that body text remains legible after gemma3's 896×896
    downsample. Bump it if the model struggles on small text.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        # Iterate by index: pymupdf's Document is iterable at runtime
        # via __getitem__, but its type stubs don't declare __iter__.
        return [doc[i].get_pixmap(dpi=dpi).tobytes("png") for i in range(len(doc))]
    finally:
        doc.close()
