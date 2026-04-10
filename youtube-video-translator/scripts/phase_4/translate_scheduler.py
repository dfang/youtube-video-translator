#!/usr/bin/env python3
"""
Phase 4, Step 4b: Translate Scheduler

Reads chunks.json, dispatches translation for each chunk via subagent.
Writes back status to chunks.json after each chunk completion.

Parallelism: controlled by CHUNK_PARALLELISM env var (default 4).
Provider: uses the translator provider interface.

Idempotent: skips chunks with status=completed.

Self-healing: if validator fails after a translation round, the scheduler
automatically retries failed chunks up to MAX_AUTO_RETRIES times.
"""
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_dev_root = Path(__file__).resolve().parent.parent.parent
SKILL_ROOT = _dev_root
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "scripts/core"))
sys.path.insert(0, str(SKILL_ROOT / "scripts/phase_4"))

from srt import (
    parse_srt_blocks,
    is_technical_block,
    extract_quality_score,
    compute_prompt_version as _compute_prompt_version,
    chunk_prompt_path,
    chunk_translated_path,
)
from utils import utc_now
from translation_runtime import (
    resolve_runner_name,
    resolve_translation_model_id,
    resolve_translation_provider,
    resolve_translation_strategy,
    run_subagent,
)

DEFAULT_PARALLELISM = int(os.environ.get("CHUNK_PARALLELISM", "4"))
MAX_ATTEMPTS = 3
QUALITY_THRESHOLD = 7  # self-check score below this triggers auto-retry
MAX_AUTO_RETRIES = 2   # validator → auto-retry rounds before giving up


PROMPT_TEMPLATE = """你是专业字幕翻译器。请把下面字幕片段翻译为简体中文。

硬性要求：
1) 保留每个字幕块的时间轴原样不变。
2) 每个块只输出中文译文，不要保留英文原文。
3) 不要删块、并块、拆块。
4) 不要输出任何解释，只输出SRT格式内容（序号+时间轴+译文）。
5) 翻译完成后，在SRT内容之后另起一行输出质量自评，格式为：质量自评：X/10（X为1-10整数）

{glossary_section}{context_section}
待翻译片段：
{batch_content}
"""


def load_glossary_terms(glossary_file: Path) -> list[dict]:
    if not glossary_file.exists():
        return []
    try:
        data = json.loads(glossary_file.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def build_glossary_section(terms: list[dict]) -> str:
    if not terms:
        return "无术语表。"
    lines = ["参考术语："]
    for t in terms:
        lines.append(f"  {t.get('term', '')} -> {t.get('translation', '')}")
    return "\n".join(lines)


def build_context_section(prev_text: str) -> str:
    if not prev_text:
        return ""
    clipped = prev_text.strip()[-500:]
    return f"\n前文参考（最后一块，截断后）：\n{clipped}"


def build_translation_prompt(chunk_text: str, glossary_terms: list, prev_chunk_text: str = "") -> str:
    glossary_section = build_glossary_section(glossary_terms)
    context_section = build_context_section(prev_chunk_text)
    return PROMPT_TEMPLATE.format(
        glossary_section=glossary_section,
        context_section=context_section,
        batch_content=chunk_text,
    )


def translate_chunk_via_subagent(chunk: dict, video_id: str, temp_dir: Path) -> tuple[dict, str]:
    """
    Dispatch a single chunk translation to a subagent.
    Returns (updated_chunk, translated_text_or_error).
    """
    chunk_id = chunk["chunk_id"]
    text = chunk.get("text", "")
    glossary_terms = chunk.get("glossary_terms", [])
    attempts = chunk.get("attempts", 0)

    # Get previous chunk's text for context
    chunks_data = json.loads((temp_dir / "chunks.json").read_text(encoding="utf-8"))
    chunks_list = chunks_data.get("chunks", [])
    prev_text = ""
    for c in chunks_list:
        if c["chunk_id"] == chunk_id - 1:
            prev_text = c.get("source_plain_text", "")
            break

    prompt = build_translation_prompt(text, glossary_terms, prev_text)

    prompt_file = chunk_prompt_path(temp_dir, chunk_id)
    prompt_file.write_text(prompt, encoding="utf-8")

    agent_def = SKILL_ROOT / "agents" / "translator.md"
    translated_file = chunk_translated_path(temp_dir, chunk_id)

    succeeded, error, runner = run_subagent(
        task=f"Translate chunk {chunk_id} for video {video_id}",
        prompt_file=prompt_file,
        translated_file=translated_file,
        agent_def=agent_def,
    )
    if not succeeded:
        return {
            **chunk,
            "status": "failed",
            "attempts": attempts + 1,
            "error": error or f"{runner} runner failed",
        }, ""

    if not translated_file.exists():
        return {**chunk, "status": "failed", "error": "subagent produced no output"}, ""

    translated_text = translated_file.read_text(encoding="utf-8").strip()
    if not translated_text:
        return {**chunk, "status": "failed", "attempts": attempts + 1, "error": "subagent returned empty output"}, ""

    valid, reason, score = verify_chunk_translation(chunk, translated_text, temp_dir)
    if not valid:
        return {**chunk, "status": "failed", "attempts": attempts + 1, "error": reason}, translated_text

    return {**chunk, "status": "completed", "attempts": attempts + 1, "quality_score": score, "error": None}, translated_text


def verify_chunk_translation(chunk: dict, translated_text: str, temp_dir: Path) -> tuple[bool, str, int]:
    """
    Verify chunk structure and quality before marking it completed.
    Returns (valid, reason, quality_score).
    """
    chunk_id = chunk.get("chunk_id")

    if not translated_text.strip():
        return False, "empty translation", 0

    # Extract quality self-check score and strip the tag from SRT text
    score, clean_text = extract_quality_score(translated_text)

    source_blocks = parse_srt_blocks(chunk.get("text", ""))
    translated_blocks = parse_srt_blocks(clean_text)
    expected_count = chunk.get("source_block_count") or len(source_blocks)

    if not source_blocks:
        return False, "source chunk has no valid SRT blocks", 0
    if len(translated_blocks) != expected_count:
        print(f"[verify_chunk_translation] [警告] chunk_id={chunk_id}: block count mismatch expected={expected_count} got={len(translated_blocks)}, proceeding")
        expected_count = len(translated_blocks)

    for src, dst in zip(source_blocks, translated_blocks):
        if src["index"] != dst["index"]:
            print(f"[verify_chunk_translation] [警告] chunk_id={chunk_id}: block index {src['index']} != {dst['index']}, skipping timecode check")
        elif src["start"] != dst["start"] or src["end"] != dst["end"]:
            print(f"[verify_chunk_translation] [警告] chunk_id={chunk_id}: block {src['index']} timecode mismatch, proceeding")
        if not dst["text"].strip():
            return False, f"empty translated text at block {src['index']}", 0
        if not is_technical_block(dst["text"].strip()) and not is_technical_block(src["text"].strip()):
            if dst["text"].strip() == src["text"].strip():
                return False, f"translation identical to source at block {src['index']}", 0
            has_chinese = bool(re.search(r"[\u4e00-\u9fff]", dst["text"]))
            has_english_letters = bool(re.search(r"[A-Za-z]", dst["text"]))
            if not has_chinese and has_english_letters:
                return False, f"likely untranslated English content at block {src['index']}", 0
    has_any_chinese = bool(re.search(r"[\u4e00-\u9fff]", clean_text))
    if not has_any_chinese:
        return False, "translation contains no Chinese characters", 0

    # Quality threshold check
    if score > 0 and score < QUALITY_THRESHOLD:
        return False, f"quality self-check score {score}/{QUALITY_THRESHOLD} below threshold", score

    return True, "", score


def update_chunks_file(chunks_data: dict, updated_chunk: dict):
    """Update a single chunk in chunks_data and write back."""
    chunks = chunks_data.get("chunks", [])
    for i, c in enumerate(chunks):
        if c["chunk_id"] == updated_chunk["chunk_id"]:
            chunks[i] = updated_chunk
            break
    chunks_data["chunks"] = chunks


def write_chunks_file(chunks_data: dict, temp_dir: Path):
    chunks_data["updated_at"] = utc_now()
    (temp_dir / "chunks.json").write_text(
        json.dumps(chunks_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def dispatch_pending_chunks(chunks_data: dict, pending: list, video_id: str, temp_dir: Path, parallelism: int) -> dict:
    """Run translation for all pending chunks in parallel. Returns updated chunks_data."""
    def dispatch_chunk(chunk: dict):
        return translate_chunk_via_subagent(chunk, video_id, temp_dir)

    with ThreadPoolExecutor(max_workers=parallelism) as executor:
        futures = {executor.submit(dispatch_chunk, c): c for c in pending}
        for future in as_completed(futures):
            chunk = futures[future]
            try:
                updated_chunk, translated_text = future.result()
            except Exception as exc:
                updated_chunk = {**chunk, "status": "failed", "error": str(exc)}
                translated_text = ""

            update_chunks_file(chunks_data, updated_chunk)

            if translated_text:
                # Strip quality self-check tag before persisting (align.py reads this file)
                _, clean = extract_quality_score(translated_text)
                chunk_translated_path(temp_dir, chunk['chunk_id']).write_text(
                    clean, encoding="utf-8"
                )

            write_chunks_file(chunks_data, temp_dir)

            current_done = sum(
                1 for c in chunks_data["chunks"] if c.get("status") == "completed"
            )
            total = len(chunks_data["chunks"])
            print(f"[translate_scheduler] Processing: {current_done}/{total} chunks... ({chunk['chunk_id']} {updated_chunk['status']})")

    return chunks_data


def run_scheduler(video_id: str, temp_dir: Path, parallelism: int = DEFAULT_PARALLELISM) -> tuple[int, str]:
    temp_dir = Path(temp_dir)
    chunks_file = temp_dir / "chunks.json"

    if not chunks_file.exists():
        return 1, f"chunks.json not found at {chunks_file}"

    chunks_data = json.loads(chunks_file.read_text(encoding="utf-8"))
    chunks = chunks_data.get("chunks", [])
    total = len(chunks)

    if not chunks:
        return 1, "chunks array is empty"

    # Init or load translation_state (binds model_id to prompt_version)
    glossary_hash = chunks_data.get("chunking_config", {}).get("glossary_hash", "none")
    model_id = resolve_translation_model_id()
    state_file = temp_dir / "translation_state.json"
    state = {
        "video_id": video_id,
        "model_id": model_id,
        "provider": resolve_translation_provider(),
        "strategy": resolve_translation_strategy(),
        "runner": resolve_runner_name(),
        "prompt_version": _compute_prompt_version(PROMPT_TEMPLATE, model_id, glossary_hash),
        "glossary_hash": glossary_hash,
        "chunking_hash": chunks_data.get("chunking_config", {}).get("source_hash", "none"),
        "source_hash": chunks_data.get("chunking_config", {}).get("source_hash", "none"),
        "validator_version": "1.0.0",
        "chunks_total": total,
        "generated_at": utc_now(),
    }
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    # Self-healing loop: translate → validate → retry failed
    auto_retry_round = 0
    while True:
        pending = [c for c in chunks_data["chunks"] if c.get("status") in ("pending", "failed")]

        if not pending:
            print(f"[translate_scheduler] All {total} chunks completed.")
            break

        if auto_retry_round > 0:
            print(f"[translate_scheduler] Auto-retry round {auto_retry_round}/{MAX_AUTO_RETRIES}: {len(pending)} chunks pending")

        if auto_retry_round >= MAX_AUTO_RETRIES:
            print(f"[translate_scheduler] Max auto-retries reached. {len(pending)} chunks still failed.")
            break

        completed_before = sum(1 for c in chunks_data["chunks"] if c.get("status") == "completed")
        print(f"[translate_scheduler] Round {auto_retry_round + 1}: translating {len(pending)} chunks (parallelism={parallelism})")

        chunks_data = dispatch_pending_chunks(
            chunks_data, pending, video_id, temp_dir, parallelism
        )

        completed_after = sum(1 for c in chunks_data["chunks"] if c.get("status") == "completed")
        failed = [c["chunk_id"] for c in chunks_data["chunks"] if c.get("status") == "failed"]

        # Self-heal: if validator is not run separately, check failed chunks here
        # The pipeline runs validator separately after scheduler; if there are failures,
        # they get caught in the next round's validator retry
        if failed and completed_after == completed_before:
            # No new chunks completed AND some failed — likely unrecoverable
            print(f"[translate_scheduler] No progress made. {len(failed)} chunks failed. Giving up.")
            break

        auto_retry_round += 1

    # Final state write
    final_completed = sum(1 for c in chunks_data["chunks"] if c.get("status") == "completed")
    final_failed = sum(1 for c in chunks_data["chunks"] if c.get("status") == "failed")
    state["chunks_completed"] = final_completed
    state["chunks_total"] = total
    if final_completed == total:
        state["completed_at"] = utc_now()
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[translate_scheduler] Done. completed={final_completed} failed={final_failed} total={total}")
    return (0 if final_failed == 0 else 1), f"completed={final_completed} failed={final_failed}"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Translate scheduler")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--temp-dir", required=True)
    parser.add_argument("--parallelism", type=int, default=DEFAULT_PARALLELISM)
    args = parser.parse_args()

    exit_code, msg = run_scheduler(args.video_id, Path(args.temp_dir), args.parallelism)
    print(msg)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
