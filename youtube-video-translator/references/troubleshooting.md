# Troubleshooting and Error Handling

## Resuming After Interruption

On re-entry, always start with:

```bash
python3 "[SKILL_ROOT]/scripts/state_manager.py" [VIDEO_ID] load
```

Then run `phase_runner.py` without specifying phase — it will auto-resume from `current_phase`:

```bash
python3 "[SKILL_ROOT]/scripts/phase_runner.py" run --video-id [VIDEO_ID]
```

If a previous attempt failed:

- Inspect `temp/<phase>_error.json` and `temp/validation_errors.json` first.
- Do not delete successful artifacts just to retry.
- Clear only the relevant error state, or use `phase_runner.py cleanup --phase N` if that subcommand is available.
- For translation failures, prefer retrying only `status=failed` chunks.

## Error Handling Rules

- Each phase script should write `temp/<phase>_error.json` on unrecoverable failure with at least: `script`, `phase`, `error`, `timestamp`.
- Validation failures should write `temp/validation_errors.json` and block the pipeline from entering align/export or later phases.
- Temporary network/IO failures may retry briefly inside the script, but final failure must be persisted as an error artifact rather than silently swallowed.
- Cleanup must not remove static schemas or unrelated completed artifacts.
