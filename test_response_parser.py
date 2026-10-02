import pytest
from response_parser import parse_response, sanitize_for_tts

def test_parse_response_normal_chat():
    text = "Hello! How can I help you today?"
    res = parse_response(text)
    assert res["explanation"] == text
    assert len(res["code_blocks"]) == 0

def test_parse_response_with_code_block():
    text = "Here is the python code:\n```python\nprint('hello')\n```\nEnjoy!"
    res = parse_response(text)
    assert res["explanation"] == "Here is the python code:\n\nEnjoy!"
    assert len(res["code_blocks"]) == 1
    assert res["code_blocks"][0]["language"] == "python"
    assert res["code_blocks"][0]["code"] == "print('hello')"

def test_parse_response_with_multiple_blocks():
    text = "Here is python:\n```python\nprint('a')\n```\nAnd JS:\n```javascript\nconsole.log('b');\n```"
    res = parse_response(text)
    assert res["explanation"] == "Here is python:\n\nAnd JS:"
    assert len(res["code_blocks"]) == 2
    assert res["code_blocks"][0]["language"] == "python"
    assert res["code_blocks"][0]["code"] == "print('a')"
    assert res["code_blocks"][1]["language"] == "javascript"
    assert res["code_blocks"][1]["code"] == "console.log('b');"

def test_parse_response_heuristic_fallback():
    # Long block of raw code without fences
    text = "def reverse_array(arr):\n    return arr[::-1]\n\ndef other_func():\n    pass\n"
    res = parse_response(text)
    assert res["explanation"] == "I've generated the requested code."
    assert len(res["code_blocks"]) == 1
    assert res["code_blocks"][0]["code"].strip() == text.strip()

def test_sanitize_for_tts():
    text = "Hello J.A.R.V.I.S., here is code ```python\nprint('x')``` **bold** *italic* `inline`"
    clean = sanitize_for_tts(text)
    # Code block is stripped and natural-language note is appended
    assert "Jarvis" in clean
    assert "bold" in clean
    assert "italic" in clean
    assert "inline" in clean
    assert "print" not in clean  # code body removed
    assert "included the code" in clean  # natural-language note added

def test_sanitize_for_tts_heuristic():
    text = "def func():\n    pass\nclass A:\n    pass\n"
    clean = sanitize_for_tts(text)
    # Heuristic detects code-heavy content and replaces with a natural-language note
    assert "included the code" in clean
    assert "def func" not in clean  # code removed
    assert "class A" not in clean
