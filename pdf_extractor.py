import re
import fitz  # pymupdf

MIN_TEXT_LENGTH = 500
CHUNK_TOKENS    = 800
OVERLAP_TOKENS  = 150

# Section header keywords → normalized label
_SECTION_PATTERNS = [
    (re.compile(r"\b(abstract)\b", re.I),       "abstract"),
    (re.compile(r"\b(introduction)\b", re.I),    "introduction"),
    (re.compile(r"\b(methodology|methods?)\b", re.I), "methodology"),
    (re.compile(r"\b(results?|findings?)\b", re.I),   "results"),
    (re.compile(r"\b(discussion)\b", re.I),      "discussion"),
    (re.compile(r"\b(conclusion|conclusions?)\b", re.I), "conclusion"),
    (re.compile(r"\b(references?|bibliography)\b", re.I), "references"),
]


def _detect_section(text: str) -> str:
    first_line = text.split("\n")[0].strip()
    for pattern, label in _SECTION_PATTERNS:
        if pattern.search(first_line):
            return label
    return "body"


def _approx_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 chars."""
    return len(text) // 4


def _chunk_text(text: str, chunk_tokens: int = CHUNK_TOKENS, overlap_tokens: int = OVERLAP_TOKENS) -> list[str]:
    words = text.split()
    chunk_words  = chunk_tokens * 4 // 5   # ~words per chunk
    overlap_words = overlap_tokens * 4 // 5

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_words
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end >= len(words):
            break
        start = end - overlap_words

    return chunks


def extract_chunks(pdf_path: str, doc_id: str, title: str = "", source: str = "dspace") -> list[dict]:
    """
    Extract text from PDF and return a list of chunk dicts ready for indexing.
    Returns empty list if text is too short (needs OCR).
    Raises ValueError with reason 'needs_ocr' in that case.
    """
    doc = fitz.open(pdf_path)

    pages_text: list[tuple[int, str]] = []
    for page_num, page in enumerate(doc, start=1):
        text = page.get_text("text").strip()
        if text:
            pages_text.append((page_num, text))

    doc.close()

    full_text = "\n".join(t for _, t in pages_text)
    if len(full_text) < MIN_TEXT_LENGTH:
        raise ValueError("needs_ocr")

    chunks = []
    chunk_counter = 0
    current_section = "body"

    for page_num, page_text in pages_text:
        section = _detect_section(page_text)
        if section != "body":
            current_section = section

        for chunk_text in _chunk_text(page_text):
            if len(chunk_text.strip()) < 50:
                continue
            chunk_counter += 1
            chunks.append({
                "chunk_id":   f"{doc_id}_{chunk_counter:04d}",
                "doc_id":     doc_id,
                "title":      title,
                "source":     source,
                "page":       page_num,
                "section":    current_section,
                "chunk_text": chunk_text,
            })

    return chunks
