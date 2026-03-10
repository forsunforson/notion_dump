import re


def split_text_by_length(text: str, max_len: int = 1800) -> list[str]:
    """
    Split text strictly by length. Useful for API limits like Notion block size.
    """
    if not text:
        return [""]
    chunks: list[str] = []
    i = 0
    while i < len(text):
        chunks.append(text[i : i + max_len])
        i += max_len
    return chunks


def split_text_smart(text: str, max_chars: int = 3500) -> list[str]:
    """
    Split text by paragraphs first, then by length if a paragraph is too long.
    Useful for messaging platforms like Telegram.
    """
    s = (text or "").strip()
    if not s:
        return []
    if len(s) <= max_chars:
        return [s]

    chunks = []
    buf = ""
    for block in re.split(r"\n{2,}", s):
        block = block.strip()
        if not block:
            continue
        candidate = (buf + "\n\n" + block).strip() if buf else block
        if len(candidate) <= max_chars:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        if len(block) <= max_chars:
            buf = block
            continue
        for i in range(0, len(block), max_chars):
            chunks.append(block[i : i + max_chars])
    if buf:
        chunks.append(buf)
    return chunks
