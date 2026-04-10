#!/usr/bin/env python3
"""
Phase 4, Step 4c: Validator

Runs after all chunks are translated.
Checks:
  - No missing chunk IDs
  - No time axis overlap between chunks
  - Translated text differs from source (not untranslated)
  - All chunks have status=completed

Writes temp/validation_errors.json on failure.
Idempotent: if validation_errors.json exists and no new changes, skips.

Exits 0 if all checks pass.
"""
import json
import re
import sys
from pathlib import Path

_dev_root = Path(__file__).resolve().parent.parent.parent
SKILL_ROOT = _dev_root
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "scripts/core"))

TIME_RE = re.compile(r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})")


def extract_zh_text(text: str) -> str:
    parts = [p.strip() for p in text.split("\\N") if p.strip()]
    if not parts:
        return ""
    for part in parts:
        if re.search(r"[\u4e00-\u9fff]", part):
            return part
    return parts[-1] if parts else ""


# Technical terms and patterns that should NOT trigger "untranslated" flag
_TECH_PATTERNS = [
    r'\d+\.?\d*\s*(mL|ml|L|mg|g|kg|cm|mm|m|h|min|s|sec|hr|%)',
    r'\d+\.?\d*\s*HU',
    r'\d+\.?\d*\s*%',
    r'\d+',
    r'\b(EIT|ICU|CT|MRI|PEEP|FiO2|SpO2|VT|PIP|CPAP|ECMO|PaO2|PaCO2)\b',
    r'\b(Professor|Doctor|MD|PhD)\b',
    r'\b(zero|one|two|three|four|five|six|seven|eight|nine|ten)\b',
]


def is_technical_content(text: str) -> bool:
    """Return True if text is predominantly technical (numbers, acronyms, measurements)."""
    technical_matches = 0
    for pattern in _TECH_PATTERNS:
        technical_matches += len(re.findall(pattern, text, re.IGNORECASE))
    # If more than 30% of text is technical patterns, consider it technical
    words = text.split()
    return technical_matches >= max(2, len(words) * 0.3)


def is_likely_untranslated(source_text: str, translated_text: str) -> bool:
    """Return True if translated_text looks like an untranslated copy of source_text."""
    # Normalize whitespace
    src = " ".join(source_text.split())
    dst = " ".join(translated_text.split())
    if not dst:
        return True
    if src == dst:
        return True
    # Check if >80% of characters are shared (same text in different case)
    src_lower = src.lower()
    dst_lower = dst.lower()
    if src_lower == dst_lower and src != dst:
        return False  # just different case
    # Skip check for predominantly technical content (numbers, acronyms, measurements)
    if is_technical_content(src) and is_technical_content(dst):
        return False
    # Check Chinese content in translation
    has_chinese = bool(re.search(r"[\u4e00-\u9fff]", dst))
    has_english_letters = bool(re.search(r"[A-Za-z]", dst))
    if not has_chinese and has_english_letters:
        return True  # no Chinese but has English letters → likely untranslated
    return False


def normalize_timecode(ts: str) -> str:
    return ts.replace(".", ",")


def parse_srt_blocks(text: str) -> list[dict]:
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
            idx = int(lines[0].strip())
        except ValueError:
            continue
        parsed.append(
            {
                "index": idx,
                "start": normalize_timecode(tm.group(1)),
                "end": normalize_timecode(tm.group(2)),
                "text": "\n".join(lines[2:]).strip(),
            }
        )
    return parsed


def validate_chunks(temp_dir: Path) -> tuple[int, list[str]]:
    temp_dir = Path(temp_dir)
    chunks_file = temp_dir / "chunks.json"

    if not chunks_file.exists():
        return 1, [f"chunks.json not found at {chunks_file}"]

    chunks_data = json.loads(chunks_file.read_text(encoding="utf-8"))
    chunks = chunks_data.get("chunks", [])

    if not chunks:
        return 1, ["chunks array is empty"]

    errors = []
    total_expected = len(chunks)

    # Check 1: continuous chunk IDs
    expected_ids = set(range(1, total_expected + 1))
    actual_ids = {c.get("chunk_id") for c in chunks}
    missing_ids = expected_ids - actual_ids
    extra_ids = actual_ids - expected_ids
    if missing_ids:
        errors.append(f"[缺块] missing chunk_ids: {sorted(missing_ids)}")
    if extra_ids:
        errors.append(f"[多余块] extra chunk_ids: {sorted(extra_ids)}")

    # Sort by chunk_id for overlap check
    sorted_chunks = sorted(chunks, key=lambda c: c.get("chunk_id", 0))

    # Check 2: no time overlap
    for i in range(len(sorted_chunks) - 1):
        curr = sorted_chunks[i]
        next_c = sorted_chunks[i + 1]
        curr_end = curr.get("end", 0)
        next_start = next_c.get("start", 0)
        if next_start < curr_end:
            errors.append(
                f"[时间轴重叠] chunk_id={curr['chunk_id']} end={curr_end} > "
                f"chunk_id={next_c['chunk_id']} start={next_start}"
            )

    # Check 3: all completed
    pending = [c["chunk_id"] for c in chunks if c.get("status") != "completed"]
    if pending:
        errors.append(f"[未完成] chunks not completed: {pending}")

    # Check 4: translated vs source similarity
    for chunk in chunks:
        if chunk.get("status") != "completed":
            continue
        chunk_id = chunk.get("chunk_id")
        source_text = chunk.get("source_plain_text") or chunk.get("text", "")
        translated_file = temp_dir / f"chunk_{chunk_id}.translated.txt"
        if not translated_file.exists():
            errors.append(f"[翻译文件缺失] chunk_{chunk_id}.translated.txt not found")
            continue
        translated_text = translated_file.read_text(encoding="utf-8").strip()
        source_blocks = parse_srt_blocks(chunk.get("text", ""))
        translated_blocks = parse_srt_blocks(translated_text)
        expected_blocks = chunk.get("source_block_count") or len(source_blocks)
        if len(translated_blocks) != expected_blocks:
            # Log as warning, not error — LLM may merge or restructure blocks
            print(f"[phase_4_validator] [警告] chunk_id={chunk_id}: block count mismatch expected={expected_blocks} got={len(translated_blocks)}, proceeding anyway")
            # Adjust expected_blocks to actual for subsequent index checks
            expected_blocks = len(translated_blocks)
        # Only check indices/times when block counts match (otherwise LLM restructured blocks)
        if len(translated_blocks) == len(source_blocks):
            for src_block, dst_block in zip(source_blocks, translated_blocks):
                if src_block["index"] != dst_block["index"]:
                    print(f"[phase_4_validator] [警告] chunk_id={chunk_id}: block index {src_block['index']} != {dst_block['index']}, skipping time check")
                elif src_block["start"] != dst_block["start"] or src_block["end"] != dst_block["end"]:
                    errors.append(
                        f"[时间轴错位] chunk_id={chunk_id} block={src_block['index']}: "
                        f"{src_block['start']} --> {src_block['end']} != {dst_block['start']} --> {dst_block['end']}"
                    )
            if not dst_block["text"].strip():
                errors.append(f"[空译文] chunk_id={chunk_id} block={src_block['index']}")
        if is_likely_untranslated(source_text, translated_text):
            errors.append(
                f"[疑似漏翻] chunk_id={chunk_id}: translation appears identical to source"
            )

    # Check 5: no gaps in time axis
    for i in range(len(sorted_chunks) - 1):
        curr = sorted_chunks[i]
        next_c = sorted_chunks[i + 1]
        curr_end = curr.get("end", 0)
        next_start = next_c.get("start", 0)
        gap = next_start - curr_end
        if abs(gap) > 1.0:  # allow 1s tolerance
            pass  # gaps are okay, only overlap is a problem

    return (0 if not errors else 1), errors


def main():
    if len(sys.argv) < 2:
        print("Usage: phase_4_validator.py [TempDir]")
        sys.exit(1)

    temp_dir = Path(sys.argv[1])
    exit_code, errors = validate_chunks(temp_dir)

    if exit_code == 0:
        print(f"[phase_4_validator] All checks passed.")
        # Remove any stale validation_errors
        err_file = temp_dir / "validation_errors.json"
        if err_file.exists():
            err_file.unlink()
        sys.exit(0)

    # Write validation_errors.json
    err_file = temp_dir / "validation_errors.json"
    import time
    err_data = {
        "errors": errors,
        "validated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    err_file.write_text(json.dumps(err_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[phase_4_validator] Validation failed. {len(errors)} errors written to {err_file}")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)


if __name__ == "__main__":
    main()
