# Phase Definitions and Contracts

## Intent Contract

Phase 1 writes `temp/intent.json`.

- JSON schema path: `[SKILL_ROOT]/references/schemas/intent.schema.json`
- Do not maintain a second inline schema in this file.
- `temp/intent.json` must validate against `intent.schema.json` before the runner continues.

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

### Phase 3: Metadata + Caption Discovery + Video Download

- **Runner**: `phase_runner.py --phase 3 --video-id [ID]`
- **Scripts** (called in order):
  1. `scripts/phase_3/metadata_probe.py`: yt-dlp probe → `temp/metadata.json` (video_id, title, duration, has_official_caption, caption_languages)
  2. `scripts/phase_3/caption_discovery.py`: reads metadata, decides `official` or `asr` path → `temp/caption_plan.json`
  3. `scripts/phase_3/video_download.py`: yt-dlp download → `temp/video.mp4`
- **Idempotent**: each script skips if its output already exists and is fresh
- **Canonical outputs**: `temp/metadata.json`, `temp/caption_plan.json`, `temp/video.mp4`
- **Error**: If official captions required (`subtitle_mode=official_only`) but unavailable, caption_discovery fails clearly

### Phase 4: Subtitle Acquisition → Chunk Translation → Align → Export

- **Runner**: `phase_runner.py --phase 4 --video-id [ID]`
- **Pipeline script**: `scripts/phase_4/pipeline.py` (orchestrates 7 atomic steps):
  1. `caption_fetch.py` — official caption path: yt-dlp → `temp/source_segments.json` (skip if ASR)
  2. `audio_extract.py` — ASR path only: `temp/video.mp4` → `temp/source_audio.wav` (skip if official)
  3. `asr.py` + `asr_normalize.py` — ASR path: `temp/source_audio.wav` + WhisperX → `temp/asr_segments.json` → `temp/source_segments.json` (skip if official)
  4. `chunk_build.py` — splits `source_segments.json` into time-bounded chunks → `temp/chunks.json`
  5. `translate_scheduler.py` — parallel subagent translation (CHUNK_PARALLELISM env, default 4); each chunk: `text + glossary_terms + context` → `chunk_N.translated.txt`; writes back `chunks.json` status
  6. `validator.py` — validates all chunks: no missing IDs, no time overlap, no untranslated text → `temp/validation_errors.json` on failure
  7. `align.py` + `export.py` — align translated chunks to source segments → `temp/subtitle_manifest.json` → `temp/bilingual.ass` / `temp/zh_only.ass`
- **Intent-aware behavior**:
  - `subtitle_mode=auto`: use official if available, else ASR
  - `subtitle_mode=official_only`: require official captions, fail if unavailable
  - `subtitle_mode=transcribe`: force ASR regardless of official captions
  - `subtitle_layout=bilingual`: export `bilingual.ass` (source + translated)
  - `subtitle_layout=chinese_only`: export `zh_only.ass`
- **Canonical outputs**:
  - `temp/source_audio.wav` — extracted audio for ASR reuse/debugging
  - `temp/subtitle_manifest.json` — consumed by Phase 6
  - `temp/subtitle_overlay.ass` — alias for Phase 6 compatibility
  - `temp/chunks.json` — per-chunk translation status (completed/failed/pending)
  - `temp/translation_state.json` — translation contract (host model policy, prompt_version, glossary_hash...)
- **Canonical contract**:
  - `source_segments.json` is the single normalized segment artifact used by chunking, align, and export regardless of caption source.
  - `translation_state.json` must include the translation contract at minimum: `model_id`, `prompt_version`, `glossary_hash`, `chunking_hash`, `source_hash`, `validator_version`.
  - Cache reuse is valid only when the translation contract matches; otherwise rerun translation for affected chunks.
- **Style presets** (Phase 6 reburn):
  - `mobile_default` (recommended): white text, black outline, Chinese size 18
  - `high_contrast`: larger text, heavier outline
  - ... (see `srt_to_ass.py` for full list)

### Phase 5: Voiceover

- **Runner**: `phase_runner.py --phase 5 --video-id [ID]`
- **Script**: `scripts/phase_5/voiceover_tts.py`
- **Output**: `temp/zh_voiceover.mp3`
- **Skip**: If user chose original audio in Phase 1

### Phase 6: Compose Final Video

- **Runner**: `phase_runner.py --phase 6 --video-id [ID]`
- **Script**: `scripts/phase_6/video_muxer.py`
- **Output**: `final/final_video.mp4`
- **Modes**: `--original-audio` or with voiceover
- **Rerender workflow**:
  - If preview quality is poor, edit `temp/subtitle_style.json` and change `preset`
  - Re-run Phase 6 to regenerate `.ass` and reburn subtitles without retranslating

### Phase 7: Cover

- **Runner**: `phase_runner.py --phase 7 --video-id [ID]`
- **Script**: `scripts/phase_7/cover.py`
- **Input artifacts**:
  - `temp/cover_options.json` (generated by runner if absent)
  - `temp/cover_selection.json` (written after user selects a title/subtitle)
  - `temp/cover_bg.jpg` (auto-extracted from `video.mp4` if no custom background is provided)
- **Output**: `final/cover_final.jpg`
- **Interactive**:
  - Runner generates 3-5 persisted title options in `temp/cover_options.json`
  - Main agent presents them to the user and writes the chosen title/subtitle to `temp/cover_selection.json`
  - Re-running Phase 7 consumes the selection and renders the cover

### Phase 8: Description Generator

- **Runner**: spawn subagent using `agents/description.md`
- **Agent provides**: `video_id`
- **Output**: `final/description.txt` — Bilibili-ready description in plain Chinese text

### Phase 9: Upload Preview

- **Runner**: spawn subagent using `agents/uploader.md`
- **Agent provides**: `video_id`
- **Output**: `final/preview.txt` with exactly one Filebin URL line
- **Reference**: `references/filebin.md` (API details)

### Phase 10: Bilibili Publish

- **Runner**: `phase_runner.py --phase 10 --video-id [ID]`
- **Blocking check**: Fails immediately if `final_video.mp4` is missing — must run Phase 6 first.
- **Two publish modes**:
  - `draft` — writes `final/publish_result.json` with `mode: draft`. Runner skips Bilibili upload, confirms preview is available.
  - `formal` — full Bilibili publish via `agent-browser` skill UI automation. Writes `final/publish_result.json` with `mode: formal` and `bilibili_url`.
- **Pre-check**: Confirm artifacts exist, generate metadata, confirm mode with user.
- **Success artifact**: `final/publish_result.json`
- **Required fields**: `status`, `video_id`, `mode`, `title`, `description`, `tags`, and either `bilibili_url` or `draft_id`
- **Reference**: `agents/publisher.md`

### Phase 11: Cleanup

- **Runner**: `phase_runner.py --phase 11 --video-id [ID]`
- **Script**: `scripts/phase_11/cleaner.py`
- **Skip**: Unless user explicitly requested cleanup in Phase 1
