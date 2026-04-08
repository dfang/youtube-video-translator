# Changelog

## v2.0.0 — Pipeline Refactor (State-Driven Orchestrator)

### Architecture

- Refactored from monolithic Phase 3/4 into atomic, state-driven pipeline
- Each step reads from and writes to `temp/` JSON artifacts
- Orchestrator (`phase_runner.py`) calls atomic scripts; no more implicit state
- **Breaking**: Phase 3/4 internal behavior changed; `phase_runner.py` CLI unchanged

### Phase 3 Changes

- Split into 3 independent scripts:
  - `phase_3_metadata_probe.py` — yt-dlp → `temp/metadata.json`
  - `phase_3_caption_discovery.py` — decision: official vs ASR → `temp/caption_plan.json`
  - `phase_3_video_download.py` — video download → `temp/raw_video.mp4`
- All scripts are idempotent (skip if output fresh)

### Phase 4 Changes

- Split into 6 atomic steps:
  - `phase_4_caption_fetch.py` — official caption → `temp/source_segments.json`
  - `phase_4_asr.py` + `phase_4_asr_normalize.py` — ASR → `temp/asr_segments.json` → `temp/source_segments.json`
  - `phase_4_chunk_build.py` — chunking → `temp/chunks.json`
  - `phase_4_translate_scheduler.py` — parallel subagent translation (default parallelism: 4)
  - `phase_4_validator.py` — batch validation → `temp/validation_errors.json`
  - `phase_4_align.py` + `phase_4_export.py` — → `temp/subtitle_manifest.json` + `.ass`
- **New artifacts**: `source_segments.json`, `chunks.json`, `translation_state.json`, `subtitle_manifest.json`, `asr_segments.json`
- Glossary injection: place `temp/glossary.json` before Phase 4; merged into each chunk's `glossary_terms`
- Single chunk failure: only that chunk retries; others unaffected
- Provider abstraction: `providers/base.py` defines `TranslatorProvider` interface

### Phase 5 (Voiceover) Changes

- Now consumes `temp/subtitle_manifest.json` (canonical translated segments)

### Phase 9 (Publish) Changes

- Explicit `draft` vs `formal` path
- `draft` mode: skip Bilibili upload, confirm preview available
- `formal` mode: full Bilibili publish via `agent-browser` skill
- Missing `final_video.mp4` now fails immediately (was silent before)

### Documentation

- `schemas/` — 7 JSON Schema files for all intermediate artifacts
- `SKILL.md` — updated Phase 3/4 descriptions and new architecture overview
- `providers/base.py` — provider interface definitions

## v1.x — Legacy

See git history for pre-refactor changelog.
