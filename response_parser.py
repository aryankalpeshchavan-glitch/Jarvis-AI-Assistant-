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
        return "" # Remove the code block from the explanation
    
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
    Sanitizes text specifically for the TTS engine.
    - Strips markdown code blocks.
    - Normalizes "J.A.R.V.I.S." to "Jarvis".
    - Strips markdown formatting.
    """
    if not text:
        return ""
    
    # 1. Strip fenced code blocks entirely
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    
    # 2. Normalize J.A.R.V.I.S to Jarvis
    text = re.sub(r'\bJ\.A\.R\.V\.I\.S\b\.?', 'Jarvis', text, flags=re.IGNORECASE)
    text = re.sub(r'J\.A\.R\.V\.I\.S\.?', 'Jarvis', text, flags=re.IGNORECASE)
    
    # 3. Strip bold/italic markdown
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    
    # 4. Strip inline code backticks but keep text
    text = re.sub(r'`(.*?)`', r'\1', text)
    
    # 5. Fallback heuristic for unfenced code blocks: if it's very code-heavy, strip it
    lines = text.split('\n')
    code_lines = 0
    for line in lines:
        stripped = line.strip()
        if (stripped.endswith(';') or stripped.endswith('{') or 
            stripped.endswith('}') or stripped.startswith('def ') or 
            stripped.startswith('class ') or stripped.startswith('import ') or
            stripped.startswith('return ') or stripped.startswith('print(') or
            stripped.startswith('console.log(')):
            code_lines += 1
    
    valid_lines = [l for l in lines if l.strip()]
    if valid_lines and (code_lines / len(valid_lines)) >= 0.5 and len(valid_lines) >= 3:
        # Heavily code-like response, remove everything to be safe
        return "I've generated the requested code."

    return text.strip()
