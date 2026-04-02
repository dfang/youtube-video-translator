---
name: youtube-video-translator
description: End-to-end YouTube video localization to Chinese with resumable phases (download, subtitle acquisition/transcription, translation, TTS, cover, mux, optional Bilibili publish). Use this skill whenever the user asks to translate/repost/localize a YouTube video, including Chinese requests like “翻译视频/搬运视频”, or provides a YouTube URL.
---

# youtube-video-translator

Translate a YouTube video into Chinese with resumable, file-based phases.

## Operating Style (Progressive Disclosure)

- Keep context minimal. Load and execute only the current phase.
- Prefer scripts over manual steps; avoid re-describing logic already in `scripts/`.
- Before each phase, announce in Chinese (e.g., `正在进入字幕处理阶段...`).
- If required output already exists, skip phase and continue.

## Phase Progress Reporting (OpenClaw Required)

- MUST proactively report phase progress in chat; do not wait for user to ask.
- For every phase transition, emit one structured status line using this template:
  - `[Phase X/10][RUNNING] <phase_name>`
  - `[Phase X/10][DONE] <phase_name> | output: <key_artifact>`
  - `[Phase X/10][SKIP] <phase_name> | reason: <why_skipped>`
  - `[Phase X/10][FAILED] <phase_name> | cmd: <failed_cmd> | retry: <retry_cmd>`
- When Phase 4 runs by batches, also emit rolling progress:
  - `[Phase 4/10][RUNNING] batch i/N`
  - `[Phase 4/10][DONE] batch i/N`
- Keep status lines concise, Chinese-friendly, and machine-parseable.

## Orchestration Model (Hybrid)

- Use **main agent** as orchestrator for end-to-end state management.
- Use **sub-agents** only for heavy/parallelizable phases.
- Main agent responsibilities:
  - Track phase progress and resumable checkpoints
  - Dispatch sub-agents with strict input/output contracts
  - Run final gates (`check-batches`, `merge`, `verify`) and decide retries
- Do **not** force sub-agent usage for every phase; keep simple phases on main agent for stability.

### Delegation Matrix

- Main-agent phases (default): 0, 1, 2, 3, 7, 8, 10
- Sub-agent preferred phases:
  - Phase 4 batch translation (parallel by `batch_N.txt`)
  - Phase 6 cover generation (optional delegation)
  - Phase 9 publishing (`agent-browser`)

## Canonical Paths

- Skill root: `$HOME/.openclaw/skills/youtube-video-translator`
- Root: `./translations/[VIDEO_ID]/`
- Temp: `./translations/[VIDEO_ID]/temp/`
- Final: `./translations/[VIDEO_ID]/final/`

## Phase Graph (Resumable)

0. Environment validation
1. Intent collection (and user confirmation)
2. Setup
3. Video download
4. Subtitle processing + translation
5. Voiceover
6. Cover
7. Video composition
8. Upload preview (Filebin)
9. Optional Bilibili publish
10. Optional cleanup

---

## Phase 0: Environment Validation

- Goal: fail fast on missing runtime dependencies.
- Command: `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/env_check.py"`
- Pass condition:
  - `ffmpeg` exists and has `libass`
  - Python deps are installed from `requirements.txt`
- If failed, stop and return fix commands.

## Phase 1: Gather Intents (Chinese)

Ask and summarize in Chinese:

- Keep original audio or use Chinese dub
- Subtitle source: download vs transcribe
- Output subtitle style: Chinese-only vs bilingual
- Whether to publish to Bilibili
- Whether to clean temp files
- Do not ask for title in this phase

Then ask: `确认开始翻译吗？` and wait for explicit confirmation.

## Phase 2: Setup

- Parse `VIDEO_ID` from URL.
- Create dirs:
  - `./translations/[VIDEO_ID]/temp/`
  - `./translations/[VIDEO_ID]/final/`
- Save source URL: `./translations/[VIDEO_ID]/temp/url.txt`

## Phase 3: Download Video

- Output target: `./translations/[VIDEO_ID]/temp/raw_video.mp4`
- Command:
  - `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/downloader.py" "[URL]" "./translations/[VIDEO_ID]/temp"`

## Phase 4: Subtitle Processing + Translation

### 4.1 Acquire source subtitle

If subtitle download mode:
- Try `yt-dlp --write-subs` flow through existing downloader pipeline.
- If unavailable, fallback to transcription with:
  - `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/whisperx_transcriber.py" "./translations/[VIDEO_ID]/temp/raw_video.mp4" "./translations/[VIDEO_ID]/temp"`

If transcription mode:
- `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/whisperx_transcriber.py" "./translations/[VIDEO_ID]/temp/raw_video.mp4" "./translations/[VIDEO_ID]/temp"`
- Expected output: `./translations/[VIDEO_ID]/temp/en_original.srt`

### 4.2 Segment audit

- `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/subtitle_splitter.py" "./translations/[VIDEO_ID]/temp/en_original.srt" "./translations/[VIDEO_ID]/temp/en_audited.srt"`
- `subtitle_splitter.py` 兼容 `00:00:10,894` 与 `00:00:10.894` 两种时间分隔格式。

### 4.3 Batch preparation + translation workflow

- Generate batches:
  - `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/translate_worker.py" prepare "./translations/[VIDEO_ID]/temp/en_audited.srt" "./translations/[VIDEO_ID]/temp"`
- Translation model source (A-mode): use the current channel/session primary model directly.
- Do NOT ask for or require Gemini/OpenAI/Claude API keys in this phase.
- Dispatch each batch to a translation sub-agent (parallel allowed), contract:
  - Input: `./translations/[VIDEO_ID]/temp/batch_N.txt`
  - Output: `./translations/[VIDEO_ID]/temp/batch_N.translated.srt`
  - Hard rule: keep index/timecode unchanged; no merge/split/drop
- For each batch file:
  - Build prompt (optional):
    - `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/translate_worker.py" prompt "./translations/[VIDEO_ID]/temp/batch_N.txt" "./translations/[VIDEO_ID]/temp/batch_N.prompt.txt"`
  - Save result as:
    - `./translations/[VIDEO_ID]/temp/batch_N.translated.srt`
- After each batch translation, immediately verify that batch:
  - `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/translate_worker.py" verify "./translations/[VIDEO_ID]/temp/batch_N.txt" "./translations/[VIDEO_ID]/temp/batch_N.translated.srt"`
- After all batches are done, run full per-batch verification sweep:
  - `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/translate_worker.py" verify-batches "./translations/[VIDEO_ID]/temp"`
  - (optional flags) `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/translate_worker.py" verify-batches "./translations/[VIDEO_ID]/temp" --max-cps 15 --glossary "./translations/[VIDEO_ID]/temp/glossary.txt"`
- Before merge, enforce completeness check:
  - `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/translate_worker.py" check-batches "./translations/[VIDEO_ID]/temp" "./translations/[VIDEO_ID]/temp/translation_manifest.json"`
- Merge translated batches into:
  - `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/translate_worker.py" merge "./translations/[VIDEO_ID]/temp" "./translations/[VIDEO_ID]/temp/zh_translated.srt"`
  - Output:
  - `./translations/[VIDEO_ID]/temp/zh_translated.srt`
- After merge, enforce final full-file verification:
  - `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/translate_worker.py" verify "./translations/[VIDEO_ID]/temp/en_audited.srt" "./translations/[VIDEO_ID]/temp/zh_translated.srt"`

### 4.4 Translation verification (strict)

- `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/translate_worker.py" verify "./translations/[VIDEO_ID]/temp/en_audited.srt" "./translations/[VIDEO_ID]/temp/zh_translated.srt"`
- Optional glossary consistency check:
  - `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/translate_worker.py" verify "./translations/[VIDEO_ID]/temp/en_audited.srt" "./translations/[VIDEO_ID]/temp/zh_translated.srt" "./translations/[VIDEO_ID]/temp/glossary.txt"`
- Fail conditions include: block count mismatch, index mismatch, timecode mismatch, suspected untranslated blocks, CPS overflow, glossary mismatch.

### 4.5 Render ASS

- `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/srt_to_ass.py" "./translations/[VIDEO_ID]/temp/zh_translated.srt" "./translations/[VIDEO_ID]/temp/bilingual.ass"`
- Subtitle style contract:
  - Layout: Chinese on top, English on bottom (`\\N{\\fs14}`)
  - Font: `PingFang SC Semibold`
  - Font size: Chinese `16`, English `14`
  - Colors: primary text black, outline white
  - Outline width: `1`

## Phase 5: Voiceover

- Skip if user chose original audio.
- Command:
  - `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/voiceover_tts.py" "./translations/[VIDEO_ID]/temp/zh_translated.srt" "./translations/[VIDEO_ID]/temp/zh_voiceover.mp3"`
- Output: `./translations/[VIDEO_ID]/temp/zh_voiceover.mp3`

## Phase 6: Cover

- Prepare background image (thumbnail or extracted frame).
- Generate 3-5 recommended Chinese titles based on video content and translated subtitles.
- Ask user to pick one recommended title before rendering cover/publish metadata.
- `SUBTITLE` source: use creator/topic short label derived from Phase 1 confirmed publish metadata (or empty string if user requests title-only cover).
- Command:
  - `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/cover_generator.py" "[BG_PATH]" "./translations/[VIDEO_ID]/final/cover_final.jpg" "[ZH_TITLE]" "[SUBTITLE]"`
- Output: `./translations/[VIDEO_ID]/final/cover_final.jpg`

## Phase 7: Compose Final Video

- Command:
  - Keep original audio:
    - `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/video_muxer.py" "./translations/[VIDEO_ID]/temp/raw_video.mp4" "" "./translations/[VIDEO_ID]/temp/bilingual.ass" "./translations/[VIDEO_ID]" --original-audio`
  - Chinese dub:
    - `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/video_muxer.py" "./translations/[VIDEO_ID]/temp/raw_video.mp4" "./translations/[VIDEO_ID]/temp/zh_voiceover.mp3" "./translations/[VIDEO_ID]/temp/bilingual.ass" "./translations/[VIDEO_ID]"`
- `video_muxer.py` 的第 4 个参数兼容三种传法：
  - 项目根目录 `./translations/[VIDEO_ID]`（推荐）
  - `final` 目录 `./translations/[VIDEO_ID]/final`
  - 完整文件路径 `./translations/[VIDEO_ID]/final/final_video.mp4`
- Output: `./translations/[VIDEO_ID]/final/final_video.mp4`

## Phase 8: Upload Preview to Filebin

- Goal: generate a shareable preview URL for quick review.
- Reference doc: `./references/filebin.md`
- Command:
  - `BIN="[VIDEO_ID]"`
  - `curl -sS -X PUT -H "Content-Type: video/mp4" --data-binary "@./translations/[VIDEO_ID]/final/final_video.mp4" "https://filebin.net/$BIN/final_video.mp4"`
  - `echo "https://filebin.net/$BIN/final_video.mp4" > "./translations/[VIDEO_ID]/final/preview.txt"`
- Preview URL:
  - `https://filebin.net/$BIN/final_video.mp4`
- Optional verify:
  - `curl -I "https://filebin.net/$BIN/final_video.mp4"`

## Phase 9: Optional Bilibili Publish (Subagent Delegation)

Run only when user explicitly asks to publish/save draft (e.g., `publish to Bilibili`, `post`, `save draft`, `发布到B站`, `保存草稿`).

- Delegate browser UI automation to `agent-browser` skill.
- Main agent responsibilities before delegation:
  - Confirm final artifacts exist (`final_video.mp4`, optional `cover_final.jpg`)
  - Generate title/description/tags in Chinese
  - Provide publish mode: post now vs save draft
- Subagent responsibilities:
  - Open Bilibili creator page
  - Upload video and fill metadata
  - Execute user-selected publish action

## Phase 10: Optional Cleanup

- Run only if user explicitly asks to clean.
- Command:
  - `python3 "$HOME/.openclaw/skills/youtube-video-translator/scripts/cleaner.py" "./translations/[VIDEO_ID]/temp"`

---

## Quality Gates

- Timing/format: translated SRT must keep index and valid timecode.
- CPS: follow `translate_worker.py verify` output.
- Subtitle render: `bilingual.ass` must be burnable by ffmpeg with `libass`.
- Subtitle visual spec must match Phase 4.5 style contract.
- Final output: `final_video.mp4` must exist before publish phase.
- Preview gate: Filebin preview URL should be generated in Phase 8 before publish.
- Preview record: `./translations/[VIDEO_ID]/final/preview.txt` must exist before publish.

## Failure Handling

- On any phase failure, always emit:
  - `[Phase X/10][FAILED] <phase_name> | cmd: <failed_cmd> | retry: <retry_cmd>`
  - one-line root cause summary in Chinese
- Resume from last completed phase; do not redo completed outputs.
