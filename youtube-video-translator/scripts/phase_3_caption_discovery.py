#!/usr/bin/env python3
"""
Phase 3, Step 2: Caption Discovery

Reads temp/metadata.json to decide:
  - official: has_official_caption=True AND 'en' in caption_languages
  - asr: otherwise

Outputs temp/caption_plan.json.

Idempotent: skips if caption_plan.json already exists and source matches.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent


def is_caption_plan_fresh(temp_dir: Path, expected_source: str) -> bool:
    plan_file = temp_dir / "caption_plan.json"
    if not plan_file.exists():
        return False
    try:
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        return plan.get("source") == expected_source
    except (json.JSONDecodeError, OSError):
        return False


def discover_caption_plan(temp_dir: Path, subtitle_mode: str = "auto") -> tuple[int, str]:
    """
    Determine caption acquisition path based on metadata.

    subtitle_mode:
      auto       — use official if available, else ASR
      official_only — require official, fail if unavailable
      transcribe  — force ASR regardless of official captions

    Returns (exit_code, message).
    """
    temp_dir = Path(temp_dir)
    metadata_file = temp_dir / "metadata.json"

    if not metadata_file.exists():
        return 1, f"metadata.json not found at {metadata_file}"

    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    has_official = metadata.get("has_official_caption", False)
    caption_languages = metadata.get("caption_languages", [])
    has_english = "en" in caption_languages or any(l.startswith("en") for l in caption_languages)

    # Determine path
    if subtitle_mode == "official_only":
        if not has_official or not has_english:
            return 1, (
                f"official_only mode requires English captions but "
                f"has_official_caption={has_official}, languages={caption_languages}"
            )
        source = "official"
        reason = "User selected official_only mode and English captions are available."
    elif subtitle_mode == "transcribe":
        source = "asr"
        reason = "User selected force-transcribe mode."
    else:  # auto
        if has_official and has_english:
            source = "official"
            reason = f"auto: English captions found in official captions ({caption_languages})."
        else:
            source = "asr"
            reason = f"auto: no English official captions found (has={has_official}, langs={caption_languages})."

    # Check if already done
    if is_caption_plan_fresh(temp_dir, source):
        print(f"[phase_3_caption_discovery] caption_plan.json already fresh (source={source}), skipping.")
        return 0, str(temp_dir / "caption_plan.json")

    plan = {
        "source": source,
        "reason": reason,
        "input_srt": None,  # filled by phase_4_caption_fetch or phase_4_asr
        "languages_checked": caption_languages,
    }

    plan_file = temp_dir / "caption_plan.json"
    plan_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[phase_3_caption_discovery] caption_plan.json written: source={source} reason={reason}")
    return 0, str(plan_file)


def main():
    if len(sys.argv) < 2:
        print("Usage: phase_3_caption_discovery.py [TempDir] [subtitle_mode:auto|official_only|transcribe]")
        sys.exit(1)

    temp_dir = Path(sys.argv[1])
    subtitle_mode = sys.argv[2] if len(sys.argv) > 2 else "auto"

    exit_code, msg = discover_caption_plan(temp_dir, subtitle_mode)
    print(msg)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
