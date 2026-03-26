---
name: YouTube-Video-Translator
description: 自动翻译 YouTube 视频。它支持下载视频、使用 WhisperX 转录（若无字幕）、调用 LLM 翻译、生成 TTS 配音，并最终使用 FFmpeg 合成。当用户说“翻译视频”或“翻译这个视频 [URL]”时触发。
---

# YouTube-Video-Translator

该 Skill 实现了 YouTube 视频的全自动翻译、转录、配音和合成流程。

## 触发场景

- 用户指令包含“翻译视频”或“翻译这个视频”。
- 用户提供了 YouTube 链接（例如 `https://www.youtube.com/watch?v=...`）。
- 可选修饰词：“清理”、“英文原音”、“双语字幕”。

## 工作流 (状态驱动/断点续传)

本 Skill 采用“项目制”管理。所有文件存储在 `./translations/[Video_ID]/` 下。在执行每一步前，请先检查相关文件是否已存在。

### 1. 准备阶段 (Setup)

- 解析 YouTube URL 获取 `Video_ID`。
- 创建目录结构：`./translations/[Video_ID]/temp/`。

### 2. 下载阶段 (Downloader)

- **目标**: 下载原始视频。
- **状态检查**: 检查 `./translations/[Video_ID]/temp/raw_video.mp4` 是否存在。
- **执行**: 调用 `scripts/downloader.py [URL] [OutputDir]`。

### 3. 字幕阶段 (Subtitle Processor)

- **目标**: 获取源文字幕并翻译成中文。
- **状态检查**: 检查 `./translations/[Video_ID]/temp/bilingual.ass` 是否存在。
- **执行逻辑**:
  1. 尝试使用 `yt-dlp --write-subs` 下载官方英文字幕。
  2. 若无官方字幕，运行 `scripts/whisperx_transcriber.py` 进行转录。
  3. 获取英文字幕后，调用 **LLM (Anthropic/OpenAI)** 将内容翻译为中文。
  4. **强制要求**: 翻译后必须生成符合以下标准的 `.ass` 文件：
     - 英文在上，中文在下。
     - 字体大小都为16，颜色白色。
     - 格式模板请参考 `references/ass_template.txt`。

### 4. 配音阶段 (Voiceover Engine)

- **目标**: 生成中文配音音频。
- **状态检查**: 检查 `./translations/[Video_ID]/temp/zh_voiceover.mp3` 是否存在。
- **默认逻辑**: 默认为“中文配音”，除非用户明确要求“英文原音”。
- **执行**: 调用 `scripts/voiceover_tts.py [zh_translated.srt]`。

### 5. 合成阶段 (Video Composer)

- **目标**: 合成视频、配音与字幕。
- **状态检查**: 检查 `./translations/[Video_ID]/final/final_video.mp4` 是否存在。
- **执行**: 调用 `scripts/video_muxer.py`。

### 6. 发布阶段 (Bilibili Publisher)

- **触发条件**: 用户提及“发布到B站”、“投稿”或“保存草稿”。
- **目标**: 通过浏览器自动化将成品发布至 Bilibili 创作中心。
- **执行逻辑**:
  1. **准备元数据**:
     - Claude 结合翻译内容与 `info.json`，生成符合 B站调性的标题、详细简介和 Tags。
     - 识别合适的分区（如：科技/医学）。
  2. **启动浏览器代理**:
     - 激活 `agent-browser` 技能。
     - 导航至 `member.bilibili.com/platform/upload/video/frame`。
  3. **UI 交互流程**:
     - 自动选取并上传 `./translations/[Video_ID]/final/final_video.mp4`。
     - 填写标题、简介、标签及分区。
     - 根据指令：点击“立即投稿”或“保存草稿”。

### 7. 清理阶段 (Cleaner)

- **条件**: 仅当用户明确提到“清理”时执行。
- **执行**: 调用 `scripts/cleaner.py` 删除 `temp/` 文件夹。

## 技术规范

- **运行环境**: macOS (Mac mini M4)。
- **翻译准则**: 翻译时必须结合视频标题和描述作为 Context，严禁使用 Google Translate。
- **FFmpeg 指令**: 必须确保音频视频同步，无丢帧。

## 故障处理

如果执行中途报错（如 API 超时），告知用户错误原因。用户修复后再次输入指令，Skill 将自动从断点处继续执行，不会重复下载。
