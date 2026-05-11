"""
Text extraction from bulletin PDFs.

Bulletins are usually 2-4 page text PDFs. pdfplumber with layout-aware
extraction handles the multi-column layouts most parishes use; pdftotext
is a CLI fallback. We don't try to extract images or fancy layout — for
parsing the text content into structured data, the raw text in roughly
top-to-bottom order is what we need.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    """
    Extract text from a bulletin PDF, preserving rough reading order.

    Tries pdfplumber first (Python, handles multi-column reasonably well),
    falls back to `pdftotext -layout` (CLI, more robust to weird PDFs).
    Raises RuntimeError if both fail.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    # Primary: pdfplumber
    try:
        import pdfplumber

        chunks: list[str] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                chunks.append(text)
        text = "\n\n".join(chunks).strip()
        if text:
            return text
    except Exception:
        # Fall through to pdftotext
        pass

    # Fallback: pdftotext -layout
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        if result.stdout.strip():
            return result.stdout
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        raise RuntimeError(f"Could not extract text from {pdf_path}: {e}")

    raise RuntimeError(f"Extracted no text from {pdf_path}")


def load_text(source: str | Path) -> str:
    """
    Load bulletin text from either a PDF path or a .txt fixture.

    Used by the CLI so test fixtures (plain text bulletins extracted
    elsewhere) can be parsed without re-running PDF extraction.
    """
    source = Path(source)
    if source.suffix.lower() == ".pdf":
        return extract_text_from_pdf(source)
    return source.read_text(encoding="utf-8")
