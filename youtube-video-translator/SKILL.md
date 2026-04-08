---
name: youtube-video-translator
description: End-to-end YouTube video localization to Chinese with resumable phases (download, subtitle acquisition/transcription, translation, TTS, cover, mux, optional Bilibili publish). Use this skill whenever the user asks to translate/repost/localize a YouTube video, including Chinese requests like "翻译视频/搬运视频", or provides a YouTube URL.
---

# youtube-video-translator

Translate a YouTube video into Chinese with resumable, file-based phases.

## Setup and Requirements

Please refer to [`references/setup.md`](references/setup.md) for system requirements and host-specific setup instructions.

## Core Principle: State Lives on Disk

All phase state is persisted to `translations/[VIDEO_ID]/.phase-state.json`.
On every invocation, read this file first to determine where to resume.
**Never redo a completed phase** — if output already exists, skip.

## Operating Style

- **Keep context minimal**: Only load files and state relevant to the current phase.
- **Proactive Reporting (Critical)**: Always inform the user before starting a phase and after it completes.
- **Iterative Execution**: To ensure the user sees progress, **execute phases one by one** using the `--phase` flag. Do not run all phases at once unless specifically requested.
- **Chinese Feedback**: All user-facing progress updates should be in Chinese.
- **State Check**: Before starting any work, check `.phase-state.json` to see if a previous run can be resumed.

## Phase Entry Point

For any phase, use the unified phase runner. It is recommended to run one phase at a time to keep the user informed:

```bash
# Example: Running Phase 3
python3 "[SKILL_ROOT]/scripts/phase_runner.py" run --video-id [VIDEO_ID] --phase 3
```

The runner handles: state loading, phase skipping (if already done), execution, and state update.

## Phase Progress Reporting (Directives for Agent)

The agent MUST relay progress to the user. When you see a structured output line from the runner, translate its meaning for the user:

- `[Phase X/10][RUNNING]`: Tell the user: "正在执行阶段 X: <name>..."
- `[Phase X/10][DONE]`: Tell the user: "阶段 X 已完成。输出文件: <artifact>"
- `[Phase X/10][HEARTBEAT]`: (Optional) Update user if a phase is taking a long time.
- `[Phase X/10][FAILED]`: Show the error and suggest a fix.

## Progressive Documentation Map

> [!IMPORTANT]  
> To prevent context overload, deep technical mechanics have been split into the following reference guides. **Use `view_file` to read them ONLY when explicitly needed:**
>
> - **Phase Logic & Steps**: Read [`references/phases.md`](references/phases.md) if you need to know exactly what a specific Phase (0-10) does or what intent options exist.
> - **Artifacts, Paths & Subagents**: Read [`references/architecture.md`](references/architecture.md) if you are debugging file paths, exploring the state-driven artifact map, or launching parallel chunk translation subagents.
> - **Error Handing & Resuming**: Read [`references/troubleshooting.md`](references/troubleshooting.md) if a phase fails or you need deep details on resuming after an interruption.
