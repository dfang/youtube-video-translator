# Setup and Integration

## System Requirements

- **FFmpeg with libass**: Required for hardcoding subtitles.
- **macOS Recommendation**: Install `ffmpeg-full` via Homebrew to ensure all capabilities are present:
  ```bash
  brew install ffmpeg-full
  brew link ffmpeg-full
  ```
- **Fallback**: The skill will attempt to find `ffmpeg-full` or `ffmpeg` with `libass` support automatically. If environment check fails, follow the suggested fix commands.

## Host Setup

- The skill can run from the repo checkout directly; all Python scripts resolve their own root from `__file__`.
- Installed copies normally live at `$HOME/.agents/skills/youtube-video-translator`.
- Claude Code integration: symlink to `$HOME/.claude/skills/youtube-video-translator`.
- OpenClaw integration: symlink to `$HOME/.openclaw/skills/youtube-video-translator`.
- Gemini CLI integration: link the local path with `gemini skills link /absolute/path/to/youtube-video-translator --scope user --consent`.
- If more than one host CLI is installed on the same machine, set `TRANSLATION_RUNNER` explicitly so Phase 4 does not guess the wrong runner.
