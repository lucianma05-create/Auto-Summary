from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .constants import CORE_KEYWORDS, DIRECTION_FALLBACK, LIST_FIELD_LIMITS


def load_directions(root: Path) -> set[str]:
    rd_path = root.parent / "Social-AI-Group" / "Research Direction.md"
    if not rd_path.exists():
        return set(DIRECTION_FALLBACK)
    pattern = re.compile(r"^###\s*([A-Za-z0-9_-]+)\s*:")
    found: set[str] = set()
    for line in rd_path.read_text(encoding="utf-8").splitlines():
        m = pattern.match(line.strip())
        if m:
            found.add(m.group(1).strip())
    return found or set(DIRECTION_FALLBACK)


def list_pending_pdfs(pending_dir: Path) -> list[Path]:
    files = [p for p in pending_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]
    return sorted(files, key=lambda p: p.name.lower())


def extract_pdf_text(pdf_path: Path, max_pages: int, max_chars: int) -> str:
    reader = PdfReader(str(pdf_path))
    chunks: list[str] = []
    total = 0
    for page_idx, page in enumerate(reader.pages):
        if page_idx >= max_pages or total >= max_chars:
            break
        text = page.extract_text() or ""
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        remain = max_chars - total
        text = text[:remain]
        chunks.append(f"[Page {page_idx + 1}] {text}")
        total += len(text)
    return "\n".join(chunks).strip()


def _ascii_tag(text: str, fallback: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9]+", "", (text or "")).lower()
    return raw or fallback


def _sharer_abbr(sharer: str) -> str:
    words = re.findall(r"[A-Za-z]+", sharer or "")
    if not words:
        return "usr"
    if len(words) == 1:
        return words[0].lower()[:8]
    return "".join(w[0].lower() for w in words)[:8]


def next_image_name(image_dir: Path, *, sharer: str, nickname: str) -> str:
    day = dt.datetime.now().strftime("%Y%m%d")
    pattern = re.compile(rf"^{day}(\d{{2}})[a-z0-9]+\.png$")
    max_id = 0
    for p in image_dir.iterdir():
        if not p.is_file():
            continue
        m = pattern.match(p.name)
        if m:
            max_id = max(max_id, int(m.group(1)))
    sharer_tag = _sharer_abbr(sharer)
    nick_tag = _ascii_tag(nickname, "general")
    return f"{day}{(max_id + 1):02d}{sharer_tag}{nick_tag}.png"


def clean_json_block(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("No JSON object found.")
    return json.loads(text[start : end + 1])


def safe_string(value: Any, default: str = "未提及") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def ensure_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [safe_string(x, "").strip() for x in value if safe_string(x, "").strip()]
    if isinstance(value, str):
        return [x.strip(" -\t") for x in value.splitlines() if x.strip()]
    return [safe_string(value)]


def sanitize_filename(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]", "-", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text or "Untitled"


def truncate_utf8_bytes(text: str, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    clipped = raw[:max_bytes]
    while clipped:
        try:
            return clipped.decode("utf-8").rstrip(" .-_")
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return "untitled"


def build_safe_markdown_filename(
    *,
    direction: str,
    venue: str,
    year: str,
    title: str,
    max_bytes: int = 180,
) -> str:
    direction = sanitize_filename(direction)
    venue = sanitize_filename(venue)
    year = sanitize_filename(year)
    title = sanitize_filename(title)
    base = f"{direction}-{venue}-{year}-{title}"
    if len(base.encode("utf-8")) <= max_bytes:
        return base + ".md"

    # Preserve prefix semantics: direction-venue-year-
    prefix = f"{direction}-{venue}-{year}-"
    remain = max_bytes - len(prefix.encode("utf-8"))
    if remain < 24:
        # venue can be very long; cap venue first.
        short_venue = truncate_utf8_bytes(venue, 40)
        prefix = f"{direction}-{short_venue}-{year}-"
        remain = max_bytes - len(prefix.encode("utf-8"))
    short_title = truncate_utf8_bytes(title, max(remain, 16))
    base = prefix + short_title
    return sanitize_filename(base) + ".md"


def normalize_year(value: Any) -> str:
    txt = safe_string(value, "unknown")
    m = re.search(r"(19|20)\d{2}", txt)
    return m.group(0) if m else txt


def normalize_venue_abbr(value: Any) -> str:
    txt = safe_string(value, "arXiv").strip()
    low = txt.lower()
    rules: list[tuple[list[str], str]] = [
        (["association for computational linguistics"], "ACL"),
        (["empirical methods in natural language processing"], "EMNLP"),
        (["north american chapter", "computational linguistics"], "NAACL"),
        (["international conference on computational linguistics"], "COLING"),
        (["conference on language modeling"], "CoLM"),
        (["conference on computer vision and pattern recognition"], "CVPR"),
        (["international conference on learning representations"], "ICLR"),
        (["international conference on machine learning"], "ICML"),
        (["advances in neural information processing systems"], "NeurIPS"),
        (["aaai conference on artificial intelligence"], "AAAI"),
        (["international joint conference on artificial intelligence"], "IJCAI"),
        (["transactions of the association for computational linguistics"], "TACL"),
        (["transactions on pattern analysis and machine intelligence"], "TPAMI"),
        (["arxiv"], "arXiv"),
    ]
    for keys, abbr in rules:
        if all(k in low for k in keys):
            return abbr
    m = re.search(r"\b([A-Z][A-Za-z0-9-]{1,11})\b", txt)
    if m and any(ch.isupper() for ch in m.group(1)):
        return m.group(1)
    m2 = re.search(r"\(([A-Za-z][A-Za-z0-9-]{1,11})\)", txt)
    if m2:
        return m2.group(1)
    words = re.findall(r"[A-Za-z]+", txt)
    if words:
        initials = "".join(w[0].upper() for w in words if w and w[0].isalpha())
        if 2 <= len(initials) <= 10:
            return initials
    return txt[:24] or "arXiv"


def fallback_title_from_filename(pdf_name: str) -> str:
    stem = Path(pdf_name).stem
    return stem.replace("_", " ").strip() or "Untitled Paper"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 1
    while True:
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def _normalize_item_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip("。.;；,，")


def _dedup_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        k = re.sub(r"[\W_]+", "", item.lower())
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out


def _core_score(item: str) -> int:
    score = 0
    low = item.lower()
    for kw in CORE_KEYWORDS:
        if kw.lower() in low:
            score += 2
    n = len(item)
    if 12 <= n <= 48:
        score += 2
    if n > 80:
        score -= 1
    return score


def trim_list_items(items: list[str], min_n: int, max_n: int) -> list[str]:
    cleaned = [_normalize_item_text(x) for x in items if _normalize_item_text(x)]
    deduped = _dedup_items(cleaned)
    if not deduped:
        return []
    ranked = sorted(deduped, key=lambda x: (_core_score(x), -len(x)), reverse=True)
    selected = ranked[:max_n]
    if len(selected) < min_n:
        for x in ranked[max_n:]:
            if x not in selected:
                selected.append(x)
            if len(selected) >= min_n:
                break
    return selected[:max_n]


def apply_quality_constraints(data: dict[str, Any]) -> dict[str, Any]:
    for field, (min_n, max_n) in LIST_FIELD_LIMITS.items():
        data[field] = trim_list_items(ensure_list(data.get(field)), min_n=min_n, max_n=max_n)
    for field in ["one_sentence_summary", "one_sentence_contrib"]:
        value = re.sub(r"\s+", " ", safe_string(data.get(field))).strip()
        if len(value) > 120:
            value = value[:120].rstrip("，,;；。.") + "。"
        data[field] = value
    return data


def quality_gaps(data: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field, (min_n, _max_n) in LIST_FIELD_LIMITS.items():
        if len(ensure_list(data.get(field))) < min_n:
            missing.append(field)
    for field in ["one_sentence_summary", "one_sentence_contrib", "innovation_example", "workflow_description"]:
        if safe_string(data.get(field)) == "未提及":
            missing.append(field)
    return missing
