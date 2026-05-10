"""Extract text content from uploaded files."""
import io
import logging

logger = logging.getLogger("talent_backend.file_handler")


async def extract_text(filename: str, content: bytes) -> str:
    """Extract plain text from a file based on its extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in ("txt", "rtf"):
        return content.decode("utf-8", errors="replace")

    elif ext == "pdf":
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(stream=content, filetype="pdf")
            text = "\n\n".join(page.get_text() for page in doc)
            doc.close()
            return text
        except ImportError:
            logger.warning("PyMuPDF not installed — falling back to raw decode")
            return content.decode("utf-8", errors="replace")

    elif ext in ("docx", "doc"):
        try:
            from docx import Document

            doc = Document(io.BytesIO(content))
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            logger.warning("python-docx not installed — falling back to raw decode")
            return content.decode("utf-8", errors="replace")

    else:
        return content.decode("utf-8", errors="replace")
