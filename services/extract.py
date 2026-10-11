"""PDF / Word fayldan matn olish va testlarni bo'laklarga ajratish."""
import re
from pathlib import Path

import pymupdf
from docx import Document

SUPPORTED = (".pdf", ".docx", ".txt")

# "1. Savol", "12) Savol" ko'rinishidagi qator boshlari
QUESTION_START = re.compile(r"(?m)^[ \t]*(\d{1,4})[ \t]*[.)][ \t]+\S")


def extract_text(path: str | Path) -> str:
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".pdf":
        with pymupdf.open(path) as doc:
            return "\n".join(page.get_text() for page in doc)
    if ext == ".docx":
        doc = Document(path)
        lines = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                lines.append(" | ".join(c.text for c in row.cells))
        return "\n".join(lines)
    if ext == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")
    raise ValueError(f"{ext} formati qo'llab-quvvatlanmaydi")


def split_numbered_questions(text: str) -> list[str]:
    """Ketma-ket raqamlangan savollarni ajratadi (1, 2, 3 ...). Variantlardagi 1) 2) larni chalg'itmaydi."""
    starts, expected = [], None
    for m in QUESTION_START.finditer(text):
        n = int(m.group(1))
        if expected is None or n == expected:
            starts.append(m.start())
            expected = n + 1
    starts.append(len(text))
    return [text[a:b].strip() for a, b in zip(starts, starts[1:]) if text[a:b].strip()]


def chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def text_windows(text: str, size: int = 12_000) -> list[str]:
    """Uzun matnni paragraf chegarasida bo'laklarga bo'ladi."""
    out, buf = [], ""
    for para in text.split("\n"):
        if len(buf) + len(para) > size and buf:
            out.append(buf)
            buf = ""
        buf += para + "\n"
    if buf.strip():
        out.append(buf)
    return out


def split_book(text: str, parts: int, max_chars: int = 60_000) -> list[str]:
    """Kitobni teng qismlarga bo'ladi; juda uzun qismdan teng oraliqdagi bo'laklar olinadi."""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    step = max(1, len(text) // parts)
    slices = [text[i * step:(i + 1) * step if i < parts - 1 else len(text)] for i in range(parts)]
    result = []
    for s in slices:
        if len(s) > max_chars:
            windows = 4
            w = max_chars // windows
            gap = len(s) // windows
            s = "\n...\n".join(s[k * gap:k * gap + w] for k in range(windows))
        result.append(s)
    return result
