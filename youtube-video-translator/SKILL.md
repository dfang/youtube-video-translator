---
name: youtube-video-translator
description: End-to-end YouTube video localization to Chinese with resumable phases (download, subtitle acquisition/transcription, translation, TTS, cover, mux, optional Bilibili publish). Use this skill whenever the user asks to translate/repost/localize a YouTube video, including Chinese requests like "翻译视频/搬运视频", or provides a YouTube URL.
---

# youtube-video-translator

Translate a YouTube video into Chinese with resumable, file-based phases.

## System Requirements

- **FFmpeg with libass**: Required for hardcoding subtitles.
- **macOS Recommendation**: Install `ffmpeg-full` via Homebrew to ensure all capabilities are present:
  ```bash
  brew install ffmpeg-full
  brew link ffmpeg-full
  ```
- **Fallback**: The skill will attempt to find `ffmpeg-full` or `ffmpeg` with `libass` support automatically. If environment check fails, follow the suggested fix commands.

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

## Canonical Paths

- Skill root: `$HOME/.openclaw/skills/youtube-video-translator`
- Root: `./translations/[VIDEO_ID]/` (Created in the project's current working directory)
- State: `./translations/[VIDEO_ID]/.phase-state.json`

## Phase Entry Point

For any phase, use the unified phase runner. It is recommended to run one phase at a time to keep the user informed:

```bash
# Example: Running Phase 3
python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/phase_runner.py" run --video-id [VIDEO_ID] --phase 3
```

The runner handles: state loading, phase skipping (if already done), execution, and state update.

## Phase Progress Reporting (Directives for Agent)

The agent MUST relay progress to the user. When you see a structured output line from the runner, translate its meaning for the user:

- `[Phase X/10][RUNNING]`: Tell the user: "正在执行阶段 X: <name>..."
- `[Phase X/10][DONE]`: Tell the user: "阶段 X 已完成。输出文件: <artifact>"
- `[Phase X/10][HEARTBEAT]`: (Optional) Update user if a phase is taking a long time.
- `[Phase X/10][FAILED]`: Show the error and suggest a fix.

## Phase 1 Intent Schema

Persist `temp/intent.json` using this schema before continuing past Phase 1:

```json
{
  "audio_mode": "original|voiceover",
  "subtitle_mode": "auto|official_only|transcribe",
  "subtitle_layout": "bilingual|chinese_only",
  "publish": false,
  "cleanup": false,
  "confirmed": true
}
```

Rules:

- `audio_mode` controls whether Phase 5 generates `zh_voiceover.mp3`.
- `subtitle_mode` controls whether Phase 4 prefers official subtitles, requires official subtitles, or forces WhisperX transcription.
- `subtitle_layout` controls whether Phase 4/7 render bilingual subtitles or Chinese-only subtitles.
- `confirmed` must be `true` before the runner continues.

## Phase Definitions (file-based)

### Phase 0: Environment Validation

- **Runner**: `phase_runner.py --phase 0`
- **Script**: `scripts/env_check.py`
- **Output**: Pass/fail + fix commands

### Phase 1: Gather Intents (Interactive)

- **Runner**: `phase_runner.py --phase 1 --video-id [ID]`
- **Agent Action**: **Ask all intent questions at once in a single message.** Do not ask them one by one.
- **Questions**:
  1. 音频模式 (audio_mode): 原声 (original) 还是 语音合成 (voiceover)?
  2. 字幕模式 (subtitle_mode): 自动 (auto), 仅官方 (official_only), 还是 强制转录 (transcribe)?
  3. 字幕布局 (subtitle_layout): 双语 (bilingual) 还是 仅中文 (chinese_only)?
  4. 是否发布到 B 站 (publish)? (true/false)
  5. 任务结束后是否清理临时文件 (cleanup)? (true/false)
- **Default Options**:
  - `audio_mode`: `original`
  - `subtitle_mode`: `auto`
  - `subtitle_layout`: `bilingual`
  - `publish`: `false`
  - `cleanup`: `false`
- **Implicit Consent**: If the user says "开始", "start", "go", or similar without answering specific questions, **immediately use the default options**, write `temp/intent.json` with `confirmed: true`, and proceed to the next phase.
- **Saved to**: `temp/intent.json` (must be valid JSON and `confirmed` set to `true` to pass Phase 1).

### Phase 2: Setup

- **Runner**: `phase_runner.py --phase 2 --video-id [ID]`
- **Script**: `phase_runner.py` handles internally
- **Creates**: `temp/`, `final/` directories, canonical input path `temp/url.txt`
- **Behavior**: If `temp/url.txt` is missing, runner creates a placeholder and returns `WAIT`
- **Main agent responsibility**: Write the YouTube URL into `temp/url.txt`, then rerun Phase 2 or resume
- **Input**: `temp/url.txt` (must contain YouTube URL)

### Phase 3: Video Download

- **Runner**: `phase_runner.py --phase 3 --video-id [ID]`
- **Script**: `scripts/downloader.py`
- **Output**: `temp/raw_video.mp4`

### Phase 4: Subtitle Processing + Translation

- **Runner**: `phase_runner.py --phase 4 --video-id [ID]`
- **Scripts**:
  - `scripts/whisperx_transcriber.py` (if transcribing)
  - `scripts/subtitle_splitter.py`
  - `scripts/phase4_runner.py`
  - `scripts/translate_worker.py`
  - `scripts/srt_to_ass.py`
- **Outputs**:
  - `temp/en_original.srt`
  - `temp/en_audited.srt`
  - `temp/zh_translated.srt`
  - `temp/bilingual.ass` or `temp/zh_only.ass`
  - `temp/subtitle_overlay.ass` (canonical subtitle artifact consumed by Phase 7)
  - `temp/subtitle_style.json` (subtitle style preset selection and optional overrides)
- **Intent-aware behavior**:
  - `subtitle_mode=auto`: use official subtitles if found, otherwise transcribe
  - `subtitle_mode=official_only`: require official subtitles, fail clearly if unavailable
  - `subtitle_mode=transcribe`: skip official subtitles and force WhisperX transcription
  - `subtitle_layout=bilingual`: generate `bilingual.ass`
  - `subtitle_layout=chinese_only`: generate `zh_only.ass`
- **Style presets**:
  - `mobile_default` (recommended): white text, black outline, Chinese size 18, tuned for phones
  - `high_contrast`: larger text and heavier outline for bright or busy frames
  - `soft_dark`: softer warm-white text with dark outline
  - `bold_yellow`: yellow emphasis style for tutorials and commentary
- **Subagent delegation**: Each `batch_N.txt` → `batch_N.translated.srt` can run in parallel subagent
- **Fallback**: If subagents are unavailable, main agent may process batches serially using `phase4_runner.py next/submit/finalize`
- **Verification**: `translate_worker.py verify` after each batch and at end

### Phase 5: Voiceover

- **Runner**: `phase_runner.py --phase 5 --video-id [ID]`
- **Script**: `scripts/voiceover_tts.py`
- **Output**: `temp/zh_voiceover.mp3`
- **Skip**: If user chose original audio in Phase 1

### Phase 6: Cover

- **Runner**: `phase_runner.py --phase 6 --video-id [ID]`
- **Script**: `scripts/cover_generator.py`
- **Input artifacts**:
  - `temp/cover_options.json` (generated by runner if absent)
  - `temp/cover_selection.json` (written after user selects a title/subtitle)
  - `temp/cover_bg.jpg` (auto-extracted from `raw_video.mp4` if no custom background is provided)
- **Output**: `final/cover_final.jpg`
- **Interactive**:
  - Runner generates 3-5 persisted title options in `temp/cover_options.json`
  - Main agent presents them to the user and writes the chosen title/subtitle to `temp/cover_selection.json`
  - Re-running Phase 6 consumes the selection and renders the cover

### Phase 7: Compose Final Video

- **Runner**: `phase_runner.py --phase 7 --video-id [ID]`
- **Script**: `scripts/video_muxer.py`
- **Output**: `final/final_video.mp4`
- **Modes**: `--original-audio` or with voiceover
- **Rerender workflow**:
  - If preview quality is poor, edit `temp/subtitle_style.json` and change `preset`
  - Re-run Phase 7 to regenerate `.ass` and reburn subtitles without retranslating
  - Re-run Phase 8 to upload a fresh preview if needed

### Phase 8: Upload Preview

- **Runner**: `phase_runner.py --phase 8 --video-id [ID]`
- **Reference**: `references/filebin.md`
- **Output**: `final/preview.txt` with exactly one Filebin URL line

### Phase 9: Bilibili Publish

- **Runner**: `phase_runner.py --phase 9 --video-id [ID]`
- **Delegation**: `agent-browser` skill for UI automation
- **Pre-check**: Confirm artifacts exist, generate metadata, confirm mode with user
- **Success artifact**: `final/publish_result.json`
- **Required fields**: `status`, `video_id`, `mode`, `title`, `description`, `tags`, and either `bilibili_url` or `draft_id`
- **Reference**: `agents/publisher.md`

### Phase 10: Cleanup

- **Runner**: `phase_runner.py --phase 10 --video-id [ID]`
- **Script**: `scripts/cleaner.py`
- **Skip**: Unless user explicitly requested cleanup in Phase 1

## Resuming After Interruption

On re-entry, always start with:

```bash
python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/state_manager.py" [VIDEO_ID] load
```

Then run `phase_runner.py` without specifying phase — it will auto-resume from `current_phase`:

```bash
python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/phase_runner.py" run --video-id [VIDEO_ID]
```

## Subagent Contract

When delegating a phase to a subagent:

1. Pass the agent definition file path
2. Pass video_id and specific inputs/outputs as arguments
3. Wait for completion and verify output exists
4. On failure, retry or report back to user

Example subagent launch:

```
Agent: general-purpose
Task: Translate batch N for video abc123
Agent definition: $HOME/.openclaw/skills/youtube-video-translator/agents/translator.md
Input: batch_N.txt in translations/abc123/temp/
Expected output: batch_N.translated.srt in translations/abc123/temp/
```
