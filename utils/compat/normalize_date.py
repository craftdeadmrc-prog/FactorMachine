from typing import Optional
def normalize_date_str(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return None
