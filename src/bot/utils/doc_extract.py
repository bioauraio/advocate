"""Lightweight, dependency-free helpers for handling uploaded documents.

Used by the agentic document handler to persist an upload into the working
directory and, where cheap, extract readable text so Claude can review the
content with its own tools instead of us stuffing binary/huge blobs into the
prompt. Pure stdlib — no python-docx / pandoc required.
"""

import io
import re
import zipfile
from pathlib import Path
from typing import Optional, Tuple

# Plain-text-ish extensions Claude can read directly once saved to disk.
_TEXT_EXT = {
    ".txt", ".md", ".markdown", ".json", ".yml", ".yaml", ".xml", ".html",
    ".css", ".py", ".js", ".ts", ".sql", ".sh", ".csv", ".log", ".rtf",
}

_ENTITIES = {
    "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'",
    "&apos;": "'",
}


def safe_upload_name(name: str) -> str:
    """Sanitise a Telegram-provided filename for safe on-disk storage."""
    name = Path(name).name  # strip any directory components
    name = re.sub(r"[^\w.\-() ]+", "_", name, flags=re.UNICODE).strip()
    return name or "upload.bin"


def _unescape(s: str) -> str:
    for k, v in _ENTITIES.items():
        s = s.replace(k, v)
    return s


def _docx_text(data: bytes) -> Optional[str]:
    """Extract paragraph text from a .docx (Office Open XML) byte blob."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
    except Exception:
        return None

    lines = []
    for para in re.split(r"</w:p>", xml):
        texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", para, flags=re.S)
        line = _unescape("".join(texts)).strip()
        if line:
            lines.append(line)
    return "\n".join(lines) if lines else None


def extract_document_text(path: Path, data: bytes) -> Tuple[Optional[str], Optional[str]]:
    """Return (text, sidecar_suffix) for an uploaded file, or (None, None).

    Only cheap, safe extractions are attempted: .docx via zip/xml, and plain
    text via UTF-8 decode. Binary formats we can't cheaply read (.pdf, .xlsx…)
    return (None, None) — the file is still saved, just not text-extracted.
    """
    ext = path.suffix.lower()
    if ext == ".docx":
        return _docx_text(data), ".txt"
    if ext in _TEXT_EXT:
        try:
            return data.decode("utf-8"), ".txt"
        except UnicodeDecodeError:
            return None, None
    return None, None
