---
name: youtube-video-translator
description: End-to-end YouTube video localization to Chinese with resumable phases (download, subtitle acquisition/transcription, translation, TTS, cover, mux, optional Bilibili publish). Use this skill whenever the user asks to translate/repost/localize a YouTube video, including Chinese requests like "翻译视频/搬运视频", or provides a YouTube URL.
---

# youtube-video-translator

Translate a YouTube video into Chinese with resumable, file-based phases.

## Core Principle: State Lives on Disk

All phase state is persisted to `translations/[VIDEO_ID]/.phase-state.json`.
On every invocation, read this file first to determine where to resume.
**Never redo a completed phase** — if output already exists, skip.

## Operating Style

- Keep context minimal. Load only the current phase.
- Prefer scripts over manual steps; refer to `scripts/` for implementation.
- Before each phase, announce in Chinese (e.g., `正在进入字幕处理阶段...`).
- Always emit structured status lines per the Phase Progress Reporting section.

## Canonical Paths

- Skill root: `$HOME/.openclaw/skills/youtube-video-translator`
- Root: `./translations/[VIDEO_ID]/`
- Temp: `./translations/[VIDEO_ID]/temp/`
- Final: `./translations/[VIDEO_ID]/final/`
- State: `./translations/[VIDEO_ID]/.phase-state.json`

## Phase Entry Point

For any phase, use the unified phase runner:

```bash
python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/phase_runner.py" run --video-id [VIDEO_ID] --phase [N]
```

The runner handles: state loading, phase skipping (if already done), execution, state update.

## Phase Progress Reporting (Non-Negotiable)

Every phase transition emits one structured line:

```
[Phase X/10][RUNNING] <phase_name>
[Phase X/10][DONE] <phase_name> | output: <artifact>
[Phase X/10][WAIT] <phase_name> | reason: <why>
[Phase X/10][SKIP] <phase_name> | reason: <why>
[Phase X/10][FAILED] <phase_name> | error: <msg>
```

Long phases emit heartbeats every 60-120s:
```
[Phase X/10][HEARTBEAT] <phase_name> | elapsed: <seconds>s
```

## Phase Definitions (file-based)

### Phase 0: Environment Validation
- **Runner**: `phase_runner.py --phase 0`
- **Script**: `scripts/env_check.py`
- **Output**: Pass/fail + fix commands

### Phase 1: Gather Intents
- **Runner**: `phase_runner.py --phase 1 --video-id [ID]`
- **Mode**: Interactive (main agent asks in Chinese)
- **Collected**: Audio choice, subtitle source, bilingual vs Chinese-only, publish intent, cleanup intent
- **Saved to**: `temp/intent.json`
- **Wait**: Explicit user confirmation before proceeding

### Phase 2: Setup
- **Runner**: `phase_runner.py --phase 2 --video-id [ID]`
- **Script**: `phase_runner.py` handles internally
- **Creates**: `temp/`, `final/` directories, `temp/url.txt`
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
  - `temp/bilingual.ass`
- **Subagent delegation**: Each `batch_N.txt` → `batch_N.translated.srt` can run in parallel subagent
- **Verification**: `translate_worker.py verify` after each batch and at end

### Phase 5: Voiceover
- **Runner**: `phase_runner.py --phase 5 --video-id [ID]`
- **Script**: `scripts/voiceover_tts.py`
- **Output**: `temp/zh_voiceover.mp3`
- **Skip**: If user chose original audio in Phase 1

### Phase 6: Cover
- **Runner**: `phase_runner.py --phase 6 --video-id [ID]`
- **Script**: `scripts/cover_generator.py`
- **Input**: Background image, Chinese title, subtitle
- **Output**: `final/cover_final.jpg`
- **Interactive**: Present 3-5 title options to user, wait for selection

### Phase 7: Compose Final Video
- **Runner**: `phase_runner.py --phase 7 --video-id [ID]`
- **Script**: `scripts/video_muxer.py`
- **Output**: `final/final_video.mp4`
- **Modes**: `--original-audio` or with voiceover

### Phase 8: Upload Preview
- **Runner**: `phase_runner.py --phase 8 --video-id [ID]`
- **Reference**: `references/filebin.md`
- **Output**: `final/preview.txt` with Filebin URL

### Phase 9: Bilibili Publish
- **Runner**: `phase_runner.py --phase 9 --video-id [ID]`
- **Delegation**: `agent-browser` skill for UI automation
- **Pre-check**: Confirm artifacts exist, generate metadata, confirm mode with user
- **Reference**: `agents/publisher.md`

### Phase 10: Cleanup
- **Runner**: `phase_runner.py --phase 10 --video-id [ID]`
- **Script**: `scripts/cleaner.py`
- **Skip**: Only if user explicitly requested cleanup in Phase 1

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
