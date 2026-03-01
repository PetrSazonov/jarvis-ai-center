import re


_BASIC_CYR_RE = re.compile(r"[А-Яа-яЁё]")
_WEIRD_CYR_RE = re.compile(r"[\u0402-\u040F\u0452-\u045F]")
_PAIR_MOJ_RE = re.compile(r"[РС][\u0402-\u045F]")


def _looks_like_mojibake(text: str) -> bool:
    sample = (text or "").strip()
    if not sample:
        return False
    if "�" in sample:
        return True
    if any(ch in sample for ch in ("Ð", "Ñ", "â")):
        return True
    if len(_PAIR_MOJ_RE.findall(sample)) >= 2:
        return True
    if len(_WEIRD_CYR_RE.findall(sample)) >= 2:
        return True
    return False


def _quality_score(text: str) -> int:
    basic = len(_BASIC_CYR_RE.findall(text))
    weird = len(_WEIRD_CYR_RE.findall(text))
    latin_moj = sum(text.count(ch) for ch in ("Ð", "Ñ", "â"))
    replacement = text.count("�")
    return basic * 2 - weird * 4 - latin_moj * 3 - replacement * 5


def _try_repair(text: str, src_encoding: str) -> str | None:
    try:
        return text.encode(src_encoding, errors="strict").decode("utf-8", errors="strict")
    except Exception:
        return None


def normalize_display_text(text: str) -> str:
    sample = (text or "").replace("\r\n", "\n")
    if not _looks_like_mojibake(sample):
        return sample

    candidates = [sample]
    for src in ("cp1251", "latin1"):
        fixed = _try_repair(sample, src)
        if fixed:
            candidates.append(fixed)

    best = max(candidates, key=_quality_score)
    return best

