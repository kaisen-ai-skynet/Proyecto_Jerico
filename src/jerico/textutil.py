import re
import unicodedata


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFD", text.strip().lower())
    folded = "".join(ch for ch in folded if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", folded)
