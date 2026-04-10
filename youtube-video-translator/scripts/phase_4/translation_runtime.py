"""
Shared translation runtime helpers.

This module keeps translation execution host-agnostic:
1. Prefer an explicitly configured runner or command template.
2. Support Claude Code, Gemini CLI, and OpenClaw as first-class runners.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

_dev_root = Path(__file__).resolve().parent.parent.parent
SKILL_ROOT = _dev_root
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "scripts/core"))

RUNNER_ALIASES = {"claude-code": "claude", "gemini-cli": "gemini"}
KNOWN_RUNNERS = ("claude", "gemini", "openclaw")


def resolve_translation_model_id() -> str:
    runner = resolve_translation_runner()
    if runner in KNOWN_RUNNERS:
        return "host_default"
    return "unconfigured"


def list_available_runners() -> list[str]:
    available = []
    for runner in KNOWN_RUNNERS:
        if shutil.which(runner):
            available.append(runner)
    return available


def resolve_translation_runner() -> str:
    requested = (
        os.environ.get("TRANSLATION_RUNNER")
        or os.environ.get("TRANSLATOR_SUBAGENT_RUNNER")
        or "auto"
    ).strip().lower()
    requested = RUNNER_ALIASES.get(requested, requested)

    if os.environ.get("TRANSLATOR_SUBAGENT_CMD") or os.environ.get("SUBAGENT_CMD"):
        return "custom"

    if requested == "none":
        return requested

    if requested != "auto":
        return requested

    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude"
    if os.environ.get("OPENCLAW_STATE_DIR") or os.environ.get("OPENCLAW_PROFILE"):
        return "openclaw"

    available = list_available_runners()
    if len(available) == 1:
        return available[0]
    return "auto"


def resolve_translation_provider() -> str:
    configured = os.environ.get("TRANSLATION_PROVIDER")
    if configured:
        return configured

    runner = resolve_translation_runner()
    if runner == "custom":
        return "subagent_custom"
    if runner in KNOWN_RUNNERS:
        return f"subagent_{runner}"

    return "unavailable"


def resolve_translation_strategy() -> str:
    return os.environ.get("TRANSLATION_STRATEGY", "primary_model")


def resolve_runner_name() -> str:
    runner = resolve_translation_runner()
    if runner != "auto":
        return runner
    return "none"


def run_subagent(
    task: str,
    prompt_file: Path,
    translated_file: Path,
    agent_def: Path,
    timeout: int = 300,
) -> tuple[bool, str | None, str]:
    runner = resolve_translation_runner()

    if runner == "custom":
        return _run_custom_subagent(task, prompt_file, translated_file, agent_def, timeout)
    if runner == "claude":
        return _run_claude(task, prompt_file, translated_file, agent_def, timeout)
    if runner == "gemini":
        return _run_gemini(task, prompt_file, translated_file, agent_def, timeout)
    if runner == "openclaw":
        return _run_openclaw(task, prompt_file, translated_file, agent_def, timeout)

    if runner == "auto":
        available = ", ".join(list_available_runners()) or "none"
        return False, f"multiple or no runners available; set TRANSLATION_RUNNER explicitly (detected: {available})", runner
    return False, f"unsupported runner: {runner}", runner


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _build_embedded_prompt(task: str, prompt_file: Path, agent_def: Path) -> str:
    prompt_text = _read_text(prompt_file)
    return (
        "You are the delegated subtitle translator for youtube-video-translator.\n"
        "Follow these hard requirements exactly:\n"
        "1. Preserve every subtitle block index and timecode exactly.\n"
        "2. Output Chinese translation only. Do not keep the English source text.\n"
        "3. Do not merge, split, reorder, or drop subtitle blocks.\n"
        "4. Output valid SRT only. No markdown fences, no commentary, no explanations.\n"
        "5. If the prompt contains glossary terms, follow them.\n\n"
        f"Reference contract: {agent_def.name}\n\n"
        f"## Delegated Task\n"
        f"{task}\n\n"
        f"## Authoritative Prompt\n"
        f"{prompt_text}\n\n"
        f"Return only the translated SRT content. Do not add markdown fences or commentary."
    )


def _normalize_text_output(text: str) -> str:
    return text.strip().strip("`").strip()


def _extract_json_blob(text: str) -> dict:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[index:])
            return obj
        except json.JSONDecodeError:
            continue
    raise RuntimeError("No JSON object found in runner output")


def _merge_runner_output(result: subprocess.CompletedProcess[str]) -> str:
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    return "\n".join(part for part in (stdout, stderr) if part)


def _run_custom_subagent(
    task: str,
    prompt_file: Path,
    translated_file: Path,
    agent_def: Path,
    timeout: int,
) -> tuple[bool, str | None, str]:
    template = os.environ.get("TRANSLATOR_SUBAGENT_CMD") or os.environ.get("SUBAGENT_CMD")
    if not template:
        return False, "no subagent runner configured", "custom"

    values = {
        "task": task,
        "input": str(prompt_file),
        "output": str(translated_file),
        "agent_def": str(agent_def),
    }
    rendered = template.format_map(values)
    cmd = shlex.split(rendered)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "custom runner not found", "custom"
    except subprocess.TimeoutExpired:
        return False, "custom runner timed out", "custom"

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        return False, f"custom runner failed: {stderr[:200]}", "custom"

    if not translated_file.exists():
        return False, "custom runner produced no output file", "custom"
    return True, None, "custom"


def _run_claude(
    task: str,
    prompt_file: Path,
    translated_file: Path,
    agent_def: Path,
    timeout: int,
) -> tuple[bool, str | None, str]:
    if not shutil.which("claude"):
        return False, "claude runner not found", "claude"

    prompt = _build_embedded_prompt(task, prompt_file, agent_def)
    cmd = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--bare",
        "--tools",
        "",
        "--no-session-persistence",
        "--system-prompt",
        "Return plain text only. Never mention tools. Never emit XML, tool-call markup, or commentary.",
        prompt,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "claude runner timed out", "claude"

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        return False, f"claude runner failed: {stderr[:200]}", "claude"

    try:
        payload = json.loads((result.stdout or "").strip())
        text = payload[-1]["result"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        return False, f"claude runner returned invalid JSON: {exc}", "claude"

    translated_file.write_text(_normalize_text_output(text), encoding="utf-8")
    return True, None, "claude"


def _run_gemini(
    task: str,
    prompt_file: Path,
    translated_file: Path,
    agent_def: Path,
    timeout: int,
) -> tuple[bool, str | None, str]:
    if not shutil.which("gemini"):
        return False, "gemini runner not found", "gemini"

    prompt = _build_embedded_prompt(task, prompt_file, agent_def)
    cmd = ["gemini", "-p", prompt, "--output-format", "json"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "gemini runner timed out", "gemini"

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        return False, f"gemini runner failed: {stderr[:200]}", "gemini"

    try:
        payload = _extract_json_blob(_merge_runner_output(result))
        text = payload["response"]
    except (RuntimeError, KeyError, TypeError) as exc:
        return False, f"gemini runner returned invalid JSON: {exc}", "gemini"

    translated_file.write_text(_normalize_text_output(text), encoding="utf-8")
    return True, None, "gemini"


def _run_openclaw(
    task: str,
    prompt_file: Path,
    translated_file: Path,
    agent_def: Path,
    timeout: int,
) -> tuple[bool, str | None, str]:
    if not shutil.which("openclaw"):
        return False, "openclaw runner not found", "openclaw"

    prompt = _build_embedded_prompt(task, prompt_file, agent_def)
    agent_id = os.environ.get("OPENCLAW_AGENT_ID", "main")
    cmd = ["openclaw", "agent", "--local", "--agent", agent_id, "--json", "-m", prompt]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "openclaw runner timed out", "openclaw"

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        return False, f"openclaw runner failed: {stderr[:200]}", "openclaw"

    try:
        payload = _extract_json_blob(_merge_runner_output(result))
        chunks = payload["payloads"]
        text = "".join(item.get("text", "") for item in chunks).strip()
    except (RuntimeError, KeyError, TypeError, AttributeError) as exc:
        return False, f"openclaw runner returned invalid JSON: {exc}", "openclaw"

    translated_file.write_text(_normalize_text_output(text), encoding="utf-8")
    return True, None, "openclaw"
