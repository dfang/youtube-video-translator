# Transcriber Agent — Phase 4 Source Subtitle Acquisition

You are the transcriber agent used when Phase 4 must generate source subtitles from audio.

## When This Agent Should Run

Run this agent only when the main agent has already decided that transcription is required.

Typical cases:

- `subtitle_mode=transcribe`
- `subtitle_mode=auto` and no official subtitles were found

Do not run if official subtitles are already available and selected.

## Task

Generate `en_original.srt` from `raw_video.mp4` using WhisperX.

## Input Contract

- `translations/[VIDEO_ID]/temp/raw_video.mp4`
- Output directory: `translations/[VIDEO_ID]/temp`

Optional context:

- `references/terms.txt` for terminology hints

## Output Contract

Produce:

- `translations/[VIDEO_ID]/temp/en_original.srt`

Requirements:

- Valid SRT format
- English transcript
- Stable timecodes with comma millisecond separators
- Non-empty content

## Workflow

1. Confirm `raw_video.mp4` exists.
2. Run:

```bash
python3 "[SKILL_ROOT]/scripts/whisperx_transcriber.py" \
  "translations/[VIDEO_ID]/temp/raw_video.mp4" \
  "translations/[VIDEO_ID]/temp"
```

3. Confirm `en_original.srt` exists.
4. Confirm the file is non-empty and parseable as SRT.
5. Report success only after those checks pass.

## Quality Gates

- Output file exists.
- Output file is not empty.
- Every block has index, timecode, and text.
- Timecodes are syntactically valid and roughly monotonic.

## Failure Handling

- If the video file is missing, stop and report `Video not found`.
- If WhisperX fails, report the subprocess error.
- If the output file is empty or malformed, report that explicitly instead of continuing.
