---
name: YouTube-Video-Translator
description: Automatically translate YouTube videos. It supports downloading videos, transcribing with WhisperX (if no subtitles), calling an LLM for translation, generating TTS voiceovers, and finally compositing with FFmpeg. Triggered when the user says "translate video" or "translate this video [URL]".
---

# YouTube-Video-Translator

This Skill implements a fully automated workflow for YouTube video translation, transcription, voiceover, and composition, publish to bilibili.

## Trigger Scenarios

- User instructions containing "translate video" or "translate this video".
- User provides a YouTube link (e.g., `https://www.youtube.com/watch?v=...`).
- Optional modifiers: "clean", "original audio", "bilingual subtitles".
- 翻译视频 或者 翻译这个视频 或者 搬运视频 或者 搬运这个视频

## Workflow (State-driven / Breakpoint Resumption)

This Skill uses a "project-based" management approach. All files are stored under `./translations/[Video_ID]/`.

**Mandatory Procedure**: Before starting each phase, you must inform the user in Chinese about the phase currently being entered (e.g., "正在进入下载阶段...").

Before executing each step, check if the relevant files already exist.

1. Gathering user intents
2. Setup basic file structure
3. Donwload video from youtube
4. Process subtitles
5. Generate voiceover
6. Compose video
7. Publish to Bilibili
8. Clean up

### 1. Gathering intents Phase

Ask user in Chinese, and print user intents in Chinese:

- keep original audio (default) or dub to chinese
- download subtitle or transcribe subtitle
- bilingual subtitles or chinese subtitle only (default)
- publish to Bilibili (default)
- clean up or not (default)

**Confirmation Step**: After gathering and summarizing all intents, you **MUST** ask the user if they are ready to proceed (e.g., "确认开始翻译吗？") and wait for their confirmation before moving to the Setup Phase.

### 2. Setup Phase

- Parse the YouTube URL to obtain the `Video_ID`.
- Create the directory structure: `./translations/[Video_ID]/temp/`.
- If raw_video.mp4 exists, skip this phase, inform user that the video is already downloaded, go to subtitle processing phase.

### 3. Video Downloading Phase

- **Goal**: Download the original video.
- **Status Check**: Check if `./translations/[Video_ID]/temp/raw_video.mp4` exists.
- **Execution**: Call `scripts/downloader.py [URL] [OutputDir]`.

### 4. Subtitle Processing Phase

- **Goal**: Obtain source subtitles and translate them into Chinese according to user intent.
- **Status Check**: Check if `./translations/[Video_ID]/temp/bilingual.ass` or `./translations/[Video_ID]/temp/chinese_only.ass` exists.
- **Execution Logic**:
  1. **Source Selection**:
     - If user intent is **Download**: Attempt to download official subtitles using `yt-dlp --write-subs`. Fall back to transcription only if download fails and user permits.
     - If user intent is **Transcribe**: Run `scripts/whisperx_transcriber.py` directly.
  2. **Translation**: Call **LLM (Anthropic/OpenAI)** to translate the English content into Chinese, using the video title and description as context.
  3. **Output Generation**:
     - **Bilingual (English/Chinese)**: Generate a `.ass` file with English on top and Chinese on bottom.
     - **Chinese Only**: Generate a `.ass` file with only Chinese text.
  4. **Mandatory Requirement**:
     - Font size 16, color white.
     - **Line Length Management**: If a translated line is too long (e.g., >20 Chinese characters or >40 English characters), use `\N` for a manual line break or request the LLM to split the content into two shorter, balanced lines.
     - Refer to `references/ass_template.txt` for the format template.

### 5. Voiceover Engine Phase

- **Goal**: Generate Chinese voiceover audio.
- **Status Check**: Check if `./translations/[Video_ID]/temp/zh_voiceover.mp3` exists.
- **Execution Logic**:
  - **Skip Condition**: If the user intent is "keep original audio", skip this phase entirely and use the original audio track during composition.
  - **Default**: Defaults to "Chinese voiceover" unless the user explicitly requests "original audio".
  - **Execution**: Call `scripts/voiceover_tts.py [zh_translated.srt]`.

### 6. Video Composer Phase

- **Goal**: Composite video, voiceover, and subtitles.
- **Status Check**: Check if `./translations/[Video_ID]/final/final_video.mp4` exists.
- **Execution**: Call `scripts/video_muxer.py`.

### 7. Bilibili Publisher Phase

- **Trigger Condition**: User mentions "publish to Bilibili", "post", or "save draft".
- **Goal**: Publish the final product to the Bilibili Creator Center via browser automation.
- **Execution Logic**:
  1. **Prepare Metadata**:
     - Claude combines translated content with `info.json` to generate a title, detailed description, and tags matching Bilibili's style.
     - Identify the appropriate category (e.g., Technology/Medicine).
  2. **Launch Browser Proxy**:
     - Activate the `agent-browser` skill.
     - Navigate to `member.bilibili.com/platform/upload/video/frame`.
  3. **UI Interaction Flow**:
     - Automatically select and upload `./translations/[Video_ID]/final/final_video.mp4`.
     - Fill in the title, description, tags, and category.
     - Based on instructions: Click "Post Now" or "Save Draft".

### 8. Cleaner Phase

- **Condition**: Execute only if the user explicitly mentions "clean".
- **Execution**: Call `scripts/cleaner.py` to delete the `temp/` folder.

## Technical Specifications

- **Operating Environment**: macOS (Mac mini M4).
- **Translation Guidelines**: Translation must incorporate the video title and description as context; using Google Translate is strictly prohibited.
- **FFmpeg Commands**: Must ensure audio and video synchronization with no dropped frames.

## Troubleshooting

- **Breakpoint Resumption**: If an error occurs mid-execution (e.g., API timeout), inform the user of the cause. Once the user fixes the issue and re-issues the command, the Skill will automatically resume from the breakpoint without re-downloading.
- **Manual Phase Selection**: If the process is interrupted or fails, the user can explicitly instruct the Skill to start from a specific phase (e.g., "Start from Voiceover Phase") to skip previous steps or re-run a specific part of the workflow.
