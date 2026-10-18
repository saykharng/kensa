"""Find declarations in a source file without a language server."""

import re

_PATTERNS = (
    re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"
    ),
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)"),
    re.compile(r"^\s*class\s+([A-Za-z_][\w]*)"),
    re.compile(
        r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_][\w]*)"
    ),
    re.compile(r"^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z_][\w]*)"),
    re.compile(r"^\s*(?:type|interface)\s+([A-Za-z_][\w]*)"),
)


def outline(text):
    """Return {name, line} for functions, classes, and similar declarations."""
    found = []
    seen = set()
    for number, line in enumerate(text.splitlines(), start=1):
        for pattern in _PATTERNS:
            match = pattern.match(line)
            if not match:
                continue
            name = next(group for group in match.groups() if group)
            key = (name, number)
            if key in seen:
                continue
            seen.add(key)
            found.append({"name": name, "line": number})
            break
    return found


def rank_hits(symbol, hits):
    """Prefer lines that declare the symbol. hits are {path, line, text}."""
    scored = []
    for hit in hits:
        declarations = outline(hit["text"])
        declared = any(item["name"] == symbol for item in declarations)
        score = 2 if declared else 1
        scored.append((score, hit))
    scored.sort(key=lambda item: (-item[0], item[1]["path"], item[1]["line"]))
    return [hit for _, hit in scored]
