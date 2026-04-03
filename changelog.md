# Changelog

## 2026-04-02

### Added
- Added `check-batches` command in `youtube-video-translator/scripts/translate_worker.py` to detect missing/extra translated batch files before merge.
- Added `youtube-video-translator/scripts/phase4_runner.py` to make Phase 4 resumable and enforce the session-model translation workflow via:
  - `start`
  - `next`
  - `submit`
  - `status`
  - `finalize`
  - `retry`
- Added stricter translation verification in `youtube-video-translator/scripts/translate_worker.py`:
  - block count consistency
  - subtitle index consistency
  - timecode alignment consistency
  - suspected untranslated block detection
  - glossary consistency checks (`EN -> ZH`)
- Added orchestration guidance in `youtube-video-translator/SKILL.md` for **hybrid mode**:
  - main agent handles scheduling/progress/quality gates
  - sub-agents handle heavy/parallelizable phases (especially batch translation)

### Changed
- Updated batch translation workflow in `youtube-video-translator/SKILL.md` to enforce:
  1. `phase4_runner.py start`
  2. `phase4_runner.py next`
  3. per-batch session-model translation
  4. `phase4_runner.py submit`
  5. `phase4_runner.py finalize`
- Updated `youtube-video-translator/scripts/phase4_runner.py` with:
  - `--max-attempts` start option
  - `status --json` machine-readable output
  - `retry` command to reset exhausted failed batches
- Updated `verify` behavior in `youtube-video-translator/scripts/translate_worker.py` to return non-zero exit code on integrity failures.
- Updated `youtube-video-translator/scripts/video_muxer.py` output argument handling to accept project dir, `final` dir, or explicit `.mp4` file path, preventing nested `final_video.mp4/final_video.mp4` output paths.
- Updated `youtube-video-translator/scripts/translate_worker.py` optional arg parsing for `verify` and `verify-batches`:
  - supports legacy positional args
  - supports `--glossary` and `--max-cps` flags
  - supports `max_cps`-only input
- Updated `youtube-video-translator/scripts/voiceover_tts.py` temp workspace strategy to use unique `tempfile.mkdtemp(...)` directories with guaranteed cleanup in `finally`.
- Updated `youtube-video-translator/scripts/env_check.py` dependency checks to map import names to install package names (`PIL` -> `Pillow`, `yt_dlp` -> `yt-dlp`).
- Updated `youtube-video-translator/SKILL.md`:
  - documented `subtitle_splitter.py` support for both `,` and `.` SRT millisecond delimiters
  - documented `video_muxer.py` output target compatibility modes
  - added `verify-batches` optional flag usage example

### Quality / Style Contract
- Subtitle visual spec is explicitly documented in `youtube-video-translator/SKILL.md` and aligned with implementation:
  - Chinese on top, English on bottom
  - Chinese size 16, English size 14
  - primary text black, white outline
  - outline width 1

### Notes
- This update addresses three reported production issues for long videos:
  - missing translations in some batches
  - timecode misalignment after translation
  - inconsistent terminology across batches
