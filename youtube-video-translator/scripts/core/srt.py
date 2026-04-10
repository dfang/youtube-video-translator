"""
Shared SRT parsing, timecode conversion, and technical block detection.
Single source of truth for all Phase 4 scripts.
"""
from __future__ import annotations

import re
import hashlib
from pathlib import Path

# ---------------------------------------------------------------------------
# Technical block patterns — blocks matching these skip untranslated checks
# ---------------------------------------------------------------------------
TECH_BLOCK_PATTERNS = [
    r"^\s*\d+\.?\d*\s*$",
    r"^\s*\d+\.?\d*\s*(mL|ml|L|mg|g|kg|cm|mm|m|h|min|s|sec|hr|%)\s*$",
    r"^\s*\d+\.?\d*\s*HU\s*$",
    r"^\s*\d+\.?\d*%\s*$",
    r"^\s*\b(EIT|ICU|CT|MRI|PEET|FiO2|SpO2|VT|PIP|CPAP|ECMO|PaO2|PaCO2)\b[。.]?\s*$",
    r"^\s*\b(Professor|Doctor|MD|PhD)\.?\s*$",
    r"^\s*\b(zero|one|two|three|four|five|six|seven|eight|nine|ten)\b\s*$",
]


def is_technical_block(text: str) -> bool:
    """Return True if a block is purely technical content (numbers, acronyms)."""
    text = text.strip()
    for pattern in TECH_BLOCK_PATTERNS:
        if re.match(pattern, text, re.IGNORECASE):
            return True
    return False


def is_likely_untranslated(source_text: str, translated_text: str) -> bool:
    """
    Return True if translated_text looks like an untranslated copy of source_text.
    Technical blocks are excluded.
    """
    src = " ".join(source_text.split())
    dst = " ".join(translated_text.split())
    if not dst:
        return True
    if src == dst:
        return True
    src_lower = src.lower()
    dst_lower = dst.lower()
    if src_lower == dst_lower and src != dst:
        return False  # just different case
    if is_technical_block(src) and is_technical_block(dst):
        return False
    has_chinese = bool(re.search(r"[\u4e00-\u9fff]", dst))
    has_english_letters = bool(re.search(r"[A-Za-z]", dst))
    if not has_chinese and has_english_letters:
        return True
    return False


# ---------------------------------------------------------------------------
# Timecode parsing
# ---------------------------------------------------------------------------
TIME_RE = re.compile(r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})")


def normalize_timecode(ts: str) -> str:
    """Normalize SRT timecode: always use comma as decimal separator."""
    return ts.replace(".", ",")


def seconds_to_srt_time(secs: float) -> str:
    """Convert float seconds to SRT timestamp: 00:00:00,000."""
    secs = max(0, secs)
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    ms = int((secs - int(secs)) * 1000)
    if ms == 1000:
        h += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def seconds_to_ass_time(secs: float) -> str:
    """Convert float seconds to ASS timestamp: H:MM:SS.CC."""
    secs = max(0, secs)
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    cs = int((secs - int(secs)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# ---------------------------------------------------------------------------
# SRT block parsing
# ---------------------------------------------------------------------------
def parse_srt_blocks(text: str) -> list[dict]:
    """
    Parse SRT text into list of {index, start, end, text}.
    Handles both comma and dot decimal separators in timecodes.
    """
    blocks = re.split(r"\n\s*\n", text.strip())
    parsed = []
    for block in blocks:
        lines = [l.rstrip("\r") for l in block.splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        tm = TIME_RE.search(lines[1])
        if not tm:
            continue
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue
        parsed.append(
            {
                "index": index,
                "start": normalize_timecode(tm.group(1)),
                "end": normalize_timecode(tm.group(2)),
                "text": "\n".join(lines[2:]).strip(),
            }
        )
    return parsed


# ---------------------------------------------------------------------------
# Quality score extraction
# ---------------------------------------------------------------------------
QUALITY_RE = re.compile(r"质量自评[：:]\s*(\d+)\s*/\s*10")


def extract_quality_score(text: str) -> tuple[int, str]:
    """
    Extract quality self-check score from translated text.
    Returns (score, text_without_score_tag). Score is 0 if not found.
    """
    text = text.strip()
    match = QUALITY_RE.search(text)
    if not match:
        return 0, text
    score = int(match.group(1))
    clean = QUALITY_RE.sub("", text).strip()
    # remove trailing blank lines
    clean = re.sub(r"\n+$", "", clean)
    return score, clean


# ---------------------------------------------------------------------------
# Prompt version (binds to model + template + glossary)
# ---------------------------------------------------------------------------
def compute_prompt_version(
    template: str,
    model_id: str,
    glossary_hash: str = "none",
) -> str:
    """
    Compute a version hash for the translation prompt.
    Binds to model_id so that model upgrades automatically invalidate
    stale cached translations.
    """
    data = f"{model_id}|{glossary_hash}|{template}"
    return hashlib.sha256(data.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Chunk file path helpers
# ---------------------------------------------------------------------------
CHUNKS_DIR = "chunks"


def get_chunks_dir(temp_dir: Path) -> Path:
    """Return the chunks output directory (created if missing)."""
    d = temp_dir / CHUNKS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def chunk_prompt_path(temp_dir: Path, chunk_id: int) -> Path:
    return get_chunks_dir(temp_dir) / f"chunk_{chunk_id}.prompt.txt"


def chunk_translated_path(temp_dir: Path, chunk_id: int) -> Path:
    return get_chunks_dir(temp_dir) / f"chunk_{chunk_id}.translated.txt"
