"""PDF text extraction with defensive handling of bad, encrypted and scanned files."""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class PDFError(Exception):
    """User-presentable PDF problem."""


@dataclass
class ExtractedDoc:
    pages: list[tuple[int, str]]  # (1-based page number, text)
    total_pages: int
    sha256: str
    warnings: list[str]

    @property
    def chars(self) -> int:
        return sum(len(t) for _, t in self.pages)


def clean_text(text: str) -> str:
    text = text.replace("­", "").replace("\x00", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # de-hyphenate line wraps
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf(data: bytes, max_pages: int = 80, max_bytes: int | None = None) -> ExtractedDoc:
    if not data:
        raise PDFError("The uploaded file is empty.")
    if max_bytes and len(data) > max_bytes:
        raise PDFError(f"File is larger than the {max_bytes // (1024 * 1024)} MB limit.")
    if not data.lstrip()[:5].startswith(b"%PDF"):
        raise PDFError("This does not look like a PDF file.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                ok = reader.decrypt("")
            except Exception:
                ok = 0
            if not ok:
                raise PDFError("This PDF is password-protected. Remove the password and retry.")
        total = len(reader.pages)
    except PDFError:
        raise
    except (PdfReadError, Exception) as exc:  # corrupt files raise many types
        raise PDFError(f"The PDF could not be read ({type(exc).__name__}). It may be corrupted.") from exc

    warnings: list[str] = []
    limit = min(total, max_pages)
    if total > max_pages:
        warnings.append(f"Large document: only the first {max_pages} of {total} pages were analysed.")

    pages: list[tuple[int, str]] = []
    bad = 0
    for i in range(limit):
        try:
            text = clean_text(reader.pages[i].extract_text() or "")
        except Exception:
            bad += 1
            continue
        if text:
            pages.append((i + 1, text))
    if bad:
        warnings.append(f"{bad} page(s) could not be parsed and were skipped.")
    if not pages:
        raise PDFError(
            "No extractable text found. This looks like a scanned/image-only PDF; "
            "Verity AI needs a text-based PDF (OCR is not supported)."
        )
    return ExtractedDoc(pages=pages, total_pages=total, sha256=hashlib.sha256(data).hexdigest(), warnings=warnings)


def chunk_pages(pages: list[tuple[int, str]], max_chars: int = 7000) -> list[tuple[list[int], str]]:
    """Group page text into chunks <= max_chars, splitting oversized pages on paragraph/sentence edges."""
    pieces: list[tuple[int, str]] = []
    for pno, text in pages:
        if len(text) <= max_chars:
            pieces.append((pno, text))
            continue
        buf = ""
        for para in re.split(r"(?<=[.!?])\s+|\n\n", text):
            if len(buf) + len(para) + 1 > max_chars and buf:
                pieces.append((pno, buf))
                buf = ""
            buf = f"{buf} {para}".strip()
        if buf:
            pieces.append((pno, buf))

    chunks: list[tuple[list[int], str]] = []
    cur_pages: list[int] = []
    cur = ""
    for pno, text in pieces:
        block = f"[Page {pno}]\n{text}\n"
        if cur and len(cur) + len(block) > max_chars:
            chunks.append((cur_pages, cur))
            cur_pages, cur = [], ""
        cur += block
        if pno not in cur_pages:
            cur_pages.append(pno)
    if cur:
        chunks.append((cur_pages, cur))
    return chunks
