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
  1. `scripts/phase_3_metadata_probe.py`: yt-dlp probe → `temp/metadata.json` (video_id, title, duration, has_official_caption, caption_languages)
  2. `scripts/phase_3_caption_discovery.py`: reads metadata, decides `official` or `asr` path → `temp/caption_plan.json`
  3. `scripts/phase_3_video_download.py`: yt-dlp download → `temp/video.mp4`
- **Idempotent**: each script skips if its output already exists and is fresh
- **Canonical outputs**: `temp/metadata.json`, `temp/caption_plan.json`, `temp/video.mp4`
- **Error**: If official captions required (`subtitle_mode=official_only`) but unavailable, caption_discovery fails clearly

### Phase 4: Subtitle Acquisition → Chunk Translation → Align → Export

- **Runner**: `phase_runner.py --phase 4 --video-id [ID]`
- **Pipeline** (7 atomic steps, all idempotent):
  1. `phase_4_caption_fetch.py` — official caption path: yt-dlp → `temp/source_segments.json` (skip if ASR)
  2. `phase_4_audio_extract.py` — ASR path only: `temp/video.mp4` → `temp/source_audio.wav` (skip if official)
  3. `phase_4_asr.py` + `phase_4_asr_normalize.py` — ASR path: `temp/source_audio.wav` + WhisperX → `temp/asr_segments.json` → `temp/source_segments.json` (skip if official)
  4. `phase_4_chunk_build.py` — splits `source_segments.json` into time-bounded chunks → `temp/chunks.json`
  5. `phase_4_translate_scheduler.py` — parallel subagent translation (CHUNK_PARALLELISM env, default 4); each chunk: `text + glossary_terms + context` → `chunk_N.translated.txt`; writes back `chunks.json` status
  6. `phase_4_validator.py` — validates all chunks: no missing IDs, no time overlap, no untranslated text → `temp/validation_errors.json` on failure
  7. `phase_4_align.py` + `phase_4_export.py` — align translated chunks to source segments → `temp/subtitle_manifest.json` → `temp/bilingual.ass` / `temp/zh_only.ass`
- **Intent-aware behavior**:
  - `subtitle_mode=auto`: use official if available, else ASR
  - `subtitle_mode=official_only`: require official captions, fail if unavailable
  - `subtitle_mode=transcribe`: force ASR regardless of official captions
  - `subtitle_layout=bilingual`: export `bilingual.ass` (source + translated)
  - `subtitle_layout=chinese_only`: export `zh_only.ass`
- **Canonical outputs**:
  - `temp/source_audio.wav` — extracted audio for ASR reuse/debugging
  - `temp/subtitle_manifest.json` — consumed by Phase 7
  - `temp/subtitle_overlay.ass` — alias for Phase 7 compatibility
  - `temp/chunks.json` — per-chunk translation status (completed/failed/pending)
  - `temp/translation_state.json` — translation contract (host model policy, prompt_version, glossary_hash...)
- **Canonical contract**:
  - `source_segments.json` is the single normalized segment artifact used by chunking, align, and export regardless of caption source.
  - `translation_state.json` must include the translation contract at minimum: `model_id`, `prompt_version`, `glossary_hash`, `chunking_hash`, `source_hash`, `validator_version`.
  - Cache reuse is valid only when the translation contract matches; otherwise rerun translation for affected chunks.
- **Failure isolation**: single chunk failure does not affect other chunks; failed chunks retryable individually
- **Glossary**: user places `temp/glossary.json` (`[{term, translation}, ...]`) before Phase 4; merged into each chunk's `glossary_terms` at chunk_build time
- **Translation model policy**:
  - The skill does not choose a model itself. It uses the model already enabled by the host agent/CLI you invoked it from.
  - `model_id` in `temp/translation_state.json` records host-managed model policy rather than a skill-selected model name.
  - Preferred host selection: set `TRANSLATION_RUNNER=claude`, `TRANSLATION_RUNNER=gemini`, or `TRANSLATION_RUNNER=openclaw`.
  - OpenClaw-specific override: set `OPENCLAW_AGENT_ID` if you want to use an agent other than the default `main`.
  - Fully custom host wiring: set `TRANSLATOR_SUBAGENT_CMD` with placeholders `{task}`, `{input}`, `{output}`, `{agent_def}`.
  - If delegated translation cannot run, Phase 4 fails the affected chunk and records the runner error. There is no direct API fallback.
- **Style presets** (Phase 7 reburn):
  - `mobile_default` (recommended): white text, black outline, Chinese size 18
  - `high_contrast`: larger text, heavier outline
  - `soft_dark`: warm-white text, dark outline
  - `bold_yellow`: yellow emphasis for tutorials
  - `black_white_thin`: black text, white outline (1.5px), Chinese 18/English 13
  - `black_white_medium`: black text, white outline (2.5px), Chinese 20/English 14
  - `black_white_thick`: black text, white outline (3.5px), Chinese 22/English 15
  - `black_white_bold`: deep black text, white outline (3.0px) + white shadow, Chinese 21/English 14
  - `neon_glow`: cyan text with dark teal glow, sci-fi aesthetic
  - `warm_cream`: cream text with brown outline, vintage warmth
  - `retro_orange`: orange text with dark brown outline, cinematic feel
  - `mint_fresh`: mint green text with dark green outline, fresh & clean
  - `elegant_pink`: light pink text with deep purple outline, elegant & soft
  - `cinema_gold`: golden text with dark brown outline, classic cinema style
  - `minimal_white`: pure white text, nearly no outline, minimalist

### Phase 5: Voiceover

- **Runner**: `phase_runner.py --phase 5 --video-id [ID]`
- **Script**: `scripts/voiceover_tts.py`
- **Output**: `temp/zh_voiceover.mp3`
- **Skip**: If user chose original audio in Phase 1

### Phase 6: Compose Final Video

- **Runner**: `phase_runner.py --phase 6 --video-id [ID]`
- **Script**: `scripts/phase_6_video_muxer.py`
- **Output**: `final/final_video.mp4`
- **Modes**: `--original-audio` or with voiceover
- **Rerender workflow**:
  - If preview quality is poor, edit `temp/subtitle_style.json` and change `preset`
  - Re-run Phase 6 to regenerate `.ass` and reburn subtitles without retranslating
  - Re-run Phase 8 to upload a fresh preview if needed

### Phase 7: Cover

- **Runner**: `phase_runner.py --phase 7 --video-id [ID]`
- **Script**: `scripts/phase_7_cover.py`
- **Input artifacts**:
  - `temp/cover_options.json` (generated by runner if absent)
  - `temp/cover_selection.json` (written after user selects a title/subtitle)
  - `temp/cover_bg.jpg` (auto-extracted from `video.mp4` if no custom background is provided)
- **Output**: `final/cover_final.jpg`
- **Interactive**:
  - Runner generates 3-5 persisted title options in `temp/cover_options.json`
  - Main agent presents them to the user and writes the chosen title/subtitle to `temp/cover_selection.json`
  - Re-running Phase 7 consumes the selection and renders the cover

### Phase 8: Upload Preview

- **Runner**: `phase_runner.py --phase 8 --video-id [ID]`
- **Reference**: `references/filebin.md`
- **Output**: `final/preview.txt` with exactly one Filebin URL line

### Phase 9: Bilibili Publish

- **Runner**: `phase_runner.py --phase 9 --video-id [ID]`
- **Blocking check**: Fails immediately if `final_video.mp4` is missing — must run Phase 7 first.
- **Two publish modes**:
  - `draft` — writes `final/publish_result.json` with `mode: draft`. Runner skips Bilibili upload, confirms preview is available.
  - `formal` — full Bilibili publish via `agent-browser` skill UI automation. Writes `final/publish_result.json` with `mode: formal` and `bilibili_url`.
- **Pre-check**: Confirm artifacts exist, generate metadata, confirm mode with user.
- **Success artifact**: `final/publish_result.json`
- **Required fields**: `status`, `video_id`, `mode`, `title`, `description`, `tags`, and either `bilibili_url` or `draft_id`
- **Reference**: `agents/publisher.md`

### Phase 10: Cleanup

- **Runner**: `phase_runner.py --phase 10 --video-id [ID]`
- **Script**: `scripts/cleaner.py`
- **Skip**: Unless user explicitly requested cleanup in Phase 1
