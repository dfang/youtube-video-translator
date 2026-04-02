# Changelog

## 2026-04-02

### Added
- Added `check-batches` command in `youtube-video-translator/scripts/translate_worker.py` to detect missing/extra translated batch files before merge.
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
  1. `prepare`
  2. per-batch translation
  3. `check-batches`
  4. `merge`
  5. strict `verify`
- Updated `verify` behavior in `youtube-video-translator/scripts/translate_worker.py` to return non-zero exit code on integrity failures.

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
