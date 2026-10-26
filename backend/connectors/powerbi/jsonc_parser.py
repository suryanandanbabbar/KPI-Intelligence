"""
KPI Intelligence — JSONC Parser.

Robust JSON with Comments (JSONC) and Trailing Comma Parser.
Correctly preserves comments inside string literals (e.g. URLs, escaped quotes)
and strips trailing commas in objects and arrays before standard JSON decoding.
"""

import json
from typing import Any, Union


def strip_jsonc_comments_and_trailing_commas(text: str) -> str:
    """
    Strips single-line (//) and multi-line (/* */) comments and trailing commas
    from JSONC text without mutating string literals.
    """
    result = []
    i = 0
    n = len(text)
    
    in_string = False
    escape = False
    
    while i < n:
        char = text[i]
        
        if in_string:
            result.append(char)
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                in_string = False
            i += 1
            continue
        
        # Not in string
        if char == '"':
            in_string = True
            result.append(char)
            i += 1
            continue
            
        # Check single-line comment
        if char == '/' and i + 1 < n and text[i + 1] == '/':
            # Skip until newline or EOF
            i += 2
            while i < n and text[i] not in ('\r', '\n'):
                i += 1
            continue
            
        # Check multi-line comment
        if char == '/' and i + 1 < n and text[i + 1] == '*':
            # Skip until */ or EOF
            i += 2
            while i + 1 < n and not (text[i] == '*' and text[i + 1] == '/'):
                if text[i] == '\n':
                    result.append('\n')  # preserve newline for line counts
                i += 1
            i += 2  # skip */
            continue
            
        # Regular character
        result.append(char)
        i += 1
        
    cleaned_text = "".join(result)
    
    # Second pass: remove trailing commas before '}' or ']'
    # We must also respect string literals during this pass
    final_chars = []
    m = len(cleaned_text)
    j = 0
    in_string = False
    escape = False
    
    while j < m:
        c = cleaned_text[j]
        
        if in_string:
            final_chars.append(c)
            if escape:
                escape = False
            elif c == '\\':
                escape = True
            elif c == '"':
                in_string = False
            j += 1
            continue
            
        if c == '"':
            in_string = True
            final_chars.append(c)
            j += 1
            continue
            
        if c == ',':
            # Look ahead across whitespace to see if next non-whitespace is '}' or ']'
            k = j + 1
            while k < m and cleaned_text[k].isspace():
                k += 1
            if k < m and cleaned_text[k] in ('}', ']'):
                # Omit this trailing comma
                j += 1
                continue
                
        final_chars.append(c)
        j += 1
        
    return "".join(final_chars)


def parse_jsonc(content: str) -> Any:
    """
    Parses a JSONC string into Python objects (dict, list, etc.).
    
    Raises:
        json.JSONDecodeError if invalid JSON.
    """
    clean = strip_jsonc_comments_and_trailing_commas(content)
    # Handle empty or whitespace-only strings
    if not clean.strip():
        return {}
    return json.loads(clean)


def parse_jsonc_file(filepath: str, encoding: str = "utf-8") -> Any:
    """
    Reads and parses a JSONC file from disk.
    Handles UTF-8 BOM if present.
    """
    with open(filepath, "r", encoding=encoding, errors="replace") as f:
        content = f.read()
    if content.startswith("\ufeff"):
        content = content[1:]
    return parse_jsonc(content)
