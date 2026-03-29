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

1. Gather user intents
2. Setup basic file structure
3. Donwload video from youtube
4. Process subtitles
5. Generate voiceover
6. Process cover
7. Compose video
8. Publish to Bilibili
9. Clean up

### 1. Gathering intents Phase

Ask user in Chinese, and print user intents in Chinese:

- keep original audio (default) or dub to chinese
- download subtitle or transcribe subtitle
- bilingual subtitles or chinese subtitle only (default)
- publish to Bilibili (default)
- clean up or not (default)
- **Localized Title Confirmation**: Propose 2-3 short, catchy Chinese titles for the video and cover based on the original metadata. Ask the user to select one or provide a custom one.

**Confirmation Step**: After gathering and summarizing all intents (including the chosen Chinese title), you **MUST** ask the user if they are ready to proceed (e.g., "确认开始翻译吗？") and wait for their confirmation before moving to the Setup Phase.

### 2. Setup Phase

- Print user intents in Chinese
- Parse the YouTube URL to obtain the `Video_ID`.
- Create the directory structure: `./translations/[Video_ID]/temp/`.
- **Traceability**: Save the original YouTube URL into `./translations/[Video_ID]/temp/url.txt`.
- If raw_video.mp4 exists, skip this phase, inform user that the video is already downloaded, go to subtitle processing phase.

### 3. Video Downloading Phase

- **Goal**: Download the original video.
- **Status Check**: Check if `./translations/[Video_ID]/temp/raw_video.mp4` exists.
- **Execution**: Call `scripts/downloader.py [URL] [OutputDir]`.

### 4. Subtitle Processing Phase

- **Goal**: Obtain source subtitles and translate them into Chinese with high precision and visual comfort.
- **Status Check**: Check if `./translations/[Video_ID]/temp/bilingual.ass` exists.
- **Execution Logic**:
  1. **Source Selection**:
     - If user intent is **Download**: Attempt `yt-dlp --write-subs`. Fall back to transcription if failed.
     - If user intent is **Transcribe**: Run `scripts/whisperx_transcriber.py`.
  2. **Segmentation Audit (Mandatory Pre-translation)**:
     - Run `scripts/subtitle_splitter.py` on the raw SRT.
     - **Thresholds**: Any segment with `Duration > 8.0s` must be split into multiple segments of ~5s.
     - **Goal**: Prevent LLM from producing massive text blocks and ensure visual comfort.
  3. **Context & Glossary Pre-process (Mandatory)**:
     - Extract key medical/technical terms from `info.json` title and description.
     - Create a **Local Glossary** (e.g., "VILI -> 呼吸机诱导的肺损伤", "PEEP -> 呼气末正压") to prime the LLM.
  4. **Batch Translation Strategy (For Videos > 10 mins)**:
     - **Constraint**: To prevent LLM context truncation or file write limits, subtitles MUST be translated in batches of ~50 segments.
     - **Verification**: After each batch, verify the line count matches the source segment count.
  5. **Translation Guidelines**:
     - **Acronym Preservation**: Keep critical acronyms (e.g., PEEP, ARDS) but provide Chinese explanation on first appearance.
     - **Conciseness (CPS Control)**: If Reading Speed (CPS) > 15 chars/sec, LLM must summarize or condense.
  6. **Physical Splitting & Formatting (Strict Enforcement)**:
     - **Hard Split (Time)**: Any segment > 8 seconds MUST be logically split into multiple chronological segments (e.g., a 20s segment should be split into 4-5 sub-segments).
     - **Hard Split (Length)**: Any single line > 25 Chinese characters MUST be split into two separate chronological segments OR use `\N` for a manual break if the duration is short.
     - **Readability (CPS Control)**: Maintain a target Reading Speed (CPS) of 10-15 chars/sec. If the translation is too long for the given duration, the LLM MUST summarize or use professional paraphrasing to shorten the text while preserving the core medical meaning.
     - **Visual Balance**: Always use English on top and Chinese on bottom via `\N`. Font size 14-16, color white.
  7. **Consistency Check**: Final `.ass` must be scanned for any remaining untranslated English lines or sequence gaps.

### 5. Voiceover Engine Phase

- **Goal**: Generate Chinese voiceover audio.
- **Status Check**: Check if `./translations/[Video_ID]/temp/zh_voiceover.mp3` exists.
- **Execution Logic**:
- **Skip Condition**: If the user intent is "keep original audio", skip this phase entirely.
- **Audio Alignment (Speed-to-Fit)**: If the generated TTS duration exceeds the original segment duration, the script must automatically speed up the audio (using FFmpeg `atempo` or TTS engine parameters) up to a maximum of 1.25x.
- **Execution**: Call `scripts/voiceover_tts.py [zh_translated.srt]`.

### 6. Cover Process Phase

- **Goal**: Generate a high-quality localized cover image using the title confirmed in Phase 1.
- **Status Check**: Check if `./translations/[Video_ID]/final/cover_final.jpg` exists.
- **Execution Logic**:
  1. **Source Extraction**: Attempt to download the highest resolution thumbnail from YouTube. If restricted, extract a keyframe from `raw_video.mp4` at approximately 30 seconds.
  2. **Localized Design**: Call `scripts/cover_generator.py` using the confirmed Chinese title.
     - **Output Destination**: The resulting image MUST be saved as `./translations/[Video_ID]/final/cover_final.jpg`.
     - The script must automatically calculate optimal font sizes to prevent text overflow.
     - Add a semi-transparent dark overlay to ensure text readability.
     - Position the title and speaker information in the vertical center for optimal visual balance.
  3. **Verification**: Ensure the final image is 16:9 and saved as `cover_final.jpg`.

### 7. Video Composer Phase

- **Goal**: Composite video, voiceover, and subtitles.
- **Status Check**: Check if `./translations/[Video_ID]/final/final_video.mp4` exists.
- **Execution**: Call `scripts/video_muxer.py`.
- **Metadata (Optional)**: If a localized cover exists, attach it as the video's thumbnail using FFmpeg's `attached_pic` disposition.

### 8. Bilibili Publisher Phase

... (rest of the file)

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
