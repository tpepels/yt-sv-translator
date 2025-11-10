import re
from typing import Optional

def col_to_index(col):
    """Convert a column letter (A,B,C,...) or number (1,2,3,...) to 1-based index."""
    if isinstance(col, int):
        return col
    s = str(col).strip()
    if s.isdigit():
        return int(s)
    # letters
    s = s.upper()
    idx = 0
    for ch in s:
        if not ('A' <= ch <= 'Z'):
            raise ValueError(f"Invalid column '{col}'")
        idx = idx * 26 + (ord(ch) - ord('A') + 1)
    return idx

def extract_candidate_terms(text: str):
    """Naive term extraction: pull capitalized tokens and multiword sequences."""
    tokens = re.findall(r"[A-ZÅÄÖ][\wÅÄÖåäö\-']+", text)
    return [t for t in tokens if len(t) > 2]

def clamp(n, lo, hi):
    return max(lo, min(hi, n))

def strip_if_needed(s: Optional[str]) -> str:
    return (s or "").strip()
