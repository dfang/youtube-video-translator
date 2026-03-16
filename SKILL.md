# YouTube Video Translator / YouTube 视频翻译

专业级 YouTube 视频翻译工具，自动下载视频、翻译字幕、克隆声音配音，输出中文配音视频。

## 触发条件

当用户提到以下内容时自动触发：

- `/yt-translate` 命令后跟 YouTube 链接
- "翻译这个视频" + YouTube 链接
- "youtube 翻译"、"视频翻译"、"yt 翻译"
- "把 youtube 视频翻译成中文"
- 直接发送 YouTube 链接并提到翻译相关关键词

## 核心流程

### 1. 下载模块 (download.sh)

- 使用 `yt-dlp` 下载 YouTube 视频（最高画质 + 最佳音质）
- 自动下载多语言字幕（英文、简体中文）
- 提取音频用于声音克隆
- 支持从 Chrome 浏览器读取 Cookie 以绕过限制

### 2. 字幕处理模块 (transcribe.sh)

- 自动检测并转换字幕格式（VTT → SRT）
- 使用 Google Translate API 逐句翻译字幕
- 保留原字幕时间轴
- 输出双语 SRT 字幕文件
- **字幕来源选项**：
  - `download`（默认）：下载 YouTube 英文字幕，使用 yt-dlp 下载原始字幕（无逐词高亮）
  - `whisper`：使用 Whisper/faster-whisper 本地转录（无高亮，时间轴干净，质量更高）

### 3. 配音生成模块 (dub.sh)

- **edge-tts TTS**: 使用 Microsoft Edge TTS 生成高质量配音
- **分段生成**：按字幕时间轴逐句生成 TTS 音频
- **语速匹配**：自动匹配原视频语速和停顿
- **元数据记录**：生成 voice-map.json 记录每个音频片段的时间信息

### 4. 视频合成模块 (merge.sh)

- 合并所有 TTS 音频片段
- 将中文配音与原始视频合成
- 自动嵌入中文字幕（可选）
- 输出最终 MP4 视频文件

### 5. 清理模块 (cleanup.sh)

- 可选清理中间文件
- 保留最终输出视频和字幕

## 特色功能

### 🎙️ edge-tts TTS

- 免费无需 API 密钥
- 无速率限制，快速生成
- 支持 30+ 语言的高质量语音
- 本地生成，隐私安全

### ⚡ MPS 加速

- Mac M 系列芯片自动启用 Metal Performance Shaders
- 音频分析和转录获得硬件加速

### 📹 高质量输出

- 保留原始视频画质（1080p/4K）
- AAC 音频编码
- 可选嵌入软字幕

### 🛡️ 容错策略

- 单步失败时尝试降级方案
- 字幕下载失败时提示但继续
- 声音克隆失败时切换预设声音
- 输出部分可用结果

## 使用方法

### 基本用法

```bash
/yt-translate https://www.youtube.com/watch?v=VIDEO_ID
```

### 带参数

```bash
# 清理中间文件
/yt-translate <URL> --cleanup

# 指定目标语言（默认中文）
/yt-translate <URL> --lang ja  # 翻译成日语

# 字幕类型：仅中文（默认）或中英文双语
/yt-translate <URL> --subtitles chinese      # 仅中文字幕（默认）
/yt-translate <URL> --subtitles bilingual    # 中英文双语字幕

# 字幕来源：下载英文字幕（默认）或使用 Whisper 本地转录
/yt-translate <URL> --subtitle-source download   # 下载 YouTube 英文字幕（默认，无逐词高亮）
/yt-translate <URL> --subtitle-source whisper    # 使用 Whisper 重新生成字幕（质量更高，时间轴干净）
```

Whisper 模式需要先安装：
```bash
# 标准 Whisper（较慢）
pip install openai-whisper

# Faster-Whisper（推荐，速度更快）
pip install faster-whisper
```

## 环境变量

无需 API 密钥，edge-tts 完全免费使用。

## 输出文件

默认保留所有中间文件：

| 文件后缀                | 说明                     |
| ----------------------- | ------------------------ |
| `*.original.mp4`        | 原始视频                 |
| `*.en.vtt` / `*.en.srt` | 英文字幕                 |
| `*.zh-CN.srt`           | 中文字幕（仅中文）       |
| `*.en.only.srt`         | 英文字幕（仅英文，双语模式生成） |
| `*.audio.mp3`           | 原音频                   |
| `*.voice-map.json`      | 配音元数据               |
| `*.zh-CN.merged.mp3`    | 合并后的中文配音         |
| `*.zh-CN.final.mp4`     | 最终输出视频（含配音 + 硬烧字幕）   |
| `subtitles.ass`         | ASS 格式字幕（用于硬烧） |

**注意**：最终输出视频 `*.zh-CN.final.mp4` 已硬烧入字幕，可在 QuickTime Player 等任何播放器直接显示字幕。

## 依赖

- `yt-dlp` - YouTube 视频下载
- `ffmpeg` - 视频/音频处理
- `HandBrakeCLI` - 硬烧字幕（可选）
- Python 3.10+
- Python 包：`edge-tts`, `requests`

## 配置参数 (config/default.json)

```json
{
  "edge-tts": {
    "default_voice": "zh-CN-XiaoxiaoNeural",
    "voice_mapping": {
      "zh-CN": "zh-CN-XiaoxiaoNeural",
      "zh-HK": "zh-HK-HiuMaanNeural",
      "zh-TW": "zh-TW-HsiaoChenNeural",
      "ja": "ja-JP-NanamiNeural",
      "ko": "ko-KR-SunHiNeural",
      "en": "en-US-JennyNeural",
      "es": "es-ES-ElviraNeural",
      "fr": "fr-FR-DeniseNeural",
      "de": "de-DE-KatjaNeural"
    }
  },
  "translation": {
    "target_language": "zh-CN",
    "subtitle_max_chars": 4000
  },
  "download": {
    "video_format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    "subtitle_languages": ["en", "zh-Hans", "zh-Hant"],
    "cookies_from_browser": "chrome"
  }
}
```

## 错误处理

采用容错策略（策略 B）：

- 单步失败时尝试降级方案
- 输出部分可用结果
- 详细错误日志便于调试

## 技术细节

### edge-tts TTS 生成

1. 解析 SRT 字幕文件获取时间轴和文本
2. 按目标语言选择预设语音（如 zh-CN-XiaoxiaoNeural）
3. 调用 edge-tts CLI 逐句生成音频片段
4. 生成 voice-map.json 记录片段映射
5. 使用 ffmpeg 合并所有音频片段

### 字幕翻译

- 使用 Google Translate 免费 API
- 自动检测源语言
- 逐句翻译保留时间轴
- 速率限制避免请求过快

### 视频合成

- 视频流直接复制（无重编码）
- 音频重新编码为 AAC
- 可选使用 ffmpeg 烧录字幕
