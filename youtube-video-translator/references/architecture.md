# Architecture and Artifacts

## Architecture

This skill is the **single orchestrator entrypoint**. It does not rely on physically nested child skills.

- Use `scripts/phase_runner.py` as the only stable execution entrypoint.
- Internally, the runner calls atomic scripts for metadata, caption discovery, audio extraction, ASR, chunking, translation, alignment, export, TTS, mux, preview upload, and publish.
- When parallel translation is needed, delegate chunk work to subagents; do not invent a second top-level CLI or a nested skill tree.
- Subagent dispatch must not assume a single host runtime. Use `TRANSLATION_RUNNER=claude|gemini|openclaw` for explicit host binding, or `TRANSLATOR_SUBAGENT_CMD` for a fully custom runner.
- Keep the orchestration rule simple: phase state lives on disk, atomic steps read/write canonical artifacts, and retries target the smallest failed unit.

## Canonical Paths

- Skill root: `[SKILL_ROOT]` (repo checkout or installed skill directory)
- Root: `./translations/[VIDEO_ID]/` (Created in the project's current working directory)
- State: `./translations/[VIDEO_ID]/.phase-state.json`
- Runtime artifacts: `./translations/[VIDEO_ID]/temp/`
- Final outputs: `./translations/[VIDEO_ID]/final/`
- Static schemas: `[SKILL_ROOT]/references/schemas/`

## Static Contracts vs Runtime State

- `references/schemas/` stores repo-owned JSON schema files for canonical artifacts.
- `translations/[VIDEO_ID]/temp/` stores runtime artifacts only.
- Do not write static contracts, templates, or repo-owned metadata into per-video `temp/`.

## Subagent Contract (Chunk Translation)

When delegating chunk translation to a subagent:

1. Pass the agent definition: `agents/translator.md`
2. Pass video_id, chunk_id, and paths as arguments
3. Wait for completion and verify `chunk_N.translated.txt` exists
4. On failure, report back — orchestrator handles retry

Example subagent launch:

```
Runner: TRANSLATION_RUNNER=claude|gemini|openclaw
Task: Translate chunk N for video abc123
Agent definition: [SKILL_ROOT]/agents/translator.md
Input: chunk_N.prompt.txt in translations/abc123/temp/
Expected output: chunk_N.translated.txt in translations/abc123/temp/
```

## State-Driven Artifact Map

The pipeline is **state-driven**: each step reads from and writes to `temp/` JSON artifacts.

- `temp/metadata.json` — video metadata (Phase 3)
- `temp/intent.json` — user intent choices validated by `references/schemas/intent.schema.json` (Phase 1)
- `temp/caption_plan.json` — caption path decision (Phase 3)
- `temp/source_audio.wav` — canonical extracted audio for ASR (Phase 4, ASR path)
- `temp/source_segments.json` — normalized subtitle segments (Phase 4)
- `temp/asr_segments.json` — raw ASR output (Phase 4, ASR path)
- `temp/chunks.json` — per-chunk translation status (Phase 4)
- `temp/glossary.json` — optional user-provided术语表 (Phase 4)
- `temp/translation_state.json` — translation contract + cache (Phase 4)
- `temp/subtitle_manifest.json` — canonical translated segments (Phase 4)
- `temp/bilingual.ass` / `temp/zh_only.ass` — subtitle files (Phase 4)

All intermediate artifacts are idempotent: rerunning any step skips if output already exists and the translation contract still matches.
