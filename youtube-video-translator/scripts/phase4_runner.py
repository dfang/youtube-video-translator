import json
import os
import shutil
import sys
from datetime import datetime, timezone

from translate_worker import (
    detect_batch_completeness,
    generate_prompt_for_batch,
    merge_translated_batches,
    verify_all_batches,
    verify_translated_srt,
    write_batches,
)


STATE_FILE_NAME = "phase4_state.json"
DEFAULT_MAX_ATTEMPTS = 3


def now_utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def abs_path(path):
    return os.path.abspath(path)


def state_path(output_dir):
    return os.path.join(output_dir, STATE_FILE_NAME)


def load_state(output_dir):
    path = state_path(output_dir)
    if not os.path.exists(path):
        raise RuntimeError(f"未找到状态文件: {path}，请先执行 start。")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    path = state_path(state["output_dir"])
    state["updated_at"] = now_utc()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return path


def build_batch_record(batch_id, batch_file):
    batch_file = abs_path(batch_file)
    prompt_file = os.path.splitext(batch_file)[0] + ".prompt.txt"
    translated_file = os.path.splitext(batch_file)[0] + ".translated.srt"
    return {
        "batch_id": batch_id,
        "batch_file": batch_file,
        "prompt_file": prompt_file,
        "translated_file": translated_file,
        "status": "pending",
        "attempts": 0,
        "last_error": "",
        "verified_at": "",
    }


def command_start(source_srt, output_dir, batch_size=50, max_attempts=DEFAULT_MAX_ATTEMPTS):
    os.makedirs(output_dir, exist_ok=True)
    batch_files, manifest_path = write_batches(source_srt, output_dir, batch_size=batch_size)
    batches = [build_batch_record(i, batch_file) for i, batch_file in enumerate(batch_files, start=1)]
    state = {
        "mode": "session_primary_model",
        "source_srt": abs_path(source_srt),
        "output_dir": abs_path(output_dir),
        "manifest_path": abs_path(manifest_path),
        "batch_size": batch_size,
        "max_attempts": max_attempts,
        "total_batches": len(batches),
        "created_at": now_utc(),
        "updated_at": now_utc(),
        "merged_output": abs_path(os.path.join(output_dir, "zh_translated.srt")),
        "final_verified": False,
        "batches": batches,
    }
    path = save_state(state)
    print(f"STARTED total_batches={len(batches)} state={path}")


def next_batch_record(state):
    for status in ("failed", "pending"):
        for batch in state["batches"]:
            if batch["status"] == status and batch["attempts"] < state.get("max_attempts", DEFAULT_MAX_ATTEMPTS):
                return batch
    return None


def command_next(output_dir):
    state = load_state(output_dir)
    batch = next_batch_record(state)
    if batch is None:
        print("NO_PENDING_BATCH")
        return

    prompt = generate_prompt_for_batch(batch["batch_file"], batch["prompt_file"])
    print(f"BATCH_ID={batch['batch_id']}")
    print(f"BATCH_FILE={batch['batch_file']}")
    print(f"PROMPT_FILE={batch['prompt_file']}")
    print(f"TRANSLATED_FILE={batch['translated_file']}")
    print("PROMPT_BEGIN")
    print(prompt.rstrip())
    print("PROMPT_END")


def find_batch(state, batch_id):
    for batch in state["batches"]:
        if batch["batch_id"] == batch_id:
            return batch
    raise RuntimeError(f"未找到 batch_id={batch_id}")


def command_submit(output_dir, batch_id, translated_source_path):
    state = load_state(output_dir)
    batch = find_batch(state, batch_id)
    translated_source_path = abs_path(translated_source_path)
    max_attempts = state.get("max_attempts", DEFAULT_MAX_ATTEMPTS)

    if not os.path.exists(translated_source_path):
        raise RuntimeError(f"提交失败，文件不存在: {translated_source_path}")

    if batch["status"] == "verified":
        raise RuntimeError(f"batch_id={batch_id} 已通过校验，无需重复提交。")
    if batch["attempts"] >= max_attempts:
        raise RuntimeError(
            f"batch_id={batch_id} 已达到最大重试次数 {max_attempts}，请先执行 retry。"
        )

    os.makedirs(os.path.dirname(batch["translated_file"]), exist_ok=True)
    shutil.copyfile(translated_source_path, batch["translated_file"])

    batch["attempts"] += 1
    issues = verify_translated_srt(batch["batch_file"], batch["translated_file"])
    if issues:
        batch["status"] = "failed"
        batch["last_error"] = " | ".join(issues)
        batch["verified_at"] = ""
        save_state(state)
        print(
            f"SUBMIT_FAILED batch_id={batch_id} attempts={batch['attempts']}/{max_attempts}"
        )
        for issue in issues:
            print(issue)
        sys.exit(2)

    batch["status"] = "verified"
    batch["last_error"] = ""
    batch["verified_at"] = now_utc()
    save_state(state)
    print(
        f"SUBMIT_OK batch_id={batch_id} attempts={batch['attempts']}/{max_attempts} "
        f"translated_file={batch['translated_file']}"
    )


def command_retry(output_dir, batch_id):
    state = load_state(output_dir)
    batch = find_batch(state, batch_id)
    max_attempts = state.get("max_attempts", DEFAULT_MAX_ATTEMPTS)

    if batch["status"] == "verified":
        raise RuntimeError(f"batch_id={batch_id} 已通过校验，不能 retry。")
    if batch["status"] != "failed":
        raise RuntimeError(f"batch_id={batch_id} 当前状态为 {batch['status']}，只能重试 failed 批次。")

    batch["status"] = "pending"
    batch["attempts"] = 0
    batch["last_error"] = ""
    batch["verified_at"] = ""
    save_state(state)
    print(f"RETRY_RESET batch_id={batch_id} max_attempts={max_attempts}")


def build_status_payload(state):
    counts = {}
    for batch in state["batches"]:
        counts[batch["status"]] = counts.get(batch["status"], 0) + 1

    current = next_batch_record(state)
    blocked = [
        batch["batch_id"]
        for batch in state["batches"]
        if batch["status"] != "verified"
        and batch["attempts"] >= state.get("max_attempts", DEFAULT_MAX_ATTEMPTS)
    ]

    return {
        "state_path": state_path(state["output_dir"]),
        "mode": state["mode"],
        "source_srt": state["source_srt"],
        "output_dir": state["output_dir"],
        "manifest_path": state["manifest_path"],
        "merged_output": state["merged_output"],
        "batch_size": state["batch_size"],
        "max_attempts": state.get("max_attempts", DEFAULT_MAX_ATTEMPTS),
        "total_batches": state["total_batches"],
        "final_verified": state["final_verified"],
        "counts": {
            "pending": counts.get("pending", 0),
            "failed": counts.get("failed", 0),
            "verified": counts.get("verified", 0),
        },
        "next_batch_id": current["batch_id"] if current else None,
        "next_status": current["status"] if current else None,
        "blocked_batches": blocked,
        "batches": state["batches"],
    }


def command_status(output_dir, json_mode=False):
    state = load_state(output_dir)
    payload = build_status_payload(state)

    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(f"STATE={payload['state_path']}")
    print(f"TOTAL={payload['total_batches']}")
    print(f"MAX_ATTEMPTS={payload['max_attempts']}")
    for name in ("pending", "failed", "verified"):
        print(f"{name.upper()}={payload['counts'].get(name, 0)}")

    if payload["next_batch_id"] is not None:
        print(f"NEXT_BATCH_ID={payload['next_batch_id']}")
        print(f"NEXT_STATUS={payload['next_status']}")
    else:
        print("NEXT_BATCH_ID=")
        print("NEXT_STATUS=")

    blocked = payload["blocked_batches"]
    if blocked:
        print(f"BLOCKED_BATCHES={','.join(str(i) for i in blocked)}")


def command_finalize(output_dir):
    state = load_state(output_dir)
    incomplete = [batch["batch_id"] for batch in state["batches"] if batch["status"] != "verified"]
    if incomplete:
        raise RuntimeError(f"仍有未完成批次: {incomplete}")

    has_error, reports = verify_all_batches(state["output_dir"])
    for line in reports:
        print(line)
    if has_error:
        raise RuntimeError("逐批校验失败，终止 finalize。")

    completeness = detect_batch_completeness(state["output_dir"], state["manifest_path"])
    if not completeness["ok"]:
        raise RuntimeError(
            f"批次完整性检查失败: missing={completeness['missing']}, extra={completeness['extra']}"
        )

    merge_translated_batches(state["output_dir"], state["merged_output"], state["manifest_path"])
    final_issues = verify_translated_srt(state["source_srt"], state["merged_output"])
    if final_issues:
        for issue in final_issues:
            print(issue)
        raise RuntimeError("最终合并字幕校验失败。")

    state["final_verified"] = True
    save_state(state)
    print(f"FINALIZE_OK merged_output={state['merged_output']}")


def print_usage():
    print("用法:")
    print("  python phase4_runner.py start [SourceSrtPath] [OutputDir] [BatchSize可选] [--max-attempts N]")
    print("  python phase4_runner.py next [OutputDir]")
    print("  python phase4_runner.py submit [OutputDir] [BatchId] [TranslatedSrtPath]")
    print("  python phase4_runner.py retry [OutputDir] [BatchId]")
    print("  python phase4_runner.py status [OutputDir] [--json]")
    print("  python phase4_runner.py finalize [OutputDir]")


def parse_start_args(argv):
    if len(argv) < 4:
        print_usage()
        sys.exit(1)

    source_srt = argv[2]
    output_dir = argv[3]
    batch_size = 50
    max_attempts = DEFAULT_MAX_ATTEMPTS

    i = 4
    while i < len(argv):
        token = argv[i]
        if token == "--max-attempts":
            if i + 1 >= len(argv):
                raise RuntimeError("参数错误: --max-attempts 需要数值")
            max_attempts = int(argv[i + 1])
            i += 2
            continue
        if token.startswith("--"):
            raise RuntimeError(f"未知参数: {token}")
        batch_size = int(token)
        i += 1

    if max_attempts < 1:
        raise RuntimeError("max_attempts 必须 >= 1")
    if batch_size < 1:
        raise RuntimeError("batch_size 必须 >= 1")

    return source_srt, output_dir, batch_size, max_attempts


def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    cmd = sys.argv[1]
    try:
        if cmd == "start":
            source_srt, output_dir, batch_size, max_attempts = parse_start_args(sys.argv)
            command_start(source_srt, output_dir, batch_size, max_attempts)
        elif cmd == "next":
            if len(sys.argv) < 3:
                print_usage()
                sys.exit(1)
            command_next(sys.argv[2])
        elif cmd == "submit":
            if len(sys.argv) < 5:
                print_usage()
                sys.exit(1)
            command_submit(sys.argv[2], int(sys.argv[3]), sys.argv[4])
        elif cmd == "retry":
            if len(sys.argv) < 4:
                print_usage()
                sys.exit(1)
            command_retry(sys.argv[2], int(sys.argv[3]))
        elif cmd == "status":
            if len(sys.argv) < 3:
                print_usage()
                sys.exit(1)
            json_mode = len(sys.argv) >= 4 and sys.argv[3] == "--json"
            if len(sys.argv) >= 4 and not json_mode:
                raise RuntimeError(f"未知参数: {sys.argv[3]}")
            command_status(sys.argv[2], json_mode=json_mode)
        elif cmd == "finalize":
            if len(sys.argv) < 3:
                print_usage()
                sys.exit(1)
            command_finalize(sys.argv[2])
        else:
            print(f"未知命令: {cmd}")
            print_usage()
            sys.exit(1)
    except RuntimeError as e:
        print(str(e))
        sys.exit(2)


if __name__ == "__main__":
    main()
