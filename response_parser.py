import re
from typing import Dict, Any, List


def parse_response(text: str) -> Dict[str, Any]:
    """
    Parses a raw AI response, extracting Markdown fenced code blocks.
    Returns:
    {
        "explanation": str (the non-code conversational text),
        "code_blocks": list of dicts {"language": str, "code": str}
    }
    """
    if not text:
        return {"explanation": "", "code_blocks": []}

    code_blocks = []

    # Extract fenced code blocks
    # Match ```language\n code \n```
    pattern = re.compile(r'```([^\n]*)\n(.*?)```', re.DOTALL)

    def replacer(match):
        lang = match.group(1).strip()
        code = match.group(2).strip()
        code_blocks.append({"language": lang, "code": code})
        return ""  # Remove the code block from the explanation

    explanation = pattern.sub(replacer, text).strip()

    # Fallback heuristic for unfenced code blocks
    if not code_blocks:
        lines = explanation.split('\n')
        code_lines = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if (stripped.endswith(';') or stripped.endswith('{') or
                    stripped.endswith('}') or stripped.startswith('def ') or
                    stripped.startswith('class ') or stripped.startswith('import ') or
                    stripped.startswith('const ') or stripped.startswith('let ') or
                    stripped.startswith('var ') or stripped.startswith('return ') or
                    stripped.startswith('print(') or stripped.startswith('console.log(')):
                code_lines += 1

        valid_lines = [l for l in lines if l.strip()]
        if valid_lines and (code_lines / len(valid_lines)) >= 0.5 and len(valid_lines) >= 3:
            # High density of code-like lines. Treat as code dump.
            code_blocks.append({"language": "", "code": explanation})
            explanation = "I've generated the requested code."

    # Cleanup explanation formatting
    explanation = re.sub(r'\n{3,}', '\n\n', explanation).strip()

    return {
        "explanation": explanation,
        "code_blocks": code_blocks
    }


def sanitize_for_tts(text: str) -> str:
    """
    Comprehensive TTS sanitization pipeline.

    Two representations exist:
      - visual/rendered response  → shown in the Chat UI (raw Markdown is fine)
      - spoken_text               → passed through this function before TTS

    Strips / replaces everything that must NOT be spoken:
      - Fenced code blocks        → "I've included the code in the chat."
      - Inline code spans         → identifier text kept (short, readable)
      - Markdown headings (##…)
      - Markdown bold / italic markers
      - Markdown horizontal rules
      - Markdown bullet / numbered list prefixes
      - Block-quote markers
      - URLs (https?://…)         → "I've included the reference link in the chat."
      - Raw www. links
      - Markdown link syntax [text](url) → text only
      - Citation references [1], [2]
      - Raw HTML tags
      - Decorative symbols (~ | )
      - Normalises J.A.R.V.I.S → Jarvis
      - Collapses excessive whitespace
    """
    if not text:
        return ""

    # ── 1. Strip fenced code blocks ──────────────────────────────────
    has_code_block = bool(re.search(r'```[\s\S]*?```', text))
    text = re.sub(r'```[\s\S]*?```', '', text)

    # ── 2. Strip raw HTML tags ───────────────────────────────────────
    text = re.sub(r'<[^>]+>', '', text)

    # ── 3. Normalise J.A.R.V.I.S → Jarvis ──────────────────────────
    text = re.sub(r'\bJ\.A\.R\.V\.I\.S\b\.?', 'Jarvis', text, flags=re.IGNORECASE)
    text = re.sub(r'J\.A\.R\.V\.I\.S\.?', 'Jarvis', text, flags=re.IGNORECASE)

    # ── 4. Strip Markdown headings (## Heading → Heading) ───────────
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # ── 5. Strip Markdown horizontal rules ───────────────────────────
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)

    # ── 6. Strip Markdown bold / italic markers ───────────────────────
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'__(.*?)__', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)

    # ── 7. Strip inline code backticks (keep the identifier text) ────
    text = re.sub(r'`([^`]*)`', r'\1', text)

    # ── 8. Replace Markdown link syntax [text](url) → text ──────────
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)

    # ── 9. Replace URLs with a natural-language placeholder ──────────
    has_url = bool(re.search(r'https?://\S+', text))
    text = re.sub(r'https?://\S+', '', text)
    # Also strip bare www. links
    bare_www = bool(re.search(r'\bwww\.\S+', text))
    if bare_www:
        has_url = True
    text = re.sub(r'\bwww\.\S+', '', text)

    # ── 10. Strip Markdown bullet / numbered list prefixes ────────────
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)

    # ── 11. Strip blockquote markers ─────────────────────────────────
    text = re.sub(r'^\s*>\s?', '', text, flags=re.MULTILINE)

    # ── 12. Strip citation / reference syntax ────────────────────────
    text = re.sub(r'\[\d+\]', '', text)

    # ── 13. Strip decorative symbols ─────────────────────────────────
    text = re.sub(r'[~|]', '', text)

    # ── 14. Collapse whitespace ──────────────────────────────────────
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = text.strip()

    # ── 15. Heuristic: if the remaining text is still code-heavy ─────
    lines = text.split('\n')
    valid_lines = [l for l in lines if l.strip()]
    if valid_lines:
        code_indicators = ('; ', '{', '}', '()', '=>', ' == ', ' != ',
                           ' += ', ' -= ', ' => ')
        code_starts = ('def ', 'class ', 'import ', 'from ', 'return ',
                       'print(', 'console.log(', 'const ', 'let ', 'var ',
                       'function ', 'if (', 'for (', 'while (', '#include',
                       'SELECT ', 'INSERT ', 'UPDATE ', 'DELETE ')
        code_line_count = sum(
            1 for l in valid_lines
            if any(l.strip().lower().startswith(s.lower()) for s in code_starts)
            or any(ind in l for ind in code_indicators)
        )
        if len(valid_lines) >= 3 and (code_line_count / len(valid_lines)) >= 0.5:
            has_code_block = True
            text = ''

    # ── 16. Append natural-language notes for stripped content ────────
    suffixes = []
    if has_code_block:
        suffixes.append("I've included the code in the chat.")
    if has_url:
        suffixes.append("I've included the reference link in the chat.")

    if not text and not suffixes:
        return ''

    if suffixes:
        suffix_str = ' '.join(suffixes)
        if text:
            text = text.rstrip('.') + '. ' + suffix_str
        else:
            text = suffix_str

    return text.strip()
